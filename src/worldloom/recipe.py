"""How a world was made, so it can be made again.

A corpus already ships with its generation ledger, because reproducibility is the
product's central promise and a world that cannot be regenerated is one run's
output. The ledger is only half of it: it records what a *model* was asked and
answered, and says nothing about the seed, the archetype, or the scenarios that
produced the questions. Rebuilding a corpus meant knowing the command line
someone typed, which is exactly the kind of thing that is not written down.

So a world carries its recipe. It is small on purpose — the archetype by key, the
seed, and the ordered scenario steps — because everything else is derived, and a
recipe that carried derived state would be a second source of truth about the
world beside the world.

One entry earns its place by a different argument from the rest. ``locale`` is
not needed to rebuild the world — the generators take their regions, names and
currency from the pack — but it *is* needed to render the corpus that comes out,
because how a figure is spelled is a jurisdiction's convention and nothing in the
world model records it. So the recipe is also where a corpus says where it is
written, and ``locale_of`` explains why that is here rather than on the artifacts
it is spelled into.

The immediate reason this exists is the actor handshake. Driving an episode from
the CLI means suspending it between decisions, and the honest way to resume a
deterministic pipeline is not to serialise its mid-flight state but to rebuild
and replay: the ledger already stops the replay from re-asking anything, so the
run walks forward to the first decision nobody has taken yet and stops there.
That works only if the corpus knows how to rebuild itself.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .locales import Locale
    from .world import World

#: Where a corpus's jurisdiction is recorded. One key, because a locale is one
#: corpus-wide decision — see ``locale_of`` for why it lives here and not on the
#: artifacts it is spelled into.
LOCALE_KEY = "locale"

#: Where a corpus records the facet claims its lore was minted from. Written by
#: ``world.extend_lore`` rather than by ``build_recipe``, because the claims
#: reach a build through the domain's own ``lore_claims`` field and never pass
#: through this module on the way in — see ``_with_lore_claims`` for the way out.
LORE_CLAIMS_KEY = "lore_claims"


class RecipeError(Exception):
    """Raised when a corpus cannot be rebuilt from what it carries."""


#: Scenario verbs a recipe may record, and the argument names each takes —
#: the retail close loop's own scenarios, hardcoded here because each takes a
#: genuinely different, bespoke set of keyword arguments (``MonthEndClose``'s
#: five bear no resemblance to ``Hire``'s) rather than one uniform shape a
#: registry entry could describe generically.
#:
#: A closed vocabulary, like ``ConstraintKind`` and the scheduler's route
#: conditions: a recipe may only name a scenario the rebuilder knows how to run,
#: and adding one means teaching it. The alternative — storing a callable's name
#: and importing it — would make a corpus file able to execute arbitrary code on
#: load, which is a lot to accept for the convenience of not writing a line here.
STEPS: dict[str, tuple[str, ...]] = {
    "MonthEndClose": ("period", "incident", "comparatives", "actors", "eval_density",
                      "trend_pct"),
    "Hire": ("period", "role_key", "title", "function", "unit_key"),
    "Departure": ("period", "role_key"),
    "Reorganisation": ("period", "unit_key", "new_leader_role"),
    # Not a scenario in the sense the others are — it mints no event and no
    # fact, only documents over what already happened — but it rides the same
    # step list for the same reason `--incident`/`--comparatives` do: a corpus
    # that carries noise must say so on its own recipe, or `--replay` would
    # silently rebuild a cleaner world than the one that shipped.
    "Distractors": ("count",),
    # Also not a scenario: a model-authored estate, applied to a built world.
    # Only the ledger key is recorded — the composition itself is the ledger
    # entry, exactly as a narrated section is, so the recipe stays the small
    # "how it was made" document it is meant to be rather than growing a copy
    # of the answer.
    "Compose": ("ledger_key",),
}

#: Single-episode verticals' own scenario, by name — banking's
#: ``QuarterlyCapitalReturn`` and insurance's ``QuarterlyReserving``, and
#: whatever a fourth vertical registers. ``QuarterlyReserving`` was the third
#: such literal this module would otherwise have carried (banking's own
#: two-line edit having already landed the first two: a ``STEPS`` entry and
#: an ``elif`` branch), which is the rule-of-three trigger the design record
#: for the insurance vertical names: a domain module calls
#: ``register_step(name, arg_names, build)`` from its own file — never from
#: here — at package import, the same seam ``domains.register_domain`` and
#: ``validate.register_domain_checks`` already use, so a third (and every
#: later) vertical's recipe verb costs this module nothing. ``build`` is the
#: scenario class itself: every single-episode vertical's scenario currently
#: takes exactly ``period``, constructed as ``build(period=...)``, so one
#: calling convention serves every registrant without this module needing to
#: know any of their names.
_STEP_REGISTRY: dict[str, tuple[tuple[str, ...], Callable[..., Any]]] = {}


def register_step(name: str, arg_names: tuple[str, ...], build: Callable[..., Any]) -> None:
    """Register a single-episode vertical's scenario as a recipe verb.

    Idempotent for an identical re-registration (a module reload); a second,
    different registration under one name is refused — the same posture
    ``domains.register_domain`` takes, for the same reason: two domains
    disagreeing about what a name means would make a recipe's meaning depend
    on import order.
    """
    existing = _STEP_REGISTRY.get(name)
    if existing is not None:
        if existing == (arg_names, build):
            return
        raise RecipeError(f"a different step is already registered as {name!r}")
    _STEP_REGISTRY[name] = (arg_names, build)


def build_recipe(
    *,
    archetype: str,
    seed: int,
    employees: int | None = None,
    annual_revenue: int | None = None,
    pack: Any = None,
    estate: str | None = None,
    physics: Any = None,
    role_table: Any = None,
    seasonality: Any = None,
    locale: Any = None,
) -> dict[str, Any]:
    """The recipe for a freshly built world, before any scenario has run.

    A pack-built world embeds the whole pack, verbatim, because the pack *is*
    part of how the world was made: a corpus that could only be rebuilt by
    whoever still had the pack file would fail the reason recipes exist. The
    embedding is plain JSON — same no-callables rule as everything else here.
    """
    return {
        "archetype": archetype,
        "seed": seed,
        "employees": employees,
        "annual_revenue": annual_revenue,
        **({} if pack is None else {"pack": _pack_payload(pack)}),
        # Written only when asked for, the same rule `eval_density` and
        # `trend_pct` follow on a step: a key that appears unconditionally puts
        # a new field in every recipe ever written for a value that changes
        # nothing, and the default-build byte diff is what catches that.
        **({} if estate is None else {"estate": estate}),
        # Same conditional rule, and here it also carries a stronger claim:
        # the key is written only when a span actually *differs* from the
        # engine's, so a recipe built with `--physics` whose file happened to
        # restate the defaults is byte-identical to one built without it.
        **_physics_payload(physics),
        # Same conditional rule: the whole table, only when one was authored.
        **({} if role_table is None else {"role_table": [list(row) for row in role_table]}),
        # Written only when a profile was chosen. The engine's own is the
        # general-retail year every corpus before this traded on, so an
        # absent key means exactly that rather than "unknown".
        **({} if seasonality is None else {"seasonality": seasonality.as_dict()}),
        # Same conditional rule, and here it is load-bearing twice over: an
        # absent key means `locales.DEFAULT`, which is what every corpus built
        # before locales existed *was*, and the default build's byte diff is
        # what proves it.
        **_locale_payload(locale),
        "steps": [],
    }


def _locale_payload(locale: Any) -> dict[str, Any]:
    return {} if locale is None else {LOCALE_KEY: _locale_document(locale)}


def _locale_document(locale: Any) -> Any:
    """A locale as the recipe stores it: a registry name, or its conventions.

    Both shapes, because ``locales.from_document`` reads both and they mean
    different things to a reader six months later. ``"germany"`` says *this
    corpus is set in the jurisdiction the registry calls Germany*, and picks up
    any correction the registry later makes to it; a dict says *these exact
    conventions*, and is what a pack-authored locale with no registry name has
    to store. Storing the dict for a named locale would freeze a copy of the
    registry into every corpus, which is the second-source-of-truth this module
    exists to avoid.
    """
    if isinstance(locale, str):
        from .locales import named

        named(locale)  # refuse an unknown name here, not on rebuild
        return locale
    return locale.as_dict()


def locale_of(recipe: dict[str, Any]) -> Locale:
    """The jurisdiction this corpus was built in.

    **Why the recipe carries this and the artifacts do not.**
    ``render/docx._negative_text`` established the rule the hard way — how a
    figure is spelled "has to be a corpus-wide decision applied in one place",
    because a table that printed ``-10,200`` in Word and ``(10,200)`` in
    Markdown was one document disagreeing with another about one number. The
    recipe is the only document a corpus has that is *singular*: there is one of
    it, it survives the round trip to disk (``World._recipe``), and it already
    holds every other build-time decision that is not derivable from the world.
    Two artifacts in a corpus cannot disagree about the locale because there is
    not one locale per artifact to disagree with.

    ``ArtifactIR`` was the other candidate and is wrong on both counts. It is
    per-artifact, so it *could* disagree; and it is persisted field-for-field by
    ``corpus.write_jsonl``, so a new field would rewrite the artifact IR of
    every corpus ever built for a value that is the same in all of them.

    An absent key is ``locales.DEFAULT`` rather than an error: every corpus
    built before this existed carries no locale and *was* Australian, so that is
    a fact about those corpora and not a gap in them.
    """
    from .locales import DEFAULT, from_document

    payload = recipe.get(LOCALE_KEY)
    if payload is None:
        return DEFAULT
    try:
        return from_document(payload)
    except (KeyError, TypeError, ValueError) as exc:
        # Loud, for the reason `locales.named` refuses an unknown name: a corpus
        # whose locale failed to load and fell back to the engine's would render
        # a Frankfurt company's variance memo in Australian punctuation and
        # report success. There is nothing in the output to notice the drop by.
        raise RecipeError(f"this corpus's recorded locale does not load: {exc}") from exc


def with_locale(recipe: dict[str, Any], locale: str | Locale) -> dict[str, Any]:
    """A copy of *recipe* set in *locale*.

    The seam for everything that decides a jurisdiction after the world is
    built — a pack field, a CLI flag, a `facets` consequence. It is a function
    here rather than a keyword everywhere because the recipe is minted deep
    inside a domain's world spec (``retail.RetailWorld.build``) and the thing
    that knows the jurisdiction is usually further out than that.

    Same shape as ``with_step``: a copy, never a mutation, so a caller holding
    the old recipe still holds the world it describes.
    """
    return {**recipe, LOCALE_KEY: _locale_document(locale)}


def _physics_payload(physics: Any) -> dict[str, Any]:
    if physics is None:
        return {}
    from .parameters import overrides_document

    overrides = overrides_document(physics)
    return {"physics": overrides} if overrides else {}


def _pack_payload(pack: Any) -> dict[str, Any]:
    from . import packs

    return packs.to_recipe(pack)


def with_step(recipe: dict[str, Any], scenario: str, **arguments: Any) -> dict[str, Any]:
    """A copy of *recipe* with one scenario step appended.

    Appended rather than merged, because order is the whole content: three closes
    on one world are not the same world as one close run three times, and a
    departure between them changes who signs the third.
    """
    if scenario in STEPS:
        arg_names = STEPS[scenario]
    elif scenario in _STEP_REGISTRY:
        arg_names, _ = _STEP_REGISTRY[scenario]
    else:
        raise RecipeError(
            f"unknown scenario {scenario!r}; add it to recipe.STEPS or register it"
            " with recipe.register_step first"
        )
    unknown = set(arguments) - set(arg_names)
    if unknown:
        raise RecipeError(f"{scenario} does not take {sorted(unknown)}")
    return {**recipe, "steps": [*recipe.get("steps", ()), {"scenario": scenario, **arguments}]}


def _under(spec: Any, physics: Any, default: Any) -> Any:
    """*spec* rebound to *physics*, or untouched when the physics are default.

    Untouched on the default path so that a domain or scenario registered
    elsewhere — which may predate the parameter registry and have no ``physics``
    field at all — keeps rebuilding exactly as it did. When non-default physics
    *were* recorded, a spec that cannot carry them is an error rather than a
    silent fallback: the corpus was built at those ranges and rebuilding it at
    the engine's would be a different world reported as the same one.
    """
    if physics is default:
        return spec
    from dataclasses import replace as _replace

    try:
        return _replace(spec, physics=physics)
    except TypeError as exc:
        raise RecipeError(
            f"this recipe records non-default physics, but {type(spec).__name__}"
            f" does not accept any: {exc}"
        ) from exc


def _with_estate(spec: Any, estate: Any) -> Any:
    """*spec* rebound to a recorded estate size, or untouched when there is none.

    Applied to the pack-built branch as well as the archetype one, which it was
    not before. A pack-built retailer could always be given ``--estate`` — the
    CLI rebinds the builder after ``from_pack`` — and ``build_recipe`` recorded
    it, but ``rebuild`` only passed it on the non-pack path. So a pack corpus
    with a hundred-node landscape rebuilt into one with nine and reported
    success, which is the single failure mode a recipe exists to make
    impossible. Same posture as ``_under`` and ``_with_roles`` on a spec that
    cannot carry one: an error, never a silent smaller world.
    """
    if estate is None:
        return spec
    from dataclasses import replace as _replace

    try:
        return _replace(spec, estate=estate)
    except TypeError as exc:
        raise RecipeError(
            f"this recipe records an estate, but {type(spec).__name__} does not"
            f" accept one: {exc}"
        ) from exc


def _with_seasonality(spec: Any, seasonality: Any) -> Any:
    """*spec* rebound to a recorded trading year, or untouched when there is none."""
    if seasonality is None:
        return spec
    from dataclasses import replace as _replace

    try:
        return _replace(spec, seasonality=seasonality)
    except TypeError as exc:
        raise RecipeError(
            f"this recipe records a trading year, but {type(spec).__name__}"
            f" does not accept one: {exc}"
        ) from exc


def _with_lore_claims(spec: Any, claims: Any) -> Any:
    """*spec* rebound to the facet lore it was built with, or untouched.

    Same posture as ``_with_roles``, and load-bearing for the same reason. Facet
    lore is an *input* to the organisation — it dates business units, attaches
    persona traits and decides artifact density — so a corpus rebuilt without it
    is a different company with the same recipe, which is the one failure
    ``rebuild`` exists to make impossible.
    """
    if not claims:
        return spec
    from dataclasses import replace as _replace

    try:
        return _replace(spec, lore_claims=claims)
    except TypeError as exc:
        raise RecipeError(
            f"this recipe records facet lore, but {type(spec).__name__} does not"
            f" accept any: {exc}"
        ) from exc


def _with_roles(spec: Any, role_table: Any) -> Any:
    """*spec* rebound to an authored role table, or untouched when there is none.

    Same posture as ``_under``: a domain registered outside this repository may
    have no ``role_table`` field, and a recipe that never recorded one must
    keep rebuilding exactly as it did. A recipe that *did* record one and meets
    a spec that cannot carry it is an error, not a silent fallback — the corpus
    was built with that organisation and rebuilding it with the engine's own
    would be a different company reported as the same one.
    """
    if role_table is None:
        return spec
    from dataclasses import replace as _replace

    try:
        return _replace(spec, role_table=role_table)
    except TypeError as exc:
        raise RecipeError(
            f"this recipe records an authored role table, but"
            f" {type(spec).__name__} does not accept one: {exc}"
        ) from exc


def rebuild(
    recipe: dict[str, Any],
    *,
    actors: Any = None,
    actor_ledger: tuple = (),
    ledger: tuple = (),
) -> World:
    """Rebuild the world this recipe describes, from scratch.

    ``ledger`` is the corpus's generation ledger, needed only by a recipe that
    records a ``Compose`` step: the composition a model authored lives in the
    ledger, not the recipe, so rebuilding one without its ledger is refused
    rather than silently producing the uncomposed world. Same shape as
    ``actor_ledger`` below and for the same reason.

    ``actors`` replaces the provider on every step the recipe recorded as
    actor-driven. That substitution is the point: the recipe says *an actor
    episode ran here*, and the caller supplies whoever is answering this time —
    the scripted fake, a paused handshake, or nothing at all.
    """
    from . import archetypes, domains
    from .generators import distractors
    from . import profiles as _profiles
    from .parameters import DEFAULT, overrides_from
    from .scenarios import Departure, Hire, MonthEndClose, Reorganisation

    missing = [key for key in ("archetype", "seed") if recipe.get(key) is None]
    if missing:
        raise RecipeError(
            f"this corpus cannot be rebuilt: its recipe is missing {missing}."
            " Corpora built before recipes existed carry none; rebuild from the"
            " original `worldloom build` command instead."
        )

    # Reconstructed before anything is built, and refused loudly if it does not
    # reconstruct. A recipe whose physics failed to load and fell back to the
    # engine's would rebuild a *different world* while reporting success, which
    # is the one failure mode a recipe exists to make impossible.
    try:
        physics = (
            DEFAULT if recipe.get("physics") is None
            else DEFAULT.with_overrides(overrides_from(recipe["physics"]))
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError(f"this corpus's recorded physics does not load: {exc}") from exc

    try:
        seasonality = (
            None if recipe.get("seasonality") is None
            else _profiles.from_document(recipe["seasonality"])
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError(
            f"this corpus's recorded trading year does not load: {exc}"
        ) from exc

    # Resolved here for its side effect only — the world is built without it,
    # and only renderers read it back. Checked this early anyway, beside the
    # physics and the trading year, because the alternative is a rebuild that
    # succeeds and then fails at render time in a different process.
    locale_of(recipe)

    authored_roles = recipe.get("role_table")
    role_table = None if authored_roles is None else tuple(
        (row[0], row[1], row[2], row[3]) for row in authored_roles
    )

    # Reconstructed up front beside the physics and the trading year, and for
    # the same reason: a recipe whose facet lore failed to load and fell back to
    # none would rebuild a world with different unit formation dates and a
    # different artifact density while reporting success.
    try:
        from . import facets as _facets

        lore_claims = _facets.claims_from_document(recipe.get(LORE_CLAIMS_KEY) or ())
    except (KeyError, TypeError, ValueError) as exc:
        raise RecipeError(f"this corpus's recorded facet lore does not load: {exc}") from exc

    if recipe.get("pack") is not None:
        # A pack-built world: the recipe carries the pack whole, and the
        # pack's base names the engine. Same closed-vocabulary posture — the
        # pack is validated data, and `base` resolves through the registry.
        from . import packs

        try:
            pack = packs.load(dict(recipe["pack"]))
        except Exception as exc:
            raise RecipeError(f"this corpus's embedded pack does not validate: {exc}") from exc
        domain = domains.by_name(pack.base)
        if domain is None:
            raise RecipeError(
                f"the embedded pack names engine {pack.base!r}, which is not"
                f" registered — registered: {', '.join(domains.names())}"
            )
        spec = _under(domain.world.from_pack(pack, seed=recipe["seed"]), physics, DEFAULT)
        spec = _with_estate(spec, recipe.get("estate"))
        spec = _with_lore_claims(spec, lore_claims)
        world = _with_seasonality(_with_roles(spec, role_table), seasonality).build()
    else:
        try:
            shape = archetypes.get(recipe["archetype"])
        except KeyError as exc:
            raise RecipeError(str(exc)) from None

        # The archetype names the domain that knows how to build it — resolved
        # through the registry rather than a stored class name, for the same
        # reason STEPS is a closed vocabulary: a recipe must never be able to
        # import and execute an arbitrary callable on load.
        domain = domains.for_archetype(shape.key)
        if domain is None:
            raise RecipeError(
                f"archetype {shape.key!r} belongs to no registered domain; the module"
                " that owns it was never imported, so this corpus cannot be rebuilt"
            )
        spec = _under(domain.world(
            seed=recipe["seed"],
            archetype=shape,
            employees=recipe.get("employees"),
            annual_revenue=recipe.get("annual_revenue"),
        ), physics, DEFAULT)
        # Rebound after construction rather than passed as a keyword, which is
        # what the archetype branch used to do. The keyword form was safe only
        # while retail's world was the only one that accepted `estate`; now that
        # banking's and insurance's do too, going through `_with_estate` gives
        # both branches one path and turns a domain that still does not accept
        # one into a stated error instead of a `TypeError` from a constructor.
        spec = _with_estate(spec, recipe.get("estate"))
        spec = _with_lore_claims(spec, lore_claims)
        world = _with_seasonality(_with_roles(spec, role_table), seasonality).build()

    # Re-attached rather than passed to the spec, because no world spec accepts
    # a locale: the half a locale decides at *build* time (regions, name pools,
    # currency) reaches the generators through the pack, and the half it decides
    # at *render* time (the figure grammar) is read back off the recipe by
    # `render/values.corpus_locale`. A freshly built world mints its own recipe
    # from `build_recipe`, which knows nothing of a locale attached afterwards,
    # so without this line a German corpus would rebuild into an identical world
    # that renders `243,800`. That is the exact failure `rebuild` exists to make
    # impossible, in the one dimension that survives only on the recipe.
    #
    # The recorded payload is copied across verbatim rather than round-tripped
    # through `locale_of`: a recipe that named `"germany"` must rebuild into one
    # that still names it, not into one carrying a frozen copy of what the
    # registry said about Germany on the day it was rebuilt.
    if recipe.get(LOCALE_KEY) is not None:
        world = world.extend(recipe={**world.recipe, LOCALE_KEY: recipe[LOCALE_KEY]})

    for step in recipe.get("steps", ()):
        name = step.get("scenario")
        if name == "MonthEndClose":
            world = world.run(
                MonthEndClose(
                    period=step["period"],
                    include_operational_incident=step.get("incident"),
                    comparative_months=step.get("comparatives", 0),
                    actors=actors if step.get("actors") else None,
                    actor_ledger=actor_ledger if step.get("actors") else (),
                    # `.get(..., 1.0)` rather than a required key: a recipe
                    # written before this field existed carries no
                    # `eval_density` at all, and 1.0 is exactly what that
                    # corpus was built with — the knob's own default.
                    eval_density=step.get("eval_density", 1.0),
                    trend_pct=step.get("trend_pct", 0.0),
                    physics=physics,
                    seasonality=seasonality,
                )
            )
        elif name == "Hire":
            world = world.run(
                Hire(
                    period=step["period"],
                    role_key=step["role_key"],
                    title=step["title"],
                    function=step["function"],
                    unit_key=step["unit_key"],
                )
            )
        elif name == "Departure":
            world = world.run(Departure(period=step["period"], role_key=step["role_key"]))
        elif name == "Reorganisation":
            world = world.run(
                Reorganisation(
                    period=step["period"],
                    unit_key=step["unit_key"],
                    new_leader_role=step["new_leader_role"],
                )
            )
        elif name == "Distractors":
            world = distractors.apply(world, count=step["count"])
        elif name == "Compose":
            from . import compose as compose_module

            world = compose_module.replay(
                world, ledger_key=step["ledger_key"], ledger=ledger,
            )
        elif name in _STEP_REGISTRY:
            _, build = _STEP_REGISTRY[name]
            kwargs = {key: value for key, value in step.items() if key != "scenario"}
            world = world.run(_under(build(**kwargs), physics, DEFAULT))
        else:
            raise RecipeError(f"unknown scenario {name!r} in recipe")
    return world


def has_actor_step(recipe: dict[str, Any]) -> bool:
    """Whether any step in this recipe is actor-driven."""
    return any(step.get("actors") for step in recipe.get("steps", ()))


__all__ = [
    "LOCALE_KEY", "RecipeError", "STEPS", "build_recipe", "has_actor_step",
    "locale_of", "rebuild", "register_step", "with_locale", "with_step",
]
