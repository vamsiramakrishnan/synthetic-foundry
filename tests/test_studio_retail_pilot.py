from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import replace
from datetime import timedelta

import pytest

from worldloom import MonthEndClose, RetailWorld
from worldloom.connector_data import builtin_projections, generate_connector_data
from worldloom.enterprise_corpus import (
    materialize_corpus,
    operational_record_case_id,
    validate_corpus,
)
from worldloom.enterprise_evidence import observation_evidence
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.eval_candidates import check_requirement
from worldloom.evals.dataset import _files
from worldloom.retail_replenishment import (
    EVENT_KIND,
    PROCESSES,
    RetailProcess,
    RetailProcessScope,
    build_retail_process,
    case_payload,
    connected_program,
    process_report,
)
from worldloom.studio.construction import bind_query, compile_project
from worldloom.studio.retail_pilot import pilot_project
from worldloom.synthesis.connectors import bind_case_query


@pytest.fixture(scope="module")
def process_world():
    base = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    config = RetailProcess(scopes=tuple(RetailProcessScope(process=process,
        business_unit=base.business_units[0].name, activity_id="p2p.09") for process in PROCESSES))
    return base, config, build_retail_process(base, config)


def test_stock_orders_receipts_and_invoices_share_physical_cases(process_world):
    base, config, world = process_world
    assert world.company == base.company
    assert tuple(world.facts) == tuple(base.facts)
    assert world.validate().ok
    report = process_report(world)
    assert report["cases"] == config.max_cases
    assert report["clean_invoices"] > 0
    assert report["contested_invoices"] > 0
    assert report["orders_beyond_receipt_horizon"] > 0
    assert report["excluded_by_case_budget"] > 0
    cases = {}
    events = {event.id: event for event in world.events}
    for event in world.events:
        payload = case_payload(event)
        if payload is not None:
            cases.setdefault(payload.case_id, {})[payload.scope.process] = (event, payload)
    assert len(cases) == config.max_cases
    for stages in cases.values():
        inventory, order, invoice = [stages[process] for process in PROCESSES]
        assert order[1].history[0] == inventory[1].history[0] == invoice[1].history[0]
        assert order[1].history == invoice[1].history
        assert events[order[0].caused_by[0]] == inventory[0]
        assert events[invoice[0].caused_by[0]] == order[0]
        match = invoice[1].match
        assert match is not None
        assert match.ordered_quantity == match.received_quantity == inventory[1].history[0].values()["order"]
        assert match.invoice_value - match.receipt_contract_value == match.invoice_variance


def test_builtin_sources_validate_scope_observations_and_shared_case(process_world):
    _, config, world = process_world
    observed = {}
    for connector in ("jira", "servicenow", "email"):
        for record in builtin_projections().project(connector, world):
            if "process" not in record.fields:
                continue
            assert observation_evidence(record.fields)[1] == ()
            assert operational_record_case_id(record) == record.fields["case_id"]
            scope = next(scope for scope in config.scopes if scope.process == record.fields["process"])
            assert record.fields["business_unit"] == scope.business_unit
            assert record.fields["activity_id"] == scope.activity_id
            assert record.event_ids == [record.fields["world_event_id"]]
            observed.setdefault(record.fields["case_id"], set()).add((connector, record.fields["process"]))
    assert all(len(items) == 9 for items in observed.values())


def test_invoice_arithmetic_tampering_fails_domain_validation(process_world):
    _, _, world = process_world
    invoice = next(event for event in world.events if event.kind == EVENT_KIND
                   and json.loads(event.summary)["scope"]["process"] == "invoice_reconciliation")
    payload = json.loads(invoice.summary)
    payload["match"]["invoice_value"] += 1
    corrupted = invoice.model_copy(update={"summary": json.dumps(payload)})
    broken = replace(world, _events=tuple(corrupted if event.id == invoice.id else event for event in world.events))
    assert any(v.code == "process_evidence" for v in broken.validate().violations)


def test_internally_consistent_but_forged_physical_history_is_rejected(process_world):
    _, _, world = process_world
    inventory = next(event for event in world.events if event.kind == EVENT_KIND
                     and json.loads(event.summary)["scope"]["process"] == "inventory_exception")
    payload = json.loads(inventory.summary)
    cell = next(cell for cell in payload["history"][0]["cells"] if cell["name"] == "lost")
    cell["value"] += 1
    corrupted = inventory.model_copy(update={"summary": json.dumps(payload)})
    assert case_payload(corrupted) is not None
    broken = replace(world, _events=tuple(corrupted if event.id == inventory.id else event for event in world.events))
    assert any(v.code == "process_evidence" and "recorded physical program" in v.detail
               for v in broken.validate().violations)


def test_retail_step_replays_in_fresh_process_without_studio_import(process_world, tmp_path):
    _, config, world = process_world
    assert build_retail_process(world, config) is world
    world.export(tmp_path / "original")
    script = (
        "from worldloom import World\n"
        "from worldloom.recipe import rebuild\n"
        "import sys\n"
        "source=World.load(sys.argv[1])\n"
        "result=rebuild(source.recipe, ledger=tuple(source.ledger), actor_ledger=tuple(source.actor_ledger))\n"
        "result.validate().raise_if_failed()\n"
        "result.export(sys.argv[2])\n"
    )
    result = subprocess.run([sys.executable, "-c", script, str(tmp_path / "original"), str(tmp_path / "replayed")],
                            capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
    assert _files(tmp_path / "original") == _files(tmp_path / "replayed")
    with pytest.raises(ValueError, match="different configuration"):
        build_retail_process(world, config.model_copy(update={"max_cases": config.max_cases + 1}))


def test_horizon_and_case_budget_do_not_invent_missing_receipts(process_world):
    base, config, _ = process_world
    short = config.model_copy(update={"program": connected_program(stores=1, products=2, ticks=3), "max_cases": 256})
    world = build_retail_process(base, short)
    report = process_report(world)
    assert 0 < report["cases"] < short.max_cases
    assert report["cases"] == report["eligible_complete_cases"]
    assert report["orders_beyond_receipt_horizon"] > 0
    assert report["excluded_by_case_budget"] == 0
    assert world.validate().ok


def test_pilot_requirements_bind_real_company_scopes_and_same_case(tmp_path):
    from worldloom.process_bindings.ownership import materialize_owners
    from worldloom.studio import Studio
    from worldloom.studio.construction import restore_generator

    project = pilot_project(count=3)
    plan = compile_project(project)
    assert plan.accepted, plan.findings
    base, _ = Studio(tmp_path).snapshot(project)
    assert project.structure is not None
    assert project.retail_process is not None
    assert project.retail_process.start is not None
    base = materialize_owners(restore_generator(base), project.structure,
                              formed_at=project.retail_process.start - timedelta(hours=1))
    for case in project.use_cases:
        assert case.construction is not None
        assert all(not check_requirement(requirement, base).satisfied for requirement in case.construction.requirements)
    world = build_retail_process(base, project.retail_process)
    records = generate_connector_data(world, ("jira", "servicenow", "email")).records
    for case in project.use_cases:
        assert case.construction is not None and case.scenario is not None
        assert all(check_requirement(requirement, world).satisfied for requirement in case.construction.requirements)
        queries, _ = EnterpriseEvalHarness.from_world(world).with_scenario(case.scenario).take(1).plan()
        query = bind_case_query(bind_query(plan, case.id, queries[0]), records)
        corpus = materialize_corpus(world, (query,), strict_sources=True)
        assert not validate_corpus(corpus)
        by_id = {record.id: record for record in corpus.connector_data.records}
        selected = [by_id[record_id] for ids in corpus.fixtures[0].input_record_ids.values() for record_id in ids]
        assert len({record.fields["case_id"] for record in selected}) == 1
        assert {record.fields["process"] for record in selected} == {case.id.replace("-", "_")}
        assert {record.fields["business_unit"] for record in selected} == {case.owner}
