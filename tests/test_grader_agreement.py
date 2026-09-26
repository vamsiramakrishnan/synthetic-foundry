"""The grader is frozen by digest, and its agreement with Eval Studio's is measured, not assumed."""

from __future__ import annotations

import csv
import json
import math
import sys
from contextlib import ExitStack
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import packkit
from worldloom.cli import app
from worldloom.evalrun import (
    AnswerOutcome,
    EvalCase,
    GroundedRater,
    case_from_row,
    compare,
    exec_rater,
    import_studio_results,
)
from worldloom.evalrun.agreement import (
    agreement,
    average_ranks,
    cohen_kappa,
    mean_absolute_error,
    pearson,
    spearman,
)
from worldloom.evalrun.grader import (
    GRADING_POLICY_KEYS,
    GraderDrift,
    check_frozen,
    frozen,
    grader_identity,
    redact_command,
)
from worldloom.models import EvaluationType

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    from worldloom.packkit.active import forget_defaults

    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


# -- fixtures ------------------------------------------------------------------

GOLDEN = "Revenue was 4200 in FY25."

#: case id -> (fetched answer, Studio's score, rubric). The grounded rater
#: scores the golden's figures present: {4200, FY25}.
ROWS: dict[str, tuple[str, str, EvaluationType]] = {
    "c1": ("Revenue was 4200 in FY25.", "1.0", EvaluationType.DIRECT_LOOKUP),    # local 1.0
    "c2": ("Revenue was 4200.", "0.6", EvaluationType.DIRECT_LOOKUP),            # local 0.5
    "c3": ("Nothing found.", "0.0", EvaluationType.DIRECT_LOOKUP),               # local 0.0
    "c4": ("FY25 revenue was 4200.", "0.9", EvaluationType.NUMERICAL_COMPARISON),  # local 1.0
    "c5": ("4200", "0.2", EvaluationType.NUMERICAL_COMPARISON),                  # local 0.5
    "c6": ("In FY25.", "0.7", EvaluationType.DIRECT_LOOKUP),                     # local 0.5
    "c7": ("Because the store ran out.", "0.8", EvaluationType.CAUSAL_MULTI_HOP),  # grounded abstains
    "c8": ("Error: 429", "0", EvaluationType.DIRECT_LOOKUP),                     # Studio error
}


def _case(case_id: str, rubric: EvaluationType = EvaluationType.DIRECT_LOOKUP) -> EvalCase:
    row = {"id": case_id, "query": f"What was revenue for record {case_id}?",
           "expected_dag": {"nodes": [{"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1",
                                       "entity": "incident", "op": "read"}], "edges": []},
           "assertions": [{"type": "tool_called", "node": "read"}]}
    return case_from_row(row, answer=AnswerOutcome(golden=GOLDEN, rubric=rubric))


def _cases() -> tuple[EvalCase, ...]:
    return tuple(_case(case_id, rubric) for case_id, (_, _, rubric) in ROWS.items())


def _csv(path: Path, cases: tuple[EvalCase, ...], scores: dict[str, str] | None = None) -> Path:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["query", "golden", "fetched", "ttft", "ttfa", "ttlt", "score", "scoreError"])
        for case in cases:
            fetched, score, _ = ROWS[case.id]
            writer.writerow([case.query, GOLDEN, fetched, "0", "0", "0", (scores or {}).get(case.id, score), ""])
        writer.writerow(["a query no case asks", "x", "y", "0", "0", "0", "1", ""])
    return path


# -- statistics against hand-computed values -------------------------------------


def test_perfect_agreement_and_anti_correlation() -> None:
    assert pearson([0.1, 0.5, 0.9], [0.2, 0.6, 1.0]) == (1.0, None)
    assert pearson([0.0, 0.5, 1.0], [1.0, 0.5, 0.0]) == (-1.0, None)
    assert spearman([1, 2, 3, 4], [10, 20, 30, 45]) == (1.0, None)
    assert spearman([1, 2, 3, 4], [4, 3, 2, 1]) == (-1.0, None)
    assert mean_absolute_error([0.2, 0.4], [0.2, 0.4]) == 0.0
    assert cohen_kappa([True, False, True], [True, False, True]) == (1.0, None)
    assert cohen_kappa([True, False], [False, True]) == (-1.0, None)


def test_ties_take_the_average_rank() -> None:
    assert average_ranks([10, 20, 20, 30]) == [1.0, 2.5, 2.5, 4.0]
    assert average_ranks([0.5, 0.5, 0.5]) == [2.0, 2.0, 2.0]
    assert average_ranks([3, 1, 2, 1]) == [4.0, 1.5, 3.0, 1.5]
    # x ranks [1, 2.5, 2.5, 4], y ranks [1, 2, 3, 4]: cov 4.5, var 4.5 and 5.
    rho, reason = spearman([1, 2, 2, 3], [1, 2, 3, 4])
    assert reason is None and rho == round(4.5 / math.sqrt(4.5 * 5), 4) == 0.9487


def test_hand_computed_pearson_mae_and_kappa() -> None:
    # x = [1, 2, 3, 4], y = [1, 3, 2, 4]: deviations (-1.5, -.5, .5, 1.5) and
    # (-1.5, .5, -.5, 1.5); cov = 2.25 - .25 - .25 + 2.25 = 4, var 5 and 5.
    assert pearson([1, 2, 3, 4], [1, 3, 2, 4]) == (0.8, None)
    assert mean_absolute_error([0.0, 0.5, 1.0], [0.1, 0.5, 0.7]) == round(0.4 / 3, 4)
    # po = 3/4; pe = .5 * .25 + .5 * .75 = .5; kappa = (.75 - .5) / .5.
    assert cohen_kappa([True, True, False, False], [True, False, False, False]) == (0.5, None)


def test_degenerate_statistics_are_none_with_a_reason() -> None:
    assert pearson([0.5], [0.5]) == (None, "fewer than two rated pairs")
    assert pearson([], []) == (None, "fewer than two rated pairs")
    value, reason = pearson([0.7, 0.7, 0.7], [0.1, 0.5, 0.9])
    assert value is None and reason is not None and "first" in reason
    value, reason = spearman([0.1, 0.5, 0.9], [1.0, 1.0, 1.0])
    assert value is None and reason is not None and "second" in reason
    value, reason = cohen_kappa([True, True], [True, True])
    assert value is None and reason is not None and "same class" in reason
    assert cohen_kappa([], []) == (None, "no rated pairs")
    assert mean_absolute_error([], []) is None


# -- the grader's identity -----------------------------------------------------------


def test_the_grader_digest_is_stable_and_names_what_graded() -> None:
    first, second = grader_identity(GroundedRater()), grader_identity(GroundedRater())
    assert first == second
    assert first["rater"] == {"name": "grounded", "kind": "grounded"}
    assert set(first["policy"]) == set(GRADING_POLICY_KEYS)
    assert first["policy"] == {"evalrun.answer_pass_score": 0.8, "evalrun.delta_band": 0.1}
    assert len(first["digest"]) == 32
    assert grader_identity(None)["rater"]["kind"] == "none"
    assert grader_identity(None)["digest"] != first["digest"]
    judge = exec_rater("judge --model m")
    assert grader_identity(judge)["rater"] == {"name": "exec:judge", "kind": "exec", "command": "judge --model m",
                                               "shell": False}
    assert grader_identity(judge)["digest"] != grader_identity(exec_rater("judge --model n"))["digest"]


def test_an_exec_raters_credentials_never_reach_the_identity() -> None:
    command = "OPENAI_API_KEY=sk-live-1 judge --token abc --api-key=sk-2 --model gemini"
    identity = grader_identity(exec_rater(command))
    text = json.dumps(identity)
    assert "sk-live-1" not in text and "abc" not in text and "sk-2" not in text
    assert identity["rater"]["command"] == "OPENAI_API_KEY=REDACTED judge --token REDACTED --api-key=REDACTED --model gemini"
    assert redact_command("judge --model 'a b'") == "judge --model 'a b'"
    # A Windows path keeps its backslashes: the identity names the judge that ran.
    windows = r"C:\Python\python.exe C:\Temp\judge.py --token abc"
    assert redact_command(windows) == r"C:\Python\python.exe C:\Temp\judge.py --token REDACTED"
    # A quoted value is one word, spaces and all.
    assert redact_command("judge --token 'sk live' --api-key=\"sk two\" x") == "judge --token REDACTED --api-key=REDACTED x"
    # Rotating a key is not a different grader.
    assert grader_identity(exec_rater(command.replace("sk-live-1", "sk-live-2")))["digest"] == identity["digest"]


def _pack(root: Path, kind: str, name: str, body: dict) -> None:
    path = root / kind / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": kind, "name": name, "body": body}))


def test_a_reworded_judge_moves_the_digest(tmp_path: Path) -> None:
    before = grader_identity(GroundedRater())
    _pack(tmp_path, "prompts", "strict-judge", {"texts": {"rater.judge.trailer": "Reply with one float in [0, 1]."}})
    with packkit.use("prompts:strict-judge", roots=[tmp_path]):
        during = grader_identity(GroundedRater())
    assert during["prompts_digest"] != before["prompts_digest"] and during["digest"] != before["digest"]
    assert during["rubrics_digest"] == before["rubrics_digest"]
    assert grader_identity(GroundedRater()) == before


def test_a_changed_rubric_moves_the_digest(monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.gemini_enterprise import cases as studio_cases

    before = grader_identity(GroundedRater())
    monkeypatch.setitem(studio_cases.RUBRICS, EvaluationType.DIRECT_LOOKUP, "Score similarity.")
    after = grader_identity(GroundedRater())
    assert after["rubrics_digest"] != before["rubrics_digest"] and after["digest"] != before["digest"]


def test_a_moved_pass_mark_moves_the_digest_and_frozen_refuses_it(tmp_path: Path) -> None:
    pinned = grader_identity(GroundedRater())
    _pack(tmp_path, "industry", "lenient", {"policy": {"evalrun.answer_pass_score": 0.5}})
    with packkit.use("industry:lenient", roots=[tmp_path]):
        moved = grader_identity(GroundedRater())
        assert moved["policy"]["evalrun.answer_pass_score"] == 0.5 and moved["digest"] != pinned["digest"]
        with pytest.raises(GraderDrift, match="policy changed") as raised:
            check_frozen(pinned, GroundedRater())
        assert raised.value.changed == ("policy",)
        with pytest.raises(GraderDrift):
            check_frozen(pinned["digest"], GroundedRater())
    assert check_frozen(pinned, GroundedRater()) == pinned
    with frozen(pinned["digest"], GroundedRater()) as identity:
        assert identity == pinned
    # A pack put in force mid-round is caught on the way out.
    with ExitStack() as stack, pytest.raises(GraderDrift), frozen(pinned, GroundedRater()):
        stack.enter_context(packkit.use("industry:lenient", roots=[tmp_path]))


# -- compare refuses to judge across graders -----------------------------------------


def test_compare_calls_runs_graded_differently_incomparable(tmp_path: Path) -> None:
    cases = _cases()
    baseline = import_studio_results(_csv(tmp_path / "a.csv", cases), cases)
    recent = import_studio_results(_csv(tmp_path / "b.csv", cases, {"c3": "1.0", "c1": "0.0"}), cases)
    plain = compare(baseline, recent)
    assert plain.improvements == ("c3",) and plain.regressions == ("c1",)
    assert plain.grader_mismatch is False and plain.notes == ()
    one = grader_identity(GroundedRater())
    other = {**one, "digest": "0" * 32}
    # One side without a grader: exactly the old behaviour.
    assert compare(baseline.model_copy(update={"grader": one}), recent) == plain
    same = compare(baseline.model_copy(update={"grader": one}), recent.model_copy(update={"grader": one}))
    assert same == plain
    mismatch = compare(baseline.model_copy(update={"grader": one}), recent.model_copy(update={"grader": other}))
    assert mismatch.grader_mismatch is True and mismatch.notes and "graded differently" in mismatch.notes[0]
    assert mismatch.improvements == () and mismatch.regressions == () and mismatch.stable == 0
    verdicts = {item.case_id: item.verdict for item in mismatch.deltas}
    assert verdicts["c1"] == verdicts["c3"] == "incomparable"
    assert verdicts["c8"] == "ungraded"


# -- agreement -------------------------------------------------------------------


def test_agreement_rates_studios_own_answers_and_joins_on_case_id(tmp_path: Path) -> None:
    cases = _cases()
    studio = import_studio_results(_csv(tmp_path / "studio.csv", cases), cases)
    report = agreement(studio, cases, GroundedRater(), instruction="Rate similarity.")
    assert report.studio_rows == 8
    assert [(row.case_id, row.studio, row.local) for row in report.cases] == [
        ("c1", 1.0, 1.0), ("c2", 0.6, 0.5), ("c3", 0.0, 0.0), ("c4", 0.9, 1.0), ("c5", 0.2, 0.5), ("c6", 0.7, 0.5)]
    stats = report.stats
    assert stats.n == 6
    # |d| = 0, .1, 0, .1, .3, .2
    assert stats.mae == round(0.7 / 6, 4)
    assert stats.within_band == round(4 / 6, 4)
    assert stats.kappa == 1.0 and stats.confusion.both_pass == 2 and stats.confusion.both_fail == 4
    studio_scores, local_scores = [1.0, 0.6, 0.0, 0.9, 0.2, 0.7], [1.0, 0.5, 0.0, 1.0, 0.5, 0.5]
    assert stats.pearson == pearson(studio_scores, local_scores)[0]
    assert stats.spearman == spearman(studio_scores, local_scores)[0]
    assert report.worst[0].case_id == "c5" and report.worst[0].difference == 0.3
    assert [entry.key for entry in report.by_shape] == ["direct_lookup", "numerical_comparison"]
    assert report.by_shape[1].stats.n == 2 and report.by_shape[1].stats.pearson == 1.0
    # The judge-only case is its own bucket, never a local error, never a zero.
    assert report.abstained.cases == 1 and report.abstained.case_ids == ("c7",)
    assert report.abstained.studio_mean == 0.8 and report.abstained.by_shape == {"causal_multi_hop": 1}
    assert report.excluded.studio_errors == 1 and report.excluded.local_errors == 0
    assert report.local == grader_identity(GroundedRater())
    assert report.studio["instruction"] == "Rate similarity." and len(report.studio["instruction_digest"]) == 32
    # Six pairs is fewer than the policy's minimum: no verdict is claimed.
    assert report.verdict == "insufficient" and report.thresholds.min_cases == 30


def test_agreement_counts_unknown_cases_and_local_errors(tmp_path: Path) -> None:
    cases = _cases()
    studio = import_studio_results(_csv(tmp_path / "studio.csv", cases), cases)
    fewer = tuple(case for case in cases if case.id != "c1")
    report = agreement(studio, fewer, GroundedRater())
    assert report.excluded.unknown_cases == 1 and report.stats.n == 5

    def flaky(case: EvalCase, answer: str) -> tuple[float | None, str | None]:
        return (None, "exec_timeout: overran") if case.id in {"c2", "c7"} else GroundedRater()(case, answer)

    class Flaky:
        name = "flaky"

        def __call__(self, case: EvalCase, answer: str) -> tuple[float | None, str | None]:
            return flaky(case, answer)

    report = agreement(studio, cases, Flaky())
    # c2 is a local error; c7 is judge-only, so a refusal there is an abstention.
    assert report.excluded.local_errors == 1 and report.excluded.local_error_messages == {"exec_timeout": 1}
    assert report.abstained.cases == 1 and report.stats.n == 5
    assert report.local["rater"] == {"name": "flaky", "kind": "custom"}


def test_the_verdict_follows_the_policy_thresholds(tmp_path: Path) -> None:
    cases = _cases()
    studio = import_studio_results(_csv(tmp_path / "studio.csv", cases), cases)
    _pack(tmp_path, "industry", "small", {"policy": {"evalrun.agreement.min_cases": 5}})
    with packkit.use("industry:small", roots=[tmp_path]):
        report = agreement(studio, cases, GroundedRater())
        # MAE .1167 exceeds .1 although kappa is 1: the grader is too far off.
        assert report.verdict == "disagrees" and "mean absolute error" in report.reasons[0]
        relaxed = agreement(studio, cases, GroundedRater(), threshold=0.5)
        # At a .5 pass mark c6 (Studio .7, local .5) is a pass both ways, c5 a local pass only.
        assert relaxed.threshold == 0.5 and relaxed.stats.confusion.studio_fail_local_pass == 1
    _pack(tmp_path, "industry", "loose", {"policy": {"evalrun.agreement.min_cases": 5,
                                                     "evalrun.agreement.max_mae": 0.2}})
    with packkit.use("industry:loose", roots=[tmp_path]):
        report = agreement(studio, cases, GroundedRater())
        assert report.verdict == "agrees", report.reasons


# -- CLI ---------------------------------------------------------------------------


def _case_set(root: Path, cases: tuple[EvalCase, ...]) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    with (root / "evalrun-cases.jsonl").open("w", encoding="utf-8") as handle:
        for case in cases:
            handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")
    (root / "records.jsonl").write_text("", encoding="utf-8")
    return root


def test_the_cli_writes_agreement_json(tmp_path: Path) -> None:
    cases = _cases()
    corpus = _case_set(tmp_path / "cases", cases)
    results = _csv(tmp_path / "studio.csv", cases)
    out = tmp_path / "agreement"
    result = runner.invoke(app, ["evalrun", "agreement", str(corpus), str(results), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "verdict: insufficient" in result.output and "kappa" in result.output
    assert "1 judge-only case(s)" in result.output
    written: dict[str, Any] = json.loads((out / "agreement.json").read_text(encoding="utf-8"))
    assert written["schema"] == "worldloom.evalrun-agreement/v1" and written["stats"]["n"] == 6
    assert written["local"]["digest"] == grader_identity(GroundedRater())["digest"]
    again = runner.invoke(app, ["evalrun", "agreement", str(corpus), str(results), "--json"])
    assert again.exit_code == 0 and json.loads(again.output) == written
    refused = runner.invoke(app, ["evalrun", "agreement", str(corpus), str(results), "--rater", "magic"])
    assert refused.exit_code != 0 and "grounded or exec:" in refused.output


def test_the_cli_measures_an_exec_judge(tmp_path: Path) -> None:
    cases = _cases()
    corpus = _case_set(tmp_path / "cases", cases)
    results = _csv(tmp_path / "studio.csv", cases)
    judge = tmp_path / "judge.py"
    judge.write_text("import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'text': 'Score: 0.5'}))\n",
                     encoding="utf-8")
    command = f"exec:{sys.executable} {judge}"
    result = runner.invoke(app, ["evalrun", "agreement", str(corpus), str(results), "--rater", command, "--json"])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    # A model judge does not abstain on causal chains: seven pairs, one Studio error.
    assert report["stats"]["n"] == 7 and report["abstained"]["cases"] == 0
    assert report["local"]["rater"]["kind"] == "exec" and str(judge) in report["local"]["rater"]["command"]
    assert report["stats"]["pearson"] is None and "second" in report["stats"]["undefined"]["pearson"]
