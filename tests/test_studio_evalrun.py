"""Studio grades agents on the company's connector cases: per axis, durable, authenticated."""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.evalrun import read_run, summarize
from worldloom.evals.dataset import _files
from worldloom.providers import digest
from worldloom.studio import RunOptions, Studio, preset
from worldloom.studio.server import StudioServer
from worldloom.studio.worker import run_job


def _command(*parts: object) -> str:
    argv = [sys.executable, *(str(part) for part in parts)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(shlex.quote(part) for part in argv)


@pytest.fixture(scope="module")
def compiled(tmp_path_factory: pytest.TempPathFactory) -> tuple[Studio, dict]:
    studio = Studio(tmp_path_factory.mktemp("studio"))
    spec = preset()
    spec = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"count": 4}),)})
    project = studio.store.create(spec)
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="compile"))
    assert run_job(studio, job["id"])
    assert studio.store.job(job["id"])["status"] == "complete", studio.store.job(job["id"])
    return studio, project


def test_the_reference_run_grades_every_axis_and_seals_its_ledger(compiled: tuple[Studio, dict]) -> None:
    studio, p = compiled
    before = studio.workflow(p["id"])
    stage = next(s for s in before.stages if s.id == "evalrun")
    assert stage.status == "ready" and before.next_action is not None and before.next_action.operation == "evalrun"
    assert before.metrics["graded_connector_cases"] == 0

    job = studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="evalrun"))
    assert run_job(studio, job["id"])
    result = studio.store.job(job["id"])
    assert result["status"] == "complete", result
    outcome = result["result"]
    assert outcome["schema"] == "worldloom.studio-evalrun/v1" and outcome["agent"] == "run:reference"
    assert outcome["cases"] == 4 and outcome["dataset_complete"]
    summary = outcome["summary"]
    assert summary["pass_rate"] == 1.0 and summary["graded"] == 4 and summary["errors"] == 0
    assert summary["means"] == {"plan": 1.0, "trajectory": 1.0, "outcomes": 1.0, "overall": 1.0}
    # The run directory is the one the CLI reads, and its receipt covers every file.
    root = studio.path("evalruns", job["id"])
    assert {"run.json", "results.jsonl", "summary.json", "identity.json", "receipt.json", "result.json", "progress.json"} <= {p.name for p in root.iterdir()}
    assert summarize(read_run(root)).pass_rate == 1.0
    assert json.loads((root / "receipt.json").read_text(encoding="utf-8"))["files"] == _files(root)

    page = studio.agent_results(p["id"], job["id"], limit=2)
    assert page["total"] == 4 and page["unfiltered_total"] == 4 and page["next_offset"] == 2 and len(page["rows"]) == 2
    row = page["rows"][0]
    assert row["use_case"] == "operations-review" and row["split"] in {"train", "validation", "test"}
    assert row["passed"] is True and row["plan"]["score"] == 1.0 and row["observed"] == ["plan", "trajectory", "outcomes"]
    assert row["dataset_row"] and row["assertion_status"] in {"ok", "behavior"}
    assert studio.agent_results(p["id"], job["id"], verdict="failed")["total"] == 0
    assert studio.agent_results(p["id"], job["id"], shape=row["shape"])["total"] >= 1
    assert studio.agent_results(p["id"], job["id"], split="holdout")["total"] == 0
    assert page["summary"]["pass_rate"] == 1.0
    for invalid in ({"limit": 0}, {"offset": -1}, {"planet": "mars"}, {"shape": "x" * 201}):
        with pytest.raises(ValueError, match="invalid agent run"):
            studio.agent_results(p["id"], job["id"], **invalid)

    after = studio.workflow(p["id"], harness_configured=False)
    stage = next(s for s in after.stages if s.id == "evalrun")
    assert stage.status == "complete" and stage.action is not None and stage.action.kind == "navigate"
    assert after.metrics["graded_connector_cases"] == 4
    described = studio.describe(p["id"])
    graded = next(j for j in described["jobs"] if j["id"] == job["id"])
    assert graded["progress"]["status"] == "complete" and graded["progress"]["passed"] == 4
    # A connected harness makes the next step grading it on the same cases.
    with_harness = studio.workflow(p["id"], harness_configured=True)
    stage = next(s for s in with_harness.stages if s.id == "evalrun")
    assert stage.status == "ready" and stage.action is not None and stage.action.options == {"evalrun_agent": "harness"}

    # Repeating the job replays the sealed ledger; a changed ledger refuses.
    assert studio.execute(job["id"]) == outcome
    ledger = root / "results.jsonl"
    original = ledger.read_text(encoding="utf-8")
    ledger.write_text(original.replace('"passed": true', '"passed": false', 1), encoding="utf-8")
    try:
        with pytest.raises(ValueError, match="changed after"):
            studio.agent_results(p["id"], job["id"])
        with pytest.raises(ValueError, match="changed after"):
            studio.execute(job["id"])
    finally:
        ledger.write_text(original, encoding="utf-8")


def test_plan_mode_and_the_harness_agent_resume_without_asking_twice(compiled: tuple[Studio, dict], tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import worldloom.studio.evalrun as module

    studio, p = compiled
    planned = studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="evalrun", evalrun_mode="plan"))
    assert run_job(studio, planned["id"])
    outcome = studio.store.job(planned["id"])["result"]
    assert outcome["agent"] == "plan:reference" and outcome["summary"]["means"]["plan"] == 1.0
    assert outcome["summary"]["means"]["trajectory"] is None and outcome["summary"]["means"]["outcomes"] is None
    assert studio.agent_results(p["id"], planned["id"])["rows"][0]["observed"] == ["plan"]

    with pytest.raises(ValueError, match="needs a configured harness"):
        RunOptions(operation="evalrun", evalrun_agent="harness")

    counter = tmp_path / "turns.txt"
    child = tmp_path / "agent.py"
    child.write_text(
        "import json, sys\n"
        "doc = json.load(sys.stdin)\n"
        "assert doc['schema'] == 'worldloom.evalrun-turn/v2' and doc['tools'] and 'expected_dag' not in json.dumps(doc)\n"
        f"open({str(counter)!r}, 'a').write(doc['case_id'] + '\\n')\n"
        "print(json.dumps({'answer': 'Nothing to do.'}))\n",
        encoding="utf-8",
    )
    command = _command(child)
    options = RunOptions(operation="evalrun", evalrun_agent="harness", evalrun_limit=2, harness_identity=digest(command))
    job = studio.store.enqueue(p["id"], p["revision"], options)
    # The worker dies after the first graded case; the ledger keeps that case.
    real = module.run_cases

    def interrupted(service, cases, agent, **kwargs):
        hook = kwargs["on_result"]

        def once(result):
            hook(result)
            raise RuntimeError("worker lost")

        return real(service, cases, agent, **{**kwargs, "on_result": once})

    monkeypatch.setattr(module, "run_cases", interrupted)
    assert run_job(studio, job["id"], harness_command=command)
    failed = studio.store.job(job["id"])
    assert failed["status"] == "failed" and "worker lost" in (failed["error"] or "")
    assert studio.describe(p["id"])["jobs"][0]["progress"]["graded"] == 1
    assert counter.read_text(encoding="utf-8").count("\n") == 1
    monkeypatch.setattr(module, "run_cases", real)
    studio.store.retry(job["id"])
    assert run_job(studio, job["id"], harness_command=command)
    resumed = studio.store.job(job["id"])
    assert resumed["status"] == "complete", resumed
    assert counter.read_text(encoding="utf-8").count("\n") == 2, "the graded case was not asked again"
    summary = resumed["result"]["summary"]
    assert resumed["result"]["agent"] == "run:harness" and summary["graded"] == 2 and summary["pass_rate"] == 0.0
    rows = studio.agent_results(p["id"], job["id"], verdict="failed")["rows"]
    assert len(rows) == 2 and all(row["plan"]["missing_nodes"] for row in rows)
    # The same options under a different harness are a different job, and a
    # harness job run without its harness is a refusal, not a silent reference run.
    other = studio.store.enqueue(p["id"], p["revision"], options.model_copy(update={"harness_identity": digest("elsewhere")}))
    assert other["id"] != job["id"]
    with pytest.raises(ValueError, match="different harness"):
        studio.execute(other["id"], harness_command=command)
    assert run_job(studio, other["id"])
    assert "different harness" in (studio.store.job(other["id"])["error"] or "")
    unconfigured = studio.store.enqueue(p["id"], p["revision"], options.model_copy(update={"harness_identity": digest(None)}))
    assert run_job(studio, unconfigured["id"])
    assert "connect a coding harness" in (studio.store.job(unconfigured["id"])["error"] or "")


@pytest.fixture
def http_server(compiled: tuple[Studio, dict]):
    studio, _ = compiled
    server = StudioServer(studio.root, port=0, launch_workers=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def _http(server: StudioServer, path: str, body: dict | None = None):
    headers = {"Content-Type": "application/json", "X-Worldloom-Studio": "1"} if body is not None else {}
    request = Request(f"http://127.0.0.1:{server.server_port}" + path,
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
    return urlopen(request, timeout=10)


def test_the_console_routes_grade_and_page_results(http_server: StudioServer, compiled: tuple[Studio, dict]) -> None:
    studio, p = compiled
    with pytest.raises(HTTPError) as refused:
        _http(http_server, f"/api/projects/{p['id']}/run", {"revision": p["revision"], "options": {"operation": "evalrun", "evalrun_agent": "harness"}})
    assert refused.value.code == 422 and b"coding harness" in refused.value.read()
    with _http(http_server, f"/api/projects/{p['id']}/run", {"revision": p["revision"], "options": {"operation": "evalrun", "evalrun_split": "train"}}) as response:
        job = json.load(response)
    assert job["status"] == "queued" and job["options"]["evalrun_split"] == "train"
    assert run_job(studio, job["id"])
    with _http(http_server, f"/api/jobs/{job['id']}") as response:
        fetched = json.load(response)
    assert fetched["status"] == "complete" and fetched["progress"]["status"] == "complete"
    assert fetched["result"]["split"] == "train" and 1 <= fetched["result"]["cases"] <= 4
    with _http(http_server, f"/api/projects/{p['id']}/agent-results?job={job['id']}&limit=1&verdict=passed") as response:
        page = json.load(response)
    assert page["agent"] == "run:reference" and len(page["rows"]) == 1 and page["rows"][0]["split"] == "train"
    with pytest.raises(HTTPError) as unknown:
        _http(http_server, f"/api/projects/{p['id']}/agent-results?job=missing")
    assert unknown.value.code == 404
    with _http(http_server, f"/api/projects/{p['id']}/workflow") as response:
        workflow = json.load(response)
    assert any(stage["id"] == "evalrun" for stage in workflow["stages"])


def test_the_cli_grades_and_refuses_a_harness_without_a_command(compiled: tuple[Studio, dict]) -> None:
    studio, p = compiled
    runner = CliRunner()
    result = runner.invoke(app, ["studio", "evalrun", p["id"], "-w", str(studio.root), "--limit", "2", "--mode", "plan"])
    assert result.exit_code == 0, result.output
    job = json.loads(result.output)
    assert job["status"] == "complete" and job["result"]["cases"] == 2 and job["result"]["agent"] == "plan:reference"
    result = runner.invoke(app, ["studio", "evalrun", p["id"], "-w", str(studio.root), "--agent", "harness"])
    assert result.exit_code != 0 and "harness-command" in result.output
    result = runner.invoke(app, ["studio", "run", p["id"], "--operation", "evalrun", "-w", str(studio.root)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["result"]["summary"]["pass_rate"] == 1.0


def test_a_catalogue_project_compiles_its_own_evidence_and_grades_it(tmp_path_factory: pytest.TempPathFactory) -> None:
    """A telecom billing line, no engine of its own: the world's records and
    channel evidence come from the process company, construction accepts
    them, and the reference agent is graded on the cases they ground."""
    import json

    from worldloom import industry

    studio = Studio(tmp_path_factory.mktemp("catalogue"))
    spec = industry.project("telecom", "Ardent Telecom", lobs=("billing",))
    project = studio.store.create(spec)
    job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="compile", batch_limit=1))
    assert run_job(studio, job["id"])
    compiled = studio.store.job(job["id"])
    assert compiled["status"] == "complete", compiled
    report = compiled["result"]["report"]
    assert report["accepted"] > 0 and report["companies"] == 1, report
    dataset = studio.path("datasets", compiled["result"]["dataset"])
    batch = next(dataset.glob("batches/*/qualified/connector-data.json"))
    records = json.loads(batch.read_text(encoding="utf-8"))["records"]
    by_connector = {record["connector"] for record in records}
    assert {"sor", "email"} <= by_connector
    threads = [r for r in records if r["connector"] == "email" and r["entity"] == "thread"]
    assert threads and any(r["fields"]["lob"] == "billing" for r in threads)
    assert all(r["fields"]["stream"] and r["fields"]["business_unit"] for r in threads)
    assert all(r["fields"]["stream"] for r in records if r["connector"] == "sor")
    run = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="evalrun", evalrun_limit=4))
    assert run_job(studio, run["id"])
    graded = studio.store.job(run["id"])
    assert graded["status"] == "complete", graded
    assert graded["result"]["cases"] == 4
    page = studio.agent_results(project["id"], run["id"], limit=4)
    assert page["total"] == 4 and all(row["use_case"].startswith("billing-") for row in page["rows"])
    # The programme's record requests run in the same job beside the dataset's
    # cases, over the company's own records, grouped under the line's use case.
    programme = studio.store.enqueue(project["id"], project["revision"],
                                     RunOptions(operation="evalrun", evalrun_source="programme", evalrun_limit=3))
    assert run_job(studio, programme["id"])
    graded_programme = studio.store.job(programme["id"])
    assert graded_programme["status"] == "complete", graded_programme
    assert graded_programme["result"]["source"] == "programme" and graded_programme["result"]["programme_cases"] == 3
    assert graded_programme["result"]["dataset"] is None and graded_programme["result"]["cases"] == 3
    rows = studio.agent_results(project["id"], programme["id"], limit=3)["rows"]
    use_case_ids = {case.id for case in spec.use_cases}
    assert all(row["source"] == "programme" and row["use_case"] in use_case_ids for row in rows)
    assert all(row["shape"] == "record_lookup" and row["plan"]["score"] == 1.0 for row in rows)
    with pytest.raises(ValueError, match="widen the selection"):
        from worldloom.studio.evalrun import execute

        blocked = studio.store.enqueue(project["id"], project["revision"],
                                       RunOptions(operation="evalrun", evalrun_source="programme", evalrun_split="test"))
        execute(studio, studio.store.job(blocked["id"]), harness_command=None, timeout=60.0)
