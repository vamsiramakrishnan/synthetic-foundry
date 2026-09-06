"""Compile an eval design into constructive world obligations.

This module is intentionally pre-data. It never generates IDs, records, or
connector fixtures. It only normalizes what a candidate world must make true.
"""

from __future__ import annotations

from enum import StrEnum
from typing import TypeAlias

from pydantic import Field

from .eval_design import EvalSpec, RequirementKind
from .models import Model

Scalar: TypeAlias = str | int | bool


class DemandKind(StrEnum):
    EVIDENCE = "evidence"
    SEARCH = "search"
    ARTIFACT = "artifact"
    ABSENCE = "absence"
    PERMISSION = "permission"
    STATE = "state"
    CARDINALITY = "cardinality"
    TEMPORAL = "temporal"
    MUTATION = "mutation"


class WorldDemand(Model):
    id: str
    kind: DemandKind
    source_requirement_ids: tuple[str, ...] = ()
    source_step_ids: tuple[str, ...] = ()
    selector: dict[str, Scalar] = Field(default_factory=dict)
    minimum: int = Field(default=1, ge=1)
    hard: bool = True


class DemandSet(Model):
    eval_spec_id: str
    design_digest: str
    demands: tuple[WorldDemand, ...]


_REQUIREMENT_KIND: dict[RequirementKind, DemandKind] = {
    RequirementKind.FACT: DemandKind.EVIDENCE,
    RequirementKind.EVENT: DemandKind.STATE,
    RequirementKind.ARTIFACT: DemandKind.ARTIFACT,
    RequirementKind.CONNECTOR: DemandKind.SEARCH,
    RequirementKind.REVISION_CHAIN: DemandKind.STATE,
    RequirementKind.PERMISSION: DemandKind.PERMISSION,
    RequirementKind.DISTRACTOR: DemandKind.CARDINALITY,
    RequirementKind.TEMPORAL_RELATION: DemandKind.TEMPORAL,
}

_IDENTITY_KEYS = ("id", "entity_id", "record_id", "artifact_id", "object_id")
_EXCLUSIVE_KEYS = ("state", "status", "effect")


def _key(demand: WorldDemand) -> tuple[DemandKind, tuple[tuple[str, Scalar], ...]]:
    return demand.kind, tuple(sorted(demand.selector.items()))


def _from_requirements(spec: EvalSpec) -> list[WorldDemand]:
    demands: list[WorldDemand] = []
    for requirement in spec.requirements:
        selector: dict[str, Scalar] = dict(requirement.selector)
        selector.setdefault("requirement_kind", requirement.kind.value)
        demands.append(
            WorldDemand(
                id=f"demand:{requirement.id}",
                kind=_REQUIREMENT_KIND[requirement.kind],
                source_requirement_ids=(requirement.id,),
                selector=selector,
                minimum=requirement.minimum,
                hard=requirement.hard,
            )
        )
    return demands


def _from_steps(spec: EvalSpec) -> list[WorldDemand]:
    """Extract obligations implied by the task graph itself.

    A declared write needs a mutable precondition even if an author forgot to
    repeat that fact in ``requirements``. Search/list/find operations need a
    searchable witness. These are construction obligations, not oracle answers.
    """

    demands: list[WorldDemand] = []
    for step in spec.steps:
        selector: dict[str, Scalar] = {"capability": step.capability}
        if step.connector:
            selector["connector"] = step.connector
        if step.entity:
            # The entity the step names is the entity its witness must be. A
            # Teams search for channel messages constructed a `team` before
            # this line, because the selector never said otherwise.
            selector["entity"] = step.entity
        if step.operation:
            selector["operation"] = step.operation
        operation = (step.operation or step.capability).lower()
        if step.effect == "write":
            demands.append(
                WorldDemand(
                    id=f"step:{step.id}:mutation",
                    kind=DemandKind.MUTATION,
                    source_step_ids=(step.id,),
                    selector=selector,
                )
            )
        elif any(token in operation for token in ("search", "find", "list", "query")):
            demands.append(
                WorldDemand(
                    id=f"step:{step.id}:search",
                    kind=DemandKind.SEARCH,
                    source_step_ids=(step.id,),
                    selector=selector,
                )
            )
    return demands


def _normalize(demands: list[WorldDemand]) -> tuple[WorldDemand, ...]:
    grouped: dict[tuple[DemandKind, tuple[tuple[str, Scalar], ...]], list[WorldDemand]] = {}
    for demand in demands:
        grouped.setdefault(_key(demand), []).append(demand)

    normalized: list[WorldDemand] = []
    for key in sorted(grouped, key=lambda item: (item[0].value, repr(item[1]))):
        group = grouped[key]
        source_requirements = tuple(sorted({item for d in group for item in d.source_requirement_ids}))
        source_steps = tuple(sorted({item for d in group for item in d.source_step_ids}))
        minimum = max(d.minimum for d in group)
        hard = any(d.hard for d in group)
        first = group[0]
        normalized.append(
            WorldDemand(
                id="demand:" + "+".join(source_requirements or source_steps),
                kind=first.kind,
                source_requirement_ids=source_requirements,
                source_step_ids=source_steps,
                selector=dict(first.selector),
                minimum=minimum,
                hard=hard,
            )
        )
    return tuple(normalized)


def _reject_obvious_conflicts(demands: tuple[WorldDemand, ...]) -> None:
    """Reject same-object hard state contradictions before generation.

    This intentionally catches only conflicts that are statically unambiguous:
    both demands identify the same concrete object and disagree on one exclusive
    state field with no temporal qualifier. Rich temporal/state solving belongs
    in tactics or a future solver rather than in this conservative preflight.
    """

    hard = [demand for demand in demands if demand.hard]
    temporal_keys = {"at", "before", "after", "period", "timestamp", "time"}
    for index, left in enumerate(hard):
        for right in hard[index + 1 :]:
            if left.kind != right.kind:
                continue
            identity = next(
                (
                    key
                    for key in _IDENTITY_KEYS
                    if key in left.selector
                    and key in right.selector
                    and left.selector[key] == right.selector[key]
                ),
                None,
            )
            if identity is None or temporal_keys & (set(left.selector) | set(right.selector)):
                continue
            for exclusive in _EXCLUSIVE_KEYS:
                if exclusive not in left.selector or exclusive not in right.selector:
                    continue
                if left.selector[exclusive] == right.selector[exclusive]:
                    continue
                comparable_keys = (
                    set(left.selector) | set(right.selector)
                ) - {exclusive}
                if all(left.selector.get(key) == right.selector.get(key) for key in comparable_keys):
                    raise ValueError(
                        "conflicting hard demands for "
                        f"{identity}={left.selector[identity]!r}: "
                        f"{exclusive}={left.selector[exclusive]!r} vs {right.selector[exclusive]!r}"
                    )


def compile_demands(spec: EvalSpec) -> DemandSet:
    """Deterministically compile *spec* into normalized constructive demands."""

    from .eval_design import design_digest

    demands = _normalize(_from_requirements(spec) + _from_steps(spec))
    if not demands:
        raise ValueError(f"{spec.id}: eval compiled to no world demands")
    _reject_obvious_conflicts(demands)
    return DemandSet(eval_spec_id=spec.id, design_digest=design_digest(spec), demands=demands)


__all__ = ["DemandKind", "DemandSet", "WorldDemand", "compile_demands"]
