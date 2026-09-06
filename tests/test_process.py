"""Role slots, the participation join, and the process cascade.

Three claims from the settled design (docs/next-phase-plan.md, "Who authors a
process"), each pinned where it could silently fail:

- **Ordering is declared, and the binding is checked.** A process declares
  slots; a LOB binds roles to them. An unbound required slot and a binding to
  a role the LOB lacks are both refused — a seat with nobody in it is not a
  warning.
- **Participation is a join, never a table.** Who is in a process derives from
  responsibility edges meeting the kinds the steps mint, under the registry's
  dot-prefix semantics — so it cannot disagree with the declarations it comes
  from, because it *is* them.
- **The cascade refuses inventions.** A step minting a kind that is neither
  registry-known nor declared with invariants is refused at the stage that
  proposed it — the same defect the fact-kind registry was built to catch,
  stopped one handshake earlier.
"""

from __future__ import annotations

import pytest

import worldloom  # noqa: F401 — importing the package populates the registries
from worldloom import episodes, lob, process
from worldloom.episodes import (
    EpisodeSpec,
    EventSpec,
    FactKindSpec,
    Invariant,
    RoleSlotSpec,
)


def _survey_spec(slots: list[RoleSlotSpec] | None = None) -> EpisodeSpec:
    """A minimal process: one step minting a registry-known kind."""
    return EpisodeSpec(
        name="HrOnboarding",
        domain="retail",
        period="month",
        fact_kinds=[FactKindSpec(
            kind="org.joined",
            value_type="text",
            text="Recorded start for the period {period}.",
            invariants=[Invariant(kind="holds-at")],
        )],
        events=[EventSpec(
            kind="hr.joiner_recorded", when="start",
            summary="The joiner is recorded.", fact_keys=["org.joined"],
        )],
        role_slots=slots if slots is not None else [
            RoleSlotSpec(slot="preparer", purpose="records the joiner"),
            RoleSlotSpec(slot="approver", purpose="signs the onboarding off"),
        ],
    )


def _hr(bindings: list[lob.SlotBinding]) -> lob.Lob:
    return lob.publish()["hr"].model_copy(update={"slot_bindings": bindings})


# ---------------------------------------------------------------------------
# Slot refusals
# ---------------------------------------------------------------------------


def test_an_unbound_required_slot_is_refused() -> None:
    spec = _survey_spec()
    bound_one = _hr([lob.SlotBinding(
        process="HrOnboarding", slot="preparer", role_key="recruiter",
    )])
    findings = lob.lint_bindings(bound_one, spec)
    assert any("approver" in f and "unbound" in f for f in findings), findings


def test_a_binding_to_a_role_the_lob_lacks_is_refused() -> None:
    spec = _survey_spec()
    seated_by_nobody = _hr([
        lob.SlotBinding(process="HrOnboarding", slot="preparer", role_key="recruiter"),
        lob.SlotBinding(process="HrOnboarding", slot="approver", role_key="chief_wizard"),
    ])
    findings = lob.lint_bindings(seated_by_nobody, spec)
    assert any("chief_wizard" in f for f in findings), findings


def test_a_binding_to_an_undeclared_slot_is_refused() -> None:
    spec = _survey_spec()
    off_vocabulary = _hr([
        lob.SlotBinding(process="HrOnboarding", slot="preparer", role_key="recruiter"),
        lob.SlotBinding(process="HrOnboarding", slot="approver", role_key="head_of_people"),
        lob.SlotBinding(process="HrOnboarding", slot="witness", role_key="recruiter"),
    ])
    findings = lob.lint_bindings(off_vocabulary, spec)
    assert any("witness" in f and "vocabulary" in f for f in findings), findings


def test_a_complete_binding_lints_clean_and_an_optional_slot_may_stay_empty() -> None:
    spec = _survey_spec(slots=[
        RoleSlotSpec(slot="preparer"),
        RoleSlotSpec(slot="observer", required=False),
    ])
    bound = _hr([lob.SlotBinding(
        process="HrOnboarding", slot="preparer", role_key="recruiter",
    )])
    assert lob.lint_bindings(bound, spec) == []


def test_a_duplicate_slot_declaration_is_refused_by_the_spec_itself() -> None:
    with pytest.raises(ValueError, match="duplicate role slot"):
        _survey_spec(slots=[RoleSlotSpec(slot="preparer"), RoleSlotSpec(slot="preparer")])


# ---------------------------------------------------------------------------
# Participation: the join
# ---------------------------------------------------------------------------


def test_participation_joins_edges_against_minted_kinds_plus_bindings() -> None:
    """`head_of_people` answers for `org.joined` and sits in a seat; the
    `recruiter` joins on the edge alone; the join uses the registry's
    dot-prefix rule, so nobody had to restate the family per process."""
    spec = _survey_spec()
    bound = _hr([lob.SlotBinding(
        process="HrOnboarding", slot="approver", role_key="head_of_people",
    )])

    participants = lob.participation(bound, spec)
    by_key = {p.role_key: p for p in participants}
    assert set(by_key) == {"head_of_people", "recruiter"}
    assert by_key["head_of_people"].slots == ("approver",)
    assert by_key["head_of_people"].kinds == ("org.joined",)
    assert by_key["head_of_people"].via == ("org.joined",)
    assert by_key["recruiter"].slots == ()
    assert by_key["recruiter"].kinds == ("org.joined",)


def test_participation_is_exposed_on_describe_and_the_blueprint() -> None:
    from worldloom import sdk

    episodes.install([_survey_spec()])
    bound = _hr([
        lob.SlotBinding(process="HrOnboarding", slot="preparer", role_key="recruiter"),
        lob.SlotBinding(process="HrOnboarding", slot="approver", role_key="head_of_people"),
    ])
    lob.install([bound.model_copy(update={"name": "hr_bound"})])

    described = lob.describe("hr_bound")
    assert described is not None
    assert "HrOnboarding" in described["participation"]
    roles = [row["role"] for row in described["participation"]["HrOnboarding"]]
    assert roles == ["head_of_people", "recruiter"]

    blueprint = sdk.retail().lob(lob.publish()["hr"], bind={
        "HrOnboarding": {"preparer": "recruiter", "approver": "head_of_people"},
    })
    joined = blueprint.participation("HrOnboarding")
    assert set(joined) == {"hr"}
    assert {p.role_key for p in joined["hr"]} == {"head_of_people", "recruiter"}


def test_the_blueprint_refuses_a_binding_to_a_role_the_lob_lacks() -> None:
    from worldloom import sdk

    with pytest.raises(ValueError, match="chief_wizard"):
        sdk.retail().lob(lob.publish()["hr"],
                         bind={"HrOnboarding": {"approver": "chief_wizard"}})


# ---------------------------------------------------------------------------
# The cascade
# ---------------------------------------------------------------------------


SEED = process.ProcessSeed(
    name="HrOnboardingCascade",
    purpose="Every joiner is recorded and the record signed off.",
    engine="retail",
    lob="hr",
    period="month",
)


def test_the_cascade_round_trips_to_a_spec_that_installs_and_runs() -> None:
    """seed → steps (registry-known kind, invariants left to the registry) →
    slots → resolve → install → run → replay. The registry fill is asserted on
    the way through: the resolved spec carries `org.joined`'s registered
    invariants without the author restating them."""
    session = process.open(SEED, facets={"listing": "listed"})

    brief = process.next_stage(session)
    assert brief.stage == "steps"
    assert brief.context["engine"] == "retail"
    assert brief.context["facets"] == {"listing": "listed"}
    assert "recruiter" in brief.context["lob_roles"], "company context rides the brief"

    session = process.accept(session, process.Answer(
        stage="steps",
        steps=[EventSpec(
            kind="hr.joiner_recorded", when="start",
            summary="The joiner is recorded for {period}.",
            fact_keys=["org.joined"],
        )],
        kinds=[FactKindSpec(kind="org.joined", value_type="text",
                            text="Recorded start, period {period}.")],
    ))
    assert session.kinds is not None
    heads = {inv.kind for inv in session.kinds[0].invariants}
    assert heads == {"holds-at", "precedes-event"}, "filled from the registry"

    assert process.next_stage(session).stage == "slots"
    session = process.accept(session, process.Answer(stage="slots", slots=[
        RoleSlotSpec(slot="preparer", purpose="records the joiner"),
        RoleSlotSpec(slot="approver", purpose="signs the record off"),
    ]))
    assert process.next_stage(session).stage == "resolve"

    spec = process.resolve(session)
    assert episodes.lint([spec]) == []
    assert [slot.slot for slot in spec.role_slots] == ["preparer", "approver"]

    episodes.install([spec])
    from worldloom import RetailWorld, recipe

    world = RetailWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode=spec.name, period="2026-01")
    )
    minted = [f for f in world.facts if f.kind == "org.joined"]
    assert len(minted) == 1 and minted[0].text_value
    assert "2026-01" in minted[0].text_value

    again = recipe.rebuild(recipe=world.recipe)
    assert tuple(again._facts) == tuple(world._facts), "only the resolved spec replays"


def test_a_step_minting_an_invented_kind_is_refused() -> None:
    session = process.open(SEED)
    with pytest.raises(ValueError, match=r"wellness\.morale"):
        process.accept(session, process.Answer(
            stage="steps",
            steps=[EventSpec(kind="hr.survey", when="start",
                             summary="A survey.", fact_keys=["wellness.morale"])],
            kinds=[],
        ))


def test_an_unknown_kind_without_invariants_is_refused_but_declared_ones_pass() -> None:
    session = process.open(SEED)
    bare = FactKindSpec(kind="wellness.morale", value_type="percent", amount=74.0)
    with pytest.raises(ValueError, match="neither registry-known nor declared"):
        process.accept(session, process.Answer(
            stage="steps",
            steps=[EventSpec(kind="hr.survey", when="start",
                             summary="A survey.", fact_keys=["wellness.morale"])],
            kinds=[bare],
        ))

    declared = bare.model_copy(update={"invariants": [Invariant(kind="holds-at")]})
    accepted = process.accept(session, process.Answer(
        stage="steps",
        steps=[EventSpec(kind="hr.survey", when="start",
                         summary="A survey.", fact_keys=["wellness.morale"])],
        kinds=[declared],
    ))
    assert accepted.steps is not None


def test_resolve_before_the_stages_are_accepted_is_refused() -> None:
    session = process.open(SEED)
    with pytest.raises(ValueError, match="steps stage"):
        process.resolve(session)


def test_lint_seed_names_an_unknown_engine_and_an_unknown_lob() -> None:
    findings = process.lint_seed(process.ProcessSeed(
        name="Nowhere", purpose="x", engine="alchemy", lob="wizards",
    ))
    assert any("alchemy" in f for f in findings)
    assert any("wizards" in f for f in findings)
