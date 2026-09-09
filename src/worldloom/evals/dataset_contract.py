"""Dataset obligations, separate from the generators that try to satisfy them."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, model_validator

from ..enterprise_specs import ScenarioProfile
from ..models import Model
from ..synthesis.connectors import IncidentRule
from ..synthesis.models import Program


class DatasetSource(Model):
    company: dict[str, Any]
    scenario: ScenarioProfile
    period: str | None = None
    periods: int = Field(default=1, ge=1)
    simulation: Program | None = None
    incident_rule: IncidentRule | None = None
    dag_shapes: tuple[str, ...] = ("*",)
    where: dict[str, str] = Field(default_factory=dict)
    pool_size: int = Field(default=32, ge=1, le=512)
    planning_budget: int = Field(default=4096, ge=1)
    acknowledged_unmet: tuple[str, ...] = ()

    @model_validator(mode="after")
    def _source(self) -> DatasetSource:
        from ..company import from_document, resolve
        from ..enterprise_dag import shape_catalogue

        resolution = resolve(from_document(self.company))
        resolution.raise_for_conflicts()
        if set(self.acknowledged_unmet) - set(resolution.unmet):
            raise ValueError("acknowledged company limitations no longer match the resolution")
        if (self.simulation is None) != (self.incident_rule is None):
            raise ValueError("simulation and incident_rule must be supplied together")
        if self.dag_shapes != ("*",) and (
            not self.dag_shapes or set(self.dag_shapes) - shape_catalogue().keys()
        ):
            raise ValueError("dataset sources require supported executable DAG shapes")
        fields = {"workflow", "source_set", "source_entities", "input_formats", "destination",
                  "destination_entity", "operation", "output_format", "failure", "dag_shape"}
        if set(self.where) - fields or any(not value for value in self.where.values()):
            raise ValueError("unsupported or empty dataset source predicate")
        return self


class DatasetStratum(Model):
    id: str = Field(min_length=1)
    count: int = Field(ge=1, strict=True)
    source: DatasetSource


class DatasetPlan(Model):
    schema_version: Literal["worldloom.dataset/v1"] = "worldloom.dataset/v1"
    seed: int = Field(default=8128, strict=True)
    builder_id: str = "worldloom-dataset-source/v1"
    strata: tuple[DatasetStratum, ...]
    max_batches: int = Field(default=128, ge=1, strict=True)
    max_per_task: int = Field(default=100, ge=1, strict=True)
    max_per_case: int = Field(default=3, ge=1, strict=True)
    max_per_request: int = Field(default=10, ge=1, strict=True)
    minimum_tasks: int = Field(default=2, ge=1, strict=True)
    minimum_companies: int = Field(default=2, ge=1, strict=True)
    split_by: Literal["task", "company"] = "task"
    split_weights: dict[str, int] = Field(default_factory=lambda: {"train": 80, "validation": 10, "test": 10})

    @model_validator(mode="after")
    def _plan(self) -> DatasetPlan:
        if not self.strata or len({s.id for s in self.strata}) != len(self.strata):
            raise ValueError("dataset strata must be nonempty and have unique IDs")
        if (not self.builder_id or not self.split_weights
                or any(k not in {"train", "validation", "test"} or type(v) is not int or v < 1
                       for k, v in self.split_weights.items())):
            raise ValueError("declare a builder identity and positive train/validation/test weights")
        target = sum(s.count for s in self.strata)
        if max(self.minimum_tasks, self.minimum_companies, len(self.split_weights)) > target:
            raise ValueError("diversity and split minima exceed the requested row count")
        return self


class DatasetRequest(Model):
    plan_digest: str
    stratum: str
    ordinal: int
    seed: int
    remaining: int
    source: DatasetSource
    refusals: dict[str, int] = Field(default_factory=dict)
    saturated_tasks: tuple[str, ...] = ()
    saturated_requests: tuple[str, ...] = ()


class DatasetEntry(Model):
    id: str
    query_id: str
    stratum: str
    batch: int
    task_id: str
    case_id: str
    request_id: str
    company_id: str
    evidence: tuple[str, ...]
    proof_digest: str
    query: str
    dimensions: dict[str, str] = Field(default_factory=dict)


class DatasetReport(Model):
    target: int
    accepted: int
    batches: int
    complete: bool
    remaining: dict[str, int]
    refusals: dict[str, int]
    tasks: int
    cases: int
    requests: int
    companies: int
    split_counts: dict[str, int]
    split_groups: int
    largest_split_group: int
    findings: tuple[str, ...]
    planned_candidates: int = 0
    equivalent_plans_removed: int = 0
    facets: dict[str, dict[str, int]] = Field(default_factory=dict)


__all__ = ["DatasetSource", "DatasetStratum", "DatasetPlan", "DatasetRequest", "DatasetEntry", "DatasetReport"]
