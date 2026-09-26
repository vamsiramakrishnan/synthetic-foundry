"""The improvement loop from Python: a few lines on an ``EvalSession``, the same loop the CLI runs.

The session builds ``improve()``'s callables (runner, agent factory,
proposer, rater) rather than reimplementing the loop, so the first thing
checked is that a loop driven through it and one driven through
``improve()`` directly leave identical reports. The conveniences for the
loop's parts (autopsy, curriculum, escalation, export, agreement) must
return exactly what the low-level functions return, and concurrency must
change nothing but the wall time. The skill that teaches the loop is
checked here too: its frontmatter, and that every reference it routes to
exists and is routed to.
"""

from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

import pytest

from worldloom import RetailWorld, packkit
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    EvalSession,
    ExecHarness,
    GroundedRater,
    ImproveLoop,
    ImproveReport,
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    import_studio_results,
    run_cases,
    service_for,
)
from worldloom.evalrun.agreement import agreement
from worldloom.evalrun.autopsy import autopsy, render_brief
from worldloom.evalrun.curriculum import design_curriculum, escalate
from worldloom.evalrun.export import (
    HoldoutRefused,
    preference_pairs,
    reward_records,
    sft_records,
)
from worldloom.evalrun.harness import ExecAgent
from worldloom.evalrun.improve import improve
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evals.dataset_contract import DatasetPlan, DatasetSource, DatasetStratum
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / ".claude" / "skills" / "worldloom-improve"


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(8)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


class PolicyAgent:
    """Walks the expected DAG when its policy teaches `verify`; otherwise does nothing."""

    def __init__(self, pack: Any, cases: Any) -> None:
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.skilled = "verify" in pack.body.skills
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")

    def run(self, task: Any, tools: Any) -> Any:
        return (self.reference if self.skilled else self.idle).run(task, tools)


def _proposer(body_change: dict[str, Any] | None = None) -> Any:
    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        body = {**payload["draft"]["body"], **(body_change or {})}
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    return exchange


HELPFUL = {"skills": {"verify": "Walk every step the request needs and read each write back."}}


def _dump(report: ImproveReport) -> dict[str, Any]:
    return report.model_dump(mode="json", by_alias=True)


# -- the loop ------------------------------------------------------------------------


def test_the_loop_is_a_few_lines_and_promotes_a_real_improvement(corpus: Any, tmp_path: Path) -> None:
    session = EvalSession.open(corpus)
    champion = session.agent_pack("agent:baseline")
    loop = session.improver(agent=lambda pack: PolicyAgent(pack, session.cases), proposer=_proposer(HELPFUL),
                            out=tmp_path / "improve", holdout_share=0.4)
    assert isinstance(loop, ImproveLoop)
    report = loop.run(champion, rounds=2)

    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    assert first.train is not None and first.train.passed
    assert first.holdout is not None and first.holdout.passed
    assert report.promotions >= 1 and report.champion["digest"] != report.initial["digest"]
    winner = loop.champion(report)
    assert winner.digest == report.champion["digest"] and "verify" in winner.body.skills
    assert (tmp_path / "improve" / "improve.json").exists()
    assert sorted(path.name for path in (tmp_path / "improve" / "rounds").glob("*.json"))[0] == "001.json"
    # A later loop into the same directory starts from the winner by name.
    again = loop.run(report.champion["ref"], rounds=1)
    assert again.initial["digest"] == report.champion["digest"]


def test_the_session_runs_the_same_loop_as_improve(corpus: Any, tmp_path: Path) -> None:
    session = EvalSession.open(corpus)
    cases = session.cases
    records = corpus.connector_data.records
    via_session = session.improver(agent=lambda pack: PolicyAgent(pack, cases), proposer=_proposer(HELPFUL),
                                   out=tmp_path / "sdk", holdout_share=0.4, concurrency=1).run("agent:baseline",
                                                                                               rounds=2)
    direct = improve(packkit.resolve("agent:baseline"), cases,
                     run=lambda subset, agent: run_cases(service_for(subset, records), subset, agent),
                     agent_for=lambda pack: PolicyAgent(pack, cases), exchange=_proposer(HELPFUL),
                     out=tmp_path / "direct", holdout_share=0.4, rounds=2)
    assert _dump(via_session) == _dump(direct)


def test_concurrency_changes_nothing_but_the_wall_time(corpus: Any, tmp_path: Path) -> None:
    session = EvalSession.open(corpus)
    reports = []
    for workers in (1, 4):
        loop = session.improver(agent=lambda pack: PolicyAgent(pack, session.cases), proposer=_proposer(HELPFUL),
                                out=tmp_path / f"c{workers}", holdout_share=0.4, concurrency=workers)
        assert loop.concurrency == workers
        reports.append(_dump(loop.run("agent:baseline", rounds=1)))
    assert reports[0] == reports[1]
    one = session.run(ReferenceAgent(session.cases), label="one")
    four = session.run(ReferenceAgent(session.cases), label="four", concurrency=4)
    assert one.results == four.results
    assert (tmp_path / "c1" / "runs").exists()
    for run_json in sorted((tmp_path / "c1" / "runs").glob("*/*/results.jsonl")):
        twin = tmp_path / "c4" / run_json.relative_to(tmp_path / "c1")
        assert twin.read_bytes() == run_json.read_bytes()


def test_a_held_out_session_is_the_holdout(corpus: Any, tmp_path: Path) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    train = EvalSession(cases[:5], records)
    held = EvalSession(cases[5:], records)
    report = train.improver(agent=lambda pack: PolicyAgent(pack, cases), proposer=_proposer(HELPFUL),
                            out=tmp_path / "improve", holdout=held).run("agent:baseline", rounds=1)
    assert report.train_cases == 5 and report.holdout_cases == len(cases) - 5
    assert report.rounds[0].decision == "promoted", report.rounds[0].reasons


def test_harnesses_and_proposers_by_name_build_what_the_cli_builds(corpus: Any) -> None:
    session = EvalSession.open(corpus)
    made = session.harness(command="python3 my_agent.py", timeout=30, max_turns=5)
    assert isinstance(made, ExecHarness) and made.command == "python3 my_agent.py"
    agent = made(session.agent_pack("agent:baseline"))
    assert isinstance(agent, ExecAgent) and agent.max_turns == 5 and agent.pack_record is not None
    named = EvalSession.harness("codex", timeout=60)
    assert "worldloom.studio.harness" in named.command and "codex" in named.command
    assert callable(session.proposer(command="python3 propose.py"))
    loop = session.improver(agent="exec:python3 my_agent.py", proposer="exec:python3 propose.py",
                            out="unused", rater="grounded")
    assert isinstance(loop.agent, ExecHarness) and isinstance(loop.rater, GroundedRater)
    with pytest.raises(ValueError, match="not both"):
        session.harness("codex", command="python3 my_agent.py")
    with pytest.raises(ValueError, match="unknown rater"):
        session.improver(agent=made, proposer="codex", out="unused", rater="judge")


# -- the loop's parts, one call each ----------------------------------------------------


@pytest.fixture(scope="module")
def ran(corpus: Any) -> EvalSession:
    session = EvalSession.open(corpus)
    session.reference()
    session.run(ScriptedAgent([], name="idle"))
    return session


def _base_plan() -> DatasetPlan:
    source = DatasetSource(
        company={"engine": "retail"}, scenario=operational_profile("retail"),
        simulation=with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15}),
        incident_rule=IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        dag_shapes=("fan_in", "map_read"), pool_size=12, planning_budget=64,
    )
    return DatasetPlan(strata=(DatasetStratum(id="retail", count=12, source=source),), max_batches=6,
                       split_by="company", max_per_task=3, max_per_request=3, minimum_tasks=2)


def test_autopsy_and_brief_match_the_low_level_functions(ran: EvalSession, tmp_path: Path) -> None:
    idle = ran.runs["idle"]
    expected = autopsy(idle, cases=ran.cases)
    assert ran.autopsy("idle") == expected
    assert ran.brief("idle") == render_brief(expected)
    ran.write("idle", tmp_path / "idle")
    assert ran.autopsy(tmp_path / "idle") == autopsy(idle, cases=ran.cases)
    with pytest.raises(KeyError, match="no run labelled"):
        ran.autopsy("missing")


def test_curriculum_and_escalation_match_the_low_level_functions(ran: EvalSession, tmp_path: Path) -> None:
    base = _base_plan()
    expected = design_curriculum(autopsy(ran.runs["idle"], cases=ran.cases), base, round=2, total=12)
    assert ran.curriculum("idle", base, round=2, total=12) == expected
    stored = tmp_path / "base.json"
    stored.write_text(json.dumps(base.model_dump(mode="json")), encoding="utf-8")
    assert ran.curriculum("idle", stored, round=2, total=12) == expected
    assert ran.escalate("reference", "idle") == escalate([ran.runs["reference"], ran.runs["idle"]])


def test_export_matches_the_low_level_functions_and_guards_the_holdout(ran: EvalSession, tmp_path: Path) -> None:
    reference, idle = ran.runs["reference"], ran.runs["idle"]
    assert ran.export("reference", "sft", tools=False) == sft_records(reference, ran.cases)
    with_tools = ran.export("reference", "sft")
    assert with_tools and all("tools" in record for record in with_tools)
    assert ran.export("reference", "rewards") == reward_records(reference, ran.cases)
    out = tmp_path / "pairs.jsonl"
    pairs = ran.export("reference", "pairs", against="idle", out=out)
    assert pairs == preference_pairs(reference, idle, ran.cases)
    assert len(out.read_text(encoding="utf-8").splitlines()) == len(pairs)
    with pytest.raises(HoldoutRefused):
        ran.export("reference", "sft", splits=("test",))
    with pytest.raises(ValueError, match="pairs need"):
        ran.export("reference", "pairs")


def test_agreement_matches_the_low_level_function(ran: EvalSession, tmp_path: Path) -> None:
    path = tmp_path / "studio.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["query", "golden", "fetched", "ttft", "ttfa", "ttlt", "score", "scoreError"])
        for index, case in enumerate(ran.cases):
            golden = case.outcomes.answer.golden if case.outcomes.answer is not None else "none"
            writer.writerow([case.query, golden, golden if index % 2 else "nothing found", "0", "0", "0",
                             "1.0" if index % 2 else "0.0", ""])
    studio = import_studio_results(path, ran.cases)
    expected = agreement(studio, ran.cases, GroundedRater())
    assert ran.agreement(path) == expected
    assert ran.agreement(ran.import_studio(path)) == expected
    assert ran.agreement("studio", rater=GroundedRater()) == expected


# -- the documented example -----------------------------------------------------------------


def test_the_sdk_guide_example_runs_offline(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The first example under "Improving an agent" in docs/sdk.md runs as written and promotes."""
    text = (ROOT / "docs" / "sdk.md").read_text(encoding="utf-8")
    section = text.split("## Improving an agent", 1)[1]
    block = re.search(r"```python\n(.*?)```", section, re.DOTALL)
    assert block, "docs/sdk.md lost its improvement example"
    monkeypatch.chdir(tmp_path)
    namespace: dict[str, Any] = {"__name__": "sdk_example"}
    exec(compile(block.group(1), "docs/sdk.md", "exec"), namespace)
    assert namespace["report"].promotions >= 1
    assert (tmp_path / "improve" / "improve.json").exists()


# -- the skill ----------------------------------------------------------------------------

_FRONTMATTER = re.compile(r"\A---\n(.*?)\n---\n", re.DOTALL)
_REFERENCE_LINK = re.compile(r"`?(references/[a-z0-9-]+\.md)`?")


def _frontmatter(path: Path) -> dict[str, str]:
    found = _FRONTMATTER.match(path.read_text(encoding="utf-8"))
    assert found, f"{path.relative_to(ROOT)} has no frontmatter"
    fields: dict[str, str] = {}
    for line in found.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip().strip('"')
    return fields


def test_the_skill_is_well_formed() -> None:
    skill = SKILL / "SKILL.md"
    fields = _frontmatter(skill)
    assert fields["name"] == SKILL.name
    assert re.fullmatch(r"[a-z0-9-]{1,64}", fields["name"])
    description = fields["description"]
    # The host's limit on a skill description; every shipped skill keeps under it.
    assert 0 < len(description) <= 1024
    assert "Use when" in description
    body = skill.read_text(encoding="utf-8")
    assert len(body.splitlines()) <= 100, "the entry point stays short; depth goes in references/"


def test_every_reference_is_routed_to_and_exists() -> None:
    body = (SKILL / "SKILL.md").read_text(encoding="utf-8")
    linked = set(_REFERENCE_LINK.findall(body))
    present = {f"references/{path.name}" for path in (SKILL / "references").glob("*.md")}
    assert linked, "the skill routes to no reference"
    assert linked == present, f"linked but missing: {sorted(linked - present)}; present but unrouted: {sorted(present - linked)}"
    for name in sorted(present):
        fields = _frontmatter(SKILL / name)
        assert fields.get("read-when"), f"{name} does not say when to read it"
        assert fields.get("title") and fields.get("description")


def test_the_skill_is_registered() -> None:
    index = (ROOT / "docs" / "skills.md").read_text(encoding="utf-8")
    assert "### `worldloom-improve`" in index
    assert ".claude/skills/worldloom-improve/SKILL.md" in index
    evalrun_skill = (ROOT / ".claude" / "skills" / "worldloom-evalrun" / "SKILL.md").read_text(encoding="utf-8")
    assert "worldloom-improve" in evalrun_skill
