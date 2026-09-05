"""Compile a causal program before generating its first record.

Same-tick edges form a DAG. A lag reads a completed earlier tick; it is not a
same-tick cycle. Relations target static dimensions so independent entity
trajectories can be sharded without an all-to-all mutable simulation.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256

from .models import (
    Column,
    Expr,
    Intervention,
    Limits,
    Parameter,
    Program,
    SynthesisError,
    Table,
)

_NAME = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,63}$")
_ARITY = {"literal": 0, "ref": 0, "param": 0, "lag": 1, "uniform": 2,
          "sub": 2, "div": 2, "mod": 2, "eq": 2, "lt": 2, "le": 2,
          "not": 1, "if": 3}


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8")


def digest(value: object) -> str:
    return sha256(canonical(value)).hexdigest()


def ordered(nodes: dict[str, set[str]], label: str) -> tuple[str, ...]:
    pending = {name: set(deps) for name, deps in nodes.items()}
    result: list[str] = []
    while pending:
        ready = sorted(name for name, deps in pending.items() if not deps)
        if not ready:
            raise SynthesisError("cycle", f"{label}: {sorted(pending)}")
        result.extend(ready)
        for name in ready:
            del pending[name]
        for deps in pending.values():
            deps.difference_update(ready)
    return tuple(result)


def _names(names: tuple[str, ...], label: str) -> None:
    if len(names) != len(set(names)):
        raise SynthesisError("duplicate_name", label)
    if any(not _NAME.fullmatch(name) for name in names):
        raise SynthesisError("invalid_name", label)


@dataclass(frozen=True)
class CompiledTable:
    table: Table
    columns: tuple[Column, ...]
    max_lag: int


@dataclass(frozen=True)
class CompiledProgram:
    program: Program
    tables: tuple[CompiledTable, ...]
    limits: Limits
    rows: int
    work: int
    program_digest: str


def compile_program(program: Program, *, limits: Limits | None = None) -> CompiledProgram:
    limits = limits or Limits()
    _names((program.namespace,), "namespace")
    _names(tuple(t.name for t in program.tables), "tables")
    _names(tuple(p.name for p in program.parameters), "parameters")
    if not program.tables or len(program.tables) > limits.max_tables:
        raise SynthesisError("table_budget", "empty or excessive table collection")
    tables = {table.name: table for table in program.tables}
    parameters = {p.name: p for p in program.parameters}
    for parameter in program.parameters:
        if not parameter.minimum <= parameter.value <= parameter.maximum:
            raise SynthesisError("parameter_bounds", parameter.name)
        if max(abs(parameter.minimum), abs(parameter.maximum)) > limits.max_abs_integer:
            raise SynthesisError("integer_budget", parameter.name)
    rows = sum(t.count * (program.ticks if t.temporal else 1) for t in program.tables)
    if rows > limits.max_rows:
        raise SynthesisError("row_budget", f"{rows} exceeds {limits.max_rows}")
    if sum(t.count for t in program.tables if not t.temporal) > limits.max_dimension_rows:
        raise SynthesisError("dimension_budget", "static dimension cache exceeds limit")
    if sum(t.count * len(t.columns) for t in program.tables if not t.temporal) > limits.max_dimension_cells:
        raise SynthesisError("dimension_budget", "static dimension cell cache exceeds limit")
    dependencies: dict[str, set[str]] = {}
    compiled: dict[str, CompiledTable] = {}
    total_nodes = 0
    work = 0
    for table in program.tables:
        result, dependencies[table.name], table_nodes = _compile_table(table, tables, parameters, limits, total_nodes)
        compiled[table.name] = result
        total_nodes += table_nodes
        work += table_nodes * table.count * (program.ticks if table.temporal else 1)
    if work > limits.max_work:
        raise SynthesisError("work_budget", f"{work} exceeds {limits.max_work}")
    table_order = ordered(dependencies, "table relationships")
    return CompiledProgram(program, tuple(compiled[n] for n in table_order), limits,
                           rows, work, digest(program.model_dump(mode="json")))


def _compile_table(table: Table, tables: dict[str, Table], parameters: dict[str, Parameter],
                   limits: Limits, previous_nodes: int) -> tuple[CompiledTable, set[str], int]:
    _names(tuple(c.name for c in table.columns) + tuple(r.name for r in table.relations), table.name)
    _names(tuple(c.name for c in table.constraints), f"{table.name} constraints")
    if not table.columns or len(table.columns) > limits.max_columns:
        raise SynthesisError("column_budget", table.name)
    columns = {c.name: c for c in table.columns}
    relations = {r.name: r for r in table.relations}
    dependencies: set[str] = set()
    for relation in table.relations:
        target = tables.get(relation.table)
        if target is None:
            raise SynthesisError("unknown_table", relation.table, table=table.name)
        if target.temporal:
            raise SynthesisError("temporal_relation", "relations must target static dimensions", table=table.name)
        dependencies.add(relation.table)
    edges: dict[str, set[str]] = {name: set() for name in columns}
    table_nodes = 0
    max_lag = 0

    def walk(node: Expr, owner: str | None, depth: int = 1) -> None:
        nonlocal table_nodes, max_lag
        table_nodes += 1
        if depth > limits.max_depth or table_nodes + previous_nodes > limits.max_expression_nodes:
            raise SynthesisError("expression_budget", table.name)
        arity = _ARITY.get(node.op)
        if (arity is not None and len(node.args) != arity) or (arity is None and len(node.args) < 2):
            raise SynthesisError("arity", node.op, table=table.name, column=owner)
        if node.op != "literal" and node.value is not None:
            raise SynthesisError("unused_attribute", f"{node.op}.value")
        if node.op not in {"ref", "param", "lag"} and node.name is not None:
            raise SynthesisError("unused_attribute", f"{node.op}.name")
        if node.op != "uniform" and (node.stream is not None or node.scope != "cell"):
            raise SynthesisError("unused_attribute", f"{node.op}.stream/scope")
        if node.op != "lag" and node.steps != 1:
            raise SynthesisError("unused_attribute", f"{node.op}.steps")
        if node.op == "literal":
            if node.value is None:
                raise SynthesisError("missing_literal", table.name)
            if type(node.value) is int and abs(node.value) > limits.max_abs_integer:
                raise SynthesisError("integer_budget", table.name)
            if isinstance(node.value, str) and len(node.value) > 4096:
                raise SynthesisError("string_budget", table.name)
        elif node.op == "param":
            if node.name not in parameters:
                raise SynthesisError("unknown_parameter", str(node.name), table=table.name)
        elif node.op == "uniform":
            if not node.stream or not _NAME.fullmatch(node.stream):
                raise SynthesisError("noise_stream", "uniform needs an explicit stable stream name")
        elif node.op == "ref":
            name = node.name or ""
            if name in {"_entity", "_tick"}:
                pass
            elif "." in name:
                relation_name, field = name.split(".", 1)
                relation = relations.get(relation_name)
                if relation is None or field not in {c.name for c in tables[relation.table].columns}:
                    raise SynthesisError("unknown_reference", name, table=table.name)
            elif name not in columns:
                raise SynthesisError("unknown_reference", name, table=table.name)
            elif owner is not None:
                edges[owner].add(name)
        elif node.op == "lag":
            if not table.temporal or node.name not in columns:
                raise SynthesisError("invalid_lag", str(node.name), table=table.name)
            if node.steps > limits.max_lag:
                raise SynthesisError("lag_budget", str(node.steps), table=table.name)
            max_lag = max(max_lag, node.steps)
        for arg in node.args:
            walk(arg, owner, depth + 1)

    for column in table.columns:
        if column.kind != "int" and (column.minimum is not None or column.maximum is not None):
            raise SynthesisError("column_bounds", column.name)
        if column.minimum is not None and column.maximum is not None and column.minimum > column.maximum:
            raise SynthesisError("column_bounds", column.name)
        walk(column.expression, column.name)
    for constraint in table.constraints:
        walk(constraint.predicate, None)
    def infer(node: Expr) -> str:
        kinds = tuple(infer(arg) for arg in node.args)
        if node.op == "literal":
            return {int: "int", bool: "bool", str: "str"}[type(node.value)]
        if node.op == "param":
            return "int"
        if node.op == "ref":
            name = node.name or ""
            if name in {"_entity", "_tick"}:
                return "int"
            if "." in name:
                relation_name, field = name.split(".", 1)
                target = tables[relations[relation_name].table]
                return next(c.kind for c in target.columns if c.name == field)
            return columns[name].kind
        if node.op == "lag":
            expected = columns[node.name or ""].kind
            if kinds != (expected,):
                raise SynthesisError("expression_type", "lag initial value differs from lagged column", table=table.name)
            return expected
        if node.op == "if":
            if kinds[0] != "bool" or kinds[1] != kinds[2]:
                raise SynthesisError("expression_type", "if requires a boolean condition and matching branches", table=table.name)
            return kinds[1]
        if node.op == "eq":
            if kinds[0] != kinds[1]:
                raise SynthesisError("expression_type", "equality operands must share a type", table=table.name)
            return "bool"
        expected = "bool" if node.op in {"and", "or", "not"} else "int"
        if any(kind != expected for kind in kinds):
            raise SynthesisError("expression_type", f"{node.op} requires {expected} operands", table=table.name)
        return "bool" if node.op in {"and", "or", "not", "lt", "le"} else "int"

    for column in table.columns:
        if infer(column.expression) != column.kind:
            raise SynthesisError("expression_type", f"{column.name} expression does not produce {column.kind}", table=table.name)
    for constraint in table.constraints:
        if infer(constraint.predicate) != "bool":
            raise SynthesisError("expression_type", f"constraint {constraint.name} must produce bool", table=table.name)
    column_order = ordered(edges, f"columns in {table.name}")
    return CompiledTable(table, tuple(columns[n] for n in column_order), max_lag), dependencies, table_nodes


def check_value(column: Column, value: int | bool | str, limits: Limits) -> None:
    expected = {"int": int, "bool": bool, "str": str}[column.kind]
    if type(value) is not expected:
        raise SynthesisError("value_type", f"{column.name} requires {column.kind}")
    if type(value) is int:
        if abs(value) > limits.max_abs_integer:
            raise SynthesisError("integer_budget", column.name)
        if column.minimum is not None and value < column.minimum:
            raise SynthesisError("column_bounds", f"{column.name} < {column.minimum}")
        if column.maximum is not None and value > column.maximum:
            raise SynthesisError("column_bounds", f"{column.name} > {column.maximum}")
    if isinstance(value, str) and len(value) > 4096:
        raise SynthesisError("string_budget", column.name)


def validate_interventions(compiled: CompiledProgram, interventions: tuple[Intervention, ...]) -> None:
    tables = {t.table.name: t.table for t in compiled.tables}
    if len(interventions) > compiled.limits.max_interventions:
        raise SynthesisError("intervention_budget", "too many interventions")
    for index, intervention in enumerate(interventions):
        table = tables.get(intervention.table)
        column = next((c for c in table.columns if c.name == intervention.column), None) if table else None
        if table is None or column is None:
            raise SynthesisError("unknown_intervention", f"{intervention.table}.{intervention.column}")
        if not column.intervenable:
            raise SynthesisError("protected_column", intervention.column)
        check_value(column, intervention.value, compiled.limits)
        ticks = compiled.program.ticks if table.temporal else 1
        stop = intervention.stop if intervention.stop is not None else ticks
        if not intervention.start < stop <= ticks:
            raise SynthesisError("intervention_window", intervention.column)
        if intervention.entities is not None and (
            not intervention.entities or len(set(intervention.entities)) != len(intervention.entities)
            or any(e < 0 or e >= table.count for e in intervention.entities)
        ):
            raise SynthesisError("intervention_entities", intervention.column)
        for other in interventions[:index]:
            if (other.table, other.column) != (intervention.table, intervention.column):
                continue
            overlaps_time = max(other.start, intervention.start) < min(other.stop or ticks, stop)
            overlaps_entities = (other.entities is None or intervention.entities is None
                                 or bool(set(other.entities) & set(intervention.entities)))
            if overlaps_time and overlaps_entities:
                raise SynthesisError("overlapping_interventions", intervention.column)
