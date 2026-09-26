"""How another harness drives a run: the turn protocol, and the request/response files.

Worldloom never imports a model SDK. Its one integration contract is the
``--exec`` seam (``execseam``): a child process receives one JSON document on
stdin and prints one on stdout. ``narrate loop`` and ``benchmark run`` are
built on it; ``evalrun run --exec`` is the third command, and the first
where the child is *interactive*: an agent has to see a tool's result before
it can decide the next call, so one exchange per case is not enough.

``ExecAgent`` runs the child once per **turn**. Each turn the child receives
the request, the tools it may call, and the transcript so far (every call it
made and what came back), and answers with exactly one of two documents:
``{"call": {"tool": ..., "arguments": {...}}}`` to make a call, or
``{"answer": ..., "artifacts": [...]}`` to finish. The child is stateless
between turns by design -- the transcript *is* its state -- which is what
lets any harness that can run a subprocess be the agent under test, with no
long-lived process, socket, or SDK. A child that exits non-zero, prints
something that is not the asked-for document, or overruns the timeout ends
the case as an error row carrying its stderr tail, per the seam's rule that a
dead subprocess leaves exactly one artifact behind.

``requests_document`` and ``load_responses`` are the file form of the same
contract, on the pattern of ``narrate requests`` / ``narrate accept``: a
harness that cannot be called back reads the cases and their tool catalogs,
writes the trajectory it would take, and ``evalrun run --agent
scripted:responses.json`` replays it. Replay cannot observe results, so it
suits fixed trajectories (a regression set, a hand-authored baseline) rather
than an agent that must find a record id before it can act on it; the
document says so in its instructions rather than leaving the harness to
discover it from a `not_found`.

**An agent policy.** ``ExecAgent(..., policy=<agent pack>)`` runs the child
under an ``agent`` pack (``evalrun.policy``). The turn document keeps its
``worldloom.evalrun-turn/v2`` schema and every field above, and gains:

- ``agent``: ``{ref, digest, system, planning, skills}``, the policy's
  identity and its standing instruction, planning note and named procedures;
- ``instructions``: the shipped ``evalrun.turn.rule.*`` overlaid by the
  policy's ``turn_rules`` (the rule stating the reply shapes is locked);
- ``tools[*].description`` and ``tools[*].hints`` on each tool the policy
  advises.

Without a policy the document is byte-identical to what it was before
policies existed. The agent's ``name`` carries the policy
(``exec:python+agent:careful@<digest[:12]>``), and ``pack_record`` is what a
run writes to ``run.json`` as ``agent_pack``.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .. import packkit
from ..connector_emulator import ConnectorError
from ..connectors.serving import ConnectorEvaluationService, ServingError
from ..execseam import DEFAULT_TIMEOUT, ExecError, run_exec
from .agents import AgentResponse, AgentTask, ProducedArtifact, ToolCall, ToolSurface
from .contract import EvalCase

if TYPE_CHECKING:
    from ..packkit import ResolvedPack

TURN_SCHEMA = "worldloom.evalrun-turn/v2"
REQUESTS_SCHEMA = "worldloom.evalrun-requests/v1"
RESPONSES_SCHEMA = "worldloom.evalrun-responses/v1"

def turn_instructions() -> list[str]:
    """What each turn tells the child, from the prompts in force (``evalrun.turn.rule.*``)."""
    return packkit.texts("evalrun.turn.rule.")


def response_instructions() -> list[str]:
    """What a requests document tells an offline harness (``evalrun.response.rule.*``)."""
    return packkit.texts("evalrun.response.rule.")


def default_max_turns() -> int:
    """Turns a child may take per case when the case's own call budget is larger.

    A turn is a subprocess; a thousand of them per case is a thousand
    interpreter start-ups, and an agent that needs that many calls is not
    being measured, it is looping. The number is the policy
    ``evalrun.max_turns``.
    """
    return int(packkit.policy("evalrun.max_turns"))


def _catalog(service: ConnectorEvaluationService, principal: str, run_id: str) -> list[dict[str, Any]]:
    return [dict(tool) for tool in service.tool_catalog(principal, run_id)]


class ExecAgent:
    """The child process as the agent, one subprocess per turn."""

    def __init__(self, command: str, *, timeout: float = DEFAULT_TIMEOUT, shell: bool = False,
                 max_turns: int | None = None, name: str | None = None,
                 policy: ResolvedPack | None = None) -> None:
        from .policy import agent_name, pack_record, require

        if policy is not None:
            policy = require(policy)
        if max_turns is None and policy is not None:
            max_turns = policy.body.max_turns
        if max_turns is None:
            max_turns = default_max_turns()
        if max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        self.command = command
        self.timeout = timeout
        self.shell = shell
        self.max_turns = max_turns
        self.policy = policy
        #: What a run records as ``agent_pack``; ``None`` without a policy.
        self.pack_record = pack_record(policy) if policy is not None else None
        self.name = name or agent_name(f"exec:{command.split()[0] if command.split() else command}", policy)

    def _unadvisable(self, tools: ToolSurface, catalog: list[dict[str, Any]]) -> tuple[str, ...]:
        """Tools the policy advises that nothing serves: a finding about the policy, not a failure of the run.

        Checked against every tool the service serves, not only this case's
        catalog (which holds just the query's connectors), so advice for a
        connector this case does not use is not reported as unknown.
        """
        assert self.policy is not None
        served = getattr(getattr(tools, "_service", None), "tools", None)
        known = set(served) if isinstance(served, Mapping) else {str(tool.get("name")) for tool in catalog}
        return tuple(sorted(key for key in self.policy.body.tools if key not in known))

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        transcript: list[dict[str, Any]] = []
        catalog = [dict(tool) for tool in tools.tools()]
        extra: dict[str, Any] = {}
        findings: tuple[str, ...] = ()
        rules: list[str] | None = None
        if self.policy is not None:
            from .policy import advise, agent_block, turn_rules

            rules = turn_rules(self.policy.body)
            extra = {"agent": agent_block(self.policy)}
            unknown = self._unadvisable(tools, catalog)
            catalog = advise(catalog, self.policy.body)
            if unknown:
                # Once per case, not per turn: the note is about the policy.
                findings = (f"agent policy {self.policy.ref} advises tools no connector serves: {', '.join(unknown)}",)
        for turn in range(1, self.max_turns + 1):
            payload = {
                "schema": TURN_SCHEMA, "case_id": task.case_id, "query": task.query, "persona": task.persona,
                "principal": task.principal, "turn": turn, "turns_left": self.max_turns - turn,
                "tools": catalog, "transcript": transcript,
                "instructions": turn_instructions() if rules is None else list(rules), **extra,
            }
            try:
                reply = run_exec(self.command, payload, timeout=self.timeout, shell=self.shell)
            except ExecError as error:
                tail = getattr(error, "stderr_tail", "")
                raise RuntimeError(f"{error.code}: {error}" + (f"\n{tail}" if tail else "")) from error
            document = reply.document
            if "call" in document:
                call = document["call"]
                if not isinstance(call, Mapping) or not isinstance(call.get("tool"), str):
                    raise RuntimeError(f"exec_unparseable: turn {turn} `call` must be {{tool, arguments}}")
                arguments = call.get("arguments") or {}
                if not isinstance(arguments, Mapping):
                    raise RuntimeError(f"exec_unparseable: turn {turn} `arguments` must be an object")
                entry: dict[str, Any] = {"tool": call["tool"], "arguments": dict(arguments)}
                try:
                    entry["result"] = tools.call(call["tool"], **dict(arguments))
                except ConnectorError as failure:
                    entry["error"] = {"code": failure.code, "kind": failure.kind, "message": failure.message}
                except ServingError as failure:
                    entry["error"] = {"code": 400, "kind": "serving", "message": str(failure)}
                transcript.append(entry)
                continue
            if "ask" in document:
                asked = document["ask"]
                if not isinstance(asked, Mapping) or not isinstance(asked.get("question"), str):
                    raise RuntimeError(f"exec_unparseable: turn {turn} `ask` must be {{question, about}}")
                about = asked.get("about") or ()
                if not isinstance(about, (list, tuple)):
                    raise RuntimeError(f"exec_unparseable: turn {turn} `about` must be a list")
                try:
                    said = tools.ask(asked["question"], about=tuple(str(value) for value in about))
                except ServingError as failure:
                    transcript.append({"ask": asked["question"], "error": {"code": 400, "kind": "serving", "message": str(failure)}})
                    continue
                transcript.append({"ask": asked["question"], "about": [str(value) for value in about], "reply": said})
                continue
            if "answer" in document:
                return _response(document, turn, findings)
            raise RuntimeError(f"exec_unparseable: turn {turn} reply has neither `call`, `ask` nor `answer`")
        return AgentResponse(answer="", notes=(f"turn budget of {self.max_turns} exhausted without an answer", *findings))


def _artifacts(raw: Any) -> tuple[ProducedArtifact, ...]:
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError("exec_unparseable: `artifacts` must be a list")
    out = []
    for item in raw:
        if not isinstance(item, Mapping) or not isinstance(item.get("name"), str):
            raise RuntimeError("exec_unparseable: each artifact needs a `name`")
        out.append(ProducedArtifact(name=item["name"], media_type=str(item.get("media_type") or "text/plain"),
                                    text=str(item.get("text") or ""),
                                    cites=tuple(str(value) for value in item.get("cites", ()))))
    return tuple(out)


def _response(document: Mapping[str, Any], turns: int, findings: tuple[str, ...] = ()) -> AgentResponse:
    planned = document.get("planned_dag")
    return AgentResponse(
        answer=str(document.get("answer") or ""), artifacts=_artifacts(document.get("artifacts")),
        planned_dag=dict(planned) if isinstance(planned, Mapping) else None,
        ttft=document.get("ttft") if isinstance(document.get("ttft"), (int, float)) else None,
        ttfa=document.get("ttfa") if isinstance(document.get("ttfa"), (int, float)) else None,
        notes=(f"answered on turn {turns}", *findings),
    )


# -- request / response files ----------------------------------------------------


def requests_document(service: ConnectorEvaluationService, cases: Iterable[EvalCase], *, principal: str = "agent") -> dict[str, Any]:
    """Every case as a request a harness can read offline, with its tool catalog.

    Catalogs come from a begun-and-ended run per case, so they are exactly
    what a live run would advertise: only the query's connectors, with the
    same safety annotations. Nothing about the expected DAG, fixtures or
    assertions is written; the document is what the agent may know.
    """

    entries = []
    for case in cases:
        begun = service.begin(principal, case.id)
        try:
            catalog = _catalog(service, principal, str(begun["run_id"]))
        finally:
            service.end(principal, str(begun["run_id"]))
        entries.append({"case_id": case.id, "query": case.query, "persona": case.persona, "principal": principal,
                        "max_calls": case.trajectory.max_calls, "tools": catalog})
    return {"schema": REQUESTS_SCHEMA, "instructions": response_instructions(), "cases": entries,
            "response_schema": {
                "schema": RESPONSES_SCHEMA,
                "cases": {"<case_id>": {"calls": [["<connector.tool>", {"<param>": "<value>"}]],
                                        "answer": "<final message>",
                                        "artifacts": [{"name": "<name>", "text": "<text>", "cites": ["<record id>"]}]}},
            }}


def load_responses(path: Path) -> dict[str, dict[str, Any]]:
    """Read a responses document (or the bare ``{case_id: {...}}`` form) into per-case scripts."""

    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        raise ValueError(f"{path}: expected a JSON object")
    body = raw.get("cases") if raw.get("schema") == RESPONSES_SCHEMA else raw
    if not isinstance(body, dict) or not all(isinstance(value, dict) for value in body.values()):
        raise ValueError(f"{path}: expected {{case_id: {{calls, answer, artifacts}}}}")
    scripts: dict[str, dict[str, Any]] = {}
    for case_id, entry in body.items():
        calls = entry.get("calls", ())
        if not isinstance(calls, list) or not all(isinstance(call, (list, tuple)) and len(call) == 2 and isinstance(call[0], str) for call in calls):
            raise ValueError(f"{path}: case {case_id!r} `calls` must be a list of [tool, arguments]")
        scripts[str(case_id)] = {
            "calls": [ToolCall(tool=call[0], arguments=dict(call[1] or {})) for call in calls],
            "answer": str(entry.get("answer") or ""),
            "artifacts": _artifacts(entry.get("artifacts")),
        }
    return scripts


class ResponsesAgent:
    """Replay a responses document: each case's scripted calls, answer and artifacts."""

    def __init__(self, scripts: Mapping[str, Mapping[str, Any]], *, name: str = "responses") -> None:
        self.name = name
        self._scripts = dict(scripts)

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        from .agents import ScriptedAgent

        entry = self._scripts.get(task.case_id)
        if entry is None:
            raise RuntimeError("not_attempted: the responses document holds no entry for this case")
        return ScriptedAgent(entry["calls"], answer=entry["answer"], artifacts=entry["artifacts"], name=self.name).run(task, tools)


__all__ = [
    "REQUESTS_SCHEMA",
    "RESPONSES_SCHEMA",
    "TURN_SCHEMA",
    "ExecAgent",
    "ResponsesAgent",
    "default_max_turns",
    "load_responses",
    "requests_document",
    "response_instructions",
    "turn_instructions",
]
