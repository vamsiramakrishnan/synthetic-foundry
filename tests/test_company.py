"""A company, described once — and the refusals that make the description worth
writing.

Three properties are asserted here and they are the whole contract. That a
specification **composes** — every field lands in a seam that already existed,
and nothing new reaches a generator. That it **refuses** — a description that
contradicts itself comes back with the arithmetic, before a corpus exists. And
that it **replays** — everything a description decides survives
``recipe.rebuild``, because the recipe records consequences and not the
description.

The fourth thing tested is the one that is easiest to lose: a specification
must not be the thing that blocks a fourth vertical. Nothing in
``worldloom.company`` may name a vertical, so a domain registered from outside
this repository has to be describable the moment it registers — and there is a
test below that registers one and describes it.
"""

from __future__ import annotations

import json
from dataclasses import replace

import pytest

from worldloom import archetypes, company, domains, facets, packs, recipe, roles, sdk
from worldloom.parameters import DEFAULTS


# ---------------------------------------------------------------------------
# The document itself
# ---------------------------------------------------------------------------


def test_an_unknown_field_is_refused_naming_what_is_taken() -> None:
    """A spec with `margins` in it would otherwise build a perfectly ordinary
    company and give its author nothing to notice the drop by — the argument
    `Parameters.with_overrides` makes about a mistyped parameter, one layer up."""
    with pytest.raises(ValueError, match="unknown field"):
        company.from_document({"margins": [0.4, 0.6]})


def test_a_document_is_read_from_text_as_well_as_from_a_path(tmp_path) -> None:
    """Told apart by the first character, not by asking the filesystem: a whole
    specification is several hundred bytes and `Path(text).exists()` raises
    `File name too long` on one before it can answer."""
    document = json.dumps(company.template())
    path = tmp_path / "company.json"
    path.write_text(document, encoding="utf-8")
    assert company.from_document(document) == company.from_document(path)
    assert company.from_document(str(path)) == company.from_document(path)


def test_a_document_round_trips_through_its_own_serialisation() -> None:
    spec = company.from_document(company.template())
    assert company.from_document(spec.as_dict()) == spec


def test_the_template_is_a_description_somebody_would_actually_write() -> None:
    """A template of empty strings teaches the schema; this one teaches what the
    schema is for, so it has to resolve cleanly."""
    resolved = company.resolve(company.from_document(company.template()))
    assert resolved.ok, [str(c) for c in resolved.conflicts]


def test_the_schema_publishes_where_every_field_gets_its_values() -> None:
    published = company.describe()
    fields = {entry["field"] for entry in published["fields"]}
    assert fields == company._FIELDS
    for entry in published["fields"]:
        assert entry["about"].strip(), entry["field"]
        assert entry["kind"] in {"value", "range", "open"}


# ---------------------------------------------------------------------------
# Composition: every field lands in a seam that already existed
# ---------------------------------------------------------------------------


def test_a_description_resolves_only_into_seams_that_already_exist() -> None:
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer",
        "vocabulary": "department_house",
        "facets": {"listing": "listed", "maturity": "legacy"},
        "physics": {"retail.margin.budget": [0.44, 0.52]},
        "calendar": "retail_christmas",
        "estate": "medium",
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    # Physics names are the registry's, so `with_overrides` can accept them.
    assert set(resolved.physics) <= set(DEFAULTS)
    # The archetype key is the qualified form, which is what a recipe stores and
    # therefore what makes the *words* rebuild as well as the figures.
    assert resolved.archetype_key == "omnichannel_retailer+department_house"
    assert archetypes.get(resolved.archetype_key).units[0].name != "Food"
    assert resolved.calendar == "retail_christmas"
    assert resolved.estate == "medium"


def test_a_typed_range_beats_one_a_facet_only_implied() -> None:
    """A range somebody typed is a statement about this company; a range a facet
    implied is an inference from a claim about a kind of company."""
    resolved = company.resolve(company.from_document({
        "facets": {"margin_profile": "premium"},
        "physics": {"retail.margin.budget": [0.30, 0.33]},
    }))
    assert resolved.ok
    budget = resolved.physics["retail.margin.budget"]
    assert (budget.low, budget.high) == pytest.approx((0.30, 0.33))


def test_the_engine_keeps_its_own_titles_for_the_keys_it_ships() -> None:
    """`roles.from_shape` titles every role off a seniority ladder, which is
    right for a probe and throws away what this engine already knows: the
    controller is the Group Financial Controller, not "Director of Technology"
    because that is where the ladder happened to land."""
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer",
        "organisation": {"headcount": 24, "span": 5, "levels": 3},
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    titles = {key: title for key, title, _, _ in resolved.role_table}
    shipped = {key: title for key, title, _, _ in roles.to_rows(roles._shipped("retail"))}
    # Over the spine, because those are the keys `from_shape` places and
    # therefore the keys whose titles it would otherwise have overwritten.
    for key in roles.SPINE["retail"]:
        assert titles[key] == shipped[key], key
    # And the roles nobody named keep their ladder titles, which is the honest
    # signal that nobody has named them.
    assert any(key.startswith("role_") for key in titles)


def test_a_synthesised_organisation_uses_the_engines_own_functions() -> None:
    """An insurer runs Actuarial and Claims. The generic ladder would put a Head
    of Merchandising in its org chart on the strength of a list written for
    retail, and the engine already knows better."""
    resolved = company.resolve(company.from_document({
        "engine": "insurance", "organisation": {"headcount": 20, "span": 5, "levels": 3},
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    functions = {function for _, _, function, _ in resolved.role_table}
    assert "Actuarial" in functions and "Claims" in functions
    assert "Merchandising" not in functions


def test_leadership_is_appended_and_the_table_is_reviewed() -> None:
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer",
        "leadership": [{"key": "chief_customer", "title": "Chief Customer Officer",
                        "function": "Executive", "reports_to": "ceo"}],
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    assert ("chief_customer", "Chief Customer Officer", "Executive", "ceo") in resolved.role_table
    # Reviewed the way the resolver reviews it — with the per-unit roles the
    # generator appends standing in, because retail's `merch_lead` reports to a
    # `gm_md` that no authored table contains.
    units = [unit.key for unit in archetypes.get("omnichannel_retailer").units]
    have = {row[0] for row in resolved.role_table}
    stand_ins = [(key, key, "Executive", "ceo")
                 for key in roles.required("retail", units) if key not in have]
    assert not roles.review(roles.from_rows([*resolved.role_table, *stand_ins]),
                            engine="retail", unit_keys=units)


def test_a_leadership_row_reporting_to_nobody_real_is_refused() -> None:
    resolved = company.resolve(company.from_document({
        "leadership": [{"key": "chief_customer", "title": "Chief Customer Officer",
                        "function": "Executive", "reports_to": "grand_vizier"}],
    }))
    assert not resolved.ok
    assert any(c.rule == "unknown_manager" for c in resolved.conflicts)


def test_a_facet_role_still_reaches_the_table() -> None:
    """`listed` mints an audit committee chair because that is what listing
    means operationally; a description that recorded the claim without minting
    the role would be the carried-and-inert failure."""
    resolved = company.resolve(company.from_document({
        "facets": {"listing": "listed"},
        "organisation": {"headcount": 26, "span": 5, "levels": 3},
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    assert "audit_chair" in {row[0] for row in resolved.role_table}


# ---------------------------------------------------------------------------
# Refusal
# ---------------------------------------------------------------------------


def test_revenue_against_headcount_is_refused_with_both_numbers() -> None:
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer",
        "revenue": 40_000_000,
        "employees": 12,
    }))
    assert not resolved.ok
    conflict = next(c for c in resolved.conflicts if c.rule == "implausible_productivity")
    assert "40,000,000" in conflict.detail and "12" in conflict.detail
    assert "per head" in conflict.detail
    # Both anchors named, so the refusal is arguable rather than merely stated.
    assert "omnichannel_retailer" in conflict.detail


def test_the_productivity_envelope_is_derived_from_the_registry() -> None:
    """Not typed in. Every registered shape has to sit inside its own envelope,
    which is the property a constant could not promise: register a fifth
    archetype and this moves rather than becoming wrong."""
    envelope = company.productivity_envelope()
    assert envelope is not None
    low, high, low_key, high_key = envelope
    for key in archetypes.available():
        shape = archetypes.get(key)
        per_head = company._per_head(shape)
        if per_head is not None:
            assert low <= per_head <= high, key
    assert low_key in archetypes.available()
    assert high_key in archetypes.available()
    # And every registered shape is comfortably inside, because the envelope is
    # the registry's own extremes widened by the registry's own spread.
    assert low < company._per_head(archetypes.get(low_key))
    assert high > company._per_head(archetypes.get(high_key))


def test_an_ordinary_pair_of_numbers_is_not_refused() -> None:
    """The check has to let a real company through, or it is not a check — it is
    a ban on stating scale."""
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer", "revenue": 7_800_000, "employees": 80_000,
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]


def test_a_corpus_cannot_name_more_people_than_the_company_employs() -> None:
    resolved = company.resolve(company.from_document({
        "organisation": {"headcount": 40, "span": 5, "levels": 3},
        "employees": 12,
    }))
    assert not resolved.ok
    assert any(c.rule == "more_named_than_employed" for c in resolved.conflicts)


def test_contradictory_facets_are_refused_through_the_registry_itself() -> None:
    """Composed, not restated: the arithmetic is `facets.resolve`'s and this
    only has to carry it out."""
    resolved = company.resolve(company.from_document({
        "facets": {"listing": "mutual", "margin_profile": "premium"},
    }))
    assert not resolved.ok
    assert any("No company is both" in c.detail for c in resolved.conflicts)


def test_an_over_determined_organisation_is_refused_with_the_arithmetic() -> None:
    resolved = company.resolve(company.from_document({
        "organisation": {"headcount": 900, "span": 2, "levels": 2},
    }))
    assert not resolved.ok
    assert any(c.rule == "shape_does_not_hold" for c in resolved.conflicts)


def test_every_conflict_comes_back_at_once() -> None:
    """A describer who wrote three incompatible things should read three
    sentences, not three error messages one build at a time."""
    resolved = company.resolve(company.from_document({
        "geo": "atlantis",
        "calendar": "no_such_year",
        "estate": "enormous",
    }))
    assert {c.subject for c in resolved.conflicts} >= {"geo", "calendar", "estate"}


def test_a_pack_and_an_identity_together_are_refused() -> None:
    resolved = company.resolve(company.from_document({
        "pack": "examples/packs/regional-insurer.json",
        "identity": {"company_name": "Somebody Else"},
    }))
    assert not resolved.ok
    assert any(c.rule == "two_identities" for c in resolved.conflicts)


def test_an_unregistered_parameter_is_refused_at_the_document() -> None:
    """The closed half. A caller free to name an arbitrary parameter would be
    open exactly where code reads it."""
    resolved = company.resolve(company.from_document({
        "physics": {"retail.margin.budgt": [0.2, 0.3]},
    }))
    assert not resolved.ok
    assert any(c.rule == "unknown_parameter" for c in resolved.conflicts)


def test_an_unknown_registry_value_is_refused_rather_than_defaulted() -> None:
    """`germay` silently becoming Australia would build a corpus with nothing in
    it to notice the drop by."""
    resolved = company.resolve(company.from_document({"geo": "germay"}))
    assert not resolved.ok
    assert any(c.rule == "unknown_locale" for c in resolved.conflicts)


# ---------------------------------------------------------------------------
# What is reported rather than dropped
# ---------------------------------------------------------------------------


def test_a_trading_year_no_engine_can_carry_is_reported() -> None:
    """Only `RetailWorld` has a `seasonality` field, and every facet set settles
    `trading_pattern` at its registry default — so refusing here would make
    facets unusable on two engines over a claim nobody typed."""
    resolved = company.resolve(company.from_document({
        "engine": "insurance", "calendar": "harvest",
    }))
    assert resolved.ok
    assert resolved.calendar is None
    assert any("trading year" in want for want in resolved.unmet)


def test_a_margin_band_aimed_at_another_engine_is_reported() -> None:
    resolved = company.resolve(company.from_document({
        "engine": "banking", "physics": {"retail.margin.budget": [0.4, 0.5]},
    }))
    assert resolved.ok
    assert any("retail.margin.budget" in want for want in resolved.unmet)


def test_a_margin_band_no_unit_will_draw_from_is_reported() -> None:
    """The trap a describer saying "premium margins" falls into.
    `retail.margin.budget` is a *fallback*: a unit with categories takes the
    revenue-weighted blend of theirs, so on an archetype whose every unit has a
    book, the claim rides the recipe and every printed margin is unchanged."""
    resolved = company.resolve(company.from_document({
        "archetype": "omnichannel_retailer", "facets": {"margin_profile": "premium"},
    }))
    assert resolved.ok
    assert any("retail.margin.budget" in want for want in resolved.unmet)
    # And the claim is true: the figures really do not move.
    plain = sdk.retail().build().episodes("2026-03").world
    premium = sdk.described({"archetype": "omnichannel_retailer",
                             "facets": {"margin_profile": "premium",
                                        "trading_pattern": "christmas_peak"}}
                            ).build().episodes("2026-03").world
    kind = "financial.gross_margin_pct.budget"
    assert [f.value for f in plain.facts if f.kind == kind] == \
           [f.value for f in premium.facts if f.kind == kind]


def test_a_named_rival_is_reported_rather_than_accepted_silently() -> None:
    resolved = company.resolve(company.from_document({"rivals": ["Northgate Retail"]}))
    assert resolved.ok
    assert any("Northgate Retail" in want for want in resolved.unmet)


def test_a_facets_own_unmet_consequences_survive() -> None:
    resolved = company.resolve(company.from_document({"facets": {"listing": "listed"}}))
    assert any("analyst consensus" in want for want in resolved.unmet)


# ---------------------------------------------------------------------------
# Identity, and the geography only an identity can carry
# ---------------------------------------------------------------------------


def test_a_geo_without_an_identity_says_which_half_it_reached() -> None:
    resolved = company.resolve(company.from_document({"geo": "germany"}))
    assert resolved.ok
    assert resolved.locale == "germany"
    assert resolved.pack is None
    if "locale" not in company._carried_by(resolved.engine):
        assert any("build half" in want for want in resolved.unmet)


def test_an_identity_composes_a_pack_that_carries_the_geography() -> None:
    resolved = company.resolve(company.from_document({
        "industry": "General insurance",
        "geo": "germany",
        "identity": {"company_name": "Rheinmark Versicherung"},
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    assert isinstance(resolved.pack, packs.Pack)
    assert resolved.pack.company_name == "Rheinmark Versicherung"
    assert resolved.pack.currency == "EUR"
    assert resolved.pack.regions and resolved.pack.name_pools.given
    # The units are the resolved archetype's, so a composed pack is the shape the
    # description already asked for rather than a second guess at it.
    assert [u.key for u in resolved.pack.units] == [
        u.key for u in archetypes.get(resolved.archetype_key).units
    ]


def test_a_composed_pack_carries_no_lore() -> None:
    """Facet lore reaches a world through `lore_claims` and `world.extend_lore`,
    never through `Pack.lore` — that seam's docstring is the argument, and this
    is the assertion that composing a pack did not quietly move it."""
    resolved = company.resolve(company.from_document({
        "facets": {"listing": "listed"},
        "identity": {"company_name": "Rheinmark Versicherung"},
    }))
    assert resolved.pack is not None and not resolved.pack.lore
    assert [claim.source for claim in resolved.lore_claims] == ["listing:listed"]


def test_an_identity_with_no_company_name_is_refused() -> None:
    resolved = company.resolve(company.from_document({
        "identity": {"headquarters": "Munich, Germany"},
    }))
    assert not resolved.ok
    assert any(c.rule == "no_company_name" for c in resolved.conflicts)


def test_a_named_pack_wins_and_refuses_to_be_restated() -> None:
    resolved = company.resolve(company.from_document({
        "pack": "examples/packs/regional-insurer.json", "revenue": 999,
    }))
    assert not resolved.ok
    assert any(c.rule == "restated_by_the_spec" for c in resolved.conflicts)


def test_a_named_pack_supplies_the_shape_and_the_engine() -> None:
    resolved = company.resolve(company.from_document({
        "pack": "examples/packs/regional-insurer.json",
    }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    assert resolved.engine == "retail"
    assert resolved.pack.company_name == packs.load("examples/packs/regional-insurer.json").company_name


# ---------------------------------------------------------------------------
# The SDK entry point
# ---------------------------------------------------------------------------


def test_a_description_becomes_an_ordinary_blueprint() -> None:
    """The point of returning a `Blueprint` rather than a world: it can be
    crossed, swept and dispersed like any other."""
    blueprint = sdk.described({"archetype": "omnichannel_retailer",
                               "facets": {"maturity": "legacy"}})
    assert isinstance(blueprint, sdk.Blueprint)
    field = sdk.sweep(blueprint, "seeded", [1, 2, 3])
    assert len({b.seed for b in field}) == 3


def test_a_contradictory_description_is_refused_before_anything_is_built() -> None:
    with pytest.raises(ValueError, match="No company is both"):
        sdk.described({"facets": {"listing": "mutual", "margin_profile": "premium"}})
    # And a caller who would rather inspect than catch can say so.
    blueprint = sdk.described(
        {"facets": {"listing": "mutual", "margin_profile": "premium"}}, strict=False
    )
    assert isinstance(blueprint, sdk.Blueprint)


def test_a_described_world_builds_and_validates() -> None:
    built = sdk.described(company.template()).build().episodes("2026-03")
    assert built.ok
    assert built.world.company.name == "Rheinmark Versicherung"
    assert built.world.company.currency == "EUR"
    titles = {person.title for person in built.world.people}
    assert "Chief Underwriting Officer" in titles
    assert "Chair, Audit and Risk Committee" in titles


def test_scale_reaches_the_corpus_with_or_without_a_composed_pack() -> None:
    """Revenue and total workforce are load-bearing on both construction paths."""
    document = {"engine": "insurance", "revenue": 2_400, "employees": 4_200,
                "identity": {"company_name": "Rheinmark Versicherung"}}
    world = sdk.described(document).build().world
    assert world._annual_revenue == 2_400
    assert world.company.employees_total == 4_200

    pack_less = sdk.described({"engine": "insurance", "employees": 4_200})
    assert not any("stated headcount" in want for want in pack_less.unmet)
    assert pack_less.build().world.company.employees_total == 4_200


def test_revenue_reaches_the_money_facts() -> None:
    """The one scale field that is load-bearing on every path — which is why it
    is worth a blueprint field rather than being left to a pack."""
    plain = sdk.retail().build()
    richer = sdk.retail().revenue(15_600_000).build()
    assert plain.world._annual_revenue != richer.world._annual_revenue
    assert richer.world._annual_revenue == 15_600_000


# ---------------------------------------------------------------------------
# Replay
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("document", [
    company.template(),
    {"archetype": "omnichannel_retailer", "vocabulary": "department_house",
     "facets": {"listing": "listed", "maturity": "legacy",
                "trading_pattern": "christmas_peak"},
     "organisation": {"headcount": 26, "span": 5, "levels": 3},
     "revenue": 9_400_000},
    # The pack path with a trading year on it, which is the case that catches a
    # divergence nothing else would. `World.from_pack` puts the pack's year on
    # the builder and `build_recipe` records it, and `recipe.rebuild` hands the
    # recorded year to *every* episode — so a build that set it on the
    # organisation and not on the closes rebuilds into a different corpus and
    # reports success, because both of them validate.
    {"archetype": "omnichannel_retailer",
     "facets": {"trading_pattern": "christmas_peak"},
     "geo": "united_kingdom",
     "identity": {"company_name": "Halverton Stores plc"}},
])
def test_everything_a_description_decides_survives_a_rebuild(document) -> None:
    """The specification itself is never recorded — its consequences are, exactly
    as `--facet` records consequences rather than facet names. So this is the
    assertion that the consequences are enough."""
    world = sdk.described(document).build().episodes("2026-03").world
    again = recipe.rebuild(world.recipe)
    for name in ("people", "business_units", "sites", "categories", "lore",
                 "events", "facts"):
        assert [x.model_dump() for x in getattr(world, name)] == \
               [x.model_dump() for x in getattr(again, name)], name
    assert world.recipe == again.recipe


def test_a_corpus_replays_after_the_registry_moves_underneath_it() -> None:
    """The reason a recipe records consequences and not the description.

    A recipe that stored "a listed German insurer" — or even `listing=listed` —
    would replay whatever those words came to *mean* later, and report success
    while doing it. So: build a world, change what `listed` implies, rebuild
    from the recipe alone, and require the same company. This is the assertion
    `--facet` already earns and a specification has to earn again, because a
    specification names far more registries than a facet does.
    """
    world = sdk.described({
        "archetype": "omnichannel_retailer",
        "facets": {"listing": "listed", "trading_pattern": "christmas_peak"},
    }).build().episodes("2026-03").world

    listing = facets.FACETS["listing"]
    moved = replace(listing, options=tuple(
        option if option.value != "listed" else replace(
            option,
            implies=replace(option.implies, roles=(), calendar="harvest", lore=(),
                            asserts="", physics={"retail.margin.budget":
                                                 facets.Span(0.9, 0.95)}),
        )
        for option in listing.options
    ))
    facets.FACETS["listing"] = moved
    try:
        again = recipe.rebuild(world.recipe)
    finally:
        facets.FACETS["listing"] = listing

    assert [p.model_dump() for p in world.people] == [p.model_dump() for p in again.people]
    assert [f.model_dump() for f in world.facts] == [f.model_dump() for f in again.facts]
    assert world.recipe == again.recipe
    # And nothing in the recipe is the document itself.
    assert "spec" not in world.recipe and "facets" not in world.recipe


# ---------------------------------------------------------------------------
# A fourth vertical
# ---------------------------------------------------------------------------


def test_nothing_in_the_module_names_a_vertical() -> None:
    """The ratchet. Engines resolve through `domains`, archetypes through
    `archetypes`, roles through `roles.SPINE`, parameters through
    `parameters.DEFAULTS` — so a fourth vertical becomes describable the moment
    it registers, with no edit here. A literal vertical name in this module
    would be the thing that blocks it."""
    import tokenize
    from pathlib import Path

    source = Path("src/worldloom/company.py")
    with source.open("rb") as handle:
        code = "".join(
            token.string
            for token in tokenize.tokenize(handle.readline)
            if token.type not in {tokenize.COMMENT, tokenize.STRING}
        )
    for vertical in ("banking", "insurance", "midsize_adi",
                     "midsize_general_insurer", "australian_grocery"):
        assert vertical not in code, vertical


def test_a_pack_makes_an_unregistered_industry_describable() -> None:
    """"Any kind of company in any kind of geo" has to include an industry this
    repository has never heard of. A pack whose base names a registered engine
    is the route that needs no archetype registration at all, and a
    specification must not be what blocks it."""
    freight = {
        "name": "orbital-freight", "base": "retail",
        "company_name": "Kestrel Freight Holdings",
        "industry": "Contract logistics and freight forwarding",
        "annual_revenue": 2_400_000, "employees": 9_000,
        "units": [
            {"key": "linehaul", "name": "Linehaul", "kind": "supermarkets",
             "share": 0.62,
             "categories": [{"name": "Domestic Linehaul", "share": 0.7, "margin": 0.11},
                            {"name": "Cross-Border", "share": 0.3, "margin": 0.17}],
             "site_formats": [{"name": "Freight Terminal", "count": 24}]},
            {"key": "contract", "name": "Contract Logistics",
             "kind": "general_merchandise", "share": 0.38,
             "categories": [{"name": "Warehousing", "share": 0.55, "margin": 0.21},
                            {"name": "Fulfilment", "share": 0.45, "margin": 0.13}],
             "site_formats": [{"name": "Distribution Hub", "count": 11}]},
        ],
    }
    import tempfile
    from pathlib import Path

    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory) / "freight.json"
        path.write_text(json.dumps(freight), encoding="utf-8")
        resolved = company.resolve(company.from_document({
            "pack": str(path),
            "facets": {"competition": "fragmented", "maturity": "legacy"},
            "geo": "united_kingdom",
        }))
    assert resolved.ok, [str(c) for c in resolved.conflicts]
    built = sdk.from_resolution(resolved).build()
    assert built.world.company.name == "Kestrel Freight Holdings"
    assert [u.name for u in built.world.business_units] == ["Linehaul", "Contract Logistics"]


def test_a_domain_registered_from_outside_is_describable_at_once() -> None:
    """The stronger version of the same claim: a vertical this module has never
    seen, registered at runtime, resolves without an edit here."""
    from worldloom.retail import RetailWorld

    shape = replace(archetypes.get("omnichannel_retailer"), key="tidewater_ferries")
    archetypes._REGISTRY[shape.key] = shape
    domain = domains.Domain(
        name="ferries", archetype_keys=frozenset({shape.key}),
        world=RetailWorld, default_archetype=shape.key,
        role_keys=("ceo",), unit_role_suffixes=("_md",),
    )
    try:
        domains.register_domain(domain)
        resolved = company.resolve(company.from_document({"engine": "ferries"}))
        assert resolved.ok, [str(c) for c in resolved.conflicts]
        assert resolved.archetype_key == "tidewater_ferries"
        assert resolved.engine == "ferries"
        # And an organisation is refused *by name* rather than crashing, because
        # this vertical declared no spine for its generators' own lookups.
        shaped = company.resolve(company.from_document({
            "engine": "ferries", "organisation": {"headcount": 20, "span": 4, "levels": 3},
        }))
        assert any(c.rule == "no_spine_for_engine" for c in shaped.conflicts)
    finally:
        domains._DOMAINS.pop("ferries", None)
        archetypes._REGISTRY.pop(shape.key, None)


# ---------------------------------------------------------------------------
# The shared default nobody should have two copies of
# ---------------------------------------------------------------------------


def test_the_function_ladder_has_exactly_one_definition_between_here_and_the_sdk() -> None:
    assert sdk._FUNCTIONS is company.FUNCTIONS
