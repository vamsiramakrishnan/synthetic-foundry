from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.enterprise_queries import PlannedEnterpriseQuery
from worldloom.evals.dataset import (
    CompanyDatasetBuilder,
    DatasetRefused,
    compile_dataset,
    verify_dataset,
)
from worldloom.evals.dataset_contract import (
    DatasetEntry,
    DatasetPlan,
    DatasetSource,
    DatasetStratum,
)
from worldloom.evals.dataset_identity import (
    assign_splits,
    program_identity,
    request_identity,
)
from worldloom.synthesis import IncidentRule, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile


def plan(count: int = 18, **kwargs) -> DatasetPlan:
    source = DatasetSource(
        company={"engine": "retail"}, scenario=operational_profile("retail"),
        simulation=with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}),
        incident_rule=IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        dag_shapes=("fan_in", "map_read"), pool_size=12, planning_budget=64,
    )
    fields = dict(strata=(DatasetStratum(id="retail", count=count, source=source),),
                  max_batches=6, split_by="company", max_per_task=3,
                  max_per_request=3, minimum_tasks=4)
    return DatasetPlan(**{**fields, **kwargs})


class CountingBuilder(CompanyDatasetBuilder):
    def __init__(self):
        self.calls = 0

    def __call__(self, request):
        self.calls += 1
        return super().__call__(request)


def tree(path: Path) -> dict[str, bytes]:
    return {p.relative_to(path).as_posix(): p.read_bytes() for p in path.rglob("*") if p.is_file()}


@pytest.fixture(scope="module")
def completed(tmp_path_factory):
    directory = tmp_path_factory.mktemp("dataset")
    builder = CountingBuilder()
    run = compile_dataset(plan(), directory, builder=builder)
    assert run.report.complete, run.report
    return directory, run, builder


def test_real_dataset_drives_new_worlds_and_meets_contract(completed):
    directory, run, builder = completed
    assert builder.calls >= 3
    assert run.report.accepted == 18
    assert run.report.tasks >= 4
    assert run.report.companies >= 3
    assert all(run.report.split_counts.values())
    entries = [json.loads(line) for line in (directory / "queryset.jsonl").read_text().splitlines()]
    for field in ("company_id", "case_id"):
        by_key = {}
        for entry in entries:
            by_key.setdefault(entry[field], set()).add(entry["split"])
        assert all(len(values) == 1 for values in by_key.values())
    evidence = {}
    for entry in entries:
        for key in entry["evidence"]:
            evidence.setdefault(key, set()).add(entry["split"])
    assert all(len(values) == 1 for values in evidence.values())
    assert all(set(json.loads(line)) == {"id", "query", "split"} for line in
               (directory / "agent-requests.jsonl").read_text().splitlines())
    assert verify_dataset(directory) == run.report


def test_completed_replay_has_zero_calls_and_identical_bytes(completed):
    directory, run, _ = completed
    before = tree(directory)
    builder = CountingBuilder()
    replay = compile_dataset(plan(), directory, builder=builder, replay_only=True)
    assert builder.calls == 0
    assert replay.report == run.report
    assert tree(directory) == before


def test_pause_resume_equals_uninterrupted(tmp_path, completed):
    builder = CountingBuilder()
    partial = compile_dataset(plan(), tmp_path, builder=builder, batch_limit=1)
    assert not partial.report.complete
    assert not (tmp_path / "queryset.jsonl").exists()
    assert (tmp_path / "candidates.jsonl").exists()
    assert verify_dataset(tmp_path) == partial.report
    resumed = compile_dataset(plan(), tmp_path, builder=builder)
    assert resumed.report.complete
    directory, _, original = completed
    assert builder.calls == original.calls
    assert tree(tmp_path) == tree(directory)


def test_tampered_batch_and_changed_plan_refuse(tmp_path, completed):
    import shutil

    directory, _, _ = completed
    shutil.copytree(directory, tmp_path, dirs_exist_ok=True)
    with pytest.raises(DatasetRefused, match="plan changed"):
        compile_dataset(plan(max_per_task=4), tmp_path)
    evidence = tmp_path / "batches/00000000/qualified/connector-data.json"
    evidence.write_text(evidence.read_text() + " ")
    with pytest.raises(DatasetRefused, match="changed after checkpoint"):
        compile_dataset(plan(), tmp_path, replay_only=True)
    with pytest.raises(DatasetRefused, match="changed after export"):
        verify_dataset(tmp_path)


def test_orphaned_staging_recovers_only_matching_request(tmp_path, completed):
    import shutil

    directory, _, _ = completed
    shutil.copytree(directory, tmp_path, dirs_exist_ok=True)
    staging = tmp_path / "batches/00000000.pending"
    staging.mkdir()
    committed = tmp_path / "batches/00000000/request.json"
    shutil.copyfile(committed, staging / "request.json")
    (staging / "unfinished.json").write_text("unfinished")
    compile_dataset(plan(), tmp_path, replay_only=True)
    assert not staging.exists()
    assert tree(tmp_path) == tree(directory)
    staging.mkdir()
    (staging / "request.json").write_text("{}")
    with pytest.raises(DatasetRefused, match="different generation request"):
        compile_dataset(plan(), tmp_path, replay_only=True)
    assert staging.exists()


def test_inert_labels_and_alpha_renaming_do_not_create_tasks(completed):
    directory, _, _ = completed
    raw = (directory / "batches/00000000/qualified/queries.jsonl").read_text().splitlines()[0]
    query = PlannedEnterpriseQuery.model_validate_json(raw)
    payload = query.model_dump(mode="json")
    payload["workflow"] = "renamed_workflow"
    payload["dimensions"].update(topology="invented", content_action="invented", audience="invented")
    mapping = {node["id"]: f"renamed-{i}" for i, node in enumerate(payload["expected_dag"])}
    def rename(value, field=""):
        if isinstance(value, dict):
            return {key: rename(child, key) for key, child in value.items()}
        if isinstance(value, list):
            return [rename(child, field) for child in value]
        return mapping.get(value, value) if isinstance(value, str) and field in {"id", "node", "depends_on"} else value
    payload["expected_dag"] = rename(payload["expected_dag"])
    other = PlannedEnterpriseQuery.model_validate(payload)
    assert program_identity(query) == program_identity(other)
    nodes = payload["expected_dag"]
    reads = [n for n in nodes if not n["depends_on"]]
    payload["expected_dag"] = list(reversed(reads)) + [n for n in nodes if n["depends_on"]]
    assert program_identity(query) == program_identity(PlannedEnterpriseQuery.model_validate(payload))
    mutation = other.generation.mutation.model_copy(update={"target_state": "resolved"})
    changed = other.model_copy(update={"generation": other.generation.model_copy(update={"mutation": mutation})})
    assert program_identity(query) != program_identity(changed)


def entry(i, *, task="task", case=None, company=None, evidence=()):
    return DatasetEntry(id=str(i), query_id=str(i), stratum="retail", batch=0, task_id=task,
                        case_id=case or str(i), request_id=str(i), company_id=company or str(i),
                        evidence=evidence, proof_digest="proof", query="query")


def test_transitive_evidence_and_counterfactuals_stay_together():
    rows = [entry(1, evidence=("a",)), entry(2, evidence=("a", "b")), entry(3, evidence=("b",)),
            entry(4), entry(5)]
    assigned, counts, groups, largest = assign_splits(rows, plan())
    assert assigned["1"] == assigned["2"] == assigned["3"]
    assert groups == 3 and largest == 3
    assert all(counts.values())
    _, counts, groups, _ = assign_splits(rows, plan(split_by="task"))
    assert groups == 1 and sum(v == 0 for v in counts.values()) == 2


def test_company_ids_and_record_suffix_do_not_buy_language_diversity():
    assert request_identity("Review Ironvale's 12 cases. Scope this work to these source records: A", company_name="Ironvale") == request_identity(
        "Review Northstar's 80 cases. Scope this work to these source records: B", company_name="Northstar")


def test_caps_prevent_padding_and_withhold_publishable_queryset(tmp_path):
    run = compile_dataset(plan(24, max_per_task=1, max_per_request=1, max_batches=2), tmp_path)
    assert not run.report.complete
    assert run.report.accepted < 24
    assert not (tmp_path / "queryset.jsonl").exists()
    assert not (tmp_path / "agent-requests.jsonl").exists()
    with pytest.raises(DatasetRefused, match="dataset_incomplete"):
        run.raise_if_incomplete()


def test_cli_reports_paused_checkpoint_and_verifies_complete(completed, tmp_path):
    path = tmp_path / "plan.json"
    path.write_text(plan().model_dump_json())
    runner = CliRunner()
    result = runner.invoke(app, ["evals", "dataset", "compile", str(path), "--out", str(tmp_path / "run"), "--batch-limit", "1"])
    assert result.exit_code == 3, result.output
    result = runner.invoke(app, ["evals", "dataset", "verify", str(completed[0])])
    assert result.exit_code == 0, result.output


def test_replay_cannot_generate_missing_batch(tmp_path):
    builder = CountingBuilder()
    with pytest.raises(DatasetRefused, match="replay requires"):
        compile_dataset(plan(), tmp_path, builder=builder, replay_only=True)
    assert builder.calls == 0


def test_nonexistent_cell_does_not_starve_other_sources(tmp_path):
    original = plan()
    good = original.strata[0].model_copy(update={"count": 4})
    bad = DatasetStratum(id="absent", count=4, source=good.source.model_copy(update={"where": {"workflow": "absent"}, "planning_budget": 8}))
    run = compile_dataset(original.model_copy(update={"strata": (bad, good), "max_batches": 2}), tmp_path)
    assert run.report.remaining["absent"] == 4
    assert run.report.remaining["retail"] < 4
    assert run.report.refusals["no_matching_plans"] == 1


def test_builder_cannot_mutate_the_sealed_plan_through_nested_dicts(tmp_path):
    original = plan()
    before = original.model_dump(mode="json")

    class MutatingBuilder(CompanyDatasetBuilder):
        def __call__(self, request):
            built = super().__call__(request)
            request.source.company["engine"] = "banking"
            request.source.where["workflow"] = "different"
            return built

    run = compile_dataset(original, tmp_path, builder=MutatingBuilder(), batch_limit=1)
    assert run.report.accepted > 0
    assert original.model_dump(mode="json") == before
    assert json.loads((tmp_path / "plan.json").read_text()) == before
