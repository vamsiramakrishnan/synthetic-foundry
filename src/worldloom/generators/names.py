"""Name pools.

Deliberately dull on purpose. Naming is a *generative* concern — the generation
boundary puts brands, culture, and terminology on the model's side of the wall —
but step 3 runs with no model at all, so a pack-less world's names come from
fixed pools combined deterministically by seed. That is enough to prove the
deterministic spine works, and it is not enough to be interesting on its own:
two worlds from different seeds still read as the same kind of company, only
differing in structure and figures.

De-hardcoding ladder rung 4 (``docs/build-order.md`` §7a) promoted these pools
from a private constant to data a pack may author: ``people_names`` accepts
``given``/``family`` overrides, and ``packs.Pack.name_pools`` is the authored
form. What stays code either way is the *mechanism* — sampling without
replacement so a seed cannot mint two people sharing a name — and the pools
below, which every pack-less build and every pack that leaves a pool empty
still draws from. ``headquarters`` stays a single draw a pack overrides
wholesale via ``Pack.headquarters``, the same discipline as ``company_name``:
nobody authors a company's one headquarters as a *pool*.

Names are invented. Any resemblance to a real organisation or person is not
intended, which is also why the pools mix roots from many languages rather than
drawing on one naming tradition.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..rng import Rng

COMPANY_FIRST = (
    "Southern Cross", "Meridian", "Kestrel", "Ardent", "Northwind",
    "Greyfell", "Aurelia", "Tessellate", "Halcyon", "Farrowgate",
    "Vantara", "Brightwater", "Ironvale", "Solmark", "Quillon",
)
COMPANY_SECOND = (
    "Retail Group", "Group", "Holdings", "Retail", "Commerce Group",
    "Trading Group", "Retail Holdings",
)

CITIES = (
    ("Sydney", "Australia"), ("Melbourne", "Australia"), ("Auckland", "New Zealand"),
    ("Brisbane", "Australia"), ("Perth", "Australia"), ("Adelaide", "Australia"),
)

GIVEN = (
    "Rosalind", "Desmond", "Priya", "Marguerite", "Callum", "Sunniva", "Adaeze",
    "Tobias", "Yerlan", "Ilse", "Ezekiel", "Havva", "Rafferty", "Beatriz",
    "Nikolai", "Wilhelmina", "Grethe", "Chidubem", "Solveig", "Anselm",
    "Mireille", "Tarquin", "Oleksandra", "Bartholomew", "Naledi", "Fionnuala",
    "Kwabena", "Isaura", "Dmitri", "Yolanda", "Emeka", "Signe", "Rustam",
    "Perpetua", "Lachlan", "Zerlina", "Osman", "Brigid", "Takoda", "Annelies",
)

FAMILY = (
    "Achterberg", "Faulkner-Reyes", "Venkataraghavan", "Oyelaran", "Draeger",
    "Bergqvist", "Nwachukwu-Hall", "Lindqvist", "Abenov", "Vandermolen",
    "Mbatha", "Demirsoy", "Okonkwo", "Sandoval-Klein", "Ferreira-Osei",
    "Costa-Braithwaite", "Aasland", "Eze-Whitfield", "Ramaswamy", "Trbojevic",
    "Kaczmarek", "Olubunmi", "Haverkamp", "Szczepanski", "Mwangi-Turner",
    "Delacroix", "Bhattacharya", "Nakamura-Wells", "Petrosyan", "Ojukwu",
    "Lindegaard", "Rasmussen", "Adeyemi", "Kowalczyk", "Fitzmaurice",
    "Sarkisian", "Vuković", "Anand-Pereira", "Halvorsen", "Ntuli",
)

ERP = ("Helios", "Atlas Core", "Keystone", "Lumen", "Cornerstone", "Pinnacle")
MDM = ("Merchandising Hub", "Range Hub", "Product Central", "Catalogue Hub")
PLATFORM = ("Atlas Data Platform", "Lakeview", "Nimbus Analytics", "Beacon Platform")
COMMERCE = ("Commerce Platform", "Storefront", "Digital Commerce", "Shopfront")
POS = ("Store POS", "Checkout POS", "Register", "Front-of-Store POS")


def company_name(rng: Rng) -> str:
    """A fictional company name."""
    return f"{rng.choice(COMPANY_FIRST)} {rng.choice(COMPANY_SECOND)}"


def headquarters(rng: Rng) -> str:
    """A headquarters location."""
    city, country = rng.choice(CITIES)
    return f"{city}, {country}"


def people_names(
    rng: Rng, count: int, *,
    given: Sequence[str] | None = None, family: Sequence[str] | None = None,
) -> list[str]:
    """*count* distinct person names.

    ``given``/``family`` default to the engine's own pools (``GIVEN``/
    ``FAMILY``); a pack supplies either or both through ``Pack.name_pools``,
    and an empty half there means "keep the engine's default for this half
    only" — an author who cares about family names but not given ones is not
    forced to write out forty given names to say so. Given and family names
    are drawn from independent shuffles so a seed cannot produce two
    identical people, which the uniqueness check would otherwise catch as a
    coherence failure.
    """
    given_pool = given if given else GIVEN
    family_pool = family if family else FAMILY
    if count > len(given_pool) or count > len(family_pool):
        raise ValueError(
            f"name pools hold {min(len(given_pool), len(family_pool))} people, asked for {count}"
        )
    given_names = rng.derive("given").sample(given_pool, count)
    family_names = rng.derive("family").sample(family_pool, count)
    return [f"{g} {f}" for g, f in zip(given_names, family_names)]


def system_names(rng: Rng) -> dict[str, str]:
    """One name per system role in the retail archetype."""
    return {
        "erp": f"{rng.derive('erp').choice(ERP)} ERP",
        "mdm": rng.derive("mdm").choice(MDM),
        "platform": rng.derive("platform").choice(PLATFORM),
        "commerce": rng.derive("commerce").choice(COMMERCE),
        "pos": rng.derive("pos").choice(POS),
    }
