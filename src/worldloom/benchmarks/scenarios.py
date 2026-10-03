"""Bounded, replayable business cases for native benchmark evidence.

The operational simulator owns the transaction arithmetic. Canonical facts
record its case-local inputs and derivations, and ordinary artifact IR projects
them into the existing native engine. Distribution ranges and prose variants
are authored mechanisms, not fitted company behaviour or model-written prose.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any, Literal

from pydantic import (
    Field,
    SerializerFunctionWrapHandler,
    model_serializer,
    model_validator,
)

from ..corpus_scale import _world_digest
from ..documents import compile_intent, register_artifact_types
from ..formula_semantics import formula_value
from ..ids import Minter, content_key
from ..models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Cell,
    Column,
    EnterpriseEvent,
    FormulaKind,
    Lifecycle,
    Model,
    Quantity,
    Row,
    Table,
)
from ..narrative import references
from ..native_corpus import (
    NativeContent,
    NativeCorpusPlan,
    NativeCorpusResult,
    render_native_corpus,
)
from ..native_query_evidence import SourceEvidenceIndex
from ..native_query_planning import NativeFormat
from ..parameters import DEFAULT, Parameters
from ..recipe import register_step, with_step
from ..rng import Rng
from ..synthesis.engine import Simulator
from ..synthesis.models import Column as SimulationColumn
from ..synthesis.models import Expr, Limits, Program
from ..synthesis.models import Table as SimulationTable
from .tactics import (
    NativeRealismMeasurements,
    NativeRealismProfile,
    apply_population_tactics,
    apply_presentation_tactics,
    historical_views,
    measure_realism,
)

if TYPE_CHECKING:
    from ..world import World

NativeScenarioProcess = Literal["supplier_reconciliation", "customer_settlement", "inventory_replenishment"]
_PROCESSES: tuple[NativeScenarioProcess, ...] = (
    "supplier_reconciliation", "customer_settlement", "inventory_replenishment",
)
_VERSION = "worldloom.native-scenarios/v1"
_STEP = "NativeScenarioEpisodes"


class NativeScenarioDemand(Model):
    episodes: int = Field(default=18, ge=1, le=256, strict=True)
    processes: tuple[NativeScenarioProcess, ...] = _PROCESSES
    start_period: str = Field(default="2026-01", pattern=r"^\d{4}-\d{2}$")
    rows_per_episode: int = Field(default=3, ge=3, le=8, strict=True)
    batch_id: str = Field(default="native-cases", min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    realism: NativeRealismProfile | None = None

    @model_serializer(mode="wrap")
    def _without_absent_profile(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.realism is None:
            data.pop("realism", None)
        return data

    @model_validator(mode="after")
    def _bounded(self) -> NativeScenarioDemand:
        if not self.processes or len(set(self.processes)) != len(self.processes):
            raise ValueError("scenario processes must be distinct and nonempty")
        if self.episodes < len(self.processes):
            raise ValueError("episode demand must fund every requested process")
        year, month = (int(part) for part in self.start_period.split("-"))
        if not 1900 <= year <= 2090 or not 1 <= month <= 12:
            raise ValueError("start_period must name a month from 1900 through 2090")
        return self


class NativeScenarioEpisode(Model):
    process: NativeScenarioProcess
    case_id: str
    source_artifact_id: str
    fact_ids: tuple[str, ...]
    event_ids: tuple[str, ...]
    period: str
    template_variant: str
    numeric_facts: int
    formula_cells: int
    simulation_digest: str
    companion_artifact_ids: tuple[str, ...] = ()
    realism: NativeRealismMeasurements | None = None


@dataclass(frozen=True)
class NativeScenarioBuild:
    world: World
    demand: NativeScenarioDemand
    episodes: tuple[NativeScenarioEpisode, ...]
    source_digest: str

    @property
    def source_artifact_ids(self) -> tuple[str, ...]:
        return tuple(identifier for episode in self.episodes
                     for identifier in (episode.source_artifact_id, *episode.companion_artifact_ids))

    def verify_source_replay(self) -> None:
        """Re-run the registered source recipe and compare the complete world.

        This is stronger than checking new file names or trusting the case IDs.
        A caller's unrecorded source mutation is intentionally a refusal.
        """
        from ..recipe import rebuild

        if _world_digest(self.world) != self.source_digest:
            raise ValueError("native scenario source changed after construction")
        replay = rebuild(self.world.recipe, ledger=tuple(self.world.ledger),
                         actor_ledger=tuple(self.world._actor_ledger))
        if _world_digest(replay) != self.source_digest:
            raise ValueError("native scenario source does not replay from its recorded recipe")

    def render(self, *, formats: tuple[NativeFormat, ...] = ("docx", "pptx", "xlsx")) -> dict[str, NativeCorpusResult]:
        """Render each whole case, keeping copies in one canonical family."""
        if not formats or len(set(formats)) != len(formats) or set(formats) - {"docx", "pptx", "xlsx"}:
            raise ValueError("native scenarios require distinct supported formats")
        if _world_digest(self.world) != self.source_digest:
            raise ValueError("native scenario source changed after construction")
        index = SourceEvidenceIndex(self.world)
        rendered = {}
        seen: set[str] = set()
        for episode in self.episodes:
            for source_id in (episode.source_artifact_id, *episode.companion_artifact_ids):
                artifact = index.artifacts[source_id]
                main = source_id == episode.source_artifact_id
                minimum_facts = episode.numeric_facts if main else 1
                for format in sorted(formats):
                    plan = NativeCorpusPlan(artifact_id=artifact.id + "-" + format, format=format,
                        title=artifact.title, surface="business", contextual_headings=True,
                        contents=tuple(NativeContent(source_artifact_id=artifact.id, section_index=i)
                                       for i in range(len(artifact.sections))),
                        minimum_units=len(artifact.sections), minimum_distinct_facts=minimum_facts)
                    result = render_native_corpus(self.world, plan)
                    actual = index.fact_closure(tuple(sorted({fact for entry in result.manifest.evidence
                                                            for fact in entry.fact_ids})))
                    if (main and actual != episode.fact_ids) or not set(actual) <= set(episode.fact_ids):
                        raise ValueError("native scenario rendered facts differ from the complete case closure")
                    rendered[plan.artifact_id] = result
            if seen.intersection(episode.fact_ids):
                raise ValueError("native scenarios share canonical ancestry across cases")
            seen.update(episode.fact_ids)
        return dict(sorted(rendered.items()))


def _literal(value: int) -> Expr:
    return Expr(op="literal", value=value)


def _ref(name: str) -> Expr:
    return Expr(op="ref", name=name)


def _draw(name: str, low: int, high: int) -> SimulationColumn:
    return SimulationColumn(name=name, expression=Expr(op="uniform", stream=name,
        args=(_literal(low), _literal(high))))


def _calculated(name: str, operation: Literal["add", "sub"], *operands: str) -> SimulationColumn:
    return SimulationColumn(name=name, expression=Expr(op=operation, args=tuple(_ref(key) for key in operands)))


def _simulation(process: NativeScenarioProcess, case_id: str, rows: int, seed: int) -> Simulator:
    columns: tuple[SimulationColumn, ...]
    if process == "supplier_reconciliation":
        columns = (_draw("budget", 240000, 780000), _draw("price_change", 1200, 24000),
            _draw("unreceipted", 3000, 48000), _calculated("actual", "add", "budget", "price_change"),
            _calculated("eligible", "sub", "actual", "unreceipted"))
    elif process == "customer_settlement":
        columns = (_draw("budget", 90000, 310000), _draw("surge", 5000, 42000),
            _draw("rejected", 2000, 18000), _draw("pending", 1000, 13000),
            _calculated("actual", "add", "budget", "surge"),
            _calculated("approved", "sub", "actual", "rejected"),
            _calculated("paid", "sub", "approved", "pending"))
    else:
        columns = (_draw("budget", 400, 950), _draw("surge", 30, 180),
            _draw("stock", 80, 150), _draw("inbound", 160, 230),
            _calculated("actual", "add", "budget", "surge"),
            _calculated("supply", "add", "stock", "inbound"),
            _calculated("shortage", "sub", "actual", "supply"))
    return Simulator(Program(namespace="native_case_" + case_id,
        tables=(SimulationTable(name="transactions", count=rows, columns=columns),)), seed=seed,
        limits=Limits(max_rows=max(8, rows), max_work=100000))


_DESCRIPTORS: dict[str, tuple[str, tuple[str, ...], str, tuple[str, ...]]] = {
    "supplier_reconciliation": ("Supplier invoice reconciliation", ("Cartons", "Labels", "Cold packs", "Pallets", "Film", "Trays", "Inserts", "Crates"),
        "procure_to_pay", ("p2p.07", "p2p.09", "p2p.10", "p2p.11")),
    "customer_settlement": ("Customer refund settlement", ("Home delivery", "Store pickup", "Marketplace", "Express delivery", "Subscriptions", "Wholesale", "Click and collect", "Service desk"),
        "order_to_cash", ("o2c.09", "o2c.11", "o2c.12")),
    "inventory_replenishment": ("Inventory replenishment exception", ("Chilled meals", "Dairy", "Produce", "Frozen", "Bakery", "Pantry", "Beverages", "Household"),
        "forecast_to_replenish", ("f2r.01", "f2r.02", "f2r.04", "f2r.05")),
}


def _period(start: str, offset: int) -> str:
    year, month = (int(part) for part in start.split("-"))
    year, month = divmod(year * 12 + month - 1 + offset, 12)
    return f"{year:04}-{month + 1:02}"


def _reference(fact: CanonicalFact) -> str:
    return "{{fact:" + fact.id + "}}"


def _episode(world: World, demand: NativeScenarioDemand, process: NativeScenarioProcess,
             ordinal: int) -> tuple[NativeScenarioEpisode, tuple[CanonicalFact, ...], tuple[EnterpriseEvent, ...], ArtifactIR]:
    assert world.seed is not None
    case_id = content_key(_VERSION, world.company.id, demand.batch_id, process, ordinal)
    prefix = case_id.upper()
    source_id = "ART-NATIVE-" + prefix
    period = _period(demand.start_period, ordinal // len(demand.processes))
    rng = Rng(world.seed).derive(_VERSION + "/" + case_id)
    opened = datetime.fromisoformat(period + "-01T09:00:00+00:00") + timedelta(days=rng.integer(1, 9))
    reviewed = opened + timedelta(days=rng.integer(1, 3))
    closed = reviewed + timedelta(days=rng.integer(1, 2))
    title, base_labels, stream, activities = _DESCRIPTORS[process]
    rows = demand.realism.line_count if demand.realism and demand.realism.line_count else demand.rows_per_episode
    cohorts = ("Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel")
    labels = tuple(base_labels[position % len(base_labels)] +
                   (" / allocation cohort " + cohorts[position // len(base_labels)] if position >= len(base_labels) else "")
                   for position in range(rows))
    preferred_functions = (("Procurement", "Finance") if process == "supplier_reconciliation"
        else ("Operations", "ServiceOperations") if process == "customer_settlement"
        else ("Merchandising", "Procurement", "Operations"))
    candidates = sorted((person for person in world.people
        if (person.joined is None or person.joined <= opened) and (person.left is None or person.left > closed)),
        key=lambda person: (person.function not in preferred_functions, person.id))
    if not candidates:
        raise ValueError("native scenario has no accountable employee active throughout its episode")
    actor = candidates[0]
    event_ids = tuple("EV-NATIVE-" + prefix + "-" + key for key in ("OPEN", "REVIEW", "CLOSE"))
    subject = event_ids[0]
    case_title = f"{title} — {period} — {demand.batch_id} case {ordinal + 1}"
    events = tuple(EnterpriseEvent(id=identifier, kind="native." + process + "." + phase,
        occurred_at=at, summary=case_title if index == 0 else case_title + ": " + phase,
        actors=[actor.id] if actor else [],
        caused_by=[] if index == 0 else [event_ids[index - 1]])
        for index, (identifier, phase, at) in enumerate(zip(event_ids,
            ("opened", "reviewed", "closed"), (opened, reviewed, closed), strict=True)))
    facts: list[CanonicalFact] = []

    def fact(key: str, value: int | float | str, *, unit: str | None = None,
             parents: tuple[CanonicalFact, ...] = (), at: datetime = closed,
             authority: Authority = Authority.SYSTEM_OF_RECORD, previous: CanonicalFact | None = None) -> CanonicalFact:
        record = CanonicalFact(id="FACT-NATIVE-" + prefix + "-" + key.upper().replace(".", "-").replace("_", "-"),
            kind="native." + process + "." + ("status" if key in ("status", "review_status", "final_status") else key),
            subject=subject, period=period,
            value=Quantity(amount=value, unit=unit) if not isinstance(value, str) and unit else None,
            text_value=value if isinstance(value, str) else None, valid_from=at, authority=authority,
            event_id=event_ids[0] if at == opened else event_ids[1] if at == reviewed else event_ids[2],
            source="authored_operational_simulation", tx_from=at,
            derived_from=tuple(parent.id for parent in parents), supersedes=previous.id if previous else None)
        facts.append(record)
        return record

    dates = {key: fact("date." + key, at.date().isoformat(), at=at)
             for key, at in (("opened", opened), ("reviewed", reviewed), ("closed", closed))}
    initial = fact("status", "Pending evidence review", at=opened, authority=Authority.INITIAL_HYPOTHESIS)
    facts[facts.index(initial)] = initial.model_copy(update={"valid_to": reviewed})
    reviewed_status = fact("review_status", "Evidence reconciled; approval pending", at=reviewed,
        authority=Authority.WORKING_DOCUMENT, previous=initial)
    facts[facts.index(reviewed_status)] = reviewed_status.model_copy(update={"valid_to": closed})
    final_status = fact("final_status", "Approved for controlled execution", authority=Authority.APPROVED_REPORT,
        previous=reviewed_status)
    owner = fact("accountable_owner", actor.name if actor else world.company.name, authority=Authority.APPROVED_REPORT)
    simulation = _simulation(process, case_id, rows, world.seed)
    if demand.realism is not None:
        simulation = apply_population_tactics(simulation, demand.realism, process=process, case_id=case_id)
    values = [{cell.name: int(cell.value) for cell in row.cells} for row in simulation.rows()]
    unit = "units" if process == "inventory_replenishment" else world.company.currency
    divisor = 1 if unit == "units" else 100
    base_keys = {
        "supplier_reconciliation": ("budget", "price_change", "unreceipted", "actual", "eligible"),
        "customer_settlement": ("budget", "surge", "rejected", "pending", "actual", "approved", "paid"),
        "inventory_replenishment": ("budget", "surge", "stock", "inbound", "actual", "supply", "shortage"),
    }[process]
    dependencies: dict[str, tuple[str, ...]] = {
        "actual": ("budget", "price_change" if process == "supplier_reconciliation" else "surge"),
        "eligible": ("actual", "unreceipted"), "approved": ("actual", "rejected"),
        "paid": ("approved", "pending"), "supply": ("stock", "inbound"), "shortage": ("actual", "supply"),
    }
    records: list[dict[str, CanonicalFact]] = []
    for position, values_row in enumerate(values):
        row_facts: dict[str, CanonicalFact] = {}
        for key in base_keys:
            # The suffix pair is a declared actual/budget comparison. The line
            # vocabulary distinguishes concurrent measures of the same company.
            kind = f"line{position}.volume.{key}" if key in ("actual", "budget") else f"line{position}.{key}"
            row_facts[key] = fact(kind, values_row[key] / divisor, unit=unit,
                parents=tuple(row_facts[parent] for parent in dependencies.get(key, ())),
                at=opened if key == "budget" else reviewed if key in ("actual", "price_change", "surge", "unreceipted", "rejected", "stock", "inbound") else closed,
                authority=Authority.APPROVED_REPORT if key == "budget" else Authority.SYSTEM_OF_RECORD)
        records.append(row_facts)

    def literal(record: CanonicalFact) -> Cell:
        assert record.value is not None
        return Cell(value=record.value.amount, fact_id=record.id)

    def computed(kind: FormulaKind, operands: list[str], numbers: list[float], *, record: CanonicalFact | None = None) -> Cell:
        return Cell(value=formula_value(kind, numbers, decimal_places=2), formula=kind,
            operands=operands, formula_decimal_places=2, fact_id=record.id if record else None)

    def number(record: CanonicalFact) -> float:
        assert record.value is not None
        return record.value.amount

    money_format = '#,##0.00' if divisor == 100 else '#,##0'
    compare_rows = []
    for position, row in enumerate(records):
        actual, budget = number(row["actual"]), number(row["budget"])
        compare_rows.append(Row(key=f"line{position}", label=labels[position], cells={
            "actual": literal(row["actual"]), "budget": literal(row["budget"]),
            "variance": computed(FormulaKind.DIFFERENCE, ["actual", "budget"], [actual, budget]),
            "variance_pct": computed(FormulaKind.RATIO_PCT, ["variance", "budget"], [actual - budget, budget]),
        }))
    totals = {key: fact("total." + key, sum(row[key] for row in values) / divisor, unit=unit,
        parents=tuple(row[key] for row in records), at=max(row[key].valid_from for row in records),
        authority=Authority.APPROVED_REPORT if key == "budget" else Authority.SYSTEM_OF_RECORD) for key in base_keys}
    total_actual, total_budget = number(totals["actual"]), number(totals["budget"])
    compare_rows.append(Row(key="total", label="Case total", emphasis=True, cells={
        "actual": computed(FormulaKind.SUM, [row.key for row in compare_rows],
            [number(row["actual"]) for row in records], record=totals["actual"]),
        "budget": computed(FormulaKind.SUM, [row.key for row in compare_rows],
            [number(row["budget"]) for row in records], record=totals["budget"]),
        "variance": computed(FormulaKind.DIFFERENCE, ["actual", "budget"], [total_actual, total_budget]),
        "variance_pct": computed(FormulaKind.RATIO_PCT, ["variance", "budget"], [total_actual - total_budget, total_budget]),
    }))
    measure = "Invoiced amount" if process == "supplier_reconciliation" else "Requested refunds" if process == "customer_settlement" else "Demand"
    comparison = Table(key="comparison", title=f"{measure} against plan [{unit}]", columns=[
        Column(key="actual", label=measure + " actual", number_format=money_format),
        Column(key="budget", label=measure + " budget", number_format=money_format),
        Column(key="variance", label="Variance", number_format=money_format),
        Column(key="variance_pct", label="Variance percent", number_format='0.00%')], rows=compare_rows)
    stages = {
        "supplier_reconciliation": (("actual", "Invoiced"), ("unreceipted", "Missing receipt holdback"), ("eligible", "Eligible payment")),
        "customer_settlement": (("actual", "Requested"), ("rejected", "Declined after review"), ("approved", "Approved"), ("paid", "Paid"), ("pending", "Pending settlement")),
        "inventory_replenishment": (("actual", "Demand"), ("stock", "Available stock"), ("inbound", "Confirmed inbound"), ("supply", "Available supply"), ("shortage", "Expedite requirement")),
    }[process]
    flow_rows = []
    for position, row in enumerate(records):
        cells = {}
        for key, _label in stages:
            if key == "actual":
                cells[key] = computed(FormulaKind.REFERENCE, [f"comparison:line{position}:actual"], [number(row[key])])
            elif key in dependencies:
                parents = dependencies[key]
                operation = FormulaKind.SUM if key == "supply" else FormulaKind.DIFFERENCE
                operands = ([f"resolution:line{position}:{parent}" for parent in parents]
                            if operation is FormulaKind.SUM else list(parents))
                cells[key] = computed(operation, operands, [number(row[parent]) for parent in parents], record=row[key])
            else:
                cells[key] = literal(row[key])
        flow_rows.append(Row(key=f"line{position}", label=labels[position], cells=cells))
    flow_rows.append(Row(key="total", label="Case total", emphasis=True, cells={key:
        computed(FormulaKind.SUM, [row.key for row in flow_rows], [number(row[key]) for row in records], record=totals[key])
        for key, _ in stages}))
    resolution = Table(key="resolution", title=f"{title} bridge [{unit}]",
        columns=[Column(key=key, label=label, number_format=money_format) for key, label in stages], rows=flow_rows)
    disposition_key = "eligible" if process == "supplier_reconciliation" else "pending" if process == "customer_settlement" else "shortage"
    decision_templates = {
        "supplier_reconciliation": (
            "Treasury can release the eligible payment of {result}. The missing receipt holdback is {hold}; it remains blocked until receiving evidence is attached.",
            "The payment run separates supported invoices from receipt exceptions. Release {result}, retaining {hold} for the receiving team to resolve.",
            "Approve {result} for settlement. The reconciliation leaves {hold} on hold because the corresponding receipt evidence has not been confirmed.",
        ),
        "customer_settlement": (
            "Customer operations approved {approved} after review and has paid {paid}. The pending settlement balance of {result} remains an execution obligation rather than a new refund approval.",
            "The reviewed refund population is split between completed payments of {paid} and pending settlements of {result}; together they reconcile to the approved amount of {approved}.",
            "Complete the remaining settlements of {result}. Approved refunds total {approved}, of which {paid} has already reached customers.",
        ),
        "inventory_replenishment": (
            "Confirmed stock and inbound supply total {supply} against demand of {actual}. Expedite {result}; the gap is a physical availability requirement, not a monetary variance.",
            "The demand revision leaves an expedite requirement of {result}. Count only confirmed supply of {supply} when comparing with demand of {actual}.",
            "Authorise replenishment of the uncovered {result}. Existing stock and confirmed inbound contribute {supply}; the demand requirement is {actual}.",
        ),
    }
    variant_index = ordinal // len(demand.processes) % 3
    variant = ("decision_first", "evidence_first", "chronology_first")[variant_index]
    substitutions = {key: _reference(record) for key, record in totals.items()}
    substitutions.update(result=_reference(totals[disposition_key]), hold=_reference(totals.get("unreceipted", totals["actual"])))
    decision = ArtifactSection(heading="Execution decision", semantic_role="decision",
        body="The reviewed " + measure.lower() + " actual is " + _reference(totals["actual"]) + ". " +
            decision_templates[process][variant_index].format(**substitutions) +
            " Accountable owner: " + _reference(owner) + ". Decision status: " + _reference(final_status) + ".",
        purpose="State the authorised action and the unresolved obligation using the reconciled case totals.")
    baseline = ArtifactSection(heading="Approved planning baseline", semantic_role="evidence",
        body="The approved " + measure.lower() + " budget for this case is " + _reference(totals["budget"]) +
            ". This is the planning baseline retained for comparison with the reviewed outcome.",
        purpose="Preserve the prior approved baseline independently from the execution decision.")
    chronology = ArtifactSection(heading="Evidence and approval chronology", semantic_role="chronology",
        body="The case opened on " + _reference(dates["opened"]) + " with status " + _reference(initial) +
            ". Review on " + _reference(dates["reviewed"]) + " advanced the record to " + _reference(reviewed_status) +
            ". On " + _reference(dates["closed"]) + ", the approval superseded that working assessment: " + _reference(final_status) + ".",
        purpose="Distinguish the initial position, evidence review and approved instruction at their recorded dates.")
    tables = [ArtifactSection(heading="Demand and plan comparison", semantic_role="evidence", table=comparison),
        ArtifactSection(heading="Reconciled execution bridge", semantic_role="evidence", table=resolution)]
    # The driver ledger carries exogenous causes not repeated in the main
    # bridge, so simulation inputs and every derived ancestor stay inspectable.
    driver_keys = tuple(key for key in base_keys if key not in {name for name, _ in stages} and key != "budget")
    if driver_keys:
        driver_rows = [Row(key=f"line{position}", label=labels[position],
            cells={key: literal(row[key]) for key in driver_keys}) for position, row in enumerate(records)]
        tables.append(ArtifactSection(heading="Review drivers", semantic_role="evidence",
            table=Table(key="drivers", title=f"Case adjustment drivers [{unit}]",
                columns=[Column(key=key, label=key.replace("_", " ").title(), number_format=money_format) for key in driver_keys],
                rows=driver_rows)))
    sections = ([decision, baseline, *tables, chronology] if variant_index == 0 else
                [baseline, *tables, chronology, decision] if variant_index == 1 else [chronology, baseline, *tables, decision])
    # Totals not projected as cells are still canonical derivations and occur in
    # a grounded reconciliation note, never a private numerical appendix.
    served = {identifier for section in sections for identifier in references.referenced(section.body or "")}
    served.update(cell.fact_id for section in sections if section.table for row in section.table.rows for cell in row.cells.values() if cell.fact_id)
    remaining = [record for record in totals.values() if record.id not in served]
    if remaining:
        sections.append(ArtifactSection(heading="Adjustment totals", semantic_role="evidence",
            body="; ".join(record.kind.rsplit(".", 1)[-1].replace("_", " ").capitalize() + ": " + _reference(record) for record in remaining) + "."))
    sections = [section.model_copy(update={"fact_ids": list(dict.fromkeys([
        *references.referenced(section.body or ""),
        *(cell.fact_id for row in section.table.rows for cell in row.cells.values() if cell.fact_id)
        ] if section.table else references.referenced(section.body or "")))}) for section in sections]
    artifact = ArtifactIR(id=source_id, intent_id=source_id,
        title=case_title, sections=sections,
        metadata={"native_scenario_version": _VERSION, "native_scenario_process": process,
            "native_scenario_case_id": case_id, "native_scenario_template": variant,
            "native_scenario_simulation_digest": simulation.run_digest,
            "process_catalogue_stream": stream, "process_catalogue_activities": ",".join(activities),
            "created_at": closed.isoformat(), "authority": Authority.APPROVED_REPORT.value,
            "author": actor.name if actor else world.company.name, "author_id": actor.id if actor else ""})
    if demand.realism is not None:
        artifact = apply_presentation_tactics(artifact, demand.realism, seed=world.seed, case_id=case_id)
    companions = historical_views(artifact, facts, demand.realism) if demand.realism is not None else ()
    description = NativeScenarioEpisode(process=process, case_id=case_id, source_artifact_id=source_id,
        fact_ids=tuple(sorted(record.id for record in facts)), event_ids=event_ids, period=period,
        template_variant=variant, numeric_facts=sum(record.value is not None for record in facts),
        formula_cells=sum(cell.formula is not None for section in artifact.sections if section.table
                          for row in section.table.rows for cell in row.cells.values()),
        simulation_digest=simulation.run_digest, companion_artifact_ids=tuple(view.artifact.id for view in companions),
        realism=measure_realism(artifact, simulation, process=process, historical_artifacts=len(companions))
            if demand.realism is not None else None)
    return description, tuple(facts), events, artifact


def build_native_scenarios(world: World, demand: NativeScenarioDemand) -> NativeScenarioBuild:
    """Create fresh episodes from explicit bounded demand, never clone files.

    A batch identifier is a case namespace, not evidence of independence. Actual
    canonical ancestor closures are checked after generation and rendering.
    """
    if world.seed is None or not world.recipe.get("archetype"):
        raise ValueError("native scenarios require a seeded world with a replayable recipe")
    demand = NativeScenarioDemand.model_validate(demand.model_dump(mode="json"))
    if not world.people:
        raise ValueError("native scenarios require an accountable employee in the source world")
    if world.artifact_intents and not world.artifact_irs:
        world = world.compile()
    descriptions: list[NativeScenarioEpisode] = []
    facts: list[CanonicalFact] = []
    events: list[EnterpriseEvent] = []
    artifacts: list[ArtifactIR] = []
    intents: list[ArtifactIntent] = []
    existing = {artifact.id for artifact in world.artifact_irs}
    for ordinal in range(demand.episodes):
        description, case_facts, case_events, artifact = _episode(world, demand,
            demand.processes[ordinal % len(demand.processes)], ordinal)
        if artifact.id in existing:
            raise ValueError("native scenario batch already exists; use a fresh batch_id for new cases")
        descriptions.append(description)
        facts.extend(case_facts)
        events.extend(case_events)
        previous = None
        if demand.realism is not None:
            for view in historical_views(artifact, case_facts, demand.realism):
                artifacts.append(view.artifact)
                intents.append(ArtifactIntent(id=view.artifact.id,
                    artifact_type="native_case_working_assessment",
                    domain="governance", audience="all_staff", author_id=artifact.metadata["author_id"],
                    triggered_by=[view.event_id], required_fact_ids=list(view.fact_ids), revises=previous,
                    rationale="Time-bounded working assessment used by the subsequent approved execution report."))
                previous = view.artifact.id
        artifacts.append(artifact)
        intents.append(ArtifactIntent(id=artifact.id, artifact_type="native_case_review", domain="governance",
            audience="all_staff", author_id=artifact.metadata["author_id"],
            triggered_by=list(description.event_ids), required_fact_ids=list(description.fact_ids),
            derived_from=[previous] if previous else [],
            rationale="Case-level evidence review and controlled execution decision."))
    result = replace(world, _facts=(*world._facts, *facts), _events=(*world._events, *events),
        _artifact_intents=(*world._artifact_intents, *intents),
        _artifact_irs=(*world._artifact_irs, *artifacts),
        _recipe=with_step(world.recipe, _STEP, demand=demand.model_dump(mode="json")))
    compiled = tuple(compile_intent(result, intent, Minter()) for intent in intents)
    result = replace(result, _artifact_irs=(*world._artifact_irs, *compiled),
        _artifacts=(*world._artifacts, *result._manifest_for(compiled)))
    index = SourceEvidenceIndex(result)
    seen: set[str] = set()
    for description in descriptions:
        closure = index.fact_closure(description.fact_ids)
        if closure != description.fact_ids or seen.intersection(closure):
            raise ValueError("native scenario case has foreign or overlapping canonical ancestors")
        seen.update(closure)
    return NativeScenarioBuild(result, demand, tuple(descriptions), _world_digest(result))


@dataclass(frozen=True)
class _NativeScenarioEpisodes:
    demand: dict[str, Any]
    # The source company's recorded parameters still rebuild its own financial
    # and organisational history. These additional cases have an explicitly
    # separate, authored simulation program; they do not claim calibration from
    # retail margin or incident-duration overrides on that company.
    physics: Parameters = DEFAULT

    def run(self, world: World) -> World:
        return build_native_scenarios(world, NativeScenarioDemand.model_validate(self.demand)).world


register_step(_STEP, ("demand",), _NativeScenarioEpisodes)


def _compile_native_case(world: World, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:
    # The registered scenario already compiled its canonical simulation. A
    # later world.compile() preserves that projection and still runs the common
    # artifact cohesion contract; it cannot silently fall back to generic prose.
    source = next((artifact for artifact in world.artifact_irs if artifact.intent_id == intent.id), None)
    if source is None:
        raise ValueError("native case source is missing; replay the recorded scenario recipe")
    return source


_STANDING = {"native_case_review": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    "native_case_working_assessment": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT)}
register_artifact_types(standing=_STANDING,
    lags={kind: timedelta() for kind in _STANDING}, compilers={kind: _compile_native_case for kind in _STANDING})


__all__ = ["NativeScenarioProcess", "NativeScenarioDemand", "NativeScenarioEpisode", "NativeScenarioBuild", "build_native_scenarios"]
