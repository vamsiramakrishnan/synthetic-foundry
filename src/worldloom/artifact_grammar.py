"""Purpose-driven artifact grammar.

This module does one job: turn already-resolved artifact sections into an
ordered storyboard without changing facts or prose. Renderers may consume the
storyboard; they do not decide the argument themselves.
"""

from __future__ import annotations

from enum import StrEnum

from .models import ArtifactIR, ArtifactSection, Model


class VisualKind(StrEnum):
    PROSE = "prose"
    TABLE = "table"
    CHART = "chart"
    FLOW = "flow"
    QUOTE = "quote"


class ArtifactGrammar(Model):
    artifact_type: str
    required_roles: tuple[str, ...]
    role_order: tuple[str, ...]


class StoryboardBeat(Model):
    role: str
    heading: str
    section_index: int
    visual: VisualKind
    hidden: bool = False


class Storyboard(Model):
    artifact_type: str
    beats: tuple[StoryboardBeat, ...]


_GRAMMARS: dict[str, ArtifactGrammar] = {
    "executive_summary": ArtifactGrammar(
        artifact_type="executive_summary",
        required_roles=("evidence",),
        role_order=("answer", "context", "evidence", "recommendation", "decision", "appendix"),
    ),
    "cfo_variance_memo": ArtifactGrammar(
        artifact_type="cfo_variance_memo",
        required_roles=("evidence",),
        role_order=("answer", "context", "evidence", "implication", "recommendation", "action", "appendix"),
    ),
    "incident_rca": ArtifactGrammar(
        artifact_type="incident_rca",
        required_roles=("evidence",),
        role_order=("impact", "chronology", "evidence", "cause", "action", "appendix"),
    ),
    "knowledge_article": ArtifactGrammar(
        artifact_type="knowledge_article",
        required_roles=(),
        role_order=("purpose", "context", "procedure", "evidence", "action", "appendix"),
    ),
}


def grammar_for(artifact_type: str) -> ArtifactGrammar | None:
    """Return the grammar when the artifact has one; unknown types stay valid."""
    return _GRAMMARS.get(artifact_type)


def _role(section: ArtifactSection) -> str:
    if section.hidden:
        return "appendix"
    return section.semantic_role.strip() or "evidence"


def _visual(section: ArtifactSection) -> VisualKind:
    if section.charts:
        return VisualKind.CHART
    if section.flow is not None:
        return VisualKind.FLOW
    if section.table is not None:
        return VisualKind.TABLE
    if section.quote is not None:
        return VisualKind.QUOTE
    return VisualKind.PROSE


def storyboard(ir: ArtifactIR, artifact_type: str) -> Storyboard:
    """Compile sections into deterministic semantic beats.

    A beat points back to exactly one section. This deliberately does not merge,
    split, rewrite, or invent content; those can be layered later without making
    this thin contract complicated.
    """
    beats = tuple(
        StoryboardBeat(
            role=_role(section),
            heading=section.heading,
            section_index=index,
            visual=_visual(section),
            hidden=section.hidden,
        )
        for index, section in enumerate(ir.sections)
    )
    return Storyboard(artifact_type=artifact_type, beats=beats)


def validate_storyboard(board: Storyboard) -> tuple[str, ...]:
    """Return grammar violations. The caller decides whether they are fatal."""
    grammar = grammar_for(board.artifact_type)
    if grammar is None:
        return ()

    violations: list[str] = []
    roles = tuple(beat.role for beat in board.beats)
    for required in grammar.required_roles:
        if required not in roles:
            violations.append(f"missing required role: {required}")

    order = {role: index for index, role in enumerate(grammar.role_order)}
    known = [order[role] for role in roles if role in order]
    if known != sorted(known):
        violations.append("semantic roles are out of order")
    return tuple(violations)
