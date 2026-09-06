"""Quality-diversity search over mechanisms, with a sealed evaluator.

Only explicitly mutable parameter values evolve. Expressions, constraints,
measurement definitions, seeds and validation limits are outside the mutation
surface. Archive cells describe observed behavior, not document formatting.
Holdout seeds are evaluated after search and never influence parent selection.
"""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Iterable
from typing import Literal

from pydantic import Field, StrictInt

from ..models import Model
from ..rng import Rng
from .compiler import digest
from .engine import Simulator
from .models import Limits, Parameter, Program, SynthesisError


class Metric(Model):
    name: str
    table: str
    column: str
    aggregation: Literal["sum", "mean", "nonzero_ppm", "max", "min"] = "sum"


class Reading(Model):
    metric: str
    value: StrictInt


class Axis(Model):
    metric: str
    # E.g. (10_000, 100_000, 500_000) partitions a nonzero_ppm metric into
    # four cells. Underflow and overflow remain observable, not clipped away.
    boundaries: tuple[StrictInt, ...]


class Target(Model):
    metric: str
    minimum: StrictInt
    maximum: StrictInt
    weight: int = Field(default=1, ge=1, strict=True)


class SearchPlan(Model):
    proposals: int = Field(default=32, ge=1, le=1024, strict=True)
    seed: StrictInt = 42
    training_seeds: tuple[StrictInt, ...] = (101, 202)
    holdout_seeds: tuple[StrictInt, ...] = (303, 404)
    metrics: tuple[Metric, ...]
    axes: tuple[Axis, ...]
    targets: tuple[Target, ...] = ()
    gates: tuple[Target, ...] = ()


class SeedReading(Model):
    seed: StrictInt
    readings: tuple[Reading, ...]


class Evaluation(Model):
    accepted: bool
    quality: StrictInt = 0
    niche: tuple[StrictInt, ...] = ()
    seeds: tuple[SeedReading, ...] = ()
    findings: tuple[str, ...] = ()


class Candidate(Model):
    id: str
    ordinal: StrictInt
    parents: tuple[str, ...]
    parameters: tuple[Parameter, ...]
    status: Literal["admitted", "dominated", "rejected", "duplicate"]
    displaced: str | None = None
    evaluation: Evaluation | None = None


class Champion(Model):
    candidate: Candidate
    holdout: Evaluation


class SearchReport(Model):
    schema_version: Literal["worldloom.synthesis.search/v1"] = "worldloom.synthesis.search/v1"
    evaluator_digest: str
    base_program: Program
    plan: SearchPlan
    candidates: tuple[Candidate, ...]
    champions: tuple[Champion, ...]
    evaluated: StrictInt


def measure(simulator: Simulator, metrics: tuple[Metric, ...]) -> tuple[Reading, ...]:
    """Streaming measurements. A requested but absent signal is an error."""
    if not metrics or len(metrics) > 64 or len({m.name for m in metrics}) != len(metrics):
        raise SynthesisError("metric_contract", "one to 64 uniquely named metrics required")
    tables = {t.name: t for t in simulator.program.tables}
    for metric in metrics:
        table = tables.get(metric.table)
        column = next((c for c in table.columns if c.name == metric.column), None) if table else None
        if column is None or column.kind not in {"int", "bool"}:
            raise SynthesisError("metric_contract", f"numeric column missing for {metric.name}")
    grouped: dict[str, list[Metric]] = {}
    for metric in metrics:
        grouped.setdefault(metric.table, []).append(metric)
    # count, sum, nonzero, minimum, maximum; no array proportional to rows.
    accumulators: dict[str, list[int]] = {m.name: [0, 0, 0, 0, 0] for m in metrics}
    for row in simulator.rows():
        values = row.values()
        for metric in grouped.get(row.table, ()):
            value = int(values[metric.column])
            state = accumulators[metric.name]
            state[3] = min(state[3], value) if state[0] else value
            state[4] = max(state[4], value) if state[0] else value
            state[0] += 1
            state[1] += value
            state[2] += int(value != 0)
    readings: list[Reading] = []
    for metric in sorted(metrics, key=lambda m: m.name):
        count, total, nonzero, minimum, maximum = accumulators[metric.name]
        if count == 0:
            raise SynthesisError("empty_metric", metric.name)
        value = {"sum": total, "mean": total // count,
                 "nonzero_ppm": nonzero * 1_000_000 // count,
                 "min": minimum, "max": maximum}[metric.aggregation]
        readings.append(Reading(metric=metric.name, value=value))
    return tuple(readings)


def with_parameters(program: Program, values: dict[str, int]) -> Program:
    known = {p.name: p for p in program.parameters}
    if set(values) - set(known):
        raise SynthesisError("unknown_parameter", str(sorted(set(values) - set(known))))
    parameters = []
    for parameter in program.parameters:
        value = values.get(parameter.name, parameter.value)
        if type(value) is not int or not parameter.minimum <= value <= parameter.maximum:
            raise SynthesisError("parameter_bounds", parameter.name)
        if value != parameter.value and not parameter.mutable:
            raise SynthesisError("protected_parameter", parameter.name)
        parameters.append(parameter.model_copy(update={"value": value}))
    return program.model_copy(update={"parameters": tuple(parameters)})


def _validate_plan(plan: SearchPlan) -> None:
    if not plan.training_seeds or not plan.holdout_seeds:
        raise SynthesisError("seed_partition", "training and holdout seeds are both required")
    all_seeds = plan.training_seeds + plan.holdout_seeds
    if len(set(all_seeds)) != len(all_seeds) or len(all_seeds) > 32:
        raise SynthesisError("seed_partition", "seeds must be distinct, disjoint and bounded")
    names = {m.name for m in plan.metrics}
    if not plan.metrics or len(plan.metrics) > 64 or len(names) != len(plan.metrics):
        raise SynthesisError("metric_contract", "one to 64 uniquely named metrics required")
    if not plan.axes or len(plan.axes) > 8 or len({a.metric for a in plan.axes}) != len(plan.axes):
        raise SynthesisError("axis_contract", "one to eight distinct behavior axes required")
    for axis in plan.axes:
        if axis.metric not in names or not axis.boundaries or len(axis.boundaries) > 64:
            raise SynthesisError("axis_contract", axis.metric)
        if tuple(sorted(set(axis.boundaries))) != axis.boundaries:
            raise SynthesisError("axis_contract", "boundaries must be strictly increasing")
    for target in plan.targets + plan.gates:
        if target.metric not in names or target.minimum > target.maximum:
            raise SynthesisError("target_contract", target.metric)


def _distance(value: int, target: Target) -> int:
    return max(target.minimum - value, 0, value - target.maximum) * target.weight


def evaluate(program: Program, plan: SearchPlan, seeds: Iterable[int], *,
             limits: Limits | None = None) -> Evaluation:
    _validate_plan(plan)
    results: list[SeedReading] = []
    findings: list[str] = []
    quality = 0
    for seed in seeds:
        try:
            readings = measure(Simulator(program, seed=seed, limits=limits), plan.metrics)
        except SynthesisError as error:
            findings.append(f"seed={seed}:{error.finding.code}:{error.finding.message}")
            continue
        results.append(SeedReading(seed=seed, readings=readings))
        by_name = {r.metric: r.value for r in readings}
        quality -= sum(_distance(by_name[t.metric], t) for t in plan.targets)
        for gate in plan.gates:
            if _distance(by_name[gate.metric], gate):
                findings.append(f"seed={seed}:gate:{gate.metric}={by_name[gate.metric]}")
    if not results or findings:
        return Evaluation(accepted=False, seeds=tuple(results), findings=tuple(findings or ["no_seed_readings"]))
    means = {m.name: sum(next(r.value for r in s.readings if r.metric == m.name) for s in results) // len(results)
             for m in plan.metrics}
    niche = tuple(bisect_right(a.boundaries, means[a.metric]) for a in plan.axes)
    return Evaluation(accepted=True, quality=quality, niche=niche, seeds=tuple(results))


def check_search_budget(program: Program, plan: SearchPlan, limits: Limits | None = None) -> None:
    _validate_plan(plan)
    compiled = Simulator(program, limits=limits).compiled
    for metric in plan.metrics:
        table = next((t for t in program.tables if t.name == metric.table), None)
        column = next((c for c in table.columns if c.name == metric.column), None) if table else None
        if column is None or column.kind not in {"int", "bool"}:
            raise SynthesisError("metric_contract", metric.name)
    runs = plan.proposals * (len(plan.training_seeds) + len(plan.holdout_seeds)) + len(plan.training_seeds)
    if compiled.work * runs > compiled.limits.max_evaluation_work:
        raise SynthesisError("evaluation_budget", "total planned evaluation work exceeds the operator limit")


def search(program: Program, plan: SearchPlan, *, limits: Limits | None = None) -> SearchReport:
    _validate_plan(plan)
    check_search_budget(program, plan, limits)  # graph errors are not search failures
    mutable = sorted((p for p in program.parameters if p.mutable and p.minimum < p.maximum), key=lambda p: p.name)
    if not mutable:
        raise SynthesisError("mutation_surface", "no bounded mutable parameter")
    archive: dict[tuple[int, ...], Candidate] = {}
    records: list[Candidate] = []
    seen: set[str] = set()
    root = Rng(plan.seed)
    baseline_values = {p.name: p.value for p in program.parameters}
    for ordinal in range(plan.proposals):
        parents: tuple[str, ...] = ()
        values = dict(baseline_values)
        if ordinal:
            rng = root.derive(f"proposal/{ordinal}")
            pool = sorted(archive.values(), key=lambda c: c.id)
            if pool:
                parent = rng.choice(pool)
                parents = (parent.id,)
                values = {p.name: p.value for p in parent.parameters}
                if ordinal % 3 == 0 and len(pool) > 1:
                    donor = rng.choice([c for c in pool if c.id != parent.id])
                    donor_values = {p.name: p.value for p in donor.parameters}
                    parents += (donor.id,)
                    for parameter in mutable:
                        if rng.derive(parameter.name).integer(0, 1):
                            values[parameter.name] = donor_values[parameter.name]
            parameter = mutable[(ordinal - 1) % len(mutable)]
            values[parameter.name] = rng.integer(parameter.minimum, parameter.maximum)
        proposed = with_parameters(program, values)
        key = digest(proposed.model_dump(mode="json"))
        if key in seen:
            records.append(Candidate(id=key, ordinal=ordinal, parents=parents,
                                     parameters=proposed.parameters, status="duplicate"))
            continue
        seen.add(key)
        evaluation = evaluate(proposed, plan, plan.training_seeds, limits=limits)
        incumbent = archive.get(evaluation.niche) if evaluation.accepted else None
        status: Literal["admitted", "dominated", "rejected", "duplicate"]
        if not evaluation.accepted:
            status = "rejected"
        elif incumbent is None:
            status = "admitted"
        else:
            assert incumbent.evaluation is not None
            status = "admitted" if (-evaluation.quality, key) < (-incumbent.evaluation.quality, incumbent.id) else "dominated"
        candidate = Candidate(id=key, ordinal=ordinal, parents=parents,
                              parameters=proposed.parameters, status=status,
                              displaced=incumbent.id if status == "admitted" and incumbent else None,
                              evaluation=evaluation)
        records.append(candidate)
        if status == "admitted":
            archive[evaluation.niche] = candidate
    champions = []
    for _, candidate in sorted(archive.items()):
        proposed = with_parameters(program, {p.name: p.value for p in candidate.parameters})
        holdout = evaluate(proposed, plan, plan.holdout_seeds, limits=limits)
        champions.append(Champion(candidate=candidate, holdout=holdout))
    return SearchReport(
        evaluator_digest=digest({"plan": plan.model_dump(mode="json"),
                                 "limits": (limits or Limits()).model_dump(mode="json")}),
        base_program=program, plan=plan, candidates=tuple(records),
        champions=tuple(champions), evaluated=len(seen),
    )


def retail_search_plan(*, proposals: int = 32) -> SearchPlan:
    return SearchPlan(proposals=proposals, metrics=(
        Metric(name="stockout_ppm", table="inventory", column="lost", aggregation="nonzero_ppm"),
        Metric(name="mean_stock", table="inventory", column="closing", aggregation="mean"),
        Metric(name="revenue", table="inventory", column="revenue"),
    ), axes=(Axis(metric="stockout_ppm", boundaries=(1, 50_000, 200_000, 500_000)),
             Axis(metric="mean_stock", boundaries=(10, 40, 80))),
        targets=(Target(metric="stockout_ppm", minimum=50_000, maximum=250_000),))


def banking_search_plan(*, proposals: int = 32) -> SearchPlan:
    return SearchPlan(proposals=proposals, metrics=(
        Metric(name="arrears_ppm", table="loan", column="arrears", aggregation="nonzero_ppm"),
        Metric(name="mean_missed", table="loan", column="missed_periods", aggregation="mean"),
        Metric(name="cash_received", table="loan", column="paid"),
    ), axes=(Axis(metric="arrears_ppm", boundaries=(1, 250_000, 500_000, 750_000)),
             Axis(metric="mean_missed", boundaries=(1, 3, 6))),
        targets=(Target(metric="arrears_ppm", minimum=100_000, maximum=600_000),))
