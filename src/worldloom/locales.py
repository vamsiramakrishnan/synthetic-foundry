"""Where a world is, as a named and validated thing — so it can be somewhere else.

Every world this tool has ever built is Australian, and it is Australian in more
places than the two the schema admits to. ``Pack.regions`` and
``Pack.headquarters`` are documented as "the only two places a generated corpus
prints bare geography", and that sentence is true only if you count geography as
*place names*. It is not the only way a corpus says where it is. A corpus also
says where it is by:

* whose names its people have (``generators/names.GIVEN``/``FAMILY``);
* what a company's second word is (``COMPANY_SECOND``: "Retail Group", never
  "Handelsgruppe", never "Trading W.L.L.") — and *which* second word depends on
  the industry as well as the country, which is what ``industry_suffixes``
  below is for: a German mutual insurer is a Versicherungsverein auf
  Gegenseitigkeit and a German cooperative bank is an eG, and neither may take
  the other's form;
* which days it does not work — ``business_days_after`` counts Monday to Friday
  and knows no public holiday, so a Gulf employer's Friday close lands on its
  weekend and its Sunday does not count;
* when its year starts — ``fiscal_year_start_month`` is on the archetype, the
  pack, and the ``Company`` model, and no *locale* could reach any of the three
  (see the module note below);
* and how a figure is spelled: ``render/values.format_value`` writes
  ``1,234.50`` and ``(1,234)`` unconditionally, in every DOCX, PPTX, PDF,
  Markdown file and BM25 index entry the tool produces.

Those are not decoration. A reader shown a German subsidiary's variance memo
printing ``(1,234)`` where every German report prints ``-1.234`` learns that the
document is synthetic, and learns it from the punctuation.

**So a locale is a jurisdiction's conventions, named.** Same contract as
``parameters.Span``, ``profiles.Seasonality`` and ``landscape.Landscape``, and
deliberately the same in every particular: a default extracted verbatim from the
literals it replaces so an un-overridden build is the same bytes rather than
close to them; a short registry of presets that are unlike each other; unknown
names refused rather than defaulted; ``named``/``from_document``/``publish`` as
the seam a pack, a probe or a `facets` consequence authors through.

**Why a module of its own, and not more of ``profiles.py``.** That module's
charter — "shapes a world has that are not ranges" — would admit this without
complaint, and ``landscape.py`` split off on proportion rather than principle.
The reason to split here is neither: it is *reach*. A ``Seasonality`` is read by
one generator. A ``Landscape`` is read by one generator. A locale is the first
override surface in this project that is not confined to one — it names sites in
``generators/hierarchy``, names people and the company in ``generators/names``,
spells figures in ``render/values``, and decides arithmetic in the close
calendar. Folding a cross-cutting thing into a module whose every other entry is
single-generator would teach the wrong shape to the next author.

**What is deliberately left closed, and why.**

* **Dates in facts stay ISO 8601.** ``close.due_date`` and
  ``close.revised_date`` are minted as ``date.isoformat()`` and are compared,
  not read: the validator cross-checks them, the evaluation cases quote them,
  and the XLSX and the DOCX have to agree character for character. A
  ``date_order`` field here would let a locale make one renderer print
  ``03/04/2026`` while the fact says ``2026-04-03``, which is the divergence
  ``render/values`` exists to prevent. A date's *format* is not a fact about
  the world; ISO is the wire, and prose already writes dates in words.
* **``currency_unit`` (thousands/millions) stays on the archetype.** A bank
  reports in millions and a grocer in thousands in the same country; that is a
  fact about the company's scale, not about the jurisdiction. ``currency``
  itself is carried here — see the field — but only so that a locale is
  *coherent*, because ``Pack.currency`` has always reached the archetype and
  re-opening it would be inventing a gap.
* **Timezone.** Every timestamp in this project is minted UTC
  (``operations._at``). Making that a locale field would move every event in
  every corpus and is a change to when things happen, not to how they are
  written. It belongs with the close calendar's own physics.
* **Movable public holidays.** ``holidays`` takes fixed ``(month, day)`` pairs
  only. Easter, the Chinese New Year, and the ninth of Dhu al-Hijjah are
  computed from three different calendars, and a locale registry that shipped
  three ephemeris implementations would be a calendar library wearing a
  costume. A fixed-date table is honest about what it covers, and the presets
  below say in ``about`` which of their real holidays it misses.

**``fiscal_year_start_month`` is no longer inert, and the route it took is the
one to copy.** It is set by ``Pack``, copied into three org generators and
stored on ``models.Company``; what was missing was any way for a *locale* to
supply it, so a German corpus kept the engine's July year. ``applied_to`` below
is that way — it rebinds an archetype's ``currency`` and
``fiscal_year_start_month`` from the jurisdiction, and an *authored* archetype
(a pack's) is returned untouched because a pack stating a currency is the
narrower claim. ``models.Company.fiscal`` had already written down the rule
this implements: the locale supplies the default and the company carries the
answer. The pairing matters as much as either half — ``operations.generate``
derives ``CloseEpisode.fiscal`` from the *calendar's* year start and
``Company.fiscal`` from the *company's*, so a locale that moved one and not the
other would give one corpus two accounts of its own financial year.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Literal

#: How a negative figure is spelled in a rendered table. A closed vocabulary
#: rather than a format string, because ``render/values.format_value`` is the
#: single place any renderer turns a number into characters and a free-form
#: template there would be a second number grammar nobody validates.
#:
#: ``trailing_minus`` is the SAP/DATEV export convention that German-speaking
#: finance functions read every day. It ships unchosen by any preset below —
#: the presets that could take it use ``leading_minus``, which is what a German
#: *annual report* prints — and it is here because a pack modelling a company
#: whose numbers arrive out of an ERP extract should not have to fake it.
Negative = Literal["parenthesised", "leading_minus", "trailing_minus"]

#: Python's ``date.weekday()`` numbering, spelled out because a tuple of ints in
#: a preset is otherwise a puzzle.
MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY, SATURDAY, SUNDAY = range(7)

#: The engine's own working week: Monday to Friday, which is what
#: ``operations.business_days_after``'s ``weekday() < 5`` has always meant.
MONDAY_TO_FRIDAY: tuple[int, ...] = (MONDAY, TUESDAY, WEDNESDAY, THURSDAY, FRIDAY)

#: Sunday to Thursday. The Gulf working week, and the reason ``working_week`` is
#: a set of days rather than a count of them: "five business days" is the same
#: number in Dubai and in Sydney and lands on different dates.
SUNDAY_TO_THURSDAY: tuple[int, ...] = (SUNDAY, MONDAY, TUESDAY, WEDNESDAY, THURSDAY)

#: A common year that starts on a Monday, used only to check that a calendar is
#: a working calendar at all (see ``_MINIMUM_BUSINESS_DAYS``). A common year
#: rather than a leap one because 29 February is refused as a fixed holiday.
_PROBE_YEAR = 2001

#: Below this many business days in a year, a calendar is not a working week
#: with holidays taken out of it — it is a shift roster, and
#: ``business_days_after(x, 5)`` would walk months to answer. Fifty-two is
#: "at least one day a week"; the check exists because a working week and a
#: holiday table can each look reasonable and compose into a year with no
#: working days at all, at which point the close calendar loops forever.
_MINIMUM_BUSINESS_DAYS = 52

#: Days in each month of a common year, for validating a fixed-date holiday.
_DAYS_IN_MONTH = (31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31)

#: Where the vocabulary packs live: versioned data files committed with the
#: package, one per shipped locale. Data files rather than 500-line tuples in
#: this module, because a pool that size is corpus material, not prose — and
#: data files rather than a runtime dependency on a name-generation library,
#: because the determinism boundary is absolute: a build must never draw from
#: anything a pip upgrade can move. The files were produced offline (a
#: scratchpad script over a generator tool); the tool is not a dependency and
#: never becomes one.
_VOCAB_DIR = Path(__file__).parent / "data" / "vocab"


def _vocabulary_pack(name: str) -> dict[str, tuple[str, ...]]:
    """The extended name pools for a shipped locale, from its data file.

    Read eagerly at import, not lazily per build: the file is package data, a
    missing or unparsable one is a packaging defect, and the right moment for a
    packaging defect to surface is import — the posture ``archetypes.py`` takes
    on its own tables. Each pool's head is the shipped base pool verbatim;
    ``Locale.__post_init__`` refuses the file if that prefix ever drifts,
    because the prefix is the byte-identity contract: every draw that fits the
    base pool must keep landing on the same names it always did.
    """
    payload = json.loads((_VOCAB_DIR / f"{name}.json").read_text(encoding="utf-8"))
    return {
        "given": tuple(str(entry) for entry in payload["given"]),
        "family": tuple(str(entry) for entry in payload["family"]),
    }


@dataclass(frozen=True)
class Locale:
    """One jurisdiction's conventions: its geography, its people, its figures,
    and its calendar.

    Everything here is convention. Nothing here can change what happens — the
    episode's causality, the physics registry's ranges, and the trading year are
    three other modules' — and that split is the whole point: a pack moving a
    corpus to Frankfurt cannot accidentally author a different incident.
    """

    # -- geography ---------------------------------------------------------

    regions: tuple[str, ...]
    """Region labels for the site estate, cycled by index in
    ``generators/hierarchy.generate`` and printed into every site's name
    ("Metro NSW 007"). Cycled rather than drawn, so the order here is an
    authoring decision: the first *n* labels are what an estate of *n* sites
    per format is spread across."""

    cities: tuple[tuple[str, str], ...]
    """``(city, country)`` pairs the one headquarters is drawn from. A pool
    here and a single value on ``Pack.headquarters``, and both are right: a
    company has exactly one headquarters, but a *locale* is a place several
    companies could be headquartered in, and the registry has to be able to
    answer for a corpus nobody hand-authored."""

    # -- people ------------------------------------------------------------

    given: tuple[str, ...]
    family: tuple[str, ...]
    """Person-name pools. Invented names, as everywhere else in this project —
    resemblance to a real person is not intended — and deliberately mixed in
    origin within each locale rather than drawn from one naming tradition. A
    workforce in Frankfurt or Dubai that all shared one etymology would be a
    less accurate corpus, not a more consistent one, and the engine's own pools
    were mixed for exactly this reason before locales existed."""

    company_suffixes: tuple[str, ...]
    """What follows the invented first word in a generated company name. The
    engine's pool is retail-and-Anglo ("Retail Group", "Holdings"); a locale's
    is what a company in that jurisdiction is actually called. Only the suffix,
    because the first word is invented branding and belongs to no country —
    ``COMPANY_FIRST`` stays a shared pool.

    This is the **retail** pool, and ``suffixes_for`` says so: it is what
    ``generators/names.company_name`` has always drawn from, and every entry in
    every preset below is a trading company's second word. A bank's and an
    insurer's are ``industry_suffixes``."""

    # -- money and figures -------------------------------------------------

    currency: str
    """ISO 4217 code. Carried so a locale is coherent, **not** because currency
    was closed: ``Pack.currency`` has always reached ``Archetype.currency`` and
    from there every money fact's unit. What this field buys is that a facet
    selecting ``germany`` gets EUR without the author having to remember to say
    so twice, and that a locale whose figures are spelled ``1.234,56`` cannot
    be paired with AUD by accident."""

    given_extended: tuple[str, ...] = ()
    family_extended: tuple[str, ...] = ()
    """The deep name pools, loaded from ``data/vocab/<locale>.json`` for every
    shipped preset and empty for a hand-composed locale that supplies none.

    **The base pool is a verbatim prefix of the extended one, and that is the
    whole contract.** ``names.people_names`` draws from the *base* pool
    whenever the headcount fits it — so every world ever built keeps drawing
    the identical names from the identical stream, because ``Rng.sample`` over
    a longer pool lands differently even for the same count — and reaches for
    the extended pool only when the ask outruns the base, which is a build
    that could never have succeeded before and therefore has no bytes to
    preserve. ``__post_init__`` refuses an extended pool whose head is not the
    base pool, because the failure otherwise is the quiet kind: a reordered
    data file would rename every employee in every freshly-built world while
    every figure stayed plausible. Defaulted empty so every existing
    ``Locale(...)`` call and JSON document stays valid — an empty extension
    means only that a headcount past the base pool is refused, exactly as it
    always was."""

    industry_suffixes: tuple[tuple[str, tuple[str, ...]], ...] = ()
    """Company suffixes for a vertical that is not retail, as ``(engine, pool)``.

    **Why per industry at all.** ``company_suffixes`` above is a retail pool by
    construction — Germany's entries are Handelsgruppe and Handel GmbH — so a
    bank drawing from it would be a Frankfurt trading group, which is why
    ``banking_org`` and ``insurance_org`` kept ``_BANK_SUFFIX`` and
    ``_INSURER_SUFFIX`` of their own and stayed English under every locale. The
    conventions really are per industry and not only per country: Germany's
    mutual insurer is a *Versicherungsverein auf Gegenseitigkeit*, a legal form
    its banks may not take and its cooperatives are barred from insurance
    business under, and a German cooperative bank is an *eG*, which no insurer
    is. One pool per jurisdiction cannot express that.

    **Keyed by the registered engine name** — ``retail``, ``banking``,
    ``insurance``: the vocabulary ``domains.Domain.name`` and ``Pack.base``
    already use, so a locale and a pack name a vertical the same way.
    Deliberately *not* ``Archetype.industry``, which is authored prose
    ("Supermarkets and omnichannel retail") and cannot be a registry key.

    **``retail`` is refused as a key**, because ``company_suffixes`` is already
    the answer for it and two places to state one pool is one place that can
    stop being the one a generator draws from — the rule this module applied to
    ``names.COMPANY_SECOND`` and ``hierarchy.REGIONS``.

    A tuple of pairs rather than a mapping, for two reasons that both bite: a
    frozen dataclass with a ``dict`` field is silently unhashable at first
    ``hash()`` rather than at definition, and JSON has no order, so
    ``as_dict``/``from_document`` can only round-trip to an equal value if the
    order is derivable. Entries are therefore held sorted by key, and
    ``__post_init__`` refuses any other order rather than quietly re-sorting."""

    group_separator: str = ","
    decimal_separator: str = "."
    """The digit grammar ``render/values.format_value`` writes with. These two
    are why this module reaches the rendered corpus at all: every money cell,
    every percentage and every figure lifted from a table into prose passes
    through that one function, and it had ``,`` and ``.`` typed into four
    f-strings."""

    negative: Negative = "parenthesised"
    """How a negative is spelled. A house style that *correlates* with
    jurisdiction rather than being decided by it — plenty of German companies
    parenthesise and plenty of Australian ones do not — so each preset below
    states which it picked instead of implying the country mandated it. It is
    on the locale rather than on the style genome because
    ``render/docx._negative_text`` established the rule the hard way: a
    per-renderer negative convention printed ``-10,200`` in Word and
    ``(10,200)`` in Markdown for one table, and the fix was that this is a
    corpus-wide decision applied in one place."""

    percent_gap: str = ""
    """What sits between the figure and the ``%``. Empty in English-language
    reporting, a non-breaking space in German and French. Small, and the kind of
    small that a reader notices without being able to say why."""

    # -- calendar ----------------------------------------------------------

    working_week: tuple[int, ...] = MONDAY_TO_FRIDAY
    """Which weekdays are business days, in ``date.weekday()`` numbering. The
    field the whole calendar half of this module exists for: "the close is due
    four business days after month end" is the same sentence in Sydney and in
    Dubai and resolves to different dates, and until now the engine could only
    ever mean the Sydney one."""

    holidays: tuple[tuple[int, int], ...] = ()
    """Fixed-date public holidays as ``(month, day)``, excluded from the
    business-day count. Empty by default and empty for the shipped Australian
    locale, which is a statement rather than an omission: the engine has never
    known a public holiday, and a default that quietly gained five would move
    every close date in every corpus ever built. Movable feasts are out of
    scope — see the module docstring."""

    fiscal_year_start_month: int = 7
    """When the financial year starts, 1-12.

    Reached through ``applied_to``, which rebinds an un-authored archetype's own
    field from this one — so ``Company.fiscal_year_start_month`` and the
    ``Calendar`` protocol's both come from here and cannot disagree. A pack's
    stays the narrower claim; see ``applied_to`` and the module docstring."""

    # -- provenance --------------------------------------------------------

    about: str = ""
    source: str = ""
    """Where the conventions came from, when a pack supplies one. The same
    boundary this project keeps everywhere else: a jurisdiction's published
    conventions are a prior and are welcome; one identifiable company's
    reporting style is that company's data wearing a costume."""

    def __post_init__(self) -> None:
        for label, pool in (("regions", self.regions), ("given", self.given),
                            ("family", self.family),
                            ("company_suffixes", self.company_suffixes)):
            if not pool:
                raise ValueError(f"a locale needs at least one {label} entry")
            if any(not str(entry).strip() for entry in pool):
                raise ValueError(f"{label} contains a blank or whitespace-only entry")
            # Duplicates are refused rather than deduplicated. A repeated region
            # silently doubles that region's share of the estate; a repeated
            # given name makes a forty-name pool a thirty-nine-name one, and
            # `names.people_names` would then refuse to mint a headcount the
            # author thought they had room for. Both read as "the pool is
            # bigger than it is", which is the failure mode worth naming.
            if len(set(pool)) != len(pool):
                repeated = sorted({e for e in pool if list(pool).count(e) > 1})
                raise ValueError(f"{label} repeats {repeated}")

        # The extended pools, held to the base pools' discipline plus one rule
        # of their own: the base pool is a verbatim prefix. That prefix is the
        # byte-identity contract — `names.people_names` switches pools only
        # when a headcount outruns the base, so any draw that ever succeeded
        # keeps sampling the same tuple — and it is checked here rather than
        # trusted to the data files because a data file is exactly the kind of
        # thing a well-meaning edit reorders ("sorted the names") without
        # anything else in the corpus to notice the rename by.
        for label, base, extended in (
            ("given", self.given, self.given_extended),
            ("family", self.family, self.family_extended),
        ):
            if not extended:
                continue
            if any(not str(entry).strip() for entry in extended):
                raise ValueError(f"{label}_extended contains a blank entry")
            if len(set(extended)) != len(extended):
                repeated = sorted({e for e in extended if extended.count(e) > 1})
                raise ValueError(f"{label}_extended repeats {repeated}")
            if tuple(extended[: len(base)]) != tuple(base):
                raise ValueError(
                    f"{label}_extended does not begin with the {label} pool"
                    " verbatim. The prefix is the byte-identity contract: a"
                    " build whose headcount fits the base pool must keep"
                    " drawing the names it always drew, and an extended pool"
                    " that reorders or edits the head would rename every"
                    " employee in every freshly-built world."
                )

        # Same pool discipline as the four above, applied per vertical. Reached
        # through the same loop deliberately: a bank's suffix pool that repeats
        # an entry is the identical "the pool is bigger than it is" failure, and
        # a second, laxer copy of the rule here would be the drift this whole
        # field exists to prevent.
        seen: list[str] = []
        for engine, pool in self.industry_suffixes:
            engine = str(engine)
            if not engine.strip():
                raise ValueError("an industry_suffixes entry has a blank engine name")
            if engine == "retail":
                raise ValueError(
                    "industry_suffixes may not key 'retail': `company_suffixes` is"
                    " already this locale's retail pool, and two places to state"
                    " one pool is one place that can stop being the one"
                    " `names.company_name` draws from"
                )
            seen.append(engine)
            if not pool:
                raise ValueError(f"industry_suffixes[{engine!r}] holds no suffixes")
            if any(not str(entry).strip() for entry in pool):
                raise ValueError(
                    f"industry_suffixes[{engine!r}] contains a blank or"
                    " whitespace-only entry"
                )
            if len(set(pool)) != len(pool):
                repeated = sorted({e for e in pool if list(pool).count(e) > 1})
                raise ValueError(f"industry_suffixes[{engine!r}] repeats {repeated}")
        if len(set(seen)) != len(seen):
            raise ValueError(f"industry_suffixes names an engine twice: {sorted(seen)}")
        # Sorted rather than sorted-on-read, so that `from_document(as_dict(x))`
        # is `x` and not merely equivalent to it. JSON objects carry no order,
        # so the only order a document can rebuild is one the value already
        # guarantees; re-sorting silently here would make an author's file and
        # the value it produced two different documents.
        if seen != sorted(seen):
            raise ValueError(
                f"industry_suffixes must be sorted by engine name; got {seen}."
                " The order is what lets a locale round-trip through JSON as an"
                " equal value rather than a reordered one."
            )

        if not self.cities:
            raise ValueError("a locale needs at least one headquarters city")
        for entry in self.cities:
            if len(entry) != 2 or not all(str(part).strip() for part in entry):
                raise ValueError(f"a headquarters city is (city, country); got {entry!r}")

        if len(self.currency) != 3 or not self.currency.isupper() or not self.currency.isalpha():
            raise ValueError(
                f"currency {self.currency!r} is not an ISO 4217 code — three"
                " uppercase letters, the shape `Archetype.currency` carries"
            )

        for label, separator in (("group_separator", self.group_separator),
                                 ("decimal_separator", self.decimal_separator)):
            if len(separator) != 1 or separator.isdigit():
                raise ValueError(
                    f"{label} must be a single non-digit character; got {separator!r}"
                )
        if self.group_separator == self.decimal_separator:
            raise ValueError(
                "the group and decimal separators are the same character, so"
                f" {self.group_separator}1{self.group_separator}234{self.group_separator}56"
                " would be unreadable and un-reparseable"
            )

        if self.negative not in ("parenthesised", "leading_minus", "trailing_minus"):
            raise ValueError(
                f"unknown negative convention {self.negative!r};"
                " known: parenthesised, leading_minus, trailing_minus"
            )

        if not self.working_week:
            raise ValueError(
                "a locale with no working days would make `business_days_after`"
                " loop forever — an organisation that never works is a closure,"
                " not a calendar"
            )
        if len(set(self.working_week)) != len(self.working_week):
            raise ValueError(f"working_week repeats a day: {self.working_week}")
        for day in self.working_week:
            if not 0 <= day <= 6:
                raise ValueError(f"{day} is not a weekday; Monday is 0 and Sunday is 6")

        for month, day in self.holidays:
            if not 1 <= month <= 12:
                raise ValueError(f"holiday ({month}, {day}) has no such month")
            if not 1 <= day <= _DAYS_IN_MONTH[month - 1]:
                # 29 February is caught here, and deliberately: a fixed-date
                # holiday that exists in one year in four is not a fixed date,
                # and a calendar that silently skipped it in common years would
                # move close dates for reasons nothing in the corpus records.
                raise ValueError(
                    f"holiday ({month}, {day}) is not a day of every year;"
                    " fixed-date holidays only — see the module docstring on"
                    " movable feasts"
                )
        if len(set(self.holidays)) != len(self.holidays):
            raise ValueError(f"holidays repeats a date: {sorted(self.holidays)}")

        # A working week and a holiday table can each look reasonable and
        # compose into a year with almost no working days — at which point
        # "four business days after month end" walks into the next quarter and
        # a pathological pair walks forever. Counted rather than reasoned about,
        # because the interaction is exactly the thing that is hard to see.
        working = sum(
            1 for offset in range(365)
            if self.is_business_day(date(_PROBE_YEAR, 1, 1) + timedelta(days=offset))
        )
        if working < _MINIMUM_BUSINESS_DAYS:
            raise ValueError(
                f"this calendar has {working} business days in a year, fewer than"
                f" one a week ({_MINIMUM_BUSINESS_DAYS}) — a working week and a"
                " holiday table that compose to this are a shift roster, and the"
                " close calendar counts business days"
            )

        if not 1 <= self.fiscal_year_start_month <= 12:
            raise ValueError(
                f"fiscal_year_start_month {self.fiscal_year_start_month} is not a month"
            )

    # -- naming ------------------------------------------------------------

    def suffixes_for(self, industry: str) -> tuple[str, ...]:
        """What a company in *industry* is called here, after its brand word.

        *industry* is a registered engine name (``retail``, ``banking``,
        ``insurance``) — see ``industry_suffixes``. ``retail`` resolves to
        ``company_suffixes``, which is the one pool this locale has always had
        and is retail's by construction.

        An unknown engine is refused with a stated reason, which is the same
        posture as ``named``'s: an unknown engine name is a configuration error
        rather than a typo, and a silent fallback would make that vertical
        unbuildable in this jurisdiction without anywhere to report why. Every
        shipped locale answers for all three shipped engines, so this is never
        raised by a shipped build. A new vertical registering itself in
        ``locales.register`` must ensure every preset carries an entry for it.
        """
        if industry == "retail":
            return self.company_suffixes
        for engine, pool in self.industry_suffixes:
            if engine == industry:
                return pool
        raise KeyError(
            f"locale {self!r} has no company-name suffixes for engine {industry!r}."
            f" A locale must answer for every registered engine, or the engine is"
            f" unbuildable in that jurisdiction. Register the suffixes via"
            f" `locales.register` before building."
        )

    def name_pool(self, kind: str, count: int) -> tuple[str, ...]:
        """The ``given`` or ``family`` pool sized for *count* distinct draws.

        The switch is the prefix contract made operative: the base pool
        whenever it is deep enough — which is every draw any existing corpus
        ever made, so those keep sampling the identical tuple — and the
        extended pool only past it, where there are no existing bytes to keep.
        A count that outruns both still comes back as the extended pool, so
        the caller's own "asked for more than the pool holds" refusal fires
        exactly as it did before extended pools existed — naming the real
        ceiling, which is now the extended pool's depth rather than the
        base's.
        """
        if kind not in ("given", "family"):
            raise KeyError(f"no name pool of kind {kind!r}; given or family")
        base = self.given if kind == "given" else self.family
        extended = self.given_extended if kind == "given" else self.family_extended
        if count <= len(base) or not extended:
            return base
        return extended

    # -- the calendar ------------------------------------------------------

    def is_business_day(self, day: date) -> bool:
        """Whether *day* is worked here."""
        return day.weekday() in self.working_week and (day.month, day.day) not in self.holidays

    def business_days_after(self, start: date, count: int) -> date:
        """The date *count* business days after *start*.

        Signature-compatible with ``generators/operations.business_days_after``,
        which is the point: that function is the close calendar's only arithmetic
        and it hardcodes ``weekday() < 5`` with no holiday table at all. For the
        default locale this returns exactly what it returns, which is what makes
        the swap byte-neutral; for ``gulf`` it returns a different date, because
        Friday is a weekend there and Sunday is not.
        """
        current, remaining = start, count
        while remaining > 0:
            current += timedelta(days=1)
            if self.is_business_day(current):
                remaining -= 1
        return current

    # -- the figure grammar ------------------------------------------------

    def spell(self, value: float, places: int) -> str:
        """*value*'s magnitude, grouped and pointed this locale's way.

        Magnitude only — the sign is ``negate``'s, because the two conventions
        compose (a German ``-1.234`` and an Australian ``(1,234)`` differ in
        both the punctuation and the sign) and separating them keeps
        ``format_value`` reading as one sentence.
        """
        text = f"{abs(value):,.{places}f}"
        if self.group_separator == "," and self.decimal_separator == ".":
            return text
        # `translate` maps each character once against the original string, so
        # a locale that *swaps* the two ("1,234.50" -> "1.234,50") is a single
        # pass. Two `replace` calls would turn every comma into a dot and then
        # every dot — including the ones just written — back into a comma.
        return text.translate(str.maketrans({
            ",": self.group_separator, ".": self.decimal_separator,
        }))

    def negate(self, spelled: str) -> str:
        """An already-spelled magnitude, marked negative this locale's way."""
        if self.negative == "parenthesised":
            return f"({spelled})"
        if self.negative == "trailing_minus":
            return f"{spelled}-"
        return f"-{spelled}"

    def percent(self, spelled: str) -> str:
        """An already-spelled magnitude, marked as a percentage."""
        return f"{spelled}{self.percent_gap}%"

    # -- serialisation -----------------------------------------------------

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "regions": list(self.regions),
            "cities": [list(entry) for entry in self.cities],
            "given": list(self.given),
            "family": list(self.family),
            "company_suffixes": list(self.company_suffixes),
            "currency": self.currency,
            "group_separator": self.group_separator,
            "decimal_separator": self.decimal_separator,
            "negative": self.negative,
            "percent_gap": self.percent_gap,
            "working_week": list(self.working_week),
            "holidays": [list(entry) for entry in self.holidays],
            "fiscal_year_start_month": self.fiscal_year_start_month,
        }
        # Written only when the locale states one, the same conditional rule
        # `recipe.build_recipe` follows: a key that appears unconditionally puts
        # an empty object into every locale document ever written for a value
        # that changes nothing.
        #
        # The extended pools ride along under the same rule so that
        # `from_document(as_dict(x)) == x` stays true of every preset — the
        # equality `industry_suffixes` keeps its entries sorted for. A recipe
        # that embeds a Locale *object* therefore embeds the deep pools too,
        # which is correct: that recipe's corpus drew from them, and a replay
        # against a later, longer data file would rename its people.
        if self.given_extended:
            payload["given_extended"] = list(self.given_extended)
        if self.family_extended:
            payload["family_extended"] = list(self.family_extended)
        if self.industry_suffixes:
            payload["industry_suffixes"] = {
                engine: list(pool) for engine, pool in self.industry_suffixes
            }
        if self.about:
            payload["about"] = self.about
        if self.source:
            payload["source"] = self.source
        return payload

    def pack_overrides(self) -> dict[str, Any]:
        """The fields of a ``packs.Pack`` this locale decides, as plain JSON.

        The bridge to the one seam that already exists. ``Pack.regions``,
        ``Pack.name_pools``, ``Pack.currency`` and ``Pack.fiscal_year_start_month``
        are authorable today and are embedded verbatim in the corpus recipe, so
        a pack merged with this dict is a locale that **already replays** with
        no change to ``recipe.py`` at all. What it cannot carry is the half a
        pack has no field for — the headquarters *pool*, the company suffixes,
        the figure grammar and the working week — which is exactly the list of
        things this module opened, and exactly why the long-run home for a
        locale is a named key on the recipe rather than four scattered pack
        fields.

        ``headquarters`` is absent on purpose: a pack states one, a locale
        offers several, and picking one here would be this module doing a draw
        that belongs to the seeded stream in ``generators/names``.
        """
        return {
            "regions": list(self.regions),
            "name_pools": {"given": list(self.given), "family": list(self.family)},
            "currency": self.currency,
            "fiscal_year_start_month": self.fiscal_year_start_month,
        }

    def applied_to(self, archetype: Any) -> Any:
        """*archetype* with the two conventions this jurisdiction decides.

        ``currency`` and ``fiscal_year_start_month`` are the only two fields an
        ``archetypes.Archetype`` holds that are a *jurisdiction's* answer rather
        than the company's own shape, and both were unreachable from a locale:
        ``Pack.currency`` reached ``Archetype.currency`` and from there every
        money fact's unit, and a locale had no route at all — so a Frankfurt
        corpus spelled its figures ``1.234,50`` and denominated them in AUD.
        This is that route, and it is the field's own docstring made operative:
        "a locale whose figures are spelled 1.234,56 cannot be paired with AUD
        by accident".

        **An authored archetype is returned untouched.** ``Archetype.authored``
        is set only by ``packs.archetype_of``, so it means a pack stated this
        company's currency and financial year explicitly — the narrower claim,
        which beats a jurisdiction's default exactly as ``Pack.regions`` beats
        ``Locale.regions``. A pack that *wants* the locale's answers merges
        ``pack_overrides`` above, which carries both.

        **What this does not do is rescale anything.** ``annual_revenue`` is
        stated in currency units and stays the number it was: the archetype's
        scale is a claim about how big the company is, and applying an exchange
        rate here would make a locale change what happened rather than what it
        is called — the line this module's class docstring draws.

        ``currency_unit`` (thousands/millions) is deliberately not here: a bank
        reports in millions and a grocer in thousands in the same country. See
        the module docstring.

        Duck-typed rather than importing ``Archetype``, the posture
        ``recipe.py``'s ``_under``/``_with_estate`` take on a spec: this module
        is imported by the generators and must not import the registry back.
        """
        from dataclasses import replace as _replace

        if getattr(archetype, "authored", False):
            return archetype
        return _replace(
            archetype,
            currency=self.currency,
            fiscal_year_start_month=self.fiscal_year_start_month,
        )


# ---------------------------------------------------------------------------
# Australia — the engine's own, extracted verbatim
# ---------------------------------------------------------------------------

#: Everything ``generators/hierarchy.REGIONS``, ``generators/names.CITIES``,
#: ``GIVEN``, ``FAMILY`` and ``COMPANY_SECOND`` held, moved here unchanged, plus
#: the conventions that were never named anywhere: ``render/values`` spelled
#: ``1,234.50`` and ``(1,234)``, ``operations.business_days_after`` worked
#: Monday to Friday and knew no holiday, and ``Archetype.fiscal_year_start_month``
#: was 7.
#:
#: Left first and named for what it actually is, so that an author choosing a
#: locale is choosing rather than inheriting — ``profiles.RETAIL_CHRISTMAS``'s
#: rule and ``landscape.RETAIL``'s.
#:
#: ``holidays`` is empty and that is the extraction being faithful, not a claim
#: that Australia has none. Australia Day, Anzac Day and Boxing Day are fixed
#: dates this table could hold; putting them in would move the close calendar in
#: every corpus this tool has ever built, and the point of an extracted default
#: is that it changes nothing. A pack that wants the real calendar can say so.
#: The vocabulary packs, read once at import. Loaded before the presets so a
#: bad file fails the import rather than the first deep build; each preset's
#: in-code 40-name pools stay the literal source of truth for the prefix, and
#: `__post_init__` proves file and code agree.
_PACKS = {name: _vocabulary_pack(name)
          for name in ("australia", "germany", "gulf", "united_kingdom")}

AUSTRALIA = Locale(
    regions=("NSW", "VIC", "QLD", "WA", "SA", "TAS", "ACT", "NT"),
    cities=(
        ("Sydney", "Australia"), ("Melbourne", "Australia"), ("Auckland", "New Zealand"),
        ("Brisbane", "Australia"), ("Perth", "Australia"), ("Adelaide", "Australia"),
        # Six cities named every major site in the estate; a national chain drew
        # its whole footprint from a boardroom's holiday list. Extended with the
        # next tier of real capitals and centres — the same invented-company
        # discipline does not apply to place names, which are geography.
        ("Canberra", "Australia"), ("Hobart", "Australia"), ("Darwin", "Australia"),
        ("Gold Coast", "Australia"), ("Wellington", "New Zealand"),
        ("Christchurch", "New Zealand"),
    ),
    given=(
        "Rosalind", "Desmond", "Priya", "Marguerite", "Callum", "Sunniva", "Adaeze",
        "Tobias", "Yerlan", "Ilse", "Ezekiel", "Havva", "Rafferty", "Beatriz",
        "Nikolai", "Wilhelmina", "Grethe", "Chidubem", "Solveig", "Anselm",
        "Mireille", "Tarquin", "Oleksandra", "Bartholomew", "Naledi", "Fionnuala",
        "Kwabena", "Isaura", "Dmitri", "Yolanda", "Emeka", "Signe", "Rustam",
        "Perpetua", "Lachlan", "Zerlina", "Osman", "Brigid", "Takoda", "Annelies",
    ),
    family=(
        "Achterberg", "Faulkner-Reyes", "Venkataraghavan", "Oyelaran", "Draeger",
        "Bergqvist", "Nwachukwu-Hall", "Lindqvist", "Abenov", "Vandermolen",
        "Mbatha", "Demirsoy", "Okonkwo", "Sandoval-Klein", "Ferreira-Osei",
        "Costa-Braithwaite", "Aasland", "Eze-Whitfield", "Ramaswamy", "Trbojevic",
        "Kaczmarek", "Olubunmi", "Haverkamp", "Szczepanski", "Mwangi-Turner",
        "Delacroix", "Bhattacharya", "Nakamura-Wells", "Petrosyan", "Ojukwu",
        "Lindegaard", "Rasmussen", "Adeyemi", "Kowalczyk", "Fitzmaurice",
        "Sarkisian", "Vuković", "Anand-Pereira", "Halvorsen", "Ntuli",
    ),
    given_extended=_PACKS["australia"]["given"],
    family_extended=_PACKS["australia"]["family"],
    company_suffixes=(
        "Retail Group", "Group", "Holdings", "Retail", "Commerce Group",
        "Trading Group", "Retail Holdings",
    ),
    # Extracted verbatim, in order, from `banking_org._BANK_SUFFIX`,
    # `insurance_org._INSURER_SUFFIX`, and `procurement_org._CONTRACTOR_SUFFIX`
    # — the same discipline as the four pools above and load-bearing for the same
    # reason. Those generators draw `rng.choice` from their module constants
    # today; the day they ask the locale instead, every archetype at any seed
    # must produce the identical company name, and only a verbatim extraction
    # makes that a fact rather than a hope. `tests/test_locale_build.py` pins
    # the equality against the constants themselves.
    industry_suffixes=(
        ("banking", ("Banking Group", "Bank", "Banking Corporation", "Mutual Bank")),
        ("insurance",
         ("Insurance Group", "General Insurance", "Assurance", "Mutual Insurance")),
        ("procurement",
         ("Infrastructure", "Group Services", "Contracting", "Infrastructure Group")),
    ),
    currency="AUD",
    fiscal_year_start_month=7,
    about="Australia and New Zealand: state and territory abbreviations, a"
          " July financial year, Monday-to-Friday, and the Anglo accounting"
          " parenthesis. What every Worldloom world has been until now,"
          " including the ones whose pack said Bristol.",
)


# ---------------------------------------------------------------------------
# United Kingdom
# ---------------------------------------------------------------------------

#: The nearest neighbour, and included because a locale registry whose entries
#: are all maximally different is easy to write and proves nothing. The UK
#: shares Australia's digit grammar and its accounting parenthesis exactly, and
#: differs on everything else: statistical regions instead of states, an April
#: financial year, and three fixed bank holidays the engine's calendar has never
#: had. Two locales that differ on the calendar but not on the punctuation is a
#: real shape, and a registry that could not express it would be a registry of
#: caricatures.
#:
#: The fixed holidays are New Year's Day, Christmas Day and Boxing Day. The
#: movable ones — Good Friday, Easter Monday, the early May, spring and summer
#: bank holidays — are genuinely missing, and this is the preset where that
#: limitation bites hardest: they are five of the UK's eight.
UNITED_KINGDOM = Locale(
    regions=(
        "LDN", "SE", "SW", "EE", "EM", "WM", "YH", "NW", "NE", "SCO", "WAL", "NI",
    ),
    cities=(
        ("London", "United Kingdom"), ("Manchester", "United Kingdom"),
        ("Leeds", "United Kingdom"), ("Edinburgh", "United Kingdom"),
        ("Bristol", "United Kingdom"), ("Belfast", "United Kingdom"),
        # Same widening as Australia's: six names could not carry a national
        # estate. The four capitals/nations stay represented — Glasgow, Cardiff
        # and a second English tier join the draw.
        ("Glasgow", "United Kingdom"), ("Cardiff", "United Kingdom"),
        ("Birmingham", "United Kingdom"), ("Newcastle", "United Kingdom"),
        ("Southampton", "United Kingdom"), ("Aberdeen", "United Kingdom"),
    ),
    given=(
        "Aoife", "Nathaniel", "Sukhwinder", "Cordelia", "Ewan", "Blessing",
        "Idris", "Harriet", "Oluwaseun", "Rhiannon", "Malachy", "Zainab",
        "Crispin", "Nadia", "Fergus", "Amara", "Tomasz", "Verity", "Hamza",
        "Imogen", "Declan", "Yasmin", "Percival", "Sinead", "Kwame", "Bronwen",
        "Alasdair", "Fatima", "Rupert", "Niamh", "Bartosz", "Adaora", "Gwilym",
        "Saoirse", "Terence", "Anouska", "Padraig", "Chandni", "Lorcan", "Winifred",
    ),
    family=(
        "Ashworth", "Ferguson-Adeyemi", "Cholmondeley", "Bhattal", "Trevelyan",
        "O'Halloran", "Wodehouse", "Nkemdirim", "Fairweather", "Sandhu-Blake",
        "Pemberton", "Macgillivray", "Okereke", "Wisniewski", "Thorne",
        "Duguid", "Rahimi", "Bellingham", "Ap-Rhys", "Considine",
        "Featherstonehaugh", "Iyengar", "Kavanagh", "Lindisfarne", "Mbeki-Shaw",
        "Nettleship", "Ozturk", "Prendergast", "Quainton", "Roscoe",
        "Sowerby", "Tremayne", "Ushakov", "Vaisey", "Wentworth",
        "Yeardsley", "Zielinski", "Aldington", "Brocklehurst", "Chidgey",
    ),
    given_extended=_PACKS["united_kingdom"]["given"],
    family_extended=_PACKS["united_kingdom"]["family"],
    company_suffixes=(
        "Group plc", "Holdings plc", "Retail Group", "Group", "Holdings Limited",
        "Trading Limited", "Retail Holdings",
    ),
    # `plc` and `Limited` are the Companies Act forms every UK company takes and
    # are not a banking or insurance convention at all — which is the point of
    # including this preset here as well as in Germany's: the industry signal in
    # the UK is the *noun* ("Bank", "Building Society", "Assurance"), not the
    # legal suffix, and a registry that only ever showed the German case would
    # teach an author that per-industry means per-legal-form.
    #
    # "Building Society" is the one entry carrying real structure: a mutual
    # deposit-taker under the Building Societies Act 1986, which is not a
    # company and therefore takes no `plc` or `Limited` — hence its bare form
    # here. "Friendly Society" would be the insurance analogue and is left out:
    # the shape a Worldloom insurer generates is a general insurer, and a
    # friendly society is a life and health mutual.
    industry_suffixes=(
        ("banking", ("Bank plc", "Banking Group plc", "Bank Limited", "Building Society")),
        ("insurance",
         ("Insurance plc", "Insurance Limited", "Assurance plc", "Mutual Insurance")),
        ("procurement",
         ("Infrastructure", "Group Services", "Contracting", "Infrastructure Group")),
    ),
    currency="GBP",
    # Same as Australia's, and stated rather than defaulted so the sameness is
    # visible: the UK groups on the comma, points on the full stop, and
    # parenthesises negatives in management reporting exactly as Australia does.
    group_separator=",",
    decimal_separator=".",
    negative="parenthesised",
    holidays=((1, 1), (12, 25), (12, 26)),
    fiscal_year_start_month=4,
    about="The United Kingdom: statistical regions, an April financial year,"
          " sterling, and three fixed bank holidays. Deliberately the closest"
          " neighbour in the registry — identical digit grammar, different"
          " calendar — so that 'a locale' does not come to mean 'a different"
          " alphabet'.",
)


# ---------------------------------------------------------------------------
# Germany
# ---------------------------------------------------------------------------

#: The one that changes every number in the corpus. German figures group on the
#: full stop and point on the comma, so ``1,234.50`` becomes ``1.234,50``; the
#: per cent sign takes a non-breaking space; and a negative is signed, not
#: parenthesised. Nothing about the *facts* moves — the workbook's formulas and
#: the validator's reconciliation are untouched — but every rendered table,
#: every figure quoted in prose and every entry in the BM25 index is spelled
#: differently, which is the strongest available demonstration that a locale is
#: not a set of renamed regions.
#:
#: ``leading_minus`` rather than ``trailing_minus``: a German annual report
#: prints ``-1.234``, and it is the SAP/DATEV *export* that prints ``1.234-``.
#: The corpus's tables are reports.
GERMANY = Locale(
    regions=(
        "BW", "BY", "BE", "BB", "HB", "HH", "HE", "MV",
        "NI", "NW", "RP", "SL", "SN", "ST", "SH", "TH",
    ),
    cities=(
        ("Frankfurt am Main", "Germany"), ("München", "Germany"),
        ("Hamburg", "Germany"), ("Düsseldorf", "Germany"),
        ("Berlin", "Germany"), ("Wien", "Austria"),
        # Widened like the other presets, staying inside what the about-text
        # declares ("Germany and Austria"): Köln and Stuttgart are the next
        # tier of German centres, and Wien's Austrian entry gains Salzburg.
        ("Köln", "Germany"), ("Stuttgart", "Germany"),
        ("Leipzig", "Germany"), ("Dortmund", "Germany"),
        ("Essen", "Germany"), ("Bremen", "Germany"),
        ("Dresden", "Germany"), ("Salzburg", "Austria"),
    ),
    given=(
        "Annegret", "Bastian", "Cemile", "Dietrich", "Elif", "Friedhelm",
        "Gudrun", "Hasan", "Ingeborg", "Jarosław", "Katharina", "Leopold",
        "Mechthild", "Nurten", "Ottmar", "Petra", "Quirin", "Reinhild",
        "Sebastiano", "Thorsten", "Ulrike", "Volkmar", "Wiebke", "Xenia",
        "Yusuf", "Zdenka", "Agnieszka", "Burkhard", "Clemens", "Dorothea",
        "Emre", "Franziska", "Gernot", "Helene", "Ismail", "Jutta",
        "Konstantin", "Liesel", "Matthias", "Nikoletta",
    ),
    family=(
        "Achterhoff", "Brandtstädter", "Czerwinski", "Drewermann", "Eichelbaum",
        "Fahrenkrug", "Güngör", "Hillebrand", "Ipek", "Jankowiak",
        "Kirchgässner", "Lauterbach-Öz", "Middelhoff", "Niedermeier", "Osterloh",
        "Prantl", "Quandt-Erdogan", "Rehberger", "Schwanitz", "Trautwein",
        "Uhlenbrock", "Vollmer", "Wendlandt", "Xylander", "Yıldırım",
        "Zumsteg", "Aschenbrenner", "Bierhoff", "Czajkowski", "Dohmen",
        "Engelhardt", "Fürstenberg", "Grzeskowiak", "Hohenester", "Illgner",
        "Jessen", "Kowalczyk-Meier", "Lindhorst", "Mütze", "Nowotny",
    ),
    given_extended=_PACKS["germany"]["given"],
    family_extended=_PACKS["germany"]["family"],
    company_suffixes=(
        "Handelsgruppe", "Gruppe", "Holding", "Handel GmbH", "Handelsholding",
        "Gruppe AG", "Handel",
    ),
    # The preset that makes the case for this field existing. German banking and
    # German insurance take *different legal forms from each other*, not merely
    # different nouns: a cooperative bank is an `eG` (eingetragene
    # Genossenschaft, under the Genossenschaftsgesetz) and a mutual insurer is a
    # `VVaG` — a Versicherungsverein auf Gegenseitigkeit, spelled `a.G.` in a
    # company name — because German cooperatives are barred from carrying on
    # insurance business, so the two mutual forms are not interchangeable. One
    # `company_suffixes` pool per jurisdiction cannot express that, and a
    # "Meridian Handelsgruppe" holding a banking licence is what it produced.
    #
    # `AG` and `SE` (Societas Europaea) are the stock forms a listed German bank
    # or insurer takes. Two real forms are deliberately absent, and for one
    # reason: `Sparkasse` and `Landesbank` are public-law institutions
    # (Anstalten des öffentlichen Rechts) named after the region or Land that
    # carries them — "Hamburger Sparkasse", not "Kestrel Sparkasse" — so
    # composing them with this project's invented English brand word
    # (`names.COMPANY_FIRST`) would produce a name no German reader would
    # accept. The pool is the forms that compose with an invented brand.
    industry_suffixes=(
        ("banking", ("Bank AG", "Bankgruppe", "Privatbank AG", "Bank SE", "Volksbank eG")),
        ("insurance",
         ("Versicherung AG", "Versicherungsgruppe", "Versicherung a.G.",
          "Assekuranz AG", "Versicherung SE")),
        ("procurement",
         ("Infrastructure", "Group Services", "Contracting", "Infrastructure Group")),
    ),
    currency="EUR",
    group_separator=".",
    decimal_separator=",",
    negative="leading_minus",
    # U+00A0, written as an escape so it is visible in the source rather than
    # an ordinary-looking space nobody can tell is not one. German typography
    # does not break a line between a figure and its per cent sign.
    percent_gap="\u00a0",
    # The nationwide fixed-date holidays. Deliberately not the Länder-specific
    # ones — Fronleichnam and Allerheiligen are public holidays in Bavaria and
    # not in Berlin, and a locale that is a country cannot hold a calendar that
    # varies by region without becoming sixteen locales.
    holidays=((1, 1), (5, 1), (10, 3), (12, 25), (12, 26)),
    fiscal_year_start_month=1,
    about="Germany and Austria: the Länder as regions, a calendar financial"
          " year, the euro, five nationwide fixed holidays — and the digit"
          " grammar that makes every rendered figure in the corpus different"
          " (1.234,50, -1.234, 12,50 %).",
)


# ---------------------------------------------------------------------------
# The Gulf
# ---------------------------------------------------------------------------

#: The one that changes the arithmetic. ``operations.business_days_after``'s
#: ``weekday() < 5`` is not a rounding convention — it decides what date the
#: close is due on, when the incident is escalated, when the review happens, and
#: how many rows the liquidity series has. Sunday to Thursday moves all of them,
#: and no amount of renaming regions gets anywhere near it.
#:
#: A United Arab Emirates locale specifically rather than "the Gulf" as a blur:
#: the working week and the two fixed national holidays are the UAE's, and its
#: neighbours' differ. Named ``gulf`` in the registry because that is what an
#: author reaches for, and the entry says which country it actually is.
#:
#: Eid al-Fitr and Eid al-Adha are the region's largest holidays and are absent,
#: because they follow the Hijri calendar and move roughly eleven days a year
#: against this one. That is the fixed-date limitation at its most visible, and
#: the honest form of it is a preset that says so.
GULF = Locale(
    regions=("AUH", "DXB", "SHJ", "AJM", "UAQ", "RAK", "FUJ"),
    cities=(
        ("Dubai", "United Arab Emirates"), ("Abu Dhabi", "United Arab Emirates"),
        ("Sharjah", "United Arab Emirates"), ("Doha", "Qatar"),
        ("Manama", "Bahrain"), ("Muscat", "Oman"),
        # Widened like the other presets: the second tier of the Emirates plus
        # the neighbouring capitals the six already reached for.
        ("Ajman", "United Arab Emirates"), ("Ras Al Khaimah", "United Arab Emirates"),
        ("Fujairah", "United Arab Emirates"), ("Al Ain", "United Arab Emirates"),
        ("Riyadh", "Saudi Arabia"), ("Kuwait City", "Kuwait"),
    ),
    # A Gulf workforce is majority-expatriate, and a name pool that was uniformly
    # Arabic would be a less accurate corpus rather than a more coherent one —
    # the same reasoning the engine's own mixed pools were built on, applied to
    # a place where it happens to be a demographic fact rather than a stylistic
    # preference.
    given=(
        "Abdulrahman", "Noura", "Rajesh", "Fatima", "Sherif", "Aparna",
        "Khalid", "Mariam", "Imran", "Layla", "Bashir", "Shreya",
        "Tariq", "Hessa", "Nikhil", "Salma", "Yousef", "Reem",
        "Anwar", "Divya", "Faisal", "Amal", "Ghassan", "Prakash",
        "Hamdan", "Jumana", "Karim", "Lubna", "Meera", "Nasser",
        "Omar", "Rania", "Saeed", "Thuraya", "Usman", "Wafa",
        "Zayed", "Basma", "Chandran", "Dana",
    ),
    family=(
        "Al Mansoori", "Al Suwaidi", "Nair", "Al Hashimi", "Fakhoury",
        "Venkatesan", "Al Marzouqi", "Habib", "Chatterjee", "Al Nuaimi",
        "Darwish", "Iqbal", "Al Zaabi", "Sayegh", "Krishnan",
        "Al Blooshi", "Haddad", "Rahman", "Al Ketbi", "Mourad",
        "Pillai", "Al Shamsi", "Qureshi", "Al Falasi", "Bou Assaf",
        "Menon", "Al Dhaheri", "Saleh", "Bhandari", "Al Rumaithi",
        "Toufic", "Ravindran", "Al Qassimi", "Barakat", "Sundaram",
        "Al Ameri", "Jaber", "Devadas", "Al Kaabi", "Nassif",
    ),
    given_extended=_PACKS["gulf"]["given"],
    family_extended=_PACKS["gulf"]["family"],
    company_suffixes=(
        "Trading Group", "Holding", "Group Holding", "Trading L.L.C.",
        "Group", "Commercial Group", "Retail Group",
    ),
    # `P.J.S.C.` — public joint stock company — is not a stylistic choice here
    # the way `plc` is in the UK entry: UAE law reserves banking and insurance
    # to public joint stock companies, so a bank or an insurer in this
    # jurisdiction is one, and the retail pool's `L.L.C.` is a form neither may
    # take. Dotted to match `Trading L.L.C.` above rather than because one
    # spelling is more correct — both are current in English-language filings,
    # and a corpus that used both would be a corpus disagreeing with itself.
    #
    # `Takaful` is the Islamic mutual-insurance structure, ordinary in the Gulf
    # and carried alongside the conventional forms rather than instead of them:
    # the market runs both, and a preset that showed only one would be the
    # caricature the registry's other entries already refuse to be.
    industry_suffixes=(
        ("banking", ("Bank P.J.S.C.", "Bank", "Islamic Bank P.J.S.C.", "Banking Group")),
        ("insurance",
         ("Insurance P.J.S.C.", "Insurance Company", "Takaful P.J.S.C.",
          "General Insurance")),
        ("procurement",
         ("Infrastructure", "Group Services", "Contracting", "Infrastructure Group")),
    ),
    currency="AED",
    # The digit grammar is Australia's. Western digits, comma groups, full-stop
    # point and the accounting parenthesis are what the region's English-language
    # reporting uses, and inventing a difference here to make the preset look
    # more foreign would be exactly the caricature this registry is trying not
    # to be. What differs is the week and the year, and that is enough.
    negative="parenthesised",
    working_week=SUNDAY_TO_THURSDAY,
    holidays=((1, 1), (12, 2), (12, 3)),
    fiscal_year_start_month=1,
    about="The United Arab Emirates: the seven emirates as regions, a"
          " Sunday-to-Thursday working week, a calendar financial year, the"
          " dirham, and a majority-expatriate name pool. The locale that moves"
          " dates rather than words — every business-day count in the close"
          " calendar lands somewhere else.",
)


#: Named locales a pack, a probe or a `facets` consequence may pick by name.
#: Deliberately few and deliberately unlike each other — ``profiles.PROFILES``'s
#: rule — but unlike each other *on different axes*, which is the extra
#: discipline this registry needs: the UK differs from Australia on the
#: calendar and not the digits, Germany on the digits, the Gulf on the week. A
#: registry where every entry moved every axis would teach an author that
#: locales come in undifferentiated flavours.
LOCALES: dict[str, Locale] = {
    "australia": AUSTRALIA,
    "united_kingdom": UNITED_KINGDOM,
    "germany": GERMANY,
    "gulf": GULF,
}

#: What an un-overridden build uses, and what every corpus built before this
#: module existed was made of.
DEFAULT = AUSTRALIA


def named(name: str) -> Locale:
    """A locale by name. Unknown names are refused, never defaulted.

    Refused for the reason every other override surface in this project refuses
    them, and with a sharper edge here than most: a pack asking for ``germay``
    that silently got Australia's would build a Frankfurt company whose people
    are called Rafferty and whose sites are in NSW, and every single figure in
    it would be plausible. There is nothing in the corpus for the author to
    notice the drop by.
    """
    try:
        return LOCALES[name]
    except KeyError:
        raise KeyError(
            f"unknown locale {name!r}; known: {sorted(LOCALES)}."
            " A pack may also supply conventions of its own."
        ) from None


def resolve(value: Locale | Mapping[str, Any] | str | None) -> Locale:
    """The locale a build was given: nothing, a name, a document, or one of these.

    The single entry point a world spec's ``locale`` field goes through, and one
    function rather than three copies of the same four-branch conditional in
    ``retail``, ``banking`` and ``insurance``: the branch that matters is the
    first, and a vertical that got it slightly wrong would build Australia and
    say Germany with nothing to notice it by.

    ``None`` is ``DEFAULT`` — every world built before a spec could carry a
    locale *was* Australian, so that is a fact about those worlds and not a gap
    in them. A ``Locale`` passes through, which is what lets a caller compose
    one in Python (``dataclasses.replace(locales.GERMANY, holidays=…)``) without
    round-tripping it through JSON to be accepted.
    """
    if value is None:
        return DEFAULT
    if isinstance(value, Locale):
        return value
    return from_document(value)


def from_document(payload: Mapping[str, Any] | str) -> Locale:
    """A locale from a pack or a recipe: a name, or conventions of its own."""
    if isinstance(payload, str):
        return named(payload)
    try:
        regions = tuple(str(entry) for entry in payload["regions"])
        cities = tuple((str(entry[0]), str(entry[1])) for entry in payload["cities"])
        given = tuple(str(entry) for entry in payload["given"])
        family = tuple(str(entry) for entry in payload["family"])
        suffixes = tuple(str(entry) for entry in payload["company_suffixes"])
        currency = str(payload["currency"])
    except (KeyError, IndexError, TypeError) as exc:
        raise ValueError(
            "a locale needs regions, cities, given, family, company_suffixes"
            f" and currency: {exc}"
        ) from exc
    # Everything below has an engine default, and reading it with `.get` is the
    # difference between a locale document being a whole jurisdiction and being
    # the parts of one an author actually cares about: a pack that only wants
    # German punctuation should not have to restate Monday-to-Friday.
    return Locale(
        regions=regions, cities=cities, given=given, family=family,
        company_suffixes=suffixes, currency=currency,
        given_extended=tuple(str(entry) for entry in payload.get("given_extended", ())),
        family_extended=tuple(str(entry) for entry in payload.get("family_extended", ())),
        group_separator=str(payload.get("group_separator", ",")),
        decimal_separator=str(payload.get("decimal_separator", ".")),
        negative=str(payload.get("negative", "parenthesised")),  # type: ignore[arg-type]
        percent_gap=str(payload.get("percent_gap", "")),
        industry_suffixes=tuple(
            (str(engine), tuple(str(entry) for entry in pool))
            # Sorted on the way in because a JSON object has no order and the
            # value's does — see the field. `__post_init__` refuses an unsorted
            # tuple, so this is what makes a hand-written document loadable
            # without making the in-memory ordering an accident.
            for engine, pool in sorted(dict(payload.get("industry_suffixes") or {}).items())
        ),
        working_week=tuple(int(day) for day in payload.get("working_week", MONDAY_TO_FRIDAY)),
        holidays=tuple(
            (int(entry[0]), int(entry[1])) for entry in payload.get("holidays", ())
        ),
        fiscal_year_start_month=int(payload.get("fiscal_year_start_month", 7)),
        about=str(payload.get("about", "")), source=str(payload.get("source", "")),
    )


def publish() -> dict[str, Any]:
    """Every named locale as data. An author cannot choose what they cannot see."""
    return {name: value.as_dict() for name, value in sorted(LOCALES.items())}


def register(name: str, locale: Locale) -> None:
    """Register a locale for a jurisdiction.

    Called by domain modules (future verticals with new jurisdictions) to add
    their own locales to the global registry. Redefinition is refused — every
    name may appear only once. A locale is named only once per jurisdiction, so
    a name collision is a wiring error rather than a legitimate override.

    Raised rather than silently absorbed if a name is already known, because a
    duplicate in the registration chain is a wiring error: either the module was
    imported twice, or two verticals collided on the same locale name. Neither
    is silent-and-plausible.
    """
    if name in LOCALES:
        raise KeyError(
            f"locale {name!r} is already registered. Each locale name may appear"
            f" only once; a collision is a wiring error in one of the modules"
            f" calling register."
        )
    LOCALES[name] = locale


__all__ = [
    "AUSTRALIA", "DEFAULT", "GERMANY", "GULF", "LOCALES", "MONDAY_TO_FRIDAY",
    "SUNDAY_TO_THURSDAY", "UNITED_KINGDOM", "Locale", "Negative",
    "from_document", "named", "publish", "register", "resolve",
]
