"""JQL (Jira Cloud) to the common filter tree.

Supported: ``field op value`` with ``= != > >= < <= ~ !~ IN (..) NOT IN (..)``,
``IS [NOT] EMPTY|NULL``; ``AND``/``&&``, ``OR``/``||``, ``NOT``/``!`` and
parentheses; ``ORDER BY field [ASC|DESC], ...``; the functions
``currentUser()``, ``now()``, ``startOfDay|Week|Month|Year([inc])`` and
``endOfDay|Week|Month|Year([inc])``; relative dates (``-7d``, ``"-2w 3d"``, units
``y M w d h m``) and absolute ones (``2026-09-01``, ``"2026/09/01 10:00"``).
``text ~`` searches every text field. Anything else (``WAS``, ``CHANGED``,
``openSprints()``) is refused with Jira's own message.
"""

from __future__ import annotations

from datetime import datetime

from .ast import (
    TRUE,
    Compare,
    In,
    IsEmpty,
    Node,
    Not,
    Op,
    OrderKey,
    Query,
    TextMatch,
    Value,
    conjoin,
    disjoin,
)
from .clock import apply_shift, aware, end_of, parse_instant, parse_shift, start_of
from .lexer import EOF, Cursor, Token, tokenize, unquote

LANGUAGE = "jql"

_TOKENS = (
    ("string", r'"(?:[^"\\]|\\.)*"|\'(?:[^\'\\]|\\.)*\''),
    ("op", r"!~|!=|>=|<=|=|>|<|~"),
    ("bang", r"!"),
    ("lparen", r"\("),
    ("rparen", r"\)"),
    ("comma", r","),
    ("word", r"[^\s()=!<>~,\"']+"),
)

_OPERATORS = (
    "Expecting operator but got '{got}'. The valid operators are '=', '!=', '<', '>', '<=', '>=', "
    "'~', '!~', 'IN', 'NOT IN', 'IS' and 'IS NOT'."
)

_COMPARE = {"=": Op.EQ, "!=": Op.NE, ">": Op.GT, ">=": Op.GE, "<": Op.LT, "<=": Op.LE}

_CALENDAR = {"day": ("d", "day"), "week": ("w", "week"), "month": ("M", "month"), "year": ("y", "year")}

#: Jira's master text field and its aliases: ``text ~`` searches all of them.
_MASTER_TEXT = frozenset({"text", "textfields"})


def resolve_calendar(name: str, args: list[str], clock: datetime) -> datetime | None:
    """``startOfWeek("-1")`` and friends, shared by JQL and CQL."""

    folded = name.casefold()
    for unit, (letter, calendar_unit) in _CALENDAR.items():
        if folded not in (f"startof{unit}", f"endof{unit}"):
            continue
        boundary = start_of if folded.startswith("start") else end_of
        if not args or not args[0].strip():
            return boundary(calendar_unit, clock)
        raw = args[0].strip()
        if raw.lstrip("+-").isdigit():
            raw = raw + letter
        parts = parse_shift(raw)
        if parts is None:
            return None
        if all(part_unit == letter for _, part_unit in parts):
            # An increment in the function's own unit moves the period, so
            # endOfMonth(-1) is the last instant of the previous month.
            moved = apply_shift(clock, raw)
            return boundary(calendar_unit, moved) if moved is not None else None
        # Any other unit offsets the boundary: startOfMonth("+14d") is the 15th.
        return apply_shift(boundary(calendar_unit, clock), raw)
    return None


def date_value(text: str, clock: datetime) -> datetime | None:
    """A relative (``-7d``) or absolute date operand, resolved against *clock*."""

    clock = aware(clock)
    shifted = apply_shift(clock, text) if parse_shift(text) is not None else None
    if shifted is not None:
        return shifted
    assert clock.tzinfo is not None
    return parse_instant(text, clock.tzinfo)


class AtlassianParser:
    """JQL's grammar, which CQL shares; ``language`` picks the error texts."""

    def __init__(
        self,
        text: str,
        clock: datetime,
        user: str | None,
        *,
        language: str = LANGUAGE,
        master_text: frozenset[str] = _MASTER_TEXT,
        allow_is: bool = True,
    ) -> None:
        self.language = language
        self.cursor = Cursor(language, text, tokenize(language, text, _TOKENS))
        self.clock = aware(clock)
        self.user = user
        self.master_text = master_text
        self.allow_is = allow_is

    def parse(self) -> Query:
        cursor = self.cursor
        where: Node = TRUE
        if not cursor.at(EOF) and not cursor.at_word("order"):
            where = self.or_expr()
        order: list[OrderKey] = []
        if cursor.accept_word("order"):
            if not cursor.accept_word("by"):
                cursor.fail(f"Expecting 'by' but got '{cursor.peek().text}'.")
            while True:
                token = self.field_token()
                descending = False
                if cursor.at_word("asc", "desc"):
                    descending = cursor.next().folded == "desc"
                order.append(OrderKey(self.field_name(token), descending, at=token.at))
                if not cursor.accept("comma"):
                    break
        if not cursor.at(EOF):
            cursor.fail(f"Expecting either 'OR' or 'AND' but got '{cursor.peek().text}'.")
        return Query(language=self.language, where=where, order=tuple(order))

    def or_expr(self) -> Node:
        items = [self.and_expr()]
        while self.cursor.accept_word("or", "||"):
            items.append(self.and_expr())
        return disjoin(items)

    def and_expr(self) -> Node:
        items = [self.not_expr()]
        while self.cursor.accept_word("and", "&&"):
            items.append(self.not_expr())
        return conjoin(items)

    def not_expr(self) -> Node:
        cursor = self.cursor
        if cursor.accept("bang") or cursor.accept_word("not"):
            return Not(self.not_expr())
        return self.primary()

    def primary(self) -> Node:
        cursor = self.cursor
        if cursor.accept("lparen"):
            inner = self.or_expr()
            if not cursor.accept("rparen"):
                cursor.fail(f"Expecting ')' but got '{cursor.peek().text}'.")
            return inner
        return self.clause()

    def field_token(self) -> Token:
        token = self.cursor.peek()
        if token.kind not in ("word", "string") or token.folded in ("and", "or", "not", "order"):
            self.cursor.fail(f"Expecting a field name but got '{token.text if token.kind != EOF else '<EOF>'}'.")
        return self.cursor.next()

    @staticmethod
    def field_name(token: Token) -> str:
        return unquote(token) if token.kind == "string" else token.text

    def clause(self) -> Node:
        cursor = self.cursor
        token = self.field_token()
        field = self.field_name(token)
        at = token.at
        if cursor.at("op"):
            symbol = cursor.next().text
            if symbol in ("~", "!~"):
                operand = cursor.peek()
                value = self.value()
                if not isinstance(value, str):
                    cursor.fail(f"The operator '{symbol}' is not supported by the '{field}' field.", operand)
                phrase = len(value) >= 2 and value[0] == value[-1] == '"'
                match = TextMatch(
                    None if field.casefold() in self.master_text else field,
                    value[1:-1] if phrase else value,
                    "phrase" if phrase else "terms",
                    at=at,
                )
                return match if symbol == "~" else Not(match)
            value = self.value()
            if value is None:
                if symbol == "=":
                    return IsEmpty(field, at=at)
                if symbol == "!=":
                    return Not(IsEmpty(field, at=at))
                cursor.fail(f"The operator '{symbol}' does not support the value 'EMPTY'.")
            return Compare(field, _COMPARE[symbol], value, at=at)
        if self.allow_is and cursor.accept_word("is"):
            negated = cursor.accept_word("not") is not None
            if not cursor.accept_word("empty", "null"):
                cursor.fail(f"Expecting 'EMPTY' or 'NULL' but got '{cursor.peek().text}'.")
            empty = IsEmpty(field, at=at)
            return Not(empty) if negated else empty
        negated = False
        if cursor.at_word("not") and cursor.at_word("in", offset=1):
            cursor.next()
            negated = True
        if cursor.accept_word("in"):
            values = self.value_list()
            present = tuple(value for value in values if value is not None)
            parts: list[Node] = []
            if present:
                parts.append(In(field, present, at=at))
            if len(present) != len(values):
                parts.append(IsEmpty(field, at=at))
            node = disjoin(parts)
            return Not(node) if negated else node
        cursor.fail(_OPERATORS.format(got=cursor.peek().text if not cursor.at(EOF) else "<EOF>"))

    def value_list(self) -> tuple[Value, ...]:
        cursor = self.cursor
        if cursor.at("word") and cursor.peek(1).kind == "lparen":
            # `sprint in openSprints()`: a function standing for a list.
            return (self.value(),)
        if not cursor.accept("lparen"):
            cursor.fail(f"Expecting '(' but got '{cursor.peek().text}'.")
        values = [self.value()]
        while cursor.accept("comma"):
            values.append(self.value())
        if not cursor.accept("rparen"):
            cursor.fail(f"Expecting ')' but got '{cursor.peek().text}'.")
        return tuple(values)

    def value(self) -> Value:
        cursor = self.cursor
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            text = unquote(token)
            resolved = date_value(text, self.clock)
            return resolved if resolved is not None else text
        if token.kind != "word":
            cursor.fail(f"Expecting either a value, list or function but got '{token.text if token.kind != EOF else '<EOF>'}'.")
        cursor.next()
        if cursor.at("lparen"):
            return self.function(token)
        if token.folded in ("empty", "null"):
            return None
        resolved = date_value(token.text, self.clock)
        return resolved if resolved is not None else token.text

    def function(self, name: Token) -> Value:
        cursor = self.cursor
        cursor.expect("lparen", "'('")
        args: list[str] = []
        while not cursor.at("rparen"):
            token = cursor.next()
            if token.kind not in ("word", "string"):
                cursor.fail(f"Expecting a function argument but got '{token.text if token.kind != EOF else '<EOF>'}'.", token)
            args.append(unquote(token) if token.kind == "string" else token.text)
            if not cursor.accept("comma"):
                break
        cursor.expect("rparen", "')'")
        folded = name.folded
        if folded == "currentuser":
            return self.user
        if folded == "now":
            if not args or not args[0].strip():
                return self.clock
            moved = apply_shift(self.clock, args[0])
            if moved is None:
                cursor.fail(f"Invalid date increment '{args[0]}' for function '{name.text}'.", name)
            return moved
        resolved = resolve_calendar(folded, args, self.clock)
        if resolved is None:
            raise cursor.error("unknown_function", token=name, name=name.text)
        return resolved


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one JQL string. Raises ``QueryError`` with Jira's message."""

    return AtlassianParser(text, clock, user).parse()


__all__ = ["LANGUAGE", "AtlassianParser", "date_value", "parse", "resolve_calendar"]
