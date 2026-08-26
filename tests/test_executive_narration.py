from __future__ import annotations

from evals.executive_narration import (
    _UNSUPPORTED_SPECIFICITY,
    author_executive,
    corpus_responses,
    section_quality,
)


def test_fixture_style_fact_list_is_rejected_as_underfilled() -> None:
    text = (
        "Revenue was {{fact:FACT-0001}}. Budget was {{fact:FACT-0002}}. "
        "Variance was {{fact:FACT-0003}}."
    )
    findings = section_quality(text)
    assert any(item.startswith("underfilled") for item in findings)
    assert any(item.startswith("fact list") for item in findings)


def test_substantive_bounded_executive_section_passes() -> None:
    text = (
        "Revenue of {{fact:FACT-0001}} finished ahead of the {{fact:FACT-0002}} "
        "plan, with the resulting {{fact:FACT-0003}} variance preserving the "
        "period's top-line position. The result does not resolve the margin "
        "shortfall, so management should keep recovery progress under review. "
        "The committee should note the contrast and request an updated outlook "
        "before the next reporting cycle."
    )
    assert section_quality(text) == []


def test_unsupported_period_counts_and_causes_are_detectable() -> None:
    text = (
        "This is the third consecutive period of structural cost pressure and "
        "requires corrective action on pricing."
    )
    assert {match.group(0).casefold() for match in _UNSUPPORTED_SPECIFICITY.finditer(text)} == {
        "third consecutive",
        "structural cost pressure",
        "corrective action",
        "pricing",
    }


def test_bounded_writer_builds_a_substantive_position_without_inventing_a_cause() -> None:
    request = {
        "id": "ART-0001/In brief",
        "section": "In brief",
        "facts": [
            {"id": "FACT-0001", "kind": "financial.revenue.actual"},
            {"id": "FACT-0002", "kind": "financial.revenue.budget"},
            {"id": "FACT-0003", "kind": "financial.revenue.variance"},
            {"id": "FACT-0004", "kind": "financial.gross_margin_pct.actual"},
            {"id": "FACT-0005", "kind": "financial.gross_margin_pct.budget"},
        ],
    }
    response = author_executive(request)
    assert section_quality(response["text"]) == []
    assert "material movement that requires a decision" in response["text"]
    assert {fact for claim in response["claims"] for fact in claim["supporting_fact_ids"]} == {
        "FACT-0001", "FACT-0002", "FACT-0003", "FACT-0004", "FACT-0005"
    }


def test_bounded_writer_routes_a_synthesised_heading_by_its_facts() -> None:
    request = {
        "id": "ART-0001/Close timetable",
        "section": "Close timetable",
        "facts": [
            {"id": "FACT-0001", "kind": "close.status"},
            {"id": "FACT-0002", "kind": "close.delay"},
            {"id": "FACT-0003", "kind": "financial.incident_pl_impact"},
        ],
    }
    response = author_executive(request)
    assert section_quality(response["text"]) == []
    assert "timing outcome" in response["text"]


def test_corpus_writer_answers_every_section_and_enriches_executive_prose() -> None:
    from worldloom import MonthEndClose, RetailWorld
    from worldloom.narrative import handshake

    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(
            period="2026-03", comparative_months=1,
            include_operational_incident=True,
        )
    ).compile()
    document = corpus_responses(world)
    pending = handshake.pending(world)
    assert len(document["responses"]) == len(pending)
    assert {row["id"] for row in document["responses"]} == {
        f"{request.artifact_id}/{request.section}" for request in pending
    }
    executive_ids = {
        f"{request.artifact_id}/{request.section}"
        for request in pending if request.artifact_type == "executive_summary"
    }
    executive = [row for row in document["responses"] if row["id"] in executive_ids]
    assert executive
    assert all(section_quality(row["text"]) == [] for row in executive)
