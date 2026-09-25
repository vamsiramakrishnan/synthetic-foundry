"""Studio's pack experience: upload, generate with a harness, choose for a company, replay exactly.

Also pins the migration that moved Studio's literals into packs: the retail,
banking and connected presets, their snapshot identities and the interview
instructions are compared with what the code produced before any of it moved
(``fixtures/studio-presets.json``, captured at the base commit).
"""

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

from worldloom import packkit
from worldloom.cli import app
from worldloom.providers import digest
from worldloom.studio import ProjectSpec, RunOptions, Studio, preset
from worldloom.studio.harness import reply_schema, role_for
from worldloom.studio.service import PackRefused, snapshot_intent
from worldloom.studio.worker import run_job

BASE = json.loads((Path(__file__).parent / "fixtures" / "studio-presets.json").read_text())

OPERATIONAL = {
    "engine": "banking", "geo": "australia", "countries": ["AU"], "workflow": "banking", "program": "banking",
    "sizing": {"borrowers": 12, "ticks": 8}, "failures": ["none"],
    "incident": {"table": "loan", "signal": "arrears", "title": "Member arrears"},
    "use_case": {"id": "member-arrears", "title": "Review member arrears", "count": 6},
}


def envelope(name: str = "credit-union", **body: object) -> dict[str, object]:
    return {"schema": "worldloom.pack/v1", "kind": "industry", "name": name, "title": "Credit union",
            "body": {"industry": "banking", "engine": "banking", "terms": {"customer": "member"},
                     "example": {"company_name": "Harbour Mutual", "description": "A member-owned lender."},
                     "operational": OPERATIONAL, **body}}


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    from worldloom.packkit.active import forget_defaults

    packkit.refresh()
    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


@pytest.fixture
def studio(tmp_path: Path) -> Studio:
    return Studio(tmp_path / "workspace")


# -- the migration is byte-identical ----------------------------------------------------------


@pytest.mark.parametrize(("key", "engine", "name"), [("retail", "retail", None), ("banking", "banking", "One Bank"),
                                                     ("retail-connected", "retail-connected", None)])
def test_presets_are_the_specs_the_hardcoded_branches_built(key: str, engine: str, name: str | None) -> None:
    spec = preset(engine, name)
    assert spec.model_dump(mode="json") == BASE[key]
    if key in BASE["intents"]:
        assert digest(snapshot_intent(spec)) == BASE["intents"][key]


def test_interview_instructions_are_the_prompt_pack_texts_unchanged(studio: Studio) -> None:
    created = studio.store.create(preset())
    request = studio.interview_request(created["id"], created["revision"], "Describe the company")
    assert request["instructions"] == BASE["interview_instructions"]


def test_preset_budgets_mirror_the_project_field_defaults() -> None:
    from worldloom.studio.operational import sizing

    fields = ProjectSpec.model_fields
    for key, value in sizing().items():
        default = fields[key].default_factory() if fields[key].default_factory else fields[key].default  # type: ignore[call-arg]
        assert value == default, key


# -- a project's packs ------------------------------------------------------------------------


def test_a_project_without_packs_dumps_and_snapshots_as_before() -> None:
    spec = preset()
    assert "packs" not in spec.model_dump(mode="json")
    assert "packs" not in snapshot_intent(spec)
    assert "pack_kind" not in RunOptions(operation="compile").model_dump(mode="json")


def test_project_packs_are_references_one_per_kind() -> None:
    document = preset().model_dump(mode="json")
    with pytest.raises(ValueError, match="industry, prompts, policy pack reference"):
        ProjectSpec.model_validate({**document, "packs": ["company:acme"]})
    with pytest.raises(ValueError, match="two industry packs"):
        ProjectSpec.model_validate({**document, "packs": ["industry:a", "industry:b"]})


def test_an_upload_is_refused_with_every_finding(studio: Studio) -> None:
    bad = envelope(terms={"Site": "branch"}, operational={**OPERATIONAL, "program": "hospital",
                                                          "incident": {"table": "ward", "signal": "x", "title": "t"}})
    with pytest.raises(PackRefused) as refused:
        studio.install_pack(bad)
    findings = refused.value.findings
    assert any(f.startswith("terms.Site") for f in findings)
    assert any(f.startswith("operational.program") and "hospital" in f for f in findings)
    assert not (studio.pack_root / "industry" / "credit-union.json").exists()


def test_an_operational_block_naming_a_missing_column_is_refused(studio: Studio) -> None:
    bad = envelope(operational={**OPERATIONAL, "incident": {"table": "loan", "signal": "late", "title": "t"}})
    with pytest.raises(PackRefused) as refused:
        studio.install_pack(bad)
    assert any("operational.incident.signal" in f and "arrears" in f for f in refused.value.findings)


def test_an_uploaded_industry_starts_a_company_and_is_pinned_into_it(studio: Studio) -> None:
    stored = studio.install_pack(envelope())
    assert stored["installed"] == "industry:credit-union" and "@" in stored["pinned"]
    listed = {p["ref"]: p for p in studio.packs("industry")}
    assert listed["industry:credit-union"]["origin"] == "workspace"
    catalogue = {e["key"]: e for e in studio.catalogue()["examples"]}
    assert catalogue["credit-union"]["company_name"] == "Harbour Mutual" and catalogue["credit-union"]["operational"]
    assert catalogue["retail-connected"]["featured"]

    with studio.in_force():
        spec = preset("credit-union")
    assert spec.packs == (stored["pinned"],)
    assert spec.company["identity"]["company_name"] == "Harbour Mutual"
    assert spec.use_cases[0].id == "member-arrears" and spec.use_cases[0].count == 6
    assert spec.use_cases[0].incident_rule is not None and spec.use_cases[0].incident_rule.title == "Member arrears"
    created = studio.store.create(spec)
    assert created["spec"]["packs"] == [stored["pinned"]]
    assert snapshot_intent(spec)["packs"] == [stored["pinned"]]


def test_choosing_a_pack_is_a_pinned_revision_and_changes_the_snapshot(studio: Studio) -> None:
    created = studio.store.create(preset())
    before = digest(snapshot_intent(ProjectSpec.model_validate(created["spec"])))
    with pytest.raises(ValueError, match="no pack industry:nowhere"):
        studio.choose_packs(created["id"], created["revision"], ("industry:nowhere",), reason="Try")
    stored = studio.install_pack(envelope())
    revised = studio.choose_packs(created["id"], created["revision"], ("industry:credit-union",), reason="Credit union")
    assert revised["spec"]["packs"] == [stored["pinned"]]
    assert digest(snapshot_intent(ProjectSpec.model_validate(revised["spec"]))) != before
    cleared = studio.choose_packs(created["id"], revised["revision"], ("industry:default",), reason="Back")
    assert "packs" not in cleared["spec"]
    assert digest(snapshot_intent(ProjectSpec.model_validate(cleared["spec"]))) == before


def test_a_pinned_pack_that_moved_is_refused_rather_than_rebuilt(studio: Studio) -> None:
    created = studio.store.create(preset())
    studio.install_pack(envelope())
    revised = studio.choose_packs(created["id"], created["revision"], ("industry:credit-union",), reason="Credit union")
    studio.install_pack(envelope(terms={"customer": "owner"}), replace=True)
    spec = ProjectSpec.model_validate(revised["spec"])
    with pytest.raises(ValueError, match="content changed"):
        studio.store.revise(created["id"], revised["revision"], spec.model_copy(update={"seed": 7}), reason="Reseed")


def test_the_interview_runs_under_the_projects_industry(studio: Studio) -> None:
    override = "Interview the operator about this ONE {{term:company}} of {{term:customers}}."
    studio.install_pack(envelope(prompts={"studio.interview.rule.01": override}))
    created = studio.store.create(preset())
    revised = studio.choose_packs(created["id"], created["revision"], ("industry:credit-union",), reason="Credit union")
    request = studio.interview_request(created["id"], revised["revision"], "Describe the company")
    assert request["instructions"][0] == "Interview the operator about this ONE company of members."
    assert request["instructions"][1:] == BASE["interview_instructions"][1:]


# -- generating a pack with a harness -----------------------------------------------------------


def _harness(tmp_path: Path) -> str:
    """A harness that proposes the credit-union pack for whatever request it is handed."""
    script = tmp_path / "harness.py"
    body = json.dumps({key: value for key, value in envelope().items() if key not in {"schema", "kind"}})
    script.write_text(
        "import json, sys\n"
        "request = json.load(sys.stdin)\n"
        f"proposal = json.loads({body!r})\n"
        "print(json.dumps({'request_id': request['request_id'], 'message': 'Proposed.', 'proposal': proposal}))\n")
    # Windows hands the string to CreateProcess whole, whose quoting is
    # `list2cmdline`'s; `shlex` quoting there is how `test_exec_seam._cmd`
    # once failed the Windows leg too.
    argv = [sys.executable, str(script)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)


def test_the_pack_interview_is_a_structured_no_tools_seam() -> None:
    assert role_for({"schema": "worldloom.pack-interview/v1"}) == packkit.text("studio.harness.role.pack_interview")
    schema = json.loads(reply_schema({"schema": "worldloom.pack-interview/v1"}) or "{}")
    assert schema["required"] == ["request_id", "message"] and "proposal" in schema["properties"]


def test_a_workspace_job_authors_a_pack_with_the_configured_harness(studio: Studio, tmp_path: Path) -> None:
    command = _harness(tmp_path)
    options = RunOptions(operation="pack_author", pack_kind="industry", pack_name="credit-union",
                         message="A member-owned lender", harness_identity=digest(command))
    job = studio.store.enqueue_workspace(options)
    assert job["project"] == "" and job["options"]["pack_kind"] == "industry"
    assert run_job(studio, job["id"], harness_command=command)
    finished = studio.store.job(job["id"])
    assert finished["status"] == "complete", finished["error"]
    assert finished["result"]["status"] == "accepted" and finished["result"]["pinned"].startswith("industry:credit-union@")
    assert (studio.pack_root / "industry" / "credit-union.json").is_file()


def test_the_cli_authors_through_a_harness_and_through_files(studio: Studio, tmp_path: Path) -> None:
    runner = CliRunner()
    workspace = str(studio.root)
    authored = runner.invoke(app, ["studio", "pack", "author", "industry", "--message", "A member-owned lender",
                                   "--harness-command", _harness(tmp_path), "-w", workspace])
    assert authored.exit_code == 0, authored.output
    assert json.loads(authored.output)["status"] == "accepted"
    (studio.pack_root / "industry" / "credit-union.json").unlink()
    packkit.refresh()

    request = tmp_path / "request.json"
    asked = runner.invoke(app, ["studio", "pack", "interview", "request", "industry", "--message", "A lender",
                                "--name", "credit-union", "-o", str(request), "-w", workspace])
    assert asked.exit_code == 0, asked.output
    payload = json.loads(request.read_text())
    reply = tmp_path / "reply.json"
    proposal = {key: value for key, value in envelope().items() if key not in {"schema", "kind"}}
    reply.write_text(json.dumps({"request_id": payload["request_id"], "message": "Here.",
                                 "proposal": {**proposal, "body": {**proposal["body"], "terms": {"Site": "x"}}}}))
    refused = runner.invoke(app, ["studio", "pack", "interview", "accept", "--request", str(request),
                                  "--from", str(reply), "-w", workspace])
    assert refused.exit_code == 3 and "terms.Site" in refused.output
    reply.write_text(json.dumps({"request_id": payload["request_id"], "message": "Here.", "proposal": proposal}))
    accepted = runner.invoke(app, ["studio", "pack", "interview", "accept", "--request", str(request),
                                   "--from", str(reply), "-w", workspace])
    assert accepted.exit_code == 0, accepted.output
    assert json.loads(accepted.output)["installed"] == "industry:credit-union"


# -- the console routes -----------------------------------------------------------------------------


@pytest.fixture
def server(studio: Studio):
    from worldloom.studio.server import StudioServer

    running = StudioServer(studio.root, port=0, launch_workers=False)
    thread = Thread(target=running.serve_forever, daemon=True)
    thread.start()
    yield running
    running.shutdown()
    running.server_close()
    thread.join(timeout=5)


def call(server, path: str, body: object = None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json", "X-Worldloom-Studio": "1"} if body is not None else {}
    request = Request(f"http://127.0.0.1:{server.server_port}{path}",
                      data=json.dumps(body).encode() if body is not None else None, headers=headers)
    try:
        with urlopen(request, timeout=60) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_the_console_uploads_lists_shows_and_refuses_packs(server) -> None:
    status, refused = call(server, "/api/packs", envelope(terms={"Site": "branch"}))
    assert status == 400 and any(f.startswith("terms.Site") for f in refused["findings"])
    status, stored = call(server, "/api/packs", envelope())
    assert status == 201 and stored["installed"] == "industry:credit-union"
    status, listed = call(server, "/api/packs?kind=industry")
    assert status == 200 and {"industry:credit-union", "industry:default"} <= {p["ref"] for p in listed["packs"]}
    status, shown = call(server, "/api/packs/industry/credit-union")
    assert status == 200 and shown["pinned"] == stored["pinned"] and shown["findings"] == []
    status, example = call(server, "/api/preset?engine=credit-union")
    assert status == 200 and example["packs"] == [stored["pinned"]]
    status, _ = call(server, "/api/packs/author", {"kind": "industry", "message": "A lender"})
    assert status == 422


_UI = r"""
import fs from "node:fs"; import vm from "node:vm";
const data = JSON.parse(fs.readFileSync(0, "utf8")), elements = new Map(), requests = [];
const document = {hidden:false, activeElement:null, addEventListener() {}, querySelector(key) {
  if (!elements.has(key)) elements.set(key, {innerHTML:"", textContent:"", open:false, showModal() {this.open = true;}, close() {}});
  return elements.get(key);}};
const context = vm.createContext({document, structuredClone, Blob, URL, FormData: class {}, setTimeout() {}, setInterval() {},
  fetch: async (path, options) => { requests.push({path, body: options.body ? JSON.parse(options.body) : undefined});
    return {ok: true, json: async () => path === "/api/bootstrap" ? {projects: [], catalogue: data.catalogue, harness_configured: true}
      : path.startsWith("/api/packs") ? data.packs : data.spec}; }});
for (const file of ["creation.js", "app.js"]) vm.runInContext(fs.readFileSync(data.root + "/" + file, "utf8"), context);
await new Promise(setImmediate);
const out = {onboarding: document.querySelector("#app").innerHTML};
await vm.runInContext("action('go-packs', {})", context);
out.packs = document.querySelector("#app").innerHTML;
try { await vm.runInContext("action('example', {dataset: {key: 'credit-union'}})", context); } catch (error) { /* the mock serves no project */ }
out.requests = requests.map(r => r.path);
console.log(JSON.stringify(out));
"""


def test_the_console_lists_examples_and_packs_from_the_service(studio: Studio) -> None:
    import shutil
    import subprocess
    from importlib.resources import files

    if not shutil.which("node"):
        pytest.skip("node is not installed")
    studio.install_pack(envelope())
    payload = {"catalogue": studio.catalogue(), "packs": {"packs": studio.packs(), "jobs": [
        {"id": "j", "status": "complete", "options": {"pack_kind": "industry", "message": "<b>lender</b>"},
         "result": {"status": "questions", "questions": ["Which country?"], "findings": []}}]},
        "spec": preset().model_dump(mode="json"), "root": str(files("worldloom.studio").joinpath("static"))}
    result = subprocess.run(["node", "--input-type=module", "-e", _UI], input=json.dumps(payload), text=True,
                            capture_output=True, timeout=60)
    assert result.returncode == 0, result.stderr
    out = json.loads(result.stdout)
    assert "Explore connected retail" in out["onboarding"] and "Harbour Mutual" in out["onboarding"]
    assert 'data-key="retail-connected"' in out["onboarding"] and 'data-key="banking"' in out["onboarding"]
    assert "industry:credit-union" in out["packs"] and "Generate with harness" in out["packs"]
    assert "Which country?" in out["packs"] and "<b>lender" not in out["packs"]
    assert "/api/preset?engine=credit-union" in out["requests"]


def test_a_cross_origin_upload_is_refused(server) -> None:
    request = Request(f"http://127.0.0.1:{server.server_port}/api/packs", data=json.dumps(envelope()).encode(),
                      headers={"Content-Type": "application/json", "X-Worldloom-Studio": "1",
                               "Origin": "http://evil.example"})
    with pytest.raises(HTTPError) as refusal:
        urlopen(request, timeout=10)
    assert refusal.value.code == 403


def test_a_workspace_takes_no_default_named_pack(studio: Studio) -> None:
    """A workspace `policy:default` changed every project with no revision saying so."""
    bad = {"schema": "worldloom.pack/v1", "kind": "policy", "name": "default",
           "body": {"values": {"studio.project.pool_size": 7}}}
    with pytest.raises((PackRefused, ValueError), match="default"):
        studio.install_pack(bad)


def test_an_industry_packs_own_policy_reaches_its_preset(studio: Studio) -> None:
    studio.install_pack(envelope("bank3", policy={"studio.project.minimum_tasks": 5, "studio.project.pool_size": 7}))
    with studio.in_force():
        spec = preset("bank3")
    assert (spec.minimum_tasks, spec.pool_size) == (5, 7)
    assert spec.packs and spec.packs[0].startswith("industry:bank3@")


def test_a_customised_default_on_the_machine_is_part_of_snapshot_identity(tmp_path: Path) -> None:
    spec = preset("retail")
    before = snapshot_intent(spec)
    home = tmp_path / "home" / "packs" / "prompts"
    home.mkdir(parents=True)
    (home / "default.json").write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "prompts", "name": "default",
                                                   "body": {"texts": {"pack.interview.role": "Custom {kind}."}}}))
    packkit.refresh()
    after = snapshot_intent(spec)
    assert "defaults" not in before and set(after["defaults"]) == {"prompts"}
