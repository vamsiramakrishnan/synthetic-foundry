"""The SDK doors onto the loop capabilities: search, mutated, twin, as_fleet.

Each capability landed with a CLI door first. These are the Python doors, and
what each test pins is *sameness*: the method must be the CLI's capability
reached from a loop, never a second implementation that can drift. Search is
compared against the evaluate index directly; mutated against the twin
machinery's own measured footprint; as_fleet against fleet's real admission
controller, refusals included.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import MonthEndClose, sdk
from worldloom.narrative import DeterministicProvider
from worldloom.twins import MutationRefused, TwinError


@pytest.fixture(scope="module")
def close() -> sdk.Built:
    return sdk.retail(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


@pytest.fixture(scope="module")
def narrated(close: sdk.Built) -> sdk.Built:
    return sdk.Built(blueprint=close.blueprint,
                     world=close.world.narrate(DeterministicProvider()))


# ---------------------------------------------------------------------------
# search
# ---------------------------------------------------------------------------


def test_search_is_the_evaluate_index_not_a_second_retriever(narrated: sdk.Built) -> None:
    from worldloom.evaluate.bm25 import Bm25
    from worldloom.evaluate.index import passages

    hits = narrated.search("operational incident", limit=4)

    world = narrated.world if narrated.world.artifact_irs else narrated.world.compile()
    found = passages(world)
    index = Bm25([passage.text for passage in found])
    expected = [
        (found[position].id, score)
        for position, score in index.rank("operational incident", limit=4)
        if score > 0.0
    ]
    assert [(hit["passage_id"], hit["score"]) for hit in hits] == expected
    assert hits[0]["fact_ids"], "a hit carries the facts its passage cites"


def test_search_refuses_an_empty_query(narrated: sdk.Built) -> None:
    with pytest.raises(ValueError, match="empty query"):
        narrated.search("   ")


def test_search_refuses_a_cutoff_before_the_world_began(narrated: sdk.Built) -> None:
    with pytest.raises(ValueError, match="1990-01-01"):
        narrated.search("margin", as_of="1990-01-01")


def test_search_never_pads_with_zero_scores(narrated: sdk.Built) -> None:
    assert narrated.search("zzqxjv unheard nonsense") == ()


# ---------------------------------------------------------------------------
# mutated / twin
# ---------------------------------------------------------------------------


def test_mutated_rebuilds_are_deterministic_and_differ_where_asked(close: sdk.Built) -> None:
    """Same interventions twice → identical facts; and the mutant differs from
    its ancestor — the recipe was patched, not decorated."""
    base = sdk.retail(seed=8128).build().run(MonthEndClose(period="2026-03"))
    once = base.mutated({"steps/0/period": "2026-05"})
    again = base.mutated({"steps/0/period": "2026-05"})

    assert [f.id for f in once.world.facts] == [f.id for f in again.world.facts]
    assert once.world.recipe["steps"][0]["period"] == "2026-05"
    assert once.world.recipe != base.world.recipe
    assert once.blueprint is base.blueprint, "the ancestor stays readable"


def test_mutated_preserves_every_twin_refusal(close: sdk.Built) -> None:
    with pytest.raises(TwinError):
        close.mutated({"steps/0/never_recorded_key": 1})
    with pytest.raises(MutationRefused):
        close.mutated({"employees": 5000})


def test_twin_measures_from_the_record_not_the_memory(close: sdk.Built) -> None:
    """The delta manifest names the intervention and localises the change —
    the same result the CLI's twin command prints, reached from a loop."""
    result = close.twin("steps/0/period", "2026-06")
    assert result.manifest.intervention["after"] == "2026-06"
    assert result.manifest.refused is None
    assert result.manifest.changed_fact_ids, "a moved period moves dated facts"
    assert result.manifest.unchanged_counts, "locality needs its denominator"


# ---------------------------------------------------------------------------
# as_fleet
# ---------------------------------------------------------------------------


def test_as_fleet_writes_what_fleet_qualify_admits(tmp_path: Path) -> None:
    """The exported layout must satisfy the real admission controller — not a
    mock of it — including replay verification of every member."""
    from worldloom import fleet

    builts = [
        sdk.retail(seed=seed).build()
        .run(MonthEndClose(period="2026-03"))
        for seed in (101, 202)
    ]
    narrated = [
        sdk.Built(blueprint=b.blueprint, world=b.world.narrate(DeterministicProvider()))
        for b in builts
    ]
    root = sdk.as_fleet(narrated, tmp_path / "flotilla")

    qualification = fleet.qualify(root, "challenge")
    assert qualification.qualified, [f for f in qualification.floors if not f["holds"]]


def test_as_fleet_refuses_emptiness(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="empty fleet"):
        sdk.as_fleet([], tmp_path / "nothing")
