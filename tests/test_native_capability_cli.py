"""Exercise the public CLI across generation, measured feedback and workflows."""
from __future__ import annotations

import json
import shlex
import sys
from dataclasses import dataclass
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld
from worldloom.benchmarks import (
    BenchmarkRequirements,
    CoverageRequirement,
    NativeBenchmark,
    NativeCurriculum,
    NativeScenarioDemand,
    NativeWorkflowPlan,
    NativeWorkflowStep,
    NativeWorkloadPlan,
)
from worldloom.cli import app
from worldloom.corpus import write_json
from worldloom.evalrun.qualification import QualificationPolicy
from worldloom.providers import digest

runner = CliRunner()


@dataclass(frozen=True)
class ScenarioProject:
    source: Path
    demand: Path
    plan: Path
    package: Path

    @property
    def arguments(self) -> list[str]:
        return ["native-evals", "scenarios", str(self.source), "--demand", str(self.demand), "--plan", str(self.plan),
            "--train-families", "3", "--holdout-families", "3", "--out", str(self.package)]


@pytest.fixture(scope="module")
def project(tmp_path_factory: pytest.TempPathFactory) -> ScenarioProject:
    pytest.importorskip("docx")
    root = tmp_path_factory.mktemp("native-capability-cli")
    source = RetailWorld(seed=8128).build().export(root / "source")
    demand, plan = root / "demand.json", root / "plan.json"
    write_json(demand, NativeScenarioDemand(episodes=6, batch_id="cli-native-cases").model_dump(mode="json"))
    write_json(plan, NativeWorkloadPlan(use_case_id="cli-native", objective="Read the business case evidence.",
        formats=("docx",), operations=("read",), max_tasks=6, discovery_scope="artifact").model_dump(mode="json"))
    result = ScenarioProject(source, demand, plan, root / "packages")
    built = runner.invoke(app, result.arguments)
    assert built.exit_code == 0, built.output
    report = json.loads(built.output)
    assert len(report["scenario_episodes"]) == 6
    assert report["split_audit"]["isolated"]
    return result


def _command(tmp_path: Path) -> tuple[str, Path]:
    script, log = tmp_path / "empty native target.py", tmp_path / "executions.jsonl"
    script.write_text(('''import json, sys
from pathlib import Path
request = json.load(sys.stdin)
task = request["task"]
root = Path(request["input_root"])
assert "expected" not in task and "assertions" not in task
assert not (root / "private").exists()
assert all((root / item["path"]).is_file() for item in task["inputs"])
with Path(LOG_PATH).open("a") as stream:
    stream.write(json.dumps({"id": task["id"], "execution_id": task["execution_id"]}) + "\\n")
print(json.dumps({"schema": "worldloom.native-harness-response/v1", "task_id": task["id"],
    "execution_id": task["execution_id"], "submission": {"answers": [], "files": []}}))
''').replace("LOG_PATH", repr(str(log))), encoding="utf-8")
    return shlex.join((sys.executable, str(script))), log


def test_scenarios_cli_preserves_roles_and_exact_resume(project: ScenarioProject) -> None:
    training = NativeBenchmark.load(project.package / "training")
    heldout = NativeBenchmark.load(project.package / "heldout")
    assert training.split_role == "training" and heldout.split_role == "heldout"
    assert len(training.world.facts) > len(RetailWorld(seed=8128).build().facts)
    assert {path.name for path in project.package.iterdir()} == {"training", "heldout", "partition.json"}
    resumed = runner.invoke(app, [*project.arguments, "--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.output)["training_digest"] == training.digest
    assert json.loads(resumed.output)["heldout_digest"] == heldout.digest


def test_inspect_and_improve_enforce_explicit_requirements_before_target_calls(
    project: ScenarioProject, tmp_path: Path,
) -> None:
    required = tmp_path / "requirements.json"
    write_json(required, BenchmarkRequirements(cells=(CoverageRequirement(
        name="four-read-units", operation="read", min_independent_units=4),)).model_dump(mode="json"))
    inspected = runner.invoke(app, ["native-evals", "inspect", str(project.package / "training"),
        "--requirements", str(required)])
    assert inspected.exit_code == 0, inspected.output
    report = json.loads(inspected.output)
    assert not report["coverage_complete"]
    cell = next(cell for cell in report["required_coverage"] if cell["name"] == "four-read-units")
    assert cell["independent_units"] == 3 and not cell["satisfied"]
    policy = tmp_path / "policy.json"
    write_json(policy, QualificationPolicy(trials=1, min_units=2).model_dump(mode="json"))
    command, log = _command(tmp_path)
    improved = runner.invoke(app, ["native-evals", "improve", str(project.package / "training"),
        str(project.package / "heldout"), "--agent-pack", "agent:baseline", "--command", command,
        "--proposer-command", command, "--source-origin", "cli/company", "--qualification-policy", str(policy),
        "--requirements", str(required), "--out", str(tmp_path / "study")])
    assert improved.exit_code != 0, improved.output
    assert "requires 4 independent units" in " ".join(improved.output.split())
    assert not log.exists() and not (tmp_path / "study").exists()


def test_workflow_cli_qualifies_then_observes_real_failure_blocking_and_resume(
    project: ScenarioProject, tmp_path: Path,
) -> None:
    package = project.package / "training"
    benchmark = NativeBenchmark.load(package)
    tasks = benchmark.workload.tasks
    plan = NativeWorkflowPlan(id="cli-authored-flow", benchmark_digest=benchmark.digest, steps=(
        NativeWorkflowStep(id="read", task_id=tasks[0].id),
        NativeWorkflowStep(id="dependent", task_id=tasks[1].id, depends_on=("read",)),
        NativeWorkflowStep(id="independent", task_id=tasks[2].id)))
    path = tmp_path / "workflow.json"
    write_json(path, plan.model_dump(mode="json"))
    qualified = runner.invoke(app, ["native-evals", "workflow-qualify", str(package), "--plan", str(path)])
    assert qualified.exit_code == 0, qualified.output
    assert json.loads(qualified.output)["passed"]
    command, log = _command(tmp_path)
    args = ["native-evals", "workflow-run", str(package), "--plan", str(path), "--command", command,
        "--out", str(tmp_path / "workflow-run")]
    result = runner.invoke(app, args)
    assert result.exit_code == 1, result.output
    report = json.loads(result.output)
    assert report["total"] == 3 and report["blocked_count"] == 1 and report["harness_failures"] == 0
    assert report["observation"] == "runner_scheduled_calls_and_staged_bytes"
    before = log.read_bytes()
    assert len(before.splitlines()) == 2
    resumed = runner.invoke(app, [*args, "--resume"])
    assert resumed.exit_code == 1, resumed.output
    assert json.loads(resumed.output) == report and log.read_bytes() == before


def test_cli_diagnosis_and_evolution_regrade_training_and_refuse_rehashed_strategy(
    project: ScenarioProject, tmp_path: Path,
) -> None:
    package = project.package / "training"
    command, _ = _command(tmp_path)
    run = tmp_path / "training-run"
    measured = runner.invoke(app, ["native-evals", "run", str(package), "--command", command, "--out", str(run)])
    assert measured.exit_code == 1, measured.output
    policy, curriculum = tmp_path / "policy.json", tmp_path / "curriculum.json"
    write_json(policy, QualificationPolicy(trials=1, min_units=2).model_dump(mode="json"))
    args = ["native-evals", "diagnose", str(package), str(run), "--source-origin", "cli/company",
        "--qualification-policy", str(policy), "--ablation", "without_failures", "--out", str(curriculum)]
    diagnosed = runner.invoke(app, args)
    assert diagnosed.exit_code == 0, diagnosed.output
    receipt = NativeCurriculum.model_validate(json.loads(curriculum.read_text()))
    assert receipt.observations[0].failures == 6
    evolved_path = tmp_path / "next-training"
    evolution_args = ["native-evals", "evolve", str(package), str(run), "--curriculum", str(curriculum),
        "--out", str(evolved_path)]
    evolved = runner.invoke(app, evolution_args)
    assert evolved.exit_code == 0, evolved.output
    report = json.loads(evolved.output)
    assert report["qualification"] == "new_study_with_fresh_heldout_required"
    next_benchmark = NativeBenchmark.load(evolved_path)
    assert next_benchmark.split_role == "training" and next_benchmark.digest != NativeBenchmark.load(package).digest
    assert next_benchmark.source_digest != receipt.source_digest
    resumed = runner.invoke(app, [*evolution_args, "--resume"])
    assert resumed.exit_code == 0, resumed.output
    assert json.loads(resumed.output)["benchmark_digest"] == next_benchmark.digest
    document = receipt.model_dump(mode="json")
    document["next_plan"]["max_tasks"] = 1
    document["digest"] = digest({key: value for key, value in document.items() if key != "digest"})
    write_json(curriculum, document)
    rejected = runner.invoke(app, [*evolution_args, "--resume"])
    assert rejected.exit_code != 0 and "independently verified training feedback" in rejected.output
    protected = runner.invoke(app, ["native-evals", "diagnose", str(project.package / "heldout"), str(run),
        "--source-origin", "cli/company", "--out", str(tmp_path / "forbidden.json")])
    assert protected.exit_code != 0 and "split_role='training'" in protected.output
    assert not (tmp_path / "forbidden.json").exists()


def test_build_role_option_and_sdk_exports_are_public() -> None:
    import worldloom.benchmarks as sdk

    assert all(hasattr(sdk, name) for name in sdk.__all__)
    help_result = runner.invoke(app, ["native-evals", "build", "--help"])
    assert help_result.exit_code == 0, help_result.output
    assert "--split-role" in help_result.output
    refused = runner.invoke(app, ["native-evals", "build", "source", "scale", "--plan", "plan.json",
        "--out", "output", "--split-role", "development"])
    assert refused.exit_code == 2 and "Invalid value" in refused.output
