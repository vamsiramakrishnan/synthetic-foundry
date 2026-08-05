"""The composition handshake: a model authors the estate, and the graph is the grammar.

The third handshake, and the first that lets a model author *entities* rather
than prose or document shape.

``narrate`` hands out a bounded request for what to say and checks the answer
against the fact ledger. ``plan`` hands out a request for how to shape a
document and checks the answer against a component grammar. This hands out a
request for **what the company runs** — its services, the systems they sit on,
who owns them, what depends on what — and checks the answer against
``graphs.py``. That is the whole design in one sentence: the model brings
judgement and vocabulary, and a graph library that already existed for other
reasons turns out to be exactly the validator that judgement needs.

Why it exists, measured rather than asserted. `worldloom topology` on the
largest world this tool builds reports **nine** services and systems, because
nine is what the month-end-close episode names. `generators/estate.py` grows
that to a hundred for retail, using retail's own service-name pools. It cannot
serve banking, whose estate would come out called ``click-collect-api``, and it
cannot serve insurance, which today has **no services at all**. A pool per
industry is one answer and it is the wrong one: it puts an ever-growing list of
made-up service names into the engine, which is the contamination build-order
§7 exists to prevent. The right answer is that the vocabulary of an industry is
the thing a model is genuinely better at than a table, so the model brings it
and the harness refuses anything incoherent.

**What the model may decide.** Names, purposes, ownership, what runs on what,
what depends on what, declared criticality, and the lore explaining why the
landscape looks the way it does — a 2019 migration that left two catalogues, an
acquisition never integrated. All of it is judgement.

**What it may not.** Identity (ids are minted here), the existing estate (the
episode's own services are untouchable — see ``generators/estate.py``), and
anything that would make the graph incoherent. The specific refusals are in
:func:`review` and every one of them is stated in the request, because a rule
an agent cannot see is a rejection it could not have predicted.

**The boundary this does not yet cross, stated plainly.** A composed estate is
*background landscape*: it is applied to a world that has already run its
episode, so no document cites it and the incident still runs through the
services the episode names. That is the same boundary ``--estate`` has, and it
is honest for what this is — the corpus's technology landscape, which is most
of what an estate is for. Letting a model author the estate an episode then
*runs through* needs the composition to happen before the episode, which is a
two-phase build like ``--actors agent``, and is the next rung rather than a
missing piece of this one.

Accepted compositions are content-addressed into the same generation ledger
narration and planning use, so ``--replay`` rebuilds a composed corpus with no
provider reachable, exactly as it rebuilds a narrated one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pydantic import Field

from . import graphs
from .ids import content_key, format_id, highest_numeric_suffix
from .models import (
    ConstraintKind,
    GenerationLedgerEntry,
    LoreCommitment,
    LoreConstraint,
    LoreKind,
    Model,
    Service,
    System,
)

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: The versioned prompt identity, part of every ledger key. Bumped whenever the
#: wording of a request or a rule below changes, for the reason
#: ``narrative/prompts.py`` states: editing a prompt in place silently changes
#: what a seed means, and a version is what makes it an explicit decision.
COMPOSE_PROMPT_KEY = "compose/estate@1"

#: How many services and systems a composition may add. An upper bound rather
#: than a target, and it exists because an unbounded one is how a handshake
#: turns into a bill: a model asked for "the estate" with no ceiling will
#: happily write six hundred services, each of which costs tokens to generate
#: and nothing to check.
MAX_SERVICES = 200
MAX_SYSTEMS = 40


# ---------------------------------------------------------------------------
# What the model is asked
# ---------------------------------------------------------------------------

#: The grammar, in sentences. Spelled out rather than pointed at, because an
#: agent should be able to answer without reading this repository — the same
#: contract ``compiler/handshake.py`` states for its own rules.
RULES: tuple[str, ...] = (
    "Every service and system you propose needs a unique `key`. Keys are yours;"
    " ids are not — the harness mints those.",
    "`depends_on` may name a key you proposed or the id of a service or system"
    " that already exists. Nothing else resolves.",
    "The dependency graph, yours and the existing one together, must be acyclic."
    " A service that transitively depends on itself is an estate that can never"
    " start.",
    "You may not change what an existing service depends on. The episode's own"
    " services carry its causality; add around them.",
    "`owner` must be the id of a person listed in `people`. A service nobody"
    " owns is a service nobody fixes.",
    "`runs_on` must be a system: a key you proposed, or an existing system id.",
    "`criticality_tier` runs 1 (highest) to 4, and the graph has to agree with"
    " it. A tier-1 or tier-2 service that nothing depends on and that depends on"
    " nothing is an isolated node claiming to be the most important thing in the"
    " company; that is refused.",
    "The finished estate must contain at least one chokepoint — something with"
    " no second path to what it serves. An estate in which everything is"
    " redundant is not one anybody has ever built or paid for.",
    "Lore is optional, and if you write it, every commitment must constrain at"
    " least one thing in the closed vocabulary. Lore that constrains nothing is"
    " decoration, and decoration is refused rather than carried.",
    "Write the landscape this industry actually has. The point of asking you"
    " rather than a table is the vocabulary: an insurer runs a policy admin"
    " system and a claims workbench, not a checkout API.",
)


@dataclass(frozen=True)
class ComposeRequest:
    """Everything a model needs to compose an estate, and nothing else."""

    id: str
    company: str
    industry: str
    business_units: tuple[tuple[str, str], ...]
    """``(id, name)`` — so an authored service can be named for what it serves."""
    existing_systems: tuple[dict[str, Any], ...]
    existing_services: tuple[dict[str, Any], ...]
    people: tuple[dict[str, str], ...]
    """Who may own a service: ``id``, ``name``, ``title``."""
    max_services: int
    max_systems: int
    constraint_vocabulary: tuple[str, ...]
    lore_kinds: tuple[str, ...]
    digest: str
    """A content address over the world state this request was formed from —
    the same role ``NarrativeRequest``'s fact digest plays. A composition
    accepted against one estate must not silently replay against a different
    one."""


def _industry(world: World) -> str:
    """What kind of company this is, from the world or from its recipe."""
    if world._archetype is not None:
        return world._archetype.industry
    key = (world._recipe or {}).get("archetype")
    if key:
        from . import archetypes

        try:
            return archetypes.get(key).industry
        except KeyError:
            return key
    return "unspecified"


def request(world: World) -> ComposeRequest:
    """The single bounded request for this world's estate."""
    systems = tuple(
        {"id": s.id, "name": s.name, "purpose": s.purpose,
         "system_of_record_for": list(s.is_system_of_record_for)}
        for s in world.systems
    )
    services = tuple(
        {"id": s.id, "name": s.name, "purpose": s.purpose,
         "criticality_tier": s.criticality_tier, "runs_on": s.system_id,
         "depends_on": list(s.depends_on)}
        for s in world.services
    )
    people = tuple(
        {"id": p.id, "name": p.name, "title": p.title}
        for p in world.people if p.left is None
    )
    return ComposeRequest(
        id="estate/compose",
        company=world.company.name,
        # A corpus loaded from disk carries no `Archetype` object — only its
        # key, on the recipe. Falling back to that matters more than it looks:
        # this handshake exists so a model brings an industry's *vocabulary*,
        # and "unspecified" is precisely the word that stops it doing so.
        industry=_industry(world),
        business_units=tuple((u.id, u.name) for u in world.business_units),
        existing_systems=systems,
        existing_services=services,
        people=people,
        max_services=MAX_SERVICES,
        max_systems=MAX_SYSTEMS,
        constraint_vocabulary=tuple(k.value for k in ConstraintKind),
        lore_kinds=tuple(k.value for k in LoreKind),
        # Over the estate the composition attaches to, not over the whole
        # world: a later close adds facts and changes nothing this request
        # described, and re-deriving the digest from those would invalidate a
        # perfectly good composition for no reason.
        digest=content_key(
            *(s["id"] for s in systems), *(s["id"] for s in services),
            *(p["id"] for p in people),
        ),
    )


def requests_document(world: World) -> dict[str, Any]:
    """The request, ready to hand to an agent."""
    made = request(world)
    return {
        "worldloom_seed": world.seed,
        "prompt_version": COMPOSE_PROMPT_KEY,
        "id": made.id,
        "company": made.company,
        "industry": made.industry,
        "business_units": [{"id": i, "name": n} for i, n in made.business_units],
        "existing_systems": [dict(s) for s in made.existing_systems],
        "existing_services": [dict(s) for s in made.existing_services],
        "people": [dict(p) for p in made.people],
        "budget": {"max_services": made.max_services, "max_systems": made.max_systems},
        "constraint_vocabulary": list(made.constraint_vocabulary),
        "lore_kinds": list(made.lore_kinds),
        "rules": list(RULES),
        "response_shape": {
            "systems": [{
                "key": "<your own unique key>", "name": "...", "purpose": "...",
                "owner": "<a person id from people>",
                "system_of_record_for": ["<what this system is the record for>"],
            }],
            "services": [{
                "key": "<your own unique key>", "name": "...", "purpose": "...",
                "owner": "<a person id from people>",
                "runs_on": "<a system key or an existing SYS id>",
                "depends_on": ["<keys or existing SVC/SYS ids>"],
                "criticality_tier": 2,
            }],
            "lore": [{
                "kind": "<one of lore_kinds>", "assertion": "...",
                "effective_from": "YYYY-MM", "visibility": "acknowledged",
                "constrains": [{
                    "kind": "<one of constraint_vocabulary>", "target": "...",
                    "effect": "...", "magnitude": 1.0,
                }],
            }],
        },
    }


# ---------------------------------------------------------------------------
# What the model answers
# ---------------------------------------------------------------------------


class ProposedSystem(Model):
    key: str
    name: str
    purpose: str
    owner: str
    system_of_record_for: list[str] = Field(default_factory=list)


class ProposedService(Model):
    key: str
    name: str
    purpose: str
    owner: str
    runs_on: str
    depends_on: list[str] = Field(default_factory=list)
    criticality_tier: int = 3


class ProposedConstraint(Model):
    kind: ConstraintKind
    target: str
    effect: str
    magnitude: float | None = None


class ProposedLore(Model):
    kind: LoreKind
    assertion: str
    effective_from: str
    visibility: str = "acknowledged"
    constrains: list[ProposedConstraint] = Field(min_length=1)


class Composition(Model):
    """One model's whole answer."""

    systems: list[ProposedSystem] = Field(default_factory=list)
    services: list[ProposedService] = Field(default_factory=list)
    lore: list[ProposedLore] = Field(default_factory=list)


@dataclass(frozen=True)
class Rejection:
    """One reason a composition was refused, and what it was about."""

    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"


# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------


def review(world: World, proposal: Composition) -> list[Rejection]:
    """Every reason this composition cannot be committed.

    All of them, not the first: a handshake that reports one problem per round
    turns an agent's work into a guessing game, and the whole point of a stated
    grammar is that a rejection was predictable.
    """
    found: list[Rejection] = []

    def refuse(subject: str, rule: str, detail: str) -> None:
        found.append(Rejection(subject, rule, detail))

    existing_systems = {s.id for s in world.systems}
    existing_services = {s.id for s in world.services}
    existing = existing_systems | existing_services
    people = {p.id for p in world.people if p.left is None}

    if len(proposal.services) > MAX_SERVICES:
        refuse("services", "budget",
               f"{len(proposal.services)} proposed, at most {MAX_SERVICES} allowed")
    if len(proposal.systems) > MAX_SYSTEMS:
        refuse("systems", "budget",
               f"{len(proposal.systems)} proposed, at most {MAX_SYSTEMS} allowed")

    # -- keys ---------------------------------------------------------------
    keys: set[str] = set()
    for item in (*proposal.systems, *proposal.services):
        if item.key in keys:
            refuse(item.key, "duplicate_key", "two proposals share this key")
        if item.key in existing:
            refuse(item.key, "key_collides_with_id",
                   "this is already the id of something in the world; keys are yours,"
                   " ids are the harness's")
        keys.add(item.key)

    system_keys = {s.key for s in proposal.systems}
    resolvable = keys | existing

    # -- ownership and hosting ----------------------------------------------
    for item in (*proposal.systems, *proposal.services):
        if item.owner not in people:
            refuse(item.key, "unknown_owner",
                   f"{item.owner!r} is not a person currently employed here")
    for service in proposal.services:
        if service.runs_on not in system_keys | existing_systems:
            refuse(service.key, "unknown_system",
                   f"runs_on {service.runs_on!r} is not a system")
        if not 1 <= service.criticality_tier <= 4:
            refuse(service.key, "tier_out_of_range",
                   f"criticality_tier {service.criticality_tier} is outside 1-4")

    # -- dependencies -------------------------------------------------------
    for service in proposal.services:
        for target in service.depends_on:
            if target not in resolvable:
                refuse(service.key, "unknown_dependency",
                       f"depends_on {target!r}, which is neither a proposed key nor an"
                       " existing id")
            if target == service.key:
                refuse(service.key, "self_dependency", "depends on itself")

    # -- the graph ----------------------------------------------------------
    # Built from the proposal *and* the world, because acyclicity is a property
    # of the union: a proposed service depending on an existing one that
    # depends back on the proposal is a cycle neither half can see alone. The
    # same `graphs.cycles` the validator runs, so the handshake and the
    # coherence gate can never disagree about what a cycle is.
    combined = _combined_graph(world, proposal)
    for cycle in graphs.cycles(combined):
        refuse(cycle[0], "dependency_cycle",
               f"cycle through {' → '.join(cycle)} → {cycle[0]}")

    if not found:
        # Only meaningful on an acyclic graph — `chokepoints` returns nothing
        # on a cyclic one, and reporting "no chokepoint" beside "there is a
        # cycle" would be one defect wearing two hats.
        depended_on = {t for s in proposal.services for t in s.depends_on}
        for service in proposal.services:
            isolated = not service.depends_on and service.key not in depended_on
            if isolated and service.criticality_tier <= 2:
                refuse(service.key, "tier_contradicts_graph",
                       f"declares tier {service.criticality_tier} but nothing depends on"
                       " it and it depends on nothing")
        if proposal.services and not graphs.chokepoints(combined):
            refuse("estate", "no_chokepoint",
                   "every node has a second path around it — an estate in which nothing"
                   " is a single point of failure is not one anybody has built")

    # -- lore ---------------------------------------------------------------
    for index, commitment in enumerate(proposal.lore):
        subject = f"lore[{index}]"
        if commitment.visibility not in ("acknowledged", "tacit", "denied"):
            refuse(subject, "unknown_visibility",
                   f"{commitment.visibility!r} is not acknowledged, tacit or denied")
        if not _looks_like_a_month(commitment.effective_from):
            refuse(subject, "bad_effective_from",
                   f"{commitment.effective_from!r} is not a YYYY-MM month")
        for constraint in commitment.constrains:
            if not constraint.target.strip() or not constraint.effect.strip():
                refuse(subject, "empty_constraint",
                       "a constraint needs both a target and an effect; one that names"
                       " neither constrains nothing")

    return found


def _looks_like_a_month(value: str) -> bool:
    parts = value.split("-")
    if len(parts) != 2 or len(parts[0]) != 4:
        return False
    try:
        year, month = int(parts[0]), int(parts[1])
    except ValueError:
        return False
    return 1 <= month <= 12 and 1900 <= year <= 2999


def _combined_graph(world: World, proposal: Composition):  # type: ignore[no-untyped-def]
    """The world's dependency graph with the proposal's nodes and edges added.

    Uses ``graphs.dependency_graph`` for the existing half rather than
    rebuilding it, so "what the world already is" is read exactly once and by
    the same code the topology report and the validator read it with.
    """
    import networkx as nx

    graph = graphs.dependency_graph(world)
    for system in sorted(proposal.systems, key=lambda s: s.key):
        graph.add_node(system.key, kind="system", name=system.name)
    for service in sorted(proposal.services, key=lambda s: s.key):
        graph.add_node(service.key, kind="service", name=service.name)
    for service in sorted(proposal.services, key=lambda s: s.key):
        for target in sorted(set(service.depends_on)):
            if target in graph and target != service.key:
                graph.add_edge(service.key, target)
    assert isinstance(graph, nx.DiGraph)
    return graph


# ---------------------------------------------------------------------------
# Acceptance
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AcceptResult:
    """What acceptance produced, or why nothing was produced."""

    world: World | None
    rejections: tuple[Rejection, ...]
    services_added: int
    systems_added: int
    lore_added: int

    @property
    def accepted(self) -> bool:
        return self.world is not None


def accept(world: World, proposal: Composition, *, model_id: str) -> AcceptResult:
    """Validate the whole composition and commit it, or reject all of it.

    All-or-nothing, the same property ``narrate accept`` and ``plan accept``
    have and for the same reason: a partial commit leaves a corpus half-composed
    with no record of which half, and the half that landed is the half nobody
    reviewed.
    """
    from dataclasses import replace as _replace

    from .recipe import with_step

    rejections = review(world, proposal)
    if rejections:
        return AcceptResult(None, tuple(rejections), 0, 0, 0)

    made = request(world)

    # Ids are derived from what the world already carries, never taken from
    # `world._minter`. That looks like the obvious source and is the wrong one:
    # the minter is *mutable shared state* hanging off a frozen world, so
    # accepting the same proposal against the same world twice would hand out
    # different ids the second time, and a composed corpus would then fail to
    # rebuild from its own ledger. `tests/test_estate.py` caught exactly that.
    # Deriving from the highest suffix present makes acceptance a pure function
    # of (world, proposal), which is what replay requires.
    existing = [
        *(s.id for s in world.systems), *(s.id for s in world.services),
        *(commitment.id for commitment in world.lore),
    ]
    counters = {
        prefix: highest_numeric_suffix(prefix, existing)
        for prefix in ("SYS", "SVC", "LORE")
    }

    def mint(prefix: str) -> str:
        counters[prefix] += 1
        return format_id(prefix, counters[prefix])

    # Systems first: a service may run on one, and the id has to exist before
    # it is referenced.
    id_of: dict[str, str] = {}
    systems: list[System] = []
    for spec in proposal.systems:
        made_id = mint("SYS")
        id_of[spec.key] = made_id
        systems.append(System(
            id=made_id, name=spec.name, purpose=spec.purpose, owner_id=spec.owner,
            is_system_of_record_for=list(spec.system_of_record_for),
        ))

    services: list[Service] = []
    for spec in proposal.services:
        id_of[spec.key] = mint("SVC")
    for spec in proposal.services:
        services.append(Service(
            id=id_of[spec.key], name=spec.name, purpose=spec.purpose,
            owner_id=spec.owner, system_id=id_of.get(spec.runs_on, spec.runs_on),
            criticality_tier=spec.criticality_tier,
            depends_on=[id_of.get(t, t) for t in spec.depends_on],
        ))

    commitments: list[LoreCommitment] = []
    for spec in proposal.lore:
        commitments.append(LoreCommitment(
            id=mint("LORE"), kind=spec.kind, assertion=spec.assertion,
            effective_from=spec.effective_from,
            visibility=spec.visibility,  # type: ignore[arg-type]
            constrains=[
                LoreConstraint(kind=c.kind, target=c.target, effect=c.effect,
                               magnitude=c.magnitude)
                for c in spec.constrains
            ],
        ))

    key = content_key(COMPOSE_PROMPT_KEY, world.seed, made.digest, model_id)
    next_gen = highest_numeric_suffix("GEN", [entry.id for entry in world.ledger]) + 1
    entry = GenerationLedgerEntry(
        id=format_id("GEN", next_gen),
        key=key,
        call_site=made.id,
        ordinal=0,
        world_seed=world.seed if world.seed is not None else 0,
        input_facts_digest=made.digest,
        model_id=model_id,
        prompt_version=COMPOSE_PROMPT_KEY,
        output=proposal.model_dump(mode="json"),
    )

    # The live minter, if there is one, is pushed past everything just minted.
    # It was not the *source* of these ids (see above) but it is still the
    # source for any episode run on the composed world afterwards, and a
    # scenario that minted SVC-0003 over a composed SVC-0003 would put two
    # different services under one id.
    if world._minter is not None:
        for prefix, value in counters.items():
            current = world._minter._counters.get(prefix, 0)
            world._minter._counters[prefix] = max(current, value)

    composed = _replace(
        world,
        _systems=(*world._systems, *systems),
        _services=(*world._services, *services),
        _lore=(*world._lore, *commitments),
        _ledger=(*world._ledger, entry),
        _recipe=with_step(world._recipe, "Compose", ledger_key=key),
    )
    return AcceptResult(
        composed, (), len(services), len(systems), len(commitments)
    )


def replay(world: World, *, ledger_key: str, ledger: tuple) -> World:
    """Re-apply a recorded composition, with no provider reachable.

    The ledger entry carries the model's whole answer, so a composed corpus
    rebuilds from its recipe exactly as a narrated one does — which is what
    stops a composed estate from being one run's output.
    """
    from .recipe import RecipeError

    for entry in ledger:
        if entry.key == ledger_key and entry.prompt_version == COMPOSE_PROMPT_KEY:
            result = accept(
                world, Composition.model_validate(entry.output), model_id=entry.model_id
            )
            if result.world is None:
                raise RecipeError(
                    "a recorded composition no longer validates against the world it"
                    f" was accepted for: {'; '.join(str(r) for r in result.rejections)}"
                )
            return result.world
    raise RecipeError(
        f"this corpus records a composition ({ledger_key}) that its own generation"
        " ledger does not carry, so it cannot be rebuilt"
    )


__all__ = [
    "COMPOSE_PROMPT_KEY",
    "AcceptResult",
    "ComposeRequest",
    "Composition",
    "MAX_SERVICES",
    "MAX_SYSTEMS",
    "ProposedLore",
    "ProposedService",
    "ProposedSystem",
    "Rejection",
    "accept",
    "replay",
    "request",
    "requests_document",
    "review",
]
