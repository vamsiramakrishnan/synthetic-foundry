"""Corner cases drawn from the world's own events, proved solvable, and searched for a frontier.

Every world here is a real build through the scenarios that carry the
events (a close with its incident, a reorganisation and a departure; a
restated capital return; a strengthened reserve; an escalated match
exception), and every grade comes from the real path: the reference agent
or a scripted one through the tool surface, over the world's own records.
Where a test needs a mistaken agent it replays the mistake the event invites
(the superseded record, the old holder's name), never an invented one.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, World
from worldloom.cli import app
from worldloom.evalrun import ReferenceAgent, ScriptedAgent, run_cases, service_for
from worldloom.evalrun.contract import read_case_set
from worldloom.evalrun.corners import (
    TEMPLATE_IDS,
    TEMPLATES,
    CornerBatch,
    HoldoutOverlap,
    activity,
    corner_cases,
    corner_generator,
    describe_templates,
    draft_cases,
    frontier,
    read_corner_set,
    seeded_world,
    write_corner_set,
    write_frontier,
)
from worldloom.evalrun.runner import case_set_digest
from worldloom.scenarios import MonthEndClose

runner = CliRunner()

SEED = 8128

#: The engine whose seeded world carries each template's event.
HOME = {
    "confirmed_cause": "retail",
    "restated_figure": "banking",
    "escalated_exception": "procurement",
    "approver_handover": "retail",
}
#: A seeded world that carries none of the template's events.
AWAY = {
    "confirmed_cause": "insurance",
    "restated_figure": "retail",
    "escalated_exception": "banking",
    "approver_handover": "procurement",
}


@pytest.fixture(scope="module")
def worlds() -> dict[str, World]:
    return {engine: seeded_world(engine, SEED) for engine in ("retail", "banking", "insurance", "procurement")}


@pytest.fixture(scope="module")
def batches(worlds: dict[str, World]) -> dict[str, CornerBatch]:
    return {engine: corner_cases(world, seed=SEED) for engine, world in worlds.items()}


def _of(batch: CornerBatch, template: str) -> list[Any]:
    return [case for case in batch.cases if case.dimensions["corner"] == template]


# -- the catalogue ---------------------------------------------------------------------


def test_every_template_names_real_events_and_catalogue_activities() -> None:
    assert len(TEMPLATES) >= 4
    for template in TEMPLATES:
        assert template.events and set(template.activities) == set(template.events)
        for ref in template.activities.values():
            found = activity(ref)
            assert found.pcf_id.isdigit() and found.value_stream and found.name
        assert set(template.expressed_as) & {"failure_at", "question_required", "reads_contain", "state_equals"}
    described = describe_templates()
    assert [item["id"] for item in described] == list(TEMPLATE_IDS)
    assert "—" not in json.dumps(described) and "Claude" not in json.dumps(described)
    with pytest.raises(KeyError):
        activity("nope.99")


# -- generation, grounded in the event ----------------------------------------------------


@pytest.mark.parametrize("template", TEMPLATE_IDS)
def test_each_template_yields_on_a_world_with_its_event_and_not_on_one_without(
        template: str, worlds: dict[str, World], batches: dict[str, CornerBatch]) -> None:
    home = worlds[HOME[template]]
    cases = _of(batches[HOME[template]], template)
    assert cases, f"{template} produced nothing on {HOME[template]}"
    events = {event.id: event for event in home.events}
    facts = {fact.id for fact in home.facts}
    spec = next(item for item in TEMPLATES if item.id == template)
    for case in cases:
        dims = case.dimensions
        assert dims["corner"] == template
        event = events[dims["event"]]
        assert event.kind in spec.events
        assert dims["activity"] == spec.activities[event.kind]
        assert dims["pcf_id"] == activity(dims["activity"]).pcf_id
        cited = dims["evidence"].split(",")
        assert dims["event"] in cited and all(item in events for item in cited)
        assert case.row["expected_evidence_ids"] == cited
        assert case.row["expected_fact_ids"] and set(case.row["expected_fact_ids"]) <= facts
        assert dims["as_of"].startswith(("2025", "2026"))
    # A world that does not contain the event is never given one.
    drafted, _ = draft_cases(worlds[AWAY[template]], templates=[template])
    assert drafted == ()


def test_worlds_missing_the_event_in_the_same_engine_yield_nothing() -> None:
    quiet = RetailWorld(seed=SEED).build().run(MonthEndClose(period="2026-03", include_operational_incident=False))
    drafted, skipped = draft_cases(quiet)
    assert drafted == ()
    assert all(not misses for misses in skipped.values())


def test_the_difficulty_is_the_event(batches: dict[str, CornerBatch], worlds: dict[str, World]) -> None:
    """Each case punishes the mistake its event invites, and only that mistake."""
    retail = batches["retail"]
    records = retail.records
    cause = _of(retail, "confirmed_cause")[0]
    target = next(node for node in cause.row["expected_dag"]["nodes"] if node["id"] == "write")
    current = target["payload"]["fields"]["root_cause_ref"]
    world = worlds["retail"]
    hypothesis = next(event for event in world.events if event.kind == "hypothesis_recorded")
    stale = next(record for record in records if record.connector == "jira" and hypothesis.id in record.event_ids)
    incident = next(record for record in records if record.id == target["fixture"])
    rows = {"stale": stale.external_id, "current": current}
    grades = {}
    for label, key in rows.items():
        agent = ScriptedAgent([
            ("servicenow.get_record", {"id": incident.external_id}),
            ("jira.search_issues", {"entity": "issue", "max_results": 50}),
            ("jira.get_issue", {"id": key}),
            ("servicenow.update_record", {"id": incident.external_id, "fields": {"root_cause_ref": key}}),
            ("servicenow.get_record", {"id": incident.external_id}),
        ], name=label)
        grades[label] = run_cases(service_for((cause,), records), (cause,), agent).results[0].score
    assert grades["current"] is not None and grades["current"].passed, grades["current"]
    assert grades["stale"] is not None and not grades["stale"].passed
    assert "state_mismatch:write" in grades["stale"].assertion_fails

    handover = _of(retail, "approver_handover")[0]
    write = next(node for node in handover.row["expected_dag"]["nodes"] if node["id"] == "write")
    item = next(record for record in records if record.id == write["fixture"])
    departed = next(fact for fact in world.facts if fact.kind == "org.departed")
    outgoing = next(person for person in world.people if person.id == departed.subject)
    carried = ScriptedAgent([("jira.get_issue", {"id": item.external_id}),
                             ("jira.update_issue", {"id": item.external_id, "fields": {"assignee": outgoing.name}}),
                             ("jira.get_issue", {"id": item.external_id})], name="old-holder")
    score = run_cases(service_for((handover,), records), (handover,), carried).results[0].score
    assert score is not None and not score.passed and "state_mismatch:write" in score.assertion_fails

    banking = batches["banking"]
    by_variant = {case.dimensions["variant"]: case for case in _of(banking, "restated_figure")}
    assert set(by_variant) == {"as_reported", "current", "unspecified"}
    refs = {variant: next(node for node in case.row["expected_dag"]["nodes"] if node["id"] == "write")
            ["payload"]["fields"]["source_ref"] for variant, case in by_variant.items()}
    assert refs["as_reported"] != refs["current"] == refs["unspecified"]
    assert by_variant["unspecified"].trajectory.questions and not by_variant["current"].trajectory.questions
    # Acting on the open request without asking which as-of is the finding.
    unasked = by_variant["unspecified"]
    make = next(node for node in unasked.row["expected_dag"]["nodes"] if node["id"] == "write")
    blind = ScriptedAgent([("jira.search_issues", {"entity": "issue", "max_results": 50}),
                           ("jira.get_issue", {"id": refs["current"]}),
                           ("jira.create_issue", {"entity": "task", "name": make["payload"]["name"],
                                                  "fields": make["payload"]["fields"]})], name="blind")
    score = run_cases(service_for((unasked,), banking.records), (unasked,), blind).results[0].score
    assert score is not None and not score.passed and "no_question:which-as-of" in score.assertion_fails

    exception = _of(batches["procurement"], "escalated_exception")[0]
    assert exception.dimensions["failure"] == "permission_denied"
    assert [point.kind for point in exception.trajectory.failures] == ["denied"]
    assert exception.outcomes.no_write


def test_every_generated_case_is_solved_by_the_reference_or_dropped_with_a_reason(
        batches: dict[str, CornerBatch]) -> None:
    for engine, batch in batches.items():
        for item in batch.yields:
            assert item.generated == item.solvable + item.dropped, (engine, item)
        assert all(drop.reason for drop in batch.drops)
        if not batch.cases:
            continue
        report = run_cases(service_for(batch.cases, batch.records), batch.cases, ReferenceAgent(batch.cases))
        failing = [(row.case_id, row.error) for row in report.results
                   if not (row.graded and row.score is not None and row.score.passed)]
        assert failing == [], (engine, failing)
    total = sum(item.solvable for batch in batches.values() for item in batch.yields)
    assert total >= 4


def test_an_unsolvable_case_is_dropped_not_kept(worlds: dict[str, World]) -> None:
    class Stops:
        name = "stops"

        def run(self, task: Any, tools: Any) -> Any:
            return ScriptedAgent([], name="stops").run(task, tools)

    batch = corner_cases(worlds["procurement"], reference=Stops())
    assert batch.cases == ()
    assert batch.drops and all("plan.missing" in drop.reason for drop in batch.drops)
    assert sum(item.dropped for item in batch.yields) == len(batch.drops)


# -- determinism -------------------------------------------------------------------------------


def test_the_same_seed_gives_the_same_cases_and_digest(tmp_path: Path) -> None:
    first = corner_generator("banking")(SEED)
    again = corner_generator("banking")(SEED)
    assert [case.id for case in first.cases] == [case.id for case in again.cases]
    assert first.summary() == again.summary()
    write_corner_set(first, tmp_path / "a")
    write_corner_set(again, tmp_path / "b")
    for name in ("evalrun-cases.jsonl", "records.jsonl", "corners.json"):
        assert (tmp_path / "a" / name).read_bytes() == (tmp_path / "b" / name).read_bytes(), name
    other = corner_generator("banking")(SEED + 1)
    assert not {case.id for case in first.cases} & {case.id for case in other.cases}
    read = read_corner_set(tmp_path / "a")
    assert case_set_digest(read.cases) == first.summary()["case_set"]


def test_a_world_read_back_from_disk_yields_the_same_cases(worlds: dict[str, World], tmp_path: Path) -> None:
    worlds["banking"].compile().export(tmp_path / "corpus", overwrite=True)
    loaded = corner_cases(World.load(str(tmp_path / "corpus")))
    built = corner_cases(worlds["banking"])
    assert loaded.summary()["case_set"] == built.summary()["case_set"]


# -- the frontier -------------------------------------------------------------------------------


def test_an_idle_champion_yields_a_frontier_the_reference_does_not(tmp_path: Path) -> None:
    idle = ScriptedAgent([], name="idle")
    report = frontier(corner_generator("retail"), idle, budget=4, seeds=(1, 2, 3))
    assert report.spent == 4 and len(report.frontier_ids) == 4
    assert report.champion == "idle" and report.reference == "reference"
    assert {item.template for item in report.yields} == {"confirmed_cause", "approver_handover"}
    assert sum(item.frontier for item in report.yields) == 4
    assert all(item.frontier <= item.evaluated <= item.solved <= item.offered for item in report.yields)
    again = frontier(corner_generator("retail"), idle, budget=4, seeds=(1, 2, 3))
    assert again.summary() == report.summary()

    none = frontier(corner_generator("retail"), lambda cases: ReferenceAgent(cases), budget=4, seeds=(1, 2, 3))
    assert none.frontier_ids == () and none.spent == 4

    written = write_frontier(report, tmp_path / "frontier")
    summary = json.loads((written / "frontier.json").read_text())
    assert summary["frontier_ids"] == list(report.frontier_ids)
    for batch in report.batches:
        cases, records = read_case_set(written / f"seed-{batch.seed}")
        assert [case.id for case in cases] == [case.id for case in batch.cases] and records


def test_a_fixed_case_set_is_searched_in_a_seeded_order_within_budget(batches: dict[str, CornerBatch]) -> None:
    batch = batches["banking"]
    idle = ScriptedAgent([], name="idle")
    one = frontier(batch, idle, budget=2, seeds=(7,))
    two = frontier(batch, idle, budget=2, seeds=(7,))
    other = frontier(batch, idle, budget=2, seeds=(8,))
    assert one.spent == 2 and one.frontier_ids == two.frontier_ids
    assert set(one.frontier_ids) <= {case.id for case in batch.cases}
    assert len(batch.cases) > 2 and (one.frontier_ids != other.frontier_ids or len(batch.cases) <= 2)


def test_the_frontier_refuses_to_touch_the_holdout(batches: dict[str, CornerBatch]) -> None:
    idle = ScriptedAgent([], name="idle")
    with pytest.raises(HoldoutOverlap, match="held out"):
        frontier(corner_generator("retail"), idle, budget=2, seeds=(1, 2), holdout_seeds=(2, 9))
    batch = batches["banking"]
    with pytest.raises(HoldoutOverlap, match="held out"):
        frontier(batch, idle, budget=2, holdout_ids=(batch.cases[0].id,))
    # Disjoint holdouts are fine.
    report = frontier(batch, idle, budget=1, holdout_ids=("corner-elsewhere",), holdout_seeds=(99,))
    assert report.spent == 1
    with pytest.raises(ValueError):
        frontier(batch, idle, budget=0)


# -- the CLI --------------------------------------------------------------------------------------


_IDLE = "import json, sys\njson.load(sys.stdin)\nprint(json.dumps({'answer': 'Done.'}))\n"


def _exec(path: Path) -> str:
    import shlex

    return " ".join(shlex.quote(part) for part in (sys.executable, str(path)))


def test_the_cli_writes_a_case_set_run_reads_and_searches_its_frontier(worlds: dict[str, World], tmp_path: Path) -> None:
    worlds["retail"].compile().export(tmp_path / "corpus", overwrite=True)
    out = tmp_path / "corners"
    result = runner.invoke(app, ["evalrun", "corners", str(tmp_path / "corpus"), "--out", str(out)])
    assert result.exit_code == 0, result.output
    assert "confirmed_cause: 1 generated, 1 solvable, 0 dropped" in result.output
    summary = json.loads((out / "corners.json").read_text())
    cases, _ = read_case_set(out)
    assert summary["case_set"] == case_set_digest(cases) and len(cases) == summary["cases"] >= 2

    again = runner.invoke(app, ["evalrun", "corners", str(tmp_path / "corpus"), "--out", str(tmp_path / "again")])
    assert again.exit_code == 0, again.output
    assert (out / "evalrun-cases.jsonl").read_bytes() == (tmp_path / "again" / "evalrun-cases.jsonl").read_bytes()

    narrow = runner.invoke(app, ["evalrun", "corners", str(tmp_path / "corpus"), "--out", str(tmp_path / "narrow"),
                                 "--templates", "approver_handover", "--limit", "1", "--json"])
    assert narrow.exit_code == 0, narrow.output
    assert json.loads(narrow.output)["cases"] == 1

    ran = runner.invoke(app, ["evalrun", "run", str(out), "-o", str(tmp_path / "ref")])
    assert ran.exit_code == 0, ran.output
    assert f"{len(cases)}/{len(cases)} passed" in ran.output

    child = tmp_path / "idle.py"
    child.write_text(_IDLE, encoding="utf-8")
    searched = runner.invoke(app, ["evalrun", "frontier", str(out), "--champion-exec", _exec(child), "--budget", "2",
                                   "--out", str(tmp_path / "front"), "--timeout", "60"])
    assert searched.exit_code == 0, searched.output
    assert "2 frontier case(s) from 2 champion run(s) of 2" in searched.output
    front, _ = read_case_set(tmp_path / "front")
    assert len(front) == 2 and {case.id for case in front} <= {case.id for case in cases}
    assert json.loads((tmp_path / "front" / "frontier.json").read_text())["spent"] == 2

    refused = runner.invoke(app, ["evalrun", "frontier", str(out), "--champion-exec", _exec(child), "--budget", "2",
                                  "--out", str(tmp_path / "held"), "--holdout", str(out)])
    assert refused.exit_code != 0 and "held out" in refused.output
    refused = runner.invoke(app, ["evalrun", "frontier", str(out), "--champion-exec", _exec(child), "--budget", "2",
                                  "--out", str(tmp_path / "held"), "--seed", "3", "--holdout-seed", "3"])
    assert refused.exit_code != 0 and "held out" in refused.output
    assert not (tmp_path / "held").exists()

    unknown = runner.invoke(app, ["evalrun", "corners", str(tmp_path / "corpus"), "--out", str(tmp_path / "x"),
                                  "--templates", "nope"])
    assert unknown.exit_code != 0 and "nope" in unknown.output
    missing = runner.invoke(app, ["evalrun", "frontier", str(out), "--budget", "1", "--out", str(tmp_path / "y")])
    assert missing.exit_code != 0 and "champion" in missing.output
