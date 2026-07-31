"""The planning handshake — the second handshake, one layer above prose.

Same discipline as ``tests/test_handshake.py``, its direct sibling: the contract
under test is a pair of JSON documents, not a function signature. A request must
be answerable without reading this repository, and a rejection must name the
rule and the offending beat clearly enough to fix in one round trip.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.compiler import handshake
from worldloom.compiler.grammar import GRAMMARS

runner = CliRunner()
PERIOD = "2026-03"


@pytest.fixture(scope="module")
def world() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()


def _grammatical_order(constraints: dict) -> list[str]:
    """A role order that satisfies one request's ``constraints`` — the same
    ordering and opening rules a real agent would read in plain English, worked
    out here from the structured fields the request carries alongside the
    prose."""
    roles = set(constraints["requires_roles"]) | set(constraints["opens_with"])
    if not roles:
        return ["evidence"]
    order = list(roles)
    changed = True
    while changed:
        changed = False
        for earlier, later in constraints["ordered_roles"]:
            if earlier in order and later in order and order.index(earlier) > order.index(later):
                order.remove(earlier)
                order.insert(order.index(later), earlier)
                changed = True
    if constraints["opens_with"]:
        opener = sorted(constraints["opens_with"])[0]
        if opener in order:
            order.remove(opener)
            order.insert(0, opener)
    return order


def _compliant_plan(request: dict) -> dict:
    """The plan a compliant agent would submit for one request."""
    roles = _grammatical_order(request["constraints"])
    required = request["required_fact_ids"] or [f["id"] for f in request["available_facts"][:1]]
    beats = []
    for index, role in enumerate(roles):
        beats.append(
            {
                "heading": f"{role.title()} for {request['artifact_id']}"[: handshake.HEADING_MAX_CHARS],
                "purpose": f"cover the {role} for this audience",
                "semantic_role": role,
                "optional": False,
                "evidence": [{"fact_id": fid} for fid in required] if index == 0 else [],
            }
        )
    return {"id": request["id"], "intent": "test intent", "beats": beats}


def answer(document: dict) -> dict:
    """Answer every request the way a compliant agent would."""
    return {"plans": [_compliant_plan(request) for request in document["requests"]]}


# ---------------------------------------------------------------------------
# 1. The request is self-describing
# ---------------------------------------------------------------------------


def test_a_request_carries_everything_needed_to_answer_it(world: World) -> None:
    document = handshake.requests_document(world)
    assert document["requests"]
    assert document["rules"], "the contract must travel with the request"
    assert "plans" in document["response_shape"]

    # One plan request per narrative artifact.
    assert len(document["requests"]) == len(
        [ir for ir in world.artifact_irs if ir.fact_ids()]
    )

    for request in document["requests"]:
        assert request["id"] == f"{request['artifact_id']}/plan"
        assert request["written_by"] and request["voice"] and request["audience"]
        assert request["available_facts"], "a request with no facts should not be asked"
        for fact in request["available_facts"]:
            assert fact["id"] and fact["subject"] and fact["statement"]
        assert request["vocabulary"], "an agent needs the vocabulary to name a semantic_role at all"
        for entry in request["vocabulary"]:
            assert entry["role"] and entry["purpose"]
        assert "prose" in request["constraints"]
        assert isinstance(request["recent_headings"], list)


def test_constraints_describe_the_actual_grammar(world: World) -> None:
    """Assert against `GRAMMARS` itself, not a hard-coded string — the request
    must track the grammar, not merely resemble it today."""
    document = handshake.requests_document(world)
    exercised: set[str] = set()

    for request in document["requests"]:
        grammar = GRAMMARS.get(request["artifact_type"])
        constraints = request["constraints"]
        if grammar is None:
            assert constraints["requires_roles"] == []
            assert constraints["opens_with"] == []
            assert constraints["ordered_roles"] == []
            continue

        exercised.add(request["artifact_type"])
        assert constraints["opens_with"] == sorted(grammar.opens_with)
        assert constraints["requires_roles"] == sorted(grammar.requires_roles)
        assert constraints["forbids_roles"] == sorted(grammar.forbids_roles)
        assert constraints["ordered_roles"] == [list(pair) for pair in grammar.ordered_roles]
        assert constraints["min_components"] == grammar.min_components
        assert constraints["max_components"] == grammar.max_components
        for earlier, later in grammar.ordered_roles:
            assert f"{earlier!r} must appear before {later!r}" in constraints["prose"]
        for role in grammar.opens_with:
            assert repr(role) in constraints["prose"]

    assert exercised, "the fixture world should exercise at least one grammared artifact type"


def test_recent_headings_reflect_only_this_authors_other_documents(world: World) -> None:
    by_author: dict[str, list] = {}
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        by_author.setdefault(intent.author_id, []).append(ir)
    multi_author = next(author for author, irs in by_author.items() if len(irs) > 1)
    irs = by_author[multi_author]
    target = irs[0]

    reqs = handshake.requests(world)
    request = next(r for r in reqs if r.artifact_id == target.intent_id)

    other_headings = {
        section.heading
        for ir in irs
        if ir.id != target.id
        for section in ir.sections
        if section.heading
    }
    assert other_headings, "fixture should give this author headings on another document"
    assert set(request.recent_headings) <= other_headings

    # Scoped to this author: a heading unique to a different author's artifact
    # must not leak in.
    other_author_ir = next(ir for ir in world.artifact_irs if ir.intent_id not in {i.id for i in irs})
    other_author_only = {
        section.heading for section in other_author_ir.sections if section.heading
    } - other_headings
    assert not (other_author_only & set(request.recent_headings))


def test_requests_are_deterministic(world: World) -> None:
    assert handshake.requests(world) == handshake.requests(world)
    assert handshake.requests_document(world) == handshake.requests_document(world)


# ---------------------------------------------------------------------------
# 2. Acceptance
# ---------------------------------------------------------------------------


def test_a_compliant_plan_set_is_accepted_and_yields_usable_plans(world: World) -> None:
    document = handshake.requests_document(world)
    responses = handshake.parse_responses(answer(document))

    result = handshake.accept(world, responses, model_id="claude-opus-5")
    assert result.accepted, {
        request_id: verdict.feedback for request_id, verdict in result.verdicts.items() if not verdict.accepted
    }
    assert len(result.plans) == len(document["requests"])
    assert len(result.ledger) == len(document["requests"])
    for entry in result.ledger:
        assert entry.model_id == "claude-opus-5"
        assert entry.prompt_version == handshake.PLAN_PROMPT_KEY
        assert entry.call_site.endswith("/plan")
    for plan in result.plans:
        assert plan.beats, "an accepted plan must actually carry a shape"


# ---------------------------------------------------------------------------
# 3. Every rejection code fires, and the fixed version clears
# ---------------------------------------------------------------------------


def test_every_rejection_code_fires(world: World) -> None:
    document = handshake.requests_document(world)
    request = next(r for r in document["requests"] if r["artifact_type"] == "cfo_variance_memo")

    bad_plan = {
        "id": request["id"],
        "intent": "x",
        "beats": [
            {
                "heading": "",
                "purpose": "",
                "semantic_role": "not-a-real-role",
                "optional": True,
                "evidence": [{"fact_id": "FACT-9999"}],
            },
            {
                "heading": "Repeated",
                "purpose": "p",
                "semantic_role": "position",
                "optional": True,
                "evidence": [],
            },
            {
                "heading": "Repeated",
                "purpose": "p",
                "semantic_role": "position",
                "optional": True,
                "evidence": [],
            },
            {
                "heading": "x" * (handshake.HEADING_MAX_CHARS + 1),
                "purpose": "p",
                "semantic_role": "position",
                "optional": True,
                "evidence": [],
            },
        ],
    }
    result = handshake.accept(world, handshake.parse_responses({"plans": [bad_plan]}), model_id="agent")
    assert not result.accepted
    verdict = result.verdicts[request["id"]]
    codes = {v.code for v in verdict.violations}
    assert codes == {
        "unknown_role",
        "unknown_fact",
        "required_fact_omitted",
        "duplicate_heading",
        "empty_heading",
        "empty_purpose",
        "heading_too_long",
        "all_optional",
    }
    assert result.plans == ()
    assert result.ledger == ()


def test_ungrammatical_sequences_are_rejected_with_the_grammars_own_text(world: World) -> None:
    document = handshake.requests_document(world)
    request = next(r for r in document["requests"] if r["artifact_type"] == "cfo_variance_memo")

    # `evidence` before `position`: cfo_variance_memo must open with position or
    # summary, so this is out of order at the very first beat.
    plan = {
        "id": request["id"],
        "intent": "x",
        "beats": [
            {
                "heading": "Evidence first",
                "purpose": "p",
                "semantic_role": "evidence",
                "optional": False,
                "evidence": [{"fact_id": fid} for fid in request["required_fact_ids"]],
            },
            {
                "heading": "Position second",
                "purpose": "p",
                "semantic_role": "position",
                "optional": False,
                "evidence": [],
            },
        ],
    }
    result = handshake.accept(world, handshake.parse_responses({"plans": [plan]}), model_id="agent")
    verdict = result.verdicts[request["id"]]
    assert not verdict.accepted
    ungrammatical = [v for v in verdict.violations if v.code == "ungrammatical"]
    assert ungrammatical
    assert "wrong_opening" in ungrammatical[0].detail


def test_the_fixed_version_of_a_rejected_plan_clears(world: World) -> None:
    document = handshake.requests_document(world)
    request = next(r for r in document["requests"] if r["artifact_type"] == "cfo_variance_memo")

    fixed = _compliant_plan(request)
    result = handshake.accept(world, handshake.parse_responses({"plans": [fixed]}), model_id="agent")
    verdict = result.verdicts[request["id"]]
    assert verdict.accepted, verdict.feedback


# ---------------------------------------------------------------------------
# 4. A rejection commits nothing
# ---------------------------------------------------------------------------


def test_a_rejection_commits_nothing(world: World) -> None:
    document = handshake.requests_document(world)
    payload = answer(document)
    # Break exactly one plan; the rest stay individually compliant.
    payload["plans"][0]["beats"] = []
    broken_id = payload["plans"][0]["id"]

    result = handshake.accept(world, handshake.parse_responses(payload), model_id="agent")
    assert not result.accepted
    assert result.plans == ()
    assert result.ledger == ()
    assert not result.verdicts[broken_id].accepted
    # Every other response validated cleanly on its own — the whole set was
    # rejected on account of one, not repaired around it.
    still_fine = [rid for rid, v in result.verdicts.items() if rid != broken_id]
    assert still_fine and all(result.verdicts[rid].accepted for rid in still_fine)


# ---------------------------------------------------------------------------
# 5. Idempotency and provider-free replay
# ---------------------------------------------------------------------------


def test_accepting_the_same_responses_twice_is_idempotent(world: World) -> None:
    document = handshake.requests_document(world)
    responses = handshake.parse_responses(answer(document))

    first = handshake.accept(world, responses, model_id="agent")
    assert first.accepted
    extended = world.extend(ledger=first.ledger)

    second = handshake.accept(extended, responses, model_id="agent")
    assert second.accepted
    assert second.ledger == (), "nothing new should be minted the second time"
    assert [p.model_dump(mode="json") for p in second.plans] == [
        p.model_dump(mode="json") for p in first.plans
    ]


def test_a_replay_from_the_ledger_needs_no_provider(world: World) -> None:
    """The planning equivalent of `world.narrate(UnreachableProvider(), ...)`:
    once every plan is already recorded, acceptance succeeds with no responses
    supplied at all."""
    document = handshake.requests_document(world)
    responses = handshake.parse_responses(answer(document))
    first = handshake.accept(world, responses, model_id="agent")
    extended = world.extend(ledger=first.ledger)

    replayed = handshake.accept(extended, {}, model_id="agent")
    assert replayed.accepted
    assert replayed.ledger == ()
    assert len(replayed.plans) == len(document["requests"])


def test_a_missing_response_is_named_rather_than_ignored(world: World) -> None:
    document = handshake.requests_document(world)
    payload = answer(document)
    payload["plans"] = payload["plans"][:2]

    result = handshake.accept(world, handshake.parse_responses(payload), model_id="agent")
    missing = [
        rid
        for rid, v in result.verdicts.items()
        if any(x.code == "missing_response" for x in v.violations)
    ]
    assert len(missing) == len(document["requests"]) - 2


def test_a_malformed_response_document_says_what_is_wrong() -> None:
    with pytest.raises(ValueError, match="plans"):
        handshake.parse_responses({"answers": []})
    with pytest.raises(ValueError, match="no 'id'"):
        handshake.parse_responses({"plans": [{"beats": []}]})


# ---------------------------------------------------------------------------
# The loop, through the CLI
# ---------------------------------------------------------------------------


def _corpus(tmp_path):  # type: ignore[no-untyped-def]
    out = tmp_path / "corpus"
    assert runner.invoke(app, ["build", "--seed", "8128", "--incident", "--out", str(out)]).exit_code == 0
    return out


def test_the_plan_cli_loop_runs_end_to_end(tmp_path) -> None:
    corpus = _corpus(tmp_path)

    requests_path = tmp_path / "plan_requests.json"
    result = runner.invoke(app, ["plan", "requests", str(corpus), "-o", str(requests_path)])
    assert result.exit_code == 0, result.output
    document = json.loads(requests_path.read_text())
    assert document["requests"]

    responses_path = tmp_path / "plan_responses.json"
    responses_path.write_text(json.dumps(answer(document)))

    accepted = runner.invoke(
        app,
        ["plan", "accept", str(corpus), "--from", str(responses_path), "--model-id", "claude-opus-5"],
    )
    assert accepted.exit_code == 0, accepted.output
    assert "accepted" in accepted.output

    world = World.load(corpus)
    assert len(world.ledger) == len(document["requests"])
    assert {entry.call_site for entry in world.ledger} == {r["id"] for r in document["requests"]}
    assert {entry.model_id for entry in world.ledger} == {"claude-opus-5"}
    # Nothing wired into the outline yet — that integration is deliberately not
    # this handshake's job. The compiled sections are untouched.
    assert world.validate().ok


def test_the_plan_cli_commits_nothing_when_any_response_is_rejected(tmp_path) -> None:
    corpus = _corpus(tmp_path)

    bad_payload = {"plans": [{"id": "ART-9999/plan", "beats": []}]}
    bad_path = tmp_path / "bad_plans.json"
    bad_path.write_text(json.dumps(bad_payload))

    result = runner.invoke(app, ["plan", "accept", str(corpus), "--from", str(bad_path)])
    assert result.exit_code == 1
    assert "Nothing was committed" in result.output
    assert "missing_response" in result.output

    world = World.load(corpus)
    assert len(world.ledger) == 0


def test_the_plan_cli_reports_a_missing_response_file_cleanly(tmp_path) -> None:
    corpus = _corpus(tmp_path)
    result = runner.invoke(app, ["plan", "accept", str(corpus), "--from", str(tmp_path / "nope.json")])
    assert result.exit_code == 2
    assert "error" in result.output


def test_the_plan_cli_is_idempotent(tmp_path) -> None:
    corpus = _corpus(tmp_path)
    requests_path = tmp_path / "plan_requests.json"
    runner.invoke(app, ["plan", "requests", str(corpus), "-o", str(requests_path)])
    document = json.loads(requests_path.read_text())

    responses_path = tmp_path / "plan_responses.json"
    responses_path.write_text(json.dumps(answer(document)))

    first = runner.invoke(app, ["plan", "accept", str(corpus), "--from", str(responses_path)])
    assert first.exit_code == 0, first.output
    ledger_after_first = len(World.load(corpus).ledger)

    second = runner.invoke(app, ["plan", "accept", str(corpus), "--from", str(responses_path)])
    assert second.exit_code == 0, second.output
    assert len(World.load(corpus).ledger) == ledger_after_first
