"""Search honesty, real child-process seams, evidence-backed connector use."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld
from worldloom.cli import app
from worldloom.enterprise_corpus import materialize_corpus, validate_corpus
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.synthesis import (
    Axis,
    IncidentRule,
    Limits,
    Metric,
    Simulator,
    SynthesisError,
    Target,
    exception_episodes,
    measure,
    operational_profile,
    operational_projections,
    retail,
    retail_search_plan,
    search,
    with_parameters,
)
from worldloom.synthesis.compiler import canonical
from worldloom.synthesis.harness import (
    Agent,
    CheckpointLedger,
    run_team,
)
from worldloom.synthesis.storage import write_program


def program():
    return retail(stores=2, products=3, ticks=8)


def plan(proposals=8):
    return retail_search_plan(proposals=proposals)


def test_search_is_repeatable_and_its_champions_really_pass() -> None:
    a = search(program(), plan())
    b = search(program(), plan())
    assert canonical(a.model_dump(mode="json")) == canonical(b.model_dump(mode="json"))
    assert a.evaluated <= 8
    assert len(a.champions) >= 2
    for champion in a.champions:
        assert champion.candidate.evaluation.accepted
        assert champion.holdout.accepted
        values = {p.name: p.value for p in champion.candidate.parameters}
        modified = with_parameters(program(), values)
        assert modified.tables == program().tables, "search must not rewrite constraints or mechanisms"
        actual = measure(Simulator(modified, seed=champion.holdout.seeds[0].seed), plan().metrics)
        assert actual == champion.holdout.seeds[0].readings


def test_holdout_cannot_influence_parent_selection_or_training_archive() -> None:
    original = plan(12)
    alternate = original.model_copy(update={"holdout_seeds": (901, 902)})
    a, b = search(program(), original), search(program(), alternate)
    assert a.candidates == b.candidates
    assert [c.candidate for c in a.champions] == [c.candidate for c in b.champions]
    assert a.evaluator_digest != b.evaluator_digest


def test_hard_gates_cannot_be_traded_for_novelty() -> None:
    impossible = plan().model_copy(update={"gates": (Target(metric="stockout_ppm", minimum=-2, maximum=-1),)})
    report = search(program(), impossible)
    assert not report.champions
    assert all(c.status in {"rejected", "duplicate"} for c in report.candidates)
    assert any("gate:stockout_ppm" in f for c in report.candidates if c.evaluation for f in c.evaluation.findings)


@pytest.mark.parametrize("change,code", [
    ({"holdout_seeds": (101, 808)}, "seed_partition"),
    ({"training_seeds": ()}, "seed_partition"),
    ({"axes": (Axis(metric="missing", boundaries=(1,)),)}, "axis_contract"),
    ({"axes": (Axis(metric="stockout_ppm", boundaries=(2, 1)),)}, "axis_contract"),
    ({"metrics": (Metric(name="x", table="inventory", column="absent"),), "axes": (Axis(metric="x", boundaries=(1,)),), "targets": ()}, "metric_contract"),
])
def test_search_refuses_invalid_evaluator_contracts(change, code) -> None:
    with pytest.raises(SynthesisError, match=code):
        search(program(), plan().model_copy(update=change))


def test_search_refuses_an_unbounded_overall_evaluation_budget() -> None:
    with pytest.raises(SynthesisError, match="evaluation_budget"):
        search(program(), plan(), limits=Limits(max_evaluation_work=1))


def test_parameter_mutation_cannot_expand_its_own_bounds() -> None:
    p = program()
    with pytest.raises(SynthesisError, match="parameter_bounds"):
        with_parameters(p, {"target_stock": 201})
    with pytest.raises(SynthesisError, match="parameter_bounds"):
        with_parameters(p, {"target_stock": True})
    with pytest.raises(SynthesisError, match="unknown_parameter"):
        with_parameters(p, {"new_parameter": 1})
    protected = p.model_copy(update={"parameters": tuple(x.model_copy(update={"mutable": False}) for x in p.parameters)})
    with pytest.raises(SynthesisError, match="protected_parameter"):
        with_parameters(protected, {"target_stock": 1 + p.parameters[0].value})


@pytest.fixture
def agents(tmp_path):
    script = tmp_path / "agent.py"
    script.write_text('''import json,sys
p=json.load(sys.stdin)
assert "holdout_seeds" not in p
if p["role"] == "critic":
    out={"concerns":["These are uncalibrated simulation assumptions."],"suggestions":[{"name":"target_stock","value":25}]}
else:
    out={"parameters":[{"name":"target_stock","value":15+10*p["round"]}],"rationale":"Exercise a different stock regime."}
print(json.dumps(out))
''')
    return (Agent(name="designer", command=f'"{sys.executable}" "{script}"', version="test-v1"),
            Agent(name="critic", command=f'"{sys.executable}" "{script}"', version="test-v1"))


def test_real_child_team_replays_without_executing_any_child(agents, monkeypatch, tmp_path) -> None:
    designer, critic = agents
    store = CheckpointLedger(tmp_path / "receipts")
    live = run_team(program(), plan(2), (designer,), critics=(critic,), on_entry=store.append)
    assert len(live.ledger) == 4
    assert len(store.read()) == 4
    assert live.champions
    assert all(attempt.critiques for attempt in live.attempts)
    def forbidden(*args, **kwargs):
        pytest.fail("offline replay attempted a child call")
    monkeypatch.setattr("worldloom.synthesis.harness.run_exec", forbidden)
    replayed = run_team(program(), plan(2), (designer,), critics=(critic,), ledger=store.read(), replay=True)
    assert live == replayed
    # Re-publishing a known immutable receipt is harmless.
    store.append(live.ledger[0])
    assert len(store.read()) == 4


def test_a_missing_replay_receipt_never_falls_through_to_a_model(agents, monkeypatch) -> None:
    monkeypatch.setattr("worldloom.synthesis.harness.run_exec", lambda *a, **kw: pytest.fail("called a model"))
    with pytest.raises(SynthesisError, match="ledger_miss"):
        run_team(program(), plan(1), (agents[0],), replay=True)


def test_invalid_team_plan_is_rejected_before_any_exec(agents, monkeypatch) -> None:
    monkeypatch.setattr("worldloom.synthesis.harness.run_exec", lambda *a, **kw: pytest.fail("called a model"))
    invalid = plan(1).model_copy(update={"metrics": tuple(m.model_copy(update={"table": "bad"}) for m in plan(1).metrics)})
    with pytest.raises(SynthesisError, match="metric_contract"):
        run_team(program(), invalid, (agents[0],))


def test_critic_cannot_authorize_an_invalid_candidate(agents, monkeypatch) -> None:
    from worldloom.execseam import ExecReply
    def executable(command, payload, **kwargs):
        return ExecReply(document=(
            {"parameters": [{"name": "target_stock", "value": 10**9}]}
            if payload["role"] == "designer" else {"concerns": [], "suggestions": []}
        ), stderr_tail="")
    monkeypatch.setattr("worldloom.synthesis.harness.run_exec", executable)
    report = run_team(program(), plan(1), (agents[0],), critics=(agents[1],))
    assert not report.champions
    assert "parameter_bounds" in report.attempts[0].findings[0]


def test_corrupt_ledger_is_not_accepted_as_a_cache_hit(agents) -> None:
    original = run_team(program(), plan(1), (agents[0],))
    poisoned = original.ledger[0].model_copy(update={"response_json": '{"parameters":[]}\n'})
    with pytest.raises(SynthesisError, match="ledger_corrupt"):
        run_team(program(), plan(1), (agents[0],), ledger=(poisoned,), replay=True)


def test_multiple_designers_share_measured_feedback_without_sharing_holdout(agents, monkeypatch) -> None:
    from worldloom.execseam import ExecReply
    seen = []
    def executable(command, payload, **kwargs):
        seen.append(payload)
        return ExecReply(document={"parameters": [{"name": "target_stock", "value": 15 + payload["round"] * 30}]}, stderr_tail="")
    monkeypatch.setattr("worldloom.synthesis.harness.run_exec", executable)
    first = agents[0]
    second = first.model_copy(update={"name": "second-designer"})
    report = run_team(program(), plan(2), (first, second))
    assert [a.designer for a in report.attempts] == ["designer", "second-designer"]
    assert seen[1]["feedback"]["evaluation"]["seeds"]
    assert seen[1]["archive"]
    assert all("holdout" not in json.dumps(payload) for payload in seen)


def case_simulator():
    return Simulator(with_parameters(retail(stores=2, products=3, ticks=12),
                                     {"initial_stock": 8, "target_stock": 15}))


def test_exception_lifecycles_carry_resolution_evidence() -> None:
    sim = case_simulator()
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    episodes = list(exception_episodes(sim, rule))
    assert episodes and any(e.stop is not None for e in episodes)
    for e in episodes:
        assert e.start == e.observations[0].tick
        assert all(r.entity_id == e.entity_id for r in e.observations)
        assert [r.tick for r in e.observations] == list(range(e.start, e.observations[-1].tick + 1))
        assert all(r.values()["lost"] > 0 for r in e.observations[:-1])
        if e.stop is not None:
            assert e.observations[-1].tick == e.stop
            assert e.observations[-1].values()["lost"] == 0
        else:
            assert e.observations[-1].values()["lost"] > 0


def test_connector_case_joins_share_actual_record_evidence() -> None:
    sim = case_simulator()
    world = RetailWorld(seed=8128).build()
    before = world.recipe
    projections = operational_projections(sim, IncidentRule(table="inventory", signal="lost", title="Stock availability"), include_world_records=False)
    records = [record for connector in ("jira", "servicenow", "email") for record in projections.project(connector, world)]
    assert len(records) > 3
    source = {row.id: row for row in sim.rows()}
    cases = {}
    for record in records:
        assert not record.fact_ids, "a generated row must not impersonate a World fact"
        cases.setdefault(record.fields["case_id"], []).append(record)
        provenance = record.fields["synthesis_provenance"]
        assert provenance["recipe_digest"] == sim.run_digest
        for observation in record.fields["history"]:
            assert observation["values"] == source[observation["record_id"]].values()
    assert all({r.connector for r in group} == {"jira", "servicenow", "email"} for group in cases.values())
    assert world.recipe == before


def test_projection_has_an_explicit_materialization_budget() -> None:
    with pytest.raises(SynthesisError, match="projection_budget"):
        operational_projections(case_simulator(), IncidentRule(table="inventory", signal="lost", title="Stock"), max_observations=1)


def incident_harness(world, sim):
    profile = operational_profile("retail")
    return EnterpriseEvalHarness.from_world(world).with_scenario(profile).with_operational_data(
        sim, IncidentRule(table="inventory", signal="lost", title="Stock availability"), include_world_records=False
    ).take(8)


def test_operational_sources_run_through_existing_enterprise_sdk() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    harness = incident_harness(world, case_simulator())
    corpus, _ = harness.build()
    assert corpus.queries and corpus.fixtures
    assert not validate_corpus(corpus)
    by_id = {r.id: r for r in corpus.connector_data.records}
    for fixture in corpus.fixtures:
        for selected in fixture.input_record_ids.values():
            assert selected
            assert all(by_id[rid].fields.get("synthesis_provenance") for rid in selected)
    assert not any(r.fields.get("generated_for_query_requirements") for r in corpus.connector_data.records)


def test_strict_mode_refuses_missing_sources_instead_of_inventing_evidence() -> None:
    from worldloom.connector_data import ConnectorProjectionRegistry
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
    harness = incident_harness(world, case_simulator())
    queries, _ = harness.plan()
    empty = ConnectorProjectionRegistry({name: lambda w: [] for name in ("jira", "servicenow", "email")})
    with pytest.raises(ValueError, match="missing_source"):
        materialize_corpus(world, queries, projections=empty, strict_sources=True)


def test_cli_build_verify_compare_and_refusal_envelope(tmp_path, monkeypatch) -> None:
    runner = CliRunner()
    spec = tmp_path / "spec.json"
    write_program(program(), spec)
    for argv in (["synth", "check", str(spec)],
                 ["synth", "build", str(spec), str(tmp_path / "base")],
                 ["synth", "verify", str(tmp_path / "base")]):
        result = runner.invoke(app, argv)
        assert result.exit_code == 0, result.output
    changes = tmp_path / "change.json"
    changes.write_text('[{"table":"inventory","column":"demand","value":100,"start":2,"stop":3,"entities":[0]}]')
    result = runner.invoke(app, ["synth", "intervene", str(tmp_path / "base"), str(changes), str(tmp_path / "twin")])
    assert result.exit_code == 0, result.output
    result = runner.invoke(app, ["synth", "compare", str(tmp_path / "base"), str(tmp_path / "twin")])
    assert result.exit_code == 0, result.output
    assert [json.loads(line) for line in result.output.splitlines()]
    monkeypatch.setenv("WORLDLOOM_OUTPUT", "json")
    result = runner.invoke(app, ["synth", "build", str(spec), str(tmp_path / "base")])
    assert result.exit_code != 0
    envelope = json.loads(result.output)
    assert envelope["refusal"] == "synthesis_failed"
    assert envelope["data"]["finding"]["code"] == "destination_exists"


def test_ci_reference_build_uses_the_fixed_narration_contract(tmp_path) -> None:
    """Reproduce the CLI path that used to disagree with the passing SDK test."""
    runner = CliRunner()
    path = tmp_path / "reference"
    result = runner.invoke(app, ["build", "--seed", "8128", "--incident", "--archetype", "australian_grocery",
                                 "--comparatives", "11", "--section-omission", "0", "--outline-synthesis", "0",
                                 "--variant-bias", "0", "--out", str(path)])
    assert result.exit_code == 0, result.output
    narration = Path(__file__).resolve().parents[1] / "examples/grocery-close/narration.json"
    result = runner.invoke(app, ["narrate", "accept", str(path), "--from", str(narration), "--model-id", "claude-agents"])
    assert result.exit_code == 0, result.output


def test_banking_queries_use_servicing_cases_and_real_message_threads() -> None:
    from worldloom import BankingWorld
    from worldloom.synthesis import banking

    world = BankingWorld(seed=8128).build()
    sim = Simulator(banking(borrowers=8, ticks=8), seed=8128)
    harness = (EnterpriseEvalHarness.from_world(world)
               .with_scenario(operational_profile("banking"))
               .with_operational_data(sim, IncidentRule(table="loan", signal="arrears", title="Payment arrears"),
                                      include_world_records=False).take(8))
    corpus, _ = harness.build()
    assert corpus.queries and not validate_corpus(corpus)
    records = {record.id: record for record in corpus.connector_data.records}
    assert {record.connector for record in records.values()} <= {"salesforce", "email"}
    threads = [record for record in records.values() if record.entity == "thread"]
    assert threads
    for thread in threads:
        for message_id in thread.fields["message_record_ids"]:
            message = records[message_id]
            assert message.entity == "message"
            assert message.fields["case_id"] == thread.fields["case_id"]
    assert not any(r.fields.get("generated_for_query_requirements") for r in records.values())
