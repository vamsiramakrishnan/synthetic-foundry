"""Who owns a failure: the agent, the interface it was served, the world it worked in, or the grader.

The autopsy names *what* failed in closed keys. An improver also needs to
know *whose* failure it is, because the loop can only change one thing at a
time. A live pilot's "agent failures" were mostly not the agent's: search
tools served as a generic ``query: string`` with no grammar, and an emulator
parser that refused valid SOQL, produced ``error:validation_error`` on every
case, and everything downstream of those refusals (a read that never ran, a
question asked because nothing was found) was charged to the agent. A
proposer that can only rewrite the agent's policy cannot fix a tool
description.

Every failing finding is given exactly one owner:

- ``agent``: planning and behaviour; what an agent pack can change.
- ``interface``: the tool surface misled the agent or could not express what
  it needed: a validation error whose argument shape a description, schema
  or query template would have prevented, a needed operation the surface does
  not expose, pagination the surface does not declare, a call the surface
  refused by name or argument. What an Anvil manifest overlay can change.
- ``world``: the case or the corpus: evidence that cannot be reached, a
  request that is ambiguous, data that contradicts itself. What a new case
  set or a corrected corpus can change.
- ``grader``: the measurement itself: a case that failed with nothing to
  explain it, a rater that could not rate, two identical trajectories scored
  differently.

The rules are deterministic, ordered, and each attribution carries the rule
that fired and the evidence it read. The first rule that applies wins.

Case-level rules, before any key is read:

1. ``world.proof``: the case's solvability proof (``proofs``, by case id: the
   ``CaseProof`` entries of the ``proof.json`` that ``evalrun prove --record``
   and the case writers put beside a case set, read by ``read_proofs``) says
   the case cannot be solved: every finding of the case is the world's, and
   the evidence names the proof's first failing node and why. A proof that
   names unreachable plan nodes makes only the missing-node findings on those
   nodes the world's.
2. ``grader.disagreement``: a peer run (another repeat, another agent) left
   the same case with the identical trajectory (the same calls, arguments,
   errors and answer) and a different verdict: every finding of the case is
   the grader's.
3. ``grader.replay``: the Anvil replay answered a call differently than the
   provider answered the agent (an ``anvil_divergence`` note): what was
   graded is not what was served, so every finding is the grader's.
4. ``world.reference``: a reference run (the agent that walks the gold plan)
   fails the same case with the same key: the key is the world's.

Key rules, one key at a time:

5. ``interface.error_code``: ``error:<code>`` for ``validation_error``,
   ``schema_mismatch`` or ``unsupported_operation``: the surface accepted a
   call shape the vendor refuses, or does not serve the operation asked for.
6. ``interface.refused_call``: ``trajectory.refused_call``: the surface
   refused a call by tool name or argument before any connector saw it.
7. ``interface.malformed_query``: ``query.malformed``, unless the served
   surface documents the tool's query grammar (then ``agent.ignored_grammar``).
8. ``interface.query_error``: ``query.error`` whose undesigned errors are
   validation errors; otherwise the agent's.
9. ``interface.pagination``: ``query.missed_evidence`` on a node that pulled
   fewer pages than its evidence needs, when the served surface does not
   declare the tool's pagination.
10. ``interface.not_exposed``: ``plan.missing:<kind>`` whose node's tool the
    served surface does not expose.
11. ``interface.serving``: ``run.errored`` whose error comes from serving
    (``anvil:`` or ``begin:``), not from the agent.
12. ``grader.unexplained``: ``unclassified``, ``assertion.fail`` (the row's
    verdict fails with no axis finding behind it) and
    ``outcomes.answer_unrated``.
13. ``interface.consequence``: in a case with an interface-owned call-level
    finding (rules 5 to 8) in which no call at any of its plan's read nodes
    succeeded (an errored search returned no evidence; without node
    attribution on the spans, none of the read nodes was observed), the
    findings that follow from never getting evidence (a missing plan node, a
    designed failure never reached or leaked, a question asked for want of
    evidence, an unmet outcome, an empty or short search) are the
    interface's, with the root finding named in the evidence.
14. ``agent.default``: everything else.

Rules 7, 9 and 10 read the served surface (``SurfaceFacts`` per tool, which
``evalrun.interface`` derives from a compiled Anvil bundle); without one they
fall back to the conservative reading named in each rule.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from ..models import Model
from .contract import EvalCase
from .runner import CaseResult, RunReport

OWNERS: tuple[str, ...] = ("agent", "interface", "world", "grader")
OWNERSHIP_SCHEMA = "worldloom.eval-ownership/v1"

#: Error codes the tool surface owns: the vendor refused an argument shape the
#: surface let through, or the surface does not serve what was asked for.
INTERFACE_ERROR_CODES: frozenset[str] = frozenset({"validation_error", "schema_mismatch", "unsupported_operation"})
#: Findings that follow from never getting evidence, and so from whatever
#: stopped the agent getting it (rule 13).
CONSEQUENCE_KEYS: tuple[str, ...] = (
    "plan.missing:", "plan.node_missing", "trajectory.failure_not_reached", "trajectory.failure_leaked",
    "trajectory.question:asked_without_need", "outcomes.unmet:", "query.zero_result", "query.missed_evidence",
)
_GRADER_KEYS = frozenset({"unclassified", "assertion.fail", "outcomes.answer_unrated"})
_VALIDATION_WORDS = ("validation", "invalid", "malformed", "unsupported", "400", "schema")
_LINE_LIMIT = 200
_READ_TOOL_PREFIXES = ("search", "get", "list", "query", "read", "fetch", "find")


@dataclass(frozen=True)
class SurfaceFacts:
    """What the served surface says about one tool (``connector.tool``), as the agent saw it."""

    #: The tool is served (an approved operation maps to it).
    exposed: bool = True
    #: Its description, intent examples or a query template show the grammar a query argument takes.
    grammar: bool = False
    #: It declares how it pages.
    paginated: bool = False


class Attribution(Model):
    """One failing finding of one case, and whose it is."""

    case_id: str
    key: str
    owner: str
    #: The rule that fired (``interface.error_code``, ``world.proof`` ...).
    rule: str
    evidence: tuple[str, ...] = ()
    #: For ``interface.consequence``: the interface finding it follows from.
    consequence_of: str | None = None


class OwnerShare(Model):
    owner: str
    #: Failing findings owned, and their share of every failing finding.
    findings: int
    share: float
    #: Failing cases with at least one finding of this owner.
    cases: int
    #: Each failing case split evenly over its findings: sums to the failing cases across owners.
    weight: float
    weight_share: float


class Ownership(Model):
    schema_version: str = "worldloom.eval-ownership/v1"
    agent: str
    case_set: str
    failing: int
    findings: int
    owners: tuple[OwnerShare, ...]
    #: Key to owner to count, for every failing finding.
    by_key: dict[str, dict[str, int]]
    #: Rule to count.
    rules: dict[str, int]
    attributions: tuple[Attribution, ...]


def _clip(text: str) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= _LINE_LIMIT else flat[: _LINE_LIMIT - 3].rstrip() + "..."


def _proof_of(case_id: str, case: EvalCase | None, proofs: Mapping[str, Any] | None) -> Mapping[str, Any] | None:
    """The solvability proof of a case from *proofs* (``read_proofs``, or a ``ProofReport``'s cases); ``None`` without one."""
    found = (proofs or {}).get(case_id)
    if found is not None and hasattr(found, "model_dump"):
        found = found.model_dump(mode="json")
    return found if isinstance(found, Mapping) else None


def _unsolvable(proof: Mapping[str, Any]) -> bool:
    if proof.get("solvable") is False:
        return True
    status = str(proof.get("status") or proof.get("verdict") or "").lower()
    return status in {"unsolvable", "refuted", "unreachable", "ambiguous", "contradictory", "failed"}


def _proof_reason(proof: Mapping[str, Any]) -> str:
    # `evalrun prove` names the first failing node, the check and why.
    failure = proof.get("failure")
    if isinstance(failure, Mapping) and failure.get("reason"):
        return f"node {failure.get('node')}, {failure.get('check')}: {failure.get('reason')}"
    for name in ("reason", "reasons", "detail", "findings"):
        value = proof.get(name)
        if isinstance(value, str) and value:
            return value
        if isinstance(value, Sequence) and not isinstance(value, str) and value:
            return "; ".join(str(item) for item in list(value)[:3])
    return str(proof.get("status") or proof.get("verdict") or "the proof says the case cannot be solved")


def _unreachable_nodes(proof: Mapping[str, Any]) -> set[str]:
    value = proof.get("unreachable") or proof.get("unreachable_nodes") or ()
    return {str(item.get("node") if isinstance(item, Mapping) else item) for item in value} if isinstance(value, Sequence) else set()


def trajectory_fingerprint(result: CaseResult) -> str:
    """The calls, arguments, errors and answer of a case, canonical: two equal fingerprints did the same thing."""
    calls = [[span.get("tool"), span.get("args", span.get("arguments")), (span.get("error") or {}).get("kind")
              if isinstance(span.get("error"), Mapping) else span.get("error")] for span in result.spans]
    refused = [[item.get("tool"), item.get("error") or item.get("reason")] for item in result.refusals]
    return json.dumps({"calls": calls, "refused": refused, "answer": result.answer, "status": result.status},
                      sort_keys=True, default=str)


def _passed(result: CaseResult) -> bool | None:
    return None if not result.graded or result.score is None else bool(result.score.passed)


def _interface_errors(result: CaseResult) -> list[tuple[int, dict[str, Any]]]:
    """Spans whose error the interface owns, by ordinal."""
    from .safety import error_code_for

    out = []
    for position, span in enumerate(result.spans):
        error = span.get("error")
        if isinstance(error, Mapping):
            code = error_code_for(error)
            if code is not None and str(code) in INTERFACE_ERROR_CODES:
                out.append((position, span))
    return out


def _tool_of_node(case: EvalCase | None, node: str) -> str | None:
    if case is None:
        return None
    for contract in case.plan.nodes:
        if contract.id == node:
            return contract.tool if "." in contract.tool else f"{contract.connector}.{contract.tool}"
    return None


def _read_nodes(case: EvalCase | None, result: CaseResult) -> list[str]:
    from .autopsy import _node_kind

    if result.score is None:
        return []
    plan = result.score.plan
    every = list(plan.observed_nodes) + list(plan.missing_nodes)
    if case is not None:
        every = [contract.id for contract in case.plan.tool_nodes]
        return [node for node in every if _node_kind(node, case) == "read"]
    # Without the case contract a node is a read when its id says so, or when
    # the calls attributed to it were searches or reads.
    reads = {node for node in every if _node_kind(node, None) == "read"}
    reads.update(str(span.get("node")) for span in result.spans if span.get("node")
                 and str(span.get("tool", "")).rsplit(".", 1)[-1].startswith(_READ_TOOL_PREFIXES))
    return sorted(reads)


def _key_rule(key: str, result: CaseResult, case: EvalCase | None,
              surface: Mapping[str, SurfaceFacts] | None) -> tuple[str, str, tuple[str, ...]]:
    """(owner, rule, evidence) for one key by rules 5 to 12; ``agent.default`` when none applies."""
    score = result.score
    if key.startswith("error:"):
        code = key.split(":", 1)[1]
        if code in INTERFACE_ERROR_CODES:
            lines = [f"{span.get('tool')} {json.dumps(span.get('args', {}), sort_keys=True, default=str)}: "
                     f"{(span.get('error') or {}).get('message', '')}" for _, span in _interface_errors(result)]
            return "interface", "interface.error_code", tuple(_clip(line) for line in lines[:3])
        return "agent", "agent.default", ()
    if key == "trajectory.refused_call":
        lines = [f"refused {item.get('tool')}: {item.get('error') or item.get('reason') or ''}" for item in result.refusals]
        return "interface", "interface.refused_call", tuple(_clip(line) for line in lines[:3])
    queries = getattr(getattr(score, "trajectory", None), "queries", None) if score is not None else None
    if key == "query.malformed":
        calls = [call for call in (queries.calls if queries is not None else ()) if call.malformed and not call.designed]
        tools = sorted({call.tool for call in calls})
        if surface is not None and tools and all(surface.get(tool, SurfaceFacts()).grammar for tool in tools):
            return "agent", "agent.ignored_grammar", tuple(f"{tool} documents its query grammar" for tool in tools)
        return "interface", "interface.malformed_query", tuple(_clip(f"{call.tool}: {call.error}") for call in calls[:3])
    if key == "query.error":
        calls = [call for call in (queries.calls if queries is not None else ())
                 if call.error is not None and not call.designed and not call.malformed]
        if calls and all(any(word in str(call.error).lower() for word in _VALIDATION_WORDS) for call in calls):
            return "interface", "interface.query_error", tuple(_clip(f"{call.tool}: {call.error}") for call in calls[:3])
        return "agent", "agent.default", ()
    if key == "query.missed_evidence" and queries is not None and surface is not None:
        short = [node for node in queries.nodes if key in node.findings and node.pages < node.min_pages]
        tools = sorted({call.tool for call in queries.calls if call.node in {node.node for node in short}})
        if short and tools and not any(surface.get(tool, SurfaceFacts()).paginated for tool in tools):
            return "interface", "interface.pagination", tuple(
                _clip(f"{node.node}: {node.pages} page(s) of {node.min_pages} needed; {', '.join(tools)} declares no pagination")
                for node in short[:3])
    if key.startswith("plan.missing:") and surface is not None and score is not None:
        from .autopsy import _node_kind

        kind = key.split(":", 1)[1]
        missing = [node for node in score.plan.missing_nodes if _node_kind(node, case) == kind]
        tools = [tool for node in missing if (tool := _tool_of_node(case, node)) is not None]
        hidden = [tool for tool in tools if not surface.get(tool, SurfaceFacts(exposed=False)).exposed]
        if tools and len(hidden) == len(tools):
            return "interface", "interface.not_exposed", tuple(f"{tool} is not on the served surface" for tool in hidden[:3])
    if key == "run.errored":
        error = str(result.error or "")
        if error.startswith(("anvil:", "begin:")):
            return "interface", "interface.serving", (_clip(error),)
        if error.startswith("grade:"):
            return "grader", "grader.unexplained", (_clip(error),)
        return "agent", "agent.default", (_clip(error),) if error else ()
    if key in _GRADER_KEYS:
        detail: tuple[str, ...] = ()
        if key == "assertion.fail" and score is not None:
            detail = (_clip("assertion fails: " + ", ".join(score.assertion_fails[:4])),)
        elif key == "outcomes.answer_unrated" and score is not None:
            detail = (_clip(f"rater error: {score.outcomes.answer_error}"),)
        return "grader", "grader.unexplained", detail
    return "agent", "agent.default", ()


def attribute_case(result: CaseResult, case: EvalCase | None = None, *, keys: Sequence[str] | None = None,
                   surface: Mapping[str, SurfaceFacts] | None = None, proofs: Mapping[str, Any] | None = None,
                   peers: Sequence[CaseResult] = (), reference: CaseResult | None = None,
                   reference_keys: Sequence[str] = ()) -> tuple[Attribution, ...]:
    """Every failing finding of one case with its owner, by the module's rules in order.

    *keys* are the case's finding keys (``autopsy.finding_keys`` when not
    given). *peers* are other results for the same case (repeats, other
    agents); *reference* is the reference agent's result for it with its
    keys in *reference_keys*.
    """
    from .autopsy import finding_keys

    found = tuple(keys) if keys is not None else finding_keys(result, case)
    if not found:
        return ()
    case_id = result.case_id

    def every(owner: str, rule: str, evidence: tuple[str, ...]) -> tuple[Attribution, ...]:
        return tuple(Attribution(case_id=case_id, key=key, owner=owner, rule=rule, evidence=evidence) for key in found)

    proof = _proof_of(case_id, case, proofs)
    unreachable: set[str] = set()
    if proof is not None:
        if _unsolvable(proof):
            return every("world", "world.proof", (_clip(f"proof: {_proof_reason(proof)}"),))
        unreachable = _unreachable_nodes(proof)
    verdict = _passed(result)
    mine = trajectory_fingerprint(result)
    for peer in peers:
        other = _passed(peer)
        if other is not None and verdict is not None and other != verdict and trajectory_fingerprint(peer) == mine:
            return every("grader", "grader.disagreement", (
                _clip(f"a peer run of agent {peer.agent!r} made the identical calls and answer and was "
                      f"{'passed' if other else 'failed'}"),))
    diverged = [note for note in result.notes if note.startswith("anvil_divergence")]
    if diverged:
        return every("grader", "grader.replay", tuple(_clip(note) for note in diverged[:2]))
    out: list[Attribution] = []
    reference_failed = set(reference_keys) if reference is not None else set()
    for key in found:
        if key.startswith("plan.missing:") and unreachable and result.score is not None:
            from .autopsy import _node_kind

            kind = key.split(":", 1)[1]
            missing = {node for node in result.score.plan.missing_nodes if _node_kind(node, case) == kind}
            if missing and missing <= unreachable:
                out.append(Attribution(case_id=case_id, key=key, owner="world", rule="world.proof",
                                       evidence=(_clip(f"proof: node(s) {', '.join(sorted(missing))} unreachable"),)))
                continue
        if key in reference_failed:
            out.append(Attribution(case_id=case_id, key=key, owner="world", rule="world.reference",
                                   evidence=(f"the reference agent fails this case with {key} too",)))
            continue
        owner, rule, evidence = _key_rule(key, result, case, surface)
        out.append(Attribution(case_id=case_id, key=key, owner=owner, rule=rule, evidence=evidence))
    roots = [item for item in out if item.rule in {"interface.error_code", "interface.refused_call",
                                                     "interface.malformed_query", "interface.query_error"}]
    if roots and result.score is not None:
        reads = _read_nodes(case, result)
        # A read node counts as served only when a call at it succeeded: an
        # errored search is observed by the plan grader, but it returned no
        # evidence. Without node attribution on the spans, the plan's
        # observed nodes are all there is to go on.
        if any(span.get("node") for span in result.spans):
            observed = {str(span.get("node")) for span in result.spans if span.get("node") and not span.get("error")}
        else:
            observed = set(result.score.plan.observed_nodes)
        if reads and not observed.intersection(reads):
            root = roots[0]
            first = _interface_errors(result)
            where = (f"; first at {first[0][1].get('tool')} (span {first[0][1].get('id')})" if first else "")
            for position, item in enumerate(out):
                if item.owner == "agent" and item.key.startswith(CONSEQUENCE_KEYS):
                    out[position] = item.model_copy(update={
                        "owner": "interface", "rule": "interface.consequence", "consequence_of": root.key,
                        "evidence": (_clip(f"follows from {root.key}{where}: none of the plan's read nodes "
                                           f"({', '.join(reads)}) ran"),)})
    return tuple(out)


def _results_by_case(runs: Iterable[RunReport]) -> dict[str, list[CaseResult]]:
    out: dict[str, list[CaseResult]] = defaultdict(list)
    for run in runs:
        for result in run.results:
            out[result.case_id].append(result)
    return out


def ownership(report: RunReport, *, cases: Mapping[str, EvalCase] | Iterable[EvalCase] | None = None,
              surface: Mapping[str, SurfaceFacts] | None = None, proofs: Mapping[str, Any] | None = None,
              peers: Sequence[RunReport] = (), reference: RunReport | None = None) -> Ownership:
    """Every failing finding of *report* attributed to an owner, and each owner's share."""
    from .autopsy import _cases_by_id, finding_keys

    by_id = _cases_by_id(cases)
    peer_rows = _results_by_case(peers)
    reference_rows = {row.case_id: row for row in reference.results} if reference is not None else {}
    attributions: list[Attribution] = []
    failing = 0
    for row in sorted(report.results, key=lambda item: item.case_id):
        case = by_id.get(row.case_id)
        keys = finding_keys(row, case)
        if not keys:
            continue
        failing += 1
        ref = reference_rows.get(row.case_id)
        ref_keys: tuple[str, ...] = ()
        if ref is not None and ref.query == row.query:
            ref_keys = finding_keys(ref, case)
        else:
            ref = None
        peer_list = [peer for peer in peer_rows.get(row.case_id, ()) if peer is not row and peer.query == row.query]
        attributions.extend(attribute_case(row, case, keys=keys, surface=surface, proofs=proofs, peers=peer_list,
                                           reference=ref, reference_keys=ref_keys))
    return summarise(report.agent, report.case_set, failing, attributions)


def summarise(agent: str, case_set: str, failing: int, attributions: Sequence[Attribution]) -> Ownership:
    """Owner shares over *attributions*."""
    total = len(attributions)
    per_case: dict[str, list[Attribution]] = defaultdict(list)
    for item in attributions:
        per_case[item.case_id].append(item)
    weights: dict[str, float] = defaultdict(float)
    for items in per_case.values():
        for item in items:
            weights[item.owner] += 1 / len(items)
    counts = Counter(item.owner for item in attributions)
    shares = tuple(OwnerShare(
        owner=owner, findings=counts[owner], share=round(counts[owner] / total, 4) if total else 0.0,
        cases=sum(1 for items in per_case.values() if any(item.owner == owner for item in items)),
        weight=round(weights[owner], 4), weight_share=round(weights[owner] / failing, 4) if failing else 0.0)
        for owner in OWNERS)
    by_key: dict[str, Counter[str]] = defaultdict(Counter)
    for item in attributions:
        by_key[item.key][item.owner] += 1
    rules = Counter(item.rule for item in attributions)
    return Ownership(agent=agent, case_set=case_set, failing=failing, findings=total, owners=shares,
                     by_key={key: dict(sorted(by_key[key].items())) for key in sorted(by_key)},
                     rules=dict(sorted(rules.items())), attributions=tuple(attributions))


def owner_line(owned: Ownership) -> str:
    """One line of owner shares: ``owners: agent 40% (8 findings), interface 55% ...``."""
    parts = [f"{share.owner} {round(share.share * 100)}% ({share.findings} finding(s), {share.cases} case(s))"
             for share in owned.owners if share.findings]
    return "owners: " + (", ".join(parts) if parts else "no failing finding")


def compare_ownership(baseline: Ownership, recent: Ownership) -> dict[str, dict[str, float | int]]:
    """Per owner: findings on each side and the change in share."""
    left = {share.owner: share for share in baseline.owners}
    right = {share.owner: share for share in recent.owners}
    return {owner: {"baseline": left[owner].findings, "recent": right[owner].findings,
                    "share_delta": round(right[owner].share - left[owner].share, 4)} for owner in OWNERS}


def read_proofs(directory: Any) -> dict[str, Any]:
    """The solvability proofs a case set carries, by case id; empty when it carries none.

    The record is the one ``evalrun prove --record`` and the case writers
    (``enterprise-evals build``, ``corners.write_case_set``) write:
    ``proof.json`` beside the cases (``evalrun.proof``). *directory* is the
    case set, or the ``proof.json`` itself. Each case's entry is its
    ``CaseProof`` (``solvable``, the first ``failure`` with its node, check
    and reason, every failure, the reference's scores); a case the writer
    dropped as unsolvable is included too, so a run over an older copy of the
    set still finds its proof.
    """
    from pathlib import Path

    from .proof import PROOF_FILE, read_proof

    path = Path(directory)
    report = read_proof(path.parent if path.name == PROOF_FILE else path)
    if report is None:
        return {}
    return {item.case_id: item.model_dump(mode="json") for item in (*report.cases, *report.dropped)}


__all__ = [
    "CONSEQUENCE_KEYS",
    "INTERFACE_ERROR_CODES",
    "OWNERS",
    "OWNERSHIP_SCHEMA",
    "Attribution",
    "OwnerShare",
    "Ownership",
    "SurfaceFacts",
    "attribute_case",
    "compare_ownership",
    "owner_line",
    "ownership",
    "read_proofs",
    "summarise",
    "trajectory_fingerprint",
]
