"""Eval-first design contracts.

Worldloom normally starts from a seed and lets a world produce evaluation cases.
That remains useful for corpus inspection, but it is the wrong direction when the
purpose of the corpus is an evaluation.  This module defines the inverse path:

    EvalSpec -> CandidatePlan -> World -> EvalInstance

Only the first arrow lives here.  A plan says what a candidate world must make
true; it does not generate a world, invent evidence, or know about a renderer.
That separation is deliberate: evaluation design owns the problem, generators
own how to satisfy it, and the completed world remains the oracle.
"""

from __future__ import annotations

import hashlib
import json
from enum import StrEnum
from typing import Literal

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


class EvalStepSpec(Model):
    """One abstract operation in the task skeleton.

    Concrete record ids and expected facts are intentionally absent.  Those are
    bound only after a candidate world exists.
    """

    id: str
    capability: str
    depends_on: tuple[str, ...] = ()
    connector: str | None = None
    operation: str | None = None
    effect: Literal["read", "transform", "write", "verify"] = "read"


class WorldRequirement(Model):
    """A predicate a generated candidate world must satisfy.

    ``selector`` is a small declarative filter over Worldloom's own typed
    records, e.g. ``{"artifact_type": "finance_workbook"}``.  It is data, not
    executable code.  Candidate validation owns its interpretation.
    """

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
    design_digest: str


def _canonical_design(spec: EvalSpec) -> bytes:
    return json.dumps(
        spec.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")


def design_digest(spec: EvalSpec) -> str:
    """Content address of the immutable evaluation design."""

    return hashlib.sha256(_canonical_design(spec)).hexdigest()


def candidate_seed(spec: EvalSpec, ordinal: int) -> int:
    """Stable 63-bit seed for candidate *ordinal*.

    Candidate seeds depend on the complete eval design, not process order or the
    wall clock.  Editing a requirement intentionally creates a new candidate
    family rather than silently reusing worlds generated for an older eval.
    """

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
            design_digest=digest,
        )
        for ordinal in range(total)
    )


__all__ = [
    "CandidatePlan",
    "EvalSpec",
    "EvalStepSpec",
    "RequirementKind",
    "WorldRequirement",
    "candidate_seed",
    "design_digest",
    "plan_candidates",
]
