"""Prove a case set solvable before an agent is graded on it, and pin what the proof rests on.

A pilot run's call errors were mostly valid vendor queries the emulator's old
parser refused, so part of what it measured was the emulator, not the agent.
Nothing said, before the run, that every case could be solved at all. This
module says it, case by case, and names the first node that makes a case
unsolvable and why.

The proof replays each case's gold DAG through the connector emulator under
the vendor query engine (``native``), through the same tool surface an agent
gets, and checks four things:

- every gold query parses in its vendor grammar: the node's ``query`` text,
  or its structured predicate compiled into the connector's language
  (``connector_query.compile_native``), run by the vendor evaluator, so a
  field the vendor does not have is refused with the vendor's own error;
- every gold read retrieves its evidence (the node's ``expected_reads``, the
  row's ``reads_contain``, else its fixture);
- every gold write produces the expected state diff, and none fails;
- the reference trajectory scores 1.0 on plan, trajectory and outcomes, and
  on each stage it is graded on (queries, plan nodes, output), with the
  row's own assertions passing.

A case that fails any of them is *unsolvable*: no agent can score full marks
on it, so grading an agent on it measures the case. ``prove_cases`` is the
SDK function; ``worldloom evalrun prove`` the command.

**Pins.** A proof holds only for what it ran against: the records, the
connector definitions, the query engine and its vendor data, the grader, and,
when Anvil serves the connectors, the contracts, the mappings and the Anvil
version. ``environment_pins`` names all of them as digests. The proof record
(``proof.json`` beside the case set) carries the pins it was proved under;
``evalrun run`` computes the live pins, and any difference makes the proof
stale: it re-proves (cheap and deterministic) and refuses to run when the
set is no longer solvable, naming the pins that moved. A case set with no
proof record still runs, with a warning, so older sets are not stranded.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ConfigDict, Field

from ..ids import content_key
from ..models import Model
from .contract import EvalCase, NodeContract

if TYPE_CHECKING:
    from ..connectors.serving import ConnectorEvaluationService
    from .anvil import AnvilServing
    from .runner import CaseResult

PROOF_SCHEMA = "worldloom.evalset-proof/v1"
#: The proof record a case set carries beside its cases.
PROOF_FILE = "proof.json"
#: The engine every proof runs under. A proof under the historical parser
#: would certify the defect the proof exists to catch.
PROOF_ENGINE = "native"

#: The checks, in the order a node is examined. A report counts first
#: failures by these names.
CHECKS: dict[str, str] = {
    "query.parse": "the gold query does not parse in its vendor grammar",
    "query.field": "the gold query names a field the vendor does not have",
    "query.evidence": "the gold query, run in its vendor language, does not return the node's evidence",
    "read.error": "a gold read or search failed",
    "read.evidence": "a gold read did not retrieve its evidence",
    "write.error": "a gold write failed",
    "write.state": "a gold write did not produce the expected state",
    "node.unexecuted": "the reference could not execute the gold node",
    "contract.gap": "on the contract surface, no exposed operation carries the gold call (connectors.surface)",
    "trajectory.safety": "the gold trajectory breaks a safety law",
    "axis.plan": "the reference plan does not score 1.0",
    "axis.trajectory": "the reference trajectory does not score 1.0",
    "axis.outcomes": "the reference outcomes do not score 1.0",
    "stage.query": "the reference queries do not score 1.0",
    "stage.plan_nodes": "the reference plan nodes do not score 1.0",
    "stage.output": "the reference output does not score 1.0",
    "assertions": "the row's own assertions fail on the reference trajectory",
    "case.error": "the reference run could not be graded",
    "anvil.unmapped": "a gold call has no modelled operation in the Anvil contract",
    "anvil.divergence": "Anvil served the gold trajectory differently from the emulator",
}

#: A node id for a failure that belongs to the whole case, not one node.
CASE_NODE = "(case)"


class ProofFailure(Model):
    """Why a case is unsolvable, at one node."""

    node: str
    check: str
    reason: str


class CaseProof(Model):
    case_id: str
    solvable: bool
    #: The first failing node in gold order, when there is one.
    failure: ProofFailure | None = None
    failures: tuple[ProofFailure, ...] = ()
    #: The reference's scores: the three axes, and the stages it was graded on.
    scores: dict[str, float] = Field(default_factory=dict)


class ProofReport(Model):
    """The proof of one case set: a verdict per case and the pins it rests on."""

    schema_version: str = Field(default=PROOF_SCHEMA, alias="schema")
    case_set: str
    serving: str = "emulator"
    query_engine: str = PROOF_ENGINE
    cases: tuple[CaseProof, ...]
    solvable: int
    unsolvable: int
    #: First failures by check name: the headline of why a set is not solvable.
    reasons: dict[str, int] = Field(default_factory=dict)
    #: What the proof ran against, as digests (``environment_pins``).
    pins: dict[str, Any] = Field(default_factory=dict)
    #: Cases removed from the set for being unsolvable, when the writer was
    #: told to drop rather than refuse, with the failure that removed each.
    dropped: tuple[CaseProof, ...] = ()
    #: Why part of the proof did not run (no Anvil CLI), when it did not.
    skipped: str | None = None

    model_config = ConfigDict(populate_by_name=True)

    @property
    def digest(self) -> str:
        """The proof record's content address: what a run pins as ``proof``."""
        return content_key("evalset-proof", json.dumps(self.model_dump(mode="json", by_alias=True), sort_keys=True,
                                                         default=str))

    def unsolvable_cases(self) -> tuple[CaseProof, ...]:
        return tuple(item for item in self.cases if not item.solvable)


# -- pins --------------------------------------------------------------------------------


def _json_digest(namespace: str, value: Any) -> str:
    return content_key(namespace, json.dumps(value, sort_keys=True, default=str))


def records_digest(records: Iterable[Any]) -> str:
    """The records a case set runs over, as one digest, whichever shape they arrive in.

    A case set on disk comes back as emulator records and an exported corpus
    as ``ConnectorRecord``s; both are digested in the emulator's shape, so a
    set proved when written and read back later pins the same corpus.
    """
    from ..enterprise_rows import runtime_records

    listed = list(records)
    shaped = runtime_records(listed) if any(hasattr(record, "model_dump") for record in listed) else listed
    lines = sorted(json.dumps(dict(record), sort_keys=True, default=str) for record in shaped)
    return content_key("evalset-records", *lines)


def _data_digest(*parts: str) -> str:
    from importlib.resources import files

    resource = files("worldloom").joinpath("_data", *parts)
    return content_key("worldloom-data", resource.read_text(encoding="utf-8"))


def environment_pins(cases: Sequence[EvalCase], records: Iterable[Any], *,
                     definitions: Mapping[str, Any], query_engine: str = PROOF_ENGINE,
                     anvil: AnvilServing | None = None, surface: Any = None) -> dict[str, Any]:
    """Everything a proof's validity depends on, as digests. Pure: no clock, no host.

    ``corpus`` is the records and the case rows; ``connectors`` each
    definition the cases use; ``query_engine`` the engine and ``query_data``
    the vendor field names and error bodies it reads; ``grader`` the grading
    code, policy and stage graders (the rater an agent's run adds is that
    run's business, recorded in its own ``grader``). Under Anvil, ``serving``
    names the contracts, their exposure profiles when the serving carries
    any, the provider mappings and the Anvil version.
    """
    from .grader import grader_identity
    from .runner import case_set_digest

    pins: dict[str, Any] = {
        "corpus": content_key("evalset-corpus", records_digest(records), case_set_digest(cases)),
        "connectors": {name: _json_digest("connector-definition", definitions[name].model_dump(mode="json"))
                       for name in sorted(definitions)},
        "query_engine": query_engine,
        "query_data": _data_digest("connectors", "_query.json"),
        "grader": grader_identity(None)["digest"],
        "serving": "emulator" if anvil is None else anvil_pins(anvil),
    }
    # The contract surface is part of what a proof rests on: the tools the
    # gold plan was carried through and the mapping that carried them. The
    # native surface adds nothing, so a proof recorded before surfaces
    # existed keeps its pins.
    from ..connectors.surface import resolve_surfaces

    surfaces = resolve_surfaces(surface, sorted(definitions))
    if surfaces is not None:
        pins["surface"] = surfaces.identity()
    return pins


def anvil_pins(anvil: AnvilServing) -> dict[str, Any]:
    """The Anvil half of the pins: contracts, exposure profiles, mappings, Anvil version."""
    from ..connectors.anvil import mapping_path

    identity = anvil.identity()
    mappings: dict[str, str] = {}
    for name in sorted(anvil.contracts):
        try:
            path = Path(str(mapping_path(name)))
            mappings[name] = content_key("anvil-mapping", path.read_text(encoding="utf-8"))
        except (OSError, KeyError, ValueError):
            mappings[name] = "unreadable"
    pins: dict[str, Any] = {"connectors": "anvil", "contracts": dict(identity.get("contracts") or {}),
                            "mappings": mappings, "anvil_version": anvil_version(anvil)}
    exposure = getattr(anvil, "exposure", None) or identity.get("exposure")
    if exposure:
        pins["exposure"] = {str(key): _json_digest("anvil-exposure", value) if not isinstance(value, str) else value
                            for key, value in sorted(dict(exposure).items())}
    return pins


def anvil_version(anvil: AnvilServing) -> str:
    """What the Anvil CLI says its version is, or ``unknown`` when it will not say."""
    import subprocess

    try:
        done = subprocess.run([*anvil.command, "--version"], capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError):
        return "unknown"
    text = (done.stdout or done.stderr).strip().splitlines()
    return text[0].strip() if done.returncode == 0 and text else "unknown"


def pin_changes(recorded: Mapping[str, Any], live: Mapping[str, Any]) -> tuple[str, ...]:
    """The pins that differ, named down to the connector or contract that moved."""

    changed: list[str] = []
    for key in sorted(set(recorded) | set(live)):
        before, after = recorded.get(key), live.get(key)
        if before == after:
            continue
        if isinstance(before, Mapping) and isinstance(after, Mapping):
            for inner in sorted(set(before) | set(after)):
                if before.get(inner) != after.get(inner):
                    changed.append(f"{key}.{inner}")
        else:
            changed.append(key)
    return tuple(changed)


# -- the gold queries ----------------------------------------------------------------------


def _row_node(case: EvalCase, node_id: str) -> Mapping[str, Any]:
    for node in (case.row.get("expected_dag") or {}).get("nodes", ()):
        if str(node.get("id")) == node_id:
            return node
    return {}


def gold_reads(case: EvalCase, node: NodeContract) -> tuple[str, ...]:
    """The records a gold read must retrieve: ``expected_reads``, ``reads_contain``, else the fixture."""

    raw = _row_node(case, node.id)
    listed = [str(value) for value in raw.get("expected_reads", ())]
    for assertion in case.row.get("assertions", ()):
        if assertion.get("type") == "reads_contain" and str(assertion.get("node")) == node.id:
            listed.extend(str(value) for value in assertion.get("records", ()))
    if not listed:
        listed.extend(str(value) for value in raw.get("fixtures", ()) or ())
        if node.fixture:
            listed.append(node.fixture)
    return tuple(dict.fromkeys(listed))


#: How each vendor language names a record by its identity, and which record
#: key holds the value it expects: Jira's issue key, Salesforce's 18-character
#: Id, Confluence's content id, ServiceNow's number, Graph's id. Drive's ``q``,
#: KQL and Slack search have no identity clause at all (a real agent fetches
#: by id instead), so an identity lookup has no vendor form there.
IDENTITY_FIELDS: dict[str, tuple[str, str]] = {
    "jql": ("key", "ident"),
    "soql": ("Id", "ident"),
    "cql": ("id", "ident"),
    "encoded_query": ("number", "ident"),
    "odata": ("id", "fid"),
}
_ID_FIELDS = frozenset({"id", "fid"})


def gold_query(case: EvalCase, node: NodeContract, definition: Any,
               records: Sequence[Mapping[str, Any]] = ()) -> tuple[str, str] | None:
    """The gold query of a search node in its vendor language, as ``(language, text)``.

    The node's own ``query`` text when it states one; otherwise its predicate
    compiled into the connector's language. A predicate that looks records up
    by Worldloom's record id (``{"id": ["in", [fid, ...]]}``, what the planner
    writes) is first restated on the vendor's identity (the Jira key, the
    Salesforce Id), because the fid is Worldloom's name for a record and no
    vendor has heard of it. ``None`` when the tool reads no vendor language
    (GraphQL, Rovo, the system of record), the language has no identity
    clause for an identity lookup, or the node carries neither.
    """
    from ..connector_emulator import _coerce_predicate
    from ..connector_query import compile_native
    from ..connectors.query import tool_language
    from ..predicates import FieldPredicate, PredicateOp

    payload = _row_node(case, node.id).get("payload") or {}
    language = tool_language(definition, node.tool)
    if language is None:
        return None
    if payload.get("query"):
        return language, str(payload["query"])
    raw = payload.get("predicate")
    if raw is None:
        return None
    entity = node.entity or None
    predicate = _coerce_predicate(raw, entity=entity)
    lookup = bool(predicate.where) and all(item.field in _ID_FIELDS and item.op in {PredicateOp.EQ, PredicateOp.IN}
                                           for item in predicate.where)
    if lookup:
        if language not in IDENTITY_FIELDS:
            return None
        field, key = IDENTITY_FIELDS[language]
        by_fid = {str(record.get("fid")): record for record in records}
        clauses = []
        for item in predicate.where:
            values = item.value if isinstance(item.value, tuple) else (item.value,)
            named = tuple(str((by_fid.get(str(value)) or {}).get(key) or value) for value in values)
            clauses.append(FieldPredicate(field=field, op=PredicateOp.IN, value=named))
        predicate = predicate.model_copy(update={"where": tuple(clauses)})
    # An alias entity (Jira's `issue` over task, bug, story) names no vendor
    # issue type, so JQL gets no `issuetype` clause for it, as a person would write none.
    concrete = entity
    if entity is not None and language != "soql":
        try:
            if tuple(definition.entity_members(entity)) != (entity,):
                concrete = None
        except KeyError:
            concrete = None
    try:
        # A tool whose language is not its connector's (SharePoint's KQL
        # search) is written in its own, as the contract carrier writes it.
        compiled = compile_native(definition, predicate.model_copy(update={"entity": concrete}), entity=concrete,
                                  language=language if language == "kql" else None)
    except (ValueError, KeyError):
        # A language the historical compiler does not write (KQL tools, Slack):
        # the predicate is what the gold states, and the emulator runs it.
        return None
    return language, compiled


def _query_failures(case: EvalCase, node: NodeContract, emulator: Any) -> list[ProofFailure]:
    """The gold query of *node*, run through the vendor evaluator by *emulator* (the connector's records)."""
    from ..connector_emulator import ConnectorError

    stated = gold_query(case, node, emulator.definition, list(emulator.records.values()))
    if stated is None:
        return []
    language, text = stated
    payload = _row_node(case, node.id).get("payload") or {}
    limit = int(payload.get("max_results") or 1000)
    wanted = gold_reads(case, node)
    try:
        found: set[str] = set()
        start = 0
        while True:
            page = emulator.call(node.tool, query=text, entity=node.entity or None, start_at=start,
                                 max_results=limit)
            found.update(emulator.trace[-1].reads)
            got = len(page.get("items", ()))
            if page.get("is_last") or not got or len(found) >= limit:
                break
            start += int(page.get("max_results") or got)
    except ConnectorError as error:
        message = str(error)
        check = "query.field" if _names_a_field(message) else "query.parse"
        return [ProofFailure(node=node.id, check=check, reason=f"{language} `{text}`: {message}")]
    missing = [fid for fid in wanted if fid not in found]
    if missing and wanted:
        return [ProofFailure(node=node.id, check="query.evidence",
                             reason=f"{language} `{text}` returns {len(found)} record(s) without {', '.join(missing[:3])}")]
    return []


def _names_a_field(message: str) -> bool:
    lowered = message.lower()
    return any(token in lowered for token in ("field", "property", "column", "no such column", "invalid_field"))


# -- the reference run, read node by node ------------------------------------------------


def _node_order(case: EvalCase) -> dict[str, int]:
    return {node.id: index for index, node in enumerate(case.plan.nodes)}


def _designed(case: EvalCase) -> tuple[set[str], set[str]]:
    failing = {failure.node for failure in case.trajectory.failures}
    blocked = {node for failure in case.trajectory.failures for node in failure.blocked_nodes}
    return failing, blocked


def _message(error: Any) -> str:
    if isinstance(error, Mapping):
        return str(error.get("message") or error.get("kind") or error)
    return str(error)


def _note_for(notes: Sequence[str], node: str) -> str | None:
    for note in notes:
        parts = note.split(":")
        if len(parts) >= 2 and parts[1] == node:
            return note
    return None


def _run_failures(case: EvalCase, result: CaseResult) -> list[ProofFailure]:
    """What the reference run shows is wrong with the case, node by node, then axis by axis."""
    from .grading import skipped_nodes

    if not result.graded or result.score is None:
        return [ProofFailure(node=CASE_NODE, check="case.error", reason=result.error or "the run was not graded")]
    score = result.score
    spans = [dict(span) for span in result.spans]
    skipped = skipped_nodes(case, spans)
    failing, blocked = _designed(case)
    out: list[ProofFailure] = []
    matches = {match.expected.node: match for match in score.outcomes.structured}
    for node in case.plan.nodes:
        if node.kind == "transform" or node.id in skipped or node.id in blocked:
            continue
        own = [span for span in spans if span.get("node") == node.id]
        errors = [span for span in own if span.get("error")]
        gap = _note_for(result.notes, node.id)
        if not own and gap is not None and "contract_gap" in gap:
            # Before the designed-failure skip: a node the contract cannot
            # carry never reached the failure the case designed for it.
            out.append(ProofFailure(node=node.id, check="contract.gap", reason=gap.split("contract_gap: ", 1)[-1]))
            continue
        if node.id in failing:
            continue  # a designed failure is expected to error; the trajectory grade judges it
        if not own:
            note = _note_for(result.notes, node.id)
            out.append(ProofFailure(node=node.id, check="node.unexecuted",
                                    reason=note or f"no call attributed to {node.connector}.{node.tool}"))
            continue
        if errors:
            check = "write.error" if node.kind == "write" else "read.error"
            first = errors[0]
            target = (first.get("args") or {}).get("id")
            called = f"{first.get('tool')}({target})" if target is not None else str(first.get("tool"))
            out.append(ProofFailure(node=node.id, check=check, reason=f"{called}: {_message(first.get('error'))}"))
            continue
        if node.kind in {"read", "search"}:
            wanted = gold_reads(case, node)
            got = {str(fid) for span in own for fid in span.get("reads", ())}
            missing = [fid for fid in wanted if fid not in got]
            if missing:
                out.append(ProofFailure(node=node.id, check="read.evidence",
                                        reason=f"{node.connector}.{node.tool} did not retrieve {', '.join(missing[:3])}"
                                        f" ({len(got)} record(s) read)"))
        elif node.kind == "write":
            match = matches.get(node.id)
            if match is not None and not match.met and not match.expected.blocked:
                detail = match.detail or f"expected {match.expected.kind} of {match.expected.fixture or match.expected.entity}"
                out.append(ProofFailure(node=node.id, check="write.state", reason=detail))
    by_span = {str(span.get("id")): str(span.get("node") or CASE_NODE) for span in spans}
    for finding in score.trajectory.safety:
        out.append(ProofFailure(node=by_span.get(finding.span_id, CASE_NODE), check="trajectory.safety",
                                reason=f"{finding.law} at {finding.tool}: {finding.detail}"))
    out.extend(_axis_failures(result, frozenset(node.id for node in case.plan.nodes)))
    return out


def _axis_failures(result: CaseResult, nodes: frozenset[str] = frozenset()) -> list[ProofFailure]:
    from .autopsy import finding_keys
    from .stages import stage_scores

    assert result.score is not None
    score = result.score
    keys = finding_keys(result)
    out: list[ProofFailure] = []
    for axis in ("plan", "trajectory", "outcomes"):
        grade = getattr(score, axis)
        if not grade.passed or grade.score < 1.0:
            named = [key for key in keys if key.startswith(f"{axis}.")]
            out.append(ProofFailure(node=CASE_NODE, check=f"axis.{axis}",
                                    reason=f"score {grade.score}" + (f": {', '.join(named[:4])}" if named else "")))
    for stage, value in sorted(stage_scores(score).items()):
        if value < 1.0:
            named = _stage_findings(score, stage)
            out.append(ProofFailure(node=_stage_node(score, stage), check=f"stage.{stage}",
                                    reason=f"score {value}" + (f": {', '.join(named[:4])}" if named else "")))
    if score.assertion_status == "fail":
        # A row assertion names its node second (`result_mismatch:read-0:<fid>`):
        # the failure is filed at that node, so the first failing node is the
        # one the trace grader blamed.
        by_node: dict[str, list[str]] = {}
        for fail in score.assertion_fails:
            parts = str(fail).split(":")
            owner = parts[1] if len(parts) > 1 and parts[1] in nodes else CASE_NODE
            by_node.setdefault(owner, []).append(str(fail))
        for owner, fails in by_node.items():
            out.append(ProofFailure(node=owner, check="assertions", reason="; ".join(fails[:3])))
        if not by_node:
            out.append(ProofFailure(node=CASE_NODE, check="assertions", reason="failed"))
    return out


def _stage_findings(score: Any, stage: str) -> list[str]:
    """What a stage grade itself says is wrong, with the sections or fields it names."""
    if stage == "query":
        queries = getattr(score.trajectory, "queries", None)
        return sorted(dict(getattr(queries, "findings", {}) or {}))
    if stage == "plan_nodes":
        return list(getattr(getattr(score.plan, "nodes", None), "findings", ()) or ())
    output = getattr(score.outcomes, "output", None)
    named = list(getattr(output, "findings", ()) or ())
    missing = tuple(getattr(output, "sections_missing", ()) or ())
    if missing:
        named.append("sections missing: " + ", ".join(missing))
    unmet = [f"{check.field}={check.expected}" for check in getattr(output, "fields", ()) or () if not check.met]
    if unmet:
        named.append("fields unmet: " + ", ".join(unmet[:3]))
    return named


def _stage_node(score: Any, stage: str) -> str:
    """The gold node a stage failure is about, when the stage names one."""
    if stage == "query":
        queries = getattr(score.trajectory, "queries", None)
        for node in getattr(queries, "nodes", ()) or ():
            if node.score < 1.0:
                return str(node.node)
    if stage == "output":
        output = getattr(score.outcomes, "output", None)
        for check in getattr(output, "fields", ()) or ():
            if not check.met:
                return str(check.node)
    return CASE_NODE


def _ordered(case: EvalCase, failures: Iterable[ProofFailure]) -> tuple[ProofFailure, ...]:
    order = _node_order(case)
    checks = list(CHECKS)
    unique = list(dict.fromkeys(failures))
    return tuple(sorted(unique, key=lambda item: (order.get(item.node, len(order)),
                                                  checks.index(item.check) if item.check in checks else len(checks))))


def _scores(result: CaseResult) -> dict[str, float]:
    if result.score is None:
        return {}
    from .stages import stage_scores

    out = {axis: getattr(result.score, axis).score for axis in ("plan", "trajectory", "outcomes")}
    out.update(stage_scores(result.score))
    return out


# -- proving ------------------------------------------------------------------------------


def prove_cases(cases: Sequence[EvalCase], records: Sequence[Any], *,
                definitions: Mapping[str, Any] | None = None, rater: Any = None,
                anvil: AnvilServing | None = None, concurrency: int = 1,
                query_engine: str = PROOF_ENGINE) -> ProofReport:
    """Prove every case solvable, or name the first node that makes it not.

    Runs the reference agent over the cases on the ``native`` engine, reads
    its run node by node and axis by axis, and runs each gold query through
    the vendor evaluator. ``rater`` grades answer contracts (default: the
    grounded rater wherever the shape allows it). With ``anvil``, the gold
    trajectory is also served through Anvil (``prove_through_anvil``) and a
    call Anvil cannot serve, or serves differently, is a failure too.
    ``query_engine`` is ``native`` unless a caller proves the engine a run
    will actually use (``gate`` does). Deterministic: the same cases and
    records give the same report, byte for byte.
    """
    from ..connector_emulator import ConnectorEmulator
    from .agents import ReferenceAgent
    from .corners import GroundedWhereAllowed
    from .runner import case_set_digest, run_cases, service_for

    listed = tuple(cases)
    if not listed:
        raise ValueError("nothing to prove: the case set is empty")
    service = service_for(listed, records, definitions=definitions or None, query_engine=query_engine,
                          limits=proof_limits(concurrency))
    # One vendor-engine emulator per connector for the gold queries: a search
    # never changes it, and indexing the records once per case was most of a
    # proof over a programme's twenty thousand records.
    emulators: dict[str, Any] = {}
    report = run_cases(service, listed, ReferenceAgent(listed),
                       rater=rater if rater is not None else GroundedWhereAllowed(), concurrency=concurrency)
    served: dict[str, list[ProofFailure]] = {}
    skipped: str | None = None
    if anvil is not None:
        served = prove_through_anvil(listed, records, report.results, anvil, definitions=definitions)
    proofs: list[CaseProof] = []
    for case, result in zip(listed, report.results, strict=True):
        failures: list[ProofFailure] = []
        for node in case.plan.nodes:
            if node.kind == "search" and node.connector in service.definitions:
                if node.connector not in emulators:
                    emulators[node.connector] = ConnectorEmulator(
                        service.definitions[node.connector], _connector_records(service, node.connector),
                        query_engine=query_engine)
                failures.extend(_query_failures(case, node, emulators[node.connector]))
        failures.extend(_run_failures(case, result))
        failures.extend(served.get(case.id, ()))
        ordered = _ordered(case, failures)
        proofs.append(CaseProof(case_id=case.id, solvable=not ordered, failure=ordered[0] if ordered else None,
                                failures=ordered, scores=_scores(result)))
    reasons = Counter(item.failure.check for item in proofs if item.failure is not None)
    pins = environment_pins(listed, records, definitions=service.definitions, anvil=anvil, query_engine=query_engine,
                            surface=service.surfaces if service.surfaces is not None else "native")
    return ProofReport(case_set=case_set_digest(listed), serving="anvil" if anvil is not None else "emulator",
                       query_engine=query_engine,
                       cases=tuple(proofs), solvable=sum(item.solvable for item in proofs),
                       unsolvable=sum(not item.solvable for item in proofs),
                       reasons=dict(sorted(reasons.items())), pins=pins, skipped=skipped)


def proof_limits(concurrency: int = 1) -> Any:
    """The serving limits a proof runs under: the policy's, without the serving process's size caps.

    Whether a case can be solved is a property of the case, not of how many
    tools or records one MCP process agrees to hold: a back-office profile
    whose cases span more than a hundred connector tools is refused by a
    default server (``tool_limit``) and is still solvable, a case at a time.
    The per-run limits (calls, request and response bytes) stay the
    policy's, because an agent's run meets them.
    """
    from dataclasses import replace

    from ..connectors.serving import ServingLimits

    policy = ServingLimits()
    return replace(policy, max_tools=max(policy.max_tools, 1_000_000), max_records=max(policy.max_records, 1_000_000_000),
                   max_runs=max(policy.max_runs, concurrency),
                   max_runs_per_principal=max(policy.max_runs_per_principal, concurrency))


def _connector_records(service: ConnectorEvaluationService, connector: str) -> list[Any]:
    from ..enterprise_rows import runtime_records

    listed: list[Any] = list(service.records)
    shaped: Sequence[Mapping[str, Any]] = (runtime_records(listed) if any(hasattr(record, "model_dump") for record in listed)
                                           else listed)
    return [record for record in shaped if str(record.get("server") or record.get("connector") or "") == connector]


# -- through Anvil -------------------------------------------------------------------------


def prove_through_anvil(cases: Sequence[EvalCase], records: Sequence[Any], results: Sequence[CaseResult],
                        anvil: AnvilServing, *, definitions: Mapping[str, Any] | None = None) -> dict[str, list[ProofFailure]]:
    """Serve each case's gold trajectory through Anvil and compare it with the emulator's.

    The reference's calls in the in-process run are the gold trajectory. Each
    is turned into the vendor request its contract operation takes
    (``anvil_request``), sent to the case's Anvil server, and the traces
    Anvil recorded are replayed and graded as any Anvil run is. A call no
    mapped operation serves is ``anvil.unmapped``; a served run whose spans or
    grade differ from the emulator's is ``anvil.divergence``.
    """
    from ..connectors.serving import ServingError
    from .agents import AgentResponse, CallableAgent
    from .anvil import AnvilError
    from .runner import run_case, service_for

    out: dict[str, list[ProofFailure]] = {}
    for case, local in zip(cases, results, strict=True):
        calls = [(str(span["tool"]), dict(span.get("args") or {}), str(span.get("node") or CASE_NODE))
                 for span in local.spans]
        planned: list[tuple[str, dict[str, Any]]] = []
        failures: list[ProofFailure] = []
        for tool, args, node in calls:
            connector = tool.split(".", 1)[0]
            mapping = anvil.mappings.get(connector)
            if mapping is None:
                failures.append(ProofFailure(node=node, check="anvil.unmapped",
                                             reason=f"{tool}: no contract serves {connector}"))
                continue
            try:
                planned.append((connector, anvil_request(mapping, tool.split(".", 1)[1], args, definitions, connector)))
            except ValueError as error:
                failures.append(ProofFailure(node=node, check="anvil.unmapped", reason=f"{tool}: {error}"))
        if failures:
            out[case.id] = failures
            continue

        def over_http(task: Any, tools: Any, planned: list[tuple[str, dict[str, Any]]] = planned,
                      answer: str = local.answer) -> AgentResponse:
            for connector, request in planned:
                _send(tools.base_urls[connector], tools.token, request)
            return AgentResponse(answer=answer, notes=())

        service = service_for((case,), records, definitions=definitions or None, query_engine=PROOF_ENGINE,
                              limits=proof_limits())
        try:
            served = run_case(service, case, CallableAgent(over_http, name="reference-anvil"), anvil=anvil)
        except (AnvilError, ServingError) as error:
            out[case.id] = [ProofFailure(node=CASE_NODE, check="anvil.divergence", reason=str(error))]
            continue
        if not served.graded or served.score is None:
            out[case.id] = [ProofFailure(node=CASE_NODE, check="anvil.divergence", reason=served.error or "ungraded")]
            continue
        if [(span["tool"], span.get("error")) for span in served.spans] != \
                [(span["tool"], span.get("error")) for span in local.spans]:
            out[case.id] = [ProofFailure(node=CASE_NODE, check="anvil.divergence",
                                         reason=f"served {len(served.spans)} call(s), the emulator {len(local.spans)}")]
        elif local.score is not None and served.score.score != local.score.score:
            out[case.id] = [ProofFailure(node=CASE_NODE, check="anvil.divergence",
                                         reason=f"served score {served.score.score}, emulator {local.score.score}")]
    return out


def anvil_request(mapping: Any, tool: str, args: Mapping[str, Any], definitions: Mapping[str, Any] | None,
                  connector: str) -> dict[str, Any]:
    """The vendor request a mapped contract operation takes for one connector tool call.

    The inverse of ``connectors.anvil.plan_call``, shared with the in-process
    contract surface (``connectors.anvil.placements``): the first routed
    operation that carries the call, each argument placed where the
    operation reads it and the whole request checked by running the same
    mapping forward over it. A structured predicate is compiled into the
    connector's vendor query first, because a vendor API takes no predicate.
    Raises ``ValueError`` when no modelled operation fits.
    """
    from ..connector_definition import load_connector_definition
    from ..connectors.anvil import expressible, placements, plan_call

    definition = (definitions or {}).get(connector) or load_connector_definition(connector)
    arguments = expressible(definition, tool, args)
    found, reasons = placements(mapping, tool, arguments, definition=definition)
    wanted = {key: value for key, value in arguments.items() if key != "start_at" or value}
    for placed in found:
        if placed.entry.route is None:
            continue
        request = placed.request()
        try:
            planned = plan_call(mapping, placed.entry, request, definition)
        except Exception as error:  # an OperationRefused or a transform's refusal: this one does not carry it
            reasons.append(f"{placed.entry.operation_id}: {error}")
            continue
        if planned.tool != tool or any(json.dumps(planned.args.get(key), sort_keys=True, default=str)
                                       != json.dumps(value, sort_keys=True, default=str)
                                       for key, value in wanted.items() if key in planned.args):
            reasons.append(f"{placed.entry.operation_id} carries another call")
            continue
        method, _, path = placed.entry.route.partition(" ")
        for name, value in (placed.params.get("path") or {}).items():
            path = path.replace("{" + name + "}", str(value))
        return {"method": method, "path": path, "query": dict(placed.params.get("query") or {}), "body": placed.body}
    raise ValueError("no modelled contract operation takes this call"
                     + (f" ({'; '.join(reasons[:2])})" if reasons else ""))


def _send(base_url: str, token: str, request: Mapping[str, Any]) -> None:
    import urllib.error
    import urllib.parse
    import urllib.request

    path = str(request["path"])
    if request.get("query"):
        path += "?" + urllib.parse.urlencode({key: str(value) for key, value in sorted(request["query"].items())})
    data = json.dumps(request["body"]).encode("utf-8") if request.get("body") is not None else None
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    message = urllib.request.Request(base_url.rstrip("/") + path, data=data, method=str(request["method"]), headers=headers)
    try:
        with urllib.request.urlopen(message, timeout=60) as response:
            response.read()
    except urllib.error.HTTPError as error:
        error.read()  # a vendor error is part of the trajectory; the replay grades it


# -- case sets on disk -----------------------------------------------------------------------


def write_proof(directory: str | Path, report: ProofReport) -> Path:
    from ..corpus import write_json

    path = Path(directory) / PROOF_FILE
    write_json(path, report.model_dump(mode="json", by_alias=True))
    return path


def read_proof(directory: str | Path) -> ProofReport | None:
    """The proof record beside a case set, or ``None`` when it carries none."""
    path = Path(directory) / PROOF_FILE
    if not path.is_file():
        return None
    return ProofReport.model_validate(json.loads(path.read_text(encoding="utf-8")))


class Unsolvable(ValueError):
    """A case set holds cases no agent can solve; refused, with the report that says which."""

    def __init__(self, report: ProofReport, message: str) -> None:
        super().__init__(message)
        self.report = report


def refusal_text(report: ProofReport, *, limit: int = 5) -> str:
    """The refusal a writer or a run prints: the count, the reasons, and the first cases with their node."""
    reasons = ", ".join(f"{check} x{count}" for check, count in report.reasons.items())
    lines = [f"{report.unsolvable} of {len(report.cases)} case(s) are unsolvable ({reasons})"]
    for item in report.unsolvable_cases()[:limit]:
        assert item.failure is not None
        lines.append(f"  {item.case_id}: node {item.failure.node}, {item.failure.check}: {item.failure.reason}")
    return "\n".join(lines)


def prove_for_writing(cases: Sequence[EvalCase], records: Sequence[Any], *, drop: bool = False,
                      definitions: Mapping[str, Any] | None = None, rater: Any = None) -> tuple[ProofReport, frozenset[str]]:
    """The proof a case writer records, and the ids it may write; ``Unsolvable`` when it may write none.

    The default refuses a set with any unsolvable case: a writer that quietly
    shipped them would hand every agent a zero it did not earn. With *drop*,
    the unsolvable cases are left out and listed in the record's ``dropped``
    with the node and reason that removed each, and the remaining cases are
    proved again so the record's pins name exactly the set written.
    """
    report = prove_cases(cases, records, definitions=definitions, rater=rater)
    if not report.unsolvable:
        return report, frozenset(case.id for case in cases)
    if not drop:
        raise Unsolvable(report, refusal_text(report))
    solvable = {item.case_id for item in report.cases if item.solvable}
    kept = [case for case in cases if case.id in solvable]
    if not kept:
        raise Unsolvable(report, "every case is unsolvable, so there is nothing to write; " + refusal_text(report))
    again = prove_cases(kept, records, definitions=definitions, rater=rater)
    if again.unsolvable:
        raise Unsolvable(again, "cases proved solvable in the full set are not solvable alone; " + refusal_text(again))
    return again.model_copy(update={"dropped": report.unsolvable_cases()}), frozenset(case.id for case in kept)


def render_proof(report: ProofReport) -> str:
    """The text verdict: one line per case, first failing node and why."""
    surface = ", contract surface" if isinstance(report.pins.get("surface"), dict) else ""
    lines = [f"{report.solvable} of {len(report.cases)} case(s) solvable under the {report.query_engine} engine"
             f" ({report.serving}{surface}); proof {report.digest[:16]}"]
    if report.skipped:
        lines.append(f"skipped: {report.skipped}")
    for check, count in report.reasons.items():
        lines.append(f"  {count} x {check}: {CHECKS.get(check, check)}")
    for call, count in contract_gaps(report).items():
        lines.append(f"  gap: {count} x {call}")
    for item in report.cases:
        if item.solvable:
            lines.append(f"ok   {item.case_id}")
        else:
            assert item.failure is not None
            lines.append(f"FAIL {item.case_id} node {item.failure.node} [{item.failure.check}] {item.failure.reason}")
    for item in report.dropped:
        assert item.failure is not None
        lines.append(f"drop {item.case_id} node {item.failure.node} [{item.failure.check}] {item.failure.reason}")
    return "\n".join(lines)


_GAP_CALL = re.compile(r"carries (\S+?): ")


def contract_gaps(report: ProofReport) -> dict[str, int]:
    """Per gold call the contract surface cannot carry (``connector.tool``), how many cases' first failure it is."""
    counts: Counter[str] = Counter()
    for item in report.cases:
        failure = item.failure
        if failure is not None and failure.check == "contract.gap":
            found = _GAP_CALL.search(failure.reason)
            counts[found.group(1) if found else failure.reason[:60]] += 1
    return dict(sorted(counts.items(), key=lambda pair: (-pair[1], pair[0])))


class Gate(Model):
    """What a run found when it checked its case set's proof: the pins it runs under, and what it said."""

    #: The live pins plus ``proof``: the recorded proof's digest when the pins
    #: match it, ``reproved:<its digest>`` when they moved and the cases the
    #: run takes proved again, ``unrecorded`` when the set carries no record.
    #: What ``run.json`` records and a comparison checks.
    pins: dict[str, Any]
    #: The pins that moved since the proof was recorded (empty when none did,
    #: or when there was no record to compare with).
    changed: tuple[str, ...] = ()
    #: ``recorded`` (pins equal, the record stands), ``reproved`` (stale,
    #: proved again) or ``unrecorded`` (no proof record; proved now).
    status: str
    warnings: tuple[str, ...] = ()
    #: Why the run must not go ahead, when it must not.
    refusal: str | None = None
    report: ProofReport | None = None


def definitions_for(cases: Sequence[EvalCase], definitions: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """The connector definitions a set of cases runs against, chosen as the service chooses them.

    Built-in definitions, then any a row embeds, then *definitions*; only the
    connectors the cases' tool nodes use.
    """
    from ..connector_definition import (
        ConnectorDefinition,
        builtin_connector_definitions,
    )

    available: dict[str, Any] = dict(builtin_connector_definitions())
    for case in cases:
        for name, value in sorted((case.row.get("connector_definitions") or {}).items()):
            available[name] = ConnectorDefinition.model_validate(value)
    available.update(definitions or {})
    required = sorted({node.connector for case in cases for node in case.plan.tool_nodes})
    return {name: available[name] for name in required if name in available}


def live_engine(anvil: AnvilServing | None = None) -> str:
    """The query engine a run's service will use: ``native`` under Anvil, else the policy's."""
    if anvil is not None:
        return PROOF_ENGINE
    from ..connector_emulator import _query_engine

    return _query_engine(None)


def gate(directory: str | Path | None, cases: Sequence[EvalCase], records: Sequence[Any], *,
         definitions: Mapping[str, Any], anvil: AnvilServing | None = None,
         query_engine: str | None = None, selected: Sequence[EvalCase] | None = None) -> Gate:
    """Check a case set's proof against the live environment before a run.

    Pins equal: the recorded proof stands. Pins moved: prove again, under
    the engine the run will use, and refuse when a case the record proved
    solvable no longer is, naming the pins that moved. No record (a set
    written before proofs existed, or an in-memory corpus): prove now and
    warn, never refuse, so older sets still run. The pins are always the
    whole set's (*cases*); what is proved is *selected* when a run takes only
    part of the set (``--limit``, ``--shard``), because a run need not pay
    for proving cases it will not run.
    """
    engine = query_engine or live_engine(anvil)
    targets = tuple(selected) if selected is not None else tuple(cases)
    live = environment_pins(cases, records, definitions=definitions, query_engine=engine, anvil=anvil)
    recorded = read_proof(directory) if directory is not None else None
    if recorded is None:
        report = prove_cases(targets, records, definitions=definitions, anvil=anvil, query_engine=engine)
        note = (f"the case set carries no proof record ({PROOF_FILE}); proved now: {report.solvable} of"
                f" {len(report.cases)} case(s) solvable")
        warnings = [note]
        if report.unsolvable:
            warnings.append(refusal_text(report))
        # No record, so no proof digest to pin: the cases proved here are the
        # run's own selection (a shard proves its share), and a digest of that
        # would make two shards of one run look like two environments.
        return Gate(pins={**live, "proof": "unrecorded"}, status="unrecorded", warnings=tuple(warnings), report=report)
    changed = pin_changes(recorded.pins, live)
    if not changed:
        standing = (refusal_text(recorded),) if recorded.unsolvable else ()
        return Gate(pins={**live, "proof": recorded.digest}, status="recorded", warnings=standing, report=recorded)
    report = prove_cases(targets, records, definitions=definitions, anvil=anvil, query_engine=engine)
    was = {item.case_id for item in recorded.cases if item.solvable}
    now_failing = [item for item in report.unsolvable_cases() if item.case_id in was]
    pins = {**live, "proof": f"reproved:{recorded.digest}"}
    if now_failing:
        first = now_failing[0]
        assert first.failure is not None
        refusal = (f"the case set's proof is stale ({', '.join(changed)} changed) and {len(now_failing)} case(s) it"
                   f" proved solvable no longer are; first: {first.case_id} at node {first.failure.node},"
                   f" {first.failure.check}: {first.failure.reason}")
        return Gate(pins=pins, changed=changed, status="reproved", refusal=refusal, report=report)
    note = f"the case set's proof was stale ({', '.join(changed)} changed); proved again: {report.solvable} of {len(report.cases)} solvable"
    return Gate(pins=pins, changed=changed, status="reproved", warnings=(note,), report=report)


__all__ = [
    "CHECKS",
    "Gate",
    "definitions_for",
    "gate",
    "live_engine",
    "PROOF_ENGINE",
    "PROOF_FILE",
    "PROOF_SCHEMA",
    "CaseProof",
    "ProofFailure",
    "ProofReport",
    "Unsolvable",
    "anvil_pins",
    "anvil_request",
    "proof_limits",
    "prove_for_writing",
    "environment_pins",
    "gold_query",
    "gold_reads",
    "pin_changes",
    "prove_cases",
    "prove_through_anvil",
    "read_proof",
    "records_digest",
    "refusal_text",
    "render_proof",
    "write_proof",
]
