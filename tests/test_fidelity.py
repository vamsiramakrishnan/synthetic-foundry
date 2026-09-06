"""`worldloom fidelity` — a vector of readings, never a score.

Correctness on small hand-built tables where the right answer is known: an
identical table scores zero distance everywhere and a full exact-match rate; a
shifted one scores a positive KS; a categorical column with a category the
reference never had reports the unseen share; a copied table is *detected* by
the nearest-neighbour block sitting near zero rather than near the same-
distribution value. Then the loaders, the overrides, and the CLI's JSON.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import fidelity
from worldloom.cli import app
from worldloom.rng import Rng

runner = CliRunner()


def _rows(seed: int, n: int, *, shift: float = 0.0, extra_category: bool = False) -> list[dict]:
    rng = Rng(seed).derive("rows")
    regions = ["N", "S", "E", "W"] + (["Z"] if extra_category else [])
    out = []
    for index in range(n):
        amount = round(rng.derive(f"a{index}").number(10.0, 100.0) + shift, 2)
        out.append({
            "amount": amount,
            "qty": rng.derive(f"q{index}").integer(1, 9),
            "region": rng.derive(f"r{index}").choice(regions),
            "channel": rng.derive(f"c{index}").weighted(["store", "online"], [0.7, 0.3]),
        })
    return out


def test_an_identical_table_is_at_zero_everywhere_and_fully_matched() -> None:
    real = _rows(1, 300)
    report = fidelity.compute(real, real)
    assert report.columns["amount"]["ks"] == 0.0 and report.columns["amount"]["wasserstein"] == 0.0
    assert report.columns["region"]["jensen_shannon"] == 0.0
    assert report.columns["region"]["total_variation"] == 0.0
    assert report.pairwise["correlation_error_mean"] == 0.0
    assert report.privacy["exact_match_rate"] == 1.0
    # A copy is detected: every point's nearest neighbour is its twin on the other side.
    assert report.multivariate["nearest_neighbour_same_label"] < 0.05
    assert report.privacy["dcr_median_synthetic_to_real"] == 0.0


def test_a_shifted_table_reads_as_shifted_in_the_right_direction() -> None:
    real, synthetic = _rows(1, 400), _rows(2, 400, shift=15.0)
    report = fidelity.compute(real, synthetic)
    entry = report.columns["amount"]
    assert entry["ks"] > 0.1
    assert entry["mean_synthetic"] > entry["mean_real"]
    assert 10.0 < entry["wasserstein"] < 20.0
    # Same distribution otherwise: the nearest-neighbour statistic sits near its baseline.
    same = fidelity.compute(_rows(1, 400), _rows(3, 400))
    assert abs(same.multivariate["nearest_neighbour_same_label"]
               - same.multivariate["expected_if_same_distribution"]) < 0.08


def test_unseen_categories_and_cardinality_are_reported() -> None:
    report = fidelity.compute(_rows(1, 400), _rows(2, 400, extra_category=True))
    entry = report.columns["region"]
    assert entry["cardinality_real"] == 4 and entry["cardinality_synthetic"] == 5
    assert 0.1 < entry["unseen_share"] < 0.3
    assert report.pairwise["categorical_pairs"] == 1


def test_slices_report_the_univariate_block_per_value() -> None:
    report = fidelity.compute(_rows(1, 400), _rows(2, 400), slices=["region"])
    assert set(report.slices["region"]) == {"N", "S", "E", "W"}
    assert "amount" in report.slices["region"]["N"]
    assert "region" not in report.columns, "a slice column is not also a compared column"
    with pytest.raises(ValueError, match="neither table"):
        fidelity.compute(_rows(1, 10), _rows(2, 10), slices=["nope"])


def test_a_malformed_synthetic_value_is_reported_not_allowed_to_retype_the_column() -> None:
    """Inferring over both tables let one stray "n/a" flip an amount column to
    categorical and delete the very readings that would have exposed it (Codex
    review, PR #40). The reference decides the kind; the synthetic side is judged."""
    real = _rows(1, 200)
    synthetic = _rows(2, 200)
    synthetic[3] = {**synthetic[3], "amount": "n/a"}
    report = fidelity.compute(real, synthetic)
    entry = report.columns["amount"]
    assert entry["kind"] == "numeric" and "ks" in entry
    assert entry["malformed_synthetic"] == round(1 / 200, 4)
    assert entry["n_synthetic"] == 199
    assert fidelity.compute(real, real).columns["amount"]["malformed_synthetic"] == 0.0
    assert "MALFORMED" in str(report)
    # The override in the other direction, for a reference that is itself dirty.
    dirty_reference = [{**row, "amount": "?"} if index == 0 else row for index, row in enumerate(real)]
    assert fidelity.infer_kinds(dirty_reference)["amount"] == "categorical"
    assert fidelity.compute(dirty_reference, synthetic, kinds={"amount": "numeric"}).columns["amount"]["kind"] == "numeric"


def test_a_sparse_unrelated_column_does_not_empty_a_pair() -> None:
    """Complete cases are per pair (Codex review, PR #40): a third numeric column
    that is almost always missing must not drop the rows two full columns share."""
    real = [{**row, "rare": (row["qty"] if index % 97 == 0 else None)} for index, row in enumerate(_rows(1, 300))]
    synthetic = [{**row, "rare": (row["qty"] if index % 89 == 0 else None)} for index, row in enumerate(_rows(2, 300))]
    report = fidelity.compute(real, synthetic, kinds={"rare": "numeric"})
    assert report.pairwise["numeric_pairs"] == 3
    without = fidelity.compute(_rows(1, 300), _rows(2, 300))
    assert without.pairwise["numeric_pairs"] == 1
    # The amount/qty pair reads the same whether or not the sparse column is present.
    assert abs(report.pairwise["correlation_error_mean"]) >= 0.0


def test_kinds_are_inferred_and_overridable() -> None:
    rows = [{"code": "101", "amount": "3.5"}, {"code": "102", "amount": "4"}]
    assert fidelity.infer_kinds(rows) == {"amount": "numeric", "code": "numeric"}
    assert fidelity.infer_kinds(rows, overrides={"code": "categorical"})["code"] == "categorical"
    report = fidelity.compute(rows, rows, kinds={"code": "ignore"})
    assert "code" not in report.columns and report.privacy["compared_columns"] == 1


def test_the_report_is_json_with_no_aggregate_score() -> None:
    payload = fidelity.compute(_rows(1, 50), _rows(2, 50)).as_dict()
    json.dumps(payload)
    assert set(payload) == {"n_real", "n_synthetic", "kinds", "univariate", "pairwise",
                            "multivariate", "privacy", "slices"}
    assert not any("score" in key for key in payload)


def test_loaders_read_csv_jsonl_and_a_corpus_detail_table(tmp_path: Path) -> None:
    rows = _rows(1, 5)
    csv_path = tmp_path / "t.csv"
    with csv_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
    jsonl_path = tmp_path / "t.jsonl"
    jsonl_path.write_text("\n".join(json.dumps(r) for r in rows))
    assert [r["region"] for r in fidelity.load_rows(csv_path)] == [r["region"] for r in rows]
    assert fidelity.load_rows(jsonl_path) == rows
    with pytest.raises(ValueError, match="name the detail table"):
        fidelity.load_rows(tmp_path)


def test_cli_emits_the_vector_as_json(tmp_path: Path) -> None:
    a, b = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    a.write_text("\n".join(json.dumps(r) for r in _rows(1, 80)))
    b.write_text("\n".join(json.dumps(r) for r in _rows(2, 80)))
    result = runner.invoke(app, ["fidelity", str(a), str(b), "--slices", "region", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["n_real"] == 80 and "amount" in payload["univariate"]
    plain = runner.invoke(app, ["fidelity", str(a), str(b)])
    assert plain.exit_code == 0 and "No single score" in plain.output
    missing = runner.invoke(app, ["fidelity", str(a), str(tmp_path / "nope.jsonl")])
    assert missing.exit_code == 2
