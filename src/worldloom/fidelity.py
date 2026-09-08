"""Fidelity: how a synthetic table compares with a reference — as a vector, never a score.

``stats.py`` reports what a corpus contains and refuses to grade it, because
there is no auditable published reference for "a real enterprise corpus". That
refusal stands. What changes here is the *question*: when a user has a real
table of their own — a transaction export, a claims register, a vendor list —
"how does the synthetic one compare with *this*" is a question with an
answer, and both sides of the comparison are on the user's own disk.

The answer is a vector, and the vector is not collapsed. A single "87%
realistic" badge rewards whichever dimension is cheapest to move (a generator
that matches every marginal and no correlation is a generator that has learned
to pass the test), and it hides the one dimension a reader actually cares
about for their use — a retrieval benchmark cares about cardinality and
category coverage; a fraud model cares about the pairwise structure; a privacy
review cares about nothing but the last block. DataGene's contribution to the
field was the list of things worth measuring; the lesson this module takes from
it is that they stay a list.

What is measured
----------------

Per column (**univariate**): for a numeric column the Kolmogorov–Smirnov
statistic and the 1-Wasserstein distance between the two empirical
distributions, with both means and both medians beside them so a reader can
see *which way* the synthetic side is off; for a categorical column the
Jensen–Shannon divergence (bits) and total variation, both cardinalities, and
the share of synthetic mass in categories the reference never had. Missingness
on both sides, always.

Per pair (**pairwise**): the mean and maximum absolute difference in Pearson
correlation across numeric pairs, and the mean total-variation distance
between joint distributions across categorical pairs. This is the block a
marginals-only generator fails.

**Multivariate**: a nearest-neighbour two-sample statistic (Schilling's) over
the standardised numeric columns — the share of pooled points whose nearest
neighbour carries the same label. Two samples from one distribution sit at the
value the report prints beside it as ``expected_if_same_distribution``; a
synthetic set that occupies a different region of the space sits well above
it; a synthetic set that *copied* the reference sits near zero, because every
point's nearest neighbour is its twin on the other side.

**Privacy**: the exact-match rate (synthetic rows identical to some reference
row on every compared column), and the distance to the closest reference
record for each synthetic row, summarised as a median and set beside the
reference's own leave-one-out nearest-neighbour distance. A synthetic set whose
records sit *closer* to the reference than the reference's own records sit to
each other has copied something, whatever its marginals say.

**Slices**: the univariate block again, per value of a named column, so a
generator that matches the whole and misses every region can be seen doing so.

Determinism, and its one honest caveat
--------------------------------------

Every count, sort and bin edge here is a deterministic function of the two
inputs; the nearest-neighbour blocks subsample large inputs through a seeded
``Rng`` so the same call reads the same rows. numpy is used for elementwise
arithmetic and reductions. A reduction's floating-point result can differ in
its last bits between numpy builds — the operation ``series.py`` and the
dependency note deliberately keep out of anything a corpus *mints*. Nothing
here is minted: a fidelity report is a measurement of two files, and a
difference in the twelfth decimal of a printed statistic moves nothing in any
world. That is the same line ``series.decompose`` draws, and it is drawn here
for the same reason.
"""

from __future__ import annotations

import csv
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

import numpy as np

from .rng import Rng

Kind = Literal["numeric", "categorical", "ignore"]

#: Past this many rows a side is subsampled (seeded) for the two quadratic
#: blocks — nearest-neighbour and distance-to-closest-record. Two thousand
#: points is a 4-million-entry distance table per column, which is a second of
#: arithmetic; twenty thousand would be a hundred seconds and four hundred
#: megabytes, for a statistic whose precision the extra points do not change.
QUADRATIC_SAMPLE = 2_000

#: Conditional metric blocks reported, most frequent in the reference first.
#: Support counts cover the entire union even when conditional metrics are
#: capped; high cardinality must be an explicit omission, never a silent pass.
MAX_SLICES = 12


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def load_rows(path: str | Path, *, table: str = "") -> list[dict[str, Any]]:
    """Rows from a CSV, a JSONL, a JSON array, or a corpus's detail table.

    A corpus directory (one holding ``world.json``) needs ``table`` — the name
    of the detail table whose rows to read, concatenated across every period
    it was generated for. That is how a corpus's own transaction rows get
    compared with a real export of the same shape.
    """
    path = Path(path)
    if path.is_dir():
        if not table:
            raise ValueError(f"{path} is a corpus; name the detail table to read with `table`")
        from .world import World

        world = World.load(path)
        rows: list[dict[str, Any]] = []
        for detail in world.detail_tables:
            if detail.name == table:
                rows.extend(dict(row) for row in detail.rows)
        if not rows:
            known = sorted({detail.name for detail in world.detail_tables})
            raise ValueError(f"{path} has no detail table {table!r}; it has {known}")
        return rows
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() == ".csv":
        return [dict(row) for row in csv.DictReader(text.splitlines())]
    if path.suffix.lower() in (".jsonl", ".ndjson"):
        return [json.loads(line) for line in text.splitlines() if line.strip()]
    payload = json.loads(text)
    if isinstance(payload, dict) and "rows" in payload:
        payload = payload["rows"]
    if not isinstance(payload, list):
        raise ValueError(f"{path}: expected a JSON array of rows")
    return [dict(row) for row in payload]


def _as_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        try:
            parsed = float(value)
        except OverflowError:
            return None
        return parsed if math.isfinite(parsed) else None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    try:
        parsed = float(text)
    except (ValueError, OverflowError):
        return None
    # float("nan") and float("inf") succeed, but neither is a numeric
    # observation. Letting them through poisoned every downstream distance.
    return parsed if math.isfinite(parsed) else None


def _category_key(value: Any) -> str:
    """Typed JSON identity: 1, "1", 1.0 and True are different categories.

    Delimiter concatenation and str(value) both collapse distinct populations.
    Canonical JSON also avoids mapping insertion order becoming an identity.
    """
    if value is None:
        return "null"
    if isinstance(value, str):
        kind = "str"
    elif isinstance(value, bool):
        kind = "bool"
    elif isinstance(value, int):
        kind = "int"
    elif isinstance(value, float):
        kind = "float"
    elif isinstance(value, (list, dict)):
        kind = "json"
    else:
        raise ValueError(f"unsupported categorical value type: {type(value).__name__}")
    try:
        return kind + ":" + json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    except (TypeError, ValueError) as exc:
        raise ValueError("categorical values must have a stable JSON representation") from exc


def _cell_key(row: Mapping[str, Any], column: str) -> str:
    if column not in row:
        return "missing"
    if row[column] == "":
        return "empty"
    return _category_key(row[column])


def infer_kinds(
    reference: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]] = (),
    *,
    overrides: Mapping[str, Kind] | None = None,
) -> dict[str, Kind]:
    """Numeric if every present *reference* value parses as a number, else categorical.

    From the reference alone, deliberately. Inferring over both tables let one
    malformed synthetic value — a stray ``"n/a"`` in an amount column — flip
    the whole column to categorical and *remove* the KS, Wasserstein and mean
    readings for exactly the broken output they exist to expose (Codex review,
    PR #40). The reference says what a column is; the synthetic side is judged
    against that, and a value that does not parse is reported as malformed
    rather than allowed to redefine the column. A column only the synthetic
    side has is typed from the synthetic side, being all there is.

    A column of ids that happen to be numeric is the classic misread, which is
    what ``overrides`` is for — and why the CLI's ``--categorical`` and
    ``--numeric`` exist. Sorted by name so the report's column order is the
    schema's, not the file's.
    """
    overrides = dict(overrides or {})
    columns: set[str] = set()
    for row in reference:
        columns.update(row)
    synthetic_only: set[str] = set()
    for row in synthetic:
        synthetic_only.update(name for name in row if name not in columns)
    kinds: dict[str, Kind] = {}
    for column in sorted(columns | synthetic_only):
        if column in overrides:
            kinds[column] = overrides[column]
            continue
        source = synthetic if column in synthetic_only else reference
        present = [row.get(column) for row in source if row.get(column) not in (None, "")]
        if present and all(_as_float(value) is not None for value in present):
            kinds[column] = "numeric"
        else:
            kinds[column] = "categorical"
    return kinds


def _malformed_rate(rows: Sequence[Mapping[str, Any]], column: str) -> float:
    """The share of present values in a numeric column that do not parse."""
    present = [row.get(column) for row in rows if row.get(column) not in (None, "")]
    if not present:
        return 0.0
    return round(sum(1 for value in present if _as_float(value) is None) / len(present), 4)


# ---------------------------------------------------------------------------
# Univariate
# ---------------------------------------------------------------------------


def _numeric(rows: Sequence[Mapping[str, Any]], column: str) -> np.ndarray:
    values = [_as_float(row.get(column)) for row in rows]
    return np.array([v for v in values if v is not None], dtype=float)


def _missing_rate(rows: Sequence[Mapping[str, Any]], column: str) -> float | None:
    if not rows:
        return None
    missing = sum(1 for row in rows if row.get(column) in (None, ""))
    return round(missing / len(rows), 4)


def ks_statistic(a: np.ndarray, b: np.ndarray) -> float:
    """sup |F_a − F_b| over the union of both supports."""
    if not len(a) or not len(b):
        return float("nan")
    grid = np.sort(np.concatenate([a, b]))
    fa = np.searchsorted(np.sort(a), grid, side="right") / len(a)
    fb = np.searchsorted(np.sort(b), grid, side="right") / len(b)
    return float(np.max(np.abs(fa - fb)))


def wasserstein_1(a: np.ndarray, b: np.ndarray) -> float:
    """∫ |F_a − F_b| dx — the earth-mover's distance in the column's own unit."""
    if not len(a) or not len(b):
        return float("nan")
    grid = np.sort(np.concatenate([a, b]))
    fa = np.asarray(np.searchsorted(np.sort(a), grid, side="right") / len(a), dtype=float)
    fb = np.asarray(np.searchsorted(np.sort(b), grid, side="right") / len(b), dtype=float)
    gaps = np.diff(grid)
    return float(np.sum(np.abs(fa[:-1] - fb[:-1]) * gaps))


def _distribution(rows: Sequence[Mapping[str, Any]], column: str) -> dict[str, float]:
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        value = row.get(column)
        if value in (None, ""):
            continue
        key = _category_key(value)
        counts[key] = counts.get(key, 0) + 1
        total += 1
    return {key: count / total for key, count in sorted(counts.items())} if total else {}


def jensen_shannon(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    """JS divergence in bits over the union of categories. 0 identical, 1 disjoint."""
    if not p or not q:
        return float("nan")
    keys = sorted(set(p) | set(q))
    total = 0.0
    for key in keys:
        pk, qk = p.get(key, 0.0), q.get(key, 0.0)
        mk = (pk + qk) / 2
        if pk:
            total += pk * math.log2(pk / mk) / 2
        if qk:
            total += qk * math.log2(qk / mk) / 2
    return total


def total_variation(p: Mapping[str, float], q: Mapping[str, float]) -> float:
    if not p or not q:
        return float("nan")
    # Sorted, as every set iteration in this package is: summation order is a
    # float-rounding order, and a set's is hash order.
    keys = sorted(set(p) | set(q))
    return sum(abs(p.get(key, 0.0) - q.get(key, 0.0)) for key in keys) / 2


def _round(value: float, places: int = 4) -> float:
    return value if math.isnan(value) else round(value, places)


def univariate(
    real: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    kinds: Mapping[str, Kind],
) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for column, kind in sorted(kinds.items()):
        if kind == "ignore":
            continue
        entry: dict[str, Any] = {
            "kind": kind,
            "rows_real": len(real),
            "rows_synthetic": len(synthetic),
            "missing_real": _missing_rate(real, column),
            "missing_synthetic": _missing_rate(synthetic, column),
        }
        if kind == "numeric":
            a, b = _numeric(real, column), _numeric(synthetic, column)
            entry.update({
                "n_real": len(a), "n_synthetic": len(b),
                "malformed_real": _malformed_rate(real, column),
                "malformed_synthetic": _malformed_rate(synthetic, column),
                "ks": _round(ks_statistic(a, b)),
                "wasserstein": _round(wasserstein_1(a, b)),
                "mean_real": _round(float(np.mean(a))) if len(a) else None,
                "mean_synthetic": _round(float(np.mean(b))) if len(b) else None,
                "median_real": _round(float(np.median(a))) if len(a) else None,
                "median_synthetic": _round(float(np.median(b))) if len(b) else None,
            })
        else:
            p, q = _distribution(real, column), _distribution(synthetic, column)
            unseen = sum(mass for key, mass in q.items() if key not in p)
            entry.update({
                "cardinality_real": len(p), "cardinality_synthetic": len(q),
                "jensen_shannon": _round(jensen_shannon(p, q)),
                "total_variation": _round(total_variation(p, q)),
                "unseen_share": _round(unseen),
            })
        out[column] = entry
    return out


# ---------------------------------------------------------------------------
# Pairwise
# ---------------------------------------------------------------------------


def _pearson(x: np.ndarray, y: np.ndarray) -> float:
    if len(x) < 2:
        return float("nan")
    xm, ym = x - x.mean(), y - y.mean()
    denominator = math.sqrt(float(np.sum(xm * xm)) * float(np.sum(ym * ym)))
    if denominator == 0:
        return 0.0
    return float(np.sum(xm * ym)) / denominator


def _numeric_matrix(rows: Sequence[Mapping[str, Any]], columns: Sequence[str]) -> np.ndarray:
    """Rows complete on every named column, as a float array. Incomplete rows
    are dropped for the pairwise and multivariate blocks only — a correlation
    over imputed values would be a correlation with the imputation."""
    kept: list[list[float]] = []
    for row in rows:
        values = [_as_float(row.get(column)) for column in columns]
        if all(value is not None for value in values):
            kept.append([float(v) for v in values])  # type: ignore[arg-type]
    return np.array(kept, dtype=float).reshape(len(kept), len(columns))


def pairwise(
    real: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    kinds: Mapping[str, Kind],
) -> dict[str, Any]:
    numeric = [c for c, k in sorted(kinds.items()) if k == "numeric"]
    categorical = [c for c, k in sorted(kinds.items()) if k == "categorical"]
    out: dict[str, Any] = {"numeric_pairs": 0, "categorical_pairs": 0}

    if len(numeric) >= 2:
        diffs: list[tuple[float, str, str]] = []
        for i in range(len(numeric)):
            for j in range(i + 1, len(numeric)):
                # Complete cases *for this pair*, not for every numeric column at
                # once: a sparse column elsewhere in the table would otherwise
                # drop rows from — and could empty — a pair it has nothing to
                # do with (Codex review, PR #40).
                pair = [numeric[i], numeric[j]]
                a, b = _numeric_matrix(real, pair), _numeric_matrix(synthetic, pair)
                ra = _pearson(a[:, 0], a[:, 1]) if len(a) else float("nan")
                rb = _pearson(b[:, 0], b[:, 1]) if len(b) else float("nan")
                if not (math.isnan(ra) or math.isnan(rb)):
                    diffs.append((abs(ra - rb), numeric[i], numeric[j]))
        if diffs:
            worst = max(diffs)
            out.update({
                "numeric_pairs": len(diffs),
                "correlation_error_mean": _round(sum(d for d, _, _ in diffs) / len(diffs)),
                "correlation_error_max": _round(worst[0]),
                "correlation_error_max_pair": [worst[1], worst[2]],
            })

    if len(categorical) >= 2:
        distances: list[float] = []
        for i in range(len(categorical)):
            for j in range(i + 1, len(categorical)):
                joint_a = _joint(real, categorical[i], categorical[j])
                joint_b = _joint(synthetic, categorical[i], categorical[j])
                tv = total_variation(joint_a, joint_b)
                if not math.isnan(tv):
                    distances.append(tv)
        if distances:
            out.update({
                "categorical_pairs": len(distances),
                "contingency_distance_mean": _round(sum(distances) / len(distances)),
                "contingency_distance_max": _round(max(distances)),
            })
    return out


def _joint(rows: Sequence[Mapping[str, Any]], a: str, b: str) -> dict[str, float]:
    counts: dict[str, int] = {}
    total = 0
    for row in rows:
        va, vb = row.get(a), row.get(b)
        if va in (None, "") or vb in (None, ""):
            continue
        key = json.dumps([_category_key(va), _category_key(vb)], separators=(",", ":"))
        counts[key] = counts.get(key, 0) + 1
        total += 1
    return {key: count / total for key, count in sorted(counts.items())} if total else {}


# ---------------------------------------------------------------------------
# Multivariate and privacy — the two quadratic blocks
# ---------------------------------------------------------------------------


def _subsample(matrix: np.ndarray, rng: Rng) -> np.ndarray:
    if len(matrix) <= QUADRATIC_SAMPLE:
        return matrix
    indexes = sorted(rng.sample(range(len(matrix)), QUADRATIC_SAMPLE))
    return matrix[indexes]


def _standardise(a: np.ndarray, b: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Both sides scaled by the *reference's* mean and spread. Scaling each by
    its own would erase exactly the location and scale differences the
    statistic is meant to see."""
    mean = a.mean(axis=0)
    spread = a.std(axis=0)
    spread = np.where(spread == 0, 1.0, spread)
    return (a - mean) / spread, (b - mean) / spread


def _squared_distances(x: np.ndarray, y: np.ndarray) -> np.ndarray:
    """Pairwise squared Euclidean distances, one column at a time.

    Accumulated per column rather than through the expanded ``(n, m, d)``
    broadcast, which is a memory shape not a compute shape; and not through
    ``x @ y.T``, which is the matrix product the dependency note keeps out."""
    out: np.ndarray = np.zeros((len(x), len(y)), dtype=float)
    for column in range(x.shape[1]):
        diff = x[:, column][:, None] - y[:, column][None, :]
        out += diff * diff
    return out


def multivariate(
    real: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    kinds: Mapping[str, Kind],
    *,
    seed: int = 0,
) -> dict[str, Any]:
    numeric = [c for c, k in sorted(kinds.items()) if k == "numeric"]
    if not numeric:
        return {"columns": 0}
    rng = Rng(seed).derive("fidelity/multivariate")
    a = _subsample(_numeric_matrix(real, numeric), rng.derive("real"))
    b = _subsample(_numeric_matrix(synthetic, numeric), rng.derive("synthetic"))
    if len(a) < 2 or len(b) < 2:
        return {"columns": len(numeric), "n_real": len(a), "n_synthetic": len(b)}
    a, b = _standardise(a, b)
    pooled = np.concatenate([a, b])
    labels = np.concatenate([np.zeros(len(a)), np.ones(len(b))])
    distances = _squared_distances(pooled, pooled)
    np.fill_diagonal(distances, np.inf)
    nearest = np.argmin(distances, axis=1)
    same = float(np.mean(labels[nearest] == labels))
    n, m = len(a), len(b)
    expected = (n * (n - 1) + m * (m - 1)) / ((n + m) * (n + m - 1))
    return {
        "columns": len(numeric), "n_real": int(n), "n_synthetic": int(m),
        "nearest_neighbour_same_label": _round(same),
        "expected_if_same_distribution": _round(expected),
    }


def privacy(
    real: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    kinds: Mapping[str, Kind],
    *,
    seed: int = 0,
) -> dict[str, Any]:
    compared = [c for c, k in sorted(kinds.items()) if k != "ignore"]
    keys = {tuple(_cell_key(row, c) for c in compared) for row in real}
    matches = sum(1 for row in synthetic if tuple(_cell_key(row, c) for c in compared) in keys)
    out: dict[str, Any] = {
        "compared_columns": len(compared),
        "exact_match_rate": _round(matches / len(synthetic)) if synthetic else None,
    }
    numeric = [c for c, k in sorted(kinds.items()) if k == "numeric"]
    if not numeric:
        return out
    rng = Rng(seed).derive("fidelity/privacy")
    a = _subsample(_numeric_matrix(real, numeric), rng.derive("real"))
    b = _subsample(_numeric_matrix(synthetic, numeric), rng.derive("synthetic"))
    if len(a) < 2 or not len(b):
        return out
    a, b = _standardise(a, b)
    to_real = np.sqrt(np.min(_squared_distances(b, a), axis=1))
    within = _squared_distances(a, a)
    np.fill_diagonal(within, np.inf)
    real_to_real = np.sqrt(np.min(within, axis=1))
    out.update({
        "dcr_median_synthetic_to_real": _round(float(np.median(to_real))),
        "dcr_median_real_to_real": _round(float(np.median(real_to_real))),
        "dcr_share_below_real_baseline": _round(float(np.mean(to_real < np.median(real_to_real)))),
    })
    return out


# ---------------------------------------------------------------------------
# The report
# ---------------------------------------------------------------------------


SliceValueKind = Literal["value", "missing", "null", "empty"]
SupportCode = Literal[
    "slice_reference_only", "slice_synthetic_only", "slice_metrics_omitted",
    "slice_no_observed_values",
]


@dataclass(frozen=True)
class SlicePopulation:
    """One population in the union, including populations with no counterpart."""

    key: str
    label: str
    kind: SliceValueKind
    reference_count: int
    synthetic_count: int
    metrics_reported: bool


@dataclass(frozen=True)
class FidelitySupportFinding:
    code: SupportCode
    column: str
    value_key: str = ""
    reference_count: int = 0
    synthetic_count: int = 0


@dataclass(frozen=True)
class SliceSupport:
    column: str
    populations: tuple[SlicePopulation, ...]
    metrics_limit: int

    @property
    def reference_rows(self) -> int:
        return sum(p.reference_count for p in self.populations)

    @property
    def synthetic_rows(self) -> int:
        return sum(p.synthetic_count for p in self.populations)

    @property
    def reference_categories(self) -> int:
        return sum(p.kind == "value" and p.reference_count > 0 for p in self.populations)

    @property
    def synthetic_categories(self) -> int:
        return sum(p.kind == "value" and p.synthetic_count > 0 for p in self.populations)

    @property
    def shared_categories(self) -> int:
        return sum(p.kind == "value" and p.reference_count > 0 and p.synthetic_count > 0 for p in self.populations)

    @property
    def reference_category_coverage(self) -> float | None:
        return self.shared_categories / self.reference_categories if self.reference_categories else None

    @property
    def reference_supported_rows(self) -> int:
        return sum(p.reference_count for p in self.populations if p.synthetic_count)

    @property
    def synthetic_supported_rows(self) -> int:
        return sum(p.synthetic_count for p in self.populations if p.reference_count)

    @property
    def omitted(self) -> tuple[SlicePopulation, ...]:
        return tuple(p for p in self.populations if not p.metrics_reported)

    def findings(self) -> tuple[FidelitySupportFinding, ...]:
        findings: list[FidelitySupportFinding] = []
        for population in self.populations:
            codes: list[SupportCode] = []
            if not population.synthetic_count:
                codes.append("slice_reference_only")
            if not population.reference_count:
                codes.append("slice_synthetic_only")
            if not population.metrics_reported:
                codes.append("slice_metrics_omitted")
            findings.extend(FidelitySupportFinding(
                code, self.column, population.key,
                population.reference_count, population.synthetic_count,
            ) for code in codes)
        if not self.reference_categories or not self.synthetic_categories:
            findings.append(FidelitySupportFinding(
                "slice_no_observed_values", self.column,
                reference_count=self.reference_rows, synthetic_count=self.synthetic_rows,
            ))
        return tuple(findings)

    @property
    def complete(self) -> bool:
        """Every union population has both sides and measured slice metrics.

        Equal support is not equal frequency. Null/empty/absent populations are
        permitted when represented on both sides; an all-missing slice is not
        a measured segment. This predicate deliberately fails if metrics were
        capped, even when the uncapped population counts prove equal support.
        """
        return not self.findings()

    def as_dict(self) -> dict[str, Any]:
        return {
            **asdict(self),
            "reference_rows": self.reference_rows,
            "synthetic_rows": self.synthetic_rows,
            "reference_categories": self.reference_categories,
            "synthetic_categories": self.synthetic_categories,
            "shared_categories": self.shared_categories,
            "reference_category_coverage": self.reference_category_coverage,
            "reference_supported_rows": self.reference_supported_rows,
            "synthetic_supported_rows": self.synthetic_supported_rows,
            "omitted_keys": [p.key for p in self.omitted],
            "complete": self.complete,
        }


def _slice_populations(
    real: Sequence[Mapping[str, Any]], synthetic: Sequence[Mapping[str, Any]],
    column: str, limit: int,
) -> tuple[SliceSupport, dict[str, list[Mapping[str, Any]]], dict[str, list[Mapping[str, Any]]]]:
    real_groups: dict[str, list[Mapping[str, Any]]] = {}
    synthetic_groups: dict[str, list[Mapping[str, Any]]] = {}
    labels: dict[str, str] = {}
    for rows, groups in ((real, real_groups), (synthetic, synthetic_groups)):
        for row in rows:
            key = _cell_key(row, column)
            groups.setdefault(key, []).append(row)
            labels[key] = (
                f"<{key}>" if key in ("missing", "null", "empty")
                else row[column] if isinstance(row[column], str)
                else key
            )
    # Preserve familiar string labels, but never let a literal "<null>" or
    # "int:1" steal another population's dictionary entry. If any collision
    # exists all labels become canonical keys, an injective representation.
    if len(set(labels.values())) != len(labels):
        labels = {key: key for key in labels}
    ranked = sorted(labels, key=lambda key: (-len(real_groups.get(key, ())), key))
    populations = tuple(SlicePopulation(
        key=key, label=labels[key],
        kind="missing" if key == "missing" else "null" if key == "null" else "empty" if key == "empty" else "value",
        reference_count=len(real_groups.get(key, ())),
        synthetic_count=len(synthetic_groups.get(key, ())),
        metrics_reported=index < limit,
    ) for index, key in enumerate(ranked))
    return SliceSupport(column, populations, limit), real_groups, synthetic_groups


def _json_finite(value: Any) -> Any:
    """Unmeasurable distances serialize as null, never nonstandard JSON NaN."""
    if isinstance(value, float) and not math.isfinite(value):
        return None
    if isinstance(value, dict):
        return {key: _json_finite(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_finite(item) for item in value]
    return value


@dataclass(frozen=True)
class FidelityReport:
    n_real: int
    n_synthetic: int
    kinds: dict[str, Kind]
    columns: dict[str, dict[str, Any]]
    pairwise: dict[str, Any]
    multivariate: dict[str, Any]
    privacy: dict[str, Any]
    slices: dict[str, dict[str, dict[str, dict[str, Any]]]] = field(default_factory=dict)
    """``slice column → slice label → column → univariate entry``."""
    slice_support: dict[str, SliceSupport] = field(default_factory=dict)
    """Uncapped population counts; metric blocks alone cannot prove support."""

    def support_findings(self) -> tuple[FidelitySupportFinding, ...]:
        return tuple(finding for _, support in sorted(self.slice_support.items()) for finding in support.findings())

    @property
    def support_complete(self) -> bool:
        """Strict admission predicate for the requested slices, not a fidelity score.

        With no requested slices the condition is vacuously true. Callers must
        choose their required segments and separately bound the metric vector.
        """
        return not self.support_findings()

    def as_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "n_real": self.n_real,
            "n_synthetic": self.n_synthetic,
            "kinds": dict(sorted(self.kinds.items())),
            "univariate": self.columns,
            "pairwise": self.pairwise,
            "multivariate": self.multivariate,
            "privacy": self.privacy,
            "slices": self.slices,
            "slice_support": {column: support.as_dict() for column, support in sorted(self.slice_support.items())},
            "support_findings": [asdict(finding) for finding in self.support_findings()],
            "support_complete": self.support_complete,
        }
        return {key: _json_finite(value) for key, value in result.items()}

    def __str__(self) -> str:
        lines = [f"reference {self.n_real} rows · synthetic {self.n_synthetic} rows", ""]
        lines.append("univariate")
        for column, entry in self.columns.items():
            if entry["kind"] == "numeric":
                malformed = entry.get("malformed_synthetic", 0.0)
                lines.append(
                    f"  {column:<28} numeric  KS {entry['ks']!s:<8} W1 {entry['wasserstein']!s:<12}"
                    f" mean {entry['mean_real']} → {entry['mean_synthetic']}"
                    f"  missing {entry['missing_real']} → {entry['missing_synthetic']}"
                    + (f"  MALFORMED {malformed}" if malformed else "")
                )
            else:
                lines.append(
                    f"  {column:<28} categ.   JS {entry['jensen_shannon']!s:<8}"
                    f" TV {entry['total_variation']!s:<8}"
                    f" card {entry['cardinality_real']} → {entry['cardinality_synthetic']}"
                    f"  unseen {entry['unseen_share']}"
                )
        lines.append("")
        lines.append("pairwise")
        for key, value in self.pairwise.items():
            lines.append(f"  {key:<34} {value}")
        lines.append("")
        lines.append("multivariate")
        for key, value in self.multivariate.items():
            lines.append(f"  {key:<34} {value}")
        lines.append("")
        lines.append("privacy")
        for key, value in self.privacy.items():
            lines.append(f"  {key:<34} {value}")
        for column, by_value in self.slices.items():
            lines.append("")
            lines.append(f"slices by {column}")
            support = self.slice_support[column]
            for population in support.populations:
                counts = f"reference {population.reference_count} → synthetic {population.synthetic_count}"
                if not population.metrics_reported:
                    lines.append(f"  {population.label:<28} {counts}; metrics omitted (limit {support.metrics_limit})")
                    continue
                entries = by_value[population.label]
                measured = [
                    (distance, name) for name, entry in entries.items()
                    if isinstance(distance := entry.get("ks" if entry["kind"] == "numeric" else "total_variation"), (int, float))
                    and math.isfinite(distance)
                ]
                worst = max(measured) if measured else None
                detail = f"worst column {worst[1]} at {worst[0]}" if worst else "distance unmeasurable"
                lines.append(f"  {population.label:<28} {counts}; {detail}")
            for finding in support.findings():
                lines.append(f"  {finding.code}: {finding.value_key or column}")
        lines.append("")
        lines.append("No single score is reported. Read the dimension your use depends on.")
        return "\n".join(lines)


def compute(
    real: Sequence[Mapping[str, Any]],
    synthetic: Sequence[Mapping[str, Any]],
    *,
    kinds: Mapping[str, Kind] | None = None,
    slices: Sequence[str] = (),
    seed: int = 0,
    max_slices: int = MAX_SLICES,
) -> FidelityReport:
    """The whole vector for two row sets. ``kinds`` overrides reference inference.

    ``max_slices`` bounds conditional metric blocks per slice column, not its
    support census. Missing counterparts and omitted blocks always remain in
    ``slice_support`` and make the strict ``support_complete`` predicate false.
    A requested slice retains its global marginal unless explicitly ignored.
    """
    if not real or not synthetic:
        raise ValueError("fidelity needs rows on both sides")
    if isinstance(max_slices, bool) or not isinstance(max_slices, int) or max_slices < 1:
        raise ValueError("max_slices must be a positive integer")
    resolved = infer_kinds(real, synthetic, overrides=kinds)
    for column in sorted(set(slices)):
        if column not in resolved:
            raise ValueError(f"slice column {column!r} is in neither table")
    # Slice requests add conditional measurements. They must not remove the
    # global marginal that reveals a missing region or changed segment mix.
    sliced: dict[str, dict[str, dict[str, dict[str, Any]]]] = {}
    supports: dict[str, SliceSupport] = {}
    for column in sorted(set(slices)):
        support, real_groups, synthetic_groups = _slice_populations(real, synthetic, column, max_slices)
        supports[column] = support
        compared = {name: kind for name, kind in resolved.items() if name != column}
        sliced[column] = {
            population.label: univariate(
                real_groups.get(population.key, ()), synthetic_groups.get(population.key, ()), compared,
            )
            for population in support.populations if population.metrics_reported
        }
    return FidelityReport(
        n_real=len(real), n_synthetic=len(synthetic), kinds=resolved,
        columns=univariate(real, synthetic, resolved),
        pairwise=pairwise(real, synthetic, resolved),
        multivariate=multivariate(real, synthetic, resolved, seed=seed),
        privacy=privacy(real, synthetic, resolved, seed=seed),
        slices=sliced, slice_support=supports,
    )


__all__ = [
    "FidelityReport", "FidelitySupportFinding", "SlicePopulation", "SliceSupport",
    "MAX_SLICES", "QUADRATIC_SAMPLE", "compute", "infer_kinds",
    "jensen_shannon", "ks_statistic", "load_rows", "multivariate", "pairwise",
    "privacy", "total_variation", "univariate", "wasserstein_1",
]
