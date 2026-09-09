"""One enterprise snapshot, many tasks. Collection plans remain a separate v1 API."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from pydantic import Field, model_validator

from ..corpus import write_json
from ..enterprise_sdk import EnterpriseEvalHarness
from ..providers import digest
from .dataset_contract import DatasetPlan, DatasetRequest

if TYPE_CHECKING:
    from ..world import World
    from .dataset import DatasetBuild, DatasetBuilder


class CompanyDatasetPlan(DatasetPlan):
    """A versioned company dataset; every stratum shares the same canonical world.

    Simulations describe different processes in this company. Each uses one
    fixed seed across batches. Batch ordinals select evidence, never rebuild
    the organisation or mint a replacement company.
    """

    schema_version: Literal["worldloom.company-dataset/v1"] = "worldloom.company-dataset/v1"
    builder_id: str = "worldloom-company-dataset/v1"
    minimum_companies: int = Field(default=1, ge=1, le=1, strict=True)
    split_by: Literal["task", "company", "case"] = "case"
    world_digest: str | None = None
    lineage: dict[str, dict[str, str]] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _one_company(self) -> CompanyDatasetPlan:
        sources = {(digest(s.source.company), s.source.period, s.source.periods) for s in self.strata}
        if len(sources) != 1:
            raise ValueError("company datasets require one company specification and episode timeline")
        if self.split_by == "company" and len(self.split_weights) > 1:
            raise ValueError("one company cannot populate company-disjoint splits; choose case or task")
        if set(self.lineage) - {s.id for s in self.strata}:
            raise ValueError("lineage names an unknown dataset stratum")
        return self


def load_dataset_plan(value: Any) -> DatasetPlan:
    """Dispatch by explicit schema; old collection manifests retain their bytes."""
    if isinstance(value, dict) and value.get("schema_version") == "worldloom.company-dataset/v1":
        return CompanyDatasetPlan.model_validate(value)
    return DatasetPlan.model_validate(value)


class FrozenCompanyBuilder:
    """An already built/narrated company can be shared by SDK, CLI and UI runs."""

    id = "worldloom-company-dataset/v1"

    def __init__(self, world: World, *, seed: int = 8128) -> None:
        self.world = world
        self.seed = seed
        self._harnesses: dict[str, EnterpriseEvalHarness] = {}

    def __call__(self, request: DatasetRequest) -> DatasetBuild:
        from ..synthesis import Simulator
        from .dataset import DatasetBuild

        source = request.source
        key = digest([source.simulation.model_dump(mode="json") if source.simulation else None,
                      source.incident_rule.model_dump(mode="json") if source.incident_rule else None])
        if key not in self._harnesses:
            harness = EnterpriseEvalHarness.from_world(self.world)
            if source.simulation is not None and source.incident_rule is not None:
                # The same process is the same evidence across normal/fault
                # strata. An incident title or batch number cannot reseed it.
                seed = int(digest([self.seed, source.simulation.model_dump(mode="json")])[:8], 16)
                harness = harness.with_operational_data(
                    Simulator(source.simulation, seed=seed), source.incident_rule,
                    include_world_records=False,
                ).with_operational_case_binding()
            self._harnesses[key] = harness
        return DatasetBuild(self._harnesses[key], {
            "scope": "company", "company_spec": source.company,
            "source_seed": self.seed, "acknowledged_unmet": list(source.acknowledged_unmet),
        })


def prepare_company(
    root: Path, plan: CompanyDatasetPlan, builder: DatasetBuilder | None, *, replay_only: bool,
) -> DatasetBuilder:
    """Commit the canonical source once and authenticate it before every resume."""
    from .. import company, sdk
    from ..world import World
    from .dataset import DatasetRefused, _files, _read

    if isinstance(builder, FrozenCompanyBuilder) and builder.seed != plan.seed and not replay_only:
        raise DatasetRefused("company builder seed differs from the dataset plan")
    source = plan.strata[0].source
    resolution = company.resolve(company.from_document(source.company))
    resolution.raise_for_conflicts()
    for cell in plan.strata:
        unmet = sorted(set(resolution.unmet) - set(cell.source.acknowledged_unmet))
        if unmet:
            raise DatasetRefused("company_unmet: " + "; ".join(unmet))
    context = root / "company"
    identity = {"company": source.company, "seed": plan.seed, "period": source.period,
                "periods": source.periods, "world_digest": plan.world_digest}
    if context.exists():
        receipt = _read(context / "receipt.json")
        if receipt.get("identity") != identity or receipt.get("files") != _files(context):
            raise DatasetRefused("canonical company snapshot changed after checkpoint")
    else:
        if replay_only:
            raise DatasetRefused("replay requires a committed company snapshot")
        staging = root / "company.pending"
        if staging.exists():
            import shutil
            if _read(staging / "identity.json") != identity:
                raise DatasetRefused("unfinished company belongs to another source")
            shutil.rmtree(staging)
        staging.mkdir()
        write_json(staging / "identity.json", identity)
        if builder is None:
            built = sdk.from_resolution(resolution, seed=plan.seed).build()
            if source.period is not None:
                built = built.episodes(source.period, periods=source.periods)
            world = built.world
        else:
            request = DatasetRequest(plan_digest=digest(plan.model_dump(mode="json")),
                                     stratum=plan.strata[0].id, ordinal=0, seed=plan.seed,
                                     remaining=plan.strata[0].count, source=source)
            world = builder(request.model_copy(deep=True)).harness.world
        world.export(staging / "world")
        actual = digest(_files(staging / "world"))
        if plan.world_digest is not None and actual != plan.world_digest:
            raise DatasetRefused("company snapshot does not match the planned world digest")
        write_json(staging / "resolution.json", {"unmet": list(resolution.unmet)})
        write_json(staging / "receipt.json", {"identity": identity, "world_digest": actual, "files": _files(staging)})
        staging.rename(context)
    world = World.load(context / "world")
    return builder if builder is not None else FrozenCompanyBuilder(world, seed=plan.seed)


__all__ = ["CompanyDatasetPlan", "FrozenCompanyBuilder", "load_dataset_plan"]
