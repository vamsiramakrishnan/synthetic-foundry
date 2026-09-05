"""Bounded-memory simulation with addressable exogenous noise.

An entity trajectory owns its lag ring. Dimensions are cached once per run;
no history of unrelated entities is retained. Sharding selects whole
trajectories rather than rows, so boundaries cannot reset state.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from types import MappingProxyType

from ..rng import Rng
from .compiler import (
    CompiledProgram,
    CompiledTable,
    canonical,
    check_value,
    compile_program,
    digest,
    validate_interventions,
)
from .models import (
    Cell,
    Expr,
    ForeignKey,
    Intervention,
    Limits,
    Program,
    Row,
    SynthesisError,
)

Value = int | bool | str


def entity_id(namespace: str, seed: int, table: str, entity: int) -> str:
    # The model digest intentionally is NOT identity. An intervention changes
    # a mechanism, not which entity we are comparing in the paired experiment.
    return "SYN-" + digest(["entity/v1", namespace, seed, table, entity])[:32].upper()


def _integer(value: Value) -> int:
    if type(value) is not int:
        raise SynthesisError("operand_type", "integer operand required")
    return value


def _boolean(value: Value) -> bool:
    if type(value) is not bool:
        raise SynthesisError("operand_type", "boolean operand required")
    return value


@dataclass
class _Context:
    table: str
    entity: int
    tick: int
    values: dict[str, Value]
    dimensions: dict[str, dict[str, Value]]
    history: deque[dict[str, Value]]


@dataclass(frozen=True, init=False, eq=False)
class Simulator:
    """A compiled program, seed and explicit do-interventions.

    This is a structural simulator, not a fitted statistical model. A
    counterfactual is valid under the declared mechanisms, not an empirical
    claim about a real retailer or bank.
    """

    compiled: CompiledProgram
    seed: int
    interventions: tuple[Intervention, ...]
    _selectors: tuple[tuple[Intervention, frozenset[int] | None], ...]
    _parameters: Mapping[str, int]
    _root: Rng

    def __init__(self, program: Program, *, seed: int = 8128,
                 interventions: tuple[Intervention, ...] = (),
                 limits: Limits | None = None) -> None:
        if type(seed) is not int:
            raise SynthesisError("seed_type", "seed must be an integer")
        object.__setattr__(self, "compiled", compile_program(program, limits=limits))
        validate_interventions(self.compiled, interventions)
        object.__setattr__(self, "seed", seed)
        object.__setattr__(self, "interventions", tuple(sorted(interventions, key=lambda i: canonical(i.model_dump(mode="json")))))
        object.__setattr__(self, "_selectors", tuple((i, frozenset(i.entities) if i.entities is not None else None) for i in self.interventions))
        object.__setattr__(self, "_parameters", MappingProxyType({p.name: p.value for p in program.parameters}))
        object.__setattr__(self, "_root", Rng(seed))

    @property
    def program(self) -> Program:
        return self.compiled.program

    @property
    def run_digest(self) -> str:
        return digest(self.recipe())

    def recipe(self) -> dict[str, object]:
        return {"engine": "worldloom.synthesis/v1", "seed": self.seed,
                "program": self.program.model_dump(mode="json"),
                "interventions": [i.model_dump(mode="json") for i in self.interventions]}

    def _eval(self, node: Expr, context: _Context) -> Value:
        if node.op == "literal":
            assert node.value is not None  # the compiler checks every node
            return node.value
        if node.op == "param":
            return self._parameters[node.name or ""]
        if node.op == "ref":
            name = node.name or ""
            if name == "_entity":
                return context.entity
            if name == "_tick":
                return context.tick
            if "." in name:
                relation, field = name.split(".", 1)
                return context.dimensions[relation][field]
            return context.values[name]
        if node.op == "lag":
            if context.tick < node.steps:
                return self._eval(node.args[0], context)
            return context.history[-node.steps][node.name or ""]
        if node.op == "if":
            return self._eval(node.args[1] if _boolean(self._eval(node.args[0], context)) else node.args[2], context)
        if node.op == "and":
            return all(_boolean(self._eval(arg, context)) for arg in node.args)
        if node.op == "or":
            return any(_boolean(self._eval(arg, context)) for arg in node.args)
        if node.op == "not":
            return not _boolean(self._eval(node.args[0], context))
        args = [self._eval(arg, context) for arg in node.args]
        if node.op == "eq":
            return type(args[0]) is type(args[1]) and args[0] == args[1]
        numbers = [_integer(value) for value in args]
        if node.op == "lt":
            return numbers[0] < numbers[1]
        if node.op == "le":
            return numbers[0] <= numbers[1]
        if node.op == "uniform":
            low, high = numbers
            if low > high:
                raise SynthesisError("distribution_bounds", f"{low} > {high}")
            key: list[object] = ["noise/v1", self.program.namespace, node.scope, node.stream]
            if node.scope in {"cell", "entity"}:
                key.extend((context.table, context.entity))
            if node.scope in {"cell", "tick"}:
                key.append(context.tick)
            # One fixed-width draw, then inverse-CDF mapping. Changing a bound
            # never changes how many random values a downstream mechanism uses.
            draw = self._root.derive(canonical(key).decode("utf-8")).integer(0, 2**63 - 1)
            result = low + draw * (high - low + 1) // 2**63
        elif node.op == "add":
            result = sum(numbers)
        elif node.op == "sub":
            result = numbers[0] - numbers[1]
        elif node.op == "mul":
            result = 1
            for value in numbers:
                result *= value
                self._check_integer(result)
        elif node.op in {"div", "mod"}:
            if numbers[1] == 0:
                raise SynthesisError("division_by_zero", node.op)
            result = numbers[0] // numbers[1] if node.op == "div" else numbers[0] % numbers[1]
        elif node.op == "min":
            result = min(numbers)
        elif node.op == "max":
            result = max(numbers)
        else:
            raise SynthesisError("unknown_operation", node.op)
        self._check_integer(result)
        return result

    def _check_integer(self, value: int) -> None:
        if abs(value) > self.compiled.limits.max_abs_integer:
            raise SynthesisError("integer_budget", "intermediate result exceeds the integer limit")

    def _trajectory(self, table: CompiledTable, entity: int,
                    dimensions: dict[str, list[Row]]) -> Iterator[Row]:
        spec = table.table
        links: list[ForeignKey] = []
        related: dict[str, dict[str, Value]] = {}
        for relation in sorted(spec.relations, key=lambda r: r.name):
            candidates = dimensions[relation.table]
            target = candidates[(entity // relation.stride + relation.offset) % len(candidates)]
            links.append(ForeignKey(relation=relation.name, table=relation.table,
                                   entity=target.entity, entity_id=target.entity_id))
            related[relation.name] = target.values()
        history: deque[dict[str, Value]] = deque(maxlen=table.max_lag)
        own_id = entity_id(self.program.namespace, self.seed, spec.name, entity)
        applicable = tuple(i for i, entities in self._selectors if i.table == spec.name
                           and (entities is None or entity in entities))
        for tick in range(self.program.ticks if spec.temporal else 1):
            values: dict[str, Value] = {}
            context = _Context(spec.name, entity, tick, values, related, history)
            active = {i.column: i.value for i in applicable if i.start <= tick
                      and (i.stop is None or tick < i.stop)}
            column_name: str | None = None
            try:
                for column in table.columns:
                    column_name = column.name
                    value = active[column.name] if column.name in active else self._eval(column.expression, context)
                    check_value(column, value, self.compiled.limits)
                    values[column.name] = value
                column_name = None
                for constraint in sorted(spec.constraints, key=lambda c: c.name):
                    if not _boolean(self._eval(constraint.predicate, context)):
                        raise SynthesisError("constraint_failed", constraint.name)
            except SynthesisError as error:
                raise SynthesisError(error.finding.code, error.finding.message,
                                     table=spec.name, column=column_name,
                                     entity=entity, tick=tick) from error
            history.append(values)
            yield Row(id="ROW-" + digest([own_id, tick])[:32].upper(), entity_id=own_id,
                      table=spec.name, entity=entity, tick=tick,
                      cells=tuple(Cell(name=n, value=v) for n, v in sorted(values.items())), links=tuple(links))

    def rows(self, *, shard_index: int = 0, shard_count: int = 1) -> Iterator[Row]:
        if (type(shard_index) is not int or type(shard_count) is not int
                or shard_count < 1 or not 0 <= shard_index < shard_count):
            raise SynthesisError("invalid_shard", f"{shard_index}/{shard_count}")
        # Dimensions are dependency-ordered internally. Emission is alphabetical
        # so declaration order and process completion order cannot affect bytes.
        dimensions: dict[str, list[Row]] = {}
        for table in self.compiled.tables:
            if not table.table.temporal:
                dimensions[table.table.name] = [
                    row for entity in range(table.table.count)
                    for row in self._trajectory(table, entity, dimensions)
                ]
        for table in sorted(self.compiled.tables, key=lambda t: t.table.name):
            if not table.table.temporal:
                yield from dimensions[table.table.name][shard_index::shard_count]
            else:
                for entity in range(shard_index, table.table.count, shard_count):
                    yield from self._trajectory(table, entity, dimensions)

    def counterfactual(self, *interventions: Intervention) -> Simulator:
        return Simulator(self.program, seed=self.seed,
                         interventions=self.interventions + interventions,
                         limits=self.compiled.limits)


@dataclass(frozen=True)
class Delta:
    row_id: str
    table: str
    entity: int
    tick: int
    column: str
    before: Value
    after: Value


def compare(left: Simulator, right: Simulator) -> Iterator[Delta]:
    """Paired cell differences; refuse accidentally comparing different worlds."""
    left_shape = sorted((t.name, t.count, t.temporal) for t in left.program.tables)
    right_shape = sorted((t.name, t.count, t.temporal) for t in right.program.tables)
    if (left.seed, left.program.namespace, left.program.ticks, left_shape) != (
        right.seed, right.program.namespace, right.program.ticks, right_shape
    ):
        raise SynthesisError("unpaired_worlds", "seed, namespace and population must match")
    for a, b in zip(left.rows(), right.rows(), strict=True):
        before, after = a.values(), b.values()
        if a.id != b.id or before.keys() != after.keys() or a.links != b.links:
            raise SynthesisError("unpaired_schema", "row identities, columns and relationships must match")
        for name in sorted(before):
            if type(before[name]) is not type(after[name]) or before[name] != after[name]:
                yield Delta(a.id, a.table, a.entity, a.tick, name, before[name], after[name])
