"""One bounded predicate evaluator for tools, construction, oracles and slices.

Joins and as-of queries require an explicit frozen QueryContext. Omitting that
context is an error, never permission to fall back to present-day raw values.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, TypeAlias

from pydantic import Field, model_validator

from .epistemics import ledger_from_facts
from .models import CanonicalFact, Model

Scalar: TypeAlias = str | int | float | bool | None


class RelativeTime(Model):
    days: int = 0
    seconds: int = 0

    def resolve(self, clock: datetime) -> datetime:
        return clock + timedelta(days=self.days, seconds=self.seconds)


class AsOf(Model):
    observer: str = "*"
    valid_at: datetime | RelativeTime | Literal["clock"] = "clock"
    tx_at: datetime | RelativeTime | Literal["clock"] = "clock"

    def resolve(self, clock: datetime) -> tuple[datetime, datetime]:
        def at(value: datetime | RelativeTime | Literal["clock"]) -> datetime:
            if value == "clock":
                return clock
            if isinstance(value, RelativeTime):
                return value.resolve(clock)
            assert isinstance(value, datetime)
            return value
        return at(self.valid_at), at(self.tx_at)


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
    field: str = Field(min_length=1)
    op: PredicateOp = PredicateOp.EQ
    value: Scalar | tuple[Scalar, ...] | RelativeTime

    @model_validator(mode="after")
    def _valid_operand(self) -> FieldPredicate:
        if self.op is PredicateOp.IN and not isinstance(self.value, tuple):
            raise ValueError("in predicate requires a tuple operand")
        if self.op is not PredicateOp.IN and isinstance(self.value, tuple):
            raise ValueError(f"{self.op.value} predicate requires a scalar operand")
        return self


class JoinPredicate(Model):
    field: str = Field(min_length=1)
    predicate: Predicate


class Predicate(Model):
    entity: str | None = None
    connector: str | None = None
    where: tuple[FieldPredicate, ...] = Field(default_factory=tuple)
    joins: tuple[JoinPredicate, ...] = ()
    as_of: AsOf | None = None

    @model_validator(mode="after")
    def _unique_fields(self) -> Predicate:
        fields = [item.field for item in self.where]
        if len(fields) != len(set(fields)):
            raise ValueError("a predicate may constrain each field only once")
        joins = [item.field for item in self.joins]
        if len(joins) != len(set(joins)):
            raise ValueError("a predicate may join each field only once")
        if self.join_depth > 8:
            raise ValueError("predicate joins exceed depth limit of eight")
        return self

    @property
    def join_depth(self) -> int:
        return max((1 + item.predicate.join_depth for item in self.joins), default=0)

    @classmethod
    def equalities(cls, where: Mapping[str, Scalar], *, entity: str | None = None) -> Predicate:
        return cls(entity=entity, where=tuple(
            FieldPredicate(field=field, value=value) for field, value in sorted(where.items())
        ))


JoinPredicate.model_rebuild()
Predicate.model_rebuild()


@dataclass(frozen=True)
class QueryContext:
    clock: datetime
    facts: tuple[CanonicalFact, ...] = ()
    records: tuple[Mapping[str, Any], ...] = ()

    def project(self, record: Mapping[str, Any], as_of: AsOf) -> dict[str, Any]:
        """Replace ledger-owned attributes with their observer/time view.

        Removing hidden attributes first is essential: overlay-only projection
        leaks the current value when the historical view contains no row.
        """
        valid_at, tx_at = as_of.resolve(self.clock)
        subject = record.get("subject", record.get("id"))
        relevant = tuple(fact for fact in self.facts if fact.subject == subject)
        output = deepcopy(dict(record))
        for fact in relevant:
            output.pop(fact.kind, None)
        if "period" in record:
            relevant = tuple(fact for fact in relevant if fact.period == record["period"])
        view = ledger_from_facts(relevant).view(as_of.observer, valid_at=valid_at, tx_at=tx_at)
        seen: set[str] = set()
        for fact in view:
            if fact.kind in seen:
                raise ValueError(f"{subject}/{fact.kind}: query must scope a period")
            seen.add(fact.kind)
            output[fact.kind] = fact.value.amount if fact.value is not None else fact.text_value
        return output


_MISSING = object()


def _value(record: Mapping[str, Any], field: str) -> Any:
    if field in record:
        return record[field]
    current: Any = record
    for key in field.split("."):
        if not isinstance(current, Mapping) or key not in current:
            return _MISSING
        current = current[key]
    return current


def _equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) != isinstance(expected, bool):
        return False
    return bool(actual == expected)


def evaluate_field(item: FieldPredicate, record: Mapping[str, Any], *, clock: datetime | None = None) -> bool:
    actual = _value(record, item.field)
    if actual is _MISSING:
        return False
    expected: Any = item.value
    if isinstance(expected, RelativeTime):
        if clock is None:
            raise ValueError("relative-time predicate requires a frozen clock")
        expected = expected.resolve(clock)
        if isinstance(actual, str):
            try:
                actual = datetime.fromisoformat(actual)
            except ValueError:
                return False
    if item.op is PredicateOp.EQ:
        return _equal(actual, expected)
    if item.op is PredicateOp.NE:
        return not _equal(actual, expected)
    if item.op is PredicateOp.IN:
        return any(_equal(actual, candidate) for candidate in expected)
    if item.op is PredicateOp.CONTAINS:
        try:
            return expected in actual
        except TypeError:
            return False
    if actual is None or expected is None or isinstance(actual, bool) or isinstance(expected, bool):
        return False
    try:
        if item.op is PredicateOp.GT:
            return bool(actual > expected)
        if item.op is PredicateOp.GTE:
            return bool(actual >= expected)
        if item.op is PredicateOp.LT:
            return bool(actual < expected)
        if item.op is PredicateOp.LTE:
            return bool(actual <= expected)
    except TypeError:
        return False
    raise AssertionError(f"unsupported predicate operator: {item.op}")


def evaluate(predicate: Predicate, record: Mapping[str, Any], *, entity: str | None = None,
             context: QueryContext | None = None) -> bool:
    if (predicate.as_of is not None or predicate.joins) and context is None:
        raise ValueError("as_of and joins require a QueryContext")
    actual_entity = entity if entity is not None else record.get("entity")
    if predicate.entity is not None and actual_entity is not None and predicate.entity != actual_entity:
        return False
    if predicate.connector is not None and record.get("connector") != predicate.connector:
        return False
    active = context.project(record, predicate.as_of) if context is not None and predicate.as_of else record
    if not all(evaluate_field(item, active, clock=context.clock if context else None) for item in predicate.where):
        return False
    for join in predicate.joins:
        assert context is not None
        links = _value(active, join.field)
        if links is _MISSING or links is None:
            return False
        ids = (links,) if isinstance(links, str) else links
        if not isinstance(ids, (list, tuple)) or not all(isinstance(value, str) for value in ids):
            raise ValueError(f"{join.field}: joins require an ID or an ordered list of IDs")
        child = join.predicate
        if child.as_of is None and predicate.as_of is not None:
            child = child.model_copy(update={"as_of": predicate.as_of})
        if not any(
            (target.get("id") in ids or target.get("external_id") in ids)
            and evaluate(child, target, context=context)
            for target in context.records
        ):
            return False
    return True


def matching(predicate: Predicate, records: Iterable[Mapping[str, Any]], *, entity: str | None = None,
             context: QueryContext | None = None) -> tuple[Mapping[str, Any], ...]:
    return tuple(record for record in records if evaluate(predicate, record, entity=entity, context=context))


def selectivity(predicate: Predicate, records: Iterable[Mapping[str, Any]], *, entity: str | None = None,
                context: QueryContext | None = None) -> float:
    pool = tuple(records)
    return len(matching(predicate, pool, entity=entity, context=context)) / len(pool) if pool else 0.0


def distance(predicate: Predicate, record: Mapping[str, Any], *, context: QueryContext | None = None) -> int:
    """Exact failed field/relationship count, not guessed agent difficulty."""
    if predicate.as_of is not None and context is None:
        raise ValueError("as_of requires a QueryContext")
    active = context.project(record, predicate.as_of) if context is not None and predicate.as_of else record
    failed = sum(not evaluate_field(item, active, clock=context.clock if context else None) for item in predicate.where)
    for join in predicate.joins:
        failed += not evaluate(predicate.model_copy(update={"where": (), "joins": (join,)}), record, context=context)
    return failed


def satisfy(predicate: Predicate, *, base: Mapping[str, Any] | None = None,
            alternatives: Mapping[str, Scalar] | None = None) -> dict[str, Any]:
    """Minimal field witness; historical or relational construction needs events."""
    if predicate.as_of is not None or predicate.joins:
        raise ValueError("historical/relational construction requires an intervention")
    result = deepcopy(dict(base or {}))
    choices = alternatives or {}
    for item in predicate.where:
        if "." in item.field:
            raise ValueError("nested construction requires an explicit domain tactic")
        if item.field in result and evaluate_field(item, result):
            continue
        if item.op is PredicateOp.EQ:
            result[item.field] = item.value
        elif item.op is PredicateOp.IN:
            assert isinstance(item.value, tuple)
            if not item.value:
                raise ValueError(f"{item.field}: cannot satisfy an empty in predicate")
            result[item.field] = item.value[0]
        elif item.op in {PredicateOp.GT, PredicateOp.GTE, PredicateOp.LT, PredicateOp.LTE}:
            value = item.value
            if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value):
                raise ValueError(f"{item.field}: ordered construction requires a finite numeric operand")
            direction = 1 if item.op is PredicateOp.GT else -1
            result[item.field] = (value + direction if isinstance(value, int) else math.nextafter(value, math.inf * direction)) if item.op in {PredicateOp.GT, PredicateOp.LT} else value
        elif item.op is PredicateOp.CONTAINS:
            if not isinstance(item.value, str):
                raise ValueError(f"{item.field}: contains construction requires a string operand")
            result[item.field] = item.value
        elif item.op is PredicateOp.NE:
            if item.field not in choices:
                raise ValueError(f"{item.field}: ne construction requires an explicit alternative")
            if _equal(choices[item.field], item.value):
                raise ValueError(f"{item.field}: alternative must differ from forbidden value")
            result[item.field] = choices[item.field]
    if not evaluate(predicate, result, entity=predicate.entity):
        raise ValueError("constructed record does not satisfy predicate")
    return result


def spoil(predicate: Predicate, record: Mapping[str, Any], *, field: str, alternative: Scalar) -> dict[str, Any]:
    if predicate.as_of is not None or predicate.joins:
        raise ValueError("historical/relational near-misses require an intervention")
    if not evaluate(predicate, record):
        raise ValueError("spoil requires a matching source record")
    if field not in {item.field for item in predicate.where}:
        raise ValueError(f"field {field!r} is not constrained by predicate")
    spoiled = deepcopy(dict(record))
    spoiled[field] = alternative
    failed = [item.field for item in predicate.where if not evaluate_field(item, spoiled)]
    if failed != [field]:
        raise ValueError(f"alternative does not create an exact one-clause near miss; failed={failed}")
    return spoiled


__all__ = ["AsOf", "FieldPredicate", "JoinPredicate", "Predicate", "PredicateOp", "QueryContext", "RelativeTime", "Scalar", "distance", "evaluate", "evaluate_field", "matching", "satisfy", "selectivity", "spoil"]
