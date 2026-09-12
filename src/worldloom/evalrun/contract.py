"""The three-axis eval case: what is graded, stated before anything runs.

Worldloom already compiles an enterprise query into a row that a runtime
executes and ``grade_trace`` grades. That row is an *execution contract*: the
tools, their order, the fixture records, the designed failure. What it does
not say is what the case is *for* -- which of its parts are the plan, which
are the trajectory, and which are the outcome -- so every consumer re-derives
that from node kinds and assertion types, differently.

This module states it once. A case has three graded axes, and the split is
the point of the whole eval-execution layer:

- **plan** (querying): given the request, which DAG should the agent form.
  Nodes, edges, the shape, which nodes are reads, writes, verifies.
- **trajectory** (iteration): how the agent should get through it. Call
  budget, the designed failure and what it must block, retry discipline.
- **outcomes**: what must be true afterwards. Structured: the records the run
  must create, update or delete, by connector, entity and fixture. Unstructured:
  the artifact or answer the run must produce, and the facts it must rest on.

The case keeps the compiled row beside these, unchanged, because
``grade_trace`` remains the authority on the twenty-two assertion kinds it
decides. The axes are a reading of the row, never a replacement for it, so a
row and its case can never disagree about what a tool call was for.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import Field

from ..models import EvaluationType, Model

NodeKind = Literal["read", "search", "write", "verify", "transform"]
OutcomeKind = Literal["create", "update", "delete"]

_READ_RESOLVED = frozenset({"get", "read", "search", "download", "extract", "list"})
#: Verb-level spellings a row may use for what the connector calls a get or a
#: create; normalised so the operation counts do not split one tool three ways.
_OP_ALIASES = {"read": "get", "readback": "get", "cross_system": "get", "draft": "create"}
_VERIFY_OPS = frozenset({"readback", "cross_system"})
_CREATE_OPS = frozenset({"create", "send", "post", "upload", "transform", "reply", "forward", "comment", "draft"})
_UPDATE_OPS = frozenset({"update", "transition", "patch", "upsert", "move"})

#: Adversarial rows whose correct outcome is *no* write, matching the set
#: ``grade_trace`` refuses a write under for its ``no_write`` assertion.
_NO_WRITE_ADVERSARIAL = frozenset({"ambiguity", "wrong_system", "missing_entity", "invalid_op", "contradiction"})


class NodeContract(Model):
    id: str
    connector: str
    tool: str
    entity: str = ""
    kind: NodeKind
    op: str
    depends_on: tuple[str, ...] = ()
    optional: bool = False
    fixture: str | None = None


class PlanContract(Model):
    """The DAG the request should produce. Graded by ``grade_plan``."""

    nodes: tuple[NodeContract, ...]
    edges: tuple[tuple[str, str], ...]
    shape: str | None = None
    grammar: str | None = None

    def of_kind(self, *kinds: NodeKind) -> tuple[str, ...]:
        return tuple(node.id for node in self.nodes if node.kind in kinds)

    @property
    def connectors(self) -> tuple[str, ...]:
        return tuple(sorted({node.connector for node in self.nodes if node.kind != "transform"}))

    @property
    def tool_nodes(self) -> tuple[NodeContract, ...]:
        return tuple(node for node in self.nodes if node.kind != "transform")


class FailurePoint(Model):
    """A designed failure: the error the agent must meet, and what it must not do after."""

    node: str
    kind: str
    writes_persist: bool = False
    blocked_nodes: tuple[str, ...] = ()
    fixture: str | None = None


class TrajectoryContract(Model):
    """How the agent should move through the plan. Graded by ``grade_trajectory``."""

    max_calls: int = Field(default=1000, ge=1)
    #: Identical calls (same tool, same arguments) tolerated before the
    #: trajectory is a retry storm. Anvil's executor caps attempts the same way.
    max_identical_calls: int = Field(default=3, ge=1)
    failures: tuple[FailurePoint, ...] = ()
    #: A destructive call must be preceded by a read of its target in the
    #: same trajectory. Anvil calls this the existence check; the row's
    #: ``existence_check_first`` assertion is the same rule when present.
    existence_check_before_destructive: bool = True


class StructuredOutcome(Model):
    """One record-level side effect the run must leave behind."""

    kind: OutcomeKind
    connector: str
    entity: str
    node: str
    fixture: str | None = None
    #: Field values the record must carry afterwards (an update's target state).
    fields: dict[str, Any] = Field(default_factory=dict)
    #: True when a designed failure stops the run before this write: the
    #: expectation is then that it does *not* happen, and a record that
    #: appears anyway is the agent writing past a refusal.
    blocked: bool = False


class UnstructuredOutcome(Model):
    """The document or resultset the run must produce, and what it must rest on.

    ``required_records`` are the source records the fixture pins: the produced
    artifact (or the record the write created) must carry them, which is what
    "the memo rests on the evidence" means at the record level. The fact and
    observation ids are the provenance behind those records, kept so a reader
    can trace the chain; they are not expected to appear verbatim in prose.
    """

    format: str | None = None
    required_records: tuple[str, ...] = ()
    required_fact_ids: tuple[str, ...] = ()
    required_evidence_ids: tuple[str, ...] = ()
    sections: tuple[str, ...] = ()


class AnswerOutcome(Model):
    """The final message, graded by a rater under one rubric shape."""

    golden: str
    rubric: EvaluationType = EvaluationType.DIRECT_LOOKUP
    expects_abstention: bool = False


class OutcomeContract(Model):
    structured: tuple[StructuredOutcome, ...] = ()
    unstructured: UnstructuredOutcome | None = None
    answer: AnswerOutcome | None = None
    #: True when the correct run writes nothing: an adversarial request, or a
    #: designed failure that blocks every write and persists none.
    no_write: bool = False

    def of_kind(self, kind: OutcomeKind) -> tuple[StructuredOutcome, ...]:
        return tuple(outcome for outcome in self.structured if outcome.kind == kind)


class EvalCase(Model):
    """One executable, three-axis case. ``row`` is the compiled execution contract, untouched."""

    id: str
    query: str
    persona: str = ""
    principal: str = "agent"
    dimensions: dict[str, str] = Field(default_factory=dict)
    plan: PlanContract
    trajectory: TrajectoryContract
    outcomes: OutcomeContract
    row: dict[str, Any]


def _node_contract(node: Mapping[str, Any]) -> NodeContract:
    op = str(node.get("op") or node.get("kind") or "")
    resolved = str(node.get("resolved_operation") or _OP_ALIASES.get(op, op))
    if node.get("node_kind"):
        kind = str(node["node_kind"])
    elif op in _VERIFY_OPS:
        kind = "verify"
    elif resolved in _READ_RESOLVED:
        kind = "search" if resolved == "search" else "read"
    else:
        kind = "write"
    if kind not in {"read", "search", "write", "verify", "transform"}:
        raise ValueError(f"node {node.get('id')!r} has unknown kind {kind!r}")
    return NodeContract(
        id=str(node["id"]), connector=str(node.get("server") or node.get("connector") or ""),
        tool=str(node.get("tool") or ""), entity=str(node.get("entity") or ""),
        kind=kind, op=resolved if kind != "transform" else op,  # type: ignore[arg-type]
        depends_on=tuple(str(parent) for parent in node.get("depends_on", ())),
        optional=bool(node.get("optional", False)),
        fixture=str(node["fixture"]) if node.get("fixture") else None,
    )


def _structured(row: Mapping[str, Any], nodes: tuple[NodeContract, ...]) -> tuple[StructuredOutcome, ...]:
    blocked: set[str] = set()
    for assertion in row.get("assertions", ()):
        if assertion.get("type") == "failure_at":
            blocked.update(str(value) for value in assertion.get("blocked_nodes", ()))
            if not assertion.get("writes_persist"):
                blocked.add(str(assertion["node"]))
    states: dict[str, dict[str, Any]] = {}
    deleted: dict[str, str | None] = {}
    for assertion in row.get("assertions", ()):
        if assertion.get("type") == "state_equals":
            states[str(assertion["node"])] = {str(assertion.get("field") or "state"): assertion.get("state")}
        elif assertion.get("type") == "deleted":
            deleted[str(assertion["node"])] = str(assertion["fixture"]) if assertion.get("fixture") else None
    out: list[StructuredOutcome] = []
    for node in nodes:
        if node.kind != "write":
            continue
        if node.op == "delete" or node.id in deleted:
            kind: OutcomeKind = "delete"
        elif node.op in _UPDATE_OPS:
            kind = "update"
        elif node.op in _CREATE_OPS:
            kind = "create"
        else:
            # An op the vocabulary does not know is graded as a mutation
            # of an existing record, never silently dropped from the
            # outcome contract: a write node with no outcome is a write
            # nobody checks.
            kind = "update"
        fixture = deleted.get(node.id) or node.fixture
        out.append(StructuredOutcome(
            kind=kind, connector=node.connector, entity=node.entity, node=node.id,
            fixture=fixture, fields=states.get(node.id, {}), blocked=node.id in blocked,
        ))
    return tuple(out)


def case_from_row(
    row: Mapping[str, Any],
    *,
    query: str | None = None,
    persona: str = "",
    principal: str = "agent",
    dimensions: Mapping[str, str] | None = None,
    output_format: str | None = None,
    answer: AnswerOutcome | None = None,
) -> EvalCase:
    """Read the three axes out of one compiled row.

    The row is kept verbatim. ``query`` defaults to the row's own text when
    the service attached one; a row without either is refused, because a case
    with no request has nothing to grade a plan against.
    """

    text = query if query is not None else str(row.get("query") or "")
    if not text.strip():
        raise ValueError(f"row {row.get('id')!r} has no request text; a case needs a query")
    expected = row.get("expected_dag") or {}
    nodes = tuple(_node_contract(node) for node in expected.get("nodes", ()))
    edges = tuple((str(source), str(target)) for source, target in expected.get("edges", ()))
    known = {node.id for node in nodes}
    dangling = [edge for edge in edges if edge[0] not in known or edge[1] not in known]
    if dangling:
        raise ValueError(f"row {row.get('id')!r} has edges naming unknown nodes: {dangling[:3]}")
    plan = PlanContract(nodes=nodes, edges=edges, shape=row.get("shape"), grammar=row.get("grammar"))

    failures = tuple(
        FailurePoint(
            node=str(assertion["node"]), kind=str(assertion["kind"]),
            writes_persist=bool(assertion.get("writes_persist", False)),
            blocked_nodes=tuple(str(value) for value in assertion.get("blocked_nodes", ())),
            fixture=str(assertion["fixture"]) if assertion.get("fixture") else None,
        )
        for assertion in row.get("assertions", ()) if assertion.get("type") == "failure_at"
    )
    trajectory = TrajectoryContract(max_calls=int(row.get("max_calls") or 1000), failures=failures)

    structured = _structured(row, nodes)
    write_ids = {outcome.node for outcome in structured}
    adversarial = (row.get("adversarial") or {}).get("type")
    blocked_all = bool(write_ids) and all(outcome.blocked for outcome in structured)
    no_write = adversarial in _NO_WRITE_ADVERSARIAL or blocked_all
    facts = tuple(str(value) for value in row.get("expected_fact_ids", ()))
    evidence = tuple(str(value) for value in row.get("expected_evidence_ids", ()))
    pinned: list[str] = []
    for assertion in row.get("assertions", ()):
        if assertion.get("type") == "reads_contain":
            pinned.extend(str(value) for value in assertion.get("records", ()))
    for node in expected.get("nodes", ()):
        pinned.extend(str(value) for value in node.get("expected_reads", ()))
        if node.get("fixture") and str(node.get("node_kind") or node.get("op")) in {"read", "search", "get"}:
            pinned.append(str(node["fixture"]))
    records = tuple(dict.fromkeys(pinned))
    # An artifact is expected only when a write carries evidence into it: the
    # grammar binds ``fields.evidence`` on every create, the legacy row does
    # not, and a requirement the reference trajectory cannot meet is not a
    # requirement, it is a gap in the row (named by `axis_coverage`).
    carries_evidence = any(
        node.get("node_kind") == "write" and any(str(key).startswith(("fields.", "body")) for key in node.get("bindings", {}))
        for node in expected.get("nodes", ())
    )
    unstructured = (
        UnstructuredOutcome(format=output_format, required_records=records, required_fact_ids=facts,
                            required_evidence_ids=evidence)
        if carries_evidence and any(outcome.kind == "create" for outcome in structured)
        else None
    )
    outcomes = OutcomeContract(structured=structured, unstructured=unstructured, answer=answer, no_write=no_write)
    return EvalCase(
        id=str(row["id"]), query=text, persona=persona, principal=principal,
        dimensions=dict(dimensions or {}), plan=plan, trajectory=trajectory,
        outcomes=outcomes, row=dict(row),
    )


def cases_from_corpus(corpus: Any, *, definitions: Mapping[str, Any] | None = None, principal: str = "agent") -> tuple[EvalCase, ...]:
    """Compile an ``EnterpriseCorpus`` into cases, refusing any row the compiler refuses.

    A refusal is a finding, not a skipped row: a corpus that silently loses
    its unexecutable queries reports a pass rate over a set it never ran.
    """

    from ..enterprise_rows import compile_rows, runtime_records

    fixtures = {fixture.query_id: fixture for fixture in corpus.fixtures}
    records = runtime_records(corpus.connector_data.records)
    report = compile_rows(corpus.queries, fixtures.values(), records, definitions=definitions)
    if report.refusals:
        reasons = "; ".join(f"{reason} x{count}" for reason, count in list(report.reasons().items())[:3])
        raise ValueError(f"{len(report.refusals)} rows refused compilation: {reasons}")
    by_id = {query.id: query for query in corpus.queries}
    cases = []
    for row in report.rows:
        query = by_id[str(row["id"])]
        mutation = query.generation.mutation
        cases.append(case_from_row(
            row, query=query.query, persona=query.dimensions.get("persona", ""),
            principal=principal, dimensions=query.dimensions,
            output_format=mutation.output_format or None,
        ))
    return tuple(cases)


class AxisCoverage(Model):
    """What a case set actually exercises, per axis. Counts, never claims."""

    cases: int
    reads: int
    writes: int
    creates: int
    updates: int
    deletes: int
    verifies: int
    transforms: int
    designed_failures: int
    no_write_cases: int
    unstructured: int
    answers: int
    shapes: dict[str, int]
    connectors: dict[str, int]
    operations: dict[str, int]
    failure_kinds: dict[str, int]


def axis_coverage(cases: Iterable[EvalCase]) -> AxisCoverage:
    """Count, per axis, what the set can grade. A zero here is a gap, named."""

    listed = list(cases)
    shapes: Counter[str] = Counter()
    connectors: Counter[str] = Counter()
    operations: Counter[str] = Counter()
    failure_kinds: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    for case in listed:
        shapes[case.plan.shape or "legacy"] += 1
        for connector in case.plan.connectors:
            connectors[connector] += 1
        for node in case.plan.tool_nodes:
            operations[node.op] += 1
        counts["reads"] += bool(case.plan.of_kind("read", "search"))
        counts["writes"] += bool(case.plan.of_kind("write"))
        counts["verifies"] += bool(case.plan.of_kind("verify"))
        counts["transforms"] += bool(case.plan.of_kind("transform"))
        counts["creates"] += bool(case.outcomes.of_kind("create"))
        counts["updates"] += bool(case.outcomes.of_kind("update"))
        counts["deletes"] += bool(case.outcomes.of_kind("delete"))
        counts["designed_failures"] += bool(case.trajectory.failures)
        counts["no_write_cases"] += case.outcomes.no_write
        counts["unstructured"] += case.outcomes.unstructured is not None
        counts["answers"] += case.outcomes.answer is not None
        for failure in case.trajectory.failures:
            failure_kinds[failure.kind] += 1
    return AxisCoverage(
        cases=len(listed), reads=counts["reads"], writes=counts["writes"], creates=counts["creates"],
        updates=counts["updates"], deletes=counts["deletes"], verifies=counts["verifies"],
        transforms=counts["transforms"], designed_failures=counts["designed_failures"],
        no_write_cases=counts["no_write_cases"], unstructured=counts["unstructured"], answers=counts["answers"],
        shapes=dict(sorted(shapes.items())), connectors=dict(sorted(connectors.items())),
        operations=dict(sorted(operations.items())), failure_kinds=dict(sorted(failure_kinds.items())),
    )


__all__ = [
    "AnswerOutcome",
    "AxisCoverage",
    "EvalCase",
    "FailurePoint",
    "NodeContract",
    "OutcomeContract",
    "PlanContract",
    "StructuredOutcome",
    "TrajectoryContract",
    "UnstructuredOutcome",
    "axis_coverage",
    "case_from_row",
    "cases_from_corpus",
]
