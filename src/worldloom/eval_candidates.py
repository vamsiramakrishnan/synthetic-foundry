"""Candidate-world validation for eval-first generation.

The eval owns the requirements. Generators are free to satisfy those
requirements however their vertical needs, but a candidate is accepted only by
an independent pass over the completed World and its deterministic connector
projections.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .artifact_ecology import profile as realism_profile
from .connector_data import ConnectorRecord, builtin_projections
from .eval_design import (
    CandidatePlan,
    EvalSpec,
    RequirementKind,
    WorldRequirement,
    design_digest,
    plan_candidates,
)
from .eval_shape_validation import ShapeCheck, check_candidate_shape
from .models import Model
from .predicates import Predicate, evaluate

if TYPE_CHECKING:  # pragma: no cover
    from .artifact_ecology import RealismProfile
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
    shape_checks: tuple[ShapeCheck, ...] = ()


@dataclass(frozen=True)
class GeneratedCandidate:
    """A generated world plus the independent verdict on it."""

    plan: CandidatePlan
    world: World
    validation: CandidateValidation


CandidateBuilder = Callable[[CandidatePlan], "World"]


def _model_record(item: Any) -> dict[str, Any]:
    if hasattr(item, "model_dump"):
        return item.model_dump(mode="json")
    return vars(item)


def _predicate_record(item: Any) -> dict[str, Any]:
    """Flatten connector payload fields without letting them shadow the envelope."""

    record = item if isinstance(item, Mapping) else _model_record(item)
    nested = record.get("fields")
    if not isinstance(nested, Mapping):
        return dict(record)
    flattened = dict(nested)
    flattened.update(record)
    return flattened


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
    if world.recipe.get("artifact_realism") == "ecology/v1":
        from .artifact_ecology import enrich_connector_records

        records = enrich_connector_records(world, records)
    return records


def _flat_connector_records(world: World, connector: str) -> list[dict[str, Any]]:
    """*connector*'s projection of *world*, flattened for predicates, once per world.

    A world is immutable, so its projection is too; a company with hundreds
    of hard requirements used to project and serialise every record of the
    connector again for each one. Held in the world's own read cache
    (`World._collections`), which a derived world starts empty.
    """
    key = f"eval_candidates.connector:{connector}"
    cached = world._collections.get(key)
    if cached is None:
        cached = [_predicate_record(record) for record in _connector_records(world, connector)]
        world._collections[key] = cached
    return cached


def _selector_predicate(selector: Mapping[str, str | int | bool]) -> Predicate:
    """Compile the legacy declarative selector to the shared predicate language."""

    return Predicate.equalities(selector)


def _check_records(
    requirement: WorldRequirement,
    records: Iterable[Any],
    *,
    id_field: str = "id",
    flattened: bool = False,
) -> RequirementCheck:
    predicate = _selector_predicate(requirement.selector)
    matches: list[str] = []
    for item in records:
        record = item if flattened else _predicate_record(item)
        if evaluate(predicate, record):
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
    predicate = _selector_predicate(requirement.selector)
    eligible = {
        artifact_id
        for artifact_id, record in artifacts.items()
        if evaluate(predicate, record)
    }
    predecessors = {
        intent.id: intent.revises
        for intent in world.artifact_intents
        if intent.id in eligible and intent.revises in eligible
    }
    longest: tuple[str, ...] = ()
    for artifact_id in sorted(eligible):
        chain: list[str] = [artifact_id]
        seen = {artifact_id}
        cursor = artifact_id
        while True:
            predecessor = predecessors.get(cursor)
            if predecessor is None or predecessor in seen:
                break
            cursor = predecessor
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
    selector = dict(requirement.selector)
    edge_kind = selector.pop("edge_kind", None)
    if edge_kind is not None:
        selector["kind"] = edge_kind
    predicate = _selector_predicate(selector)
    edges = [
        edge
        for edge in realism.graph.edges
        if evaluate(predicate, _model_record(edge))
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

    if requirement.kind == RequirementKind.FACT:
        return _check_records(requirement, world.facts)
    if requirement.kind == RequirementKind.EVENT:
        return _check_records(requirement, world.events)
    if requirement.kind in {RequirementKind.ARTIFACT, RequirementKind.DISTRACTOR}:
        realism = realism or realism_profile(world)
        return _check_records(requirement, _artifact_records(world, realism))
    if requirement.kind == RequirementKind.PERMISSION:
        return _check_records(requirement, world.access_policies)
    if requirement.kind == RequirementKind.REVISION_CHAIN:
        realism = realism or realism_profile(world)
        return _check_revision_chain(requirement, world, realism)
    if requirement.kind == RequirementKind.TEMPORAL_RELATION:
        realism = realism or realism_profile(world)
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
            records = _flat_connector_records(world, connector)
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
        return _check_records(narrowed, records, flattened=True)
    raise AssertionError(f"unhandled requirement kind {requirement.kind}")


def validate_candidate(plan: CandidatePlan, spec: EvalSpec, world: World) -> CandidateValidation:
    """Check that *world* really instantiates the eval it was generated for."""

    if plan.eval_spec_id != spec.id:
        raise ValueError(
            f"candidate plan belongs to {plan.eval_spec_id!r}, not eval {spec.id!r}"
        )
    if world.seed != plan.seed:
        raise ValueError(
            f"candidate world seed {world.seed!r} does not match plan seed {plan.seed}"
        )
    if (plan.design_digest != design_digest(spec) or plan.requirements != spec.requirements
            or plan.shape != spec.shape):
        raise ValueError("candidate plan does not match the immutable eval design")
    # Structured evidence does not require a document compiler. Share ecology
    # only for requirements that actually inspect its lifecycle or graph.
    ecology_kinds = {RequirementKind.ARTIFACT, RequirementKind.DISTRACTOR,
                    RequirementKind.REVISION_CHAIN, RequirementKind.TEMPORAL_RELATION}
    realism = (realism_profile(world)
               if any(r.kind in ecology_kinds for r in plan.requirements) else None)
    checks = tuple(
        check_requirement(requirement, world, realism=realism)
        for requirement in plan.requirements
    )
    hard = {requirement.id: requirement.hard for requirement in plan.requirements}
    shape_checks = check_candidate_shape(plan.shape, world, project=lambda name: _connector_records(world, name))
    coherence = world.validate()
    accepted = coherence.ok and all(check.satisfied for check in shape_checks) and all(
        check.satisfied or not hard[check.requirement_id] for check in checks
    )
    return CandidateValidation(
        eval_spec_id=spec.id,
        candidate_seed=plan.seed,
        accepted=accepted,
        checks=checks,
        shape_checks=shape_checks,
    )


def generate_candidates(
    spec: EvalSpec,
    builder: CandidateBuilder,
    *,
    count: int | None = None,
    keep_rejected: bool = False,
) -> tuple[GeneratedCandidate, ...]:
    """Generate candidate worlds *after* the eval and retain only valid ones."""

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
