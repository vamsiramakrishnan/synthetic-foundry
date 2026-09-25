"""A section is what its key says, whatever a pack calls it.

Outline headings and the appended "Divisional summary" are display text read
from the prompts pack (``documents.outline.heading.<key>``). Everything
structural (the semantic role, which section a causal flow rides, the
reserved-heading lint) reads the section's key, so a pack can colloquialise
every heading and the documents keep their shape.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

import worldloom
from worldloom import doctypes, documents, packkit
from worldloom.packkit.active import forget_defaults
from worldloom.retail import MonthEndClose, RetailWorld


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


def _pack(root: Path, prompts: dict[str, str]) -> None:
    path = root / "industry" / "spoken.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "worldloom.pack/v1", "kind": "industry", "name": "spoken",
        "body": {"prompts": prompts},
    }))


def _compiled():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    ).compile()


def _ir(world, artifact_type: str):  # type: ignore[no-untyped-def]
    intent = next(i for i in world.artifact_intents if i.artifact_type == artifact_type)
    return next(ir for ir in world.artifact_irs if ir.intent_id == intent.id)


def _plans() -> list[documents.SectionPlan]:
    worldloom._install()
    plans = [p for outline in documents._OUTLINES.values() for p in outline]
    plans += [p for variants in documents._OUTLINE_VARIANTS.values() for v in variants for p in v]
    return plans


def test_every_engine_heading_is_a_prompt_whose_default_is_the_heading() -> None:
    """Default display text is the authored heading, character for character."""
    for plan in _plans():
        assert documents.spoken_heading(plan.heading, plan.structural_key) == plan.heading, plan.heading
    assert documents.spoken_heading(documents.DIVISIONAL_SUMMARY) == "Divisional summary"


def test_keys_are_unique_per_heading() -> None:
    """Two headings sharing a key would share one prompt, so one would speak the other's words."""
    by_key: dict[str, str] = {}
    for plan in _plans():
        assert by_key.setdefault(plan.structural_key, plan.heading) == plan.heading, plan.structural_key
    assert documents.section_key("Root cause and classification") == "root_cause_and_classification"
    assert documents.section_key("Access, and what to do") == "access_and_what_to_do"


def test_renamed_headings_keep_their_structure(tmp_path: Path) -> None:
    """Rename every heading of the RCA and the memo to words carrying other role hints."""
    default = _compiled()
    rca, memo = _ir(default, "incident_rca"), _ir(default, "cfo_variance_memo")
    renamed = {
        f"documents.outline.heading.{documents.section_key(section.heading)}": f"Decision {n}"
        for n, section in enumerate(rca.sections + memo.sections)
    }
    _pack(tmp_path, renamed)
    with packkit.use("industry:spoken", roots=[tmp_path]):
        spoken = _compiled()
    from worldloom.compiler.compose import infer_semantic_role

    def roles(ir):  # type: ignore[no-untyped-def]
        # The role a composer acts on: stated, else inferred from the words shown.
        return [s.semantic_role or infer_semantic_role(s.heading, ()) for s in ir.sections]

    for artifact_type in ("incident_rca", "cfo_variance_memo"):
        before, after = _ir(default, artifact_type), _ir(spoken, artifact_type)
        assert roles(after) == roles(before)
        assert [s.flow is not None for s in after.sections] == [s.flow is not None for s in before.sections]
        assert [s.fact_ids for s in after.sections] == [s.fact_ids for s in before.sections]
    # The sign-off block is appended after the outline and is not one of its headings.
    headings = [s.heading for s in _ir(spoken, "incident_rca").sections
                if not s.hidden and s.heading != "Approval"]
    assert len(headings) == 6 and all(h.startswith("Decision ") for h in headings), headings


def test_the_divisional_summary_is_display_text_with_a_fixed_role(tmp_path: Path) -> None:
    default = _ir(_compiled(), "cfo_variance_memo")
    before = next(s for s in default.sections if s.heading == "Divisional summary")
    # Unset on the engine's own words, which keeps a default IR byte-identical.
    assert before.semantic_role == ""
    _pack(tmp_path, {"documents.outline.heading.divisional_summary": "Branch results"})
    with packkit.use("industry:spoken", roots=[tmp_path]):
        memo = _ir(_compiled(), "cfo_variance_memo")
    after = next(s for s in memo.sections if s.heading == "Branch results")
    assert after.table == before.table and after.fact_ids == before.fact_ids
    # Stated, because a composer infers a missing role from the words shown and
    # "Branch results" would read as evidence where the summary read as summary.
    from worldloom.compiler.compose import infer_semantic_role

    assert after.semantic_role == infer_semantic_role("Divisional summary", ()) == "summary"


def _doctype_findings(heading: str, key: str = "") -> list[str]:
    spec = doctypes.describe("cfo_variance_memo").model_copy(update={"key": "levy_note"})
    section = spec.sections[0].model_copy(update={"heading": heading, "key": key})
    authored = spec.model_copy(update={"sections": [section, *spec.sections[1:]]})
    return [f for f in doctypes.lint([authored]) if "appends a section of its own" in f]


def test_the_reserved_lint_reads_the_key_and_the_displayed_words(tmp_path: Path) -> None:
    worldloom._install()
    assert _doctype_findings("Divisional summary")
    assert _doctype_findings("Divisional Summary"), "same key, same collision"
    assert _doctype_findings("Position of the divisions", key="divisional_summary")
    assert not _doctype_findings("Position of the divisions")
    _pack(tmp_path, {"documents.outline.heading.divisional_summary": "Branch results"})
    with packkit.use("industry:spoken", roots=[tmp_path]):
        assert _doctype_findings("Branch results"), "collides with the words shown"


def test_an_authors_own_heading_is_spoken_as_written() -> None:
    """Only the engine's shipped wording is replaced by its prompt; a heading that
    merely slugs like one (a pack document type's "ROOT CAUSE") keeps its case."""
    from worldloom.documents import spoken_heading

    assert spoken_heading("ROOT CAUSE") == "ROOT CAUSE"
    assert spoken_heading("Root cause") == "Root cause"
    assert spoken_heading("Something bespoke") == "Something bespoke"


def test_a_heading_override_that_collides_with_another_section_is_refused(tmp_path) -> None:
    """Two sections spoken alike share one narration request id; one would be lost."""
    import json

    from worldloom import packkit

    path = tmp_path / "industry" / "clash.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "industry", "name": "clash",
                                "body": {"prompts": {"documents.outline.heading.drivers": "Position"}}}))
    findings = packkit.lint(packkit.resolve("industry:clash", roots=[tmp_path]), roots=[tmp_path])
    assert any("documents.outline.heading.drivers" in f and "cannot share a heading" in f for f in findings)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "industry", "name": "clash",
                                "body": {"prompts": {"documents.outline.heading.drivers": "What moved"}}}))
    packkit.refresh()
    assert packkit.lint(packkit.resolve("industry:clash", roots=[tmp_path]), roots=[tmp_path]) == []


def test_a_pack_doctypes_own_heading_is_displayed_as_written_in_a_document() -> None:
    from worldloom.documents import SectionPlan, spoken_heading

    plan = SectionPlan("ROOT CAUSE", (), "group", "")
    assert spoken_heading(plan.heading, plan.key or None) == "ROOT CAUSE"
