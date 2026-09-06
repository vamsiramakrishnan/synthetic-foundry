"""Calibration: ranges cross the boundary, rows never do, and the receipt says how.

The contract has four halves. With enough rows and budget, the seeded estimator
recovers the band the data actually has. The snapshot carries no value from the
source — checked by looking for them. A seeded release says it is not private
and an unseeded one says it is. And a snapshot is exactly what ``build
--priors`` reads, landing in the recipe as physics overrides whose ``source``
names the calibration.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import calibrate
from worldloom.cli import app
from worldloom.parameters import DEFAULT, Span
from worldloom.providers import PriorEstimator
from worldloom.rng import Rng

runner = CliRunner()

SCHEMA = {
    "unit": "unit",
    "contribution_bound": 1,
    "columns": [
        {"column": "miss", "parameter": "retail.revenue.miss_pct", "clip": [-0.25, 0.10], "bins": 70},
        {"column": "margin", "parameter": "retail.margin.budget", "clip": [0.05, 0.70], "bins": 65},
    ],
}


def _rows(n: int, seed: int = 1) -> list[dict]:
    rng = Rng(seed).derive("calibration")
    # A triangular-ish band: uniform draws so the 10th/90th percentiles are known.
    return [
        {"unit": f"U{index}",
         "miss": round(rng.derive(f"m{index}").number(-0.06, 0.0), 4),
         "margin": round(rng.derive(f"g{index}").number(0.22, 0.32), 4),
         "secret_note": f"customer-{index}-{seed}"}
        for index in range(n)
    ]


def test_the_estimator_satisfies_the_protocol() -> None:
    assert isinstance(calibrate.LaplaceHistogramEstimator(), PriorEstimator)


def test_with_enough_rows_the_band_is_recovered() -> None:
    snapshot = calibrate.calibrate(
        _rows(4000), SCHEMA, epsilon=2.0,
        estimator=calibrate.LaplaceHistogramEstimator(noise_seed=11),
    )
    miss = snapshot.spans["retail.revenue.miss_pct"]
    margin = snapshot.spans["retail.margin.budget"]
    # Uniform on [-0.06, 0] has q10 = -0.054, q90 = -0.006; one cell is 0.005 wide.
    assert abs(miss["low"] - (-0.054)) < 0.012 and abs(miss["high"] - (-0.006)) < 0.012
    assert abs(margin["low"] - 0.23) < 0.02 and abs(margin["high"] - 0.31) < 0.02
    assert snapshot.noisy == []
    assert snapshot.quality["retail.margin.budget"]["values_read"] == 4000


def test_nothing_from_the_source_is_in_the_snapshot() -> None:
    rows = _rows(500)
    snapshot = calibrate.calibrate(rows, SCHEMA, epsilon=1.0,
                                   estimator=calibrate.LaplaceHistogramEstimator(noise_seed=1))
    payload = snapshot.model_dump(mode="json")
    text = json.dumps(payload)
    assert "secret_note" not in text and "customer-" not in text and '"U1' not in text
    # Structurally: two spans, each nothing but a range and its provenance.
    assert set(snapshot.spans) == {"retail.revenue.miss_pct", "retail.margin.budget"}
    for span in snapshot.spans.values():
        assert set(span) <= {"low", "high", "kind", "places", "about", "source"}
    assert set(payload) == {"schema_version", "spans", "receipt", "about", "quality"}
    assert set(payload["quality"]["retail.margin.budget"]) == {"values_read", "expected_noise_mass", "noise_share"}


def test_a_seeded_release_is_deterministic_and_says_it_is_not_private() -> None:
    a = calibrate.calibrate(_rows(300), SCHEMA, epsilon=1.0,
                            estimator=calibrate.LaplaceHistogramEstimator(noise_seed=5))
    b = calibrate.calibrate(_rows(300), SCHEMA, epsilon=1.0,
                            estimator=calibrate.LaplaceHistogramEstimator(noise_seed=5))
    assert a.spans == b.spans and a.receipt.key == b.receipt.key
    assert not a.private and a.receipt.privacy.noise_source == "seeded"
    assert "NOT a private release" in a.spans["retail.margin.budget"]["source"]


def test_an_unseeded_release_is_private_and_not_reproducible() -> None:
    a = calibrate.calibrate(_rows(300), SCHEMA, epsilon=1.0)
    b = calibrate.calibrate(_rows(300), SCHEMA, epsilon=1.0)
    assert a.private and a.receipt.privacy.mechanism == "laplace-histogram"
    assert a.receipt.privacy.epsilon == 1.0 and a.receipt.privacy.queries == 2
    assert a.spans != b.spans, "system-entropy noise is not a seed"
    assert a.receipt.configuration_digest == b.receipt.configuration_digest
    assert a.receipt.key != b.receipt.key


def test_contribution_bounding_is_enforced_not_assumed() -> None:
    rows = [{**row, "unit": f"U{index % 10}"} for index, row in enumerate(_rows(500))]
    schema = {**SCHEMA, "contribution_bound": 3}
    snapshot = calibrate.calibrate(rows, schema, epsilon=1.0,
                                   estimator=calibrate.LaplaceHistogramEstimator(noise_seed=1))
    assert snapshot.quality["retail.margin.budget"]["values_read"] == 30
    assert snapshot.receipt.privacy.sensitivity == 3.0
    assert snapshot.receipt.privacy.contribution_bound == 3
    assert snapshot.noisy == ["retail.margin.budget", "retail.revenue.miss_pct"]


def test_lint_refuses_what_a_build_could_not_use() -> None:
    bad = calibrate.CalibrationSchema.model_validate({
        "columns": [
            {"column": "a", "parameter": "retail.margin.budgt", "clip": [0, 1]},
            {"column": "b", "parameter": "ops.incident.likelihood", "clip": [0, 1]},
            {"column": "c", "parameter": "retail.margin.budget", "clip": [1, 0]},
            {"column": "d", "parameter": "retail.margin.budget", "clip": [0, 1], "quantiles": [0.9, 0.1]},
        ],
    })
    findings = "\n".join(calibrate.lint(bad))
    for expected in ("does not carry", "a chance", "is not a range", "informed by two columns", "quantiles"):
        assert expected in findings, expected
    with pytest.raises(ValueError, match="lint findings"):
        calibrate.calibrate(_rows(10), bad, epsilon=1.0)
    with pytest.raises(ValueError, match="epsilon"):
        calibrate.calibrate(_rows(10), SCHEMA, epsilon=0.0)


def test_the_snapshot_is_physics_the_registry_accepts_and_round_trips(tmp_path: Path) -> None:
    snapshot = calibrate.calibrate(_rows(300), SCHEMA, epsilon=1.0,
                                   estimator=calibrate.LaplaceHistogramEstimator(noise_seed=2))
    physics = DEFAULT.with_overrides(snapshot.overrides())
    span = physics.span("retail.margin.budget")
    assert isinstance(span, Span) and span.places == 4 and "calibrated from column" in span.source
    path = snapshot.write(tmp_path / "priors.json")
    assert calibrate.PriorSnapshot.read(path) == snapshot


def test_cli_calibrates_and_a_build_carries_the_priors_on_its_recipe(tmp_path: Path) -> None:
    source = tmp_path / "actuals.csv"
    rows = _rows(600)
    with source.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["unit", "miss", "margin"])
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row[k] for k in ("unit", "miss", "margin")})
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(SCHEMA))
    out = tmp_path / "priors.json"
    result = runner.invoke(app, [
        "calibrate", "--from", str(source), "--schema", str(schema),
        "--epsilon", "1.5", "--noise-seed", "3", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "not a private release" in result.output
    snapshot = calibrate.PriorSnapshot.read(out)
    assert snapshot.receipt.source_digest

    corpus = tmp_path / "corpus"
    built = runner.invoke(app, ["build", "--seed", "8128", "--priors", str(out), "--out", str(corpus)])
    assert built.exit_code == 0, built.output
    recipe = json.loads((corpus / "world.json").read_text())["recipe"]
    assert set(recipe["physics"]) == {"retail.revenue.miss_pct", "retail.margin.budget"}
    assert "calibrated from column 'margin'" in recipe["physics"]["retail.margin.budget"]["source"]
    assert runner.invoke(app, ["validate", str(corpus)]).exit_code == 0

    template = runner.invoke(app, ["calibrate", "--template"])
    assert template.exit_code == 0 and "columns" in json.loads(template.output)
    neither = runner.invoke(app, ["calibrate"])
    assert neither.exit_code == 2
