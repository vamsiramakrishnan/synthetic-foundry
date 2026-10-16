"""Qualified native benchmark improvement through the established evalrun loop.

The adapter owns composition, not another optimizer. Byte-qualified cases,
fresh held-out evidence tranches, policy revisions and resumable receipts retain
the same contracts as ``evalrun.improve``.
"""
from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

from ..evalrun.agents import AgentResponse, AgentTask, ToolSurface
from ..evalrun.improve import AgentFor, ImproveReport, improve
from ..evalrun.policy import AgentPolicy, agent_name, pack_record, require
from ..evalrun.qualification import (
    QualificationPolicy,
    audit_splits,
    evidence_components,
    qualification_tranches,
)
from ..native_eval_bridge import (
    NativeGrader,
    native_runner,
    native_source_digest,
    native_task_cases,
)
from ..packkit.authoring import Exchange
from ..providers import digest
from .requirements import (
    BenchmarkRequirements,
    measure_requirements,
    requirement_deficits,
    resolve_requirements,
    task_formats,
)

if TYPE_CHECKING:
    from ..native_corpus import NativeCorpusResult
    from ..packkit import ResolvedPack
    from ..world import World
    from .core import NativeBenchmark
    from .runner import NativeHarness


class NativePolicyAgent:
    """Resolved policy supplied to a native target on every measured revision.

    Callable and command transports serialize ``policy`` in the public request;
    it contains neither private native assertions nor held-out evidence.
    """

    def __init__(self, pack: ResolvedPack) -> None:
        self.pack = require(pack)
        self.name = agent_name("native-benchmark", self.pack)

    @property
    def policy(self) -> AgentPolicy:
        return cast(AgentPolicy, self.pack.body)

    @property
    def pack_record(self) -> dict[str, Any]:
        return pack_record(self.pack)

    def fingerprint(self) -> dict[str, Any]:
        return {"kind": "native-policy", "policy": self.pack_record}

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        raise TypeError("native policies execute through the benchmark harness byte-submission transport")


def _sources(training: NativeBenchmark, heldout: NativeBenchmark) -> tuple[
    dict[str, NativeCorpusResult], dict[str, World],
]:
    """Keep one identity per served artifact across both verified benchmarks."""
    merged: dict[str, NativeCorpusResult] = {}
    worlds: dict[str, World] = {}
    source_digests: dict[str, str] = {}
    for benchmark in (training, heldout):
        benchmark.validate()
        source_digest = native_source_digest(benchmark.world)
        selected = {item.artifact_id for task in benchmark.workload.tasks for item in task.inputs}
        for artifact_id in sorted(selected):
            result = benchmark.rendered[artifact_id]
            previous = merged.get(artifact_id)
            if previous is not None and (previous.payload != result.payload or previous.manifest != result.manifest):
                raise ValueError("benchmark improvement sources have conflicting artifact identities: " + artifact_id)
            if artifact_id in source_digests and source_digests[artifact_id] != source_digest:
                raise ValueError("benchmark improvement sources have conflicting canonical source graphs: " + artifact_id)
            merged[artifact_id] = result
            worlds[artifact_id] = benchmark.world
            source_digests[artifact_id] = source_digest
    if training.world.company.id != heldout.world.company.id:
        raise ValueError("benchmark improvement requires one company origin under a shared source namespace")
    return merged, worlds


def _require_coverage(benchmark: NativeBenchmark, split: str) -> None:
    """Qualify the declared work, never silently narrow it to surviving tasks."""
    workload = benchmark.workload
    operations = {task.operation for task in workload.tasks}
    formats = {format for task in workload.tasks for format in task_formats(task)}
    for dimension, requested, delivered in (("operations", workload.plan.operations, operations),
            ("formats", workload.plan.formats, formats)):
        missing = sorted(set(requested) - delivered)
        if missing:
            raise ValueError(f"{split} benchmark does not cover requested {dimension}: {', '.join(missing)}")


def improve_benchmark(
    champion: ResolvedPack,
    training: NativeBenchmark,
    heldout: NativeBenchmark,
    *,
    namespace: str,
    harness: NativeHarness,
    proposer: Exchange,
    out: Path,
    qualification_policy: QualificationPolicy | None = None,
    requirements: BenchmarkRequirements | None = None,
    agent_for: AgentFor | None = None,
    rounds: int = 1,
    repeats: int = 2,
    ablate: bool = True,
    candidates: int = 1,
    screen_cases: int = 6,
    finalists: int = 1,
    round_budget: int | None = None,
    pack_roots: Sequence[str | Path] = (),
    authoring_rounds: int | None = None,
    min_train_delta: float | None = None,
    min_holdout_delta: float | None = None,
    max_axis_regression: float | None = None,
) -> ImproveReport:
    """Revise an agent policy against a sealed pool of native byte tasks.

    ``namespace`` identifies the company origin, shared across snapshots and
    format replicas; it must never identify the split. ``heldout`` must contain
    enough independent evidence components for every predeclared trial. Repeated
    questions, source copies and multiple formats do not create independent
    units. ``qualification_policy=None`` selects the strict default policy; it
    never disables qualification. Invalid provenance, split overlap and an
    undersized pool are refused before the target or proposer runs.

    The default ``NativePolicyAgent`` delivers the candidate's resolved policy
    to ``harness``. Supply ``agent_for`` only when adapting an existing agent
    implementation; its fingerprint must identify the actual measured policy.
    ``out`` holds the existing evalrun receipts and finite qualification budget.
    An interrupted study can resume only with its unchanged source, grader,
    harness and experiment identity. Native files observe the outcomes axis;
    this adapter does not manufacture plan or trajectory scores.
    """
    require(champion)
    if not namespace.strip():
        raise ValueError("benchmark improvement requires a stable company source namespace")
    if not harness.identity:
        raise ValueError("benchmark improvement requires an explicit harness identity")
    if training.split_role == "heldout" or heldout.split_role == "training":
        raise ValueError("benchmark split roles prohibit using held-out evidence as training or training evidence as held-out")
    rendered, worlds = _sources(training, heldout)
    _require_coverage(training, "training")
    _require_coverage(heldout, "held-out")
    train = native_task_cases(training.workload.tasks, rendered, namespace=namespace, world=training.world)
    held = native_task_cases(heldout.workload.tasks, rendered, namespace=namespace, world=heldout.world)
    policy = QualificationPolicy() if qualification_policy is None else qualification_policy
    if {case.id for case in train} & {case.id for case in held}:
        raise ValueError("native cases cannot be both training and held out")
    if not audit_splits(train, held, unit_dimension=policy.unit_dimension).isolated:
        raise ValueError("training and held-out cases share protected evidence or an independent unit")
    declared = resolve_requirements(training.workload.plan, heldout.workload.plan, additional=requirements)
    deficits = requirement_deficits(measure_requirements(train, declared, unit_dimension=policy.unit_dimension))
    if deficits:
        raise ValueError("training benchmark required coverage is insufficient: " + "; ".join(deficits))
    units = evidence_components(held, unit_dimension=policy.unit_dimension)
    # Assess exactly the cohorts QualificationVault will seal, before a target,
    # proposer or agent factory can observe any data or spend a held-out probe.
    tranches = qualification_tranches(held, policy=policy)
    deficits = requirement_deficits(measure_requirements(held, declared, components=units,
        min_units=policy.min_units, multiplier=policy.trials))
    if deficits:
        raise ValueError("held-out benchmark required coverage is insufficient: " + "; ".join(deficits))
    by_id = {case.id: case for case in held}
    for index, tranche in enumerate(tranches, start=1):
        deficits = requirement_deficits(measure_requirements(tuple(by_id[case_id] for case_id in tranche),
            declared, components=units, min_units=policy.min_units))
        if deficits:
            raise ValueError(f"held-out fresh tranche {index} required coverage is insufficient: " + "; ".join(deficits))
    runner = native_runner(rendered, harness, namespace=namespace,
        submit_identity={"harness": dict(harness.identity), "requirements": digest(declared.model_dump(mode="json"))}, world=worlds)
    return improve(champion, train, holdout=held, run=runner,
        agent_for=NativePolicyAgent if agent_for is None else agent_for,
        exchange=proposer, out=out, rater=NativeGrader(),
        qualification=policy,
        rounds=rounds, repeats=repeats, ablate=ablate, candidates=candidates,
        screen_cases=screen_cases, finalists=finalists, round_budget=round_budget,
        pack_roots=pack_roots, authoring_rounds=authoring_rounds,
        min_train_delta=min_train_delta, min_holdout_delta=min_holdout_delta,
        max_axis_regression=max_axis_regression)


__all__ = ["NativePolicyAgent", "improve_benchmark"]
