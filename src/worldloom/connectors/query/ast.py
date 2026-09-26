"""The one filter tree every vendor query language parses into.

Frozen dataclasses, because a parsed query is a value: two parses of the same
text under the same clock compare equal, hash equal, and can key a cache. Field
names stay exactly as the query wrote them (``Account.Name``,
``from/emailAddress/address``, ``cf[10231]``); binding them to record keys is
the schema's job (``schema.QueryTarget``), so a golden AST says what the vendor
text *means* without saying anything about one corpus's records.

Every time a query states relatively (``-7d``, ``LAST_N_DAYS:30``,
``javascript:gs.daysAgoStart(7)``, ``now("-4w")``, ``on:yesterday``) is resolved
by the parser against the evaluation clock it is handed, which is the corpus's
as-of time and never the wall clock. The tree therefore holds absolute,
timezone-aware instants only, and replays byte for byte.

``at`` is the character offset of the construct in the source text. It is kept
for vendor error messages that point at a column (SOQL's
``ERROR at Row:1:Column:N``) and excluded from equality and ``repr``, so a
golden tree does not have to spell offsets.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as _field
from datetime import datetime
from enum import StrEnum
from typing import Literal, TypeAlias

Value: TypeAlias = str | int | float | bool | datetime | None
"""A literal operand. Dates are always aware ``datetime``s."""

ELEMENT = "$"
"""The field name that refers to the current element inside ``AnyOf``."""

TextMode = Literal["terms", "phrase", "prefix", "contains", "startswith", "endswith", "like"]
"""How a ``TextMatch`` matches.

``terms``: every token appears (a token written ``foo*`` matches as a prefix).
``phrase``: the tokens appear contiguously and in order.
``prefix``: some token boundary in the value starts with the text (Drive's
``name contains``). ``contains``/``startswith``/``endswith``: case-folded
substring tests. ``like``: an SQL ``LIKE`` pattern over the whole value, ``%``
and ``_`` as wildcards.
"""


class Op(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GE = "ge"
    LT = "lt"
    LE = "le"


@dataclass(frozen=True)
class Compare:
    """``field op value``. A list-valued field matches when any element does.

    ``missing_matches`` is the vendor's answer to ``field != x`` over a record
    with no value: SOQL returns the record, JQL does not.
    """

    field: str
    op: Op
    value: Value
    case_sensitive: bool = False
    missing_matches: bool = False
    at: int = _field(default=0, compare=False, repr=False)
    raw: str = _field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class In:
    """``field IN (values)``; negation is ``Not(In(...))``."""

    field: str
    values: tuple[Value, ...]
    case_sensitive: bool = False
    at: int = _field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class IsEmpty:
    """The field is absent, null, an empty string or an empty list."""

    field: str
    at: int = _field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class TimeWindow:
    """``start <= field < end``; an open side is ``None``."""

    field: str
    start: datetime | None
    end: datetime | None
    at: int = _field(default=0, compare=False, repr=False)
    raw: str = _field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class TextMatch:
    """A text condition. ``field=None`` searches every text field of the record.

    Positive text matches (those not under a ``Not``) are also what relevance
    ranking scores: see ``engine.execute``.
    """

    field: str | None
    text: str
    mode: TextMode = "terms"
    case_sensitive: bool = False
    at: int = _field(default=0, compare=False, repr=False)
    raw: str = _field(default="", compare=False, repr=False)


@dataclass(frozen=True)
class AnyOf:
    """Some element of a collection field satisfies ``condition``.

    Inside ``condition`` the element is the field named ``ELEMENT``. OData's
    ``categories/any(c: c eq 'Red')``, SOQL's ``INCLUDES`` and Drive's
    ``'id' in parents`` all land here.
    """

    field: str
    condition: Node
    at: int = _field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class And:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Or:
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Not:
    item: Node


@dataclass(frozen=True)
class Const:
    """A condition that is decided without a record: an empty filter, or a
    clause the vendor drops (ServiceNow ignores an unknown field)."""

    value: bool


Node: TypeAlias = Compare | In | IsEmpty | TimeWindow | TextMatch | AnyOf | And | Or | Not | Const

TRUE = Const(True)


@dataclass(frozen=True)
class OrderKey:
    field: str
    descending: bool = False
    nulls_first: bool | None = None
    """``None`` is the default: nulls sort as the smallest value."""
    at: int = _field(default=0, compare=False, repr=False)


@dataclass(frozen=True)
class Query:
    """One parsed vendor query.

    ``source`` is the object the query names itself (SOQL ``FROM Account``);
    languages without one leave it ``None`` and the caller's tool decides the
    pool. With no ``order``, a query with positive text conditions ranks by
    relevance (ties by record id) and one without keeps the pool's order.
    """

    language: str
    where: Node = TRUE
    source: str | None = None
    order: tuple[OrderKey, ...] = ()
    limit: int | None = None
    offset: int = 0
    select: tuple[str, ...] = ()
    source_at: int = _field(default=0, compare=False, repr=False)


def conjoin(items: list[Node] | tuple[Node, ...]) -> Node:
    """``And`` of *items*, flattened; one item is itself and none is ``TRUE``."""

    flat: list[Node] = []
    for item in items:
        if isinstance(item, And):
            flat.extend(item.items)
        elif item != TRUE:
            flat.append(item)
    if not flat:
        return TRUE
    return flat[0] if len(flat) == 1 else And(tuple(flat))


def disjoin(items: list[Node] | tuple[Node, ...]) -> Node:
    """``Or`` of *items*, flattened; one item is itself."""

    flat: list[Node] = []
    for item in items:
        if isinstance(item, Or):
            flat.extend(item.items)
        else:
            flat.append(item)
    return flat[0] if len(flat) == 1 else Or(tuple(flat))


def fields_of(node: Node) -> tuple[str, ...]:
    """Every field a tree names, in first-seen order (``ELEMENT`` excluded)."""

    seen: dict[str, None] = {}

    def walk(item: Node) -> None:
        if isinstance(item, (And, Or)):
            for child in item.items:
                walk(child)
        elif isinstance(item, Not):
            walk(item.item)
        elif isinstance(item, AnyOf):
            seen.setdefault(item.field)
            walk(item.condition)
        elif isinstance(item, Const):
            return
        elif isinstance(item, TextMatch):
            if item.field is not None and item.field != ELEMENT:
                seen.setdefault(item.field)
        elif item.field != ELEMENT:
            seen.setdefault(item.field)

    walk(node)
    return tuple(seen)


__all__ = [
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
    "TextMode",
    "TimeWindow",
    "Value",
    "conjoin",
    "disjoin",
    "fields_of",
]
