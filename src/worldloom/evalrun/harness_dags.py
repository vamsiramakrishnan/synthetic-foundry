"""Ground configurable harness querysets in existing connector records.

The case generator chooses business cohorts, not answers. Source numbers and
identities come from the supplied corpus; the seed chooses cohorts and
controlled retrieval conditions. Every case compiles through EnterpriseDag
and is served and graded by the ordinary three-axis evaluator.
"""

from __future__ import annotations

import itertools
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from ..connector_data import ConnectorRecord
from ..connector_definition import (
    ConnectorDefinition,
    ConnectorFieldDefinition,
    ConnectorFieldType,
    load_connector_definition,
)
from ..enterprise_corpus import QueryFixture
from ..enterprise_dag import (
    EnterpriseDag,
    EnterpriseDagNode,
    ResultIteration,
    ResultReference,
    transform_results,
)
from ..enterprise_evidence import carries_evidence
from ..enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from ..enterprise_rows import compile_row, runtime_records
from ..ids import content_key
from ..models import Model
from ..predicates import FieldPredicate, Predicate, PredicateOp
from .agents import AgentResponse, AgentTask, ToolSurface
from .contract import CASE_SET_FILE, RECORDS_FILE, EvalCase, case_from_row

if TYPE_CHECKING:
    from ..world import World


class HarnessDagConfig(Model):
    """A bounded queryset over authentic source cohorts.

    A cohort is all approved records sharing scope and reporting period.
    Exceeding max_sources refuses that cohort instead of truncating an
    aggregate and silently changing its answer.
    """

    seed: int = 8128
    cases: int = Field(default=12, ge=1, le=128)
    source_connector: str = "sharepoint"
    source_entity: str = "xlsx"
    destination_entity: str = "docx"
    destination_parent: str = "worldloom-eval"
    value_field: str = "amount_minor"
    scope_field: str = "business_unit"
    period_field: str = "period"
    authority_field: str = "status"
    authority_value: str = "approved"
    operations: tuple[Literal["create", "update"], ...] = ("create", "update")
    response_modes: tuple[Literal["empty", "partial", "stale"], ...] = ("empty", "partial", "stale")
    min_sources: int = Field(default=2, ge=1, le=1000)
    max_sources: int = Field(default=100, ge=1, le=1000)
    max_calls: int = Field(default=128, ge=4, le=10000)
    require_evidence: bool = True

    @model_validator(mode="after")
    def _bounded(self) -> HarnessDagConfig:
        if self.max_sources < self.min_sources:
            raise ValueError("max_sources must be at least min_sources")
        if not self.operations or len(set(self.operations)) != len(self.operations):
            raise ValueError("operations must be nonempty and distinct")
        if not self.response_modes or len(set(self.response_modes)) != len(self.response_modes):
            raise ValueError("response_modes must be nonempty and distinct")
        fields = (self.value_field, self.scope_field, self.period_field, self.authority_field)
        if any(not field.strip() for field in fields) or len(set(fields)) != len(fields):
            raise ValueError("numeric, scope, period and authority fields must be distinct and nonempty")
        if set(fields) & {"total", "source_count", "evidence"}:
            raise ValueError("source fields cannot shadow the report's total, source_count or evidence fields")
        if self.source_entity == self.destination_entity:
            raise ValueError("source and destination entities must differ so a created report cannot become its own evidence")
        if not self.authority_value:
            raise ValueError("authority_value must be nonempty")
        return self


class HarnessDagTask(Model):
    """Public task parameters. No source IDs, expected answer, or private DAG."""

    case_id: str
    query: str
    connector: str
    source_entity: str
    destination_entity: str
    scope: FieldPredicate
    period: FieldPredicate
    authority: FieldPredicate
    value_field: str
    operation: Literal["create", "update"]
    destination_name: str
    destination_parent: str
    destination_id: str | None = None
    search_tool: str
    read_tool: str
    write_tool: str
    readback_tool: str
    page_size: int = Field(ge=1, le=1000)


class HarnessDagFinding(Model):
    cohort: str
    reason: str


@dataclass(frozen=True)
class HarnessDagSuite:
    config: HarnessDagConfig
    cases: tuple[EvalCase, ...]
    records: tuple[ConnectorRecord, ...]
    tasks: tuple[HarnessDagTask, ...]
    skipped: tuple[HarnessDagFinding, ...] = ()
    candidates: int = 0

    def write(self, directory: str | Path) -> Path:
        """The existing evalrun case-set format plus a separate public task view."""
        from ..corpus import write_json, write_jsonl

        root = Path(directory)
        if root.exists() and (not root.is_dir() or any(root.iterdir())):
            raise ValueError(f"case-set destination is not empty: {root}")
        root.mkdir(parents=True, exist_ok=True)
        write_jsonl(root / CASE_SET_FILE, list(self.cases))
        write_jsonl(root / RECORDS_FILE, list(self.records))
        write_jsonl(root / "public-tasks.jsonl", list(self.tasks))
        write_json(root / "harness-dags.json", {
            "schema": "worldloom.harness-dags/v1", "config": self.config.model_dump(mode="json"),
            "cases": len(self.cases), "candidates": self.candidates,
            "source": "supplied-connector-records", "skipped": [item.model_dump(mode="json") for item in self.skipped],
        })
        return root


def _fields(config: HarnessDagConfig) -> tuple[ConnectorFieldDefinition, ...]:
    names: tuple[tuple[str, ConnectorFieldType], ...] = (
        (config.scope_field, "text"), (config.period_field, "text"),
        (config.authority_field, "text"), (config.value_field, "number"),
        ("total", "json"), ("evidence", "json"), ("source_count", "integer"),
    )
    return tuple(ConnectorFieldDefinition(
        id=name, canonical=name, name=name.replace("_", " "), field_type=kind,
    ) for name, kind in names)


def _numeric_total(records: Iterable[ConnectorRecord], field: str) -> int | str:
    node = EnterpriseDagNode(id="total", kind="transform", connector="model", entity="value",
                             operation="aggregate", transform="aggregate", depends_on=("records",),
                             arguments={"aggregate": "sum", "path": [field]})
    return transform_results(node, {"records": [record.fields for record in records]})[0]["value"]  # type: ignore[no-any-return]


def build_harness_dags(
    records: Iterable[ConnectorRecord], config: HarnessDagConfig | None = None,
    *, definitions: Mapping[str, ConnectorDefinition] | None = None,
) -> HarnessDagSuite:
    """Compile real source cohorts into search/read/analyse/write/readback cases.

    Missing data is an explicit finding. There is no filler-source fallback.
    Records from the same business cohort share a split family even when the
    query, mutation or retrieval condition changes.
    """
    config = config or HarnessDagConfig()
    materialized = tuple(sorted(records, key=lambda record: record.id))
    if len({record.id for record in materialized}) != len(materialized):
        raise ValueError("source record IDs must be unique")
    available = dict(definitions or {})
    definition = available.get(config.source_connector) or load_connector_definition(config.source_connector)
    for entity in (config.source_entity, config.destination_entity):
        definition = definition.with_fields(entity, _fields(config))
    available[config.source_connector] = definition
    groups: dict[tuple[str, str], list[ConnectorRecord]] = {}
    findings: list[HarnessDagFinding] = []
    for record in materialized:
        if (record.connector, record.entity) != (config.source_connector, config.source_entity):
            continue
        fields = record.fields
        scope, period = fields.get(config.scope_field), fields.get(config.period_field)
        if not isinstance(scope, str) or not scope or not isinstance(period, str) or not period:
            findings.append(HarnessDagFinding(cohort=record.id, reason="missing_scope_or_period"))
            continue
        if fields.get(config.authority_field) != config.authority_value:
            continue
        groups.setdefault((scope, period), []).append(record)
    eligible: list[tuple[tuple[str, str], tuple[ConnectorRecord, ...]]] = []
    for key, values in sorted(groups.items()):
        reason = None
        if not config.min_sources <= len(values) <= config.max_sources:
            reason = f"source_count:{len(values)} outside [{config.min_sources},{config.max_sources}]"
        elif config.require_evidence and any(not carries_evidence(record) for record in values):
            reason = "source_without_canonical_evidence"
        else:
            try:
                _numeric_total(values, config.value_field)
            except (KeyError, TypeError, ValueError) as error:
                reason = f"invalid_numeric_source:{error}"
        if reason is not None:
            findings.append(HarnessDagFinding(cohort="/".join(key), reason=reason))
        else:
            eligible.append((key, tuple(values)))
    eligible.sort(key=lambda item: content_key("harness-cohort", config.seed, *item[0]))
    if not eligible:
        reasons = "; ".join(f"{item.cohort}: {item.reason}" for item in findings[:8])
        raise ValueError(f"no grounded harness cohorts for {config.source_connector}/{config.source_entity}: {reasons or 'no approved sources'}")
    variants = tuple(itertools.product(config.operations, config.response_modes))
    candidates = len(eligible) * len(variants)
    cases: list[EvalCase] = []
    tasks: list[HarnessDagTask] = []
    destinations: list[ConnectorRecord] = []
    # Interleave business cohorts before varying conditions, so a small budget
    # cannot accidentally spend every case on one company's one period.
    for operation, response_mode in variants:
        for key, sources in eligible:
            if len(cases) >= config.cases:
                break
            search_tool = definition.tool(definition.tool_for(config.source_entity, "search"))
            page_size = min(search_tool.page_size, search_tool.max_results, config.max_sources)
            pages = (len(sources) + page_size - 1) // page_size
            minimum_calls = len(sources) + pages + 2 + (operation == "update")
            if minimum_calls > config.max_calls:
                findings.append(HarnessDagFinding(cohort="/".join(key), reason=f"call_budget:{minimum_calls}>{config.max_calls}"))
                continue
            if response_mode == "stale" and not any(
                    record.connector == config.source_connector and record.entity == config.source_entity
                    and record.fields.get(config.scope_field) == key[0]
                    and record.fields.get(config.period_field) == key[1]
                    and record.fields.get(config.authority_field) not in (None, config.authority_value)
                    for record in materialized):
                findings.append(HarnessDagFinding(cohort="/".join(key), reason="stale_response_without_stale_source"))
                continue
            case, task, destination = _compile_case(config, key, sources, materialized, available, operation, response_mode)
            cases.append(case)
            tasks.append(task)
            if destination is not None:
                destinations.append(destination)
    if not cases:
        raise ValueError("no harness cases fit the call budget: " + "; ".join(item.reason for item in findings[:8]))
    return HarnessDagSuite(config=config, cases=tuple(cases), tasks=tuple(tasks),
                           records=tuple(sorted((*materialized, *destinations), key=lambda record: record.id)),
                           skipped=tuple(findings), candidates=candidates)


def build_world_harness_dags(world: World, config: HarnessDagConfig | None = None) -> HarnessDagSuite:
    """Project a World's actual connector records; absent business fields refuse."""
    from ..connector_data import generate_connector_data

    selected = config or HarnessDagConfig()
    return build_harness_dags(generate_connector_data(world, connectors=(selected.source_connector,)).records, selected)


def _compile_case(
    config: HarnessDagConfig, key: tuple[str, str], sources: tuple[ConnectorRecord, ...],
    records: tuple[ConnectorRecord, ...], definitions: Mapping[str, ConnectorDefinition],
    operation: Literal["create", "update"], response_mode: Literal["empty", "partial", "stale"],
) -> tuple[EvalCase, HarnessDagTask, ConnectorRecord | None]:
    from .retrieval import QueryIntent, ResponsePolicy, RetrievalContract

    scope, period = key
    family_evidence = tuple(sorted({str(record.fields["source_family"]) for record in sources if record.fields.get("source_family")}))
    if not family_evidence:
        family_evidence = tuple(sorted({fact for record in sources for fact in record.fact_ids}))
    if not family_evidence:
        family_evidence = tuple(record.id for record in sources)
    cohort_id = content_key("harness-cohort/v1", scope, period, *family_evidence)
    case_id = "hdag-" + content_key(config.seed, cohort_id, operation, response_mode)[:24]
    definition = definitions[config.source_connector]
    search_tool = definition.tool_for(config.source_entity, "search")
    read_tool = definition.tool_for(config.source_entity, "read")
    write_tool = definition.tool_for(config.destination_entity, operation)
    readback_tool = definition.tool_for(config.destination_entity, "read")
    predicates = (FieldPredicate(field=config.scope_field, value=scope),
                  FieldPredicate(field=config.period_field, value=period),
                  FieldPredicate(field=config.authority_field, value=config.authority_value))
    predicate = Predicate(entity=config.source_entity, where=predicates)
    search_fields = ("id", "name", config.scope_field, config.period_field, config.authority_field)
    page_size = min(definition.tool(search_tool).page_size, definition.tool(search_tool).max_results, config.max_sources)
    destination_name = f"{scope} {period} reconciliation {case_id[-6:]}"
    destination = None
    if operation == "update":
        destination = ConnectorRecord(id=f"destination-{case_id}", external_id=f"destination-{case_id}",
                                      connector=config.source_connector, entity=config.destination_entity,
                                      title=destination_name, fields={"name": destination_name, "total": None,
                                      "evidence": [], "source_count": 0, "manual_note": "Keep the controller's sign-off."})
    request = (f"For {scope} in {period}, reconcile every {config.authority_value} {config.source_entity} source "
               f"in {config.source_connector}. Filter {config.scope_field}={scope!r}, {config.period_field}={period!r}, "
               f"and {config.authority_field}={config.authority_value!r}. Read each complete source and sum its "
               f"{config.value_field}. {operation.capitalize()} the {config.destination_entity} report "
               f"{destination_name!r}" + (f" (ID {destination.external_id})" if destination else f" in {config.destination_parent!r}") +
               " with total, source_count, and evidence containing the source IDs in ascending order. Preserve existing unrelated fields. "
               "Read the report back and verify those values. If a search is incomplete, refine it using the returned "
               "feedback; do not repeat an unchanged query. Search returns metadata, so fetch each source to obtain the amounts.")
    task = HarnessDagTask(case_id=case_id, query=request, connector=config.source_connector,
                          source_entity=config.source_entity, destination_entity=config.destination_entity,
                          scope=predicates[0], period=predicates[1], authority=predicates[2], value_field=config.value_field,
                          operation=operation, destination_name=destination_name,
                          destination_parent=config.destination_parent,
                          destination_id=destination.external_id if destination else None,
                          search_tool=search_tool, read_tool=read_tool, write_tool=write_tool,
                          readback_tool=readback_tool, page_size=page_size)
    search = EnterpriseDagNode(id="find", kind="search", connector=config.source_connector, entity=config.source_entity,
                               operation="search", source_index=0,
                               arguments={"predicate": predicate.model_dump(mode="json"), "fields": list(search_fields),
                                          "max_results": len(sources)})
    read = EnterpriseDagNode(id="read", kind="read", connector=config.source_connector, entity=config.source_entity,
                             operation="read", depends_on=("find",), for_each=ResultIteration(node="find", limit=config.max_sources, order="any"),
                             bindings={"id": ResultReference(node="find", path=("payload", "id"), select="item")})
    aggregate = EnterpriseDagNode(id="aggregate", kind="transform", connector="model", entity="value",
                                  operation="aggregate", transform="aggregate", depends_on=("read",),
                                  arguments={"aggregate": "sum", "path": ["payload", config.value_field],
                                             "evidence_path": ["payload", "id"]})
    nodes = [search, read, aggregate]
    if destination is not None:
        nodes.append(EnterpriseDagNode(id="inspect-destination", kind="verify", connector=config.source_connector,
                                      entity=config.destination_entity, operation="read",
                                      arguments={"id": destination.external_id}))
    write_dependencies = ("aggregate", "read") + (("inspect-destination",) if destination else ())
    arguments: dict[str, Any] = {"name": destination_name, "parent": config.destination_parent} if operation == "create" else {}
    bindings = {"fields.total": ResultReference(node="aggregate", path=("value",)),
                "fields.source_count": ResultReference(node="aggregate", path=("count",)),
                "fields.evidence": ResultReference(node="aggregate", path=("evidence",))}
    if destination is not None:
        bindings["id"] = ResultReference(node="inspect-destination", path=("payload", "id"))
    nodes.append(EnterpriseDagNode(id="write", kind="write", connector=config.source_connector,
                                  entity=config.destination_entity, operation=operation, depends_on=write_dependencies,
                                  arguments=arguments, bindings=bindings))
    nodes.append(EnterpriseDagNode(id="verify", kind="verify", connector=config.source_connector,
                                  entity=config.destination_entity, operation="read", depends_on=("write",),
                                  bindings={"id": ResultReference(node="write", path=("payload", "id"))}))
    dag = EnterpriseDag(nodes=tuple(nodes), max_calls=config.max_calls)
    dimensions = {"dag_grammar": dag.version, "dag_shape": "evidence-reconciliation", "operation": operation,
                  "retrieval_response": response_mode, "family_id": cohort_id,
                  "source_connector": config.source_connector, "source_entity": config.source_entity}
    planned = PlannedEnterpriseQuery(id=case_id, query=request, workflow="evidence_reconciliation", dimensions=dimensions,
        generation=GenerationRequirement(process="financial_reconciliation", source_requirements=(SourceRequirement(
            connector=config.source_connector, entity=config.source_entity, minimum=len(sources),
            predicate=predicate, bind="predicate", field_definitions=_fields(config)),),
            mutation=MutationRequirement(connector=config.source_connector, entity=config.destination_entity,
                operation=operation, output_format=config.destination_entity, preexisting_record=operation == "update")),
        expected_dag=tuple(node.model_dump(mode="json") for node in dag.nodes))
    fixture = QueryFixture(query_id=case_id, input_record_ids={f"{config.source_connector}:{config.source_entity}":
                               tuple(record.id for record in sources)},
                           destination_record_id=destination.id if destination else None, overrides=(),
                           expected_side_effects=(operation,), expected_fact_ids=tuple(sorted({fact for record in sources for fact in record.fact_ids})))
    row = compile_row(planned, fixture, runtime_records((*records, *((destination,) if destination else ()))), definitions=definitions)
    # The generic compiler supplies reference-only create names and parents.
    # These cases have a complete public destination contract, so retain only
    # those authored arguments; the agent must not guess compiler defaults.
    next(node for node in row["expected_dag"]["nodes"] if node["id"] == "write")["payload"] = arguments
    row["max_calls"] = config.max_calls
    hint = (f"Results are insufficient for a final reconciliation. Constrain {config.scope_field}, "
            f"{config.period_field}, and {config.authority_field} to the values in the request.")
    policy = ResponsePolicy(mode=response_mode, limit=1 if response_mode == "partial" else None,
                            selector=Predicate(where=(FieldPredicate(field=config.authority_field, op=PredicateOp.NE, value=config.authority_value),))
                            if response_mode == "stale" else None, hint=hint)
    contract = RetrievalContract(id=f"retrieval-{case_id}", connector=config.source_connector, tool=search_tool,
                                 intent=QueryIntent(entity=config.source_entity, scope=(predicates[0],), period=(predicates[1],),
                                                    authority=(predicates[2],)), on_insufficient=policy)
    row["controlled_retrieval"] = contract.model_dump(mode="json")
    case = case_from_row(row, query=request, dimensions=dimensions)
    total = _numeric_total(sources, config.value_field)
    expected_fields = {"total": total, "source_count": len(sources), "evidence": sorted(record.external_id for record in sources)}
    # The aggregate's canonical value is pinned separately on the outcome
    # axis; an absent/wrong computation cannot pass merely by creating a file.
    structured = tuple(item.model_copy(update={"fields": expected_fields}) if item.node == "write" else item
                       for item in case.outcomes.structured)
    unstructured = case.outcomes.unstructured
    if unstructured is not None:
        unstructured = unstructured.model_copy(update={"required_records": tuple(record.external_id for record in sources)})
    case = case.model_copy(update={"outcomes": case.outcomes.model_copy(update={"structured": structured, "unstructured": unstructured})})
    return case, task, destination


class HarnessDagReference:
    """A reference worker given public task parameters and tools, never cases.

    `refine=True` deliberately starts with scope alone, then uses the declared
    insufficient-result feedback to refine. It proves the recovery path. The
    direct worker proves that starting with a sufficient query also passes.
    Neither worker receives source identities or the expected aggregate.
    """

    name = "harness-dag-public-reference"

    def __init__(self, tasks: Iterable[HarnessDagTask], *, refine: bool = False) -> None:
        self._tasks = {task.case_id: task for task in tasks}
        self.refine = refine

    def run(self, task: AgentTask, tools: ToolSurface) -> AgentResponse:
        public = self._tasks[task.case_id]
        if public.query != task.query:
            raise ValueError("public request does not match the running task")
        prefix = public.connector + "."
        search_fields = ["id", "name", public.scope.field, public.period.field, public.authority.field]
        if self.refine:
            response = tools.call(prefix + public.search_tool, entity=public.source_entity,
                                  predicate=Predicate(entity=public.source_entity, where=(public.scope,)).model_dump(mode="json"),
                                  fields=search_fields, max_results=public.page_size)
            if not isinstance(response, Mapping):
                raise ValueError("search must return a result envelope")
            feedback = response.get("retrieval")
            if not isinstance(feedback, Mapping) or not feedback.get("hint"):
                raise ValueError("recovery requires public insufficient-result feedback")
        rows: list[Mapping[str, Any]] = []
        start = 0
        predicate = Predicate(entity=public.source_entity, where=(public.scope, public.period, public.authority))
        while True:
            response = tools.call(prefix + public.search_tool, entity=public.source_entity,
                                  predicate=predicate.model_dump(mode="json"), fields=search_fields,
                                  max_results=public.page_size, start_at=start)
            rows.extend(response["items"])
            if response.get("is_last") or not response["items"]:
                break
            start += len(response["items"])
        documents = [tools.call(prefix + public.read_tool, id=record["id"]) for record in rows]
        node = EnterpriseDagNode(id="sum", kind="transform", connector="model", entity="value", operation="aggregate",
                                 transform="aggregate", depends_on=("read",), arguments={"path": [public.value_field]})
        computed = transform_results(node, {"read": documents})[0]
        fields = {"total": computed["value"], "source_count": computed["count"],
                  "evidence": sorted(record["id"] for record in documents)}
        if public.operation == "update":
            inspected = tools.call(prefix + public.readback_tool, id=public.destination_id)
            result = tools.call(prefix + public.write_tool, id=inspected["id"], fields=fields)
        else:
            result = tools.call(prefix + public.write_tool, entity=public.destination_entity,
                                name=public.destination_name, parent=public.destination_parent, fields=fields)
        final = tools.call(prefix + public.readback_tool, id=result["id"])
        if any(final.get(key) != value for key, value in fields.items()):
            raise ValueError("readback did not preserve the computed values")
        return AgentResponse(answer=f"Verified {public.destination_name}: total {computed['value']} from {computed['count']} sources.")


__all__ = ["HarnessDagConfig", "HarnessDagTask", "HarnessDagFinding", "HarnessDagSuite", "HarnessDagReference",
           "build_harness_dags", "build_world_harness_dags"]
