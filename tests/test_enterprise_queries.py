from __future__ import annotations

import itertools

from worldloom.enterprise_queries import constrained_cover, valid_rows
from worldloom.enterprise_specs import (
    CoverageProfile,
    EnterpriseEvalSpec,
    ScenarioProfile,
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
