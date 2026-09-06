"""Deterministic organization-wide artifact realism primitives.

This module is intentionally renderer-agnostic. It derives stable organization
and department habits from the world seed, then derives bounded artifact-local
variation from those habits. Renderers consume the resulting profile; they do
not draw their own style randomness.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Literal

from pydantic import Field, model_validator

from .ids import content_key
from .models import Lifecycle, Model
from .rng import Rng

Density = Literal["sparse", "balanced", "dense"]
Tone = Literal["terse", "plain", "formal", "analytical"]
DeckGrammar = Literal["executive", "operating_review", "incident", "decision"]
WorkbookGrammar = Literal["analyst", "controller", "operations"]
DocumentGrammar = Literal["memo", "operating_review", "policy", "rca", "sop"]


class OrganizationDNA(Model):
    """Stable house style shared by every artifact in one synthetic company."""

    id: str
    density: Density
    tone: Tone
    typography_family: Literal["humanist", "neo_grotesk", "serif_sans"]
    chart_preference: Literal["bar_first", "line_first", "table_first"]
    title_case: Literal["sentence", "title"]
    page_numbers: bool
    footer_mode: Literal["minimal", "classification", "document_control"]
    accent_count: int = Field(ge=1, le=3)


class DepartmentDNA(Model):
    """A bounded mutation of the organization style for one function."""

    organization_id: str
    department: str
    density: Density
    tone: Tone
    prefers_tables: bool
    prefers_bullets: bool
    revision_formality: Literal["light", "controlled"]


class ArtifactStyle(Model):
    """Artifact-local style selected from stable organization and team habits."""

    organization_id: str
    department: str
    artifact_key: str
    density: Density
    tone: Tone
    deck_grammar: DeckGrammar
    workbook_grammar: WorkbookGrammar
    document_grammar: DocumentGrammar
    information_blocks: int = Field(ge=2, le=12)
    appendix_probability: int = Field(ge=0, le=100)


class LifecycleStep(Model):
    state: Lifecycle
    at: datetime
    actor_id: str | None = None


class ArtifactLifecycle(Model):
    artifact_id: str
    revision: int = Field(ge=1)
    steps: tuple[LifecycleStep, ...]
    supersedes_id: str | None = None

    @model_validator(mode="after")
    def chronological(self) -> ArtifactLifecycle:
        if not self.steps:
            raise ValueError("artifact lifecycle must contain at least one step")
        instants = [step.at for step in self.steps]
        if instants != sorted(instants):
            raise ValueError("artifact lifecycle steps must be chronological")
        return self


class EvidenceNode(Model):
    """One surface-specific trace of the same underlying business episode."""

    id: str
    episode_id: str
    surface: Literal[
        "email", "jira", "servicenow", "confluence", "pptx", "docx", "pdf", "xlsx"
    ]
    external_id: str
    occurred_at: datetime
    fact_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    references: tuple[str, ...] = ()


class EvidenceGraph(Model):
    nodes: tuple[EvidenceNode, ...]

    @model_validator(mode="after")
    def references_exist(self) -> EvidenceGraph:
        ids = {node.id for node in self.nodes}
        for node in self.nodes:
            missing = set(node.references) - ids
            if missing:
                raise ValueError(
                    f"evidence node {node.id} references missing nodes {sorted(missing)}"
                )
        return self


def organization_dna(seed: int, company_id: str) -> OrganizationDNA:
    """Derive one reproducible house style without Python hash or wall clock."""
    rng = Rng(seed, f"artifact-dna/{company_id}")
    return OrganizationDNA(
        id=f"DNA-{content_key(seed, company_id, 'artifact-dna')[:16].upper()}",
        density=rng.choice(("sparse", "balanced", "dense")),
        tone=rng.choice(("terse", "plain", "formal", "analytical")),
        typography_family=rng.choice(("humanist", "neo_grotesk", "serif_sans")),
        chart_preference=rng.choice(("bar_first", "line_first", "table_first")),
        title_case=rng.choice(("sentence", "title")),
        page_numbers=rng.chance(0.8),
        footer_mode=rng.choice(("minimal", "classification", "document_control")),
        accent_count=rng.integer(1, 3),
    )


def department_dna(seed: int, org: OrganizationDNA, department: str) -> DepartmentDNA:
    rng = Rng(seed, f"artifact-dna/{org.id}/department/{department.lower()}")
    density: Density = org.density
    if rng.chance(0.25):
        density = rng.choice(("sparse", "balanced", "dense"))
    tone: Tone = org.tone
    if rng.chance(0.35):
        tone = rng.choice(("terse", "plain", "formal", "analytical"))
    return DepartmentDNA(
        organization_id=org.id,
        department=department,
        density=density,
        tone=tone,
        prefers_tables=rng.chance(0.55 if department.lower() in {"finance", "operations"} else 0.35),
        prefers_bullets=rng.chance(0.65),
        revision_formality="controlled" if department.lower() in {"finance", "risk", "legal"} else rng.choice(("light", "controlled")),
    )


def artifact_style(seed: int, team: DepartmentDNA, artifact_key: str) -> ArtifactStyle:
    rng = Rng(seed, f"artifact-dna/{team.organization_id}/{team.department}/{artifact_key}")
    blocks = {"sparse": (2, 5), "balanced": (4, 8), "dense": (7, 12)}[team.density]
    return ArtifactStyle(
        organization_id=team.organization_id,
        department=team.department,
        artifact_key=artifact_key,
        density=team.density,
        tone=team.tone,
        deck_grammar=rng.choice(("executive", "operating_review", "incident", "decision")),
        workbook_grammar=rng.choice(("analyst", "controller", "operations")),
        document_grammar=rng.choice(("memo", "operating_review", "policy", "rca", "sop")),
        information_blocks=rng.integer(*blocks),
        appendix_probability={"sparse": 20, "balanced": 45, "dense": 70}[team.density],
    )


def lifecycle_for(
    artifact_id: str,
    created_at: datetime,
    *,
    author_id: str | None = None,
    reviewer_id: str | None = None,
    publish: bool = True,
    revision: int = 1,
    supersedes_id: str | None = None,
) -> ArtifactLifecycle:
    """Create deterministic lifecycle timestamps from a simulated timestamp."""
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    steps = [LifecycleStep(state=Lifecycle.DRAFT, at=created_at, actor_id=author_id)]
    if reviewer_id:
        steps.append(
            LifecycleStep(
                state=Lifecycle.REVIEWED,
                at=created_at + timedelta(hours=2),
                actor_id=reviewer_id,
            )
        )
        steps.append(
            LifecycleStep(
                state=Lifecycle.APPROVED,
                at=created_at + timedelta(hours=4),
                actor_id=reviewer_id,
            )
        )
    if publish:
        steps.append(
            LifecycleStep(
                state=Lifecycle.PUBLISHED,
                at=created_at + timedelta(hours=6 if reviewer_id else 2),
                actor_id=reviewer_id or author_id,
            )
        )
    return ArtifactLifecycle(
        artifact_id=artifact_id,
        revision=revision,
        steps=tuple(steps),
        supersedes_id=supersedes_id,
    )
