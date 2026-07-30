"""Fact references, and the rule that keeps documents in agreement.

Generated prose carries ``{{fact:FACT-0004}}`` where a figure belongs. The value is
substituted at render time, from the ledger, by whichever renderer is emitting the
document.

That single indirection is what stops a board deck from disagreeing with the
workbook it was derived from: both read the same ledger entry, and neither holds a
copy of the number. Change the fact and every document that references it moves
together, because none of them ever stored it.

The complementary rule lives in ``claims.py``: a model may not emit a bare numeral
at all. Substitution guarantees literals cannot drift; claim validation catches
assertions that drift without a literal in them.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact

REFERENCE = re.compile(r"\{\{fact:(?P<id>[A-Z][A-Z0-9]*-[A-Z0-9-]+)\}\}")

#: A digit run outside a reference. Prose is not allowed to contain one — that is
#: the arithmetic rule, enforced lexically.
BARE_NUMBER = re.compile(r"(?<!\{)\b\d[\d,.]*\b(?!\}\})")


def referenced(text: str) -> list[str]:
    """Every fact ID referenced in *text*, in order, deduplicated."""
    seen: dict[str, None] = {}
    for match in REFERENCE.finditer(text):
        seen.setdefault(match.group("id"), None)
    return list(seen)


def strip_references(text: str) -> str:
    """*text* with every reference removed, for lexical checks on the prose itself."""
    return REFERENCE.sub("", text)


def bare_numbers(text: str) -> list[str]:
    """Digit runs that sit outside a fact reference.

    Any hit is a violation: a model that writes ``2.48%`` has restated a number it
    should have referenced, and that copy can drift from the ledger.
    """
    return BARE_NUMBER.findall(strip_references(text))


def render_value(fact: CanonicalFact) -> str:
    """A fact as a reader would see it in prose.

    Formatting lives here rather than at each call site so that the same fact reads
    identically in every document that references it.
    """
    if fact.value is None:
        return fact.text_value or ""

    amount, unit = fact.value.amount, fact.value.unit
    magnitude = f"{abs(amount):,.0f}" if float(amount).is_integer() else f"{abs(amount):,.2f}"

    if unit == "percent":
        return f"{amount:.2f}%"
    if unit == "bps":
        return f"{abs(amount):,.0f} bps {'adverse' if amount < 0 else 'favourable'}"
    if unit.startswith(("AUD", "USD", "GBP", "EUR")):
        currency, _, scale = unit.partition("_")
        rendered = f"{currency} {magnitude}"
        if scale:
            rendered += f" {scale}"
        return f"{rendered} adverse" if amount < 0 else rendered
    if unit == "business_days":
        return f"{magnitude} business day" + ("" if amount == 1 else "s")
    return f"{magnitude} {unit}"


def substitute(text: str, facts: dict[str, CanonicalFact]) -> str:
    """Replace every reference in *text* with its fact's value.

    An unresolvable reference is left visible as ``[missing FACT-0001]`` rather
    than silently dropped. A document with a hole in it is a bug worth seeing; one
    that quietly omits a figure reads as complete and is not.
    """

    def replace(match: re.Match[str]) -> str:
        fact = facts.get(match.group("id"))
        return render_value(fact) if fact else f"[missing {match.group('id')}]"

    return REFERENCE.sub(replace, text)


def unresolved(text: str, facts: dict[str, CanonicalFact]) -> list[str]:
    """References in *text* that *facts* cannot resolve."""
    return [fact_id for fact_id in referenced(text) if fact_id not in facts]
