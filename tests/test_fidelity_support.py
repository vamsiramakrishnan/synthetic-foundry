"""A capped conditional report cannot silently certify absent populations."""

from __future__ import annotations

import json
import math
from typing import Any

import pytest

from worldloom.fidelity import MAX_SLICES, compute, infer_kinds, pairwise


def _population(report: Any, key: str) -> Any:
    return next(p for p in report.slice_support["geo"].populations if p.key == key)


def test_reference_only_slice_retains_zero_support_and_global_marginal() -> None:
    real = [{"geo": "north", "amount": 1}, {"geo": "south", "amount": 2}]
    synthetic = [{"geo": "north", "amount": 1}] * 2
    report = compute(real, synthetic, slices=("geo",))
    assert set(report.slices["geo"]) == {"north", "south"}
    assert report.kinds["geo"] == "categorical"
    assert report.columns["geo"]["total_variation"] == 0.5
    population = _population(report, 'str:"south"')
    assert (population.reference_count, population.synthetic_count) == (1, 0)
    metric = report.slices["geo"]["south"]["amount"]
    assert metric["n_real"] == 1 and metric["n_synthetic"] == 0
    assert metric["rows_real"] == 1 and metric["rows_synthetic"] == 0
    assert math.isnan(metric["ks"])
    assert report.as_dict()["slices"]["geo"]["south"]["amount"]["ks"] is None
    assert not report.support_complete
    assert {f.code for f in report.support_findings()} == {"slice_reference_only"}
    support = report.slice_support["geo"]
    assert support.reference_category_coverage == 0.5
    assert support.reference_supported_rows == 1
    assert support.synthetic_supported_rows == 2
    assert "reference 1 → synthetic 0" in str(report)
    json.dumps(report.as_dict(), allow_nan=False)


def test_synthetic_only_population_and_no_overlap_are_reported() -> None:
    report = compute([{"geo": "north", "amount": 1}], [{"geo": "east", "amount": 2}], slices=("geo",))
    assert set(report.slices["geo"]) == {"north", "east"}
    support = report.slice_support["geo"]
    assert support.reference_category_coverage == 0.0
    assert support.reference_supported_rows == support.synthetic_supported_rows == 0
    assert {f.code for f in report.support_findings()} == {"slice_reference_only", "slice_synthetic_only"}
    assert report.columns["geo"]["jensen_shannon"] == 1.0
    assert not report.support_complete


def test_absent_null_and_empty_are_distinct_from_literal_labels() -> None:
    real = [{"geo": "north"}, {}, {"geo": None}, {"geo": ""}, {"geo": "<null>"}]
    synthetic = [{"geo": "north"}, {"geo": None}, {"geo": None}, {"geo": ""}, {"geo": "<null>"}]
    report = compute(real, synthetic, slices=("geo",))
    populations = {p.key: p for p in report.slice_support["geo"].populations}
    assert len(populations) == len(report.slices["geo"]) == 5
    assert populations["missing"].kind == "missing"
    assert populations["null"].kind == "null"
    assert populations["empty"].kind == "empty"
    assert populations['str:"<null>"'].kind == "value"
    assert populations["null"].synthetic_count == 2
    assert populations["missing"].synthetic_count == 0
    assert report.slice_support["geo"].reference_rows == len(real)
    assert report.slice_support["geo"].synthetic_rows == len(synthetic)
    assert not report.support_complete
    assert compute(real, real, slices=("geo",)).support_complete


@pytest.mark.parametrize("row", [{"geo": None}, {"geo": ""}])
def test_all_missing_cannot_certify_observed_segments(row: dict[str, Any]) -> None:
    report = compute([row, {}], [row, {}], slices=("geo",))
    assert report.slice_support["geo"].reference_category_coverage is None
    assert report.slice_support["geo"].reference_rows == 2
    assert not report.support_complete
    assert [f.code for f in report.support_findings()] == ["slice_no_observed_values"]


def test_typed_values_and_delimiter_collisions_do_not_merge_populations() -> None:
    values = [1, "1", 1.0, True, "int:1", "bool:true", {"b": 2, "a": 1}]
    rows = [{"geo": value} for value in values]
    report = compute(rows, rows, slices=("geo",), kinds={"geo": "categorical"})
    support = report.slice_support["geo"]
    assert support.reference_categories == support.synthetic_categories == len(values)
    assert len(report.slices["geo"]) == len(values)
    assert report.columns["geo"]["cardinality_real"] == len(values)
    assert report.support_complete
    disjoint = compute([{"geo": 1}], [{"geo": "1"}], kinds={"geo": "categorical"}, slices=("geo",))
    assert disjoint.columns["geo"]["total_variation"] == 1.0
    assert disjoint.privacy["exact_match_rate"] == 0.0
    assert not disjoint.support_complete
    # Separator concatenation used to make these different pairs identical.
    real = [{"a": "x\x1fy", "b": "z"}]
    synthetic = [{"a": "x", "b": "y\x1fz"}]
    assert pairwise(real, synthetic, {"a": "categorical", "b": "categorical"})["contingency_distance_mean"] == 1.0


def test_metric_cap_keeps_uncapped_support_counts_and_refuses_completion() -> None:
    real = [{"geo": f"g{index:02}", "amount": index} for index in range(MAX_SLICES + 4)]
    synthetic = real[:-1] + [{"geo": "unseen", "amount": 0}]
    report = compute(real, synthetic, slices=("geo",))
    support = report.slice_support["geo"]
    assert len(report.slices["geo"]) == MAX_SLICES
    assert len(support.populations) == MAX_SLICES + 5
    assert len(support.omitted) == 5
    assert support.reference_rows == support.synthetic_rows == len(real)
    assert support.reference_category_coverage == (len(real) - 1) / len(real)
    assert {f.code for f in report.support_findings()} == {"slice_reference_only", "slice_synthetic_only", "slice_metrics_omitted"}
    identical = compute(real, real, slices=("geo",))
    assert not identical.support_complete, "equal counts cannot pretend omitted conditional metrics were read"
    assert compute(real, real, slices=("geo",), max_slices=len(real)).support_complete


@pytest.mark.parametrize("limit", [0, -1, True, 1.5, "2"])
def test_invalid_metric_cap_refuses(limit: Any) -> None:
    with pytest.raises(ValueError, match="positive integer"):
        compute([{"geo": "N"}], [{"geo": "N"}], slices=("geo",), max_slices=limit)


def test_support_and_slice_order_are_independent_of_row_and_request_order() -> None:
    real = [{"geo": "south", "channel": "store", "amount": 2}, {"geo": "north", "channel": "web", "amount": 1}, {"geo": None, "amount": 3}]
    synthetic = [{"geo": "north", "channel": "web", "amount": 4}, {"geo": "east", "channel": "store", "amount": 2}]
    report = compute(real, synthetic, slices=("geo", "channel", "geo"), max_slices=2)
    reordered = compute(list(reversed(real)), list(reversed(synthetic)), slices=("channel", "geo"), max_slices=2)
    assert report.slice_support == reordered.slice_support
    assert report.support_findings() == reordered.support_findings()
    assert report.as_dict()["slices"] == reordered.as_dict()["slices"]
    assert list(report.slices) == ["channel", "geo"]


@pytest.mark.parametrize("malformed", ["NaN", "inf", "-Infinity", "1e999", float("nan"), float("inf"), True, 10 ** 400])
def test_nonfinite_numeric_values_are_malformed_and_do_not_retype(malformed: Any) -> None:
    real = [{"geo": "N", "amount": 1}, {"geo": "N", "amount": 2}]
    synthetic = [{"geo": "N", "amount": malformed}, {"geo": "N", "amount": 3}]
    report = compute(real, synthetic, slices=("geo",))
    assert report.columns["amount"]["kind"] == "numeric"
    assert report.columns["amount"]["malformed_synthetic"] == 0.5
    assert report.columns["amount"]["n_synthetic"] == 1
    assert report.slices["geo"]["N"]["amount"]["malformed_synthetic"] == 0.5
    assert infer_kinds([{"amount": malformed}])["amount"] == "categorical"
    dirty_reference = compute(synthetic, real, kinds={"amount": "numeric"})
    assert dirty_reference.columns["amount"]["malformed_real"] == 0.5
    json.dumps(report.as_dict(), allow_nan=False)


def test_no_slices_makes_no_support_claim_and_ignored_slice_still_checks_support() -> None:
    real = [{"geo": "N", "amount": 1}]
    synthetic = [{"geo": "S", "amount": 2}]
    assert compute(real, synthetic).support_complete
    ignored = compute(real, synthetic, slices=("geo",), kinds={"geo": "ignore"})
    assert "geo" not in ignored.columns
    assert not ignored.support_complete
