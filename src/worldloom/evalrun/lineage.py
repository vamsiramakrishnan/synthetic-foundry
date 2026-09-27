"""Plans as data flow: which earlier call each call consumed, read off the values that moved.

A plan is a DAG of calls, and a DAG's edges are dependencies: call B depends
on call A when B could not have been written without something A returned.
Ordering says nothing about that. Two reads that happened to run one after
the other are not a chain, and a write that names a record id it never saw
is not downstream of the search that would have found it, however early the
search ran. So the executed DAG is derived here from the values themselves:
a value call A returned that reappears in call B's arguments makes B depend
on A.

**What a call produced.** Only a call that succeeded produced anything, and
only what the agent saw: the response the surface handed back (for a run
served by Anvil, the vendor-shaped response Anvil answered with, not the
replay's). Every scalar in it that passes the distinctiveness rule below is a
produced value, and so is every identifier-shaped token inside a longer
string (``see OPS-7``). A record the call returned or wrote is produced under
each handle the surface resolves to it (its fid, ident and external id),
because the in-process surface accepts those as well as the payload's own ids.

**What a call consumed.** Every scalar in its request (for an Anvil-served
run, the path, query string and body the agent actually sent), every
identifier-shaped token inside a string, the literal values of a native
query (JQL, SOQL, an encoded query, OData, CQL, KQL, Drive and Slack search)
read through the shared evaluator in ``worldloom.connectors.query`` (never a
parser of this module's own), and the records the call targeted (the record
a get, update or delete resolved, not the rows a search returned).

**Distinctiveness.** A value links two calls only when it could not have
been arrived at by coincidence. Booleans and nulls never link. A number
links when its integer part has at least five digits (record ids, account
numbers; not a count, a state code or a year). A string links when it is an
email address; or contains a digit and is at least three characters long
(``OPS-1``, ``INC0001001``, a sys_id), with an all-digit string held to the
five-digit rule; or, with no digit at all, is at least sixteen characters
long (a copied title or an opaque cursor). ISO dates and timestamps never
link: every record of a corpus carries the same few. Within one response, a
value carried by more than half the items of a list of three or more is a
shared attribute (a status, an assignee, a project key), not an identity,
and does not link.

**Stated values.** A value the case's request states (as a whole token, or a
phrase inside it) is the user's, not a call's: it links nothing, whoever
returned it later.

**The same value from several calls.** The link goes to the most recent
earlier call that produced it; the others are recorded as alternatives, and
the link is ambiguous. An edge graded against the gold DAG is honoured when
the gold producer is the chosen call or one of its alternatives.

**Pagination.** A call that repeats the most recent call to the same tool
with the same non-paging arguments and advances a paging argument (an
offset past zero, a page past one, or any cursor) depends on that call.

**Unsourced values.** A record a call targeted, or a record handle in its
request, that no earlier call produced and the request did not state is
unsourced: the agent guessed it or had it hardcoded. It is counted, never
linked.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator, Mapping, Sequence
from typing import Any, Literal

from pydantic import model_serializer

from ..models import Model

#: Bumped by hand whenever the rules above change which calls a trace links.
LINEAGE_VERSION = "1"

_STOP = frozenset({"true", "false", "null", "none", "n/a", "nan", "yes", "no"})
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?)?$")
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")
_TOKEN = re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9._:@/+-]*[A-Za-z0-9])?")
_EMAIL_IN = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
#: Request keys whose value is a native query string.
_QUERY_KEYS = frozenset({"query", "jql", "soql", "q", "sysparm_query", "filter", "$filter", "cql", "search", "$search", "kql"})
#: Request keys that page: left out when two calls are compared as the same request.
_PAGING_KEYS = frozenset({
    "start_at", "startat", "offset", "page", "page_token", "pagetoken", "cursor", "next", "after", "skip", "$skip",
    "sysparm_offset", "nextpagetoken", "next_page_token", "max_results", "maxresults", "limit", "$top", "top",
    "sysparm_limit", "per_page", "page_size", "pagesize", "count", "starting_after", "continuation",
})
#: Of those, the ones that say *which* page: a call that sets one past its first value is a continuation.
_OFFSET_KEYS = frozenset({"start_at", "startat", "offset", "skip", "$skip", "sysparm_offset"})
_PAGE_KEYS = frozenset({"page"})
_CURSOR_KEYS = frozenset({"page_token", "pagetoken", "cursor", "next", "after", "nextpagetoken", "next_page_token",
                          "starting_after", "continuation"})
_SEARCH_OPS = frozenset({"search", "list"})
_CREATE_OPS = frozenset({"create", "send", "post", "upload", "reply", "forward", "comment", "draft"})
#: Values are kept on a link for review, clipped: a link is evidence, not a copy of the payload.
_VALUE_LIMIT = 3
_VALUE_CLIP = 80


# -- the distinctiveness rule --------------------------------------------------------


def canonical(value: Any) -> str | None:
    """*value* as the string a link compares, or ``None`` when it is not a scalar that can link."""

    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if value != value or value in (float("inf"), float("-inf")):
            return None
        return str(int(value)) if value.is_integer() else repr(value)
    if isinstance(value, str):
        text = value.strip()
        return text or None
    return None


def distinctive(text: str) -> bool:
    """Whether a canonical value is distinctive enough to link two calls (the rule in the module docstring)."""

    if len(text) < 3 or text.casefold() in _STOP or _DATE.match(text):
        return False
    if _EMAIL.match(text):
        return True
    digits = sum(1 for char in text if char.isdigit())
    if digits:
        stripped = text.lstrip("-+")
        if stripped.replace(".", "", 1).isdigit():
            integral = stripped.split(".", 1)[0]
            return len(integral) >= 5
        return True
    return len(text) >= 16


def _tokens(text: str) -> Iterator[str]:
    """Identifier-shaped tokens and email addresses inside a longer string."""

    for match in _EMAIL_IN.finditer(text):
        yield match.group(0)
    for match in _TOKEN.finditer(text):
        token = match.group(0)
        if token != text and any(char.isdigit() for char in token):
            yield token
            # A path or a key=value pair holds its identifier after the separator.
            for piece in re.split(r"[/:=]", token):
                if piece and piece != token and any(char.isdigit() for char in piece):
                    yield piece


def _walk(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            yield from _walk(value[key], (*path, str(key)))
    elif isinstance(value, (list, tuple)):
        for item in value:
            yield from _walk(item, (*path, "[]"))
    else:
        yield path, value


def _shared_attributes(response: Any) -> set[str]:
    """Values carried by more than half the items of a list of three or more, anywhere in *response*."""

    shared: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            for key in sorted(value, key=str):
                visit(value[key])
        elif isinstance(value, (list, tuple)):
            items = [item for item in value if isinstance(item, Mapping)]
            if len(items) >= 3:
                counts: dict[str, int] = {}
                for item in items:
                    seen = {text for _, leaf in _walk(item) if (text := canonical(leaf)) is not None}
                    for text in seen:
                        counts[text] = counts.get(text, 0) + 1
                shared.update(text for text, count in counts.items() if count * 2 > len(items))
            for item in value:
                visit(item)

    visit(response)
    return shared


def produced_values(response: Any) -> set[str]:
    """The distinctive values one response exposes, shared attributes removed."""

    out: set[str] = set()
    for _, leaf in _walk(response):
        text = canonical(leaf)
        if text is None:
            continue
        if distinctive(text):
            out.add(text)
        if isinstance(leaf, str):
            out.update(token for token in _tokens(text) if distinctive(token))
    return out - _shared_attributes(response)


def _query_literals(definitions: Mapping[str, Any], tool: str, text: str) -> list[str]:
    """The literal values of a native query, read by the shared evaluator; empty when it cannot read it."""

    from datetime import datetime

    from ..connectors.query import (
        AnyOf,
        Compare,
        In,
        Node,
        QueryError,
        TextMatch,
        canonical_language,
        parse,
        tool_language,
    )
    from ..connectors.query.ast import And, Not, Or

    connector, _, name = tool.partition(".")
    definition = definitions.get(connector)
    if definition is None:
        return []
    try:
        language = tool_language(definition, name) or canonical_language(str(definition.query_language))
        if language is None:
            return []
        parsed = parse(language, text, clock=datetime.fromisoformat(str(definition.clock)))
    except (QueryError, ValueError, TypeError, KeyError):
        return []
    found: list[str] = []

    def walk(node: Node) -> None:
        if isinstance(node, (And, Or)):
            for item in node.items:
                walk(item)
        elif isinstance(node, Not):
            walk(node.item)
        elif isinstance(node, AnyOf):
            walk(node.condition)
        elif isinstance(node, Compare):
            if (value := canonical(node.value)) is not None:
                found.append(value)
        elif isinstance(node, In):
            found.extend(value for item in node.values if (value := canonical(item)) is not None)
        elif isinstance(node, TextMatch):
            if (value := canonical(node.text)) is not None:
                found.append(value)

    walk(parsed.where)
    return found


def consumed_values(request: Any, *, tool: str = "", definitions: Mapping[str, Any] | None = None) -> set[str]:
    """Every value one request carries that could have come from an earlier response."""

    out: set[str] = set()
    for path, leaf in _walk(request):
        text = canonical(leaf)
        if text is None:
            continue
        out.add(text)
        if isinstance(leaf, str):
            out.update(_tokens(text))
            if path and path[-1].casefold() in _QUERY_KEYS and definitions:
                out.update(_query_literals(definitions, tool, text))
    return out


def stated_values(query: str) -> tuple[frozenset[str], str]:
    """The request's own tokens (casefolded) and its whole text, for the stated-value check."""

    folded = query.casefold()
    tokens = {match.group(0).casefold() for match in _TOKEN.finditer(query)}
    tokens.update(match.group(0).casefold() for match in _EMAIL_IN.finditer(query))
    return frozenset(tokens), folded


def is_stated(value: str, stated: tuple[frozenset[str], str]) -> bool:
    tokens, text = stated
    folded = value.casefold()
    if folded in tokens:
        return True
    return (" " in folded or len(folded) >= 16) and folded in text


# -- the lineage -------------------------------------------------------------------------


class LineageLink(Model):
    """One dependency: *consumer* used what *producer* returned."""

    consumer: str
    producer: str
    #: ``value``: a returned value reappeared; ``record``: the call targeted a
    #: record the producer returned or wrote; ``page``: a continuation.
    via: Literal["value", "record", "page"]
    #: A few of the values that carried the link, clipped (review evidence).
    values: tuple[str, ...] = ()
    #: Other earlier calls that produced the same values: the link is ambiguous when non-empty.
    alternatives: tuple[str, ...] = ()


class SpanLineage(Model):
    span: str
    consumed_from: tuple[str, ...] = ()
    links: tuple[LineageLink, ...] = ()
    #: Records (by fid) the call referenced that no earlier call produced and the request did not state.
    unsourced: tuple[str, ...] = ()
    #: Values skipped because the request itself states them.
    stated: int = 0


class Lineage(Model):
    """The data-flow parents of every span of one run."""

    version: str = LINEAGE_VERSION
    spans: tuple[SpanLineage, ...]

    def consumed_from(self) -> dict[str, tuple[str, ...]]:
        return {item.span: item.consumed_from for item in self.spans}

    def links(self) -> tuple[LineageLink, ...]:
        return tuple(link for item in self.spans for link in item.links)


def _span(raw: Any) -> dict[str, Any]:
    from .grading import _span as materialize

    return materialize(raw)


def _tool_op(definitions: Mapping[str, Any], tool: str) -> str | None:
    connector, _, name = tool.partition(".")
    definition = definitions.get(connector)
    if definition is None:
        return None
    try:
        return str(definition.tool(name).op)
    except KeyError:
        return None


def _paging(request: Mapping[str, Any]) -> tuple[str, bool]:
    """The request with its paging arguments removed (as a comparable key), and whether it asks for a later page."""

    later = False

    def strip(value: Any) -> Any:
        nonlocal later
        if isinstance(value, Mapping):
            kept = {}
            for key in sorted(value, key=str):
                folded = str(key).casefold()
                if folded in _PAGING_KEYS:
                    raw = value[key]
                    if folded in _OFFSET_KEYS and _number(raw) > 0:
                        later = True
                    elif folded in _PAGE_KEYS and _number(raw) > 1:
                        later = True
                    elif folded in _CURSOR_KEYS and raw not in (None, "", 0):
                        later = True
                    continue
                kept[str(key)] = strip(value[key])
            return kept
        if isinstance(value, (list, tuple)):
            return [strip(item) for item in value]
        return value

    return json.dumps(strip(request), sort_keys=True, default=str), later


def _number(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _clip(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(value if len(value) <= _VALUE_CLIP else value[:_VALUE_CLIP - 1] + "~" for value in sorted(values)[:_VALUE_LIMIT])


def _credit(chosen: dict[int, dict[str, Any]], producer: int, via: str, value: str, alternatives: Iterable[int]) -> None:
    entry = chosen.setdefault(producer, {"via": set(), "values": set(), "alternatives": set()})
    entry["via"].add(via)
    entry["values"].add(value)
    entry["alternatives"].update(alt for alt in alternatives if alt != producer)


def derive_lineage(spans: Sequence[Any], *, query: str = "", definitions: Mapping[str, Any] | None = None,
                   before: Mapping[str, Mapping[str, Any]] | None = None,
                   after: Mapping[str, Mapping[str, Any]] | None = None,
                   observations: Mapping[str, Mapping[str, Any]] | None = None) -> Lineage:
    """The data-flow parents of every span, by the rules in the module docstring.

    *observations* overrides, per span id, what the agent sent (``request``)
    and saw (``response``): an Anvil-served run passes the vendor request and
    response here, since the span's own ``args`` and ``result`` are the
    replay's. *before* and *after* are the run's snapshots, read only for a
    record's handles (fid, ident, external id).
    """

    known = dict(definitions or {})
    records: dict[str, Mapping[str, Any]] = {**dict(before or {}), **dict(after or {})}
    stated = stated_values(query)
    materialized = [_span(span) for span in spans]
    seen = dict(observations or {})

    handle_index: dict[str, str] | None = None

    def handles(fid: str) -> set[str]:
        record = records.get(fid) or {}
        out = {fid}
        for key in ("ident", "external_id"):
            if (value := canonical(record.get(key))) is not None:
                out.add(value)
        return out

    def record_of(value: str) -> str | None:
        nonlocal handle_index
        if value in records:
            return value
        if handle_index is None:
            handle_index = {}
            for fid in sorted(records):
                for handle in sorted(handles(fid)):
                    handle_index.setdefault(handle, fid)
        return handle_index.get(value)

    # Per span: what it produced (value -> span indices), its target records, its request.
    produced_by: dict[str, list[int]] = {}
    record_by: dict[str, list[int]] = {}
    requests: list[Any] = []
    targets: list[tuple[str, ...]] = []
    for index, span in enumerate(materialized):
        span_id = str(span.get("id"))
        observed = seen.get(span_id) or {}
        request = observed.get("request", span.get("args") or {})
        response = observed.get("response", span.get("result"))
        requests.append(request)
        tool = str(span.get("tool", ""))
        op = _tool_op(known, tool)
        touched = tuple(str(fid) for fid in (*span.get("reads", ()), *span.get("writes", ())))
        if op in _SEARCH_OPS or op in _CREATE_OPS:
            targets.append(())
        else:
            targets.append(tuple(dict.fromkeys(str(fid) for fid in (*span.get("reads", ()), *span.get("writes", ())))))
        if span.get("error"):
            continue
        for value in produced_values(response):
            produced_by.setdefault(value, []).append(index)
        for fid in touched:
            record_by.setdefault(fid, []).append(index)
            for handle in handles(fid):
                if distinctive(handle) or handle == fid:
                    produced_by.setdefault(handle, []).append(index)

    out: list[SpanLineage] = []
    last_request: dict[tuple[str, str], int] = {}
    for index, span in enumerate(materialized):
        span_id = str(span.get("id"))
        tool = str(span.get("tool", ""))
        request = requests[index]
        # producer index -> how it was consumed: link kinds, values, alternative producers
        chosen: dict[int, dict[str, Any]] = {}
        stated_count = 0
        unsourced: set[str] = set()

        own = {str(fid) for fid in span.get("writes", ())}
        values = consumed_values(request, tool=tool, definitions=known)
        for value in sorted(values):
            candidates = [at for at in produced_by.get(value, ()) if at < index]
            if not candidates:
                named = record_of(value) if (len(value) >= 3 and value.casefold() not in _STOP) else None
                if named is not None and named not in own and not is_stated(value, stated) \
                        and not any(at < index for at in record_by.get(named, ())):
                    unsourced.add(named)
                continue
            if is_stated(value, stated):
                stated_count += 1
                continue
            _credit(chosen, candidates[-1], "value", value, candidates[:-1])
        for fid in targets[index]:
            candidates = [at for at in record_by.get(fid, ()) if at < index]
            if not candidates:
                if not any(is_stated(handle, stated) for handle in handles(fid)):
                    unsourced.add(fid)
                continue
            _credit(chosen, candidates[-1], "record", fid, candidates[:-1])
        if isinstance(request, Mapping):
            key, later = _paging(request)
            previous = last_request.get((tool, key))
            if later and previous is not None:
                _credit(chosen, previous, "page", "page", ())
            last_request[(tool, key)] = index
        links: list[LineageLink] = []
        for producer in sorted(chosen):
            entry = chosen[producer]
            via = "record" if "record" in entry["via"] else ("value" if "value" in entry["via"] else "page")
            links.append(LineageLink(
                consumer=span_id, producer=str(materialized[producer].get("id")), via=via,  # type: ignore[arg-type]
                values=_clip(value for value in entry["values"] if value != "page"),
                alternatives=tuple(str(materialized[alt].get("id")) for alt in sorted(entry["alternatives"])),
            ))
        out.append(SpanLineage(span=span_id, consumed_from=tuple(link.producer for link in links), links=tuple(links),
                               unsourced=tuple(sorted(unsourced)), stated=stated_count))
    return Lineage(spans=tuple(out))


def with_lineage(spans: Sequence[Mapping[str, Any]], lineage: Lineage) -> tuple[dict[str, Any], ...]:
    """The ledger's span dicts with ``consumed_from`` set to the data-flow parents."""

    parents = lineage.consumed_from()
    return tuple({**dict(span), "consumed_from": list(parents.get(str(span.get("id")), ()))} for span in spans)


# -- the executed DAG, graded against the gold DAG ------------------------------------------------


class ExecutedNode(Model):
    id: str
    label: str
    connector: str
    kind: str
    entity: str = ""
    spans: tuple[str, ...]
    #: The gold node it matched, when it matched one.
    gold: str | None = None


class ExecutedEdge(Model):
    source: str
    target: str
    via: tuple[str, ...]
    #: A few of the values that carried it, clipped (review evidence).
    values: tuple[str, ...] = ()
    #: Other executed nodes that produced the same values.
    alternatives: tuple[str, ...] = ()


class ExecutedDag(Model):
    """The run's DAG: one node per plan step the calls served, edges from lineage."""

    nodes: tuple[ExecutedNode, ...]
    edges: tuple[ExecutedEdge, ...]
    #: The longest dependency chain, in nodes.
    depth: int
    #: Sequential steps the run took: spans, with calls that overlapped counted once.
    steps: int


class DeclaredDivergence(Model):
    """The DAG the agent declared against the DAG its calls formed."""

    declared: int
    executed: int
    matched: int
    declared_not_executed: tuple[str, ...] = ()
    executed_not_declared: tuple[str, ...] = ()
    #: Declared dependencies with no data-flow path between the executed counterparts.
    edges_dropped: tuple[tuple[str, str], ...] = ()
    #: Data-flow edges the declared plan does not have as a dependency.
    edges_added: tuple[tuple[str, str], ...] = ()
    #: The declared DAG's own dependencies against the gold DAG's edges.
    declared_edge_precision: float | None = None
    declared_edge_recall: float | None = None
    node_agreement: float
    edge_agreement: float | None = None
    #: Mean of the two agreements; 1.0 means the agent did what it said.
    agreement: float


class DagGrade(Model):
    """The executed DAG against the gold DAG, edge by edge."""

    version: str = LINEAGE_VERSION
    executed: ExecutedDag
    #: Gold edges by kind: ``data`` (the consumer binds the producer's output
    #: or acts on its record), ``control`` (a branch condition reads it),
    #: ``order`` (sequence only). Only data edges are graded as lineage.
    gold_data_edges: int
    gold_control_edges: int = 0
    gold_order_edges: int = 0
    #: Lineage edges between executed nodes that both matched a gold node.
    executed_edges: int
    honoured: int
    edge_precision: float | None = None
    edge_recall: float | None = None
    #: Gold data edges the run did not carry: the consumer ran without the producer's output.
    missing: tuple[tuple[str, str], ...] = ()
    #: Lineage edges between matched nodes that no gold edge or ancestry accounts for.
    spurious: tuple[tuple[str, str], ...] = ()
    #: ``(consumer, gold producer, actual producer)``.
    wrong_source: tuple[tuple[str, str, str], ...] = ()
    #: Gold nodes on a branch the data did not select that the run executed anyway.
    wrong_branch: tuple[str, ...] = ()
    #: Pairs of matched read nodes with no dependency either way, and those run one after the other.
    parallelisable: int = 0
    serialised: tuple[tuple[str, str], ...] = ()
    ambiguous_links: int = 0
    #: Record references no earlier call produced and the request did not state (guessed or hardcoded).
    unsourced: int = 0
    declared: DeclaredDivergence | None = None
    score: float | None = None
    findings: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_absent(self, handler: Any) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("declared") is None:
            data.pop("declared", None)
        return data


def _row_nodes(case: Any) -> dict[str, Mapping[str, Any]]:
    return {str(node.get("id")): node for node in (case.row.get("expected_dag") or {}).get("nodes", ())}


def _references(raw: Mapping[str, Any]) -> tuple[set[str], set[str]]:
    """The nodes a row node binds (data) and the node its condition reads (control)."""

    data: set[str] = set()
    for reference in (raw.get("bindings") or {}).values():
        if isinstance(reference, Mapping) and reference.get("node"):
            data.add(str(reference["node"]))
    iteration = raw.get("for_each")
    if isinstance(iteration, Mapping) and iteration.get("node"):
        data.add(str(iteration["node"]))
    control: set[str] = set()
    condition = raw.get("condition")
    if isinstance(condition, Mapping):
        reference = condition.get("reference")
        if isinstance(reference, Mapping) and reference.get("node"):
            control.add(str(reference["node"]))
    return data, control


def gold_edge_kinds(case: Any) -> dict[tuple[str, str], str]:
    """Every gold edge between tool nodes (transforms compressed out), with its kind."""

    from .grading import _tool_edges

    rows = _row_nodes(case)
    transforms = set(case.plan.of_kind("transform"))
    incoming: dict[str, list[str]] = {}
    for source, target in case.plan.edges:
        incoming.setdefault(target, []).append(source)
    nodes = {node.id: node for node in case.plan.nodes}

    def expand(name: str, trail: frozenset[str] = frozenset()) -> set[str]:
        if name not in transforms:
            return {name}
        if name in trail:
            return set()
        out: set[str] = set()
        for parent in (*incoming.get(name, ()), *nodes[name].depends_on):
            out |= expand(parent, trail | {name})
        return out

    kinds: dict[tuple[str, str], str] = {}
    for producer, consumer in _tool_edges(case):
        raw = rows.get(consumer, {})
        data, control = _references(raw)
        data_sources = {found for name in data for found in expand(name)}
        control_sources = {found for name in control for found in expand(name)}
        first, then = nodes.get(producer), nodes.get(consumer)
        if producer in data_sources:
            kind = "data"
        elif producer in control_sources:
            kind = "control"
        elif not data and not control and first is not None and then is not None and (
                (first.fixture and first.fixture == then.fixture)
                or (then.kind == "verify" and first.kind == "write")):
            # A row with no bindings (the legacy contract) still says the
            # consumer acts on the producer's record: the same fixture, or a
            # readback of what the write made.
            kind = "data"
        else:
            kind = "order"
        kinds[(producer, consumer)] = kind
    return kinds


def _closure(edges: Iterable[tuple[str, str]]) -> dict[str, set[str]]:
    """Ancestors of every node over *edges*."""

    parents: dict[str, set[str]] = {}
    for source, target in edges:
        parents.setdefault(target, set()).add(source)
    memo: dict[str, set[str]] = {}

    def ancestors(node: str, trail: frozenset[str] = frozenset()) -> set[str]:
        if node in memo:
            return memo[node]
        found: set[str] = set()
        for parent in parents.get(node, ()):
            if parent in trail:
                continue
            found.add(parent)
            found |= ancestors(parent, trail | {node})
        memo[node] = found
        return found

    nodes = set(parents) | {source for sources in parents.values() for source in sources}
    return {node: ancestors(node) for node in sorted(nodes)}


def _leaves(value: Any, path: tuple[str, ...] = ()) -> Iterator[tuple[tuple[str, ...], Any]]:
    if isinstance(value, Mapping):
        for key in sorted(value, key=str):
            yield from _leaves(value[key], (*path, str(key)))
    else:
        yield path, value


def _lookup(value: Any, path: tuple[str, ...]) -> Any:
    for key in path:
        if not isinstance(value, Mapping) or key not in value:
            return _MISSING
        value = value[key]
    return value


_MISSING = object()
_LITERAL_SKIP = frozenset({"id", "start_at", "max_results"})


def wrong_branch_spans(case: Any, spans: Sequence[Mapping[str, Any]], lineage: Lineage) -> dict[str, str]:
    """Span id to the gold node it executed on a branch the observed data did not select.

    Which branch the data selected is ``grading.skipped_nodes``'s call, made
    from the results the reads returned. A span executed an untaken node when
    it carries that node's literal arguments (the two writes of a conditional
    differ by name), whatever node the service attributed it to: attribution
    by shape puts a write on the taken branch's node whenever its tool fits.
    A node with nothing literal (a readback) is on the untaken branch when it
    consumed a write that was.
    """

    from .grading import skipped_nodes

    skipped = skipped_nodes(case, spans)
    if not skipped:
        return {}
    rows = _row_nodes(case)
    parents = lineage.consumed_from()
    found: dict[str, str] = {}
    for node_id in [node.id for node in case.plan.tool_nodes if node.id in skipped]:
        raw = rows.get(node_id, {})
        tool = f"{raw.get('server') or raw.get('connector')}.{raw.get('tool')}"
        literals = [(path, value) for path, value in _leaves(raw.get("payload") or {})
                    if path and path[0] not in _LITERAL_SKIP]
        data, _ = _references(raw)
        for span in spans:
            span_id = str(span.get("id"))
            if span_id in found or str(span.get("tool")) != tool:
                continue
            args = span.get("args") or {}
            if literals:
                if all(_lookup(args, path) == value for path, value in literals):
                    found[span_id] = node_id
            elif any(found.get(parent) in data for parent in parents.get(span_id, ())):
                # Nothing literal to tell the branches apart (a readback): it
                # is on the wrong branch when it consumed a wrong-branch write.
                found[span_id] = node_id
    return found


def _concurrent_of(concurrent: Sequence[Sequence[str]]) -> dict[str, int]:
    group: dict[str, int] = {}
    for index, members in enumerate(concurrent):
        for member in members:
            group[str(member)] = index
    return group


def grade_dag(case: Any, spans: Sequence[Any], lineage: Lineage, *, definitions: Mapping[str, Any],
              planned: Any = None, concurrent: Sequence[Sequence[str]] = ()) -> DagGrade:
    """The executed DAG (lineage over the implied nodes) against the gold DAG, edge by edge."""

    from .grading import _reachable, skipped_nodes
    from .stages import (
        _AgentNode,
        _gold_kind,
        _match_nodes,
        _op,
        _round,
        _tool_kind,
    )

    materialized = [_span(span) for span in spans]
    wrong = wrong_branch_spans(case, materialized, lineage)
    # One executed node per attributed plan node, per wrong-branch node, and per unattributed (tool, entity).
    keys: dict[str, str] = {}
    order: dict[str, _AgentNode] = {}
    members: dict[str, list[str]] = {}
    for index, span in enumerate(materialized):
        span_id = str(span.get("id"))
        tool = str(span.get("tool", ""))
        entity = str((span.get("args") or {}).get("entity") or "")
        if span_id in wrong:
            key, label = f"branch:{wrong[span_id]}", f"{wrong[span_id]}(untaken)"
        elif span.get("node"):
            key, label = f"node:{span['node']}", str(span["node"])
        else:
            key, label = f"call:{tool}:{entity}", tool
        keys[span_id] = key
        members.setdefault(key, []).append(span_id)
        if key not in order:
            order[key] = _AgentNode(key, tool.partition(".")[0], _tool_kind(_op(definitions, tool)), entity, index,
                                    label=label)
    agent = list(order.values())
    reachable = set(_reachable(case, skipped_nodes(case, materialized)))
    expected = [node for node in case.plan.tool_nodes if node.id in reachable]
    matched, _ = _match_nodes(expected, agent, definitions, implied=True)
    gold_of = {item.id: gold for gold, item in matched.items()}

    # Executed edges from span links.
    edge_via: dict[tuple[str, str], set[str]] = {}
    edge_alts: dict[tuple[str, str], set[str]] = {}
    edge_values: dict[tuple[str, str], set[str]] = {}
    ambiguous = 0
    unsourced = 0
    for item in lineage.spans:
        unsourced += len(item.unsourced)
        for link in item.links:
            if link.alternatives:
                ambiguous += 1
            source, target = keys.get(link.producer), keys.get(link.consumer)
            if source is None or target is None or source == target:
                continue
            edge_via.setdefault((source, target), set()).add(link.via)
            edge_values.setdefault((source, target), set()).update(link.values)
            edge_alts.setdefault((source, target), set()).update(
                keys[alt] for alt in link.alternatives if alt in keys and keys[alt] != target)
    executed_edges = sorted(edge_via)
    exec_ancestors = _closure(executed_edges)

    def depth() -> int:
        memo: dict[str, int] = {}
        parents: dict[str, list[str]] = {}
        for source, target in executed_edges:
            parents.setdefault(target, []).append(source)

        def level(node: str, trail: frozenset[str] = frozenset()) -> int:
            if node not in memo:
                memo[node] = 1 + max((level(parent, trail | {node}) for parent in parents.get(node, ())
                                      if parent not in trail), default=0)
            return memo[node]

        return max((level(node.id) for node in agent), default=0)

    groups = _concurrent_of(concurrent)
    steps = len(materialized) - sum(max(0, len([span for span in group if span in keys]) - 1) for group in concurrent)

    kinds = gold_edge_kinds(case)
    gold_ancestors = _closure(kinds)
    data_edges = [(a, b) for (a, b), kind in kinds.items() if kind == "data" and a in matched and b in matched]
    honoured_gold: list[tuple[str, str]] = []
    missing: list[tuple[str, str]] = []
    for producer, consumer in data_edges:
        pa, pb = matched[producer].id, matched[consumer].id
        if (pa, pb) in edge_via or any(target == pb and pa in edge_alts.get((source, target), ())
                                       for source, target in executed_edges):
            honoured_gold.append((producer, consumer))
        else:
            missing.append((producer, consumer))
    # A missing edge whose consumer did consume, from a node that is none of its gold producers, is a wrong source.
    wrong_source: list[tuple[str, str, str]] = []
    explained: set[tuple[str, str]] = set()
    still_missing: list[tuple[str, str]] = []
    for producer, consumer in missing:
        pb = matched[consumer].id
        gold_parents = {a for (a, b) in kinds if b == consumer}
        culprit = next((edge for edge in executed_edges if edge[1] == pb and edge not in explained
                        and gold_of.get(edge[0]) not in gold_parents
                        and gold_of.get(edge[0]) not in gold_ancestors.get(consumer, set())), None)
        if culprit is None:
            still_missing.append((producer, consumer))
            continue
        explained.add(culprit)
        wrong_source.append((consumer, producer, gold_of.get(culprit[0]) or order[culprit[0]].label))
    between = [(source, target) for source, target in executed_edges if source in gold_of and target in gold_of]
    spurious: list[tuple[str, str]] = []
    for source, target in between:
        if (source, target) in explained:
            continue
        a, b = gold_of[source], gold_of[target]
        if (a, b) in kinds or a in gold_ancestors.get(b, set()):
            continue
        spurious.append((a, b))
    precision = _round((len(between) - len(spurious) - sum(1 for edge in explained if edge in between)) / len(between)) \
        if between else None
    recall = _round(len(honoured_gold) / len(data_edges)) if data_edges else None

    # Independent reads the run could have issued together.
    reads = [node for node in expected if node.id in matched and _gold_kind(node) in {"read", "search"}]
    parallel = 0
    serialised: list[tuple[str, str]] = []
    for position, first in enumerate(reads):
        for second in reads[position + 1:]:
            if first.id in gold_ancestors.get(second.id, set()) or second.id in gold_ancestors.get(first.id, set()):
                continue
            one, two = matched[first.id].id, matched[second.id].id
            if one in exec_ancestors.get(two, set()) or two in exec_ancestors.get(one, set()):
                continue
            parallel += 1
            together = {groups.get(span) for span in members.get(one, ())} & {groups.get(span) for span in members.get(two, ())}
            if not (together - {None}):
                serialised.append((first.id, second.id))

    wrong_branch = tuple(sorted(set(wrong.values())))
    findings: set[str] = set()
    if still_missing:
        findings.add("plan.edge_missing")
    if spurious:
        findings.add("plan.edge_spurious")
    if wrong_source:
        findings.add("plan.wrong_source")
    if wrong_branch:
        findings.add("plan.wrong_branch")
    if serialised:
        findings.add("plan.serialised")
    nodes = tuple(ExecutedNode(id=item.id, label=item.label, connector=item.connector, kind=item.kind,
                               entity=item.entity, spans=tuple(members[item.id]), gold=gold_of.get(item.id))
                  for item in agent)
    edges = tuple(ExecutedEdge(source=source, target=target, via=tuple(sorted(edge_via[(source, target)])),
                               values=_clip(edge_values.get((source, target), ())),
                               alternatives=tuple(sorted(edge_alts.get((source, target), ()))))
                  for source, target in executed_edges)
    declared = _declared(case, planned, agent, executed_edges, kinds, definitions) if planned is not None else None
    scored = [value for value in (precision, recall) if value is not None]
    return DagGrade(
        executed=ExecutedDag(nodes=nodes, edges=edges, depth=depth(), steps=max(steps, 0)),
        gold_data_edges=sum(1 for kind in kinds.values() if kind == "data"),
        gold_control_edges=sum(1 for kind in kinds.values() if kind == "control"),
        gold_order_edges=sum(1 for kind in kinds.values() if kind == "order"),
        executed_edges=len(between), honoured=len(honoured_gold), edge_precision=precision, edge_recall=recall,
        missing=tuple(still_missing), spurious=tuple(sorted(set(spurious))), wrong_source=tuple(wrong_source),
        wrong_branch=wrong_branch, parallelisable=parallel, serialised=tuple(serialised),
        ambiguous_links=ambiguous, unsourced=unsourced, declared=declared,
        score=_round(sum(scored) / len(scored)) if scored else None, findings=tuple(sorted(findings)),
    )


def _declared(case: Any, planned: Any, executed: Sequence[Any], executed_edges: Sequence[tuple[str, str]],
              kinds: Mapping[tuple[str, str], str], definitions: Mapping[str, Any]) -> DeclaredDivergence:
    """The declared DAG graded on its own against gold, and against what the calls did."""

    from .stages import _declared_nodes, _entity_ok, _match_nodes, _round

    declared, _ = _declared_nodes(planned, definitions)
    # Declared against executed: shape match, greedy in declared order.
    pairs: dict[str, str] = {}
    free = list(executed)
    for node in declared:
        for candidate in free:
            if candidate.connector == node.connector and candidate.kind == node.kind and (
                    _entity_ok(definitions, node.connector, candidate.entity, node.entity or None)
                    or not candidate.entity):
                pairs[node.id] = candidate.id
                free.remove(candidate)
                break
    back = {value: key for key, value in pairs.items()}
    labels = {item.id: item.label for item in executed}
    declared_edges = [(parent, node.id) for node in planned.nodes for parent in node.depends_on]
    exec_ancestors = _closure(executed_edges)
    dropped = [(a, b) for a, b in declared_edges if a in pairs and b in pairs
               and pairs[a] not in exec_ancestors.get(pairs[b], set())]
    added = [(labels.get(a, a), labels.get(b, b)) for a, b in executed_edges if a in back and b in back
             and back[a] not in planned.ancestors(back[b])]
    comparable = [(a, b) for a, b in declared_edges if a in pairs and b in pairs]
    comparable_exec = [(a, b) for a, b in executed_edges if a in back and b in back]
    union = len(comparable) + len(comparable_exec) - (len(comparable) - len(dropped))
    edge_agreement = _round((len(comparable) - len(dropped)) / union) if union else None
    node_agreement = _round(2 * len(pairs) / (len(declared) + len(executed))) if (declared or executed) else 1.0
    # Declared against gold.
    gold_match, _ = _match_nodes(list(case.plan.tool_nodes), declared, definitions, implied=False)
    to_gold = {item.id: gold for gold, item in gold_match.items()}
    gold_ancestors = _closure(kinds)
    on_gold = [(to_gold[a], to_gold[b]) for a, b in declared_edges if a in to_gold and b in to_gold]
    precision = _round(sum(1 for a, b in on_gold if a in gold_ancestors.get(b, set())) / len(on_gold)) if on_gold else None
    gold_edges = [(a, b) for a, b in kinds if a in gold_match and b in gold_match]
    recall = _round(sum(1 for a, b in gold_edges if gold_match[a].id in planned.ancestors(gold_match[b].id))
                    / len(gold_edges)) if gold_edges else None
    agreements = [value for value in (node_agreement, edge_agreement) if value is not None]
    return DeclaredDivergence(
        declared=len(declared), executed=len(executed), matched=len(pairs),
        declared_not_executed=tuple(f"{node.id}={node.connector}:{node.kind}:{node.entity or '*'}"
                                    for node in declared if node.id not in pairs),
        executed_not_declared=tuple(f"{item.label}={item.connector}:{item.kind}:{item.entity or '*'}"
                                    for item in executed if item.id not in back),
        edges_dropped=tuple(dropped), edges_added=tuple(added),
        declared_edge_precision=precision, declared_edge_recall=recall,
        node_agreement=node_agreement, edge_agreement=edge_agreement,
        agreement=_round(sum(agreements) / len(agreements)),
    )


__all__ = [
    "LINEAGE_VERSION",
    "DagGrade",
    "DeclaredDivergence",
    "ExecutedDag",
    "ExecutedEdge",
    "ExecutedNode",
    "Lineage",
    "LineageLink",
    "SpanLineage",
    "canonical",
    "consumed_values",
    "derive_lineage",
    "distinctive",
    "gold_edge_kinds",
    "grade_dag",
    "produced_values",
    "stated_values",
    "with_lineage",
]
