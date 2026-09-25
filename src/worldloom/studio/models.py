"""Project intent references existing company, LOB, process and eval contracts."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from ..company import from_document, resolve
from ..enterprise_specs import ScenarioProfile
from ..eval_design import EvalSpec
from ..evals.dataset_contract import DatasetSource
from ..lob import Lob, lint_lob
from ..models import Model
from ..native_corpus import NativeCorpusPlan
from ..native_tasks import NativeTask
from ..packs import Pack, PackUnit
from ..process_bindings.models import CompanySpec as ProcessCompany
from ..retail_replenishment import RetailProcess
from ..synthesis.connectors import IncidentRule
from ..synthesis.models import Program
from .calibration import CompanyCalibrationPlan
from .native_calibration import NativeCalibrationPlan
from .native_suite_contract import NativeSuiteRequest

#: The kinds a project may put in force. These three are read through
#: ``packkit.text``/``policy``/``term`` everywhere a company is built; a
#: company, connector or LOB pack is authored into the project itself.
PROJECT_PACK_KINDS: tuple[str, ...] = ("industry", "prompts", "policy")


class UseCase(Model):
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")
    title: str = Field(min_length=1, max_length=200)
    objective: str = Field(min_length=1, max_length=4000)
    owner: str = ""
    lob: str = ""
    activities: tuple[str, ...] = ()
    count: int = Field(default=12, ge=1, le=100_000, strict=True)
    scenario: ScenarioProfile | None = None
    simulation: Program | None = None
    incident_rule: IncidentRule | None = None
    dag_shapes: tuple[str, ...] = ("*",)
    where: dict[str, str] = Field(default_factory=dict)
    construction: EvalSpec | None = None

    def source(self, project: ProjectSpec) -> DatasetSource:
        if self.scenario is None:
            raise ValueError(f"use case {self.id} needs an executable workflow contract")
        return DatasetSource(company=project.company, scenario=self.scenario,
                             simulation=self.simulation, incident_rule=self.incident_rule,
                             dag_shapes=self.dag_shapes, where=self.where,
                             pool_size=project.pool_size, planning_budget=project.planning_budget,
                             acknowledged_unmet=project.acknowledged_unmet)


class ProjectSpec(Model):
    schema_version: Literal["worldloom.project/v1"] = "worldloom.project/v1"
    company: dict[str, Any]
    seed: int = Field(default=8128, strict=True)
    structure: ProcessCompany | None = None
    lobs: tuple[Lob, ...] = ()
    divisions: tuple[PackUnit, ...] = ()
    episodes: tuple[str, ...] = ()
    narration_job: str | None = Field(default=None, pattern=r"^[a-f0-9]{30,64}$")
    calibration: CompanyCalibrationPlan | None = None
    retail_process: RetailProcess | None = None
    native_calibration: NativeCalibrationPlan | None = None
    native_corpus: tuple[NativeCorpusPlan, ...] = ()
    native_tasks: tuple[NativeTask, ...] = ()
    use_cases: tuple[UseCase, ...] = ()
    acknowledged_unmet: tuple[str, ...] = ()
    max_batches: int = Field(default=16, ge=1, le=10_000, strict=True)
    pool_size: int = Field(default=24, ge=1, le=512, strict=True)
    planning_budget: int = Field(default=1024, ge=1, le=100_000, strict=True)
    max_per_task: int = Field(default=24, ge=1, strict=True)
    max_per_case: int = Field(default=3, ge=1, strict=True)
    max_per_request: int = Field(default=12, ge=1, strict=True)
    minimum_tasks: int = Field(default=2, ge=1, strict=True)
    split_by: Literal["task", "case"] = "case"
    split_weights: dict[str, int] = Field(default_factory=lambda: {"train": 80, "validation": 10, "test": 10})
    #: Packs this company is built, interviewed and evaluated under, as pinned
    #: references (``industry:healthcare@<digest>``). The store pins a bare
    #: ``kind:name`` when it records a revision, so a revision replays exactly
    #: or is refused, never silently rebuilt under a pack that moved. The
    #: field defaults above stay literals because they are the JSON schema a
    #: harness reads; ``studio.project.*`` in the policy pack holds the same
    #: numbers for the presets that an industry pack may resize.
    packs: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def _omit_no_packs(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # A project with no packs dumps exactly as before packs existed, so its
        # project key, revision digests and snapshot identity are unchanged.
        data: dict[str, Any] = handler(self)
        if not self.packs:
            data.pop("packs", None)
        return data

    @model_validator(mode="after")
    def _references(self) -> ProjectSpec:
        from datetime import date

        from ..packkit import parse_ref
        from ..process_bindings import compile_company

        pack_kinds: set[str] = set()
        for ref in self.packs:
            parsed = parse_ref(ref) if ":" in ref else None
            if parsed is None or parsed.path is not None or parsed.kind not in PROJECT_PACK_KINDS:
                raise ValueError(f"packs: {ref!r} must be a {', '.join(PROJECT_PACK_KINDS)} pack reference kind:name[@digest]")
            if parsed.kind in pack_kinds:
                raise ValueError(f"packs: two {parsed.kind} packs; a project is built under one of each kind")
            pack_kinds.add(str(parsed.kind))
        spec = from_document(self.company)
        if spec.pack:
            raise ValueError("studio projects embed company identity; external pack paths are not portable")
        if spec.identity is None or not spec.identity.company_name.strip():
            raise ValueError("name the company before creating its project")
        resolution = resolve(spec)
        resolution.raise_for_conflicts()
        if self.divisions:
            if resolution.pack is None:
                raise ValueError("explicit revenue divisions require a resolved company identity")
            Pack.model_validate({**resolution.pack.model_dump(mode="json"),
                                 "units": [unit.model_dump(mode="json") for unit in self.divisions]})
            if len({unit.key for unit in self.divisions}) != len(self.divisions):
                raise ValueError("revenue division keys must be unique")
        if set(self.acknowledged_unmet) - set(resolution.unmet):
            raise ValueError("company limitation acknowledgement is stale or unknown")
        if self.structure and self.structure.name != spec.identity.company_name:
            raise ValueError("process structure and company profile must name the same company")
        if len({u.id for u in self.use_cases}) != len(self.use_cases):
            raise ValueError("use case IDs must be unique")
        if len({plan.artifact_id for plan in self.native_corpus}) != len(self.native_corpus):
            raise ValueError("native corpus artifact IDs must be unique")
        if len({task.id for task in self.native_tasks}) != len(self.native_tasks):
            raise ValueError("native task IDs must be unique")
        native_ids = {plan.artifact_id for plan in self.native_corpus}
        for task in self.native_tasks:
            if not task.prompt.strip():
                raise ValueError("native task requires a business question for the target")
            if task.use_case_id not in {case.id for case in self.use_cases}:
                raise ValueError("native task must name its owning use case")
            if any(source.artifact_id not in native_ids for source in task.inputs):
                raise ValueError("native task names an artifact outside this company's native corpus")
        if len({lob.name for lob in self.lobs}) != len(self.lobs):
            raise ValueError("LOB names must be unique")
        if any(lob.engine != resolution.engine for lob in self.lobs):
            raise ValueError("LOB engine differs from the company engine")
        lob_findings = [finding for lob in self.lobs for finding in lint_lob(lob, base=resolution.engine)]
        if lob_findings:
            raise ValueError("; ".join(lob_findings))
        if self.episodes != tuple(sorted(set(self.episodes))):
            raise ValueError("episode periods must be unique and chronological")
        for period in self.episodes:
            if len(period) != 7:
                raise ValueError("episode periods use YYYY-MM")
            date.fromisoformat(period + "-01")
        rows = compile_company(self.structure).rows if self.structure else ()
        units = {bu.name for bu in self.structure.bus} if self.structure else set()
        if self.retail_process is not None:
            if resolution.engine != "retail":
                raise ValueError("retail processes require the retail company engine")
            for scope in self.retail_process.scopes:
                if scope.business_unit not in units:
                    raise ValueError("retail process names an unknown business unit")
                if scope.activity_id not in {row.activity_id for row in rows if row.owner_bu == scope.business_unit}:
                    raise ValueError("retail process names an activity outside its owner")
                if scope.lob and scope.lob not in {lob.name for lob in self.lobs}:
                    raise ValueError("retail process names an unknown LOB")
        for case in self.use_cases:
            if case.owner and case.owner not in units:
                raise ValueError(f"use case {case.id} names an unknown business unit")
            if case.lob and case.lob not in {lob.name for lob in self.lobs}:
                raise ValueError(f"use case {case.id} names an unknown LOB")
            available = {row.activity_id for row in rows if not case.owner or row.owner_bu == case.owner}
            if set(case.activities) - available:
                raise ValueError(f"use case {case.id} names a process outside its owner")
            if case.scenario is not None:
                case.source(self)
            elif case.simulation is not None or case.incident_rule is not None:
                raise ValueError("an evidence generator needs an executable scenario")
        return self


class InterviewReply(Model):
    request_id: str
    message: str = Field(min_length=1, max_length=8000)
    questions: tuple[str, ...] = Field(default=(), max_length=5)
    proposal: ProjectSpec | None = None
    #: When true, the Studio derives the proposal's divisions, LOBs, use cases
    #: and acknowledged limitations from its `structure` through the process
    #: catalogue (`industry.rederive`) before recording the revision. The
    #: interviewer describes the company; the catalogue says what it does.
    derive: bool = False

    @model_validator(mode="after")
    def _derive_needs_a_structure(self) -> InterviewReply:
        if self.derive and (self.proposal is None or self.proposal.structure is None):
            raise ValueError("derive needs a proposal with a process structure to derive from")
        return self


class RunOptions(Model):
    operation: Literal["build", "compile", "interview", "narrate", "foundry", "native", "prepare_native", "evalrun",
                       "pack_author"]
    batch_limit: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    message: str = Field(default="", max_length=8000)
    max_rounds: int = Field(default=2, ge=1, le=8, strict=True)
    harness_identity: str = ""
    native_suite: NativeSuiteRequest | None = None
    #: `evalrun` jobs: which agent is graded on the revision's connector
    #: dataset (the reference agent needs no harness; `harness` is the
    #: configured coding harness over the exec seam), whether it executes
    #: (`run`) or only states a DAG (`plan`), and which rows it sees.
    evalrun_agent: Literal["reference", "harness"] = "reference"
    evalrun_mode: Literal["run", "plan"] = "run"
    #: Which cases: the revision's connector dataset, the process programme's
    #: record requests over the company's own records (a project with a
    #: process structure), or both. The dataset is the default, as before.
    evalrun_source: Literal["dataset", "programme", "both"] = "dataset"
    evalrun_split: str = Field(default="", max_length=40)
    evalrun_limit: int | None = Field(default=None, ge=1, le=100_000, strict=True)
    evalrun_max_turns: int = Field(default=32, ge=1, le=128, strict=True)
    #: `pack_author` jobs: the kind and (optional) name of the pack the
    #: configured harness is interviewed to author into the workspace's pack
    #: root; `message` is what the operator asked for. A workspace job, not a
    #: company's: it belongs to no project revision.
    pack_kind: str = Field(default="", max_length=40)
    pack_name: str = Field(default="", max_length=64)

    @model_serializer(mode="wrap")
    def _omit_pack_fields(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        # Job keys are digests of these options; a run that authors no pack
        # keeps the key it had before pack authoring existed.
        data: dict[str, Any] = handler(self)
        for key in ("pack_kind", "pack_name"):
            if not data.get(key):
                data.pop(key, None)
        return data

    @model_validator(mode="after")
    def _native_request(self) -> RunOptions:
        if (self.operation == "prepare_native") != (self.native_suite is not None):
            raise ValueError("native_suite is required only for prepare_native jobs")
        if (self.operation == "pack_author") != bool(self.pack_kind):
            raise ValueError("pack_kind is required only for pack_author jobs")
        if self.operation == "pack_author" and not (self.message.strip() and self.harness_identity):
            raise ValueError("authoring a pack needs a message and a configured harness")
        if self.operation == "evalrun" and self.evalrun_agent == "harness" and not self.harness_identity:
            raise ValueError("evaluating a harness needs a configured harness; the reference agent needs none")
        return self


__all__ = ["ProjectSpec", "UseCase", "InterviewReply", "RunOptions"]
