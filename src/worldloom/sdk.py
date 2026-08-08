"""Worldloom as a library a model writes code against.

Every capability in this project is reachable from the CLI, and the CLI is the
wrong shape for most of what you would want to do with them. A command is a
*fixed pipeline*: it takes flags, runs one arrangement of the machinery, and
exits. ``worldloom mosaic -n 5`` is one arrangement. So is ``build``, so is
``evaluate``. Wanting a different arrangement — five organisation shapes crossed
with three trading calendars, keeping only the ones whose blast radius exceeds
ten — means either a new flag, a new command, or a shell script gluing JSON
between processes.

That ceiling is the reason this module exists, and it is a real one rather than
an aesthetic complaint. The combinatorics this project is *for* live in the
loop, and a CLI has no loop. A coding harness does: it writes Python, so give
it Python.

**The shape.** Everything is a value, nothing is a side effect until you ask
for one. A ``Blueprint`` is an immutable description of a world that has not
been built; every method returns a new one; ``build()`` is the only thing that
does work. That means a blueprint can be put in a list, crossed with another
list, sorted, filtered, sampled, and passed around before a single fact is
minted — which is exactly what a comprehension wants.

    from worldloom import sdk

    field = [
        sdk.retail().org(headcount=n, span=s).calendar(c)
        for n, s in ((18, 4), (31, 8))
        for c in ("flat", "harvest")
    ]
    worlds = [b.build().episodes("2026-01", periods=3) for b in field]

That is four worlds from three lines, and no command could have expressed it.

**Loops are values too.** ``cross``, ``sweep`` and ``dispersed`` are the three
arrangements worth naming. The first two are ordinary combinatorics; the third
is the one people get wrong, because a cartesian product of six axes is 46,656
worlds and nobody wants those — they want the eight least alike, which is
``dispersed``, and it is the same farthest-point traversal ``mosaic`` uses.

**What this does not do.** It does not relax a single invariant. A blueprint
still refuses a role table missing a spine key, physics that would close the
held-versus-central gap, or an organisation that does not fit its own depth. The
freedom here is in *arrangement*, and the constraints are what make an
arrangement worth building — a loop that could emit incoherent worlds would just
be a slower way to get noise.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field as _field, replace
from pathlib import Path
from typing import Any

from . import archetypes, domains, landscape, profiles
from .company import FUNCTIONS as _FUNCTIONS
from .parameters import DEFAULT, Parameters, Span
from .roles import from_shape, to_rows

__all__ = [
    "Blueprint", "Built", "banking", "built", "companies", "cross", "described",
    "dispersed", "company", "engine", "insurance", "mosaic_of", "outcome_selected",
    "probe_of", "retail", "sweep",
]


# ---------------------------------------------------------------------------
# A world, described but not yet built
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Blueprint:
    """An immutable description of a world. Nothing is minted until ``build()``.

    Every method returns a new blueprint rather than mutating this one, which is
    what lets a blueprint sit in a comprehension. It also means a half-configured
    blueprint is a perfectly good value to hand around — ``base = retail().org(
    span=8)`` then ``[base.calendar(c) for c in calendars]`` is the ordinary way
    to use this, and it only works because ``base`` cannot be spoiled by what is
    done to its descendants.
    """

    domain_name: str = "retail"
    seed: int = 8128
    archetype_key: str | None = None
    physics_overrides: Mapping[str, Span] = _field(default_factory=dict)
    shape: Mapping[str, Any] | None = None
    calendar_name: str | None = None
    estate_size: str | None = None
    estate_vocabulary: str | None = None
    employees: int | None = None
    annual_revenue: int | None = None
    """The company's scale in the archetype's own ``currency_unit``. Unlike
    ``employees`` this one is load-bearing on every path — every money fact in
    the corpus is derived from it (``generators/finance``) — which is why it is
    worth a field of its own rather than being left to a pack."""

    pack_source: Any = None
    """A ``packs.Pack`` this world is built from, or ``None``. Held rather than
    folded into ``archetype_key`` because a pack is not a shape: it also carries
    the company's name, its lore, its voices and its geography, and
    ``World.from_pack`` is a different constructor from ``World(...)``."""

    vocabulary_name: str = ""
    """Which ``worldloom.vocabulary`` preset this world's divisions, categories
    and site formats are named from. Empty is the archetype's own words, and
    empty is byte-identical to a build made before this field existed —
    ``vocabulary.spoken`` returns the archetype untouched for an empty name,
    which is the property that lets ``build`` apply it unconditionally.

    Here because ``mosaic_of`` was dropping it. A mosaic deals its worlds
    distinct vocabularies precisely so that no two of them are the same company
    (``mosaic._vocabularies``), and a blueprint that carried the mosaic's
    shape, seed, physics and estate but not its words rebuilt a world the
    mosaic never planned."""

    locale_name: str | None = None
    """The jurisdiction this corpus is written in. Applied to the *recipe*
    after the build rather than to the builder, because that is where a locale
    lives — ``recipe.locale_of`` argues out why — and no world spec accepts
    one."""

    master_data_counts: Mapping[str, int] | None = None
    """Reference tables to mint at build — ``{"vendors": 2000, "skus": 500}``.
    ``None`` mints nothing; see ``RetailWorld.master_data`` for the contract
    (opt-in, own stream, counts on the recipe, rows on ``masterdata.json``)."""

    facet_choices: Mapping[str, str] = _field(default_factory=dict)
    role_rows: tuple[tuple[str, str, str, str | None], ...] = ()
    """A finished organisation, when something upstream already built one — a
    resolved company specification is the case this exists for. Kept apart from
    ``shape``/``implied_roles`` rather than reverse-engineered into them,
    because a table that has already passed ``roles.review`` is a stronger
    thing than the shape it came from, and re-synthesising it here would throw
    away the leadership rows a describer wrote by hand."""

    lob_specs: tuple[Any, ...] = ()
    """The ``lob.Lob`` specs attached by ``.lob()``, kept whole rather than
    flattened into ``implied_roles``, because a LOB is more than its rows:
    its responsibility edges are what ``participation`` joins against a
    process's minted kinds, and its slot bindings are the company's half of a
    process's ordering. The rows still land in ``implied_roles`` — the build
    reads only those — so keeping the spec adds derivation, not a second
    account of the organisation."""

    implied_roles: tuple[tuple[str, str, str, str | None], ...] = ()
    implied_lore: tuple[Any, ...] = ()
    """The ``facets.LoreClaim``s the chosen facets commit this world to, minted
    into real commitments by the domain's build. Claims rather than commitments
    because a blueprint mints nothing — the ids have to come off the build's own
    ``Minter``, in sequence, after the domain's own lore."""

    unmet: tuple[str, ...] = ()
    """Consequences the chosen facets have that nothing implements. Carried
    rather than dropped, so a caller can read what their claims committed to
    and the engine did not honour — the same evidence a probe's unbound leaf
    is."""

    # -- description -------------------------------------------------------

    def seeded(self, seed: int) -> Blueprint:
        return replace(self, seed=seed)

    def archetype(self, key: str) -> Blueprint:
        """A specific archetype rather than the domain's default."""
        return replace(self, archetype_key=key)

    def physics(self, **spans: tuple[float, float] | Span) -> Blueprint:
        """Override world-physics ranges by their registry name.

        Dots are not valid in a keyword, so underscores stand in for them:
        ``physics(retail_margin_erosion=(0.10, 0.15))`` sets
        ``retail.margin.erosion``. Ugly, and the alternative — a dict positional
        — reads worse in the comprehensions this module exists to serve. An
        unknown name is refused by ``Parameters.with_overrides``, so a typo is
        an error rather than a silently ordinary world.
        """
        resolved: dict[str, Span] = dict(self.physics_overrides)
        for key, value in spans.items():
            name = key.replace("_", ".") if "." not in key else key
            name = _nearest_parameter(name)
            resolved[name] = value if isinstance(value, Span) else Span(*value)
        return replace(self, physics_overrides=resolved)

    def org(
        self,
        *,
        headcount: int | None = None,
        span: int | None = None,
        levels: int | None = None,
        functions: Sequence[str] | None = None,
    ) -> Blueprint:
        """The organisation as a shape, synthesised into a role table at build.

        Partial: ``org(span=8)`` leaves headcount and depth at whatever a
        previous call set, or at defaults. That matters for the comprehension
        case, where one axis varies and the rest are held.
        """
        current = dict(self.shape or {"headcount": 23, "span": 5, "levels": 3})
        for key, value in (("headcount", headcount), ("span", span),
                           ("levels", levels), ("functions", functions)):
            if value is not None:
                current[key] = value
        return replace(self, shape=current)

    def calendar(self, name: str) -> Blueprint:
        """The trading year, by name from ``worldloom.profiles``."""
        profiles.named(name)          # refuse an unknown one here, not at build
        return replace(self, calendar_name=name)

    def speaking(self, name: str) -> Blueprint:
        """The words this company uses, by preset from ``worldloom.vocabulary``.

        Changes what the units are *called* and nothing about what they are —
        no share, no margin, no site count moves. Refuses an unknown preset
        here rather than at build, for ``calendar``'s reason: a comprehension
        crossing four vocabularies should fail on the typo, not four worlds
        later.
        """
        from . import vocabulary

        if name:
            vocabulary.named(name)
        return replace(self, vocabulary_name=name)

    def estate(self, size: str, *, vocabulary: str | None = None) -> Blueprint:
        """How much technology landscape, and optionally whose vocabulary."""
        if vocabulary is not None:
            landscape.named(vocabulary)
        return replace(self, estate_size=size, estate_vocabulary=vocabulary)

    def facets(self, **chosen: str) -> Blueprint:
        """What the company *is* — listed, legacy, private-equity owned.

        The extensible half of the schema. A facet is a claim with
        consequences: it emits parameter ranges, lore, roles, a calendar and an
        estate into the vocabularies the engine already reads, so describing a
        new kind of company is data rather than a generator edit.

        Applied on top of whatever was set explicitly, and explicit wins — a
        caller who says ``.calendar("harvest").facets(trading_pattern="steady")``
        gets harvest, because they said it and the facet only implies it. The
        reverse would make the last call silently authoritative over the more
        specific one.

        Contradictory facets are refused here rather than at build: a comprehension
        crossing six facets should fail on the combination that cannot hold, not
        fifty worlds later.
        """
        from . import facets as facets_module

        resolved = facets_module.resolve(**chosen)
        if not resolved.ok:
            raise ValueError("; ".join(str(c) for c in resolved.conflicts))

        # Lore used to be reported here as unmet, because a blueprint had no
        # seam to add to a domain's own and carrying an inert constraint is the
        # exact failure `packs.lint` exists to catch. `world.extend_lore` is that
        # seam now, so lore is carried and minted like roles are, and `unmet` is
        # back to meaning only what it says: consequences nothing implements.
        unmet = list(resolved.wants)

        merged = dict(resolved.physics)
        merged.update(self.physics_overrides)          # explicit wins
        return replace(
            self,
            physics_overrides=merged,
            calendar_name=self.calendar_name or resolved.calendar,
            estate_size=self.estate_size or resolved.estate,
            facet_choices=dict(resolved.chosen),
            implied_roles=resolved.roles,
            implied_lore=resolved.claims,
            unmet=tuple(unmet),
        )

    def staff(self, employees: int) -> Blueprint:
        """The archetype's stated headcount — the *company's* size, which is a
        different claim from how many people the corpus names."""
        return replace(self, employees=employees)

    def revenue(self, annual: int) -> Blueprint:
        """Annual revenue, in the archetype's own ``currency_unit``.

        A value and not a range, because the engine reads it once: every money
        fact in the corpus is a share of this figure. Contrast ``physics``,
        which sets the bands the engine *draws inside*.
        """
        return replace(self, annual_revenue=annual)

    def master_data(self, **counts: int) -> Blueprint:
        """Mint relational reference tables at build — vendors, customers, SKUs.

            sdk.company("procurement").master_data(vendors=2000, skus=500)

        Counts, validated here rather than at build (``sweep`` over forty
        worlds should fail on the typo, not forty builds later), and recorded
        on the recipe so a replay re-mints the same rows. The engines that ship
        here all accept the knob; a domain registered outside this repository
        that does not will refuse it at ``build()`` by field name.
        """
        from .generators.masterdata import check_request

        return replace(self, master_data_counts=check_request(counts))

    def located(self, locale: str) -> Blueprint:
        """The jurisdiction. Refuses an unknown one here rather than at render.

        Reaches the figure grammar corpus-wide. Whether it reaches the people,
        the regions and the head office as well depends on there being a pack:
        that half has one door and it is ``organisation.generate``'s
        ``name_pools``/``regions``/``headquarters``, which only a pack fills.
        ``worldloom.company`` composes one when a description carries an
        identity; a bare blueprint does not, so this is the render half alone.
        """
        from . import locales

        locales.named(locale)
        return replace(self, locale_name=locale)

    def pack(self, source: Any) -> Blueprint:
        """Build from an authored pack — its shape, lore, name and geography.

        Refuses the fields a pack already states, rather than picking a winner.
        A pack *is* the company; a blueprint field beside it would be a second
        account of the same thing, which is what the recipe exists to make
        impossible.
        """
        from . import packs

        loaded = source if hasattr(source, "units") else packs.load(source)
        restated = [
            name for name, given in (
                ("archetype", self.archetype_key is not None),
                ("staff", self.employees is not None),
                ("revenue", self.annual_revenue is not None),
            ) if given
        ]
        if restated:
            raise ValueError(
                f"a pack already states {restated}; drop those calls or edit the"
                " pack — a build with two answers has no rule for which wins"
            )
        return replace(self, pack_source=loaded, domain_name=loaded.base)

    def lob(
        self,
        spec: Any,
        *,
        bind: Mapping[str, Mapping[str, str]] | None = None,
    ) -> Blueprint:
        """Attach a LOB: its roles join the organisation, its spec is kept.

        A LOB (Line of Business) spec declares roles and responsibilities.
        The roles are appended to the implicit role list (after facet roles)
        so they are included in the final organisation; the spec itself is
        kept on ``lob_specs`` so ``participation`` can derive who is in a
        process from the responsibility edges.

        ``bind`` is the blueprint's way of seating this LOB's roles into a
        process's declared slots without editing the LOB —
        ``bind={"QuarterlyCapitalReturn": {"preparer": "controller"}}`` adds
        ``lob.SlotBinding`` rows to the attached copy. A binding naming a role
        the LOB lacks is refused here, at the call that made the claim, rather
        than surfacing later as a seat filled by nobody; the other half of the
        lint — a required slot left unbound — needs the process spec and lives
        in ``lob.lint_bindings``.

        Args:
            spec: A ``lob.Lob`` or dict matching its shape.
            bind: Optional ``{process: {slot: role_key}}`` bindings to add.

        Returns:
            A new Blueprint with the LOB attached.
        """
        from . import lob as lob_module

        loaded = spec if hasattr(spec, "roles") else lob_module.Lob.model_validate(spec)
        if bind:
            added = [
                lob_module.SlotBinding(process=process, slot=slot, role_key=role_key)
                for process, seats in bind.items()
                for slot, role_key in seats.items()
            ]
            loaded = loaded.model_copy(
                update={"slot_bindings": list(loaded.slot_bindings) + added}
            )
        role_keys = {role.key for role in loaded.roles}
        orphaned = sorted(
            {b.role_key for b in loaded.slot_bindings if b.role_key not in role_keys}
        )
        if orphaned:
            raise ValueError(
                f"LOB {loaded.name!r} binds roles it does not declare:"
                f" {orphaned}. A slot binding seats one of the LOB's own roles;"
                f" its roles are {sorted(role_keys)}."
            )
        lob_rows = tuple(role.as_row() for role in loaded.roles)
        combined = list(self.implied_roles) + list(lob_rows)
        return replace(self, implied_roles=tuple(combined),
                       lob_specs=self.lob_specs + (loaded,))

    def participation(self, process: Any) -> dict[str, tuple[Any, ...]]:
        """Who is in *process*, per attached LOB — derived, never stored.

        *process* is an ``episodes.EpisodeSpec`` or the name of one already
        installed in this Python process. The result maps each attached LOB's
        name to its ``lob.Participant`` rows: the join of the LOB's
        responsibility edges against the kinds the process's steps mint, plus
        whoever the slot bindings seat. LOBs with nobody in the process are
        omitted rather than reported empty, so the dict reads as the answer to
        "who shows up", not as a roster of everyone asked.
        """
        from . import episodes, lob as lob_module

        if hasattr(process, "fact_kinds"):
            spec = process
        else:
            spec = episodes.loaded().get(process)
            if spec is None:
                raise KeyError(
                    f"no process named {process!r} is installed —"
                    " call episodes.install(episodes.load(...)) first, or pass"
                    " the EpisodeSpec itself"
                )
        joined: dict[str, tuple[Any, ...]] = {}
        for attached in self.lob_specs:
            participants = lob_module.participation(attached, spec)
            if participants:
                joined[attached.name] = participants
        return joined

    # -- realisation -------------------------------------------------------

    @property
    def parameters(self) -> Parameters:
        return DEFAULT.with_overrides(dict(self.physics_overrides))

    @property
    def seasonality(self) -> profiles.Seasonality | None:
        """The trading year this world is built *and run* under.

        A pack's own wins, and reading it here rather than only in ``build`` is
        load-bearing: ``World.from_pack`` puts the pack's year on the builder,
        ``build_recipe`` records it, and ``recipe.rebuild`` hands the recorded
        year to *every episode*. So a blueprint that built under the pack's year
        and ran its closes under none would produce a corpus its own recipe
        rebuilds differently — the one failure a recipe exists to make
        impossible, and silent, because both corpora validate.
        """
        if self.pack_source is not None:
            from . import packs

            packed = packs.seasonality_of(self.pack_source)
            if packed is not None:
                return packed
        return None if self.calendar_name is None else profiles.named(self.calendar_name)

    def role_table(self) -> tuple[tuple[str, str, str, str | None], ...] | None:
        """The organisation, including any role a facet says must exist.

        A facet's roles are appended rather than merely recorded, because an
        audit committee chair is what "listed" *means* operationally — a corpus
        claiming to be listed without one has not modelled it, and a blueprint
        that carried the role without minting it would be the carried-and-inert
        failure this project spends most of its invariants catching.

        Appended after the synthesised table so the shape a caller asked for is
        still the shape they get, plus whatever their claims oblige. That does
        mean headcount exceeds what `org()` requested; the alternative is
        dropping a role the claim requires, which is worse and quieter.
        """
        if self.role_rows:
            return self.role_rows
        if self.shape is None and not self.implied_roles:
            return None
        rows: list[tuple[str, str, str, str | None]] = []
        if self.shape is not None:
            shape = dict(self.shape)
            rows = list(to_rows(from_shape(
                functions=shape.get("functions") or _FUNCTIONS[:shape["levels"] + 2],
                headcount=shape["headcount"], span=shape["span"], levels=shape["levels"],
                engine=self.domain_name,
            )))
        else:
            from .generators import organisation

            rows = list(organisation._ROLES)
        have = {row[0] for row in rows}
        rows.extend(role for role in self.implied_roles if role[0] not in have)
        return tuple(rows)

    def describe(self) -> dict[str, Any]:
        """What this blueprint says, without building it.

        Worth having for the same reason ``mosaic --describe`` is: deciding
        whether a field of forty worlds is worth the wait should not require
        building forty worlds.
        """
        return {
            "engine": self.domain_name,
            "seed": self.seed,
            "archetype": self.archetype_key,
            "shape": dict(self.shape) if self.shape else None,
            "calendar": self.calendar_name,
            "estate": self.estate_size,
            "vocabulary": self.vocabulary_name,
            "locale": self.locale_name,
            "revenue": self.annual_revenue,
            "pack": None if self.pack_source is None else self.pack_source.name,
            "physics": {name: span.as_dict()
                        for name, span in sorted(self.physics_overrides.items())},
            "master_data": (dict(self.master_data_counts)
                            if self.master_data_counts else None),
            "facets": dict(sorted(self.facet_choices.items())),
            # Which claims will put lore in the corpus, by source rather than by
            # count: "2 commitments" tells a reader deciding whether to build
            # forty worlds nothing, and `listing:listed` tells them what changed.
            "lore": [claim.source for claim in self.implied_lore],
            "unmet": list(self.unmet),
        }

    def build(self) -> Built:
        """Mint the world. The only method here that does any work."""
        registered = domains.by_name(self.domain_name)
        if registered is None:
            raise KeyError(
                f"no domain named {self.domain_name!r}; known: {domains.names()}"
            )
        key = self.archetype_key or registered.default_archetype

        changes: dict[str, Any] = {"physics": self.parameters}
        table = self.role_table()
        if table is not None:
            changes["role_table"] = table
        if self.seasonality is not None:
            changes["seasonality"] = self.seasonality
        if self.estate_size is not None:
            changes["estate"] = self.estate_size
        if self.implied_lore:
            # Only when there is something to add. An unconditional keyword would
            # be harmless here but would make every domain outside this
            # repository have to accept the field before any of its worlds could
            # be built at all — the same reason `estate` and `seasonality` above
            # are conditional.
            changes["lore_claims"] = self.implied_lore
        if self.master_data_counts:
            # Conditional for the same out-of-tree-domain reason as the rest.
            changes["master_data"] = dict(self.master_data_counts)

        if self.pack_source is not None:
            # A different constructor, not a different argument: `from_pack`
            # resolves the archetype, the lore and the trading year off the
            # pack, and reproducing that here would be a second implementation
            # of the pack contract that could drift from the one the CLI uses.
            spec = registered.world.from_pack(self.pack_source, seed=self.seed)
        else:
            from .vocabulary import spoken

            spec = registered.world(
                # `spoken` with an empty name returns the archetype itself, so
                # this line is byte-identical to `archetypes.get(key)` for every
                # blueprint that never called `.speaking()` — which is what lets
                # it be applied unconditionally rather than behind a branch.
                seed=self.seed, archetype=spoken(archetypes.get(key), self.vocabulary_name),
                **({} if self.employees is None else {"employees": self.employees}),
                **({} if self.annual_revenue is None
                   else {"annual_revenue": self.annual_revenue}),
            )
        # `replace` rather than constructor keywords: a domain registered
        # outside this repository may not accept every field, and this way the
        # failure names the field rather than being a TypeError on a keyword
        # nobody can see from the call site.
        for name, value in changes.items():
            try:
                spec = replace(spec, **{name: value})
            except TypeError as exc:
                raise TypeError(
                    f"{type(spec).__name__} does not accept {name!r}: {exc}"
                ) from exc
        if self.locale_name is not None:
            try:
                # When the engine's builder has a `locale` field the build half
                # reaches the generators directly — regions, name pools, head
                # office. When it does not, this is a no-op and the render half
                # below is all a locale gets; `company.resolve` reports that
                # shortfall rather than leaving it to be discovered.
                spec = replace(spec, locale=self.locale_name)
            except TypeError:
                pass
        world = spec.build()
        if self.locale_name is not None:
            # On the recipe, after the build, exactly as `cli._localised` does
            # it and for the reason `recipe.locale_of` gives: the recipe is the
            # only document a corpus has that is singular, so two artifacts
            # cannot disagree about how a figure is spelled. Doing it here
            # rather than in `Built` means a blueprint's world is localised
            # before any episode runs, which is where `recipe.rebuild` puts it.
            from .recipe import with_locale

            world = world.extend(recipe=with_locale(world.recipe, self.locale_name))
        return Built(world, self)


def _nearest_parameter(name: str) -> str:
    """A registry name from an underscored keyword, refusing an ambiguous one.

    ``retail_margin_erosion`` is unambiguous once dots are restored, but
    ``ops_incident_hypothesis_minutes`` is not — the underscore inside
    ``hypothesis_minutes`` is part of the leaf. So the match is against the real
    registry rather than by splitting: exactly one parameter whose dots-to-
    underscores form equals the keyword, or an error naming the candidates.
    """
    from .parameters import DEFAULTS

    if name in DEFAULTS:
        return name
    flat = name.replace(".", "_")
    matches = [real for real in DEFAULTS if real.replace(".", "_") == flat]
    if len(matches) == 1:
        return matches[0]
    raise KeyError(
        f"no parameter matches {name!r}."
        + (f" Did you mean one of {matches}?" if matches else
           " Run `worldloom pack params` for the registry.")
    )


# ---------------------------------------------------------------------------
# A world that exists
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Built:
    """A minted world, plus the blueprint that described it.

    Keeping the blueprint is not sentiment: a caller filtering a field of forty
    built worlds wants to know *which description* produced the one that came
    out interesting, and reconstructing that from the world is guesswork.
    """

    world: Any
    blueprint: Blueprint

    def episodes(
        self,
        start: str,
        *,
        periods: int = 1,
        incident: bool | None = None,
    ) -> Built:
        """Run this world's own episode, *periods* times from *start*.

        The domain decides what an episode is and how far apart they land — the
        retail close is monthly, a capital return quarterly — so this does not
        take a cadence. A caller who wants a *history* rather than a repetition
        wants ``worldloom.timeline``.
        """
        from .scenarios import MonthEndClose

        registered = domains.by_name(self.blueprint.domain_name)
        assert registered is not None
        world = self.world
        for index in range(max(1, periods)):
            stamp = _step(start, index, registered.period_step_months)
            if registered.single_episode is not None:
                episode = replace(registered.single_episode(stamp),
                                  physics=self.blueprint.parameters)
            else:
                episode = MonthEndClose(
                    period=stamp, include_operational_incident=incident,
                    physics=self.blueprint.parameters,
                    seasonality=self.blueprint.seasonality,
                )
            world = world.run(episode)
        return replace(self, world=world)

    def run(self, *scenarios: Any) -> Built:
        """Run arbitrary scenarios in order — the escape hatch under ``episodes``."""
        world = self.world
        for scenario in scenarios:
            world = world.run(scenario)
        return replace(self, world=world)

    # -- measurement, so a loop can filter on what came out ----------------

    def validate(self) -> Any:
        return self.world.validate()

    @property
    def ok(self) -> bool:
        return self.world.validate().ok

    def topology(self) -> dict[str, Any]:
        """Blast radius, chokepoints and depth — what a loop filters on.

        The graph subset of ``measure()``, projected from it rather than
        computed again: the extra work is one walk over the people list, and
        the alternative is two definitions of "chokepoint" that a future edit
        can move independently.
        """
        from . import outcomes

        measured = outcomes.shape_vector(self.world)
        return {key: measured[key] for key in ("nodes", "chokepoints", "longest_chain")}

    def measure(self) -> dict[str, Any]:
        """A shape vector for this corpus. Enough to sort or disperse a field on.

        The same eight numbers ``outcomes.shape_vector`` reads, and now
        literally them: an outcome-selected field and a hand-filtered loop have
        to agree about what a chokepoint is, and two copies of this walk were
        how they could stop agreeing. Imported here rather than at module level
        because ``outcomes`` imports ``stats``, which imports the retrieval
        index — a cost no caller of ``sdk.retail()`` should pay.
        """
        from . import outcomes

        return outcomes.shape_vector(self.world)

    def export(self, out: str | Path, *, overwrite: bool = True) -> Path:
        return self.world.export(Path(out), overwrite=overwrite)

    def render(self, *formats: str, out: str | Path | None = None) -> Path:
        """Render to xlsx/docx/pdf/pptx/markdown and write the corpus."""
        rendered = self.world.render(*formats)
        return rendered.export(Path(out) if out else Path("."), overwrite=True)


def _step(period: str, index: int, months: int) -> str:
    year, month = (int(part) for part in period.split("-"))
    total = (year * 12 + month - 1) + index * months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ---------------------------------------------------------------------------
# Starting points
# ---------------------------------------------------------------------------


def company(engine: str, *, seed: int = 8128) -> Blueprint:
    """A blueprint for any registered industry, by engine name.

    THE front door, and industry-neutral on purpose. The named conveniences
    below (`retail()`, `banking()`, ...) predate the fourth vertical and were
    never extended to it — `procurement` had no named entry at all, which is
    the tell: a per-industry function is a list somebody has to remember to
    grow, and the registry already knows every engine including ones authored
    outside this repository. Name the industry as data, not as an import.
    """
    if domains.by_name(engine) is None:
        raise KeyError(f"no domain named {engine!r}; known: {domains.names()}")
    return Blueprint(domain_name=engine, seed=seed)


def engine(name: str, *, seed: int = 8128) -> Blueprint:
    """A blueprint for any registered domain by name. Alias of `company`."""
    return company(name, seed=seed)


def described(
    specification: Any,
    *,
    seed: int = 8128,
    strict: bool = True,
) -> Blueprint:
    """A blueprint from a company specification — a document, a path, or a spec.

    The one entry point that starts from *what kind of company this is* rather
    than from which engine builds it. Everything it sets, a caller could set by
    hand; what it adds is that the nine surfaces are resolved together, so a
    contradiction between two of them is a sentence rather than a corpus.

        sdk.described({"industry": "general insurance", "geo": "germany",
                       "facets": {"listing": "listed", "trading_pattern": "steady"}})

    The result is an ordinary ``Blueprint``, which is the point: it can be
    crossed, swept, dispersed, and further constrained like any other, and the
    description is not carried past this call. ``worldloom.company.resolve``
    returns the same resolution with its ``unmet`` list intact when you want to
    read what the description committed to and the engine did not honour.

    ``strict=False`` returns a blueprint even when the description conflicts,
    for a caller who wants to inspect the conflicts rather than catch them.
    Nothing downstream is relaxed: the same refusals fire again at ``build()``,
    because they are the engine's and not this function's.
    """
    from . import company as company_module

    spec = (specification if isinstance(specification, company_module.CompanySpec)
            else company_module.from_document(specification))
    resolution = company_module.resolve(spec)
    if strict:
        resolution.raise_for_conflicts()
    return from_resolution(resolution, seed=seed)


def from_resolution(resolution: Any, *, seed: int = 8128) -> Blueprint:
    """A resolved specification as a blueprint. The bridge, made addressable.

    Separate from ``described`` so that a caller who resolved a description
    themselves — to read its ``unmet``, or to amend it — does not have to
    resolve it twice. Deliberately mechanical: every assignment below is a
    consequence the resolution already computed and argued for, and this
    function makes no decision of its own.
    """
    blueprint = Blueprint(
        domain_name=resolution.engine or "retail",
        seed=seed,
        archetype_key=resolution.archetype_key or None,
        physics_overrides=dict(resolution.physics),
        calendar_name=resolution.calendar,
        estate_size=resolution.estate,
        locale_name=resolution.locale,
        facet_choices=dict(resolution.facet_choices),
        implied_lore=tuple(resolution.lore_claims),
        master_data_counts=(dict(resolution.master_data)
                            if resolution.master_data else None),
        unmet=tuple(resolution.unmet),
    )
    if resolution.pack is not None:
        # A pack carries the shape, the scale and the name, so the fields it
        # states are not set beside it — `Blueprint.pack` refuses exactly those,
        # and this is why: two accounts of one company is what the resolution
        # already refused one layer up.
        return replace(blueprint, pack_source=resolution.pack,
                       domain_name=resolution.pack.base, archetype_key=None,
                       role_rows=resolution.role_table or ())
    return replace(
        blueprint,
        employees=resolution.employees,
        annual_revenue=resolution.annual_revenue,
        role_rows=resolution.role_table or (),
    )


# Kept as conveniences for existing callers and docs; `company()` is the
# canonical, industry-neutral path and the only one a new engine appears in
# automatically.
def retail(*, seed: int = 8128) -> Blueprint:
    return company("retail", seed=seed)


def banking(*, seed: int = 8128) -> Blueprint:
    return engine("banking", seed=seed)


def insurance(*, seed: int = 8128) -> Blueprint:
    return engine("insurance", seed=seed)


# ---------------------------------------------------------------------------
# Loops
# ---------------------------------------------------------------------------


def cross(base: Blueprint, **axes: Sequence[Any]) -> tuple[Blueprint, ...]:
    """Every combination of the given axes, applied to *base*.

    An axis name is a ``Blueprint`` method — ``cross(b, calendar=[...],
    estate=[...])`` calls ``.calendar(c).estate(e)`` for every pair. Ordinary
    cartesian product, ordered by ``itertools.product`` so the result is stable.

    Grows the way a product grows: three axes of four values is sixty-four
    worlds. That is the honest behaviour and why ``dispersed`` exists beside it.
    """
    names = sorted(axes)
    for name in names:
        if not hasattr(base, name):
            raise AttributeError(
                f"a blueprint has no {name!r} to vary; try one of"
                f" {sorted(m for m in dir(base) if not m.startswith('_'))}"
            )
    out: list[Blueprint] = []
    for combination in itertools.product(*(axes[name] for name in names)):
        blueprint = base
        for name, value in zip(names, combination, strict=True):
            method = getattr(blueprint, name)
            blueprint = method(**value) if isinstance(value, dict) else method(value)
        out.append(blueprint)
    return tuple(out)


def sweep(base: Blueprint, axis: str, values: Iterable[Any]) -> tuple[Blueprint, ...]:
    """One axis, many values. The degenerate ``cross``, named because it is what
    you want when asking "what does *this* knob do" rather than exploring."""
    return cross(base, **{axis: list(values)})


def dispersed(
    candidates: Sequence[Blueprint],
    count: int,
    *,
    key: Callable[[Blueprint], Sequence[float]] | None = None,
) -> tuple[Blueprint, ...]:
    """The *count* blueprints least like each other.

    The arrangement people get wrong. A cartesian product of six axes is 46,656
    worlds and nobody wants those — they want the eight least alike, and taking
    the first eight of a product gives eight that differ only in the last axis,
    because that is what a product's ordering does.

    Same farthest-point traversal ``mosaic`` uses. ``key`` maps a blueprint to
    coordinates; the default reads the numeric parts of ``describe()``,
    normalised across the candidate set so no one wide dimension decides what
    "unlike" means.
    """
    from .dispersion import farthest_first, manhattan

    if count > len(candidates):
        raise ValueError(f"cannot select {count} from {len(candidates)}")
    if key is not None:
        vectors = [list(key(b)) for b in candidates]
    else:
        # One key space across the whole candidate set, not per blueprint.
        # Blueprints carry different numbers of physics overrides — a facet that
        # implies two and one that implies none — so a per-blueprint vector has
        # a per-blueprint length and nothing can be compared to anything.
        vectors = _normalised(_vectors(candidates))
    chosen = farthest_first(vectors, manhattan, count)
    return tuple(candidates[at] for at in chosen)


def outcome_selected(
    candidates: Sequence[Blueprint],
    count: int,
    *,
    start: str = "2026-03",
    periods: int = 1,
    incident: bool | None = None,
) -> tuple[Built, ...]:
    """``dispersed``'s sibling that looks at what came out.

    ``dispersed`` measures the *descriptions*: headcount, calendar index,
    estate, the low end of every physics override. That is a proxy, and this
    module has never said how good a one. Two descriptions far apart in that
    space can produce corpora that measure identically — a margin band no
    figure lands in — and two close ones can differ sharply, because one more
    reporting level changes who signs what and therefore what the evaluation
    generator can ask.

    So this builds every candidate, runs its episodes, compiles, measures the
    corpora with the instruments this repository already owns, and runs the
    same farthest-point traversal over the **measurements**. See
    ``worldloom.outcomes`` for what is measured and for why the safe objective
    is spread rather than difficulty.

    Returns ``Built`` worlds rather than blueprints, and that is not a
    convenience: the candidates have already been built to be measured, and
    handing back descriptions would make the caller pay for the whole field a
    second time. It also costs what it costs — a pool of thirty is thirty
    builds — so this is the call to reach for when the field is tens, not
    thousands. Cut a large product down with ``dispersed`` first, then measure
    what survives.
    """
    from . import outcomes

    field = outcomes.pool(candidates, start=start, periods=periods, incident=incident)
    chosen = field.select(count)
    return tuple(Built(field.worlds[at], candidates[at]) for at in chosen)


def _vectors(candidates: Sequence[Blueprint]) -> list[list[float]]:
    """Coordinates for a whole candidate set, over one shared key space.

    The keys are the union of every parameter and every facet any candidate
    mentions, so a blueprint that says nothing about a dimension sits at zero on
    it rather than having a shorter vector. That is also the honest reading:
    "this one does not claim anything here" is a position in the space, not a
    missing measurement.
    """
    described = [b.describe() for b in candidates]
    parameters = sorted({name for d in described for name in d["physics"]})
    facet_names = sorted({name for d in described for name in d["facets"]})
    calendars = sorted(profiles.PROFILES)
    estates = ("none", "small", "medium", "large")

    vectors: list[list[float]] = []
    for d in described:
        shape = d["shape"] or {}
        row = [
            float(shape.get("headcount", 0)), float(shape.get("span", 0)),
            float(shape.get("levels", 0)),
            float(calendars.index(d["calendar"]) if d["calendar"] in calendars else -1),
            float(estates.index(d["estate"] or "none")),
        ]
        row += [float(d["physics"][name]["low"]) if name in d["physics"] else 0.0
                for name in parameters]
        # A facet choice is categorical, so its index carries no order — but it
        # does carry *difference*, which is all a dispersion measure needs.
        row += [float(_choice_index(name, d["facets"].get(name))) for name in facet_names]
        vectors.append(row)
    return vectors


def _choice_index(facet: str, value: str | None) -> int:
    from . import facets as facets_module

    if value is None:
        return -1
    return list(facets_module.choices(facet)).index(value)


def _normalised(vectors: Sequence[Sequence[float]]) -> list[list[float]]:
    """Each coordinate scaled to [0, 1] across the set.

    Without this, headcount runs to forty and a margin runs from 0.2 to 0.6, so
    headcount decides entirely what "unlike" means and every selection differs
    in one dimension while looking identical in the rest.
    """
    if not vectors:
        return []
    columns = list(zip(*vectors, strict=True))
    spans = [(min(column), max(column)) for column in columns]
    return [
        [0.0 if high == low else (value - low) / (high - low)
         for value, (low, high) in zip(vector, spans, strict=True)]
        for vector in vectors
    ]


# ---------------------------------------------------------------------------
# Bridges to what already exists
# ---------------------------------------------------------------------------


def mosaic_of(count: int, *, engine: str = "retail", seed: int = 8128) -> tuple[Blueprint, ...]:
    """``mosaic.field`` as blueprints, so its worlds can join an ordinary loop.

    The mosaic picks a well-dispersed field over axes it chose; this returns
    them as values a caller can further constrain, filter, or cross with
    something else before building any of them.
    """
    from . import mosaic as mosaic_module

    return tuple(_from_variant(v) for v in mosaic_module.field(count, seed=seed, engine=engine))


def probe_of(session: Any, count: int, *, engine: str = "retail",
             seed: int = 8128) -> tuple[Blueprint, ...]:
    """``mosaic.from_probe`` as blueprints — a model's derived space, as values."""
    from . import mosaic as mosaic_module

    return tuple(_from_variant(v) for v in
                 mosaic_module.from_probe(session, count, seed=seed, engine=engine))


def _from_variant(variant: Any) -> Blueprint:
    from . import mosaic as mosaic_module

    # Only when this engine's mosaic actually varies a trading year. `Variant`
    # always carries one — `mosaic._DEFAULT_CALENDAR` for an engine that reads
    # none — and passing it on made `build()` hand a `seasonality` to a world
    # spec with no such field, so every blueprint from `mosaic_of(n,
    # engine="banking")` raised `TypeError` the moment it was built. Latent
    # until now because nothing built one: `test_sdk` counted the blueprints.
    # `cli.mosaic` draws the same guard for the same reason.
    varies_calendar = any(
        axis.name == "calendar" for axis in mosaic_module.ENGINES[variant.engine]
    )
    return Blueprint(
        domain_name=variant.engine,
        seed=variant.seed,
        physics_overrides=dict(variant.overrides),
        shape={"headcount": variant.headcount, "span": variant.span,
               "levels": variant.levels, "functions": list(variant.functions)},
        calendar_name=variant.calendar if varies_calendar else None,
        estate_size=variant.estate,
        # The words the mosaic dealt this world, which this bridge used to
        # drop. A mosaic deals distinct vocabularies so that no two of its
        # worlds are the same company; a blueprint that carried everything
        # except the words rebuilt a world the mosaic never planned, and the
        # only symptom was that `sdk.mosaic_of(5)` and `worldloom mosaic -n 5`
        # disagreed about what the divisions were called.
        vocabulary_name=variant.vocabulary,
    )


def built(blueprints: Iterable[Blueprint]) -> Iterator[Built]:
    """Build lazily, so a caller can stop early without minting the rest."""
    for blueprint in blueprints:
        yield blueprint.build()


def companies(base: Blueprint, *facet_names: str, limit: int | None = None) -> tuple[Blueprint, ...]:
    """Every *consistent* combination of the named facets, as blueprints.

    Consistent, not every combination. The full product of the seven shipped
    facets is 6,480 and only 3,720 of those describe a company that can exist —
    no listed mutual, no premium-margin commodity business. Handing a caller the
    product to filter would make the exclusion rules something every caller
    reimplements, and reimplements differently.

    This is the combinatorial surface worth crossing. Pair it with ``dispersed``
    rather than taking a prefix: the product's ordering means the first N differ
    only in the last facet.
    """
    from . import facets as facets_module

    out = [base.facets(**chosen) for chosen in facets_module.combinations(*facet_names)]
    return tuple(out if limit is None else out[:limit])
