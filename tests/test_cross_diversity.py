"""Cross-corpus shape overlap: the failure no single corpus's report can see.

Five mosaic companies can each score a respectable unique-shape ratio while
all five hold the same shapes — first noticed as thirty-one benchmark
questions asked byte-identically across five worlds. `cross_report` makes
that a number per corpus pair instead of an anecdote.
"""

from __future__ import annotations

from worldloom.compiler.diversity import Fingerprint, cross_report


def _fp(artifact_type: str, *components: str) -> Fingerprint:
    return Fingerprint(
        artifact_type=artifact_type,
        components=tuple(components),
        layouts=(),
        style_key="",
        density_bucket="balanced",
        section_count=len(components),
    )


def test_identical_batches_read_as_total_overlap() -> None:
    batch = [_fp("memo", "a", "b"), _fp("memo", "a", "c")]
    reading = cross_report({"one": batch, "two": list(batch)})
    assert reading.shared_shapes == 2
    assert reading.shared_share == {"one": 1.0, "two": 1.0}
    assert reading.pair_overlap[("one", "two")] == 1.0


def test_disjoint_batches_read_as_none() -> None:
    reading = cross_report({
        "one": [_fp("memo", "a", "b")],
        "two": [_fp("filing", "x", "y")],
    })
    assert reading.shared_shapes == 0
    assert reading.shared_share == {"one": 0.0, "two": 0.0}
    assert reading.pair_overlap[("one", "two")] == 0.0


def test_internal_repetition_is_not_fleet_overlap() -> None:
    # Corpus one repeats a shared shape five times; the pair overlap is over
    # digest *sets*, so its internal monotony (its own report's business)
    # does not inflate how much the fleet overlaps.
    shared = _fp("memo", "a", "b")
    reading = cross_report({
        "one": [shared] * 5 + [_fp("memo", "q", "r")],
        "two": [shared, _fp("filing", "x", "y")],
    })
    assert reading.shared_shapes == 1
    assert reading.pair_overlap[("one", "two")] == 1 / 3
    # But shared_share is over artifacts, because that is the exposure: five
    # sixths of corpus one is reproducible from its neighbour.
    assert reading.shared_share["one"] == 5 / 6


def test_order_and_denominators_are_the_callers() -> None:
    reading = cross_report({"b": [], "a": [_fp("memo", "a")]})
    assert reading.corpora == ("b", "a")
    assert reading.counts == {"b": 0, "a": 1}
    # An empty batch shares nothing and divides by nothing.
    assert reading.shared_share["b"] == 0.0
    assert list(reading.pair_overlap) == [("b", "a")]
