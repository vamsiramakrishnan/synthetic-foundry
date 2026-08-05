"""What a company calls its divisions — so two worlds of one shape are two companies.

``mosaic.py`` varies everything about an organisation except its *words*.
Headcount, span, reporting depth, trading year, estate size and four physics
ranges all move; the divisions are still called Food, General Merchandise and
Digital, and they still sell Fresh, Apparel and Online Grocery, because those
strings live on the archetype and an archetype is one object shared by every
world built from it. ``evaluate/across.py`` measured what that costs: 222
questions across five structurally unlike companies, 66 distinct strings, 38 of
them byte-identical in all five. "What revenue did General Merchandise report
for 2026-03?" is the same question in world 1 and world 5 because both worlds
have a division of that name, and no amount of structural variation reaches it.

So this module is the archetype's **vocabulary**, made separable from its
**shape**, exactly as ``landscape.py`` separated an estate's words from its
construction and ``profiles.py`` separated a trading year's shape from its
level.

**Why a registry of named vocabularies and not generated names.** A generator
that assembled division names from parts would have to be told which parts go
together, and the interesting failure is not a silly name — it is an *incoherent
company*. A unit called Reinsurance selling Home and Living is not a typo, it is
two businesses in one row, and every document that rolls that unit up inherits
the incoherence. Rather than police that after the fact, the registry makes it
unrepresentable: a ``Trade`` is one indivisible bundle — a division's name, what
it sells, and what its sites are called — so a unit's categories can only ever
come from the same business its name came from. The only thing selected is the
whole bundle, and it is selected by ``UnitSpec.kind``, so a ``supermarkets``
unit can be dressed only in supermarket words. Coherence is structural here, not
reviewed.

**What a vocabulary may not change: the shape.** ``spoken`` rebuilds each unit
with ``dataclasses.replace``, substituting names and nothing else — every
``share``, ``margin``, ``count`` and ``revenue_weight`` is the object the
archetype authored. That is not tidiness, it is the arithmetic: unit shares sum
to the group, category shares sum to their unit, and a zero-weight site format
is a warehouse rather than a store that books no revenue. A vocabulary that
could touch any of those would be able to break a reconciliation by renaming
something, which is the one thing renaming must never do. ``spoken`` re-checks
the share vectors afterwards anyway — see the comment there for why a check that
cannot fire today still earns its lines.

**Contract, deliberately identical to ``landscape.py``'s.** Named presets that
are unlike each other, unknown names refused rather than defaulted, everything
published as data because an author cannot choose what they cannot see. One
difference, and it is the honest one: ``landscape`` had a *default* to extract,
because the estate generator held retail words in its own source. There is no
default to extract here. An archetype **is** its vocabulary — ``AUSTRALIAN_GROCERY``
already says Australian Food and General Merchandise — so what this module ships
is the *alternatives*, and applying none of them is what every build that does
not ask for one gets. That is what keeps ``worldloom build`` byte-identical: not
a default preset that happens to match, but no substitution at all.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

#: Separates an archetype key from the vocabulary it speaks, in the qualified
#: keys ``archetypes.get`` accepts (``"omnichannel_retailer+wholesale_club"``).
#:
#: The key is the carrier because the *recipe* is: ``recipe.build_recipe`` stores
#: ``archetype.key`` and nothing else about the shape, and a corpus whose words
#: could not be rebuilt from its own recipe would fail the reason recipes exist.
#: A separator absent from every registered key and from every identifier
#: elsewhere in the project, so splitting on it can never bisect a real name.
QUALIFIER = "+"


@dataclass(frozen=True)
class Trade:
    """One line of business, named: the division, its products, its sites.

    Indivisible on purpose. The whole reason a vocabulary is a registry of these
    rather than four independent name pools is that "General Merchandise" and
    "Apparel" have to be chosen *together* or the unit stops describing one
    business.
    """

    unit: str
    """What the division is called — ``UnitSpec.name``."""

    categories: tuple[str, ...]
    """What it sells, in the order a unit takes them. A unit takes the first
    *n*, so the order is an authoring decision: the most characteristic line
    goes first, because a three-category archetype will only ever see the head
    of this tuple."""

    trading: tuple[str, ...] = ()
    """Site formats that book revenue — stores, branches, offices."""

    support: tuple[str, ...] = ()
    """Site formats that book none. Kept apart from ``trading`` rather than
    merged into one pool, because ``SiteFormat.revenue_weight == 0`` is a claim
    about *what the site is* — ``generators/hierarchy.py`` spells out that a
    distribution centre holds stock and books no turnover — and a renaming that
    called a warehouse a store would leave a corpus whose site table reads as
    forty shops that sold nothing."""

    def __post_init__(self) -> None:
        for label, values in (("unit", (self.unit,)), ("categories", self.categories),
                              ("trading", self.trading), ("support", self.support)):
            if any(not str(value).strip() for value in values):
                raise ValueError(f"trade {self.unit!r} has a blank name in {label}")
        if len(set(self.categories)) != len(self.categories):
            raise ValueError(
                f"trade {self.unit!r} names a category twice; two categories of one"
                " unit sharing a name makes every roll-up ambiguous about which"
                " row a figure came from"
            )


@dataclass(frozen=True)
class Vocabulary:
    """The words one company is built out of, keyed by the kind of unit they dress.

    Nothing here can change a share, a count or a margin — see the module
    docstring. A vocabulary that named a kind an archetype does not have is
    harmless and common (a retail vocabulary knows nothing about ``treasury``);
    an archetype with a kind the vocabulary does *not* name is refused at
    ``spoken``, because half-renamed is the one outcome worse than not renamed.
    """

    trades: Mapping[str, tuple[Trade, ...]]
    """``UnitSpec.kind`` to the trades its units take, positionally: the first
    unit of a kind takes ``trades[kind][0]``, the second ``[1]``. Positional
    rather than drawn, for ``generators/hierarchy.py``'s reason for cycling
    regions by index — the assignment must be exhaustive and stable, and a draw
    guarantees neither. It also means an archetype with two ``supermarkets``
    units (``AUSTRALIAN_GROCERY`` has an Australian and a New Zealand one) gets
    two *different* divisions rather than the same name twice."""

    about: str = ""
    source: str = ""
    """Where the words came from, when a pack supplies its own. Same boundary as
    everywhere else in this project: a sector's typical division structure is a
    prior and is welcome; one identifiable company's segment names are that
    company's data wearing a costume."""

    def __post_init__(self) -> None:
        if not self.trades:
            raise ValueError("a vocabulary names no trades at all")
        for kind, trades in self.trades.items():
            if not str(kind).strip():
                raise ValueError("a vocabulary has a blank unit kind")
            if not trades:
                raise ValueError(f"kind {kind!r} names no trades")

        # Across the whole vocabulary, not per kind. Two divisions of one company
        # sharing a name is not an id clash — the units still have distinct
        # keys — but every fact, memo and evaluation question that quotes one
        # becomes ambiguous about which it meant, which is `landscape.py`'s
        # reason for the same check over service names.
        units = [trade.unit for trades in self.trades.values() for trade in trades]
        if len(set(units)) != len(units):
            repeated = sorted({name for name in units if units.count(name) > 1})
            raise ValueError(f"division name(s) {repeated} are used by more than one trade")

        # Site formats, likewise across the vocabulary — and this one is sharper
        # than ambiguity. `hierarchy.generate` names a site
        # `f"{format} {region} {index:03d}"` and counts the index *per format
        # within a unit*, so two units sharing a format name mint two different
        # sites called "Depot NSW 001". The shipped archetypes already avoid it
        # by hand ("Distribution Centre", "Distribution Centre NZ",
        # "Distribution Centre GM"); a vocabulary has to avoid it on purpose.
        formats = [
            name
            for trades in self.trades.values()
            for trade in trades
            for name in (*trade.trading, *trade.support)
        ]
        if len(set(formats)) != len(formats):
            repeated = sorted({name for name in formats if formats.count(name) > 1})
            raise ValueError(
                f"site format(s) {repeated} appear in more than one trade; two units"
                " sharing a format name mint two different sites with the same name"
            )

    @property
    def kinds(self) -> frozenset[str]:
        return frozenset(self.trades)

    def dresses(self, units: Sequence[Any]) -> bool:
        """Whether this vocabulary can name every one of *units*, fully.

        The whole test, not the easy half: enough trades of each kind, and each
        trade deep enough for the unit that will take it. A vocabulary that can
        name three of four divisions cannot be used at all.
        """
        try:
            _assign(self, units)
        except ValueError:
            return False
        return True

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "trades": {
                kind: [
                    {
                        "unit": trade.unit,
                        "categories": list(trade.categories),
                        "trading": list(trade.trading),
                        "support": list(trade.support),
                    }
                    for trade in trades
                ]
                for kind, trades in sorted(self.trades.items())
            }
        }
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload


def _assign(vocabulary: Vocabulary, units: Sequence[Any]) -> list[Trade]:
    """One trade per unit, in unit order, or a ValueError naming what is short.

    Refused rather than truncated or recycled, ``landscape.py``'s rule for a
    size profile that outruns its pool: a vocabulary quietly reusing a trade
    would give a company two divisions with the same name and no signal
    anywhere that it had happened.
    """
    taken: dict[str, int] = {}
    chosen: list[Trade] = []
    for unit in units:
        trades = vocabulary.trades.get(unit.kind)
        if not trades:
            raise ValueError(
                f"this vocabulary names no {unit.kind!r} trade, so unit {unit.key!r}"
                " would keep its archetype's words while its siblings changed"
            )
        position = taken.get(unit.kind, 0)
        if position >= len(trades):
            raise ValueError(
                f"this vocabulary names {len(trades)} {unit.kind!r} trade(s) and the"
                f" archetype has more; unit {unit.key!r} has nothing left to wear"
            )
        trade = trades[position]
        taken[unit.kind] = position + 1

        if len(trade.categories) < len(unit.categories):
            raise ValueError(
                f"unit {unit.key!r} has {len(unit.categories)} categories and trade"
                f" {trade.unit!r} names {len(trade.categories)}"
            )
        wanted_trading = sum(1 for fmt in unit.site_formats if fmt.revenue_weight != 0.0)
        wanted_support = len(unit.site_formats) - wanted_trading
        if len(trade.trading) < wanted_trading or len(trade.support) < wanted_support:
            raise ValueError(
                f"unit {unit.key!r} runs {wanted_trading} trading and {wanted_support}"
                f" non-trading format(s); trade {trade.unit!r} names"
                f" {len(trade.trading)} and {len(trade.support)}"
            )
        chosen.append(trade)
    return chosen


def spoken(archetype: Any, name: str) -> Any:
    """*archetype*, saying everything in the vocabulary called *name*.

    Same shape, different company. The returned archetype's key is qualified
    (``"omnichannel_retailer+wholesale_club"``) so that the world's recipe —
    which records the key and nothing else about the shape — rebuilds the words
    as well as the figures.

    Three things return the archetype untouched, and each is a decision:

    * ``name`` empty — "no vocabulary" is the default state and the reason a
      build that does not ask for one is byte-identical to before this module
      existed.
    * ``archetype.authored`` — a pack wrote these words (``packs.archetype_of``).
      ``Pack.units`` names divisions, categories and formats explicitly, and a
      generated vocabulary overriding an author is the wrong way round: the
      pack is the more specific claim, the same way ``Pack.regions`` beats a
      locale's pool in ``generators/hierarchy.generate``.
    * already spoken — a vocabulary is a company's words, not a filter that
      stacks. Re-dressing would produce a key naming two vocabularies of which
      only the second is legible, and a recipe that cannot say what it built.
    """
    if not name:
        return archetype
    if getattr(archetype, "authored", False):
        return archetype
    if getattr(archetype, "vocabulary", ""):
        raise ValueError(
            f"archetype {archetype.key!r} already speaks"
            f" {archetype.vocabulary!r}; a vocabulary replaces an archetype's"
            " words rather than layering over them"
        )

    vocabulary = named(name)
    chosen = _assign(vocabulary, archetype.units)

    units = tuple(
        replace(
            unit,
            name=trade.unit,
            # Only the name moves. `share` and `margin` are the objects the
            # archetype authored, so a vocabulary cannot alter the arithmetic
            # a category participates in.
            categories=tuple(
                replace(spec, name=label)
                for spec, label in zip(unit.categories, trade.categories, strict=False)
            ),
            site_formats=tuple(
                replace(fmt, name=label)
                for fmt, label in zip(unit.site_formats, _formats(unit, trade), strict=True)
            ),
        )
        for unit, trade in zip(archetype.units, chosen, strict=True)
    )

    # Cannot fire while the loop above uses `replace` — which is the point. It
    # is the invariant that made this module safe to write at all ("a vocabulary
    # is a renaming, not a re-shaping"), it is one comparison, and the next
    # person to reach for a vocabulary that also re-splits a unit will find out
    # here rather than in a workbook whose group total no longer reconciles.
    before = [(u.key, u.share, tuple(c.share for c in u.categories)) for u in archetype.units]
    after = [(u.key, u.share, tuple(c.share for c in u.categories)) for u in units]
    if before != after:
        raise ValueError(
            f"vocabulary {name!r} moved a share; a vocabulary renames a company"
            " and may not re-shape it"
        )

    return replace(
        archetype,
        key=f"{archetype.key}{QUALIFIER}{name}",
        units=units,
        vocabulary=name,
    )


def _formats(unit: Any, trade: Trade) -> list[str]:
    """New format names for *unit*, trading and non-trading kept apart.

    Consumed positionally against ``unit.site_formats``, so the order has to be
    the unit's own rather than "all trading then all support" — an archetype is
    free to declare a warehouse between two store formats and
    ``AUSTRALIAN_GROCERY`` nearly does.
    """
    trading = iter(trade.trading)
    support = iter(trade.support)
    return [
        next(support) if fmt.revenue_weight == 0.0 else next(trading)
        for fmt in unit.site_formats
    ]


# ---------------------------------------------------------------------------
# Retail
# ---------------------------------------------------------------------------
#
# Five, and five because that is what a default `worldloom mosaic -n 5` asks
# for: a sixth would be a menu entry and a fourth would make two of five worlds
# the same company. Each is a *different retailer*, not a synonym list — a
# discounter, a wholefoods grocer, a forecourt operator, a department house and
# a wholesale club sell overlapping goods under words that share almost nothing,
# which is the property the measurement is about.
#
# The primary `supermarkets` trade names thirteen categories because
# AUSTRALIAN_GROCERY's food division has thirteen, and a vocabulary that only
# fitted the small archetype would be a trap for whoever first pointed it at the
# large one. The second names eight, for that archetype's New Zealand division.

DISCOUNT_GROCER = Vocabulary(
    trades={
        "supermarkets": (
            Trade(
                unit="Value Grocery",
                categories=(
                    "Ambient Grocery", "Chilled and Dairy", "Everyday Fresh", "Butchery",
                    "In-Store Bakery", "Frozen Food", "Soft Drinks and Water",
                    "Personal Care", "Home Care", "Infant Care", "Pet Care",
                    "Confectionery", "Beer and Wine",
                ),
                trading=("Discount Store", "Compact Store", "Trial Store"),
                support=("Regional Depot", "Central Depot"),
            ),
            Trade(
                unit="Regional Grocery",
                categories=(
                    "Ambient Lines", "Chilled Lines", "Produce Lines", "Frozen Lines",
                    "Bakery Lines", "Beverage Lines", "Household Lines", "Health Lines",
                ),
                trading=("Regional Discount Store", "Regional Compact Store"),
                support=("Regional Cross-Dock",),
            ),
        ),
        "general_merchandise": (
            Trade(
                unit="Special Buys",
                categories=(
                    "Seasonal Buys", "Homewares", "Apparel and Footwear",
                    "Tools and Hardware", "Garden and Outdoor", "Consumer Electronics",
                    "Sport and Leisure", "Toys and Games",
                ),
                trading=("Buys Outlet", "Buys Concession"),
                support=("Buys Depot",),
            ),
        ),
        "online": (
            Trade(
                unit="Direct Fulfilment",
                categories=(
                    "Online Basket", "Bulk Delivery", "Third-Party Marketplace",
                    "Digital Vouchers", "Kerbside Pickup",
                ),
                trading=("Fulfilment Hub", "Micro Fulfilment Site"),
                support=("Returns Depot",),
            ),
        ),
    },
    about="A hard discounter: a short range, own-brand led, a weekly non-food"
          " event and no counters. Everything is a line rather than a"
          " department, which is why the words are.",
)

WHOLEFOODS_GROCER = Vocabulary(
    trades={
        "supermarkets": (
            Trade(
                unit="Fresh Markets",
                categories=(
                    "Market Produce", "Organic Grocery", "Cheese and Deli",
                    "Artisan Bakery", "Sustainable Seafood", "Free Range Meat",
                    "Plant Based", "Wholefoods and Bulk", "Natural Health",
                    "Eco Household", "Baby Organics", "Pet Naturals",
                    "Craft Beverages",
                ),
                trading=("Market Hall", "Market Corner", "Market Stall"),
                support=("Produce Depot", "Chilled Depot"),
            ),
            Trade(
                unit="Neighbourhood Markets",
                categories=(
                    "Neighbourhood Produce", "Neighbourhood Deli",
                    "Neighbourhood Bakery", "Neighbourhood Chilled",
                    "Neighbourhood Pantry", "Neighbourhood Frozen",
                    "Neighbourhood Drinks", "Neighbourhood Wellbeing",
                ),
                trading=("Neighbourhood Store", "Neighbourhood Kiosk"),
                support=("Neighbourhood Depot",),
            ),
        ),
        "general_merchandise": (
            Trade(
                unit="Home and Wellbeing",
                categories=(
                    "Kitchen and Table", "Bed and Bath", "Natural Beauty",
                    "Fitness and Movement", "Garden and Growing",
                    "Books and Stationery", "Gifting", "Seasonal Living",
                ),
                trading=("Wellbeing Studio", "Wellbeing Concession"),
                support=("Wellbeing Depot",),
            ),
        ),
        "online": (
            Trade(
                unit="Subscription Boxes",
                categories=(
                    "Weekly Box", "Recipe Kits", "Curated Marketplace",
                    "Membership", "Locker Collection",
                ),
                trading=("Packing Hall", "Regional Packing Site"),
                support=("Box Returns Depot",),
            ),
        ),
    },
    about="An organic and wholefoods grocer: provenance on every shelf edge, a"
          " counter-heavy store and a subscription business that is closer to a"
          " magazine than to a checkout.",
)

CONVENIENCE_FORECOURT = Vocabulary(
    trades={
        "supermarkets": (
            Trade(
                unit="Convenience Retail",
                categories=(
                    "Food to Go", "Impulse Confectionery", "Chilled Snacking",
                    "Hot Beverages", "Cold Beverages", "Everyday Essentials",
                    "Bakery Counter", "Ice and Frozen", "Health and Wellbeing",
                    "Home Essentials", "Baby Essentials", "Pet Essentials",
                    "Tobacco and Vape",
                ),
                trading=("Convenience Store", "Transit Kiosk", "Campus Store"),
                support=("Convenience Depot", "Chilled Cross-Dock"),
            ),
            Trade(
                unit="Forecourt Retail",
                categories=(
                    "Forecourt Food", "Forecourt Drinks", "Forecourt Snacking",
                    "Forecourt Essentials", "Car Care", "Driver Wellbeing",
                    "Forecourt Bakery", "Forecourt Frozen",
                ),
                trading=("Service Station Shop", "Highway Stop"),
                support=("Forecourt Depot",),
            ),
        ),
        "general_merchandise": (
            Trade(
                unit="Motoring and Travel",
                categories=(
                    "Motoring Accessories", "Lubricants and Fluids", "Travel Comfort",
                    "Navigation and Electronics", "Camping and Touring",
                    "Cleaning and Detailing", "Safety and Recovery",
                    "Seasonal Motoring",
                ),
                trading=("Motoring Store", "Motoring Concession"),
                support=("Motoring Depot",),
            ),
        ),
        "online": (
            Trade(
                unit="Mobile Ordering",
                categories=(
                    "App Ordering", "Delivery Partners", "Fuel Payment",
                    "Loyalty Redemption", "Locker Pickup",
                ),
                trading=("Dark Kitchen", "Delivery Hub"),
                support=("Digital Returns Depot",),
            ),
        ),
    },
    about="Convenience and fuel: small baskets, long hours, and a merchandise"
          " arm that exists because the customer arrived in a car.",
)

DEPARTMENT_HOUSE = Vocabulary(
    trades={
        "supermarkets": (
            Trade(
                unit="Food Halls",
                categories=(
                    "Delicatessen", "Patisserie", "Fine Cheese", "Charcuterie",
                    "Greengrocery", "Fishmonger", "Butcher Counter", "Wine Cellar",
                    "Coffee and Tea", "Chocolate and Sweets", "Pantry Staples",
                    "Prepared Meals", "Hampers",
                ),
                trading=("Food Hall", "Food Hall Counter", "Seasonal Food Hall"),
                support=("Food Hall Depot", "Cellar Store"),
            ),
            Trade(
                unit="Regional Food Halls",
                categories=(
                    "Regional Delicatessen", "Regional Patisserie",
                    "Regional Greengrocery", "Regional Butcher", "Regional Cellar",
                    "Regional Pantry", "Regional Prepared Meals", "Regional Hampers",
                ),
                trading=("Regional Food Hall", "Regional Food Counter"),
                support=("Regional Food Depot",),
            ),
        ),
        "general_merchandise": (
            Trade(
                unit="Department Retail",
                categories=(
                    "Womenswear", "Menswear", "Beauty Hall", "Home and Interiors",
                    "Accessories and Handbags", "Childrenswear", "Furniture",
                    "Fine Jewellery",
                ),
                trading=("Flagship Store", "City Store"),
                support=("Department Depot",),
            ),
        ),
        "online": (
            Trade(
                unit="Omnichannel Commerce",
                categories=(
                    "Online Department", "Personal Shopping", "Concession Marketplace",
                    "Gift Registry", "Click and Collect",
                ),
                trading=("Commerce Hub", "Concession Fulfilment Site"),
                support=("Commerce Returns Depot",),
            ),
        ),
    },
    about="A department house with a food hall attached rather than a grocer"
          " with a clothing aisle — the same two units as the engine's default"
          " retailer, weighted the other way round in every word.",
)

WHOLESALE_CLUB = Vocabulary(
    trades={
        "supermarkets": (
            Trade(
                unit="Club Grocery",
                categories=(
                    "Pallet Grocery", "Chilled Multipack", "Produce Cases",
                    "Meat Cases", "Bakery Multipack", "Frozen Cases",
                    "Beverage Pallets", "Household Multipack",
                    "Personal Care Multipack", "Infant Multipack", "Pet Multipack",
                    "Confectionery Cases", "Cellar Cases",
                ),
                trading=("Club Warehouse", "Compact Club", "Trial Club"),
                support=("Club Depot", "Bulk Cross-Dock"),
            ),
            Trade(
                unit="Trade Grocery",
                categories=(
                    "Trade Ambient", "Trade Chilled", "Trade Produce", "Trade Frozen",
                    "Trade Bakery", "Trade Beverages", "Trade Household",
                    "Trade Catering",
                ),
                trading=("Trade Warehouse", "Trade Counter"),
                support=("Trade Depot",),
            ),
        ),
        "general_merchandise": (
            Trade(
                unit="Club Merchandise",
                categories=(
                    "Appliances", "Furniture and Storage", "Workwear",
                    "Outdoor Living", "Office and Print", "Tyres and Auto",
                    "Optical and Hearing", "Seasonal Bulk",
                ),
                trading=("Merchandise Warehouse", "Merchandise Concession"),
                support=("Merchandise Depot",),
            ),
        ),
        "online": (
            Trade(
                unit="Membership Digital",
                categories=(
                    "Member Online", "Business Delivery", "Member Marketplace",
                    "Membership Renewals", "Depot Collection",
                ),
                trading=("Member Fulfilment Centre", "Member Collection Point"),
                support=("Member Returns Depot",),
            ),
        ),
    },
    about="A membership warehouse club: cases rather than units, a trade"
          " customer beside the household one, and a merchandise range that"
          " changes when the container lands.",
)


# ---------------------------------------------------------------------------
# Banking
# ---------------------------------------------------------------------------
#
# Three rather than five, and stated rather than padded: a `--engine banking`
# mosaic of five worlds will reuse two of these. Three genuinely different
# deposit-takers is a decision; five would have been two more names for the same
# bank, which is the thing this module exists to stop.
#
# `treasury` names a trade with no categories and no sites, matching
# MIDSIZE_ADI's own empty tuples — a treasury desk's income is not decomposed by
# product book, and inventing books for it here would put a fiction in the one
# place the archetype was careful to leave honest.

MUTUAL_BANK = Vocabulary(
    trades={
        "retail_banking": (
            Trade(
                unit="Member Banking",
                categories=(
                    "Owner Occupied Home Loans", "Member Credit Cards",
                    "Member Personal Lending", "Everyday and Savings Accounts",
                ),
                trading=("Member Branch", "Member Service Centre"),
                support=("Member Operations Hub",),
            ),
        ),
        "business_banking": (
            Trade(
                unit="Community Business",
                categories=(
                    "Small Business Lending", "Community Property Finance",
                    "Equipment Finance",
                ),
                trading=("Community Business Centre", "Community Lending Office"),
                support=("Business Support Hub",),
            ),
        ),
        "treasury": (Trade(unit="Balance Sheet Management", categories=()),),
    },
    about="A customer-owned mutual: members rather than shareholders, a branch"
          " network it is reluctant to close, and a treasury desk that funds"
          " the book rather than trading it.",
)

BROKER_LENDER = Vocabulary(
    trades={
        "retail_banking": (
            Trade(
                unit="Third Party Lending",
                categories=(
                    "Broker Originated Mortgages", "Consumer Credit Cards",
                    "Unsecured Personal Lending", "At-Call Deposits",
                ),
                trading=("Lending Hub", "Broker Service Centre"),
                support=("Loan Operations Centre",),
            ),
        ),
        "business_banking": (
            Trade(
                unit="Commercial Origination",
                categories=(
                    "Secured Commercial Lending", "Investment Property Finance",
                    "Asset and Equipment Finance",
                ),
                trading=("Commercial Origination Office", "Commercial Lending Desk"),
                support=("Commercial Support Centre",),
            ),
        ),
        "treasury": (Trade(unit="Funding and Markets", categories=()),),
    },
    about="A broker-distributed lender: almost no counters, a settlement"
          " factory instead, and a funding desk that is the whole liability"
          " side of the business.",
)

REGIONAL_TRADING_BANK = Vocabulary(
    trades={
        "retail_banking": (
            Trade(
                unit="Personal Banking Network",
                categories=(
                    "Residential Lending", "Everyday Credit Cards",
                    "Personal Loans and Overdrafts", "Term and Savings Deposits",
                ),
                trading=("Regional Branch", "Agency Branch"),
                support=("Regional Processing Centre",),
            ),
        ),
        "business_banking": (
            Trade(
                unit="Agribusiness and Commercial",
                categories=(
                    "Agribusiness Lending", "Regional Commercial Property",
                    "Farm Equipment Finance",
                ),
                trading=("Agribusiness Centre", "Regional Commercial Office"),
                support=("Commercial Processing Centre",),
            ),
        ),
        "treasury": (Trade(unit="Group Treasury", categories=()),),
    },
    about="A regional trading bank: an agency branch in towns that lost their"
          " last bank, and a commercial book concentrated in one industry and"
          " one weather system.",
)


# ---------------------------------------------------------------------------
# Insurance
# ---------------------------------------------------------------------------

DIRECT_INSURER = Vocabulary(
    trades={
        "personal_lines": (
            Trade(
                unit="Direct Personal",
                categories=("Private Motor", "Household", "Travel and Leisure"),
                trading=("Direct Service Centre", "Retail Shopfront"),
                support=("Claims Handling Centre",),
            ),
        ),
        "commercial_lines": (
            Trade(
                unit="Small Business Lines",
                categories=("Business Liability", "Business Property", "Trades Indemnity"),
                trading=("Business Underwriting Hub", "Business Sales Desk"),
                support=("Business Claims Centre",),
            ),
        ),
        "investments": (Trade(unit="Shareholder Funds", categories=()),),
    },
    about="A direct writer: no intermediary, a price on a screen in ninety"
          " seconds, and a claims operation that is the entire brand.",
)

BROKER_UNDERWRITER = Vocabulary(
    trades={
        "personal_lines": (
            Trade(
                unit="Intermediated Personal",
                categories=("Broker Motor", "Broker Home", "Broker Travel"),
                trading=("Broker Branch", "Adviser Office"),
                support=("Intermediated Claims Centre",),
            ),
        ),
        "commercial_lines": (
            Trade(
                unit="Corporate and Specialty",
                categories=("Casualty and Liability", "Corporate Property", "Financial Lines"),
                trading=("Specialty Underwriting Office", "Corporate Underwriting Desk"),
                support=("Specialty Claims Centre",),
            ),
        ),
        "investments": (Trade(unit="Investment Management", categories=()),),
    },
    about="An intermediated underwriter: the broker is the customer, the"
          " long-tail casualty book is where the reserving argument lives, and"
          " personal lines is the smaller half.",
)

MUTUAL_INSURER = Vocabulary(
    trades={
        "personal_lines": (
            Trade(
                unit="Member Protection",
                categories=("Member Motor", "Member Home and Contents", "Member Travel"),
                trading=("Member Insurance Branch", "Member Contact Centre"),
                support=("Member Claims Centre",),
            ),
        ),
        "commercial_lines": (
            Trade(
                unit="Community and Commercial",
                categories=("Community Liability", "Community Property", "Professional Risks"),
                trading=("Community Underwriting Office", "Community Broker Desk"),
                support=("Community Claims Centre",),
            ),
        ),
        "investments": (Trade(unit="Mutual Investments", categories=()),),
    },
    about="A member-owned insurer: a discretionary flavour to the wording, a"
          " community book nobody else wants to write, and an investment"
          " function answerable to policyholders.",
)


#: Every named vocabulary. Ordered by name at every use — a mosaic's fifth world
#: must speak the same words on every machine, and a dict that decided by
#: insertion order would make that a property of this file's history.
VOCABULARIES: dict[str, Vocabulary] = {
    "broker_lender": BROKER_LENDER,
    "broker_underwriter": BROKER_UNDERWRITER,
    "convenience_forecourt": CONVENIENCE_FORECOURT,
    "department_house": DEPARTMENT_HOUSE,
    "direct_insurer": DIRECT_INSURER,
    "discount_grocer": DISCOUNT_GROCER,
    "mutual_bank": MUTUAL_BANK,
    "mutual_insurer": MUTUAL_INSURER,
    "regional_trading_bank": REGIONAL_TRADING_BANK,
    "wholefoods_grocer": WHOLEFOODS_GROCER,
    "wholesale_club": WHOLESALE_CLUB,
}


def named(name: str) -> Vocabulary:
    """A vocabulary by name. Unknown names are refused, never defaulted.

    ``landscape.named``'s reasoning, and for a sharper reason: a build that
    asked for ``wholsale_club`` and silently got the archetype's own words would
    report five varied worlds and produce five identical ones, which is the
    exact defect this module was written to fix.
    """
    try:
        return VOCABULARIES[name]
    except KeyError:
        raise KeyError(
            f"unknown vocabulary {name!r}; known: {sorted(VOCABULARIES)}."
            " A pack authors its divisions on `Pack.units` instead."
        ) from None


def for_units(units: Sequence[Any]) -> tuple[str, ...]:
    """Every vocabulary that can fully dress *units*, sorted.

    Sorted rather than in registry order so that "the third vocabulary a retail
    mosaic can use" is a property of the names and not of where somebody added
    an entry to the table.
    """
    return tuple(
        name for name in sorted(VOCABULARIES) if VOCABULARIES[name].dresses(units)
    )


def for_engine(engine: str) -> tuple[str, ...]:
    """Every vocabulary that can dress the archetype *engine* builds by default.

    The engine names its own archetype (``domains.Domain.default_archetype``)
    and the archetype names its unit kinds, so nothing here holds a map from a
    vertical to its words — the same reason ``cli.py`` resolves a mosaic's shape
    through the domain registry rather than through a table in core.
    """
    from . import archetypes, domains

    registered = domains.by_name(engine)
    if registered is None or not registered.default_archetype:
        return ()
    return for_units(archetypes.get(registered.default_archetype).units)


def publish() -> dict[str, Any]:
    """Every vocabulary as data. An author cannot choose what they cannot see."""
    return {name: value.as_dict() for name, value in sorted(VOCABULARIES.items())}


__all__ = [
    "QUALIFIER", "VOCABULARIES", "Trade", "Vocabulary", "for_engine",
    "for_units", "named", "publish", "spoken",
]
