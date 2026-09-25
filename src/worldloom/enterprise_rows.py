"""Compile authored enterprise requirements into executable connector rows.

Connector definitions choose tools, entity aliases and required payload fields.
Model-only nodes are removed and dependencies rewired. Outcome assertions
anchor on fixture inputs or destination records. Field contracts travel with
the row so exported plans retain their filters and native projections.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from .connector_definition import (
    ConnectorDefinition,
)
from .enterprise_corpus import QueryFixture
from .enterprise_failures import compile_failure_contract
from .enterprise_queries import PlannedEnterpriseQuery
from .enterprise_runner import canonical_operation

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
    *,
    preexisting_record: bool | None = None,
) -> tuple[str, str]:
    """The bare tool and the concrete entity for one node.

    `tool_for` resolves an alias entity to its members and refuses when they
    disagree about which tool serves the operation, which is the right refusal:
    a compiler picking one arbitrarily would produce a row that executes and
    grades against the wrong tool.
    """
    try:
        canonical = canonical_operation(operation, preexisting_record=preexisting_record)
    except ValueError as error:
        raise RowError(query_id, str(error)) from error
    try:
        members = definition.entity_members(entity)
        concrete = concrete_hint if concrete_hint in members else entity
        tool = definition.tool_for(concrete, canonical)
    except KeyError as error:
        raise RowError(
            query_id, f"{definition.connector}/{entity} has no tool for {canonical!r}"
        ) from error

    # A create refuses an alias: "Create requires one concrete entity, not
    # alias 'file'". Reads do not, because they address a record that already
    # knows what it is. The planner names the alias and puts the concrete
    # member in the mutation's `output_format`, so the compiler resolves it
    # here rather than leaving the emulator to guess between `docx` and `xlsx`.
    if len(members) == 1:
        return tool, members[0]
    if concrete != entity:
        return tool, concrete
    if canonical in _WRITE_NEEDS_CONCRETE:
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


def create_payload(
    definition: ConnectorDefinition, entity: str, query_id: str, node_id: str,
) -> dict[str, Any]:
    """An explicit reference payload satisfying the declared create contract."""
    name = f"{query_id[:12]}-{node_id}"
    supplied_by_name = {"name", "title", "summary", "Name", "Subject", "short_description", "issuetype"}
    fields = {
        field: name for field in definition.entities[entity].required_on_create
        if field not in supplied_by_name and field not in {"parent", "parents"}
    }
    return {"name": name, "fields": fields, "parent": "worldloom-eval"}


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
    if query.dimensions.get("dag_grammar") == "enterprise-dag@1":
        from .enterprise_dag_rows import compile_dag_row
        return compile_dag_row(query, fixture, records, definitions=definitions)

    from .enterprise_fields import query_connector_definitions, required_field_payload

    available = query_connector_definitions((query,), definitions)
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
    if mutation.operation == "upsert" and mutation.preexisting_record != bool(fixture.destination_record_id):
        raise RowError(query.id, "upsert fixture contradicts its preexisting_record precondition")
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
        is_source_read = str(node["kind"]) in {"read", "search", "get", "extract"}
        is_destination = (connector, entity) == (mutation.connector, mutation.entity) and not is_source_read
        tool, concrete = _tool_name(
            definition,
            entity,
            str(node["kind"]),
            query.id,
            mutation.output_format if is_destination else None,
            preexisting_record=mutation.preexisting_record if is_destination else None,
        )

        key = f"{connector}:{entity}"
        # A source read takes its own record; a write or verify takes the
        # destination. The two coincide when a workflow reads and writes one
        # entity, which is why this asks what the node is for rather than
        # which key happens to hold a record.
        if key in sources and not node.get("depends_on"):
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
            "resolved_operation": definition.tool(tool).op,
        }
        if key in sources and not node.get("depends_on"):
            source_fids = [by_external.get(rid, rid) for rid in fixture.input_record_ids.get(key, ())]
            if len(source_fids) > 1:
                compiled["fixtures"] = source_fids
        target = _fid(by_external, chosen)
        if str(node["kind"]) in {"readback", "cross_system"}:
            # Verification follows the actual write output. A create has no
            # destination fixture yet; falling back to a source id can make a
            # successful write verify the wrong object or fail with a 404.
            write_parent = next(iter(node.get("depends_on", ())), None)
            if write_parent is not None:
                compiled["reference_from"] = str(write_parent)
                target = None
        if target is not None:
            compiled["fixture"] = target
        if canonical_operation(
            str(node["kind"]),
            preexisting_record=mutation.preexisting_record if is_destination else None,
        ) in _WRITE_NEEDS_CONCRETE:
            # `invalidRequest: name is required`. Derived from the query id so
            # two compilations of one corpus produce the same bytes; nothing
            # here draws or reads a clock.
            # Required create fields belong to the definition. The synthetic
            # reference payload supplies them explicitly instead of turning a
            # missing subject/body into a supposedly valid failed trajectory.
            compiled["payload"] = create_payload(definition, concrete, query.id, node_id)
        if is_source_read and key in sources and sources[key].required_fields:
            compiled["tool"] = definition.tool_for(entity, "search")
            compiled["op"] = "search"
            compiled["payload"] = required_field_payload(sources[key], definition)
            compiled["required_fields"] = list(sources[key].required_fields)
        if is_destination and str(node["kind"]) not in {"readback", "cross_system"} and mutation.target_state is not None:
            payload = compiled.setdefault("payload", {})
            payload.setdefault("fields", {})[mutation.target_state_field] = mutation.target_state
        if "payload" in compiled:
            # Reference defaults span several APIs; the concrete tool owns its
            # wire arguments (email create, for example, accepts no parent).
            admitted = definition.tool(compiled["tool"]).params
            compiled["payload"] = {key: value for key, value in compiled["payload"].items() if key in admitted}
        nodes.append(compiled)
        for dep in node.get("depends_on", ()):
            for source_id in resolve(str(dep)):
                edges.append([source_id, node_id])

    if not nodes:
        raise RowError(query.id, "every node was a model transform")

    custom_connectors = {source.connector for source in query.generation.source_requirements if source.field_definitions}
    return compile_failure_contract({
        **({"connector_definitions": {name: available[name].served_dict() for name in sorted(custom_connectors)}} if custom_connectors else {}),
        "id": query.id,
        "expected_dag": {"nodes": nodes, "edges": edges},
        "assertions": _assertions(query, fixture, nodes, edges, by_external),
        "ground_truth": {},
        "expected_fact_ids": list(fixture.expected_fact_ids),
        "expected_evidence_ids": list(fixture.expected_evidence_ids),
        "state_overrides": [override.model_dump(mode="json") for override in fixture.overrides],
    })


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
            wanted = list(node.get("fixtures", ())) or ([str(node["fixture"])] if node.get("fixture") else [])
        if wanted:
            out.append(
                {"type": "reads_contain", "node": str(node["id"]), "records": wanted}
            )

    for node in nodes:
        if node.get("required_fields"):
            out.append({"type": "fields_used", "node": str(node["id"]), "fields": node["required_fields"], "payload_fields": node["payload"]["fields"]})

    mutation = query.generation.mutation
    write = next(
        (
            node
            for node in nodes
            if node["server"] == mutation.connector
            and str(node.get("op")) not in {"read", "search", "extract", "get", "readback", "cross_system"}
        ),
        None,
    )
    if write is not None and mutation.target_state is not None:
        if fixture.destination_record_id is None:
            raise RowError(query.id, "checked target state requires a destination fixture")
        out.append({"type": "state_equals", "node": str(write["id"]), "state": mutation.target_state, "field": mutation.target_state_field, "fixture": _fid(by_external, fixture.destination_record_id)})
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
        # `ident` is the product key the emulator shapes a native id from
        # (`connector_emulator._canonical_record` sets it from `external_id`).
        # Left unset here, a compiled row's `input_snapshots` minted a hashed
        # page id while the served emulator answered with the external id,
        # and every search over a Confluence page graded `result_mismatch`.
        ident = held.get("ident") or held.get("external_id")
        out.append(
            {
                **held,
                **fields,
                **({"ident": ident} if ident not in (None, "") else {}),
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
    "create_payload",
]
