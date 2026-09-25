"""Connector packs: an uploaded definition is served, listed, planned and shown catalogue records."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from worldloom import packkit
from worldloom.connector_data import ConnectorRecord
from worldloom.connector_definition import (
    REFERENCE_CONNECTORS,
    ConnectorDefinition,
    builtin_connector_definitions,
    is_reference_connector,
    load_connector_definition,
    reference_connectors,
)
from worldloom.connector_emulator import ConnectorEmulator


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


def _definition(name: str, *, vendor: str, projection: dict | None = None) -> dict:
    """A complete definition body: ServiceNow's contract under another name."""
    body = load_connector_definition("servicenow").served_dict()
    body.update(connector=name, vendor_product=vendor)
    if projection is not None:
        body["record_projection"] = projection
    return body


def _pack(root: Path, name: str, body: dict) -> Path:
    path = root / "connector" / f"{name}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "connector", "name": name, "body": body}))
    return path


ZENDESK_PROJECTION = {
    "fields": {"ticket_id": "{key|first:12|upper}", "subject": "{title}", "status": "{status}",
               "requester": "{owner_bu|address}", "tags": ["{stream}", "{period}"]},
    "entities": {"problem": {"type": "problem"}},
}


def test_the_reference_list_is_the_shipped_listing_in_its_historical_order() -> None:
    assert REFERENCE_CONNECTORS == (
        "jira", "servicenow", "salesforce", "confluence", "sharepoint", "drive", "outlook", "email", "onedrive",
        "teams", "slack", "teamwork_graph", "rovo", "sor",
    )
    directory = files("worldloom").joinpath("_data", "connectors")
    listed = {entry.name[:-5] for entry in directory.iterdir()
              if entry.name.endswith(".json") and not entry.name.startswith("_")}
    assert set(REFERENCE_CONNECTORS) == listed
    assert reference_connectors() == REFERENCE_CONNECTORS  # no pack in view


def test_an_uploaded_connector_pack_is_listed_loaded_served_and_planned(tmp_path: Path) -> None:
    root = tmp_path / "packs"
    _pack(root, "zendesk", _definition("zendesk", vendor="Zendesk Support", projection=ZENDESK_PROJECTION))
    assert not is_reference_connector("zendesk")
    with pytest.raises(ValueError, match="unknown built-in connector definition"):
        load_connector_definition("zendesk")
    with packkit.use(roots=[root]):
        assert reference_connectors() == (*REFERENCE_CONNECTORS, "zendesk")
        assert is_reference_connector("zendesk")
        definition = load_connector_definition("zendesk")
        assert definition.vendor_product == "Zendesk Support"
        assert "zendesk" in builtin_connector_definitions()
        # The emulator serves it like any shipped connector.
        emulator = ConnectorEmulator(definition, [
            {"fid": "zd:1", "server": "zendesk", "entity": "incident", "ident": "INC0000001", "name": "Printer down",
             "short_description": "Printer down", "state": 1},
        ])
        page = emulator.call("search_records", entity="incident", predicate={"short_description": "Printer down"})
        assert page, page
        # The enterprise registry gets a spec derived from the definition.
        from worldloom.enterprise_specs import builtin_registry

        spec = builtin_registry().connectors["zendesk"]
        assert spec.display_name == "Zendesk Support"
        assert [entity.name for entity in spec.entities] == list(definition.entities)
        assert {entity.stable_id for entity in spec.entities} == {definition.id.field}
        assert "patch" not in spec.entity("incident").operations
    assert not is_reference_connector("zendesk")


def test_a_pack_in_the_users_home_is_visible_but_never_shadows_a_shipped_connector(tmp_path: Path) -> None:
    home = tmp_path / "home" / "packs"
    _pack(home, "zendesk", _definition("zendesk", vendor="Zendesk Support"))
    _pack(home, "jira", {**load_connector_definition("jira").served_dict(), "vendor_product": "Jira (home copy)"})
    assert is_reference_connector("zendesk")
    assert load_connector_definition("jira").vendor_product == "Jira Cloud"
    # A root the run names does shadow it, and so does a pack put in force.
    named = tmp_path / "named"
    _pack(named, "jira", {**load_connector_definition("jira").served_dict(), "vendor_product": "Jira (named root)"})
    with packkit.use(roots=[named]):
        assert load_connector_definition("jira").vendor_product == "Jira (named root)"
    with packkit.use("connector:jira"):
        assert load_connector_definition("jira").vendor_product == "Jira (home copy)"
    assert load_connector_definition("jira").vendor_product == "Jira Cloud"


def test_a_pack_declares_how_catalogue_records_appear_on_it(tmp_path: Path) -> None:
    from worldloom import sor

    root = tmp_path / "packs"
    _pack(root, "zendesk", _definition("zendesk", vendor="Zendesk Support", projection=ZENDESK_PROJECTION))
    record = ConnectorRecord(
        id="SOR-1", connector="sor", entity="incident", external_id="SOR0000000001", title="Outage in billing",
        fields={"period": "2026-03", "owner_bu": "Service Desk", "status": "open", "control": "Triage within 4h",
                "exception": "", "stream": "incidents", "function": "Support", "company_id": "Ardent",
                "product": "Zendesk", "object": "Incident"},
    )
    table = {"products": {"Zendesk": {"connector": "zendesk", "objects": {"Incident": "problem"}}}}
    with packkit.use(roots=[root]):
        (restated,) = sor.product_records([record], table=table)
    assert restated.connector == "zendesk" and restated.entity == "problem"
    fields = restated.fields
    assert fields["sor_record_id"] == "SOR-1" and fields["subject"] == "Outage in billing"
    assert fields["requester"] == "Service Desk <service-desk@ardent.example>"
    assert fields["tags"] == ["incidents", "2026-03"] and fields["type"] == "problem"
    assert fields["ticket_id"] == fields["ticket_id"].upper() and len(fields["ticket_id"]) == 12


def test_a_projection_naming_an_unknown_filter_is_refused_with_the_definition() -> None:
    body = _definition("zendesk", vendor="Zendesk Support", projection={"fields": {"subject": "{title|shout}"}})
    with pytest.raises(ValueError, match="filter 'shout' is unknown"):
        ConnectorDefinition.model_validate(body)
    body = _definition("zendesk", vendor="Zendesk Support", projection={"fields": {"id": "{key|first}"}})
    with pytest.raises(ValueError, match="needs an argument"):
        ConnectorDefinition.model_validate(body)


def test_a_pack_stored_under_another_name_is_refused_by_the_lint(tmp_path: Path) -> None:
    _pack(tmp_path, "zendesk", _definition("freshdesk", vendor="Freshdesk"))
    findings = packkit.lint(packkit.resolve("connector:zendesk", roots=[tmp_path]))
    assert findings and "connector:freshdesk" in findings[0]


def test_the_projection_is_build_time_only_and_the_wire_form_round_trips() -> None:
    servicenow = load_connector_definition("servicenow")
    assert servicenow.record_projection is not None
    assert ConnectorDefinition.model_validate(servicenow.wire_dict()) == servicenow
    assert "record_projection" not in servicenow.served_dict()
    # A definition without one serialises exactly as before the field existed.
    assert "record_projection" not in load_connector_definition("slack").wire_dict()


def test_identity_keys_are_stated_once() -> None:
    from worldloom import connector_emulator, enterprise_failures
    from worldloom.connector_keys import (
        PAYLOAD_IDENTITY_KEYS,
        RECORDED_ALIAS_KEYS,
        SHAPED_IDENTITY_KEYS,
        STABLE_ID_FIELDS,
    )

    assert SHAPED_IDENTITY_KEYS == ("id", "Id", "sys_id", "key", "number", "ts", "ari")
    assert PAYLOAD_IDENTITY_KEYS == {"id", "Id", "sys_id", "key", "number", "attributes", "ts", "ari", "type"}
    assert RECORDED_ALIAS_KEYS == ("id", "Id", "sys_id", "key", "number", "name", "title")
    assert connector_emulator._SHAPED_IDENTITY_KEYS is SHAPED_IDENTITY_KEYS
    assert enterprise_failures._STABLE_FIELDS is STABLE_ID_FIELDS


def test_the_connector_prompt_and_policy_keys_resolve() -> None:
    assert packkit.text("connectors.record.body", title="T", control="C") == "T. Control: C."
    assert packkit.text("connectors.record.exception", exception="E") == " Exception: E."
    from worldloom.connectors.serving import ServingLimits

    assert ServingLimits() == ServingLimits(max_runs=32, max_runs_per_principal=4, max_calls_per_run=4096,
                                            max_tools=100, max_request_bytes=65536, max_response_bytes=1048576,
                                            max_records=100000)
