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

    vocabulary: str = ""
    """Which ``worldloom.vocabulary`` preset supplied these units' *words*.

    Empty means the archetype's own, written below — which is what every build
    that does not ask for a vocabulary gets, and the reason adding this field
    changed no corpus by a byte. A non-empty value is always accompanied by a
    ``key`` qualified with it (``"omnichannel_retailer+wholesale_club"``), so a
    recipe that stores the key alone rebuilds the words as well as the figures."""

    authored: bool = False
    """These words were written by a pack author, not by this registry.

    Set only by ``packs.archetype_of``. ``vocabulary.spoken`` returns an
    authored archetype untouched: ``Pack.units`` names every division, category
    and site format explicitly, and a generated vocabulary overriding that would
    invert the specificity rule the rest of the pack surface follows — a pack's
    ``regions`` already beat a locale's pool for the same reason."""

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



def _mutual_bank_books() -> tuple[CategorySpec, ...]:
    """A customer-owned bank's books, and why they are not the ADI's.

    A mutual has no shareholders to return capital to, so it runs a thinner
    net interest margin on purpose and holds a larger share of its income in
    deposits. There is no card book worth decomposing and no asset finance at
    all: the products a mutual does not sell are as much a part of its shape as
    the ones it does, and a second archetype that carried the same four books
    with different weights would vary a figure rather than a company.
    """
    return (
        CategorySpec("Owner-Occupier Mortgages", 0.44, 0.014),
        CategorySpec("Investor Mortgages", 0.16, 0.017),
        CategorySpec("Personal and Green Loans", 0.07, 0.048),
        CategorySpec("Member Deposits", 0.33, 0.016),
    )


def _wealth_books() -> tuple[CategorySpec, ...]:
    """Advice and administration income — a fee book, not a spread book."""
    return (
        CategorySpec("Financial Advice", 0.58, 0.21),
        CategorySpec("Superannuation Administration", 0.42, 0.16),
    )


#: A customer-owned mutual bank, and the second shape this engine has ever had.
#:
#: Banking, insurance and procurement each shipped exactly *one* archetype,
#: which is why their benchmarks were frozen. Measured across four seeds at one
#: period, a banking corpus produced 16 of 16 identical question strings and an
#: insurance corpus 9 of 9 — not similar, identical — so a five-world mosaic
#: shipped one benchmark five times and no world-selection method could move
#: anything. The cause is not the evaluation generator: a seed changes figures,
#: names and dates, while an evaluation question is about *structure*, and
#: there was only one structure. Retail, with two archetypes, drops to 76%
#: shared at a fixed seed for exactly that reason.
#:
#: So this differs from ``MIDSIZE_ADI`` where a bank actually differs, not
#: where a random number would: three units against three but a different
#: three — no treasury desk, because a mutual does not run a markets book, and
#: a wealth arm earning fees rather than a spread. Smaller, branch-light,
#: June-year like its peer but with a materially different income mix.
CUSTOMER_OWNED_BANK = Archetype(
    key="customer_owned_bank",
    label="Customer-owned mutual bank",
    industry="Banking",
    currency="AUD",
    currency_unit="millions",
    fiscal_year_start_month=7,
    annual_revenue=610,
    employees=2_100,
    units=(
        UnitSpec(
            key="retail", name="Member Banking", kind="retail_banking", share=0.72,
            categories=_mutual_bank_books(),
            site_formats=(
                SiteFormat("Member Centre", 34, 1.00),
                SiteFormat("Operations Centre", 1, 0.0),
            ),
        ),
        UnitSpec(
            key="business", name="Community Business", kind="business_banking", share=0.16,
            categories=(
                CategorySpec("Community Organisation Lending", 0.61, 0.026),
                CategorySpec("Small Business Overdrafts", 0.39, 0.034),
            ),
            site_formats=(SiteFormat("Business Banking Centre", 3, 2.1),),
        ),
        UnitSpec(
            key="wealth", name="Member Wealth", kind="wealth", share=0.12,
            categories=_wealth_books(),
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


def _transport_spend() -> tuple[CategorySpec, ...]:
    """Third-party spend categories, share of the unit's addressable spend.

    The fourth reading of these two fields, and the one that finally makes the
    ``share``/``margin`` pair mean what a procurement function means by them:
    ``share`` is the category's share of what this division *buys in*, and
    ``margin`` is the margin the division earns on the work that spend goes
    into. That is the same arithmetic slot a retail category uses and a bank's
    product book borrows — deliberately, because ``hierarchy.generate`` is the
    one dimension machine all four verticals run through.

    ``Subcontract Labour`` is the category the procure-to-pay cycle's contested
    order sits on: labour is bought by the crew-day against a rate card, which
    is what makes a quantity and a rate two separately contestable numbers. A
    tonne of aggregate delivered short is a quantity dispute and nothing else;
    a crew-day billed at the wrong rate is the price half of a three-way match,
    and this vertical needs a category that can carry both.
    """
    return (
        CategorySpec("Subcontract Labour", 0.42, 0.096),
        CategorySpec("Civil Materials", 0.31, 0.134),
        CategorySpec("Plant Hire", 0.27, 0.118),
    )


def _utilities_spend() -> tuple[CategorySpec, ...]:
    return (
        CategorySpec("Specialist Subcontract", 0.40, 0.088),
        CategorySpec("Cable and Conductor", 0.38, 0.141),
        CategorySpec("Traffic Management", 0.22, 0.126),
    )


def _facilities_spend() -> tuple[CategorySpec, ...]:
    return (
        CategorySpec("Hard Services and Maintenance", 0.55, 0.152),
        CategorySpec("Cleaning and Soft Services", 0.45, 0.109),
    )


#: A mid-size Australian infrastructure services group — the procure-to-pay
#: vertical's shape. Shape only, like the three above it: the scale is the
#: sector's, the spend categories are generic construction and utilities
#: contracting, and every figure is generated from a seed.
#:
#: Why this kind of business rather than a manufacturer or a hospital group,
#: both of which also buy heavily. A services contractor's cost base is
#: *bought in* — subcontractors, plant, materials — so the purchase order is
#: not a back-office artifact, it is where the money is committed, and the
#: month-end accrual for what has been received and not yet invoiced is a
#: material number rather than a rounding. That is what makes the composition
#: this vertical exists to demonstrate — a goods receipt deciding a general
#: ledger figure — a real dependency and not a contrivance.
#:
#: Revenue per head sits inside the envelope the registry already spans (see
#: ``company.productivity_envelope``), which is a constraint a fifth archetype
#: has to respect rather than a coincidence: an archetype outside it would
#: widen the envelope and quietly stop the scale check refusing the figures it
#: was written to refuse.
MIDSIZE_INFRASTRUCTURE_SERVICES = Archetype(
    key="midsize_infrastructure_services",
    label="Mid-size Australian infrastructure services group",
    industry="Infrastructure services and contracting",
    currency="AUD",
    currency_unit="thousands",
    fiscal_year_start_month=7,
    # ~3.2bn in thousands. Rounded to the scale of the sector, not to any filing.
    annual_revenue=3_200_000,
    employees=9_500,
    units=(
        UnitSpec(
            key="transport", name="Transport Infrastructure", kind="transport_infrastructure",
            share=0.46,
            categories=_transport_spend(),
            site_formats=(
                SiteFormat("Depot", 34, 1.00),
                SiteFormat("Project Office", 12, 0.42),
            ),
        ),
        UnitSpec(
            key="utilities", name="Utilities and Energy", kind="utilities_services",
            share=0.34,
            categories=_utilities_spend(),
            site_formats=(
                SiteFormat("Network Depot", 21, 1.00),
                # A materials yard holds stock, not turnover — the same
                # zero-revenue-weight shape `hierarchy.py` documents for a
                # distribution centre and banking reuses for an operations centre.
                SiteFormat("Materials Yard", 5, 0.0),
            ),
        ),
        UnitSpec(
            key="facilities", name="Facilities Management", kind="facilities_management",
            share=0.20,
            categories=_facilities_spend(),
            site_formats=(SiteFormat("Facilities Hub", 9, 1.60),),
        ),
    ),
)


_REGISTRY: dict[str, Archetype] = {
    AUSTRALIAN_GROCERY.key: AUSTRALIAN_GROCERY,
    OMNICHANNEL_RETAILER.key: OMNICHANNEL_RETAILER,
    MIDSIZE_ADI.key: MIDSIZE_ADI,
    CUSTOMER_OWNED_BANK.key: CUSTOMER_OWNED_BANK,
    MIDSIZE_GENERAL_INSURER.key: MIDSIZE_GENERAL_INSURER,
    MIDSIZE_INFRASTRUCTURE_SERVICES.key: MIDSIZE_INFRASTRUCTURE_SERVICES,
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
    # Deliberately no bare "services" or "contractor": both occur inside
    # descriptions of businesses that are nothing like this one ("financial
    # services", "a contractor to the grocery trade"), and the longest-phrase
    # rule below would not save them — it only breaks ties between phrases that
    # all matched.
    "infrastructure services": "midsize_infrastructure_services",
    "civil contractor": "midsize_infrastructure_services",
    "construction services": "midsize_infrastructure_services",
    "engineering services": "midsize_infrastructure_services",
    "utilities contractor": "midsize_infrastructure_services",
}


def get(key: str) -> Archetype:
    """Look up an archetype by key, optionally qualified with a vocabulary.

    ``"omnichannel_retailer"`` is the shape with its own words.
    ``"omnichannel_retailer+wholesale_club"`` is the same shape — identical
    shares, margins, site counts and unit keys — spoken as a membership
    warehouse club (``worldloom.vocabulary``).

    Resolved *here*, in the one function every caller already goes through,
    rather than by adding a parameter to each of them. That is what makes the
    qualified form work from ``build --archetype``, from ``Blueprint.archetype``
    and, load-bearing, from ``recipe.rebuild`` — which reads back the single
    ``archetype`` string a world stored and would otherwise rebuild a mosaic
    world with its figures intact and every division renamed back.
    """
    from .vocabulary import QUALIFIER, spoken

    base, _, dialect = key.partition(QUALIFIER)
    try:
        shape = _REGISTRY[base]
    except KeyError:
        raise KeyError(
            f"unknown archetype {base!r}. Registered: {', '.join(sorted(_REGISTRY))}"
        ) from None
    return spoken(shape, dialect) if dialect else shape


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
