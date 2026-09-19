from __future__ import annotations

import itertools

import pytest

from worldloom import enterprise_queries
from worldloom.connector_definition import builtin_connector_definitions
from worldloom.enterprise_queries import (
    _connector_label,
    _render,
    constrained_cover,
    plan_queries,
    valid_rows,
)
from worldloom.enterprise_specs import (
    BUILTIN_CONNECTORS,
    ContentAction,
    CoverageProfile,
    DestinationRole,
    EnterpriseEvalSpec,
    Operation,
    ScenarioProfile,
    SourceRole,
    SpecRegistry,
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


# The connector definitions carried fourteen connectors while the planner's
# registry carried eight, hand-written and never compared. A scenario profile
# naming `slack` was refused as unknown while the emulator stood ready to
# serve it. The tests below hold the two catalogues to each other by name,
# entity and operation, so the next definition added without a spec fails
# here and not in a user's profile.

#: The eight specs written before the definitions existed carry `patch`,
#: `upsert`, `attach` and `link`, which no definition maps to a tool. They are
#: kept because planned rows already name them; a spec added after the
#: definitions may not take them.
ORIGINAL_CONNECTORS = frozenset({"jira", "confluence", "sharepoint", "drive", "servicenow", "salesforce", "email", "sor"})
LEGACY_OPERATIONS = frozenset({Operation.PATCH, Operation.UPSERT, Operation.ATTACH, Operation.LINK})

#: Which definition operation keys carry each spec operation. `list` is the
#: definition's `search` where the product's search is a listing call, and a
#: `draft` is the definition's `draft` or a `create` that makes a draft.
GROUNDING = {
    Operation.SEARCH: {"search"},
    Operation.LIST: {"search"},
    Operation.READ: {"read"},
    Operation.CREATE: {"create"},
    Operation.UPDATE: {"update"},
    Operation.DELETE: {"delete"},
    Operation.MOVE: {"move"},
    Operation.COMMENT: {"comment"},
    Operation.DRAFT: {"draft", "create"},
    Operation.SEND: {"send"},
    Operation.REPLY: {"reply"},
    Operation.FORWARD: {"forward"},
}


def test_every_connector_definition_has_a_planner_spec() -> None:
    registry = builtin_registry()

    assert set(registry.connectors) == set(builtin_connector_definitions())
    assert registry.review() == ()
    # The order is the tuple's, so a dump of the built-in spec is stable.
    assert list(registry.connectors) == [spec.name for spec in BUILTIN_CONNECTORS]


def test_spec_entities_and_operations_are_carried_by_their_definitions() -> None:
    definitions = builtin_connector_definitions()
    for name, spec in builtin_registry().connectors.items():
        definition = definitions[name]
        for entity in spec.entities:
            # An alias such as jira's `issue` resolves to its members; a name
            # the definition does not know raises here.
            members = definition.entity_members(entity.name)
            carried = {op for member in members for op in definition.entities[member].ops}
            for operation in entity.operations:
                if operation in LEGACY_OPERATIONS:
                    assert name in ORIGINAL_CONNECTORS, f"{name}.{entity.name} carries {operation.value}, which no definition maps to a tool"
                    continue
                assert GROUNDING[operation] & carried, f"{name}.{entity.name} spec operation {operation.value} is not in the definition's {sorted(carried)}"
            if name == "onedrive":
                # The definition types the drive item per format, so the
                # spec's formats are entity names there, not free labels.
                assert set(entity.formats) <= set(definition.entities)


def test_render_reads_the_display_name_from_the_spec() -> None:
    registry = builtin_registry()
    workflow = WorkflowSpec(
        name="chat_digest", purpose="channel digest",
        sources=(SourceRole(connector="slack", entities=("thread",)), SourceRole(connector="teamwork_graph", entities=("work_item",))),
        destinations=(DestinationRole(connector="teams", entities=("channel_message",), operations=(Operation.CREATE,)),),
        content_actions=(ContentAction.SUMMARIZE,), audiences=("manager",),
        prompt_template="Use {sources}. {action_instruction} {output_label} in {destination}.{failure_instruction}",
    )
    row = {
        "workflow": "chat_digest", "source_set": "slack+teamwork_graph", "source_entities": "slack:thread+teamwork_graph:work_item",
        "input_formats": "record+record", "destination": "teams", "destination_entity": "channel_message", "operation": "create",
        "output_format": "record", "content_action": "summarize", "audience": "manager", "topology": "chain", "failure": "none", "verification": "readback",
    }

    text = _render(World.load("examples/retail-close"), workflow, row, registry)

    assert "the relevant Slack thread" in text
    assert "the relevant Teamwork Graph work item" in text
    assert "in Microsoft Teams." in text


def _legacy_source_label(name: str) -> str:
    return name.replace("servicenow", "ServiceNow").replace("sharepoint", "SharePoint").replace("jira", "Jira").replace("salesforce", "Salesforce").replace("confluence", "Confluence").replace("drive", "Drive").replace("email", "email")


def _legacy_destination_label(name: str) -> str:
    return name.replace("servicenow", "ServiceNow").replace("sharepoint", "SharePoint").title()


def test_the_original_eight_keep_the_labels_their_rows_were_rendered_with() -> None:
    """The replace chain and `.title()` the renderer used are the oracle here,
    reproduced verbatim, so a spec's `display_name` can be corrected without
    moving the text of a row that already exists."""
    registry = builtin_registry()
    for name in sorted(ORIGINAL_CONNECTORS):
        assert _connector_label(registry, name, role="source") == _legacy_source_label(name)
        assert _connector_label(registry, name, role="destination") == _legacy_destination_label(name)


def test_narrowed_profile_plans_byte_identically(monkeypatch: pytest.MonkeyPatch) -> None:
    """The same narrowed profile, planned with the spec's labels and with the
    old chain swapped back in, must write the same bytes."""
    profile = ScenarioProfile(
        name="narrow", industry="retail", company_description="An omnichannel retailer.",
        workflows=("executive_digest",), connectors=("jira", "confluence", "email"),
        coverage=CoverageProfile(name="narrow", strengths=2, connector_counts=(1, 2), failures=("none", "permission_denied")),
    )
    world = World.load("examples/retail-close")
    registry = apply_scenario_profile(builtin_registry(), profile)

    queries, _ = plan_queries(world, registry=registry, profile=profile.coverage)
    current = [query.model_dump_json() for query in queries]

    def legacy(registry: SpecRegistry, name: str, *, role: str) -> str:
        return _legacy_source_label(name) if role == "source" else _legacy_destination_label(name)

    monkeypatch.setattr(enterprise_queries, "_connector_label", legacy)
    queries, _ = plan_queries(world, registry=registry, profile=profile.coverage)
    assert current == [query.model_dump_json() for query in queries]
    assert len(current) > 100


def test_every_write_operation_can_be_phrased() -> None:
    """`review()` accepts any operation an entity declares; `_render` must phrase it.

    Found by the back-office scenario: a destination saying `comment` passed
    the lint and raised `KeyError` at plan time. The read operations are
    sources, never destinations, so they are the only members left out.
    """
    from worldloom.enterprise_queries import ACTION_INSTRUCTIONS
    from worldloom.enterprise_specs import Operation

    reads = {Operation.SEARCH.value, Operation.LIST.value, Operation.READ.value}
    writes = {member.value for member in Operation} - reads
    assert writes <= set(ACTION_INSTRUCTIONS), sorted(writes - set(ACTION_INSTRUCTIONS))
    assert all(text and text[0].isupper() for text in ACTION_INSTRUCTIONS.values())
