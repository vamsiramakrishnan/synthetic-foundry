"""The ten generated locales, and the digit grammar one of them needed.

Four locales shipped and the process catalogue built companies in fourteen
countries, so an Indian telecom was given Australian names, Australian cities,
an Australian calendar and Australian digit grammar while its records were
denominated in rupees. These assertions are about that gap being closed with
published data rather than invented pools.
"""

from __future__ import annotations

import json
from dataclasses import replace
from importlib.resources import files

import pytest

from worldloom import domains, industry, locales

GENERATED = (
    "china", "hong_kong", "india", "indonesia", "japan",
    "malaysia", "singapore", "taiwan",
)

#: Two countries have no locale and the ingest tool says why for each. A deep
#: pool needs 500 given and 500 family names. No library publishes a romanised
#: Vietnamese surname pool at all (Faker carries ten, names-dataset none), and
#: Faker's Thai surnames romanise to 314 distinct forms. Ten Vietnamese
#: surnames is not even wrong — they are extraordinarily concentrated — but it
#: cannot meet a contract that draws one distinct surname per person, and
#: padding either pool would be inventing names, which is the one thing the
#: tool exists not to do.
UNSERVED = ("TH", "VN")


def test_every_country_the_shipped_industries_build_in_has_a_locale() -> None:
    """The gap itself: no company is built somewhere it cannot be spelled."""
    catalogue = industry.load_catalogue()
    unlocalised: set[str] = set()
    for name in sorted(catalogue["industry_overlays"]):
        spec = industry.project(name, "Probe Company")
        unlocalised.update(industry.unlocalised(spec.structure.countries))
    assert unlocalised == set(UNSERVED)


@pytest.mark.parametrize("name", GENERATED)
def test_a_generated_locale_is_complete_and_registered(name: str) -> None:
    locale = locales.named(name)
    assert locale.regions and locale.cities
    assert len(locale.given) >= 10 and len(locale.family) >= 10
    assert locale.company_suffixes and locale.about
    assert len(locale.currency) == 3 and locale.currency.isupper()
    assert 1 <= locale.fiscal_year_start_month <= 12
    # The extended pool's head is the base pool, the contract every locale
    # keeps: a reordered data file would rename every employee in every world.
    assert locale.given_extended[:len(locale.given)] == locale.given
    assert locale.family_extended[:len(locale.family)] == locale.family


@pytest.mark.parametrize("name", sorted(locales.LOCALES))
def test_every_locale_answers_for_every_registered_engine(name: str) -> None:
    """The failure this test exists for, which CI found and the suite did not.

    `domains.names()` registers four engines and `suffixes_for` refuses one the
    locale has no pool for, so a generated table that stopped at banking and
    insurance made every procurement build in eight jurisdictions raise at
    company-naming time. A locale is only complete against the registry, and
    the registry is where the count comes from.
    """
    locale = locales.named(name)
    for engine in domains.names():
        assert locale.suffixes_for(engine), engine


@pytest.mark.parametrize("name", GENERATED)
def test_a_generated_pool_is_romanised(name: str) -> None:
    """names-dataset mixes scripts, and three kanji surnames reached Japan's pool.

    This project renders English-language business documents; a group report
    listing a kanji surname beside a romanised one is a mixed-script artefact,
    not a more accurate corpus. The hand-written Latin-script locales are
    excluded deliberately: Germany's Müller and Yıldırım are correct.
    """
    locale = locales.named(name)
    for pool in (locale.given, locale.family, locale.given_extended, locale.family_extended):
        offenders = [entry for entry in pool if not entry.isascii()]
        assert not offenders, offenders[:5]


def test_india_is_the_locale_the_gap_was_named_for() -> None:
    india = locales.named("india")
    assert india.currency == "INR"
    # A statutory year opening on 1 April, which neither Australia nor the
    # calendar-year presets could have stood in for.
    assert india.fiscal_year_start_month == 4
    assert ("Mumbai", "India") in india.cities
    assert (1, 26) in india.holidays and (8, 15) in india.holidays


def test_south_asian_digit_grouping_is_not_thousands() -> None:
    """The thing a single separator character could not express.

    India writes 12,34,567 and its filings are denominated in lakh and crore.
    A rupee figure printed 1,234,567 is wrong the way `(1,234)` is wrong in a
    German memo, and every renderer in this project goes through `spell`.
    """
    india = locales.named("india")
    assert india.grouping == (3, 2)
    assert india.spell(1_234_567, 0) == "12,34,567"
    assert india.spell(12_345_678, 0) == "1,23,45,678"
    assert india.spell(1_234_567.89, 2) == "12,34,567.89"
    # Below the first group boundary the two systems agree.
    assert india.spell(999, 0) == locales.AUSTRALIA.spell(999, 0) == "999"
    assert india.spell(12_345, 0) == locales.AUSTRALIA.spell(12_345, 0) == "12,345"


def test_thousands_grouping_is_untouched_and_is_every_other_locale() -> None:
    assert locales.AUSTRALIA.grouping == (3,)
    for name in GENERATED:
        if name != "india":
            assert locales.named(name).grouping == (3,)
    assert locales.AUSTRALIA.spell(1_234_567, 0) == "1,234,567"
    # A locale that swaps the separators still swaps them under grouping.
    assert locales.GERMANY.spell(1_234_567.5, 2) == "1.234.567,50"


def test_grouping_defaults_so_an_authored_locale_stays_valid() -> None:
    """The field is defaulted: every locale written before it exists loads."""
    assert locales.AUSTRALIA.grouping == (3,)
    custom = replace(locales.AUSTRALIA, grouping=(3, 2))
    assert custom.spell(1_234_567, 0) == "12,34,567"


def test_the_generated_table_records_the_libraries_it_came_from() -> None:
    """Nothing here is authored, and the file says which library published it."""
    payload = json.loads(
        files("worldloom").joinpath("_data/locales/locales@1.json").read_text(encoding="utf-8")
    )
    assert payload["schema"] == "worldloom.locales/v1"
    assert set(payload["locales"]) == set(GENERATED)
    assert {"babel", "faker", "pycountry"} <= set(payload["sources"])
    for name, row in payload["locales"].items():
        assert row["name_source"].startswith(("names-dataset", "faker:")), name


def test_a_company_in_india_is_spelled_in_india() -> None:
    """End to end: the locale reaches the company, not just the registry."""
    assert industry.geo_for(("IN", "SG")) == "india"
    assert industry.geo_for(("SG",)) == "singapore"
    # An unknown country still falls back rather than failing.
    assert industry.geo_for(("ZZ",)) == industry.DEFAULT_GEO
