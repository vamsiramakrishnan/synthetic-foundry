"""Grading a ranking another team's system wrote down.

`evaluate --predictions FILE` scores a retrieval system this package never
ran. The file holds one JSON object per line, one line per case, rankings
best first::

    {"id": "EVAL-0001", "passage_ids": ["ART-0002#1", "ART-0003#0"]}
    {"id": "EVAL-0032", "abstain": true}

A prediction is just another retriever's ranking, so it is graded by
`score.grade()`, the function every built-in retriever is graded by: the
same coverage, temporal and authority rules, the same *k*, the same
per-family scorecard. What a file cannot carry is scores, so abstention is
read from the line rather than from a floor calibrated on scores: an
abstention case passes when the line abstains or ranks nothing, and an
answerable case the line abstains on fails. That is `benchmark run`'s rule,
the other place an outside system's answer is graded here.

Two granularities, one per file. ``passage_ids`` name the passages `evals
passages` exports. ``artifact_ids`` are for a system that ranks whole
documents; each artifact is then one unit carrying every fact its passages
carry, written when the artifact was, at its authority. That unit is built
by merging the same passages, never by chunking anything again.

The file is held to its contract strictly, because the failures it rules out
are silent ones. A typo'd key (``passage_id``) would read as an empty
ranking and *pass* every abstention case; an id from another corpus or an
older build would carry no facts and fail cases for a reason that is not
retrieval. Both refuse instead, naming the line or the ids.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from .index import Passage, passages
from .score import DEFAULT_K, Retrieval, Scorecard, grade

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World

Granularity = Literal["passage", "artifact"]

#: The keys a line may carry. ``metadata`` is the one place for anything a
#: team wants to keep beside a ranking (scores, latency, a run id); it is read
#: by nothing. Every other key is refused rather than ignored — see the
#: module docstring for the typo this exists to catch.
KEYS = ("id", "passage_ids", "artifact_ids", "abstain", "metadata")

#: What a refusal tells the caller to do about each code. Here rather than in
#: the CLI so the SDK caller who catches `PredictionsError` gets the same fix.
_FIXES = {
    "predictions_unreadable": (
        'write one JSON object per line: {"id": "EVAL-0001", "passage_ids": [...ranked...]}'
        ' or "artifact_ids" (one kind per file), optionally "abstain": true'
    ),
    "predictions_unknown_ids": (
        "rank the passages `worldloom evals passages` exports and answer the case ids"
        " `worldloom evals export` lists, both from this corpus: ids from another corpus"
        " or an earlier build do not join"
    ),
}

#: How many unknown ids the message names before summarising. All of them
#: still ride in the error's data.
_NAMED = 5


class PredictionsError(ValueError):
    """The predictions file breaks its contract.

    ``code`` is a key of the CLI's refusal registry and ``data`` rides in its
    JSON envelope — the shape `execseam.ExecError` already gives the CLI, so
    this module stays importable without typer.
    """

    def __init__(self, code: str, message: str, **data: Any) -> None:
        super().__init__(message)
        self.code = code
        self.fix = _FIXES[code]
        self.data = data


@dataclass(frozen=True)
class Prediction:
    """One line: a case, its ranking (duplicates collapsed), and whether it abstained."""

    case_id: str
    ranked: tuple[str, ...]
    abstain: bool


@dataclass(frozen=True)
class Predictions:
    """A parsed predictions file."""

    granularity: Granularity
    by_case: dict[str, Prediction]


@dataclass(frozen=True)
class PredictionScore:
    """A predictions file graded: the scorecard, and the cases it never answered."""

    card: Scorecard
    granularity: Granularity
    missing: tuple[str, ...] = ()
    """Case ids with no line, in evaluation-set order. Each is a failure in
    `card`; listed here as well so a reader can tell an unanswered case from
    a wrong answer without reading every outcome's detail."""


def parse(text: str) -> Predictions:
    """Read a predictions file's contents, refusing the first line that breaks the contract."""
    by_case: dict[str, Prediction] = {}
    lines_by_case: dict[str, int] = {}
    granularity: Granularity | None = None
    granularity_line = 0

    # Split on "\n" alone, not `splitlines()`: JSONL separates records with a
    # newline, and `splitlines()` also breaks on U+2028 and friends, which a
    # writer that does not escape non-ASCII may leave inside a string value.
    for number, raw in enumerate(text.split("\n"), start=1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise _unreadable(number, f"not JSON ({exc.msg})") from None
        if not isinstance(row, dict):
            raise _unreadable(number, f"a line must be a JSON object, got {type(row).__name__}")
        unknown = sorted(set(row) - set(KEYS))
        if unknown:
            raise _unreadable(number, f"unknown key(s) {unknown}; a line takes {list(KEYS)}")

        case_id = row.get("id")
        if not isinstance(case_id, str) or not case_id:
            raise _unreadable(number, '"id" must be a non-empty string naming an evaluation case')
        if case_id in lines_by_case:
            raise _unreadable(number, f"{case_id} was already predicted on line {lines_by_case[case_id]}")

        abstain = row.get("abstain", False)
        if not isinstance(abstain, bool):
            raise _unreadable(number, '"abstain" must be true or false')

        kinds = [key for key in ("passage_ids", "artifact_ids") if key in row]
        if len(kinds) > 1:
            raise _unreadable(number, 'give "passage_ids" or "artifact_ids", not both')
        if not kinds and not abstain:
            raise _unreadable(number, 'give a ranking ("passage_ids" or "artifact_ids"), or "abstain": true')

        ranked: tuple[str, ...] = ()
        if kinds:
            key = kinds[0]
            ids = row[key]
            if not isinstance(ids, list) or not all(isinstance(i, str) and i for i in ids):
                raise _unreadable(number, f'"{key}" must be a list of non-empty strings, best first')
            # First occurrence wins, before the cut at k. A document-level
            # ranking derived from passage hits repeats an artifact once per
            # hit, and letting the repeats spend slots would grade the
            # derivation, not the retrieval.
            ranked = tuple(dict.fromkeys(ids))
            kind: Granularity = "passage" if key == "passage_ids" else "artifact"
            if granularity is None:
                granularity, granularity_line = kind, number
            elif kind != granularity:
                raise _unreadable(number, f"line {granularity_line} ranks {granularity}s and this"
                                          f" line ranks {kind}s; one file is one granularity")

        by_case[case_id] = Prediction(case_id, ranked, abstain)
        lines_by_case[case_id] = number

    if not by_case:
        raise PredictionsError("predictions_unreadable", "the file holds no predictions", line=0)
    # A file of nothing but abstentions names no granularity; passages is the
    # unit every built-in retriever ranks, and with no ids to resolve the
    # choice changes no grade.
    return Predictions(granularity or "passage", by_case)


def artifact_units(world: World, pool: Sequence[Passage]) -> list[Passage]:
    """One unit per artifact, for grading a ranking of whole documents.

    Merged from *pool*, not re-chunked: a unit carries every fact its
    artifact's passages carry, and the time and authority they already share
    (`index.passages()` stamps both from the manifest entry). Artifacts in the
    manifest with no retrievable passage are units too, carrying nothing: a
    system that indexed the rendered files can return one legitimately, and
    refusing it as unknown would blame the system for the corpus's shape.
    """
    members: dict[str, list[Passage]] = {}
    for passage in pool:
        members.setdefault(passage.artifact_id, []).append(passage)
    units: list[Passage] = []
    for entry in world.artifacts:
        parts = members.get(entry.id, [])
        units.append(Passage(
            id=entry.id,
            artifact_id=entry.id,
            heading="",
            text="\n\n".join(part.text for part in parts),
            fact_ids=frozenset().union(*(part.fact_ids for part in parts)),
            authority=entry.authority,
            created_at=entry.created_at,
            hidden=False,
        ))
    return units


def score_predictions(
    world: World, predictions: Predictions, *, k: int = DEFAULT_K, label: str = "predictions"
) -> PredictionScore:
    """Grade *predictions* against *world*'s evaluation set, labelled *label*.

    Every id is resolved before anything is graded, and one that does not
    resolve refuses the whole file: a scorecard over the cases that happened
    to join would be a score for a different evaluation set.
    """
    pool = passages(world)
    if not pool:
        # `score()`'s sentence for the same state, so the CLI maps both to one code.
        raise ValueError("nothing to retrieve from — render or compile the corpus first")
    units = pool if predictions.granularity == "passage" else artifact_units(world, pool)
    by_id = {unit.id: unit for unit in units}
    cases = list(world.evaluations)

    known = {case.id for case in cases}
    unknown_cases = sorted(set(predictions.by_case) - known)
    unknown_ids = sorted({
        identifier
        for prediction in predictions.by_case.values()
        for identifier in prediction.ranked
        if identifier not in by_id
    })
    if unknown_cases or unknown_ids:
        parts = []
        if unknown_cases:
            parts.append(f"{len(unknown_cases)} case id(s) not in this evaluation set"
                         f" ({_named(unknown_cases)})")
        if unknown_ids:
            parts.append(f"{len(unknown_ids)} {predictions.granularity} id(s) not in this corpus"
                         f" ({_named(unknown_ids)})")
        raise PredictionsError(
            "predictions_unknown_ids", "; ".join(parts),
            unknown_case_ids=unknown_cases, unknown_ids=unknown_ids,
            granularity=predictions.granularity,
        )

    unit = predictions.granularity
    retrievals: list[Retrieval | None] = []
    missing: list[str] = []
    for case in cases:
        prediction = predictions.by_case.get(case.id)
        if prediction is None:
            missing.append(case.id)
            retrievals.append(None)
            continue
        found = tuple(by_id[identifier] for identifier in prediction.ranked[:k])
        if prediction.abstain:
            detail = "abstained, as expected"
        elif not found:
            detail = "returned nothing, as expected"
        else:
            detail = f"returned {len(found)} {unit}(s) where abstention was expected"
        # Ranking nothing is staying quiet, which is what an abstention case
        # asks for; on an answerable case it is only an empty ranking, graded
        # as one. An explicit abstain is a decline on either.
        abstained = prediction.abstain or (case.expects_abstention and not found)
        retrievals.append(Retrieval(found, abstained, detail))

    card = grade(units, cases, retrievals, k=k, retriever=label)
    return PredictionScore(card, predictions.granularity, tuple(missing))


def _unreadable(line: int, reason: str) -> PredictionsError:
    return PredictionsError("predictions_unreadable", f"line {line}: {reason}", line=line)


def _named(ids: list[str]) -> str:
    shown = ", ".join(ids[:_NAMED])
    return shown if len(ids) <= _NAMED else f"{shown}, +{len(ids) - _NAMED} more"


__all__ = [
    "KEYS",
    "Granularity",
    "Prediction",
    "Predictions",
    "PredictionScore",
    "PredictionsError",
    "parse",
    "artifact_units",
    "score_predictions",
]
