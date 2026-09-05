"""A thin projection from artifact composition to visual beats.

The compiler already owns artifact grammar and component selection. This module
adds no second grammar. It only keeps the exact section-to-component mapping in
one place so renderers can reason about a document as a sequence of visual
beats instead of re-deriving that mapping themselves.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from .compiler.compose import Composition, compose, plan_from_ir
from .compiler.plan import DensityProfile, SizeClass
from .models import ArtifactIR, ArtifactSection


class VisualKind(StrEnum):
    PROSE = "prose"
    TABLE = "table"
    CHART = "chart"
    FLOW = "flow"
    QUOTE = "quote"


@dataclass(frozen=True)
class StoryboardBeat:
    key: str
    component_id: str
    semantic_role: str
    section_index: int
    heading: str
    visual: VisualKind
    hidden: bool


@dataclass(frozen=True)
class Storyboard:
    composition: Composition
    beats: tuple[StoryboardBeat, ...]

    @property
    def ok(self) -> bool:
        return self.composition.ok


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


def _heading(ir: ArtifactIR, section: ArtifactSection, role: str) -> str:
    """Use existing prose as an assertion heading when the style asks for it.

    This is deliberately conservative: no prose is generated, unresolved fact
    references stay in the body, and evidence/table/appendix sections keep their
    authored labels. The renderer receives a presentation choice, not new truth.
    """
    if ir.metadata.get("title_register") != "assertion":
        return section.heading
    if role not in {"summary", "position", "explanation", "decision", "recommendation", "management"}:
        return section.heading
    body = (section.body or "").strip()
    if not body or "{{fact:" in body:
        return section.heading
    first = re.split(r"(?<=[.!?])\s+", body, maxsplit=1)[0].strip()
    if 18 <= len(first) <= 110 and "\n" not in first:
        return first
    return section.heading


def build(
    ir: ArtifactIR,
    *,
    artifact_type: str,
    fmt: str,
    size_class: SizeClass,
    density_profile: DensityProfile,
) -> Storyboard:
    """Compose *ir* once and preserve the compiler's exact beat mapping."""
    plan = plan_from_ir(
        ir,
        artifact_type=artifact_type,
        size_class=size_class,
        density_profile=density_profile,
    )
    composition = compose(plan, fmt=fmt)
    section_by_key = {
        beat.key: (index, section)
        for index, (beat, section) in enumerate(zip(plan.beats, ir.sections))
    }
    role_by_key = {beat.key: beat.semantic_role for beat in plan.beats}

    beats = tuple(
        StoryboardBeat(
            key=key,
            component_id=component_id,
            semantic_role=role_by_key[key],
            section_index=section_by_key[key][0],
            heading=_heading(ir, section_by_key[key][1], role_by_key[key]),
            visual=_visual(section_by_key[key][1]),
            hidden=section_by_key[key][1].hidden,
        )
        for component_id, key in zip(composition.components, composition.beats)
    )
    return Storyboard(composition=composition, beats=beats)
