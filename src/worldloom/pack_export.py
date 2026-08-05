"""Keeping a world somebody derived: a variant or a probe, as a pack.

``mosaic.field`` and ``probe.resolve`` both answer the question "what kind of
company is this?" — one by covering a space, one by asking. Neither answer
survives the command that produced it. A mosaic writes twenty corpora and a
plan; a probe writes a parameter file. An author who reads world 3 and wants
*that one*, named, edited, and handed to a colleague, has nothing to hand over.
``packs.Pack`` is the artifact that travels — so this module turns the derived
thing into one.

**What a pack cannot carry, and why that is the interesting part.**

A pack is *texture*: a company's name, its units and their books, its lore, its
voices. A variant and a probe are *physics and shape*: parameter ranges, an org
chart, an estate, a trading year. The overlap is one field — ``seasonality`` —
and everything else falls on one side or the other:

* **Neither source knows what the company is.** No name, no industry, no unit
  names, no categories, no lore. These are not derivable from a Halton
  coordinate or an interval graph, and filling them in would be this module
  inventing a company and signing an author's name to it. So the skeleton
  path marks them ``packs.PLACEHOLDER`` and ``packs.lint`` names every one.
* **A pack has no field for physics, a role table, or an estate.** Deliberately
  — see ``packs``'s module docstring and ``worldloom pack params``, which sends
  an author to ``build --physics`` rather than to a pack field. The recipe
  agrees: it carries ``pack``, ``physics``, ``role_table``, ``estate`` and
  ``seasonality`` as five siblings, because they are five different claims.

So an export is a *bundle*, not a pack: the pack, plus the sidecars the pack is
not allowed to hold, plus a list of what nobody filled in. Widening ``Pack``
with a ``physics`` block would have been the shorter route and the wrong one —
it would give a pack two ways to say the same thing (its own field and
``--physics``), and a build would then have to decide which wins.

**Two shapes, because two things happen in practice.**

``onto=None`` gives a skeleton: derived parts filled, identity placeheld,
structurally complete enough to *build* so an author can see their physics
working before they have named anything. ``onto=<Pack>`` returns that pack with
the derived parts applied, which is what an author who already has a pack and
has just probed its physics wants. Both, because they are not the same moment.

**The round trip.** ``Derived.write`` emits files that ``packs.load`` and
``build --physics`` read; ``Derived.apply`` rebinds a world spec to the
sidecars. Exporting, loading and building returns the same ``Parameters`` and
the same ``Seasonality`` objects the source held — ``tests/test_pack_export.py``
asserts it against a real build's recipe rather than against these functions'
own return values.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from . import packs
from .packs import Pack, PackCategory, PackSiteFormat, PackUnit

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .archetypes import Archetype
    from .mosaic import Variant
    from .probe import Resolution

#: A role-table row as ``roles.to_rows`` emits it and ``RetailWorld.role_table``
#: accepts it: key, title, function, reports-to.
Row = tuple[str, str, str, str | None]


@dataclass(frozen=True)
class Derived:
    """A pack, the parts a pack may not hold, and what nobody could fill in.

    Three fields rather than one file because the build takes them through
    three different doors (``--pack``, ``--physics``, and a spec field with no
    flag at all yet). Pretending otherwise would mean inventing a pack field
    that the recipe would then carry twice.
    """

    pack: Pack
    physics: dict[str, Any]
    """Parameter overrides as ``parameters.overrides_document`` writes them —
    only the spans that differ from the engine's, so a derivation that happened
    to land on the defaults writes no file at all."""
    role_table: tuple[Row, ...] | None = None
    estate: str | None = None
    unfilled: tuple[str, ...] = ()
    """What this source could not honestly supply, each with the reason. Not a
    warning list — a contract. An author reading it knows exactly which parts
    of the pack are theirs to write."""
    notes: tuple[str, ...] = ()
    """Findings from the source itself, carried rather than dropped — a probe's
    unbound leaves are the case this exists for."""

    def physics_document(self) -> dict[str, Any]:
        """The sidecar ``build --physics`` reads.

        Provenance goes on the envelope, never on the spans: ``--physics`` and
        ``overrides_from`` read ``document["overrides"]`` and ignore the rest,
        so a ``source`` here is recorded for a human without becoming part of
        the ``Span`` that has to compare equal after a round trip.
        """
        return {"source": "worldloom pack_export", "overrides": self.physics}

    def shape_document(self) -> dict[str, Any]:
        """The org shape and estate — everything with no home in a pack *or* a
        pack-build flag today. Written as data so the information survives the
        gap rather than being lost until a flag exists."""
        document: dict[str, Any] = {}
        if self.role_table is not None:
            document["role_table"] = [list(row) for row in self.role_table]
        if self.estate is not None:
            document["estate"] = self.estate
        return document

    def apply(self, spec: Any) -> Any:
        """*spec* — a world builder — rebound to the sidecars this carries.

        Untouched fields are not passed, for the reason ``cli``'s
        ``_under_physics`` does the same: a domain registered outside this
        repository may have no ``estate`` or ``role_table`` field, and a build
        that needed neither should not start failing on a keyword.
        """
        from dataclasses import replace

        from .parameters import DEFAULT, overrides_from

        changes: dict[str, Any] = {}
        if self.physics:
            changes["physics"] = DEFAULT.with_overrides(overrides_from(self.physics))
        if self.role_table is not None:
            changes["role_table"] = self.role_table
        if self.estate is not None:
            changes["estate"] = self.estate
        return replace(spec, **changes) if changes else spec

    def write(self, directory: str | Path) -> dict[str, Path]:
        """Write the bundle. Returns what was written, keyed by kind.

        A sidecar with nothing in it is not written at all — an empty
        ``physics.json`` beside a pack would read as "these physics are the
        derivation's" when it means "the derivation moved nothing".
        """
        target = Path(directory)
        target.mkdir(parents=True, exist_ok=True)
        written: dict[str, Path] = {}

        pack_path = target / "pack.json"
        pack_path.write_text(
            json.dumps(packs.to_recipe(self.pack), indent=2, allow_nan=False) + "\n",
            encoding="utf-8",
        )
        written["pack"] = pack_path

        if self.physics:
            physics_path = target / "physics.json"
            physics_path.write_text(
                json.dumps(self.physics_document(), indent=2, allow_nan=False) + "\n",
                encoding="utf-8",
            )
            written["physics"] = physics_path

        shape = self.shape_document()
        if shape:
            shape_path = target / "shape.json"
            shape_path.write_text(
                json.dumps(shape, indent=2, allow_nan=False) + "\n", encoding="utf-8"
            )
            written["shape"] = shape_path

        return written

    def as_dict(self) -> dict[str, Any]:
        return {
            "pack": packs.to_recipe(self.pack),
            "physics": self.physics,
            **self.shape_document(),
            "unfilled": list(self.unfilled),
            "notes": list(self.notes),
            "lint": packs.lint(self.pack),
        }


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def from_variant(variant: Variant, *, name: str = "", onto: Pack | None = None) -> Derived:
    """One mosaic world, kept.

    *onto* is a pack to apply the derivation to; omitted, a skeleton is minted
    whose identity fields are placeholders ``packs.lint`` will name.
    """
    from . import mosaic

    engine = _engine(variant.engine, onto)

    # Only the engines whose mosaic actually *varies* a calendar get one
    # written. `Variant.calendar` is `retail_christmas` for the others — a
    # default, not a finding — and putting that in a pack would turn a
    # placeholder into an authored claim that a bank trades at Christmas,
    # which is the exact defect `profiles` was written to end.
    varies_calendar = any(axis.name == "calendar" for axis in mosaic.ENGINES[engine])
    seasonality = variant.calendar if varies_calendar else None

    physics = _overrides_document(variant.physics)
    role_table = variant.role_table()

    unfilled = [
        f"physics: {len(physics)} parameter range(s) — a pack has no physics field"
        " (see `worldloom pack params`), so these are written as a `--physics`"
        " sidecar and are not part of the pack",
        f"role_table: {len(role_table)} role(s) at headcount {variant.headcount},"
        f" span {variant.span}, {variant.levels} level(s) — a pack cannot state an"
        " org shape and `build` has no flag for one; carried in the shape sidecar",
    ]
    if variant.estate is not None:
        unfilled.append(
            f"estate: {variant.estate!r} — `build --estate` takes it; a pack cannot"
        )
    if not varies_calendar:
        unfilled.append(
            f"seasonality: the {engine} mosaic varies no trading year, so none is"
            " claimed — the engine's own stands"
        )
    if onto is None:
        unfilled.extend(_skeleton_unfilled(engine))
        unfilled.append(
            f"employees: a variant's headcount ({variant.headcount}) is the size of"
            " the *role table*, not the company's payroll; the two are different"
            " numbers and one is not substituted for the other"
        )

    notes = [f"mosaic world {variant.index}, seed {variant.seed}: {variant.summary()}"]
    # Said out loud rather than merged quietly. `seasonality` is the one field
    # where the derivation and the base pack can both have an opinion, and the
    # derivation winning is the whole point of `onto=` — but an author whose
    # insurer traded flat and now trades on a January peak should read that
    # here, not infer it from a revenue line.
    if onto is not None and seasonality is not None and onto.seasonality is not None:
        notes.append(
            f"seasonality: the pack's own {onto.seasonality!r} was replaced by the"
            f" variant's {seasonality!r}"
        )

    pack = (
        _applied(onto, seasonality=seasonality)
        if onto is not None
        else _skeleton(name or f"mosaic-{variant.index:02d}", engine,
                       seasonality=seasonality)
    )
    return Derived(
        pack=pack,
        physics=physics,
        role_table=role_table,
        estate=variant.estate,
        unfilled=tuple(unfilled),
        notes=tuple(notes),
    )


def from_probe(
    resolution: Resolution,
    *,
    engine: str = "",
    name: str = "probe",
    onto: Pack | None = None,
    premise: str = "",
) -> Derived:
    """A settled probe graph, kept.

    Refused while the graph is unsettled, exactly as ``probe resolve`` refuses:
    a pack carrying physics derived from reasoning nobody finished would be a
    shareable artifact whose whole claim is unfinished.
    """
    if not resolution.usable:
        raise ValueError(
            "this probe cannot produce physics yet: "
            + "; ".join([*resolution.unanswered,
                         *(str(c) for c in resolution.contradictions)])
        )
    resolved_engine = _engine(engine, onto)

    physics = _overrides_document(resolution.parameters())
    unfilled = [
        f"physics: {len(physics)} parameter range(s) — a pack has no physics field"
        " (see `worldloom pack params`), so these are written as a `--physics`"
        " sidecar and are not part of the pack",
        "seasonality: a probe derives ranges, not a trading year — nothing is"
        " claimed, so the engine's own (or the base pack's) stands",
    ]
    if onto is None:
        unfilled.extend(_skeleton_unfilled(resolved_engine))

    # Unbound leaves are the probe's own finding — a range the world needed and
    # the engine cannot read — and dropping them at the export boundary would
    # lose exactly the evidence `probe.Unbound` exists to preserve.
    notes = [f"probe: {premise}"] if premise else []
    notes.extend(
        f"unbound leaf {missing.key!r} ({missing.bounds} {missing.unit}):"
        f" {missing.claim or missing.asks} — no engine parameter reads it, so it"
        " is recorded here and carried by nothing"
        for missing in resolution.unbound
    )

    pack = (
        onto if onto is not None
        else _skeleton(name, resolved_engine, seasonality=None)
    )
    return Derived(pack=pack, physics=physics, unfilled=tuple(unfilled), notes=tuple(notes))


# ---------------------------------------------------------------------------
# The skeleton
# ---------------------------------------------------------------------------


def _engine(engine: str, onto: Pack | None) -> str:
    """The engine this export runs on, refusing a disagreement rather than
    picking a winner.

    A variant derived against banking's axes applied to a retail pack would
    build: the parameter registry is one namespace, so ``with_overrides``
    accepts a bank's parameter names and the retail generators simply never
    read them. Silently inert physics on a shareable artifact is worse than an
    error, because the pack looks derived and behaves default.
    """
    if onto is None:
        if not engine:
            raise ValueError(
                "no engine: a probe derives parameter ranges and does not know"
                " which engine draws from them. Pass engine=, or pass onto= a"
                " pack whose `base` says."
            )
        return engine
    if engine and engine != onto.base:
        raise ValueError(
            f"this derivation is for the {engine!r} engine and the pack it is"
            f" being applied to runs on {onto.base!r}. Applying it anyway would"
            " leave physics the engine never reads on a pack that looks derived."
        )
    return onto.base


def _applied(base: Pack, *, seasonality: str | None) -> Pack:
    """*base* with the derived pack-level fields applied, re-validated.

    Re-validated rather than ``model_copy``-d, because a copy skips every
    validator on ``Pack`` and the whole point of handing this back is that it
    is a pack somebody can load.
    """
    if seasonality is None:
        return base
    return Pack.model_validate({**base.model_dump(), "seasonality": seasonality})


def _default_shape(engine: str) -> Archetype:
    from . import archetypes, domains

    domain = domains.by_name(engine)
    if domain is None or not domain.default_archetype:
        raise KeyError(
            f"no registered engine named {engine!r} with a default archetype;"
            f" registered: {', '.join(domains.names())}"
        )
    return archetypes.get(domain.default_archetype)


def _skeleton(name: str, engine: str, *, seasonality: str | None) -> Pack:
    """A pack with the identity placeheld and the scale borrowed, on purpose.

    Two different kinds of blank, kept different:

    * The **nouns** — company name, industry, unit and category names — are
      ``packs.PLACEHOLDER``-marked, because there is no honest default for
      them and ``packs.lint`` names every one.
    * The **numbers and the structure** — revenue, headcount, currency, how
      many units there are and how they decompose — are the engine's default
      archetype's, verbatim and stated in ``unfilled``. Not invented: borrowed
      from a named source, which is a different claim and a weaker one.

    The reason for the second rather than a single token unit is that the
    skeleton has to *build*. An author whose whole purpose was to see derived
    physics move a figure should not first have to invent a company for the
    figure to be about.
    """
    shape = _default_shape(engine)
    todo = packs.PLACEHOLDER
    return Pack(
        name=name,
        base=engine,
        description=f"{todo} one line on what kind of business this is",
        company_name=f"{todo} name this company",
        industry=f"{todo} industry",
        currency=shape.currency,
        currency_unit=shape.currency_unit,
        fiscal_year_start_month=shape.fiscal_year_start_month,
        annual_revenue=shape.annual_revenue,
        employees=shape.employees,
        units=[
            PackUnit(
                # Not `unit_N`, and the reason is a live collision rather than
                # taste: `scenarios` recovers the unit set from the role
                # registry by stripping a `unit_` prefix, so a unit keyed
                # `unit_1` makes its own `unit_1_md` role look like a second
                # unit called `1_md` and the financial generator raises on it.
                # `unit_` is effectively reserved; a placeholder key must not
                # sit on it.
                key=f"{todo.lower()}_{index}",
                name=f"{todo} unit {index} name",
                kind=f"{todo}_kind_{index}",
                share=unit.share,
                categories=[
                    PackCategory(
                        name=f"{todo} unit {index} category {position}",
                        share=category.share,
                        margin=category.margin,
                    )
                    for position, category in enumerate(unit.categories, start=1)
                ],
                site_formats=[
                    PackSiteFormat(name=f"{todo} site format {position}",
                                   count=site.count, revenue_weight=site.revenue_weight)
                    for position, site in enumerate(unit.site_formats, start=1)
                ],
            )
            for index, unit in enumerate(shape.units, start=1)
        ],
        **({} if seasonality is None else {"seasonality": seasonality}),
    )


def _skeleton_unfilled(engine: str) -> list[str]:
    shape = _default_shape(engine)
    todo = packs.PLACEHOLDER
    return [
        f"company_name, industry, description: {todo}-marked — neither a mosaic"
        " coordinate nor an interval graph knows what the company is called or"
        " what it sells, and a name invented here would be signed with the"
        " author's",
        f"units: {len(shape.units)} unit(s) with the shares, category shares,"
        f" margins and site counts of the {engine} default archetype"
        f" ({shape.key!r}); every *name* is {todo}-marked. The structure is"
        " borrowed from a named source so the skeleton builds; the nouns are"
        " nobody's to guess",
        "lore: none — neither source makes a claim about the company's history,"
        " and lore is the lever that makes an incident likely and a persona"
        " defensive (`worldloom pack targets`)",
        "voices, system_brands, episode_text, evaluation_text, name_pools,"
        " headquarters, regions: not derived, left at the engine's own",
    ]


def _overrides_document(physics: Any) -> dict[str, Any]:
    from .parameters import overrides_document

    return overrides_document(physics)


__all__ = ["Derived", "Row", "from_probe", "from_variant"]
