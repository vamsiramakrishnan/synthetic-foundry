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
from collections.abc import Callable, Iterable, Mapping, Sequence
from functools import lru_cache
from typing import Any

from pydantic import Field, model_serializer

from ..ids import content_key
from ..models import Model
from .autopsy import Autopsy, Cluster
from .runner import RunReport
from .value import (
    REPRESENTATIVE_KEY,
    MixCheck,
    ReferenceMix,
    check_mix,
    total_variation,
)

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
    #: How the plan's mix compares with the reference mix, when one was
    #: given; left out of every dump otherwise, so a curriculum designed
    #: without a reference is byte-identical to one written before mixes.
    mix: MixCheck | None = None

    @model_serializer(mode="wrap")
    def _omit_absent_mix(self, handler: Any) -> Any:
        data = handler(self)
        if isinstance(data, dict) and data.get("mix", False) is None:
            data.pop("mix")
        return data

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
    """Largest-remainder shares of ``total``, each within ``[floor, cap]``; deterministic.

    The counts always sum to ``total``. A cap too low to hold it (two strata
    capped at five cannot hold eleven rows) is raised to the even share,
    ``ceil(total / count)``, rather than silently planning fewer rows than
    asked for; a total under ``floor`` per stratum is refused.
    """

    count = len(weights)
    if not count:
        return []
    if total < floor * count:
        raise ValueError(f"total {total} is under the floor of {floor} row(s) for each of {count} stratum(s)")
    cap = max(cap, -(-total // count))
    counts = [floor] * count
    remaining = total - floor * count
    if remaining <= 0:
        return counts
    # A zero weight stands in at the mean weight; the shares are taken over
    # the weights as filled, so they never add up to more than `remaining`.
    fill = (sum(weights) / count) if sum(weights) else 1.0
    filled = [weight or fill for weight in weights]
    whole = sum(filled)
    raw = [remaining * weight / whole for weight in filled]
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
    values: Mapping[str, Any] | None = None,
    reference: ReferenceMix | None = None,
    representative_share: float | None = None,
    max_mix_tvd: float | None = None,
) -> Curriculum:
    """The targeted plan for one improvement round, with an account of every cluster.

    ``total`` defaults to the base plan's row count. Each stratum gets at
    least ``min_per_cluster`` rows and at most ``max_share`` of the total
    (raised to the even share when the funded strata could not otherwise
    hold the total, so the plan always has exactly ``total`` rows); between
    those bounds its count is proportional to its clusters' share of
    failures. A total under ``min_per_cluster`` is refused. Clusters that map onto the same predicates share a stratum.
    ``holdout_share`` becomes the ``test`` split weight; the rest is ``train``.
    Everything not in a stratum is in ``unmappable`` with its reason.

    ``values`` (case id to ``CaseValue`` or a weight) makes each stratum's
    claim its failure share times its relative value (the cluster's mean
    case weight over the failing cases' mean weight, which makes the claim
    the cluster's share of the failing value), for funding order and row
    counts alike; uniform values leave the plan as it was. ``reference`` keeps ``representative_share`` of the rows
    (policy ``evalrun.curriculum.representative_share``) drawn to match the
    reference mix and gives only the rest to failure targets; the share is
    raised when needed so the whole plan stays within ``max_mix_tvd``
    (policy ``evalrun.curriculum.max_mix_tvd``) of the reference, and the
    check is returned as ``mix``. Without either, the plan is exactly the
    one this function wrote before they existed.
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
    if budget < min_per_cluster:
        raise ValueError(f"total {budget} is under min_per_cluster {min_per_cluster}: not even one stratum can be "
                         "funded at its floor; raise --total or lower the floor")

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

    claim = _value_claim(report, values) if values is not None else None

    def priority(item: tuple[tuple[tuple[str, str], ...], list[Cluster]]) -> tuple[Any, ...]:
        if claim is None:
            return (-max(c.cases for c in item[1]), item[0])
        return (-max(claim(c) for c in item[1]), -max(c.cases for c in item[1]), item[0])

    ranked: list[tuple[tuple[tuple[str, str], ...], list[Cluster], Any]] = []
    for filters, clusters in sorted(grouped.items(), key=priority):
        stratum, why = _choose_stratum(base, dict(filters))
        if stratum is None:
            unmapped.extend(Unmapped(key=cluster.key, cases=cluster.cases, reason=str(why)) for cluster in clusters)
            continue
        ranked.append((filters, clusters, stratum))

    def fund(tail: int) -> tuple[list[tuple[tuple[tuple[str, str], ...], list[Cluster], Any]], list[int], list[float], list[Unmapped]]:
        fundable = max(1, tail // min_per_cluster)
        unfunded = [Unmapped(key=cluster.key, cases=cluster.cases,
                             reason=f"total {tail} funds {fundable} stratum(s) at {min_per_cluster} rows")
                    for _, clusters, _ in ranked[fundable:] for cluster in clusters]
        funded = ranked[:fundable]
        if not funded:
            raise ValueError("no failing cluster maps onto a dataset stratum: " + "; ".join(
                f"{item.key} ({item.reason})" for item in [*unmapped, *unfunded]) if unmapped or unfunded
                else "the autopsy has no failing cluster")
        if claim is None:
            weights = [max(cluster.share_of_failures for cluster in clusters) for _, clusters, _ in funded]
        else:
            weights = [max(claim(cluster) for cluster in clusters) for _, clusters, _ in funded]
        cap = max(min_per_cluster, int(tail * max_share)) if len(funded) > 1 else tail
        return funded, _allocate(weights, tail, min_per_cluster, cap), weights, unfunded

    tail_budget = budget
    if reference is not None:
        tail_budget = _tail_budget(reference, base, budget, fund, representative_share, max_mix_tvd, min_per_cluster)
    candidates, counts, weights, unfunded = fund(tail_budget)
    unmapped.extend(unfunded)
    # The targets report the failure share whatever weighted the rows, so a
    # reader can see how far value moved the allocation.
    shares = ([max(cluster.share_of_failures for cluster in clusters) for _, clusters, _ in candidates]
              if claim is not None else weights)
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
    if reference is not None:
        for name, where, count, stratum in _representative(reference, base, budget - sum(counts), round, used, unmapped):
            strata.append({"id": name, "count": count, "source": _source_for(stratum, where)})
            targets.append(CurriculumTarget(stratum=name, keys=(REPRESENTATIVE_KEY,), where=where, count=count,
                                            share_of_failures=0.0, base_stratum=stratum.id))
            counts.append(count)

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
    dumped = plan.model_dump(mode="json")
    mix = check_mix(dumped, reference, max_mix_tvd) if reference is not None else None
    return Curriculum(round=round, seed=chosen_seed, base_seed=base.seed, plan=dumped,
                      targets=tuple(targets), unmappable=tuple(unmapped), mix=mix)


def round_half_up(value: float) -> int:
    return int(value + 0.5)


def _value_claim(report: Autopsy, values: Mapping[str, Any]) -> Callable[[Cluster], float]:
    """Failure share times relative value, per cluster, over the failing cases the clusters name.

    Relative value is the cluster's mean case weight over the failing
    cases' mean weight, so the claim is the cluster's share of the failing
    value, and uniform values reproduce the unweighted allocation exactly
    (a product of two shares would square every cluster's count instead).
    """

    def weight_of(case_id: str) -> float:
        value = values.get(case_id)
        return 1.0 if value is None else float(getattr(value, "weight", value))

    failing = sorted({case_id for cluster in report.clusters for case_id in cluster.case_ids})
    mean = (sum(weight_of(case_id) for case_id in failing) / len(failing)) if failing else 1.0

    def claim(cluster: Cluster) -> float:
        if not cluster.case_ids or not mean:
            return cluster.share_of_failures
        relative = sum(weight_of(case_id) for case_id in cluster.case_ids) / len(cluster.case_ids) / mean
        return round(cluster.share_of_failures * relative, 6)

    return claim


def _pinned(stratum: Any, where: Mapping[str, str], dimension: str) -> str | None:
    value = where.get(dimension) or stratum.source.where.get(dimension)
    return str(value) if value else None


def _tail_budget(reference: ReferenceMix, base: Any, budget: int, fund: Callable[[int], Any],
                 share: float | None, max_tvd: float | None, floor: int) -> int:
    """Rows left for failure targets once the representative share, and the mix limit, are kept.

    The tail's own distance from the reference is predicted from the
    values its strata pin (a stratum that pins none follows the
    reference); with the representative rows matching the reference, the
    plan's distance is the tail's fraction times the tail's distance, so the
    tail is shrunk until that product is within the limit.
    """

    from .. import packkit

    kept = float(packkit.policy("evalrun.curriculum.representative_share")) if share is None else float(share)
    limit = float(packkit.policy("evalrun.curriculum.max_mix_tvd")) if max_tvd is None else float(max_tvd)
    if not 0.0 <= kept < 1.0:
        raise ValueError("representative_share must be in [0, 1)")
    if limit < 0.0:
        raise ValueError("max_mix_tvd must be non-negative")
    tail = budget - round_half_up(budget * kept)
    candidates, counts, _, _ = fund(max(tail, floor))
    ref = reference.shares
    mass: dict[str, float] = defaultdict(float)
    for (filters, _, stratum), count in zip(candidates, counts, strict=True):
        pinned = _pinned(stratum, dict(filters), reference.dimension)
        if pinned is not None:
            mass[pinned] += count
        else:
            for key, value in ref.items():
                mass[key] += count * value
    whole = sum(mass.values()) or 1.0
    distance = total_variation({key: value / whole for key, value in mass.items()}, ref)
    if distance > 0 and (tail / budget) * distance > limit:
        tail = int(budget * limit / distance)
    if tail < floor:
        raise ValueError(f"the reference mix leaves {tail} row(s) for failure targets, under the floor of {floor};"
                         " raise --total or lower the representative share")
    return tail


def _representative(reference: ReferenceMix, base: Any, rows: int, round_number: int, used: set[str],
                    unmapped: list[Unmapped]) -> list[tuple[str, dict[str, str], int, Any]]:
    """Strata that draw ``rows`` rows in the reference's proportions.

    When the reference dimension is a dataset predicate, one stratum per
    reference value a base stratum admits, sized by largest remainders.
    Otherwise (a catalogue activity is not a dataset predicate) the rows are
    spread over the base strata by their counts, with no added predicate:
    the base plan's own draw is the company's simulated mix.
    """

    if rows <= 0:
        return []
    chosen: list[tuple[str, dict[str, str], float, Any]] = []
    if reference.dimension in MAPPABLE_DIMENSIONS:
        for value, share in reference.shares.items():
            where = {reference.dimension: value}
            stratum, why = _choose_stratum(base, where)
            if stratum is None or share <= 0:
                unmapped.append(Unmapped(key=f"mix:{reference.dimension}={value}", cases=0, reason=str(why)))
                continue
            chosen.append((value, where, share, stratum))
    if not chosen:
        chosen = [(stratum.id, {}, float(stratum.count), stratum) for stratum in base.strata if stratum.count > 0]
    counts = _allocate([item[2] for item in chosen], rows, 0, rows)
    out: list[tuple[str, dict[str, str], int, Any]] = []
    for (label, where, _, stratum), count in zip(chosen, counts, strict=True):
        if count <= 0:
            continue
        name = f"r{round_number}-mix-{_slug(label)}"
        suffix = 2
        while name in used:
            name = f"r{round_number}-mix-{_slug(label)}-{suffix}"
            suffix += 1
        used.add(name)
        out.append((name, where, count, stratum))
    return out


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
    values: Mapping[str, Any] | None = None,
    reference: ReferenceMix | None = None,
) -> Any:
    """The ``DatasetPlan`` of ``design_curriculum``; use that to see what was unmappable."""

    return design_curriculum(report, base, seed=seed, round=round, total=total, min_per_cluster=min_per_cluster,
                             max_share=max_share, holdout_share=holdout_share, values=values,
                             reference=reference).dataset_plan()


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
