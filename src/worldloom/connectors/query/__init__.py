"""One query evaluator for every enterprise connector's native query language.

Grading an agent's search is done elsewhere, by what the search retrieves, so
this package's job is faithful execution: parse each vendor language into one
filter tree (``ast``), bind its field names to record keys through a
``QueryTarget`` derived from the connector definition (``schema``), evaluate it
over corpus records with deterministic BM25 relevance (``engine``), and answer
anything outside the supported grammar with the vendor's own error
(``errors``; the texts live in ``_data/connectors/_query.json``).

The same functions serve the built-in connector emulator (the default: the
policy ``connectors.query.engine`` is ``native``; ``predicate`` selects the
historical conjunctive parser) and any out-of-process provider, which needs
only ``parse``, a ``QueryTarget`` and ``execute``. What each search tool tells
the agent about its query language is ``docs.query_help``.

Relative time resolves against the clock the caller passes, the corpus's
as-of time, never the wall clock. Same text, clock and records: same answer.

Supported grammar, per language (each parser's docstring has the detail):

``jql`` (Jira)
    ``= != > >= < <= ~ !~ IN NOT IN``, ``IS [NOT] EMPTY|NULL``, ``AND OR NOT``
    (and ``&& || !``), parentheses, ``ORDER BY``; ``currentUser()``, ``now()``,
    ``startOf|endOf Day|Week|Month|Year(inc)``; relative dates ``-7d`` (units
    ``y M w d h m``). ``text ~`` searches every text field.
``soql`` (Salesforce)
    ``SELECT .. FROM obj [WHERE] [ORDER BY .. NULLS FIRST|LAST] [LIMIT] [OFFSET]``;
    ``= != <> < <= > >= LIKE IN NOT IN INCLUDES EXCLUDES``, ``AND OR NOT``
    (not mixed unparenthesised), date literals (``TODAY``, ``LAST_N_DAYS:n``,
    ``THIS_QUARTER``, ...), relationship paths (``Account.Name``).
``encoded_query`` (ServiceNow)
    ``^`` ``^OR`` ``^NQ``, ``= != LIKE NOT LIKE STARTSWITH ENDSWITH IN NOT IN
    ISEMPTY ISNOTEMPTY ANYTHING EMPTYSTRING > >= < <= BETWEEN ON NOTON``,
    ``ORDERBY``/``ORDERBYDESC``, ``javascript:gs.daysAgoStart(n)`` and the
    other ``gs`` date helpers. Unknown fields and unreadable conditions are
    dropped, as ServiceNow does.
``odata`` (Microsoft Graph)
    ``$filter`` with ``eq ne gt ge lt le in and or not``, ``startswith``,
    ``endswith``, ``contains``, ``p/any(v: ..)`` and ``p/all(v: ..)``;
    ``$orderby``, ``$top``, ``$skip``, ``$select``, ``$search``. No
    ``ConsistencyLevel: eventual`` features.
``cql`` (Confluence)
    ``space type title text ~ label creator contributor created lastmodified
    ancestor parent id``, ``= != > >= < <= ~ !~ IN NOT IN``, ``AND OR NOT``,
    ``ORDER BY``, ``now("-4w")`` and the ``startOf``/``endOf`` functions.
``kql`` (Microsoft Search, SharePoint)
    free text, ``"phrases"``, ``prefix*``, ``prop:value``, ``prop=value``,
    ``prop<>value``, ``> >= < <=`` on dates and numbers, ``AND OR NOT``
    (upper case), ``-term``, parentheses. Unknown properties are text.
``drive_q`` (Google Drive v3)
    ``name contains``, ``fullText contains``, ``mimeType =``, ``modifiedTime >``
    (and the other time fields), ``'id' in parents``, ``trashed = false``,
    ``and or not``, parentheses; per-field operator checks.
``slack_search`` (Slack)
    ``in:#channel``, ``from:@user``, ``before:`` ``after:`` ``on:``
    ``during:``, ``has:`` ``is:``, ``-term``, ``"phrases"``, free text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from . import cql, drive, encoded, jql, kql, odata, slack, soql
from .ast import (
    ELEMENT,
    TRUE,
    And,
    AnyOf,
    Compare,
    Const,
    In,
    IsEmpty,
    Node,
    Not,
    Op,
    Or,
    OrderKey,
    Query,
    TextMatch,
    TimeWindow,
    Value,
)
from .clock import aware
from .engine import QueryResult, Relevance, bind, bm25, execute, matches
from .errors import QueryError, query_error
from .schema import (
    QueryTarget,
    canonical_language,
    entity_for_source,
    target_for,
    tool_language,
)

if TYPE_CHECKING:
    from ...connector_definition import ConnectorDefinition

Parser = Callable[..., Query]

PARSERS: Mapping[str, Parser] = {
    "jql": jql.parse,
    "soql": soql.parse,
    "encoded_query": encoded.parse,
    "odata": odata.parse,
    "cql": cql.parse,
    "kql": kql.parse,
    "drive_q": drive.parse,
    "slack_search": slack.parse,
}

SUPPORTED_LANGUAGES = tuple(PARSERS)


def parse(language: str, text: str, *, clock: datetime, user: str | None = None) -> Query:
    """Parse *text* in *language* (a ``query_language`` name or alias) against *clock*."""

    resolved = canonical_language(language)
    if resolved is None:
        raise ValueError(f"unsupported query language {language!r}; supported: {', '.join(SUPPORTED_LANGUAGES)}")
    return PARSERS[resolved](text, clock=aware(clock), user=user)


def run(
    language: str,
    text: str,
    records: Sequence[Mapping[str, Any]],
    target: QueryTarget,
    *,
    clock: datetime,
    user: str | None = None,
    relevance: Relevance | None = None,
    id_key: str = "fid",
) -> QueryResult:
    """Parse, bind and execute in one call."""

    parsed = parse(language, text, clock=clock, user=user)
    return execute(bind(parsed, target, text=text), records, target, relevance=relevance, id_key=id_key)


@dataclass(frozen=True)
class ConnectorSearch:
    """One native search over a connector definition's records."""

    language: str
    entity: str | None
    records: tuple[Mapping[str, Any], ...]
    """The pool the query ran over; ``result.matches`` index into it."""
    result: QueryResult


def connector_search(
    definition: ConnectorDefinition,
    tool: str,
    text: str,
    *,
    pool: Callable[[str | None], Sequence[Mapping[str, Any]]],
    entity: str | None = None,
    user: str | None = None,
    relevance: Relevance | None = None,
    id_key: str = "fid",
) -> ConnectorSearch:
    """Run *text* as *tool*'s native query over the pool *pool* returns for an entity.

    The clock is the definition's ``clock``, the corpus's as-of time. A query
    that names its own object (SOQL ``FROM``) chooses the entity; an object the
    definition does not declare is the vendor's unknown-type error. Raises
    ``ValueError`` when the tool's language is not one this package parses.
    """

    language = tool_language(definition, tool)
    if language is None:
        raise ValueError(f"{definition.connector}.{tool}: query language {definition.query_language!r} is not supported")
    clock = datetime.fromisoformat(definition.clock)
    parsed = parse(language, text, clock=clock, user=user)
    chosen = entity
    if parsed.source is not None:
        chosen = entity_for_source(definition, parsed.source, language=language, query=text, at=parsed.source_at)
    records = tuple(pool(chosen))
    target = target_for(definition, language=language, entity=chosen, records=records)
    result = execute(bind(parsed, target, text=text), records, target, relevance=relevance, id_key=id_key)
    return ConnectorSearch(language=language, entity=chosen, records=records, result=result)


__all__ = [
    # entry points
    "PARSERS",
    "SUPPORTED_LANGUAGES",
    "ConnectorSearch",
    "bind",
    "connector_search",
    "execute",
    "matches",
    "parse",
    "run",
    # the tree
    "ELEMENT",
    "TRUE",
    "And",
    "AnyOf",
    "Compare",
    "Const",
    "In",
    "IsEmpty",
    "Node",
    "Not",
    "Op",
    "Or",
    "OrderKey",
    "Query",
    "TextMatch",
    "TimeWindow",
    "Value",
    # binding and results
    "QueryError",
    "QueryResult",
    "QueryTarget",
    "Relevance",
    "bm25",
    "canonical_language",
    "entity_for_source",
    "query_error",
    "target_for",
    "tool_language",
]
