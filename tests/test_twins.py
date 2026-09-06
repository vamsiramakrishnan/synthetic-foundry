"""Counterfactual twins: the delta is measured, the refusal is honest.

Every number asserted verbatim here was measured at seed 8128 before the test
existed — the module's contract is that the manifest reports measurements, so
the tests hold it to the measured values rather than to "some rows changed".
The negative controls are the half that matters most: an identity intervention
must produce a byte-identical world (anything else is a nondeterminism in
``recipe.rebuild`` and must fail loudly here), an intervention on margin
physics must leave revenue and incident facts byte-identical (locality proven
on a *named* unrelated subset, not an aggregate count), and a cardinality
intervention must refuse rather than diff across reshuffled ids.

Everything goes through ``twins.twin``, which goes through ``recipe.rebuild``
with nothing but the recipe and the ledger — the P1 lesson from
``test_recipe_structure.py``: a proof that re-supplies the original build
flags is not testing the recording.
"""

from __future__ import annotations

import json

import pytest

from worldloom import profiles
from worldloom.parameters import DEFAULT, Span
from worldloom.recipe import RecipeError
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.twins import Intervention, TwinError, TwinResult, twin

SEED = 8128

#: The recorded physics the value-intervention cases patch. The override
#: restates the engine's own erosion *numbers* while carrying none of the
#: registry's `about` prose, so `overrides_document` — which compares whole
#: spans — records the key while the base world stays byte-identical to an
#: un-overridden build. An intervention needs a recorded value to name, and
#: this is the cheapest honest way to record one. If a future change makes
#: `overrides_document` compare numbers only, the key disappears and these
#: tests fail loudly at the path, which is the right noise.
_EROSION = {"retail.margin.erosion": Span(0.002, 0.020)}


def _row(model) -> str:
    """The corpus's own jsonl spelling — the representation the diff runs at."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True)


@pytest.fixture(scope="module")
def erosion_recipe() -> dict:
    """A retail close with an incident and a recorded physics override.

    Built the way the CLI builds it — physics on the spec *and* on the
    scenario — then only the recipe and ledger travel onward, exactly what
    ``twin`` accepts. Module-scoped because five tests read it and a build is
    the expensive step.
    """
    physics = DEFAULT.with_overrides(_EROSION)
    world = (
        RetailWorld(seed=SEED, physics=physics)
        .build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True,
                           physics=physics))
        .compile()
    )
    return world.recipe


@pytest.fixture(scope="module")
def erosion_twin(erosion_recipe: dict) -> TwinResult:
    """The one real twin: margin-erosion ceiling 0.020 -> 0.06."""
    return twin(erosion_recipe, (),
                Intervention("physics/retail.margin.erosion/high", 0.06))


def test_a_value_intervention_yields_a_local_twin(erosion_twin: TwinResult) -> None:
    """The measured claim, verbatim: 38 facts moved and 577 did not.

    The denominator is asserted beside the numerator because "38 changed" is
    not a locality claim until "577 did not" stands next to it — and the six
    changed documents and six changed evaluation cases are named, not counted,
    so a reshuffle that kept the counts would still fail.
    """
    m = erosion_twin.manifest
    assert m.refused is None
    assert m.intervention == {"path": "physics/retail.margin.erosion/high",
                              "before": 0.02, "after": 0.06}
    assert len(m.changed_fact_ids) == 38
    assert m.unchanged_counts["facts"] == 577
    assert m.changed_event_ids == ()
    assert m.unchanged_counts["events"] == 17
    assert m.changed_artifact_ids == (
        "ART-0002", "ART-0003", "ART-0010", "ART-0011", "ART-0012", "ART-0013",
    )
    assert m.changed_evaluation_ids == (
        "EVAL-0002", "EVAL-0003", "EVAL-0012", "EVAL-0013", "EVAL-0014", "EVAL-0015",
    )
    assert m.changed_entity_ids == ()
    assert m.changed_record_ids == ()

    # A named changed fact, and its kind: the delta is where the physics says
    # it should be, in the margin family the eroded parameter feeds.
    assert "FACT-0536" in m.changed_fact_ids
    assert erosion_twin.base.facts.by_id("FACT-0536").kind == "financial.gross_profit.actual"
    changed_kinds = {erosion_twin.base.facts.by_id(i).kind for i in m.changed_fact_ids}
    assert changed_kinds == {
        "financial.gross_margin_pct.actual",
        "financial.gross_profit.actual",
        "financial.gross_profit.variance",
        "metric.gross_margin_variance",
        "metric.promotional_depth_margin_impact",
    }
    # And a named unchanged one: the group's revenue was not touched by a
    # margin intervention.
    assert "FACT-0020" not in m.changed_fact_ids
    assert erosion_twin.base.facts.by_id("FACT-0020").kind == "financial.revenue.actual"


def test_unrelated_measures_stay_byte_identical(erosion_twin: TwinResult) -> None:
    """Locality proven on named subsets, independently of the manifest.

    The manifest *defines* changed ids by row diff, so re-reading it here would
    be circular. This recomputes the rows from the two worlds directly: every
    revenue fact and every incident fact — measures the margin intervention
    has no business touching — must serialise to the same bytes. Both subsets
    are asserted non-empty first, because a prefix typo would otherwise prove
    locality over nothing (which is how the first draft of this test passed
    with a wrong prefix: ``operational.`` matches no fact kind; ``ops.`` does).
    """
    base = {f.id: f for f in erosion_twin.base._facts}
    counter = {f.id: f for f in erosion_twin.world._facts}
    revenue = [i for i, f in base.items() if f.kind == "financial.revenue.actual"]
    incident = [i for i, f in base.items() if f.kind.startswith("ops.")]
    assert len(revenue) == 172
    assert len(incident) == 13
    for fact_id in (*revenue, *incident):
        assert _row(base[fact_id]) == _row(counter[fact_id]), fact_id


def test_changed_answers_trace_to_changed_facts(erosion_twin: TwinResult) -> None:
    """Every changed evaluation case cites at least one changed fact.

    This is what stops the manifest's evaluation column from being noise: an
    answer that moved without any of its supporting facts moving would mean
    the eval set carries values the fact ledger does not — a coherence hole,
    not a delta. And the unchanged cases must keep identical expected answers,
    compared directly between the two worlds rather than through the manifest.
    """
    m = erosion_twin.manifest
    changed_facts = set(m.changed_fact_ids)
    base_evals = {e.id: e for e in erosion_twin.base._evaluations}
    twin_evals = {e.id: e for e in erosion_twin.world._evaluations}
    for eval_id in m.changed_evaluation_ids:
        assert set(base_evals[eval_id].expected_fact_ids) & changed_facts, eval_id
    for eval_id in set(base_evals) - set(m.changed_evaluation_ids):
        assert base_evals[eval_id].expected_answer == twin_evals[eval_id].expected_answer


def test_the_same_twin_twice_is_the_same_manifest(erosion_recipe: dict) -> None:
    """Two computations of one twin agree to the byte.

    ``rebuild`` is a pure function of (recipe, ledger) or it is nothing; a
    manifest that differed between two runs would mean the delta depends on
    when it was measured, and every causal claim above it collapses.
    """
    intervention = Intervention("physics/retail.margin.erosion/high", 0.06)
    first = twin(erosion_recipe, (), intervention)
    second = twin(erosion_recipe, (), intervention)
    assert first.manifest == second.manifest
    assert first.manifest.as_dict() == second.manifest.as_dict()


def test_identity_intervention_is_byte_identical(erosion_recipe: dict) -> None:
    """Replacing the recorded value with itself changes nothing at all.

    The loudest nondeterminism detector this module has: both worlds are built
    by two separate ``rebuild`` calls, so *any* clock, unseeded draw, or
    set-ordering leak in the build path shows up here as a changed row with an
    intervention that changed nothing. If this fails, the finding is about
    ``rebuild``, not about twins — report it, do not paper over it.
    """
    result = twin(erosion_recipe, (),
                  Intervention("physics/retail.margin.erosion/high", 0.02))
    assert result.manifest.is_null
    assert result.manifest.refused is None
    assert result.manifest.unchanged_counts["facts"] == 615
    # Belt and braces beyond the manifest: the whole persisted surface,
    # serialised, is the same bytes.
    for attribute in ("_facts", "_events", "_artifact_intents", "_artifact_irs",
                      "_artifacts", "_evaluations", "_people", "_business_units",
                      "_sites", "_systems", "_services", "_lore"):
        base_rows = [_row(m) for m in getattr(result.base, attribute)]
        twin_rows = [_row(m) for m in getattr(result.world, attribute)]
        assert base_rows == twin_rows, attribute


def test_an_absorbed_intervention_measures_null(erosion_recipe: dict) -> None:
    """A widened integer range can leave the drawn value exactly where it was.

    Measured, and surprising enough to pin: ``ops.incident.affected_records``
    high 27,000 -> 30,000 changes *nothing* at this seed, because
    ``random.Random.randint`` rejection-samples at the range's bit width —
    both widths need 15 bits, the accepted draw is the same, and
    ``low + draw`` lands on the same number of records. The honest manifest
    for that is zero changes, not an invented delta; ``is_null`` names it a
    finding. (Continuous ``number`` parameters scale the draw by the range's
    width, so any endpoint change moves them — the value cases above.)
    """
    physics = DEFAULT.with_overrides({"ops.incident.affected_records": Span(4000, 27000)})
    world = (
        RetailWorld(seed=SEED, physics=physics)
        .build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True,
                           physics=physics))
        .compile()
    )
    result = twin(world.recipe, (),
                  Intervention("physics/ops.incident.affected_records/high", 30000.0))
    assert result.manifest.is_null
    assert result.manifest.unchanged_counts["facts"] == 615


def test_a_recorded_step_argument_is_twinnable(erosion_recipe: dict) -> None:
    """`--trend` doubled reaches the comparative history and nothing else.

    The sharpest locality result of the measured classes: 148 comparative-month
    facts move, 667 do not, exactly one document (the trend commentary's
    workbook, ART-0002) changes, and *no evaluation case* does — the eval set
    asks about the reporting month, and the trend shapes the months behind it.
    """
    world = (
        RetailWorld(seed=SEED)
        .build()
        .run(MonthEndClose(period="2026-03", comparative_months=6, trend_pct=0.004))
        .compile()
    )
    result = twin(world.recipe, (), Intervention("steps/0/trend_pct", 0.008))
    m = result.manifest
    assert m.refused is None
    assert m.intervention["before"] == 0.004
    assert len(m.changed_fact_ids) == 148
    assert m.unchanged_counts["facts"] == 667
    assert m.changed_artifact_ids == ("ART-0002",)
    assert m.changed_evaluation_ids == ()
    assert m.changed_event_ids == ()


def test_a_recorded_trading_year_is_twinnable_whole() -> None:
    """Replacing the whole seasonality index is a value intervention.

    Broad — the index multiplies every month's budget — but id-stable, so the
    twin holds: no refusal, no event moves, and every changed answer traces to
    a changed fact.
    """
    season = profiles.Seasonality.normalised([1.0] * 11 + [1.4])
    world = (
        RetailWorld(seed=SEED, seasonality=season)
        .build()
        .run(MonthEndClose(period="2026-03", comparative_months=6, seasonality=season))
        .compile()
    )
    flat = {str(month): 1.0 for month in profiles.MONTHS}
    result = twin(world.recipe, (), Intervention("seasonality/index", flat))
    m = result.manifest
    assert m.refused is None
    assert m.changed_fact_ids and m.changed_evaluation_ids
    assert m.changed_event_ids == ()
    changed_facts = set(m.changed_fact_ids)
    base_evals = {e.id: e for e in result.base._evaluations}
    for eval_id in m.changed_evaluation_ids:
        assert set(base_evals[eval_id].expected_fact_ids) & changed_facts, eval_id


def test_a_single_seasonality_month_is_refused_by_the_engine_itself() -> None:
    """One month cannot be intervened on: the trading year must average one.

    ``profiles.Seasonality`` refuses a mean off 1.0 because it would resize the
    company, so the patched recipe fails to *load* and ``rebuild`` raises
    ``RecipeError`` before any counterfactual exists. That is an error, not a
    manifest refusal — there is no world to measure — and it is the engine's
    own invariant doing the refusing, which is exactly where it belongs. The
    twinnable unit is the whole ``index``, re-normalised by the caller.
    """
    season = profiles.Seasonality.normalised([1.0] * 11 + [1.4])
    world = (
        RetailWorld(seed=SEED, seasonality=season)
        .build()
        .run(MonthEndClose(period="2026-03", seasonality=season))
        .compile()
    )
    with pytest.raises(RecipeError, match="trading year"):
        twin(world.recipe, (), Intervention("seasonality/index/3", 1.5))


def test_a_cardinality_intervention_is_refused_with_the_cause() -> None:
    """``policies`` core -> full adds documents, so the twin refuses.

    Five standing documents, their parameter facts and their questions arrive
    mid-sequence, so every later id names a different thing in the two worlds.
    The manifest must say so — with the measured counts — and must claim no
    per-id delta at all, because a diff across reshuffled ids would label
    unrelated changes as caused.
    """
    world = (
        RetailWorld(seed=SEED, policies="core")
        .build()
        .run(MonthEndClose(period="2026-03"))
        .compile()
    )
    result = twin(world.recipe, (), Intervention("policies", "full"))
    m = result.manifest
    assert m.refused is not None
    assert "changes what exists" in m.refused
    assert "facts 631 -> 652" in m.refused
    assert m.changed_fact_ids == ()
    assert m.changed_artifact_ids == ()
    assert m.unchanged_counts == {}
    # The counterfactual is still a real world — what the refusal withdraws is
    # the causal labelling, not the build.
    assert len(result.world._facts) == 652


def test_switching_the_incident_off_is_refused(erosion_recipe: dict) -> None:
    """The other refusal shape: an intervention that removes an episode's spine."""
    result = twin(erosion_recipe, (), Intervention("steps/0/incident", False))
    assert result.manifest.refused is not None
    assert "changes what exists" in result.manifest.refused


def test_an_unrecorded_path_is_an_error_not_a_refusal(erosion_recipe: dict) -> None:
    """A path that does not resolve raises before any world is built.

    Three grammars of failure, each named: a key the recipe never recorded, a
    list indexed by a word, and a descent into a scalar. None of them is a
    refusal — a refusal is a measurement, and nothing was measured.
    """
    with pytest.raises(TwinError, match="not recorded"):
        twin(erosion_recipe, (), Intervention("physics/retail.margin.budgt/high", 0.3))
    with pytest.raises(TwinError, match="must be an integer"):
        twin(erosion_recipe, (), Intervention("steps/first/incident", False))
    with pytest.raises(TwinError, match="no children"):
        twin(erosion_recipe, (), Intervention("seed/low", 1))


def test_the_manifest_serialises_deterministically(erosion_twin: TwinResult) -> None:
    """``as_dict`` is plain JSON with stable ordering, fit for a sidecar."""
    document = erosion_twin.manifest.as_dict()
    assert json.dumps(document) == json.dumps(erosion_twin.manifest.as_dict())
    assert list(document["unchanged_counts"]) == sorted(document["unchanged_counts"])
    assert document["refused"] is None
