from __future__ import annotations

import itertools

from worldloom.enterprise_queries import constrained_cover, valid_rows
from worldloom.enterprise_specs import (
    ContentAction,
    CoverageProfile,
    DestinationRole,
    EnterpriseEvalSpec,
    Operation,
    ScenarioProfile,
    SourceRole,
    WorkflowSpec,
    apply_scenario_profile,
    builtin_registry,
    builtin_spec,
    canonical_action,
    load_enterprise_spec,
)


def test_modify_is_explicitly_canonicalized() -> None:
    assert canonical_action("modify") == "update"
    assert canonical_action("modify", content=True) == "transform"


def test_valid_rows_respect_workflow_connector_contracts() -> None:
    rows = list(itertools.islice(valid_rows(builtin_registry(), CoverageProfile()), 1_000))
    assert rows
    for row in rows:
        workflow = builtin_registry().workflows[row["workflow"]]
        assert row["destination"] in {destination.connector for destination in workflow.destinations}
        assert set(row["source_set"].split("+")) <= {source.connector for source in workflow.sources}


def test_constrained_cover_proves_coverage_over_valid_rows() -> None:
    rows = (
        {"a": "1", "b": "1", "c": "1"},
        {"a": "1", "b": "2", "c": "2"},
        {"a": "2", "b": "1", "c": "2"},
        {"a": "2", "b": "2", "c": "1"},
    )
    selected, report = constrained_cover(rows, 2)
    assert selected
    assert report.complete
    assert report.covered_interactions == report.required_interactions


def test_builtin_spec_round_trips_through_authoring_loader() -> None:
    original = builtin_spec()
    loaded = load_enterprise_spec(original.model_dump(mode="json"))
    assert isinstance(loaded, EnterpriseEvalSpec)
    assert loaded == original


def test_scenario_profile_filters_registry() -> None:
    profile = ScenarioProfile(
        name="service-desk",
        industry="technology",
        company_description="A managed technology provider.",
        workflows=("incident_review",),
        connectors=("jira", "servicenow", "email"),
    )
    selected = apply_scenario_profile(builtin_registry(), profile)
    assert set(selected.workflows) == {"incident_review"}
    assert set(selected.connectors) == {"jira", "servicenow", "email"}


def test_scenario_profile_can_author_an_industry_workflow() -> None:
    retail = WorkflowSpec(
        name="merchandising_review",
        purpose="category and inventory performance review",
        process="retail_merchandising",
        sources=(SourceRole(connector="sharepoint", entities=("file",)),),
        destinations=(
            DestinationRole(
                connector="drive",
                entities=("file",),
                operations=(Operation.CREATE,),
                formats=("xlsx",),
            ),
        ),
        content_actions=(ContentAction.RECONCILE, ContentAction.GENERATE),
        audiences=("category_manager",),
        prompt_template=(
            "Prepare {purpose} for {company}. Use {sources}. "
            "{action_instruction} {output_label} in {destination}, then "
            "{verification_instruction}.{failure_instruction}"
        ),
    )
    profile = ScenarioProfile(
        name="retailer",
        industry="retail",
        company_description="An omnichannel retailer.",
        workflows=("merchandising_review",),
        connectors=("sharepoint", "drive"),
        additional_workflows=(retail,),
    )

    selected = apply_scenario_profile(builtin_registry(), profile)

    assert selected.workflows["merchandising_review"].process == "retail_merchandising"


def test_bounded_prefix_is_balanced_across_major_dimensions() -> None:
    profile = CoverageProfile()
    rows = tuple(itertools.islice(valid_rows(builtin_registry(), profile), 1000))

    assert {row["workflow"] for row in rows} == set(builtin_registry().workflows)
    assert {row["failure"] for row in rows} == set(profile.failures)
    assert {row["topology"] for row in rows} == {
        "chain",
        "fan_in",
        "fan_out",
        "diamond",
    }
    assert {row["verification"] for row in rows} == {"readback", "cross_system"}
