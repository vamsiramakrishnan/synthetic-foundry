"""Reviewed sizing proposals over existing company and simulation mechanisms.

Compilation counts the rows a program would emit; it never executes trajectories,
builds a World, or equates requested queries with independent evidence.
"""

from __future__ import annotations

from datetime import date
from typing import Annotated

from pydantic import Field, StrictBool, model_validator

from ..models import Model
from ..retail_replenishment import connected_program
from ..sdk import _step
from ..synthesis import (
    Limits,
    Program,
    banking,
    compile_program,
    retail,
    with_parameters,
)
from .models import ProjectSpec

Dimension = Annotated[int, Field(ge=1, le=100_000, strict=True)]
QueryCount = Annotated[int, Field(ge=1, le=100_000, strict=True)]
UseCaseId = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]


class DataCreationRequest(Model):
    start_period: str | None = Field(default=None, pattern=r"^\d{4}-\d{2}$")
    periods: int | None = Field(default=None, ge=1, le=120, strict=True)
    acknowledge_invalidation: StrictBool = False
    simulation_target: str | None = Field(default=None, min_length=1, max_length=64)
    stores: Dimension | None = None
    products: Dimension | None = None
    borrowers: Dimension | None = None
    ticks: int | None = Field(default=None, ge=1, le=10_000, strict=True)
    query_counts: dict[UseCaseId, QueryCount] = Field(default_factory=dict)

    @model_validator(mode="after")
    def contract(self) -> DataCreationRequest:
        if (self.start_period is None) != (self.periods is None):
            raise ValueError("start_period and periods must be supplied together")
        if self.start_period is not None:
            date.fromisoformat(self.start_period + "-01")
            assert self.periods is not None
            date.fromisoformat(_step(self.start_period, self.periods - 1, 1) + "-01")
        dimensions = any(value is not None for value in (self.stores, self.products, self.borrowers, self.ticks))
        if dimensions != (self.simulation_target is not None):
            raise ValueError("simulation_target and at least one sizing dimension must be supplied together")
        return self


class HistorySummary(Model):
    before: tuple[str, ...]
    after: tuple[str, ...]
    changed: bool


class InvalidatedContracts(Model):
    narration_job: int = 0
    native_corpus: int = 0
    native_tasks: int = 0
    native_calibration: int = 0


class SimulationSummary(Model):
    target: str
    mechanism: str
    dimensions: dict[str, int]
    supported: bool
    reason: str | None = None
    table_rows: dict[str, int]
    total_rows: int
    work: int | None = None
    limits: Limits


class DataCreationSummary(Model):
    history: HistorySummary
    simulation: SimulationSummary | None
    requested_queries: dict[str, int]
    requested_query_total: int
    invalidated: InvalidatedContracts
    limitations: tuple[str, ...]


class DataCreationProposal(Model):
    spec: ProjectSpec
    summary: DataCreationSummary


def _limits(target: str) -> Limits:
    # This is the connected-process execution limit, not a larger UI allowance.
    return Limits(max_rows=100_000) if target == "retail_process" else Limits()


def _canonical(program: Program) -> tuple[Program, dict[str, int]]:
    tables = {table.name: table for table in program.tables}
    if program.namespace in {"retail_operations", "retail_replenishment"} and {"store", "product"} <= tables.keys():
        dimensions = {"stores": tables["store"].count, "products": tables["product"].count, "ticks": program.ticks}
        builder = connected_program if program.namespace == "retail_replenishment" else retail
        canonical = builder(**dimensions)
    elif program.namespace == "loan_servicing" and "borrower" in tables:
        dimensions = {"borrowers": tables["borrower"].count, "ticks": program.ticks}
        canonical = banking(**dimensions)
    else:
        raise ValueError("custom simulation is not supported by the sizing editor; preserve and edit its Program explicitly")
    # Values are mutable inputs; expressions, bounds, mutability, constraints,
    # ordering and relation strides remain the exact authored mechanism.
    mutable = {parameter.name for parameter in canonical.parameters if parameter.mutable}
    values = {parameter.name: parameter.value for parameter in program.parameters if parameter.name in mutable}
    canonical = with_parameters(canonical, values)
    if canonical != program:
        raise ValueError("custom simulation differs from the canonical mechanism; resizing would overwrite authored logic or parameters")
    return canonical, dimensions


def _summary(target: str, program: Program) -> SimulationSummary:
    table_rows = {table.name: table.count * (program.ticks if table.temporal else 1)
                  for table in sorted(program.tables, key=lambda table: table.name)}
    dimensions: dict[str, int] = {}
    work = None
    reason = None
    try:
        _, dimensions = _canonical(program)
        work = compile_program(program, limits=_limits(target)).work
    except ValueError as exc:
        reason = str(exc)
    return SimulationSummary(target=target, mechanism=program.namespace, dimensions=dimensions,
        supported=reason is None, reason=reason, table_rows=table_rows,
        total_rows=sum(table_rows.values()), work=work, limits=_limits(target))


def inspect_simulations(spec: ProjectSpec) -> list[SimulationSummary]:
    """Show current editable targets and explain why custom programs are protected."""
    targets = [(case.id, case.simulation) for case in spec.use_cases if case.simulation is not None]
    if spec.retail_process is not None:
        targets.append(("retail_process", spec.retail_process.program))
    collision = any(case.id == "retail_process" for case in spec.use_cases)
    summaries = []
    for target, program in sorted(targets, key=lambda item: (item[0], item[1].namespace)):
        summary = _summary(target, program)
        if collision and target == "retail_process":
            summary = summary.model_copy(update={"supported": False, "reason":
                "use case ID retail_process collides with the reserved connected-process target; rename the use case before resizing"})
        summaries.append(summary)
    return summaries


def _resize(program: Program, request: DataCreationRequest) -> Program:
    _, dimensions = _canonical(program)
    requested = {key: value for key in ("stores", "products", "borrowers", "ticks")
                 if (value := getattr(request, key)) is not None}
    if requested.keys() - dimensions.keys():
        raise ValueError(f"unsupported dimensions for {program.namespace}: {sorted(requested.keys() - dimensions.keys())}")
    dimensions.update(requested)
    if program.namespace == "retail_replenishment":
        resized = connected_program(**dimensions)
    elif program.namespace == "retail_operations":
        resized = retail(**dimensions)
    else:
        resized = banking(**dimensions)
    resized = with_parameters(resized, {parameter.name: parameter.value for parameter in program.parameters if parameter.mutable})
    assert request.simulation_target is not None
    compile_program(resized, limits=_limits(request.simulation_target))
    return resized


def propose(spec: ProjectSpec, request: DataCreationRequest) -> DataCreationProposal:
    """Return an immutable proposal; only the caller's revision review may apply it."""
    # Revalidate at this boundary: model_copy intentionally skips validators.
    spec = ProjectSpec.model_validate(spec.model_dump(mode="json"))
    request = DataCreationRequest.model_validate(request.model_dump(mode="json"))
    case_ids = {case.id for case in spec.use_cases}
    unknown = request.query_counts.keys() - case_ids
    if unknown:
        raise ValueError(f"unknown use cases in query_counts: {sorted(unknown)}")
    connector_case_ids = {case.id for case in spec.use_cases if case.scenario is not None}
    unsupported = request.query_counts.keys() - connector_case_ids
    if unsupported:
        raise ValueError(f"query_counts requires executable connector scenarios; native-only or draft use cases {sorted(unsupported)} do not consume connector query demand; size native tasks with NativeSuiteRequest")
    episodes = spec.episodes
    if request.start_period is not None:
        assert request.periods is not None
        episodes = tuple(_step(request.start_period, index, 1) for index in range(request.periods))
    changed = episodes != spec.episodes
    invalidated = InvalidatedContracts()
    document = spec.model_dump(mode="json")
    if changed:
        if not request.acknowledge_invalidation:
            raise ValueError("history changes require acknowledge_invalidation: accepted narration and native contracts must be regenerated")
        invalidated = InvalidatedContracts(narration_job=int(spec.narration_job is not None),
            native_corpus=len(spec.native_corpus), native_tasks=len(spec.native_tasks),
            native_calibration=int(spec.native_calibration is not None))
        document.update(episodes=list(episodes), narration_job=None, native_corpus=[],
                        native_tasks=[], native_calibration=None)
    simulation = None
    if request.simulation_target is not None:
        target = request.simulation_target
        if target == "retail_process":
            if target in case_ids:
                raise ValueError("simulation_target retail_process is ambiguous: the use case ID collides with the reserved connected-process target; rename the use case before resizing")
            if spec.retail_process is None:
                raise ValueError("project has no connected retail_process to resize")
            resized = _resize(spec.retail_process.program, request)
            document["retail_process"]["program"] = resized.model_dump(mode="json")
        else:
            case = next((case for case in spec.use_cases if case.id == target), None)
            if case is None or case.simulation is None:
                raise ValueError("simulation_target must name a use case with an existing simulation")
            resized = _resize(case.simulation, request)
            for case_document in document["use_cases"]:
                if case_document["id"] == target:
                    case_document["simulation"] = resized.model_dump(mode="json")
        simulation = _summary(target, resized)
    for case_document in document["use_cases"]:
        if case_document["id"] in request.query_counts:
            case_document["count"] = request.query_counts[case_document["id"]]
    proposed = ProjectSpec.model_validate(document)
    queries = {case.id: case.count for case in sorted(proposed.use_cases, key=lambda case: case.id)
               if case.scenario is not None}
    limitations: tuple[str, ...] = (
        "This proposal has not generated company data, corpus files, or evaluations.",
        "Table rows are planned from the actual Program; query counts are requests, not measured qualified queries or independent evidence components.",
        "Requested query totals cover executable connector scenarios only; native task counts are determined by the native suite contract, not UseCase.count.",
        "Simulation ticks do not extend the company's episode history or reconcile operational amounts to its macro financial close.",
        "Only existing canonical retail, connected retail, and banking mechanisms can be resized; custom programs are preserved and require explicit Program editing.",
        "History sizing replaces the declared monthly episode list; changed history requires new accepted narration and native corpus/task contracts.",
    )
    if proposed.retail_process is not None:
        limitations += (f"Connected retail keeps its existing max_cases={proposed.retail_process.max_cases}; more planned rows do not guarantee more emitted business cases.",)
    return DataCreationProposal(spec=proposed, summary=DataCreationSummary(
        history=HistorySummary(before=spec.episodes, after=episodes, changed=changed),
        simulation=simulation, requested_queries=queries, requested_query_total=sum(queries.values()),
        invalidated=invalidated, limitations=limitations))


__all__ = ["DataCreationRequest", "DataCreationProposal", "DataCreationSummary", "SimulationSummary",
           "inspect_simulations", "propose"]
