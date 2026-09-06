"""The extension seams and the receipt every external execution leaves.

Three properties, each the reason the seam is safe to open:

* A receipt's key is a content address over *all* of its inputs — change any
  one and the key moves — and no receipt field carries a value from the
  source, only digests of it.
* ``accept`` makes a proposal into data by reconciling every declared total by
  largest remainder at the declared precision, so the rows sum to the ledger
  exactly, and by refusing rows that violate a constraint *before* the shares
  are computed.
* The deterministic fake proposes the same candidate for the same seed, so
  the propose → accept → receipt pipeline is testable with no backend at all
  — the same argument ``narrative.providers.DeterministicProvider`` makes.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from worldloom import providers
from worldloom.providers import (
    Candidate,
    DetailSynthesizer,
    EvenSynthesizer,
    PrivacyReceipt,
    Receipt,
    StableKey,
    accept,
    digest,
)


def _receipt(**overrides) -> Receipt:
    base = dict(
        backend="smartnoise", backend_version="1.0", operation="estimate_priors",
        configuration_digest=digest({"a": 1}), source_digest="ab" * 16, seed=8128,
        accepted_digest=digest({"b": 2}),
    )
    base.update(overrides)
    return Receipt(**base)


def test_the_key_is_a_content_address_over_every_input() -> None:
    reference = _receipt().key
    assert len(reference) == 32
    assert _receipt().key == reference
    for change in (
        {"backend": "tumult"}, {"backend_version": "1.1"}, {"operation": "propose_rows"},
        {"configuration_digest": digest({"a": 2})}, {"source_digest": "cd" * 16},
        {"seed": 8129}, {"accepted_digest": digest({"b": 3})},
        {"privacy": PrivacyReceipt(mechanism="laplace", epsilon=1.0, sensitivity=1.0,
                                   contribution_bound=1, queries=1)},
    ):
        assert _receipt(**change).key != reference, change


def test_a_seeded_privacy_receipt_is_not_private() -> None:
    """Noise an adversary can regenerate is not noise."""
    private = PrivacyReceipt(mechanism="laplace", epsilon=1.0, sensitivity=1.0,
                             contribution_bound=1, queries=1)
    seeded = private.model_copy(update={"noise_source": "seeded"})
    assert private.private and not seeded.private


def test_digest_is_canonical_over_key_order() -> None:
    assert digest({"a": 1, "b": [1, 2]}) == digest({"b": [1, 2], "a": 1})
    assert digest({"a": 1}) != digest({"a": 2})


def test_receipts_are_closed_and_frozen() -> None:
    with pytest.raises(ValidationError):
        Receipt(**{**_receipt().model_dump(), "rows": []})  # type: ignore[arg-type]
    with pytest.raises(ValidationError):
        _receipt().backend = "other"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# accept
# ---------------------------------------------------------------------------


def test_the_fake_satisfies_the_protocol_and_is_deterministic() -> None:
    fake = EvenSynthesizer()
    assert isinstance(fake, DetailSynthesizer)
    a = fake.propose(columns=["amount", "qty"], rows=7, seed=3)
    b = fake.propose(columns=["amount", "qty"], rows=7, seed=3)
    assert a == b and a.digest == b.digest
    assert fake.propose(columns=["amount", "qty"], rows=7, seed=4).digest != a.digest


def test_accept_reconciles_every_total_exactly_at_the_declared_precision() -> None:
    candidate = EvenSynthesizer().propose(columns=["amount", "qty"], rows=13, seed=1)
    rows, acceptance, receipt = accept(candidate, totals={"amount": 1234.57, "qty": 91}, decimals=2)
    assert acceptance.accepted == 13 and acceptance.refused == 0
    assert acceptance.reconciled_columns == ("amount", "qty")
    assert round(sum(row["amount"] for row in rows), 2) == 1234.57
    assert round(sum(row["qty"] for row in rows), 2) == 91.0
    # The proposal's *shape* survives: the largest proposed share is still the largest.
    proposed = max(candidate.rows, key=lambda r: r["amount"])["line"]
    assert max(rows, key=lambda r: r["amount"])["line"] == proposed
    assert receipt.candidate_digest == candidate.digest
    assert receipt.accepted_digest == digest([dict(sorted(r.items())) for r in rows])
    assert receipt.operation == "propose_rows" and receipt.key


def test_accept_refuses_before_it_reconciles() -> None:
    candidate = Candidate(
        backend="x", backend_version="1", configuration_digest=digest({}),
        rows=(
            {"line": 1, "amount": 0.2, "qty": 3},
            {"line": 2, "amount": 9.0, "qty": 3},      # out of bounds — refused
            {"line": 3, "amount": None, "qty": 3},     # missing — refused
            {"line": 4, "amount": 0.6, "qty": 3},
        ),
    )
    rows, acceptance, _ = accept(
        candidate, totals={"amount": 100.0}, required=["amount"], bounds={"amount": (0.0, 1.0)},
    )
    assert acceptance.refused == 2 and acceptance.accepted == 2
    assert [r["line"] for r in rows] == [1, 4]
    # The refused 9.0 did not distort the surviving shares: 0.2 : 0.6 → 25 : 75.
    assert [r["amount"] for r in rows] == [25.0, 75.0]
    assert any("outside declared bounds" in line for line in acceptance.refusals)
    assert any("missing" in line for line in acceptance.refusals)


def test_a_negative_total_reconciles_exactly_too() -> None:
    """A credit note is a total like any other. `int()` truncated toward zero
    and -1.00 over 1:2:3 came back as -0.97 (Codex review, PR #40); flooring
    keeps the remainder a count of units still to place, whatever the sign."""
    from worldloom.providers import _allocate

    for total in (-1.00, -0.05, -1234.57, 0.0, 0.01):
        for weights in ([1, 2, 3], [1, 1, 1], [0.7, 0.2, 0.1, 0.0]):
            shares = _allocate(total, weights, 2)
            assert round(sum(shares), 2) == round(total, 2), (total, weights, shares)
    assert _allocate(-1.00, [1, 2, 3], 2) == [-0.17, -0.33, -0.5]
    candidate = EvenSynthesizer().propose(columns=["amount"], rows=9, seed=2)
    rows, _, _ = accept(candidate, totals={"amount": -250.25})
    assert round(sum(row["amount"] for row in rows), 2) == -250.25


def test_a_total_with_nothing_to_allocate_over_is_an_error() -> None:
    candidate = Candidate(backend="x", backend_version="1", configuration_digest=digest({}),
                          rows=({"amount": None},))
    with pytest.raises(ValueError, match="no accepted rows"):
        accept(candidate, totals={"amount": 10.0}, required=["amount"])


def test_a_stable_key_is_a_path_that_carries_the_version() -> None:
    key = StableKey(8128, "vendor", "VND-00001", "phone")
    assert key.stream("1").label == "surface/1/vendor/VND-00001/phone"
    # Same seed, same path, same draw; a version bump is a different stream.
    assert key.stream("1").integer(0, 10**9) == key.stream("1").integer(0, 10**9)
    assert key.stream("1").integer(0, 10**9) != key.stream("2").integer(0, 10**9)


def test_the_module_exports_the_four_seams() -> None:
    for name in ("PriorEstimator", "SurfaceValueProvider", "DetailSynthesizer", "DomainImporter"):
        assert name in providers.__all__
    json.dumps(_receipt().model_dump(mode="json"))
