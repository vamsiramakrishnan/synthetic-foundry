"""Source-value reuse changes parser work, never the qualification proof."""
from __future__ import annotations

import hashlib
from collections import Counter
from typing import Any

import pytest

from worldloom import native_artifacts
from worldloom.native_artifacts import NativeArtifactError, _SourceInspection
from worldloom.native_query_planning import plan_native_workload
from worldloom.native_reference import qualify_native_task, reference_submission
from worldloom.native_tasks import (
    NativeAssertion,
    NativeCitation,
    NativeInput,
    NativeOutput,
    NativeTask,
    grade_native_task,
)


@pytest.fixture
def source() -> tuple:
    from test_native_intake_integrity import _corpus

    pytest.importorskip("docx")
    return _corpus("docx", "prose")


def _count(monkeypatch: pytest.MonkeyPatch) -> Counter[tuple[str, str]]:
    calls: Counter[tuple[str, str]] = Counter()
    original = native_artifacts.inspect_artifact
    def inspect(payload: bytes, format: str) -> Any:
        calls[format, hashlib.sha256(payload).hexdigest()] += 1
        return original(payload, format)
    monkeypatch.setattr(native_artifacts, "inspect_artifact", inspect)
    return calls


def test_source_cache_keys_actual_bytes_and_format_and_refuses_changed_task_input(source: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    world, result, plan = source
    workload = plan_native_workload(world, {"review": result}, plan)
    task = workload.tasks[0]
    calls = _count(monkeypatch)
    inspection = _SourceInspection()
    inputs = {"review": result.payload}
    assert qualify_native_task(task, inputs, _inspection=inspection).passed
    assert qualify_native_task(task, inputs, _inspection=inspection).passed
    assert sum(calls.values()) == 1
    changed = result.payload + b"changed-package-bytes"
    refused = qualify_native_task(task, {"review": changed}, _inspection=inspection)
    assert not refused.passed and refused.findings == ("reference_invalid:ValueError",)
    assert sum(calls.values()) == 2
    with pytest.raises(NativeArtifactError, match="package is not xlsx"):
        inspection.inspect(result.payload, "xlsx")
    assert sum(calls.values()) == 3


def test_source_cache_does_not_share_mutable_metrics(source: tuple) -> None:
    _, result, _ = source
    inspection = _SourceInspection()
    first = inspection.inspect(result.payload, "docx")
    expected = first.metrics.copy()
    first.metrics.clear()
    second = inspection.inspect(result.payload, "docx")
    assert second.metrics == expected and second.metrics is not first.metrics
    second.metrics["paragraphs"] = -1
    assert inspection.inspect(result.payload, "docx").metrics == expected
    with pytest.raises(ValueError, match="frozen"):
        second.units[0].text = "forged extraction"


def test_source_cache_lru_and_unit_text_admission_bounds_do_not_retain_oversized_values(source: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, result, _ = source
    calls = _count(monkeypatch)
    inspection = _SourceInspection(max_entries=2)
    payloads = [result.payload + tail for tail in (b"a", b"b", b"c")]
    for position in (0, 1, 0, 2, 0, 1):
        inspection.inspect(payloads[position], "docx")
    assert sum(calls.values()) == 4
    assert len(inspection._entries) == 2
    baseline = native_artifacts.inspect_artifact(result.payload, "docx")
    for bounded in (_SourceInspection(max_entries=0), _SourceInspection(max_units=1), _SourceInspection(max_text_bytes=1)):
        before = sum(calls.values())
        assert bounded.inspect(result.payload, "docx") == baseline
        assert bounded.inspect(result.payload, "docx") == baseline
        assert sum(calls.values()) == before + 2
        assert not bounded._entries and bounded._units == bounded._text_bytes == 0


def test_submitted_output_is_freshly_parsed_even_when_source_inspection_is_shared(source: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    _, result, _ = source
    task = NativeTask(id="update", operation="update", inputs=(NativeInput(artifact_id="review", format="docx",
        path="inputs/review.docx", sha256=result.manifest.sha256),), output=NativeOutput(artifact_id="updated",
            format="docx", source_artifact_id="review", assertions=(NativeAssertion(id="title",
                target=NativeCitation(artifact_id="updated", locator="paragraph:1"), expected="Revised revenue review"),)))
    inputs = {"review": result.payload}
    inspection = _SourceInspection()
    calls = _count(monkeypatch)
    submitted = reference_submission(task, inputs, _inspection=inspection)
    first = grade_native_task(task, inputs, submitted, _inspection=inspection)
    second = grade_native_task(task, inputs, submitted, _inspection=inspection)
    assert first == second and first.passed
    assert calls["docx", result.manifest.sha256] == 1
    assert sum(calls.values()) == 3
    assert len(inspection._entries) == 1


def test_cached_and_uncached_plans_submissions_and_grades_are_identical_with_fewer_parses(monkeypatch: pytest.MonkeyPatch) -> None:
    from test_native_query_planning import _plan, _world

    for dependency in ("docx", "pptx", "openpyxl"):
        pytest.importorskip(dependency)
    world, rendered = _world()
    plan = _plan(max_tasks=24)
    calls = _count(monkeypatch)
    source_keys = {(value.manifest.format, value.manifest.sha256) for value in rendered.values()}
    baseline = plan_native_workload(world, rendered, plan, _inspection=_SourceInspection(max_entries=0))
    uncached_source_calls = sum(calls[key] for key in sorted(source_keys))
    calls.clear()
    workload = plan_native_workload(world, rendered, plan)
    cached_source_calls = sum(calls[key] for key in sorted(source_keys))
    assert workload.model_dump_json() == baseline.model_dump_json()
    assert set(workload.operation_counts) == {"read", "analyze", "update", "create"}
    assert cached_source_calls == len(source_keys) == 6
    assert uncached_source_calls > cached_source_calls * 10
    payloads = {key: value.payload for key, value in rendered.items()}
    inspection = _SourceInspection()
    for task in workload.tasks:
        uncached = reference_submission(task, payloads)
        cached = reference_submission(task, payloads, _inspection=inspection)
        assert cached.model_dump_json() == uncached.model_dump_json()
        assert (grade_native_task(task, payloads, cached, _inspection=inspection).model_dump_json()
                == grade_native_task(task, payloads, uncached).model_dump_json())


def test_warm_source_cache_never_reuses_world_privacy_or_task_truth_decisions(source: tuple) -> None:
    from test_native_intake_integrity import _changed_section

    world, result, plan = source
    inspection = _SourceInspection()
    workload = plan_native_workload(world, {"review": result}, plan, _inspection=inspection)
    assert len(inspection._entries) == 1
    with pytest.raises(ValueError, match="private authored section"):
        plan_native_workload(_changed_section(world, hidden=True), {"review": result}, plan, _inspection=inspection)
    task = workload.tasks[0]
    altered = task.model_copy(update={"assertions": (task.assertions[0].model_copy(update={"expected": "forged truth"}),)})
    refused = qualify_native_task(altered, {"review": result.payload}, _inspection=inspection)
    assert not refused.passed and refused.findings == ("answer_failed:" + task.assertions[0].id,)


def test_native_case_compilation_reuses_extraction_without_reusing_source_validation(source: tuple, monkeypatch: pytest.MonkeyPatch) -> None:
    from test_native_intake_integrity import _changed_section

    from worldloom.native_eval_bridge import native_task_cases

    world, result, plan = source
    workload = plan_native_workload(world, {"review": result}, plan)
    calls = _count(monkeypatch)
    cases = native_task_cases(workload.tasks, {"review": result}, namespace="company", world=world)
    assert len(cases) == len(workload.tasks) > 1
    # _bytes independently rechecks each distinct source through its existing
    # path; inventory and all reference proofs share one extraction here.
    assert calls["docx", result.manifest.sha256] == 1
    with pytest.raises(ValueError, match="private authored section"):
        native_task_cases(workload.tasks, {"review": result}, namespace="company", world=_changed_section(world, hidden=True))
