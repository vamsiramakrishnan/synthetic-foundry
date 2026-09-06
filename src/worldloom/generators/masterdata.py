"""Relational reference tables at scale: vendors, customers, SKUs.

A real ERP's master data runs to thousands of rows — a vendor register, a
customer book, an item master — where every Worldloom world so far has carried
at most a handful of counterparty *strings* (``procurement.py`` records "a
supplier is not an entity" as its sharpest gap). This module mints those tables
as data: deterministic, addressable by id, with parent/child integrity held by
construction rather than reviewed after the fact.

**Inside the determinism boundary, as data files.** Every name here is composed
from component pools in ``data/vocab/masterdata.json`` — invented brand stems,
trade nouns, street pools, SKU part names — committed to the repository beside
the locale vocabulary packs. No generation library is imported, in this module
or anywhere in ``src/``: a vocabulary that arrived via pip could move under a
pip upgrade, and a corpus whose vendor register renames itself between installs
fails the reason ledgers exist.

**Design acknowledgement.** Two ideas here follow the owner's prior art in
``ge-agent-factory/packages/synthkit`` (JS; a read-only reference, deliberately
not a dependency). First, the shared **contact pool**: the same invented humans
recur across collections — a vendor's contact and a customer's account manager
can be one person, not two unrelated strings — and each contact's email is
derived deterministically from their name (ASCII-folded), so name and address
can never disagree. Second, **per-collection, per-field stream derivation**:
synthkit derives a sub-stream from ``(seed, collection, field)`` via a hash
fold; the same granularity here rides the project's own ``Rng.derive`` — one
named child stream per collection per field — so adding a field to vendors can
never reshuffle a customer, and adding a vendor never moves a SKU.

**Uniqueness by construction, not by retry.** Vendor and customer names are
composed by indexing a shuffled stem pool against a shuffled trade pool
(``name_i = stems[i % S] + trades[i // S]``), which is injective for
``i < S x T`` — about 48,000 combinations against the shipped pools — so two
rows can no more share a name than two ids can. A rejection-sampling loop would
also work and would couple every row's draw to every earlier collision, which
is exactly the cross-talk the named streams exist to prevent. SKU names use the
same construction over qualifier x noun pairs.

**Opt-in, and recorded.** Nothing here runs unless a build asks
(``master_data`` on a world spec / ``Blueprint.master_data``). The recipe
records the requested counts — never the rows — and replay re-runs this same
construction, the posture ``physics`` and ``role_table`` take: the counts are
what the build was given, the rows are what they became.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..locales import DEFAULT as DEFAULT_LOCALE
from ..locales import Locale
from ..rng import Rng

#: The component pools, read once at import — `locales._vocabulary_pack`'s
#: posture: package data whose absence is a packaging defect, surfaced at
#: import rather than at the first opted-in build.
_VOCAB_PATH = Path(__file__).parent.parent / "data" / "vocab" / "masterdata.json"
_VOCAB: dict[str, tuple[str, ...]] = {
    key: tuple(str(entry) for entry in value)
    for key, value in json.loads(_VOCAB_PATH.read_text(encoding="utf-8")).items()
    if key != "about"
}

#: How many shared contacts a table mints. Small on purpose (synthkit ships 24
#: for the same reason): recurrence is the feature. Two thousand vendors served
#: by forty humans is what a vendor register actually looks like — the same
#: account manager's name against many suppliers — and it is what lets a
#: downstream consumer put one person in a vendor record, an approval chain,
#: and an email thread without three unrelated strings.
CONTACT_POOL_SIZE = 40

#: Payment-terms weights: most of the book on Net 30, tails either side. Zipf
#: in spirit (synthkit weights its enums so frequent values dominate), stated
#: as literals because five terms do not need a distribution function.
_TERMS_WEIGHTS = (0.15, 0.45, 0.2, 0.15, 0.05)

_SEGMENT_WEIGHTS = (0.2, 0.1, 0.3, 0.3, 0.1)


def _slug(text: str) -> str:
    """A name fragment as an email local-part token: ASCII-folded, lowercase.

    The synthkit rule verbatim (`personaSlug`), because it is the right one:
    an email derived from a name has to survive the name's diacritics, and
    folding at derivation time keeps the pair coherent by construction.
    """
    folded = unicodedata.normalize("NFKD", text)
    return "".join(c for c in folded if c.isascii() and c.isalnum()).lower()


@dataclass(frozen=True)
class Contact:
    """One invented human, shared across collections."""

    name: str
    email_local: str
    """``given.family``, folded. The domain half belongs to whichever company
    the contact is speaking for, so it is composed at the row, not here."""

    def as_dict(self) -> dict[str, Any]:
        return {"name": self.name, "email_local": self.email_local}


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    category: str
    payment_terms: str
    address: str
    contact_name: str
    contact_email: str
    postcode: str = ""
    phone: str = ""
    business_id: str = ""
    bank_account: str = ""
    """The four surface values (``surface.py``), filled only when a build asked
    for ``identifiers``. Empty strings otherwise, and ``as_dict`` omits an
    empty one — so a register minted before these fields existed writes the
    same bytes it always did, and a reader of an old ``masterdata.json`` finds
    no key it does not recognise."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "category": self.category,
            "payment_terms": self.payment_terms, "address": self.address,
            "contact_name": self.contact_name, "contact_email": self.contact_email,
            **_surface_fields(self),
        }


@dataclass(frozen=True)
class Customer:
    id: str
    name: str
    segment: str
    payment_terms: str
    address: str
    contact_name: str
    contact_email: str
    postcode: str = ""
    phone: str = ""
    business_id: str = ""
    bank_account: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "segment": self.segment,
            "payment_terms": self.payment_terms, "address": self.address,
            "contact_name": self.contact_name, "contact_email": self.contact_email,
            **_surface_fields(self),
        }


def _surface_fields(row: Any) -> dict[str, str]:
    """Only the surface values a row actually carries, in `surface.FIELDS` order."""
    from .. import surface

    return {name: getattr(row, name) for name in surface.FIELDS if getattr(row, name)}


@dataclass(frozen=True)
class Sku:
    id: str
    name: str
    vendor_id: str
    category: str
    """The vendor's own category, copied — never drawn. A SKU whose category
    disagreed with its supplier's would be the two-businesses-in-one-row
    incoherence ``vocabulary.py`` makes unrepresentable for divisions, showing
    up as a purchase line no spend report can bucket."""

    unit_price: float
    """Plain data, not a ``CanonicalFact``: a list price on a master record is
    reference data the way an address is, not an assertion any document cites.
    The moment an episode *transacts* at a price, the transaction mints facts
    through its own generators, as the P2P cycle already does."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "vendor_id": self.vendor_id,
            "category": self.category, "unit_price": self.unit_price,
        }


@dataclass(frozen=True)
class MasterData:
    """The reference tables one world carries. Immutable, like the world."""

    vendors: tuple[Vendor, ...] = ()
    customers: tuple[Customer, ...] = ()
    skus: tuple[Sku, ...] = ()
    contacts: tuple[Contact, ...] = ()

    def __post_init__(self) -> None:
        # Integrity held at construction, wherever the rows came from — a
        # generator bug and a hand-edited masterdata.json fail the same way.
        vendor_ids = {vendor.id: vendor for vendor in self.vendors}
        if len(vendor_ids) != len(self.vendors):
            raise ValueError("master data repeats a vendor id")
        if len({c.id for c in self.customers}) != len(self.customers):
            raise ValueError("master data repeats a customer id")
        if len({s.id for s in self.skus}) != len(self.skus):
            raise ValueError("master data repeats a SKU id")
        for sku in self.skus:
            parent = vendor_ids.get(sku.vendor_id)
            if parent is None:
                raise ValueError(
                    f"SKU {sku.id} names vendor {sku.vendor_id!r}, which this"
                    " table does not hold — a child row whose parent resolves"
                    " to nothing is the referential failure `worldloom"
                    " validate` treats as a defect everywhere else"
                )
            if sku.category != parent.category:
                raise ValueError(
                    f"SKU {sku.id} is categorised {sku.category!r} but its"
                    f" vendor {parent.id} supplies {parent.category!r}; a"
                    " SKU's category is its vendor's, copied, so a spend"
                    " report buckets the line and the supplier the same way"
                )

    def __bool__(self) -> bool:
        return bool(self.vendors or self.customers or self.skus)

    @property
    def counts(self) -> dict[str, int]:
        return {
            "vendors": len(self.vendors),
            "customers": len(self.customers),
            "skus": len(self.skus),
        }

    def as_dict(self) -> dict[str, Any]:
        return {
            "vendors": [v.as_dict() for v in self.vendors],
            "customers": [c.as_dict() for c in self.customers],
            "skus": [s.as_dict() for s in self.skus],
            "contacts": [c.as_dict() for c in self.contacts],
        }


def from_document(payload: Mapping[str, Any]) -> MasterData:
    """A table read back off a corpus. Integrity re-checked by ``__post_init__``."""
    return MasterData(
        vendors=tuple(Vendor(**row) for row in payload.get("vendors", ())),
        customers=tuple(Customer(**row) for row in payload.get("customers", ())),
        skus=tuple(Sku(**row) for row in payload.get("skus", ())),
        contacts=tuple(Contact(**row) for row in payload.get("contacts", ())),
    )


#: The knob's vocabulary, closed: a request naming anything else is a typo, and
#: a typo that silently minted nothing would report a smaller world as the one
#: that was asked for — `Parameters.with_overrides`'s argument.
REQUEST_KEYS = frozenset({"vendors", "customers", "skus", "identifiers"})

#: The largest request the committed vocabulary can satisfy without repeating
#: a supposedly unique business or item name.  This belongs at the request
#: boundary, not only in ``generate``: company specifications and SDK
#: blueprints promise to reject an impossible shape before an expensive world
#: build begins.
REQUEST_LIMITS = {
    "vendors": len(_VOCAB["company_stems"]) * len(_VOCAB["trades"]),
    "customers": len(_VOCAB["company_stems"]) * len(_VOCAB["trades"]),
    "skus": len(_VOCAB["sku_qualifiers"]) * len(_VOCAB["sku_nouns"]),
}


def check_request(request: Mapping[str, Any]) -> dict[str, int]:
    """A ``master_data`` request normalised, or a ValueError naming the defect.

    ``identifiers`` is the one key that is a switch rather than a count — 1 to
    fill postcodes, phones, registration numbers and bank accounts on every
    vendor and customer from ``surface.py``, 0 (or absent) to leave the
    register as it was. It rides the same request so the recipe records it the
    same way, and it is an int rather than a bool for the same reason: a
    recipe is JSON, and one representation is what lets two recipes that mean
    the same thing compare equal.
    """
    unknown = sorted(set(request) - REQUEST_KEYS)
    if unknown:
        raise ValueError(
            f"master_data does not take {unknown}; it takes"
            f" {sorted(REQUEST_KEYS)} — counts of reference rows to mint,"
            " and `identifiers` (0 or 1) to fill surface values on them"
        )
    counts: dict[str, int] = {}
    for key in sorted(request):
        value = int(request[key])
        if value < 0:
            raise ValueError(f"master_data.{key} is a count, and {value} is not one")
        if key == "identifiers" and value not in (0, 1):
            raise ValueError(f"master_data.identifiers is a switch, 0 or 1; got {value}")
        elif key in REQUEST_LIMITS and value > REQUEST_LIMITS[key]:
            raise ValueError(
                f"master_data.{key} asks for {value} unique rows, but the"
                f" committed vocabulary can compose only {REQUEST_LIMITS[key]}"
            )
        counts[key] = value
    if counts.get("skus", 0) and not counts.get("vendors", 0):
        raise ValueError(
            "master_data.skus are children of vendors; asking for skus with"
            " vendors=0 would mint rows whose parent table does not exist"
        )
    return counts


def _composed_names(rng: Rng, stems: Sequence[str], trades: Sequence[str],
                    count: int, suffix_pool: Sequence[str]) -> list[str]:
    """*count* unique company names: shuffled stem x shuffled trade, indexed.

    Injective for ``count <= len(stems) * len(trades)`` — see the module
    docstring for why indexing beats rejection sampling here. The legal-form
    suffix is a per-row draw from the locale's pool, because it carries no
    uniqueness burden: the (stem, trade) pair already does.
    """
    if count > len(stems) * len(trades):
        raise ValueError(
            f"asked for {count} names and the pools compose only"
            f" {len(stems) * len(trades)}"
        )
    shuffled_stems = rng.derive("stems").shuffled(stems)
    shuffled_trades = rng.derive("trades").shuffled(trades)
    suffix_rng = rng.derive("suffix")
    out = []
    for index in range(count):
        stem = shuffled_stems[index % len(shuffled_stems)]
        trade = shuffled_trades[index // len(shuffled_stems)]
        out.append(f"{stem} {trade} {suffix_rng.choice(suffix_pool)}")
    return out


def _address(rng: Rng, locale: Locale) -> str:
    """One line of invented geography. See ``_address_in``."""
    return _address_in(rng, locale)[0]


def _address_in(rng: Rng, locale: Locale) -> tuple[str, str]:
    """``(address line, city)`` — one line of invented geography, drawn from the
    locale the world is in, and the city it was drawn in.

    Street from the data file, city from the locale's own pool — and no region
    label, deliberately: ``Locale.regions`` and ``Locale.cities`` are parallel
    pools with no mapping between them, and "Adelaide ACT" is the kind of
    mismatch a local reader spots as synthetic from the punctuation
    (``locales.py``'s founding argument). A street-city-country line is
    plausible everywhere; a wrong state is plausible nowhere.
    """
    number = rng.derive("number").integer(1, 480)
    street = rng.derive("street").choice(_VOCAB["streets"])
    city, country = rng.derive("city").choice(locale.cities)
    return f"{number} {street}, {city}, {country}", city


def _contacts(rng: Rng, locale: Locale) -> tuple[Contact, ...]:
    """The shared contact pool, drawn from the locale's own name machinery.

    Deep pools via ``Locale.name_pool`` so the draw is independent of the
    employee roster's (different stream, and external people may legitimately
    share a name with staff — colliding streams, not colliding names, are the
    defect). Independent shuffles per half, ``names.people_names``'s rule, so
    no two contacts are the same person.
    """
    given = rng.derive("given").sample(
        locale.name_pool("given", CONTACT_POOL_SIZE), CONTACT_POOL_SIZE)
    family = rng.derive("family").sample(
        locale.name_pool("family", CONTACT_POOL_SIZE), CONTACT_POOL_SIZE)
    return tuple(
        Contact(name=f"{g} {f}", email_local=f"{_slug(g)}.{_slug(f)}")
        for g, f in zip(given, family)
    )


def _domain_of(company_name: str) -> str:
    """A mail domain from a composed company name: the stem, folded.

    The stem alone rather than the whole name, because that is what a company
    does to its own domain — Oakhurst Freight Pty Ltd is oakhurst.example —
    and ``.example`` because RFC 2606 reserves it: an invented register must
    not mint routable addresses."""
    return f"{_slug(company_name.split()[0])}.example"


def generate(
    rng: Rng,
    *,
    vendors: int = 0,
    customers: int = 0,
    skus: int = 0,
    locale: Locale = DEFAULT_LOCALE,
    categories: Sequence[str] = (),
    identifiers: bool = False,
    surface_provider: Any = None,
) -> MasterData:
    """Mint the requested reference tables. Same seed, same rows, every time.

    ``identifiers`` fills the four surface values on every vendor and
    customer through ``surface_provider`` (the vendored default when
    ``None``). Each value is keyed by ``StableKey(seed, entity type, entity
    id, field)`` under the provider's version — *not* drawn from this
    function's streams — so switching identifiers on moves no name, address
    or contact, and a vendor's phone number is the same whether the register
    has ten rows or ten thousand.

    ``categories`` is the world's own spend/category vocabulary when the caller
    has one; empty falls back to the data file's generic spend categories, so a
    table minted without a world still buckets its vendors. SKUs are children:
    each is assigned a parent vendor (weighted toward the head of the register,
    the way a real item master concentrates on a few suppliers) and copies its
    category. Asking for SKUs with no vendors is refused — a child table with
    no parent table cannot hold integrity.

    Stream discipline: one named child per collection, one per field within
    it — ``masterdata/vendors/terms`` and so on — so no count perturbs any
    other collection's draws and adding a field never reshuffles its
    neighbours. (Granularity per the synthkit reference; mechanism per
    ``worldloom.rng``.)
    """
    if skus and not vendors:
        raise ValueError(
            "SKUs are children of vendors; asking for skus with vendors=0"
            " would mint rows whose parent table does not exist"
        )
    pool = tuple(categories) or _VOCAB["spend_categories"]
    contacts = _contacts(rng.derive("contacts"), locale)

    vendor_rows: list[Vendor] = []
    if vendors:
        stream = rng.derive("vendors")
        # An industry-neutral supplier registry: the trade noun carries what
        # the company does, the locale's *retail* pool would brand every
        # supplier a trading group, so the suffix pool is the locale's own
        # generic tail — the last entries of `company_suffixes` are the
        # jurisdiction's plain legal/holding forms in every shipped preset.
        names = _composed_names(
            stream.derive("names"), _VOCAB["company_stems"], _VOCAB["trades"],
            vendors, locale.company_suffixes,
        )
        terms_rng = stream.derive("terms")
        category_rng = stream.derive("category")
        address_rng = stream.derive("address")
        contact_rng = stream.derive("contact")
        for index, name in enumerate(names, start=1):
            contact = contact_rng.choice(contacts)
            address, city = _address_in(address_rng.derive(str(index)), locale)
            vendor_id = f"VND-{index:05d}"
            vendor_rows.append(Vendor(
                id=vendor_id,
                name=name,
                category=category_rng.choice(pool),
                payment_terms=terms_rng.weighted(_VOCAB["payment_terms"], _TERMS_WEIGHTS),
                address=address,
                contact_name=contact.name,
                contact_email=f"{contact.email_local}@{_domain_of(name)}",
                **_identifiers(rng, "vendor", vendor_id, locale, city, identifiers, surface_provider),
            ))

    customer_rows: list[Customer] = []
    if customers:
        stream = rng.derive("customers")
        names = _composed_names(
            stream.derive("names"), _VOCAB["company_stems"], _VOCAB["trades"],
            customers, locale.company_suffixes,
        )
        terms_rng = stream.derive("terms")
        segment_rng = stream.derive("segment")
        address_rng = stream.derive("address")
        contact_rng = stream.derive("contact")
        for index, name in enumerate(names, start=1):
            contact = contact_rng.choice(contacts)
            address, city = _address_in(address_rng.derive(str(index)), locale)
            customer_id = f"CUS-{index:05d}"
            customer_rows.append(Customer(
                id=customer_id,
                name=name,
                segment=segment_rng.weighted(_VOCAB["customer_segments"], _SEGMENT_WEIGHTS),
                payment_terms=terms_rng.weighted(_VOCAB["payment_terms"], _TERMS_WEIGHTS),
                address=address,
                contact_name=contact.name,
                contact_email=f"{contact.email_local}@{_domain_of(name)}",
                **_identifiers(rng, "customer", customer_id, locale, city, identifiers, surface_provider),
            ))

    sku_rows: list[Sku] = []
    if skus:
        stream = rng.derive("skus")
        qualifiers = stream.derive("qualifiers").shuffled(_VOCAB["sku_qualifiers"])
        nouns = stream.derive("nouns").shuffled(_VOCAB["sku_nouns"])
        if skus > len(qualifiers) * len(nouns):
            raise ValueError(
                f"asked for {skus} SKUs and the pools compose only"
                f" {len(qualifiers) * len(nouns)} distinct names"
            )
        parent_rng = stream.derive("vendor")
        price_rng = stream.derive("price")
        for index in range(1, skus + 1):
            name = (f"{qualifiers[(index - 1) % len(qualifiers)]}"
                    f" {nouns[(index - 1) // len(qualifiers)]}")
            # Head-weighted parent draw: min of two uniforms concentrates the
            # item master on the front of the register, the way a real one
            # leans on a few suppliers, without a distribution function.
            position = min(parent_rng.integer(0, len(vendor_rows) - 1),
                           parent_rng.integer(0, len(vendor_rows) - 1))
            parent = vendor_rows[position]
            sku_rows.append(Sku(
                id=f"SKU-{index:05d}",
                name=name,
                vendor_id=parent.id,
                category=parent.category,
                unit_price=price_rng.number(4.0, 900.0, places=2),
            ))

    return MasterData(
        vendors=tuple(vendor_rows),
        customers=tuple(customer_rows),
        skus=tuple(sku_rows),
        contacts=contacts,
    )


def _identifiers(rng: Rng, entity_type: str, entity_id: str, locale: Locale, city: str,
                 wanted: bool, provider: Any) -> dict[str, str]:
    """The surface values for one row, or nothing when the build did not ask."""
    if not wanted:
        return {}
    from .. import surface

    return surface.identifiers(
        seed=rng.seed, entity_type=entity_type, entity_id=entity_id,
        locale=locale, city=city, provider=provider or surface.DEFAULT,
    )


def applied(world: Any, request: Mapping[str, Any] | None, *,
            locale: Locale = DEFAULT_LOCALE) -> Any:
    """*world* carrying the requested tables, or untouched when none were asked.

    The one-line seam each world builder calls after minting its organisation.
    ``None``/empty is a strict no-op — the world object comes back identical,
    which is what keeps every un-opted build byte-for-byte what it was. The
    stream is derived from the world's own seed under a root of its own
    (``masterdata``), so no existing generator's draws move whatever is asked
    for here.

    Categories come off the world's own dimension table when it has one: a
    vendor register bucketed in the company's own category vocabulary is what
    lets a spend report join the two.
    """
    if not request:
        return world
    from dataclasses import replace as _replace

    counts = check_request(request)
    if not any(value for key, value in counts.items() if key != "identifiers"):
        # `identifiers: 1` with nothing to put them on is a no-op, not a table.
        return world
    table = generate(
        Rng(world.seed).derive("masterdata"),
        vendors=counts.get("vendors", 0),
        customers=counts.get("customers", 0),
        skus=counts.get("skus", 0),
        locale=locale,
        categories=tuple(category.name for category in world._categories),
        identifiers=bool(counts.get("identifiers", 0)),
    )
    return _replace(world, _masterdata=table)


__all__ = [
    "CONTACT_POOL_SIZE", "Contact", "Customer", "MasterData", "REQUEST_KEYS",
    "REQUEST_LIMITS", "Sku", "Vendor", "applied", "check_request",
    "from_document", "generate",
]
