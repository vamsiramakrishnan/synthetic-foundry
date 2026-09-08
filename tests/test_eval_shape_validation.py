from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from worldloom.connector_data import ConnectorRecord
from worldloom.eval_candidates import validate_candidate
from worldloom.eval_design import (
    ArtifactShapeRequirement,
    EvalShape,
    EvalSpec,
    EvalStepSpec,
    RecordShapeRequirement,
    RequirementKind,
    ThreadShapeRequirement,
    WorldRequirement,
    plan_candidates,
)
from worldloom.eval_shape_validation import check_candidate_shape
from worldloom.models import ArtifactIR, ArtifactSection
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.world import World


def _spec(shape: EvalShape | None = None) -> EvalSpec:
    return EvalSpec(id="shape-proof", capability="search", persona="operator",
                    request_template="Find the evidence.",
                    steps=(EvalStepSpec(id="find", capability="search"),),
                    requirements=(WorldRequirement(id="facts", kind=RequirementKind.FACT),),
                    shape=shape or EvalShape(), candidate_count=1)


@pytest.mark.parametrize(("minimum", "accepted"), ((1, True), (1_000_000, False)))
def test_candidate_checks_shape_even_when_requirements_pass(minimum: int, accepted: bool) -> None:
    spec = _spec(EvalShape(records=(RecordShapeRequirement(
        connector="email", entity="message", records=minimum,
    ),)))
    plan = plan_candidates(spec)[0]
    world = RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))

    result = validate_candidate(plan, spec, world)

    assert all(check.satisfied for check in result.checks)
    assert result.accepted is accepted
    assert result.shape_checks[0].observed < 1_000_000


@pytest.mark.parametrize("field", ("shape", "requirements", "design_digest"))
def test_plan_cannot_remove_shape_or_requirement_obligations(field: str) -> None:
    spec = _spec(EvalShape(records=(RecordShapeRequirement(connector="email", entity="message"),)))
    plan = plan_candidates(spec)[0]
    world = RetailWorld(seed=plan.seed).build()
    forged = plan.model_copy(update={field: {"shape": EvalShape(), "requirements": (), "design_digest": "wrong"}[field]})

    with pytest.raises(ValueError, match="immutable eval design"):
        validate_candidate(forged, spec, world)


def _message(identifier: str, **fields: object) -> ConnectorRecord:
    return ConnectorRecord(id=identifier, connector="email", entity="message",
                           external_id=identifier, title=identifier, fields=dict(fields))


def test_record_minima_must_hold_on_the_same_real_records() -> None:
    world = RetailWorld(seed=8128).build()
    shape = EvalShape(records=(RecordShapeRequirement(
        connector="email", entity="message", total_fields=3, minimum_payload_bytes=100,
    ),))
    records = [_message("wide", a=1, b=2, c=3), _message("large", body="x" * 200)]
    checks = check_candidate_shape(shape, world, project=lambda _: records)
    assert not checks[0].satisfied
    assert checks[0].observed == 0

    records.append(_message("both", body="x" * 200, a=False, b=0))
    checks = check_candidate_shape(shape, world, project=lambda _: records)
    assert checks[0].satisfied
    assert checks[0].evidence_ids == ("both",)


def test_unobservable_constraints_are_explicit_failures() -> None:
    world = RetailWorld(seed=8128).build()
    shape = EvalShape(records=(RecordShapeRequirement(
        connector="email", entity="message", custom_fields=3,
        projection_required=True, maximum_read_bytes=100,
    ),), artifacts=(ArtifactShapeRequirement(artifact_type="pptx", slides=100),),
        threads=(ThreadShapeRequirement(connector="email", entity="message", pagination_required=True),))
    checks = check_candidate_shape(shape, world)
    unsupported = [check for check in checks if not check.supported]
    assert unsupported
    assert all(not check.satisfied and "unsupported" in check.detail for check in unsupported)
    assert {check.requirement_id for check in unsupported} >= {
        "shape.records[0].custom_fields", "shape.records[0].maximum_read_bytes",
        "shape.artifacts[0].slides", "shape.threads[0].pagination_required",
    }


def test_artifact_shape_requires_content_and_native_bytes() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    intent = next(iter(world.artifact_intents))
    shape = EvalShape(artifacts=(ArtifactShapeRequirement(
        artifact_type=intent.artifact_type, paragraphs=2, locator_required=False,
    ),))
    assert not check_candidate_shape(shape, world)[0].satisfied
    ir = ArtifactIR(id=intent.id, intent_id=intent.id, title="Evidence", sections=[
        ArtifactSection(heading="Context", body="First paragraph.\n\nSecond paragraph."),
    ])
    compiled = replace(world, _artifact_irs=(ir,))
    assert check_candidate_shape(shape, compiled)[0].satisfied
    native = EvalShape(artifacts=(ArtifactShapeRequirement(artifact_type="docx", locator_required=False),))
    assert not check_candidate_shape(native, compiled)[0].satisfied


def test_native_instance_and_size_are_read_from_rendered_bytes() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).render("markdown")
    shape = EvalShape(artifacts=(ArtifactShapeRequirement(
        artifact_type="markdown", file_size_bytes=1, locator_required=False,
    ),))
    assert check_candidate_shape(shape, world)[0].satisfied
    stripped = replace(world, _rendered=())
    assert not check_candidate_shape(shape, stripped)[0].satisfied


def test_native_shape_survives_export_load_and_refuses_missing_bytes(tmp_path: Path) -> None:
    spec = _spec(EvalShape(artifacts=(ArtifactShapeRequirement(
        artifact_type="markdown", file_size_bytes=1, locator_required=False,
    ),)))
    plan = plan_candidates(spec)[0]
    world = RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03")).render("markdown")
    original = validate_candidate(plan, spec, world)
    assert original.accepted
    world.export(tmp_path / "corpus")
    loaded = World.load(tmp_path / "corpus")
    assert not loaded._rendered
    assert validate_candidate(plan, spec, loaded) == original

    for artifact in loaded.artifacts:
        if artifact.path:
            (loaded.root / artifact.path).unlink()
    verdict = validate_candidate(plan, spec, loaded)
    assert not verdict.accepted
    assert verdict.shape_checks[0].observed == 0


def test_secondary_native_format_is_measured_after_load(tmp_path: Path) -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).render("html", "markdown")
    shape = EvalShape(artifacts=tuple(ArtifactShapeRequirement(
        artifact_type=format_name, file_size_bytes=1, locator_required=False,
    ) for format_name in ("markdown", "html")))
    assert all(item.path.endswith(".html") for item in world.artifacts)
    original = check_candidate_shape(shape, world)
    assert original[0].satisfied
    world.export(tmp_path / "corpus")
    loaded = World.load(tmp_path / "corpus")
    assert check_candidate_shape(shape, loaded) == original
    for item in loaded.artifacts:
        (loaded.root / item.path).with_suffix(".md").unlink(missing_ok=True)
    (loaded.root / "artifacts" / "unrelated.md").write_text("Unrelated bytes cannot stand in for a missing rendering.")
    checks = check_candidate_shape(shape, loaded)
    assert not checks[0].satisfied
    assert checks[1].satisfied


@pytest.mark.parametrize("escape", ("relative", "absolute", "symlink"))
def test_persisted_shape_cannot_read_outside_corpus(tmp_path: Path, escape: str) -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).render("markdown")
    world.export(tmp_path / "corpus")
    loaded = World.load(tmp_path / "corpus")
    artifact = next(item for item in loaded.artifacts if item.path.endswith(".md"))
    outside = tmp_path / "outside.md"
    outside.write_text("Bytes outside the corpus cannot satisfy its native artifact shape.")
    path = str(outside) if escape == "absolute" else "../outside.md"
    if escape == "symlink":
        (tmp_path / "corpus" / "escape.md").symlink_to(outside)
        path = "escape.md"
    forged = replace(loaded, _artifacts=(artifact.model_copy(update={"path": path}),))
    shape = EvalShape(artifacts=(ArtifactShapeRequirement(artifact_type="markdown", locator_required=False),))
    assert not check_candidate_shape(shape, forged)[0].satisfied


def test_reply_depth_cannot_join_different_threads_or_count_cycles() -> None:
    world = RetailWorld(seed=8128).build()
    shape = EvalShape(threads=(ThreadShapeRequirement(
        connector="email", entity="message", messages_per_thread=2, reply_depth=2,
    ),))
    records = [_message("a", thread_id="one"), _message("b", thread_id="two", in_reply_to="a")]
    assert not check_candidate_shape(shape, world, project=lambda _: records)[0].satisfied
    records.append(_message("c", thread_id="two", in_reply_to="b"))
    check = check_candidate_shape(shape, world, project=lambda _: records)[0]
    assert check.satisfied
    assert check.evidence_ids == ("two",)
    records[:] = [_message("a", thread_id="one", in_reply_to="b"),
                  _message("b", thread_id="one", in_reply_to="a")]
    assert not check_candidate_shape(shape, world, project=lambda _: records)[0].satisfied
