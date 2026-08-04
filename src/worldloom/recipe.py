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
    from .world import World


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
        "steps": [],
    }


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


def rebuild(
    recipe: dict[str, Any],
    *,
    actors: Any = None,
    actor_ledger: tuple = (),
) -> World:
    """Rebuild the world this recipe describes, from scratch.

    ``actors`` replaces the provider on every step the recipe recorded as
    actor-driven. That substitution is the point: the recipe says *an actor
    episode ran here*, and the caller supplies whoever is answering this time —
    the scripted fake, a paused handshake, or nothing at all.
    """
    from . import archetypes, domains
    from .generators import distractors
    from .scenarios import Departure, Hire, MonthEndClose, Reorganisation

    missing = [key for key in ("archetype", "seed") if recipe.get(key) is None]
    if missing:
        raise RecipeError(
            f"this corpus cannot be rebuilt: its recipe is missing {missing}."
            " Corpora built before recipes existed carry none; rebuild from the"
            " original `worldloom build` command instead."
        )

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
        world = domain.world.from_pack(pack, seed=recipe["seed"]).build()
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
        world = domain.world(
            seed=recipe["seed"],
            archetype=shape,
            employees=recipe.get("employees"),
            annual_revenue=recipe.get("annual_revenue"),
        ).build()

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
        elif name in _STEP_REGISTRY:
            _, build = _STEP_REGISTRY[name]
            kwargs = {key: value for key, value in step.items() if key != "scenario"}
            world = world.run(build(**kwargs))
        else:
            raise RecipeError(f"unknown scenario {name!r} in recipe")
    return world


def has_actor_step(recipe: dict[str, Any]) -> bool:
    """Whether any step in this recipe is actor-driven."""
    return any(step.get("actors") for step in recipe.get("steps", ()))


__all__ = [
    "RecipeError", "STEPS", "build_recipe", "has_actor_step", "rebuild",
    "register_step", "with_step",
]
