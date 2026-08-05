"""What kind of company this is, said once — and resolved into the seams that exist.

Nine surfaces answer that question today. An archetype key says what the
business sells; ``--employees`` says how many people it has; a ``--facet``
says whether it is listed; ``--locale`` says which jurisdiction spells its
figures; ``--estate`` says how much technology it runs; a ``--physics`` file
says what its margins are; ``--pack`` says what it is called; a vocabulary
qualifier says what its divisions are called; and revenue can only be said by
writing a pack. Somebody describing a business — "a listed mid-size German
insurer, thin margins, fragmented market" — has to know which of those nine
each clause belongs to, and two of them interact in a way nobody predicts
(naming *any* facet settles *every* facet at its registry default, so
``--facet listing=listed`` alone also asserts a flat trading year).

This module is one document instead. It is **a composer, not an engine**:
every field below resolves into a seam that is already load-bearing, and
nothing here is a new thing a generator must learn to read.

===========================  =================================================
what the document says       which seam carries it
===========================  =================================================
``industry`` / ``archetype``  ``archetypes.inspired_by`` / ``archetypes.get``
``vocabulary``                ``vocabulary.spoken`` (the ``base+dialect`` key)
``engine``                    ``domains.by_name`` — the registry, never a table here
``facets``                    ``facets.resolve`` → spans, roles, lore, calendar, estate
``physics``                   ``parameters.overrides_from`` → ``with_overrides``
``organisation``              ``roles.from_shape`` → ``roles.review``
``leadership``                rows appended to the engine's own table
``revenue`` / ``employees``   the world builder's ``annual_revenue`` / ``employees``
``geo``                       ``locales.named`` → the recipe, and a pack's geography
``calendar`` / ``estate``     ``profiles.named`` / the estate profiles
``identity`` / ``pack``       ``packs.Pack`` — which keeps winning over all of it
===========================  =================================================

**Why this is a second type and not a wider ``Pack``.** A pack is *identity*:
a real-sounding company name, its divisions, their books, its voices, its
lore. ``pack_export`` marks every identity field ``PLACEHOLDER`` precisely
because neither a Halton coordinate nor an interval graph knows what a company
is called, and inventing one would sign somebody else's name to a fiction. A
specification is the opposite kind of statement — *a description*, true of a
class of businesses, naming no company at all. "A listed mid-size German
insurer on thin margins in a fragmented market" is a complete and useful thing
to say and contains no identity whatsoever, so a schema that required one
would force every describer to invent a company before they could describe a
kind of company.

They also have opposite relationships with the recipe, which is the harder
argument. A pack is embedded **verbatim**, because the pack *is* how the world
was made and a corpus rebuildable only by whoever still had the file would
fail the reason recipes exist. A specification is embedded **not at all**: it
resolves to consequences — spans, a role table, a calendar, lore claims, an
estate, a locale — and those are what the recipe records, exactly as
``--facet`` records consequences rather than facet names. That is the stronger
of the two for a *derived* document: consequences replay this world
byte-for-byte after the facet registry, the archetype table or the locale
presets move underneath it, where a stored ``"a listed German insurer"`` would
replay whatever those came to mean later while reporting success.

**What converts between them, in each direction.**

* A specification with an ``identity`` composes **into** a pack
  (``pack_of``). ``company_name`` is the exact boundary: it is the one field
  no description implies, so a spec that supplies it can write a pack and a
  spec that does not, cannot. That conversion is not a convenience — it is
  the only way a ``geo`` reaches the *build* half of a locale, because
  ``organisation.generate`` takes its regions, name pools and headquarters
  from a pack and nothing else does. A spec naming a geo and no identity
  reports the shortfall as ``unmet`` rather than quietly rendering German
  digits over Australian staff.
* A specification **carrying** a pack (``pack: path``) uses it whole, and the
  pack wins over everything derived. Same precedence
  ``vocabulary.spoken`` keeps for an authored archetype and ``Pack.regions``
  keeps over a locale's pool: the more specific claim, made by a human, beats
  the general one this module inferred.
* Nothing converts a specification back out of a built world. That is
  ``pack_export``'s job and it produces a pack, not a spec — a world can be
  measured for its physics and its shape, and cannot be measured for the
  sentence somebody would have written to ask for it.

**What is a range and what is a value.** The recurring architecture here is
*closed where code reads it, open above it*, and this document sits on both
sides of that line at once:

* **Values** are the things the engine reads exactly once: an archetype key, a
  locale, a calendar, an estate size, a headcount, a revenue figure, a role
  row, a company name. Each is checked against the registry that owns it —
  ``domains``, ``archetypes``, ``locales``, ``profiles``, ``roles.SPINE`` —
  and an unknown one is refused rather than defaulted, because a spec that
  asked for ``germay`` and silently got Australia would build a corpus with
  nothing in it to notice the drop by.
* **Ranges** are the things the engine *draws inside*: every
  ``parameters.Span``. A spec states these as intervals, and it may name only
  parameters ``parameters.DEFAULTS`` already carries. That is the closed half
  and it has to be: a caller free to name an arbitrary parameter would be
  open exactly where code reads, and a generator asking for a name nobody
  registered raises part-way through an episode.
* **Open** is everything nothing reads: ``industry``, ``about``, a span's
  ``source``. Free text, printed back at the describer and carried into the
  corpus's provenance, constraining nothing.

The user-facing consequence is a rule worth stating plainly: *if the engine
draws it, you may only narrow it; if the engine reads it, you may only choose
from what is registered.*

**What refuses.** ``facets.resolve`` refuses an empty intersection with the
arithmetic — a mutual runs 16-26% margin and a premium brand 48-62%, and no
company is both — and a description deserves the same treatment. So does
``roles.from_shape``, on headcount, span and depth. Both are composed here
rather than restated, and one more refusal is derived: see
``productivity_envelope`` for why "revenue 40bn, headcount 12" is refused with
both numbers and the shapes that bound them, and why the bound is computed
from the archetype registry rather than typed in.

**Extensibility, and what a fourth vertical has to write.** Nothing in this
module names a vertical. Engines resolve through ``domains.by_name``,
archetypes through ``archetypes.get``, roles through ``roles.SPINE``,
parameters through ``parameters.DEFAULTS`` — so a fourth vertical that
registers a domain (``domains.register_domain``), a recipe verb
(``recipe.register_step``), its artifact types and its check group becomes
describable here the moment it registers, with no edit to this file. And a
vertical that has not gone that far is still describable *through a pack*: a
spec whose ``pack`` names ``base: "logistics"`` composes and builds without
this module having heard of logistics either. A specification is a composer,
which is exactly why it cannot be the thing that blocks a new engine — it has
no opinions of its own to be wrong about.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Any

from . import archetypes, domains, facets as facets_module, locales, profiles, roles
from .parameters import DEFAULTS, Span, overrides_from

__all__ = [
    "Conflict", "CompanySpec", "FUNCTIONS", "Identity", "Resolution",
    "describe", "from_document", "pack_of", "productivity_envelope", "publish",
    "resolve", "template",
]


#: Departments a synthesised organisation draws from, longest-first so a deeper
#: tree gets more of them. Placeholders in the sense ``roles._LADDER`` is: what
#: a business actually calls its functions is texture a describer supplies with
#: ``organisation.functions``, and this is what it gets for saying nothing.
#:
#: Here rather than in ``sdk`` — where it used to live — because two callers now
#: need it and the second one is this module. A copy in each would drift, and a
#: drifting default means the same specification resolves to a different
#: organisation depending on which door it came through.
FUNCTIONS: tuple[str, ...] = (
    "Executive", "Finance", "Technology", "Operations", "Merchandising",
    "ServiceOperations", "Risk", "Supply Chain", "Digital", "People",
)


def _estate_sizes() -> tuple[str, ...]:
    """Estate sizes ``generators/estate.PROFILES`` registers.

    Read from there rather than restated, so a fourth profile is describable
    the day it is added.
    """
    from .generators import estate

    return tuple(sorted(estate.PROFILES))


#: How many of the reporting currency one ``currency_unit`` is worth. Needed by
#: exactly one check — the revenue-against-headcount refusal — because an
#: archetype states revenue in thousands and another in millions and comparing
#: the raw integers would call a bank a thousand times more productive than a
#: grocer. Deliberately not a general-purpose money layer: nothing else in this
#: project converts between units, and a unit outside this table is handled by
#: *declining to run the check* rather than by guessing (see ``_per_head``).
_MULTIPLIER: Mapping[str, float] = {
    "units": 1.0, "thousands": 1e3, "millions": 1e6, "billions": 1e9,
}


# ---------------------------------------------------------------------------
# The document
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Conflict:
    """One reason a description cannot be built, with the arithmetic where any."""

    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"

    def as_dict(self) -> dict[str, str]:
        return {"subject": self.subject, "rule": self.rule, "detail": self.detail}


@dataclass(frozen=True)
class Identity:
    """The half of a company only a person can supply.

    Optional in its entirety, and that is the design rather than leniency: a
    description of a *kind* of company names none of this, and requiring it
    would make every describer invent a company before they could describe one.
    Supplying ``company_name`` is what turns a description into something that
    can be written as a pack — see ``pack_of``.
    """

    company_name: str = ""
    name: str = ""
    """What to call the pack this identity composes into. Defaults to a slug of
    ``company_name``: the pack name reaches the corpus only as the archetype
    key ``pack:<name>``, so a describer who has named the company has already
    said enough."""

    headquarters: str = ""
    """The one head office. Empty takes the geo's first city — index nought
    rather than a draw, because a specification mints nothing and has no ``Rng``
    stream to draw from. A describer who wants Munich rather than Berlin says
    Munich."""

    regions: tuple[str, ...] = ()
    """Site-estate labels. Empty takes the geo's own, which is the whole point
    of naming a geo."""


@dataclass(frozen=True)
class CompanySpec:
    """A company, described. Every field optional; each one resolves to a seam.

    Immutable, and resolved rather than executed: ``resolve`` turns this into a
    ``Resolution`` of consequences and the document itself never reaches a
    generator, a recipe or a corpus.
    """

    # -- what business it is in --------------------------------------------
    industry: str = ""
    """Free prose, resolved through ``archetypes.inspired_by`` — the existing
    seam for "describe a business and get a shape". Open: nothing reads it but
    the resolver and the corpus's own ``Company.industry``."""

    engine: str = ""
    """A registered domain by name. Omitted, the archetype names its own."""

    archetype: str = ""
    """A registered shape by key, overriding ``industry``'s guess."""

    vocabulary: str = ""
    """What the divisions are *called* — a ``worldloom.vocabulary`` preset. The
    same shape spoken as a different company."""

    # -- how big, and where -------------------------------------------------
    revenue: int | None = None
    """Annual revenue in the archetype's own ``currency_unit``."""

    employees: int | None = None
    """The company's stated headcount, which is a different claim from how many
    people the corpus names (that is ``organisation.headcount``)."""

    geo: str = ""
    """A registered locale. Reaches the figure grammar always, and the people,
    regions and head office only with an ``identity`` — see the module
    docstring, and ``Resolution.unmet`` when there is none."""

    # -- what kind of company ----------------------------------------------
    facets: Mapping[str, str] = _field(default_factory=dict)
    """``worldloom pack facets`` by name: listing, scale, margin_profile,
    competition, governance, maturity, trading_pattern. Named ``facets`` and
    not something more descriptive on purpose — inventing a second word for one
    registry is how two vocabularies for one thing start."""

    physics: Mapping[str, Span] = _field(default_factory=dict)
    """Parameter ranges by registry name, applied *over* whatever the facets
    imply: a range you typed is a statement, a range a facet implied is an
    inference, and the statement wins."""

    calendar: str = ""
    estate: str = ""

    # -- who is in it -------------------------------------------------------
    organisation: Mapping[str, Any] = _field(default_factory=dict)
    """``headcount``, ``span``, ``levels`` and optionally ``functions`` —
    synthesised into a reporting tree by ``roles.from_shape``. Three numbers
    with two degrees of freedom, so an over-determined trio is refused with the
    arithmetic rather than rounded into feasibility."""

    leadership: tuple[tuple[str, str, str, str | None], ...] = ()
    """Roles this company has that the engine's own table does not: key, title,
    function, who they report to. Appended, never substituted — the engine
    looks several keys up by name."""

    # -- identity, or the pack that already holds it ------------------------
    identity: Identity | None = None
    pack: str = ""
    """A path to an authored pack. Mutually exclusive with ``identity``: two
    accounts of one company is the failure every part of this project refuses."""

    # -- open, read by nobody ----------------------------------------------
    about: str = ""
    rivals: tuple[str, ...] = ()
    """Named competitors. Accepted and reported as ``unmet``, one per rival,
    because nothing in this engine mints an entity for a company that is not
    this one: lore asserting a rival exists would constrain no consulted
    target, which is the carried-cited-and-inert failure ``packs.lint`` exists
    to catch. Reported rather than refused for ``facets.Implication.wants``'s
    reason — a consequence a claim honestly has and nothing implements is the
    only honest pressure for implementing it. Say what the market *does* to
    pricing with ``facets: {"competition": ...}``, which is load-bearing."""

    def as_dict(self) -> dict[str, Any]:
        """The document as JSON, omitting everything left at its default.

        Omitting, so a round trip through ``from_document`` gives back the same
        spec and a template of a two-line description stays two lines. The same
        rule ``recipe.build_recipe`` follows and for a weaker version of the
        same reason: a document full of empty keys teaches a reader that the
        keys are required.
        """
        payload: dict[str, Any] = {}
        for key in ("industry", "engine", "archetype", "vocabulary", "geo",
                    "calendar", "estate", "pack", "about"):
            if getattr(self, key):
                payload[key] = getattr(self, key)
        for key in ("revenue", "employees"):
            if getattr(self, key) is not None:
                payload[key] = getattr(self, key)
        if self.facets:
            payload["facets"] = dict(sorted(self.facets.items()))
        if self.physics:
            payload["physics"] = {
                name: span.as_dict() for name, span in sorted(self.physics.items())
            }
        if self.organisation:
            payload["organisation"] = dict(self.organisation)
        if self.leadership:
            payload["leadership"] = [
                {"key": key, "title": title, "function": function,
                 "reports_to": manager}
                for key, title, function, manager in self.leadership
            ]
        if self.rivals:
            payload["rivals"] = list(self.rivals)
        if self.identity is not None:
            identity: dict[str, Any] = {}
            for key in ("company_name", "name", "headquarters"):
                if getattr(self.identity, key):
                    identity[key] = getattr(self.identity, key)
            if self.identity.regions:
                identity["regions"] = list(self.identity.regions)
            payload["identity"] = identity
        return payload


#: Every key the document takes. Closed, and refused by name rather than
#: ignored: a spec with ``margins`` in it (there is no such field — margin is a
#: facet or a physics range) would otherwise build a perfectly ordinary company
#: and give its author nothing to notice the drop by. The same argument
#: ``Parameters.with_overrides`` makes about a mistyped parameter, one layer up.
_FIELDS: frozenset[str] = frozenset({
    "industry", "engine", "archetype", "vocabulary", "revenue", "employees",
    "geo", "facets", "physics", "calendar", "estate", "organisation",
    "leadership", "identity", "pack", "about", "rivals",
})

_IDENTITY_FIELDS: frozenset[str] = frozenset({
    "company_name", "name", "headquarters", "regions",
})

_ORGANISATION_FIELDS: frozenset[str] = frozenset({
    "headcount", "span", "levels", "functions",
})


def from_document(payload: Mapping[str, Any] | str | Path) -> CompanySpec:
    """A specification from JSON: a path, JSON text, or a parsed mapping.

    Unknown keys are an error, not a warning. See ``_FIELDS``.
    """
    if isinstance(payload, (str, Path)):
        # Distinguished by the first character rather than by asking the
        # filesystem whether the string is a path. A whole specification is
        # several hundred bytes, and `Path(text).exists()` on one raises
        # `OSError: File name too long` on Linux before it can answer — which
        # is a filesystem limit deciding whether a document parses. A JSON
        # object starts with `{` and a path does not.
        text = str(payload)
        if not text.lstrip().startswith("{"):
            text = Path(text).read_text(encoding="utf-8")
        payload = json.loads(text)
    if not isinstance(payload, Mapping):
        raise ValueError("a company specification is a JSON object")

    unknown = sorted(set(payload) - _FIELDS)
    if unknown:
        raise ValueError(
            f"unknown field(s) {unknown} in this specification; it takes"
            f" {sorted(_FIELDS)}. Run `worldloom pack spec` for what each one"
            " means and which registry supplies its values."
        )

    identity = payload.get("identity")
    if identity is not None:
        if not isinstance(identity, Mapping):
            raise ValueError("identity is an object")
        unknown = sorted(set(identity) - _IDENTITY_FIELDS)
        if unknown:
            raise ValueError(f"unknown identity field(s) {unknown}; it takes"
                             f" {sorted(_IDENTITY_FIELDS)}")
        identity = Identity(
            company_name=str(identity.get("company_name", "")),
            name=str(identity.get("name", "")),
            headquarters=str(identity.get("headquarters", "")),
            regions=tuple(str(region) for region in identity.get("regions", ())),
        )

    organisation = dict(payload.get("organisation") or {})
    unknown = sorted(set(organisation) - _ORGANISATION_FIELDS)
    if unknown:
        raise ValueError(f"unknown organisation field(s) {unknown}; it takes"
                         f" {sorted(_ORGANISATION_FIELDS)}")

    return CompanySpec(
        industry=str(payload.get("industry", "")),
        engine=str(payload.get("engine", "")),
        archetype=str(payload.get("archetype", "")),
        vocabulary=str(payload.get("vocabulary", "")),
        revenue=None if payload.get("revenue") is None else int(payload["revenue"]),
        employees=None if payload.get("employees") is None else int(payload["employees"]),
        geo=str(payload.get("geo", "")),
        facets={str(k): str(v) for k, v in (payload.get("facets") or {}).items()},
        physics=_spans(payload.get("physics") or {}),
        calendar=str(payload.get("calendar", "")),
        estate=str(payload.get("estate", "")),
        organisation=organisation,
        leadership=_leadership(payload.get("leadership") or ()),
        identity=identity,
        pack=str(payload.get("pack", "")),
        about=str(payload.get("about", "")),
        rivals=tuple(str(rival) for rival in payload.get("rivals", ())),
    )


def _spans(payload: Mapping[str, Any]) -> dict[str, Span]:
    """Physics as a describer writes it: ``[low, high]`` or the full span object.

    Both shapes, because they are written by different hands. ``[0.02, 0.06]``
    is what somebody typing a description writes; the object form is what
    ``worldloom probe resolve`` and ``pack export`` already emit, and refusing
    it would mean a derived physics file could not be pasted into a
    specification. The pair form is normalised into the object form and handed
    to ``parameters.overrides_from``, so there is exactly one parser for a span
    in this project and it is not this one.
    """
    document: dict[str, Any] = {}
    for name, entry in payload.items():
        if isinstance(entry, Sequence) and not isinstance(entry, (str, bytes)):
            pair = list(entry)
            if len(pair) != 2:
                raise ValueError(
                    f"physics[{name!r}] is a two-element [low, high], not"
                    f" {len(pair)} value(s)"
                )
            document[str(name)] = {"low": pair[0], "high": pair[1]}
        elif isinstance(entry, Mapping):
            document[str(name)] = dict(entry)
        else:
            raise ValueError(
                f"physics[{name!r}] is [low, high] or {{'low': …, 'high': …}}"
            )
    return overrides_from(document)


def _leadership(payload: Any) -> tuple[tuple[str, str, str, str | None], ...]:
    rows: list[tuple[str, str, str, str | None]] = []
    for index, entry in enumerate(payload):
        if not isinstance(entry, Mapping):
            raise ValueError(f"leadership[{index}] is an object with key, title,"
                             " function and reports_to")
        missing = [k for k in ("key", "title", "function") if not entry.get(k)]
        if missing:
            raise ValueError(f"leadership[{index}] is missing {missing}")
        manager = entry.get("reports_to")
        rows.append((str(entry["key"]), str(entry["title"]), str(entry["function"]),
                     None if manager is None else str(manager)))
    return tuple(rows)


# ---------------------------------------------------------------------------
# The refusal nobody else can make
# ---------------------------------------------------------------------------


def _carried_by(engine: str) -> frozenset[str]:
    """The fields this engine's world builder actually has.

    Read off the registered class rather than assumed, because the three
    shipped engines already disagree: only ``RetailWorld`` has a
    ``seasonality``, so a trading year claimed for an insurer has nowhere to
    land. ``cli._claimed`` discovered that at build time by catching
    ``TypeError`` and printing ``unmet``; discovering it here means a describer
    reads it from their description instead of from a build.

    The same question a fourth vertical will answer differently — a domain
    registered outside this repository may carry fewer of these, or more — and
    reflection is the only way to ask it without this module keeping a table of
    verticals, which is the one thing it must not do.
    """
    import dataclasses

    registered = domains.by_name(engine) if engine else None
    if registered is None:
        return frozenset()
    try:
        return frozenset(field.name for field in dataclasses.fields(registered.world))
    except TypeError:
        # A domain whose world is not a dataclass. Nothing can be said about
        # what it carries, so nothing is said: every consequence is attempted
        # and the builder's own error is the report.
        return frozenset()


def _per_head(shape: Any) -> float | None:
    """One archetype's revenue per employee, or ``None`` if it cannot be said.

    ``None`` rather than a guess when the currency unit is not one this module
    can convert. A new vertical is free to report in a unit nobody thought of,
    and the honest consequence is that it drops out of the envelope below —
    never that it is silently treated as thousands, which would put a shape a
    thousand times too small at one end and refuse perfectly ordinary
    descriptions on the strength of it.
    """
    multiplier = _MULTIPLIER.get(shape.currency_unit)
    if multiplier is None or not shape.employees:
        return None
    return shape.annual_revenue * multiplier / shape.employees


def productivity_envelope() -> tuple[float, float, str, str] | None:
    """How much revenue per employee this engine believes a company can make.

    Derived, not typed. The registry of archetypes is the *only* place this
    project has ever committed to a revenue figure and a headcount at the same
    time — ``parameters.DEFAULTS`` has no opinion, because
    ``finance.generate`` divides annual revenue by twelve and by unit share and
    never once consults how many people work there, and ``probe`` links
    headcount to span and depth and to nothing monetary. So the four registered
    shapes are what the engine believes, and their extremes are the anchor::

        omnichannel_retailer      97,500 per head
        midsize_adi              200,000
        australian_grocery       331,707
        midsize_general_insurer  514,286

    **Widened by the registry's own spread, and that number is derived too.**
    Refusing everything outside [97,500, 514,286] would refuse a software firm,
    a law practice and a trading desk — all real, none registered — so the
    envelope is extended by the factor the registry itself spans (5.3×) at each
    end. The argument is that the engine has already committed to companies
    differing in productivity by that factor, so one more factor beyond each
    end is a business unlike anything registered and not unlike anything real;
    two factors is not a company, it is a typo. A tolerance derived from the
    data moves when the data does, which a constant would not: register a
    fifth archetype and this widens on its own.

    ``None`` when fewer than two shapes can be compared — a fresh registry, or
    one whose currency units this module cannot convert. No envelope means no
    refusal, which is the right failure: a check that cannot be computed must
    not be invented.
    """
    measured = [
        (per_head, key)
        for key in archetypes.available()
        for per_head in (_per_head(archetypes.get(key)),)
        if per_head is not None
    ]
    if len(measured) < 2:
        return None
    measured.sort()
    (low, low_key), (high, high_key) = measured[0], measured[-1]
    if low <= 0:
        return None
    spread = high / low
    return low / spread, high * spread, low_key, high_key


def _scale_conflicts(spec: CompanySpec, shape: Any) -> list[Conflict]:
    """Every way the stated size contradicts itself.

    Two checks, and both are arithmetic rather than judgement. The first is the
    envelope above. The second is simpler and sharper: a corpus cannot name
    more people than the company employs, because every person the corpus names
    *is* an employee and the headcount fact would contradict the org chart in
    the same workbook.
    """
    found: list[Conflict] = []

    if spec.revenue is not None and spec.employees is not None:
        envelope = productivity_envelope()
        multiplier = _MULTIPLIER.get(shape.currency_unit)
        if envelope is not None and multiplier is not None and spec.employees > 0:
            low, high, low_key, high_key = envelope
            per_head = spec.revenue * multiplier / spec.employees
            if not low <= per_head <= high:
                found.append(Conflict(
                    "revenue/employees", "implausible_productivity",
                    f"{spec.revenue:,} {shape.currency_unit} of revenue across"
                    f" {spec.employees:,} employee(s) is {per_head:,.0f} per"
                    f" head. The shapes this engine knows run {low:,.0f} to"
                    f" {high:,.0f} per head — that is the {low_key} and the"
                    f" {high_key} extremes, each widened by the factor the"
                    " registry itself spans. No company is both of the numbers"
                    " you gave.",
                ))

    headcount = spec.organisation.get("headcount")
    if headcount is not None and spec.employees is not None and headcount > spec.employees:
        found.append(Conflict(
            "organisation.headcount", "more_named_than_employed",
            f"the organisation names {headcount} people and the company employs"
            f" {spec.employees}. Every person a corpus names is an employee, so"
            " the org chart and the headcount fact would contradict each other"
            " in the same workbook.",
        ))
    return found


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Resolution:
    """Everything a description commits a world to, or why it cannot hold.

    Deliberately the same shape as ``facets.Resolved``, one layer up: the same
    ``ok``/``conflicts``/``wants`` posture, so a caller that already handles a
    facet refusal handles this one without learning a second protocol.
    """

    spec: CompanySpec
    archetype_key: str
    """Possibly vocabulary-qualified (``omnichannel_retailer+department_house``),
    which is what makes the words replay off the recipe's single archetype
    string."""

    engine: str
    physics: Mapping[str, Span]
    role_table: tuple[tuple[str, str, str, str | None], ...] | None
    lore_claims: tuple[Any, ...]
    calendar: str | None
    estate: str | None
    locale: str | None
    employees: int | None
    annual_revenue: int | None
    facet_choices: Mapping[str, str]
    pack: Any = None
    """A ``packs.Pack``: loaded from ``spec.pack``, composed from
    ``spec.identity``, or ``None``. When present it is the shape, the lore, the
    name and the geography, and everything derived yields to it."""

    unmet: tuple[str, ...] = ()
    conflicts: tuple[Conflict, ...] = ()

    @property
    def ok(self) -> bool:
        return not self.conflicts

    def as_dict(self) -> dict[str, Any]:
        return {
            "archetype": self.archetype_key,
            "engine": self.engine,
            "physics": {n: s.as_dict() for n, s in sorted(self.physics.items())},
            "role_table": (None if self.role_table is None
                           else [list(row) for row in self.role_table]),
            "lore": [claim.source for claim in self.lore_claims],
            "calendar": self.calendar,
            "estate": self.estate,
            "locale": self.locale,
            "employees": self.employees,
            "annual_revenue": self.annual_revenue,
            "facets": dict(sorted(self.facet_choices.items())),
            "pack": None if self.pack is None else self.pack.name,
            "company_name": None if self.pack is None else self.pack.company_name,
            "unmet": list(self.unmet),
            "conflicts": [conflict.as_dict() for conflict in self.conflicts],
        }

    def raise_for_conflicts(self) -> None:
        if self.conflicts:
            raise ValueError("; ".join(str(conflict) for conflict in self.conflicts))


def resolve(spec: CompanySpec) -> Resolution:
    """Turn a description into the consequences that build it, or refuse it.

    Every refusal is collected rather than raised at the first one: a describer
    who wrote three incompatible things should read three sentences, not three
    error messages one build at a time. Same posture as ``roles.review`` and
    ``compose``'s estate check, for the same reason.
    """
    found: list[Conflict] = []
    unmet: list[str] = []

    # -- the pack, first, because everything else yields to it --------------
    pack = None
    if spec.pack and spec.identity is not None:
        found.append(Conflict(
            "pack/identity", "two_identities",
            "this specification names a pack and an identity. A pack already"
            " says what the company is called, what its divisions are and"
            " where it is; a second account of that is the one thing a"
            " corpus's own recipe exists to make impossible.",
        ))
    if spec.pack:
        from . import packs

        try:
            pack = packs.load(spec.pack)
        except Exception as exc:            # noqa: BLE001 - reported, not swallowed
            found.append(Conflict("pack", "does_not_validate", str(exc)))
        else:
            restated = [
                field for field, given in (
                    ("archetype", bool(spec.archetype)),
                    ("vocabulary", bool(spec.vocabulary)),
                    ("revenue", spec.revenue is not None),
                    ("employees", spec.employees is not None),
                ) if given
            ]
            if restated:
                found.append(Conflict(
                    "pack", "restated_by_the_spec",
                    f"the pack already states {restated}; a specification that"
                    " restated them would give the build two answers and no"
                    " rule for which wins. Edit the pack, or drop the field.",
                ))
            if spec.engine and spec.engine != pack.base:
                found.append(Conflict(
                    "engine", "disagrees_with_pack",
                    f"the spec says {spec.engine!r} and the pack's base is"
                    f" {pack.base!r}",
                ))

    # -- the shape ----------------------------------------------------------
    shape = None
    archetype_key = ""
    if pack is not None:
        from . import packs

        shape = packs.archetype_of(pack)
        archetype_key = shape.key
        engine = pack.base
    else:
        engine, shape, archetype_key, shape_conflicts, shape_unmet = _shape_of(spec)
        found.extend(shape_conflicts)
        unmet.extend(shape_unmet)

    domain = domains.by_name(engine) if engine else None
    if engine and domain is None:
        found.append(Conflict(
            "engine", "unknown_engine",
            f"no domain named {engine!r}; registered: {', '.join(domains.names())}."
            " A vertical becomes describable here the moment it calls"
            " `domains.register_domain` — this module holds no list of its own.",
        ))

    # -- what kind of company ----------------------------------------------
    resolved_facets = facets_module.resolve(**dict(spec.facets))
    for conflict in resolved_facets.conflicts:
        found.append(Conflict(conflict.subject, conflict.rule, conflict.detail))
    unmet.extend(resolved_facets.wants)

    # Facet spans first, the spec's own over them. A range a describer typed is
    # a statement about *this* company; a range a facet implied is an inference
    # from a claim about a kind of company, so the statement wins. The same rule
    # `--physics` already has over `--facet` on the command line, and
    # `Blueprint.facets` over `.physics()` in the SDK.
    physics: dict[str, Span] = dict(resolved_facets.physics)
    physics.update(spec.physics)
    # Refused here rather than left to `Parameters.with_overrides`, which would
    # refuse it at build time. Same rule, said at the point the describer can
    # act on it: they are looking at their own document, and the registry has a
    # command that prints itself.
    unknown = sorted(set(physics) - set(DEFAULTS))
    if unknown:
        found.append(Conflict(
            "physics", "unknown_parameter",
            f"no parameter is registered as {unknown}. A specification may only"
            " narrow a range the engine already draws inside — run"
            " `worldloom pack params` for the registry. Naming an arbitrary one"
            " would be open exactly where code reads, and a generator asking"
            " for a name nobody registered raises part-way through an episode.",
        ))

    carried = _carried_by(engine)

    calendar = spec.calendar or resolved_facets.calendar
    if calendar:
        try:
            profiles.named(calendar)
        except KeyError as exc:
            found.append(Conflict("calendar", "unknown_calendar", str(exc)))
        else:
            if carried and "seasonality" not in carried:
                # Dropped and *said*, rather than raised. Every facet set
                # settles `trading_pattern` at its registry default, so
                # refusing here would make `facets` unusable on two of the three
                # shipped engines over a claim nobody typed — `cli._claimed`
                # made exactly this call and this is the same one, moved
                # earlier.
                unmet.append(
                    f"the {calendar!r} trading year: the {engine} engine's world"
                    " builder has no `seasonality` field, so nothing carries"
                    " one. Only the retail engine reads a trading year today"
                    " (`generators/finance` is the one generator that consults"
                    " it)."
                )
                calendar = ""

    estate = spec.estate or resolved_facets.estate
    if estate and estate not in _estate_sizes():
        found.append(Conflict(
            "estate", "unknown_estate",
            f"no estate profile named {estate!r}; known: {', '.join(_estate_sizes())}",
        ))
    elif estate and carried and "estate" not in carried:
        unmet.append(
            f"an estate of size {estate!r}: the {engine} engine's world builder"
            " has no `estate` field, so no landscape is grown around the"
            " episode's own services."
        )
        estate = ""

    # -- who is in it -------------------------------------------------------
    role_table, role_conflicts = _organisation_of(
        spec, engine, resolved_facets.roles,
        # The archetype's own unit keys, because the per-unit roles are derived
        # from them rather than authored — the same derivation
        # `organisation.generate` makes, from the same source.
        unit_keys=() if shape is None else [unit.key for unit in shape.units],
    )
    found.extend(role_conflicts)

    # -- how big ------------------------------------------------------------
    if shape is not None:
        found.extend(_scale_conflicts(spec, shape))
    for field, value in (("revenue", spec.revenue), ("employees", spec.employees)):
        if value is not None and value <= 0:
            found.append(Conflict(field, "not_positive",
                                  f"{field} is a count of something, and {value} is not one"))

    # -- where --------------------------------------------------------------
    locale = spec.geo or None
    if locale is not None:
        try:
            locales.named(locale)
        except KeyError as exc:
            found.append(Conflict("geo", "unknown_locale", str(exc)))
            locale = None

    # -- identity, and the geography only an identity can carry -------------
    if pack is None and spec.identity is not None and spec.identity.company_name:
        if shape is not None and domain is not None:
            try:
                pack = pack_of(spec, shape, engine, locale=locale, calendar=calendar)
            except Exception as exc:        # noqa: BLE001 - reported, not swallowed
                found.append(Conflict("identity", "does_not_compose", str(exc)))
    elif spec.identity is not None and not spec.identity.company_name and pack is None:
        found.append(Conflict(
            "identity", "no_company_name",
            "an identity without a company name says nothing a description"
            " could not. `company_name` is the field that turns a description"
            " into something that can be written as a pack; everything else in"
            " `identity` qualifies it.",
        ))

    # A locale has two halves and they arrive by two different doors. The
    # figure grammar rides the recipe and is applied by whoever builds this
    # resolution, always. The build half — whose names the people have, what
    # the site regions are called, where the head office is — reaches
    # `organisation.generate` either from the engine's own `locale` field, when
    # it has one, or from a pack's `name_pools`/`regions`/`headquarters`, and
    # from nowhere else. Asked of the engine rather than assumed, because
    # which engines have that field is exactly the kind of thing that changes.
    if locale is not None and pack is None and "locale" not in carried:
        unmet.append(
            f"the {locale} locale's build half: whose names the people have,"
            " what the site regions are called, and where the head office is."
            " Those reach the generators through a pack's `name_pools`,"
            " `regions` and `headquarters`, and this specification names no"
            " company, so it cannot write one. The figure grammar is applied"
            " either way. Add `identity.company_name` to reach the rest."
        )

    if spec.revenue is not None and carried and "annual_revenue" not in carried:
        unmet.append(
            f"annual revenue of {spec.revenue:,}: the {engine} engine's world"
            " builder has no `annual_revenue` field, so every money fact stays"
            " the archetype's own scale."
        )

    if spec.employees is not None and pack is None:
        # Stated because it is invisible otherwise, and it is genuinely
        # surprising: `RetailWorld.employees` exists, rides the recipe, and
        # reaches no generator — `organisation.generate` reads
        # `archetype.employees` for `Company.employees_total` and takes no
        # employees argument at all. Routed through a pack it *is* load-bearing
        # (`packs.archetype_of` copies it onto the archetype), which is why this
        # is reported only on the pack-less path.
        unmet.append(
            f"a stated headcount of {spec.employees:,} on a pack-less build:"
            " the world builder carries it onto the recipe and"
            " `organisation.generate` takes the archetype's own figure for"
            " `Company.employees_total`. Add an `identity` — a composed pack"
            " sets it on the archetype, where it is read."
        )

    # A range this build carries and its engine never draws from. Derived, not
    # tabulated: `parameters.py` names every parameter `<domain>.<subject>.
    # <measure>` precisely so a domain's physics is legible as a block, so a
    # prefix that *is* a registered domain name and is not this build's engine
    # is a range aimed at somebody else's generators. Deliberately silent about
    # `ops.`, `org.`, `capital.` and `reserves.` — the first two are shared and
    # the last two are prefixes no domain is *named* after, so this check
    # cannot speak about them without a table, and a table is the thing this
    # module refuses to keep. Reported rather than refused: the override is
    # legal, it rides the recipe, and it changes nothing, which is exactly the
    # carried-and-inert case `facets.wants` exists to make visible.
    for parameter in sorted(physics):
        prefix = parameter.split(".", 1)[0]
        if engine and prefix != engine and domains.by_name(prefix) is not None:
            unmet.append(
                f"{parameter} is a {prefix} parameter and this build runs the"
                f" {engine} engine: it rides the recipe and no {engine}"
                " generator ever draws from it. Margin bands are"
                " retail's; the other verticals' economics have their own"
                " names in `worldloom pack params`."
            )

    # The one range in the registry whose own `about` says when it is *not*
    # consulted, and the one a describer saying "thin margins" reaches for
    # first. `generators/finance` blends a unit's category margins when it has
    # any and falls back to this parameter when it does not, so an archetype
    # whose every unit has a book of categories draws none of it — the claim
    # rides the recipe and every printed margin is the archetype's. Named
    # explicitly rather than sniffed out of the prose, and the message quotes
    # the registry's own sentence so there is one authority for the rule.
    _MARGIN_FALLBACK = "retail.margin.budget"
    if (_MARGIN_FALLBACK in physics and shape is not None and shape.units
            and all(unit.categories for unit in shape.units)):
        unmet.append(
            f"{_MARGIN_FALLBACK}: every unit of {archetype_key!r} has a"
            " category breakdown, and — "
            + DEFAULTS[_MARGIN_FALLBACK].about.split(". ")[-1].rstrip(".")
            + ". Margins per category are a pack's `units`, not a range."
        )

    for rival in spec.rivals:
        unmet.append(
            f"a named competitor ({rival}) with its own share of the market:"
            " nothing here mints an entity for a company that is not this one,"
            " and lore asserting one would constrain no consulted target."
            " `facets: {\"competition\": …}` says what the market does to"
            " pricing, which is load-bearing."
        )

    return Resolution(
        spec=spec,
        archetype_key=archetype_key,
        engine=engine,
        physics=physics,
        role_table=role_table,
        lore_claims=resolved_facets.claims,
        calendar=calendar or None,
        estate=estate or None,
        locale=locale,
        employees=spec.employees,
        annual_revenue=spec.revenue,
        facet_choices=dict(resolved_facets.chosen),
        pack=pack,
        # Sorted and de-duplicated: two facets can want the same missing
        # behaviour, and a describer reading the same sentence twice learns
        # nothing the second time. `facets.resolve` already sorts its own.
        unmet=tuple(sorted(set(unmet))),
        conflicts=tuple(found),
    )


def _shape_of(spec: CompanySpec) -> tuple[str, Any, str, list[Conflict], list[str]]:
    """The archetype a description names, and the engine that owns it.

    Four ways to say it, narrowest first — an explicit key, an engine's own
    default, prose through ``inspired_by``, and the engine's default of last
    resort. Resolved in that order because each is a *more specific* claim than
    the one after it, which is the precedence rule this project keeps
    everywhere (`Pack.regions` over a locale's, `--estate` over a facet's).
    """
    found: list[Conflict] = []
    unmet: list[str] = []

    engine = spec.engine
    if spec.archetype:
        try:
            base = archetypes.get(spec.archetype)
        except KeyError as exc:
            found.append(Conflict("archetype", "unknown_archetype", str(exc)))
            return engine or "retail", None, spec.archetype, found, unmet
    elif spec.industry:
        base = archetypes.inspired_by(spec.industry)
        fallback = archetypes.inspired_by("")
        if base.key == fallback.key:
            # `inspired_by` falls back rather than raising, which is right for a
            # caller who would rather have a world than an error and wrong for a
            # describer: "a Bavarian machine-tool maker" would silently become a
            # supermarket group. It does not report whether it matched, so this
            # cannot distinguish a genuine retail match from a fallback — and
            # says so, rather than claiming a certainty it does not have.
            unmet.append(
                f"an archetype for {spec.industry!r}: it resolved to"
                f" {base.key!r}, which is also what an unrecognised industry"
                " falls back to. Say `archetype` to be certain, `vocabulary` to"
                " keep the shape and change the words, or write a pack whose"
                " units are this business's own."
            )
    elif engine:
        registered = domains.by_name(engine)
        if registered is None or not registered.default_archetype:
            found.append(Conflict(
                "engine", "no_default_archetype",
                f"domain {engine!r} names no default archetype, so a"
                " specification that says only the engine has nothing to build."
                " Name an `archetype`, or register one on the domain.",
            ))
            return engine, None, "", found, unmet
        base = archetypes.get(registered.default_archetype)
    else:
        base = archetypes.get("omnichannel_retailer")

    key = base.key
    if spec.vocabulary:
        from . import vocabulary as vocabulary_module

        try:
            vocabulary_module.named(spec.vocabulary)
            # Through the qualified key rather than by calling `spoken` and
            # keeping the object: the key is what a recipe stores, so resolving
            # it here proves the same string the recipe will carry rebuilds into
            # the same words.
            key = f"{base.key}{vocabulary_module.QUALIFIER}{spec.vocabulary}"
            base = archetypes.get(key)
        except (KeyError, ValueError) as exc:
            found.append(Conflict("vocabulary", "cannot_dress", str(exc)))
            key = base.key

    owner = domains.for_archetype(base.key)
    if owner is None:
        found.append(Conflict(
            "archetype", "no_owning_domain",
            f"archetype {base.key!r} belongs to no registered domain",
        ))
    elif engine and owner.name != engine:
        found.append(Conflict(
            "engine", "disagrees_with_archetype",
            f"engine {engine!r} does not own archetype {base.key!r} —"
            f" {owner.name!r} does",
        ))
    return (engine or (owner.name if owner else "retail")), base, key, found, unmet


def _functions_of(engine: str, levels: int) -> list[str]:
    """The departments this engine's own organisation is divided into.

    Distinct, in first-appearance order rather than sorted: the shipped table
    reads top-down, so Executive comes before Finance because the chief
    executive comes before the CFO, and alphabetising would put Actuarial
    first for no reason a reader could reconstruct.
    """
    seen: list[str] = []
    try:
        rows = roles.to_rows(roles._shipped(engine))
    except (AttributeError, KeyError):
        rows = ()
    for _, _, function, _ in rows:
        if function not in seen:
            seen.append(function)
    return seen or list(FUNCTIONS[:levels + 2])


def _organisation_of(
    spec: CompanySpec,
    engine: str,
    facet_roles: Sequence[tuple[str, str, str, str | None]],
    unit_keys: Sequence[str] = (),
) -> tuple[tuple[tuple[str, str, str, str | None], ...] | None, list[Conflict]]:
    """The reporting spine this description asks for, checked before it is built.

    ``None`` when the description says nothing about the organisation, which is
    what keeps a spec that talks only about margins byte-identical to the build
    it would otherwise have produced.

    Both refusals are composed rather than restated. ``roles.from_shape``
    already knows that headcount, span and depth are three numbers with two
    degrees of freedom and refuses an over-determined trio with the arithmetic;
    ``roles.review`` already knows every rule a table must satisfy for the
    engine's own lookups to resolve. Running them here rather than at build
    time is the whole value — a describer finds out from their description
    rather than from a ``KeyError`` part-way through an episode.
    """
    found: list[Conflict] = []
    if not spec.organisation and not spec.leadership and not facet_roles:
        return None, found
    if engine not in roles.SPINE:
        # A vertical that registered a domain but no spine cannot have a table
        # synthesised for it, because `roles.required` has nothing to place.
        # Reported as a conflict rather than silently skipped: the description
        # asked for an organisation and would otherwise get the engine's.
        found.append(Conflict(
            "organisation", "no_spine_for_engine",
            f"engine {engine!r} declares no `roles.SPINE` entry, so the keys its"
            " generators look up by name are unknown and no table can be placed."
            " tests/test_roles.py computes what belongs in one.",
        ))
        return None, found

    shipped = {row[0]: row for row in roles.to_rows(roles._shipped(engine))}

    rows: list[tuple[str, str, str, str | None]] = []
    if spec.organisation:
        levels = int(spec.organisation.get("levels", 3))
        # The engine's own functions before the generic ladder, because the
        # engine already knows what it calls them: an insurer runs Actuarial
        # and Claims, and `FUNCTIONS` would put a Head of Merchandising in its
        # org chart on the strength of a list written for retail. Taken in
        # first-appearance order off the shipped table — deterministic, and the
        # order an author reading that table would expect. `FUNCTIONS` remains
        # the answer for an engine that ships none.
        functions = spec.organisation.get("functions") or _functions_of(engine, levels)
        try:
            synthesised = roles.from_shape(
                functions=list(functions),
                headcount=int(spec.organisation.get("headcount", 23)),
                span=int(spec.organisation.get("span", 5)),
                levels=levels,
                engine=engine,
            )
        except ValueError as exc:
            found.append(Conflict("organisation", "shape_does_not_hold", str(exc)))
            return None, found
        # `from_shape` titles every role off a seniority ladder, which is right
        # for a probe — a derived organisation has no titles to keep — and
        # wrong here. This engine already knows what it calls its own spine:
        # `controller` is the Group Financial Controller, not "Director of
        # Technology" because that is what the ladder happened to reach at
        # depth one. Restoring the shipped title and function for a key the
        # engine ships, and only for those, keeps the *shape* the describer
        # asked for while keeping the *names* the engine had — the two claims
        # are independent, and throwing the second away is information loss
        # nobody asked for. Invented roles keep their ladder titles, which is
        # the honest signal that nobody has named them yet.
        rows = [
            (key, shipped[key][1], shipped[key][2], manager) if key in shipped
            else (key, title, function, manager)
            for key, title, function, manager in roles.to_rows(synthesised)
        ]
    else:
        rows = list(shipped.values())

    have = {row[0] for row in rows}
    # The describer's own roles before the facets', and neither replaces a key
    # that already exists. A leadership row is what somebody *said*; a facet
    # role is what a claim implies; and the engine's own row is what its
    # generators look up. Later wins would let a facet quietly rename a spine
    # key, which is the one substitution `roles.review` cannot catch because the
    # key is still there.
    for row in (*spec.leadership, *facet_roles):
        if row[0] not in have:
            rows.append(row)
            have.add(row[0])

    # Reviewed against the table the *generator* will assemble, not the one this
    # returns. `organisation.generate` appends a row per unit per suffix after
    # taking whatever table it is handed, and the engine's own rows already
    # depend on those: retail's `merch_lead` reports to `gm_md`, which is a
    # per-unit role and therefore not in any table a caller writes. Reviewing
    # without them would refuse every retail organisation for an unknown
    # manager, and adding them to the returned table would make the generator
    # append each one twice. So they are stand-ins: present for the check,
    # discarded afterwards, with their titles and their real managers left to
    # the generator that mints them.
    stand_ins = [
        (key, key, "Executive", roles.ROOT)
        for key in roles.required(engine, unit_keys)
        if key not in have
    ]
    for rejection in roles.review(roles.from_rows([*rows, *stand_ins]),
                                  engine=engine, unit_keys=unit_keys):
        found.append(Conflict(rejection.subject, rejection.rule, rejection.detail))
    return tuple(rows), found


# ---------------------------------------------------------------------------
# Description to identity
# ---------------------------------------------------------------------------


def pack_of(
    spec: CompanySpec,
    shape: Any,
    engine: str,
    *,
    locale: str | None = None,
    calendar: str | None = None,
) -> Any:
    """The pack a description with an identity composes into.

    **Why this exists at all**, given that a spec is not a pack: the *build*
    half of a locale has exactly one door. ``organisation.generate`` takes
    ``name_pools``, ``regions`` and ``headquarters``, and the three world
    builders pass them from a pack and from nothing else. So a description that
    says "German" reaches the figure grammar through the recipe and reaches the
    people, the sites and the head office through a pack or not at all. Writing
    the pack is therefore not a convenience layered on top of the composition —
    it *is* the composition, for the one attribute that has no other route.

    **What it fills in, and what it refuses to.** Units, categories, site
    formats, currency and scale come off the resolved archetype, so a pack
    composed here is the shape the description already asked for, spoken in the
    vocabulary it already chose. Geography comes off the locale. The company's
    *name* comes from the describer and from nowhere else — that is the whole
    boundary, and it is why this function takes a spec with an identity rather
    than deriving one: a name invented here would be ``pack_export``'s refused
    PLACEHOLDER, minted anyway and signed with somebody else's fiction.

    **What it does not carry: lore.** Facet lore reaches a world through
    ``lore_claims`` and ``world.extend_lore``, never through ``Pack.lore``, and
    that seam's own docstring is the argument — pack lore is authored prose a
    lint holds an author to, and derived claims put sentences nobody wrote in
    front of it. Composing a pack here does not change where facet lore goes.
    """
    from . import packs

    identity = spec.identity or Identity()
    if not identity.company_name:
        raise ValueError("a composed pack needs identity.company_name")

    place = locales.named(locale) if locale else None
    regions = list(identity.regions) or (list(place.regions) if place else [])
    headquarters = identity.headquarters
    if not headquarters and place is not None and place.cities:
        city, country = place.cities[0]
        headquarters = f"{city}, {country}"

    return packs.load({
        "name": identity.name or _slug(identity.company_name),
        "base": engine,
        "description": spec.about or shape.label,
        "company_name": identity.company_name,
        "industry": spec.industry or shape.industry,
        # The locale's currency, the archetype's unit. `locales` argues that
        # split out: a bank reports in millions and a grocer in thousands in
        # the same country, so scale belongs to the company and the currency to
        # the jurisdiction.
        "currency": place.currency if place else shape.currency,
        "currency_unit": shape.currency_unit,
        "fiscal_year_start_month": (place.fiscal_year_start_month if place
                                    else shape.fiscal_year_start_month),
        "annual_revenue": spec.revenue or shape.annual_revenue,
        "employees": spec.employees or shape.employees,
        "units": [
            {
                "key": unit.key, "name": unit.name, "kind": unit.kind,
                "share": unit.share,
                "categories": [
                    {"name": c.name, "share": c.share, "margin": c.margin}
                    for c in unit.categories
                ],
                "site_formats": [
                    {"name": f.name, "count": f.count, "revenue_weight": f.revenue_weight}
                    for f in unit.site_formats
                ],
            }
            for unit in shape.units
        ],
        **({} if place is None else {
            "regions": regions,
            "name_pools": {"given": list(place.given), "family": list(place.family)},
        }),
        **({} if not headquarters else {"headquarters": headquarters}),
        # The trading year goes on the pack as well as on the builder, because
        # `World.from_pack` resolves seasonality from `packs.seasonality_of`
        # and a facet's would otherwise be dropped on the floor. Only when the
        # engine can carry one at all: a pack field that no builder reads is
        # the carried-and-inert failure written into an artifact that travels.
        **({} if not calendar or "seasonality" not in _carried_by(engine)
           else {"seasonality": calendar}),
    })


def _slug(name: str) -> str:
    """A pack name from a company name: lowercase, hyphenated, alphanumeric.

    Deterministic and unlovely on purpose. It reaches the corpus only as the
    archetype key ``pack:<name>``, so it has to be stable across processes and
    does not have to be pretty.
    """
    kept = [character.lower() if character.isalnum() else "-" for character in name]
    return "-".join(part for part in "".join(kept).split("-") if part) or "company"


# ---------------------------------------------------------------------------
# Publication
# ---------------------------------------------------------------------------

#: Every field, what it means, and which registry supplies its values. Data
#: rather than prose because a describer — human or model — should be able to
#: enumerate the surface without reading this file, the same reason
#: `parameters.publish` and `facets.describe` exist.
_SCHEMA: tuple[tuple[str, str, str, str], ...] = (
    ("industry", "open", "",
     "What the business does, in prose. Resolved through the same phrase table"
     " `--inspired-by` uses; say `archetype` instead when you want certainty."),
    ("engine", "value", "worldloom.domains",
     "Which registered vertical runs the episode. Omitted, the archetype names"
     " its own."),
    ("archetype", "value", "worldloom archetypes",
     "A registered company shape by key."),
    ("vocabulary", "value", "worldloom pack landscapes / vocabulary.VOCABULARIES",
     "What the divisions are called. The same shape spoken as a different"
     " company."),
    ("revenue", "value", "",
     "Annual revenue in the archetype's currency unit. Reaches the world"
     " builder's `annual_revenue`, which every money fact is derived from."),
    ("employees", "value", "",
     "The company's stated headcount. Load-bearing only through a pack — see"
     " the `unmet` line a pack-less build prints."),
    ("geo", "value", "worldloom pack locales",
     "The jurisdiction. Reaches the figure grammar always; reaches the people,"
     " the regions and the head office only with an `identity`."),
    ("facets", "value", "worldloom pack facets",
     "What the company *is*, as claims with consequences. Naming any facet"
     " settles every facet at its registry default."),
    ("physics", "range", "worldloom pack params",
     "Parameter ranges the engine draws inside, by registry name. Applied over"
     " whatever the facets imply."),
    ("calendar", "value", "worldloom pack profiles",
     "The trading year."),
    ("estate", "value", "generators/estate.PROFILES",
     "How much technology landscape: small, medium, large."),
    ("organisation", "value", "worldloom.roles",
     "headcount, span, levels, functions — synthesised into a reporting tree."
     " Three numbers with two degrees of freedom."),
    ("leadership", "value", "worldloom.roles",
     "Roles this company has that the engine's table does not. Appended, never"
     " substituted."),
    ("identity", "value", "worldloom.packs",
     "company_name, name, headquarters, regions. The half only a person can"
     " supply, and what turns a description into a pack."),
    ("pack", "value", "worldloom pack check",
     "An authored pack, used whole. Wins over everything derived. Mutually"
     " exclusive with `identity`."),
    ("rivals", "open", "",
     "Named competitors. Reported as unmet, one per rival: nothing here mints"
     " an entity for a company that is not this one."),
    ("about", "open", "",
     "Prose for whoever reads the document next. Read by nobody."),
)


def describe() -> dict[str, Any]:
    """The schema as data, including where each field's values come from."""
    return {
        "fields": [
            {"field": field, "kind": kind, "registry": registry, "about": about}
            for field, kind, registry, about in _SCHEMA
        ],
        "engines": domains.names(),
        "archetypes": archetypes.available(),
        "locales": sorted(locales.LOCALES),
        "calendars": sorted(profiles.PROFILES),
        "estates": list(_estate_sizes()),
        "facets": {name: list(facets_module.choices(name))
                   for name in sorted(facets_module.FACETS)},
        "parameters": sorted(DEFAULTS),
    }


def publish() -> dict[str, Any]:
    return describe()


def template() -> dict[str, Any]:
    """A starter document: the sentence somebody would actually say, as JSON.

    Filled in rather than blank, and filled in with a company this repository
    cannot express any other way — a listed German insurer in a fragmented
    market — because a template of empty strings teaches the schema and a
    template of a real description teaches what the schema is *for*.
    """
    return {
        "about": "A listed mid-size German general insurer in a fragmented"
                 " broker market, carrying decades of systems.",
        "industry": "General insurance",
        "geo": "germany",
        "facets": {
            "listing": "listed",
            "scale": "midmarket",
            "competition": "fragmented",
            "maturity": "legacy",
            # `margin_profile` is deliberately absent, and its absence is the
            # lesson: the only margin bands in the registry are retail's, so
            # claiming one here would ride the recipe and change nothing an
            # insurance generator reads — which `resolve` reports as unmet.
            # Said explicitly instead, because naming any facet settles every
            # facet at its registry default, and an insurer's year is a book
            # rather than a till.
            "trading_pattern": "steady",
        },
        "organisation": {"headcount": 26, "span": 5, "levels": 3},
        "leadership": [
            {"key": "chief_underwriting", "title": "Chief Underwriting Officer",
             "function": "Executive", "reports_to": "ceo"},
        ],
        "identity": {
            "company_name": "Rheinmark Versicherung",
            "headquarters": "Munich, Germany",
        },
    }
