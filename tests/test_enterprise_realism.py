"""The enterprise/v1 realism profile: documents the size companies keep them.

Pins the contract of `realism_profiles`, `longform` and `render.enterprise`:
a default build meets real-document minimums (a board paper of fifteen or
more pages, a deck of twenty or more slides each with speaker notes, a long
PDF with an outline, intranet pages, wiki exports, revision and pack files);
every figure in the long form is a fact or an IR cell; the output is
deterministic; connector file records carry their text; and ``legacy``
reproduces the old bytes exactly.
"""
from __future__ import annotations

import hashlib
import re
import zipfile
from io import BytesIO

import pytest

from worldloom import longform, realism_profiles, sdk
from worldloom.artifact_text import extract
from worldloom.connector_data import generate_artifact_projection
from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.narrative import DeterministicProvider, references
from worldloom.presentation import AUDIT
from worldloom.render import enterprise
from worldloom.render.values import corpus_locale
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose

FORMATS = ("xlsx", "docx", "pdf", "pptx", "markdown", "html")


@pytest.fixture(scope="module")
def narrated():  # type: ignore[no-untyped-def]
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    ).narrate(DeterministicProvider())


@pytest.fixture(scope="module")
def rendered(narrated):  # type: ignore[no-untyped-def]
    world = narrated.extend(recipe=realism_profiles.with_realism(narrated.recipe, "enterprise"))
    return world.render(*FORMATS)


def _files(world) -> dict[str, bytes]:  # type: ignore[no-untyped-def]
    return {item.path: bytes(item.payload) for item in world._rendered}


def _by_type(world, artifact_type: str, ext: str) -> tuple[str, bytes]:  # type: ignore[no-untyped-def]
    for ir in world.artifact_irs:
        if world.artifact_intents.by_id(ir.intent_id).artifact_type != artifact_type:
            continue
        for item in world._rendered:
            if item.artifact_id == ir.id and item.path.endswith(f".{ext}") and "/revisions/" not in item.path:
                return item.path, bytes(item.payload)
    raise AssertionError(f"no {ext} for {artifact_type}")


# -- the profile seam ---------------------------------------------------------


def test_absent_key_is_legacy_and_legacy_writes_nothing() -> None:
    assert realism_profiles.of({}) == realism_profiles.LEGACY
    recipe = {"seed": 1, "artifact_realism": "enterprise/v1"}
    assert realism_profiles.with_realism(recipe, "legacy") == {"seed": 1}
    assert realism_profiles.with_realism({"seed": 1}, "enterprise")["artifact_realism"] == "enterprise/v1"
    with pytest.raises(ValueError):
        realism_profiles.named("glossy")


def test_new_sdk_builds_default_to_enterprise_and_legacy_is_a_keyword() -> None:
    assert sdk.retail().build().world.recipe["artifact_realism"] == realism_profiles.DEFAULT_FOR_NEW_BUILDS
    assert "artifact_realism" not in sdk.retail().realism("legacy").build().world.recipe


def test_legacy_reproduces_the_bytes_of_a_recipe_that_names_no_profile(narrated) -> None:  # type: ignore[no-untyped-def]
    before = narrated.render(*FORMATS)
    legacy = narrated.extend(recipe=realism_profiles.with_realism(
        {**narrated.recipe, "artifact_realism": "enterprise/v1"}, "legacy")).render(*FORMATS)
    assert legacy.recipe == narrated.recipe
    assert _files(legacy) == _files(before)
    assert not any("/revisions/" in path or "/families/" in path for path in _files(legacy))


def test_the_ir_and_the_validation_do_not_move_with_the_profile(narrated, rendered) -> None:  # type: ignore[no-untyped-def]
    legacy = narrated.render(*FORMATS)
    assert [ir.model_dump() for ir in legacy.artifact_irs] == [ir.model_dump() for ir in rendered.artifact_irs]
    assert rendered.validate().ok


# -- sizes a default build meets ----------------------------------------------


def test_a_board_paper_runs_to_fifteen_pages_or_more(rendered) -> None:  # type: ignore[no-untyped-def]
    path, payload = _by_type(rendered, "executive_summary", "docx")
    read = extract(path, payload)
    assert read is not None and read.pages >= 15, read.pages if read else None
    text = read.text
    for furniture in ("Document control", "Revision history", "Approvals", "Contents",
                      "Executive summary", "Appendix A"):
        assert furniture in text
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        footer = "".join(archive.read(n).decode() for n in archive.namelist() if n.startswith("word/footer"))
    assert "PAGE" in footer and "NUMPAGES" in footer


def test_the_variance_paper_pdf_is_long_with_an_outline_and_page_totals(rendered) -> None:  # type: ignore[no-untyped-def]
    path, payload = _by_type(rendered, "cfo_variance_memo", "pdf")
    read = extract(path, payload)
    assert read is not None and read.pages >= 20
    assert read.extra["outline"] is True
    assert f"Page {read.pages} of {read.pages}" in read.units[-1].text


def test_a_deck_has_twenty_slides_or_more_on_real_layouts_with_notes(rendered) -> None:  # type: ignore[no-untyped-def]
    path, payload = _by_type(rendered, "executive_summary", "pptx")
    read = extract(path, payload)
    assert read is not None
    assert read.extra["slides"] >= 20
    assert read.notes == read.extra["slides"], "every slide carries speaker notes"
    assert read.extra["charts"] >= 1
    with zipfile.ZipFile(BytesIO(payload)) as archive:
        layouts = set()
        for name in archive.namelist():
            if re.fullmatch(r"ppt/slides/_rels/slide\d+\.xml\.rels", name):
                layouts.update(re.findall(r"slideLayouts/(slideLayout\d+)\.xml", archive.read(name).decode()))
        slide = archive.read("ppt/slides/slide3.xml").decode()
    assert len(layouts) >= 4, layouts
    assert 'type="sldNum"' in slide and 'type="ftr"' in slide


def test_pages_and_exports_look_like_their_products(rendered) -> None:  # type: ignore[no-untyped-def]
    _path, page = _by_type(rendered, "cfo_variance_memo", "html")
    html = page.decode()
    for marker in ('class="breadcrumbs"', 'class="site-nav"', 'class="page-meta"', "Attachments",
                   "Page history", 'class="comments"'):
        assert marker in html
    _path, md = _by_type(rendered, "incident_rca", "md")
    text = md.decode()
    assert text.startswith("---\n") and "template: postmortem" in text
    assert "```yaml" in text and "## Related pages" in text


def test_revisions_and_packs_are_separate_files(rendered) -> None:  # type: ignore[no-untyped-def]
    files = _files(rendered)
    revisions = [p for p in files if p.startswith("artifacts/revisions/")]
    assert any(p.endswith("-v0.1.docx") for p in revisions)
    assert any(p.endswith("-v0.2.docx") for p in revisions)
    assert any(p.startswith("artifacts/families/") and p.endswith("index.md") for p in files)
    reviewed = next(p for p in revisions if "cfo-variance-memo-v0.2" in p)
    read = extract(reviewed, files[reviewed])
    assert read is not None and read.comments > 0


def test_an_amendment_tracks_the_fact_that_superseded_a_cited_one(rendered) -> None:  # type: ignore[no-untyped-def]
    amended = [p for p in _files(rendered) if re.search(r"-v1\.\d+\.docx$", p)]
    assert amended, "the incident world supersedes cited facts after approval"
    with zipfile.ZipFile(BytesIO(_files(rendered)[amended[0]])) as archive:
        body = archive.read("word/document.xml").decode()
    assert "<w:ins " in body and "<w:del " in body


# -- every figure is a fact or a cell ------------------------------------------


def test_every_figure_in_the_long_form_is_a_fact_or_an_ir_cell(rendered) -> None:  # type: ignore[no-untyped-def]
    facts = {fact.id: fact for fact in rendered.facts}
    locale = corpus_locale(rendered)
    cells = {(cell.fact_id, cell.value) for ir in rendered.artifact_irs for table in ir.tables()
             for row in table.rows for cell in row.cells.values()}
    ctx = enterprise.context(rendered, FORMATS)
    for ir in rendered.artifact_irs:
        for revision in ctx.history(ir):
            doc = ctx.doc(ir, revision)
            for block in doc.tables():
                assert block.table is not None
                for row in block.table.rows:
                    for cell in row.cells.values():
                        if isinstance(cell.value, (int, float)):
                            assert (cell.fact_id, cell.value) in cells, (ir.id, revision.version, row.key)
                        elif cell.fact_id:
                            fact = facts[cell.fact_id]
                            spelled = references.render_value(fact, locale=locale, presentation=AUDIT)
                            assert cell.value in {spelled, references.describe(fact)} or (
                                cell.fact_id, cell.value) in cells, (ir.id, cell.value)
            for part in doc.all_parts():
                for node in (part, *part.children):
                    for block in node.blocks:
                        if block.kind == "prose":
                            assert "{{fact:" not in block.text and "[missing" not in block.text


def test_a_draft_states_only_what_was_true_at_its_date(rendered) -> None:  # type: ignore[no-untyped-def]
    facts = {fact.id: fact for fact in rendered.facts}
    ctx = enterprise.context(rendered, FORMATS)
    for ir in rendered.artifact_irs:
        for revision in ctx.history(ir):
            if revision.as_of is None or revision.amendment:
                continue
            doc = ctx.doc(ir, revision)
            for block in doc.tables():
                for row in block.table.rows:  # type: ignore[union-attr]
                    for cell in row.cells.values():
                        if cell.fact_id in facts and not isinstance(cell.value, (int, float)):
                            assert facts[cell.fact_id].valid_from <= revision.as_of


def test_history_is_chronological_and_signed_by_people_of_the_world(rendered) -> None:  # type: ignore[no-untyped-def]
    people = {person.id for person in rendered.people}
    for ir in rendered.artifact_irs:
        history = longform.revisions(rendered, ir)
        assert [r.at for r in history] == sorted(r.at for r in history)
        assert all(r.by.id in people for r in history)
        assert sum(1 for r in history if r.as_of is None) == 1


# -- determinism and connectors ------------------------------------------------


def test_enterprise_rendering_is_byte_deterministic(narrated, rendered) -> None:  # type: ignore[no-untyped-def]
    again = narrated.extend(recipe=realism_profiles.with_realism(narrated.recipe, "enterprise")).render(*FORMATS)
    first, second = _files(rendered), _files(again)
    assert first.keys() == second.keys()
    differing = [p for p in first if hashlib.sha256(first[p]).digest() != hashlib.sha256(second[p]).digest()]
    assert not differing, differing


def test_get_file_returns_the_documents_text_and_structure(narrated, rendered) -> None:  # type: ignore[no-untyped-def]
    records = generate_artifact_projection(rendered, "sharepoint")
    emulator = ConnectorEmulator(load_connector_definition("sharepoint"), records)
    decks = [r for r in records if r.entity == "pptx"]
    papers = [r for r in records if r.entity == "docx"]
    assert decks and papers
    fetched = emulator.call("get_file", id=papers[0].external_id)
    assert "Document control" in fetched["content"]
    assert decks[0].fields["structure"]["unit_kind"] == "slide"
    assert any(len(r.fields.get("version_history", ())) > 1 for r in papers)

    legacy_records = generate_artifact_projection(narrated.render("docx", "pptx"), "sharepoint")
    assert all("content" not in r.fields and "structure" not in r.fields for r in legacy_records)
