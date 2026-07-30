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

from ..models import AUTHORITY_RANK, Authority, Table
from ..narrative import references
from ..render.values import format_value

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


def _table_text(table: Table) -> str:
    """A table as the flat text a naive ingester would extract from it."""
    lines = [table.title, " ".join(column.label for column in table.columns)]
    for row in table.rows:
        cells = [row.label]
        for column in table.columns:
            cell = row.cells.get(column.key)
            cells.append(format_value(cell.value, column.number_format) if cell else "")
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

    out: list[Passage] = []
    for ir in world.artifact_irs:
        entry = manifest.get(ir.id)
        if entry is None:
            continue
        for index, section in enumerate(ir.sections):
            if section.hidden and not include_hidden:
                continue
            if section.body:
                text = references.substitute(section.body, facts)
                cited = frozenset(references.referenced(section.body)) | frozenset(section.fact_ids)
            elif section.table is not None:
                text = _table_text(section.table)
                cited = frozenset(
                    cell.fact_id
                    for row in section.table.rows
                    for cell in row.cells.values()
                    if cell.fact_id
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
