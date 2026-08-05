"""The estate: generated, and authored.

Two paths to the same thing, held to the same standard. `generators/estate.py`
grows a landscape from pools; `compose.py` lets a model author one. The
generated path is checked for the properties it claims to construct — layering,
placed chokepoints, real depth — and the authored path is checked for every
refusal, because a handshake whose grammar has never rejected anything is a
handshake that is not checking.

The one property both must have, and the reason the default is off: a build
that does not ask for an estate is byte-identical to a build made before either
of these existed.
"""

from __future__ import annotations

import json

import pytest

from worldloom import InsuranceWorld, RetailWorld, World, compose, graphs
from worldloom.generators import estate as estate_module
from worldloom.insurance_scenarios import QuarterlyReserving
from worldloom.scenarios import MonthEndClose

SEED = 8128


@pytest.fixture(scope="module")
def grown() -> World:
    return RetailWorld(seed=SEED, estate="medium").build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


# ---------------------------------------------------------------------------
# The generated estate
# ---------------------------------------------------------------------------


def test_the_default_build_is_untouched() -> None:
    """The whole reason the estate is opt-in. Ids are minted per prefix, so the
    estate's ``SVC``/``SYS`` numbers append after the core's without moving a
    single person, category or fact."""
    plain = RetailWorld(seed=SEED).build()
    assert len(list(plain.services)) == 4
    assert len(list(plain.systems)) == 5


def test_an_estate_is_much_larger_than_the_episode_needs(grown: World) -> None:
    reading = graphs.analyse(grown)
    assert len(reading.services) > 30
    # Five layers cap a strictly stratified estate at four hops; the same-layer
    # calls are what take it past that, and a landscape that bottoms out in
    # four is a diagram.
    assert reading.provenance_cycles == ()
    assert graphs._hops(reading.longest_dependency_chain) > 4


def test_the_episodes_own_services_are_untouched(grown: World) -> None:
    """The estate may depend on them; their own dependencies are never edited,
    which is what keeps the incident's causality exactly what it was."""
    plain = RetailWorld(seed=SEED).build()
    core = {s.id: s for s in plain.services}
    for service in grown.services:
        if service.id in core:
            assert service.model_dump() == core[service.id].model_dump()


def test_the_close_orchestrator_finally_has_a_blast_radius(grown: World) -> None:
    """A nine-node estate gives the most important service in the company a
    blast radius of zero. This is what the measure was always meant to say."""
    plain = RetailWorld(seed=SEED).build()
    orchestrator = next(s for s in plain.services if "close-orchestrator" in s.name)
    before = graphs.blast_radius(graphs.dependency_graph(plain), orchestrator.id)
    after = graphs.blast_radius(graphs.dependency_graph(grown), orchestrator.id)
    assert len(after) > len(before)


def test_chokepoints_are_placed_rather_than_hoped_for(grown: World) -> None:
    """Drawing dependencies uniformly gives a graph with a large blast radius
    everywhere and no gates anywhere. The private backing store is what puts a
    shared platform service on the single path to something."""
    gated = dict(graphs.chokepoints(graphs.dependency_graph(grown)))
    names = {s.id: s.name for s in grown.services}
    assert any(names.get(node) == "identity-provider" for node in gated)


def test_the_generated_estate_is_acyclic_by_construction(grown: World) -> None:
    assert graphs.cycles(graphs.dependency_graph(grown)) == ()


def test_a_generated_estate_validates(grown: World) -> None:
    report = grown.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_an_unknown_profile_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown estate profile"):
        RetailWorld(seed=SEED, estate="enormous").build()


def test_the_recipe_rebuilds_a_grown_estate(grown: World, tmp_path) -> None:
    from worldloom.recipe import rebuild

    exported = grown.compile().export(tmp_path / "grown")
    loaded = World.load(exported)
    assert loaded.recipe["estate"] == "medium"
    again = rebuild(loaded.recipe)
    assert [s.model_dump() for s in again.services] == [s.model_dump() for s in grown.services]


def test_a_default_recipe_does_not_carry_the_estate_key(tmp_path) -> None:
    world = RetailWorld(seed=SEED).build().run(MonthEndClose(period="2026-03"))
    exported = world.compile().export(tmp_path / "plain")
    assert "estate" not in World.load(exported).recipe


def test_core_layers_are_inferred_from_the_edges() -> None:
    """`Service` carries no layer, deliberately — giving the thin waist a field
    for a generator's private concept is the contamination §7 forbids."""
    plain = RetailWorld(seed=SEED).build()
    layers = estate_module.core_layers(tuple(plain.services), tuple(plain.systems))
    assert all(layers[s.id] == "system" for s in plain.systems)
    assert set(layers[s.id] for s in plain.services) <= {"edge", "domain", "data"}


# ---------------------------------------------------------------------------
# The estate invariants, each shown firing
# ---------------------------------------------------------------------------


def test_an_isolated_tier_one_service_is_refused(grown: World) -> None:
    from dataclasses import replace

    from worldloom.models import Service

    orphan = Service(
        id="SVC-9901", name="orphan", purpose="nothing depends on it",
        owner_id=next(iter(grown.people)).id, system_id=next(iter(grown.systems)).id,
        criticality_tier=1, depends_on=[],
    )
    tampered = replace(grown, _services=(*grown._services, orphan))
    assert "tier_contradicts_graph" in {v.code for v in tampered.validate().violations}


def test_a_service_on_no_system_is_refused(grown: World) -> None:
    from dataclasses import replace

    victim = list(grown.services)[-1]
    tampered = replace(grown, _services=tuple(
        s.model_copy(update={"system_id": "SYS-9999"}) if s.id == victim.id else s
        for s in grown._services
    ))
    assert "service_without_system" in {v.code for v in tampered.validate().violations}


# ---------------------------------------------------------------------------
# The composition handshake
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def insurer() -> World:
    return InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period="2026-06"))


def _proposal(insurer: World) -> dict:
    """An insurer's estate, in insurance vocabulary — what a model would write.

    Insurance is the case that proves the handshake's reason for existing: it
    ships with **no services at all**, and the generated estate cannot serve it
    because the name pools are retail's.
    """
    people = [p.id for p in insurer.people if p.left is None]
    systems = [s.id for s in insurer.systems]
    return {
        "systems": [
            {"key": "s_identity", "name": "Identity Store",
             "purpose": "Credential and entitlement store for the underwriting estate",
             "owner": people[0], "system_of_record_for": ["credential"]},
        ],
        "services": [
            {"key": "v_auth", "name": "entitlement-service",
             "purpose": "Authenticates and entitles every internal caller",
             "owner": people[0], "runs_on": "s_identity",
             "depends_on": ["s_identity"], "criticality_tier": 1},
            {"key": "v_claims_feed", "name": "claims-transaction-feed",
             "purpose": "Publishes claim payments and case movements nightly",
             "owner": people[1], "runs_on": systems[1],
             "depends_on": [systems[1], "v_auth"], "criticality_tier": 2},
            {"key": "v_triangle", "name": "development-triangle-builder",
             "purpose": "Assembles paid and incurred development triangles",
             "owner": people[1], "runs_on": systems[2],
             "depends_on": ["v_claims_feed"], "criticality_tier": 1},
        ],
        "lore": [
            {"kind": "decision",
             "assertion": "A 2019 broker-channel migration left the legacy submission "
                          "gateway in place for renewals.",
             "effective_from": "2019-04", "visibility": "acknowledged",
             "constrains": [{"kind": "tech_posture", "target": "policy_data/dual_source",
                             "effect": "In-force figures disagree until the monthly "
                                       "reconciliation", "magnitude": 1.4}]},
        ],
    }


def test_a_composed_estate_is_accepted_and_coherent(insurer: World) -> None:
    proposal = compose.Composition.model_validate(_proposal(insurer))
    assert compose.review(insurer, proposal) == []

    result = compose.accept(insurer, proposal, model_id="test")
    assert result.accepted
    assert (result.services_added, result.systems_added, result.lore_added) == (3, 1, 1)
    assert result.world is not None
    report = result.world.validate()
    assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_composed_estate_speaks_the_industrys_language(insurer: World) -> None:
    """The whole reason a model authors this rather than a pool. The generated
    estate's pools are retail's; an insurer built from them would run a
    `click-collect-api`."""
    assert not list(insurer.services)
    result = compose.accept(
        insurer, compose.Composition.model_validate(_proposal(insurer)), model_id="test"
    )
    names = {s.name for s in result.world.services}  # type: ignore[union-attr]
    assert "development-triangle-builder" in names


def test_ids_are_the_harnesss_and_keys_are_the_models(insurer: World) -> None:
    result = compose.accept(
        insurer, compose.Composition.model_validate(_proposal(insurer)), model_id="test"
    )
    ids = [s.id for s in result.world.services]  # type: ignore[union-attr]
    assert len(set(ids)) == len(ids), "every minted id must be distinct"
    assert all(i.startswith("SVC-") for i in ids)


@pytest.mark.parametrize(("label", "mutate", "rule"), [
    ("a cycle", lambda p: p["services"][0]["depends_on"].append("v_triangle"),
     "dependency_cycle"),
    ("a duplicate key", lambda p: p["services"].append(dict(p["services"][0])),
     "duplicate_key"),
    ("a key that is already an id",
     lambda p: p["services"][0].update(key="SYS-0001"), "key_collides_with_id"),
    ("an owner who does not work here",
     lambda p: p["services"][1].update(owner="PERSON-9999"), "unknown_owner"),
    ("a dependency on nothing",
     lambda p: p["services"][1].update(depends_on=["v_ghost"]), "unknown_dependency"),
    ("a system that does not exist",
     lambda p: p["services"][1].update(runs_on="s_ghost"), "unknown_system"),
    ("a tier outside the range",
     lambda p: p["services"][0].update(criticality_tier=9), "tier_out_of_range"),
    ("a service that depends on itself",
     lambda p: p["services"][0]["depends_on"].append("v_auth"), "self_dependency"),
    ("lore effective whenever",
     lambda p: p["lore"][0].update(effective_from="soon"), "bad_effective_from"),
    ("a constraint that constrains nothing",
     lambda p: p["lore"][0]["constrains"][0].update(target="  "), "empty_constraint"),
])
def test_the_grammar_refuses(insurer: World, label: str, mutate, rule: str) -> None:
    """Every rule shown firing. A grammar that has never rejected anything
    proves only that it parses."""
    payload = json.loads(json.dumps(_proposal(insurer)))
    mutate(payload)
    rejections = compose.review(insurer, compose.Composition.model_validate(payload))
    assert rule in {r.rule for r in rejections}, f"{label} was not refused"


def test_an_estate_where_nothing_is_a_single_point_of_failure_is_refused(
    insurer: World,
) -> None:
    """Not a stylistic preference. Every real estate has something with no
    second path around it, and a proposal in which everything is redundant is a
    model describing an ideal rather than a company."""
    systems = [s.id for s in insurer.systems]
    owner = next(p.id for p in insurer.people if p.left is None)
    flat = {
        "systems": [],
        "services": [
            {"key": f"v{i}", "name": f"flat-{i}", "purpose": "x", "owner": owner,
             "runs_on": systems[0], "depends_on": [systems[0]], "criticality_tier": 3}
            for i in range(4)
        ],
        "lore": [],
    }
    rejections = compose.review(insurer, compose.Composition.model_validate(flat))
    assert "no_chokepoint" in {r.rule for r in rejections}


def test_nothing_is_committed_when_anything_is_refused(insurer: World) -> None:
    payload = json.loads(json.dumps(_proposal(insurer)))
    payload["services"][1]["owner"] = "PERSON-9999"
    result = compose.accept(
        insurer, compose.Composition.model_validate(payload), model_id="test"
    )
    assert not result.accepted
    assert result.world is None
    assert (result.services_added, result.systems_added, result.lore_added) == (0, 0, 0)


def test_a_composed_corpus_rebuilds_from_its_ledger(insurer: World, tmp_path) -> None:
    from worldloom.recipe import rebuild

    result = compose.accept(
        insurer, compose.Composition.model_validate(_proposal(insurer)), model_id="test"
    )
    assert result.world is not None
    exported = result.world.compile().export(tmp_path / "composed")
    loaded = World.load(exported)

    again = rebuild(loaded.recipe, ledger=loaded._ledger)
    assert [s.model_dump() for s in again.services] == [
        s.model_dump() for s in result.world.services
    ]
    assert [c.model_dump() for c in again.lore] == [
        c.model_dump() for c in result.world.lore
    ]


def test_rebuilding_without_the_ledger_refuses_rather_than_dropping_the_estate(
    insurer: World, tmp_path,
) -> None:
    """The failure mode worth refusing loudly: silently producing the
    *uncomposed* world would be a corpus that rebuilds into something smaller
    than the one that shipped, with nothing to say so."""
    from worldloom.recipe import RecipeError, rebuild

    result = compose.accept(
        insurer, compose.Composition.model_validate(_proposal(insurer)), model_id="test"
    )
    assert result.world is not None
    loaded = World.load(result.world.compile().export(tmp_path / "composed"))
    with pytest.raises(RecipeError, match="generation ledger"):
        rebuild(loaded.recipe)


def test_the_request_is_self_contained(insurer: World) -> None:
    """An agent should be able to answer without reading this repository."""
    document = compose.requests_document(insurer)
    assert document["industry"] == "General insurance"
    assert document["people"], "no owners offered means nothing can be proposed"
    assert len(document["rules"]) >= 8
    assert document["constraint_vocabulary"], "lore needs its closed vocabulary stated"
    # Every existing service is described with what it depends on, or a model
    # cannot avoid creating a cycle it was never shown.
    assert all("depends_on" in s for s in document["existing_services"])
