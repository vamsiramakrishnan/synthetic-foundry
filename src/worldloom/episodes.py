"""Episodes as authored data — a schema, a loader, and a lint.

An episode is a declarative specification of a scenario: which facts get minted,
with what invariants; which events occur; which artifacts are produced; which
evaluation cases the corpus answers; and which facts carry forward to the next
period.

The grammar is pack-carried, like doctypes, so it rides the recipe and replays
deterministically. Three commitments:

1. **Declaring a fact kind means declaring its invariants.** Sums-to, supersedes-prior,
   holds-at, carries-forward-as, reconciles-against — checks are derived from the
   declaration, never hand-written per kind. A kind with no invariant is lint-refused.

2. **Carry-forward as declared slots.** This period's value is resolved from the prior
   period's fact by a declared rule (sum, reuse, derive), and the validator checks
   the relationship holds.

3. **Structured and unstructured per event.** Tables compile from facts (via `outline()`),
   sections go to `narrate requests` — the spec declares which of each.

The proof obligation: four existing episodes re-expressed in this grammar, building
byte-identical corpora. Banking's QuarterlyCapitalReturn is the first; what cannot be
expressed stays Python and the grammar documents why.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field as _dataclass_field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import validate as validate_module
from .models import Authority, CanonicalFact, EnterpriseEvent, Quantity
from .models import ArtifactIntent as ArtifactIntentModel

if TYPE_CHECKING:  # pragma: no cover
    from .ids import Minter
    from .rng import Rng
    from .world import World

# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------


class Model(BaseModel):
    """Base for every episode grammar model."""

    model_config = ConfigDict(frozen=True, extra="forbid")


class Invariant(Model):
    """A constraint that facts of a kind must satisfy."""

    kind: Literal[
        "sums-to", "supersedes-prior", "holds-at", "carries-forward-as",
        "reconciles-against", "precedes-event", "standing", "never-superseded"
    ]
    """The invariant type. Determines how the validator checks it.

    - **sums-to**: This kind (or scope) must equal the sum of specified children.
      ``operands`` names the breakdown; subjects must have a common parent.
    - **supersedes-prior**: A fact of this kind with ``supersedes=X`` must have
      a ``valid_from`` after X's ``valid_to`` (or after the episode's start if X
      has no expiry).
    - **holds-at**: Every fact must have a ``valid_from`` and ``valid_to`` that
      bracket its use in any document. Checked by the temporal validator.
    - **carries-forward-as**: This kind in period N derives this period N+1 fact
      by the declared rule. Namespace and rule given in ``operands``.
    - **reconciles-against**: This fact must sum to the prior-period balance plus
      movements. ``operands`` names the opening balance kind and movement kind.
    - **precedes-event**: This kind must be valid before the event that cites it.
      Checked by the temporal validator.
    - **standing**: Carries no period; minted once per subject and reused by
      later periods rather than re-minted (a policy, a regulatory floor).
    - **never-superseded**: The permanent record — never closed, never
      superseded (banking's as-filed ratio, insurance's booked total). The
      vocabulary matches ``factkinds.INVARIANT_HEADS`` exactly, so a kind's
      registry declaration and a process spec's cannot drift apart.
    """

    operands: list[str] = Field(default_factory=list)
    """Names of operands for the invariant — child kinds (sums-to), related facts
    (reconciles-against), or carry-forward rules (carries-forward-as)."""

    detail: str = Field(default="", min_length=0)
    """Explanation for documentation — why this invariant matters."""


class FactKindSpec(Model):
    """Declaration of a fact kind and its rules."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    """The fact kind name, in the format ``domain.metric`` or ``domain.category.metric``."""

    authority: Authority = Authority.SYSTEM_OF_RECORD
    """Default authority for facts of this kind. May be overridden by the generator."""

    value_type: Literal["money", "measure", "text", "date", "percent"]
    """The type of value this kind carries."""

    period_scope: Literal["standing", "period-keyed", "period-scoped"] = "period-keyed"
    """Whether this kind belongs to a period or stands alone.

    - **standing**: No period. Minted once, reused across periods (e.g., policy).
    - **period-keyed**: One fact per period. Every period has exactly one (e.g., monthly accrual).
    - **period-scoped**: Optional per period. A period may have none (e.g., incident facts).
    """

    invariants: list[Invariant] = Field(default_factory=list, min_length=1)
    """The rules this kind must satisfy. Empty list is lint-refused."""

    subject_type: Literal["company", "unit", "category", "person", "system", "any"] = "company"
    """What entity this fact describes — determines scoping in artifact outlines."""

    # -- how the runner mints a value for this kind. At most one of
    # ``parameter``, ``derive``, ``amount``, ``text`` decides; the lint names a
    # spec that sets none for a kind an event actually mints.

    parameter: str = ""
    """A ``parameters.py`` span this kind's value is drawn from (the level+noise
    primitive). The draw arrives on a stream named for the kind — which is also
    why an authored kind can never reproduce a generator's own figures: the
    generator's stream labels are its private identity, not data."""

    scale: float = 1.0
    """Multiplier applied to the draw, for spans stated in multiples
    (``capital.rwa.filed_hundreds`` counts hundreds; the ``× 100`` was call-site
    arithmetic and is now declared beside the kind that needs it)."""

    amount: float | None = None
    """An authored constant (a standard's floor, a zero delay) — for values that
    are commitments of the fiction, not draws from physics."""

    text: str = ""
    """The authored statement for a text fact. May carry ``{period}``, ``{at}``
    (the minting event's timestamp, ISO), and ``{bd:N}`` (the Nth business day
    after period end, ISO date). Per-occurrence overrides live on the event's
    ``fact_texts``, because a status chain says a different thing each time."""

    derive: str = ""
    """A derivation from kinds already minted, in a closed vocabulary:
    ``pct_of(K)`` (this kind's ``parameter`` drawn as a percent of K),
    ``ratio_pct(A, B)`` (A over B as a percentage, two decimals, pair-aware),
    ``initial(K)`` (the pre-correction half of K's supersession pair),
    ``supersession_delta(K)`` (corrected minus initial),
    ``bps_delta(K)`` (initial minus corrected, in basis points),
    ``at_rate(Q, R)`` (quantity Q priced at per-unit rate R, published in the
    money unit's thousands to two decimals — the three-way match's one line of
    arithmetic, ``procurement_match._money``'s rounding exactly),
    ``percent_of(A, P)`` (amount A at the already-minted percentage kind P —
    unlike ``pct_of``, nothing is drawn: a delegation of authority is a stated
    policy applied to a stated order value),
    ``multiple_of(K)`` (K times a factor drawn from this kind's ``parameter`` —
    how a variance is sized as a multiple of a tolerance, or split by a drawn
    fraction),
    ``plus(A, B)`` / ``minus(A, B)`` (two decimals — the reconciliation
    identities the procurement check group recomputes),
    ``units_of(V, R)`` (the whole units a value V represents at rate R),
    ``prior(K)`` (the prior period's value of K, resolved by a declared
    ``sum``/``derive`` carry-forward; zero in a world's first period, because
    "nothing was outstanding" is a claim, not an absence).
    Closed for the invariant vocabulary's reason: a derivation the validator
    cannot recompute is a figure nothing checks."""

    unit: str = ""
    """The quantity's unit. Empty means: the archetype's own money unit for
    ``money`` kinds, ``pct`` for ``percent`` kinds — the same defaulting
    ``regulatory.generate`` applies."""

    subject_role: str = ""
    """The role key (``world._roles``) whose id is this fact's subject — and,
    for a multi-subject kind with a supersession pair, the one subject the
    correction lands on. Empty means the company, or every enumerable subject
    for ``category``/``unit`` kinds."""

    source_role: str = ""
    """The role key of the ``source_system`` recorded on the fact."""

    series_days: int = 0
    """When positive, this kind is a business-day series (the series primitive):
    one fact per day, chained by supersession with exact validity handover —
    the shape the liquidity cadence check walks."""

    series_start_bd: int = 0
    """Which business day after period end the series opens on."""

    authorities: list[Authority] = Field(default_factory=list)
    """Authority per successive occurrence, for kinds whose epistemic standing
    moves (an initial hypothesis is CONFIRMED away). Empty means ``authority``
    every time."""


class EventSpec(Model):
    """Declaration of an event that can occur in an episode."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    """The event kind, in the format ``domain.event``."""

    when: Literal["start", "before_incident", "incident", "after_incident", "end"]
    """Relative timing in the episode. Used by generators to determine when to fire."""

    summary: str = Field(min_length=1)
    """The event summary prose (from episode_text, overrideable by pack)."""

    fact_keys: list[str] = Field(default_factory=list)
    """The fact *kinds* this event mints, in mint order. An event naming a kind
    the episode does not declare is lint-refused — the finding that caught this
    module's own first authored spec citing two invented kinds."""

    detail: str = Field(default="", min_length=0)
    """Why this event occurs in the episode."""

    # -- placement and linkage, so an authored event can actually be minted.
    # Timing is calendar arithmetic on the period string — a business-day
    # offset and a time of day are *data* about the episode; only the incident
    # tempo (five cumulative interval draws) is physics, and an authored spec
    # states literals where the generator draws (a documented divergence, not
    # a silent one).

    business_day: int = 1
    """Which business day after the anchor this event occurs on."""

    anchor: Literal["period_end", "prior_period_end"] = "period_end"
    """Which period end ``business_day`` counts from.

    ``period_end`` is the end of the episode's own period — where a close, a
    filing, or anything after the books shut belongs. ``prior_period_end`` is
    the end of the period *before*, which is how an event lands **inside** the
    month: the procurement cycle raises its order on the 3rd working day of the
    month and receipts the delivery on the 15th, and counting those from the
    month's own end would push the whole operational half of the cycle into the
    next month. The step honours the spec's cadence (one month, three, twelve),
    so a quarterly episode's in-period events count from the previous quarter's
    end. Defaulted to ``period_end`` so every spec authored before this field
    existed replays byte-identically."""

    hour: int = 9
    minute: int = 0

    caused_by: str = ""
    """The earlier event kind this one follows from. Resolved to the minted
    event's id; naming a later or undeclared event is refused at run."""

    actors: list[str] = Field(default_factory=list)
    """Role keys of the people acting, resolved through ``world._roles``."""

    services: list[str] = Field(default_factory=list)
    """Role keys of the services involved."""

    systems: list[str] = Field(default_factory=list)
    """Role keys of the systems involved."""

    units: list[str] = Field(default_factory=list)
    """Role keys of the business units involved."""

    fact_texts: dict[str, str] = Field(default_factory=dict)
    """Per-occurrence text overrides, by fact kind — how a status chain says
    ``filed`` at one event and ``restated`` at the next with one declared kind."""


class ArtifactIntentSpec(Model):
    """Declaration of an artifact intent — the decision to file a document."""

    artifact_type: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The document type (e.g., ``"status_update"``, ``"capital_return_workbook"``)."""

    author_role: str = Field(min_length=1)
    """The role that authors this artifact."""

    audience: str = Field(min_length=1)
    """Who may read it (e.g., ``"finance"``, ``"executive_committee"``)."""

    required_facts: list[str] = Field(default_factory=list)
    """Which fact kinds must be provided to this artifact for it to compile."""

    size: Literal["small", "medium", "long"] = "medium"
    """Expected prose length."""

    structured: bool = False
    """Whether this artifact has structured tables (compiled from facts)."""

    unstructured: bool = True
    """Whether this artifact has unstructured prose sections for narration."""

    rationale: str = Field(min_length=1)
    """Why the company files this artifact in this episode."""

    triggered_by_events: list[str] = Field(default_factory=list)
    """Event kinds this artifact is filed in response to. Resolved to event
    ids at run; an undeclared kind is lint-refused."""


class CarryForwardSpec(Model):
    """A fact that carries forward from one period to the next."""

    from_kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    """The fact kind in the prior period."""

    to_kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    """The fact kind minted this period."""

    rule: Literal["reuse", "sum", "derive"]
    """How the next period's fact is determined.

    - **reuse**: The same fact ID is carried (both periods reference one canonical fact).
    - **sum**: Arithmetic across periods (e.g., opening balance + movements).
    - **derive**: A generator function computes the value from prior facts.
    """

    detail: str = Field(default="", min_length=0)
    """Explanation for the carry-forward."""


class PhaseSpec(Model):
    """One phase of an episode (detection, investigation, control, resolution)."""

    name: str = Field(pattern=r"^[a-z_]*$")
    """Phase name: ``detection``, ``investigation``, ``control``, ``resolution``."""

    fact_kinds: list[str] = Field(default_factory=list)
    """Which fact kinds are minted in this phase."""

    events: list[str] = Field(default_factory=list)
    """Which event kinds fire in this phase."""


class RoleSlotSpec(Model):
    """One ordered role slot a process declares.

    Ordering is the one thing participation cannot derive (docs/next-phase-plan.md,
    "Who authors a process"): the join says *who is in* a process, but not who
    prepares before who challenges before who approves. So a process declares
    slots — its own vocabulary, in its own order — and a LOB binds its role keys
    to them (``lob.SlotBinding``). The slot names are spec-defined on purpose:
    ``preparer``/``challenger``/``approver`` is the shape the settled design
    names, but a recruitment drive's ``screener``/``interviewer``/``signer`` is
    just as much a process, and a hardcoded vocabulary here would make every
    new process a core edit.
    """

    slot: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    """The slot's name — the process's own word for the seat."""

    required: bool = True
    """Whether a company running this process must bind a role to this slot.
    ``lob.lint_bindings`` refuses an unbound required slot; an optional slot
    (an observer, a second challenger in larger firms) may stay empty."""

    purpose: str = Field(default="", min_length=0)
    """What the seat does, in a sentence — documentation for the binder."""


class EpisodeSpec(Model):
    """Complete declaration of an episode."""

    name: str = Field(pattern=r"^[A-Z][a-zA-Z0-9]*$")
    """Episode name: ``MonthEndClose``, ``QuarterlyCapitalReturn``, etc."""

    domain: str = Field(pattern=r"^[a-z_]*$")
    """Domain: ``retail``, ``banking``, ``insurance``, ``procurement``."""

    period: Literal["month", "quarter", "year"]
    """The period this episode runs over."""

    fact_kinds: list[FactKindSpec] = Field(min_length=1)
    """Every fact kind this episode mints."""

    events: list[EventSpec] = Field(default_factory=list)
    """Events that can occur."""

    artifacts: list[ArtifactIntentSpec] = Field(default_factory=list)
    """Artifact intents that can be filed."""

    carry_forward: list[CarryForwardSpec] = Field(default_factory=list)
    """Facts that carry from one period to the next."""

    phases: list[PhaseSpec] = Field(default_factory=list)
    """The phases this episode goes through."""

    role_slots: list[RoleSlotSpec] = Field(default_factory=list)
    """The ordered seats this process needs filled — the process's vocabulary.
    Declaration order is the order the work moves: preparer before challenger
    before approver. Binding a company's roles to these is the LOB's half
    (``lob.SlotBinding``), never declared here — a process spec that named a
    company's role keys would only run at one company."""

    detail: str = Field(default="", min_length=0)
    """General notes about the episode."""

    @field_validator("fact_kinds")
    @classmethod
    def _no_duplicate_kinds(cls, kinds: list[FactKindSpec]) -> list[FactKindSpec]:
        seen = set()
        for kind in kinds:
            if kind.kind in seen:
                raise ValueError(f"duplicate fact kind: {kind.kind}")
            seen.add(kind.kind)
        return kinds

    @field_validator("events")
    @classmethod
    def _no_duplicate_events(cls, events: list[EventSpec]) -> list[EventSpec]:
        seen = set()
        for event in events:
            if event.kind in seen:
                raise ValueError(f"duplicate event kind: {event.kind}")
            seen.add(event.kind)
        return events

    @field_validator("role_slots")
    @classmethod
    def _no_duplicate_slots(cls, slots: list[RoleSlotSpec]) -> list[RoleSlotSpec]:
        # Declaration order *is* the ordering, so a duplicate is not merely
        # redundant — it makes "where in the sequence does this seat sit"
        # ambiguous, which is the one question slots exist to answer.
        seen = set()
        for slot in slots:
            if slot.slot in seen:
                raise ValueError(f"duplicate role slot: {slot.slot}")
            seen.add(slot.slot)
        return slots


class Episodes(Model):
    """A file of episode specs. Also the shape ``Pack.episodes`` holds."""

    episodes: list[EpisodeSpec] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load(source: str | Path | dict[str, Any] | list[Any]) -> tuple[EpisodeSpec, ...]:
    """Load and validate episode specs from a path, JSON text, or parsed data.

    Accepts a bare list as well as an ``{"episodes": [...]}`` document, because
    the same shape is both a file of its own and a field inside a pack.
    """
    if isinstance(source, (str, Path)) and Path(str(source)).exists():
        source = json.loads(Path(source).read_text(encoding="utf-8"))
    elif isinstance(source, str):
        source = json.loads(source)
    if isinstance(source, list):
        source = {"episodes": source}
    return tuple(Episodes.model_validate(source).episodes)


#: Every declared episode spec this process has loaded, by name.
_LOADED: dict[str, EpisodeSpec] = {}


def loaded() -> dict[str, EpisodeSpec]:
    """The episode specs this process holds. A copy; the registry is not a surface."""
    return dict(_LOADED)


def install(specs: Sequence[EpisodeSpec]) -> None:
    """Register *specs* into the grammar.

    Called at build time when a pack carries episodes. Refuses a name that is
    already declared and differs from the incoming spec.
    """
    for spec in specs:
        existing = _LOADED.get(spec.name)
        if existing is not None and existing != spec:
            raise ValueError(
                f"episode {spec.name!r} is already loaded with different content — "
                "an episode spec may not be redefined. Check the pack and any "
                "installed domain modules."
            )
        _LOADED[spec.name] = spec


# ---------------------------------------------------------------------------
# The lint
# ---------------------------------------------------------------------------


def lint(specs: Iterable[EpisodeSpec], *, base: str = "") -> list[str]:
    """Findings an author should read before building.

    Same contract as ``doctypes.lint``: a list of strings naming divergences
    between what was authored and what the engine will do. Nothing raises.
    """
    from . import domains, factkinds, parameters

    findings: list[str] = []
    domain = domains.by_name(base) if base else None

    seen_names: set[str] = set()
    for index, spec in enumerate(specs):
        where = f"episodes[{index}] ({spec.name})"

        # -- the name ---------------------------------------------------
        if spec.name in seen_names:
            findings.append(
                f"{where}: {spec.name!r} appears twice — the second spec wins "
                "silently and the first is ignored."
            )
        seen_names.add(spec.name)

        # -- fact kinds -------------------------------------------------
        if not spec.fact_kinds:
            findings.append(
                f"{where}: declares no fact kinds. An episode that mints nothing "
                "produces no facts for artifacts to cite and no events to narrate."
            )

        declared_events = [event.kind for event in spec.events]
        for fk_index, fk in enumerate(spec.fact_kinds):
            fk_where = f"{where}.fact_kinds[{fk_index}] ({fk.kind})"

            # The process-global registry is the cross-module truth about a
            # kind. Reusing a kind another domain registered is established
            # practice — banking mints retail's `close.*` verbatim — so reuse
            # is not a finding. What *is* one: declaring invariants the
            # registry does not hold for that kind, because then the spec's
            # derived checks and the registry's documented rules disagree
            # about what the kind means, and only one of them can be right.
            registered = factkinds.get(fk.kind)
            if registered is not None:
                registered_heads = {
                    factkinds.parse_invariant(inv)[0] for inv in registered.invariants
                }
                extra = sorted(
                    {inv.kind for inv in fk.invariants} - registered_heads
                )
                if extra:
                    findings.append(
                        f"{fk_where}: declares invariant(s) {extra} that the"
                        f" fact-kind registry does not hold for this kind"
                        f" (registered by {registered.domain!r} as"
                        f" {sorted(registered_heads)}). Either the registry"
                        " declaration is incomplete — fix it where the kind is"
                        " registered — or the spec claims a rule the kind's"
                        " generator does not keep."
                    )

            if fk.parameter:
                if fk.parameter not in parameters.DEFAULTS:
                    findings.append(
                        f"{fk_where}: parameter {fk.parameter!r} is not in the"
                        " physics registry — the draw would raise at run. See"
                        " `worldloom pack params`."
                    )

            if fk.derive:
                head, _, rest = fk.derive.partition("(")
                operand_kinds = [p.strip() for p in rest.rstrip(")").split(",") if p.strip()]
                if head not in ("pct_of", "ratio_pct", "initial",
                                "supersession_delta", "bps_delta",
                                "at_rate", "percent_of", "multiple_of",
                                "plus", "minus", "units_of", "prior"):
                    findings.append(
                        f"{fk_where}: derive {fk.derive!r} is not in the closed"
                        " derivation vocabulary."
                    )
                for operand in operand_kinds:
                    if operand not in {k.kind for k in spec.fact_kinds}:
                        findings.append(
                            f"{fk_where}: derive operand {operand!r} is not a"
                            " declared fact kind of this episode."
                        )
                if head in ("pct_of", "multiple_of") and not fk.parameter:
                    findings.append(
                        f"{fk_where}: derive {head} draws its factor from this"
                        " kind's `parameter`, and none is declared — the draw"
                        " would have no span."
                    )
                if head == "prior" and operand_kinds and not any(
                    cf.rule in ("sum", "derive") and cf.from_kind == operand_kinds[0]
                    for cf in spec.carry_forward
                ):
                    findings.append(
                        f"{fk_where}: derive prior({operand_kinds[0]}) reads a"
                        " prior period's value, and no sum/derive carry-forward"
                        " declares that slot — the runner only resolves what a"
                        " declaration asks it to."
                    )

            if not fk.invariants:
                findings.append(
                    f"{fk_where}: declares no invariants. The validator will have "
                    "no rules to check this kind against; a kind that satisfies "
                    "nothing is declared but never validated, and a corpus carrying "
                    "it may violate unwritten expectations."
                )

            for inv_index, inv in enumerate(fk.invariants):
                inv_where = f"{fk_where}.invariants[{inv_index}] ({inv.kind})"

                if inv.kind in ("sums-to", "reconciles-against") and not inv.operands:
                    findings.append(
                        f"{inv_where}: {inv.kind} invariant requires operands "
                        "(child kinds or related kinds) but none are given."
                    )

                if inv.kind == "carries-forward-as" and not inv.operands:
                    findings.append(
                        f"{inv_where}: carries-forward-as requires a carry-forward "
                        "declaration (namespace and rule) in operands, but none given."
                    )

        # -- events --------------------------------------------------
        for ev_index, event in enumerate(spec.events):
            ev_where = f"{where}.events[{ev_index}] ({event.kind})"

            unknown_facts = [
                fk for fk in event.fact_keys
                if fk not in {fk_spec.kind for fk_spec in spec.fact_kinds}
            ]
            if unknown_facts:
                findings.append(
                    f"{ev_where}: fact_keys {unknown_facts} — not declared in this "
                    "episode's fact_kinds. The event will reference facts that the "
                    "generator does not produce."
                )

            if event.caused_by and event.caused_by not in declared_events[:ev_index]:
                findings.append(
                    f"{ev_where}: caused_by {event.caused_by!r} is not an earlier"
                    " declared event — causality may only point backwards."
                )

        # -- artifacts ------------------------------------------------
        for art_index, artifact in enumerate(spec.artifacts):
            art_where = f"{where}.artifacts[{art_index}] ({artifact.artifact_type})"

            unknown_required = [
                fk for fk in artifact.required_facts
                if fk not in {fk_spec.kind for fk_spec in spec.fact_kinds}
            ]
            if unknown_required:
                findings.append(
                    f"{art_where}: required_facts {unknown_required} — not declared "
                    "in this episode's fact_kinds. The artifact will require facts "
                    "the generator does not produce."
                )

            if not artifact.structured and not artifact.unstructured:
                findings.append(
                    f"{art_where}: both structured and unstructured are false — "
                    "the artifact has no tables and no prose sections, so it "
                    "compiles into an empty document."
                )

            if domain is not None and artifact.author_role:
                if artifact.author_role not in domain.role_keys:
                    findings.append(
                        f"{art_where}: author_role {artifact.author_role!r} is not "
                        f"a known {base} role. Roles: {', '.join(domain.role_keys)}"
                    )

            unknown_triggers = [
                kind for kind in artifact.triggered_by_events
                if kind not in declared_events
            ]
            if unknown_triggers:
                findings.append(
                    f"{art_where}: triggered_by_events {unknown_triggers} — not"
                    " declared in this episode's events."
                )

        # -- carry-forward ------------------------------------------------
        for cf_index, cf in enumerate(spec.carry_forward):
            cf_where = f"{where}.carry_forward[{cf_index}]"

            from_spec = next(
                (fk for fk in spec.fact_kinds if fk.kind == cf.from_kind), None
            )
            if from_spec is None:
                findings.append(
                    f"{cf_where}: from_kind {cf.from_kind!r} is not declared in "
                    "this episode's fact_kinds."
                )

            to_spec = next((fk for fk in spec.fact_kinds if fk.kind == cf.to_kind), None)
            if to_spec is None:
                findings.append(
                    f"{cf_where}: to_kind {cf.to_kind!r} is not declared in this "
                    "episode's fact_kinds."
                )

            # A standing fact carries forward one way only: reuse. That *is*
            # the banking minimum's pattern (autopsy, carry-forward category 1)
            # — the same fact id listed by every quarter, never re-minted. This
            # lint used to refuse standing carry-forward outright, which would
            # have refused the very episode the grammar's proof ports.
            if from_spec is not None and from_spec.period_scope == "standing":
                if cf.rule != "reuse":
                    findings.append(
                        f"{cf_where}: a standing from_kind ({cf.from_kind!r}) can only "
                        "carry forward by reuse — sum and derive describe a value that "
                        "moves between periods, and a standing fact has no periods to "
                        "move between."
                    )
            elif from_spec is not None and from_spec.period_scope != "period-keyed":
                findings.append(
                    f"{cf_where}: from_kind {cf.from_kind!r} has period_scope "
                    f"{from_spec.period_scope!r} — only period-keyed facts (every "
                    "period has one) or standing facts (reuse) can carry forward; "
                    "period-scoped facts are incident-specific."
                )

    return findings


# ---------------------------------------------------------------------------
# The runner: an authored spec, executed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RunResult:
    """One episode — a bounded run of a declared process — before the world absorbs it."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    intents: tuple[ArtifactIntentModel, ...]
    keys: dict[str, str] = _dataclass_field(default_factory=dict)
    reused_fact_ids: tuple[str, ...] = ()
    """Standing facts resolved from the world by a carry-forward declaration
    and re-listed in ``facts`` — the caller filters these back out before
    ``world.extend``, exactly as ``QuarterlyCapitalReturn.run`` does."""


def _invariant(spec: FactKindSpec, head: str) -> Invariant | None:
    for invariant in spec.invariants:
        if invariant.kind == head:
            return invariant
    return None


def run(
    spec: EpisodeSpec,
    world: World,
    rng: Rng,
    minter: Minter,
    *,
    period: str,
) -> RunResult:
    """Instantiate an authored process into one episode over *period*.

    Vocabulary (docs/next-phase-plan.md, "The ontology, settled"): the spec is
    a *process* — the recurring type, declared once; one bounded run of it over
    a period is an *episode*; history is the ordered episodes. ``EpisodeSpec``
    keeps its committed name, but what it declares is the process, and what
    this function returns is one episode of it.

    Phases run in declared order; each phase's events fire in declared order;
    each event mints the fact kinds its ``fact_keys`` list, in list order —
    so the minter's ID sequence is fixed by the spec alone. Values come from
    ``generators.primitives``: a level+noise draw where a kind names a
    parameter, a roll-up where a kind is the child of a ``sums-to``, a
    supersession pair where a kind is ``supersedes-prior`` and minted twice,
    a business-day series where a kind declares one, and a declared carry-
    forward resolved from the world before anything mints.

    What this cannot do, stated rather than approximated: reproduce a
    hand-built generator's bytes. Stream labels are generator-private, an
    incident's tempo is five cumulative draws the spec states as literals,
    identifier formats (an INC number) are mechanism, and the artifact
    relationship graph (restates/revises/derived_from, intentional errors)
    is planner logic. The proof's byte-diff names each of these, measured.
    """
    from .generators import primitives
    from .generators.operations import _at, business_days_after, period_end
    from .parameters import DEFAULT

    if world.seed is None:
        raise ValueError("an authored episode needs a seeded world")

    company_id = world.company.id
    roles = dict(world._roles)
    archetype = world._archetype
    money_unit = (
        f"{archetype.currency}_{archetype.currency_unit}" if archetype is not None
        else "AUD_millions"
    )
    physics = DEFAULT
    ends = period_end(period)

    from .recipe import locale_of

    calendar = locale_of(world._recipe)

    by_kind = {fk.kind: fk for fk in spec.fact_kinds}

    def subject_of(fk: FactKindSpec) -> str:
        if fk.subject_role:
            resolved = roles.get(fk.subject_role)
            if resolved is None:
                raise ValueError(
                    f"{spec.name}: subject_role {fk.subject_role!r} is not a role"
                    " of this world"
                )
            return resolved
        return company_id

    def unit_for(fk: FactKindSpec) -> str:
        if fk.unit:
            return fk.unit
        if fk.value_type == "percent":
            return "pct"
        return money_unit

    # The cadence in months — how far back "the prior period" is, and where
    # the previous period's end sits for `anchor="prior_period_end"` events.
    from .generators.finance import previous_periods

    step = {"month": 1, "quarter": 3, "year": 12}[spec.period]
    prior_period = previous_periods(period, step)[0]
    prior_ends = period_end(prior_period)

    # -- carry-forward, resolved before anything mints -----------------------
    # Reuse means: the world's standing fact is listed in this episode's facts
    # (so intents and keys resolve identically whichever period this is) and
    # reported in `reused_fact_ids` for the caller to filter out of `extend`.
    # Sum/derive means: the *prior* period's value is resolved and handed to
    # the `prior(K)` derivation — scoped to that period explicitly, because a
    # period-keyed snapshot stays open forever and an unscoped lookup would
    # find whichever one sorted last (`PurchaseToPayCycle.run`'s own comment).
    reused: dict[str, CanonicalFact] = {}
    prior_values: dict[str, float] = {}
    for cf in spec.carry_forward:
        fk = by_kind.get(cf.from_kind)
        if fk is None:
            continue
        prior = primitives.carried_forward(
            world, kind=cf.from_kind, subject=subject_of(fk), rule=cf.rule,
            prior_period=None if fk.period_scope == "standing" else prior_period,
        )
        if prior is not None and cf.rule == "reuse":
            reused[cf.to_kind] = prior
        elif cf.rule in ("sum", "derive") and prior is not None and prior.value is not None:
            prior_values[cf.from_kind] = prior.value.amount

    # -- event times first, because a supersession pair's first fact must
    # close exactly where its successor opens, and that moment is the second
    # event's — unknowable while minting the first unless times precede facts.
    times: dict[str, datetime] = {}
    for event_spec in spec.events:
        anchored = ends if event_spec.anchor == "period_end" else prior_ends
        times[event_spec.kind] = _at(
            business_days_after(anchored, event_spec.business_day),
            event_spec.hour, event_spec.minute,
        )

    # Which events mint each kind, in declared phase-then-event order — the
    # occurrence index is what picks the pair half and the authority.
    ordered_events: list[EventSpec] = []
    for phase in spec.phases or [PhaseSpec(name="episode", events=[e.kind for e in spec.events])]:
        for kind in phase.events:
            event_spec = next((e for e in spec.events if e.kind == kind), None)
            if event_spec is None:
                raise ValueError(f"{spec.name}: phase {phase.name!r} names undeclared event {kind!r}")
            ordered_events.append(event_spec)

    mints: dict[str, list[str]] = {}
    for event_spec in ordered_events:
        for kind in event_spec.fact_keys:
            mints.setdefault(kind, []).append(event_spec.kind)

    # -- values, computed per kind in declaration order ----------------------
    # Derivations read earlier kinds, so declaration order is evaluation
    # order — the same rule a spreadsheet's dependency graph flattens to.
    values: dict[str, Any] = {}

    def pair_of(kind: str) -> tuple[float, float]:
        value = values[kind]
        if not (isinstance(value, tuple) and len(value) == 2):
            raise ValueError(f"{kind} is not a supersession pair")
        return value

    def scalar_of(kind: str) -> float:
        value = values[kind]
        if isinstance(value, tuple):
            return value[0]
        return value

    def compute(fk: FactKindSpec) -> None:
        kind = fk.kind
        if kind in values:
            # Already valued — a sums-to child is allocated when its parent
            # computes, whatever the declaration order says.
            return
        occurrences = mints.get(kind, [])
        paired = _invariant(fk, "supersedes-prior") is not None and len(occurrences) == 2

        if kind in reused:
            values[kind] = reused[kind].value.amount if reused[kind].value else None
            return
        if fk.derive:
            head, _, rest = fk.derive.partition("(")
            operands = [p.strip() for p in rest.rstrip(")").split(",") if p.strip()]
            if head == "pct_of":
                pct = primitives.level(physics, fk.parameter, rng.derive(f"kind/{kind}"))
                values[kind] = int(round(scalar_of(operands[0]) * float(pct) / 100))
            elif head == "ratio_pct":
                a, b = operands
                def ratio(x: float, y: float) -> float:
                    return round(x / y * 100, 2)
                a_val, b_val = values[a], values[b]
                a_pair = isinstance(a_val, tuple)
                b_pair = isinstance(b_val, tuple)
                if a_pair or b_pair:
                    a_i, a_c = (a_val if a_pair else (a_val, a_val))
                    b_i, b_c = (b_val if b_pair else (b_val, b_val))
                    values[kind] = (ratio(a_i, b_i), ratio(a_c, b_c))
                else:
                    values[kind] = ratio(a_val, b_val)
            elif head == "initial":
                values[kind] = pair_of(operands[0])[0]
            elif head == "supersession_delta":
                initial, corrected = pair_of(operands[0])
                values[kind] = corrected - initial
            elif head == "bps_delta":
                initial, corrected = pair_of(operands[0])
                values[kind] = round((initial - corrected) * 100)
            # -- the procure-to-pay arithmetic. Each is a pure function of
            # already-valued kinds (plus at most one drawn factor), rounded the
            # way `procurement_match._money` publishes figures — two decimals of
            # the reporting unit — so the identities the procurement check group
            # recomputes ((f) the halves sum, (g) the settlement, (i) the
            # accrual, (j)/(k) the carry) hold exactly by construction.
            elif head == "at_rate":
                q, r = operands
                values[kind] = round(scalar_of(q) * scalar_of(r) / 1000, 2)
            elif head == "percent_of":
                a, p = operands
                values[kind] = round(scalar_of(a) * scalar_of(p) / 100, 2)
            elif head == "multiple_of":
                factor = primitives.level(physics, fk.parameter, rng.derive(f"kind/{kind}"))
                values[kind] = round(scalar_of(operands[0]) * float(factor), 2)
            elif head == "plus":
                a, b = operands
                values[kind] = round(scalar_of(a) + scalar_of(b), 2)
            elif head == "minus":
                a, b = operands
                values[kind] = round(scalar_of(a) - scalar_of(b), 2)
            elif head == "units_of":
                v, r = operands
                values[kind] = int(round(scalar_of(v) * 1000 / scalar_of(r)))
            elif head == "prior":
                # Zero when no prior period holds the slot — minted, not
                # omitted, because the accrual reconciliation adds this term
                # unconditionally and a missing fact would make "nothing was
                # outstanding" indistinguishable from "nobody checked"
                # (`procurement_cycle.generate`'s own reasoning, kept).
                values[kind] = prior_values.get(operands[0], 0)
            else:
                raise ValueError(f"{kind}: unknown derivation {fk.derive!r}")
            return
        if fk.series_days:
            start = calendar.business_days_after(ends, fk.series_start_bd)
            values[kind] = primitives.series(
                physics, fk.parameter, rng.derive(f"kind/{kind}"),
                start=start, days=fk.series_days, calendar=calendar,
            )
            return
        if fk.parameter and paired:
            supersedes = _invariant(fk, "supersedes-prior")
            error_parameter = supersedes.operands[0] if supersedes and supersedes.operands else ""
            if not error_parameter:
                raise ValueError(
                    f"{kind}: a drawn supersession pair needs its error span in the"
                    " supersedes-prior invariant's operands"
                )
            values[kind] = primitives.supersession_pair(
                physics, fk.parameter, error_parameter,
                rng.derive(f"kind/{kind}"), scale=fk.scale,
            )
            return
        if fk.parameter:
            drawn = primitives.level(physics, fk.parameter, rng.derive(f"kind/{kind}"))
            values[kind] = float(drawn) * fk.scale if fk.scale != 1.0 else drawn
            return
        if fk.amount is not None:
            values[kind] = fk.amount
            return
        # Text kinds carry no numeric value; anything else minted without a
        # source is refused rather than invented.
        if fk.value_type not in ("text", "date") and kind in mints:
            raise ValueError(
                f"{kind}: minted by {mints[kind]} but declares no parameter,"
                " amount, or derivation to value it"
            )

    # sums-to children: allocated from the parent, never drawn — the invariant
    # holds by construction. The parent computes first (declaration order), and
    # the child's roll-up weights are the world's own two-level income shares,
    # the same weighting `capital.generate` uses.
    def compute_children(parent: FactKindSpec, child_kind: str) -> None:
        child = by_kind[child_kind]
        books = tuple(c for c in world._categories if c.revenue_share > 0)
        if not books:
            raise ValueError(f"{child_kind}: no weighted subjects to roll up over")
        unit_share_of = {}
        if archetype is not None:
            unit_share_of = {
                roles.get(f"unit_{unit.key}"): unit.share for unit in archetype.units
            }
        weights = [
            max(book.revenue_share * unit_share_of.get(book.business_unit_id, 0.0), 1e-9)
            for book in books
        ]
        parent_value = values[parent.kind]
        initial = parent_value[0] if isinstance(parent_value, tuple) else parent_value
        allocated = primitives.rollup(int(initial), weights)
        per_subject = dict(zip((book.id for book in books), allocated))
        affected = roles.get(child.subject_role) if child.subject_role else None
        corrected = None
        if isinstance(parent_value, tuple) and affected is not None:
            corrected = per_subject[affected] + (parent_value[1] - parent_value[0])
        values[child_kind] = ("books", per_subject, affected, corrected)

    for fk in spec.fact_kinds:
        sums_to = _invariant(fk, "sums-to")
        compute(fk)
        if sums_to is not None and sums_to.operands and sums_to.operands[0] in by_kind:
            compute_children(fk, sums_to.operands[0])

    # -- mint ---------------------------------------------------------------
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}
    event_ids: dict[str, str] = {}
    minted: dict[str, list[CanonicalFact]] = {}
    seen_occurrence: dict[str, int] = {}

    def resolve_roles(role_keys: list[str], what: str) -> list[str]:
        out = []
        for key in role_keys:
            resolved = roles.get(key)
            if resolved is None:
                raise ValueError(f"{spec.name}: {what} {key!r} is not a role of this world")
            out.append(resolved)
        return out

    def render_text(template: str, at: datetime) -> str:
        text = template.replace("{period}", period).replace("{at}", at.isoformat())
        while "{bd:" in text:
            head, _, tail = text.partition("{bd:")
            days, _, rest = tail.partition("}")
            text = head + business_days_after(ends, int(days)).isoformat() + rest
        return text

    def next_occurrence_at(kind: str, current_index: int) -> datetime | None:
        """When the *next* mint of this kind occurs — where this fact's window closes."""
        occurrences = mints[kind]
        if current_index + 1 < len(occurrences):
            return times[occurrences[current_index + 1]]
        return None

    for event_spec in ordered_events:
        at = times[event_spec.kind]
        made = EnterpriseEvent(
            id=minter.next("EV"),
            kind=event_spec.kind,
            occurred_at=at,
            summary=render_text(event_spec.summary, at),
            actors=resolve_roles(event_spec.actors, "actor role"),
            services=resolve_roles(event_spec.services, "service role"),
            systems=resolve_roles(event_spec.systems, "system role"),
            business_units=resolve_roles(event_spec.units, "unit role"),
            caused_by=[event_ids[event_spec.caused_by]] if event_spec.caused_by else [],
        )
        events.append(made)
        event_ids[event_spec.kind] = made.id
        keys[f"event_{event_spec.kind}"] = made.id

        for kind in event_spec.fact_keys:
            fk = by_kind[kind]
            index = seen_occurrence.get(kind, 0)
            seen_occurrence[kind] = index + 1
            occurrences = mints[kind]
            paired = _invariant(fk, "supersedes-prior") is not None and len(occurrences) > 1
            authority = (
                fk.authorities[index] if index < len(fk.authorities) else fk.authority
            )
            fact_period = None if fk.period_scope == "standing" or fk.series_days else period
            source = roles.get(fk.source_role) if fk.source_role else None

            if kind in reused and reused[kind].id in {f.id for f in facts}:
                continue
            if kind in reused:
                facts.append(reused[kind])
                # Into `minted` as well as `facts`: an artifact requiring a
                # standing kind must cite the same fact id in every period, and
                # a reused fact left out of `minted` would drop off the second
                # period's required_fact_ids while staying in its keys.
                minted.setdefault(kind, []).append(reused[kind])
                keys[f"fact_{kind}"] = reused[kind].id
                continue

            if fk.series_days:
                # The chain: per-day facts, supersession-linked, each window
                # handing over exactly at the next observation — what the
                # cadence check walks. No period, deliberately: a daily
                # observation belongs to its moment, and its chain relates it
                # to its own quarter (`regulatory.generate`'s reasoning).
                previous: CanonicalFact | None = None
                observations = values[kind]
                for day_index, (day, value) in enumerate(observations):
                    day_at = _at(day, event_spec.hour, event_spec.minute)
                    next_at = (
                        _at(observations[day_index + 1][0], event_spec.hour, event_spec.minute)
                        if day_index + 1 < len(observations) else None
                    )
                    fact = CanonicalFact(
                        id=minter.next("FACT"), kind=kind, subject=subject_of(fk),
                        value=Quantity(amount=value, unit=unit_for(fk)),
                        valid_from=day_at, valid_to=next_at, authority=authority,
                        source_system=source,
                        event_id=made.id if day_index == 0 else None,
                        supersedes=previous.id if previous else None,
                    )
                    facts.append(fact)
                    previous = fact
                minted.setdefault(kind, []).extend(facts[-len(observations):])
                keys[f"fact_{kind}"] = facts[-len(observations)].id
                continue

            value = values.get(kind)
            if isinstance(value, tuple) and value and value[0] == "books":
                _, per_subject, affected, corrected = value
                if index == 0:
                    for subject_id, amount in per_subject.items():
                        until = times[occurrences[1]] if (
                            paired and affected == subject_id and len(occurrences) > 1
                        ) else None
                        fact = CanonicalFact(
                            id=minter.next("FACT"), kind=kind, subject=subject_id,
                            period=fact_period,
                            value=Quantity(amount=amount, unit=unit_for(fk)),
                            valid_from=at, valid_to=until, authority=authority,
                            source_system=source, event_id=made.id,
                        )
                        facts.append(fact)
                        minted.setdefault(kind, []).append(fact)
                        if affected == subject_id:
                            keys[f"fact_{kind}"] = fact.id
                else:
                    predecessor = next(
                        f for f in minted[kind] if f.subject == affected
                    )
                    fact = CanonicalFact(
                        id=minter.next("FACT"), kind=kind, subject=affected,
                        period=fact_period,
                        value=Quantity(amount=corrected, unit=unit_for(fk)),
                        valid_from=at, authority=authority, source_system=source,
                        event_id=made.id, supersedes=predecessor.id,
                    )
                    facts.append(fact)
                    minted.setdefault(kind, []).append(fact)
                    keys[f"fact_{kind}_corrected"] = fact.id
                continue

            text_template = event_spec.fact_texts.get(kind, fk.text)
            if fk.value_type in ("text", "date") and not isinstance(value, (int, float)):
                if not text_template:
                    raise ValueError(f"{kind}: a text fact needs authored text")
                amount_value = None
                text_value = render_text(text_template, at)
            else:
                if isinstance(value, tuple):
                    amount_value = value[index] if index < 2 else value[1]
                else:
                    amount_value = value
                text_value = None

            until = None
            supersedes_id = None
            if paired:
                # Every occurrence but the last closes exactly where its
                # successor opens — the *chain*, of which the pair is the
                # two-link case. Procurement's exception status walks three
                # links (raised → escalated → resolved), and the original
                # pair-only shape left the middle link open forever, which is
                # precisely the torn window the engine's own check (m)
                # (`exception_status_torn` / `not_singular`) exists to refuse.
                until = next_occurrence_at(kind, index)
                if index > 0:
                    predecessor = minted[kind][index - 1]
                    supersedes_id = predecessor.id
            never = _invariant(fk, "never-superseded") is not None
            if never:
                until = None
                supersedes_id = None

            fact = CanonicalFact(
                id=minter.next("FACT"), kind=kind, subject=subject_of(fk),
                period=fact_period,
                value=Quantity(amount=amount_value, unit=unit_for(fk))
                if amount_value is not None else None,
                text_value=text_value,
                valid_from=at, valid_to=until, authority=authority,
                source_system=source, event_id=made.id, supersedes=supersedes_id,
            )
            facts.append(fact)
            minted.setdefault(kind, []).append(fact)
            suffix = "" if index == 0 else f"_{index}"
            keys[f"fact_{kind}{suffix}"] = fact.id

    # -- artifact intents ----------------------------------------------------
    intents: list[ArtifactIntentModel] = []
    for artifact in spec.artifacts:
        author = roles.get(artifact.author_role)
        if author is None:
            raise ValueError(
                f"{spec.name}: author_role {artifact.author_role!r} is not a role"
                " of this world"
            )
        required: list[str] = []
        for kind in artifact.required_facts:
            for fact in minted.get(kind, ()):
                required.append(fact.id)
        intents.append(ArtifactIntentModel(
            id=minter.next("ART"),
            artifact_type=artifact.artifact_type,
            domain=spec.domain,
            audience=artifact.audience,
            author_id=author,
            triggered_by=[event_ids[k] for k in artifact.triggered_by_events],
            required_fact_ids=required,
            size_profile=artifact.size,
            rationale=artifact.rationale,
        ))

    return RunResult(
        events=tuple(events),
        facts=tuple(facts),
        intents=tuple(intents),
        keys=keys,
        reused_fact_ids=tuple(fact.id for fact in reused.values()),
    )


# ---------------------------------------------------------------------------
# Derived checks: the invariants, enforced
# ---------------------------------------------------------------------------


def derived_checks(spec: EpisodeSpec):
    """A validator check group derived from *spec*'s invariant declarations.

    This is the commitment the module docstring makes: declaring a kind means
    declaring its invariants, and the checks come from the declaration — never
    hand-written per kind. The callable follows the domain-check contract
    (``world -> (violations, checks_run)``) and returns quickly on a world that
    carries none of the spec's kinds.
    """
    from .validate import RECONCILIATION_TOLERANCE, Violation

    declared = {fk.kind: fk for fk in spec.fact_kinds}

    def _checks(world) -> tuple[list, int]:
        violations: list[Violation] = []
        checks = 0
        facts = [f for f in world.facts if f.kind in declared]
        if not facts:
            return violations, checks

        def fail(code: str, subject: str, detail: str) -> None:
            violations.append(Violation(
                group=f"episode:{spec.name}", code=code, subject=subject, detail=detail,
            ))

        by_id = {f.id: f for f in world.facts}
        superseded_ids = {f.supersedes for f in world.facts if f.supersedes}

        for kind, fk in declared.items():
            kind_facts = [f for f in facts if f.kind == kind]
            if not kind_facts:
                continue
            for invariant in fk.invariants:
                head, operands = invariant.kind, tuple(invariant.operands)

                if head == "never-superseded":
                    for fact in kind_facts:
                        checks += 1
                        if fact.valid_to is not None or fact.id in superseded_ids:
                            fail("never_superseded_touched", fact.id,
                                 f"{kind} is declared never-superseded; closing or"
                                 " superseding it erases the permanent record")

                elif head == "standing":
                    checks += 1
                    with_period = [f for f in kind_facts if f.period]
                    if with_period:
                        fail("standing_carries_period", kind,
                             f"{len(with_period)} facts carry a period; a standing"
                             " fact belongs to no quarter")
                    by_subject: dict[str, int] = {}
                    for fact in kind_facts:
                        by_subject[fact.subject] = by_subject.get(fact.subject, 0) + 1
                    for subject, count in sorted(by_subject.items()):
                        checks += 1
                        if count > 1:
                            fail("standing_minted_twice", f"{kind}/{subject}",
                                 f"{count} facts for one subject — a standing fact"
                                 " is minted once and reused, never duplicated")

                elif head == "supersedes-prior":
                    for fact in kind_facts:
                        if not fact.supersedes:
                            continue
                        checks += 1
                        predecessor = by_id.get(fact.supersedes)
                        if predecessor is None:
                            fail("supersedes_nothing", fact.id,
                                 f"supersedes {fact.supersedes}, which does not exist")
                        elif predecessor.kind != kind:
                            fail("supersedes_other_kind", fact.id,
                                 f"a {kind} fact supersedes a {predecessor.kind} fact —"
                                 " succession stays within one kind")
                        # Closed no later than the successor opens — `<=`, not
                        # `==`, because a belief may be *ruled out* before its
                        # replacement is confirmed (retail's and banking's
                        # ops.cause both close the hypothesis at the rule-out,
                        # hours before the confirmed cause opens), and a check
                        # that failed that correct shape would teach authors to
                        # distrust the gate.
                        elif predecessor.valid_to is None or predecessor.valid_to > fact.valid_from:
                            fail("succession_torn", fact.id,
                                 "the superseded fact's window must close at or before"
                                 " the successor opens, and it does not")

                elif head == "sums-to" and operands:
                    child_kind = operands[0]
                    children_all = [f for f in world.facts if f.kind == child_kind]
                    for total in kind_facts:
                        if total.value is None:
                            continue
                        children = [
                            f for f in children_all
                            if f.period == total.period and f.holds_at(total.valid_from)
                            and f.value is not None
                        ]
                        if not children:
                            continue
                        checks += 1
                        summed = sum(f.value.amount for f in children)
                        if abs(summed - total.value.amount) > RECONCILIATION_TOLERANCE:
                            fail("children_do_not_sum", total.id,
                                 f"{child_kind} facts holding at {total.valid_from.isoformat()}"
                                 f" sum to {summed:,.2f} against a declared total of"
                                 f" {total.value.amount:,.2f}")

                elif head == "reconciles-against" and len(operands) == 2:
                    # SYSTEM_OF_RECORD only, on all three legs, and every leg
                    # scoped to the stated fact's own period. Both narrowings
                    # were paid for: a two-quarter `validate()` run failed the
                    # second quarter's *working paper* ratio — stated before
                    # its own quarter's amounts enter the record — against the
                    # prior quarter's still-open capital figure (2,077 /
                    # 20,100 = 10.33 "vs" a stated 13.40). A working figure
                    # precedes its amounts by design, and last quarter's
                    # never-closed amounts are not this quarter's operands.
                    a_kind, b_kind = operands
                    a_all = [f for f in world.facts if f.kind == a_kind and f.value
                             and f.authority is Authority.SYSTEM_OF_RECORD]
                    b_all = [f for f in world.facts if f.kind == b_kind and f.value
                             and f.authority is Authority.SYSTEM_OF_RECORD]
                    for stated in kind_facts:
                        if stated.value is None or stated.authority is not Authority.SYSTEM_OF_RECORD:
                            continue
                        a_at = [f for f in a_all if f.holds_at(stated.valid_from)
                                and (f.period == stated.period or stated.period is None)]
                        b_at = [f for f in b_all if f.holds_at(stated.valid_from)
                                and (f.period == stated.period or stated.period is None)]
                        if not a_at or not b_at:
                            continue
                        checks += 1
                        a_val = max(a_at, key=lambda f: f.valid_from).value.amount
                        b_val = max(b_at, key=lambda f: f.valid_from).value.amount
                        derived = a_val / b_val * 100
                        if abs(derived - stated.value.amount) > 0.01:
                            fail("reconciliation_disagrees", stated.id,
                                 f"states {stated.value.amount:.2f} but {a_val:,.2f} /"
                                 f" {b_val:,.2f} = {derived:.4f}")

        return violations, checks

    return _checks


#: Check groups already derived and registered, by spec name — so a rebuild
#: re-registering the same spec passes `register_domain_checks`'s identity
#: test instead of tripping it.
_REGISTERED_CHECKS: dict[str, Any] = {}


def install_checks(spec: EpisodeSpec) -> None:
    """Derive *spec*'s check group and register it with the validator.

    Registered under ``episode:<name>``, beside the vertical groups. Cached by
    name so the second installation of one spec re-registers the same callable
    (a harmless reload); ``install`` has already refused a different spec under
    the same name before this can run.
    """
    checks = _REGISTERED_CHECKS.get(spec.name)
    if checks is None:
        checks = derived_checks(spec)
        _REGISTERED_CHECKS[spec.name] = checks
    validate_module.register_domain_checks(f"episode:{spec.name}", checks)


# ---------------------------------------------------------------------------
# The scenario wrapper: an authored episode as a recipe step
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AuthoredEpisode:
    """One episode of an installed process spec, run as an ordinary scenario.

    Episode-flavoured on purpose: the spec declares the recurring *process*
    (P2P, the close, the capital return); this dataclass is one bounded run of
    it over one period, and a history is these, ordered.

    ``episode`` names a spec in this process's registry (``install``), which is
    how the step replays: the recipe records the name and the period, the spec
    itself travels with whatever installed it (a pack, a domain module, a
    test), and a rebuild in a process that never installed the spec fails
    loudly here rather than building a world with a silent hole in it.
    """

    episode: str
    period: str

    def run(self, world: World) -> World:
        from .recipe import with_step
        from .rng import Rng

        spec = _LOADED.get(self.episode)
        if spec is None:
            raise ValueError(
                f"episode {self.episode!r} is not installed in this process —"
                " call episodes.install(episodes.load(...)) before building or"
                " rebuilding a corpus that runs it"
            )
        if world.seed is None:
            raise ValueError("an authored episode needs a seeded world")
        if world._minter is None:
            raise ValueError(
                "this world was loaded from disk and cannot be advanced; build one from a seed"
            )

        # The stream is named for the *spec*, not for this wrapper class:
        # "scenario/<name>/<period>", the same shape every hand-built scenario
        # derives — so a ported episode at least shares the convention, even
        # though its child stream labels are its own.
        rng = Rng(world.seed).derive(f"scenario/{spec.name}/{self.period}")
        result = run(spec, world, rng, world._minter, period=self.period)
        install_checks(spec)

        known_fact_ids = set(world.facts.ids())
        new_facts = tuple(f for f in result.facts if f.id not in known_fact_ids)

        return world.extend(
            events=result.events,
            facts=new_facts,
            artifact_intents=result.intents,
            period=self.period,
            recipe=with_step(world._recipe, "AuthoredEpisode",
                             episode=self.episode, period=self.period),
        )


# The recipe verb, registered from this module exactly as each vertical's
# scenario registers its own — an authored episode's replay costs core nothing.
from . import recipe as _recipe  # noqa: E402

_recipe.register_step("AuthoredEpisode", ("episode", "period"), AuthoredEpisode)


__all__ = [
    "Invariant",
    "FactKindSpec",
    "EventSpec",
    "ArtifactIntentSpec",
    "CarryForwardSpec",
    "PhaseSpec",
    "RoleSlotSpec",
    "EpisodeSpec",
    "Episodes",
    "load",
    "loaded",
    "install",
    "lint",
    "run",
    "RunResult",
    "derived_checks",
    "install_checks",
    "AuthoredEpisode",
]
