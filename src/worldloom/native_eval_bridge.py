"""Native byte outcomes on the existing sealed harness-improvement seam.

Cases retain the evaluator's complete private task contract. Targets receive
only public requests and input bytes. Whole input artifacts and canonical
evidence own independence; neither more assertions nor format copies buy units.
Plan and trajectory remain unobserved because a native reply is not a trace.
"""
from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

from .evalrun.agents import AgentUnderTest, fingerprint
from .evalrun.contract import (
    EvalCase,
    OutcomeContract,
    PlanContract,
    TrajectoryContract,
    UnstructuredOutcome,
)
from .evalrun.grader import grader_identity
from .evalrun.grading import (
    CaseScore,
    unobserved_outcomes,
    unobserved_plan,
    unobserved_trajectory,
)
from .evalrun.runner import CaseResult, RunReport, case_set_digest
from .native_artifacts import inspect_artifact
from .native_corpus import NativeCorpusResult
from .native_query_evidence import SourceEvidenceIndex
from .native_reference import qualify_native_task
from .native_tasks import (
    NativeGrade,
    NativeInput,
    NativeSubmission,
    NativeTask,
    grade_native_task,
    public_contract,
)
from .providers import digest

if TYPE_CHECKING:
    from .world import World

_SCHEMA = "worldloom.native-eval-case/v1"
NativeSubmit = Callable[[AgentUnderTest, dict[str, Any], Mapping[str, bytes]], NativeSubmission]


def native_grader_identity() -> dict[str, Any]:
    """Pin byte grading, accepted source semantics and parser dependencies."""
    from . import (
        formula_semantics,
        native_artifacts,
        native_business,
        native_corpus,
        native_query_evidence,
        native_query_planning,
        native_reference,
        native_tasks,
    )

    sources = {}
    for module in (formula_semantics, native_artifacts, native_business, native_corpus, native_query_evidence,
                   native_query_planning, native_reference, native_tasks):
        if module.__file__ is None:
            raise ValueError("native grader software source cannot be pinned")
        sources[module.__name__] = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
    sources[__name__] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    dependencies = {}
    for name in ("python-docx", "python-pptx", "openpyxl", "pydantic", "networkx"):
        try:
            dependencies[name] = version(name)
        except PackageNotFoundError:
            dependencies[name] = "absent"
    parts = {"schema": "worldloom.native-grader/v1", "sources": sources, "dependencies": dependencies}
    return {**parts, "digest": digest(parts)}


@dataclass(frozen=True)
class NativeGrader:
    """Identity marker for ``improve(rater=NativeGrader())``; no model judge."""

    kind: str = "native"

    @property
    def name(self) -> str:
        return "native/" + str(native_grader_identity()["digest"])

    def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
        raise TypeError("NativeGrader is an identity marker; native outcomes require actual submitted bytes")


def _snapshot(inputs: Sequence[NativeInput]) -> str:
    return digest(["native-input-snapshot/v1", sorted((item.artifact_id, item.format, item.sha256) for item in inputs)])


def _bytes(tasks: Sequence[NativeTask], inputs: Mapping[str, bytes]) -> dict[str, bytes]:
    identities: dict[str, tuple[str, str]] = {}
    used: dict[str, bytes] = {}
    for task in tasks:
        for item in task.inputs:
            identity = item.format, item.sha256
            if item.artifact_id in identities and identities[item.artifact_id] != identity:
                raise ValueError("native improvement sources have contradictory byte identities")
            if item.artifact_id not in inputs:
                raise ValueError(f"native improvement source is missing: {item.artifact_id}")
            if item.artifact_id not in used:
                payload = inputs[item.artifact_id]
                if inspect_artifact(payload, item.format).sha256 != item.sha256:
                    raise ValueError(f"native improvement source bytes changed: {item.artifact_id}")
                used[item.artifact_id] = payload
                identities[item.artifact_id] = identity
    return used


def _source_digest(source: SourceEvidenceIndex) -> str:
    return digest({"schema": "worldloom.native-canonical-source/v1",
        "facts": [source.facts[key].model_dump(mode="json") for key in sorted(source.facts)],
        "artifacts": [source.artifacts[key].model_dump(mode="json") for key in sorted(source.artifacts)]})


def native_source_digest(world: World) -> str:
    """Pin evaluator-owned canonical facts and authored IR, not caller claims."""
    return _source_digest(SourceEvidenceIndex(world))


def _canonical_sources(worlds: Mapping[str, World]) -> dict[str, tuple[SourceEvidenceIndex, str]]:
    snapshots: list[tuple[World, SourceEvidenceIndex, str]] = []
    result = {}
    for artifact_id, world in sorted(worlds.items()):
        cached = next(((source, pin) for prior, source, pin in snapshots if prior is world), None)
        if cached is None:
            source = SourceEvidenceIndex(world)
            pin = _source_digest(source)
            snapshots.append((world, source, pin))
        else:
            source, pin = cached
        result[artifact_id] = source, pin
    return result


def _lineage(task: NativeTask, rendered: Mapping[str, NativeCorpusResult],
             canonical: Mapping[str, tuple[SourceEvidenceIndex, str]]) -> list[dict[str, Any]]:
    sources = []
    for item in sorted(task.inputs, key=lambda value: value.artifact_id):
        if item.artifact_id not in rendered:
            raise ValueError("native improvement provenance source is missing: " + item.artifact_id)
        manifest = rendered[item.artifact_id].manifest
        if (manifest.artifact_id, manifest.format, manifest.sha256) != (item.artifact_id, item.format, item.sha256):
            raise ValueError("native improvement manifest disagrees with its byte-bound input")
        source, source_digest = canonical[item.artifact_id]
        direct = sorted({fid for entry in manifest.evidence for fid in entry.fact_ids})
        artifacts = [source.artifacts[key] for key in sorted({entry.source_artifact_id for entry in manifest.evidence})]
        coverage_dimensions = {}
        for dimension, metadata_key in (("scenario_process", "native_scenario_process"),
                ("scenario_template", "native_scenario_template")):
            values = {artifact.metadata.get(metadata_key, "") for artifact in artifacts}
            if len(values) == 1 and "" not in values:
                coverage_dimensions[dimension] = next(iter(values))
        sources.append({"artifact_id": item.artifact_id, "format": item.format, "sha256": item.sha256,
            "manifest_digest": digest(manifest.model_dump(mode="json")),
            "canonical_source_digest": source_digest, "direct_fact_ids": direct,
            "coverage_dimensions": coverage_dimensions,
            "fact_ids": list(source.fact_closure(direct)),
            "evidence_ids": sorted({"native-artifact:" + item.artifact_id, "native-bytes:" + manifest.sha256,
                *(f"native-section:{entry.source_artifact_id}:{entry.section_index}" for entry in manifest.evidence)})})
    return sources


def _case_lineage(lineage: Sequence[Mapping[str, Any]]) -> tuple[list[str], list[str]]:
    if any(not isinstance(source, Mapping) or any(
            not isinstance(source.get(key), list) or any(not isinstance(value, str) or not value for value in source[key])
            for key in ("fact_ids", "evidence_ids")) for source in lineage):
        raise ValueError("native improvement source lineage has invalid evidence tokens")
    if any(not isinstance(source.get("coverage_dimensions"), dict) or any(
            key not in {"scenario_process", "scenario_template"} or not isinstance(value, str) or not value
            for key, value in source["coverage_dimensions"].items()) for source in lineage):
        raise ValueError("native improvement source lineage has invalid coverage dimensions")
    return (sorted({fid for source in lineage for fid in source["fact_ids"]}),
            sorted({eid for source in lineage for eid in source["evidence_ids"]}))


def _dimensions(task: NativeTask, namespace: str, software: Mapping[str, Any],
                lineage: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    result = {"source_namespace": namespace, "source_digest": _snapshot(task.inputs),
        "native_grader_digest": str(software["digest"]), "native_operation": task.operation,
        "use_case_id": task.use_case_id, "native_formats": ",".join(sorted({item.format for item in task.inputs}))}
    # Only unanimous canonical metadata identifies measured scenario cells.
    # Task labels and case-unique IDs cannot invent process support.
    for dimension in ("scenario_process", "scenario_template"):
        values = {str(source.get("coverage_dimensions", {}).get(dimension, "")) for source in lineage}
        if len(values) == 1 and "" not in values:
            result[dimension] = next(iter(values))
    return result


def native_task_cases(
    tasks: Sequence[NativeTask], rendered: Mapping[str, NativeCorpusResult], *, namespace: str, world: World,
) -> tuple[EvalCase, ...]:
    """Compile private improvement cases from accepted native provenance.

    ``namespace`` is the stable source-world origin, shared by snapshots and
    format replicas, never a split name or byte hash. The canonical ``world``
    independently validates authored lineage as well as file bytes.
    """
    if not namespace.strip() or not tasks or len({task.id for task in tasks}) != len(tasks):
        raise ValueError("native improvement needs a stable origin and distinct, nonempty tasks")
    if any(not task.inputs or any(item.format not in ("docx", "pptx", "xlsx") for item in task.inputs) for task in tasks):
        raise ValueError("native improvement lineage requires grounded DOCX, PPTX or XLSX inputs")
    selected = {item.artifact_id: rendered[item.artifact_id] for task in tasks for item in task.inputs}
    from .native_artifacts import _SourceInspection
    from .native_query_planning import NativeWorkloadPlan, _inventory

    inspection = _SourceInspection()
    _inventory(world, selected, NativeWorkloadPlan(use_case_id="native-bridge", objective="Validate source provenance."),
        _inspection=inspection)
    inputs = _bytes(tasks, {key: result.payload for key, result in selected.items()})
    source = SourceEvidenceIndex(world)
    source_digest = _source_digest(source)
    canonical = {key: (source, source_digest) for key in selected}
    software = native_grader_identity()
    cases = []
    for task in sorted(tasks, key=lambda item: item.id):
        lineage = _lineage(task, selected, canonical)
        facts, evidence = _case_lineage(lineage)
        proof = qualify_native_task(task, inputs, _inspection=inspection)
        if not proof.passed:
            raise ValueError("native improvement task is not reference-qualified: " + task.id)
        cases.append(EvalCase(id=task.id, query=task.prompt,
            dimensions=_dimensions(task, namespace, software, lineage),
            plan=PlanContract(nodes=(), edges=(), shape="native." + task.operation), trajectory=TrajectoryContract(),
            outcomes=OutcomeContract(unstructured=UnstructuredOutcome(
                format=task.output.format if task.output is not None else None, required_fact_ids=tuple(facts)),
                no_write=task.operation in ("read", "analyze")),
            row={"schema": _SCHEMA, "id": task.id, "native_task": task.model_dump(mode="json"),
                "native_grader": software, "native_lineage": lineage,
                "expected_fact_ids": facts, "expected_evidence_ids": evidence}))
    return tuple(cases)


def _tasks(cases: Sequence[EvalCase]) -> tuple[NativeTask, ...]:
    if not cases or len({case.id for case in cases}) != len(cases):
        raise ValueError("native improvement run requires distinct, nonempty cases")
    software = native_grader_identity()
    tasks = []
    for case in cases:
        if case.row.get("schema") != _SCHEMA or case.row.get("native_grader") != software:
            raise ValueError("native improvement contract or native grader identity changed")
        task = NativeTask.model_validate(case.row.get("native_task"))
        if task.id != case.id or task.prompt != case.query or case.dimensions.get("source_digest") != _snapshot(task.inputs):
            raise ValueError("native improvement case differs from its private native contract")
        lineage = case.row.get("native_lineage")
        if not isinstance(lineage, list) or len(lineage) != len(task.inputs):
            raise ValueError("native improvement source lineage is missing")
        facts, evidence = _case_lineage(lineage)
        expected_inputs = sorted((item.artifact_id, item.format, item.sha256) for item in task.inputs)
        if sorted((source.get("artifact_id"), source.get("format"), source.get("sha256")) for source in lineage) != expected_inputs:
            raise ValueError("native improvement source lineage differs from its byte-bound inputs")
        if (case.row.get("expected_fact_ids") != facts or case.row.get("expected_evidence_ids") != evidence or
                case.outcomes.unstructured is None or case.outcomes.unstructured.required_fact_ids != tuple(facts)):
            raise ValueError("native improvement evidence lineage differs from its verified source receipt")
        namespace = case.dimensions.get("source_namespace", "")
        if not namespace.strip() or case.dimensions != _dimensions(task, namespace, software, lineage):
            raise ValueError("native improvement dimensions differ from its verified source contract")
        tasks.append(task)
    return tuple(tasks)


def _grading_identity(rater: Any, submit_identity: Mapping[str, Any]) -> dict[str, Any]:
    parts = {**grader_identity(rater), "native": native_grader_identity(), "native_submit": dict(submit_identity)}
    parts.pop("digest")
    return {**parts, "digest": digest(parts)}


def native_run_report(
    cases: Sequence[EvalCase], inputs: Mapping[str, bytes], submissions: Mapping[str, NativeSubmission], *,
    agent: str, agent_identity: Mapping[str, Any], grader: Mapping[str, Any] | None = None,
) -> RunReport:
    """Regrade actual native replies into an outcomes-only improvement report."""
    tasks = _tasks(cases)
    if not agent or not agent_identity or set(submissions) != {task.id for task in tasks}:
        raise ValueError("native improvement needs complete replies and an actual harness identity")
    used = _bytes(tasks, inputs)
    software = native_grader_identity()
    identity = dict(grader) if grader is not None else _grading_identity(NativeGrader(), agent_identity)
    if identity.get("native") != software or not isinstance(identity.get("native_submit"), Mapping) or not identity["native_submit"]:
        raise ValueError("native improvement report grader differs from the byte grader in force")
    results = []
    for case, task in zip(cases, tasks, strict=True):
        raw_submission = submissions[task.id]
        try:
            submission = NativeSubmission.model_validate(raw_submission)
        except ValidationError as error:
            submission = NativeSubmission()
            grade = NativeGrade(passed=False, findings=("submission_schema_invalid",), metrics={"validation_errors": len(error.errors())})
        else:
            grade = grade_native_task(task, used, submission)
        value = float(grade.passed)
        outcomes = unobserved_outcomes(answer_score=value).model_copy(update={"passed": grade.passed,
            "artifacts_produced": len(submission.files)})
        score = CaseScore(plan=unobserved_plan(), trajectory=unobserved_trajectory(), outcomes=outcomes,
            assertion_status="ok" if grade.passed else "fail", assertion_fails=grade.findings,
            observed=("outcomes",), score=value, passed=grade.passed)
        results.append(CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions,
            shape=case.plan.shape, agent=agent, status="graded", score=score,
            answer=json.dumps({"native_grade": grade.model_dump(mode="json"), "submission_digest": digest(submission.model_dump(mode="json"))}, sort_keys=True),
            notes=grade.findings))
    source_identities = sorted({(item.artifact_id, item.format, item.sha256) for task in tasks for item in task.inputs})
    return RunReport(agent=agent, principal=cases[0].principal, case_set=case_set_digest(cases), results=tuple(results),
        grader=identity, agent_identity=dict(agent_identity),
        pins={"native": software, "native_sources": source_identities,
            "native_submit": identity["native_submit"]})


class NativeRunner:
    """Existing improvement ``Runner`` with fresh repeat IDs and a byte grader."""

    def __init__(self, rendered: Mapping[str, NativeCorpusResult], submit: NativeSubmit, *,
                 world: World | Mapping[str, World],
                 namespace: str, submit_identity: Mapping[str, Any]):
        if not namespace.strip() or not submit_identity:
            raise ValueError("native runner needs a stable origin and explicit submission harness identity")
        self.rendered = dict(rendered)
        self.worlds = dict(world) if isinstance(world, Mapping) else {key: world for key in self.rendered}
        if set(self.worlds) != set(self.rendered):
            raise ValueError("native runner requires a trusted source world for every served artifact")
        self.submit = submit
        self.namespace = namespace
        self.submit_identity = dict(submit_identity)

    def grading_identity(self, rater: Any = None) -> dict[str, Any]:
        served = []
        for artifact_id, result in sorted(self.rendered.items()):
            manifest = result.manifest
            if manifest.artifact_id != artifact_id or hashlib.sha256(result.payload).hexdigest() != manifest.sha256:
                raise ValueError("native runner source bytes differ from the served manifest")
            served.append((artifact_id, manifest.format, manifest.sha256, digest(manifest.model_dump(mode="json"))))
        parts = {**_grading_identity(rater, self.submit_identity), "native_serving": served}
        canonical = _canonical_sources(self.worlds)
        parts["native_canonical_sources"] = [(key, canonical[key][1]) for key in sorted(canonical)]
        parts.pop("digest")
        return {**parts, "digest": digest(parts)}

    def validate_cases(self, cases: Sequence[EvalCase]) -> None:
        """Refuse relabeled independence before qualification or cached runs."""
        tasks = _tasks(cases)
        canonical = _canonical_sources(self.worlds)
        from .native_query_planning import NativeWorkloadPlan, _inventory

        selected: list[tuple[World, dict[str, NativeCorpusResult]]] = []
        for artifact_id in sorted({item.artifact_id for task in tasks for item in task.inputs}):
            if artifact_id not in self.rendered:
                raise ValueError("native improvement provenance source is missing: " + artifact_id)
            world = self.worlds[artifact_id]
            group = next((files for prior, files in selected if prior is world), None)
            if group is None:
                group = {}
                selected.append((world, group))
            group[artifact_id] = self.rendered[artifact_id]
        for world, files in selected:
            _inventory(world, files, NativeWorkloadPlan(use_case_id="native-runner", objective="Validate trusted source provenance."))
        for case, task in zip(cases, tasks, strict=True):
            if case.dimensions.get("source_namespace") != self.namespace:
                raise ValueError("native runner origin differs from its sealed cases")
            if case.row["native_lineage"] != _lineage(task, self.rendered, canonical):
                raise ValueError("native runner evidence lineage differs from actual source manifests")

    def __call__(self, cases: Sequence[EvalCase], agent: AgentUnderTest) -> RunReport:
        return self.run_experiment(cases, agent, directory=Path("."), label="native", repeat=None,
            grader=self.grading_identity(NativeGrader()))

    def run_experiment(self, cases: Sequence[EvalCase], agent: AgentUnderTest, *, directory: Path,
                       label: str, repeat: int | None, grader: Mapping[str, Any]) -> RunReport:
        self.validate_cases(cases)
        tasks = _tasks(cases)
        inputs = _bytes(tasks, {key: result.payload for key, result in self.rendered.items()})
        harness = fingerprint(agent)
        if not harness:
            raise ValueError("native target must expose its harness identity")
        submissions = {}
        for task in tasks:
            public = public_contract(task)
            public["execution_id"] = digest(["native-execution/v1", str(directory.resolve()), label, repeat, harness,
                self.submit_identity, task.id, _snapshot(task.inputs)])
            public_inputs = {item.artifact_id: inputs[item.artifact_id] for item in task.inputs}
            submissions[task.id] = self.submit(agent, public, public_inputs)
        return native_run_report(cases, inputs, submissions, agent=agent.name,
            agent_identity={**harness, "native_submit": self.submit_identity}, grader=grader)


def native_runner(rendered: Mapping[str, NativeCorpusResult], submit: NativeSubmit, *,
                  world: World | Mapping[str, World],
                  namespace: str, submit_identity: Mapping[str, Any]) -> NativeRunner:
    """Bind native runs to evaluator-owned source worlds, including ancestry."""
    return NativeRunner(rendered, submit, world=world, namespace=namespace, submit_identity=submit_identity)


__all__ = ["NativeGrader", "NativeRunner", "NativeSubmit", "native_grader_identity", "native_run_report", "native_source_digest",
           "native_runner", "native_task_cases"]
