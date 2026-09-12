"""Organise my drive, my inbox, my chats: the count is the point.

Every planned query wrote one record; a reorganisation is hundreds of small,
checkable moves. `worldloom.housekeeping` builds a corpus that needs tidying
in the world's own words and the cases that grade the tidying, through the
same grammar, compiler, served surface and graders every other row uses. The
reference agent passes every case on every connector; an agent that leaves
records behind scores by how many landed; and nothing on a record says where
it should be.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import housekeeping
from worldloom.enterprise_io import export_corpus, load_exported_corpus
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    axis_coverage,
    cases_from_corpus,
    run_case,
    run_cases,
    service_for,
)
from worldloom.retail import RetailWorld

PAIRS = (("drive", "drive"), ("drive", "sharepoint"), ("drive", "onedrive"),
         ("inbox", "email"), ("inbox", "outlook"), ("chats", "slack"), ("chats", "teams"))


@pytest.fixture(scope="module")
def world():
    return RetailWorld(seed=8128).build()


def _run(world, kind: str, connector: str, records: int = 40):
    spec = housekeeping.HousekeepingSpec(kind=kind, connector=connector, records=records)
    corpus = housekeeping.corpus(world, spec)
    cases = cases_from_corpus(corpus)
    return spec, corpus, cases


@pytest.mark.parametrize(("kind", "connector"), PAIRS)
def test_the_reference_agent_tidies_every_corpus_on_every_connector(world, kind: str, connector: str) -> None:
    spec, corpus, cases = _run(world, kind, connector)
    built = housekeeping.plan(world, spec)
    assert built.moves + built.deletions > 0 and len(cases) == len(built.queries)
    report = run_cases(service_for(cases, corpus.connector_data.records), cases, ReferenceAgent(cases))
    failed = [(r.case_id, r.error, r.score and r.score.assertion_fails[:3]) for r in report.results
              if not (r.graded and r.score is not None and r.score.passed)]
    assert failed == [], failed
    graded = sum(len(o.records) for case in cases for o in case.outcomes.structured)
    assert graded == built.moves + built.deletions, "every expected record is graded by fid, once"


def test_the_corpus_is_the_worlds_own_and_says_nothing_about_where_things_belong(world) -> None:
    spec = housekeeping.HousekeepingSpec(kind="drive", connector="drive", records=60, mess=0.4, stale=0.2, duplicates=0.1)
    built = housekeeping.plan(world, spec)
    files = [r for r in built.records if r.entity != "folder"]
    folders = [r for r in built.records if r.entity == "folder"]
    units = {unit.name for unit in world.business_units}
    assert {r.fields["unit"] for r in files} <= units
    assert {f.fields["name"] for f in folders if f.fields.get("parent") is None} == units | {"Archive"}
    assert len(files) == 60 + round(60 * 0.1)
    assert built.moves == round(60 * 0.4) + round(60 * 0.2) and built.deletions == round(60 * 0.1)
    for record in built.records:
        assert record.fields["housekeeping"] == built.tag
        assert not {"expected", "home", "target"} & set(record.fields), "the ground truth stays off the record"
    # Deterministic: the same world and spec build the same corpus and cases.
    again = housekeeping.plan(world, spec)
    assert [r.model_dump() for r in again.records] == [r.model_dump() for r in built.records]
    assert [q.id for q in again.queries] == [q.id for q in built.queries]
    salted = housekeeping.plan(world, spec.model_copy(update={"salt": "b"}))
    assert salted.tag != built.tag


def test_a_case_is_one_rule_stated_in_the_request_and_searched_by_its_predicate(world) -> None:
    _, _, cases = _run(world, "drive", "drive")
    case = next(c for c in cases if c.dimensions["group"].startswith("move:"))
    search = next(n for n in case.row["expected_dag"]["nodes"] if n["id"] == "read-0")
    fields = {clause["field"] for clause in search["payload"]["predicate"]["where"]}
    assert {"housekeeping", "unit_id", "reporting_period", "parent", "is_copy"} == fields
    assert "id" not in fields, "bound to the rule, not to the fixture's identities"
    assert len(search["expected_reads"]) == int(case.dimensions["records"])
    write = next(n for n in case.row["expected_dag"]["nodes"] if n["id"] == "write")
    assert write["op"] == "move" and write["for_each"]["node"] == "read-0" and write["payload"]["parent"]
    assert "belongs in the folder" in case.query and "read each back" in case.query
    per_record = next(a for a in case.row["assertions"] if a["type"] == "per_record_state")
    assert per_record["records"] == search["expected_reads"] and per_record["fields"] == {"parent": write["payload"]["parent"]}
    coverage = axis_coverage(cases)
    assert coverage.updates >= 1 and coverage.deletes == 1


def test_an_agent_that_leaves_records_behind_scores_by_how_many_landed(world) -> None:
    _, corpus, cases = _run(world, "drive", "drive")
    case = next(c for c in cases if c.dimensions["group"].startswith("move:"))
    write = next(n for n in case.row["expected_dag"]["nodes"] if n["id"] == "write")
    search = next(n for n in case.row["expected_dag"]["nodes"] if n["id"] == "read-0")
    targets = list(search["expected_reads"])
    folder = write["payload"]["parent"]
    calls = [("drive.search", {"entity": "file", "predicate": search["payload"]["predicate"], "max_results": 100})]
    calls += [("drive.move_file", {"id": fid, "parent": folder}) for fid in targets[:-1]]
    calls += [("drive.get_file", {"id": fid}) for fid in targets[:-1]]
    result = run_case(service_for(cases, corpus.connector_data.records), case, ScriptedAgent(calls, name="almost"))
    assert result.score is not None and not result.score.passed
    match = next(m for m in result.score.outcomes.structured if m.expected.node == "write")
    assert match.ratio == pytest.approx((len(targets) - 1) / len(targets))
    assert set(match.records) == set(targets[:-1]) and not match.met
    assert result.score.outcomes.collateral == ()
    assert result.score.outcomes.score < 1.0
    wrong = [f for f in result.score.assertion_fails if f.startswith("record_state_mismatch")]
    assert wrong == [f"record_state_mismatch:write:{targets[-1]}:parent"]


def test_the_corpus_exports_and_reloads_for_the_evalrun_command(world, tmp_path: Path) -> None:
    _, corpus, cases = _run(world, "chats", "slack")
    export_corpus(corpus, tmp_path / "hk")
    loaded = load_exported_corpus(tmp_path / "hk")
    again = cases_from_corpus(loaded)
    assert [c.id for c in again] == [c.id for c in cases]
    manifest = json.loads((tmp_path / "hk" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["queries"] == len(cases)
    requirement = loaded.queries[0].generation.source_requirements[0]
    assert requirement.bind == "predicate" and requirement.predicate is not None


def test_the_spec_refuses_a_connector_that_does_not_serve_the_kind() -> None:
    with pytest.raises(ValueError, match="does not serve"):
        housekeeping.HousekeepingSpec(kind="drive", connector="slack")
    with pytest.raises(ValueError, match="may not exceed"):
        housekeeping.HousekeepingSpec(kind="inbox", connector="email", mess=0.7, stale=0.5)


def test_a_thousand_files_is_one_number_away(world) -> None:
    """The count scales: the search is paged at the tool's page size and every
    record is graded, so a corpus past the old hundred-record cap compiles."""
    # Stale files share one destination (Archive), so the stale share is the
    # group that grows past the old cap.
    spec = housekeeping.HousekeepingSpec(kind="drive", connector="drive", records=400, mess=0.1, stale=0.4, duplicates=0.0)
    corpus = housekeeping.corpus(world, spec)
    cases = cases_from_corpus(corpus)
    biggest = max(cases, key=lambda c: int(c.dimensions["records"]))
    assert int(biggest.dimensions["records"]) > 100
    search = next(n for n in biggest.row["expected_dag"]["nodes"] if n["id"] == "read-0")
    assert len(search["expected_reads"]) == int(biggest.dimensions["records"]) and search["payload"]["max_results"] > 100
    result = run_case(service_for(cases, corpus.connector_data.records), biggest, ReferenceAgent(cases))
    assert result.score is not None and result.score.passed, (result.error, result.score and result.score.assertion_fails[:3])
    pages = [s for s in result.spans if s["node"] == "read-0"]
    assert len(pages) > 1, "paged at the tool's page size"
