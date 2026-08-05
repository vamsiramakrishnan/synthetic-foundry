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
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import validate as validate_module
from .models import Authority

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
        "reconciles-against", "precedes-event"
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


class EventSpec(Model):
    """Declaration of an event that can occur in an episode."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    """The event kind, in the format ``domain.event``."""

    when: Literal["start", "before_incident", "incident", "after_incident", "end"]
    """Relative timing in the episode. Used by generators to determine when to fire."""

    summary: str = Field(min_length=1)
    """The event summary prose (from episode_text, overrideable by pack)."""

    fact_keys: list[str] = Field(default_factory=list)
    """Names of facts this event links to (e.g., ``"fact_rwa"``, ``"fact_incident_ref"``)."""

    detail: str = Field(default="", min_length=0)
    """Why this event occurs in the episode."""


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
    from . import domains

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

        for fk_index, fk in enumerate(spec.fact_kinds):
            fk_where = f"{where}.fact_kinds[{fk_index}] ({fk.kind})"

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

            if from_spec is not None and from_spec.period_scope != "period-keyed":
                findings.append(
                    f"{cf_where}: from_kind {cf.from_kind!r} has period_scope "
                    f"{from_spec.period_scope!r} — only period-keyed facts can carry "
                    "forward (standing facts exist forever; period-scoped facts are "
                    "incident-specific)."
                )

    return findings


__all__ = [
    "Invariant",
    "FactKindSpec",
    "EventSpec",
    "ArtifactIntentSpec",
    "CarryForwardSpec",
    "PhaseSpec",
    "EpisodeSpec",
    "Episodes",
    "load",
    "loaded",
    "install",
    "lint",
]
