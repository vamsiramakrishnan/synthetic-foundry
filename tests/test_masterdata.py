"""Vocabulary packs and master data: deep pools that move no existing byte.

Two measured gaps closed at once — the hospital run was bounded by ~40-name
locale pools, and a "vendor register" was six strings in a module constant —
and one contract that must survive both: every world built before either
existed keeps building byte-identically. The tests here pin the three halves
of that contract.

* **Prefix stability.** Every shipped locale's extended pool begins with its
  base pool verbatim, and any draw that fits the base pool samples the base
  pool — `Rng.sample` over a longer sequence lands differently even for the
  same count, so the switch, not the prefix alone, is what preserves bytes.
* **Master data is deterministic and relationally sound.** Same seed, same
  rows; a SKU's vendor exists and shares its category; names and ids are
  unique by construction; the request rides the recipe as counts and replays
  into the identical register.
* **Opt-out is a no-op.** No request, no table, no file, no recipe key.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import locales
from worldloom import recipe as recipe_module
from worldloom.generators import masterdata, names
from worldloom.retail import RetailWorld
from worldloom.rng import Rng

VOCAB_DIR = Path(__file__).resolve().parents[1] / "src" / "worldloom" / "data" / "vocab"


# ---------------------------------------------------------------------------
# Vocabulary packs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("name", sorted(locales.LOCALES))
def test_extended_pools_keep_base_as_verbatim_prefix(name: str) -> None:
    """The byte-identity contract, pinned against both the object and the file.

    Checked twice on purpose: `Locale.__post_init__` proves the constructed
    value, and the raw JSON proves the committed file — an edit that reordered
    the file *and* the in-code base pool together would fool the first check
    and not the second.
    """
    locale = locales.LOCALES[name]
    assert locale.given_extended[: len(locale.given)] == locale.given
    assert locale.family_extended[: len(locale.family)] == locale.family

    payload = json.loads((VOCAB_DIR / f"{name}.json").read_text(encoding="utf-8"))
    assert tuple(payload["given"]) == locale.given_extended
    assert tuple(payload["family"]) == locale.family_extended


@pytest.mark.parametrize("name", sorted(locales.LOCALES))
def test_extended_pools_are_deep_and_clean(name: str) -> None:
    locale = locales.LOCALES[name]
    for pool in (locale.given_extended, locale.family_extended):
        assert len(pool) >= 500
        assert len(set(pool)) == len(pool)
        assert all(entry.strip() == entry and entry for entry in pool)


def test_draws_that_fit_the_base_pool_are_untouched() -> None:
    """A headcount the base pool holds samples the base pool — the identical
    tuple, so the identical names in the identical order for every seed."""
    for locale in locales.LOCALES.values():
        got = names.people_names(Rng(8128).derive("people"), 40, locale=locale)
        expected_given = Rng(8128).derive("people").derive("given").sample(locale.given, 40)
        expected_family = Rng(8128).derive("people").derive("family").sample(locale.family, 40)
        assert got == [f"{g} {f}" for g, f in zip(expected_given, expected_family)]


def test_headcount_past_the_base_pool_draws_from_the_extension() -> None:
    """The hospital's stated bound, gone: 150 distinct people from one locale,
    where 41 used to raise."""
    people = names.people_names(Rng(8128).derive("people"), 150,
                                locale=locales.AUSTRALIA)
    assert len(people) == len(set(people)) == 150


def test_a_pack_pool_is_never_extended_from_the_locale() -> None:
    """A pack's twelve names are an authoring claim; topping them up from the
    jurisdiction would bury the authoring error the refusal exists to name."""
    with pytest.raises(ValueError, match="hold 3 people"):
        names.people_names(Rng(1), 5, given=["A", "B", "C"],
                           family=["X", "Y", "Z"], locale=locales.AUSTRALIA)


def test_a_reordered_extension_is_refused() -> None:
    import dataclasses

    broken = tuple(reversed(locales.AUSTRALIA.given_extended))
    with pytest.raises(ValueError, match="verbatim"):
        dataclasses.replace(locales.AUSTRALIA, given_extended=broken)


# ---------------------------------------------------------------------------
# Master data
# ---------------------------------------------------------------------------


def test_masterdata_is_deterministic() -> None:
    first = masterdata.generate(Rng(8128).derive("masterdata"),
                                vendors=500, customers=100, skus=300)
    second = masterdata.generate(Rng(8128).derive("masterdata"),
                                 vendors=500, customers=100, skus=300)
    assert first == second
    assert first != masterdata.generate(Rng(8129).derive("masterdata"),
                                        vendors=500, customers=100, skus=300)


def test_masterdata_integrity_holds_at_scale() -> None:
    table = masterdata.generate(Rng(8128).derive("masterdata"),
                                vendors=2000, customers=250, skus=1500)
    vendor_ids = {vendor.id: vendor for vendor in table.vendors}
    assert len(vendor_ids) == 2000
    assert len({vendor.name for vendor in table.vendors}) == 2000
    assert len({sku.name for sku in table.skus}) == 1500
    for sku in table.skus:
        parent = vendor_ids[sku.vendor_id]          # KeyError = broken parent
        assert sku.category == parent.category
    # Contact coherence, the synthkit-inspired half: every contact recurs from
    # one shared pool and every email's local part is the contact's own name.
    pool = {contact.name: contact.email_local for contact in table.contacts}
    for vendor in table.vendors:
        assert vendor.contact_name in pool
        assert vendor.contact_email.startswith(pool[vendor.contact_name] + "@")
        assert vendor.contact_email.endswith(".example")


def test_masterdata_refuses_a_bad_request() -> None:
    with pytest.raises(ValueError, match="does not take"):
        masterdata.check_request({"vendor": 10})
    with pytest.raises(ValueError, match="not one"):
        masterdata.check_request({"vendors": -1})
    with pytest.raises(ValueError, match="children of vendors"):
        masterdata.generate(Rng(1), skus=10)


def test_masterdata_rides_the_corpus_and_the_recipe(tmp_path: Path) -> None:
    """Export -> load -> export is the same file, and the recipe's counts
    rebuild the identical register with no table on hand."""
    world = RetailWorld(seed=8128, master_data={"vendors": 120, "skus": 60}).build()
    assert world.recipe["master_data"] == {"skus": 60, "vendors": 120}

    out = world.export(tmp_path / "corpus")
    first = (out / "masterdata.json").read_text(encoding="utf-8")
    from worldloom.world import World

    loaded = World.load(out)
    assert loaded.masterdata == world.masterdata
    again = loaded.export(tmp_path / "again")
    assert (again / "masterdata.json").read_text(encoding="utf-8") == first

    rebuilt = recipe_module.rebuild(world.recipe)
    assert rebuilt.masterdata == world.masterdata


def test_no_request_is_a_strict_no_op(tmp_path: Path) -> None:
    world = RetailWorld(seed=8128).build()
    assert world.masterdata is None
    assert "master_data" not in world.recipe
    out = world.export(tmp_path / "corpus")
    assert not (out / "masterdata.json").exists()


def test_spec_requests_reach_the_build() -> None:
    """The spec/SDK knob end to end: a described company with a headcount past
    every base pool and a vendor register, built without exhaustion."""
    from worldloom import sdk

    built = sdk.described({
        "industry": "Private healthcare and hospital services",
        "geo": "australia",
        "archetype": "midsize_general_insurer",
        "organisation": {"headcount": 110, "span": 5, "levels": 4},
        "master_data": {"vendors": 1000},
        "identity": {"company_name": "Healwell Healthcare Group"},
    }, seed=8128).build()
    people = list(built.world.people)
    assert len(people) >= 110
    assert len({person.name for person in people}) == len(people)
    assert len(built.world.masterdata.vendors) == 1000
