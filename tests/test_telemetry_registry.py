"""Matching a catalogue's vocabulary against the connectors Worldloom ships.

The miner's example catalogue is the anchor: nine steps across three journeys,
all of which Worldloom can build except one Jira project lookup, which folds.
Those four counts are measured, not assumed, and they are the first test —
break the alias lookup or the fold table and they move.

Everything else here covers what one happy file cannot:

    the example shows      │ these tests add
    ───────────────────────┼──────────────────────────────────────────────
    a fold happening       │ the graph it leaves behind is correct
    connectors we have     │ one we do not is refused by name
    operations we support  │ one we do not is refused by name
    an alias that resolves │ it resolves without comment, not with a finding
    today's field names    │ the fold table's fields still exist tomorrow
                           │ a write still needs a concrete type (W3's job)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worldloom.connector_definition import load_connector_definition
from worldloom.telemetry import (
    CONNECTOR_NOT_EMULATED,
    ENTITY_UNRESOLVED,
    FOLDS,
    OPERATION_UNSUPPORTED,
    STEP_FOLDED,
    Severity,
    load_catalogue,
    match_catalogue,
    match_cuj,
)

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

#: The journey the design document works through: notes in Confluence become
#: epics in Jira. It is the only one of the three that folds anything.
NOTES_TO_EPICS = "cuj_9636dd61a048"


def _catalogue():
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    return catalogue


def _cuj(catalogue, cuj_id: str):
    return next(cuj for cuj in catalogue.cujs if cuj.id == cuj_id)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


# The refusal tests need journeys the miner would never ship, and W1 refuses
# those at the door: naming a connector no ``connectors[]`` entry declares
# breaks ``inv1``, and any change to a step's signature breaks the id check in
# ``inv8``. Editing the JSON would mean re-deriving both. These helpers edit
# the loaded objects instead, which is the right level anyway — matching is
# being tested here, not loading, and W1 already proves a catalogue cannot
# arrive self-inconsistent.


def _edit(cuj, step_id: str, **changes):
    """A copy of *cuj* with one step's fields replaced."""
    return cuj.model_copy(update={"steps": tuple(
        step.model_copy(update=changes) if step.id == step_id else step
        for step in cuj.steps)})


def _drop(cuj, step_id: str):
    """A copy of *cuj* without one step."""
    return cuj.model_copy(update={"steps": tuple(
        step for step in cuj.steps if step.id != step_id)})


def _replacing(catalogue, cuj):
    """A copy of *catalogue* with one journey swapped for *cuj*."""
    return catalogue.model_copy(update={"cujs": tuple(
        cuj if other.id == cuj.id else other for other in catalogue.cujs)})


# ---------------------------------------------------------------------------
# The example catalogue, end to end.
# ---------------------------------------------------------------------------


def test_the_example_catalogue_matches_with_one_fold() -> None:
    """Nine steps, three of them capability steps, one fold, nothing refused.

    These numbers come from running the three checks over the miner's own
    example. They are the regression guard for the whole module: any change
    that breaks alias resolution, the fold table or capability pass-through
    moves at least one of them.
    """
    matched = match_catalogue(_catalogue())

    assert matched.refused == ()
    assert len(matched.cujs) == 3
    assert matched.report.accepted
    assert _codes(matched.report.findings) == [STEP_FOLDED]

    # Nine steps went in; the fold removed one.
    assert sum(len(cuj.steps) for cuj in _catalogue().cujs) == 9
    assert sum(len(cuj.steps) for cuj in matched.cujs) == 8


def test_capability_steps_pass_through_untouched() -> None:
    """A step that calls nothing has nothing to match against."""
    matched = match_catalogue(_catalogue())
    capability_steps = [step for cuj in matched.cujs for step in cuj.steps
                        if not step.is_tool_step]

    assert len(capability_steps) == 3
    assert {step.capability for step in capability_steps} == {"generate", "answer"}


# ---------------------------------------------------------------------------
# The fold.
# ---------------------------------------------------------------------------


def test_folding_removes_the_step_and_rewires_what_depended_on_it() -> None:
    """``find_project`` disappears; its value and its edges survive.

    Before: ``create_epics`` depends on ``find_project`` and ``draft_epics``,
    and ``find_project`` depends on nothing. After: the lookup is gone,
    ``create_epics`` depends only on ``draft_epics``, and it carries the
    ``project`` field the lookup used to supply.
    """
    before = _cuj(_catalogue(), NOTES_TO_EPICS)
    assert {step.id for step in before.steps} >= {"find_project", "create_epics"}
    assert set(_step(before, "create_epics").depends_on) == {
        "find_project", "draft_epics"}
    assert "project" not in _step(before, "create_epics").argument_fields

    after, findings = match_cuj(before)

    assert after is not None
    assert "find_project" not in {step.id for step in after.steps}
    assert _step(after, "create_epics").depends_on == ("draft_epics",)
    assert "project" in _step(after, "create_epics").argument_fields
    assert _codes(findings) == [STEP_FOLDED]
    assert findings[0].severity is Severity.INFO
    assert findings[0].detail["host_step_id"] == "create_epics"


def test_folding_leaves_untouched_steps_identical() -> None:
    """Only the deleted step and its host change. Nothing else is rewritten."""
    before = _cuj(_catalogue(), NOTES_TO_EPICS)
    after, _ = match_cuj(before)

    assert after is not None
    for step_id in ("find_notes", "read_notes", "draft_epics"):
        assert _step(after, step_id) == _step(before, step_id)


def test_a_fold_with_nowhere_to_put_the_value_is_unresolved() -> None:
    """A lookup nothing consumes cannot fold, because the value has no home.

    Deleting ``create_epics`` leaves ``find_project`` with no dependent step
    on a Jira issue. Silently dropping the lookup would quietly shrink the
    journey, so this is refused like any other unmatched entity.
    """
    stranded = _drop(_cuj(_catalogue(), NOTES_TO_EPICS), "create_epics")

    matched, findings = match_cuj(stranded)

    assert matched is None
    assert _codes(findings) == [ENTITY_UNRESOLVED]
    assert "nowhere to go" in findings[0].message
    assert findings[0].detail["fold_target"] == "issue"


# ---------------------------------------------------------------------------
# The three refusals.
# ---------------------------------------------------------------------------


def test_an_unknown_connector_is_refused_by_name() -> None:
    """The catalogue's own picture of this case: ``acme_internal_tool``."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    connector="acme_internal_tool")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [CONNECTOR_NOT_EMULATED]
    assert findings[0].detail["connector"] == "acme_internal_tool"
    assert findings[0].cuj_id == NOTES_TO_EPICS


def test_an_unknown_entity_with_no_fold_is_refused_by_name() -> None:
    """Confluence has pages and spaces. It has no ``widget``, and no fold."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [ENTITY_UNRESOLVED]
    assert findings[0].detail["entity"] == "widget"


def test_an_unsupported_operation_is_refused_by_name() -> None:
    """Jira models sprints, but its emulator will not delete one."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    connector="jira", entity="sprint", operation="delete")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [OPERATION_UNSUPPORTED]
    assert findings[0].detail["operation"] == "delete"


def test_every_step_is_checked_before_anything_is_refused() -> None:
    """Two broken steps report two findings, not just the first.

    W1 reports every invariant a file breaks rather than stopping at one, on
    the grounds that whoever has to fix a catalogue would rather see the whole
    list. Matching extends the same courtesy.
    """
    journey = _edit(_edit(_cuj(_catalogue(), NOTES_TO_EPICS),
                          "find_notes", connector="acme_internal_tool"),
                    "create_epics", entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [CONNECTOR_NOT_EMULATED, ENTITY_UNRESOLVED]


def test_one_bad_journey_does_not_refuse_the_others() -> None:
    """A catalogue naming a connector we lack still yields the rest."""
    catalogue = _catalogue()
    broken = _edit(_cuj(catalogue, NOTES_TO_EPICS), "find_notes",
                   connector="acme_internal_tool")

    matched = match_catalogue(_replacing(catalogue, broken))

    assert matched.refused == (NOTES_TO_EPICS,)
    assert len(matched.cujs) == 2
    assert NOTES_TO_EPICS not in {cuj.id for cuj in matched.cujs}
    assert not matched.report.accepted


# ---------------------------------------------------------------------------
# Aliases.
# ---------------------------------------------------------------------------


def test_an_alias_resolves_without_a_finding() -> None:
    """``jira.issue`` is not a record type; it stands for five of them.

    The design document proposed choosing a concrete member here and recording
    ``alias_member_chosen``. Matching does not need to: the lookup accepts the
    alias. Choosing the concrete type belongs with choosing every other
    argument value, which is W3.
    """
    definition = load_connector_definition("jira")
    assert "issue" not in definition.entities
    assert definition.entity_members("issue") == (
        "epic", "story", "bug", "task", "subtask")
    assert definition.tool_for("issue", "create") == "create_issue"

    matched = match_catalogue(_catalogue())

    assert "alias_member_chosen" not in _codes(matched.report.findings)
    assert _step(_cuj_of(matched, NOTES_TO_EPICS), "create_epics").entity == "issue"


# ---------------------------------------------------------------------------
# Guards against Worldloom drifting underneath us.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("source", "target"), sorted(FOLDS.items()))
def test_fold_fields_exist_in_the_live_definition(
        source: tuple[str, str], target) -> None:
    """Every field the fold table writes must still be a real field.

    A fold whose target field has been renamed does not fail — it quietly
    writes a field nothing reads, and the journey is built wrong. This is the
    test that turns that into a loud failure. Fields live in two places: an
    entity's ``required_on_create``, and the connector's ``query_fields``.
    """
    connector, entity = source
    definition = load_connector_definition(connector)
    assert entity not in definition.entities, (
        f"{connector}.{entity} is now a real record type; it should not be "
        "folded any more")

    members = definition.entity_members(target.entity)
    required = {field for member in members
                for field in definition.entities[member].required_on_create}
    assert target.field in required | set(definition.query_fields), (
        f"{connector}.{entity} folds onto the field {target.field!r} of "
        f"{target.entity!r}, which no longer exists")


def test_a_write_still_needs_a_concrete_entity() -> None:
    """Resolving the tool accepts an alias; calling it does not.

    ``tool_for('issue', 'create')`` answers happily, which is why matching has
    nothing to refuse. But ``create_issue`` declares ``entity`` without the
    ``?`` that marks a parameter optional, so some later stage must still pick
    epic, story or bug. That stage is W3's binding step. If this assertion
    ever fails, Worldloom has relaxed the requirement and the deferred rule
    can be dropped rather than written.
    """
    definition = load_connector_definition("jira")
    create = definition.tool(definition.tool_for("issue", "create"))

    assert create.params["entity"] == "string"
    assert "issue" not in create.entities


def _step(cuj, step_id: str):
    return next(step for step in cuj.steps if step.id == step_id)


def _cuj_of(matched, cuj_id: str):
    return next(cuj for cuj in matched.cujs if cuj.id == cuj_id)
