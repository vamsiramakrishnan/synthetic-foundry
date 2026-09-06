"""Accountability: the edge from a person to a number they answer for."""

from __future__ import annotations

from worldloom import archetypes, packs
from worldloom.generators.org_builder import ACCOUNTABILITY_KIND, DEFAULT_TOLERANCE_PCT
from worldloom.ids import Minter
from worldloom.models import ConstraintKind, LoreCommitment, LoreConstraint, LoreKind
from worldloom.retail import RetailWorld
from worldloom.rng import Rng


def commitment(minter: Minter, *targets: tuple[str, float | None]) -> LoreCommitment:
    return LoreCommitment(
        id=minter.next("LORE"), kind=LoreKind.NORM,
        assertion="Each division's managing director answers for its revenue against budget.",
        effective_from="2023-04",
        constrains=[
            LoreConstraint(kind=ConstraintKind.ACCOUNTABILITY, target=target,
                           effect="judged on it", magnitude=magnitude)
            for target, magnitude in targets
        ],
    )


def organisation_with(*targets: tuple[str, float | None]):  # type: ignore[no-untyped-def]
    from worldloom.generators import organisation

    minter = Minter()
    lore = (commitment(minter, *targets),)
    return organisation.generate(
        Rng(8128, "organisation"), minter,
        archetype=archetypes.get("omnichannel_retailer"), lore=lore,
    )


def accountabilities(org) -> list:  # type: ignore[no-untyped-def]
    return [f for f in org.founding_facts if f.kind == ACCOUNTABILITY_KIND]


# ---------------------------------------------------------------------------
# The edge itself
# ---------------------------------------------------------------------------


def test_the_fact_subject_is_a_person() -> None:
    """The gap this closes.

    Budgets attach to business units and variances are reported against them,
    so nothing in any corpus this tool had produced said who answered for
    either. This is the first fact in the project whose subject is a person.
    """
    org = organisation_with(("gm_md/financial.revenue.variance", 3.0))
    (fact,) = accountabilities(org)
    assert fact.subject.startswith("PERSON-")
    assert fact.subject in {p.id for p in org.people}


def test_the_fact_carries_both_the_measure_and_the_tolerance() -> None:
    """One claim in two parts: what they are judged on, and how far it may move.

    Two facts would make the second orphanable.
    """
    org = organisation_with(("gm_md/financial.revenue.variance", 3.0))
    (fact,) = accountabilities(org)
    assert fact.text_value == "financial.revenue.variance"
    assert fact.value is not None
    assert (fact.value.amount, fact.value.unit) == (3.0, "percent")


def test_a_tolerance_nobody_stated_falls_back_rather_than_failing() -> None:
    org = organisation_with(("controller/close_cycle_time", None))
    (fact,) = accountabilities(org)
    assert fact.value is not None and fact.value.amount == DEFAULT_TOLERANCE_PCT


def test_the_accountability_begins_when_its_lore_does() -> None:
    """Dating it otherwise would let `World.org_at` report somebody answerable
    for a measure before anyone had made them so."""
    org = organisation_with(("gm_md/financial.revenue.variance", 3.0))
    (fact,) = accountabilities(org)
    assert (fact.valid_from.year, fact.valid_from.month) == (2023, 4)


def test_the_fact_cites_the_commitment_that_created_it() -> None:
    org = organisation_with(("gm_md/financial.revenue.variance", 3.0))
    (fact,) = accountabilities(org)
    assert fact.lore_ids and fact.lore_ids[0].startswith("LORE")


def test_a_target_naming_a_role_this_world_lacks_is_skipped_not_raised() -> None:
    """A pack shared across archetypes will legitimately name a role one of
    them lacks; `packs.lint` is where an author hears about it."""
    org = organisation_with(
        ("gm_md/financial.revenue.variance", 3.0),
        ("chief_actuary/reserves.movement", 2.0),   # an insurer's role, not retail's
    )
    (fact,) = accountabilities(org)
    assert fact.text_value == "financial.revenue.variance"


def test_a_malformed_target_is_skipped() -> None:
    assert accountabilities(organisation_with(("gm_md", 3.0))) == []
    assert accountabilities(organisation_with(("gm_md/", 3.0))) == []


def test_several_accountabilities_all_land() -> None:
    org = organisation_with(
        ("gm_md/financial.revenue.variance", 3.0),
        ("controller/close_cycle_time", 1.0),
        ("cfo/financial.gross_margin_pct.actual", 0.5),
    )
    assert {f.text_value for f in accountabilities(org)} == {
        "financial.revenue.variance", "close_cycle_time",
        "financial.gross_margin_pct.actual",
    }


# ---------------------------------------------------------------------------
# Byte-identity
# ---------------------------------------------------------------------------


def test_a_world_whose_lore_names_no_accountability_mints_none() -> None:
    """No shipped lore carries this kind, so every existing corpus is
    unchanged — which is what made it safe to mint facts inside the org
    generator at all."""
    world = RetailWorld(seed=8128).build()
    assert [f for f in world.facts if f.kind == ACCOUNTABILITY_KIND] == []


def test_accountability_facts_append_and_never_renumber() -> None:
    """Minted after the founding milestones for the same reason those are
    minted last: a fact some narration already cites must keep its id."""
    # The baseline still has to constrain *something* — the schema refuses a
    # commitment that constrains nothing — so it carries a persona trait, which
    # mints no fact.
    from worldloom.generators import organisation

    def built(constraints: list[LoreConstraint]):  # type: ignore[no-untyped-def]
        minter = Minter()
        lore = (LoreCommitment(
            id=minter.next("LORE"), kind=LoreKind.NORM, assertion="A norm.",
            effective_from="2023-04", constrains=constraints,
        ),)
        return organisation.generate(
            Rng(8128, "organisation"), minter,
            archetype=archetypes.get("omnichannel_retailer"), lore=lore,
        )

    trait = LoreConstraint(kind=ConstraintKind.PERSONA_TRAIT,
                           target="controller/anxious", effect="reads anxious", magnitude=0.3)
    plain = built([trait])
    with_one = built([trait, LoreConstraint(
        kind=ConstraintKind.ACCOUNTABILITY, target="gm_md/financial.revenue.variance",
        effect="judged on it", magnitude=3.0)])
    shared = {f.id for f in plain.founding_facts}
    assert shared <= {f.id for f in with_one.founding_facts}
    assert {p.id for p in plain.people} == {p.id for p in with_one.people}


# ---------------------------------------------------------------------------
# What the linter now tells an author
# ---------------------------------------------------------------------------


def base_pack(**extra: object) -> dict:
    return {
        "name": "lint-probe", "base": "retail", "company_name": "Probe Group",
        "industry": "Retail", "annual_revenue": 1_000_000, "employees": 500,
        "units": [{"key": "gm", "name": "General Merchandise", "kind": "general_merchandise",
                   "share": 1.0,
                   "categories": [{"name": "Home", "share": 1.0, "margin": 0.3}]}],
        **extra,
    }


def lint_with(*constraints: dict) -> list[str]:
    pack = packs.load(base_pack(lore=[{
        "kind": "norm", "assertion": "A norm about accountability and targets.",
        "effective_from": "2024-01", "constrains": list(constraints),
    }]))
    return packs.lint(pack)


def test_a_templated_target_is_no_longer_reported_as_inert() -> None:
    """The live false negative.

    Retail publishes `forecast_miss/<unit_key>` because the real key is only
    known once the units are, and the lint compared it by string equality — so
    a pack writing `forecast_miss/gm`, which `finance.generate` genuinely
    reads, was told it would change nothing.
    """
    findings = lint_with({
        "kind": "event_likelihood", "target": "forecast_miss/gm",
        "effect": "the unit misses because of a promotion", "magnitude": 1.4,
    })
    assert not [f for f in findings if "forecast_miss" in f], findings


def test_an_accountability_target_is_recognised() -> None:
    findings = lint_with({
        "kind": "accountability", "target": "gm_md/financial.revenue.variance",
        "effect": "the MD answers for revenue against budget", "magnitude": 3.0,
    })
    assert not [f for f in findings if "accountability" in f], findings


def test_a_misshapen_accountability_target_is_named() -> None:
    findings = lint_with({
        "kind": "accountability", "target": "gm_md",
        "effect": "answers for something", "magnitude": 3.0,
    })
    assert any("ROLE/measure shaped" in f for f in findings), findings


def test_an_inert_constraint_is_reported_even_beside_a_load_bearing_one() -> None:
    """The `hits == 0` test was the only one, so a commitment with one persona
    trait beside three nonsense targets linted clean and the author never heard
    about the three."""
    findings = lint_with(
        {"kind": "persona_trait", "target": "controller/anxious",
         "effect": "reads as anxious in writing", "magnitude": 0.3},
        {"kind": "risk_appetite", "target": "finance/nothing_reads_this",
         "effect": "carried and inert", "magnitude": 0.5},
    )
    assert any("nothing_reads_this" in f and "change nothing" in f for f in findings), findings


def test_the_engines_publish_the_accountability_target() -> None:
    """An author cannot aim at a target they cannot find."""
    from worldloom import banking, insurance, retail

    for module in (retail, banking, insurance):
        assert any("<role_key>/<fact_kind>" == target
                   for target, _ in module.CONSULTED_TARGETS), module.__name__


def test_an_accountability_reaches_a_built_world_through_a_pack() -> None:
    pack = packs.load(base_pack(lore=[{
        "kind": "norm",
        "assertion": "Each division's managing director answers for its revenue against budget.",
        "effective_from": "2023-04",
        "constrains": [{
            "kind": "accountability", "target": "gm_md/financial.revenue.variance",
            "effect": "the MD answers for revenue against budget", "magnitude": 3.0,
        }],
    }]))
    world = RetailWorld.from_pack(pack, seed=8128).build()
    facts = [f for f in world.facts if f.kind == ACCOUNTABILITY_KIND]
    assert len(facts) == 1
    person = world.people.by_id(facts[0].subject)
    assert "Managing Director" in person.title
    assert facts[0].text_value == "financial.revenue.variance"


def test_the_world_still_validates_with_accountabilities_in_it() -> None:
    from worldloom.scenarios import MonthEndClose

    pack = packs.load(base_pack(lore=[{
        "kind": "norm", "assertion": "The controller answers for the close landing on time.",
        "effective_from": "2023-04",
        "constrains": [{"kind": "accountability", "target": "controller/close_cycle_time",
                        "effect": "answers for the close date", "magnitude": 1.0}],
    }]))
    world = RetailWorld.from_pack(pack, seed=8128).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    report = world.validate()
    assert report.ok, [str(v) for v in report.violations[:5]]
