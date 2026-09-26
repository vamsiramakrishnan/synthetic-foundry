"""KQL (Microsoft Search, SharePoint) to the common filter tree.

Supported: free-text terms (all must match), ``"quoted phrases"``, suffix
wildcards (``budg*``), property restrictions ``prop:value`` (contains, token
wise), ``prop=value``, ``prop<>value`` and ``prop>``/``>=``/``<``/``<=`` on
dates and numbers; date values ``2026-09-01``, ``2026-09-01T10:00:00Z`` and the
intervals ``today``, ``yesterday``, ``"this week"``, ``"this month"``, ``"last
month"``, ``"this year"``, ``"last year"``; ``AND``, ``OR``, ``NOT`` (upper
case only; lower case is a search term, as in KQL), ``-term`` and ``+term``,
implicit ``AND`` between adjacent terms, and parentheses.

As SharePoint does, a restriction on a property the index does not know is not
an error: ``colour:blue`` becomes the free-text term ``colour:blue`` at binding.
Only a malformed query (an unclosed quote or parenthesis) is refused.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from .ast import (
    Compare,
    Node,
    Not,
    Op,
    Query,
    TextMatch,
    TimeWindow,
    conjoin,
    disjoin,
)
from .clock import aware, parse_instant, window
from .lexer import EOF, Cursor, Token, tokenize, unquote
from .soql import range_condition

LANGUAGE = "kql"

_TOKENS = (
    ("string", r'"(?:[^"\\]|\\.)*"'),
    ("lparen", r"\("),
    ("rparen", r"\)"),
    ("op", r"<>|>=|<=|:|=|>|<"),
    ("prefix", r"[+-](?=[^\s()])"),
    ("word", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})?"),
    ("word", r"[^\s()\":<>=]+"),
)
_INTERVALS = {
    "today": ("day", 0), "yesterday": ("day", -1),
    "this week": ("week", 0), "last week": ("week", -1),
    "this month": ("month", 0), "last month": ("month", -1),
    "this year": ("year", 0), "last year": ("year", -1),
}
_OPS = {":": Op.EQ, "=": Op.EQ, "<>": Op.NE, ">": Op.GT, ">=": Op.GE, "<": Op.LT, "<=": Op.LE}


class _Parser:
    def __init__(self, text: str, clock: datetime) -> None:
        self.cursor = Cursor(LANGUAGE, text, tokenize(LANGUAGE, text, _TOKENS))
        self.clock = aware(clock)

    def keyword(self, word: str, offset: int = 0) -> bool:
        token = self.cursor.peek(offset)
        return token.kind == "word" and token.text == word

    def parse(self) -> Query:
        if self.cursor.at(EOF):
            return Query(language=LANGUAGE)
        where = self.or_expr()
        if not self.cursor.at(EOF):
            self.cursor.fail("unexpected token")
        return Query(language=LANGUAGE, where=where)

    def or_expr(self) -> Node:
        items = [self.and_expr()]
        while self.keyword("OR"):
            self.cursor.next()
            items.append(self.and_expr())
        return disjoin(items)

    def and_expr(self) -> Node:
        items = [self.unary()]
        while not self.cursor.at(EOF) and not self.cursor.at("rparen") and not self.keyword("OR"):
            if self.keyword("AND"):
                self.cursor.next()
            items.append(self.unary())
        return conjoin(items)

    def unary(self) -> Node:
        cursor = self.cursor
        if self.keyword("NOT"):
            cursor.next()
            return Not(self.unary())
        prefix = cursor.accept("prefix")
        if prefix is not None:
            inner = self.unary()
            return Not(inner) if prefix.text == "-" else inner
        return self.primary()

    def primary(self) -> Node:
        cursor = self.cursor
        if cursor.accept("lparen"):
            inner = self.or_expr()
            if not cursor.accept("rparen"):
                cursor.fail("unbalanced parenthesis")
            return inner
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            return TextMatch(None, unquote(token), "phrase", at=token.at, raw=token.text)
        if token.kind != "word":
            cursor.fail("unexpected token")
        cursor.next()
        if cursor.at("op"):
            return self.restriction(token)
        return TextMatch(None, token.text, "terms", at=token.at, raw=token.text)

    def restriction(self, name: Token) -> Node:
        cursor = self.cursor
        symbol = cursor.next().text
        value_token = cursor.peek()
        if value_token.kind not in ("word", "string"):
            cursor.fail("missing property value")
        cursor.next()
        quoted = value_token.kind == "string"
        value = unquote(value_token) if quoted else value_token.text
        raw = self.cursor.text[name.at:value_token.at + len(value_token.text)]
        field = name.text
        op = _OPS[symbol]
        span = self.window(value)
        if span is not None:
            return range_condition(field, op, *span, at=name.at, raw=raw) if op is not Op.EQ else TimeWindow(field, *span, at=name.at, raw=raw)
        instant = parse_instant(value, self.clock.tzinfo)  # type: ignore[arg-type]
        if instant is not None:
            return Compare(field, op, instant, at=name.at, raw=raw)
        if symbol == ":":
            return TextMatch(field, value, "phrase" if quoted else "terms", at=name.at, raw=raw)
        number: int | float | str = value
        try:
            number = float(value) if "." in value else int(value)
        except ValueError:
            number = value
        return Compare(field, op, number, at=name.at, raw=raw)

    def window(self, value: str) -> tuple[datetime, datetime] | None:
        interval = _INTERVALS.get(value.casefold())
        if interval is not None:
            return window(interval[0], self.clock, interval[1])
        if len(value) == 10:
            day = parse_instant(value, self.clock.tzinfo)  # type: ignore[arg-type]
            if day is not None:
                return day, day + timedelta(days=1)
        return None


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one KQL string. Only a malformed query is refused."""

    return _Parser(text, clock).parse()


__all__ = ["LANGUAGE", "parse"]
