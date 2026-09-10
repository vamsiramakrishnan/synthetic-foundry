"""A connected retail process, recorded in the same World as the company.

The stock simulator owns quantities and a two-tick receipt lead time. This
extension adds supplier pricing and invoice matching to those same rows. It
does not import the procurement vertical's civil-contract estate, invent a
second receipt quantity, or reconcile operational money to the macro close.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from heapq import nsmallest
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from .models import EnterpriseEvent, Model
from .synthesis.compiler import compile_program, digest
from .synthesis.connectors import IncidentRule
from .synthesis.engine import Simulator
from .synthesis.models import (
    Column,
    Constraint,
    Limits,
    Program,
    Relation,
    Row,
    Table,
    expr,
    literal,
    ref,
    uniform,
)
from .synthesis.programs import retail
from .synthesis.search import with_parameters

if TYPE_CHECKING:
    from .connector_data import ConnectorRecord
    from .validate import Violation
    from .world import World

Process = Literal["inventory_exception", "supplier_replenishment", "invoice_reconciliation"]
PROCESSES: tuple[Process, ...] = ("inventory_exception", "supplier_replenishment", "invoice_reconciliation")
EVENT_KIND = "retail.connected_process"
RULE = IncidentRule(table="inventory", signal="lost", title="Inventory-led replenishment")


def connected_program(*, stores: int = 3, products: int = 6, ticks: int = 24) -> Program:
    """Reuse stock conservation, then attach supplier and invoice mechanisms.

    Alternate suppliers are clean controls. Other suppliers bill a stable
    per-unit surcharge; the invoice stays evidence of what was billed, while
    the contracted receipt value remains what is payable before approval.
    Partial deliveries and credit-note settlement are outside this mechanism.
    """
    base = with_parameters(retail(stores=stores, products=products, ticks=ticks),
                           {"initial_stock": 8, "target_stock": 15})
    r = ref
    supplier = Table(name="supplier", count=products, columns=(
        Column(name="invoice_surcharge", minimum=0, unit="minor_currency",
               expression=expr("if", expr("eq", expr("mod", r("_entity"), literal(2)), literal(0)),
                               literal(0), uniform(1, 50, stream="invoice_surcharge", scope="entity"))),
    ))
    inventory = base.tables[-1]
    columns = (
        Column(name="contract_unit_price", minimum=0, unit="minor_currency", expression=r("product.cost")),
        Column(name="invoice_unit_price", minimum=0, unit="minor_currency",
               expression=expr("add", r("contract_unit_price"), r("supplier.invoice_surcharge"))),
        Column(name="receipt_contract_value", minimum=0, unit="minor_currency",
               expression=expr("mul", r("receipts"), r("contract_unit_price"))),
        Column(name="invoice_value", minimum=0, unit="minor_currency",
               expression=expr("mul", r("receipts"), r("invoice_unit_price"))),
        Column(name="invoice_variance", minimum=0, unit="minor_currency",
               expression=expr("sub", r("invoice_value"), r("receipt_contract_value"))),
    )
    inventory = inventory.model_copy(update={
        "relations": (*inventory.relations, Relation(name="supplier", table="supplier")),
        "columns": (*inventory.columns, *columns),
        "constraints": (*inventory.constraints, Constraint(name="invoice_reconciliation",
            predicate=expr("eq", r("invoice_value"), expr("add", r("receipt_contract_value"), r("invoice_variance"))))),
    })
    return base.model_copy(update={"namespace": "retail_replenishment", "tables": (*base.tables[:-1], supplier, inventory)})


class RetailProcessScope(Model):
    process: Process
    business_unit: str = Field(min_length=1)
    activity_id: str = Field(min_length=1)
    lob: str = ""


class RetailProcess(Model):
    program: Program = Field(default_factory=connected_program)
    scopes: tuple[RetailProcessScope, ...]
    start: datetime | None = None
    max_cases: int = Field(default=32, ge=1, le=256, strict=True)

    @model_validator(mode="after")
    def _contract(self) -> RetailProcess:
        if self.start is not None and self.start.tzinfo is None:
            raise ValueError("retail process start must be timezone-aware")
        if sorted(s.process for s in self.scopes) != sorted(PROCESSES):
            raise ValueError("retail process needs exactly one scope for each connected stage")
        compile_program(self.program, limits=Limits(max_rows=100_000))
        tables = {table.name: table for table in self.program.tables}
        required = {"lost", "order", "receipts", "contract_unit_price", "invoice_unit_price",
                    "receipt_contract_value", "invoice_value", "invoice_variance"}
        inventory = tables.get("inventory")
        if (inventory is None or not inventory.temporal or self.program.ticks < 3
                or not required <= {column.name for column in inventory.columns}
                or not {"store", "product", "supplier"} <= {relation.name for relation in inventory.relations}):
            raise ValueError("retail process requires a temporal inventory, supplier pricing and invoice arithmetic")
        return self


class RetailMatch(Model):
    ordered_quantity: int = Field(ge=1, strict=True)
    received_quantity: int = Field(ge=1, strict=True)
    contract_unit_price: int = Field(ge=0, strict=True)
    invoice_unit_price: int = Field(ge=0, strict=True)
    receipt_contract_value: int = Field(ge=0, strict=True)
    invoice_value: int = Field(ge=0, strict=True)
    invoice_variance: int = Field(ge=0, strict=True)
    unit: Literal["minor_currency"] = "minor_currency"

    @model_validator(mode="after")
    def _reconcile(self) -> RetailMatch:
        if self.ordered_quantity != self.received_quantity:
            raise ValueError("this mechanism requires the actual two-tick order receipt; partial deliveries are unsupported")
        if (self.receipt_contract_value != self.received_quantity * self.contract_unit_price
                or self.invoice_value != self.received_quantity * self.invoice_unit_price
                or self.invoice_variance != self.invoice_value - self.receipt_contract_value):
            raise ValueError("invoice, contracted receipt value and variance do not reconcile")
        return self


class RetailCaseEvent(Model):
    schema_version: Literal["worldloom.retail-process-event/v1"] = "worldloom.retail-process-event/v1"
    case_id: str
    scope: RetailProcessScope
    program_digest: str
    recipe_digest: str
    history: tuple[Row, ...]
    upstream_event_ids: tuple[str, ...] = ()
    match: RetailMatch | None = None

    @model_validator(mode="after")
    def _evidence(self) -> RetailCaseEvent:
        if not self.history:
            raise ValueError("retail events require physical observation rows")
        first = self.history[0]
        if (any(row.table != "inventory" or row.entity_id != first.entity_id for row in self.history)
                or tuple(row.tick for row in self.history) != tuple(range(first.tick, first.tick + len(self.history)))):
            raise ValueError("retail history must be consecutive rows of one inventory trajectory")
        if self.case_id != digest(["episode/v1", self.recipe_digest, RULE.model_dump(mode="json"), first.id]):
            raise ValueError("retail case identity differs from its originating observation")
        if int(first.values()["lost"]) <= 0 or int(first.values()["order"]) <= 0:
            raise ValueError("retail case must begin with lost demand and a real replenishment order")
        expected_length = 1 if self.scope.process == "inventory_exception" else 3
        if len(self.history) != expected_length:
            raise ValueError("retail stage evidence disagrees with its two-tick receipt horizon")
        if len(self.upstream_event_ids) != (0 if self.scope.process == "inventory_exception" else 1):
            raise ValueError("retail stage needs its direct upstream event")
        if self.scope.process != "inventory_exception":
            if int(self.history[-1].values()["receipts"]) != int(first.values()["order"]):
                raise ValueError("retail receipt does not equal the order that caused it")
        if (self.match is not None) != (self.scope.process == "invoice_reconciliation"):
            raise ValueError("only the invoice stage carries an invoice match")
        if self.match is not None:
            amounts = self.history[-1].values()
            if self.match != _match(first, amounts):
                raise ValueError("invoice match differs from physical source rows")
        return self


def _match(order: Row, receipt: dict[str, int | bool | str]) -> RetailMatch:
    return RetailMatch(ordered_quantity=int(order.values()["order"]), received_quantity=int(receipt["receipts"]),
        contract_unit_price=int(receipt["contract_unit_price"]), invoice_unit_price=int(receipt["invoice_unit_price"]),
        receipt_contract_value=int(receipt["receipt_contract_value"]), invoice_value=int(receipt["invoice_value"]),
        invoice_variance=int(receipt["invoice_variance"]))


def case_payload(event: EnterpriseEvent) -> RetailCaseEvent | None:
    if event.kind != EVENT_KIND:
        return None
    return RetailCaseEvent.model_validate_json(event.summary)


def _histories(simulator: Simulator) -> Iterator[tuple[Row, ...]]:
    # Whole trajectories make adjacent cases share evidence when they truly
    # overlap. Dataset splitting subsequently closes those evidence components.
    recent: list[Row] = []
    for row in simulator.rows():
        if row.table != "inventory":
            continue
        if recent and recent[-1].entity_id != row.entity_id:
            recent = []
        recent = [*recent[-2:], row]
        if len(recent) == 3 and int(recent[0].values()["lost"]) > 0 and int(recent[0].values()["order"]) > 0:
            yield tuple(recent)


def build_retail_process(world: World, config: RetailProcess, *, occurred_at: datetime | None = None) -> World:
    """Record an opt-in process before eval construction and snapshot freezing."""
    from .recipe import with_step

    config = RetailProcess.model_validate(config.model_dump(mode="json"))
    if occurred_at is not None and config.start is not None and occurred_at != config.start:
        raise ValueError("retail process start differs from its declared configuration")
    occurred_at = occurred_at or config.start
    prior = [step for step in world.recipe.get("steps", ()) if step.get("scenario") == "RetailReplenishment"]
    if prior:
        if (len(prior) == 1 and prior[0]["config"] == config.model_dump(mode="json")
                and (occurred_at is None or prior[0]["occurred_at"] == occurred_at.isoformat())):
            return world
        raise ValueError("retail process already exists with a different configuration; rebuild from the company baseline")
    if world.seed is None:
        raise ValueError("retail process requires the company's recorded seed")
    units = {unit.name: unit for unit in world.business_units}
    missing = {scope.business_unit for scope in config.scopes} - units.keys()
    if missing:
        raise ValueError(f"retail process owners must be generated company business units: {sorted(missing)}")
    if occurred_at is None:
        if not world.events:
            raise ValueError("retail process needs an explicit start or an existing company timeline")
        occurred_at = max(event.occurred_at for event in world.events) + timedelta(hours=1)
    if occurred_at.tzinfo is None:
        raise ValueError("retail process start must be timezone-aware")
    simulator = Simulator(config.program, seed=world.seed, limits=Limits(max_rows=100_000))
    histories = nsmallest(config.max_cases, _histories(simulator), key=lambda history: (history[0].tick, history[0].entity_id))
    scopes = {scope.process: scope for scope in config.scopes}
    events: list[EnterpriseEvent] = []
    for history in histories[:config.max_cases]:
        first = history[0]
        case_id = digest(["episode/v1", simulator.run_digest, RULE.model_dump(mode="json"), first.id])
        parent: tuple[str, ...] = ()
        for process in PROCESSES:
            visible = history[:1] if process == "inventory_exception" else history
            payload = RetailCaseEvent(case_id=case_id, scope=scopes[process],
                program_digest=simulator.compiled.program_digest, recipe_digest=simulator.run_digest,
                history=visible, upstream_event_ids=parent,
                match=_match(first, history[-1].values()) if process == "invoice_reconciliation" else None)
            event_id = "EV-RETAIL-" + digest([world.company.id, case_id, process])[:24].upper()
            event = EnterpriseEvent(id=event_id, kind=EVENT_KIND,
                occurred_at=occurred_at + timedelta(days=visible[-1].tick,
                                                   hours=1 if process == "invoice_reconciliation" else 0),
                summary=payload.model_dump_json(), caused_by=list(parent),
                business_units=[units[scopes[process].business_unit].id])
            events.append(event)
            parent = (event_id,)
    if not events:
        raise ValueError("retail process produced no complete stock-order-receipt cases under its declared parameters")
    updated = world.extend(events=tuple(sorted(events, key=lambda event: (event.occurred_at, event.id))),
        recipe=with_step(world.recipe, "RetailReplenishment", config=config.model_dump(mode="json"),
                         occurred_at=occurred_at.isoformat()))
    return updated


def process_report(world: World) -> dict[str, Any]:
    """Report achieved physical coverage and the boundary of this mechanism."""
    payloads = [payload for event in world.events if (payload := case_payload(event)) is not None]
    cases = {payload.case_id for payload in payloads}
    matches = [payload.match for payload in payloads if payload.match is not None]
    step = next((step for step in world.recipe.get("steps", ()) if step.get("scenario") == "RetailReplenishment"), None)
    achieved: dict[str, Any] = {}
    if step is not None:
        config = RetailProcess.model_validate(step["config"])
        assert world.seed is not None
        simulator = Simulator(config.program, seed=world.seed, limits=Limits(max_rows=100_000))
        eligible = sum(1 for _ in _histories(simulator))
        pending = sum(row.table == "inventory" and row.tick >= config.program.ticks - 2
                      and int(row.values()["lost"]) > 0 and int(row.values()["order"]) > 0
                      for row in simulator.rows())
        achieved = {"maximum_cases": config.max_cases, "eligible_complete_cases": eligible,
                    "excluded_by_case_budget": max(0, eligible - len(cases)),
                    "orders_beyond_receipt_horizon": pending}
    return {"cases": len(cases), "stages": {process: sum(p.scope.process == process for p in payloads) for process in PROCESSES},
            **achieved,
            "clean_invoices": sum(match.invoice_variance == 0 for match in matches),
            "contested_invoices": sum(match.invoice_variance > 0 for match in matches),
            "scope": "operational_simulation_not_macro_reconciliation",
            "unresolved_obligations": ["Partial deliveries", "Credit-note settlement and payment approval", "Macro ledger reconciliation"]}


def project_records(world: World, connector: str) -> list[ConnectorRecord]:
    """Project real process events through the same registry all evaluators read."""
    from .connector_data import ConnectorRecord

    definition = {"jira": ("issue", "key"), "servicenow": ("incident", "sys_id"), "email": ("message", "message_id")}
    if connector not in definition:
        return []
    entity, stable_field = definition[connector]
    records: list[ConnectorRecord] = []
    for event in world.events:
        payload = case_payload(event)
        if payload is None:
            continue
        first = payload.history[0]
        key = digest([event.id, connector])[:24].upper()
        external = f"RPL-{int(key[:12], 16)}" if connector == "jira" else key.lower()
        title = f"{payload.scope.process.replace('_', ' ').capitalize()}: {first.entity_id} at tick {first.tick}"
        fields: dict[str, Any] = {
            stable_field: external, "company_id": world.company.id, "case_id": payload.case_id,
            "process": payload.scope.process, "business_unit": payload.scope.business_unit,
            "business_unit_id": event.business_units[0],
            "activity_id": payload.scope.activity_id, "lob": payload.scope.lob,
            "subject_entity_id": first.entity_id, "opened_tick": first.tick,
            "world_event_id": event.id, "upstream_event_ids": list(payload.upstream_event_ids),
            "opened_at": event.occurred_at.isoformat(),
            "status": "received" if payload.scope.process == "supplier_replenishment" else "open",
            "history": [{"record_id": row.id, "tick": row.tick, "values": row.values(),
                         "relations": [link.model_dump(mode="json") for link in row.links]} for row in payload.history],
            "synthesis_provenance": {"recipe_digest": payload.recipe_digest, "program_digest": payload.program_digest,
                "source_record_ids": [row.id for row in payload.history], "trigger": RULE.model_dump(mode="json"),
                "scope": "operational_simulation_not_macro_reconciliation"},
        }
        if payload.match is not None:
            fields.update(payload.match.model_dump(mode="json"))
            fields["status"] = "match_exception" if payload.match.invoice_variance else "matched"
        if connector == "email":
            fields.update(thread_id=key.lower(), subject=title,
                          body=f"{title}. Status: {fields['status']}. Read the source observation history and upstream event references.")
        record = ConnectorRecord(id=f"CONN-{connector.upper()}-RETAIL-{key}", connector=connector,
            entity=entity, external_id=external, title=title, fields=fields, event_ids=[event.id])
        records.append(record)
        if connector == "email":
            thread = {key: value for key, value in fields.items() if key != "message_id"}
            thread.update(message_ids=[external], message_record_ids=[record.id])
            records.append(ConnectorRecord(id=record.id + "-THREAD", connector=connector,
                entity="thread", external_id=str(fields["thread_id"]), title=title, fields=thread, event_ids=[event.id]))
    return records


@dataclass(frozen=True)
class RetailReplenishment:
    config: dict[str, Any]
    occurred_at: str
    physics: Any = None

    def run(self, world: World) -> World:
        return build_retail_process(world, RetailProcess.model_validate(self.config),
                                    occurred_at=datetime.fromisoformat(self.occurred_at))


def _checks(world: World) -> tuple[list[Violation], int]:
    from .validate import Violation

    events = {event.id: event for event in world.events}
    violations: list[Violation] = []
    checks = 0
    materialized = [event for event in world.events if event.kind == EVENT_KIND]
    if not materialized:
        return violations, checks
    steps = [step for step in world.recipe.get("steps", ()) if step.get("scenario") == "RetailReplenishment"]
    try:
        if len(steps) != 1 or world.seed is None:
            raise ValueError("retail evidence requires one recorded process recipe and company seed")
        config = RetailProcess.model_validate(steps[0]["config"])
        units = {unit.name: unit for unit in world.business_units}
        if {scope.business_unit for scope in config.scopes} - units.keys():
            raise ValueError("retail process owner is absent from the generated company")
        simulator = Simulator(config.program, seed=world.seed, limits=Limits(max_rows=100_000))
        start = datetime.fromisoformat(steps[0]["occurred_at"])
        scoped = {scope.process: scope for scope in config.scopes}
        # Compare only the materialized evidence cohort, keeping memory bounded
        # by max_cases rather than retaining every row in a large simulation.
        histories = nsmallest(config.max_cases, _histories(simulator),
                              key=lambda history: (history[0].tick, history[0].entity_id))
        expected = {digest(["episode/v1", simulator.run_digest, RULE.model_dump(mode="json"), history[0].id]): history
                    for history in histories}
        if len(materialized) != len(expected) * len(PROCESSES):
            raise ValueError("retail process is missing or duplicating a required case stage")
    except (KeyError, ValueError) as error:
        return [Violation("retail_replenishment", "process_recipe", world.company.id, str(error))], 1
    seen: set[tuple[str, Process]] = set()
    for event in world.events:
        if event.kind != EVENT_KIND:
            continue
        checks += 1
        try:
            payload = case_payload(event)
            assert payload is not None
            physical = expected.get(payload.case_id)
            visible = physical[:1] if physical and payload.scope.process == "inventory_exception" else physical
            if (payload.history != visible or payload.program_digest != simulator.compiled.program_digest
                    or payload.recipe_digest != simulator.run_digest or payload.scope != scoped[payload.scope.process]):
                raise ValueError("process evidence differs from recorded physical program, selected case or owner scope")
            pair = (payload.case_id, payload.scope.process)
            if pair in seen:
                raise ValueError("retail process repeats one case stage")
            seen.add(pair)
            expected_time = start + timedelta(days=payload.history[-1].tick,
                                              hours=1 if payload.scope.process == "invoice_reconciliation" else 0)
            if event.occurred_at != expected_time:
                raise ValueError("retail stage time differs from its physical observation cutoff")
            if event.caused_by != list(payload.upstream_event_ids):
                raise ValueError("event causal references differ from process evidence")
            if event.business_units != [units[payload.scope.business_unit].id]:
                raise ValueError("event owner differs from the process's generated business unit")
            for reference in payload.upstream_event_ids:
                upstream = events.get(reference)
                previous = case_payload(upstream) if upstream is not None else None
                index = PROCESSES.index(payload.scope.process)
                if (previous is None or previous.case_id != payload.case_id or index == 0
                        or previous.scope.process != PROCESSES[index - 1]
                        or upstream is None or upstream.occurred_at > event.occurred_at):
                    raise ValueError("process predecessor must be the preceding stage of this same case")
        except (KeyError, ValueError, AssertionError) as error:
            violations.append(Violation("retail_replenishment", "process_evidence", event.id, str(error)))
    return violations, checks


from .recipe import register_step
from .validate import register_domain_checks

register_step("RetailReplenishment", ("config", "occurred_at"), RetailReplenishment)
register_domain_checks("retail_replenishment", _checks)

__all__ = ["RetailProcess", "RetailProcessScope", "RetailCaseEvent", "RetailMatch", "RetailReplenishment",
           "connected_program", "build_retail_process", "case_payload", "process_report", "project_records"]
