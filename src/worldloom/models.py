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
    ACCOUNTABILITY = "accountability"
    """Who is judged on which measure. Target is ``role_key/fact_kind``, and
    ``magnitude`` is the tolerance band in per cent.

    Added because the corpus had no edge from a person to a number. Budgets
    attach to business units, variances are reported and never judged, and the
    one ownership fact the engine mints resolves to "unassigned" — so *who was
    accountable for the unit that missed* had no answer in any corpus this tool
    had produced, which is a strange gap in a dataset built for questions about
    an enterprise.

    Read by ``org_builder.accountability_facts``, which is what keeps this kind
    from joining the several above it that are carried, citable, and inert."""


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
    HARDCODED_VALUE = "hardcoded_value"
    """A workbook cell carries a typed-in number where the formula belongs.

    The first *mechanical* kind: every kind above it is editorial — a stale
    page, a wrong first hypothesis — while this one is a spreadsheet failure
    mode, a paste-over that severed a cell from its derivation. For this kind
    and ``SHORT_RANGE``, ``IntentionalError.observed_value`` is the bare
    reading of the wrong figure rather than a prose account, because two
    subsystems parse it back: ``compiler.mechanical`` types it into the cell,
    and ``validate.intentional`` compares the compiled cell against it."""
    SHORT_RANGE = "short_range"
    """A SUM whose range stops one row early, so the total misses a member.

    Mechanical, like ``HARDCODED_VALUE``, and carrying the same bare-reading
    ``observed_value`` contract for the same two parsers."""


# ---------------------------------------------------------------------------
# The fiscal calendar
# ---------------------------------------------------------------------------


class FiscalPeriod(Model):
    """Where a ``YYYY-MM`` reporting period sits inside a company's own year.

    A period keeps its calendar identity — ``2026-03`` is March 2026 in every
    world this tool builds, because every renderer prints that string and every
    narrated sentence says "March". What a fiscal year decides is not what a
    period *is* but what it *counts as*: which reporting year it falls in, how
    far into that year it is, and whether it closes a quarter or the year.

    That split is the whole of the fiscal-year design, and it was chosen against
    the alternative — periods becoming fiscal throughout, so that ``2026-03``
    would name the ninth month of FY2026 rather than March — for two reasons.
    The first is that the alternative cannot be made byte-neutral: relabelling
    periods changes the ``{period}`` in every event summary, every artifact
    title, and every evaluation question, at *every* fiscal year start including
    the shipped July. The second is sharper. Under Australia's July year the
    insurer archetype's shipped valuation period is ``2026-06`` — which is the
    fiscal **year end**. So any rule that made a year-end period behave
    differently (a longer hard close, an extra approval, a different due date)
    would have moved a shipped corpus the day it landed, at the default value,
    with no locale involved at all. The fiscal year is a frame, not a clock.
    """

    year: int
    """The year the fiscal year *ends* in — FY2026 is July 2025 to June 2026
    under a July start, and the calendar year under a January one. One
    convention rather than a choice, because the two conventions disagree only
    for a non-January start and picking per-jurisdiction would mean a corpus
    could not compare two subsidiaries' FY labels."""

    quarter: int = Field(ge=1, le=4)
    month: int = Field(ge=1, le=12)
    """The period's ordinal position in the fiscal year: 1 is the first month of
    the year, not January. This is the field that makes "quarter" stop being a
    label a caller typed — ``banking_scenarios`` documents that "the label 'Q1'
    exists only inside prose" and nothing derives it, which was true because
    nothing could."""

    @property
    def is_quarter_end(self) -> bool:
        return self.month % 3 == 0

    @property
    def is_year_end(self) -> bool:
        return self.month == 12

    @property
    def label(self) -> str:
        """``FY2026 Q3 P9`` — the coordinates, spelled the way a finance
        function writes them. Not minted into any fact: a fact carrying this
        would be a new fact, and a new fact shifts every id the minter hands
        out after it. Callers that want it can ask."""
        return f"FY{self.year} Q{self.quarter} P{self.month}"


def fiscal_period(period: str, start_month: int) -> FiscalPeriod:
    """Where ``YYYY-MM`` *period* sits in a fiscal year starting *start_month*.

    Pure arithmetic on the period string, no clock — the rule
    ``generators.operations.period_end`` and ``finance.previous_periods``
    already keep, and the reason replay stays byte-identical.
    """
    year, month = (int(part) for part in period.split("-"))
    if not 1 <= month <= 12:
        raise ValueError(f"{period!r} is not a YYYY-MM period; month {month} does not exist")
    if not 1 <= start_month <= 12:
        raise ValueError(f"fiscal_year_start_month {start_month} is not a month")
    # Months since the fiscal year opened, 0-11. The modulo is what makes a
    # December start work without a branch: month 1 of a year that opens in
    # December is December, and January is month 2.
    offset = (month - start_month) % 12
    return FiscalPeriod(
        # `start_month > 1` rather than a bare comparison: under a January start
        # every month satisfies `month >= start_month`, and without the guard
        # every calendar year would be labelled as the next one.
        year=year + (1 if start_month > 1 and month >= start_month else 0),
        quarter=offset // 3 + 1,
        month=offset + 1,
    )


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
    """When this company's financial year opens, 1-12.

    Stored here since the model existed and read by nothing until now — a pack
    could set it, three org generators copied it, it was written into
    ``world.json``, and no date, label or comparison anywhere depended on it.
    ``fiscal`` below is what makes it answerable: the field states the
    convention, the method applies it."""

    currency: str = "AUD"
    currency_unit: str = "thousands"
    employees_total: int = Field(ge=0)

    def fiscal(self, period: str) -> FiscalPeriod:
        """This company's fiscal coordinates for ``YYYY-MM`` *period*.

        On the company rather than on the locale because a company is the
        authority on its own year: a German subsidiary of an Australian group
        keeps the group's July year while working a German week and printing
        German figures, and a locale that decided the fiscal year would make
        that world unbuildable. The locale supplies the *default* — see
        ``locales.Locale.fiscal_year_start_month`` — and the company carries
        the answer.
        """
        return fiscal_period(period, self.fiscal_year_start_month)


class BusinessUnit(Entity):
    company_id: str
    leader_id: str
    kind: str
    formed: datetime | None = None
    dissolved: datetime | None = None
    """When the unit existed. ``None`` at either end means "outside the corpus"."""


class Employee(Entity):
    title: str
    joined: datetime | None = None
    """When this person started. ``None`` means "before the corpus begins"."""
    left: datetime | None = None
    """When they stopped. ``None`` means still here.

    A datetime rather than a date, so it compares directly with an artifact's
    ``created_at`` without a conversion at every call site. The invariant this
    exists for is that an artifact's author must have been employed on the day it
    was written — which the corpus asserted implicitly and could never check,
    because nobody ever left.
    """
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
    introduced: datetime | None = None
    retired: datetime | None = None
    """Half-open operating window. Missing bounds preserve legacy always-live estates."""


class Service(Entity):
    """A runtime service that can succeed or fail."""

    purpose: str
    owner_id: str
    system_id: str
    criticality_tier: int = Field(ge=1, le=4)
    depends_on: list[str] = Field(default_factory=list)
    introduced: datetime | None = None
    retired: datetime | None = None
    """Half-open operating window. A retired service remains available to history."""


class CostCentre(Entity):
    owner_id: str
    business_unit_id: str | None = None


class Category(Entity):
    """A merchandise category — the level a retailer actually reports margin at.

    First-class rather than a string on a fact, because a category is a noun the
    business owns: it has a unit, a buyer, and its own margin profile, and the
    reporting hierarchy runs category → unit → group.
    """

    business_unit_id: str
    buyer_id: str | None = None
    margin_profile: float = Field(ge=0.0, le=1.0)
    revenue_share: float = Field(default=0.0, ge=0.0, le=1.0)
    """Share of the parent unit's revenue. The category rows of a unit sum to 1."""


class Site(Entity):
    """A store, distribution centre, or fulfilment site."""

    business_unit_id: str
    format: str
    region: str
    opened: str | None = None
    activated_at: datetime | None = None
    closed_at: datetime | None = None
    revenue_weight: float = Field(default=0.0, ge=0.0)
    """Relative trading size. Zero for a site that holds stock but sells nothing.

    A weight rather than a share, because sites are allocated a unit's revenue
    proportionally and a share would have to be recomputed every time the estate
    changed. Distribution centres carry zero so that a store-level P&L does not
    invent turnover for a warehouse.
    """


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
    approver_id: str | None = None
    """Who signed it off, when the document is one that gets signed off.

    The corpus's documents were all authored and none of them approved, which
    is not how a company works and, more to the point, is not how a company's
    *archive* works: "who approved the March pack for Fuel and Convenience" is
    a question every real reader asks and no artifact here could answer.

    ``None`` is not an oversight and is the value for most types — a ServiceNow
    ticket has an assignee, an email thread has a sender, a republished
    calendar is issued rather than approved. Which types get a signature is
    ``planning._APPROVED`` and is a claim about what kind of document it is.

    An id rather than a name, resolved against the same roster ``author_id``
    is, because the approver is a person in this world with a function an
    access policy can read — and ``validate.approvals`` holds the pair to that:
    an approver who could not open what they signed is a signature nobody could
    have given.
    """
    triggered_by: list[str] = Field(default_factory=list)
    required_fact_ids: list[str] = Field(default_factory=list)
    size_profile: Literal["small", "medium", "long"] = "small"
    rationale: str | None = None
    revises: str | None = None
    """A new version of the *same* document, not a different one.

    Three relationships, and conflating them loses information a reader needs.
    ``supersedes`` is a different document replacing this one — last month's
    calendar by this month's. ``derived_from`` builds on without replacing, and
    both stay true. ``revises`` keeps the document's identity: an incident review
    that gains a section after review is the same review, at version two.
    """
    supersedes: str | None = None
    """The artifact this one replaces — a republished calendar, a reissued report.

    Declared at planning time rather than discovered at render time, because
    whether a document replaces another is a decision the planner makes and a
    renderer has no way to infer.
    """
    derived_from: list[str] = Field(default_factory=list)
    """Artifacts this one builds on without replacing. A second incident review
    citing the first is derived from it; neither supersedes the other, and both
    remain current."""
    restates: str | None = None
    """A formal correction of a document that cannot itself be changed.

    The fourth relationship, and the one regulated industries force
    (build-order §7): a filed return is immutable, so a correction is not a new
    version (``revises``), not a replacement (``supersedes``), and not a
    derivative (``derived_from``) — it is a *restatement*. The distinguishing
    rule is what happens to the original: ``revises`` and ``supersedes`` retire
    their predecessor, a restatement leaves it standing, because a filing that
    vanished from the record would defeat the reason filings are immutable.
    Both documents remain current; the restatement says which figures moved and
    why, and the validator holds the pair to that contract."""

    @model_validator(mode="after")
    def _one_relationship_per_predecessor(self) -> ArtifactIntent:
        if self.restates and (self.revises or self.supersedes):
            raise ValueError(
                f"{self.id}: restates is exclusive with revises/supersedes —"
                " a correction that also retired the original would be an edit"
                " of an immutable filing wearing a different name"
            )
        return self


class FormulaKind(StrEnum):
    """How a computed cell is derived.

    Which cells are computed, and from what, is a *semantic* fact the planner
    knows — so it is declared in the IR rather than inferred by a renderer. XLSX
    emits ``=SUM(C4:C6)``; Markdown emits the literal; both agree because both
    read the same declaration.
    """

    SUM = "sum"
    """Sum of the named rows, within this cell's own column."""

    DIFFERENCE = "difference"
    """First operand column minus the second, within this cell's own row."""

    RATIO_PCT = "ratio_pct"
    """First operand column divided by the second, as a percentage."""

    REFERENCE = "reference"
    """A single cell elsewhere, addressed ``table:row:column``."""


class MagnitudeBand(StrEnum):
    """Where a cell's value sits within its column's range — declared exactly
    the way `FormulaKind` declares a computation: a *semantic* fact about the
    value, not a rendering decision. ``finance.heatmap``'s whole purpose is "a
    grid of values shaded by magnitude", and until this existed there was
    nothing in the IR for a generator to shade *by* — a renderer had no choice
    but to draw the table underneath it and stop, which is exactly the
    collapse this field exists to end.

    A renderer picks the colour, the marker, or the shading; this only says
    which of five positions the value occupies in its own column, so a
    Markdown render and an XLSX conditional-format agree about *which* cells
    are extreme without either inventing the other's spelling of "extreme".
    Five rather than three: three bands (low/mid/high) collapse the two
    interesting edges — "clearly above average" and "clearly below" — into the
    same middle bucket as "exactly average", which is the one distinction a
    heatmap is drawn to show.
    """

    LOW = "low"
    BELOW_AVERAGE = "below_average"
    AVERAGE = "average"
    ABOVE_AVERAGE = "above_average"
    HIGH = "high"


class Cell(Model):
    """One value in a table.

    Always carries a literal ``value``, even when it is computed. That is what
    lets a renderer without formula support stay consistent with one that has it,
    and it is what the reconciliation check compares against.
    """

    value: float | str | None = None
    fact_id: str | None = None
    formula: FormulaKind | None = None
    operands: list[str] = Field(default_factory=list)
    band: MagnitudeBand | None = None
    """Where this value sits in its column's range — see `MagnitudeBand`.

    ``None`` means no generator has computed a range to place this cell in,
    which is every cell in every corpus this repository ships today; it does
    not mean "average" and a renderer must not treat it as such. Additive and
    silent by construction: a table nobody ever bands renders exactly as it
    always has, because nothing reads this field until it is set.
    """

    @model_validator(mode="after")
    def _formula_needs_operands(self) -> Cell:
        if self.formula is not None and not self.operands:
            raise ValueError(f"a {self.formula.value} cell must name its operands")
        return self


class Column(Model):
    """A table column."""

    key: str
    label: str
    number_format: str | None = None


class Row(Model):
    """A table row. ``emphasis`` marks totals."""

    key: str
    label: str
    cells: dict[str, Cell] = Field(default_factory=dict)
    emphasis: bool = False


class ChartKind(StrEnum):
    """How a chart presents its series."""

    COLUMN = "column"
    """Vertical bars. Comparing a handful of things at one moment."""
    BAR = "bar"
    """Horizontal bars. Many categories with long labels — a category ranking."""
    LINE = "line"
    """A measure over ordered periods. Only meaningful when the axis is time."""
    PIE = "pie"
    """Composition of a single total. One series only."""


class Chart(Model):
    """A chart, declared over a table that is already resolved.

    Declared rather than drawn, for the same reason a formula is declared rather
    than computed: a workbook, a document and a deck all show "revenue by
    division", and if each renderer chose its own rows and series they would be
    three charts of three different things wearing one title. The IR says which
    table, which rows, which series; a renderer decides only how to draw it.

    A chart never introduces a number. Every value it plots is a cell that is
    already in the table beside it, which is why a reader can check the chart
    against the figures without leaving the page.
    """

    key: str
    title: str
    kind: ChartKind
    table: str
    """Key of the table this chart reads. Must be a table in the same artifact."""
    series: list[str] = Field(default_factory=list)
    """Column keys to plot, in order."""
    rows: list[str] = Field(default_factory=list)
    """Row keys to plot. Empty means every row that is not a subtotal — a chart
    that included the subtotals would double every bar."""
    by_row: bool = False
    """Whether each plotted *row* is a series, with the columns as the axis.

    A P&L chart wants one series per measure across divisions. A trend wants one
    line per division across months — the same table read the other way round.
    Which one is meant is a semantic choice the planner makes, not something a
    renderer can infer: a line chart drawn the wrong way round is twelve lines of
    one month each, and it renders perfectly.
    """
    category_axis: str = ""
    value_axis: str = ""
    note: str | None = None


class Table(Model):
    """A resolved table: every value present, every computation declared."""

    key: str
    title: str
    columns: list[Column] = Field(default_factory=list)
    rows: list[Row] = Field(default_factory=list)
    note: str | None = None

    def column(self, key: str) -> Column | None:
        for column in self.columns:
            if column.key == key:
                return column
        return None

    def row(self, key: str) -> Row | None:
        for row in self.rows:
            if row.key == key:
                return row
        return None


class FlowNode(Model):
    """One step, trigger, control, or effect in a declared `FlowDiagram`.

    Carries a label, never a figure: the constraint every primitive in this
    file is held to — see `Cell.band` — applies here identically. A node
    names a thing that happened or should happen; any number attached to it is
    reached through ``fact_id`` and resolved by a renderer exactly as a
    section's own ``{{fact:ID}}`` is, never typed into ``label`` itself.
    """

    key: str
    label: str
    fact_id: str | None = None
    """The fact this node stands for, if any — a renderer may resolve it into
    the node's label the same way `narrative.references.substitute` resolves
    a `{{fact:ID}}` marker in prose. ``None`` for a node that names a step or a
    control rather than a measured thing."""


class FlowEdge(Model):
    """One connection from *source* to *target*, in a declared `FlowDiagram`.

    ``label`` names the relationship — "triggers", "should have caught this",
    "confirmed by" — the vocabulary `ops.causal_chain`'s own purpose text
    already uses in prose. Free text rather than a closed enum, for the same
    reason `Table.note` and `Chart.note` are: a causal chain's edges are as
    varied as the incidents they describe, and a fixed vocabulary here would
    either grow without bound or force an edge into a label that does not fit.
    """

    source: str
    """A `FlowNode.key` in the same diagram."""
    target: str
    """A `FlowNode.key` in the same diagram."""
    label: str = ""


class FlowDiagram(Model):
    """A declared shape — named nodes, and the edges between them — for a
    section that is a sequence of steps rather than a table of figures.

    Exists for `ops.process_flow` ("the steps a system takes when it works")
    and `ops.causal_chain` ("from trigger to effect, naming the control that
    should have caught it"): the registry's own purpose text for both already
    describes a graph, and before this there was nothing in the IR to hold
    one — a renderer had to fall back to prose or a table that flattened the
    shape away. A renderer with no drawing surface still has enough here to
    print an ordered chain; one with a canvas can lay out a real diagram —
    the same split `Chart` already makes between the data it declares and the
    picture a renderer decides to draw of it.
    """

    nodes: list[FlowNode] = Field(default_factory=list)
    edges: list[FlowEdge] = Field(default_factory=list)

    @model_validator(mode="after")
    def _edges_reference_declared_nodes(self) -> FlowDiagram:
        keys = {node.key for node in self.nodes}
        for edge in self.edges:
            if edge.source not in keys or edge.target not in keys:
                raise ValueError(
                    f"edge {edge.source!r} -> {edge.target!r} names a node this"
                    " flow never declared"
                )
        return self


class Quotation(Model):
    """One line pulled out and set apart from the surrounding prose.

    For `editorial.pull_quote` ("carrying an emphasis the surrounding
    paragraph would otherwise bury") and `editorial.callout` ("the one or two
    things to watch") — both currently spelled, if they compose at all, as a
    plain paragraph indistinguishable from the body text around them.

    ``text`` may carry ``{{fact:ID}}`` references exactly as
    `ArtifactSection.body` does, resolved by the identical
    `narrative.references.substitute` call, so a pulled quotation and the
    paragraph it was drawn from can never disagree about a figure — there is
    only ever the one resolution path.
    """

    text: str
    attribution: str | None = None
    fact_ids: list[str] = Field(default_factory=list)
    """Facts this quotation rests on, beyond any resolved inline via
    ``{{fact:ID}}`` — the same idea `ArtifactSection.fact_ids` carries for a
    whole section, kept separate because a quotation is its own citable unit,
    not a restatement of the section's citations."""


class ArtifactSection(Model):
    """One resolved section of an artifact.

    ``body`` is ``None`` while a section is awaiting prose. That is the ordinary
    state before the narrative compiler exists: structure and tables are resolved
    first, so prose is later written against data that already exists.
    """

    heading: str
    body: str | None = None
    table: Table | None = None
    charts: list[Chart] = Field(default_factory=list)
    """Charts over this section's table. A view of data already present, never a
    source of data of its own."""
    flow: FlowDiagram | None = None
    """A declared node/edge shape for this section — see `FlowDiagram`.

    Additive and silent: no generator in this repository sets it yet, so every
    existing section keeps rendering as prose, then a table, then "awaiting
    narrative" exactly as it always has. Set only by a generator that has
    actually decided the shape, never inferred from a table or from prose.
    """
    quote: Quotation | None = None
    """A pulled-out line for this section — see `Quotation`. Same rule as
    ``flow``: absent changes nothing, present is a fourth content primitive a
    renderer may present instead of falling back to prose or a table."""
    fact_ids: list[str] = Field(default_factory=list)
    purpose: str = ""
    """What this section has to accomplish, and for whom.

    A heading and a bag of figures is enough to produce a list. It is not enough
    to produce an argument, and the difference between a list and an argument is
    most of what separates real enterprise prose from generated prose. So the
    outline states the section's job, and the narrative request carries it.
    """
    semantic_role: str = ""
    """Which component family can present this section — ``evidence``,
    ``chronology``, ``decision``.

    On the IR rather than on a parallel structure beside it, because the role is
    a property of what the section *is*, and it is known at outline time. The
    artifact compiler originally carried this on its own plan type built from the
    intent, which put a second format-independent layer above the one that
    already existed and left the two to be kept in step by hand.

    Empty means "unclassified", and a composer falls back to inferring it from
    the heading. That is a migration affordance, not the design: an outline that
    states the role is telling the truth about itself, and one that leaves it
    blank is asking a heuristic to guess.
    """
    optional: bool = False
    """Droppable when the artifact is over budget, rather than truncated.

    A planning decision, not a rendering one: it says this section is genuinely
    supporting material. Dropping a required section produces a document missing
    part of its argument, which is a defect rather than editing.
    """
    hidden: bool = False
    """Present in the artifact but not part of its readable surface."""

    @property
    def awaiting_prose(self) -> bool:
        """Whether this section still needs narrative.

        A ``table`` exempts a section and a ``flow`` deliberately does not, and
        the difference is what each one *is*. A table is the content — the
        divisional summary is a grid of figures with a note, and prose beside it
        would restate the grid. A flow is a *diagram of* an argument, not the
        argument: an RCA's root-cause section is the conclusion of the document,
        and a reader who gets seven boxes and an arrow where the explanation
        should be has been shown the shape of a finding without being told what
        it was.

        Found by rendering rather than by reasoning. Extending the exemption to
        ``flow`` by analogy with ``table`` was the obvious reading, and its only
        symptom was that declaring a causal chain silently withdrew the section
        from ``narrate requests`` — the prose was never written, nothing
        reported a problem, and the rendered RCA showed a bare arrow chain under
        "Root cause".

        ``quote`` keeps the exemption for the reason ``table`` has it: a pull
        quote is the content of its section, and narrating around it would
        produce a paragraph whose job is to introduce a sentence.
        """
        return self.body is None and self.table is None and self.quote is None


class ArtifactIR(Model):
    """Format-independent artifact content.

    Renderers consume this. It knows nothing about XLSX or Confluence, which is
    what lets a renderer be added without touching the world model.
    """

    id: str
    intent_id: str
    title: str
    subtitle: str | None = None
    sections: list[ArtifactSection] = Field(default_factory=list)
    metadata: dict[str, str] = Field(default_factory=dict)

    def tables(self) -> list[Table]:
        """Every table in this artifact, in order."""
        return [s.table for s in self.sections if s.table is not None]

    def charts(self) -> list[Chart]:
        """Every chart in this artifact, in order."""
        return [chart for section in self.sections for chart in section.charts]

    def fact_ids(self) -> list[str]:
        """Every fact this artifact rests on, deduplicated, order preserved."""
        seen: dict[str, None] = {}
        for section in self.sections:
            for fact_id in section.fact_ids:
                seen.setdefault(fact_id, None)
            if section.table:
                for row in section.table.rows:
                    for cell in row.cells.values():
                        if cell.fact_id:
                            seen.setdefault(cell.fact_id, None)
            if section.quote:
                # A quotation is its own citable unit — see `Quotation.fact_ids`
                # — so its facts join the artifact's total the same way a
                # table cell's do, two lines up. No corpus in this repository
                # sets `quote` yet, so this is additive: an empty ``quote``
                # (the only value that exists today) contributes nothing.
                for fact_id in section.quote.fact_ids:
                    seen.setdefault(fact_id, None)
            if section.flow:
                for node in section.flow.nodes:
                    if node.fact_id:
                        seen.setdefault(node.fact_id, None)
        return list(seen)


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
    approver_id: str | None = None
    """Who signed it off. ``None`` for a type that is not signed off — see
    ``ArtifactIntent.approver_id``, which this copies verbatim so the manifest
    can answer "who approved this" without reopening the file."""
    audience: str
    created_at: datetime
    authority: Authority
    lifecycle: Lifecycle
    supporting_fact_ids: list[str] = Field(default_factory=list)
    event_ids: list[str] = Field(default_factory=list)
    lore_ids: list[str] = Field(default_factory=list)
    derived_from: list[str] = Field(default_factory=list)
    supersedes: str | None = None
    revises: str | None = None
    """The earlier version of this same document. See ``ArtifactIntent.revises``."""
    restates: str | None = None
    """The immutable filing this document formally corrects, which stays on the
    record. See ``ArtifactIntent.restates``."""
    access_policy_id: str | None = None
    recipe: str | None = None
    version: int = 1
    """Which revision this is. Incremented along a ``revises`` chain, and left at
    one for a document that was never reissued."""


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
