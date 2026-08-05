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

#: Anything *shaped* like a reference, however malformed its id. ``REFERENCE``
#: alone is not enough for validation, and the gap was found live, not in
#: review: Gemini, asked for ``{{fact:FACT-0001}}``, wrote ``{{fact:0001}}`` —
#: which ``REFERENCE`` does not match (so it was never checked against the
#: ledger) and whose digits ``BARE_NUMBER``'s trailing ``(?!\}\})`` lookahead
#: excuses (that escape exists for digits inside *well-formed* references).
#: Each pattern's escape hatch sat exactly over the other's blind spot, and the
#: malformed reference sailed through to render as literal mustache in the
#: document. Validation therefore checks everything reference-shaped; only
#: ``REFERENCE`` itself is used for substitution.
REFERENCE_SHAPED = re.compile(r"\{\{fact:(?P<id>[^{}]*)\}\}")

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
    if _is_money(unit):
        currency, _, scale = unit.partition("_")
        rendered = f"{currency} {magnitude}"
        if scale:
            rendered += f" {scale}"
        return f"{rendered} adverse" if amount < 0 else rendered
    if unit == "business_days":
        return f"{magnitude} business day" + ("" if amount == 1 else "s")
    return f"{magnitude} {unit}"


def _is_money(unit: str) -> bool:
    """Whether a unit names a currency, by its shape rather than by a list.

    This was an allow-list of four — AUD, USD, GBP, EUR — and `Pack.currency`
    has always accepted any string. So a pack denominated in AED, CHF, SGD, JPY
    or INR fell through to the generic branch and printed
    `240,900 AED_thousands` instead of `AED 240,900 thousands`, and silently
    lost the ` adverse` suffix that tells a reader a negative variance is bad
    news. A live defect for every currency nobody thought to add, and the kind
    that gets found by a reader rather than by a test.

    ISO 4217 is exactly three uppercase letters, which no other unit this corpus
    mints resembles — `percent`, `bps`, `business_days` and `SKUs` are all
    lowercase-led or longer. Matching the shape means a currency works because
    it is a currency, not because somebody remembered it.
    """
    head, _, _ = unit.partition("_")
    return len(head) == 3 and head.isascii() and head.isupper() and head.isalpha()


def describe(fact: CanonicalFact, subject: str | None = None) -> str:
    """A fact as one line: what it is about, what it measures, and what it says.

    The subject is the whole point of this function. Without it, a request
    carrying four business units' revenue is four indistinguishable numbers, and a
    writer handed them can only produce four identical sentences — which is
    exactly what happened until this existed. "Australian Food revenue was X, New
    Zealand Food Y" is not writable from ``financial.revenue.actual = 614,400``
    repeated four times, however good the writer.

    The measure goes through ``render_value`` rather than a format string of its
    own, so a figure reads the same here as it does in finished prose. Formatting
    it separately is how ``3.4935e+06`` reached a supporting-facts table that a
    human was supposed to read.
    """
    measure = render_value(fact) if fact.value is not None else (fact.text_value or "")
    lead = f"{subject} · " if subject else ""
    return f"{lead}{fact.kind} = {measure}" if measure else f"{lead}{fact.kind}"


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
    """Everything reference-shaped in *text* that *facts* cannot resolve.

    Scans ``REFERENCE_SHAPED``, not ``REFERENCE``: a malformed id
    (``{{fact:0001}}``) is exactly as unresolvable as a well-formed unknown one
    (``{{fact:FACT-9999}}``), and it is the render-time substitution — which
    only matches well-formed references — that makes catching it here the last
    line of defence before literal mustache lands in a document.
    """
    seen: dict[str, None] = {}
    for match in REFERENCE_SHAPED.finditer(text):
        fact_id = match.group("id")
        if fact_id not in facts:
            seen.setdefault(fact_id, None)
    return list(seen)
