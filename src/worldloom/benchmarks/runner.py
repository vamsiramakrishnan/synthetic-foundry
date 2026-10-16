"""Run native benchmarks against trusted harnesses, preserving byte evidence.

Commands receive one public task and a temporary directory of its input files.
The private benchmark and run directories never appear in the protocol. This
is an information boundary, not an OS sandbox: commands inherit the caller's
filesystem permissions and environment. Use a container/remote adapter for an
untrusted target. Callable harnesses likewise run in the evaluator's process.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import signal
import subprocess
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import TemporaryDirectory, TemporaryFile
from time import monotonic
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pydantic import BaseModel, Field

from ..corpus import write_json
from ..evalrun.agents import fingerprint
from ..models import Model
from ..native_eval_bridge import native_grader_identity
from ..native_tasks import (
    MAX_FILE_BYTES,
    NativeGrade,
    NativeInput,
    NativeSubmission,
    NativeTask,
    grade_native_task,
    public_contract,
)
from ..providers import digest

if TYPE_CHECKING:
    from ..evalrun.agents import AgentUnderTest
    from .core import NativeBenchmark

REQUEST_SCHEMA = "worldloom.native-harness-request/v1"
RESPONSE_SCHEMA = "worldloom.native-harness-response/v1"
_RUN_SCHEMA = "worldloom.native-benchmark-run/v1"
_RECEIPT_SCHEMA = "worldloom.native-benchmark-receipt/v1"


def protocol_manifest() -> dict[str, Any]:
    """The versioned public command contract, usable without optional parsers."""
    return {"request_schema": REQUEST_SCHEMA, "response_schema": RESPONSE_SCHEMA,
        "transport": "one JSON object on stdin; one JSON object on stdout per task",
        "request": {"schema": REQUEST_SCHEMA, "task": "public_contract(task) plus opaque execution_id",
            "input_root": "temporary absolute directory; task.inputs[].path is relative to it",
            "agent": "optional target identity and AgentPolicy body when used for improvement"},
        "response": {"schema": RESPONSE_SCHEMA, "task_id": "echo task.id", "execution_id": "echo task.execution_id",
            "submission": NativeSubmission.model_json_schema()},
        "boundary": "trusted subprocess; only declared task inputs are staged; no OS sandbox",
        "resume": "exact configuration only; committed submissions are independently regraded; interrupted tasks may be reissued"}


class HarnessFailure(ValueError):
    """A target failed; its other tasks remain executable."""

    def __init__(self, code: str, detail: str = "") -> None:
        self.code = code
        self.detail = detail
        super().__init__(code + (": " + detail if detail else ""))


def _canonical(value: Any) -> Any:
    return json.loads(json.dumps(value, sort_keys=True, allow_nan=False))


def _file_digest(path: Path) -> str:
    with path.open("rb") as handle:
        return hashlib.file_digest(handle, "sha256").hexdigest()


class NativeHarness(Protocol):
    """An identity-pinned target over public requests and input bytes."""

    @property
    def identity(self) -> Mapping[str, Any]: ...

    def submit(self, request: dict[str, Any], inputs: Mapping[str, bytes], *,
               agent: AgentUnderTest | None = None) -> NativeSubmission: ...

    def __call__(self, agent: AgentUnderTest, request: dict[str, Any], inputs: Mapping[str, bytes]) -> NativeSubmission: ...


def _public_agent(agent: AgentUnderTest) -> dict[str, Any]:
    policy = getattr(agent, "policy", None)
    body = policy if isinstance(policy, BaseModel) else getattr(policy, "body", None)
    return {"name": agent.name, "identity": fingerprint(agent),
        "policy": body.model_dump(mode="json") if isinstance(body, BaseModel) else None}


@dataclass(frozen=True, init=False)
class CallableHarness:
    """Adapt an in-process target; the caller owns a complete stable identity.

    The callback receives no oracle. Its identity must cover implementation,
    model, policy and settings; Python closures cannot be fully fingerprinted.
    Improvement calls add ``request['agent']`` with target identity and policy.
    """

    callback: Callable[[dict[str, Any], Mapping[str, bytes]], NativeSubmission]
    _identity_json: str = field(repr=False)

    def __init__(self, callback: Callable[[dict[str, Any], Mapping[str, bytes]], NativeSubmission],
                 identity: Mapping[str, Any]) -> None:
        if not identity:
            raise ValueError("callable harness needs an explicit implementation identity")
        object.__setattr__(self, "callback", callback)
        object.__setattr__(self, "_identity_json", json.dumps(dict(identity), sort_keys=True, allow_nan=False))

    @property
    def identity(self) -> Mapping[str, Any]:
        return json.loads(self._identity_json)

    def submit(self, request: dict[str, Any], inputs: Mapping[str, bytes], *,
               agent: AgentUnderTest | None = None) -> NativeSubmission:
        public = _canonical(request)
        if agent is not None:
            public["agent"] = _public_agent(agent)
        return NativeSubmission.model_validate(self.callback(public, dict(inputs)))

    def __call__(self, agent: AgentUnderTest, request: dict[str, Any], inputs: Mapping[str, bytes]) -> NativeSubmission:
        try:
            return self.submit(request, inputs, agent=agent)
        except Exception:
            return NativeSubmission()


@dataclass(frozen=True)
class CommandHarness:
    """A JSON stdin/stdout adapter also usable as ``native_runner(submit=...)``.

    File arguments and the executable are automatically pinned by SHA-256.
    Add imported modules, configuration and lockfiles to ``identity_files``;
    remote model/deployment settings belong in ``identity_extra``. The adapter
    cannot discover transitive dependencies or remote deployment mutations.

    Captured output is checked during execution and read with a fixed bound;
    temporary stream files avoid pipe deadlocks and unbounded memory capture.
    A single polling interval may exceed the disk limit before termination.
    """

    argv: tuple[str, ...]
    timeout_seconds: float = 120
    max_output_bytes: int = 16 * 1024 * 1024
    identity_files: tuple[Path, ...] = ()
    identity_extra: Mapping[str, Any] = field(default_factory=dict)
    environment: Mapping[str, str] = field(default_factory=dict)
    _argv: tuple[str, ...] = field(init=False, repr=False)
    _files: tuple[Path, ...] = field(init=False, repr=False)
    _environment: Mapping[str, str] = field(init=False, repr=False)
    _initial_identity: Mapping[str, Any] = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if not self.argv or any(not isinstance(item, str) or not item or "\0" in item for item in self.argv):
            raise ValueError("harness argv requires nonempty strings without NUL bytes")
        if not math.isfinite(self.timeout_seconds) or self.timeout_seconds <= 0:
            raise ValueError("harness timeout must be finite and positive")
        if isinstance(self.max_output_bytes, bool) or not isinstance(self.max_output_bytes, int) or self.max_output_bytes < 1:
            raise ValueError("harness output bound must be positive")
        environment = {**os.environ, **self.environment}
        if any(not isinstance(key, str) or not isinstance(value, str) or "\0" in key or "\0" in value
               for key, value in environment.items()):
            raise ValueError("harness environment requires string keys and values without NUL bytes")
        executable = shutil.which(self.argv[0], path=environment.get("PATH"))
        if executable is None:
            raise ValueError("harness executable was not found: " + self.argv[0])
        # Preserve the selected executable's entry path. Resolving a venv's
        # python symlink before launch silently selects the base interpreter,
        # discarding its installed dependencies after cwd changes. Hash the
        # entry path's bytes (following its current target) for identity, but
        # launch that absolute entry path, not its resolved binary target.
        resolved = [str(Path(executable).absolute())]
        files = [Path(resolved[0])]
        # Resolve arguments before moving the child into its public workspace;
        # python ./adapter.py must continue to work after cwd changes.
        for argument in self.argv[1:]:
            path = Path(argument)
            try:
                is_file = path.is_file()
            except OSError:
                is_file = False
            if is_file:
                path = path.resolve()
                files.append(path)
                resolved.append(str(path))
            else:
                resolved.append(argument)
        files.extend(path.resolve() for path in self.identity_files)
        if any(not path.is_file() for path in files):
            raise ValueError("harness identity file is missing")
        object.__setattr__(self, "_argv", tuple(resolved))
        object.__setattr__(self, "_files", tuple(sorted(set(files))))
        object.__setattr__(self, "_environment", environment)
        object.__setattr__(self, "identity_extra", _canonical(self.identity_extra))
        object.__setattr__(self, "_initial_identity", self._current_identity())

    def _current_identity(self) -> dict[str, Any]:
        return {"kind": "native-command", "request_schema": REQUEST_SCHEMA, "response_schema": RESPONSE_SCHEMA,
            "argv": list(self._argv), "files": {str(path): _file_digest(path) for path in self._files},
            "timeout_seconds": self.timeout_seconds, "max_output_bytes": self.max_output_bytes,
            "environment_digest": digest(dict(self._environment)), "extra": _canonical(self.identity_extra),
            "adapter_sha256": _file_digest(Path(__file__))}

    @property
    def identity(self) -> Mapping[str, Any]:
        current = self._current_identity()
        if current != self._initial_identity:
            raise ValueError("harness command identity changed; create a new run")
        return _canonical(current)

    def submit(self, request: dict[str, Any], inputs: Mapping[str, bytes], *,
               agent: AgentUnderTest | None = None) -> NativeSubmission:
        _ = self.identity
        task = _canonical(request)
        if not isinstance(task.get("id"), str) or not isinstance(task.get("execution_id"), str):
            raise ValueError("native command requires task and execution identities")
        with TemporaryDirectory(prefix="worldloom-native-target-") as temporary:
            root = Path(temporary)
            (root / "inputs").mkdir()
            seen: set[str] = set()
            for raw in task.get("inputs", []):
                item = NativeInput.model_validate(raw)
                if item.artifact_id in seen:
                    raise ValueError("native command input identities must be distinct")
                seen.add(item.artifact_id)
                data = inputs[item.artifact_id]
                if len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != item.sha256:
                    raise ValueError("native command input checksum changed: " + item.artifact_id)
                relative = "inputs/" + digest([item.artifact_id, item.sha256]) + "." + item.format
                (root / relative).write_bytes(data)
                raw["path"] = relative
            if seen != set(inputs):
                raise ValueError("native command inputs must match its public task exactly")
            payload: dict[str, Any] = {"schema": REQUEST_SCHEMA, "task": task, "input_root": str(root)}
            if agent is not None:
                # A policy is part of the target, never private evaluation data.
                payload["agent"] = _public_agent(agent)
            document = self._exchange(payload, root)
        if (not isinstance(document, dict) or set(document) != {"schema", "task_id", "execution_id", "submission"}
                or document.get("schema") != RESPONSE_SCHEMA or document.get("task_id") != task["id"]
                or document.get("execution_id") != task["execution_id"]):
            raise HarnessFailure("response_identity_invalid", "reply must echo the schema, task_id and execution_id")
        try:
            return NativeSubmission.model_validate(document["submission"])
        except ValueError as error:
            raise HarnessFailure("submission_schema_invalid", "reply does not match NativeSubmission") from error

    def __call__(self, agent: AgentUnderTest, request: dict[str, Any], inputs: Mapping[str, bytes]) -> NativeSubmission:
        """Existing improvement seam; malformed target outcomes fail byte grading."""
        try:
            return self.submit(request, inputs, agent=agent)
        except HarnessFailure:
            return NativeSubmission()

    def _exchange(self, payload: dict[str, Any], directory: Path) -> Any:
        with TemporaryFile() as stdin, TemporaryFile() as stdout, TemporaryFile() as stderr:
            stdin.write(json.dumps(payload, sort_keys=True, allow_nan=False).encode("utf-8"))
            stdin.seek(0)
            try:
                process = subprocess.Popen(self._argv, cwd=directory, env=self._environment,
                    stdin=stdin, stdout=stdout, stderr=stderr, shell=False, start_new_session=os.name != "nt")
            except OSError as error:
                raise HarnessFailure("command_start_failed", type(error).__name__) from error
            deadline = monotonic() + self.timeout_seconds
            failure = ""
            try:
                while True:
                    if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > self.max_output_bytes:
                        failure = "command_output_limit"
                        break
                    remaining = deadline - monotonic()
                    if remaining <= 0:
                        failure = "command_timeout"
                        break
                    try:
                        process.wait(timeout=min(remaining, 0.05))
                        break
                    except subprocess.TimeoutExpired:
                        continue
            finally:
                # Reap the direct child on interruption too. A POSIX process
                # group also covers helpers which inherited these stream files.
                if os.name != "nt":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.poll() is None:
                    process.kill()
                process.wait()
            if os.fstat(stdout.fileno()).st_size + os.fstat(stderr.fileno()).st_size > self.max_output_bytes:
                failure = "command_output_limit"
            if failure:
                raise HarnessFailure(failure)
            stderr.seek(max(0, os.fstat(stderr.fileno()).st_size - 4096))
            diagnostic = stderr.read(4096).decode("utf-8", errors="replace")
            if process.returncode != 0:
                raise HarnessFailure("command_exit_nonzero", f"exit {process.returncode}; {diagnostic}")
            stdout.seek(0)
            try:
                return json.loads(stdout.read(self.max_output_bytes + 1))
            except (ValueError, UnicodeDecodeError) as error:
                raise HarnessFailure("response_json_invalid", diagnostic) from error


class BenchmarkTrial(Model):
    task_id: str
    repeat: int = Field(ge=1)
    execution_id: str
    operation: str
    status: Literal["graded", "harness_failed"]
    grade: NativeGrade
    submission_digest: str
    failure_code: str | None = None
    failure_detail: str | None = None


class BenchmarkRun(Model):
    schema_version: Literal["worldloom.native-benchmark-run/v1"] = "worldloom.native-benchmark-run/v1"
    run_id: str
    benchmark_digest: str
    harness_identity: dict[str, Any]
    repeats: int
    total: int
    passed_count: int
    failed_count: int
    harness_failures: int
    passed: bool
    trials: tuple[BenchmarkTrial, ...]


def _atomic_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".pending")
    if path.is_symlink() or temporary.is_symlink():
        raise ValueError("benchmark receipt paths may not be symlinks")
    write_json(temporary, document)
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ValueError("benchmark receipt is missing or a symlink: " + path.name)
    value = json.loads(path.read_bytes())
    if not isinstance(value, dict):
        raise ValueError("benchmark receipt must be an object")
    return value


def _seal(document: dict[str, Any]) -> dict[str, Any]:
    return {**document, "digest": digest(document)}


def _unseal(document: dict[str, Any]) -> dict[str, Any]:
    content = {key: value for key, value in document.items() if key != "digest"}
    if document.get("digest") != digest(content):
        raise ValueError("benchmark receipt checksum changed")
    return content


def _trial(task: NativeTask, inputs: Mapping[str, bytes], submission: NativeSubmission, *, repeat: int,
           execution_id: str, failure_code: str | None, failure_detail: str | None) -> BenchmarkTrial:
    grade = grade_native_task(task, inputs, submission)
    if failure_code is not None:
        grade = NativeGrade(passed=False, findings=(failure_code, *grade.findings), metrics=grade.metrics)
    return BenchmarkTrial(task_id=task.id, repeat=repeat, execution_id=execution_id, operation=task.operation,
        status="harness_failed" if failure_code else "graded", grade=grade,
        submission_digest=digest(submission.model_dump(mode="json")), failure_code=failure_code, failure_detail=failure_detail)


def _pins(task: NativeTask, run_id: str, repeat: int) -> dict[str, Any]:
    execution_id = digest([run_id, task.id, repeat])
    return {"schema": _RECEIPT_SCHEMA, "run_id": run_id, "task_id": task.id, "repeat": repeat,
        "execution_id": execution_id, "request_digest": digest({**public_contract(task), "execution_id": execution_id}),
        "task_digest": digest(task.model_dump(mode="json"))}


def run_benchmark(benchmark: NativeBenchmark, harness: NativeHarness, *, directory: Path,
                  repeats: int = 1, resume: bool = False) -> BenchmarkRun:
    """Independently grade each actual reply; resume only an exact sealed run.

    Completed receipts include submissions, independently checked again before
    reuse. Interruptions leave completed trials intact. A trial interrupted
    before its receipt is committed can be reissued with the same execution
    ID, so targets performing external writes must use that idempotency key.
    """
    if isinstance(repeats, bool) or not isinstance(repeats, int) or repeats < 1:
        raise ValueError("benchmark repeats must be a positive integer")
    # A byte checksum alone cannot establish that its authored source remains
    # public or that task assertions still agree with canonical world facts.
    benchmark.validate()
    tasks = benchmark.workload.tasks
    if not tasks or len({task.id for task in tasks}) != len(tasks):
        raise ValueError("benchmark requires distinct, nonempty tasks")
    inputs = dict(benchmark.inputs)
    input_identities: dict[str, tuple[str, str]] = {}
    for task in tasks:
        for item in task.inputs:
            data = inputs.get(item.artifact_id)
            if data is None or len(data) > MAX_FILE_BYTES or hashlib.sha256(data).hexdigest() != item.sha256:
                raise ValueError("benchmark input checksum changed: " + item.artifact_id)
            identity = (item.format, item.sha256)
            if item.artifact_id in input_identities and input_identities[item.artifact_id] != identity:
                raise ValueError("benchmark inputs have inconsistent identities")
            input_identities[item.artifact_id] = identity
    harness_identity = _canonical(harness.identity)
    if not harness_identity:
        raise ValueError("benchmark harness needs an explicit identity")
    configuration = {"schema": _RUN_SCHEMA, "benchmark_digest": benchmark.digest,
        "workload_digest": digest(benchmark.workload.model_dump(mode="json")),
        "inputs": _canonical(input_identities), "harness": harness_identity, "repeats": repeats,
        "grader": native_grader_identity(), "runner_sha256": _file_digest(Path(__file__))}
    directory = Path(directory).absolute()
    if directory.is_symlink():
        raise ValueError("benchmark run directory may not be a symlink")
    run_id = digest([configuration, str(directory.resolve())])
    manifest = _seal({**configuration, "run_id": run_id})
    directory.parent.mkdir(parents=True, exist_ok=True)
    lock = directory.parent / ("." + directory.name + ".lock")
    try:
        descriptor = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError as error:
        raise ValueError("benchmark run is locked by another invocation; verify no process is active before removing the lock") from error
    os.close(descriptor)
    try:
        if directory.exists():
            if not resume:
                raise ValueError("benchmark run exists; use resume for the exact same configuration")
            if _read_json(directory / "manifest.json") != manifest:
                raise ValueError("benchmark run configuration changed; create a new run")
        else:
            if resume:
                raise ValueError("cannot resume a missing benchmark run")
            directory.mkdir()
            _atomic_json(directory / "manifest.json", manifest)
        receipts = directory / "receipts"
        if receipts.is_symlink():
            raise ValueError("benchmark receipt directory may not be a symlink")
        receipts.mkdir(exist_ok=True)
        expected = {digest([task.id, repeat]) + ".json" for task in tasks for repeat in range(1, repeats + 1)}
        if any(path.name not in expected and path.name.removesuffix(".pending") not in expected for path in receipts.iterdir()):
            raise ValueError("benchmark contains unknown trial receipts")
        if (directory / "run.json").exists() and not all((receipts / name).is_file() for name in sorted(expected)):
            raise ValueError("completed benchmark is missing trial receipts")
        # Validate *all* completed receipts before spending another target call.
        # A later corrupt receipt must not trigger earlier missing-task retries.
        cached: dict[tuple[str, int], BenchmarkTrial] = {}
        for task in sorted(tasks, key=lambda value: value.id):
            task_inputs = {item.artifact_id: inputs[item.artifact_id] for item in task.inputs}
            for repeat in range(1, repeats + 1):
                path = receipts / (digest([task.id, repeat]) + ".json")
                if not (path.exists() or path.is_symlink()):
                    continue
                saved = _unseal(_read_json(path))
                pins = _pins(task, run_id, repeat)
                if saved.get("pins") != pins or set(saved) != {"pins", "submission", "trial"}:
                    raise ValueError("benchmark trial receipt differs from its sealed task")
                submission = NativeSubmission.model_validate(saved["submission"])
                prior = BenchmarkTrial.model_validate(saved["trial"])
                trial = _trial(task, task_inputs, submission, repeat=repeat, execution_id=pins["execution_id"],
                    failure_code=prior.failure_code, failure_detail=prior.failure_detail)
                if saved["trial"] != trial.model_dump(mode="json"):
                    raise ValueError("benchmark saved trial disagrees with independent byte grading")
                cached[task.id, repeat] = trial
        trials = []
        for task in sorted(tasks, key=lambda value: value.id):
            public = public_contract(task)
            task_inputs = {item.artifact_id: inputs[item.artifact_id] for item in task.inputs}
            for repeat in range(1, repeats + 1):
                if _canonical(harness.identity) != harness_identity:
                    raise ValueError("benchmark harness identity changed during the run")
                if (task.id, repeat) in cached:
                    trials.append(cached[task.id, repeat])
                    continue
                execution_id = digest([run_id, task.id, repeat])
                request = {**public, "execution_id": execution_id}
                pins = _pins(task, run_id, repeat)
                path = receipts / (digest([task.id, repeat]) + ".json")
                failure_code: str | None = None
                failure_detail: str | None = None
                try:
                    submission = NativeSubmission.model_validate(harness.submit(_canonical(request), dict(task_inputs)))
                except HarnessFailure as error:
                    submission = NativeSubmission()
                    failure_code, failure_detail = error.code, error.detail
                except Exception as error:
                    # Only target invocation is caught. Broken input parsing,
                    # grader or persistence must refuse the run, not become
                    # a target failure that improves its apparent coverage.
                    submission = NativeSubmission()
                    failure_code, failure_detail = "harness_exception", type(error).__name__
                if _canonical(harness.identity) != harness_identity:
                    raise ValueError("benchmark harness identity changed during the run")
                trial = _trial(task, task_inputs, submission, repeat=repeat, execution_id=execution_id,
                    failure_code=failure_code, failure_detail=failure_detail)
                document = {"pins": pins, "submission": submission.model_dump(mode="json"), "trial": trial.model_dump(mode="json")}
                _atomic_json(path, _seal(document))
                trials.append(trial)
        passed_count = sum(trial.grade.passed for trial in trials)
        report = BenchmarkRun(run_id=run_id, benchmark_digest=benchmark.digest, harness_identity=harness_identity,
            repeats=repeats, total=len(trials), passed_count=passed_count, failed_count=len(trials) - passed_count,
            harness_failures=sum(trial.status == "harness_failed" for trial in trials),
            passed=passed_count == len(trials), trials=tuple(trials))
        summary = report.model_dump(mode="json")
        if (directory / "run.json").exists() and _read_json(directory / "run.json") != summary:
            raise ValueError("benchmark saved aggregate differs from its trial receipts")
        _atomic_json(directory / "run.json", summary)
        return report
    finally:
        lock.unlink()


__all__ = ["REQUEST_SCHEMA", "RESPONSE_SCHEMA", "BenchmarkRun", "BenchmarkTrial", "CallableHarness",
           "CommandHarness", "HarnessFailure", "NativeHarness", "protocol_manifest", "run_benchmark"]
