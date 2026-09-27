"""The deck somebody stands up and gives.

The ledger deck (`pptx.render_deck` under ``deck: ledger``) is assembled from
the pack the way a validator reads it: every schedule is a Title Only table
slide, and every speaker note names the ledger entries on its slide
("Every figure is a ledger entry: FACT-0017, FACT-0019..."). Thirty of its
fifty-two slides were tables, and nothing in its notes was sayable.

This deck is built for the presenter profile (``deck: presenter``):

* **Takeaway titles.** A slide's title is its point, built from the lead
  fact of the slide's lead move: the clause of the section that carries that
  fact, when it is a claim ("Close for the period is now final"), else the
  fact itself in a pack template ("Revenue finished AUD 13.3m adverse against
  plan", ``render.deck.takeaway.fact.*``), or for a chart the row the chart
  is about ("The widest revenue gap is Food, at AUD 10.2m adverse"). A
  lead-in that points at a claim without making one ("What the committee
  needs to note", ``render.deck.generic_titles``) is never a title, and
  `lint_titles` refuses any content slide title that carries no fact.
* **An agenda of the argument.** The agenda lists the sections the argument
  runs through, one line per lead move in order (``render.deck.agenda.move.*``:
  where the month landed, which division carried it, what drove it), not the
  slide titles that follow it.
* **Bullets that are the argument.** One bullet per paragraph of the
  section's prose (one per move), each the paragraph's first figure-bearing
  sentence with its connective dropped.
* **The right layout.** Title and Content for an argument, Two Content for
  an argument beside the chart it rests on, Title Only for a chart under a
  takeaway, and tables in the appendix unless the table is the point.
* **Talk-track notes.** What the presenter says: the point, the evidence
  behind it and the line into the next slide, from the notes moves the
  rhetoric catalogue declares and the prompts pack texts
  ``render.deck.notes.<move>``. An alternative is not used twice in one deck
  while another is unused, and the line into the next slide says why it
  follows: the relation between this slide's lead move and the next one's
  (``render.deck.notes.relation.<from>.<to>``, else ``...relation.to.<to>``),
  so a headline hands on to its attribution as "which division carried it"
  rather than "Next:". `prose_quality.notes_repetition` is the measure. No
  fact id appears in a note.
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
from ... import titles as title_style
from ...ids import content_key

if TYPE_CHECKING:  # pragma: no cover
    from collections.abc import Callable

    from ...models import ArtifactIR, ArtifactSection, CanonicalFact, Table
    from ...titles import TitleRules
    from . import Context
    from .pptx import _Deck

__all__ = ["argument", "build", "chart_takeaway", "lint_titles", "takeaway"]

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


def _title(text: str, style: TitleRules | None, keep: Callable[[str], bool] | None = None) -> str:
    """*text* fitted as a title: the shipped cut when the profile names no
    style, else `titles.fit` (a shorter clause, never a truncation), and
    ``""`` when nothing complete fits, so the caller titles the slide from
    its lead fact instead."""
    if style is None:
        return _shorten(text, _TITLE_CHARS).rstrip(".")
    return title_style.fit(text, style, keep) or ""


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
                    and cleaned not in out and not (": " in cleaned and _generic(cleaned.partition(": ")[0]))):
                out.append(cleaned)
    return out[:limit]


def _generic_titles() -> tuple[str, ...]:
    """Lead-ins that point at a claim without making one, from the pack."""
    from ... import packkit

    try:
        raw = packkit.template("render.deck.generic_titles")
    except KeyError:
        return ()
    return tuple(piece.strip().lower() for piece in raw.split(" | ") if piece.strip())


def _generic(text: str) -> bool:
    lowered = text.strip().lower()
    return any(lowered.startswith(phrase) for phrase in _generic_titles())


#: A clause shorter than this is a figure, not a claim: "AUD 13.3m adverse".
_CLAIM_WORDS = 4


def _clauses(raw: str, spelled: str) -> list[tuple[str, str]]:
    """A sentence's clauses around a colon, raw and spelled side by side; the
    whole sentence when the two do not split alike (a value with a colon)."""
    raw_parts, spelled_parts = raw.split(": "), spelled.split(": ")
    if len(raw_parts) != len(spelled_parts):
        return [(raw, spelled)]
    return list(zip(raw_parts, spelled_parts, strict=True))


def takeaway(raw: str, spelled: str, fallback: str, facts: Mapping[str, CanonicalFact] | None = None,
             fact_title: Any = None, titled: set[str] | None = None, style: TitleRules | None = None,
             keep: Callable[[str], bool] | None = None) -> str:
    """A slide title that is the slide's point, built from its lead fact.

    The lead fact is the first current fact the section cites. The title is
    the clause that carries it when that clause is a claim; when it is only a
    figure ("The group's position in one line: AUD 13.3m adverse") the title
    is the fact itself in the pack's words (*fact_title*). A sentence that only
    retells a superseded belief is history, not a point. A fact that already
    titles an earlier slide (*titled*, updated here) does not title another:
    two slides saying "Revenue finished AUD 13.3m adverse" are one slide.

    Under a title *style* (the profile's ``titles`` knob) a claim that does
    not fit is shortened to a shorter clause that still carries a figure
    (*keep* says which pieces do), never cut mid-clause; when none fits, the
    lead fact's template titles the slide.
    """
    from ...narrative import references

    titled = set() if titled is None else titled

    for paragraph in _pairs(raw, spelled):
        for raw_sentence, sentence in paragraph:
            ids = references.referenced(raw_sentence)
            if not ids:
                continue
            current = [i for i in ids if (facts is None or getattr(facts.get(i), "valid_to", None) is None)
                       and i not in titled]
            if not current:
                continue
            for raw_clause, clause in _clauses(raw_sentence, sentence):
                if not references.referenced(raw_clause):
                    continue
                claim = _clean(clause).rstrip(".")
                if len(claim.split()) >= _CLAIM_WORDS and not _generic(claim):
                    claim = claim[:1].upper() + claim[1:]
                    fitted = _title(claim, style, keep)
                    if fitted:
                        titled.update(references.referenced(raw_clause))
                        return fitted
                break
            built = fact_title(current[0]) if fact_title is not None else ""
            if built:
                titled.add(current[0])
                return built
    return fallback


def lint_titles(titles: list[tuple[str, list[str]]], style: TitleRules | None = None) -> list[str]:
    """Findings on a deck plan's content slide titles, as sentences to act on.

    *titles* pairs each content slide's title with the values of the facts it
    shows, as spelled. A title must carry one of them (a figure, a recorded
    value, a name the fact is about): a title with none is a label, not a
    point. And no title may be a lead-in the pack lists as generic. Under a
    title *style* (`titles`), a title must also be complete (no ellipsis, no
    last word that leaves a clause open), within the style's words and
    characters, and free of the characters the style does not print.
    """
    findings: list[str] = []
    for title, values in titles:
        lowered = title.lower()
        if _generic(title):
            findings.append(f"{title!r} is a lead-in, not a takeaway; title the slide with the claim it points at")
        elif not any(value and value.lower() in lowered for value in values):
            findings.append(f"{title!r} carries none of the slide's facts; build the title from its lead fact")
        findings.extend(title_style.lint(title, style))
    return findings


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
    style = title_style.rules_for(presentation)
    return _title(text or chart.title, style, lambda piece: value.lower() in piece.lower()) or chart.title


class Talk:
    """Speaker notes as a talk track: point, evidence, transition.

    One per deck, because the no-repeat rule is a deck's: an alternative of a
    pack text is not used twice while another is unused, walked from a start
    chosen by content key, so the same deck always says the same thing and
    two slides never open their notes alike while the pack has another way.
    """

    def __init__(self, deck: _Deck, artifact_type: str, mode: str = "talk", names: tuple[str, ...] = ()) -> None:
        from ... import rhetoric

        self.names = tuple(sorted((n for n in names if n[:1].isupper()), key=len, reverse=True))
        """Names that open a sentence as themselves: "Food carried the miss"
        stays "Food" after "the point is that"."""
        self.deck = deck
        self.mode = mode
        """``talk`` (what the presenter says) or ``provenance`` (where the
        slide's content came from), from the profile's `notes` knob."""
        self.moves = rhetoric.notes_moves(artifact_type)
        self.used: dict[str, set[int]] = {}

    def _lower(self, text: str) -> str:
        if text[:2].isupper() or any(text.startswith(name) for name in self.names):
            return text
        return text[:1].lower() + text[1:]

    def say(self, key: str, seed: str, **values: Any) -> str:
        """One alternative of *key*, filled, not yet used in this deck if any
        alternative is still unused."""
        from ... import packkit
        from ...packkit.models import PLACEHOLDER

        try:
            raw = packkit.template(key)
        except KeyError:
            return ""
        options = [piece.strip() for piece in raw.split(" | ") if piece.strip()]
        if not options:
            return ""
        used = self.used.setdefault(key, set())
        if len(used) >= len(options):
            used.clear()
        start = int(content_key(key, seed), 16) % len(options)
        index = next((start + step) % len(options) for step in range(len(options))
                     if (start + step) % len(options) not in used)
        used.add(index)
        return PLACEHOLDER.sub(lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0),
                               options[index])

    def bridge(self, move: str, following: str, following_move: str, seed: str) -> str:
        """The line into the next slide: why it follows, from the relation
        between this slide's lead move and the next one's."""
        target = self._lower(following).rstrip(".")
        keys = [f"render.deck.notes.relation.{move}.{following_move}",
                f"render.deck.notes.relation.from.{move}",
                f"render.deck.notes.relation.to.{following_move}"] if following_move else []
        for key in [*keys, "render.deck.notes.transition"]:
            line = self.say(key, seed, next=target)
            if line:
                return line
        return ""

    def notes(self, title: str, point: str, evidence: list[str], following: str, *,
              said: str = "", move: str = "", following_move: str = "") -> list[str]:
        """The note for one slide. *said* replaces the point where the slide
        has something to say rather than a claim (the opening, the close)."""
        lines: list[str] = []
        seed = f"{self.deck.ir.id}\x1f{title}"
        if self.mode == "provenance":
            source = f"{self.deck.doc.title} ({self.deck.doc.reference})"
            return [_text("render.deck.notes.provenance", seed, title=title, source=source)
                    or f"{title}: from {source}."]
        for note_move in self.moves:
            if note_move == "point":
                if said:
                    lines.append(said)
                elif point:
                    lines.append(self.say("render.deck.notes.point", seed, point=point.rstrip("."),
                                          point_lower=self._lower(point).rstrip(".")))
            elif note_move == "evidence" and evidence:
                joined = " ".join(evidence)
                lines.append(self.say("render.deck.notes.evidence", seed, evidence=joined,
                                      evidence_lower=self._lower(joined)))
            elif note_move == "transition" and following:
                lines.append(self.bridge(move, following, following_move, seed))
        return [line for line in lines if line]


def _lead_move(artifact_type: str, section: ArtifactSection) -> str:
    """The first move a section makes, which is what its slide argues."""
    from ... import rhetoric

    specs = rhetoric.declared(artifact_type, section.heading, section.semantic_role or "")
    return specs[0].name if specs else ""


def _display(name: str) -> str:
    """A subject a reader names: a slug (``inventory-valuation``) as words."""
    if name and name == name.lower() and "-" in name and " " not in name:
        words = name.replace("-", " ")
        return f"the {words}" if words.endswith("service") else f"the {words} service"
    return name


def build(ctx: Context, ir: ArtifactIR, deck: _Deck, presentation: Any) -> list[dict[str, Any]]:
    """Fill *deck* as a presenter's deck of *ir*, within the profile's budget.

    Returns the slide plan it drew, so a check can read what each slide was
    built from."""
    from ...narrative import references
    from ...narrative.composer import _parse, measure_noun
    from .pptx import (
        _LAYOUT_CONTENT,
        _LAYOUT_SECTION,
        _LAYOUT_TITLE_ONLY,
        _visible_prose,
    )

    doc = deck.doc
    facts = ctx.facts
    style = title_style.rules_for(presentation)
    irs = {item.id: item for item in ctx.world.artifact_irs}
    names = ctx.world.entity_names()
    talk = Talk(deck, doc.artifact_type, presentation.notes, tuple(names.values()))
    company = ctx.world.company.id
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

    def alone(fact: CanonicalFact) -> str:
        return references.render_value(fact, locale=ctx.locale, presentation=presentation)

    def fact_title(fact_id: str) -> str:
        """The lead fact as a claim, in the pack's words."""
        fact = facts.get(fact_id)
        if fact is None:
            return ""
        subject = _display(names.get(fact.subject, ""))
        noun = measure_noun(fact.kind)
        phrase = noun if fact.subject == company or not subject else f"{subject} {noun}"
        value = alone(fact)
        if fact.value is None:
            if len(value.split()) >= _CLAIM_WORDS:
                head = " ".join(value.split()[:_CLAIM_WORDS]).lower()
                fitted = _title(value[:1].upper() + value[1:], style, lambda piece: head in piece.lower())
                if fitted:
                    return fitted
            key = "render.deck.takeaway.fact.text"
        else:
            facet = _parse(fact.kind)[2] or "value"
            key = f"render.deck.takeaway.fact.{facet}"
            if facet == "variance":
                key += ".adverse" if fact.value.amount < 0 else ".favourable"
        text = _text(key, fact_id, subject=phrase, value=value) or _text(
            "render.deck.takeaway.fact.value", fact_id, subject=phrase, value=value)
        shown_value = value if fact.value is not None else " ".join(value.split()[:_CLAIM_WORDS])
        return _title(text[:1].upper() + text[1:], style,
                      lambda piece: shown_value.lower() in piece.lower()) if text else ""

    def figured(section_raw: str) -> list[str]:
        """The spellings of the section's facts a shortened title may keep:
        its figures and the opening words of its recorded values."""
        from ...figures import spellings_of

        values: list[str] = []
        for fid in references.referenced(section_raw):
            fact = facts.get(fid)
            if fact is None:
                continue
            spelled = alone(fact).rstrip(".")
            values.append(spelled if fact.value is not None else " ".join(spelled.split()[:_CLAIM_WORDS]))
            values.extend(spellings_of(fact, locale=ctx.locale, presentation=presentation))
        return [v for v in values if v]

    def shown(section_raw: str) -> list[str]:
        """What the slide's facts look like on it: their spellings, alone and
        rounded, their recorded words, and the names they are about."""
        from ...figures import spellings_of

        values: list[str] = []
        for fid in references.referenced(section_raw):
            fact = facts.get(fid)
            if fact is None:
                continue
            values.append(alone(fact).rstrip("."))
            values.extend(spellings_of(fact, locale=ctx.locale, presentation=presentation))
            if fact.value is None and fact.text_value:
                values.append(" ".join(alone(fact).split()[:4]))
            values.append(_display(names.get(fact.subject, "")))
        return [v for v in values if v]

    # The slides, planned before any is drawn, so every note can name the
    # slide that follows it and the budget can be kept.
    plan: list[dict[str, Any]] = []
    titles_seen: set[str] = set()
    titled: set[str] = set()

    def add(item: dict[str, Any]) -> None:
        if item["title"] in titles_seen:
            return
        titles_seen.add(item["title"])
        plan.append(item)

    def argue(section: ArtifactSection, artifact_type: str) -> None:
        raw, spelled = section.body or "", spell(section)
        bullets = argument(raw, spelled)
        if not bullets:
            return
        grounds = [v.lower() for v in figured(raw)]
        title = takeaway(raw, spelled, section.heading, facts, fact_title, titled, style,
                         lambda piece: any(v in piece.lower() for v in grounds))
        # A bullet that only restates the title, or leads with a lead-in the
        # pack calls generic, says nothing the title has not; the argument's
        # other bullets carry the slide.
        kept = [b for b in bullets if not (_generic(b.partition(": ")[0] if ": " in b else b)
                                           or (title.lower() in b.lower() and len(b) - len(title) < 60))]
        bullets = kept or bullets
        values = shown(raw)
        if lint_titles([(title, values)], style):
            # The clause read as a claim and carries no fact of its own: the
            # lead fact titles the slide instead.
            lead = next((i for i in references.referenced(raw) if facts.get(i) is not None
                         and facts[i].valid_to is None), None)
            title = (fact_title(lead) or title) if lead else title
        add({"kind": "argument", "title": title, "bullets": bullets, "values": values,
             "evidence": evidence(raw, spelled, title), "section": section,
             "move": _lead_move(artifact_type, section)})

    for _heading, _body, section in _visible_prose(ir):
        argue(section, doc.artifact_type)

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
                add({"kind": "two", "title": title, "bullets": argument(raw, spelled)[:3], "values": [title],
                     "evidence": evidence(raw, spelled, title), "chart": chart, "table": section.table,
                     "move": "attribution"})
            else:
                add({"kind": "chart", "title": title, "chart": chart, "table": section.table, "values": [title],
                     "evidence": [f"{chart.title}, as the workbook plots it."], "move": "comparison"})
    for section in memo_sections:
        if section is attribution or section.semantic_role == "decision":
            continue
        argue(section, "cfo_variance_memo")
    for section in [s for s in (rca.sections if rca else []) if s.body and not s.hidden][:2]:
        argue(section, "incident_rca")
    for section in memo_sections:
        if section.semantic_role == "decision":
            argue(section, "cfo_variance_memo")

    # The closing slide is always given; the appendix gets what the budget
    # leaves. Title, agenda and closing are three slides of it.
    body = plan[:max(0, presentation.slide_cap - 3)]
    closing_title = _text("render.deck.closing.title", doc.title) or "Questions and next steps"
    titles = [item["title"] for item in body] + [closing_title]
    moves = [str(item.get("move", "")) for item in body] + ["close"]

    opening = _text("render.deck.notes.opening", doc.title, genre=doc.genre.lower(), period=doc.period)
    deck.title_slide_notes = talk.notes(doc.title, "", [], "", said=opening)
    deck.title()
    # The agenda is the argument's sections in order, one line per lead move,
    # never the slide titles that follow it.
    agenda: list[str] = []
    for item in body:
        line = _text(f"render.deck.agenda.move.{item.get('move', '')}", doc.title) or (
            item["section"].heading if item.get("section") is not None else "")
        if line and line not in agenda:
            agenda.append(line)
    agenda_title = _text("render.deck.agenda.title", doc.title) or "Agenda"
    slide = deck.slide(_LAYOUT_CONTENT, agenda_title, talk.notes(
        agenda_title, "", [], titles[0] if titles else "", said=_text("render.deck.notes.agenda", doc.title),
        move="agenda", following_move=moves[0] if moves else ""))
    if slide is not None:
        deck._bullets(deck._body_placeholder(slide).text_frame, agenda[:6], 18)

    for position, item in enumerate(body):
        following = titles[position + 1] if position + 1 < len(titles) else ""
        notes = talk.notes(item["title"], item["title"], item.get("evidence", []), following,
                           move=str(item.get("move", "")), following_move=moves[position + 1])
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
        from ...figures import unit_caption

        for heading, table, source in appendix_tables:
            if deck.room() < 1:
                break
            # A schedule prints the ledger's cells, in thousands: its title
            # says so, as the memo's caption does.
            heading, table = unit_caption(heading, table, facts, presentation)
            deck.table(heading, table, source, layout=_LAYOUT_TITLE_ONLY, notes=[
                talk.say("render.deck.notes.schedule", heading, schedule=heading, source=source)], max_chunks=1)
    return body
