"""Revision: the same document, at a later version.

`test_episodes.py` covers the other two artifact relationships this corpus
distinguishes — `supersedes` (a different document replacing an earlier one)
and `derived_from` (a new document building on an earlier one that stays
true). `revises` is the third: the same document's identity carried forward,
with `version` derived from the chain length rather than asserted anywhere.

The status page (`confluence_page`) is the case `planning.py` wires: one
persistent operational record, edited across incident occurrences, rather than
a fresh page minted per incident the way its ServiceNow neighbour is. See the
comment at the call site for why it is this artifact and not another.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.models import Lifecycle

PERIODS = ("2026-03", "2026-04", "2026-05")


@pytest.fixture(scope="module")
def series() -> World:
    world = RetailWorld(seed=8128).build()
    for period in PERIODS:
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))
    return world.compile()


def _pages(world: World) -> list:
    return [a for a in world.artifacts if a.artifact_type == "confluence_page"]


# ---------------------------------------------------------------------------
# 1 & 2: version is derived from the chain, not asserted
# ---------------------------------------------------------------------------


def test_a_revision_advances_the_version_and_retires_its_predecessor(series: World) -> None:
    pages = _pages(series)
    revised = [a for a in pages if a.revises]
    assert revised, "at least one status page should revise an earlier one"

    entry = revised[0]
    predecessor = series.artifacts.by_id(entry.revises)
    assert entry.version == 2
    assert predecessor.version == 1
    assert predecessor.lifecycle is Lifecycle.SUPERSEDED, (
        "a revised predecessor must be marked, or a reader could still treat it as current"
    )


def test_a_chain_of_three_gives_versions_one_two_three(series: World) -> None:
    """Nobody sets `version` anywhere — `World._manifest_for` derives it from
    the length of the `revises` chain behind each entry."""
    pages = _pages(series)
    assert len(pages) == len(PERIODS)
    assert sorted(a.version for a in pages) == [1, 2, 3]

    by_id = {a.id: a for a in pages}
    newest = max(pages, key=lambda a: a.version)

    # Walk the chain back from the newest page. It must be a line — no branch,
    # no repeat — which is exactly what `revised_twice` in validate.py exists
    # to catch if planning ever emitted one.
    seen: set[str] = set()
    node = newest
    while node.revises:
        assert node.revises not in seen, "a version history is a line, not a tree"
        seen.add(node.revises)
        node = by_id[node.revises]
    assert len(seen) == len(PERIODS) - 1


# ---------------------------------------------------------------------------
# 3: the distinction test — the substance of this task
# ---------------------------------------------------------------------------


def test_revision_is_distinct_from_supersession_and_derivation(series: World) -> None:
    """A `revises` that also showed up in `supersedes` for the same predecessor
    would mean the model had collapsed two different relationships into one."""
    supersedes_targets = {a.supersedes for a in series.artifacts if a.supersedes}
    revises_targets = {a.revises for a in series.artifacts if a.revises}
    derived_targets = {parent for a in series.artifacts for parent in a.derived_from}

    assert supersedes_targets, "no supersession present in this world"
    assert revises_targets, "no revision present in this world"
    assert derived_targets, "no derivation present in this world"

    assert not (supersedes_targets & revises_targets), "a predecessor is both replaced and revised"
    assert not (supersedes_targets & derived_targets), "a predecessor is both replaced and derived from"
    assert not (revises_targets & derived_targets), "a predecessor is both revised and derived from"


# ---------------------------------------------------------------------------
# 4: a revision knows more than what it revises
# ---------------------------------------------------------------------------


def test_a_revision_cites_more_than_the_version_it_revises(series: World) -> None:
    """A revision that cited exactly the same facts as its predecessor would not
    have modelled anything — it would be a duplicate wearing a version number."""
    revised = [a for a in _pages(series) if a.revises]
    assert revised
    for entry in revised:
        predecessor = series.artifacts.by_id(entry.revises)
        assert len(entry.supporting_fact_ids) > len(predecessor.supporting_fact_ids)


# ---------------------------------------------------------------------------
# 5: the corpus still agrees with itself
# ---------------------------------------------------------------------------


def test_the_series_validates_with_revisions_live(series: World) -> None:
    report = series.validate()
    assert report.ok, report.violations[:5]


# ---------------------------------------------------------------------------
# 6: determinism
# ---------------------------------------------------------------------------


def test_revision_is_deterministic() -> None:
    def build() -> World:
        world = RetailWorld(seed=8128).build()
        for period in PERIODS:
            world = world.run(MonthEndClose(period=period, include_operational_incident=True))
        return world.compile()

    def signature(world: World) -> list[tuple[str, str | None, int]]:
        return sorted(
            (a.id, a.revises, a.version)
            for a in world.artifacts
            if a.artifact_type == "confluence_page"
        )

    assert signature(build()) == signature(build())


# ---------------------------------------------------------------------------
# The floor this task must not disturb
# ---------------------------------------------------------------------------


def test_a_single_period_world_mints_no_revision() -> None:
    """A world that has never run before has no earlier page to revise. This is
    the id-stability guarantee spelled out as a test: minting a revision intent
    here would insert an extra id ahead of every artifact that follows it in a
    single-period build, which is exactly what would break
    examples/grocery-close/narration.json — real prose keyed to the ids a
    single-period build mints today.
    """
    world = RetailWorld(seed=8128).build()
    world = world.run(MonthEndClose(period="2026-04", include_operational_incident=True))
    world = world.compile()

    pages = _pages(world)
    assert len(pages) == 1
    assert pages[0].revises is None
    assert pages[0].version == 1
