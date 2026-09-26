"""Autopsy, curriculum and escalation: failures become findings, findings become fresh cases.

Every result here comes from the real grading path (a scripted or reference
agent through the tool surface), so the keys under test are the keys a real
run produces. Where a test needs a distribution the small corpus cannot
supply (thirty passes on one slice, a failure kind the grammar refuses), it
relabels real graded results rather than inventing a score.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from typer.testing import CliRunner

from worldloom import RetailWorld
from worldloom.cli import app
from worldloom.connector_definition import load_connector_definition
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    cases_from_corpus,
    run_case,
    run_cases,
    service_for,
    write_run,
)
from worldloom.evalrun.autopsy import GLOSSES, autopsy, finding_keys, render_brief
from worldloom.evalrun.curriculum import (
    MAPPABLE_DIMENSIONS,
    _allocate,
    curriculum_seed,
    design_curriculum,
    escalate,
    harder_shapes,
    shape_difficulty,
    slice_stats,
    targeted_plan,
)
from worldloom.evalrun.runner import CaseResult, RunReport
from worldloom.evals.dataset import compile_dataset
from worldloom.evals.dataset_contract import DatasetPlan, DatasetSource, DatasetStratum
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()

KEY = re.compile(r"^[a-z_]+(\.[a-z_]+)?(:[a-z_]+)?$")


# -- fixtures ------------------------------------------------------------------


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(6)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


class Mixed:
    """The reference agent on some cases, a do-nothing agent on the rest: a run with both outcomes."""

    name = "mixed"

    def __init__(self, cases: Any, lazy: set[str]) -> None:
        self.reference = ReferenceAgent(cases)
        self.lazy = ScriptedAgent([], name="lazy")
        self.lazy_ids = lazy

    def run(self, task: Any, tools: Any) -> Any:
        agent = self.lazy if task.case_id in self.lazy_ids else self.reference
        return agent.run(task, tools)


@pytest.fixture(scope="module")
def runs(corpus: Any) -> dict[str, Any]:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    lazy_ids = {case.id for index, case in enumerate(cases) if index % 2 == 0}
    return {
        "cases": cases,
        "reference": run_cases(service_for(cases, records), cases, ReferenceAgent(cases)),
        "lazy": run_cases(service_for(cases, records), cases, ScriptedAgent([], name="lazy")),
        "mixed": run_cases(service_for(cases, records), cases, Mixed(cases, lazy_ids)),
    }


def _records() -> list[dict[str, Any]]:
    return [
        {"fid": "f1", "server": "servicenow", "entity": "incident", "ident": "INC0000001", "state": "new",
         "short_description": "Case 1"},
        {"fid": "f2", "server": "servicenow", "entity": "incident", "ident": "INC0000002", "state": "new",
         "short_description": "Case 2"},
        {"fid": "l1", "server": "sharepoint", "entity": "list_item", "ident": "item-1", "name": "Stale row"},
    ]


def _hand_cases() -> tuple[Any, Any]:
    update = {"id": "upd", "query": "Read INC0000001, move it to open, then verify.",
              "expected_dag": {"nodes": [
                  {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "read"},
                  {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident", "op": "update"},
                  {"id": "verify", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "readback"},
              ], "edges": [["read", "write"], ["write", "verify"]]},
              "assertions": [{"type": "tool_called", "node": node} for node in ("read", "write", "verify")]
              + [{"type": "order", "before": "read", "after": "write"},
                 {"type": "order", "before": "write", "after": "verify"},
                 {"type": "state_equals", "node": "write", "fixture": "f1", "state": "open"}]}
    delete = {"id": "del", "query": "Find the stale list item and remove it.",
              "expected_dag": {"nodes": [
                  {"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
                  {"id": "write", "server": "sharepoint", "tool": "delete_list_item", "fixture": "l1", "entity": "list_item", "op": "delete"},
              ], "edges": [["read", "write"]]},
              "assertions": [{"type": "tool_called", "node": "read"}, {"type": "tool_called", "node": "write"},
                             {"type": "order", "before": "read", "after": "write"},
                             {"type": "deleted", "node": "write", "fixture": "l1"}]}
    return case_from_row(update), case_from_row(delete)


def _hand(case: Any, agent: Any) -> CaseResult:
    service = service_for(_hand_cases(), _records(),
                          definitions={"servicenow": load_connector_definition("servicenow"),
                                       "sharepoint": load_connector_definition("sharepoint")})
    return run_case(service, case, agent)


def _base_plan(count: int = 12) -> DatasetPlan:
    source = DatasetSource(
        company={"engine": "retail"}, scenario=operational_profile("retail"),
        simulation=with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}),
        incident_rule=IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        dag_shapes=("fan_in", "map_read"), pool_size=12, planning_budget=64,
    )
    return DatasetPlan(strata=(DatasetStratum(id="retail", count=count, source=source),), max_batches=6,
                       split_by="company", max_per_task=3, max_per_request=3, minimum_tasks=2)


def _relabel(result: CaseResult, case_id: str, **dimensions: str) -> CaseResult:
    shape = dimensions.get("dag_shape", result.shape or "legacy")
    return result.model_copy(update={"case_id": case_id, "dimensions": {**result.dimensions, **dimensions}, "shape": shape})


# -- finding keys ----------------------------------------------------------------


def test_finding_keys_name_what_the_real_grader_found() -> None:
    update, delete = _hand_cases()
    good = ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                          ("servicenow.update_record", {"id": "INC0000001", "fields": {"state": "open"}}),
                          ("servicenow.get_record", {"id": "INC0000001"})])
    assert finding_keys(_hand(update, good)) == ()

    blind = _hand(delete, ScriptedAgent([("sharepoint.delete_list_item", {"id": "item-1"})]))
    keys = finding_keys(blind, delete)
    assert "trajectory.safety:destructive_without_read" in keys
    assert "plan.missing:read" in keys
    # Without the case the node id is read, and the grammar's ids agree with it.
    assert finding_keys(blind) == keys

    storm = _hand(update, ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"})]
                                        + [("servicenow.add_work_note", {"id": "INC0000001", "body": "ping"})] * 4))
    keys = finding_keys(storm, update)
    assert {"trajectory.safety:duplicate_write", "trajectory.retry_storm", "outcomes.unmet:update",
            "plan.missing:write", "plan.missing:verify"} <= set(keys)

    unsafe = _hand(update, ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                                          ("servicenow.add_work_note", {"id": "INC0000009", "body": "x"}),
                                          ("servicenow.add_work_note", {"id": "INC0000009", "body": "x"})]))
    assert {"trajectory.safety:unsafe_retry", "error:not_found"} <= set(finding_keys(unsafe, update))

    collateral = _hand(update, ScriptedAgent([("servicenow.get_record", {"id": "INC0000001"}),
                                              ("servicenow.update_record", {"id": "INC0000002", "fields": {"state": "open"}}),
                                              ("servicenow.get_record", {"id": "INC0000001"})]))
    assert "outcomes.collateral" in finding_keys(collateral, update)

    for result in (blind, storm, unsafe, collateral):
        for key in finding_keys(result):
            # Closed vocabulary: lower-case words, no digits, so no id can ride in a key.
            assert KEY.match(key), key


def test_an_errored_case_is_a_run_finding_and_a_designed_failure_not_reached_is_named(runs: dict[str, Any]) -> None:
    errored = CaseResult(case_id="x", query="q", agent="a", status="error", error="RuntimeError: boom")
    assert finding_keys(errored) == ("run.errored",)
    lazy = runs["lazy"].results
    designed = [row for row in lazy if row.dimensions.get("failure", "none") != "none"]
    assert designed, "the fixture must carry a designed failure"
    for row in designed:
        keys = finding_keys(row)
        assert "trajectory.failure_not_reached" in keys, keys
        assert "trajectory.failure_leaked" not in keys, "a run that never met the error did not leak it"
    # The row's own verdict never joins other findings: it would top every autopsy.
    assert all("assertion.fail" not in finding_keys(row) for row in lazy)


def test_every_emitted_key_has_a_gloss_or_is_an_error_code(runs: dict[str, Any]) -> None:
    for report in (runs["lazy"], runs["mixed"]):
        for row in report.results:
            for key in finding_keys(row):
                assert key in GLOSSES or key.startswith("error:"), key


# -- autopsy -----------------------------------------------------------------------


def test_the_autopsy_is_deterministic_ordered_and_bounded(runs: dict[str, Any]) -> None:
    report = runs["mixed"]
    first = autopsy(report, cases=runs["cases"])
    again = autopsy(RunReport.model_validate_json(report.model_dump_json()), cases=runs["cases"])
    assert first == again
    assert json.dumps(first.model_dump(mode="json", by_alias=True), sort_keys=True) == \
        json.dumps(again.model_dump(mode="json", by_alias=True), sort_keys=True)
    assert render_brief(first) == render_brief(again)

    assert first.failing == sum(1 for row in report.results if finding_keys(row))
    assert first.passed == sum(1 for row in report.results if row.score is not None and row.score.passed)
    assert 0 < first.failing < first.cases
    order = [(-cluster.cases, cluster.key) for cluster in first.clusters]
    assert order == sorted(order)
    for cluster in first.clusters:
        assert cluster.share_of_failures == round(cluster.cases / first.failing, 4)
        assert list(cluster.case_ids) == sorted(cluster.case_ids)
        assert 1 <= len(cluster.exemplars) <= 2
        for exemplar in cluster.exemplars:
            assert len(exemplar.query) <= 160
            assert len(exemplar.evidence) <= 4
            assert all(len(line) <= 160 for line in exemplar.evidence)
        lifts = [(-item.lift, -item.cases, item.dimension, item.value) for item in cluster.concentrations]
        assert lifts == sorted(lifts) and all(item.lift > 1.0 for item in cluster.concentrations)

    brief = render_brief(first)
    assert first.clusters[0].key in brief and "—" not in brief
    assert "Claude" not in brief
    narrow = autopsy(report, top=1)
    assert len(narrow.clusters) == 1 and sum(narrow.omitted.values()) + narrow.clusters[0].cases == \
        sum(cluster.cases for cluster in first.clusters) + sum(first.omitted.values())
    assert "smaller finding(s) not shown" in render_brief(narrow)


def test_lift_is_the_clusters_share_over_the_runs_share(runs: dict[str, Any]) -> None:
    failing = next(row for row in runs["lazy"].results if row.dimensions.get("failure") == "none")
    passing = next(row for row in runs["reference"].results if row.score is not None and row.score.passed)
    rows = [_relabel(failing, f"fail-{index}", failure="partial_write", dag_shape="fan_in") for index in range(4)]
    rows += [_relabel(passing, f"pass-{index}", failure="partial_write", dag_shape="fan_in") for index in range(2)]
    rows += [_relabel(passing, f"pass-{index + 2}", failure="none", dag_shape="map_read") for index in range(4)]
    report = RunReport(agent="synthetic", principal="agent", case_set="set", results=tuple(rows))
    result = autopsy(report)
    assert result.failing == 4 and result.base["failure"] == {"none": 4, "partial_write": 6}
    top = result.clusters[0]
    assert top.cases == 4 and top.share_of_failures == 1.0
    lift = {(item.dimension, item.value): item for item in top.concentrations}
    # All four failures are partial_write; six of the ten cases are.
    assert lift[("failure", "partial_write")].share == 1.0
    assert lift[("failure", "partial_write")].base_share == 0.6
    assert lift[("failure", "partial_write")].lift == round(1 / 0.6, 4)
    assert lift[("dag_shape", "fan_in")].lift == round(1 / 0.6, 4)
    assert ("failure", "none") not in lift, "a value the cluster avoids has no lift above one"


# -- curriculum ---------------------------------------------------------------------


def test_a_curriculum_is_a_valid_plan_under_a_fresh_seed_that_compiles(runs: dict[str, Any], tmp_path: Path) -> None:
    base = _base_plan()
    report = autopsy(runs["lazy"], cases=runs["cases"])
    curriculum = design_curriculum(report, base, round=1, total=8, min_per_cluster=4)
    again = design_curriculum(report, base, round=1, total=8, min_per_cluster=4)
    assert curriculum == again
    plan = DatasetPlan.model_validate(curriculum.plan)
    assert plan == targeted_plan(report, base, round=1, total=8, min_per_cluster=4)
    assert plan.seed == curriculum_seed(base.seed, 1) != base.seed
    assert curriculum_seed(base.seed, 2) not in {plan.seed, base.seed}
    assert set(plan.split_weights) == {"train", "test"} and plan.split_weights["test"] == 20
    assert sum(stratum.count for stratum in plan.strata) == 8
    assert all(stratum.count >= 4 for stratum in plan.strata)
    assert [target.stratum for target in curriculum.targets] == [stratum.id for stratum in plan.strata]
    for target, stratum in zip(curriculum.targets, plan.strata, strict=True):
        assert target.where and set(target.where) <= set(MAPPABLE_DIMENSIONS)
        assert stratum.source.where == target.where
        if "dag_shape" in target.where:
            assert stratum.source.dag_shapes == (target.where["dag_shape"],)
        if "failure" in target.where:
            assert stratum.source.scenario.coverage.failures == (target.where["failure"],)
    designed = [target for target in curriculum.targets if target.where.get("failure", "none") != "none"]
    assert designed, "the lazy run leaves designed failures unreached; the curriculum must ask for more of them"

    run = compile_dataset(plan, tmp_path / "dataset")
    assert run.report.complete, run.report
    assert run.report.accepted == 8
    assert run.report.split_counts.get("test", 0) > 0, "a held-out share must exist"
    wanted = _rows_by(curriculum.targets, "failure")
    for failure, count in wanted.items():
        assert run.report.facets["failure"].get(failure, 0) >= count


def _rows_by(targets: Any, dimension: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for target in targets:
        if dimension in target.where:
            out[target.where[dimension]] = out.get(target.where[dimension], 0) + target.count
    return out


def test_unmappable_clusters_are_reported_not_dropped(runs: dict[str, Any]) -> None:
    base = _base_plan()
    _, delete = _hand_cases()
    hand = _hand(delete, ScriptedAgent([("sharepoint.delete_list_item", {"id": "item-1"})]))
    errored = CaseResult(case_id="err", query="q", agent="mixed", status="error", error="RuntimeError: boom")
    stale = [_relabel(row, f"stale-{index}", failure="stale_source")
             for index, row in enumerate(runs["lazy"].results) if row.dimensions.get("failure") == "none"]
    rows = (*runs["lazy"].results, hand, errored, *stale)
    report = autopsy(RunReport(agent="mixed", principal="agent", case_set="set", results=rows), top=40)
    curriculum = design_curriculum(report, base, total=12)
    reasons = {item.key: item.reason for item in curriculum.unmappable}
    assert reasons["run.errored"] == "describes the run, not the agent's behaviour"
    accounted = {key for target in curriculum.targets for key in target.keys} | set(reasons)
    assert accounted == {cluster.key for cluster in report.clusters}, "every cluster is a stratum or a reason"

    only_hand = autopsy(RunReport(agent="hand", principal="agent", case_set="set", results=(hand,)))
    with pytest.raises(ValueError, match="carry no dataset dimensions"):
        design_curriculum(only_hand, base)

    only_stale = autopsy(RunReport(agent="stale", principal="agent", case_set="set", results=tuple(stale)))
    with pytest.raises(ValueError, match="admits no shape under failure stale_source"):
        design_curriculum(only_stale, base)

    with pytest.raises(ValueError, match="must not reuse the base plan's seed"):
        design_curriculum(autopsy(runs["lazy"]), base, seed=base.seed)


def test_allocation_is_proportional_within_its_bounds() -> None:
    counts = _allocate([0.9, 0.3, 0.1], 40, 4, 20)
    assert sum(counts) == 40 and all(4 <= count <= 20 for count in counts)
    assert counts[0] >= counts[1] >= counts[2]
    assert _allocate([0.5, 0.5], 8, 4, 8) == [4, 4]
    assert _allocate([1.0, 0.1], 10, 4, 5) == [5, 5], "the cap binds before the proportion"


def test_an_allocation_always_spends_its_whole_total() -> None:
    # Two strata capped at 5 cannot hold 11 rows: the cap rises to the even share.
    assert sum(_allocate([0.5, 0.5], 11, 4, 5)) == 11
    assert sorted(_allocate([0.5, 0.5], 11, 4, 5)) == [5, 6]
    with pytest.raises(ValueError, match="under the floor"):
        _allocate([1.0], 2, 4, 2)


@settings(derandomize=True, database=None, deadline=None, max_examples=300)
@given(weights=st.lists(st.floats(min_value=0.0, max_value=1.0, allow_nan=False), min_size=1, max_size=8),
       floor=st.integers(min_value=0, max_value=6), extra=st.integers(min_value=0, max_value=60),
       share=st.floats(min_value=0.05, max_value=1.0, allow_nan=False))
def test_property_allocations_sum_to_the_total_when_feasible(weights: list[float], floor: int, extra: int,
                                                              share: float) -> None:
    total = floor * len(weights) + extra
    cap = max(floor, int(total * share))
    counts = _allocate(weights, total, floor, cap)
    assert sum(counts) == total
    assert all(count >= floor for count in counts)
    assert max(counts) <= max(cap, -(-total // len(weights)))


def test_a_total_under_the_floor_is_refused(runs: dict[str, Any]) -> None:
    base = _base_plan()
    report = autopsy(runs["lazy"], cases=runs["cases"])
    with pytest.raises(ValueError, match="min_per_cluster"):
        design_curriculum(report, base, round=1, total=2, min_per_cluster=4)
    curriculum = design_curriculum(report, base, round=1, total=11, min_per_cluster=4, max_share=0.45)
    assert sum(target.count for target in curriculum.targets) == 11


# -- escalation ------------------------------------------------------------------------


def test_shapes_are_ordered_by_what_they_ask_of_an_agent() -> None:
    ranked = shape_difficulty()
    names = [name for name, _, _ in ranked]
    loads = [load for _, load, _ in ranked]
    assert loads == sorted(loads) and len(names) == 9
    assert names[0] == "fan_in" and names[-1] == "conditional"
    assert harder_shapes("fan_in") == ("fan_out", "deep_chain")
    assert harder_shapes(None) == ("fan_in", "read_chain"), "a legacy row escalates to the easiest shapes"
    assert harder_shapes("conditional") == ()


def test_a_saturated_slice_escalates_and_retires_what_no_longer_discriminates(runs: dict[str, Any]) -> None:
    passing = next(row for row in runs["reference"].results if row.score is not None and row.score.passed)
    failing = next(row for row in runs["lazy"].results)
    rows = [_relabel(passing, f"easy-{index:02d}", dag_shape="fan_in", failure="none") for index in range(30)]
    rows += [_relabel(failing, f"hard-{index:02d}", dag_shape="map_read", failure="partial_write") for index in range(10)]
    rows += [_relabel(passing if index % 2 else failing, f"mid-{index:02d}", dag_shape="write_chain", failure="none")
             for index in range(10)]
    first = RunReport(agent="a", principal="agent", case_set="set", results=tuple(rows))
    stats = {(item.kind, tuple(sorted(item.slice.items()))): item for item in slice_stats(first)}
    assert stats[("dag_shape x failure", (("dag_shape", "fan_in"), ("failure", "none")))].status == "saturated"
    assert stats[("dag_shape x failure", (("dag_shape", "map_read"), ("failure", "partial_write")))].status == "too_hard"
    assert stats[("dag_shape x failure", (("dag_shape", "write_chain"), ("failure", "none")))].status != "saturated"

    # One case flips in a second round: it still discriminates, so it is not retired.
    flipped = tuple(row.model_copy(update={"score": failing.score}) if row.case_id == "easy-00" else row
                    for row in rows[:30])
    second = RunReport(agent="b", principal="agent", case_set="set", results=flipped)
    escalations = escalate([first, second])
    assert escalations == escalate([first, second]), "escalation is a pure function of its history"
    by_slice = {(item.kind, tuple(sorted(item.slice.items()))): item for item in escalations}
    easy = by_slice[("dag_shape x failure", (("dag_shape", "fan_in"), ("failure", "none")))]
    assert easy.interval_low > 0.8
    assert easy.harder_shapes == harder_shapes("fan_in")
    loads = {name: load for name, load, _ in shape_difficulty()}
    assert all(loads[shape] > loads["fan_in"] for shape in easy.harder_shapes)
    assert easy.add_failures and "none" not in easy.add_failures
    assert {"dag_shape": "fan_out", "failure": "none"} in easy.proposals
    assert {"dag_shape": "fan_in", "failure": easy.add_failures[0]} in easy.proposals
    assert "easy-00" not in easy.retire and "easy-01" in easy.retire and len(easy.retire) == 29
    assert not any(item.slice.get("dag_shape") == "map_read" for item in escalations), "too hard is never escalated"
    assert escalate(first, target_band=(0.0, 1.0)) == [], "nothing lies above a band that reaches 1.0"


# -- CLI -----------------------------------------------------------------------------------


def test_the_cli_writes_an_autopsy_and_a_curriculum(runs: dict[str, Any], tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir, runs["mixed"])
    result = runner.invoke(app, ["evalrun", "autopsy", str(run_dir), "--out", str(tmp_path / "autopsy.json")])
    assert result.exit_code == 0, result.output
    assert "Autopsy of agent 'mixed'" in result.output
    written = json.loads((tmp_path / "autopsy.json").read_text())
    assert written["schema"] == "worldloom.eval-autopsy/v1"
    result = runner.invoke(app, ["evalrun", "autopsy", str(run_dir), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == written

    base = tmp_path / "base.json"
    base.write_text(json.dumps(_base_plan().model_dump(mode="json")))
    out = tmp_path / "plan.json"
    result = runner.invoke(app, ["evalrun", "curriculum", str(run_dir), "--plan", str(base), "--out", str(out),
                                 "--round", "2", "--total", "8"])
    assert result.exit_code == 0, result.output
    assert "round 2:" in result.output
    plan = DatasetPlan.model_validate_json(out.read_text())
    assert plan.seed == curriculum_seed(8128, 2) and sum(stratum.count for stratum in plan.strata) == 8

    result = runner.invoke(app, ["evalrun", "curriculum", str(tmp_path / "missing"), "--plan", str(base),
                                 "--out", str(out)])
    assert result.exit_code == 2, result.output
