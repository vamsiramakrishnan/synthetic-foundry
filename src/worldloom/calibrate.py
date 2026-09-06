"""Calibration: physics ranges learned from data the corpus may never contain.

``parameters.py`` is honest about its defaults — "chosen to make one plausible
episode work, not calibrated against anything" — and it draws a boundary at the
point of temptation: sector aggregates are priors, a named company's figures
are not ours to put in a fictional corpus. That boundary was drawn for a model
with web search grounding a margin in a published statistic. This module is
for the harder case: a user with their *own* transaction data who wants a
world whose physics resemble it, and who must not — legally, contractually, or
because the data is about real people — let a single row of it into the
corpus.

The shape of the answer is the one the architecture already has. A physics
parameter is a ``Span``: a low and a high, a kind, a rounding, and a ``source``.
Calibration produces spans. Nothing else crosses the boundary — not a row, not
a mean, not a histogram — and the ``PriorSnapshot`` that carries them is the
same JSON ``build --physics`` has always read, with a receipt attached that
says how the ranges were made and what privacy budget making them spent.

The built-in estimator
----------------------

``LaplaceHistogramEstimator`` is deliberately the simplest mechanism that is
actually differentially private, chosen so that this module has no dependency
and no claim it cannot state in full:

1. For each calibrated column, values are **clipped** to the declared domain.
   A DP release needs a bounded domain; the author states it, and the receipt
   records it.
2. One individual's **contribution is bounded**: when the schema names a
   ``unit`` column, only the first ``contribution_bound`` rows per unit are
   read. Sensitivity rests on this, so it is enforced, not assumed.
3. A **histogram** over ``bins`` equal-width cells is released with
   **Laplace noise** of scale ``contribution_bound / ε_i`` on every cell, where
   ``ε_i = ε / columns`` under sequential composition. Negative cells are
   floored at zero after noising (post-processing is free).
4. The span's low and high are read off the noised cumulative distribution at
   the declared **quantiles**, then scaled into the parameter's own unit.

SmartNoise, Tumult or OpenDP would do this with better mechanisms (MWEM, a
Gaussian mechanism with tighter composition), and the ``PriorEstimator``
protocol in ``providers.py`` is where such an adapter plugs in — producing the
same ``PriorSnapshot`` with a different ``mechanism`` in its receipt. None of
them ship here: each is a heavy dependency this package has no business
carrying for every user who will never calibrate anything.

The honest part about noise
---------------------------

Differential privacy is a property of a *random* mechanism. Noise an adversary
can regenerate is not noise, and a seed written into a receipt is exactly that.
So the estimator draws its noise from **system entropy** by default, which
means a calibration is *not reproducible* — and that is correct: the thing
that must replay is the corpus, and the corpus replays from the snapshot, not
from the calibration. ``noise_seed`` exists for tests, and a snapshot made
with it carries ``noise_source: "seeded"`` in its receipt and ``private ==
False`` on it; the CLI prints a warning and the snapshot's spans say so in
their ``source``. A seeded calibration is a deterministic *summary*, not a
private one, and nothing here lets the two be confused.
"""

from __future__ import annotations

import json
import math
import random
import secrets
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from .ids import content_key
from .parameters import DEFAULT as DEFAULT_PHYSICS, Parameters, Span
from .providers import PrivacyReceipt, Receipt, digest

SCHEMA_VERSION = 1

#: Past this share of expected noise mass in a column's histogram, the
#: snapshot names the parameter as noisy. A quarter: at that point one cell in
#: four of the released distribution is a Laplace draw rather than a count.
NOISE_SHARE_WARNING = 0.25


class Model(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


# ---------------------------------------------------------------------------
# The schema an author writes
# ---------------------------------------------------------------------------


class ColumnCalibration(Model):
    """One column of the source, and the physics parameter it informs."""

    column: str
    parameter: str
    """A ``parameters.py`` name. Refused at lint if the registry lacks it —
    a snapshot naming a parameter nothing reads would calibrate nothing and
    report success."""

    clip: tuple[float, float]
    """The bounded domain the values are clipped to before release. Required:
    a Laplace mechanism's sensitivity is undefined over an unbounded column."""

    bins: int = Field(default=64, ge=4, le=4096)
    quantiles: tuple[float, float] = (0.1, 0.9)
    """Which points of the noised distribution become the span's low and high.
    A physics range is a *plausible band*, not a min and max, so the defaults
    trim the tails the noise most distorts."""

    scale: float = Field(default=1.0, gt=0.0)
    """Column units → parameter units. A margin column in per cent informing a
    span stated as a fraction is ``0.01``."""

    about: str = ""


class CalibrationSchema(Model):
    columns: list[ColumnCalibration] = Field(min_length=1)
    unit: str = ""
    """The column identifying the individual whose privacy the budget
    protects — a customer id, an employee id. Empty means each row is its
    own individual, which is only true when it is."""

    contribution_bound: int = Field(default=1, ge=1)
    about: str = ""
    source: str = ""


def lint(schema: CalibrationSchema, *, physics: Parameters = DEFAULT_PHYSICS) -> list[str]:
    findings: list[str] = []
    seen: set[str] = set()
    for spec in schema.columns:
        if spec.parameter not in physics.spans:
            findings.append(
                f"column {spec.column!r} informs {spec.parameter!r}, which the physics"
                " registry does not carry (`worldloom pack params`)"
            )
        elif physics.spans[spec.parameter].kind == "chance":
            findings.append(
                f"column {spec.column!r} informs {spec.parameter!r}, a chance — a"
                " probability is a single value, not a range, and is not calibrated here"
            )
        if spec.parameter in seen:
            findings.append(f"parameter {spec.parameter!r} is informed by two columns")
        seen.add(spec.parameter)
        low, high = spec.clip
        if not low < high:
            findings.append(f"column {spec.column!r}: clip [{low}, {high}] is not a range")
        q_low, q_high = spec.quantiles
        if not 0.0 <= q_low < q_high <= 1.0:
            findings.append(f"column {spec.column!r}: quantiles must satisfy 0 ≤ low < high ≤ 1")
    return findings


# ---------------------------------------------------------------------------
# The snapshot a build reads
# ---------------------------------------------------------------------------


class PriorSnapshot(Model):
    """Calibrated spans and the receipt for how they were made. Nothing else."""

    schema_version: int = SCHEMA_VERSION
    spans: dict[str, dict[str, Any]]
    """``parameter → Span.as_dict()`` — exactly the ``overrides`` document
    ``build --physics`` reads."""

    receipt: Receipt
    about: str = ""
    quality: dict[str, dict[str, float | int]] = Field(default_factory=dict)
    """Per column: how many values were actually read after contribution
    bounding, the noise mass the mechanism is expected to have added across
    the histogram, and that mass as a share of the total. A share near one
    means the spans are noise wearing data's clothes — the budget and the row
    count did not support the release — and the CLI says so. Recorded rather
    than used to refuse, because a wide prior is still a *valid* private
    release; it is just not an informative one, and the author should know."""

    @property
    def noisy(self) -> list[str]:
        """Parameters whose release was more noise than signal."""
        return sorted(
            name for name, reading in self.quality.items()
            if reading.get("noise_share", 0.0) > NOISE_SHARE_WARNING
        )

    def overrides(self) -> dict[str, Span]:
        from .parameters import overrides_from

        return overrides_from(self.spans)

    @property
    def private(self) -> bool:
        return self.receipt.privacy is not None and self.receipt.privacy.private

    def write(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.model_dump(mode="json"), indent=2, sort_keys=True) + "\n",
                        encoding="utf-8")
        return path

    @classmethod
    def read(cls, path: str | Path) -> PriorSnapshot:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
        version = payload.get("schema_version", SCHEMA_VERSION)
        if version > SCHEMA_VERSION:
            raise ValueError(f"prior snapshot schema {version} is newer than this library reads")
        return cls.model_validate(payload)


# ---------------------------------------------------------------------------
# The estimator
# ---------------------------------------------------------------------------


def _laplace(scale: float, draw: random.Random | secrets.SystemRandom) -> float:
    """Inverse-CDF Laplace: u ∈ (−½, ½) → −b · sgn(u) · ln(1 − 2|u|)."""
    u = draw.random() - 0.5
    while u == 0.0:  # pragma: no cover — probability 2^-53
        u = draw.random() - 0.5
    return -scale * math.copysign(1.0, u) * math.log(1.0 - 2.0 * abs(u))


def _bounded(rows: Sequence[Mapping[str, Any]], unit: str, bound: int) -> list[Mapping[str, Any]]:
    """The first *bound* rows per unit, in file order. Enforced, not assumed."""
    if not unit:
        return list(rows)
    seen: dict[str, int] = {}
    kept: list[Mapping[str, Any]] = []
    for row in rows:
        key = str(row.get(unit, ""))
        seen[key] = seen.get(key, 0) + 1
        if seen[key] <= bound:
            kept.append(row)
    return kept


def _value(raw: Any) -> float | None:
    if raw is None or isinstance(raw, bool):
        return None
    try:
        value = float(str(raw).replace(",", "")) if not isinstance(raw, (int, float)) else float(raw)
    except ValueError:
        return None
    return value if math.isfinite(value) else None


class LaplaceHistogramEstimator:
    """The built-in ``PriorEstimator``. See the module docstring for the mechanism."""

    id = "worldloom-dp"
    version = "1"

    def __init__(self, *, noise_seed: int | None = None) -> None:
        self.noise_seed = noise_seed

    def _draw(self, column: str) -> random.Random | secrets.SystemRandom:
        if self.noise_seed is None:
            return secrets.SystemRandom()
        return random.Random(int(content_key("calibrate", self.noise_seed, column), 16))

    def estimate(
        self,
        rows: Sequence[Mapping[str, Any]],
        schema: CalibrationSchema,
        *,
        epsilon: float,
        delta: float = 0.0,
        source_digest: str = "",
        physics: Parameters = DEFAULT_PHYSICS,
    ) -> PriorSnapshot:
        if epsilon <= 0:
            raise ValueError("epsilon must be positive")
        findings = lint(schema, physics=physics)
        if findings:
            raise ValueError("calibration schema has lint findings: " + "; ".join(findings))
        bounded = _bounded(rows, schema.unit, schema.contribution_bound)
        per_query = epsilon / len(schema.columns)
        sensitivity = float(schema.contribution_bound)
        noise_source = "seeded" if self.noise_seed is not None else "system-entropy"
        spans: dict[str, dict[str, Any]] = {}
        quality: dict[str, dict[str, float | int]] = {}
        clipping: dict[str, tuple[float, float]] = {}
        bins: dict[str, int] = {}
        for spec in schema.columns:
            low_edge, high_edge = spec.clip
            width = (high_edge - low_edge) / spec.bins
            counts = [0.0] * spec.bins
            for row in bounded:
                value = _value(row.get(spec.column))
                if value is None:
                    continue
                clipped = min(max(value, low_edge), high_edge)
                index = min(int((clipped - low_edge) / width), spec.bins - 1)
                counts[index] += 1.0
            draw = self._draw(spec.column)
            scale_b = sensitivity / per_query
            noised = [max(0.0, c + _laplace(scale_b, draw)) for c in counts]
            total = sum(noised)
            # E[max(0, Laplace(b))] = b/2 per cell: the mass the mechanism adds
            # to an empty histogram, which is what the true counts compete with.
            read = sum(counts)
            expected_noise = spec.bins * scale_b / 2
            quality[spec.parameter] = {
                "values_read": int(read),
                "expected_noise_mass": round(expected_noise, 2),
                "noise_share": round(expected_noise / (expected_noise + read), 4) if (expected_noise + read) else 1.0,
            }
            if total <= 0:
                low, high = low_edge, high_edge
            else:
                low = _quantile(noised, total, spec.quantiles[0], low_edge, width)
                high = _quantile(noised, total, spec.quantiles[1], low_edge, width)
                if high <= low:
                    # Two quantiles in one cell: the band is at least one cell wide,
                    # because a span with low == high is a constant wearing a
                    # range's clothes.
                    high = min(low + width, high_edge)
                    low = max(high - width, low_edge)
            about = spec.about or physics.spans[spec.parameter].about
            privacy_note = (
                f"ε={per_query:.4g} of {epsilon:g}" if noise_source == "system-entropy"
                else "seeded noise — a deterministic summary, NOT a private release"
            )
            spans[spec.parameter] = Span(
                round(low * spec.scale, 6), round(high * spec.scale, 6),
                about=about,
                source=(
                    f"calibrated from column {spec.column!r} by {self.id} v{self.version}"
                    f" (laplace-histogram, {privacy_note}, clip [{low_edge:g}, {high_edge:g}],"
                    f" {spec.bins} bins, q{spec.quantiles[0]:g}–q{spec.quantiles[1]:g})"
                ),
            ).as_dict()
            clipping[spec.column] = (low_edge, high_edge)
            bins[spec.column] = spec.bins

        privacy = PrivacyReceipt(
            mechanism="laplace-histogram", epsilon=epsilon, delta=delta,
            sensitivity=sensitivity, contribution_bound=schema.contribution_bound,
            clipping=clipping, bins=bins, queries=len(schema.columns),
            noise_source=noise_source,
        )
        receipt = Receipt(
            backend=self.id, backend_version=self.version, operation="estimate_priors",
            configuration_digest=digest(schema.model_dump(mode="json")),
            source_digest=source_digest, seed=None, privacy=privacy,
            accepted_digest=digest(spans),
            notes=f"{len(bounded)} of {len(rows)} rows read after contribution bounding",
        )
        return PriorSnapshot(spans=spans, receipt=receipt, about=schema.about, quality=quality)


def _quantile(counts: Sequence[float], total: float, q: float, low_edge: float, width: float) -> float:
    """The value at cumulative mass *q*, interpolated inside its cell."""
    target = q * total
    running = 0.0
    for index, count in enumerate(counts):
        if running + count >= target:
            inside = (target - running) / count if count else 0.0
            return low_edge + (index + inside) * width
        running += count
    return low_edge + len(counts) * width


def calibrate(
    rows: Sequence[Mapping[str, Any]],
    schema: CalibrationSchema | Mapping[str, Any],
    *,
    epsilon: float,
    delta: float = 0.0,
    estimator: Any = None,
    source_digest: str = "",
) -> PriorSnapshot:
    """The library entry point: rows and a schema in, a snapshot out."""
    resolved = schema if isinstance(schema, CalibrationSchema) else CalibrationSchema.model_validate(schema)
    backend = estimator or LaplaceHistogramEstimator()
    return backend.estimate(rows, resolved, epsilon=epsilon, delta=delta, source_digest=source_digest)


#: A schema to start from: the columns a retail transaction export would carry
#: against the physics they most plausibly inform.
TEMPLATE: dict[str, Any] = {
    "about": "Retail close physics from a monthly unit-level actuals export.",
    "unit": "business_unit",
    "contribution_bound": 12,
    "columns": [
        {"column": "revenue_miss_pct", "parameter": "retail.revenue.miss_pct",
         "clip": [-0.25, 0.10], "bins": 70, "quantiles": [0.1, 0.9],
         "about": "Actual revenue against budget, as a fraction, per unit-month."},
        {"column": "gross_margin", "parameter": "retail.margin.budget",
         "clip": [0.05, 0.70], "bins": 65, "quantiles": [0.1, 0.9],
         "about": "Budgeted gross margin per unit-month, as a fraction."},
    ],
}


__all__ = [
    "CalibrationSchema", "ColumnCalibration", "LaplaceHistogramEstimator",
    "NOISE_SHARE_WARNING", "PriorSnapshot", "SCHEMA_VERSION", "TEMPLATE",
    "calibrate", "lint",
]
