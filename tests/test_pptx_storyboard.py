import pytest

from worldloom.models import ArtifactIR, ArtifactSection
from worldloom.render import RenderError
from worldloom.render.pptx import _plan


def _ir(*sections: ArtifactSection, ecology: bool = True) -> ArtifactIR:
    return ArtifactIR(
        id="deck",
        intent_id="intent",
        title="Operating review",
        metadata={"realism_profile": "ecology/v1"} if ecology else {},
        sections=list(sections),
    )


def test_ecology_deck_refuses_semantic_order_drift() -> None:
    ir = _ir(
        ArtifactSection(heading="Decision", body="Approve.", semantic_role="decision"),
        ArtifactSection(heading="Evidence", body="Observed.", semantic_role="evidence"),
    )

    with pytest.raises(RenderError, match="artifact grammar"):
        _plan(ir)


def test_ecology_deck_accepts_answer_evidence_decision_arc() -> None:
    ir = _ir(
        ArtifactSection(heading="Answer", body="Revise the forecast.", semantic_role="answer"),
        ArtifactSection(heading="Evidence", body="Performance changed.", semantic_role="evidence"),
        ArtifactSection(heading="Decision", body="Approve the revision.", semantic_role="decision"),
    )

    plan = _plan(ir)
    assert [slide.heading for slide in plan.slides if slide.kind == "content"] == [
        "Answer",
        "Evidence",
        "Decision",
    ]


def test_legacy_deck_is_not_rejected_by_new_grammar() -> None:
    ir = _ir(
        ArtifactSection(heading="Decision", body="Approve.", semantic_role="decision"),
        ArtifactSection(heading="Evidence", body="Observed.", semantic_role="evidence"),
        ecology=False,
    )

    _plan(ir)
