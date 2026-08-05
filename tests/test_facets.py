"""Facets: claims with consequences, and the ones that cannot hold together."""

from __future__ import annotations

import math
from dataclasses import replace

import pytest

from worldloom import facets, sdk


def test_every_facet_option_says_what_it_decides() -> None:
    for name, facet in facets.FACETS.items():
        assert facet.about.strip(), name
        for option in facet.options:
            assert option.about.strip(), f"{name}:{option.value}"


def test_a_claim_emits_into_vocabularies_that_already_exist() -> None:
    """The whole design: a facet is expressive because it composes load-bearing
    things, not because a generator learned a new one."""
    from worldloom.parameters import DEFAULTS

    resolved = facets.resolve(listing="listed", maturity="legacy")
    assert all(name in DEFAULTS for name in resolved.physics)
    assert resolved.roles and resolved.lore


def test_two_facets_on_one_parameter_intersect_rather_than_conflict() -> None:
    """A premium brand in a fragmented market is an ordinary company and both
    have something true to say about margin erosion. Refusing would make the
    most interesting combinations illegal while calling them contradictory."""
    resolved = facets.resolve(margin_profile="premium", competition="fragmented")
    assert resolved.ok
    erosion = resolved.physics["retail.margin.erosion"]
    assert (erosion.low, erosion.high) == pytest.approx((0.020, 0.045))


def test_an_empty_intersection_is_refused_with_the_arithmetic() -> None:
    """"These conflict" is unactionable; the numbers are not."""
    resolved = facets.resolve(listing="mutual", margin_profile="premium")
    assert not resolved.ok
    (conflict,) = [c for c in resolved.conflicts if c.rule == "no_overlap"]
    assert "0.16" in conflict.detail and "0.48" in conflict.detail


def test_claims_that_cannot_both_be_true_are_named_as_such() -> None:
    """And claims that merely sound incompatible are not.

    The second assertion was written `not ... .ok is False`, which Python parses
    as `not (ok is False)` — the opposite of how it reads, and true whenever
    `ok` is anything but exactly `False`. It would have passed on a resolve that
    returned `None`. Both directions are stated plainly here because a
    conflict rule that refused too much would be as wrong as one that refused
    too little, and only one of those shows up as a failing test.
    """
    mutual_fund = facets.resolve(listing="mutual", governance="private_equity")
    assert not mutual_fund.ok
    assert any(c.rule == "excludes" for c in mutual_fund.conflicts)

    # A listed company owned by a fund is ordinary — plenty of them exist.
    assert facets.resolve(listing="listed", governance="private_equity").ok


def test_an_unknown_facet_or_value_lists_what_exists() -> None:
    assert any("known" in c.detail for c in facets.resolve(vibe="good").conflicts)
    assert any("takes one of" in c.detail
               for c in facets.resolve(listing="floated").conflicts)


def test_resolution_does_not_depend_on_keyword_order() -> None:
    """Keyword order is not meaningful to a reader, so the same claims must not
    resolve differently depending on how they were typed."""
    a = facets.resolve(listing="listed", maturity="legacy", scale="enterprise")
    b = facets.resolve(scale="enterprise", listing="listed", maturity="legacy")
    assert a.as_dict() == b.as_dict()


def test_estate_takes_the_larger_claim_rather_than_conflicting() -> None:
    """A legacy multinational is not a contradiction, and refusing it would make
    the two most interesting facets mutually exclusive for no reason."""
    assert facets.resolve(scale="multinational", maturity="legacy").estate == "large"


def test_unimplemented_consequences_are_reported_not_dropped() -> None:
    """A facet whose real consequence the engine lacks is evidence for building
    it; hiding that lets the facet look load-bearing while changing nothing."""
    resolved = facets.resolve(listing="listed")
    assert resolved.wants
    assert facets.unmet(resolved) == resolved.wants


def test_only_consistent_combinations_are_enumerated() -> None:
    every = facets.combinations()
    total = math.prod(len(facets.choices(name)) for name in facets.FACETS)
    assert 0 < len(every) < total
    assert all(facets.resolve(**chosen).ok for chosen in every)


# ---------------------------------------------------------------------------
# Through the SDK
# ---------------------------------------------------------------------------


def test_a_facets_roles_are_minted_not_merely_recorded() -> None:
    """An audit chair is what "listed" means operationally. A blueprint that
    carried the role without minting it would be carried-and-inert."""
    world = (sdk.retail()
             .facets(listing="listed", governance="private_equity")
             .org(headcount=25, span=5, levels=3).build())
    titles = {person.title for person in world.world.people}
    assert any("Audit and Risk" in title for title in titles)
    assert any("Investor Relations" in title for title in titles)
    assert any("Value Creation" in title for title in titles)
    assert world.ok


def test_an_explicit_setting_beats_one_a_facet_merely_implies() -> None:
    blueprint = sdk.retail().calendar("harvest").facets(trading_pattern="steady")
    assert blueprint.calendar_name == "harvest"


def test_contradictory_facets_fail_where_they_are_written() -> None:
    """A comprehension crossing six facets should fail on the combination that
    cannot hold, not fifty worlds later."""
    with pytest.raises(ValueError, match="no_overlap|excludes"):
        sdk.retail().facets(listing="mutual", margin_profile="premium")


def test_companies_enumerates_only_what_can_exist() -> None:
    field = sdk.companies(sdk.retail(), "listing", "margin_profile")
    assert 0 < len(field) < 4 * 3
    assert all(b.facet_choices for b in field)


# ---------------------------------------------------------------------------
# Lore: from a constraint a facet implies to a commitment a corpus carries
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def listed_pe():
    """The same organisation, with and without two claims about its ownership."""
    base = sdk.retail().org(headcount=25, span=5, levels=3)
    return base.build(), base.facets(listing="listed",
                                     governance="private_equity").build()


def test_a_constraint_without_an_assertion_cannot_become_a_commitment() -> None:
    """The whole reason ``Implication.asserts`` exists. Constraints with no
    sentence around them leave ``commit`` inventing prose or dropping them, and
    dropping them is the carried-and-inert failure facets exist to avoid."""
    from worldloom.models import ConstraintKind, LoreConstraint

    constraint = LoreConstraint(kind=ConstraintKind.METRIC_EMPHASIS,
                                target="close_cycle_time", effect="watched")
    with pytest.raises(ValueError, match="what it asserts"):
        facets.Implication(lore=(constraint,))


def test_a_facets_lore_is_minted_not_merely_reported(listed_pe) -> None:
    """The gap this seam closes. ``Blueprint.facets`` used to report these as
    unmet, because a blueprint had no way to add lore to a domain's own."""
    plain, faceted = listed_pe
    added = [c for c in faceted.world.lore
             if c.id not in {x.id for x in plain.world.lore}]
    assert [c.kind.value for c in added] == ["constraint", "constraint"]
    assert any("listed" in c.assertion for c in added)
    assert any("hold period" in c.assertion for c in added)
    # And generative rather than decorative: `scenarios.density_adjustment`
    # sums exactly these magnitudes when it decides how much status reporting a
    # close produces.
    from worldloom.scenarios import density_adjustment

    assert (density_adjustment(faceted.world, "finance/status_reports")
            > density_adjustment(plain.world, "finance/status_reports"))


def test_a_facets_lore_arrives_with_the_milestones_that_make_it_citable(listed_pe) -> None:
    """A commitment nothing on the timeline witnesses is a dated assertion no
    reader can chase — which is the reason ``founding_milestones`` exists at
    all, and it must hold for facet lore too."""
    _, faceted = listed_pe
    for commitment in faceted.world.lore[-2:]:
        events = [e for e in faceted.world.events if commitment.id in e.lore_ids]
        facts = [f for f in faceted.world.facts if commitment.id in f.lore_ids]
        assert [e.summary for e in events] == [commitment.assertion]
        assert [f.kind for f in facts] == ["lore.milestone"]
        assert facts[0].event_id == events[0].id


def test_added_lore_appends_and_renumbers_nothing(listed_pe) -> None:
    """Why a no-facet build is byte-identical rather than usually-identical.

    Lore order decides id order for three sequences at once — LORE, and through
    ``founding_milestones`` both EV and MFACT — so lore that inserted anywhere
    but the tail would move ids a narration already cites by literal value."""
    plain, faceted = listed_pe
    for before, after in ((plain.world.lore, faceted.world.lore),
                          (plain.world.events, faceted.world.events),
                          (plain.world.facts, faceted.world.facts)):
        assert [x.model_dump() for x in after[:len(before)]] == \
               [x.model_dump() for x in before]


def test_a_standing_claim_is_dated_so_it_cannot_re_date_the_company(listed_pe) -> None:
    """``org_builder._earliest_effective`` anchors every business unit's
    formation to the earliest dated commitment. A facet claim dated earlier
    would silently reform the whole organisation; one dated later would assert
    the company became listed part-way through its own history."""
    plain, faceted = listed_pe
    earliest = min(c.effective_from for c in plain.world.lore if c.effective_from)
    assert {c.effective_from for c in faceted.world.lore[-2:]} == {earliest}
    assert [(u.id, u.formed) for u in faceted.world.business_units] == \
           [(u.id, u.formed) for u in plain.world.business_units]


def test_the_corpus_records_where_its_facet_lore_came_from(listed_pe) -> None:
    """The claims, not the commitments they became. Every id and date in a
    commitment is a property of the world it landed in, so a rebuild that
    re-attached them would collide with ids its own minter had issued; the claim
    is what the build was given, and replaying it re-runs the construction."""
    _, faceted = listed_pe
    recorded = faceted.world.recipe["lore_claims"]
    assert [entry["source"] for entry in recorded] == ["listing:listed",
                                                       "governance:private_equity"]
    assert all(entry["constrains"] for entry in recorded)


def test_a_faceted_corpus_rebuilds_from_its_own_recipe(listed_pe) -> None:
    """The gap `world.extend_lore` used to record and not close. A corpus whose
    recipe replays into a world without its facet lore is a *different company*
    reported as the same one — different unit formation dates, different
    artifact density — which is the one failure a recipe exists to prevent."""
    from worldloom import recipe as recipe_module

    _, faceted = listed_pe
    again = recipe_module.rebuild(faceted.world.recipe)
    assert [c.model_dump() for c in again.lore] == \
           [c.model_dump() for c in faceted.world.lore]
    assert [p.model_dump() for p in again.people] == \
           [p.model_dump() for p in faceted.world.people]


def test_facet_lore_composes_with_a_packs_own_rather_than_replacing_it() -> None:
    """The argument for putting the seam where the two lore sources already
    meet: a pack-shaped path could only have carried one of them."""
    from worldloom import packs
    from worldloom.retail import RetailWorld

    pack = packs.load("examples/packs/regional-insurer.json")
    claims = facets.resolve(listing="listed").claims
    authored = RetailWorld.from_pack(pack, seed=4242).build()
    both = replace(RetailWorld.from_pack(pack, seed=4242), lore_claims=claims).build()
    assert [c.assertion for c in both.lore[:len(authored.lore)]] == \
           [c.assertion for c in authored.lore]
    assert len(both.lore) == len(authored.lore) + 1


def test_unmet_no_longer_claims_a_facets_lore_is_out_of_reach() -> None:
    """It said "put them on a pack's `lore` and build with it". It is minted
    now, so ``unmet`` is back to meaning only what it says."""
    blueprint = sdk.retail().facets(listing="listed", governance="private_equity")
    assert blueprint.implied_lore
    assert not any("lore" in entry for entry in blueprint.unmet)
    assert blueprint.describe()["lore"] == ["listing:listed",
                                            "governance:private_equity"]


def test_a_faceted_field_disperses_over_one_key_space() -> None:
    """Blueprints carry different numbers of overrides, so a per-blueprint
    vector has a per-blueprint length and nothing compares to anything."""
    field = sdk.companies(sdk.retail(), "listing", "maturity", "margin_profile")
    picked = sdk.dispersed(field, 5)
    assert len({tuple(sorted(b.facet_choices.items())) for b in picked}) == 5
