"""Reference proofs derive outputs from executed reads, never oracle injection."""

from __future__ import annotations

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.connector_emulator import ConnectorEmulator
from worldloom.eval_candidates import _connector_records
from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.eval_instances import EvalAssertion
from worldloom.eval_reference import ExecutionStep, ProofStatus, execute_reference
from worldloom.evals import EvalCampaign, emulator_executor
from worldloom.predicates import Predicate
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


def _campaign(*steps: EvalStepSpec):  # type: ignore[no-untyped-def]
    spec = EvalSpec(
        id="source-proof-integrity",
        capability="cross_source_retrieval",
        persona="operations manager",
        request_template="Find the critical incident and the urgent bridge message.",
        steps=steps or (
            EvalStepSpec(id="incidents", capability="search", connector="servicenow",
                         entity="incident", operation="search"),
            EvalStepSpec(id="messages", capability="search", connector="teams",
                         entity="channel_message", operation="search", depends_on=("incidents",)),
        ),
        requirements=(
            WorldRequirement(id="critical", kind=RequirementKind.CONNECTOR,
                             selector={"connector": "servicenow", "entity": "incident", "priority": "1 - Critical"}),
            WorldRequirement(id="urgent", kind=RequirementKind.CONNECTOR,
                             selector={"connector": "teams", "entity": "channel_message", "importance": "urgent"}),
            # This is a static corpus requirement, not a promise that each
            # source will retrieve all financial facts in the company.
            WorldRequirement(id="workbook", kind=RequirementKind.ARTIFACT,
                             selector={"artifact_type": "finance_workbook"}),
        ),
        candidate_count=1,
    )
    return EvalCampaign(spec).construct(
        lambda plan: RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03")),
    )


def test_cross_connector_steps_prove_only_their_own_source_evidence() -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    proof = execute_reference(instance, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_EXECUTABLE, proof.failure
    observed = {step.step_id: set(step.output_ids) for step in proof.steps}
    scoped = {assertion.step_id: set(assertion.evidence_ids) for assertion in instance.assertions
              if assertion.type == "capability_invoked"}
    assert scoped["incidents"] and scoped["messages"]
    assert scoped["incidents"].isdisjoint(scoped["messages"])
    assert scoped["incidents"] <= observed["incidents"]
    assert scoped["messages"] <= observed["messages"]
    assert scoped["messages"].isdisjoint(observed["incidents"])
    assert instance.oracle.fact_ids, "the static workbook contributes canonical facts"
    assert set(instance.oracle.fact_ids).isdisjoint(observed["incidents"] | observed["messages"])


@pytest.mark.parametrize("page_size", [7, 50])
def test_search_proof_reads_every_page_of_each_witness_selector(
    monkeypatch: pytest.MonkeyPatch, page_size: int,
) -> None:
    spec = EvalSpec(
        id="paginated-source-proof", capability="incident_inventory", persona="operations manager",
        request_template="Find all new critical incidents for the critical desk and high-priority incidents for the high desk.",
        steps=(EvalStepSpec(id="incidents", capability="search", connector="servicenow",
                            entity="incident", operation="search"),),
        requirements=tuple(WorldRequirement(
            id=label, kind=RequirementKind.CONNECTOR, minimum=count,
            selector={"connector": "servicenow", "entity": "incident", "priority": priority,
                      "state": "New", "assignment_group": label + " desk"},
        ) for label, priority, count in (("critical", "1 - Critical", 101), ("high", "2 - High", 57))),
        candidate_count=1,
    )
    run = EvalCampaign(spec).construct(
        lambda plan: RetailWorld(seed=plan.seed).build().run(MonthEndClose(period="2026-03")),
    )
    world, instance = run.accepted[0].world, run.instances[0]
    definition = load_connector_definition("servicenow")
    tool = definition.tool_for("incident", "search")
    definition = definition.model_copy(update={"tools": {
        **definition.tools, tool: definition.tools[tool].model_copy(update={"page_size": page_size}),
    }})
    pages: dict[str, list[tuple[int, int, int, bool, tuple[str, ...]]]] = {}
    original_call = ConnectorEmulator.call

    def observe_call(emulator, tool_name, **args):  # type: ignore[no-untyped-def]
        result = original_call(emulator, tool_name, **args)
        if args.get("_node") == "incidents":
            selector = args["predicate"].model_dump_json()
            pages.setdefault(selector, []).append((result["start_at"], result["max_results"],
                result["total"], result["is_last"], tuple(emulator.trace[-1].reads)))
        return result

    monkeypatch.setattr(ConnectorEmulator, "call", observe_call)
    proof = execute_reference(instance, world, emulator_executor({"servicenow": definition}))
    assert proof.status == ProofStatus.PROVEN_EXECUTABLE, proof.failure
    assert len(pages) == 2, "each independently scoped selector must start its own pagination"
    for selector_pages in pages.values():
        assert len(selector_pages) > 1
        assert [page[0] for page in selector_pages] == list(range(0, selector_pages[0][2], page_size))
        assert all(page[1] == page_size for page in selector_pages)
        assert all(not page[3] for page in selector_pages[:-1]) and selector_pages[-1][3]
        assert sum(len(page[4]) for page in selector_pages) == selector_pages[0][2]
    actual_reads = {fid for selector_pages in pages.values() for page in selector_pages for fid in page[4]}
    records = _connector_records(world, "servicenow")
    required = {record.id for record in records if record.fields.get("witness_role") == "witness"}
    near_misses = {record.id for record in records if record.fields.get("witness_role") == "near_miss"}
    assert len(required) == 158
    assert required <= actual_reads
    assert actual_reads.isdisjoint(near_misses)
    provenance = {identifier for record in records if record.id in actual_reads
                  for identifier in (*record.fact_ids, *record.event_ids, *record.source_artifact_ids)}
    assert set(proof.steps[0].output_ids) == actual_reads | provenance


def test_oracle_mutation_cannot_supply_missing_read_evidence() -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    unrelated = instance.oracle.fact_ids[0]
    strengthened = instance.model_copy(update={
        "oracle": instance.oracle.model_copy(update={"fact_ids": (unrelated,)}),
        "assertions": (*instance.assertions, EvalAssertion(
            type="capability_invoked", step_id="incidents", operation="search", evidence_ids=(unrelated,),
        )),
    })
    proof = execute_reference(strengthened, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert unrelated not in proof.steps[0].output_ids
    assert any(result.assertion_type == "capability_invoked" and not result.passed
               for result in proof.assertion_results)


def test_irrelevant_nonempty_search_hits_do_not_prove_required_evidence(monkeypatch: pytest.MonkeyPatch) -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    # Near misses exist on the same surface and match every clause except
    # priority. The query succeeds, but the required incident is absent.
    monkeypatch.setattr("worldloom.eval_execution._witness_predicates", lambda _world, connector, _entity: (
        [Predicate.equalities({"witness_role": "near_miss"}, entity="incident")]
        if connector == "servicenow" else [Predicate.equalities({"importance": "urgent"}, entity="channel_message")]
    ))
    proof = execute_reference(instance, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert proof.steps[0].output_ids, "successful irrelevant hits must not be credited as relevant"
    assert any(result.assertion_type == "capability_invoked" and not result.passed
               for result in proof.assertion_results)


@pytest.mark.parametrize("operation", ["get", "search"])
def test_missing_selector_match_refuses_instead_of_falling_back_to_pool(
    monkeypatch: pytest.MonkeyPatch, operation: str,
) -> None:
    run = _campaign(EvalStepSpec(id="incidents", capability="read", connector="servicenow",
                                entity="incident", operation=operation))
    world, instance = run.accepted[0].world, run.instances[0]
    monkeypatch.setattr("worldloom.eval_execution._witness_predicates", lambda *_args: [
        Predicate.equalities({"priority": "no such priority"}, entity="incident"),
    ])
    proof = execute_reference(instance, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert not proof.steps
    assert "found nothing" in proof.failure or "no servicenow/incident record" in proof.failure


@pytest.mark.parametrize("effect", ["read", "transform", "verify", "write"])
def test_connectorless_semantics_require_a_custom_executor(effect: str) -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    step = EvalStepSpec(id="unimplemented", capability="reconcile", effect=effect)  # type: ignore[arg-type]
    changed = instance.model_copy(update={"steps": (step,)})
    proof = execute_reference(changed, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert not proof.steps
    assert "caller-supplied StepExecutor" in proof.failure


def test_unsupported_connector_transform_is_not_proven_by_a_search() -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    step = EvalStepSpec(id="unimplemented", capability="reconcile", operation="reconcile",
                        connector="servicenow", entity="incident", effect="transform")
    changed = instance.model_copy(update={"steps": (step,)})
    proof = execute_reference(changed, world, emulator_executor())
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert "unsupported transform operation" in proof.failure


@pytest.mark.parametrize("effect", ["read", "transform", "verify"])
def test_custom_executor_requires_outputs_even_when_no_source_ids_are_bound(effect: str) -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    step = EvalStepSpec(id="custom", capability="find", operation="find", effect=effect)  # type: ignore[arg-type]
    changed = instance.model_copy(update={"steps": (step,), "assertions": (
        EvalAssertion(type="capability_invoked", step_id=step.id, operation="find"),
    )})

    def empty_executor(current, declaration, _bound):  # type: ignore[no-untyped-def]
        return current, ExecutionStep(step_id=declaration.id, operation="find", effect_ids=("an-effect",))

    empty = execute_reference(changed, world, empty_executor)
    assert empty.status == ProofStatus.PROVEN_UNSAT
    assert not empty.assertion_results[0].passed

    def observed_executor(current, declaration, _bound):  # type: ignore[no-untyped-def]
        # An explicit executor reads its own source rather than filling its
        # outputs from the evaluation oracle. Its nonempty result is required
        # even when the assertion has no connector-specific ID binding.
        observed = next(iter(current.facts)).id
        return current, ExecutionStep(step_id=declaration.id, operation="find", output_ids=(observed,))

    observed = execute_reference(changed, world, observed_executor)
    assert observed.status == ProofStatus.PROVEN_EXECUTABLE
    assert observed.steps[0].output_ids


@pytest.mark.parametrize("readback", [(), ("unrelated-record",)])
def test_verification_must_observe_the_write_it_depends_on(readback: tuple[str, ...]) -> None:
    run = _campaign()
    world, instance = run.accepted[0].world, run.instances[0]
    changed = instance.model_copy(update={
        "steps": (
            EvalStepSpec(id="write", capability="create", connector="jira", effect="write"),
            EvalStepSpec(id="check", capability="get", connector="jira", effect="verify", depends_on=("write",)),
        ),
        "assertions": (
            EvalAssertion(type="side_effect_occurred", step_id="write"),
            EvalAssertion(type="verification_performed", step_id="check"),
        ),
    })

    def executor(current, step, _bound):  # type: ignore[no-untyped-def]
        return current, ExecutionStep(step_id=step.id, operation=step.capability,
                                      effect_ids=("written-record",) if step.id == "write" else (),
                                      output_ids=readback if step.id == "check" else ())

    proof = execute_reference(changed, world, executor)
    assert proof.status == ProofStatus.PROVEN_UNSAT
    assert any(result.assertion_type == "verification_performed" and not result.passed
               for result in proof.assertion_results)
