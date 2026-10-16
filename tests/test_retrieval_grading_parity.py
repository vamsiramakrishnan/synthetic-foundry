"""Identical rankings must get identical temporal and authority grades.

The hard-coded verdicts catch a shared grader that drifts; the differential
checks catch an entry point that bypasses it. Ranking and the child process
are scripted here so a changed retrieval heuristic cannot hide grading drift.
The CLI test below exercises the real BM25 index and subprocess boundary.
"""

from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World, execseam
from worldloom.cli import app
from worldloom.evaluate import RETRIEVERS, Bm25, passages, score
from worldloom.evaluate.predictions import parse, score_predictions
from worldloom.models import (
    ArtifactIR,
    ArtifactManifestEntry,
    ArtifactSection,
    Authority,
    Company,
    EvaluationCase,
    EvaluationType,
    Lifecycle,
)
from worldloom.narrative import DeterministicProvider
from worldloom.recipe import rebuild

AT = datetime(2026, 4, 8, 9, 40, tzinfo=UTC)
BEFORE, AFTER = AT - timedelta(seconds=1), AT + timedelta(seconds=1)
FACT, OTHER, SECOND = "FACT-ANSWER", "FACT-WRONG", "FACT-SECOND"
TEMPORAL = EvaluationType.TEMPORAL_STATE
AUTHORITY = EvaluationType.AUTHORITY_RESOLUTION
LOW, HIGH = Authority.WORKING_DOCUMENT, Authority.SYSTEM_OF_RECORD


@dataclass(frozen=True)
class Evidence:
    at: datetime = AT
    authority: Authority = HIGH
    facts: tuple[str, ...] = (FACT,)


@dataclass(frozen=True)
class Scenario:
    kind: EvaluationType
    evidence: tuple[Evidence, ...]
    ranked: tuple[int, ...]
    passed: bool
    reachable: bool = True
    expected: tuple[str, ...] = (FACT,)
    offered: tuple[int, ...] | None = None


SCENARIOS = [
    pytest.param(Scenario(TEMPORAL, (Evidence(AFTER), Evidence()), (0, 1), False,
                          offered=(1, 0)), id="late-top-not-rescued-by-timely-second"),
    pytest.param(Scenario(TEMPORAL, (Evidence(facts=(OTHER,)), Evidence()), (0, 1), False),
                 id="timely-top-with-wrong-fact"),
    pytest.param(Scenario(TEMPORAL, (Evidence(),), (0,), True), id="cutoff-inclusive"),
    pytest.param(Scenario(TEMPORAL, (Evidence(BEFORE),), (0,), True), id="before-cutoff"),
    pytest.param(Scenario(TEMPORAL, (Evidence(AFTER),), (0,), False, False),
                 id="only-late-evidence-unreachable"),
    pytest.param(Scenario(TEMPORAL, (Evidence(), Evidence(facts=(SECOND,))), (0, 1), False,
                          False, expected=(FACT, SECOND)), id="temporal-top-needs-all-facts"),
    pytest.param(Scenario(TEMPORAL, (Evidence(),), (), False), id="temporal-empty-ranking"),
    pytest.param(Scenario(TEMPORAL, (Evidence(facts=(OTHER,)),), (0,), False, False),
                 id="temporal-missing-evidence"),
    pytest.param(Scenario(AUTHORITY, (Evidence(authority=LOW), Evidence()), (0, 1), False),
                 id="low-top-not-rescued-by-authoritative-second"),
    pytest.param(Scenario(AUTHORITY, (Evidence(facts=(OTHER,)), Evidence()), (0, 1), False,
                          offered=(1, 0)), id="wrong-fact-at-right-authority"),
    pytest.param(Scenario(AUTHORITY, (Evidence(), Evidence(authority=LOW)), (0, 1), True),
                 id="authoritative-top-with-fact"),
    pytest.param(Scenario(AUTHORITY, (Evidence(authority=LOW), Evidence(facts=(OTHER,))),
                          (0,), True), id="authority-floor-uses-carriers-only"),
    pytest.param(Scenario(AUTHORITY, (Evidence(authority=LOW), Evidence()), (0,), False),
                 id="authority-floor-uses-full-pool-not-offered-hits"),
    pytest.param(Scenario(AUTHORITY, (Evidence(facts=(OTHER,)),), (0,), False, False),
                 id="authority-missing-evidence"),
    pytest.param(Scenario(AUTHORITY, (Evidence(),), (), False), id="authority-empty-ranking"),
    pytest.param(Scenario(AUTHORITY, (Evidence(), Evidence(authority=LOW, facts=(SECOND,))),
                          (0,), True, expected=(FACT, SECOND)),
                 id="authority-retains-expected-fact-intersection"),
    pytest.param(Scenario(EvaluationType.CROSS_ARTIFACT,
                          (Evidence(), Evidence(facts=(SECOND,))), (0, 1), True,
                          expected=(FACT, SECOND)), id="coverage-still-uses-whole-ranking"),
]


def _world(scenario: Scenario) -> World:
    artifacts, irs = [], []
    for index, evidence in enumerate(scenario.evidence):
        identifier = f"ART-{index}"
        artifacts.append(ArtifactManifestEntry(
            id=identifier, title=identifier, artifact_type="memo", domain="finance",
            path=f"{identifier}.md", media_type="text/markdown", author_id="PERSON-1",
            audience="finance", created_at=evidence.at, authority=evidence.authority,
            lifecycle=Lifecycle.PUBLISHED,
        ))
        irs.append(ArtifactIR(id=identifier, intent_id=f"INTENT-{index}", title=identifier,
                             sections=[ArtifactSection(heading="Evidence", body="A recorded status.",
                                                       fact_ids=list(evidence.facts))]))
    case = EvaluationCase(id="EVAL-1", question="What status was recorded?",
                          evaluation_type=scenario.kind, expected_fact_ids=list(scenario.expected),
                          temporal_cutoff=AT if scenario.kind is TEMPORAL else None)
    return World(company=Company(id="CO-1", name="Parity", industry="retail",
                                 headquarters="Sydney", fiscal_year_start_month=7, employees_total=1),
                 _artifacts=tuple(artifacts), _artifact_irs=tuple(irs), _evaluations=(case,))


@pytest.mark.parametrize("scenario", SCENARIOS)
def test_same_ranking_gets_same_grade_through_every_entry_point(
    scenario: Scenario, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(scenario)
    pool = passages(world)
    k = max(1, len(pool))

    class Ranked:
        def rank(self, query: str, *, limit: int) -> list[tuple[int, float]]:
            return [(index, 1.0) for index in scenario.ranked[:limit]]

    monkeypatch.setitem(RETRIEVERS, "parity", lambda texts: Ranked())
    builtin = score(world, k=k, retriever="parity").outcomes

    def offered(index: Bm25, query: str, *, limit: int) -> list[tuple[int, float]]:
        positions = scenario.ranked if scenario.offered is None else scenario.offered
        return [(position, 1.0) for position in positions[:limit]]

    ids = [pool[index].id for index in scenario.ranked]

    def reply(command: str, payload: dict, **kwargs: object) -> execseam.ExecReply:
        # Pin the existing child wire shape; provenance stays in the grader.
        assert set(payload) == {"question", "passages"}
        assert all(set(p) == {"passage_id", "text"} for p in payload["passages"])
        assert set(ids) <= {p["passage_id"] for p in payload["passages"]}
        return execseam.ExecReply({"answer_passage_ids": ids, "abstain": False}, "")

    monkeypatch.setattr(Bm25, "rank", offered)
    monkeypatch.setattr(execseam, "run_exec", reply)
    executed = execseam.benchmark_run(world, "scripted", k=k).outcomes

    # Each artifact has one passage, so both granularities carry identical
    # evidence. Multi-section document rankings intentionally merge facts.
    passage_predictions = parse(json.dumps({"id": "EVAL-1", "passage_ids": ids}))
    artifact_predictions = parse(json.dumps({"id": "EVAL-1", "artifact_ids": [
        pool[index].artifact_id for index in scenario.ranked
    ]}))
    external = score_predictions(world, passage_predictions, k=k).card.outcomes
    documents = score_predictions(world, artifact_predictions, k=k).card.outcomes
    assert builtin == external == documents == executed
    assert builtin[0].passed is scenario.passed
    assert builtin[0].reachable is scenario.reachable


@pytest.mark.parametrize("kind", [TEMPORAL, AUTHORITY])
def test_explicit_abstention_fails_answerable_hard_cases(
    kind: EvaluationType, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(Scenario(kind, (Evidence(),), (0,), False))
    ids = [passages(world)[0].id]
    monkeypatch.setattr(execseam, "run_exec", lambda *args, **kwargs: execseam.ExecReply(
        {"answer_passage_ids": ids, "abstain": True}, ""))
    external = score_predictions(world, parse(json.dumps({
        "id": "EVAL-1", "passage_ids": ids, "abstain": True,
    }))).card.outcomes
    assert execseam.benchmark_run(world, "scripted").outcomes == external
    assert not external[0].passed and external[0].reachable


@pytest.mark.parametrize("kind", [TEMPORAL, AUTHORITY])
@pytest.mark.parametrize("unknown", [False, True], ids=["known-but-unoffered", "unknown-id"])
def test_an_unoffered_top_id_cannot_be_dropped_to_promote_the_second_hit(
    kind: EvaluationType, unknown: bool, monkeypatch: pytest.MonkeyPatch,
) -> None:
    world = _world(Scenario(kind, (Evidence(facts=(OTHER,)), Evidence()), (0, 1), False))
    pool = passages(world)
    first = "no-such-passage" if unknown else pool[0].id
    ids = [first, pool[1].id]
    monkeypatch.setattr(Bm25, "rank", lambda *args, **kwargs: [(1, 1.0)])
    monkeypatch.setattr(execseam, "run_exec", lambda *args, **kwargs: execseam.ExecReply(
        {"answer_passage_ids": ids, "abstain": False}, "adapter diagnostic"))
    with pytest.raises(execseam.ExecUnparseable, match="not offered") as refused:
        execseam.benchmark_run(world, "scripted")
    assert refused.value.code == "exec_unparseable"
    assert refused.value.data["case"] == "EVAL-1"
    assert refused.value.data["unoffered_ids"] == [first]
    assert refused.value.stderr_tail == "adapter diagnostic"
    if not unknown:
        # The same valid corpus IDs fail evaluate, with no top-hit filtering.
        external = score_predictions(world, parse(json.dumps({"id": "EVAL-1", "passage_ids": ids})))
        assert not external.card.outcomes[0].passed


@pytest.mark.parametrize("seed", [8128, 7, 4242])
def test_final_status_is_cut_at_first_publication_and_replays(seed: int) -> None:
    world = RetailWorld(seed=seed).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True))
    final_case = next(case for case in world.evaluations if case.id == "EVAL-0023")
    final_fact = world.facts.by_id(final_case.expected_fact_ids[0])
    narrated = world.narrate(DeterministicProvider()).render("markdown")
    carriers = [p for p in passages(narrated) if final_fact.id in p.fact_ids]
    assert final_case.evaluation_type is TEMPORAL
    assert final_case.temporal_cutoff == min(p.created_at for p in carriers)
    assert final_case.temporal_cutoff > final_fact.valid_from
    assert final_fact.holds_at(final_case.temporal_cutoff)
    assert [case.model_dump() for case in rebuild(world.recipe).evaluations] == [
        case.model_dump() for case in world.evaluations
    ]

    # Old stored corpora are not silently recut at score time. Their late-only
    # evidence is unreachable, rather than a retriever's unexplained failure.
    legacy = final_case.model_copy(update={"temporal_cutoff": final_fact.valid_from})
    before = legacy.model_dump_json()
    old_world = replace(narrated, _evaluations=(legacy,))
    prediction = parse(json.dumps({"id": legacy.id, "passage_ids": [carriers[0].id]}))
    outcome = score_predictions(old_world, prediction).card.outcomes[0]
    assert not outcome.passed and not outcome.reachable
    assert legacy.model_dump_json() == before


@pytest.mark.parametrize("k", [1, 5])
def test_cli_benchmark_matches_evaluate_and_predictions_without_wire_changes(tmp_path: Path, k: int) -> None:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    ).narrate(DeterministicProvider()).render("markdown")
    root = tmp_path / "corpus"
    world.export(root)
    script = tmp_path / "ranked.py"
    script.write_text('''import json, sys
payload = json.load(sys.stdin)
assert set(payload) == {"question", "passages"}
assert all(set(p) == {"passage_id", "text"} for p in payload["passages"])
print(json.dumps({"answer_passage_ids": [p["passage_id"] for p in payload["passages"]], "abstain": False}))
''', encoding="utf-8")
    argv = [sys.executable, str(script)]
    command = subprocess.list2cmdline(argv) if os.name == "nt" else shlex.join(argv)
    pool = passages(world)
    index = Bm25([p.text for p in pool])
    predictions = tmp_path / "predictions.jsonl"
    predictions.write_text("".join(json.dumps({
        "id": case.id, "passage_ids": [pool[i].id for i, _ in index.rank(case.question, limit=k)],
    }) + "\n" for case in world.evaluations), encoding="utf-8")
    runner = CliRunner()

    def run(*args: str) -> dict:
        result = runner.invoke(app, [*args, "-k", str(k), "--json"])
        assert result.exit_code == 0, result.output
        return json.loads(result.stdout)

    builtin = run("evaluate", str(root))
    external = run("evaluate", str(root), "--predictions", str(predictions))
    executed = run("benchmark", "run", str(root), "--exec", command)
    assert set(executed) == {"exec", "k", "overall", "by_type", "outcomes"}
    assert set(builtin) == {"retriever", "k", "overall", "by_type", "outcomes"}

    def hard(payload: dict) -> list[dict]:
        return [o for o in payload["outcomes"] if o["type"] in {TEMPORAL.value, AUTHORITY.value}]

    assert hard(builtin) == hard(external) == hard(executed)
    assert {o["type"] for o in hard(builtin)} == {TEMPORAL.value, AUTHORITY.value}
