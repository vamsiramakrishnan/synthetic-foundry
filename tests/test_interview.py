"""A whole world from an interview: the refusal loop per layer, determinism, resumability, provenance, levels.

The scripted interviewee (`examples/interviews/kestrel-vale.json`) answers
every question twice: a first answer each layer's lint refuses on purpose,
then a clean one. So one scripted run exercises the refusal loop on every
layer, and everything downstream (build, narration, render, cases, the
reference agent) runs offline and deterministically.
"""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import interview
from worldloom.cli import app
from worldloom.enterprise_dag import EnterpriseDag, EnterpriseDagNode, dag_metrics
from worldloom.interview import cases as interview_cases
from worldloom.interview.layers import lint, next_question
from worldloom.interview.orchestrator import TRANSCRIPT

ROOT = Path(__file__).resolve().parent.parent
SCRIPT = ROOT / "examples" / "interviews" / "kestrel-vale.json"
runner = CliRunner()


def _script() -> dict:
    return json.loads(SCRIPT.read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def completed(tmp_path_factory: pytest.TempPathFactory) -> interview.InterviewRun:
    directory = tmp_path_factory.mktemp("interview")
    return interview.run(interview.ScriptedInterviewee(_script()), directory)


@pytest.fixture(scope="module")
def realised(completed: interview.InterviewRun) -> interview.Realised:
    return interview.realise(completed.opened.state)


# -- the orchestrator ------------------------------------------------------------------------


def test_the_scripted_interview_completes_through_every_layer(completed: interview.InterviewRun) -> None:
    assert completed.status == "complete"
    settled = [key for key, _ in completed.opened.state.answers]
    assert settled == ["company", "lobs", "employees", "processes:commercial", "processes:delivery",
                       "processes:service", "documents", "timeline", "evals"]
    directory = completed.opened.directory
    assert directory is not None
    for name in (TRANSCRIPT, "pack.json", "resolution.json"):
        assert (directory / name).is_file(), name


def test_every_layer_refuses_its_first_answer_with_findings_then_accepts(completed: interview.InterviewRun) -> None:
    rounds = completed.opened.rounds
    by_question: dict[str, list[dict]] = {}
    for entry in rounds:
        by_question.setdefault(entry["question"], []).append(entry)
    assert {entry["layer"] for entry in rounds} == set(interview.LAYERS)
    for question, entries in by_question.items():
        assert [entry["status"] for entry in entries] == ["refused", "accepted"], question
        assert entries[0]["findings"], question
        assert entries[1]["findings"] == [], question
    expected = {
        "company": "identity.company_name",
        "lobs": "at least two lines of business",
        "employees": "cannot report to",
        "processes:commercial": "keeps no process steps",
        "processes:delivery": "required slot 'sponsor'",
        "processes:service": "which service does not declare",
        "documents": "sits below the author",
        "timeline": "nothing changes what later documents say",
        "evals": "reads one system once",
    }
    for question, fragment in expected.items():
        assert any(fragment in finding for finding in by_question[question][0]["findings"]), (question, by_question[question][0]["findings"])


def test_a_refusal_commits_nothing_and_questions_end_the_loop(tmp_path: Path) -> None:
    def asks(payload: dict) -> dict:
        return {"request_id": payload["request_id"], "questions": ["Which country is the company in?"]}

    result = interview.run(asks, tmp_path)
    assert result.status == "questions" and result.question == "company"
    assert result.questions == ("Which country is the company in?",)
    assert result.opened.state.answers == ()


def test_the_interview_is_deterministic(completed: interview.InterviewRun, tmp_path: Path) -> None:
    again = interview.run(interview.ScriptedInterviewee(_script()), tmp_path)
    assert again.status == "complete"
    first = completed.opened.directory
    assert first is not None
    for name in (TRANSCRIPT, "pack.json", "resolution.json"):
        assert (first / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_an_interrupted_interview_resumes_where_it_stopped(completed: interview.InterviewRun, tmp_path: Path) -> None:
    # Paused between questions.
    paused = interview.run(interview.ScriptedInterviewee(_script()), tmp_path, stop_after=4)
    assert paused.status == "paused" and paused.question == "processes:delivery"
    # Stopped inside a question, after one refused attempt: the budget is spent.
    stuck = interview.run(interview.ScriptedInterviewee(_script()), tmp_path, max_rounds=1)
    assert stuck.status == "exhausted" and stuck.question == "processes:delivery" and stuck.findings
    reopened = interview.open_interview(tmp_path)
    assert reopened.attempt == 1 and reopened.findings == stuck.findings
    # A fresh interviewee picks up at attempt two, exactly where the transcript left it.
    resumed = interview.run(interview.ScriptedInterviewee(_script()), tmp_path)
    assert resumed.status == "complete"
    first = completed.opened.directory
    assert first is not None
    for name in (TRANSCRIPT, "pack.json", "resolution.json"):
        assert (first / name).read_bytes() == (tmp_path / name).read_bytes(), name


def test_a_transcript_whose_accepted_answer_no_longer_lints_is_refused(completed: interview.InterviewRun, tmp_path: Path) -> None:
    source = completed.opened.directory
    assert source is not None
    lines = (source / TRANSCRIPT).read_text(encoding="utf-8").splitlines()
    tampered = []
    for line in lines:
        entry = json.loads(line)
        if entry["question"] == "lobs" and entry["status"] == "accepted":
            entry["answer"]["lobs"] = entry["answer"]["lobs"][:1]
        tampered.append(json.dumps(entry, sort_keys=True))
    (tmp_path / TRANSCRIPT).write_text("\n".join(tampered) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="no longer lints"):
        interview.open_interview(tmp_path)


def test_a_reply_to_another_request_is_refused(tmp_path: Path) -> None:
    opened = interview.open_interview(tmp_path)
    verdict = interview.submit(opened, {"request_id": "not-this-one", "answer": {"spec": {}}})
    assert verdict.status == "refused" and "not" in verdict.findings[0]
    assert opened.state.answers == () and opened.attempt == 1


def test_the_file_round_trip_answers_one_question_at_a_time(tmp_path: Path) -> None:
    script = _script()
    request_path, reply_path = tmp_path / "request.json", tmp_path / "reply.json"
    directory = tmp_path / "interview"
    result = runner.invoke(app, ["interview", "next", str(directory), "-o", str(request_path)])
    assert result.exit_code == 0, result.output
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["schema"] == interview.REQUEST_SCHEMA and request["question"]["id"] == "company"
    assert request["response_schema"]["properties"]["answer"]
    reply_path.write_text(json.dumps({"request_id": request["request_id"], "answer": script["answers"]["company"][0]}))
    refused = runner.invoke(app, ["interview", "answer", str(directory), "--reply", str(reply_path)])
    assert refused.exit_code == 2, refused.output
    assert "company_name" in refused.output
    result = runner.invoke(app, ["interview", "next", str(directory), "-o", str(request_path)])
    request = json.loads(request_path.read_text(encoding="utf-8"))
    assert request["attempt"] == 1 and request["findings"] and request["draft"] is not None
    reply_path.write_text(json.dumps({"request_id": request["request_id"], "answer": script["answers"]["company"][1]}))
    accepted = runner.invoke(app, ["interview", "answer", str(directory), "--reply", str(reply_path)])
    assert accepted.exit_code == 0, accepted.output
    assert "next: lobs" in accepted.output
    status = runner.invoke(app, ["interview", "status", str(directory), "--json"])
    assert json.loads(status.output)["settled"] == ["company"]


def test_the_cli_runs_a_scripted_interview_and_names_where_it_paused(tmp_path: Path) -> None:
    paused = runner.invoke(app, ["interview", "run", str(tmp_path), "--script", str(SCRIPT), "--stop-after", "2"])
    assert paused.exit_code == 2, paused.output
    assert "employees" in paused.output
    done = runner.invoke(app, ["interview", "run", str(tmp_path), "--script", str(SCRIPT)])
    assert done.exit_code == 0, done.output
    assert "complete: 9 questions settled" in done.output


# -- the lints that tie layers together -------------------------------------------------------


def _state_before(completed: interview.InterviewRun, question: str) -> interview.State:
    answers = completed.opened.state.answers
    index = [key for key, _ in answers].index(question)
    return interview.State(answers[:index])


def test_the_evals_lint_ties_every_read_to_a_declared_step_and_keeps_one_source_per_entity(completed: interview.InterviewRun) -> None:
    state = _state_before(completed, "evals")
    question = next_question(state)
    assert question is not None and question.layer == "evals"
    good = _script()["answers"]["evals"][1]
    _, findings = lint(question, good, state)
    assert findings == []
    doubled = copy.deepcopy(good)
    manager = next(item for item in doubled["intents"] if item["level"] == "manager")
    manager["reads"].append(dict(manager["reads"][0], step=manager["reads"][0]["step"]))
    alias = copy.deepcopy(good)
    alias["intents"][0]["deliver"].pop("format")
    _, findings = lint(question, doubled, state)
    assert any("one case reads each system entity once" in finding for finding in findings), findings
    _, findings = lint(question, alias, state)
    assert any("name the one to create as `format`" in finding for finding in findings), findings


def test_the_processes_lint_reads_the_compilers_authorship_contract(completed: interview.InterviewRun) -> None:
    state = _state_before(completed, "processes:service")
    question = next_question(state)
    assert question is not None and question.id == "processes:service"
    answer = copy.deepcopy(_script()["answers"]["processes:service"][1])
    answer["episodes"][0]["artifacts"][0]["domain"] = "engineering"
    _, findings = lint(question, answer, state)
    assert any("ServiceOperations author (svc_incident) cannot own an engineering document" in finding
               for finding in findings), findings


# -- the world, its cases and their provenance ------------------------------------------------


def test_the_assembled_pack_is_the_existing_company_pack(completed: interview.InterviewRun) -> None:
    from worldloom import packs

    pack = interview.pack_of(completed.opened.state)
    assert packs.lint(pack) == []
    assert [lob.name for lob in pack.lobs] == ["commercial", "delivery", "service"]
    assert {spec.name for spec in pack.episodes} == {"TradeAgreementCycle", "ProjectSteering", "IncidentReview"}
    assert any(policy.effective_from == "2026-03" for policy in pack.lore)


def test_cases_are_generated_per_level_with_the_level_shape(realised: interview.Realised) -> None:
    by_level: dict[str, list] = {}
    for item in realised.planned:
        by_level.setdefault(item.level, []).append(item)
    assert {level: len(items) for level, items in by_level.items()} == {"ic": 3, "manager": 3, "director": 3, "executive": 3}
    for level, items in by_level.items():
        for item in items:
            assert item.query.dimensions["dag_shape"] == interview.SHAPES[level]
            assert item.query.dimensions["dag_grammar"] == "enterprise-dag@1"
            dag = EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in item.query.expected_dag))
            metrics = dag_metrics(dag)
            reads = [node for node in dag.nodes if node.kind == "search"]
            if level == "ic":
                assert len(reads) == 1 and metrics["width"] == 1 and metrics["conditional"] == 0
            elif level == "manager":
                assert len({node.connector for node in reads}) >= 2 and metrics["conditional"] == 0
            elif level == "director":
                assert metrics["conditional"] == 4
                documents = [source for source in item.query.generation.source_requirements
                             if any(clause.field == "artifact_type" for clause in source.predicate.where)]
                assert documents and all(any(clause.field == "period" for clause in source.predicate.where) for source in documents)
            else:
                assert metrics["for_each"] == len(reads) >= 3
                assert len(item.query.dimensions["interview_lobs"].split("+")) >= 2
    depths = {level: max(dag_metrics(EnterpriseDag(nodes=tuple(EnterpriseDagNode.model_validate(node) for node in item.query.expected_dag)))["depth"]
                         for item in items) for level, items in by_level.items()}
    assert depths["executive"] > depths["ic"]


def test_revision_aware_reads_select_only_documents_with_a_revision_chain(realised: interview.Realised) -> None:
    revised = [source for item in realised.planned for source in item.query.generation.source_requirements
               if any(clause.field == "revisions" for clause in source.predicate.where)]
    assert revised
    records = {record.id: record for record in realised.corpus.connector_data.records}
    for fixture in realised.corpus.fixtures:
        for key, selected in fixture.input_record_ids.items():
            for rid in selected:
                assert records[rid].fact_ids, (key, rid)
    for item in realised.planned:
        for source in item.query.generation.source_requirements:
            clauses = {clause.field: clause.value for clause in source.predicate.where}
            if "revisions" in clauses:
                fixture = next(f for f in realised.corpus.fixtures if f.query_id == item.query.id)
                for rid in fixture.input_record_ids[f"{source.connector}:{source.entity}"]:
                    assert records[rid].fields["revisions"] >= 2
                    assert records[rid].fields["period"] == clauses["period"]


def test_every_node_carries_the_question_that_produced_it(realised: interview.Realised) -> None:
    questions = set(realised.resolution["questions"])
    for item in realised.planned:
        provenance = json.loads(item.query.dimensions["interview_provenance"])
        assert provenance == item.provenance
        assert set(provenance) == {node["id"] for node in item.query.expected_dag}
        for node, origin in provenance.items():
            assert origin["question"] in questions, (node, origin)
            if node.startswith("read-") and "step" in origin:
                assert origin["question"].startswith("processes:")
                assert origin["system"] in realised.resolution["steps"][origin["step"]]["systems"]
            if node.startswith("read-") and "document" in origin:
                assert origin["question"] == "documents"


def test_records_across_systems_share_the_worlds_identifiers(realised: interview.Realised) -> None:
    records = realised.corpus.connector_data.records
    steps = [record for record in records if record.fields.get("interview_step")]
    assert {record.connector for record in steps} >= {"jira", "servicenow", "salesforce", "slack", "outlook", "sharepoint", "confluence"}
    by_event: dict[str, set[str]] = {}
    for record in steps:
        for event in record.event_ids:
            by_event.setdefault(event, set()).add(record.connector)
    assert max(len(connectors) for connectors in by_event.values()) >= 3
    periods = {record.fields["period"] for record in steps}
    assert periods == set(realised.resolution["periods"])


def test_the_reference_agent_passes_every_generated_case(realised: interview.Realised) -> None:
    from worldloom.interview.realise import prove

    proof = prove(realised)
    assert proof == {level: {"cases": 3, "passed": 3} for level in ("ic", "manager", "director", "executive")}


def test_the_measurements_count_what_the_interview_asked_for(realised: interview.Realised) -> None:
    measured = realised.measurements
    assert measured["employees"]["by_level"] == {"director": 3, "executive": 3, "ic": 3, "manager": 3}
    assert measured["lobs"] == 3 and measured["processes"] == 3
    assert set(measured["systems_touched"]) >= {"servicenow", "salesforce", "jira", "sharepoint", "confluence", "slack", "drive", "outlook"}
    assert measured["timeline"]["periods"] == 4 and measured["timeline"]["org_changes"] == 1
    assert measured["revisions"]["revision_files"] > 0
    levels = {key.split("@")[1] for key in measured["documents"]["by_type_and_level"]}
    assert {"manager", "director", "executive"} <= levels
    for level, size in measured["cases"]["case_sets"].items():
        assert size["tools"] <= size["tools_admitted"], level


def test_the_export_is_byte_identical_across_builds(realised: interview.Realised, completed: interview.InterviewRun,
                                                    tmp_path: Path) -> None:
    interview.export(realised, tmp_path / "one")
    again = interview.realise(completed.opened.state)
    interview.export(again, tmp_path / "two")
    one = {path.relative_to(tmp_path / "one"): path.read_bytes() for path in sorted((tmp_path / "one").rglob("*")) if path.is_file()}
    two = {path.relative_to(tmp_path / "two"): path.read_bytes() for path in sorted((tmp_path / "two").rglob("*")) if path.is_file()}
    assert one.keys() == two.keys()
    assert [str(key) for key in one if one[key] != two[key]] == []
    for level in ("ic", "manager", "director", "executive"):
        assert (tmp_path / "one" / "evals" / level / "provenance.jsonl").is_file()


def test_an_ungroundable_read_is_refused_with_the_intent_named(realised: interview.Realised, completed: interview.InterviewRun) -> None:
    intents = list(completed.opened.state.evals.intents)
    broken = intents[0].model_copy(update={"reads": [intents[0].reads[0].model_copy(update={"period": "2031-01"})]})
    with pytest.raises(interview_cases.CaseRefusal, match="ic-analyst-pipeline"):
        interview_cases.plan(realised.world, realised.resolution, [broken])
