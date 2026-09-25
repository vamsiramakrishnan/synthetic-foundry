"""Materialize authored support ownership without allocating trading revenue.

The process catalogue names accountable groups, while vertical organisation
builders usually create revenue divisions. This recipe step makes the declared
support groups real World entities. It reuses existing company leaders and
records that accountability explicitly rather than inventing employees or
silently making an operating division responsible for another group's work.
"""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from ..models import BusinessUnit, EnterpriseEvent
from ..recipe import register_step, with_step
from .models import SUPPORT_ARCHETYPES, CompanySpec

if TYPE_CHECKING:
    from ..world import World


def materialize_owners(world: World, structure: CompanySpec, *,
                       leader_roles: dict[str, str] | None = None,
                       formed_at: datetime | None = None) -> World:
    """Create named support units, with existing CEO accountability by default.

    The default is a declared construction policy, retained as concrete role
    bindings in the recipe and formation event. It is not an inferred claim
    that the interview identified a dedicated department head. Callers may
    supply existing group-level roles for more specific accountability.
    """
    if structure.name != world.company.name:
        raise ValueError("process ownership structure names a different company")
    authored = {unit.name: unit for unit in structure.bus if unit.archetype in SUPPORT_ARCHETYPES}
    if leader_roles is not None and set(leader_roles) - authored.keys():
        raise ValueError("support leadership names a group outside the declared structure")
    leaders = {name: (leader_roles or {}).get(name, "ceo") for name in sorted(authored)}
    existing = {unit.name: unit for unit in world.business_units}
    if len(existing) != len(world.business_units):
        raise ValueError("support ownership requires unambiguous company business-unit names")
    if not authored:
        return world
    if world._minter is None:
        raise ValueError("support ownership needs restored generation state before materialization")
    events = tuple(world.events)
    if formed_at is None:
        joined = [person.joined for person in world.people if person.joined is not None]
        if events:
            formed_at = max(event.occurred_at for event in events) + timedelta(hours=1)
        elif joined:
            # A world with people and no events yet (a company built without
            # an episode, as a catalogue-derived project is): the support
            # units form an hour after the last person joined, so every
            # leader has joined at formation and nothing is dated before the
            # organisation it belongs to.
            formed_at = max(joined) + timedelta(hours=1)
        else:
            raise ValueError("support ownership needs a company event timeline, people with join dates, or explicit formed_at")
    from ..recipe import process_structure_of

    # A world built from this very structure (a catalogue project: the
    # company's units are the declared ones, `industry.divisions`) already
    # holds every support unit, led as its pack seats it. Nothing to form.
    built_from = process_structure_of(world.recipe) == structure
    resolved: dict[str, str] = {}
    for name, role in leaders.items():
        if built_from and name in existing:
            resolved[name] = existing[name].leader_id
            continue
        identifier = world._roles.get(role)
        person = next((person for person in world.people if person.id == identifier), None)
        if person is None:
            raise ValueError(f"support group {name!r} needs an existing leader role {role!r}")
        if person.business_unit_id not in (None, existing[name].id if name in existing else None):
            raise ValueError(f"support leader {role!r} already belongs to another business unit")
        if person.joined is not None and person.joined > formed_at:
            raise ValueError(f"support leader {role!r} has not joined at formation")
        if person.left is not None and person.left <= formed_at:
            raise ValueError(f"support leader {role!r} has left before formation")
        resolved[name] = person.id
        if name in existing and (existing[name].kind != "support" or existing[name].leader_id != person.id):
            raise ValueError(f"support group {name!r} conflicts with an existing business unit or its leadership")
    missing = sorted(authored.keys() - existing.keys())
    if not missing:
        return world
    # Validation must not consume another branch's sequential IDs, including
    # the no-op/rejected paths callers use while reviewing a company revision.
    minter = deepcopy(world._minter)
    additions = tuple(BusinessUnit(id=minter.next("BU"), name=name, company_id=world.company.id,
                                   leader_id=resolved[name], kind="support", formed=formed_at)
                      for name in missing)
    event = EnterpriseEvent(id=minter.next("EV"), kind="organisation.support_ownership",
        occurred_at=formed_at, actors=sorted(set(resolved[name] for name in missing)),
        business_units=[unit.id for unit in additions],
        summary=json.dumps({"schema": "worldloom.support-ownership/v1", "company_id": world.company.id,
            "units": [{"id": unit.id, "name": unit.name, "archetype": authored[unit.name].archetype,
                       "leader_role": leaders[unit.name], "leader_id": unit.leader_id,
                       "countries": list(authored[unit.name].countries)} for unit in additions],
            "financial_allocation": "none", "leadership_policy": "explicit_existing_role"},
            sort_keys=True, separators=(",", ":")))
    changed = replace(world, _minter=minter).extend(business_units=additions, events=(event,),
        recipe=with_step(world.recipe, "MaterializeProcessOwners", structure=structure.model_dump(mode="json"),
                         leader_roles=leaders, formed_at=formed_at.isoformat()))
    changed.validate().raise_if_failed()
    return changed


@dataclass(frozen=True)
class MaterializeProcessOwners:
    structure: dict[str, Any]
    leader_roles: dict[str, str]
    formed_at: str
    physics: Any = None

    def run(self, world: World) -> World:
        return materialize_owners(world, CompanySpec.model_validate(self.structure),
                                  leader_roles=self.leader_roles,
                                  formed_at=datetime.fromisoformat(self.formed_at))


register_step("MaterializeProcessOwners", ("structure", "leader_roles", "formed_at"), MaterializeProcessOwners)

__all__ = ["materialize_owners", "MaterializeProcessOwners"]
