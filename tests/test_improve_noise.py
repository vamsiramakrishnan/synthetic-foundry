"""Noise-aware gates: repeats, a paired bootstrap over per-case means, and the noise floor.

The agent under test here is stochastic but deterministic: whether it walks
a case's expected DAG (and scores well) or does nothing is a draw from a
SHA-256 of a salt, its policy's digest, the case and how many times this
policy has run this case before. A policy that teaches `verify` succeeds more
often than one that does not, by as much as a test asks. So one run a side
can promote by luck exactly as a real agent can, and five runs a side is
what shows it was luck. Every draw is a pure function of its inputs, so each
test is reproducible to the byte.
"""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any

import pytest
from typer.testing import CliRunner

from worldloom import RetailWorld, packkit
from worldloom.cli import app
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.evalrun import (
    ReferenceAgent,
    ScriptedAgent,
    cases_from_corpus,
    run_cases,
    service_for,
)
from worldloom.evalrun.grader import grader_identity
from worldloom.evalrun.improve import Gate, Improver, improve, judge, judge_paired
from worldloom.evalrun.noise import (
    Interval,
    PairedComparison,
    interval,
    minimum_detectable_effect,
    noise,
    noise_floor,
    paired,
    t_quantile,
)
from worldloom.evalrun.policy import agent_name, pack_record
from worldloom.evalrun.results import compare, read_run
from worldloom.evalrun.runner import RunReport
from worldloom.packkit import diffs
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

runner = CliRunner()

#: The Gate keys a single-run receipt has always carried; repeats add none of theirs at k=1.
SINGLE_RUN_GATE_KEYS = {"name", "passed", "reasons", "compared", "mean_delta", "axis_deltas", "improvements",
                        "regressions", "newly_errored", "value_delta"}
#: A salt under which a candidate barely better than the champion wins one run
#: a side by luck (found once by search, then fixed: the draws are deterministic).
LUCK_SALT = "luck-17"


@pytest.fixture(scope="module")
def corpus() -> Any:
    world = RetailWorld(seed=8128).build()
    program = with_parameters(retail(stores=2, products=3, ticks=12), {"initial_stock": 8, "target_stock": 15})
    rule = IncidentRule(table="inventory", signal="lost", title="Stock availability")
    harness = (
        EnterpriseEvalHarness.from_world(world)
        .with_scenario(operational_profile("retail"))
        .with_operational_data(Simulator(program, seed=8128), rule, include_world_records=False)
        .exhaustive().take(8)
        .with_dag_grammar("map_read", "conditional", "fan_in", "write_chain")
    )
    built, _ = harness.build()
    return built


def _skilled(pack: Any) -> bool:
    return "verify" in pack.body.skills or "skills/verify/SKILL.md" in pack.body.files


class StochasticAgent:
    """Walks the expected DAG with a probability its policy sets; otherwise does nothing.

    The draw for a case is a SHA-256 of the salt, the policy's digest, the
    case id and the attempt: the how-many-th time this policy has run this
    case in this test, counted in *attempts* shared across agent instances.
    """

    def __init__(self, pack: Any, cases: Any, *, rates: tuple[float, float], salt: str,
                 attempts: dict[tuple[str, str], int], log: list[str]) -> None:
        self.pack = pack
        self.name = agent_name("policy", pack)
        self.pack_record = pack_record(pack)
        self.rate = rates[1] if _skilled(pack) else rates[0]
        self.salt = salt
        self.attempts = attempts
        self.reference = ReferenceAgent(cases)
        self.idle = ScriptedAgent([], name="idle")
        self.log = log

    def run(self, task: Any, tools: Any) -> Any:
        key = (self.pack.digest, task.case_id)
        attempt = self.attempts.get(key, 0)
        self.attempts[key] = attempt + 1
        self.log.append(self.pack.digest)
        draw = hashlib.sha256(f"{self.salt}\0{self.pack.digest}\0{task.case_id}\0{attempt}".encode()).hexdigest()
        succeeds = int(draw[:12], 16) / float(16 ** 12) < self.rate
        return (self.reference if succeeds else self.idle).run(task, tools)


def _proposer(change: dict[str, Any]) -> Any:
    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        return {"request_id": payload["request_id"], "message": "revised",
                "proposal": {"name": payload["draft"]["name"], "body": {**payload["draft"]["body"], **change}}}

    return exchange


_VERIFY = {"skills": {"verify": "Walk every step the request needs and read each write back."}}


def _loop(corpus: Any, out: Path, *, rates: tuple[float, float] = (0.0, 1.0), salt: str = "fixed",
          log: list[str] | None = None, exchange: Any = None, **options: Any) -> Any:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    attempts: dict[tuple[str, str], int] = {}
    calls = log if log is not None else []

    def run(subset: Any, agent: Any) -> Any:
        return run_cases(service_for(subset, records), subset, agent)

    def agent_for(pack: Any) -> Any:
        return StochasticAgent(pack, cases, rates=rates, salt=salt, attempts=attempts, log=calls)

    return improve(packkit.resolve("agent:baseline"), cases, run=run, agent_for=agent_for,
                   exchange=exchange or _proposer(_VERIFY), out=out, holdout_share=0.4, **options)


def _files(root: Path) -> dict[str, bytes]:
    return {str(path.relative_to(root)): path.read_bytes() for path in sorted(root.rglob("*")) if path.is_file()}


# -- repeats = 1 is the loop as it was ------------------------------------------------


def test_one_repeat_writes_exactly_what_the_single_run_loop_wrote(corpus: Any, tmp_path: Path) -> None:
    default = _loop(corpus, tmp_path / "default", rounds=2)
    explicit = _loop(corpus, tmp_path / "explicit", rounds=2, repeats=1)
    assert default.rounds[0].decision == "promoted"
    assert _files(tmp_path / "default") == _files(tmp_path / "explicit")
    # Nothing a repeat adds reaches a single-run receipt, improve.json or the run layout.
    for path in sorted((tmp_path / "default" / "rounds").glob("*.json")):
        stored = json.loads(path.read_text(encoding="utf-8"))
        for gate in (stored.get("train"), stored.get("holdout")):
            assert gate is None or set(gate) == SINGLE_RUN_GATE_KEYS
    assert "repeats" not in json.loads((tmp_path / "default" / "improve.json").read_text(encoding="utf-8"))
    assert not list((tmp_path / "default" / "runs").rglob("rep-*"))
    # The gates are the existing single-run rules over the single runs on disk.
    first = default.rounds[0]
    runs = tmp_path / "default" / "runs"
    for gate, label, strict, bar in ((first.train, "train", False, 0.1), (first.holdout, "holdout", True, 0.0)):
        champion = read_run(next(runs.glob(f"baseline@*/{label}")))
        candidate = read_run(next(runs.glob(f"baseline-r1@*/{label}")))
        expected = judge(compare(champion, candidate), name=label, min_delta=bar, strict=strict,
                         max_axis_regression=0.1)
        assert gate is not None
        assert gate.model_dump(mode="json") == expected.model_dump(mode="json")
    assert explicit.model_dump(mode="json", by_alias=True) == default.model_dump(mode="json", by_alias=True)


def test_repeats_below_one_are_refused(corpus: Any, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="repeats"):
        _loop(corpus, tmp_path / "zero", rounds=1, repeats=0)


# -- luck and a real gain -------------------------------------------------------------


def test_a_lucky_single_run_is_promoted_and_five_repeats_refuse_it(corpus: Any, tmp_path: Path) -> None:
    # The candidate's true gain is small next to the noise: it walks the
    # DAG 55% of the time where the champion walks it 50%.
    rates = (0.5, 0.55)
    single = _loop(corpus, tmp_path / "k1", rates=rates, salt=LUCK_SALT, rounds=1)
    assert single.rounds[0].decision == "promoted", single.rounds[0].reasons
    guarded = _loop(corpus, tmp_path / "k5", rates=rates, salt=LUCK_SALT, rounds=1, repeats=5)
    receipt = guarded.rounds[0]
    assert receipt.decision == "rejected", receipt.reasons
    gate = receipt.holdout if receipt.holdout is not None and not receipt.holdout.passed else receipt.train
    assert gate is not None and not gate.passed and gate.repeats == 5 and gate.method == "bootstrap"
    assert gate.ci_low is not None and gate.ci_low <= 0 < (gate.ci_high or 0)
    assert any("lower bound" in reason for reason in gate.reasons)
    assert guarded.repeats == 5
    assert json.loads((tmp_path / "k5" / "improve.json").read_text(encoding="utf-8"))["repeats"] == 5


def test_a_real_gain_is_promoted_at_five_repeats(corpus: Any, tmp_path: Path) -> None:
    report = _loop(corpus, tmp_path / "real", rates=(0.1, 0.95), salt="real", rounds=1, repeats=5)
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    for gate in (receipt.train, receipt.holdout):
        assert gate is not None and gate.passed and gate.repeats == 5
        assert gate.ci_low is not None and gate.ci_high is not None and gate.stderr is not None
        assert gate.ci_low > 0 and gate.ci_low <= gate.mean_delta <= gate.ci_high
        assert gate.t_low is not None and gate.t_high is not None and gate.confidence == 0.95
        # Both policies are stochastic here, so each has a floor to report.
        assert gate.noise_floor_champion is not None and gate.noise_floor_champion > 0
        assert gate.noise_floor_candidate is not None and gate.noise_floor_candidate > 0
        assert set(gate.axis_intervals) == {"plan", "trajectory", "outcomes"}
    stored = json.loads((tmp_path / "real" / "rounds" / "001.json").read_text(encoding="utf-8"))
    assert stored["train"]["repeats"] == 5 and stored["train"]["method"] == "bootstrap"
    runs = tmp_path / "real" / "runs"
    for pack in ("baseline", "baseline-r1"):
        for label in ("train", "holdout"):
            reps = sorted(path.name for path in next(runs.glob(f"{pack}@*")).joinpath(label).iterdir())
            assert reps == [f"rep-{index}" for index in range(1, 6)]
    held = json.loads(next(runs.glob("baseline-r1@*/holdout/rep-3/run.json")).read_text(encoding="utf-8"))
    assert held["split"] == "holdout" and held["agent_pack"]["digest"] == receipt.candidate["digest"]


def test_resume_reuses_every_finished_repeat(corpus: Any, tmp_path: Path) -> None:
    out = tmp_path / "resume"
    first: list[str] = []
    report = _loop(corpus, out, rates=(0.1, 0.95), salt="resume", rounds=1, repeats=3, log=first)
    assert first
    # A round interrupted before its receipt pays for nothing it already ran.
    (out / "rounds" / "001.json").unlink()
    (out / "improve.json").unlink()
    second: list[str] = []
    again = _loop(corpus, out, rates=(0.1, 0.95), salt="resume", rounds=1, repeats=3, log=second)
    assert not second
    assert again.rounds[0] == report.rounds[0]
    # One repeat lost is one repeat paid for again, and nothing else.
    candidate = report.rounds[0].candidate["digest"]
    lost = out / "runs" / f"baseline-r1@{candidate[:12]}" / "train" / "rep-2"
    for path in sorted(lost.iterdir()):
        path.unlink()
    lost.rmdir()
    (out / "rounds" / "001.json").unlink()
    (out / "improve.json").unlink()
    third: list[str] = []
    _loop(corpus, out, rates=(0.1, 0.95), salt="resume", rounds=1, repeats=3, log=third)
    assert third and set(third) == {candidate}
    assert len(third) == report.train_cases


def test_ablation_over_repeats_drops_a_hunk_only_when_its_interval_says_so(corpus: Any, tmp_path: Path) -> None:
    verify = ("---\nname: verify\ndescription: Use after any write, to confirm it held.\n---\n\n"
              "Walk every step the request needs and read each write back.\n")
    notes = "---\nname: notes\ndescription: Background on the connectors.\n---\n\nNothing here changes anything.\n"

    def exchange(payload: dict[str, Any]) -> dict[str, Any]:
        base = payload["draft_tree"]
        files = {"skills/notes/SKILL.md": notes, "skills/verify/SKILL.md": verify}
        return {"request_id": payload["request_id"], "message": "patched",
                "proposal": {"name": payload["draft"]["name"], "diff": diffs.render(base, {**base, **files})}}

    report = _loop(corpus, tmp_path / "ablate", rates=(0.0, 1.0), rounds=1, repeats=3, exchange=exchange)
    receipt = report.rounds[0]
    assert receipt.decision == "promoted", receipt.reasons
    ablation = receipt.ablation
    assert ablation is not None and ablation.reduced
    by_file = {hunk.file: hunk for hunk in ablation.hunks}
    dropped, kept = by_file["skills/notes/SKILL.md"], by_file["skills/verify/SKILL.md"]
    assert dropped.decision == "dropped" and dropped.ci_high is not None and dropped.ci_high < ablation.tolerance
    assert kept.decision == "kept" and kept.contribution is not None and kept.contribution >= 0.1
    assert ablation.reduced_train is not None and ablation.reduced_train.repeats == 3


# -- the arithmetic -------------------------------------------------------------------


def test_the_t_interval_on_a_hand_computed_sample() -> None:
    # Differences 0.1, 0.2, 0.3, 0.4: mean 0.25, sample sd sqrt(0.05 / 3),
    # standard error 0.0645497, t(0.975, 3) = 3.1824463, half-width 0.2054262.
    assert t_quantile(0.975, 3) == pytest.approx(3.1824463, abs=1e-6)
    assert t_quantile(0.975, 1000) == pytest.approx(1.9623391, abs=1e-6)
    assert t_quantile(0.025, 3) == pytest.approx(-3.1824463, abs=1e-6)
    result = interval([0.1, 0.2, 0.3, 0.4], confidence=0.95, resamples=2000, seed="hand")
    assert result.cases == 4 and result.mean == 0.25
    assert result.stderr == pytest.approx(0.0645497, abs=1e-6)
    assert result.t_low == pytest.approx(0.044574, abs=1e-5) and result.t_high == pytest.approx(0.455426, abs=1e-5)
    # The bootstrap's bounds lie inside the sample's range and around its mean.
    assert result.ci_low is not None and result.ci_high is not None
    assert 0.1 <= result.ci_low < 0.25 < result.ci_high <= 0.4
    # A sample with no spread has an interval of one point.
    flat = interval([0.2, 0.2, 0.2], confidence=0.95, resamples=500, seed="flat")
    assert (flat.ci_low, flat.ci_high, flat.stderr) == (0.2, 0.2, 0.0)
    # Weighted: each case keeps its weight in every resample.
    weighted = interval([0.1, 0.2, 0.3, 0.4], confidence=0.95, resamples=500, seed="w", weights=[1, 1, 1, 5])
    assert weighted.mean == pytest.approx(0.325)
    # One case has a mean and no interval.
    single = interval([0.3], confidence=0.95, resamples=500, seed="one")
    assert single.mean == 0.3 and single.ci_low is None and single.stderr is None


def test_the_bootstrap_is_deterministic_and_seeded_by_what_it_compares() -> None:
    sample = [0.5, -0.1, 0.2, 0.0, 0.3, 0.9, -0.4]
    first = interval(sample, confidence=0.9, resamples=1000, seed="a")
    assert first == interval(sample, confidence=0.9, resamples=1000, seed="a")
    other = interval(sample, confidence=0.9, resamples=1000, seed="b")
    assert other.mean == first.mean and other.t_low == first.t_low
    assert (other.ci_low, other.ci_high) != (first.ci_low, first.ci_high)
    with pytest.raises(ValueError):
        interval(sample, confidence=0.9, resamples=10, seed="a")


def _rescored(base: RunReport, scores: dict[str, float | None], *, pack: str = "p1") -> RunReport:
    """*base* with each listed case's overall score replaced (``None``: the case errored)."""
    rows = []
    for row in base.results:
        if row.case_id not in scores:
            continue
        value = scores[row.case_id]
        if value is None:
            rows.append(row.model_copy(update={"status": "error", "score": None, "error": "boom"}))
        else:
            assert row.score is not None
            rows.append(row.model_copy(update={"status": "graded", "error": None,
                                               "score": row.score.model_copy(update={"score": value})}))
    return base.model_copy(update={"results": tuple(rows), "agent_pack": {"ref": f"agent:{pack}", "digest": pack}})


@pytest.fixture(scope="module")
def base_run(corpus: Any) -> RunReport:
    cases = cases_from_corpus(corpus)
    return run_cases(service_for(cases, corpus.connector_data.records), cases, ReferenceAgent(cases))


def test_noise_floor_and_minimum_detectable_effect(base_run: RunReport) -> None:
    a, b = base_run.results[0].case_id, base_run.results[1].case_id
    runs = [_rescored(base_run, {a: 0.2, b: 1.0}), _rescored(base_run, {a: 0.4, b: 1.0})]
    # Case a deviates by 0.1 each way (squares 0.02), case b not at all; two
    # degrees of freedom: pooled sd = sqrt(0.02 / 2) = 0.1.
    assert noise_floor(runs) == pytest.approx(0.1)
    assert noise_floor(runs[:1]) is None
    # (z(0.975) + z(0.8)) * sqrt(2 * 0.01 / (2 * 2)) = 2.8015853 * 0.0707107.
    expected = (1.959963985 + 0.841621234) * math.sqrt(2 * 0.01 / 4)
    assert minimum_detectable_effect(0.1, cases=2, repeats=2, confidence=0.95, power=0.8) == pytest.approx(expected, abs=1e-6)
    report = noise(runs)
    assert report.runs == 2 and report.cases == 2 and report.repeated_cases == 2
    assert report.pooled_std == pytest.approx(0.1)
    assert report.minimum_detectable_effect == pytest.approx(expected, abs=1e-6)
    assert report.by_repeats["2"] == report.minimum_detectable_effect
    assert report.by_repeats["10"] is not None and report.by_repeats["10"] < report.by_repeats["1"]  # type: ignore[operator]
    by_case = {item.case_id: item for item in report.per_case}
    assert by_case[a].mean == pytest.approx(0.3) and by_case[a].std == pytest.approx(0.141421, abs=1e-6)
    assert by_case[b].std == 0.0
    # Sized for another experiment: 40 cases at 5 repeats a side.
    sized = noise(runs, cases=40, repeats=5)
    assert sized.minimum_detectable_effect == pytest.approx((1.959963985 + 0.841621234) * math.sqrt(2 * 0.01 / 200), abs=1e-6)
    # Runs of two policies are not noise.
    with pytest.raises(ValueError, match="different agents or policies"):
        noise([runs[0], _rescored(base_run, {a: 0.4, b: 1.0}, pack="p2")])


def test_paired_newly_errored_needs_a_majority_of_candidate_repeats(base_run: RunReport) -> None:
    a, b, c = (row.case_id for row in base_run.results[:3])
    champion = [_rescored(base_run, {a: 0.5, b: 0.5, c: 0.5}) for _ in range(3)]
    candidate = [_rescored(base_run, {a: None, b: None, c: 0.9}, pack="p2"),
                 _rescored(base_run, {a: None, b: 0.9, c: 0.9}, pack="p2"),
                 _rescored(base_run, {a: 0.9, b: 0.9, c: 0.9}, pack="p2")]
    result = paired(champion, candidate, resamples=500)
    # a errored in 2 of 3 candidate repeats: newly errored. b in 1 of 3: not.
    assert result.newly_errored == (a,)
    assert result.baseline_repeats == result.recent_repeats == 3
    assert result.overall is not None and result.overall.cases == 3
    assert result.case_deltas[c] == pytest.approx(0.4)
    assert result == paired(champion, candidate, resamples=500)
    gate = judge_paired(result, name="train", min_delta=0.1, strict=False, max_axis_regression=0.1)
    assert not gate.passed and any("errored" in reason for reason in gate.reasons)


def test_paired_value_weighting_uses_the_same_per_case_means(base_run: RunReport) -> None:
    a, b = base_run.results[0].case_id, base_run.results[1].case_id
    champion = [_rescored(base_run, {a: 0.5, b: 0.5}) for _ in range(2)]
    candidate = [_rescored(base_run, {a: 0.9, b: 0.3}, pack="p2"), _rescored(base_run, {a: 0.7, b: 0.3}, pack="p2")]
    plain = paired(champion, candidate, resamples=500)
    weighted = paired(champion, candidate, resamples=500, values={a: 1.0, b: 3.0})
    # Per-case means: a +0.3, b -0.2. Plain mean 0.05; weighted (0.3 - 0.6) / 4.
    assert plain.overall is not None and plain.overall.mean == pytest.approx(0.05)
    assert weighted.value is not None and weighted.value.mean == pytest.approx(-0.075)
    gate = judge_paired(weighted, name="holdout", min_delta=0.0, strict=True, max_axis_regression=0.1)
    assert any(reason.startswith("value-weighted") for reason in gate.reasons)


def test_an_axis_fails_only_when_its_whole_interval_is_a_regression() -> None:
    def estimate(mean: float, low: float, high: float) -> Interval:
        return Interval(cases=10, mean=mean, stderr=0.05, ci_low=low, ci_high=high, t_low=low, t_high=high)

    comparison = PairedComparison(
        baseline_repeats=3, recent_repeats=3, same_case_set=True, grader_mismatch=False, compared=10,
        confidence=0.95, resamples=2000, seed="s", overall=estimate(0.3, 0.2, 0.4),
        axes={"plan": estimate(-0.3, -0.5, 0.05), "trajectory": estimate(-0.3, -0.5, -0.15),
              "outcomes": estimate(0.5, 0.4, 0.6)},
        case_deltas={}, improvements=(), regressions=(), newly_errored=(),
        noise_floor_baseline=0.1, noise_floor_recent=0.12)
    gate = judge_paired(comparison, name="train", min_delta=0.1, strict=False, max_axis_regression=0.1)
    assert not gate.passed
    assert gate.reasons == ("the trajectory axis fell: its interval's upper bound -0.15 is below -0.1",)
    assert gate.axis_deltas == {"plan": -0.3, "trajectory": -0.3, "outcomes": 0.5}
    # The training rule: a lower bound at the minimum passes, the held-out rule needs it above.
    passing = comparison.model_copy(update={"axes": {}, "overall": estimate(0.2, 0.0, 0.4)})
    assert judge_paired(passing, name="train", min_delta=0.1, strict=False, max_axis_regression=0.1).passed
    assert not judge_paired(passing, name="holdout", min_delta=0.0, strict=True, max_axis_regression=0.1).passed
    low = comparison.model_copy(update={"axes": {}, "overall": estimate(0.05, 0.01, 0.1)})
    assert judge_paired(low, name="train", min_delta=0.1, strict=False, max_axis_regression=0.1).reasons == (
        "mean delta 0.05 is not at least 0.1",)
    dump = Gate.model_validate(gate.model_dump(mode="json")).model_dump(mode="json")
    assert dump["repeats"] == 3 and dump["noise_floor_candidate"] == 0.12


def test_improver_runs_each_repeat_into_its_own_directory(corpus: Any, tmp_path: Path) -> None:
    cases = cases_from_corpus(corpus)
    records = corpus.connector_data.records
    attempts: dict[tuple[str, str], int] = {}
    improver = Improver(run=lambda subset, agent: run_cases(service_for(subset, records), subset, agent),
                        agent_for=lambda pack: StochasticAgent(pack, cases, rates=(0.5, 0.5), salt="dirs",
                                                               attempts=attempts, log=[]),
                        exchange=_proposer({}), out=tmp_path / "dirs", repeats=2)
    reports = improver._pinned_runs(packkit.resolve("agent:baseline"), cases, "train", grader_identity(None))
    assert len(reports) == 2
    assert sorted(path.name for path in next((tmp_path / "dirs" / "runs").glob("baseline@*")).joinpath("train").iterdir()) == ["rep-1", "rep-2"]
    assert improver._pinned_runs(packkit.resolve("agent:baseline"), cases, "train", grader_identity(None)) == reports


# -- the CLI --------------------------------------------------------------------------


def test_cli_noise_reads_repeats_and_sizes_an_experiment(corpus: Any, tmp_path: Path) -> None:
    out = tmp_path / "cli"
    _loop(corpus, out, rates=(0.5, 0.5), salt="cli", rounds=1, repeats=3)
    train = next((out / "runs").glob("baseline@*/train"))
    result = runner.invoke(app, ["evalrun", "noise", str(train), "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["schema"] == "worldloom.eval-noise/v1" and payload["runs"] == 3
    reports = [read_run(train / f"rep-{index}") for index in range(1, 4)]
    assert payload == noise(reports).model_dump(mode="json", by_alias=True)
    explicit = runner.invoke(app, ["evalrun", "noise", *(str(train / f"rep-{index}") for index in range(1, 4)),
                                   "--cases", "40", "--repeats", "5", "--json"])
    assert explicit.exit_code == 0, explicit.output
    assert json.loads(explicit.output)["sized_cases"] == 40 and json.loads(explicit.output)["sized_repeats"] == 5
    text = runner.invoke(app, ["evalrun", "noise", str(train)])
    assert text.exit_code == 0 and "run-to-run std" in text.output and "minimum detectable effect" in text.output
    candidate = next((out / "runs").glob("baseline-r1@*/train"))
    mixed = runner.invoke(app, ["evalrun", "noise", str(train / "rep-1"), str(candidate / "rep-1")])
    assert mixed.exit_code != 0
    missing = runner.invoke(app, ["evalrun", "noise", str(tmp_path / "nowhere")])
    assert missing.exit_code != 0
