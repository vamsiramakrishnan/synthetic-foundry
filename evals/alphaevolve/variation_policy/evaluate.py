"""Frozen evaluator for the child-variation policy.

The evaluator deliberately scores only the scheduling decision.  Worldloom's
validator, recipe replay, fleet fitness and fact ledger are protected oracles:
generated code neither sees nor changes them.  A candidate must first choose a
valid admissible single-axis child.  Only then does balanced axis/value
coverage contribute to its score.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from evals.alphaevolve.sandbox import (
    INVALID_SCORE,
    candidate_code,
    controller_evaluation,
    run_candidate,
)

TITLE = "Worldloom balanced fleet-variation policy"
METRIC_NAME = "completion_adjusted_axis_coverage"
HERE = Path(__file__).resolve().parent
PROBLEM_PATH = HERE / "PROBLEM.md"
INITIAL_PROGRAM_CODE = (HERE / "program.py").read_text(encoding="utf-8")
INTEGRATED_PROGRAM_CODE = (HERE / "integrated_program.py").read_text(encoding="utf-8")
FUNCTION_NAME = "choose_variation"

_AXES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("archetype", ("grocery", "retailer", "infrastructure", "bank")),
    ("history", ("none", "incident", "turbulent")),
    ("locale", ("none", "australia")),
    ("messiness", ("pristine", "well_run", "lived_in")),
)


def _tie(salt: str, case_index: int, axis: str, value: str) -> str:
    payload = f"{salt}|{case_index}|{axis}|{value}".encode()
    return hashlib.sha256(payload).hexdigest()[:16]


def _generated_cases(salt: str, count: int) -> tuple[dict[str, Any], ...]:
    """A deterministic matrix kept out of the model-visible problem prompt."""
    cases: list[dict[str, Any]] = []
    for case_index in range(count):
        options: list[dict[str, Any]] = []
        for axis_index, (axis, values) in enumerate(_AXES):
            for value_index, value in enumerate(values[1:], 1):
                tie_key = _tie(salt, case_index, axis, value)
                # Counts deliberately cross: value-only selection often likes
                # an already-overused wide axis, while the axis-first oracle
                # can still spread values inside the chosen axis.
                axis_count = (case_index * 3 + axis_index * 2) % 5
                value_count = (case_index * 5 + axis_index + value_index * 3) % 6
                # Refused/already-proposed candidates stay in the matrix as an
                # adversarially cheap temptation.  At least one option remains
                # admissible because no case can reject more than two of nine.
                admissible = int(tie_key[-2:], 16) % 11 != 0
                options.append({
                    "id": f"{axis}={value}",
                    "axis": axis,
                    "value": value,
                    "axis_count": axis_count,
                    "value_count": value_count,
                    "tie_key": tie_key,
                    "admissible": admissible,
                })
        cases.append({
            "name": f"{salt}-{case_index:03d}",
            "state": {"generation": 1 + case_index // 8, "slot": case_index % 8},
            "options": tuple(options),
        })
    return tuple(cases)


def _adversarial_cases() -> tuple[dict[str, Any], ...]:
    return (
        {
            "name": "inadmissible-cheap-child",
            "state": {"generation": 2, "slot": 0},
            "options": (
                {"id": "wide=blocked", "axis": "wide", "value": "blocked", "axis_count": 0, "value_count": 0, "tie_key": "00", "admissible": False},
                {"id": "narrow=fresh", "axis": "narrow", "value": "fresh", "axis_count": 0, "value_count": 1, "tie_key": "10", "admissible": True},
            ),
        },
        {
            "name": "axis-before-value",
            "state": {"generation": 3, "slot": 1},
            "options": (
                {"id": "wide=unseen", "axis": "wide", "value": "unseen", "axis_count": 4, "value_count": 0, "tie_key": "00", "admissible": True},
                {"id": "narrow=seen", "axis": "narrow", "value": "seen", "axis_count": 0, "value_count": 3, "tie_key": "99", "admissible": True},
            ),
        },
        {
            "name": "value-within-axis",
            "state": {"generation": 3, "slot": 2},
            "options": (
                {"id": "locale=used", "axis": "locale", "value": "used", "axis_count": 1, "value_count": 4, "tie_key": "00", "admissible": True},
                {"id": "locale=fresh", "axis": "locale", "value": "fresh", "axis_count": 1, "value_count": 0, "tie_key": "99", "admissible": True},
            ),
        },
        {
            "name": "stable-final-tie",
            "state": {"generation": 4, "slot": 0},
            "options": (
                {"id": "history=b", "axis": "history", "value": "b", "axis_count": 2, "value_count": 2, "tie_key": "20", "admissible": True},
                {"id": "history=a", "axis": "history", "value": "a", "axis_count": 2, "value_count": 2, "tie_key": "10", "admissible": True},
            ),
        },
    )


SEARCH_CASES = _generated_cases("search-v1", 64)
HOLDOUT_CASES = _generated_cases("holdout-v1", 37)
ADVERSARIAL_CASES = _adversarial_cases()


def _available(options: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return [option for option in options if option["admissible"]]


def _oracle(options: Iterable[dict[str, Any]]) -> dict[str, Any]:
    return min(
        _available(options),
        key=lambda option: (
            option["axis_count"],
            option["value_count"],
            option["tie_key"],
            option["id"],
        ),
    )


def _baseline(options: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """The production policy before this campaign, frozen as the control."""
    return min(
        _available(options),
        key=lambda option: (
            option["value_count"],
            option["tie_key"],
            option["id"],
        ),
    )


def _totals(selected: list[dict[str, Any]], oracle_hits: int) -> dict[str, int]:
    return {
        "axis_reuse_debt": sum(int(option["axis_count"]) for option in selected),
        "value_reuse_debt": sum(int(option["value_count"]) for option in selected),
        "oracle_misses": len(selected) - oracle_hits,
    }


def _score(code: str, cases: tuple[dict[str, Any], ...]) -> dict[str, Any]:
    calls = [
        {"state": row["state"], "options": row["options"]}
        for row in cases
    ]
    run = run_candidate(code, FUNCTION_NAME, calls)
    if run["error"]:
        return {"score": INVALID_SCORE, "error": run["error"], "cases": {}}

    selected: list[dict[str, Any]] = []
    baselines: list[dict[str, Any]] = []
    details: dict[str, dict[str, Any]] = {}
    invalid: list[str] = []
    oracle_hits = 0
    baseline_hits = 0
    for row, selected_id in zip(cases, run["outputs"], strict=True):
        by_id = {option["id"]: option for option in row["options"]}
        option = by_id.get(selected_id) if isinstance(selected_id, str) else None
        if option is None or not option["admissible"]:
            invalid.append(row["name"])
            continue
        expected = _oracle(row["options"])
        baseline = _baseline(row["options"])
        selected.append(option)
        baselines.append(baseline)
        hit = option["id"] == expected["id"]
        baseline_hit = baseline["id"] == expected["id"]
        oracle_hits += int(hit)
        baseline_hits += int(baseline_hit)
        details[row["name"]] = {
            "option": option["id"],
            "oracle": expected["id"],
            "baseline": baseline["id"],
            "completion": 1.0,
            "axis_count": option["axis_count"],
            "value_count": option["value_count"],
            "optimal": hit,
        }

    if invalid:
        return {
            "score": -100_000.0 - 1_000.0 * len(invalid),
            "error": "invalid or inadmissible choices: " + ", ".join(invalid),
            "cases": details,
            "promotion_passed": False,
        }

    totals = _totals(selected, oracle_hits)
    baseline_totals = _totals(baselines, baseline_hits)
    count = len(cases)
    max_axis_debt = max(1, sum(
        max(int(option["axis_count"]) for option in _available(row["options"]))
        for row in cases
    ))
    max_value_debt = max(1, sum(
        max(int(option["value_count"]) for option in _available(row["options"]))
        for row in cases
    ))
    optimal_share = oracle_hits / count
    # Completion was gated above.  Exact oracle agreement dominates; debt
    # terms distinguish incomplete search candidates without letting a small
    # efficiency gain outrank the coverage policy being searched.
    score = (
        100.0 * optimal_share
        + 10.0 * (1.0 - totals["axis_reuse_debt"] / max_axis_debt)
        + 1.0 * (1.0 - totals["value_reuse_debt"] / max_value_debt)
    )
    return {
        "score": score,
        "error": None,
        "cases": details,
        "totals": totals,
        "baseline": baseline_totals,
        "optimal": oracle_hits,
        "case_count": count,
        "optimal_share": optimal_share,
        "promotion_passed": oracle_hits == count,
        "lexicographically_beats_baseline": (
            totals["oracle_misses"],
            totals["axis_reuse_debt"],
            totals["value_reuse_debt"],
        ) < (
            baseline_totals["oracle_misses"],
            baseline_totals["axis_reuse_debt"],
            baseline_totals["value_reuse_debt"],
        ),
        "elapsed_ms": run["elapsed_ms"],
    }


def score_candidate(code: str) -> dict[str, Any]:
    return _score(code, SEARCH_CASES)


def score_holdout(code: str) -> dict[str, Any]:
    return _score(code, HOLDOUT_CASES)


def score_adversarial(code: str) -> dict[str, Any]:
    return _score(code, ADVERSARIAL_CASES)


def evaluation_function(program_candidate: dict[str, Any]) -> dict[str, Any]:
    """Adapt the local evaluator to AlphaEvolve's controller protocol."""
    try:
        result = score_candidate(candidate_code(program_candidate))
    except (KeyError, IndexError, TypeError) as exc:
        result = {"score": INVALID_SCORE, "error": f"invalid envelope: {exc}"}
    detail = result.get("error") or (
        f"all completion gates passed; score={result['score']:.4f}; "
        f"optimal={result['optimal']}/{result['case_count']}; "
        f"axis_reuse_debt={result['totals']['axis_reuse_debt']}"
    )
    return controller_evaluation(METRIC_NAME, result["score"], detail)
