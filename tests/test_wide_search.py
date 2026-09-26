"""Wide search: many candidates a round, screened by successive halving, and an archive to branch from.

The agent under test reads its policy for real: each skill it may be taught
is a lever over a fixed set of cases, which it then walks with the
reference agent; every other case it leaves alone. So a candidate's quality
is exactly the cases its skills cover, a test can build a strong, a weak, a
medium and an inert candidate side by side, and a near miss (a skill that
helps, but by less than the delta band) is a real near miss. The proposer is
a function over the pack interview's request: for the i-th candidate of a
round it adds the i-th skill of its script, which it reads from the message
the loop wrote, the same document a harness reads.
"""

from __future__ import annotations

import importlib
import json
import re
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
from worldloom.evalrun.contract import CASE_SET_FILE, RECORDS_FILE
from worldloom.evalrun.improve import improve, round_stem, split_cases
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.search import (
    PASSING,
    Archive,
    ArchiveEntry,
    cluster_means,
    dominates,
    halving_keep,
    parent_weights,
    pareto_frontier,
    screen_order,
    select_parent,
)
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()
HOLDOUT_SHARE = 0.4


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(24)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


@pytest.fixture(scope="module")
def split(corpus: Any) -> tuple[list[str], list[str]]:
    """Training and held-out case ids, training ordered from the smallest gain the reference would bring."""
    cases = cases_from_corpus(corpus)
    train, held = split_cases(cases, holdout_share=HOLDOUT_SHARE)
    idle = run_cases(service_for(train, corpus.connector_data.records), train, ScriptedAgent([], name="idle"))
    scores = {row.case_id: row.score.score for row in idle.results if row.score is not None}
    return sorted(scores, key=lambda case_id: (-scores[case_id], case_id)), sorted(case.id for case in held)


class LeverAgent:
    """The reference agent on every case one of its policy's skills covers; idle elsewhere."""

    def __init__(self, pack: Any, cases: Any, levers: dict[str, frozenset[str]], log: list[tuple[str, str]]) -> None:
        self.pack = pack
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        skills = set(pack.body.skills)
        self.covered = frozenset(case_id for name in sorted(skills) for case_id in levers.get(name, ()))
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")
        self.log = log

    def run(self, task: Any, tools: Any) -> Any:
        self.log.append((self.pack.digest, task.case_id))
        return (self.reference if task.case_id in self.covered else self.idle).run(task, tools)


_CANDIDATE = re.compile(r"This is candidate (\d+) of (\d+)")


def _script(skills: list[str | None]) -> Any:
    """For candidate i of a round, add skill ``skills[i-1]`` to the draft (``None``: a reply the lint refuses)."""
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        found = _CANDIDATE.search(payload["message"])
        index = int(found.group(1)) if found else 1
        skill = skills[(index - 1) % len(skills)]
        if skill is None:
            return {"request_id": payload["request_id"], "proposal": {"body": "a whole policy as prose"}}
        body = payload["draft"]["body"]
        return {"request_id": payload["request_id"], "message": f"Teach the {skill} skill.\nIt helps.",
                "proposal": {"name": payload["draft"]["name"],
                             "body": {**body, "skills": {**body.get("skills", {}), skill: f"Use {skill} on every request."}}}}

    exchange.seen = seen  # type: ignore[attr-defined]
    return exchange


def _next_skill(order: list[str]) -> Any:
    """Add the first skill of *order* the draft lacks: from the champion, alpha; from alpha's candidate, beta."""
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        body = payload["draft"]["body"]
        have = body.get("skills", {})
        skill = next(name for name in order if name not in have)
        return {"request_id": payload["request_id"], "message": f"Teach {skill}.",
                "proposal": {"name": payload["draft"]["name"],
                             "body": {**body, "skills": {**have, skill: f"Use {skill}."}}}}

    exchange.seen = seen  # type: ignore[attr-defined]
    return exchange


def _loop(corpus: Any, out: Path, exchange: Any, levers: dict[str, frozenset[str]], *, rounds: int = 1,
          log: list[tuple[str, str]] | None = None, calls: list[tuple[str, ...]] | None = None,
          hook: Any = None, **options: Any) -> Any:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    runs = log if log is not None else []

    def run(subset: Any, agent: Any) -> Any:
        if hook is not None:
            hook(subset)
        if calls is not None:
            calls.append(tuple(case.id for case in subset))
        return run_cases(service_for(subset, records), subset, agent)

    return improve(packkit.resolve("agent:baseline"), cases, run=run,
                   agent_for=lambda pack: LeverAgent(pack, cases, levers, runs), exchange=exchange, out=out,
                   holdout_share=HOLDOUT_SHARE, rounds=rounds, **options)


def _screening_levers(split: tuple[list[str], list[str]]) -> dict[str, frozenset[str]]:
    """``best`` covers nine of eleven training cases, ``some`` three of those, ``one`` a case ``best`` misses."""
    train, held = split
    assert len(train) == 11 and len(held) == 13
    return {"best": frozenset(train[:9]) | frozenset(held[:6]), "some": frozenset(train[:3]),
            "one": frozenset(train[9:10]), "other": frozenset(train[10:11]), "notes": frozenset()}


#: Five proposals: weak, inert, best, medium, and the inert one again.
_FIVE = ["one", "notes", "best", "some", "notes"]


def _tree(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


# -- the pure parts ----------------------------------------------------------------


def test_the_pareto_frontier_on_a_hand_built_archive() -> None:
    vectors = {
        "a": {"read": 0.5, "write": 0.5},
        "b": {"read": 0.6, "write": 0.4},
        "c": {"read": 0.4, "write": 0.4},   # a beats it everywhere
        "d": {"read": 0.6, "write": 0.4},   # the same as b: neither is better anywhere
        "e": {"read": 0.5, "write": 0.6},   # as good as a on read, better on write
    }
    assert dominates(vectors["a"], vectors["c"]) and not dominates(vectors["b"], vectors["d"])
    assert not dominates(vectors["b"], vectors["e"]) and not dominates(vectors["e"], vectors["b"])
    assert pareto_frontier(vectors) == ("b", "d", "e")
    assert pareto_frontier({"only": {"x": 0.0}}) == ("only",)
    # Cluster means are over each cluster's own cases; clusters may overlap.
    scores = {"c1": 1.0, "c2": 0.5, "c3": 0.0}
    assert cluster_means(scores, {"plan.missing:read": ("c1", "c2", "c3"), "outcomes.ungrounded": ("c1",),
                                  PASSING: ("c3",)}) == {PASSING: 0.0, "outcomes.ungrounded": 1.0,
                                                         "plan.missing:read": 0.5}


def test_parent_selection_is_seeded_and_favours_a_high_mean_and_few_visits() -> None:
    members = [("champion", 0.50, 3), ("stone", 0.58, 0), ("stale", 0.58, 4)]
    weights = parent_weights(members)
    assert weights["stone"] == 1.0 and weights["stale"] == pytest.approx(0.2)
    assert weights["champion"] == pytest.approx(0.449329 / 4, abs=1e-6)
    seeds = [f"{index:012x}" + "0" * 52 for index in range(0, 2 ** 48, 2 ** 42)]
    picks = [select_parent(members, seed)[0] for seed in seeds]
    assert picks == [select_parent(members, seed)[0] for seed in seeds], "the same seed draws the same parent"
    assert picks.count("stone") > picks.count("stale") > 0 and picks.count("champion") > 0
    # The draw is the seed's first 48 bits over 2**48, laid out in digest order.
    assert select_parent(members, "0" * 64)[0] == "champion"
    assert select_parent(members, "f" * 64)[0] == "stone"
    with pytest.raises(ValueError):
        select_parent([], "0" * 64)


def test_the_screening_order_is_stratified_seeded_and_nested() -> None:
    ids = [f"case-{index:02d}" for index in range(12)]
    clusters = [("plan.missing:read", ids[:10]), ("outcomes.ungrounded", ids[:2]), ("plan.order", ids[8:10])]
    order = screen_order(ids, clusters, "seed-a")
    assert sorted(order) == ids and order == screen_order(list(reversed(ids)), clusters, "seed-a")
    # The first sweep deals one case from each stratum: the two rare clusters,
    # the common one, then a case the champion passes.
    assert set(order[:4]) & set(ids[:2]) and set(order[:4]) & set(ids[8:10])
    assert set(order[:4]) & set(ids[2:8]) and set(order[:4]) & set(ids[10:])
    assert order != screen_order(ids, clusters, "seed-b")
    assert [halving_keep(alive, 1, False) for alive in (5, 4, 3, 2)] == [3, 2, 2, 1]
    assert halving_keep(4, 2, False) == 2 and halving_keep(3, 1, True) == 1 and halving_keep(1, 2, True) == 1


# -- the loop ----------------------------------------------------------------------


def test_screening_advances_the_best_for_fewer_case_runs_and_the_finalist_is_promoted(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    levers = _screening_levers(split)
    exchange = _script(_FIVE)
    log: list[tuple[str, str]] = []
    report = _loop(corpus, tmp_path / "wide", exchange, levers, log=log, candidates=5, screen_cases=4)
    first = report.rounds[0]
    assert first.decision == "promoted", first.reasons
    screening = first.screening
    assert screening is not None and screening.requested == 5
    statuses = {record.index: record.status for record in screening.candidates}
    assert statuses == {1: "screened_out", 2: "screened_out", 3: "finalist", 4: "screened_out", 5: "duplicate"}
    assert screening.candidates[4].duplicate_of == 2
    # Successive halving: four distinct candidates on four cases, the better
    # two on the next four, and the best is the one finalist.
    assert [len(stage.cases) for stage in screening.stages] == [4, 8]
    assert [len(stage.ran) for stage in screening.stages] == [4, 4]
    assert screening.stages[0].advanced[0] == 3 and len(screening.stages[0].advanced) == 2
    assert screening.stages[1].advanced == (3,) and screening.finalists == (3,)
    assert screening.stopped == "finalists" and screening.cost == 4 * 4 + 2 * 4 == 24
    assert set(screening.order) == set(split[0]) and set(split[1]).isdisjoint(screening.order)
    best = next(record for record in screening.candidates if record.index == 3)
    assert first.candidate is not None and first.candidate["digest"] == best.digest
    assert first.candidate["ref"] == "agent:baseline-r1-c3" and round_stem("baseline-r1-c3") == "baseline"
    assert best.train_passed and first.train is not None and first.train.passed
    assert first.holdout is not None and first.holdout.passed
    # The case-runs, counted at the agent: screening plus one full training
    # evaluation is fewer than evaluating all four candidates in full.
    by_pack: dict[str, int] = {}
    for digest, _ in log:
        by_pack[digest] = by_pack.get(digest, 0) + 1
    champion, train, held = report.initial["digest"], 11, 13
    candidate_training = sum(count for digest, count in by_pack.items() if digest != champion) - held
    assert candidate_training == 24 + train == 35 < 4 * train
    assert first.spent == len(log) == train + 24 + train + 2 * held == 72
    assert report.spent == 72 and report.search == {"candidates": 5, "screen_cases": 4, "finalists": 1,
                                                    "parents": "champion", "round_budget": None}
    # Each request said which candidate it was and listed the earlier ones by
    # summary and size, never by content; the duplicate was never run.
    messages = [payload["message"] for payload in exchange.seen]
    assert "This is candidate 1 of 5" in messages[0] and "(none yet)" in messages[0]
    assert "- candidate 1: Teach the one skill. (1 file(s), 1 hunk(s)" in messages[1]
    assert "Use one on every request." not in messages[1]
    assert "- candidate 5" not in messages[4] and "- candidate 2: Teach the notes skill." in messages[4]
    duplicate = screening.candidates[4].digest
    assert duplicate not in by_pack
    stored = json.loads((tmp_path / "wide" / "rounds" / "001.json").read_text())
    assert stored["screening"]["stages"][1]["advanced"] == [3] and stored["spent"] == 72
    assert json.loads((tmp_path / "wide" / "improve.json").read_text())["spent"] == 72
    assert not (tmp_path / "wide" / "proposals" / "001.json").exists(), "the receipt replaces the journal"


def test_a_round_budget_stops_screening_and_the_ranking_so_far_decides(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    levers = _screening_levers(split)
    # Stage one (16) plus the finalist's full training runs (11) fits; stage two (8 more) does not.
    report = _loop(corpus, tmp_path / "budget", _script(_FIVE), levers, candidates=5, screen_cases=4, round_budget=30)
    screening = report.rounds[0].screening
    assert screening is not None and screening.stopped == "budget" and screening.budget == 30
    assert len(screening.stages) == 1 and screening.cost == 16 and screening.finalists == (3,)
    assert report.rounds[0].decision == "promoted"
    tight = _loop(corpus, tmp_path / "tight", _script(_FIVE), levers, candidates=5, screen_cases=4, round_budget=11)
    screening = tight.rounds[0].screening
    assert screening is not None and screening.stopped == "budget" and not screening.stages
    assert screening.finalists == (1,), "with nothing screened the first candidate goes on"


def test_candidates_1_is_the_narrow_loop_to_the_byte(corpus: Any, split: tuple[list[str], list[str]],
                                                     tmp_path: Path) -> None:
    levers = _screening_levers(split)
    narrow = _loop(corpus, tmp_path / "narrow", _script(["best"]), levers, rounds=2)
    explicit = _loop(corpus, tmp_path / "explicit", _script(["best"]), levers, rounds=2, candidates=1,
                     finalists=3, screen_cases=2, parents="champion")
    assert narrow.model_dump() == explicit.model_dump()
    assert _tree(tmp_path / "narrow") == _tree(tmp_path / "explicit")
    for path in sorted((tmp_path / "narrow" / "rounds").glob("*.json")):
        stored = json.loads(path.read_text())
        assert not {"parent", "screening", "spent"} & set(stored), path
    assert not {"search", "spent"} & set(json.loads((tmp_path / "narrow" / "improve.json").read_text()))
    assert not (tmp_path / "narrow" / "archive").exists() and not (tmp_path / "narrow" / "proposals").exists()
    assert narrow.rounds[0].candidate is not None and narrow.rounds[0].candidate["ref"] == "agent:baseline-r1"


def test_the_holdout_is_never_run_before_a_finalist_passes_the_training_gate(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    levers = _screening_levers(split)
    held = set(split[1])
    calls: list[tuple[str, ...]] = []
    # Only weak and inert candidates: none passes, so no held-out case ever runs.
    report = _loop(corpus, tmp_path / "weak", _script(["one", "notes", "other"]), levers, calls=calls,
                   candidates=3, screen_cases=4)
    first = report.rounds[0]
    assert first.decision == "rejected" and first.holdout is None and first.train is not None
    assert first.screening is not None and len(first.screening.stages) >= 1
    assert calls and not any(held & set(ids) for ids in calls)
    assert not list((tmp_path / "weak" / "runs").glob("*/holdout"))
    # With a winner, every run before the first held-out case is on training
    # cases, and the last of them is the finalist's full training evaluation.
    calls = []
    _loop(corpus, tmp_path / "strong", _script(_FIVE), levers, calls=calls, candidates=5, screen_cases=4)
    first_held = next(position for position, ids in enumerate(calls) if held & set(ids))
    assert all(not held & set(ids) for ids in calls[:first_held])
    assert set(calls[first_held - 1]) == set(split[0]), "the finalist ran the whole training set first"


def test_the_archive_keeps_every_full_evaluation_and_its_frontier(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    levers = _screening_levers(split)
    out = tmp_path / "archived"
    report = _loop(corpus, out, _script(["one", "notes", "some"]), levers, candidates=3, screen_cases=4,
                   finalists=2)
    screening = report.rounds[0].screening
    assert screening is not None and len(screening.finalists) == 2
    archive_dir = out / "archive"
    clusters = json.loads((archive_dir / "clusters.json").read_text())
    assert clusters["case_set"] == report.train_case_set
    entries = {path.stem: ArchiveEntry.model_validate_json(path.read_text())
               for path in sorted(archive_dir.glob("*.json")) if path.name != "clusters.json"}
    finalist_digests = {record.digest for record in screening.candidates if record.status == "finalist"}
    assert set(entries) == finalist_digests | {report.initial["digest"]}, "the champion and both finalists"
    for digest, entry in entries.items():
        assert entry.digest == digest and set(entry.scores) == set(split[0])
        assert entry.clusters == cluster_means(entry.scores, clusters["clusters"])
        assert entry.parent in {None, report.initial["digest"]}
    # The loaded archive recomputes the same frontier, and a candidate that
    # covers more is never behind one that covers less.
    archive = Archive(archive_dir, case_set=report.train_case_set, grader=report.grader["digest"])
    frontier = archive.frontier()
    assert frontier == pareto_frontier({digest: entry.clusters for digest, entry in entries.items()})
    assert report.initial["digest"] not in frontier, "every finalist is at least as good as the idle champion"
    # An archive over another case set ignores these entries.
    assert not Archive(archive_dir, case_set="other", grader=report.grader["digest"]).entries


def test_a_near_miss_in_the_archive_becomes_the_parent_and_its_child_is_promoted(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    train, held = split
    # Each skill alone helps two training cases: under the delta band, a near
    # miss. Together they clear it.
    levers = {"alpha": frozenset(train[:2]) | {held[0]}, "beta": frozenset(train[2:4]) | {held[1]}}
    narrow = _loop(corpus, tmp_path / "narrow", _next_skill(["alpha", "beta"]), levers, rounds=2)
    assert [item.decision for item in narrow.rounds] == ["rejected", "rejected"]
    assert narrow.rounds[0].train is not None and 0 < narrow.rounds[0].train.mean_delta < 0.1
    exchange = _next_skill(["alpha", "beta"])
    report = _loop(corpus, tmp_path / "archive", exchange, levers, rounds=2, parents="archive")
    first, second = report.rounds
    assert first.decision == "rejected" and first.parent is not None and first.parent["mode"] == "archive"
    assert first.parent["digest"] == report.initial["digest"], "round one has only the champion to branch from"
    assert first.candidate is not None
    stone = first.candidate["digest"]
    # Round two branches from the near miss, which dominates the champion on
    # every failure cluster, and its child clears both gates.
    assert second.parent is not None and second.parent["mode"] == "archive"
    assert second.parent["digest"] == stone != report.initial["digest"]
    assert [member["digest"] for member in second.parent["frontier"]] == [stone]
    assert second.decision == "promoted", second.reasons
    assert second.train is not None and second.train.mean_delta >= 0.1
    assert second.holdout is not None and second.holdout.passed
    assert report.champion["digest"] == second.candidate["digest"]
    promoted = packkit.resolve(f"{report.champion['ref']}@{report.champion['digest']}",
                               roots=[tmp_path / "archive" / "packs"])
    assert set(promoted.body.skills) == {"alpha", "beta"}
    # The proposer was told the draft is an archived candidate, and shown its failures.
    message = exchange.seen[-1]["message"]
    assert "The draft is not the champion" in message and first.candidate["ref"] in message
    # The draw is seeded: the same loop elsewhere makes the same choices, to the byte.
    again = _loop(corpus, tmp_path / "again", _next_skill(["alpha", "beta"]), levers, rounds=2, parents="archive")
    assert again.model_dump() == report.model_dump()
    assert _tree(tmp_path / "again" / "rounds") == _tree(tmp_path / "archive" / "rounds")


class Interrupted(Exception):
    pass


def test_a_round_interrupted_mid_screening_resumes_without_paying_again(
        corpus: Any, split: tuple[list[str], list[str]], tmp_path: Path) -> None:
    levers = _screening_levers(split)
    clean = _loop(corpus, tmp_path / "clean", _script(_FIVE), levers, candidates=5, screen_cases=4)
    out = tmp_path / "resumed"
    runs: list[int] = []

    def interrupt(subset: Any) -> None:
        runs.append(len(subset))
        # The champion's training run, stage one's four, then the first of
        # stage two's two: the second is interrupted.
        if len(runs) == 7:
            raise Interrupted

    exchange = _script(_FIVE)
    with pytest.raises(Interrupted):
        _loop(corpus, out, exchange, levers, candidates=5, screen_cases=4, hook=interrupt)
    assert len(exchange.seen) == 5 and (out / "proposals" / "001.json").exists()
    assert not (out / "rounds" / "001.json").exists()
    log: list[tuple[str, str]] = []
    again = _script(_FIVE)
    report = _loop(corpus, out, again, levers, log=log, candidates=5, screen_cases=4)
    assert not again.seen, "the proposals were kept, not asked for again"
    # Only the unfinished screen (four cases), the finalist's training run and
    # the two held-out runs are paid for.
    assert len(log) == 4 + 11 + 2 * 13 == report.rounds[0].spent
    resumed, first = report.rounds[0], clean.rounds[0]
    assert resumed.model_dump(exclude={"spent"}) == first.model_dump(exclude={"spent"})
    assert not (out / "proposals" / "001.json").exists()


def test_the_cli_and_the_sdk_take_the_wide_search_settings(corpus: Any, split: tuple[list[str], list[str]],
                                                           tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    cases = cases_from_corpus(corpus)
    levers = _screening_levers(split)
    case_set = tmp_path / "cases"
    write_jsonl(case_set / CASE_SET_FILE, list(cases))
    write_jsonl(case_set / RECORDS_FILE, list(corpus.connector_data.records))
    harness_module = importlib.import_module("worldloom.evalrun.harness")
    authoring_module = importlib.import_module("worldloom.packkit.authoring")
    monkeypatch.setattr(harness_module, "ExecAgent",
                        lambda command, *, policy, **options: LeverAgent(policy, cases, levers, []))
    monkeypatch.setattr(authoring_module, "run_exec_exchange", lambda command, **options: _script(_FIVE))
    args = ["evalrun", "improve", str(case_set), "--agent-pack", "agent:baseline", "--exec", "agent",
            "--proposer-exec", "proposer", "--holdout-share", str(HOLDOUT_SHARE), "--rounds", "1",
            "--candidates", "5", "--screen-cases", "4", "--finalists", "1", "--parents", "archive",
            "--round-budget", "500"]
    result = runner.invoke(app, [*args, "-o", str(tmp_path / "cli"), "--json"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert document["search"] == {"candidates": 5, "screen_cases": 4, "finalists": 1, "parents": "archive",
                                  "round_budget": 500}
    receipt = document["rounds"][0]
    assert receipt["decision"] == "promoted" and receipt["parent"]["mode"] == "archive"
    assert receipt["screening"]["finalists"] == [3] and receipt["spent"] == document["spent"] == 72
    text = runner.invoke(app, [*args, "-o", str(tmp_path / "text")])
    assert text.exit_code == 0, text.output
    assert "5 candidate(s), 2 screening stage(s) costing 24 case-run(s); finalist(s): 3" in text.output
    assert "72 case-run(s) spent across 1 round(s)" in text.output
    bad = runner.invoke(app, [*args[:-4], "--parents", "everyone", "-o", str(tmp_path / "bad")])
    assert bad.exit_code == 2 and "--parents" in bad.output
    campaign = runner.invoke(app, ["evalrun", "campaign", str(case_set), "--agent-pack", "agent:baseline",
                                   "--plan", str(tmp_path / "missing.json"), "--exec", "agent", "--proposer-exec",
                                   "proposer", "-o", str(tmp_path / "campaign"), "--parents", "everyone"])
    assert campaign.exit_code == 2 and "--parents" in campaign.output
    # The SDK takes the same keywords and leaves the same report.
    session = EvalSession.open(corpus)
    loop = session.improver(agent=lambda pack: LeverAgent(pack, cases, levers, []), proposer=_script(_FIVE),
                            out=tmp_path / "sdk", holdout_share=HOLDOUT_SHARE, candidates=5, screen_cases=4,
                            finalists=1, parents="archive", round_budget=500)
    sdk = loop.run("agent:baseline", rounds=1)
    assert sdk.rounds[0].screening == document_screening(document)
    assert sdk.spent == 72 and loop.champion(sdk).digest == sdk.champion["digest"]


def document_screening(document: dict[str, Any]) -> Any:
    from worldloom.evalrun.search import Screening

    return Screening.model_validate(document["rounds"][0]["screening"])
