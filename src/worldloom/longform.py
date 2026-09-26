"""The long-form document a company actually keeps, as one format-neutral plan.

`ArtifactIR` is the traceability record: every section, every cited fact, the
prose a writer produced under constraint. Rendered as it stands it is a memo of
a few hundred words, because that is how much prose a constrained writer is
asked for, and inflating the prose is the one thing this layer may never do.
Real enterprise documents are long for a different reason: **structure**. A
board paper has a cover, a document-control table, an approval block, a
contents page, numbered sections each with the figures it cites set out as a
table, the schedules it rests on incorporated from the workbook, appendices of
lineage and definitions, and a revision history whose entries were written by
people who work there. Every one of those is derivable from the world without
typing a number, which is what this module does.

**The rule every block here keeps.** A block is one of:

* prose the narrative compiler wrote, with each ``{{fact:ID}}`` spelled by
  `narrative.references.render_value` exactly as every other renderer spells
  it;
* a table whose every figure is either an IR cell (its own artifact's, or a
  family member's, attributed as such) or a fact spelled by the same function
  and carrying that fact's id;
* furniture built from world records: people, their titles, systems, access
  policies, event kinds and timestamps, artifact ids and titles.

Nothing here computes a figure, rounds one, or sums one. The one place a value
can differ from the canonical document's is a *revision* (`revisions`), and
there the difference is a different fact from the store: the predecessor a
draft was written against, or the successor an amendment adopted.

**One plan, five renderers.** `render.enterprise` turns a `LongDocument` into
DOCX, PDF, Markdown and HTML, and a family into a PPTX deck, so a board paper's
Word and PDF twins cannot disagree about which table is Table 3.1.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .models import (
    ArtifactIR,
    ArtifactSection,
    CanonicalFact,
    Cell,
    Chart,
    Column,
    Row,
    Table,
)
from .narrative import references

if TYPE_CHECKING:  # pragma: no cover
    from .locales import Locale
    from .models import ArtifactIntent
    from .presentation import Presentation
    from .world import World

__all__ = [
    "Block",
    "Comment",
    "Family",
    "LongDocument",
    "Part",
    "Person",
    "Revision",
    "document",
    "families",
    "family_of",
    "genre_label",
    "revisions",
]


# ---------------------------------------------------------------------------
# The plan
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Person:
    id: str
    name: str
    title: str


@dataclass(frozen=True)
class Block:
    """One unit of body content.

    ``kind`` is ``prose`` (``text``), ``table`` (``table``, ``number``,
    ``caption``, ``source``), ``figure`` (``chart`` over ``table``, same
    numbering), or ``note`` (``text``). ``segments`` is set on a revised prose
    block only: ``(text, None)`` is unchanged text and ``(old, new)`` is a
    tracked replacement, so a renderer can mark the change the way Word does.
    """

    kind: str
    text: str = ""
    table: Table | None = None
    chart: Chart | None = None
    number: str = ""
    caption: str = ""
    source: str = ""
    segments: tuple[tuple[str, str | None], ...] = ()


@dataclass(frozen=True)
class Part:
    """A numbered section (``level`` 1) or subsection (``level`` 2)."""

    number: str
    heading: str
    blocks: tuple[Block, ...] = ()
    children: tuple[Part, ...] = ()
    appendix: bool = False
    fact_ids: tuple[str, ...] = ()

    @property
    def label(self) -> str:
        prefix = f"Appendix {self.number}" if self.appendix else self.number
        return f"{prefix} {self.heading}".strip()


@dataclass(frozen=True)
class Revision:
    version: str
    status: str
    at: datetime
    by: Person
    summary: str
    as_of: datetime | None
    """The instant whose facts this revision was written against. ``None`` is
    the canonical revision, rendered from the IR exactly."""
    amendment: bool = False
    changed_fact_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class Comment:
    author: Person
    at: datetime
    part: str
    text: str
    resolution: str


@dataclass(frozen=True)
class Family:
    """Documents that travel together: a close pack, a board pack."""

    key: str
    kind: str
    title: str
    period: str
    members: tuple[tuple[str, str], ...]
    """``(artifact_id, role)`` in pack order."""

    def roles(self) -> dict[str, str]:
        return dict(self.members)


@dataclass(frozen=True)
class Related:
    artifact_id: str
    title: str
    artifact_type: str
    role: str
    slug: str


@dataclass(frozen=True)
class LongDocument:
    artifact_id: str
    artifact_type: str
    title: str
    subtitle: str
    genre: str
    company: str
    reference: str
    classification: str
    audience: str
    period: str
    created_at: datetime
    author: Person
    approver: Person | None
    reviewers: tuple[Person, ...]
    revision: Revision
    history: tuple[Revision, ...]
    comments: tuple[Comment, ...]
    parts: tuple[Part, ...]
    appendices: tuple[Part, ...]
    related: tuple[Related, ...]
    family: Family | None
    labels: tuple[str, ...]
    fact_ids: tuple[str, ...]
    draft: bool = False
    long: bool = True
    """Chaptered: each numbered section opens a page and a contents page
    precedes them. A one-page calendar is not a report and does not get one."""
    metadata: Mapping[str, str] = field(default_factory=dict)

    def all_parts(self) -> tuple[Part, ...]:
        return self.parts + self.appendices

    def tables(self) -> list[Block]:
        out: list[Block] = []
        for part in self.all_parts():
            for node in (part, *part.children):
                out.extend(block for block in node.blocks if block.kind == "table")
        return out


# ---------------------------------------------------------------------------
# Vocabulary
# ---------------------------------------------------------------------------

#: What each document type is called on its own cover. A label, never a
#: figure; types nobody named here are called by their own type name.
_GENRES: dict[str, str] = {
    "cfo_variance_memo": "Monthly business review paper",
    "executive_summary": "Board paper",
    "incident_rca": "Post-incident review report",
    "working_note": "Working paper",
    "knowledge_article": "Standard operating procedure",
    "close_calendar": "Close calendar",
    "finance_workbook": "Management accounts workbook",
    "meeting_minutes": "Minutes",
    "unit_close_commentary": "Business unit commentary",
    "confluence_page": "Status page",
    "servicenow_incident": "Incident record",
    "jira_issues": "Engineering work log",
    "email_thread": "Correspondence",
    "company_timeline": "Company history",
    "audit_committee_pack": "Audit committee paper",
    "service_impact_assessment": "Service impact assessment",
    "remediation_scope_review": "Remediation scope review",
    "peak_trading_review": "Peak trading review",
    "sponsor_pack": "Sponsor pack",
    "member_report": "Member report",
    "ministerial_brief": "Ministerial brief",
}


def genre_label(artifact_type: str) -> str:
    return _GENRES.get(artifact_type, artifact_type.replace("_", " ").capitalize())


#: Which family each type belongs to, and its role there. A type may sit in
#: more than one pack, the way a CFO paper is both part of the close pack and
#: tabled at the executive committee.
_FAMILY_ROLES: dict[str, tuple[tuple[str, str], ...]] = {
    "finance_workbook": (("close", "Management accounts workbook"),),
    "cfo_variance_memo": (("close", "Variance paper"), ("board", "Paper for decision")),
    "unit_close_commentary": (("close", "Business unit commentary"),),
    "close_calendar": (("close", "Close calendar"),),
    "working_note": (("close", "Working paper"),),
    "executive_summary": (("close", "Results deck"), ("board", "Board paper and deck")),
    "meeting_minutes": (("board", "Minutes"),),
    "incident_rca": (("incident", "Post-incident review"), ("board", "Paper for noting")),
    "servicenow_incident": (("incident", "Incident record"),),
    "jira_issues": (("incident", "Engineering work"),),
    "knowledge_article": (("incident", "Workaround procedure"),),
    "email_thread": (("incident", "Correspondence"),),
    "confluence_page": (("incident", "Status page"),),
}

_FAMILY_TITLES = {
    "close": "Month-end close pack",
    "board": "Executive committee pack",
    "incident": "Incident record pack",
}

#: Types whose long form incorporates the close pack's schedules. A board
#: paper or a variance paper that did not carry the numbers it discusses would
#: be one a reader has to open a second file to check.
_INCORPORATES_SCHEDULES = {"cfo_variance_memo", "executive_summary"}

#: Sections that summarise, by semantic role, in preference order.
_SUMMARY_ROLES = ("summary", "position")

#: A schedule longer than this goes to an appendix rather than the body.
_BODY_TABLE_ROWS = 24


def _period_of(ir: ArtifactIR, world: World) -> str:
    scope = [p for p in ir.metadata.get("scope_periods", "").split(",") if p]
    if scope:
        return max(scope)
    return world.period or "current"


def families(world: World) -> tuple[Family, ...]:
    """Every pack the world's documents form, in a stable order.

    A pack is only a pack with two members; a lone document is not a family.
    """
    grouped: dict[tuple[str, str], list[tuple[str, str]]] = {}
    for ir in sorted(world.artifact_irs, key=lambda item: item.id):
        intent = world.artifact_intents.by_id(ir.intent_id)
        roles = _FAMILY_ROLES.get(intent.artifact_type)
        if roles is None:
            roles = ((f"domain:{intent.domain}", genre_label(intent.artifact_type)),)
        period = _period_of(ir, world)
        for kind, role in roles:
            grouped.setdefault((kind, period), []).append((ir.id, role))
    out: list[Family] = []
    for (kind, period), members in sorted(grouped.items()):
        if len(members) < 2:
            continue
        if kind.startswith("domain:"):
            domain = kind.split(":", 1)[1]
            title = f"{domain.replace('_', ' ').capitalize()} documents"
            kind_slug = f"{domain.replace('_', '-')}-documents"
        else:
            title = _FAMILY_TITLES[kind]
            kind_slug = f"{kind}-pack"
        out.append(Family(
            key=f"{kind_slug}-{period}",
            kind=kind,
            title=f"{title} {period}",
            period=period,
            members=tuple(members),
        ))
    return tuple(out)


def family_of(world: World, artifact_id: str, *, fams: Sequence[Family] | None = None) -> Family | None:
    """The artifact's primary pack: the first of its type's packs that lists it.

    A variance paper is tabled at the executive committee, but it belongs to
    the close pack that produced it; ``_FAMILY_ROLES`` lists that pack first.
    """
    containing = [f for f in (fams if fams is not None else families(world)) if artifact_id in f.roles()]
    if not containing:
        return None
    irs = {ir.id: ir for ir in world.artifact_irs}
    ir = irs.get(artifact_id)
    order: list[str] = []
    if ir is not None:
        artifact_type = world.artifact_intents.by_id(ir.intent_id).artifact_type
        order = [kind for kind, _ in _FAMILY_ROLES.get(artifact_type, ())]
    return min(containing, key=lambda f: (order.index(f.kind) if f.kind in order else len(order), f.key))


# ---------------------------------------------------------------------------
# Small derivations
# ---------------------------------------------------------------------------

_MEASURE_SUFFIXES = {"actual", "budget", "variance", "forecast", "prior", "target"}


def fact_label(fact: CanonicalFact) -> str:
    """A fact kind as a reader would label a row: ``Revenue, actual``."""
    parts = fact.kind.split(".")
    body = parts[1:] if len(parts) > 1 else parts
    tail = ""
    if len(body) > 1 and body[-1] in _MEASURE_SUFFIXES:
        tail = body[-1]
        body = body[:-1]
    words = " ".join(body).replace("_", " ").replace(" pct", " %").strip()
    words = words[:1].upper() + words[1:]
    return f"{words}, {tail}" if tail else words


def _person(world: World, person_id: str | None) -> Person | None:
    if not person_id:
        return None
    try:
        person = world.people.by_id(person_id)
    except (KeyError, ValueError):
        return None
    return Person(id=person.id, name=person.name, title=person.title)


def _classification(world: World, intent: ArtifactIntent) -> tuple[str, str]:
    policy_id = getattr(intent, "access_policy_id", None)
    label = ""
    for policy in world.access_policies:
        if policy.id == policy_id:
            label = policy.label
    if not label:
        label = intent.audience.replace("_", " ").capitalize()
    if intent.audience == "all_staff" or label.lower() == "all staff":
        return "Internal", label
    return f"Confidential ({label})", label


def _minute(instant: datetime) -> datetime:
    return instant.replace(second=0, microsecond=0)


def _chain(facts: Mapping[str, CanonicalFact], successors: Mapping[str, list[str]],
           fact_id: str) -> tuple[list[CanonicalFact], list[CanonicalFact]]:
    """``(ancestors, descendants)`` of *fact_id* along ``supersedes``, nearest first."""
    ancestors: list[CanonicalFact] = []
    seen = {fact_id}
    current = facts.get(fact_id)
    while current is not None and current.supersedes and current.supersedes not in seen:
        seen.add(current.supersedes)
        parent = facts.get(current.supersedes)
        if parent is None:
            break
        ancestors.append(parent)
        current = parent
    descendants: list[CanonicalFact] = []
    frontier = [fact_id]
    while frontier:
        nxt: list[str] = []
        for fid in frontier:
            for child in sorted(successors.get(fid, ())):
                if child in seen:
                    continue
                seen.add(child)
                if child in facts:
                    descendants.append(facts[child])
                    nxt.append(child)
        frontier = nxt
    descendants.sort(key=lambda item: (item.valid_from, item.id))
    return ancestors, descendants


class _Resolver:
    """Which fact a revision states for each cited fact id.

    ``as_of is None`` is the canonical document: every id resolves to itself,
    which is exactly what every other renderer does. A draft resolves an id to
    the newest member of its supersession chain *at or before* the cited fact
    that was already true at ``as_of``, or to nothing (``TBC``). An amendment
    resolves it to the newest *later* member true at ``as_of``.
    """

    def __init__(self, facts: Mapping[str, CanonicalFact], successors: Mapping[str, list[str]],
                 as_of: datetime | None, *, amendment: bool) -> None:
        self.facts = facts
        self.successors = successors
        self.as_of = as_of
        self.amendment = amendment
        self._cache: dict[str, CanonicalFact | None] = {}

    def __call__(self, fact_id: str) -> CanonicalFact | None:
        if fact_id in self._cache:
            return self._cache[fact_id]
        fact = self.facts.get(fact_id)
        resolved: CanonicalFact | None = fact
        if fact is not None and self.as_of is not None:
            ancestors, descendants = _chain(self.facts, self.successors, fact_id)
            if self.amendment:
                live = [d for d in descendants if d.valid_from <= self.as_of]
                resolved = live[-1] if live else fact
            elif fact.valid_from > self.as_of:
                resolved = next((a for a in ancestors if a.valid_from <= self.as_of), None)
        self._cache[fact_id] = resolved
        return resolved


_TBC = "TBC"


def _spell(fact: CanonicalFact | None, locale: Locale, presentation: Presentation) -> str:
    if fact is None:
        return _TBC
    return references.render_value(fact, locale=locale, presentation=presentation)


def _prose(text: str, resolve: _Resolver, canonical: Mapping[str, CanonicalFact],
           locale: Locale, presentation: Presentation) -> tuple[str, tuple[tuple[str, str | None], ...]]:
    """*text* with every reference spelled, and the tracked segments if any
    reference resolved to a different fact than the canonical document's."""
    segments: list[tuple[str, str | None]] = []
    changed = False
    cursor = 0
    for match in references.REFERENCE.finditer(text):
        fid = match.group("id")
        segments.append((text[cursor:match.start()], None))
        stated = resolve(fid)
        base = canonical.get(fid)
        new_text = _spell(stated, locale, presentation) if base is not None or stated is not None else f"[missing {fid}]"
        if base is not None and (stated is None or stated.id != base.id):
            old_text = _spell(base, locale, presentation)
            if resolve.amendment:
                segments.append((old_text, new_text))
            else:
                segments.append((new_text, None))
            changed = True
        else:
            segments.append((new_text, None))
        cursor = match.end()
    segments.append((text[cursor:], None))
    merged: list[tuple[str, str | None]] = []
    for piece, replacement in segments:
        if replacement is None and merged and merged[-1][1] is None:
            merged[-1] = (merged[-1][0] + piece, None)
        elif piece or replacement:
            merged.append((piece, replacement))
    plain = "".join(new if new is not None else old for old, new in merged)
    return plain, (tuple(merged) if changed and resolve.amendment else ())


def _as_of_table(table: Table, resolve: _Resolver, canonical: Mapping[str, CanonicalFact],
                 locale: Locale, presentation: Presentation) -> Table:
    """*table* as a revision states it: a cell whose fact differs from the
    canonical one shows the fact the revision resolved to, spelled, or TBC."""
    if resolve.as_of is None:
        return table
    rows: list[Row] = []
    touched = False
    for row in table.rows:
        cells: dict[str, Cell] = {}
        for key, cell in row.cells.items():
            if cell.fact_id and cell.fact_id in canonical:
                stated = resolve(cell.fact_id)
                if stated is None or stated.id != cell.fact_id:
                    touched = True
                    cells[key] = Cell(
                        value=_spell(stated, locale, presentation),
                        fact_id=stated.id if stated is not None else None,
                    )
                    continue
            cells[key] = cell
        rows.append(row.model_copy(update={"cells": cells}))
    return table.model_copy(update={"rows": rows}) if touched else table


def _cited_table(key: str, title: str, fact_ids: Sequence[str], resolve: _Resolver,
                 names: Mapping[str, str], systems: Mapping[str, str],
                 locale: Locale, presentation: Presentation) -> Table | None:
    """The figures a section cites, one row per fact, as a table.

    Every value cell is the fact spelled by the same function the prose uses
    and carries that fact's id, so the table and the sentence above it cannot
    disagree about a figure.
    """
    rows: list[Row] = []
    seen: set[str] = set()
    for fid in fact_ids:
        if fid in seen:
            continue
        seen.add(fid)
        stated = resolve(fid)
        base = resolve.facts.get(fid)
        if base is None:
            continue
        shown = stated or base
        rows.append(Row(key=fid, label=fact_label(base), cells={
            "subject": Cell(value=names.get(base.subject, base.subject)),
            "value": Cell(value=_spell(stated, locale, presentation),
                          fact_id=stated.id if stated is not None else None),
            "source": Cell(value=systems.get(shown.source_system or "", shown.authority.value.replace("_", " "))),
            "reference": Cell(value=shown.id if stated is not None else fid),
        }))
    if not rows:
        return None
    return Table(
        key=key, title=title,
        columns=[
            Column(key="subject", label="Subject"),
            Column(key="value", label="Value"),
            Column(key="source", label="Source"),
            Column(key="reference", label="Fact"),
        ],
        rows=rows,
    )


def _numeric(fact: CanonicalFact | None) -> bool:
    return fact is not None and fact.value is not None


# ---------------------------------------------------------------------------
# Revisions and review
# ---------------------------------------------------------------------------


def _successors(facts: Mapping[str, CanonicalFact]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for fact in facts.values():
        if fact.supersedes:
            out.setdefault(fact.supersedes, []).append(fact.id)
    return out


def _reviewer(world: World, intent: ArtifactIntent) -> Person | None:
    author = _person(world, intent.author_id)
    if author is None:
        return None
    try:
        manager_id = world.people.by_id(intent.author_id).manager_id
    except (KeyError, ValueError):
        manager_id = None
    reviewer = _person(world, manager_id)
    if reviewer is None or reviewer.id == intent.approver_id:
        # A reviewer who is also the approver is one pair of eyes, not two;
        # the author's peers in the same function are the next line.
        for person in sorted(world.people, key=lambda p: p.id):
            if (person.function == world.people.by_id(intent.author_id).function
                    and person.id not in {intent.author_id, intent.approver_id}
                    and person.left is None):
                return Person(id=person.id, name=person.name, title=person.title)
        return reviewer
    return reviewer


def _describe_changes(changed: Sequence[str], facts: Mapping[str, CanonicalFact],
                      names: Mapping[str, str]) -> str:
    labels: list[str] = []
    for fid in changed:
        fact = facts.get(fid)
        if fact is None:
            continue
        label = f"{fact_label(fact)} ({names.get(fact.subject, fact.subject)})"
        if label not in labels:
            labels.append(label)
    if not labels:
        return ""
    head = "; ".join(labels[:3])
    return head + ("; and others" if len(labels) > 3 else "")


def revisions(world: World, ir: ArtifactIR, *, facts: Mapping[str, CanonicalFact] | None = None,
              successors: Mapping[str, list[str]] | None = None) -> tuple[Revision, ...]:
    """The document's history, oldest first, derived from world time.

    A draft is dated inside the window its own citations open, so it is
    written against the facts that were true then and marks what was not yet
    known as TBC. Review follows once every figure is in, approval is the
    moment the manifest already records, and an amendment follows each later
    fact that superseded one the approved document cites.
    """
    from . import documents

    facts = facts if facts is not None else {fact.id: fact for fact in world.facts}
    successors = successors if successors is not None else _successors(facts)
    names = world.entity_names()
    intent = world.artifact_intents.by_id(ir.intent_id)
    author = _person(world, intent.author_id) or Person(intent.author_id, intent.author_id, "")
    approver = _person(world, intent.approver_id)
    reviewer = _reviewer(world, intent)
    created = _minute(documents.written_at(intent, facts if isinstance(facts, dict) else dict(facts)))
    cited = sorted({facts[f].valid_from for f in intent.required_fact_ids if f in facts})
    newest = cited[-1] if cited else created
    recent = [t for t in cited if t >= newest - timedelta(days=3)]
    lag = max(created - newest, timedelta(minutes=8))

    draft_at = _minute(recent[len(recent) // 2] + timedelta(minutes=1)) if len(recent) > 1 else None
    if draft_at is None or draft_at >= newest:
        draft_at = _minute(newest + lag / 4)
    history: list[Revision] = []

    def changed_between(earlier: datetime | None, later: datetime | None, *, amendment: bool = False) -> tuple[str, ...]:
        a = _Resolver(facts, successors, earlier, amendment=amendment)
        b = _Resolver(facts, successors, later, amendment=amendment)
        out = []
        for fid in ir.fact_ids():
            left, right = a(fid), b(fid)
            if (left.id if left else None) != (right.id if right else None):
                out.append(fid)
        return tuple(out)

    tbc = [fid for fid in ir.fact_ids() if _Resolver(facts, successors, draft_at, amendment=False)(fid) is None]
    history.append(Revision(
        version="0.1", status="Draft", at=draft_at, by=author,
        summary="First draft for review." + (" Figures not yet confirmed are marked TBC." if tbc else ""),
        as_of=draft_at,
    ))
    reviewing = reviewer or approver
    if reviewing is not None:
        reviewed_at = _minute(newest + lag / 2)
        if reviewed_at <= draft_at:
            reviewed_at = draft_at + timedelta(minutes=1)
        changes = changed_between(draft_at, reviewed_at)
        detail = _describe_changes(changes, facts, names)
        history.append(Revision(
            version="0.2", status="Reviewed", at=reviewed_at, by=reviewing,
            summary=("Reviewed; comments raised." + (f" Figures confirmed: {detail}." if detail else "")),
            as_of=reviewed_at, changed_fact_ids=changes,
        ))
    if approver is not None:
        approved_at = max(created, history[-1].at + timedelta(minutes=1))
        history.append(Revision(
            version="1.0", status="Approved", at=approved_at, by=approver,
            summary=f"Approved for issue by {approver.name}, {approver.title}.",
            as_of=None,
        ))
    else:
        published_at = max(created, history[-1].at + timedelta(minutes=1))
        changes = changed_between(history[-1].as_of, None)
        detail = _describe_changes(changes, facts, names)
        history.append(Revision(
            version="1.0", status="Published", at=published_at, by=author,
            summary="Issued." + (f" Figures confirmed: {detail}." if detail else ""),
            as_of=None,
        ))
    # Amendments: each later fact that superseded one this document cites.
    later: set[datetime] = set()
    for fid in ir.fact_ids():
        _, descendants = _chain(facts, successors, fid)
        for successor in descendants:
            if successor.valid_from > history[-1].at:
                later.add(_minute(successor.valid_from + timedelta(hours=2)))
    previous = _Resolver(facts, successors, None, amendment=True)
    minor = 0
    for at in sorted(later):
        current = _Resolver(facts, successors, at, amendment=True)
        changes = tuple(fid for fid in ir.fact_ids()
                        if (previous(fid) or facts[fid]).id != (current(fid) or facts[fid]).id)
        previous = current
        if not changes:
            continue
        minor += 1
        detail = _describe_changes(changes, facts, names)
        history.append(Revision(
            version=f"1.{minor}", status="Amended", at=at, by=author,
            summary=f"Amended: superseded figures restated ({detail}).",
            as_of=at, amendment=True, changed_fact_ids=changes,
        ))
    return tuple(history)


def _comments(world: World, intent: ArtifactIntent, ir: ArtifactIR, parts: Sequence[Part],
              reviewer: Person | None, approver: Person | None, at: datetime,
              family_facts: Mapping[str, tuple[str, str]], facts: Mapping[str, CanonicalFact],
              systems: Mapping[str, str], names: Mapping[str, str]) -> tuple[Comment, ...]:
    """Review comments, each one a checkable statement about the document.

    A comment is written only when it is true of this document: a tie-out is
    claimed only for figures the named workbook also carries (the same fact
    ids, therefore the same values), a superseded-figure query only where a
    cited fact actually superseded another, a source only where the fact
    names its system of record.
    """
    out: list[Comment] = []
    voices = [p for p in (reviewer, approver) if p is not None]
    if not voices:
        return ()
    used: dict[str, int] = {}
    for index, part in enumerate(p for p in parts if p.fact_ids):
        voice = voices[index % len(voices)]
        candidates: list[tuple[str, str]] = []
        superseding = [facts[f] for f in part.fact_ids if f in facts and facts[f].supersedes]
        tied = [f for f in part.fact_ids if f in family_facts]
        sourced = [facts[f] for f in part.fact_ids if f in facts and facts[f].source_system in systems]
        if superseding:
            fact = superseding[0]
            candidates.append(("supersedes", (
                f"Please confirm this section states {fact.id} ({fact.authority.value.replace('_', ' ')})"
                f" and not {fact.supersedes}, which it superseded.")))
        if tied:
            owner_id, owner_title = family_facts[tied[0]]
            candidates.append(("tie-out", (
                f"Tied out to {owner_title} ({owner_id}): the figures cited here are the"
                " same ledger entries the schedule carries.")))
        if sourced:
            fact = sourced[0]
            candidates.append(("source", (
                f"Source for these figures is {systems[fact.source_system or '']};"
                " please keep the reference in the table.")))
        subjects = sorted({facts[f].subject for f in part.fact_ids if f in facts})
        if len(subjects) > 1:
            candidates.append(("coverage", (
                f"Section covers {', '.join(names.get(s, s) for s in subjects[:4])}"
                + (" and others" if len(subjects) > 4 else "")
                + "; check nothing in scope is missing before approval.")))
        if approver is not None:
            candidates.append(("owner", f"Decision owner is {approver.name}; confirm the wording before approval."))
        if not candidates:
            continue
        key, text = min(candidates, key=lambda item: used.get(item[0], 0))
        used[key] = used.get(key, 0) + 1
        out.append(Comment(author=voice, at=at, part=part.number, text=text,
                           resolution="Addressed in the approved version."))
        if len(out) >= 6:
            break
    return tuple(out)


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


def _schedule_members(world: World, artifact_id: str, fams: Sequence[Family]) -> list[ArtifactIR]:
    """The workbooks in any pack this artifact belongs to."""
    irs = {ir.id: ir for ir in world.artifact_irs}
    out: list[ArtifactIR] = []
    for family in fams:
        if artifact_id not in family.roles():
            continue
        for member_id, _role in family.members:
            ir = irs.get(member_id)
            if ir is None or ir in out:
                continue
            if world.artifact_intents.by_id(ir.intent_id).artifact_type == "finance_workbook":
                out.append(ir)
    return out


def document(
    world: World,
    ir: ArtifactIR,
    *,
    locale: Locale,
    presentation: Presentation,
    revision: Revision | None = None,
    history: Sequence[Revision] | None = None,
    fams: Sequence[Family] | None = None,
    facts: Mapping[str, CanonicalFact] | None = None,
    successors: Mapping[str, list[str]] | None = None,
    slug_for: Callable[[str], str] | None = None,
) -> LongDocument:
    """The long-form plan of *ir*, as of *revision* (the canonical one if omitted)."""
    from . import documents

    facts = facts if facts is not None else {fact.id: fact for fact in world.facts}
    successors = successors if successors is not None else _successors(facts)
    history = tuple(history) if history is not None else revisions(world, ir, facts=facts, successors=successors)
    canonical_index = max(i for i, r in enumerate(history) if r.as_of is None)
    revision = revision or history[canonical_index]
    upto = tuple(r for r in history if r.at <= revision.at)
    resolve = _Resolver(facts, successors, revision.as_of, amendment=revision.amendment)
    draft = revision.status == "Draft"

    intent = world.artifact_intents.by_id(ir.intent_id)
    names = world.entity_names()
    systems = {system.id: system.name for system in world.systems}
    fams = tuple(fams) if fams is not None else families(world)
    family = family_of(world, ir.id, fams=fams)
    author = _person(world, intent.author_id) or Person(intent.author_id, ir.metadata.get("author", intent.author_id), "")
    approver = _person(world, intent.approver_id)
    reviewer = _reviewer(world, intent)
    classification, audience = _classification(world, intent)
    created = _minute(documents.written_at(intent, facts if isinstance(facts, dict) else dict(facts)))
    company = world.company.name

    hidden_ok = presentation.for_doctype(intent.artifact_type).appendix == "append"
    visible = [s for s in ir.sections if not s.hidden]
    hidden = [s for s in ir.sections if s.hidden]

    def prose_block(section: ArtifactSection) -> list[Block]:
        if not section.body:
            if section.table is None and section.quote is None:
                return [Block(kind="note", text="Awaiting narrative.")]
            return []
        text, segments = _prose(section.body, resolve, facts, locale, presentation)
        return [Block(kind="prose", text=para.strip(),
                      segments=segments if len(text.split("\n\n")) == 1 else ())
                for para in text.split("\n\n") if para.strip()]

    summary_section = next(
        (s for role in _SUMMARY_ROLES for s in visible if s.semantic_role == role and s.body),
        next((s for s in visible if s.body), None),
    )

    parts: list[Part] = []
    number = 0

    def next_number() -> str:
        nonlocal number
        number += 1
        return str(number)

    # 1. Executive summary.
    if summary_section is not None:
        num = next_number()
        blocks: list[Block] = []
        if draft and resolve.as_of is not None and any(resolve(f) is None for f in summary_section.fact_ids):
            blocks.append(Block(kind="note", text="Executive summary to be finalised once the outstanding figures are confirmed."))
        blocks.extend(prose_block(summary_section))
        children: list[Part] = []
        numeric = [f for f in summary_section.fact_ids if _numeric(facts.get(f))]
        table = _cited_table("key_figures", "Key figures", numeric, resolve, names, systems, locale, presentation)
        if table is not None:
            children.append(Part(number=f"{num}.1", heading="Key figures", blocks=(Block(
                kind="table", table=table, number=f"{num}.1", caption=f"Key figures: {summary_section.heading}",
                source=f"{ir.title} ({ir.id}), fact ledger"),)))
        parts.append(Part(number=num, heading=f"Executive summary: {summary_section.heading}",
                          blocks=tuple(blocks), children=tuple(children),
                          fact_ids=tuple(summary_section.fact_ids)))

    # 2. The document's own sections, numbered.
    for section in visible:
        if section is summary_section:
            continue
        num = next_number()
        blocks = prose_block(section)
        children = []
        sub = 0
        if section.table is not None:
            sub += 1
            table = _as_of_table(section.table, resolve, facts, locale, presentation)
            blocks.append(Block(kind="table", table=table, number=f"{num}.{sub}",
                                caption=section.table.title, source=f"{ir.title} ({ir.id})"))
            for chart in section.charts:
                if chart.table != section.table.key:
                    continue
                sub += 1
                blocks.append(Block(kind="figure", chart=chart, table=table, number=f"{num}.{sub}",
                                    caption=chart.title, source=f"{ir.title} ({ir.id})"))
        cited = [f for f in section.fact_ids if f in facts]
        if section.body and cited:
            table = _cited_table(f"cited_{num}", f"Figures cited in section {num}", cited,
                                 resolve, names, systems, locale, presentation)
            if table is not None:
                children.append(Part(number=f"{num}.1", heading="Figures cited", blocks=(Block(
                    kind="table", table=table, number=f"{num}.1",
                    caption=f"Figures cited: {section.heading}", source="Fact ledger"),)))
        fact_ids = list(section.fact_ids)
        if section.table is not None:
            fact_ids.extend(c.fact_id for r in section.table.rows for c in r.cells.values() if c.fact_id)
        parts.append(Part(number=num, heading=section.heading, blocks=tuple(blocks),
                          children=tuple(children), fact_ids=tuple(dict.fromkeys(fact_ids))))

    # 3. Schedules incorporated from the pack's workbook.
    appendices: list[Part] = []
    letter = iter("ABCDEFGHIJKLMNOPQRSTUVWXYZ")
    family_facts: dict[str, tuple[str, str]] = {}
    if intent.artifact_type in _INCORPORATES_SCHEDULES:
        for workbook in _schedule_members(world, ir.id, fams):
            for section in workbook.sections:
                if section.table is not None:
                    for row in section.table.rows:
                        for cell in row.cells.values():
                            if cell.fact_id:
                                family_facts.setdefault(cell.fact_id, (workbook.id, workbook.title))
            body_children: list[Part] = []
            num = next_number()
            sub = 0
            for section in workbook.sections:
                if section.hidden or section.table is None or not section.table.rows:
                    continue
                if len(section.table.rows) > _BODY_TABLE_ROWS or section.heading == "Approval":
                    continue
                sub += 1
                table = _as_of_table(section.table, resolve, facts, locale, presentation)
                blocks = [Block(kind="table", table=table, number=f"{num}.{sub}", caption=section.table.title,
                                source=f"{workbook.title} ({workbook.id}), sheet {section.heading}")]
                for chart in section.charts:
                    if chart.table == section.table.key:
                        blocks.append(Block(kind="figure", chart=chart, table=table, number=f"{num}.{sub}",
                                            caption=chart.title,
                                            source=f"{workbook.title} ({workbook.id}), sheet {section.heading}"))
                body_children.append(Part(number=f"{num}.{sub}", heading=section.heading, blocks=tuple(blocks)))
            if body_children:
                parts.append(Part(number=num, heading=f"Financial schedules from {workbook.title}",
                                  blocks=(Block(kind="note", text=(
                                      f"Schedules incorporated from {workbook.title} ({workbook.id}),"
                                      " the workbook this paper rests on. Every figure is the workbook's own cell.")),),
                                  children=tuple(body_children)))
            else:
                number -= 1
            for section in workbook.sections:
                if section.hidden or section.table is None or len(section.table.rows) <= _BODY_TABLE_ROWS:
                    continue
                code = next(letter)
                table = _as_of_table(section.table, resolve, facts, locale, presentation)
                appendices.append(Part(number=code, heading=f"{section.heading} (detailed schedule)", appendix=True,
                                       blocks=(Block(kind="table", table=table, number=f"{code}.1",
                                                     caption=section.table.title,
                                                     source=f"{workbook.title} ({workbook.id}), sheet {section.heading}"),)))

    # 4. Appendices from the document's own record.
    if hidden_ok:
        for section in hidden:
            if section.table is None:
                continue
            code = next(letter)
            table = _as_of_table(section.table, resolve, facts, locale, presentation)
            appendices.append(Part(number=code, heading=section.heading, appendix=True, blocks=(
                Block(kind="note", text="Every fact the prose in this document cites, at the authority and validity the ledger holds."),
                Block(kind="table", table=table, number=f"{code}.1", caption=section.table.title,
                      source=f"{ir.title} ({ir.id})"))))

    cited_all = [f for f in ir.fact_ids() if f in facts]
    lineage_rows: list[Row] = []
    for fid in cited_all:
        stated = resolve(fid)
        fact = stated or facts[fid]
        lineage_rows.append(Row(key=fid, label=fact.id if stated is not None else fid, cells={
            "measure": Cell(value=fact_label(fact)),
            "subject": Cell(value=names.get(fact.subject, fact.subject)),
            "period": Cell(value=fact.period or ""),
            "valid_from": Cell(value=fact.valid_from.strftime("%d %b %Y %H:%M") if stated is not None else _TBC),
            "system": Cell(value=systems.get(fact.source_system or "", "")),
            "event": Cell(value=fact.event_id or ""),
        }))
    if lineage_rows:
        code = next(letter)
        appendices.append(Part(number=code, heading="Data lineage", appendix=True, blocks=(
            Block(kind="note", text="Where each figure in this document comes from: the ledger entry, its system of record and the event that produced it."),
            Block(kind="table", number=f"{code}.1", caption="Lineage of cited figures", source="Fact ledger",
                  table=Table(key="lineage", title="Lineage", columns=[
                      Column(key="measure", label="Measure"), Column(key="subject", label="Subject"),
                      Column(key="period", label="Period"), Column(key="valid_from", label="Valid from"),
                      Column(key="system", label="System of record"), Column(key="event", label="Event")],
                      rows=lineage_rows)))))

    measures: dict[str, tuple[str, str, str]] = {}
    for fid in cited_all:
        fact = facts[fid]
        measures.setdefault(fact.kind, (fact_label(fact), systems.get(fact.source_system or "", ""),
                                        fact.authority.value.replace("_", " ")))
    if measures:
        code = next(letter)
        appendices.append(Part(number=code, heading="Measures and sources", appendix=True, blocks=(
            Block(kind="table", number=f"{code}.1", caption="Measures used in this document", source="Fact ledger",
                  table=Table(key="measures", title="Measure", columns=[
                      Column(key="kind", label="Ledger kind"), Column(key="system", label="System of record"),
                      Column(key="authority", label="Authority")],
                      rows=[Row(key=kind, label=label, cells={
                          "kind": Cell(value=kind), "system": Cell(value=system), "authority": Cell(value=authority)})
                          for kind, (label, system, authority) in sorted(measures.items())])),)))

    event_ids = sorted({event_id for f in cited_all if (event_id := facts[f].event_id)})
    events = [event for event in world.events if event.id in set(event_ids)]
    if events:
        code = next(letter)
        people = {p.id: p.name for p in world.people}
        appendices.append(Part(number=code, heading="Chronology of events", appendix=True, blocks=(
            Block(kind="table", number=f"{code}.1", caption="Events behind the cited figures", source="Event log",
                  table=Table(key="events", title="Event", columns=[
                      Column(key="when", label="When"), Column(key="kind", label="What happened"),
                      Column(key="who", label="People"), Column(key="systems", label="Systems")],
                      rows=[Row(key=e.id, label=e.id, cells={
                          "when": Cell(value=e.occurred_at.strftime("%d %b %Y %H:%M")),
                          "kind": Cell(value=e.kind.replace("_", " ").capitalize()),
                          "who": Cell(value=", ".join(people.get(a, a) for a in e.actors)),
                          "systems": Cell(value=", ".join(systems.get(s, s) for s in e.systems)),
                      }) for e in sorted(events, key=lambda item: (item.occurred_at, item.id))])),)))

    related: list[Related] = []
    slugger = slug_for or (lambda t: t.replace("_", "-"))
    irs = {item.id: item for item in world.artifact_irs}
    for fam in fams:
        if ir.id not in fam.roles():
            continue
        for artifact_id, role in fam.members:
            if artifact_id == ir.id or any(r.artifact_id == artifact_id for r in related):
                continue
            other = irs.get(artifact_id)
            if other is None:
                continue
            other_type = world.artifact_intents.by_id(other.intent_id).artifact_type
            related.append(Related(artifact_id=artifact_id, title=other.title, artifact_type=other_type,
                                   role=role, slug=slugger(other_type)))
    if related:
        code = next(letter)
        appendices.append(Part(number=code, heading="Related documents", appendix=True, blocks=(
            Block(kind="table", number=f"{code}.1", caption="Documents in the same pack", source="Document register",
                  table=Table(key="related", title="Reference", columns=[
                      Column(key="title", label="Title"), Column(key="type", label="Type"),
                      Column(key="role", label="Role in pack")],
                      rows=[Row(key=r.artifact_id, label=r.artifact_id, cells={
                          "title": Cell(value=r.title), "type": Cell(value=genre_label(r.artifact_type)),
                          "role": Cell(value=r.role)}) for r in related])),)))

    parts = [_number_figures(part) for part in parts]
    appendices = [_number_figures(part) for part in appendices]
    reviewers = tuple(p for p in (reviewer,) if p is not None and (approver is None or p.id != approver.id))
    review_at = next((r.at for r in history if r.status == "Reviewed"), revision.at)
    comments = () if revision.status == "Draft" else _comments(
        world, intent, ir, parts, reviewer, approver, review_at, family_facts, facts, systems, names)

    labels = tuple(dict.fromkeys(
        label for label in (intent.domain, intent.artifact_type.replace("_", "-"), _period_of(ir, world),
                            family.key if family else "") if label))
    return LongDocument(
        artifact_id=ir.id,
        artifact_type=intent.artifact_type,
        title=ir.title,
        subtitle=ir.subtitle or "",
        genre=genre_label(intent.artifact_type),
        company=company,
        reference=f"{world.company.id}-{intent.domain.upper()}-{ir.id}",
        classification=classification,
        audience=audience,
        period=_period_of(ir, world),
        created_at=created,
        author=author,
        approver=approver,
        reviewers=reviewers,
        revision=revision,
        history=upto,
        comments=comments,
        parts=tuple(parts),
        appendices=tuple(appendices),
        related=tuple(related),
        family=family,
        labels=labels,
        fact_ids=tuple(cited_all),
        draft=draft,
        long=intent.size_profile != "small" or intent.artifact_type in _INCORPORATES_SCHEDULES,
        metadata=dict(ir.metadata),
    )


def _number_figures(part: Part) -> Part:
    """Figures get their own sequence within each numbered section, the way
    Word's caption numbering does, so two charts over one table are
    Figure 3.1 and Figure 3.2 rather than both borrowing the table's number."""
    from dataclasses import replace

    counter = 0

    def renumber(blocks: tuple[Block, ...]) -> tuple[Block, ...]:
        nonlocal counter
        out = []
        for block in blocks:
            if block.kind == "figure":
                counter += 1
                block = replace(block, number=f"{part.number}.{counter}")
            out.append(block)
        return tuple(out)

    blocks = renumber(part.blocks)
    children = tuple(replace(child, blocks=renumber(child.blocks)) for child in part.children)
    return replace(part, blocks=blocks, children=children)


def control_rows(doc: LongDocument) -> list[tuple[str, str]]:
    """The document-control table, as ``(label, value)`` pairs, shared by
    every renderer so the Word and PDF twins list the same fields."""
    rows = [
        ("Document reference", doc.reference),
        ("Title", doc.title),
        ("Document type", doc.genre),
        ("Version", doc.revision.version),
        ("Status", doc.revision.status),
        ("Classification", doc.classification),
        ("Owner", f"{doc.author.name}, {doc.author.title}".strip(", ")),
        ("Approver", f"{doc.approver.name}, {doc.approver.title}" if doc.approver else "Not required"),
        ("Reviewers", "; ".join(f"{p.name}, {p.title}" for p in doc.reviewers) or "None"),
        ("Distribution", doc.audience),
        ("Reporting period", doc.period),
        ("Date of this version", doc.revision.at.strftime("%d %B %Y")),
    ]
    if doc.family is not None:
        rows.append(("Pack", doc.family.title))
    return rows


def history_rows(doc: LongDocument) -> list[tuple[str, str, str, str, str]]:
    return [(r.version, r.at.strftime("%d %b %Y %H:%M"), r.by.name, r.status, r.summary) for r in doc.history]


def approval_rows(doc: LongDocument) -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = [
        ("Author", doc.author.name, doc.author.title, "Prepared", next(
            (r.at.strftime("%d %b %Y") for r in doc.history if r.status == "Draft"), ""))]
    for person in doc.reviewers:
        reviewed = next((r for r in doc.history if r.status == "Reviewed"), None)
        rows.append(("Reviewer", person.name, person.title, "Reviewed" if reviewed else "Pending",
                     reviewed.at.strftime("%d %b %Y") if reviewed else ""))
    if doc.approver is not None:
        approved = next((r for r in doc.history if r.status == "Approved"), None)
        rows.append(("Approver", doc.approver.name, doc.approver.title,
                     "Approved" if approved else "Pending", approved.at.strftime("%d %b %Y") if approved else ""))
    return rows


def contents(doc: LongDocument) -> list[tuple[int, str]]:
    """``(level, label)`` for every numbered heading, in order."""
    out: list[tuple[int, str]] = []
    for part in doc.parts:
        out.append((1, part.label))
        out.extend((2, f"{child.number} {child.heading}") for child in part.children)
    out.extend((1, part.label) for part in doc.appendices)
    return out


def version_slug(revision: Revision) -> str:
    return "v" + revision.version


_SENTENCE = re.compile(r"(?<=[.!?])\s+(?=[A-Z\[])")


def sentences(text: str) -> list[str]:
    """Split prose into sentences, for slides that show one per bullet."""
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()]


def all_text_cells(table: Table) -> list[Any]:
    return [cell for row in table.rows for cell in row.cells.values()]
