"""The episode's third output: who was told what, and who therefore knew it.

Two things are being proved here, and they are not the same thing.

The first is that the knowledge layer *exists and is coherent* — every
observation sits inside its observer's employment and after its fact was true,
every message discloses only what its sender held and reaches everyone it names,
and every document's author had heard what the document says. Those are the
invariants ``validate.actors`` polices, and they are asserted here against the
records rather than against the code that wrote them.

The second is that it *buys a question nothing else can pose*. An asymmetry case
whose answer cannot be recomputed from ``observations.jsonl`` is a sentence, not
a benchmark entry, so the test that matters most below re-derives the expected
answer from the shipped ledger and requires it to match character for character.

And one negative: a close built without ``conversations`` produces exactly the
corpus it always did, down to the absence of the recipe key. Every corpus this
project has built is downstream of that assertion.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.actors import ScriptedActorProvider
from worldloom.asymmetry import cases as asymmetry_cases
from worldloom.conversation import derive
from worldloom.documents import written_at
from worldloom.ids import Minter

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def spoken() -> World:
    """A retail close with its knowledge layer recorded."""
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True, conversations=True)
    )


@pytest.fixture(scope="module")
def asymmetry(spoken: World) -> tuple:
    """The asymmetry families, re-derived from the shipped world.

    Re-derived rather than filtered out of ``spoken.evaluations``: the corpus
    already carries `temporal_state` and `authority_resolution` cases from the
    ordinary taxonomy, and a test that picks its subject out of a mixed pile by
    guessing at question wording proves whatever the guess happened to match.
    """
    return asymmetry_cases(
        Minter(),
        world=spoken,
        observations=tuple(spoken.observations),
        messages=tuple(spoken.messages),
        period=PERIOD,
    )


@pytest.fixture(scope="module")
def silent() -> World:
    """The same close without it."""
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


def _held(world: World) -> dict[tuple[str, str], object]:
    out: dict[tuple[str, str], object] = {}
    for record in world.observations:
        key = (record.observer_id, record.fact_id)
        first = out.get(key)
        if first is None or record.learned_at < first:  # type: ignore[operator]
            out[key] = record.learned_at
    return out


# -- the layer exists ------------------------------------------------------


def test_an_episode_records_who_knew_what(spoken: World) -> None:
    assert spoken.observations, "conversations produced no knowledge ledger"
    assert spoken.messages, "conversations produced no messages"
    observers = {record.observer_id for record in spoken.observations}
    assert len(observers) > 1, "a ledger with one observer has no asymmetry in it"


def test_the_same_fact_reaches_different_people_at_different_times(spoken: World) -> None:
    """The whole point. A ledger where everyone learns everything at once is the
    canonical fact ledger with more rows."""
    by_fact: dict[str, set] = {}
    for record in spoken.observations:
        by_fact.setdefault(record.fact_id, set()).add(record.learned_at)
    assert any(len(moments) > 1 for moments in by_fact.values())


def test_every_channel_the_model_declares_is_actually_used(spoken: World) -> None:
    """A channel nothing ever takes is a branch nobody has exercised.

    ``artifact`` is deliberately absent from the expectation: during a build
    nothing has been rendered, so ``observations_for`` finds no readable document
    and that channel cannot fire. It is named here so its absence stays a
    recorded finding rather than becoming an unnoticed hole.
    """
    used = {record.source_type for record in spoken.observations}
    assert {"participant", "trigger", "system_of_record", "message", "duty"} <= used
    assert "artifact" not in used


def test_a_message_channel_observation_names_the_message(spoken: World) -> None:
    ids = {message.id for message in spoken.messages}
    told = [r for r in spoken.observations if r.source_type == "message"]
    assert told
    assert all(record.source_id in ids for record in told)


# -- the invariants --------------------------------------------------------


def test_nobody_learns_anything_before_it_is_true(spoken: World) -> None:
    facts = {fact.id: fact for fact in spoken.facts}
    for record in spoken.observations:
        assert record.learned_at >= facts[record.fact_id].valid_from


def test_nobody_learns_anything_before_they_are_hired(spoken: World) -> None:
    """The defect this pass found in the shipped runtime, as an assertion.

    The ``duty`` channel works backwards from a fact's own validity, so a norm
    adopted in 2022 was reaching a 2024 hire in 2022.
    """
    people = {person.id: person for person in spoken.people}
    for record in spoken.observations:
        person = people[record.observer_id]
        assert person.joined is None or person.joined <= record.learned_at
        assert person.left is None or person.left > record.learned_at


def test_a_sender_only_discloses_what_it_already_holds(spoken: World) -> None:
    held = _held(spoken)
    for message in spoken.messages:
        for fact_id in message.disclosed_fact_ids:
            first = held.get((message.sender_id, fact_id))
            assert first is not None and first <= message.sent_at, (
                f"{message.id} discloses {fact_id} its sender had no record of"
            )


def test_every_disclosure_reaches_every_recipient(spoken: World) -> None:
    held = _held(spoken)
    for message in spoken.messages:
        for recipient in message.recipient_ids:
            for fact_id in message.disclosed_fact_ids:
                assert held.get((recipient, fact_id)) is not None


def test_an_author_has_heard_what_their_document_says(spoken: World) -> None:
    """The epistemic half of ``cites_future_fact``.

    Before briefings existed this failed six times on the stock incident close:
    the controller's working note cites a root cause their role cannot read, and
    the analyst's email thread cites a close status theirs cannot.
    """
    held = _held(spoken)
    facts = {fact.id: fact for fact in spoken.facts}
    covered = {record.observer_id for record in spoken.observations}
    checked = 0
    for intent in spoken.artifact_intents:
        if intent.author_id not in covered:
            continue
        deadline = written_at(intent, facts)
        for fact_id in intent.required_fact_ids:
            first = held.get((intent.author_id, fact_id))
            assert first is not None and first <= deadline, (
                f"{intent.id}: {intent.author_id} cites {fact_id} unheard"
            )
            checked += 1
    assert checked, "no author was covered by the ledger, so nothing was checked"


def test_the_corpus_validates(spoken: World) -> None:
    report = spoken.validate()
    assert report.ok, [f"{v.code} {v.subject}: {v.detail}" for v in report.violations]


# -- the question it buys --------------------------------------------------


def test_the_asymmetry_answer_is_recomputable_from_the_shipped_ledger(
    spoken: World, asymmetry: tuple
) -> None:
    """A benchmark answer nobody can check is a sentence with a colon in it."""
    people = {person.id: person for person in spoken.people}
    held: dict[str, list] = {}
    for record in spoken.observations:
        held.setdefault(record.fact_id, []).append(record)

    windows = [
        case for case in asymmetry
        if case.evaluation_type.value == "causal_multi_hop"
    ]
    assert windows, "no information-asymmetry window case was generated"

    proven = 0
    for case in windows:
        fact_id = case.expected_fact_ids[0]
        earliest: dict[str, object] = {}
        for record in held.get(fact_id, ()):
            first = earliest.get(record.observer_id)
            if first is None or record.learned_at < first:  # type: ignore[operator]
                earliest[record.observer_id] = record.learned_at
        ahead = sorted(
            (at, person) for person, at in earliest.items()
            if at < case.temporal_cutoff  # type: ignore[operator]
        )
        if not ahead:
            continue
        expected = "; ".join(
            f"{people[person].name} ({people[person].title}) from {at.isoformat()}"  # type: ignore[attr-defined]
            for at, person in ahead
        ) + "."
        assert case.expected_answer == expected
        proven += 1
    assert proven, "every window case had an empty answer set"


def test_every_asymmetry_case_cites_a_fact_some_document_carries(
    spoken: World, asymmetry: tuple
) -> None:
    carried = {
        fact_id
        for intent in spoken.artifact_intents
        for fact_id in intent.required_fact_ids
    }
    assert asymmetry
    for case in asymmetry:
        assert set(case.expected_fact_ids) <= carried


def test_the_derived_cases_reached_the_corpus(spoken: World, asymmetry: tuple) -> None:
    """The seam is wired, not merely importable."""
    asked = {case.question for case in spoken.evaluations}
    assert {case.question for case in asymmetry} <= asked


def test_the_channel_family_is_generated_at_all(asymmetry: tuple) -> None:
    """Ranking on spread alone would never select a fact somebody was *told*, so
    the family that makes ``messages.jsonl`` load-bearing would be dead code."""
    told = [
        case for case in asymmetry
        if case.evaluation_type.value == "authority_resolution"
    ]
    assert told
    assert all("told them at" in (case.expected_answer or "") for case in told)


def test_the_cases_are_absent_without_a_ledger(silent: World) -> None:
    empty = asymmetry_cases(Minter(), world=silent, observations=(), period=PERIOD)
    assert empty == ()


# -- determinism and additivity --------------------------------------------


def test_deriving_twice_gives_the_same_records(silent: World) -> None:
    first = derive(silent, minter=Minter(), roles=dict(silent._roles))
    second = derive(silent, minter=Minter(), roles=dict(silent._roles))
    assert list(first.observations) == list(second.observations)
    assert list(first.messages) == list(second.messages)


def test_deriving_again_over_its_own_output_adds_nothing(silent: World) -> None:
    """What makes a second period append rather than duplicate."""
    first = derive(silent, minter=Minter(), roles=dict(silent._roles))
    once = silent.extend(observations=first.observations, messages=first.messages)
    again = derive(once, minter=Minter(), roles=dict(silent._roles))
    assert again.observations == ()
    assert again.messages == ()


def test_a_close_without_conversations_is_untouched(silent: World) -> None:
    assert silent.observations == ()
    assert silent.messages == ()
    step = silent.recipe["steps"][-1]
    assert "conversations" not in step, (
        "an absent knob must stay absent from the recipe, or every default"
        " build's bytes move"
    )


def test_the_recipe_rebuilds_the_knowledge_layer_exactly(spoken: World) -> None:
    from worldloom.recipe import rebuild

    replayed = rebuild(spoken.recipe)
    assert list(replayed.observations) == list(spoken.observations)
    assert list(replayed.messages) == list(spoken.messages)
    assert list(replayed.evaluations) == list(spoken.evaluations)


def test_a_second_period_appends_rather_than_repeats() -> None:
    world = RetailWorld(seed=8128).build()
    world = world.run(
        MonthEndClose(period="2026-03", include_operational_incident=True, conversations=True)
    )
    after_one = len(world.observations)
    world = world.run(MonthEndClose(period="2026-04", conversations=True))
    pairs = [(record.observer_id, record.fact_id) for record in world.observations]
    assert len(pairs) == len(set(pairs)), "a (person, fact) pair was recorded twice"
    assert len(world.observations) > after_one


def test_conversations_and_actors_are_refused_together() -> None:
    world = RetailWorld(seed=8128).build()
    with pytest.raises(ValueError, match="knowledge ledger"):
        world.run(
            MonthEndClose(
                period=PERIOD,
                include_operational_incident=True,
                conversations=True,
                actors=ScriptedActorProvider(),
            )
        )


# -- the validator has teeth ----------------------------------------------


@pytest.mark.parametrize(
    ("code", "tamper"),
    [
        ("premature_observation", "early"),
        ("observer_not_employed", "prehire"),
        ("undisclosed_by_sender", "unheard"),
        ("author_cited_unobserved", "forget"),
    ],
)
def test_the_validator_catches_a_doctored_ledger(spoken: World, code: str, tamper: str) -> None:
    """Each check is asserted by breaking exactly the thing it claims to catch.

    A validator nobody has seen fail is a validator nobody has tested.
    """
    from dataclasses import replace

    from datetime import timedelta

    observations = list(spoken.observations)
    messages = list(spoken.messages)

    if tamper == "early":
        target = observations[0]
        observations[0] = target.model_copy(
            update={"learned_at": target.learned_at - timedelta(days=3650)}
        )
    elif tamper == "prehire":
        people = {person.id: person for person in spoken.people}
        facts = {fact.id: fact for fact in spoken.facts}
        # After the fact was valid — so only the employment check can fire — and
        # before the observer was hired.
        target = next(
            record for record in observations
            if (start := people[record.observer_id].joined) is not None
            and facts[record.fact_id].valid_from < start
        )
        joined = people[target.observer_id].joined
        observations[observations.index(target)] = target.model_copy(
            update={"learned_at": joined - timedelta(minutes=1)}
        )
    elif tamper == "unheard":
        target = messages[0]
        stranger = next(
            fact.id for fact in spoken.facts
            if fact.id not in target.disclosed_fact_ids
            and not any(
                record.observer_id == target.sender_id and record.fact_id == fact.id
                for record in observations
            )
        )
        messages[0] = target.model_copy(
            update={"disclosed_fact_ids": [*target.disclosed_fact_ids, stranger]}
        )
    else:  # forget
        covered = {record.observer_id for record in observations}
        intent = next(i for i in spoken.artifact_intents if i.author_id in covered)
        dropped = intent.required_fact_ids[0]
        observations = [
            record for record in observations
            if not (record.observer_id == intent.author_id and record.fact_id == dropped)
        ]

    doctored = replace(spoken, _observations=tuple(observations), _messages=tuple(messages))
    report = doctored.validate()
    assert not report.ok
    assert code in {violation.code for violation in report.violations}, (
        f"{code} did not fire; got {sorted({v.code for v in report.violations})}"
    )
