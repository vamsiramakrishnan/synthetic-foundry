"""The thin waist.

Every subsystem speaks in these objects and nothing else. They are deliberately
defined before generators, renderers, or prompts, so that no subsystem gets to
invent its own vocabulary.

The set is fixed by ``docs/build-order.md``:

    World · Event · Fact · Persona · ArtifactIntent · ArtifactIR
    EvaluationCase · GenerationLedger

with supporting models for lore, access, intentional error, and the artifact
manifest. Nothing here knows about XLSX, Jira, or any LLM provider.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Model(BaseModel):
    """Base for every thin-waist model.

    Frozen, because immutability is a stated property of the API: deriving a new
    world must never mutate the one it came from.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class Authority(StrEnum):
    """How much weight a fact or artifact carries.

    Ordered least to most authoritative. A corpus that only records *what
    happened* cannot answer "what was believed at the time, and which source
    superseded it" — so authority is a first-class field, not metadata.
    """

    INITIAL_HYPOTHESIS = "initial_hypothesis"
    UNOFFICIAL_NOTE = "unofficial_note"
    WORKING_DOCUMENT = "working_document"
    APPROVED_REPORT = "approved_report"
    CONFIRMED = "confirmed"
    SYSTEM_OF_RECORD = "system_of_record"


#: Authority ranking, for resolving which of two competing sources wins.
AUTHORITY_RANK: dict[Authority, int] = {
    Authority.INITIAL_HYPOTHESIS: 0,
    Authority.UNOFFICIAL_NOTE: 1,
    Authority.WORKING_DOCUMENT: 2,
    Authority.APPROVED_REPORT: 3,
    Authority.CONFIRMED: 4,
    Authority.SYSTEM_OF_RECORD: 5,
}


class Lifecycle(StrEnum):
    """Where an artifact sits in its review lifecycle."""

    DRAFT = "draft"
    REVIEWED = "reviewed"
    APPROVED = "approved"
    PUBLISHED = "published"
    SUPERSEDED = "superseded"
    ARCHIVED = "archived"


class LoreKind(StrEnum):
    """What sort of commitment a piece of lore is."""

    EVENT = "event"
    DECISION = "decision"
    NORM = "norm"
    TENSION = "tension"
    CAPABILITY = "capability"
    CONSTRAINT = "constraint"


class ConstraintKind(StrEnum):
    """The closed vocabulary of things lore may constrain.

    Closed on purpose: a lore commitment may only constrain something the
    deterministic engine knows how to apply. Adding to this enum means teaching
    the engine to honour it, and that coupling is what stops lore from drifting
    into free text. See ``docs/lore.md``.
    """

    ORG_SHAPE = "org_shape"
    VENDOR_SELECTION = "vendor_selection"
    TECH_POSTURE = "tech_posture"
    PERSONA_TRAIT = "persona_trait"
    APPROVAL_CHAINS = "approval_chains"
    ARTIFACT_DENSITY = "artifact_density"
    TERMINOLOGY = "terminology"
    METRIC_EMPHASIS = "metric_emphasis"
    RISK_APPETITE = "risk_appetite"
    EVENT_LIKELIHOOD = "event_likelihood"


class EvaluationType(StrEnum):
    """Question shapes the corpus is built to support."""

    DIRECT_LOOKUP = "direct_lookup"
    CROSS_ARTIFACT = "cross_artifact"
    NUMERICAL_COMPARISON = "numerical_comparison"
    CAUSAL_MULTI_HOP = "causal_multi_hop"
    TEMPORAL_STATE = "temporal_state"
    AUTHORITY_RESOLUTION = "authority_resolution"
    EXPECTED_ABSTENTION = "expected_abstention"
    CITATION_REQUIRED = "citation_required"


class ErrorType(StrEnum):
    """Kinds of deliberate imperfection.

    Every one is labelled and traceable, which is what makes it a test case
    rather than a bug.
    """

    INCORRECT_INITIAL_HYPOTHESIS = "incorrect_initial_hypothesis"
    STALE_STATUS = "stale_status"
    MATERIAL_OMISSION = "material_omission"
    POLITICAL_UNDERSTATEMENT = "political_understatement"
    CONFLICTING_ACRONYM = "conflicting_acronym"
    DUPLICATE_ISSUE = "duplicate_issue"
    INCOMPLETE_SUMMARY = "incomplete_summary"
    OUTDATED_OWNER = "outdated_owner"
    MISSING_FIELD = "missing_field"
    TIMEZONE_DISCREPANCY = "timezone_discrepancy"


# ---------------------------------------------------------------------------
# Entities
# ---------------------------------------------------------------------------


class Entity(Model):
    """Anything with a stable identity in the world."""

    id: str
    name: str


class Company(Entity):
    industry: str
    headquarters: str
    fiscal_year_start_month: int = Field(ge=1, le=12)
    currency: str = "AUD"
    currency_unit: str = "thousands"
    employees_total: int = Field(ge=0)


class BusinessUnit(Entity):
    company_id: str
    leader_id: str
    kind: str


class Employee(Entity):
    title: str
    manager_id: str | None = None
    business_unit_id: str | None = None
    function: str
    cost_centre_id: str | None = None
    persona_id: str | None = None
    traits: dict[str, float] = Field(default_factory=dict)
    """Per-person trait adjustments, applied by lore.

    Separate from the shared ``Persona`` on purpose: a lore commitment that makes
    one manager defensive about ownership must not make every merchandiser
    defensive. The persona is the register; these are the individual.
    """


class System(Entity):
    """A system of record — an application that owns data."""

    purpose: str
    owner_id: str
    is_system_of_record_for: list[str] = Field(default_factory=list)


class Service(Entity):
    """A runtime service that can succeed or fail."""

    purpose: str
    owner_id: str
    system_id: str
    criticality_tier: int = Field(ge=1, le=4)
    depends_on: list[str] = Field(default_factory=list)


class CostCentre(Entity):
    owner_id: str
    business_unit_id: str | None = None


class Persona(Model):
    """How a specific author writes.

    In the thin waist because "who wrote this, and could they have known it" is
    load-bearing for authority and temporal questions — and because a narrative
    request cannot be formed without one.
    """

    id: str
    label: str
    voice: str
    sentence_complexity: Literal["low", "medium", "high"]
    technical_depth: Literal["low", "medium", "high"]
    optimism: float = Field(ge=-1.0, le=1.0)
    risk_tolerance: float = Field(ge=-1.0, le=1.0)
    political_awareness: float = Field(ge=-1.0, le=1.0)
    favourite_phrases: list[str] = Field(default_factory=list)
    traits: dict[str, float] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Lore
# ---------------------------------------------------------------------------


class LoreConstraint(Model):
    """One typed downstream effect of a lore commitment."""

    kind: ConstraintKind
    target: str
    effect: str
    magnitude: float | None = None


class LoreCommitment(Model):
    """A commitment about what the company is, that binds later generation.

    ``constrains`` is mandatory and non-empty. That is the schema enforcing the
    test from ``docs/lore.md``: lore that constrains nothing is decoration, and
    decoration cannot be committed.
    """

    id: str
    kind: LoreKind
    assertion: str
    effective_from: str
    effective_to: str | None = None
    actors: list[str] = Field(default_factory=list)
    constrains: list[LoreConstraint] = Field(min_length=1)
    scars: list[str] = Field(default_factory=list)
    visibility: Literal["acknowledged", "tacit", "denied"] = "acknowledged"


# ---------------------------------------------------------------------------
# Events and facts
# ---------------------------------------------------------------------------


class EnterpriseEvent(Model):
    """Something that happened. The deterministic engine decides these."""

    id: str
    kind: str
    occurred_at: datetime
    summary: str
    actors: list[str] = Field(default_factory=list)
    services: list[str] = Field(default_factory=list)
    systems: list[str] = Field(default_factory=list)
    business_units: list[str] = Field(default_factory=list)
    caused_by: list[str] = Field(default_factory=list)
    lore_ids: list[str] = Field(default_factory=list)


class Quantity(Model):
    """A measured value with its unit. Never a bare float."""

    amount: float
    unit: str


class CanonicalFact(Model):
    """A truth about the world, valid over an interval, with an authority.

    Append-only. An initial hypothesis is never mutated into the confirmed
    answer — both are preserved with different validity and authority, and the
    later one records what it ``supersedes``.
    """

    id: str
    kind: str
    subject: str
    period: str | None = None
    value: Quantity | None = None
    text_value: str | None = None
    valid_from: datetime
    valid_to: datetime | None = None
    authority: Authority
    source_system: str | None = None
    event_id: str | None = None
    supersedes: str | None = None
    lore_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _needs_a_value(self) -> CanonicalFact:
        if self.value is None and self.text_value is None:
            raise ValueError(f"{self.id}: fact must carry either value or text_value")
        return self

    @model_validator(mode="after")
    def _validity_ordered(self) -> CanonicalFact:
        if self.valid_to is not None and self.valid_to < self.valid_from:
            raise ValueError(f"{self.id}: valid_to precedes valid_from")
        return self

    @property
    def is_superseded(self) -> bool:
        """Whether this fact stopped being current at some point."""
        return self.valid_to is not None

    def holds_at(self, moment: datetime) -> bool:
        """Whether this fact was current at *moment*."""
        if moment < self.valid_from:
            return False
        return self.valid_to is None or moment < self.valid_to


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


class ArtifactIntent(Model):
    """The decision that an artifact should exist, before it has any content.

    Separating intent from content is what lets the deterministic layer resolve
    every table, reference, and number *before* prose is written.
    """

    id: str
    artifact_type: str
    domain: str
    audience: str
    author_id: str
    triggered_by: list[str] = Field(default_factory=list)
    required_fact_ids: list[str] = Field(default_factory=list)
    size_profile: Literal["small", "medium", "long"] = "small"
    rationale: str | None = None


class ArtifactSection(Model):
    """One resolved section of an artifact."""

    heading: str
    body: str | None = None
    table: list[dict[str, Any]] | None = None
    fact_ids: list[str] = Field(default_factory=list)


class ArtifactIR(Model):
    """Format-independent artifact content.

    Renderers consume this. It knows nothing about XLSX or Confluence, which is
    what lets a renderer be added without touching the world model.
    """

    id: str
    intent_id: str
    title: str
    sections: list[ArtifactSection] = Field(default_factory=list)


class ArtifactManifestEntry(Model):
    """The provenance record for one artifact.

    Nothing is anonymous: every artifact records where it came from, who wrote
    it, what facts justify it, and who may see it.
    """

    id: str
    intent_id: str | None = None
    title: str
    artifact_type: str
    domain: str
    path: str
    media_type: str
    author_id: str
    audience: str
    created_at: datetime
    authority: Authority
    lifecycle: Lifecycle
    supporting_fact_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    lore_ids: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    access_policy_id: str | None = None
    recipe: str | None = None
    version: int = 1


# ---------------------------------------------------------------------------
# Access, deliberate imperfection, evaluation, ledger
# ---------------------------------------------------------------------------


class AccessPolicy(Model):
    """Who may see an artifact. Deny takes precedence over allow."""

    id: str
    label: str
    allow_people: list[str] = Field(default_factory=list)
    allow_functions: list[str] = Field(default_factory=list)
    allow_business_units: list[str] = Field(default_factory=list)
    deny_people: list[str] = Field(default_factory=list)

    def permits(self, employee: Employee) -> bool:
        """Whether *employee* may see artifacts under this policy."""
        if employee.id in self.deny_people:
            return False
        if employee.id in self.allow_people:
            return True
        if employee.function in self.allow_functions:
            return True
        if employee.business_unit_id and employee.business_unit_id in self.allow_business_units:
            return True
        return not (self.allow_people or self.allow_functions or self.allow_business_units)


class IntentionalError(Model):
    """A deliberate imperfection, labelled so it is a test case not a bug."""

    id: str
    artifact_id: str
    error_type: ErrorType
    observed_value: str
    canonical_value: str
    canonical_fact_id: str | None = None
    detectable: bool = True
    note: str | None = None


class EvaluationCase(Model):
    """A question the corpus can be scored against.

    The answer is never invented: it is derived from canonical facts, which is
    what makes the eval set trustworthy.
    """

    id: str
    question: str
    evaluation_type: EvaluationType
    expected_answer: str | None = None
    expected_fact_ids: list[str] = Field(default_factory=list)
    required_artifact_ids: list[str] = Field(default_factory=list)
    distractor_artifact_ids: list[str] = Field(default_factory=list)
    temporal_cutoff: datetime | None = None
    expects_abstention: bool = False
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    reasoning: str | None = None

    @model_validator(mode="after")
    def _abstention_has_no_answer(self) -> EvaluationCase:
        if self.expects_abstention:
            if self.expected_fact_ids:
                raise ValueError(f"{self.id}: an abstention case cannot cite supporting facts")
        elif not self.expected_fact_ids:
            raise ValueError(f"{self.id}: non-abstention case must cite at least one fact")
        return self


class GenerationLedgerEntry(Model):
    """One recorded generative call.

    In the thin waist rather than inside an LLM client, because a world must
    *ship* with its ledger for a corpus to be citable. ``from_seed()`` replays
    these instead of re-prompting, which is how a world stays byte-identical
    without depending on model calls being reproducible.
    """

    id: str
    key: str
    call_site: str
    ordinal: int
    world_seed: int
    input_facts_digest: str
    model_id: str
    prompt_version: str
    output: dict[str, Any]
    rejected_attempts: int = 0

    @field_validator("key")
    @classmethod
    def _key_is_content_address(cls, value: str) -> str:
        if len(value) < 16:
            raise ValueError("ledger key must be a content address, not a label")
        return value
