"""Controlled retrieval measures a harness's query decisions, not a search index.

The evaluator declares semantic requirements and a response policy before a run.
Queries use the existing Predicate language; accepted aliases normalize to that
same language. The connector selects real, ACL-visible records, with no ranking
threshold and no answer inserted by the oracle. Insufficient queries may expose
a declared subset and a static hint. Only the evaluator sees the assessment.

Receipts record what the service delivered, not what an agent claims to have
read. Delivery establishes access, not mental use of a source. Answer grounding
and state changes remain the outcome grader's responsibility.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from ..models import Model
from ..predicates import (
    FieldPredicate,
    Predicate,
    PredicateOp,
    QueryContext,
    RelativeTime,
    evaluate,
    evaluate_field,
)
from ..providers import digest

if TYPE_CHECKING:
    from ..connector_definition import ConnectorDefinition
    from ..connector_emulator import ConnectorSpan

IntentStatus = Literal["sufficient", "insufficient", "invalid_query", "unsupported_query", "transport_fault", "tool_error"]
Progress = Literal["initial", "refinement", "pagination", "retry", "no_progress"]


class UnsupportedControlledQuery(ValueError):
    """The controlled semantic evaluator does not claim native search parity."""


class QueryIntent(Model):
    """Required query semantics, private to the evaluator.

    Dimensions are named so a failure can drive the next curriculum. Their
    predicates still use Worldloom's one shared field and operator vocabulary.
    Extra constraints are allowed; a contradictory extra constraint naturally
    produces no records and cannot pass the ordinary outcome assertions.
    """

    entity: str | None = None
    operation: Literal["search"] = "search"
    scope: tuple[FieldPredicate, ...] = ()
    period: tuple[FieldPredicate, ...] = ()
    authority: tuple[FieldPredicate, ...] = ()

    @model_validator(mode="after")
    def _valid(self) -> QueryIntent:
        fields = [item.field for _, item in self.clauses()]
        if len(fields) != len(set(fields)):
            raise ValueError("intent dimensions must constrain distinct fields")
        if not fields and self.entity is None:
            raise ValueError("controlled retrieval needs an entity or a field requirement")
        if any(isinstance(item.value, RelativeTime) for _, item in self.clauses()):
            raise ValueError("retrieval intent requires explicit periods, not relative time")
        return self

    def clauses(self) -> tuple[tuple[str, FieldPredicate], ...]:
        return tuple((dimension, item) for dimension in ("scope", "period", "authority")
                     for item in getattr(self, dimension))

    def predicate(self) -> Predicate:
        return Predicate(entity=self.entity, where=tuple(item for _, item in self.clauses()))


class QueryAlias(Model):
    """Equivalent values for one semantic field, never whole prompt strings."""

    field: str = Field(min_length=1)
    canonical: str = Field(min_length=1)
    alternatives: tuple[str, ...] = ()


class ResponsePolicy(Model):
    """An insufficient query can reveal only its real matching records.

    A stale response requires an explicit selector over corpus metadata. A
    partial response requires a selector or cap. Hints are authored scenario
    text, never synthesized from private requirements or expected answers.
    """

    mode: Literal["empty", "partial", "stale"] = "empty"
    selector: Predicate | None = None
    limit: int | None = Field(default=None, ge=1)
    hint: str = ""

    @model_validator(mode="after")
    def _valid(self) -> ResponsePolicy:
        if self.mode == "stale" and self.selector is None:
            raise ValueError("stale response requires an explicit source selector")
        if self.mode == "partial" and self.selector is None and self.limit is None:
            raise ValueError("partial response requires a selector or limit")
        if self.selector is not None and (self.selector.joins or self.selector.as_of is not None):
            raise ValueError("response selectors must be record-local")
        return self


class RetrievalFault(Model):
    """A transient transport failure at a fixed controlled-tool attempt."""

    attempt: int = Field(ge=1)
    kind: Literal["timeout", "rate_limit"] = "timeout"


class RetrievalContract(Model):
    id: str = Field(min_length=1)
    connector: str = Field(min_length=1)
    tool: str = Field(min_length=1)
    intent: QueryIntent
    on_insufficient: ResponsePolicy = Field(default_factory=ResponsePolicy)
    aliases: tuple[QueryAlias, ...] = ()
    faults: tuple[RetrievalFault, ...] = ()

    @model_validator(mode="after")
    def _valid(self) -> RetrievalContract:
        seen: dict[tuple[str, str], str] = {}
        for alias in self.aliases:
            for spelling in (alias.canonical, *alias.alternatives):
                key = (alias.field, spelling.casefold())
                if key in seen and seen[key] != alias.canonical:
                    raise ValueError(f"conflicting query alias for {alias.field!r}: {spelling!r}")
                seen[key] = alias.canonical
        attempts = [fault.attempt for fault in self.faults]
        if len(attempts) != len(set(attempts)):
            raise ValueError("only one retrieval fault may occur at an attempt")
        return self


class DeliveryReceipt(Model):
    record_id: str
    source_digest: str
    payload_digest: str


class RetrievalReceipt(Model):
    contract_id: str
    span_id: str
    ordinal: int
    tool: str
    intent_status: IntentStatus
    error_kind: str | None = None
    missing_dimensions: tuple[str, ...] = ()
    satisfied: tuple[str, ...] = ()
    query_digest: str
    returned: tuple[DeliveryReceipt, ...] = ()
    response_digest: str | None = None
    start_at: int = 0
    next_at: int | None = None
    is_last: bool = True
    progress: Progress = "initial"


def _implies(actual: FieldPredicate, required: FieldPredicate) -> bool:
    """Sound, bounded implication for the shared conjunctive predicate subset.

    Merely matching the target record is insufficient: ``period != 2024`` must
    not count as identifying 2026 because this fixture happens to lack 2025.
    Unsupported implications fail closed rather than crediting a broad query.
    """
    if actual.field != required.field or isinstance(actual.value, RelativeTime):
        return False
    if actual.op is PredicateOp.EQ:
        return evaluate_field(required, {required.field: actual.value})
    if actual.op is PredicateOp.IN:
        assert isinstance(actual.value, tuple)
        return bool(actual.value) and all(evaluate_field(required, {required.field: value}) for value in actual.value)
    if actual.op is required.op and digest(actual.value) == digest(required.value):
        return True
    # CONTAINS also means list membership. A longer string is not generally
    # stronger: tags=["APAC-approved"] contains that element but not "APAC".
    # Only identical CONTAINS operands were admitted above.
    # Equal bounds require strictness in the right direction. Different bounds
    # must be comparable values; bool and null are not ordered field values.
    if actual.value is None or required.value is None or isinstance(actual.value, bool) or isinstance(required.value, bool):
        return False
    lower = {PredicateOp.GT, PredicateOp.GTE}
    upper = {PredicateOp.LT, PredicateOp.LTE}
    if actual.op in lower and required.op in lower:
        stricter = evaluate_field(required.model_copy(update={"op": PredicateOp.GT}), {required.field: actual.value})
        return stricter or (actual.value == required.value and
                            (actual.op is PredicateOp.GT or required.op is PredicateOp.GTE))
    if actual.op in upper and required.op in upper:
        stricter = evaluate_field(required.model_copy(update={"op": PredicateOp.LT}), {required.field: actual.value})
        return stricter or (actual.value == required.value and
                            (actual.op is PredicateOp.LT or required.op is PredicateOp.LTE))
    return False


class ControlledRetrieval:
    """One evaluator-owned policy and its deterministic session state.

    Bind this to a ConnectorEmulator with ``retrieval=...``. It deliberately
    does not expose a public schema containing requirements, aliases, source
    selectors, or receipts. Normal connector tool parameters remain public.
    """

    def __init__(self, contract: RetrievalContract) -> None:
        self.contract = contract
        self._definition: ConnectorDefinition | None = None
        self._receipts: list[RetrievalReceipt] = []
        self._attempts = 0
        self._active: tuple[Predicate, tuple[str, ...], tuple[str, ...]] | None = None

    @property
    def receipts(self) -> tuple[RetrievalReceipt, ...]:
        return tuple(self._receipts)

    def receipt_for(self, span_id: str) -> RetrievalReceipt | None:
        return next((receipt for receipt in reversed(self._receipts) if receipt.span_id == span_id), None)

    def reject_delivery(self, span_id: str, *, error_kind: Literal["response_limit", "timeout", "rate_limit"] = "response_limit") -> RetrievalReceipt:
        """The serving layer could not deliver the most recent result.

        A response-byte limit is applied outside the connector transaction.
        Rolling back records must not rewind this observed attempt or claim
        the discarded payload reached the harness. The service retains this
        controller while dropping the transaction's business-state changes.
        """
        if not self._receipts or self._receipts[-1].span_id != span_id:
            raise ValueError("only the latest retrieval delivery may be rejected")
        corrected = self._receipts[-1].model_copy(update={
            "intent_status": "transport_fault", "error_kind": error_kind, "returned": (),
            "response_digest": None, "next_at": None, "is_last": True,
            "progress": "initial" if len(self._receipts) == 1 else "no_progress",
        })
        self._receipts.pop()
        corrected = corrected.model_copy(update={"progress": self._progress(corrected)})
        self._receipts.append(corrected)
        return corrected

    def bind(self, definition: ConnectorDefinition) -> None:
        if self.contract.connector != definition.connector:
            raise ValueError("controlled retrieval connector does not match the emulator")
        try:
            tool = definition.tool(definition.canonical_tool(self.contract.tool))
            if self.contract.intent.entity is not None:
                members = set(definition.entity_members(self.contract.intent.entity))
                if not members <= set(tool.entities):
                    raise ValueError("controlled retrieval tool cannot search the required entity")
        except KeyError as error:
            raise ValueError("controlled retrieval requires a declared connector tool and entity") from error
        if tool.op != self.contract.intent.operation:
            raise ValueError("controlled retrieval tool does not implement the required operation")
        self._definition = definition

    def fork(self, *, fresh: bool = True) -> ControlledRetrieval:
        child = copy.copy(self)
        child._receipts = [] if fresh else list(self._receipts)
        child._attempts = 0 if fresh else self._attempts
        child._active = None
        return child

    def applies(self, tool_name: str) -> bool:
        assert self._definition is not None
        return self._definition.canonical_tool(tool_name) == self._definition.canonical_tool(self.contract.tool)

    def before_call(self, tool_name: str) -> None:
        if not self.applies(tool_name):
            return
        from ..connector_emulator import ConnectorError

        self._active = None
        self._attempts += 1
        for fault in self.contract.faults:
            if fault.attempt == self._attempts:
                code, message = (504, "Gateway timeout") if fault.kind == "timeout" else (429, "Too many requests")
                raise ConnectorError(code, message, fault.kind)

    def _normalise(self, predicate: Predicate) -> Predicate:
        assert self._definition is not None
        if predicate.joins or predicate.as_of is not None:
            raise ValueError("controlled retrieval requires record-local query predicates")
        bindings = {native.casefold(): semantic for semantic, native in self._definition.query_fields.items()}
        aliases = {(alias.field, spelling.casefold()): alias.canonical for alias in self.contract.aliases
                   for spelling in (alias.canonical, *alias.alternatives)}
        clauses = []
        for item in predicate.where:
            field = bindings.get(item.field.casefold(), item.field)
            value = item.value
            if isinstance(value, RelativeTime):
                value = value.resolve(datetime.fromisoformat(self._definition.clock)).isoformat()
            if isinstance(value, str):
                value = aliases.get((field, value.casefold()), value)
            elif isinstance(value, tuple):
                value = tuple(aliases.get((field, part.casefold()), part) if isinstance(part, str) else part for part in value)
                # IN order and repetitions do not make a new query or retry.
                distinct = {digest(part): part for part in value}
                value = tuple(distinct[key] for key in sorted(distinct))
            clauses.append(item.model_copy(update={"field": field, "value": value}))
        return Predicate(entity=predicate.entity, connector=predicate.connector,
                         where=tuple(sorted(clauses, key=lambda item: item.field)))

    def parse(self, *, query: str | None = None, predicate: Predicate | Mapping[str, Any] | None = None,
              entity: str | None = None, name: str | None = None) -> Predicate:
        from ..connector_emulator import _coerce_predicate

        assert self._definition is not None
        if sum(value is not None for value in (query, predicate, name)) > 1:
            raise ValueError("controlled retrieval accepts one of query, predicate, or name")
        if predicate is not None:
            active = _coerce_predicate(predicate, entity=entity)
        elif query is not None:
            # Native comparators include case folding, coercion, lists, and
            # vendor null defaults. Translating their syntax into Predicate
            # would silently change meaning. Native query execution remains
            # available in ordinary connector mode; this mode is explicit.
            raise UnsupportedControlledQuery(
                "Controlled retrieval accepts typed predicates, not native query text; "
                "use predicate={\"where\":[{\"field\":\"...\",\"op\":\"eq\",\"value\":\"...\"}]}"
            )
        elif name is not None:
            active = Predicate(entity=entity, where=(FieldPredicate(field="name", value=name),))
        else:
            active = Predicate(entity=entity)
        return self._normalise(active)

    def _assessment(self, predicate: Predicate) -> tuple[tuple[str, ...], tuple[str, ...]]:
        assert self._definition is not None
        missing: set[str] = set()
        satisfied: list[str] = []
        if predicate.connector is not None and predicate.connector != self.contract.connector:
            missing.add("scope")
        required_entity = self.contract.intent.entity
        if required_entity is not None:
            try:
                actual_members = set(self._definition.entity_members(predicate.entity)) if predicate.entity else set()
                required_members = set(self._definition.entity_members(required_entity))
                matches = bool(actual_members) and actual_members <= required_members
            except KeyError:
                matches = False
            if matches:
                satisfied.append("entity")
            else:
                missing.add("entity")
        by_field = {item.field: item for item in predicate.where}
        for dimension, required in self.contract.intent.clauses():
            actual = by_field.get(required.field)
            if actual is not None and _implies(actual, required):
                satisfied.append(f"{dimension}:{required.field}")
            else:
                missing.add(dimension)
        return tuple(sorted(missing)), tuple(sorted(satisfied))

    def select(self, predicate: Predicate, records: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
        assert self._definition is not None
        missing, satisfied = self._assessment(predicate)
        self._active = (predicate, missing, satisfied)
        # Pool membership, visibility, entity aliases and native payloads remain
        # owned by the connector. This evaluator does not bypass its ACLs.
        active = predicate
        if active.entity is not None and active.entity not in self._definition.entities:
            active = active.model_copy(update={"entity": None})
        context = QueryContext(clock=datetime.fromisoformat(self._definition.clock))
        hits = [dict(record) for record in records if evaluate(active, record, context=context)]
        hits.sort(key=lambda record: str(record["fid"]))
        if missing:
            policy = self.contract.on_insufficient
            if policy.mode == "empty":
                return []
            if policy.selector is not None:
                hits = [record for record in hits if evaluate(policy.selector, record, context=context)]
            if policy.limit is not None:
                hits = hits[:policy.limit]
        return hits

    def public_info(self) -> dict[str, str]:
        if self._active is None or not self._active[1]:
            return {"mode": "controlled", "completeness": "complete"}
        policy = self.contract.on_insufficient
        info = {"mode": "controlled", "completeness": policy.mode}
        if policy.hint:
            info["hint"] = policy.hint
        return info

    def qualify(self, records: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
        """Prove a sufficient query can expose real records before calling a target.

        The caller supplies the tool's ACL-filtered pool, as its service owns
        ACL and entity interpretation. This method never stores expected data
        in a tool response or rewrites a source record.
        """
        active = self._active
        try:
            assert self._definition is not None
            tool = self._definition.tool(self._definition.canonical_tool(self.contract.tool))
            requested = self.contract.intent.entity
            members = set(self._definition.entity_members(requested)) if requested else set(tool.entities)
            admitted = members | ({requested} if requested else {
                alias for alias, kinds in self._definition.entity_aliases.items() if set(kinds) <= members
            })
            pool = tuple(record for record in records if record.get("entity") in admitted)
            hits = self.select(self._normalise(self.contract.intent.predicate()), pool)
        finally:
            self._active = active
        if not hits:
            raise ValueError(f"{self.contract.id}: sufficient retrieval intent has no visible source")
        return tuple(str(record["fid"]) for record in hits)

    def observe(self, span: ConnectorSpan, result: Any, records: Mapping[str, Mapping[str, Any]]) -> None:
        if not self.applies(span.tool.split(".", 1)[1]):
            return
        error = span.error or {}
        active = self._active
        if active is None:
            try:
                parsed = self.parse(**{key: span.args[key] for key in ("query", "predicate", "entity", "name") if key in span.args})
                missing, satisfied = self._assessment(parsed)
                active = (parsed, missing, satisfied)
            except (ValueError, KeyError):
                active = None
        if error:
            status: IntentStatus = ("transport_fault" if error.get("kind") in {"timeout", "rate_limit", "response_limit"}
                                    else "invalid_query" if error.get("kind") == "validation"
                                    else "unsupported_query" if error.get("kind") == "unsupported_query" else "tool_error")
        else:
            status = "sufficient" if active is not None and not active[1] else "insufficient"
        payload = active[0].model_dump(mode="json") if active is not None else span.args
        query_digest = digest({"tool": span.tool, "query": payload, "fields": sorted(span.args.get("fields") or ())})
        page = result if isinstance(result, Mapping) else {}
        deliveries = tuple(DeliveryReceipt(record_id=fid, source_digest=digest(records[fid]), payload_digest=digest(item))
                           for fid, item in zip(span.reads, page.get("items", ()), strict=True)) if not error else ()
        start_at = int(span.args.get("start_at", 0))
        is_last = bool(page.get("is_last", True))
        receipt = RetrievalReceipt(
            contract_id=self.contract.id, span_id=span.id, ordinal=span.ordinal, tool=span.tool,
            intent_status=status, error_kind=str(error["kind"]) if error else None,
            missing_dimensions=active[1] if active else (), satisfied=active[2] if active else (),
            query_digest=query_digest, returned=deliveries, response_digest=digest(result) if not error else None,
            start_at=start_at, next_at=start_at + int(page.get("max_results", 0)) if not is_last else None,
            is_last=is_last,
        )
        self._receipts.append(receipt.model_copy(update={"progress": self._progress(receipt)}))
        self._active = None

    def _progress(self, current: RetrievalReceipt) -> Progress:
        if not self._receipts:
            return "initial"
        previous = self._receipts[-1]
        same = current.query_digest == previous.query_digest and current.start_at == previous.start_at
        if (same and previous.intent_status == "transport_fault"
                and current.intent_status in {"sufficient", "insufficient", "transport_fault"}):
            return "retry"
        if current.intent_status not in {"sufficient", "insufficient"}:
            return "no_progress"
        if previous.intent_status in {"unsupported_query", "invalid_query"} and current.intent_status == "sufficient":
            return "refinement"
        if current.query_digest == previous.query_digest and previous.next_at == current.start_at and current.returned:
            earlier = [receipt for receipt in self._receipts if receipt.query_digest == current.query_digest]
            delivered = {item.record_id for receipt in earlier for item in receipt.returned}
            if (not any(receipt.start_at == current.start_at and receipt.returned for receipt in earlier)
                    and all(item.record_id not in delivered for item in current.returned)):
                return "pagination"
        if previous.intent_status == "insufficient" and set(current.satisfied) > set(previous.satisfied):
            return "refinement"
        return "no_progress"


__all__ = ["QueryIntent", "QueryAlias", "ResponsePolicy", "RetrievalFault", "RetrievalContract",
           "DeliveryReceipt", "RetrievalReceipt", "ControlledRetrieval", "UnsupportedControlledQuery"]
