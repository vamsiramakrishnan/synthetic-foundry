"""Every engine's offline prose meets the reader-grade floors, not only retail's.

Banking, insurance and procurement builds narrated by the composing narrator
fell below the sentences- and paragraphs-per-section floors, and banking
over the repeated-sentence ceiling: their sections held one or two facts and
the narrator had retail's words for them. The fix is data, not code per
doctype: each engine's industry pack carries its own phrase bank (fact
sentences, nouns, connectives, implications), the rhetoric catalogue gives
their doctypes move sets, a thin section may draw on context facts beside
its own, and a fact kind the corpus keeps citing walks on through its
alternatives. These tests hold all four engines to the same thresholds.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World, prose_quality, realism_profiles
from worldloom.banking import BankingWorld
from worldloom.banking_scenarios import QuarterlyCapitalReturn
from worldloom.insurance import InsuranceWorld
from worldloom.insurance_scenarios import QuarterlyReserving
from worldloom.narrative import ComposedProvider
from worldloom.narrative.composer import _engine_pack
from worldloom.procurement import ProcureToPayWorld
from worldloom.procurement_scenarios import PurchaseToPayCycle

SEED = 8128
PERIOD = "2026-03"

BUILDS = {
    "retail": lambda: RetailWorld(seed=SEED).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)),
    "banking": lambda: BankingWorld(seed=SEED).build().run(QuarterlyCapitalReturn(period=PERIOD)),
    "insurance": lambda: InsuranceWorld(seed=SEED).build().run(QuarterlyReserving(period=PERIOD)),
    "procurement": lambda: ProcureToPayWorld(seed=SEED).build().run(PurchaseToPayCycle(period=PERIOD)),
}


def _narrated(engine: str) -> World:
    world = BUILDS[engine]()
    planned = world.extend(recipe=realism_profiles.with_realism(world.recipe, "enterprise")).compile()
    provider = ComposedProvider.for_world(planned)
    assert provider.engine == engine
    return planned.narrate(provider)


@pytest.fixture(scope="module", params=sorted(BUILDS))
def narrated(request: pytest.FixtureRequest) -> tuple[str, World]:
    return request.param, _narrated(request.param)


def test_each_engine_meets_the_reader_grade_floors(narrated: tuple[str, World]) -> None:
    engine, world = narrated
    reading = prose_quality.measure(world)
    assert prose_quality.failures(reading) == [], (engine, reading.as_dict())
    assert world.validate().ok, engine


def test_the_prose_carries_no_record_spellings(narrated: tuple[str, World]) -> None:
    engine, world = narrated
    reading = prose_quality.measure(world)
    assert reading.slug_leaks == 0 and reading.number_spelling_defects == 0, (engine, reading.examples)


def test_each_non_retail_engine_speaks_through_its_own_industry_pack() -> None:
    for engine, name in (("banking", "banking"), ("insurance", "insurance"),
                         ("procurement", "infrastructure_services")):
        pack = _engine_pack(engine)
        assert pack is not None and pack.name == name, engine
        assert any(key.startswith("narrative.prose.implication.kind.") for key in pack.body.prompts), engine
    assert _engine_pack("no-such-engine") is None


def test_context_facts_are_allowed_never_required_and_never_invented() -> None:
    from worldloom.narrative import handshake

    world = BUILDS["banking"]()
    planned = world.extend(recipe=realism_profiles.with_realism(world.recipe, "enterprise")).compile()
    facts = {fact.id: fact for fact in planned.facts}
    widened = 0
    for request in handshake.pending(planned):
        ir = next(ir for ir in planned.artifact_irs if ir.id == request.artifact_id)
        section = next(s for s in ir.sections if s.heading == request.section)
        extra = set(request.allowed_fact_ids) - set(section.fact_ids) - set(request.comparators.values())
        widened += bool(extra)
        assert not extra & set(request.required_fact_ids)
        assert all(fid in facts and facts[fid].value is not None for fid in extra)
        assert request.recurrence and set(request.recurrence) <= set(request.allowed_fact_ids)
    assert widened, "no thin banking section was given context facts"
