"""Executable realism controls over canonical native scenario evidence.

Population interventions reuse the relational simulator and the detail layer's
largest-remainder allocation. Presentation interventions reuse artifact IR.
Neither path creates a second source of truth or counts padding as evidence.
The distributions are authored experiment settings, not fitted company data.
"""
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal

from pydantic import Field, model_validator

from ..detail import _lognormal_weights, _zipf_weights, allocate_scaled
from ..ids import content_key
from ..models import ArtifactIR, ArtifactSection, Authority, CanonicalFact, Model, Row
from ..narrative import references
from ..rng import Rng
from ..synthesis.engine import Simulator
from ..synthesis.models import Intervention, Limits

_VERSION = "worldloom.native-realism/v1"


class NativeRealismProfile(Model):
    """Closed, replayable interventions with explicitly bounded scope.

    ``exception_rate`` selects an exact rounded fraction of rows carrying an
    unresolved execution obligation: unreceipted supplier value, pending refund
    value, or inventory shortage. It is not an empirical estimate of all errors.
    ``decision_placement`` describes authored sections, never PDF/Word pages.
    """

    line_count: int | None = Field(default=None, ge=3, le=64, strict=True)
    budget_spread: Literal["authored", "lognormal", "zipf"] = "authored"
    lognormal_sigma: float = Field(default=0.6, gt=0, le=2.5, strict=True)
    zipf_exponent: float = Field(default=1.0, gt=0, le=3.0, strict=True)
    exception_rate: float | None = Field(default=None, ge=0, le=1, strict=True)
    decision_placement: Literal["authored", "front", "middle", "back", "varied"] = "authored"
    row_order: Literal["authored", "reversed", "varied"] = "authored"
    comparison_detail: Literal["ratio", "variance", "amounts"] = "ratio"
    line_commentary: Literal["none", "largest_variance", "all"] = "none"
    revision_views: tuple[Literal["opened", "reviewed"], ...] = ()

    @model_validator(mode="after")
    def _supported(self) -> NativeRealismProfile:
        if len(set(self.revision_views)) != len(self.revision_views):
            raise ValueError("realism revision views must be distinct")
        if self.budget_spread != "lognormal" and self.lognormal_sigma != 0.6:
            raise ValueError("lognormal_sigma requires budget_spread=lognormal")
        if self.budget_spread != "zipf" and self.zipf_exponent != 1.0:
            raise ValueError("zipf_exponent requires budget_spread=zipf")
        return self


class NativeRealismMeasurements(Model):
    """Observed source IR and simulation quantities, not perceived realism scores."""

    scope: Literal["canonical_simulation_and_authored_ir"] = "canonical_simulation_and_authored_ir"
    line_count: int
    exception_rows: int
    realised_exception_rate: float
    budget_total_minor_units: int
    largest_budget_share: float
    sections: int
    narrative_sections: int
    table_sections: int
    table_rows: int
    numeric_cells: int
    formula_cells: int
    decision_section_index: int
    decision_section_fraction: float
    distinct_projected_facts: int
    fact_first_section: dict[str, int]
    historical_artifacts: int


@dataclass(frozen=True)
class NativeHistoricalView:
    phase: Literal["opened", "reviewed"]
    artifact: ArtifactIR
    fact_ids: tuple[str, ...]
    event_id: str


def _stream(seed: int, case_id: str, tactic: str) -> Rng:
    return Rng(seed).derive(_VERSION).derive(case_id).derive(tactic)


def apply_population_tactics(simulation: Simulator, profile: NativeRealismProfile,
                            *, process: str, case_id: str) -> Simulator:
    """Intervene on exogenous columns, then let the existing DAG recalculate.

    The floor is the original generator's minimum budget, which preserves the
    process's nonnegative obligations after redistributing the remaining total.
    No allocation changes a cohort's total or rounds monetary floats.
    """
    definitions = {
        "supplier_reconciliation": (240000, "unreceipted"),
        "customer_settlement": (90000, "pending"),
        "inventory_replenishment": (400, "inbound"),
    }
    if process not in definitions:
        raise ValueError("realism population tactics require a supported native process")
    if profile.budget_spread == "authored" and profile.exception_rate is None:
        return simulation
    floor, exception_column = definitions[process]
    rows = [row.values() for row in simulation.rows()]
    count = len(rows)
    columns = {"budget"} if profile.budget_spread != "authored" else set()
    if profile.exception_rate is not None:
        columns.add(exception_column)
    program = simulation.program.model_copy(update={"tables": tuple(table.model_copy(update={
        "columns": tuple(column.model_copy(update={"intervenable": True}) if column.name in columns
                         else column for column in table.columns)}) for table in simulation.program.tables)})
    limits = Limits(max_rows=64, max_work=100000, max_interventions=128)
    interventions: list[Intervention] = []
    if profile.budget_spread != "authored":
        rng = _stream(simulation.seed, case_id, "budget-spread")
        weights = (_lognormal_weights(rng, count, profile.lognormal_sigma)
                   if profile.budget_spread == "lognormal" else
                   rng.shuffled(_zipf_weights(count, profile.zipf_exponent)))
        total = sum(int(row["budget"]) for row in rows)
        if total < floor * count:
            raise ValueError("realism budget population cannot meet the process floor")
        allocated = allocate_scaled(total - floor * count, weights, decimals=0)
        interventions.extend(Intervention(table="transactions", column="budget", value=floor + int(value),
            entities=(position,)) for position, value in enumerate(allocated))
    redistributed = Simulator(program, seed=simulation.seed, interventions=tuple(interventions), limits=limits)
    if profile.exception_rate is not None:
        # A fixed permutation makes exception populations nested as the rate
        # increases: changing prevalence cannot swap unrelated case identities.
        exceptional = set(_stream(simulation.seed, case_id, "exception-membership").shuffled(
            list(range(count)))[:int(profile.exception_rate * count + 0.5)])
        # Inventory's nonexception is enough confirmed inbound to meet actual
        # demand. It is an upstream intervention; shortage remains a derivation.
        for position, row in enumerate(redistributed.rows()):
            if position in exceptional:
                continue
            values = row.values()
            value = int(values["actual"]) - int(values["stock"]) if process == "inventory_replenishment" else 0
            interventions.append(Intervention(table="transactions", column=exception_column,
                value=value, entities=(position,)))
    return Simulator(program, seed=simulation.seed, interventions=tuple(interventions), limits=limits)


def _ordered_rows(rows: Sequence[Row], profile: NativeRealismProfile, rng: Rng) -> list[Row]:
    detail = [row for row in rows if row.key != "total"]
    totals = [row for row in rows if row.key == "total"]
    if profile.row_order == "reversed":
        detail.reverse()
    elif profile.row_order == "varied":
        detail = rng.shuffled(detail)
    return [*detail, *totals]


def apply_presentation_tactics(artifact: ArtifactIR, profile: NativeRealismProfile,
                              *, seed: int, case_id: str) -> ArtifactIR:
    """Change evidence shape without changing canonical facts or cell addresses."""
    sections: list[ArtifactSection] = []
    commentaries: list[ArtifactSection] = []
    for section in artifact.sections:
        table = section.table
        if table is None:
            sections.append(section)
            continue
        if table.key == "comparison":
            commentary_rows = [row for row in table.rows if row.key != "total"]
            if profile.line_commentary == "largest_variance":
                commentary_rows = sorted(commentary_rows, key=lambda row: (
                    -abs(float(row.cells["actual"].value or 0) - float(row.cells["budget"].value or 0)), row.key))[:1]
            if profile.line_commentary != "none":
                for row in commentary_rows:
                    actual, budget = row.cells["actual"].fact_id, row.cells["budget"].fact_id
                    if actual is None or budget is None:
                        raise ValueError("line commentary requires canonical actual and budget facts")
                    commentaries.append(ArtifactSection(heading=row.label + " reconciliation commentary",
                        body="For " + row.label + ", the approved plan is {{fact:" + budget +
                            "}} and the recorded actual is {{fact:" + actual +
                            "}}. Read this line with the execution bridge before authorising the case.",
                        fact_ids=[budget, actual], semantic_role="evidence",
                        purpose="Explain a scoped comparison using the same canonical line as the table."))
            removed = ({"variance", "variance_pct"} if profile.comparison_detail == "amounts" else
                       {"variance_pct"} if profile.comparison_detail == "variance" else set())
            table = table.model_copy(update={"columns": [column for column in table.columns if column.key not in removed],
                "rows": [row.model_copy(update={"cells": {key: value for key, value in row.cells.items()
                                                          if key not in removed}}) for row in table.rows]})
        table = table.model_copy(update={"rows": _ordered_rows(table.rows, profile,
            _stream(seed, case_id, "row-order/" + table.key))})
        sections.append(section.model_copy(update={"table": table}))
    sections.extend(commentaries)
    placement = profile.decision_placement
    if placement == "varied":
        placement = _stream(seed, case_id, "decision-placement").choice(("front", "middle", "back"))
    if placement != "authored":
        decisions = [section for section in sections if section.semantic_role == "decision"]
        if len(decisions) != 1:
            raise ValueError("decision placement requires exactly one declared decision section")
        sections = [section for section in sections if section.semantic_role != "decision"]
        position = 0 if placement == "front" else len(sections) // 2 if placement == "middle" else len(sections)
        sections.insert(position, decisions[0])
    return artifact.model_copy(update={"sections": sections,
        "metadata": {**artifact.metadata, "native_realism_version": _VERSION,
                     "native_realism_profile_digest": content_key(profile.model_dump(mode="json"))}})


def historical_views(artifact: ArtifactIR, facts: Sequence[CanonicalFact],
                     profile: NativeRealismProfile) -> tuple[NativeHistoricalView, ...]:
    """Publish bounded status snapshots without borrowing future evidence.

    These are working assessments preceding an approved report, not fake
    contradictory numbers. Their canonical overlap keeps the whole family in
    one benchmark partition even when the files use different formats.
    """
    result: list[NativeHistoricalView] = []
    for phase in ("opened", "reviewed"):
        if phase not in profile.revision_views:
            continue
        date = next(fact for fact in facts if fact.kind.endswith(".date." + phase))
        cutoff = date.valid_from
        status = next(fact for fact in facts if fact.kind.endswith(".status") and fact.valid_from == cutoff)
        available = [fact for fact in facts if fact.value is not None and ".total." in fact.kind
                     and fact.valid_from <= cutoff and (fact.valid_to is None or cutoff < fact.valid_to)
                     and (fact.tx_from is None or fact.tx_from <= cutoff)]
        selected = [date, status, *sorted(available, key=lambda fact: fact.kind)]
        if not available:
            raise ValueError("historical realism view has no time-valid numerical evidence")
        lines = ["Recorded on {{fact:" + date.id + "}}. Assessment status: {{fact:" + status.id + "}}."]
        lines.extend(fact.kind.rsplit(".", 1)[-1].replace("_", " ").capitalize() + ": {{fact:" + fact.id + "}}."
                     for fact in selected[2:])
        identifier = artifact.id + "-" + phase.upper()
        view = artifact.model_copy(update={"id": identifier, "intent_id": identifier,
            "title": artifact.title + (" — initial case assessment" if phase == "opened" else " — working case assessment"),
            "sections": [ArtifactSection(heading="Assessment at issue", body=" ".join(lines),
                fact_ids=[fact.id for fact in selected], semantic_role="evidence")],
            "metadata": {**artifact.metadata, "created_at": cutoff.isoformat(), "authority": Authority.WORKING_DOCUMENT.value,
                "native_scenario_phase": phase}})
        assert date.event_id is not None
        result.append(NativeHistoricalView(phase, view, tuple(sorted(fact.id for fact in selected)), date.event_id))
    return tuple(result)


def measure_realism(artifact: ArtifactIR, simulation: Simulator, *, process: str,
                    historical_artifacts: int) -> NativeRealismMeasurements:
    rows = [row.values() for row in simulation.rows()]
    obligation = {"supplier_reconciliation": "unreceipted", "customer_settlement": "pending",
                  "inventory_replenishment": "shortage"}[process]
    exception_rows = sum(int(row[obligation]) > 0 for row in rows)
    budgets = [int(row["budget"]) for row in rows]
    first: dict[str, int] = {}
    for position, section in enumerate(artifact.sections):
        identifiers = set(references.referenced(section.body or ""))
        if section.table is not None:
            identifiers.update(cell.fact_id for row in section.table.rows for cell in row.cells.values() if cell.fact_id)
        for identifier in sorted(identifiers):
            first.setdefault(identifier, position)
    decision = next(position for position, section in enumerate(artifact.sections) if section.semantic_role == "decision")
    cells = [cell for section in artifact.sections if section.table for row in section.table.rows for cell in row.cells.values()]
    return NativeRealismMeasurements(line_count=len(rows), exception_rows=exception_rows,
        realised_exception_rate=exception_rows / len(rows), budget_total_minor_units=sum(budgets),
        largest_budget_share=max(budgets) / sum(budgets), sections=len(artifact.sections),
        narrative_sections=sum(bool(section.body) for section in artifact.sections),
        table_sections=sum(section.table is not None for section in artifact.sections),
        table_rows=sum(len(section.table.rows) for section in artifact.sections if section.table),
        numeric_cells=sum(isinstance(cell.value, (float, int)) and not isinstance(cell.value, bool) for cell in cells),
        formula_cells=sum(cell.formula is not None for cell in cells), decision_section_index=decision,
        decision_section_fraction=decision / max(1, len(artifact.sections) - 1),
        distinct_projected_facts=len(first), fact_first_section=dict(sorted(first.items())),
        historical_artifacts=historical_artifacts)


__all__ = ["NativeRealismProfile", "NativeRealismMeasurements"]
