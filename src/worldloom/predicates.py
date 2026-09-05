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


__all__ = [
    "FieldPredicate",
    "Predicate",
    "PredicateOp",
    "Scalar",
    "evaluate",
    "evaluate_field",
    "matching",
    "selectivity",
]
