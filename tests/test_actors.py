"""The actor runtime: bounded employees acting through typed tools.

Organised by the exit gates in ``docs/actor-simulation.md``, because that is what
these tests are for — each one is a gate stated as an assertion rather than as a
paragraph. The centrepiece is
``test_the_actor_episode_replays_with_the_provider_unavailable``: an episode that
cannot regenerate from its ledger is not a corpus, it is one run's output.

The rejection tests matter as much as the happy path. A policy layer that has
never refused anything is decoration, so every one of the roadmap's §A2 cases —
the business partner who cannot post a journal, the engineer who cannot approve
their own change — is exercised as a *rejection with a named rule*, not as an
absence.
"""

from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.actors import (
    ActorProviderError,
    ScriptedActorProvider,
    UnreachableActorProvider,
    scheduler,
)
from worldloom.actors import observation as observation_module
from worldloom.actors import policy as policy_module
from worldloom.actors.models import ActorAction, ToolResult
from worldloom.actors.runtime import run_episode
from worldloom.actors.tools import base as tool_base
from worldloom.ids import Minter

PERIOD = "2026-03"


def episode_world(provider=None, ledger=()) -> World:
    """A retail close with the incident forced on, driven by actors."""
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(
            period=PERIOD,
            include_operational_incident=True,
            actors=provider if provider is not None else ScriptedActorProvider(),
            actor_ledger=ledger,
        )
    )


@pytest.fixture(scope="module")
def acted() -> World:
    return episode_world()


# ---------------------------------------------------------------------------
# A0 — the boundary, and replay
# ---------------------------------------------------------------------------


def test_the_actor_episode_replays_with_the_provider_unavailable(acted: World) -> None:
    """The gate. Same seed plus the ledger, no provider, byte-identical output.

    Compared through ``model_dump`` rather than object identity because the
    execution ledger is what *ships*: a replay that produced equal objects and
    different JSON would still fail CI's directory diff, and would do it far
    from here.
    """
    replayed = episode_world(UnreachableActorProvider(), ledger=acted._ledger)

    assert [f.id for f in replayed.facts] == [f.id for f in acted.facts]
    assert [e.id for e in replayed.events] == [e.id for e in acted.events]
    assert [
        entry.model_dump(mode="json") for entry in replayed.actor_ledger
    ] == [entry.model_dump(mode="json") for entry in acted.actor_ledger]
    assert [
        o.model_dump(mode="json") for o in replayed.observations
    ] == [o.model_dump(mode="json") for o in acted.observations]


def test_a_replay_missing_its_ledger_fails_loudly() -> None:
    """A replay that quietly regenerated would not be a replay."""
    with pytest.raises(ActorProviderError, match="Replay is incomplete"):
        episode_world(UnreachableActorProvider(), ledger=())


def test_the_scripted_provider_is_never_asked_on_replay(acted: World) -> None:
    provider = ScriptedActorProvider()
    episode_world(provider, ledger=acted._ledger)
    assert provider.calls == 0


def test_every_call_is_in_the_execution_ledger_including_the_refused(acted: World) -> None:
    entries = list(acted.actor_ledger)
    assert entries, "the episode produced no tool calls at all"
    assert any(not entry.result.accepted for entry in entries), (
        "no refusals recorded — an execution ledger that only holds successes "
        "cannot show that the bounds bind"
    )
    assert [entry.sequence for entry in entries] == list(range(len(entries)))


def test_a_rejected_result_cannot_carry_state() -> None:
    """The residue rule, enforced by the type rather than remembered by a caller."""
    with pytest.raises(ValueError, match="cannot have changed anything"):
        ToolResult(accepted=False, fact_ids=["FACT-0001"], rejection_reason="nope")
    with pytest.raises(ValueError, match="name the rule"):
        ToolResult(accepted=False)


def test_an_abstention_must_say_why() -> None:
    with pytest.raises(ValueError, match="silent no-op"):
        ActorAction(invocation_id="INV-0001", tool_name=None)


# ---------------------------------------------------------------------------
# A1 — epistemic observations
# ---------------------------------------------------------------------------


def test_two_actors_on_one_incident_see_materially_different_facts(acted: World) -> None:
    """The §A1 gate. Same failure, same minute, different worlds."""
    first: dict[str, frozenset[str]] = {}
    last: dict[str, frozenset[str]] = {}
    for entry in acted.actor_ledger:
        seen = frozenset(entry.observation.visible_fact_ids)
        first.setdefault(entry.invocation.role_key, seen)
        last[entry.invocation.role_key] = seen

    partner_role = next(key for key in first if key.endswith("_bp"))

    # Woken by the same event, at the same minute, three roles are already
    # looking at three different incidents.
    assert first["platform_senior"] != first[partner_role]
    assert first["svc_desk"] != first["platform_senior"]

    # And by the end each holds something the other cannot reach. That is the
    # two-sided form, and it is the one the gate is really about: the engineer
    # never sees the ledger position, the business partner never sees the
    # dependency graph, and neither can cite what it did not see. Checked at the
    # end rather than at the first turn because at the first turn the difference
    # is mostly that less had happened to one of them.
    engineer = last["platform_senior"]
    partner = last[partner_role]
    assert engineer - partner
    assert partner - engineer

    # And the difference is along the domain boundary rather than incidental.
    # Note what the partner's exclusive set actually contains on the day of the
    # outage: the close calendar and the dependency, not the month's figures —
    # those do not exist yet on day one, which is the whole reason the close is
    # worth escalating about.
    def domains(ids: frozenset[str]) -> set[str]:
        return {policy_module.domain_of(acted.facts.by_id(i).kind) for i in ids}

    assert "finance" in domains(partner - engineer)
    assert {"operations", "engineering"} & domains(engineer - partner)


def test_no_actor_ever_cited_a_fact_it_had_not_observed(acted: World) -> None:
    for entry in acted.actor_ledger:
        if not entry.result.accepted:
            continue
        observed = set(entry.observation.visible_fact_ids)
        for name, value in entry.action.arguments.items():
            if not name.endswith(("fact_id", "fact_ids")):
                continue
            cited = [value] if isinstance(value, str) else (value or [])
            assert set(cited) <= observed, (
                f"{entry.id} cited {sorted(set(cited) - observed)} unobserved"
            )


def test_nobody_learns_a_fact_before_it_was_true(acted: World) -> None:
    facts = {fact.id: fact for fact in acted.facts}
    for observation in acted.observations:
        assert observation.learned_at >= facts[observation.fact_id].valid_from


def test_learning_a_fact_is_later_than_the_fact(acted: World) -> None:
    """A world where knowledge is instantaneous cannot pose a temporal question."""
    delayed = [
        o
        for o in acted.observations
        if o.learned_at > acted.facts.by_id(o.fact_id).valid_from
    ]
    assert delayed, "every observation was immediate; the channels are not doing anything"


def test_a_departed_employee_observes_nothing() -> None:
    world = RetailWorld(seed=8128).build()
    person = world.people.by_id(world._roles["controller"])
    gone = replace(
        world,
        _people=tuple(
            p.model_copy(update={"left": world._facts[0].valid_from}) if p.id == person.id else p
            for p in world._people
        ),
    )
    policy = policy_module.policy_for("controller")
    assert policy is not None
    assert (
        observation_module.observations_for(
            gone,
            actor_id=person.id,
            policy=policy,
            at=gone._facts[-1].valid_from,
            minter=Minter(),
        )
        == ()
    )


# ---------------------------------------------------------------------------
# A2 — role policy and decision rights
# ---------------------------------------------------------------------------


def refuse(world: World, *, role_key: str, tool: str, arguments: dict) -> ToolResult:
    """Run one tool call for one role and return whatever the runtime decided.

    Built against the real world and the real policies rather than a stub, so a
    permission test cannot pass because the fixture was wrong about who somebody
    is.
    """
    from worldloom.actors.runtime import _execute, _visible_intents

    policy = policy_module.policy_for(role_key)
    assert policy is not None, f"{role_key} has no policy"
    actor_id = world._roles[role_key]
    at = world._facts[-1].valid_from
    observed = observation_module.project(
        world,
        actor_id=actor_id,
        role_key=role_key,
        policy=policy,
        at=at,
        trigger_event_id=None,
        observations=observation_module.observations_for(
            world, actor_id=actor_id, policy=policy, at=at, minter=Minter()
        ),
        messages=(),
        tasks=(),
        minter=Minter(),
        artifact_ids=_visible_intents(world, actor_id=actor_id, at=at),
    )
    ctx = tool_base.ToolContext(
        world=world,
        minter=Minter(),
        actor=world.people.by_id(actor_id),
        role_key=role_key,
        policy=policy,
        observation=observed,
        at=at,
        period=PERIOD,
        roles=dict(world._roles),
    )
    result, _ = _execute(tool, arguments, ctx, seen={})
    return result


def test_a_finance_business_partner_may_request_a_journal_but_not_post_one(acted: World) -> None:
    """The §A2 gate, first half."""
    partner = next(key for key in acted._roles if key.endswith("_bp"))
    posted = refuse(
        acted,
        role_key=partner,
        tool="post_journal",
        arguments={"request_fact_id": acted._facts[0].id, "amount": 10.0},
    )
    assert not posted.accepted
    assert "not_authorised" in (posted.rejection_reason or "")
    assert "prohibited by policy" in (posted.rejection_reason or "")

    policy = policy_module.policy_for(partner)
    assert policy is not None
    assert policy.permits("request_journal")


def test_an_engineer_may_propose_a_change_but_not_approve_one(acted: World) -> None:
    """The §A2 gate, second half."""
    proposal = next(f for f in acted.facts if f.kind == "ops.change_proposal")
    result = refuse(
        acted,
        role_key="platform_senior",
        tool="approve_change",
        arguments={"proposal_fact_id": proposal.id, "note": "looks fine to me"},
    )
    assert not result.accepted
    assert "not_authorised" in (result.rejection_reason or "")

    policy = policy_module.policy_for("platform_senior")
    assert policy is not None
    assert policy.permits("propose_change")


def test_a_refused_call_changed_nothing(acted: World) -> None:
    """A world in which the refusals had left residue would not validate.

    Checked directly as well, because the interesting failure is a tool that
    mutates *before* raising and a validator that only reads the finished corpus
    cannot see the difference.
    """
    before = len(acted.facts)
    refuse(
        acted,
        role_key="svc_desk",
        tool="escalate_major_incident",
        arguments={
            "service_id": acted._roles["svc_valuation"],
            "justification": "it feels big",
            "cite_fact_ids": [],
        },
    )
    assert len(acted.facts) == before


def test_a_decision_needs_standing_not_merely_a_tool(acted: World) -> None:
    """`approve_artifact` is granted to the CFO; the decision right is separate."""
    right = policy_module.decision_right("close_schedule")
    assert right is not None
    assert right.accountable_role == "controller"
    assert "cfo" in right.approver_roles
    assert policy_module.policy_for("platform_lead") is not None
    assert not policy_module.policy_for("platform_lead").permits("decide_close_schedule")


def test_a_role_without_a_policy_cannot_act() -> None:
    """A missing policy means "not an actor", never "may do anything"."""
    assert policy_module.policy_for("merch_analyst") is None
    assert policy_module.policy_for("audit") is None


def test_business_unit_partners_share_one_policy() -> None:
    assert policy_module.policy_role("digital_bp") == "finance_business_partner"
    assert policy_module.policy_role("food_bp") == "finance_business_partner"


# ---------------------------------------------------------------------------
# A3 — the typed tool runtime
# ---------------------------------------------------------------------------


def test_every_registered_tool_describes_itself() -> None:
    names = tool_base.available()
    assert len(names) >= 20
    for name in names:
        spec = tool_base.get(name).spec()
        assert spec.summary, f"{name} has no summary"
        assert spec.domain
        for argument in spec.arguments:
            assert argument.description, f"{name}.{argument.name} is undescribed"
            if argument.kind == "enum":
                assert argument.choices, f"{name}.{argument.name} is an enum with no choices"


def test_an_actor_is_only_shown_tools_its_policy_grants() -> None:
    policy = policy_module.policy_for("svc_desk")
    assert policy is not None
    offered = {spec.name for spec in tool_base.catalogue(policy)}
    assert "create_incident" in offered
    assert "escalate_major_incident" not in offered
    assert "post_journal" not in offered


def test_schema_rejects_the_wrong_shape(acted: World) -> None:
    unknown = refuse(
        acted,
        role_key="svc_desk",
        tool="create_incident",
        arguments={"service_id": "SVC-0001", "priority": "P2", "summary": "x",
                   "evidence_fact_ids": [], "colour": "blue"},
    )
    assert "unknown_argument" in (unknown.rejection_reason or "")

    bad_enum = refuse(
        acted,
        role_key="svc_desk",
        tool="create_incident",
        arguments={"service_id": "SVC-0001", "priority": "P9", "summary": "x",
                   "evidence_fact_ids": []},
    )
    assert "bad_argument" in (bad_enum.rejection_reason or "")

    missing = refuse(
        acted, role_key="svc_desk", tool="create_incident", arguments={"priority": "P2"}
    )
    assert "missing_argument" in (missing.rejection_reason or "")


def test_a_confirmed_cause_requires_evidence_the_actor_gathered(acted: World) -> None:
    """The evidence gate. A hunch is free; a confirmation is not."""
    cause = next(f for f in acted.facts if f.kind == "ops.cause" and not f.is_superseded)
    result = refuse(
        acted,
        role_key="platform_senior",
        tool="record_hypothesis",
        arguments={
            "service_id": acted._roles["svc_valuation"],
            "status": "confirmed",
            "assessment": "definitely the mapping",
            "cite_fact_ids": [cause.id],
        },
    )
    assert not result.accepted
    assert "insufficient_evidence" in (result.rejection_reason or "")

    hunch = refuse(
        acted,
        role_key="platform_senior",
        tool="record_hypothesis",
        arguments={
            "service_id": acted._roles["svc_valuation"],
            "status": "hypothesis",
            "assessment": "might be the mapping",
            "cite_fact_ids": [cause.id],
        },
    )
    assert hunch.accepted, hunch.rejection_reason


def test_a_tool_cannot_cite_a_fact_the_caller_never_saw(acted: World) -> None:
    unseen = next(
        f.id
        for f in acted.facts
        if f.kind.startswith("financial.gross_profit")
    )
    result = refuse(
        acted,
        role_key="svc_desk",
        tool="add_work_note",
        arguments={
            "service_id": acted._roles["svc_valuation"],
            "note": "for the record",
            "cite_fact_ids": [unseen],
        },
    )
    assert "unobserved_fact" in (result.rejection_reason or "")


def test_calling_a_mutating_tool_twice_changes_nothing_twice(acted: World) -> None:
    """Idempotency, and the fact that reads are deliberately exempt from it."""
    incident = tool_base.get("create_incident")
    read = tool_base.get("read_ledger")

    class _Ctx:
        actor = type("P", (), {"id": "PERSON-0001"})()

    assert incident.idempotency_key({"service_id": "SVC-0001"}, _Ctx()) is not None
    # A read at 09:00 and the same read at 16:40 are different questions. Caching
    # them together is how one actor silently receives another's answer.
    assert read.idempotency_key({"subject_id": "CO-0001"}, _Ctx()) is None


def test_one_failure_produces_one_incident(acted: World) -> None:
    states = [f for f in acted.facts if f.kind == "ops.incident_state"]
    opened = [f for f in states if f.text_value and f.text_value.startswith("triage")]
    assert len(opened) == 1


def test_an_artifact_may_not_be_stuffed_with_the_whole_ledger(acted: World) -> None:
    """The narrative fan-out bound, as a precondition rather than a guideline."""
    from worldloom.actors.tools.artifacts import MAX_CITED_FACTS

    everything = [f.id for f in acted.facts][: MAX_CITED_FACTS + 5]
    result = refuse(
        acted,
        role_key="controller",
        tool="draft_artifact",
        arguments={
            "artifact_type": "working_note",
            "cite_fact_ids": everything,
            "rationale": "all of it",
        },
    )
    assert "too_many_facts" in (result.rejection_reason or "")


# ---------------------------------------------------------------------------
# A4 — the scheduler
# ---------------------------------------------------------------------------


def test_the_same_world_and_seed_produce_the_same_actor_queue() -> None:
    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    first = scheduler.queue(world, roles=world._roles)
    second = scheduler.queue(world, roles=world._roles)
    assert first == second
    assert first, "no activation at all — the routing table matches nothing"
    assert [a.at for a in first] == sorted(a.at for a in first)


def test_each_event_wakes_each_role_once(acted: World) -> None:
    fired = [(e.invocation.trigger_event_id, e.invocation.role_key) for e in acted.actor_ledger]
    per_invocation = {e.invocation.id: (e.invocation.trigger_event_id, e.invocation.role_key)
                      for e in acted.actor_ledger}
    assert len(set(per_invocation.values())) == len(per_invocation), (
        "one (event, role) pair was activated twice — an actor scheduled itself"
    )
    assert fired


def test_a_route_may_only_require_a_condition_the_scheduler_knows() -> None:
    for route in scheduler.ROUTES:
        for condition in route.required_conditions:
            assert condition in scheduler.CONDITIONS


def test_an_actor_woken_by_an_event_can_see_that_events_facts(acted: World) -> None:
    """Being paged is how the service desk finds out at all."""
    first = next(e for e in acted.actor_ledger if e.invocation.role_key == "svc_desk")
    symptom = next(f for f in acted.facts if f.kind == "ops.feed_status")
    assert symptom.id in first.observation.visible_fact_ids


# ---------------------------------------------------------------------------
# A5 — the bounded episode
# ---------------------------------------------------------------------------


def test_the_episode_runs_the_whole_flow(acted: World) -> None:
    """Pipeline failure → incident → investigation → cause → delay → summary → remediation."""
    tools = [e.action.tool_name for e in acted.actor_ledger if e.result.accepted]
    for expected in (
        "create_incident",
        "inspect_dependencies",
        "record_hypothesis",
        "request_evidence",
        "assign_incident",
        "escalate_close_issue",
        "decide_close_schedule",
        "create_remediation_issue",
        "approve_change",
        "draft_artifact",
        "publish_runbook",
    ):
        assert expected in tools, f"the episode never called {expected}"


def test_the_episode_produces_the_documents_the_close_needs(acted: World) -> None:
    planned = {intent.artifact_type for intent in acted.artifact_intents}
    assert {
        "servicenow_incident",
        "jira_issues",
        "confluence_page",
        "incident_rca",
        "knowledge_article",
        "working_note",
        "executive_summary",
        # Still deterministic: a close produces these whether or not anything
        # went wrong, so nobody decides to write them.
        "close_calendar",
        "finance_workbook",
        "cfo_variance_memo",
    } <= planned


def test_the_incident_documents_were_written_by_the_people_who_did_the_work(
    acted: World,
) -> None:
    authors = {
        intent.artifact_type: intent.author_id
        for intent in acted.artifact_intents
    }
    assert authors["servicenow_incident"] == acted._roles["svc_desk"]
    assert authors["incident_rca"] == acted._roles["platform_senior"]
    assert authors["jira_issues"] == acted._roles["platform_lead"]
    assert authors["executive_summary"] == acted._roles["cfo"]
    assert authors["working_note"] == acted._roles["controller"]


def test_the_canonical_outcome_is_unchanged_by_who_wrote_it_down() -> None:
    """The §A5 gate. Actors change the records, never the world's physics."""
    plain = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    acted = episode_world()

    def canonical(world: World) -> list[tuple[str, str]]:
        return [
            (f.kind, f.text_value or f"{f.value.amount}")  # type: ignore[union-attr]
            for f in world.facts
            if f.kind in {"ops.cause", "close.status", "close.delay", "ops.feed_status"}
        ]

    assert canonical(acted) == canonical(plain)


def test_the_executive_summary_omits_the_control_failure(acted: World) -> None:
    """An omission that is a citation not made, rather than a rule in a template."""
    summary = next(i for i in acted.artifact_intents if i.artifact_type == "executive_summary")
    review = next(i for i in acted.artifact_intents if i.artifact_type == "incident_rca")
    classification = next(
        f.id for f in acted.facts if f.kind == "ops.root_cause_classification"
    )
    assert classification in review.required_fact_ids
    assert classification not in summary.required_fact_ids


def test_the_close_decision_names_its_evidence_and_its_approver(acted: World) -> None:
    decision = next(f for f in acted.facts if f.kind == "close.decision")
    entry = next(
        e
        for e in acted.actor_ledger
        if e.action.tool_name == "decide_close_schedule" and e.result.accepted
    )
    assert decision.id in entry.result.fact_ids
    assert entry.action.arguments["cite_fact_ids"]
    assert "Approved by" in (decision.text_value or "")


def test_remediation_separates_the_control_fix_from_the_detection_fix(acted: World) -> None:
    fixes = {task.addresses for task in acted.tasks if task.kind == "remediation"}
    assert fixes == {"control", "detection"}
    for task in acted.tasks:
        if task.kind == "remediation":
            assert task.owner_id, f"{task.id} has no owner"


def test_the_world_stays_coherent(acted: World) -> None:
    acted.validate().raise_if_failed()


def test_an_actor_corpus_renders_and_still_agrees_with_itself(tmp_path) -> None:
    from worldloom.narrative import DeterministicProvider

    world = episode_world().narrate(DeterministicProvider())
    world = world.render("markdown", "jira", "confluence", "servicenow")
    world.validate().raise_if_failed()
    world.export(tmp_path / "corpus")
    reloaded = World.load(tmp_path / "corpus")
    assert len(reloaded.actor_ledger) == len(world.actor_ledger)
    assert len(reloaded.observations) == len(world.observations)
    reloaded.validate().raise_if_failed()


# ---------------------------------------------------------------------------
# A10 — evaluation and the actor validators
# ---------------------------------------------------------------------------


def test_the_episode_adds_question_families_the_plain_corpus_cannot_pose(
    acted: World,
) -> None:
    plain = RetailWorld(seed=8128).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )
    assert len(acted.evaluations) > len(plain.evaluations)
    questions = " ".join(case.question for case in acted.evaluations)
    for probe in ("approved that decision", "before the", "who owns it"):
        assert probe in questions, f"no case asks about {probe!r}"


def test_every_generated_case_is_answerable_from_a_document(acted: World) -> None:
    carried: set[str] = set()
    for intent in acted.artifact_intents:
        carried.update(intent.required_fact_ids)
    for case in acted.evaluations:
        assert set(case.expected_fact_ids) <= carried, case.id


def test_the_validator_catches_a_citation_of_something_unobserved(acted: World) -> None:
    """Edit the shipped ledger, and the check has to notice.

    Against the corpus rather than the runtime on purpose: the runtime enforces
    this while it runs, but what a reader is handed is a directory, and a
    directory can be edited.
    """
    entry = next(
        e
        for e in acted.actor_ledger
        if e.result.accepted and e.action.arguments.get("cite_fact_ids")
    )
    tampered = entry.model_copy(
        update={
            "action": entry.action.model_copy(
                update={
                    "arguments": {
                        **entry.action.arguments,
                        "cite_fact_ids": ["FACT-0001", "FACT-0002"],
                    }
                }
            )
        }
    )
    broken = replace(
        acted,
        _actor_ledger=tuple(
            tampered if e.id == entry.id else e for e in acted._actor_ledger
        ),
    )
    codes = {v.code for v in broken.validate().violations}
    assert "cites_unobserved_fact" in codes


def test_the_validator_catches_a_tool_call_beyond_a_roles_authority(acted: World) -> None:
    entry = next(e for e in acted.actor_ledger if e.result.accepted and e.action.tool_name)
    tampered = entry.model_copy(
        update={
            "invocation": entry.invocation.model_copy(update={"role_key": "svc_desk"}),
            "action": entry.action.model_copy(update={"tool_name": "post_journal"}),
        }
    )
    broken = replace(
        acted,
        _actor_ledger=tuple(
            tampered if e.id == entry.id else e for e in acted._actor_ledger
        ),
    )
    codes = {v.code for v in broken.validate().violations}
    assert "tool_exceeds_authority" in codes


def test_the_validator_catches_knowledge_that_predates_its_fact(acted: World) -> None:
    from datetime import timedelta

    observation = acted._observations[0]
    tampered = observation.model_copy(
        update={"learned_at": observation.learned_at - timedelta(days=400)}
    )
    broken = replace(
        acted,
        _observations=(tampered, *acted._observations[1:]),
    )
    codes = {v.code for v in broken.validate().violations}
    assert "premature_observation" in codes


def test_every_mutation_has_exactly_one_accepted_tool_call_behind_it(acted: World) -> None:
    claimed: dict[str, str] = {}
    for entry in acted.actor_ledger:
        if not entry.result.accepted:
            continue
        for created in (
            *entry.result.fact_ids,
            *entry.result.event_ids,
            *entry.result.artifact_intent_ids,
        ):
            assert created not in claimed, f"{created} claimed twice"
            claimed[created] = entry.id
    assert claimed


# ---------------------------------------------------------------------------
# Bounds
# ---------------------------------------------------------------------------


def test_no_invocation_exceeded_its_tool_budget(acted: World) -> None:
    used: dict[str, int] = {}
    budget: dict[str, int] = {}
    for entry in acted.actor_ledger:
        if entry.action.tool_name is None:
            continue
        used[entry.invocation.id] = used.get(entry.invocation.id, 0) + 1
        budget[entry.invocation.id] = entry.invocation.max_tool_calls
    assert used
    for invocation_id, count in used.items():
        assert count <= budget[invocation_id]


def test_no_actor_acted_after_its_deadline(acted: World) -> None:
    for entry in acted.actor_ledger:
        assert entry.acted_at <= entry.invocation.deadline


def test_the_episode_moves_forward_in_time_only(acted: World) -> None:
    """Monotonic, so an actor woken second cannot observe a moment its
    predecessor has not reached."""
    stamps = [entry.acted_at for entry in acted.actor_ledger]
    assert stamps == sorted(stamps)


def test_an_episode_needs_a_seeded_world() -> None:
    from worldloom.actors.runtime import EpisodeError

    loaded = World.load("retail-close")
    with pytest.raises(EpisodeError):
        run_episode(loaded, ScriptedActorProvider(), period=PERIOD)
