"""An agent pack's skill tree: real skills as files, linted, delivered natively, revised by diff.

The tree is the agent kind's codec: `policy.json` holds every field but
`files`, and `skills/<name>/...` holds the skills. A revision can then be a
unified diff, applied strictly (no fuzz), and every refusal names the hunk,
the line and what it expected.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from worldloom import packkit
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.evalrun import ExecAgent, case_from_row, run_case, service_for
from worldloom.evalrun.policy import (
    POLICY_FILE,
    from_tree,
    lint_files,
    materialise,
    tree,
)
from worldloom.packkit import diffs

runner = CliRunner()
_PROPERTY = settings(max_examples=150, deadline=2000, derandomize=True, database=None)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


def _skill(name: str, description: str = "Use after any write, to confirm it held.",
           body: str = "Fetch the record you wrote and compare each field you set.\n") -> str:
    return f"---\nname: {name}\ndescription: {description}\n---\n\n{body}"


_FILES = {
    "skills/verify/SKILL.md": _skill("verify"),
    "skills/verify/references/fields.md": "# Fields\n\nCompare `state` and `assigned_to`.\n",
    "skills/verify/scripts/compare.py": "import json\nimport sys\n\nprint(json.dumps(sys.argv[1:]))\n",
    "skills/verify/scripts/run.sh": "#!/bin/sh\necho ok\n",
}


def _body(files: dict[str, str] | None = None, **extra: Any) -> dict[str, Any]:
    return {"system": "Complete the request with the tools provided, then answer.", "files": dict(files or _FILES),
            **extra}


def _check(body: dict[str, Any]) -> list[str]:
    envelope = packkit.PackEnvelope(kind="agent", name="probe", body=body)
    resolved, findings = packkit.check(envelope)
    return list(findings) if resolved is not None else ["unresolved: " + "; ".join(findings)]


# -- lint -----------------------------------------------------------------------------------------------------


def test_a_well_formed_skill_tree_lints_clean() -> None:
    assert _check(_body()) == []
    resolved = packkit.resolve_envelope(packkit.PackEnvelope(kind="agent", name="probe", body=_body()))
    assert resolved.body.files == _FILES


@pytest.mark.parametrize(("path", "text", "expected"), [
    ("skills/verify/../escape.md", "x", "'..' segment"),
    ("/etc/skills/verify/SKILL.md", "x", "absolute path"),
    ("skills\\verify\\notes.md", "x", "backslash"),
    ("tools/verify/SKILL.md", "x", "only under `skills/`"),
    ("skills/notes.md", "x", "lives in a skill's directory"),
    ("skills/Verify/SKILL.md", _skill("Verify"), "lower-case letters and digits"),
    ("skills/verify/assets/logo.png", "x", "nothing else"),
    ("skills/verify/scripts/tool.rb", "puts 1", "nothing else"),
    ("skills/verify/.hidden.md", "x", "does not start with '.'"),
    ("skills/verify/scripts/broken.py", "def broken(:\n", "does not parse as Python"),
    ("skills/verify/scripts/empty.sh", "  \n", "an empty script"),
    ("skills/verify/references/keys.md", "-----BEGIN RSA PRIVATE KEY-----\nabc\n", "a private key block"),
    ("skills/verify/scripts/call.py", 'API_TOKEN = "abcd1234efgh5678ijkl"\n', "a credential"),
    ("skills/verify/references/shape.md", 'Reply {"answer": "done"}\n', "restates a reply shape"),
    ("skills/other/references/notes.md", "x", "skills/other/SKILL.md: missing"),
])
def test_a_tree_is_refused_with_a_finding_naming_the_file(path: str, text: str, expected: str) -> None:
    findings = _check(_body({**_FILES, path: text}))
    assert any(expected in finding for finding in findings), findings


@pytest.mark.parametrize(("skill", "expected"), [
    ("no frontmatter\n", "starts without frontmatter"),
    ("---\nname: verify\ndescription: open\n", "never closed"),
    (_skill("verified"), "must be 'verify'"),
    (_skill("verify", description=""), "`description` is empty"),
    (_skill("verify", body=""), "body after the frontmatter is empty"),
    ("---\nname: verify\ndescription: x\nallowed-tools: Bash\n---\nbody\n", "`allowed-tools` is not a key"),
    ("---\nname: verify\ndescription: |\n  long\n---\nbody\n", "write `description` on one line"),
])
def test_skill_frontmatter_is_checked(skill: str, expected: str) -> None:
    findings = _check(_body({**_FILES, "skills/verify/SKILL.md": skill}))
    assert any(expected in finding for finding in findings), findings


def test_size_caps_are_policy(monkeypatch: pytest.MonkeyPatch) -> None:
    per_file = int(packkit.policy("evalrun.agent_pack.max_file_bytes"))
    big = {**_FILES, "skills/verify/references/big.md": "x" * (per_file + 1)}
    assert any("max_file_bytes" in finding for finding in lint_files(big))
    per_tree = int(packkit.policy("evalrun.agent_pack.max_tree_bytes"))
    many = dict(_FILES)
    for index in range(per_tree // per_file + 2):
        many[f"skills/verify/references/part{index}.md"] = "y" * (per_file - 10)
    assert any("max_tree_bytes" in finding for finding in lint_files(many))


def test_a_string_skill_and_a_file_skill_of_one_name_collide() -> None:
    findings = _check(_body(skills={"verify": "Read it back."}))
    assert any("also defines this skill as a string" in finding for finding in findings)


def test_secrets_are_refused_without_repeating_them() -> None:
    token = "sk-" + "a1B2" * 8
    findings = lint_files({**_FILES, "skills/verify/scripts/leak.py": f'KEY = "{token}"\n'})
    assert findings and all(token not in finding for finding in findings)
    # A reference to a credential is not a credential.
    assert lint_files({**_FILES, "skills/verify/scripts/env.py": 'import os\nTOKEN = os.environ["API_TOKEN"]\n'}) == []


# -- the tree codec -------------------------------------------------------------------------------------------


def test_the_whole_policy_is_a_tree_and_reads_back() -> None:
    body = _body(turn_rules={"10": "Read back every write."}, max_turns=9)
    files = tree(body)
    assert sorted(files) == [POLICY_FILE, *sorted(_FILES)]
    stated = json.loads(files[POLICY_FILE])
    assert "files" not in stated and stated["max_turns"] == 9
    assert files[POLICY_FILE] == json.dumps(stated, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    assert from_tree(files) == body
    assert packkit.kind("agent").to_tree is not None and packkit.kind("industry").to_tree is None


@pytest.mark.parametrize(("extra", "expected"), [
    ({"README.md": "x"}, "policy.json and skills/ only"),
    ({"skills/../policy.json": "x"}, "'..' segment"),
    ({"/skills/x/SKILL.md": "x"}, "absolute path"),
])
def test_from_tree_refuses_paths_outside_its_boundary(extra: dict[str, str], expected: str) -> None:
    with pytest.raises(ValueError, match=expected.replace("(", r"\(").replace(".", r"\.")):
        from_tree({**tree(_body()), **extra})


def test_from_tree_refuses_a_policy_file_that_smuggles_files() -> None:
    with pytest.raises(ValueError, match="must not hold `files`"):
        from_tree({POLICY_FILE: json.dumps({"system": "x", "files": {"evil.py": "x"}})})
    with pytest.raises(ValueError, match="missing"):
        from_tree({"skills/verify/SKILL.md": _skill("verify")})


_SEGMENT = st.from_regex(r"[a-z][a-z0-9]{0,6}", fullmatch=True)
_TEXT = st.text(st.characters(codec="utf-8", exclude_categories=("Cs",)), max_size=60)
_LINES = st.lists(st.sampled_from(["alpha\n", "beta\n", "gamma\n", "delta\n", "\n", "no newline", "x\ry\n"]),
                  max_size=12).map("".join)


@_PROPERTY
@given(system=_TEXT.filter(lambda text: bool(text.strip())), skills=st.dictionaries(_SEGMENT, _TEXT, max_size=3),
       files=st.dictionaries(_SEGMENT.map(lambda name: f"skills/{name}/SKILL.md"), _TEXT, max_size=3),
       max_turns=st.none() | st.integers(1, 99))
def test_round_trip_property(system: str, skills: dict[str, str], files: dict[str, str], max_turns: int | None) -> None:
    body: dict[str, Any] = {"system": system, "skills": skills}
    if max_turns is not None:
        body["max_turns"] = max_turns
    if files:
        body["files"] = files
    assert from_tree(tree(body)) == body


# -- diffs ----------------------------------------------------------------------------------------------------


def test_render_is_deterministic_with_prefixes_and_dev_null() -> None:
    old = {"a.md": "one\ntwo\nthree\n", "gone.md": "bye\n"}
    new = {"a.md": "one\n2\nthree\n", "new.md": "hello\n"}
    text = diffs.render(old, new)
    assert text == diffs.render(dict(reversed(list(old.items()))), new)
    assert text.splitlines()[:2] == ["--- a/a.md", "+++ b/a.md"]
    assert "--- a/gone.md\n+++ /dev/null\n" in text and "--- /dev/null\n+++ b/new.md\n" in text
    assert diffs.apply(old, text) == new
    found = diffs.hunks(text)
    assert [(hunk.path, hunk.index) for hunk in found] == [("a.md", 1), ("gone.md", 1), ("new.md", 1)]
    assert found[0].header == "@@ -1,3 +1,3 @@"
    assert diffs.render(old, old) == ""


def test_apply_creates_and_deletes_files() -> None:
    created = diffs.apply({}, "--- /dev/null\n+++ b/skills/x/SKILL.md\n@@ -0,0 +1,2 @@\n+one\n+two\n")
    assert created == {"skills/x/SKILL.md": "one\ntwo\n"}
    assert diffs.apply(created, "--- a/skills/x/SKILL.md\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-one\n-two\n") == {}
    with pytest.raises(diffs.DiffError, match="already exists"):
        diffs.apply(created, "--- /dev/null\n+++ b/skills/x/SKILL.md\n@@ -0,0 +1 @@\n+one\n")
    with pytest.raises(diffs.DiffError, match="no such file"):
        diffs.apply({}, "--- a/missing.md\n+++ b/missing.md\n@@ -1 +1 @@\n-a\n+b\n")
    with pytest.raises(diffs.DiffError, match="leaves 1 line"):
        diffs.apply(created, "--- a/skills/x/SKILL.md\n+++ /dev/null\n@@ -1 +0,0 @@\n-one\n")


def test_apply_is_strict_and_says_where_and_what() -> None:
    lines = "".join(f"line {n}\n" for n in range(1, 21))
    edited = lines.replace("line 3\n", "LINE 3\n").replace("line 15\n", "LINE 15\n")
    patch = diffs.render({"skills/x/SKILL.md": lines}, {"skills/x/SKILL.md": edited})
    assert len(diffs.hunks(patch)) == 2
    drifted = lines.replace("line 14\n", "line fourteen\n")
    with pytest.raises(diffs.DiffError) as refused:
        diffs.apply({"skills/x/SKILL.md": drifted}, patch)
    assert str(refused.value) == ("hunk 2 of skills/x/SKILL.md does not apply at line 14: expected 'line 14\\n', "
                                  "found 'line fourteen\\n'")
    # No fuzz: the same hunk one line off is refused, not searched for.
    shifted = "extra\n" + lines
    with pytest.raises(diffs.DiffError, match=r"hunk 1 of skills/x/SKILL\.md does not apply at line 1"):
        diffs.apply({"skills/x/SKILL.md": shifted}, patch)
    with pytest.raises(diffs.DiffError, match="header counts"):
        diffs.apply({"a": "x\n"}, "--- a/a\n+++ b/a\n@@ -1,2 +1,2 @@\n-x\n+y\n")
    with pytest.raises(diffs.DiffError, match="expected a `--- a/<path>` file header"):
        diffs.apply({"a": "x\n"}, "Here is my patch:\n--- a/a\n+++ b/a\n")


def test_a_no_newline_marker_belongs_only_after_a_files_last_line() -> None:
    # Where it belongs: the old file's last line lacks a newline, the new one adds a line after it.
    good = "--- a/a\n+++ b/a\n@@ -1,2 +1,3 @@\n x\n-y\n\\ No newline at end of file\n+y\n+z\n"
    assert diffs.apply({"a": "x\ny"}, good) == {"a": "x\ny\nz\n"}
    # After a line with more of its side to come, the marker used to glue two lines into one.
    glued = "--- a/a\n+++ b/a\n@@ -1,2 +1,2 @@\n-x\n\\ No newline at end of file\n-y\n+x\n+y\n"
    with pytest.raises(diffs.DiffError, match=r"line 5: hunk 1 of a has a no-newline marker after a line that is "
                                              r"not the last old line of the hunk"):
        diffs.apply({"a": "xy\n"}, glued)
    added = "--- a/a\n+++ b/a\n@@ -0,0 +1,2 @@\n+x\n\\ No newline at end of file\n+y\n"
    with pytest.raises(diffs.DiffError, match="not the last new line"):
        diffs.apply({}, added.replace("--- a/a", "--- /dev/null"))
    context = "--- a/a\n+++ b/a\n@@ -1,2 +1,3 @@\n x\n\\ No newline at end of file\n y\n+z\n"
    with pytest.raises(diffs.DiffError, match="not the last old or new line"):
        diffs.apply({"a": "xy\n"}, context)
    twice = "--- a/a\n+++ b/a\n@@ -1 +1 @@\n-x\n\\ No newline at end of file\n\\ No newline at end of file\n+y\n"
    with pytest.raises(diffs.DiffError, match="two no-newline markers in a row"):
        diffs.apply({"a": "x"}, twice)


def test_a_crlf_diff_is_refused_naming_its_line_endings() -> None:
    patch = diffs.render({"a.md": "x\n"}, {"a.md": "y\n"}).replace("\n", "\r\n")
    with pytest.raises(diffs.DiffError, match=r"line 1: the header ends in a carriage return; the diff has CRLF"):
        diffs.apply({"a.md": "x\n"}, patch)
    # A hunk header is held to the same rule when the file header was clean.
    mixed = "--- a/a.md\n+++ b/a.md\n@@ -1 +1 @@\r\n-x\n+y\n"
    with pytest.raises(diffs.DiffError, match=r"line 3: the header ends in a carriage return"):
        diffs.apply({"a.md": "x\n"}, mixed)


def test_hunks_can_be_left_out_and_the_rest_still_applies() -> None:
    lines = "".join(f"line {n}\n" for n in range(1, 21))
    edited = lines.replace("line 3\n", "LINE 3\n").replace("line 15\n", "LINE 15\n")
    base = {"f.md": lines}
    found = diffs.hunks(diffs.render(base, {"f.md": edited}))
    assert diffs.apply(base, diffs.join([found[1]]))["f.md"] == lines.replace("line 15\n", "LINE 15\n")
    assert diffs.apply(base, diffs.join([found[0]]))["f.md"] == lines.replace("line 3\n", "LINE 3\n")
    assert found[1].text.startswith("--- a/f.md\n+++ b/f.md\n@@ -12,7 +12,7 @@")


@_PROPERTY
@given(old=st.dictionaries(st.sampled_from(["a.md", "b/c.md", "d.py"]), _LINES, max_size=3),
       new=st.dictionaries(st.sampled_from(["a.md", "b/c.md", "e.sh"]), _LINES, max_size=3))
def test_render_then_apply_is_the_identity_property(old: dict[str, str], new: dict[str, str]) -> None:
    assert diffs.apply(old, diffs.render(old, new)) == new


# -- the interview --------------------------------------------------------------------------------------------


def _draft() -> dict[str, Any]:
    baseline = packkit.resolve("agent:baseline")
    return {"schema": "worldloom.pack/v1", "kind": "agent", "name": "careful", "title": "Careful",
            "body": baseline.data}


def _reply(payload: dict[str, Any], **proposal: Any) -> dict[str, Any]:
    return {"request_id": payload["request_id"], "message": "revised", "proposal": {"name": "careful", **proposal}}


def test_the_interview_accepts_a_diff_against_the_draft_tree() -> None:
    payload = packkit.request("agent", "A careful agent", name="careful", draft=_draft())
    assert payload["draft_tree"] == tree(_draft()["body"])
    assert "diff" in payload["response_schema"]["$defs"]["Proposal"]["properties"]
    assert packkit.text("pack.interview.tree") in payload["instructions"]
    patch = diffs.render(payload["draft_tree"], {**payload["draft_tree"], **_FILES})
    verdict = packkit.accept(payload, _reply(payload, diff=patch))
    assert verdict.status == "accepted", verdict.findings
    assert verdict.resolved is not None and verdict.resolved.body.files == _FILES
    assert verdict.envelope is not None and verdict.envelope.title == "Careful"


def test_the_interview_refuses_a_bad_diff_with_findings() -> None:
    payload = packkit.request("agent", "A careful agent", name="careful", draft=_draft())
    stale = "--- a/policy.json\n+++ b/policy.json\n@@ -1 +1 @@\n-{ \"system\": \"old\" }\n+{}\n"
    verdict = packkit.accept(payload, _reply(payload, diff=stale))
    assert verdict.status == "refused"
    assert verdict.findings[0].startswith("diff: hunk 1 of policy.json does not apply at line 1: expected")
    outside = diffs.render(payload["draft_tree"], {**payload["draft_tree"], "tools/run.py": "print(1)\n"})
    verdict = packkit.accept(payload, _reply(payload, diff=outside))
    assert verdict.status == "refused" and "policy.json and skills/ only" in verdict.findings[0]
    unlinted = diffs.render(payload["draft_tree"], {**payload["draft_tree"], "skills/verify/SKILL.md": "no frontmatter\n"})
    verdict = packkit.accept(payload, _reply(payload, diff=unlinted))
    assert verdict.status == "refused" and any("starts without frontmatter" in f for f in verdict.findings)
    both = packkit.accept(payload, _reply(payload, diff=outside, body={"system": "x"}))
    assert both.status == "refused" and "not both" in both.findings[0]


def test_a_reply_of_the_wrong_shape_is_refused_with_findings_not_raised() -> None:
    payload = packkit.request("agent", "A careful agent", name="careful", draft=_draft())
    for reply in ({"message": "no id"}, {"request_id": payload["request_id"], "questions": "one string"},
                  {"request_id": payload["request_id"], "proposal": {"name": "careful", "diff": 7}}, ["not", "an", "object"]):
        verdict = packkit.accept(payload, reply)  # type: ignore[arg-type]
        assert verdict.status == "refused" and verdict.findings, reply
        assert all("response_schema" in finding for finding in verdict.findings)
    verdict = packkit.accept(payload, {"message": "no id"})
    assert verdict.findings[0].startswith("request_id: ")
    # The loop hands the finding back and takes the corrected reply.
    replies: list[dict[str, Any]] = []

    def exchange(request: dict[str, Any]) -> dict[str, Any]:
        replies.append(request)
        if len(replies) == 1:
            return {"proposal": "the whole pack, as prose"}
        return _reply(request, diff=diffs.render(request["draft_tree"], {**request["draft_tree"], **_FILES}))

    authored = packkit.author("agent", "A careful agent", exchange, name="careful", draft=_draft())
    assert [item["status"] for item in authored.rounds] == ["refused", "accepted"]
    assert any(finding.startswith("request_id:") for finding in replies[1]["findings"])


def test_the_refusal_loop_takes_a_diff_until_it_lints() -> None:
    replies: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        base = payload["draft_tree"]
        files = {"skills/verify/SKILL.md": "no frontmatter\n"} if not replies else _FILES
        replies.append(payload)
        if payload["findings"]:
            # Revise against the refused draft, which is now the draft.
            files = {**_FILES, "skills/verify/SKILL.md": _skill("verify")}
        return _reply(payload, diff=diffs.render(base, {**base, **files}))

    authored = packkit.author("agent", "A careful agent", exchange, name="careful", draft=_draft())
    assert [item["status"] for item in authored.rounds] == ["refused", "accepted"]
    assert replies[1]["draft_tree"]["skills/verify/SKILL.md"] == "no frontmatter\n"


def test_kinds_without_a_codec_keep_body_proposals_only() -> None:
    payload = packkit.request("industry", "A hospital", name="hospital")
    assert "draft_tree" not in payload
    assert "diff" not in payload["response_schema"]["$defs"]["Proposal"]["properties"]
    verdict = packkit.accept(payload, {"request_id": payload["request_id"], "message": "",
                                       "proposal": {"name": "hospital", "diff": "--- a/x\n+++ b/x\n"}})
    assert verdict.status == "refused" and "has no tree form" in verdict.findings[0]


# -- delivery -------------------------------------------------------------------------------------------------


_RECORDING_CHILD = """
import json, sys
from pathlib import Path
raw = sys.stdin.read()
log = Path(sys.argv[1])
log.mkdir(parents=True, exist_ok=True)
doc = json.loads(raw)
(log / f"{doc['turn']:02d}.json").write_text(raw, encoding="utf-8")
print(json.dumps({"answer": "done"}))
"""


def _exec_cmd(*parts: object) -> str:
    argv = [sys.executable, *(str(part) for part in parts)]
    return subprocess.list2cmdline(argv) if os.name == "nt" else " ".join(shlex.quote(part) for part in argv)


def _case() -> Any:
    return case_from_row({
        "id": "read", "query": "Read INC0000001.",
        "expected_dag": {"nodes": [{"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1",
                                    "entity": "incident", "op": "read"}], "edges": []},
        "assertions": [{"type": "tool_called", "node": "read"}]})


def _service(case: Any) -> Any:
    records = [{"fid": "f1", "server": "servicenow", "entity": "incident", "ident": "INC0000001", "state": "new",
                "short_description": "Case 1"}]
    return service_for((case,), records, definitions={"servicenow": load_connector_definition("servicenow")})


def _pack(root: Path, name: str, body: dict[str, Any]) -> Any:
    path = root / "agent" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "agent", "name": name, "body": body}),
                    encoding="utf-8")
    return packkit.resolve(f"agent:{name}", roots=[root])


def test_exec_agent_materialises_the_tree_and_sends_an_index(tmp_path: Path) -> None:
    policy = _pack(tmp_path / "packs", "skilled", _body())
    child = tmp_path / "child.py"
    child.write_text(_RECORDING_CHILD, encoding="utf-8")
    cache = tmp_path / "cache"
    agent = ExecAgent(_exec_cmd(child, tmp_path / "log"), timeout=60, policy=policy, skills_cache=cache)
    case = _case()
    result = run_case(_service(case), case, agent)
    assert result.status == "graded", result.error
    document = json.loads((tmp_path / "log" / "01.json").read_text(encoding="utf-8"))
    block = document["agent"]
    skills_dir = Path(block["skills_dir"])
    assert skills_dir.is_dir() and skills_dir.parent.parent == cache.resolve()
    assert block["skill_index"] == [{"name": "verify", "description": "Use after any write, to confirm it held.",
                                     "path": str(skills_dir / "verify" / "SKILL.md")}]
    for path, text in _FILES.items():
        assert (skills_dir.parent / path).read_text(encoding="utf-8") == text
    # Content-addressed: the same tree is the same directory, written once.
    again = ExecAgent("python child.py", policy=policy, skills_cache=cache)
    assert again.skills_dir == skills_dir
    assert [path.name for path in cache.iterdir()] == [skills_dir.parent.name]
    assert materialise(_FILES, cache) == skills_dir.parent / "skills"


def test_without_files_the_agent_block_is_unchanged(tmp_path: Path) -> None:
    policy = _pack(tmp_path / "packs", "plain", {"system": "Answer.", "skills": {"verify": "Read it back."}})
    child = tmp_path / "child.py"
    child.write_text(_RECORDING_CHILD, encoding="utf-8")
    agent = ExecAgent(_exec_cmd(child, tmp_path / "log"), timeout=60, policy=policy, skills_cache=tmp_path / "cache")
    assert agent.skills_dir is None
    case = _case()
    run_case(_service(case), case, agent)
    raw = (tmp_path / "log" / "01.json").read_bytes()
    block = json.loads(raw)["agent"]
    assert block == {"ref": "agent:plain", "digest": policy.digest, "system": "Answer.", "planning": "",
                     "skills": {"verify": "Read it back."}}
    assert not (tmp_path / "cache").exists()
    # The same run twice sends the same bytes.
    other = ExecAgent(_exec_cmd(child, tmp_path / "again"), timeout=60, policy=policy)
    run_case(_service(case), case, other)
    assert (tmp_path / "again" / "01.json").read_bytes() == raw


def test_the_bundled_adapters_deliver_skills_by_what_each_harness_may_do(tmp_path: Path) -> None:
    from worldloom.studio.harness import skills_preamble

    skills_dir = materialise(_FILES, tmp_path / "cache")
    index = [{"name": "verify", "description": "Use after a write.", "path": str(skills_dir / "verify" / "SKILL.md")}]
    turn = {"schema": "worldloom.evalrun-turn/v2",
            "agent": {"ref": "agent:skilled", "skills_dir": str(skills_dir), "skill_index": index}}
    codex = skills_preamble(turn, "codex")
    assert f"- verify: Use after a write. ({index[0]['path']})" in codex
    assert "Fetch the record you wrote" not in codex and packkit.text("studio.harness.agent_skills.read") in codex
    claude = skills_preamble(turn, "claude")
    assert "Fetch the record you wrote" in claude and packkit.text("studio.harness.agent_skills.inline") in claude
    assert skills_preamble({**turn, "schema": "worldloom.evalrun-plan/v1"}, "claude") == ""
    assert skills_preamble({"schema": "worldloom.evalrun-turn/v2", "agent": {"ref": "agent:x"}}, "claude") == ""
    outside = {**turn, "agent": {**turn["agent"], "skill_index": [{**index[0], "path": str(tmp_path / "SKILL.md")}]}}
    with pytest.raises(ValueError, match=r"not a SKILL\.md under"):
        skills_preamble(outside, "claude")


def test_the_claude_adapter_puts_the_skills_ahead_of_the_role(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from worldloom.studio.harness import invoke

    prompts: list[str] = []

    def run(argv: Any, **kwargs: Any) -> Any:
        prompts.append(kwargs["input"])
        envelope = {"type": "result", "is_error": False, "structured_output": {"answer": "done"}}
        return subprocess.CompletedProcess(argv, 0, json.dumps(envelope), "")

    monkeypatch.setattr(subprocess, "run", run)
    skills_dir = materialise(_FILES, tmp_path / "cache")
    index = [{"name": "verify", "description": "Use after a write.", "path": str(skills_dir / "verify" / "SKILL.md")}]
    invoke("claude", {"schema": "worldloom.evalrun-turn/v2", "query": "q",
                      "agent": {"ref": "agent:skilled", "system": "", "skills_dir": str(skills_dir), "skill_index": index}})
    assert prompts[-1].startswith(packkit.text("studio.harness.agent_skills.open", ref="agent:skilled",
                                               directory=str(skills_dir)))
    assert prompts[-1].index("Fetch the record you wrote") < prompts[-1].index(packkit.text("studio.harness.role.evalrun_turn"))


# -- the CLI --------------------------------------------------------------------------------------------------


def test_pack_tree_from_tree_and_diff(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _pack(root, "skilled", _body())
    out = tmp_path / "tree"
    result = runner.invoke(app, ["pack", "tree", "agent:skilled", "-o", str(out), "--root", str(root)])
    assert result.exit_code == 0, result.output
    assert sorted(p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()) == [POLICY_FILE, *sorted(_FILES)]
    refused = runner.invoke(app, ["pack", "tree", "agent:skilled", "-o", str(out), "--root", str(root)])
    assert refused.exit_code != 0 and "not an empty directory" in " ".join(refused.output.split())

    (out / "skills" / "verify" / "SKILL.md").write_text(_skill("verify", body="Read every write back.\n"), encoding="utf-8")
    into = tmp_path / "into"
    result = runner.invoke(app, ["pack", "from-tree", str(out), "--name", "edited", "--into", str(into)])
    assert result.exit_code == 0, result.output
    edited = packkit.resolve("agent:edited", roots=[into])
    assert edited.body.files["skills/verify/SKILL.md"].endswith("Read every write back.\n")

    diff = runner.invoke(app, ["pack", "diff", "agent:skilled", "agent:edited", "--root", str(root), "--root", str(into)])
    assert diff.exit_code == 0, diff.output
    assert diff.output.startswith("--- a/skills/verify/SKILL.md\n+++ b/skills/verify/SKILL.md\n@@")
    assert "+Read every write back." in diff.output
    assert runner.invoke(app, ["pack", "diff", "agent:baseline", "industry:default"]).exit_code != 0


def test_from_tree_takes_a_bare_skills_directory_and_refuses_what_lint_refuses(tmp_path: Path) -> None:
    skills = tmp_path / ".claude" / "skills"
    (skills / "verify").mkdir(parents=True)
    (skills / "verify" / "SKILL.md").write_text(_skill("verify"), encoding="utf-8")
    result = runner.invoke(app, ["pack", "from-tree", str(skills), "--name", "native", "--into", str(tmp_path / "into")])
    assert result.exit_code == 0, result.output
    native = packkit.resolve("agent:native", roots=[tmp_path / "into"])
    assert native.body.system == packkit.resolve("agent:baseline").body.system
    assert list(native.body.files) == ["skills/verify/SKILL.md"]

    (skills / "verify" / "scripts").mkdir()
    (skills / "verify" / "scripts" / "broken.py").write_text("def (:\n", encoding="utf-8")
    refused = runner.invoke(app, ["pack", "from-tree", str(skills), "--name", "broken", "--into", str(tmp_path / "into")])
    assert refused.exit_code != 0 and "does not parse as Python" in " ".join(refused.output.split())
    (tmp_path / "loose").mkdir()
    (tmp_path / "loose" / POLICY_FILE).write_text('{"system": "x"}', encoding="utf-8")
    (tmp_path / "loose" / "run.py").write_text("print(1)\n", encoding="utf-8")
    outside = runner.invoke(app, ["pack", "from-tree", str(tmp_path / "loose"), "--name", "loose"])
    assert outside.exit_code != 0 and "policy.json and skills/ only" in " ".join(outside.output.split())
