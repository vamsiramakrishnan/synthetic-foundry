"""Google Drive v3 ``q`` to the common filter tree.

Supported: ``name contains|=|!= 'x'`` (``contains`` is a prefix match at a word
boundary, as Drive matches names), ``fullText contains 'x'`` (every term; a
double-quoted value is a phrase), ``mimeType =|!=|contains``,
``modifiedTime|createdTime|viewedByMeTime`` with ``< <= = != > >=`` against
RFC 3339 strings (UTC when no offset is given, as Drive reads them),
``trashed``/``starred``/``sharedWithMe = true|false``, ``'value' in
parents|owners|writers|readers``, ``and``/``or``/``not`` and parentheses.
Each field accepts only the operators Drive documents for it; anything else is
Drive's ``400 Invalid Value``.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from .ast import (
    ELEMENT,
    AnyOf,
    Compare,
    Node,
    Not,
    Op,
    Query,
    TextMatch,
    Value,
    conjoin,
    disjoin,
)
from .clock import parse_instant
from .errors import language_config
from .lexer import EOF, Cursor, Token, tokenize, unquote

LANGUAGE = "drive_q"

_TOKENS = (
    ("string", r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\""),
    ("op", r"!=|<=|>=|=|<|>"),
    ("lparen", r"\("),
    ("rparen", r"\)"),
    ("number", r"-?\d+(?:\.\d+)?"),
    ("word", r"[A-Za-z_][A-Za-z0-9_.]*"),
)
_COMPARE = {"=": Op.EQ, "!=": Op.NE, ">": Op.GT, ">=": Op.GE, "<": Op.LT, "<=": Op.LE}
_TIME_FIELDS = frozenset({"modifiedtime", "createdtime", "viewedbymetime", "sharedwithmetime"})


class _Parser:
    def __init__(self, text: str) -> None:
        self.cursor = Cursor(LANGUAGE, text, tokenize(LANGUAGE, text, _TOKENS))
        operators: Mapping[str, Any] = language_config(LANGUAGE).get("operators", {})
        self.operators = {name: tuple(ops) for name, ops in operators.items()}

    def invalid(self, token: Token | None = None) -> Exception:
        return self.cursor.error("parse", "Invalid Value", token)

    def parse(self) -> Query:
        if self.cursor.at(EOF):
            return Query(language=LANGUAGE)
        where = self.or_expr()
        if not self.cursor.at(EOF):
            raise self.invalid()
        return Query(language=LANGUAGE, where=where)

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
                raise self.invalid()
            return inner
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            if not cursor.accept_word("in"):
                raise self.invalid()
            collection = cursor.peek()
            if collection.kind != "word":
                raise self.invalid(collection)
            cursor.next()
            self.check(collection, "in")
            return AnyOf(collection.text, Compare(ELEMENT, Op.EQ, unquote(token), case_sensitive=True), at=collection.at)
        if token.kind != "word":
            raise self.invalid(token)
        cursor.next()
        field = token.text
        if cursor.accept_word("contains"):
            self.check(token, "contains")
            value_token = cursor.peek()
            if value_token.kind != "string":
                raise self.invalid(value_token)
            cursor.next()
            text = unquote(value_token)
            folded = field.casefold()
            if folded == "fulltext":
                phrase = len(text) >= 2 and text[0] == text[-1] == '"'
                return TextMatch(None, text[1:-1] if phrase else text, "phrase" if phrase else "terms", at=token.at)
            if folded == "name":
                return TextMatch(field, text, "prefix", at=token.at)
            return TextMatch(field, text, "contains", at=token.at)
        operator = cursor.peek()
        if operator.kind != "op":
            raise self.invalid(operator)
        cursor.next()
        self.check(token, operator.text)
        value = self.value(field)
        return Compare(field, _COMPARE[operator.text], value, at=token.at)

    def check(self, field: Token, operator: str) -> None:
        allowed = self.operators.get(field.folded)
        if allowed is not None and operator not in allowed:
            raise self.invalid(field)

    def value(self, field: str) -> Value:
        cursor = self.cursor
        token = cursor.peek()
        if token.kind == "string":
            cursor.next()
            text = unquote(token)
            if field.casefold() in _TIME_FIELDS:
                instant = parse_instant(text, UTC)
                if instant is None:
                    raise self.invalid(token)
                return instant
            return text
        if token.kind == "word" and token.folded in ("true", "false"):
            cursor.next()
            return token.folded == "true"
        if token.kind == "number":
            cursor.next()
            return float(token.text) if "." in token.text else int(token.text)
        raise self.invalid(token)


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one Drive ``q`` string. Raises ``QueryError`` (``400 Invalid Value``)."""

    return _Parser(text).parse()


__all__ = ["LANGUAGE", "parse"]
