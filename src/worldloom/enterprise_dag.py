"""A bounded, executable grammar for enterprise connector trajectories.

Nodes are composable values, not a shape label. References are explicit paths
into prior results; predicates and maps may only read their ancestors. The
catalogue is a small versioned set of examples of this public grammar.
"""

from __future__ import annotations

import json
from collections.abc import Iterable, Mapping
from functools import lru_cache
from importlib.resources import files
from typing import Any, Literal

from pydantic import Field, model_validator

from .models import Model

GRAMMAR_VERSION: Literal["enterprise-dag@1"] = "enterprise-dag@1"


class ResultReference(Model):
    node: str
    path: tuple[str, ...] = ()
    select: Literal["first", "all", "count", "item"] = "first"
    encoding: Literal["value", "json"] = "value"

    @model_validator(mode="after")
    def _path(self) -> ResultReference:
        if self.select == "count" and self.path:
            raise ValueError("count references cannot carry a field path")
        if any(not part for part in self.path):
            raise ValueError("reference paths cannot contain empty components")
        return self


class ResultCondition(Model):
    reference: ResultReference
    operator: Literal["eq", "ne", "gt", "gte", "lt", "lte"]
    value: Any


class ResultIteration(Model):
    node: str
    limit: int = Field(default=100, ge=1, le=1000)


class EnterpriseDagNode(Model):
    id: str = Field(min_length=1)
    kind: Literal["read", "search", "transform", "write", "verify"]
    connector: str
    entity: str
    operation: str
    depends_on: tuple[str, ...] = ()
    source_index: int | None = Field(default=None, ge=0)
    arguments: dict[str, Any] = Field(default_factory=dict)
    bindings: dict[str, ResultReference] = Field(default_factory=dict)
    condition: ResultCondition | None = None
    for_each: ResultIteration | None = None
    transform: Literal["collect", "project", "unique"] | None = None

    @model_validator(mode="after")
    def _contract(self) -> EnterpriseDagNode:
        admitted = {
            "read": {"read", "get", "extract", "download"},
            "search": {"search"},
            "verify": {"read", "get", "download", "readback", "cross_system"},
            "write": {"create", "draft", "send", "post", "upload", "update", "patch", "upsert", "reply", "forward", "comment", "transition", "delete", "move"},
            "transform": {"collect", "project", "unique"},
        }
        if self.operation not in admitted[self.kind]:
            raise ValueError(f"{self.id}: {self.kind} cannot execute {self.operation!r}")
        if self.kind == "transform":
            if self.connector != "model" or self.transform is None:
                raise ValueError(f"{self.id}: a local transform needs model and an explicit transform")
            if self.for_each is not None:
                raise ValueError(f"{self.id}: local transforms consume whole resultsets")
        elif self.connector == "model" or self.transform is not None:
            raise ValueError(f"{self.id}: only transform nodes may use model")
        if self.source_index is not None and self.kind not in {"read", "search"}:
            raise ValueError(f"{self.id}: only evidence reads have a source_index")
        if self.for_each and self.kind not in {"read", "write", "verify"}:
            raise ValueError(f"{self.id}: for_each requires one record operation")
        if len(set(self.depends_on)) != len(self.depends_on):
            raise ValueError(f"{self.id}: duplicate dependency")
        for key, ref in self.bindings.items():
            if key in self.arguments:
                raise ValueError(f"{self.id}: argument {key!r} is both literal and bound")
            if ref.select == "item" and (self.for_each is None or ref.node != self.for_each.node):
                raise ValueError(f"{self.id}: item binding requires its for_each resultset")
        if self.condition is not None and self.condition.reference.select == "item":
            raise ValueError(f"{self.id}: condition cannot inspect an item before iteration")
        return self


class EnterpriseDag(Model):
    version: Literal["enterprise-dag@1"] = GRAMMAR_VERSION
    nodes: tuple[EnterpriseDagNode, ...]
    max_calls: int = Field(default=1000, ge=1, le=10000)
    max_result_items: int = Field(default=10000, ge=1, le=10000)

    @model_validator(mode="after")
    def _closed(self) -> EnterpriseDag:
        if not self.nodes or len(self.nodes) > 128:
            raise ValueError("DAG requires between 1 and 128 nodes")
        ancestors: dict[str, set[str]] = {}
        for node in self.nodes:
            if node.id in ancestors:
                raise ValueError(f"duplicate DAG node {node.id!r}")
            missing = set(node.depends_on) - ancestors.keys()
            if missing:
                raise ValueError(f"{node.id}: unresolved or cyclic dependencies {sorted(missing)}")
            reachable = set(node.depends_on)
            for parent in node.depends_on:
                reachable.update(ancestors[parent])
            refs = list(node.bindings.values())
            if node.condition is not None:
                refs.append(node.condition.reference)
            if node.for_each is not None:
                refs.append(ResultReference(node=node.for_each.node))
            bad = sorted({ref.node for ref in refs} - reachable)
            if bad:
                raise ValueError(f"{node.id}: result references are not ancestors: {bad}")
            if node.kind == "transform" and not node.depends_on:
                raise ValueError(f"{node.id}: transform requires inputs")
            ancestors[node.id] = reachable
        return self


def resolve_reference(
    reference: ResultReference,
    outputs: Mapping[str, list[Any]],
    *,
    item: Any = None,
) -> Any:
    """Resolve without guessing an absent node, empty result, or missing field."""
    if reference.node not in outputs:
        raise ValueError(f"missing_result:{reference.node}")
    values = outputs[reference.node]
    if reference.select == "count":
        if reference.path:
            raise ValueError("count references cannot carry a field path")
        return json.dumps(len(values)) if reference.encoding == "json" else len(values)
    if reference.select == "item":
        if item is None:
            raise ValueError(f"missing_item:{reference.node}")
        selected = [item]
    elif reference.select == "first":
        if not values:
            raise ValueError(f"empty_result:{reference.node}")
        selected = values[:1]
    else:
        selected = values
    result = []
    for value in selected:
        for key in reference.path:
            if not isinstance(value, Mapping) or key not in value:
                raise ValueError(f"missing_result_field:{reference.node}:{'.'.join(reference.path)}")
            value = value[key]
        result.append(value)
    selected_value = result if reference.select == "all" else result[0]
    return json.dumps(selected_value, sort_keys=True, separators=(",", ":")) if reference.encoding == "json" else selected_value


def condition_matches(condition: ResultCondition, outputs: Mapping[str, list[Any]]) -> bool:
    value = resolve_reference(condition.reference, outputs)
    other = condition.value
    if condition.operator == "eq":
        return bool(value == other)
    if condition.operator == "ne":
        return bool(value != other)
    try:
        if condition.operator == "gt":
            return bool(value > other)
        if condition.operator == "gte":
            return bool(value >= other)
        if condition.operator == "lt":
            return bool(value < other)
        return bool(value <= other)
    except TypeError as error:
        raise ValueError(f"incomparable_condition:{condition.reference.node}") from error


def transform_results(node: EnterpriseDagNode, outputs: Mapping[str, list[Any]], *, max_items: int = 10000) -> list[Any]:
    if sum(len(outputs.get(parent, ())) for parent in node.depends_on) > max_items:
        raise ValueError(f"result_budget_exceeded:{node.id}:{max_items}")
    values = [value for parent in node.depends_on for value in outputs.get(parent, ())]
    if node.transform == "project":
        fields = tuple(node.arguments.get("fields", ()))
        if not fields:
            raise ValueError(f"{node.id}: project requires fields")
        projected = []
        for value in values:
            if not isinstance(value, Mapping) or any(field not in value for field in fields):
                raise ValueError(f"{node.id}: missing projection field")
            projected.append({field: value[field] for field in fields})
        return projected
    if node.transform == "unique":
        seen: set[str] = set()
        unique = []
        for value in values:
            token = json.dumps(value, sort_keys=True, separators=(",", ":"))
            if token not in seen:
                seen.add(token)
                unique.append(value)
        return unique
    return values


def dag_metrics(dag: EnterpriseDag) -> dict[str, int]:
    levels: dict[str, int] = {}
    widths: dict[int, int] = {}
    for node in dag.nodes:
        level = 1 + max((levels[parent] for parent in node.depends_on), default=0)
        levels[node.id] = level
        widths[level] = widths.get(level, 0) + 1
    return {
        "nodes": len(dag.nodes), "depth": max(levels.values()),
        "width": max(widths.values()),
        "connectors": len({node.connector for node in dag.nodes if node.connector != "model"}),
        "conditional": sum(node.condition is not None for node in dag.nodes),
        "for_each": sum(node.for_each is not None for node in dag.nodes),
    }


@lru_cache(maxsize=1)
def _shape_data() -> dict[str, dict[str, Any]]:
    payload = json.loads(files("worldloom").joinpath("_data/evals/enterprise_dag_shapes_v1.json").read_text())
    return dict(payload["shapes"])


def shape_catalogue() -> dict[str, dict[str, Any]]:
    return {key: dict(value) for key, value in _shape_data().items()}


def shape_coverage(queries: Iterable[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for query in queries:
        shape = query.dimensions.get("dag_shape", "legacy")
        counts[shape] = counts.get(shape, 0) + 1
    return dict(sorted(counts.items()))


__all__ = ["GRAMMAR_VERSION", "EnterpriseDag", "EnterpriseDagNode", "ResultReference", "ResultCondition", "ResultIteration", "dag_metrics", "shape_catalogue", "shape_coverage"]
