"""Turning a corpus into passages a retriever can see.

A passage is one section of one artifact, carrying the provenance the manifest
already records. That provenance is deliberately *available* to the index and
deliberately *unused* by the baseline — the point of the baseline is to show what
a system that ignores it gets wrong.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from ..locales import DEFAULT as DEFAULT_LOCALE, Locale
from ..models import AUTHORITY_RANK, Authority, Table
from ..narrative import references
from ..render.values import corpus_locale, format_value

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


@dataclass(frozen=True)
class Passage:
    """One retrievable chunk, with everything the manifest knows about it."""

    id: str
    artifact_id: str
    heading: str
    text: str
    fact_ids: frozenset[str]
    authority: Authority
    created_at: datetime
    hidden: bool

    @property
    def authority_rank(self) -> int:
        return AUTHORITY_RANK[self.authority]


def table_text(table: Table, *, locale: Locale = DEFAULT_LOCALE) -> str:
    """A table as the flat text a naive ingester would extract from it.

    Public (not `_table_text`) because `stats.py` needs the identical flattening
    to build whole-document text — a table has to look the same to the word-count
    report as it does to the retriever it is also feeding, or the two would be
    silently describing different corpora.

    *locale* is the corpus's, and it belongs here for a reason that is easy to
    miss: this is not a *view* of the corpus, it is what a retriever gets asked
    to match against. An index built in Australian punctuation over a German
    corpus would fail to find `1.234,50` — the string the reader actually sees
    in the document — while reporting a healthy score against a query nobody
    would type. The index has to be spelled the way the documents are.
    """
    lines = [table.title, " ".join(column.label for column in table.columns)]
    for row in table.rows:
        cells = [row.label]
        for column in table.columns:
            cell = row.cells.get(column.key)
            cells.append(
                format_value(cell.value, column.number_format, locale=locale) if cell else ""
            )
        lines.append(" ".join(cells))
    if table.note:
        lines.append(table.note)
    return "\n".join(lines)


def passages(world: World, *, include_hidden: bool = False) -> list[Passage]:
    """Every retrievable passage in *world*.

    Hidden sections are excluded by default. A lineage appendix is machinery, and
    a retriever that answers from it is answering from something no reader would
    have found — which flatters the score without reflecting anything real.
    """
    facts = {fact.id: fact for fact in world.facts}
    manifest = {entry.id: entry for entry in world.artifacts}
    locale = corpus_locale(world)

    out: list[Passage] = []
    for ir in world.artifact_irs:
        entry = manifest.get(ir.id)
        if entry is None:
            continue
        for index, section in enumerate(ir.sections):
            if section.hidden and not include_hidden:
                continue
            if section.body:
                text = references.substitute(section.body, facts, locale=locale)
                cited = frozenset(references.referenced(section.body)) | frozenset(section.fact_ids)
            elif section.table is not None:
                text = table_text(section.table, locale=locale)
                cited = frozenset(
                    cell.fact_id
                    for row in section.table.rows
                    for cell in row.cells.values()
                    if cell.fact_id
                ) | frozenset(section.fact_ids)
            elif section.flow is not None and (section.flow.nodes or section.flow.edges):
                # A causal chain is readable content — every renderer draws it
                # — and this branch not existing meant an RCA's root-cause
                # section yielded no passage at all: the retrieval index held
                # less than the page a reader was looking at, and a question
                # about the chain graded against passages that never contained
                # it. Rendered the way `render.markdown._flow` prints it, one
                # line per edge, so what the index ranks is what a reader sees.
                labels = {node.key: node.label for node in section.flow.nodes}

                def _resolved(raw: str) -> str:
                    return references.substitute(raw, facts, locale=locale)

                lines = (
                    [
                        f"{_resolved(labels.get(edge.source, edge.source))} → "
                        f"{_resolved(labels.get(edge.target, edge.target))}"
                        + (f" ({_resolved(edge.label)})" if edge.label else "")
                        for edge in section.flow.edges
                    ]
                    if section.flow.edges
                    else [_resolved(node.label) for node in section.flow.nodes]
                )
                text = "\n".join(lines)
                cited = frozenset(
                    node.fact_id for node in section.flow.nodes if node.fact_id
                ) | frozenset(section.fact_ids)
            else:
                continue

            out.append(
                Passage(
                    id=f"{ir.id}#{index}",
                    artifact_id=ir.id,
                    heading=section.heading,
                    text=f"{ir.title}\n{section.heading}\n{text}",
                    fact_ids=cited,
                    authority=entry.authority,
                    created_at=entry.created_at,
                    hidden=section.hidden,
                )
            )
    return out


def document_texts(world: World, *, include_hidden: bool = False) -> dict[str, str]:
    """Whole-document text, one string per artifact — `stats.py`'s unit of account.

    `passages()` is deliberately section-granular because that is what a
    retriever indexes. A word-count or vocabulary report has no use for that
    granularity and every reason to avoid it: gluing `Passage.text` back together
    would repeat `ir.title` once per section, inflating every document's count by
    however many sections it has. So this walks `ir.sections` directly rather
    than going through `passages()`, and shares only the substitution and table
    flattening — the two views of "what text does this artifact contain" would
    otherwise drift the moment one changed how a table renders and the other did
    not.
    """
    facts = {fact.id: fact for fact in world.facts}
    locale = corpus_locale(world)
    out: dict[str, str] = {}
    for ir in world.artifact_irs:
        pieces = [ir.title]
        for section in ir.sections:
            if section.hidden and not include_hidden:
                continue
            if section.body:
                pieces.append(section.heading)
                pieces.append(references.substitute(section.body, facts, locale=locale))
            elif section.table is not None:
                pieces.append(section.heading)
                pieces.append(table_text(section.table, locale=locale))
        out[ir.id] = "\n".join(pieces)
    return out
