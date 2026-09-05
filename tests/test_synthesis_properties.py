"""Generated counterexamples for trajectory partitioning and intervention isolation."""

from __future__ import annotations

import pytest

pytest.importorskip("hypothesis")
from hypothesis import given, settings
from hypothesis import strategies as st

from worldloom.synthesis import Intervention, Simulator, banking, retail


@settings(max_examples=32, derandomize=True, database=None, deadline=2000)
@given(seed=st.integers(min_value=-(2**31), max_value=2**31 - 1),
       entities=st.integers(1, 5), ticks=st.integers(1, 12),
       shards=st.integers(1, 7), is_bank=st.booleans())
def test_partitioning_never_resets_state_or_loses_dimension_rows(seed, entities, ticks, shards, is_bank):
    program = banking(borrowers=entities, ticks=ticks) if is_bank else retail(stores=entities, products=2, ticks=ticks)
    simulator = Simulator(program, seed=seed)
    expected = tuple(simulator.rows())
    partitioned = tuple(sorted(
        (row for index in range(shards) for row in simulator.rows(shard_index=index, shard_count=shards)),
        key=lambda row: (row.table, row.entity, row.tick),
    ))
    assert partitioned == expected
    assert len({row.id for row in partitioned}) == len(expected)


@settings(max_examples=32, derandomize=True, database=None, deadline=2000)
@given(seed=st.integers(min_value=-(2**31), max_value=2**31 - 1),
       tick=st.integers(0, 9))
def test_cash_intervention_preserves_common_noise_and_unaffected_borrowers(seed, tick):
    simulator = Simulator(banking(borrowers=3, ticks=12), seed=seed)
    changed = simulator.counterfactual(Intervention(table="loan", column="capacity", value=0,
                                                    start=tick, stop=tick + 1, entities=(0,)))
    for original, alternative in zip(simulator.rows(), changed.rows(), strict=True):
        assert original.id == alternative.id and original.links == alternative.links
        if original.table != "loan" or original.entity != 0 or original.tick < tick:
            assert original == alternative
        else:
            before, after = original.values(), alternative.values()
            assert before["income_noise"] == after["income_noise"]
            assert after["closing"] >= before["closing"]
            if original.tick == tick:
                assert after["paid"] == 0
