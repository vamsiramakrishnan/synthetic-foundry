from __future__ import annotations

import hashlib
import json

from worldloom.eval_design import (
    ArtifactShapeRequirement,
    EvalShape,
    EvalSpec,
    EvalStepSpec,
    RecordShapeRequirement,
    RequirementKind,
    ThreadShapeRequirement,
    WorldRequirement,
    candidate_seed,
    design_digest,
    plan_candidates,
)


def _base_spec(**updates: object) -> EvalSpec:
    data = {
        "id": "wide-real-world",
        "capability": "cross_connector_reasoning",
        "persona": "operator",
        "request_template": "Find the evidence and update the record.",
        "steps": (
            EvalStepSpec(id="n1", capability="search", connector="jira"),
        ),
        "requirements": (
            WorldRequirement(
                id="r1",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "jira", "entity": "bug"},
            ),
        ),
        "candidate_count": 2,
    }
    data.update(updates)
    return EvalSpec.model_validate(data)


def test_empty_shape_preserves_legacy_design_digest() -> None:
    spec = _base_spec()
    legacy_payload = spec.model_dump(mode="json")
    legacy_payload.pop("shape")
    # ``entity`` was added to EvalStepSpec with the connector thin waist. A
    # legacy design did not serialize that field at all, so None must not change
    # the candidate family merely because a newer Worldloom reads it.
    for step in legacy_payload["steps"]:
        if step["entity"] is None:
            step.pop("entity")
    expected = hashlib.sha256(
        json.dumps(
            legacy_payload,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
        ).encode("utf-8")
    ).hexdigest()

    assert design_digest(spec) == expected


def test_real_world_shape_changes_candidate_family() -> None:
    plain = _base_spec()
    shaped = _base_spec(
        shape=EvalShape(
            records=(
                RecordShapeRequirement(
                    connector="jira",
                    entity="bug",
                    total_fields=320,
                    custom_fields=300,
                    minimum_populated_fields=35,
                    minimum_payload_bytes=20_000,
                    projection_required=True,
                    maximum_read_bytes=8_000,
                ),
            ),
            artifacts=(
                ArtifactShapeRequirement(
                    artifact_type="pptx",
                    slides=120,
                    versions=7,
                    speaker_note_slides=60,
                    hidden_slides=3,
                    native_charts=24,
                    file_size_bytes=40_000_000,
                    evidence_index=97,
                    evidence_modality="speaker_notes",
                ),
                ArtifactShapeRequirement(
                    artifact_type="xlsx",
                    sheets=20,
                    rows_per_sheet=50_000,
                    columns_per_sheet=40,
                    formulas=200_000,
                    file_size_bytes=80_000_000,
                    evidence_index=45_000,
                    evidence_modality="cell",
                ),
                ArtifactShapeRequirement(
                    artifact_type="docx",
                    pages=180,
                    paragraphs=2_500,
                    versions=5,
                    file_size_bytes=15_000_000,
                    evidence_index=151,
                    evidence_modality="text",
                ),
            ),
            threads=(
                ThreadShapeRequirement(
                    connector="outlook",
                    entity="message",
                    messages_per_thread=400,
                    reply_depth=40,
                    attachments_per_thread=12,
                    minimum_payload_bytes=5_000_000,
                    pagination_required=True,
                ),
            ),
        )
    )

    assert design_digest(shaped) != design_digest(plain)
    assert candidate_seed(shaped, 0) != candidate_seed(plain, 0)
    assert plan_candidates(shaped)[0].shape == shaped.shape
    assert shaped.shape.artifacts[1].cells == 40_000_000
