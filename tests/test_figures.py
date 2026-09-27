"""A reader spelling: rounded, worded, one precision per sentence, and checkable.

The defects these pin were read off a rendered enterprise/v2 corpus: "AUD
151.325m" beside "AUD 617.2m" in one paragraph, "AUD 958 thousands adverse",
"The number that matters is AUD 0 thousands", "13.40 pct", "3,363
loan_facilities", "control_failure: the mapping table ...". Each is a
spelling, so each is fixed by the profile and never by moving a value, and a
reader's copy of a rounded figure is still the fact (`figures.agrees`).
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from worldloom import figures, presentation
from worldloom.locales import DEFAULT
from worldloom.models import Authority, CanonicalFact, Quantity
from worldloom.narrative import references
from worldloom.presentation import AUDIT, READER

_WHEN = datetime(2026, 3, 31, tzinfo=UTC)


def _fact(fact_id: str, amount: float | None = None, unit: str = "AUD_thousands", *,
          text: str | None = None, kind: str = "financial.gross_profit.variance") -> CanonicalFact:
    return CanonicalFact(
        id=fact_id, kind=kind, subject="COMP-0001", period="2026-03",
        value=Quantity(amount=amount, unit=unit) if amount is not None else None, text_value=text,
        valid_from=_WHEN, authority=Authority.SYSTEM_OF_RECORD,
    )


FACTS = {
    "FACT-0001": _fact("FACT-0001", 617_200.0),
    "FACT-0002": _fact("FACT-0002", 151_325.0),
    "FACT-0003": _fact("FACT-0003", -958.0),
    "FACT-0004": _fact("FACT-0004", 0.0),
    "FACT-0005": _fact("FACT-0005", 13.40, "pct", kind="capital.cet1_ratio"),
    "FACT-0006": _fact("FACT-0006", 3363.0, "loan_facilities", kind="ops.affected_records"),
    "FACT-0007": _fact("FACT-0007", text="control_failure: the mapping table has no registered owner",
                       kind="ops.root_cause_classification"),
    "FACT-0008": _fact("FACT-0008", text="2026-04-24T10:15:00+00:00", kind="capital.return_filed_at"),
    "FACT-0009": _fact("FACT-0009", 600.0, "AUD_millions", kind="capital.rwa_understatement"),
    "FACT-0010": _fact("FACT-0010", -10_200.0),
    "FACT-0011": _fact("FACT-0011", 24.52, "percent", kind="metric.gross_margin_pct.actual"),
    "FACT-0012": _fact("FACT-0012", 25.7, "percent", kind="metric.gross_margin_pct.budget"),
    "FACT-0013": _fact("FACT-0013", 120.0),
    "FACT-0014": _fact("FACT-0014", 12_000.0),
    "FACT-0015": _fact("FACT-0015", 15_500.0, "AUD_millions", kind="capital.rwa_total"),
}


def _spell(text: str, profile: presentation.Presentation = READER) -> str:
    return references.substitute(text, FACTS, locale=DEFAULT, presentation=profile)


def test_the_reader_profile_owns_the_spelling_and_audit_is_untouched() -> None:
    assert READER.spelling == "reader" and AUDIT.spelling == "exact"
    assert "spelling" in presentation.KNOBS and presentation.SPELLINGS == figures.spellings()
    text = "Revenue was {{fact:FACT-0001}}; gross profit {{fact:FACT-0002}}, a gap of {{fact:FACT-0003}}."
    # Audit is the ledger, byte for byte, as every corpus before the knob printed.
    assert _spell(text, AUDIT) == ("Revenue was AUD 617,200 thousands; gross profit AUD 151,325 thousands,"
                                   " a gap of AUD 958 thousands adverse.")


def test_money_is_rounded_per_magnitude_and_consolidated_within_a_sentence() -> None:
    spelled = _spell("Revenue was {{fact:FACT-0001}}; gross profit {{fact:FACT-0002}},"
                     " a variance of {{fact:FACT-0003}}.")
    # One precision for the m figures, and the 958k gap spelled in the
    # sentence's magnitude rather than beside it in thousands.
    assert spelled == "Revenue was AUD 617.2m; gross profit AUD 151.3m, a variance of AUD 1.0m adverse."
    assert figures.defects(spelled) == []
    # A figure the lead's places cannot carry keeps its own magnitude rather
    # than dragging the sentence to two places.
    assert _spell("Revenue {{fact:FACT-0001}}, a gap of {{fact:FACT-0013}}.") == "Revenue AUD 617.2m, a gap of AUD 120k."
    # The fewest places that still carry the rounding, and never fewer
    # significant figures than the floor.
    assert _spell("Assets of {{fact:FACT-0015}}.") == "Assets of AUD 15.5bn."
    assert _spell("Revenue {{fact:FACT-0014}}, a variance of {{fact:FACT-0003}}.") == (
        "Revenue AUD 12.0m, a variance of AUD 1.0m adverse.")
    alone = _spell("The variance was {{fact:FACT-0003}}.")
    assert alone == "The variance was AUD 958k adverse."
    assert "thousands" not in alone


def test_zero_units_percent_dates_and_enums_read_in_words() -> None:
    assert _spell("The effect was {{fact:FACT-0004}}.") == "The effect was nil."
    assert _spell("CET1 was {{fact:FACT-0005}}.") == "CET1 was 13.4%."
    assert _spell("Margin {{fact:FACT-0011}} against {{fact:FACT-0012}}.") == "Margin 24.52% against 25.70%."
    assert _spell("Scope ran to {{fact:FACT-0006}}.") == "Scope ran to 3,363 loan facilities."
    assert _spell("Filed at {{fact:FACT-0008}}.") == "Filed at 24 April 2026, 10:15."
    assert _spell("Classed as {{fact:FACT-0007}}.").startswith("Classed as control failure: the mapping")
    # A ledger held in millions is not relabelled as if it were thousands.
    assert _spell("Understated by {{fact:FACT-0009}}.") == "Understated by AUD 600m."


def test_a_direction_phrase_carries_the_direction_once() -> None:
    assert _spell("A shortfall of {{fact:FACT-0010}}.") == "A shortfall of AUD 10.2m."
    assert _spell("Food finished {{fact:FACT-0010}}.") == "Food finished AUD 10.2m adverse."


@pytest.mark.parametrize(("fact_id", "shown", "agrees"), [
    ("FACT-0002", "AUD 151.3m", True),
    ("FACT-0002", "AUD 151,325 thousands", True),
    ("FACT-0002", "AUD 151.325m", True),
    ("FACT-0002", "AUD 151m", True),
    ("FACT-0002", "AUD 151.4m", False),
    ("FACT-0002", "AUD 150m", False),
    ("FACT-0002", "AUD 0.2bn", False),
    ("FACT-0002", "USD 151.3m", False),
    ("FACT-0003", "AUD 1.0m adverse", True),
    ("FACT-0003", "AUD 958k adverse", True),
    ("FACT-0003", "AUD 958k favourable", False),
    ("FACT-0003", "AUD 1m adverse", False),
    ("FACT-0003", "AUD 0.9m adverse", False),
    ("FACT-0004", "nil", True),
    ("FACT-0001", "nil", False),
    ("FACT-0005", "13.4%", True),
    ("FACT-0005", "13%", True),
    ("FACT-0005", "13.5%", False),
])
def test_agrees_accepts_a_correct_rounding_and_refuses_a_wrong_one(fact_id: str, shown: str, agrees: bool) -> None:
    assert figures.agrees(FACTS[fact_id], shown, locale=DEFAULT, presentation=READER) is agrees


def test_every_enumerated_spelling_agrees_and_includes_the_sentence_spelling() -> None:
    options = figures.spellings_of(FACTS["FACT-0003"], locale=DEFAULT, presentation=READER)
    assert "AUD 1.0m adverse" in options and "AUD 0.96m adverse" in options
    assert all(figures.agrees(FACTS["FACT-0003"], o, locale=DEFAULT, presentation=READER) for o in options)
    assert figures.spellings_of(FACTS["FACT-0003"], locale=DEFAULT, presentation=AUDIT) == ()


@pytest.mark.parametrize(("text", "defect"), [
    ("gross profit of AUD 958 thousands adverse", "unit word"),
    ("The number that matters is AUD 0 thousands", "zero"),
    ("revenue of AUD 617.2m and profit of AUD 151.325m", "over-precise"),
    ("revenue of AUD 617.2m and profit of AUD 151.33m", "over-precise"),
    ("revenue of AUD 617.2m against AUD 630m", "mixed precision"),
    ("a shortfall of AUD 10.2m adverse", "direction said twice"),
    ("CET1 of 13.40 pct", "recorded unit"),
    ("filed at 2026-04-24T10:15:00+00:00", "timestamp"),
    ("AUD 10.2m adverse adverse", "said twice"),
])
def test_defects_names_each_spelling_mistake(text: str, defect: str) -> None:
    assert any(defect in found for found in figures.defects(text)), figures.defects(text)


def test_a_singular_unit_word_is_how_a_reader_says_it() -> None:
    assert figures.defects("a gap of AUD 958 thousand against plan") == []


def test_a_small_figure_that_needs_two_places_is_not_over_precise() -> None:
    assert figures.defects("a gap of AUD 0.12m against AUD 617.2m") == [
        "mixed precision for 'm' figures in one sentence: 'a gap of AUD 0.12m against AUD 617.2m'"]
    assert figures.defects("a gap of AUD 0.12m.") == []
