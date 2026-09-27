"""How a figure is spelled for a reader, and how a copy of one is recognised.

``narrative.references.render_value`` spells one fact, alone. That was enough
while every spelling was the ledger's own: a fact reads the same wherever it
is cited. It stopped being enough the moment a profile promoted magnitudes,
because a sentence is not a list of independent figures. The shipped reader
profile printed "Food's gross profit of AUD 93.421m compares with a planned
AUD 100.443m" two lines under "revenue of AUD 617.2m", "AUD 958 thousands
adverse" beside "AUD 10.2m adverse", and "The number that matters is AUD 0
thousands". Each spelling was exact and the paragraph read like a ledger
export, because precision was decided per fact and a reader reads per
sentence.

So the spelling is a rulebook the presentation profile names (its
``spelling`` knob), kept as data in ``_data/presentation/spelling.json``:

* **Rounding per magnitude.** Money is spelled at the magnitude a memo uses
  (``bn``, ``m``, ``k``) with that magnitude's places (two, one, none), and
  never fewer significant figures than the rulebook's floor.
* **One precision per sentence.** Money figures in one sentence share the
  sentence's largest magnitude when they are at least a tenth of it (a gap of
  AUD 0.96m beside revenue of AUD 617.2m, not AUD 958k), and figures in one
  unit share one number of places. Percentages likewise.
* **Words a reader uses.** ``k``, never "thousands" after a figure; a zero is
  "nil" (prompts pack ``render.figures.zero``); a percentage is ``%`` even
  where the ledger's unit is ``pct``; a unit recorded as ``loan_facilities``
  reads "loan facilities"; an ISO date reads "24 April 2026"; a recorded enum
  value (``control_failure: ...``) reads in words.
* **The direction once.** A negative figure whose clause already says it
  went the wrong way drops its "adverse": after a phrase ("a shortfall of",
  prompts pack ``render.figures.direction_phrases``) and, since a live board
  deck printed "missing revenue plan by AUD 10.2m adverse", wherever a
  direction word sits in the figure's clause (`direction`: a verb or noun
  lexicon in ``render.figures.direction_words.*``, "missing", "fell",
  "overspent", "below budget"). A clause that says the other way ("ahead of
  plan by") keeps the word, and `defects` refuses the contradiction.

**A rounding is a spelling, never a value.** The ledger figure does not
move; the IR, the tables and the appendix of sources keep it. And because a
reader copying a rounded figure out of a sentence has copied the fact
correctly, the checks that compare what a reader recovered against the
ledger accept it through `agrees`: a spelling is accepted when it is a
correct rounding of the fact at the precision it shows, with at least the
rulebook's significant figures, and refused otherwise. "AUD 151.3m" is
AUD 151,325 thousands; "AUD 151.4m" is not, and neither is "AUD 150m".

`defects` is the other direction: a lexical reading of spelled text for the
mistakes this module exists to prevent, used by the claim validator on a
writer's prose (after substitution, so a writer who types "thousands" after a
reference is refused) and by `prose_quality` as a reading.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime
from functools import lru_cache
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:  # pragma: no cover
    from .locales import Locale
    from .models import CanonicalFact, Table
    from .presentation import Presentation

__all__ = [
    "DATA",
    "Rules",
    "agrees",
    "defects",
    "direction",
    "enum_values",
    "humanise",
    "rules_for",
    "spell_all",
    "spell_one",
    "spellings_of",
    "spellings",
    "table_units",
    "unit_caption",
]

DATA = "_data/presentation/spelling.json"


@dataclass(frozen=True)
class Magnitude:
    suffix: str
    factor: float
    places: int


@dataclass(frozen=True)
class Rules:
    """One spelling from the rulebook."""

    name: str
    magnitudes: tuple[Magnitude, ...]
    scales: Mapping[str, float]
    min_significant: int
    consolidate_share: float
    percent_units: tuple[str, ...]
    percent_places: int
    dates: bool
    enums: bool


@lru_cache(maxsize=1)
def _book() -> Mapping[str, Any]:
    from importlib.resources import files

    data: dict[str, Any] = json.loads(files("worldloom").joinpath(DATA).read_text(encoding="utf-8"))
    return data


def spellings() -> tuple[str, ...]:
    """Every spelling the rulebook names, ``exact`` first."""
    names = list(_book()["spellings"])
    return tuple(["exact", *sorted(n for n in names if n != "exact")])


@lru_cache(maxsize=8)
def _rules(name: str) -> Rules | None:
    entry = _book()["spellings"].get(name)
    if entry is None:
        raise KeyError(f"no spelling {name!r}; the rulebook has {', '.join(spellings())}")
    money = entry.get("money")
    if not money:
        return None
    percent = entry.get("percent", {})
    return Rules(
        name=name,
        magnitudes=tuple(Magnitude(str(m["suffix"]), float(m["factor"]), int(m["places"]))
                         for m in sorted(money["magnitudes"], key=lambda m: -float(m["factor"]))),
        scales={str(k): float(v) for k, v in money.get("scales", {}).items()},
        min_significant=int(money.get("min_significant", 2)),
        consolidate_share=float(money.get("consolidate_share", 0.0)),
        percent_units=tuple(percent.get("units", ("percent",))),
        percent_places=int(percent.get("places", 2)),
        dates=bool(entry.get("dates", False)),
        enums=bool(entry.get("enums", False)),
    )


def rules_for(presentation: Presentation | None) -> Rules | None:
    """The rulebook entry *presentation* spells by, or ``None`` for exact."""
    name = getattr(presentation, "spelling", "exact") or "exact"
    return None if name == "exact" else _rules(name)


# ---------------------------------------------------------------------------
# Words from the prompts pack
# ---------------------------------------------------------------------------


def _pack(key: str, fallback: str) -> str:
    from . import packkit

    try:
        return packkit.template(key)
    except KeyError:
        return fallback


def _zero() -> str:
    return _pack("render.figures.zero", "nil")


def _direction_phrases() -> tuple[str, ...]:
    raw = _pack("render.figures.direction_phrases", "shortfall of | short by | gap of | miss of")
    return tuple(sorted((p.strip().lower() for p in raw.split(" | ") if p.strip()), key=len, reverse=True))


def _lexicon(key: str) -> tuple[str, ...]:
    raw = _pack(key, "")
    return tuple(sorted((p.strip().lower() for p in raw.split(" | ") if p.strip()), key=len, reverse=True))


def _direction_words() -> tuple[tuple[str, ...], tuple[str, ...], int]:
    """``(adverse, favourable, window)``: the words that say which way a figure
    went, from the prompts pack, and how many words before a figure are read."""
    try:
        window = int(_pack("render.figures.direction_window", "8"))
    except ValueError:
        window = 8
    return (_lexicon("render.figures.direction_words.adverse"),
            _lexicon("render.figures.direction_words.favourable"), max(1, window))


#: Where a clause ends, for the purpose of asking what a figure's clause says:
#: a comma, a semicolon, a colon, a bracket or a dash. "Food carried the
#: shortfall, missing plan by X" reads "missing plan by" and not "shortfall".
_CLAUSE_BREAK = re.compile(r"[,;:()\[\]\u2014\u2013]|\s-\s")


_FIGURE_WORD = re.compile(r"(\d(?:k|m|bn|tn)?|\}\}|\bnil)\s+(?:adverse|favourable)\b")


def _spans(words: str, lexicon: tuple[str, ...]) -> list[tuple[int, int]]:
    """Where each lexicon entry occurs in *words*, as whole words."""
    return [(found.start(), found.end()) for entry in lexicon
            for found in re.finditer(rf"(?<![\w-]){re.escape(entry)}(?![\w-])", words)]


def direction(before: str, after: str = "") -> str | None:
    """Which way the words around a figure already say it went.

    ``"adverse"`` when the figure's own clause carries the direction in words
    before it ("missing revenue plan by", "a shortfall of", "the group missed
    plan by") or straight after it ("AUD 10.2m below budget"); ``"favourable"``
    when the nearest such word says the other way ("ahead of plan by"); ``None``
    when the words say nothing about direction ("revenue of", "at"), and the
    figure has to say it itself. Lexical, read on the clause only, and the
    lexicon is prompts pack text (``render.figures.direction_words.*``), so an
    industry pack that says "under water" adds it without code.
    """
    adverse, favourable, window = _direction_words()
    # Another figure's own direction word ("AUD 7.0m adverse and Digital
    # AUD 2.9m") belongs to that figure, not to this one's clause.
    clause = _FIGURE_WORD.sub(r"\1", _CLAUSE_BREAK.split(before)[-1]).lower()
    phrases = _direction_phrases()
    if any(clause.rstrip().endswith(phrase) for phrase in phrases):
        return "adverse"
    tail = " ".join(clause.split()[-window:])
    # The word nearest the figure decides: "Digital beat plan while Food
    # missed by X" is a miss.
    worse = max((end for _start, end in _spans(tail, adverse)), default=-1)
    better = max((end for _start, end in _spans(tail, favourable)), default=-1)
    if worse >= 0 or better >= 0:
        return "adverse" if worse >= better else "favourable"
    # Straight after the figure: "AUD 10.2m below budget". Its own "adverse"
    # is the figure's word, not the clause's, and is skipped.
    head = " ".join(_CLAUSE_BREAK.split(after)[0].lower().split()[:3])
    head = head.removeprefix("adverse").strip()
    if any(start == 0 for start, _end in _spans(head, adverse)):
        return "adverse"
    if any(start == 0 for start, _end in _spans(head, favourable)):
        return "favourable"
    return None


def _months() -> tuple[str, ...]:
    raw = _pack("render.figures.months", "January | February | March | April | May | June | July | August"
                " | September | October | November | December")
    months = tuple(p.strip() for p in raw.split(" | "))
    return months if len(months) == 12 else ("January", "February", "March", "April", "May", "June", "July",
                                             "August", "September", "October", "November", "December")


# ---------------------------------------------------------------------------
# Spelling
# ---------------------------------------------------------------------------

_ISO_DATE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})$")
_ISO_STAMP = re.compile(r"^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:?\d{2})?$")
#: A recorded enum value, alone or leading a longer record ("control_failure:
#: the mapping table has no registered owner").
_ENUM_LEAD = re.compile(r"^([a-z][a-z0-9]*(?:_[a-z0-9]+)+)(?=$|[:;,.\s])")


def humanise(text: str, rules: Rules | None = None) -> str:
    """A recorded text value in the words a reader uses: an ISO date or
    timestamp in words, a leading enum token with spaces for underscores."""
    if rules is not None and not (rules.dates or rules.enums):
        return text
    stripped = text.strip()
    if rules is None or rules.dates:
        months = _months()
        found = _ISO_DATE.match(stripped)
        if found:
            try:
                day = date(int(found.group(1)), int(found.group(2)), int(found.group(3)))
            except ValueError:
                return text
            return f"{day.day} {months[day.month - 1]} {day.year}"
        found = _ISO_STAMP.match(stripped)
        if found:
            try:
                moment = datetime(int(found.group(1)), int(found.group(2)), int(found.group(3)),
                                  int(found.group(4)), int(found.group(5)))
            except ValueError:
                return text
            return f"{moment.day} {months[moment.month - 1]} {moment.year}, {moment:%H:%M}"
    if rules is None or rules.enums:
        found = _ENUM_LEAD.match(text)
        if found:
            return found.group(1).replace("_", " ") + text[found.end():]
    return text


def _money_parts(unit: str, rules: Rules) -> tuple[str, float, str] | None:
    """``(currency, factor to currency units, trailing words)`` for a money unit."""
    from .narrative.references import _is_money

    if not _is_money(unit):
        return None
    currency, _, scale = unit.partition("_")
    if scale in rules.scales:
        return currency, rules.scales[scale], ""
    return currency, 1.0, scale.replace("_", " ")



@dataclass
class _Money:
    index: int
    fact: CanonicalFact
    currency: str
    base: float
    trailing: str
    magnitude: Magnitude | None = None
    places: int = 0


def _magnitude_of(base: float, rules: Rules) -> Magnitude:
    for magnitude in rules.magnitudes:
        if abs(base) >= magnitude.factor:
            return magnitude
    return rules.magnitudes[-1]


def _places_for(base: float, magnitude: Magnitude, rules: Rules) -> int:
    places = magnitude.places
    while places < 3:
        shown = round(abs(base) / magnitude.factor, places)
        if shown and _count_significant(shown, places) >= rules.min_significant:
            break
        if magnitude.factor == 1 and float(base).is_integer():
            break
        places += 1
    return places


def _count_significant(shown: float, places: int) -> int:
    text = f"{shown:.{places}f}".replace(".", "").lstrip("0")
    return len(text)


def _sentences(text: str) -> list[tuple[int, int]]:
    """Sentence spans of *text*, split where a writer ends one."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in re.finditer(r"(?<=[.!?])\s+|\n\n+", text):
        spans.append((start, match.start()))
        start = match.end()
    spans.append((start, len(text)))
    return spans


def spell_one(fact: CanonicalFact, *, locale: Locale, presentation: Presentation) -> str:
    """One fact spelled alone, as a table or a brief shows it."""
    return spell_all("{{fact:" + fact.id + "}}", {fact.id: fact}.get, locale=locale,
                     presentation=presentation)[0] or ""


def spell_all(
    text: str,
    lookup: Callable[[str], CanonicalFact | None],
    *,
    locale: Locale,
    presentation: Presentation,
) -> list[str | None]:
    """The spelled value of every well-formed reference in *text*, in order.

    ``None`` where *lookup* cannot resolve the id, so each caller keeps its own
    wording for a hole ("[missing ...]", "TBC"). Under an exact spelling this is
    ``render_value`` per reference, byte for byte; under a reader spelling the
    figures of one sentence are spelled together.
    """
    from .narrative import references

    matches = list(references.REFERENCE.finditer(text))
    facts = [lookup(m.group("id")) for m in matches]
    rules = rules_for(presentation)
    if rules is None:
        return [references.exact_value(f, locale=locale, presentation=presentation) if f is not None else None
                for f in facts]

    out: list[str | None] = [None] * len(matches)
    for start, end in _sentences(text):
        inside = [i for i, m in enumerate(matches) if start <= m.start() < end]
        money: list[_Money] = []
        percents: list[tuple[int, float]] = []
        for i in inside:
            fact = facts[i]
            if fact is None:
                continue
            if fact.value is None:
                out[i] = humanise(references.exact_value(fact, locale=locale, presentation=presentation), rules)
                continue
            unit = fact.value.unit
            parts = _money_parts(unit, rules)
            if parts is not None:
                currency, factor, trailing = parts
                money.append(_Money(i, fact, currency, float(fact.value.amount) * factor, trailing))
            elif unit in rules.percent_units:
                percents.append((i, float(fact.value.amount)))
            else:
                spelled = references.exact_value(fact, locale=locale, presentation=presentation)
                out[i] = spelled.replace("_", " ") if "_" in unit else spelled

        # Money: the sentence's largest magnitude per currency leads.
        leads: dict[str, Magnitude] = {}
        for item in money:
            if item.base == 0 or item.trailing:
                continue
            own = _magnitude_of(item.base, rules)
            lead = leads.get(item.currency)
            if lead is None or own.factor > lead.factor:
                leads[item.currency] = own
        for item in money:
            if item.base == 0 or item.trailing:
                continue
            own = _magnitude_of(item.base, rules)
            lead = leads[item.currency]
            chosen = own
            if own.factor < lead.factor and abs(item.base) >= rules.consolidate_share * lead.factor:
                # Only where the lead's own places still carry the figure:
                # AUD 958k reads as AUD 1.0m beside AUD 617.2m, but AUD 120k
                # would need AUD 0.12m and drag the whole sentence to two places.
                shown = round(abs(item.base) / lead.factor, lead.places)
                if _count_significant(shown, lead.places) >= rules.min_significant:
                    chosen = lead
            item.magnitude = chosen
            # The fewest places that still say the rounded figure: 15.5bn,
            # not 15.50bn, when nothing beside it needs the second place.
            shown = abs(item.base) / chosen.factor
            full = _places_for(item.base, chosen, rules)
            places = _trimmed_places(shown, full)
            while places < full and _count_significant(round(shown, places), places) < rules.min_significant:
                places += 1
            item.places = places
        # One precision per unit per sentence.
        groups: dict[tuple[str, str], list[_Money]] = {}
        for item in money:
            if item.magnitude is not None:
                groups.setdefault((item.currency, item.magnitude.suffix), []).append(item)
        for items in groups.values():
            places = max(item.places for item in items)
            for item in items:
                item.places = places
        for item in money:
            fact = item.fact
            assert fact.value is not None
            if item.base == 0:
                out[item.index] = _zero()
                continue
            if item.trailing:
                places = 0 if float(fact.value.amount).is_integer() else 2
                spelled = f"{item.currency} {locale.spell(abs(float(fact.value.amount)), places)} {item.trailing}"
            else:
                assert item.magnitude is not None
                shown = abs(item.base) / item.magnitude.factor
                spelled = f"{item.currency} {locale.spell(shown, item.places)}{item.magnitude.suffix}"
            if item.base < 0:
                # The direction once: a clause that already says the figure
                # went the wrong way ("missing plan by", "a shortfall of",
                # "... below budget") leaves the figure bare. One that says
                # the other way keeps it, so the contradiction stays on the
                # page for `defects` to refuse rather than being hidden.
                match = matches[item.index]
                if direction(text[start:match.start()], text[match.end():end]) != "adverse":
                    spelled += " adverse"
            out[item.index] = spelled
        # Percentages: one number of places per sentence.
        if percents:
            wanted = [_trimmed_places(value, rules.percent_places) for _i, value in percents]
            places = max(wanted)
            for i, value in percents:
                out[i] = locale.percent(f"{'-' if value < 0 else ''}{locale.spell(value, places)}")
    for i, fact in enumerate(facts):
        if out[i] is None and fact is not None:
            out[i] = references.exact_value(fact, locale=locale, presentation=presentation)
    return out


def _trimmed_places(value: float, places: int) -> int:
    for spent in range(places + 1):
        if round(value, spent) == round(value, places):
            return spent
    return places


# ---------------------------------------------------------------------------
# Recognising a copy
# ---------------------------------------------------------------------------

_SUFFIX_WORDS: dict[str, float] = {
    "tn": 1e12, "bn": 1e9, "billion": 1e9, "billions": 1e9, "m": 1e6, "million": 1e6, "millions": 1e6,
    "k": 1e3, "thousand": 1e3, "thousands": 1e3, "": 1.0,
}
_MONEY_SHOWN = re.compile(
    r"^(?P<cur>[A-Z]{3})\s*(?P<num>\(?-?[\d][\d\s.,'’]*\)?)\s*(?P<suffix>tn|bn|m|k|billions?|millions?|thousands?)?"
    r"(?:\s+(?P<dir>adverse|favourable))?$")


def _number(raw: str, locale: Locale) -> tuple[float, int] | None:
    """A spelled magnitude as ``(value, places shown)`` in *locale*'s grammar."""
    negative = raw.startswith(("(", "-"))
    cleaned = raw.strip("()-").replace(" ", "").replace("'", "").replace("’", "")
    cleaned = cleaned.replace(locale.group_separator, "") if locale.group_separator else cleaned
    whole, _, fraction = cleaned.partition(locale.decimal_separator)
    try:
        value = float(f"{whole}.{fraction}" if fraction else whole)
    except ValueError:
        return None
    return (-value if negative else value), len(fraction)


def agrees(fact: CanonicalFact, shown: str, *, locale: Locale, presentation: Presentation) -> bool:
    """Whether *shown* is a correct spelling of *fact*.

    The exact spellings (the ledger's, the profile's alone) always agree. A
    money figure also agrees when it rounds the ledger figure correctly at the
    precision it shows and keeps the rulebook's significant figures, and a
    percentage when it rounds it correctly; "nil" agrees with a zero. Anything
    else is refused: a wrong digit, a wrong magnitude, a direction word that
    contradicts the sign, a figure rounded past the floor.
    """
    from .narrative import references
    from .presentation import AUDIT

    text = shown.strip()
    candidates = {references.render_value(fact, locale=locale, presentation=AUDIT),
                  references.render_value(fact, locale=locale, presentation=presentation)}
    try:
        candidates.add(spell_one(fact, locale=locale, presentation=presentation))
    except KeyError:
        pass
    if text in candidates:
        return True
    rules = rules_for(presentation) or _rules("reader")
    assert rules is not None
    if fact.value is None:
        return text == humanise(fact.text_value or "", rules)
    amount, unit = float(fact.value.amount), fact.value.unit
    parts = _money_parts(unit, rules)
    if parts is not None:
        currency, factor, _trailing = parts
        base = amount * factor
        if text.lower() == _zero().lower():
            return base == 0
        found = _MONEY_SHOWN.match(text)
        if found is None or found.group("cur") != currency:
            return False
        parsed = _number(found.group("num"), locale)
        if parsed is None:
            return False
        value, places = parsed
        direction = found.group("dir")
        if (direction == "adverse" and base >= 0) or (direction == "favourable" and base < 0):
            return False
        if value < 0 and base >= 0:
            return False
        scale = _SUFFIX_WORDS[found.group("suffix") or ""]
        tolerance = 0.5 * (10 ** -places) * scale
        if abs(abs(value) * scale - abs(base)) > tolerance + 1e-9 * max(1.0, abs(base)):
            return False
        return _count_significant(abs(value), places) >= rules.min_significant or abs(value) * scale == abs(base)
    if unit in rules.percent_units:
        found = re.match(r"^(?P<num>-?[\d.,\s]+?)\s*%$", text)
        if found is None:
            return False
        parsed = _number(found.group("num"), locale)
        if parsed is None:
            return False
        value, places = parsed
        return abs(value - amount) <= 0.5 * (10 ** -places) + 1e-9
    spelled = references.render_value(fact, locale=locale, presentation=AUDIT)
    return text == spelled.replace("_", " ")


def spellings_of(fact: CanonicalFact, *, locale: Locale, presentation: Presentation) -> tuple[str, ...]:
    """Every spelling of *fact* that `agrees` accepts, other than its own.

    Finite because a spelling is: each magnitude the rulebook names at up to
    three places, with and without its direction word (a sentence can carry
    the direction in a phrase instead), a zero's word, a percentage at up to
    three places. Enumerated so a check made now can be re-made later from
    the list alone, without the world that produced it.
    """
    from .narrative import references

    rules = rules_for(presentation)
    if rules is None or fact.value is None:
        return ()
    own = references.render_value(fact, locale=locale, presentation=presentation)
    amount, unit = float(fact.value.amount), fact.value.unit
    found: set[str] = set()
    parts = _money_parts(unit, rules)
    if parts is not None:
        currency, factor, trailing = parts
        base = amount * factor
        if base == 0:
            found.add(_zero())
        elif not trailing:
            for magnitude in rules.magnitudes:
                for places in range(4):
                    shown = round(abs(base) / magnitude.factor, places)
                    if not shown:
                        continue
                    text = f"{currency} {locale.spell(shown, places)}{magnitude.suffix}"
                    found.update((f"{text} adverse", text) if base < 0 else (text,))
    elif unit in rules.percent_units:
        for places in range(4):
            found.add(locale.percent(f"{'-' if amount < 0 else ''}{locale.spell(amount, places)}"))
    return tuple(sorted(text for text in found
                        if text != own and agrees(fact, text, locale=locale, presentation=presentation)))


# ---------------------------------------------------------------------------
# Reading spelled text for defects
# ---------------------------------------------------------------------------

#: A unit word after a figure: straight after its digits, or after the
#: magnitude or direction a reference already spelled ("AUD 958k thousands").
_PLURAL_UNIT = re.compile(r"\d\s+(?:thousands|millions|billions)\b"
                          r"|(?:\d(?:k|m|bn|tn)|\b(?:adverse|favourable|nil))\s+(?:thousands?|millions?|billions?)\b")
_ZERO_MONEY = re.compile(r"\b[A-Z]{3}\s+0(?:[.,]0+)?(?:\s*(?:thousands|millions|billions|k|m|bn)\b|(?=[\s,;:)]|\.(?!\d)|$))")
_SCALED = re.compile(r"\b[A-Z]{3}\s+[\d][\d,]*(?:\.(?P<frac>\d+))?(?P<suffix>tn|bn|m|k)\b")
_RAW_UNIT = re.compile(r"\d\s+(?:pct\b|[a-z]+_[a-z_]+\b)")
_STAMP = re.compile(r"\b\d{4}-\d{2}-\d{2}T\d{2}:\d{2}")
_DOUBLED = re.compile(r"\b(adverse|favourable)\s+\1\b|\b([A-Z]{3})\s+\2\b")


def defects(text: str, rules: Rules | None = None) -> list[str]:
    """Every number-spelling defect in spelled *text*, as a phrase naming it.

    Lexical, and read on what a reader sees (references already substituted).
    Over-precision is judged against *rules* (the reader rulebook by default).
    """
    rules = rules or _rules("reader")
    assert rules is not None
    places = {m.suffix: m.places for m in rules.magnitudes}
    found: list[str] = []
    for match in _PLURAL_UNIT.finditer(text):
        found.append(f"unit word after a figure: {text[max(0, match.start() - 12):match.end()].strip()!r}")
    for match in _ZERO_MONEY.finditer(text):
        found.append(f"a zero spelled as a figure: {match.group(0).strip()!r}")
    for match in _RAW_UNIT.finditer(text):
        found.append(f"a recorded unit in prose: {match.group(0)!r}")
    for match in _STAMP.finditer(text):
        found.append(f"a raw timestamp: {match.group(0)!r}")
    for match in _DOUBLED.finditer(text):
        found.append(f"said twice: {match.group(0)!r}")
    for start, end in _sentences(text):
        sentence = text[start:end]
        by_suffix: dict[str, set[int]] = {}
        for match in _SCALED.finditer(sentence):
            decimals = len(match.group("frac") or "")
            suffix = match.group("suffix")
            by_suffix.setdefault(suffix, set()).add(decimals)
            limit = places.get(suffix)
            if limit is not None and decimals > limit:
                # Over-precise only when one place fewer would still carry
                # the rulebook's significant figures: "AUD 0.12m" needs both.
                digits = match.group(0).split()[-1].rstrip("tnbmk").replace(",", "")
                if _count_significant(float(digits), decimals - 1) >= rules.min_significant:
                    found.append(f"over-precise: {match.group(0)!r}")
            tail = sentence[match.end():match.end() + 9]
            if tail.startswith(" adverse"):
                said = direction(sentence[:match.start()], sentence[match.end() + 8:])
                where = sentence[max(0, match.start() - 24):match.end() + 8]
                if said == "adverse":
                    found.append(f"direction said twice (the words already say it; drop one): {where!r}")
                elif said == "favourable":
                    found.append(f"direction contradicts the figure (the words say favourable, the figure"
                                 f" is adverse): {where!r}")
        for suffix, spent in by_suffix.items():
            if len(spent) > 1:
                found.append(f"mixed precision for {suffix!r} figures in one sentence: {sentence[:60]!r}")
    return found


def enum_values(facts: Sequence[CanonicalFact]) -> dict[str, str]:
    """Recorded enum tokens in *facts*' text values, each to its reader's words."""
    out: dict[str, str] = {}
    for fact in facts:
        if fact.value is not None or not fact.text_value:
            continue
        found = _ENUM_LEAD.match(fact.text_value)
        if found:
            out[found.group(1)] = found.group(1).replace("_", " ")
    return out


# ---------------------------------------------------------------------------
# A table's unit
# ---------------------------------------------------------------------------


def _tables(name: str) -> Mapping[str, Any]:
    entry = _book()["spellings"].get(name, {})
    tables: Mapping[str, Any] = entry.get("tables", {})
    return tables


def table_units(table: Table, facts: Mapping[str, CanonicalFact], presentation: Presentation) -> dict[str, str]:
    """Money column key to the unit its cells are held in, as a reader names it.

    A table prints the ledger's own cells ("617,200" for AUD 617.2m held in
    thousands), which is right for a schedule and meaningless without its
    unit: the appendix schedules of a reader-spelled memo printed thousands
    with nothing saying so. Read from the facts the cells cite (the ledger's
    unit, never guessed from a header), and empty under the exact spelling
    and for a table that carries a unit column of its own.
    """
    from .narrative.references import _is_money

    rules = rules_for(presentation)
    if rules is None:
        return {}
    spec = _tables(rules.name)
    if not spec:
        return {}
    marks = {str(m).lower() for m in spec.get("unit_columns", ())}
    if any(column.label.strip().lower() in marks for column in table.columns):
        return {}
    found: dict[str, set[str]] = {}
    for row in table.rows:
        for key, cell in row.cells.items():
            fact = facts.get(cell.fact_id or "")
            if fact is None or fact.value is None or not isinstance(cell.value, (int, float)):
                continue
            if _is_money(fact.value.unit):
                found.setdefault(key, set()).add(fact.value.unit)
    out: dict[str, str] = {}
    template = str(spec.get("unit", "{currency} {scale}"))
    for key, units in sorted(found.items()):
        if len(units) != 1:
            continue
        currency, _, scale = next(iter(units)).partition("_")
        out[key] = " ".join(template.format(currency=currency, scale=scale.replace("_", " ")).split())
    return out


def unit_caption(caption: str, table: Table, facts: Mapping[str, CanonicalFact],
                 presentation: Presentation) -> tuple[str, Table]:
    """*caption* and *table* stating the table's money unit, once.

    In the caption when every money column shares one unit ("Business Unit
    P&L (AUD thousands)"), else in each money column's header. Unchanged
    under the exact spelling, so an audit rendering keeps its bytes.
    """
    units = table_units(table, facts, presentation)
    if not units:
        return caption, table
    rules = rules_for(presentation)
    assert rules is not None
    spec = _tables(rules.name)
    labels = set(units.values())
    if len(labels) == 1:
        unit = next(iter(labels))
        if unit.lower() in caption.lower():
            return caption, table
        return str(spec.get("caption", "{caption} ({unit})")).format(caption=caption, unit=unit), table
    header = str(spec.get("header", "{label} ({unit})"))
    columns = [column.model_copy(update={"label": header.format(label=column.label, unit=units[column.key])})
               if column.key in units and units[column.key].lower() not in column.label.lower() else column
               for column in table.columns]
    return caption, table.model_copy(update={"columns": columns})
