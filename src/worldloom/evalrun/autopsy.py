"""Turn a run's failures into findings an improver can act on.

A summary says *how much* an agent failed: a pass rate, per-axis means, a
count per safety law. That is the right shape for a dashboard and the wrong
one for whoever has to change the agent, who needs to know *what kind* of
failure dominates, *where* it concentrates, and *one case to look at*. The
grades already hold every fact needed; nothing here re-grades anything.

Three steps, each deterministic:

1. ``finding_keys`` reads one graded case and names each thing that failed
   as a stable, low-cardinality key (``trajectory.safety:unsafe_retry``,
   ``plan.missing:verify``, ``outcomes.unmet:update``). The vocabulary is
   closed over the grader's own: safety and question laws, Anvil's error
   codes, the node kinds and outcome kinds of the case contract. A key never
   carries a case id, a record id or free text, so two runs over different
   case sets produce comparable clusters.
2. ``autopsy`` groups the failing cases by key and reports, per cluster, its
   share of the failures, the dimensions it concentrates in with their lift
   against the whole run, and a few exemplar cases with a bounded excerpt of
   the evidence.
3. ``render_brief`` writes the autopsy as plain text short enough to hand an
   improving harness as its instructions.

Why lift and not raw counts: a cluster whose cases are 60% ``partial_write``
says nothing if the run was 60% ``partial_write``. Lift is the cluster's
share of a value divided by the run's share of it, so a lift of 2.0 means
the failure is twice as common there as the case set alone would explain.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from typing import Any

from pydantic import ConfigDict, Field

from ..models import Model
from .contract import EvalCase
from .runner import CaseResult, RunReport

AUTOPSY_SCHEMA = "worldloom.eval-autopsy/v1"

#: The dimensions a cluster is profiled over. ``failure``, ``dag_shape`` and
#: ``operation`` are also dataset ``where`` predicates, which is what lets a
#: curriculum ask for more of a cluster; ``shape`` and ``connector`` are the
#: slices ``summarize`` already reports, so the two read side by side.
PROFILE_DIMENSIONS: tuple[str, ...] = ("failure", "dag_shape", "shape", "connector", "workflow", "operation", "destination")

#: What each key family means, in one line, for the brief. A key outside
#: these families still clusters; it just renders without a gloss.
GLOSSES: dict[str, str] = {
    "trajectory.safety:duplicate_write": "a non-idempotent write was issued twice after it succeeded",
    "trajectory.safety:unsafe_retry": "a failed write was retried with no idempotency basis",
    "trajectory.safety:destructive_without_read": "a destructive call hit a record no earlier call read",
    "trajectory.question:acted_without_asking": "the request needed a clarifying question and none was asked",
    "trajectory.question:asked_too_late": "the question came after the calls it should have gated",
    "trajectory.question:ignored_the_answer": "the user declined and the blocked call ran anyway",
    "trajectory.question:asked_without_need": "a question was asked that the request did not call for",
    "trajectory.failure_leaked": "a designed failure was met and then worked around or retried unchanged",
    "trajectory.failure_not_reached": "the run stopped before the node where the designed failure waits",
    "trajectory.budget_exceeded": "the run used more calls than the case allows",
    "trajectory.retry_storm": "the same call with the same arguments repeated past the cap",
    "trajectory.refused_call": "the tool surface refused a call (unknown tool or undeclared argument)",
    "plan.missing:read": "a planned read or search never ran",
    "plan.missing:write": "a planned write never ran",
    "plan.missing:verify": "a planned readback or target check never ran",
    "plan.extra_write": "a successful write landed outside the plan's write nodes",
    "plan.order": "every node ran but a dependency ran after the node that needs it",
    "outcomes.unmet:create": "an expected record was not created",
    "outcomes.unmet:update": "an expected record was not left in the stated state",
    "outcomes.unmet:delete": "an expected record is still there",
    "outcomes.collateral": "records changed that no expectation covers",
    "outcomes.ungrounded": "the produced artifact does not carry the evidence it must rest on",
    "outcomes.answer_below_threshold": "the rated answer scored under the pass threshold",
    "outcomes.answer_unrated": "the rater could not judge the answer",
    "assertion.fail": "the row's own assertion verdict failed and no finding above explains it",
    "run.errored": "the agent raised or the run could not be graded",
    "unclassified": "the case failed and no finding explains it (a grader gap worth reporting)",
}

_QUERY_LIMIT = 160
_LINE_LIMIT = 160
_EVIDENCE_LINES = 4


def _clip(text: str, limit: int) -> str:
    flat = " ".join(str(text).split())
    return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."


def _node_kind(node: str, case: EvalCase | None) -> str:
    """``read``, ``write`` or ``verify`` for a plan node, from the case when known.

    Without the case the node id is read. The enterprise DAG grammar names its
    nodes by role (``read-0``, ``fetch-1``, ``write``, ``write-copy``,
    ``verify-write``, ``target-write``, ``delete``), so the id is a faithful
    reading of the kind for every compiled row. Search folds into read: an
    improver cares that evidence was never gathered, not how.
    """

    if case is not None:
        for contract in case.plan.nodes:
            if contract.id == node:
                return {"search": "read", "transform": "read"}.get(contract.kind, contract.kind)
    lowered = node.lower()
    if lowered.startswith(("verify", "target", "readback")):
        return "verify"
    if lowered.startswith(("write", "delete", "update", "create")):
        return "write"
    if lowered.startswith(("read", "fetch", "search", "get", "list")):
        return "read"
    return "other"


def finding_keys(result: CaseResult, case: EvalCase | None = None) -> tuple[str, ...]:
    """The findings one case failed on, as sorted unique keys; empty when it passed.

    Only axes the score observed contribute: a plan-only run yields plan keys
    alone, an Eval Studio import answer keys alone. A failed case that no
    finding explains is ``unclassified``, never silently empty, because
    that is a gap in this vocabulary or the grader, and should surface.
    """

    if not result.graded or result.score is None:
        return ("run.errored",)
    score = result.score
    if score.passed:
        return ()
    keys: set[str] = set()
    observed = set(score.observed)
    if "plan" in observed:
        plan = score.plan
        for node in plan.missing_nodes:
            keys.add(f"plan.missing:{_node_kind(node, case)}")
        if plan.extra_writes:
            keys.add("plan.extra_write")
        if plan.edge_recall < 1.0 and not plan.missing_nodes:
            keys.add("plan.order")
    if "trajectory" in observed:
        trajectory = score.trajectory
        keys.update(f"trajectory.safety:{finding.law}" for finding in trajectory.safety)
        keys.update(f"trajectory.question:{finding.law}" for finding in trajectory.question_findings)
        if trajectory.failures_honoured < trajectory.failures_expected:
            # Leaked needs the error to have been met. A run that never
            # reached the failing node did not work around anything; it
            # stopped short, which the plan keys already say, and the
            # designed failure it skipped is its own finding.
            keys.add("trajectory.failure_leaked" if trajectory.errors else "trajectory.failure_not_reached")
        if trajectory.budget_exceeded:
            keys.add("trajectory.budget_exceeded")
        if trajectory.retry_storm:
            keys.add("trajectory.retry_storm")
        if trajectory.refused_calls:
            keys.add("trajectory.refused_call")
        # An error the case designed and the agent honoured is the case
        # working, not a finding. Codes are reported only when the run hit
        # more errors than the designed failures it honoured account for.
        if trajectory.errors > trajectory.failures_honoured:
            keys.update(f"error:{code}" for code in trajectory.error_codes)
    if "outcomes" in observed:
        outcomes = score.outcomes
        keys.update(f"outcomes.unmet:{match.expected.kind}" for match in outcomes.structured if not match.met)
        if outcomes.collateral:
            keys.add("outcomes.collateral")
        if outcomes.grounding is not None and outcomes.grounding < 1.0:
            keys.add("outcomes.ungrounded")
        if outcomes.answer_error is not None:
            keys.add("outcomes.answer_unrated")
        elif outcomes.answer_score is not None:
            from .grading import _answer_pass_score

            if outcomes.answer_score < _answer_pass_score():
                keys.add("outcomes.answer_below_threshold")
    # The row's own verdict fails alongside nearly every finding above, so as
    # a key beside them it would top every autopsy and explain nothing. It is
    # kept for the case it alone condemns.
    if not keys and score.assertion_status == "fail":
        keys.add("assertion.fail")
    return tuple(sorted(keys)) or ("unclassified",)


def axis_of(key: str) -> str:
    """The family a key belongs to: ``plan``, ``trajectory``, ``outcomes``, ``error``, ``assertion``, ``run``."""

    return key.split(":", 1)[0].split(".", 1)[0]


def profile(result: CaseResult) -> dict[str, tuple[str, ...]]:
    """The values one case takes on each profile dimension.

    ``connector`` is read from what the case asked for (its destination and
    source entities) rather than from the spans, so a case the agent never
    touched still has connectors; a row without those dimensions falls back
    to the tools its spans called, then to ``none``, as ``summarize`` does.
    """

    dims = result.dimensions
    out: dict[str, tuple[str, ...]] = {}
    for name in PROFILE_DIMENSIONS:
        if name == "shape":
            out[name] = (result.shape or "legacy",)
        elif name == "connector":
            named = {value.split(":", 1)[0] for value in dims.get("source_entities", "").split("+") if value}
            if dims.get("destination"):
                named.add(dims["destination"])
            if not named:
                named = {str(span.get("tool", "")).split(".")[0] for span in result.spans} - {""}
            out[name] = tuple(sorted(named)) or ("none",)
        elif name in dims:
            out[name] = (dims[name],)
        elif name == "failure" and dims:
            # A compiled row without a failure has none designed. A hand
            # row with no dimensions at all says nothing either way, and a
            # guessed `none` would let a curriculum filter on it.
            out[name] = ("none",)
    return out


class DimensionLift(Model):
    """One dimension value a cluster concentrates in, measured against the run."""

    dimension: str
    value: str
    #: Cluster cases carrying the value, and their share of the cluster.
    cases: int
    share: float
    #: The value's share of every case in the run, passing or not.
    base_share: float
    lift: float


class Exemplar(Model):
    case_id: str
    query: str
    #: A few lines, each clipped, naming what the grade saw: the finding,
    #: the node, the detail. Bounded so a brief of twelve clusters stays short.
    evidence: tuple[str, ...]


class Cluster(Model):
    key: str
    axis: str
    gloss: str = ""
    cases: int
    #: Share of failing cases that carry this key. Shares across clusters sum
    #: past 1.0 because one case can fail on several findings.
    share_of_failures: float
    case_ids: tuple[str, ...]
    #: Counts per profile dimension value among the cluster's cases.
    dimensions: dict[str, dict[str, int]]
    #: Values with lift above 1.0, strongest first.
    concentrations: tuple[DimensionLift, ...]
    exemplars: tuple[Exemplar, ...]


class Autopsy(Model):
    schema_version: str = Field(default=AUTOPSY_SCHEMA, alias="schema")
    agent: str
    case_set: str
    cases: int
    graded: int
    errors: int
    passed: int
    failing: int
    #: The whole run's counts per profile dimension value: the denominator of every lift.
    base: dict[str, dict[str, int]]
    clusters: tuple[Cluster, ...]
    #: Clusters beyond ``top``, by key and count, so nothing is dropped unseen.
    omitted: dict[str, int] = Field(default_factory=dict)

    model_config = ConfigDict(populate_by_name=True)


def _cases_by_id(cases: Mapping[str, EvalCase] | Iterable[EvalCase] | None) -> dict[str, EvalCase]:
    if cases is None:
        return {}
    if isinstance(cases, Mapping):
        return dict(cases)
    return {case.id: case for case in cases}


def _evidence(key: str, result: CaseResult, case: EvalCase | None) -> tuple[str, ...]:
    """The lines of a case's grade that bear on one key, clipped and bounded."""

    lines: list[str] = []
    score = result.score
    if key == "run.errored" or score is None:
        lines.append(f"error: {result.error or result.status}")
    elif key.startswith("trajectory.safety:"):
        law = key.split(":", 1)[1]
        lines.extend(f"{finding.law} at {finding.tool} (span {finding.span_id}): {finding.detail}"
                     for finding in score.trajectory.safety if finding.law == law)
    elif key.startswith("trajectory.question:"):
        law = key.split(":", 1)[1]
        lines.extend(f"{finding.law} on {finding.question_id}: {finding.detail}"
                     for finding in score.trajectory.question_findings if finding.law == law)
    elif key in {"trajectory.failure_leaked", "trajectory.failure_not_reached"}:
        lines.append(f"designed failures honoured {score.trajectory.failures_honoured} of {score.trajectory.failures_expected}")
        failed = [span for span in result.spans if span.get("error")]
        lines.extend(f"error at {span.get('node')} ({span.get('tool')}): {(span.get('error') or {}).get('kind')}"
                     for span in failed[:2])
    elif key in {"trajectory.budget_exceeded", "trajectory.retry_storm", "trajectory.refused_call"}:
        trajectory = score.trajectory
        lines.append(f"{trajectory.calls} call(s), {trajectory.refused_calls} refused, {trajectory.repeated_calls} repeated")
        lines.extend(f"refused {item.get('tool')}: {item.get('reason') or item.get('error') or ''}" for item in result.refusals[:2])
    elif key.startswith("error:"):
        code = key.split(":", 1)[1]
        lines.append(f"{score.trajectory.error_codes.get(code, 0)} {code} error(s) over {score.trajectory.calls} call(s)")
    elif key.startswith("plan.missing:"):
        kind = key.split(":", 1)[1]
        missing = [node for node in score.plan.missing_nodes if _node_kind(node, case) == kind]
        lines.append(f"missing {kind} node(s): {', '.join(missing)}; observed {', '.join(score.plan.observed_nodes) or 'none'}")
    elif key == "plan.extra_write":
        lines.append(f"{score.plan.extra_writes} write(s) outside the plan's write nodes")
    elif key == "plan.order":
        lines.append(f"edge recall {score.plan.edge_recall}; observed order {', '.join(score.plan.observed_nodes)}")
    elif key.startswith("outcomes.unmet:"):
        kind = key.split(":", 1)[1]
        lines.extend(f"{match.expected.kind} {match.expected.connector}/{match.expected.entity} at {match.expected.node}: {match.detail}"
                     for match in score.outcomes.structured if not match.met and match.expected.kind == kind)
    elif key == "outcomes.collateral":
        lines.append(f"{len(score.outcomes.collateral)} unexpected change(s): {', '.join(score.outcomes.collateral[:3])}")
    elif key == "outcomes.ungrounded":
        lines.append(f"grounding {score.outcomes.grounding} over {score.outcomes.artifacts_produced} artifact(s)")
    elif key in {"outcomes.answer_below_threshold", "outcomes.answer_unrated"}:
        lines.append(f"answer score {score.outcomes.answer_score}; rater error {score.outcomes.answer_error}")
        if result.answer:
            lines.append(f"answer: {result.answer}")
    elif key == "assertion.fail":
        lines.append("assertion fails: " + ", ".join(score.assertion_fails[:4]))
    return tuple(_clip(line, _LINE_LIMIT) for line in lines[:_EVIDENCE_LINES])


def _share(part: int, whole: int) -> float:
    return round(part / whole, 4) if whole else 0.0


def autopsy(
    report: RunReport,
    *,
    cases: Mapping[str, EvalCase] | Iterable[EvalCase] | None = None,
    top: int = 12,
    exemplars: int = 2,
    concentrations: int = 3,
) -> Autopsy:
    """Cluster a run's failing cases by finding key.

    Clusters are ordered by case count, then key; exemplars are the first
    failing cases of the cluster in case-id order; concentrations are the
    values with lift above 1.0, strongest first, then by count, dimension and
    value. Every ordering is total, so the same run always yields the same
    autopsy. ``cases`` is optional: with it, a missing node's kind comes from
    the case contract rather than its id.
    """

    if top < 1 or exemplars < 1 or concentrations < 0:
        raise ValueError("top and exemplars must be positive and concentrations non-negative")
    by_id = _cases_by_id(cases)
    rows = sorted(report.results, key=lambda row: row.case_id)
    profiles = {row.case_id: profile(row) for row in rows}
    base: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        for name, values in profiles[row.case_id].items():
            base[name].update(values)
    members: dict[str, list[CaseResult]] = defaultdict(list)
    failing = 0
    for row in rows:
        keys = finding_keys(row, by_id.get(row.case_id))
        if keys:
            failing += 1
        for key in keys:
            members[key].append(row)
    ordered = sorted(members, key=lambda key: (-len(members[key]), key))
    clusters: list[Cluster] = []
    for key in ordered[:top]:
        group = members[key]
        counts: dict[str, Counter[str]] = defaultdict(Counter)
        for row in group:
            for name, values in profiles[row.case_id].items():
                counts[name].update(values)
        lifts: list[DimensionLift] = []
        for name in sorted(counts):
            for value, count in counts[name].items():
                share = _share(count, len(group))
                base_share = _share(base[name][value], len(rows))
                # From the counts, not the rounded shares, so a lift of
                # exactly two prints as 2.0.
                lift = round((count * len(rows)) / (len(group) * base[name][value]), 4) if base[name][value] else 0.0
                if lift > 1.0:
                    lifts.append(DimensionLift(dimension=name, value=value, cases=count, share=share,
                                               base_share=base_share, lift=lift))
        lifts.sort(key=lambda item: (-item.lift, -item.cases, item.dimension, item.value))
        clusters.append(Cluster(
            key=key, axis=axis_of(key), gloss=GLOSSES.get(key, ""), cases=len(group),
            share_of_failures=_share(len(group), failing), case_ids=tuple(row.case_id for row in group),
            dimensions={name: dict(sorted(counts[name].items())) for name in sorted(counts)},
            concentrations=tuple(lifts[:concentrations]),
            exemplars=tuple(Exemplar(case_id=row.case_id, query=_clip(row.query, _QUERY_LIMIT),
                                     evidence=_evidence(key, row, by_id.get(row.case_id)))
                            for row in group[:exemplars]),
        ))
    graded = [row for row in rows if row.graded]
    return Autopsy(
        agent=report.agent, case_set=report.case_set, cases=len(rows), graded=len(graded),
        errors=len(rows) - len(graded),
        passed=sum(1 for row in graded if row.score is not None and row.score.passed),
        failing=failing,
        base={name: dict(sorted(base[name].items())) for name in sorted(base)},
        clusters=tuple(clusters),
        omitted={key: len(members[key]) for key in ordered[top:]},
    )


def render_brief(report: Autopsy, *, clusters: int | None = None) -> str:
    """The autopsy as plain text an improving harness can take as its instructions.

    Most frequent finding first, each with what it means, where it
    concentrates and one or two cases to look at. No markup, no colour, no
    line longer than the evidence clip plus its indent.
    """

    shown: Sequence[Cluster] = report.clusters if clusters is None else report.clusters[:clusters]
    lines = [
        f"Autopsy of agent {report.agent!r} over case set {report.case_set[:16]}:",
        f"{report.failing} of {report.cases} case(s) failed ({report.errors} errored, {report.passed} passed).",
    ]
    if not shown:
        lines.append("No failing case: nothing to improve on this case set; consider escalating its difficulty.")
        return "\n".join(lines) + "\n"
    lines.append("Findings, most frequent first (one case can carry several):")
    for number, cluster in enumerate(shown, start=1):
        lines.append("")
        lines.append(f"{number}. {cluster.key}: {cluster.cases} case(s), {round(cluster.share_of_failures * 100)}% of failures")
        if cluster.gloss:
            lines.append(f"   meaning: {cluster.gloss}")
        if cluster.concentrations:
            lines.append("   concentrated in: " + ", ".join(
                f"{item.dimension}={item.value} (x{item.lift}, {item.cases} case(s))" for item in cluster.concentrations))
        for exemplar in cluster.exemplars:
            lines.append(f"   example {exemplar.case_id}: {exemplar.query}")
            lines.extend(f"     - {line}" for line in exemplar.evidence)
    hidden = len(report.clusters) - len(shown) + len(report.omitted)
    if hidden:
        lines.append("")
        lines.append(f"{hidden} smaller finding(s) not shown.")
    lines.append("")
    lines.append("Fix the behaviour behind the most frequent findings first; do not special-case the example ids.")
    return "\n".join(lines) + "\n"


def autopsy_summary(report: Autopsy) -> dict[str, Any]:
    """Key to case count, for a one-line log or a comparison of two autopsies."""

    counts = {cluster.key: cluster.cases for cluster in report.clusters}
    counts.update(report.omitted)
    return dict(sorted(counts.items()))


__all__ = [
    "AUTOPSY_SCHEMA",
    "GLOSSES",
    "PROFILE_DIMENSIONS",
    "Autopsy",
    "Cluster",
    "DimensionLift",
    "Exemplar",
    "autopsy",
    "autopsy_summary",
    "axis_of",
    "finding_keys",
    "profile",
    "render_brief",
]
