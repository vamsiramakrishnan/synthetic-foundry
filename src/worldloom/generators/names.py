"""Name pools.

Deliberately dull, and deliberately temporary.

Naming is a *generative* concern — the generation boundary puts brands, culture,
and terminology on the model's side of the wall. But step 3 runs with no model at
all, so names come from fixed pools combined deterministically by seed. That is
enough to prove the deterministic spine works, and it is not enough to be
interesting: two worlds from different seeds will differ in structure and figures
but read as the same kind of company.

Step 8 replaces this with archetype and lore packs, at which point identity
becomes a recorded generative call rather than a lookup. Until then this file is
a placeholder wearing a function signature, and the surrounding code should not
grow to depend on the pools themselves.

Names are invented. Any resemblance to a real organisation or person is not
intended, which is also why the pools mix roots from many languages rather than
drawing on one naming tradition.
"""

from __future__ import annotations

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


def people_names(rng: Rng, count: int) -> list[str]:
    """*count* distinct person names.

    Given and family names are drawn from independent shuffles so a seed cannot
    produce two identical people, which the uniqueness check would otherwise
    catch as a coherence failure.
    """
    if count > len(GIVEN) or count > len(FAMILY):
        raise ValueError(f"name pools hold {min(len(GIVEN), len(FAMILY))} people, asked for {count}")
    given = rng.derive("given").sample(GIVEN, count)
    family = rng.derive("family").sample(FAMILY, count)
    return [f"{g} {f}" for g, f in zip(given, family)]


def system_names(rng: Rng) -> dict[str, str]:
    """One name per system role in the retail archetype."""
    return {
        "erp": f"{rng.derive('erp').choice(ERP)} ERP",
        "mdm": rng.derive("mdm").choice(MDM),
        "platform": rng.derive("platform").choice(PLATFORM),
        "commerce": rng.derive("commerce").choice(COMMERCE),
        "pos": rng.derive("pos").choice(POS),
    }
