"""Sorting matched journeys into what this wave can and cannot build.

The sample catalogue happens to contain one of each interesting case, which
is the point of using it as the anchor:

    cuj_9636dd61a048   creates Jira epics      ──▶  write
    cuj_3ac134e740af   searches and answers    ──▶  lookup
    cuj_80e0d9ce1f1b   drafting, no tools      ──▶  no_world

The rest of the tests cover the edges one happy file cannot: a journey W2
refused, a journey anchored on a cluster that still carries a tool step, and
a capability step claiming to write.
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from worldloom.enterprise_specs import builtin_registry
from worldloom.providers import digest_bytes
from worldloom.studio.construction import compile_project
from worldloom.studio.models import ProjectSpec
from worldloom.telemetry import (
    ANSWER_ONLY_UNSUPPORTED,
    NO_WORLD_NEEDED,
    Group,
    Severity,
    group_for,
    load_catalogue,
    match_catalogue,
    sort_catalogue,
)
from worldloom.telemetry.binding import bind_question, fold_map, prompt_template
from worldloom.telemetry.catalogue import Hardness
from worldloom.telemetry.compile import (
    ARGUMENT_FIELD_UNKNOWN,
    CASES_BELOW_JOURNEYS,
    DEFAULT_CASES,
    DROPPED_FOR_CONFLICT,
    _apportion,
    build_use_case,
    check_with_studio,
    import_catalogue,
    record_shapes,
    share_counts,
)

EXAMPLE = (Path(__file__).parent / "fixtures" / "telemetry" / "conformance"
           / "valid" / "example.json")

WRITES = "cuj_9636dd61a048"
LOOKS_UP = "cuj_3ac134e740af"
DRAFTS = "cuj_80e0d9ce1f1b"

#: The smallest company document ``ProjectSpec`` accepts. The importer never
#: invents one — ``--company`` is required — so tests supply their own.
COMPANY = {"engine": "retail", "identity": {"company_name": "Northwind Grocers"}}


def _catalogue():
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    return catalogue


def _sorted():
    return sort_catalogue(match_catalogue(_catalogue()))


def _cuj(catalogue, cuj_id: str):
    return next(cuj for cuj in catalogue.cujs if cuj.id == cuj_id)


def _codes(findings) -> list[str]:
    return [finding.code for finding in findings]


# ---------------------------------------------------------------------------
# The sample catalogue, one journey per group.
# ---------------------------------------------------------------------------


def test_the_sample_sorts_into_one_write_one_lookup_one_no_world() -> None:
    piles = _sorted()

    assert [cuj.id for cuj in piles.write] == [WRITES]
    assert piles.lookup == (LOOKS_UP,)
    assert piles.no_world == (DRAFTS,)
    assert piles.blocked == ()


def test_every_journey_lands_in_exactly_one_pile() -> None:
    """The four piles must account for the whole catalogue, or one was lost."""
    piles = _sorted()

    assert piles.total == len(_catalogue().cujs) == 3


def test_w2s_findings_are_carried_forward_not_replaced() -> None:
    """Sorting adds to the report; it does not start a new one.

    The fold from W2 must still be visible after sorting, or a reader of the
    final report loses the fact that a step was removed.
    """
    piles = _sorted()

    assert "step_folded" in _codes(piles.report.findings)


# ---------------------------------------------------------------------------
# The two findings, and their deliberately different severities.
# ---------------------------------------------------------------------------


def test_a_lookup_journey_is_refused_as_hard_and_names_what_is_missing() -> None:
    """Reads only. Real behaviour, but Worldloom cannot express it yet."""
    piles = _sorted()
    finding = next(f for f in piles.report.findings
                   if f.code == ANSWER_ONLY_UNSUPPORTED)

    assert finding.severity is Severity.HARD
    assert finding.cuj_id == LOOKS_UP
    assert "C3" in finding.message


def test_a_no_world_journey_is_info_and_leaves_the_import_acceptable() -> None:
    """No tool calls means no world is missing. Nothing is wrong.

    This is the severity that matters most: if it were hard, every catalogue
    containing a drafting journey would fail under --strict, for doing
    nothing more than describing work that needs no connector.
    """
    piles = _sorted()
    finding = next(f for f in piles.report.findings if f.code == NO_WORLD_NEEDED)

    assert finding.severity is Severity.INFO
    assert finding.cuj_id == DRAFTS
    assert finding.detail["anchor"] == "domain_cluster"


# ---------------------------------------------------------------------------
# Edges the sample does not show.
# ---------------------------------------------------------------------------


def test_a_journey_w2_refused_is_blocked_without_a_second_finding() -> None:
    """W2 already said why. Saying it again in other words helps nobody."""
    catalogue = _catalogue()
    broken = _cuj(catalogue, WRITES).model_copy(update={"steps": tuple(
        step.model_copy(update={"connector": "acme_internal_tool"})
        if step.id == "find_notes" else step
        for step in _cuj(catalogue, WRITES).steps)})
    matched = match_catalogue(catalogue.model_copy(update={"cujs": tuple(
        broken if cuj.id == WRITES else cuj for cuj in catalogue.cujs)}))

    piles = sort_catalogue(matched)

    assert piles.blocked == (WRITES,)
    assert piles.write == ()
    assert WRITES not in {f.cuj_id for f in piles.report.findings
                          if f.code in (ANSWER_ONLY_UNSUPPORTED, NO_WORLD_NEEDED)}


def test_a_cluster_anchored_journey_is_no_world_even_with_a_tool_step() -> None:
    """The anchor says how the journey was *identified*, not what it did.

    ``domain_cluster`` means there was no tool signature to name it by. A
    stray tool step does not turn it into a journey we can anchor a world on.
    """
    drafting = _cuj(_catalogue(), DRAFTS)
    with_a_tool = drafting.model_copy(update={"steps": (
        *drafting.steps,
        _cuj(_catalogue(), WRITES).steps[0])})

    assert with_a_tool.anchor == "domain_cluster"
    assert any(step.is_tool_step for step in with_a_tool.steps)
    assert group_for(with_a_tool) is Group.NO_WORLD


def test_a_capability_step_cannot_make_a_journey_a_write() -> None:
    """Only a *tool* step writes. Model-only work changes nothing.

    ``Step`` does not forbid a capability step declaring ``effect="write"``,
    so without the ``is_tool_step`` guard a drafting journey would be sorted
    as a write and then fail to build anything.
    """
    lookup = _cuj(_catalogue(), LOOKS_UP)
    assert group_for(lookup) is Group.LOOKUP

    claiming_to_write = lookup.model_copy(update={"steps": tuple(
        step.model_copy(update={"effect": "write"})
        if not step.is_tool_step else step
        for step in lookup.steps)})

    assert any(s.effect == "write" for s in claiming_to_write.steps)
    assert group_for(claiming_to_write) is Group.LOOKUP


def test_a_journey_with_no_steps_at_all_is_no_world() -> None:
    drafting = _cuj(_catalogue(), DRAFTS).model_copy(update={"steps": ()})

    assert group_for(drafting) is Group.NO_WORLD


# ---------------------------------------------------------------------------
# Building a use case from a write journey.
# ---------------------------------------------------------------------------


def _built_parts():
    """The sample's one write journey, bound and ready to build, plus W2's
    record of the lookup it folded away."""
    data = EXAMPLE.read_bytes()
    catalogue, _ = load_catalogue(data)
    piles = sort_catalogue(match_catalogue(catalogue))
    cuj = piles.write[0]
    folds = fold_map(piles.report)
    question, _ = bind_question(cuj, digest_bytes(data), folds=folds)
    assert question is not None
    return (cuj, prompt_template(question, company_name="Northwind Grocers"),
            question.bindings), folds


def _built():
    """The sample's one write journey, all the way to a ``UseCase``."""
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    industry = catalogue.industry_hint.industry if catalogue.industry_hint else ""
    parts, folds = _built_parts()
    return build_use_case(*parts, industry=industry, folds=folds)


def test_the_write_journey_becomes_a_use_case_studio_accepts() -> None:
    """Construction is the point: if ``EvalSpec`` rejected any of this, the
    call above would have raised rather than returned."""
    case = _built()

    assert case.id == WRITES
    assert case.title == "Meeting notes to Jira epics"
    assert case.construction is not None
    assert case.construction.capability == "meeting-notes-to-jira-epics"
    assert case.scenario is not None


def test_the_question_and_the_world_agree_on_every_value() -> None:
    """The one that matters.

    If the question asks for a project the construction never requires, the
    agent is sent looking for something nobody built — and nothing fails
    loudly. It just scores badly, for a reason no one can see.
    """
    case = _built()
    assert case.construction is not None
    selectors = {requirement.id: requirement.selector
                 for requirement in case.construction.requirements}

    assert selectors["jira.issue"]["project"] == "ACTIONITEM"
    assert "ACTIONITEM" in case.construction.request_template


def test_there_is_one_requirement_per_pair_not_per_step() -> None:
    """Studio refuses a case whose requirements for one (connector, entity)
    disagree about selectors. Merging is the only reliable way to comply."""
    case = _built()
    assert case.construction is not None
    ids = [requirement.id for requirement in case.construction.requirements]

    assert ids == ["confluence.page", "jira.issue"]
    assert len(ids) == len(set(ids))
    # Three steps touch those two pairs.
    assert len([s for s in case.construction.steps if s.connector]) == 3


def test_a_capability_step_becomes_a_transform_with_no_connector() -> None:
    case = _built()
    assert case.construction is not None
    drafting = next(step for step in case.construction.steps
                    if step.id == "draft_epics")

    assert drafting.capability == "generate"
    assert drafting.connector is None
    assert drafting.effect == "transform"


def test_reads_become_sources_and_writes_become_destinations() -> None:
    case = _built()
    assert case.scenario is not None
    workflow = case.scenario.additional_workflows[0]

    assert [(role.connector, role.required_fields)
            for role in workflow.sources] == [
        ("confluence", ("title",)), ("jira", ("project",))]
    assert [role.connector for role in workflow.destinations] == ["jira"]
    assert workflow.destinations[0].entities == ("issue",)


def test_a_folded_lookup_still_counts_as_a_read() -> None:
    """W2 deleted ``find_project``, but people did look the project up.

    So Jira stays a source, and the world must hold issues in that project
    for an agent that checks before it creates. Without the fold record,
    the same journey loses both — which is why the builder takes it.
    """
    parts, folds = _built_parts()

    with_folds = build_use_case(*parts, folds=folds)
    without = build_use_case(*parts)

    assert with_folds.construction is not None
    assert without.construction is not None
    assert "jira.issue" in {r.id for r in with_folds.construction.requirements}
    assert "jira.issue" not in {r.id for r in without.construction.requirements}


def test_a_search_phrase_is_pinned_as_the_title_of_what_was_searched_for() -> None:
    """The question says "store ops notes", so a page titled "store ops" must
    exist. The world builder mints it, plus a near miss on the title."""
    case = _built()
    assert case.construction is not None
    page = next(r for r in case.construction.requirements
                if r.id == "confluence.page")

    assert page.selector["title"] == "store ops"
    assert "store ops" in case.construction.request_template


def test_written_free_text_is_not_pinned() -> None:
    """Text the agent writes into a record is its output, not the world's
    starting state. Only reads are pinned."""
    case = _built()
    assert case.construction is not None
    issue = next(r for r in case.construction.requirements
                 if r.id == "jira.issue")

    assert set(issue.selector) == {"connector", "entity", "project"}


def test_a_journey_that_only_writes_still_builds() -> None:
    """A single "create an issue" reads nothing. ``WorkflowSpec`` refuses a
    workflow with no source and ``EvalSpec`` one with no requirement, so
    before this the import crashed instead of reporting anything. The
    written pair stands in as what must exist beforehand."""
    parts, _ = _built_parts()
    cuj, prompt, _ = parts
    write_only = cuj.model_copy(update={"steps": tuple(
        step.model_copy(update={"depends_on": ()})
        for step in cuj.steps if step.id == "create_epics")})

    case = build_use_case(write_only, prompt, ())

    assert case.construction is not None
    assert case.scenario is not None
    assert [(r.id, r.selector) for r in case.construction.requirements] == [
        ("jira.issue", {"connector": "jira", "entity": "issue"})]
    workflow = case.scenario.additional_workflows[0]
    assert [role.connector for role in workflow.sources] == ["jira"]
    assert compile_project(ProjectSpec(company=COMPANY,
                                       use_cases=(case,))).accepted


def test_difficulty_follows_the_hardness_tally_and_ties_go_harder() -> None:
    parts, folds = _built_parts()
    cuj = parts[0]
    assert build_use_case(*parts, folds=folds).construction.difficulty == "medium"

    tied = cuj.model_copy(update={"hardness": {
        Hardness.HEAD_EASY: 5, Hardness.HARD_FAILURE: 3,
        Hardness.ADVERSARIAL_EDGE: 2}})

    assert build_use_case(tied, *parts[1:]).construction.difficulty == "hard"


def test_candidate_count_is_one_as_studio_does() -> None:
    case = _built()
    assert case.construction is not None

    assert case.construction.candidate_count == 1


def test_arguments_the_definition_does_not_know_are_reported() -> None:
    """Shipped connectors carry no field manifests, and ``queries`` is how a
    page was asked for, not a field it has. So no shape, and a note each."""
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    cuj = next(c for c in catalogue.cujs if c.id == WRITES)

    shape, findings = record_shapes(cuj)

    assert shape.records == ()
    assert {(f.detail["step_id"], f.detail["field"]) for f in findings} == {
        ("find_notes", "queries"), ("read_notes", "page_id"),
        ("find_project", "query")}
    assert all(f.severity is Severity.INFO for f in findings)


def test_a_known_argument_asks_for_a_record_shape() -> None:
    """``title`` is a Confluence query field, so the definition knows it."""
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    cuj = next(c for c in catalogue.cujs if c.id == WRITES)
    titled = cuj.model_copy(update={"steps": tuple(
        step.model_copy(update={"argument_fields": ("title",)})
        if step.id == "find_notes" else step for step in cuj.steps)})

    shape, _ = record_shapes(titled)

    assert [(r.connector, r.entity, r.minimum_populated_fields)
            for r in shape.records] == [("confluence", "page", 1)]


def test_a_process_is_invented_when_no_built_in_covers_every_pair() -> None:
    """``delivery_work`` knows Jira issues but nothing about Confluence.

    Half a match is not a match: a process is what tells Worldloom which
    events a world of this kind produces, so one that does not know about
    Confluence would quietly build a world missing half the journey.
    """
    case = _built()
    assert case.scenario is not None
    invented = case.scenario.additional_processes[0]

    assert invented.name == WRITES
    assert invented.connector_entities == {"confluence": "page", "jira": "issue"}
    # Event kinds borrowed from the closest built-in rather than guessed.
    assert invented.event_kinds == builtin_registry().processes[
        "delivery_work"].event_kinds


def test_the_objective_carries_counts_and_no_customer_text() -> None:
    """Anyone can check it against the catalogue. Nothing else leaks."""
    case = _built()

    assert case.objective == (
        "Reproduce telemetry CUJ cuj_9636dd61a048 (Meeting notes to Jira "
        "epics): 22 sessions, share 0.229.")


def test_the_steps_left_after_folding_are_the_construction_steps() -> None:
    case = _built()
    assert case.construction is not None

    assert [step.id for step in case.construction.steps] == [
        "find_notes", "read_notes", "draft_epics", "create_epics"]


def test_activities_stay_empty_so_a_project_can_hold_the_case() -> None:
    """The design document says "step ids in order". Studio disagrees.

    ``ProjectSpec`` checks every activity against the activity ids of the
    company's process structure, and refuses the whole project when one is
    missing. A step id is never one of those, so following the document made
    every imported case unbuildable — which no test noticed until a real
    ``ProjectSpec`` was constructed.
    """
    case = _built()

    assert case.activities == ()
    project = ProjectSpec(company=COMPANY, use_cases=(case,))
    assert project.use_cases[0].id == WRITES


# ---------------------------------------------------------------------------
# Sharing out the question count.
# ---------------------------------------------------------------------------


def _counts(cases: int = DEFAULT_CASES):
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    piles = sort_catalogue(match_catalogue(catalogue))
    return share_counts(piles, catalogue, cases=cases)


def test_the_sample_gives_every_question_to_its_one_write_journey() -> None:
    counts, findings = _counts()

    assert findings == ()
    assert counts.total == DEFAULT_CASES
    assert [a.cuj_id for a in counts.allocations] == [WRITES]
    assert counts.allocations[0].count == 200


def test_share_lost_reports_the_traffic_no_question_represents() -> None:
    """Rescaling hides the loss by construction: the shares always sum to 1
    afterwards, whatever was dropped. Two of the sample's three journeys are
    not built, and that is half its traffic."""
    counts, _ = _counts()

    assert counts.share_lost == pytest.approx(0.323 + 0.188)
    assert counts.allocations[0].original_share == pytest.approx(0.229)
    assert counts.allocations[0].rescaled_share == pytest.approx(1.0)


def test_the_counts_add_up_and_nobody_gets_zero() -> None:
    """The design document asks for both, and the two can contradict.

    Largest-remainder rounding alone gives a=5 b=3 c=2 d=0, summing to 10.
    Raising d to 1 would make 11. The repayment takes that question back
    from the largest count, which is the one it costs least.
    """
    weights = {"a": 0.44, "b": 0.31, "c": 0.24, "d": 0.01}

    counts = _apportion(weights, 10)

    assert counts == {"a": 4, "b": 3, "c": 2, "d": 1}
    assert sum(counts.values()) == 10
    assert min(counts.values()) >= 1


def test_a_long_tail_still_adds_up_exactly() -> None:
    """The case that actually bites: forty journeys, most under 1/N."""
    weights = {f"cuj_{index:02d}": (0.6 if index == 0 else 0.4 / 39)
               for index in range(40)}

    counts = _apportion(weights, 200)

    assert sum(counts.values()) == 200
    assert min(counts.values()) >= 1
    assert len(counts) == 40


def test_asking_for_fewer_questions_than_journeys_is_refused() -> None:
    """Capping would drop journeys with no finding, which is the one thing
    this importer is built not to do."""
    weights = {f"c{index}": 0.25 for index in range(4)}
    assert sum(_apportion(weights, 4).values()) == 4

    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    piles = sort_catalogue(match_catalogue(catalogue))
    counts, findings = share_counts(piles, catalogue, cases=0)

    assert counts.allocations == ()
    assert findings[0].code == CASES_BELOW_JOURNEYS
    assert findings[0].severity is Severity.HARD


def test_no_journeys_built_is_not_this_functions_problem() -> None:
    """Nothing to divide. Whether that should stop the run is the command
    line's decision, so no finding is raised here."""
    catalogue, _ = load_catalogue(EXAMPLE.read_bytes())
    piles = sort_catalogue(match_catalogue(catalogue)).model_copy(
        update={"write": ()})

    counts, findings = share_counts(piles, catalogue)

    assert findings == ()
    assert counts.total == 0
    assert counts.share_lost == pytest.approx(0.229 + 0.323 + 0.188)


def test_ties_are_broken_by_journey_id_so_the_split_never_drifts() -> None:
    """Four identical weights, three questions. Someone must miss out, and
    it must be the same someone every run."""
    weights = {"cuj_d": 0.25, "cuj_b": 0.25, "cuj_a": 0.25, "cuj_c": 0.25}

    first = _apportion(weights, 7)
    again = _apportion(dict(reversed(list(weights.items()))), 7)

    assert first == again
    assert sum(first.values()) == 7
    # The extra three go to the lowest ids.
    assert [key for key, value in sorted(first.items()) if value == 2] == [
        "cuj_a", "cuj_b", "cuj_c"]


def test_the_allocated_count_reaches_the_use_case() -> None:
    """The split is only worth computing if the case carries it."""
    counts, _ = _counts(cases=50)
    case = _built()
    allocated = next(a for a in counts.allocations if a.cuj_id == case.id)

    assert build_use_case(
        *_built_parts()[0], count=allocated.count).count == 50


# ---------------------------------------------------------------------------
# Studio's checks, and the whole import.
# ---------------------------------------------------------------------------


def _imported(data: bytes | None = None, *, cases: int = DEFAULT_CASES):
    return import_catalogue(data if data is not None else EXAMPLE.read_bytes(),
                            COMPANY, cases=cases)


def _pinned(case_id: str, status: str):
    """The sample's case, renamed, with its Jira issue pinned to one record in
    one state. Importer output never does this — it is the only way to make
    Studio's cross-case conflict rule fire."""
    result = _imported()
    assert result.project is not None
    base = result.project.use_cases[0]
    assert base.construction is not None
    requirements = tuple(
        requirement.model_copy(update={"selector": {
            **requirement.selector, "id": "OPS-1", "status": status}})
        if requirement.id == "jira.issue" else requirement
        for requirement in base.construction.requirements)
    return base.model_copy(update={
        "id": case_id,
        "construction": base.construction.model_copy(update={
            "id": case_id, "requirements": requirements})})


def test_the_sample_imports_end_to_end() -> None:
    result = _imported()

    assert result.project is not None
    assert [(case.id, case.count) for case in result.project.use_cases] == [
        (WRITES, DEFAULT_CASES)]
    assert result.counts.share_lost == pytest.approx(0.511)
    assert [finding.code for finding in result.report.findings] == [
        "step_folded", ANSWER_ONLY_UNSUPPORTED, NO_WORLD_NEEDED,
        ARGUMENT_FIELD_UNKNOWN, ARGUMENT_FIELD_UNKNOWN]


def test_studio_accepts_what_the_importer_built() -> None:
    """The reason this stage exists: ``studio run`` must never find a problem
    the import could have reported."""
    result = _imported()
    assert result.project is not None

    plan = compile_project(result.project)

    assert plan.accepted
    assert plan.findings == ()


def test_importer_output_cannot_trigger_studios_conflict_rule() -> None:
    """Studio only compares demands that share an identity key, and the
    importer never writes one — an id in a selector would be an id in the
    question. So the drop-the-smaller-share path below is unreachable from a
    real catalogue today.

    If this fails, a binding rule has started pinning records, and that path
    has just become live. Check it was meant to.
    """
    result = _imported()
    assert result.project is not None
    identity_keys = {"id", "entity_id", "record_id", "artifact_id", "object_id"}

    for case in result.project.use_cases:
        assert case.construction is not None
        for requirement in case.construction.requirements:
            assert not identity_keys & requirement.selector.keys()


def test_a_clash_drops_the_journey_fewer_people_performed() -> None:
    small, large = "cuj_aaaaaaaaaaaa", "cuj_bbbbbbbbbbbb"

    kept, findings = check_with_studio(
        COMPANY, (_pinned(small, "done"), _pinned(large, "open")),
        {small: 0.10, large: 0.30})

    assert [case.id for case in kept] == [large]
    assert [finding.code for finding in findings] == [DROPPED_FOR_CONFLICT]
    assert findings[0].severity is Severity.HARD
    assert findings[0].detail == {
        "kept": large, "dropped": small,
        "reason": findings[0].detail["reason"]}
    assert "OPS-1" in findings[0].detail["reason"]


def test_a_tie_drops_the_higher_id_so_the_result_never_drifts() -> None:
    low, high = "cuj_aaaaaaaaaaaa", "cuj_bbbbbbbbbbbb"

    kept, _ = check_with_studio(
        COMPANY, (_pinned(high, "open"), _pinned(low, "done")),
        {low: 0.20, high: 0.20})

    assert [case.id for case in kept] == [low]


def test_a_case_outside_the_clash_survives_it() -> None:
    """Only the clashing pair is touched."""
    result = _imported()
    assert result.project is not None
    bystander = result.project.use_cases[0]

    kept, findings = check_with_studio(
        COMPANY,
        (_pinned("cuj_aaaaaaaaaaaa", "done"), _pinned("cuj_bbbbbbbbbbbb", "open"),
         bystander),
        {"cuj_aaaaaaaaaaaa": 0.1, "cuj_bbbbbbbbbbbb": 0.3, WRITES: 0.229})

    assert {case.id for case in kept} == {"cuj_bbbbbbbbbbbb", WRITES}
    assert [finding.cuj_id for finding in findings] == ["cuj_aaaaaaaaaaaa"]


def test_a_case_studio_refuses_alone_is_removed_with_studios_own_code() -> None:
    """Studio's code is kept exactly, so it reads the same here as it would
    from ``studio run``."""
    result = _imported()
    assert result.project is not None
    broken = result.project.use_cases[0].model_copy(update={
        "id": "cuj_cccccccccccc", "construction": None})

    kept, findings = check_with_studio(
        COMPANY, (result.project.use_cases[0], broken),
        {WRITES: 0.229, "cuj_cccccccccccc": 0.5})

    assert [case.id for case in kept] == [WRITES]
    assert [finding.code for finding in findings] == [
        "construction_contract_missing"]
    assert findings[0].cuj_id == "cuj_cccccccccccc"


def test_a_write_journey_without_phrasings_borrows_a_built_in_template() -> None:
    """No real wording survived, so the closest built-in workflow speaks for
    it. The journey is still built — and the report says whose words those
    are, so nobody mistakes them for the customer's."""
    payload = json.loads(EXAMPLE.read_text())
    next(cuj for cuj in payload["cujs"] if cuj["id"] == WRITES)["phrasings"] = []

    result = _imported(json.dumps(payload).encode())
    defaults = [finding for finding in result.report.findings
                if finding.code == "phrasing_default_used"]

    assert result.project is not None
    assert len(defaults) == 1
    assert defaults[0].severity is Severity.INFO
    assert defaults[0].detail["workflow"] in builtin_registry().workflows


def test_the_whole_budget_goes_to_whatever_survives() -> None:
    result = _imported(cases=37)

    assert result.project is not None
    assert sum(case.count for case in result.project.use_cases) == 37


# ---------------------------------------------------------------------------
# The design document's §8 tests 3 and 8.
# ---------------------------------------------------------------------------


GOLDEN = (Path(__file__).parent / "fixtures" / "telemetry" / "golden"
          / "cuj_9636dd61a048.json")


def _golden_text() -> str:
    result = _imported()
    assert result.project is not None
    case = result.project.use_cases[0]
    return json.dumps(case.model_dump(mode="json"), indent=2, sort_keys=True,
                      ensure_ascii=False) + "\n"


def test_the_write_journey_produces_exactly_the_reviewed_use_case() -> None:
    """§8 test 3: compared as a golden JSON file, byte for byte.

    The file is our output, reviewed against the design document's §7. It
    differs from §7 only where a decision was made: ``issue`` rather than
    ``epic``, the seeded ``ACTIONITEM`` rather than the illustrative
    ``STOREOPS``, §5.5's prefix and suffix on the question, requirement ids
    named for their pair, and no failure modes yet (W5).

    A change here is a change to every imported corpus. If it is intended,
    review the diff, then regenerate with
    ``WORLDLOOM_UPDATE_GOLDEN=1 pytest tests/test_telemetry_compile.py``.
    """
    actual = _golden_text()
    if os.environ.get("WORLDLOOM_UPDATE_GOLDEN") == "1":
        GOLDEN.write_text(actual, encoding="utf-8")

    assert actual == GOLDEN.read_text(encoding="utf-8"), (
        "the imported use case no longer matches the reviewed golden file; "
        "see this test's docstring")


def test_importing_twice_gives_identical_bytes() -> None:
    """§8 test 8. Nothing may depend on the clock, the machine, or the order a
    dictionary happened to be built in."""
    first, second = _imported(), _imported()

    assert first.model_dump_json() == second.model_dump_json()
