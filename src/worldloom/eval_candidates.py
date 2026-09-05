"""Candidate-world validation for eval-first generation.

The eval owns the requirements.  Generators are free to satisfy those
requirements however their vertical needs, but a candidate is accepted only by
an independent pass over the completed World and its deterministic connector
projections.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .artifact_ecology import RealismProfile, profile as realism_profile
from .connector_data import ConnectorRecord, builtin_projections
from .eval_design import (
    CandidatePlan,
    EvalSpec,
    RequirementKind,
    WorldRequirement,
    plan_candidates,
)
from .models import Model

if TYPE_CHECKING:  # pragma: no cover
    from .world import World


class RequirementCheck(Model):
    requirement_id: str
    satisfied: bool
    observed: int
    required: int
    evidence_ids: tuple[str, ...] = ()
    detail: str = ""


class CandidateValidation(Model):
    eval_spec_id: str
    candidate_seed: int
    accepted: bool
    checks: tuple[RequirementCheck, ...]


@dataclass(frozen=True)
class GeneratedCandidate:
    """A generated world plus the independent verdict on it."""

    plan: CandidatePlan
    world: World
    validation: CandidateValidation


CandidateBuilder = Callable[[CandidatePlan], "World"]


def _scalar(value: Any) -> Any:
    return getattr(value, "value", value)


def _matches(record: Mapping[str, Any], selector: Mapping[str, str | int | bool]) -> bool:
    for key, expected in selector.items():
        if key == "connector":
            continue
        actual = record.get(key)
        if _scalar(actual) != expected:
            return False
    return True


def _model_record(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="python")
    return vars(item)


def _artifact_records(world: World, realism: RealismProfile) -> list[dict[str, Any]]:
    lifecycle = {item.artifact_id: item for item in realism.lifecycles}
    records: list[dict[str, Any]] = []
    for intent in world.artifact_intents:
        record = _model_record(intent)
        life = lifecycle.get(intent.id)
        if life is not None:
            record.update(
                lifecycle=life.current.value,
                revision=life.revision,
                predecessor_id=life.predecessor_id,
            )
        records.append(record)
    return records


def _connector_records(world: World, connector: str) -> list[ConnectorRecord]:
    records = builtin_projections().project(connector, world)
    # Artifact ecology only enriches workflow detail; it does not mint evidence.
    if world.recipe.get("artifact_realism") == "ecology/v1":
        from .artifact_ecology import enrich_connector_records

        records = enrich_connector_records(world, records)
    return records


def _check_records(
    requirement: WorldRequirement,
    records: Iterable[Any],
    *,
    id_field: str = "id",
) -> RequirementCheck:
    matches: list[str] = []
    for item in records:
        record = item if isinstance(item, Mapping) else _model_record(item)
        if _matches(record, requirement.selector):
            identifier = record.get(id_field) or record.get("external_id") or "evidence"
            matches.append(str(identifier))
    observed = len(matches)
    return RequirementCheck(
        requirement_id=requirement.id,
        satisfied=observed >= requirement.minimum,
        observed=observed,
        required=requirement.minimum,
        evidence_ids=tuple(sorted(matches)),
    )


def _check_revision_chain(
    requirement: WorldRequirement,
    world: World,
    realism: RealismProfile,
) -> RequirementCheck:
    artifacts = {record["id"]: record for record in _artifact_records(world, realism)}
    eligible = {
        artifact_id
        for artifact_id, record in artifacts.items()
        if _matches(record, requirement.selector)
    }
    predecessors = {
        item.artifact_id: item.predecessor_id
        for item in realism.lifecycles
        if item.artifact_id in eligible and item.predecessor_id in eligible
    }
    longest: tuple[str, ...] = ()
    for artifact_id in sorted(eligible):
        chain: list[str] = [artifact_id]
        seen = {artifact_id}
        cursor = artifact_id
        while predecessors.get(cursor) and predecessors[cursor] not in seen:
            cursor = predecessors[cursor]  # type: ignore[assignment]
            seen.add(cursor)
            chain.append(cursor)
        candidate = tuple(reversed(chain))
        if len(candidate) > len(longest):
            longest = candidate
    return RequirementCheck(
        requirement_id=requirement.id,
        satisfied=len(longest) >= requirement.minimum,
        observed=len(longest),
        required=requirement.minimum,
        evidence_ids=longest,
        detail="longest matching artifact revision chain",
    )


def _check_temporal_relation(
    requirement: WorldRequirement, realism: RealismProfile
) -> RequirementCheck:
    edge_kind = requirement.selector.get("edge_kind")
    edges = [
        edge
        for edge in realism.graph.edges
        if edge_kind is None or edge.kind == edge_kind
    ]
    observed = len(edges)
    evidence = tuple(f"{edge.source}->{edge.target}:{edge.kind}" for edge in edges)
    return RequirementCheck(
        requirement_id=requirement.id,
        satisfied=observed >= requirement.minimum,
        observed=observed,
        required=requirement.minimum,
        evidence_ids=evidence,
    )


def check_requirement(
    requirement: WorldRequirement,
    world: World,
    *,
    realism: RealismProfile | None = None,
) -> RequirementCheck:
    """Evaluate one declarative requirement against a completed candidate."""

    realism = realism or realism_profile(world)
    if requirement.kind == RequirementKind.FACT:
        return _check_records(requirement, world.facts)
    if requirement.kind == RequirementKind.EVENT:
        return _check_records(requirement, world.events)
    if requirement.kind in {RequirementKind.ARTIFACT, RequirementKind.DISTRACTOR}:
        return _check_records(requirement, _artifact_records(world, realism))
    if requirement.kind == RequirementKind.PERMISSION:
        return _check_records(requirement, world.access_policies)
    if requirement.kind == RequirementKind.REVISION_CHAIN:
        return _check_revision_chain(requirement, world, realism)
    if requirement.kind == RequirementKind.TEMPORAL_RELATION:
        return _check_temporal_relation(requirement, realism)
    if requirement.kind == RequirementKind.CONNECTOR:
        connector = requirement.selector.get("connector")
        if not isinstance(connector, str) or not connector:
            return RequirementCheck(
                requirement_id=requirement.id,
                satisfied=False,
                observed=0,
                required=requirement.minimum,
                detail="connector requirement needs selector.connector",
            )
        try:
            records = _connector_records(world, connector)
        except ValueError as error:
            return RequirementCheck(
                requirement_id=requirement.id,
                satisfied=False,
                observed=0,
                required=requirement.minimum,
                detail=str(error),
            )
        selector = dict(requirement.selector)
        selector.pop("connector", None)
        narrowed = requirement.model_copy(update={"selector": selector})
        return _check_records(narrowed, records)
    raise AssertionError(f"unhandled requirement kind {requirement.kind}")


def validate_candidate(plan: CandidatePlan, spec: EvalSpec, world: World) -> CandidateValidation:
    """Check that *world* really instantiates the eval it was generated for."""

    if plan.eval_spec_id != spec.id:
        raise ValueError(
            f"candidate plan belongs to {plan.eval_spec_id!r}, not eval {spec.id!r}"
        )
    realism = realism_profile(world)
    checks = tuple(
        check_requirement(requirement, world, realism=realism)
        for requirement in plan.requirements
    )
    hard = {requirement.id: requirement.hard for requirement in plan.requirements}
    accepted = all(check.satisfied or not hard[check.requirement_id] for check in checks)
    return CandidateValidation(
        eval_spec_id=spec.id,
        candidate_seed=plan.seed,
        accepted=accepted,
        checks=checks,
    )


def generate_candidates(
    spec: EvalSpec,
    builder: CandidateBuilder,
    *,
    count: int | None = None,
    keep_rejected: bool = False,
) -> tuple[GeneratedCandidate, ...]:
    """Generate candidate worlds *after* the eval and retain only valid ones.

    The builder receives the complete candidate plan, including its deterministic
    seed and world predicates.  It may use a normal vertical builder, an
    evolutionary harness, or a bespoke scenario compiler.  Acceptance remains
    here, outside that generator.
    """

    generated: list[GeneratedCandidate] = []
    for plan in plan_candidates(spec, count=count):
        world = builder(plan)
        validation = validate_candidate(plan, spec, world)
        candidate = GeneratedCandidate(plan=plan, world=world, validation=validation)
        if validation.accepted or keep_rejected:
            generated.append(candidate)
    return tuple(generated)


__all__ = [
    "CandidateBuilder",
    "CandidateValidation",
    "GeneratedCandidate",
    "RequirementCheck",
    "check_requirement",
    "generate_candidates",
    "validate_candidate",
]
