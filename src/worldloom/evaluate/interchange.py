"""The corpus in the shapes another team's retrieval stack reads.

`worldloom evaluate` grades the retrievers this package ships. A team with
its own retrieval system needs the same answer key pointed at *their*
system, and that takes two things this module supplies: the exact units the
answer key is keyed by, so their index holds the passages the grading reads
fact ids off, and the evaluation set in the shape their harness already
speaks.

Everything here is a projection, never a second derivation. Passages come
from `index.passages()`, the function every built-in retriever indexes and
`worldloom search` ranks, so a passage id in an export is the id `score()`
would have retrieved. Re-chunking the documents here would hand the team a
different corpus from the one the scorecard grades, and the first symptom
would be a perfect system scoring zero because none of its ids join.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from typing import TYPE_CHECKING, Any

from .index import passages

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


def passage_records(world: World) -> list[dict[str, Any]]:
    """Every passage `evaluate` indexes, one JSON-ready record each, in index order.

    ``text`` is `Passage.text` exactly, title and heading lines included,
    because that is the string the built-in retrievers rank: a team that
    indexes ``title + text`` has indexed the title twice and is no longer
    being compared like for like. ``passage_id`` is what `evaluate
    --predictions` joins on.

    The provenance fields (``authority``, ``created_at``) are here on purpose.
    `index.py` keeps them available to an index and unused by the baseline,
    and the hard families exist to reward a system that reads them; leaving
    them out of the export would make the families unwinnable rather than
    hard. ``fact_ids`` is the grading key itself: there to debug a ranking
    against, and a system that ranks on it is reading the answer sheet.

    ``created_at`` is spelled the way every corpus file and `evals export`
    spell a timestamp (pydantic's ``Z``), not ``isoformat()``'s ``+00:00``,
    so a case's ``temporal_cutoff`` and a passage's ``created_at`` compare as
    strings as well as as datetimes.
    """
    manifest = {entry.id: entry for entry in world.artifacts}
    # Dumped once per artifact rather than per passage: a workbook can carry
    # dozens of sections, and every one of them reads the same entry.
    dumped: dict[str, dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    for passage in passages(world):
        # `passages()` skips any IR without a manifest entry, so the lookup
        # cannot miss: every passage it yields has one.
        entry = manifest[passage.artifact_id]
        wire = dumped.get(entry.id)
        if wire is None:
            wire = dumped[entry.id] = entry.model_dump(mode="json")
        records.append({
            "passage_id": passage.id,
            "artifact_id": passage.artifact_id,
            "artifact_type": entry.artifact_type,
            "title": entry.title,
            "heading": passage.heading,
            "source": entry.path,
            "authority": passage.authority.value,
            "created_at": wire["created_at"],
            "fact_ids": sorted(passage.fact_ids),
            "text": passage.text,
        })
    return records


def jsonl(records: Iterable[dict[str, Any]]) -> str:
    """*records* as JSONL: sorted keys, ASCII-escaped, one ``\\n`` per line.

    The same `json.dumps` call `evals export` has always made, so every file
    this family of commands writes is byte-stable across platforms and
    Python versions in the same way.
    """
    return "".join(json.dumps(record, sort_keys=True) + "\n" for record in records)


__all__ = ["passage_records", "jsonl"]
