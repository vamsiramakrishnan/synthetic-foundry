"""File exchange for native discovery tasks and independent byte grading."""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Annotated

import typer
from pydantic import Field

from .models import Model
from .native_tasks import NativeGrade, NativeSubmission

if TYPE_CHECKING:
    from .native_query_planning import NativeWorkload

native_evals_app = typer.Typer(no_args_is_help=True, help="Build discovery tasks over native files and independently grade replies.")
_PUBLIC_WORKLOAD_SCHEMA = "worldloom.native-workload.public/v1"


class NativeTaskReply(Model):
    task_id: str = Field(min_length=1)
    submission: NativeSubmission


class NativeWorkloadReplies(Model):
    replies: tuple[NativeTaskReply, ...]


class NativeWorkloadGrade(Model):
    passed: bool
    grades: dict[str, NativeGrade]


def _reject(error: Exception) -> None:
    from rich.markup import escape

    from .cli import _refuse

    _refuse("native_evals_rejected", escape(str(error)))


def _load_package(directory: Path) -> tuple[NativeWorkload, dict[str, bytes]]:
    from .native_artifacts import inspect_artifact
    from .native_query_planning import NativeWorkload
    from .native_tasks import MAX_FILE_BYTES, public_contract
    from .quality_cli import _document

    workload = NativeWorkload.model_validate(_document(directory / "oracle.json"))
    if not workload.tasks or len({task.id for task in workload.tasks}) != len(workload.tasks):
        raise ValueError("native workload requires distinct, nonempty tasks")
    expected_public = {"schema": _PUBLIC_WORKLOAD_SCHEMA,
                       "tasks": [public_contract(task) for task in workload.tasks]}
    if _document(directory / "public-tasks.json") != expected_public:
        raise ValueError("public native tasks differ from the evaluator's task contract")
    root = directory.resolve()
    inputs: dict[str, bytes] = {}
    identities: dict[str, tuple[str, str, str]] = {}
    for task in workload.tasks:
        for item in task.inputs:
            identity = (item.format, item.path, item.sha256)
            if item.artifact_id in identities and identities[item.artifact_id] != identity:
                raise ValueError("input identity differs between tasks")
            if item.artifact_id in inputs:
                continue
            path = (directory / item.path).resolve()
            if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size > MAX_FILE_BYTES:
                raise ValueError(f"native input is missing, outside the package, or oversized: {item.artifact_id}")
            payload = path.read_bytes()
            if inspect_artifact(payload, item.format).sha256 != item.sha256:
                raise ValueError(f"native input checksum changed: {item.artifact_id}")
            identities[item.artifact_id] = identity
            inputs[item.artifact_id] = payload
    return workload, inputs


@native_evals_app.command("build")
def build_command(
    corpus_path: Annotated[str, typer.Argument(help="Original source company corpus.")],
    scale_directory: Annotated[Path, typer.Argument(help="Verified corpus-scale output containing native files.")],
    plan: Annotated[Path, typer.Option("--plan", help="NativeWorkloadPlan JSON: business objective, formats, operations and task budget.")],
    out: Annotated[Path, typer.Option("--out", "-o", help="New exchange directory; oracle.json stays evaluator-private.")],
) -> None:
    """Compile and reference-qualify tasks; export public prompts and byte-bound inputs."""
    from tempfile import TemporaryDirectory

    from .cli import _load
    from .corpus import write_json
    from .corpus_scale import verify_corpus_scale
    from .ids import content_key
    from .native_corpus import NativeCorpusResult
    from .native_query_planning import NativeWorkloadPlan, plan_native_workload
    from .native_tasks import public_contract
    from .quality_cli import _document, _emit

    try:
        if out.exists():
            raise ValueError("native exchange destination already exists")
        world = _load(corpus_path)
        manifest = verify_corpus_scale(world, scale_directory)
        files = {item.sha256: item.path for item in manifest.files if item.kind == "native"}
        rendered = {item.artifact_id: NativeCorpusResult(
            payload=(scale_directory / files[item.sha256]).read_bytes(), manifest=item) for item in manifest.native}
        workload = plan_native_workload(world, rendered, NativeWorkloadPlan.model_validate(_document(plan)))
        if not workload.tasks:
            raise ValueError("native workload has no executable tasks; inspect source scope and discovery coverage")
        paths = {key: "inputs/" + content_key("native-evals/input/v1", key) + "." + value.manifest.format
                 for key, value in rendered.items()}
        tasks = tuple(task.model_copy(update={"inputs": tuple(item.model_copy(update={"path": paths[item.artifact_id]})
            for item in task.inputs)}) for task in workload.tasks)
        workload = workload.model_copy(update={"tasks": tasks})
        used = {item.artifact_id for task in tasks for item in task.inputs}
        out.parent.mkdir(parents=True, exist_ok=True)
        with TemporaryDirectory(prefix=".native-evals-", dir=out.parent) as temporary:
            stage = Path(temporary) / "package"
            (stage / "inputs").mkdir(parents=True)
            for artifact_id in sorted(used):
                (stage / paths[artifact_id]).write_bytes(rendered[artifact_id].payload)
            write_json(stage / "oracle.json", workload.model_dump(mode="json"))
            write_json(stage / "public-tasks.json", {"schema": _PUBLIC_WORKLOAD_SCHEMA,
                "tasks": [public_contract(task) for task in tasks]})
            stage.rename(out)
    except (ValueError, OSError, KeyError) as error:
        _reject(error)
        return
    _emit({"tasks": len(workload.tasks), "reference_qualified": workload.reference_qualified,
        "operation_counts": workload.operation_counts, "capability_coverage": workload.capability_coverage,
        "findings": [finding.model_dump(mode="json") for finding in workload.findings],
        "public_tasks": str(out / "public-tasks.json"), "private_oracle": str(out / "oracle.json")})


@native_evals_app.command("qualify")
def qualify_command(
    directory: Annotated[Path, typer.Argument(help="Native workload exchange directory.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write independent qualification grades JSON.")] = None,
) -> None:
    """Construct reference replies and recheck satisfiability against actual input bytes."""
    from .native_reference import qualify_native_task
    from .quality_cli import _emit

    try:
        workload, inputs = _load_package(directory)
        grades = {task.id: qualify_native_task(task, inputs) for task in workload.tasks}
        report = NativeWorkloadGrade(passed=all(grade.passed for grade in grades.values()), grades=grades)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)
    if not report.passed:
        raise typer.Exit(1)


@native_evals_app.command("grade")
def grade_command(
    directory: Annotated[Path, typer.Argument(help="Evaluator's native workload exchange directory.")],
    replies: Annotated[Path, typer.Option("--replies", help="NativeWorkloadReplies JSON, including actual native output bytes as base64.")],
    out: Annotated[Path | None, typer.Option("--out", "-o", help="Write grades JSON.")] = None,
) -> None:
    """Require exact task coverage and inspect answers, citations, output types and preservation."""
    from .native_tasks import grade_native_task
    from .quality_cli import _document, _emit

    try:
        workload, inputs = _load_package(directory)
        submissions = NativeWorkloadReplies.model_validate(_document(replies)).replies
        by_id = {reply.task_id: reply.submission for reply in submissions}
        if len(by_id) != len(submissions) or set(by_id) != {task.id for task in workload.tasks}:
            raise ValueError("reply task ids must cover the workload exactly once")
        grades = {task.id: grade_native_task(task, inputs, by_id[task.id]) for task in workload.tasks}
        report = NativeWorkloadGrade(passed=all(grade.passed for grade in grades.values()), grades=grades)
    except (ValueError, OSError) as error:
        _reject(error)
        return
    _emit(report.model_dump(mode="json"), out)
    if not report.passed:
        raise typer.Exit(1)
