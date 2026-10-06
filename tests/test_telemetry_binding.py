"""Choosing the values the catalogue deliberately threw away.

Two properties are worth more here than any individual value being good, and
most of this file is about them:

    determinism   the same catalogue must give the same question text on any
                  machine, in any year, or a corpus cannot be compared with
                  itself between runs

    no giveaways  a question carrying a record id has handed the agent the
                  answer, and the search step it was meant to perform is
                  graded without being needed

The sample's write journey is the anchor. Its slots both resolve to free
text, so the edges — closed lists, people, ids — are built by hand.
"""

from __future__ import annotations

from pathlib import Path

from worldloom.providers import digest_bytes
from worldloom.telemetry import (
    Severity,
    load_catalogue,
    match_catalogue,
    sort_catalogue,
)
from worldloom.telemetry.binding import (
    PHRASING_DEFAULT_USED,
    PHRASING_VARIANT_UNUSED,
    BindRule,
    bind_question,
    bind_slot,
    fold_map,
    names_a_person,
    names_an_id,
    seed_for,
)

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

WRITES = "cuj_9636dd61a048"
DRAFTS = "cuj_80e0d9ce1f1b"


def _data() -> bytes:
    return EXAMPLE.read_bytes()


def _catalogue():
    catalogue, _ = load_catalogue(_data())
    return catalogue


def _cuj(cuj_id: str):
    """The journey as W3 sees it: matched, and with folds applied."""
    piles = sort_catalogue(match_catalogue(_catalogue()))
    found = next((cuj for cuj in piles.write if cuj.id == cuj_id), None)
    if found is not None:
        return found
    return next(cuj for cuj in _catalogue().cujs if cuj.id == cuj_id)


def _with_slot(cuj, *, field: str, name: str = "project"):
    """The journey with its first phrasing's named slot aimed at *field*."""
    phrasing = cuj.phrasings[0]
    slots = tuple(slot.model_copy(update={"field": field})
                  if slot.name == name else slot
                  for slot in phrasing.slots)
    return cuj.model_copy(update={
        "phrasings": (phrasing.model_copy(update={"slots": slots}),)})


# ---------------------------------------------------------------------------
# Determinism.
# ---------------------------------------------------------------------------


def test_the_same_catalogue_gives_the_same_question_every_time() -> None:
    first, _ = bind_question(_cuj(WRITES), digest_bytes(_data()))
    second, _ = bind_question(_cuj(WRITES), digest_bytes(_data()))

    assert first is not None
    assert first == second


def test_a_different_catalogue_gives_different_values() -> None:
    """The file's digest is in the seed, so two catalogues cannot collide.

    Without this, two customers' corpora would ask word-for-word identical
    questions wherever their journeys happened to share a shape.
    """
    journey = _cuj(WRITES)
    here, _ = bind_question(journey, digest_bytes(_data()))
    elsewhere, _ = bind_question(journey, digest_bytes(b"a different file"))

    assert here is not None
    assert elsewhere is not None
    assert here.text != elsewhere.text


def test_the_seed_depends_on_every_part_of_its_input() -> None:
    base = seed_for("cat", "cuj_1", "jira", "issue", "summary")

    assert base != seed_for("OTHER", "cuj_1", "jira", "issue", "summary")
    assert base != seed_for("cat", "cuj_2", "jira", "issue", "summary")
    assert base != seed_for("cat", "cuj_1", "confluence", "issue", "summary")
    assert base != seed_for("cat", "cuj_1", "jira", "page", "summary")
    assert base != seed_for("cat", "cuj_1", "jira", "issue", "description")
    assert base == seed_for("cat", "cuj_1", "jira", "issue", "summary")


# ---------------------------------------------------------------------------
# The sample, bound end to end.
# ---------------------------------------------------------------------------


def test_the_write_journey_produces_a_question_with_no_holes_left() -> None:
    question, findings = bind_question(_cuj(WRITES), digest_bytes(_data()))

    assert findings == ()
    assert question is not None
    assert "{" not in question.text
    assert "}" not in question.text
    assert {binding.slot for binding in question.bindings} == {
        "project", "meeting_title"}


def test_a_slot_whose_step_was_folded_is_followed_to_where_the_value_went() -> None:
    """``find_project`` is gone by now, but its value is not lost.

    W2 recorded where it went. Following that redirection is what keeps the
    slot bound against a real connector and entity — without it the slot
    would resolve to nothing, and a field with declared options would
    silently fall through to free text.
    """
    piles = sort_catalogue(match_catalogue(_catalogue()))
    journey = next(cuj for cuj in piles.write if cuj.id == WRITES)
    folds = fold_map(piles.report)

    assert "find_project" not in {step.id for step in journey.steps}
    assert folds["find_project"] == ("create_epics", "project")

    question, _ = bind_question(journey, digest_bytes(_data()), folds=folds)

    assert question is not None
    assert any(binding.slot == "project" for binding in question.bindings)


def test_following_a_fold_is_what_makes_a_closed_list_reachable() -> None:
    """Not cosmetic. A dangling slot resolves to no connector at all, so a
    field with declared options falls through to invented free text. Followed
    to its host, the same field finds the connector's real values.

    Shown with ``status``, which Jira declares states for. The sample's real
    fold targets ``project``, which has no closed list, so it cannot show the
    difference.
    """
    piles = sort_catalogue(match_catalogue(_catalogue()))
    journey = next(cuj for cuj in piles.write if cuj.id == WRITES)
    slot = journey.phrasings[0].slots[0].model_copy(update={
        "name": "state", "step_id": "find_project", "field": "query"})
    digest = digest_bytes(_data())

    dangling = bind_slot(slot, journey, digest)
    followed = bind_slot(slot, journey, digest,
                         folds={"find_project": ("create_epics", "status")})

    assert dangling.rule is BindRule.TEXT
    assert followed.rule is BindRule.OPTION
    assert followed.value in {"todo", "open", "review", "done", "blocked"}


# ---------------------------------------------------------------------------
# The four rules.
# ---------------------------------------------------------------------------


def test_an_id_or_key_is_recognised_by_name() -> None:
    for name in ("id", "page_id", "project_key", "issue_ids", "record_uuid",
                 "key"):
        assert names_an_id(name), name
    for name in ("identity", "summary", "keywords", "query", "queries",
                 "description"):
        assert not names_an_id(name), name


def test_an_id_is_referred_to_rather_than_written() -> None:
    """A question naming OPS-412 grades a search the agent never performed.

    So the id is never written — but it is still referred to, by the kind of
    thing it names. The question survives and the search stays worth doing.
    """
    journey = _with_slot(_cuj(WRITES), field="page_id")

    question, _ = bind_question(journey, digest_bytes(_data()))

    assert question is not None
    binding = next(b for b in question.bindings if b.slot == "project")
    assert binding.rule is BindRule.REFERENCE
    assert binding.value.startswith("the ")
    assert "page_id" not in question.text
    assert not any(character.isdigit() for character in binding.value)


def test_a_person_field_gets_a_role_not_a_name() -> None:
    """The catalogue carries no names. Inventing one would read as evidence."""
    for name in ("assignee", "reporter", "owner_user", "mentions"):
        assert names_a_person(name), name

    journey = _with_slot(_cuj(WRITES), field="assignee")
    slot = journey.phrasings[0].slots[0]

    binding = bind_slot(slot, journey, digest_bytes(_data()))

    assert binding is not None
    assert binding.rule is BindRule.PERSON
    assert binding.value == "the assignee"


def test_a_closed_list_is_picked_from_the_connector_not_invented() -> None:
    """Jira declares its own statuses. The value must be one of them."""
    journey = _cuj(WRITES)
    phrasing = journey.phrasings[0]
    slot = phrasing.slots[0].model_copy(update={
        "step_id": "create_epics", "field": "status"})

    binding = bind_slot(slot, journey, digest_bytes(_data()))

    assert binding is not None
    assert binding.rule is BindRule.OPTION
    assert binding.value in {"todo", "open", "review", "done", "blocked"}
    assert "workflow" in binding.source


def test_a_container_slot_gets_a_key_shaped_name_not_a_phrase() -> None:
    """"Create epics in store ops" is not English. "in STOREOPS" is.

    The width and the casing are not invented here: ``jira.json`` builds its
    own project values as ``{stream|upper|first:10}``, so this matches the
    shape Worldloom already generates.
    """
    journey = _cuj(WRITES)
    question, _ = bind_question(journey, digest_bytes(_data()))

    assert question is not None
    binding = next(b for b in question.bindings if b.slot == "project")
    assert binding.rule is BindRule.KEY
    assert binding.value.isupper()
    assert binding.value.isalnum()
    assert len(binding.value) <= 10
    assert "derived from" in binding.source


def test_a_container_name_prefers_a_phrase_over_a_single_word() -> None:
    """A lone word in a journey's vocabulary is usually jargon for the work
    — "epic", "sprint". A phrase usually names what the work is about, which
    is what a container tends to be called after."""
    journey = _cuj(WRITES).model_copy(update={
        "domain_terms": ("epic", "sprint", "store ops")})

    question, _ = bind_question(journey, digest_bytes(_data()))

    assert question is not None
    binding = next(b for b in question.bindings if b.slot == "project")
    assert binding.value == "STOREOPS"


def test_a_container_falls_back_when_the_journey_has_no_vocabulary() -> None:
    journey = _cuj(WRITES).model_copy(update={"domain_terms": ()})

    question, _ = bind_question(journey, digest_bytes(_data()))

    assert question is not None
    binding = next(b for b in question.bindings if b.slot == "project")
    assert binding.value == "GENERAL"


def test_a_closed_list_still_beats_the_container_rule() -> None:
    """Real declared values are always better than a derived name."""
    journey = _cuj(WRITES)
    slot = journey.phrasings[0].slots[0].model_copy(update={
        "name": "project", "step_id": "create_epics", "field": "status"})

    binding = bind_slot(slot, journey, digest_bytes(_data()))

    assert binding is not None
    assert binding.rule is BindRule.OPTION


def test_free_text_comes_from_the_journeys_own_vocabulary() -> None:
    journey = _cuj(WRITES)
    question, _ = bind_question(journey, digest_bytes(_data()))

    assert question is not None
    text_values = {binding.value for binding in question.bindings
                   if binding.rule is BindRule.TEXT}
    assert text_values
    assert text_values <= set(journey.domain_terms)


# ---------------------------------------------------------------------------
# Choosing which phrasing to use.
# ---------------------------------------------------------------------------


def test_the_most_used_phrasing_wins() -> None:
    journey = _cuj(WRITES)
    popular = journey.phrasings[0]
    rare = popular.model_copy(update={
        "template": "Make some epics for {project}", "support": 1,
        "slots": (popular.slots[0],)})

    question, _ = bind_question(
        journey.model_copy(update={"phrasings": (rare, popular)}),
        digest_bytes(_data()))

    assert question is not None
    assert question.template == popular.template
    assert question.support == popular.support


def test_a_template_naming_an_undeclared_slot_falls_through() -> None:
    """One broken phrasing should not cost the journey. ``inv3`` checks that
    every slot names a real step; nothing checks the other direction."""
    journey = _cuj(WRITES)
    good = journey.phrasings[0]
    broken = good.model_copy(update={
        "template": "Comment on {nobody_declared_this}", "support": 99,
        "slots": (good.slots[0],)})

    question, findings = bind_question(
        journey.model_copy(update={"phrasings": (broken, good)}),
        digest_bytes(_data()))

    assert question is not None
    assert question.template == good.template
    assert PHRASING_VARIANT_UNUSED in [f.code for f in findings]


def test_a_journey_with_no_phrasings_asks_for_a_default_not_a_refusal() -> None:
    """The drafting journey ships none, because every wording it saw was too
    rare to publish safely. That is privacy working, not a fault, so the
    caller supplies a built-in template rather than losing the journey."""
    question, findings = bind_question(_cuj(DRAFTS), digest_bytes(_data()))

    assert question is None
    assert findings[0].code == PHRASING_DEFAULT_USED
    assert findings[0].severity is Severity.INFO
    assert findings[0].detail["phrasings"] == "0"
