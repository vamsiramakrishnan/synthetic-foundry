"""Surface values: the postcode, phone, registration number and bank account an
entity would carry — locale-correct, checksum-valid, and vendored.

The gap this closes is measured. Four locales ship, each with regions, cities,
name pools and number punctuation, and not one of them can put a postcode on an
address, a phone number on a vendor, or a registration number on a company. A
vendor register with 2,000 rows and no ABN, no VAT number and no bank account is
a register a local reader spots as synthetic from the second row.

The tempting fix is ``pip install faker``, and this project has refused it twice
already (``detail.py``, ``generators/masterdata.py``): a value drawn from a
third-party dataset is a value a seed cannot mean across versions, because the
dataset moves under a pip upgrade and an old corpus's vendors silently acquire
new phone numbers. Recording the faker version in the recipe would *detect* the
drift; it would not prevent it, and it would pin every old corpus to a package
version forever.

So the rules are **data in this repository**, versioned, and every value is a
pure function of a ``StableKey`` — ``seed / provider version / entity type /
entity id / field`` — so that:

* upgrading the rules file bumps its version and *old* keys keep replaying
  under the old version's path, which is what "the version is in the path"
  buys that "the version is in a note" does not;
* adding a field to vendors cannot move a single customer's phone number,
  because no two fields share a stream;
* two entities never share a stream, so a rule change for one country cannot
  reshuffle another's values.

**Checksums are real.** An ABN validates under the ATO's weighted mod-89, a
German USt-IdNr under the 11-10 procedure, an Austrian UID under its digit-sum
rule, a UK VAT number under mod-97, a New Zealand NZBN under GS1 mod-10, and
every IBAN under ISO 7064 mod-97. A number that *looks* right and fails the
check a real system runs is the kind of tell that makes a corpus useless for
testing the system; a number that passes is one the downstream ERP will accept.
No identifier here is a real organisation's: the bodies of the numbers are
drawn, only the check digits are computed.

**Leaf values only.** This module decides nothing about who an entity is, whom
it trades with, or what happened. ``SurfaceValueProvider`` is the seam
(``providers.py``); this is its vendored default, and a provider that wanted to
draw from somewhere else would implement the same four methods under its own
``id`` and ``version`` — and the recipe would record which one filled the rows.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from .locales import Locale
from .providers import Receipt, StableKey, digest
from .rng import Rng

_RULES_PATH = Path(__file__).parent / "data" / "surface" / "rules.json"

#: Letters permitted in the *unit* half of a UK postcode's inward code. Royal
#: Mail excludes C, I, K, M, O and V because they are too easily misread.
_UK_UNIT_LETTERS = "ABDEFGHJLNPQRSTUWXYZ"

#: The alphabet IBAN and mod-97 checks convert letters through: A=10 … Z=35.
_ALPHABET = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"


@lru_cache(maxsize=1)
def _document() -> dict[str, Any]:
    """The rules file, read once. Absence is a packaging defect, surfaced at
    first use rather than as a silently empty register."""
    return json.loads(_RULES_PATH.read_text(encoding="utf-8"))


def version() -> str:
    """The rules version a *new* build uses."""
    return str(_document()["current"])


def versions() -> tuple[str, ...]:
    """Every rules version the file still carries, oldest first.

    Every version is kept, because a corpus records the one it was built
    under and must replay under exactly those rules. The Codex review of PR
    #40 named the hole this closes: with one live rule set, a bump would have
    re-derived every postcode in every existing corpus on its next rebuild,
    the version being in every stream's path.
    """
    return tuple(sorted(_document()["versions"], key=int))


def rules(version: str | None = None) -> dict[str, Any]:
    """The rule set for *version* (the current one when ``None``)."""
    chosen = str(version) if version is not None else version_default()
    try:
        return _document()["versions"][chosen]
    except KeyError:
        raise KeyError(
            f"surface rules version {chosen!r} is not in this build; it carries"
            f" {list(versions())}. A corpus built under a version this package"
            " has lost cannot replay its identifiers — versions are kept, never"
            " removed, precisely so this does not happen."
        ) from None


def version_default() -> str:
    return version()


# ---------------------------------------------------------------------------
# Check-digit arithmetic — each one the algorithm the issuing body publishes
# ---------------------------------------------------------------------------


def _digits(rng: Rng, count: int, *, first_nonzero: bool = False) -> str:
    out = []
    for index in range(count):
        low = 1 if (first_nonzero and index == 0) else 0
        out.append(str(rng.integer(low, 9)))
    return "".join(out)


def mod97(value: str) -> int:
    """ISO 7064 mod-97 over a string whose letters read A=10 … Z=35.

    Chunked rather than converted to one integer: Python would cope with the
    big integer, but the chunked form is the one every reference
    implementation uses, and matching it is what makes "valid under the same
    rule the bank runs" a checkable claim rather than a hope.
    """
    numeric = "".join(str(_ALPHABET.index(ch)) for ch in value.upper())
    remainder = 0
    for chunk_start in range(0, len(numeric), 7):
        remainder = int(str(remainder) + numeric[chunk_start:chunk_start + 7]) % 97
    return remainder


def iban(country: str, bban: str) -> str:
    """A valid IBAN for *country* over *bban*: check digits computed, not drawn."""
    check = 98 - mod97(f"{bban}{country}00")
    return f"{country}{check:02d}{bban}"


def iban_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    return mod97(compact[4:] + compact[:4]) == 1


def abn(rng: Rng) -> str:
    """An Australian Business Number: nine drawn digits, two computed.

    The ATO rule: subtract 1 from the first digit, weight the eleven digits by
    10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19, and the sum is divisible by 89.
    Solved for the leading pair rather than searched — there is exactly one
    two-digit prefix in 10..99 for each nine-digit body that satisfies it.
    """
    body = _digits(rng, 9)
    for prefix in range(10, 100):
        candidate = f"{prefix:02d}{body}"
        if abn_valid(candidate):
            return candidate
    raise AssertionError("every nine-digit body has a valid ABN prefix")  # pragma: no cover


_ABN_WEIGHTS = (10, 1, 3, 5, 7, 9, 11, 13, 15, 17, 19)


def abn_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    if len(compact) != 11 or not compact.isdigit():
        return False
    digits = [int(ch) for ch in compact]
    digits[0] -= 1
    return sum(d * w for d, w in zip(digits, _ABN_WEIGHTS)) % 89 == 0


def gs1_check(body: str) -> str:
    """GS1 mod-10 check digit (GTIN, NZBN): weights 3 and 1 from the right."""
    total = 0
    for index, ch in enumerate(reversed(body)):
        total += int(ch) * (3 if index % 2 == 0 else 1)
    return str((10 - total % 10) % 10)


def de_ustid(rng: Rng) -> str:
    """A German USt-IdNr: ``DE`` + eight drawn digits + the 11-10 check digit.

    The Bundeszentralamt's procedure: product starts at 10; for each digit,
    sum = (digit + product) mod 10, with 0 read as 10; product = (2 × sum)
    mod 11; the check is 11 − product, with 10 read as 0.
    """
    body = _digits(rng, 8, first_nonzero=True)
    return f"DE{body}{_de_check(body)}"


def _de_check(body: str) -> str:
    product = 10
    for ch in body:
        total = (int(ch) + product) % 10
        if total == 0:
            total = 10
        product = (2 * total) % 11
    check = 11 - product
    return str(0 if check == 10 else check)


def de_ustid_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    if len(compact) != 11 or not compact.startswith("DE") or not compact[2:].isdigit():
        return False
    return _de_check(compact[2:10]) == compact[10]


def at_uid(rng: Rng) -> str:
    """An Austrian UID: ``ATU`` + seven drawn digits + a digit-sum check.

    Weights alternate 1, 2 across the seven digits; the doubled positions are
    digit-summed; the check is (96 − total) mod 10.
    """
    body = _digits(rng, 7, first_nonzero=True)
    return f"ATU{body}{_at_check(body)}"


def _at_check(body: str) -> str:
    total = 0
    for index, ch in enumerate(body):
        d = int(ch)
        if index % 2 == 0:
            total += d
        else:
            doubled = 2 * d
            total += doubled // 10 + doubled % 10
    return str((96 - total) % 10)


def at_uid_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    if len(compact) != 11 or not compact.startswith("ATU") or not compact[3:].isdigit():
        return False
    return _at_check(compact[3:10]) == compact[10]


def gb_vat(rng: Rng) -> str:
    """A UK VAT registration number, nine digits under the mod-97 rule.

    Weights 8..2 over the first seven digits; subtract 97 until the total is
    negative; the last two digits are the absolute value. Bodies are drawn in
    the range HMRC issues (first digit 1–9).
    """
    body = _digits(rng, 7, first_nonzero=True)
    total = sum(int(ch) * w for ch, w in zip(body, range(8, 1, -1)))
    while total > 0:
        total -= 97
    return f"GB{body}{abs(total):02d}"


def gb_vat_valid(value: str) -> bool:
    compact = value.replace(" ", "")
    if len(compact) != 11 or not compact.startswith("GB") or not compact[2:].isdigit():
        return False
    body, check = compact[2:9], compact[9:]
    total = sum(int(ch) * w for ch, w in zip(body, range(8, 1, -1)))
    while total > 0:
        total -= 97
    return f"{abs(total):02d}" == check


# ---------------------------------------------------------------------------
# The vendored provider
# ---------------------------------------------------------------------------


def _pattern(rng: Rng, pattern: str, *, area: str = "") -> str:
    """Fill a pattern: ``#`` is a drawn digit, ``@`` is the area code verbatim."""
    out: list[str] = []
    for ch in pattern:
        if ch == "#":
            out.append(str(rng.integer(0, 9)))
        elif ch == "@":
            out.append(area)
        else:
            out.append(ch)
    return "".join(out)


def _group(digits: str, size: int) -> str:
    return " ".join(digits[i:i + size] for i in range(0, len(digits), size))


class Vendored:
    """The default provider: rules from ``data/surface/rules.json``, nothing else.

    Country is resolved from the *city*, through the locale's own
    ``(city, country)`` pairs, because a locale is a jurisdiction and a
    jurisdiction can span more than one country's numbering — the Gulf locale
    has Dubai and Doha, and a Qatari company with a UAE tax number is exactly
    the punctuation-level tell ``locales.py`` was written to stop.

    Pinned to one rules version for its whole life. ``DEFAULT`` is pinned to
    the current one; a replay constructs ``Vendored(version=...)`` from what
    the recipe recorded, and reads that version's rules and nothing newer.
    """

    id = "vendored"

    def __init__(self, version: str | None = None) -> None:
        self._version = str(version) if version is not None else version_default()
        rules(self._version)  # refuse an unknown version at construction, not at the first vendor

    @property
    def version(self) -> str:
        return self._version

    # -- resolution ---------------------------------------------------------

    @staticmethod
    def country_of(locale: Locale, city: str) -> str:
        for name, country in locale.cities:
            if name == city:
                return country
        # A city the locale does not list (a pack's own) falls to the locale's
        # first country — the jurisdiction the locale is named for.
        return locale.cities[0][1] if locale.cities else ""

    def _rules_for(self, locale: Locale, city: str) -> tuple[str, Mapping[str, Any]]:
        country = self.country_of(locale, city)
        table = rules(self._version)["countries"]
        if country in table:
            return country, table[country]
        return country, table["_generic"]

    # -- the four leaf values ------------------------------------------------

    def postcode(self, key: StableKey, locale: Locale, *, city: str) -> str:
        country, rule = self._rules_for(locale, city)
        rng = key.stream(self.version)
        spec = rule["postcode"]
        kind = spec["kind"]
        if kind == "range_by_city":
            low, high = spec.get("cities", {}).get(city, spec["default"])
            return f"{rng.integer(int(low), int(high)):0{int(spec['width'])}d}"
        if kind == "uk":
            areas = spec.get("cities", {}).get(city, spec["default"])
            area = rng.derive("area").choice(areas)
            district = rng.derive("district").integer(1, 20)
            sector = rng.derive("sector").integer(0, 9)
            unit = "".join(rng.derive("unit").choice(_UK_UNIT_LETTERS) for _ in range(2))
            return f"{area}{district} {sector}{unit}"
        if kind == "po_box":
            return f"P.O. Box {rng.integer(int(spec['low']), int(spec['high']))}"
        if kind == "fixed_width":
            return _digits(rng, int(spec["width"]), first_nonzero=True)
        raise ValueError(f"{country}: unknown postcode rule {kind!r}")

    def phone(self, key: StableKey, locale: Locale, *, city: str) -> str:
        _country, rule = self._rules_for(locale, city)
        rng = key.stream(self.version)
        spec = rule["phone"]
        mobile = key.field.endswith("mobile")
        # A city may carry its own landline shape: London's 020 has eight local
        # digits where Manchester's 0161 has seven, and one national pattern
        # would print a London number a Londoner would not dial.
        pattern = spec["mobile"] if mobile else spec.get("landline_by_city", {}).get(city, spec["landline"])
        area = spec.get("area_by_city", {}).get(city, spec.get("area_default", ""))
        return _pattern(rng, pattern, area=area)

    def business_identifier(self, key: StableKey, locale: Locale, *, city: str) -> str:
        country, rule = self._rules_for(locale, city)
        rng = key.stream(self.version)
        kind = rule["business_identifier"]["kind"]
        if kind == "abn":
            return _format_abn(abn(rng))
        if kind == "nzbn":
            body = "9429" + _digits(rng, 8)
            return body + gs1_check(body)
        if kind == "de_ustid":
            return de_ustid(rng)
        if kind == "at_uid":
            return at_uid(rng)
        if kind == "gb_vat":
            value = gb_vat(rng)
            return f"{value[:2]} {value[2:5]} {value[5:9]} {value[9:]}"
        if kind == "pattern":
            return _pattern(rng, rule["business_identifier"]["pattern"])
        raise ValueError(f"{country}: unknown business identifier rule {kind!r}")

    def bank_account(self, key: StableKey, locale: Locale, *, city: str) -> str:
        country, rule = self._rules_for(locale, city)
        rng = key.stream(self.version)
        spec = rule["bank_account"]
        kind = spec["kind"]
        if kind == "iban":
            bban = _pattern(rng, spec["bban"])
            return _group(iban(spec["country"], bban), 4)
        if kind == "pattern":
            return _pattern(rng, spec["pattern"])
        raise ValueError(f"{country}: unknown bank account rule {kind!r}")


def _format_abn(value: str) -> str:
    return f"{value[:2]} {value[2:5]} {value[5:8]} {value[8:]}"


DEFAULT = Vendored()

#: The fields ``identifiers`` fills, in the order they are written. Order is
#: part of the contract only in the sense that a row's keys print in it; each
#: field draws from its own stream, so the order could change without moving a
#: value.
FIELDS: tuple[str, ...] = ("postcode", "phone", "business_id", "bank_account")


def identifiers(
    *,
    seed: int,
    entity_type: str,
    entity_id: str,
    locale: Locale,
    city: str,
    provider: Any = DEFAULT,
) -> dict[str, str]:
    """The four leaf values for one entity, each from its own stable stream,
    under whatever rules version *provider* is pinned to."""
    def key(field: str) -> StableKey:
        return StableKey(seed, entity_type, entity_id, field)

    return {
        "postcode": provider.postcode(key("postcode"), locale, city=city),
        "phone": provider.phone(key("phone"), locale, city=city),
        "business_id": provider.business_identifier(key("business_id"), locale, city=city),
        "bank_account": provider.bank_account(key("bank_account"), locale, city=city),
    }


def receipt(*, seed: int, filled: int, provider: Any = DEFAULT, locale: str = "") -> Receipt:
    """The receipt a build leaves for having filled *filled* entities.

    No source digest — the provider read nothing outside the repository — and
    the accepted digest is over the count and the configuration rather than
    the values: the values are a pure function of the seed and the version
    recorded here, so re-deriving them is the check, not re-reading them.
    """
    configuration = {"provider": provider.id, "version": provider.version, "locale": locale}
    return Receipt(
        backend=provider.id, backend_version=provider.version,
        operation="surface_values", configuration_digest=digest(configuration),
        seed=seed, accepted_digest=digest({"filled": filled, **configuration}),
    )


__all__ = [
    "DEFAULT", "FIELDS", "Vendored", "abn", "abn_valid", "at_uid", "at_uid_valid",
    "de_ustid", "de_ustid_valid", "gb_vat", "gb_vat_valid", "gs1_check", "iban",
    "iban_valid", "identifiers", "mod97", "receipt", "rules", "version", "versions",
]
