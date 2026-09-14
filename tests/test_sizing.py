"""Size budgets: one declared value where two literal tables used to be.

`compiler.compose` capped components per size class off one dict and
`narrative.compiler` briefed each section's writer off another, two modules
apart, neither reachable from a pack. `sizing` is the one table both now read,
and `SizeBudget` is what a document type declares when no preset fits. Three
claims are pinned here: the presets are the old literals to the number (so a
default build is byte-identical), an unset budget is invisible on every wire
it could reach (intent, plan, doctype), and a declared one actually arrives
at the composer and the writer.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from worldloom import (
    MonthEndClose,
    RetailWorld,
    World,
    doctypes,
    packs,
    registries,
    sizing,
)
from worldloom.compiler import ArtifactPlan, EvidenceRef, NarrativeBeat
from worldloom.compiler.compose import CompositionError, compose
from worldloom.models import ArtifactIntent, SizeBudget
from worldloom.narrative import handshake

EXAMPLES = pathlib.Path(__file__).resolve().parents[1] / "examples" / "artifact-types"
AUTHORED = EXAMPLES / "franchise-network.json"
STATEMENT = "franchisee_trading_statement"
PERIOD = "2026-03"


@pytest.fixture(autouse=True)
def _restore_the_registries():
    with registries.scoped():
        yield


# ---------------------------------------------------------------------------
# The presets are the literals they replaced
# ---------------------------------------------------------------------------


def test_the_presets_are_the_two_tables_they_replaced_to_the_number() -> None:
    """Moving any of these six numbers is a Generation change: every default
    build composes to these caps and is narrated to these briefs."""
    assert {name: b.components for name, b in sizing.PRESETS.items()} == {
        "small": 4, "medium": 7, "long": 12, "xlong": 40,
    }
    assert {name: b.words for name, b in sizing.PRESETS.items()} == {
        "small": 110, "medium": 190, "long": 300, "xlong": 420,
    }
    assert sizing.names() == ("small", "medium", "long", "xlong")


def test_a_declared_budget_wins_over_the_preset_it_sits_beside() -> None:
    own = SizeBudget(components=60, words=450)
    assert sizing.budget_for("small", override=own) == own
    assert sizing.budget_for("small") == sizing.PRESETS["small"]
    with pytest.raises(KeyError, match="no size preset named 'huge'"):
        sizing.budget_for("huge")


# ---------------------------------------------------------------------------
# An unset budget is invisible on every wire
# ---------------------------------------------------------------------------


def _intent(**overrides) -> ArtifactIntent:
    fields = dict(
        id="ART-0001", artifact_type="cfo_variance_memo", domain="finance",
        audience="all_staff", author_id="EMP-0001", size_profile="medium",
    )
    fields.update(overrides)
    return ArtifactIntent(**fields)


def test_an_intent_on_a_preset_keeps_the_wire_it_always_had() -> None:
    """Every corpus built before budgets existed serialises byte for byte."""
    assert "budget" not in _intent().model_dump(mode="json")
    assert "budget" not in json.loads(_intent().model_dump_json())
    dumped = _intent(budget=SizeBudget(components=60, words=450)).model_dump(mode="json")
    assert dumped["budget"] == {"components": 60, "words": 450}
    assert ArtifactIntent.model_validate(dumped).budget == SizeBudget(components=60, words=450)


def test_a_plan_and_a_doctype_drop_an_unset_budget_the_same_way() -> None:
    plan = ArtifactPlan(
        intent_id="ART-0001", artifact_type="cfo_variance_memo", audience="group_cfo",
        intent="explain", beats=[NarrativeBeat(key="position", purpose="p", semantic_role="position")],
    )
    assert "budget" not in plan.model_dump(mode="json")
    assert "budget" in plan.model_copy(update={"budget": SizeBudget(components=9, words=200)}).model_dump(mode="json")

    filing = doctypes.FilingSpec(author_role="cfo", facts=["headline"], rationale="because")
    assert "budget" not in filing.model_dump(mode="json")
    shipped = doctypes.to_document(doctypes.load(_authored(None)["artifact_types"]))
    assert "budget" not in shipped["artifact_types"][0]["filing"]


def test_a_pack_built_corpus_embeds_no_null_budget_in_its_recipe() -> None:
    """The pack rides the recipe verbatim, episodes and doctypes included, so
    an unset budget on either must stay off `world.json` — the leak the pack
    byte-comparison caught was five `"budget": null` lines on episode artifacts."""
    trading = pathlib.Path(__file__).resolve().parents[1] / "examples" / "packs" / "trading-retailer.json"
    pack = packs.load(trading)

    def keys(node: object) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {k for v in node.values() for k in keys(v)}
        if isinstance(node, list):
            return {k for v in node for k in keys(v)}
        return set()

    assert "budget" not in keys(packs.to_recipe(pack))


def test_the_shipped_port_of_the_engine_types_is_untouched() -> None:
    """`examples/artifact-types/core.json` is dumped from the registry; a
    budget field that leaked into it would be a diff on every type."""
    core = json.loads((EXAMPLES / "core.json").read_text(encoding="utf-8"))
    assert not any("budget" in json.dumps(spec) for spec in core["artifact_types"])
    ported = doctypes.load(EXAMPLES / "core.json")
    assert "budget" not in json.dumps(doctypes.to_document(ported))


# ---------------------------------------------------------------------------
# A declared budget reaches the composer and the writer
# ---------------------------------------------------------------------------


def _facts(n: int) -> list[EvidenceRef]:
    return [EvidenceRef(fact_id=f"FACT-{i:04d}", role="driver") for i in range(n)]


def _required(n: int) -> list[NarrativeBeat]:
    return [
        NarrativeBeat(key=f"required_{i}", purpose="p", evidence=_facts(2), semantic_role="position")
        for i in range(n)
    ]


def test_the_composer_caps_by_the_declared_budget_not_the_size_word() -> None:
    plan = ArtifactPlan(
        intent_id="ART-0001", artifact_type="cfo_variance_memo", audience="group_cfo",
        intent="explain", beats=_required(6), size_class="small",
    )
    with pytest.raises(CompositionError) as refused:
        compose(plan, fmt="markdown")
    assert refused.value.code == "over_budget"

    roomy = plan.model_copy(update={"budget": SizeBudget(components=6, words=200)})
    assert len(compose(roomy, fmt="markdown").components) == 6

    # And the new preset composes a plan no old size class could hold.
    long_form = plan.model_copy(update={"size_class": "xlong", "beats": _required(30)})
    assert len(compose(long_form, fmt="markdown").components) == 30


def _authored(budget: dict | None, size: str = "medium") -> dict:
    document = json.loads(AUTHORED.read_text(encoding="utf-8"))
    filing = document["artifact_types"][0]["filing"]
    filing["size"] = size
    if budget is not None:
        filing["budget"] = budget
    return document


def _world(document: dict) -> World:
    pack = packs.load(document)
    return RetailWorld.from_pack(pack, seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


def test_an_authored_budget_rides_the_intent_from_plan_to_writer() -> None:
    """The planner copies the doctype's budget onto the intent, so a process
    that only *loads* the corpus — to narrate or render — has the numbers
    without the pack that declared them."""
    own = {"components": 5, "words": 260}
    world = _world(_authored(own)).compile()
    intent = next(i for i in world.artifact_intents if i.artifact_type == STATEMENT)
    assert intent.size_profile == "medium"
    assert intent.budget == SizeBudget(**own)
    assert sizing.budget_of(intent) == SizeBudget(**own)

    requests = [
        request for request in handshake.requests_document(world)["requests"]
        if request["artifact_id"] == intent.id
    ]
    assert requests, "the statement has prose sections to ask for"
    assert {request["target_words"] for request in requests} == {260}

    # Every engine-planned intent stays on its preset: no budget on the wire,
    # the brief its size always meant.
    others = [i for i in world.artifact_intents if i.artifact_type != STATEMENT]
    assert others and all(i.budget is None for i in others)
    for request in handshake.requests_document(world)["requests"]:
        if request["artifact_id"] != intent.id:
            planned = world.artifact_intents.by_id(request["artifact_id"])
            assert request["target_words"] == sizing.PRESETS[planned.size_profile].words


def test_an_authored_budget_survives_the_recipe_round_trip() -> None:
    from worldloom import recipe as recipe_module

    world = _world(_authored({"components": 5, "words": 260}))
    rebuilt = recipe_module.rebuild(json.loads(json.dumps(world.recipe)))
    assert [(i.artifact_type, i.budget) for i in rebuilt.artifact_intents] == [
        (i.artifact_type, i.budget) for i in world.artifact_intents
    ]


def test_the_xlong_preset_is_a_size_an_authored_type_may_name() -> None:
    world = _world(_authored(None, size="xlong")).compile()
    intent = next(i for i in world.artifact_intents if i.artifact_type == STATEMENT)
    assert intent.size_profile == "xlong" and intent.budget is None
    assert sizing.budget_of(intent) == sizing.PRESETS["xlong"]


# ---------------------------------------------------------------------------
# The lint names a budget the outline cannot fit
# ---------------------------------------------------------------------------


def test_the_lint_refuses_a_budget_below_the_required_sections() -> None:
    types = doctypes.load(_authored({"components": 1, "words": 200})["artifact_types"])
    findings = doctypes.lint(types, base="retail")
    assert any("allows 1 component(s), but the outline declares" in f for f in findings), findings
    assert any("over_budget" in f for f in findings)

    clean = doctypes.lint(doctypes.load(_authored(None)["artifact_types"]), base="retail")
    assert not any("over_budget" in f for f in clean), clean
