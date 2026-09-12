"""Chapter furniture for documents long enough to need it, and none for a memo.

Past `render.CHAPTERED_FROM` visible sections, Word and PDF open every section
on its own page, Word's running head names the current section, the hidden
sections gather under one "Appendix" heading, and the Markdown twin opens
with a linked contents list. Below the threshold every document renders as it
always did — the property every byte-identity gate in this repository rests
on, pinned here directly on the renderers rather than only through a corpus.
"""

from __future__ import annotations

import io
import re

import docx as python_docx

from worldloom.models import ArtifactIR, ArtifactSection
from worldloom.render import CHAPTERED_FROM, chaptered
from worldloom.render import docx as docx_render
from worldloom.render import markdown as markdown_render
from worldloom.render import pdf as pdf_render

_BODY = "The position held through the period, and the movement is explained here."


def _ir(visible: int, *, hidden: int = 1) -> ArtifactIR:
    sections = [
        ArtifactSection(heading=f"Chapter {chr(ord('A') + i)}", body=_BODY, purpose="argue",
                        semantic_role="summary")
        for i in range(visible)
    ]
    sections += [
        ArtifactSection(heading=f"Supporting note {chr(ord('A') + i)}", body=_BODY, purpose="cite",
                        hidden=True, semantic_role="summary")
        for i in range(hidden)
    ]
    return ArtifactIR(
        id="ART-7001", intent_id="ART-7001", title="Group Review", subtitle="A long document",
        metadata={"company": "Test Co", "worldloom_seed": "8128"}, sections=sections,
    )


def _document_xml(payload: bytes) -> str:
    return python_docx.Document(io.BytesIO(payload)).element.xml


def _header_xml(payload: bytes) -> str:
    return python_docx.Document(io.BytesIO(payload)).sections[0].header._element.xml


def test_the_threshold_is_the_one_the_writers_are_framed_at() -> None:
    from worldloom.narrative import compiler as narrative_compiler

    assert CHAPTERED_FROM == narrative_compiler.FRAMED_FROM == 8
    assert not chaptered(_ir(CHAPTERED_FROM))
    assert chaptered(_ir(CHAPTERED_FROM + 1))


def test_a_workbook_of_many_sheets_is_not_a_chaptered_report() -> None:
    """The month-end model's Markdown twin runs to nine sheets and is a
    workbook; the byte-identity gate caught chapters being put on it."""
    from worldloom.models import Column, Row, Table

    def sheet(i: int) -> ArtifactSection:
        table = Table(key=f"t{i}", title=f"Sheet {i}", columns=[Column(key="v", label="V")],
                      rows=[Row(key="r", label="R", cells={})])
        return ArtifactSection(heading=f"Sheet {chr(ord('A') + i)}", table=table, purpose="show")

    workbook = ArtifactIR(id="ART-7002", intent_id="ART-7002", title="Model", sections=[sheet(i) for i in range(12)])
    assert not chaptered(workbook)
    assert "## Contents" not in markdown_render.render(workbook, {}).decode("utf-8")


def test_a_memo_renders_with_no_chapter_furniture() -> None:
    ir = _ir(3)
    xml = _document_xml(docx_render.render(ir, {}))
    assert "w:type=\"page\"" not in xml, "a three-section memo has no page breaks"
    assert " STYLEREF " not in _header_xml(docx_render.render(ir, {}))
    assert "Appendix" not in xml

    text = markdown_render.render(ir, {}).decode("utf-8")
    assert "## Contents" not in text and "## Appendix" not in text


def test_a_long_document_opens_each_chapter_on_its_own_page_in_word() -> None:
    ir = _ir(10, hidden=2)
    payload = docx_render.render(ir, {})
    xml = _document_xml(payload)
    # Nine breaks between ten chapters, one before the appendix, and the one
    # the contents page already ended in.
    assert xml.count("w:type=\"page\"") == 9 + 1 + 1
    assert xml.count(">Appendix<") == 1, "one heading over the hidden run, not one per section"
    assert " TOC " in xml
    assert ' STYLEREF "Heading 1" ' in _header_xml(payload)


def test_a_long_document_paginates_by_chapter_in_pdf() -> None:
    from tests.test_pdf import _page_count, _pdf_text

    ir = _ir(10, hidden=2)
    payload = pdf_render.render(ir, {}, artifact_type="group_review", size_class="xlong")
    # Ten chapters on their own pages, an appendix page, and the front matter
    # shares the first chapter's page.
    assert _page_count(payload) >= 10 + 1
    text = _pdf_text(payload)
    assert "Appendix" in text and text.count("Appendix") == 1

    short = pdf_render.render(_ir(3), {}, artifact_type="group_review", size_class="medium")
    assert _page_count(short) == 1


def test_a_long_document_opens_with_a_linked_contents_list_in_markdown() -> None:
    ir = _ir(9, hidden=1)
    text = markdown_render.render(ir, {}).decode("utf-8")
    contents = text.split("## Chapter A")[0]
    assert "## Contents" in contents
    for section in ir.sections:
        if not section.hidden:
            assert f"- [{section.heading}](#{markdown_render._anchor(section.heading)})" in contents
        else:
            assert section.heading not in contents
    assert markdown_render._anchor("By trading division") == "by-trading-division"
    assert markdown_render._anchor("Q3: what moved, and why?") == "q3-what-moved-and-why"
    assert re.search(r"## Appendix\n+## Supporting note A", text)
