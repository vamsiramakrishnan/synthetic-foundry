"""Industry packs: authored worlds through unmodified engines.

The property under test is the §7a boundary: a pack supplies texture — shape,
lore, a name — and the engine keeps the physics. So the shipped example packs
must build coherent, narratable, renderable corpora through BOTH engines with
zero engine edits, rebuild byte-equal from their own recipes with no pack file
on hand, and the lint must name lore the engine would silently ignore.
"""

from __future__ import annotations

import json

import pytest

from worldloom import MonthEndClose, QuarterlyCapitalReturn, packs
from worldloom.banking import BankingWorld
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld

INSURER = "examples/packs/regional-insurer.json"
MUTUAL = "examples/packs/mutual-bank.json"


@pytest.fixture(scope="module")
def insurer():
    pack = packs.load(INSURER)
    return pack, RetailWorld.from_pack(pack, seed=4242).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


@pytest.fixture(scope="module")
def mutual():
    pack = packs.load(MUTUAL)
    return pack, BankingWorld.from_pack(pack, seed=7).build().run(
        QuarterlyCapitalReturn(period="2026-03")
    )


def test_a_pack_names_its_own_fiction(insurer, mutual) -> None:
    _, world = insurer
    assert world.company.name == "Harbourline Insurance Group"
    assert world.company.industry == "General insurance"
    _, bank = mutual
    assert bank.company.name == "Fairmont Mutual Bank"


def test_pack_worlds_are_coherent(insurer, mutual) -> None:
    for _, world in (insurer, mutual):
        report = world.compile().validate()
        assert report.ok, "\n".join(str(v) for v in report.violations)


def test_the_engine_survives_units_it_never_heard_of(insurer, mutual) -> None:
    """The three leaks the first packs found, pinned closed: an incident in a
    world with no 'gm' unit, a merchandising lead with a manager, and a
    banking error scoped to whatever book is actually heaviest."""
    _, world = insurer
    roots = [p for p in world.people if p.manager_id is None]
    assert len(roots) == 1
    found = world.events.where(kind="root_cause_confirmed")[0]
    assert found.business_units, "the incident lands on a real unit"

    _, bank = mutual
    book = bank.entity_names()[bank._roles["cat_sme_secured"]]
    assert book == "Owner-Occupier Home Loans", (
        "with no SME book, the heaviest book by group weight carries the error"
    )


def test_pack_lore_drives_generation(insurer) -> None:
    """A pack's commitments arrive as founding milestones and tag the episode
    — carried and load-bearing, not decoration."""
    pack, world = insurer
    milestones = world.facts.where(kind="lore.milestone")
    assert len(milestones) == len(pack.lore)
    cause = next(
        f for f in world.facts.where(kind="ops.cause") if not f.is_superseded
    )
    assert cause.lore_ids, "the confirmed cause cites the pack's migration decision"


def test_pack_worlds_rebuild_from_their_own_recipes(insurer, mutual) -> None:
    """The recipe embeds the pack, so a corpus rebuilds with no pack file."""
    for _, world in (insurer, mutual):
        assert world.recipe.get("pack"), "the pack travels in the recipe"
        again = rebuild(world.recipe)
        assert [f.model_dump() for f in again.facts] == [
            f.model_dump() for f in world.facts
        ]


def test_a_pack_brands_its_systems(insurer, mutual) -> None:
    """The rename is the brand, never the concept: the insurer's merchandising
    master answers to an insurance name, and its purpose stays the engine's."""
    _, world = insurer
    names = {s.name for s in world.systems}
    assert "Policy and Claims Register" in names
    assert "Actuarial Data Platform" in names
    _, bank = mutual
    assert "MemberCore" in {s.name for s in bank.systems}


def test_a_pack_voices_its_roles(insurer) -> None:
    """A voiced role writes with a cloned persona — override applied, shared
    persona untouched, temperament kept."""
    _, world = insurer
    cfo = world.people.by_id(world._roles["cfo"])
    assert cfo.persona_id == "PERSONA-PACK-CFO"
    voiced = world.personas.by_id("PERSONA-PACK-CFO")
    assert "reserves" in voiced.voice
    assert "loss experience" in voiced.favourite_phrases
    base = world.personas.by_id("PERSONA-CFO")
    assert "reserves" not in base.voice, "the shared persona is cloned, not edited"
    assert voiced.optimism == base.optimism, "temperament stays the engine's"
    # And the per-unit role form works too.
    bp = world.people.by_id(world._roles["personal_bp"])
    assert bp.persona_id == "PERSONA-PACK-PERSONAL-BP"


def test_a_pack_revoices_the_episode(insurer, mutual) -> None:
    """Surface text follows the pack; causality does not. The insurer's
    incident is about claims and peril codes now — same event chain, same
    supersession, same timestamps."""
    _, world = insurer
    failed = world.events.where(kind="pipeline_failed")[0]
    assert "claims reserving pipeline" in failed.summary
    cause = next(f for f in world.facts.where(kind="ops.cause") if not f.is_superseded)
    assert "peril-code mapping" in cause.text_value
    assert cause.supersedes is not None, "causality untouched: the wrong answer still expires"

    _, bank = mutual
    challenge = bank.events.where(kind="challenge_raised")[0]
    assert "Owner-Occupier" in challenge.summary, (
        "the pack's own book is named where the stock archetype's used to be"
    )


def test_episode_text_overrides_survive_the_recipe(insurer) -> None:
    """A re-voiced corpus rebuilds its own voice with no pack file on hand."""
    _, world = insurer
    again = rebuild(world.recipe)
    cause = next(f for f in again.facts.where(kind="ops.cause") if not f.is_superseded)
    assert "peril-code mapping" in cause.text_value


def test_a_pack_revoices_its_evaluation_set(insurer) -> None:
    """The costume problem, one layer further: an insurer's benchmark should
    not still ask about "merchandise category" just because the episode
    itself was re-voiced. `evaluation_text` is the seam that fixes it."""
    _, world = insurer
    questions = [case.question for case in world.evaluations]
    assert not any("merchandise category" in q for q in questions), (
        "the pack overrides this pair; the stock retail phrasing must not leak through"
    )
    assert any("class of business" in q for q in questions)
    assert any("gross written premium" in q for q in questions)


def test_evaluation_text_overrides_survive_the_recipe(insurer) -> None:
    """Same discipline as `episode_text`: a re-voiced benchmark rebuilds its
    own voice with no pack file on hand."""
    _, world = insurer
    again = rebuild(world.recipe)
    questions = [case.question for case in again.evaluations]
    assert any("class of business" in q for q in questions)


def test_the_lint_names_unknown_text_keys_and_slots() -> None:
    pack_dict = json.loads(open(INSURER).read())
    pack_dict["episode_text"]["event.no_such_moment"] = "words"
    pack_dict["episode_text"]["event.pipeline_failed"] = "It broke at {hour}."
    findings = packs.lint(packs.load(pack_dict))
    assert any("event.no_such_moment" in f for f in findings)
    assert any("'hour'" in f for f in findings)


def test_the_lint_names_unknown_evaluation_text_keys_and_slots() -> None:
    """The same contract as `episode_text`'s lint, over the evaluation
    surface: an unknown key and an invented placeholder are both findings,
    and each names `evaluation_text` rather than `episode_text` — the two
    tables share the checking machinery but must not share the message."""
    pack_dict = json.loads(open(INSURER).read())
    pack_dict["evaluation_text"]["q.no_such_question"] = "words"
    pack_dict["evaluation_text"]["q.numerical.worst_category"] = "What about {widget}?"
    findings = packs.lint(packs.load(pack_dict))
    assert any("evaluation_text['q.no_such_question']" in f for f in findings)
    assert any("evaluation_text['q.numerical.worst_category']" in f and "'widget'" in f
               for f in findings)


def test_the_lint_names_unknown_slots_and_roles() -> None:
    pack_dict = json.loads(open(INSURER).read())
    pack_dict["system_brands"]["core_banking"] = "Wrong Engine Brand"
    pack_dict["voices"]["prudential_risk_head"] = {"voice": "not a retail role"}
    findings = packs.lint(packs.load(pack_dict))
    assert any("system_brands['core_banking']" in f for f in findings)
    assert any("voices['prudential_risk_head']" in f for f in findings)


def test_the_lint_names_inert_lore() -> None:
    pack_dict = json.loads(open(INSURER).read())
    pack_dict["lore"].append({
        "kind": "constraint",
        "assertion": "Nobody owns the peril-code mapping.",
        "effective_from": "2025-01",
        "constrains": [{
            "kind": "approval_chains",
            "target": "something_no_engine_reads",
            "effect": "no reviewer",
            "magnitude": 0.0,
        }],
    })
    findings = packs.lint(packs.load(pack_dict))
    assert any("constrains nothing the retail engine consults" in f for f in findings)
    assert any("something_no_engine_reads" not in f or "Consulted targets" in f for f in findings)


def test_the_schema_refuses_a_pack_that_cannot_reconcile() -> None:
    pack_dict = json.loads(open(INSURER).read())
    pack_dict["units"][0]["share"] = 0.9  # 0.9 + 0.42 != 1
    with pytest.raises(Exception, match="unit shares sum"):
        packs.load(pack_dict)

    pack_dict = json.loads(open(INSURER).read())
    pack_dict["units"][0]["categories"][0]["share"] = 0.9
    with pytest.raises(Exception, match="category shares sum"):
        packs.load(pack_dict)


def test_consulted_targets_stay_honest() -> None:
    """Every consulted target the engines publish is genuinely read by some
    generator — the pack author's contract, greppably true. The one templated
    entry (forecast_miss/<unit_key>) is checked by its prefix."""
    from pathlib import Path

    from worldloom.banking import CONSULTED_TARGETS as BANK
    from worldloom.retail import CONSULTED_TARGETS as RETAIL

    src = ""
    for path in Path("src/worldloom").rglob("*.py"):
        src += path.read_text(encoding="utf-8")
    for target, _ in (*RETAIL, *BANK):
        probe = target.split("<")[0].rstrip("/") if "<" in target else target
        assert probe in src, f"published target {target!r} is read by no generator"
