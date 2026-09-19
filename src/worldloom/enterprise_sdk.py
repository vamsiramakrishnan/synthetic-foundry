"""Small fluent SDK for enterprise query planning and corpus materialization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import islice
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .connector_data import (
    ConnectorDataset,
    ConnectorProjectionRegistry,
    generate_connector_data,
)
from .enterprise_artifacts import RenderedEvalArtifact, render_corpus_artifacts
from .enterprise_corpus import EnterpriseCorpus, materialize_corpus
from .enterprise_queries import CoverageReport, PlannedEnterpriseQuery, plan_queries
from .enterprise_specs import (
    CoverageProfile,
    EnterpriseEvalSpec,
    ScenarioProfile,
    SpecRegistry,
    apply_scenario_profile,
    builtin_registry,
)

if TYPE_CHECKING:
    from .enterprise_qualification import EnterpriseQualification, QueryBinder
    from .synthesis.connectors import IncidentRule
    from .synthesis.engine import Simulator
    from .world import World


@dataclass(frozen=True)
class EnterpriseEvalHarness:
    world: World
    registry: SpecRegistry
    profile: CoverageProfile
    strategy: Literal["covering", "exhaustive"] = "covering"
    limit: int | None = None
    projections: ConnectorProjectionRegistry | None = None
    strict_sources: bool = False
    dag_shapes: tuple[str, ...] = ()
    operational_max_cases: int | None = None

    @classmethod
    def from_world(cls, world: World) -> EnterpriseEvalHarness:
        return cls(world=world, registry=builtin_registry(), profile=CoverageProfile())

    def with_registry(self, registry: SpecRegistry) -> EnterpriseEvalHarness:
        return replace(self, registry=registry)

    def with_profile(self, profile: CoverageProfile) -> EnterpriseEvalHarness:
        return replace(self, profile=profile)

    def with_spec(self, spec: EnterpriseEvalSpec) -> EnterpriseEvalHarness:
        return replace(
            self,
            registry=SpecRegistry(spec.connectors, spec.workflows, spec.processes),
            profile=spec.coverage,
        )

    def with_scenario(self, profile: ScenarioProfile) -> EnterpriseEvalHarness:
        return replace(
            self,
            registry=apply_scenario_profile(self.registry, profile),
            profile=profile.coverage,
        )

    def exhaustive(self) -> EnterpriseEvalHarness:
        return replace(self, strategy="exhaustive")

    def with_projections(
        self, projections: ConnectorProjectionRegistry
    ) -> EnterpriseEvalHarness:
        return replace(self, projections=projections)

    def with_operational_data(
        self, simulator: Simulator, rule: IncidentRule, *, include_world_records: bool = True
    ) -> EnterpriseEvalHarness:
        """Use stateful operational cases, and refuse absent query sources."""
        from .synthesis.connectors import operational_projections

        return replace(self, projections=operational_projections(
            simulator, rule, include_world_records=include_world_records
        ), strict_sources=True)

    def require_sources(self) -> EnterpriseEvalHarness:
        """Refuse missing source evidence instead of generating placeholder rows."""
        return replace(self, strict_sources=True)

    def with_operational_case_binding(self, *, max_cases: int = 128) -> EnterpriseEvalHarness:
        """Bind each query to a bounded cohort of actual cross-connector cases."""
        if type(max_cases) is not int or not 1 <= max_cases <= 128:
            raise ValueError("max_cases must be an integer in [1,128]")
        return replace(self, operational_max_cases=max_cases, strict_sources=True)

    def with_dag_grammar(self, *shapes: str) -> EnterpriseEvalHarness:
        """Opt into versioned executable shapes; no arguments selects the catalogue."""
        from .enterprise_dag import shape_catalogue
        unknown = set(shapes) - shape_catalogue().keys()
        if unknown:
            raise ValueError(f"unknown DAG shapes: {sorted(unknown)}")
        return replace(self, dag_shapes=tuple(shapes) or ("*",))

    def take(self, count: int) -> EnterpriseEvalHarness:
        return replace(self, limit=count)

    def plan(self) -> tuple[tuple[PlannedEnterpriseQuery, ...], CoverageReport | None]:
        queries, report = plan_queries(self.world, registry=self.registry, profile=self.profile, strategy=self.strategy, limit=self.limit, dag_shapes=self.dag_shapes, projections=self.projections)
        planned = tuple(queries)
        binder = self._case_binder(planned)
        if binder is not None:
            planned = tuple(binder(query, ordinal) for ordinal, query in enumerate(planned))
        return planned, report

    def _case_binder(self, queries: tuple[PlannedEnterpriseQuery, ...]) -> QueryBinder | None:
        if self.operational_max_cases is None:
            return None
        from .synthesis.connectors import bind_case_query

        connectors = tuple(sorted({source.connector for query in queries
                                   for source in query.generation.source_requirements}))
        data: ConnectorDataset | None = None
        max_cases = self.operational_max_cases

        def bind(query: PlannedEnterpriseQuery, ordinal: int) -> PlannedEnterpriseQuery:
            nonlocal data
            if data is None:
                data = generate_connector_data(self.world, connectors, projections=self.projections)
            return bind_case_query(query, data.records, ordinal=ordinal, max_cases=max_cases)

        return bind

    def qualify(self, *, pool_size: int, max_selected: int | None = None) -> EnterpriseQualification:
        """Execute a finite exhaustive pool before selecting semantic and case coverage.

        The pool uses the planner's interleaved exhaustive order, independently
        of ``take`` or the ordinary planning strategy, and of the world's
        groundable inventory: qualification grounds each query by executing it
        and refuses per query, with the reason, in its own report. ``take``
        supplies the output cap unless ``max_selected`` overrides it. One
        lookahead query establishes whether the bounded pool exhausted the
        requested space.
        """
        from .enterprise_qualification import qualify_queries

        if pool_size < 1:
            raise ValueError("pool_size must be positive")
        cap = self.limit if max_selected is None else max_selected
        if cap is not None and cap < 1:
            raise ValueError("max_selected must be positive")
        queries, _ = plan_queries(self.world, registry=self.registry, profile=self.profile,
                                  strategy="exhaustive", dag_shapes=self.dag_shapes, ground=False)
        bounded = tuple(islice(queries, pool_size + 1))
        pool = bounded[:pool_size]
        return qualify_queries(self.world, pool, pool_size=pool_size,
                               pool_exhausted=len(bounded) <= pool_size,
                               strength=self.profile.strengths, max_selected=cap,
                               projections=self.projections, binder=self._case_binder(pool))

    def build(self) -> tuple[EnterpriseCorpus, CoverageReport | None]:
        queries, report = self.plan()
        return (
            materialize_corpus(
                self.world, queries, projections=self.projections, strict_sources=self.strict_sources
            ),
            report,
        )

    def build_and_render(
        self, directory: Path, *, render_limit: int | None = None
    ) -> tuple[
        EnterpriseCorpus,
        CoverageReport | None,
        tuple[RenderedEvalArtifact, ...],
    ]:
        corpus, report = self.build()
        rendered = render_corpus_artifacts(
            corpus, directory, limit=render_limit
        )
        return corpus, report, rendered

    def shard(
        self, index: int, count: int
    ) -> tuple[tuple[PlannedEnterpriseQuery, ...], CoverageReport | None]:
        queries, report = plan_queries(
            self.world,
            registry=self.registry,
            profile=self.profile,
            strategy=self.strategy,
            limit=self.limit,
            shard_index=index,
            shard_count=count,
            dag_shapes=self.dag_shapes,
            projections=self.projections,
        )
        planned = tuple(queries)
        binder = self._case_binder(planned)
        if binder is not None:
            planned = tuple(binder(query, index + ordinal * count) for ordinal, query in enumerate(planned))
        return planned, report
