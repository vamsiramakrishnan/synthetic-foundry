"""A locale as a *build* input, not only a spelling.

`worldloom.locales` could already say where a company is, and the three org
generators could already be told — `tests/test_org_locale.py` pins that seam.
What nothing could do was *choose* a locale for a build: `RetailWorld`,
`BankingWorld` and `InsuranceWorld` took no such field, so the only route into
the generators was a pack's `name_pools`/`regions`/`headquarters`, and
`--locale` attached the jurisdiction to the finished world's recipe. A corpus
that said Frankfurt therefore had German punctuation, Australian staff, NSW
sites and AUD facts, and nothing in it said so.

The tests here assert the three claims that closes, and one it does not.

* **It reaches.** A world spec's locale decides the region labels, the people,
  the headquarters, the retailer's second word, the currency and the financial
  year — for all three verticals, so a fourth cannot quietly ship without it.
* **It replays.** The recipe records what it was *given* (`"germany"`, not a
  frozen copy of the registry) and `recipe.rebuild` builds the same world from
  it. Before, rebuild re-attached the key to an Australian world; a corpus and
  its own replay have to be one world.
* **It changes nothing when absent.** Every default build is the same bytes,
  which is the whole reason `locales.AUSTRALIA` was extracted verbatim.

And the one it does not: **the working week never reaches the close calendar.**
`operations.generate` takes a `calendar`, `liquidity.generate` takes a
`calendar`, and no scenario passes one — so a Gulf corpus's close is still due
on a Sydney Friday. Pinned below rather than left unsaid, the way
`test_org_locale.py` pins the company-name gap: a stated gap is a decision, and
an unstated one is a bug nobody has met yet.
"""

from __future__ import annotations

import filecmp
import json
from datetime import date

import pytest

from worldloom import archetypes, locales, packs, recipe
from worldloom.banking import BankingWorld
from worldloom.generators import banking_org, insurance_org
from worldloom.insurance import InsuranceWorld
from worldloom.locales import Locale
from worldloom.retail import RetailWorld

SEED = 8128

#: (world spec, archetype key). One entry per vertical, so a test written once
#: is a test that holds for the vertical added next — the insurance geography
#: gap existed precisely because its surface was never checked against its
#: siblings'.
VERTICALS = [
    pytest.param(RetailWorld, "omnichannel_retailer", id="retail"),
    pytest.param(BankingWorld, "midsize_adi", id="banking"),
    pytest.param(InsuranceWorld, "midsize_general_insurer", id="insurance"),
]


def build(spec, archetype_key, **kwargs):  # type: ignore[no-untyped-def]
    """One world, from a fixed seed. The same seed for every call in this file,
    so two builds that differ only in their locale differ *only* in it."""
    return spec(seed=SEED, archetype=archetypes.get(archetype_key), **kwargs).build()


def same_bytes(first, second, tmp_path, label, ignoring=()):  # type: ignore[no-untyped-def]
    """Two worlds exported and diffed file by file.

    Exported rather than compared field by field, and it is the same argument
    `tests/test_cli_claims._replays` makes: what a user has is the corpus on
    disk, and an equality that skipped a file nobody thought to compare would
    pass for the world it did not check.

    No `compile()`, unlike that helper: these worlds have run no episode, and
    the organisation is exactly what a locale decides. What an episode adds on
    top replays identically already — `test_cli_claims` covers the whole
    pipeline — and running one per vertical per parameter here would buy a
    slower test for a claim another file already makes.
    """
    a, b = tmp_path / f"{label}-a", tmp_path / f"{label}-b"
    first.export(a, overwrite=True)
    second.export(b, overwrite=True)
    files = sorted(p.name for p in a.iterdir())
    assert files == sorted(p.name for p in b.iterdir())
    files = [name for name in files if name not in ignoring]
    match, mismatch, errors = filecmp.cmpfiles(a, b, files, shallow=False)
    assert not mismatch and not errors, f"{label}: {mismatch} differ, {errors} unreadable"


# ---------------------------------------------------------------------------
# It reaches
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "archetype_key"), VERTICALS)
def test_a_locale_on_the_world_spec_reaches_the_generated_organisation(
    spec, archetype_key,  # type: ignore[no-untyped-def]
) -> None:
    """The claim the whole change is for, stated per vertical."""
    au = build(spec, archetype_key)
    de = build(spec, archetype_key, locale="germany")

    assert au.company.headquarters != de.company.headquarters
    assert de.company.headquarters.endswith("Germany") or de.company.headquarters.endswith("Austria")
    # Sites carry the region label in their own name — "Supermarket NSW 007" —
    # so this is the check a reader of the corpus would make.
    assert {site.region for site in de.sites} <= set(locales.GERMANY.regions)
    assert not {site.region for site in de.sites} & set(locales.AUSTRALIA.regions)
    assert all(
        person.name.split(" ")[0] in locales.GERMANY.given for person in de.people
    )


@pytest.mark.parametrize(("spec", "archetype_key"), VERTICALS)
def test_a_locale_denominates_the_money_and_opens_the_financial_year(
    spec, archetype_key,  # type: ignore[no-untyped-def]
) -> None:
    """`Locale.applied_to`, and the reason it is worth having: a Frankfurt
    corpus spelling `1.234,50` and denominating it in AUD is a corpus that
    got the punctuation right and the currency wrong, which is the more
    embarrassing half."""
    de = build(spec, archetype_key, locale="germany")
    assert de.company.currency == "EUR"
    assert de.company.fiscal_year_start_month == 1
    # The world's archetype is the rebound one, because every money fact's unit
    # is `f"{archetype.currency}_{archetype.currency_unit}"` and a scenario
    # reads it off the world rather than off the spec.
    assert de._archetype.currency == "EUR"
    # Not rescaled. The archetype's revenue is a claim about how big the
    # company is; applying an exchange rate here would make a locale change
    # what happened rather than what it is called.
    assert de._annual_revenue == build(spec, archetype_key)._annual_revenue


def test_a_locale_names_the_retailer_after_its_jurisdiction() -> None:
    """`names.company_name` draws the second word from the locale's retail
    pool, so a German retailer is a Handelsgruppe rather than a Retail Group."""
    de = build(RetailWorld, "omnichannel_retailer", locale="germany")
    assert de.company.name.endswith(locales.GERMANY.company_suffixes)


# ---------------------------------------------------------------------------
# It changes nothing when absent
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "archetype_key"), VERTICALS)
def test_an_unset_locale_and_the_default_locale_build_one_world(
    spec, archetype_key, tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """The extracted-default discipline, checked where it is load-bearing: an
    un-localised build must be the same *bytes*, not merely the same shape, or
    every corpus this tool has ever produced stops replaying."""
    unset = build(spec, archetype_key)
    stated = build(spec, archetype_key, locale=locales.AUSTRALIA)
    # `world.json` carries the recipe, and a recipe records what it was *given*
    # — so a build that named Australia says so and a build that named nothing
    # does not. That is the one legitimate difference between them, and it is
    # asserted immediately below rather than waved past.
    same_bytes(unset, stated, tmp_path, "default", ignoring=("world.json",))
    assert stated.company == unset.company
    assert recipe.LOCALE_KEY not in unset.recipe
    assert {k: v for k, v in stated.recipe.items() if k != recipe.LOCALE_KEY} == unset.recipe


@pytest.mark.parametrize(("spec", "archetype_key"), VERTICALS)
def test_a_locale_changes_the_words_and_never_the_world(
    spec, archetype_key,  # type: ignore[no-untyped-def]
) -> None:
    """A locale is convention. It may not change what happened, and the way it
    would is by changing how many draws a stream takes — every value is drawn
    whether or not a locale redirects which pool it reads."""
    au = build(spec, archetype_key)
    de = build(spec, archetype_key, locale="germany")

    assert [p.id for p in au.people] == [p.id for p in de.people]
    assert [p.joined for p in au.people] == [p.joined for p in de.people]
    assert [p.manager_id for p in au.people] == [p.manager_id for p in de.people]
    assert [s.id for s in au.sites] == [s.id for s in de.sites]
    assert [s.revenue_weight for s in au.sites] == [s.revenue_weight for s in de.sites]
    assert [e.id for e in au.events] == [e.id for e in de.events]


# ---------------------------------------------------------------------------
# It replays
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("spec", "archetype_key"), VERTICALS)
def test_the_recipe_records_the_name_it_was_given_and_rebuilds_the_same_world(
    spec, archetype_key, tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    """A recipe that stored the resolved conventions would freeze a copy of the
    registry into every corpus; one that stored nothing would rebuild a
    different company under the same recipe. It stores the name."""
    de = build(spec, archetype_key, locale="germany")
    assert de.recipe[recipe.LOCALE_KEY] == "germany"

    again = recipe.rebuild(de.recipe)
    assert again.company.name == de.company.name
    assert again.company.headquarters == de.company.headquarters
    assert again.company.currency == de.company.currency
    same_bytes(de, again, tmp_path, "rebuild")
    # And the rebuilt recipe still names Germany rather than carrying a copy of
    # what the registry said about it on the day of the rebuild.
    assert again.recipe[recipe.LOCALE_KEY] == "germany"


def test_a_locale_stated_as_conventions_replays_as_those_conventions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The other half of `recipe._locale_document`: a jurisdiction with no
    registry name — a pack's own — round-trips as its conventions."""
    invented = Locale(
        regions=("NORTE", "SUR"),
        cities=(("Montevideo", "Uruguay"),),
        # Thirty of each: `names.people_names` samples without replacement and
        # a retail organisation is twenty-three people, so a smaller pool would
        # fail the build for a reason that has nothing to do with this test.
        given=tuple(f"Nombre{n:02d}" for n in range(30)),
        family=tuple(f"Apellido{n:02d}" for n in range(30)),
        company_suffixes=("Comercial S.A.", "Grupo"),
        currency="UYU",
        group_separator=".", decimal_separator=",",
    )
    world = build(RetailWorld, "omnichannel_retailer", locale=invented)
    assert world.recipe[recipe.LOCALE_KEY] == invented.as_dict()
    assert recipe.locale_of(world.recipe) == invented

    again = recipe.rebuild(world.recipe)
    assert again.company.headquarters == "Montevideo, Uruguay"
    same_bytes(world, again, tmp_path, "invented")


def test_a_locale_that_does_not_load_stops_the_build_before_anything_is_minted() -> None:
    """Refused, never defaulted. A build that fell back to Australia's pools
    would produce a Frankfurt company whose every figure is plausible, with
    nothing in the corpus to notice the drop by."""
    with pytest.raises(KeyError, match="unknown locale"):
        build(RetailWorld, "omnichannel_retailer", locale="germay")


# ---------------------------------------------------------------------------
# A pack is the narrower claim
# ---------------------------------------------------------------------------


def _insurer_pack() -> object:
    """The shipped general insurer, run through its own engine.

    `examples/packs/regional-insurer.json` names `retail` as its base — it
    predates the insurance engine being registered — so the base is swapped
    here. Everything else is the file as authored, which is the point: this is
    a real pack's geography, not a fixture written to pass.
    """
    source = json.loads(open("examples/packs/regional-insurer.json").read())
    return packs.load({**source, "base": "insurance", "voices": {}, "system_brands": {}})


def test_an_insurers_pack_geography_is_forwarded_at_all() -> None:
    """The bug this file found on the way past. `insurance.build` passed the
    pack's `name_pools`, `headquarters` and `regions` to nothing, so a pack
    that named Plymouth and Devon was accepted, validated, embedded in the
    recipe — and built in Sydney with sites in NSW."""
    world = InsuranceWorld.from_pack(_insurer_pack(), seed=SEED).build()
    assert world.company.headquarters == "Plymouth, United Kingdom"
    assert {site.region for site in world.sites} == {"Devon", "Cornwall", "Somerset",
                                                    "Dorset", "Bristol", "Gloucestershire",
                                                    "Wiltshire", "Hampshire"}


def test_a_packs_own_geography_still_beats_the_locales() -> None:
    """A pack is a claim about *this company*; a locale about the country it is
    in. The narrower claim wins, which is the rule `hierarchy.generate` and
    `names.people_names` already state one layer down."""
    pack = _insurer_pack()
    world = InsuranceWorld.from_pack(pack, seed=SEED)
    localised = type(world)(**{**world.__dict__, "locale": "germany"}).build()
    assert localised.company.headquarters == "Plymouth, United Kingdom"
    assert {s.region for s in localised.sites} <= set(pack.regions)  # type: ignore[attr-defined]
    # And an authored archetype keeps its own currency and financial year: a
    # pack stating GBP said so, and `Locale.applied_to` returns it untouched.
    assert localised.company.currency == "GBP"
    assert localised.company.fiscal_year_start_month == 7


# ---------------------------------------------------------------------------
# Per-industry company suffixes
# ---------------------------------------------------------------------------


def test_australias_industry_pools_are_the_generators_own_constants() -> None:
    """Extracted verbatim, in order — the discipline every other pool in
    `locales.AUSTRALIA` follows, and load-bearing here for a specific future:
    the day `banking_org` and `insurance_org` draw from the locale instead of
    their module constants, `midsize_adi` and `midsize_general_insurer` at any
    seed must produce the identical company name. Only a verbatim extraction
    makes that a fact rather than a hope."""
    assert locales.AUSTRALIA.suffixes_for("banking") == banking_org._BANK_SUFFIX
    assert locales.AUSTRALIA.suffixes_for("insurance") == insurance_org._INSURER_SUFFIX


def test_every_preset_answers_for_every_shipped_engine() -> None:
    """The fallback in `suffixes_for` exists for a vertical that lands after a
    locale is authored, not as a way for the shipped registry to say nothing.
    A preset that fell through would name a Frankfurt bank a Handelsgruppe."""
    for name, locale in sorted(locales.LOCALES.items()):
        for engine in ("banking", "insurance"):
            assert locale.suffixes_for(engine) != locale.company_suffixes, f"{name}/{engine}"


def test_retail_resolves_to_the_one_pool_and_may_not_be_stated_twice() -> None:
    """`company_suffixes` is already the retail answer, and two places to state
    one pool is one place that can stop being the one a generator draws from."""
    assert locales.GERMANY.suffixes_for("retail") is locales.GERMANY.company_suffixes
    with pytest.raises(ValueError, match="may not key 'retail'"):
        Locale(
            regions=("A",), cities=(("X", "Y"),), given=("Ann",), family=("Bee",),
            company_suffixes=("Group",), currency="EUR",
            industry_suffixes=(("retail", ("Handelsgruppe",)),),
        )


def test_an_engine_no_locale_was_written_for_falls_back_rather_than_raising() -> None:
    """The opposite posture from `locales.named`, and deliberately: an unknown
    locale name is a typo with no other reading; an unknown engine is a
    vertical that landed later, and refusing it would make that vertical
    unbuildable in this jurisdiction — an outage caused by a naming table."""
    assert locales.GULF.suffixes_for("telco") == locales.GULF.company_suffixes


def test_industry_suffixes_must_be_sorted_so_a_document_round_trips() -> None:
    """JSON objects carry no order, so the only order `from_document` can
    rebuild is one the value guarantees. Refused rather than silently
    re-sorted: an author's file and the value it produced would otherwise be
    two different documents."""
    with pytest.raises(ValueError, match="must be sorted"):
        Locale(
            regions=("A",), cities=(("X", "Y"),), given=("Ann",), family=("Bee",),
            company_suffixes=("Group",), currency="EUR",
            industry_suffixes=(("insurance", ("Assurance",)), ("banking", ("Bank",))),
        )


def test_a_hand_written_document_may_state_industry_pools_in_any_order() -> None:
    """The loading seam sorts, because a JSON object has no order to preserve.
    The refusal above is about the in-memory value, not about the file."""
    loaded = locales.from_document({
        "regions": ["A"], "cities": [["X", "Y"]], "given": ["Ann"], "family": ["Bee"],
        "company_suffixes": ["Group"], "currency": "EUR",
        "industry_suffixes": {"insurance": ["Assurance"], "banking": ["Bank"]},
    })
    assert loaded.suffixes_for("banking") == ("Bank",)
    assert loaded.industry_suffixes == (("banking", ("Bank",)), ("insurance", ("Assurance",)))


# ---------------------------------------------------------------------------
# What still does not move, pinned as a decision
# ---------------------------------------------------------------------------


def test_the_working_week_reaches_the_close_calendar() -> None:
    """This test was written the other way up, asserting the gap: a Gulf
    retailer's close was due on the day a Sydney retailer's was, because
    `MonthEndClose.run` called `operations.generate` without a calendar and no
    world carried a route from its locale to that argument. It is the assertion
    that failed the day the argument was passed, which is what it was for.

    Both directions, because a calendar that moved every corpus would be as
    wrong as one that moved none: August ends on a Monday, and four working
    days later is Friday the 4th in Sydney and Sunday the 6th in Manama —
    Gulf works Sunday to Thursday, so it has already spent its weekend.
    """
    from worldloom.scenarios import MonthEndClose

    period = "2026-08"
    au = build(RetailWorld, "omnichannel_retailer").run(
        MonthEndClose(period=period, include_operational_incident=False))
    gulf = build(RetailWorld, "omnichannel_retailer", locale="gulf").run(
        MonthEndClose(period=period, include_operational_incident=False))

    def due(world):  # type: ignore[no-untyped-def]
        return next(f.text_value for f in world.facts if f.kind == "close.due_date")

    ends = date(2026, 8, 31)
    assert locales.AUSTRALIA.business_days_after(ends, 4) == date(2026, 9, 4)
    assert locales.GULF.business_days_after(ends, 4) == date(2026, 9, 6)
    assert due(au) == "2026-09-04"
    assert due(gulf) == "2026-09-06"


def test_the_liquidity_cadence_check_asks_this_corpus_own_calendar() -> None:
    """`banking._checks`'s `liquidity_cadence_gap` recomputed "the next business
    day" on the engine's Monday-to-Friday, so it would have failed a correct
    Gulf series for a gap that is its weekend. It now asks the recipe.

    Both halves, because each alone reads like the other's bug. On the default
    calendar nothing moves — a bank validates exactly as it did. On a Gulf
    recipe it validates too, and only because the *generator* moved with the
    checker: this assertion read `"liquidity_cadence_gap" in codes` while
    `liquidity.generate` was still stepping Monday to Friday, and the failure
    was true — a Gulf bank really was observing its LCR on Fridays. Checker and
    generator now read one locale, so what is asserted is that they agree, and
    that the series lands on days the company works.
    """
    from worldloom.banking_scenarios import QuarterlyCapitalReturn

    period = "2026-03"
    au = build(BankingWorld, "midsize_adi").run(QuarterlyCapitalReturn(period=period))
    assert au.validate().ok

    gulf = build(BankingWorld, "midsize_adi", locale="gulf").run(
        QuarterlyCapitalReturn(period=period))
    assert gulf.validate().ok
    observed = sorted(f.valid_from.date() for f in gulf.facts
                      if f.kind == "liquidity.lcr")
    assert observed, "no observations to check the cadence of"
    # Friday and Saturday are the Gulf weekend, so no observation may land on
    # one. Asserted against the days rather than the count: a series that
    # simply had fewer points would pass a gap check and still be wrong.
    assert all(locales.GULF.is_business_day(day) for day in observed)
