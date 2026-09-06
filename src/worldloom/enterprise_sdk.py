"""Small fluent SDK for enterprise query planning and corpus materialization."""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from .connector_data import ConnectorProjectionRegistry
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

    def take(self, count: int) -> EnterpriseEvalHarness:
        return replace(self, limit=count)

    def plan(self) -> tuple[tuple[PlannedEnterpriseQuery, ...], CoverageReport | None]:
        queries, report = plan_queries(self.world, registry=self.registry, profile=self.profile, strategy=self.strategy, limit=self.limit)
        return tuple(queries), report

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
        )
        return tuple(queries), report
