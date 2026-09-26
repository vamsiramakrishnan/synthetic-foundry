"""OData query options (Microsoft Graph) to the common filter tree.

Accepts either a bare ``$filter`` expression or a query-option string
(``$filter=...&$orderby=...&$top=5``, percent-encoding allowed). Supported:
``$filter`` with ``eq ne gt ge lt le``, ``in (..)``, ``and``/``or``/``not`` and
parentheses; ``startswith(p,'x')``, ``endswith(p,'x')``, ``contains(p,'x')``
(optionally ``eq true``); ``p/any(v: ...)`` and ``p/all(v: ...)`` over simple
collections, where the body names ``v`` or ``v/prop``; property paths
(``from/emailAddress/address``); literals ``'str'`` (``''`` escapes a quote),
numbers, ``true``/``false``/``null``, ``2026-09-01`` and
``2026-09-01T10:00:00Z``. ``$orderby=p [asc|desc], ...``, ``$top``, ``$skip``,
``$select`` and ``$search="terms"`` (free text over the item's text fields).
String comparison is case-insensitive, as Graph's mail and drive filters are.
No ``ConsistencyLevel: eventual`` features: ``$count``, ``$expand``, casts and
arithmetic are refused with Graph's ``Invalid filter clause``.
"""

from __future__ import annotations

import re
from datetime import datetime
from urllib.parse import unquote as url_unquote

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
    Value,
    conjoin,
    disjoin,
)
from .clock import aware, parse_instant
from .errors import query_error
from .lexer import EOF, Cursor, Token, tokenize, unquote

LANGUAGE = "odata"

_TOKENS = (
    ("string", r"'(?:[^']|'')*'"),
    ("datetime", r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2})"),
    ("date", r"\d{4}-\d{2}-\d{2}(?![\dT])"),
    ("number", r"-?\d+(?:\.\d+)?"),
    ("lparen", r"\("),
    ("rparen", r"\)"),
    ("comma", r","),
    ("colon", r":"),
    ("slash", r"/"),
    ("word", r"[A-Za-z_@$][A-Za-z0-9_.]*"),
)
_COMPARE = {"eq": Op.EQ, "ne": Op.NE, "gt": Op.GT, "ge": Op.GE, "lt": Op.LT, "le": Op.LE}
_TEXT_FUNCTIONS = {"startswith": "startswith", "endswith": "endswith", "contains": "contains"}
_OPTIONS = frozenset({"$filter", "$orderby", "$top", "$skip", "$select", "$search"})


def _split_options(text: str) -> dict[str, str]:
    options: dict[str, str] = {}
    quote = False
    current: list[str] = []
    parts: list[str] = []
    for char in text.lstrip("?"):
        if char == "'":
            quote = not quote
        if char == "&" and not quote:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    for part in parts:
        if not part.strip():
            continue
        name, _, value = part.partition("=")
        options[url_unquote(name.strip()).casefold()] = url_unquote(value)
    return options


class _Filter:
    def __init__(self, text: str, clock: datetime) -> None:
        self.cursor = Cursor(LANGUAGE, text, tokenize(LANGUAGE, text, _TOKENS))
        self.clock = aware(clock)
        self.variables: tuple[str, ...] = ()

    def syntax(self, token: Token | None = None) -> Exception:
        token = token or self.cursor.peek()
        return self.cursor.error("parse", f"Syntax error at position {token.at + 1} in '{self.cursor.text}'.", token)

    def parse(self) -> Node:
        node = self.or_expr()
        if not self.cursor.at(EOF):
            raise self.syntax()
        return node

    def or_expr(self) -> Node:
        items = [self.and_expr()]
        while self.cursor.accept_word("or"):
            items.append(self.and_expr())
        return disjoin(items)

    def and_expr(self) -> Node:
        items = [self.unary()]
        while self.cursor.accept_word("and"):
            items.append(self.unary())
        return conjoin(items)

    def unary(self) -> Node:
        if self.cursor.accept_word("not"):
            return Not(self.unary())
        return self.primary()

    def primary(self) -> Node:
        cursor = self.cursor
        if cursor.accept("lparen"):
            inner = self.or_expr()
            if not cursor.accept("rparen"):
                raise self.syntax()
            return inner
        token = cursor.peek()
        if token.kind != "word":
            raise self.syntax()
        if cursor.peek(1).kind == "lparen":
            return self.function()
        path, lambda_node = self.path()
        if lambda_node is not None:
            return lambda_node
        return self.comparison(path, token)

    def path(self) -> tuple[str, Node | None]:
        """A property path, or a whole ``p/any(...)`` condition when one follows."""

        cursor = self.cursor
        first = cursor.next()
        parts = [first.text]
        while cursor.accept("slash"):
            token = cursor.peek()
            if token.kind != "word":
                raise self.syntax()
            if token.folded in ("any", "all") and cursor.peek(1).kind == "lparen":
                cursor.next()
                return "/".join(parts), self.lambda_(self.field_path(parts, first), token.folded, first.at)
            cursor.next()
            parts.append(token.text)
        return self.field_path(parts, first), None

    def field_path(self, parts: list[str], first: Token) -> str:
        if parts[0] in self.variables:
            return "/".join([ELEMENT, *parts[1:]])
        return "/".join(parts)

    def lambda_(self, field: str, kind: str, at: int) -> Node:
        cursor = self.cursor
        cursor.expect("lparen", "'('")
        variable = cursor.peek()
        if variable.kind != "word":
            raise self.syntax()
        cursor.next()
        if not cursor.accept("colon"):
            raise self.syntax()
        saved = self.variables
        self.variables = (*saved, variable.text)
        body = self.or_expr()
        self.variables = saved
        if not cursor.accept("rparen"):
            raise self.syntax()
        if kind == "any":
            return AnyOf(field, body, at=at)
        return Not(AnyOf(field, Not(body), at=at))

    def function(self) -> Node:
        cursor = self.cursor
        name = cursor.next()
        if name.folded not in _TEXT_FUNCTIONS:
            raise cursor.error("unknown_function", token=name, name=name.text)
        cursor.expect("lparen", "'('")
        head = cursor.peek()
        if head.kind != "word":
            raise self.syntax()
        field, lambda_node = self.path()
        if lambda_node is not None:
            raise self.syntax(head)
        if not cursor.accept("comma"):
            raise self.syntax()
        literal = cursor.peek()
        if literal.kind != "string":
            raise self.syntax()
        cursor.next()
        if not cursor.accept("rparen"):
            raise self.syntax()
        node: Node = TextMatch(field, unquote(literal), _TEXT_FUNCTIONS[name.folded], at=head.at)  # type: ignore[arg-type]
        if cursor.at_word("eq", "ne") and cursor.at_word("true", "false", offset=1):
            negate = (cursor.next().folded == "ne") != (cursor.next().folded == "false")
            if negate:
                node = Not(node)
        return node

    def comparison(self, field: str, token: Token) -> Node:
        cursor = self.cursor
        if cursor.accept_word("in"):
            if not cursor.accept("lparen"):
                raise self.syntax()
            values = [self.literal()]
            while cursor.accept("comma"):
                values.append(self.literal())
            if not cursor.accept("rparen"):
                raise self.syntax()
            return In(field, tuple(values), at=token.at)
        operator = cursor.peek()
        if operator.kind != "word" or operator.folded not in _COMPARE:
            raise self.syntax(operator)
        cursor.next()
        op = _COMPARE[operator.folded]
        value = self.literal()
        if value is None:
            if op is Op.EQ:
                return IsEmpty(field, at=token.at)
            if op is Op.NE:
                return Not(IsEmpty(field, at=token.at))
            raise self.syntax(operator)
        return Compare(field, op, value, at=token.at)

    def literal(self) -> Value:
        cursor = self.cursor
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            return unquote(token)
        if token.kind == "number":
            cursor.next()
            return float(token.text) if "." in token.text else int(token.text)
        if token.kind in ("datetime", "date"):
            cursor.next()
            parsed = parse_instant(token.text, self.clock.tzinfo)  # type: ignore[arg-type]
            if parsed is None:
                raise self.syntax(token)
            return parsed
        if token.kind == "word" and token.folded in ("true", "false"):
            cursor.next()
            return token.folded == "true"
        if token.kind == "word" and token.folded == "null":
            cursor.next()
            return None
        raise self.syntax(token)


def _order(text: str) -> tuple[OrderKey, ...]:
    keys: list[OrderKey] = []
    offset = 0
    for part in text.split(","):
        words = part.split()
        at = offset + (len(part) - len(part.lstrip()))
        offset += len(part) + 1
        if not words:
            continue
        if len(words) > 2 or (len(words) == 2 and words[1].casefold() not in ("asc", "desc")):
            raise query_error(LANGUAGE, "parse", query=text, detail=f"Syntax error at position {at + 1} in '{text}'.")
        keys.append(OrderKey(words[0], len(words) == 2 and words[1].casefold() == "desc", at=at))
    return tuple(keys)


def _integer(name: str, value: str) -> int:
    if not re.fullmatch(r"\d+", value.strip()):
        raise query_error(LANGUAGE, "parse", query=value,
                          detail=f"Invalid value '{value}' for {name} query option found. The {name} query option requires a non-negative integer value.")
    return int(value)


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse a ``$filter`` expression or a whole OData query-option string."""

    stripped = text.strip()
    if re.match(r"^\??\$\w+=", stripped) or re.search(r"&\$\w+=", stripped):
        options = _split_options(stripped)
    else:
        options = {"$filter": stripped}
    unknown = sorted(set(options) - _OPTIONS)
    if unknown:
        raise query_error(LANGUAGE, "parse", query=text,
                          detail=f"Query option '{unknown[0]}' is not supported by this subset.")
    parts: list[Node] = []
    if options.get("$filter", "").strip():
        parts.append(_Filter(options["$filter"].strip(), clock).parse())
    search = options.get("$search", "").strip()
    if search:
        parts.append(TextMatch(None, search.strip('"'), "terms"))
    return Query(
        language=LANGUAGE,
        where=conjoin(parts) if parts else TRUE,
        order=_order(options["$orderby"]) if options.get("$orderby", "").strip() else (),
        limit=_integer("$top", options["$top"]) if "$top" in options else None,
        offset=_integer("$skip", options["$skip"]) if "$skip" in options else 0,
        select=tuple(part.strip() for part in options.get("$select", "").split(",") if part.strip()),
    )


__all__ = ["LANGUAGE", "parse"]
