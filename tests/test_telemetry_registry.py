"""Matching a catalogue's vocabulary against the connectors Worldloom ships.

The miner's example catalogue is the anchor: three journeys. Two match. The
third — notes in Confluence become epics in Jira — searches for a Jira
*project*, and Jira models no project record. It is refused, and the refusal
says exactly what Worldloom would need: a ``jira.project`` entity offering
``search``, wanted by 22 sessions, 22.9% of traffic.

Nothing here rewrites a journey. A matched journey comes back byte for byte
as the customer recorded it, and still passes every invariant W1 checks; a
journey that cannot be matched is refused whole.

    the example shows      │ these tests add
    ───────────────────────┼──────────────────────────────────────────────
    one missing entity     │ the gap report groups and ranks by traffic
    journeys that match    │ they come back unchanged, invariants intact
    connectors we have     │ one we do not is refused by name
    operations we support  │ one we do not, and an ambiguous one, by name
    one fault at a time    │ a journey with two faults reports both
    an alias that resolves │ it resolves with no finding at all
    today's definitions    │ loaded once per run, and the day jira.project
                           │ arrives, a test says so
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import connector_definition
from worldloom.connector_definition import load_connector_definition
from worldloom.telemetry import (
    CONNECTOR_NOT_EMULATED,
    ENTITY_UNRESOLVED,
    OPERATION_AMBIGUOUS,
    OPERATION_UNSUPPORTED,
    load_catalogue,
    match_catalogue,
    match_cuj,
    registry,
)
from worldloom.telemetry.invariants import check

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

#: Notes in Confluence become epics in Jira. Searches for a Jira project.
NOTES_TO_EPICS = "cuj_9636dd61a048"
#: Search a Confluence page, read it, answer. Matches cleanly, so the
#: refusal tests edit this one: one cause per test.
LOOKUP = "cuj_3ac134e740af"
#: Drafting help, no tool calls at all.
DRAFTING = "cuj_80e0d9ce1f1b"


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
# ``inv8``. These helpers edit the loaded objects instead, which is the right
# level anyway — matching is being tested here, not loading.


def _edit(cuj, step_id: str, **changes):
    """A copy of *cuj* with one step's fields replaced."""
    return cuj.model_copy(update={"steps": tuple(
        step.model_copy(update=changes) if step.id == step_id else step
        for step in cuj.steps)})


def _replacing(catalogue, *cujs):
    """A copy of *catalogue* with some journeys swapped for edited ones."""
    edited = {cuj.id: cuj for cuj in cujs}
    return catalogue.model_copy(update={"cujs": tuple(
        edited.get(other.id, other) for other in catalogue.cujs)})


# ---------------------------------------------------------------------------
# The example catalogue, end to end.
# ---------------------------------------------------------------------------


def test_the_example_matches_two_journeys_and_refuses_the_project_lookup() -> None:
    matched = match_catalogue(_catalogue())

    assert {cuj.id for cuj in matched.cujs} == {LOOKUP, DRAFTING}
    assert matched.refused == (NOTES_TO_EPICS,)
    assert _codes(matched.report.findings) == [ENTITY_UNRESOLVED]
    finding = matched.report.findings[0]
    assert finding.detail == {"step_id": "find_project", "connector": "jira",
                              "entity": "project", "operation": "search"}
    assert "Add it to the jira connector definition" in finding.message


def test_the_refusal_says_exactly_what_worldloom_would_need() -> None:
    """A to-do list for the connector definitions, weighted by real usage."""
    matched = match_catalogue(_catalogue())

    assert len(matched.missing) == 1
    gap = matched.missing[0]
    assert gap.name == "jira.project"
    assert gap.kind == "entity"
    assert gap.operations == ("search",)
    assert gap.cuj_ids == (NOTES_TO_EPICS,)
    assert gap.sessions == 22
    assert gap.share == pytest.approx(0.229)


def test_matched_journeys_come_back_exactly_as_recorded() -> None:
    """Matching asks questions; it never rewrites. An earlier version folded
    a lookup into a field, which left a slot and two failure modes pointing
    at a deleted step and the id no longer hashing from the steps."""
    catalogue = _catalogue()
    matched = match_catalogue(catalogue)

    for cuj in matched.cujs:
        assert cuj == _cuj(catalogue, cuj.id)


def test_the_output_still_satisfies_every_invariant_w1_checks() -> None:
    """The check the folding version never ran. Put the matched journeys back
    into the catalogue and W1's invariants must find nothing — so no later
    change to matching can quietly break inv2, inv3, inv4 or inv8."""
    catalogue = _catalogue()
    matched = match_catalogue(catalogue)

    assert check(_replacing(catalogue, *matched.cujs)) == ()


def test_capability_steps_pass_through_untouched() -> None:
    """A step that calls nothing has nothing to match against."""
    matched = match_catalogue(_catalogue())
    capability_steps = [step for cuj in matched.cujs for step in cuj.steps
                        if not step.is_tool_step]

    assert {step.capability for step in capability_steps} == {"answer", "generate"}


# ---------------------------------------------------------------------------
# The gap report.
# ---------------------------------------------------------------------------


def test_the_gap_report_groups_journeys_and_sums_their_traffic() -> None:
    """Two journeys needing the same entity are one line, worth both."""
    catalogue = _catalogue()
    also_projects = _edit(_cuj(catalogue, LOOKUP), "search",
                          connector="jira", entity="project")

    matched = match_catalogue(_replacing(catalogue, also_projects))

    assert [gap.name for gap in matched.missing] == ["jira.project"]
    gap = matched.missing[0]
    assert gap.cuj_ids == (LOOKUP, NOTES_TO_EPICS)
    assert gap.sessions == 22 + 31
    assert gap.share == pytest.approx(0.229 + 0.323)


def test_the_gap_report_puts_the_most_used_gap_first() -> None:
    catalogue = _catalogue()
    no_such_system = _edit(_cuj(catalogue, LOOKUP), "search",
                           connector="acme_internal_tool")

    matched = match_catalogue(_replacing(catalogue, no_such_system))

    assert [(gap.kind, gap.name) for gap in matched.missing] == [
        ("connector", "acme_internal_tool"),   # 32.3% of traffic
        ("entity", "jira.project")]            # 22.9%


def test_an_ambiguous_operation_is_not_a_gap() -> None:
    """The record type and the operation both exist; the definition's
    mapping is what needs fixing, not its coverage."""
    findings = match_cuj(_create_issue(), definitions=_ambiguous_jira())[1]

    assert _codes(findings) == [OPERATION_AMBIGUOUS]
    assert registry._missing(_catalogue(), list(findings)) == ()


# ---------------------------------------------------------------------------
# The refusals.
# ---------------------------------------------------------------------------


def test_an_unknown_connector_is_refused_by_name() -> None:
    journey = _edit(_cuj(_catalogue(), LOOKUP), "search",
                    connector="acme_internal_tool")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [CONNECTOR_NOT_EMULATED]
    assert findings[0].detail["connector"] == "acme_internal_tool"
    assert findings[0].cuj_id == LOOKUP


def test_an_unknown_entity_is_refused_by_name() -> None:
    """Confluence has pages and spaces. It has no ``widget``."""
    journey = _edit(_cuj(_catalogue(), LOOKUP), "search", entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [ENTITY_UNRESOLVED]
    assert findings[0].detail["entity"] == "widget"


def test_an_unsupported_operation_is_refused_by_name() -> None:
    """Jira models sprints, but its emulator will not delete one."""
    journey = _edit(_cuj(_catalogue(), LOOKUP), "search",
                    connector="jira", entity="sprint", operation="delete")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [OPERATION_UNSUPPORTED]
    assert findings[0].detail["operation"] == "delete"


def _create_issue():
    """The notes-to-epics journey without its project lookup, so it matches
    on today's Jira — the shape it would have once ``jira.project`` exists
    and is used through a different step."""
    cuj = _cuj(_catalogue(), NOTES_TO_EPICS)
    return cuj.model_copy(update={"steps": tuple(
        step.model_copy(update={"depends_on": tuple(
            dep for dep in step.depends_on if dep != "find_project")})
        for step in cuj.steps if step.id != "find_project")})


def _ambiguous_jira():
    """Today's Jira with one change: epics are created by their own tool. Now
    ``issue`` maps ``create`` to two tools, and no shipped connector does."""
    jira = load_connector_definition("jira")
    epic = jira.entities["epic"]
    entities = {**jira.entities, "epic": epic.model_copy(update={
        "ops": {**epic.ops, "create": "create_epic"}})}
    return {"jira": jira.model_copy(update={"entities": entities}),
            "confluence": load_connector_definition("confluence")}


def test_an_alias_mapping_one_operation_to_several_tools_is_ambiguous() -> None:
    """Reported as unsupported before, which sent whoever read it looking for
    a missing operation that was not missing."""
    matched, findings = match_cuj(_create_issue(), definitions=_ambiguous_jira())

    assert matched is None
    assert _codes(findings) == [OPERATION_AMBIGUOUS]
    assert findings[0].detail["tools"] == "create_epic,create_issue"


def test_every_step_is_checked_before_anything_is_refused() -> None:
    """Two broken steps report two findings, not just the first.

    W1 reports every invariant a file breaks rather than stopping at one, on
    the grounds that whoever has to fix a catalogue would rather see the whole
    list. Matching extends the same courtesy.
    """
    journey = _edit(_edit(_cuj(_catalogue(), LOOKUP),
                          "search", connector="acme_internal_tool"),
                    "read", entity="widget")

    matched, findings = match_cuj(journey)

    assert matched is None
    assert _codes(findings) == [CONNECTOR_NOT_EMULATED, ENTITY_UNRESOLVED]


def test_one_bad_journey_does_not_refuse_the_others() -> None:
    """A catalogue naming a connector we lack still yields the rest."""
    catalogue = _catalogue()
    broken = _edit(_cuj(catalogue, LOOKUP), "search",
                   connector="acme_internal_tool")

    matched = match_catalogue(_replacing(catalogue, broken))

    assert set(matched.refused) == {NOTES_TO_EPICS, LOOKUP}
    assert [cuj.id for cuj in matched.cujs] == [DRAFTING]
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

    matched, findings = match_cuj(_create_issue())

    assert matched is not None
    assert findings == ()


# ---------------------------------------------------------------------------
# Definitions, and Worldloom changing underneath us.
# ---------------------------------------------------------------------------


def test_each_connector_definition_is_loaded_once_per_run(
        monkeypatch: pytest.MonkeyPatch) -> None:
    """Once per run, not once per step: every journey in one import is
    matched against the same definitions."""
    loads: list[str] = []
    real = connector_definition.load_connector_definition

    def counting(name: str):
        loads.append(name)
        return real(name)

    monkeypatch.setattr(registry, "load_connector_definition", counting)

    match_catalogue(_catalogue())

    assert sorted(loads) == ["confluence", "jira"]


def test_jira_does_not_model_projects_yet() -> None:
    """The day this fails, ``jira.project`` has been added, the example's
    notes-to-epics journey matches exactly as recorded, and the tests above
    that expect it refused should be updated to expect it built."""
    definition = load_connector_definition("jira")

    assert "project" not in definition.entities
    assert "project" not in definition.entity_aliases


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
