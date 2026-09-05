"""Closed, versioned programs for relational, temporal synthetic records.

Programs contain data, never Python. Limits belong to the caller, not the
program's author. Money uses integer minor units; no binary-float arithmetic
or model-owned state enters a trajectory.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, StrictBool, StrictInt, StrictStr

from ..models import Model

Scalar = StrictInt | StrictBool | StrictStr
Name = str
Operation = Literal[
    "literal", "ref", "param", "lag", "uniform", "add", "sub", "mul",
    "div", "mod", "min", "max", "eq", "lt", "le", "and", "or", "not", "if",
]


class Expr(Model):
    op: Operation
    args: tuple[Expr, ...] = ()
    value: Scalar | None = None
    name: str | None = None
    steps: int = Field(default=1, ge=1, le=256, strict=True)
    scope: Literal["cell", "entity", "tick", "world"] = "cell"
    stream: str | None = None


class Parameter(Model):
    name: Name
    value: StrictInt
    minimum: StrictInt
    maximum: StrictInt
    mutable: StrictBool = False


class Column(Model):
    name: Name
    expression: Expr
    kind: Literal["int", "bool", "str"] = "int"
    minimum: StrictInt | None = None
    maximum: StrictInt | None = None
    unit: str | None = None
    intervenable: StrictBool = False


class Relation(Model):
    name: Name
    table: Name
    # Stable entity selection, including Cartesian products: product uses
    # stride=1, store uses stride=number_of_products. No random dangling FK.
    stride: int = Field(default=1, ge=1, strict=True)
    offset: int = Field(default=0, ge=0, strict=True)


class Constraint(Model):
    name: Name
    predicate: Expr


class Table(Model):
    name: Name
    count: int = Field(ge=1, strict=True)
    temporal: StrictBool = False
    columns: tuple[Column, ...]
    relations: tuple[Relation, ...] = ()
    constraints: tuple[Constraint, ...] = ()


class Program(Model):
    schema_version: Literal["worldloom.synthesis/v1"] = "worldloom.synthesis/v1"
    namespace: Name
    ticks: int = Field(default=1, ge=1, strict=True)
    parameters: tuple[Parameter, ...] = ()
    tables: tuple[Table, ...]


class Limits(Model):
    max_rows: int = Field(default=1_000_000, ge=1, strict=True)
    max_work: int = Field(default=100_000_000, ge=1, strict=True)
    max_dimension_rows: int = Field(default=100_000, ge=1, strict=True)
    max_dimension_cells: int = Field(default=1_000_000, ge=1, strict=True)
    max_evaluation_work: int = Field(default=500_000_000, ge=1, strict=True)
    max_interventions: int = Field(default=128, ge=1, strict=True)
    max_expression_nodes: int = Field(default=20_000, ge=1, strict=True)
    max_depth: int = Field(default=24, ge=1, strict=True)
    max_tables: int = Field(default=32, ge=1, strict=True)
    max_columns: int = Field(default=128, ge=1, strict=True)
    max_lag: int = Field(default=256, ge=1, le=256, strict=True)
    max_abs_integer: int = Field(default=2**63 - 1, ge=1, strict=True)


class Intervention(Model):
    table: Name
    column: Name
    value: Scalar
    start: int = Field(default=0, ge=0, strict=True)
    stop: int | None = Field(default=None, ge=1, strict=True)
    # None is the entire population, not an empty set. Selectors are explicit
    # and disjoint; a later intervention may never silently override an earlier one.
    entities: tuple[StrictInt, ...] | None = None


class Cell(Model):
    name: str
    value: Scalar


class ForeignKey(Model):
    relation: str
    table: str
    entity: StrictInt
    entity_id: str


class Row(Model):
    id: str
    entity_id: str
    table: str
    entity: StrictInt
    tick: StrictInt
    cells: tuple[Cell, ...]
    links: tuple[ForeignKey, ...] = ()

    def values(self) -> dict[str, int | bool | str]:
        return {cell.name: cell.value for cell in self.cells}


class Finding(Model):
    code: str
    message: str
    table: str | None = None
    column: str | None = None
    entity: int | None = None
    tick: int | None = None


class SynthesisError(ValueError):
    def __init__(self, code: str, message: str, *, table: str | None = None,
                 column: str | None = None, entity: int | None = None,
                 tick: int | None = None) -> None:
        self.finding = Finding(code=code, message=message, table=table,
                               column=column, entity=entity, tick=tick)
        super().__init__(f"{code}: {message}")


def literal(value: int | bool | str) -> Expr:
    return Expr(op="literal", value=value)


def ref(name: str) -> Expr:
    return Expr(op="ref", name=name)


def param(name: str) -> Expr:
    return Expr(op="param", name=name)


def expr(op: Operation, *args: Expr) -> Expr:
    return Expr(op=op, args=args)


def lag(name: str, initial: int | bool | str | Expr, steps: int = 1) -> Expr:
    return Expr(op="lag", name=name, steps=steps,
                args=(initial if isinstance(initial, Expr) else literal(initial),))


def uniform(low: int | Expr, high: int | Expr, *, stream: str,
            scope: Literal["cell", "entity", "tick", "world"] = "cell") -> Expr:
    return Expr(op="uniform", stream=stream, scope=scope,
                args=tuple(a if isinstance(a, Expr) else literal(a) for a in (low, high)))
