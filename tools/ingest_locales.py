#!/usr/bin/env python3
"""Build locale presets from published libraries instead of authoring them.

Four locales shipped and ten countries the process catalogue builds companies
in had none, so an Indian telecom was given Australian names, Australian
cities, an Australian calendar and Australian digit grammar while its records
were denominated in rupees. Writing ten name pools by hand would have been
invented data; every field below comes from a library that publishes it.

    field                     source
    ------------------------- ----------------------------------------------
    regions                   pycountry, ISO 3166-2 subdivisions
    cities                    geonamescache, by population
    given / family            names-dataset where it carries the country,
                              else Faker's romanised provider
    currency                  babel, CLDR territory currencies
    group / decimal / minus   babel, CLDR number symbols
    grouping                  babel, CLDR decimal pattern
    percent_gap               babel, CLDR percent pattern
    holidays                  holidays, fixed-date entries only

**Romanised, deliberately.** Faker's Japanese, Chinese and Indian providers
are in native script, and this project renders English-language business
documents: a group report listing 田中 beside Katharina is not more accurate,
it is a mixed-script artefact. names-dataset publishes romanised forms for
eight of the ten; Thailand and Vietnam come from Faker's `en_TH` and the
gendered `vi_VN` lists, which are romanised. Faker's plain `vi_VN.first_names`
is a two-entry stub (`John`, `Jane`) and is skipped for that reason.

**names-dataset needs cleaning.** Its per-country first names are derived from
profile data where field order varies, so surnames leak in: Singapore's list
opens `Md, Tan, Lim, Lee, Ng`, which are an abbreviation and four surnames.
Any candidate that also appears in the country's surname list is dropped, as
is anything under three characters.

**Two tables are authored, and neither is a name.** Statutory company forms
and the month a financial year opens are facts no library publishes per
jurisdiction; they are listed below with what they are, and they are ten
values rather than ten pools.

    pip install "worldloom[ingest]" names-dataset
    python tools/ingest_locales.py
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

SCHEMA = "worldloom.locales/v1"
BASE_POOL = 40
#: Drawn deep, then cleaned: `masterdata` wants 500 names in an extended pool
#: and the surname filter removes a good share of what comes back.
POOL_DRAW = 3000
#: Capped so the shipped vocab files stay small; well past what any build asks.
POOL_CAP = 900
#: What `masterdata` requires of an extended pool, both halves.
DEEP_POOL = 500
CITY_POOL = 14
REGION_POOL = 16

#: `locale name -> (ISO 3166-1 alpha-2, printed country, babel locale)`.
COUNTRIES: dict[str, tuple[str, str, str]] = {
    "china": ("CN", "China", "zh_Hans_CN"),
    "hong_kong": ("HK", "Hong Kong", "en_HK"),
    "india": ("IN", "India", "en_IN"),
    "indonesia": ("ID", "Indonesia", "id_ID"),
    "japan": ("JP", "Japan", "ja_JP"),
    "malaysia": ("MY", "Malaysia", "ms_MY"),
    "singapore": ("SG", "Singapore", "en_SG"),
    "taiwan": ("TW", "Taiwan", "zh_Hant_TW"),
}

#: Vietnam is deliberately absent, and this is the whole reason. A locale has
#: to staff a company: `generators/names.people_names` draws one distinct
#: surname per person, so a 40-person build needs 40 surnames. names-dataset
#: does not carry Vietnam, Faker's `vi_VN` publishes ten surnames, and mimesis
#: has no Vietnamese locale at all. Ten is not wrong — Vietnamese surnames are
#: extraordinarily concentrated, and Nguyen alone is around two in five people
#: — but it cannot meet a contract that wants one each. Writing thirty more
#: would be inventing Vietnamese surnames, which is the thing this tool exists
#: not to do, so `industry.locale_finding` keeps saying VN has no locale until
#: a published pool turns up.
UNSERVED: dict[str, str] = {
    "VN": "no library publishes a romanised Vietnamese surname pool deep enough"
          " to staff a company; Faker carries ten and names-dataset carries none",
    "TH": "Faker's Thai surnames romanise to 314 distinct forms and a deep pool"
          " needs 500; names-dataset and mimesis carry no Thai names at all",
}

#: Faker person providers for the two countries names-dataset does not carry.
#: Both are romanised; `vi_VN`'s gendered lists are used because its plain
#: `first_names` is the `John`/`Jane` stub.
#: Both Thai providers, unioned: romanising the deep one collapses distinct
#: Thai spellings onto the same transcription, which leaves it just under the
#: depth a locale needs, and `en_TH` is already romanised.
FAKER_PEOPLE: dict[str, tuple[str, ...]] = {"TH": ("th_TH", "en_TH")}

#: Faker's `en_TH` is romanised and 67 names deep, which cannot staff a
#: company; its `th_TH` is 500 deep and in Thai script. Romanising the deep one
#: is mechanical rather than a judgement: pythainlp implements the Royal Thai
#: General System of Transcription, which is the published romanisation.
ROMANISE: frozenset[str] = frozenset({"TH"})

#: Statutory company forms, which no library publishes per jurisdiction. These
#: are the forms that compose with this project's invented English brand word
#: (`generators/names.COMPANY_FIRST`); a form named after the state or the
#: region that charters it would produce a name no reader would accept, which
#: is the same rule the German preset states for Sparkasse and Landesbank.
COMPANY_FORMS: dict[str, tuple[str, ...]] = {
    "CN": ("Co., Ltd.", "Group Co., Ltd.", "Holdings Co., Ltd.", "Technology Co., Ltd."),
    "HK": ("Limited", "Holdings Limited", "(HK) Limited", "Group Limited"),
    "IN": ("Private Limited", "Limited", "Industries Limited", "Enterprises Private Limited"),
    "ID": ("Tbk", "Persero Tbk", "Indonesia Tbk", "Group Tbk"),
    "JP": ("K.K.", "Co., Ltd.", "Holdings K.K.", "Corporation"),
    "MY": ("Sdn Bhd", "Berhad", "Holdings Bhd", "Group Berhad"),
    "SG": ("Pte Ltd", "Holdings Pte Ltd", "Singapore Pte Ltd", "Group Pte Ltd"),
    "TH": ("Co., Ltd.", "PCL", "Public Company Limited", "Group Co., Ltd."),
    "TW": ("Co., Ltd.", "Inc.", "Holdings Co., Ltd.", "Technology Inc."),
    "VN": ("JSC", "Co., Ltd.", "Company Limited", "Group JSC"),
}

#: The month a statutory financial year opens. India and Japan open on 1 April;
#: the rest of this set default to the calendar year. A company may elect
#: another, which is why `Archetype.fiscal_year_start_month` still wins: this
#: is the jurisdiction's default, not a company's choice.
FISCAL_START: dict[str, int] = {"IN": 4, "JP": 4}

#: Industry company forms, same axis as the German preset's `industry_suffixes`:
#: a bank and an insurer in these jurisdictions are licensed under forms a
#: trading company may not take.
INDUSTRY_FORMS: dict[str, dict[str, tuple[str, ...]]] = {
    "IN": {"banking": ("Bank Limited", "Banking Corporation Limited", "Finance Limited"),
           "insurance": ("Insurance Company Limited", "General Insurance Limited",
                         "Life Insurance Company Limited")},
    "SG": {"banking": ("Bank Pte Ltd", "Banking Group Pte Ltd", "Bank Limited"),
           "insurance": ("Insurance Pte Ltd", "Assurance Pte Ltd", "Life Pte Ltd")},
    "HK": {"banking": ("Bank Limited", "Banking Corporation Limited", "Finance Limited"),
           "insurance": ("Insurance Limited", "Assurance Limited", "Life Insurance Limited")},
    "JP": {"banking": ("Bank, Ltd.", "Financial Group, Inc.", "Shinkin Bank"),
           "insurance": ("Insurance Co., Ltd.", "Life Insurance Co., Ltd.",
                         "Marine and Fire Insurance Co., Ltd.")},
    "CN": {"banking": ("Bank Co., Ltd.", "Commercial Bank Co., Ltd.", "Rural Bank Co., Ltd."),
           "insurance": ("Insurance Co., Ltd.", "Life Insurance Co., Ltd.",
                         "Property and Casualty Insurance Co., Ltd.")},
    "MY": {"banking": ("Bank Berhad", "Banking Berhad", "Islamic Bank Berhad"),
           "insurance": ("Insurance Berhad", "Takaful Berhad", "General Insurance Berhad")},
    "ID": {"banking": ("Bank Tbk", "Bank Persero Tbk", "Bank Syariah Tbk"),
           "insurance": ("Asuransi Tbk", "Asuransi Jiwa Tbk", "Asuransi Umum Tbk")},
    "TH": {"banking": ("Bank PCL", "Commercial Bank PCL", "Bank Co., Ltd."),
           "insurance": ("Insurance PCL", "Life Assurance PCL", "General Insurance PCL")},
    "TW": {"banking": ("Bank Co., Ltd.", "Financial Holdings Co., Ltd.", "Commercial Bank Co., Ltd."),
           "insurance": ("Insurance Co., Ltd.", "Life Insurance Co., Ltd.",
                         "Property Insurance Co., Ltd.")},
    "VN": {"banking": ("Commercial JSC Bank", "Bank JSC", "Joint Stock Commercial Bank"),
           "insurance": ("Insurance JSC", "Life Insurance JSC", "Non-Life Insurance JSC")},
}


def titled(name: str) -> str:
    """One name, cased the way a document prints it."""
    cleaned = re.sub(r"\s+", " ", str(name)).strip()
    return cleaned if any(ch.isupper() for ch in cleaned[1:]) else cleaned.title()


def dedupe(values) -> list[str]:
    """Order-preserving: frequency order is information and sorting loses it."""
    return list(dict.fromkeys(values))


def names_dataset_pools(alpha2: str) -> tuple[list[str], list[str]] | None:
    from names_dataset import NameDataset

    dataset = NameDataset()
    if alpha2 not in dataset.get_country_codes(alpha_2=True):
        return None
    given_raw = dataset.get_top_names(n=POOL_DRAW, country_alpha2=alpha2, use_first_names=True)
    family_raw = dataset.get_top_names(n=POOL_DRAW, country_alpha2=alpha2, use_first_names=False)
    family = dedupe(titled(n) for n in family_raw.get(alpha2, []) if len(str(n)) > 1)
    surnames = {n.casefold() for n in family}
    given: list[str] = []
    for gendered in (given_raw.get(alpha2) or {}).values():
        given.extend(titled(n) for n in gendered)
    # Surname contamination and initials, both described in the module note.
    given = dedupe(n for n in dedupe(given) if len(n) > 2 and n.casefold() not in surnames)
    return given, family


def faker_pools(locales: tuple[str, ...], romanise: bool = False) -> tuple[list[str], list[str]]:
    import importlib

    given: list[str] = []
    family: list[str] = []
    for locale in locales:
        provider = importlib.import_module(f"faker.providers.person.{locale}").Provider
        gendered: list[str] = []
        for attribute in ("first_names_male", "first_names_female", "first_names_unisex"):
            gendered.extend(getattr(provider, attribute, ()) or ())
        if not gendered:
            gendered = list(getattr(provider, "first_names", ()) or ())
        names = list(getattr(provider, "last_names", ()) or ())
        if romanise and any(ord(ch) > 0x0E00 for ch in "".join(gendered[:5])):
            from pythainlp.transliterate import romanize

            gendered = [romanize(n) for n in gendered]
            names = [romanize(n) for n in names]
        given.extend(gendered)
        family.extend(names)
    return dedupe(titled(n) for n in given), dedupe(titled(n) for n in family)


def number_grammar(babel_locale: str) -> dict[str, Any]:
    from babel import Locale as BabelLocale

    parsed = BabelLocale.parse(babel_locale)
    symbols = parsed.number_symbols["latn"]
    pattern = parsed.decimal_formats[None].pattern
    # CLDR writes the primary group last: `#,##0.###` groups by three, and
    # India's `#,##,##0.###` groups the first three then twos. The leading `#`
    # is a placeholder rather than a group, so a secondary size is only real
    # when the pattern has three or more comma-separated parts.
    parts = pattern.split(".")[0].split(",")
    grouping = [len(parts[-1])]
    if len(parts) >= 3:
        grouping.append(len(parts[-2]))
    percent = parsed.percent_formats[None].pattern
    gap = " " if " %" in percent else (" " if " %" in percent else "")
    return {
        "group_separator": symbols.get("group", ","),
        "decimal_separator": symbols.get("decimal", "."),
        "grouping": grouping,
        "percent_gap": gap,
    }


def fixed_holidays(alpha2: str, years=(2024, 2025, 2026)) -> list[list[int]]:
    """Only entries that land on the same day every year.

    The same limitation the Gulf preset states: a holiday that follows a lunar
    calendar moves against this one, so a fixed-date table cannot carry Diwali,
    Eid or Lunar New Year, and a preset that pretends otherwise is wrong on
    most years.
    """
    import collections

    import holidays as holidays_library

    seen: collections.Counter = collections.Counter()
    for year in years:
        try:
            calendar = holidays_library.country_holidays(alpha2, years=year)
        except (KeyError, NotImplementedError):
            return []
        for day in calendar:
            seen[(day.month, day.day)] += 1
    return [[month, day] for (month, day), count in sorted(seen.items()) if count == len(years)]


def build(name: str, alpha2: str, printed: str, babel_locale: str) -> dict[str, Any]:
    import geonamescache
    import pycountry
    from babel.numbers import get_territory_currencies

    cities_all = geonamescache.GeonamesCache().get_cities().values()
    ranked = sorted((c for c in cities_all if c["countrycode"] == alpha2),
                    key=lambda c: (-c["population"], c["name"]))
    cities = [[c["name"], printed] for c in ranked[:CITY_POOL]]

    subdivisions = sorted(pycountry.subdivisions.get(country_code=alpha2) or [],
                          key=lambda row: row.code)
    # The code where it is a word a reader knows (Germany's `BW`, India's
    # `AP`), the name where ISO numbers the subdivisions instead: a site called
    # "Metro 01 007" names nothing, and Japan's prefectures are numbered.
    regions = [
        (row.code.split("-", 1)[1] if not row.code.split("-", 1)[1].isdigit() else row.name)
        for row in subdivisions
    ][:REGION_POOL]
    if not regions:
        # A city-state charters no subdivisions ISO records: Hong Kong has
        # districts and no ISO 3166-2 entries. Its populated places are what a
        # site estate is actually spread across, so they are the labels.
        regions = [c["name"] for c in ranked[:REGION_POOL]]

    pools = names_dataset_pools(alpha2)
    source = "names-dataset"
    if pools is None:
        pools = faker_pools(FAKER_PEOPLE[alpha2], romanise=alpha2 in ROMANISE)
        source = "faker:" + "+".join(FAKER_PEOPLE[alpha2])
        if alpha2 in ROMANISE:
            source += "+pythainlp"
    given, family = pools[0][:POOL_CAP], pools[1][:POOL_CAP]
    if len(given) < DEEP_POOL or len(family) < DEEP_POOL:
        raise SystemExit(
            f"{name}: {source} gives {len(given)} given and {len(family)} family names;"
            f" a deep pool needs {DEEP_POOL} of each. Add the country to UNSERVED"
            " rather than padding the pool with names nobody published."
        )

    grammar = number_grammar(babel_locale)
    currencies = get_territory_currencies(alpha2) or []
    return {
        "country": alpha2,
        "name_source": source,
        "regions": regions,
        "cities": cities,
        "given": given[:BASE_POOL],
        "family": family[:BASE_POOL],
        "given_extended": given,
        "family_extended": family,
        "company_suffixes": list(COMPANY_FORMS[alpha2]),
        "industry_suffixes": {k: list(v) for k, v in sorted(INDUSTRY_FORMS.get(alpha2, {}).items())},
        "currency": currencies[0] if currencies else "USD",
        "negative": "leading_minus",
        "holidays": fixed_holidays(alpha2),
        "fiscal_year_start_month": FISCAL_START.get(alpha2, 1),
        **grammar,
    }


def about(name: str, row: dict[str, Any]) -> str:
    grouping = row["grouping"]
    digits = ("lakh grouping (12,34,567)" if len(grouping) > 1
              else f"{row['group_separator']!r} thousands")
    return (
        f"{name.replace('_', ' ').title()}: {len(row['regions'])} ISO subdivisions as regions,"
        f" {len(row['cities'])} cities by population, {row['currency']},"
        f" {len(row['holidays'])} fixed-date holidays, a financial year opening in month"
        f" {row['fiscal_year_start_month']}, and {digits}."
        f" Names are romanised, from {row['name_source']}."
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("src/worldloom/_data/locales/locales@1.json"))
    parser.add_argument("--vocab", type=Path, default=Path("src/worldloom/data/vocab"))
    args = parser.parse_args()

    import babel
    import faker
    import geonamescache
    import pycountry

    locales: dict[str, Any] = {}
    for name, (alpha2, printed, babel_locale) in sorted(COUNTRIES.items()):
        row = build(name, alpha2, printed, babel_locale)
        extended_given = row.pop("given_extended")
        extended_family = row.pop("family_extended")
        row["about"] = about(name, row)
        locales[name] = row
        args.vocab.mkdir(parents=True, exist_ok=True)
        (args.vocab / f"{name}.json").write_text(json.dumps({
            "about": (
                f"Extended person-name pools for the {name} locale. The first"
                f" {BASE_POOL} given / {BASE_POOL} family entries are the shipped base"
                " pools verbatim (prefix contract: locales.Locale.__post_init__ refuses"
                f" any drift). Romanised, from {row['name_source']};"
                " tools/ingest_locales.py rebuilds this file."
            ),
            "family": extended_family,
            "given": extended_given,
        }, ensure_ascii=False, indent=1, sort_keys=True) + "\n", encoding="utf-8")
        print(f"{name:12s} regions={len(row['regions']):2d} cities={len(row['cities']):2d}"
              f" given={len(extended_given):4d} family={len(extended_family):4d}"
              f" {row['currency']} grouping={row['grouping']} holidays={len(row['holidays'])}"
              f" [{row['name_source']}]")

    document = {
        "schema": SCHEMA,
        "sources": {
            "babel": babel.__version__,
            "faker": faker.VERSION,
            "geonamescache": getattr(geonamescache, "__version__", "unknown"),
            "names-dataset": "2.x",
            "pycountry": pycountry.__version__,
        },
        "locales": locales,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(document, ensure_ascii=False, indent=1, sort_keys=True) + "\n",
                        encoding="utf-8")
    print(f"wrote {args.out}: {len(locales)} locales")


if __name__ == "__main__":
    main()
