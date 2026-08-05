"""The question a corpus could not ask: who answers for a number that moved.

The family joins three facts that no single document holds — the accountability
(who, and which measure), the variance (how far it moved), and the budget (what
turns an amount into a percentage the band can be compared against).
"""

from __future__ import annotations

import pytest

from worldloom import packs
from worldloom.generators.org_builder import ACCOUNTABILITY_KIND
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

PERIOD = "2026-03"


def pack_with(*accountabilities: tuple[str, float]) -> object:
    """A two-unit retailer whose lore names the given accountabilities.

    Two units on purpose. One would let an unconstrained join look correct by
    accident, and the whole correctness of this family is that it scopes a
    person to their own unit.
    """
    return packs.load({
        "name": "acct-probe", "base": "retail", "company_name": "Probe Group",
        "industry": "Retail", "annual_revenue": 400_000_000, "employees": 900,
        "units": [
            {"key": "gm", "name": "General Merchandise", "kind": "general_merchandise",
             "share": 0.6, "categories": [{"name": "Home", "share": 1.0, "margin": 0.3}]},
            {"key": "digital", "name": "Digital", "kind": "digital", "share": 0.4,
             "categories": [{"name": "Online", "share": 1.0, "margin": 0.28}]},
        ],
        "lore": [{
            "kind": "norm",
            "assertion": "Each division's managing director answers for its revenue.",
            "effective_from": "2023-04",
            "constrains": [
                {"kind": "accountability", "target": target,
                 "effect": "answers for the measure", "magnitude": band}
                for target, band in accountabilities
            ],
        }],
    })


def built(pack: object):  # type: ignore[no-untyped-def]
    return RetailWorld.from_pack(pack, seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True))


def accountability_cases(world) -> list:  # type: ignore[no-untyped-def]
    return [c for c in world.evaluations if "accountable for" in c.question]


# ---------------------------------------------------------------------------
# Nothing, until lore asks
# ---------------------------------------------------------------------------


def test_a_world_with_no_accountability_lore_asks_nothing() -> None:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True))
    assert accountability_cases(world) == []
    assert [f for f in world.facts if f.kind == ACCOUNTABILITY_KIND] == []


def test_the_shipped_evaluation_set_is_unchanged() -> None:
    """No shipped lore names an accountability, so the stock case count must
    not have moved — the family is additive or it is a regression."""
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True))
    assert len(world.evaluations) == 42


# ---------------------------------------------------------------------------
# The join, and the reason it has to be scoped
# ---------------------------------------------------------------------------


def test_a_case_names_the_person_accountable_for_that_unit() -> None:
    world = built(pack_with(("gm_md/financial.revenue.variance", 1.0),
                            ("digital_md/financial.revenue.variance", 1.0)))
    cases = accountability_cases(world)
    assert cases, "a band of 1% should be exceeded by at least one unit"

    people = {p.id: p for p in world.people}
    units = {u.id: u.name for u in world.business_units}
    facts = {f.id: f for f in world.facts}

    for case in cases:
        cited = [facts[i] for i in case.expected_fact_ids]
        (accountability,) = [f for f in cited if f.kind == ACCOUNTABILITY_KIND]
        variances = [f for f in cited if f.kind == "financial.revenue.variance"]
        person = people[accountability.subject]
        # The correctness of the whole family: an accountability's subject is a
        # person and a variance's subject is a unit, so an unconstrained join
        # would name the general-merchandise MD as answerable for the digital
        # unit's miss — a case that is well-formed, citable, and false.
        for variance in variances:
            assert variance.subject == person.business_unit_id
            assert units[variance.subject] in case.question


def test_a_case_joins_three_facts_no_one_document_holds() -> None:
    world = built(pack_with(("digital_md/financial.revenue.variance", 1.0)))
    (case,) = accountability_cases(world)
    kinds = {world_fact.kind for world_fact in
             [f for f in world.facts if f.id in case.expected_fact_ids]}
    assert kinds == {ACCOUNTABILITY_KIND, "financial.revenue.variance",
                     "financial.revenue.budget"}


def test_a_measure_inside_its_band_is_not_a_miss() -> None:
    """Asking who was accountable for a number that behaved is a question with
    no answer."""
    world = built(pack_with(("digital_md/financial.revenue.variance", 99.0)))
    assert [f for f in world.facts if f.kind == ACCOUNTABILITY_KIND], "the fact must exist"
    assert accountability_cases(world) == []


def test_a_person_with_no_unit_is_skipped_rather_than_guessed_at() -> None:
    """A group CFO belongs to no unit, so "their unit's variance" has no
    subject. The family says nothing rather than picking one."""
    world = built(pack_with(("cfo/financial.revenue.variance", 0.1)))
    assert [f for f in world.facts if f.kind == ACCOUNTABILITY_KIND], "the fact must exist"
    assert accountability_cases(world) == []


def test_the_case_is_answerable_from_a_planned_artifact() -> None:
    """`cases.answerable` drops any question whose facts no artifact carries,
    so a family can be perfectly correct and silently discarded."""
    world = built(pack_with(("digital_md/financial.revenue.variance", 1.0)))
    (case,) = accountability_cases(world)
    assert case.required_artifact_ids

    planned = {intent.id: intent for intent in world.artifact_intents}
    carried: set[str] = set()
    for artifact_id in case.required_artifact_ids:
        carried |= set(planned[artifact_id].required_fact_ids)
    missing = set(case.expected_fact_ids) - carried
    assert not missing, f"facts no planned artifact carries: {sorted(missing)}"


def test_the_answer_is_a_person_the_world_actually_employs() -> None:
    world = built(pack_with(("digital_md/financial.revenue.variance", 1.0)))
    (case,) = accountability_cases(world)
    assert case.expected_answer.rstrip(".") in {p.name for p in world.people}


def test_a_world_with_accountability_cases_still_validates() -> None:
    world = built(pack_with(("gm_md/financial.revenue.variance", 1.0),
                            ("digital_md/financial.revenue.variance", 1.0)))
    report = world.validate()
    assert report.ok, [str(v) for v in report.violations[:5]]


def test_the_question_names_the_unit_and_the_period() -> None:
    """Without both, two units' questions are indistinguishable and a retriever
    is being asked something ambiguous rather than something hard."""
    world = built(pack_with(("digital_md/financial.revenue.variance", 1.0)))
    (case,) = accountability_cases(world)
    assert "Digital" in case.question
    assert PERIOD in case.question
