"""Deliberate imperfection, and the invariant that makes it safe.

``worldloom.messiness`` lets a corpus be as untidy as a real archive — pages
nobody updated, quotations that have gone out of date, documents whose author
left. That is only defensible because of one property, and this file is where it
stops being a claim:

**every imperfection is establishable from the corpus itself.** Not "is labelled
as deliberate" — a label is the generator vouching for itself. Establishable: a
reader holding only the ledger can derive, from timestamps and relationships that
were already there, that the stale page is stale and what the current position
is. An imperfection the corpus cannot explain is a defect wearing realism's
clothes, and it would break the one property the whole project rests on.

So ``test_every_imperfection_is_establishable`` **ignores the labels entirely**
and re-derives each kind's audit trail from the world. The labels are then
checked to agree with what was derived, which is the opposite direction from
trusting them.

The other three tests guard the contract around it: a pristine build is
untouched (byte-identity, the gate every other dimension in this project passes),
a corpus with imperfections replays from its own recipe, and ``validate``
actually refuses a label the corpus cannot substantiate — the check that makes
the first test's property enforced rather than merely observed.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World, messiness
from worldloom.documents import written_at
from worldloom.models import ErrorType, IntentionalError
from worldloom.recipe import rebuild
from worldloom.scenarios import Departure


def _base() -> World:
    """Three closes with a departure between the first and second.

    A departure is needed for orphaning to have any substrate at all — this pass
    mints no people, so a world where nobody ever leaves honestly has no orphaned
    documents — and it has to fall *between* episodes: run after the closes it
    would retroactively strand documents the planner had already dated, which is
    an ordinary incoherence (``temporal.author_already_departed``) and not
    something a messiness profile is entitled to introduce.
    """
    return (
        RetailWorld(seed=4242)
        .build()
        .run(MonthEndClose(period="2026-01", include_operational_incident=True))
        .run(Departure("2026-01", "controller"))
        .run(MonthEndClose(period="2026-02"))
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
    )


@pytest.fixture(scope="module")
def before() -> World:
    return _base()


@pytest.fixture(scope="module")
def after() -> World:
    # A fresh base, not `before`: a world's id minter is shared across `extend`,
    # so applying a pass to a fixture another test also reads would make the two
    # depend on which ran first.
    return messiness.apply(_base(), "neglected")


def test_a_pristine_profile_leaves_the_world_untouched() -> None:
    """The byte-identity contract, at the only place it can be broken.

    Every dimension in this project defaults to what the engine already did, so
    that adding the dimension is not a change to any corpus already built. Here
    that means the zero case touches neither the plan, nor the labels, nor the
    recipe — a recipe step recording "imperfections: none" would still be a new
    line in every recipe ever written, and the byte diff would find it.
    """
    base = _base()
    pristine = messiness.apply(base, "pristine")

    assert [i.id for i in pristine.artifact_intents] == [i.id for i in base.artifact_intents]
    assert list(pristine.intentional_errors) == list(base.intentional_errors)
    assert pristine._recipe == base._recipe
    assert messiness.DEFAULT is messiness.PRISTINE
    assert messiness.PRISTINE.degree == 0


def test_unknown_profiles_and_kinds_are_refused() -> None:
    """Refused, never quietly defaulted.

    The same posture ``Parameters.with_overrides`` and ``profiles.named`` take:
    a misspelled name that fell back to pristine would build a perfectly valid
    corpus with none of the messiness the caller asked for, and give them no way
    at all to notice.
    """
    with pytest.raises(KeyError, match="unknown messiness profile"):
        messiness.named("livedin")
    with pytest.raises(KeyError, match="unknown imperfection kind"):
        messiness.Messiness({"stalenes": 1})
    with pytest.raises(ValueError, match="negative"):
        messiness.Messiness({"staleness": -1})

    # A kind merely absent means zero, which is what lets a fourth kind be added
    # later without invalidating every profile already written down.
    assert messiness.Messiness({"staleness": 2})["orphaning"] == 0


def test_every_imperfection_is_establishable(before: World, after: World) -> None:
    """Derive each imperfection from the ledger, then check the label agrees.

    The labels are read only to find *which* documents claim to be imperfect and
    to compare against at the end. Everything asserted in between comes from
    facts, dates and relationships the corpus carries anyway.
    """
    assert after.validate().ok

    facts = {fact.id: fact for fact in after.facts}
    successor = {fact.supersedes: fact.id for fact in after.facts if fact.supersedes}
    minted = {i.id for i in after.artifact_intents} - {i.id for i in before.artifact_intents}
    errors = [e for e in after.intentional_errors if e not in list(before.intentional_errors)]
    assert minted and errors, "the profile produced nothing to check"

    labelled = {error.artifact_id: error for error in errors}
    corrections_used: set[str] = set()

    for artifact_id in minted:
        intent = after.artifact_intents.by_id(artifact_id)
        stale_facts = [f for f in intent.required_fact_ids if facts[f].is_superseded]

        # Establishable, part one: it carries exactly one thing the ledger
        # corrected, and it does not also carry the correction. All three halves
        # matter — "exactly one" is what makes the document unambiguous about
        # which claim it is making, the existence of a correction is what makes
        # "out of date" falsifiable, and the absence of it from the citations is
        # what keeps the document from being a history of the correction instead.
        assert len(stale_facts) == 1, f"{artifact_id} is out of date about {stale_facts}"
        assert successor.get(stale_facts[0]) not in intent.required_fact_ids, (
            f"{artifact_id} carries both a figure and its replacement"
        )

        old = facts[stale_facts[0]]
        new = facts[successor[old.id]]
        wrote = written_at(intent, facts)

        # Part two: which kind it is, derived from the date rather than read off
        # a label — and the two kinds are mutually exclusive by construction, so
        # the corpus cannot be ambiguous about which claim it is making.
        if wrote > new.valid_from:
            # Staleness. Written after the correction went on the record, so
            # nobody can plead ignorance, and nothing revises it, so it is still
            # in circulation rather than an archived draft.
            assert intent.revises is None and intent.supersedes is None
        else:
            # Disagreement. It predates the correction, so it was right when
            # written; it derives from the document it quoted, which is what
            # makes it secondary; and some *other* document carries the corrected
            # figure, so there is a live disagreement rather than a hole.
            assert intent.derived_from, f"{artifact_id} quotes nothing"
            parent = after.artifact_intents.by_id(intent.derived_from[0])
            assert written_at(parent, facts) <= wrote
            assert old.id in parent.required_fact_ids
            assert any(
                new.id in other.required_fact_ids
                for other in after.artifact_intents
                if other.id != artifact_id
            ), f"nothing in the corpus carries {new.id} for {artifact_id} to disagree with"

        # And the label agrees with what was derived, rather than the reverse.
        error = labelled[artifact_id]
        assert error.error_type is ErrorType.STALE_STATUS
        assert error.canonical_fact_id == new.id
        corrections_used.add(old.id)

    # One correction, one document. Two documents built from the same correction
    # would put the same figure in circulation twice under two different
    # explanations, and a reader could not tell which label described which.
    assert len(corrections_used) == len(minted)

    for error in errors:
        if error.error_type is not ErrorType.OUTDATED_OWNER:
            continue
        # Orphaning mints nothing, so it is checked against the documents the
        # world already had. Establishable: the roster says the author left, and
        # the fact named says who took the work on.
        author = after.people.by_id(after.artifact_intents.by_id(error.artifact_id).author_id)
        assert author.left is not None
        departure = after.facts.by_id(error.canonical_fact_id)
        assert departure.subject == author.id
        assert departure.valid_from >= author.left

    assert any(e.error_type is ErrorType.OUTDATED_OWNER for e in errors)


def test_a_messy_corpus_replays_from_its_own_recipe(after: World) -> None:
    """The recipe verb, and why it had to be one.

    An unrecorded generation step makes a corpus that cannot rebuild itself, and
    rebuilding itself is what a Worldloom corpus *is*. ``Imperfections`` is
    registered through ``recipe.register_step`` from ``messiness`` for that
    reason, and this is the check that the registration is real rather than
    decorative.
    """
    assert after._recipe["steps"][-1] == {"scenario": "Imperfections", "profile": "neglected"}

    replayed = rebuild(after._recipe)
    assert [i.model_dump() for i in replayed.artifact_intents] == [
        i.model_dump() for i in after.artifact_intents
    ]
    assert [e.model_dump() for e in replayed.intentional_errors] == [
        e.model_dump() for e in after.intentional_errors
    ]

    # A budget written out by hand round-trips too, since a recipe is JSON and a
    # corpus rebuildable only by whoever still had the Python object would fail
    # the reason recipes exist.
    custom = messiness.apply(_base(), messiness.Messiness({"staleness": 1}))
    assert rebuild(custom._recipe).validate().ok


def test_validate_refuses_a_label_the_corpus_cannot_substantiate(before: World) -> None:
    """The enforcement behind the property, stated as its own failure mode.

    A generator that gets this right today is not the same as a corpus that
    cannot get it wrong. These two labels are exactly what a careless pass — or
    a hand-authored corpus — would produce, and both are refused.
    """
    current = next(f for f in before.facts if not f.is_superseded)
    document = next(
        i for i in before.artifact_intents
        if not any(before.facts.by_id(f).is_superseded for f in i.required_fact_ids)
    )
    unearned = before.extend(intentional_errors=(
        IntentionalError(
            id="ERR-9001",
            artifact_id=document.id,
            error_type=ErrorType.STALE_STATUS,
            observed_value="claims to be out of date",
            canonical_value=(current.text_value or "").strip() or str(current.value.amount),
            canonical_fact_id=current.id,
        ),
    ))
    codes = {v.code for v in unearned.validate().violations}
    assert "stale_without_correction" in codes

    author_of = next(
        i for i in before.artifact_intents if before.people.by_id(i.author_id).left is None
    )
    mislabelled = before.extend(intentional_errors=(
        IntentionalError(
            id="ERR-9002",
            artifact_id=author_of.id,
            error_type=ErrorType.OUTDATED_OWNER,
            observed_value="claims to be orphaned",
            canonical_value="anything",
            canonical_fact_id=None,
        ),
    ))
    assert "owner_still_here" in {v.code for v in mislabelled.validate().violations}
