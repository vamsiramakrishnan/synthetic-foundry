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

import importlib
import json
import re
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.corpus import write_jsonl
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ImproveLoop,
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.grader import GraderDrift, grader_identity
from worldloom.evalrun.improve import Improver, improve, judge, round_stem, split_cases
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.results import compare, read_run
from worldloom.evalrun.splits import HELD_OUT_SPLITS
from worldloom.execseam import ExecFailed
from worldloom.packkit import diffs
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()
#: The module, not the function `worldloom.evalrun` re-exports under the same name.
improve_module = importlib.import_module("worldloom.evalrun.improve")


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
          log: list[str] | None = None, run_hook: Any = None, champion: Any = None, agent: Any = None,
          **options: Any) -> Any:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    calls = log if log is not None else []
    make = agent or PolicyAgent

    def run(subset: Any, agent: Any) -> Any:
        if run_hook is not None:
            run_hook()
        return run_cases(service_for(subset, records), subset, agent, rater=rater)

    return improve(champion or packkit.resolve("agent:baseline"), cases, run=run,
                   agent_for=lambda pack: make(pack, cases, calls), exchange=exchange,
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
    report = _loop(corpus, tmp_path, exchange, rounds=1, log=first)
    champion = report.initial["digest"]
    # A second loop is a new round (r2), so only its candidate is new: the
    # champion's runs are already paid for.
    second: list[str] = []
    again = _loop(corpus, tmp_path, exchange, rounds=1, log=second)
    assert again.rounds[0].round == 2 and again.rounds[0].candidate["ref"] == "agent:baseline-r2"
    assert first and second and champion not in set(second)
    # A round interrupted before its receipt resumes under the same name and
    # pays for nothing it already ran.
    (tmp_path / "improve" / "rounds" / "002.json").unlink()
    third: list[str] = []
    resumed = _loop(corpus, tmp_path, exchange, rounds=1, log=third)
    assert resumed.rounds[0].round == 2 and resumed.rounds[0].candidate == again.rounds[0].candidate
    assert not third


class OtherPolicyAgent(PolicyAgent):
    """The same policy, run by a different agent: another command, say."""

    def fingerprint(self) -> dict[str, Any]:
        return {"kind": "exec", "command": "other-harness", "agent_pack": self.pack.digest}


def test_a_run_is_reused_only_for_the_agent_that_made_it(corpus: Any, tmp_path: Path) -> None:
    exchange = _proposer({"system": "Complete the request with care, then answer."})
    report = _loop(corpus, tmp_path, exchange, rounds=1)
    stored = json.loads(next((tmp_path / "improve" / "runs").glob("baseline@*/train/run.json")).read_text())
    assert stored["agent_identity"] == {"kind": "PolicyAgent", "name": stored["agent"]}
    other: list[str] = []
    _loop(corpus, tmp_path, exchange, rounds=1, log=other, agent=OtherPolicyAgent)
    # The champion's pack, case set and grader all match what is on disk, but
    # another agent made that run, so it is run again rather than borrowed.
    assert report.initial["digest"] in other
    stored = json.loads(next((tmp_path / "improve" / "runs").glob("baseline@*/train/run.json")).read_text())
    assert stored["agent_identity"]["command"] == "other-harness"
    # The same holds in memory, within one loop.
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    made: list[Any] = []

    def agent_for(pack: Any) -> Any:
        made.append((OtherPolicyAgent if made else PolicyAgent)(pack, cases, []))
        return made[-1]

    ran: list[str] = []

    def run(subset: Any, agent: Any) -> Any:
        ran.append(agent.name)
        return run_cases(service_for(subset, records), subset, agent)

    improver = Improver(run=run, agent_for=agent_for, exchange=exchange, out=tmp_path / "memory")
    grader = grader_identity(None)
    baseline = packkit.resolve("agent:baseline")
    improver._pinned_run(baseline, cases, "train", grader)
    improver._pinned_run(baseline, cases, "train", grader)
    assert len(ran) == 2


_VERIFY_SKILL = {"skills": {"verify": "Walk every step the request needs and read each write back."}}


def test_a_second_loop_into_one_directory_keeps_the_first_loops_champion_and_receipts(corpus: Any, tmp_path: Path) -> None:
    first = _loop(corpus, tmp_path, _proposer(_VERIFY_SKILL), rounds=1)
    assert first.rounds[0].decision == "promoted" and first.champion["ref"] == "agent:baseline-r1"
    rounds_dir = tmp_path / "improve" / "rounds"
    receipt = (rounds_dir / "001.json").read_bytes()
    second = _loop(corpus, tmp_path, _proposer({"skills": {"verify": "Read every write back before you answer."}}),
                   rounds=1)
    # The numbering continues: the second loop's round is 2, its candidate r2.
    assert [item.round for item in second.rounds] == [2]
    assert second.rounds[0].candidate["ref"] == "agent:baseline-r2"
    assert (rounds_dir / "001.json").read_bytes() == receipt and (rounds_dir / "002.json").exists()
    # The first loop's champion is where it left it, pinned by digest.
    loop = ImproveLoop(session=None, agent=lambda pack: None, exchange=lambda payload: {},  # type: ignore[arg-type,return-value]
                       out=tmp_path / "improve")
    assert loop.champion(first).digest == first.champion["digest"]
    assert loop.champion(second).digest == second.champion["digest"]
    # A later loop from the promoted champion keeps its stem and the numbering,
    # and never reuses a name a receipt or the champion holds.
    improver = Improver(run=run_cases, agent_for=PolicyAgent, exchange=_proposer(),  # type: ignore[arg-type]
                        out=tmp_path / "improve")
    last, protected = improver._earlier()
    assert last == 2 and {"agent:baseline-r1", "agent:baseline-r2"} <= protected
    promoted = loop.champion(first)
    assert improver._candidate_name(promoted, round_stem(promoted.name), 3, protected) == "baseline-r3"
    for taken in (1, 2):
        renamed = improver._candidate_name(promoted, "baseline", taken, protected)
        assert re.fullmatch(rf"baseline-r{taken}-[0-9a-f]{{8}}", renamed), renamed


def test_candidate_names_keep_the_stem_and_never_shadow_a_champion(corpus: Any, tmp_path: Path) -> None:
    assert round_stem("ops-runner") == "ops-runner"
    assert round_stem("ops-runner-r2") == "ops-runner"
    assert round_stem("baseline-r3-1f2e3d4c") == "baseline"
    assert round_stem("baseline-rx") == "baseline-rx"
    roots = tmp_path / "roots"
    baseline = packkit.resolve("agent:baseline")
    for name in ("ops-runner", "baseline-r1"):
        packkit.install({"schema": "worldloom.pack/v1", "kind": "agent", "name": name, "body": baseline.data},
                        root=roots)
    report = _loop(corpus, tmp_path / "a", _proposer(_VERIFY_SKILL), rounds=1,
                   champion=packkit.resolve("agent:ops-runner", roots=[roots]), pack_roots=[roots])
    assert report.rounds[0].candidate["ref"] == "agent:ops-runner-r1"
    # A champion named like a round and kept outside the loop's root: the
    # candidate takes a suffixed name rather than shadowing it.
    held = packkit.resolve("agent:baseline-r1", roots=[roots])
    report = _loop(corpus, tmp_path / "b", _proposer(_VERIFY_SKILL), rounds=1, champion=held, pack_roots=[roots])
    name = report.rounds[0].candidate["ref"]
    assert re.fullmatch(r"agent:baseline-r1-[0-9a-f]{8}", name), name
    assert packkit.resolve(f"agent:baseline-r1@{held.digest}", roots=[tmp_path / "b" / "improve" / "packs", roots])


def test_declared_held_out_cases_never_train_even_beside_a_separate_holdout(corpus: Any, tmp_path: Path) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    sealed = [cases[0].model_copy(update={"dimensions": {**cases[0].dimensions, "split": "validation"}}),
              cases[1].model_copy(update={"row": {**cases[1].row, "dimensions": {"split": "test"}}})]
    training = [*sealed, *cases[2:5]]
    holdout = list(cases[5:])
    exchange = _proposer(_VERIFY_SKILL)
    report = improve(packkit.resolve("agent:baseline"), training,
                     run=lambda subset, agent: run_cases(service_for(subset, records), subset, agent),
                     agent_for=lambda pack: PolicyAgent(pack, cases, []), exchange=exchange,
                     out=tmp_path / "improve", holdout=holdout, rounds=1)
    assert report.train_cases == 3 and report.held_out_dropped == 2
    sealed_ids = {case.id for case in sealed}
    runs = tmp_path / "improve" / "runs"
    trained_at = next(runs.glob("baseline@*/train/run.json"))
    trained = json.loads(trained_at.read_text())
    assert trained["cases"] == 3
    assert sealed_ids.isdisjoint(row.case_id for row in read_run(trained_at.parent).results)
    assert not any(case_id in exchange.seen[0]["message"] for case_id in sealed_ids)
    # Held-out runs say so on the run itself; training runs do not.
    assert "split" not in trained
    held_runs = sorted(runs.glob("*/holdout/run.json"))
    assert held_runs and all(json.loads(path.read_text())["split"] == "holdout" for path in held_runs)
    assert read_run(held_runs[0].parent).split == "holdout"
    # Without a separate holdout the same cases join the held-out side.
    assert sealed_ids <= {case.id for case in split_cases(training, holdout_share=0.4)[1]}
    # A caller driving the Improver directly is refused rather than trusted.
    improver = Improver(run=run_cases, agent_for=PolicyAgent, exchange=exchange,  # type: ignore[arg-type]
                        out=tmp_path / "direct")
    with pytest.raises(ValueError, match="declare a held-out split"):
        improver.improve(packkit.resolve("agent:baseline"), training, holdout, rounds=1)
    assert improve_module.HELD_OUT_SPLITS is HELD_OUT_SPLITS


@pytest.mark.parametrize("error", [
    ValueError("claude exited 1; check its local installation and login"),
    TimeoutError("the proposer ran past its timeout"),
    OSError("codex: command not found"),
    json.JSONDecodeError("Expecting value", "", 0),
    ExecFailed("the proposer exited 2"),
])
def test_a_proposer_that_fails_leaves_a_receipt_and_stops_the_loop(corpus: Any, tmp_path: Path,
                                                                   error: Exception) -> None:
    def broken(payload: dict[str, Any]) -> dict[str, Any]:
        raise error

    report = _loop(corpus, tmp_path, broken, rounds=3)
    assert [item.decision for item in report.rounds] == ["proposer_error"]
    assert type(error).__name__ in report.rounds[0].reasons[0] and str(error) in report.rounds[0].reasons[0]
    stored = json.loads((tmp_path / "improve" / "rounds" / "001.json").read_text())
    assert stored["decision"] == "proposer_error"
    assert json.loads((tmp_path / "improve" / "improve.json").read_text())["champion"] == report.initial


def test_a_malformed_proposal_is_refused_with_findings_not_a_crash(corpus: Any, tmp_path: Path) -> None:
    def sloppy(payload: dict[str, Any]) -> dict[str, Any]:
        return {"request_id": payload["request_id"], "proposal": {"body": "a whole policy as prose"}}

    report = _loop(corpus, tmp_path, sloppy, rounds=1, authoring_rounds=2)
    only = report.rounds[0]
    assert only.decision == "refused" and len(only.authoring) == 2
    assert any(reason.startswith("proposal.name:") for reason in only.reasons), only.reasons


def test_the_cli_refuses_a_grader_that_drifts_with_its_own_code(corpus: Any, tmp_path: Path,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    case_set = tmp_path / "cases"
    write_jsonl(case_set / CASE_SET_FILE, list(cases_from_corpus(corpus)))
    write_jsonl(case_set / RECORDS_FILE, list(corpus.connector_data.records))

    def drifted(*args: Any, **kwargs: Any) -> Any:
        raise GraderDrift("the grader moved", pinned="aaa", current="bbb", changed=("rater",))

    monkeypatch.setattr(improve_module, "improve", drifted)
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["evalrun", "improve", str(case_set), "--agent-pack", "agent:baseline",
                                 "--exec", "true", "--proposer-exec", "true", "-o", str(tmp_path / "o")])
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output.strip().splitlines()[-1])
    assert envelope["refusal"] == "grader_drift" and envelope["data"]["changed"] == ["rater"]


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


def test_a_long_failure_brief_is_fitted_to_the_interview_limit(corpus: Any, tmp_path: Path) -> None:
    """Many failing cases make a long brief; the proposer still gets asked, with the most frequent findings."""
    from worldloom.evalrun.autopsy import autopsy as run_autopsy
    from worldloom.evalrun.improve import Improver
    from worldloom.packkit.authoring import MAX_MESSAGE, clip_message

    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    idle = run_cases(service_for(cases, records), cases, ScriptedAgent([], name="idle"))
    found = run_autopsy(idle, cases=cases)
    improver = Improver(run=lambda s, a: idle, agent_for=lambda p: None, exchange=lambda p: {}, out=tmp_path)
    champion = packkit.resolve("agent:baseline")
    # Inflate the message template's brief budget: a long champion ref eats into the room.
    brief = improver._fitted_brief(found, champion, 1)
    assert len(improver._message(champion, brief, 1)) <= MAX_MESSAGE
    huge = "x\n" * (MAX_MESSAGE * 2)
    clipped = clip_message(huge, 500)
    assert len(clipped) <= 500 and "more characters not shown" in clipped
