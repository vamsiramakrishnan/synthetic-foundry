"""From an autopsy to the next dataset: more of what failed, harder where it passes.

An autopsy names what an agent gets wrong. Training (or prompting) against
the very cases that exposed it teaches the case ids, not the behaviour, and
the next run over the same set can no longer tell the two apart. So the
curriculum never reuses cases: it writes a new ``DatasetPlan`` whose strata
ask the dataset compiler for *fresh* cases of the failing kinds, under a seed
the base plan never used, with a held-out split so the improvement can be
measured on cases nobody tuned against.

Two functions, both returning data and doing nothing else:

- ``targeted_plan`` maps each actionable cluster onto the compiler's ``where``
  predicates (``failure``, ``dag_shape``, ``operation`` and the other
  dimensions a row carries), sizes its stratum by the cluster's share of the
  failures within a floor and a cap, and says which clusters could not be
  mapped and why. ``design_curriculum`` returns the same plan with that
  account beside it.
- ``escalate`` reads one or more runs, puts a Wilson interval (the
  ``DifficultyCalibrator`` estimator) on the pass rate of every
  ``dag_shape x failure`` and ``shape`` slice, and for each slice whose whole
  interval sits above the target band proposes harder slices: a deeper or
  wider DAG shape, ordered by ``dag_metrics`` over the shape catalogue, or a
  designed failure kind. It also names the cases in that slice that passed
  in every run, which no longer discriminate between agents.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Sequence
from functools import lru_cache
from typing import Any

from pydantic import Field

from ..ids import content_key
from ..models import Model
from .autopsy import Autopsy, Cluster
from .runner import RunReport

#: Dataset ``where`` predicates a cluster can be mapped onto, in the order a
#: stratum's filters are chosen. ``failure`` and ``dag_shape`` first: they are
#: the designed difficulty of a row, and every compiled row carries both.
MAPPABLE_DIMENSIONS: tuple[str, ...] = (
    "failure", "dag_shape", "operation", "workflow", "destination", "destination_entity", "output_format",
)

#: Key families that describe the run, not the agent's behaviour: more cases
#: of them teach nothing.
_UNACTIONABLE = ("run.", "unclassified")


class CurriculumTarget(Model):
    """One stratum of the new plan and the clusters it answers."""

    stratum: str
    keys: tuple[str, ...]
    where: dict[str, str]
    count: int
    share_of_failures: float
    base_stratum: str


class Unmapped(Model):
    key: str
    cases: int
    reason: str


class Curriculum(Model):
    schema_version: str = Field(default="worldloom.eval-curriculum/v1", alias="schema")
    round: int
    seed: int
    base_seed: int
    plan: dict[str, Any]
    targets: tuple[CurriculumTarget, ...]
    unmappable: tuple[Unmapped, ...]

    def dataset_plan(self) -> Any:
        from ..evals.company_dataset import load_dataset_plan

        return load_dataset_plan(self.plan)


def curriculum_seed(base_seed: int, round_number: int) -> int:
    """A seed for round ``round_number`` that is never the base seed.

    Content-addressed from both, so round 2 of one base never collides with
    round 1, and a rerun of the same round asks for the same cases.
    """

    if round_number < 1:
        raise ValueError("curriculum rounds start at 1")
    derived = int(content_key("eval-curriculum-seed", str(base_seed), str(round_number))[:8], 16)
    return derived if derived != base_seed else derived + 1


def _dominant(cluster: Cluster, dimension: str, dominance: float) -> str | None:
    counts = cluster.dimensions.get(dimension) or {}
    if not counts:
        return None
    value, count = sorted(counts.items(), key=lambda item: (-item[1], item[0]))[0]
    if value in {"legacy", "none"} and dimension == "dag_shape":
        return None
    return value if count / cluster.cases >= dominance else None


def cluster_filters(
    cluster: Cluster,
    *,
    base: dict[str, dict[str, int]] | None = None,
    cases: int = 0,
    dominance: float = 0.5,
) -> dict[str, str]:
    """The ``where`` predicates a cluster maps onto.

    ``failure`` and ``dag_shape`` are the designed difficulty of a row, so
    each is taken when its modal value holds a ``dominance`` majority of the
    cluster. Every other mappable dimension must also *concentrate*: given
    the run's counts (``base``, over ``cases`` rows) its modal value must be
    more common in the cluster than in the run. A dimension every case
    shares (one workflow, one destination) is then left to the base
    stratum, instead of pinning the new stratum to a value that explains
    nothing. ``failure=none`` is a filter like any other: plan misses on
    ordinary rows are answered with ordinary rows. A designed-failure key
    (``trajectory.failure_leaked``, ``failure_not_reached``) insists on a
    designed failure, so its modal *non-none* failure is taken whatever its
    share.
    """

    where: dict[str, str] = {}
    for dimension in MAPPABLE_DIMENSIONS:
        value = _dominant(cluster, dimension, dominance)
        if value is None:
            continue
        if dimension not in {"failure", "dag_shape"} and base is not None and cases:
            inside = cluster.dimensions[dimension][value] / cluster.cases
            overall = (base.get(dimension) or {}).get(value, 0) / cases
            if inside <= overall:
                continue
        where[dimension] = value
    if cluster.key in {"trajectory.failure_leaked", "trajectory.failure_not_reached"}:
        designed = {value: count for value, count in (cluster.dimensions.get("failure") or {}).items() if value != "none"}
        if designed:
            where["failure"] = sorted(designed.items(), key=lambda item: (-item[1], item[0]))[0][0]
    return where


@lru_cache(maxsize=1)
def _shaped_failures() -> frozenset[str]:
    """Designed failure kinds the DAG grammar admits, read from the planner rather than restated."""

    from ..enterprise_dag_planning import compatible_shapes
    from ..enterprise_specs import CoverageProfile

    row = {"source_entities": "probe:record", "operation": "create", "destination": "probe",
           "destination_entity": "record", "output_format": "html"}
    return frozenset(failure for failure in CoverageProfile().failures
                     if compatible_shapes({**row, "failure": failure}, ("fan_in",)))


def _slug(key: str) -> str:
    out = "".join(char if char.isalnum() else "-" for char in key.lower())
    return "-".join(part for part in out.split("-") if part)


def _allocate(weights: Sequence[float], total: int, floor: int, cap: int) -> list[int]:
    """Largest-remainder shares of ``total``, each within ``[floor, cap]``; deterministic."""

    count = len(weights)
    counts = [floor] * count
    remaining = total - floor * count
    if remaining <= 0:
        return counts
    whole = sum(weights) or float(count)
    raw = [remaining * (weight or (whole / count)) / whole for weight in weights]
    for index, value in enumerate(raw):
        counts[index] = min(cap, counts[index] + int(value))
    order = sorted(range(count), key=lambda index: (-(raw[index] - int(raw[index])), index))
    spare = total - sum(counts)
    while spare > 0:
        progressed = False
        for index in order:
            if spare and counts[index] < cap:
                counts[index] += 1
                spare -= 1
                progressed = True
        if not progressed:
            break
    return counts


def _choose_stratum(base: Any, where: dict[str, str]) -> tuple[Any, str | None]:
    """The base stratum a target is generated from, or the reason none can be.

    A stratum qualifies when its own ``where`` does not contradict the target
    and, for a workflow filter, its scenario declares that workflow. Among
    those, the one already closest to the target (fewest source edits) wins,
    then plan order.
    """

    best: tuple[int, int, Any] | None = None
    for position, stratum in enumerate(base.strata):
        source = stratum.source
        if any(key in source.where and source.where[key] != value for key, value in where.items()):
            continue
        workflows = set(source.scenario.workflows) | {item.name for item in source.scenario.additional_workflows}
        if "workflow" in where and workflows and where["workflow"] not in workflows:
            continue
        edits = 0
        if "dag_shape" in where and source.dag_shapes != ("*",) and where["dag_shape"] not in source.dag_shapes:
            edits += 1
        if "failure" in where and where["failure"] not in source.scenario.coverage.failures:
            edits += 1
        if best is None or (edits, position) < best[:2]:
            best = (edits, position, stratum)
    if best is None:
        return None, "no base stratum admits these predicates"
    return best[2], None


def _source_for(stratum: Any, where: dict[str, str]) -> dict[str, Any]:
    source = stratum.source.model_dump(mode="json")
    source["where"] = dict(sorted({**source.get("where", {}), **where}.items()))
    if "dag_shape" in where:
        source["dag_shapes"] = [where["dag_shape"]]
    if "failure" in where:
        # Generate only the failure asked for: the compiler filters the pool
        # by `where` after planning, so a coverage profile spanning every
        # failure would plan (and discard) six rows for each one it keeps.
        source["scenario"]["coverage"]["failures"] = [where["failure"]]
    return source


def design_curriculum(
    report: Autopsy,
    base: Any,
    *,
    seed: int | None = None,
    round: int = 1,
    total: int | None = None,
    min_per_cluster: int = 4,
    max_share: float = 0.5,
    holdout_share: float = 0.2,
    dominance: float = 0.5,
) -> Curriculum:
    """The targeted plan for one improvement round, with an account of every cluster.

    ``total`` defaults to the base plan's row count. Each stratum gets at
    least ``min_per_cluster`` rows and at most ``max_share`` of the total;
    between those bounds its count is proportional to its clusters' share
    of failures. Clusters that map onto the same predicates share a stratum.
    ``holdout_share`` becomes the ``test`` split weight; the rest is ``train``.
    Everything not in a stratum is in ``unmappable`` with its reason.
    """

    from ..evals.company_dataset import load_dataset_plan

    if not 0.0 < holdout_share < 1.0:
        raise ValueError("holdout_share must be strictly between 0 and 1")
    if min_per_cluster < 1 or not 0.0 < max_share <= 1.0:
        raise ValueError("min_per_cluster must be positive and max_share in (0, 1]")
    chosen_seed = curriculum_seed(base.seed, round) if seed is None else seed
    if chosen_seed == base.seed:
        raise ValueError("a curriculum must not reuse the base plan's seed: its cases are the ones that exposed the failures")
    budget = total if total is not None else sum(stratum.count for stratum in base.strata)
    if budget < 1:
        raise ValueError("total must be positive")

    unmapped: list[Unmapped] = []
    grouped: dict[tuple[tuple[str, str], ...], list[Cluster]] = {}
    for cluster in report.clusters:
        if cluster.key.startswith(_UNACTIONABLE):
            unmapped.append(Unmapped(key=cluster.key, cases=cluster.cases,
                                     reason="describes the run, not the agent's behaviour"))
            continue
        where = cluster_filters(cluster, base=report.base, cases=report.cases, dominance=dominance)
        if not where:
            reason = ("its cases carry no dataset dimensions" if not any(
                cluster.dimensions.get(name) for name in MAPPABLE_DIMENSIONS)
                else f"no dataset dimension holds a {dominance:.0%} majority of its cases")
            unmapped.append(Unmapped(key=cluster.key, cases=cluster.cases, reason=reason))
            continue
        # A dataset source always plans under DAG shapes (its validator
        # refuses an empty selection), and the grammar admits no shape under
        # some failure kinds, so a stratum asking for one would never fill.
        if where.get("failure", "none") not in _shaped_failures():
            unmapped.append(Unmapped(key=cluster.key, cases=cluster.cases,
                                     reason=f"the DAG grammar admits no shape under failure {where['failure']}"))
            continue
        grouped.setdefault(tuple(sorted(where.items())), []).append(cluster)
    for key, cases in sorted(report.omitted.items()):
        unmapped.append(Unmapped(key=key, cases=cases, reason="beyond the autopsy's top clusters"))

    candidates: list[tuple[tuple[tuple[str, str], ...], list[Cluster], Any]] = []
    for filters, clusters in sorted(grouped.items(), key=lambda item: (-max(c.cases for c in item[1]), item[0])):
        stratum, why = _choose_stratum(base, dict(filters))
        if stratum is None:
            unmapped.extend(Unmapped(key=cluster.key, cases=cluster.cases, reason=str(why)) for cluster in clusters)
            continue
        candidates.append((filters, clusters, stratum))
    fundable = max(1, budget // min_per_cluster)
    for _, clusters, _ in candidates[fundable:]:
        unmapped.extend(Unmapped(key=cluster.key, cases=cluster.cases,
                                 reason=f"total {budget} funds {fundable} stratum(s) at {min_per_cluster} rows") for cluster in clusters)
    candidates = candidates[:fundable]
    if not candidates:
        raise ValueError("no failing cluster maps onto a dataset stratum: " + "; ".join(
            f"{item.key} ({item.reason})" for item in unmapped) if unmapped else "the autopsy has no failing cluster")

    shares = [max(cluster.share_of_failures for cluster in clusters) for _, clusters, _ in candidates]
    cap = max(min_per_cluster, int(budget * max_share)) if len(candidates) > 1 else budget
    counts = _allocate(shares, budget, min_per_cluster, cap)
    targets: list[CurriculumTarget] = []
    strata: list[dict[str, Any]] = []
    used: set[str] = set()
    for (filters, clusters, stratum), count, share in zip(candidates, counts, shares, strict=True):
        name = f"r{round}-{_slug(clusters[0].key)}"
        suffix = 2
        while name in used:
            name = f"r{round}-{_slug(clusters[0].key)}-{suffix}"
            suffix += 1
        used.add(name)
        where = dict(filters)
        strata.append({"id": name, "count": count, "source": _source_for(stratum, where)})
        targets.append(CurriculumTarget(stratum=name, keys=tuple(cluster.key for cluster in clusters), where=where,
                                        count=count, share_of_failures=share, base_stratum=stratum.id))

    rows = sum(counts)
    holdout = max(1, min(99, round_half_up(holdout_share * 100)))
    payload = base.model_dump(mode="json")
    for per_stratum in ("lineage", "generation_contracts", "split_assignments"):
        payload.pop(per_stratum, None)
    payload.update(
        seed=chosen_seed, strata=strata, split_weights={"train": 100 - holdout, "test": holdout},
        minimum_tasks=min(base.minimum_tasks, rows), minimum_companies=min(base.minimum_companies, rows),
    )
    plan = load_dataset_plan(payload)
    return Curriculum(round=round, seed=chosen_seed, base_seed=base.seed, plan=plan.model_dump(mode="json"),
                      targets=tuple(targets), unmappable=tuple(unmapped))


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def targeted_plan(
    report: Autopsy,
    base: Any,
    *,
    seed: int | None = None,
    round: int = 1,
    total: int | None = None,
    min_per_cluster: int = 4,
    max_share: float = 0.5,
    holdout_share: float = 0.2,
) -> Any:
    """The ``DatasetPlan`` of ``design_curriculum``; use that to see what was unmappable."""

    return design_curriculum(report, base, seed=seed, round=round, total=total, min_per_cluster=min_per_cluster,
                             max_share=max_share, holdout_share=holdout_share).dataset_plan()


# -- escalation -----------------------------------------------------------------


@lru_cache(maxsize=1)
def shape_difficulty() -> tuple[tuple[str, int, dict[str, int]], ...]:
    """Every catalogue shape with its load and ``dag_metrics``, easiest first.

    Each shape is applied to one fixed probe request (two sources, a create)
    so the shapes differ only in what the shape adds. Load is ``nodes +
    depth + width + conditional + for_each``: every term is something an
    agent must get right, and a tie is broken by name so the order is total.
    """

    from ..enterprise_dag import (
        EnterpriseDag,
        EnterpriseDagNode,
        dag_metrics,
        shape_catalogue,
    )
    from ..enterprise_dag_planning import apply_dag_shape
    from ..enterprise_queries import (
        GenerationRequirement,
        MutationRequirement,
        PlannedEnterpriseQuery,
        SourceRequirement,
    )

    probe = PlannedEnterpriseQuery(
        id="difficulty-probe", workflow="probe", query="probe", dimensions={}, expected_dag=(),
        generation=GenerationRequirement(
            process="probe",
            source_requirements=(SourceRequirement(connector="probe-a", entity="record"),
                                 SourceRequirement(connector="probe-b", entity="record")),
            mutation=MutationRequirement(connector="probe-c", entity="record", operation="create",
                                         output_format="html", preexisting_record=False),
        ),
    )
    rows: list[tuple[str, int, dict[str, int]]] = []
    for shape in sorted(shape_catalogue()):
        shaped = apply_dag_shape(probe, shape)
        metrics = dag_metrics(EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in shaped.expected_dag)))
        load = metrics["nodes"] + metrics["depth"] + metrics["width"] + metrics["conditional"] + metrics["for_each"]
        rows.append((shape, load, metrics))
    return tuple(sorted(rows, key=lambda row: (row[1], row[0])))


def harder_shapes(shape: str | None, *, step: int = 2) -> tuple[str, ...]:
    """The next ``step`` shapes strictly harder than ``shape``; a legacy row's are the easiest ones."""

    ranked = shape_difficulty()
    loads = {name: load for name, load, _ in ranked}
    floor = loads.get(shape or "", -1)
    return tuple(name for name, load, _ in ranked if load > floor)[:step]


class SliceStats(Model):
    kind: str
    slice: dict[str, str]
    trials: int
    successes: int
    pass_rate: float
    interval_low: float
    interval_high: float
    #: ``saturated`` (interval above the band), ``too_hard`` (below it),
    #: ``in_band`` or ``undetermined`` (the interval straddles an edge).
    status: str


class Escalation(Model):
    """One saturated slice and the harder slices to generate in its place."""

    kind: str
    slice: dict[str, str]
    trials: int
    successes: int
    interval_low: float
    interval_high: float
    band: tuple[float, float]
    estimator: str = "laplace-wilson95/v1"
    harder_shapes: tuple[str, ...]
    add_failures: tuple[str, ...]
    #: Dataset ``where`` predicates for the proposed strata, one per proposal.
    proposals: tuple[dict[str, str], ...]
    #: Cases in the slice that passed in every run that observed them.
    retire: tuple[str, ...]
    reason: str


def _trials(history: Any) -> list[tuple[str, dict[str, str], bool]]:
    """``(case_id, {dag_shape, failure, shape}, passed)`` per graded observation.

    Accepts run reports and ``CalibrationObservation``s whose feature
    conditions name ``dag_shape``, ``failure`` or ``shape``; an errored case
    is not a trial, exactly as it is not a zero in ``summarize``.
    """

    from ..eval_metrics import CalibrationObservation

    items: Iterable[Any] = [history] if isinstance(history, (RunReport, CalibrationObservation)) else history
    out: list[tuple[str, dict[str, str], bool]] = []
    for item in items:
        if isinstance(item, RunReport):
            for row in item.results:
                if not row.graded or row.score is None:
                    continue
                shape = row.shape or "legacy"
                out.append((row.case_id, {"dag_shape": row.dimensions.get("dag_shape", shape),
                                          "failure": row.dimensions.get("failure", "none"), "shape": shape},
                            row.score.passed))
        elif isinstance(item, CalibrationObservation):
            conditions = dict(item.features.conditions)
            shape = conditions.get("shape") or conditions.get("dag_shape") or "legacy"
            out.append((item.eval_id, {"dag_shape": conditions.get("dag_shape", shape),
                                       "failure": conditions.get("failure", "none"), "shape": shape}, item.passed))
        else:
            raise TypeError(f"cannot escalate from {type(item).__name__}; pass run reports or calibration observations")
    return out


def slice_stats(history: Any, *, target_band: tuple[float, float] = (0.3, 0.8)) -> tuple[SliceStats, ...]:
    """Wilson intervals per ``dag_shape x failure`` and per ``shape`` slice, sorted by kind and slice."""

    from ..eval_metrics import _wilson

    low_edge, high_edge = target_band
    if not 0.0 <= low_edge < high_edge <= 1.0:
        raise ValueError("target_band must be (low, high) with 0 <= low < high <= 1")
    counts: dict[tuple[str, tuple[tuple[str, str], ...]], list[bool]] = defaultdict(list)
    for _, keys, passed in _trials(history):
        counts[("dag_shape x failure", (("dag_shape", keys["dag_shape"]), ("failure", keys["failure"])))].append(passed)
        counts[("shape", (("shape", keys["shape"]),))].append(passed)
    stats: list[SliceStats] = []
    for (kind, key), outcomes in sorted(counts.items()):
        trials, successes = len(outcomes), sum(outcomes)
        low, high = _wilson(successes, trials)
        status = ("saturated" if low > high_edge else "too_hard" if high < low_edge
                  else "in_band" if low >= low_edge and high <= high_edge else "undetermined")
        stats.append(SliceStats(kind=kind, slice=dict(key), trials=trials, successes=successes,
                                pass_rate=round(successes / trials, 4), interval_low=round(low, 4),
                                interval_high=round(high, 4), status=status))
    return tuple(stats)


def escalate(
    history: Any,
    *,
    target_band: tuple[float, float] = (0.3, 0.8),
    step: int = 2,
) -> list[Escalation]:
    """Harder slices for every slice the agent has saturated; data only, nothing generated.

    ``history`` is a run report, a calibration observation, or an iterable
    of either (several rounds pool their trials). A slice is saturated when
    its whole Wilson interval lies above ``target_band``'s upper edge, so a
    handful of lucky passes cannot trigger it. For each, the proposals are
    the ``step`` next-harder DAG shapes under the same failure and, on a
    slice with no designed failure, up to ``step`` designed failure kinds
    the DAG grammar admits whose own slice is not saturated too.
    """

    stats = slice_stats(history, target_band=target_band)
    saturated = {(item.kind, tuple(sorted(item.slice.items()))) for item in stats if item.status == "saturated"}
    observed = {(item.kind, tuple(sorted(item.slice.items()))) for item in stats}
    trials = _trials(history)
    passes: dict[str, list[bool]] = defaultdict(list)
    members: dict[tuple[str, tuple[tuple[str, str], ...]], set[str]] = defaultdict(set)
    for case_id, keys, passed in trials:
        passes[case_id].append(passed)
        members[("dag_shape x failure", (("dag_shape", keys["dag_shape"]), ("failure", keys["failure"])))].add(case_id)
        members[("shape", (("shape", keys["shape"]),))].add(case_id)
    admitted = sorted(_shaped_failures() - {"none"})
    escalations: list[Escalation] = []
    for item in stats:
        if item.status != "saturated":
            continue
        key = tuple(sorted(item.slice.items()))
        shape = item.slice.get("dag_shape") or item.slice.get("shape")
        harder = harder_shapes(None if shape == "legacy" else shape, step=step)
        failure = item.slice.get("failure")
        # One designed failure per row: a slice that already has one can
        # only get harder by shape. A clean slice, or a whole shape, can take
        # a failure kind whose own slice at this shape is not saturated too.
        # Kinds never tried at this shape come first: they are new
        # difficulty, where a kind already observed is only more of it.
        add: list[str] = []
        if failure in (None, "none") and shape and shape != "legacy":
            fresh = sorted(admitted, key=lambda kind: (("dag_shape x failure", (("dag_shape", shape), ("failure", kind))) in observed, kind))
            add = [kind for kind in fresh
                   if ("dag_shape x failure", (("dag_shape", shape), ("failure", kind))) not in saturated][:step]
        proposals: list[dict[str, str]] = []
        for harder_shape in harder:
            proposal = {"dag_shape": harder_shape}
            if failure is not None:
                proposal["failure"] = failure
            proposals.append(proposal)
        if shape and shape != "legacy":
            proposals.extend({"dag_shape": shape, "failure": kind} for kind in add)
        retire = tuple(sorted(case_id for case_id in members[(item.kind, key)] if all(passes[case_id])))
        escalations.append(Escalation(
            kind=item.kind, slice=dict(item.slice), trials=item.trials, successes=item.successes,
            interval_low=item.interval_low, interval_high=item.interval_high, band=target_band,
            harder_shapes=harder, add_failures=tuple(add), proposals=tuple(proposals), retire=retire,
            reason=(f"{item.successes}/{item.trials} passed; the 95% interval "
                    f"[{item.interval_low}, {item.interval_high}] lies above {target_band[1]}"
                    + ("" if proposals else "; nothing in the catalogue is harder, so author a new shape or failure")),
        ))
    return escalations


def escalation_counts(escalations: Sequence[Escalation]) -> dict[str, int]:
    """How many saturated slices per kind; handy in a one-line log."""

    return dict(sorted(Counter(item.kind for item in escalations).items()))


__all__ = [
    "MAPPABLE_DIMENSIONS",
    "Curriculum",
    "CurriculumTarget",
    "Escalation",
    "SliceStats",
    "Unmapped",
    "cluster_filters",
    "curriculum_seed",
    "design_curriculum",
    "escalate",
    "escalation_counts",
    "harder_shapes",
    "shape_difficulty",
    "slice_stats",
    "targeted_plan",
]
