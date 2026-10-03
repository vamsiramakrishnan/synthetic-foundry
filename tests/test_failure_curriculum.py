"""Between improve rounds, new training cases aimed at the last champion's failures, never a held-out one.

The mapping from finding keys to the cases that exercise them is data
(`FINDING_TARGETS`, `UNMAPPABLE`); the first tests are its lint, and fail the
moment the autopsy can emit a key with no entry. The rest fix an autopsy and
a pool and check that the draw is deterministic, targets what the mapping
says, and never touches the held-out cases by id, content, source records or
gold DAG; then run the loop with and without the curriculum.
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
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.autopsy import Autopsy, Cluster
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.failure_curriculum import (
    FINDING_TARGETS,
    UNMAPPABLE,
    HeldOutOverlap,
    case_key,
    check_targets,
    check_unseen,
    dag_digest,
    draw_failure_cases,
    finding_vocabulary,
    source_digest,
)
from worldloom.evalrun.improve import improve, split_cases
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()
improve_module = importlib.import_module("worldloom.evalrun.improve")
SRC = Path(__file__).resolve().parents[1] / "src" / "worldloom" / "evalrun"


# -- the mapping's lint ---------------------------------------------------------------------------


def test_every_finding_key_is_mapped_or_declared_unmappable() -> None:
    assert check_targets() == []
    vocabulary = set(finding_vocabulary())
    assert vocabulary == set(FINDING_TARGETS) | set(UNMAPPABLE)
    assert not set(FINDING_TARGETS) & set(UNMAPPABLE)
    # The keys the task names are targeted, not waved through.
    for key in ("plan.missing:read", "query.missed_evidence", "outcomes.ungrounded"):
        assert key in FINDING_TARGETS


_KEY_LITERAL = re.compile(r"\"((?:plan|trajectory|outcomes|query|output|assertion|run)\.[a-z_]*[a-z](?::[a-z_]+)?|unclassified)\"")
_KEY_FAMILY = re.compile(r"f\"((?:plan|trajectory|outcomes|query|output|error)[a-z_.]*):\{")


def test_no_key_the_grader_writes_escapes_the_vocabulary() -> None:
    """A literal key or keyed family added to the modules that emit findings must reach the mapping."""
    vocabulary = set(finding_vocabulary())
    families = {key.split(":", 1)[0] for key in vocabulary if ":" in key}
    missing: list[str] = []
    for module in ("autopsy.py", "stages.py", "lineage.py"):
        text = (SRC / module).read_text(encoding="utf-8")
        for literal in _KEY_LITERAL.findall(text):
            if literal not in vocabulary and literal not in families:
                missing.append(f"{module}: {literal}")
        for family in _KEY_FAMILY.findall(text):
            if family not in families:
                missing.append(f"{module}: {family}:*")
    assert not missing, missing


# -- a fixed autopsy over a fixed pool ----------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(24)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


def _cluster(key: str, cases: int, dimensions: dict[str, dict[str, int]]) -> Cluster:
    return Cluster(key=key, axis=key.split(".", 1)[0], cases=cases, share_of_failures=cases / 10,
                   case_ids=tuple(f"x{index}" for index in range(cases)), dimensions=dimensions,
                   concentrations=(), exemplars=())


def _autopsy(*clusters: Cluster, omitted: dict[str, int] | None = None) -> Autopsy:
    return Autopsy(agent="fixed", case_set="fixed", cases=10, graded=10, errors=0, passed=0, failing=10,
                   base={}, clusters=clusters, omitted=omitted or {})


FIXED = _autopsy(
    _cluster("trajectory.failure_not_reached", 5, {"failure": {"permission_denied": 5},
                                                   "dag_shape": {"fan_in": 2, "map_read": 2, "write_chain": 1}}),
    _cluster("outcomes.unmet:create", 3, {"dag_shape": {"conditional": 2, "fan_in": 1}, "operation": {"draft": 3}}),
    _cluster("trajectory.question:acted_without_asking", 2, {"failure": {"none": 2}}),
    _cluster("run.errored", 1, {}),
    _cluster("plan.brand_new_finding", 1, {}),
    omitted={"plan.order": 1},
)


def _corner(case: Any, template: str) -> Any:
    """A pool case dressed as a corner case of *template*: only its `corner` dimension decides matching."""
    return case.model_copy(update={"id": f"corner-{template}-{case.id[:8]}",
                                   "row": {**case.row, "id": f"corner-{template}-{case.id[:8]}"},
                                   "dimensions": {**case.dimensions, "corner": template}})


def _sets(corpus: Any) -> tuple[list[Any], list[Any], list[Any]]:
    cases = list(cases_from_corpus(corpus))
    train, held = cases[:6], cases[6:8]
    pool = cases[8:20] + [_corner(cases[20], "restated_figure"), _corner(cases[21], "confirmed_cause")]
    return train, held, pool


def test_the_draw_is_deterministic_and_targets_the_mapped_templates(corpus: Any) -> None:
    train, held, pool = _sets(corpus)
    draw = draw_failure_cases(FIXED, pool, count=6, round=2, train=train, held=held)
    again = draw_failure_cases(FIXED, list(reversed(pool)), count=6, round=2, train=train, held=held)
    assert [case.id for case in draw.cases] == [case.id for case in again.cases]
    assert draw.record(source_round=1, train_cases=12, train_case_set="d") == \
        again.record(source_round=1, train_cases=12, train_case_set="d")
    assert len(draw.cases) == 6 and draw.shortfall == 0
    by_key = {target.key: target for target in draw.targets}
    leaked = by_key["trajectory.failure_not_reached"]
    # Funded by cluster size: 5 and 3 and 2 of 10 cases share six rows 3/2/1.
    assert (leaked.allotted, by_key["outcomes.unmet:create"].allotted,
            by_key["trajectory.question:acted_without_asking"].allotted) == (3, 2, 1)
    drawn = {case.id: case for case in draw.cases}
    # The designed-failure key follows the cluster's own failure, inside the designed kinds.
    assert leaked.where["failure"] == ("permission_denied",)
    assert all(drawn[case_id].dimensions["failure"] == "permission_denied" for case_id in leaked.case_ids)
    # The question key takes the restatement template and nothing else.
    question = by_key["trajectory.question:acted_without_asking"]
    assert question.templates == ("restated_figure",)
    assert [drawn[case_id].dimensions.get("corner") for case_id in question.case_ids] == ["restated_figure"]
    assert all(drawn[case_id].dimensions.get("corner") != "confirmed_cause" for case_id in leaked.case_ids)
    # Every cluster the curriculum declines is accounted for, with its reason.
    reasons = {key: reason for key, _, reason in draw.unmappable}
    assert reasons["run.errored"] == UNMAPPABLE["run.errored"]
    assert "no entry in FINDING_TARGETS" in reasons["plan.brand_new_finding"]
    assert reasons["plan.order"] == "beyond the autopsy's top clusters"
    # A different round draws in a different order but from the same targets.
    other = draw_failure_cases(FIXED, pool, count=6, round=3, train=train, held=held)
    assert {target.key for target in other.targets} == set(by_key)


def test_a_cluster_that_cannot_fill_gives_its_rows_to_the_others(corpus: Any) -> None:
    train, held, pool = _sets(corpus)
    draw = draw_failure_cases(FIXED, pool, count=20, round=2, train=train, held=held)
    by_key = {target.key: target for target in draw.targets}
    # One restatement corner in the pool: the question cluster draws it and
    # the rest of its share goes to the clusters that still have cases.
    assert len(by_key["trajectory.question:acted_without_asking"].case_ids) == 1
    assert len(draw.cases) == len({case_key(case) for case in draw.cases})
    assert draw.shortfall == 20 - len(draw.cases)


def test_held_out_cases_are_never_drawn_by_id_content_source_or_dag(corpus: Any) -> None:
    train, held, pool = _sets(corpus)
    twin = held[0].model_copy(update={"id": "renamed-held-case"})            # same row: same records, same DAG
    # Same records as a held-out case, under another id and another DAG.
    sealed_evidence = held[1].model_copy(update={"id": "other-dag", "row": {
        **held[1].row, "expected_dag": {**held[1].row["expected_dag"], "edges": []}}})
    declared = pool[1].model_copy(update={"id": "declared-test",
                                          "dimensions": {**pool[1].dimensions, "split": "test"}})
    retrained = train[0].model_copy(update={"id": "renamed-training-case"})
    poisoned = [*pool, *held, twin, sealed_evidence, declared, retrained]
    draw = draw_failure_cases(FIXED, poisoned, count=40, round=2, train=train, held=held)
    drawn = draw.cases
    assert drawn
    held_ids = {case.id for case in held}
    held_sources = {source_digest(case) for case in held} - {None}
    held_dags = {dag_digest(case) for case in held} - {None}
    assert not {case.id for case in drawn} & held_ids
    assert not {case_key(case) for case in drawn} & {case_key(case) for case in held}
    assert not {source_digest(case) for case in drawn} & held_sources
    assert not {dag_digest(case) for case in drawn} & held_dags
    assert not {"renamed-held-case", "other-dag", "declared-test"} & {case.id for case in drawn}
    assert draw.excluded["held_out"] >= 5
    check_unseen(drawn, held)
    with pytest.raises(HeldOutOverlap, match="source-record digest"):
        check_unseen([sealed_evidence], held)
    with pytest.raises(HeldOutOverlap, match="gold-DAG digest"):
        check_unseen([twin], held)
    # Nor a training case again, under its own id or another.
    assert not {case.id for case in drawn} & {case.id for case in train}
    assert "renamed-training-case" not in {case.id for case in drawn} and draw.excluded["duplicate"] >= 1


# -- the loop ------------------------------------------------------------------------------------


class PolicyAgent:
    """Walks the expected DAG when its policy teaches `verify`; otherwise does nothing."""

    def __init__(self, pack: Any, cases: Any) -> None:
        self.pack = pack
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.skilled = "verify" in pack.body.skills
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")

    def run(self, task: Any, tools: Any) -> Any:
        return (self.reference if self.skilled else self.idle).run(task, tools)


def _rewording(payload: dict[str, Any]) -> dict[str, Any]:
    body = {**payload["draft"]["body"], "system": f"Be careful. ({payload['request_id'][:6]})"}
    return {"request_id": payload["request_id"], "message": "reworded",
            "proposal": {"name": payload["draft"]["name"], "body": body}}


def _loop(corpus: Any, out: Path, **options: Any) -> Any:
    everything = list(cases_from_corpus(corpus))
    cases, pool = everything[:8], everything[8:]
    records = corpus.connector_data.records

    def run(subset: Any, agent: Any) -> Any:
        return run_cases(service_for(subset, records), subset, agent)

    if options.pop("with_pool", False):
        options["curriculum_pool"] = pool
    return improve(packkit.resolve("agent:baseline"), cases, run=run,
                   agent_for=lambda pack: PolicyAgent(pack, everything), exchange=_rewording, out=out,
                   holdout_share=0.4, rounds=3, **options)


def test_the_loop_adds_cases_from_the_last_champion_failures(corpus: Any, tmp_path: Path) -> None:
    report = _loop(corpus, tmp_path / "a", curriculum="failures", curriculum_cases=3, with_pool=True)
    assert [item.decision for item in report.rounds] == ["rejected"] * 3
    first, second, third = report.rounds
    assert first.curriculum is None
    record = second.curriculum
    assert record is not None and record["source_round"] == 1 and record["mode"] == "failures"
    assert record["added"] == 3 and record["train_cases"] == record["added"] + report.train_cases
    # Every new case is attributed to the failing cluster of round 1 that drew it.
    assert {target["key"] for target in record["targets"]} <= set(first.clusters)
    drawn = [case["id"] for target in record["targets"] for case in target["cases"]]
    assert len(drawn) == 3
    assert third.curriculum is not None and third.curriculum["source_round"] == 2
    assert third.curriculum["train_cases"] == record["train_cases"] + third.curriculum["added"]
    # None of them is held out, and none of them came from CORPUS's own cases.
    everything = list(cases_from_corpus(corpus))
    _, held = split_cases(everything[:8], holdout_share=0.4)
    pool_ids = {case.id for case in everything[8:]}
    all_drawn = drawn + [case["id"] for target in third.curriculum["targets"] for case in target["cases"]]
    assert set(all_drawn) <= pool_ids and not set(all_drawn) & {case.id for case in held}
    # The grown set is run under its own label and recorded on disk.
    stored = json.loads((tmp_path / "a" / "rounds" / "002.json").read_text(encoding="utf-8"))
    assert stored["curriculum"] == json.loads(json.dumps(record))
    assert "curriculum" not in json.loads((tmp_path / "a" / "rounds" / "001.json").read_text(encoding="utf-8"))
    assert list((tmp_path / "a" / "runs").glob(f"baseline@*/train-{record['train_case_set'][:12]}/run.json"))
    summary = json.loads((tmp_path / "a" / "improve.json").read_text(encoding="utf-8"))["curriculum"]
    assert summary["added"] == record["added"] + third.curriculum["added"]
    assert summary["final_train_cases"] == report.train_cases + summary["added"]
    # The same loop again draws the same cases.
    again = _loop(corpus, tmp_path / "b", curriculum="failures", curriculum_cases=3, with_pool=True)
    assert again.rounds[1].curriculum == record


def test_without_a_curriculum_the_loop_is_unchanged(corpus: Any, tmp_path: Path) -> None:
    report = _loop(corpus, tmp_path / "plain")
    assert all(item.curriculum is None for item in report.rounds)
    for path in sorted((tmp_path / "plain" / "rounds").glob("*.json")):
        assert "curriculum" not in json.loads(path.read_text(encoding="utf-8"))
    assert "curriculum" not in json.loads((tmp_path / "plain" / "improve.json").read_text(encoding="utf-8"))
    labels = {path.parent.name for path in (tmp_path / "plain" / "runs").glob("*/*/run.json")}
    assert labels == {"train"}
    with pytest.raises(ValueError, match="curriculum='failures'"):
        _loop(corpus, tmp_path / "x", curriculum_cases=2)
    with pytest.raises(ValueError, match="unknown curriculum"):
        _loop(corpus, tmp_path / "y", curriculum="harder")
    with pytest.raises(ValueError, match="value table"):
        _loop(corpus, tmp_path / "z", curriculum="failures", values={})


def test_the_cli_draws_from_the_cases_limit_left_out(corpus: Any, tmp_path: Path,
                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    case_set = tmp_path / "cases"
    write_jsonl(case_set / CASE_SET_FILE, list(cases_from_corpus(corpus)))
    write_jsonl(case_set / RECORDS_FILE, list(corpus.connector_data.records))
    seen: dict[str, Any] = {}

    def capture(champion: Any, cases: Any, **kwargs: Any) -> Any:
        seen.update(kwargs, cases=cases)
        raise ValueError("stop here")

    monkeypatch.setattr(improve_module, "improve", capture)
    base = ["evalrun", "improve", str(case_set), "--agent-pack", "agent:baseline", "--exec", "true",
            "--proposer-exec", "true", "-o", str(tmp_path / "o"), "--limit", "8"]
    runner.invoke(app, [*base, "--curriculum", "failures", "--curriculum-cases", "2"])
    assert seen["curriculum"] == "failures" and seen["curriculum_cases"] == 2
    assert len(seen["cases"]) == 8 and len(seen["curriculum_pool"]) == 16
    assert not {case.id for case in seen["curriculum_pool"]} & {case.id for case in seen["cases"]}
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, [*base, "--curriculum", "harder"])
    assert result.exit_code == 2 and json.loads(result.output.strip().splitlines()[-1])["refusal"] == "unknown_curriculum"
    result = runner.invoke(app, [*base, "--curriculum-cases", "2"])
    assert result.exit_code == 2 and json.loads(result.output.strip().splitlines()[-1])["refusal"] == "missing_flag"
    result = runner.invoke(app, [*base, "--curriculum", "failures", "--value"])
    assert result.exit_code == 2 and json.loads(result.output.strip().splitlines()[-1])["refusal"] == "cannot_combine"
