"""A connector is not a file format.

SharePoint is one connector that holds docx, xlsx, pptx and pdf; Drive holds a
different set. Until this layer, a SharePoint record was one ``file`` item per
artifact with the artifact's flattened text and no format, so an eval could
not ask for "the deck" as opposed to "the workbook" of the same pack, and an
agent that fetched the item got prose rather than bytes. These tests pin the
contract: once rendered, one record per artifact and format, under the
definition's entity for that format, carrying the rendered file's path, size
and hash; before rendering, the one planned item it always was, byte for
byte; and a demand for a format is constructed by rendering it.
"""
from __future__ import annotations

import hashlib
from datetime import UTC, datetime

from worldloom.connector_data import (
    builtin_projections,
    file_formats,
    generate_artifact_projection,
    rendered_payload,
)
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from worldloom.eval_interventions import construct_candidate
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _world(seed: int = 8128):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=seed).build().run(MonthEndClose(period="2026-03"))


def test_each_file_connector_declares_the_formats_it_holds() -> None:
    assert file_formats("sharepoint") == ("docx", "xlsx", "pptx", "pdf")
    assert file_formats("drive") == ("pdf", "docx", "xlsx")
    assert file_formats("jira") == ()


def test_an_unrendered_world_projects_one_planned_item_per_artifact() -> None:
    world = _world()
    records = generate_artifact_projection(world, "sharepoint")
    assert len(records) == len(world.artifact_intents)
    assert {record.entity for record in records} == {"file"}
    assert all("format" not in record.fields for record in records)


def test_a_rendered_world_projects_one_record_per_artifact_and_format() -> None:
    world = _world().render("docx", "xlsx", "pptx", "pdf")
    records = generate_artifact_projection(world, "sharepoint")

    by_artifact: dict[str, set[str]] = {}
    for record in records:
        by_artifact.setdefault(record.fields["world_artifact_id"], set()).add(record.entity)
    assert set().union(*by_artifact.values()) <= {"docx", "xlsx", "pptx", "pdf"}
    assert any(len(formats) > 1 for formats in by_artifact.values()), "one pack, several files"
    assert len({record.id for record in records}) == len(records)

    for record in records:
        payload = rendered_payload(world, record)
        assert payload is not None
        assert record.fields["size_bytes"] == len(payload)
        assert record.fields["sha256"] == hashlib.sha256(payload).hexdigest()
        assert record.fields["name"].endswith(f".{record.fields['format']}")

    # Drive holds no decks, so the same world projects fewer formats there.
    drive = {record.entity for record in generate_artifact_projection(world, "drive")}
    assert "pptx" not in drive and drive <= {"docx", "xlsx", "pdf"}


def test_the_emulator_searches_across_formats_and_serves_the_hash() -> None:
    world = _world().render("docx", "xlsx")
    definition = load_connector_definition("sharepoint")
    emulator = ConnectorEmulator(definition, builtin_projections().project("sharepoint", world))

    everything = emulator.call("search_files", entity="file", max_results=200)
    only_docx = emulator.call("search_files", entity="docx", max_results=200)
    assert everything["total"] > only_docx["total"] > 0

    item = only_docx["items"][0]
    fetched = emulator.call("get_file", id=item["id"])
    assert fetched["file"]["mimeType"].endswith("wordprocessingml.document")
    assert len(fetched["file"]["hashes"]["sha256Hash"]) == 64
    assert fetched["size"] > 0


def test_a_demand_for_a_format_is_constructed_by_rendering_it() -> None:
    rendered = _world().render("docx")
    doc_type = next(
        intent.artifact_type for intent in rendered.artifact_intents
        if any(item.artifact_id == intent.id and item.path.endswith(".docx") for item in rendered._rendered)
    )
    spec = EvalSpec(
        id="EVALSPEC-DOC", capability="find_document", persona="chief of staff",
        request_template="Find the Word document in SharePoint.",
        steps=(EvalStepSpec(id="find", capability="search", connector="sharepoint", entity="docx"),),
        requirements=(WorldRequirement(
            id="the-doc", kind=RequirementKind.CONNECTOR,
            selector={"connector": "sharepoint", "entity": "docx", "artifact_type": doc_type},
        ),),
        candidate_count=1,
    )
    plan = plan_candidates(spec)[0]
    base = _world(plan.seed)
    result = construct_candidate(spec, plan, base, occurred_at=datetime(2026, 9, 1, tzinfo=UTC))

    assert result.findings == ()
    assert result.candidate.validation.accepted
    check = next(c for c in result.candidate.validation.checks if c.requirement_id == "the-doc")
    assert check.observed >= 1
    assert any(item.path.endswith(".docx") for item in result.candidate.world._rendered)


def test_a_field_a_file_cannot_answer_for_is_refused_with_the_list() -> None:
    spec = EvalSpec(
        id="EVALSPEC-FILE-PRIORITY", capability="find", persona="analyst",
        request_template="Find the urgent workbook.",
        steps=(EvalStepSpec(id="find", capability="search", connector="sharepoint"),),
        requirements=(WorldRequirement(
            id="urgent-file", kind=RequirementKind.CONNECTOR,
            selector={"connector": "sharepoint", "entity": "xlsx", "priority": "urgent"},
        ),),
        candidate_count=1,
    )
    plan = plan_candidates(spec)[0]
    result = construct_candidate(spec, plan, _world(plan.seed), occurred_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert [f.code for f in result.findings] == ["construction_refused"]
    assert "priority" in result.findings[0].detail and "artifact_type" in result.findings[0].detail


def test_two_formats_demanded_on_one_candidate_both_survive() -> None:
    """Review finding: rendering the second format discarded the first."""
    rendered = _world().render("docx", "xlsx")

    def type_with(suffix: str) -> str:
        ids = {i.artifact_id for i in rendered._rendered if i.path.endswith(suffix)}
        return next(i.artifact_type for i in rendered.artifact_intents if i.id in ids)

    doc_type, sheet_type = type_with(".docx"), type_with(".xlsx")
    spec = EvalSpec(
        id="EVALSPEC-TWO-FORMATS", capability="find", persona="analyst", request_template="Find both files.",
        steps=(EvalStepSpec(id="find", capability="search", connector="sharepoint"),),
        requirements=(
            WorldRequirement(id="doc", kind=RequirementKind.CONNECTOR,
                             selector={"connector": "sharepoint", "entity": "docx", "artifact_type": doc_type}),
            WorldRequirement(id="sheet", kind=RequirementKind.CONNECTOR,
                             selector={"connector": "sharepoint", "entity": "xlsx", "artifact_type": sheet_type}),
        ),
        candidate_count=1,
    )
    plan = plan_candidates(spec)[0]
    result = construct_candidate(spec, plan, _world(plan.seed), occurred_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert result.findings == ()
    assert result.candidate.validation.accepted
    suffixes = {item.path[-5:] for item in result.candidate.world._rendered}
    assert ".docx" in suffixes and ".xlsx" in suffixes
