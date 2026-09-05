import pytest

from worldloom.predicates import (
    FieldPredicate,
    Predicate,
    PredicateOp,
    evaluate,
    matching,
    selectivity,
)


def test_equalities_are_canonical_and_match() -> None:
    predicate = Predicate.equalities({"status": "open", "priority": "P1"}, entity="incident")
    record = {"priority": "P1", "status": "open", "assignment_group": "Payments-SRE"}

    assert [item.field for item in predicate.where] == ["priority", "status"]
    assert evaluate(predicate, record, entity="incident")
    assert not evaluate(predicate, record, entity="bug")


def test_order_membership_and_contains_are_typed() -> None:
    predicate = Predicate(
        where=(
            FieldPredicate(field="age_days", op=PredicateOp.GT, value=7),
            FieldPredicate(field="priority", op=PredicateOp.IN, value=("P1", "P2")),
            FieldPredicate(field="summary", op=PredicateOp.CONTAINS, value="payment"),
        )
    )

    assert evaluate(
        predicate,
        {"age_days": 21, "priority": "P1", "summary": "payment gateway timeout"},
    )
    assert not evaluate(
        predicate,
        {"age_days": 3, "priority": "P1", "summary": "payment gateway timeout"},
    )


def test_bad_operands_refuse() -> None:
    with pytest.raises(ValueError, match="tuple operand"):
        FieldPredicate(field="priority", op=PredicateOp.IN, value="P1")
    with pytest.raises(ValueError, match="scalar operand"):
        FieldPredicate(field="priority", op=PredicateOp.EQ, value=("P1", "P2"))


def test_matching_and_selectivity_share_evaluator() -> None:
    predicate = Predicate.equalities({"priority": "P1"})
    records = (
        {"id": "1", "priority": "P1"},
        {"id": "2", "priority": "P2"},
        {"id": "3", "priority": "P1"},
        {"id": "4", "priority": "P3"},
    )

    assert tuple(row["id"] for row in matching(predicate, records)) == ("1", "3")
    assert selectivity(predicate, records) == 0.5


def test_duplicate_field_constraint_refuses_until_boolean_language_exists() -> None:
    with pytest.raises(ValueError, match="each field only once"):
        Predicate(
            where=(
                FieldPredicate(field="age_days", op=PredicateOp.GTE, value=7),
                FieldPredicate(field="age_days", op=PredicateOp.LTE, value=30),
            )
        )
