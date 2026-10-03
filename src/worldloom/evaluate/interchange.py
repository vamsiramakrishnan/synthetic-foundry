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

The evaluation set goes out in two harnesses' own shapes as well. ragas gets
the passages a case's answer rests on as its reference contexts; promptfoo
gets substring assertions only, because an assertion that needed a model to
grade would put a judge inside the measurement, which `score.py` exists to
keep out. A case no substring can honestly check is left out and counted,
never exported with nothing to fail.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Sequence
from typing import TYPE_CHECKING, Any

from ..generators.cases import magnitude
from ..models import EvaluationType
from ..narrative.references import exact_value
from ..render.values import corpus_locale
from .index import Passage, passages

if TYPE_CHECKING:  # pragma: no cover
    from ..locales import Locale
    from ..models import CanonicalFact, EvaluationCase
    from ..world import World

#: What `evals export --format` writes. ``worldloom`` is the evaluation set as
#: it has always been exported; the others are projections of it.
EXPORT_FORMATS: tuple[str, ...] = ("worldloom", "ragas", "promptfoo")

#: A figure spelled with fewer digits than this gets no assertion. A
#: one-business-day delay is a real expected value, but ``contains "1"``
#: passes nearly any answer that mentions a date, and an assertion that
#: cannot fail is a test that reports a pass it did not measure.
MIN_FIGURE_DIGITS = 2

#: A text value longer than this many words gets no assertion. A status
#: (``delayed``), an owner (``unassigned``) or a hypothesis's name (``Overnight
#: ERP outage``) is what a correct answer states verbatim; a root-cause
#: sentence is what a correct answer paraphrases, and a substring check on it
#: would fail right answers for their wording.
MAX_TEXT_WORDS = 4

#: The first figure in a spelled value: digits, and between them the group and
#: decimal marks locales spell with (comma, point, apostrophe, plain, no-break
#: and narrow no-break spaces). Read off `references.exact_value` rather than
#: re-spelled here, so the precision rules per unit stay in one place.
_FIGURE = re.compile(r"\d(?:[\d.,'\u00a0\u202f ]*\d)?")


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


# ---------------------------------------------------------------------------
# ragas: the evaluation set as SingleTurnSample rows
# ---------------------------------------------------------------------------


def reference_passages(case: EvaluationCase, pool: Sequence[Passage]) -> list[Passage]:
    """The passages *case*'s answer rests on, in index order.

    The passages carrying any expected fact — the key `_covers` grades with —
    narrowed to the case's `required_artifact_ids` when it names any, which is
    what keeps the superseded triage page out of a confirmed-cause case's
    references. A `temporal_state` case keeps only passages written by its
    cut-off, the one family `score.grade()` holds to the cut-off; one whose
    evidence was all written later gets none, because no passage answers it
    as of when it is asked. An abstention case gets none by definition.
    """
    if case.expects_abstention:
        return []
    expected = set(case.expected_fact_ids)
    carriers = [passage for passage in pool if expected & passage.fact_ids]
    if case.required_artifact_ids:
        required = set(case.required_artifact_ids)
        carriers = [passage for passage in carriers if passage.artifact_id in required]
    cutoff = case.temporal_cutoff
    if case.evaluation_type is EvaluationType.TEMPORAL_STATE and cutoff is not None:
        carriers = [passage for passage in carriers if passage.created_at <= cutoff]
    return carriers


def _case_metadata(case: EvaluationCase) -> dict[str, Any]:
    """What a harness needs to slice results by family and to read why a case
    grades the way it does. The cut-off in the corpus files' spelling."""
    return {
        "evaluation_type": case.evaluation_type.value,
        "difficulty": case.difficulty,
        "expects_abstention": case.expects_abstention,
        "expected_answer": case.expected_answer,
        "expected_fact_ids": list(case.expected_fact_ids),
        "required_artifact_ids": list(case.required_artifact_ids),
        "temporal_cutoff": case.model_dump(mode="json")["temporal_cutoff"],
    }


def ragas_records(world: World) -> list[dict[str, Any]]:
    """One ragas ``SingleTurnSample`` row per case, in evaluation-set order.

    ``user_input`` is the question and ``reference`` the expected answer.
    ``reference_contexts`` and ``reference_context_ids`` are the texts and
    ids of `reference_passages()`, so ragas's context metrics compare a
    system's retrieved contexts against the passages this corpus's own
    grading would credit, and its id-based ones join on the same passage ids
    `evaluate --predictions` reads. ``id`` and ``metadata`` are for joining
    scores back; ragas builds a sample from the keys it knows and ignores
    these two.
    """
    pool = passages(world)
    records = []
    for case in world.evaluations:
        references = reference_passages(case, pool)
        records.append({
            "id": case.id,
            "user_input": case.question,
            "reference": case.expected_answer,
            "reference_contexts": [passage.text for passage in references],
            "reference_context_ids": [passage.id for passage in references],
            "metadata": _case_metadata(case),
        })
    return records


# ---------------------------------------------------------------------------
# promptfoo: test cases whose assertions need no model
# ---------------------------------------------------------------------------


def _figure_assertion(fact: CanonicalFact, answer: str, locale: Locale) -> dict[str, str] | None:
    """``contains`` the figure, when the expected answer states it.

    Found in the answer by the spelling the answer key wrote it in
    (`generators.cases.magnitude`, sign dropped as "below budget" drops it),
    and asserted in the spelling the exported passages use, the corpus
    locale's digits, because that is what a system quoting the corpus says.
    Bounded on both sides so ``7,022`` is not found inside ``17,022``.
    """
    if fact.value is None:
        return None
    stated = magnitude(abs(fact.value.amount))
    if not re.search(rf"(?<![\d.,]){re.escape(stated)}(?![\d]|[.,]\d)", answer):
        return None
    match = _FIGURE.search(exact_value(fact, locale=locale))
    if match is None or sum(ch.isdigit() for ch in match.group()) < MIN_FIGURE_DIGITS:
        return None
    return {"type": "contains", "value": match.group()}


def _text_assertion(fact: CanonicalFact, answer: str) -> dict[str, str] | None:
    """``icontains`` a short text value, when the expected answer states it as a whole word run."""
    value = (fact.text_value or "").strip()
    if not value or len(value.split()) > MAX_TEXT_WORDS:
        return None
    if not re.search(rf"(?<!\w){re.escape(value.casefold())}(?!\w)", answer.casefold()):
        return None
    return {"type": "icontains", "value": value}


def assertions(case: EvaluationCase, facts: dict[str, CanonicalFact], locale: Locale) -> list[dict[str, str]]:
    """The substring checks a correct answer to *case* must pass, in fact order.

    Only values the expected answer itself states. A case's expected facts
    are what grading needs, not what the answer says: "which unit had the
    largest adverse variance" needs all four units' variances and states one,
    and asserting the other three would fail the right answer. Nothing for an
    abstention case: absence is not a substring.

    And never a value the question already contains, compared the way
    promptfoo compares, as a plain case-insensitive substring. Running the
    export through promptfoo with a provider that echoes the prompt caught
    it: "What was the close status once the period was finalised?" passed
    ``icontains "final"`` by repeating the question.
    """
    answer = case.expected_answer or ""
    if case.expects_abstention or not answer:
        return []
    question = case.question.casefold()
    out: list[dict[str, str]] = []
    for fact_id in case.expected_fact_ids:
        fact = facts.get(fact_id)
        if fact is None:
            continue
        assertion = (_figure_assertion(fact, answer, locale) if fact.value is not None
                     else _text_assertion(fact, answer))
        if assertion is None or assertion in out or assertion["value"].casefold() in question:
            continue
        out.append(assertion)
    return out


def promptfoo_tests(world: World) -> tuple[list[dict[str, Any]], list[str]]:
    """promptfoo test cases, and the ids of the cases left out.

    ``description`` is the case id, ``vars.question`` the question, ``assert``
    the case's `assertions()` and ``metadata`` the rest. A case with no
    assertion is left out rather than exported with an empty list, because
    promptfoo passes a test that asserts nothing and the pass rate would count
    it. That leaves out every abstention case and every answer stated only in
    prose or by a name the fact ledger does not hold as a value.
    """
    facts = {fact.id: fact for fact in world.facts}
    locale = corpus_locale(world)
    tests: list[dict[str, Any]] = []
    left_out: list[str] = []
    for case in world.evaluations:
        checks = assertions(case, facts, locale)
        if not checks:
            left_out.append(case.id)
            continue
        tests.append({
            "description": case.id,
            "vars": {"question": case.question},
            "assert": checks,
            "metadata": {"case_id": case.id, **_case_metadata(case)},
        })
    return tests, left_out


__all__ = [
    "EXPORT_FORMATS",
    "MIN_FIGURE_DIGITS",
    "MAX_TEXT_WORDS",
    "passage_records",
    "jsonl",
    "reference_passages",
    "ragas_records",
    "assertions",
    "promptfoo_tests",
]
