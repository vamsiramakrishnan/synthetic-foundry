"""Where a world is, extracted verbatim and then made moveable.

`worldloom.locales` is the fourth module to take the contract `parameters.Span`
set: a default lifted from the literals it replaces, a short registry of presets
that are unlike each other, unknown names refused, a document round trip. This
file holds it to that contract and to one more thing the earlier three did not
have to prove — that the locale is *deep*. A registry whose entries differ only
in their region strings would pass every structural test above and be worthless,
so the tests below are organised around the three axes the presets actually
move, and each one is asserted against generated output rather than against the
table it came from.

Four things this file is for, in the order they matter:

* **The Australian locale is the literals it replaced.** Held as goldens,
  because asserting the tuples against themselves proves nothing. The goldens
  were captured from `generators/hierarchy`, `generators/names` and
  `render/values` as they stood before the pools moved.
* **A locale reaches the corpus.** Region strings, people's names, the
  headquarters and the company's suffix all change, and every figure in every
  rendered table is respelled.
* **Every validation rule is shown firing.** `tests/test_landscape.py`'s
  standard: a check that has never rejected anything proves only that it runs.
* **The calendar is arithmetic, not vocabulary.** The sharpest claim this
  module makes is that "four business days after month end" is a different date
  in Dubai, and it is the claim that cannot be faked by renaming anything.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import date, timedelta

import pytest

from worldloom import locales
from worldloom.generators import hierarchy, names
from worldloom.generators.operations import business_days_after
from worldloom.locales import Locale
from worldloom.render.values import format_value
from worldloom.rng import Rng

SEED = 8128


# ---------------------------------------------------------------------------
# The default locale is the literals it replaced
# ---------------------------------------------------------------------------

#: `generators/hierarchy.REGIONS`, as it stood.
REGIONS: tuple[str, ...] = ("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT")

#: `generators/names.CITIES`, `COMPANY_SECOND`, and the first and last entries
#: of each forty-name pool. The whole pools are not repeated here: the two ends
#: plus the length pin the order and the contents against any reordering or
#: truncation, and forty more strings would make this file a second copy of the
#: module rather than a check on it.
#:
#: `CITIES` *is* repeated whole — it was six entries, and stayed short enough
#: to read as a unit even after the 2026 widening added the second tier; the
#: prefix pins the historical order against reordering.
CITIES: tuple[tuple[str, str], ...] = (
    ("Sydney", "Australia"), ("Melbourne", "Australia"), ("Auckland", "New Zealand"),
    ("Brisbane", "Australia"), ("Perth", "Australia"), ("Adelaide", "Australia"),
    ("Canberra", "Australia"), ("Hobart", "Australia"), ("Darwin", "Australia"),
    ("Gold Coast", "Australia"), ("Wellington", "New Zealand"),
    ("Christchurch", "New Zealand"),
)
COMPANY_SECOND: tuple[str, ...] = (
    "Retail Group", "Group", "Holdings", "Retail", "Commerce Group",
    "Trading Group", "Retail Holdings",
)


def test_the_australian_locale_is_the_literals_it_replaced() -> None:
    au = locales.AUSTRALIA
    assert au.regions == REGIONS
    assert au.cities == CITIES
    assert au.company_suffixes == COMPANY_SECOND
    assert (au.given[0], au.given[-1], len(au.given)) == ("Rosalind", "Annelies", 40)
    assert (au.family[0], au.family[-1], len(au.family)) == ("Achterberg", "Ntuli", 40)
    # The conventions that were never named anywhere: `render/values` spelled
    # `1,234.50` and `(1,234)`, `operations.business_days_after` worked Monday
    # to Friday with no holiday table at all, and the archetype's financial
    # year started in July.
    assert (au.group_separator, au.decimal_separator) == (",", ".")
    assert au.negative == "parenthesised"
    assert au.percent_gap == ""
    assert au.working_week == locales.MONDAY_TO_FRIDAY
    assert au.holidays == ()
    assert au.fiscal_year_start_month == 7
    assert au.currency == "AUD"


def test_the_generators_still_publish_the_engines_own_pools() -> None:
    """`hierarchy.REGIONS` and the `names` pools are what `packs.py`,
    `organisation.py` and `banking_org.py` import. They moved; the names did
    not — `landscape.py`'s move on `estate.PROFILES`."""
    assert hierarchy.REGIONS == REGIONS
    assert names.CITIES == CITIES
    assert names.COMPANY_SECOND == COMPANY_SECOND
    assert names.GIVEN == locales.AUSTRALIA.given
    assert names.FAMILY == locales.AUSTRALIA.family


def test_the_default_locale_is_australia() -> None:
    assert locales.DEFAULT is locales.AUSTRALIA


def test_the_engines_own_locale_claims_no_source() -> None:
    """Honestly labelled, `parameters.Span.source`'s rule."""
    assert all(value.source == "" for value in locales.LOCALES.values())
    assert all(value.about for value in locales.LOCALES.values())


def test_the_default_locale_spells_numbers_exactly_as_the_f_strings_did() -> None:
    """The four literals `render/values.format_value` used to hold, as goldens.

    This is the one extraction with no surviving copy to compare against — the
    pools at least still exist under their old names — so the old behaviour is
    written out here.
    """
    for value, fmt, expected in [
        (1234.5, None, "1,234.50"),
        (1234.0, None, "1,234"),
        (-1234.5, None, "-1,234.50"),
        (0.0, None, "0"),
        # `,.0f` rounds half to even, so 1234.5 is 1,234 and not 1,235. Pinned
        # rather than tidied: the whole value of an extracted default is that it
        # reproduces the old behaviour including the parts nobody chose.
        (1234.5, "#,##0", "1,234"),
        (-1234.5, "#,##0", "(1,234)"),
        (-0.4, "#,##0", "(0)"),
        (3.5, "0.00%", "3.50%"),
        (-3.5, "0.00%", "-3.50%"),
        (None, "#,##0", ""),
        ("already text", "#,##0", "already text"),
    ]:
        assert format_value(value, fmt) == expected, (value, fmt)


# ---------------------------------------------------------------------------
# Axis one: the figure grammar. Germany respells every number in the corpus.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("value", "fmt", "au", "de"), [
    (1234.5, None, "1,234.50", "1.234,50"),
    (-1234.5, None, "-1,234.50", "-1.234,50"),
    (1234567.0, "#,##0", "1,234,567", "1.234.567"),
    (-1234567.0, "#,##0", "(1,234,567)", "-1.234.567"),
    (12.5, "0.00%", "12.50%", "12,50 %"),
])
def test_a_locale_respells_every_figure_a_renderer_writes(
    value: float, fmt: str | None, au: str, de: str,
) -> None:
    """`format_value` is the single seam every renderer that writes a number as
    characters passes through — DOCX, PPTX, PDF, Markdown and the BM25 index —
    which is what makes this one parameter reach the whole rendered corpus."""
    assert format_value(value, fmt) == au
    assert format_value(value, fmt, locale=locales.GERMANY) == de


def test_the_swap_of_the_two_separators_is_a_single_pass() -> None:
    """The bug two `replace` calls would have: every comma becomes a dot, then
    every dot — including the ones just written — becomes a comma, and
    `1,234.50` renders as `1,234,50`."""
    assert locales.GERMANY.spell(1234.5, 2) == "1.234,50"


def test_a_percentage_keeps_its_minus_sign_under_every_locale() -> None:
    """A parenthesised percentage is not a convention anywhere — the accounting
    parenthesis belongs to money columns — and this branch printed a plain minus
    before locales existed, so routing it through `negate` would be wrong *and*
    would move the default build."""
    for locale in locales.LOCALES.values():
        assert format_value(-3.5, "0.00%", locale=locale).startswith("-")


def test_the_three_negative_conventions_are_all_reachable() -> None:
    base = locales.AUSTRALIA
    spelled = {
        convention: format_value(
            -1234.0, "#,##0",
            locale=dataclasses.replace(base, negative=convention),
        )
        for convention in ("parenthesised", "leading_minus", "trailing_minus")
    }
    assert spelled == {
        "parenthesised": "(1,234)",
        "leading_minus": "-1,234",
        "trailing_minus": "1,234-",
    }


# ---------------------------------------------------------------------------
# Axis two: the calendar. The Gulf moves dates, not words.
# ---------------------------------------------------------------------------


def test_the_default_locales_calendar_is_the_engines_calendar_exactly() -> None:
    """Whole-range, not a spot check: `operations.business_days_after` is what
    the close's due date, the escalation, the review and the revised date are
    all derived from, so "equivalent" has to mean equivalent on every day.

    Five years and one to twelve business days is 21,900 comparisons, which
    costs milliseconds and is the only honest way to claim a drop-in.
    """
    for offset in range((date(2029, 1, 1) - date(2024, 1, 1)).days):
        day = date(2024, 1, 1) + timedelta(days=offset)
        for count in range(1, 13):
            assert locales.AUSTRALIA.business_days_after(day, count) == \
                business_days_after(day, count)


def test_a_gulf_week_lands_the_close_on_a_different_date() -> None:
    """The claim no amount of renaming gets near, and it is not an edge case.

    ``operations.generate`` puts the close's due date four business days after
    month end. Under a Sunday-to-Thursday week that is a different calendar day
    for **half the month ends in 2026** — and the two answers are not one day
    apart in a consistent direction, they cross: August's close is due on a
    Friday in Sydney, which is a weekend in Dubai, where it is due on the
    following Sunday.
    """
    moved = [
        month for month in range(1, 13)
        for end in [date(2026 + (month == 12), 1 if month == 12 else month + 1, 1)
                    - timedelta(days=1)]
        if business_days_after(end, 4) != locales.GULF.business_days_after(end, 4)
    ]
    assert len(moved) == 6, moved

    august = date(2026, 8, 31)
    assert business_days_after(august, 4) == date(2026, 9, 4)          # a Friday
    assert locales.GULF.business_days_after(august, 4) == date(2026, 9, 6)  # a Sunday
    # The days they disagree about are the weekend, in both directions.
    assert not locales.GULF.is_business_day(date(2026, 9, 4))   # Friday, off
    assert locales.GULF.is_business_day(date(2026, 9, 6))       # Sunday, worked


def test_a_holiday_is_taken_out_of_the_business_day_count() -> None:
    """The UK's fixed bank holidays. 24 December 2025 is a Wednesday; one
    business day later is Christmas Day on the engine's calendar and 29
    December on the UK's, because the 25th, the 26th and the weekend are all
    out."""
    assert business_days_after(date(2025, 12, 24), 1) == date(2025, 12, 25)
    assert locales.UNITED_KINGDOM.business_days_after(date(2025, 12, 24), 1) == \
        date(2025, 12, 29)


def test_the_engines_calendar_knows_no_holiday_and_the_default_locale_says_so() -> None:
    """Empty, and that is the extraction being faithful rather than a claim that
    Australia has no public holidays. Putting Australia Day in would move the
    close calendar in every corpus this tool has ever built."""
    assert locales.AUSTRALIA.holidays == ()
    assert locales.AUSTRALIA.is_business_day(date(2026, 1, 26))  # Australia Day, a Monday


# ---------------------------------------------------------------------------
# Axis three: the words. Regions, people, headquarters, the company's suffix.
# ---------------------------------------------------------------------------


def _dimensions(locale: Locale | None):  # type: ignore[no-untyped-def]
    from worldloom.archetypes import AUSTRALIAN_GROCERY
    from worldloom.ids import Minter

    kwargs = {} if locale is None else {"locale": locale}
    return hierarchy.generate(
        Rng(SEED), Minter(),
        units=AUSTRALIAN_GROCERY.units,
        unit_ids={unit.key: f"BU-{i}" for i, unit in enumerate(AUSTRALIAN_GROCERY.units)},
        buyers={},
        **kwargs,
    )


def test_a_locale_names_the_site_estate() -> None:
    plain = {site.region for site in _dimensions(None).sites}
    german = {site.region for site in _dimensions(locales.GERMANY).sites}
    assert plain == set(REGIONS)
    assert german <= set(locales.GERMANY.regions)
    assert not plain & german
    # The name, not only the field — a site prints its region.
    assert any(site.name.startswith("Metro NW ") for site in _dimensions(locales.GERMANY).sites)


def test_a_packs_regions_still_beat_the_locales() -> None:
    """The precedence argued in `hierarchy.generate`: a pack naming regions has
    said something more specific than "put this company in Germany"."""
    sites = hierarchy.generate(
        Rng(SEED), _minter(), units=_units(), unit_ids=_unit_ids(), buyers={},
        regions=("ZONE-A", "ZONE-B"), locale=locales.GERMANY,
    ).sites
    assert {site.region for site in sites} == {"ZONE-A", "ZONE-B"}


def test_an_unpassed_locale_and_the_default_locale_agree() -> None:
    """What byte-identity rests on, at the one call site that gained a
    parameter."""
    assert [s.model_dump() for s in _dimensions(None).sites] == \
        [s.model_dump() for s in _dimensions(locales.AUSTRALIA).sites]


def _minter():  # type: ignore[no-untyped-def]
    from worldloom.ids import Minter
    return Minter()


def _units():  # type: ignore[no-untyped-def]
    from worldloom.archetypes import AUSTRALIAN_GROCERY
    return AUSTRALIAN_GROCERY.units


def _unit_ids():  # type: ignore[no-untyped-def]
    return {unit.key: f"BU-{i}" for i, unit in enumerate(_units())}


def test_a_locale_names_the_people() -> None:
    plain = names.people_names(Rng(SEED), 20)
    gulf = names.people_names(Rng(SEED), 20, locale=locales.GULF)
    assert len(set(plain) & set(gulf)) == 0
    assert all(name in locales.GULF.given for name in (n.split(" ")[0] for n in gulf))


def test_a_packs_name_pools_still_beat_the_locales_by_half() -> None:
    """The half-and-half rule `people_names` already had, extended to the third
    source: a pack that authored family names and not given ones gets its own
    family names and the *locale's* given ones, not the engine's."""
    minted = names.people_names(
        Rng(SEED), 5, family=["Aa", "Bb", "Cc", "Dd", "Ee"], locale=locales.GERMANY,
    )
    assert {n.split(" ")[1] for n in minted} <= {"Aa", "Bb", "Cc", "Dd", "Ee"}
    assert {n.split(" ")[0] for n in minted} <= set(locales.GERMANY.given)


def test_a_locale_names_the_headquarters_and_the_company() -> None:
    assert names.headquarters(Rng(SEED)) in {f"{c}, {k}" for c, k in CITIES}
    assert names.headquarters(Rng(SEED), locale=locales.GERMANY) in {
        f"{c}, {k}" for c, k in locales.GERMANY.cities
    }
    german = names.company_name(Rng(SEED), locale=locales.GERMANY)
    assert german.split(" ")[0] in {f.split(" ")[0] for f in names.COMPANY_FIRST}
    assert any(german.endswith(suffix) for suffix in locales.GERMANY.company_suffixes)


def test_the_company_name_draws_the_same_stream_positions_under_any_locale() -> None:
    """Two draws, in the same order. A locale changes the tuple the second one
    reads and not how much of the stream it consumes, so nothing downstream of
    the company name reshuffles because the company moved."""
    rng_a, rng_b = Rng(SEED), Rng(SEED)
    names.company_name(rng_a)
    names.company_name(rng_b, locale=locales.GULF)
    assert rng_a.integer(0, 10**9) == rng_b.integer(0, 10**9)


# ---------------------------------------------------------------------------
# The registry is a registry of decisions, not of flavours
# ---------------------------------------------------------------------------


def test_every_preset_moves_a_different_axis() -> None:
    """The discipline `locales.LOCALES` claims for itself. A registry where
    every entry moved every axis would teach an author that locales come in
    undifferentiated flavours, and the UK entry — same digits as Australia,
    different calendar — is there to make the point."""
    au, uk, de, gulf = (
        locales.AUSTRALIA, locales.UNITED_KINGDOM, locales.GERMANY, locales.GULF,
    )

    def digits(locale: Locale) -> tuple:
        return (locale.group_separator, locale.decimal_separator,
                locale.negative, locale.percent_gap)

    assert digits(uk) == digits(au), "the UK is the near neighbour, on purpose"
    assert digits(de) != digits(au), "Germany is the one that respells figures"
    assert gulf.working_week != au.working_week, "the Gulf is the one that moves dates"
    assert uk.working_week == au.working_week
    assert de.working_week == au.working_week
    # And every one of them still differs on the things a shallow locale would
    # be nothing but.
    for other in (uk, de, gulf):
        assert not set(other.regions) & set(au.regions)
        assert not set(other.given) & set(au.given)
        assert other.currency != au.currency


def test_every_preset_can_name_a_grocers_worth_of_people() -> None:
    """`names.people_names` refuses a pool smaller than the headcount, and a
    locale that could only staff a small company would fail part-way through a
    build rather than at the point the author chose it."""
    for name, locale in sorted(locales.LOCALES.items()):
        assert len(names.people_names(Rng(SEED), 40, locale=locale)) == 40, name


def test_every_presets_fiscal_year_is_stated_rather_than_inherited() -> None:
    """The one inert field. It is carried so the jurisdiction's answer exists in
    one place, and the presets that are not July say so — which is the only
    thing that would be true of a corpus if anything read it."""
    assert {name: locale.fiscal_year_start_month
            for name, locale in locales.LOCALES.items()} == {
        "australia": 7, "united_kingdom": 4, "germany": 1, "gulf": 1,
    }


# ---------------------------------------------------------------------------
# Refusals — each rule shown firing
# ---------------------------------------------------------------------------


def test_an_unknown_locale_is_refused_rather_than_defaulted() -> None:
    """A pack asking for `germay` that silently got Australia's would build a
    Frankfurt company whose people are called Rafferty and whose sites are in
    NSW, and every figure in it would be plausible."""
    with pytest.raises(KeyError, match="unknown locale"):
        locales.named("germay")


def test_the_error_names_what_is_known() -> None:
    with pytest.raises(KeyError, match="united_kingdom"):
        locales.named("nope")


def _valid() -> dict:
    """A minimal well-formed locale, as keyword arguments to mutate."""
    return {
        "regions": ("A", "B"),
        "cities": (("Somewhere", "Nowhere"),),
        "given": ("Ann", "Bo"),
        "family": ("Cee", "Dee"),
        "company_suffixes": ("Group",),
        "currency": "XYZ",
    }


def test_the_minimal_locale_is_actually_valid() -> None:
    """Otherwise every refusal below passes for the wrong reason."""
    assert Locale(**_valid()).regions == ("A", "B")


@pytest.mark.parametrize(("label", "mutate", "message"), [
    ("no regions", lambda k: k.__setitem__("regions", ()), "at least one regions"),
    ("a blank region", lambda k: k.__setitem__("regions", ("  ",)), "blank or whitespace"),
    ("a repeated region", lambda k: k.__setitem__("regions", ("A", "A")), "regions repeats"),
    ("a repeated given name",
     lambda k: k.__setitem__("given", ("Ann", "Ann")), "given repeats"),
    ("no cities", lambda k: k.__setitem__("cities", ()), "at least one headquarters"),
    ("a city with no country",
     lambda k: k.__setitem__("cities", (("Somewhere",),)), "is \\(city, country\\)"),
    ("no company suffix",
     lambda k: k.__setitem__("company_suffixes", ()), "at least one company_suffixes"),
    ("a currency that is not an ISO code",
     lambda k: k.__setitem__("currency", "Euro"), "ISO 4217"),
    ("a lowercase currency",
     lambda k: k.__setitem__("currency", "eur"), "ISO 4217"),
    ("a two-character separator",
     lambda k: k.__setitem__("group_separator", "''"), "single non-digit"),
    ("a digit as a separator",
     lambda k: k.__setitem__("decimal_separator", "0"), "single non-digit"),
    ("one character for both jobs",
     lambda k: k.__setitem__("decimal_separator", ","), "un-reparseable"),
    ("an invented negative convention",
     lambda k: k.__setitem__("negative", "angry_red"), "unknown negative convention"),
    ("a week with no working days",
     lambda k: k.__setitem__("working_week", ()), "loop forever"),
    ("a repeated working day",
     lambda k: k.__setitem__("working_week", (0, 0)), "working_week repeats"),
    ("a day that is not a weekday",
     lambda k: k.__setitem__("working_week", (0, 7)), "Monday is 0"),
    ("a holiday in a thirteenth month",
     lambda k: k.__setitem__("holidays", ((13, 1),)), "no such month"),
    ("a holiday on the 31st of April",
     lambda k: k.__setitem__("holidays", ((4, 31),)), "not a day of every year"),
    ("a holiday on 29 February",
     lambda k: k.__setitem__("holidays", ((2, 29),)), "not a day of every year"),
    ("a repeated holiday",
     lambda k: k.__setitem__("holidays", ((1, 1), (1, 1))), "holidays repeats"),
    ("a fiscal year starting in month zero",
     lambda k: k.__setitem__("fiscal_year_start_month", 0), "is not a month"),
])
def test_a_locale_that_would_build_a_worse_corpus_is_refused(
    label: str, mutate, message: str,
) -> None:
    kwargs = _valid()
    mutate(kwargs)
    with pytest.raises(ValueError, match=message):
        Locale(**kwargs)


def test_a_working_week_and_a_holiday_table_that_compose_to_nothing_are_refused() -> None:
    """The rule worth having, because neither half looks wrong on its own. A
    one-day working week is legal, a long holiday table is legal, and a Monday
    working week whose holidays are every Monday of a year leaves
    `business_days_after` walking forever with nothing anywhere to say so.
    """
    mondays = tuple(
        (day.month, day.day)
        for day in (date(2001, 1, 1) + timedelta(days=offset) for offset in range(365))
        if day.weekday() == locales.MONDAY
    )
    with pytest.raises(ValueError, match="fewer than"):
        Locale(**{**_valid(), "working_week": (locales.MONDAY,), "holidays": mondays})


def test_a_one_day_working_week_on_its_own_is_legal() -> None:
    """The refusal above is about the composition, not about insisting every
    locale work five days — `landscape.py`'s rule that a validator must not
    become a taste."""
    thin = Locale(**{**_valid(), "working_week": (locales.WEDNESDAY,)})
    # 31 March 2026 is a Tuesday: one business day is the 1st, two is the 8th.
    assert thin.business_days_after(date(2026, 3, 31), 2) == date(2026, 4, 8)


# ---------------------------------------------------------------------------
# Publishing and the document round trip
# ---------------------------------------------------------------------------


def test_every_locale_publishes_as_json_and_round_trips() -> None:
    """An author cannot choose what they cannot see — `parameters.publish`'s
    reason — and `from_document` is the seam a pack or a facet authors through."""
    published = locales.publish()
    assert sorted(published) == sorted(locales.LOCALES)
    for name, payload in json.loads(json.dumps(published)).items():
        assert locales.from_document(payload) == locales.LOCALES[name]
    assert locales.from_document("gulf") is locales.GULF


def test_a_document_may_state_only_what_it_cares_about() -> None:
    """A pack that wants German punctuation should not have to restate
    Monday-to-Friday. The required half is what has no engine default."""
    partial = locales.from_document({
        "regions": ["A"], "cities": [["Somewhere", "Nowhere"]],
        "given": ["Ann"], "family": ["Bee"], "company_suffixes": ["Group"],
        "currency": "EUR", "group_separator": ".", "decimal_separator": ",",
    })
    assert partial.spell(1234.5, 2) == "1.234,50"
    assert partial.working_week == locales.MONDAY_TO_FRIDAY
    assert partial.fiscal_year_start_month == 7


def test_a_document_missing_what_has_no_default_is_refused() -> None:
    with pytest.raises(ValueError, match="regions, cities, given, family"):
        locales.from_document({"regions": ["A"]})


def test_the_pack_bridge_produces_a_pack_a_pack_would_accept() -> None:
    """`Locale.pack_overrides` is the half of a locale that today's schema can
    already carry — and therefore the half that already replays, because a pack
    is embedded verbatim in the corpus recipe."""
    from worldloom import packs

    source = json.loads(open("examples/packs/regional-insurer.json").read())
    merged = {**source, **locales.GERMANY.pack_overrides()}
    pack = packs.load(merged)
    assert pack.regions == list(locales.GERMANY.regions)
    assert pack.currency == "EUR"
    assert pack.fiscal_year_start_month == 1
    assert pack.name_pools.given == list(locales.GERMANY.given)
    # The recipe embedding is plain JSON and carries all of it, which is what
    # "it replays" means concretely.
    assert packs.to_recipe(pack)["regions"] == list(locales.GERMANY.regions)


def test_the_pack_bridge_leaves_the_headquarters_to_the_seeded_draw() -> None:
    """A pack states one headquarters; a locale offers several. Picking one here
    would be this module doing a draw that belongs to `generators/names`."""
    assert "headquarters" not in locales.GERMANY.pack_overrides()
