"""Value at stake and a realistic mix: cases priced from their records, case sets measured against the company.

Two real corpora: the operational retail corpus the autopsy tests use (money
lives in each exception record's observation history) and a small telecom
programme (system-of-record records carry an amount and a currency, and a
catalogue activity). Every price asserted here is recomputed from the records
the case names, so a test fails when money is invented, not only when a
number moves.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, industry
from worldloom.cli import app
from worldloom.corpus import write_jsonl
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    case_from_row,
    cases_from_corpus,
    run_cases,
    service_for,
    write_run,
)
from worldloom.evalrun.autopsy import autopsy, render_brief
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.curriculum import design_curriculum
from worldloom.evalrun.results import compare
from worldloom.evalrun.runner import RunReport
from worldloom.evalrun.value import (
    REPRESENTATIVE_KEY,
    ReferenceMix,
    check_mix,
    index_records,
    mix_report,
    mix_scores,
    reference_from_catalogue,
    reference_mix,
    total_variation,
    touched_records,
    value_of,
    value_summary,
    value_table,
    value_weighted_delta,
)
from worldloom.evals.dataset_contract import DatasetPlan, DatasetSource, DatasetStratum
from worldloom.process_bindings import BusinessUnit, CompanySpec, compile_company
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()


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
    """The reference agent on some cases, a do-nothing agent on the rest."""

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
        "records": records,
        "reference": run_cases(service_for(cases, records), cases, ReferenceAgent(cases)),
        "lazy": run_cases(service_for(cases, records), cases, ScriptedAgent([], name="lazy")),
        "mixed": run_cases(service_for(cases, records), cases, Mixed(cases, lazy_ids)),
    }


@pytest.fixture(scope="module")
def telecom() -> dict[str, Any]:
    company = CompanySpec(name="Ardent Telecom", industry="telecom", operating_model="centralised", countries=("IN",),
                          bus=(BusinessUnit(name="Consumer", archetype="customer_segment"),
                               BusinessUnit(name="Group Finance", archetype="group_function")))
    derived = industry.programme(company)
    cases = industry.evalrun_cases(derived)
    return {"company": company, "derived": derived, "cases": cases, "records": derived.records}


def _fields(record: Any) -> dict[str, Any]:
    return dict(record.fields)


def _by_id(records: Any) -> dict[str, Any]:
    return {record.id: record for record in records}


def _history_revenue(record: Any) -> float:
    return float(sum(item["values"]["revenue"] for item in record.fields["history"]))


# -- value of one case -------------------------------------------------------------


def test_operational_money_is_the_touched_records_history_and_nothing_else(runs: dict[str, Any]) -> None:
    records = _by_id(runs["records"])
    table = value_table(runs["cases"], runs["records"])
    assert list(table) == sorted(table), "values come back in case-id order"
    for case in runs["cases"]:
        value = table[case.id]
        touched = [records[fid] for fid in touched_records(case) if fid in records]
        assert touched, "every operational case reads an exception record"
        assert value.at_stake == round(sum(_history_revenue(record) for record in touched), 2)
        assert value.currency is None, "the simulated records name no currency and none is invented"
        assert any("history[].revenue summed over" in line for line in value.basis)
        assert any(record.id in line for record in touched for line in value.basis)
        # A draft is a create; every row in this corpus with a designed failure is priced up by the policy factor.
        assert value.operation == "create"
        expected = 3.0 * (1.5 if case.trajectory.failures else 1.0)
        assert value.error_cost == expected
        # No catalogue activity; the frequency is the simulation's episode count on the source.
        assert value.activity is None
        source = next(record for record in touched)
        episodes = {r.fields["case_id"] for r in runs["records"]
                    if r.connector == source.connector and r.entity == source.entity}
        assert value.frequency == float(len(episodes))
        assert any("simulated volume" in line for line in value.basis)


def test_a_case_without_money_has_none_at_stake_and_neutral_parts() -> None:
    records = [
        {"fid": "f1", "server": "servicenow", "entity": "incident", "ident": "INC0000001", "state": "new"},
        {"fid": "l1", "server": "sharepoint", "entity": "list_item", "ident": "item-1", "name": "Stale row"},
    ]
    update = case_from_row({"id": "upd", "query": "Move INC0000001 to open.", "expected_dag": {"nodes": [
        {"id": "read", "server": "servicenow", "tool": "get_record", "fixture": "f1", "entity": "incident", "op": "read"},
        {"id": "write", "server": "servicenow", "tool": "update_record", "fixture": "f1", "entity": "incident", "op": "update"},
    ], "edges": [["read", "write"]]}, "assertions": []})
    delete = case_from_row({"id": "del", "query": "Remove the stale item.", "expected_dag": {"nodes": [
        {"id": "read", "server": "sharepoint", "tool": "get_list_items", "fixture": "l1", "entity": "list_item", "op": "search"},
        {"id": "write", "server": "sharepoint", "tool": "delete_list_item", "fixture": "l1", "entity": "list_item", "op": "delete"},
    ], "edges": [["read", "write"]]}, "assertions": [{"type": "deleted", "node": "write", "fixture": "l1"}]})
    table = value_table([update, delete], records)
    for case_id, cost in (("upd", 2.0), ("del", 5.0)):
        value = table[case_id]
        assert value.at_stake is None and value.currency is None and value.frequency is None
        assert value.error_cost == cost and value.weight == cost, "missing parts count as a typical case"
        assert any(line.startswith("at stake unknown") for line in value.basis)
        assert any("counted as a typical case" in line for line in value.basis)
    assert table["upd"].operation == "update" and table["del"].operation == "delete"


def test_quantity_times_unit_price_and_currencies_are_never_mixed() -> None:
    records = [
        {"fid": "po1", "server": "sor", "entity": "purchase_order", "quantity": 4, "unit_price": 25.5, "currency": "EUR"},
        {"fid": "po2", "server": "sor", "entity": "purchase_order", "amount": 300, "currency": "USD"},
        {"fid": "po3", "server": "sor", "entity": "purchase_order", "Amount": "40", "currency": "EUR"},
    ]
    case = case_from_row({"id": "po", "query": "Compare the three orders.", "expected_dag": {"nodes": [
        {"id": "read-0", "server": "sor", "tool": "search_records", "entity": "purchase_order", "op": "search",
         "expected_reads": ["po1", "po2", "po3", "po-missing"]},
    ], "edges": []}, "assertions": []})
    value = value_of(case, records)
    # USD 300 is the largest single-currency total; the EUR 142 is named, never converted or added.
    assert value.at_stake == 300.0 and value.currency == "USD"
    assert "po1.quantity=4 x unit_price=25.5" in "\n".join(value.basis) or value.currency == "USD"
    assert any(line.startswith("not added: records in EUR") for line in value.basis)
    assert value.basis[0] == "4 record(s) the plan touches, 3 in the record set (1 absent)"
    euro = value_of(case, [record for record in records if record["currency"] == "EUR"])
    assert euro.at_stake == 4 * 25.5 + 40 and euro.currency == "EUR"
    assert "po1.quantity=4 x unit_price=25.5" in euro.basis


def test_programme_money_frequency_and_activity_come_from_the_records(telecom: dict[str, Any]) -> None:
    records = _by_id(telecom["records"])
    cases = telecom["cases"][:80]
    table = value_table(cases, telecom["records"])
    per_activity = Counter(record.fields["activity_id"] for record in telecom["records"])
    periods: dict[str, set[str]] = {}
    for record in telecom["records"]:
        periods.setdefault(record.fields["activity_id"], set()).add(record.fields["period"])
    priced = unpriced = 0
    for case in cases:
        value = table[case.id]
        touched = [records[fid] for fid in touched_records(case)]
        amounts = [record.fields["amount"] for record in touched if "amount" in record.fields]
        if amounts:
            priced += 1
            assert value.at_stake == round(sum(amounts), 2)
            assert value.currency == "INR"
        else:
            unpriced += 1
            assert value.at_stake is None, "no amount on any touched record: nothing is at stake, nothing invented"
        activity = Counter(record.fields["activity_id"] for record in touched).most_common(1)[0][0]
        assert value.activity == activity
        assert value.frequency == round(per_activity[activity] / len(periods[activity]), 4)
        assert value.operation == "read" and value.error_cost == 1.0
    assert priced and unpriced, "the slice must hold both kinds of case"

    compiled = compile_company(telecom["company"])
    by_catalogue = value_of(cases[0], telecom["records"], catalogue=compiled)
    assert any("compiled catalogue" in line for line in by_catalogue.basis)
    supplied = value_of(cases[0], telecom["records"], catalogue={table[cases[0].id].activity: 7})
    assert supplied.frequency == 7.0, "supplied volumes take precedence over the record count"


def test_values_are_deterministic_and_independent_of_record_order(runs: dict[str, Any], telecom: dict[str, Any]) -> None:
    for cases, records in ((runs["cases"], runs["records"]), (telecom["cases"][:40], telecom["records"])):
        first = value_table(cases, records)
        again = value_table(list(reversed(cases)), list(reversed(list(records))))
        assert first == again
        assert json.dumps({key: value.model_dump(mode="json") for key, value in first.items()}, sort_keys=True) == \
            json.dumps({key: value.model_dump(mode="json") for key, value in again.items()}, sort_keys=True)
        assert value_table(cases, index_records(records)) == first


def test_weights_are_the_normalised_product(telecom: dict[str, Any]) -> None:
    cases = telecom["cases"][:60]
    table = value_table(cases, telecom["records"])
    stakes = sorted(value.at_stake for value in table.values() if value.at_stake is not None)
    frequencies = sorted(value.frequency for value in table.values() if value.frequency is not None)

    def median(values: list[float]) -> float:
        middle = len(values) // 2
        return values[middle] if len(values) % 2 else (values[middle - 1] + values[middle]) / 2

    for value in table.values():
        stake = 1.0 if value.at_stake is None else min(100.0, max(0.01, value.at_stake / median(stakes)))
        often = min(100.0, max(0.01, value.frequency / median(frequencies))) if value.frequency is not None else 1.0
        assert value.weight == pytest.approx(stake * often * value.error_cost, rel=1e-5)
        assert value.basis[-1].startswith(f"weight {value.weight:g}")


# -- a run, weighted -------------------------------------------------------------------


def test_the_value_summary_weights_the_same_grades(runs: dict[str, Any]) -> None:
    report = runs["mixed"]
    table = value_table(runs["cases"], runs["records"])
    summary = value_summary(report, runs["cases"], runs["records"])
    graded = [row for row in report.results if row.graded and row.score is not None]
    weight = {row.case_id: table[row.case_id].weight for row in graded}
    passed = [row for row in graded if row.score.passed]
    assert 0 < len(passed) < len(graded)
    assert summary.pass_rate == round(len(passed) / len(graded), 4)
    assert summary.value_weighted_pass_rate == round(sum(weight[row.case_id] for row in passed) / sum(weight.values()), 4)
    assert summary.value_weighted_mean_score == round(
        sum(weight[row.case_id] * row.score.score for row in graded) / sum(weight.values()), 4)
    assert summary.at_stake == pytest.approx(summary.at_stake_passed + summary.at_stake_failed + summary.at_stake_errored)
    assert summary.at_stake_failed == pytest.approx(sum(table[row.case_id].at_stake for row in graded if not row.score.passed))
    failing = [(item.weight, item.at_stake or 0.0) for item in summary.top_failing]
    assert failing == sorted(failing, reverse=True) and all(item.passed is False for item in summary.top_failing)
    assert [entry.activity for entry in summary.by_activity] == ["workflow:inventory_exception_review"]
    assert summary.by_activity[0].value_weighted_pass_rate == summary.value_weighted_pass_rate
    assert value_summary(report, runs["cases"], runs["records"]) == summary

    # The unweighted summary is untouched by any of this.
    from worldloom.evalrun.results import summarize

    assert "value" not in json.dumps(summarize(report).model_dump(mode="json", by_alias=True))


def test_the_value_weighted_delta_averages_the_same_deltas(runs: dict[str, Any]) -> None:
    comparison = compare(runs["lazy"], runs["reference"])
    uniform = {row.case_id: 1.0 for row in runs["lazy"].results}
    assert value_weighted_delta(comparison, uniform) == comparison.mean_delta
    table = value_table(runs["cases"], runs["records"])
    deltas = [item for item in comparison.deltas if item.delta is not None]
    expected = sum(table[item.case_id].weight * item.delta for item in deltas) / sum(table[item.case_id].weight for item in deltas)
    assert value_weighted_delta(comparison, table) == round(expected, 4)
    assert value_weighted_delta(comparison, {}) == comparison.mean_delta, "a case with no value weighs 1.0"
    with pytest.raises(ValueError, match="graded differently"):
        value_weighted_delta(comparison.model_copy(update={"grader_mismatch": True}), table)


# -- autopsy and curriculum ------------------------------------------------------------


def _base_plan(count: int = 12) -> DatasetPlan:
    source = DatasetSource(
        company={"engine": "retail"}, scenario=operational_profile("retail"),
        simulation=with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}),
        incident_rule=IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        dag_shapes=("fan_in", "map_read"), pool_size=12, planning_budget=64,
    )
    return DatasetPlan(strata=(DatasetStratum(id="retail", count=count, source=source),), max_batches=6,
                       split_by="company", max_per_task=3, max_per_request=3, minimum_tasks=2)


def test_the_autopsy_without_values_is_unchanged_and_with_them_is_weighted(runs: dict[str, Any]) -> None:
    report = runs["lazy"]
    plain = autopsy(report, cases=runs["cases"])
    dumped = plain.model_dump(mode="json", by_alias=True)
    assert all("value" not in cluster for cluster in dumped["clusters"])
    assert autopsy(report, cases=runs["cases"], values=None) == plain
    assert "value:" not in render_brief(plain)

    table = value_table(runs["cases"], runs["records"])
    valued = autopsy(report, cases=runs["cases"], values=table)
    assert [cluster.key for cluster in valued.clusters] == [cluster.key for cluster in plain.clusters], \
        "values add fields; the default ordering stays by count"
    failing = sorted({case_id for cluster in valued.clusters for case_id in cluster.case_ids})
    total = sum(table[case_id].weight for case_id in failing)
    for cluster in valued.clusters:
        assert cluster.model_copy(update={"value": None}) == next(c for c in plain.clusters if c.key == cluster.key)
        assert cluster.value is not None
        assert cluster.value.weight == pytest.approx(sum(table[case_id].weight for case_id in cluster.case_ids))
        assert cluster.value.value_share == round(cluster.value.weight / total, 4)
        assert cluster.value.at_stake == pytest.approx(sum(table[case_id].at_stake for case_id in cluster.case_ids))
    assert "value:" in render_brief(valued)

    # Weigh one cluster's cases a hundredfold: ordering by value puts it first.
    light = valued.clusters[-1]
    skewed = {case_id: (100.0 if case_id in light.case_ids else 1.0) for case_id in table}
    by_value = autopsy(report, cases=runs["cases"], values=skewed, order="value")
    order = [(-cluster.value.weight, -cluster.cases, cluster.key) for cluster in by_value.clusters if cluster.value]
    assert order == sorted(order)
    assert by_value.clusters[0].value is not None and by_value.clusters[0].value.weight >= light.cases * 100.0
    with pytest.raises(ValueError, match="needs values"):
        autopsy(report, order="value")


def test_the_curriculum_is_unchanged_without_values_and_weighted_with_them(runs: dict[str, Any]) -> None:
    base = _base_plan()
    report = autopsy(runs["lazy"], cases=runs["cases"])
    plain = design_curriculum(report, base, round=1, total=24, min_per_cluster=4)
    assert design_curriculum(report, base, round=1, total=24, min_per_cluster=4, values=None, reference=None) == plain
    assert "mix" not in plain.model_dump(mode="json", by_alias=True, exclude={"plan"})
    assert len(plain.targets) >= 2, "the fixture must yield more than one stratum to weigh"

    # Claim is failure share x value share. Put the value on the designed-failure
    # cases: the stratum that answers them grows, the other falls to its floor.
    roomy = {"round": 1, "total": 24, "min_per_cluster": 4, "max_share": 0.9}
    unweighted = design_curriculum(report, base, **roomy)
    designed = {case.id for case in runs["cases"] if case.trajectory.failures}
    assert designed and len(designed) < len(runs["cases"])
    values = {case.id: (50.0 if case.id in designed else 1.0) for case in runs["cases"]}
    weighted = design_curriculum(report, base, **roomy, values=values)
    before = {tuple(sorted(target.where.items())): target.count for target in unweighted.targets}
    after = {tuple(sorted(target.where.items())): target.count for target in weighted.targets}
    assert set(before) == set(after) and sum(after.values()) == 24
    grows = next(key for key in after if dict(key).get("failure") not in (None, "none"))
    assert after[grows] > before[grows]
    assert all(after[key] == 4 for key in after if key != grows), "the cheap stratum keeps only its floor"
    for target in weighted.targets:
        match = next(item for item in unweighted.targets if item.where == target.where)
        assert target.share_of_failures == match.share_of_failures, "targets still report the failure share"
    assert design_curriculum(report, base, **roomy, values={case.id: 1.0 for case in runs["cases"]}).targets == \
        unweighted.targets, "uniform values change nothing"


# -- mix -----------------------------------------------------------------------------------


def test_total_variation_is_half_the_l1_distance() -> None:
    assert total_variation({"a": 0.5, "b": 0.5}, {"a": 1.0}) == 0.5
    assert total_variation({"a": 1.0}, {"b": 1.0}) == 1.0
    assert total_variation({"a": 0.25, "b": 0.75}, {"a": 0.25, "b": 0.75}) == 0.0
    reference = ReferenceMix(dimension="source_set", volumes={"jira": 3.0, "servicenow": 1.0, "retired": 0.0})
    assert reference.shares == {"jira": 0.75, "servicenow": 0.25}


def test_the_mix_report_measures_the_case_set_against_a_reference(runs: dict[str, Any]) -> None:
    cases = runs["cases"]
    plain = mix_report(cases)
    shares = {item.dimension: item.shares for item in plain.dimensions}
    assert shares["workflow"] == {"inventory_exception_review": 1.0}
    assert shares["operation"] == {"draft": 1.0}
    assert plain.comparison is None and plain.notes == ()

    counts = Counter(case.dimensions["source_set"] for case in cases)
    reference = ReferenceMix(dimension="source_set", volumes={"jira": 1.0, "servicenow": 1.0})
    report = mix_report(cases, reference=reference)
    case_shares = {key: value / len(cases) for key, value in counts.items()}
    assert report.comparison is not None
    assert report.comparison.tvd == pytest.approx(0.5 * sum(abs(case_shares.get(key, 0) - 0.5) for key in ("jira", "servicenow")), abs=1e-6)
    over = counts.most_common(1)[0][0]
    assert report.comparison.over[0].value == over
    assert "simulated operations" in report.notes[0]


def test_the_company_mix_comes_from_its_records_and_bindings(telecom: dict[str, Any]) -> None:
    records = telecom["records"]
    reference = reference_mix(records)
    counts = Counter(record.fields["activity_id"] for record in records)
    assert reference.volumes == {key: float(value) for key, value in sorted(counts.items())}
    assert not reference.empirical and "authored prior" in reference.basis[-1]
    compiled = compile_company(telecom["company"])
    by_bindings = reference_from_catalogue(compiled)
    # Every binding writes the same records per kind and period, so the two mixes agree.
    assert by_bindings.shares == pytest.approx(reference.shares)
    assert reference_from_catalogue(compiled, dimension="activity_type").volumes
    with pytest.raises(ValueError, match="no 'workflow'"):
        reference_mix(records, dimension="workflow")

    cases = telecom["cases"]
    report = mix_report(cases, reference=reference, records=records)
    activity = next(item for item in report.dimensions if item.dimension == "activity")
    assert sum(activity.counts.values()) == len(cases) and "none" not in activity.counts
    assert report.comparison is not None
    assert report.comparison.tvd == total_variation(activity.shares, reference.shares)


def test_the_guard_refuses_a_set_that_drifts_into_one_slice(telecom: dict[str, Any]) -> None:
    records = telecom["records"]
    reference = reference_mix(records)
    index = index_records(records)
    narrow = [case for case in telecom["cases"] if value_of(case, index).activity == "a2r.01"]
    assert narrow
    refused = check_mix(narrow, reference, records=index)
    assert not refused.ok and refused.measured_on == "cases" and refused.max_tvd == 0.3
    assert refused.over[0].value == "a2r.01" and "exceeds 0.3" in refused.reason
    assert check_mix(narrow, reference, 1.0, records=index).ok

    # A plan is predicted from what its strata pin; an unpinned stratum follows the reference.
    plan = {"strata": [{"id": "a", "count": 5, "source": {"where": {}}}]}
    assert check_mix(plan, reference).tvd == pytest.approx(0.0, abs=1e-6)
    pinned = {"strata": [{"id": "a", "count": 5, "source": {"where": {"activity": "a2r.01"}}}]}
    assert not check_mix(pinned, reference).ok


def test_a_curriculum_keeps_a_representative_share_and_scores_it_apart(runs: dict[str, Any]) -> None:
    base = _base_plan()
    report = autopsy(runs["lazy"], cases=runs["cases"])
    reference = ReferenceMix(dimension="workflow", volumes={"inventory_exception_review": 40.0})
    curriculum = design_curriculum(report, base, round=1, total=24, min_per_cluster=4, reference=reference)
    representative = [target for target in curriculum.targets if target.keys == (REPRESENTATIVE_KEY,)]
    tail = [target for target in curriculum.targets if target.keys != (REPRESENTATIVE_KEY,)]
    assert sum(target.count for target in representative) == 12, "policy share 0.5 of 24 rows"
    assert sum(target.count for target in tail) == 12
    assert representative[0].where == {"workflow": "inventory_exception_review"}
    assert curriculum.mix is not None and curriculum.mix.ok and curriculum.mix.measured_on == "plan"
    dumped = curriculum.model_dump(mode="json", by_alias=True, exclude={"plan"})
    assert dumped["mix"]["dimension"] == "workflow"
    DatasetPlan.model_validate(curriculum.plan)

    # A reference the tail strata pin away from: the representative share is raised to hold the limit.
    shapes = ReferenceMix(dimension="dag_shape", volumes={"fan_in": 1.0, "map_read": 1.0})
    pinned = design_curriculum(report, base, round=1, total=24, min_per_cluster=4, reference=shapes,
                               representative_share=0.25, max_mix_tvd=0.1)
    assert pinned.mix is not None and pinned.mix.tvd <= 0.1 + 1 / 24
    kept = sum(target.count for target in pinned.targets if target.keys == (REPRESENTATIVE_KEY,))
    assert kept >= 6
    # Every failure target pins a failure the reference never holds, and no drift is allowed: no room is left.
    clean = ReferenceMix(dimension="failure", volumes={"none": 1.0})
    with pytest.raises(ValueError, match="under the floor"):
        design_curriculum(report, base, round=1, total=8, min_per_cluster=4, reference=clean, max_mix_tvd=0.0)

    # Scored apart: each case goes where its stratum says.
    ids = sorted(row.case_id for row in runs["mixed"].results)
    strata = {case_id: (representative[0].stratum if index % 2 else tail[0].stratum) for index, case_id in enumerate(ids)}
    scores = mix_scores(runs["mixed"], curriculum, strata=strata)
    assert scores.representative.cases + scores.tail.cases == len(ids) and scores.unassigned == 0
    rep_rows = [row for row in runs["mixed"].results if strata[row.case_id] == representative[0].stratum]
    assert scores.representative.passed == sum(1 for row in rep_rows if row.score is not None and row.score.passed)


# -- CLI -------------------------------------------------------------------------------------


def _write_case_set(directory: Path, cases: Any, records: Any) -> None:
    write_jsonl(directory / CASE_SET_FILE, list(cases))
    write_jsonl(directory / RECORDS_FILE, list(records))


def test_the_cli_prints_and_writes_the_value_summary(runs: dict[str, Any], tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    write_run(run_dir, runs["mixed"])
    case_set = tmp_path / "cases"
    _write_case_set(case_set, runs["cases"], runs["records"])
    out = tmp_path / "value.json"
    result = runner.invoke(app, ["evalrun", "value", str(run_dir), "--corpus", str(case_set), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "value-weighted" in result.output and "Costliest failures:" in result.output
    written = json.loads(out.read_text())
    expected = value_summary(RunReport.model_validate(runs["mixed"].model_dump()), runs["cases"], runs["records"])
    assert written["value"] == json.loads(json.dumps(expected.model_dump(mode="json", by_alias=True)))
    result = runner.invoke(app, ["evalrun", "value", str(run_dir), "--corpus", str(case_set), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == written

    refused = runner.invoke(app, ["evalrun", "value", str(run_dir), "--corpus", str(case_set), "--mix", "activity"])
    assert refused.exit_code == 2, refused.output
    missing = runner.invoke(app, ["evalrun", "value", str(tmp_path / "missing"), "--corpus", str(case_set)])
    assert missing.exit_code == 2, missing.output


def test_the_cli_compares_a_programme_run_with_the_company_mix(telecom: dict[str, Any], tmp_path: Path) -> None:
    records = telecom["records"]
    index = index_records(records)
    cases = [case for case in telecom["cases"][:200] if value_of(case, index).at_stake is not None][:12]
    report = run_cases(service_for(cases, records), cases, ScriptedAgent([], name="lazy"))
    run_dir = tmp_path / "run"
    write_run(run_dir, report)
    case_set = tmp_path / "cases"
    _write_case_set(case_set, telecom["cases"], records)
    result = runner.invoke(app, ["evalrun", "value", str(run_dir), "--corpus", str(case_set), "--mix", "activity", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["value"]["cases"] == 12 and payload["value"]["currency"] == "INR"
    assert payload["mix"]["comparison"]["dimension"] == "activity" and payload["mix"]["comparison"]["tvd"] > 0.3
    text = runner.invoke(app, ["evalrun", "value", str(run_dir), "--corpus", str(case_set), "--mix", "activity"])
    assert text.exit_code == 0, text.output
    assert "Mix over activity" in text.output and "simulated operations" in text.output
