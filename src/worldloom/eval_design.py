"""Eval-first design contracts.

Worldloom normally starts from a seed and lets a world produce evaluation cases.
That remains useful for corpus inspection, but it is the wrong direction when the
purpose of the corpus is an evaluation. This module defines the inverse path:

    EvalSpec -> CandidatePlan -> World -> EvalInstance

The design also owns the *shape* an agent must survive. A correct answer over a
12-field issue is not equivalent to the same answer inside a 300-field issue; a
fact on slide 4 is not the same test as a fact in speaker notes on slide 87.
Shape is therefore part of the immutable eval contract rather than a renderer
accident.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Model


class RequirementKind(StrEnum):
    """Closed vocabulary of world conditions an eval may require."""

    FACT = "fact"
    EVENT = "event"
    ARTIFACT = "artifact"
    CONNECTOR = "connector"
    REVISION_CHAIN = "revision_chain"
    PERMISSION = "permission"
    DISTRACTOR = "distractor"
    TEMPORAL_RELATION = "temporal_relation"


class RecordShapeRequirement(Model):
    """Wide-record and payload pressure required by an eval."""

    connector: str
    entity: str
    records: int = Field(default=1, ge=1)
    total_fields: int = Field(default=0, ge=0)
    custom_fields: int = Field(default=0, ge=0)
    minimum_populated_fields: int = Field(default=0, ge=0)
    minimum_payload_bytes: int = Field(default=0, ge=0)
    projection_required: bool = False
    maximum_read_bytes: int | None = Field(default=None, ge=1)
    fill_rate_scale: float = Field(default=1.0, gt=0.0)

    @model_validator(mode="after")
    def _possible_record_shape(self) -> RecordShapeRequirement:
        if self.total_fields and self.custom_fields > self.total_fields:
            raise ValueError("custom_fields cannot exceed total_fields")
        if self.total_fields and self.minimum_populated_fields > self.total_fields:
            raise ValueError("minimum_populated_fields cannot exceed total_fields")
        if self.projection_required and self.maximum_read_bytes is None:
            raise ValueError("projection_required needs maximum_read_bytes")
        return self


EvidenceModality = Literal[
    "text",
    "table",
    "chart",
    "speaker_notes",
    "hidden_slide",
    "cell",
    "formula",
    "comment",
    "image",
    "metadata",
]


class ArtifactShapeRequirement(Model):
    """Heavy native-artifact shape required by an eval."""

    artifact_type: str
    instances: int = Field(default=1, ge=1)
    pages: int = Field(default=0, ge=0)
    paragraphs: int = Field(default=0, ge=0)
    slides: int = Field(default=0, ge=0)
    sheets: int = Field(default=0, ge=0)
    rows_per_sheet: int = Field(default=0, ge=0)
    columns_per_sheet: int = Field(default=0, ge=0)
    versions: int = Field(default=1, ge=1)
    file_size_bytes: int = Field(default=0, ge=0)
    image_bytes: int = Field(default=0, ge=0)
    speaker_note_slides: int = Field(default=0, ge=0)
    hidden_slides: int = Field(default=0, ge=0)
    native_charts: int = Field(default=0, ge=0)
    formulas: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    evidence_index: int | None = Field(default=None, ge=1)
    evidence_modality: EvidenceModality | None = None
    locator_required: bool = True

    @model_validator(mode="after")
    def _possible_artifact_shape(self) -> ArtifactShapeRequirement:
        if self.slides and self.hidden_slides > self.slides:
            raise ValueError("hidden_slides cannot exceed slides")
        if self.slides and self.speaker_note_slides > self.slides:
            raise ValueError("speaker_note_slides cannot exceed slides")
        if self.evidence_index is not None:
            bound = self.slides or self.pages or self.rows_per_sheet
            if bound and self.evidence_index > bound:
                raise ValueError("evidence_index exceeds the declared artifact depth")
        if self.evidence_modality is None and self.evidence_index is not None:
            raise ValueError("evidence_index needs evidence_modality")
        return self

    @property
    def cells(self) -> int:
        return self.sheets * self.rows_per_sheet * self.columns_per_sheet


class ThreadShapeRequirement(Model):
    """Long conversational history required by an eval."""

    connector: str
    entity: str
    threads: int = Field(default=1, ge=1)
    messages_per_thread: int = Field(default=1, ge=1)
    reply_depth: int = Field(default=1, ge=1)
    attachments_per_thread: int = Field(default=0, ge=0)
    minimum_payload_bytes: int = Field(default=0, ge=0)
    pagination_required: bool = False


class EvalShape(Model):
    """Real-world load contract shared by generation, tools, renderers and grading."""

    records: tuple[RecordShapeRequirement, ...] = ()
    artifacts: tuple[ArtifactShapeRequirement, ...] = ()
    threads: tuple[ThreadShapeRequirement, ...] = ()

    @property
    def empty(self) -> bool:
        return not (self.records or self.artifacts or self.threads)


class EvalStepSpec(Model):
    """One abstract operation in the task skeleton.

    Concrete record ids and expected facts are intentionally absent. The
    connector/entity/operation triple is enough to bind the step to one concrete
    connector tool; record ids are bound only after a candidate world exists.
    """

    id: str
    capability: str
    depends_on: tuple[str, ...] = ()
    connector: str | None = None
    entity: str | None = None
    operation: str | None = None
    effect: Literal["read", "transform", "write", "verify"] = "read"

    @model_validator(mode="after")
    def _connector_tuple(self) -> EvalStepSpec:
        if self.entity is not None and self.connector is None:
            raise ValueError(f"{self.id}: entity needs connector")
        return self


class WorldRequirement(Model):
    """A predicate a generated candidate world must satisfy."""

    id: str
    kind: RequirementKind
    selector: dict[str, str | int | bool] = Field(default_factory=dict)
    minimum: int = Field(default=1, ge=1)
    hard: bool = True


class EvalSpec(Model):
    """An evaluation before any synthetic data exists."""

    id: str
    capability: str
    persona: str
    request_template: str
    steps: tuple[EvalStepSpec, ...]
    requirements: tuple[WorldRequirement, ...]
    shape: EvalShape = Field(default_factory=EvalShape)
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    candidate_count: int = Field(default=4, ge=1, le=10_000)

    @model_validator(mode="after")
    def _closed_design(self) -> EvalSpec:
        if not self.steps:
            raise ValueError(f"{self.id}: eval needs at least one task step")
        if not self.requirements:
            raise ValueError(f"{self.id}: eval needs at least one world requirement")

        step_ids: set[str] = set()
        for step in self.steps:
            if step.id in step_ids:
                raise ValueError(f"{self.id}: duplicate step {step.id!r}")
            missing = set(step.depends_on) - step_ids
            if missing:
                raise ValueError(
                    f"{self.id}: {step.id} depends on missing or later steps {sorted(missing)}"
                )
            step_ids.add(step.id)

        requirement_ids = [requirement.id for requirement in self.requirements]
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError(f"{self.id}: requirement ids must be unique")
        return self


class CandidatePlan(Model):
    """One deterministic attempt to instantiate an :class:`EvalSpec`."""

    eval_spec_id: str
    ordinal: int = Field(ge=0)
    seed: int = Field(ge=0)
    requirements: tuple[WorldRequirement, ...]
    shape: EvalShape = Field(default_factory=EvalShape)
    design_digest: str


def _canonical_design_payload(spec: EvalSpec) -> dict[str, Any]:
    payload = spec.model_dump(mode="json")
    # Compatibility invariant: adding shape/entity support must not reshuffle
    # old eval families whose designs did not contain those fields.
    if spec.shape.empty:
        payload.pop("shape", None)
    for step in payload.get("steps", []):
        if step.get("entity") is None:
            step.pop("entity", None)
    return payload


def _canonical_design(spec: EvalSpec) -> bytes:
    return json.dumps(
        _canonical_design_payload(spec),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def design_digest(spec: EvalSpec) -> str:
    """Content address of the immutable evaluation design."""

    return hashlib.sha256(_canonical_design(spec)).hexdigest()


def candidate_seed(spec: EvalSpec, ordinal: int) -> int:
    """Stable 63-bit seed for candidate *ordinal*."""

    if ordinal < 0:
        raise ValueError("candidate ordinal must be non-negative")
    digest = hashlib.sha256(
        _canonical_design(spec) + b"\0candidate\0" + str(ordinal).encode("ascii")
    ).digest()
    return int.from_bytes(digest[:8], "big") & ((1 << 63) - 1)


def plan_candidates(spec: EvalSpec, *, count: int | None = None) -> tuple[CandidatePlan, ...]:
    """Compile one eval design into deterministic candidate-world attempts."""

    total = spec.candidate_count if count is None else count
    if total < 1:
        raise ValueError("candidate count must be at least one")
    digest = design_digest(spec)
    return tuple(
        CandidatePlan(
            eval_spec_id=spec.id,
            ordinal=ordinal,
            seed=candidate_seed(spec, ordinal),
            requirements=spec.requirements,
            shape=spec.shape,
            design_digest=digest,
        )
        for ordinal in range(total)
    )


__all__ = [
    "ArtifactShapeRequirement",
    "CandidatePlan",
    "EvalShape",
    "EvalSpec",
    "EvalStepSpec",
    "EvidenceModality",
    "RecordShapeRequirement",
    "RequirementKind",
    "ThreadShapeRequirement",
    "WorldRequirement",
    "candidate_seed",
    "design_digest",
    "plan_candidates",
]
