"""The organisation-building mechanism, shared by every vertical.

Extracted from ``organisation.py`` and ``banking_org.py`` *after* both existed —
the §7a rule, applied: two implementations showed which parts genuinely repeat,
and this module is exactly that intersection. What repeats is **mechanism** —
how identity, ordering, dates, and wiring work:

* roles minted parents-first, by distance from the org root;
* join dates drawn from a stream named after the role, so adding a role
  elsewhere never reshuffles anyone's tenure;
* people minted before manager wiring, so every manager exists before its
  reports reference it;
* business units formed no earlier than their leader joined and no earlier
  than the oldest dated lore commitment, since lore asserts things happened
  *to* the unit by those dates;
* one founding milestone event and fact per dated commitment, minted last so
  they can never renumber an entity id;
* lore-driven traits attached to the person, never the shared persona.

What deliberately does **not** live here is content: role tables, personas,
systems, services, policies, and company naming stay in the domain modules,
because those are the things the telco experiment showed leak between
industries when shared. A domain module supplies one callback — ``assign``,
which decides a person's unit, cost centre, and persona from their role — and
owns everything the callback closes over.

Byte-identity note: both org generators were refactored onto this module with
their minting and rng-draw order unchanged, verified by diffing full corpus
exports before and after. Anything edited here moves every seed's output;
treat the draw order as API.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta

from ..ids import Minter
from ..locales import DEFAULT as DEFAULT_LOCALE
from ..locales import Locale
from ..models import (
    Authority,
    BusinessUnit,
    CanonicalFact,
    ConstraintKind,
    Employee,
    EnterpriseEvent,
    LoreCommitment,
    LoreKind,
    Quantity,
)
from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from ..roles import unit_role_key
from . import names


def stated_headcount(
    requested: int | None,
    *,
    archetype_headcount: int,
    modelled_headcount: int,
) -> int:
    """Resolve the company's stated workforce without pretending it is the roster.

    Worldloom materialises the decision-making graph, not one row per employee.
    ``modelled_headcount`` is therefore the hard lower bound: every named person
    is an employee, while the remainder may stay aggregate.  Keeping this rule
    beside the shared people builder gives every vertical the same refusal and
    stops ``--employees 5`` producing a company whose own file names twenty
    employed people.

    ``None`` is the byte-stable path: the archetype's historical value is used
    exactly as before this seam existed.
    """
    total = archetype_headcount if requested is None else requested
    if total < modelled_headcount:
        raise ValueError(
            f"stated headcount {total:,} is smaller than the {modelled_headcount:,}"
            " people the organisation must model; increase --employees or use a"
            " smaller authored role table"
        )
    return total

#: A role-table row: (role key, title, function, manager role key).
RoleRow = tuple[str, str, str, str | None]

#: What ``assign`` returns for one person: (business unit id, cost centre id,
#: persona id). Any of the three may be None.
Assignment = tuple[str | None, str | None, str | None]


#: What kind of milestone event a lore commitment becomes. A DECISION reads
#: differently on the timeline from an EVENT — "the mapping was decided" is not
#: "the checkout stack was replatformed" — so the distinction the lore already
#: carries is preserved onto the event rather than collapsing every commitment
#: into one generic "milestone" kind that a reader could not tell apart.
_MILESTONE_KIND: dict[LoreKind, str] = {
    LoreKind.EVENT: "milestone_occurred",
    LoreKind.DECISION: "milestone_decided",
    LoreKind.NORM: "milestone_norm_adopted",
    LoreKind.CONSTRAINT: "milestone_constraint_identified",
    LoreKind.TENSION: "milestone_tension_surfaced",
}

#: No one can appear to have joined later than this and still safely author
#: every artifact this corpus writes. Close periods start in 2026 at the
#: earliest (the CLI's own default period is "2026-03"), so this sits most of a
#: year ahead of that — comfortable margin without inspecting any actual period,
#: which the builders here have no reason to know about.
_LATEST_JOIN = datetime(2025, 6, 1, tzinfo=UTC)


def _month_start(effective_from: str) -> datetime:
    """The first instant of an ``"YYYY-MM"`` lore date, UTC.

    Split-and-int rather than a date-parsing library: the value is constrained
    to exactly this shape by every lore function, and pulling in a calendar
    parser for it would be a dependency to cover a format string already this
    simple.
    """
    year, month = effective_from.split("-")
    return datetime(int(year), int(month), 1, tzinfo=UTC)


def _earliest_effective(lore: tuple[LoreCommitment, ...]) -> datetime:
    """The earliest dated lore commitment, anchoring business-unit formation.

    Falls back to ``_LATEST_JOIN`` when there is no lore to anchor to — the
    ``lore`` parameter defaults to ``()`` for a caller that only wants the org
    graph — so a unit still gets a formation date either way.
    """
    dated = [c.effective_from for c in lore if c.effective_from]
    if not dated:
        return _LATEST_JOIN
    # "YYYY-MM" strings sort lexicographically in calendar order, so a plain
    # `min` over the raw strings is exact — no need to parse before comparing.
    return _month_start(min(dated))


def _depth(role: str, managers: dict[str, str | None], seen: frozenset[str] = frozenset()) -> int:
    """Distance from the root, so people are minted parents-first."""
    if role in seen:
        raise ValueError(f"reporting cycle at {role}")
    manager = managers.get(role)
    return 0 if manager is None else 1 + _depth(manager, managers, seen | {role})


def _joined_date(rng: Rng, role: str, depth: int, physics: Parameters = DEFAULT) -> datetime:
    """A join date for *role*, further back the closer it sits to the org root.

    An executive who has been here a decade and an analyst hired last year is a
    more useful world than one where everyone started the same day — it is what
    makes ``World.org_at`` produce a different roster at different moments.
    ``depth`` (distance from the CEO in the reporting tree) stands in for
    seniority, since every leadership role sorts shallow and every
    individual-contributor role sorts deep by construction of the role tables.

    Tenure is drawn from a stream named after the role, not after draw order,
    so adding a role elsewhere can never reshuffle anyone else's join date.
    """
    tenure_rng = rng.derive(f"joined/{role}")
    # Six years of headroom per level, floored at half a year so even the
    # deepest role has clearly joined before the corpus's close periods rather
    # than landing on day zero.
    min_years = max(0.5, 6.0 - depth * 2.0)
    max_years = min_years + 6.0
    # The only registry draw in this module that is not the range it replaced:
    # `org.tenure.years` is the *position within* the band above, because the
    # band's ends are derived from depth and a pack cannot state them as one
    # range. Scaling a unit draw is bit-identical to drawing across
    # [min_years, max_years] directly — `Rng.number` is `random.uniform`, which
    # is `a + (b - a) * random()`, and float multiplication commutes — so this
    # is a rewrite of the arithmetic and not of the world. Verified across every
    # band `depth` can produce rather than argued from the identity alone.
    position = physics.number("org.tenure.years", tenure_rng)
    tenure_days = (min_years + position * (max_years - min_years)) * 365.25
    return _LATEST_JOIN - timedelta(days=tenure_days)


def sorted_roles(role_table: Sequence[RoleRow]) -> tuple[list[RoleRow], dict[str, int]]:
    """The role table in parents-first order, with each role's depth.

    Sorting by depth is what lets one pass mint everyone: a manager's id
    exists before any report needs it, whatever order the domain wrote its
    table in.
    """
    table = list(role_table)
    managers = {row[0]: row[3] for row in table}
    table.sort(key=lambda row: _depth(row[0], managers))
    return table, {row[0]: _depth(row[0], managers) for row in table}


def mint_people(
    rng: Rng,
    minter: Minter,
    role_table: Sequence[RoleRow],
    depth_of: dict[str, int],
    *,
    assign: Callable[[str, str, str], Assignment],
    given: Sequence[str] | None = None,
    family: Sequence[str] | None = None,
    locale: Locale = DEFAULT_LOCALE,
    physics: Parameters = DEFAULT,
) -> tuple[dict[str, str], list[Employee]]:
    """Mint one person per role row, in table order.

    ``assign`` is the domain's one decision per person — which unit they sit
    in, which cost centre carries them, which persona they write with — and is
    called with (role, title, function). Everything else about a person is
    mechanism: name pools, id sequence, join date, and a ``left`` of ``None``,
    because departures are a scenario's concern, not the beginning's.

    ``given``/``family``/``locale`` pass straight through to
    ``names.people_names``, which owns the precedence between them: a pack's
    ``name_pools`` is a claim about *this company's* people and beats the
    ``locale``, which is a claim about the country they are in. Stated once
    there rather than resolved here, because three domain modules call this and
    three copies of "pool or locale" is three places the rule can drift.

    ``locale`` is threaded rather than left to ``people_names``'s own default
    for the reason ``hierarchy.generate`` gives about ``regions``: reaching for
    a module default *shadows* the locale a caller already decided, and it does
    so invisibly — a Frankfurt company whose staff are all called Rafferty is
    entirely plausible prose, so there is nothing in the corpus to notice the
    drop by. Defaulted here so an un-localised call draws from the same
    Australian pools it always did.

    Draw order is contract: names from ``rng.derive("people")``, join dates
    from ``rng.derive("founding")`` — the labels both original generators used,
    kept so existing seeds reproduce their worlds. A locale changes *which*
    pool is sampled and never how many draws are taken from it, so a localised
    world differs in its names and in nothing downstream of them.
    """
    person_names = names.people_names(
        rng.derive("people"), len(role_table), given=given, family=family, locale=locale
    )
    founding_rng = rng.derive("founding")
    role_ids: dict[str, str] = {}
    people: list[Employee] = []
    for (role, title, function, _manager), person_name in zip(role_table, person_names):
        person_id = minter.next("PERSON")
        role_ids[role] = person_id
        business_unit, cost_centre, persona = assign(role, title, function)
        people.append(
            Employee(
                id=person_id,
                name=person_name,
                title=title,
                joined=_joined_date(founding_rng, role, depth_of[role], physics),
                left=None,
                manager_id=None,  # wired by `wire_managers`, once every role has an id
                business_unit_id=business_unit,
                function=function,
                cost_centre_id=cost_centre,
                persona_id=persona,
            )
        )
    return role_ids, people


def wire_managers(
    people: list[Employee], role_table: Sequence[RoleRow], role_ids: dict[str, str]
) -> list[Employee]:
    """Point every person at their manager, now that every manager has an id."""
    manager_of = {row[0]: row[3] for row in role_table}
    role_of_person = {pid: role for role, pid in role_ids.items()}
    return [
        person.model_copy(
            update={"manager_id": role_ids.get(manager_of[role_of_person[person.id]] or "", None)}
        )
        for person in people
    ]


def form_units(
    units,  # type: ignore[no-untyped-def]  # a sequence of UnitSpec
    unit_ids: dict[str, str],
    role_ids: dict[str, str],
    people: list[Employee],
    company_id: str,
    lore: tuple[LoreCommitment, ...],
) -> tuple[BusinessUnit, ...]:
    """Business units, formed no earlier than lore requires or their leader allows.

    Anchored to the earliest dated lore commitment rather than an arbitrary
    constant: lore asserts things happened by certain dates, so the unit those
    things happened *to* must already have existed by then. Clamped forward of
    the leader's own join — never back — because a unit cannot form before the
    person leading it was here to lead it; ``validate.py``'s
    ``leader_not_yet_employed`` enforces exactly that. ``dissolved`` stays
    ``None``: no unit has closed at build, same as no one has left.
    """
    joined_by_person = {p.id: p.joined for p in people}
    lore_anchor = _earliest_effective(lore)
    return tuple(
        BusinessUnit(
            id=unit_ids[unit.key],
            name=unit.name,
            company_id=company_id,
            leader_id=role_ids[unit_role_key(unit.key, "_md")],
            kind=unit.kind,
            formed=max(lore_anchor, joined_by_person[role_ids[unit_role_key(unit.key, "_md")]]),
        )
        for unit in units
    )


def _persona_traits(lore: tuple[LoreCommitment, ...], role_ids: dict[str, str]) -> dict[str, dict[str, float]]:
    """Apply lore ``persona_trait`` constraints, keyed by person ID.

    A constraint target is written ``ROLE/trait`` — a role rather than a person
    ID, because lore is authored before the graph exists and cannot know who
    ``PERSON-0017`` will be.
    """
    out: dict[str, dict[str, float]] = {}
    for commitment in lore:
        for constraint in commitment.constrains:
            if constraint.kind.value != "persona_trait":
                continue
            role, _, trait = constraint.target.partition("/")
            person_id = role_ids.get(role)
            if person_id is None or not trait:
                continue
            out.setdefault(person_id, {})[trait] = constraint.magnitude or 0.0
    return out


def apply_traits(
    people: Sequence[Employee], lore: tuple[LoreCommitment, ...], role_ids: dict[str, str]
) -> tuple[Employee, ...]:
    """Lore-driven traits, attached to the person and never the shared persona —
    one defensive individual must not make everyone with their job defensive."""
    traits = _persona_traits(lore, role_ids)
    return tuple(
        person if person.id not in traits else person.model_copy(update={"traits": traits[person.id]})
        for person in people
    )


#: What an accountability fact is called. One kind, not one per measure, so a
#: reader asking "what is this person answerable for" has a single thing to look
#: for and the measure they are answerable *for* is the fact's own text.
ACCOUNTABILITY_KIND = "org.accountability"

#: The tolerance band a role is judged within, when its lore does not say. Five
#: per cent because that is the band a variance memo in this corpus treats as
#: worth explaining — it is a default, and a pack that means something else
#: should say so rather than inherit this.
DEFAULT_TOLERANCE_PCT = 5.0


def accountability_facts(
    minter: Minter,
    lore: tuple[LoreCommitment, ...],
    role_ids: dict[str, str],
) -> tuple[CanonicalFact, ...]:
    """One fact per ``accountability`` constraint: this person, this measure.

    The edge the corpus did not have. A budget attaches to a business unit and
    a variance is reported against it, but nothing anywhere said who answers
    for either — so a reader could ask what the miss *was* and never who was
    answerable for it.

    Targets are written ``role_key/fact_kind`` and resolved through
    ``role_ids``, exactly as ``persona_trait`` is and for the same reason: lore
    is authored before the graph exists and cannot know who ``PERSON-0017``
    will be. A target naming a role this world does not have is skipped rather
    than raising — a pack shared across archetypes will legitimately name roles
    one of them lacks, and ``packs.lint`` is where an author is told about it.

    Minted last and only when lore asks for it. Both halves matter: no shipped
    lore carries this kind, so every existing corpus mints nothing here and is
    byte-identical, and appending after the founding milestones means the FACT
    sequence can only grow at the end rather than renumbering a fact some
    narration already cites.
    """
    facts: list[CanonicalFact] = []
    for commitment in lore:
        for constraint in commitment.constrains:
            if constraint.kind is not ConstraintKind.ACCOUNTABILITY:
                continue
            role, _, measure = constraint.target.partition("/")
            person_id = role_ids.get(role)
            if person_id is None or not measure:
                continue
            facts.append(CanonicalFact(
                id=minter.next("FACT"),
                kind=ACCOUNTABILITY_KIND,
                subject=person_id,
                # The measure as text and the tolerance as the value, because
                # the fact makes one claim in two parts: *what* this person is
                # judged on, and *how far* it may move before anyone asks. Two
                # facts would make the second orphanable.
                text_value=measure,
                value=Quantity(
                    amount=(DEFAULT_TOLERANCE_PCT if constraint.magnitude is None
                            else constraint.magnitude),
                    unit="percent",
                ),
                # From when the commitment that created it takes effect, not
                # from a timestamp the caller passed in: an accountability
                # begins when the thing that assigned it does, and dating it
                # otherwise would let `World.org_at` report somebody answerable
                # for a measure before anyone had made them so.
                valid_from=(_month_start(commitment.effective_from)
                            if commitment.effective_from else _LATEST_JOIN),
                authority=Authority.SYSTEM_OF_RECORD,
                lore_ids=[commitment.id],
            ))
    return tuple(facts)


def founding_milestones(
    minter: Minter, lore: tuple[LoreCommitment, ...], company_id: str
) -> tuple[tuple[EnterpriseEvent, ...], tuple[CanonicalFact, ...]]:
    """One milestone event and fact per dated lore commitment.

    Every dated commitment becomes a witness on the corpus's own timeline:
    without it, lore asserts dated things ("remapped in 2024-08") that no event
    or fact records, and a reader asking "when" gets an answer from prose that
    nothing backs.

    Called last, once every entity is minted — so adding this feature never
    renumbers a PERSON, BU, CAT, or SITE id that already existed. Events still
    take the shared "EV" sequence (``validate.py``'s referential checks require
    a fact's ``event_id`` to resolve to prefix "EV", so there is no other
    choice), which does shift where a *scenario's* first event lands —
    acceptable, because nothing addresses an event by literal id across a
    build.

    Facts are different, and get their own "MFACT" sequence rather than
    "FACT". A generated world's very first scenario-minted fact — the close
    calendar's due date — has always been ``FACT-0001``, and
    ``examples/grocery-close/narration.json`` cites it by exactly that id (and
    everything after it, by exact id, all the way through the workbook). If
    founding facts took even one "FACT" number before the first close ran,
    every fact a scenario mints afterwards would shift down and that reference
    narration — real prose, checked in and replayed byte-for-byte in CI —
    would reject outright. A milestone fact is standing background, not
    something any scenario-era artifact currently cites, so it costing nothing
    against the "FACT" sequence is exactly the property that keeps the
    existing corpus's fact identity untouched.
    """
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    for commitment in lore:
        if not commitment.effective_from:
            continue
        occurred_at = _month_start(commitment.effective_from)
        event = EnterpriseEvent(
            id=minter.next("EV"),
            kind=_MILESTONE_KIND[commitment.kind],
            occurred_at=occurred_at,
            summary=commitment.assertion,
            lore_ids=[commitment.id],
        )
        events.append(event)
        facts.append(
            CanonicalFact(
                id=minter.next("MFACT"),
                kind="lore.milestone",
                subject=company_id,
                text_value=commitment.assertion,
                # Must equal the event's `occurred_at`: `validate.py`'s
                # `fact_precedes_event` check rejects a fact that claims validity
                # before the event it cites actually happened.
                valid_from=occurred_at,
                authority=Authority.CONFIRMED,
                event_id=event.id,
                # The whole point: a document citing this fact reaches the lore
                # that shaped it via `World.provenance()`.
                lore_ids=[commitment.id],
            )
        )
    return tuple(events), tuple(facts)
