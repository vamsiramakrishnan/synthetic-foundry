import pytest

from worldloom.predicates import (
    FieldPredicate,
    Predicate,
    PredicateOp,
    distance,
    evaluate,
    matching,
    satisfy,
    selectivity,
    spoil,
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


def test_satisfy_constructs_one_witness_for_same_evaluator() -> None:
    predicate = Predicate(
        entity="incident",
        where=(
            FieldPredicate(field="priority", value="P1"),
            FieldPredicate(field="age_days", op=PredicateOp.GT, value=7),
            FieldPredicate(field="group", op=PredicateOp.IN, value=("Payments-SRE", "Core-SRE")),
        ),
    )

    witness = satisfy(predicate, base={"summary": "gateway timeout"})

    assert witness == {
        "summary": "gateway timeout",
        "priority": "P1",
        "age_days": 8,
        "group": "Payments-SRE",
    }
    assert evaluate(predicate, witness, entity="incident")
    assert distance(predicate, witness) == 0


def test_spoil_fails_exactly_one_clause_and_distance_measures_it() -> None:
    predicate = Predicate.equalities(
        {"priority": "P1", "status": "open", "assignment_group": "Payments-SRE"}
    )
    witness = satisfy(predicate)

    near_miss = spoil(predicate, witness, field="priority", alternative="P2")

    assert not evaluate(predicate, near_miss)
    assert distance(predicate, near_miss) == 1
    assert near_miss["status"] == "open"
    assert near_miss["assignment_group"] == "Payments-SRE"


def test_spoil_refuses_an_alternative_that_still_matches() -> None:
    predicate = Predicate.equalities({"priority": "P1"})
    witness = satisfy(predicate)

    with pytest.raises(ValueError, match="exact one-clause near miss"):
        spoil(predicate, witness, field="priority", alternative="P1")


def test_ne_construction_requires_domain_alternative() -> None:
    predicate = Predicate(
        where=(FieldPredicate(field="status", op=PredicateOp.NE, value="closed"),)
    )

    with pytest.raises(ValueError, match="explicit alternative"):
        satisfy(predicate)
    assert satisfy(predicate, alternatives={"status": "open"})["status"] == "open"


def test_duplicate_field_constraint_refuses_until_boolean_language_exists() -> None:
    with pytest.raises(ValueError, match="each field only once"):
        Predicate(
            where=(
                FieldPredicate(field="age_days", op=PredicateOp.GTE, value=7),
                FieldPredicate(field="age_days", op=PredicateOp.LTE, value=30),
            )
        )
