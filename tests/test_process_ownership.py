from __future__ import annotations

import json
from dataclasses import replace

import pytest

from worldloom.evals.dataset import _files
from worldloom.process_bindings import BusinessUnit, CompanySpec, materialize_owners
from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


@pytest.fixture(scope="module")
def company():
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    structure = CompanySpec(name=world.company.name, industry="retail", operating_model="centralised",
        countries=("AU",), bus=(BusinessUnit(name="Supply Chain", archetype="group_function"),
                                BusinessUnit(name="Finance", archetype="shared_service_centre")))
    return world, structure


def test_support_ownership_is_real_replayable_and_has_no_financial_allocation(company, tmp_path):
    world, structure = company
    counters = dict(world._minter._counters)
    result = materialize_owners(world, structure)
    assert result.company == world.company
    assert tuple(result.facts) == tuple(world.facts)
    assert tuple(result.categories) == tuple(world.categories)
    assert tuple(result.people) == tuple(world.people)
    assert tuple(result.sites) == tuple(world.sites)
    assert world._minter._counters == counters
    additions = tuple(result.business_units)[len(world.business_units):]
    assert [unit.name for unit in additions] == ["Finance", "Supply Chain"]
    assert all(unit.kind == "support" and unit.leader_id == world._roles["ceo"] for unit in additions)
    event = tuple(result.events)[-1]
    assert event.business_units == [unit.id for unit in additions]
    assert json.loads(event.summary)["financial_allocation"] == "none"
    assert result.recipe["steps"][-1]["leader_roles"] == {"Finance": "ceo", "Supply Chain": "ceo"}
    result.validate().raise_if_failed()
    result.export(tmp_path / "owned")
    rebuild(result.recipe).export(tmp_path / "replayed")
    assert _files(tmp_path / "owned") == _files(tmp_path / "replayed")
    assert materialize_owners(result, structure) is result


def test_support_ownership_refuses_unknown_or_misassigned_leadership(company):
    world, structure = company
    with pytest.raises(ValueError, match="existing leader role"):
        materialize_owners(world, structure, leader_roles={"Supply Chain": "invented_department_head"})
    assigned = next(role for role, identifier in world._roles.items()
                    if any(person.id == identifier and person.business_unit_id for person in world.people))
    with pytest.raises(ValueError, match="already belongs to another"):
        materialize_owners(world, structure, leader_roles={"Supply Chain": assigned})
    with pytest.raises(ValueError, match="outside the declared structure"):
        materialize_owners(world, structure, leader_roles={"Undeclared": "ceo"})


def test_operating_units_cannot_be_relabelled_as_support_and_cached_state_is_required(company):
    world, structure = company
    conflicting = structure.model_copy(update={"bus": (BusinessUnit(name=world.business_units[0].name,
                                                                     archetype="group_function"),)})
    with pytest.raises(ValueError, match="conflicts with an existing business unit"):
        materialize_owners(world, conflicting)
    with pytest.raises(ValueError, match="restored generation state"):
        materialize_owners(replace(world, _minter=None), structure)
