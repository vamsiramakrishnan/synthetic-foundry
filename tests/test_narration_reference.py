"""The reference narration: prose a capable writer produced from these requests.

The deterministic provider proves the *contract* works. It cannot show whether a
request is good enough to be answered well, because it answers everything the same
way. This module runs the narration in `examples/grocery-close/` — 23 sections
written against the real requests — and asserts the harness still accepts it.

The point is not the prose. The point is that if a change makes the requests worse
— drops the section purpose, stops naming subjects, loses the prior period — this
narration keeps being accepted while quietly becoming unanswerable, and the tests
below are where that shows up.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.archetypes import AUSTRALIAN_GROCERY
from worldloom.narrative import handshake, references

NARRATION = Path(__file__).resolve().parents[1] / "examples" / "grocery-close" / "narration.json"
PERIOD = "2026-03"


@pytest.fixture(scope="module")
def staged() -> World:
    world = RetailWorld(seed=8128, archetype=AUSTRALIAN_GROCERY).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True, comparative_months=11)
    )
    return world.compile()


@pytest.fixture(scope="module")
def narration() -> dict:
    return json.loads(NARRATION.read_text())


def test_the_reference_narration_is_accepted_whole(staged: World, narration: dict) -> None:
    """All-or-nothing, exactly as the CLI applies it."""
    responses = handshake.parse_responses(narration)
    verdicts = handshake.review(staged, responses)

    rejected = {rid: v for rid, v in verdicts.items() if not v.accepted}
    assert not rejected, "\n".join(
        f"{rid}: " + "; ".join(f"{x.code} {x.detail}" for x in v.violations)
        for rid, v in rejected.items()
    )


def test_it_answers_every_request_the_corpus_makes(staged: World, narration: dict) -> None:
    """A narration that covers most sections would leave the corpus half-written."""
    pending = {f"{r.artifact_id}/{r.section}" for r in handshake.pending(staged)}
    answered = {r["id"] for r in narration["responses"]}
    assert answered == pending


def test_no_figure_was_typed_rather_than_referenced(narration: dict) -> None:
    """The arithmetic rule, over the reference prose specifically."""
    for response in narration["responses"]:
        assert not references.bare_numbers(response["text"]), response["id"]


def test_the_prose_is_substantial(narration: dict) -> None:
    """Guards against the reference degrading into stubs over time."""
    words = sum(len(r["text"].split()) for r in narration["responses"])
    assert words > 1_500, f"only {words} words"
    assert all(len(r["claims"]) >= 1 for r in narration["responses"])


def test_it_writes_to_the_purpose_rather_than_listing(staged: World, narration: dict) -> None:
    """The property the fixture provider cannot have.

    A listing writes one sentence per fact. Real prose weights them: it spends
    paragraphs on what moved and clauses on what did not. So the reference must
    cite materially fewer facts than it was offered, while still covering every
    fact the artifact exists to convey.
    """
    by_id = {f"{r.artifact_id}/{r.section}": r for r in handshake.pending(staged)}
    texts = {r["id"]: r["text"] for r in narration["responses"]}

    section = by_id["ART-0003/By business unit"]
    used = set(references.referenced(texts["ART-0003/By business unit"]))
    assert len(used) < len(section.allowed_fact_ids) / 2, "every offered fact got a sentence"
    assert set(section.required_fact_ids) <= used

    # And the section that carries the argument reads as an argument.
    drivers = texts["ART-0003/Drivers"]
    assert "structural" in drivers


def test_any_currency_renders_as_money_not_only_the_four_somebody_listed() -> None:
    """A live defect, and the kind a reader finds rather than a test.

    This was an allow-list of AUD/USD/GBP/EUR while `Pack.currency` accepted any
    string, so a pack denominated in AED printed `240,900 AED_thousands` instead
    of `AED 240,900 thousands` — and silently dropped the ` adverse` suffix that
    tells a reader a negative variance is bad news.
    """
    from datetime import datetime, timezone

    from worldloom.models import Authority, CanonicalFact, Quantity
    from worldloom.narrative.references import render_value

    def fact(amount: float, unit: str) -> CanonicalFact:
        return CanonicalFact(
            id="FACT-0001", kind="financial.revenue.actual", subject="BU-0001",
            value=Quantity(amount=amount, unit=unit),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            authority=Authority.SYSTEM_OF_RECORD,
        )

    for code in ("AUD", "AED", "CHF", "SGD", "JPY", "INR"):
        assert render_value(fact(240900, f"{code}_thousands")) == f"{code} 240,900 thousands"
        assert render_value(fact(-2900, f"{code}_thousands")).endswith(" adverse")


def test_a_unit_that_is_not_a_currency_is_not_rendered_as_one() -> None:
    """ISO 4217 is three uppercase letters and nothing else this corpus mints
    resembles that — but the shape test has to be narrow enough to prove it."""
    from datetime import datetime, timezone

    from worldloom.models import Authority, CanonicalFact, Quantity
    from worldloom.narrative.references import render_value

    def fact(unit: str) -> CanonicalFact:
        return CanonicalFact(
            id="FACT-0001", kind="k", subject="s",
            value=Quantity(amount=12, unit=unit),
            valid_from=datetime(2026, 1, 1, tzinfo=timezone.utc),
            authority=Authority.SYSTEM_OF_RECORD,
        )

    assert render_value(fact("SKUs")) == "12 SKUs"
    assert render_value(fact("business_days")) == "12 business days"
    assert render_value(fact("bps")).endswith("favourable")
