from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from threading import Thread
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.evals.dataset import _files
from worldloom.studio import (
    InterviewReply,
    ProjectSpec,
    RunOptions,
    Studio,
    StudioConflict,
    preset,
)
from worldloom.studio.harness import command_for, invoke
from worldloom.studio.server import StudioServer
from worldloom.studio.worker import recover, run_job, writer_lock


@pytest.fixture
def project(tmp_path):
    studio = Studio(tmp_path)
    company = studio.store.create(preset())
    return studio, company


def test_revision_cas_and_eval_changes_reuse_world(project):
    studio, p = project
    spec = ProjectSpec.model_validate(p["spec"])
    world, root = studio.snapshot(spec)
    data = _files(root)
    changed = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"count": 36}),)})
    revised = studio.store.revise(p["id"], p["revision"], changed, reason="Increase coverage")
    assert revised["ordinal"] == 2
    assert studio.store.get(p["id"], p["revision"])["spec"] == p["spec"]
    again, reused = studio.snapshot(changed)
    assert reused == root and again.company == world.company and _files(root) == data
    with pytest.raises(StudioConflict):
        studio.store.revise(p["id"], p["revision"], changed, reason="Stale change")


def test_extend_timeline_after_restart_preserves_company_and_old_records(project):
    studio, p = project
    spec = ProjectSpec.model_validate(p["spec"]).model_copy(update={"episodes": ("2026-03",)})
    before, location = studio.snapshot(spec)
    files = _files(location)
    restarted = Studio(studio.root)
    after, _ = restarted.snapshot(spec.model_copy(update={"episodes": ("2026-03", "2026-04")}))
    assert before.company == after.company
    assert tuple(before.people) == tuple(after.people)
    assert {f.id for f in before.facts} <= {f.id for f in after.facts}
    assert len(after.facts) > len(before.facts)
    assert _files(location) == files


def test_authored_divisions_change_generated_structure_not_only_metadata(project):
    from worldloom.packs import PackUnit

    studio, p = project
    original = ProjectSpec.model_validate(p["spec"])
    base, base_path = studio.snapshot(original)
    amended = original.model_copy(update={"divisions": (
        PackUnit(key="stores", name="Stores", kind="supermarkets", share=0.75),
        PackUnit(key="online", name="Online", kind="online", share=0.25),
    )})
    world, location = studio.snapshot(ProjectSpec.model_validate(amended.model_dump(mode="json")))
    assert location != base_path
    assert len(base.business_units) != len(world.business_units)
    assert [unit.name for unit in world.business_units] == ["Stores", "Online"]
    world.validate().raise_if_failed()


def test_accepted_narration_can_be_selected_and_replayed_without_calls(project, monkeypatch):
    from worldloom.execseam import LoopResult
    from worldloom.narrative.providers import DeterministicProvider

    studio, p = project
    spec = ProjectSpec.model_validate(p["spec"]).model_copy(update={"episodes": ("2026-03",)})
    p = studio.store.revise(p["id"], p["revision"], spec, reason="Generate document evidence")
    calls = []
    def narrate(world, command, **kwargs):
        calls.append(command)
        return LoopResult(rounds=(), world=world.narrate(DeterministicProvider()), outstanding={})
    monkeypatch.setattr("worldloom.execseam.narrate_loop", narrate)
    job = studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="narrate"))
    run_job(studio, job["id"], harness_command="scripted-author")
    assert studio.store.job(job["id"])["status"] == "complete", studio.store.job(job["id"])
    studio.execute(job["id"], harness_command="scripted-author")
    assert len(calls) == 1
    chosen = spec.model_copy(update={"narration_job": job["id"]})
    current = studio.store.revise(p["id"], p["revision"], chosen, reason="Use accepted authored evidence")
    sources = studio.native_sources(p["id"], current["revision"], limit=1)
    assert sources["status"] == "accepted" and sources["total"] > 1
    assert len(sources["sources"]) == 1 and sources["next_offset"] == 1
    assert sources["sources"][0]["fact_ids"]
    sections = studio.native_sources(p["id"], current["revision"], limit=1000)["sources"]
    grouped = studio.native_sources(p["id"], current["revision"], group_by="artifact", limit=1000)
    assert 1 < grouped["total"] <= len(sections)
    first_page = studio.native_sources(p["id"], current["revision"], group_by="artifact", limit=1)
    assert first_page["sources"] == grouped["sources"][:1] and first_page["next_offset"] == 1
    # Search the entire catalogue before pagination, including identifiers whose
    # artifact would not appear on the unfiltered first page.
    last = grouped["sources"][-1]
    filtered = studio.native_sources(p["id"], current["revision"], group_by="artifact", limit=1,
                                     search=last["source_artifact_id"].lower())
    assert filtered["sources"] == [last] and filtered["total"] == 1
    assert filtered["next_offset"] is None
    constituents = [item for item in sections if item["source_artifact_id"] == last["source_artifact_id"]]
    assert last["section_count"] == len(constituents)
    assert last["sections"] == [{"index": item["section_index"], "heading": item["heading"]} for item in constituents]
    assert last["fact_ids"] == sorted({fact for item in constituents for fact in item["fact_ids"]})
    assert studio.native_sources(p["id"], current["revision"], search="missing-artifact-search")["total"] == 0
    request = studio.interview_request(p["id"], current["revision"], "Plan a long native corpus using accepted evidence")
    assert request["native_sources"]["sources"][0] == sources["sources"][0]
    compile_job = studio.store.enqueue(p["id"], current["revision"], RunOptions(operation="compile", batch_limit=1))
    run_job(studio, compile_job["id"])
    result = studio.store.job(compile_job["id"])
    assert result["status"] == "complete", result
    assert result["result"]["report"]["companies"] == 1
    assert len(calls) == 1


def test_interview_proposals_are_reviewed_and_revision_bound(project):
    studio, p = project
    request = studio.interview_request(p["id"], p["revision"], "We need 36 inventory evaluations.")
    assert request["schema"] == "worldloom.company-interview/v1"
    spec = ProjectSpec.model_validate(p["spec"])
    proposal = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"count": 36}),)})
    reply = InterviewReply(request_id=request["request_id"], message="I propose increasing the inventory quota.", proposal=proposal)
    result = studio.accept_interview(p["id"], reply)
    assert result["changes"]
    assert studio.store.get(p["id"])["revision"] == p["revision"]
    assert studio.accept_interview(p["id"], reply) == result
    applied = studio.apply_interview(p["id"], reply.request_id)
    assert applied["spec"]["use_cases"][0]["count"] == 36
    with pytest.raises(StudioConflict):
        studio.apply_interview(p["id"], reply.request_id)
    with pytest.raises(StudioConflict):
        studio.accept_interview(p["id"], reply.model_copy(update={"message": "Different reply"}))


def test_cross_company_and_unknown_process_references_refuse(project):
    _studio, p = project
    document = p["spec"]
    document["use_cases"][0]["owner"] = "Missing BU"
    with pytest.raises(ValueError, match="unknown business unit"):
        ProjectSpec.model_validate(document)
    document["use_cases"][0]["owner"] = p["spec"]["structure"]["bus"][0]["name"]
    document["use_cases"][0]["activities"] = ["fabricated"]
    with pytest.raises(ValueError, match="process outside"):
        ProjectSpec.model_validate(document)


def test_worker_claim_and_recovery_do_not_overlap_live_writer(project):
    studio, p = project
    job = studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="build"))
    assert studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="build"))["id"] == job["id"]
    with writer_lock(studio.root):
        assert not run_job(studio, job["id"])
        assert not recover(studio)
    assert run_job(studio, job["id"])
    assert studio.store.job(job["id"])["status"] == "complete"
    assert not run_job(studio, job["id"])
    with studio.store.connection() as db:
        db.execute("UPDATE jobs SET status='running' WHERE id=?", (job["id"],))
    assert recover(studio)
    assert studio.store.job(job["id"])["status"] == "interrupted"
    studio.store.retry(job["id"])
    assert run_job(studio, job["id"])


def test_harness_job_records_reply_and_never_applies_it(project, monkeypatch):
    from worldloom.execseam import ExecReply
    studio, p = project
    calls = []
    def adapter(command, payload, **kwargs):
        calls.append(payload)
        return ExecReply({"request_id": payload["request_id"], "message": "Which teams own the approval?", "questions": ["Who approves?"]}, "")
    monkeypatch.setattr("worldloom.execseam.run_exec", adapter)
    job = studio.store.enqueue(p["id"], p["revision"], RunOptions(operation="interview", message="Help define the approval flow."))
    run_job(studio, job["id"], harness_command="trusted-adapter")
    assert studio.store.job(job["id"])["status"] == "complete"
    assert len(calls) == 1
    assert studio.store.get(p["id"])["revision"] == p["revision"]
    # Exact recorded authoring response is replayable without another model call.
    studio.execute(job["id"], harness_command="trusted-adapter")
    assert len(calls) == 1


def test_installed_harness_adapters_parse_only_final_output(tmp_path, monkeypatch):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        assert kwargs["shell"] is False
        assert "bounded-task" in kwargs["input"]
        if argv[0] == "codex":
            Path(argv[argv.index("--output-last-message") + 1]).write_text('{"message":"done"}')
            return subprocess.CompletedProcess(argv, 0, "progress", "")
        return subprocess.CompletedProcess(argv, 0, '{"result":"{\\"message\\":\\"done\\"}"}', "")
    monkeypatch.setattr(subprocess, "run", run)
    assert invoke("codex", {"message": "bounded-task"}) == {"message": "done"}
    assert invoke("claude", {"message": "bounded-task"}) == {"message": "done"}
    assert "read-only" in commands[0]
    assert "plan" in commands[1]
    with pytest.raises(ValueError):
        command_for("arbitrary-command", tmp_path / "result")


def test_native_codex_write_scope_requires_operator_opt_in(tmp_path, monkeypatch):
    commands = []
    def run(argv, **kwargs):
        commands.append(argv)
        Path(argv[argv.index("--output-last-message") + 1]).write_text('{"request_id":"one"}')
        return subprocess.CompletedProcess(argv, 0, "", "")
    monkeypatch.setattr(subprocess, "run", run)
    payload = {"schema": "worldloom.native-trial/v1", "task": {"operation": "update"}, "output_directory": str(tmp_path)}
    invoke("codex", payload)
    assert "read-only" in commands[-1] and "--cd" not in commands[-1]
    invoke("codex", payload, allow_native_writes=True)
    assert "workspace-write" in commands[-1]
    assert commands[-1][commands[-1].index("--cd") + 1] == str(tmp_path)
    assert not any("bypass" in arg or arg == "--ignore-rules" for arg in commands[-1])
    invoke("codex", {**payload, "schema": "worldloom.company-interview/v1"}, allow_native_writes=True)
    assert "read-only" in commands[-1]
    with pytest.raises(ValueError, match="existing absolute directory"):
        invoke("codex", {**payload, "output_directory": "relative"}, allow_native_writes=True)


@pytest.fixture
def http_server(tmp_path):
    server = StudioServer(tmp_path, port=0, launch_workers=False)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield server
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


def http(server, path, body=None, **headers):
    if body is not None:
        headers = {"Content-Type": "application/json", "X-Worldloom-Studio": "1", **headers}
    request = Request(f"http://127.0.0.1:{server.server_port}" + path,
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
    return urlopen(request, timeout=10)


def test_http_native_preparation_uses_existing_worker_and_requires_review(http_server, monkeypatch):
    server = http_server
    p = server.studio.store.create(preset())
    with http(server, f"/api/projects/{p['id']}/workflow") as response:
        assert json.load(response)["next_action"]["operation"] == "build"
    calls = []
    def prepare(project, revision, request):
        calls.append(request.use_case_id)
        return {"revision": revision, "spec": p["spec"], "summary": {"tasks": 1}}
    monkeypatch.setattr(server.studio, "prepare_native", prepare)
    body = {"revision": p["revision"], "request": {"use_case_id": p["spec"]["use_cases"][0]["id"]}}
    with http(server, f"/api/projects/{p['id']}/prepare-native", body) as response:
        job = json.load(response)
    assert calls == [] and job["status"] == "queued"
    assert run_job(server.studio, job["id"])
    assert len(calls) == 1
    assert server.studio.store.get(p["id"])["revision"] == p["revision"]
    assert server.studio.store.job(job["id"])["result"]["summary"]["tasks"] == 1


def test_data_creation_proposals_are_readonly_and_revision_bound(project, monkeypatch):
    studio, p = project
    case_id = p["spec"]["use_cases"][0]["id"]
    monkeypatch.setattr(studio, "snapshot", lambda *a, **k: pytest.fail("planning generated company data"))
    proposal = studio.prepare_data(p["id"], p["revision"], {"query_counts": {case_id: 36}})
    assert proposal["project"] == p["id"] and proposal["revision"] == p["revision"]
    assert proposal["summary"]["requested_queries"][case_id] == 36
    assert proposal["spec"]["use_cases"][0]["count"] == 36
    assert studio.store.get(p["id"])["spec"] == p["spec"]
    assert len(studio.store.history(p["id"])) == 1 and studio.store.jobs(p["id"]) == []
    applied = studio.store.revise(p["id"], p["revision"], ProjectSpec.model_validate(proposal["spec"]),
                                  reason="Reviewed requested coverage")
    assert applied["revision"] != p["revision"]
    with pytest.raises(StudioConflict, match="company changed"):
        studio.prepare_data(p["id"], p["revision"], {"query_counts": {case_id: 48}})


def test_native_source_selection_requires_accepted_narration_and_valid_filters(project):
    studio, p = project
    assert studio.native_sources(p["id"], group_by="artifact", search="annual") == {
        "sources": [], "total": 0, "next_offset": None, "status": "select_accepted_narration"}
    for invalid in ({"offset": -1}, {"limit": 0}, {"limit": 1001}, {"group_by": "fact"}, {"search": "x" * 201}):
        with pytest.raises(ValueError, match="invalid native source"):
            studio.native_sources(p["id"], **invalid)


def test_http_data_creation_inspection_review_and_stale_refusal(http_server, monkeypatch):
    server = http_server
    p = server.studio.store.create(preset())
    monkeypatch.setattr(server.studio, "snapshot", lambda *a, **k: pytest.fail("planning generated company data"))
    with http(server, f"/api/projects/{p['id']}/creation") as response:
        creation = json.load(response)
    assert creation["project"] == p["id"] and creation["revision"] == p["revision"]
    assert creation["simulations"] and all(item["supported"] for item in creation["simulations"])
    simulation = creation["simulations"][0]
    assert simulation["total_rows"] == sum(simulation["table_rows"].values())
    request = {"simulation_target": simulation["target"], "stores": 4}
    with http(server, f"/api/projects/{p['id']}/prepare-data", {"revision": p["revision"], "request": request}) as response:
        proposal = json.load(response)
    assert proposal["summary"]["simulation"]["dimensions"]["stores"] == 4
    assert server.studio.store.get(p["id"])["revision"] == p["revision"]
    assert server.studio.store.jobs(p["id"]) == []
    with http(server, f"/api/projects/{p['id']}/revise", {
            "revision": p["revision"], "spec": proposal["spec"], "reason": "Reviewed data sizing"}) as response:
        applied = json.load(response)
    assert applied["revision"] != p["revision"]
    with pytest.raises(HTTPError) as error:
        http(server, f"/api/projects/{p['id']}/prepare-data", {"revision": p["revision"], "request": request})
    assert error.value.code == 409
    with pytest.raises(HTTPError) as error:
        http(server, f"/api/projects/{p['id']}/prepare-data", {
            "revision": applied["revision"], "request": {"start_period": "2026-01"}})
    assert error.value.code == 422
    with http(server, "/creation.js") as response:
        assert "text/javascript" in response.headers["Content-Type"]
        assert response.read()


def test_http_native_source_filters_are_forwarded(http_server, monkeypatch):
    p = http_server.studio.store.create(preset())
    calls = []
    def sources(project, revision, **kwargs):
        calls.append((project, revision, kwargs))
        return {"sources": [], "total": 0, "next_offset": None, "status": "accepted"}
    monkeypatch.setattr(http_server.studio, "native_sources", sources)
    with http(http_server, f"/api/projects/{p['id']}/native-sources?revision={p['revision']}&offset=2&limit=5&group_by=artifact&search=annual") as response:
        assert json.load(response)["sources"] == []
    assert calls == [(p["id"], p["revision"], {"offset": 2, "limit": 5, "group_by": "artifact", "search": "annual"})]


def test_http_create_interview_revision_and_content_security(http_server):
    server = http_server
    with http(server, "/") as response:
        assert b"Worldloom Studio" in response.read()
        assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
    with http(server, "/api/projects", preset().model_dump(mode="json")) as response:
        p = json.load(response)
    with http(server, f"/api/projects/{p['id']}") as response:
        result = json.load(response)
    assert result["processes"]["rows"]
    with http(server, f"/api/projects/{p['id']}/run", {"revision": p["revision"], "options": {"operation": "build"}}) as response:
        job = json.load(response)
    assert job["status"] == "queued"
    with pytest.raises(HTTPError) as error:
        http(server, "/api/projects", preset().model_dump(mode="json"), Origin="https://untrusted.example")
    assert error.value.code == 403
    with pytest.raises(HTTPError) as error:
        http(server, "/api/bootstrap", Host="untrusted.example")
    assert error.value.code == 403
    with pytest.raises(HTTPError) as error:
        http(server, f"/api/projects/{p['id']}/run", {"revision": p["revision"], "options": {"operation": "interview", "message": "hello", "command": "evil"}})
    assert error.value.code == 422


def test_http_external_worker_compiles_and_exposes_verified_evidence(http_server):
    server = http_server
    server.launch_workers = True
    spec = preset()
    spec = spec.model_copy(update={"use_cases": (spec.use_cases[0].model_copy(update={"count": 4}),)})
    with http(server, "/api/projects", spec.model_dump(mode="json")) as response:
        p = json.load(response)
    with http(server, f"/api/projects/{p['id']}/run", {"revision": p["revision"], "options": {"operation": "compile"}}) as response:
        job = json.load(response)
    try:
        deadline = time.monotonic() + 90
        while job["status"] in {"queued", "running"} and time.monotonic() < deadline:
            time.sleep(0.05)
            with http(server, f"/api/jobs/{job['id']}") as response:
                job = json.load(response)
        assert job["status"] == "complete", job
        assert job["result"]["report"]["complete"]
        with http(server, f"/api/projects/{p['id']}/evals") as response:
            rows = json.load(response)["rows"]
        assert len(rows) == 4
        with http(server, f"/api/projects/{p['id']}/evidence?id={rows[0]['id']}") as response:
            evidence = json.load(response)
        assert evidence["row"] == rows[0]
        assert evidence["proof"]["query_id"] == rows[0]["query_id"]
        assert evidence["records"] and evidence["total_records"] >= len(evidence["records"])
        assert evidence["expected_evidence_ids"]
        dataset = server.studio.path("datasets", job["result"]["dataset"])
        # Inspection must authenticate the stored dataset before revealing proof.
        (dataset / "queryset.jsonl").write_text("{}\n")
        with pytest.raises(HTTPError) as error:
            http(server, f"/api/projects/{p['id']}/evidence?id={rows[0]['id']}")
        assert error.value.code == 422
    finally:
        if server.child is not None:
            if server.child.poll() is None:
                server.child.terminate()
            server.child.wait(timeout=10)


def test_cli_init_show_and_interview_match_sdk(tmp_path):
    runner = CliRunner()
    spec = tmp_path / "company.json"
    spec.write_text(preset().model_dump_json())
    root = tmp_path / "workspace"
    result = runner.invoke(app, ["studio", "init", str(spec), "-w", str(root)])
    assert result.exit_code == 0, result.output
    project = json.loads(result.output)
    shown = runner.invoke(app, ["studio", "show", project["id"], "-w", str(root)])
    assert shown.exit_code == 0, shown.output
    request = tmp_path / "request.json"
    requested = runner.invoke(app, ["studio", "interview", "request", project["id"], "--message", "Describe our workflows", "-o", str(request), "-w", str(root)])
    assert requested.exit_code == 0, requested.output
    assert json.loads(request.read_text())["revision"] == project["revision"]


def test_console_javascript_parses_and_assets_are_packaged(project):
    import shutil
    from importlib.resources import files
    root = files("worldloom.studio").joinpath("static")
    assert root.joinpath("index.html").is_file()
    assert root.joinpath("style.css").is_file()
    if shutil.which("node"):
        subprocess.run(["node", "--check", str(root.joinpath("app.js"))], check=True, capture_output=True)
        studio, p = project
        result = subprocess.run(["node", str(Path(__file__).resolve().parents[1] / "tools/check_studio_ui.mjs")],
                                input=json.dumps({"company": studio.describe(p["id"]), "catalogue": studio.catalogue()}),
                                text=True, capture_output=True)
        assert result.returncode == 0, result.stderr


def test_snapshot_recovers_crash_before_intent_write(project):
    import shutil

    studio, p = project
    spec = ProjectSpec.model_validate(p["spec"])
    _, location = studio.snapshot(spec)
    expected = _files(location)
    staging = location.with_name(location.name + ".pending")
    staging.mkdir()
    shutil.rmtree(location)
    _, recovered = studio.snapshot(spec)
    assert recovered == location and _files(recovered) == expected
    assert not staging.exists()
