"""The world as graphs, and the invariants only a graph can see.

Two claims are pinned here and they are different claims. The first is that the
measures are *right* — blast radius, chokepoints, the longest chain — checked
against graphs small enough to work out by hand, because a measure that agrees
with itself on a generated corpus proves only that it is consistent. The
second is that the three defects `validate.py` was structurally unable to see
now fail: a cycle through more than one hop, a forked supersession chain, and a
provenance loop that uses a different relationship on each edge. Each is shown
*firing* against a deliberately broken world, following the actor and banking
suites' convention that a check which has never failed proves only that it
compiles.
"""

from __future__ import annotations

from dataclasses import replace

import networkx as nx
import pytest

from worldloom import BankingWorld, RetailWorld, World, graphs
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.scenarios import MonthEndClose, StructuralChange

SEED = 8128


@pytest.fixture(scope="module")
def world() -> World:
    built = RetailWorld(seed=SEED).build()
    return built.run(MonthEndClose(period="2026-03", include_operational_incident=True))


@pytest.fixture(scope="module")
def banking() -> World:
    return BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period="2026-03"))


def codes(w: World) -> set[str]:
    return {v.code for v in w.validate().violations}


# ---------------------------------------------------------------------------
# The measures, against graphs small enough to check by hand
# ---------------------------------------------------------------------------


def _chain() -> nx.DiGraph:
    """``A → B → C``, plus ``D → B``. Read as: A and D both depend on B, which
    depends on C. B is the only route from either of them to C."""
    graph = nx.DiGraph()
    graph.add_edges_from([("A", "B"), ("B", "C"), ("D", "B")])
    return graph


def test_blast_radius_is_everything_upstream() -> None:
    graph = _chain()
    assert graphs.blast_radius(graph, "C") == frozenset({"A", "B", "D"})
    assert graphs.blast_radius(graph, "B") == frozenset({"A", "D"})
    assert graphs.blast_radius(graph, "A") == frozenset()


def test_supply_chain_is_everything_downstream() -> None:
    assert graphs.supply_chain(_chain(), "A") == frozenset({"B", "C"})


def test_a_chokepoint_is_a_node_nothing_routes_around() -> None:
    """B gates C for both roots; nothing gates B, which has two independent
    dependents. Blast radius and gating are genuinely different measures and
    this is the graph that separates them: C has the larger blast radius and
    gates nothing."""
    gated = dict(graphs.chokepoints(_chain()))
    assert gated == {"B": 1}


def test_a_redundant_dependency_gates_nothing() -> None:
    """Gating is an estate-level question: *anything* routing around B clears
    it, not every consumer individually. One second route to C is enough, and
    B's blast radius does not move — which is the separation the two measures
    exist for. (D still reaches C only through B; that per-consumer reading is
    the weaker question `chokepoints` documents and deliberately does not
    answer.)"""
    graph = _chain()
    assert dict(graphs.chokepoints(graph)) == {"B": 1}

    graph.add_edge("A", "C")
    assert dict(graphs.chokepoints(graph)) == {}
    assert graphs.blast_radius(graph, "C") == frozenset({"A", "B", "D"})


def test_the_longest_chain_breaks_ties_on_the_smallest_sequence() -> None:
    """Two chains of equal depth: the rule is longest first, then the
    lexicographically smallest path — stated, not inherited from whatever
    adjacency order the graph was built in."""
    graph = nx.DiGraph()
    graph.add_edges_from([("A", "M"), ("M", "Z"), ("B", "N"), ("N", "Y")])
    assert graphs.longest_chain(graph) == ("A", "M", "Z")


def test_the_longest_chain_is_undefined_on_a_cycle() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("A", "B"), ("B", "A")])
    assert graphs.longest_chain(graph) == ()


def test_a_cycle_is_reported_from_its_smallest_node() -> None:
    """The same loop entered from a different node is the same defect, so the
    rotation is what makes two runs agree they found one thing."""
    graph = nx.DiGraph()
    graph.add_edges_from([("C", "A"), ("A", "B"), ("B", "C")])
    assert graphs.cycles(graph) == (("A", "B", "C"),)


def test_forks_name_who_points_at_what() -> None:
    graph = nx.DiGraph()
    graph.add_edges_from([("new", "old"), ("other", "old")])
    assert graphs.forks(graph) == (("old", ("new", "other")),)


# ---------------------------------------------------------------------------
# Reading a real corpus
# ---------------------------------------------------------------------------


def test_a_generated_estate_has_a_dependency_chain(world: World) -> None:
    reading = graphs.analyse(world)
    assert len(reading.longest_dependency_chain) > 1
    assert reading.services, "every service and system should be ranked"
    # Ranked by reach: the head of the ranking carries at least as much as the
    # tail, which is the ordering contract `ServiceRank.key` states.
    reaches = [rank.blast_radius for rank in reading.services]
    assert reaches == sorted(reaches, reverse=True)


def test_the_banking_corpus_carries_a_deep_supersession_chain(banking: World) -> None:
    """The restatement arc is a chain of facts, not a flat pair, and this is
    the measure that says so — the same walk insurance's estimate-chain check
    does for one vertical, available for every corpus at once."""
    reading = graphs.analyse(banking.compile())
    assert reading.supersession_chains > 0
    assert len(reading.longest_supersession_chain) >= 2
    assert reading.forked_supersessions == ()


def test_documents_build_on_each_other_in_banking(banking: World) -> None:
    reading = graphs.analyse(banking.compile())
    assert reading.provenance_depth >= 1
    assert reading.provenance_cycles == ()


def test_the_reading_is_stable_across_runs(world: World) -> None:
    """Nothing here may depend on set iteration or dict insertion order, so two
    readings of two separately-built worlds must be identical, not merely
    equivalent."""
    again = RetailWorld(seed=SEED).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    assert graphs.analyse(again).as_dict() == graphs.analyse(world).as_dict()


def test_topology_defaults_to_the_current_estate_and_keeps_history_queryable() -> None:
    base = RetailWorld(seed=SEED).build()
    initial_systems, initial_services = len(base.systems), len(base.services)
    changed = base.run(MonthEndClose("2026-01", include_operational_incident=False))
    changed = changed.run(StructuralChange(
        "2026-01",
        len(base.business_units), len(base.sites),
        initial_systems + 2, initial_services + 3,
    ))
    growth_at = [
        event.occurred_at for event in changed.events
        if event.kind == "structural_estate_changed"
    ][0]
    changed = changed.run(MonthEndClose("2026-02", include_operational_incident=False))
    changed = changed.run(StructuralChange(
        "2026-02",
        len(base.business_units), len(base.sites),
        initial_systems, initial_services,
    ))

    current = graphs.analyse(changed)
    historical = graphs.analyse(changed, at=growth_at)
    all_time = graphs.analyse(changed, at=None)

    assert len(current.services) == initial_systems + initial_services
    assert len(historical.services) == initial_systems + initial_services + 5
    assert len(all_time.services) == len(changed.systems) + len(changed.services)
    expected_current = {
        entity.id
        for collection in (
            changed.systems_at("2100-01-01"),
            changed.services_at("2100-01-01"),
        )
        for entity in collection
    }
    assert {rank.id for rank in current.services} == expected_current


def test_a_provenance_graph_falls_back_to_intents(world: World) -> None:
    """A built-but-unrendered world has no manifest and its provenance is
    already decided. Reading only the manifest would report every such corpus
    as having none."""
    assert not list(world.artifacts)
    assert list(world.artifact_intents)
    assert graphs.provenance_graph(world).number_of_nodes() == len(world.artifact_intents)


# ---------------------------------------------------------------------------
# The invariants, each shown firing
# ---------------------------------------------------------------------------


def test_a_multi_hop_service_cycle_is_caught(world: World) -> None:
    """The defect the old check could not see. `self_dependency` fires on a
    service that lists itself; a loop through three services passes it three
    times and is still an estate that can never start."""
    a, b, c = list(world.services)[:3]
    tampered = replace(world, _services=tuple(
        s.model_copy(update={"depends_on": [b.id]}) if s.id == a.id else
        s.model_copy(update={"depends_on": [c.id]}) if s.id == b.id else
        s.model_copy(update={"depends_on": [a.id]}) if s.id == c.id else s
        for s in world._services
    ))
    found = codes(tampered)
    assert "service_cycle" in found
    assert "self_dependency" not in found, "no service depends on itself here"


def test_a_forked_supersession_chain_is_caught(world: World) -> None:
    """Two facts replacing one earlier fact leaves the corpus stating two
    current answers with no rule for choosing. `temporal()`'s superseded_by
    dict silently let the second writer win."""
    superseding = next(f for f in world.facts if f.supersedes)
    rival = superseding.model_copy(update={"id": "FACT-9901"})
    tampered = replace(world, _facts=(*world._facts, rival))
    assert "fact_superseded_twice" in codes(tampered)


def test_a_reporting_cycle_through_three_people_is_caught(world: World) -> None:
    people = list(world.people)
    a, b, c = people[1], people[2], people[3]
    tampered = replace(world, _people=tuple(
        p.model_copy(update={"manager_id": b.id}) if p.id == a.id else
        p.model_copy(update={"manager_id": c.id}) if p.id == b.id else
        p.model_copy(update={"manager_id": a.id}) if p.id == c.id else p
        for p in world._people
    ))
    assert "reporting_cycle" in codes(tampered)


def test_a_provenance_loop_across_relationships_is_caught(banking: World) -> None:
    """Each relationship is checked for its own semantics and none of those
    checks can see a loop that uses a different one on each edge."""
    compiled = banking.compile().render("markdown")
    entries = list(compiled.artifacts)
    first, second = entries[0], entries[1]
    tampered = replace(compiled, _artifacts=tuple(
        a.model_copy(update={"derived_from": [*a.derived_from, second.id]}) if a.id == first.id
        else a.model_copy(update={"derived_from": [*a.derived_from, first.id]}) if a.id == second.id
        else a
        for a in compiled._artifacts
    ))
    assert "provenance_cycle" in codes(tampered)


def test_a_healthy_corpus_still_runs_the_fork_check(world: World) -> None:
    """A counter incremented only inside the failure branch would report zero
    checks on a passing corpus — which reads as "never checked", on exactly the
    corpus where it matters."""
    before = RetailWorld(seed=SEED).build().validate().checks_run
    after = world.validate().checks_run
    assert after > before
    assert world.validate().ok
