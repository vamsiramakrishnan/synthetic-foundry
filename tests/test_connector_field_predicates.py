"""The live connector schema owns field presence and value predicates."""

from __future__ import annotations

import pytest

from worldloom.connector_definition import (
    ConnectorFieldDefinition,
    load_connector_definition,
)
from worldloom.connector_payload import manifest_value, shape_payload
from worldloom.predicates import (
    AsOf,
    FieldPredicate,
    JoinPredicate,
    Predicate,
    RelativeTime,
)


def test_presence_predicate_controls_both_synthesized_and_supplied_values() -> None:
    field = ConnectorFieldDefinition(
        id="cf_risk", canonical="risk_review", name="Risk review",
        field_type="option", options=("required", "waived"),
        present_when=Predicate.equalities({"priority": "High"}),
    )
    definition = load_connector_definition("jira").with_fields("bug", (field,))
    record = {"fid": "bug:1", "entity": "bug", "priority": "High"}
    assert field.is_present(record)
    assert shape_payload(definition, record)["fields"][field.id] in field.options

    record.update(priority="Low", risk_review="required")
    assert not field.is_present(record)
    assert shape_payload(definition, record)["fields"][field.id] is None
    assert manifest_value(definition, record, field, required=True) is None


def test_required_population_bypasses_sparsity_without_overwriting_canonical_truth() -> None:
    field = ConnectorFieldDefinition(id="cf", canonical="risk", name="Risk", fill_rate=0)
    definition = load_connector_definition("jira")
    record = {"fid": "bug:1", "entity": "bug"}
    assert manifest_value(definition, record, field) is None
    value = manifest_value(definition, record, field, required=True)
    assert isinstance(value, str)
    assert value == manifest_value(definition, record, field, required=True)
    assert manifest_value(definition, {**record, "risk": "authored"}, field, required=True) == "authored"


@pytest.mark.parametrize("condition", [
    Predicate(as_of=AsOf()),
    Predicate(joins=(JoinPredicate(field="links", predicate=Predicate()),)),
    Predicate(where=(FieldPredicate(field="updated", value=RelativeTime(days=-1)),)),
])
def test_field_conditions_refuse_context_dependent_predicates(condition: Predicate) -> None:
    with pytest.raises(ValueError, match="record-local"):
        ConnectorFieldDefinition(id="cf", canonical="risk", name="Risk", present_when=condition)


@pytest.mark.parametrize("field_type, valid, invalid", [
    ("text", "abc", 12),
    ("number", 1.5, True),
    ("number", 1, float("nan")),
    ("number", 10**400, float("inf")),
    ("integer", 1, 1.5),
    ("boolean", False, 0),
    ("date", "2024-02-29", "2023-02-29"),
    ("datetime", "2024-02-29T12:00:00+00:00", "not-a-date"),
    ("option", "red", "purple"),
    ("multi_option", ["red", "green"], ["red", "purple"]),
    ("user", {"id": "user:1"}, {"id": 1}),
    ("multi_user", [{"id": "user:1"}], [True]),
    ("cascading", {"value": "red", "child": {"value": "green"}}, {"value": "purple"}),
    ("json", {"a": [1, True]}, {"a": float("inf")}),
])
def test_value_predicates_keep_type_option_and_finiteness_contracts(
    field_type: str, valid: object, invalid: object,
) -> None:
    field = ConnectorFieldDefinition(
        id="cf", canonical="risk", name="Risk", field_type=field_type,
        options=("red", "green") if field_type in {"option", "multi_option", "cascading"} else (),
    )
    assert field.valid_value(valid)
    assert field.valid_value(None)
    assert not field.valid_value(invalid)


def test_duplicate_options_are_rejected_by_the_single_field_contract() -> None:
    with pytest.raises(ValueError, match="duplicate field options"):
        ConnectorFieldDefinition(
            id="cf", canonical="risk", name="Risk", field_type="option", options=("red", "red"),
        )
