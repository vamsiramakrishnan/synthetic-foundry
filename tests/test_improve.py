"""The improvement loop: a revised policy is kept only when it wins on cases its proposer never saw.

The agent under test here reads its policy for real: it walks every expected
DAG when its pack teaches the `verify` skill and does nothing otherwise, so a
proposal that adds the skill is a genuine improvement and one that only
rewords the instruction is not. The proposer is a function over the pack
interview's request, the same document a harness reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.grader import GraderDrift
from worldloom.evalrun.improve import improve, judge, split_cases
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.results import compare
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(8)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


class PolicyAgent:
    """Walks the expected DAG when its policy teaches `verify`; otherwise does nothing."""

    def __init__(self, pack: Any, cases: Any, log: list[str]) -> None:
        self.pack = pack
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.skilled = "verify" in pack.body.skills
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")
        self.log = log

    def run(self, task: Any, tools: Any) -> Any:
        self.log.append(self.pack.digest)
        return (self.reference if self.skilled else self.idle).run(task, tools)


def _proposer(body_change: dict[str, Any] | None = None, *, questions: tuple[str, ...] = ()) -> Any:
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        if questions:
            return {"request_id": payload["request_id"], "message": "need more", "questions": list(questions)}
        body = {**payload["draft"]["body"], **(body_change or {})}
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    exchange.seen = seen  # type: ignore[attr-defined]
    return exchange


def _loop(corpus: Any, tmp_path: Path, exchange: Any, *, rounds: int = 2, rater: Any = None,
          log: list[str] | None = None, run_hook: Any = None) -> Any:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    calls = log if log is not None else []

    def run(subset: Any, agent: Any) -> Any:
        if run_hook is not None:
            run_hook()
        return run_cases(service_for(subset, records), subset, agent, rater=rater)

    return improve(packkit.resolve("agent:baseline"), cases, run=run,
                   agent_for=lambda pack: PolicyAgent(pack, cases, calls), exchange=exchange,
                   out=tmp_path / "improve", rater=rater, holdout_share=0.4, rounds=rounds)


def test_split_is_stable_disjoint_and_keeps_declared_splits(corpus: Any) -> None:
    cases = cases_from_corpus(corpus)
    train, held = split_cases(cases, holdout_share=0.4)
    assert {c.id for c in train}.isdisjoint({c.id for c in held})
    assert len(train) + len(held) == len(cases)
    again = split_cases(list(reversed(cases)), holdout_share=0.4)
    assert {c.id for c in again[1]} == {c.id for c in held}
    declared = [case.model_copy(update={"dimensions": {**case.dimensions, "split": "test"}}) for case in cases]
    assert split_cases(declared, holdout_share=0.4) == ((), tuple(declared))
    with pytest.raises(ValueError):
        split_cases(cases, holdout_share=1.0)


def test_a_revision_that_helps_is_promoted_after_both_gates(corpus: Any, tmp_path: Path) -> None:
    exchange = _proposer({"skills": {"verify": "Walk every step the request needs and read each write back."}})
    report = _loop(corpus, tmp_path, exchange)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    assert first.train is not None and first.train.passed and first.train.mean_delta >= 0.1
    assert first.holdout is not None and first.holdout.passed and first.holdout.mean_delta > 0
    assert report.champion["digest"] == first.candidate["digest"] != report.initial["digest"]
    assert report.promotions >= 1
    # The proposer saw the training failures and never a held-out case id.
    held_ids = {case.id for case in split_cases(cases_from_corpus(corpus), holdout_share=0.4)[1]}
    message = exchange.seen[0]["message"]
    assert "Failures on the training cases" in message
    assert not any(case_id in message for case_id in held_ids)
    receipts = sorted((tmp_path / "improve" / "rounds").glob("*.json"))
    assert len(receipts) == len(report.rounds)
    stored = json.loads(receipts[0].read_text())
    assert stored["schema"] == "worldloom.improve-round/v1" and stored["decision"] == "promoted"
    assert (tmp_path / "improve" / "packs" / "agent" / "baseline-r1.json").exists()
    run_json = json.loads(next((tmp_path / "improve" / "runs").glob("baseline-r1@*/holdout/run.json")).read_text())
    assert run_json["agent_pack"]["digest"] == first.candidate["digest"]
    assert run_json["grader"]["digest"] == report.grader["digest"]


def test_a_revision_that_does_not_help_is_rejected_on_training_and_never_sees_the_holdout(corpus: Any, tmp_path: Path) -> None:
    exchange = _proposer({"system": "Complete the request with care, then answer."})
    log: list[str] = []
    report = _loop(corpus, tmp_path, exchange, rounds=1, log=log)
    only = report.rounds[0]
    assert only.decision == "rejected"
    assert only.train is not None and not only.train.passed and only.holdout is None
    assert any("mean delta" in reason for reason in only.reasons)
    assert report.champion == report.initial
    assert not list((tmp_path / "improve" / "runs").glob("*/holdout"))


def test_a_restatement_of_the_champion_is_not_run(corpus: Any, tmp_path: Path) -> None:
    report = _loop(corpus, tmp_path, _proposer(), rounds=1)
    assert report.rounds[0].decision == "unchanged"
    assert report.rounds[0].train is None


def test_questions_stop_the_loop_for_the_operator(corpus: Any, tmp_path: Path) -> None:
    report = _loop(corpus, tmp_path, _proposer(questions=("Which connector is authoritative?",)), rounds=3)
    assert [item.decision for item in report.rounds] == ["questions"]
    assert report.rounds[0].questions == ("Which connector is authoritative?",)


def test_runs_already_paid_for_are_reused(corpus: Any, tmp_path: Path) -> None:
    exchange = _proposer({"system": "Complete the request with care, then answer."})
    first: list[str] = []
    _loop(corpus, tmp_path, exchange, rounds=1, log=first)
    second: list[str] = []
    _loop(corpus, tmp_path, exchange, rounds=1, log=second)
    assert first and not second


class ShiftingRater:
    kind = "custom"

    def __init__(self) -> None:
        self.name = "steady"

    def __call__(self, case: Any, answer: str) -> tuple[float | None, str | None]:
        return None, "unrated"


def test_a_grader_that_moves_mid_loop_stops_it(corpus: Any, tmp_path: Path) -> None:
    rater = ShiftingRater()

    def drift() -> None:
        rater.name = "moved"

    with pytest.raises(GraderDrift):
        _loop(corpus, tmp_path, _proposer(), rounds=1, rater=rater, run_hook=drift)


def test_judge_names_every_reason(corpus: Any) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    good = run_cases(service_for(cases, records), cases, ReferenceAgent(cases))
    idle = run_cases(service_for(cases, records), cases, ScriptedAgent([], name="idle"))
    gate = judge(compare(good, idle), name="train", min_delta=0.1, strict=False, max_axis_regression=0.1)
    assert not gate.passed
    assert any("mean delta" in reason for reason in gate.reasons)
    assert any("axis fell" in reason for reason in gate.reasons)
    assert judge(compare(idle, good), name="train", min_delta=0.1, strict=False, max_axis_regression=0.1).passed
    same = judge(compare(good, good), name="holdout", min_delta=0.0, strict=True, max_axis_regression=0.1)
    assert not same.passed


def test_the_cli_refuses_without_an_agent_or_a_proposer(corpus: Any, tmp_path: Path) -> None:
    result = runner.invoke(app, ["evalrun", "improve", str(tmp_path), "--agent-pack", "agent:baseline", "-o", str(tmp_path / "o")])
    assert result.exit_code != 0 and "exec" in result.output
    result = runner.invoke(app, ["evalrun", "improve", str(tmp_path), "--agent-pack", "agent:baseline", "--exec", "true",
                                 "-o", str(tmp_path / "o")])
    assert result.exit_code != 0 and "proposer" in result.output
