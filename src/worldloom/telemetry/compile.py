"""Turning matched journeys into things Worldloom can build.

W2 answered *can we emulate this?* — connector, record type, operation. That
is not the same as *can we build a test case from it?*, and this module asks
the second question.

Every journey lands in exactly one of four groups::

    write      a matched tool step writes        ──▶  built
    lookup     matched tool steps, none write    ──▶  answer_only_unsupported
    no_world   domain_cluster, or no tool step   ──▶  no_world_needed
    blocked    W2 found something hard           ──▶  already refused, upstream

Only ``write`` is built, and only in this wave. The other three are reported
rather than dropped, which is the same bargain W1 and W2 strike: anything the
importer cannot build says so by name.

The two it cannot build are not the same kind of problem, so they do not carry
the same severity.

``lookup`` is **hard**
    A journey of pure reads ending in an answer is a perfectly real journey.
    Worldloom simply has no way to express "no world changed, judge the
    answer" yet — that is core change C3, scheduled as W7. So the journey is
    refused, and the finding names what is missing rather than blaming the
    catalogue.

``no_world`` is **info**
    A journey with no tool calls at all — rewrite this email, summarise these
    notes — needs no fake world to run against. Nothing is missing and nothing
    is broken. It is counted as uncovered in the fidelity report, and the
    import is still accepted.

Sorting changes nothing. It reads a :class:`~.registry.MatchedCatalogue` and
returns the same journeys in labelled piles.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TYPE_CHECKING

from ..models import Model
from .catalogue import Cuj
from .report import Finding, ImportReport, hard, info

if TYPE_CHECKING:
    from .registry import MatchedCatalogue


ANSWER_ONLY_UNSUPPORTED = "answer_only_unsupported"
"""Reads only, then answers. Needs core change C3 (W7)."""

NO_WORLD_NEEDED = "no_world_needed"
"""Model-only work. There is no world to build, and that is fine."""


class Group(StrEnum):
    """Which pile a journey lands in."""

    WRITE = "write"
    LOOKUP = "lookup"
    NO_WORLD = "no_world"
    BLOCKED = "blocked"


class SortedCatalogue(Model):
    """Every journey, in exactly one pile. The four sum to the input."""

    write: tuple[Cuj, ...] = ()
    """The only pile this wave builds from, so these stay whole journeys."""

    lookup: tuple[str, ...] = ()
    no_world: tuple[str, ...] = ()
    blocked: tuple[str, ...] = ()
    """Ids only. Nothing downstream needs their steps."""

    report: ImportReport = ImportReport()
    """W2's findings, plus one per lookup and one per no_world journey."""

    @property
    def total(self) -> int:
        """Journeys sorted. Equals the catalogue's, or a pile was lost."""
        return (len(self.write) + len(self.lookup)
                + len(self.no_world) + len(self.blocked))


def group_for(cuj: Cuj) -> Group:
    """Which pile *cuj* belongs in, for a journey W2 did not refuse.

    ``blocked`` never comes back from here: it is a property of W2's verdict,
    not of the journey, so the caller assigns it.

    The ``domain_cluster`` test comes first because the anchor is a statement
    about how the journey was *identified* — answer-only traffic with no tool
    signature to name it by. A stray tool step does not change that.
    """
    if cuj.anchor == "domain_cluster":
        return Group.NO_WORLD
    tool_steps = [step for step in cuj.steps if step.is_tool_step]
    if not tool_steps:
        return Group.NO_WORLD
    # "A matched tool step writes" — a capability step is model-only work and
    # changes nothing, whatever its declared effect.
    if any(step.effect == "write" for step in tool_steps):
        return Group.WRITE
    return Group.LOOKUP


def sort_catalogue(matched: MatchedCatalogue) -> SortedCatalogue:
    """Sort every journey in *matched* into one of the four groups.

    Journeys W2 refused are already explained by its hard findings, so they
    are counted as ``blocked`` without a second finding saying the same thing
    in different words.
    """
    write: list[Cuj] = []
    lookup: list[str] = []
    no_world: list[str] = []
    findings: list[Finding] = []

    for cuj in matched.cujs:
        group = group_for(cuj)
        if group is Group.WRITE:
            write.append(cuj)
        elif group is Group.LOOKUP:
            lookup.append(cuj.id)
            findings.append(hard(
                ANSWER_ONLY_UNSUPPORTED,
                f"{cuj.id} reads and answers without changing anything. "
                "Worldloom cannot yet express a journey that leaves no trace "
                "in the world, so there is nothing to build a case against. "
                "Needs core change C3 (answer-only workflows)",
                cuj_id=cuj.id,
                detail={"label": cuj.label, "steps": str(len(cuj.steps))}))
        else:
            no_world.append(cuj.id)
            findings.append(info(
                NO_WORLD_NEEDED,
                f"{cuj.id} calls no business tool, so it needs no world to "
                "run against. Not built, and counted as uncovered",
                cuj_id=cuj.id,
                detail={"label": cuj.label, "anchor": cuj.anchor}))

    return SortedCatalogue(
        write=tuple(write), lookup=tuple(lookup), no_world=tuple(no_world),
        blocked=matched.refused,
        report=ImportReport(findings=matched.report.findings + tuple(findings)))
