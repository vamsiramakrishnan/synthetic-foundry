"""Bounded, principal-scoped connector evaluation runs, with an optional MCP transport.

Corpus records are copied into a run. The transport never writes a corpus, and
only the server assigns trace spans and node attribution. Authentication and
protocol concurrency stay outside the deterministic generator.
"""
from __future__ import annotations

import copy
import hashlib
import hmac
import json
import os
import warnings
from collections.abc import Iterable, Iterator, Mapping, Sequence
from contextlib import contextmanager, nullcontext
from dataclasses import asdict, dataclass, field, replace
from threading import RLock
from typing import Any

from .. import packkit
from ..connector_data import ConnectorRecord
from ..connector_definition import ConnectorDefinition, builtin_connector_definitions
from ..connector_emulator import (
    QUERY_ENGINES,
    ConnectorEmulator,
    ConnectorError,
    ConnectorSpan,
)
from ..connector_keys import RECORDED_ALIAS_KEYS
from ..connector_trace import grade_trace
from .run_store import RunStore, RunStoreError, RunStoreWarning

_READ_OPS = frozenset({"search", "get", "download"})
_MANAGEMENT_TOOLS = 6


class ServingError(ValueError):
    """An actionable refusal at the serving boundary."""


def _limit(name: str) -> int:
    return int(packkit.policy(f"connectors.serving.{name}"))


@dataclass(frozen=True)
class ServingLimits:
    """What one serving process admits. Each default is the policy ``connectors.serving.<field>``."""

    max_runs: int = field(default_factory=lambda: _limit("max_runs"))
    max_runs_per_principal: int = field(default_factory=lambda: _limit("max_runs_per_principal"))
    # High enough for a mapped reorganisation of a thousand records (one
    # search page per hundred, a write and a readback per record); a
    # run that needs more is a retry storm, which the trajectory grade
    # names on its own.
    max_calls_per_run: int = field(default_factory=lambda: _limit("max_calls_per_run"))
    max_tools: int = field(default_factory=lambda: _limit("max_tools"))
    max_request_bytes: int = field(default_factory=lambda: _limit("max_request_bytes"))
    max_response_bytes: int = field(default_factory=lambda: _limit("max_response_bytes"))
    max_records: int = field(default_factory=lambda: _limit("max_records"))

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
    #: Evaluator-owned delivery receipts. They are deliberately separate from
    #: the spans an agent can inspect: the intent and missing dimensions are
    #: a private grading contract, not a search hint.
    retrieval_receipts: dict[str, dict[str, Any]] = field(default_factory=dict)
    attempts: int = 0
    #: Calls the run did not admit (unknown tool, undeclared argument, a
    #: limit): no span exists for them, so they are kept here and graded as
    #: attempts. An agent that keeps probing the surface is not the same
    #: trajectory as one that did not.
    refusals: list[dict[str, Any]] = field(default_factory=list)
    #: Ordinals of spans attributed to a node by shape rather than by the
    #: reference's own arguments; `call` keeps such an attribution only when
    #: the call bore it out.
    structural: set[int] = field(default_factory=set)
    #: Every record as it stood when the run began. `score` diffs the live
    #: state against it, so an external agent's outcomes are graded from what
    #: it changed, never from what it reported.
    before: dict[str, dict[str, Any]] = field(default_factory=dict)
    #: The questions the agent asked the user, in order, each with the
    #: number of spans recorded before it and the reply it was given. A
    #: question is a turn: recorded here, never claimed by the agent.
    questions: list[dict[str, Any]] = field(default_factory=list)
    #: The records planned calls addressed, by ``(connector, reference)``, as
    #: they stood when last seen: a readback after a delete addresses a record
    #: the state no longer holds, and its request still names the record's
    #: coordinates (a Graph drive), as the client that deleted it knew them.
    addressed: dict[tuple[str, str], dict[str, Any]] = field(default_factory=dict)
    #: Serialises everything that reads or changes this run. Runs share
    #: nothing but the read-only rows, definitions and base emulators, so each
    #: takes its own lock and a slow agent on one run never waits on a call
    #: made in another.
    lock: RLock = field(default_factory=RLock, repr=False, compare=False)
    #: Set by `end` under the run's lock. A call that looked the run up before
    #: `end` released it, and waited on the lock meanwhile, is refused rather
    #: than acting on a released fork.
    ended: bool = False
    #: The ordinal its id was minted from, so a listing orders runs as they began.
    ordinal: int = 0
    #: How deep the journalled entry points are nested on this run (`call`
    #: reaches `call_connector`; both are entry points). Only the outermost
    #: is journalled: replaying it makes the inner calls again. It is read
    #: and changed only under the run's lock, which nested calls already hold.
    journal_depth: int = 0


def _row_digest(row: Mapping[str, Any]) -> str:
    """What a journalled run was begun against; a reload refuses to replay it against anything else."""
    text = json.dumps(row, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _resolve_surfaces(choice: Any, connectors: Sequence[str]) -> Any:
    """The service's contract surfaces, or ``None`` for the connector definitions' own tools."""
    from .surface import SurfaceError, resolve_surfaces

    try:
        return resolve_surfaces(choice, connectors)
    except SurfaceError as error:
        raise ServingError(str(error)) from error


class _RunBackend:
    """A run's connector state as a mapping backend, remembering the connector call the mapping made.

    The contract surface dispatches through it: the tool the mapping chooses
    runs as that connector tool in the run (a span, graded), and a caller
    that asked for the connector call (the reference carrying a gold node)
    gets its result or its error back as the tool gave it.
    """

    def __init__(self, service: ConnectorEvaluationService, principal: str, run_id: str, connector: str) -> None:
        self.service = service
        self.principal = principal
        self.run_id = run_id
        self.connector = connector
        self.result: Any = None
        self.error: ConnectorError | None = None
        self.called = False

    @property
    def definition(self) -> ConnectorDefinition:
        return self.service.definitions[self.connector]

    def call(self, tool: str, args: Mapping[str, Any]) -> Any:
        self.called = True
        try:
            self.result = self.service.call_connector(self.principal, self.run_id, f"{self.connector}.{tool}", args)
        except ConnectorError as error:
            self.error = error
            raise
        return self.result

    def record(self, reference: Any) -> Mapping[str, Any] | None:
        return self.service.lookup(self.principal, self.run_id, self.connector, reference)

    def snapshot(self) -> dict[str, dict[str, Any]]:
        return self.service.snapshot(self.principal, self.run_id)


def _entities_meet(definition: ConnectorDefinition, node_entity: str, asked: str) -> bool:
    """Whether a call's ``entity`` names the node's entity, either way round an alias.

    An entity the connector does not declare meets nothing. It used to raise
    ``KeyError`` out of attribution, which crashed the agent's turn on a call
    the emulator answers with its own ``Unknown entity`` validation error: an
    agent that guessed a plural table name (``incidents``) lost the case to a
    grader exception instead of seeing the vendor's refusal.
    """
    for requested, actual in ((node_entity, asked), (asked, node_entity)):
        try:
            if definition.entity_matches(requested, actual):
                return True
        except KeyError:
            continue
    return False


class ConnectorEvaluationService:
    """Synchronous SDK for isolated runs over compiled eval rows.

    A principal is supplied by a trusted host, never by a tool argument. Run IDs
    are local monotonic handles, not credentials. HTTP binds them to the
    authenticated principal on every call, including trace and grade reads.

    Safe to share between threads, and concurrent across runs. The registry
    (begin, end, the ordinal, the lazily built bases) is guarded by the
    service lock; every read of a run and every call into it by that run's own
    lock. Two runs proceed in parallel; one run's calls stay strictly ordered.
    ``run_prefix`` is prepended to every run id (``w3-run-1``) so ids minted
    by different processes serving the same rows never collide; without one
    the ids are the plain ``run-<n>`` they always were. ``query_engine``
    runs every run's searches under that engine (``connector_emulator``'s
    ``predicate`` or ``native``); unset, the policy
    ``connectors.query.engine`` decides, as it always has.

    ``run_store`` names an append-only JSONL journal (``connectors.run_store``)
    that makes runs durable: every begin, every call, question and recorded
    refusal, and every end with its grade is written and fsynced before the
    entry point returns. A service constructed on an existing journal
    replays the open runs' calls (the service is deterministic, so they leave
    the same spans, records and grades) and keeps the ended runs' grades for
    `list_runs`. Unset, runs live in memory only and `end` forgets them, as
    they always have.
    """

    def __init__(
        self,
        rows: Iterable[Mapping[str, Any]],
        records: Iterable[ConnectorRecord | Mapping[str, Any]],
        *,
        definitions: Mapping[str, ConnectorDefinition] | None = None,
        allowed_tools: Iterable[str] | None = None,
        limits: ServingLimits | None = None,
        run_prefix: str = "",
        query_engine: str | None = None,
        surface: Any = None,
        run_store: str | os.PathLike[str] | None = None,
    ) -> None:
        if query_engine is not None and query_engine not in QUERY_ENGINES:
            raise ServingError(f"query_engine: one of {', '.join(QUERY_ENGINES)}")
        self.query_engine = query_engine
        if run_prefix and not all(char.isalnum() or char in "-_." for char in run_prefix):
            raise ServingError("run_prefix: letters, digits, '-', '_' and '.' only")
        self.run_prefix = run_prefix
        limits = limits or ServingLimits()
        self.limits = limits
        materialized_rows = tuple(copy.deepcopy(dict(row)) for row in rows)
        self.rows = {str(row["id"]): row for row in materialized_rows}
        if not self.rows or any(not key for key in self.rows) or len(self.rows) != len(materialized_rows):
            raise ServingError("evaluation rows must have unique, nonempty IDs")
        self.records = tuple(copy.deepcopy(record) for record in records)
        self._bases: dict[str, ConnectorEmulator] = {}
        self._runtime_records: tuple[dict[str, Any], ...] | None = None
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
        self.surfaces = _resolve_surfaces(surface, sorted(self.definitions))
        #: ``native`` (the connector definitions' tools) or ``contract`` (Anvil's projection of each contract).
        self.surface = "contract" if self.surfaces is not None else "native"
        #: Contract tool name to its connector and tool, for connectors served on their contract.
        self.contract_tools: dict[str, tuple[str, Any]] = {}
        if self.surfaces is not None:
            for connector in self.surfaces.connectors:
                for item in self.surfaces.surfaces[connector].tools:
                    self.contract_tools[item.name] = (connector, item)
            # One MCP process lists every connector's tools; a contract lists
            # more than a hand-written definition, so the limit is held per
            # query, against the tools one run is actually shown.
            for row in materialized_rows:
                servers = {str(node["server"]) for node in row["expected_dag"]["nodes"] if node.get("node_kind") != "transform"}
                shown = sum(len(self.surfaces.surfaces[name].tools) if name in self.surfaces.surfaces
                            else sum(1 for tool in selected if catalog[tool][0] == name) for name in servers)
                if shown + _MANAGEMENT_TOOLS > limits.max_tools:
                    raise ServingError(f"tool_limit: query {row['id']} is shown {shown} contract and connector tools "
                                       "plus six evaluation tools; raise connectors.serving.max_tools")
        elif len(selected) + _MANAGEMENT_TOOLS > limits.max_tools:
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
        self._retrieval_contracts: dict[str, Any] = {}
        self._retrieval_nodes: dict[str, str] = {}
        self._prepare_retrieval()
        #: Ended runs' summaries, kept only when a store is set: without one,
        #: `end` forgets a run exactly as it always has.
        self._ended: dict[str, dict[str, Any]] = {}
        self._replaying = False
        try:
            self.run_store = RunStore(run_store) if run_store is not None else None
            if self.run_store is not None:
                self._restore(self.run_store.load())
        except (OSError, RunStoreError) as error:
            raise ServingError(str(error)) from error

    def _prepare_retrieval(self) -> None:
        """Refuse invalid or unsatisfiable controlled searches before a target runs."""
        for query_id, row in sorted(self.rows.items()):
            if "controlled_retrieval" not in row:
                continue
            from ..evalrun.retrieval import ControlledRetrieval, RetrievalContract

            try:
                contract = RetrievalContract.model_validate(row["controlled_retrieval"])
                if contract.connector not in self.definitions:
                    raise ValueError(f"connector {contract.connector!r} is not in the case")
                if self.definitions[contract.connector].canonical_tool(contract.tool) != contract.tool:
                    raise ValueError("controlled retrieval contracts must name the canonical connector tool")
                controller = ControlledRetrieval(contract)
                controller.bind(self.definitions[contract.connector])
                matching = [node for node in row["expected_dag"]["nodes"]
                            if node.get("server") == contract.connector and node.get("tool") == contract.tool
                            and (contract.intent.entity is None or _entities_meet(
                                self.definitions[contract.connector], str(node.get("entity", "")), contract.intent.entity))]
                if len(matching) != 1:
                    raise ValueError("a controlled retrieval contract must identify exactly one planned search node")
                self._retrieval_contracts[query_id] = contract
                self._retrieval_nodes[query_id] = str(matching[0]["id"])
                source = self._source(contract.connector, row)
                emulator = self._fork(contract.connector, source, row, "agent")
                tool = self.definitions[contract.connector].tool(contract.tool)
                pool = emulator._pool(contract.intent.entity, tool)
                qualified = set(controller.qualify(tuple(emulator._record_for_predicate(record) for record in pool)))
                target = matching[0]
                expected = {str(value) for value in (*target.get("expected_reads", ()), *target.get("fixtures", ()),
                                                    target.get("fixture")) if value}
                if not expected <= qualified:
                    raise ValueError("sufficient retrieval intent cannot expose the planned source records")
            except (ConnectorError, KeyError, TypeError, ValueError) as error:
                raise ServingError(f"controlled_retrieval:{query_id}: {error}") from error

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
        return self._begin(principal, query_id)

    def _begin(self, principal: str, query_id: str, *, restored: tuple[str, int] | None = None) -> dict[str, Any]:
        """Begin a run; *restored* is the id and ordinal a journal gave it, replayed without admission."""
        if not principal:
            raise ServingError("principal_required")
        with self._lock:
            if query_id not in self.rows:
                raise ServingError(f"unknown_query: {query_id}")
            if restored is None:
                self._admit(principal)
            row = self.rows[query_id]
            servers = sorted({str(node["server"]) for node in row["expected_dag"]["nodes"] if node.get("node_kind") != "transform"})
            # The shared inputs are built once, under the registry lock; the
            # fork each run takes of them is built outside it, so a begin
            # that copies a large corpus does not stall every other run.
            sources = {server: self._source(server, row) for server in servers}
        emulators = {server: self._fork(server, sources[server], row, principal) for server in servers}
        before = {fid: dict(record) for server in sorted(emulators)
                  for fid, record in sorted(emulators[server].records.items())}
        with self._lock:
            if restored is None:
                # Checked again: another begin may have taken the last slot
                # while this one was forking.
                self._admit(principal)
                self._ordinal += 1
                run_id, ordinal = f"{self.run_prefix}run-{self._ordinal}", self._ordinal
                if self.run_store is not None:
                    # Under the registry lock, before the id is handed out:
                    # no call on the run can be journalled ahead of its begin.
                    self._append({"kind": "begin", "run_id": run_id, "ordinal": ordinal, "principal": principal,
                                  "query_id": query_id, "row": _row_digest(row)})
            else:
                run_id, ordinal = restored
                self._ordinal = max(self._ordinal, ordinal)
            self._runs[run_id] = _Run(principal, query_id, emulators, before=before, ordinal=ordinal)
        return {"run_id": run_id, "query_id": query_id, "query": row.get("query", ""),
                "max_calls": self.limits.max_calls_per_run,
                **({"execution_mode": "controlled_retrieval"} if query_id in self._retrieval_contracts else {})}

    def _admit(self, principal: str) -> None:
        """Refuse a begin the limits do not admit. The caller holds the service lock."""
        if len(self._runs) >= self.limits.max_runs:
            raise ServingError("run_limit: end a run before starting another")
        if sum(run.principal == principal for run in self._runs.values()) >= self.limits.max_runs_per_principal:
            raise ServingError("principal_run_limit: end a run before starting another")

    def _source(self, server: str, row: Mapping[str, Any]) -> Any:
        """What a run's emulator for *server* forks from, built once. The caller holds the service lock."""
        if row.get("state_overrides"):
            from ..enterprise_rows import runtime_records

            # Converted once: the query emulator neither keeps nor changes
            # its input records, it copies the ones it holds.
            if self._runtime_records is None:
                self._runtime_records = tuple(runtime_records(self.records))
            return self._runtime_records
        # One canonical emulator per connector, built once; each run starts
        # from a fresh transaction over it rather than re-copying every record.
        base = self._bases.get(server)
        if base is None:
            base = self._bases[server] = ConnectorEmulator(self.definitions[server], self.records)
        return base

    def _fork(self, server: str, source: Any, row: Mapping[str, Any], principal: str) -> ConnectorEmulator:
        """A run's own emulator over *source*: reads the shared source, never changes it."""
        if row.get("state_overrides"):
            from ..enterprise_failures import build_query_emulator

            emulator = build_query_emulator(self.definitions[server], source,
                                            overrides=row["state_overrides"],
                                            mutation_nodes=row["expected_dag"]["nodes"],
                                            query_id=str(row["id"]))
        else:
            emulator = source.transaction(fresh=True)
        emulator.actor = principal
        if self.query_engine is not None:
            emulator.query_engine = self.query_engine
        contract = self._retrieval_contracts.get(str(row["id"]))
        if contract is not None and contract.connector == server:
            from ..evalrun.retrieval import ControlledRetrieval

            emulator.retrieval = ControlledRetrieval(contract)
            emulator.retrieval.bind(self.definitions[server])
        return emulator

    def _controlled_attribution(
        self, run: _Run, name: str, arguments: Mapping[str, Any], receipt: Mapping[str, Any],
    ) -> tuple[str | None, tuple[str, ...]]:
        """Bind a sufficient query by its observed intent, never reference query bytes."""
        if receipt.get("intent_status") != "sufficient":
            return None, ()
        node_id = self._retrieval_nodes[run.query_id]
        row = self.rows[run.query_id]
        node = next(item for item in row["expected_dag"]["nodes"] if str(item["id"]) == node_id)
        if f"{node['server']}.{node['tool']}" != name:
            return None, ()
        prior = [span for span in run.spans if span.node == node_id and not span.error]
        if prior:
            # A repeat of page zero is not another plan step. Pagination has
            # to continue the actual previous delivery with the same query.
            previous = run.retrieval_receipts.get(prior[-1].id, {})
            if (int(arguments.get("start_at", 0)) != int(prior[-1].args.get("start_at", 0)) + prior[-1].items
                    or not prior[-1].items or previous.get("is_last") is True
                    or receipt.get("query_digest") != previous.get("query_digest")):
                return None, ()
        elif int(arguments.get("start_at", 0)) != 0:
            return None, ()
        if row.get("grammar") == "enterprise-dag@1":
            from ..enterprise_dag import condition_matches
            from ..enterprise_dag_rows import program_for
            from ..enterprise_dag_runtime import observed_flow

            planned = next(item for item in program_for(row).nodes if item.id == node_id)
            outputs, producers = observed_flow(row, run.spans)
            if any(parent not in outputs for parent in planned.depends_on):
                return None, ()
            if planned.condition and (planned.condition.reference.node not in outputs
                                      or not condition_matches(planned.condition, outputs)):
                return None, ()
            consumed = tuple(dict.fromkeys(identifier for parent in planned.depends_on
                                           for identifier in producers.get(parent, ())))
            return node_id, consumed
        parents = {str(source) for source, target in row["expected_dag"].get("edges", ()) if str(target) == node_id}
        completed = {span.node for span in run.spans if not span.error}
        if not parents <= completed:
            return None, ()
        return node_id, tuple(span.id for span in run.spans if span.node in parents and not span.error)

    def _run(self, principal: str, run_id: str) -> _Run:
        """The run, looked up under the registry lock. Read or change it only inside `_held`."""
        with self._lock:
            run = self._runs.get(run_id)
        if run is None or run.principal != principal:
            # Do not disclose whether another principal owns this handle.
            raise ServingError("unknown_run: start a run with eval_begin")
        return run

    @contextmanager
    def _held(self, principal: str, run_id: str) -> Iterator[_Run]:
        """The run with its own lock held; refused if `end` released it while this waited."""
        run = self._run(principal, run_id)
        with run.lock:
            if run.ended:
                raise ServingError("unknown_run: start a run with eval_begin")
            yield run

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
        candidates: list[tuple[str, set[str]]] = []
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
            candidates.append((str(node["id"]), parents))
        # A read and its readback share a tool and a fixture, so a call both
        # match is the readback once the readback's parents have run: a get
        # issued after the write is that write's verify, whatever came before.
        # First-declared-wins used to give it to the read, so a run that
        # skipped the read and wrote blind was graded as missing its *verify*
        # (the grader mutation suite's `drop_read` on `legacy-update`).
        for node_id, parents in candidates:
            if parents and parents.issubset(completed):
                return node_id
        return candidates[0][0] if candidates else None

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
            if node.for_each and node.for_each.order == "any" and node.kind == "read" and arguments.get("id") is not None:
                # Independent reads in a mapped node can run in either order.
                # Bind the actual returned handle to its unconsumed input,
                # rather than making source-list order an unstated task rule.
                actual_id = emulator.by_ident.get(str(arguments["id"]), str(arguments["id"]))
                already = {fid for span in prior for fid in span.reads}
                index = len(items)
                if actual_id not in already:
                    for candidate_index, item in enumerate(items):
                        try:
                            bound_id = str(bound_arguments(node, outputs, item).get("id"))
                        except ValueError:
                            continue
                        if emulator.by_ident.get(bound_id, bound_id) == actual_id:
                            index = candidate_index
                            break
            if index >= len(items):
                continue
            try:
                wanted = bound_arguments(node, outputs, items[index])
            except ValueError:
                continue
            actual = dict(arguments)
            if node.operation == "search" and actual.get("predicate") is None and actual.get("query") is not None \
                    and wanted.get("predicate") is not None:
                # A vendor API takes no predicate: a search through a contract
                # carries a vendor query instead, which no text comparison with
                # the plan's predicate can judge. It is attributed by shape, and
                # kept only if it read the node's evidence.
                continue
            # A vendor search names its type in the query (JQL `issuetype`, a
            # CQL `type`, SOQL `FROM`) and takes no separate entity, so a call
            # carrying exactly the plan's query without one is the plan's call.
            implied = (node.operation == "search" and "entity" not in actual and actual.get("query") is not None
                       and actual.get("query") == wanted.get("query"))
            if node.operation in {"search", "create", "send", "post", "upload"} and "entity" in declared.params \
                    and not implied:
                # Only when the tool declares it. `call` refuses an undeclared
                # argument before reaching here, so demanding `entity` of a
                # tool without one (email's `search_threads`) made every such
                # node unattributable through the very surface it is served on.
                wanted["entity"] = node.entity
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
        structural = self._structural_attribution(run, program, wire, outputs, producers, name, arguments)
        if structural is not None:
            run.structural.add(len(run.spans) + 1)
            return structural
        return None, self._consumed(run, arguments)

    def _structural_attribution(
        self, run: _Run, program: Any, wire: Mapping[str, Mapping[str, Any]], outputs: Mapping[str, list[Any]],
        producers: Mapping[str, list[str]], name: str, arguments: Mapping[str, Any],
    ) -> tuple[str, tuple[str, ...]] | None:
        """Attribute an external agent's call by shape when its arguments are its own.

        The pass above binds a node's arguments from the reference flow and
        demands equality: the fixture id inside the search predicate, the
        reference's own page name and evidence fields on the create. An agent
        that is not the reference never reproduces those bytes, so every call
        it made was unattributed and its plan graded 0.0 however well it did
        the task. Measured on a real run: twenty calls, the page created and
        read back, plan 0.0, both conditional branches expected.

        Shape is: the node's tool, every tool ancestor already completed, the
        node's condition holding on what was observed, the entity the node
        names, and a target that resolves to the node's fixture or to a
        record a parent produced. A source read with a fixture is attributed
        now and kept only if the call then read that record (`call` checks).
        """
        from ..enterprise_dag import condition_matches

        connector, tool = self.tools[name]
        definition = self.definitions[connector]
        called_op = definition.tool(tool).op
        emulator = run.emulators[connector]
        completed = {span.node for span in run.spans if span.node and not span.error}
        by_id = {node.id: node for node in program.nodes}
        read_ops = {"search", "get", "read", "list"}

        def tool_ancestors(node: Any) -> set[str]:
            found: set[str] = set()
            frontier = list(node.depends_on)
            while frontier:
                parent = by_id[frontier.pop()]
                if parent.kind == "transform":
                    frontier.extend(parent.depends_on)
                else:
                    found.add(parent.id)
            return found

        raw_id = arguments.get("id")
        fid = None
        if raw_id is not None:
            fid = emulator.by_ident.get(str(raw_id), _recorded_aliases(outputs).get(str(raw_id), str(raw_id)))
        for node in program.nodes:
            if node.kind == "transform":
                continue
            same_tool = f"{node.connector}.{wire[node.id]['tool']}" == name
            # A source record read through search instead of get is still
            # read; `call` keeps the attribution only if the fixture came back.
            read_alias = (node.connector == connector and called_op in read_ops
                          and node.operation in read_ops and bool(wire[node.id].get("fixture") or wire[node.id].get("fixtures")))
            if not (same_tool or read_alias):
                continue
            if node.id in completed:
                continue
            ancestors = tool_ancestors(node)
            if not ancestors <= completed:
                continue
            if node.condition and (node.condition.reference.node not in outputs
                                   or not condition_matches(node.condition, outputs)):
                continue
            wanted_entity = arguments.get("entity")
            if wanted_entity and str(wanted_entity) != node.entity and not _entities_meet(
                    definition, node.entity, str(wanted_entity)):
                continue
            if node.operation not in {"search", "create", "send", "post", "upload"} and called_op != "search":
                if fid is None:
                    continue
                fixture = wire[node.id].get("fixture")
                if fixture is not None:
                    if str(fixture) != fid:
                        continue
                else:
                    produced = {record for span in run.spans if span.node in ancestors and not span.error
                                for record in (*span.reads, *span.writes)}
                    if fid not in produced:
                        continue
            consumed = tuple(dict.fromkeys(identifier for parent in node.depends_on
                                           for identifier in producers.get(parent, ())))
            return node.id, consumed
        return None

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
        with self._journal("call", principal, run_id, {"name": name, "arguments": dict(arguments)}):
            return self._call(principal, run_id, name, arguments)

    def _call(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        """One call on the surface this run presents.

        On the native surface *name* is ``connector.tool``. On the contract
        surface it is a contract tool (``jira_get_issue``), dispatched through
        the connector's mapping to the connector tool it becomes; a connector
        tool of a contracted connector is not on that surface and is refused.
        """
        if self.surface_for(principal, run_id) == "native":
            return self.call_connector(principal, run_id, name, arguments)
        if self.surfaces is not None:
            held = self.contract_tools.get(name)
            if held is not None:
                return self._contract_call(principal, run_id, held[0], held[1], arguments)
            if name in self.tools and self.surfaces.get(self.tools[name][0]) is not None:
                with self._held(principal, run_id) as run:
                    message = (f"tool_not_served: {name} is not on this run's contract surface; call the "
                               f"{self.tools[name][0]} contract's operations (tools/list)")
                    self._refusal(run, name, arguments, message)
                raise ServingError(message)
        return self.call_connector(principal, run_id, name, arguments)

    def _refusal(self, run: _Run, name: str, arguments: Iterable[str], message: str) -> None:
        run.refusals.append({"tool": name, "arguments": sorted(str(key) for key in arguments), "error": message,
                             # Where it happened: the span count at the refusal, so an
                             # exported trace can place it among the spans.
                             "index": len(run.spans)})

    def _contract_call(self, principal: str, run_id: str, connector: str, tool: Any, arguments: Mapping[str, Any],
                       backend: _RunBackend | None = None) -> Any:
        from .anvil import refusal_message
        from .surface import ContractCallError

        surface = self.surfaces.surfaces[connector]
        with self._held(principal, run_id) as run:
            if connector not in run.emulators:
                self._refusal(run, tool.name, arguments, f"connector_not_in_query: {connector}")
                raise ServingError(f"connector_not_in_query: {connector}")
            if run.attempts >= self.limits.max_calls_per_run:
                self._refusal(run, tool.name, arguments, "call_limit: retrieve the trace and end this run")
                raise ServingError("call_limit: retrieve the trace and end this run")
            if len(json.dumps(dict(arguments), sort_keys=True, allow_nan=False, default=str).encode()) > \
                    self.limits.max_request_bytes:
                run.attempts += 1
                self._refusal(run, tool.name, arguments, "request_limit: reduce the tool arguments")
                raise ServingError("request_limit: reduce the tool arguments")
            backend = backend or _RunBackend(self, principal, run_id, connector)
            before = (len(run.spans), len(run.refusals))

            def refuse(label: str, names: Sequence[str], message: str) -> None:
                run.attempts += 1
                self._refusal(run, label, names, message)

            try:
                return surface.invoke(tool.name, arguments, backend,
                                      request_id=f"r{len(run.spans) + len(run.refusals) + 1}", refuse=refuse)
            except ContractCallError as error:
                if (len(run.spans), len(run.refusals)) == before:
                    # Refused on Anvil's surface (a missing input, an
                    # unconfirmed write): no connector saw it, and it is an
                    # attempt all the same, counted against the tool it maps to.
                    run.attempts += 1
                    self._refusal(run, surface.maps_to(tool) or f"{connector}.{tool.name}", arguments,
                                  refusal_message(error.envelope.get("error") or {}))
                raise

    def call_planned(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        with self._journal("call_planned", principal, run_id, {"name": name, "arguments": dict(arguments)}):
            return self._call_planned(principal, run_id, name, arguments)

    def _call_planned(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        """A planned connector call (``connector.tool``), made on the surface this run presents.

        On the native surface it is ``call``. On the contract surface the call
        is carried by the exposed operation whose mapping gives it back
        exactly (``ContractSurface.carry``) and made as that operation, so
        the span it leaves is the one an agent calling the operation would
        leave; the connector tool's own result (or error) is returned, which
        is what a plan's next node reads. A call no exposed operation carries
        is refused as a ``contract_gap``. The reference agent walks gold
        plans through this.
        """
        from .surface import ContractCallError, SurfaceError

        if self.surface_for(principal, run_id) == "native" or name not in self.tools:
            return self.call(principal, run_id, name, arguments)
        connector, tool = self.tools[name]
        surface = self.surfaces.get(connector)
        if surface is None:
            return self.call(principal, run_id, name, arguments)
        record = None
        if arguments.get("id") is not None:
            record = self.lookup(principal, run_id, connector, arguments["id"])
            with self._held(principal, run_id) as run:
                key = (connector, str(arguments["id"]))
                if record is not None:
                    run.addressed[key] = record
                else:
                    record = run.addressed.get(key)
        arguments = self._vendor_handles(principal, run_id, connector, tool, arguments)
        try:
            carried = surface.carry(tool, arguments, self.definitions[connector], record=record)
        except SurfaceError as gap:
            with self._held(principal, run_id) as run:
                run.attempts += 1
                self._refusal(run, name, arguments, f"contract_gap: {gap}")
            raise ServingError(f"contract_gap: {gap}") from gap
        backend = _RunBackend(self, principal, run_id, connector)
        try:
            self._contract_call(principal, run_id, connector, surface.tool(carried.tool), carried.arguments,
                                backend=backend)
        except ContractCallError:
            if backend.error is not None:
                raise backend.error from None
            raise
        if backend.error is not None:
            raise backend.error
        return backend.result

    def _vendor_handles(self, principal: str, run_id: str, connector: str, tool: str,
                        arguments: Mapping[str, Any]) -> dict[str, Any]:
        """A planned search's predicate on Worldloom record ids, restated on the vendor's handles where it must be.

        A plan may pick records by the corpus's own ids (``id in
        ('CONN-JIRA-...')``). Some vendor languages resolve those (the
        emulator's ServiceNow encoded query does); others see only the
        vendor's own handle, the connector catalog's ``stable_id`` (a Jira
        key, a Salesforce ``Id``). The predicate is restated on the handles
        only when the vendor query compiled from it finds nothing and the
        restated one finds records, each probed on a throwaway copy of the
        run's state (never a span). The records are the same ones; only
        their names change.
        """
        from ..connector_emulator import _coerce_predicate
        from ..connector_payload import shape_payload
        from .anvil import expressible

        out = dict(arguments)
        raw = out.get("predicate")
        definition = self.definitions[connector]
        if raw is None or definition.catalog is None or not tool.startswith(("search", "query")):
            return out
        try:
            predicate = _coerce_predicate(raw, entity=out.get("entity"))
        except (TypeError, ValueError):
            return out
        entity = str(out.get("entity") or predicate.entity or "")
        catalog = definition.catalog.entities or {}
        stable = (catalog[entity].stable_id if entity in catalog else None) \
            or next((item.stable_id for item in catalog.values() if item.stable_id), None)
        if not stable or not any(item.field == "id" for item in predicate.where):
            return out
        with self._held(principal, run_id) as run:
            emulator = run.emulators.get(connector)
            if emulator is None:
                return out

            def found(candidate: Mapping[str, Any]) -> bool:
                try:
                    trial = emulator.transaction()
                    trial.call(tool, **expressible(definition, tool, candidate))
                    return bool(trial.trace[-1].reads)
                except (ConnectorError, TypeError, ValueError, KeyError):
                    return False

            if found(out):
                return out
            where = []
            # A vendor that numbers its records (a Confluence page id) is
            # given numbers: its contract types the filter as integers.
            numeric = definition.id.pattern == "numeric"
            named = stable
            for item in predicate.where:
                if item.field != "id":
                    where.append(item)
                    continue
                listed = isinstance(item.value, list | tuple)
                handles = []
                for value in (item.value if listed else [item.value]):  # type: ignore[union-attr]
                    try:
                        record = emulator.records[emulator.resolve(value)]
                    except ConnectorError:
                        return out
                    payload = shape_payload(definition, record)
                    # The catalog's handle as the payload spells it, else the
                    # payload's own `id` (a Confluence page keeps `page_id` on
                    # the record and serves it as `id`).
                    key = next((key for key in payload if str(key).casefold() == stable.casefold()), None)
                    if key is None and payload.get("id") is not None:
                        key, named = "id", "id"
                    if key is None:
                        return out
                    handle = payload[key]
                    if numeric and isinstance(handle, str) and handle.isdigit():
                        handle = int(handle)
                    handles.append(handle)
                where.append(item.model_copy(update={"field": named,
                                                     "value": tuple(handles) if listed else handles[0]}))
            restated = {**out, "predicate": predicate.model_copy(update={"where": tuple(where)})}
            return restated if found(restated) else out

    def native_params(self) -> dict[str, set[str]]:
        """Every connector tool's parameters, ``connector.tool`` to names: what a planned call may carry."""
        return {name: set(self.definitions[connector].tool(tool).params) for name, (connector, tool) in self.tools.items()}

    def call_connector(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        with self._journal("call_connector", principal, run_id, {"name": name, "arguments": dict(arguments)}):
            return self._call_connector(principal, run_id, name, arguments)

    def _call_connector(self, principal: str, run_id: str, name: str, arguments: Mapping[str, Any]) -> Any:
        """The connector tool ``connector.tool`` itself, whatever surface the run presents: the call graded.

        What the contract surface's mapping, the Anvil provider and the
        replay of an Anvil trace run each operation as.
        """
        with self._held(principal, run_id) as run:

            def refuse(message: str) -> ServingError:
                run.refusals.append({"tool": name, "arguments": sorted(str(key) for key in arguments), "error": message,
                                     # Where it happened: the span count at the refusal, so an
                                     # exported trace can place it among the spans.
                                     "index": len(run.spans)})
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
            trial = run.emulators[connector].transaction()
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
            controller = getattr(trial, "retrieval", None)
            receipt = controller.receipt_for(local.id) if controller is not None else None
            if receipt is not None:
                assert controller is not None
                if rollback and error is not None and error.kind == "response_limit":
                    receipt = controller.reject_delivery(local.id)
                evidence = receipt.model_dump(mode="json")
                evidence.update(span_id=span.id, ordinal=span.ordinal)
                if rollback:
                    # The emulator produced a payload, but the service did
                    # not deliver it. A response-size failure must not count
                    # as successful acquisition or commit any state change.
                    evidence.update(intent_status="transport_fault" if error is not None
                                    and error.kind == "response_limit" else "tool_error", returned=[],
                                    response_digest=None)
                node, consumed = self._controlled_attribution(run, name, supplied, evidence)
                span = replace(span, node=node, consumed_from=consumed)
                run.structural.discard(span.ordinal)
                run.retrieval_receipts[span.id] = evidence
            if node is not None and span.ordinal in run.structural:
                # Attributed by shape, so the call itself has to bear it out. A
                # read stands only if it read the record the node is for; a
                # search that missed it read something else. A refused call
                # stands only when the refusal is the node's designed failure;
                # an agent's own mistake at the right tool is not the plan step.
                planned: Mapping[str, Any] = next(
                    (item for item in self.rows[run.query_id]["expected_dag"]["nodes"] if item["id"] == node), {})
                wanted = {str(value) for value in (*planned.get("fixtures", ()), planned.get("fixture")) if value}
                designed = {str(a.get("kind")) for a in self.rows[run.query_id].get("assertions", ())
                            if a.get("type") == "failure_at" and str(a.get("node")) == node}
                reads_record = planned.get("node_kind") in {"read", "search", "get", "extract"} or planned.get("op") in {"search", "read", "get"}
                missed_read = error is None and wanted and reads_record and not wanted & set(local.reads)
                own_mistake = error is not None and error.kind not in designed
                if missed_read or own_mistake:
                    span = replace(span, node=None, consumed_from=())
                    run.structural.discard(span.ordinal)
            if error is not None:
                span = replace(span, error={"code": error.code, "kind": error.kind, "message": error.message})
            if rollback:
                span = replace(span, reads=(), writes=(), items=0, bytes=0)
                if controller is not None:
                    # Delivery failed, but the attempt happened. Preserve its
                    # corrected telemetry and fault ordinal without publishing
                    # any of the trial's business state.
                    run.emulators[connector].retrieval = controller
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
        with self._held(principal, run_id) as run:
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
        with self._held(principal, run_id) as run:
            return tuple(run.spans)

    @staticmethod
    def _grading_spans(run: _Run) -> tuple[Any, ...]:
        if not run.retrieval_receipts:
            return tuple(run.spans)
        return tuple({**_span_json(span), **({"retrieval": copy.deepcopy(run.retrieval_receipts[span.id])}
                                           if span.id in run.retrieval_receipts else {})}
                     for span in run.spans)

    def grading_spans(self, principal: str, run_id: str) -> tuple[Any, ...]:
        """Trusted evaluator trace, including receipts never offered by target tools.

        The agent's ``ToolSurface.spans`` and MCP ``eval_trace`` deliberately
        use the ordinary spans. A target cannot submit or replace the
        evaluator's intent classification or delivery receipts.
        """
        with self._held(principal, run_id) as run:
            return self._grading_spans(run)

    def refusals(self, principal: str, run_id: str) -> tuple[dict[str, Any], ...]:
        """Every call this run refused before a span could exist, in order."""
        with self._held(principal, run_id) as run:
            return tuple(dict(item) for item in run.refusals)

    def ask(self, principal: str, run_id: str, question: str, about: tuple[str, ...] = ()) -> str:
        with self._journal("ask", principal, run_id, {"question": question, "about": [str(value) for value in about]}):
            return self._ask(principal, run_id, question, about)

    def _ask(self, principal: str, run_id: str, question: str, about: tuple[str, ...] = ()) -> str:
        """Record a question to the user and answer it from the case.

        The reply comes from the row's own question points — the first
        unclaimed point the question matches — so an agent that asks what
        the request left open gets the user's answer, and one that asks
        something the row never wanted gets a neutral reply and is graded as
        unsolicited. The agent never learns which of the two it was.
        """
        from ..evalrun.contract import case_from_row

        text = str(question or "").strip()
        if not text:
            raise ServingError("ask: a question needs text")
        if len(text) > 2000:
            raise ServingError("ask: a question is at most 2000 characters")
        with self._held(principal, run_id) as run:
            if len(run.questions) >= 32:
                raise ServingError("ask: at most 32 questions per run")
            row = self.rows[run.query_id]
            case = case_from_row(row, query=str(row.get("query") or f"case {row['id']}"), principal=principal)
            claimed = {str(item.get("point")) for item in run.questions if item.get("point")}
            point = next((p for p in case.trajectory.questions if p.id not in claimed and p.matches(text)), None)
            reply = point.answer if point is not None else "Please proceed as you judge best."
            run.questions.append({
                "id": f"q{len(run.questions) + 1}", "index": len(run.spans), "question": text,
                "about": [str(value) for value in about], "reply": reply,
                **({"point": point.id} if point is not None else {}),
            })
            return reply

    def questions(self, principal: str, run_id: str) -> tuple[dict[str, Any], ...]:
        """Every question this run asked, in order, with what the user replied.

        The `point` a question matched is the grader's business, not the
        agent's, and is stripped here: the surface tells an agent what the
        user said, never whether the question was expected.
        """
        with self._held(principal, run_id) as run:
            return tuple({key: value for key, value in item.items() if key != "point"}
                         for item in run.questions)

    def _question_behaviours(self, run: _Run) -> set[str]:
        behaviours: set[str] = set()
        for item in run.questions:
            behaviours.add("clarify")
            if item.get("point"):
                behaviours.add(f"question:{item['point']}")
                if str(item["point"]).startswith("confirm-"):
                    behaviours.add("confirm_before")
        return behaviours

    def record_refusal(self, principal: str, run_id: str, name: str, arguments: Iterable[str], message: str) -> None:
        arguments = tuple(arguments)
        with self._journal("record_refusal", principal, run_id,
                           {"name": name, "arguments": [str(key) for key in arguments], "message": message}):
            self._record_refusal(principal, run_id, name, arguments, message)

    def _record_refusal(self, principal: str, run_id: str, name: str, arguments: Iterable[str], message: str) -> None:
        """Record a call another surface refused before any connector saw it.

        An Anvil server answers some calls itself (auth, an injected fault,
        an idempotent replay, an unmodelled operation): no span exists for
        them, and they are the run's attempts all the same, kept where the
        service keeps its own refusals.
        """
        with self._held(principal, run_id) as run:
            run.refusals.append({"tool": name, "arguments": sorted(str(key) for key in arguments), "error": message,
                                 "index": len(run.spans)})

    def lookup(self, principal: str, run_id: str, connector: str, reference: Any) -> dict[str, Any] | None:
        """One record of the run's *connector* state by any name it answers to, copied; ``None`` if absent."""
        with self._held(principal, run_id) as run:
            emulator = run.emulators.get(connector)
            if emulator is None:
                return None
            try:
                return dict(emulator.records[emulator.resolve(reference)])
            except ConnectorError:
                return None

    def snapshot(self, principal: str, run_id: str) -> dict[str, dict[str, Any]]:
        """The run's connector state, every record by fid, copied.

        Taken at `begin` and again after the agent finishes, the two snapshots
        are the outcome axis: created is in the second and not the first,
        deleted the reverse, updated is the same fid with different fields.
        Each record is copied at its top level, so a caller holding the
        pre-state cannot watch it change: the emulator replaces a record it
        writes rather than changing it in place, so the nested values a copy
        shares are never written. A caller must not write them either.
        """
        with self._held(principal, run_id) as run:
            return {fid: dict(record) for server in sorted(run.emulators)
                    for fid, record in sorted(run.emulators[server].records.items())}

    def tool_catalog(self, principal: str, run_id: str) -> tuple[dict[str, Any], ...]:
        """The tools this run may call, with parameters and safety annotations.

        The `tools/list` an MCP client would see, minus the five evaluation
        tools: only connectors the query names, each with the read-only,
        destructive and idempotent hints the same classification derives.
        On the contract surface a contracted connector's entries are its
        contract's tools as Anvil projects them (``ContractSurface.catalog``).
        """
        from ..evalrun.safety import classify_tool, tool_annotations
        from .query.docs import query_help

        with self._held(principal, run_id) as run:
            out = []
            contracted: set[str] = set()
            controlled = run.query_id in self._retrieval_contracts
            if self.surfaces is not None and not controlled:
                # A connector on its contract shows Anvil's tools for it, as
                # Anvil's MCP server lists them, in place of its own.
                for connector in sorted(run.emulators):
                    surface = self.surfaces.get(connector)
                    if surface is not None:
                        contracted.add(connector)
                        out.extend(surface.catalog(self.definitions[connector]))
            for name in sorted(self.tools):
                connector, tool = self.tools[name]
                if connector not in run.emulators or connector in contracted:
                    continue
                definition = self.definitions[connector]
                declared = definition.tool(tool)
                safety = classify_tool(connector, tool, declared)
                entry: dict[str, Any] = {"name": name, "op": declared.op, "entities": list(declared.entities),
                         "params": dict(declared.params), "annotations": tool_annotations(safety),
                         "risk": safety.risk.value, "idempotency": safety.idempotency.value}
                # What a create must carry, per entity, beyond `name`: the
                # fields the emulator refuses without. An agent that cannot
                # see them can only guess; a real run guessed twice and read
                # the refusal as a duplicate title.
                required = {
                    entity: list(definition.entities[entity].required_on_create)
                    for entity in declared.entities
                    if declared.op == "create" and entity in definition.entities and definition.entities[entity].required_on_create
                }
                if required:
                    entry["required_on_create"] = required
                # What the tool's `query` (or `predicate`) is written in, with
                # a grammar summary and examples in the vendor's own syntax: a
                # pilot's call errors were mostly queries the agent had no way
                # to know the grammar of.
                help = self.controlled_query_help(connector, tool, query_id=run.query_id) if controlled else None
                if help is None:
                    help = query_help(definition, tool)
                if help is not None:
                    entry["query"] = help
                    if controlled and help.get("name") == "controlled structured retrieval":
                        entry["params"].pop("query", None)
                if controlled:
                    entry["execution_mode"] = "controlled_retrieval"
                out.append(entry)
            return tuple(out)

    def surface_for(self, principal: str, run_id: str) -> str:
        """The actual surface of one case; controlled cases use typed connector tools."""
        with self._held(principal, run_id) as run:
            return "native" if run.query_id in self._retrieval_contracts else self.surface

    def controlled_query_help(self, connector: str, tool: str, *, query_id: str | None = None) -> dict[str, Any] | None:
        """Public query vocabulary: field names and types, never target filter values."""
        from ..predicates import PredicateOp

        contracts = (self._retrieval_contracts.get(query_id),) if query_id is not None else tuple(self._retrieval_contracts.values())
        definition = self.definitions[connector]
        if not any(contract is not None and contract.connector == connector
                   and definition.canonical_tool(contract.tool) == definition.canonical_tool(tool) for contract in contracts):
            return None
        declared = definition.tool(tool)
        fields = set(definition.query_fields)
        # Include business columns from the corpus schema, not their values.
        # Internal evidence and identity plumbing is not a query vocabulary.
        internal = {"fid", "server", "ident", "external_id", "fact_ids", "event_ids", "source_artifact_ids"}
        for record in self.records:
            if isinstance(record, ConnectorRecord):
                if record.connector == connector:
                    fields.update(record.fields)
            elif record.get("server", connector) == connector:
                fields.update(str(key) for key in record if key not in internal)
        names = sorted(fields - internal)
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"entity": {"type": "string", "enum": list(declared.entities)},
                                 "where": {"type": "array", "items": {"type": "object", "additionalProperties": False,
                                           "properties": {"field": {"type": "string", "enum": names},
                                                          "op": {"type": "string", "enum": [op.value for op in PredicateOp]},
                                                          "value": {"type": ["string", "number", "boolean", "null", "array"]}},
                                           "required": ["field", "value"]}}}, "required": ["where"]}
        return {"language": "predicate", "argument": "predicate", "name": "controlled structured retrieval",
                "grammar": "Pass {entity, where: [{field, op, value}]}; clauses are ANDed and each field appears once. "
                           "Use eq, ne, gt, gte, lt, lte, in, or contains. Results depend on declared query semantics, not ranking.",
                "free_text": "Not supported in controlled mode. Use the structured predicate; native query strings return unsupported_query.",
                "examples": ['{"where": [{"field": "<field>", "op": "eq", "value": "<value>"}]}'],
                "fields": names, "schema": schema}

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

        with self._held(principal, run_id) as run:
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
            questions = tuple(dict(item) for item in run.questions)
            after = {fid: dict(record) for server in sorted(run.emulators)
                     for fid, record in sorted(run.emulators[server].records.items())}
            assertions = self.grade(principal, run_id)
            score = grade_run(case, self._grading_spans(run), run.before, after, assertions, response,
                              definitions=self.definitions, rater=rater, safety=safety_for(self.definitions),
                              refusals=refusals, questions=questions)
            result = CaseResult(case_id=case.id, query=case.query, dimensions=case.dimensions, shape=case.plan.shape,
                                agent=f"served:{principal}", status="graded", score=score, answer=answer,
                                calls=len(spans), spans=tuple(_span_json(span) for span in spans),
                                refused=len(refusals), refusals=refusals,
                                questions=tuple({k: v for k, v in item.items() if k != "point"} for item in questions),
                                execution_mode="controlled_retrieval" if run.query_id in self._retrieval_contracts else None)
            return result.model_dump(mode="json")

    def grade(self, principal: str, run_id: str) -> dict[str, Any]:
        with self._held(principal, run_id) as run:
            post_state = {fid: record for server in sorted(run.emulators)
                          for fid, record in sorted(run.emulators[server].records.items())}
            behaviors = set()
            for span in run.spans:
                if span.error:
                    code, kind = span.error.get("code"), span.error.get("kind")
                    behaviors.add("denial_surfaced" if code == 403 else
                                  "report_not_found" if code == 404 or kind == "not_found" else
                                  "branch_failed" if kind in {"timeout", "rate_limit"} else "validation_error")
            # The questions the run asked are behaviours too: `clarify` and
            # `confirm_before` are what `clarify_before_write` and
            # `confirm_before` have always waited for, and `question:<id>`
            # is what `question_required` reads.
            behaviors |= self._question_behaviours(run)
            return dict(grade_trace(self._grading_spans(run), self.rows[run.query_id], post_state=post_state,
                                   behaviors=sorted(behaviors)))

    def end(self, principal: str, run_id: str) -> dict[str, Any]:
        # The run's lock, then the registry's: the one order every path takes
        # them in, so an end racing a call on the same run waits for it.
        with self._held(principal, run_id) as run:
            grade = self.grade(principal, run_id)
            if self.run_store is not None:
                summary = {"run_id": run_id, "ordinal": run.ordinal, "principal": principal,
                           "query_id": run.query_id, "grade": grade}
                # Written before the run is released: a failed write leaves
                # it open, never ended in memory and open on disk.
                self._append({"kind": "end", **summary})
                # The listing returns what a reload would read back, so a
                # grade is the same value before and after a restart.
                self._ended[run_id] = json.loads(json.dumps(summary, sort_keys=True, default=str))
            run.ended = True
            with self._lock:
                del self._runs[run_id]
        return {"run_id": run_id, "ended": True, "grade": grade}

    def list_runs(self, principal: str) -> list[dict[str, Any]]:
        """This principal's runs, open and (with a run store) ended, in the order they began.

        An open run reports its calls so far; an ended one its final grade,
        read back from the journal after a restart. Without a run store `end`
        forgets a run, so only open runs are listed.
        """
        with self._lock:
            opened = [(run_id, run) for run_id, run in self._runs.items() if run.principal == principal]
            ended = [dict(item) for item in self._ended.values() if item["principal"] == principal]
        listed: list[tuple[int, dict[str, Any]]] = []
        for run_id, run in opened:
            with run.lock:
                if run.ended:
                    continue
                listed.append((run.ordinal, {"run_id": run_id, "query_id": run.query_id, "status": "open",
                                             "calls": len(run.spans), "attempts": run.attempts}))
        for item in ended:
            listed.append((int(item["ordinal"]), {"run_id": item["run_id"], "query_id": item["query_id"],
                                                  "status": "ended", "grade": item["grade"]}))
        return [entry for _, entry in sorted(listed, key=lambda pair: (pair[0], pair[1]["run_id"]))]

    # -- durability ---------------------------------------------------------

    def _append(self, record: Mapping[str, Any]) -> None:
        if self.run_store is None or self._replaying:
            return
        try:
            self.run_store.append(record)
        except (OSError, RunStoreError) as error:
            raise ServingError(f"run_store: {error}") from error

    @contextmanager
    def _journal(self, op: str, principal: str, run_id: str, args: Mapping[str, Any]) -> Iterator[None]:
        """Journal one entry-point call on a run once it has run, whether it returned or raised.

        A refused call changes the run too (an attempt, a refusal), so it is
        journalled and replayed like any other. Only the outermost entry
        point on a run is written; the run's lock is held throughout, so the
        journal's order for a run is the order its calls took effect.
        """
        if self.run_store is None or self._replaying:
            yield
            return
        record = {"kind": "event", "op": op, "run_id": run_id, "principal": principal, "args": dict(args)}
        try:
            json.dumps(record, allow_nan=False)
        except (TypeError, ValueError) as error:
            raise ServingError(f"run_store: {op} arguments must be plain JSON to be journalled ({error})") from error
        try:
            run: _Run | None = self._run(principal, run_id)
        except ServingError:
            # Unknown here: the call refuses without touching any run, so
            # there is nothing to replay.
            run = None
        with run.lock if run is not None else nullcontext():
            outer = run is not None and run.journal_depth == 0
            if run is not None:
                run.journal_depth += 1
            try:
                yield
            finally:
                if run is not None:
                    run.journal_depth -= 1
                    if outer and not run.ended:
                        self._append(record)

    def _restore(self, records: Sequence[Mapping[str, Any]]) -> None:
        """Rebuild the runs a journal holds: ended runs as their summaries, open runs by replaying their calls."""
        begun: dict[str, Mapping[str, Any]] = {}
        events: dict[str, list[Mapping[str, Any]]] = {}
        for record in records:
            kind, run_id = record.get("kind"), str(record.get("run_id"))
            if kind == "begin":
                if run_id in begun:
                    warnings.warn(f"run_store: {run_id} begins twice; keeping the first", RunStoreWarning, stacklevel=3)
                    continue
                begun[run_id] = record
                events[run_id] = []
                self._ordinal = max(self._ordinal, int(record["ordinal"]))
            elif run_id not in begun:
                warnings.warn(f"run_store: a {kind} record names {run_id}, which never began; skipped",
                              RunStoreWarning, stacklevel=3)
            elif kind == "end":
                self._ended[run_id] = {key: record[key] for key in ("run_id", "ordinal", "principal", "query_id", "grade")}
            elif kind == "event":
                events[run_id].append(record)
        self._replaying = True
        try:
            for run_id, begin in sorted(begun.items(), key=lambda item: (int(item[1]["ordinal"]), item[0])):
                if run_id in self._ended:
                    continue
                query_id, principal = str(begin["query_id"]), str(begin["principal"])
                if query_id not in self.rows or _row_digest(self.rows[query_id]) != begin.get("row"):
                    warnings.warn(f"run_store: {run_id} began on query {query_id} as it no longer is; "
                                  "not replayed", RunStoreWarning, stacklevel=3)
                    continue
                self._begin(principal, query_id, restored=(run_id, int(begin["ordinal"])))
                for event in events[run_id]:
                    self._replay(principal, run_id, event)
        finally:
            self._replaying = False

    def _replay(self, principal: str, run_id: str, event: Mapping[str, Any]) -> None:
        op, args = event.get("op"), dict(event.get("args") or {})
        try:
            if op in {"call", "call_planned", "call_connector"}:
                getattr(self, str(op))(principal, run_id, args["name"], args["arguments"])
            elif op == "ask":
                self.ask(principal, run_id, args["question"], tuple(args.get("about") or ()))
            elif op == "record_refusal":
                self.record_refusal(principal, run_id, args["name"], args["arguments"], args["message"])
            else:
                warnings.warn(f"run_store: {run_id} has an unknown event {op!r}; skipped", RunStoreWarning, stacklevel=4)
        except Exception:
            # The journalled call raised too; replaying it rebuilds the same refusal.
            pass


def _recorded_aliases(outputs: Mapping[str, Sequence[Any]]) -> dict[str, str]:
    """Native identifiers in recorded results, mapped to the fid each answered for."""
    aliases: dict[str, str] = {}
    for produced in outputs.values():
        for entry in produced:
            if isinstance(entry, Mapping) and isinstance(entry.get("payload"), Mapping):
                native = entry["payload"]
                for key in RECORDED_ALIAS_KEYS:
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
    from .query.docs import describe, query_help

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
        register("eval_ask", {"run_id": (str, ...), "question": (str, ...), "about": (list[str] | None, None)},
                 lambda principal, args: {"reply": service.ask(principal, args["run_id"], args["question"],
                                                                tuple(args.get("about") or ()))},
                 "Ask the user a question and get their reply. Ask when the request is ambiguous, a required "
                 "parameter is missing, or a call would be destructive and the request did not authorise it; "
                 "asking when nothing is unclear is graded as unsolicited.", False),
        register("eval_end", {"run_id": (str, ...)},
                 lambda principal, args: service.end(principal, **args), "Grade and release this run. Retrieve the trace before ending.", False),
    ]
    param_types: dict[str, Any] = {"string": str, "int": int, "integer": int,
                                 "number": float, "bool": bool, "boolean": bool,
                                 "object": dict[str, Any], "array": list[Any]}
    contracted = set(service.surfaces.connectors) if service.surfaces is not None else set()
    controlled_connectors = {str(node["server"]) for row in service.rows.values() if "controlled_retrieval" in row
                             for node in row["expected_dag"]["nodes"] if node.get("node_kind") != "transform"}
    if contracted:
        from .surface import ContractCallError

        class _Passthrough(FuncMetadata):
            """A contract tool's arguments are Anvil's schema's, handed to the surface as sent (zod strips, not refuses)."""

            def validate_arguments(self, arguments_to_validate: dict[str, Any]) -> dict[str, Any]:
                raw = dict(self.pre_parse_json(arguments_to_validate))
                run_id = raw.pop("run_id", None)
                if not isinstance(run_id, str):
                    raise ToolError("run_id: a string is required")
                return {"run_id": run_id, "arguments": raw}

        class _ContractArgs(ArgModelBase):
            model_config = ConfigDict(extra="allow")
            run_id: str

        def contract_tool(connector: str, item: Any) -> Any:
            def invoke(ctx: Any, run_id: str, arguments: dict[str, Any], name: str = item.name) -> Any:
                principal = ctx.request_context.request.scope["worldloom.principal"]
                try:
                    return service.call(principal, run_id, name, arguments)
                except ContractCallError as error:
                    raise ToolError(json.dumps(error.envelope, sort_keys=True)) from error
                except (ServingError, ConnectorError) as error:
                    raise ToolError(str(error)) from error

            schema = json.loads(json.dumps(item.input_schema))
            schema.setdefault("properties", {})["run_id"] = {"type": "string",
                                                             "description": "The evaluation run this call acts in."}
            schema["required"] = ["run_id", *schema.get("required", [])]
            hints = dict(item.definition.get("annotations") or {})
            return Tool(name=item.name, title=item.definition.get("title"), description=str(item.definition.get("description") or ""),
                        fn=invoke, is_async=False, context_kwarg="ctx", parameters=schema,
                        fn_metadata=_Passthrough(arg_model=_ContractArgs),
                        annotations=ToolAnnotations(read_only_hint=hints.get("readOnlyHint"),
                                                    destructive_hint=hints.get("destructiveHint"),
                                                    idempotent_hint=hints.get("idempotentHint"),
                                                    open_world_hint=hints.get("openWorldHint")))

        for connector in sorted(contracted):
            if connector in service.definitions:
                tools.extend(contract_tool(connector, item) for item in service.surfaces.surfaces[connector].tools)
    for name, (connector, tool_name) in service.tools.items():
        if connector in contracted and connector not in controlled_connectors:
            continue
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

        controlled_help = service.controlled_query_help(connector, tool_name)
        description = (f"{definition.vendor_product}: {tool.op} {', '.join(tool.entities)}. "
                       "Acts only in the named evaluation run.")
        if connector in contracted:
            description += " This typed connector operation is available for controlled retrieval cases."
        described = controlled_help if controlled_help is not None else query_help(definition, tool_name)
        registered = register(name, params, operation, description + describe(described), tool.op in _READ_OPS)
        if controlled_help is not None and "predicate" in registered.parameters.get("properties", {}):
            registered.parameters["properties"]["predicate"] = copy.deepcopy(controlled_help["schema"])
        tools.append(registered)
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
