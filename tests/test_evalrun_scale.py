"""Evalrun at scale: concurrent cases, per-run locks, durable ledgers, resume, shards and merge.

Every claim here is about sameness. A run with eight cases in flight writes
the bytes a sequential run writes; a resumed run writes the bytes an
uninterrupted one would; three shards merged write the bytes one process
would. Speed is measured only where it is the point (two runs overlapping in
the service), and then as overlap, never as a threshold on a fast machine.
"""

from __future__ import annotations

import json
import shutil
import threading
import time
import warnings
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.connectors.serving import ConnectorEvaluationService, ServingError
from worldloom.enterprise_io import export_corpus
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    AgentResponse,
    CallableAgent,
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    cases_from_corpus,
    run_cases,
    service_for,
    write_run,
)
from worldloom.evalrun.results import (
    LedgerWarning,
    append_result,
    begin_ledger,
    read_results,
    read_run,
    shard_of,
)
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()
LEDGER = ("run.json", "results.jsonl", "summary.json")


# -- fixtures ------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    built, _ = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(6)
        .with_dag_grammar("map_read", "conditional")
        .build()
    )
    return built


@pytest.fixture(scope="module")
def exported(corpus: Any, tmp_path_factory: pytest.TempPathFactory) -> Path:
    root = tmp_path_factory.mktemp("scale") / "corpus"
    export_corpus(corpus, root)
    return root


@pytest.fixture(autouse=True)
def _isolated_packs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


def _policy_pack(root: Path, values: dict[str, Any]) -> None:
    path = root / "industry" / "scaleco.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "industry", "name": "scaleco",
                                "body": {"policy": values}}), encoding="utf-8")


def _records() -> list[dict[str, Any]]:
    return [{"fid": f"f{n}", "server": "servicenow", "entity": "incident", "ident": f"INC000000{n}", "state": "new",
             "short_description": f"Case {n}"} for n in range(1, 7)]


def _read_row(n: int) -> dict[str, Any]:
    return {"id": f"read-{n}", "query": f"Read INC000000{n}.",
            "expected_dag": {"nodes": [{"id": "read", "server": "servicenow", "tool": "get_record", "fixture": f"f{n}",
                                        "entity": "incident", "op": "read"}], "edges": []},
            "assertions": [{"type": "tool_called", "node": "read"}]}


def _hand_cases(count: int = 6) -> tuple[Any, ...]:
    return tuple(case_from_row(_read_row(n)) for n in range(1, count + 1))


def _definitions() -> dict[str, Any]:
    return {"servicenow": load_connector_definition("servicenow")}


def _bytes(directory: Path) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in LEDGER}


# -- concurrency ---------------------------------------------------------------


@pytest.mark.parametrize("agent_kind", ["reference", "scripted"])
def test_a_concurrent_run_writes_the_bytes_a_sequential_run_writes(corpus: Any, agent_kind: str, tmp_path: Path) -> None:
    cases = cases_from_corpus(corpus)
    assert len(cases) >= 4

    def agent() -> Any:
        if agent_kind == "reference":
            return ReferenceAgent(cases)
        # A scripted agent that does something on every case: reads the
        # first record of whatever it may search, and answers.
        return ScriptedAgent([("servicenow.search_records", {"entity": "incident", "max_results": 1})],
                             answer="Looked.", name="looker")

    sequential = run_cases(service_for(cases, corpus.connector_data.records), cases, agent())
    active = 0
    most = 0
    seen: list[str] = []
    guard = threading.Lock()

    def landed(result: Any) -> None:
        nonlocal active, most
        with guard:
            active += 1
            most = max(most, active)
        time.sleep(0.01)
        seen.append(result.case_id)
        with guard:
            active -= 1

    concurrent = run_cases(service_for(cases, corpus.connector_data.records, concurrency=4), cases, agent(),
                           on_result=landed, concurrency=4)
    assert most == 1, "on_result ran for two results at once"
    assert sorted(seen) == sorted(case.id for case in cases)
    assert [result.case_id for result in concurrent.results] == [case.id for case in cases]
    write_run(tmp_path / "seq", sequential)
    write_run(tmp_path / "par", concurrent)
    assert _bytes(tmp_path / "seq") == _bytes(tmp_path / "par")
    if agent_kind == "reference":
        assert all(result.graded and result.score is not None and result.score.passed for result in concurrent.results)


def test_a_passed_service_keeps_its_limits_and_refuses_more_concurrency_than_they_admit() -> None:
    cases = _hand_cases()
    service = service_for(cases, _records(), definitions=_definitions())
    assert service.limits.max_runs_per_principal == 4
    with pytest.raises(ServingError, match=r"concurrency_limit: concurrency 8 .*max_runs_per_principal=4.*concurrency=8"):
        run_cases(service, cases, ScriptedAgent([], name="idle"), concurrency=8)
    sized = service_for(cases, _records(), definitions=_definitions(), concurrency=8)
    assert sized.limits.max_runs == 32 and sized.limits.max_runs_per_principal == 8
    report = run_cases(sized, cases, ScriptedAgent([], name="idle"), concurrency=8)
    assert [result.status for result in report.results] == ["graded"] * len(cases)
    with pytest.raises(ValueError, match="at least 1"):
        run_cases(sized, cases, ScriptedAgent([], name="idle"), concurrency=0)


def test_worker_threads_see_the_callers_packs(tmp_path: Path) -> None:
    _policy_pack(tmp_path, {"evalrun.concurrency": 3})
    cases = _hand_cases()
    seen: list[int] = []

    def reads_policy(task: Any, tools: Any) -> AgentResponse:
        seen.append(int(packkit.policy("evalrun.concurrency")))
        return AgentResponse(answer="ok")

    with packkit.use("industry:scaleco", roots=[tmp_path]):
        from worldloom.evalrun.runner import default_concurrency

        assert default_concurrency() == 3
        run_cases(service_for(cases, _records(), definitions=_definitions(), concurrency=3), cases,
                  CallableAgent(reads_policy, name="policy-reader"), concurrency=3)
    assert seen == [3] * len(cases)
    from worldloom.evalrun.runner import default_concurrency

    assert default_concurrency() == 1


# -- the service's locks --------------------------------------------------------


class _SlowService(ConnectorEvaluationService):
    """Every call spends `delay` seconds inside the service, under whatever lock `call` holds."""

    delay = 0.3

    def _consumed(self, run: Any, arguments: Any) -> tuple[str, ...]:
        time.sleep(self.delay)
        return super()._consumed(run, arguments)


def _timed_calls(service: ConnectorEvaluationService, targets: list[tuple[str, str]]) -> float:
    errors: list[BaseException] = []

    def call(principal: str, run_id: str) -> None:
        try:
            service.call(principal, run_id, "servicenow.get_record", {"id": "INC0000001"})
        except BaseException as error:  # surfaced below
            errors.append(error)

    threads = [threading.Thread(target=call, args=target) for target in targets]
    started = time.perf_counter()
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert not errors, errors
    return time.perf_counter() - started


def test_calls_on_different_runs_overlap_and_calls_on_one_run_do_not() -> None:
    rows = [{**case.row, "query": case.query} for case in _hand_cases(2)]
    service = _SlowService(rows, _records(), definitions=_definitions())
    one = service.begin("alice", "read-1")["run_id"]
    two = service.begin("bob", "read-2")["run_id"]
    # Two runs: both calls are inside the service at once, so the pair takes
    # about one delay. Under the old service-wide lock it took two.
    parallel = _timed_calls(service, [("alice", one), ("bob", two)])
    assert parallel < 1.6 * service.delay, parallel
    # One run: its calls are strictly ordered, so the pair takes two delays.
    serial = _timed_calls(service, [("alice", one), ("alice", one)])
    assert serial >= 1.9 * service.delay, serial
    assert [span.ordinal for span in service.spans("alice", one)] == [1, 2, 3]
    service.end("alice", one)
    with pytest.raises(ServingError, match="unknown_run"):
        service.call("alice", one, "servicenow.get_record", {"id": "INC0000001"})
    with pytest.raises(ServingError, match="unknown_run"):
        service.spans("bob", one)


def test_a_slow_agent_runs_cases_in_parallel_under_concurrency() -> None:
    cases = _hand_cases()

    def slow(task: Any, tools: Any) -> AgentResponse:
        time.sleep(0.2)
        tools.call("servicenow.get_record", id=task.query.split()[1].rstrip("."))
        return AgentResponse(answer="Read it.")

    agent = CallableAgent(slow, name="slow")
    started = time.perf_counter()
    sequential = run_cases(service_for(cases, _records(), definitions=_definitions()), cases, agent)
    sequential_seconds = time.perf_counter() - started
    started = time.perf_counter()
    concurrent = run_cases(service_for(cases, _records(), definitions=_definitions(), concurrency=6), cases, agent,
                           concurrency=6)
    concurrent_seconds = time.perf_counter() - started
    assert sequential.model_dump(mode="json") == concurrent.model_dump(mode="json")
    assert all(result.graded and result.score is not None and result.score.passed for result in concurrent.results)
    # Six 0.2 s cases: at least 1.2 s in a row, and well under that at once.
    assert sequential_seconds >= 1.2 and concurrent_seconds < sequential_seconds / 2, (sequential_seconds, concurrent_seconds)


def test_run_ids_carry_a_worker_prefix_when_asked() -> None:
    rows = [{**case.row, "query": case.query} for case in _hand_cases(2)]
    plain = ConnectorEvaluationService(rows, _records(), definitions=_definitions())
    assert plain.begin("alice", "read-1")["run_id"] == "run-1"
    prefixed = ConnectorEvaluationService(rows, _records(), definitions=_definitions(), run_prefix="w3-")
    begun = prefixed.begin("alice", "read-1")["run_id"]
    assert begun == "w3-run-1"
    assert prefixed.spans("alice", begun) == ()
    with pytest.raises(ServingError, match="unknown_run"):
        prefixed.spans("alice", "run-1")
    with pytest.raises(ServingError, match="run_prefix"):
        ConnectorEvaluationService(rows, _records(), definitions=_definitions(), run_prefix="w 3/")


# -- a durable ledger ----------------------------------------------------------


def _small_run(tmp_path: Path) -> Path:
    cases = _hand_cases(3)
    report = run_cases(service_for(cases, _records(), definitions=_definitions()), cases, ReferenceAgent(cases))
    write_run(tmp_path / "run", report)
    return tmp_path / "run"


def test_a_torn_final_line_is_dropped_with_a_note_and_nothing_else_is(tmp_path: Path) -> None:
    run = _small_run(tmp_path)
    ledger = run / "results.jsonl"
    whole = ledger.read_bytes()
    lines = whole.splitlines(keepends=True)
    # Killed mid-append: the last line has part of its JSON and no newline.
    ledger.write_bytes(b"".join(lines[:2]) + lines[2][: len(lines[2]) // 2])
    with pytest.warns(LedgerWarning, match=r"results.jsonl:3: dropped a torn final line"):
        report = read_run(run)
    assert [result.case_id for result in report.results] == ["read-1", "read-2"]
    # A complete last line without its newline is kept, silently.
    ledger.write_bytes(whole.rstrip(b"\n"))
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        assert len(read_run(run).results) == 3
    # A bad line in the middle is corruption, not a crash, and refuses.
    ledger.write_bytes(lines[0] + b'{"case_id": "torn\n' + lines[2])
    with pytest.raises(ValueError, match=r"results.jsonl:2: invalid result"):
        read_run(run)
    # So is a bad last line that was terminated: a torn write has no newline.
    ledger.write_bytes(b"".join(lines[:2]) + b'{"case_id": \n')
    with pytest.raises(ValueError, match=r"results.jsonl:3: invalid result"):
        read_results(ledger)


def test_append_result_syncs_each_line(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.evalrun.results as module

    synced: list[int] = []
    real = module.os.fsync
    monkeypatch.setattr(module.os, "fsync", lambda fd: (synced.append(fd), real(fd))[1])
    report = read_run(_small_run(tmp_path))
    for result in report.results:
        append_result(tmp_path / "appended", result)
    assert len(synced) == 3
    assert (tmp_path / "appended" / "results.jsonl").read_bytes() == (tmp_path / "run" / "results.jsonl").read_bytes()


# -- the CLI: resume, shards, merge ---------------------------------------------


def _run(*args: str) -> Any:
    return runner.invoke(app, ["evalrun", "run", *args])


def _said(result: Any) -> str:
    """The output with the terminal's wrapping undone."""
    return " ".join(result.output.split())


def test_resume_finishes_a_killed_run_byte_identically(exported: Path, tmp_path: Path) -> None:
    whole = tmp_path / "whole"
    result = _run(str(exported), "-o", str(whole), "--limit", "5")
    assert result.exit_code == 0, result.output
    # Kill it after two cases, mid-way through writing the third.
    killed = tmp_path / "killed"
    shutil.copytree(whole, killed)
    header = read_run(whole)
    begin_ledger(killed, header.model_copy(update={"results": ()}), 5)
    assert json.loads((killed / "run.json").read_text(encoding="utf-8"))["partial"] is True
    lines = (whole / "results.jsonl").read_bytes().splitlines(keepends=True)
    (killed / "results.jsonl").write_bytes(b"".join(lines[:2]) + lines[2][:40])
    (killed / "summary.json").unlink()
    result = _run(str(exported), "-o", str(killed), "--limit", "5", "--resume", "--progress", "--concurrency", "2")
    assert result.exit_code == 0, result.output
    assert "dropped a torn final line" in _said(result)
    # Three cases graded here (the torn one again), counted after the two kept.
    assert "[3/5]" in result.output and "[5/5]" in result.output and "[1/5]" not in result.output
    assert _bytes(killed) == _bytes(whole)
    # Resuming a finished run grades nothing and changes nothing.
    result = _run(str(exported), "-o", str(killed), "--limit", "5", "--resume", "--progress")
    assert result.exit_code == 0, result.output
    assert "[" not in result.output.split("\n")[0] and _bytes(killed) == _bytes(whole)


def test_resume_refuses_a_ledger_for_a_different_run(exported: Path, tmp_path: Path) -> None:
    out = tmp_path / "run"
    assert _run(str(exported), "-o", str(out), "--limit", "3").exit_code == 0
    result = _run(str(exported), "-o", str(out), "--limit", "3", "--agent", "lazy", "--resume")
    assert result.exit_code != 0 and "cannot resume a different run" in _said(result) and "agent (ledger 'reference'" in _said(result)
    result = _run(str(exported), "-o", str(out), "--limit", "4", "--resume")
    assert result.exit_code != 0 and "case_set" in _said(result)
    result = _run(str(exported), "-o", str(out), "--limit", "3", "--principal", "someone", "--resume")
    assert result.exit_code != 0 and "principal" in _said(result)
    result = _run(str(exported), "-o", str(out), "--limit", "3", "--shard", "1/2", "--resume")
    assert result.exit_code != 0 and "shard (ledger unsharded" in _said(result)
    # A ledger with no run.json to prove it against is refused too.
    orphan = tmp_path / "orphan"
    orphan.mkdir()
    shutil.copy(out / "results.jsonl", orphan / "results.jsonl")
    result = _run(str(exported), "-o", str(orphan), "--limit", "3", "--resume")
    assert result.exit_code != 0 and "no run.json" in _said(result)
    # Without --resume the directory is simply run again, as before.
    result = _run(str(exported), "-o", str(out), "--limit", "3", "--agent", "lazy")
    assert result.exit_code == 0, result.output
    assert read_run(out).agent == "lazy"


def test_shards_merge_into_the_bytes_of_one_process(exported: Path, corpus: Any, tmp_path: Path) -> None:
    whole = tmp_path / "whole"
    assert _run(str(exported), "-o", str(whole)).exit_code == 0
    cases = cases_from_corpus(corpus)
    shards = [tmp_path / f"shard-{index}" for index in (1, 2, 3)]
    for index, directory in enumerate(shards, start=1):
        result = _run(str(exported), "-o", str(directory), "--shard", f"{index}/3", "--concurrency", "2")
        assert result.exit_code == 0, result.output
        owned = [case.id for case in cases if shard_of(case.id, 3) == index - 1]
        assert [result.case_id for result in read_run(directory).results] == owned
        assert json.loads((directory / "shard.json").read_text(encoding="utf-8"))["order"] == [case.id for case in cases]
    # The partition is by id: the shards cover the set exactly once.
    assert sum(len(read_run(directory).results) for directory in shards) == len(cases)
    merged = tmp_path / "merged"
    result = runner.invoke(app, ["evalrun", "merge", str(merged), *map(str, reversed(shards))])
    assert result.exit_code == 0, result.output
    assert _bytes(merged) == _bytes(whole)

    def refused(*directories: Path) -> str:
        outcome = runner.invoke(app, ["evalrun", "merge", str(tmp_path / "nope"), *map(str, directories)])
        assert outcome.exit_code != 0, outcome.output
        return _said(outcome)

    assert "missing shard(s) 3/3" in refused(shards[0], shards[1])
    assert "given twice" in refused(shards[0], shards[0], shards[1], shards[2])
    assert "no shard.json" in refused(whole)
    # A shard graded by another agent is not a shard of this run.
    lazy = tmp_path / "lazy-2"
    assert _run(str(exported), "-o", str(lazy), "--shard", "2/3", "--agent", "lazy").exit_code == 0
    assert "differs in agent" in refused(shards[0], lazy, shards[2])
    # Nor is one cut from a different set, or into a different count.
    other = tmp_path / "other-2"
    assert _run(str(exported), "-o", str(other), "--shard", "2/3", "--limit", "4").exit_code == 0
    assert "case_set" in refused(shards[0], other, shards[2])
    # Two shards that grade the same case overlap.
    overlap = tmp_path / "overlap"
    shutil.copytree(shards[0], overlap)
    document = json.loads((overlap / "shard.json").read_text(encoding="utf-8"))
    (overlap / "shard.json").write_text(json.dumps({**document, "index": 2}), encoding="utf-8")
    if read_run(overlap).results:
        assert "graded in two shards" in refused(shards[0], overlap, shards[2])
    # An unfinished shard is refused until it is resumed.
    unfinished = tmp_path / "unfinished"
    shutil.copytree(shards[2], unfinished)
    begin_ledger(unfinished, read_run(shards[2]).model_copy(update={"results": ()}), 1)
    assert "did not finish" in refused(shards[0], shards[1], unfinished)
    # An unsharded run into an old shard directory is no longer a shard.
    reused = tmp_path / "reused"
    shutil.copytree(shards[0], reused)
    assert _run(str(exported), "-o", str(reused), "--limit", "2").exit_code == 0
    assert not (reused / "shard.json").exists() and "no shard.json" in refused(reused)


def test_a_malformed_shard_is_refused(exported: Path, tmp_path: Path) -> None:
    for bad in ("0/3", "4/3", "x", "1/0", "2"):
        result = _run(str(exported), "-o", str(tmp_path / "bad"), "--shard", bad)
        assert result.exit_code != 0 and "give i/n" in _said(result), (bad, result.output)


def test_the_policy_sets_the_cli_concurrency(exported: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.evalrun.runner as module

    used: list[int] = []
    real = module.run_cases

    def spy(*args: Any, **kwargs: Any) -> Any:
        used.append(int(kwargs.get("concurrency", 1)))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "run_cases", spy)
    assert _run(str(exported), "-o", str(tmp_path / "a"), "--limit", "2").exit_code == 0
    assert _run(str(exported), "-o", str(tmp_path / "b"), "--limit", "2", "--concurrency", "3").exit_code == 0
    # The empty identity run, then the real one, per invocation.
    assert used == [1, 1, 1, 3]


# -- Studio ---------------------------------------------------------------------


def test_studio_runs_cases_concurrently_under_policy_and_resumes_a_torn_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.studio.evalrun as module
    from worldloom.studio import RunOptions, Studio, preset
    from worldloom.studio.worker import run_job

    studio = Studio(tmp_path / "studio")
    spec = preset()
    spec = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"count": 4}),)})
    project = studio.store.create(spec)
    compiled = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="compile"))
    assert run_job(studio, compiled["id"])
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="evalrun"))
    assert run_job(studio, job["id"])
    assert studio.store.job(job["id"])["status"] == "complete"
    root = studio.path("evalruns", job["id"])
    sequential = _bytes(root)

    used: list[int] = []
    real = module.run_cases

    def spy(*args: Any, **kwargs: Any) -> Any:
        used.append(int(kwargs.get("concurrency", 1)))
        return real(*args, **kwargs)

    monkeypatch.setattr(module, "run_cases", spy)
    _policy_pack(tmp_path / "packs", {"evalrun.concurrency": 3})
    shutil.rmtree(root)
    with packkit.use("industry:scaleco", roots=[tmp_path / "packs"]):
        studio.execute(job["id"])
    assert used == [3]
    assert _bytes(root) == sequential
    # Killed mid-append: one whole case and a torn one. The retry keeps the
    # first, grades the rest, and seals the same ledger.
    lines = sequential["results.jsonl"].splitlines(keepends=True)
    for name in ("receipt.json", "result.json", "run.json", "summary.json"):
        (root / name).unlink()
    (root / "results.jsonl").write_bytes(lines[0] + lines[1][:30])
    used.clear()
    with packkit.use("industry:scaleco", roots=[tmp_path / "packs"]):
        studio.execute(job["id"])
    assert used == [3]
    assert _bytes(root) == sequential
