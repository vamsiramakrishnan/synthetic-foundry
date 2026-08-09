"""Who signed it — and the three ways a synthetic signature goes wrong.

Every document in this corpus was authored and none of them was approved,
which is not how a company works and, more to the point, is not how a
company's *archive* works. "Who approved the March pack for Fuel and
Convenience" is a question every real reader asks, and until
``ArtifactIntent.approver_id`` existed no artifact here could answer it.

Five properties, and they are the contract. That a signature is **real** — the
approver exists, is not the author, and could open what they signed. That
absence is a **claim** rather than an omission. That the approval **fans out**
with the company, because a division's own managing director signs it. That
access **follows the post** when a unit changes hands, which is where the
validator found the first defect the day it existed. And that the corpus
**asks about it**, because a document property nobody asks about is
decoration.
"""

from __future__ import annotations

import pytest

from worldloom import RetailWorld, archetypes
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import MonthEndClose, Reorganisation

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def closed() -> object:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    ).compile()


# ---------------------------------------------------------------------------
# 1. A signature is one somebody could have given
# ---------------------------------------------------------------------------


def test_nobody_approves_their_own_document(closed) -> None:  # type: ignore[no-untyped-def]
    """A byline printed twice is not a review.

    Dropped at the source by `documents.approver_of` — banking's
    `internal_audit_review` names `audit`, who wrote it, precisely so that the
    row reads as an argument about independence rather than as an omission —
    and failed here for anything that gets past it.
    """
    for intent in closed.artifact_intents:
        assert intent.approver_id != intent.author_id, intent.id


def test_an_approver_can_open_what_they_signed(closed) -> None:  # type: ignore[no-untyped-def]
    """The check that found the first real defect the day approvals existed.

    A division's close commentary is signed by its managing director, who sits
    in Executive, while the policy on it says "Finance and audit only" — so
    eight people were signing documents the corpus also said they could not
    read. `organisation.generate` now names the divisional MDs on that policy,
    for the reason the chief executive was already named on it.
    """
    report = closed.validate()
    signature_faults = [
        v for v in report.violations
        if v.code in {
            "approver_cannot_see_what_they_signed",
            "approver_is_the_author",
            "approver_not_employed",
        }
    ]
    assert not signature_faults, signature_faults


def test_the_validator_catches_a_signature_nobody_could_have_given(closed) -> None:  # type: ignore[no-untyped-def]
    """The check has to be able to fail, or passing it means nothing.

    Forged by hand rather than by finding a build that produces one: the
    planner is what stops these reaching a corpus, so the only way to exercise
    the validator is to write the state the planner refuses to.
    """
    from dataclasses import replace

    broken = replace(closed, _artifacts=tuple(
        artifact.model_copy(update={"approver_id": artifact.author_id})
        if artifact.approver_id else artifact
        for artifact in closed.artifacts
    ))
    codes = {v.code for v in broken.validate().violations}
    assert "approver_is_the_author" in codes


# ---------------------------------------------------------------------------
# 2. Absence is a claim
# ---------------------------------------------------------------------------


def test_most_documents_carry_no_signature_and_that_is_the_point(closed) -> None:  # type: ignore[no-untyped-def]
    """A corpus where everything is signed is as unlike a real archive as one
    where nothing is.

    A ServiceNow ticket has an assignee, an email thread has a sender, a
    republished calendar is issued rather than approved, a working note is
    nobody's but its writer's. Those types are missing from
    `planning._APPROVED_BY` deliberately.
    """
    signed = {i.artifact_type for i in closed.artifact_intents if i.approver_id}
    unsigned = {i.artifact_type for i in closed.artifact_intents if not i.approver_id}
    assert signed and unsigned, "both halves must exist for the distinction to mean anything"
    assert {"close_calendar", "servicenow_incident", "email_thread"} <= unsigned
    assert {"finance_workbook", "cfo_variance_memo", "unit_close_commentary"} <= signed


def test_an_unsigned_document_renders_exactly_as_it_always_did(closed) -> None:  # type: ignore[no-untyped-def]
    """`_signoff` returns `None` when nobody signed, so the section is absent
    rather than empty — which is what makes every corpus built before this
    existed byte-identical after it."""
    by_id = {ir.intent_id: ir for ir in closed._artifact_irs}
    for intent in closed.artifact_intents:
        headings = [s.heading for s in by_id[intent.id].sections]
        assert ("Approval" in headings) == bool(intent.approver_id), intent.artifact_type


# ---------------------------------------------------------------------------
# 3. It fans out with the company
# ---------------------------------------------------------------------------


def test_each_division_is_signed_by_its_own_managing_director() -> None:
    """The one approval in the corpus that scales with the archetype.

    Widen a retailer to eight divisions and eight *different* people sign eight
    different documents — which is the whole reason `documents.approver_of`
    takes a per-document override rather than reading the type table alone.
    """
    world = RetailWorld(
        seed=8128, archetype=archetypes.get("omnichannel_retailer+8div"),
    ).build().run(MonthEndClose(period=PERIOD)).compile()

    commentary = [
        i for i in world.artifact_intents if i.artifact_type == "unit_close_commentary"
    ]
    assert len(commentary) == 8
    signers = {i.approver_id for i in commentary}
    assert len(signers) == 8, "one signature per division, not one signature for all of them"
    for person_id in signers:
        assert world.people.by_id(person_id).title.startswith("Managing Director")


# ---------------------------------------------------------------------------
# 4. Access follows the post
# ---------------------------------------------------------------------------


def test_a_unit_changing_hands_carries_its_access_with_it() -> None:
    """A handover that moved the title without moving the access left the
    corpus recording a signature from somebody it also recorded as unable to
    open the document.

    Added and never substituted — see `personnel._access_follows_the_post`. The
    outgoing leader stays named, because the archive is historical and the
    policy is current state: striking a name off today would retroactively
    invalidate every signature that person ever gave, which is the same
    violation arriving from the other direction.
    """
    world = RetailWorld(seed=2).build().run(MonthEndClose(period=PERIOD))
    before = {p.id: list(p.allow_people) for p in world._access_policies}
    outgoing = world._roles["gm_md"]

    world = world.run(Reorganisation(
        period="2026-04", unit_key="gm", new_leader_role="gm_buyer",
    )).run(MonthEndClose(period="2026-04")).compile()

    incoming = world._roles["gm_md"]
    assert incoming != outgoing, "the case is only interesting if the post moved"

    finance = next(p for p in world._access_policies if p.label == "Finance and audit only")
    assert incoming in finance.allow_people, "the new leader can open what they now sign"
    assert outgoing in finance.allow_people, "and the old one's earlier signatures stand"
    assert set(before["POLICY-0002"]) <= set(finance.allow_people)

    report = world.validate()
    assert report.ok, report.violations[:3]


def test_a_signed_corpus_still_replays_byte_identically() -> None:
    """The gate everything in this repository is held to.

    An approval is resolved from the role table at plan time and dated from the
    facts the document already cites — no clock, no draw — so a corpus that
    carries signatures rebuilds itself with the same ones.
    """
    from worldloom.recipe import rebuild

    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    again = rebuild(world._recipe)
    assert [i.model_dump() for i in again.artifact_intents] == [
        i.model_dump() for i in world.artifact_intents
    ]

    rendered = world.compile().narrate(DeterministicProvider()).render("markdown")
    replayed = again.compile().narrate(DeterministicProvider()).render("markdown")
    assert [ir.model_dump() for ir in replayed._artifact_irs] == [
        ir.model_dump() for ir in rendered._artifact_irs
    ]


# ---------------------------------------------------------------------------
# 5. And the corpus asks about it
# ---------------------------------------------------------------------------


def test_the_signature_block_is_something_the_corpus_asks_about(closed) -> None:  # type: ignore[no-untyped-def]
    """A document property nobody asks about is decoration.

    Three authority questions and one abstention. The authority family scored
    0/3 against a keyword baseline before and 0/6 after, which is the intended
    result rather than a disappointing one — a baseline that could tell an
    author from an approver would mean the two were not distinguishable in the
    first place.
    """
    from worldloom.models import EvaluationType

    questions = {case.question: case for case in closed.evaluations}
    approval = [q for q in questions if "approved" in q or "prepared by" in q]
    assert len(approval) >= 3, approval

    answered = [questions[q] for q in approval if not questions[q].expects_abstention]
    assert answered, "at least one has an answer, or the family is only abstentions"
    for case in answered:
        assert case.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
        assert case.expected_answer, case.question


def test_a_document_nobody_signed_stays_unsigned(closed) -> None:  # type: ignore[no-untyped-def]
    """The only test this corpus has that a system will not invent a signature.

    Absence is a claim (`planning._APPROVED_BY`) and a claim is worth nothing
    if nothing checks it: asking who approved a close calendar has to come back
    as an abstention, because the corpus records who issued it and nobody else.
    """
    abstentions = [
        case for case in closed.evaluations
        if case.expects_abstention and "approved" in case.question
    ]
    assert abstentions, "no case asks after an approval that does not exist"
    unsigned = {i.artifact_type.replace("_", " ") for i in closed.artifact_intents
                if not i.approver_id}
    assert any(
        any(kind in case.question for kind in unsigned) for case in abstentions
    ), "the abstention must name a type this corpus really does leave unsigned"


def test_the_answer_to_who_approved_is_never_the_author(closed) -> None:  # type: ignore[no-untyped-def]
    """The byline is the trap, so it must not also be the answer.

    A document names its author at the top in larger type and its approver in a
    table at the foot. A case whose expected answer happened to be the author's
    name would reward exactly the shortcut it exists to catch.
    """
    names = {p.id: p.name for p in closed.people}
    by_id = {i.id: i for i in closed.artifact_intents}
    for case in closed.evaluations:
        if "Who approved" not in case.question or case.expects_abstention:
            continue
        for artifact_id in case.required_artifact_ids:
            intent = by_id.get(artifact_id)
            if intent is not None:
                assert case.expected_answer != names[intent.author_id], case.question
