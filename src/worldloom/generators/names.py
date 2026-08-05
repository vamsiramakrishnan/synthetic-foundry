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

**Where the pools live now.** Four of the five below moved to
``worldloom.locales``, because what they held was never "the engine's names" —
it was *Australia's*, and a corpus set in Frankfurt inherited them silently
along with the state abbreviations. The names here are aliases onto
``locales.AUSTRALIA`` (``landscape.py``'s move on ``estate.PROFILES``): callers
and ``packs.py`` import them, so they stay, but a second copy of a pool is a
copy that can stop being the one a generator draws from. ``COMPANY_FIRST`` did
*not* move: an invented first word is branding and belongs to no jurisdiction,
which is the line this split is drawn on.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..locales import DEFAULT as DEFAULT_LOCALE, Locale
from ..rng import Rng

COMPANY_FIRST = (
    "Southern Cross", "Meridian", "Kestrel", "Ardent", "Northwind",
    "Greyfell", "Aurelia", "Tessellate", "Halcyon", "Farrowgate",
    "Vantara", "Brightwater", "Ironvale", "Solmark", "Quillon",
)

#: Aliases onto the default locale — see the module docstring. Verbatim what
#: each held before ``locales`` existed, which is what keeps an un-localised
#: build byte-identical rather than close to it.
COMPANY_SECOND = DEFAULT_LOCALE.company_suffixes
CITIES = DEFAULT_LOCALE.cities
GIVEN = DEFAULT_LOCALE.given
FAMILY = DEFAULT_LOCALE.family

ERP = ("Helios", "Atlas Core", "Keystone", "Lumen", "Cornerstone", "Pinnacle")
MDM = ("Merchandising Hub", "Range Hub", "Product Central", "Catalogue Hub")
PLATFORM = ("Atlas Data Platform", "Lakeview", "Nimbus Analytics", "Beacon Platform")
COMMERCE = ("Commerce Platform", "Storefront", "Digital Commerce", "Shopfront")
POS = ("Store POS", "Checkout POS", "Register", "Front-of-Store POS")


def company_name(rng: Rng, *, locale: Locale = DEFAULT_LOCALE) -> str:
    """A fictional company name: an invented first word, then a locale's suffix.

    Two draws in this order, unchanged — the second one reads a different tuple
    under a different locale but consumes the same stream position, so a
    localised build differs in the name it produces and in nothing downstream
    of it.
    """
    return f"{rng.choice(COMPANY_FIRST)} {rng.choice(locale.company_suffixes)}"


def headquarters(rng: Rng, *, locale: Locale = DEFAULT_LOCALE) -> str:
    """A headquarters location, drawn from the locale's cities."""
    city, country = rng.choice(locale.cities)
    return f"{city}, {country}"


def people_names(
    rng: Rng, count: int, *,
    given: Sequence[str] | None = None, family: Sequence[str] | None = None,
    locale: Locale = DEFAULT_LOCALE,
) -> list[str]:
    """*count* distinct person names.

    Three sources, and the precedence is the same argument
    ``hierarchy.generate`` makes about regions: ``given``/``family`` are a
    pack's ``Pack.name_pools``, which is a claim about *this company's* people
    and beats ``locale``, which is a claim about the country they are in. An
    empty half of the pack's pools falls through to the locale for that half
    only — an author who cares about family names but not given ones is not
    forced to write out forty given names to say so.

    Given and family names are drawn from independent shuffles so a seed cannot
    produce two identical people, which the uniqueness check would otherwise
    catch as a coherence failure.
    """
    given_pool = given if given else locale.given
    family_pool = family if family else locale.family
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
