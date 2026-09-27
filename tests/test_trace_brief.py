"""The trace-level brief: the connectors' own messages, the arguments behind them, and what worked instead.

The agent under test here is a scripted one that makes the mistakes a live
baseline made: a ServiceNow search against a table the instance does not
have (its encoded query, `priority=N^ORDERBYnumber`, is valid ServiceNow and
is no longer refused now that the vendor evaluator is the default engine),
an email search in the wrong dialect (with a different value every
case, so grouping has to normalise), an undeclared argument the surface
refuses, and a draft without the field a create requires. Every error in the
brief is one the service really returned. The reference agent's run over the
training cases supplies the accepted calls.
"""

from __future__ import annotations

import inspect
from pathlib import Path
from typing import Any

import pytest

from worldloom import RetailWorld, packkit
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.autopsy import autopsy, render_brief
from worldloom.evalrun.evidence import (
    BRIEF_MODES,
    admit_reference,
    brief_mode,
    collect,
    fit_summary,
    normalise_message,
    render_evidence,
    trace_brief,
)
from worldloom.evalrun.improve import Improver, improve, split_cases
from worldloom.evalrun.results import read_run, write_run
from worldloom.packkit.authoring import MAX_MESSAGE, clip_message
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile


@pytest.fixture(scope="module")
def world() -> dict[str, Any]:
    built_world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(built_world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(40)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    cases = cases_from_corpus(built)
    records = built.connector_data.records
    train, held = split_cases(cases, holdout_share=0.25)
    run = run_cases(service_for(train, records), train, Sloppy(cases))
    reference = run_cases(service_for(train, records), train, ReferenceAgent(cases))
    return {"cases": cases, "records": records, "train": train, "held": held, "run": run, "reference": reference,
            "found": autopsy(run, cases=train)}


def _script(index: int, case: Any) -> ScriptedAgent:
    connectors = sorted({node.connector for node in case.plan.nodes if node.kind != "transform"})
    calls: list[tuple[str, dict[str, Any]]] = []
    if "servicenow" in connectors:
        calls += [("servicenow.search_records", {"query": f"priority={index % 4 + 1}^ORDERBYnumber",
                                                  "entity": "incidents"}),
                  ("servicenow.search_records", {"query": "stock", "limit": 5})]
    if "email" in connectors:
        calls += [("email.search_messages", {"query": f"subject:stock-{index}"}),
                  ("email.create_draft", {"name": "Stock review", "fields": {"body": "see attached"}})]
    return ScriptedAgent(calls, name="sloppy", answer="I could not find the records.")


class Sloppy:
    """A per-case scripted agent: each case replays its own malformed calls."""

    name = "sloppy"

    def __init__(self, cases: Any, pack: Any = None) -> None:
        self.scripts = {case.id: _script(index, case) for index, case in enumerate(cases)}

    def run(self, task: Any, tools: Any) -> Any:
        return self.scripts[task.case_id].run(task, tools)


def _group(evidence: Any, tool: str, code: str) -> Any:
    matches = [group for group in evidence.errors if group.tool == tool and group.code == code]
    assert len(matches) == 1, [(group.tool, group.code, group.pattern) for group in evidence.errors]
    return matches[0]


def _legacy_brief(found: Any, room: int) -> str:
    """The summary brief exactly as the loop fitted it before trace briefs existed."""
    for shown in range(len(found.clusters), 0, -1):
        brief = render_brief(found, clusters=shown)
        if len(brief) <= room:
            return str(brief)
    return clip_message(render_brief(found, clusters=1), room)


def _servicenow_cases(world: dict[str, Any]) -> int:
    return sum(1 for case in world["train"]
               if any(node.connector == "servicenow" for node in case.plan.nodes if node.kind != "transform"))


def test_the_catalogue_groups_real_errors_with_the_failing_args_and_an_accepted_shape(world: dict[str, Any]) -> None:
    evidence = collect(world["run"], cases=world["train"], found=world["found"],
                       reference=admit_reference(world["reference"], train=world["train"], holdout=world["held"]))
    servicenow = _servicenow_cases(world)
    assert servicenow >= 4

    search = _group(evidence, "servicenow.search_records", "validation_error")
    # Four different priorities, one wrong table: one group.
    assert search.count == servicenow and search.cases == servicenow
    assert search.pattern == "Unknown entity <value>"
    assert search.message == "Unknown entity 'incidents'"
    assert search.arg_names == (("entity", "query"),)
    assert any("^ORDERBYnumber" in example for example in search.examples)
    reference = [shape for shape in search.accepted if shape.source == "reference"]
    assert reference and "predicate" in reference[0].names and "<id>" in reference[0].example
    assert "CONN-" not in reference[0].example

    # A different value in every case, still one group: the quoted value is masked.
    email = _group(evidence, "email.search_messages", "validation_error")
    assert email.count == len(world["train"])
    assert email.pattern == "Invalid filter clause: Syntax error at position <n> in <value>."
    assert len(email.examples) == 3

    refused = _group(evidence, "servicenow.search_records", "refused")
    assert refused.kind == "unknown_arguments" and refused.arg_names == (("limit", "query"),)
    assert not refused.examples  # the surface keeps names, not values

    draft = _group(evidence, "email.create_draft", "validation_error")
    assert draft.message == "Required field 'subject' is missing on create of message"
    assert draft.accepted and "subject" in draft.accepted[-1].example
    # A write's payload is reduced to its field names.
    assert draft.examples == ('{"fields": "{body}", "name": "<12 chars>"}',)

    contracts = {contract.tool: contract for contract in evidence.contracts}
    assert set(contracts) == {group.tool for group in evidence.errors}
    assert contracts["servicenow.search_records"].params["predicate"] == "object?"
    assert contracts["servicenow.search_records"].query_language == "encoded_query"
    assert "priority" in contracts["servicenow.search_records"].query_fields
    assert contracts["email.create_draft"].required_on_create == {"message": ("subject",)}

    text = render_evidence(evidence, 20000)
    assert "message: Unknown entity 'incidents'" in text
    assert "params: query string?, predicate object?" in text
    assert "accepted from the reference agent" in text
    assert "Not shown for length" not in text


def test_trajectories_follow_the_top_clusters_with_the_reference_beside_them(world: dict[str, Any]) -> None:
    evidence = collect(world["run"], cases=world["train"], found=world["found"],
                       reference=admit_reference(world["reference"], train=world["train"]))
    assert 1 <= len(evidence.trajectories) <= 3
    assert [item.cluster for item in evidence.trajectories] == [
        cluster.key for cluster in world["found"].clusters[:len(evidence.trajectories)]]
    assert len({item.case_id for item in evidence.trajectories}) == len(evidence.trajectories)
    first = evidence.trajectories[0]
    assert any("validation_error:" in turn for turn in first.turns)
    assert first.answer == "I could not find the records."
    assert first.reference is not None and first.reference
    reference_text = "\n".join(item for trajectory in evidence.trajectories for item in trajectory.reference or ())
    # The reference shows tools and shapes, never its answer or a record id.
    assert "Completed" not in reference_text and "CONN-" not in reference_text
    # A refusal sits among the spans where it happened: after the search before it.
    turns = [turn for trajectory in evidence.trajectories for turn in trajectory.turns]
    refused = [index for index, turn in enumerate(turns) if "refused before any connector saw it" in turn]
    assert refused and "unknown_arguments: ['limit']" in turns[refused[0]]
    assert "servicenow.search_records" in turns[refused[0] - 1] and "ORDERBYnumber" in turns[refused[0] - 1]


def test_the_traces_brief_fits_the_message_limit_on_a_large_failure_set(world: dict[str, Any], tmp_path: Path) -> None:
    found = world["found"]
    assert found.failing >= 20
    champion = packkit.resolve("agent:baseline")
    improver = Improver(run=lambda s, a: world["run"], agent_for=lambda p: None, exchange=lambda p: {},
                        out=tmp_path, brief_mode="traces", reference_run=world["reference"])
    brief = improver._fitted_brief(found, champion, 1, run=world["run"], train=world["train"], holdout=world["held"])
    assert len(improver._message(champion, brief, 1)) <= MAX_MESSAGE
    assert brief.startswith("Autopsy of agent 'sloppy'")
    assert "Connector errors, most costly first" in brief
    assert "Tool contracts as served" in brief

    # A tight room drops whole items from the back and says so.
    tight = trace_brief(found, world["run"], room=2500, train=world["train"], holdout=world["held"],
                        reference=world["reference"])
    assert len(tight) <= 2500
    assert "Not shown for length:" in tight
    assert "E1. " in tight  # the most costly error group survives
    evidence = collect(world["run"], cases=world["train"], found=found, reference=world["reference"])
    small = render_evidence(evidence, 1200)
    assert len(small) <= 1200 and "Not shown for length:" in small and "trajectory(ies)" in small


def test_summary_mode_is_byte_identical_to_the_brief_before_traces(world: dict[str, Any], tmp_path: Path) -> None:
    found = world["found"]
    champion = packkit.resolve("agent:baseline")
    assert brief_mode() == "summary" and BRIEF_MODES == ("summary", "traces")
    for mode in (None, "summary"):
        improver = Improver(run=lambda s, a: world["run"], agent_for=lambda p: None, exchange=lambda p: {},
                            out=tmp_path, brief_mode=mode, reference_run=world["reference"])
        room = MAX_MESSAGE - len(improver._message(champion, "", 1))
        with_run = improver._fitted_brief(found, champion, 1, run=world["run"], train=world["train"],
                                          holdout=world["held"])
        assert with_run == improver._fitted_brief(found, champion, 1) == _legacy_brief(found, room)
        assert fit_summary(found, 900) == _legacy_brief(found, 900)
        assert "Trace evidence" not in with_run


def test_a_held_out_run_never_reaches_a_brief(world: dict[str, Any], tmp_path: Path) -> None:
    train, held = world["train"], world["held"]
    records = world["records"]
    everything = run_cases(service_for(world["cases"], records), world["cases"], ReferenceAgent(world["cases"]))
    with pytest.raises(ValueError, match="held-out case"):
        admit_reference(everything, train=train, holdout=held)
    marked = world["reference"].model_copy(update={"split": "holdout"})
    with pytest.raises(ValueError, match="held-out run"):
        admit_reference(marked, train=train, holdout=held)
    held_run = run_cases(service_for(held, records), held, ReferenceAgent(world["cases"]))
    with pytest.raises(ValueError, match="held-out"):
        admit_reference(held_run, train=train, holdout=held)
    with pytest.raises(ValueError, match="training runs only"):
        trace_brief(world["found"], world["run"].model_copy(update={"split": "holdout"}), room=6000,
                    train=train, holdout=held)
    # Results for cases outside the training set are dropped, not shown.
    kept = admit_reference(world["reference"], train=train[:5], holdout=())
    assert {row.case_id for row in kept.results} == {case.id for case in train[:5]}

    # The loop refuses such a reference before paying for a single run.
    runs: list[int] = []

    def run(subset: Any, agent: Any) -> Any:
        runs.append(len(subset))
        return run_cases(service_for(subset, records), subset, agent)

    with pytest.raises(ValueError, match="held-out case"):
        improve(packkit.resolve("agent:baseline"), world["cases"], run=run,
                agent_for=lambda pack: Sloppy(world["cases"]), exchange=lambda payload: {}, out=tmp_path / "loop",
                holdout_share=0.25, rounds=1, brief="traces", reference_run=everything)
    assert runs == []


def test_a_traces_loop_shows_the_proposer_evidence_and_no_held_out_case(world: dict[str, Any], tmp_path: Path) -> None:
    cases, records, held = world["cases"], world["records"], world["held"]
    train_ids = {case.id for case in world["train"]}
    seen: list[dict[str, Any]] = []

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        seen.append(payload)
        body = {**payload["draft"]["body"], "instruction": "Use the connectors' own query syntax."}
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": body}}

    report = improve(packkit.resolve("agent:baseline"), cases,
                     run=lambda subset, agent: run_cases(service_for(subset, records), subset, agent),
                     agent_for=lambda pack: Sloppy(cases, pack), exchange=exchange, out=tmp_path / "loop",
                     holdout_share=0.25, rounds=1, brief="traces", reference_run=world["reference"], ablate=False)
    assert report.rounds[0].brief_digest is not None
    message = seen[0]["message"]
    assert len(message) <= MAX_MESSAGE
    assert "Unknown entity" in message and "accepted from the reference agent" in message
    sealed = sorted({case.id for case in held} - train_ids)
    assert sealed and not any(case_id in message for case_id in sealed)
    assert not any(case_id[:12] in message for case_id in sealed)


def test_the_brief_is_deterministic_and_survives_a_round_trip_to_disk(world: dict[str, Any], tmp_path: Path) -> None:
    kwargs = {"room": 7000, "train": world["train"], "holdout": world["held"], "reference": world["reference"]}
    first = trace_brief(world["found"], world["run"], **kwargs)
    assert first == trace_brief(world["found"], world["run"], **kwargs)
    write_run(tmp_path / "run", world["run"])
    write_run(tmp_path / "reference", world["reference"])
    again = trace_brief(world["found"], read_run(tmp_path / "run"), room=7000, train=world["train"],
                        holdout=world["held"], reference=read_run(tmp_path / "reference"))
    assert again == first


def test_messages_are_normalised_by_ids_values_and_numbers() -> None:
    assert normalise_message("Message or thread not found: MSG-12") == "Message or thread not found: <id>"
    assert normalise_message("unsupported odata query clause 'subject:stock-3'") == \
        "unsupported odata query clause <value>"
    assert normalise_message("no record CONN-JIRA-61F322A8A8FA2AD067AFA60D after 3 tries") == \
        "no record <id> after <n> tries"
    with pytest.raises(ValueError, match="unknown brief mode"):
        brief_mode("full")


def test_the_brief_reaches_the_sdk_the_cli_and_campaigns() -> None:
    from typer import main as typer_main

    from worldloom.cli import app
    from worldloom.evalrun import campaign as campaign_module
    from worldloom.evalrun.session import EvalSession

    assert "brief" in inspect.signature(improve).parameters
    assert {"brief", "reference_run"} <= set(inspect.signature(EvalSession.improver).parameters)
    # A campaign passes improve options through untouched; the brief is not one it owns.
    assert "brief" not in campaign_module._OWNED
    # Read the declared options, not rendered help: CI forces colour, which splits flags.
    def flags(name: str) -> set[str]:
        group = typer_main.get_command(app).commands["evalrun"]  # type: ignore[attr-defined]
        return {opt for param in group.commands[name].params for opt in param.opts}

    assert {"--brief", "--reference-run"} <= flags("improve")
    assert "--brief" in flags("campaign")
