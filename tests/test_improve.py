"""The improvement loop: a revised policy is kept only when it wins on cases its proposer never saw.

The agent under test here reads its policy for real: it walks every expected
DAG when its pack teaches the `verify` skill and does nothing otherwise, so a
proposal that adds the skill is a genuine improvement and one that only
rewords the instruction is not. The proposer is a function over the pack
interview's request, the same document a harness reads. The skill can be a
string or a real skill file (`skills/verify/SKILL.md`), which a proposer adds
by diffing the champion's tree.
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
from worldloom.packkit import diffs
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
        self.skilled = "verify" in pack.body.skills or "skills/verify/SKILL.md" in pack.body.files
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


def _diff_proposer(files: dict[str, str]) -> Any:
    """A proposer that answers with a unified diff adding *files* to the draft's tree."""
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        base = payload["draft_tree"]
        return {"request_id": payload["request_id"], "message": "patched",
                "proposal": {"name": payload["draft"]["name"], "diff": diffs.render(base, {**base, **files})}}

    exchange.seen = seen  # type: ignore[attr-defined]
    return exchange


_VERIFY = ("---\nname: verify\ndescription: Use after any write, to confirm it held.\n---\n\n"
           "Walk every step the request needs and read each write back.\n")
_NOTES = ("---\nname: notes\ndescription: Background on the connectors.\n---\n\n"
          "Nothing here changes what the agent does.\n")


def _loop(corpus: Any, tmp_path: Path, exchange: Any, *, rounds: int = 2, rater: Any = None,
          log: list[str] | None = None, run_hook: Any = None, **options: Any) -> Any:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    calls = log if log is not None else []

    def run(subset: Any, agent: Any) -> Any:
        if run_hook is not None:
            run_hook()
        return run_cases(service_for(subset, records), subset, agent, rater=rater)

    return improve(packkit.resolve("agent:baseline"), cases, run=run,
                   agent_for=lambda pack: PolicyAgent(pack, cases, calls), exchange=exchange,
                   out=tmp_path / "improve", rater=rater, holdout_share=0.4, rounds=rounds, **options)


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


def test_a_diff_is_promoted_and_ablation_drops_the_hunk_that_carried_nothing(corpus: Any, tmp_path: Path) -> None:
    exchange = _diff_proposer({"skills/notes/SKILL.md": _NOTES, "skills/verify/SKILL.md": _VERIFY})
    report = _loop(corpus, tmp_path, exchange, rounds=1)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    # The proposer was handed the champion as a tree and asked for a diff.
    payload = exchange.seen[0]
    assert set(payload["draft_tree"]) == {"policy.json"}
    assert packkit.text("evalrun.improve.rule.diff") in payload["message"]
    # Ablation measured each hunk: the inert skill cost nothing and was dropped,
    # the useful one carried the whole gain and was kept.
    ablation = first.ablation
    assert ablation is not None and ablation.reduced
    assert ablation.proposed_diff.count("+++ b/skills/") == 2
    by_file = {hunk.file: hunk for hunk in ablation.hunks}
    notes, verify = by_file["skills/notes/SKILL.md"], by_file["skills/verify/SKILL.md"]
    assert notes.decision == "dropped" and notes.contribution is not None and notes.contribution < ablation.tolerance
    assert verify.decision == "kept" and verify.contribution is not None and verify.contribution >= 0.1
    assert ablation.reduced_train is not None and ablation.reduced_train.passed
    # What went to the holdout, and what the receipt and the pack root hold, is the reduced candidate.
    assert first.diff_hunks == 1 and first.diff is not None
    assert "+++ b/skills/verify/SKILL.md" in first.diff and "notes" not in first.diff
    assert first.candidate["digest"] != ablation.proposed["digest"]
    rounds_dir = tmp_path / "improve" / "rounds"
    assert (rounds_dir / "001.diff").read_text(encoding="utf-8") == first.diff
    stored = json.loads((rounds_dir / "001.json").read_text(encoding="utf-8"))
    assert stored["diff_hunks"] == 1 and stored["ablation"]["hunks"][0]["decision"] == "dropped"
    promoted = packkit.resolve("agent:baseline-r1", roots=[tmp_path / "improve" / "packs"])
    assert promoted.digest == first.candidate["digest"] == report.champion["digest"]
    assert list(promoted.body.files) == ["skills/verify/SKILL.md"]
    # Every run stayed in the loop's output directory, the reduced candidate's included.
    assert list((tmp_path / "improve" / "runs").glob(f"baseline-r1@{first.candidate['digest'][:12]}/holdout/run.json"))


def test_without_ablation_the_whole_diff_goes_to_the_holdout(corpus: Any, tmp_path: Path) -> None:
    exchange = _diff_proposer({"skills/notes/SKILL.md": _NOTES, "skills/verify/SKILL.md": _VERIFY})
    report = _loop(corpus, tmp_path, exchange, rounds=1, ablate=False)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    assert first.ablation is None and first.diff_hunks == 2


def test_a_revision_that_does_not_help_is_rejected_on_training_and_never_sees_the_holdout(corpus: Any, tmp_path: Path) -> None:
    exchange = _proposer({"system": "Complete the request with care, then answer."})
    log: list[str] = []
    report = _loop(corpus, tmp_path, exchange, rounds=1, log=log)
    only = report.rounds[0]
    assert only.decision == "rejected"
    assert only.train is not None and not only.train.passed and only.holdout is None
    # A rejected candidate still leaves its diff against the champion.
    assert only.diff is not None and "with care" in only.diff and only.diff_hunks == 1
    assert (tmp_path / "improve" / "rounds" / "001.diff").exists()
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


class Split:
    """The reference agent on the cases in *ids*, idle on the rest."""

    def __init__(self, cases: Any, ids: set[str], name: str) -> None:
        self.name = name
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")
        self.ids = ids

    def run(self, task: Any, tools: Any) -> Any:
        return (self.reference if task.case_id in self.ids else self.idle).run(task, tools)


def test_a_value_gate_refuses_a_win_on_cheap_cases_bought_with_costly_ones(corpus: Any) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    ids = [case.id for case in cases]
    costly, cheap = set(ids[: len(ids) // 2]), set(ids[len(ids) // 2 :])
    # The one costly case the candidate gives up is one the reference agent
    # actually wins, so giving it up is a real loss.
    lost = min(delta.case_id for delta in compare(
        run_cases(service_for(cases, records), cases, Split(cases, set(), "idle")),
        run_cases(service_for(cases, records), cases, Split(cases, costly, "ref"))).deltas
        if delta.case_id in costly and (delta.delta or 0) > 0)
    before = run_cases(service_for(cases, records), cases, Split(cases, costly, "before"))
    after = run_cases(service_for(cases, records), cases, Split(cases, (costly | cheap) - {lost}, "after"))
    comparison = compare(before, after)
    plain = judge(comparison, name="train", min_delta=0.0, strict=True, max_axis_regression=1.0)
    assert plain.passed and plain.value_delta is None
    uniform = judge(comparison, name="train", min_delta=0.0, strict=True, max_axis_regression=1.0,
                    values={case_id: 1.0 for case_id in ids})
    assert uniform.passed and uniform.value_delta == pytest.approx(comparison.mean_delta, abs=1e-3)
    weighted = judge(comparison, name="train", min_delta=0.0, strict=True, max_axis_regression=1.0,
                     values={case_id: (1000.0 if case_id == lost else 0.001) for case_id in ids})
    assert not weighted.passed and weighted.value_delta is not None and weighted.value_delta < 0
    assert any("value-weighted delta" in reason for reason in weighted.reasons)


def test_the_loop_records_the_value_delta_when_given_values(corpus: Any, tmp_path: Path) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    exchange = _proposer({"skills": {"verify": "Walk every step the request needs and read each write back."}})
    report = improve(packkit.resolve("agent:baseline"), cases,
                     run=lambda subset, agent: run_cases(service_for(subset, records), subset, agent),
                     agent_for=lambda pack: PolicyAgent(pack, cases, []), exchange=exchange,
                     out=tmp_path / "improve", holdout_share=0.4, rounds=1,
                     values={case.id: 1.0 for case in cases})
    first = report.rounds[0]
    assert first.decision == "promoted"
    assert first.train is not None and first.train.value_delta is not None
    assert first.holdout is not None and first.holdout.value_delta is not None
