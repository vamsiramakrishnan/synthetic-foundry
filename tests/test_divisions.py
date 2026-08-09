"""Widening a company, and the arithmetic that keeps it the same company.

``divisions.py`` exists because of a measurement: scaling the modelled
organisation from 23 people to 429 left facts at 8,021, artifacts at 204 and
evaluation cases at 596 — identical, because 429 people were managing the same
three divisions. The corpus follows the *structure*, so the structure is the
knob, and these are the properties that make widening it safe.
"""

from __future__ import annotations

import pytest

from worldloom import archetypes, divisions


def _shares(units) -> list[float]:  # type: ignore[no-untyped-def]
    return [unit.share for unit in units]


# ---------------------------------------------------------------------------
# 1. The arithmetic
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("count", [3, 4, 5, 6, 7, 8])
def test_shares_sum_to_exactly_one(count: int) -> None:
    """Exactly, not approximately.

    A share is a fraction of group revenue and every unit-level table in the
    corpus reconciles against the group total. ``0.9999999999999999`` is a
    reconciliation failure waiting for the right renderer, which is why
    ``widen`` puts the rounding remainder on the largest division rather than
    hoping float addition lands.
    """
    units = divisions.widen(
        archetypes.get("omnichannel_retailer").units,
        industry="Omnichannel retail", count=count,
    )
    assert len(units) == count
    assert sum(_shares(units)) == 1.0


def test_the_declared_divisions_keep_their_relative_sizes() -> None:
    """What makes a widened company the *same* company.

    64/21/15 must stay in that ratio however many divisions arrive. If it did
    not, widening would be a different business rather than a bigger one, and
    every figure a reader recognises would move for no reason they can see.
    """
    base = archetypes.get("omnichannel_retailer").units
    wide = divisions.widen(base, industry="Omnichannel retail", count=8)

    original = _shares(base)
    kept = _shares(wide)[: len(base)]
    for index in range(1, len(base)):
        assert kept[index] / kept[0] == pytest.approx(original[index] / original[0])


def test_an_added_division_is_never_larger_than_the_core() -> None:
    """Equal shares were the first rule and they produce a company nobody has.

    Widening a 64/21/15 retailer to eight divisions gave Property 12.5% against
    General Merchandise's 7.9% — an adjacent business outweighing the core it
    was bolted onto. A company's fourth line of business is smaller than the
    ones it was built on, and its fifth smaller again.
    """
    base = archetypes.get("omnichannel_retailer").units
    wide = divisions.widen(base, industry="Omnichannel retail", count=8)
    added = _shares(wide)[len(base):]

    assert max(added) <= max(_shares(wide)[: len(base)])
    assert added == sorted(added, reverse=True), "each addition is smaller than the last"


# ---------------------------------------------------------------------------
# 2. Refusals a caller can act on
# ---------------------------------------------------------------------------


def test_narrowing_is_refused_rather_than_truncating() -> None:
    """A corpus that quietly got smaller is the worst kind of surprise.

    Dropping a division removes every fact, document and question it owned, and
    doing that because somebody typed a smaller number would be a silent data
    loss reported as success.
    """
    with pytest.raises(ValueError, match="cannot be narrowed"):
        divisions.widen(
            archetypes.get("omnichannel_retailer").units,
            industry="Omnichannel retail", count=2,
        )


def test_running_out_of_pool_is_refused_with_the_number_available() -> None:
    """Better than a division called ``Division 7``.

    A synthetic company whose seventh division is named for its index tells a
    reader it is synthetic without telling them anything else — and the whole
    point of an archetype is that the shape means something.
    """
    with pytest.raises(ValueError, match="is the most it can be widened to"):
        divisions.widen(
            archetypes.get("omnichannel_retailer").units,
            industry="Omnichannel retail", count=99,
        )


def test_an_industry_with_no_pool_cannot_be_widened() -> None:
    with pytest.raises(ValueError, match="has 0 more in its pool"):
        divisions.widen(
            archetypes.get("omnichannel_retailer").units,
            industry="Deep Sea Mining", count=4,
        )


# ---------------------------------------------------------------------------
# 3. The key is the record
# ---------------------------------------------------------------------------


def test_the_width_rides_the_archetype_key_so_a_recipe_rebuilds_it() -> None:
    """The one thing a recipe records about the shape is the key.

    A width carried anywhere else would rebuild a three-division company from
    an eight-division corpus and report success — the failure
    ``vocabulary.spoken`` qualified its own key to avoid.
    """
    wide = archetypes.get("omnichannel_retailer+8div")
    assert len(wide.units) == 8
    assert wide.key.endswith("+8div")
    assert archetypes.get(wide.key).units == wide.units, "the key round-trips"


def test_a_vocabulary_and_a_width_compose() -> None:
    """Both qualifiers on one key, applied in a fixed order.

    Widening runs *after* the vocabulary, so a pool division keeps the pool's
    own name: ``spoken`` maps an archetype's declared units onto a dialect's
    trades one for one and has nothing to say about a division the dialect
    never described.
    """
    club = archetypes.get("omnichannel_retailer+wholesale_club+8div")
    assert len(club.units) == 8
    assert club.units[0].name == archetypes.get(
        "omnichannel_retailer+wholesale_club"
    ).units[0].name
    # ...and the added ones are the pool's, unspoken.
    assert club.units[3].name == divisions.POOLS["Omnichannel retail"][0].name


def test_asking_for_what_the_archetype_already_has_returns_it_unchanged() -> None:
    """The byte-stable path. A build that does not widen is the build that
    shipped before this module existed, which is why ``widened(a, None)`` and
    ``widened(a, len(a.units))`` both return the archetype itself."""
    base = archetypes.get("omnichannel_retailer")
    assert divisions.widened(base, None) is base
    assert divisions.widened(base, len(base.units)) is base


def test_a_bad_width_qualifier_is_refused_rather_than_ignored() -> None:
    with pytest.raises(KeyError, match="width qualifier"):
        archetypes.get("omnichannel_retailer+notanumberdiv")


# ---------------------------------------------------------------------------
# 4. It actually reaches the corpus
# ---------------------------------------------------------------------------


def test_widening_grows_what_the_organisation_knob_could_not() -> None:
    """The measurement this module exists for, at corpus scale.

    Facts, artifacts and evaluation cases all follow the division count, where
    raising ``organisation.headcount`` from 23 to 429 moved none of them.
    Asserted as strict growth rather than as pinned numbers: what matters is
    that the structure reaches the corpus, and pinning counts here would make
    every future generator change edit this test.
    """
    from worldloom import RetailWorld
    from worldloom.scenarios import MonthEndClose

    def built(key: str):  # type: ignore[no-untyped-def]
        world = RetailWorld(seed=8128, archetype=archetypes.get(key)).build()
        return world.run(
            MonthEndClose(period="2026-03", include_operational_incident=True)
        ).compile()

    narrow, wide = built("omnichannel_retailer"), built("omnichannel_retailer+8div")

    assert len(wide.business_units) == 8 > len(narrow.business_units)
    assert len(wide.categories) > len(narrow.categories)
    assert len(wide.facts) > len(narrow.facts)
    assert len(wide.artifact_intents) > len(narrow.artifact_intents)
    assert len(wide.evaluations) > len(narrow.evaluations)
