"""Executable native-file contracts with byte-bound inputs and content grading.

Preservation compares every extracted semantic unit, including formulas and notes.
It is deliberately not a claim that visual layout is identical.
"""
from __future__ import annotations

import base64
import binascii
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation, localcontext
from pathlib import PurePosixPath
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Model

MAX_FILE_BYTES = 64 * 1024 * 1024


class NativeCitation(Model):
    artifact_id: str = Field(min_length=1)
    locator: str = Field(min_length=1)


class NativeInput(Model):
    artifact_id: str = Field(min_length=1)
    format: Literal["docx", "pptx", "xlsx", "pdf"]
    path: str = Field(min_length=1)
    sha256: str = Field(default="", pattern=r"^(?:[a-f0-9]{64})?$")

    @model_validator(mode="after")
    def safe_path(self) -> NativeInput:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "\\" in self.path:
            raise ValueError("native input path must remain inside the corpus")
        return self


class NativeCalculation(Model):
    operation: Literal["sum", "difference", "ratio"]
    operands: tuple[NativeCitation, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def arity(self) -> NativeCalculation:
        if self.operation != "sum" and len(self.operands) != 2:
            raise ValueError("difference and ratio require two operands")
        return self


class NativeAssertion(Model):
    id: str = Field(min_length=1)
    target: NativeCitation | None = None
    calculation: NativeCalculation | None = None
    expected: str | None = None
    expected_type: Literal["formula", "string", "number", "boolean"] | None = None
    tolerance: Decimal = Field(default=Decimal(0), ge=0)

    @model_validator(mode="after")
    def one_source(self) -> NativeAssertion:
        if (self.target is None) == (self.calculation is None):
            raise ValueError("assertion requires exactly one target or calculation")
        if not self.tolerance.is_finite():
            raise ValueError("tolerance must be finite")
        return self


class NativeOutput(Model):
    artifact_id: str = Field(min_length=1)
    format: Literal["docx", "pptx", "xlsx", "pdf"]
    source_artifact_id: str | None = None
    assertions: tuple[NativeAssertion, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def concrete_targets(self) -> NativeOutput:
        for assertion in self.assertions:
            if assertion.target is None or assertion.target.artifact_id != self.artifact_id or assertion.expected is None:
                raise ValueError("output assertions require an explicit output locator and expected content")
        if any(a.expected_type is not None for a in self.assertions) and self.format != "xlsx":
            raise ValueError("expected_type requires an XLSX output")
        if len({a.id for a in self.assertions}) != len(self.assertions):
            raise ValueError("output assertion ids must be unique")
        if len({a.target.locator for a in self.assertions if a.target}) != len(self.assertions):
            raise ValueError("output locators must be unique")
        return self


class NativeTask(Model):
    id: str = Field(min_length=1)
    prompt: str = Field(default="", max_length=16000)
    use_case_id: str = ""
    operation: Literal["read", "analyze", "update", "create"]
    inputs: tuple[NativeInput, ...] = ()
    assertions: tuple[NativeAssertion, ...] = ()
    output: NativeOutput | None = None

    @model_validator(mode="after")
    def constrained(self) -> NativeTask:
        ids = {item.artifact_id for item in self.inputs}
        if len(ids) != len(self.inputs):
            raise ValueError("input artifact ids must be unique")
        if len({a.id for a in self.assertions}) != len(self.assertions):
            raise ValueError("answer assertion ids must be unique")
        if self.operation in {"read", "analyze"}:
            if not self.inputs or not self.assertions or self.output is not None:
                raise ValueError("read and analyze require inputs and assertions without output")
        elif self.output is None:
            raise ValueError("update and create require output assertions")
        if self.operation == "analyze" and not any(a.calculation for a in self.assertions):
            raise ValueError("analysis requires a computed assertion")
        if self.output is not None:
            if self.output.artifact_id in ids:
                raise ValueError("output must have a distinct artifact id")
            if self.operation == "update":
                source = next((i for i in self.inputs if i.artifact_id == self.output.source_artifact_id), None)
                if source is None or source.format != self.output.format:
                    raise ValueError("update requires an input of the same format")
                if source.format == "pdf":
                    raise ValueError("PDF update preservation is not supported")
            elif self.output.source_artifact_id is not None:
                raise ValueError("only updates declare a source artifact")
        for assertion in self.assertions:
            refs = assertion.calculation.operands if assertion.calculation else (assertion.target,)
            if any(ref is None or ref.artifact_id not in ids for ref in refs):
                raise ValueError("answer assertions must reference declared inputs")
        return self


class NativeAnswer(Model):
    assertion_id: str
    value: str
    citations: tuple[NativeCitation, ...] = Field(min_length=1)


class NativeFile(Model):
    artifact_id: str
    format: Literal["docx", "pptx", "xlsx", "pdf"]
    content_base64: str = Field(max_length=((MAX_FILE_BYTES + 2) // 3) * 4)
    source_sha256: str | None = None


class NativeSubmission(Model):
    answers: tuple[NativeAnswer, ...] = ()
    files: tuple[NativeFile, ...] = ()


class NativeGrade(Model):
    passed: bool
    findings: tuple[str, ...]
    metrics: dict[str, int | str]


def _number(value: str) -> Decimal:
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError("numeric evidence must be an explicit decimal") from exc
    if not result.is_finite():
        raise ValueError("numeric evidence must be finite")
    return result


def _equal(actual: str, expected: str, tolerance: Decimal, *, numeric: bool = False) -> bool:
    if numeric or tolerance:
        try:
            with localcontext() as context:
                context.prec = 50
                return abs(_number(actual) - _number(expected)) <= tolerance
        except (ValueError, ArithmeticError):
            return False
    return actual == expected


def expected_cell_type(assertion: NativeAssertion, source_type: str | None) -> str:
    """An update preserves cell semantics unless its contract explicitly changes them."""
    if assertion.expected_type is not None:
        return {"formula": "f", "string": "s", "number": "n", "boolean": "b"}[assertion.expected_type]
    if assertion.expected is not None and assertion.expected.startswith("="):
        return "f"
    return source_type or "s"


def _preserved_units(units: dict[str, str], format: str) -> dict[str, str]:
    # Slide text is a retrieval alias over editable shape text, not an
    # independently mutable field. Comparing both would reject valid leaf edits.
    if format != "pptx":
        return units
    aliases = {key.split("/shape:", 1)[0] + "/text" for key in units if "/shape:" in key and key.endswith("/text")}
    return {key: value for key, value in units.items() if key not in aliases}


def grade_native_task(task: NativeTask, inputs: Mapping[str, bytes], submission: NativeSubmission) -> NativeGrade:
    """Inspect actual input and submitted bytes; never accept agent-reported success."""
    from .native_artifacts import inspect_artifact

    findings: list[str] = []
    units: dict[str, dict[str, str]] = {}
    hashes: dict[str, str] = {}
    metrics: dict[str, int | str] = {"preservation": "extracted_semantic_units", "assertions": 0}
    for item in task.inputs:
        payload = inputs.get(item.artifact_id)
        if payload is None or len(payload) > MAX_FILE_BYTES:
            findings.append(f"input_missing_or_oversized:{item.artifact_id}")
            continue
        try:
            snapshot = inspect_artifact(payload, item.format)
            if snapshot.sha256 != item.sha256:
                raise ValueError("checksum mismatch")
            units[item.artifact_id] = {unit.locator: unit.text for unit in snapshot.units}
            hashes[item.artifact_id] = snapshot.sha256
        except (ValueError, OSError, KeyError, TypeError) as exc:
            findings.append(f"input_invalid:{item.artifact_id}:{type(exc).__name__}")

    def resolve(ref: NativeCitation) -> str:
        return units[ref.artifact_id][ref.locator]

    answers = {answer.assertion_id: answer for answer in submission.answers}
    if len(answers) != len(submission.answers) or set(answers) != {a.id for a in task.assertions}:
        findings.append("answer_set_mismatch")
    for assertion in task.assertions:
        try:
            if assertion.calculation:
                operands = assertion.calculation.operands
                values = [_number(resolve(ref)) for ref in operands]
                with localcontext() as context:
                    context.prec = 50
                    if assertion.calculation.operation == "sum":
                        expected = str(sum(values, Decimal(0)))
                    elif assertion.calculation.operation == "difference":
                        expected = str(values[0] - values[1])
                    else:
                        if values[1] == 0:
                            raise ValueError("zero denominator")
                        expected = str(values[0] / values[1])
            else:
                assert assertion.target is not None
                operands = (assertion.target,)
                expected = resolve(assertion.target)
            numeric = assertion.calculation is not None
            if assertion.expected is not None and not _equal(expected, assertion.expected, assertion.tolerance, numeric=numeric):
                raise ValueError("input evidence disagrees with expected truth")
            answer = answers[assertion.id]
            cited = {(c.artifact_id, c.locator) for c in answer.citations}
            required = {(c.artifact_id, c.locator) for c in operands}
            if cited != required:
                raise ValueError("citations do not identify required evidence")
            if not _equal(answer.value, expected, assertion.tolerance, numeric=numeric):
                raise ValueError("answer differs from inspected evidence")
            metrics["assertions"] = int(metrics["assertions"]) + 1
        except (KeyError, ValueError, ArithmeticError):
            findings.append(f"answer_failed:{assertion.id}")

    output = task.output
    if output is None:
        if submission.files:
            findings.append("unexpected_output_files")
    elif len(submission.files) != 1 or submission.files[0].artifact_id != output.artifact_id:
        findings.append("output_set_mismatch")
    else:
        submitted = submission.files[0]
        try:
            if submitted.format != output.format:
                raise ValueError("output format differs")
            payload = base64.b64decode(submitted.content_base64, validate=True)
            if not payload or len(payload) > MAX_FILE_BYTES:
                raise ValueError("invalid output size")
            snapshot = inspect_artifact(payload, output.format)
            result_units = {unit.locator: unit.text for unit in snapshot.units}
            metrics["output_sha256"] = snapshot.sha256
            for assertion in output.assertions:
                assert assertion.target is not None and assertion.expected is not None
                locator = assertion.target.locator
                actual = result_units.get(locator)
                numeric = False
                if output.format == "xlsx" and "/cell:" in locator and locator.rsplit("/", 1)[-1].startswith("cell:"):
                    source_type = units.get(output.source_artifact_id or "", {}).get(locator + "/type")
                    required_type = expected_cell_type(assertion, source_type)
                    numeric = required_type == "n"
                    if result_units.get(locator + "/type") != required_type:
                        findings.append(f"output_type_failed:{assertion.id}")
                elif assertion.expected_type is not None:
                    findings.append(f"output_type_requires_cell:{assertion.id}")
                if actual is None or not _equal(actual, assertion.expected, assertion.tolerance, numeric=numeric):
                    findings.append(f"output_assertion_failed:{assertion.id}")
                else:
                    metrics["assertions"] = int(metrics["assertions"]) + 1
            if output.source_artifact_id is not None:
                source_id = output.source_artifact_id
                if submitted.source_sha256 != hashes.get(source_id) or source_id not in hashes:
                    findings.append("update_source_version_mismatch")
                else:
                    source_units = _preserved_units(units[source_id], output.format)
                    preserved_result = _preserved_units(result_units, output.format)
                    changed = {a.target.locator for a in output.assertions if a.target}
                    if not changed <= source_units.keys():
                        findings.append("update_target_missing_in_source")
                    changed_types = {key + "/type" for key in changed if key + "/type" in source_units} if output.format == "xlsx" else set()
                    if not any(result_units.get(key) != source_units.get(key) for key in changed | changed_types):
                        findings.append("update_did_not_change_content")
                    authorized = changed | changed_types
                    if {k: v for k, v in source_units.items() if k not in authorized} != {k: v for k, v in preserved_result.items() if k not in authorized}:
                        findings.append("update_unaffected_content_changed")
        except (ValueError, OSError, KeyError, TypeError, binascii.Error):
            findings.append("output_invalid")
    return NativeGrade(passed=not findings, findings=tuple(findings), metrics=metrics)


def public_contract(task: NativeTask) -> dict[str, Any]:
    """Only task instructions and submission shape cross the agent boundary."""
    return {
        "id": task.id,
        "operation": task.operation,
        "prompt": task.prompt,
        "inputs": [item.model_dump(mode="json") for item in task.inputs],
        "answers": [{"assertion_id": a.id, "requires_citations": True} for a in task.assertions],
        "output": None if task.output is None else {
            "artifact_id": task.output.artifact_id,
            "format": task.output.format,
            "source_artifact_id": task.output.source_artifact_id,
        },
        "submission_schema": NativeSubmission.model_json_schema(),
    }
