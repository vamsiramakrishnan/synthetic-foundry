"""Sorting matched journeys into what this wave can and cannot build.

The sample catalogue happens to contain one of each interesting case, which
is the point of using it as the anchor:

    cuj_9636dd61a048   creates Jira epics      ──▶  write
    cuj_3ac134e740af   searches and answers    ──▶  lookup
    cuj_80e0d9ce1f1b   drafting, no tools      ──▶  no_world

The rest of the tests cover the edges one happy file cannot: a journey W2
refused, a journey anchored on a cluster that still carries a tool step, and
a capability step claiming to write.
"""

from __future__ import annotations

from pathlib import Path

from worldloom.telemetry import (
    ANSWER_ONLY_UNSUPPORTED,
    NO_WORLD_NEEDED,
    Group,
    Severity,
    group_for,
    load_catalogue,
    match_catalogue,
    sort_catalogue,
)

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

WRITES = "cuj_9636dd61a048"
LOOKS_UP = "cuj_3ac134e740af"
DRAFTS = "cuj_80e0d9ce1f1b"


def _catalogue():
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    return catalogue


def _sorted():
    return sort_catalogue(match_catalogue(_catalogue()))


def _cuj(catalogue, cuj_id: str):
    return next(cuj for cuj in catalogue.cujs if cuj.id == cuj_id)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


# ---------------------------------------------------------------------------
# The sample catalogue, one journey per group.
# ---------------------------------------------------------------------------


def test_the_sample_sorts_into_one_write_one_lookup_one_no_world() -> None:
    piles = _sorted()

    assert [cuj.id for cuj in piles.write] == [WRITES]
    assert piles.lookup == (LOOKS_UP,)
    assert piles.no_world == (DRAFTS,)
    assert piles.blocked == ()


def test_every_journey_lands_in_exactly_one_pile() -> None:
    """The four piles must account for the whole catalogue, or one was lost."""
    piles = _sorted()

    assert piles.total == len(_catalogue().cujs) == 3


def test_w2s_findings_are_carried_forward_not_replaced() -> None:
    """Sorting adds to the report; it does not start a new one.

    The fold from W2 must still be visible after sorting, or a reader of the
    final report loses the fact that a step was removed.
    """
    piles = _sorted()

    assert "step_folded" in _codes(piles.report.findings)


# ---------------------------------------------------------------------------
# The two findings, and their deliberately different severities.
# ---------------------------------------------------------------------------


def test_a_lookup_journey_is_refused_as_hard_and_names_what_is_missing() -> None:
    """Reads only. Real behaviour, but Worldloom cannot express it yet."""
    piles = _sorted()
    finding = next(f for f in piles.report.findings
                   if f.code == ANSWER_ONLY_UNSUPPORTED)

    assert finding.severity is Severity.HARD
    assert finding.cuj_id == LOOKS_UP
    assert "C3" in finding.message


def test_a_no_world_journey_is_info_and_leaves_the_import_acceptable() -> None:
    """No tool calls means no world is missing. Nothing is wrong.

    This is the severity that matters most: if it were hard, every catalogue
    containing a drafting journey would fail under --strict, for doing
    nothing more than describing work that needs no connector.
    """
    piles = _sorted()
    finding = next(f for f in piles.report.findings if f.code == NO_WORLD_NEEDED)

    assert finding.severity is Severity.INFO
    assert finding.cuj_id == DRAFTS
    assert finding.detail["anchor"] == "domain_cluster"


# ---------------------------------------------------------------------------
# Edges the sample does not show.
# ---------------------------------------------------------------------------


def test_a_journey_w2_refused_is_blocked_without_a_second_finding() -> None:
    """W2 already said why. Saying it again in other words helps nobody."""
    catalogue = _catalogue()
    broken = _cuj(catalogue, WRITES).model_copy(update={"steps": tuple(
        step.model_copy(update={"connector": "acme_internal_tool"})
        if step.id == "find_notes" else step
        for step in _cuj(catalogue, WRITES).steps)})
    matched = match_catalogue(catalogue.model_copy(update={"cujs": tuple(
        broken if cuj.id == WRITES else cuj for cuj in catalogue.cujs)}))

    piles = sort_catalogue(matched)

    assert piles.blocked == (WRITES,)
    assert piles.write == ()
    assert WRITES not in {f.cuj_id for f in piles.report.findings
                          if f.code in (ANSWER_ONLY_UNSUPPORTED, NO_WORLD_NEEDED)}


def test_a_cluster_anchored_journey_is_no_world_even_with_a_tool_step() -> None:
    """The anchor says how the journey was *identified*, not what it did.

    ``domain_cluster`` means there was no tool signature to name it by. A
    stray tool step does not turn it into a journey we can anchor a world on.
    """
    drafting = _cuj(_catalogue(), DRAFTS)
    with_a_tool = drafting.model_copy(update={"steps": (
        *drafting.steps,
        _cuj(_catalogue(), WRITES).steps[0])})

    assert with_a_tool.anchor == "domain_cluster"
    assert any(step.is_tool_step for step in with_a_tool.steps)
    assert group_for(with_a_tool) is Group.NO_WORLD


def test_a_capability_step_cannot_make_a_journey_a_write() -> None:
    """Only a *tool* step writes. Model-only work changes nothing.

    ``Step`` does not forbid a capability step declaring ``effect="write"``,
    so without the ``is_tool_step`` guard a drafting journey would be sorted
    as a write and then fail to build anything.
    """
    lookup = _cuj(_catalogue(), LOOKS_UP)
    assert group_for(lookup) is Group.LOOKUP

    claiming_to_write = lookup.model_copy(update={"steps": tuple(
        step.model_copy(update={"effect": "write"})
        if not step.is_tool_step else step
        for step in lookup.steps)})

    assert any(s.effect == "write" for s in claiming_to_write.steps)
    assert group_for(claiming_to_write) is Group.LOOKUP


def test_a_journey_with_no_steps_at_all_is_no_world() -> None:
    drafting = _cuj(_catalogue(), DRAFTS).model_copy(update={"steps": ()})

    assert group_for(drafting) is Group.NO_WORLD
