"""Every shipped scenario profile loads, merges, and names only what the registry holds.

`examples/enterprise-evals/*.json` are the profiles an operator points
`worldloom enterprise-evals space|plan|build --profile` at. Nothing loaded
them before this file: a profile could name a connector entity that no spec
carries, or a workflow that no registry holds, and the first person to find
out would be the operator, at plan time, as a refusal. The checks here are
the ones `apply_scenario_profile` and `registry.review()` make, run over the
shipped files so that a typo in an example is a failing test rather than a
support question.

Planning cost is deliberately not measured here.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path

import pytest

from worldloom.enterprise_queries import valid_rows
from worldloom.enterprise_specs import (
    BUILTIN_CONNECTORS,
    ScenarioProfile,
    SpecRegistry,
    apply_scenario_profile,
    builtin_registry,
)

ROOT = Path(__file__).resolve().parents[1]
PROFILES = sorted((ROOT / "examples" / "enterprise-evals").glob("*.json"))

#: The placeholders `enterprise_queries._render` fills. A template naming any
#: other placeholder raises `KeyError` at plan time, after the profile has
#: loaded and reviewed cleanly, so the loader cannot catch it.
TEMPLATE_PLACEHOLDERS = (
    "period", "purpose", "company", "audience", "sources", "action_instruction",
    "output_label", "destination", "verification_instruction", "failure_instruction",
)

#: Destination operations the planner can phrase. `Operation.COMMENT` and the
#: like are legal on an entity and pass `review()`, but `_render` has no
#: instruction for them and raises at plan time.
RENDERABLE_OPERATIONS = frozenset({"create", "update", "patch", "upsert", "draft", "send", "reply"})


def _profile(path: Path) -> ScenarioProfile:
    return ScenarioProfile.model_validate_json(path.read_text(encoding="utf-8"))


def _merged(profile: ScenarioProfile) -> SpecRegistry:
    """Builtin plus the profile's additions, before the connector selection filters roles."""
    base = builtin_registry()
    return SpecRegistry(
        (*base.connectors.values(), *profile.additional_connectors),
        (*base.workflows.values(), *profile.additional_workflows),
        (*base.processes.values(), *profile.additional_processes),
    )


def test_there_are_shipped_profiles() -> None:
    """A glob that matched nothing would pass every parametrized test for free."""
    assert len(PROFILES) >= 4
    assert ROOT / "examples" / "enterprise-evals" / "back-office.json" in PROFILES


@pytest.mark.parametrize("path", PROFILES, ids=lambda path: path.name)
def test_profile_loads_merges_and_reviews_clean(path: Path) -> None:
    profile = _profile(path)
    selected = apply_scenario_profile(builtin_registry(), profile)
    assert selected.review() == ()
    assert selected.workflows, path.name
    # The profile says which connectors it selects; the selection must not be
    # a superset of what the registry holds, and every selected one survives.
    assert set(profile.connectors) <= set(_merged(profile).connectors)
    if profile.connectors:
        assert set(selected.connectors) == set(profile.connectors)


@pytest.mark.parametrize("path", PROFILES, ids=lambda path: path.name)
def test_every_named_workflow_exists_and_survives_selection(path: Path) -> None:
    profile = _profile(path)
    merged = _merged(profile)
    selected = apply_scenario_profile(builtin_registry(), profile)
    for name in profile.workflows:
        assert name in merged.workflows, f"{path.name} names unknown workflow {name!r}"
        assert name in selected.workflows, f"{path.name}: workflow {name!r} lost every source or destination to the connector selection"
    for workflow in profile.additional_workflows:
        assert workflow.name in selected.workflows, f"{path.name}: authored workflow {workflow.name!r} is not selected"


@pytest.mark.parametrize("path", PROFILES, ids=lambda path: path.name)
def test_every_role_names_a_connector_and_entity_the_registry_carries(path: Path) -> None:
    profile = _profile(path)
    merged = _merged(profile)
    # The authored roles are checked against the merged registry, not the
    # selected one: `apply_scenario_profile` drops a role whose connector is
    # outside the selection, so a misspelt connector would vanish silently.
    for workflow in profile.additional_workflows:
        for role in (*workflow.sources, *workflow.destinations):
            assert role.connector in merged.connectors, f"{workflow.name}: unknown connector {role.connector!r}"
            connector = merged.connectors[role.connector]
            for entity in role.entities:
                spec = connector.entity(entity)
                unsupported = set(role.operations) - set(spec.operations)
                assert not unsupported, f"{workflow.name}: {role.connector}.{entity} cannot {sorted(unsupported)}"
        for destination in workflow.destinations:
            unrenderable = {op.value for op in destination.operations} - RENDERABLE_OPERATIONS
            assert not unrenderable, f"{workflow.name}: planner cannot phrase {sorted(unrenderable)}"
            for entity in destination.entities:
                spec = merged.connectors[destination.connector].entity(entity)
                if spec.formats:
                    assert set(destination.formats) <= set(spec.formats), f"{workflow.name}: {destination.connector}.{entity} formats"
    for process in profile.additional_processes:
        for connector, entity in process.connector_entities.items():
            assert connector in merged.connectors, f"process {process.name}: unknown connector {connector!r}"
            merged.connectors[connector].entity(entity)


@pytest.mark.parametrize("path", PROFILES, ids=lambda path: path.name)
def test_prompt_templates_use_only_the_planner_placeholders(path: Path) -> None:
    profile = _profile(path)
    selected = apply_scenario_profile(builtin_registry(), profile)
    blanks = dict.fromkeys(TEMPLATE_PLACEHOLDERS, "")
    for workflow in selected.workflows.values():
        try:
            workflow.prompt_template.format(**blanks)
        except (KeyError, IndexError, ValueError) as error:
            pytest.fail(f"{path.name}: {workflow.name} template: {error!r}")


@pytest.mark.parametrize("path", PROFILES, ids=lambda path: path.name)
def test_a_bounded_prefix_reaches_every_selected_workflow(path: Path) -> None:
    profile = _profile(path)
    selected = apply_scenario_profile(builtin_registry(), profile)
    rows = tuple(itertools.islice(valid_rows(selected, profile.coverage), 2_000))
    assert {row["workflow"] for row in rows} == set(selected.workflows)
    for row in rows:
        workflow = selected.workflows[row["workflow"]]
        assert row["destination"] in {role.connector for role in workflow.destinations}
        assert set(row["source_set"].split("+")) <= {role.connector for role in workflow.sources}


def test_profiles_are_additive_over_the_builtin_registry() -> None:
    """A shipped profile must not redefine a builtin workflow or connector: a
    plan made without a profile has to stay byte-identical."""
    builtin_workflows = set(builtin_registry().workflows)
    builtin_connectors = {item.name for item in BUILTIN_CONNECTORS}
    for path in PROFILES:
        profile = _profile(path)
        overridden = {item.name for item in profile.additional_workflows} & builtin_workflows
        assert not overridden, f"{path.name} redefines builtin workflows {sorted(overridden)}"
        overridden = {item.name for item in profile.additional_connectors} & builtin_connectors
        assert not overridden, f"{path.name} redefines builtin connectors {sorted(overridden)}"


def test_back_office_widens_the_axes_and_grounds_on_bound_record_kinds() -> None:
    """The back-office profile exists to stress agents on close, match,
    onboarding and renewal work rather than ticket triage. Its workflows must
    together use every topology, add content actions and output formats the
    builtin workflows never emit, and read `sor` entities a catalogue company
    actually binds: `employee` and `vendor_bill` are connector entities, but
    no industry's default company holds records of them, so a row over them
    materializes evidence carrying no fact and is refused at validation."""
    from worldloom.process_bindings import compile_company, default_company
    from worldloom.process_bindings.compiler import resource
    from worldloom.sor import entity_name

    path = ROOT / "examples" / "enterprise-evals" / "back-office.json"
    profile = _profile(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["connectors"] == ["jira", "confluence", "sharepoint", "drive", "servicenow", "salesforce", "email", "sor"]
    assert profile.coverage.name == "back-office-pairwise"
    names = {workflow.name for workflow in profile.additional_workflows}
    assert {"finance_month_end_close", "procurement_exception_review", "hr_onboarding_readiness", "contract_renewal_review"} <= names

    topologies = {topology for workflow in profile.additional_workflows for topology in workflow.topologies}
    assert topologies == {"chain", "fan_in", "fan_out", "diamond"}
    builtin = builtin_registry().workflows.values()
    builtin_actions = {action.value for workflow in builtin for action in workflow.content_actions}
    authored_actions = {action.value for workflow in profile.additional_workflows for action in workflow.content_actions}
    assert authored_actions - builtin_actions >= {"classify", "transform"}
    builtin_formats = {fmt for workflow in builtin for role in workflow.destinations for fmt in role.formats}
    authored_formats = {fmt for workflow in profile.additional_workflows for role in workflow.destinations for fmt in role.formats}
    assert "csv" in authored_formats - builtin_formats
    assert any(role.connector == "sor" for workflow in profile.additional_workflows for role in workflow.destinations)

    # The industries `default_company` accepts, read from the same table it reads.
    bound: set[str] = set()
    for industry in sorted(resource("defaults.json")["DEFAULT_ORGS"]):
        compiled = compile_company(default_company(industry))
        bound |= {entity_name(kind) for row in compiled.rows for kind in row.sor_objects}
    for workflow in profile.additional_workflows:
        for role in workflow.sources:
            if role.connector == "sor":
                unbound = set(role.entities) - bound
                assert not unbound, f"{workflow.name}: no catalogue company binds sor {sorted(unbound)}"
