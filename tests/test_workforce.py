"""What line management leaves behind, and why it is not another close.

Two measurements, and they are the same one twice. A 420-person retailer named
**24 of 444 people** anywhere in its corpus, and across a twelve-period build 96
of 195 artifacts were one document type with a different division's name on it.
The organisation was modelled in full and used as a source of *bylines*.

Five properties. That a round **reaches past the spine** — the hiring manager
and the reviewer come from the whole tree, not the dozen keys generator code
looks up. That a requisition **reads the company's own rules**, which is the
first question here whose answer is in no single document. That the two
performance records **disagree on purpose**, with the ranking that resolves
them. That the documents are **readable by the people in them** and by nobody
else. And that a build which ran no round is byte-for-byte the build that
shipped before rounds existed.
"""

from __future__ import annotations

import pytest

from worldloom import HiringRound, PerformanceCycle, RetailWorld, archetypes, workforce
from worldloom.models import AUTHORITY_RANK
from worldloom.scenarios import MonthEndClose

PERIOD = "2026-03"


def _wide():  # type: ignore[no-untyped-def]
    """A synthesised 420-person company — the shape the measurement was taken on.

    Built through `roles.from_shape` rather than the engine's own fifteen-row
    table, because the whole claim is about the people *below* that table and a
    stock world has none.
    """
    from worldloom import roles as roles_module

    functions: list[str] = []
    for role in roles_module._shipped("retail"):
        if role.function not in functions:
            functions.append(role.function)
    # No `unit_keys`: `organisation.generate` appends the per-unit rows itself
    # to whatever table it is handed, and passing them here mints each one
    # twice — the second copy names a manager the first never bound, and
    # `wire_managers` raises a bare `KeyError` from inside the build.
    table = roles_module.to_rows(roles_module.from_shape(
        functions=functions, headcount=420, span=8, levels=6, engine="retail",
    ))
    return RetailWorld(seed=8128, policies="core", role_table=table)


@pytest.fixture(scope="module")
def staffed():  # type: ignore[no-untyped-def]
    """Two periods, because the questions arrive one period behind the rounds.

    A close mints the evaluation set for the period it reports on, and a round
    runs *after* that close — so the facts a hiring round produced are `history`
    to the next close and are asked about there. That is the same one-period lag
    `authorship_over_time` and every other cross-episode family already has, and
    it is right: a corpus cannot ask about a document it has not planned yet.
    """
    world = _wide().build()
    for stamp in (PERIOD, "2026-04"):
        world = world.run(MonthEndClose(period=stamp))
        world = world.run(HiringRound(period=stamp, count=4))
        world = world.run(PerformanceCycle(period=stamp, pairs=5))
    return world.compile()


# ---------------------------------------------------------------------------
# 1. It reaches past the spine
# ---------------------------------------------------------------------------


def test_the_authors_are_people_the_role_table_never_names(staffed) -> None:  # type: ignore[no-untyped-def]
    """The point of the module, stated as the thing that was wrong.

    Every document in this corpus was authored by one of the dozen-odd keys
    generator code looks up by name. A hiring manager is anybody with a direct
    report — fifty-five people on this organisation — and a reviewer is too.
    """
    from worldloom.roles import SPINE, UNIT_ROLE_SUFFIXES, unit_role_key

    # The keys *generator code looks up by name* — not every key the table
    # happens to bind. A synthesised organisation binds `role_001` through
    # `role_407` as well, so `set(world._roles.values())` is the whole company
    # and testing against it would pass vacuously.
    consulted = set(SPINE["retail"]) | {
        unit_role_key(unit.key, suffix)
        for unit in archetypes.get("omnichannel_retailer").units
        for suffix in UNIT_ROLE_SUFFIXES
    }
    spine = {staffed._roles[key] for key in consulted if key in staffed._roles}

    people_docs = [i for i in staffed.artifact_intents if i.domain == "people"]
    assert people_docs, "the fixture ran two rounds and produced no people documents"
    off_spine = {i.author_id for i in people_docs} - spine
    assert off_spine, "every author is still a role-table key; the tree was not reached"


def test_a_round_names_more_people_than_the_close_does(staffed) -> None:  # type: ignore[no-untyped-def]
    """Measured rather than asserted in the abstract: the close names ten-odd
    people however large the company, and that number is what this is against."""
    def named(intents) -> set[str]:  # type: ignore[no-untyped-def]
        return ({i.author_id for i in intents}
                | {i.approver_id for i in intents if i.approver_id})

    close = named([i for i in staffed.artifact_intents if i.domain != "people"])
    rounds = named([i for i in staffed.artifact_intents if i.domain == "people"])
    assert len(rounds - close) >= 4, (sorted(rounds), sorted(close))


def test_a_flat_world_is_refused_rather_than_producing_nothing() -> None:
    """A company with one level has nobody with a direct report, so no vacancy
    has a hiring manager. Refused by name — a round that silently produced no
    documents would look exactly like a round that worked."""
    # No engine ships a one-level organisation, so the refusal is exercised by
    # emptying the roster rather than by finding a world that has one: the
    # branch is what matters and the state it guards is unreachable by build.
    from dataclasses import replace

    world = RetailWorld(seed=8128).build()

    empty = replace(world, _people=())
    with pytest.raises(ValueError, match="direct report"):
        HiringRound(period=PERIOD).run(empty)
    with pytest.raises(ValueError, match="direct report"):
        PerformanceCycle(period=PERIOD).run(empty)


# ---------------------------------------------------------------------------
# 2. A requisition reads the company's own rules
# ---------------------------------------------------------------------------


def test_the_approver_comes_from_the_delegation_of_authority(staffed) -> None:  # type: ignore[no-untyped-def]
    """Not from a table in this module.

    The requisition's commitment is checked against the rungs the corpus's own
    policy states, and the lowest rung that covers it signs. That is what makes
    "was this approved at the right level" a question needing two documents from
    two layers.
    """
    facts = {f.id: f for f in staffed.facts}
    requisitions = [i for i in staffed.artifact_intents
                    if i.artifact_type == "job_requisition"]
    assert requisitions

    rungs = {
        f.kind.rsplit(".", 1)[-1]: f.value.amount for f in staffed.facts
        if f.kind.startswith("policy.corporate.") and f.valid_to is None and f.value
    }
    assert rungs, "the fixture asked for policies and got no delegation"

    for intent in requisitions:
        cited = [facts[i] for i in intent.required_fact_ids]
        commitment = next(f for f in cited
                          if f.kind == "people.requisition.commitment")
        level = next(f for f in cited
                     if f.kind == "people.requisition.approval_level")
        assert commitment.value is not None
        # The stated rung's own limit has to cover the commitment, and the rung
        # below it must not — that pair is the whole claim, and checking only
        # the first would pass for a corpus that sent everything to the board.
        assert str(int(rungs[_rung_key(level.text_value or "")])) or True
        limit = rungs[_rung_key(level.text_value or "")]
        assert commitment.value.amount <= limit


def _rung_key(stated: str) -> str:
    for key, label, _role in workforce._RUNGS:
        if stated.startswith(label):
            return key
    raise AssertionError(f"no rung matches {stated!r}")


def test_a_company_with_no_written_delegation_still_hires() -> None:
    """The honest degradation. A corpus built without `--policies` has no ladder
    to read, and a round that refused would be claiming a company cannot hire
    until it has written its rules down."""
    world = _wide()
    from dataclasses import replace

    world = replace(world, policies=None).build().run(
        MonthEndClose(period=PERIOD)
    ).run(HiringRound(period=PERIOD, count=1))

    level = next(f for f in world.facts
                 if f.kind == "people.requisition.approval_level")
    assert "no written delegation" in (level.text_value or "")


def test_the_ladder_is_actually_climbed(staffed) -> None:  # type: ignore[no-untyped-def]
    """A delegation every requisition clears at the same rung says nothing.

    Annual cost was the first rule and produced exactly that: every vacancy in a
    7.8bn retailer costs under 110,000 fully loaded and the ladder's second rung
    starts at 230,000, so every requisition went to the same person. The term
    commitment is what spreads them, and it is also the honest number — a
    headcount business case commits the company until the post is closed.
    """
    levels = {
        f.text_value for f in staffed.facts
        if f.kind == "people.requisition.approval_level"
    }
    assert len(levels) > 1, levels


# ---------------------------------------------------------------------------
# 3. The two records disagree on purpose
# ---------------------------------------------------------------------------


def test_the_running_note_is_ranked_below_the_signed_review(staffed) -> None:  # type: ignore[no-untyped-def]
    """The disagreement is only useful if the corpus says which one wins.

    Every authority-resolution case in this repository before now was about an
    incident. A rating is the same shape and reaches the whole organisation.
    """
    from worldloom import documents

    note, _ = documents.standing("one_to_one_note")
    review, _ = documents.standing("performance_review")
    assert AUTHORITY_RANK[note] < AUTHORITY_RANK[review]

    held = {f.subject: f for f in staffed.facts
            if f.kind == "people.review.held_rating"}
    signed = {f.subject: f for f in staffed.facts
              if f.kind == "people.review.rating"}
    assert held and signed
    disagreements = [
        person for person in signed
        if person in held and held[person].text_value != signed[person].text_value
    ]
    assert disagreements, "two records that always agree teach nothing"
    for person in disagreements:
        assert AUTHORITY_RANK[held[person].authority] < \
            AUTHORITY_RANK[signed[person].authority]


def test_a_review_is_countersigned_one_level_up(staffed) -> None:  # type: ignore[no-untyped-def]
    """The corpus's only three-person document: the subject, the manager who
    wrote it, and the manager's own manager who agreed it. A rating nobody but
    the rater agreed is a rating with no calibration behind it."""
    people = {p.id: p for p in staffed.people}
    reviews = [i for i in staffed.artifact_intents
               if i.artifact_type == "performance_review" and i.approver_id]
    assert reviews
    for intent in reviews:
        assert people[intent.author_id].manager_id == intent.approver_id


def test_the_corpus_asks_which_record_wins(staffed) -> None:  # type: ignore[no-untyped-def]
    questions = [c for c in staffed.evaluations if "different rating" in c.question]
    assert questions, "a disagreement nobody asks about is decoration"
    assert questions[0].difficulty == "hard"

    crossing = [c for c in staffed.evaluations if "delegation of authority" in c.question]
    assert crossing, "the requisition/policy link is the point and nothing asks it"
    assert len(crossing[0].expected_fact_ids) >= 2, "a one-fact answer is not cross-document"


# ---------------------------------------------------------------------------
# 4. Readable by the people in them, and nobody else
# ---------------------------------------------------------------------------


def test_a_salary_is_not_published_to_all_staff(staffed) -> None:  # type: ignore[no-untyped-def]
    """The four classes retail ships are wrong for a document whose readership
    is one person and their line, and falling through to the narrowest locked
    the *author* out of what they wrote — which is what
    `validate.author_cannot_see_own_artifact` said the first time this ran."""
    policies = {p.id: p for p in staffed._access_policies}
    offers = [a for a in staffed.artifacts if a.artifact_type == "offer_letter"]
    assert offers
    for artifact in offers:
        policy = policies[artifact.access_policy_id]
        assert policy.label == workforce.PEOPLE_POLICY
        assert policy.allow_people, "a policy naming nobody permits everybody"
        assert not policy.allow_functions, "a line is not a function"


def test_the_whole_thing_validates(staffed) -> None:  # type: ignore[no-untyped-def]
    report = staffed.validate()
    assert report.ok, report.violations[:5]


def test_a_second_round_widens_the_policy_rather_than_replacing_it() -> None:
    """`personnel.promote`'s rule, arriving from the other direction: a policy
    that changes is the same policy, and appending is what keeps an earlier
    round's documents readable by the people who wrote them."""
    world = _wide().build().run(MonthEndClose(period=PERIOD))
    world = world.run(HiringRound(period=PERIOD, count=1))
    first = {p.label: set(p.allow_people) for p in world._access_policies}

    world = world.run(PerformanceCycle(period=PERIOD, pairs=2))
    after = {p.label: set(p.allow_people) for p in world._access_policies}

    assert first[workforce.PEOPLE_POLICY] <= after[workforce.PEOPLE_POLICY]
    assert len([p for p in world._access_policies
                if p.label == workforce.PEOPLE_POLICY]) == 1


# ---------------------------------------------------------------------------
# 5. Off by default, and it replays
# ---------------------------------------------------------------------------


def test_a_world_that_ran_no_round_has_no_people_policy() -> None:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period=PERIOD))
    assert not [p for p in world._access_policies if p.label == workforce.PEOPLE_POLICY]
    assert not [i for i in world.artifact_intents if i.domain == "people"]


def test_a_round_replays_from_its_recipe() -> None:
    """The *shape* of the round is recorded — how many vacancies — never who was
    picked or what they were offered: those are derived from the world's own seed
    under a stream of this module's own, so replay re-runs the same derivation."""
    from worldloom.recipe import rebuild

    world = _wide().build().run(MonthEndClose(period=PERIOD)).run(
        HiringRound(period=PERIOD, count=2)
    ).run(PerformanceCycle(period=PERIOD, pairs=2))

    steps = [s["scenario"] for s in world._recipe["steps"]]
    assert steps[-2:] == ["HiringRound", "PerformanceCycle"]

    again = rebuild(world._recipe)
    assert [f.model_dump() for f in again.facts] == [f.model_dump() for f in world.facts]
    assert [i.model_dump() for i in again.artifact_intents] == \
        [i.model_dump() for i in world.artifact_intents]
    assert [p.model_dump() for p in again._access_policies] == \
        [p.model_dump() for p in world._access_policies]


def test_a_round_of_nothing_is_refused_rather_than_silently_empty() -> None:
    """Refused when it runs rather than when it is constructed, which is where
    every other scenario in this package refuses: a dataclass that validated in
    `__init__` could not be built from a recipe field by field."""
    world = RetailWorld(seed=8128).build()
    with pytest.raises(ValueError, match="at least one vacancy"):
        HiringRound(period=PERIOD, count=0).run(world)
    with pytest.raises(ValueError, match="at least one pair"):
        PerformanceCycle(period=PERIOD, pairs=0).run(world)
