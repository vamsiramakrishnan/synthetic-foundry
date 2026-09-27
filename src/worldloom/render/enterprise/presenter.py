"""The deck somebody stands up and gives.

The ledger deck (`pptx.render_deck` under ``deck: ledger``) is assembled from
the pack the way a validator reads it: every schedule is a Title Only table
slide, and every speaker note names the ledger entries on its slide
("Every figure is a ledger entry: FACT-0017, FACT-0019..."). Thirty of its
fifty-two slides were tables, and nothing in its notes was sayable.

This deck is built for the presenter profile (``deck: presenter``):

* **Takeaway titles.** A slide's title is its point, written from the facts
  it shows: the section's first sentence that carries a current figure, cut
  to its claim ("Revenue finished AUD 13.3m adverse against budget"), or for
  a chart the row the chart is about ("The widest revenue gap is Food, at AUD
  10.2m adverse"). No title is typed here: each is a sentence the narrator
  already wrote under claim validation, or a pack template filled with a cell
  the chart plots.
* **Bullets that are the argument.** One bullet per paragraph of the
  section's prose (one per move), each the paragraph's first figure-bearing
  sentence with its connective dropped.
* **The right layout.** Title and Content for an argument, Two Content for
  an argument beside the chart it rests on, Title Only for a chart under a
  takeaway, and tables in the appendix unless the table is the point.
* **Talk-track notes.** What the presenter says: the point, the evidence
  behind it and the line into the next slide, from the notes moves the
  rhetoric catalogue declares and the prompts pack texts
  ``render.deck.notes.<move>``. No fact id appears in a note.
* **A slide budget** from the profile (`Presentation.slide_cap`): the closing
  slide is reserved, and the appendix takes what the budget leaves.

Every figure on a slide is still a fact spelled by
`narrative.references.render_value` or an IR cell spelled by
`values.format_value`, exactly as in the ledger deck.
"""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from typing import TYPE_CHECKING, Any

from ... import longform
from ...ids import content_key

if TYPE_CHECKING:  # pragma: no cover
    from ...models import ArtifactIR, ArtifactSection, CanonicalFact, Table
    from . import Context
    from .pptx import _Deck

__all__ = ["argument", "build", "chart_takeaway", "takeaway"]

_BULLETS = 4
#: A lead-in that only points at what follows its colon ("The remediation now
#: open is this:") is not a claim, so the title is what it points at.
_POINTERS = ("this", "as follows", "reads", "matters", "is", "follows")
_BULLET_CHARS = 170
_TITLE_CHARS = 92


def _text(key: str, seed: str, **values: Any) -> str:
    """One alternative of a prompts pack text, chosen by *seed*, filled."""
    from ... import packkit
    from ...packkit.models import PLACEHOLDER

    try:
        raw = packkit.template(key)
    except KeyError:
        return ""
    options = [piece.strip() for piece in raw.split(" | ") if piece.strip()]
    if not options:
        return ""
    chosen = options[int(content_key(key, seed), 16) % len(options)]
    return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), chosen)


@lru_cache(maxsize=8)
def _connectives(_key: str = "") -> tuple[str, ...]:
    """The connective openings the narrator's pack can put in front of a
    sentence ("Against budget,", "Meanwhile,"), longest first. Dropped from a
    bullet so it opens on its subject; read from the pack, so a pack that
    says its connectives differently has them dropped too."""
    from ... import packkit

    found: set[str] = set()
    for prefix in ("narrative.prose.opening.", "narrative.prose.connective.", "narrative.prose.sequence.",
                   "narrative.prose.hedge"):
        for text in packkit.texts(prefix):
            found.update(piece.strip() for piece in text.split(" | ") if piece.strip())
    return tuple(sorted(found, key=len, reverse=True))


def _clean(sentence: str) -> str:
    """*sentence* without a leading connective the narrator put there."""
    from ... import packkit

    pack = packkit.active("prompts")
    for connective in _connectives(pack.digest if pack is not None else ""):
        if sentence.startswith(connective + " ") and len(sentence) > len(connective) + 2:
            rest = sentence[len(connective) + 1:]
            return rest[:1].upper() + rest[1:]
    return sentence


def _shorten(text: str, limit: int) -> str:
    """*text* cut at a clause boundary once it runs past *limit* characters."""
    text = text.strip()
    if len(text) <= limit:
        return text
    head = text[:limit]
    for mark in ("; ", ", which ", " — ", ", "):
        cut = head.rfind(mark)
        if cut > limit // 3:
            return text[:cut].rstrip(",;") + "."
    return text[:limit].rsplit(" ", 1)[0] + "…"


def _pairs(raw: str, spelled: str) -> list[list[tuple[str, str]]]:
    """``(raw, spelled)`` sentence pairs, per paragraph: the raw sentence says
    which facts it cites, the spelled one is what a reader sees."""
    out = []
    for raw_paragraph, spelled_paragraph in zip(raw.split("\n\n"), spelled.split("\n\n"), strict=False):
        if raw_paragraph.strip():
            out.append(list(zip(longform.sentences(raw_paragraph), longform.sentences(spelled_paragraph),
                                strict=False)))
    return [p for p in out if p]


def argument(raw: str, spelled: str) -> list[str]:
    """The bullets a section's prose makes: from each paragraph (each move),
    its first sentence that carries a figure, else its first sentence,
    cleaned and shortened. A one-paragraph section gives its first three."""
    from ...narrative import references

    paragraphs = _pairs(raw, spelled)
    picked: list[str] = []
    if len(paragraphs) == 1:
        picked = [s for _r, s in paragraphs[0][:3]]
    else:
        for paragraph in paragraphs:
            figured = next((s for r, s in paragraph if references.referenced(r)), None)
            picked.append(figured or paragraph[0][1])
    return list(dict.fromkeys(_shorten(_clean(s), _BULLET_CHARS) for s in picked))[:_BULLETS]


def evidence(raw: str, spelled: str, exclude: str, limit: int = 2) -> list[str]:
    """Figure-bearing sentences a presenter would say behind the point."""
    from ...narrative import references

    out: list[str] = []
    for paragraph in _pairs(raw, spelled):
        for r, s in paragraph:
            cleaned = _clean(s)
            if (references.referenced(r) and exclude.rstrip(".").lower() not in cleaned.lower()
                    and cleaned not in out):
                out.append(cleaned)
    return out[:limit]


def takeaway(raw: str, spelled: str, fallback: str, facts: Mapping[str, CanonicalFact] | None = None) -> str:
    """A slide title that is the slide's point: the first sentence of the
    section that carries a current figure, cut to its claim. A sentence that
    only retells a superseded belief is history, not a point."""
    from ...narrative import references

    for paragraph in _pairs(raw, spelled):
        for raw_sentence, sentence in paragraph:
            ids = references.referenced(raw_sentence)
            if not ids:
                continue
            if facts is not None and all(getattr(facts.get(i), "valid_to", None) is not None for i in ids):
                continue
            # "The month missed plan: revenue finished AUD 13.3m adverse" is
            # titled by its figure; "The first theory did not survive the
            # evidence: ERP logs show ..." by its claim.
            head, _, tail = sentence.partition(": ")
            if tail and any(ch.isdigit() for ch in tail) and len(tail) > 24:
                claim = tail
            elif tail and len(head) > 24 and not head.endswith(_POINTERS):
                claim = head
            elif tail:
                claim = tail
            else:
                claim = sentence
            claim = _clean(claim).rstrip(".")
            claim = claim[:1].upper() + claim[1:]
            return _shorten(claim, _TITLE_CHARS).rstrip(".")
    return fallback


def chart_takeaway(chart: Any, table: Table, ctx: Context, presentation: Any) -> str:
    """A chart's title as its point: the row the chart is about, read from a
    cell of the measure it plots (its widest variance, else its lowest
    actual). The comparison picks a row; it never computes a figure."""
    from ...narrative import references
    from ..values import format_value

    plotted = list(getattr(chart, "series", ()) or ())
    stem = plotted[0].rsplit("_", 1)[0] if plotted else ""
    variance = table.column(f"{stem}_variance") if stem else None
    actual = table.column(f"{stem}_actual") if stem else None
    column = variance or actual
    if column is None:
        return chart.title
    rows = [row for row in table.rows if not row.emphasis and row.cells.get(column.key) is not None
            and isinstance(row.cells[column.key].value, (int, float))]
    if not rows:
        return chart.title
    row = min(rows, key=lambda r: float(r.cells[column.key].value))  # type: ignore[arg-type]
    cell = row.cells[column.key]
    fact = ctx.facts.get(cell.fact_id or "")
    value = (references.render_value(fact, locale=ctx.locale, presentation=presentation) if fact is not None
             else format_value(cell.value, column.number_format, locale=ctx.locale))
    # The measure as the chart names it ("Gross margin against budget by
    # division" is about gross margin), which reads better than a column
    # header written for a grid ("GM% actual").
    measure = chart.title.split(" against ")[0].split(" by ")[0].strip() or column.label
    key = "render.deck.takeaway.widest" if variance is not None else "render.deck.takeaway.lowest"
    text = _text(key, chart.title, row=row.label, measure=measure.lower(), value=value, chart=chart.title)
    text = text[:1].upper() + text[1:]
    return _shorten(text or chart.title, _TITLE_CHARS).rstrip(".")


class Talk:
    """Speaker notes as a talk track: point, evidence, transition."""

    def __init__(self, deck: _Deck, artifact_type: str, mode: str = "talk") -> None:
        from ... import rhetoric

        self.deck = deck
        self.mode = mode
        """``talk`` (what the presenter says) or ``provenance`` (where the
        slide's content came from), from the profile's `notes` knob."""
        self.moves = rhetoric.notes_moves(artifact_type)

    @staticmethod
    def _lower(text: str) -> str:
        return text if text[:2].isupper() else text[:1].lower() + text[1:]

    def notes(self, title: str, point: str, evidence: list[str], following: str, *,
              said: str = "") -> list[str]:
        """The note for one slide. *said* replaces the point where the slide
        has something to say rather than a claim (the opening, the close)."""
        lines: list[str] = []
        seed = f"{self.deck.ir.id}\x1f{title}"
        if self.mode == "provenance":
            source = f"{self.deck.doc.title} ({self.deck.doc.reference})"
            return [_text("render.deck.notes.provenance", seed, title=title, source=source)
                    or f"{title}: from {source}."]
        for move in self.moves:
            if move == "point":
                if said:
                    lines.append(said)
                elif point:
                    lines.append(_text("render.deck.notes.point", seed, point=point.rstrip("."),
                                       point_lower=self._lower(point).rstrip(".")))
            elif move == "evidence" and evidence:
                lines.append(_text("render.deck.notes.evidence", seed, evidence=" ".join(evidence)))
            elif move == "transition" and following:
                lines.append(_text("render.deck.notes.transition", seed, next=self._lower(following).rstrip(".")))
        return [line for line in lines if line]


def build(ctx: Context, ir: ArtifactIR, deck: _Deck, presentation: Any) -> None:
    """Fill *deck* as a presenter's deck of *ir*, within the profile's budget."""
    from ...narrative import references
    from .pptx import (
        _LAYOUT_CONTENT,
        _LAYOUT_SECTION,
        _LAYOUT_TITLE_ONLY,
        _visible_prose,
    )

    doc = deck.doc
    facts = ctx.facts
    talk = Talk(deck, doc.artifact_type, presentation.notes)
    irs = {item.id: item for item in ctx.world.artifact_irs}
    members: dict[str, ArtifactIR] = {}
    for family in ctx.families:
        if ir.id not in family.roles():
            continue
        for artifact_id, _role in family.members:
            other = irs.get(artifact_id)
            if other is not None and artifact_id != ir.id:
                members.setdefault(ctx.intent(other).artifact_type, other)

    def spell(section: ArtifactSection) -> str:
        return references.substitute(section.body or "", facts, locale=ctx.locale, presentation=presentation)

    # The slides, planned before any is drawn, so every note can name the
    # slide that follows it and the budget can be kept.
    plan: list[dict[str, Any]] = []
    titles_seen: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["title"] in titles_seen:
            return
        titles_seen.add(item["title"])
        plan.append(item)

    def argue(section: ArtifactSection) -> None:
        raw, spelled = section.body or "", spell(section)
        bullets = argument(raw, spelled)
        if not bullets:
            return
        title = takeaway(raw, spelled, section.heading, facts)
        add({"kind": "argument", "title": title, "bullets": bullets,
             "evidence": evidence(raw, spelled, title), "section": section})

    for _heading, _body, section in _visible_prose(ir):
        argue(section)

    workbook = members.get("finance_workbook")
    memo = members.get("cfo_variance_memo")
    rca = members.get("incident_rca")

    memo_sections = [s for s in (memo.sections if memo else []) if s.body and not s.hidden]
    attribution = next((s for s in memo_sections if s.semantic_role == "evidence"), None)
    if workbook is not None:
        charted = [(s, c) for s in workbook.sections if s.table is not None and not s.hidden
                   for c in s.charts if c.table == s.table.key and len(s.table.rows) <= 24]
        for index, (section, chart) in enumerate(charted[:2]):
            assert section.table is not None
            title = chart_takeaway(chart, section.table, ctx, presentation)
            if index == 0 and attribution is not None:
                raw, spelled = attribution.body or "", spell(attribution)
                add({"kind": "two", "title": title, "bullets": argument(raw, spelled)[:3],
                     "evidence": evidence(raw, spelled, title), "chart": chart, "table": section.table})
            else:
                add({"kind": "chart", "title": title, "chart": chart, "table": section.table,
                     "evidence": [f"{chart.title}, as the workbook plots it."]})
    for section in memo_sections:
        if section is attribution or section.semantic_role == "decision":
            continue
        argue(section)
    for section in [s for s in (rca.sections if rca else []) if s.body and not s.hidden][:2]:
        argue(section)
    for section in memo_sections:
        if section.semantic_role == "decision":
            argue(section)

    # The closing slide is always given; the appendix gets what the budget
    # leaves. Title, agenda and closing are three slides of it.
    body = plan[:max(0, presentation.slide_cap - 3)]
    closing_title = _text("render.deck.closing.title", doc.title) or "Questions and next steps"
    titles = [item["title"] for item in body] + [closing_title]

    opening = _text("render.deck.notes.opening", doc.title, genre=doc.genre.lower(), period=doc.period)
    deck.title_slide_notes = talk.notes(doc.title, "", [], "the agenda", said=opening)
    deck.title()
    agenda_title = _text("render.deck.agenda.title", doc.title) or "What this deck covers"
    slide = deck.slide(_LAYOUT_CONTENT, agenda_title, talk.notes(
        agenda_title, "", [], titles[0] if titles else "", said=_text("render.deck.notes.agenda", doc.title)))
    if slide is not None:
        deck._bullets(deck._body_placeholder(slide).text_frame,
                      [_shorten(item["title"], 80) for item in body][:6], 18)

    for position, item in enumerate(body):
        following = titles[position + 1] if position + 1 < len(titles) else ""
        notes = talk.notes(item["title"], item["title"], item.get("evidence", []), following)
        if item["kind"] == "argument":
            slide = deck.slide(_LAYOUT_CONTENT, item["title"], notes)
            if slide is not None:
                deck._bullets(deck._body_placeholder(slide).text_frame, item["bullets"],
                              16 if len(item["bullets"]) > 3 else 18)
        elif item["kind"] == "two":
            deck.argument_with_chart(item["title"], item["bullets"], item["chart"], item["table"], notes)
        elif item["kind"] == "chart":
            deck.chart_slide(item["title"], item["chart"], item["table"], notes)

    decisions = [item["title"] for item in body if item.get("section") is not None
                 and item["section"].semantic_role == "decision"]
    closing = deck.slide(_LAYOUT_CONTENT, closing_title, talk.notes(
        closing_title, "", [], "", said=_text("render.deck.notes.closing", doc.title)))
    if closing is not None:
        lines = decisions[:2] + [f"Owner: {doc.author.name}, {doc.author.title}"]
        if doc.approver is not None:
            lines.append(f"Decision: {doc.approver.name}, {doc.approver.title}")
        deck._bullets(deck._body_placeholder(closing).text_frame, lines, 16)

    appendix_tables: list[tuple[str, Table, str]] = []
    if workbook is not None:
        for section in workbook.sections:
            table = section.table
            if section.hidden or table is None or not table.rows or section.heading == "Approval":
                continue
            appendix_tables.append((section.heading, table, workbook.title))
    if appendix_tables and deck.room() > 1:
        section_slide = deck.slide(_LAYOUT_SECTION, "Appendix", [_text("render.deck.notes.appendix", doc.title)])
        if section_slide is not None:
            body_placeholder = deck._body_placeholder(section_slide)
            if body_placeholder is not None:
                body_placeholder.text = "Supporting schedules"
        for heading, table, source in appendix_tables:
            if deck.room() < 1:
                break
            deck.table(heading, table, source, layout=_LAYOUT_TITLE_ONLY, notes=[
                _text("render.deck.notes.schedule", heading, schedule=heading, source=source)], max_chunks=1)
