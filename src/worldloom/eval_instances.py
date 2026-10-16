"""Bind an accepted candidate world into a concrete evaluation instance.

Assertions are derived from the task skeleton and the evidence that satisfied the
world predicates.  They are never authored separately from the eval design.  The
completed World is the oracle: concrete fact, event, artifact and connector ids
appear only at this stage.
"""

from __future__ import annotations

import hashlib
from typing import TYPE_CHECKING, Literal

from .connector_data import builtin_projections
from .eval_candidates import GeneratedCandidate
from .eval_design import EvalSpec, EvalStepSpec, RequirementKind
from .models import Model

if TYPE_CHECKING:
    from .world import World


class EvalAssertion(Model):
    type: Literal[
        "dag_acyclic",
        "order",
        "capability_invoked",
        "side_effect_occurred",
        "verification_performed",
        "world_requirement_satisfied",
        "evidence_grounded",
    ]
    step_id: str | None = None
    before: str | None = None
    after: str | None = None
    capability: str | None = None
    connector: str | None = None
    operation: str | None = None
    requirement_id: str | None = None
    evidence_ids: tuple[str, ...] = ()


class EvalOracle(Model):
    fact_ids: tuple[str, ...] = ()
    event_ids: tuple[str, ...] = ()
    artifact_ids: tuple[str, ...] = ()
    connector_record_ids: tuple[str, ...] = ()
    permission_ids: tuple[str, ...] = ()
    relation_evidence: tuple[str, ...] = ()
    evidence_by_requirement: dict[str, tuple[str, ...]]


class EvalInstance(Model):
    id: str
    spec_id: str
    candidate_seed: int
    design_digest: str
    capability: str
    persona: str
    request: str
    difficulty: str
    steps: tuple[EvalStepSpec, ...]
    assertions: tuple[EvalAssertion, ...]
    oracle: EvalOracle


def _instance_id(spec: EvalSpec, candidate: GeneratedCandidate) -> str:
    digest = hashlib.sha256(
        f"{candidate.plan.design_digest}\0{candidate.plan.seed}\0{spec.id}".encode()
    ).hexdigest()
    return f"EVAL-{digest[:16].upper()}"


def _assertions(
    spec: EvalSpec,
    evidence: dict[str, tuple[str, ...]],
    fact_ids: tuple[str, ...],
    step_evidence: dict[str, tuple[str, ...]],
) -> tuple[EvalAssertion, ...]:
    assertions: list[EvalAssertion] = [EvalAssertion(type="dag_acyclic")]
    for step in spec.steps:
        for dependency in step.depends_on:
            assertions.append(EvalAssertion(type="order", before=dependency, after=step.id))
        assertions.append(
            EvalAssertion(
                type="capability_invoked",
                step_id=step.id,
                capability=step.capability,
                connector=step.connector,
                operation=step.operation,
                # World requirements describe corpus conditions. A source
                # operation must retrieve its own bound records and their
                # provenance, not every fact another source contributed to
                # the instance's global oracle.
                evidence_ids=step_evidence.get(step.id, ()),
            )
        )
        if step.effect == "write":
            assertions.append(EvalAssertion(type="side_effect_occurred", step_id=step.id))
        elif step.effect == "verify":
            assertions.append(EvalAssertion(type="verification_performed", step_id=step.id))
    for requirement in spec.requirements:
        assertions.append(
            EvalAssertion(
                type="world_requirement_satisfied",
                requirement_id=requirement.id,
                evidence_ids=evidence.get(requirement.id, ()),
            )
        )
    if fact_ids:
        assertions.append(EvalAssertion(type="evidence_grounded", evidence_ids=fact_ids))
    return tuple(assertions)


def _step_evidence(
    spec: EvalSpec,
    world: World,
    evidence: dict[str, tuple[str, ...]],
) -> dict[str, tuple[str, ...]]:
    """Bind source requirements to the connector and entity that reads them.

    Search steps promise the required result set. A single-record read promises
    one required record; its reference executor uses that binding to choose the
    gold call, then proves the evidence actually came back. Verification after
    a write is checked against observed effects rather than the initial source
    requirement. Other requirements remain static world conditions.
    """
    from .connector_definition import is_reference_connector, load_connector_definition
    from .eval_candidates import _connector_records

    scoped: dict[str, tuple[str, ...]] = {}
    for step in spec.steps:
        if step.connector is None or step.effect != "read":
            continue
        if not is_reference_connector(step.connector):
            continue
        definition = load_connector_definition(step.connector)
        records = _connector_records(world, step.connector)
        members = set(definition.entity_members(step.entity)) if step.entity else None
        required = {
            identifier for requirement in spec.requirements
            if requirement.kind == RequirementKind.CONNECTOR
            and requirement.selector.get("connector") == step.connector
            and (members is None or not isinstance(requirement.selector.get("entity"), str)
                 or bool(members & set(definition.entity_members(str(requirement.selector["entity"])))))
            for identifier in evidence[requirement.id]
        }
        if (step.operation or step.capability).lower() in {"get", "read", "download", "extract"}:
            required = set(sorted(required)[:1])
        selected = sorted(
            (record for record in records if record.id in required
             and (members is None or record.entity in members)),
            key=lambda record: record.id,
        )
        if required:
            # Keep mandatory record IDs even if a caller hands binding a stale
            # validation snapshot: absence cannot turn a required read into an
            # evidence-free capability assertion.
            scoped[step.id] = tuple(sorted(required | {
                identifier for record in selected
                for identifier in (record.id, *record.fact_ids, *record.event_ids, *record.source_artifact_ids)
            }))
    return scoped


def bind_eval_instance(spec: EvalSpec, candidate: GeneratedCandidate) -> EvalInstance:
    """Turn one accepted candidate into the concrete, gradeable eval.

    Binding refuses a world built under a different seed.  A candidate builder
    therefore cannot ignore the plan and accidentally attach an unrelated corpus
    to a valid eval specification.
    """

    if not candidate.validation.accepted:
        raise ValueError("cannot bind a rejected candidate")
    if candidate.plan.eval_spec_id != spec.id:
        raise ValueError(
            f"candidate belongs to {candidate.plan.eval_spec_id!r}, not {spec.id!r}"
        )
    if candidate.world.seed != candidate.plan.seed:
        raise ValueError(
            f"candidate world seed {candidate.world.seed!r} does not match plan seed {candidate.plan.seed}"
        )

    checks = {check.requirement_id: check for check in candidate.validation.checks}
    evidence = {
        requirement.id: checks[requirement.id].evidence_ids
        for requirement in spec.requirements
    }

    fact_ids: set[str] = set()
    event_ids: set[str] = set()
    artifact_ids: set[str] = set()
    connector_ids: set[str] = set()
    permission_ids: set[str] = set()
    relation_evidence: set[str] = set()

    for requirement in spec.requirements:
        ids = set(evidence[requirement.id])
        if requirement.kind == RequirementKind.FACT:
            fact_ids.update(ids)
        elif requirement.kind == RequirementKind.EVENT:
            event_ids.update(ids)
        elif requirement.kind in {
            RequirementKind.ARTIFACT,
            RequirementKind.DISTRACTOR,
            RequirementKind.REVISION_CHAIN,
        }:
            artifact_ids.update(ids)
        elif requirement.kind == RequirementKind.CONNECTOR:
            connector_ids.update(ids)
        elif requirement.kind == RequirementKind.PERMISSION:
            permission_ids.update(ids)
        elif requirement.kind == RequirementKind.TEMPORAL_RELATION:
            relation_evidence.update(ids)

    # Evidence closure: artifact and connector requirements imply the canonical
    # facts those records carry.  The grader therefore receives truth ids rather
    # than having to trust a document's prose as an oracle.
    for artifact_id in artifact_ids:
        intent = candidate.world.artifact_intents.get(artifact_id)
        if intent is not None:
            fact_ids.update(intent.required_fact_ids)

    for event_id in event_ids:
        fact_ids.update(fact.id for fact in candidate.world.facts if fact.event_id == event_id)

    connector_names = {
        requirement.selector.get("connector")
        for requirement in spec.requirements
        if requirement.kind == RequirementKind.CONNECTOR
    }
    for connector in sorted(name for name in connector_names if isinstance(name, str)):
        for record in builtin_projections().project(connector, candidate.world):
            if record.id in connector_ids:
                fact_ids.update(record.fact_ids)
                event_ids.update(record.event_ids)
                artifact_ids.update(record.source_artifact_ids)

    reachable_facts = set(candidate.world.facts.ids())
    fact_ids.intersection_update(reachable_facts)

    oracle = EvalOracle(
        fact_ids=tuple(sorted(fact_ids)),
        event_ids=tuple(sorted(event_ids)),
        artifact_ids=tuple(sorted(artifact_ids)),
        connector_record_ids=tuple(sorted(connector_ids)),
        permission_ids=tuple(sorted(permission_ids)),
        relation_evidence=tuple(sorted(relation_evidence)),
        evidence_by_requirement=evidence,
    )
    return EvalInstance(
        id=_instance_id(spec, candidate),
        spec_id=spec.id,
        candidate_seed=candidate.plan.seed,
        design_digest=candidate.plan.design_digest,
        capability=spec.capability,
        persona=spec.persona,
        request=spec.request_template,
        difficulty=spec.difficulty,
        steps=spec.steps,
        assertions=_assertions(spec, evidence, oracle.fact_ids, _step_evidence(spec, candidate.world, evidence)),
        oracle=oracle,
    )


__all__ = [
    "EvalAssertion",
    "EvalInstance",
    "EvalOracle",
    "bind_eval_instance",
]
