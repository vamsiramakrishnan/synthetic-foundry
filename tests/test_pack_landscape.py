"""A pack says how much technology its company runs, and in whose words.

`landscape.named`'s error message promised "a pack may also supply pools of
its own" for as long as the module existed, and no pack field read it; the
SDK's `estate(vocabulary=)` was carried and applied nowhere. Both reach the
build now through one builder field, `landscape`, recorded on the recipe
beside the size so an estate rebuilds in the same words from the corpus
alone. Unset, nothing moves: the fields stay off the wire and the estate
speaks the engine's own vocabulary.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from worldloom import QuarterlyCapitalReturn, landscape, packs, recipe
from worldloom.banking import BankingWorld
from worldloom.retail import RetailWorld

INSURER = "examples/packs/regional-insurer.json"
MUTUAL = "examples/packs/mutual-bank.json"


def _pack(path: str, **fields: object) -> packs.Pack:
    document = json.loads(open(path, encoding="utf-8").read())
    document.update(fields)
    return packs.load(document)


def _own_vocabulary() -> dict:
    """Pools of a pack's own: the smallest landscape the type accepts."""
    return {
        "services": {
            "edge": ("quote-portal", "claims-lodgement-web"),
            "domain": ("rating-engine", "claims-triage-service"),
            "platform": ("identity-provider", "event-bus"),
            "data": ("policy-extract", "claims-feed"),
        },
        "systems": [
            ["Policy Register", "Policies of record", "policies"],
            ["Claims Desk", "Claims of record", "claims"],
            ["Document Vault", "Every document, once", "documents"],
        ],
        "purpose": {layer: "Layer: {name}" for layer in landscape.GENERATIVE},
        "profiles": {"only": {"edge": 2, "domain": 2, "platform": 2, "data": 2, "system": 3}},
        "chokepoints": 1,
        "about": "A two-of-everything insurer, for the test.",
    }


def test_an_unset_estate_stays_off_the_wire_and_grows_nothing() -> None:
    pack = _pack(INSURER)
    assert pack.estate == "" and pack.landscape is None
    embedded = packs.to_recipe(pack)
    assert "estate" not in embedded and "landscape" not in embedded
    spec = RetailWorld.from_pack(pack, seed=4242)
    assert spec.estate is None and spec.landscape is None


def test_a_pack_asks_for_an_estate_in_a_registered_vocabulary() -> None:
    pack = _pack(INSURER, estate="small", landscape="insurance")
    assert not [f for f in packs.lint(pack) if "estate" in f or "landscape" in f]
    world = RetailWorld.from_pack(pack, seed=4242).build()
    grown = {s.name for s in world.services} - {s.name for s in RetailWorld.from_pack(_pack(INSURER), seed=4242).build().services}
    assert grown, "the pack's size grew an estate"
    spoken = {name for pool in landscape.INSURANCE.services.values() for name in pool}
    assert grown <= spoken, sorted(grown - spoken)
    assert world.recipe["estate"] == "small" and world.recipe["landscape"] == "insurance"
    again = recipe.rebuild(world.recipe)
    assert [s.name for s in again.services] == [s.name for s in world.services]


def test_a_pack_supplies_pools_of_its_own_and_the_corpus_rebuilds_in_them() -> None:
    own = _own_vocabulary()
    pack = _pack(INSURER, estate="only", landscape=own)
    assert not [f for f in packs.lint(pack) if "estate" in f or "landscape" in f]
    world = RetailWorld.from_pack(pack, seed=4242).build()
    names = {s.name for s in world.services}
    assert {"quote-portal", "rating-engine", "policy-extract"} <= names
    assert "Document Vault" in {s.name for s in world.systems}
    # The recipe stores the pools themselves, not a name it does not have,
    # and the rebuild reads them back with no pack file on hand.
    assert world.recipe["landscape"]["about"] == own["about"]
    again = recipe.rebuild(world.recipe)
    assert [s.name for s in again.services] == [s.name for s in world.services]
    assert [s.model_dump() for s in again.systems] == [s.model_dump() for s in world.systems]


def test_the_banking_engine_reads_the_same_two_fields() -> None:
    pack = _pack(MUTUAL, estate="small")
    world = BankingWorld.from_pack(pack, seed=7).build().run(QuarterlyCapitalReturn(period="2026-03"))
    assert world.recipe["estate"] == "small" and "landscape" not in world.recipe
    spoken = {name for pool in landscape.BANKING.services.values() for name in pool}
    bare = {s.name for s in BankingWorld.from_pack(_pack(MUTUAL), seed=7).build().services}
    assert ({s.name for s in world.services} - bare) <= spoken


def test_the_lint_names_what_the_build_would_refuse() -> None:
    findings = packs.lint(_pack(INSURER, landscape="bankng"))
    assert any("landscape:" in f and "unknown estate vocabulary" in f for f in findings), findings

    findings = packs.lint(_pack(INSURER, estate="huge", landscape="banking"))
    assert any("estate 'huge' names no size" in f for f in findings), findings

    broken = _own_vocabulary()
    broken["systems"] = []
    findings = packs.lint(_pack(INSURER, landscape=broken))
    assert any("landscape:" in f and "at least one system" in f for f in findings), findings

    # A base that grows no estate is named, not silently inert. Every shipped
    # engine registers a vocabulary now, so the branch is reached only by an
    # out-of-tree engine; `lint` refuses an unregistered base before this
    # check runs, which is why it is exercised on the check itself.
    elsewhere = _pack(INSURER, estate="small", landscape="banking").model_copy(update={"base": "logistics"})
    findings = packs._lint_estate(elsewhere)
    assert any("logistics engine grows no estate" in f for f in findings), findings
    assert sum("grows no estate" in f for f in findings) == 2, "the size and the vocabulary are each named"


def test_the_typed_size_wins_over_the_packs_and_the_recipe_says_which() -> None:
    """`--estate` rebinds the builder after `from_pack`, the CLI's order."""
    spec = RetailWorld.from_pack(_pack(INSURER, estate="small", landscape="insurance"), seed=4242)
    typed = replace(spec, estate="medium")
    assert typed.estate == "medium" and typed.landscape == "insurance"


def test_a_blueprint_vocabulary_reaches_the_build_and_the_recipe() -> None:
    from worldloom import sdk

    spoken = sdk.retail(seed=8128).estate("small", vocabulary="banking")
    assert spoken.describe()["landscape"] == "banking"
    plain = sdk.retail(seed=8128).estate("small")
    assert "landscape" not in plain.describe()

    world = spoken.build().world
    assert world.recipe["landscape"] == "banking"
    bare = plain.build().world
    assert "landscape" not in bare.recipe
    grown = {s.name for s in world.services} - {s.name for s in bare.services}
    bank_words = {name for pool in landscape.BANKING.services.values() for name in pool}
    assert grown and grown <= bank_words, sorted(grown - bank_words)


def test_resolve_and_document_of_agree_on_every_shape() -> None:
    assert landscape.resolve(None, default=landscape.BANKING) is landscape.BANKING
    assert landscape.resolve("insurance", default=landscape.RETAIL) is landscape.INSURANCE
    assert landscape.resolve(landscape.RETAIL, default=landscape.BANKING) is landscape.RETAIL
    own = landscape.resolve(_own_vocabulary(), default=landscape.RETAIL)
    assert own.about == "A two-of-everything insurer, for the test."
    assert landscape.document_of("banking") == "banking"
    assert landscape.document_of(own) == own.as_dict() == landscape.document_of(_own_vocabulary())
    with pytest.raises(KeyError, match="unknown estate vocabulary"):
        landscape.document_of("nowhere")
    with pytest.raises(recipe.RecipeError, match="estate vocabulary"):
        recipe._with_landscape(object(), "banking")
