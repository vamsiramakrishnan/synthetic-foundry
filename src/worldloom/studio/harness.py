"""Adapters to installed coding harnesses, using their existing login/settings.

No model API, key store or approval bypass belongs here. The proposing harness
receives a bounded task and returns JSON through the ordinary acceptance seam.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shlex
import subprocess
import sys
from collections.abc import Mapping
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

#: The harness names this module adapts. A third is a custom JSON adapter.
NAMES: tuple[str, ...] = ("codex", "claude")

#: Turns re-asked when a reply is not one JSON object, before the turn is an error.
RETRIES = 1

_STRINGS = {"type": "array", "items": {"type": "string"}}
_FREE = {"type": "object", "additionalProperties": True}

#: The structured-output schema per evalrun seam. A schema that admitted any
#: object let the harness serialise the nested call as a string ("call":
#: "{\"tool\": ...}"), so each seam states the shape its reader parses:
#: `ExecAgent` for a turn, `parse_plan` for a plan, `exec_rater` for a rating.
_REPLY_SCHEMAS: dict[str, dict[str, Any]] = {
    # The API refuses `oneOf` at the top level, so the three reply shapes
    # share one object with every key optional; `_unwrapped` reads a reply
    # the harness wrote as a string inside one of them.
    "worldloom.evalrun-turn/v2": {
        "type": "object",
        "properties": {
            "call": {"type": "object", "properties": {"tool": {"type": "string"}, "arguments": _FREE},
                     "required": ["tool", "arguments"], "additionalProperties": False},
            "ask": {"type": "object", "properties": {"question": {"type": "string"}, "about": _STRINGS},
                    "required": ["question"], "additionalProperties": False},
            "answer": {"type": "string"},
            "artifacts": {"type": "array", "items": {
                "type": "object", "properties": {"name": {"type": "string"}, "text": {"type": "string"}, "cites": _STRINGS},
                "required": ["name", "text"], "additionalProperties": False}},
        },
        "additionalProperties": False,
    },
    "worldloom.evalrun-plan/v1": {
        "type": "object",
        "properties": {"plan": {"type": "object", "properties": {"nodes": {"type": "array", "items": {
            "type": "object",
            "properties": {"id": {"type": "string"}, "tool": {"type": "string"}, "depends_on": _STRINGS},
            "required": ["tool"], "additionalProperties": False}}}, "required": ["nodes"], "additionalProperties": False}},
        "required": ["plan"], "additionalProperties": False,
    },
    "worldloom.evalrun-rating/v1": {
        "type": "object",
        "properties": {"score": {"type": "number"}, "rationale": {"type": "string"}},
        "required": ["score"], "additionalProperties": False,
    },
    # `packkit.accept` validates the body against the kind's own model after
    # its `extends` chain is merged, so the structured output only fixes the
    # envelope; a body schema per kind would refuse a layered pack that
    # states two fields of a model that requires ten.
    "worldloom.pack-interview/v1": {
        "type": "object",
        "properties": {
            "request_id": {"type": "string"},
            "message": {"type": "string"},
            "questions": {**_STRINGS, "maxItems": 5},
            # `body` or, for a kind with a tree codec, `diff` against the
            # request's `draft_tree`; `packkit.accept` refuses a proposal
            # with neither, or both, as a finding.
            "proposal": {"type": "object", "properties": {
                "name": {"type": "string"}, "title": {"type": "string"}, "description": {"type": "string"},
                "extends": _STRINGS, "body": _FREE, "diff": {"type": "string"}},
                "required": ["name"], "additionalProperties": False},
        },
        "required": ["request_id", "message"], "additionalProperties": False,
    },
}


def reply_schema(payload: Mapping[str, Any]) -> str | None:
    """The structured-output schema for the seam this document belongs to, as JSON."""
    schema = payload.get("schema")
    if isinstance(schema, str) and schema in _REPLY_SCHEMAS:
        return json.dumps(_REPLY_SCHEMAS[schema], sort_keys=True)
    return None

#: What the child is being asked to be, keyed by the document it is handed:
#: the prompt key (``prompts/default/studio.json``) of each seam's role.
#: Every one of these seams ends in "return exactly one JSON object", so the
#: wrapper's job is to say which role the object plays. Without this the
#: authoring prose below reached an evalrun turn and told the agent under
#: test it was completing an authoring request. A seam named here runs with
#: no tools and a structured reply (`_REPLY_SCHEMAS`).
_ROLES: dict[str, str] = {
    "worldloom.evalrun-turn/v2": "studio.harness.role.evalrun_turn",
    "worldloom.evalrun-plan/v1": "studio.harness.role.evalrun_plan",
    "worldloom.evalrun-rating/v1": "studio.harness.role.evalrun_rating",
    "worldloom.pack-interview/v1": "studio.harness.role.pack_interview",
}

#: The closing sentence for a structured seam whose reply is not one of
#: several alternatives. The evalrun closing says "fill exactly one of its
#: top-level fields", which a pack interview cannot obey: its reply is an
#: envelope that always carries `request_id` and `message` beside the
#: proposal or the questions.
_CLOSINGS: dict[str, str] = {
    "worldloom.pack-interview/v1": "studio.harness.closing.envelope",
}

#: Every role ends in this sentence, which `invoke` swaps for the write
#: instruction when an operator has opted a native trial into workspace
#: writes. A role that omits it would silently lose that opt-in.
_NO_WRITES = "Do not modify project files."


def role_for(payload: dict[str, Any]) -> str:
    """What the child is being asked to be, from the document it is handed.

    A narration request carries no `schema`; it is recognised by the request
    list and response shape `narrate requests` writes.
    """
    from .. import packkit

    schema = payload.get("schema")
    if isinstance(schema, str) and schema in _ROLES:
        return packkit.text(_ROLES[schema])
    if "requests" in payload and "response_shape" in payload:
        return packkit.text("studio.harness.narration")
    return packkit.text("studio.harness.authoring")


#: The prompt texts that open and close a policy's own text in a prompt.
_MARKER_KEYS = ("studio.harness.agent_policy.open", "studio.harness.agent_policy.close",
                "studio.harness.agent_skills.open", "studio.harness.agent_skills.close")
#: The tag of the nonce-bearing lines around a policy's text.
MARKER_TAG = "worldloom-policy"


def marker_phrases() -> tuple[str, ...]:
    """The fixed text that delimits a policy in a prompt, which the policy's own text may not contain.

    The delimiters around a policy are prose from the prompts pack, which
    anyone can read, so a policy could write "End of the standing
    instruction." and go on as if it were the harness. The real boundary is
    the nonce-bearing line (`fence`), which a policy cannot know in advance;
    the lint refuses the fixed phrases and the tag so a forged boundary
    never reaches a prompt at all.
    """
    from .. import packkit

    phrases = [packkit.text(key, ref="\x00", directory="\x00").split("\x00")[0].strip() for key in _MARKER_KEYS]
    return tuple(dict.fromkeys(phrase for phrase in (*phrases, MARKER_TAG) if phrase))


def fence_nonce(payload: Mapping[str, Any]) -> str:
    """The nonce on one prompt's delimiters: a digest of the policy block it fences.

    Deterministic, so the same case under the same policy is the same prompt
    and a champion and a candidate are measured without prompt noise. It
    cannot be forged either: the lint refuses the marker tag in any policy
    text, and a policy that tried to predict its own digest would change it.
    """
    block = payload.get("agent")
    canonical = json.dumps(block if isinstance(block, Mapping) else {}, sort_keys=True, default=str)
    return hashlib.sha256(f"fence\0{canonical}".encode()).hexdigest()[:16]


def _fenced(opening: str, text: str, closing: str, nonce: str) -> str:
    return f"{opening}[{MARKER_TAG} {nonce}]\n{text}[/{MARKER_TAG} {nonce}]\n{closing}"


#: The seams whose document can carry a policy the child runs under.
_POLICY_SEAMS = frozenset({"worldloom.evalrun-turn/v2", "worldloom.evalrun-plan/v1"})
#: The seams whose document can carry a policy's skills.
_SKILL_SEAMS = frozenset({"worldloom.evalrun-turn/v2"})
_INTERVIEW = "worldloom.pack-interview/v1"


def _proposes_under_policy(payload: Mapping[str, Any]) -> bool:
    """Whether a pack interview names the proposer policy its harness runs under.

    ``packkit.authoring`` writes that policy as an ``agent`` block with a
    ``ref`` and a ``digest``; an interview without one (every interview a
    caller did not give a proposer policy) is rendered exactly as before.
    """
    block = payload.get("agent")
    return (payload.get("schema") == _INTERVIEW and isinstance(block, Mapping)
            and isinstance(block.get("ref"), str) and isinstance(block.get("digest"), str))


def standing_instruction(payload: Mapping[str, Any], nonce: str | None = None) -> str:
    """The agent policy's `system` text, delimited, for the front of the prompt; empty without one.

    An evalrun document run under an `agent` pack carries the policy in its
    `agent` block. A harness reading only the JSON would see the standing
    instruction as one field among many, so it goes ahead of the role, where
    a harness takes its instructions, between markers naming the policy and
    lines carrying *nonce* (a digest of the policy block unless given), which the
    policy's text cannot forge.
    The evalrun seams carry it, and so does a pack interview whose proposer
    runs under a policy (``packkit.authoring.request(..., proposer=...)``):
    the improver is then as much a policy as the agent it improves. A
    narration request, or an interview without a proposer policy, gets
    nothing here.
    """
    from .. import packkit

    block = payload.get("agent")
    if payload.get("schema") not in _POLICY_SEAMS and not _proposes_under_policy(payload):
        return ""
    if not isinstance(block, Mapping) or not isinstance(block.get("system"), str) or not block["system"].strip():
        return ""
    return _fenced(packkit.text("studio.harness.agent_policy.open", ref=str(block.get("ref") or "agent")),
                   block["system"].strip() + "\n", packkit.text("studio.harness.agent_policy.close"),
                   nonce or fence_nonce(payload))


def skills_preamble(payload: Mapping[str, Any], name: str, nonce: str | None = None) -> str:
    """The agent policy's skills, for the front of an evalrun turn's prompt; empty without them.

    An `agent` pack with a skill tree reaches the turn document as
    `agent.skills_dir` (the tree, materialised) and `agent.skill_index`
    (each skill's name, description and SKILL.md path). The index goes ahead
    of the role so the child knows what it can open. How the bodies arrive
    depends on what the harness may do on this seam:

    - `codex` runs in its read-only sandbox, which can read files, so it gets
      the index and the directory and opens a SKILL.md only when its
      description fits the step (progressive disclosure);
    - `claude` runs the evalrun seams with no tools at all (`--tools ""`), so
      it could neither invoke a skill natively nor read one from disk. Giving
      it file or skill tools would also let it read the cases' expected
      answers, so instead each SKILL.md is inlined after the index. Its
      references and scripts stay on disk, named by path.

    A pack interview whose proposer runs under a policy with a skill tree
    gets the same preamble; the interview seam gives each harness the same
    tools an evalrun turn does.
    """
    from .. import packkit

    block = payload.get("agent")
    if (payload.get("schema") not in _SKILL_SEAMS and not _proposes_under_policy(payload)) or not isinstance(block, Mapping):
        return ""
    index = block.get("skill_index")
    directory = block.get("skills_dir")
    if not isinstance(index, list) or not index or not isinstance(directory, str):
        return ""
    root = Path(directory).resolve()
    lines = [f"- {entry.get('name')}: {entry.get('description')} ({entry.get('path')})\n" for entry in index
              if isinstance(entry, Mapping)]
    if name == "claude":
        lines.append(packkit.text("studio.harness.agent_skills.inline"))
        cap = int(packkit.policy("evalrun.agent_pack.max_file_bytes"))
        for entry in index:
            path = Path(str(entry.get("path") if isinstance(entry, Mapping) else "")).resolve()
            if path.parent.parent != root or path.name != "SKILL.md" or not path.is_file():
                raise ValueError(f"the skill index names {path}, which is not a SKILL.md under {root}")
            if path.stat().st_size > cap:
                raise ValueError(f"{path} exceeds the policy `evalrun.agent_pack.max_file_bytes` ({cap})")
            lines.append(f"\n## {path.parent.name}\n\n{path.read_text(encoding='utf-8').strip()}\n")
    else:
        lines.append(packkit.text("studio.harness.agent_skills.read"))
    return _fenced(packkit.text("studio.harness.agent_skills.open", ref=str(block.get("ref") or "agent"),
                                directory=directory),
                   "".join(lines), packkit.text("studio.harness.agent_skills.close"), nonce or fence_nonce(payload))


def adapter_command(name: str, *, timeout: float = 590, allow_native_writes: bool = False) -> str:
    """This module as an `--exec` child, ready to pass wherever one is taken.

    One spelling for `studio serve --harness`, `evalrun run --harness` and
    `narrate loop --harness`, so an installed `codex` or `claude` login drives
    any of them without an adapter script.
    """
    if name not in NAMES:
        raise ValueError(f"choose {' or '.join(NAMES)}, or configure a custom JSON adapter")
    if allow_native_writes and name != "codex":
        raise ValueError("native output writes require codex or a custom JSON adapter")
    args = [
        sys.executable, "-m", "worldloom.studio.harness", name,
        "--timeout", str(timeout),
        *(["--allow-native-writes"] if allow_native_writes else []),
    ]
    # The seam runs the command without a shell, so it is split back by the
    # platform's own rules; a Windows path with a space must quote that way.
    return subprocess.list2cmdline(args) if os.name == "nt" else shlex.join(args)


def command_for(name: str, output: Path, *, native_output: Path | None = None, tools: bool = True,
                schema: str | None = None, workdir: Path | None = None) -> list[str]:
    """The child process for one turn.

    `tools=False` is the evalrun seams: the agent under test, the planner and
    the judge answer from the document on stdin and touch nothing local, so
    the child gets no tools at all. Plan mode was the earlier way to keep it
    off the files, and it cost the run: after sixteen turns of reads the
    child answered in prose that plan mode restricted it to read-only actions
    and required a tool it did not have. The authoring and narration seams
    may read the project, so they keep plan mode.

    *workdir* is the empty directory an isolated seam runs from; codex is
    pointed at it with the same `--cd` a native write uses for its output
    directory, since codex takes its workspace root from that flag.
    """
    if name == "codex":
        root = native_output or workdir
        return ["codex", "exec", "--sandbox", "workspace-write" if native_output else "read-only",
                *(["--cd", str(root)] if root else []), "--skip-git-repo-check",
                "--output-last-message", str(output), "-"]
    if native_output is not None:
        raise ValueError("native output writes require codex or a custom JSON adapter")
    if name == "claude":
        if tools:
            # No persisted session on this path either: a turn is one bounded
            # task, and a run from inside a Claude Code session wrote the
            # child's transcript under the caller's own session id.
            return ["claude", "-p", "--output-format", "json", "--permission-mode", "plan",
                    "--no-session-persistence"]
        # No built-in tools, no MCP servers from the operator's own settings
        # (a real run made "errant tool calls" through them), no persisted
        # session, and a structured reply in the seam's own shape, so the
        # harness cannot answer with prose or a body cut off mid-string.
        return ["claude", "-p", "--output-format", "json", "--tools", "", "--strict-mcp-config",
                "--no-session-persistence", *(["--json-schema", schema] if schema else [])]
    raise ValueError("choose codex or claude, or configure a custom JSON adapter")


#: Variables naming the session that launched Worldloom. A harness run from
#: inside a Claude Code session inherits them, and the child then answered as
#: that session: its `session_id` was the caller's, and in plan mode it wrote
#: its transcript into the caller's session file. The child is its own turn.
_CALLER_SESSION = ("CLAUDE_CODE_SESSION_ID", "CLAUDE_CODE_REMOTE_SESSION_ID")


def child_environment() -> dict[str, str]:
    """This process's environment without the caller's session identity; login and settings stay."""
    return {key: value for key, value in os.environ.items() if key not in _CALLER_SESSION}


def invoke(name: str, payload: dict[str, Any], *, timeout: float = 590,
           allow_native_writes: bool = False) -> dict[str, Any]:
    if allow_native_writes and name != "codex":
        raise ValueError("native output writes require codex or a custom JSON adapter")
    native_output = None
    if (allow_native_writes and payload.get("schema") == "worldloom.native-trial/v1"
            and payload.get("task", {}).get("operation") in {"update", "create"}):
        native_output = Path(payload.get("output_directory", ""))
        if (not native_output.is_absolute() or not native_output.is_dir()
                or any(path.is_symlink() for path in (native_output, *native_output.parents))):
            raise ValueError("native output writes require an existing absolute directory without symlinks")
    from .. import packkit

    role = role_for(payload)
    if native_output is not None:
        if _NO_WRITES not in role:
            raise ValueError("this seam has no write instruction to grant; native writes are an authoring opt-in")
        role = role.replace(_NO_WRITES, packkit.text("studio.harness.native_writes"))
    command_tools = payload.get("schema") not in _ROLES
    structured = None if command_tools else reply_schema(payload)
    closing = packkit.text(_CLOSINGS.get(str(payload.get("schema")), "studio.harness.closing.structured")
                           if structured else "studio.harness.closing.object")
    nonce = fence_nonce(payload)
    prompt = (standing_instruction(payload, nonce) + skills_preamble(payload, name, nonce) + role + closing + "\n\n"
              + json.dumps(payload, sort_keys=True, ensure_ascii=False, allow_nan=False))
    with TemporaryDirectory(prefix="worldloom-harness-") as temp:
        output = Path(temp) / "response.json"
        # Every seam with a role of its own (the evalrun turn, plan and
        # rating, and the pack interview) runs from a fresh empty directory,
        # for either harness. A child started in the repository loads its
        # project instructions and skills (it answered a turn "in the
        # Worldloom project"), and one started where the operator works can
        # read what is there: the held-out cases, the loop's runs. The
        # materialised skills stay readable by their absolute path. This is
        # a working directory, not a jail: a child with shell access can
        # still read an absolute path it is told or guesses; the improve
        # loop's output directory is simply never the child's directory.
        workdir = Path(temp) / "work" if not command_tools else None
        if workdir is not None:
            workdir.mkdir()
        asked = prompt
        for attempt in range(RETRIES + 1):
            try:
                command = command_for(name, output, native_output=native_output, tools=command_tools,
                                      schema=structured, workdir=workdir)
                result = subprocess.run(command, input=asked, text=True, cwd=workdir, env=child_environment(),
                                        capture_output=True, timeout=timeout, shell=False)
            except subprocess.TimeoutExpired as error:
                raise ValueError("coding harness exceeded its configured timeout") from error
            if result.returncode:
                raise ValueError(f"{name} exited {result.returncode}; check its local installation and login")
            envelope: dict[str, Any] | None = None
            if name == "codex":
                raw = output.read_text(encoding="utf-8")
            else:
                envelope = json.loads(result.stdout)
                if envelope.get("is_error"):
                    raise ValueError("Claude Code reported a failed authoring turn")
                value = envelope.get("structured_output", envelope.get("result"))
                raw = value if isinstance(value, str) else json.dumps(value)
            if len(raw) > 4_000_000:
                raise ValueError("coding harness response exceeds 4 MB")
            try:
                return parse_object(raw, name=name, envelope=envelope)
            except ValueError as error:
                if attempt == RETRIES:
                    raise
                # One more turn, with the refusal in front of the document.
                # A reply cut off inside a long body, or wrapped in prose,
                # is the harness stumbling on the shape, not on the task;
                # a second refusal is the harness's answer and stands.
                asked = packkit.text("studio.harness.retry", error=error) + prompt
        raise AssertionError("unreachable")


def parse_object(raw: str, *, name: str, envelope: dict[str, Any] | None = None) -> dict[str, Any]:
    """The one JSON object a harness turn must return, salvaged from what it said.

    The instruction asks for exactly one object without a fence. A model that
    complied except for a fence, or that wrote a sentence before the object,
    is still answering the turn; the object is taken from the first `{` to
    the matching `}`. An empty reply is refused with the envelope's own
    account of why the turn ended, because the earlier `Expecting value:
    line 1 column 1` said nothing anyone could act on.
    """
    text = raw.strip()
    if not text:
        detail = ""
        if envelope:
            detail = " (" + ", ".join(f"{key}={envelope[key]!r}" for key in ("subtype", "stop_reason", "num_turns") if key in envelope) + ")"
        raise ValueError(f"{name} returned no text for the turn{detail}")
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        end = text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(f"{name} returned no JSON object; it said: {text[:200]!r}") from None
        try:
            value = json.loads(text[start:end + 1])
        except json.JSONDecodeError as error:
            raise ValueError(f"{name} returned malformed JSON ({error.msg} at {error.pos}); it said: {text[:200]!r}") from None
    if not isinstance(value, dict):
        raise ValueError("coding harness must return a JSON object")
    return _unwrapped(value)


_REPLY_KEYS = ("call", "ask", "answer", "plan")


def _unwrapped(value: dict[str, Any]) -> dict[str, Any]:
    """A reply the harness serialised one level down, read as the object it meant.

    Under structured output a harness wrote `{"call": "{\"tool\": ...}"}` and
    then `{"answer": "{\"call\": {...}}"}`: the object it meant, as a string
    inside one of the reply keys. A string that parses to an object carrying a
    reply key is that object.
    """
    for key in _REPLY_KEYS:
        held = value.get(key)
        if isinstance(held, str) and held.lstrip().startswith("{"):
            try:
                inner = json.loads(held)
            except json.JSONDecodeError:
                continue
            if isinstance(inner, dict):
                if key == "answer" and any(reply in inner for reply in _REPLY_KEYS):
                    return _unwrapped(inner)
                if key != "answer":
                    return {**value, key: inner}
    return value


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("harness", choices=("codex", "claude"))
    parser.add_argument("--timeout", type=float, default=590)
    parser.add_argument("--allow-native-writes", action="store_true",
                        help="Opt in to Codex workspace writes for native update/create output directories.")
    args = parser.parse_args()
    payload = json.loads(sys.stdin.read(4_000_001))
    if not isinstance(payload, dict):
        raise ValueError("authoring request must be a JSON object")
    print(json.dumps(invoke(args.harness, payload, timeout=args.timeout, allow_native_writes=args.allow_native_writes), sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
