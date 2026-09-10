from __future__ import annotations

from dataclasses import replace

import pytest

from worldloom.eval_design import (
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
)
from worldloom.evals.calibration import (
    NoiseCalibrationPlan,
    NoiseCalibrationRecord,
    NoiseVariant,
    TrialOutcome,
    calibrate_noise,
)
from worldloom.evals.campaign import EvalCampaign
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose


@pytest.fixture(scope="module")
def campaign_run():  # type: ignore[no-untyped-def]
    spec = EvalSpec(id="noise-eval", capability="search", persona="controller", request_template="Find evidence.",
                    steps=(EvalStepSpec(id="read", capability="search"),),
                    requirements=(WorldRequirement(id="facts", kind=RequirementKind.FACT),), candidate_count=6)
    return EvalCampaign(spec).run(lambda p: RetailWorld(seed=p.seed).build().run(MonthEndClose(period="2026-03")))


def _plan(**updates):  # type: ignore[no-untyped-def]
    payload = dict(variants=(NoiseVariant(name="clean", budget={}, niche="current"),
                            NoiseVariant(name="stale", budget={"staleness": 1}, niche="decayed")),
                   niches=("current", "decayed", "unproposed"), cohort="scripted-controller-test/v1",
                   evaluator_config={"implementation": "scripted-smoke/v1"},
                   target_low=.5, target_high=1, min_support=2, max_training_attempts=8,
                   max_holdout_attempts=4, holdout_ordinals=(4, 5))
    payload.update(updates)
    return NoiseCalibrationPlan(**payload)


def test_finite_loop_freezes_selection_before_holdout_and_replays(campaign_run, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    calls = []
    def evaluate(request):  # type: ignore[no-untyped-def]
        calls.append((request.variant.name, request.split))
        return TrialOutcome(passed=request.split == "train", details={"cohort_type": "scripted"})
    result = calibrate_noise(campaign_run, _plan(), evaluate)
    assert len(calls) == 12
    assert [split for _, split in calls] == ["train"] * 8 + ["holdout"] * 4
    assert result.report.selected_variants == ("clean", "stale")
    assert result.report.holes == ("unproposed",)
    assert all(v.estimate.successes == 4 for v in result.report.variants)
    assert all(v.holdout_estimate.successes == 0 for v in result.report.variants)
    assert all(v.holdout_status == "target_unmet" for v in result.report.variants)
    record_path = result.record.export(tmp_path / "record.json")
    def offline(_):  # type: ignore[no-untyped-def]
        raise AssertionError("offline replay called the evaluator")
    from worldloom.narrative.providers import DeterministicProvider
    monkeypatch.setattr(DeterministicProvider, "complete", lambda *_args, **_kwargs: pytest.fail("replay called template provider"))
    replay = calibrate_noise(campaign_run, _plan(), offline, recorded=NoiseCalibrationRecord.load(record_path))
    assert replay.report == result.report
    assert replay.record == result.record
    first = result.export(tmp_path / "first")
    second = replay.export(tmp_path / "second")
    assert {p.relative_to(first): p.read_bytes() for p in first.rglob("*") if p.is_file()} == {
        p.relative_to(second): p.read_bytes() for p in second.rglob("*") if p.is_file()}


def test_budget_and_uncertainty_preserve_holes(campaign_run):  # type: ignore[no-untyped-def]
    result = calibrate_noise(campaign_run, _plan(max_training_attempts=2, target_low=.4, target_high=.6),
                             lambda _: TrialOutcome(passed=True))
    assert result.report.status == "unfitted"
    assert result.report.training_budget_exhausted
    assert not result.report.selected_variants
    assert result.report.holdout_attempts == 0
    assert len(result.record.attempts) == 2


def test_quality_inputs_missing_do_not_train(campaign_run):  # type: ignore[no-untyped-def]
    result = calibrate_noise(campaign_run, _plan(reader_id="independent-reader/v1"),
                             lambda _: pytest.fail("unreviewed candidate trained"))
    assert result.report.status == "unfitted"
    assert all(a.findings == ("reader_input_missing",) for a in result.record.attempts)
    assert not any(a.observation for a in result.record.attempts)


def test_sealed_plans_and_observations_refuse_conflicts(campaign_run):  # type: ignore[no-untyped-def]
    result = calibrate_noise(campaign_run, _plan(), lambda _: TrialOutcome(passed=True))
    with pytest.raises(ValueError, match="plan or baseline changed"):
        calibrate_noise(campaign_run, _plan(max_training_attempts=7), lambda _: TrialOutcome(passed=True), recorded=result.record)
    corrupted = result.record.model_dump(mode="json")
    corrupted["attempts"][0]["outcome"]["passed"] = False
    with pytest.raises(ValueError, match="receipt digest"):
        NoiseCalibrationRecord.model_validate(corrupted)
    changed = replace(campaign_run, attempts=campaign_run.attempts[:-1])
    with pytest.raises(ValueError, match="holdout"):
        calibrate_noise(changed, _plan(), lambda _: TrialOutcome(passed=True), recorded=result.record)


def test_prefix_resume_only_calls_remaining_trials(campaign_run):  # type: ignore[no-untyped-def]
    checkpoints = []
    result = calibrate_noise(campaign_run, _plan(), lambda _: TrialOutcome(passed=True), checkpoint=checkpoints.append)
    calls = []
    resumed = calibrate_noise(campaign_run, _plan(), lambda r: (calls.append(r.trial_id) or TrialOutcome(passed=True)),
                              recorded=checkpoints[4])
    assert len(calls) == 7
    assert resumed.record == result.record


def test_plan_rejects_reference_cohort_and_invalid_budgets():
    with pytest.raises(ValueError):
        _plan(evaluator_kind="reference_executor")
    with pytest.raises(ValueError):
        NoiseVariant(name="bad", budget={"made_up": 1}, niche="bad")
    with pytest.raises(ValueError):
        NoiseVariant(name="bad", budget={"staleness": 1.5}, niche="bad")


def test_fidelity_requires_measured_support_and_metric_thresholds(campaign_run):  # type: ignore[no-untyped-def]
    from worldloom.evals.calibration import MetricThreshold
    from worldloom.fidelity import compute

    plan = _plan(fidelity_config={"reference_digest": "controlled-example", "projection": "scripted/v1"},
                 fidelity_slices=("geo",),
                 fidelity_thresholds=(MetricThreshold(path=("univariate", "amount", "ks"), maximum=0),))
    rows = [{"geo": "north", "amount": 1}, {"geo": "south", "amount": 2}]
    calls = []
    result = calibrate_noise(campaign_run, plan, lambda _: TrialOutcome(passed=True),
                             fidelity=lambda world: (calls.append(world.seed) or compute(rows, rows, slices=("geo",))))
    assert result.report.selected_variants
    assert len(calls) == 12
    replay = calibrate_noise(campaign_run, plan, lambda _: pytest.fail("replay evaluator called"),
                             fidelity=lambda _: pytest.fail("replay fidelity called"), recorded=result.record)
    assert replay.record == result.record
    refused = calibrate_noise(campaign_run, plan, lambda _: pytest.fail("unsupported fidelity trained"),
                               fidelity=lambda _: compute(rows, rows[:1], slices=("geo",)))
    assert refused.report.status == "unfitted"
    assert all("fidelity_support_incomplete" in a.findings for a in refused.record.attempts)


def test_authentic_rejected_reader_is_recorded_and_replayed(campaign_run):  # type: ignore[no-untyped-def]
    from worldloom.narrative import reader_checks

    plan = _plan(reader_id="scripted-independent-reader/v1", reader_config={"share": 0.1})
    calls = []
    def read(world, instance):  # type: ignore[no-untyped-def]
        calls.append(world.seed)
        return reader_checks.accept(world, reader_checks.plan(world, reader_id=plan.reader_id, instances=(instance,), share=.1, reader_config=plan.reader_config))
    refused = calibrate_noise(campaign_run, plan, lambda _: pytest.fail("reader-rejected candidate trained"), read=read)
    assert calls
    assert all("reader_rejected" in a.findings and a.quality["reader"] for a in refused.record.attempts)
    replay = calibrate_noise(campaign_run, plan, lambda _: pytest.fail("replay evaluator called"),
                             read=lambda *_: pytest.fail("replay reader called"), recorded=refused.record)
    assert replay.record == refused.record


def test_callback_cannot_change_sealed_variant(campaign_run):  # type: ignore[no-untyped-def]
    def mutate(request):  # type: ignore[no-untyped-def]
        request.variant.budget["staleness"] = 99
        return TrialOutcome(passed=True)
    with pytest.raises(ValueError, match="sealed plan"):
        calibrate_noise(campaign_run, _plan(), mutate)


def test_nonmonotonic_observations_choose_supported_middle_variant(campaign_run):  # type: ignore[no-untyped-def]
    plan = _plan(variants=tuple(NoiseVariant(name=name, budget={"staleness": budget}, niche="decayed")
                               for name, budget in (("clean", 0), ("middle", 1), ("highest", 2))),
                 max_training_attempts=12)
    result = calibrate_noise(campaign_run, plan, lambda request: TrialOutcome(passed=request.variant.name == "middle"))
    assert result.report.selected_variants == ("middle",)
    assert result.report.holes == ("current", "unproposed")
    assert all(a.split == "train" or a.variant == "middle" for a in result.record.attempts)


def test_noise_preserves_authored_ir_and_native_bytes_and_materializes_new_intents(campaign_run):  # type: ignore[no-untyped-def]
    from worldloom.evals.calibration import world_digest
    from worldloom.narrative.providers import DeterministicProvider

    authored = campaign_run.map_worlds(lambda world: world.narrate(DeterministicProvider()).render("markdown"))
    before = tuple(world_digest(c.world) for c in authored.attempts)
    plan = _plan(target_low=0, min_support=1, max_training_attempts=2, max_holdout_attempts=2)
    result = calibrate_noise(authored, plan, lambda _: TrialOutcome(passed=True))
    assert result.report.selected_variants
    for _, campaign in result.campaigns:
        for candidate in campaign.selected:
            original = authored.attempts[candidate.plan.ordinal].world
            by_id = {ir.id: ir for ir in candidate.world.artifact_irs}
            assert all(by_id[ir.id] == ir for ir in original.artifact_irs)
            produced = {r.path: r.payload for r in candidate.world._rendered}
            assert all(produced[r.path] == r.payload for r in original._rendered)
            assert {intent.id for intent in candidate.world.artifact_intents} <= set(by_id)
    assert tuple(world_digest(c.world) for c in authored.attempts) == before


@pytest.mark.parametrize("budget,formats", [({"staleness": 1}, ("markdown",)), ({"mechanical": 1}, ("xlsx", "markdown"))])
def test_ordinary_recipe_replay_preserves_mixed_authors_and_native_noise(budget, formats, tmp_path):  # type: ignore[no-untyped-def]
    from worldloom.corpus import tree_divergence
    from worldloom.evals.calibration import _noise_world
    from worldloom.narrative import handshake
    from worldloom.narrative.providers import DeterministicProvider, UnreachableProvider
    from worldloom.recipe import rebuild

    author = DeterministicProvider()
    author.id = "scripted-original-author/v1"
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03", include_operational_incident=True))
    world = world.narrate(author).render(*formats)
    noisy = _noise_world(world, NoiseVariant(name="noise", budget=budget, niche="decayed"), ())
    assert not handshake.pending(noisy)
    original = {ir.id: ir for ir in world.artifact_irs}
    assert all(ir == original[ir.id] for ir in noisy.artifact_irs if ir.id in original)
    assert len(noisy.artifact_irs) > len(world.artifact_irs)
    models = tuple(sorted({ir.metadata["narrated_by"] for ir in noisy.artifact_irs if "narrated_by" in ir.metadata}))
    assert author.id in models
    if budget.get("staleness"):
        assert "worldloom-noise-template/v1" in models
    reconstructed = rebuild(noisy.recipe, ledger=tuple(noisy.ledger)).compile().narrate(
        UnreachableProvider(allowed_model_ids=models), ledger=tuple(noisy.ledger),
    ).render(*formats)
    assert reconstructed._narration[0] == 0
    expected = noisy.export(tmp_path / "expected")
    actual = reconstructed.export(tmp_path / "actual")
    assert tree_divergence(expected, actual) is None
    if budget.get("mechanical"):
        from worldloom.models import ErrorType
        mechanical = [error for error in noisy.intentional_errors if error.error_type in {ErrorType.HARDCODED_VALUE, ErrorType.SHORT_RANGE}]
        assert mechanical
        rendered = {item.artifact_id for item in noisy._rendered if item.path.endswith(".xlsx")}
        assert all(error.artifact_id in rendered for error in mechanical)


def test_mixed_author_replay_refuses_ambiguous_current_receipts():
    from worldloom.narrative.compiler import NarrationError
    from worldloom.narrative.providers import DeterministicProvider, UnreachableProvider

    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    one = DeterministicProvider()
    one.id = "scripted-one"
    two = DeterministicProvider()
    two.id = "scripted-two"
    first = world.narrate(one)
    second = world.narrate(two)
    with pytest.raises(NarrationError, match="ambiguous narration replay"):
        world.narrate(UnreachableProvider(allowed_model_ids=(one.id, two.id)), ledger=tuple(first.ledger) + tuple(second.ledger))
