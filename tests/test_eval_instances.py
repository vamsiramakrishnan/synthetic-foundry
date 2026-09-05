from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom.eval_candidates import GeneratedCandidate, generate_candidates
from worldloom.eval_design import EvalSpec, EvalStepSpec, RequirementKind, WorldRequirement
from worldloom.eval_instances import bind_eval_instance
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _spec() -> EvalSpec:
    return EvalSpec(
        id="EVALSPEC-ORACLE-BINDING",
        capability="cross_connector_evidence",
        persona="service delivery lead",
        request_template="Find the operational evidence, reconcile it, and verify the result.",
        steps=(
            EvalStepSpec(
                id="read-email",
                capability="message_search",
                connector="email",
                operation="search",
            ),
            EvalStepSpec(
                id="reconcile",
                capability="evidence_reconcile",
                depends_on=("read-email",),
                effect="transform",
            ),
            EvalStepSpec(
                id="verify",
                capability="read_after_write",
                depends_on=("reconcile",),
                effect="verify",
            ),
        ),
        requirements=(
            WorldRequirement(id="canonical-facts", kind=RequirementKind.FACT, minimum=1),
            WorldRequirement(
                id="email-record",
                kind=RequirementKind.CONNECTOR,
                selector={"connector": "email", "entity": "message"},
                minimum=1,
            ),
        ),
        candidate_count=1,
    )


def _builder(plan):  # type: ignore[no-untyped-def]
    return RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03"))


def test_binding_derives_assertions_from_design_and_evidence() -> None:
    spec = _spec()
    candidate = generate_candidates(spec, _builder)[0]

    instance = bind_eval_instance(spec, candidate)

    kinds = [assertion.type for assertion in instance.assertions]
    assert kinds[0] == "dag_acyclic"
    assert kinds.count("order") == 2
    assert kinds.count("capability_invoked") == 3
    assert "verification_performed" in kinds
    assert kinds.count("world_requirement_satisfied") == len(spec.requirements)
    assert "evidence_grounded" in kinds
    assert instance.oracle.fact_ids
    assert instance.oracle.connector_record_ids
    assert set(instance.oracle.fact_ids) <= set(candidate.world.facts.ids())


def test_binding_is_deterministic_for_same_candidate() -> None:
    spec = _spec()
    candidate = generate_candidates(spec, _builder)[0]

    assert bind_eval_instance(spec, candidate) == bind_eval_instance(spec, candidate)


def test_binding_refuses_builder_that_ignored_candidate_seed() -> None:
    spec = _spec()
    candidate = generate_candidates(spec, _builder)[0]
    wrong_world = replace(candidate.world, seed=(candidate.plan.seed + 1))
    wrong = GeneratedCandidate(
        plan=candidate.plan,
        world=wrong_world,
        validation=candidate.validation,
    )

    with pytest.raises(ValueError, match="does not match plan seed"):
        bind_eval_instance(spec, wrong)
