"""Run a case against Anvil's served vendor API instead of the in-process emulator.

``worldloom evalrun run --connectors anvil --contract <bundle>`` (and
``EvalSession.run(..., anvil=AnvilServing(...))``) serves each case's
connectors through ``anvil simulate serve``: one server per connector per
case, each started with ``python -m worldloom.anvil_provider`` as its state
provider, over exactly the row and records the in-process service would
have used. The agent under test gets the servers' URLs and a token in its
environment (``ANVIL_BASE_URL``, ``ANVIL_TOKEN``, and per connector
``ANVIL_<CONNECTOR>_BASE_URL``) and calls the vendor's own REST paths; its
``call`` documents are refused, because the calls graded are the ones Anvil
saw.

When the agent returns, the servers stop and their JSONL traces are read
back. Each call that reached the provider is replayed, in the order the
providers answered, through the run's own service: the same mapping, the
same ``answer`` the provider ran, so the spans, the refusals and the state
diff the grader and the stages read are the ones an in-process run would
have produced for those calls. A replay that answers differently from what
the provider answered (a node-scoped failure attributed differently when
several connectors' calls interleave) is noted on the result, not hidden.
Calls Anvil answered itself (auth, an injected fault, an idempotent replay)
never reached a connector and are recorded as refusals.

The default stays the in-process emulator; nothing here runs unless a
caller asks for it.
"""

from __future__ import annotations

import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import threading
from collections import deque
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ..connectors.anvil import (
    AnvilMapping,
    MappingError,
    ServiceBackend,
    answer,
    lint_mapping,
    load_mapping,
    operations_from_air,
    read_air,
    shipped_mappings,
)
from ..connectors.anvil_provider import STATE_SCHEMA
from ..connectors.serving import ServingError
from ..ids import content_key
from .agents import ToolSurface

if TYPE_CHECKING:
    from ..connectors.serving import ConnectorEvaluationService
    from .contract import EvalCase

#: The environment variable naming the Anvil CLI (``node .../bin-anvil.js``),
#: split like a shell command; unset, ``anvil`` on ``PATH``.
ANVIL_COMMAND_ENV = "WORLDLOOM_ANVIL"
#: The simulated principal Anvil gives every scope; the agent sends it as its bearer token.
DEFAULT_TOKEN = "admin"


class AnvilError(RuntimeError):
    """Anvil could not serve a case: no CLI, a contract no mapping covers, a server that did not start."""


def find_anvil(explicit: str | None = None) -> tuple[str, ...] | None:
    """The Anvil CLI as an argv prefix: *explicit*, else ``$WORLDLOOM_ANVIL``, else ``anvil`` on ``PATH``."""

    spec = explicit or os.environ.get(ANVIL_COMMAND_ENV)
    if spec:
        return tuple(shlex.split(spec))
    found = shutil.which("anvil")
    return (found,) if found else None


def contract_service(path: str | Path) -> str:
    """The service id a contract was compiled under."""

    service = read_air(path).get("service") or {}
    return str(service.get("id") or "")


def resolve_contracts(specs: Sequence[str]) -> dict[str, Path]:
    """``connector=path`` (or a bare path, its connector the mapping written for its service) to a map.

    Refuses a path that does not exist, a connector named twice, and a bare
    path whose service no shipped mapping claims.
    """

    out: dict[str, Path] = {}
    for spec in specs:
        name, sep, raw = spec.partition("=")
        if not sep:
            name, raw = "", spec
        path = Path(raw)
        if not path.exists():
            raise AnvilError(f"contract {raw!r} does not exist")
        if not name:
            service = contract_service(path)
            claimed = [connector for connector in shipped_mappings() if load_mapping(connector).service == service]
            if not claimed and service in shipped_mappings():
                claimed = [service]
            if len(claimed) != 1:
                raise AnvilError(f"contract {raw!r} serves service {service!r}, which no shipped mapping claims; "
                                 "name its connector as CONNECTOR=PATH")
            name = claimed[0]
        if name in out:
            raise AnvilError(f"connector {name!r} is given two contracts")
        out[name] = path
    return out


def anvil_environment(base_urls: Mapping[str, str], token: str) -> dict[str, str]:
    """What the agent under test finds in its environment for these servers."""

    names = sorted(base_urls)
    env = {"ANVIL_TOKEN": token, "ANVIL_CONNECTORS": ",".join(names)}
    if names:
        env["ANVIL_BASE_URL"] = base_urls[names[0]]
    for name in names:
        env[f"ANVIL_{re.sub(r'[^A-Z0-9]', '_', name.upper())}_BASE_URL"] = base_urls[name]
    return env


class AnvilToolSurface(ToolSurface):
    """The run's surface when Anvil serves it: the catalog for reference, the calls over HTTP.

    ``base_urls``, ``token`` and ``environment`` say where the API is. A
    ``call`` is refused and recorded as a refusal: a call made here would not
    be the vendor-shaped call Anvil grades.
    """

    def __init__(self, service: ConnectorEvaluationService, principal: str, run_id: str, *,
                 base_urls: Mapping[str, str], token: str) -> None:
        super().__init__(service, principal, run_id)
        self.base_urls = dict(sorted(base_urls.items()))
        self.token = token
        self.environment = anvil_environment(self.base_urls, token)

    def call(self, tool: str, /, **arguments: Any) -> Any:
        self.attempts += 1
        message = ("anvil_mode: this run is served by Anvil; call the vendor API at $ANVIL_BASE_URL "
                   "with $ANVIL_TOKEN as the bearer token")
        self._service.record_refusal(self._principal, self.run_id, tool, arguments, message)
        raise ServingError(message)


def _record_json(record: Any) -> dict[str, Any]:
    raw = record.model_dump(mode="json") if hasattr(record, "model_dump") else dict(record)
    return json.loads(json.dumps(raw, sort_keys=True, default=str))


def _record_connector(record: Any) -> str:
    if hasattr(record, "connector"):
        return str(record.connector)
    return str(record.get("server") or record.get("connector") or "")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", name)[:120] or "case"


class AnvilServing:
    """Which connectors Anvil serves, from which contracts, with which CLI.

    Built once per run. Every contract is linted against its connector's
    mapping here, so a contract the mapping does not cover is refused before
    any case starts. ``workdir`` keeps each case's state files, traces and
    server logs (``<workdir>/<case>/``); without one they go to a temporary
    directory.
    """

    def __init__(self, contracts: Mapping[str, str | Path], *, command: Sequence[str] | str | None = None,
                 python: str | None = None, token: str = DEFAULT_TOKEN, workdir: str | Path | None = None,
                 startup_timeout: float = 60.0, mappings: Mapping[str, AnvilMapping] | None = None) -> None:
        if not contracts:
            raise AnvilError("name at least one contract")
        resolved = find_anvil(command) if isinstance(command, str) or command is None else tuple(command)
        if not resolved:
            raise AnvilError(f"no Anvil CLI: pass --anvil-cmd, set ${ANVIL_COMMAND_ENV}, or put `anvil` on PATH")
        self.command: tuple[str, ...] = tuple(resolved)
        self.python = python or sys.executable
        self.token = token
        self.startup_timeout = startup_timeout
        self.contracts = {name: Path(path) for name, path in sorted(contracts.items())}
        self.mappings: dict[str, AnvilMapping] = {}
        self._digests: dict[str, str] = {}
        for name, path in self.contracts.items():
            try:
                mapping = (mappings or {}).get(name) or load_mapping(name)
                air = read_air(path)
            except (MappingError, OSError, ValueError) as error:
                raise AnvilError(f"{name}: {error}") from error
            errors, _ = lint_mapping(mapping, operations_from_air(air))
            if errors:
                raise AnvilError(f"{name}: the mapping does not cover {path}: " + "; ".join(errors))
            self.mappings[name] = mapping
            self._digests[name] = content_key("anvil-contract", json.dumps(air, sort_keys=True, default=str))
        self._temporary: tempfile.TemporaryDirectory[str] | None = None
        if workdir is None:
            self._temporary = tempfile.TemporaryDirectory(prefix="worldloom-anvil-")
            workdir = self._temporary.name
        self.workdir = Path(workdir)
        self._records: dict[str, Path] = {}
        self._lock = threading.Lock()

    def identity(self) -> dict[str, Any]:
        """What a run records about its serving, so it is never compared with an in-process run unawares."""

        return {"connectors": "anvil", "contracts": dict(self._digests)}

    def _records_file(self, service: ConnectorEvaluationService, connector: str) -> Path:
        with self._lock:
            held = self._records.get(connector)
            if held is None:
                held = self.workdir / "_records" / f"{_safe(connector)}.json"
                held.parent.mkdir(parents=True, exist_ok=True)
                chosen = [_record_json(record) for record in service.records if _record_connector(record) == connector]
                held.write_text(json.dumps(chosen, sort_keys=True), encoding="utf-8")
                self._records[connector] = held
            return held

    def open(self, service: ConnectorEvaluationService, case: EvalCase, principal: str, run_id: str) -> AnvilCase:
        """Start one server per connector the case uses; refused if one has no contract."""

        row = service.rows[case.id]
        connectors = sorted({str(node["server"]) for node in row["expected_dag"]["nodes"]
                             if node.get("node_kind") != "transform"})
        missing = [name for name in connectors if name not in self.contracts]
        if missing:
            raise AnvilError(f"case {case.id} uses {', '.join(missing)}, which no --contract serves")
        directory = self.workdir / _safe(case.id)
        directory.mkdir(parents=True, exist_ok=True)
        order = directory / "order.jsonl"
        order.unlink(missing_ok=True)
        definitions = {name: service.definitions[name].model_dump(mode="json", by_alias=True) for name in connectors}
        served = AnvilCase(self, service, case, principal, run_id, order)
        try:
            for name in connectors:
                state = directory / f"{_safe(name)}.state.json"
                state.write_text(json.dumps({
                    "schema": STATE_SCHEMA, "connector": name, "principal": principal, "query_engine": "native",
                    "row": row, "records_file": str(self._records_file(service, name)), "definitions": definitions,
                }, sort_keys=True, default=str), encoding="utf-8")
                served.start(name, state, directory)
        except BaseException:
            served.stop()
            raise
        return served


class AnvilCase:
    """One case's servers: the surface the agent gets, then the replay that grades it."""

    def __init__(self, serving: AnvilServing, service: ConnectorEvaluationService, case: EvalCase, principal: str,
                 run_id: str, order: Path) -> None:
        self.serving = serving
        self.service = service
        self.case = case
        self.principal = principal
        self.run_id = run_id
        self.order = order
        self.base_urls: dict[str, str] = {}
        self.traces: dict[str, Path] = {}
        self._processes: dict[str, subprocess.Popen[str]] = {}
        self._logs: dict[str, Path] = {}

    @property
    def surface(self) -> AnvilToolSurface:
        return AnvilToolSurface(self.service, self.principal, self.run_id, base_urls=self.base_urls,
                                token=self.serving.token)

    def start(self, connector: str, state: Path, directory: Path) -> None:
        import worldloom

        trace = directory / f"{_safe(connector)}.calls.jsonl"
        trace.unlink(missing_ok=True)
        log = directory / f"{_safe(connector)}.serve.log"
        provider = shlex.join([self.serving.python, "-m", "worldloom.anvil_provider", "--state", str(state),
                               "--order-log", str(self.order)])
        env = dict(os.environ)
        source_root = str(Path(worldloom.__file__).resolve().parent.parent)
        env["PYTHONPATH"] = os.pathsep.join(part for part in (source_root, env.get("PYTHONPATH", "")) if part)
        argv = [*self.serving.command, "simulate", "serve", "--contract", str(self.serving.contracts[connector]),
                "--provider-cmd", provider, "--port", "0", "--trace", str(trace)]
        with log.open("w", encoding="utf-8") as handle:
            try:
                process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=handle, text=True, env=env)
            except OSError as error:
                raise AnvilError(f"{connector}: could not start {argv[0]}: {error}") from error
        self._processes[connector] = process
        self._logs[connector] = log
        self.traces[connector] = trace
        watchdog = threading.Timer(self.serving.startup_timeout, process.kill)
        watchdog.start()
        try:
            assert process.stdout is not None
            line = process.stdout.readline().strip()
        finally:
            watchdog.cancel()
        if not line.startswith("http"):
            process.kill()
            process.wait()
            tail = log.read_text(encoding="utf-8", errors="replace")[-2000:]
            raise AnvilError(f"{connector}: anvil simulate serve did not print its URL\n{tail}")
        self.base_urls[connector] = line

    def stop(self) -> None:
        """Stop every server: SIGTERM (Anvil shuts its provider down), then kill if it lingers."""

        for process in self._processes.values():
            if process.poll() is None:
                process.terminate()
        for process in self._processes.values():
            try:
                process.wait(timeout=15)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            if process.stdout is not None:
                process.stdout.close()

    def close(self) -> tuple[str, ...]:
        """Stop the servers, replay their traces into the run, and return what differed."""

        self.stop()
        return replay_traces(self.service, self.principal, self.run_id, self.traces, self.serving.mappings,
                             order=self.order)


def read_trace(path: Path) -> list[dict[str, Any]]:
    """Anvil's call trace: one JSON object per line (``anvil.simulator.trace/v1``)."""

    if not path.is_file():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def merge_traces(traces: Mapping[str, Sequence[Mapping[str, Any]]],
                 order: Sequence[tuple[str, str]]) -> list[tuple[str, Mapping[str, Any]]]:
    """Every connector's trace in one sequence: provider calls in the order the providers answered them.

    A call Anvil answered itself (it has no ``normalized`` request) keeps its
    place after the provider call that preceded it on the same server.
    """

    queues = {name: deque(entries) for name, entries in sorted(traces.items())}
    merged: list[tuple[str, Mapping[str, Any]]] = []
    for connector, request_id in order:
        queue = queues.get(connector)
        while queue:
            entry = queue.popleft()
            merged.append((connector, entry))
            if entry.get("normalized") is not None and entry.get("requestId") == request_id:
                break
    for connector in sorted(queues):
        merged.extend((connector, entry) for entry in queues[connector])
    return merged


def _order(path: Path | None) -> list[tuple[str, str]]:
    if path is None or not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            item = json.loads(line)
            out.append((str(item.get("connector")), str(item.get("requestId"))))
    return out


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _argument_names(entry: Mapping[str, Any]) -> list[str]:
    request = entry.get("request") or {}
    body = request.get("body")
    names = list(body) if isinstance(body, Mapping) else []
    names.extend(request.get("query") or {})
    return sorted(set(map(str, names)))


def replay_traces(service: ConnectorEvaluationService, principal: str, run_id: str, traces: Mapping[str, Path],
                  mappings: Mapping[str, AnvilMapping], *, order: Path | None = None) -> tuple[str, ...]:
    """Replay what Anvil served into the run's service; the notes name every call whose answer differed."""

    loaded = {name: read_trace(path) for name, path in sorted(traces.items())}
    notes: list[str] = []
    for connector, entry in merge_traces(loaded, _order(order)):
        normalized = entry.get("normalized")
        provider = entry.get("provider")
        label = f"{connector} seq {entry.get('seq')} ({entry.get('operationId')})"
        if normalized is None or (isinstance(provider, Mapping) and "transportError" in provider):
            error = (entry.get("result") or {}).get("error") or {}
            if isinstance(provider, Mapping) and "transportError" in provider:
                error = {"code": "upstream_unavailable", "message": str(provider["transportError"])}
            # Named as the connector tool the operation maps to, where it
            # maps to one, so a refused attempt counts against that tool.
            mapped = mappings[connector].entry(str(entry.get("operationId")))
            tool = mapped.tool if mapped is not None and mapped.tool else entry.get("tool")
            service.record_refusal(principal, run_id, f"{connector}.{tool}", _argument_names(entry),
                                   f"anvil_{error.get('code', 'refused')}: {error.get('message', '')}".rstrip())
            continue
        replayed = answer(mappings[connector], ServiceBackend(service, principal, run_id, connector), normalized)
        if not replayed.called:
            error = replayed.response.get("error") or {}
            service.record_refusal(principal, run_id, f"{connector}.{replayed.tool or entry.get('tool')}",
                                   _argument_names(entry), f"anvil_{error.get('code')}: {error.get('message', '')}")
        if provider is not None and _canonical(replayed.response) != _canonical(provider):
            notes.append(f"anvil_divergence: {label} answered differently on replay than it did to the agent")
    return tuple(notes)


__all__ = [
    "ANVIL_COMMAND_ENV",
    "DEFAULT_TOKEN",
    "AnvilCase",
    "AnvilError",
    "AnvilServing",
    "AnvilToolSurface",
    "anvil_environment",
    "contract_service",
    "find_anvil",
    "merge_traces",
    "read_trace",
    "replay_traces",
    "resolve_contracts",
]
