"""CQL (Confluence) to the common filter tree.

CQL is JQL's grammar over content, so this reuses ``jql.AtlassianParser``.
Supported: ``space``, ``type``, ``title``, ``text``/``siteSearch`` (``~`` over
every text field), ``label``, ``creator``, ``contributor``, ``created``,
``lastmodified``, ``ancestor``, ``parent``, ``id`` and any field the connector
definition declares; operators ``= != > >= < <= ~ !~ IN (..) NOT IN (..)``;
``AND``/``OR``/``NOT`` with parentheses; ``ORDER BY field [ASC|DESC]``; dates
``2026-09-01``, ``"2026/09/01 10:00"``; the functions ``now("-4w")``,
``startOfDay|Week|Month|Year("inc")``, ``endOfDay|Week|Month|Year("inc")`` and
``currentUser()``. ``IS EMPTY`` is not CQL and is refused, as is every other
construct, with Confluence's ``Could not parse cql`` answer.
"""

from __future__ import annotations

from datetime import datetime

from .ast import Query
from .jql import AtlassianParser

LANGUAGE = "cql"

_MASTER_TEXT = frozenset({"text", "sitesearch"})


def parse(text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse one CQL string. Raises ``QueryError`` shaped as Confluence answers."""

    return AtlassianParser(text, clock, user, language=LANGUAGE, master_text=_MASTER_TEXT, allow_is=False).parse()


__all__ = ["LANGUAGE", "parse"]
