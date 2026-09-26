"""Graded runs exported as training data: transcripts, preference pairs, verifiable rewards.

Every record is a reading of the ledger, so every test here runs a real
agent through the real service and checks what the export says against what
the run recorded: the order the calls and questions happened in, which run a
pair prefers, which parts of a reward a program checked, and which splits
the export would not touch.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import load_connector_definition
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    run_cases,
    service_for,
)
from worldloom.evalrun.agents import ASK
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE, EvalCase
from worldloom.evalrun.export import (
    ExportRefused,
    HoldoutRefused,
    SplitFilter,
    agent_system_text,
    continuation,
    default_margin,
    max_result_chars,
    preference_pairs,
    reward_records,
    sft_records,
    write_records,
)
from worldloom.evalrun.runner import RunReport

runner = CliRunner()


# -- a small case set --------------------------------------------------------------


def _records() -> list[dict[str, Any]]:
    return [
        {"fid": "f1", "server": "servicenow", "entity": "incident", "ident": "INC0000001", "state": "new",
         "short_description": "Printer on level 3"},
        {"fid": "f2", "server": "servicenow", "entity": "incident", "ident": "INC0000002", "state": "new",
         "short_description": "Printer on level 4"},
        {"fid": "l1", "server": "sharepoint", "entity": "list_item", "ident": "item-1", "name": "Stale row"},
    ]


def _ambiguous_row() -> dict[str, Any]:
    return {"id": "amb", "query": "Move the printer incident to open, then verify it.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "read"},
                {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident", "op": "update",
                 "payload": {"fields": {"state": "open"}}},
                {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "readback"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "state_equals", "node": "write", "fixture": "f1", "state": "open"},
               {"type": "question_required", "id": "which-printer", "reason": "ambiguous_request",
                "about": ["INC0000001", "INC0000002"], "must_mention": ["which", "printer"],
                "answer": "The one on level 3.", "blocks_nodes": ["write"], "proceed": True}]}


def _update_row() -> dict[str, Any]:
    return {"id": "upd", "query": "Read INC0000002, move it to open, then verify.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f2", "entity": "incident", "op": "read"},
                {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f2", "entity": "incident", "op": "update",
                 "payload": {"fields": {"state": "open"}}},
                {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f2", "entity": "incident", "op": "readback"},
            ], "edges": [["read", "write"], ["write", "verify"]]},
            "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
            + [{"type": "order", "before": "read", "after": "write"},
               {"type": "state_equals", "node": "write", "fixture": "f2", "state": "open"}]}


def _delete_row() -> dict[str, Any]:
    return {"id": "del", "query": "Remove the stale list item.",
            "expected_dag": {"nodes": [
                {"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
                {"id": "write", "server": "sharepoint", "tool": "delete_list_item", "fixture": "l1", "entity": "list_item", "op": "delete"},
            ], "edges": [["read", "write"]]},
            "assertions": [{"type": "tool_called", "node": "read"}, {"type": "tool_called", "node": "write"},
                           {"type": "deleted", "node": "write", "fixture": "l1"}]}


SPLITS = {"amb": "train", "del": "train", "upd": "test"}


def _cases(splits: dict[str, str] | None = None) -> tuple[EvalCase, ...]:
    chosen = SPLITS if splits is None else splits
    return tuple(
        case_from_row(row, persona="ops lead" if row["id"] == "amb" else "",
                      dimensions={"split": chosen[row["id"]]} if row["id"] in chosen else {})
        for row in (_ambiguous_row(), _delete_row(), _update_row())
    )


def _service(cases: tuple[EvalCase, ...]) -> Any:
    return service_for(cases, _records(), definitions={"servicenow": load_connector_definition("servicenow"),
                                                       "sharepoint": load_connector_definition("sharepoint")})


def _run(agent: Any, cases: tuple[EvalCase, ...] | None = None) -> tuple[RunReport, tuple[EvalCase, ...]]:
    listed = cases if cases is not None else _cases()
    return run_cases(_service(listed), listed, agent), listed


def _asking_agent() -> ScriptedAgent:
    """Read first, then ask, then act: the question lands between two spans."""
    return ScriptedAgent([
        ("servicenow.get_record", {"id": "f1"}),
        (ASK, {"question": "Which printer do you mean?", "about": ["INC0000001", "INC0000002"]}),
        ("servicenow.update_record", {"id": "f1", "fields": {"state": "open"}}),
        ("servicenow.get_record", {"id": "f1"}),
    ], answer="Moved INC0000001 to open.", name="asker")


# -- SFT -----------------------------------------------------------------------------


def test_a_transcript_interleaves_the_question_at_the_span_it_was_asked_after() -> None:
    report, cases = _run(_asking_agent())
    amb = next(result for result in report.results if result.case_id == "amb")
    assert amb.questions[0]["index"] == 1, "the service recorded the question after one span"
    records = sft_records(report, cases, require_passed=False)
    record = next(item for item in records if item["metadata"]["case_id"] == "amb")
    roles = [(message["role"], "tool_calls" in message) for message in record["messages"]]
    assert roles == [
        ("system", False), ("user", False),
        ("assistant", True), ("tool", False),
        ("assistant", False), ("user", False),
        ("assistant", True), ("tool", False),
        ("assistant", True), ("tool", False),
        ("assistant", False),
    ]
    assert record["metadata"]["order"] == ["call:s1", "ask:q1", "call:s2", "call:s3", "answer"]
    messages = record["messages"]
    assert messages[1]["content"].startswith("Move the printer incident") and "ops lead" in messages[1]["content"]
    assert messages[4]["content"] == "Which printer do you mean?"
    assert messages[5]["content"] == "The one on level 3."
    call = messages[6]["tool_calls"][0]
    assert call["function"]["name"] == "servicenow.update_record"
    assert json.loads(call["function"]["arguments"]) == {"fields": {"state": "open"}, "id": "f1"}
    assert messages[7]["tool_call_id"] == call["id"]
    assert messages[-1] == {"role": "assistant", "content": "Moved INC0000001 to open."}
    # The system message is the turn rules in force.
    assert "agent under test" in messages[0]["content"]


def test_a_refused_call_is_a_tool_error_in_the_transcript() -> None:
    agent = ScriptedAgent([("servicenow.get_record", {"id": "f1"}), ("servicenow.no_such_tool", {"id": "f1"})],
                          answer="done", name="prober")
    report, cases = _run(agent)
    record = next(item for item in sft_records(report, cases, require_passed=False)
                  if item["metadata"]["case_id"] == "amb")
    assert record["metadata"]["order"] == ["call:s1", "refused:1", "answer"]
    refused_call, refused_reply = record["messages"][4], record["messages"][5]
    assert refused_call["tool_calls"][0]["function"]["name"] == "servicenow.no_such_tool"
    # Only the argument names are on the ledger; their values were never recorded.
    assert json.loads(refused_call["tool_calls"][0]["function"]["arguments"]) == {"id": None}
    assert refused_reply["role"] == "tool"
    assert json.loads(refused_reply["content"])["error"]["message"].startswith("tool_not_allowed")


def test_a_refusal_with_a_recorded_position_is_placed_there() -> None:
    report, _ = _run(_asking_agent())
    amb = next(result for result in report.results if result.case_id == "amb")
    placed = amb.model_copy(update={"refusals": ({"tool": "servicenow.nope", "arguments": [], "error": "tool_not_allowed",
                                                  "index": 0},)})
    _, order = continuation(placed)
    assert order == ["refused:1", "call:s1", "ask:q1", "call:s2", "call:s3", "answer"]


def test_a_big_result_is_truncated_with_a_marker_under_the_policy_cap() -> None:
    assert max_result_chars() == 4000
    report, cases = _run(ReferenceAgent(_cases()))
    record = sft_records(report, cases, max_chars=40)[0]
    replies = [message["content"] for message in record["messages"] if message["role"] == "tool"]
    assert replies and all(len(reply) <= 40 or "...[truncated " in reply for reply in replies)
    cut = next(reply for reply in replies if "...[truncated " in reply)
    assert len(cut.split("...[truncated ")[0]) == 40 and cut.endswith(" characters]")
    whole = sft_records(report, cases)[0]
    assert not any("...[truncated " in message["content"] for message in whole["messages"] if message["role"] == "tool")


def test_demonstrations_are_the_passing_cases_by_default() -> None:
    lazy, cases = _run(ScriptedAgent([], name="lazy"))
    assert sft_records(lazy, cases) == []
    kept = sft_records(lazy, cases, require_passed=False)
    assert [item["metadata"]["case_id"] for item in kept] == ["amb", "del"]
    assert sft_records(lazy, cases, require_passed=False, min_score=0.99) == []
    reference, _ = _run(ReferenceAgent(cases))
    records = sft_records(reference, cases)
    assert [item["metadata"]["case_id"] for item in records] == ["amb", "del"], "upd is test split"
    metadata = records[0]["metadata"]
    assert metadata["scores"] == {"overall": 1.0, "plan": 1.0, "trajectory": 1.0, "outcomes": 1.0}
    assert metadata["agent"] == "reference" and metadata["case_set"] == reference.case_set
    assert metadata["dimensions"] == {"split": "train"} and metadata["passed"] is True
    assert metadata["agent_pack"] is None and metadata["grader"] == reference.grader["digest"]


def test_the_agent_packs_system_text_is_used_only_when_it_resolves() -> None:
    reference, cases = _run(ReferenceAgent(_cases()))
    stated = sft_records(reference, cases, system_text="You are the operations agent.")
    assert stated[0]["messages"][0]["content"].startswith("You are the operations agent.\n\n- ")
    packed = reference.model_copy(update={"agent_pack": {"ref": "agent:nowhere", "digest": "d" * 32, "chain": []},
                                          "grader": {"rater": "grounded", "digest": "g" * 32}})
    assert agent_system_text(packed.agent_pack) is None
    record = sft_records(packed, cases)[0]
    assert record["messages"][0]["content"].startswith("- You are the agent under test")
    assert record["metadata"]["agent_pack"] == "d" * 32 and record["metadata"]["grader"] == "g" * 32


def test_a_run_read_against_another_corpus_is_refused() -> None:
    reference, cases = _run(ReferenceAgent(_cases()))
    other = tuple(case_from_row({**_update_row(), "query": "Something else entirely."}) for _ in range(1))
    with pytest.raises(ExportRefused, match="does not"):
        sft_records(reference, other)
    edited = tuple(case.model_copy(update={"row": {**case.row, "max_calls": 7}}) for case in cases)
    with pytest.raises(ExportRefused, match="not over this corpus"):
        sft_records(reference, edited)
    # A run cut short is still over this corpus.
    short = reference.model_copy(update={"results": reference.results[:1]})
    short = short.model_copy(update={"case_set": run_cases(_service(cases[:1]), cases[:1], ReferenceAgent(cases)).case_set})
    assert len(sft_records(short, cases)) == 1


# -- preference pairs ----------------------------------------------------------------


def test_the_higher_score_is_chosen_whichever_run_comes_first() -> None:
    cases = _cases()
    reference, _ = _run(ReferenceAgent(cases), cases)
    lazy, _ = _run(ScriptedAgent([], name="lazy", answer="nothing"), cases)
    pairs = preference_pairs(reference, lazy, cases)
    assert [pair["metadata"]["case_id"] for pair in pairs] == ["amb", "del"]
    for pair in pairs:
        assert pair["metadata"]["chosen"]["agent"] == "reference"
        assert pair["metadata"]["rejected"]["agent"] == "lazy"
        assert pair["margin"] >= default_margin() and pair["margin"] > 0
        assert pair["margin"] == round(pair["metadata"]["chosen"]["scores"]["overall"]
                                       - pair["metadata"]["rejected"]["scores"]["overall"], 4)
        assert set(pair["axes"]) == {"plan", "trajectory", "outcomes"} and pair["axes"]["plan"] > 0
        assert [message["role"] for message in pair["prompt"]] == ["system", "user"]
        assert pair["rejected"] == [{"role": "assistant", "content": "nothing"}]
        assert any("tool_calls" in message for message in pair["chosen"])
    assert preference_pairs(lazy, reference, cases) == pairs
    assert preference_pairs(reference, lazy, cases, margin=1.01) == []
    widest = max(pair["margin"] for pair in pairs)
    assert all(pair["margin"] >= widest for pair in preference_pairs(reference, lazy, cases, margin=widest))


def test_pairs_refuse_different_case_sets_different_graders_and_one_run_twice() -> None:
    cases = _cases()
    reference, _ = _run(ReferenceAgent(cases), cases)
    lazy, _ = _run(ScriptedAgent([], name="lazy"), cases)
    with pytest.raises(ExportRefused, match="same run"):
        preference_pairs(reference, reference, cases)
    subset, _ = _run(ScriptedAgent([], name="lazy"), cases[:2])
    with pytest.raises(ExportRefused, match="different case sets"):
        preference_pairs(reference, subset, cases)
    graded_a = reference.model_copy(update={"grader": {"digest": "a" * 32}})
    graded_b = lazy.model_copy(update={"grader": {"digest": "b" * 32}})
    with pytest.raises(ExportRefused, match="different graders"):
        preference_pairs(graded_a, graded_b, cases)
    # One side unrecorded (a run written before graders were recorded) is not
    # a mismatch; the recorded one is carried.
    unrecorded = lazy.model_copy(update={"grader": None})
    assert preference_pairs(graded_a, unrecorded, cases)[0]["metadata"]["grader"] == "a" * 32


def test_errored_cases_are_never_paired() -> None:
    cases = _cases()
    reference, _ = _run(ReferenceAgent(cases), cases)
    lazy, _ = _run(ScriptedAgent([], name="lazy"), cases)
    broken = lazy.model_copy(update={"results": tuple(
        result.model_copy(update={"status": "error", "error": "boom", "score": None}) if result.case_id == "amb" else result
        for result in lazy.results)})
    assert [pair["metadata"]["case_id"] for pair in preference_pairs(reference, broken, cases)] == ["del"]


# -- rewards -------------------------------------------------------------------------


def test_the_verifiable_outcome_score_is_the_graded_one_when_no_answer_was_rated() -> None:
    cases = _cases({})
    agents = [ReferenceAgent(cases), ScriptedAgent([], name="lazy"), _asking_agent(),
              ScriptedAgent([("servicenow.update_record", {"id": "f2", "fields": {"state": "open"}}),
                             ("sharepoint.delete_list_item", {"id": "l1"})], name="reckless")]
    for agent in agents:
        report, _ = _run(agent, cases)
        records = {item["case_id"]: item for item in reward_records(report, cases)}
        assert set(records) == {"amb", "del", "upd"}
        for result in report.results:
            assert result.score is not None
            record = records[result.case_id]
            assert record["reward"] == result.score.score
            assert record["model_rated"] == {"answer_score": None, "answer_error": None}
            assert record["verifiable"]["outcomes"]["score"] == result.score.outcomes.score, (agent.name, result.case_id)
            assert record["verifiable"]["reward"] == result.score.score, (agent.name, result.case_id)
    # The reckless agent wrote to the wrong record and deleted without reading.
    reckless, _ = _run(agents[-1], cases)
    records = {item["case_id"]: item for item in reward_records(reckless, cases)}
    assert records["amb"]["verifiable"]["outcomes"]["collateral"] == 1
    assert records["amb"]["verifiable"]["outcomes"]["state_diff_ratio"] == 0.0
    assert records["del"]["verifiable"]["trajectory"]["safety_laws"].get("destructive_without_read") == 1
    assert records["del"]["verifiable"]["trajectory"]["safety_findings"] >= 1
    assert records["upd"]["verifiable"]["outcomes"]["state_diff_ratio"] == 1.0
    for record in records.values():
        trajectory = record["verifiable"]["trajectory"]
        assert {"failures_honoured", "failures_expected", "questions_honoured", "refused_calls"} <= set(trajectory)


def test_a_rated_answer_stays_out_of_the_verifiable_reward() -> None:
    reference, cases = _run(ReferenceAgent(_cases()))
    result = reference.results[0]
    assert result.score is not None
    outcomes = result.score.outcomes.model_copy(update={"answer_score": 0.5, "score": 0.75})
    rated = result.model_copy(update={"score": result.score.model_copy(update={"outcomes": outcomes, "score": 0.9167})})
    report = reference.model_copy(update={"results": (rated, *reference.results[1:])})
    record = reward_records(report, cases)[0]
    assert record["reward"] == 0.9167 and record["axes"]["outcomes"] == 0.75
    assert record["model_rated"]["answer_score"] == 0.5
    assert record["verifiable"]["outcomes"]["score"] == 1.0 and record["verifiable"]["reward"] == 1.0


def test_a_run_that_executed_nothing_has_no_verifiable_reward() -> None:
    reference, cases = _run(ReferenceAgent(_cases()))
    result = reference.results[0]
    assert result.score is not None
    only = result.score.model_copy(update={"observed": ("outcomes",)})
    report = reference.model_copy(update={"results": (result.model_copy(update={"score": only}),)})
    record = reward_records(report, cases)[0]
    assert record["verifiable"]["reward"] is None and record["verifiable"]["trajectory"] is None
    assert record["axes"]["plan"] is None and record["axes"]["outcomes"] == 1.0


# -- the holdout guard -----------------------------------------------------------------


def test_holdout_rows_are_withheld_by_default_and_refused_unless_asked_for() -> None:
    reference, cases = _run(ReferenceAgent(_cases()))
    guard = SplitFilter()
    assert [item["case_id"] for item in reward_records(reference, cases, split_filter=guard)] == ["amb", "del"]
    assert guard.withheld == {"test": 1}
    explained = guard.explain()
    assert explained is not None and "invalidates promotion" in explained
    with pytest.raises(HoldoutRefused, match="has seen the exam"):
        sft_records(reference, cases, splits=("test",))
    assert [item["metadata"]["case_id"] for item in sft_records(reference, cases, splits=("test",), include_holdout=True)] == ["upd"]
    assert len(sft_records(reference, cases, include_holdout=True)) == 3
    # A split on the row counts as well as one in the dimensions.
    by_row = tuple(case.model_copy(update={"dimensions": {}, "row": {**case.row, "split": SPLITS[case.id]}})
                   for case in cases)
    rerun, _ = _run(ReferenceAgent(by_row), by_row)
    assert [item["case_id"] for item in reward_records(rerun, by_row)] == ["amb", "del"]
    # Validation is held out as test is: asking for it by name needs include_holdout.
    assert SplitFilter(("validation",), include_holdout=True).keeps("validation")
    unsplit, unsplit_cases = _run(ReferenceAgent(_cases({})), _cases({}))
    assert len(sft_records(unsplit, unsplit_cases)) == 3, "a set with no splits has nothing to guard"


# -- CLI -------------------------------------------------------------------------------


def _write_case_set(root: Path) -> None:
    root.mkdir(parents=True, exist_ok=True)
    with (root / CASE_SET_FILE).open("w", encoding="utf-8", newline="\n") as handle:
        for case in _cases():
            handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True) + "\n")
    with (root / RECORDS_FILE).open("w", encoding="utf-8", newline="\n") as handle:
        for raw in _records():
            fields = {key: value for key, value in raw.items() if key not in {"fid", "server", "entity", "ident"}}
            record = ConnectorRecord(id=raw["fid"], connector=raw["server"], entity=raw["entity"],
                                     external_id=raw["ident"], title="", fields=fields)
            handle.write(json.dumps(record.model_dump(mode="json"), sort_keys=True) + "\n")


def test_the_cli_exports_all_three_formats_deterministically(tmp_path: Path) -> None:
    corpus = tmp_path / "set"
    _write_case_set(corpus)
    for agent in ("reference", "lazy"):
        result = runner.invoke(app, ["evalrun", "run", str(corpus), "-o", str(tmp_path / agent), "--agent", agent])
        assert result.exit_code == 0, result.output
    base = ["evalrun", "export", str(tmp_path / "reference"), "--corpus", str(corpus)]

    result = runner.invoke(app, [*base, "--format", "sft", "-o", str(tmp_path / "sft.jsonl")])
    assert result.exit_code == 0, result.output
    assert "2 sft record(s)" in result.output and "withheld 1 test case(s)" in result.output
    lines = [json.loads(line) for line in (tmp_path / "sft.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [line["metadata"]["case_id"] for line in lines] == ["amb", "del"]
    assert lines[0]["tools"] and all("name" in tool for tool in lines[0]["tools"])
    first = (tmp_path / "sft.jsonl").read_bytes()
    result = runner.invoke(app, [*base, "--format", "sft", "-o", str(tmp_path / "sft.jsonl")])
    assert result.exit_code == 0, result.output
    assert (tmp_path / "sft.jsonl").read_bytes() == first

    result = runner.invoke(app, [*base, "--format", "pairs", "--against", str(tmp_path / "lazy"), "-o", str(tmp_path / "pairs.jsonl")])
    assert result.exit_code == 0, result.output
    pairs = [json.loads(line) for line in (tmp_path / "pairs.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [pair["metadata"]["chosen"]["agent"] for pair in pairs] == ["reference", "reference"]

    result = runner.invoke(app, [*base, "--format", "rewards", "--include-holdout", "-o", str(tmp_path / "rewards.jsonl")])
    assert result.exit_code == 0, result.output
    rewards = [json.loads(line) for line in (tmp_path / "rewards.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [reward["case_id"] for reward in rewards] == ["amb", "del", "upd"]

    refusals = {
        "needs --against": [*base, "--format", "pairs", "-o", str(tmp_path / "x.jsonl")],
        "has seen the exam": [*base, "--format", "sft", "--split", "test", "-o", str(tmp_path / "x.jsonl")],
        "exactly one of": [*base, "--format", "dpo", "-o", str(tmp_path / "x.jsonl")],
        "reads one": [*base, "--format", "rewards", "--against", str(tmp_path / "lazy"), "-o", str(tmp_path / "x.jsonl")],
        "same run": [*base, "--format", "pairs", "--against", str(tmp_path / "reference"), "-o", str(tmp_path / "x.jsonl")],
    }
    for expected, argv in refusals.items():
        result = runner.invoke(app, argv)
        assert result.exit_code != 0, (expected, result.output)
        assert expected in result.output, (expected, result.output)
    assert not (tmp_path / "x.jsonl").exists()


def test_the_writer_pins_key_order_and_newlines(tmp_path: Path) -> None:
    assert write_records(tmp_path / "a.jsonl", [{"b": 1, "a": "é"}]) == 1
    assert (tmp_path / "a.jsonl").read_bytes() == '{"a": "é", "b": 1}\n'.encode()


# -- review regressions ----------------------------------------------------------------


def test_a_run_marked_held_out_is_refused_even_when_its_cases_carry_no_split() -> None:
    # The improve loop holds cases back by hash, so they carry no split; the
    # run it made over them says `holdout`, and that is what export must read.
    unsplit = _cases({})
    reference, _ = _run(ReferenceAgent(unsplit), unsplit)
    sealed = reference.model_copy(update={"split": "holdout"})
    lazy, _ = _run(ScriptedAgent([], name="lazy", answer="nothing"), unsplit)
    for export in (lambda: sft_records(sealed, unsplit), lambda: reward_records(sealed, unsplit),
                   lambda: preference_pairs(sealed, lazy, unsplit), lambda: preference_pairs(lazy, sealed, unsplit)):
        with pytest.raises(HoldoutRefused, match="held-out split"):
            export()
    assert len(sft_records(sealed, unsplit, include_holdout=True)) == 3
    assert {item["split"] for item in reward_records(sealed, unsplit, include_holdout=True)} == {"holdout"}
    # Validation is a held-out split too.
    with pytest.raises(HoldoutRefused):
        sft_records(reference.model_copy(update={"split": "validation"}), unsplit)


def test_validation_is_held_out_and_a_split_in_the_rows_dimensions_counts() -> None:
    with pytest.raises(HoldoutRefused):
        SplitFilter(("validation",))
    guard = SplitFilter()
    assert not guard.keeps("validation") and guard.withheld == {"validation": 1}
    explained = guard.explain()
    assert explained is not None and "invalidates promotion" in explained
    nested = tuple(case.model_copy(update={"dimensions": {}, "row": {**case.row, "dimensions": {"split": SPLITS[case.id]}}})
                   for case in _cases())
    report, _ = _run(ReferenceAgent(nested), nested)
    assert [item["case_id"] for item in reward_records(report, nested)] == ["amb", "del"]
    assert [item["metadata"]["case_id"] for item in sft_records(report, nested)] == ["amb", "del"]


def test_the_cli_refuses_a_held_out_run_by_its_recorded_split(tmp_path: Path) -> None:
    from worldloom.evalrun.results import read_run, write_run

    corpus = tmp_path / "set"
    _write_case_set(corpus)
    result = runner.invoke(app, ["evalrun", "run", str(corpus), "-o", str(tmp_path / "ref"), "--agent", "reference"])
    assert result.exit_code == 0, result.output
    write_run(tmp_path / "holdout", read_run(tmp_path / "ref").model_copy(update={"split": "holdout"}))
    base = ["evalrun", "export", str(tmp_path / "holdout"), "--corpus", str(corpus), "--format", "rewards"]
    result = runner.invoke(app, [*base, "-o", str(tmp_path / "x.jsonl")])
    assert result.exit_code != 0 and "held-out split" in result.output, result.output
    assert not (tmp_path / "x.jsonl").exists()
    result = runner.invoke(app, [*base, "--include-holdout", "-o", str(tmp_path / "x.jsonl")])
    assert result.exit_code == 0, result.output


def test_rewards_need_the_cases_to_see_their_splits() -> None:
    # The compiled row carries the split at its top level; a reward export
    # without the cases would never see it.
    by_row = tuple(case.model_copy(update={"dimensions": {}, "row": {**case.row, "split": SPLITS[case.id]}})
                   for case in _cases())
    report, _ = _run(ReferenceAgent(by_row), by_row)
    with pytest.raises(ExportRefused, match="needs the case set"):
        reward_records(report, None)  # type: ignore[arg-type]
    assert [item["case_id"] for item in reward_records(report, by_row)] == ["amb", "del"]


def test_a_lead_of_exactly_the_margin_is_not_a_preference() -> None:
    cases = _cases()
    reference, _ = _run(ReferenceAgent(cases), cases)

    def scored(report: RunReport, value: float, name: str) -> RunReport:
        rows = tuple(row.model_copy(update={"score": row.score.model_copy(update={"score": value})})
                     if row.score is not None else row for row in report.results)
        return report.model_copy(update={"results": rows, "agent": name})

    band = default_margin()
    high, low = scored(reference, 0.9, "high"), scored(reference, round(0.9 - band, 4), "low")
    assert preference_pairs(high, low, cases) == [], "compare calls a lead of exactly the band stable"
    assert preference_pairs(high, low, cases, margin=band - 0.01)
    # Floating-point noise at the band is still inside it.
    assert preference_pairs(scored(reference, 0.7, "a"), scored(reference, 0.6, "b"), cases) == []


def test_a_question_and_a_refusal_at_one_span_index_keep_the_documented_tie_order() -> None:
    # The service records questions and refusals in two lists with no shared
    # sequence, so at one span index questions come first, then refusals,
    # each list in the order it was recorded.
    report, _ = _run(_asking_agent())
    amb = next(result for result in report.results if result.case_id == "amb")
    tied = amb.model_copy(update={"refusals": (
        {"tool": "servicenow.nope", "arguments": [], "error": "tool_not_allowed", "index": 1},
        {"tool": "servicenow.nope2", "arguments": [], "error": "tool_not_allowed", "index": 1})})
    _, order = continuation(tied)
    assert order == ["call:s1", "ask:q1", "refused:1", "refused:2", "call:s2", "call:s3", "answer"]
