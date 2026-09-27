"""The ``sdk-program`` harness mode: the agent under test writes a program, Worldloom runs it.

A coding harness does not plan by emitting one tool call per turn; it writes
a program against an SDK and runs it. ``evalrun run --exec <cmd>
--harness-mode sdk-program`` measures exactly that. The child is asked once
per case, over the same ``--exec`` seam (one JSON document on stdin, one on
stdout), for a Python program; the document (``worldloom.evalrun-program/v1``)
carries the request, the tool catalog, a generated client module with one
method per tool (``worldloom_client``), the environment variable naming the
tool endpoint (``WORLDLOOM_TOOL_URL``) and, when the run is served by Anvil,
the vendor base URLs. The child replies ``{"program": "<python source>"}``,
optionally with the ``planned_dag`` it intends.

Worldloom writes the program beside the client module in a scratch directory
and runs it in a subprocess, with a timeout, against the run's serving path:
in process, through a local HTTP shim over the run's own tool surface (so
every call is a span of the run, graded by the same code as any other
agent's); under ``--connectors anvil``, against Anvil's vendor API, whose
trace is replayed into the run as usual. The program prints its answer on
stdout: a last line that is a JSON object with ``answer`` (and optional
``artifacts``) is read as the reply, anything else is the answer text.

The program is an artifact of the run: its source, digest, exit status and
output tails ride on the case's ledger line (``CaseResult.program``) for
trace review and training export. Its declared DAG is the reply's
``planned_dag`` when the child states one, else the DAG read statically off
the source (``declared_from_program``): every tool call in source order,
depending on the calls whose results flow into its arguments through
variables. The executed DAG is read off data flow as for any run
(``evalrun.lineage``), and the two are graded separately.

The shim notes which calls overlapped in time (a program that issues reads
from threads); those spans count as one step, so independent reads the
program did issue together are not reported as serialised.

Nothing here runs unless a caller asks for it: the default harness mode is
the turn protocol (``harness.ExecAgent``).
"""

from __future__ import annotations

import ast
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from collections.abc import Mapping, Sequence
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .. import packkit
from ..connector_emulator import ConnectorError
from ..connectors.serving import ServingError
from ..connectors.surface import error_document
from ..execseam import DEFAULT_TIMEOUT, ExecError, run_exec
from ..ids import content_key
from .agents import AgentResponse, AgentTask, ProducedArtifact, ToolSurface

PROGRAM_SCHEMA = "worldloom.evalrun-program/v1"
HARNESS_MODES = ("turns", "sdk-program")
#: The environment variable the program finds the tool endpoint in.
ENDPOINT_ENV = "WORLDLOOM_TOOL_URL"
CLIENT_MODULE = "worldloom_client"
DEFAULT_PROGRAM_TIMEOUT = 300.0
_TAIL = 2000


def program_instructions() -> list[str]:
    """What the program document tells the child (``evalrun.program.rule.*``)."""
    return packkit.texts("evalrun.program.rule.")


# -- the generated client ----------------------------------------------------------------


def _identifier(name: str) -> str:
    cleaned = re.sub(r"\W", "_", name)
    return f"_{cleaned}" if not cleaned or cleaned[0].isdigit() else cleaned


def _client_connector(tool: Mapping[str, Any]) -> str:
    """The client object a tool's method hangs on: a contract tool says its connector; a native one is ``connector.tool``."""
    name = str(tool.get("name", ""))
    return str(tool.get("connector") or (name.partition(".")[0] if "." in name else ""))


def _client_method(tool: Mapping[str, Any]) -> str:
    """A tool's method name: a contract tool without its service prefix (as Anvil's own SDK names it)."""
    name = str(tool.get("name", ""))
    if tool.get("surface") == "contract":
        return _identifier(name.removeprefix(f"{_client_connector(tool)}_"))
    return _identifier(name.partition(".")[2])


def client_methods(catalog: Sequence[Mapping[str, Any]]) -> dict[str, str]:
    """``client.method`` to tool name for each contract tool, so a program's calls are read as the tools they are."""
    return {f"{_identifier(_client_connector(tool))}.{_client_method(tool)}": str(tool["name"])
            for tool in catalog if tool.get("surface") == "contract" and _client_connector(tool)}


def client_source(catalog: Sequence[Mapping[str, Any]]) -> str:
    """A client module with one method per tool in *catalog*, calling the endpoint in ``$WORLDLOOM_TOOL_URL``."""

    by_connector: dict[str, list[Mapping[str, Any]]] = {}
    for tool in catalog:
        connector = _client_connector(tool)
        if connector:
            by_connector.setdefault(connector, []).append(tool)
    lines = [
        '"""Worldloom tool client, generated for one case: one method per tool the case may call.',
        "",
        "Call a tool as ``<connector>.<tool>(**arguments)`` or ``call(\"<connector>.<tool>\", **arguments)``.",
        "A tool error raises ``ToolError`` (``.code``, ``.kind``, ``.message``); ``ask`` puts a question to the user.",
        '"""',
        "",
        "import json",
        "import os",
        "import urllib.request",
        "",
        "",
        "class ToolError(Exception):",
        "    def __init__(self, error):",
        "        super().__init__(error.get(\"message\", \"\"))",
        "        self.error = error",
        "        self.code = error.get(\"code\")",
        "        self.kind = error.get(\"kind\")",
        "        self.message = error.get(\"message\", \"\")",
        "",
        "",
        "def _post(path, body):",
        f"    url = os.environ[{ENDPOINT_ENV!r}].rstrip(\"/\") + path",
        "    request = urllib.request.Request(url, data=json.dumps(body).encode(\"utf-8\"), method=\"POST\",",
        "                                     headers={\"Content-Type\": \"application/json\"})",
        "    with urllib.request.urlopen(request, timeout=600) as response:",
        "        return json.loads(response.read().decode(\"utf-8\"))",
        "",
        "",
        "def call(tool, **arguments):",
        "    reply = _post(\"/call\", {\"tool\": tool, \"arguments\": arguments})",
        "    if \"error\" in reply:",
        "        raise ToolError(reply[\"error\"])",
        "    return reply[\"result\"]",
        "",
        "",
        "def ask(question, about=()):",
        "    return _post(\"/ask\", {\"question\": question, \"about\": list(about)}).get(\"reply\", \"\")",
    ]
    for connector in sorted(by_connector):
        cls = f"_{_identifier(connector).title().replace('_', '')}"
        lines += ["", "", f"class {cls}:"]
        for tool in sorted(by_connector[connector], key=lambda item: str(item.get("name"))):
            name = str(tool["name"])
            params = sorted(str(key) for key in (tool.get("params") or {}))
            if tool.get("surface") == "contract":
                # The contract's operation: its title and its route.
                summary = f"{tool.get('title') or tool.get('operation')} ({tool.get('method')} {tool.get('path')})."
                summary = summary.replace('"""', "'''").replace("\\", "/")
            else:
                entities = ", ".join(str(entity) for entity in tool.get("entities") or ()) or "any"
                summary = f"{tool.get('op') or 'call'} on {entities}."
            lines += [
                f"    def {_client_method(tool)}(self, **arguments):",
                f'        """{summary} Parameters: {", ".join(params) or "none"}."""',
                f"        return call({name!r}, **arguments)",
                "",
            ]
        lines += [f"{_identifier(connector)} = {cls}()"]
    return "\n".join(lines) + "\n"


# -- the declared DAG, read off the source -------------------------------------------------


def declared_from_program(source: str, tools: Sequence[str], *, methods: Mapping[str, str] | None = None
                          ) -> dict[str, Any] | None:
    """The DAG a program's source declares: tool calls in source order, dependencies by variable flow.

    A call is ``<connector>.<tool>(...)`` (through any client object) or
    ``call("<connector.tool>", ...)``. A call depends on every earlier call
    whose result reaches one of its arguments through assignments, loop
    variables and subscripts. A call inside a loop is one node. ``None`` when
    the source does not parse or names no tool.
    """

    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return None
    known = {name: name for name in tools}
    for name in tools:
        connector, _, tool = name.partition(".")
        known[f"{_identifier(connector)}.{_identifier(tool)}"] = name
    known.update(methods or {})
    taint: dict[str, set[str]] = {}
    nodes: list[dict[str, Any]] = []

    def tool_of(call: ast.Call) -> str | None:
        func = call.func
        if isinstance(func, ast.Attribute):
            if func.attr == "call" and call.args and isinstance(call.args[0], ast.Constant) \
                    and isinstance(call.args[0].value, str) and call.args[0].value in known:
                return known[call.args[0].value]
            owner = func.value
            if isinstance(owner, ast.Attribute):
                return known.get(f"{owner.attr}.{func.attr}")
            if isinstance(owner, ast.Name):
                return known.get(f"{owner.id}.{func.attr}")
        if isinstance(func, ast.Name) and func.id == "call" and call.args and isinstance(call.args[0], ast.Constant) \
                and isinstance(call.args[0].value, str):
            return known.get(call.args[0].value)
        return None

    def deps(expr: ast.AST | None) -> set[str]:
        if expr is None:
            return set()
        if isinstance(expr, ast.Call):
            tool = tool_of(expr)
            inner: set[str] = set()
            for child in (*expr.args, *(keyword.value for keyword in expr.keywords)):
                inner |= deps(child)
            if tool is None:
                receiver = deps(expr.func)
                # ``details.append(result)``: a method call carries its
                # arguments' results into the object it was called on.
                owner: ast.AST = expr.func
                while isinstance(owner, (ast.Attribute, ast.Subscript)):
                    owner = owner.value
                if isinstance(owner, ast.Name) and isinstance(expr.func, ast.Attribute) and inner:
                    taint.setdefault(owner.id, set()).update(inner)
                return inner | receiver
            entity = next((keyword.value.value for keyword in expr.keywords
                           if keyword.arg == "entity" and isinstance(keyword.value, ast.Constant)
                           and isinstance(keyword.value.value, str)), "")
            node_id = f"p{len(nodes) + 1}"
            nodes.append({"id": node_id, "tool": tool, "depends_on": sorted(inner), "entity": entity})
            return {node_id}
        if isinstance(expr, ast.Name):
            return set(taint.get(expr.id, set())) if isinstance(expr.ctx, ast.Load) else set()
        found: set[str] = set()
        for part in ast.iter_child_nodes(expr):
            found |= deps(part)
        return found

    def bind(target: ast.AST, flowing: set[str]) -> None:
        if isinstance(target, ast.Name):
            taint[target.id] = set(flowing)
        elif isinstance(target, (ast.Tuple, ast.List)):
            for element in target.elts:
                bind(element, flowing)
        elif isinstance(target, ast.Starred):
            bind(target.value, flowing)
        elif isinstance(target, (ast.Attribute, ast.Subscript)):
            base: ast.AST = target
            while isinstance(base, (ast.Attribute, ast.Subscript)):
                base = base.value
            if isinstance(base, ast.Name):
                taint.setdefault(base.id, set()).update(flowing)

    def block(statements: Sequence[ast.stmt]) -> None:
        for statement in statements:
            if isinstance(statement, ast.Assign):
                flowing = deps(statement.value)
                for target in statement.targets:
                    bind(target, flowing)
            elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)):
                flowing = deps(statement.value)
                if isinstance(statement, ast.AugAssign):
                    flowing |= deps(ast.Name(id=statement.target.id, ctx=ast.Load())) \
                        if isinstance(statement.target, ast.Name) else set()
                bind(statement.target, flowing)
            elif isinstance(statement, (ast.For, ast.AsyncFor)):
                bind(statement.target, deps(statement.iter))
                block(statement.body)
                block(statement.orelse)
            elif isinstance(statement, (ast.While, ast.If)):
                deps(statement.test)
                block(statement.body)
                block(statement.orelse)
            elif isinstance(statement, (ast.With, ast.AsyncWith)):
                for item in statement.items:
                    flowing = deps(item.context_expr)
                    if item.optional_vars is not None:
                        bind(item.optional_vars, flowing)
                block(statement.body)
            elif isinstance(statement, ast.Try):
                block(statement.body)
                for handler in statement.handlers:
                    block(handler.body)
                block(statement.orelse)
                block(statement.finalbody)
            elif isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                block(statement.body)
            elif isinstance(statement, ast.ClassDef):
                block(statement.body)
            else:
                for child in ast.iter_child_nodes(statement):
                    deps(child)

    block(tree.body)
    if not nodes:
        return None
    return {"nodes": nodes}


# -- the tool shim ----------------------------------------------------------------------------


class ToolShim:
    """A local HTTP endpoint over one run's tool surface, for a program in a subprocess.

    ``POST /call`` ``{"tool", "arguments"}`` answers ``{"result"}`` or
    ``{"error"}``; ``POST /ask`` ``{"question", "about"}`` answers
    ``{"reply"}``; ``GET /tools`` is the catalog. Calls reach the surface
    one at a time, in arrival order, so the run's spans are the program's
    calls in the order it made them; a call that arrived while another was in
    flight is recorded as concurrent with it.
    """

    def __init__(self, tools: ToolSurface) -> None:
        self.tools = tools
        self._serial = threading.Lock()
        self._state = threading.Lock()
        self._inflight = 0
        self._group = 0
        self._groups: dict[int, list[str]] = {}
        shim = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, format: str, *args: Any) -> None:
                return

            def _reply(self, status: int, body: Any) -> None:
                data = json.dumps(body, sort_keys=True, default=str).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                if self.path.rstrip("/") == "/tools":
                    self._reply(200, {"tools": [dict(tool) for tool in shim.tools.tools()]})
                else:
                    self._reply(404, {"error": {"code": 404, "kind": "not_found", "message": self.path}})

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8") or "{}")
                except ValueError:
                    self._reply(400, {"error": {"code": 400, "kind": "validation", "message": "body is not JSON"}})
                    return
                if not isinstance(body, dict):
                    self._reply(400, {"error": {"code": 400, "kind": "validation", "message": "body must be an object"}})
                    return
                if self.path.rstrip("/") == "/call":
                    self._reply(200, shim.call(str(body.get("tool", "")), body.get("arguments") or {}))
                elif self.path.rstrip("/") == "/ask":
                    self._reply(200, shim.ask(str(body.get("question", "")), body.get("about") or ()))
                else:
                    self._reply(404, {"error": {"code": 404, "kind": "not_found", "message": self.path}})

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._server.daemon_threads = True
        self._thread = threading.Thread(target=self._server.serve_forever, name="evalrun-program-shim", daemon=True)

    @property
    def url(self) -> str:
        host, port = self._server.server_address[:2]
        return f"http://{host!s}:{port}"

    def __enter__(self) -> ToolShim:
        self._thread.start()
        return self

    def __exit__(self, *exc: Any) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=10)

    def call(self, tool: str, arguments: Any) -> dict[str, Any]:
        with self._state:
            if self._inflight == 0:
                self._group += 1
            group = self._group
            self._inflight += 1
        try:
            with self._serial:
                before = len(self.tools.spans)
                reply: dict[str, Any]
                try:
                    if not isinstance(arguments, Mapping):
                        raise ServingError("arguments must be an object")
                    reply = {"result": self.tools.call(tool, **dict(arguments))}
                except ConnectorError as failure:
                    reply = {"error": error_document(failure)}
                except ServingError as failure:
                    reply = {"error": {"code": 400, "kind": "serving", "message": str(failure)}}
                spans = self.tools.spans
                if len(spans) > before:
                    self._groups.setdefault(group, []).append(str(spans[-1].id))
                return reply
        finally:
            with self._state:
                self._inflight -= 1

    def ask(self, question: str, about: Any) -> dict[str, Any]:
        with self._serial:
            try:
                return {"reply": self.tools.ask(question, about=tuple(str(value) for value in about))}
            except ServingError as failure:
                return {"error": {"code": 400, "kind": "serving", "message": str(failure)}}

    def concurrent(self) -> list[list[str]]:
        """The groups of spans whose calls overlapped in time, only groups of two or more."""
        return [list(members) for _, members in sorted(self._groups.items()) if len(members) > 1]


# -- the agent --------------------------------------------------------------------------------


def _tail(text: str) -> str:
    return text[-_TAIL:]


def _answer(stdout: str) -> tuple[str, tuple[ProducedArtifact, ...]]:
    lines = [line for line in stdout.splitlines() if line.strip()]
    if lines:
        try:
            document = json.loads(lines[-1])
        except ValueError:
            document = None
        if isinstance(document, dict) and "answer" in document:
            from .harness import _artifacts

            return str(document.get("answer") or ""), _artifacts(document.get("artifacts"))
    return stdout.strip(), ()


class ProgramAgent:
    """The child writes a program once per case; Worldloom runs it and grades the calls it made."""

    def __init__(self, command: str, *, timeout: float = DEFAULT_TIMEOUT, shell: bool = False,
                 program_timeout: float = DEFAULT_PROGRAM_TIMEOUT, name: str | None = None,
                 python: str | None = None) -> None:
        if program_timeout <= 0:
            raise ValueError("program_timeout must be positive")
        self.command = command
        self.timeout = timeout
        self.shell = shell
        self.program_timeout = program_timeout
        self.python = python or sys.executable
        self.name = name or f"program:{command.split()[0] if command.split() else command}"
        #: Case id to the program record of a case whose program failed, so the
        #: runner keeps the program on the error row as well.
        self.last_program: dict[str, dict[str, Any]] = {}

    def fingerprint(self) -> dict[str, Any]:
        from .grader import redact_command

        return {"kind": "sdk-program", "command": redact_command(self.command), "shell": self.shell,
                "timeout": self.timeout, "program_timeout": self.program_timeout}

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        catalog = [dict(tool) for tool in tools.tools()]
        names = [str(tool.get("name")) for tool in catalog]
        environment: Mapping[str, str] | None = getattr(tools, "environment", None)
        base_urls: Mapping[str, str] | None = getattr(tools, "base_urls", None)
        client = client_source(catalog)
        payload: dict[str, Any] = {
            "schema": PROGRAM_SCHEMA, "case_id": task.case_id, "query": task.query, "persona": task.persona,
            "principal": task.principal, "tools": catalog, "instructions": program_instructions(),
            "client": {"module": CLIENT_MODULE, "source": client, "endpoint_env": ENDPOINT_ENV},
            "language": "python", "program_timeout": self.program_timeout,
        }
        if base_urls:
            payload["anvil"] = {"base_urls": dict(base_urls), "base_url_env": "ANVIL_BASE_URL", "token_env": "ANVIL_TOKEN"}
        try:
            reply = run_exec(self.command, payload, timeout=self.timeout, shell=self.shell, env=environment)
        except ExecError as error:
            tail = getattr(error, "stderr_tail", "")
            raise RuntimeError(f"{error.code}: {error}" + (f"\n{tail}" if tail else "")) from error
        document = reply.document
        source = document.get("program")
        if not isinstance(source, str) or not source.strip():
            raise RuntimeError("exec_unparseable: the reply must be {\"program\": \"<python source>\"}")
        stated = document.get("planned_dag")
        declared = dict(stated) if isinstance(stated, Mapping) else declared_from_program(source, names, methods=client_methods(catalog))
        record: dict[str, Any] = {
            "language": "python", "source": source, "digest": content_key("evalrun-program", source),
            "declared_from": "reply" if isinstance(stated, Mapping) else ("source" if declared else None),
            "declared": declared,
        }
        with tempfile.TemporaryDirectory(prefix="worldloom-program-") as scratch, ToolShim(tools) as shim:
            folder = Path(scratch)
            (folder / f"{CLIENT_MODULE}.py").write_text(client, encoding="utf-8")
            (folder / "program.py").write_text(source, encoding="utf-8")
            env = {**os.environ, **dict(environment or {})}
            env[ENDPOINT_ENV] = shim.url
            env["PYTHONPATH"] = os.pathsep.join(part for part in (scratch, env.get("PYTHONPATH", "")) if part)
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            try:
                done = subprocess.run([self.python, "program.py"], cwd=scratch, env=env, capture_output=True,
                                      text=True, timeout=self.program_timeout, check=False)
            except subprocess.TimeoutExpired as error:
                stderr = error.stderr.decode("utf-8", "replace") if isinstance(error.stderr, bytes) else (error.stderr or "")
                record.update({"exit_code": None, "stdout_tail": "", "stderr_tail": _tail(stderr),
                               "concurrent": shim.concurrent()})
                self.last_program[task.case_id] = record
                raise RuntimeError(f"program_timeout: the program ran past {self.program_timeout}s") from error
            record.update({"exit_code": done.returncode, "stdout_tail": _tail(done.stdout),
                           "stderr_tail": _tail(done.stderr), "concurrent": shim.concurrent()})
        if done.returncode != 0:
            self.last_program[task.case_id] = record
            raise RuntimeError(f"program_failed: exit {done.returncode}\n{_tail(done.stderr)}")
        answer, artifacts = _answer(done.stdout)
        return AgentResponse(answer=answer, artifacts=artifacts, planned_dag=declared,
                             notes=(f"sdk-program {record['digest'][:12]} exited 0",), program=record)


__all__ = [
    "CLIENT_MODULE",
    "DEFAULT_PROGRAM_TIMEOUT",
    "ENDPOINT_ENV",
    "HARNESS_MODES",
    "PROGRAM_SCHEMA",
    "ProgramAgent",
    "ToolShim",
    "client_source",
    "declared_from_program",
    "program_instructions",
]
