from __future__ import annotations

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_query import compile_native, parse_native
from worldloom.predicates import FieldPredicate, Predicate, PredicateOp


@pytest.mark.parametrize(
    ("connector", "entity", "predicate", "native_field"),
    [
        (
            "jira",
            "bug",
            Predicate(
                entity="bug",
                where=(
                    FieldPredicate(field="project", value="PHX"),
                    FieldPredicate(field="severity", op=PredicateOp.EQ, value="Sev-1"),
                ),
            ),
            "cf[10231]",
        ),
        (
            "salesforce",
            "opportunity",
            Predicate(
                entity="opportunity",
                where=(
                    FieldPredicate(field="company", value="Stark Retail"),
                    FieldPredicate(field="amount", op=PredicateOp.GTE, value=100000),
                ),
            ),
            "Account.Name",
        ),
        (
            "servicenow",
            "incident",
            Predicate(
                entity="incident",
                where=(
                    FieldPredicate(field="ci", value="checkout-api"),
                    FieldPredicate(field="priority", op=PredicateOp.IN, value=("1", "2")),
                ),
            ),
            "cmdb_ci.name",
        ),
        (
            "confluence",
            "page",
            Predicate(
                entity="page",
                where=(
                    FieldPredicate(field="space", value="ENG"),
                    FieldPredicate(
                        field="mentions",
                        op=PredicateOp.CONTAINS,
                        value="data residency",
                    ),
                ),
            ),
            "text",
        ),
        (
            "sharepoint",
            "docx",
            Predicate(
                entity="docx",
                where=(
                    FieldPredicate(field="site", value="Fabrikam-Ops"),
                    FieldPredicate(field="modified_days", op=PredicateOp.LTE, value=30),
                ),
            ),
            "lastModifiedDateTime",
        ),
        (
            "drive",
            "gdoc",
            Predicate(
                entity="gdoc",
                where=(
                    FieldPredicate(field="folder", value="Program Cinder"),
                    FieldPredicate(
                        field="mentions", op=PredicateOp.CONTAINS, value="rollback"
                    ),
                ),
            ),
            "fullText",
        ),
    ],
)
def test_native_query_round_trip_uses_definition_bindings(
    connector: str,
    entity: str,
    predicate: Predicate,
    native_field: str,
) -> None:
    definition = load_connector_definition(connector)

    native = compile_native(definition, predicate, entity=entity)
    parsed = parse_native(definition, native, entity=entity)

    assert native_field in native
    assert parsed == predicate


def test_salesforce_source_name_is_definition_data() -> None:
    definition = load_connector_definition("salesforce")
    predicate = Predicate.equalities({"status": "open"}, entity="case")

    native = compile_native(definition, predicate)

    assert native.startswith("SELECT Id, Name FROM Case WHERE ")
    assert parse_native(definition, native) == predicate


def test_confluence_type_is_definition_data() -> None:
    definition = load_connector_definition("confluence")
    predicate = Predicate.equalities({"space": "OPS"}, entity="blogpost")

    native = compile_native(definition, predicate)

    assert native.startswith("type = 'blogpost' AND ")
    assert parse_native(definition, native) == predicate


def test_null_predicates_round_trip_without_another_query_dsl() -> None:
    jira = load_connector_definition("jira")
    missing = Predicate(
        entity="bug",
        where=(FieldPredicate(field="assignee", op=PredicateOp.EQ, value=None),),
    )
    present = Predicate(
        entity="bug",
        where=(FieldPredicate(field="assignee", op=PredicateOp.NE, value=None),),
    )

    assert parse_native(jira, compile_native(jira, missing)) == missing
    assert parse_native(jira, compile_native(jira, present)) == present
