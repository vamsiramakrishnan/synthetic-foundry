"""The deck a committee is actually shown.

The legacy deck is seven slides drawn on the blank layout. A results deck in a
company is built on the template's own layouts (title, section header, title
and content, two content, comparison, title only for a chart or a table),
carries the footer, date and slide number from the master on every slide,
has an agenda and an appendix, and has speaker notes on every slide because
somebody has to present it. It is also not a projection of one memo: it is
assembled from the pack. The executive summary's own prose opens it; the
workbook it rests on supplies the schedules and native charts; the variance
paper supplies the commentary and the decision; the post-incident review
supplies the operational section; the ledger supplies the key figures.

Every value on every slide is either a cell of the IR table it came from
(spelled by `values.format_value`) or a fact spelled by
`narrative.references.render_value`, and every speaker note names where the
slide's content came from. A chart is a native chart over a table the deck
also shows.
"""

from __future__ import annotations

import copy
from io import BytesIO
from typing import TYPE_CHECKING, Any

from ... import longform
from .. import Rendered, ooxml
from .. import pptx as legacy
from ..values import format_value

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIR, Table
    from . import Context

MEDIA_TYPE = legacy.MEDIA_TYPE

#: Slide geometry: 16:9, the template's 4:3 layouts scaled across.
_WIDTH_IN, _HEIGHT_IN = 13.333, 7.5
_TABLE_ROWS = 11
_BULLETS = 5
_MAX_SLIDES = 60

_LAYOUT_TITLE, _LAYOUT_CONTENT, _LAYOUT_SECTION, _LAYOUT_TWO, _LAYOUT_COMPARISON, _LAYOUT_TITLE_ONLY = 0, 1, 2, 3, 4, 5


def _emu(inches: float) -> int:
    return round(inches * 914_400)


class _Deck:
    def __init__(self, ctx: Context, ir: ArtifactIR, doc: longform.LongDocument) -> None:
        pptx_pkg = legacy._require_pptx()
        self.ctx = ctx
        self.ir = ir
        self.doc = doc
        self.g = legacy._genome_for(ir)
        self.prs = pptx_pkg.Presentation()
        scale = _emu(_WIDTH_IN) / self.prs.slide_width
        self.prs.slide_width = _emu(_WIDTH_IN)
        self.prs.slide_height = _emu(_HEIGHT_IN)
        for owner in (self.prs.slide_master, *self.prs.slide_layouts):
            for shape in owner.shapes:
                if shape.left is not None and shape.width is not None:
                    shape.left, shape.width = int(shape.left * scale), int(shape.width * scale)
        self.date = doc.revision.at.strftime("%d %B %Y")
        self.footer = f"{doc.company} | {doc.classification}"
        self.cap = _MAX_SLIDES
        """The most slides this deck may run to: the renderer's hard stop, or
        the presentation profile's budget (`Presentation.slide_cap`)."""
        self.title_slide_notes: list[str] | None = None

    # -- furniture --------------------------------------------------------

    def _furniture(self, slide: Any) -> None:
        """Date, footer and slide number, cloned from the layout the way
        PowerPoint's Insert > Header & Footer does."""
        from pptx.enum.shapes import PP_PLACEHOLDER

        number = len(self.prs.slides)
        for placeholder in slide.slide_layout.placeholders:
            kind = placeholder.placeholder_format.type
            if kind not in (PP_PLACEHOLDER.DATE, PP_PLACEHOLDER.FOOTER, PP_PLACEHOLDER.SLIDE_NUMBER):
                continue
            element = copy.deepcopy(placeholder._element)
            slide.shapes._spTree.append(element)
            texts = list(element.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}t"))
            value = {PP_PLACEHOLDER.DATE: self.date, PP_PLACEHOLDER.FOOTER: self.footer}.get(kind, str(number))
            if texts:
                texts[0].text = value
                for extra in texts[1:]:
                    extra.text = ""

    def _notes(self, slide: Any, lines: list[str]) -> None:
        text = "\n".join(line for line in lines if line)
        slide.notes_slide.notes_text_frame.text = text

    def room(self) -> int:
        """Slides left in the budget."""
        return self.cap - len(self.prs.slides)

    def slide(self, layout: int, title: str, notes: list[str]) -> Any | None:
        return self._slide(layout, title, notes)

    def _slide(self, layout: int, title: str, notes: list[str]) -> Any | None:
        if len(self.prs.slides) >= min(self.cap, _MAX_SLIDES):
            return None
        slide = self.prs.slides.add_slide(self.prs.slide_layouts[layout])
        if slide.shapes.title is not None:
            slide.shapes.title.text = title
        self._furniture(slide)
        self._notes(slide, notes)
        return slide

    def _body_placeholder(self, slide: Any, idx: int = 1) -> Any:
        for placeholder in slide.placeholders:
            if placeholder.placeholder_format.idx == idx:
                return placeholder
        return None

    def _bullets(self, frame: Any, lines: list[str], size: int = 18) -> None:
        from pptx.util import Pt

        frame.clear()
        for index, line in enumerate(lines):
            paragraph = frame.paragraphs[0] if index == 0 else frame.add_paragraph()
            paragraph.text = line
            for run in paragraph.runs:
                run.font.size = Pt(size)

    # -- slide kinds ------------------------------------------------------

    def title(self) -> None:
        doc = self.doc
        slide = self._slide(_LAYOUT_TITLE, doc.title, self.title_slide_notes if self.title_slide_notes is not None else [
            f"Presented by {doc.author.name}, {doc.author.title}.",
            f"Pack: {doc.family.title}." if doc.family else "",
            f"Reference {doc.reference}, version {doc.revision.version} ({doc.revision.status}), {self.date}.",
        ])
        if slide is not None:
            subtitle = self._body_placeholder(slide)
            if subtitle is not None:
                subtitle.text = f"{doc.company} | {doc.genre} | {doc.period}\n{doc.author.name}, {doc.author.title}"

    def agenda(self, sections: list[str]) -> None:
        slide = self._slide(_LAYOUT_CONTENT, "Agenda", [
            "The deck follows the pack: the ask first, then the results, the commentary, operations and the"
            " decisions, with detailed schedules in the appendix."])
        if slide is not None:
            self._bullets(self._body_placeholder(slide).text_frame, sections, 20)

    def section(self, number: str, heading: str, source: str) -> None:
        slide = self._slide(_LAYOUT_SECTION, f"{number} {heading}".strip(), [f"This section draws on {source}."])
        if slide is not None:
            body = self._body_placeholder(slide)
            if body is not None:
                body.text = source

    def prose(self, heading: str, paragraphs: list[str], source: str) -> None:
        sentences = [s for paragraph in paragraphs for s in longform.sentences(paragraph)]
        if not sentences:
            return
        chunks = [sentences[i:i + _BULLETS] for i in range(0, len(sentences), _BULLETS)]
        for index, chunk in enumerate(chunks):
            title = heading if index == 0 else f"{heading} (continued)"
            slide = self._slide(_LAYOUT_CONTENT, title, [" ".join(chunk), f"Source: {source}."])
            if slide is None:
                return
            self._bullets(self._body_placeholder(slide).text_frame, chunk, 16 if len(chunk) > 3 else 18)

    def _table_shape(self, slide: Any, table: Table, rows: list[Any], left: int, top: int, width: int, height: int) -> None:
        from pptx.dml.color import RGBColor
        from pptx.util import Pt

        columns = table.columns
        shape = slide.shapes.add_table(len(rows) + 1, len(columns) + 1, left, top, width, height)
        grid = shape.table
        header = [table.title] + [column.label for column in columns]
        roles = self.g.colour_roles
        for c, text in enumerate(header):
            cell = grid.cell(0, c)
            cell.text = text
            cell.fill.solid()
            cell.fill.fore_color.rgb = RGBColor.from_string(roles["header_fill"])
            for paragraph in cell.text_frame.paragraphs:
                for run in paragraph.runs:
                    run.font.size = Pt(11)
                    run.font.bold = True
                    run.font.color.rgb = RGBColor.from_string(roles["header_text"])
        for r, row in enumerate(rows, start=1):
            values = [row.label]
            for column in columns:
                cell = row.cells.get(column.key)
                values.append(format_value(cell.value, column.number_format, locale=self.ctx.locale) if cell else "")
            for c, text in enumerate(values):
                cell = grid.cell(r, c)
                cell.text = text
                for paragraph in cell.text_frame.paragraphs:
                    for run in paragraph.runs:
                        run.font.size = Pt(10)
                        run.font.bold = bool(row.emphasis)

    def table(self, heading: str, table: Table, source: str, *, layout: int = _LAYOUT_TITLE_ONLY,
              notes: list[str] | None = None, max_chunks: int | None = None) -> None:
        if not table.rows:
            return
        chunks = [table.rows[i:i + _TABLE_ROWS] for i in range(0, len(table.rows), _TABLE_ROWS)]
        talk = notes
        for index, rows in enumerate(chunks[:max_chunks] if max_chunks else chunks):
            if talk is not None:
                notes = talk
            else:
                facts = sorted({c.fact_id for row in rows for c in row.cells.values() if c.fact_id})
                notes = [f"{table.title}, from {source}.",
                         (f"Every figure is a ledger entry: {', '.join(facts[:8])}" + (" and others." if len(facts) > 8 else "."))
                         if facts else "Figures as the source table states them."]
                if table.note and index == 0:
                    notes.append(table.note)
            title = heading if index == 0 else f"{heading} (continued)"
            slide = self._slide(layout, title, notes)
            if slide is None:
                return
            height = _emu(0.42) * (len(rows) + 1)
            self._table_shape(slide, table, rows, _emu(0.6), _emu(1.5), _emu(_WIDTH_IN - 1.2), height)

    def chart(self, chart: Any, table: Table, source: str) -> None:
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_LEGEND_POSITION

        categories, series = legacy._chart_series(chart, table)
        if not categories or not series:
            return
        labels = ", ".join(label for label, _values, _fmt in series)
        slide = self._slide(_LAYOUT_TITLE_ONLY, chart.title, [
            f"Chart of {labels} by {', '.join(categories[:6])}.",
            f"Every point is a cell of {table.title} in {source}, shown as a table elsewhere in this deck."])
        if slide is None:
            return
        data = CategoryChartData()
        data.categories = categories
        for label, values, number_format in series[:1] if chart.kind.value == "pie" else series:
            data.add_series(label, tuple(v if v is not None else 0.0 for v in values), number_format=number_format or "General")
        frame = slide.shapes.add_chart(legacy._chart_type(chart.kind), _emu(0.8), _emu(1.5),
                                       _emu(_WIDTH_IN - 1.6), _emu(5.0), data)
        native = frame.chart
        native.has_legend = len(series) > 1
        if native.has_legend:
            native.legend.position = XL_LEGEND_POSITION.BOTTOM
            native.legend.include_in_layout = False

    def _chart_frame(self, slide: Any, chart: Any, table: Table, left: int, top: int, width: int, height: int) -> bool:
        from pptx.chart.data import CategoryChartData
        from pptx.enum.chart import XL_LEGEND_POSITION

        categories, series = legacy._chart_series(chart, table)
        if not categories or not series:
            return False
        data = CategoryChartData()
        data.categories = categories
        for label, values, number_format in series[:1] if chart.kind.value == "pie" else series:
            data.add_series(label, tuple(v if v is not None else 0.0 for v in values), number_format=number_format or "General")
        frame = slide.shapes.add_chart(legacy._chart_type(chart.kind), left, top, width, height, data)
        native = frame.chart
        native.has_legend = len(series) > 1
        if native.has_legend:
            native.legend.position = XL_LEGEND_POSITION.BOTTOM
            native.legend.include_in_layout = False
        return True

    def chart_slide(self, title: str, chart: Any, table: Table, notes: list[str]) -> None:
        """A chart under a takeaway title (the presenter deck's chart slide)."""
        categories, series = legacy._chart_series(chart, table)
        if not categories or not series:
            return
        slide = self._slide(_LAYOUT_TITLE_ONLY, title, notes)
        if slide is None:
            return
        self._chart_frame(slide, chart, table, _emu(0.8), _emu(1.5), _emu(_WIDTH_IN - 1.6), _emu(5.0))

    def argument_with_chart(self, title: str, bullets: list[str], chart: Any, table: Table,
                            notes: list[str]) -> None:
        """Two Content: the argument on the left, the chart it rests on on the right."""
        categories, series = legacy._chart_series(chart, table)
        if not categories or not series or not bullets:
            return
        slide = self._slide(_LAYOUT_TWO, title, notes)
        if slide is None:
            return
        self._bullets(self._body_placeholder(slide, 1).text_frame, bullets, 14)
        right = self._body_placeholder(slide, 2)
        left, top, width, height = right.left, right.top, right.width, right.height
        right._element.getparent().remove(right._element)
        self._chart_frame(slide, chart, table, left, top, width, height)

    def comparison(self, heading: str, table: Table, left_key: str, right_key: str, source: str) -> None:
        left_col, right_col = table.column(left_key), table.column(right_key)
        if left_col is None or right_col is None:
            return
        slide = self._slide(_LAYOUT_COMPARISON, heading, [
            f"{left_col.label} against {right_col.label}, row by row, from {table.title} in {source}."])
        if slide is None:
            return
        for label_idx, body_idx, column in ((1, 2, left_col), (3, 4, right_col)):
            label = self._body_placeholder(slide, label_idx)
            if label is not None:
                label.text = column.label
            body = self._body_placeholder(slide, body_idx)
            if body is not None:
                lines = []
                for row in table.rows:
                    cell = row.cells.get(column.key)
                    if cell is not None:
                        lines.append(f"{row.label}: {format_value(cell.value, column.number_format, locale=self.ctx.locale)}")
                self._bullets(body.text_frame, lines[:8], 14)

    def two_content(self, heading: str, paragraphs: list[str], table: Table, source: str) -> None:
        sentences = [s for p in paragraphs for s in longform.sentences(p)][:4]
        if not sentences:
            self.table(heading, table, source)
            return
        slide = self._slide(_LAYOUT_TWO, heading, [" ".join(sentences), f"Table: {table.title}, from {source}."])
        if slide is None:
            return
        self._bullets(self._body_placeholder(slide, 1).text_frame, sentences, 14)
        right = self._body_placeholder(slide, 2)
        left, top, width = right.left, right.top, right.width
        right._element.getparent().remove(right._element)
        self._table_shape(slide, table, table.rows[:8], left, top, width, _emu(0.4) * (min(8, len(table.rows)) + 1))

    def closing(self) -> None:
        doc = self.doc
        lines = [f"Owner: {doc.author.name}, {doc.author.title}"]
        if doc.approver:
            lines.append(f"Approver: {doc.approver.name}, {doc.approver.title}")
        lines.extend(f"{r.title} ({r.artifact_id})" for r in doc.related[:5])
        slide = self._slide(_LAYOUT_CONTENT, "Questions and supporting papers", [
            "Close by pointing to the papers in the pack; every figure shown is in them."])
        if slide is not None:
            self._bullets(self._body_placeholder(slide).text_frame, lines, 16)


def _visible_prose(ir: ArtifactIR) -> list[tuple[str, list[str], Any]]:
    out = []
    for section in ir.sections:
        if section.hidden or not section.body:
            continue
        out.append((section.heading, [section.body], section))
    return out


def render_deck(ctx: Context, ir: ArtifactIR) -> bytes:
    """The deck for *ir*, assembled from its packs."""
    doc = ctx.doc(ir)
    deck = _Deck(ctx, ir, doc)
    facts = ctx.facts
    presentation = ctx.presentation(doc.artifact_type)
    if presentation.deck == "presenter":
        from . import presenter

        deck.cap = presentation.slide_cap
        presenter.build(ctx, ir, deck, presentation)
        return _finish(deck, doc, presentation)
    irs = {item.id: item for item in ctx.world.artifact_irs}
    members: dict[str, ArtifactIR] = {}
    for family in ctx.families:
        if ir.id not in family.roles():
            continue
        for artifact_id, _role in family.members:
            other = irs.get(artifact_id)
            if other is None or artifact_id == ir.id:
                continue
            members.setdefault(ctx.intent(other).artifact_type, other)

    def spell(section: Any) -> list[str]:
        from ...narrative import references

        return [references.substitute(section.body, facts, locale=ctx.locale, presentation=presentation)]

    own = [(h, spell(s), s) for h, _p, s in _visible_prose(ir)]
    workbook = members.get("finance_workbook")
    memo = members.get("cfo_variance_memo")
    rca = members.get("incident_rca")

    plan: list[tuple[str, str]] = [("Summary", f"{ir.title} ({ir.id})")]
    if workbook is not None:
        plan.append(("Financial results", f"{workbook.title} ({workbook.id})"))
    if memo is not None:
        plan.append(("Variance commentary", f"{memo.title} ({memo.id})"))
    if rca is not None:
        plan.append(("Operations", f"{rca.title} ({rca.id})"))
    decisions = [s for s in (memo.sections if memo else []) if s.semantic_role == "decision" and s.body]
    if decisions:
        plan.append(("Decisions requested", f"{memo.title} ({memo.id})" if memo else ""))
    plan.append(("Appendix", "Supporting schedules and ledger references"))

    deck.title()
    deck.agenda([f"{i} {name}" for i, (name, _src) in enumerate(plan, start=1)])

    for number, (name, source) in enumerate(plan, start=1):
        if name == "Appendix":
            continue
        deck.section(str(number), name, source)
        if name == "Summary":
            for heading, paragraphs, _section in own:
                deck.prose(heading, paragraphs, f"{ir.title} ({ir.id}), section {heading}")
            key = longform._cited_table(
                "key_figures", "Key figures", [f for f in ir.fact_ids() if longform._numeric(facts.get(f))],
                longform._Resolver(facts, ctx.successors, None, amendment=False),
                ctx.world.entity_names(), {s.id: s.name for s in ctx.world.systems}, ctx.locale, presentation)
            if key is not None:
                deck.table("Key figures", key, "the fact ledger")
        elif name == "Financial results" and workbook is not None:
            for section in workbook.sections:
                table = section.table
                if section.hidden or table is None or not table.rows or len(table.rows) > 24:
                    continue
                if section.heading == "Approval":
                    continue
                src = f"{workbook.title} ({workbook.id}), sheet {section.heading}"
                deck.table(section.heading, table, src)
                budget = next((c.key for c in table.columns if c.key.endswith("_budget")), None)
                actual = next((c.key for c in table.columns if c.key.endswith("_actual")), None)
                if budget and actual and len(table.rows) <= 8:
                    deck.comparison(f"{section.heading}: budget and actual", table, budget, actual, src)
                for chart in section.charts:
                    if chart.table == table.key:
                        deck.chart(chart, table, src)
        elif name == "Variance commentary" and memo is not None:
            memo_table = next((s.table for s in memo.sections if s.table is not None and not s.hidden
                               and s.heading != "Approval"), None)
            for index, section in enumerate(s for s in memo.sections if s.body and not s.hidden
                                            and s.semantic_role != "decision"):
                src = f"{memo.title} ({memo.id}), section {section.heading}"
                if index == 0 and memo_table is not None:
                    deck.two_content(section.heading, spell(section), memo_table, src)
                else:
                    deck.prose(section.heading, spell(section), src)
            for section in memo.sections:
                if section.table is not None and not section.hidden:
                    for chart in section.charts:
                        if chart.table == section.table.key:
                            deck.chart(chart, section.table, f"{memo.title} ({memo.id})")
        elif name == "Operations" and rca is not None:
            for section in rca.sections:
                if section.body and not section.hidden:
                    deck.prose(section.heading, spell(section), f"{rca.title} ({rca.id}), section {section.heading}")
        elif name == "Decisions requested":
            for section in decisions:
                deck.prose(section.heading, spell(section), f"{memo.title} ({memo.id}), section {section.heading}" if memo else "")

    deck.section(str(len(plan)), "Appendix", "Supporting schedules and ledger references")
    for section in ir.sections:
        if section.hidden and section.table is not None and presentation.appendix == "append":
            deck.table(section.heading, section.table, f"{ir.title} ({ir.id})")
    if workbook is not None:
        for section in workbook.sections:
            if not section.hidden and section.table is not None and len(section.table.rows) > 24:
                deck.table(f"{section.heading} (appendix)", section.table,
                           f"{workbook.title} ({workbook.id}), sheet {section.heading}")
    deck.closing()
    return _finish(deck, doc, presentation)


def _finish(deck: _Deck, doc: longform.LongDocument, presentation: Any) -> bytes:
    """Core properties, custom properties under a reader profile, bytes."""
    properties = deck.prs.core_properties
    properties.title = doc.title
    properties.subject = doc.genre
    properties.author = doc.author.name
    properties.category = doc.genre
    properties.keywords = ", ".join(doc.labels)
    properties.comments = doc.metadata.get("note", "Synthetic corpus generated by Worldloom.")
    properties.identifier = doc.reference
    properties.version = doc.revision.version
    properties.content_status = doc.revision.status
    buffer = BytesIO()
    deck.prs.save(buffer)
    payload = buffer.getvalue()
    if presentation.citations == "appendix":
        from .pdf import provenance_properties

        payload = ooxml.with_custom_properties(payload, provenance_properties(doc, presentation.name))
    return ooxml.normalise(payload, created=doc.revision.at.isoformat())


def render_all(ctx: Context) -> list[Rendered]:
    out: list[Rendered] = []
    for ir in ctx.world.artifact_irs:
        if ctx.intent(ir).artifact_type not in legacy.HANDLES:
            continue
        out.append(Rendered(artifact_id=ir.id, path=ctx.path(ir, "pptx"), media_type=MEDIA_TYPE,
                            payload=render_deck(ctx, ir)))
    return out
