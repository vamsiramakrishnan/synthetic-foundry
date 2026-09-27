"""A small tokenizer and recursive-descent cursor the vendor parsers share.

Each language states its tokens as an ordered list of ``(kind, regex)`` pairs;
the first that matches at the cursor wins, so longer operators are listed
before their prefixes. Keywords are not tokens of their own: a ``word`` whose
case-folded text is ``and`` is the keyword ``AND`` exactly where the grammar
expects one, which is how every one of these languages treats reserved words.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import NoReturn

from .errors import QueryError, query_error


@dataclass(frozen=True)
class Token:
    kind: str
    text: str
    at: int

    @property
    def folded(self) -> str:
        return self.text.casefold()


EOF = "eof"


def tokenize(
    language: str,
    text: str,
    patterns: Sequence[tuple[str, str]],
    *,
    skip: str = r"\s+",
) -> list[Token]:
    """Split *text* into tokens; an unreadable character is a vendor parse error."""

    compiled = [(kind, re.compile(pattern, re.DOTALL)) for kind, pattern in patterns]
    skipper = re.compile(skip)
    tokens: list[Token] = []
    position = 0
    while position < len(text):
        gap = skipper.match(text, position)
        if gap is not None and gap.end() > position:
            position = gap.end()
            continue
        for kind, pattern in compiled:
            match = pattern.match(text, position)
            if match is not None and match.end() > position:
                tokens.append(Token(kind, match.group(0), position))
                position = match.end()
                break
        else:
            raise query_error(
                language, "parse", query=text, position=position + 1, column=position + 1,
                token=text[position], detail=f"Illegal character '{text[position]}'.",
            )
    tokens.append(Token(EOF, "", len(text)))
    return tokens


def unquote(token: Token) -> str:
    """The text of a quoted string token, escapes resolved.

    Handles backslash escapes (JQL, CQL, SOQL, Drive) and the doubled quote
    OData uses (``'O''Brien'``).
    """

    body = token.text[1:-1]
    quote = token.text[0]
    body = body.replace(quote + quote, quote) if quote == "'" and "\\" not in body else body
    out: list[str] = []
    escaped = False
    for char in body:
        if escaped:
            out.append({"n": "\n", "t": "\t", "r": "\r"}.get(char, char))
            escaped = False
        elif char == "\\":
            escaped = True
        else:
            out.append(char)
    return "".join(out)


class Cursor:
    """The token stream a recursive-descent parser walks."""

    def __init__(self, language: str, text: str, tokens: list[Token]) -> None:
        self.language = language
        self.text = text
        self.tokens = tokens
        self.index = 0

    def peek(self, offset: int = 0) -> Token:
        return self.tokens[min(self.index + offset, len(self.tokens) - 1)]

    def next(self) -> Token:
        token = self.peek()
        if token.kind != EOF:
            self.index += 1
        return token

    def at(self, kind: str) -> bool:
        return self.peek().kind == kind

    def at_word(self, *words: str, offset: int = 0) -> bool:
        token = self.peek(offset)
        return token.kind == "word" and token.folded in words

    def accept(self, kind: str) -> Token | None:
        return self.next() if self.at(kind) else None

    def accept_word(self, *words: str) -> Token | None:
        return self.next() if self.at_word(*words) else None

    def expect(self, kind: str, what: str) -> Token:
        if not self.at(kind):
            self.fail(f"Expecting {what} but got '{self.peek().text}'.")
        return self.next()

    def fail(self, detail: str, token: Token | None = None, **extra: object) -> NoReturn:
        raise self.error("parse", detail, token, **extra)

    def error(self, kind: str, detail: str = "", token: Token | None = None, **extra: object) -> QueryError:
        where = token or self.peek()
        shown = where.text if where.kind != EOF else "<EOF>"
        return query_error(
            self.language, kind, query=self.text, position=where.at + 1, column=where.at + 1,
            token=shown, detail=detail, **extra,
        )


__all__ = ["EOF", "Cursor", "Token", "tokenize", "unquote"]
