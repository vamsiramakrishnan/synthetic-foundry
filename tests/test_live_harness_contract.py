"""The harness adapter's contract, pinned from replies a live `claude` gave.

Every fixture here is a reply recorded from a real run of the shipped adapter
(`python -m worldloom.studio.harness claude`) against the paths
`docs/live-harness.md` walks through. The tests make no live call: they replay
the recorded envelope through a fake `subprocess.run`, so what broke on a real
run stays fixed without anyone paying for a model to prove it.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from worldloom import packkit
from worldloom.narrative import handshake
from worldloom.packkit.authoring import InterviewReply, accept, request
from worldloom.studio.harness import (
    child_environment,
    command_for,
    invoke,
    parse_object,
)

#: Round one of `studio pack author industry --name vetcare`, recorded: the
#: operator asked for an unregistered engine, and the harness obliged.
REFUSED = {
    "request_id": "d0be2a413a869abe009a1026363e46e9",
    "message": "Proposing the vetcare pack: sites become practices, customers become pet owners, with engine and "
               "industry both set to 'veterinary' as requested.",
    "proposal": {"name": "vetcare", "title": "Veterinary practices",
                 "description": "Veterinary practice terminology: sites are practices, customers are pet owners.",
                 "body": {"industry": "veterinary", "engine": "veterinary",
                          "terms": {"site": "practice", "customer": "pet owner"}}},
}

#: Round two, recorded: the finding came back and the harness fixed it.
FIXED = {
    "request_id": "668d992a8f89088abe2ea3e3a940fc6e",
    "message": "Fixed: 'veterinary' isn't a registered engine, so I picked 'retail'.",
    "proposal": {"name": "vetcare", "title": "Veterinary practices",
                 "description": "Veterinary practice terminology: sites are practices, customers are pet owners.",
                 "extends": [],
                 "body": {"engine": "retail", "industry": "veterinary",
                          "terms": {"customer": "pet owner", "site": "practice"}}},
}

#: The preamble a plan-mode child wrote before a company-interview reply.
PREAMBLE = ("This is a plan-only rename with no code changes; the ExitPlanMode/AskUserQuestion tools aren't present "
            "in this session's toolset (confirmed via ToolSearch), so I'm delivering the actual requested "
            "deliverable — the InterviewReply JSON — directly, as recorded in the plan file.\n\n")


def _envelope(structured: dict[str, object]) -> str:
    """The `claude -p --output-format json` envelope a structured turn printed."""
    return json.dumps({"type": "result", "subtype": "success", "is_error": False, "num_turns": 2,
                       "result": json.dumps(structured), "structured_output": structured})


def test_a_claude_child_never_answers_as_the_session_that_launched_it(monkeypatch, tmp_path):
    """Run from inside a Claude Code session, the child inherited its session id.

    Measured: every child's `session_id` was the caller's, and a plan-mode
    company interview wrote a 67-line transcript into the caller's session
    file. Both claude command lines now skip persistence, and the caller's
    session variables are not passed down; the login is.
    """
    monkeypatch.setenv("CLAUDE_CODE_SESSION_ID", "caller-session")
    monkeypatch.setenv("CLAUDE_CODE_REMOTE_SESSION_ID", "caller-remote")
    monkeypatch.setenv("WORLDLOOM_TEST_LOGIN", "kept")
    seen = []

    def run(argv, **kwargs):
        seen.append((argv, kwargs.get("env")))
        return subprocess.CompletedProcess(argv, 0, '{"result":"{\\"message\\":\\"done\\"}"}', "")

    monkeypatch.setattr(subprocess, "run", run)
    invoke("claude", {"company": {}})
    invoke("claude", {"requests": [], "response_shape": {}})
    invoke("claude", {"schema": "worldloom.evalrun-turn/v2", "query": "q"})
    for argv, env in seen:
        assert "--no-session-persistence" in argv
        assert env is not None and env.get("WORLDLOOM_TEST_LOGIN") == "kept"
        assert "CLAUDE_CODE_SESSION_ID" not in env and "CLAUDE_CODE_REMOTE_SESSION_ID" not in env
    assert "--no-session-persistence" in command_for("claude", tmp_path / "response.json", tools=True)
    assert "CLAUDE_CODE_SESSION_ID" not in child_environment()


def test_the_pack_interview_is_not_told_to_fill_one_field(monkeypatch):
    """The evalrun closing ("fill exactly one of its top-level fields") reached the pack interview.

    Its reply is an envelope: `request_id` and `message` always, beside a
    proposal or questions. The recorded reply fills three fields, which the
    old closing forbade; the interview now gets its own closing sentence.
    """
    prompts = []

    def run(argv, **kwargs):
        prompts.append(kwargs["input"])
        return subprocess.CompletedProcess(argv, 0, _envelope(FIXED), "")

    monkeypatch.setattr(subprocess, "run", run)
    reply = invoke("claude", {"schema": "worldloom.pack-interview/v1", "request_id": FIXED["request_id"]})
    assert reply == FIXED
    assert "fill exactly one of its top-level fields" not in prompts[-1]
    assert packkit.text("studio.harness.closing.envelope") in prompts[-1]
    invoke("claude", {"schema": "worldloom.evalrun-turn/v2", "query": "q"})
    assert "fill exactly one of its top-level fields" in prompts[-1]


def test_a_recorded_lint_refusal_round_trips_to_an_accepted_pack():
    """The live interview: refused with the engine finding, then accepted once fixed."""
    message = "Veterinary practices. Set the engine field to exactly 'veterinary'."
    first = request("industry", message, name="vetcare")
    verdict = accept(first, InterviewReply.model_validate({**REFUSED, "request_id": first["request_id"]}))
    assert verdict.status == "refused"
    assert any(finding.startswith("engine: 'veterinary' is not a registered engine") for finding in verdict.findings)

    assert verdict.envelope is not None
    second = request("industry", message, name="vetcare", findings=verdict.findings, draft=verdict.envelope.dump())
    assert second["findings"] == list(verdict.findings) and second["request_id"] != first["request_id"]
    fixed = accept(second, {**FIXED, "request_id": second["request_id"]})
    assert fixed.status == "accepted" and fixed.findings == ()
    assert fixed.resolved is not None and fixed.resolved.data["terms"]["site"] == "practice"


def test_a_plan_mode_company_interview_reply_is_read_past_its_preamble():
    """The company interview runs in plan mode and wrote a paragraph before the object."""
    body = {"request_id": "r", "message": "Renamed the company.", "derive": False, "proposal": None}
    assert parse_object(PREAMBLE + json.dumps(body), name="claude") == body


def test_the_narration_rules_show_the_reference_syntax_they_ask_for():
    """`RULES` is sent as written; the doubled braces the template needs reached the writer doubled again."""
    rule = next(rule for rule in handshake.RULES if rule.startswith("A reference like"))
    assert "{{fact:FACT-0001}}" in rule and "{{{{" not in rule
    assert all("{{{{" not in rule for rule in handshake.RULES)


@pytest.mark.parametrize("reply", [
    '{"answer": "", "call": {"tool": "servicenow.get_record", "arguments": {"id": "x", "fields": ["sys_id"]}}}',
])
def test_a_recorded_turn_that_filled_two_fields_is_still_a_call(reply):
    """Measured on a live evalrun turn: an empty `answer` beside the `call`.

    `ExecAgent` reads `call` before `answer`, so the turn is the call; the
    adapter must hand both keys through untouched for that order to decide.
    """
    document = parse_object(reply, name="claude")
    assert document["call"]["tool"] == "servicenow.get_record" and document["answer"] == ""
