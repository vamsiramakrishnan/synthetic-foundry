"""Binding and evaluating a parsed query over corpus records.

``bind`` checks every field a query names against its ``QueryTarget`` and
answers as the vendor does for one it does not know: Jira, Salesforce, Graph,
Confluence and Drive refuse, ServiceNow and Slack drop the condition, and
Microsoft Search reads it as free text. ``execute`` then filters, ranks and
pages.

Values compare the way a person reading the vendor's UI expects, not the way
Python's ``==`` does: a ``{"name": "Done"}`` status equals ``'done'`` under a
case-insensitive language, ``"1"`` equals ``1``, an ISO string is an instant,
and a list-valued field matches when any element does.

Ranking is deterministic. With an explicit order, records sort by it and ties
fall back to record id. Without one, a query with positive text conditions
ranks by BM25 over each record's text fields (``relevance`` replaces the
scorer) with ties by id; a query without text keeps the pool's order.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

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
from .clock import as_instant
from .errors import language_config, query_error
from .schema import QueryTarget

Relevance = Callable[[Sequence[str], str], Sequence[float]]
"""``(documents, query_text) -> one score per document``."""

_MISSING: Any = object()
_WORD = re.compile(r"[a-z0-9]+")
_DISPLAY_KEYS = ("name", "displayName", "display_value", "value", "key", "address", "id")


@dataclass(frozen=True)
class QueryResult:
    """What a query returned: indices into the records, best first."""

    query: Query
    matches: tuple[int, ...]
    total: int
    scores: tuple[float, ...]
    select: tuple[str, ...]


# ---------------------------------------------------------------------------
# Binding
# ---------------------------------------------------------------------------


def _unknown(target: QueryTarget, kind: str, name: str, at: int, text: str) -> Exception:
    errors: Mapping[str, Any] = language_config(target.language)["errors"]
    if target.language == "soql" and "." in name and kind == "unknown_field":
        head = name.split(".", 1)[0]
        if target.resolve(head) is None:
            return query_error(target.language, "unknown_relationship", relationship=head,
                               entity=target.entity, query=text, column=at + 1)
    chosen = kind if kind in errors else "unknown_field"
    return query_error(target.language, chosen, field=name, entity=target.entity, query=text, column=at + 1)


def _bind_node(node: Node, target: QueryTarget, text: str) -> Node | None:
    """*node* with unknown fields handled; ``None`` when the vendor drops it."""

    if isinstance(node, (And, Or)):
        kept = [bound for item in node.items if (bound := _bind_node(item, target, text)) is not None]
        if not kept:
            return None
        return kept[0] if len(kept) == 1 else type(node)(tuple(kept))
    if isinstance(node, Not):
        inner = _bind_node(node.item, target, text)
        return None if inner is None else Not(inner)
    if isinstance(node, Const):
        return node
    name = node.field
    if name is None or name == ELEMENT or name.startswith(ELEMENT + "/"):
        return node
    if target.resolve(name) is not None:
        return node
    if target.unknown_field == "ignore":
        return None
    if target.unknown_field == "text":
        raw = getattr(node, "raw", "") or name
        return TextMatch(None, raw, "terms", at=getattr(node, "at", 0), raw=raw)
    raise _unknown(target, "unknown_field", name, getattr(node, "at", 0), text)


def bind(query: Query, target: QueryTarget, *, text: str = "") -> Query:
    """*query* checked against *target*; raises the vendor's ``QueryError`` for what it refuses.

    *text* is the query as written, for the messages that quote it.
    """

    for name in query.select:
        if target.resolve(name) is None and target.unknown_field == "error":
            at = text.find(name) if text else 0
            raise _unknown(target, "unknown_select_field", name, max(at, 0), text)
    select = tuple(name for name in query.select if target.resolve(name) is not None)
    order: list[OrderKey] = []
    for key in query.order:
        if target.resolve(key.field) is not None:
            order.append(key)
        elif target.unknown_field == "error":
            raise _unknown(target, "unknown_order_field", key.field, key.at, text)
    where = _bind_node(query.where, target, text)
    return replace(query, where=TRUE if where is None else where, order=tuple(order), select=select)


# ---------------------------------------------------------------------------
# Values
# ---------------------------------------------------------------------------


def _lookup(record: Mapping[str, Any], path: str) -> Any:
    if path in record:
        return record[path]
    current: Any = record
    for part in re.split(r"[./]", path):
        if isinstance(current, Mapping):
            if part in current:
                current = current[part]
                continue
            folded = {str(key).casefold(): key for key in current}
            if part.casefold() in folded:
                current = current[folded[part.casefold()]]
                continue
        return _MISSING
    return current


def _scalar(value: Any) -> Any:
    if isinstance(value, Mapping):
        for key in _DISPLAY_KEYS:
            if key in value and not isinstance(value[key], (Mapping, list, tuple)):
                return value[key]
        return _MISSING
    return value


def _elements(value: Any) -> list[Any]:
    if value is _MISSING or value is None:
        return []
    if isinstance(value, (list, tuple)):
        out: list[Any] = []
        for item in value:
            out.extend(_elements(item))
        return out
    scalar = _scalar(value)
    return [] if scalar is _MISSING or scalar is None else [scalar]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


class _Context:
    def __init__(self, target: QueryTarget) -> None:
        self.target = target
        self.resolved: dict[str, tuple[str, ...]] = {}

    def keys(self, name: str) -> tuple[str, ...]:
        keys = self.resolved.get(name)
        if keys is None:
            keys = self.target.resolve(name) or (name,)
            self.resolved[name] = keys
        return keys

    def value(self, record: Mapping[str, Any], name: str, element: Any) -> Any:
        if name == ELEMENT:
            return element
        if name.startswith(ELEMENT + "/"):
            return _lookup(element, name[2:]) if isinstance(element, Mapping) else _MISSING
        for key in self.keys(name):
            found = _lookup(record, key)
            if found is not _MISSING and found is not None:
                return found
        default = self.target.default(name)
        return default if default is not None else _MISSING

    def instant(self, value: Any) -> datetime | None:
        return as_instant(value, self.target.timezone)

    def equal(self, actual: Any, expected: Value, case_sensitive: bool) -> bool:
        if isinstance(expected, datetime):
            instant = self.instant(actual)
            return instant is not None and instant == expected
        if isinstance(expected, bool):
            if isinstance(actual, bool):
                return actual is expected
            return isinstance(actual, str) and actual.strip().casefold() == str(expected).casefold()
        if isinstance(expected, (int, float)):
            number = _number(actual)
            return number is not None and number == float(expected)
        if isinstance(expected, str):
            if isinstance(actual, bool):
                return str(actual).casefold() == expected.strip().casefold()
            if isinstance(actual, (int, float)):
                number = _number(expected)
                return number is not None and number == float(actual)
            if isinstance(actual, str):
                return actual == expected if case_sensitive else actual.casefold() == expected.casefold()
        return False

    def order(self, actual: Any, expected: Value, case_sensitive: bool) -> int | None:
        """``-1``, ``0`` or ``1`` comparing *actual* to *expected*, ``None`` when incomparable."""

        left: Any
        right: Any
        if isinstance(expected, datetime):
            left, right = self.instant(actual), expected
            if left is None:
                return None
        elif isinstance(expected, bool) or isinstance(actual, bool):
            return None
        elif isinstance(expected, (int, float)):
            left, right = _number(actual), float(expected)
            if left is None:
                return None
        elif isinstance(expected, str):
            if isinstance(actual, (int, float)):
                right = _number(expected)
                if right is None:
                    return None
                left = float(actual)
            elif isinstance(actual, str):
                instant = self.instant(expected) if re.match(r"^\d{4}-\d{2}-\d{2}", expected) else None
                if instant is not None and self.instant(actual) is not None:
                    left, right = self.instant(actual), instant
                else:
                    left, right = (actual, expected) if case_sensitive else (actual.casefold(), expected.casefold())
            else:
                return None
        else:
            return None
        return (left > right) - (left < right)

    def text_of(self, record: Mapping[str, Any]) -> str:
        parts: list[str] = []
        for key in self.target.text_fields:
            for element in _elements(_lookup(record, key)):
                if isinstance(element, str):
                    parts.append(element)
        return "\n".join(parts)


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.casefold())


def _matches_terms(haystack: str, needle: str) -> bool:
    words = _tokens(haystack)
    present = set(words)
    for raw in needle.split():
        if raw.endswith("*") and len(raw) > 1:
            stems = _tokens(raw[:-1])
            if not stems:
                continue
            if not all(stem in present for stem in stems[:-1]):
                return False
            if not any(word.startswith(stems[-1]) for word in words):
                return False
            continue
        if not all(token in present for token in _tokens(raw)):
            return False
    return True


def _matches_phrase(haystack: str, needle: str) -> bool:
    words = _tokens(haystack)
    phrase = _tokens(needle)
    if not phrase:
        return True
    width = len(phrase)
    return any(words[index:index + width] == phrase for index in range(len(words) - width + 1))


def _like(pattern: str, value: str, case_sensitive: bool) -> bool:
    body = "".join(".*" if char == "%" else "." if char == "_" else re.escape(char) for char in pattern)
    return re.fullmatch(body, value, flags=0 if case_sensitive else re.IGNORECASE | re.DOTALL) is not None


def _text_match(node: TextMatch, value: str) -> bool:
    if node.mode == "terms":
        return _matches_terms(value, node.text)
    if node.mode == "phrase":
        return _matches_phrase(value, node.text)
    if node.mode == "like":
        return _like(node.text, value, node.case_sensitive)
    left, right = (value, node.text) if node.case_sensitive else (value.casefold(), node.text.casefold())
    if node.mode == "contains":
        return right in left
    if node.mode == "startswith":
        return left.startswith(right)
    if node.mode == "endswith":
        return left.endswith(right)
    # prefix: at a word boundary, as Drive's `name contains` matches.
    return any(left[index:].startswith(right) for index in range(len(left))
               if index == 0 or not left[index - 1].isalnum())


def _matches(node: Node, record: Mapping[str, Any], context: _Context, element: Any = _MISSING) -> bool:
    if isinstance(node, Const):
        return node.value
    if isinstance(node, And):
        return all(_matches(item, record, context, element) for item in node.items)
    if isinstance(node, Or):
        return any(_matches(item, record, context, element) for item in node.items)
    if isinstance(node, Not):
        return not _matches(node.item, record, context, element)
    if isinstance(node, TextMatch):
        if node.field is None:
            return _text_match(node, context.text_of(record))
        values = [item for item in _elements(context.value(record, node.field, element)) if not isinstance(item, (Mapping, list))]
        return any(_text_match(node, str(item)) for item in values)
    if isinstance(node, AnyOf):
        raw = context.value(record, node.field, element)
        if isinstance(raw, str):
            members: list[Any] = [part.strip() for part in raw.split(";")] if ";" in raw else [raw]
        elif isinstance(raw, (list, tuple)):
            members = list(raw)
        elif raw is _MISSING or raw is None:
            members = []
        else:
            members = [raw]
        return any(_matches(node.condition, record, context, _scalar(member) if not isinstance(member, Mapping) else member)
                   for member in members)
    values = _elements(context.value(record, node.field, element))
    if isinstance(node, IsEmpty):
        return all(item == "" for item in values)
    if isinstance(node, In):
        return any(context.equal(item, candidate, node.case_sensitive) for item in values for candidate in node.values)
    if isinstance(node, TimeWindow):
        for item in values:
            instant = context.instant(item)
            if instant is None:
                continue
            if (node.start is None or instant >= node.start) and (node.end is None or instant < node.end):
                return True
        return False
    assert isinstance(node, Compare)
    if not values:
        return node.op is Op.NE and node.missing_matches
    if node.op is Op.EQ:
        return any(context.equal(item, node.value, node.case_sensitive) for item in values)
    if node.op is Op.NE:
        return not any(context.equal(item, node.value, node.case_sensitive) for item in values)
    for item in values:
        sign = context.order(item, node.value, node.case_sensitive)
        if sign is None:
            continue
        if (node.op is Op.GT and sign > 0) or (node.op is Op.GE and sign >= 0) \
                or (node.op is Op.LT and sign < 0) or (node.op is Op.LE and sign <= 0):
            return True
    return False


def matches(query: Query, record: Mapping[str, Any], target: QueryTarget) -> bool:
    """Whether one record satisfies *query*'s filter."""

    return _matches(query.where, record, _Context(target))


# ---------------------------------------------------------------------------
# Ranking
# ---------------------------------------------------------------------------


def relevance_text(node: Node, negated: bool = False) -> list[str]:
    """The text of every positive search-style ``TextMatch``: what relevance scores against.

    Only ``terms`` and ``phrase`` matches are searches (JQL and CQL ``~``, KQL,
    Slack, Drive ``fullText``, ``$search``); a ``LIKE``, ``startswith`` or
    ``contains`` filter narrows without ranking, as it does at the vendor.
    """

    if isinstance(node, (And, Or)):
        return [text for item in node.items for text in relevance_text(item, negated)]
    if isinstance(node, Not):
        return relevance_text(node.item, not negated)
    if isinstance(node, TextMatch) and not negated and node.mode in ("terms", "phrase"):
        return [node.text.replace("*", "")]
    return []


def bm25(documents: Sequence[str], text: str) -> Sequence[float]:
    """The default relevance: the repository's own BM25 (``evaluate.bm25``)."""

    from ...evaluate.bm25 import Bm25

    return Bm25(list(documents)).scores(text)


def _sort_value(context: _Context, value: Any) -> tuple[int, Any]:
    elements = _elements(value)
    if not elements:
        return (-1, 0)
    first = elements[0]
    if isinstance(first, bool):
        return (2, int(first))
    if isinstance(first, (int, float)):
        return (1, float(first))
    if isinstance(first, datetime):
        return (0, first.timestamp())
    text = str(first)
    instant = context.instant(text) if re.match(r"^\d{4}-\d{2}-\d{2}", text) else None
    if instant is not None:
        return (0, instant.timestamp())
    return (3, text.casefold())


def _record_id(record: Mapping[str, Any], id_key: str) -> str:
    for key in (id_key, "fid", "id", "sys_id", "Id", "key"):
        value = record.get(key)
        if value not in (None, ""):
            return str(value)
    return ""


def execute(
    query: Query,
    records: Sequence[Mapping[str, Any]],
    target: QueryTarget,
    *,
    relevance: Relevance | None = None,
    id_key: str = "fid",
) -> QueryResult:
    """Filter, order and page *records* by a bound *query*."""

    context = _Context(target)
    hits = [index for index, record in enumerate(records) if _matches(query.where, record, context)]
    scores = [0.0] * len(records)
    text = " ".join(relevance_text(query.where))
    if text.strip() and not query.order and hits:
        documents = [context.text_of(record) for record in records]
        scores = [float(score) for score in (relevance or bm25)(documents, text)]
    ids = {index: _record_id(records[index], id_key) for index in hits}
    if query.order:
        ordered = sorted(hits, key=lambda index: ids[index])
        for key in reversed(query.order):
            null_first = (not key.descending) if key.nulls_first is None else key.nulls_first
            null_rank = (0 if null_first else 2) if not key.descending else (2 if null_first else 0)

            def sort_key(index: int, key: OrderKey = key, null_rank: int = null_rank) -> tuple[int, int, Any]:
                rank, value = _sort_value(context, context.value(records[index], key.field, _MISSING))
                return (null_rank, 0, 0) if rank < 0 else (1, rank, value)

            ordered.sort(key=sort_key, reverse=key.descending)
    elif text.strip():
        ordered = sorted(hits, key=lambda index: (-scores[index], ids[index]))
    else:
        ordered = hits
    total = len(ordered)
    page = ordered[query.offset:]
    if query.limit is not None:
        page = page[:query.limit]
    return QueryResult(
        query=query,
        matches=tuple(page),
        total=total,
        scores=tuple(scores[index] for index in page),
        select=query.select,
    )


__all__ = [
    "QueryResult",
    "Relevance",
    "bind",
    "bm25",
    "execute",
    "matches",
    "relevance_text",
]
