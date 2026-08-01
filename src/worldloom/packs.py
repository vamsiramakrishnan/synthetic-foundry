"""Industry packs: a world's shape and lore as data an agent can author.

This is the fourth intervention surface, and the one that was missing. The
harness could already shape a corpus's *structure* (``worldloom plan``), its
*prose* (``worldloom narrate``), and its *decisions* (``worldloom act``) — but
the world itself was frozen in Python: archetypes were constants, lore was a
function, and "generate me an insurer" meant editing this repository. A pack
moves that boundary. It is a JSON document carrying an archetype (units,
product categories, site estate, scale), lore commitments in the same closed
vocabulary the engine already honours, and a company name — everything the
telco experiment measured as authorable data, and nothing that is not.

What a pack deliberately cannot do:

* **Choose an episode.** ``base`` names one of the registered domain engines
  (``retail``, ``banking``), and the episode physics stay that engine's code.
  §7a's warning is the reason: a pack that renames nouns and stops produces
  retail with different words, so the honest contract is that a pack supplies
  *texture* to an engine whose events it does not control — and lore is the
  lever it does get, because lore genuinely changes what happens (incident
  likelihood, artifact density, personas, terminology).
* **Execute anything.** A pack is validated data end to end. It embeds into
  the corpus recipe verbatim, which is what makes a pack-built world
  rebuildable from its own corpus with no pack file on hand — same closed
  vocabulary rule as ``recipe.STEPS``.

The lint (``worldloom pack check``) is the part built for agents rather than
despite them: a lore constraint aimed at a target no engine consults is legal
and inert, and an author who cannot see which targets are load-bearing will
cargo-cult them. Each engine publishes its consulted targets
(``retail.CONSULTED_TARGETS``, ``banking.CONSULTED_TARGETS``), and the lint
names every commitment whose constraints all miss.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from .archetypes import Archetype
from .generators.hierarchy import CategorySpec, SiteFormat, UnitSpec
from .ids import Minter
from .models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind


class PackModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class PackCategory(PackModel):
    """One product category or book: its share of the unit, and its margin."""

    name: str
    share: float = Field(gt=0.0, le=1.0)
    margin: float = Field(ge=0.0, le=1.0)


class PackSiteFormat(PackModel):
    name: str
    count: int = Field(ge=0)
    revenue_weight: float = Field(default=1.0, ge=0.0)


class PackUnit(PackModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    name: str
    kind: str
    share: float = Field(gt=0.0, le=1.0)
    categories: list[PackCategory] = Field(default_factory=list)
    site_formats: list[PackSiteFormat] = Field(default_factory=list)

    @model_validator(mode="after")
    def _categories_sum_to_the_unit(self) -> PackUnit:
        if self.categories:
            total = sum(c.share for c in self.categories)
            if abs(total - 1.0) > 0.02:
                raise ValueError(
                    f"unit {self.key!r}: category shares sum to {total:.3f}, not 1 —"
                    " the roll-up discipline needs the books to decompose the unit"
                )
        return self


class PackConstraint(PackModel):
    kind: ConstraintKind
    target: str
    effect: str
    magnitude: float | None = None


class PackCommitment(PackModel):
    """A lore commitment as a pack states it: everything but the id, which the
    build mints so pack lore and hand-authored lore live in one sequence."""

    kind: LoreKind
    assertion: str
    effective_from: str = Field(pattern=r"^\d{4}-\d{2}$")
    effective_to: str | None = None
    constrains: list[PackConstraint] = Field(min_length=1)
    visibility: Literal["acknowledged", "tacit", "denied"] = "acknowledged"


class Pack(PackModel):
    """One industry pack. See the module docstring for what it can and cannot do."""

    name: str
    base: str
    """Which registered domain engine runs the episode: ``retail`` or ``banking``."""
    description: str = ""
    company_name: str
    """The fictional company's name. Named by the author because it is their
    fiction — every other identity (people, systems, figures) stays generated."""
    industry: str
    currency: str = "AUD"
    currency_unit: str = "thousands"
    fiscal_year_start_month: int = Field(default=7, ge=1, le=12)
    annual_revenue: int = Field(gt=0)
    employees: int = Field(gt=0)
    units: list[PackUnit] = Field(min_length=1)
    lore: list[PackCommitment] = Field(default_factory=list)

    @model_validator(mode="after")
    def _units_sum_to_the_group(self) -> Pack:
        total = sum(unit.share for unit in self.units)
        if abs(total - 1.0) > 0.02:
            raise ValueError(
                f"unit shares sum to {total:.3f}, not 1 — the group must decompose"
                " into its units exactly"
            )
        return self


def load(source: str | Path | dict[str, Any]) -> Pack:
    """Load and validate a pack from a path, JSON text, or parsed dict."""
    if isinstance(source, dict):
        return Pack.model_validate(source)
    text = Path(source).read_text(encoding="utf-8") if Path(str(source)).exists() else str(source)
    return Pack.model_validate(json.loads(text))


def archetype_of(pack: Pack) -> Archetype:
    """The pack's company shape, as the engine's own archetype type.

    The key is derived from the pack name so recipes and registries stay
    string-keyed; pack archetypes are not registered globally — a pack travels
    with its corpus rather than living in the process.
    """
    return Archetype(
        key=f"pack:{pack.name}",
        label=pack.description or pack.name,
        industry=pack.industry,
        currency=pack.currency,
        currency_unit=pack.currency_unit,
        fiscal_year_start_month=pack.fiscal_year_start_month,
        annual_revenue=pack.annual_revenue,
        employees=pack.employees,
        units=tuple(
            UnitSpec(
                key=unit.key,
                name=unit.name,
                kind=unit.kind,
                share=unit.share,
                categories=tuple(
                    CategorySpec(c.name, c.share, c.margin) for c in unit.categories
                ),
                site_formats=tuple(
                    SiteFormat(f.name, f.count, f.revenue_weight)
                    for f in unit.site_formats
                ),
            )
            for unit in pack.units
        ),
    )


def lore_of(pack: Pack, minter: Minter) -> tuple[LoreCommitment, ...]:
    """The pack's lore, minted into the world's own LORE sequence."""
    return tuple(
        LoreCommitment(
            id=minter.next("LORE"),
            kind=commitment.kind,
            assertion=commitment.assertion,
            effective_from=commitment.effective_from,
            effective_to=commitment.effective_to,
            constrains=[
                LoreConstraint(
                    kind=c.kind, target=c.target, effect=c.effect, magnitude=c.magnitude
                )
                for c in commitment.constrains
            ],
            visibility=commitment.visibility,
        )
        for commitment in pack.lore
    )


def lint(pack: Pack) -> list[str]:
    """Advisory findings an author should read before building.

    Nothing here is fatal — an inert constraint is legal — but every finding
    is a place where the pack's intent and the engine's behaviour diverge, and
    an agent authoring lore needs that divergence *named*, not discovered by
    generating a corpus that ignored half its backstory.
    """
    from . import domains

    findings: list[str] = []
    domain = domains.by_name(pack.base)
    if domain is None:
        findings.append(
            f"base {pack.base!r} names no registered engine —"
            f" registered: {', '.join(sorted(domains.names()))}"
        )
        return findings

    consulted: dict[str, str] = dict(domain.consulted_targets)
    for index, commitment in enumerate(pack.lore):
        hits = 0
        for constraint in commitment.constrains:
            if constraint.kind is ConstraintKind.PERSONA_TRAIT:
                # Persona traits target "role/trait"; whether the role exists is
                # a build-time property of the engine's role table, so the lint
                # only checks the shape here.
                hits += 1 if "/" in constraint.target else 0
                if "/" not in constraint.target:
                    findings.append(
                        f"lore[{index}]: persona_trait target {constraint.target!r}"
                        " is not ROLE/trait shaped"
                    )
            elif constraint.kind is ConstraintKind.TERMINOLOGY:
                hits += 1  # terminology reaches prose, not a generator switch
            elif constraint.target in consulted:
                hits += 1
        if hits == 0:
            findings.append(
                f"lore[{index}] ({commitment.kind.value}: {commitment.assertion[:60]!r}…)"
                f" constrains nothing the {pack.base} engine consults — it will be"
                " carried, cited, and inert. Consulted targets:"
                f" {', '.join(sorted(consulted))}"
            )
    if not pack.lore:
        findings.append(
            "the pack carries no lore — the corpus will be coherent and"
            " characterless; lore is the lever that makes an incident likely,"
            " a persona defensive, a norm binding"
        )
    return findings


def to_recipe(pack: Pack) -> dict[str, Any]:
    """The pack as its recipe embedding — plain JSON, carried by the corpus so
    a pack-built world rebuilds with no pack file on hand."""
    return json.loads(pack.model_dump_json())


__all__ = ["Pack", "PackCommitment", "archetype_of", "lint", "load", "lore_of", "to_recipe"]
