"""Tests for `worldloom.compiler` — the plan/component/grammar spine and the
composer built on top of it.

Neither layer has tests yet, so this file covers both: hand-built plans exercise
the composer the way `test_lifetimes.py` hand-builds validator violations
(building the case a check exists for is the only way to prove it fires at all),
and a handful of direct calls into `components.py` and `grammar.py` cover the
registry and the grammar rules the composer leans on.

`ArtifactPlan`, `NarrativeBeat` and `EvidenceRef` are frozen pydantic models —
built with keyword arguments and never mutated, the same discipline
`test_lifetimes.py` applies to the (frozen dataclass) `World` and its entities.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.compiler import ArtifactPlan, EvidenceRef, NarrativeBeat
from worldloom.compiler.components import REGISTRY, compatible, component, roles_for
from worldloom.compiler.compose import compose, plan_for
from worldloom.compiler.grammar import check
from worldloom.documents import _DEFAULT_OUTLINE, _OUTLINES


def _facts(n: int, *, role: str = "driver", emphasis: float = 0.5) -> list[EvidenceRef]:
    """*n* interchangeable evidence references — enough to hit a component's row
    floor without the test caring which facts they are."""
    return [EvidenceRef(fact_id=f"FACT-{i:04d}", role=role, emphasis=emphasis) for i in range(n)]


def _plan(
    *,
    artifact_type: str = "cfo_variance_memo",
    beats: list[NarrativeBeat],
    size_class: str = "medium",
    density_profile: str = "balanced",
) -> ArtifactPlan:
    return ArtifactPlan(
        intent_id="ART-TEST-0001",
        artifact_type=artifact_type,
        audience="group_cfo",
        intent="explain_performance_and_request_decisions",
        beats=beats,
        size_class=size_class,  # type: ignore[arg-type]
        density_profile=density_profile,  # type: ignore[arg-type]
    )


# ---------------------------------------------------------------------------
# 1. A well-formed plan
# ---------------------------------------------------------------------------


def test_a_well_formed_plan_composes_grammatically() -> None:
    plan = _plan(
        beats=[
            NarrativeBeat(key="position", purpose="p", evidence=_facts(2), semantic_role="position"),
            NarrativeBeat(key="evidence", purpose="e", evidence=_facts(3), semantic_role="evidence"),
            NarrativeBeat(key="decision", purpose="d", evidence=_facts(1), semantic_role="decision"),
        ],
    )

    composition = compose(plan, fmt="markdown")

    assert composition.ok, composition.violations
    assert composition.components == ("core.position", "finance.variance_table", "mgmt.decision_panel")
    assert composition.beats == ("position", "evidence", "decision")
    assert composition.dropped == ()


# ---------------------------------------------------------------------------
# 2. Repairable ordering
# ---------------------------------------------------------------------------


def test_a_missing_precondition_is_repaired_by_reordering() -> None:
    """`mgmt.decision_panel` requires an `evidence` component before it. The
    plan puts the decision beat second and the evidence beat third — wrong for
    the argument, but mechanically fixable because the evidence-providing beat
    exists, just too late. The repair must move it ahead rather than leave the
    violation for `grammar.check` to report.
    """
    plan = _plan(
        beats=[
            NarrativeBeat(key="position", purpose="p", evidence=_facts(2), semantic_role="position"),
            NarrativeBeat(key="decision", purpose="d", evidence=_facts(1), semantic_role="decision"),
            NarrativeBeat(key="evidence", purpose="e", evidence=_facts(3), semantic_role="evidence"),
        ],
    )

    composition = compose(plan, fmt="markdown")

    assert composition.ok, composition.violations
    assert composition.beats == ("position", "evidence", "decision"), (
        "the evidence beat must be pulled ahead of the decision beat it repairs"
    )
    assert composition.components == ("core.position", "finance.variance_table", "mgmt.decision_panel")


# ---------------------------------------------------------------------------
# 3. Unrepairable ordering
# ---------------------------------------------------------------------------


def test_an_unrepairable_precondition_is_reported_not_raised() -> None:
    """No beat anywhere in this plan fills the `evidence` role `decision`
    needs, so there is nothing a reordering could move — the violation must
    come back on the `Composition`, and `compose` must not raise or silently
    drop the decision beat to make the problem disappear.
    """
    plan = _plan(
        beats=[
            NarrativeBeat(key="position", purpose="p", evidence=_facts(2), semantic_role="position"),
            NarrativeBeat(key="decision", purpose="d", evidence=_facts(1), semantic_role="decision"),
        ],
    )

    composition = compose(plan, fmt="markdown")

    assert not composition.ok
    codes = {v.code for v in composition.violations}
    assert "missing_precondition" in codes
    assert "missing_role" in codes
    # Both beats survive: an unrepairable ordering problem is reported, not
    # edited away by quietly dropping the beat that exposed it.
    assert composition.beats == ("position", "decision")


# ---------------------------------------------------------------------------
# 4. The size budget
# ---------------------------------------------------------------------------


def test_over_budget_drops_optional_beats_lowest_emphasis_first() -> None:
    required = [
        NarrativeBeat(key="position", purpose="p", evidence=_facts(2), semantic_role="position"),
        NarrativeBeat(key="req_evidence", purpose="e", evidence=_facts(2), semantic_role="evidence"),
    ]
    optional = [
        NarrativeBeat(
            key=f"optional_{tag}", purpose="o", evidence=_facts(3, emphasis=emphasis), semantic_role="comparison",
            optional=True,
        )
        for tag, emphasis in (("high", 0.9), ("lowest", 0.1), ("mid_high", 0.5), ("mid_low", 0.3))
    ]
    # size_class "small" caps at 4 components; 2 required + 4 optional is 2 over.
    plan = _plan(beats=required + optional, size_class="small")

    composition = compose(plan, fmt="markdown")

    assert composition.ok, composition.violations
    assert len(composition.components) == 4
    # The two lowest total-emphasis optional beats go; the two required beats
    # and the two higher-emphasis optional beats survive.
    assert set(composition.dropped) == {"optional_lowest", "optional_mid_low"}
    assert "position" in composition.beats and "req_evidence" in composition.beats
    assert "optional_high" in composition.beats and "optional_mid_high" in composition.beats


def test_required_beats_are_never_dropped_and_the_shortfall_raises() -> None:
    """Five required beats against a "small" cap of four: there is no optional
    beat to shed, so this is a defect in the plan, not something to silently
    truncate into a document missing part of its argument.
    """
    beats = [
        NarrativeBeat(key=f"required_{i}", purpose="p", evidence=_facts(2), semantic_role="position")
        for i in range(5)
    ]
    plan = _plan(beats=beats, size_class="small")

    with pytest.raises(ValueError, match="over budget"):
        compose(plan, fmt="markdown")


# ---------------------------------------------------------------------------
# 5. Format sensitivity
# ---------------------------------------------------------------------------


def test_a_component_unsupported_in_the_format_is_not_selected() -> None:
    """`xlsx.reconciliation` is the only implementation of the `control` role
    and is xlsx-only. In xlsx it is selected; in markdown nothing can fill a
    required `control` beat, and `compose` must say so rather than compose a
    workbook control section markdown cannot express.
    """
    plan = _plan(
        artifact_type="finance_workbook",
        beats=[
            NarrativeBeat(key="evidence", purpose="e", evidence=_facts(3), semantic_role="evidence"),
            NarrativeBeat(key="control", purpose="c", evidence=_facts(1), semantic_role="control"),
        ],
    )

    composition = compose(plan, fmt="xlsx")
    assert "xlsx.reconciliation" in composition.components
    assert composition.ok, composition.violations

    with pytest.raises(ValueError, match="control"):
        compose(plan, fmt="markdown")


def test_finance_metric_strip_caps_at_six_rows() -> None:
    """`finance.metric_strip` is the only `position`-role component left once
    density excludes `core.position` (see `compose._DENSITY_BY_PROFILE`), and
    it declares `max_rows=6`. Five rows of evidence fit; seven do not, and
    with nothing else able to fill a required `position` beat, composing must
    fail rather than silently truncate the evidence to fit.
    """
    fits = _plan(
        artifact_type="executive_summary",
        beats=[NarrativeBeat(key="strip", purpose="s", evidence=_facts(5), semantic_role="position")],
        size_class="small",
        density_profile="dense",
    )
    composition = compose(fits, fmt="markdown")
    assert composition.components == ("finance.metric_strip",)

    overflows = _plan(
        artifact_type="executive_summary",
        beats=[NarrativeBeat(key="strip", purpose="s", evidence=_facts(7), semantic_role="position")],
        size_class="small",
        density_profile="dense",
    )
    with pytest.raises(ValueError, match="strip"):
        compose(overflows, fmt="markdown")


# ---------------------------------------------------------------------------
# 6. Determinism
# ---------------------------------------------------------------------------


def test_composing_the_same_plan_twice_is_identical() -> None:
    plan = _plan(
        beats=[
            NarrativeBeat(key="position", purpose="p", evidence=_facts(2), semantic_role="position"),
            NarrativeBeat(key="evidence", purpose="e", evidence=_facts(3), semantic_role="evidence"),
        ],
    )

    first = compose(plan, fmt="markdown")
    second = compose(plan, fmt="markdown")

    assert first == second


def test_composing_for_two_formats_can_legitimately_differ() -> None:
    """A `control` beat is optional here, so an xlsx-only component being
    unselectable in markdown does not fail the compose — it is simply dropped,
    and the two formats' compositions genuinely differ as a result. Legitimate
    divergence, not nondeterminism: each format on its own is still stable
    (covered by the identical-twice case above).
    """
    plan = _plan(
        artifact_type="finance_workbook",
        beats=[
            NarrativeBeat(key="evidence", purpose="e", evidence=_facts(3), semantic_role="evidence"),
            NarrativeBeat(key="control", purpose="c", evidence=_facts(1), semantic_role="control", optional=True),
        ],
    )

    xlsx = compose(plan, fmt="xlsx")
    markdown = compose(plan, fmt="markdown")

    assert xlsx.components != markdown.components
    assert xlsx.dropped == ()
    assert markdown.dropped == ("control",)


# ---------------------------------------------------------------------------
# 7. plan_for — the migration bridge
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def built_world() -> World:
    # A real world, one close with an incident, so every artifact type
    # `generators/planning.py` ever emits is present to bridge — the same
    # build `test_episodes.py` uses, at a single period since nothing here
    # needs recurrence.
    world = RetailWorld(seed=8128).build()
    return world.run(MonthEndClose(period="2026-03", include_operational_incident=True))


def test_plan_for_never_invents_evidence_beyond_the_intent(built_world: World) -> None:
    for intent in built_world.artifact_intents:
        sections = _OUTLINES.get(intent.artifact_type, _DEFAULT_OUTLINE)
        plan = plan_for(intent, sections, built_world.facts)

        assert set(plan.evidence_ids()) <= set(intent.required_fact_ids), (
            f"{intent.artifact_type} ({intent.id}) cited evidence its intent never required"
        )
        assert plan.intent_id == intent.id
        assert plan.artifact_type == intent.artifact_type
        assert plan.audience == intent.audience


def test_plan_for_carries_purpose_across_verbatim() -> None:
    intent = next(
        i for i in RetailWorld(seed=8128).build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True))
        .artifact_intents
        if i.artifact_type == "cfo_variance_memo"
    )
    sections = _OUTLINES["cfo_variance_memo"]

    plan = plan_for(intent, sections, [])

    purposes = {beat.purpose for beat in plan.beats}
    assert purposes == {section.purpose for section in sections}


# ---------------------------------------------------------------------------
# 8. The grammar itself
# ---------------------------------------------------------------------------


def test_grammar_catches_a_decision_panel_before_its_evidence() -> None:
    violations = check("cfo_variance_memo", ["core.position", "mgmt.decision_panel"])
    codes = {v.code for v in violations}
    assert "missing_role" in codes
    assert "missing_precondition" in codes


def test_grammar_catches_remediation_preceding_cause_in_an_rca() -> None:
    violations = check(
        "incident_rca",
        ["ops.incident_timeline", "ops.remediation_table", "ops.causal_chain"],
    )
    codes = {v.code for v in violations}
    assert "out_of_order" in codes


def test_grammar_forbids_a_control_component_in_an_executive_summary() -> None:
    violations = check("executive_summary", ["core.executive_summary", "xlsx.reconciliation"])
    codes = {v.code for v in violations}
    assert "forbidden_role" in codes


def test_unknown_artifact_type_is_unconstrained_by_design() -> None:
    """A type with no grammar entry is not a violation — see `grammar.check`'s
    own docstring: coupling every new artifact type to a grammar change would
    stop a scenario from introducing one at all."""
    assert check("not_a_real_artifact_type", ["core.position"]) == []


# ---------------------------------------------------------------------------
# The spine: components.py and grammar.py directly
# ---------------------------------------------------------------------------


def test_component_lookup_of_an_unknown_id_names_what_was_asked_for() -> None:
    with pytest.raises(KeyError, match=r"not\.a\.component"):
        component("not.a.component")


def test_roles_for_preserves_registry_order() -> None:
    """The tie-break the composer relies on: candidates come back in exactly
    the order `REGISTRY` declares them, not sorted or grouped."""
    evidence_ids = [spec.component_id for spec in REGISTRY if "evidence" in spec.semantic_roles]
    assert [spec.component_id for spec in roles_for("evidence")] == evidence_ids


def test_component_spec_fits_checks_format_density_and_rows() -> None:
    strip = component("finance.metric_strip")
    assert strip.fits(fmt="markdown", density=0.5, rows=4)
    assert not strip.fits(fmt="xlsx", density=0.5, rows=4), "markdown/docx/pptx only"
    assert not strip.fits(fmt="markdown", density=0.9, rows=4), "outside the 0.2-0.8 band"
    assert not strip.fits(fmt="markdown", density=0.5, rows=7), "over max_rows"
    assert not strip.fits(fmt="markdown", density=0.5, rows=2), "under min_rows"


def test_compatible_treats_an_empty_predecessor_set_as_unconstrained() -> None:
    # `finance.variance_table` declares no `compatible_predecessors` at all —
    # per its own field docstring that means "no constraint", not "nothing may
    # precede it". Getting this backwards would reject the entire vocabulary.
    assert compatible("core.position", "finance.variance_table")


def test_evidence_ids_are_order_preserving_and_deduplicated() -> None:
    plan = _plan(
        beats=[
            NarrativeBeat(
                key="a", purpose="p",
                evidence=[EvidenceRef(fact_id="FACT-0001", role="headline"),
                          EvidenceRef(fact_id="FACT-0002", role="driver")],
                semantic_role="position",
            ),
            NarrativeBeat(
                key="b", purpose="p",
                # FACT-0001 repeats — must not appear twice, and must not move.
                evidence=[EvidenceRef(fact_id="FACT-0001", role="driver"),
                          EvidenceRef(fact_id="FACT-0003", role="driver")],
                semantic_role="evidence",
            ),
        ],
    )

    assert plan.evidence_ids() == ["FACT-0001", "FACT-0002", "FACT-0003"]


def test_required_beats_excludes_optional_ones() -> None:
    plan = _plan(
        beats=[
            NarrativeBeat(key="required", purpose="p", evidence=[], semantic_role="position"),
            NarrativeBeat(key="optional", purpose="p", evidence=[], semantic_role="evidence", optional=True),
        ],
    )

    assert [b.key for b in plan.required_beats()] == ["required"]
