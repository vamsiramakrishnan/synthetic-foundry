"""Mechanisms, not row-count theatre: conservation, interventions and replay."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from hashlib import sha256
from pathlib import Path

import pytest

from worldloom.synthesis import (
    Column,
    Constraint,
    Expr,
    Intervention,
    Limits,
    Program,
    Relation,
    Simulator,
    SynthesisError,
    Table,
    banking,
    compare,
    compile_program,
    export,
    expr,
    lag,
    literal,
    merge_exports,
    param,
    ref,
    retail,
    uniform,
    verify_export,
)
from worldloom.synthesis.compiler import canonical
from worldloom.synthesis.storage import iter_export


def simple(*columns: Column, count: int = 3, ticks: int = 4,
           constraints: tuple[Constraint, ...] = ()) -> Program:
    return Program(namespace="test", ticks=ticks, tables=(
        Table(name="series", count=count, temporal=True, columns=columns,
              constraints=constraints),
    ))


def col(name: str, expression: Expr, **kwargs) -> Column:
    return Column(name=name, expression=expression, **kwargs)


def encoded(simulator: Simulator) -> bytes:
    return b"".join(canonical(row.model_dump(mode="json")) for row in simulator.rows())


@pytest.mark.parametrize("seed", [0, 1, -1, 42, 8128, 999999])
@pytest.mark.parametrize("vertical", ["retail", "banking"])
def test_conservation_and_recurrence_across_populations(seed: int, vertical: str) -> None:
    program = retail(stores=3, products=4, ticks=17) if vertical == "retail" else banking(borrowers=12, ticks=17)
    simulator = Simulator(program, seed=seed)
    rows = list(simulator.rows())
    assert len(rows) == simulator.compiled.rows
    assert len({r.id for r in rows}) == len(rows)
    dimensions = {r.entity_id for r in rows if r.table in {"store", "product", "borrower"}}
    histories = {}
    for row in rows:
        assert all(link.entity_id in dimensions for link in row.links)
        if row.table not in {"inventory", "loan"}:
            continue
        v = row.values()
        history = histories.setdefault(row.entity_id, [])
        if history:
            assert v["opening"] == history[-1]["closing"]
        if vertical == "retail":
            assert v["opening"] + v["receipts"] == v["sold"] + v["closing"]
            assert v["demand"] == v["sold"] + v["lost"]
            assert v["margin"] == v["revenue"] - v["cost"]
            assert v["receipts"] == (history[-2]["order"] if len(history) >= 2 else 0)
            assert v["pipeline"] == (history[-1]["order"] if history else 0)
        else:
            assert v["opening"] + v["interest"] == v["paid"] + v["closing"]
            assert 0 <= v["arrears"] <= v["closing"]
            assert v["due"] == v["paid"] + v["arrears"]
            assert v["missed_periods"] == ((history[-1]["missed_periods"] if history else 0) + 1 if v["arrears"] else 0)
        history.append(v)
    assert encoded(simulator) == encoded(Simulator(program, seed=seed))


def test_declaration_order_cannot_change_values_or_ids() -> None:
    program = retail(stores=2, products=4, ticks=5)
    reordered = program.model_copy(update={"tables": tuple(
        table.model_copy(update={"columns": tuple(reversed(table.columns)),
                                 "relations": tuple(reversed(table.relations)),
                                 "constraints": tuple(reversed(table.constraints))})
        for table in reversed(program.tables)
    )})
    assert encoded(Simulator(program)) == encoded(Simulator(reordered))


def test_adding_an_unrelated_column_does_not_shift_noise() -> None:
    program = simple(col("x", uniform(0, 1000, stream="x")))
    table = program.tables[0]
    extended = program.model_copy(update={"tables": (table.model_copy(update={
        "columns": table.columns + (col("a", uniform(0, 1000, stream="a")),)
    }),)})
    left, right = list(Simulator(program).rows()), list(Simulator(extended).rows())
    assert [r.id for r in left] == [r.id for r in right]
    assert [r.values()["x"] for r in left] == [r.values()["x"] for r in right]


def test_noise_scope_makes_shared_and_idiosyncratic_shocks() -> None:
    program = simple(
        col("market", uniform(0, 10**8, stream="market", scope="tick")),
        col("individual", uniform(0, 10**8, stream="individual")),
        col("trait", uniform(0, 10**8, stream="trait", scope="entity")),
        col("constant", uniform(0, 10**8, stream="constant", scope="world")),
        count=6, ticks=8,
    )
    rows = list(Simulator(program).rows())
    assert len({r.values()["constant"] for r in rows}) == 1
    for tick in range(8):
        group = [r.values() for r in rows if r.tick == tick]
        assert len({v["market"] for v in group}) == 1
        assert len({v["individual"] for v in group}) > 1
    for entity in range(6):
        assert len({r.values()["trait"] for r in rows if r.entity == entity}) == 1


def test_pair_changes_only_descendants_inside_the_selected_trajectory() -> None:
    base = Simulator(retail(stores=2, products=3, ticks=10))
    twin = base.counterfactual(Intervention(table="inventory", column="demand", value=100,
                                            start=3, stop=5, entities=(1,)))
    deltas = list(compare(base, twin))
    assert deltas
    assert {d.table for d in deltas} == {"inventory"}
    assert {d.entity for d in deltas} == {1}
    assert min(d.tick for d in deltas) == 3
    assert any(d.tick > 4 for d in deltas), "the intervention should propagate through inventory state"
    assert not {"market", "noise", "promotion", "product", "store"} & {d.column for d in deltas}
    assert [r.id for r in base.rows()] == [r.id for r in twin.rows()]


def test_static_dimension_intervention_propagates_through_foreign_keys() -> None:
    dimension = Table(name="dimension", count=2, columns=(col("price", literal(10), intervenable=True),))
    fact = Table(name="fact", count=4, temporal=True,
                 relations=(Relation(name="product", table="dimension"),),
                 columns=(col("revenue", expr("mul", ref("product.price"), literal(3))),))
    base = Simulator(Program(namespace="relations", ticks=3, tables=(fact, dimension)))
    twin = base.counterfactual(Intervention(table="dimension", column="price", value=20, entities=(1,)))
    deltas = list(compare(base, twin))
    assert {d.entity for d in deltas if d.table == "fact"} == {1, 3}
    assert all(d.after == 60 for d in deltas if d.table == "fact")


@pytest.mark.parametrize("intervention,code", [
    (Intervention(table="inventory", column="closing", value=0), "protected_column"),
    (Intervention(table="missing", column="demand", value=0), "unknown_intervention"),
    (Intervention(table="inventory", column="demand", value=-1), "column_bounds"),
    (Intervention(table="inventory", column="demand", value=True), "value_type"),
    (Intervention(table="inventory", column="demand", value=1, start=100), "intervention_window"),
    (Intervention(table="inventory", column="demand", value=1, entities=()), "intervention_entities"),
    (Intervention(table="inventory", column="demand", value=1, entities=(0, 0)), "intervention_entities"),
    (Intervention(table="inventory", column="demand", value=1, entities=(-1,)), "intervention_entities"),
    (Intervention(table="inventory", column="demand", value=1, entities=(99999,)), "intervention_entities"),
])
def test_invalid_interventions_are_refused(intervention: Intervention, code: str) -> None:
    with pytest.raises(SynthesisError, match=code):
        Simulator(retail(), interventions=(intervention,))


def test_overlapping_interventions_are_not_last_writer_wins() -> None:
    intervention = Intervention(table="inventory", column="demand", value=0, entities=(0,))
    with pytest.raises(SynthesisError, match="overlapping_interventions"):
        Simulator(retail(), interventions=(intervention, intervention))
    a = intervention.model_copy(update={"stop": 3})
    b = intervention.model_copy(update={"start": 3})
    assert Simulator(retail(), interventions=(a, b))


def test_unpaired_counterfactual_is_refused() -> None:
    with pytest.raises(SynthesisError, match="unpaired_worlds"):
        list(compare(Simulator(retail(), seed=1), Simulator(retail(), seed=2)))


@pytest.mark.parametrize("columns,code", [
    ((col("x", ref("y")), col("y", ref("x"))), "cycle"),
    ((col("x", ref("missing")),), "unknown_reference"),
    ((col("x", param("missing")),), "unknown_parameter"),
    ((col("x", Expr(op="add", args=(literal(1),))),), "arity"),
    ((col("x", Expr(op="uniform", args=(literal(0), literal(1)))),), "noise_stream"),
    ((col("x", Expr(op="literal", value=1, stream="ignored")),), "unused_attribute"),
    ((col("x", literal(True)),), "expression_type"),
    ((col("x", expr("add", literal(True), literal(1))),), "expression_type"),
    ((col("x", expr("if", literal(1), literal(2), literal(3))),), "expression_type"),
    ((col("x", lag("x", True)),), "expression_type"),
    ((col("x", literal(1)), col("x", literal(2))), "duplicate_name"),
    ((col("bad/name", literal(1)),), "invalid_name"),
    ((col("x", literal(2**64)),), "integer_budget"),
])
def test_compiler_rejects_bad_programs_before_generation(columns, code: str) -> None:
    with pytest.raises(SynthesisError, match=code):
        compile_program(simple(*columns))


def test_temporal_dimension_reference_is_not_silently_sampled() -> None:
    a = Table(name="a", count=1, temporal=True, columns=(col("x", literal(1)),))
    b = Table(name="b", count=1, columns=(col("x", ref("other.x")),), relations=(Relation(name="other", table="a"),))
    with pytest.raises(SynthesisError, match="temporal_relation"):
        compile_program(Program(namespace="bad", tables=(a, b)))


@pytest.mark.parametrize("limits,code", [
    (Limits(max_rows=1), "row_budget"),
    (Limits(max_work=1), "work_budget"),
    (Limits(max_depth=1), "expression_budget"),
    (Limits(max_expression_nodes=1), "expression_budget"),
    (Limits(max_dimension_rows=1), "dimension_budget"),
    (Limits(max_dimension_cells=1), "dimension_budget"),
    (Limits(max_tables=1), "table_budget"),
    (Limits(max_columns=1), "column_budget"),
    (Limits(max_lag=1), "lag_budget"),
])
def test_resource_limits_are_operator_owned(limits: Limits, code: str) -> None:
    with pytest.raises(SynthesisError, match=code):
        Simulator(retail(), limits=limits)


def test_short_circuit_prevents_inactive_division_by_zero() -> None:
    program = simple(col("safe", expr("if", literal(True), literal(7), expr("div", literal(1), literal(0)))))
    assert all(r.values()["safe"] == 7 for r in Simulator(program).rows())


@pytest.mark.parametrize("expression,code", [
    (expr("div", literal(1), literal(0)), "division_by_zero"),
    (expr("mul", literal(2**62), literal(4)), "integer_budget"),
    (uniform(2, 1, stream="bad"), "distribution_bounds"),
])
def test_runtime_refusal_names_the_actual_cell(expression: Expr, code: str) -> None:
    with pytest.raises(SynthesisError, match=code) as caught:
        list(Simulator(simple(col("x", expression))).rows())
    assert caught.value.finding.table == "series"
    assert caught.value.finding.column == "x"
    assert caught.value.finding.entity == caught.value.finding.tick == 0


@pytest.mark.parametrize("shards", [1, 2, 3, 7, 16])
def test_sharded_reduction_is_byte_identical(tmp_path: Path, shards: int) -> None:
    simulator = Simulator(retail(stores=2, products=3, ticks=7))
    export(simulator, tmp_path / "whole")
    paths = []
    for index in range(shards):
        path = tmp_path / f"part{index}"
        export(simulator, path, shard_index=index, shard_count=shards)
        paths.append(path)
    merge_exports(reversed(paths), tmp_path / "merged")
    for name in ("recipe.json", "records.jsonl", "manifest.json"):
        assert (tmp_path / "whole" / name).read_bytes() == (tmp_path / "merged" / name).read_bytes()
    assert verify_export(tmp_path / "merged").rows == simulator.compiled.rows


def test_missing_and_duplicate_shards_are_refused(tmp_path: Path) -> None:
    sim = Simulator(simple(col("x", literal(1))))
    export(sim, tmp_path / "a", shard_count=2)
    for paths in ([tmp_path / "a"], [tmp_path / "a", tmp_path / "a"]):
        with pytest.raises(SynthesisError, match="shard_coverage"):
            merge_exports(paths, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_resume_verifies_recipe_and_records(tmp_path: Path) -> None:
    sim = Simulator(simple(col("x", literal(1))))
    path = tmp_path / "corpus"
    first = export(sim, path)
    assert export(sim, path, resume=True) == first
    with pytest.raises(SynthesisError, match="resume_mismatch"):
        export(Simulator(sim.program, seed=2), path, resume=True)
    with pytest.raises(SynthesisError, match="destination_exists"):
        export(sim, path)


def test_recomputed_checksums_cannot_hide_fabricated_records(tmp_path: Path) -> None:
    sim = Simulator(simple(col("x", literal(1))))
    path = tmp_path / "corpus"
    export(sim, path)
    records = list(iter_export(path))
    record = records[0]
    records[0] = record.model_copy(update={"cells": (record.cells[0].model_copy(update={"value": 9}),)})
    data = b"".join(canonical(r.model_dump(mode="json")) for r in records)
    (path / "records.jsonl").write_bytes(data)
    manifest = json.loads((path / "manifest.json").read_bytes())
    manifest["records_sha256"] = sha256(data).hexdigest()
    (path / "manifest.json").write_bytes(canonical(manifest))
    with pytest.raises(SynthesisError, match="replay_mismatch"):
        verify_export(path)


def test_failed_constraints_publish_nothing(tmp_path: Path) -> None:
    program = simple(col("x", literal(1)), constraints=(Constraint(name="not_true", predicate=literal(False)),))
    with pytest.raises(SynthesisError, match="constraint_failed"):
        export(Simulator(program), tmp_path / "bad")
    assert list(tmp_path.iterdir()) == []


def test_different_python_hash_seeds_do_not_change_output() -> None:
    code = "from worldloom.synthesis import Simulator,retail; from worldloom.synthesis.compiler import canonical; import sys; [sys.stdout.buffer.write(canonical(r.model_dump(mode='json'))) for r in Simulator(retail(stores=1,products=2,ticks=3)).rows()]"
    outputs = [subprocess.check_output([sys.executable, "-c", code], env={**os.environ, "PYTHONHASHSEED": seed}) for seed in ("1", "999")]
    assert outputs[0] == outputs[1]


def test_simulator_configuration_cannot_be_mutated_after_compilation() -> None:
    from dataclasses import FrozenInstanceError

    sim = Simulator(retail(stores=1, products=2, ticks=3))
    with pytest.raises(FrozenInstanceError):
        sim.seed = 99
    with pytest.raises(TypeError):
        sim._parameters["initial_stock"] = 0
