"""Observed target-agent trials over the existing connector serving runtime.

Only the public question, connector contracts and delivered tool responses cross
the exec seam. Attribution, fixtures, reference traces and grades stay here. A
validated proposal is saved before its isolated tool transaction, so recovery
never needs to ask the target to repeat an already accepted turn.
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, model_validator

from .. import execseam
from ..connector_emulator import ConnectorError
from ..connectors.serving import ConnectorEvaluationService, ServingError, ServingLimits
from ..corpus import read_jsonl, write_json
from ..enterprise_corpus import validate_corpus
from ..enterprise_io import load_exported_corpus
from ..enterprise_qualification import QUALIFICATION_SCHEMA
from ..enterprise_qualification import digest as qualification_digest
from ..evals.calibration import TrialOutcome
from ..models import Model
from ..providers import digest

PROTOCOL: Literal["worldloom.target-trial/v1"] = "worldloom.target-trial/v1"
MAX_DOCUMENT_BYTES = 4_000_000
_PRINCIPAL = "studio-target-agent"


def unmeasured_artifact_outcomes(query: Any) -> tuple[str, ...]:
    """A connector write or byte receipt cannot certify native file analysis."""
    native = {"docx", "pptx", "xlsx", "pdf", "gdoc", "gslides", "gsheet"}
    findings = []
    if any(source.input_format in native for source in query.generation.source_requirements):
        findings.append("native_ingestion_and_analysis_unmeasured")
    artifact = query.generation.artifact
    if query.generation.mutation.output_format in native or (artifact is not None and artifact.format in native):
        findings.append("native_output_content_and_preservation_unmeasured")
    return tuple(findings)


class AgentToolCall(Model):
    tool: str = Field(min_length=1, max_length=200)
    arguments: dict[str, Any] = Field(default_factory=dict)


class AgentTurn(Model):
    request_id: str
    call: AgentToolCall | None = None
    final: str | None = Field(default=None, max_length=16000)

    @model_validator(mode="after")
    def _one_action(self) -> AgentTurn:
        if (self.call is None) == (self.final is None):
            raise ValueError("return exactly one tool call or final answer")
        json.dumps(self.model_dump(mode="json"), allow_nan=False)
        return self


class TrialReceipt(Model):
    schema_version: Literal["worldloom.target-trial/v1"] = PROTOCOL
    kind: Literal["input", "proposal", "observation", "result"]
    body: dict[str, Any]
    receipt_digest: str

    @model_validator(mode="after")
    def _sealed(self) -> TrialReceipt:
        if digest([self.schema_version, self.kind, self.body]) != self.receipt_digest:
            raise ValueError("target trial receipt digest mismatch")
        return self


def _receipt(kind: Literal["input", "proposal", "observation", "result"], **body: Any) -> TrialReceipt:
    # Native trace dataclasses contain tuples; receipts compare their wire
    # representation, so a JSON round trip cannot change equality on resume.
    body = json.loads(json.dumps(body, allow_nan=False))
    return TrialReceipt(kind=kind, body=body, receipt_digest=digest([PROTOCOL, kind, body]))


def _save(path: Path, receipt: TrialReceipt) -> None:
    if path.exists():
        if TrialReceipt.model_validate_json(path.read_text(encoding="utf-8")) != receipt:
            raise ValueError(f"target trial replay changed {path.name}")
        return
    temporary = path.with_suffix(".tmp")
    write_json(temporary, receipt.model_dump(mode="json"))
    temporary.replace(path)


def _qualified(directory: Path, query_id: str) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("qualification_schema") != QUALIFICATION_SCHEMA:
        raise ValueError("target trials require an exported qualified enterprise corpus")
    corpus = load_exported_corpus(directory)
    rows = read_jsonl(directory / "qualified-rows.jsonl")
    proofs = read_jsonl(directory / "proofs.jsonl")
    report = json.loads((directory / "qualification.json").read_text(encoding="utf-8"))
    checks = {"corpus_digest": corpus, "connector_data_digest": corpus.connector_data,
              "rows_digest": rows, "proofs_digest": proofs, "qualification_digest": report,
              "pool_digest": read_jsonl(directory / "pool-queries.jsonl")}
    for key, value in checks.items():
        if qualification_digest(value) != manifest.get(key):
            raise ValueError(f"target trial qualified input digest mismatch: {key}")
    findings = validate_corpus(corpus)
    if findings:
        raise ValueError("target trial corpus is invalid: " + "; ".join(findings[:3]))
    queries = [query for query in corpus.queries if query.id == query_id]
    fixtures = [fixture for fixture in corpus.fixtures if fixture.query_id == query_id]
    selected_rows = [row for row in rows if row["id"] == query_id]
    selected_proofs = [proof for proof in proofs if proof["query_id"] == query_id]
    if any(len(items) != 1 for items in (queries, fixtures, selected_rows, selected_proofs)):
        raise ValueError("target trial query must have one qualified fixture, row and proof")
    unsupported = unmeasured_artifact_outcomes(queries[0])
    if unsupported:
        raise ValueError("target artifact checks unavailable: " + "; ".join(unsupported))
    row, proof = selected_rows[0], selected_proofs[0]
    if (proof["query_digest"] != qualification_digest(queries[0])
            or proof["fixture_digest"] != qualification_digest(fixtures[0])
            or proof["row_digest"] != qualification_digest(row)
            or proof["connector_data_digest"] != manifest["connector_data_digest"]
            or proof["grade"].get("fails") != [] or proof["grade"].get("status") == "fail"):
        raise ValueError("target trial reference qualification does not bind the supplied inputs")
    return corpus, {**row, "query": queries[0].query}, manifest


def _tools(service: ConnectorEvaluationService) -> list[dict[str, Any]]:
    """Publish all tools on the participating systems, not the expected path."""
    return [
        {"name": name, **service.definitions[connector].tool(tool).model_dump(mode="json"),
         "query_language": service.definitions[connector].query_language,
         "entity_contracts": {
             entity: service.definitions[connector].entities[entity].model_dump(mode="json")
             for entity in service.definitions[connector].tool(tool).entities},
         "fields": {
             entity: [field.model_dump(mode="json") for field in service.definitions[connector].fields_for(entity)]
             for entity in service.definitions[connector].tool(tool).entities}}
        for name, (connector, tool) in sorted(service.tools.items())
    ]


def _trace(service: ConnectorEvaluationService, run_id: str) -> list[dict[str, Any]]:
    spans: list[dict[str, Any]] = []
    offset = 0
    while True:
        page = service.trace(_PRINCIPAL, run_id, offset=offset)
        spans.extend(page["spans"])
        if page["next_offset"] is None:
            return spans
        offset = page["next_offset"]


def evaluate_trial(
    corpus: str | Path,
    query_id: str,
    *,
    root: str | Path,
    harness_command: str,
    timeout: float = 600,
    max_turns: int = 32,
    trial_id: str | None = None,
    world_digest: str | None = None,
) -> TrialOutcome:
    """Execute or replay one bounded target trial; grade only observed effects.

    ``root`` belongs to one immutable trial/configuration. Reopening it rebuilds
    isolated runtime state from validated proposals and compares every observed
    response and trace. A completed run makes zero exec calls; an interrupted
    prefix asks only for its first missing proposal. The host must isolate the
    configured executable's filesystem when the target is untrusted: the JSON
    boundary does not grant the child access to fixtures, but is not an OS jail.
    """
    if type(max_turns) is not int or not 1 <= max_turns <= 128:
        raise ValueError("target trial max_turns must be in [1, 128]")
    if not math.isfinite(timeout) or timeout <= 0 or not harness_command.strip():
        raise ValueError("target trial requires a nonempty harness and positive finite timeout")
    loaded, row, manifest = _qualified(Path(corpus), query_id)
    limits = ServingLimits(max_runs=1, max_runs_per_principal=1, max_calls_per_run=max_turns,
                           max_tools=512, max_request_bytes=65536, max_response_bytes=262144)
    service = ConnectorEvaluationService([row], loaded.connector_data.records, limits=limits)
    tools = _tools(service)
    entry = _receipt("input", query_id=query_id, trial_id=trial_id, world_digest=world_digest,
                     corpus_digest=manifest["corpus_digest"], rows_digest=manifest["rows_digest"],
                     proofs_digest=manifest["proofs_digest"], tools_digest=digest(tools),
                     harness_digest=digest(harness_command), timeout=timeout, max_turns=max_turns)
    destination = Path(root)
    destination.mkdir(parents=True, exist_ok=True)
    _save(destination / "input.json", entry)
    # A missing prefix cannot silently cause another external execution when
    # later receipts prove that the supposedly missing proposal already ran.
    proposals = sorted(destination.glob("proposal-*.json"))
    if [path.name for path in proposals] != [f"proposal-{index:04d}.json" for index in range(1, len(proposals) + 1)]:
        raise ValueError("target trial receipts have a missing proposal prefix")
    if len(proposals) > max_turns:
        raise ValueError("target trial receipts exceed the configured turn budget")
    observations = sorted(destination.glob("observation-*.json"))
    if [path.name for path in observations] != [f"observation-{index:04d}.json" for index in range(1, len(observations) + 1)]:
        raise ValueError("target trial receipts have a missing observation prefix")
    if not len(proposals) - 1 <= len(observations) <= len(proposals):
        raise ValueError("target trial receipts contain an unbound observation")
    final_path = destination / "result.json"
    recorded_result = (TrialReceipt.model_validate_json(final_path.read_text(encoding="utf-8"))
                       if final_path.exists() else None)
    if recorded_result and recorded_result.body.get("turns") != len(proposals):
        raise ValueError("target trial result has a missing proposal prefix")
    run_id = service.begin(_PRINCIPAL, query_id)["run_id"]
    history: list[dict[str, Any]] = []
    span_count = 0
    previous = entry.receipt_digest
    stopped = "turn_budget"
    try:
        for number in range(1, max_turns + 1):
            request = {
                "schema": PROTOCOL, "request_id": digest([entry.receipt_digest, number, previous]),
                "query": row["query"], "tools": tools, "history": history,
                "remaining_turns": max_turns - number + 1,
                "instructions": (
                    "Carry out the question using the supplied connector tools. Return exactly one JSON object "
                    "matching response_schema and echo request_id. Propose one tool call with native arguments, "
                    "or return a final answer. Tool calls execute in an isolated company snapshot. Only returned "
                    "observations establish what happened. Discover record identifiers using available searches "
                    "when needed. Do not claim a grade, invent a tool response or return internal trace fields."
                ),
                "response_schema": AgentTurn.model_json_schema(),
            }
            if len(json.dumps(request, allow_nan=False).encode()) > MAX_DOCUMENT_BYTES:
                stopped = "context_budget"
                break
            proposal_path = destination / f"proposal-{number:04d}.json"
            if proposal_path.exists():
                proposal = TrialReceipt.model_validate_json(proposal_path.read_text(encoding="utf-8"))
                reply = AgentTurn.model_validate(proposal.body.get("reply"))
            else:
                if recorded_result is not None:
                    raise ValueError("completed target trial is missing a proposal")
                raw = execseam.run_exec(harness_command, request, timeout=timeout).document
                if len(json.dumps(raw, allow_nan=False).encode()) > MAX_DOCUMENT_BYTES:
                    raise ValueError("target trial response exceeds 4 MB")
                reply = AgentTurn.model_validate(raw)
            if reply.request_id != request["request_id"]:
                raise ValueError("target trial response request_id does not match")
            proposal = _receipt("proposal", input_digest=entry.receipt_digest, previous_digest=previous,
                                request_digest=digest(request), reply=reply.model_dump(mode="json"))
            _save(proposal_path, proposal)
            observation: dict[str, Any] | None = None
            if reply.call is not None:
                try:
                    result = service.call(_PRINCIPAL, run_id, reply.call.tool, reply.call.arguments)
                    observation = {"result": result}
                except ConnectorError as error:
                    observation = {"error": {"code": error.code, "kind": error.kind, "message": error.message}}
                except ServingError as error:
                    observation = {"error": {"kind": "invalid_tool_call", "message": str(error)}}
            observed_spans = _trace(service, run_id)
            receipt = _receipt("observation", proposal_digest=proposal.receipt_digest,
                               observation=observation, spans=observed_spans[span_count:],
                               trace_digest=digest(observed_spans))
            span_count = len(observed_spans)
            _save(destination / f"observation-{number:04d}.json", receipt)
            history.append({"turn": number, "response": reply.model_dump(mode="json"),
                            "observation": observation})
            previous = receipt.receipt_digest
            if reply.final is not None:
                stopped = "final"
                break
        if len(history) < len(proposals):
            raise ValueError("target trial contains proposals after termination")
        spans = _trace(service, run_id)
        grade = service.grade(_PRINCIPAL, run_id)
        # The historical legacy grader does not reject unmatched writes. Keep
        # its assertions intact and refuse additional unassigned side effects;
        # otherwise completing the task and corrupting another record passes.
        unmatched = [span["id"] for span in spans if span.get("writes") and not span.get("node")]
        outcome = TrialOutcome(
            passed=not grade["fails"] and not unmatched,
            details={"protocol": PROTOCOL, "grade": grade, "unmatched_writes": unmatched,
                     "turns": len(history), "calls": sum(item["response"]["call"] is not None for item in history),
                     "stopped": stopped, "trace_digest": digest(spans), "input_digest": entry.receipt_digest,
                     "receipt_digest": previous, "evaluation": "observed_connector_contract"},
        )
        final = _receipt("result", input_digest=entry.receipt_digest, previous_digest=previous,
                         turns=len(history), outcome=outcome.model_dump(mode="json"))
        _save(final_path, final)
        return outcome
    finally:
        service.end(_PRINCIPAL, run_id)


__all__ = ["AgentToolCall", "AgentTurn", "TrialReceipt", "evaluate_trial"]
