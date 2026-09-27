"""Narration is refused until what a reader will see is clean.

Two live defects, each now a named refusal under a reader spelling (and only
there: every other corpus is judged as it always was):

* ``number_spelling``: the prose as spelled carries a figure no memo prints
  ("{{fact:X}} thousands", "a shortfall of {{fact:X}} adverse").
* ``slug_leak``: the writer typed a recorded identifier ("control_failure:
  the mapping table has no registered owner", ``inventory-valuation``); the
  finding names the words to use.
"""

from __future__ import annotations

from datetime import UTC, datetime

from worldloom import realism_profiles
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import handshake
from worldloom.narrative.claims import validate
from worldloom.narrative.requests import (
    GeneratedClaim,
    GeneratedNarrative,
    NarrativeRequest,
)
from worldloom.presentation import AUDIT, READER
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

_WHEN = datetime(2026, 3, 31, tzinfo=UTC)
FACTS = {
    "FACT-0001": CanonicalFact(id="FACT-0001", kind="financial.gross_profit.variance", subject="COMP-0001",
                               period="2026-03", value=Quantity(amount=-958.0, unit="AUD_thousands"),
                               valid_from=_WHEN, authority=Authority.SYSTEM_OF_RECORD),
    "FACT-0002": CanonicalFact(id="FACT-0002", kind="ops.root_cause_classification", subject="COMP-0001",
                               text_value="control_failure: the mapping table has no registered owner",
                               valid_from=_WHEN, authority=Authority.SYSTEM_OF_RECORD),
}
REQUEST = NarrativeRequest(
    artifact_id="ART-0001", artifact_type="cfo_variance_memo", section="Position", persona_id="",
    voice="plain", audience="board", author_title="CFO", allowed_fact_ids=list(FACTS),
    display={"inventory-valuation": "the inventory valuation service"},
)


def _verdict(text: str, profile=READER):  # type: ignore[no-untyped-def]
    narrative = GeneratedNarrative(text=text, claims=[GeneratedClaim(text=text, supporting_fact_ids=list(FACTS))])
    return validate(REQUEST, narrative, FACTS, presentation=profile)


def test_clean_prose_is_accepted_under_the_reader_spelling() -> None:
    verdict = _verdict("Gross profit finished {{fact:FACT-0001}}; the review classes it as {{fact:FACT-0002}}.")
    assert verdict.accepted, verdict.feedback


def test_a_unit_word_or_a_doubled_direction_is_refused_as_number_spelling() -> None:
    for text in ("Gross profit fell by {{fact:FACT-0001}} thousands, as {{fact:FACT-0002}}.",
                 "A shortfall of {{fact:FACT-0001}} adverse followed {{fact:FACT-0002}}.",
                 "Gross profit was AUD {{fact:FACT-0001}}, as {{fact:FACT-0002}}."):
        verdict = _verdict(text)
        assert not verdict.accepted
        assert any(v.code == "number_spelling" for v in verdict.violations), (text, verdict.feedback)


def test_a_recorded_identifier_is_refused_with_the_words_to_use() -> None:
    verdict = _verdict("The finding is control_failure, per {{fact:FACT-0002}}; the gap is {{fact:FACT-0001}}.")
    leaks = [v for v in verdict.violations if v.code == "slug_leak"]
    assert leaks and "'control failure'" in leaks[0].detail, verdict.feedback
    verdict = _verdict("The inventory-valuation feed failed: {{fact:FACT-0002}}, {{fact:FACT-0001}}.")
    assert any("the inventory valuation service" in v.detail for v in verdict.violations if v.code == "slug_leak")


def test_the_exact_spelling_judges_as_it_always_did() -> None:
    verdict = _verdict("The finding is control_failure, {{fact:FACT-0002}}, {{fact:FACT-0001}} thousands.", AUDIT)
    assert verdict.accepted, verdict.feedback


def test_the_brief_states_the_spelling_rules_and_shows_the_page_spelling() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03", include_operational_incident=True))
    reader = world.extend(recipe=realism_profiles.with_realism(world.recipe, "enterprise")).compile()
    document = handshake.requests_document(reader)
    assert any("number_spelling" in rule for rule in document["rules"])
    assert any("slug_leak" in rule for rule in document["rules"])
    statements = [f["statement"] for r in document["requests"] for f in r["facts"]]
    assert statements and not any(" thousands" in s for s in statements)
    legacy = handshake.requests_document(world.compile())
    assert not any("number_spelling" in rule for rule in legacy["rules"])
    assert any(" thousands" in f["statement"] for r in legacy["requests"] for f in r["facts"])
