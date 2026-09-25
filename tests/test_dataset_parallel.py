"""Waves of dataset batches commit concurrently and still replay byte for byte."""

from __future__ import annotations

import dataclasses
import json
import shutil
from pathlib import Path

import pytest

from worldloom import packkit
from worldloom.evals import (
    CompanyDatasetPlan,
    DatasetPlan,
    DatasetStratum,
    FrozenCompanyBuilder,
    compile_dataset,
)
from worldloom.evals.company_dataset import load_dataset_plan
from worldloom.evals.dataset import DatasetRefused, _files, dataset_workers
from worldloom.providers import digest
from worldloom.studio import preset
from worldloom.world import World


def plan(**updates) -> CompanyDatasetPlan:
    spec = preset()
    source = spec.use_cases[0].source(spec).model_copy(update={"pool_size": 12, "planning_budget": 256})
    values = dict(strata=(DatasetStratum(id="inventory", count=36, source=source),),
                  max_batches=8, max_per_task=6, max_per_request=4, minimum_tasks=4, batch_wave=4)
    return CompanyDatasetPlan(**{**values, **updates})


class PolicyEcho(FrozenCompanyBuilder):
    """Records the policy its generation read, so a worker's packs are visible."""

    def __call__(self, request):
        built = super().__call__(request)
        return dataclasses.replace(built, metadata={**built.metadata, "workers_policy": packkit.policy("dataset.workers")})


@pytest.fixture(scope="module")
def serial(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("wave-serial")
    run = compile_dataset(plan(), root, workers=1)
    assert run.report.complete, run.report
    assert run.report.batches == 4  # one whole wave of four
    return root


def test_a_sequential_plan_dumps_and_digests_as_before_waves_existed() -> None:
    sequential = plan(batch_wave=1)
    dumped = sequential.model_dump(mode="json")
    assert "batch_wave" not in dumped
    assert load_dataset_plan(dumped) == sequential
    widened = plan()
    assert widened.model_dump(mode="json")["batch_wave"] == 4
    assert digest(widened.model_dump(mode="json")) != digest(dumped)
    collection = DatasetPlan(strata=sequential.strata, minimum_companies=1)
    assert "batch_wave" not in collection.model_dump(mode="json")
    assert DatasetPlan.model_validate({**collection.model_dump(mode="json"), "batch_wave": 3}).batch_wave == 3


def test_worker_count_never_changes_a_byte(tmp_path: Path, serial: Path) -> None:
    run = compile_dataset(plan(), tmp_path, workers=4)
    assert run.report.complete
    assert _files(tmp_path) == _files(serial)
    assert (tmp_path / "manifest.json").read_bytes() == (serial / "manifest.json").read_bytes()


def test_a_run_killed_mid_wave_resumes_to_the_same_bytes(tmp_path: Path, serial: Path) -> None:
    # A pause inside the wave issues exactly the wave's prefix.
    paused = compile_dataset(plan(), tmp_path, batch_limit=2, workers=2)
    assert paused.report.batches == 2 and not paused.report.complete
    for index in (0, 1):
        name = f"batches/{index:08d}"
        assert _files(tmp_path / name) == _files(serial / name)
    # A kill leaves one batch committed and another half staged beside it.
    shutil.copytree(serial / "batches" / "00000002", tmp_path / "batches" / "00000002")
    staged = tmp_path / "batches" / "00000003.pending"
    shutil.copytree(serial / "batches" / "00000003", staged)
    (staged / "receipt.json").unlink()
    shutil.rmtree(staged / "qualified")
    resumed = compile_dataset(plan(), tmp_path, workers=4)
    assert resumed.report.complete
    assert not staged.exists()
    assert _files(tmp_path) == _files(serial)


def test_workers_run_under_the_packs_in_force(tmp_path: Path, serial: Path) -> None:
    packs = tmp_path / "packs" / "policy"
    packs.mkdir(parents=True)
    (packs / "wide.json").write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "policy", "name": "wide",
                                                 "body": {"values": {"dataset.workers": 3}}}))
    world = World.load(serial / "company" / "world")
    with packkit.use("policy:wide", roots=[tmp_path / "packs"]):
        assert dataset_workers() == 3
        compile_dataset(plan(), tmp_path / "out", builder=PolicyEcho(world, seed=8128), workers=2)
    batches = sorted((tmp_path / "out" / "batches").iterdir())
    assert len(batches) == 4
    assert {json.loads((b / "source.json").read_text())["workers_policy"] for b in batches} == {3}


class RootsEcho(FrozenCompanyBuilder):
    """Records whether a pack visible only through the roots is visible to generation."""

    def __call__(self, request):
        from worldloom.connector_definition import reference_connectors

        built = super().__call__(request)
        return dataclasses.replace(built, metadata={**built.metadata, "sees_acme": "acme" in reference_connectors()})


def test_workers_search_the_pack_roots_of_the_compile(tmp_path: Path, serial: Path) -> None:
    """A pack visible but not in force (a workspace connector) reached only the
    parent; with workers it vanished and the batches changed with the count."""
    from worldloom.connector_definition import load_connector_definition

    connectors = tmp_path / "packs" / "connector"
    connectors.mkdir(parents=True)
    body = load_connector_definition("jira").model_dump(mode="json", by_alias=True)
    body["connector"] = "acme"
    body.pop("catalog", None)
    (connectors / "acme.json").write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "connector",
                                                      "name": "acme", "body": body}))
    world = World.load(serial / "company" / "world")
    outs = {}
    for workers in (1, 2):
        with packkit.use(roots=[tmp_path / "packs"]):
            compile_dataset(plan(), tmp_path / f"out{workers}", builder=RootsEcho(world, seed=8128), workers=workers)
        outs[workers] = {json.loads((b / "source.json").read_text())["sees_acme"]
                         for b in sorted((tmp_path / f"out{workers}" / "batches").iterdir())}
    assert outs == {1: {True}, 2: {True}}


def test_worker_count_resolves_argument_then_environment_then_policy(monkeypatch) -> None:
    monkeypatch.delenv("WORLDLOOM_DATASET_WORKERS", raising=False)
    assert dataset_workers() == 1
    monkeypatch.setenv("WORLDLOOM_DATASET_WORKERS", "3")
    assert dataset_workers() == 3 and dataset_workers(2) == 2
    with pytest.raises(ValueError, match="positive"):
        dataset_workers(0)


def test_a_builder_that_cannot_cross_processes_is_refused_by_name(tmp_path: Path, serial: Path) -> None:
    world = World.load(serial / "company" / "world")
    unpicklable = FrozenCompanyBuilder(world, seed=8128, query_transforms={"inventory": lambda query: query})
    with pytest.raises(DatasetRefused, match="process boundary"):
        compile_dataset(plan(), tmp_path, builder=unpicklable, workers=2)
