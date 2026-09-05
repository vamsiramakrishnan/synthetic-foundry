from worldloom.artifact_grammar import VisualKind, storyboard, validate_storyboard
from worldloom.models import ArtifactIR, ArtifactSection, Table


def test_storyboard_preserves_section_identity_and_visual_kind() -> None:
    ir = ArtifactIR(
        id="A1",
        intent_id="I1",
        title="Monthly review",
        sections=[
            ArtifactSection(heading="Answer", body="Use the revised forecast.", semantic_role="answer"),
            ArtifactSection(
                heading="Variance",
                table=Table(key="variance", title="Variance"),
                semantic_role="evidence",
            ),
            ArtifactSection(heading="Backup", body="Detail", semantic_role="evidence", hidden=True),
        ],
    )

    board = storyboard(ir, "executive_summary")

    assert [beat.section_index for beat in board.beats] == [0, 1, 2]
    assert [beat.visual for beat in board.beats] == [VisualKind.PROSE, VisualKind.TABLE, VisualKind.PROSE]
    assert [beat.role for beat in board.beats] == ["answer", "evidence", "appendix"]
    assert validate_storyboard(board) == ()


def test_storyboard_reports_missing_required_role() -> None:
    ir = ArtifactIR(
        id="A1",
        intent_id="I1",
        title="Review",
        sections=[ArtifactSection(heading="Decision", body="Approve.", semantic_role="decision")],
    )

    assert validate_storyboard(storyboard(ir, "executive_summary")) == (
        "missing required role: evidence",
    )


def test_storyboard_reports_semantic_order_drift() -> None:
    ir = ArtifactIR(
        id="A1",
        intent_id="I1",
        title="Review",
        sections=[
            ArtifactSection(heading="Decision", body="Approve.", semantic_role="decision"),
            ArtifactSection(heading="Evidence", body="Observed.", semantic_role="evidence"),
        ],
    )

    assert "semantic roles are out of order" in validate_storyboard(storyboard(ir, "executive_summary"))


def test_unknown_artifact_type_is_not_rejected() -> None:
    ir = ArtifactIR(id="A1", intent_id="I1", title="Custom")
    assert validate_storyboard(storyboard(ir, "custom_type")) == ()
