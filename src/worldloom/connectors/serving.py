"""Bounded, principal-scoped connector evaluation runs, with an optional MCP transport.

Corpus records are copied into a run. The transport never writes a corpus, and
only the server assigns trace spans and node attribution. Authentication and
protocol concurrency stay outside the deterministic generator.
"""
from __future__ import annotations

import copy
import hmac
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field, replace
from threading import RLock
from typing import Any

from ..connector_data import ConnectorRecord
from ..connector_definition import ConnectorDefinition, builtin_connector_definitions
from ..connector_emulator import ConnectorEmulator, ConnectorError, ConnectorSpan
from ..connector_trace import grade_trace

_READ_OPS = frozenset({"search", "get", "download"})
_MANAGEMENT_TOOLS = 6


class ServingError(ValueError):
    """An actionable refusal at the serving boundary."""


@dataclass(frozen=True)
class ServingLimits:
    max_runs: int = 32
    max_runs_per_principal: int = 4
    # High enough for a mapped reorganisation of a thousand records (one
    # search page per hundred, a write and a readback per record); a
    # run that needs more is a retry storm, which the trajectory grade
    # names on its own.
    max_calls_per_run: int = 4096
    max_tools: int = 100
    max_request_bytes: int = 65536
    max_response_bytes: int = 1048576
    max_records: int = 100000

    def __post_init__(self) -> None:
        if any(value < 1 for value in asdict(self).values()):
            raise ServingError("serving limits must be positive")
        if self.max_tools <= _MANAGEMENT_TOOLS:
            raise ServingError("max_tools must leave room for six evaluation tools")


@dataclass
class _Run:
    principal: str
    query_id: str
    emulators: dict[str, ConnectorEmulator]
    spans: list[ConnectorSpan] = field(default_factory=list)
    attempts: int = 0
    #: Calls the run did not admit (unknown tool, undeclared argument, a
    #: limit): no span exists for them, so they are kept here and graded as
    #: attempts. An agent that keeps probing the surface is not the same
    #: trajectory as one that did not.
    refusals: list[dict[str, Any]] = field(default_factory=list)
    #: Every record as it stood when the run began. `score` diffs the live
    #: state against it, so an external agent's outcomes are graded from what
    #: it changed, never from what it reported.
    before: dict[str, dict[str, Any]] = field(default_factory=dict)


class ConnectorEvaluationService:
    """Synchronous SDK for isolated runs over compiled eval rows.

    A principal is supplied by a trusted host, never by a tool argument. Run IDs
    are local monotonic handles, not credentials. HTTP binds them to the
    authenticated principal on every call, including trace and grade reads.
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]],
        records: Iterable[ConnectorRecord | Mapping[str, Any]],
        *,
        definitions: Mapping[str, ConnectorDefinition] | None = None,
        allowed_tools: Iterable[str] | None = None,
        limits: ServingLimits | None = None,
    ) -> None:
        limits = limits or ServingLimits()
        self.limits = limits
        materialized_rows = tuple(copy.deepcopy(dict(row)) for row in rows)
        self.rows = {str(row["id"]): row for row in materialized_rows}
        if not self.rows or any(not key for key in self.rows) or len(self.rows) != len(materialized_rows):
            raise ServingError("evaluation rows must have unique, nonempty IDs")
        self.records = tuple(copy.deepcopy(record) for record in records)
        if len(self.records) > limits.max_records:
            raise ServingError("record_limit: select a smaller evaluation corpus")
        available = builtin_connector_definitions()
        embedded: dict[str, ConnectorDefinition] = {}
        explicit = dict(definitions or {})
        for row in materialized_rows:
            for name, value in sorted(row.get("connector_definitions", {}).items()):
                definition = ConnectorDefinition.model_validate(value)
                if definition.connector != name:
                    raise ServingError(f"definition_name_mismatch: {name}")
                if name in embedded and embedded[name] != definition and name not in explicit:
                    raise ServingError(f"conflicting_row_definitions: {name}; provide one explicit definition")
                embedded[name] = definition
        available.update(embedded)
        available.update(explicit)
        required = sorted({str(node["server"]) for row in self.rows.values()
                           for node in row["expected_dag"]["nodes"] if node.get("node_kind") != "transform"})
        if set(required) - set(available):
            raise ServingError(f"unknown connectors: {sorted(set(required) - set(available))}")
        self.definitions = {name: available[name] for name in required}
        catalog = {f"{name}.{tool}": (name, tool)
                   for name, definition in self.definitions.items()
                   for tool in sorted(definition.tools)}
        selected = set(allowed_tools) if allowed_tools is not None else set(catalog)
        if selected - set(catalog):
            raise ServingError(f"unknown tools: {sorted(selected - set(catalog))}")
        if len(selected) + _MANAGEMENT_TOOLS > limits.max_tools:
            raise ServingError(f"tool_limit: {len(selected)} connector tools plus six evaluation tools; use --tool")
        self.tools = {name: catalog[name] for name in sorted(selected)}
        for row in self.rows.values():
            for node in row["expected_dag"]["nodes"]:
                if node.get("node_kind") == "transform":
                    continue
                name = f"{node['server']}.{node['tool']}"
                if name not in self.tools:
                    raise ServingError(f"required_tool_disabled: query {row['id']} needs {name}")
        self._runs: dict[str, _Run] = {}
        self._ordinal = 0
        self._lock = RLock()

    @classmethod
    def from_corpus(cls, corpus: Any, **options: Any) -> ConnectorEvaluationService:
        """Compile an EnterpriseCorpus, refusing any unexecutable row."""
        from ..enterprise_corpus import validate_corpus
        from ..enterprise_rows import compile_row, runtime_records

        findings = validate_corpus(corpus)
        if findings:
            raise ServingError(f"invalid_corpus: {len(findings)} findings; " + "; ".join(findings[:3]))
        fixtures = {fixture.query_id: fixture for fixture in corpus.fixtures}
        records = runtime_records(corpus.connector_data.records)
        rows = [
            {**compile_row(query, fixtures[query.id], records,
                           definitions=options.get("definitions")), "query": query.query}
            for query in corpus.queries
        ]
        return cls(rows, corpus.connector_data.records, **options)

    def list_queries(self, *, offset: int = 0, limit: int = 50) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ServingError("query_page: offset >= 0 and 1 <= limit <= 100 required")
        ids = sorted(self.rows)
        return {"queries": [{"query_id": key, "query": self.rows[key].get("query", "")}
                            for key in ids[offset:offset + limit]],
                "next_offset": offset + limit if offset + limit < len(ids) else None}

    def begin(self, principal: str, query_id: str) -> dict[str, Any]:
        if not principal:
            raise ServingError("principal_required")
        with self._lock:
            if query_id not in self.rows:
                raise ServingError(f"unknown_query: {query_id}")
            if len(self._runs) >= self.limits.max_runs:
                raise ServingError("run_limit: end a run before starting another")
            if sum(run.principal == principal for run in self._runs.values()) >= self.limits.max_runs_per_principal:
                raise ServingError("principal_run_limit: end a run before starting another")
            row = self.rows[query_id]
            servers = sorted({str(node["server"]) for node in row["expected_dag"]["nodes"] if node.get("node_kind") != "transform"})
            emulators = {server: self._emulator(server, row, principal) for server in servers}
            self._ordinal += 1
            run_id = f"run-{self._ordinal}"
            before = {fid: copy.deepcopy(dict(record)) for server in sorted(emulators)
                      for fid, record in sorted(emulators[server].records.items())}
            self._runs[run_id] = _Run(principal, query_id, emulators, before=before)
            return {"run_id": run_id, "query_id": query_id, "query": row.get("query", ""),
                    "max_calls": self.limits.max_calls_per_run}

    def _emulator(self, server: str, row: Mapping[str, Any], principal: str) -> ConnectorEmulator:
        if row.get("state_overrides"):
            from ..enterprise_failures import build_query_emulator
            from ..enterprise_rows import runtime_records

            emulator = build_query_emulator(self.definitions[server], runtime_records(self.records),
                                        overrides=row["state_overrides"],
                                        mutation_nodes=row["expected_dag"]["nodes"],
                                        query_id=str(row["id"]))
            emulator.actor = principal
            return emulator
        return ConnectorEmulator(self.definitions[server], self.records, actor=principal)

    def _run(self, principal: str, run_id: str) -> _Run:
        run = self._runs.get(run_id)
        if run is None or run.principal != principal:
            # Do not disclose whether another principal owns this handle.
            raise ServingError("unknown_run: start a run with eval_begin")
        return run

    def _node(self, run: _Run, name: str, args: Mapping[str, Any]) -> str | None:
        """Attribute observed tools/targets; never accept an agent's node label."""
        completed = {span.node for span in run.spans if not span.error}
        connector, tool = self.tools[name]
        emulator = run.emulators[connector]
        reference = args.get("id")
        fid = emulator.by_ident.get(str(reference), str(reference)) if reference is not None else None
        nodes = self.rows[run.query_id]["expected_dag"]["nodes"]
        op = self.definitions[connector].tool(tool).op
        if op == "search" and int(args.get("start_at", 0)) > 0:
            for prior in reversed(run.spans):
                if prior.tool != name or prior.error or not prior.node:
                    continue
                selectors = ("query", "predicate", "entity", "name", "fields")
                if any(prior.args.get(key) != args.get(key) for key in selectors):
                    continue
                if int(args["start_at"]) == int(prior.args.get("start_at", 0)) + prior.items:
                    return prior.node
        for node in nodes:
            if f"{node['server']}.{node['tool']}" != name:
                continue
            if str(node["id"]) in completed and not node.get("for_each"):
                continue
            parents = {str(source) for source, target in self.rows[run.query_id]["expected_dag"].get("edges", ())
                       if str(target) == str(node["id"])}
            if node.get("for_each"):
                members = {record for span in run.spans if span.node in parents and not span.error
                           for record in (*span.reads, *span.writes)}
                already_written = {written for span in run.spans if span.node == str(node["id"]) and not span.error
                                   for written in span.writes}
                if fid not in members or fid in already_written:
                    continue
            elif node.get("fixture") and op != "search":
                if str(node["fixture"]) != fid:
                    continue
            if not node.get("fixture") and op in {"get", "download"}:
                produced = {written for span in run.spans if span.node in parents and not span.error
                            for written in span.writes}
                if parents and (not produced or fid not in produced):
                    continue
            if args.get("entity") and node.get("entity") != args["entity"]:
                continue
            return str(node["id"])
        return None

    def _grammar_attribution(
        self, run: _Run, name: str, arguments: Mapping[str, Any],
    ) -> tuple[str | None, tuple[str, ...]]:
        from ..enterprise_dag import condition_matches
        from ..enterprise_dag_rows import program_for
        from ..enterprise_dag_runtime import bound_arguments, observed_flow

        row = self.rows[run.query_id]
        program = program_for(row)
        outputs, producers = observed_flow(row, run.spans)
        wire = {node["id"]: node for node in row["expected_dag"]["nodes"]}
        connector, tool = self.tools[name]
        declared = self.definitions[connector].tool(tool)
        emulator = run.emulators[connector]
        for node in program.nodes:
            if node.kind == "transform" or f"{node.connector}.{wire[node.id]['tool']}" != name:
                continue
            if any(parent not in outputs for parent in node.depends_on):
                continue
            if node.condition and (node.condition.reference.node not in outputs or
                                   not condition_matches(node.condition, outputs)):
                continue
            prior = [span for span in run.spans if span.node == node.id and not span.error]
            items = outputs.get(node.for_each.node, [])[:node.for_each.limit] if node.for_each else [None]
            index = len(prior) if node.operation != "search" else 0
            if index >= len(items):
                continue
            try:
                wanted = bound_arguments(node, outputs, items[index])
            except ValueError:
                continue
            if node.operation in {"search", "create", "send", "post", "upload"} and "entity" in declared.params:
                # Only when the tool declares it. `call` refuses an undeclared
                # argument before reaching here, so demanding `entity` of a
                # tool without one (email's `search_threads`) made every such
                # node unattributable through the very surface it is served on.
                wanted["entity"] = node.entity
            actual = dict(arguments)
            if node.operation == "search" and prior:
                next_offset = int(prior[-1].args.get("start_at", 0)) + prior[-1].items
                if int(actual.get("start_at", 0)) != next_offset or not prior[-1].items:
                    continue
            for key in ("start_at", "max_results"):
                if node.operation == "search":
                    wanted.pop(key, None)
                    actual.pop(key, None)
            if wanted.get("id") is not None:
                wanted["id"] = emulator.by_ident.get(str(wanted["id"]), str(wanted["id"]))
                raw = str(actual.get("id"))
                # The emulator forgets a deleted record's native id; the
                # readback the agent took it from is still in the run's
                # recorded results, so the readback after a delete attributes.
                actual["id"] = emulator.by_ident.get(raw, _recorded_aliases(outputs).get(raw, raw))
            if any(actual.get(key) != value for key, value in wanted.items()):
                continue
            consumed = tuple(dict.fromkeys(identifier for parent in node.depends_on
                                           for identifier in producers.get(parent, ())))
            return node.id, consumed
        return None, self._consumed(run, arguments)

    def _consumed(self, run: _Run, arguments: Mapping[str, Any]) -> tuple[str, ...]:
        def references(value: Any) -> set[str]:
            if isinstance(value, Mapping):
                return {found for key in sorted(value) for found in references(value[key])}
            if isinstance(value, (list, tuple)):
                return {found for item in value for found in references(item)}
            if isinstance(value, str):
                return {emulator.by_ident.get(value, value) for emulator in run.emulators.values()}
            return set()

        unresolved = references(arguments)
        consumed: list[str] = []
        for span in reversed(run.spans):
            if span.error:
                continue
            produced = set((*span.reads, *span.writes)) & unresolved
            if produced:
                consumed.append(span.id)
                unresolved -= produced
        return tuple(reversed(consumed))

    def call(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        with self._lock:
            run = self._run(principal, run_id)

            def refuse(message: str) -> ServingError:
                run.refusals.append({"tool": name, "arguments": sorted(str(key) for key in arguments), "error": message})
                return ServingError(message)

            if name not in self.tools:
                raise refuse(f"tool_not_allowed: {name}")
            connector, tool = self.tools[name]
            if connector not in run.emulators:
                raise refuse(f"connector_not_in_query: {connector}")
            if run.attempts >= self.limits.max_calls_per_run:
                raise refuse("call_limit: retrieve the trace and end this run")
            run.attempts += 1
            supplied = dict(arguments)
            declared = self.definitions[connector].tool(tool)
            unknown = set(supplied) - set(declared.params)
            if unknown:
                raise refuse(f"unknown_arguments: {sorted(unknown)}")
            if len(json.dumps(supplied, sort_keys=True, allow_nan=False).encode()) > self.limits.max_request_bytes:
                raise refuse("request_limit: reduce the tool arguments")
            if self.rows[run.query_id].get("grammar") == "enterprise-dag@1":
                node, consumed = self._grammar_attribution(run, name, supplied)
            else:
                node, consumed = self._node(run, name, supplied), self._consumed(run, supplied)
            # An oversized result must not commit a write the client never saw.
            # Copy the bounded emulator transaction; publish it only on success.
            trial = copy.deepcopy(run.emulators[connector])
            error: ConnectorError | None = None
            rollback = False
            result: Any = None
            try:
                result = trial.call(tool, _node=node, _consumed=consumed, **supplied)
                if len(json.dumps(result, sort_keys=True, allow_nan=False).encode()) > self.limits.max_response_bytes:
                    error = ConnectorError(413, "response_limit: request fewer fields or results", "response_limit")
                    rollback = True
            except ConnectorError as caught:
                error = caught
            except (TypeError, ValueError) as caught:
                error = ConnectorError(400, str(caught), "validation")
                rollback = True
            local = trial.trace[-1]
            span = replace(local, id=f"s{len(run.spans) + 1}", ordinal=len(run.spans) + 1,
                           actor=principal)
            if error is not None:
                span = replace(span, error={"code": error.code, "kind": error.kind, "message": error.message})
            if rollback:
                span = replace(span, reads=(), writes=(), items=0, bytes=0)
            else:
                run.emulators[connector] = trial
            if error is None:
                from ..connector_results import record_connector_result

                span = record_connector_result(span, result)
            run.spans.append(span)
            if error is not None:
                raise error
            return result

    def trace(self, principal: str, run_id: str, *, offset: int = 0, limit: int = 100) -> dict[str, Any]:
        if offset < 0 or not 1 <= limit <= 100:
            raise ServingError("trace_page: offset >= 0 and 1 <= limit <= 100 required")
        with self._lock:
            run = self._run(principal, run_id)
            # One receipt can contain a full bounded result plus its bounded
            # request. Reserve framing room, and stop the page before a second
            # receipt would turn a 100-span page into a 100 MiB response.
            budget = self.limits.max_response_bytes + self.limits.max_request_bytes + 16384
            selected: list[dict[str, Any]] = []
            size = 0
            for span in run.spans[offset:offset + limit]:
                item = asdict(span)
                item_bytes = len(json.dumps(item, sort_keys=True, allow_nan=False).encode())
                if size + item_bytes > budget:
                    if not selected:
                        raise ServingError("trace_span_limit: a span exceeds the trace page budget")
                    break
                selected.append(item)
                size += item_bytes
            next_offset = offset + len(selected)
            return {"schema": "worldloom.connector-trace/v1", "run_id": run_id, "query_id": run.query_id,
                    "spans": selected,
                    "next_offset": next_offset if next_offset < len(run.spans) else None,
                    "attempts": run.attempts}

    def spans(self, principal: str, run_id: str) -> tuple[ConnectorSpan, ...]:
        """Every span of a run, unpaged. The SDK path for a trusted embedding.

        `trace` is the wire: paged and byte-bounded because it answers an
        external client. A grader running in the same process wants the
        whole thing once, and paging it back through the wire budget only
        adds a place to lose a span.
        """
        with self._lock:
            return tuple(self._run(principal, run_id).spans)

    def refusals(self, principal: str, run_id: str) -> tuple[dict[str, Any], ...]:
        """Every call this run refused before a span could exist, in order."""
        with self._lock:
            return tuple(dict(item) for item in self._run(principal, run_id).refusals)

    def snapshot(self, principal: str, run_id: str) -> dict[str, dict[str, Any]]:
        """The run's connector state, every record by fid, copied.

        Taken at `begin` and again after the agent finishes, the two snapshots
        are the outcome axis: created is in the second and not the first,
        deleted the reverse, updated is the same fid with different fields.
        Copied, so a caller holding the pre-state cannot watch it change.
        """
        with self._lock:
            run = self._run(principal, run_id)
            return {fid: copy.deepcopy(dict(record)) for server in sorted(run.emulators)
                    for fid, record in sorted(run.emulators[server].records.items())}

    def tool_catalog(self, principal: str, run_id: str) -> tuple[dict[str, Any], ...]:
        """The tools this run may call, with parameters and safety annotations.

        The `tools/list` an MCP client would see, minus the five evaluation
        tools: only connectors the query names, each with the read-only,
        destructive and idempotent hints the same classification derives.
        """
        from ..evalrun.safety import classify_tool, tool_annotations

        with self._lock:
            run = self._run(principal, run_id)
            out = []
            for name in sorted(self.tools):
                connector, tool = self.tools[name]
                if connector not in run.emulators:
                    continue
                declared = self.definitions[connector].tool(tool)
                safety = classify_tool(connector, tool, declared)
                out.append({"name": name, "op": declared.op, "entities": list(declared.entities),
                            "params": dict(declared.params), "annotations": tool_annotations(safety),
                            "risk": safety.risk.value, "idempotency": safety.idempotency.value})
            return tuple(out)

    def score(self, principal: str, run_id: str, *, answer: str = "",
              artifacts: Iterable[Mapping[str, Any]] = (), planned_dag: Mapping[str, Any] | None = None,
              rater: Any = None) -> dict[str, Any]:
        """Grade this run on the three axes: the plan, the trajectory, the outcomes.

        `grade` decides the row's assertions; this adds the per-axis grades
        `worldloom.evalrun` computes over the same spans, the snapshot taken at
        `begin`, and the live state now. The agent may hand over its final
        answer, the artifacts it produced (name, text, the record ids it
        cites) and the DAG it says it planned; all three are graded only
        against what was observed. The result is a `CaseResult` document, so
        a served run lands in the same ledger as a local one
        (`worldloom evalrun import-served`). The run stays open.
        """
        from ..evalrun.agents import AgentResponse, ProducedArtifact
        from ..evalrun.contract import case_from_row
        from ..evalrun.runner import CaseResult, grade_run, safety_for

        with self._lock:
            run = self._run(principal, run_id)
            row = self.rows[run.query_id]
            case = case_from_row(row, query=str(row.get("query") or f"case {row['id']}"), principal=principal)
            produced = tuple(
                ProducedArtifact(name=str(item.get("name") or f"artifact-{index}"),
                                 media_type=str(item.get("media_type") or "text/plain"),
                                 text=str(item.get("text") or ""),
                                 cites=tuple(str(value) for value in item.get("cites", ())))
                for index, item in enumerate(artifacts)
            )
            response = AgentResponse(answer=answer, artifacts=produced,
                                     planned_dag=dict(planned_dag) if planned_dag else None)
            spans = tuple(run.spans)
            refusals = tuple(dict(item) for item in run.refusals)
            after = {fid: copy.deepcopy(dict(record)) for server in sorted(run.emulators)
                     for fid, record in sorted(run.emulators[server].records.items())}
            assertions = self.grade(principal, run_id)
            score = grade_run(case, spans, run.before, after, assertions, response,
                              definitions=self.definitions, rater=rater, safety=safety_for(self.definitions),
                              refusals=refusals)
            result = CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                                agent=f"served:{principal}", status="graded", score=score, answer=answer,
                                calls=len(spans), spans=tuple(_span_json(span) for span in spans),
                                refused=len(refusals), refusals=refusals)
            return result.model_dump(mode="json")

    def grade(self, principal: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            run = self._run(principal, run_id)
            post_state = {fid: record for server in sorted(run.emulators)
                          for fid, record in sorted(run.emulators[server].records.items())}
            behaviors = set()
            for span in run.spans:
                if span.error:
                    code, kind = span.error.get("code"), span.error.get("kind")
                    behaviors.add("denial_surfaced" if code == 403 else
                                  "report_not_found" if code == 404 or kind == "not_found" else
                                  "branch_failed" if kind in {"timeout", "rate_limit"} else "validation_error")
            return dict(grade_trace(run.spans, self.rows[run.query_id], post_state=post_state,
                                   behaviors=sorted(behaviors)))

    def end(self, principal: str, run_id: str) -> dict[str, Any]:
        with self._lock:
            grade = self.grade(principal, run_id)
            del self._runs[run_id]
            return {"run_id": run_id, "ended": True, "grade": grade}


def _recorded_aliases(outputs: Mapping[str, Sequence[Any]]) -> dict[str, str]:
    """Native identifiers in recorded results, mapped to the fid each answered for."""
    aliases: dict[str, str] = {}
    for produced in outputs.values():
        for entry in produced:
            if isinstance(entry, Mapping) and isinstance(entry.get("payload"), Mapping):
                native = entry["payload"]
                for key in ("id", "Id", "sys_id", "key", "number", "name", "title"):
                    if native.get(key) is not None:
                        aliases.setdefault(str(native[key]), str(entry.get("id")))
    return aliases


def _span_json(span: ConnectorSpan) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(span), sort_keys=True, default=str))


class _AccessBoundary:
    """Synchronous ASGI routing; the SDK owns coroutine execution and IO."""

    def __init__(self, app: Any, *, bearer_tokens: Mapping[str, str]) -> None:
        self.app = app
        self.tokens = tuple(sorted(bearer_tokens.items()))

    def __call__(self, scope: Any, receive: Any, send: Any) -> Any:
        if scope["type"] != "http":
            return self.app(scope, receive, send)
        principal = "local"
        if self.tokens:
            headers = dict(scope["headers"])
            authorization = headers.get(b"authorization", b"").decode("latin-1")
            token = authorization[7:] if authorization[:7].lower() == "bearer " else ""
            principal = next((name for name, secret in self.tokens
                              if hmac.compare_digest(token.encode(), secret.encode())), "")
            if not principal:
                from starlette.responses import JSONResponse

                response = JSONResponse({"error": "unauthorized"}, status_code=401,
                                        headers={"WWW-Authenticate": "Bearer"})
                return response(scope, receive, send)
        scope["worldloom.principal"] = principal
        return self.app(scope, receive, send)


def create_connector_app(
    service: ConnectorEvaluationService,
    *,
    host: str = "127.0.0.1",
    bearer_tokens: Mapping[str, str] | None = None,
    allowed_hosts: Iterable[str] = (),
) -> Any:
    """Build a StreamableHTTP ASGI app; run with one worker or sticky routing.

    ``bearer_tokens`` maps principal names to secrets. A host outside loopback
    requires authentication. TLS is terminated by the deployment's proxy.
    """
    try:
        from mcp.server import MCPServer
        from mcp.server.mcpserver.exceptions import ToolError
        from mcp.server.mcpserver.tools import Tool
        from mcp.server.mcpserver.utilities.func_metadata import (
            ArgModelBase,
            FuncMetadata,
        )
        from mcp.server.transport_security import TransportSecuritySettings
        from mcp.types import ToolAnnotations
        from pydantic import ConfigDict, create_model
    except ImportError as error:
        raise ServingError("install `pip install 'worldloom[mcp]'` (MCP SDK >=2.2,<3)") from error
    tokens = dict(bearer_tokens or {})
    if any(not name or len(secret) < 24 for name, secret in tokens.items()):
        raise ServingError("bearer_tokens need named principals and secrets of at least 24 characters")
    if len(set(tokens.values())) != len(tokens):
        raise ServingError("bearer_tokens must be unique per principal")
    if host not in {"127.0.0.1", "localhost", "::1"} and not tokens:
        raise ServingError("authentication_required: public binds need bearer tokens")

    class Arguments(ArgModelBase):
        model_config = ConfigDict(extra="forbid", strict=True)

    def register(name: str, params: Mapping[str, tuple[Any, Any]], operation: Any,
                 description: str, read_only: bool) -> Any:
        field_definitions: dict[str, Any] = dict(params)
        model = create_model(name.replace(".", "_") + "Args", __base__=Arguments, **field_definitions)

        def invoke(ctx: Any, **arguments: Any) -> Any:
            request = ctx.request_context.request
            principal = request.scope["worldloom.principal"]
            try:
                return operation(principal, {key: value for key, value in arguments.items() if value is not None})
            except (ServingError, ConnectorError) as error:
                raise ToolError(str(error)) from error

        return Tool(name=name, title=None, description=description, fn=invoke, is_async=False,
                    context_kwarg="ctx", parameters=model.model_json_schema(),
                    fn_metadata=FuncMetadata(arg_model=model),
                    annotations=ToolAnnotations(read_only_hint=read_only,
                                                destructive_hint=not read_only,
                                                open_world_hint=False))

    tools = [
        register("eval_list", {"offset": (int, 0), "limit": (int, 50)},
                 lambda principal, args: service.list_queries(**args), "List available evaluation questions.", True),
        register("eval_begin", {"query_id": (str, ...)},
                 lambda principal, args: service.begin(principal, **args), "Begin an isolated evaluation. Keep the returned run_id for connector calls.", False),
        register("eval_trace", {"run_id": (str, ...), "offset": (int, 0), "limit": (int, 100)},
                 lambda principal, args: service.trace(principal, **args), "Read this run's observed tool spans. Follow next_offset for more.", True),
        register("eval_grade", {"run_id": (str, ...)},
                 lambda principal, args: service.grade(principal, **args), "Grade observed calls and actual record state against the evaluation.", True),
        register("eval_score", {"run_id": (str, ...), "answer": (str | None, None),
                                "artifacts": (list[dict[str, Any]] | None, None),
                                "planned_dag": (dict[str, Any] | None, None)},
                 lambda principal, args: service.score(principal, args.pop("run_id"), **args),
                 "Grade this run on three axes (plan, trajectory, outcomes) as a worldloom.eval-run case result. "
                 "Optionally hand over your final answer, the artifacts you produced ({name, text, cites}) and the "
                 "DAG you planned; they are graded only against what was observed. The run stays open.", True),
        register("eval_end", {"run_id": (str, ...)},
                 lambda principal, args: service.end(principal, **args), "Grade and release this run. Retrieve the trace before ending.", False),
    ]
    param_types: dict[str, Any] = {"string": str, "int": int, "integer": int,
                                 "number": float, "bool": bool, "boolean": bool,
                                 "object": dict[str, Any], "array": list[Any]}
    for name, (connector, tool_name) in service.tools.items():
        definition = service.definitions[connector]
        tool = definition.tool(tool_name)
        params: dict[str, tuple[Any, Any]] = {"run_id": (str, ...)}
        for key, declared in sorted(tool.params.items()):
            kind = param_types.get(declared.rstrip("?"))
            if kind is None:
                raise ServingError(f"unsupported parameter type: {name}.{key}={declared}")
            params[key] = (kind | None, None) if declared.endswith("?") else (kind, ...)

        def operation(principal: str, args: dict[str, Any], name: str = name) -> Any:
            return service.call(principal, args.pop("run_id"), name, args)

        tools.append(register(name, params, operation,
                              f"{definition.vendor_product}: {tool.op} {', '.join(tool.entities)}. "
                              "Acts only in the named evaluation run.", tool.op in _READ_OPS))
    server = MCPServer("worldloom-connectors", tools=tools)
    public_hosts = tuple(allowed_hosts)
    security = TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1", "localhost", "[::1]", "127.0.0.1:*", "localhost:*", "[::1]:*", *public_hosts],
        allowed_origins=["http://127.0.0.1:*", "http://localhost:*", "http://[::1]:*"],
    )
    app = server.streamable_http_app(
        stateless_http=True, json_response=True, host=host,
        max_request_body_size=service.limits.max_request_bytes,
        transport_security=security,
    )
    app.add_middleware(_AccessBoundary, bearer_tokens=tokens)
    return app


__all__ = ["ConnectorEvaluationService", "ServingError", "ServingLimits", "create_connector_app"]
