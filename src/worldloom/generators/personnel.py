"""The personnel generator.

Org change is a first-class thing the world can do, not a mutation performed on
the side: someone joins, someone leaves, a unit gets a new leader, and each of
those is witnessed by an ``EnterpriseEvent`` and a ``CanonicalFact`` exactly like
a revenue variance or an incident is. Nothing here touches a ``World`` — these
functions take the pieces of it they need and return what changed, the same
division ``finance.generate`` and ``operations.generate`` already keep, so a
scenario is the only layer that knows how to fold an ``OrgChange`` into a world.

A departure is deliberately not a hire in reverse. Hiring mints a new identity;
leaving closes a window on an identity that already exists. Conflating the two —
giving a departing employee record a fresh ``PERSON`` id — would make "did the
person who signed March's close also sign April's" an unanswerable question,
which is the exact thing ``World.org_at`` and the ``temporal`` validator group
exist to answer.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..ids import Minter
from ..models import Authority, BusinessUnit, CanonicalFact, Employee, EnterpriseEvent
from ..rng import Rng
from . import names


@dataclass(frozen=True)
class OrgChange:
    """What a personnel change produces. Never a ``World`` — a scenario extends
    one with these fields, the same way it extends one with a ``CloseEpisode``
    or a ``Financials``.

    ``people`` and ``business_units`` merge into the world by id (see
    ``World.extend``): a hire appends a new id, a departure or a leadership
    change replaces an existing record in place. ``roles`` rebinds whichever
    role keys the change affects, so the next episode plans its artifacts
    against who actually holds a post rather than who first held it.
    """

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    people: tuple[Employee, ...]
    business_units: tuple[BusinessUnit, ...] = ()
    roles: dict[str, str] = field(default_factory=dict)


def _employed_at(employee: Employee, moment: datetime) -> bool:
    """Whether *employee* was on the roster at *moment*.

    Exactly ``World.org_at``'s window, reimplemented against a single record
    rather than a whole world: a departure or promotion only ever has the one
    or two ``Employee`` rows in front of it, never the roster to search. The
    two implementations have to agree, because this is the check that decides
    whether a succession is coherent *before* the validator ever sees it —
    disagreeing with ``org_at`` here would let a bad succession through in one
    place and get caught in the other, which is worse than catching it nowhere.
    """
    if employee.joined is not None and employee.joined > moment:
        return False
    if employee.left is not None and employee.left <= moment:
        return False
    return True


def hire(
    rng: Rng,
    minter: Minter,
    *,
    company_id: str,
    title: str,
    function: str,
    business_unit_id: str | None,
    manager_id: str | None,
    cost_centre_id: str | None,
    persona_id: str | None,
    at: datetime,
    period: str,
) -> OrgChange:
    """A new person joins, effective *at*.

    Always a new ``PERSON`` id with ``joined`` set — the counterpart to
    ``depart`` never reusing one. ``company_id`` is accepted rather than
    threaded into anything: it keeps this entry point's signature the same
    shape as every other generator's (``rng, minter`` first, thin-waist ids
    after), even though a hire's own fact and event are scoped to the person,
    not the company.
    """
    del company_id  # see docstring: kept for signature symmetry only

    # A single name, not a call site that also has to track everyone hired
    # before it. ``people_names`` samples without replacement *within one
    # call*, so a second hire in the same run draws its own independent
    # sample and cannot be made to exclude the first without threading the
    # whole roster through this pure function. The pools are wide relative to
    # how many people any one scenario hires, so a collision is not a
    # practical risk; nothing in this corpus asserts person names are unique.
    [person_name] = names.people_names(rng.derive("name"), 1)

    person_id = minter.next("PERSON")
    person = Employee(
        id=person_id,
        name=person_name,
        title=title,
        joined=at,
        manager_id=manager_id,
        business_unit_id=business_unit_id,
        function=function,
        cost_centre_id=cost_centre_id,
        persona_id=persona_id,
    )

    event = EnterpriseEvent(
        id=minter.next("EV"),
        kind="person_hired",
        occurred_at=at,
        summary=f"{person.name} joined as {title}.",
        actors=[person_id],
        business_units=[business_unit_id] if business_unit_id else [],
    )

    fact = CanonicalFact(
        id=minter.next("FACT"),
        kind="org.joined",
        subject=person_id,
        period=period,
        text_value=f"{title}, {function}",
        valid_from=at,
        authority=Authority.SYSTEM_OF_RECORD,
        event_id=event.id,
    )

    return OrgChange(events=(event,), facts=(fact,), people=(person,))


def depart(
    rng: Rng,
    minter: Minter,
    *,
    person: Employee,
    successor: Employee,
    roles: dict[str, str],
    units: tuple[BusinessUnit, ...],
    at: datetime,
    period: str,
) -> OrgChange:
    """*person* leaves at *at*; *successor* takes over every post they held.

    The same ``Employee`` id comes back with ``left`` set — never a second
    record — because a person who leaves is still the one person who was
    here, and their name has to keep meaning the same thing in every earlier
    document that mentions them.
    """
    del rng  # nothing here needs a draw: the caller has already chosen who succeeds

    # The single easiest way to hand this feature an incoherent world: the
    # successor has to already be on the roster at the moment they take over,
    # or `leader_not_yet_employed` / `author_already_departed` will catch it
    # downstream on whatever they sign first. Failing loudly here, with both
    # ids and the moment named, is cheaper to debug than failing quietly in
    # `validate()` two scenarios later.
    if not _employed_at(successor, at):
        raise ValueError(
            f"{successor.id} cannot succeed {person.id} at {at.isoformat()}: "
            f"not employed at that moment (joined={successor.joined}, left={successor.left})"
        )

    # `left` is exclusive, matching `World.org_at` and the `author_already_
    # departed` check: someone's last day is a day they worked, so `left`
    # names the first instant they are gone, not their last instant present.
    # Setting it to `at` rather than `at - epsilon` is what lets a departure
    # placed at a period boundary still credit that period's artifacts to
    # them — the whole point of the boundary-timing decision in `scenarios.py`.
    departed_person = person.model_copy(update={"left": at})

    # Sorted rather than trusted in caller order: `units` and `roles` both
    # come from world state that is deterministic but not obviously ordered
    # to a reader of this function, and a hand-over that is not stably
    # ordered would mint its facts in a different sequence on every replay.
    led_units = tuple(
        unit.model_copy(update={"leader_id": successor.id})
        for unit in sorted(units, key=lambda u: u.id)
        if unit.leader_id == person.id
    )
    rebound_roles = {
        role_key: successor.id
        for role_key, holder in sorted(roles.items())
        if holder == person.id
    }

    event = EnterpriseEvent(
        id=minter.next("EV"),
        kind="person_departed",
        occurred_at=at,
        summary=f"{person.name} departed; {successor.name} succeeds them.",
        actors=[person.id, successor.id],
        business_units=[unit.id for unit in led_units],
    )

    facts = [
        CanonicalFact(
            id=minter.next("FACT"),
            kind="org.departed",
            subject=person.id,
            period=period,
            text_value=f"succeeded by {successor.name}",
            valid_from=at,
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
        )
    ]
    for role_key, holder_id in sorted(rebound_roles.items()):
        facts.append(
            CanonicalFact(
                id=minter.next("FACT"),
                kind="org.role_changed",
                subject=holder_id,
                period=period,
                text_value=f"assumed the {role_key} role from {person.name}",
                valid_from=at,
                authority=Authority.SYSTEM_OF_RECORD,
                event_id=event.id,
            )
        )
    for unit in led_units:
        facts.append(
            CanonicalFact(
                id=minter.next("FACT"),
                kind="org.unit_leader_changed",
                subject=unit.id,
                period=period,
                text_value=f"leadership passed to {successor.name}",
                valid_from=at,
                authority=Authority.SYSTEM_OF_RECORD,
                event_id=event.id,
            )
        )

    return OrgChange(
        events=(event,),
        facts=tuple(facts),
        people=(departed_person,),
        business_units=led_units,
        roles=rebound_roles,
    )


def promote(
    rng: Rng,
    minter: Minter,
    *,
    person: Employee,
    title: str,
    role_key: str,
    units: tuple[BusinessUnit, ...],
    at: datetime,
    period: str,
) -> OrgChange:
    """*person* takes *title* and becomes leader of every unit in *units*.

    Reorganisation, not succession: nobody's ``left`` is touched, because
    nobody left — this is the verb for a unit changing hands on its own,
    which is a different shape of change from ``depart`` handing over posts
    on the way out.
    """
    del rng  # no draw needed: which unit and who leads it are the caller's decision

    if not _employed_at(person, at):
        raise ValueError(
            f"{person.id} cannot be promoted at {at.isoformat()}: "
            f"not employed at that moment (joined={person.joined}, left={person.left})"
        )

    # A business unit's leader has to belong to it (or to no unit at all) —
    # `graph`'s `leader_elsewhere` check enforces exactly this. Asserting it
    # here rather than letting the validator find it later keeps this verb to
    # the same standard as `depart`: it should not be possible to produce the
    # violation, not merely possible to catch it.
    for unit in units:
        if person.business_unit_id not in (None, unit.id):
            raise ValueError(
                f"{person.id} cannot lead {unit.id}: already assigned to {person.business_unit_id}"
            )

    update: dict[str, Any] = {"title": title}
    if len(units) == 1:
        # The common case — one unit, one new leader — is also the only case
        # where "which unit do they now belong to" has an unambiguous answer.
        # A multi-unit promotion leaves `business_unit_id` alone rather than
        # guessing among them.
        update["business_unit_id"] = units[0].id
    promoted = person.model_copy(update=update)

    changed_units = tuple(
        unit.model_copy(update={"leader_id": person.id})
        for unit in sorted(units, key=lambda u: u.id)
    )

    event = EnterpriseEvent(
        id=minter.next("EV"),
        kind="leadership_changed",
        occurred_at=at,
        summary=f"{person.name} became {title}.",
        actors=[person.id],
        business_units=[unit.id for unit in changed_units],
    )

    facts = [
        CanonicalFact(
            id=minter.next("FACT"),
            kind="org.role_changed",
            subject=person.id,
            period=period,
            text_value=f"became {title}",
            valid_from=at,
            authority=Authority.SYSTEM_OF_RECORD,
            event_id=event.id,
        )
    ]
    for unit in changed_units:
        facts.append(
            CanonicalFact(
                id=minter.next("FACT"),
                kind="org.unit_leader_changed",
                subject=unit.id,
                period=period,
                text_value=f"leadership passed to {person.name}",
                valid_from=at,
                authority=Authority.SYSTEM_OF_RECORD,
                event_id=event.id,
            )
        )

    return OrgChange(
        events=(event,),
        facts=tuple(facts),
        people=(promoted,),
        business_units=changed_units,
        roles={role_key: person.id},
    )


__all__ = ["OrgChange", "hire", "depart", "promote"]
