"""Paired legacy/grammar planning: one identity set, both arms, refusals kept."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from functools import lru_cache
from pathlib import Path

import pytest

from worldloom.enterprise_pairing import (
    PAIR_CATEGORIES,
    PAIR_DIMENSION,
    ArmOutcome,
    QueryPair,
    arm_queries,
    pair_outcomes,
    plan_paired_queries,
)
from worldloom.enterprise_queries import plan_queries
from worldloom.world import World

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "measure_enterprise_execution.py"
#: Long enough that the fair stream reaches the ``ambiguous_join`` and
#: ``stale_source`` rows no grammar shape admits, so refusals are exercised.
LIMIT = 40


@lru_cache(maxsize=1)
def _world() -> World:
    return World.load(ROOT / "examples" / "retail-close")


@lru_cache(maxsize=1)
def _pairs() -> tuple[QueryPair, ...]:
    return plan_paired_queries(_world(), limit=LIMIT)


def test_both_arms_carry_the_same_pairing_key() -> None:
    pairs = _pairs()
    assert len(pairs) == LIMIT
    assert len({pair.key for pair in pairs}) == LIMIT
    paired = [pair for pair in pairs if pair.grammar is not None]
    assert paired, "no identity admitted a grammar shape"
    for pair in pairs:
        assert pair.key == pair.legacy.id
        assert pair.legacy.dimensions[PAIR_DIMENSION] == pair.key
    for pair in paired:
        assert pair.grammar is not None
        assert pair.grammar.dimensions[PAIR_DIMENSION] == pair.key
        assert pair.grammar.dimensions["dag_shape"] == pair.grammar_shape
        # The grammar arm is the same base request: every base dimension
        # agrees, and only the grammar's own dimensions are added.
        base = dict(pair.legacy.dimensions)
        grammar = {key: value for key, value in pair.grammar.dimensions.items()
                   if key not in {"dag_shape", "dag_grammar"}}
        assert grammar == base
    keys = {arm: [query.dimensions[PAIR_DIMENSION] for query in arm_queries(pairs, arm)]
            for arm in ("legacy", "grammar")}
    assert set(keys["grammar"]) <= set(keys["legacy"])
    assert len(keys["grammar"]) == len(set(keys["grammar"]))


def test_legacy_arm_is_the_default_legacy_population() -> None:
    # Pairing selects identities from the same stream the default walks, and
    # only appends the key after ids are minted: strip it and the arm is the
    # default population, byte for byte.
    default, _ = plan_queries(_world(), strategy="exhaustive", limit=LIMIT)
    expected = [query.model_dump_json() for query in default]
    stripped = []
    for query in arm_queries(_pairs(), "legacy"):
        dimensions = {key: value for key, value in query.dimensions.items() if key != PAIR_DIMENSION}
        stripped.append(query.model_copy(update={"dimensions": dimensions}).model_dump_json())
    assert stripped == expected


def test_grammar_refusals_are_kept_as_pairs() -> None:
    pairs = _pairs()
    refused = [pair for pair in pairs if pair.grammar is None]
    assert refused, "limit too short to reach a row no shape admits"
    for pair in refused:
        assert pair.grammar_refusal and pair.grammar_shape is None
    assert len(arm_queries(pairs, "grammar")) == len(pairs) - len(refused)
    legacy = {pair.legacy.id: ArmOutcome("ok") for pair in pairs}
    grammar = {pair.grammar.id: ArmOutcome("behavior") for pair in pairs if pair.grammar is not None}
    table = pair_outcomes(pairs, legacy, grammar)
    assert table["pairs"] == len(pairs)
    assert table["categories"]["refused_grammar"] == len(refused)
    assert table["categories"]["legacy_only_ok"] == len(pairs) - len(refused)
    assert sum(table["categories"].values()) == len(pairs)
    assert sum(table["refusal_reasons"].values()) == len(refused)
    rows = {row[PAIR_DIMENSION]: row for row in table["rows"]}
    for pair in refused:
        assert rows[pair.key]["grammar"] == {"query_id": None, "status": "refused", "stage": "plan",
                                             "reason": pair.grammar_refusal}


def test_compile_and_runtime_refusals_classify_per_arm() -> None:
    pairs = tuple(pair for pair in _pairs() if pair.grammar is not None)[:3]
    assert len(pairs) == 3
    legacy = {pairs[0].legacy.id: ArmOutcome("refused", "compile", "no fixture"),
              pairs[1].legacy.id: ArmOutcome("ok"),
              pairs[2].legacy.id: ArmOutcome("refused", "runtime", "KeyError: x")}
    ids = [query.id for query in arm_queries(pairs, "grammar")]
    grammar = {ids[0]: ArmOutcome("ok"),
               ids[1]: ArmOutcome("refused", "compile", "insufficient records"),
               ids[2]: ArmOutcome("refused", "compile", "insufficient records")}
    table = pair_outcomes(pairs, legacy, grammar)
    assert [row["category"] for row in table["rows"]] == ["refused_legacy", "refused_grammar", "refused_both"]
    assert tuple(table["categories"]) == PAIR_CATEGORIES
    # An arm that reported nothing for a query lost a row; the table refuses
    # to absorb it as a refusal it never observed.
    with pytest.raises(KeyError):
        pair_outcomes(pairs, {}, grammar)


def test_paired_planning_is_deterministic() -> None:
    first = [pair.model_dump_json() for pair in plan_paired_queries(_world(), limit=LIMIT)]
    second = [pair.model_dump_json() for pair in plan_paired_queries(_world(), limit=LIMIT)]
    assert first == second
    # A shorter limit is a prefix: the same identities keep the same shapes.
    shorter = [pair.model_dump_json() for pair in plan_paired_queries(_world(), limit=LIMIT // 2)]
    assert shorter == first[: LIMIT // 2]


def _run_tool(*arguments: str, hash_seed: str) -> str:
    environment = {**os.environ, "PYTHONHASHSEED": hash_seed}
    result = subprocess.run(
        [sys.executable, str(TOOL), *arguments], cwd=ROOT, capture_output=True, text=True,
        env=environment, check=False,
    )
    assert result.returncode == 0, result.stderr
    return result.stdout


def test_paired_report_replays_across_hash_seeds() -> None:
    arguments = ("--paired", "--limit", "16")
    first = _run_tool(*arguments, hash_seed="13")
    assert first == _run_tool(*arguments, hash_seed="927")
    report = json.loads(first)
    paired = report["paired"]
    assert paired["pairs"] == 16
    assert report["arms"]["legacy"]["population"] == 16
    grammar = report["arms"]["grammar"]
    assert grammar["population"] + grammar["planning_refused"] == 16
    assert {row[PAIR_DIMENSION] for row in paired["rows"]} == {pair.key for pair in _pairs()[:16]}


def test_default_report_is_unpaired() -> None:
    report = json.loads(_run_tool("--limit", "4", hash_seed="0"))
    assert "paired" not in report and "arms" not in report
    assert "paired" not in report["parameters"]
    assert report["population"] == 4
