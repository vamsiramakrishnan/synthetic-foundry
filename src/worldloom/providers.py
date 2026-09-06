"""Extension seams: what an external generator may *propose*, and the receipt it leaves.

Worldloom builds a world deterministically and is the final authority on
identity, arithmetic, chronology, causality, provenance and replay. That is the
property every other module defends, and it is the reason this package imports
no generation library: a faker wordlist, a copula fit or a GAN sample inside the
byte-replay boundary is a value a seed cannot mean across versions
(``detail.py`` and ``generators/masterdata.py`` each make the argument at the
point of temptation).

But the boundary is a *boundary*, not a wall. There is a great deal outside it
worth having — a distribution learned from a customer's real ledger, a
locale's postcode grammar, a transaction-level shape a statistical model
proposes, a clinical event stream a domain simulator exports — and the way the
project already lets an outside party in is instructive. ``narrative.providers``
and ``actors.providers`` are the two seams that exist: each is a small
``Protocol`` with an ``id`` that enters a content-addressed ledger key, each
ships with a deterministic fake so the whole pipeline is testable with no
network, and each is **asked once and replayed forever** — the accepted output
is what the corpus carries, not a promise that the backend can be asked again.

This module names the four further seams on the same pattern, and the one thing
every one of them must leave behind.

The four seams
--------------

``PriorEstimator``
    Learns *ranges*, never rows: a ``parameters.Span`` per named physics
    parameter, from data it may not copy. ``calibrate.py`` ships the built-in
    differentially private estimator; a SmartNoise- or Tumult-backed adapter is
    the same protocol with a different mechanism in its receipt.

``SurfaceValueProvider``
    Leaf values only — a postcode, a phone number, a business identifier, a
    bank account — for an entity the world has already minted. It may never
    decide identity, relationships or outcomes. ``surface.py`` ships the
    vendored, versioned default.

``DetailSynthesizer``
    Proposes candidate transaction-level rows. ``accept`` below is what makes a
    proposal into data: it reconciles every declared total by largest
    remainder, refuses what violates a constraint, and records what it did.
    The synthesizer never mints a canonical fact; the ledger already stated the
    total, and the rows are made to agree with it.

``DomainImporter``
    Turns an external simulator's export — a FHIR bundle, a Synthea history —
    into neutral ``ImportedEvent`` records with a digest of what was read. What
    the world *does* with imported events is a vertical's business; this seam
    only guarantees the import is recorded and reproducible from its source.

The receipt
-----------

Every external execution produces a ``Receipt``: backend and version, the
operation, digests of configuration, source, candidate and accepted output, the
seed if any, and a ``PrivacyReceipt`` when a privacy budget was spent. Its
``key`` is a content address over all of that, the same discipline as
``GenerationLedgerEntry.key`` — and for the same reason. A corpus that says "the
priors came from SmartNoise" has said nothing; one that says "this digest of
this source, under this configuration, produced spans with this digest, at ε=1"
has said something a reader can check and a rebuild can refuse to drift from.

**Digests, never data.** No receipt field carries a value from the source.
``source_digest`` is a hash of the bytes read; ``accepted_digest`` is a hash of
what came out. A receipt is safe to ship in a corpus precisely because it
proves what happened without repeating any of it.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .ids import content_key
from .rng import Rng

if TYPE_CHECKING:  # pragma: no cover
    from .calibrate import CalibrationSchema, PriorSnapshot
    from .locales import Locale


class Model(BaseModel):
    """Frozen and closed, like every other record a corpus carries."""

    model_config = ConfigDict(frozen=True, extra="forbid")


def digest(payload: Any) -> str:
    """A content address for any JSON-serialisable value.

    Canonical JSON — sorted keys, no whitespace — so two equal values hash
    equal whatever order their keys arrived in. Same width as ``content_key``
    (32 hex characters) so a digest and a ledger key look like the same kind of
    thing, because they are.
    """
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:32]


def digest_bytes(data: bytes) -> str:
    """A content address for raw bytes — the source file a calibration read."""
    return hashlib.sha256(data).hexdigest()[:32]


# ---------------------------------------------------------------------------
# The receipt
# ---------------------------------------------------------------------------


class PrivacyReceipt(Model):
    """What a privacy budget bought, stated so it can be audited.

    Every field here is something a reviewer asks about a differentially
    private release and cannot reconstruct afterwards: the mechanism, the
    budget, the sensitivity bound it rested on, how contributions were bounded,
    how the domain was clipped and discretised, and how the per-query budgets
    were composed into the total.
    """

    mechanism: str
    """``"laplace-histogram"`` for the built-in estimator; a backend's own
    name for an adapter (``"smartnoise-mwem"``)."""

    epsilon: float = Field(gt=0.0)
    delta: float = Field(default=0.0, ge=0.0)
    """Zero for pure ε-DP mechanisms. Recorded even at zero so a reader never
    has to wonder whether it was omitted or was zero."""

    sensitivity: float = Field(gt=0.0)
    """The L1 sensitivity each noised query was calibrated to."""

    contribution_bound: int = Field(ge=1)
    """Most rows one individual may contribute. Sensitivity rests on this, so
    a bound that was not enforced is a privacy claim that is not true — the
    estimator enforces it by truncation, and says so here."""

    clipping: dict[str, tuple[float, float]] = Field(default_factory=dict)
    """Per-column domain bounds the values were clipped to before release."""

    bins: dict[str, int] = Field(default_factory=dict)
    """Per-column histogram resolution."""

    composition: Literal["sequential"] = "sequential"
    queries: int = Field(ge=1)
    """How many noised releases the total budget was split across."""

    noise_source: Literal["system-entropy", "seeded"] = "system-entropy"
    """Where the noise came from. ``seeded`` exists for tests and is **not a
    privacy guarantee**: noise an adversary can regenerate is not noise. The
    estimator refuses to call a seeded release private anywhere but here."""

    @property
    def private(self) -> bool:
        """Whether this receipt describes a release anyone should call private."""
        return self.noise_source == "system-entropy"


class Receipt(Model):
    """One recorded external execution — the thing a corpus carries in place of
    the backend that ran."""

    backend: str
    backend_version: str
    operation: str
    """``"estimate_priors"``, ``"surface_values"``, ``"propose_rows"``,
    ``"import_events"`` — the seam's verb."""

    configuration_digest: str
    source_digest: str = ""
    """Hash of the bytes the backend read. Empty when it read nothing outside
    the world (a surface provider drawing from its own vendored rules)."""

    seed: int | None = None
    privacy: PrivacyReceipt | None = None
    candidate_digest: str = ""
    """Hash of what the backend *proposed*, before acceptance."""

    acceptance_digest: str = ""
    """Hash of the acceptance report — what was reconciled, what was refused."""

    accepted_digest: str
    """Hash of what actually entered the world."""

    notes: str = ""

    @property
    def key(self) -> str:
        """The content address, over everything above. The ledger-key discipline:
        change any input and the key changes, so a replay that finds a different
        key knows the world it is rebuilding is not the one that was recorded."""
        return content_key(
            self.backend, self.backend_version, self.operation,
            self.configuration_digest, self.source_digest, self.seed,
            self.privacy.model_dump_json() if self.privacy else "",
            self.candidate_digest, self.acceptance_digest, self.accepted_digest,
        )


# ---------------------------------------------------------------------------
# Stable keys: how a surface value is addressed
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StableKey:
    """Where a leaf value belongs: which entity, which field, under which seed.

    A surface value is derived from ``world seed / provider version / entity
    type / entity id / field``, never from draw order. That is what lets a
    provider be upgraded without renaming every vendor in every old corpus —
    the version is *in the path*, so an old recipe replays under the version it
    recorded — and what lets a new field be added to vendors without moving a
    single customer's phone number.
    """

    seed: int
    entity_type: str
    entity_id: str
    field: str

    def stream(self, provider_version: str) -> Rng:
        return Rng(
            self.seed,
            f"surface/{provider_version}/{self.entity_type}/{self.entity_id}/{self.field}",
        )


# ---------------------------------------------------------------------------
# The protocols
# ---------------------------------------------------------------------------


@runtime_checkable
class PriorEstimator(Protocol):
    """Anything that can turn data it may not copy into physics ranges."""

    id: str
    version: str

    def estimate(
        self,
        rows: Sequence[Mapping[str, Any]],
        schema: CalibrationSchema,
        *,
        epsilon: float,
        delta: float = 0.0,
    ) -> PriorSnapshot:
        """Bounded aggregate priors over *rows*, with a receipt. Never rows."""
        ...


@runtime_checkable
class SurfaceValueProvider(Protocol):
    """Leaf values for an entity the world already minted.

    Every method takes the ``StableKey`` of the field it fills and the
    ``Locale`` the world is in, and must be a pure function of both plus the
    provider's own version — no state between calls, no clock, no global RNG.
    """

    id: str
    version: str

    def postcode(self, key: StableKey, locale: Locale, *, city: str) -> str: ...

    def phone(self, key: StableKey, locale: Locale, *, city: str) -> str: ...

    def business_identifier(self, key: StableKey, locale: Locale, *, city: str) -> str: ...

    def bank_account(self, key: StableKey, locale: Locale, *, city: str) -> str: ...


class Candidate(Model):
    """What a synthesizer proposed: rows, and the receipt-to-be's raw material."""

    backend: str
    backend_version: str
    configuration_digest: str
    seed: int | None = None
    rows: tuple[dict[str, float | int | str | None], ...]

    @property
    def digest(self) -> str:
        return digest([dict(sorted(row.items())) for row in self.rows])


class Acceptance(Model):
    """What ``accept`` did to a candidate before it became data."""

    accepted: int
    refused: int
    reconciled_columns: tuple[str, ...]
    refusals: tuple[str, ...] = ()
    """One line per refused row, naming the row index and the rule."""

    @property
    def digest(self) -> str:
        return digest(self.model_dump(mode="json"))


@runtime_checkable
class DetailSynthesizer(Protocol):
    """Proposes transaction-level rows. Proposes — ``accept`` decides."""

    id: str
    version: str

    def propose(
        self,
        *,
        columns: Sequence[str],
        rows: int,
        seed: int,
        configuration: Mapping[str, Any] | None = None,
    ) -> Candidate: ...


class ImportedEvent(Model):
    """One event read from an external simulator, in neutral vocabulary."""

    kind: str = Field(pattern=r"^[a-z][a-z0-9_.]*$")
    occurred_at: str
    """ISO-8601, as the source stated it. Parsed by whoever consumes it, so a
    source's own precision survives the import."""

    subject: str
    attributes: dict[str, float | int | str | bool | None] = Field(default_factory=dict)
    source_ref: str = ""
    """The source's own identifier for the record this came from."""


@runtime_checkable
class DomainImporter(Protocol):
    """Reads an external export into events, and says exactly what it read."""

    id: str
    version: str

    def events(self, source: bytes) -> tuple[tuple[ImportedEvent, ...], Receipt]: ...


# ---------------------------------------------------------------------------
# Acceptance: the half that makes a proposal into data
# ---------------------------------------------------------------------------


def _allocate(total: float, weights: Sequence[float], decimals: int) -> list[float]:
    """Largest-remainder split of *total* by *weights* at *decimals* places.

    ``finance.allocate`` reasons over integers; this is the same discipline at
    a declared precision — scale to integer units, allocate, scale back — so
    the column sums to the total exactly at that precision by construction.
    """
    scale = 10 ** decimals
    units = round(total * scale)
    weight_sum = sum(weights) or 1.0
    exact = [units * w / weight_sum for w in weights]
    floors = [int(x) for x in exact]
    remainder = units - sum(floors)
    # Spare units to the largest fractional parts; index order breaks ties so
    # the same rows get them every rebuild.
    order = sorted(range(len(exact)), key=lambda i: (-(exact[i] - floors[i]), i))
    for i in order[:remainder]:
        floors[i] += 1
    return [f / scale for f in floors]


def accept(
    candidate: Candidate,
    *,
    totals: Mapping[str, float],
    decimals: int = 2,
    required: Sequence[str] = (),
    bounds: Mapping[str, tuple[float, float]] | None = None,
) -> tuple[tuple[dict[str, Any], ...], Acceptance, Receipt]:
    """Reconcile a candidate against what the ledger states, and record it.

    Three things happen, in this order, and the order matters:

    1. **Refusal.** A row missing a ``required`` column, or carrying a value
       outside its declared ``bounds``, is dropped and named. Refusing first
       means a bad row cannot distort the shares of the good ones.
    2. **Reconciliation.** Each column in ``totals`` is re-allocated across the
       surviving rows by largest remainder, using the proposed values as
       *weights*. The synthesizer's shape survives; the sum is the ledger's.
       This is ``detail.py``'s non-negotiable rule applied to a proposal that
       arrived from outside: rows are never "close enough" to a total.
    3. **The receipt.** Candidate digest, acceptance digest and accepted
       digest — so a corpus can prove what was proposed, what was done to it,
       and what it kept, without carrying the backend.

    A column in ``totals`` that no surviving row carries is a hard error rather
    than a silent zero: a total with nothing to allocate over is a claim the
    corpus would be making about rows that do not exist.
    """
    bounds = dict(bounds or {})
    kept: list[dict[str, Any]] = []
    refusals: list[str] = []
    for index, row in enumerate(candidate.rows):
        missing = [name for name in required if row.get(name) is None]
        if missing:
            refusals.append(f"row {index}: missing {missing}")
            continue
        out_of_bounds = [
            name for name, (low, high) in sorted(bounds.items())
            if isinstance(row.get(name), (int, float))
            and not (low <= float(row[name]) <= high)  # type: ignore[arg-type]
        ]
        if out_of_bounds:
            refusals.append(f"row {index}: {out_of_bounds} outside declared bounds")
            continue
        kept.append(dict(row))

    reconciled: list[str] = []
    for column in sorted(totals):
        weights = [
            max(float(row[column]), 0.0) if isinstance(row.get(column), (int, float)) else 0.0
            for row in kept
        ]
        if not kept:
            raise ValueError(
                f"total for {column!r} has no accepted rows to allocate over;"
                f" {len(refusals)} of {len(candidate.rows)} rows were refused"
            )
        if not any(weights):
            # Nothing proposed a share — allocate evenly rather than fail. The
            # sum is still the ledger's; the shape was simply not proposed.
            weights = [1.0] * len(kept)
        for row, value in zip(kept, _allocate(float(totals[column]), weights, decimals)):
            row[column] = value
        reconciled.append(column)

    acceptance = Acceptance(
        accepted=len(kept), refused=len(refusals),
        reconciled_columns=tuple(reconciled), refusals=tuple(refusals),
    )
    accepted_rows = tuple(kept)
    receipt = Receipt(
        backend=candidate.backend,
        backend_version=candidate.backend_version,
        operation="propose_rows",
        configuration_digest=candidate.configuration_digest,
        seed=candidate.seed,
        candidate_digest=candidate.digest,
        acceptance_digest=acceptance.digest,
        accepted_digest=digest([dict(sorted(row.items())) for row in accepted_rows]),
    )
    return accepted_rows, acceptance, receipt


# ---------------------------------------------------------------------------
# The deterministic fake, for the same reason `DeterministicProvider` exists
# ---------------------------------------------------------------------------


class EvenSynthesizer:
    """A synthesizer with no model behind it.

    Proposes rows whose numeric columns are drawn uniformly from a seeded
    stream — no shape worth having, which is the point: it exercises the
    propose → accept → receipt contract so the contract is proven before any
    statistical backend is written against it. ``accept`` is what gives the
    rows their sums; this only gives them a proposal to reconcile.
    """

    id = "even-fake"
    version = "1"

    def propose(
        self,
        *,
        columns: Sequence[str],
        rows: int,
        seed: int,
        configuration: Mapping[str, Any] | None = None,
    ) -> Candidate:
        configuration = dict(configuration or {})
        rng = Rng(seed, f"synth/{self.id}/{self.version}")
        proposed: list[dict[str, float | int | str | None]] = []
        for index in range(rows):
            row: dict[str, float | int | str | None] = {"line": index + 1}
            for column in columns:
                row[column] = rng.derive(f"{column}/{index}").number(0.0, 1.0, places=6)
            proposed.append(row)
        return Candidate(
            backend=self.id, backend_version=self.version,
            configuration_digest=digest(configuration), seed=seed,
            rows=tuple(proposed),
        )


__all__ = [
    "Acceptance", "Candidate", "DetailSynthesizer", "DomainImporter",
    "EvenSynthesizer", "ImportedEvent", "PriorEstimator", "PrivacyReceipt",
    "Receipt", "StableKey", "SurfaceValueProvider", "accept", "digest",
    "digest_bytes",
]
