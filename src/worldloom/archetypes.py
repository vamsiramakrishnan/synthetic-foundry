"""Archetypes: the shape of a company, without the company.

An archetype captures what makes a kind of business hard — its unit mix, where
revenue sits, how thin its margins are, how many sites it runs, what its categories
are. It captures none of the company's actual data.

That distinction is the point of `inspired_by`. A generated world should be
recognisably the same *kind* of business as a real one — so that a retrieval system
tested on it meets realistic scale, realistic margin arithmetic, and a realistic
reporting hierarchy — while every name, figure, employee, store, and incident is
invented.

`AUSTRALIAN_GROCERY` is the shape of a large Australian supermarket group: a
dominant food division on low single-digit net margin, a smaller New Zealand food
business, a general-merchandise arm that drags on group margin, a growing digital
and marketplace arm, and around a thousand stores across state-based regions. Those
are industry characteristics, not proprietary facts — the scale is rounded, the
category structure is generic grocery retail, and the figures are generated from a
seed.

Nothing here is a claim about any real company's performance.
"""

from __future__ import annotations

from dataclasses import dataclass

from .generators.hierarchy import CategorySpec, SiteFormat, UnitSpec


@dataclass(frozen=True)
class Archetype:
    """The shape of a company: scale, mix, and reporting hierarchy."""

    key: str
    label: str
    industry: str
    currency: str = "AUD"
    currency_unit: str = "thousands"
    fiscal_year_start_month: int = 7
    annual_revenue: int = 7_800_000
    """In the currency unit. With ``thousands``, 68_000_000 is 68bn."""
    employees: int = 80_000
    units: tuple[UnitSpec, ...] = ()

    @property
    def site_count(self) -> int:
        return sum(fmt.count for unit in self.units for fmt in unit.site_formats)

    @property
    def category_count(self) -> int:
        return sum(len(unit.categories) for unit in self.units)


def _food_categories() -> tuple[CategorySpec, ...]:
    """Supermarket categories, with the margin spread a grocer actually has.

    Fresh runs thinner than packaged; tobacco is near zero and is carried for
    footfall. That spread is what makes a category-level P&L interesting: the group
    margin can move without any single division looking unusual.
    """
    return (
        CategorySpec("Fresh Produce", 0.118, 0.242),
        CategorySpec("Meat, Seafood and Deli", 0.104, 0.221),
        CategorySpec("Dairy, Eggs and Chilled", 0.096, 0.258),
        CategorySpec("Bakery", 0.041, 0.401),
        CategorySpec("Packaged Grocery", 0.211, 0.263),
        CategorySpec("Frozen", 0.072, 0.281),
        CategorySpec("Drinks", 0.081, 0.244),
        CategorySpec("Health and Beauty", 0.063, 0.318),
        CategorySpec("Household and Cleaning", 0.058, 0.271),
        CategorySpec("Baby and Toddler", 0.029, 0.229),
        CategorySpec("Pet", 0.026, 0.286),
        CategorySpec("Tobacco", 0.052, 0.081),
        CategorySpec("Liquor", 0.049, 0.226),
    )


def _nz_food_categories() -> tuple[CategorySpec, ...]:
    return (
        CategorySpec("Fresh Produce", 0.131, 0.236),
        CategorySpec("Meat and Seafood", 0.112, 0.214),
        CategorySpec("Dairy and Chilled", 0.108, 0.249),
        CategorySpec("Packaged Grocery", 0.243, 0.257),
        CategorySpec("Frozen", 0.084, 0.272),
        CategorySpec("Drinks", 0.093, 0.238),
        CategorySpec("Household", 0.121, 0.264),
        CategorySpec("Health and Beauty", 0.108, 0.305),
    )


def _general_merchandise_categories() -> tuple[CategorySpec, ...]:
    """The unit that drags on group margin, and knows it."""
    return (
        CategorySpec("Apparel", 0.196, 0.318),
        CategorySpec("Home and Living", 0.171, 0.294),
        CategorySpec("Toys and Entertainment", 0.124, 0.281),
        CategorySpec("Electronics", 0.148, 0.152),
        CategorySpec("Seasonal", 0.092, 0.201),
        CategorySpec("Stationery and Craft", 0.071, 0.336),
        CategorySpec("Outdoor and Leisure", 0.104, 0.263),
        CategorySpec("Baby and Nursery", 0.094, 0.248),
    )


def _digital_categories() -> tuple[CategorySpec, ...]:
    return (
        CategorySpec("Online Grocery", 0.518, 0.187),
        CategorySpec("Marketplace", 0.146, 0.412),
        CategorySpec("Retail Media", 0.072, 0.688),
        CategorySpec("Subscription and Loyalty", 0.061, 0.552),
        CategorySpec("Direct to Boot", 0.203, 0.194),
    )


#: A large Australian supermarket group. Shape only — every specific is generated.
AUSTRALIAN_GROCERY = Archetype(
    key="australian_grocery",
    label="Large Australian supermarket group",
    industry="Supermarkets and omnichannel retail",
    currency="AUD",
    currency_unit="thousands",
    fiscal_year_start_month=7,
    # ~68bn in thousands. Rounded to the scale of the sector, not to any filing.
    annual_revenue=68_000_000,
    employees=205_000,
    units=(
        UnitSpec(
            key="food", name="Australian Food", kind="supermarkets", share=0.652,
            categories=_food_categories(),
            site_formats=(
                SiteFormat("Supermarket", 1_100, 1.00),
                SiteFormat("Metro", 90, 0.34),
                SiteFormat("Distribution Centre", 34, 0.0),
            ),
        ),
        UnitSpec(
            key="nzfood", name="New Zealand Food", kind="supermarkets", share=0.114,
            categories=_nz_food_categories(),
            site_formats=(
                SiteFormat("Supermarket NZ", 185, 1.00),
                SiteFormat("Distribution Centre NZ", 6, 0.0),
            ),
        ),
        UnitSpec(
            key="gm", name="General Merchandise", kind="general_merchandise", share=0.089,
            categories=_general_merchandise_categories(),
            site_formats=(
                SiteFormat("Department Store", 176, 1.00),
                SiteFormat("Distribution Centre GM", 4, 0.0),
            ),
        ),
        UnitSpec(
            key="digital", name="Digital and Marketplace", kind="online", share=0.145,
            categories=_digital_categories(),
            site_formats=(SiteFormat("Customer Fulfilment Centre", 12, 1.00),),
        ),
    ),
)


#: The smaller default: enough to demonstrate the pipeline without a large workbook.
OMNICHANNEL_RETAILER = Archetype(
    key="omnichannel_retailer",
    label="Mid-size omnichannel retailer",
    industry="Omnichannel retail",
    annual_revenue=7_800_000,
    employees=80_000,
    units=(
        UnitSpec(
            key="food", name="Food", kind="supermarkets", share=0.64,
            categories=(
                CategorySpec("Fresh", 0.34, 0.238),
                CategorySpec("Packaged Grocery", 0.41, 0.261),
                CategorySpec("Drinks", 0.25, 0.244),
            ),
            site_formats=(SiteFormat("Supermarket", 120, 1.00),),
        ),
        UnitSpec(
            key="gm", name="General Merchandise", kind="general_merchandise", share=0.21,
            categories=(
                CategorySpec("Apparel", 0.44, 0.318),
                CategorySpec("Home and Living", 0.36, 0.294),
                CategorySpec("Seasonal", 0.20, 0.201),
            ),
            site_formats=(SiteFormat("Department Store", 40, 1.00),),
        ),
        UnitSpec(
            key="digital", name="Digital", kind="online", share=0.15,
            categories=(
                CategorySpec("Online Grocery", 0.71, 0.187),
                CategorySpec("Marketplace", 0.29, 0.412),
            ),
        ),
    ),
)

def _retail_bank_books() -> tuple[CategorySpec, ...]:
    """Retail banking's product books, with a lender's margin spread.

    ``share`` is the book's share of the unit's net interest income and
    ``margin`` its net interest margin profile — the same two fields a retail
    category uses for revenue share and gross margin, deliberately, because the
    dimension machinery must be exercised by both verticals before §7a extracts
    a pack interface from it. Mortgages dominate income on the thinnest margin;
    cards are small and rich; deposits earn a spread, not a fee.
    """
    return (
        CategorySpec("Residential Mortgages", 0.52, 0.019),
        CategorySpec("Credit Cards", 0.13, 0.083),
        CategorySpec("Personal Loans", 0.09, 0.061),
        CategorySpec("Transaction and Savings Deposits", 0.26, 0.021),
    )


def _business_bank_books() -> tuple[CategorySpec, ...]:
    return (
        CategorySpec("SME Secured Lending", 0.47, 0.028),
        CategorySpec("Commercial Property", 0.33, 0.024),
        CategorySpec("Asset Finance", 0.20, 0.039),
    )


#: A mid-size Australian deposit-taking bank. Shape only, like the grocer: the
#: scale is the sector's, the books are generic banking, and every figure is
#: generated from a seed. The regulator this bank files to is fictional (see
#: ``worldloom.banking``) — no real prudential standard or authority is named.
MIDSIZE_ADI = Archetype(
    key="midsize_adi",
    label="Mid-size Australian deposit-taking bank",
    industry="Banking",
    currency="AUD",
    currency_unit="millions",
    fiscal_year_start_month=7,
    # Net operating income, in millions — the banking analogue of revenue.
    annual_revenue=2_400,
    employees=12_000,
    units=(
        UnitSpec(
            key="retail", name="Retail Banking", kind="retail_banking", share=0.55,
            categories=_retail_bank_books(),
            site_formats=(
                SiteFormat("Branch", 118, 1.00),
                # The operations centre is banking's distribution centre: it
                # holds work, not income, and hierarchy.py already documents the
                # zero-revenue-weight case for exactly this shape.
                SiteFormat("Operations Centre", 1, 0.0),
            ),
        ),
        UnitSpec(
            key="business", name="Business Banking", kind="business_banking", share=0.30,
            categories=_business_bank_books(),
            site_formats=(SiteFormat("Business Banking Centre", 14, 2.4),),
        ),
        UnitSpec(
            # No books and no sites, like retail's digital unit had no estate: a
            # treasury desk's income is not decomposed by product book, and an
            # empty tuple is the honest statement of that.
            key="treasury", name="Treasury and Markets", kind="treasury", share=0.15,
            categories=(),
        ),
    ),
)


def _personal_lines_books() -> tuple[CategorySpec, ...]:
    """Personal lines products, share of the unit's gross written premium.

    ``margin`` here stands in for the same slot a retail category uses for
    gross margin — general insurance's nearest analogue is the underwriting
    margin implied by the combined ratio, not a real one this generator reads;
    only ``share`` is consulted, by the triangle generator's roll-up.
    """
    return (
        CategorySpec("Motor", 0.55, 0.08),
        CategorySpec("Home", 0.35, 0.10),
        CategorySpec("Travel", 0.10, 0.05),
    )


def _commercial_lines_books() -> tuple[CategorySpec, ...]:
    """Commercial lines products. ``Public and Products Liability`` is the
    long-tail book the reserving episode's error lands on — thin margin and a
    volatile pattern, the two things that make a liability book the one a
    revaluation-style distortion would actually hurt."""
    return (
        CategorySpec("Public and Products Liability", 0.30, 0.03),
        CategorySpec("Commercial Property", 0.45, 0.09),
        CategorySpec("Professional Indemnity", 0.25, 0.04),
    )


#: A mid-size Australian general insurer. Shape only, like the grocer and the
#: bank: the scale is the sector's, the books are generic general-insurance
#: lines, and every figure is generated from a seed. No real insurer, standard,
#: or regulator is named (see ``worldloom.insurance``).
MIDSIZE_GENERAL_INSURER = Archetype(
    key="midsize_general_insurer",
    label="Mid-size Australian general insurer",
    industry="General insurance",
    currency="AUD",
    currency_unit="millions",
    fiscal_year_start_month=7,
    # Gross written premium, in millions — the insurer's analogue of revenue.
    annual_revenue=1_800,
    employees=3_500,
    units=(
        UnitSpec(
            key="personal", name="Personal Lines", kind="personal_lines", share=0.55,
            categories=_personal_lines_books(),
            site_formats=(
                SiteFormat("Branch", 20, 1.00),
                # A claims centre processes claims, not premium — the same
                # zero-revenue-weight shape hierarchy.py already documents for
                # a distribution centre.
                SiteFormat("Claims Centre", 3, 0.0),
            ),
        ),
        UnitSpec(
            key="commercial", name="Commercial Lines", kind="commercial_lines", share=0.35,
            categories=_commercial_lines_books(),
            site_formats=(SiteFormat("Underwriting Office", 6, 2.0),),
        ),
        UnitSpec(
            # No books and no sites, the same honest-empty-tuple shape as
            # banking's treasury desk: an investment function's income is not
            # decomposed by product book.
            key="investments", name="Group Investments", kind="investments", share=0.10,
            categories=(),
        ),
    ),
)


_REGISTRY: dict[str, Archetype] = {
    AUSTRALIAN_GROCERY.key: AUSTRALIAN_GROCERY,
    OMNICHANNEL_RETAILER.key: OMNICHANNEL_RETAILER,
    MIDSIZE_ADI.key: MIDSIZE_ADI,
    MIDSIZE_GENERAL_INSURER.key: MIDSIZE_GENERAL_INSURER,
}

#: What `inspired_by` accepts, and the archetype each phrase resolves to.
#:
#: Deliberately a shape lookup rather than anything that reaches for data about the
#: named company. "woolworths" means *this kind of business*, and the world that
#: comes back is invented.
_INSPIRATION: dict[str, str] = {
    "woolworths": "australian_grocery",
    "woolies": "australian_grocery",
    "coles": "australian_grocery",
    "large australian retailer": "australian_grocery",
    "large australian supermarket": "australian_grocery",
    "australian grocery": "australian_grocery",
    "supermarket": "australian_grocery",
    "grocery": "australian_grocery",
    "retailer": "omnichannel_retailer",
    "retail": "omnichannel_retailer",
    "bank": "midsize_adi",
    "banking": "midsize_adi",
    "australian bank": "midsize_adi",
    "regional bank": "midsize_adi",
    # Not the bare acronym "adi": three letters that occur inside ordinary
    # words ("trading") would hijack descriptions that never mention a bank.
    "deposit-taking institution": "midsize_adi",
    "insurer": "midsize_general_insurer",
    "insurance": "midsize_general_insurer",
    "general insurer": "midsize_general_insurer",
    "australian insurer": "midsize_general_insurer",
    "general insurance": "midsize_general_insurer",
}


def get(key: str) -> Archetype:
    """Look up an archetype by key."""
    try:
        return _REGISTRY[key]
    except KeyError:
        raise KeyError(
            f"unknown archetype {key!r}. Registered: {', '.join(sorted(_REGISTRY))}"
        ) from None


def inspired_by(description: str) -> Archetype:
    """Resolve a description of a real company to an archetype of that shape.

    Matches on the longest phrase found in *description*, so "a large Australian
    retailer like Woolworths" and "woolies" land in the same place. Falls back to
    the mid-size retailer rather than raising, because a caller who describes
    something unrecognised is better served by a working world than an error.
    """
    lowered = description.casefold()
    best = ""
    for phrase in _INSPIRATION:
        if phrase in lowered and len(phrase) > len(best):
            best = phrase
    return get(_INSPIRATION.get(best, "omnichannel_retailer"))


def available() -> list[str]:
    """Every registered archetype key."""
    return sorted(_REGISTRY)
