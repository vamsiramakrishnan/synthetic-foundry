from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from worldloom.connector_definition import (
    CONNECTOR_DEFINITION_SCHEMA,
    REFERENCE_CONNECTORS,
    ConnectorDefinition,
    builtin_connector_definitions,
    load_connector_definition,
)


def test_all_reference_connector_definitions_load() -> None:
    definitions = builtin_connector_definitions()

    assert tuple(definitions) == tuple(sorted(REFERENCE_CONNECTORS))
    assert {item.connector for item in definitions.values()} == set(REFERENCE_CONNECTORS)
    assert all(item.query_fields for item in definitions.values())
    assert all(item.tools for item in definitions.values())
    assert all(item.entities for item in definitions.values())


def test_definition_round_trips_stable_wire_schema() -> None:
    jira = load_connector_definition("jira")

    encoded = jira.wire_dict()

    assert encoded["schema"] == CONNECTOR_DEFINITION_SCHEMA
    assert "definition_schema" not in encoded
    assert ConnectorDefinition.model_validate(encoded) == jira


def test_entity_operations_resolve_to_declared_tools() -> None:
    definitions = builtin_connector_definitions()

    assert definitions["jira"].tool_for("bug", "transition") == "transition_issue"
    assert definitions["servicenow"].tool_for("incident", "comment") == "add_work_note"
    assert definitions["salesforce"].tool_for("task", "create") == "create_task"
    assert definitions["confluence"].tool_for("page", "create") == "create_page"
    assert definitions["sharepoint"].tool_for("docx", "transform") == "convert_file"
    assert definitions["drive"].tool_for("gslides", "create") == "create_slides"


def test_workflow_aliases_are_connector_data() -> None:
    jira = load_connector_definition("jira")
    workflow = jira.entities["bug"].workflow

    assert workflow is not None
    assert workflow.canonical_state("In Progress") == "open"
    assert workflow.transitions["open"] == ("review", "blocked", "done")


def test_unknown_tool_reference_is_rejected() -> None:
    jira = load_connector_definition("jira")
    broken = jira.wire_dict()
    broken["entities"] = dict(broken["entities"])
    bug = dict(broken["entities"]["bug"])
    bug["ops"] = {**bug["ops"], "read": "not_a_tool"}
    broken["entities"]["bug"] = bug

    with pytest.raises(ValidationError, match="unknown tools"):
        ConnectorDefinition.model_validate(broken)


def test_unknown_workflow_state_is_rejected() -> None:
    jira = load_connector_definition("jira")
    broken = json.loads(json.dumps(jira.wire_dict()))
    broken["entities"]["bug"]["workflow"]["transitions"]["open"].append("vanished")

    with pytest.raises(ValidationError, match="unknown states"):
        ConnectorDefinition.model_validate(broken)
