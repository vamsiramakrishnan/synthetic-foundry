from __future__ import annotations

import json

import pytest

from worldloom.evals import (
    CompanyDatasetPlan,
    DatasetSource,
    DatasetStratum,
    FrozenCompanyBuilder,
    compile_dataset,
)
from worldloom.evals.company_dataset import load_dataset_plan
from worldloom.evals.dataset import DatasetRefused, _files, verify_dataset
from worldloom.providers import digest
from worldloom.studio import Studio, preset


def plan(count=36, **updates):
    spec = preset()
    source = spec.use_cases[0].source(spec).model_copy(update={"pool_size": 12, "planning_budget": 256})
    values = dict(strata=(DatasetStratum(id="inventory", count=count, source=source),),
                  max_batches=8, max_per_task=6, max_per_request=4, minimum_tasks=4)
    return CompanyDatasetPlan(**{**values, **updates})


@pytest.fixture(scope="module")
def generated(tmp_path_factory):
    root = tmp_path_factory.mktemp("company-dataset")
    run = compile_dataset(plan(), root)
    assert run.report.complete, run.report
    return root, run


def test_many_batches_share_exact_world_and_case_isolation(generated):
    root, run = generated
    assert run.report.companies == 1
    assert run.report.batches >= 3
    worlds = [_files(p / "world") for p in sorted((root / "batches").iterdir())]
    assert all(world == _files(root / "company/world") for world in worlds)
    entries = [json.loads(line) for line in (root / "queryset.jsonl").read_text().splitlines()]
    assert len({e["company_id"] for e in entries}) == 1
    assert len({e["case_id"] for e in entries}) > 12
    evidence = {}
    for row in entries:
        for key in row["evidence"]:
            evidence.setdefault(key, set()).add(row["split"])
    assert all(len(splits) == 1 for splits in evidence.values())
    assert verify_dataset(root) == run.report


def test_pause_resume_and_offline_replay_keep_company_bytes(tmp_path, generated, monkeypatch):
    partial = compile_dataset(plan(), tmp_path, batch_limit=1)
    assert not partial.report.complete
    canonical = _files(tmp_path / "company")
    resumed = compile_dataset(plan(), tmp_path)
    assert resumed.report.complete
    assert _files(tmp_path / "company") == canonical
    original, _ = generated
    assert _files(tmp_path) == _files(original)
    before = _files(tmp_path)
    monkeypatch.setattr(FrozenCompanyBuilder, "__call__", lambda *args: pytest.fail("replay called a builder"))
    compile_dataset(plan(), tmp_path, replay_only=True)
    assert _files(tmp_path) == before


def test_same_name_does_not_authorize_rebuilding_other_facts(tmp_path):
    studio = Studio(tmp_path / "studio")
    spec = preset()
    world, source = studio.snapshot(spec)
    planned = plan(12, minimum_tasks=2, split_weights={"train": 1}, world_digest=digest(_files(source / "world")))
    with pytest.raises(DatasetRefused, match="builder seed"):
        compile_dataset(planned, tmp_path / "wrong-seed", builder=FrozenCompanyBuilder(world, seed=spec.seed + 1))

    class Changed(FrozenCompanyBuilder):
        def __call__(self, request):
            from dataclasses import replace

            from worldloom.evals.dataset import DatasetBuild
            built = super().__call__(request)
            changed = replace(built.harness.world, seed=9000)
            return DatasetBuild(replace(built.harness, world=changed), {})

    with pytest.raises(DatasetRefused, match="world digest"):
        compile_dataset(planned, tmp_path / "bad", builder=Changed(world, seed=spec.seed))


def test_company_scope_rejects_mixed_sources_and_company_splits():
    original = plan()
    with pytest.raises(ValueError, match="company-disjoint"):
        plan(split_by="company")
    with pytest.raises(ValueError):
        plan(minimum_companies=2)
    other = DatasetSource.model_validate({**original.strata[0].source.model_dump(mode="json"),
                                         "company": {"engine": "retail", "identity": {"company_name": "Other"}}})
    with pytest.raises(ValueError, match="one company specification"):
        plan(strata=(*original.strata, DatasetStratum(id="other", count=12, source=other)))
    assert isinstance(load_dataset_plan(original.model_dump(mode="json")), CompanyDatasetPlan)


def test_company_snapshot_tampering_refuses_before_generation(tmp_path, generated):
    import shutil
    root, _ = generated
    shutil.copytree(root, tmp_path, dirs_exist_ok=True)
    target = tmp_path / "company/world/world.json"
    target.write_bytes(target.read_bytes() + b" ")
    with pytest.raises(DatasetRefused, match="company snapshot changed"):
        compile_dataset(plan(), tmp_path, replay_only=True)


def test_fixed_evidence_exhaustion_cannot_mint_companies(tmp_path):
    result = compile_dataset(plan(100, max_batches=2, max_per_case=1, max_per_task=1, max_per_request=1), tmp_path)
    assert not result.report.complete
    assert result.report.companies <= 1
    assert not (tmp_path / "queryset.jsonl").exists()
    assert result.report.findings
