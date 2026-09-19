from __future__ import annotations

import itertools

import pytest

from worldloom.enterprise_dag import default_shapes
from worldloom.enterprise_queries import (
    _subsets,
    constrained_cover,
    plan_queries,
    required_interactions,
    valid_rows,
)
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
from worldloom.world import World


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


#: Two connectors, one workflow, three failures chosen so that every
#: admissibility rule prunes something: 5,760 valid rows, 35,840 with the
#: default DAG shapes. Small enough to enumerate in a test, large enough that
#: a derived set which merely resembled the truth would be caught.
def _small_profile() -> ScenarioProfile:
    return ScenarioProfile.model_validate({
        "name": "small",
        "industry": "retail",
        "company_description": "Retail service operations.",
        "connectors": ["servicenow", "confluence"],
        "workflows": ["incident_review"],
        "coverage": {
            "name": "small", "connector_counts": [1],
            "failures": ["none", "missing_stable_id", "version_conflict"],
            "max_candidates": 1_000_000,
        },
    })


@pytest.mark.parametrize("strength", [2, 3])
@pytest.mark.parametrize("shapes", [(), default_shapes()])
def test_required_interactions_are_derived_exactly(strength: int, shapes: tuple[str, ...]) -> None:
    """The set the cover stops at is the set enumeration would find.

    The derivation never looks at a row, so the only proof that it agrees
    with the stream is to enumerate the stream and compare. The DAG shape
    path is checked too: a shape is decided per row, and the derivation
    decides it from a stub row instead.
    """
    from worldloom.enterprise_dag_planning import compatible_shapes

    profile = _small_profile()
    registry = apply_scenario_profile(builtin_registry(), profile)
    rows = list(valid_rows(registry, profile.coverage))
    if shapes:
        rows = [{**row, "dag_shape": shape} for row in rows for shape in compatible_shapes(row, shapes)]
    enumerated = {interaction for row in rows for interaction in _subsets(row, strength)}
    assert required_interactions(registry, profile.coverage, strength, shapes) == enumerated


def test_a_limit_yields_the_prefix_of_the_unlimited_walk_and_says_so() -> None:
    """`--limit 40` on the default profile ran for fifteen minutes and wrote
    nothing, because the cap was applied to the cover's output after the walk
    had scanned millions of candidates. The cap now stops the walk, and the
    report admits what the selection has not proved."""
    world = World.load("examples/retail-close")
    profile = _small_profile()
    registry = apply_scenario_profile(builtin_registry(), profile)
    unlimited, full = plan_queries(world, registry=registry, profile=profile.coverage)
    limited, report = plan_queries(world, registry=registry, profile=profile.coverage, limit=5)
    assert [query.id for query in limited] == [query.id for query in unlimited][:5]
    assert full.complete and not full.truncated and full.exact and full.holes == ()
    assert report.truncated and report.exact and not report.complete
    assert report.candidates < full.candidates
    assert report.covered_interactions < report.required_interactions == full.required_interactions
    assert len(report.holes) == report.required_interactions - report.covered_interactions


def test_a_cover_without_the_required_set_does_not_claim_what_it_cannot_prove() -> None:
    rows = (
        {"a": "1", "b": "1", "c": "1"},
        {"a": "1", "b": "2", "c": "2"},
        {"a": "2", "b": "1", "c": "2"},
        {"a": "2", "b": "2", "c": "1"},
    )
    _, exhausted = constrained_cover(rows, 2)
    assert exhausted.exact and exhausted.complete and not exhausted.truncated

    selected, cut = constrained_cover(rows, 2, limit=1)
    assert len(selected) == 1
    assert cut.truncated and not cut.exact and not cut.complete
    assert cut.required_interactions == cut.covered_interactions  # a lower bound, and labelled as one

    _, sliced = constrained_cover(rows, 2, partial=True)
    assert not sliced.truncated and not sliced.exact and not sliced.complete

    required = {interaction for row in rows for interaction in _subsets(row, 2)}
    _, proven = constrained_cover(rows, 2, limit=1, required=required)
    assert proven.truncated and proven.exact and not proven.complete
    assert set(proven.holes) == required - _subsets(rows[0], 2)
    with pytest.raises(ValueError, match="outside the derived required set"):
        constrained_cover(rows, 2, required=set(itertools.islice(required, 3)))


def test_shards_cover_their_own_slices_and_their_union_covers_the_space() -> None:
    """Sharding splits the candidate stream, not the cover's output, so each
    shard is an independent walk. The trade is stated by the report: a shard's
    holes are relative to the whole space, and the union of the shards'
    selections is complete because the union of their slices is the space."""
    world = World.load("examples/retail-close")
    profile = _small_profile()
    registry = apply_scenario_profile(builtin_registry(), profile)
    required = required_interactions(registry, profile.coverage, 2)
    shards = [
        plan_queries(world, registry=registry, profile=profile.coverage, shard_index=index, shard_count=3)
        for index in range(3)
    ]
    union: set[tuple[tuple[str, str], ...]] = set()
    for queries, report in shards:
        covered = {interaction for query in queries for interaction in _subsets(query.dimensions, 2)}
        assert report.exact
        assert len(covered) == report.covered_interactions
        assert set(report.holes) == required - covered
        union |= covered
    assert union == required
    ids = [query.id for queries, _ in shards for query in queries]
    assert len(ids) == len(set(ids))


def test_plans_are_the_same_from_one_run_to_the_next() -> None:
    world = World.load("examples/retail-close")
    profile = _small_profile()
    registry = apply_scenario_profile(builtin_registry(), profile)
    first, first_report = plan_queries(world, registry=registry, profile=profile.coverage, limit=7)
    second, second_report = plan_queries(world, registry=registry, profile=profile.coverage, limit=7)
    assert [query.model_dump_json() for query in first] == [query.model_dump_json() for query in second]
    assert first_report == second_report
