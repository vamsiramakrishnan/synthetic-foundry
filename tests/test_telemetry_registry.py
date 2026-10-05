"""Matching a catalogue's vocabulary against the connectors Worldloom ships.

The miner's example catalogue is the anchor: nine steps across three journeys.
Eight of them Worldloom can build today. The ninth is a Jira *project* lookup,
and Jira has no project record — the next commit folds it; here it is simply
refused, which is the honest answer until then.

Everything else covers what one file cannot:

    the example shows      │ these tests add
    ───────────────────────┼──────────────────────────────────────────────
    connectors we have     │ one we do not is refused by name
    entities we have       │ one we do not is refused by name
    operations we support  │ one we do not is refused by name
    one fault at a time    │ a journey with two faults reports both
    an alias that resolves │ it resolves with no finding at all
"""

from __future__ import annotations

from pathlib import Path

from worldloom.connector_definition import load_connector_definition
from worldloom.telemetry import (
    CONNECTOR_NOT_EMULATED,
    ENTITY_UNRESOLVED,
    OPERATION_UNSUPPORTED,
    load_catalogue,
    match_catalogue,
    match_cuj,
)

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

#: The journey the design document works through: notes in Confluence become
#: epics in Jira. It is the only one of the three that touches Jira.
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


def _replacing(catalogue, cuj):
    """A copy of *catalogue* with one journey swapped for *cuj*."""
    return catalogue.model_copy(update={"cujs": tuple(
        cuj if other.id == cuj.id else other for other in catalogue.cujs)})


def _step(cuj, step_id: str):
    return next(step for step in cuj.steps if step.id == step_id)


# ---------------------------------------------------------------------------
# The example catalogue, end to end.
# ---------------------------------------------------------------------------


def test_the_example_catalogue_matches_except_the_project_lookup() -> None:
    """Two of three journeys build; the one touching ``jira.project`` does not.

    These counts come from running the three checks over the miner's own
    example, and they are the regression guard for the whole module. They
    change in the next commit, when folding gives ``jira.project`` somewhere
    to go.
    """
    matched = match_catalogue(_catalogue())

    assert matched.refused == (NOTES_TO_EPICS,)
    assert len(matched.cujs) == 2
    assert _codes(matched.report.hard_findings) == [ENTITY_UNRESOLVED]
    assert matched.report.hard_findings[0].detail["entity"] == "project"

    # Nine steps in the file, across three journeys.
    assert sum(len(cuj.steps) for cuj in _catalogue().cujs) == 9


def test_capability_steps_pass_through_untouched() -> None:
    """A step that calls nothing has nothing to match against."""
    journeys = [match_cuj(cuj)[0] for cuj in _catalogue().cujs]
    capability_steps = [step for cuj in journeys if cuj is not None
                        for step in cuj.steps if not step.is_tool_step]

    assert len(capability_steps) == 2
    assert {step.capability for step in capability_steps} == {"answer", "generate"}


# ---------------------------------------------------------------------------
# The three refusals.
# ---------------------------------------------------------------------------


def test_an_unknown_connector_is_refused_by_name() -> None:
    """The design document's own picture of this case: ``acme_internal_tool``."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    connector="acme_internal_tool")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert CONNECTOR_NOT_EMULATED in _codes(findings)
    assert findings[0].detail["connector"] == "acme_internal_tool"
    assert findings[0].cuj_id == NOTES_TO_EPICS


def test_an_unknown_entity_is_refused_by_name() -> None:
    """Confluence has pages and spaces. It has no ``widget``."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert findings[0].code == ENTITY_UNRESOLVED
    assert findings[0].detail["entity"] == "widget"


def test_an_unsupported_operation_is_refused_by_name() -> None:
    """Jira models sprints, but its emulator will not delete one."""
    journey = _edit(_cuj(_catalogue(), NOTES_TO_EPICS), "find_notes",
                    connector="jira", entity="sprint", operation="delete")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert findings[0].code == OPERATION_UNSUPPORTED
    assert findings[0].detail["operation"] == "delete"


def test_every_step_is_checked_before_anything_is_refused() -> None:
    """Two broken steps report two findings, not just the first.

    W1 reports every invariant a file breaks rather than stopping at one, on
    the grounds that whoever has to fix a catalogue would rather see the whole
    list. Matching extends the same courtesy.
    """
    journey = _edit(_edit(_cuj(_catalogue(), NOTES_TO_EPICS),
                          "find_notes", connector="acme_internal_tool"),
                    "read_notes", entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings)[:2] == [CONNECTOR_NOT_EMULATED, ENTITY_UNRESOLVED]


def test_one_bad_journey_does_not_refuse_the_others() -> None:
    """A catalogue naming a connector we lack still yields the rest."""
    catalogue = _catalogue()
    lookup = _cuj(catalogue, "cuj_3ac134e740af")
    broken = _edit(lookup, "search", connector="acme_internal_tool")

    matched = match_catalogue(_replacing(catalogue, broken))

    assert set(matched.refused) == {NOTES_TO_EPICS, lookup.id}
    assert len(matched.cujs) == 1
    assert not matched.report.accepted


# ---------------------------------------------------------------------------
# Aliases.
# ---------------------------------------------------------------------------


def test_an_alias_resolves_without_a_finding() -> None:
    """``jira.issue`` is not a record type; it stands for five of them.

    The design document proposed choosing a concrete member here and recording
    ``alias_member_chosen``. Matching does not need to: the lookup accepts the
    alias on a write exactly as it does on a read. Choosing the concrete type
    belongs with choosing every other argument value, which is W3.
    """
    definition = load_connector_definition("jira")
    assert "issue" not in definition.entities
    assert definition.entity_members("issue") == (
        "epic", "story", "bug", "task", "subtask")
    assert definition.tool_for("issue", "create") == "create_issue"

    journey = _cuj(_catalogue(), NOTES_TO_EPICS)
    _, findings = match_cuj(journey)

    assert "alias_member_chosen" not in _codes(findings)
    assert _step(journey, "create_epics").entity == "issue"
