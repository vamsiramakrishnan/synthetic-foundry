"""The incident storyline library: variety without a byte of causality.

The library exists because a 24-period flagship measured 24 copies of one
incident — one distinct confirmed cause across 48 `ops.cause` facts. These
tests hold the two promises that made the fix safe to ship: a storyline can
only say what the failure *was* (it rides the episode-text seam, so keys,
placeholders, fact ids and machine values cannot move), and a build that
never names one is the build this engine always produced.
"""

from __future__ import annotations

import pytest

from worldloom.generators import episode_text, operations
from worldloom.retail import MonthEndClose, RetailWorld
from worldloom.rng import Rng

CLASSIC = "hierarchy_mapping"


def test_classic_storyline_is_an_empty_overlay() -> None:
    # The whole byte-identity argument rests here: merged({}, pack) is the
    # exact value the scenario always passed, so a corpus that never chose a
    # storyline cannot have moved.
    assert operations.STORYLINES[CLASSIC] == {}


def test_every_storyline_overrides_only_known_keys_and_placeholders() -> None:
    # The same lint a pack's episode_text passes through: no orphan keys, no
    # invented placeholders. A storyline that failed this would crash a build
    # mid-generation with a KeyError from inside the engine — the exact
    # failure mode the seam exists to catch at the edge.
    for name, overlay in operations.STORYLINES.items():
        findings = episode_text.check_overrides(
            operations.TEXT, overlay, field=f"storyline[{name!r}]"
        )
        assert findings == [], findings


def test_storylines_disagree_about_what_the_failure_was() -> None:
    # Five storylines that resolved to the same confirmed cause would be the
    # repetition hole wearing five names.
    causes = {
        overlay.get("fact.cause", operations.TEXT["fact.cause"])
        for overlay in operations.STORYLINES.values()
    }
    assert len(causes) == len(operations.STORYLINES)


def test_every_storyline_has_a_matching_benchmark_overlay() -> None:
    # One authored thing, two surfaces. A storyline in one table but not the
    # other is a benchmark that contradicts its own corpus — the exact drift
    # keeping both tables in `operations` exists to prevent.
    assert sorted(operations.EVAL_STORYLINES) == sorted(operations.STORYLINES)
    assert operations.EVAL_STORYLINES[CLASSIC] == {}

    from worldloom.generators import evaluation

    for name, overlay in operations.EVAL_STORYLINES.items():
        findings = episode_text.check_overrides(
            evaluation.EVAL_TEXT, overlay, field=f"eval_storyline[{name!r}]"
        )
        assert findings == [], findings

    # Every EVAL_TEXT template that states the classic failure in words is
    # re-voiced by every non-classic storyline. Found by grep once, pinned
    # here so a new mapping-table-quoting template cannot land without
    # joining the overlay.
    coupled = {
        "a.incident.undetected", "a.incident.recurrence", "q.citation.mapping_owner",
        "a.across.recurrence", "q.abstain.next_audit", "q.incident.undetected.estate",
        "q.citation.mapping_owner.estate",
    }
    import re

    actually_coupled = {
        key for key, template in evaluation.EVAL_TEXT.items()
        if re.search(r"mapping|hierarchy", template)
    }
    assert actually_coupled == coupled
    for name, overlay in operations.EVAL_STORYLINES.items():
        if name == CLASSIC:
            continue
        assert coupled <= set(overlay), f"{name} misses {coupled - set(overlay)}"


def test_rotation_is_classic_first_every_storyline_once_and_seeded() -> None:
    order = operations.storyline_rotation(Rng(8128).derive("incident-storylines"))
    assert order[0] == CLASSIC
    assert sorted(order) == sorted(operations.STORYLINES)
    assert order == operations.storyline_rotation(Rng(8128).derive("incident-storylines"))
    # A different world deals a different order — the point of seeding it —
    # though any single pair of seeds may collide; three seeds pin the claim
    # without betting on which two differ.
    orders = {
        tuple(operations.storyline_rotation(Rng(seed).derive("incident-storylines")))
        for seed in (1, 2, 3)
    }
    assert len(orders) > 1


def test_unknown_storyline_is_refused_by_name() -> None:
    with pytest.raises(ValueError, match="unknown incident storyline"):
        operations.storyline_text("emu_stampede")


def test_a_storyline_changes_the_cause_but_not_the_chain() -> None:
    classic = RetailWorld(seed=4242).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    varied = RetailWorld(seed=4242).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True,
                      storyline="fx_rate_stale")
    )

    def confirmed_cause(world):
        return next(
            fact.text_value for fact in world.facts.where(kind="ops.cause")
            if fact.supersedes is not None
        )

    assert confirmed_cause(classic) == operations.TEXT["fact.cause"]
    assert confirmed_cause(varied) == operations.STORYLINES["fx_rate_stale"]["fact.cause"]
    # Surface only: the same facts by kind, the same events by kind, the same
    # ids in the same order. A storyline that could add or drop a step would
    # be a causality knob wearing a costume.
    assert [f.id for f in classic.facts] == [f.id for f in varied.facts]
    assert [f.kind for f in classic.facts] == [f.kind for f in varied.facts]
    assert [e.kind for e in classic.events] == [e.kind for e in varied.events]


def test_default_close_records_no_storyline_and_a_chosen_one_records_its_name() -> None:
    world = RetailWorld(seed=4242).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    step = world.recipe["steps"][-1]
    # Absent, not "hierarchy_mapping": an unconditional key would move the
    # recipe of every default build, which is the byte-for-byte diff CI runs.
    assert "storyline" not in step

    varied = world.run(
        MonthEndClose(period="2026-04", include_operational_incident=True,
                      storyline="duplicate_grn")
    )
    assert varied.recipe["steps"][-1]["storyline"] == "duplicate_grn"


def test_recurrence_only_counts_prior_periods_of_the_same_storyline() -> None:
    world = RetailWorld(seed=4242).build()
    world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.run(
        MonthEndClose(period="2026-04", include_operational_incident=True,
                      storyline="snapshot_late")
    )
    world = world.run(MonthEndClose(period="2026-05", include_operational_incident=True))

    recurrences = [
        fact.text_value for fact in world.facts.where(kind="ops.previous_similar_incident")
    ]
    assert len(recurrences) == 3
    # March: nothing before it. April: a March incident exists, but it told a
    # different story, and "a comparable failure was traced to the same
    # snapshot schedule" citing a mapping-table month would be the corpus
    # contradicting itself — so April reads as a first occurrence too.
    assert "2026-03" not in recurrences[1]
    assert recurrences[1] == operations.STORYLINES["snapshot_late"]["fact.recurrence_first"]
    # May retells March's story, and names March.
    assert "2026-03" in recurrences[2]
