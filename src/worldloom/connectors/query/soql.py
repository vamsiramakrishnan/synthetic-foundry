"""SOQL (Salesforce) to the common filter tree.

Supported: ``SELECT f1, f2, Rel.Field FROM Object [WHERE ...] [ORDER BY f
[ASC|DESC] [NULLS FIRST|LAST], ...] [LIMIT n] [OFFSET n]``. Conditions:
``= != <> < <= > >=``, ``LIKE`` (``%`` and ``_``), ``[NOT] IN (..)``,
``INCLUDES (..)``/``EXCLUDES (..)`` on multi-select values (``'a;b'`` means
both), ``AND``/``OR``/``NOT`` with parentheses. As in Salesforce, ``AND`` and
``OR`` cannot be mixed at one level without parentheses. Literals: strings,
numbers, ``true``/``false``/``null``, dates (``2026-09-01``, a whole day),
datetimes (``2026-09-01T10:00:00Z``) and the date literals ``TODAY``,
``YESTERDAY``, ``TOMORROW``, ``{LAST,THIS,NEXT}_{WEEK,MONTH,QUARTER,YEAR}``,
``LAST_90_DAYS``, ``NEXT_90_DAYS``, ``{LAST,NEXT}_N_{DAYS,WEEKS,MONTHS,QUARTERS,YEARS}:n``
and ``N_{DAYS,WEEKS,MONTHS,QUARTERS,YEARS}_AGO:n``. String comparison is
case-insensitive and ``!=`` returns records with no value, as Salesforce does.
Aggregates, subqueries, bind variables and ``GROUP BY`` are refused with
``MALFORMED_QUERY``.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import NoReturn

from .ast import (
    ELEMENT,
    TRUE,
    AnyOf,
    Compare,
    In,
    IsEmpty,
    Node,
    Not,
    Op,
    OrderKey,
    Query,
    TextMatch,
    TimeWindow,
    Value,
    conjoin,
    disjoin,
)
from .clock import aware, parse_instant, shift, start_of, window
from .lexer import EOF, Cursor, Token, tokenize, unquote

LANGUAGE = "soql"

_TOKENS = (
    ("string", r"'(?:[^'\\]|\\.)*'"),
    ("datetime", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:?\d{2})"),
    ("date", r"\d{4}-\d{2}-\d{2}(?![\dT])"),
    ("number", r"-?\d+(?:\.\d+)?"),
    ("op", r"!=|<>|<=|>=|=|<|>"),
    ("lparen", r"\("),
    ("rparen", r"\)"),
    ("comma", r","),
    ("word", r"[A-Za-z_][A-Za-z0-9_.]*(?::-?\d+)?"),
    ("bind", r":[A-Za-z_]\w*"),
)

_COMPARE = {"=": Op.EQ, "!=": Op.NE, "<>": Op.NE, ">": Op.GT, ">=": Op.GE, "<": Op.LT, "<=": Op.LE}
_RESERVED = frozenset({"and", "or", "not", "from", "where", "order", "limit", "offset", "group", "having", "with", "for"})
_UNITS = {"days": "day", "weeks": "week", "months": "month", "quarters": "quarter", "years": "year"}
_FIXED = {
    "today": ("day", 0), "yesterday": ("day", -1), "tomorrow": ("day", 1),
    "last_week": ("week", -1), "this_week": ("week", 0), "next_week": ("week", 1),
    "last_month": ("month", -1), "this_month": ("month", 0), "next_month": ("month", 1),
    "last_quarter": ("quarter", -1), "this_quarter": ("quarter", 0), "next_quarter": ("quarter", 1),
    "last_year": ("year", -1), "this_year": ("year", 0), "next_year": ("year", 1),
}
_PARAMETRIC = re.compile(r"^(last_n|next_n|n)_(days|weeks|months|quarters|years)(_ago)?:(\d+)$")

#: The largest OFFSET Salesforce accepts.
MAX_OFFSET = 2000


def date_literal(name: str, clock: datetime) -> tuple[datetime, datetime] | None:
    """A SOQL date literal as its half-open window, or ``None`` when *name* is not one."""

    folded = name.casefold()
    if folded in _FIXED:
        unit, count = _FIXED[folded]
        return window(unit, clock, count)
    today = start_of("day", clock)
    if folded == "last_90_days":
        return today - timedelta(days=90), today + timedelta(days=1)
    if folded == "next_90_days":
        return today + timedelta(days=1), today + timedelta(days=91)
    match = _PARAMETRIC.match(folded)
    if match is None:
        return None
    kind, units, ago, raw = match.groups()
    unit = _UNITS[units]
    count = int(raw)
    if kind == "n" and ago:
        return window(unit, clock, -count)
    if kind == "n" or ago:
        return None
    if unit == "day":
        if kind == "last_n":
            return today - timedelta(days=count), today + timedelta(days=1)
        return today + timedelta(days=1), today + timedelta(days=count + 1)
    current, following = window(unit, clock, 0)
    step = 3 if unit == "quarter" else 1
    letter = {"week": "w", "month": "M", "quarter": "M", "year": "y"}[unit]
    if kind == "last_n":
        return shift(current, -count * step, letter), current
    return following, shift(following, count * step, letter)


def range_condition(field: str, op: Op, start: datetime, end: datetime, *, at: int, raw: str = "") -> Node:
    """A comparison against a whole window, the way SOQL reads one."""

    if op is Op.EQ:
        return TimeWindow(field, start, end, at=at, raw=raw)
    if op is Op.NE:
        return Not(TimeWindow(field, start, end, at=at, raw=raw))
    bounds = {Op.GT: (end, None), Op.GE: (start, None), Op.LT: (None, start), Op.LE: (None, end)}[op]
    return TimeWindow(field, bounds[0], bounds[1], at=at, raw=raw)


class _Parser:
    def __init__(self, text: str, clock: datetime) -> None:
        self.cursor = Cursor(LANGUAGE, text, tokenize(LANGUAGE, text, _TOKENS))
        self.clock = aware(clock)

    def unexpected(self, token: Token | None = None) -> NoReturn:
        token = token or self.cursor.peek()
        shown = token.text if token.kind != EOF else "<EOF>"
        self.cursor.fail(f"unexpected token: '{shown}'", token)

    def keyword(self, word: str) -> Token:
        token = self.cursor.accept_word(word)
        if token is None:
            self.unexpected()
        return token

    def field(self) -> Token:
        token = self.cursor.peek()
        if token.kind != "word" or token.folded in _RESERVED:
            self.unexpected()
        self.cursor.next()
        if self.cursor.at("lparen"):
            self.cursor.fail(f"Aggregate or function '{token.text}()' is not supported by this query endpoint", token)
        return token

    def parse(self) -> Query:
        cursor = self.cursor
        self.keyword("select")
        select: list[Token] = []
        while True:
            if cursor.at("lparen"):
                cursor.fail("Nested queries are not supported by this query endpoint", cursor.peek())
            select.append(self.field())
            if not cursor.accept("comma"):
                break
        self.keyword("from")
        source = cursor.peek()
        if source.kind != "word" or source.folded in _RESERVED:
            self.unexpected()
        cursor.next()
        where: Node = TRUE
        if cursor.accept_word("where"):
            where = self.condition()
        order: list[OrderKey] = []
        if cursor.accept_word("order"):
            self.keyword("by")
            while True:
                token = self.field()
                descending = False
                if cursor.at_word("asc", "desc"):
                    descending = cursor.next().folded == "desc"
                nulls: bool | None = None
                if cursor.accept_word("nulls"):
                    if not cursor.at_word("first", "last"):
                        self.unexpected()
                    nulls = cursor.next().folded == "first"
                order.append(OrderKey(token.text, descending, nulls, at=token.at))
                if not cursor.accept("comma"):
                    break
        limit = None
        offset = 0
        if cursor.accept_word("limit"):
            limit = self.integer()
        if cursor.accept_word("offset"):
            token = cursor.peek()
            offset = self.integer()
            if offset > MAX_OFFSET:
                cursor.fail(f"Maximum SOQL offset allowed is {MAX_OFFSET}", token)
        if not cursor.at(EOF):
            self.unexpected()
        return Query(
            language=LANGUAGE,
            where=where,
            source=source.text,
            order=tuple(order),
            limit=limit,
            offset=offset,
            select=tuple(token.text for token in select),
            source_at=source.at,
        )

    def integer(self) -> int:
        token = self.cursor.peek()
        if token.kind != "number" or not token.text.isdigit():
            self.unexpected()
        self.cursor.next()
        return int(token.text)

    def condition(self) -> Node:
        cursor = self.cursor
        items = [self.unary()]
        joiner: str | None = None
        while cursor.at_word("and", "or"):
            word = cursor.peek().folded
            if joiner is not None and word != joiner:
                # Salesforce refuses `a AND b OR c`: the grouping must be stated.
                self.unexpected()
            joiner = word
            cursor.next()
            items.append(self.unary())
        if joiner == "or":
            return disjoin(items)
        return conjoin(items)

    def unary(self) -> Node:
        cursor = self.cursor
        if cursor.accept_word("not"):
            return Not(self.unary())
        if cursor.accept("lparen"):
            inner = self.condition()
            if not cursor.accept("rparen"):
                self.unexpected()
            return inner
        return self.comparison()

    def comparison(self) -> Node:
        cursor = self.cursor
        token = self.field()
        field = token.text
        at = token.at
        if cursor.at("op"):
            symbol = cursor.next().text
            op = _COMPARE[symbol]
            value_token = cursor.peek()
            window_value = self.window_value()
            if window_value is not None:
                return range_condition(field, op, *window_value, at=at, raw=value_token.text)
            value = self.value()
            if value is None:
                if op is Op.EQ:
                    return IsEmpty(field, at=at)
                if op is Op.NE:
                    return Not(IsEmpty(field, at=at))
                self.unexpected(value_token)
            return Compare(field, op, value, missing_matches=op is Op.NE, at=at)
        if cursor.accept_word("like"):
            value_token = cursor.peek()
            if value_token.kind != "string":
                self.unexpected()
            cursor.next()
            return TextMatch(field, unquote(value_token), "like", at=at)
        negated = False
        if cursor.at_word("not") and cursor.at_word("in", offset=1):
            cursor.next()
            negated = True
        if cursor.accept_word("in"):
            values = self.value_list()
            present = tuple(value for value in values if value is not None)
            parts: list[Node] = [In(field, present, at=at)] if present else []
            if len(present) != len(values):
                parts.append(IsEmpty(field, at=at))
            node = disjoin(parts) if parts else TRUE
            return Not(node) if negated else node
        if cursor.at_word("includes", "excludes"):
            excludes = cursor.next().folded == "excludes"
            groups: list[Node] = []
            for value in self.value_list():
                if not isinstance(value, str):
                    self.unexpected()
                required = [part.strip() for part in value.split(";") if part.strip()]
                groups.append(conjoin([
                    AnyOf(field, Compare(ELEMENT, Op.EQ, part), at=at) for part in required
                ]))
            node = disjoin(groups)
            return Not(node) if excludes else node
        self.unexpected()

    def value_list(self) -> tuple[Value, ...]:
        cursor = self.cursor
        if not cursor.accept("lparen"):
            self.unexpected()
        values = [self.value()]
        while cursor.accept("comma"):
            values.append(self.value())
        if not cursor.accept("rparen"):
            self.unexpected()
        return tuple(values)

    def window_value(self) -> tuple[datetime, datetime] | None:
        cursor = self.cursor
        token = cursor.peek()
        if token.kind == "date":
            day = parse_instant(token.text, self.clock.tzinfo)  # type: ignore[arg-type]
            assert day is not None
            cursor.next()
            return day, day + timedelta(days=1)
        if token.kind == "word":
            literal = date_literal(token.text, self.clock)
            if literal is not None:
                cursor.next()
                return literal
            if ":" in token.text:
                cursor.fail(f"Invalid date literal: {token.text}", token)
        return None

    def value(self) -> Value:
        cursor = self.cursor
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            return unquote(token)
        if token.kind == "number":
            cursor.next()
            return float(token.text) if "." in token.text else int(token.text)
        if token.kind == "datetime":
            cursor.next()
            parsed = parse_instant(token.text, self.clock.tzinfo)  # type: ignore[arg-type]
            assert parsed is not None
            return parsed
        if token.kind == "date":
            cursor.next()
            parsed = parse_instant(token.text, self.clock.tzinfo)  # type: ignore[arg-type]
            assert parsed is not None
            return parsed
        if token.kind == "word" and token.folded in ("true", "false"):
            cursor.next()
            return token.folded == "true"
        if token.kind == "word" and token.folded == "null":
            cursor.next()
            return None
        if token.kind == "bind":
            cursor.fail("Bind variables are not supported by this query endpoint", token)
        self.unexpected()


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one SOQL statement. Raises ``QueryError`` shaped as Salesforce answers."""

    return _Parser(text, clock).parse()


__all__ = ["LANGUAGE", "MAX_OFFSET", "date_literal", "parse", "range_condition"]
