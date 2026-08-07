"""Mass-corpus shards and checkpoints are deterministic and resumable."""

from __future__ import annotations

import pytest

from worldloom import batch
from worldloom.models import GenerationLedgerEntry


def _entry(key: str = "a" * 32, *, ordinal: int = 0) -> GenerationLedgerEntry:
    return GenerationLedgerEntry(
        id=f"GEN-CKPT-{ordinal:016X}",
        key=key,
        call_site=f"ART-0001/section-{ordinal}",
        ordinal=ordinal,
        world_seed=8128,
        input_facts_digest="facts",
        model_id="deterministic-fake-1",
        prompt_version="section_prose@3",
        output={"text": "grounded", "claims": []},
    )


def test_shards_are_disjoint_and_exhaust_the_global_plan() -> None:
    worlds = tuple(range(1, 18))
    shards = [batch.owned(worlds, shard_count=4, shard_index=index) for index in range(4)]
    assert sorted(value for shard in shards for value in shard) == list(worlds)
    assert all(set(left).isdisjoint(right)
               for index, left in enumerate(shards) for right in shards[index + 1:])


def test_plan_digest_refuses_argument_drift(tmp_path) -> None:  # type: ignore[no-untyped-def]
    plan = {"seed": 8128, "worlds": [{"index": 1}]}
    batch.install_plan(tmp_path, plan, resume=False)
    assert batch.install_plan(tmp_path, plan, resume=True) == batch.digest(plan)
    with pytest.raises(ValueError, match="different mosaic plan"):
        batch.install_plan(tmp_path, {**plan, "seed": 8129}, resume=True)


def test_checkpoint_is_append_only_and_deduplicated_on_load(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checkpoint = batch.Checkpoint(tmp_path, 7)
    entry = _entry()
    checkpoint.append(entry)
    checkpoint.append(entry)
    assert checkpoint.load() == (entry,)
    assert len(checkpoint.path.read_text(encoding="utf-8").splitlines()) == 2


def test_checkpoint_recovers_only_an_unterminated_final_record(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checkpoint = batch.Checkpoint(tmp_path, 8)
    first, second = _entry(), _entry("b" * 32, ordinal=1)
    checkpoint.append(first)
    with checkpoint.path.open("ab") as handle:
        handle.write(b'{"id":"GEN-CKPT-torn"')

    # Appending without an intervening load also repairs the torn tail, so a
    # resumed worker cannot join a valid row onto an incomplete one.
    checkpoint.append(second)

    assert checkpoint.load() == (first, second)
    assert checkpoint.path.read_bytes().endswith(b"\n")
    assert b"GEN-CKPT-torn" not in checkpoint.path.read_bytes()


def test_checkpoint_rejects_a_malformed_committed_record(tmp_path) -> None:  # type: ignore[no-untyped-def]
    checkpoint = batch.Checkpoint(tmp_path, 9)
    checkpoint.append(_entry())
    with checkpoint.path.open("ab") as handle:
        handle.write(b"{not-json}\n")

    with pytest.raises(ValueError, match=r"checkpoint .*:2"):
        checkpoint.load()
