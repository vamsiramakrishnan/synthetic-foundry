"""The long report as a fixed-page PDF: outline, contents, running heads.

The same plan the Word file is rendered from, laid out natively by reportlab
(never a conversion), with what a PDF reader expects of a long report:

* a **contents page** with page numbers, built by ``multiBuild`` from the
  headings actually laid out, so a number cannot point at the wrong page;
* a **document outline** (bookmarks) of every numbered section, subsection
  and appendix;
* **running heads** naming the company, the document, its classification and
  the section the page belongs to, and a footer with the reference, version
  and ``Page X of Y``;
* **tables that span pages** with their header row repeated (the legacy
  table flowable, ``repeatRows=1``);
* a **sign-off form** in the style of a scanned approval sheet, for
  documents that are signed.

``pageCompression=0`` and ``invariant=True`` as in the legacy renderer, so
the bytes are a function of the plan alone and every figure is searchable in
the file.
"""

from __future__ import annotations

from dataclasses import replace
from io import BytesIO
from typing import TYPE_CHECKING, Any
from xml.sax.saxutils import escape

from ... import longform
from .. import Rendered, RenderError
from .. import pdf as legacy
from ..docx import HANDLES

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIR
    from . import Context

MEDIA_TYPE = legacy.MEDIA_TYPE


def _info_class(properties: dict[str, str]):  # type: ignore[no-untyped-def]
    """reportlab's document information dictionary, with *properties* added.

    Where a reader profile keeps provenance in a PDF: ``/WorldloomFacts`` and
    ``/WorldloomProvenance`` beside ``/Title`` and ``/Author``, which a
    viewer's Properties dialog lists and `artifact_text` reads, and which no
    page prints.
    """
    from reportlab.pdfbase.pdfdoc import PDFDictionary, PDFInfo, PDFString

    class _Info(PDFInfo):
        def format(self, document: Any) -> bytes:
            formatted = super().format(document)
            extra = PDFDictionary({key: PDFString(value) for key, value in sorted(properties.items())})
            inner = extra.format(document)
            # Splice the extra keys into the dictionary reportlab formatted,
            # keeping its own keys and order exactly as they were.
            return bytes(formatted.rstrip()[:-2] + inner.strip()[2:])

    return _Info


def _doc_class(properties: dict[str, str] | None = None, *, first_heading: bool = False):  # type: ignore[no-untyped-def]
    from reportlab.platypus import BaseDocTemplate

    info_class = _info_class(properties) if properties else None

    class _Report(BaseDocTemplate):
        """Bookmarks, contents entries and the current section, per heading."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            super().__init__(*args, **kwargs)
            self.section = ""
            self.total = 0
            self._seq = 0

        def beforeDocument(self) -> None:
            self.section = ""
            self._seq = 0
            self._section_page = 0
            if info_class is not None:
                current = self.canv._doc.info
                replacement = info_class()
                replacement.__dict__.update(current.__dict__)
                self.canv._doc.info = replacement

        def afterFlowable(self, flowable: Any) -> None:
            level = getattr(flowable, "_wl_level", None)
            if level is None:
                return
            text = flowable.getPlainText()
            self._seq += 1
            key = f"wl-{self._seq}"
            self.canv.bookmarkPage(key)
            self.canv.addOutlineEntry(text, key, level=level, closed=level > 0)
            if level == 0 and not (first_heading and self._section_page == self.page):
                # Where sections run on, the running head names the section
                # a page opens with, not the last one that started on it.
                self.section = text
                self._section_page = self.page
            self.notify("TOCEntry", (level, escape(text), self.page, key))

    return _Report


def _heading(text: str, level: int, styles: dict, *, keep: bool = False) -> Any:
    from reportlab.platypus import Paragraph

    paragraph = Paragraph(escape(text), styles["heading"] if level == 0 else styles["subheading"])
    paragraph._wl_level = level  # type: ignore[attr-defined]
    if keep:
        # A heading at the foot of a page with its text overleaf is the most
        # visible layout defect there is; platypus moves the pair together.
        paragraph.keepWithNext = True  # type: ignore[attr-defined]
    return paragraph


def _grid(header: list[str], rows: list[list[str]], styles: dict, width: float, g: Any,
          *, widths: list[float] | None = None) -> Any:
    from reportlab.lib import colors
    from reportlab.platypus import Paragraph, TableStyle
    from reportlab.platypus import Table as PlatypusTable

    data = [[Paragraph(escape(h), styles["cell_header"]) for h in header]]
    data.extend([Paragraph(escape(value), styles["cell"]) for value in row] for row in rows)
    widths = widths or [width / len(header)] * len(header)
    table = PlatypusTable(data, colWidths=widths, repeatRows=1)
    roles = g.colour_roles
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(f"#{roles['header_fill']}")),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#999999")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return table


def _signoff(doc: longform.LongDocument, styles: dict, width: float) -> list:
    """An approval sheet in the style of a signed and scanned form."""
    from reportlab.lib import colors
    from reportlab.platypus import Flowable, Paragraph, Spacer, TableStyle
    from reportlab.platypus import Table as PlatypusTable

    approved = next((r for r in doc.history if r.status == "Approved"), None)
    if doc.approver is None or approved is None:
        return []

    class _Stamp(Flowable):
        def __init__(self, text: str) -> None:
            super().__init__()
            self.text = text
            self.width, self.height = width, 60

        def draw(self) -> None:
            canvas = self.canv
            canvas.saveState()
            canvas.setStrokeColor(colors.HexColor("#9B2226"))
            canvas.setFillColor(colors.HexColor("#9B2226"))
            canvas.translate(width - 170, 20)
            canvas.rotate(8)
            canvas.roundRect(0, 0, 150, 34, 4, stroke=1, fill=0)
            canvas.setFont("Helvetica-Bold", 11)
            canvas.drawCentredString(75, 20, "APPROVED")
            canvas.setFont("Helvetica", 7)
            canvas.drawCentredString(75, 8, self.text)
            canvas.restoreState()

    rows = [
        ["Document reference", doc.reference],
        ["Title", doc.title],
        ["Version presented", "1.0"],
        ["Approver", f"{doc.approver.name}, {doc.approver.title}"],
        ["Decision", "[X] Approved   [ ] Approved with changes   [ ] Not approved"],
        ["Signature", f"Signed electronically by {doc.approver.name}"],
        ["Date", approved.at.strftime("%d %B %Y")],
    ]
    data = [[Paragraph(escape(a), styles["cell_bold"]), Paragraph(escape(b), styles["cell"])] for a, b in rows]
    form = PlatypusTable(data, colWidths=[width * 0.3, width * 0.7])
    form.setStyle(TableStyle([
        ("BOX", (0, 0), (-1, -1), 1.2, colors.black),
        ("INNERGRID", (0, 0), (-1, -1), 0.6, colors.black),
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F4F1EA")),
        ("TOPPADDING", (0, 0), (-1, -1), 9),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 9),
    ]))
    return [
        Paragraph("Approval and sign-off form", styles["heading"]),
        Paragraph(escape(f"Form retained with the controlled copy of {doc.reference}."), styles["note"]),
        form,
        Spacer(1, 12),
        _Stamp(approved.at.strftime("%d %b %Y")),
    ]


#: A table this short is kept whole under a designed layout: it moves to the
#: next page rather than leaving two rows behind (or ahead) on their own.
_KEEP_WHOLE_ROWS = 14


def _blocks(blocks: tuple[longform.Block, ...], styles: dict, width: float, ctx: Context, presentation: Any,
            g: Any) -> list:
    from reportlab.platypus import KeepTogether, Paragraph, Spacer

    if presentation.layout == "designed":
        out_designed: list = []
        for block in blocks:
            flowables = _blocks((block,), styles, width, ctx, replace(presentation, layout="plain"), g)
            if block.kind in ("table", "figure") and flowables:
                rows = len(block.table.rows) if block.table is not None else 0
                if block.kind == "figure" or rows <= _KEEP_WHOLE_ROWS:
                    out_designed.append(KeepTogether(flowables))
                    continue
                flowables[0].keepWithNext = True
            out_designed.extend(flowables)
        return out_designed

    out: list = []
    for block in blocks:
        if block.kind == "prose":
            if block.segments:
                text = "".join(
                    escape(old) if new is None else f"<strike>{escape(old)}</strike> <u>{escape(new)}</u>"
                    for old, new in block.segments)
            else:
                text = escape(block.text)
            out.append(Paragraph(text, styles["body"]))
        elif block.kind == "note":
            out.append(Paragraph(escape(block.text), styles["note"]))
        elif block.kind == "table" and block.table is not None:
            out.append(Paragraph(escape(f"Table {block.number}: {block.caption}"), styles["figure_title"]))
            out.append(legacy._table_flowable(block.table, width, styles, ctx.locale, presentation, g=g))
            if block.source:
                out.append(Paragraph(escape(f"Source: {block.source}"), styles["figure_note"]))
            out.append(Spacer(1, 6))
        elif block.kind == "figure" and block.chart is not None and block.table is not None:
            out.append(Paragraph(escape(f"Figure {block.number}: {block.caption}"), styles["figure_title"]))
            out.extend(legacy._figure_flowables(block.chart, block.table, width, styles, ctx.locale, g=g))
            if block.source:
                out.append(Paragraph(escape(f"Source: {block.source}"), styles["figure_note"]))
    return out


def _page_total_class():  # type: ignore[no-untyped-def]
    from reportlab.platypus.flowables import Flowable

    class _PageTotal(Flowable):
        """The ``Y`` of ``Page X of Y``, settled across multiBuild passes."""

        def __init__(self, report: Any) -> None:
            super().__init__()
            self.report = report
            self.last = 0
            self.current = 0

        def isIndexing(self) -> int:
            return 1

        def isSatisfied(self) -> bool:
            return self.current > 0 and self.last == self.current

        def notify(self, kind: str, stuff: Any) -> None:
            return None

        def beforeBuild(self) -> None:
            self.last = self.current

        def afterBuild(self) -> None:
            self.current = self.report.page

        def wrap(self, available_width: float, available_height: float) -> tuple[float, float]:
            return (0, 0)

        def draw(self) -> None:
            return None

    return _PageTotal


def _PageTotal(report: Any) -> Any:
    return _page_total_class()(report)


def _designed_cover(doc: longform.LongDocument, styles: dict, width: float, g: Any) -> list:
    """A cover a design team would sign off, as flowables under the band the
    cover page template draws: title block, summary box, distribution and
    reference, notice."""
    from reportlab.lib import colors
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, Spacer, TableStyle
    from reportlab.platypus import Table as PlatypusTable

    roles = g.colour_roles
    story: list = [
        Spacer(1, 40),
        Paragraph(escape(doc.company.upper()), styles["byline"]),
        Paragraph(escape(doc.genre), styles["subtitle"]),
        Spacer(1, 18),
        Paragraph(escape(doc.title), styles["title"]),
    ]
    if doc.subtitle:
        story.append(Paragraph(escape(doc.subtitle), styles["subtitle"]))
    story.append(Paragraph(escape(f"{doc.period} | {doc.revision.status} | Version {doc.revision.version}"),
                           styles["note"]))
    if doc.draft:
        story.append(Paragraph("DRAFT FOR REVIEW", styles["heading"]))
    story.append(Spacer(1, 16))
    abstract = _abstract(doc.abstract)
    if abstract:
        label = ParagraphStyle("wl-cover-label", parent=styles["cell_bold"], fontSize=styles["body"].fontSize,
                               leading=styles["body"].leading)
        box = PlatypusTable([[Paragraph("Summary", label)], [Paragraph(escape(abstract), styles["body"])]],
                            colWidths=[width])
        box.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#F3F4F6")),
            ("LINEBEFORE", (0, 0), (0, -1), 3, colors.HexColor(f"#{roles['accent']}")),
            ("LEFTPADDING", (0, 0), (-1, -1), 12), ("RIGHTPADDING", (0, 0), (-1, -1), 12),
            ("TOPPADDING", (0, 0), (-1, -1), 8), ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
        ]))
        story.extend([box, Spacer(1, 18)])
    contents = [part for part in doc.parts][:9]
    if contents:
        rows = [[Paragraph(escape(part.number), styles["cell_bold"]), Paragraph(escape(part.heading), styles["cell"])]
                for part in contents]
        if doc.appendices:
            rows.append([Paragraph("", styles["cell"]), Paragraph(escape(
                f"Appendices: {', '.join(part.heading for part in doc.appendices[:6])}"), styles["cell"])])
        listing = PlatypusTable([[Paragraph("In this paper", styles["cell_bold"]), ""], *rows],
                                colWidths=[width * 0.08, width * 0.92])
        listing.setStyle(TableStyle([
            ("SPAN", (0, 0), (-1, 0)), ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0), ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ]))
        story.extend([listing, Spacer(1, 16)])
    left = [Paragraph("Distribution", styles["cell_bold"])] + [
        Paragraph(escape(line), styles["cell"]) for line in _distribution(doc)]
    right = [Paragraph("Document", styles["cell_bold"])] + [
        Paragraph(f"<b>{escape(k)}</b>  {escape(v)}", styles["cell"]) for k, v in _reference(doc)]
    block = PlatypusTable([[left, right]], colWidths=[width * 0.45, width * 0.55])
    block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LINEABOVE", (0, 0), (-1, 0), 0.75, colors.HexColor(f"#{roles['accent']}")),
        ("TOPPADDING", (0, 0), (-1, -1), 8), ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.extend([block, Spacer(1, 18)])
    story.append(Paragraph(escape(doc.metadata.get("note", "Synthetic corpus generated by Worldloom. Not a real company.")),
                           styles["notice"]))
    return story


def _abstract(text: str, words: int = 90) -> str:
    """The opening paragraph for a summary box, cut at a sentence once long."""
    if len(text.split()) <= words:
        return text
    kept: list[str] = []
    for sentence in longform.sentences(text):
        if kept and len(" ".join(kept + [sentence]).split()) > words:
            break
        kept.append(sentence)
    return " ".join(kept)


def _distribution(doc: longform.LongDocument) -> list[str]:
    """Who the document goes to: its audience, its approver and reviewers."""
    lines = [doc.audience]
    if doc.approver is not None:
        lines.append(f"{doc.approver.name}, {doc.approver.title} (approver)")
    lines.extend(f"{p.name}, {p.title} (reviewer)" for p in doc.reviewers)
    if doc.family is not None:
        lines.append(f"Filed with the {doc.family.title}")
    return lines


def _reference(doc: longform.LongDocument) -> list[tuple[str, str]]:
    rows = [("Reference", doc.reference), ("Date", doc.revision.at.strftime("%d %B %Y")),
            ("Prepared by", f"{doc.author.name}, {doc.author.title}".strip(", "))]
    if doc.approver is not None:
        rows.append(("Approved by", f"{doc.approver.name}, {doc.approver.title}"))
    rows.append(("Classification", doc.classification))
    return rows


def provenance_properties(doc: longform.LongDocument, profile: str) -> dict[str, str]:
    """The provenance a reader profile writes into a file instead of its pages."""
    return {
        "WorldloomReference": doc.reference,
        "WorldloomProfile": profile,
        "WorldloomFacts": " ".join(doc.fact_ids),
        "WorldloomProvenance": "; ".join(f"{part}: {' '.join(ids)}" for part, ids in doc.provenance.items()),
    }


def render_document(doc: longform.LongDocument, ctx: Context, ir: ArtifactIR) -> bytes:
    legacy._require_reportlab()
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import (
        Frame,
        KeepTogether,
        NextPageTemplate,
        PageBreak,
        PageTemplate,
        Paragraph,
        Spacer,
    )
    from reportlab.platypus.doctemplate import LayoutError
    from reportlab.platypus.tableofcontents import TableOfContents

    from .. import fonts

    g = legacy._genome_for(ir)
    faces = fonts.named(g.typeface)
    styles = dict(legacy._styles(g))
    styles["subheading"] = ParagraphStyle(
        "wl-subheading", parent=styles["heading"], fontSize=styles["heading"].fontSize * 0.8,
        leading=styles["heading"].leading * 0.8)
    presentation = ctx.presentation(doc.artifact_type)
    designed = presentation.layout == "designed"
    if designed:
        # Widow and orphan control on body text: a paragraph never leaves one
        # line behind at the foot of a page or carries one alone to the next.
        styles["body"] = ParagraphStyle("wl-body-designed", parent=styles["body"], allowWidows=0, allowOrphans=0)
    page_w, page_h, margin = legacy._PAGE_WIDTH_PT, legacy._PAGE_HEIGHT_PT, legacy._MARGIN_PT
    frame_w = page_w - 2 * margin
    # A hair inside the frame: a table sized to exactly the frame width
    # overflows it by a float's last digit and platypus refuses it.
    width = frame_w - 2

    def make_story() -> tuple[list, Any]:
        """Fresh flowables per pass: platypus splits a table in place, so a
        story laid out once cannot be laid out again."""
        story: list
        if designed:
            story = _designed_cover(doc, styles, width, g)
        else:
            story = [
                Paragraph(escape(doc.company.upper()), styles["byline"]),
                Paragraph(escape(doc.genre), styles["subtitle"]),
                Spacer(1, 90),
                Paragraph(escape(doc.title), styles["title"]),
            ]
            if doc.subtitle:
                story.append(Paragraph(escape(doc.subtitle), styles["subtitle"]))
            if doc.draft:
                story.append(Paragraph("DRAFT FOR REVIEW", styles["heading"]))
            story.append(Spacer(1, 60))
            cover_rows = [["Reference", doc.reference], ["Version", f"{doc.revision.version} ({doc.revision.status})"],
                          ["Date", doc.revision.at.strftime("%d %B %Y")], ["Classification", doc.classification],
                          ["Prepared by", f"{doc.author.name}, {doc.author.title}".strip(", ")]]
            if doc.approver is not None:
                cover_rows.append(["Approved by", f"{doc.approver.name}, {doc.approver.title}"])
            story.append(_grid(["Document", ""], cover_rows, styles, width, g, widths=[width * 0.3, width * 0.7]))
            story.append(Spacer(1, 18))
            story.append(Paragraph(escape(doc.metadata.get("note", "Synthetic corpus generated by Worldloom. Not a real company.")),
                                   styles["notice"]))
        story.append(NextPageTemplate("body"))
        story.append(PageBreak())

        def control(heading: str, flowable: Any, *, level: int = 1) -> None:
            title = Paragraph(heading, styles["heading"] if level == 0 else styles["subheading"])
            if designed:
                # The control tables are short: kept whole, a review record
                # moves to the next page entire instead of spilling two rows.
                story.append(KeepTogether([title, flowable]))
            else:
                story.extend([title, flowable])

        if designed:
            # Two field/value pairs a row: the control record is a reference
            # block, and at half the height it shares its page with the
            # history, the approvals and the review record.
            pairs = [list(r) for r in longform.control_rows(doc)]
            rows = [pairs[i] + (pairs[i + 1] if i + 1 < len(pairs) else ["", ""]) for i in range(0, len(pairs), 2)]
            control("Document control", _grid(["Field", "Value", "Field", "Value"], rows, styles, width, g,
                                              widths=[width * 0.17, width * 0.33, width * 0.17, width * 0.33]), level=0)
        else:
            control("Document control", _grid(["Field", "Value"], [list(r) for r in longform.control_rows(doc)],
                                              styles, width, g, widths=[width * 0.3, width * 0.7]), level=0)
        control("Revision history", _grid(["Version", "Date", "Author", "Status", "Description of change"],
                                          [list(r) for r in longform.history_rows(doc)], styles, width, g,
                                          widths=[width * 0.11, width * 0.16, width * 0.18, width * 0.12, width * 0.43]))
        control("Approvals", _grid(["Role", "Name", "Title", "Decision", "Date"],
                                   [list(r) for r in longform.approval_rows(doc)], styles, width, g))
        if doc.comments:
            control("Review record", _grid(["Section", "Reviewer", "Comment", "Resolution"],
                                           [[c.part, c.author.name, c.text, c.resolution] for c in doc.comments],
                                           styles, width, g,
                                           widths=[width * 0.1, width * 0.2, width * 0.45, width * 0.25]))
        signoff = _signoff(doc, styles, width)
        if signoff and designed:
            # The sign-off form follows the review record on the same page
            # when it fits, rather than leaving the record alone on one.
            story.append(Spacer(1, 12))
            story.append(KeepTogether(signoff))
        elif signoff:
            story.append(PageBreak())
            story.extend(signoff)
        toc: Any = None
        if doc.long:
            story.append(PageBreak())
            story.append(Paragraph("Contents", styles["heading"]))
            toc = TableOfContents()
            toc.levelStyles = [
                ParagraphStyle("wl-toc0", parent=styles["body"], leftIndent=0, firstLineIndent=0),
                ParagraphStyle("wl-toc1", parent=styles["body"], leftIndent=14, firstLineIndent=0),
            ]
            story.append(toc)
        for position, part in enumerate(doc.all_parts()):
            # A designed report runs its argument on from section to section
            # and turns the page once, into its appendices; a plain one opens every
            # chapter on a page of its own.
            if designed:
                turn = position == 0 or (part.appendix and part is doc.appendices[0])
            else:
                turn = doc.long or position == 0 or (part.appendix and part is doc.appendices[0])
            if turn:
                story.append(PageBreak())
            story.append(_heading(part.label, 0, styles, keep=designed))
            story.extend(_blocks(part.blocks, styles, width, ctx, presentation, g))
            for child in part.children:
                story.append(_heading(f"{child.number} {child.heading}", 1, styles, keep=designed))
                story.extend(_blocks(child.blocks, styles, width, ctx, presentation, g))

        return story, toc

    header = f"{'DRAFT | ' if doc.draft else ''}{doc.company} | {doc.title} | {doc.classification}"
    footer = f"{doc.reference} | Version {doc.revision.version} | {doc.revision.status}"
    properties = (provenance_properties(doc, presentation.name)
                  if presentation.citations == "appendix" else None)
    report_cls = _doc_class(properties, first_heading=designed)

    buffer = BytesIO()
    report = report_cls(
        buffer, pagesize=(page_w, page_h), leftMargin=margin, rightMargin=margin,
        topMargin=margin, bottomMargin=margin, title=doc.title, author=doc.author.name,
        subject=doc.genre, creator="Worldloom", keywords=list(doc.labels),
        invariant=True, pageCompression=0,
    )
    total = _PageTotal(report)
    frame = Frame(margin, margin, frame_w, page_h - 2 * margin, id="body", leftPadding=0, rightPadding=0)

    def running(canvas: Any, template: Any) -> None:
        from reportlab.lib.colors import HexColor

        canvas.saveState()
        canvas.setFont(faces.pdf_body, 7.5)
        canvas.setFillColor(HexColor(f"#{legacy._MUTED}"))
        canvas.drawString(margin, page_h - margin + 10, header)
        if template.section:
            canvas.drawRightString(page_w - margin, page_h - margin + 10, template.section[:60])
        page = canvas.getPageNumber()
        tail = f"Page {page} of {total.last}" if total.last else f"Page {page}"
        canvas.drawString(margin, margin - 14, footer)
        canvas.drawRightString(page_w - margin, margin - 14, tail)
        canvas.restoreState()

    def band(canvas: Any, template: Any) -> None:
        """The designed cover's classification band and foot rule."""
        from reportlab.lib.colors import HexColor

        roles = g.colour_roles
        canvas.saveState()
        canvas.setFillColor(HexColor(f"#{roles['header_fill']}"))
        canvas.rect(0, page_h - 34, page_w, 34, stroke=0, fill=1)
        canvas.setFillColor(HexColor(f"#{roles['header_text']}"))
        canvas.setFont(f"{faces.pdf_body}-Bold", 9)
        canvas.drawString(margin, page_h - 22, doc.classification.upper())
        canvas.drawRightString(page_w - margin, page_h - 22, doc.reference)
        canvas.setStrokeColor(HexColor(f"#{roles['accent']}"))
        canvas.setLineWidth(2)
        canvas.line(margin, margin - 6, page_w - margin, margin - 6)
        canvas.restoreState()

    report.addPageTemplates([
        PageTemplate(id="cover", frames=[Frame(margin, margin, frame_w, page_h - 2 * margin, id="cover",
                                               leftPadding=0, rightPadding=0)],
                     **({"onPage": band} if designed else {})),
        PageTemplate(id="body", frames=[frame], onPageEnd=running),
    ])
    story, _toc = make_story()
    try:
        # One multiBuild settles the contents page and the page total
        # together: `_PageTotal` is an indexing flowable that is satisfied
        # only once a pass laid out as many pages as the pass before it.
        report.multiBuild([total, *story], maxPasses=8)
    except LayoutError as exc:
        raise RenderError(f"{ir.id}: a table row does not fit on a page ({exc})") from exc
    payload = buffer.getvalue()
    return legacy._normalise(payload)


def render_all(ctx: Context) -> list[Rendered]:
    out: list[Rendered] = []
    for ir in ctx.world.artifact_irs:
        if ctx.intent(ir).artifact_type not in HANDLES:
            continue
        out.append(Rendered(artifact_id=ir.id, path=ctx.path(ir, "pdf"), media_type=MEDIA_TYPE,
                            payload=render_document(ctx.doc(ir), ctx, ir)))
    return out
