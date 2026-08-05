"""Worldloom as a library a model writes code against.

Every capability in this project is reachable from the CLI, and the CLI is the
wrong shape for most of what you would want to do with them. A command is a
*fixed pipeline*: it takes flags, runs one arrangement of the machinery, and
exits. ``worldloom mosaic -n 5`` is one arrangement. So is ``build``, so is
``refine``. Wanting a different arrangement — five organisation shapes crossed
with three trading calendars, each refined until it plateaus, keeping only the
ones whose blast radius exceeds ten — means either a new flag, a new command, or
a shell script gluing JSON between processes.

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
from .parameters import DEFAULT, Parameters, Span
from .roles import from_shape, to_rows

__all__ = [
    "Blueprint", "Built", "banking", "built", "companies", "cross", "dispersed",
    "engine", "insurance", "mosaic_of", "probe_of", "retail", "sweep",
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
    facet_choices: Mapping[str, str] = _field(default_factory=dict)
    implied_roles: tuple[tuple[str, str, str, str | None], ...] = ()
    implied_lore: tuple[Any, ...] = ()
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

        # Lore is generated by the domain, and a blueprint has no seam to add to
        # it — so facet lore is *reported as unmet* rather than carried
        # silently. Carrying a constraint nothing applies is precisely the
        # "carried, cited, and inert" failure `packs.lint` exists to catch, and
        # a facet layer that reproduced it would be worse than one that admitted
        # the gap. The honest route today is a pack: paste these into its `lore`.
        unmet = list(resolved.wants)
        if resolved.lore:
            unmet.append(
                f"{len(resolved.lore)} lore constraint(s) these facets imply —"
                " a blueprint cannot add lore to a domain's own, so put them on"
                " a pack's `lore` and build with it"
            )

        merged = dict(resolved.physics)
        merged.update(self.physics_overrides)          # explicit wins
        return replace(
            self,
            physics_overrides=merged,
            calendar_name=self.calendar_name or resolved.calendar,
            estate_size=self.estate_size or resolved.estate,
            facet_choices=dict(resolved.chosen),
            implied_roles=resolved.roles,
            implied_lore=resolved.lore,
            unmet=tuple(unmet),
        )

    def staff(self, employees: int) -> Blueprint:
        """The archetype's stated headcount — the *company's* size, which is a
        different claim from how many people the corpus names."""
        return replace(self, employees=employees)

    # -- realisation -------------------------------------------------------

    @property
    def parameters(self) -> Parameters:
        return DEFAULT.with_overrides(dict(self.physics_overrides))

    @property
    def seasonality(self) -> profiles.Seasonality | None:
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
            "physics": {name: span.as_dict()
                        for name, span in sorted(self.physics_overrides.items())},
            "facets": dict(sorted(self.facet_choices.items())),
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
        shape = archetypes.get(key)

        changes: dict[str, Any] = {"physics": self.parameters}
        table = self.role_table()
        if table is not None:
            changes["role_table"] = table
        if self.seasonality is not None:
            changes["seasonality"] = self.seasonality
        if self.estate_size is not None:
            changes["estate"] = self.estate_size

        spec = registered.world(seed=self.seed, archetype=shape,
                                **({} if self.employees is None
                                   else {"employees": self.employees}))
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
        return Built(spec.build(), self)


#: Departments, drawn longest-first so a deeper organisation gets more of them.
_FUNCTIONS: tuple[str, ...] = (
    "Executive", "Finance", "Technology", "Operations", "Merchandising",
    "ServiceOperations", "Risk", "Supply Chain", "Digital", "People",
)


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
        """Blast radius, chokepoints and depth — what a loop filters on."""
        from . import graphs

        dependency = graphs.dependency_graph(self.world)
        return {
            "nodes": dependency.number_of_nodes(),
            "chokepoints": len(graphs.chokepoints(dependency)),
            "longest_chain": len(graphs.longest_chain(dependency)),
        }

    def measure(self) -> dict[str, Any]:
        """A shape vector for this corpus. Enough to sort or disperse a field on."""
        people = [p for p in self.world.people if p.left is None]
        return {
            "people": len(people),
            "titles": len({p.title for p in people}),
            "facts": len(self.world.facts),
            "artifacts": len(self.world.artifact_intents),
            "evaluations": len(self.world.evaluations),
            **self.topology(),
        }

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


def engine(name: str, *, seed: int = 8128) -> Blueprint:
    """A blueprint for any registered domain by name."""
    if domains.by_name(name) is None:
        raise KeyError(f"no domain named {name!r}; known: {domains.names()}")
    return Blueprint(domain_name=name, seed=seed)


def retail(*, seed: int = 8128) -> Blueprint:
    return engine("retail", seed=seed)


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
    return Blueprint(
        domain_name=variant.engine,
        seed=variant.seed,
        physics_overrides=dict(variant.overrides),
        shape={"headcount": variant.headcount, "span": variant.span,
               "levels": variant.levels, "functions": list(variant.functions)},
        calendar_name=variant.calendar,
        estate_size=variant.estate,
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
