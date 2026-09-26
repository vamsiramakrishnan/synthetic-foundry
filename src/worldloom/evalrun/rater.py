"""Rating a final answer: Eval Studio's judge contract, and a rater that needs no model.

Gemini Enterprise Eval Studio grades an answer by sending one prompt to a
model: an instruction the operator wrote, then the query, the fetched
response and the golden response, then a fixed trailer asking for a float.
That contract is the only part of Eval Studio worth keeping verbatim, and
``judge_prompt`` reproduces it byte for byte (its indentation included) so a
score produced here and one produced there are answers to the same question.
The rubric per grading shape comes from ``gemini_enterprise.RUBRICS``, which
already argued why one similarity instruction grades an abstention backwards.

``parse_score`` is Eval Studio's salvage parser for what a model says back:
strip fences, strip a ``Score:`` prefix, strip the scale words so "between
0.0 and 1.0" is not read as the score, take the last number. Two things are
different here on purpose. The result is clamped to ``[0, 1]``, because Eval
Studio returns ``5`` when a rater says 5 and then averages it. And a response
with no number is an *error*, not a zero, because Eval Studio's ``score: 0``
with a populated ``scoreError`` is the one field its results doc warns about.

``GroundedRater`` is the rater this package can run without a model. It
checks the golden's figures and identifiers against the answer, and abstains
(returns an error) on shapes where a lexical check would be a lie -- causal
chains, authority resolution -- rather than emitting a number that looks like
a judgement. Anvil calls such terms judge-only and reports them ungraded,
never green; the same rule holds here.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Protocol

from .. import packkit
from ..models import EvaluationType
from .contract import EvalCase

# The judge's words are data in the prompts pack (`_data/packs/prompts/default/
# rater.json`, keys `rater.*`), and they are pinned to Gemini Enterprise Eval
# Studio's exact wording: the trailer and the default instruction are verbatim
# from its `eval.service.ts`, and the prompt reproduces its layout byte for byte,
# the four-space indentation included, so a score produced here and one produced
# there are answers to the same question. `tests/test_rater_pinned.py` pins the
# shipped text, so an operator's prompts pack may reword it on purpose (and is
# recorded doing so) but no edit changes it silently. An industry pack's words
# have no business here: parity is the operator's decision, not an industry's.

#: Eval Studio's trailer, verbatim from `eval.service.ts`. The instruction is
#: expected to set up this sentence, not contradict it. The shipped text, not
#: whatever pack is in force; `judge_prompt` reads the pack in force.
JUDGE_TRAILER: str = packkit.shipped("prompts").body.texts["rater.judge.trailer"]

#: Eval Studio's default instruction, verbatim, ellipsis included. Kept so a
#: report can say a run used the product default rather than a shape rubric.
DEFAULT_INSTRUCTION: str = packkit.shipped("prompts").body.texts["rater.judge.default_instruction"]


def judge_prompt(instruction: str, query: str, fetched: str, golden: str) -> str:
    """The exact prompt Eval Studio sends its auto-rater, including its literal indentation."""

    return packkit.text("rater.judge.prompt", instruction=instruction, query=query, fetched=fetched, golden=golden,
                        trailer=packkit.text("rater.judge.trailer"))


def rubric_for(shape: EvaluationType) -> str:
    from ..gemini_enterprise import RUBRICS

    return RUBRICS[shape]


_FENCE = re.compile(r"```[a-zA-Z]*\n?|```")
_PREFIX = re.compile(r"^\s*(?:score|rating|similarity score|similarity|final score|result)\s*[:=]\s*", re.IGNORECASE)
_SCALE = re.compile(
    r"between\s+0(?:\.0)?\s+and\s+1(?:\.0)?|0(?:\.0)?\s*(?:to|-|–)\s*1(?:\.0)?|\[\s*0\s*,\s*1\s*\]|out of\s+1(?:\.0)?|/\s*1(?:\.0)?|scale\s*0\s*-\s*1",
    re.IGNORECASE,
)
_NUMBER = re.compile(r"[0-9]+(?:\.[0-9]+)?")


def parse_score(text: str) -> tuple[float | None, str | None]:
    """Eval Studio's five-stage salvage, clamped, with "no number" as an error.

    Returns ``(score, error)``. Exactly one is ``None``.
    """

    cleaned = _FENCE.sub("", text or "").strip()
    cleaned = _PREFIX.sub("", cleaned)
    cleaned = _SCALE.sub(" ", cleaned).strip()
    try:
        value = float(cleaned)
    except ValueError:
        found = _NUMBER.findall(cleaned)
        if not found:
            return None, f"no score in rater output: {text[:80]!r}"
        value = float(found[-1])
    return max(0.0, min(1.0, value)), None


class Rater(Protocol):
    name: str

    def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]: ...


#: Shapes a lexical check cannot honestly grade. `GroundedRater` reports
#: them as errors (ungraded), so they are excluded from every mean rather
#: than scored by a heuristic that looks like a judgement.
JUDGE_ONLY = frozenset({EvaluationType.CAUSAL_MULTI_HOP, EvaluationType.AUTHORITY_RESOLUTION, EvaluationType.CITATION_REQUIRED})

_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_-]{2,}|[0-9][0-9,.%]*")
_ABSTAIN = re.compile(r"\b(cannot|can't|unable|no (record|information|data)|not (found|available|present)|does not (contain|hold))\b", re.IGNORECASE)


def _figures(text: str) -> set[str]:
    return {token.rstrip(".,").replace(",", "") for token in _TOKEN.findall(text) if token[0].isdigit()}


def _identifiers(text: str) -> set[str]:
    return {token for token in _TOKEN.findall(text) if not token[0].isdigit() and any(ch.isdigit() or ch == "-" for ch in token)}


class GroundedRater:
    """Score an answer by the golden's figures and identifiers, without a model.

    Direct lookups and comparisons are graded on whether every figure in the
    golden appears in the answer. Abstention cases are graded on whether the
    answer refuses and carries none of the golden's would-be figures. Shapes
    in ``JUDGE_ONLY`` are returned as errors: ungraded, never passed.
    """

    name = "grounded"
    kind = "grounded"

    def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
        contract = case.outcomes.answer
        if contract is None:
            return None, "case has no answer contract"
        if contract.rubric in JUDGE_ONLY:
            return None, f"{contract.rubric} needs a model rater; not graded"
        golden_figures = _figures(contract.golden) | _identifiers(contract.golden)
        answer_figures = _figures(answer) | _identifiers(answer)
        if contract.expects_abstention or contract.rubric is EvaluationType.EXPECTED_ABSTENTION:
            refused = bool(_ABSTAIN.search(answer))
            invented = bool(answer_figures - golden_figures)
            return (1.0 if refused and not invented else 0.0), None
        if not golden_figures:
            return None, "golden carries no figure or identifier to check"
        hit = len(golden_figures & answer_figures) / len(golden_figures)
        return round(hit, 4), None


def model_rater(complete: Callable[[str], str], *, model: str, name: str | None = None) -> Rater:
    """Wrap any ``prompt -> text`` completion as a rater using Eval Studio's prompt.

    The caller supplies the model call; this package never does. The rubric
    is the shape's, from ``gemini_enterprise.RUBRICS``, so the judge is told
    what *this* shape counts as correct rather than asked for similarity.
    ``model`` names the judge model the completion calls (``gemini-2.5-pro``)
    and is part of the grader's identity: two judge models are two graders,
    and a loop pinned to one must refuse the other. ``name`` defaults to
    ``model:<model>``.
    """

    if not isinstance(model, str) or not model.strip():
        raise ValueError("model_rater names no model: pass model=<the judge model the completion calls>")
    judge_model = model.strip()

    class _ModelRater:
        kind = "model"

        def __init__(self) -> None:
            self.name = name or f"model:{judge_model}"
            # Read by `grader.grader_identity`, which refuses a model rater without it.
            self.model = judge_model

        def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
            contract = case.outcomes.answer
            if contract is None:
                return None, "case has no answer contract"
            prompt = judge_prompt(rubric_for(contract.rubric), case.query, answer, contract.golden)
            try:
                text = complete(prompt)
            except Exception as error:  # a rater outage is a scoreError, not a zero
                return None, f"rater failed: {error}"
            return parse_score(text)

    return _ModelRater()


RATING_SCHEMA = "worldloom.evalrun-rating/v1"


def exec_rater(command: str, *, timeout: float | None = None, shell: bool = False, name: str | None = None) -> Rater:
    """The judge as an executable over the ``--exec`` seam: one subprocess per answer.

    The child receives a ``worldloom.evalrun-rating/v1`` document on stdin:
    the assembled Eval Studio prompt (rubric for the case's shape, query,
    fetched answer, golden), plus its parts, and prints ``{"score": 0.85}``
    or ``{"text": "<what the model said>"}`` for ``parse_score`` to salvage.
    A child that exits non-zero, prints something else, or overruns the
    timeout is a rating *error* on that case, excluded from every mean, with
    its stderr tail in the message. No model SDK is imported here; the child
    owns the vendor, the key and the retry budget.
    """

    from ..execseam import DEFAULT_TIMEOUT, ExecError, run_exec

    class _ExecRater:
        kind = "exec"

        def __init__(self) -> None:
            self.name = name or f"exec:{command.split()[0] if command.split() else command}"
            # Read by `grader.grader_identity`, which records the command with
            # anything that looks like a credential redacted.
            self.command = command
            self.shell = shell

        def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
            contract = case.outcomes.answer
            if contract is None:
                return None, "case has no answer contract"
            instruction = rubric_for(contract.rubric)
            payload = {
                "schema": RATING_SCHEMA, "case_id": case.id, "query": case.query,
                "rubric": contract.rubric.value, "instruction": instruction,
                "fetched": answer, "golden": contract.golden,
                "prompt": judge_prompt(instruction, case.query, answer, contract.golden),
                "instructions": packkit.texts("rater.exec.rule."),
            }
            try:
                reply = run_exec(command, payload, timeout=DEFAULT_TIMEOUT if timeout is None else timeout, shell=shell)
            except ExecError as error:
                tail = getattr(error, "stderr_tail", "")
                return None, f"{error.code}: {error}" + (f" | {tail.strip()}" if tail else "")
            document = reply.document
            if isinstance(document.get("score"), (int, float)) and not isinstance(document.get("score"), bool):
                return max(0.0, min(1.0, float(document["score"]))), None
            if isinstance(document.get("text"), str):
                return parse_score(document["text"])
            return None, "exec_unparseable: the rater's reply has neither `score` nor `text`"

    return _ExecRater()


__all__ = [
    "DEFAULT_INSTRUCTION",
    "RATING_SCHEMA",
    "exec_rater",
    "JUDGE_ONLY",
    "JUDGE_TRAILER",
    "GroundedRater",
    "Rater",
    "judge_prompt",
    "model_rater",
    "parse_score",
    "rubric_for",
]
