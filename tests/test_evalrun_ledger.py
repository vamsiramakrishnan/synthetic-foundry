"""The run ledger under an adversary: other harnesses, unfinished runs, kills mid-write.

Each test here reproduces a way a ledger could report something it is not:
a resume or merge that joins two agents because they share a name, a
reader that takes a run's first cases for the whole run, a rewrite that a
kill leaves half-done, and a worker's failure dressed as a concurrency
refusal.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import packkit
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.connectors.serving import ServingError
from worldloom.evalrun import (
    ReferenceAgent,
    case_from_row,
    run_cases,
    service_for,
    write_run,
)
from worldloom.evalrun.harness import ExecAgent
from worldloom.evalrun.results import (
    PartialRun,
    begin_ledger,
    merge_shards,
    read_run,
    resume_ledger,
    shard_document,
    shard_of,
    write_shard,
)
from worldloom.evalrun.runner import ConcurrencyRefused
from worldloom.studio.harness import adapter_command

runner = CliRunner()
LEDGER = ("run.json", "results.jsonl", "summary.json")


@pytest.fixture(autouse=True)
def _isolated_packs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


def _records() -> list[dict[str, Any]]:
    return [{"fid": f"f{n}", "server": "servicenow", "entity": "incident", "ident": f"INC000000{n}", "state": "new",
             "short_description": f"Case {n}"} for n in range(1, 7)]


def _cases(count: int = 6) -> tuple[Any, ...]:
    return tuple(case_from_row({
        "id": f"read-{n}", "query": f"Read INC000000{n}.",
        "expected_dag": {"nodes": [{"id": "read", "server": "servicenow", "tool": "get_record", "fixture": f"f{n}",
                                    "entity": "incident", "op": "read"}], "edges": []},
        "assertions": [{"type": "tool_called", "node": "read"}]}) for n in range(1, count + 1))


def _service(cases: Any) -> Any:
    return service_for(cases, _records(), definitions={"servicenow": load_connector_definition("servicenow")})


def _harness(name: str) -> ExecAgent:
    # What `evalrun run --harness <name>` builds with its default --timeout.
    return ExecAgent(adapter_command(name, timeout=595.0), timeout=600.0)


def _identity(agent: Any, cases: Any) -> Any:
    return run_cases(_service(cases), (), agent).model_copy(update={"case_set": "digest-of-the-set"})


def _finished(tmp_path: Path, name: str = "run", count: int = 3) -> Path:
    cases = _cases(count)
    write_run(tmp_path / name, run_cases(_service(cases), cases, ReferenceAgent(cases)))
    return tmp_path / name


def _bytes(directory: Path) -> dict[str, bytes]:
    return {name: (directory / name).read_bytes() for name in LEDGER}


# -- agent identity -------------------------------------------------------------


def test_resume_refuses_a_ledger_another_harness_wrote(tmp_path: Path) -> None:
    cases = _cases(3)
    codex, claude = _harness("codex"), _harness("claude")
    # The trap: one name for both, so only the fingerprint tells them apart.
    assert codex.name == claude.name
    begin_ledger(tmp_path / "run", _identity(codex, cases), 3)
    with pytest.raises(ValueError, match=r"cannot resume a different run: agent_identity \(ledger .*codex"):
        resume_ledger(tmp_path / "run", _identity(claude, cases))
    # The same harness resumes.
    assert resume_ledger(tmp_path / "run", _identity(_harness("codex"), cases)) == ([], None)


def test_merge_refuses_shards_from_different_agent_identities(tmp_path: Path) -> None:
    cases = _cases(6)
    whole = run_cases(_service(cases), cases, ReferenceAgent(cases))
    codex, claude = _harness("codex"), _harness("claude")

    def shard(index: int, agent: Any, harness: str) -> Path:
        directory = tmp_path / f"{harness}-{index}"
        owned = tuple(result for result in whole.results if shard_of(result.case_id, 2) == index - 1)
        report = whole.model_copy(update={"agent": agent.name, "agent_identity": agent.fingerprint(),
                                          "results": owned})
        write_run(directory, report)
        write_shard(directory, shard_document(index, 2, cases))
        return directory

    assert merge_shards([shard(1, codex, "codex"), shard(2, codex, "codex")]).agent_identity == codex.fingerprint()
    with pytest.raises(ValueError, match="differs in agent_identity"):
        merge_shards([shard(1, codex, "codex"), shard(2, claude, "claude")])


# -- R2: an unfinished run is not a finished one ----------------------------------


def _killed(tmp_path: Path) -> Path:
    """A run of five planned cases, killed after two."""
    run = _finished(tmp_path, "killed", 2)
    begin_ledger(run, read_run(run).model_copy(update={"results": ()}), 5)
    (run / "summary.json").unlink()
    return run


def test_read_run_refuses_an_unfinished_run_naming_its_counts(tmp_path: Path) -> None:
    run = _killed(tmp_path)
    with pytest.raises(PartialRun, match=r"unfinished: 2 of 5 planned case\(s\) finished.*--resume"):
        read_run(run)
    assert isinstance(PartialRun("x"), ValueError)
    # Asked for, the finished cases are there.
    assert [result.case_id for result in read_run(run, allow_partial=True).results] == ["read-1", "read-2"]


@pytest.mark.parametrize("command", ["summarize", "compare", "autopsy"])
def test_the_cli_refuses_an_unfinished_run_with_run_partial(tmp_path: Path, command: str,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    run = _killed(tmp_path)
    args = {"summarize": [str(run)], "compare": [str(_finished(tmp_path)), str(run)], "autopsy": [str(run)]}[command]
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["evalrun", command, *args])
    assert result.exit_code == 2, result.output
    envelope = json.loads(result.output.strip().splitlines()[-1])
    assert envelope["refusal"] == "run_partial"
    assert "2 of 5" in envelope["message"] and "--resume" in envelope["fix"]


def test_the_library_readers_refuse_an_unfinished_run(tmp_path: Path) -> None:
    from worldloom.evalrun.session import EvalSession
    from worldloom.mcp import evalrun_compare, evalrun_summarize

    run = _killed(tmp_path)
    with pytest.raises(PartialRun):
        evalrun_summarize(str(run))
    with pytest.raises(PartialRun):
        evalrun_compare(str(_finished(tmp_path)), str(run))
    with pytest.raises(PartialRun):
        EvalSession(_cases(1), _records()).report(str(run))


# -- R3: a kill mid-write leaves the last good ledger ------------------------------


def test_write_run_killed_mid_ledger_keeps_the_previous_ledger(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.evalrun.results as module

    run = _finished(tmp_path, count=3)
    before = _bytes(run)
    report = read_run(run)
    real = module._result_line
    written: list[int] = []

    def dying(result: Any) -> str:
        written.append(1)
        if len(written) == 2:
            raise KeyboardInterrupt  # killed with one line of the rewrite out
        return real(result)

    monkeypatch.setattr(module, "_result_line", dying)
    with pytest.raises(KeyboardInterrupt):
        write_run(run, report)
    assert _bytes(run) == before
    assert sorted(path.name for path in run.iterdir()) == sorted(LEDGER)


def test_write_run_syncs_and_replaces_each_file_with_run_json_last(tmp_path: Path,
                                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.evalrun.results as module

    run = _finished(tmp_path, count=3)
    before = _bytes(run)
    synced: list[int] = []
    replaced: list[str] = []
    real_fsync, real_replace = module.os.fsync, module.os.replace
    monkeypatch.setattr(module.os, "fsync", lambda fd: (synced.append(fd), real_fsync(fd))[1])
    monkeypatch.setattr(module.os, "replace",
                        lambda source, target: (replaced.append(Path(target).name), real_replace(source, target))[1])
    write_run(run, read_run(run))
    assert replaced == ["results.jsonl", "summary.json", "run.json"]
    assert len(synced) >= 3
    assert _bytes(run) == before
    replaced.clear()
    begin_ledger(tmp_path / "begun", read_run(run).model_copy(update={"results": ()}), 3)
    assert replaced == ["run.json"]


def test_resume_refuses_a_torn_run_json_precisely(tmp_path: Path) -> None:
    run = _killed(tmp_path)
    header = (run / "run.json").read_bytes()
    (run / "run.json").write_bytes(header[: len(header) // 2])
    identity = read_run(_finished(tmp_path)).model_copy(update={"results": ()})
    with pytest.raises(ValueError, match=r"run.json is torn") as caught:
        resume_ledger(run, identity)
    assert "different run" not in str(caught.value)
    with pytest.raises(ValueError, match=r"run.json is torn"):
        read_run(run)


# -- the concurrency refusal is only the up-front one --------------------------------


def test_only_the_up_front_concurrency_refusal_is_refused_as_such(tmp_path: Path,
                                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.evalrun.runner as module

    cases = _cases(6)
    service = service_for(cases, _records(), definitions={"servicenow": load_connector_definition("servicenow")})
    with pytest.raises(ConcurrencyRefused, match="concurrency_limit"):
        run_cases(service, cases, ReferenceAgent(cases), concurrency=64)

    # A worker's own ServingError is not a concurrency refusal.
    def failing(*args: Any, **kwargs: Any) -> Any:
        raise ServingError("unknown_run: the service lost this run")

    monkeypatch.setattr(module, "run_case", failing)
    with pytest.raises(ServingError) as caught:
        run_cases(service, cases, ReferenceAgent(cases), concurrency=2)
    assert not isinstance(caught.value, ConcurrencyRefused)
