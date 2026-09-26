"""Campaigns: the outer loop that keeps improving an agent after one case set is spent.

The agent under test reads its policy for real, and each slice of cases
needs its own skill: it walks the expected DAG of a `fan_in` case when its
pack teaches `verify`, of any harder shape when it teaches `chain`, and does
nothing otherwise. The proposer learns one skill per call, the next one it
does not yet have. So a campaign's first stage promotes `verify` and the
champion saturates; only a stage built from a harder slice can teach it
anything more, and the second stage is that slice, built fresh. The builder
is scripted (cases cloned from one real case under fresh ids, relabelled
with the slice the campaign asked for), which is the `StageBuilder` seam
working as designed; the dataset builder is checked on its plans and, end
to end, through the CLI on a small compiled corpus.
"""

from __future__ import annotations

import importlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.corpus import write_jsonl
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    EvalSession,
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.autopsy import autopsy
from worldloom.evalrun.campaign import (
    CampaignReport,
    CornerStageBuilder,
    DatasetStageBuilder,
    NothingHarder,
    RecordGroups,
    StageExhausted,
    StageOutcome,
    StageRequest,
    campaign,
    campaign_champion,
    case_key,
    read_stage_cases,
    run_grouped,
    stage_seeds,
)
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.curriculum import escalate, harder_shapes
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evals.dataset_contract import DatasetPlan, DatasetSource, DatasetStratum
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()
campaign_module = importlib.import_module("worldloom.evalrun.campaign")

EASY = "fan_in"
SKILLS = ("verify", "chain")


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


@pytest.fixture(scope="module")
def seed_case(corpus: Any) -> Any:
    """One real case the reference agent solves and an idle agent fails: every scripted case is a clone of it."""
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    good = run_cases(service_for(cases, records), cases, ReferenceAgent(cases))
    idle = run_cases(service_for(cases, records), cases, ScriptedAgent([], name="idle"))
    for case, ok, bad in zip(cases, good.results, idle.results, strict=True):
        if ok.score is not None and ok.score.passed and not (bad.score is not None and bad.score.passed):
            return case
    raise AssertionError("the corpus holds no case the reference solves and an idle agent fails")


class PolicyAgent:
    """Solves a case when its policy teaches the skill that case's slice needs; otherwise does nothing."""

    def __init__(self, pack: Any, registry: dict[str, Any]) -> None:
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.skills = set(pack.body.skills)
        self.registry = registry
        self.idle = ScriptedAgent([], name="idle")

    def run(self, task: Any, tools: Any) -> Any:
        case = self.registry[task.case_id]
        need = "verify" if case.dimensions.get("dag_shape") in {EASY, "map_read"} else "chain"
        if need in self.skills:
            return ReferenceAgent([case]).run(task, tools)
        return self.idle.run(task, tools)


def _learner(*, calls: list[str] | None = None, stuck: bool = False) -> Any:
    """A proposer that adds the next skill its draft lacks; ``stuck`` restates the draft instead."""

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        body = dict(payload["draft"]["body"])
        skills = dict(body.get("skills") or {})
        if not stuck:
            missing = [name for name in SKILLS if name not in skills]
            if missing:
                skills[missing[0]] = f"Apply the {missing[0]} discipline to every step."
        body["skills"] = skills
        if calls is not None:
            calls.append(",".join(sorted(skills)))
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    return exchange


def _clone(case: Any, case_id: str, shape: str) -> Any:
    return case.model_copy(update={"id": case_id, "row": {**case.row, "id": case_id},
                                   "dimensions": {**case.dimensions, "dag_shape": shape, "failure": "none"}})


class ScriptedBuilder:
    """Clones one real case into a stage's slice, under ids the stage's seeds make fresh."""

    id = "scripted:v1"

    def __init__(self, case: Any, records: Any, registry: dict[str, Any], *, train: int = 32, held: int = 8,
                 leak: bool = False, exhaust_at: int | None = None) -> None:
        self.case = case
        self.records = tuple(records)
        self.registry = registry
        self.train, self.held = train, held
        self.leak = leak
        self.exhaust_at = exhaust_at
        self.requests: list[StageRequest] = []
        self.first_held: list[Any] = []

    def __call__(self, request: StageRequest) -> Any:
        self.requests.append(request)
        if self.exhaust_at == request.stage:
            raise StageExhausted("the world ran out of events")
        shape = EASY
        if request.mode == "escalate":
            proposals = [item for item in request.proposals() if item.get("dag_shape")]
            if not proposals:
                raise NothingHarder("no slice is saturated; nothing harder to propose")
            shape = proposals[0]["dag_shape"]
        train = [_clone(self.case, f"s{request.stage}-{request.seeds.train[0]}-t{index:02d}", shape)
                 for index in range(self.train)]
        held = [_clone(self.case, f"s{request.stage}-{request.seeds.held[0]}-h{index:02d}", shape)
                for index in range(self.held)]
        if request.stage == 1:
            self.first_held = held
        if self.leak and request.stage == 2:
            train = [*train, *self.first_held]
        for case in (*train, *held):
            self.registry[case.id] = case
        return train, held, self.records, self.records, f"{request.mode}: {self.train} {shape} case(s)"


def _campaign(corpus: Any, seed_case: Any, out: Path, *, builder: Any = None, exchange: Any = None,
              registry: dict[str, Any] | None = None, agent_for: Any = None, **options: Any) -> CampaignReport:
    registry = {} if registry is None else registry
    options.setdefault("rounds", 3)
    options.setdefault("stages", 2)
    return campaign(packkit.resolve("agent:baseline"),
                    builder=builder or ScriptedBuilder(seed_case, corpus.connector_data.records, registry),
                    agent_for=agent_for or (lambda pack: PolicyAgent(pack, registry)),
                    exchange=exchange or _learner(), out=out, seed=7, **options)


# -- the headline --------------------------------------------------------------------------


def test_a_campaign_escalates_after_saturation_and_its_ledger_shows_the_gain(corpus: Any, seed_case: Any,
                                                                           tmp_path: Path) -> None:
    registry: dict[str, Any] = {}
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry)
    calls: list[str] = []
    report = _campaign(corpus, seed_case, tmp_path / "c", builder=builder, exchange=_learner(calls=calls),
                       registry=registry)
    assert report.stopped == "max_stages" and len(report.stages) == 2, report.reasons
    first, second = report.stages
    # Stage 1 teaches `verify` and the champion then passes every training case.
    assert first.mode == "initial" and first.improve.decisions == ("promoted", "no_failures")
    assert first.status == "saturated" and first.improve.promotions == 1
    # Stage 2 was built fresh from a harder slice escalation proposed.
    assert second.mode == "escalate" and builder.requests[1].mode == "escalate"
    assert second.escalations and second.escalations[0]["dag_shape"] in harder_shapes(EASY)
    assert all(case.dimensions["dag_shape"] == second.escalations[0]["dag_shape"]
               for case in read_stage_cases(tmp_path / "c" / "stages" / "002" / "cases" / "train")[0])
    assert second.improve.decisions[0] == "promoted" and second.status == "saturated"
    assert calls == ["verify", "chain,verify"], "one skill learned per stage"
    # The ledger: the original policy against the current one, on each stage's never-seen cases.
    assert [entry.stage for entry in report.ledger] == [1, 2]
    for record, entry in zip(report.stages, report.ledger, strict=True):
        assert entry == record.ledger
        assert entry.original.digest == report.original["digest"]
        assert entry.original.passed == 0 and entry.current.passed == entry.held_cases == 8
        assert entry.mean_delta > 0 and entry.pass_rate_delta == 1.0 and entry.improvements == 8
    assert report.ledger[1].current.digest == report.champion["digest"] != report.original["digest"]
    assert first.ledger.current.digest == first.improve.champion_after["digest"]
    # Ledger runs are marked held out, so an export refuses them.
    for side in ("original", "current"):
        run = json.loads((tmp_path / "c" / "stages" / "001" / "ledger" / side / "run.json").read_text())
        assert run["split"] == "holdout"
    stored = json.loads((tmp_path / "c" / "campaign.json").read_text())
    assert stored["schema"] == "worldloom.campaign/v1" and stored["stopped"] == "max_stages"
    assert CampaignReport.model_validate(stored) == report
    assert json.loads((tmp_path / "c" / "stages" / "001" / "stage.json").read_text())["schema"] == "worldloom.campaign-stage/v1"
    assert campaign_champion(report, tmp_path / "c").digest == report.champion["digest"]
    assert report.cases_spent == 2 * (32 + 8)


def test_no_held_out_case_ever_trains_and_seeds_are_fresh_and_recorded(corpus: Any, seed_case: Any,
                                                                        tmp_path: Path) -> None:
    report = _campaign(corpus, seed_case, tmp_path / "c")
    root = tmp_path / "c" / "stages"
    trained: set[str] = set()
    held: list[set[str]] = []
    for record in report.stages:
        train_cases, _ = read_stage_cases(root / f"{record.stage:03d}" / "cases" / "train")
        held_cases, groups = read_stage_cases(root / f"{record.stage:03d}" / "cases" / "held")
        assert isinstance(groups, RecordGroups)
        trained |= {case_key(case) for case in train_cases}
        held.append({case_key(case) for case in held_cases})
    for keys in held:
        assert keys and keys.isdisjoint(trained)
    # Seeds derive from the campaign seed and the stage, and skip every seed used before.
    used: set[int] = set()
    for record in report.stages:
        assert record.seeds == stage_seeds(7, record.stage, used=used)
        assert used.isdisjoint(record.seeds.all()) and len(set(record.seeds.all())) == 2
        used |= set(record.seeds.all())
    assert stage_seeds(7, 1) != stage_seeds(8, 1) and stage_seeds(7, 1) != stage_seeds(7, 2)
    # The same campaign seed writes the same campaign, byte for byte.
    _campaign(corpus, seed_case, tmp_path / "again")
    assert (tmp_path / "again" / "campaign.json").read_bytes() == (tmp_path / "c" / "campaign.json").read_bytes()


def test_a_completed_stage_is_read_back_not_rerun(corpus: Any, seed_case: Any, tmp_path: Path) -> None:
    registry: dict[str, Any] = {}
    first = _campaign(corpus, seed_case, tmp_path / "c", registry=registry, stages=1)
    written = (tmp_path / "c" / "stages" / "001" / "stage.json").read_bytes()

    class Refusing:
        id = "scripted:v1"

        def __init__(self, inner: Any) -> None:
            self.inner = inner
            self.stages: list[int] = []

        def __call__(self, request: StageRequest) -> Any:
            assert request.stage != 1, "a completed stage must not be rebuilt"
            self.stages.append(request.stage)
            return self.inner(request)

    def no_proposer(payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("a completed stage must not ask the proposer again")

    again = _campaign(corpus, seed_case, tmp_path / "c", registry=registry, stages=1,
                      builder=Refusing(ScriptedBuilder(seed_case, corpus.connector_data.records, registry)),
                      exchange=no_proposer)
    assert again == first
    assert (tmp_path / "c" / "stages" / "001" / "stage.json").read_bytes() == written
    # Extending the campaign continues from the stored champion and pays only for the new stage.
    inner = ScriptedBuilder(seed_case, corpus.connector_data.records, registry)
    extended = _campaign(corpus, seed_case, tmp_path / "c", registry=registry, stages=2, builder=Refusing(inner))
    assert extended.stages[0] == first.stages[0] and len(extended.stages) == 2
    assert inner.requests[0].stage == 2 and inner.requests[0].champion.digest == first.champion["digest"]
    with pytest.raises(ValueError, match="another seed or champion"):
        campaign(packkit.resolve("agent:baseline"), builder=inner, agent_for=lambda pack: PolicyAgent(pack, registry),
                 exchange=_learner(), out=tmp_path / "c", seed=8)


# -- stopping -----------------------------------------------------------------------------------


def test_escalation_that_proposes_nothing_harder_stops_the_campaign(corpus: Any, seed_case: Any,
                                                                    tmp_path: Path) -> None:
    registry: dict[str, Any] = {}
    # Eight passes are not enough for any slice's interval to clear the band.
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry, train=8, held=4)
    report = _campaign(corpus, seed_case, tmp_path / "c", builder=builder, registry=registry, stages=3)
    assert [record.status for record in report.stages] == ["saturated"]
    assert report.stopped == "nothing_harder" and "stage 2 (escalate)" in report.reasons[0]
    assert builder.requests[1].escalations == () or not builder.requests[1].proposals()


def test_a_builder_that_leaks_a_held_out_case_into_training_is_refused(corpus: Any, seed_case: Any,
                                                                       tmp_path: Path) -> None:
    registry: dict[str, Any] = {}
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry, leak=True)
    report = _campaign(corpus, seed_case, tmp_path / "c", builder=builder, registry=registry)
    assert report.stopped == "held_out_overlap" and len(report.stages) == 1
    assert "held out by an earlier stage" in report.reasons[0]
    assert not (tmp_path / "c" / "stages" / "002" / "stage.json").exists()
    refused = json.loads((tmp_path / "c" / "stages" / "002" / "refused.json").read_text())
    assert refused["stopped"] == "held_out_overlap"
    assert not (tmp_path / "c" / "stages" / "002" / "improve").exists(), "nothing ran on the leaked set"


def test_the_case_budget_and_an_exhausted_builder_stop_the_campaign(corpus: Any, seed_case: Any,
                                                                    tmp_path: Path) -> None:
    report = _campaign(corpus, seed_case, tmp_path / "budget", max_cases=50)
    assert report.stopped == "case_budget" and len(report.stages) == 1 and report.cases_spent == 40
    assert "10 of the campaign's 50 remain" in report.reasons[0]

    registry: dict[str, Any] = {}
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry, exhaust_at=2)
    report = _campaign(corpus, seed_case, tmp_path / "dry", builder=builder, registry=registry)
    assert report.stopped == "no_new_cases" and "ran out of events" in report.reasons[0]


def test_a_failing_proposer_halts_the_campaign(corpus: Any, seed_case: Any, tmp_path: Path) -> None:
    def broken(payload: dict[str, Any]) -> dict[str, Any]:
        raise OSError("codex: command not found")

    report = _campaign(corpus, seed_case, tmp_path / "c", exchange=broken)
    assert report.stopped == "proposer_error" and len(report.stages) == 1
    assert report.stages[0].status == "halted" and "command not found" in report.stages[0].status_reason
    assert report.ledger[0].mean_delta == 0.0 and report.champion == report.original


def test_a_champion_still_failing_gets_a_targeted_stage_and_a_plateau_escalates(corpus: Any, seed_case: Any,
                                                                                tmp_path: Path) -> None:
    registry: dict[str, Any] = {}
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry, train=8, held=4)
    report = _campaign(corpus, seed_case, tmp_path / "target", builder=builder, registry=registry,
                       exchange=_learner(stuck=True), rounds=1, patience=2)
    assert [record.status for record in report.stages] == ["failing", "failing"]
    assert [record.mode for record in report.stages] == ["initial", "target"]
    request = builder.requests[1]
    assert request.autopsy is not None and request.autopsy.failing == 8
    assert report.stages[1].targets == tuple(cluster.key for cluster in request.autopsy.clusters)

    registry = {}
    builder = ScriptedBuilder(seed_case, corpus.connector_data.records, registry, train=8, held=4)
    report = _campaign(corpus, seed_case, tmp_path / "plateau", builder=builder, registry=registry,
                       exchange=_learner(stuck=True), rounds=2, patience=2)
    assert report.stages[0].status == "plateaued" and report.stages[0].improve.decisions == ("unchanged", "unchanged")
    assert builder.requests[1].mode == "escalate" and report.stopped == "nothing_harder"


def test_the_campaign_refuses_to_be_handed_what_it_owns(corpus: Any, seed_case: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="holdout"):
        _campaign(corpus, seed_case, tmp_path / "c", holdout=())


# -- running over several worlds -------------------------------------------------------------------


def test_record_groups_serve_each_world_on_its_own(corpus: Any, seed_case: Any) -> None:
    records = tuple(corpus.connector_data.records)
    cases = [_clone(seed_case, f"g-{index}", EASY) for index in range(4)]
    one = run_grouped(cases, records, ReferenceAgent(cases))
    groups = RecordGroups(groups=((("g-0", "g-2"), records), (("g-1", "g-3"), records)))
    two = run_grouped(cases, groups, ReferenceAgent(cases))
    assert [row.case_id for row in two.results] == [case.id for case in cases]
    assert two.case_set == one.case_set
    assert [row.score.passed if row.score else None for row in two.results] == \
        [row.score.passed if row.score else None for row in one.results]
    with pytest.raises(ValueError, match="no record group"):
        RecordGroups(groups=((("g-0",), records),)).split(cases)


# -- the dataset builder ---------------------------------------------------------------------------


def _base_plan(count: int = 6) -> DatasetPlan:
    source = DatasetSource(
        company={"engine": "retail"}, scenario=operational_profile("retail"),
        simulation=with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}),
        incident_rule=IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        dag_shapes=("fan_in", "map_read"), pool_size=12, planning_budget=64,
    )
    return DatasetPlan(strata=(DatasetStratum(id="retail", count=count, source=source),), max_batches=6,
                       split_by="company", max_per_task=3, max_per_request=3, minimum_tasks=2)


def _request(mode: str, *, previous: Any = None, found: Any = None, escalations: tuple[Any, ...] = (),
             workdir: Path = Path("unused")) -> StageRequest:
    return StageRequest(stage=2, mode=mode, seeds=stage_seeds(3, 2, used=(8128,)),
                        champion=packkit.resolve("agent:baseline"), previous=previous, autopsy=found,
                        escalations=escalations, sealed=frozenset(), budget=None, workdir=workdir,
                        agent_for=lambda pack: ScriptedAgent([], name="idle"))


def test_the_dataset_builder_plans_each_mode_under_the_stages_seeds(corpus: Any) -> None:
    base = _base_plan(8)
    builder = DatasetStageBuilder(base, held_ratio=0.5)
    assert builder.reserved_seeds == (8128,) and builder.id.startswith("dataset:")
    train, held, description = builder.plans(_request("initial"))
    seeds = stage_seeds(3, 2, used=(8128,))
    assert (train.seed, held.seed) == (seeds.train[0], seeds.held[0]) and 8128 not in (train.seed, held.seed)
    assert train.split_weights == {"train": 100} and held.split_weights == {"test": 100}
    assert [s.count for s in train.strata] == [8] and [s.count for s in held.strata] == [4]
    assert description.startswith("initial:")

    cases = cases_from_corpus(corpus)
    lazy = run_cases(service_for(cases, corpus.connector_data.records), cases, ScriptedAgent([], name="lazy"))
    found = autopsy(lazy, cases=cases)
    outcome = StageOutcome(stage=1, status="failing", champion=packkit.resolve("agent:baseline"),
                           train_cases=tuple(cases), train_records=RecordGroups.of(corpus.connector_data.records, cases),
                           champion_run=lazy)
    train, held, description = builder.plans(_request("target", previous=outcome, found=found))
    assert description.startswith("target:") and sum(s.count for s in train.strata) == 8
    assert all(stratum.source.where for stratum in train.strata)
    assert [s.id for s in train.strata] == [s.id for s in held.strata]

    passing = next(row for row in run_cases(service_for(cases, corpus.connector_data.records), cases,
                                            ReferenceAgent(cases)).results if row.score and row.score.passed)
    saturated = lazy.model_copy(update={"results": tuple(
        passing.model_copy(update={"case_id": f"easy-{index:02d}",
                                   "dimensions": {**passing.dimensions, "dag_shape": EASY, "failure": "none"}})
        for index in range(30))})
    escalations = tuple(escalate(saturated))
    train, held, description = builder.plans(_request("escalate", escalations=escalations))
    assert description.startswith("escalate:")
    # One stratum per proposal, the saturated slice's own first: a harder shape under the same failure.
    assert dict(train.strata[0].source.where) == escalations[0].proposals[0]
    assert train.strata[0].source.where["dag_shape"] in harder_shapes(EASY)
    assert train.strata[0].source.dag_shapes == (train.strata[0].source.where["dag_shape"],)
    with pytest.raises(NothingHarder):
        builder.plans(_request("escalate"))


# -- the SDK and the CLI -------------------------------------------------------------------------------


def test_the_session_runs_a_campaign_from_its_cases(corpus: Any, seed_case: Any, tmp_path: Path) -> None:
    registry: dict[str, Any] = {case.id: case for case in cases_from_corpus(corpus)}
    session = EvalSession.open(corpus)
    loop = session.campaign(agent=lambda pack: PolicyAgent(pack, registry), proposer=_learner(),
                            out=tmp_path / "c", builder=ScriptedBuilder(seed_case, corpus.connector_data.records,
                                                                        registry, train=8, held=4),
                            seed=7, rounds=3)
    report = loop.run("agent:baseline", stages=1)
    assert report.baseline is not None and report.baseline["cases"] == len(session.cases)
    # The champion fails the session's cases, so the first stage targets its failures.
    assert report.stages[0].mode == "target" and report.stages[0].improve.promotions == 1
    assert loop.champion(report).digest == report.champion["digest"]


def test_the_cli_runs_a_campaign_end_to_end(corpus: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    case_set = tmp_path / "cases"
    write_jsonl(case_set / CASE_SET_FILE, list(cases_from_corpus(corpus)))
    write_jsonl(case_set / RECORDS_FILE, list(corpus.connector_data.records))
    plan = tmp_path / "base.json"
    plan.write_text(json.dumps(_base_plan(6).model_dump(mode="json")), encoding="utf-8")
    registry: dict[str, Any] = {}
    original = campaign_module.run_grouped

    def registering(cases: Any, records: Any, agent: Any, **options: Any) -> Any:
        registry.update({case.id: case for case in cases})
        return original(cases, records, agent, **options)

    harness_module = importlib.import_module("worldloom.evalrun.harness")
    authoring_module = importlib.import_module("worldloom.packkit.authoring")
    monkeypatch.setattr(campaign_module, "run_grouped", registering)
    monkeypatch.setattr(harness_module, "ExecAgent",
                        lambda command, *, policy, **options: PolicyAgent(policy, registry))
    monkeypatch.setattr(authoring_module, "run_exec_exchange", lambda command, **options: _learner())
    out = tmp_path / "campaign"
    args = ["evalrun", "campaign", str(case_set), "--agent-pack", "agent:baseline", "--exec", "agent",
            "--proposer-exec", "proposer", "--plan", str(plan), "-o", str(out), "--stages", "2", "--seed", "5",
            "--rounds", "2"]
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    assert "stage 1 (target)" in result.output and "stopped:" in result.output
    report = CampaignReport.model_validate_json((out / "campaign.json").read_text())
    first = report.stages[0]
    assert first.improve.promotions == 1 and first.builder.startswith("dataset:")
    assert first.ledger.current.mean > first.ledger.original.mean
    assert (out / "stages" / "001" / "build" / "train" / "manifest.json").exists()
    # Six training cases cannot saturate a slice, so the escalation after stage 1 has nothing to propose.
    assert first.status == "saturated" and report.stopped == "nothing_harder", report.reasons
    assert "stopped: nothing_harder" in result.output
    # Run again: every stage is read back, and --json prints what campaign.json holds.
    result = runner.invoke(app, [*args, "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == json.loads((out / "campaign.json").read_text())


def test_the_corner_builder_draws_fresh_worlds_and_escalates_to_the_frontier(tmp_path: Path) -> None:
    builder = CornerStageBuilder(engine="retail", worlds=2, budget=10)
    assert builder.seeds_per_set == 2 and builder.id == "corners:retail:all:2"
    request = replace(_request("initial", workdir=tmp_path), seeds=stage_seeds(3, 2, count=2))
    train, held, train_records, held_records, description = builder(request)
    assert train and held and description.startswith("initial:")
    assert {case_key(case) for case in train}.isdisjoint(case_key(case) for case in held)
    # Every world is its own record group.
    assert train_records.split(train) and held_records.split(held)
    assert len(train_records.groups) + len(held_records.groups) >= 3
    frontier_train, _, _, _, how = builder(replace(request, mode="escalate"))
    assert how.startswith("escalate:") and frontier_train, "an idle champion fails every corner the reference solves"
