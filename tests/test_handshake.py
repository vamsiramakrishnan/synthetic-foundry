"""The agent handshake.

Worldloom does not call a model — an agent drives it. So the contract under test is
not a function signature but a pair of JSON documents: what the harness asks for,
and what it accepts back.

The properties that matter are that a request is answerable *without reading this
repository*, and that a rejection says enough to fix the problem.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.narrative import ResponseProvider, handshake, references

runner = CliRunner()
PERIOD = "2026-03"


@pytest.fixture(scope="module")
def world() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()


def answer(document: dict, *, restate: bool = False, invent: bool = False) -> dict:
    """Answer every request the way a compliant agent would."""
    responses = []
    for request in document["requests"]:
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        sentences, claims = [], []
        for fact in picked:
            lead = "It was recorded at the time as" if fact["superseded"] else "The position was"
            sentence = f"{lead} {{{{fact:{fact['id']}}}}}."
            sentences.append(sentence)
            claims.append({"text": sentence, "supporting_fact_ids": [fact["id"]]})
        text = " ".join(sentences)
        if restate:
            text += " Revenue finished 2.48% below plan."
        if invent:
            text += " Northgate Logistics was responsible."
        responses.append({"id": request["id"], "text": text, "claims": claims})
    return {"responses": responses}


# ---------------------------------------------------------------------------
# The request is self-describing
# ---------------------------------------------------------------------------


def test_a_request_carries_everything_needed_to_answer_it(world: World) -> None:
    """An agent should not have to read this repository to write the prose."""
    document = handshake.requests_document(world)
    assert document["requests"]
    assert document["rules"], "the contract must travel with the request"
    assert document["reference_syntax"] == "{{fact:FACT-0001}}"
    assert "responses" in document["response_shape"]

    for request in document["requests"]:
        assert request["id"] == f"{request['artifact_id']}/{request['section']}"
        assert request["written_by"] and request["voice"] and request["audience"]
        assert request["target_words"] > 0
        assert request["facts"], "a request with no facts should not be asked"
        for fact in request["facts"]:
            assert fact["statement"], "a fact ID alone is not answerable"
            assert "authority" in fact and "superseded" in fact and "required" in fact


def test_the_rules_name_the_traps_an_agent_falls_into(world: World) -> None:
    rules = " ".join(handshake.RULES).lower()
    assert "never write a figure" in rules
    assert "superseded" in rules
    assert "required" in rules
    assert "knows_as_of" in rules


def test_a_request_never_offers_a_fact_the_author_could_not_know(world: World) -> None:
    facts = {f.id: f for f in world.facts}
    for request in handshake.pending(world):
        if request.temporal_cutoff is None:
            continue
        for fact_id in request.allowed_fact_ids:
            assert facts[fact_id].valid_from <= request.temporal_cutoff, (
                f"{request.artifact_id}/{request.section} was offered a fact from its own future"
            )


def test_a_triage_request_is_forbidden_from_naming_a_root_cause(world: World) -> None:
    triage = next(
        r for r in handshake.pending(world)
        if r.artifact_type == "confluence_page"
    )
    assert "root cause" in triage.forbidden_claims


# ---------------------------------------------------------------------------
# Acceptance and rejection
# ---------------------------------------------------------------------------


def test_a_compliant_answer_is_accepted(world: World) -> None:
    verdicts = handshake.review(world, handshake.parse_responses(answer(handshake.requests_document(world))))
    rejected = {name: v for name, v in verdicts.items() if not v.accepted}
    assert not rejected, "\n".join(f"{n}: {v.feedback}" for n, v in rejected.items())


def test_a_restated_figure_is_rejected_with_the_offending_text(world: World) -> None:
    document = handshake.requests_document(world)
    verdicts = handshake.review(world, handshake.parse_responses(answer(document, restate=True)))

    rejected = [v for v in verdicts.values() if not v.accepted]
    assert rejected
    detail = " ".join(str(vi) for v in rejected for vi in v.violations)
    assert "bare_number" in detail
    assert "2.48" in detail, "the agent needs to be told which text was wrong"


def test_an_invented_entity_is_rejected(world: World) -> None:
    document = handshake.requests_document(world)
    verdicts = handshake.review(world, handshake.parse_responses(answer(document, invent=True)))
    detail = " ".join(str(vi) for v in verdicts.values() for vi in v.violations)
    assert "unknown_entity" in detail
    assert "Northgate Logistics" in detail


def test_a_missing_response_is_named_rather_than_ignored(world: World) -> None:
    document = handshake.requests_document(world)
    partial = answer(document)
    partial["responses"] = partial["responses"][:2]

    verdicts = handshake.review(world, handshake.parse_responses(partial))
    missing = [n for n, v in verdicts.items() if any(x.code == "missing_response" for x in v.violations)]
    assert len(missing) == len(document["requests"]) - 2


def test_every_rejection_is_reported_not_just_the_first(world: World) -> None:
    """An agent fixing five violations in one pass beats five round trips."""
    document = handshake.requests_document(world)
    verdicts = handshake.review(world, handshake.parse_responses(answer(document, restate=True, invent=True)))
    assert len([v for v in verdicts.values() if not v.accepted]) > 1


def test_a_malformed_response_document_says_what_is_wrong() -> None:
    with pytest.raises(ValueError, match="responses"):
        handshake.parse_responses({"answers": []})
    with pytest.raises(ValueError, match="no 'id'"):
        handshake.parse_responses({"responses": [{"text": "hello"}]})


# ---------------------------------------------------------------------------
# The agent as provider
# ---------------------------------------------------------------------------


def test_accepted_prose_goes_through_the_same_pipeline(world: World) -> None:
    """No shortcut for agent-written prose: same validation, same ledger."""
    responses = handshake.parse_responses(answer(handshake.requests_document(world)))
    narrated = world.narrate(ResponseProvider(responses, model_id="claude-opus-5"), retries=0)

    assert len(narrated.ledger) == len(responses)
    assert {entry.model_id for entry in narrated.ledger} == {"claude-opus-5"}

    for ir in narrated.artifact_irs:
        for section in ir.sections:
            if section.body:
                assert not references.bare_numbers(section.body)


def test_agent_prose_replays_from_the_ledger(world: World) -> None:
    """The model identity is the agent's, and replay works the same way."""
    from worldloom.narrative import UnreachableProvider

    responses = handshake.parse_responses(answer(handshake.requests_document(world)))
    narrated = world.narrate(ResponseProvider(responses, model_id="claude-opus-5"), retries=0)

    class Unreachable(UnreachableProvider):
        id = "claude-opus-5"

    replayed = world.narrate(Unreachable(), ledger=narrated.ledger)
    assert replayed._narration[0] == 0, "a replay must not ask the agent again"
    assert [s.body for ir in replayed.artifact_irs for s in ir.sections] == [
        s.body for ir in narrated.artifact_irs for s in ir.sections
    ]


def test_a_response_provider_names_the_request_it_lacks(world: World) -> None:
    from worldloom.narrative import ProviderError

    with pytest.raises(ProviderError, match="narrate requests"):
        world.narrate(ResponseProvider({}, model_id="agent"), retries=0)


# ---------------------------------------------------------------------------
# The loop, through the CLI
# ---------------------------------------------------------------------------


def _corpus(tmp_path):  # type: ignore[no-untyped-def]
    out = tmp_path / "corpus"
    assert runner.invoke(app, ["build", "--seed", "8128", "--incident", "--out", str(out)]).exit_code == 0
    return out


def test_the_cli_loop_runs_end_to_end(tmp_path) -> None:
    corpus = _corpus(tmp_path)

    requests = tmp_path / "requests.json"
    result = runner.invoke(app, ["narrate", "requests", str(corpus), "-o", str(requests)])
    assert result.exit_code == 0, result.output
    document = json.loads(requests.read_text())
    assert document["requests"]

    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(answer(document)))

    accepted = runner.invoke(app, [
        "narrate", "accept", str(corpus), "--from", str(responses), "--model-id", "claude-opus-5",
    ])
    assert accepted.exit_code == 0, accepted.output
    assert "accepted" in accepted.output

    rendered = runner.invoke(app, ["render", str(corpus), "-f", "markdown", "-f", "xlsx"])
    assert rendered.exit_code == 0, rendered.output
    assert runner.invoke(app, ["validate", str(corpus)]).exit_code == 0

    # The prose is in the rendered documents, with figures substituted.
    body = next(corpus.glob("artifacts/*incident-rca.md")).read_text()
    assert "{{fact:" not in body
    assert "Awaiting narrative" not in body


def test_the_cli_commits_nothing_when_any_response_is_rejected(tmp_path) -> None:
    """A partial commit would leave a corpus half-narrated with no record of which half."""
    corpus = _corpus(tmp_path)
    requests = tmp_path / "requests.json"
    runner.invoke(app, ["narrate", "requests", str(corpus), "-o", str(requests)])
    document = json.loads(requests.read_text())

    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(answer(document, restate=True)))

    result = runner.invoke(app, ["narrate", "accept", str(corpus), "--from", str(bad)])
    assert result.exit_code == 1
    assert "Nothing was committed" in result.output
    assert "bare_number" in result.output
    assert not (corpus / "generation-ledger.jsonl").exists()


def test_the_cli_reports_a_missing_response_file_cleanly(tmp_path) -> None:
    corpus = _corpus(tmp_path)
    result = runner.invoke(app, ["narrate", "accept", str(corpus), "--from", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "error" in result.output


def test_requests_are_empty_once_everything_is_narrated(tmp_path) -> None:
    corpus = _corpus(tmp_path)
    requests = tmp_path / "requests.json"
    runner.invoke(app, ["narrate", "requests", str(corpus), "-o", str(requests)])
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(answer(json.loads(requests.read_text()))))
    runner.invoke(app, ["narrate", "accept", str(corpus), "--from", str(responses)])

    again = runner.invoke(app, ["narrate", "requests", str(corpus)])
    assert again.exit_code == 0
    assert "nothing awaiting prose" in again.output


def test_an_unrendered_artifact_has_no_path_and_that_is_allowed(tmp_path) -> None:
    """A Jira bundle has no file when only Markdown was asked for."""
    corpus = _corpus(tmp_path)
    assert runner.invoke(app, ["render", str(corpus), "-f", "markdown"]).exit_code == 0

    world = World.load(corpus)
    empty = [a for a in world.artifacts if not a.path]
    assert empty, "some artifacts have no Markdown rendering"
    assert world.validate().ok


def test_responses_into_a_fully_narrated_corpus_are_an_error(tmp_path) -> None:
    """Not a corner case — the one that let a CI guardrail go unexercised.

    Submitting responses to a corpus where every section already has prose used
    to print "0 section(s) accepted" and exit zero, which is indistinguishable
    from success to anything reading the exit code. CI's agent-handshake step
    submits *deliberately invalid* prose to prove the guardrail rejects it, and
    had been doing so against an already-narrated corpus: nothing was reviewed,
    and the step passed only because of an unrelated `FileExistsError` further
    down in `export`. Fixing that bug is what revealed it.
    """
    corpus = _corpus(tmp_path)
    requests = tmp_path / "requests.json"
    runner.invoke(app, ["narrate", "requests", str(corpus), "-o", str(requests)])
    responses = tmp_path / "responses.json"
    responses.write_text(json.dumps(answer(json.loads(requests.read_text()))))
    assert runner.invoke(
        app, ["narrate", "accept", str(corpus), "--from", str(responses)]
    ).exit_code == 0

    again = runner.invoke(app, ["narrate", "accept", str(corpus), "--from", str(responses)])
    assert again.exit_code == 2
    assert "no section awaiting prose" in again.output


def test_the_restated_figure_guardrail_fires_on_a_pending_corpus(tmp_path) -> None:
    """The property CI's step is named for, pinned where it cannot decay into
    passing for an unrelated reason: invalid prose submitted while sections are
    genuinely awaiting it must be rejected, by the validator, with the
    violation named."""
    corpus = _corpus(tmp_path)
    requests = tmp_path / "requests.json"
    runner.invoke(app, ["narrate", "requests", str(corpus), "-o", str(requests)])

    document = json.loads(requests.read_text())
    bad = answer(document)
    bad["responses"][0]["text"] += " Revenue finished 2.48% below plan."
    source = tmp_path / "bad.json"
    source.write_text(json.dumps(bad))

    result = runner.invoke(app, ["narrate", "accept", str(corpus), "--from", str(source)])
    assert result.exit_code == 1
    assert "rejected" in result.output


def test_an_in_place_export_of_a_rendered_corpus_survives(tmp_path) -> None:
    """`export` staged the artifacts directory and then copied it again, so
    writing a rendered corpus back over itself raised `FileExistsError` on a
    corpus that was perfectly intact. It never fired because the only in-place
    callers ran before rendering — until one did not."""
    corpus = _corpus(tmp_path)
    assert runner.invoke(app, ["render", str(corpus), "-f", "markdown"]).exit_code == 0

    world = World.load(corpus)
    assert (Path(corpus) / "artifacts").is_dir()
    world.export(corpus, overwrite=True)

    reloaded = World.load(corpus)
    assert reloaded.validate().ok
    assert list((Path(corpus) / "artifacts").iterdir()), "the artifacts must survive"
