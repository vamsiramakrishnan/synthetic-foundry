"""An Anvil simulator state provider over Worldloom records: ``python -m worldloom.anvil_provider``.

Anvil starts this process with ``anvil simulate serve --provider-cmd`` and
speaks newline-delimited JSON-RPC 2.0 on its stdio (Anvil's
``docs/simulator-state-providers.md``): ``initialize`` once, with the
contract's operation table; ``invoke`` per call that passed Anvil's surface
gates; ``shutdown`` at the end. Stdout carries protocol lines and nothing
else; every diagnostic goes to stderr, which Anvil forwards.

Two ways to hold state:

``--corpus DIR --connector NAME``
    The connector's records from a corpus directory (a case set's
    ``records.jsonl``, an enterprise export's ``connector-data.json``, or a
    bare ``records.jsonl``) in one emulator, searched by the shared vendor
    query evaluator. ``--as-of`` moves the clock relative dates resolve
    against. Writes change that emulator's state for the life of the process.
``--state FILE``
    One evaluation case, as ``worldloom evalrun run --connectors anvil``
    writes it: the case's compiled row and records, served by an evaluation
    service run so node attribution and the case's designed failures apply
    exactly as they do in process. ``--order-log`` appends each call's
    connector and request id, which is how the runner orders the traces of
    several Anvil servers.

``--lint CONTRACT`` checks the mapping against a contract (a bundle
directory, its ``air.json``/``air.yaml``, or an ``initialize`` operation table
saved as JSON) and exits non-zero when an exposed operation is unmapped.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import traceback
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import IO, Any

from .anvil import (
    PROTOCOL_VERSION,
    AnvilMapping,
    Backend,
    EmulatorBackend,
    MappingError,
    ServiceBackend,
    answer,
    lint_mapping,
    load_mapping,
    operations_from_air,
    operations_from_table,
    read_air,
)

STATE_SCHEMA = "worldloom.anvil-case/v1"


class HandshakeRefused(Exception):
    """``initialize`` asked for something this provider will not serve."""


def _log(message: str) -> None:
    print(f"worldloom-anvil-provider: {message}", file=sys.stderr, flush=True)


def load_corpus_records(directory: str | Path) -> tuple[Any, ...]:
    """Connector records from a case set, an enterprise export, or a bare ``records.jsonl``."""

    from ..connector_data import ConnectorDataset, ConnectorRecord
    from ..evalrun.contract import is_case_set, read_case_set

    root = Path(directory)
    if is_case_set(root):
        return tuple(read_case_set(root)[1])
    exported = root / "connector-data.json"
    if exported.is_file():
        return tuple(ConnectorDataset.model_validate_json(exported.read_text(encoding="utf-8")).records)
    bare = root / "records.jsonl"
    if bare.is_file():
        return tuple(ConnectorRecord.model_validate(json.loads(line))
                     for line in bare.read_text(encoding="utf-8").splitlines() if line.strip())
    raise FileNotFoundError(f"{root} holds no records.jsonl or connector-data.json")


def corpus_backend(corpus: str | Path, connector: str, *, as_of: str | None = None,
                   actor: str = "agent") -> EmulatorBackend:
    """One emulator over the corpus's *connector* records, native query engine."""

    from datetime import datetime

    from ..connector_definition import load_connector_definition
    from ..connector_emulator import ConnectorEmulator

    definition = load_connector_definition(connector)
    if as_of is not None:
        datetime.fromisoformat(as_of)  # refuse a clock the evaluator could not read
        definition = definition.model_copy(update={"clock": as_of})
    records = load_corpus_records(corpus)
    return EmulatorBackend(ConnectorEmulator(definition, records, actor=actor, query_engine="native"))


def _record(item: Mapping[str, Any]) -> Any:
    """A record as the runner held it: a ``ConnectorRecord`` it dumped, or a runtime record (``fid``) as is.

    The service treats the two differently when a case overrides state, so
    the provider must hand it the same kind the runner's service held.
    """

    from ..connector_data import ConnectorRecord

    if "fid" not in item and {"id", "connector", "entity", "fields"} <= set(item):
        return ConnectorRecord.model_validate(item)
    return dict(item)


def case_backend(state: Mapping[str, Any]) -> ServiceBackend:
    """An evaluation service run over one case's row and records, as the runner wrote them."""

    from ..connector_definition import ConnectorDefinition
    from .serving import ConnectorEvaluationService

    if state.get("schema") != STATE_SCHEMA:
        raise ValueError(f"state file schema must be {STATE_SCHEMA!r}")
    definitions = {name: ConnectorDefinition.model_validate(value)
                   for name, value in sorted((state.get("definitions") or {}).items())}
    row = dict(state["row"])
    records = state.get("records")
    if records is None and state.get("records_file"):
        records = json.loads(Path(str(state["records_file"])).read_text(encoding="utf-8"))
    records = [_record(item) for item in records or ()]
    service = ConnectorEvaluationService([row], records or (), definitions=definitions or None,
                                         query_engine=str(state.get("query_engine") or "native"))
    principal = str(state["principal"])
    begun = service.begin(principal, str(row["id"]))
    return ServiceBackend(service, principal, str(begun["run_id"]), str(state["connector"]))


class Provider:
    """The protocol's three methods over one mapping and one backend."""

    def __init__(self, mapping: AnvilMapping, backend: Backend, *, order_log: str | Path | None = None,
                 snapshot_out: str | Path | None = None) -> None:
        self.mapping = mapping
        self.backend = backend
        self.order_log = Path(order_log) if order_log is not None else None
        self.snapshot_out = Path(snapshot_out) if snapshot_out is not None else None
        self.initialized = False

    def finish(self) -> None:
        """Write the final state (every record by fid) where ``--snapshot-out`` asked: the post-state of a diff."""

        if self.snapshot_out is None:
            return
        self.snapshot_out.write_text(json.dumps(self.backend.snapshot(), sort_keys=True, indent=1, default=str) + "\n",
                                     encoding="utf-8")

    def initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        version = params.get("protocolVersion")
        if version != PROTOCOL_VERSION:
            raise HandshakeRefused(f"protocolVersion {version!r} is not supported; this provider speaks {PROTOCOL_VERSION}")
        service = params.get("serviceId")
        if self.mapping.service and service and service != self.mapping.service:
            _log(f"the contract's service is {service!r}; the {self.mapping.connector} mapping was written for "
                 f"{self.mapping.service!r}, so operations are matched by route")
        operations = operations_from_table(params.get("operations") or ())
        errors, advisories = lint_mapping(self.mapping, operations, self.backend.definition)
        for advisory in advisories:
            _log(advisory)
        if errors:
            raise HandshakeRefused(f"the {self.mapping.connector} mapping does not cover this contract: " + "; ".join(errors))
        self.initialized = True
        return {"protocolVersion": PROTOCOL_VERSION}

    def invoke(self, params: Mapping[str, Any]) -> dict[str, Any]:
        if self.order_log is not None:
            line = json.dumps({"connector": self.mapping.connector, "requestId": params.get("requestId")},
                              sort_keys=True) + "\n"
            # One short O_APPEND write: whole on POSIX, so the providers of
            # several servers can share the file without a lock.
            descriptor = os.open(self.order_log, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
            try:
                os.write(descriptor, line.encode("utf-8"))
            finally:
                os.close(descriptor)
        return answer(self.mapping, self.backend, params).response


def serve(provider: Provider, stdin: Iterable[str], stdout: IO[str]) -> int:
    """Answer JSON-RPC lines from *stdin* on *stdout* until ``shutdown`` or end of input.

    The final state is written (``Provider.finish``) before ``shutdown`` is
    answered, since Anvil closes the pipe once it has the answer, and at the
    end of input for a host that closes it without asking.
    """

    for raw in stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except ValueError:
            _log(f"ignored a line that is not JSON: {line[:120]!r}")
            continue
        if not isinstance(message, dict) or "id" not in message:
            continue  # a notification, or noise: nothing to answer
        method = message.get("method")
        params = message.get("params") or {}
        reply: dict[str, Any] = {"jsonrpc": "2.0", "id": message["id"]}
        try:
            if method == "initialize":
                reply["result"] = provider.initialize(params)
            elif method == "invoke":
                reply["result"] = provider.invoke(params)
            elif method == "shutdown":
                provider.finish()
                reply["result"] = None
            else:
                reply["error"] = {"code": -32601, "message": f"unknown method {method!r}"}
        except HandshakeRefused as refused:
            _log(str(refused))
            reply["error"] = {"code": -32602, "message": str(refused)}
        except Exception as error:  # the provider could not process the request: Anvil's upstream_unavailable
            traceback.print_exc(file=sys.stderr)
            reply["error"] = {"code": -32603, "message": f"{type(error).__name__}: {error}"}
        stdout.write(json.dumps(reply, sort_keys=True, separators=(",", ":"), default=str) + "\n")
        stdout.flush()
        if method == "shutdown":
            return 0
    provider.finish()
    return 0


def _contract_operations(path: str) -> Any:
    target = Path(path)
    if target.suffix == ".json" and target.is_file():
        document = json.loads(target.read_text(encoding="utf-8"))
        if isinstance(document, list):
            return operations_from_table(document)
        if isinstance(document, dict) and isinstance(document.get("params"), dict):
            return operations_from_table(document["params"].get("operations") or ())
    return operations_from_air(read_air(target))


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m worldloom.anvil_provider", description=__doc__.split("\n\n")[0])
    parser.add_argument("--connector", help="The connector whose records and mapping serve the contract (e.g. jira).")
    parser.add_argument("--corpus", help="Corpus directory: a case set, an enterprise export, or a records.jsonl.")
    parser.add_argument("--as-of", dest="as_of", help="ISO time relative query dates resolve against (default: the definition's clock).")
    parser.add_argument("--actor", default="agent", help="Who a write is recorded as (default: agent).")
    parser.add_argument("--state", help="One evaluation case, as `evalrun run --connectors anvil` writes it.")
    parser.add_argument("--order-log", dest="order_log", help="Append each call's connector and request id here.")
    parser.add_argument("--snapshot-out", dest="snapshot_out", help="At shutdown, write every record by fid here (the post-state of a state diff).")
    parser.add_argument("--mapping", help="A mapping file instead of the shipped _data/connectors/anvil/<connector>.json.")
    parser.add_argument("--lint", metavar="CONTRACT", help="Check the mapping against a contract and exit.")
    options = parser.parse_args(argv)
    state: dict[str, Any] | None = None
    if options.state:
        state = json.loads(Path(options.state).read_text(encoding="utf-8"))
    connector = options.connector or (str(state["connector"]) if state else None)
    try:
        mapping = load_mapping(connector, path=options.mapping)
    except MappingError as error:
        _log(str(error))
        return 2
    if options.lint:
        from ..connector_definition import load_connector_definition

        errors, advisories = lint_mapping(mapping, _contract_operations(options.lint),
                                          load_connector_definition(mapping.connector))
        for item in (*errors, *advisories):
            print(item, file=sys.stderr)
        print(json.dumps({"connector": mapping.connector, "errors": list(errors), "advisories": list(advisories)},
                         indent=2, sort_keys=True))
        return 1 if errors else 0
    backend: Backend
    if state is not None:
        backend = case_backend(state)
    elif options.corpus:
        backend = corpus_backend(options.corpus, mapping.connector, as_of=options.as_of, actor=options.actor)
    else:
        parser.error("give --corpus or --state (or --lint)")
    # Stdout is the protocol. Anything else that prints goes to stderr.
    protocol = sys.stdout
    sys.stdout = sys.stderr
    try:
        return serve(Provider(mapping, backend, order_log=options.order_log, snapshot_out=options.snapshot_out),
                     sys.stdin, protocol)
    finally:
        sys.stdout = protocol


__all__ = ["STATE_SCHEMA", "HandshakeRefused", "Provider", "case_backend", "corpus_backend", "load_corpus_records",
           "main", "serve"]
