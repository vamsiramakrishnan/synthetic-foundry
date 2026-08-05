"""The service estate: an organisation's technology landscape, as a graph.

`worldloom topology` on the largest world this tool builds — 1,607 stores, 34
categories, 7,720 facts — reports **nine** services and systems and a dependency
chain three hops deep. Categories scale with the archetype, sites scale, facts
scale; the estate does not. It is fixed at four services and five systems
because that is exactly what the month-end-close episode names, which makes it
a prop list rather than a landscape.

That has consequences beyond looking thin. Blast radius is meaningless when
nothing has one. "Who gets paged" has a single answer. A question like "which
service's failure would reach the most of the close" is not hard, it is
trivial. And the incident's cause — a stale mapping table between two systems —
reads as an unlucky coincidence rather than as the kind of thing that is
sitting in every estate of this size, because in this estate there is nothing
else it could have been.

This module generates the rest of the landscape around the episode's own
services.

**The episode's services are never touched, and that is load-bearing.**
`organisation.generate` mints four services by hand — the valuation job, the
hierarchy sync, the close orchestrator, the checkout API — and the retail close
depends on their exact identities, their exact dependencies, and the incident
that runs through two of them. Generated services may depend *on* those four;
the four's own `depends_on` lists are never edited. So the episode's causality
is bit-for-bit what it was, the corpus grows a real estate around it, and the
close orchestrator ends up with the large blast radius it always deserved and
never had.

**Layering is what makes it a DAG, rather than a check that hopes it is one.**
Every node sits in a layer, and a service may depend only on something in a
strictly lower layer:

    edge          customer- and colleague-facing      (4)
    domain        business capability services        (3)
    platform      shared services: auth, config, ...  (2)
    data          pipelines, feeds, warehouses        (1)
    system        systems of record                   (0)

A cycle is then not merely unlikely, it is unconstructible, which is a better
guarantee than a validator finding one afterwards. The validator checks it
anyway — `validate.py`'s estate group refuses an upward edge — because a
*model-authored* estate arrives through the same door (`worldloom compose`) and
has no such construction to rely on.

**Chokepoints are placed, not hoped for.** A handful of platform services are
marked as the single provider of their capability, and everything needing that
capability depends on that one node. That is what a real estate looks like —
one identity provider, one config service, one event bus — and it is what makes
`graphs.chokepoints` return something a reader can act on. Drawing dependencies
uniformly at random would produce a graph with a large blast radius everywhere
and no gates anywhere, which is the shape of no organisation that has ever
existed.

**A declared tier that the graph contradicts is a defect, not a rounding.**
`criticality_tier` is derived here from layer and fan-in rather than drawn, so
the number a service declares and the position it actually occupies cannot
disagree. That is exactly the invariant the validator enforces on an estate it
did not generate.

**The construction is the engine's; the words are the vertical's.** Everything
above is industry-agnostic — nothing about layering, chokepoint placement or
derived tiers is retail. What *was* retail is the naming, and it lived here as
four pools and a system table, which is why `--estate` had to be refused for
every other vertical: a bank whose landscape is called `click-collect-api` is
worse than a bank with no landscape. The pools now live in
``worldloom.landscape`` as a named, validated ``Landscape`` a pack or an engine
picks, this module takes one as an argument, and its default is the retail
vocabulary extracted verbatim — so an un-overridden build is the same bytes, not
close to them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..ids import Minter
from ..landscape import DEFAULT as DEFAULT_LANDSCAPE
from ..landscape import Landscape
from ..models import Service, System
from ..rng import Rng

Layer = Literal["edge", "domain", "platform", "data", "system"]

#: Layer to depth. A service may depend only on a strictly lower depth, which
#: is what makes the generated estate acyclic by construction rather than by
#: inspection.
#:
#: Not part of the ``Landscape`` vocabulary, and that is the line between the
#: two modules: these five strings are this generator's coordinate system, not
#: anything a reader sees. Nothing prints them — `Service` carries no layer at
#: all — while the code below reasons about them structurally, building
#: bottom-up in this order, deriving `criticality_tier` from them, and placing
#: the gate at ``DEPTH[layer] > DEPTH["platform"]``. A vocabulary free to rename
#: "platform" would have to move all three, which is the construction that makes
#: a cycle unconstructible.
DEPTH: dict[str, int] = {
    "edge": 4, "domain": 3, "platform": 2, "data": 1, "system": 0,
}

#: The engine's own size profiles and chokepoint count, re-exported from the
#: default vocabulary. Kept as module names because they are what this module
#: has always published — a caller reading `estate.PROFILES` to list the sizes
#: `--estate` accepts should not have to learn where they moved to. A landscape
#: that authors its own is what those callers get when they ask *it*.
PROFILES: dict[str, dict[str, int]] = {
    size: dict(counts) for size, counts in DEFAULT_LANDSCAPE.profiles.items()
}
CHOKEPOINTS = DEFAULT_LANDSCAPE.chokepoints


@dataclass(frozen=True)
class Estate:
    """The generated landscape, ready to append to the organisation's own."""

    systems: tuple[System, ...]
    services: tuple[Service, ...]
    layer_of: dict[str, str]
    """Every generated node's layer, and every *core* node's inferred one — the
    validator needs both to check that no edge points upward, and the core's
    layers are inferred here rather than declared on `Service` so the thin waist
    gains no field for a concept only this generator has."""
    chokepoints: tuple[str, ...]
    """The platform services deliberately made single-provider."""


def core_layers(services: tuple[Service, ...], systems: tuple[System, ...]) -> dict[str, str]:
    """The layer each *hand-written* node occupies, inferred from its edges.

    Inferred rather than declared, because the four episode services predate
    this module by the whole project and giving `Service` a `layer` field to
    satisfy a generator would be exactly the industry-specific contamination of
    the thin waist build-order §7 forbids. A service that depends on nothing
    but systems is data-layer; one that depends on another service is domain;
    one nothing depends on is edge. That is the same reading `graphs.py` does,
    applied to four nodes.
    """
    layers = {system.id: "system" for system in systems}
    depended_on = {target for service in services for target in service.depends_on}
    for service in services:
        if service.id not in depended_on:
            layers[service.id] = "edge"
        elif any(target not in layers or layers[target] != "system"
                 for target in service.depends_on):
            layers[service.id] = "domain"
        else:
            layers[service.id] = "data"
    return layers


def generate(
    rng: Rng,
    minter: Minter,
    *,
    profile: str,
    core_services: tuple[Service, ...],
    core_systems: tuple[System, ...],
    owner_ids: tuple[str, ...],
) -> Estate:
    """Generate the estate around an organisation's own services and systems.

    ``owner_ids`` are the people who may own a service — engineering and
    platform roles, passed in rather than resolved here so this module never
    learns a role key and stays as vertical-agnostic as `org_builder`.
    """
    if profile not in PROFILES:
        raise ValueError(f"unknown estate profile {profile!r}; expected one of {sorted(PROFILES)}")
    if not owner_ids:
        raise ValueError("an estate needs at least one person who can own a service")

    counts = PROFILES[profile]
    layers = core_layers(core_services, core_systems)

    # Systems first: everything else may depend on them, and nothing depends
    # in the other direction.
    systems: list[System] = []
    for index in range(min(counts["system"], len(_SYSTEMS))):
        name, purpose, record = _SYSTEMS[index]
        made = System(
            id=minter.next("SYS"), name=name, purpose=purpose,
            owner_id=rng.derive(f"system/{index}/owner").choice(owner_ids),
            is_system_of_record_for=[record],
        )
        systems.append(made)
        layers[made.id] = "system"

    all_systems = [*core_systems, *systems]
    # The last generated systems are reserved as each chokepoint's *private*
    # backing store, and nothing else may depend on them. That reservation is
    # what actually makes a chokepoint a chokepoint: a shared platform service
    # whose own dependencies everything else can also reach directly dominates
    # nothing, because there is always another path. Giving it something only
    # it can reach is what puts it on the single path — and it is how a real
    # identity provider works, since the credential store is not something the
    # rest of the estate is allowed to query directly.
    reserved = [s.id for s in systems[-CHOKEPOINTS:]] if len(systems) > CHOKEPOINTS else []
    shared_systems = [s.id for s in all_systems if s.id not in reserved]
    by_layer: dict[str, list[str]] = {name: [] for name in DEPTH}
    for node_id, layer in layers.items():
        by_layer[layer].append(node_id)
    for members in by_layer.values():
        members.sort()

    services: list[Service] = []
    chosen_chokepoints: list[str] = []

    def mint(layer: str, name: str, purpose: str, depends_on: list[str],
             system_id: str) -> Service:
        # Tier derived, never drawn: a service's declared criticality and the
        # position it occupies in the graph cannot then disagree, which is the
        # invariant `validate.py` enforces on an estate this module did not
        # generate. Edge and domain services carry the business; a shared
        # platform node that many things route through is tier 1 whatever
        # layer it sits in.
        tier = {"edge": 2, "domain": 2, "platform": 3, "data": 3, "system": 4}[layer]
        made = Service(
            id=minter.next("SVC"), name=name, purpose=purpose,
            owner_id=rng.derive(f"service/{name}/owner").choice(owner_ids),
            system_id=system_id, criticality_tier=tier, depends_on=depends_on,
        )
        services.append(made)
        layers[made.id] = layer
        by_layer[layer].append(made.id)
        return made

    # Built bottom-up so a layer's dependencies already exist when it is
    # reached. `data` before `platform` before `domain` before `edge`.
    pools: dict[str, tuple[str, ...]] = {
        "data": _DATA, "platform": _PLATFORM, "domain": _DOMAIN, "edge": _EDGE,
    }
    for layer in ("data", "platform", "domain", "edge"):
        # Two candidate sets, not one. Drawing uniformly from *everything*
        # lower makes an edge service as likely to depend directly on a system
        # of record as on a domain service, which flattens the estate: the
        # first version of this generator produced 101 nodes and a chain only
        # four hops deep, because most edges skipped straight to the bottom.
        # Weighting the layer immediately below is what gives the graph its
        # depth, and it is also how estates are actually built — a checkout API
        # calls the payments service, not the ledger.
        nearest = sorted(
            node for node, node_layer in layers.items()
            if DEPTH[node_layer] == DEPTH[layer] - 1 and node not in reserved
        )
        anywhere = sorted(
            node for node, node_layer in layers.items()
            if DEPTH[node_layer] < DEPTH[layer] and node not in reserved
        )
        pool = pools[layer]
        for index in range(min(counts[layer], len(pool))):
            name = pool[index]
            draw = rng.derive(f"{layer}/{name}")

            if layer == "platform" and len(chosen_chokepoints) < CHOKEPOINTS and reserved:
                # A single-provider platform service, backed by a store only it
                # may reach. Everything above routes through it, so it is on
                # the single path to that store and `graphs.chokepoints`
                # reports it — which is the whole point of placing them rather
                # than hoping a uniform draw produces one.
                private = reserved[len(chosen_chokepoints)]
                made = mint(layer, name, _PURPOSE[layer].format(name=name),
                            [private], private)
                chosen_chokepoints.append(made.id)
                continue

            system_id = draw.derive("system").choice(shared_systems)
            wanted = draw.derive("fanout").integer(2, 4)
            candidates = nearest or anywhere
            targets = set(draw.derive("targets").sample(
                candidates, min(wanted, len(candidates))
            ))
            # One reach past the nearest layer, so the estate is layered
            # without being strictly stratified — real ones have a domain
            # service that talks to a warehouse system directly, and a graph
            # with no such edge reads as a diagram rather than a landscape.
            if anywhere and draw.derive("skip").chance(0.35):
                targets.add(draw.derive("skip_target").choice(anywhere))
            # Above the platform layer, every service routes through a
            # chokepoint — which is what makes it one. Added rather than
            # substituted, so the service keeps the dependencies it drew.
            if DEPTH[layer] > DEPTH["platform"] and chosen_chokepoints:
                targets.add(draw.derive("gate").choice(chosen_chokepoints))
            # A same-layer call, to an *earlier* service in this layer only.
            # Five layers cap a strictly-stratified estate at four hops, and
            # four hops is not a landscape — real depth comes from services
            # calling their peers. Restricting the target to one already minted
            # keeps the graph acyclic by construction rather than by luck:
            # every same-layer edge points backwards along a fixed order.
            # Core services of this layer are candidates too. Leaving them out
            # meant nothing generated could ever depend on the close
            # orchestrator — an edge service, so no lower layer reaches it —
            # and the most important service in the company kept its blast
            # radius of zero even in a hundred-node estate.
            peers = sorted(
                node for node, node_layer in layers.items()
                if node_layer == layer and node not in reserved
            )
            if peers and draw.derive("peer").chance(0.45):
                targets.add(draw.derive("peer_target").choice(peers))
            mint(layer, name, _PURPOSE[layer].format(name=name), sorted(targets), system_id)

        # Candidate sets are recomputed per layer rather than once, and never
        # include the layer being built: a domain service may depend on another
        # domain service in a real estate, but allowing it here would make the
        # acyclicity a property of draw order rather than of the layering, and
        # "acyclic unless the sampler is unlucky" is not a guarantee.
        # Same-layer edges are the model-authored path's to take, where the
        # validator checks the DAG directly.

    return Estate(
        systems=tuple(systems),
        services=tuple(services),
        layer_of=layers,
        chokepoints=tuple(chosen_chokepoints),
    )


#: One purpose sentence per layer. Terse on purpose: a service catalogue in a
#: real estate is terse, and inventing a paragraph per node would put three
#: hundred sentences of unreviewed prose into a corpus whose whole claim is
#: that its prose is checked.
_PURPOSE: dict[str, str] = {
    "edge": "Customer- or colleague-facing surface: {name}",
    "domain": "Business capability service: {name}",
    "platform": "Shared platform capability used across the estate: {name}",
    "data": "Data pipeline publishing to downstream consumers: {name}",
}


__all__ = ["CHOKEPOINTS", "DEPTH", "PROFILES", "Estate", "core_layers", "generate"]
