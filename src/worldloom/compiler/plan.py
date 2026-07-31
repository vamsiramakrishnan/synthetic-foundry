"""The semantic artifact plan — what a document must accomplish, before it has a shape.

This is the layer a model is allowed to author. It says nothing about sections,
tables, slides or cells, because the moment a plan mentions a cell it has stopped
being a statement of intent and started being a rendering, and a rendering cannot
be re-targeted at another format.

The test for whether something belongs here: could the same plan produce a Word
memo and a slide deck that a reader would recognise as the same argument? If yes
it is a plan. If the answer depends on the format, it belongs in the component
tree downstream.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from ..models import Model

#: Size classes, in the vocabulary the existing ``ArtifactIntent`` already uses.
#: Kept identical rather than improved, because two adjacent vocabularies for the
#: same idea is how a codebase starts needing a translation table.
SizeClass = Literal["small", "medium", "long"]

#: How much a reader is expected to absorb per unit of surface. Not a synonym for
#: size: a one-page dashboard is small and dense, a twenty-page discussion
#: document is long and sparse, and the two fail in opposite directions.
DensityProfile = Literal["sparse", "balanced", "dense"]

#: Where each profile sits on the 0–1 axis that ``ComponentSpec.density`` bands
#: are declared against.
#:
#: Here rather than in the composer, and not because this is the more natural
#: home — the composer is what consumes it. It is here because two callers
#: already needed it independently (component selection, and the static audit
#: that checks no component's band is unreachable), and each was about to invent
#: its own. Two private mappings of the same three words agree until one of them
#: is tuned, and then a component the audit calls reachable stops being selected
#: with nothing reporting a contradiction.
#:
#: The values are chosen against the bands components actually declare, not as
#: even thirds. A mapping that always lands mid-band would never exclude
#: anything, which would make the density field decorative:
#:
#: - "dense" at 0.75 sits above every prose-shaped component's ceiling
#:   (``core.position`` 0.7, ``core.executive_summary`` and
#:   ``mgmt.decision_panel`` 0.6) while staying inside
#:   ``finance.metric_strip``'s 0.2–0.8. A one-page dashboard should reach for
#:   a headline strip and not for a paragraph of framing.
#: - "sparse" at 0.15 sits below that same strip's floor of 0.2. A twenty-page
#:   discussion document should not open with a row of numbers built for a
#:   reader who will look at it for three seconds.
#: - "balanced" at 0.5 clears every band, and is where most existing artifact
#:   types genuinely fall.
DENSITY_POINTS: dict[str, float] = {
    "sparse": 0.15,
    "balanced": 0.5,
    "dense": 0.75,
}


def density_of(profile: str) -> float:
    """The numeric density for a profile name."""
    try:
        return DENSITY_POINTS[profile]
    except KeyError:
        raise KeyError(
            f"unknown density profile {profile!r}; known: {', '.join(DENSITY_POINTS)}"
        ) from None


class EvidenceRef(Model):
    """A fact the artifact rests on, and the job that fact does in the argument.

    A bare fact id would be enough to render a table and is not enough to write
    an argument. ``role`` is what lets a component be chosen: the same revenue
    figure is a headline when it is the position and a driver when it is one of
    six things explaining a movement, and those want different components.
    """

    fact_id: str
    role: str
    """Semantic job — ``headline``, ``driver``, ``comparative``, ``control``."""
    emphasis: float = 0.5
    """0 to 1. Governs prominence downstream, not truth."""


class NarrativeBeat(Model):
    """One movement of the argument.

    Beats are ordered and the order is the argument. A beat is not a section: a
    single beat can become a section, half a slide, or a row band in a workbook,
    and one beat becoming three sections in a long artifact is normal.
    """

    key: str
    purpose: str
    """The beat's job, in the words its author would use.

    Carried through to the narrative request, which is what decides whether the
    prose argues or lists — a writer told "here are four metrics" produces four
    correct sentences and nothing better.
    """
    evidence: list[EvidenceRef] = Field(default_factory=list)
    semantic_role: str = "evidence"
    """Which component family can implement this beat. Matched against
    ``ComponentSpec.semantic_roles``."""
    optional: bool = False
    """Droppable when the artifact is over budget, rather than truncated.

    Marking a beat optional is a planning decision — it says this beat is
    genuinely supporting material. Dropping a required beat is a defect; dropping
    an optional one is editing.
    """


class ArtifactPlan(Model):
    """What an artifact has to accomplish, independent of how it is spelled.

    Deliberately not a subclass of ``ArtifactIntent``. An intent is the decision
    that a document *should exist*, made by the scenario before any facts are
    resolved; a plan is what that document has to *do*, made once the facts are
    known. Collapsing them would put narrative structure into the layer that runs
    before there is anything to narrate about.
    """

    intent_id: str
    artifact_type: str
    audience: str
    intent: str
    """The artifact's purpose in one line — ``explain_performance_and_request_decisions``."""
    beats: list[NarrativeBeat] = Field(default_factory=list)
    size_class: SizeClass = "medium"
    density_profile: DensityProfile = "balanced"
    emphasis: list[str] = Field(default_factory=list)
    """Themes to foreground, in priority order."""

    def evidence_ids(self) -> list[str]:
        """Every fact this plan rests on, in beat order, without duplicates.

        Order-preserving rather than a set, because the result reaches artifact
        planning and a set's iteration order would make the corpus depend on
        string hashing — which is randomised per process and would break replay.
        """
        seen: dict[str, None] = {}
        for beat in self.beats:
            for reference in beat.evidence:
                seen.setdefault(reference.fact_id, None)
        return list(seen)

    def required_beats(self) -> list[NarrativeBeat]:
        return [beat for beat in self.beats if not beat.optional]


__all__ = [
    "DENSITY_POINTS",
    "ArtifactPlan",
    "DensityProfile",
    "EvidenceRef",
    "NarrativeBeat",
    "SizeClass",
    "density_of",
]
