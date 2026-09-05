from worldloom.models import ArtifactIR, ArtifactSection, Table
from worldloom.storyboard import VisualKind, build


def test_storyboard_preserves_compiler_order_and_section_identity() -> None:
    ir = ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Executive review",
        sections=[
            ArtifactSection(heading="Position", body="Current position.", semantic_role="summary"),
            ArtifactSection(
                heading="Evidence",
                table=Table(key="evidence", title="Evidence"),
                semantic_role="evidence",
            ),
        ],
    )

    board = build(
        ir,
        artifact_type="executive_summary",
        fmt="pptx",
        size_class="small",
        density_profile="balanced",
    )

    assert board.ok
    assert [beat.section_index for beat in board.beats] == [0, 1]
    assert [beat.semantic_role for beat in board.beats] == ["summary", "evidence"]
    assert [beat.visual for beat in board.beats] == [VisualKind.PROSE, VisualKind.TABLE]


def test_storyboard_exposes_existing_grammar_failure_without_new_rules() -> None:
    ir = ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Executive review",
        sections=[ArtifactSection(heading="Controls", body="Detail.", semantic_role="control")],
    )

    board = build(
        ir,
        artifact_type="executive_summary",
        fmt="pptx",
        size_class="small",
        density_profile="balanced",
    )

    assert not board.ok
    assert {violation.code for violation in board.composition.violations} >= {
        "wrong_opening",
        "missing_role",
        "forbidden_role",
    }
