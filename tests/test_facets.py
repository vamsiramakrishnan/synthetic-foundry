"""Facets: claims with consequences, and the ones that cannot hold together."""

from __future__ import annotations

import math

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


def test_a_faceted_field_disperses_over_one_key_space() -> None:
    """Blueprints carry different numbers of overrides, so a per-blueprint
    vector has a per-blueprint length and nothing compares to anything."""
    field = sdk.companies(sdk.retail(), "listing", "maturity", "margin_profile")
    picked = sdk.dispersed(field, 5)
    assert len({tuple(sorted(b.facet_choices.items())) for b in picked}) == 5
