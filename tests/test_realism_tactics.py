from __future__ import annotations

from datetime import datetime

import pytest

from worldloom import RetailWorld
from worldloom.benchmarks.scenarios import NativeScenarioDemand, build_native_scenarios
from worldloom.benchmarks.tactics import NativeRealismProfile
from worldloom.evalrun.qualification import evidence_components
from worldloom.models import Authority, FormulaKind, Lifecycle
from worldloom.native_eval_bridge import native_task_cases
from worldloom.native_query_planning import NativeWorkloadPlan, plan_native_workload


@pytest.fixture(scope="module")
def source_world():
    return RetailWorld(seed=31).build()


def _case_facts(build, episode):
    return {identifier: build.world.facts.by_id(identifier) for identifier in episode.fact_ids}


def _totals(build, episode):
    return {fact.kind.rsplit(".", 1)[-1]: fact.value.amount
            for fact in _case_facts(build, episode).values() if ".total." in fact.kind and fact.value}


def test_absent_profile_retains_recipe_shape_and_presentation_preserves_truth(source_world) -> None:
    demand = NativeScenarioDemand(episodes=3)
    assert "realism" not in demand.model_dump(mode="json")
    original = build_native_scenarios(source_world, demand)
    changed = build_native_scenarios(source_world, demand.model_copy(update={"realism": NativeRealismProfile(
        decision_placement="back", row_order="reversed", comparison_detail="amounts", line_commentary="all")}))
    assert original.world._facts == changed.world._facts
    assert original.world._events == changed.world._events
    assert [episode.fact_ids for episode in original.episodes] == [episode.fact_ids for episode in changed.episodes]
    for before, after in zip(original.episodes, changed.episodes, strict=True):
        assert before.simulation_digest == after.simulation_digest
        metrics = after.realism
        assert metrics is not None
        assert metrics.decision_section_fraction == 1
        assert metrics.line_count == demand.rows_per_episode
        assert metrics.narrative_sections > 4
        assert metrics.formula_cells < before.formula_cells
        assert metrics.distinct_projected_facts == len(after.fact_ids)
        comparison = next(table for table in changed.world.artifact_irs.by_id(after.source_artifact_id).tables()
                          if table.key == "comparison")
        assert [row.key for row in comparison.rows] == ["line2", "line1", "line0", "total"]
        assert [column.key for column in comparison.columns] == ["actual", "budget"]
    changed.world.validate().raise_if_failed()
    changed.verify_source_replay()


@pytest.mark.parametrize("spread", ["lognormal", "zipf"])
def test_population_tactics_reconcile_and_do_not_count_variants_as_fresh_facts(source_world, spread) -> None:
    control = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(line_count=12)))
    changed = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(line_count=12, budget_spread=spread, exception_rate=0.25)))
    for before, after in zip(control.episodes, changed.episodes, strict=True):
        assert before.fact_ids == after.fact_ids
        old, new = before.realism, after.realism
        assert old is not None and new is not None
        assert new.line_count == 12
        assert new.exception_rows == 3
        assert new.realised_exception_rate == 0.25
        assert old.budget_total_minor_units == new.budget_total_minor_units
        assert old.largest_budget_share != new.largest_budget_share
        totals = _totals(changed, after)
        assert totals["budget"] == _totals(control, before)["budget"]
        if after.process == "supplier_reconciliation":
            assert totals["eligible"] == pytest.approx(totals["actual"] - totals["unreceipted"])
        elif after.process == "customer_settlement":
            assert totals["actual"] == pytest.approx(totals["rejected"] + totals["paid"] + totals["pending"])
        else:
            assert totals["shortage"] == totals["actual"] - totals["stock"] - totals["inbound"]
        assert all(fact.value is None or fact.value.amount >= 0 for fact in _case_facts(changed, after).values())
    changed.world.validate().raise_if_failed()
    changed.verify_source_replay()


@pytest.mark.parametrize("rate", [0.0, 1.0])
def test_population_boundaries_leave_formula_dag_valid(source_world, rate) -> None:
    built = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(line_count=64, budget_spread="lognormal", exception_rate=rate)))
    for episode in built.episodes:
        assert episode.realism.line_count == 64
        assert episode.realism.exception_rows == 64 * rate
        assert len(built.world.artifact_irs.by_id(episode.source_artifact_id).tables()[0].rows) == 65
    built.world.validate().raise_if_failed()


def test_presentation_streams_cannot_shift_population_draws(source_world) -> None:
    profile = NativeRealismProfile(line_count=12, budget_spread="lognormal", exception_rate=0.25)
    first = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3, realism=profile))
    second = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=profile.model_copy(update={"decision_placement": "varied", "row_order": "varied",
                                          "line_commentary": "largest_variance"})))
    assert first.world._facts == second.world._facts
    assert first.world._events == second.world._events
    assert [episode.simulation_digest for episode in first.episodes] == [episode.simulation_digest for episode in second.episodes]


def test_prevalence_counterfactual_keeps_existing_exception_members(source_world) -> None:
    builds = [build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(line_count=12, exception_rate=rate))) for rate in (0.25, 0.5)]
    for low, high in zip(builds[0].episodes, builds[1].episodes, strict=True):
        suffix = {"supplier_reconciliation": ".unreceipted", "customer_settlement": ".pending",
                  "inventory_replenishment": ".shortage"}[low.process]
        memberships = [{fact.id for fact in _case_facts(build, episode).values()
                        if ".line" in fact.kind and fact.kind.endswith(suffix) and fact.value.amount > 0}
                       for build, episode in zip(builds, (low, high), strict=True)]
        assert len(memberships[0]) == 3
        assert len(memberships[1]) == 6
        assert memberships[0] < memberships[1]


def test_historical_files_are_temporally_grounded_and_stay_in_their_case_family(source_world) -> None:
    built = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(revision_views=("opened", "reviewed"), row_order="varied",
                                     decision_placement="back", line_commentary="largest_variance")))
    built.world.validate().raise_if_failed()
    built.verify_source_replay()
    for episode in built.episodes:
        assert len(episode.companion_artifact_ids) == 2
        opened, reviewed = (built.world.artifacts.by_id(identifier) for identifier in episode.companion_artifact_ids)
        report = built.world.artifacts.by_id(episode.source_artifact_id)
        assert opened.authority is reviewed.authority is Authority.WORKING_DOCUMENT
        assert reviewed.revises == opened.id
        assert opened.lifecycle is Lifecycle.SUPERSEDED
        assert report.authority is Authority.APPROVED_REPORT
        assert report.derived_from == [reviewed.id]
        for identifier in episode.companion_artifact_ids:
            artifact = built.world.artifact_irs.by_id(identifier)
            cutoff = datetime.fromisoformat(artifact.metadata["created_at"])
            facts = [built.world.facts.by_id(fact_id) for fact_id in artifact.fact_ids()]
            assert all(fact.valid_from <= cutoff and (fact.valid_to is None or cutoff < fact.valid_to)
                       and (fact.tx_from is None or fact.tx_from <= cutoff) for fact in facts)
            assert not any(fact.text_value == "Approved for controlled execution" for fact in facts)
    rendered = built.render()
    assert len(rendered) == 27
    plan = NativeWorkloadPlan(use_case_id="realism-case-families", objective="Read, compare, update and create case evidence.",
        discovery_scope="artifact", max_tasks=144)
    workload = plan_native_workload(built.world, rendered, plan)
    assert workload.reference_qualified == len(workload.tasks)
    assert not workload.findings
    cases = native_task_cases(workload.tasks, rendered, world=built.world, namespace="realism")
    assert len(set(evidence_components(cases).values())) == 3
    rerendered = build_native_scenarios(source_world, built.demand).render()
    assert {key: value.payload for key, value in rendered.items()} == {key: value.payload for key, value in rerendered.items()}


def test_reduced_comparison_detail_preserves_actual_native_formula_semantics(source_world) -> None:
    built = build_native_scenarios(source_world, NativeScenarioDemand(episodes=3,
        realism=NativeRealismProfile(line_count=12, comparison_detail="amounts", row_order="varied",
            line_commentary="largest_variance", exception_rate=0.25, budget_spread="zipf")))
    rendered = built.render(formats=("xlsx",))
    workload = plan_native_workload(built.world, rendered, NativeWorkloadPlan(use_case_id="realism-formulas",
        objective="Reconcile allocation, update and create the case report.", discovery_scope="artifact", max_tasks=96))
    assert workload.reference_qualified == len(workload.tasks)
    assert not workload.findings
    for episode in built.episodes:
        formulas = {cell.formula for table in built.world.artifact_irs.by_id(episode.source_artifact_id).tables()
                    for row in table.rows for cell in row.cells.values()}
        assert FormulaKind.RATIO_PCT not in formulas
        assert {FormulaKind.SUM, FormulaKind.DIFFERENCE, FormulaKind.REFERENCE} <= formulas


@pytest.mark.parametrize("arguments", [
    {"line_count": 65}, {"line_count": True}, {"line_count": 2}, {"exception_rate": -0.1},
    {"exception_rate": 1.1}, {"exception_rate": True}, {"exception_rate": float("nan")},
    {"budget_spread": "gaussian"}, {"lognormal_sigma": 1.0}, {"zipf_exponent": 2.0},
    {"revision_views": ("opened", "opened")}, {"decision_placement": "page_200"}, {"ocr_noise": 0.2},
])
def test_unknown_unbounded_and_inert_tactics_refuse(arguments) -> None:
    with pytest.raises(ValueError):
        NativeRealismProfile(**arguments)
