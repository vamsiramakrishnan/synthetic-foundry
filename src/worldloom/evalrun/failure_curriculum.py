"""Between improve rounds: new training cases aimed at what the last champion failed.

``curriculum.design_curriculum`` turns an autopsy into a fresh ``DatasetPlan``
for the *next* case set, which a campaign compiles between stages. Inside one
``improve`` loop the training set used to stay fixed from round to round, so
the champion that failed ``plan.missing:read`` on six cases in round 1 met the
same six cases in round 2 and nothing more of the kind. This module closes
that gap: after each round it draws new training cases from a pool of
generated cases (corner cases from ``evalrun corners``, a larger compile of
the same dataset, any case set), aimed at the clusters the round's champion
failed, sized by each cluster's case count.

Three parts, each a pure function of its inputs:

- ``FINDING_TARGETS`` declares, as data, which case templates and which
  generation dimensions exercise each autopsy finding key, and
  ``UNMAPPABLE`` names every key no case can be generated for, with the
  reason. ``finding_vocabulary`` enumerates every key the autopsy can emit
  from the grader's own closed vocabularies, and ``check_targets`` says which
  of them has no entry, so a new finding key cannot slip in untargeted (the
  test suite runs it).
- ``draw_failure_cases`` allocates N new cases over the mapped clusters by
  their size (largest remainder), takes each cluster's share from the pool in
  a content-addressed order seeded by the round and the key, gives what a
  cluster cannot fill to the others, and accounts for every cluster it could
  not serve.
- The held-out cases are never a source. A pool case is refused when it
  shares a case id, a content key, a source-record digest (the exact set of
  records it reads and the evidence it cites) or a gold-DAG digest with any
  held-out case, and ``check_unseen`` raises ``HeldOutOverlap`` should one
  ever get through.

The draw is deterministic: the same autopsy, pool, training set and held-out
set give the same cases in the same order, whatever order the pool arrived in.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, get_args

from ..ids import content_key
from .autopsy import GLOSSES, Autopsy, Cluster
from .contract import EvalCase, OutcomeKind
from .grading import QUESTION_LAWS, SAFETY_LAWS
from .safety import ErrorCode
from .stages import STAGE_FINDINGS

#: The one curriculum mode the improve loop knows: new cases from the failures.
CURRICULUM_MODES: tuple[str, ...] = ("failures",)
#: New training cases a round adds when the caller names no count.
DEFAULT_CURRICULUM_CASES = 8

#: What ``plan.missing:<kind>`` can carry: the case contract's node kinds with
#: search folded into read (``autopsy._node_kind``), and ``other`` for a node
#: id that names no role the DAG grammar uses.
PLAN_MISSING_KINDS: tuple[str, ...] = ("read", "write", "verify", "other")
#: What ``plan.node_missing:<kind>`` and ``plan.node_extra:<kind>`` can carry
#: (``stages._gold_kind`` and ``stages._tool_kind``).
STAGE_NODE_KINDS: tuple[str, ...] = ("search", "read", "create", "update", "delete")
#: Stage families the stages module keys by node kind.
_KEYED_STAGE_FAMILIES: tuple[str, ...] = ("plan.node_missing", "plan.node_extra")

_DESIGNED_FAILURES: tuple[str, ...] = (
    "ambiguous_join", "missing_stable_id", "partial_write", "permission_denied", "stale_source", "version_conflict",
)
_SEARCH_SHAPES: tuple[str, ...] = ("map_read", "conditional")
_ORDERED_SHAPES: tuple[str, ...] = ("read_chain", "deep_chain", "write_chain", "delete_chain")


@dataclass(frozen=True)
class FindingTarget:
    """The cases that exercise one finding key.

    A pool case matches when it is a corner case of one of ``templates``
    (its ``corner`` dimension), or, for any other case, when every dimension
    in ``where`` takes one of the listed values and every dimension in
    ``follow`` takes the value that holds a majority of the failing cluster.
    A target whose ``where`` and resolved ``follow`` are both empty admits
    no non-corner case: "more of anything" exercises nothing in particular.
    """

    why: str
    templates: tuple[str, ...] = ()
    where: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    follow: tuple[str, ...] = ()


def _t(why: str, *, templates: tuple[str, ...] = (), where: Mapping[str, tuple[str, ...]] | None = None,
       follow: tuple[str, ...] = ()) -> FindingTarget:
    return FindingTarget(why=why, templates=templates, where=dict(where or {}), follow=follow)


_READ_TARGET = _t("evidence that must be found before anything is written: the superseded and the current record, "
                  "or the handover record, and search-led shapes",
                  templates=("confirmed_cause", "approver_handover"), follow=("dag_shape",))
_WRITE_TARGET = _t("more cases whose plan writes, in the shape and operation the misses concentrate in",
                   follow=("dag_shape", "operation"))
_NO_WRITE_TARGET = _t("a refused write that must leave nothing behind, and the shapes the extra writes came from",
                      templates=("escalated_exception",), follow=("dag_shape",))
_ORDER_TARGET = _t("shapes whose nodes depend on one another in sequence",
                   where={"dag_shape": _ORDERED_SHAPES}, follow=("dag_shape",))
_SOURCE_TARGET = _t("a value that must come from the record the plan read, beside an older record that also "
                    "names one", templates=("confirmed_cause", "approver_handover"))
_QUESTION_TARGET = _t("restatements whose as-of decides the answer: some variants name it, one requires the agent "
                      "to ask", templates=("restated_figure",))
_DESIGNED_TARGET = _t("a designed failure on the node it waits at: the world's own refusal, and dataset rows "
                      "carrying the designed failure the cluster met", templates=("escalated_exception",),
                      where={"failure": _DESIGNED_FAILURES}, follow=("failure", "dag_shape"))
_RETRY_TARGET = _t("a refusal that must be met, not retried", templates=("escalated_exception",),
                   where={"failure": ("partial_write", "permission_denied", "version_conflict")})
_GROUNDING_TARGET = _t("answers that must cite the figures on the record as of a date",
                       templates=("restated_figure", "confirmed_cause"), follow=("dag_shape",))
_SEARCH_TARGET = _t("search-led shapes, where the query decides what evidence there is",
                    where={"dag_shape": _SEARCH_SHAPES}, follow=("dag_shape",))
_OUTPUT_TARGET = _t("the same output format and destination the mismatches concentrate in",
                    follow=("output_format", "destination"))

#: Finding key to the cases that exercise it. Every key ``finding_vocabulary``
#: names is here or in ``UNMAPPABLE``, never both (``check_targets``).
FINDING_TARGETS: dict[str, FindingTarget] = {
    # -- trajectory ------------------------------------------------------------------
    "trajectory.safety:duplicate_write": _t("shapes with more than one write, where a write can be issued twice",
                                            where={"dag_shape": ("write_chain", "fan_out", "delete_chain")},
                                            follow=("operation",)),
    "trajectory.safety:unsafe_retry": _RETRY_TARGET,
    "trajectory.safety:destructive_without_read": _t("shapes that update or delete a record they must read first",
                                                     where={"dag_shape": ("write_chain", "delete_chain")}),
    "trajectory.question:acted_without_asking": _QUESTION_TARGET,
    "trajectory.question:asked_too_late": _QUESTION_TARGET,
    "trajectory.question:ignored_the_answer": _QUESTION_TARGET,
    "trajectory.question:asked_without_need": _QUESTION_TARGET,
    "trajectory.failure_leaked": _DESIGNED_TARGET,
    "trajectory.failure_not_reached": _DESIGNED_TARGET,
    "trajectory.budget_exceeded": _t("the shapes whose call budget the runs exceeded", follow=("dag_shape",)),
    "trajectory.retry_storm": _RETRY_TARGET,
    # -- plan --------------------------------------------------------------------------
    "plan.missing:read": _READ_TARGET,
    "plan.missing:write": _WRITE_TARGET,
    "plan.missing:verify": _t("shapes that read a write back, in the shape the misses concentrate in",
                              where={"dag_shape": ("write_chain", "delete_chain", "fan_out", "fan_in", "map_read")},
                              follow=("dag_shape",)),
    "plan.extra_write": _NO_WRITE_TARGET,
    "plan.order": _ORDER_TARGET,
    "plan.node_missing:search": _READ_TARGET,
    "plan.node_missing:read": _READ_TARGET,
    "plan.node_missing:create": _WRITE_TARGET,
    "plan.node_missing:update": _t("an update to the record the evidence names",
                                   templates=("confirmed_cause", "approver_handover"),
                                   where={"dag_shape": ("write_chain",)}),
    "plan.node_missing:delete": _t("a delete of the exact record written", where={"dag_shape": ("delete_chain",)}),
    "plan.node_extra:search": _t("the shapes the extra searches came from", follow=("dag_shape",)),
    "plan.node_extra:read": _t("the shapes the extra reads came from", follow=("dag_shape",)),
    "plan.node_extra:create": _NO_WRITE_TARGET,
    "plan.node_extra:update": _NO_WRITE_TARGET,
    "plan.node_extra:delete": _NO_WRITE_TARGET,
    "plan.node_misordered": _ORDER_TARGET,
    "plan.edge_missing": _t("a value that must be taken from an earlier read, never guessed",
                            templates=("confirmed_cause", "approver_handover"),
                            where={"dag_shape": ("read_chain", "deep_chain", "write_chain")}),
    "plan.edge_spurious": _t("shapes with independent branches that must stay independent",
                             where={"dag_shape": ("diamond", "fan_in", "fan_out")}, follow=("dag_shape",)),
    "plan.wrong_source": _SOURCE_TARGET,
    "plan.wrong_branch": _t("a conditional whose branch the data selects", where={"dag_shape": ("conditional",)}),
    # -- outcomes ----------------------------------------------------------------------
    "outcomes.unmet:create": _WRITE_TARGET,
    "outcomes.unmet:update": _t("a state post-condition on the record the evidence names",
                                templates=("confirmed_cause", "approver_handover"),
                                where={"dag_shape": ("write_chain",)}),
    "outcomes.unmet:delete": _t("a delete whose absence is checked", where={"dag_shape": ("delete_chain",)}),
    "outcomes.collateral": _NO_WRITE_TARGET,
    "outcomes.ungrounded": _GROUNDING_TARGET,
    "outcomes.answer_below_threshold": _GROUNDING_TARGET,
    # -- errors the agent's own calls provoke ----------------------------------------------
    "error:validation_error": _SEARCH_TARGET,
    "error:schema_mismatch": _SEARCH_TARGET,
    "error:permission_denied": _t("a write outside the agent's authority",
                                  templates=("escalated_exception",), where={"failure": ("permission_denied",)}),
    "error:policy_denied": _t("a write a policy refuses", templates=("escalated_exception",),
                              where={"failure": ("permission_denied",)}),
    "error:not_found": _t("records whose stable id is missing or stale",
                          where={"failure": ("missing_stable_id", "stale_source")}),
    "error:conflict": _t("a write that meets a newer version", where={"failure": ("version_conflict",)}),
    "error:unsafe_retry_blocked": _RETRY_TARGET,
    "error:idempotency_required": _t("a write that half lands and must be finished idempotently",
                                     where={"failure": ("partial_write",)}),
    "error:confirmation_required": _t("a destructive call that needs confirmation",
                                      where={"dag_shape": ("delete_chain",)}),
    # -- stages ------------------------------------------------------------------------
    "query.missed_evidence": _t("evidence a search must retrieve beside a record that looks like it",
                                templates=("confirmed_cause", "approver_handover"),
                                where={"dag_shape": _SEARCH_SHAPES}, follow=("dag_shape",)),
    "query.overfetch": _t("searches with a declared result bound", where={"dag_shape": ("map_read",)}),
    "query.missing_filter": _t("searches that must filter on what the node constrains",
                               templates=("approver_handover",), where={"dag_shape": _SEARCH_SHAPES}),
    "query.wrong_window": _t("an as-of that decides which record counts", templates=("restated_figure",)),
    "query.malformed": _SEARCH_TARGET,
    "query.wrong_scope": _t("search-led shapes on the destination the stray searches concentrate in",
                            where={"dag_shape": _SEARCH_SHAPES}, follow=("destination",)),
    "query.zero_result": _t("a search with evidence to find", templates=("confirmed_cause",),
                            where={"dag_shape": _SEARCH_SHAPES}),
    "output.field_mismatch": _t("a written field whose value comes from the evidence",
                                templates=("confirmed_cause", "approver_handover"), follow=("operation",)),
    "output.wrong_format": _OUTPUT_TARGET,
    "output.missing_section": _OUTPUT_TARGET,
    "output.ungrounded_fact": _GROUNDING_TARGET,
}

_TRANSPORT = ("served by the emulator's transport, not designed by any case template or dataset dimension, so no "
              "generated case exercises it more than another")

#: Finding keys no case can be generated for, with the reason. Each is still
#: clustered and briefed; the curriculum only declines to buy cases for it.
UNMAPPABLE: dict[str, str] = {
    "run.errored": "describes the run (the agent raised or the case could not be graded), not the agent's behaviour",
    "unclassified": "no finding explains the failure: a grader gap to report, with nothing to aim a case at",
    "assertion.fail": "the row's own verdict failed with no finding naming why, so there is no kind to ask for",
    "outcomes.answer_unrated": "the rater could not judge the answer: a measurement failure, not the agent's",
    "trajectory.refused_call": ("a call outside the served tool surface: every case serves the same tools, so the "
                                "interface lever owns it and no case template exercises it more than another"),
    "plan.missing:other": "the node id names no role the DAG grammar uses, so there is no node kind to ask for",
    "plan.serialised": "an efficiency observation that never fails a case; buying cases for it trades correctness for speed",
    "query.error": "a search met an undesigned error; its code is the actionable finding, keyed as error:<code>",
    "error:unsupported_operation": ("the served surface lacks the operation: an interface finding, and every case "
                                    "serves the same surface"),
    "error:auth_required": "credentials belong to the harness that serves the run, not to any case",
    "error:rate_limited": _TRANSPORT,
    "error:upstream_timeout": _TRANSPORT,
    "error:upstream_unavailable": _TRANSPORT,
    "error:unknown_upstream_error": _TRANSPORT,
    "error:idempotency_ledger_unavailable": _TRANSPORT,
}


# -- the vocabulary and its lint ------------------------------------------------------------


def finding_vocabulary() -> tuple[str, ...]:
    """Every key ``autopsy.finding_keys`` can emit, from the grader's own closed vocabularies, sorted."""

    keys: set[str] = {key for key in GLOSSES if key.split(":", 1)[0] not in _KEYED_STAGE_FAMILIES}
    keys -= set(_KEYED_STAGE_FAMILIES)
    keys.update(f"trajectory.safety:{law}" for law in SAFETY_LAWS)
    keys.update(f"trajectory.question:{law}" for law in QUESTION_LAWS)
    keys.update(f"plan.missing:{kind}" for kind in PLAN_MISSING_KINDS)
    keys.update(f"outcomes.unmet:{kind}" for kind in get_args(OutcomeKind))
    keys.update(f"error:{code.value}" for code in ErrorCode)
    keys.update(key for key in STAGE_FINDINGS if key not in _KEYED_STAGE_FAMILIES)
    keys.update(f"{family}:{kind}" for family in _KEYED_STAGE_FAMILIES for kind in STAGE_NODE_KINDS)
    return tuple(sorted(keys))


def check_targets() -> list[str]:
    """Problems with the declared mapping, one line each; empty when every key is accounted for.

    A key of the vocabulary with no entry, an entry for a key the autopsy
    cannot emit, a key both mapped and unmappable, a template no corner
    generator ships, or a ``where`` value no dataset row can carry.
    """

    from ..enterprise_dag_planning import shape_catalogue
    from ..enterprise_specs import CoverageProfile
    from .corners import TEMPLATE_IDS

    problems: list[str] = []
    vocabulary = set(finding_vocabulary())
    declared = set(FINDING_TARGETS) | set(UNMAPPABLE)
    problems.extend(f"{key}: no entry in FINDING_TARGETS or UNMAPPABLE" for key in sorted(vocabulary - declared))
    problems.extend(f"{key}: declared but the autopsy cannot emit it" for key in sorted(declared - vocabulary))
    problems.extend(f"{key}: both mapped and unmappable" for key in sorted(set(FINDING_TARGETS) & set(UNMAPPABLE)))
    known = {"failure": set(CoverageProfile().failures), "dag_shape": set(shape_catalogue())}
    for key, target in sorted(FINDING_TARGETS.items()):
        if not target.why:
            problems.append(f"{key}: no reason given")
        if not (target.templates or target.where or target.follow):
            problems.append(f"{key}: names no template, predicate or dimension")
        problems.extend(f"{key}: unknown corner template {name!r}" for name in target.templates
                        if name not in TEMPLATE_IDS)
        for dimension, values in sorted(target.where.items()):
            allowed = known.get(dimension)
            if allowed is not None:
                problems.extend(f"{key}: {dimension}={value!r} is not a value the generator plans"
                                for value in values if value not in allowed)
    problems.extend(f"{key}: no reason given" for key, reason in sorted(UNMAPPABLE.items()) if not reason)
    return problems


# -- fingerprints ------------------------------------------------------------------------------


def case_key(case: EvalCase) -> str:
    """A case's content address: id, request and row (the key ``improve`` refuses overlap by)."""
    return hashlib.sha256(json.dumps({"id": case.id, "query": case.query, "row": case.row}, sort_keys=True,
                                     default=str).encode()).hexdigest()


def _nodes(case: EvalCase) -> list[Mapping[str, Any]]:
    expected = case.row.get("expected_dag") or {}
    nodes = expected.get("nodes", ()) if isinstance(expected, Mapping) else expected
    return [node for node in nodes if isinstance(node, Mapping)]


def source_digest(case: EvalCase) -> str | None:
    """The exact set of records a case reads and the evidence it cites, as one digest; ``None`` when it names none.

    Read from the gold DAG's read and search nodes (``fixture``, ``fixtures``,
    ``expected_reads``, each with its connector), the ``reads_contain``
    assertions, and the row's expected fact and evidence ids. Two cases with
    the same digest rest on the same evidence, whatever their ids say.
    """
    refs: set[str] = set()
    connector_by_node: dict[str, str] = {}
    for node in _nodes(case):
        connector = str(node.get("server") or node.get("connector") or "")
        connector_by_node[str(node.get("id", ""))] = connector
        if str(node.get("node_kind") or node.get("op")) not in {"read", "search", "get", "list", "download"}:
            continue
        values = [*node.get("expected_reads", ()), *node.get("fixtures", ())]
        if node.get("fixture"):
            values.append(node["fixture"])
        refs.update(f"record:{connector}:{value}" for value in values)
    for assertion in case.row.get("assertions", ()):
        if isinstance(assertion, Mapping) and assertion.get("type") == "reads_contain":
            connector = connector_by_node.get(str(assertion.get("node", "")), "")
            refs.update(f"record:{connector}:{value}" for value in assertion.get("records", ()))
    for name, kind in (("expected_fact_ids", "fact"), ("expected_evidence_ids", "evidence")):
        refs.update(f"{kind}:{value}" for value in case.row.get(name, ()) or ())
    return content_key("curriculum-source", *sorted(refs)) if refs else None


def dag_digest(case: EvalCase) -> str | None:
    """The gold DAG's structure over its records, as one digest; ``None`` when the row has none.

    Payloads are left out: the compiler names a write after its case id, so
    a payload would make every DAG unique and the digest say nothing.
    """
    nodes = _nodes(case)
    if not nodes:
        return None
    keep = ("id", "server", "connector", "entity", "node_kind", "op", "fixture", "fixtures", "expected_reads",
            "bindings", "for_each")
    shaped = [{name: node[name] for name in keep if name in node} for node in nodes]
    expected = case.row.get("expected_dag")
    edges = expected.get("edges", ()) if isinstance(expected, Mapping) else ()
    return content_key("curriculum-dag", json.dumps({"nodes": shaped, "edges": list(edges)}, sort_keys=True,
                                                    default=str))


@dataclass(frozen=True)
class _Seal:
    """The fingerprints of a set of cases, in the four ways a case can reappear."""

    ids: frozenset[str]
    keys: frozenset[str]
    sources: frozenset[str]
    dags: frozenset[str]

    @classmethod
    def of(cls, cases: Iterable[EvalCase]) -> _Seal:
        listed = list(cases)
        return cls(ids=frozenset(case.id for case in listed), keys=frozenset(map(case_key, listed)),
                   sources=frozenset(digest for digest in map(source_digest, listed) if digest is not None),
                   dags=frozenset(digest for digest in map(dag_digest, listed) if digest is not None))

    def hits(self, case: EvalCase, *, sources: bool = True) -> list[str]:
        found: list[str] = []
        if case.id in self.ids:
            found.append("case id")
        if case_key(case) in self.keys:
            found.append("content key")
        source = source_digest(case) if sources else None
        if source is not None and source in self.sources:
            found.append("source-record digest")
        dag = dag_digest(case)
        if dag is not None and dag in self.dags:
            found.append("gold-DAG digest")
        return found


class HeldOutOverlap(ValueError):
    """A case about to train shares an id, a content key, a source-record or a gold-DAG digest with a held-out case."""


def check_unseen(added: Sequence[EvalCase], held: Sequence[EvalCase]) -> None:
    """Refuse *added* when any of it could be a held-out case in disguise."""
    seal = _Seal.of(held)
    for case in added:
        hits = seal.hits(case)
        if hits:
            raise HeldOutOverlap(f"curriculum case {case.id} shares its {', '.join(hits)} with a held-out case; "
                                 "the held-out set must stay unseen")


# -- the draw ----------------------------------------------------------------------------------


@dataclass(frozen=True)
class FailureCurriculum:
    """The improve loop's ``failures`` curriculum: where new cases come from and how many a round adds.

    ``exclude`` refuses a pool case the loop would have held out (the stable
    hash split, when the held-out cases are a share of the corpus); the
    pool's own declared held-out splits are always refused.
    """

    pool: tuple[EvalCase, ...]
    cases: int = DEFAULT_CURRICULUM_CASES
    mode: str = "failures"
    exclude: Callable[[EvalCase], bool] | None = None

    def settings(self) -> dict[str, Any]:
        return {"mode": self.mode, "cases_per_round": self.cases, "pool": len(self.pool)}


@dataclass(frozen=True)
class DrawnTarget:
    key: str
    #: The cluster's failing cases, its share of the failures, and the rows asked for it.
    cluster_cases: int
    share_of_failures: float
    allotted: int
    templates: tuple[str, ...]
    #: The predicates a non-corner case had to meet, with ``follow`` resolved against the cluster.
    where: dict[str, tuple[str, ...]]
    #: Eligible pool cases that matched, and the ones this cluster drew.
    available: int
    case_ids: tuple[str, ...]

    def record(self, keys: Mapping[str, str]) -> dict[str, Any]:
        return {"key": self.key, "cluster_cases": self.cluster_cases, "share_of_failures": self.share_of_failures,
                "allotted": self.allotted, "templates": list(self.templates),
                "where": {name: list(values) for name, values in sorted(self.where.items())},
                "available": self.available, "drawn": len(self.case_ids),
                "cases": [{"id": case_id, "key": keys[case_id]} for case_id in self.case_ids]}


@dataclass(frozen=True)
class FailureDraw:
    """The cases one round adds, which cluster drew each, and every cluster that drew none and why."""

    round: int
    requested: int
    cases: tuple[EvalCase, ...]
    targets: tuple[DrawnTarget, ...]
    unmappable: tuple[tuple[str, int, str], ...]
    #: Pool cases refused before the draw: ``held_out`` (they could be a
    #: held-out case), ``duplicate`` (already training, or a repeat in the pool).
    excluded: dict[str, int]

    @property
    def shortfall(self) -> int:
        return self.requested - len(self.cases)

    def record(self, *, source_round: int, train_cases: int, train_case_set: str) -> dict[str, Any]:
        """What a round's receipt carries: which clusters drove which new cases, never the cases themselves."""
        keys = {case.id: case_key(case)[:16] for case in self.cases}
        return {"mode": "failures", "source_round": source_round, "requested": self.requested,
                "added": len(self.cases), "shortfall": self.shortfall,
                "train_cases": train_cases, "train_case_set": train_case_set,
                "targets": [target.record(keys) for target in self.targets],
                "unmappable": [{"key": key, "cases": cases, "reason": reason}
                               for key, cases, reason in self.unmappable],
                "excluded": dict(sorted(self.excluded.items()))}


def _resolve(target: FindingTarget, cluster: Cluster, dominance: float) -> dict[str, tuple[str, ...]]:
    where = {name: tuple(values) for name, values in target.where.items()}
    for dimension in target.follow:
        counts = cluster.dimensions.get(dimension) or {}
        if not counts or not cluster.cases:
            continue
        value, count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
        if count / cluster.cases < dominance or (dimension == "dag_shape" and value in {"legacy", "none"}):
            continue
        if dimension in where and value not in where[dimension]:
            # The cluster concentrates outside what the key asks for: the
            # key's own predicate wins, so the case still exercises it.
            continue
        where[dimension] = (value,)
    return where


def _matches(case: EvalCase, templates: tuple[str, ...], where: Mapping[str, tuple[str, ...]]) -> bool:
    corner = case.dimensions.get("corner")
    if corner:
        return corner in templates
    if not where:
        return False
    return all(case.dimensions.get(name) in values for name, values in where.items())


def _allot(weights: Sequence[int], total: int) -> list[int]:
    """Largest-remainder shares of *total* by *weights*; ties to the earlier entry."""
    whole = sum(weights)
    if not weights or whole <= 0 or total <= 0:
        return [0] * len(weights)
    raw = [total * weight / whole for weight in weights]
    counts = [int(value) for value in raw]
    order = sorted(range(len(raw)), key=lambda index: (-(raw[index] - counts[index]), index))
    for index in order[: total - sum(counts)]:
        counts[index] += 1
    return counts


def draw_failure_cases(found: Autopsy, pool: Iterable[EvalCase], *, count: int, round: int,
                       train: Sequence[EvalCase], held: Sequence[EvalCase],
                       exclude: Callable[[EvalCase], bool] | None = None,
                       dominance: float = 0.5) -> FailureDraw:
    """Up to *count* pool cases aimed at *found*'s clusters, never a held-out case nor one already training.

    Clusters are funded by case count (largest remainder over the mapped
    clusters that have a matching case); a cluster takes its share in a
    content-addressed order seeded by *round* and its key, and what it could
    not fill passes, one case at a time, to the clusters that can, largest
    first. A case drawn by one cluster is not drawn again by another.
    """
    from .splits import declared_split, is_held_out

    if count < 1:
        raise ValueError(f"a curriculum round adds at least one case, not {count}")
    sealed = _Seal.of(held)
    training = _Seal.of(train)
    excluded = {"held_out": 0, "duplicate": 0}
    seen_keys: set[str] = set()
    seen_dags: set[str] = set()
    eligible: list[EvalCase] = []
    # Sorted by content, so the pool's arrival order never reaches the draw.
    for case in sorted(pool, key=lambda item: (case_key(item), item.id)):
        if (sealed.hits(case) or is_held_out(declared_split(case))
                or (exclude is not None and exclude(case))):
            excluded["held_out"] += 1
            continue
        key, dag = case_key(case), dag_digest(case)
        # Evidence shared with a *training* case is fine (that is the
        # point: more of the same kind); the same request or the same gold
        # DAG is a duplicate, and so is a repeat within the pool.
        if (training.hits(case, sources=False) or key in seen_keys or (dag is not None and dag in seen_dags)):
            excluded["duplicate"] += 1
            continue
        seen_keys.add(key)
        if dag is not None:
            seen_dags.add(dag)
        eligible.append(case)

    unmappable: list[tuple[str, int, str]] = []
    plans: list[tuple[Cluster, FindingTarget, dict[str, tuple[str, ...]], list[EvalCase]]] = []
    for cluster in found.clusters:
        if cluster.key in UNMAPPABLE:
            unmappable.append((cluster.key, cluster.cases, UNMAPPABLE[cluster.key]))
            continue
        target = FINDING_TARGETS.get(cluster.key)
        if target is None:
            unmappable.append((cluster.key, cluster.cases, "no entry in FINDING_TARGETS: a finding key the "
                               "curriculum lint has not seen"))
            continue
        where = _resolve(target, cluster, dominance)
        ordered = sorted((case for case in eligible if _matches(case, target.templates, where)),
                         key=lambda case: content_key("failure-curriculum", str(round), cluster.key, case_key(case)))
        plans.append((cluster, target, where, ordered))
    for key, cases in sorted(found.omitted.items()):
        unmappable.append((key, cases, "beyond the autopsy's top clusters"))

    fundable = [index for index, plan in enumerate(plans) if plan[3]]
    shares = _allot([plans[index][0].cases for index in fundable], count)
    allotted = [0] * len(plans)
    for index, share in zip(fundable, shares, strict=True):
        allotted[index] = share
    taken: set[str] = set()
    drawn: list[list[EvalCase]] = [[] for _ in plans]
    cursor = [0] * len(plans)

    def take(index: int) -> bool:
        candidates = plans[index][3]
        while cursor[index] < len(candidates):
            case = candidates[cursor[index]]
            cursor[index] += 1
            if case_key(case) not in taken:
                taken.add(case_key(case))
                drawn[index].append(case)
                return True
        return False

    for index in fundable:
        for _ in range(allotted[index]):
            if not take(index):
                break
    spare = count - len(taken)
    while spare > 0:
        progressed = False
        for index in fundable:
            if spare and take(index):
                spare -= 1
                progressed = True
        if not progressed:
            break

    targets = tuple(DrawnTarget(key=cluster.key, cluster_cases=cluster.cases,
                                share_of_failures=cluster.share_of_failures, allotted=allotted[index],
                                templates=target.templates, where=where, available=len(ordered),
                                case_ids=tuple(case.id for case in drawn[index]))
                    for index, (cluster, target, where, ordered) in enumerate(plans))
    # The new cases join the training set in the order clusters drew them,
    # largest cluster first, so the set's digest is a function of the draw.
    added = tuple(case for cases in drawn for case in cases)
    return FailureDraw(round=round, requested=count, cases=added, targets=targets,
                       unmappable=tuple(unmappable), excluded=excluded)


__all__ = [
    "CURRICULUM_MODES",
    "DEFAULT_CURRICULUM_CASES",
    "FINDING_TARGETS",
    "PLAN_MISSING_KINDS",
    "STAGE_NODE_KINDS",
    "UNMAPPABLE",
    "DrawnTarget",
    "FailureCurriculum",
    "FailureDraw",
    "FindingTarget",
    "HeldOutOverlap",
    "case_key",
    "check_targets",
    "check_unseen",
    "dag_digest",
    "draw_failure_cases",
    "finding_vocabulary",
    "source_digest",
]
