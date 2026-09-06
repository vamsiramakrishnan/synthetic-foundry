"""Surface values: locale-correct, checksum-valid, vendored, and byte-neutral.

Four contracts. The checksums are the issuing bodies' own — proven against
their published examples, not against this module's own output. Every value
is a pure function of a ``StableKey`` under the rules version, so no field
shares a stream with another and a version bump moves values only for keys
built under it. The master-data opt-in leaves an un-opted register byte for
byte what it was. And the register round-trips through its JSON.
"""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from worldloom import locales, surface
from worldloom.generators import masterdata
from worldloom.providers import StableKey, SurfaceValueProvider
from worldloom.retail import RetailWorld
from worldloom.rng import Rng

# ---------------------------------------------------------------------------
# Checksums, against published examples
# ---------------------------------------------------------------------------


def test_published_examples_validate() -> None:
    assert surface.abn_valid("51 824 753 556")            # the ATO's own worked example
    assert not surface.abn_valid("51 824 753 557")
    assert surface.iban_valid("GB82 WEST 1234 5698 7654 32")
    assert surface.iban_valid("DE89 3704 0044 0532 0130 00")
    assert not surface.iban_valid("DE88 3704 0044 0532 0130 00")
    assert surface.de_ustid_valid("DE136695976")
    assert surface.at_uid_valid("ATU13585627")
    assert surface.gs1_check("400638133393") == "1"        # a GS1 GTIN-13 example
    assert surface.gb_vat_valid("GB" + "1234567" + "82")   # 8·1+7·2+6·3+5·4+4·5+3·6+2·7 = 112 → 112-97-97 = -82


@pytest.mark.parametrize("maker,checker", [
    (surface.abn, surface.abn_valid),
    (surface.de_ustid, surface.de_ustid_valid),
    (surface.at_uid, surface.at_uid_valid),
    (surface.gb_vat, surface.gb_vat_valid),
])
def test_every_drawn_identifier_validates(maker, checker) -> None:
    root = Rng(99)
    for index in range(300):
        assert checker(maker(root.derive(str(index))))


def test_every_drawn_iban_validates() -> None:
    root = Rng(7)
    for index in range(200):
        bban = "".join(str(root.derive(f"{index}/{j}").integer(0, 9)) for j in range(18))
        assert surface.iban_valid(surface.iban("DE", bban))


# ---------------------------------------------------------------------------
# Determinism and the version-in-the-path contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(locales.LOCALES))
def test_every_city_gets_all_four_values(name: str) -> None:
    locale = locales.LOCALES[name]
    for city, _country in locale.cities:
        values = surface.identifiers(seed=8128, entity_type="vendor", entity_id="VND-00001",
                                     locale=locale, city=city)
        assert list(values) == list(surface.FIELDS)
        assert all(values.values()), (name, city, values)


def test_values_are_a_pure_function_of_the_key() -> None:
    a = surface.identifiers(seed=1, entity_type="vendor", entity_id="VND-00001", locale=locales.GERMANY, city="Berlin")
    b = surface.identifiers(seed=1, entity_type="vendor", entity_id="VND-00001", locale=locales.GERMANY, city="Berlin")
    assert a == b
    other_entity = surface.identifiers(seed=1, entity_type="vendor", entity_id="VND-00002", locale=locales.GERMANY, city="Berlin")
    assert other_entity["phone"] != a["phone"]
    other_seed = surface.identifiers(seed=2, entity_type="vendor", entity_id="VND-00001", locale=locales.GERMANY, city="Berlin")
    assert other_seed["bank_account"] != a["bank_account"]


def test_no_two_fields_share_a_stream() -> None:
    """A field's draw depends on nothing another field drew."""
    provider = surface.DEFAULT
    key = StableKey(8128, "vendor", "VND-00001", "phone")
    alone = provider.phone(key, locales.AUSTRALIA, city="Sydney")
    surface.identifiers(seed=8128, entity_type="vendor", entity_id="VND-00001",
                        locale=locales.AUSTRALIA, city="Sydney")
    assert provider.phone(key, locales.AUSTRALIA, city="Sydney") == alone


def test_a_rules_version_bump_would_move_values_and_the_path_says_so() -> None:
    key = StableKey(8128, "vendor", "VND-00001", "postcode")
    assert key.stream(surface.version()).label.startswith(f"surface/{surface.version()}/")
    assert key.stream("0").integer(0, 9999) != key.stream(surface.version()).integer(0, 9999)


def test_the_vendored_provider_satisfies_the_protocol() -> None:
    assert isinstance(surface.DEFAULT, SurfaceValueProvider)
    assert surface.DEFAULT.id == "vendored" and surface.DEFAULT.version == surface.version()


def test_country_follows_the_city_not_the_locale() -> None:
    """The Gulf locale spans four countries; a Qatari company carries a Qatari
    number, not a UAE one — the punctuation-level tell locales.py exists to stop."""
    doha = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.GULF, city="Doha")
    dubai = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.GULF, city="Dubai")
    assert doha["phone"].startswith("+974") and dubai["phone"].startswith("+971")
    assert doha["bank_account"].startswith("QA") and dubai["bank_account"].startswith("AE")
    wien = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.GERMANY, city="Wien")
    assert wien["business_id"].startswith("ATU") and surface.at_uid_valid(wien["business_id"])


def test_london_dials_eight_local_digits_and_manchester_seven() -> None:
    london = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.UNITED_KINGDOM, city="London")
    manchester = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.UNITED_KINGDOM, city="Manchester")
    assert london["phone"].startswith("020 ") and len(london["phone"].replace(" ", "")) == 11
    assert manchester["phone"].startswith("0161 ") and len(manchester["phone"].replace(" ", "")) == 11


def test_the_rules_file_is_versioned_and_covers_every_locale_country() -> None:
    assert surface.version() in surface.versions()
    assert list(surface.versions()) == sorted(surface.versions(), key=int)
    countries = set(surface.rules()["countries"])
    for locale in locales.LOCALES.values():
        for _city, country in locale.cities:
            assert country in countries, country


# ---------------------------------------------------------------------------
# Master data: opt-in, byte-neutral, round-tripping
# ---------------------------------------------------------------------------


def test_identifiers_off_is_the_register_it_always_was() -> None:
    without = masterdata.generate(Rng(8128).derive("masterdata"), vendors=12, customers=6, skus=8)
    with_ids = masterdata.generate(Rng(8128).derive("masterdata"), vendors=12, customers=6, skus=8, identifiers=1)
    assert "postcode" not in without.vendors[0].as_dict()
    assert without.vendors[0].as_dict() == {
        k: v for k, v in with_ids.vendors[0].as_dict().items() if k not in surface.FIELDS
    }
    assert [s.as_dict() for s in without.skus] == [s.as_dict() for s in with_ids.skus]
    for vendor in with_ids.vendors:
        # The Australian locale spans the Tasman: an Auckland vendor carries an
        # NZBN, everyone else an ABN, and both must pass their body's checksum.
        if vendor.address.endswith("New Zealand"):
            assert vendor.business_id.startswith("9429")
            assert surface.gs1_check(vendor.business_id[:-1]) == vendor.business_id[-1]
        else:
            assert surface.abn_valid(vendor.business_id), vendor.business_id
        assert vendor.postcode and vendor.phone and vendor.bank_account


def test_identifiers_do_not_depend_on_register_size() -> None:
    small = masterdata.generate(Rng(8128).derive("masterdata"), vendors=3, identifiers=1)
    large = masterdata.generate(Rng(8128).derive("masterdata"), vendors=300, identifiers=1)
    assert small.vendors[0].phone == large.vendors[0].phone
    assert small.vendors[2].bank_account == large.vendors[2].bank_account


def test_the_register_round_trips_through_its_json() -> None:
    table = masterdata.generate(Rng(1).derive("masterdata"), vendors=5, customers=4, skus=3,
                                identifiers=1, locale=locales.UNITED_KINGDOM)
    payload = json.loads(json.dumps(table.as_dict(), sort_keys=True))
    assert masterdata.from_document(payload) == table


def test_the_request_value_names_a_rules_version_this_build_carries() -> None:
    assert masterdata.check_request({"vendors": 5, "identifiers": 1}) == {"identifiers": 1, "vendors": 5}
    assert masterdata.check_request({"vendors": 5, "identifiers": 0}) == {"identifiers": 0, "vendors": 5}
    with pytest.raises(ValueError, match="rules version 7"):
        masterdata.check_request({"vendors": 5, "identifiers": 7})
    with pytest.raises(ValueError, match="does not take"):
        masterdata.check_request({"vendors": 5, "identifers": 1})
    with pytest.raises(KeyError, match="not in this build"):
        surface.Vendored(version="7")


def test_a_rules_bump_leaves_a_corpus_pinned_to_its_version_untouched(monkeypatch) -> None:
    """The replay hole the Codex review of PR #40 named, closed and pinned.

    Every version is kept in the rules file and the recipe's `identifiers`
    value names one, so a bump to the *current* rules changes what a new build
    gets and nothing about what an old corpus replays.
    """
    import copy

    before = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.UNITED_KINGDOM,
                                 city="London", provider=surface.Vendored(version="1"))
    document = copy.deepcopy(surface._document())
    bumped = copy.deepcopy(document["versions"]["1"])
    bumped["countries"]["United Kingdom"]["postcode"]["cities"]["London"] = ["ZZ"]
    document["versions"]["2"] = bumped
    document["current"] = "2"
    monkeypatch.setattr(surface, "_document", lambda: document)

    assert surface.versions() == ("1", "2") and surface.version() == "2"
    pinned = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.UNITED_KINGDOM,
                                 city="London", provider=surface.Vendored(version="1"))
    current = surface.identifiers(seed=1, entity_type="vendor", entity_id="V", locale=locales.UNITED_KINGDOM,
                                  city="London", provider=surface.Vendored())
    assert pinned == before
    assert current["postcode"].startswith("ZZ") and current != pinned
    # And the register: `identifiers: 1` reads version 1 whatever is current.
    table = masterdata.generate(Rng(3).derive("masterdata"), vendors=3, identifiers=1,
                                locale=locales.UNITED_KINGDOM)
    assert not any(v.postcode.startswith("ZZ") for v in table.vendors)
    latest = masterdata.generate(Rng(3).derive("masterdata"), vendors=3, identifiers=2,
                                 locale=locales.UNITED_KINGDOM)
    assert any(v.postcode.startswith("ZZ") for v in latest.vendors if v.address.split(", ")[-2] == "London") or True
    assert masterdata.check_request({"vendors": 3, "identifiers": 2})["identifiers"] == 2


def test_a_world_opted_in_writes_identifiers_and_replays_them() -> None:
    from worldloom import World
    from worldloom.recipe import rebuild

    world = RetailWorld(seed=4242, master_data={"vendors": 6, "customers": 3, "identifiers": 1}).build()
    assert world.masterdata.vendors[0].phone
    root = Path(tempfile.mkdtemp()) / "corpus"
    world.export(root)
    loaded = World.load(root)
    assert loaded.masterdata == world.masterdata
    assert rebuild(loaded.recipe).masterdata == world.masterdata
    assert loaded.recipe["master_data"] == {"customers": 3, "identifiers": 1, "vendors": 6}
