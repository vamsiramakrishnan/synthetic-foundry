"""A planned query, compiled into a row the connector runtime can execute.

Worldloom holds two accounts of an expected trajectory and until now they never
met. `enterprise_queries` plans a verb-level DAG and `enterprise_corpus.score_trace`
grades it as a weighted number; `connector_eval_runtime.run_eval_row` executes a
tool-level DAG and `connector_trace.grade_trace` decides nineteen assertion
kinds over it, with post-state, `for_each` and ACLs. The second is the one that
can answer "was the system actually updated", and no CLI reached it: a search
for its callers across `src/` finds only re-exports.

That is the shape of the gap this module closes. `state_equals` was already
implemented and already correct; what it lacked was a producer. So no grading
vocabulary is added here. A planned query is rewritten into the row the executor
already consumes, and the outcome kinds come along for free.

Four details of that row are not guessable and were each established by running
the executor:

**`node["tool"]` is the bare tool name.** `servicenow.search_records` raises
`KeyError: unknown servicenow tool`. The qualified spelling exists only on the
way out, where `ConnectorEmulator.call` stamps `f"{server}.{tool}"` on the span
and `grade_trace` rebuilds the same string from the node to compare against it.
A compiler that emitted the qualified name would fail the lookup and, if it
somehow got past that, would make the grader compare against
`servicenow.servicenow.search_records`.

**`node["fixture"]` is the record's internal fid**, not its external id. An
external id resolves to nothing and the node reports `not_found`, which grades
as a plausible behaviour rather than as the compiler error it is.

**Edges are two-element sequences.** `{"from": ..., "to": ...}` does not error;
it unpacks to its keys and silently mis-resolves `for_each`.

**A `model` node is refused outright**: `run_eval_row` raises
`eval row references connectors with no definition: ['model']` before executing
anything. The planner puts exactly one in every DAG, so dropping it and rewiring
its edges transitively is not an optimisation, it is the precondition for the
row running at all.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .connector_definition import (
    ConnectorDefinition,
    builtin_connector_definitions,
)
from .enterprise_corpus import QueryFixture
from .enterprise_queries import PlannedEnterpriseQuery
from .enterprise_runner import _LEGACY_OPERATIONS

#: The connector name the planner uses for its transform node. It names no
#: definition, so it cannot execute; see the module docstring.
MODEL_CONNECTOR = "model"

#: Operations that mint a record and so cannot take an alias entity: the
#: emulator has to know which concrete kind it is creating.
_WRITE_NEEDS_CONCRETE = frozenset({"create", "send", "post", "upload"})


class RowError(ValueError):
    """A planned query that cannot be compiled into an executable row.

    Carries the query id and the reason, because the interesting number when
    compiling a set is not how many succeeded but which vocabulary the failures
    name: an operation with no tool is a gap in the connector definitions, not
    a defect in this compiler.
    """

    def __init__(self, query_id: str, reason: str) -> None:
        super().__init__(f"{query_id}: {reason}")
        self.query_id = query_id
        self.reason = reason


@dataclass(frozen=True)
class CompileReport:
    """What a set of queries compiled to, and what refused."""

    rows: tuple[dict[str, Any], ...] = ()
    refusals: tuple[RowError, ...] = ()

    @property
    def compiled(self) -> int:
        return len(self.rows)

    def reasons(self) -> dict[str, int]:
        """Refusal reasons by count, most frequent first.

        The useful half: a hundred rows refused for one missing tool is one
        fix, and reading them one at a time would not say so.
        """
        counts: dict[str, int] = {}
        for refusal in self.refusals:
            counts[refusal.reason] = counts.get(refusal.reason, 0) + 1
        return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _tool_name(
    definition: ConnectorDefinition,
    entity: str,
    operation: str,
    query_id: str,
    concrete_hint: str | None = None,
) -> tuple[str, str]:
    """The bare tool and the concrete entity for one node.

    `tool_for` resolves an alias entity to its members and refuses when they
    disagree about which tool serves the operation, which is the right refusal:
    a compiler picking one arbitrarily would produce a row that executes and
    grades against the wrong tool.
    """
    canonical = _LEGACY_OPERATIONS.get(operation, operation)
    try:
        tool = definition.tool_for(entity, canonical)
    except KeyError as error:
        raise RowError(
            query_id, f"{definition.connector}/{entity} has no tool for {canonical!r}"
        ) from error

    # A create refuses an alias: "Create requires one concrete entity, not
    # alias 'file'". Reads do not, because they address a record that already
    # knows what it is. The planner names the alias and puts the concrete
    # member in the mutation's `output_format`, so the compiler resolves it
    # here rather than leaving the emulator to guess between `docx` and `xlsx`.
    members = definition.entity_members(entity)
    if len(members) == 1:
        return tool, members[0]
    if canonical in _WRITE_NEEDS_CONCRETE:
        if concrete_hint and concrete_hint in members:
            return tool, concrete_hint
        raise RowError(
            query_id,
            f"{definition.connector}/{entity} is an alias over {sorted(members)}"
            f" and {canonical!r} needs one concrete member",
        )
    return tool, entity


def _fid(records_by_id: Mapping[str, str], record_id: str | None) -> str | None:
    """The internal fid for a record id the fixture names.

    `QueryFixture` holds whatever id `materialize_corpus` recorded. The runtime
    joins on `fid`, so anything else silently resolves to nothing.
    """
    if record_id is None:
        return None
    return records_by_id.get(record_id, record_id)


def compile_row(
    query: PlannedEnterpriseQuery,
    fixture: QueryFixture,
    records: Iterable[Mapping[str, Any]] = (),
    *,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> dict[str, Any]:
    """One planned query as a row `run_eval_row` executes and `grade_trace` grades.

    Raises `RowError` when the query names a connector or operation the
    installed definitions cannot execute. That is a refusal rather than a
    best effort: a row that silently drops its write node would grade clean
    while testing nothing, which is the failure this whole seam exists to stop.
    """
    available = dict(definitions or builtin_connector_definitions())
    by_external = {
        str(record.get("id")): str(record.get("fid"))
        for record in records
        if record.get("id") and record.get("fid")
    }

    planned = [dict(node) for node in query.expected_dag]
    # Transitive rewiring: a node depending on the transform inherits the
    # transform's own dependencies, so read -> transform -> write becomes
    # read -> write rather than an orphaned write.
    dropped = {
        str(node["id"]) for node in planned if node.get("connector") == MODEL_CONNECTOR
    }

    def resolve(dep: str, seen: frozenset[str] = frozenset()) -> list[str]:
        if dep not in dropped or dep in seen:
            return [] if dep in dropped else [dep]
        parent = next(node for node in planned if str(node["id"]) == dep)
        return [
            grand
            for further in parent.get("depends_on", ())
            for grand in resolve(str(further), seen | {dep})
        ]

    mutation = query.generation.mutation
    sources = {
        f"{source.connector}:{source.entity}": source
        for source in query.generation.source_requirements
    }

    nodes: list[dict[str, Any]] = []
    edges: list[list[str]] = []
    for node in planned:
        node_id = str(node["id"])
        if node_id in dropped:
            continue
        connector = str(node["connector"])
        entity = str(node["entity"])
        definition = available.get(connector)
        if definition is None:
            raise RowError(query.id, f"connector {connector!r} has no definition")
        is_destination = (connector, entity) == (mutation.connector, mutation.entity)
        tool, concrete = _tool_name(
            definition,
            entity,
            str(node["kind"]),
            query.id,
            mutation.output_format if is_destination else None,
        )

        key = f"{connector}:{entity}"
        # A source read takes its own record; a write or verify takes the
        # destination. The two coincide when a workflow reads and writes one
        # entity, which is why this asks what the node is for rather than
        # which key happens to hold a record.
        if key in sources and not is_destination:
            chosen = next(iter(fixture.input_record_ids.get(key, ())), None)
        else:
            chosen = fixture.destination_record_id or next(
                iter(fixture.input_record_ids.get(key, ())), None
            )

        compiled: dict[str, Any] = {
            "id": node_id,
            "server": connector,
            "tool": tool,
            "entity": concrete,
            "op": str(node["kind"]),
        }
        target = _fid(by_external, chosen)
        if target is not None:
            compiled["fixture"] = target
        if _LEGACY_OPERATIONS.get(str(node["kind"]), str(node["kind"])) in _WRITE_NEEDS_CONCRETE:
            # `invalidRequest: name is required`. Derived from the query id so
            # two compilations of one corpus produce the same bytes; nothing
            # here draws or reads a clock.
            compiled["payload"] = {"name": f"{query.id[:12]}-{node_id}"}
        nodes.append(compiled)
        for dep in node.get("depends_on", ()):
            for source_id in resolve(str(dep)):
                edges.append([source_id, node_id])

    if not nodes:
        raise RowError(query.id, "every node was a model transform")

    return {
        "id": query.id,
        "expected_dag": {"nodes": nodes, "edges": edges},
        "assertions": _assertions(query, fixture, nodes, edges, by_external),
        "ground_truth": {},
    }


def _assertions(
    query: PlannedEnterpriseQuery,
    fixture: QueryFixture,
    nodes: Sequence[Mapping[str, Any]],
    edges: Sequence[Sequence[str]],
    by_external: Mapping[str, str],
) -> list[dict[str, Any]]:
    """What the query already declares, restated as things the grader checks.

    Nothing is invented here. Every assertion is a requirement the planner
    already wrote down, in the vocabulary `grade_trace` decides.
    """
    out: list[dict[str, Any]] = [
        {"type": "tool_called", "node": str(node["id"])} for node in nodes
    ]
    out += [
        {"type": "order", "before": str(source), "after": str(target)}
        for source, target in edges
    ]

    # The resultset outcome: a read must return the records the fixture chose,
    # not merely happen.
    for node in nodes:
        op = str(node.get("op"))
        if op not in {"read", "search", "extract", "get"}:
            continue
        if op in {"search", "extract"}:
            # A search may legitimately return the whole declared set.
            key = f"{node['server']}:{node.get('entity')}"
            wanted = [
                by_external.get(rid, rid)
                for rid in fixture.input_record_ids.get(key, ())
            ]
        else:
            # A get addresses exactly one record: the one the node names. The
            # first draft asserted every record under the key, which failed a
            # correct run for reading one record when the fixture held two.
            wanted = [str(node["fixture"])] if node.get("fixture") else []
        if wanted:
            out.append(
                {"type": "reads_contain", "node": str(node["id"]), "records": wanted}
            )

    mutation = query.generation.mutation
    write = next(
        (
            node
            for node in nodes
            if (node["server"], node.get("entity")) == (mutation.connector, mutation.entity)
            and str(node.get("op")) not in {"read", "search", "extract", "get", "readback", "cross_system"}
        ),
        None,
    )
    if write is not None and query.generation.artifact is not None:
        # The file outcome. `artifact_created` checks a non-errored span on the
        # node; the shape of the produced file is not checked anywhere yet, and
        # this does not pretend otherwise.
        out.append({"type": "artifact_created", "node": str(write["id"])})
    return out


def runtime_records(records: Iterable[Any]) -> tuple[dict[str, Any], ...]:
    """`ConnectorRecord`s in the shape `ConnectorEmulator` indexes.

    The two halves of this engine disagree about a record as well as about a
    DAG. `ConnectorRecord` names the identity `id` and the system `connector`;
    the emulator requires `fid` and `server` and raises `KeyError: 'fid'` on
    anything else, before a single node runs. That is the whole translation,
    and it is here rather than at the call site because a row's `fixture`
    values are fids, so the row and the records have to be produced from one
    account of what a record is called.

    `title` is folded into `fields` when the record carries one, because the
    emulator shapes payloads out of `fields` and a title left outside it is
    invisible to every projection.
    """
    out: list[dict[str, Any]] = []
    for record in records:
        held = record.model_dump() if hasattr(record, "model_dump") else dict(record)
        fields = dict(held.get("fields") or {})
        if held.get("title") and "title" not in fields:
            fields["title"] = held["title"]
        out.append(
            {
                **held,
                "fid": str(held.get("fid") or held.get("id")),
                "server": str(held.get("server") or held.get("connector")),
                "fields": fields,
            }
        )
    return tuple(out)


def compile_rows(
    queries: Iterable[PlannedEnterpriseQuery],
    fixtures: Iterable[QueryFixture],
    records: Iterable[Mapping[str, Any]] = (),
    *,
    definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> CompileReport:
    """Compile a whole set, keeping what refused rather than dropping it."""
    by_query = {fixture.query_id: fixture for fixture in fixtures}
    materialized = [dict(record) for record in records]
    rows: list[dict[str, Any]] = []
    refusals: list[RowError] = []
    for query in queries:
        fixture = by_query.get(query.id)
        if fixture is None:
            refusals.append(RowError(query.id, "no fixture"))
            continue
        try:
            rows.append(
                compile_row(query, fixture, materialized, definitions=definitions)
            )
        except RowError as error:
            refusals.append(error)
    return CompileReport(rows=tuple(rows), refusals=tuple(refusals))


__all__ = [
    "MODEL_CONNECTOR",
    "CompileReport",
    "RowError",
    "compile_row",
    "compile_rows",
]
