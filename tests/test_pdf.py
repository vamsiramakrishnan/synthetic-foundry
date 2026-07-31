"""Step 5.4: native PDF.

The interesting property is not that a ``.pdf`` opens. It is the one
``docs/artifact-compiler.md`` §9.4 draws the line on: a *derived* PDF goes
through an external, version-dependent binary and can never be byte-reproducible
across machines, so it can only ever be a preview. This renderer exists because
``-f pdf`` has to be a real corpus artifact — a deterministic projection of the
same ``ArtifactIR`` the DOCX and Markdown renderers read, with no external binary
anywhere in the path. Every test below is either checking that projection is
faithful (same figures as Markdown, no invented numbers) or checking the
determinism claim directly (same bytes, twice, in separate processes).
"""

from __future__ import annotations

import re
import subprocess
import sys
import textwrap

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.models import ArtifactIR, ArtifactSection, Cell, Column, Row, Table
from worldloom.narrative import DeterministicProvider, references
from worldloom.render import RenderError, available
from worldloom.render import pdf as pdf_renderer
from worldloom.render import ooxml
from worldloom.render.values import format_value

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def rendered() -> World:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    return world.narrate(DeterministicProvider()).render("pdf", "docx", "markdown")


def _files(world: World, suffix: str) -> dict[str, bytes]:
    return {r.artifact_id: r.payload for r in world._rendered if r.path.endswith(suffix)}


# ---------------------------------------------------------------------------
# A minimal PDF text recovery, for asserting content rather than just bytes
# ---------------------------------------------------------------------------
#
# `pageCompression=0` (see `render/pdf.py::render`) keeps every content stream
# as literal bytes rather than deflated ones specifically so a figure can be
# checked for the same way `test_docx.py` checks one — by looking at the text a
# reader would see. This is not a general PDF parser: it recovers exactly what
# reportlab emits for a `Tj`/`TJ` show-text operator, which is all a renderer
# under our own control needs.

_TJ = re.compile(rb"\(((?:[^()\\]|\\.)*)\)\s*Tj")
_TJ_ARRAY = re.compile(rb"\[((?:[^\[\]]|\\.)*)\]\s*TJ")
_TJ_ARRAY_STRING = re.compile(rb"\(((?:[^()\\]|\\.)*)\)")


def _pdf_text(payload: bytes) -> str:
    parts: list[bytes] = [m.group(1) for m in _TJ.finditer(payload)]
    for array in _TJ_ARRAY.finditer(payload):
        parts.extend(s.group(1) for s in _TJ_ARRAY_STRING.finditer(array.group(1)))
    text = b" ".join(parts)
    text = text.replace(rb"\(", b"(").replace(rb"\)", b")").replace(rb"\\", b"\\")
    return text.decode("latin1")


def _page_count(payload: bytes) -> int:
    # The /Pages dictionary's own key order is reportlab's choice — /Count has
    # come both before and after /Type /Pages across the fixtures used to build
    # this test — so this matches the whole `<< ... >>` body and pulls /Count
    # out of it, rather than assuming one order.
    dictionary = re.search(rb"<<([^<>]*?/Type\s*/Pages[^<>]*?)>>", payload, re.S)
    assert dictionary, "no /Pages object found"
    match = re.search(rb"/Count\s+(\d+)", dictionary.group(1))
    assert match, "the /Pages object has no /Count"
    return int(match.group(1))


# ---------------------------------------------------------------------------
# What gets rendered
# ---------------------------------------------------------------------------


def test_every_document_shaped_artifact_becomes_a_pdf_file(rendered: World) -> None:
    """The same set DOCX handles — a native-PDF artifact and a Word artifact are
    the same document-shaped content in two fixed-page formats."""
    produced = {
        rendered.artifact_intents.by_id(
            next(ir.intent_id for ir in rendered.artifact_irs if ir.id == artifact_id)
        ).artifact_type
        for artifact_id in _files(rendered, ".pdf")
    }
    assert produced == pdf_renderer.HANDLES & {
        i.artifact_type for i in rendered.artifact_intents
    }
    assert produced, "the episode should plan at least one document"


def test_pdf_and_docx_render_the_same_artifacts(rendered: World) -> None:
    """`render/pdf.py` reuses `docx.HANDLES` rather than a second hand-kept list
    — this is the test that would catch the two silently drifting apart."""
    pdf_ids = set(_files(rendered, ".pdf"))
    docx_ids = set(_files(rendered, ".docx"))
    assert pdf_ids == docx_ids


def test_the_workbook_is_not_rendered_as_a_pdf(rendered: World) -> None:
    assert "finance_workbook" not in pdf_renderer.HANDLES
    workbooks = [i.id for i in rendered.artifact_intents if i.artifact_type == "finance_workbook"]
    assert workbooks
    assert not set(workbooks) & set(_files(rendered, ".pdf"))


def test_one_artifact_has_one_basename_across_formats(rendered: World) -> None:
    pdfs = {r.artifact_id: r.path for r in rendered._rendered if r.path.endswith(".pdf")}
    markdown = {r.artifact_id: r.path for r in rendered._rendered if r.path.endswith(".md")}
    for artifact_id, path in pdfs.items():
        assert markdown[artifact_id].removesuffix(".md") == path.removesuffix(".pdf")


# ---------------------------------------------------------------------------
# It is a PDF at all
# ---------------------------------------------------------------------------


def test_every_pdf_starts_with_the_pdf_header(rendered: World) -> None:
    for payload in _files(rendered, ".pdf").values():
        assert payload, "empty PDF"
        assert payload.startswith(b"%PDF-"), payload[:16]


# ---------------------------------------------------------------------------
# Determinism — the property a derived PDF could not offer
# ---------------------------------------------------------------------------


def test_rendering_twice_is_byte_identical(rendered: World) -> None:
    ir = next(ir for ir in rendered.artifact_irs if ir.id in _files(rendered, ".pdf"))
    facts = {fact.id: fact for fact in rendered.facts}
    intent = rendered.artifact_intents.by_id(ir.intent_id)
    first = pdf_renderer.render(ir, facts, artifact_type=intent.artifact_type, size_class=intent.size_profile)
    second = pdf_renderer.render(ir, facts, artifact_type=intent.artifact_type, size_class=intent.size_profile)
    assert first == second


def test_rendering_is_byte_identical_across_separate_processes() -> None:
    """The determinism proof that matters: nothing in-process — module caching,
    a memoised style object, an object id leaking into a hash — is doing the
    work. Two cold interpreters, same seed, must agree bit for bit.
    """
    script = textwrap.dedent(
        """
        import sys
        from worldloom import MonthEndClose, RetailWorld
        from worldloom.narrative import DeterministicProvider
        from worldloom.render import pdf as pdf_renderer

        world = RetailWorld(seed=8128).build().run(
            MonthEndClose(period="2026-03", include_operational_incident=True)
        )
        world = world.narrate(DeterministicProvider())
        facts = {f.id: f for f in world.facts}
        ir = next(
            ir for ir in world.artifact_irs
            if world.artifact_intents.by_id(ir.intent_id).artifact_type == "cfo_variance_memo"
        )
        intent = world.artifact_intents.by_id(ir.intent_id)
        sys.stdout.buffer.write(
            pdf_renderer.render(ir, facts, artifact_type=intent.artifact_type, size_class=intent.size_profile)
        )
        """
    )
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True)
    assert first.stdout, "subprocess produced no bytes"
    assert first.stdout == second.stdout


def test_no_wall_clock_date_survives_into_the_pdf(rendered: World) -> None:
    """`/CreationDate` and `/ModDate` must be the same fixed instant
    `render/ooxml.py` uses for the Office formats, not `now()` and not
    reportlab's own default invariant epoch (2000-01-01) — see
    `render/pdf.py::_normalise`.
    """
    expected = pdf_renderer._pdf_date(ooxml.EPOCH).encode()
    for payload in _files(rendered, ".pdf").values():
        creation = re.search(rb"/CreationDate\s*\(([^)]*)\)", payload)
        modified = re.search(rb"/ModDate\s*\(([^)]*)\)", payload)
        assert creation and modified, "Info dictionary is missing a date"
        assert creation.group(1) == expected, creation.group(1)
        assert modified.group(1) == expected, modified.group(1)
        # Belt and braces: the current year must not appear in either field,
        # which is the failure this test exists to catch even if the exact
        # epoch format above ever changes.
        assert b"2026" not in creation.group(1)
        assert b"2026" not in modified.group(1)


def test_the_id_array_does_not_change_between_renders(rendered: World) -> None:
    """`/ID` is a hash of document content salted with reportlab's `invariant`
    instant (see `_normalise`'s docstring) rather than a literal constant — it
    is legitimate for two *different* documents to carry different IDs. What
    must not happen is the same document carrying a different one on a second
    render, which is exactly what a clock- or random-salted ID would do.
    """
    ir = next(ir for ir in rendered.artifact_irs if ir.id in _files(rendered, ".pdf"))
    facts = {fact.id: fact for fact in rendered.facts}
    intent = rendered.artifact_intents.by_id(ir.intent_id)
    first = pdf_renderer.render(ir, facts, artifact_type=intent.artifact_type, size_class=intent.size_profile)
    second = pdf_renderer.render(ir, facts, artifact_type=intent.artifact_type, size_class=intent.size_profile)

    def id_of(payload: bytes) -> bytes:
        match = re.search(rb"/ID\s*\n?\[([^\]]*)\]", payload)
        assert match, "no /ID array"
        return match.group(1)

    assert id_of(first) == id_of(second)


def test_render_is_deterministic_end_to_end() -> None:
    def build() -> World:
        return (
            RetailWorld(seed=8128).build()
            .run(MonthEndClose(period=PERIOD, include_operational_incident=True))
            .narrate(DeterministicProvider())
            .render("pdf")
        )

    first = {item.path: item.payload for item in build()._rendered}
    second = {item.path: item.payload for item in build()._rendered}
    assert first == second


# ---------------------------------------------------------------------------
# Faithfulness — no invented facts, cross-format agreement
# ---------------------------------------------------------------------------


def test_every_numeric_table_cell_traces_to_the_ir(rendered: World) -> None:
    """The renderer introduces no facts or values: every figure that appears in
    a resolved table must appear in the PDF exactly as `format_value` — the
    same function Markdown and DOCX use — renders that cell. No PDF-specific
    rounding, no invented total.
    """
    pdfs = _files(rendered, ".pdf")
    checked = 0
    for ir in rendered.artifact_irs:
        payload = pdfs.get(ir.id)
        if payload is None:
            continue
        text = _pdf_text(payload)
        for section in ir.sections:
            if section.table is None:
                continue
            for row in section.table.rows:
                for column in section.table.columns:
                    cell = row.cells.get(column.key)
                    if cell is None or not isinstance(cell.value, (int, float)):
                        continue
                    expected = format_value(cell.value, column.number_format)
                    assert expected in text, (
                        f"{ir.id}: cell {row.key}/{column.key} = {expected!r} missing from the PDF"
                    )
                    checked += 1
    assert checked > 5, f"only checked {checked} numeric cells — the sweep is not covering the corpus"


def test_prose_figures_match_the_fact_ledger(rendered: World) -> None:
    """Every substituted ``{{fact:...}}`` value must appear in the PDF text,
    read back from the same ledger the request was written against.
    """
    facts = {fact.id: fact for fact in rendered.facts}
    pdfs = _files(rendered, ".pdf")
    checked = 0
    for ir in rendered.artifact_irs:
        payload = pdfs.get(ir.id)
        if payload is None:
            continue
        text = _pdf_text(payload)
        for section in ir.sections:
            if not section.body:
                continue
            for fact_id in references.referenced(section.body):
                fact = facts.get(fact_id)
                if fact is None:
                    continue
                value = references.render_value(fact)
                assert value in text, f"{ir.id}/{section.heading}: {fact_id} = {value!r} missing"
                checked += 1
    assert checked > 10, f"only checked {checked} fact references"


def test_no_fact_reference_survives_into_the_pdf(rendered: World) -> None:
    """An unsubstituted ``{{fact:...}}`` in a finished document is a broken
    document — same rule `test_docx.py` holds DOCX to."""
    for payload in _files(rendered, ".pdf").values():
        text = _pdf_text(payload)
        assert "{{fact:" not in text
        assert "[missing " not in text


def test_pdf_and_markdown_report_the_same_numbers(rendered: World) -> None:
    """Two projections of one IR cannot disagree. This is the property that
    justifies a second renderer existing at all.
    """
    from worldloom.render import markdown as markdown_renderer

    facts = {fact.id: fact for fact in rendered.facts}
    pdfs = _files(rendered, ".pdf")
    checked = 0
    for ir in rendered.artifact_irs:
        payload = pdfs.get(ir.id)
        if payload is None:
            continue
        pdf_text = _pdf_text(payload)
        md_text = markdown_renderer.render(ir, facts).decode("utf-8")
        for section in ir.sections:
            if section.table is None:
                continue
            for row in section.table.rows:
                for column in section.table.columns:
                    cell = row.cells.get(column.key)
                    if cell is None or not isinstance(cell.value, (int, float)):
                        continue
                    text = format_value(cell.value, column.number_format)
                    if text and text in md_text:
                        assert text in pdf_text, f"{ir.id}: {text!r} in Markdown but not PDF"
                        checked += 1
    assert checked > 5, f"only checked {checked} cells"


def test_a_hidden_section_is_written_but_labelled(rendered: World) -> None:
    """Hidden means not part of the readable surface, not undocumented — same
    rule `render/docx.py` follows, so an appendix present in one format cannot
    be silently absent from another."""
    pdfs = _files(rendered, ".pdf")
    ir = next(
        ir for ir in rendered.artifact_irs
        if ir.id in pdfs and any(s.hidden for s in ir.sections)
    )
    text = _pdf_text(pdfs[ir.id])
    assert "Not part of the readable surface" in text
    for section in ir.sections:
        if section.hidden:
            assert section.heading in text


def test_acronyms_survive_the_title(rendered: World) -> None:
    titles = {ir.title for ir in rendered.artifact_irs}
    pdfs = _files(rendered, ".pdf")
    for ir in rendered.artifact_irs:
        if ir.id not in pdfs:
            continue
        text = _pdf_text(pdfs[ir.id])
        assert ir.title in text


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_page_count_matches_the_footer_the_renderer_wrote(rendered: World) -> None:
    """`_NumberedCanvas` (see `render/pdf.py`) stamps every page with its own
    claim, "Page X of Y", once the true total is known. This checks that claim
    against the file's actual page count — the self-consistency check for the
    pagination this renderer is responsible for, since nothing upstream of the
    renderer knows how many pages an artifact will take.
    """
    checked = 0
    for payload in _files(rendered, ".pdf").values():
        text = _pdf_text(payload)
        matches = re.findall(r"Page (\d+) of (\d+)", text)
        assert matches, "no page-number footer found"
        totals = {int(total) for _, total in matches}
        assert len(totals) == 1, f"footer disagrees with itself about the total: {totals}"
        total = totals.pop()
        seen = sorted(int(page) for page, _ in matches)
        assert seen == list(range(1, total + 1)), seen
        assert _page_count(payload) == total
        checked += 1
    assert checked > 0


def test_a_long_table_continues_with_its_header_repeated() -> None:
    """A table that runs past the bottom margin must continue on the next
    page with its header repeated — the pagination rule `render/pdf.py`
    delegates to `Table(repeatRows=1)`. Built directly against the renderer
    rather than pulled from the corpus, since nothing in the shipped worlds
    happens to produce a table long enough to force a page break.
    """
    columns = [Column(key="value", label="Value", number_format="#,##0")]
    rows = [
        Row(key=f"row-{i}", label=f"Line item {i}", cells={"value": Cell(value=float(i))})
        for i in range(80)
    ]
    table = Table(key="long", title="Long table", columns=columns, rows=rows)
    ir = ArtifactIR(
        id="ART-LONG",
        intent_id="INT-LONG",
        title="A table long enough to paginate",
        sections=[ArtifactSection(heading="Detail", table=table)],
        metadata={},
    )
    payload = pdf_renderer.render(ir)
    assert _page_count(payload) > 1, "the table should have forced a second page"

    text = _pdf_text(payload)
    assert text.count("Long table") >= 2, "the header should repeat on the continuation page"
    assert text.count("Value") >= 2
    # Every row must still be present exactly once each — pagination must not
    # drop or duplicate content, only relocate it.
    for i in range(80):
        assert f"Line item {i}" in text


def test_a_row_that_cannot_fit_on_one_page_fails_loudly_rather_than_rendering_garbage() -> None:
    """Reportlab's own failure here is a bare `LayoutError` naming a `Flowable`
    object, not an artifact. `render/pdf.py::render` catches it and re-raises a
    `RenderError` that names the artifact — "say what you do" rather than
    silently clip content or crash uninformatively.
    """
    huge = " word" * 3000
    columns = [Column(key="value", label="Value")]
    rows = [Row(key="huge", label=huge, cells={"value": Cell(value=1.0)})]
    table = Table(key="t", title="Huge", columns=columns, rows=rows)
    ir = ArtifactIR(
        id="ART-HUGE",
        intent_id="INT-HUGE",
        title="A row that cannot fit",
        sections=[ArtifactSection(heading="Detail", table=table)],
        metadata={},
    )
    with pytest.raises(RenderError, match="ART-HUGE"):
        pdf_renderer.render(ir)


# ---------------------------------------------------------------------------
# The document plan
# ---------------------------------------------------------------------------


def test_the_plan_carries_fixed_a4_geometry() -> None:
    """A4 with the same corporate margins as `render/docx.py` — the worlds this
    renders are not American, and one artifact rendered as two fixed-page
    formats with two different page sizes would not read as one artifact.
    """
    ir = ArtifactIR(id="X", intent_id="Y", title="T", sections=[], metadata={})
    plan = pdf_renderer._plan(ir, "cfo_variance_memo", "medium")
    assert round(plan.page_width_pt / pdf_renderer._MM_TO_PT) == 210
    assert round(plan.page_height_pt / pdf_renderer._MM_TO_PT) == 297
    assert round(plan.margin_pt / pdf_renderer._MM_TO_PT) == 22


def test_the_plan_is_derived_from_the_ir_via_the_compiler(rendered: World) -> None:
    """`render/pdf.py::_plan` is not a second hand-written outline — it calls
    `compiler.compose.plan_from_ir` and `compose`, and (against every artifact
    type this repository ships) finds a clean composition: nothing dropped,
    no grammar violation. A failure here means either a shipped artifact type
    changed shape or the component registry regressed — either is real news.
    """
    for ir in rendered.artifact_irs:
        intent = rendered.artifact_intents.by_id(ir.intent_id)
        if intent.artifact_type not in pdf_renderer.HANDLES:
            continue
        plan = pdf_renderer._plan(ir, intent.artifact_type, intent.size_profile)
        assert not plan.dropped, (intent.artifact_type, plan.dropped)
        assert not plan.violations, (intent.artifact_type, plan.violations)
        assert {s.heading for s in plan.sections} == {s.heading for s in ir.sections}


# ---------------------------------------------------------------------------
# Graceful degradation
# ---------------------------------------------------------------------------


def test_a_missing_reportlab_raises_an_actionable_error(monkeypatch: pytest.MonkeyPatch) -> None:
    """Matches how `render/docx.py` behaves when python-docx is absent: an
    import failure becomes a `RenderError` naming the extra to install, not a
    bare `ModuleNotFoundError` a caller has to decode.
    """
    import builtins

    real_import = builtins.__import__

    def blocked(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "reportlab" or name.startswith("reportlab."):
            raise ImportError("simulated missing reportlab")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", blocked)
    with pytest.raises(RenderError, match="worldloom\\[pdf\\]"):
        pdf_renderer._require_reportlab()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


def test_pdf_is_a_registered_format() -> None:
    assert "pdf" in available()
