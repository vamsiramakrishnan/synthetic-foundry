"""Step 5.3: Word documents.

The interesting test is not that a ``.docx`` opens. It is that the Word document
and the Markdown document of the *same artifact* say the same thing — same
headings, same prose, same figures — because both are projections of one resolved
IR. A renderer that quietly dropped a section or rounded a number differently
would give the corpus two answers to one question, and every other test here
would still pass.
"""

from __future__ import annotations

import io
import zipfile
from datetime import datetime

import docx as python_docx
import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.narrative import DeterministicProvider, references
from worldloom.render import docx as docx_renderer
from worldloom.render import ooxml, slug_for
from worldloom.render.values import format_value

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def rendered() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    return world.narrate(DeterministicProvider()).render("docx", "markdown")


def _files(world: World, suffix: str) -> dict[str, bytes]:
    return {r.artifact_id: r.payload for r in world._rendered if r.path.endswith(suffix)}


def _document(payload: bytes):  # type: ignore[no-untyped-def]
    return python_docx.Document(io.BytesIO(payload))


def _text(payload: bytes) -> str:
    document = _document(payload)
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            parts.extend(cell.text for cell in row.cells)
    return "\n".join(parts)


# ---------------------------------------------------------------------------
# What gets rendered
# ---------------------------------------------------------------------------


def test_every_document_shaped_artifact_becomes_a_word_file(rendered: World) -> None:
    produced = {
        rendered.artifact_intents.by_id(
            next(ir.intent_id for ir in rendered.artifact_irs if ir.id == artifact_id)
        ).artifact_type
        for artifact_id in _files(rendered, ".docx")
    }
    assert produced == docx_renderer.HANDLES & {
        i.artifact_type for i in rendered.artifact_intents
    }
    assert produced, "the episode should plan at least one document"


def test_the_workbook_is_not_rendered_as_a_document(rendered: World) -> None:
    """A spreadsheet flattened into Word loses every formula that made it a source."""
    assert "finance_workbook" not in docx_renderer.HANDLES

    workbooks = [
        i.id for i in rendered.artifact_intents if i.artifact_type == "finance_workbook"
    ]
    assert workbooks
    assert not set(workbooks) & set(_files(rendered, ".docx"))


def test_a_confluence_page_stays_in_confluence(rendered: World) -> None:
    """Rendering it as Word would assert a filing that does not exist."""
    assert "confluence_page" not in docx_renderer.HANDLES


def test_one_artifact_has_one_basename_across_formats(rendered: World) -> None:
    """A reader who finds the Word file should be able to guess its Markdown twin."""
    word = {r.artifact_id: r.path for r in rendered._rendered if r.path.endswith(".docx")}
    markdown = {r.artifact_id: r.path for r in rendered._rendered if r.path.endswith(".md")}
    for artifact_id, path in word.items():
        assert markdown[artifact_id].removesuffix(".md") == path.removesuffix(".docx")


def test_slug_covers_every_planned_type(rendered: World) -> None:
    for intent in rendered.artifact_intents:
        assert slug_for(intent.artifact_type) == slug_for(intent.artifact_type)
        assert "_" not in slug_for(intent.artifact_type)


# ---------------------------------------------------------------------------
# The two formats must agree
# ---------------------------------------------------------------------------


def test_word_and_markdown_carry_the_same_prose(rendered: World) -> None:
    """The claim that matters. Both are projections of one IR; neither may drift."""
    facts = {fact.id: fact for fact in rendered.facts}
    word = _files(rendered, ".docx")
    checked = 0

    for ir in rendered.artifact_irs:
        if ir.id not in word:
            continue
        body = _text(word[ir.id])
        for section in ir.sections:
            assert section.heading in body, f"{ir.id}: missing section {section.heading!r}"
            if section.body:
                resolved = references.substitute(section.body, facts)
                for sentence in resolved.split(". "):
                    fragment = sentence.strip().rstrip(".")
                    if len(fragment) > 20:
                        assert fragment in body, f"{ir.id}: prose dropped — {fragment!r}"
                        checked += 1

    assert checked > 10, f"only compared {checked} fragments"


def test_table_values_match_the_markdown_rendering(rendered: World) -> None:
    """Same cell, same characters — one `format_value`, so neither can round alone."""
    word = _files(rendered, ".docx")
    checked = 0
    for ir in rendered.artifact_irs:
        if ir.id not in word:
            continue
        body = _text(word[ir.id])
        for section in ir.sections:
            if section.table is None:
                continue
            for row in section.table.rows:
                for column in section.table.columns:
                    cell = row.cells.get(column.key)
                    if cell is None or cell.value is None:
                        continue
                    text = format_value(cell.value, column.number_format)
                    assert text in body, f"{ir.id}: cell {row.key}/{column.key} = {text!r} missing"
                    checked += 1
    assert checked > 20, f"only checked {checked} cells"


def test_a_hidden_section_is_written_but_labelled(rendered: World) -> None:
    """Hidden means not part of the readable surface, not undocumented.

    Markdown includes these, so Word must too — one artifact whose appendix
    exists in one format and not the other is two artifacts.
    """
    word = _files(rendered, ".docx")
    ir = next(
        ir for ir in rendered.artifact_irs
        if ir.id in word and any(s.hidden for s in ir.sections)
    )
    body = _text(word[ir.id])
    assert "Not part of the readable surface" in body
    for section in ir.sections:
        if section.hidden:
            assert section.heading in body


def test_no_fact_reference_survives_into_the_document(rendered: World) -> None:
    """An unsubstituted `{{fact:...}}` in a finished document is a broken document."""
    for payload in _files(rendered, ".docx").values():
        body = _text(payload)
        assert "{{fact:" not in body
        assert "[missing " not in body


def test_prose_still_contains_no_bare_number(rendered: World) -> None:
    """The arithmetic rule holds after rendering: figures arrive by substitution."""
    facts = {fact.id: fact for fact in rendered.facts}
    for ir in rendered.artifact_irs:
        for section in ir.sections:
            if section.body:
                assert not references.bare_numbers(section.body), (
                    f"{ir.id}/{section.heading} restated a figure"
                )
                # And the substituted form does contain figures, or the
                # references were decorative.
                assert references.substitute(section.body, facts) != section.body


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_no_clock_reaches_the_document(rendered: World) -> None:
    """Checked as an invariant, not by rendering twice.

    A comparison test passes by luck whenever two runs land in the same second,
    which is how the same defect went unnoticed in the XLSX renderer until CI
    happened to straddle a boundary.
    """
    for ir in rendered.artifact_irs:
        payload = _files(rendered, ".docx").get(ir.id)
        if payload is None:
            continue

        with zipfile.ZipFile(io.BytesIO(payload)) as archive:
            stamps = {info.date_time for info in archive.infolist()}
        assert stamps == {ooxml.EPOCH}, f"{ir.id}: archive carries wall-clock entries {stamps}"

        properties = _document(payload).core_properties
        expected = datetime.fromisoformat(ir.metadata["worldloom_created"])
        assert properties.created == expected
        assert properties.modified == expected
        assert properties.created.year == 2026, "the template's own date leaked through"


def test_the_document_date_is_when_the_artifact_was_written(rendered: World) -> None:
    """It must match the manifest, or a file contradicts the corpus about itself."""
    word = _files(rendered, ".docx")
    for artifact in rendered.artifacts:
        if artifact.id not in word:
            continue
        properties = _document(word[artifact.id]).core_properties
        assert properties.created == artifact.created_at


def test_rendering_twice_is_byte_identical(rendered: World) -> None:
    ir = next(ir for ir in rendered.artifact_irs if ir.id in _files(rendered, ".docx"))
    facts = {fact.id: fact for fact in rendered.facts}
    assert docx_renderer.render(ir, facts) == docx_renderer.render(ir, facts)


def test_acronyms_survive_the_title(rendered: World) -> None:
    """"Cfo Variance Memo" is the tell that a document was generated."""
    titles = {ir.title for ir in rendered.artifact_irs}
    assert "CFO Variance Memo" in titles
    assert not any("Cfo" in title for title in titles)
