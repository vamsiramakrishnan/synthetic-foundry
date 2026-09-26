"""Graded runs as training data: demonstrations, preference pairs, verifiable rewards.

A run ledger already holds everything a trainer asks for. Each case has the
request, every call that reached a connector with its arguments and result
(the spans), every question asked with the reply and the position it was
asked at, every call the surface refused, the final answer, and a grade on
three axes. What it does not hold is the *shape* a trainer reads: a chat
transcript, a chosen and a rejected continuation of one prompt, a scalar
reward with its parts. This module is that reading and nothing more. It
grades nothing and re-derives no score: a record says what the ledger says.

Three exports:

- ``sft_records``: one chat transcript per qualifying case, rebuilt in the
  order the service recorded it (spans by ordinal, questions interleaved at
  the span count they were asked after, refusals as tool errors), ending with
  the answer. A demonstration is only worth training on when it was good, so
  a case qualifies on its score and, by default, on passing.
- ``preference_pairs``: two runs of one case set, paired by case id, the
  higher overall score chosen when it leads by at least the margin. Two runs
  measured by different graders are not comparable, and are refused rather
  than paired.
- ``reward_records``: the grade as a reward, with the deterministic parts (the
  state diff, collateral, grounding, the safety laws, the designed failures)
  kept apart from the model-rated answer, so a trainer can reward on what a
  program checked and nothing a model judged.

The leakage guard: a case set compiled by the dataset compiler carries a
split. Training on a held-out row (``test``, ``holdout`` or ``validation``,
the set ``evalrun.splits`` owns) makes every later promotion decision over
that row meaningless, so the exporter keeps ``train`` by default and refuses
a held-out split unless it is asked for by name with ``include_holdout``. A
run can be held out as a whole: the improve loop holds cases back by hash,
so they carry no split, and marks the run it made over them
(``RunReport.split``). Such a run is refused outright without
``include_holdout``, whatever its cases say. A case set without splits, in a
run nobody sealed, has nothing to guard.

Output order is case id, and the JSONL writer pins key order and newlines,
so one ledger always exports to the same bytes.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .. import packkit
from ..ids import content_key
from .contract import EvalCase
from .grading import CaseScore, OutcomeGrade
from .runner import CaseResult, RunReport, case_set_digest
from .splits import HELD_OUT_SPLITS, declared_split, is_held_out

SFT_SCHEMA = "worldloom.trace-export.sft/v1"
PAIR_SCHEMA = "worldloom.trace-export.pair/v1"
REWARD_SCHEMA = "worldloom.trace-export.reward/v1"

FORMATS = ("sft", "pairs", "rewards")

#: The split every export keeps when none is asked for.
TRAIN_SPLIT = "train"
#: Splits an export refuses unless ``include_holdout`` is given: promotion is
#: decided on them, and a model trained on them has seen the exam. The one
#: set every part of evalrun reads (``evalrun.splits``), so ``validation`` is
#: sealed here exactly as the improve loop seals it.
HOLDOUT_SPLITS = HELD_OUT_SPLITS

AXES = ("plan", "trajectory", "outcomes")


class ExportRefused(ValueError):
    """The export would be wrong, not merely empty: the message says why."""


class HoldoutRefused(ExportRefused):
    """A holdout split was asked for without ``include_holdout``."""


def max_result_chars() -> int:
    """Characters of one tool result kept in a transcript: the policy ``evalrun.export.max_result_chars``.

    A search page of five hundred records is a legitimate span and a useless
    training token budget. The cap truncates with a marker that states what
    was cut, so a reader of the record knows the result was longer.
    """
    return int(packkit.policy("evalrun.export.max_result_chars"))


def default_margin() -> float:
    """The smallest overall-score lead a preference pair is built on: ``evalrun.delta_band``.

    The same band ``compare`` calls stable. A pair inside it would teach a
    preference the comparison itself does not report as a difference.
    """
    from .results import delta_band

    return delta_band()


# -- cases, splits and identity ---------------------------------------------------


def _by_id(cases: Iterable[EvalCase] | Mapping[str, EvalCase]) -> dict[str, EvalCase]:
    if isinstance(cases, Mapping):
        return dict(cases)
    return {case.id: case for case in cases}


def case_split(result: CaseResult | None, case: EvalCase | None, report: RunReport | None = None) -> str | None:
    """The dataset split a case belongs to, as ``evalrun.splits`` resolves it, else its run's.

    The case's dimensions, its row, the row's ``dimensions``, then the
    result's dimensions; a case that names none is in the split its run was
    made on (``RunReport.split``), when the run names one.
    """
    found = declared_split(case, result)
    if found is None and report is not None and report.split:
        return str(report.split)
    return found


@dataclass
class SplitFilter:
    """Which splits an export keeps, and a count of what it withheld."""

    splits: tuple[str, ...] | None = None
    include_holdout: bool = False
    withheld: Counter[str] = field(default_factory=Counter)

    def __post_init__(self) -> None:
        asked = set(self.splits or ())
        holdout = sorted(asked & HOLDOUT_SPLITS)
        if holdout and not self.include_holdout:
            raise HoldoutRefused(
                f"split {', '.join(holdout)} is a holdout: promotion is decided on it, and a model trained on it "
                "has seen the exam, so every later promotion over it is void; pass include_holdout "
                "(--include-holdout) only for a set that will never be used to promote")

    def keeps(self, split: str | None) -> bool:
        if split is None:
            # An unsplit set has no holdout to leak; every case is training data.
            return True
        if self.splits is not None:
            kept = split in self.splits
        else:
            kept = self.include_holdout or split == TRAIN_SPLIT
        if not kept:
            self.withheld[split] += 1
        return kept

    def explain(self) -> str | None:
        """Why cases were withheld, for the operator; None when none were."""
        if not self.withheld:
            return None
        counts = ", ".join(f"{count} {split}" for split, count in sorted(self.withheld.items()))
        held = sorted(split for split in self.withheld if split in HOLDOUT_SPLITS)
        why = (" (training on holdout rows invalidates promotion; --include-holdout overrides)" if held
               else "")
        return f"withheld {counts} case(s) outside the exported split(s){why}"


def _check_run_split(report: RunReport, guard: SplitFilter) -> None:
    """A run made on a held-out split is refused whole unless ``include_holdout``.

    Its cases may carry no split at all (the improve loop holds cases back
    by hash), so a per-case filter would read every one of them as training
    data; the run's own mark is the only thing that says otherwise.
    """
    if is_held_out(report.split) and not guard.include_holdout:
        raise HoldoutRefused(
            f"run by {report.agent!r} was made on the held-out split {report.split!r}: promotion is decided on it, "
            "and a model trained on it has seen the exam; pass include_holdout (--include-holdout) only for a "
            "set that will never be used to promote")


def _check_case_set(report: RunReport, cases: Mapping[str, EvalCase]) -> None:
    """The run was over these cases, or the export is refused.

    Two digests are accepted: one over the cases the run holds, in its order
    (a run cut short with ``--limit``), and one over the whole set in its own
    order (an import that matched only some rows). Anything else is a ledger
    being read against the wrong corpus, whose personas and splits are not
    the ones the run saw.
    """
    missing = sorted({result.case_id for result in report.results} - set(cases))
    if missing:
        raise ExportRefused(f"run by {report.agent!r} holds {len(missing)} case(s) this corpus does not, e.g. {missing[0]!r}")
    ran = case_set_digest(cases[result.case_id] for result in report.results)
    if report.case_set not in (ran, case_set_digest(cases.values())):
        raise ExportRefused(f"run by {report.agent!r} was not over this corpus's case set "
                            f"({report.case_set[:12]} is neither {ran[:12]} nor the whole set's digest)")


def _digest(block: Mapping[str, Any] | None) -> str | None:
    if not block:
        return None
    value = block.get("digest")
    return str(value) if value else None


# -- transcripts -----------------------------------------------------------------


def _dumps(value: Any) -> str:
    return json.dumps(value, sort_keys=True, ensure_ascii=False, default=str)


def _bounded(text: str, cap: int) -> str:
    if len(text) <= cap:
        return text
    return f"{text[:cap]}...[truncated {len(text) - cap} of {len(text)} characters]"


def agent_system_text(agent_pack: Mapping[str, Any] | None, *, roots: Sequence[str | Path] = ()) -> str | None:
    """The system text of the agent pack a run names, when it resolves to the same digest.

    Read from the resolved body's ``system`` (a string or a list of lines). A
    pack that no longer resolves, or resolves to different content than the
    run recorded, is omitted: a demonstration under a system prompt the agent
    never saw would teach the wrong conditional.
    """
    if not agent_pack or not agent_pack.get("ref"):
        return None
    try:
        resolved = packkit.resolve(str(agent_pack["ref"]), kind_name="agent", roots=roots)
    except (KeyError, LookupError, ValueError, OSError, TypeError):
        return None
    recorded = _digest(agent_pack)
    if recorded is not None and resolved.digest != recorded:
        return None
    system = resolved.data.get("system")
    if isinstance(system, str) and system.strip():
        return system
    if isinstance(system, list) and system and all(isinstance(line, str) for line in system):
        return "\n".join(system)
    return None


def _system_message(system_text: str | None) -> dict[str, Any]:
    from .harness import turn_instructions

    rules = "\n".join(f"- {rule}" for rule in turn_instructions())
    content = f"{system_text.strip()}\n\n{rules}" if system_text else rules
    return {"role": "system", "content": content}


def _user_message(query: str, persona: str) -> dict[str, Any]:
    content = f"{query}\n\n(Asked by: {persona})" if persona else query
    return {"role": "user", "content": content}


def _tool_call(call_id: str, tool: str, arguments: Mapping[str, Any]) -> dict[str, Any]:
    return {"role": "assistant", "content": "", "tool_calls": [
        {"id": call_id, "type": "function", "function": {"name": tool, "arguments": _dumps(dict(arguments))}}]}


def _tool_reply(call_id: str, tool: str, content: str) -> dict[str, Any]:
    return {"role": "tool", "tool_call_id": call_id, "name": tool, "content": content}


def continuation(result: CaseResult, *, cap: int | None = None) -> tuple[list[dict[str, Any]], list[str]]:
    """The agent's side of one case, in recorded order, and the order as labels.

    Spans come by ordinal. A question carries ``index``, the number of spans
    recorded before it was asked, so it goes in front of span ``index + 1``.
    A refusal carries only the tool, its argument names and the error; the
    service does not record where it fell among the spans, so a refusal
    without an ``index`` goes after the last span, before the answer, and the
    labels say ``refused`` so a reader knows its place is not measured. The
    refused call's argument values were never recorded either; its names are
    kept with null values.

    Ties: a question and a refusal can share a span index, and the service
    records them in two separate lists with no sequence across the two, so
    their true order at that index is not on the ledger. The rule is fixed
    rather than guessed: at one index, questions first, then refusals, each
    list in the order it was recorded. The labels in ``order`` make the
    choice visible to a reader of the record.
    """
    limit = max_result_chars() if cap is None else cap
    spans = sorted(result.spans, key=lambda span: int(span.get("ordinal") or 0))
    by_index: dict[int, list[tuple[str, dict[str, Any]]]] = {}
    for question in result.questions:
        by_index.setdefault(int(question.get("index", len(spans))), []).append(("ask", dict(question)))
    for number, refusal in enumerate(result.refusals, start=1):
        position = int(refusal["index"]) if isinstance(refusal.get("index"), int) else len(spans)
        by_index.setdefault(position, []).append(("refused", {**dict(refusal), "_n": number}))
    messages: list[dict[str, Any]] = []
    order: list[str] = []

    def interleave(position: int) -> None:
        for kind, item in by_index.pop(position, ()):
            if kind == "ask":
                messages.append({"role": "assistant", "content": str(item.get("question", ""))})
                messages.append({"role": "user", "content": str(item.get("reply", ""))})
                order.append(f"ask:{item.get('id', '')}")
            else:
                call_id = f"refused_{item['_n']}"
                tool = str(item.get("tool", ""))
                names = item.get("arguments") or ()
                arguments = {str(name): None for name in names} if isinstance(names, (list, tuple)) else dict(names)
                messages.append(_tool_call(call_id, tool, arguments))
                messages.append(_tool_reply(call_id, tool, _bounded(_dumps(
                    {"error": {"code": 400, "kind": "serving", "message": str(item.get("error", ""))}}), limit)))
                order.append(f"refused:{item['_n']}")

    for position, span in enumerate(spans):
        interleave(position)
        call_id = f"call_{span.get('id', position + 1)}"
        tool = str(span.get("tool", ""))
        messages.append(_tool_call(call_id, tool, span.get("args") or {}))
        if span.get("error"):
            body = _dumps({"error": span["error"]})
        else:
            body = _dumps(span.get("result"))
        messages.append(_tool_reply(call_id, tool, _bounded(body, limit)))
        order.append(f"call:{span.get('id', position + 1)}")
    # Anything recorded after the last span, plus any index past the end.
    for position in sorted(by_index):
        interleave(position)
    messages.append({"role": "assistant", "content": result.answer})
    order.append("answer")
    return messages, order


def _axis_scores(score: CaseScore) -> dict[str, float | None]:
    return {"overall": score.score, **{axis: getattr(score, axis).score if axis in score.observed else None
                                       for axis in AXES}}


def _metadata(report: RunReport, result: CaseResult, case: EvalCase) -> dict[str, Any]:
    assert result.score is not None
    return {
        "case_id": result.case_id, "case_set": report.case_set, "agent": report.agent,
        "agent_pack": _digest(report.agent_pack), "grader": _digest(report.grader),
        "scores": _axis_scores(result.score), "observed": list(result.score.observed),
        "passed": result.score.passed, "dimensions": dict(sorted(case.dimensions.items())),
        "split": case_split(result, case, report), "shape": result.shape,
    }


# -- exports ---------------------------------------------------------------------


def sft_records(
    report: RunReport,
    cases: Iterable[EvalCase] | Mapping[str, EvalCase],
    *,
    min_score: float = 0.0,
    require_passed: bool = True,
    splits: Sequence[str] | None = None,
    include_holdout: bool = False,
    system_text: str | None = None,
    tools: Mapping[str, Sequence[Mapping[str, Any]]] | None = None,
    max_chars: int | None = None,
    split_filter: SplitFilter | None = None,
) -> list[dict[str, Any]]:
    """One chat transcript per graded case scoring at least *min_score* (and passing, by default).

    *system_text* overrides the agent pack's; without either, the system
    message is the turn rules alone. *tools*, keyed by case id, is the
    catalog each case advertised (``requests_document`` gives it) and is
    carried on the record when present.
    """
    by_id = _by_id(cases)
    _check_case_set(report, by_id)
    guard = split_filter or SplitFilter(tuple(splits) if splits is not None else None, include_holdout)
    _check_run_split(report, guard)
    system = system_text if system_text is not None else agent_system_text(report.agent_pack)
    head = _system_message(system)
    out: list[dict[str, Any]] = []
    for result in sorted(report.results, key=lambda row: row.case_id):
        case = by_id[result.case_id]
        if not result.graded or result.score is None:
            continue
        if result.score.score < min_score or (require_passed and not result.score.passed):
            continue
        if not guard.keeps(case_split(result, case, report)):
            continue
        tail, order = continuation(result, cap=max_chars)
        messages = [head, _user_message(case.query, case.persona), *tail]
        record: dict[str, Any] = {
            "schema": SFT_SCHEMA, "id": content_key("trace-export-sft", report.case_set, report.agent, result.case_id),
            "messages": messages, "metadata": {**_metadata(report, result, case), "order": order},
        }
        if tools is not None and result.case_id in tools:
            record["tools"] = [dict(tool) for tool in tools[result.case_id]]
        out.append(record)
    return out


def preference_pairs(
    a: RunReport,
    b: RunReport,
    cases: Iterable[EvalCase] | Mapping[str, EvalCase],
    *,
    margin: float | None = None,
    splits: Sequence[str] | None = None,
    include_holdout: bool = False,
    max_chars: int | None = None,
    split_filter: SplitFilter | None = None,
) -> list[dict[str, Any]]:
    """Chosen and rejected continuations of one prompt, from two runs of one case set.

    A case pairs when both runs graded it on the same axes and one leads on
    the overall score by more than *margin* (default: ``evalrun.delta_band``;
    a lead of exactly the band is one ``compare`` calls stable).
    Refused: two runs over different case sets, two runs whose graders carry
    different digests, and one run paired with itself.
    """
    if a is b or a == b:
        raise ExportRefused("a preference pair needs two runs; both sides are the same run")
    if a.case_set != b.case_set:
        raise ExportRefused(f"runs by {a.agent!r} and {b.agent!r} are over different case sets "
                            f"({a.case_set[:12]} and {b.case_set[:12]}); a pair must share its prompt")
    left_grader, right_grader = _digest(a.grader), _digest(b.grader)
    if left_grader is not None and right_grader is not None and left_grader != right_grader:
        raise ExportRefused(f"runs were graded by different graders ({left_grader[:12]} and {right_grader[:12]}); "
                            "their scores are not on one scale")
    by_id = _by_id(cases)
    _check_case_set(a, by_id)
    _check_case_set(b, by_id)
    band = default_margin() if margin is None else margin
    guard = split_filter or SplitFilter(tuple(splits) if splits is not None else None, include_holdout)
    _check_run_split(a, guard)
    _check_run_split(b, guard)
    head = _system_message(None)
    left = {row.case_id: row for row in a.results}
    right = {row.case_id: row for row in b.results}
    out: list[dict[str, Any]] = []
    for case_id in sorted(set(left) & set(right)):
        x, y = left[case_id], right[case_id]
        if not (x.graded and y.graded) or x.score is None or y.score is None:
            continue
        if set(x.score.observed) != set(y.score.observed):
            continue
        case = by_id[case_id]
        split = case_split(x, case, a) or case_split(y, case, b)
        if not guard.keeps(split):
            continue
        delta = round(x.score.score - y.score.score, 4)
        # Inside the band, edge included: `compare` calls |delta| <= band
        # stable, and a pair must not teach a difference it does not report.
        if delta == 0 or abs(delta) <= band + 1e-9:
            continue
        (chosen, chosen_run), (rejected, rejected_run) = ((x, a), (y, b)) if delta > 0 else ((y, b), (x, a))
        assert chosen.score is not None and rejected.score is not None
        chosen_messages, _ = continuation(chosen, cap=max_chars)
        rejected_messages, _ = continuation(rejected, cap=max_chars)
        axes = {axis: round(getattr(chosen.score, axis).score - getattr(rejected.score, axis).score, 4)
                for axis in AXES if axis in chosen.score.observed}
        out.append({
            "schema": PAIR_SCHEMA,
            "id": content_key("trace-export-pair", a.case_set, chosen_run.agent, rejected_run.agent, case_id),
            "prompt": [head, _user_message(case.query, case.persona)],
            "chosen": chosen_messages, "rejected": rejected_messages,
            "margin": abs(delta), "axes": axes,
            "metadata": {
                "case_id": case_id, "case_set": a.case_set, "grader": left_grader or right_grader,
                "chosen": {"agent": chosen_run.agent, "agent_pack": _digest(chosen_run.agent_pack),
                           "scores": _axis_scores(chosen.score), "passed": chosen.score.passed},
                "rejected": {"agent": rejected_run.agent, "agent_pack": _digest(rejected_run.agent_pack),
                             "scores": _axis_scores(rejected.score), "passed": rejected.score.passed},
                "dimensions": dict(sorted(case.dimensions.items())), "split": split,
                "shape": x.shape,
            },
        })
    return out


def _verifiable_outcomes(outcomes: OutcomeGrade, no_write: bool) -> tuple[float, float | None]:
    """The outcome score with the rated answer taken out, and the state-diff ratio.

    ``grade_outcomes``'s formula term by term, minus its last term: the same
    parts in the same order, so a case with no rated answer gets exactly the
    outcome score it was graded with (the tests hold this to equality).
    """
    touched = bool(outcomes.diff.created or outcomes.diff.updated or outcomes.diff.deleted)
    live = [match for match in outcomes.structured
            if not match.expected.blocked and match.detail != "branch not taken"]
    parts: list[float] = []
    ratio: float | None = None
    if live:
        ratio = round(sum(match.ratio for match in live) / len(live), 4)
    elif outcomes.structured_expected:
        ratio = round(outcomes.structured_met / outcomes.structured_expected, 4)
    if no_write:
        parts.append(0.0 if touched else 1.0)
    elif ratio is not None:
        parts.extend((ratio, 0.0 if outcomes.collateral else 1.0))
    elif touched:
        parts.append(0.0)
    if outcomes.grounding is not None:
        parts.append(outcomes.grounding)
    return (round(sum(parts) / len(parts), 4) if parts else 1.0), ratio


def _no_write(case: EvalCase | None, outcomes: OutcomeGrade) -> bool:
    if case is not None:
        return case.outcomes.no_write
    # Without the case, the one no-write condition the grade itself shows:
    # every structured expectation was blocked by a designed failure.
    return bool(outcomes.structured) and all(match.expected.blocked for match in outcomes.structured)


def reward_records(
    report: RunReport,
    cases: Iterable[EvalCase] | Mapping[str, EvalCase],
    *,
    splits: Sequence[str] | None = None,
    include_holdout: bool = False,
    split_filter: SplitFilter | None = None,
) -> list[dict[str, Any]]:
    """Per graded case: the overall reward, its axes, and the parts a program checked.

    ``verifiable`` holds only what the service observed and a deterministic
    rule decided; ``model_rated`` holds the answer score, the one term a
    rater (possibly a model) produced. ``verifiable.reward`` is the overall
    score recomputed without that term, over the executed axes; it is null
    for a run that executed nothing (an Eval Studio import), where the
    answer is all there is.

    *cases* is required: a compiled row carries its split at its top level,
    which the result does not copy, so without the cases the holdout guard
    would pass every row it cannot see.
    """
    if cases is None:
        raise ExportRefused("a reward export needs the case set the run was over: the rows' splits live there, "
                            "and without them a held-out row would be exported as training data")
    by_id = _by_id(cases)
    _check_case_set(report, by_id)
    guard = split_filter or SplitFilter(tuple(splits) if splits is not None else None, include_holdout)
    _check_run_split(report, guard)
    out: list[dict[str, Any]] = []
    for result in sorted(report.results, key=lambda row: row.case_id):
        if not result.graded or result.score is None:
            continue
        case = by_id.get(result.case_id)
        split = case_split(result, case, report)
        if not guard.keeps(split):
            continue
        score = result.score
        executed = "trajectory" in score.observed
        verifiable: dict[str, Any] = {"assertion_status": score.assertion_status,
                                      "plan": None, "trajectory": None, "outcomes": None, "reward": None}
        parts: list[float] = []
        if "plan" in score.observed:
            plan = score.plan
            verifiable["plan"] = {
                "score": plan.score, "node_recall": plan.node_recall, "node_precision": plan.node_precision,
                "edge_recall": plan.edge_recall, "missing_verify": len(plan.missing_verify),
                "extra_writes": plan.extra_writes, "unattributed_calls": plan.unattributed_calls,
            }
            parts.append(plan.score)
        if executed:
            trajectory = score.trajectory
            laws = Counter(finding.law for finding in trajectory.safety)
            verifiable["trajectory"] = {
                "score": trajectory.score, "exact_match": trajectory.exact_match,
                "in_order_match": trajectory.in_order_match, "any_order_match": trajectory.any_order_match,
                "precision": trajectory.precision, "recall": trajectory.recall, "calls": trajectory.calls,
                "refused_calls": trajectory.refused_calls, "budget_exceeded": trajectory.budget_exceeded,
                "retry_storm": trajectory.retry_storm,
                "safety_findings": len(trajectory.safety), "safety_laws": dict(sorted(laws.items())),
                "failures_honoured": trajectory.failures_honoured, "failures_expected": trajectory.failures_expected,
                "questions_honoured": trajectory.questions_honoured,
                "questions_expected": trajectory.questions_expected,
                "question_findings": len(trajectory.question_findings),
            }
            parts.append(trajectory.score)
            outcome_score, ratio = _verifiable_outcomes(score.outcomes, _no_write(case, score.outcomes))
            verifiable["outcomes"] = {
                "score": outcome_score, "state_diff_ratio": ratio,
                "structured_met": score.outcomes.structured_met,
                "structured_expected": score.outcomes.structured_expected,
                "collateral": len(score.outcomes.collateral), "grounding": score.outcomes.grounding,
            }
            parts.append(outcome_score)
        if parts and executed:
            verifiable["reward"] = round(sum(parts) / len(parts), 4)
        out.append({
            "schema": REWARD_SCHEMA, "case_id": result.case_id, "case_set": report.case_set,
            "agent": report.agent, "agent_pack": _digest(report.agent_pack), "grader": _digest(report.grader),
            "query": result.query, "reward": score.score, "passed": score.passed,
            "axes": _axis_scores(score), "observed": list(score.observed),
            "verifiable": verifiable,
            "model_rated": {"answer_score": score.outcomes.answer_score, "answer_error": score.outcomes.answer_error},
            "dimensions": dict(sorted(result.dimensions.items())), "split": split,
        })
    return out


def write_records(path: Path, records: Iterable[Mapping[str, Any]]) -> int:
    """JSONL, one record per line, keys sorted, ``\\n`` newlines: the same records are the same bytes."""
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        for record in records:
            handle.write(json.dumps(record, sort_keys=True, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


__all__ = [
    "AXES",
    "FORMATS",
    "HOLDOUT_SPLITS",
    "PAIR_SCHEMA",
    "REWARD_SCHEMA",
    "SFT_SCHEMA",
    "TRAIN_SPLIT",
    "ExportRefused",
    "HoldoutRefused",
    "SplitFilter",
    "agent_system_text",
    "case_split",
    "continuation",
    "default_margin",
    "max_result_chars",
    "preference_pairs",
    "reward_records",
    "sft_records",
    "write_records",
]
