"""The dimensions a company is cut along: does industry actually decide shape?

The module's claim is that a company's dimensions become a function of the
company. A test suite that only checked the declarations round-trip would pass
on a lookup table with extra steps, so the load-bearing tests here are the two
that could fail on a real design mistake: **the resolution discriminates**
(§ "discrimination"), and **the library is honest about what nothing populates**
(§ "the honesty rule"). The rest hold the bridges into the grammars this module
is required to reuse rather than reinvent.
"""

from __future__ import annotations

from itertools import combinations

import pytest

from worldloom import archetypes, axes, factkinds
from worldloom.episodes import CohortSpec, FactKindSpec, Invariant
from worldloom.generators import hierarchy
from worldloom.ids import Minter
from worldloom.rng import Rng

#: The four shipped verticals, one archetype each. `australian_grocery` and
#: `customer_owned_bank` are second archetypes of two of these verticals and are
#: used below for the two questions they are the only way to ask: whether scale
#: changes shape, and whether two companies in one industry can differ.
FOUR = (
    "omnichannel_retailer",
    "midsize_adi",
    "midsize_general_insurer",
    "midsize_infrastructure_services",
)


def shape(key: str) -> axes.Shape:
    return axes.for_company(archetypes.get(key))


# ---------------------------------------------------------------------------
# The measured defect this module exists for
# ---------------------------------------------------------------------------


def test_the_declared_schema_cuts_every_shipped_company_identically():
    """The defect, asserted rather than described.

    `archetypes.UnitSpec` is `(key, name, kind, share, categories,
    site_formats)` for all six archetypes, so every company the engine builds is
    cut unit → category → site format whatever industry it is in. If this ever
    fails, `archetypes.py` grew a per-industry dimension and this module's
    premise needs re-reading before its library does.
    """
    shapes = {
        key: (
            tuple(sorted({"categories" for unit in archetypes.get(key).units if unit.categories}))
            + tuple(sorted({"site_formats" for unit in archetypes.get(key).units
                            if unit.site_formats}))
        )
        for key in archetypes.available()
    }
    assert len(set(shapes.values())) == 1, shapes


def test_an_empty_tuple_is_where_the_schema_says_it_is_the_wrong_schema():
    """Two units carry no categories and four carry no site formats.

    Pinned because it is the evidence for `applies_to`: an empty tuple is the
    only way `UnitSpec` can say "this line of business is not cut that way", and
    it is indistinguishable from "cut that way, into zero members".
    """
    units = [unit for key in archetypes.available() for unit in archetypes.get(key).units]
    assert len(units) == 19
    assert sum(1 for unit in units if not unit.categories) == 2
    assert sum(1 for unit in units if not unit.site_formats) == 4


def test_the_legacy_shape_is_what_the_engine_actually_does():
    """`LEGACY` describes today's build, so an undeclared industry is described
    as it is rather than as somebody's idea of it."""
    assert axes.LEGACY.names() == ("unit", "category", "format", "site", "region")
    assert axes.LEGACY.declared is False
    assert axes.lint(axes.LEGACY) == []


# ---------------------------------------------------------------------------
# Discrimination — the headline
# ---------------------------------------------------------------------------


def test_the_four_verticals_resolve_to_four_different_shapes():
    """By *name*, which is the vocabulary reading."""
    named = {key: shape(key).names() for key in FOUR}
    assert len(set(named.values())) == 4, named


def test_the_four_verticals_differ_structurally_and_not_only_in_words():
    """By *signature*, which strips the names out.

    The reading that matters. Calling a bank's second cut a "portfolio" and a
    grocer's a "category" is a thesaurus, not a design — `Shape.signature`
    removes the words and compares source, parent source, roll-up invariant and
    whether anything populates the axis. Every pair still differs, so the
    discrimination survives having its vocabulary taken away.
    """
    for a, b in combinations(FOUR, 2):
        left, right = set(shape(a).signature()), set(shape(b).signature())
        assert left != right, f"{a} and {b} are cut the same way in different words"
        # Four is the smallest structural gap between any two of the four (the
        # bank and the insurer, and the bank and the contractor). Pinned so a
        # future edit that quietly collapses two verticals toward each other
        # fails here rather than in a report.
        assert len(left ^ right) >= 4, (a, b, sorted(left ^ right))


def test_every_vertical_differs_structurally_from_the_shape_the_engine_performs():
    """If a declared shape had the same signature as `LEGACY`, declaring it
    bought nothing — the company would be cut exactly as it is today."""
    legacy = set(axes.LEGACY.signature())
    for key in FOUR:
        assert set(shape(key).signature()) != legacy, key


def test_two_banks_in_one_industry_differ_by_their_lines_of_business():
    """The reason resolution is two-stage rather than an industry lookup.

    `midsize_adi` and `customer_owned_bank` are both `industry="Banking"`, so
    anything keyed on the industry string alone hands them the same answer while
    one runs a trading book and the other runs a financial-advice business. The
    trading book brings a maturity-bucket axis; the wealth arm does not.
    """
    adi, mutual = shape("midsize_adi"), shape("customer_owned_bank")
    assert archetypes.get("midsize_adi").industry == archetypes.get(
        "customer_owned_bank").industry == "Banking"
    # Each brings its own. The `service_line` half of this arrived when
    # `hierarchy.generate` started consuming the shape and refused to build the
    # mutual: the wealth arm carries two categories and no axis cut them, so the
    # declaration had been saying a financial-advice business is cut by nothing
    # below the book. Before that the mutual's difference from the ADI was
    # purely an absence, which is the weaker of the two readings.
    assert set(adi.names()) ^ set(mutual.names()) == {"maturity_bucket", "service_line"}
    assert "service_line" in mutual.names()


def test_scale_does_not_change_shape():
    """The two retail archetypes resolve identically, and that is correct.

    `australian_grocery` is `omnichannel_retailer` at nine times the revenue and
    the same lines of business. A resolver that returned different *dimensions*
    for the same business at a different size would be encoding size as shape,
    which is the failure this module is a reaction to in the other direction.
    """
    big, small = shape("australian_grocery"), shape("omnichannel_retailer")
    assert big.names() == small.names()
    assert big.signature() == small.signature()


def test_an_unregistered_industry_gets_the_legacy_shape_and_says_so():
    """A pack may name any industry. The honest answer for one nobody has
    described is "cut the way the engine cuts everything" — flagged, so a caller
    cannot publish it as a declared shape."""
    made_up = archetypes.Archetype(
        key="k", label="l", industry="Deep sea salvage",
        units=archetypes.get("omnichannel_retailer").units,
    )
    resolved = axes.for_company(made_up)
    assert resolved.declared is False
    assert resolved.names() == axes.LEGACY.names()


# ---------------------------------------------------------------------------
# `applies_to` — the empty tuple's replacement
# ---------------------------------------------------------------------------


def test_a_treasury_desk_is_cut_by_something_rather_than_by_nothing():
    """`UnitSpec` says a treasury desk has no categories and no branches.

    That reads as "this desk has zero dimensions" and means "this desk is cut a
    different way". The declared shape says which way.
    """
    assert [axis.name for axis in axes.LEGACY.for_line("treasury")] == list(
        axes.LEGACY.names()
    )  # LEGACY cuts a treasury desk exactly as it cuts a supermarket
    assert [axis.name for axis in shape("midsize_adi").for_line("treasury")] == [
        "book", "maturity_bucket",
    ]


def test_an_investment_book_is_cut_by_asset_class():
    """The insurer's other empty tuple, answered the same way."""
    assert [axis.name for axis in shape("midsize_general_insurer").for_line(
        "investments")] == ["segment", "asset_class"]


def test_an_axis_no_line_of_business_carries_is_not_one_of_the_companys_axes():
    """Resolution's second stage. The mutual has no treasury desk, so it has no
    maturity buckets — computed, not declared per archetype."""
    assert "maturity_bucket" not in shape("customer_owned_bank").names()
    assert "maturity_bucket" in shape("midsize_adi").names()


# ---------------------------------------------------------------------------
# The honesty rule — `probe.MEASURES`' comment, one layer along
# ---------------------------------------------------------------------------


def test_the_library_partitions_into_populated_and_not_and_reports_both():
    library = axes.library()
    populated = [axis for axis in library if axis.populated]
    gaps = [axis for axis in library if not axis.populated]
    # 35/24/11 when the library was declared and nothing read it. The
    # twenty-fifth populated axis is `service_line`, which the first consumer
    # required; the eleven gaps are unmoved, because consuming a shape closes no
    # gap — it only makes the engine say, per build, which ones it did not cut.
    assert len(library) == 36
    assert len(populated) == 25
    assert len(gaps) == 11
    # Every gap names the axis it is, and none of them pretends to a generator.
    assert all(axis.populated_by == "" for axis in gaps)
    assert all(axis.populated_by for axis in populated)


def test_every_unpopulated_axis_is_reported_by_lint():
    """A dimension nothing generates members for is the *carried, cited, and
    inert* failure arriving at the dimension instead of the figure. It may be
    declared — naming the gap is the deliverable — but it may not be quiet."""
    for industry in axes.declared():
        resolved = axes.for_company(_an_archetype_in(industry))
        reported = {
            axis.name for axis in resolved.unpopulated
            if any(f"({axis.name!r})" in finding and "nothing populates" in finding
                   for finding in axes.lint(resolved))
        }
        assert reported == {axis.name for axis in resolved.unpopulated}, industry


def test_every_populated_axis_names_a_module_a_reader_can_open():
    from pathlib import Path

    root = Path(__file__).resolve().parent.parent / "src" / "worldloom"
    for axis in axes.library():
        if axis.populated:
            assert (root / axis.populated_by).exists(), (axis.name, axis.populated_by)


def test_no_declared_shape_has_a_finding_other_than_a_named_gap():
    """The shipped library is clean apart from the gaps it is honest about."""
    for industry in axes.declared():
        findings = axes.lint(axes.for_company(_an_archetype_in(industry)))
        assert [f for f in findings if "nothing populates" not in f] == [], industry


def _an_archetype_in(industry: str) -> archetypes.Archetype:
    for key in archetypes.available():
        candidate = archetypes.get(key)
        if candidate.industry == industry:
            return candidate
    raise AssertionError(f"no archetype in {industry!r}")


# ---------------------------------------------------------------------------
# The grammars this module is required to reuse
# ---------------------------------------------------------------------------


def test_the_accident_quarter_axis_is_the_cohort_spec_the_engine_already_runs():
    """Not a copy of the insurer's four numbers — the same value.

    `examples/packs/longtail-insurer.json` declares `{"name":
    "accident_quarter", "count": 4, "spacing_months": 3, "lag_months": 3}` and
    `generators/reserving.COHORT_COUNT` is 4. If those move and this does not,
    the axis library would be describing a triangle the engine does not build.
    """
    from worldloom.generators import reserving

    (spec,) = axes.as_cohorts(shape("midsize_general_insurer"))
    assert spec == CohortSpec(
        name="accident_quarter", count=4, spacing_months=3, lag_months=3
    )
    assert spec.count == reserving.COHORT_COUNT


def test_a_cohort_axis_hands_the_episode_grammar_a_spec_it_can_run():
    """`as_cohorts` output is directly usable as an `EpisodeSpec.cohorts` entry —
    which is the whole reason the axis carries the spec rather than three ints."""
    (spec,) = axes.as_cohorts(shape("midsize_general_insurer"))
    from worldloom.episodes import cohort_periods

    assert cohort_periods("2026-03", spec) == ("2025-03", "2025-06", "2025-09", "2025-12")


def test_the_roll_up_is_emitted_as_an_invariant_in_the_closed_vocabulary():
    subject = shape("midsize_general_insurer")
    across_subjects = axes.as_invariant(subject.get("segment"), "financial.revenue.actual")
    across_cohorts = axes.as_invariant(
        subject.get("accident_quarter"), "reserves.ultimate"
    )
    assert isinstance(across_subjects, Invariant)
    assert across_subjects.kind == "sums-to"
    assert across_cohorts.kind == "rolls-up-to"
    assert {across_subjects.kind, across_cohorts.kind} <= factkinds.INVARIANT_HEADS


def test_an_axis_that_does_not_decompose_emits_no_invariant():
    """Rather than an invariant with no operands, which would be a declared
    check that passes on everything."""
    assert axes.as_invariant(
        shape("midsize_general_insurer").get("valuation"), "reserves.ultimate"
    ) is None


def test_subject_types_are_read_off_the_fact_grammar_rather_than_retyped():
    assert axes.SUBJECT_TYPES == frozenset(
        {"company", "unit", "category", "person", "system", "any"}
    )
    for axis in axes.library():
        assert axis.subject_type in axes.SUBJECT_TYPES
        FactKindSpec(
            kind="probe.check", value_type="money",
            subject_type=axis.subject_type,  # type: ignore[arg-type]
            invariants=[Invariant(kind="holds-at")],
        )


def test_the_fact_grammar_has_no_subject_type_for_a_site_or_a_region():
    """Recorded as a finding, not asserted as correct.

    `generators/finance.py` mints `financial.revenue.actual` against `Site.id`
    on every build and `FactKindSpec.subject_type` has no `site` — so both site
    axes fall through to `any`. Pinned here so that adding one to the Literal
    breaks this test and the axes get updated with it.
    """
    assert "site" not in axes.SUBJECT_TYPES
    assert "region" not in axes.SUBJECT_TYPES
    for name in ("site", "region"):
        assert axes.LEGACY.get(name).subject_type == "any"


# ---------------------------------------------------------------------------
# Structure
# ---------------------------------------------------------------------------


def test_retail_nests_a_store_inside_a_format_inside_a_division():
    """Three levels where `UnitSpec` can only say two.

    `hierarchy.generate` really does mint `SiteFormat.count` sites inside each
    format and stamps `Site.format` on every one of them; the schema flattens
    that into one field called `site_formats`.
    """
    retail = shape("omnichannel_retailer")
    assert retail.chain("store") == ("division", "format", "store")
    assert retail.depth() == 4  # ... and `region` hangs off the store


def test_the_nesting_chain_of_every_declared_axis_reaches_a_root():
    for industry in axes.declared():
        resolved = axes.for_company(_an_archetype_in(industry))
        for name in resolved.names():
            chain = resolved.chain(name)
            assert chain[-1] == name
            assert resolved.get(chain[0]).nests_under == "", (industry, name, chain)


# ---------------------------------------------------------------------------
# The lint's own findings
# ---------------------------------------------------------------------------


def _axis(name: str, **kwargs: object) -> axes.Axis:
    base: dict[str, object] = {
        "label": name.title(), "source": "units",
        "populated_by": "generators/hierarchy.py",
    }
    base.update(kwargs)
    return axes.Axis(name=name, **base)  # type: ignore[arg-type]


def test_lint_catches_a_cohort_axis_that_would_pass_vacuously():
    """`sums-to` on a grid looks for the breakdown across subjects, finds no
    children, and succeeds having compared nothing — `episodes.Invariant`'s own
    warning, made checkable."""
    findings = axes.lint([_axis(
        "vintage", source="cohort", rollup="sums-to",
        cohort=CohortSpec(name="vintage", count=4, spacing_months=3, lag_months=3),
    )])
    assert any("pass having compared nothing" in f for f in findings)


def test_lint_catches_a_grid_roll_up_with_no_grid():
    findings = axes.lint([_axis("vintage", rollup="rolls-up-to")])
    assert any("there is no grid here" in f for f in findings)


def test_lint_catches_a_cohort_source_with_no_spec():
    findings = axes.lint([_axis("vintage", source="cohort", rollup="rolls-up-to")])
    assert any("no `CohortSpec` is carried" in f for f in findings)


def test_lint_allows_a_stated_grid_geometry_on_an_axis_nothing_populates():
    """A gap named precisely is worth more than a gap gestured at: the generator
    that closes it needs the three numbers and nowhere else holds them."""
    findings = axes.lint([axes.Axis(
        name="vintage", label="Vintage", source="none", rollup="rolls-up-to",
        cohort=CohortSpec(name="vintage", count=8, spacing_months=3, lag_months=3),
    )])
    assert [f for f in findings if "nothing populates" not in f] == []


def test_lint_catches_a_cohort_spec_addressed_by_a_different_name():
    findings = axes.lint([_axis(
        "vintage", source="cohort", rollup="rolls-up-to",
        cohort=CohortSpec(name="origination", count=4, spacing_months=3, lag_months=3),
    )])
    assert any("addresses an axis by that name" in f for f in findings)


def test_lint_catches_a_line_of_business_no_registry_declares():
    findings = axes.lint([_axis("book", applies_to=frozenset({"retail_bankinng"}))])
    assert any("silently never resolves" in f for f in findings)
    # ... and does not fire on one that does.
    assert axes.lint([_axis("book", applies_to=frozenset({"retail_banking"}))]) == []


def test_lint_catches_a_broken_and_a_circular_nesting():
    assert any("does not declare" in f for f in axes.lint([_axis("a", nests_under="b")]))
    assert any("nests inside itself" in f for f in axes.lint([
        _axis("a", nests_under="b"), _axis("b", nests_under="a"),
    ]))


def test_lint_catches_a_share_of_something_that_holds_no_shares():
    findings = axes.lint([
        _axis("valuation", rollup=""), _axis("cell", nests_under="valuation"),
    ])
    assert any("subtotal with no total" in f for f in findings)


def test_lint_catches_a_child_cutting_lines_its_parent_does_not():
    findings = axes.lint([
        _axis("book", applies_to=frozenset({"retail_banking"})),
        _axis("branch", nests_under="book",
              applies_to=frozenset({"retail_banking", "treasury"})),
    ])
    assert any("its parent 'book' does not" in f for f in findings)


def test_lint_catches_a_source_with_no_module_and_an_invented_invariant():
    assert any("`populated_by` is empty" in f
               for f in axes.lint([axes.Axis(name="a", label="A", source="units")]))
    assert any("closed invariant vocabulary" in f
               for f in axes.lint([_axis("a", rollup="averages-to")]))


def test_lint_catches_a_subject_type_the_fact_grammar_does_not_have():
    findings = axes.lint([_axis("a", subject_type="site")])
    assert any("is not one the fact grammar has" in f for f in findings)


# ---------------------------------------------------------------------------
# Registry posture and determinism
# ---------------------------------------------------------------------------


def test_a_duplicate_axis_name_is_refused_at_construction():
    with pytest.raises(ValueError, match="twice"):
        axes.Shape(industry="x", axes=(_axis("a"), _axis("a")))


def test_re_registering_an_identical_shape_is_a_harmless_reload():
    """`factkinds.register`'s posture: a module reload must not raise."""
    before = axes.declared()
    axes.register(axes.shape_of("Banking"))
    assert axes.declared() == before


def test_a_different_shape_under_a_known_industry_is_refused():
    """A lint whose verdict depended on import order is worse than no lint."""
    with pytest.raises(ValueError, match="already declares a shape"):
        axes.register(axes.Shape(industry="Banking", axes=(_axis("something_else"),)))
    assert axes.shape_of("Banking").names()[0] == "book"


def test_the_declaration_and_the_resolution_are_different_readings():
    """`shape_of` is what the industry declares; `for_company` is what one
    company keeps. The mutual drops an axis the declaration carries."""
    declaration = axes.shape_of("Banking")
    assert "maturity_bucket" in declaration.names()
    assert "maturity_bucket" not in shape("customer_owned_bank").names()


def test_resolution_is_deterministic_and_never_iterates_a_frozenset():
    """`applies_to` is a `frozenset`, whose iteration order is not stable across
    processes. Resolution filters *declaration-ordered* axes by membership, so
    the order out is the order declared — asserted by repetition here and by the
    literal expectations above."""
    for key in FOUR:
        assert shape(key).names() == shape(key).names()
    assert shape("midsize_general_insurer").names() == (
        "segment", "class_of_business", "office", "region", "accident_quarter",
        "valuation", "peril", "reinsurance_layer", "asset_class",
    )


def test_the_library_is_ordered_by_industry_and_deduplicated_by_value():
    """Two industries share the retail axes, and the library lists each once —
    by value, so re-typing an axis instead of sharing it would show up."""
    library = axes.library()
    assert len(library) == len(set(library))
    assert library[:5] == axes.LEGACY.axes


# ---------------------------------------------------------------------------
# Consumption — does the declaration reach the build
#
# The section that decides whether the module above is a description or a
# capability. `hierarchy.generate` takes an optional `shape`; if passing one
# produced the same `Dimensions` for every shipped archetype, a parameter would
# have been added and nothing else. So these tests measure the difference, name
# the archetypes where there is none and why, and pin the four refusals — which
# are the load-bearing half, because a shape may drop no member a company
# declares.
# ---------------------------------------------------------------------------


def _cut(key: str, shaped: bool = True) -> hierarchy.Dimensions:
    """Run `hierarchy.generate` for an archetype, with or without its shape.

    Ids are handed in rather than minted from an organisation, for `plan`'s own
    reason: the cut is settled from `UnitSpec` alone, so measuring it needs no
    world. Same rng seed and same minter sequence on both sides, so any
    difference is the shape's.
    """
    archetype = archetypes.get(key)
    unit_ids = {unit.key: f"BU-{i:03d}" for i, unit in enumerate(archetype.units)}
    return hierarchy.generate(
        Rng(8128).derive("hierarchy"), Minter(),
        units=archetype.units, unit_ids=unit_ids, buyers=unit_ids,
        shape=axes.for_company(archetype) if shaped else None,
    )


def test_no_shape_is_the_cut_the_engine_has_always_performed():
    """`None` is not "some default shape" — it is the five-axis cut, unchanged.

    Every corpus this repository has built was cut that way, so the parameter
    has to be a strict no-op when absent. The whole-corpus proof is a build
    diff; this is the same claim at the generator.
    """
    for key in archetypes.available():
        assert _cut(key, shaped=False).gaps == ()


def test_the_declared_shape_changes_three_of_the_four_verticals():
    """The measurement that says this is a capability rather than a parameter.

    Retail is the one that does *not* move, and that is the correct answer
    rather than a hole: `LEGACY` is a grocer's cut written down, and the retail
    shape declares the same nesting — division → format → store — so a shape
    faithful to the engine must reproduce it byte for byte. The other three all
    declare their site axis directly under the unit, and say why in the axis's
    own `about`: an operations centre is not a smaller branch, a claims centre
    is not a smaller branch, a materials yard is not a smaller depot.
    """
    moved = {}
    for key in archetypes.available():
        plain, shaped = _cut(key, shaped=False), _cut(key)
        assert len(plain.sites) == len(shaped.sites), key
        assert len(plain.categories) == len(shaped.categories), key
        moved[key] = sum(
            1 for before, after in zip(plain.sites, shaped.sites)
            if (before.name, before.region) != (after.name, after.region)
        )
    assert moved == {
        # Cut by format, as the engine always was.
        "australian_grocery": 0,
        "omnichannel_retailer": 0,
        # Not cut by format: the estate is one sequence under the book, so
        # every site after the first format takes a different ordinal and a
        # different point in the region cycle.
        "customer_owned_bank": 1,           # the operations centre
        "midsize_adi": 1,                   # the operations centre
        "midsize_general_insurer": 3,       # three claims centres
        "midsize_infrastructure_services": 17,  # 12 project offices, 5 yards
    }


def test_a_bank_numbers_its_estate_by_book_and_a_grocer_by_format():
    """The difference above, read as the sentence it is.

    A bank's single operations centre is the 119th site of its retail book, not
    the first site of a format of one — and it is placed where the region cycle
    had reached rather than always at the head of the pool, which is what made
    every non-retail company's odd formats pile into the first region.
    """
    adi = {site.id: site for site in _cut("midsize_adi").sites}
    centre = next(s for s in adi.values() if s.format == "Operations Centre")
    assert centre.name == "Operations Centre ACT 119"
    assert next(s for s in _cut("midsize_adi", shaped=False).sites
                if s.format == "Operations Centre").name == "Operations Centre NSW 001"

    store = next(s for s in _cut("australian_grocery").sites if s.format == "Metro")
    assert store.name == "Metro NSW 001"  # a format is a cut here, so it restarts


def test_the_cut_names_the_axes_it_did_not_perform():
    """"Not an empty dimension" — the contractor's `project` axis mints no
    members and is not silently absent either."""
    assert _cut("midsize_infrastructure_services").gaps == (
        "project", "contract_type", "project_vintage",
    )
    # Two kinds of absence, and the insurer carries both. `peril` and
    # `asset_class` are gaps in the engine; `accident_quarter` and `valuation`
    # are populated — by `generators/triangles.py` and `generators/reserving.py`
    # — and are listed because *this* generator did not cut them, which is how a
    # reader learns the company has a dimension from somewhere else.
    insurer = _cut("midsize_general_insurer")
    resolved = shape("midsize_general_insurer")
    assert insurer.gaps == (
        "accident_quarter", "valuation", "peril", "reinsurance_layer", "asset_class",
    )
    assert {axis.name for axis in resolved.unpopulated} < set(insurer.gaps)


def test_a_shape_may_not_drop_a_member_the_company_declares():
    """The refusal that paid for the exercise.

    Silently dropping a unit's categories removes every fact, document and
    question they own and reports success — the failure mode `validate`'s "fewer
    compiled documents than the plan asked for" exists for, one layer earlier.
    So the shape that omits the mutual's wealth arm raises, naming the members.
    """
    mutual = archetypes.get("customer_owned_bank")
    without = axes.Shape(
        industry="Banking",
        axes=tuple(a for a in axes.for_company(mutual).axes if a.name != "service_line"),
    )
    with pytest.raises(ValueError, match="Financial Advice"):
        hierarchy.plan(mutual.units, without)


def test_a_shape_may_not_drop_an_estate_either():
    grocer = archetypes.get("omnichannel_retailer")
    without = axes.Shape(
        industry="Omnichannel retail",
        axes=tuple(a for a in axes.for_company(grocer).axes
                   if a.name not in ("store", "region", "comparability")),
    )
    with pytest.raises(ValueError, match="cuts that line of business by site"):
        hierarchy.plan(grocer.units, without)


def test_a_site_with_no_region_is_refused_rather_than_placed_nowhere():
    """`models.Site.region` is required, so this is a shape the thin waist has
    no entity for. Named, rather than filled in with an empty string that would
    render as a site nobody can place — one of the answers to "what would a
    non-three-axis company break downstream"."""
    grocer = archetypes.get("omnichannel_retailer")
    without = axes.Shape(
        industry="Omnichannel retail",
        axes=tuple(a for a in axes.for_company(grocer).axes if a.name != "region"),
    )
    with pytest.raises(ValueError, match="cut by site and not by region"):
        hierarchy.plan(grocer.units, without)


def test_an_axis_claiming_this_generator_for_a_source_it_cannot_mint_is_refused():
    """`populated_by` is documentation and not dispatch, so nothing keeps it
    honest but this. An axis naming `hierarchy.py` while sourcing its members
    from the roster is a cut the library promises and nobody performs."""
    grocer = archetypes.get("omnichannel_retailer")
    wrong = axes.Shape(industry="Omnichannel retail", axes=(
        *axes.for_company(grocer).axes,
        _axis("headcount", source="roster", populated_by="generators/hierarchy.py",
              nests_under="division"),
    ))
    with pytest.raises(ValueError, match="no branch for"):
        hierarchy.plan(grocer.units, wrong)


def test_two_axes_on_one_source_are_refused_rather_than_ordered():
    """Both name the same member set, and which one the cut is reported under
    would depend on declaration order."""
    grocer = archetypes.get("omnichannel_retailer")
    twice = axes.Shape(industry="Omnichannel retail", axes=(
        *axes.for_company(grocer).axes,
        _axis("subcategory", source="categories",
              populated_by="generators/hierarchy.py", nests_under="division",
              subject_type="category"),
    ))
    with pytest.raises(ValueError, match="axes drawing on 'categories'"):
        hierarchy.plan(grocer.units, twice)


def test_a_gap_is_reported_and_never_refused():
    """Every shipped shape names axes nothing populates — eleven of thirty-six,
    by design, each already reported by `lint`. Raising on one would refuse all
    four verticals, so the parameter would be unusable on every company this
    repository ships. `plan` accepts them and `Cut.gaps` names them."""
    for key in archetypes.available():
        archetype = archetypes.get(key)
        resolved = axes.for_company(archetype)
        assert resolved.unpopulated, key  # every vertical declares at least one
        cut = hierarchy.plan(archetype.units, resolved)
        assert {axis.name for axis in resolved.unpopulated} <= set(cut.gaps), key


def test_every_member_the_registry_declares_is_cut_by_a_populated_axis():
    """The check `lint` cannot make, and the one that found `service_line` and
    the insurer's two missing classes of business.

    `lint` asserts that every line of business an axis *names* exists; nothing
    asserted the reverse, so a line no axis named was described as uncut — and,
    once anything consumed the shape, refused. Division pools are included
    because a widened company's extra divisions reach the same generator, and
    both holes were in a pool: `POOLS['Banking']` ships a wealth division and
    `POOLS['General insurance']` ships specialty and health.

    Members, not lines. A treasury desk declares no categories and no estate and
    is cut below the book by `maturity_bucket` alone, which nothing populates —
    that is a stated gap and not a hole, and asserting on lines rather than on
    declared members would have to call it one.
    """
    from worldloom import divisions

    for industry in axes.declared():
        declaration = axes.shape_of(industry)
        units = (*_an_archetype_in(industry).units, *divisions.POOLS.get(industry, ()))
        for unit in units:
            # `sites` rather than `site_formats` for the estate, and that is the
            # nesting difference stated as a lookup: three of the four verticals
            # declare no format axis at all because a claims centre is not a
            # smaller branch, so the axis their `site_formats` members land on
            # is the site axis directly.
            for source, members in (("categories", unit.categories),
                                    ("sites", unit.site_formats)):
                if not members:
                    continue
                assert declaration.cut_by(unit.kind, source), (
                    industry, unit.key, unit.kind, source,
                )
