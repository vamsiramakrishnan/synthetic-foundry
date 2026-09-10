"""Content identity and connected-component split isolation for eval datasets.

Workflow names, topology labels and opaque IDs cannot buy another task. A
structural fingerprint deliberately coalesces equivalent labelled DAGs. It is
not a claim that arbitrary natural-language tasks are semantically equivalent.
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any

from ..enterprise_corpus import QueryFixture
from ..enterprise_queries import PlannedEnterpriseQuery
from ..providers import digest
from .dataset_contract import DatasetEntry, DatasetPlan


def program_identity(query: PlannedEnterpriseQuery) -> str:
    """Directed colour refinement, invariant to IDs and independent-node order.

    Hashing both incoming and outgoing structure preserves sharing and branch
    relationships. Any residual graph-hash collision conservatively merges
    families; it cannot manufacture apparent diversity.
    """
    nodes = {n["id"]: n for n in query.expected_dag}
    colours = {key: "node" for key in nodes}

    def normalize(value: Any, field: str = "") -> Any:
        if isinstance(value, dict):
            return {k: normalize(v, k) for k, v in sorted(value.items()) if k not in {"source_index"}}
        if isinstance(value, (list, tuple)):
            values = [normalize(v, field) for v in value]
            return sorted(values) if field == "depends_on" else values
        if isinstance(value, str) and field in {"node", "depends_on"} and value in colours:
            return colours[value]
        return value

    for _ in range(len(nodes) + 1):
        colours = {key: digest({
            "node": normalize({k: v for k, v in node.items() if k != "id"}),
            "children": sorted(colours[k] for k, n in nodes.items() if key in n.get("depends_on", ())),
        }) for key, node in nodes.items()}
    # Source selectors bind individual cases, while fields/formats/minima are
    # actual evidence obligations and remain part of the task contract.
    sources = sorted((s.model_dump(mode="json", exclude={"predicate"}) for s in query.generation.source_requirements), key=digest)
    return digest({"version": "dataset-task/v1", "graph": sorted(colours.values()),
                   "sources": sources, "mutation": query.generation.mutation.model_dump(mode="json"),
                   "artifact": query.generation.artifact.model_dump(mode="json") if query.generation.artifact else None})


def request_identity(text: str, *, company_name: str) -> str:
    # Generated record suffixes and changing company/number literals used to
    # make the same template count as fresh language on every seed.
    text = text.split(" Scope this work to these source records:", 1)[0]
    text = text.casefold().replace(company_name.casefold(), "<company>")
    text = re.sub(r"\b(?:syn-)?[a-f0-9]{16,}\b", "<id>", text)
    text = re.sub(r"\b\d+(?:[.,:-]\d+)*\b", "<number>", text)
    return digest(" ".join(re.findall(r"\w+|<[^>]+>", text)))


def evidence_identity(fixture: QueryFixture, company_id: str) -> tuple[str, ...]:
    # Shared facts/observations link different queries, including counterfactual
    # fault variants. Destination records never masquerade as source evidence.
    identities = [digest(["fact", company_id, value]) for value in fixture.expected_fact_ids]
    identities += [digest(["observation", value]) for value in fixture.expected_evidence_ids]
    identities += [digest(["source", company_id, connector, value])
                   for connector, values in sorted(fixture.input_record_ids.items()) for value in values]
    return tuple(sorted(set(identities)))


def assign_splits(entries: list[DatasetEntry], plan: DatasetPlan) -> tuple[dict[str, str], dict[str, int], int, int]:
    """Union all leakage relationships before assigning whole components.

    Largest-first placement reduces imbalance without breaking a component.
    Targets are weights, not exact row quotas. A giant component remains
    visible and can cause the nonempty-split gate to refuse the dataset.
    """
    parent = list(range(len(entries)))

    def root(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owners: dict[str, int] = {}
    for i, entry in enumerate(entries):
        keys = ["case:" + entry.case_id, *entry.evidence]
        if plan.split_by == "task":
            keys.append("task:" + entry.task_id)
        elif plan.split_by == "company":
            keys.append("company:" + entry.company_id)
        for key in keys:
            if key in owners:
                a, b = root(i), root(owners[key])
                parent[max(a, b)] = min(a, b)
            else:
                owners[key] = i
    groups: dict[int, list[DatasetEntry]] = {}
    for i, entry in enumerate(entries):
        groups.setdefault(root(i), []).append(entry)
    counts: Counter[str] = Counter({name: 0 for name in plan.split_weights})
    assignment: dict[str, str] = {}
    fixed = getattr(plan, "split_assignments", {})
    if fixed:
        for group in groups.values():
            keys = [digest([e.stratum, e.query_id]) for e in group]
            if any(key not in fixed for key in keys):
                raise ValueError("variant added a task outside the sealed split assignment")
            splits = {fixed[key] for key in keys}
            if len(splits) != 1:
                raise ValueError("variant evidence merged opposite sides of the sealed holdout")
            split = next(iter(splits))
            for entry in group:
                assignment[entry.id] = split
                counts[split] += 1
        return assignment, dict(sorted(counts.items())), len(groups), max((len(g) for g in groups.values()), default=0)
    total_weight = sum(plan.split_weights.values())
    ordered = sorted(groups.values(), key=lambda g: (-len(g), min(e.id for e in g)))
    for index, group in enumerate(ordered):
        empty = [key for key in plan.split_weights if not counts[key]]
        options = empty if len(ordered) - index <= len(empty) else list(plan.split_weights)
        split = min(options, key=lambda k: (
            counts[k] * total_weight - len(entries) * plan.split_weights[k], k))
        counts[split] += len(group)
        for entry in group:
            assignment[entry.id] = split
    return assignment, dict(sorted(counts.items())), len(groups), max((len(g) for g in ordered), default=0)


__all__ = ["program_identity", "request_identity", "evidence_identity", "assign_splits"]
