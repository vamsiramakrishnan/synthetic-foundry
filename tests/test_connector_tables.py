"""The connector tables are derived from the connector definitions, and equal the literals they replaced.

`connector_data.CAPABILITIES` and `enterprise_specs.BUILTIN_CONNECTORS` were
literal tables kept beside `_data/connectors/*.json`, and they disagreed with
it (``Jira`` against ``Jira Cloud``, ``issue`` against the issue types, ``key``
against ``ident``). Each disagreement is now a field of the definition's
``catalog``, and both tables are derived from it. The literals below are the
tables as they stood when they were deleted, verbatim: a derived table that
differs from them by one verb, one entity or one position changes every
planned query row and every corpus's connector dataset.
"""

from __future__ import annotations

import json
import re
import typing
from pathlib import Path

import pytest
from pydantic import ValidationError

from worldloom import packkit
from worldloom.connector_data import (
    CAPABILITIES,
    ConnectorCapability,
    ConnectorVerb,
    ContentVerb,
    connector_capabilities,
    definition_capabilities,
)
from worldloom.connector_definition import (
    REFERENCE_CONNECTORS,
    CatalogContentVerb,
    CatalogOperation,
    CatalogRecordVerb,
    ConnectorDefinition,
    load_connector_definition,
    shipped_order,
)
from worldloom.enterprise_specs import (
    BUILTIN_CONNECTORS,
    MUTATE,
    READ,
    ConnectorSpec,
    ContentAction,
    EntitySpec,
    Operation,
    builtin_registry,
    connector_spec_from_definition,
)


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


# -- the literal tables, as they stood in code ---------------------------------------------------------

FILES = ("docx", "xlsx", "pptx", "pdf", "csv", "html", "markdown")


def _entity(name: str, stable_id: str, operations: tuple[Operation, ...], *formats: str) -> EntitySpec:
    return EntitySpec(name=name, stable_id=stable_id, operations=operations, formats=formats)


def _literal_sor_connector() -> ConnectorSpec:
    definition = load_connector_definition("sor")
    return ConnectorSpec(
        name="sor", display_name="System of record",
        entities=tuple(_entity(name, "ident", READ + MUTATE + (Operation.COMMENT,)) for name in definition.entities),
        content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE, ContentAction.RECONCILE),
    )


LITERAL_CAPABILITIES = [
    ConnectorCapability(
        connector="jira",
        entity="issue",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
            ConnectorVerb.LINK,
            ConnectorVerb.UNLINK,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="key",
    ),
    ConnectorCapability(
        connector="servicenow",
        entity="incident",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="sys_id",
    ),
    ConnectorCapability(
        connector="servicenow",
        entity="change_request",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.CREATE,
            ConnectorVerb.UPDATE,
            ConnectorVerb.PATCH,
            ConnectorVerb.UPSERT,
            ConnectorVerb.COMMENT,
            ConnectorVerb.ATTACH,
        ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="sys_id",
    ),
    ConnectorCapability(
        connector="email",
        entity="message",
        verbs=(
            ConnectorVerb.SEARCH,
            ConnectorVerb.LIST,
            ConnectorVerb.READ,
            ConnectorVerb.DRAFT,
            ConnectorVerb.SEND,
            ConnectorVerb.REPLY,
            ConnectorVerb.FORWARD,
            ConnectorVerb.ATTACH,
            ConnectorVerb.DELETE,
        ),
        content_verbs=(
            ContentVerb.SUMMARIZE,
            ContentVerb.EXTRACT,
            ContentVerb.CLASSIFY,
        ),
        stable_id_field="message_id",
    ),
    ConnectorCapability(
        connector="email",
        entity="thread",
        verbs=(ConnectorVerb.SEARCH, ConnectorVerb.LIST, ConnectorVerb.READ),
        content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
        stable_id_field="thread_id",
    ),
    *[
        ConnectorCapability(
            connector="salesforce",
            entity=entity,
            verbs=(
                ConnectorVerb.SEARCH,
                ConnectorVerb.LIST,
                ConnectorVerb.READ,
                ConnectorVerb.CREATE,
                ConnectorVerb.UPDATE,
                ConnectorVerb.PATCH,
                ConnectorVerb.UPSERT,
            ),
            content_verbs=(ContentVerb.SUMMARIZE, ContentVerb.EXTRACT),
            stable_id_field="id",
        )
        for entity in ("account", "contact", "opportunity")
    ],
    *[
        ConnectorCapability(
            connector=connector,
            entity=entity,
            verbs=(
                ConnectorVerb.SEARCH,
                ConnectorVerb.LIST,
                ConnectorVerb.READ,
                ConnectorVerb.CREATE,
                ConnectorVerb.UPDATE,
                ConnectorVerb.PATCH,
                ConnectorVerb.UPSERT,
                ConnectorVerb.DELETE,
            ),
            content_verbs=(
                ContentVerb.SUMMARIZE,
                ContentVerb.EXTRACT,
                ContentVerb.GENERATE,
                ContentVerb.CONVERT,
            ),
            stable_id_field=stable_id,
        )
        for connector, entity, stable_id in (
            ("confluence", "page", "page_id"),
            ("sharepoint", "file", "item_id"),
            ("drive", "file", "file_id"),
            ("salesforce", "case", "id"),
        )
    ],
]


LITERAL_BUILTIN_CONNECTORS = (
    ConnectorSpec(name="jira", display_name="Jira", entities=(_entity("issue", "key", READ + MUTATE + (Operation.COMMENT,)),), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT)),
    ConnectorSpec(name="confluence", display_name="Confluence", entities=(_entity("page", "page_id", READ + MUTATE + (Operation.COMMENT,), "html", "markdown", "pdf"),), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="sharepoint", display_name="SharePoint", entities=(_entity("file", "item_id", READ + MUTATE + (Operation.DELETE,), *FILES), _entity("list_item", "item_id", READ + MUTATE)), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="drive", display_name="Google Drive", entities=(_entity("file", "file_id", READ + MUTATE + (Operation.DELETE,), *FILES),), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="servicenow", display_name="ServiceNow", entities=(_entity("incident", "sys_id", READ + MUTATE + (Operation.COMMENT,)), _entity("change_request", "sys_id", READ + MUTATE + (Operation.COMMENT,))), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT)),
    ConnectorSpec(name="salesforce", display_name="Salesforce", entities=(_entity("account", "id", READ + MUTATE), _entity("contact", "id", READ + MUTATE), _entity("opportunity", "id", READ + MUTATE), _entity("case", "id", READ + MUTATE)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE)),
    ConnectorSpec(name="email", display_name="Email", entities=(_entity("message", "message_id", READ + (Operation.DRAFT, Operation.SEND, Operation.REPLY, Operation.FORWARD)), _entity("thread", "thread_id", READ)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.CLASSIFY, ContentAction.GENERATE)),
    _literal_sor_connector(),
    ConnectorSpec(name="onedrive", display_name="OneDrive", entities=(_entity("file", "id", READ + (Operation.CREATE, Operation.UPDATE, Operation.DELETE), "docx", "xlsx", "pptx", "pdf"), _entity("folder", "id", READ + (Operation.CREATE, Operation.DELETE))), content_actions=tuple(ContentAction)),
    ConnectorSpec(name="outlook", display_name="Outlook", entities=(_entity("message", "id", READ + (Operation.CREATE, Operation.DRAFT, Operation.UPDATE, Operation.SEND, Operation.REPLY, Operation.FORWARD, Operation.COMMENT, Operation.DELETE)), _entity("mail_folder", "id", READ + (Operation.CREATE,)), _entity("attachment", "id", READ + (Operation.CREATE, Operation.DELETE))), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.CLASSIFY, ContentAction.GENERATE)),
    ConnectorSpec(name="slack", display_name="Slack", entities=(_entity("channel", "id", READ + (Operation.CREATE,)), _entity("message", "ts", READ + (Operation.CREATE, Operation.UPDATE, Operation.COMMENT, Operation.REPLY, Operation.DELETE)), _entity("thread", "ts", READ + (Operation.COMMENT, Operation.REPLY)), _entity("file", "id", READ), _entity("user", "id", READ)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.CLASSIFY, ContentAction.GENERATE)),
    ConnectorSpec(name="teams", display_name="Microsoft Teams", entities=(_entity("team", "id", READ), _entity("channel", "id", READ + (Operation.CREATE, Operation.UPDATE, Operation.DELETE)), _entity("chat", "id", READ + (Operation.CREATE,)), _entity("channel_message", "id", READ + (Operation.CREATE, Operation.UPDATE, Operation.COMMENT, Operation.REPLY, Operation.DELETE)), _entity("chat_message", "id", READ + (Operation.CREATE, Operation.UPDATE, Operation.DELETE)), _entity("member", "id", READ)), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.CLASSIFY, ContentAction.GENERATE)),
    ConnectorSpec(name="rovo", display_name="Rovo", entities=tuple(_entity(name, "ari", READ) for name in ("document", "message", "work_item", "person", "team", "project", "goal")), content_actions=(ContentAction.SUMMARIZE, ContentAction.EXTRACT, ContentAction.COMPARE)),
    ConnectorSpec(name="teamwork_graph", display_name="Teamwork Graph", entities=tuple(_entity(name, "ari", READ + (Operation.CREATE, Operation.UPDATE, Operation.DELETE)) for name in ("document", "message", "work_item", "project", "comment", "pull_request", "repository", "space")) + tuple(_entity(name, "ari", READ) for name in ("team", "user", "goal")), content_actions=(ContentAction.EXTRACT, ContentAction.COMPARE)),
)


# -- the derived tables equal them ---------------------------------------------------------------------


def test_the_derived_capabilities_equal_the_literal_table_in_value_and_order() -> None:
    assert CAPABILITIES == LITERAL_CAPABILITIES
    assert [item.model_dump_json() for item in CAPABILITIES] == [item.model_dump_json() for item in LITERAL_CAPABILITIES]


def test_the_derived_specs_equal_the_literal_tuple_in_value_and_order() -> None:
    assert BUILTIN_CONNECTORS == LITERAL_BUILTIN_CONNECTORS
    assert [spec.model_dump_json() for spec in BUILTIN_CONNECTORS] == [
        spec.model_dump_json() for spec in LITERAL_BUILTIN_CONNECTORS]
    assert tuple(builtin_registry().connectors.values()) == LITERAL_BUILTIN_CONNECTORS


def test_the_catalog_vocabularies_are_the_enums_they_stand_for() -> None:
    assert typing.get_args(CatalogOperation) == tuple(item.value for item in Operation)
    assert typing.get_args(CatalogRecordVerb) == tuple(item.value for item in ConnectorVerb)
    assert typing.get_args(CatalogContentVerb) == tuple(item.value for item in ContentAction)
    assert typing.get_args(CatalogContentVerb) == tuple(item.value for item in ContentVerb)


def test_the_pinned_orders_name_only_what_the_definitions_declare() -> None:
    assert set(shipped_order("specs")) == set(REFERENCE_CONNECTORS)
    declared = {(item.connector, item.entity) for name in REFERENCE_CONNECTORS
                for item in definition_capabilities(load_connector_definition(name))}
    assert {tuple(pair.split("/", 1)) for pair in shipped_order("capabilities")} == declared


def test_the_catalog_is_build_time_and_never_served() -> None:
    jira = load_connector_definition("jira")
    assert jira.catalog is not None and jira.display_name == "Jira" and jira.vendor_product == "Jira Cloud"
    assert "catalog" not in jira.served_dict()
    assert ConnectorDefinition.model_validate(jira.wire_dict()) == jira


# -- a pack gets both from its own JSON ----------------------------------------------------------------


def _pack(root: Path, name: str, body: dict) -> None:
    path = root / "connector" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "connector", "name": name, "body": body}))


def _slack_as(name: str, **changes: object) -> dict:
    body = load_connector_definition("slack").served_dict()
    body.update(connector=name, **changes)
    return body


def test_a_pack_without_a_catalog_gets_the_derived_defaults_and_declares_no_capability(tmp_path: Path) -> None:
    _pack(tmp_path, "chatops", _slack_as("chatops", vendor_product="ChatOps Cloud"))
    with packkit.use(roots=[tmp_path]):
        definition = load_connector_definition("chatops")
        spec = builtin_registry().connectors["chatops"]
        assert connector_capabilities(("chatops",)) == []
    assert spec.display_name == "ChatOps Cloud"
    assert [entity.name for entity in spec.entities] == list(definition.entities)
    assert {entity.stable_id for entity in spec.entities} == {"ts"}
    assert spec.content_actions == (ContentAction.SUMMARIZE, ContentAction.EXTRACT)
    # `post` reads as `create`; `transition` has no spec operation; patch/upsert stay off.
    assert spec.entity("channel").operations == READ + (Operation.CREATE,)
    assert spec.entity("message").operations == READ + (Operation.CREATE, Operation.UPDATE, Operation.DELETE,
                                                        Operation.COMMENT, Operation.REPLY)


def test_a_pack_with_a_catalog_is_planned_and_projected_by_it(tmp_path: Path) -> None:
    catalog = {"display_name": "ChatOps", "content_actions": ["summarize"],
               "entities": {"message": {"stable_id": "message_ref", "operations": ["search", "read", "create"],
                                        "record_verbs": ["search", "read"], "content_verbs": ["extract"]},
                            "channel": {}}}
    _pack(tmp_path, "chatops", _slack_as("chatops", catalog=catalog))
    with packkit.use(roots=[tmp_path]):
        definition = load_connector_definition("chatops")
        spec = builtin_registry().connectors["chatops"]
        capabilities = connector_capabilities(("jira", "chatops"))
    assert connector_spec_from_definition(definition) == spec
    assert spec.display_name == "ChatOps" and spec.content_actions == (ContentAction.SUMMARIZE,)
    assert [entity.name for entity in spec.entities] == ["message", "channel"]
    assert spec.entity("message") == EntitySpec(name="message", stable_id="message_ref",
                                                operations=(Operation.SEARCH, Operation.READ, Operation.CREATE))
    assert spec.entity("channel").stable_id == "ts"  # an entry that states nothing takes id.field
    assert capabilities == [
        *(item for item in LITERAL_CAPABILITIES if item.connector == "jira"),
        ConnectorCapability(connector="chatops", entity="message", verbs=(ConnectorVerb.SEARCH, ConnectorVerb.READ),
                            content_verbs=(ContentVerb.EXTRACT,), stable_id_field="message_ref"),
    ]


def test_a_pack_named_like_a_shipped_connector_keeps_the_shipped_tables(tmp_path: Path) -> None:
    body = load_connector_definition("jira").wire_dict()
    body["catalog"] = {"display_name": "Not Jira"}
    _pack(tmp_path, "jira", body)
    with packkit.use(roots=[tmp_path]):
        assert load_connector_definition("jira").display_name == "Not Jira"
        assert builtin_registry().connectors["jira"] == LITERAL_BUILTIN_CONNECTORS[0]
        assert connector_capabilities(("jira",)) == LITERAL_CAPABILITIES[:1]


@pytest.mark.parametrize("catalog, refusal", [
    ({"entities": {"ticket": {}}}, "catalog.entities.ticket: 'ticket' is neither an entity nor an entity alias of chatops"),
    ({"entities": {"message": {"content_verbs": ["extract"]}}}, "content_verbs without record_verbs"),
    ({"entities": {"message": {"record_verbs": ["read", "read"]}}}, "catalog.entities.message.record_verbs repeats a value"),
    ({"entities": {"message": {"stable_id": ""}}}, "catalog.entities.message.stable_id is empty"),
    ({"display_name": ""}, "catalog.display_name is empty"),
    ({"entities": {"message": {"record_verbs": ["move"]}}}, "record_verbs"),
    ({"operations": ["unlink"]}, "operations"),
])
def test_an_inconsistent_catalog_is_refused_naming_what_to_fix(catalog: dict, refusal: str) -> None:
    with pytest.raises(ValidationError, match=re.escape(refusal)):
        ConnectorDefinition.model_validate(_slack_as("chatops", catalog=catalog))


def test_an_inconsistent_catalog_in_a_pack_is_refused_when_the_pack_resolves(tmp_path: Path) -> None:
    _pack(tmp_path, "chatops", _slack_as("chatops", catalog={"entities": {"ticket": {}}}))
    with pytest.raises(ValueError, match=r"does not fit the connector model: .*neither an entity nor an entity alias"):
        packkit.resolve("connector:chatops", roots=[tmp_path])
