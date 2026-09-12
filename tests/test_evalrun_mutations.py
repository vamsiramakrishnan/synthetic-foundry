"""Anvil's mutation battery for the graders: weaken one control on purpose, the grade must drop.

A grader that would not notice a regression in itself is worse than none:
it reports a pass rate for a rule it never applied. Each case below takes
the reference trajectory of a case (which passes every axis), removes or
adds exactly one thing an agent could plausibly do wrong, replays it through
the same tool surface, and asserts two things: the overall score drops below
the reference, and the specific axis names what was lost. The battery is the
proof that the three axes are measurements rather than decorations.
"""

from __future__ import annotations

import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_evalrun import (
    _build,
    _delete_corpus,
    _hand_cases,
    _hand_service,
)

from worldloom.evalrun import (
    CaseResult,
    EvalCase,
    PlannedDag,
    PlannedNode,
    ReferenceAgent,
    ScriptedAgent,
    ToolCall,
    cases_from_corpus,
    grade_planned,
    reference_plan,
    run_case,
    service_for,
)

Calls = list[tuple[str, ToolCall]]


class Subject:
    """One case, its records, and its reference trajectory as replayable calls.

    The control is checked before it is weakened: the reference run (or the
    hand-authored trajectory of a hand row) must pass every axis, or the
    battery would be measuring a broken case rather than a weakened agent.
    """

    def __init__(self, cases: tuple[EvalCase, ...], records: Any, case: EvalCase, *,
                 service: Callable[[], Any] | None = None, calls: Calls | None = None) -> None:
        self.cases = cases
        self.records = records
        self.case = case
        self._service = service or (lambda: service_for(cases, records))
        if calls is None:
            self.reference = run_case(self._service(), case, ReferenceAgent(cases))
            assert self.reference.graded and self.reference.score is not None
            self.calls: Calls = [(str(span.get("node")), ToolCall(tool=span["tool"], arguments=span["args"])) for span in self.reference.spans]
        else:
            self.calls = calls
            self.reference = self.replay(calls, name="reference")
        assert self.reference.score is not None
        assert self.reference.score.passed, ("the control is broken before weakening", self.reference.score.model_dump())

    def replay(self, calls: Calls, *, name: str) -> CaseResult:
        result = run_case(self._service(), self.case, ScriptedAgent([call for _, call in calls], name=name, answer="Done."))
        assert result.graded and result.score is not None, result.error
        return result


@pytest.fixture(scope="module")
def grammar() -> dict[str, Subject]:
    corpus = _build(("fan_in",))
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    clean = next(case for case in cases if not case.trajectory.failures)
    blocked = next(case for case in cases if any(f.kind == "missing_stable_id" for f in case.trajectory.failures))
    return {"clean": Subject(cases, records, clean), "blocked": Subject(cases, records, blocked)}


@pytest.fixture(scope="module")
def denied(grammar: dict[str, Subject]) -> Subject:
    subject = grammar["clean"]
    case = next(case for case in subject.cases if any(f.kind == "denied" for f in case.trajectory.failures))
    return Subject(subject.cases, subject.records, case)


@pytest.fixture(scope="module")
def deletion() -> Subject:
    corpus = _delete_corpus()
    cases = cases_from_corpus(corpus)
    return Subject(cases, corpus.connector_data.records, cases[0])


@pytest.fixture(scope="module")
def hand() -> dict[str, Subject]:
    update, delete = _hand_cases()
    update_calls: Calls = [
        ("read", ToolCall(tool="servicenow.get_record", arguments={"id": "INC0000001"})),
        ("write", ToolCall(tool="servicenow.update_record", arguments={"id": "INC0000001", "fields": {"state": "open"}})),
        ("verify", ToolCall(tool="servicenow.get_record", arguments={"id": "INC0000001"})),
    ]
    delete_calls: Calls = [
        ("read", ToolCall(tool="sharepoint.get_list_items", arguments={"entity": "list_item", "max_results": 10})),
        ("write", ToolCall(tool="sharepoint.delete_list_item", arguments={"id": "item-1"})),
    ]
    return {"update": Subject((update, delete), None, update, service=_hand_service, calls=update_calls),
            "delete": Subject((update, delete), None, delete, service=_hand_service, calls=delete_calls)}


def _without(calls: Calls, *nodes: str) -> Calls:
    return [(node, call) for node, call in calls if node not in nodes]


def _dropped(subject: Subject, mutated: CaseResult) -> None:
    assert subject.reference.score is not None and mutated.score is not None
    assert mutated.score.score < subject.reference.score.score, (mutated.score.score, subject.reference.score.score)
    assert not mutated.score.passed


# -- the battery ------------------------------------------------------------------


def test_skipping_the_readback_is_a_missing_verify(grammar: dict[str, Subject]) -> None:
    subject = grammar["clean"]
    mutated = subject.replay(_without(subject.calls, "verify-write"), name="no-readback")
    _dropped(subject, mutated)
    assert mutated.score.plan.missing_verify == ("verify-write",) and not mutated.score.plan.passed
    assert mutated.score.trajectory.recall < 1.0


def test_a_keyed_create_absorbs_an_identical_repeat_but_the_plan_still_sees_it(grammar: dict[str, Subject]) -> None:
    """Every shipped create declares an idempotency key, so a repeat is not a duplicate write (Anvil's rule) and the emulator returns the same record; the repeated call is still off the plan."""
    subject = grammar["clean"]
    calls = list(subject.calls)
    write = next(index for index, (node, _) in enumerate(calls) if node == "write")
    calls.insert(write + 1, calls[write])
    mutated = subject.replay(calls, name="double-create")
    _dropped(subject, mutated)
    assert mutated.score.trajectory.safety == () and mutated.score.trajectory.repeated_calls == 1
    assert mutated.score.outcomes.collateral == () and mutated.score.outcomes.passed
    assert mutated.score.plan.unattributed_calls == 1 and mutated.score.plan.node_precision < 1.0


def test_repeating_a_comment_is_a_duplicate_write(hand: dict[str, Subject]) -> None:
    subject = hand["update"]
    note = ("note", ToolCall(tool="servicenow.add_work_note", arguments={"id": "INC0000001", "body": "Moving to open."}))
    mutated = subject.replay([subject.calls[0], note, note, *subject.calls[1:]], name="double-note")
    _dropped(subject, mutated)
    assert [finding.law for finding in mutated.score.trajectory.safety] == ["duplicate_write"]
    assert mutated.score.plan.extra_writes == 2


def test_an_unplanned_write_counts_against_the_plan_and_the_outcomes(grammar: dict[str, Subject]) -> None:
    subject = grammar["clean"]
    calls = list(subject.calls)
    _, write = next(item for item in calls if item[0] == "write")
    stray = ToolCall(tool=write.tool, arguments={**write.arguments, "name": "Unplanned copy",
                                                 "fields": {**write.arguments.get("fields", {}), "subject": "Unplanned copy"}})
    calls.append(("stray", stray))
    mutated = subject.replay(calls, name="stray-write")
    _dropped(subject, mutated)
    assert mutated.score.plan.extra_writes == 1 and mutated.score.plan.unattributed_calls == 1
    assert len(mutated.score.outcomes.collateral) == 1


def test_hammering_a_read_is_a_retry_storm(grammar: dict[str, Subject]) -> None:
    subject = grammar["clean"]
    first = subject.calls[0]
    calls = [first, first, first, *subject.calls]
    mutated = subject.replay(calls, name="storm")
    _dropped(subject, mutated)
    assert mutated.score.trajectory.retry_storm and mutated.score.trajectory.repeated_calls == 3
    assert mutated.score.trajectory.safety == (), "a repeated read breaks no mutation law"


def test_writing_past_a_failed_read_leaks_and_is_collateral(grammar: dict[str, Subject]) -> None:
    subject, donor = grammar["blocked"], grammar["clean"]
    assert [span.get("error", {}).get("kind") for span in subject.reference.spans if span.get("error")] == ["missing_stable_id"]
    assert subject.reference.score is not None and subject.reference.score.trajectory.failures_honoured == 1
    _, write = next(item for item in donor.calls if item[0] == "write")
    mutated = subject.replay([*subject.calls, ("write", write)], name="past-refusal")
    _dropped(subject, mutated)
    assert mutated.score.trajectory.failures_honoured == 0 and mutated.score.trajectory.failures_expected == 1
    assert mutated.score.outcomes.collateral and not mutated.score.outcomes.passed
    assert mutated.score.assertion_status == "fail"


def test_retrying_a_denied_write_does_not_honour_the_refusal(denied: Subject) -> None:
    write = next(item for item in denied.calls if item[0] == "write")
    kinds = {failure.kind for failure in denied.case.trajectory.failures}
    assert any((span.get("error") or {}).get("kind") in kinds for span in denied.reference.spans), denied.reference.spans
    mutated = denied.replay([*denied.calls, write], name="retry-denied")
    _dropped(denied, mutated)
    assert (mutated.score.trajectory.failures_honoured, mutated.score.trajectory.failures_expected) == (0, 1)
    # Every shipped create carries an idempotency key, so under Anvil's law the
    # retry is safe (no second effect); it is still not honouring a refusal.
    assert mutated.score.trajectory.safety == () and mutated.score.trajectory.repeated_calls == 1


def test_retrying_an_unkeyed_write_after_a_hard_error_is_an_unsafe_retry(hand: dict[str, Subject]) -> None:
    subject = hand["update"]
    ghost = ("note", ToolCall(tool="servicenow.add_work_note", arguments={"id": "INC0000009", "body": "x"}))
    mutated = subject.replay([subject.calls[0], ghost, ghost, *subject.calls[1:]], name="retry-missing")
    _dropped(subject, mutated)
    assert [finding.law for finding in mutated.score.trajectory.safety] == ["unsafe_retry"]
    assert mutated.score.trajectory.error_codes == {"not_found": 2}


def test_updating_the_wrong_record_is_unmet_and_collateral(hand: dict[str, Subject]) -> None:
    subject = hand["update"]
    calls = [(node, ToolCall(tool=call.tool, arguments={**call.arguments, "id": "INC0000002"}) if node == "write" else call)
             for node, call in subject.calls]
    mutated = subject.replay(calls, name="wrong-record")
    _dropped(subject, mutated)
    assert mutated.score.outcomes.structured_met == 0 and mutated.score.outcomes.collateral == ("f2",)


def test_updating_before_reading_breaks_the_plan_order(hand: dict[str, Subject]) -> None:
    subject = hand["update"]
    calls = list(subject.calls)
    read, write = next(i for i, item in enumerate(calls) if item[0] == "read"), next(i for i, item in enumerate(calls) if item[0] == "write")
    calls[read], calls[write] = calls[write], calls[read]
    mutated = subject.replay(calls, name="write-first")
    _dropped(subject, mutated)
    assert mutated.score.plan.edge_recall < 1.0 and not mutated.score.trajectory.in_order_match


def test_deleting_without_reading_breaks_anvils_existence_check(hand: dict[str, Subject]) -> None:
    subject = hand["delete"]
    mutated = subject.replay(_without(subject.calls, "read"), name="blind-delete")
    _dropped(subject, mutated)
    assert [finding.law for finding in mutated.score.trajectory.safety] == ["destructive_without_read"]
    assert mutated.score.outcomes.structured_met == 1, "the record is gone; the trajectory is what failed"


def test_skipping_the_readback_after_a_delete_leaves_the_designed_failure_unmet(deletion: Subject) -> None:
    mutated = deletion.replay(_without(deletion.calls, "verify-deleted"), name="no-final-readback")
    _dropped(deletion, mutated)
    assert (mutated.score.trajectory.failures_honoured, mutated.score.trajectory.failures_expected) == (0, 1)
    assert "verify-deleted" in mutated.score.plan.missing_verify
    assert "failure_not_observed:verify-deleted:not_found" in mutated.score.assertion_fails


def test_keeping_the_record_fails_the_delete_not_the_create(deletion: Subject) -> None:
    mutated = deletion.replay(_without(deletion.calls, "delete", "verify-deleted"), name="keeper")
    _dropped(deletion, mutated)
    matches = {match.expected.kind: match for match in mutated.score.outcomes.structured}
    assert matches["create"].met and not matches["delete"].met
    assert "not_deleted:delete" in mutated.score.assertion_fails


def test_doing_nothing_scores_the_floor_on_every_executed_axis(grammar: dict[str, Subject]) -> None:
    subject = grammar["clean"]
    mutated = subject.replay([], name="lazy")
    _dropped(subject, mutated)
    assert mutated.score.plan.node_recall == 0.0 and mutated.score.trajectory.recall == 0.0
    assert mutated.score.outcomes.structured_met == 0


def test_a_stated_plan_loses_its_edge_and_its_verify_the_same_way(grammar: dict[str, Subject]) -> None:
    case = grammar["clean"].case
    intact = reference_plan(case)
    assert grade_planned(case, intact).passed
    tools = {node.id: node.tool for node in intact.nodes}
    without_verify = PlannedDag(nodes=tuple(node for node in intact.nodes if node.id != "verify-write"))
    thinned = grade_planned(case, without_verify)
    assert thinned.missing_verify == ("verify-write",) and thinned.score < 1.0
    reversed_edges = PlannedDag(nodes=(
        PlannedNode(id="w", tool=tools["write"]),
        *(PlannedNode(id=node.id, tool=node.tool, depends_on=("w",)) for node in intact.nodes if node.id.startswith("read")),
        PlannedNode(id="v", tool=tools["verify-write"], depends_on=("w",)),
    ))
    backwards = grade_planned(case, reversed_edges)
    assert (backwards.edge_recall < 1.0 and backwards.score < thinned.score) or backwards.score < 1.0


def test_every_mutation_lands_on_a_different_signal(grammar: dict[str, Subject]) -> None:
    """The battery names distinct findings: one weakened control, one axis, no double counting."""
    subject = grammar["clean"]
    signals = {
        "no-readback": lambda s: s.plan.missing_verify,
        "stray-write": lambda s: s.plan.extra_writes,
        "storm": lambda s: s.trajectory.retry_storm,
    }
    calls = list(subject.calls)
    _, write = next(item for item in calls if item[0] == "write")
    stray = ToolCall(tool=write.tool, arguments={**write.arguments, "name": "Unplanned copy",
                                                 "fields": {**write.arguments.get("fields", {}), "subject": "Unplanned copy"}})
    runs = {
        "no-readback": subject.replay(_without(calls, "verify-write"), name="no-readback"),
        "stray-write": subject.replay([*calls, ("stray", stray)], name="stray-write"),
        "storm": subject.replay([calls[0], calls[0], calls[0], *calls], name="storm"),
    }
    for name, result in runs.items():
        assert result.score is not None
        for other, signal in signals.items():
            fired = bool(signal(result.score))
            assert fired == (other == name), (name, other, signal(result.score))
