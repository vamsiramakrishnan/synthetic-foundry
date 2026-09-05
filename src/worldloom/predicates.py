"""One predicate language for synthetic construction, tools, grading and slicing.

The first version is deliberately small: typed field comparisons over one record.
Joins and bitemporal ``as_of`` views are added by composing this evaluator, not by
creating another matching language in a connector or eval subsystem.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from enum import StrEnum
from typing import Any, TypeAlias

from pydantic import Field, model_validator

from .models import Model

Scalar: TypeAlias = str | int | float | bool | None


class PredicateOp(StrEnum):
    EQ = "eq"
    NE = "ne"
    GT = "gt"
    GTE = "gte"
    LT = "lt"
    LTE = "lte"
    IN = "in"
    CONTAINS = "contains"


class FieldPredicate(Model):
    field: str
    op: PredicateOp = PredicateOp.EQ
    value: Scalar | tuple[Scalar, ...]

    @model_validator(mode="after")
    def _valid_operand(self) -> FieldPredicate:
        if self.op is PredicateOp.IN and not isinstance(self.value, tuple):
            raise ValueError("in predicate requires a tuple operand")
        if self.op is not PredicateOp.IN and isinstance(self.value, tuple):
            raise ValueError(f"{self.op.value} predicate requires a scalar operand")
        return self


class Predicate(Model):
    """A conjunction of typed field predicates for one entity kind."""

    entity: str | None = None
    where: tuple[FieldPredicate, ...] = Field(default_factory=tuple)

    @model_validator(mode="after")
    def _unique_fields(self) -> Predicate:
        fields = [item.field for item in self.where]
        if len(fields) != len(set(fields)):
            raise ValueError("a predicate may constrain each field only once")
        return self

    @classmethod
    def equalities(cls, where: Mapping[str, Scalar], *, entity: str | None = None) -> Predicate:
        return cls(
            entity=entity,
            where=tuple(
                FieldPredicate(field=field, value=value)
                for field, value in sorted(where.items())
            ),
        )


def _ordered_compare(actual: Any, expected: Scalar, op: PredicateOp) -> bool:
    if actual is None or expected is None:
        return False
    try:
        if op is PredicateOp.GT:
            return bool(actual > expected)
        if op is PredicateOp.GTE:
            return bool(actual >= expected)
        if op is PredicateOp.LT:
            return bool(actual < expected)
        if op is PredicateOp.LTE:
            return bool(actual <= expected)
    except TypeError:
        return False
    raise AssertionError(f"not an ordered operator: {op}")


def evaluate_field(item: FieldPredicate, record: Mapping[str, Any]) -> bool:
    actual = record.get(item.field)
    if item.op is PredicateOp.EQ:
        return actual == item.value
    if item.op is PredicateOp.NE:
        return actual != item.value
    if item.op in {PredicateOp.GT, PredicateOp.GTE, PredicateOp.LT, PredicateOp.LTE}:
        assert not isinstance(item.value, tuple)
        return _ordered_compare(actual, item.value, item.op)
    if item.op is PredicateOp.IN:
        assert isinstance(item.value, tuple)
        return actual in item.value
    if item.op is PredicateOp.CONTAINS:
        assert not isinstance(item.value, tuple)
        if actual is None:
            return False
        try:
            return item.value in actual
        except TypeError:
            return False
    raise AssertionError(f"unsupported predicate operator: {item.op}")


def evaluate(predicate: Predicate, record: Mapping[str, Any], *, entity: str | None = None) -> bool:
    """Return whether *record* satisfies *predicate* exactly."""

    if predicate.entity is not None and entity is not None and predicate.entity != entity:
        return False
    return all(evaluate_field(item, record) for item in predicate.where)


def matching(
    predicate: Predicate,
    records: Iterable[Mapping[str, Any]],
    *,
    entity: str | None = None,
) -> tuple[Mapping[str, Any], ...]:
    return tuple(record for record in records if evaluate(predicate, record, entity=entity))


def selectivity(
    predicate: Predicate,
    records: Iterable[Mapping[str, Any]],
    *,
    entity: str | None = None,
) -> float:
    """Observed hit fraction. Empty pools have zero selectivity."""

    pool = tuple(records)
    if not pool:
        return 0.0
    hits = sum(1 for record in pool if evaluate(predicate, record, entity=entity))
    return hits / len(pool)


def distance(predicate: Predicate, record: Mapping[str, Any]) -> int:
    """Number of predicate clauses the record fails.

    This is intentionally clause distance, not lexical distance or retriever
    difficulty. It gives fixture construction and difficulty measurement the same
    exact notion of a one-dimensional near miss.
    """

    return sum(1 for item in predicate.where if not evaluate_field(item, record))


def satisfy(
    predicate: Predicate,
    *,
    base: Mapping[str, Any] | None = None,
    alternatives: Mapping[str, Scalar] | None = None,
) -> dict[str, Any]:
    """Construct the smallest record patch that satisfies *predicate*.

    Operators with no canonical witness (currently ``ne``) require an explicit
    domain alternative. This is deliberate: construction refuses rather than
    minting impossible business values.
    """

    result = dict(base or {})
    choices = alternatives or {}
    for item in predicate.where:
        if evaluate_field(item, result):
            continue
        if item.op is PredicateOp.EQ:
            result[item.field] = item.value
        elif item.op is PredicateOp.IN:
            assert isinstance(item.value, tuple)
            if not item.value:
                raise ValueError(f"{item.field}: cannot satisfy an empty in predicate")
            result[item.field] = item.value[0]
        elif item.op in {PredicateOp.GT, PredicateOp.GTE, PredicateOp.LT, PredicateOp.LTE}:
            assert not isinstance(item.value, tuple)
            if not isinstance(item.value, (int, float)) or isinstance(item.value, bool):
                raise ValueError(f"{item.field}: ordered construction requires a numeric operand")
            if item.op is PredicateOp.GT:
                result[item.field] = item.value + 1
            elif item.op is PredicateOp.GTE:
                result[item.field] = item.value
            elif item.op is PredicateOp.LT:
                result[item.field] = item.value - 1
            else:
                result[item.field] = item.value
        elif item.op is PredicateOp.CONTAINS:
            assert not isinstance(item.value, tuple)
            if not isinstance(item.value, str):
                raise ValueError(f"{item.field}: contains construction requires a string operand")
            result[item.field] = item.value
        elif item.op is PredicateOp.NE:
            if item.field not in choices:
                raise ValueError(f"{item.field}: ne construction requires an explicit alternative")
            candidate = choices[item.field]
            if candidate == item.value:
                raise ValueError(f"{item.field}: alternative must differ from forbidden value")
            result[item.field] = candidate
        else:
            raise AssertionError(f"unsupported predicate operator: {item.op}")
    if not evaluate(predicate, result):
        raise ValueError("constructed record does not satisfy predicate")
    return result


def spoil(
    predicate: Predicate,
    record: Mapping[str, Any],
    *,
    field: str,
    alternative: Scalar,
) -> dict[str, Any]:
    """Create a controlled near-miss that fails exactly *field*.

    Callers own domain-valid alternatives. Worldloom guarantees the mutation is
    minimal and verifies that unrelated predicate clauses remain satisfied.
    """

    if not evaluate(predicate, record):
        raise ValueError("spoil requires a matching source record")
    constrained = {item.field: item for item in predicate.where}
    if field not in constrained:
        raise ValueError(f"field {field!r} is not constrained by predicate")
    spoiled = dict(record)
    spoiled[field] = alternative
    failed = [item.field for item in predicate.where if not evaluate_field(item, spoiled)]
    if failed != [field]:
        raise ValueError(
            f"alternative does not create an exact one-clause near miss; failed={failed}"
        )
    return spoiled


__all__ = [
    "FieldPredicate",
    "Predicate",
    "PredicateOp",
    "Scalar",
    "distance",
    "evaluate",
    "evaluate_field",
    "matching",
    "satisfy",
    "selectivity",
    "spoil",
]
