"""The agent under test, and the surface it sees.

An eval run needs a seam between the thing being measured and the thing
measuring it. On one side of the seam is the agent: it receives a request and
a set of tools, calls some of them, and returns an answer. On the other side
is the run: it owns the connector state, records every call, and grades. The
agent never sees the expected DAG, the fixture ids, or the assertions, and it
cannot submit its own trace -- the same rule ``ConnectorEvaluationService``
enforces over MCP, kept here for an in-process agent.

Three agents ship. ``ScriptedAgent`` replays a list of calls, which is how a
test states a trajectory exactly. ``CallableAgent`` wraps any Python callable,
which is how a harness plugs in a model. ``ReferenceAgent`` is privileged: it
holds the compiled rows and walks each expected DAG through the same surface,
so a case can be proven executable *through the surface an external agent
would use* rather than through a private runtime. Its trajectory is the
ceiling every other agent is compared against, not a claim about any model.
"""

from __future__ import annotations

import copy
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any, Protocol

from pydantic import Field

from ..connector_emulator import ConnectorError, ConnectorSpan
from ..connectors.serving import ConnectorEvaluationService, ServingError
from ..models import Model
from .contract import EvalCase


class AgentTask(Model):
    """What the agent is told. Nothing else about the case reaches it."""

    case_id: str
    query: str
    persona: str = ""
    principal: str = "agent"


class ProducedArtifact(Model):
    """An unstructured output the agent hands back: a memo, a sheet, a reply body."""

    name: str
    media_type: str = "text/plain"
    text: str = ""
    #: Fact or evidence ids the agent claims the artifact rests on. Claims,
    #: not proof; the outcome grader checks them against the case.
    cites: tuple[str, ...] = ()


class AgentResponse(Model):
    answer: str = ""
    artifacts: tuple[ProducedArtifact, ...] = ()
    #: The DAG the agent says it planned, when it exposes one. Graded
    #: alongside the observed DAG, never instead of it.
    planned_dag: dict[str, Any] | None = None
    #: Seconds to the first token and first answer token, when the agent's
    #: transport can measure them (Eval Studio's TTFT and TTFA). The runner
    #: measures the last-token time itself.
    ttft: float | None = None
    ttfa: float | None = None
    notes: tuple[str, ...] = Field(default=())


#: The pseudo-tool a scripted trajectory uses to ask the user a question:
#: ``ToolCall(tool="ask", arguments={"question": ..., "about": [...]})``.
#: Not a connector tool; the surface routes it to ``ToolSurface.ask``.
ASK = "ask"


class ToolCall(Model):
    tool: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolSurface:
    """The run's tools, callable, and the observed trace so far.

    Errors propagate to the agent as the connector would raise them: a
    ``ConnectorError`` for a refused call, a ``ServingError`` for a call the
    run does not admit. Both are recorded before they propagate: the first as
    an error span, the second in the run's refusals (there is no span for a
    call that never reached a connector), so an agent that swallows an error
    still leaves the attempt where the grader reads it.
    """

    def __init__(self, service: ConnectorEvaluationService, principal: str, run_id: str) -> None:
        self._service = service
        self._principal = principal
        self.run_id = run_id
        self.attempts = 0

    def tools(self) -> tuple[dict[str, Any], ...]:
        return self._service.tool_catalog(self._principal, self.run_id)

    def call(self, tool: str, /, **arguments: Any) -> Any:
        # Positional-only, because ``name`` is a real tool argument (every
        # create takes one) and must not collide with the tool's own name.
        self.attempts += 1
        return self._service.call(self._principal, self.run_id, tool, arguments)

    def ask(self, question: str, *, about: Sequence[str] = ()) -> str:
        """Ask the user a question and get their reply.

        A question is a turn: the service records it beside the spans, at the
        position it was asked, and answers it from the case's own question
        points. The agent never sees whether the question was expected; an
        unexpected one is answered too, and graded as unsolicited.
        """
        return str(self._service.ask(self._principal, self.run_id, question, tuple(about)))

    @property
    def questions(self) -> tuple[dict[str, Any], ...]:
        """Every question this run asked, in order, with the reply it got."""
        return self._service.questions(self._principal, self.run_id)

    @property
    def spans(self) -> tuple[ConnectorSpan, ...]:
        return self._service.spans(self._principal, self.run_id)

    @property
    def refusals(self) -> tuple[dict[str, Any], ...]:
        """Calls the run did not admit: unknown tool, undeclared argument, a limit."""
        return self._service.refusals(self._principal, self.run_id)


class AgentUnderTest(Protocol):
    name: str

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse: ...


class ScriptedAgent:
    """Replay a fixed trajectory. A test's way of saying exactly what happened."""

    def __init__(self, calls: Iterable[ToolCall | tuple[str, Mapping[str, Any]]], *, answer: str = "",
                 artifacts: Sequence[ProducedArtifact] = (), name: str = "scripted", stop_on_error: bool = False) -> None:
        self.name = name
        self.calls = tuple(call if isinstance(call, ToolCall) else ToolCall(tool=call[0], arguments=dict(call[1]))
                           for call in calls)
        self.answer = answer
        self.artifacts = tuple(artifacts)
        self.stop_on_error = stop_on_error

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        for call in self.calls:
            if call.tool == ASK:
                # A scripted question: replay cannot read the reply, but the
                # turn is recorded where it was asked, which is what the
                # grade reads.
                tools.ask(str(call.arguments.get("question", "")),
                          about=tuple(str(value) for value in call.arguments.get("about", ())))
                continue
            try:
                tools.call(call.tool, **copy.deepcopy(call.arguments))
            except (ConnectorError, ServingError):
                if self.stop_on_error:
                    break
        return AgentResponse(answer=self.answer, artifacts=self.artifacts)


class CallableAgent:
    """Any ``(task, tools) -> AgentResponse`` callable, named."""

    def __init__(self, fn: Callable[[AgentTask, ToolSurface], AgentResponse], *, name: str) -> None:
        self.name = name
        self._fn = fn

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        return self._fn(task, tools)


_CREATE_OPS = frozenset({"create", "send", "post", "upload"})
_BODY_OPS = frozenset({"comment", "reply"})
_READ_OPS = frozenset({"get", "download"})


def _first_id(values: Sequence[Any]) -> Any:
    for value in values:
        if isinstance(value, Mapping):
            for key in ("id", "key", "number", "name"):
                if value.get(key) not in (None, ""):
                    return value[key]
        elif value not in (None, ""):
            return value
    return None


class ReferenceAgent:
    """Walk each case's expected DAG through the surface. The executable ceiling.

    Privileged by construction: it is handed the cases, so it knows the plan.
    That is the point -- it proves the plan is executable through the tools
    an external agent gets, and its grade is what a perfect agent scores.
    A case it cannot complete is a finding about the case, reported in the
    response notes, never hidden by a fallback to a private runtime.
    """

    name = "reference"

    def __init__(self, cases: Iterable[EvalCase]) -> None:
        self._rows = {case.id: case.row for case in cases}
        self._params: dict[str, set[str]] = {}

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        row = self._rows.get(task.case_id)
        if row is None:
            raise ValueError(f"reference agent holds no row for case {task.case_id!r}")
        # The surface refuses an argument the tool does not declare, exactly
        # as the MCP server would. The compiled row speaks the emulator's
        # wider vocabulary (an ``entity`` on every create), so each call is
        # pruned to what the tool advertises, which is what a real agent
        # reading ``tools/list`` would send.
        self._params = {str(tool["name"]): set(tool["params"]) for tool in tools.tools()}
        # The questions the row requires, asked before anything runs: the
        # reference knows the plan, so it also knows what is unclear about it.
        # A question carries what the row says it must mention; a
        # confirmation names the record it is about.
        for assertion in row.get("assertions", ()):
            if assertion.get("type") == "question_required":
                tokens = " ".join(str(value) for value in assertion.get("must_mention", ()))
                tools.ask(f"Before I proceed: {tokens or assertion.get('id', 'please clarify')}?",
                          about=tuple(str(value) for value in assertion.get("about", ())))
        if any(assertion.get("type") == "confirm_before" for assertion in row.get("assertions", ())):
            for node in row["expected_dag"]["nodes"]:
                if node.get("op") == "delete" or node.get("resolved_operation") == "delete":
                    tools.ask(f"This will permanently delete {node.get('fixture') or 'the record'}; shall I go ahead?",
                              about=(str(node["id"]),))
        notes = (self._walk_grammar(row, tools) if row.get("grammar") == "enterprise-dag@1"
                 else self._walk_legacy(row, tools))
        # A row that states its expected answer (a programme's record request
        # does: the answer is read off the records the plan searches) has the
        # reference say it, so the ceiling covers the answer axis too. A row
        # without one reports what it did, as before.
        stated = str(row.get("expected_answer") or "").strip()
        answer = stated or f"Completed {task.case_id}: {len(tools.spans)} calls."
        return AgentResponse(answer=answer, notes=tuple(notes))

    def _call(self, tools: ToolSurface, tool: str, /, **arguments: Any) -> Any:
        allowed = self._params.get(tool)
        pruned = {key: value for key, value in arguments.items()
                  if value is not None and (allowed is None or key in allowed)}
        return tools.call(tool, **pruned)

    # -- legacy rows ---------------------------------------------------------

    def _walk_legacy(self, row: Mapping[str, Any], tools: ToolSurface) -> list[str]:
        nodes = list(row["expected_dag"]["nodes"])
        edges = list(row["expected_dag"].get("edges", ()))
        parents = {str(node["id"]): [str(s) for s, t in edges if str(t) == str(node["id"])] for node in nodes}
        outputs: dict[str, list[Any]] = {}
        failed: set[str] = set()
        notes: list[str] = []
        for node in nodes:
            node_id = str(node["id"])
            if "gated" in set(node.get("flags", ())):
                continue
            if failed.intersection(parents[node_id]):
                failed.add(node_id)
                notes.append(f"blocked:{node_id}")
                continue
            name = f"{node['server']}.{node['tool']}"
            payload = dict(node.get("payload") or {})
            entity = node.get("entity")
            op = str(node.get("resolved_operation") or node.get("op") or "")
            target: Any = node.get("fixture")
            if node.get("reference_from"):
                produced = outputs.get(str(node["reference_from"]), [])
                if len(produced) != 1:
                    notes.append(f"unresolved_reference:{node_id}")
                    failed.add(node_id)
                    continue
                target = produced[0]
            iterations: list[Any] = [None]
            if node.get("for_each"):
                iterations = list(outputs.get(parents[node_id][0], ())) if parents[node_id] else []
                if not iterations:
                    notes.append(f"no_items:{node_id}")
                    continue
            made: list[Any] = []
            try:
                if op == "search":
                    arguments: dict[str, Any] = {"entity": entity, "max_results": int(payload.get("max_results", 50) or 50),
                                                 "start_at": int(payload.get("start_at", 0) or 0)}
                    for key in ("predicate", "query", "fields", "name"):
                        if key in payload:
                            arguments[key] = payload[key]
                    page = self._call(tools, name, **arguments)
                    made.extend(_first_id([item]) for item in page.get("items", ()))
                elif op in _READ_OPS or op in {"read", "extract", "readback", "cross_system"}:
                    # A verify is a read of what was written: the legacy
                    # spelling of the op is `readback`, and the reference
                    # never walked one until the hand rows asked it to.
                    for reference in list(node.get("fixtures", ())) or [target]:
                        result = self._call(tools, name, id=reference, fields=payload.get("fields"))
                        made.append(_first_id([result]) if isinstance(result, Mapping) else reference)
                else:
                    for item in iterations:
                        record = item if item is not None else target
                        if op in _CREATE_OPS:
                            fields = {k: v for k, v in (payload.get("fields") or {}).items()}
                            arguments = {"entity": entity, "name": payload.get("name"), "fields": fields,
                                         "parent": payload.get("parent") or payload.get("dest")}
                            result = self._call(tools, name, **arguments)
                        elif op == "update":
                            result = self._call(tools, name, id=record, fields=dict(payload.get("fields") or {}))
                        elif op in _BODY_OPS:
                            result = self._call(tools, name, id=record, body=payload.get("body") or payload.get("note") or "update")
                        elif op == "forward":
                            result = self._call(tools, name, id=record, to=payload.get("to") or (), body=payload.get("body"))
                        elif op == "transition":
                            result = self._call(tools, name, id=record, state=payload.get("state"))
                        elif op == "delete":
                            result = self._call(tools, name, id=record)
                        elif op == "transform":
                            result = self._call(tools, name, id=record, format=payload.get("format") or payload.get("fmt"),
                                                dest=payload.get("dest"))
                        else:
                            notes.append(f"unsupported_operation:{node_id}:{op}")
                            failed.add(node_id)
                            break
                        made.append(_first_id([result]) if isinstance(result, Mapping) else record)
            except ConnectorError as error:
                failed.add(node_id)
                notes.append(f"connector_error:{node_id}:{error.kind}")
            except ServingError as error:
                failed.add(node_id)
                notes.append(f"serving_error:{node_id}:{error}")
            outputs[node_id] = [value for value in made if value is not None]
        return notes

    # -- grammar rows --------------------------------------------------------

    def _walk_grammar(self, row: Mapping[str, Any], tools: ToolSurface) -> list[str]:
        from ..enterprise_dag import condition_matches
        from ..enterprise_dag_rows import program_for
        from ..enterprise_dag_runtime import bound_arguments, observed_outputs

        program = program_for(row)
        wire = {str(node["id"]): node for node in row["expected_dag"]["nodes"]}
        failed: set[str] = set()
        notes: list[str] = []
        for node in program.nodes:
            if any(parent in failed for parent in node.depends_on):
                failed.add(node.id)
                notes.append(f"blocked:{node.id}")
                continue
            outputs = observed_outputs(row, tools.spans)
            if node.condition is not None and not condition_matches(node.condition, outputs):
                notes.append(f"condition:{node.id}:false")
                continue
            if node.kind == "transform":
                continue
            name = f"{node.connector}.{wire[node.id]['tool']}"
            items = outputs.get(node.for_each.node, [])[:node.for_each.limit] if node.for_each else [None]
            for item in items:
                try:
                    arguments = bound_arguments(node, outputs, item)
                except ValueError as error:
                    failed.add(node.id)
                    notes.append(f"unbound:{node.id}:{error}")
                    break
                if node.operation == "search":
                    arguments.setdefault("max_results", 50)
                    arguments["entity"] = node.entity
                    start = int(arguments.get("start_at", 0))
                    requested = int(arguments["max_results"])
                    emitted = 0
                    while emitted < requested:
                        page_args = {**arguments, "start_at": start, "max_results": requested - emitted}
                        try:
                            page = self._call(tools, name, **page_args)
                        except (ConnectorError, ServingError) as error:
                            failed.add(node.id)
                            notes.append(f"connector_error:{node.id}:{getattr(error, 'kind', error)}")
                            break
                        got = list(page.get("items", ()))
                        emitted += len(got)
                        if page.get("is_last") or not got:
                            break
                        start += int(page.get("max_results") or len(got))
                    continue
                if node.operation in _CREATE_OPS:
                    arguments["entity"] = node.entity
                try:
                    self._call(tools, name, **arguments)
                except (ConnectorError, ServingError) as error:
                    failed.add(node.id)
                    notes.append(f"connector_error:{node.id}:{getattr(error, 'kind', error)}")
                    break
        return notes


__all__ = [
    "ASK",
    "AgentResponse",
    "AgentTask",
    "AgentUnderTest",
    "CallableAgent",
    "ProducedArtifact",
    "ReferenceAgent",
    "ScriptedAgent",
    "ToolCall",
    "ToolSurface",
]
