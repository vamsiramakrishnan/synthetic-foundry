import pytest

from worldloom.compiler.compose import CompositionError
from worldloom.models import ArtifactIR, ArtifactSection, Table
from worldloom.storyboard import VisualKind, build


def _build(ir: ArtifactIR):  # type: ignore[no-untyped-def]
    return build(
        ir,
        artifact_type="executive_summary",
        fmt="pptx",
        size_class="small",
        density_profile="balanced",
    )


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

    board = _build(ir)

    assert board.ok
    assert [beat.section_index for beat in board.beats] == [0, 1]
    assert [beat.semantic_role for beat in board.beats] == ["summary", "evidence"]
    assert [beat.visual for beat in board.beats] == [VisualKind.PROSE, VisualKind.TABLE]
    assert [beat.heading for beat in board.beats] == ["Position", "Evidence"]


def test_assertion_register_promotes_existing_summary_sentence() -> None:
    ir = ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Executive review",
        metadata={"title_register": "assertion"},
        sections=[
            ArtifactSection(
                heading="Position",
                body="Margin recovery is behind plan and requires a forecast reset. Supporting detail follows.",
                semantic_role="summary",
            ),
            ArtifactSection(
                heading="Evidence",
                table=Table(key="evidence", title="Evidence"),
                semantic_role="evidence",
            ),
        ],
    )

    board = _build(ir)

    assert board.beats[0].heading == "Margin recovery is behind plan and requires a forecast reset."
    assert board.beats[1].heading == "Evidence"


def test_assertion_register_does_not_promote_unresolved_fact_reference() -> None:
    ir = ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Executive review",
        metadata={"title_register": "assertion"},
        sections=[
            ArtifactSection(
                heading="Position",
                body="Margin is {{fact:margin.actual}} and remains below plan.",
                semantic_role="summary",
            ),
            ArtifactSection(
                heading="Evidence",
                table=Table(key="evidence", title="Evidence"),
                semantic_role="evidence",
            ),
        ],
    )

    assert _build(ir).beats[0].heading == "Position"


def test_storyboard_preserves_existing_compiler_refusal() -> None:
    ir = ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Executive review",
        sections=[ArtifactSection(heading="Controls", body="Detail.", semantic_role="control")],
    )

    with pytest.raises(CompositionError, match="no component that fits"):
        _build(ir)
