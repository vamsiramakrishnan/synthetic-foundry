"""Evidence lives where each vendor keeps it: declared as data, planned, carried on the contract, graded from there.

A gold plan used to write its evidence as two fields no vendor has
(``evidence``, ``evidence_count``), so it proved on the emulator's own tools
and failed on the contract surface. These tests hold the declaration
(``catalog.evidence``) to the shipped contract surfaces, the planner to the
declaration, the contract carrier to the vendor requests a competent client
sends (a named file, a Graph ``@odata.type``, a Confluence page's restated
version, Drive's disjunction, CQL's id filter, SOQL's column list), and the
output grade to the declared place.
"""

from __future__ import annotations

from typing import Any

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connectors.surface import shipped_surface, shipped_surfaces
from worldloom.enterprise_dag import EnterpriseDag, EnterpriseDagNode, outline_document
from worldloom.enterprise_dag_planning import apply_dag_shape, write_body, write_nodes
from worldloom.enterprise_queries import (
    GenerationRequirement,
    MutationRequirement,
    PlannedEnterpriseQuery,
    SourceRequirement,
)
from worldloom.enterprise_specs import builtin_registry
from worldloom.evidence_placement import (
    carries_evidence,
    contract_gap,
    placement,
    plannable,
)


def _query(connector: str, entity: str, operation: str, output_format: str, *, preexisting: bool) -> PlannedEnterpriseQuery:
    return PlannedEnterpriseQuery(
        id="placement-query", workflow="test", query="Write the evidence.", dimensions={},
        generation=GenerationRequirement(
            process="test", source_requirements=(SourceRequirement(connector="jira", entity="issue"),),
            mutation=MutationRequirement(connector=connector, entity=entity, operation=operation,
                                         output_format=output_format, preexisting_record=preexisting),
        ), expected_dag=(),
    )


def _destinations() -> list[tuple[str, str, str]]:
    """Every (connector, entity, operation) a shipped workflow may write its evidence to."""
    registry = builtin_registry()
    found: set[tuple[str, str, str]] = set()
    for workflow in registry.workflows.values():
        for role in workflow.destinations:
            entity_spec = registry.connectors[role.connector]
            for entity in role.entities:
                for operation in role.operations:
                    if operation in entity_spec.entity(entity).operations and carries_evidence(operation.value):
                        found.add((role.connector, entity, operation.value))
    return sorted(found)


# -- the declaration ----------------------------------------------------------------------


def test_every_shipped_destination_declares_where_its_evidence_lives() -> None:
    for connector, entity, _ in _destinations():
        found = placement(connector, entity)
        assert found is not None, f"{connector}/{entity} declares no evidence place (catalog.evidence)"
        assert found.field not in {"evidence", "evidence_count"}, f"{connector}/{entity} keeps an invented field"


def test_a_concrete_entity_finds_the_place_its_alias_declares() -> None:
    sharepoint = load_connector_definition("sharepoint")
    assert sharepoint.evidence_placement("docx") == sharepoint.evidence_placement("file")
    assert sharepoint.evidence_placement("file") is not None and sharepoint.evidence_placement("file").field == "description"


@pytest.mark.parametrize(("connector", "entity", "operation"), _destinations())
def test_the_declaration_agrees_with_the_shipped_contract(connector: str, entity: str, operation: str) -> None:
    """A place the contract carries is planned; one it cannot carry says why, and is not."""
    pytest.importorskip("jsonschema")  # some gaps (Confluence's body union) are the schema's to decide
    if connector not in shipped_surfaces():
        pytest.skip(f"{connector} ships no contract surface; its own tools are its surface")
    definition = load_connector_definition(connector)
    gap = contract_gap(definition, entity, operation)
    found = definition.evidence_placement(entity)
    assert found is not None
    if found.unserved is None:
        assert gap is None, f"{connector}/{entity} {operation}: declared carried, and the contract says {gap}"
    else:
        assert gap is not None, f"{connector}/{entity}: declared unserved ({found.unserved}) but the contract carries it"
        assert not plannable(connector, entity, operation)


def test_an_unserved_place_is_never_planned() -> None:
    from worldloom.enterprise_queries import _row_lanes
    from worldloom.enterprise_specs import CoverageProfile

    lanes = [lane for group in _row_lanes(builtin_registry(), CoverageProfile()) for lane in group]
    for lane in lanes:
        constants = dict(lane.constants)
        for operation in lane.operations:
            assert plannable(constants["destination"], constants["destination_entity"], operation.value), (
                constants, operation)
    destinations = {(dict(lane.constants)["destination"], dict(lane.constants)["destination_entity"])
                    for lane in lanes if lane.operations}
    assert ("confluence", "page") not in destinations
    assert {("sharepoint", "file"), ("drive", "file"), ("salesforce", "account"), ("salesforce", "case"),
            ("salesforce", "opportunity")} <= destinations


# -- the planner --------------------------------------------------------------------------


def test_a_record_write_binds_an_evidence_document_to_the_declared_place() -> None:
    query = _query("sharepoint", "file", "update", "docx", preexisting=True)
    mutation = query.generation.mutation
    nodes, body = write_body(mutation, "collect", ("Summary", "Sources"))
    assert [node.transform for node in nodes] == ["outline"]
    assert nodes[0].arguments == {"sections": ("Summary", "Sources"), "format": "markdown"}
    written = write_nodes(mutation, "collect", body, "write")
    write = next(node for node in written if node.kind == "write")
    assert set(write.bindings) == {"fields.description"} and write.depends_on == ("document",)


def test_a_case_without_sections_writes_one_evidence_section_in_the_places_format() -> None:
    nodes, _ = write_body(MutationRequirement(connector="email", entity="message", operation="draft",
                                              output_format="html", preexisting_record=False), "collect", ())
    assert nodes[0].arguments == {"sections": ("Evidence",), "format": "html"}


def test_a_connector_without_a_place_keeps_the_generic_fields() -> None:
    mutation = MutationRequirement(connector="probe-c", entity="record", operation="create",
                                   output_format="html", preexisting_record=False)
    nodes, body = write_body(mutation, "collect", ())
    assert nodes == [] and body.node == "collect"
    write = next(node for node in write_nodes(mutation, "collect", body, "write") if node.kind == "write")
    assert set(write.bindings) == {"fields.evidence", "fields.evidence_count"}


def test_the_verification_marker_rewrites_the_evidence_at_its_place() -> None:
    shaped = apply_dag_shape(_query("sharepoint", "file", "update", "docx", preexisting=True), "write_chain")
    dag = EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in shaped.expected_dag))
    by_id = {node.id: node for node in dag.nodes}
    marker = by_id["write-marker"]
    assert not marker.arguments and set(marker.bindings) == {"id", "fields.description"}
    assert by_id["document-verified"].arguments["note"] == "Verified against the saved record."


def test_an_outline_closes_with_its_note() -> None:
    values = [{"id": "A", "title": "First"}]
    assert outline_document(values, ["Evidence"], "markdown", note="Checked.").endswith("\n\nChecked.")
    assert outline_document(values, ["Evidence"], "html", note="Checked.").endswith("<p>Checked.</p>")


# -- the contract carrier ------------------------------------------------------------------


def test_a_file_store_create_is_carried_as_a_named_file_with_its_facet() -> None:
    surface = shipped_surface("sharepoint")
    definition = load_connector_definition("sharepoint")
    carried = surface.carry("create_file", {"entity": "pptx", "name": "deck.pptx", "parent": "folder-1",
                                            "fields": {"name": "deck.pptx", "description": "## Evidence"}}, definition)
    assert carried.arguments["body"]["file"] == {} and carried.arguments["body"]["name"] == "deck.pptx"
    assert carried.arguments["body"]["description"] == "## Evidence"


def test_a_graph_update_sends_the_odata_type_its_schema_fixes() -> None:
    surface = shipped_surface("sharepoint")
    definition = load_connector_definition("sharepoint")
    carried = surface.carry("update_file", {"id": "item-1", "fields": {"description": "## Evidence"}}, definition,
                            record={"entity": "docx"})
    assert carried.arguments["body"] == {"description": "## Evidence", "@odata.type": "#microsoft.graph.driveItem"}


def test_a_drive_create_puts_its_parent_in_an_array() -> None:
    surface = shipped_surface("drive")
    definition = load_connector_definition("drive")
    carried = surface.carry("upload_file", {"entity": "docx", "name": "memo.docx", "parent": "folder-1",
                                            "fields": {"name": "memo.docx", "description": "x"}}, definition)
    assert carried.arguments["body"]["parents"] == ["folder-1"]


def test_a_confluence_page_put_restates_the_page_it_read() -> None:
    from worldloom.connectors.anvil import load_mapping
    from worldloom.connectors.surface import _restated

    mapping = load_mapping("confluence")
    entry = mapping.operations["confluence.pages.replace"]
    record = {"fid": "p1", "ident": "10000001", "entity": "page", "title": "Runbook", "updates": [1]}
    _, body = _restated(entry, {"path": {"id": "10000001"}}, {"body": {"value": "<p>x</p>"}},
                        load_connector_definition("confluence"), record)
    assert body["id"] == "10000001" and body["status"] == "current" and body["title"] == "Runbook"
    assert body["version"] == {"number": 3}  # the page is at version 2; a PUT asks for the next
    assert body["body"] == {"value": "<p>x</p>", "representation": "storage"}


def test_a_salesforce_update_carries_its_evidence_and_state_by_the_vendors_field_names() -> None:
    # The authored sObject body declares Description; a state the plan sets on
    # the connector's `stage` or `status` travels as StageName or Status.
    definition = load_connector_definition("salesforce")
    surface = shipped_surface("salesforce")
    for entity, fields, wire in (
        ("opportunity", {"Description": "## Evidence", "stage": "Develop"}, {"description": "## Evidence", "stage_name": "Develop"}),
        ("case", {"Description": "## Evidence", "status": "escalated"}, {"description": "## Evidence", "status": "escalated"}),
    ):
        record = {"fid": "r1", "ident": "0061000000ABCDEFGH", "entity": entity, "title": "Probe"}
        carried = surface.carry("update_record", {"id": "0061000000ABCDEFGH", "fields": fields}, definition, record=record)
        assert carried.tool == "salesforce_update_s_object"
        assert {key: carried.arguments[key] for key in wire} == wire, carried.arguments
        assert carried.arguments["s_object"] == entity.capitalize()


def test_confluence_selects_pages_by_their_numeric_ids_or_their_title() -> None:
    surface = shipped_surface("confluence")
    definition = load_connector_definition("confluence")
    by_id = surface.carry("search", {"predicate": {"where": [{"field": "id", "op": "in", "value": [10000001, 10000002]}]},
                                     "entity": "page", "max_results": 2}, definition)
    assert by_id.tool == "confluence_get_pages" and by_id.arguments == {"id": [10000001, 10000002], "limit": 2}
    by_title = surface.carry("search", {"predicate": {"title": "Runbook"}, "entity": "page", "max_results": 1}, definition)
    assert by_title.arguments == {"title": "Runbook", "limit": 1}


def test_drive_selects_files_by_name_as_a_disjunction() -> None:
    from worldloom.connector_query import compile_native, parse_native
    from worldloom.predicates import Predicate

    definition = load_connector_definition("drive")
    query = compile_native(definition, Predicate.model_validate(
        {"where": [{"field": "name", "op": "in", "value": ["A", "B's"]}]}))
    assert query == "(name = 'A' or name = 'B\\'s')"
    assert parse_native(definition, query).where[0].value == ("A", "B's")
    carried = shipped_surface("drive").carry("search", {"predicate": {"name": ["in", ["A", "B"]]}, "entity": "file",
                                                        "max_results": 2}, definition)
    assert carried.arguments["q"] == "(name = 'A' or name = 'B')"


def test_a_soql_search_names_the_columns_it_needs() -> None:
    from worldloom.connectors.anvil import expressible

    definition = load_connector_definition("salesforce")
    args: dict[str, Any] = {"predicate": {"id": ["in", ["001"]]}, "entity": "case", "fields": ["Id", "Name", "Status"]}
    assert expressible(definition, "query", args)["query"] == "SELECT Id, Name, Status FROM Case WHERE id in ('001')"
    assert expressible(definition, "query", {"predicate": {"id": ["in", ["001"]]}, "entity": "case"})["query"] \
        == "SELECT Id, Name FROM Case WHERE id in ('001')"


def test_a_drive_search_selects_by_name_only_when_the_names_pick_out_the_records() -> None:
    from worldloom.enterprise_dag_rows import identity_selector

    definition = load_connector_definition("drive")
    records = [{"fid": "f1", "server": "drive", "entity": "docx", "name": "Plan"},
               {"fid": "f2", "server": "drive", "entity": "docx", "name": "Memo"},
               {"fid": "f3", "server": "drive", "entity": "docx", "name": "Plan"}]
    by_fid = {record["fid"]: record for record in records}
    assert identity_selector(definition, "search", "file", ["f2"], by_fid, records) == ("name", ["Memo"])
    # Two files named `Plan`: the name would return both, so the search keeps the ids.
    assert identity_selector(definition, "search", "file", ["f1"], by_fid, records) == ("id", ["f1"])
    jira = load_connector_definition("jira")
    assert identity_selector(jira, "search_issues", "issue", ["j1"], {}, [])[0] == "id"


def test_a_sharepoint_search_selects_files_in_kql() -> None:
    definition = load_connector_definition("sharepoint")
    carried = shipped_surface("sharepoint").carry(
        "search_files", {"predicate": {"where": [{"field": "name", "op": "in", "value": ["A", "B"]}]},
                         "entity": "file", "max_results": 2}, definition)
    assert carried.arguments["q"] == '(filename="A" OR filename="B")'


def test_a_command_given_no_surface_keeps_the_one_in_force() -> None:
    from worldloom.connectors.surface import serving_surface, surface_in_force

    with serving_surface("native"), serving_surface(None):
        assert surface_in_force() == "native"
