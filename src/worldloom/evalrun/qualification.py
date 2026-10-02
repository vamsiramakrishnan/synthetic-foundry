"""Sealed promotion experiments over independent evidence, with finite probe budgets.

Repeatedly consulting the same held-out set is adaptation, even when its
contents never enter a prompt. ``QualificationPolicy`` upgrades the existing
improvement loop: whole evidence components become independent sampling units,
and a candidate gets one fresh tranche of the held-out pool. A reservation is
written before either side runs. An interrupted experiment may finish, but a
different candidate, harness, grader or record snapshot cannot reuse its data.

The confidence allocation is Bonferroni across the bounded number of probes.
The intervals remain empirical cluster-bootstrap estimates, not an exact
finite-sample probability guarantee. The source digest is a provenance pin,
not a filesystem sandbox: callers still have to isolate the target process
from protected files when claiming an externally sealed benchmark.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import Field

from ..ids import content_key
from ..models import Model
from .contract import EvalCase
from .runner import case_set_digest
from .splits import declared_split, is_held_out

QUALIFICATION_SCHEMA = "worldloom.qualification/v1"


class QualificationPolicy(Model):
    """A predeclared experimental budget, sealed before the first proposal.

    ``unit_dimension`` explicitly groups correlated cases (for example an
    enterprise episode or source-world ID). Shared evidence always merges
    units, so a caller cannot label copies independent. Without it, explicit
    ``independent_unit`` lineage and evidence connectivity define the units.
    A source snapshot digest is required on every case.
    """

    trials: int = Field(default=3, ge=1)
    min_units: int = Field(default=5, ge=2)
    min_repeats: int = Field(default=2, ge=2)
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    unit_dimension: str | None = None

    @property
    def probe_confidence(self) -> float:
        return 1.0 - (1.0 - self.confidence) / self.trials


def with_record_provenance(cases: Sequence[EvalCase], records: Sequence[Any], *,
                           namespace: str | None = None,
                           independent_unit: str | None = None) -> tuple[EvalCase, ...]:
    """Attach the served snapshot digest without changing any executable row.

    Record IDs are local to a generated world. ``namespace`` is the stable
    source-world origin, shared by snapshots and counterfactual variants.
    Without one, reused IDs conservatively share an unscoped origin: changing
    a snapshot's bytes never establishes independent evidence.
    An existing contradictory pin is refused rather than overwritten.
    """
    from .proof import records_digest

    digest = records_digest(records)
    result = []
    for case in cases:
        existing = case.dimensions.get("source_digest")
        if existing is not None and existing != digest:
            raise ValueError(f"case {case.id}: source snapshot differs from its source_digest")
        dimensions = {**case.dimensions, "source_digest": digest}
        if namespace is not None:
            prior_namespace = dimensions.get("source_namespace")
            if prior_namespace is not None and prior_namespace != namespace:
                raise ValueError(f"case {case.id}: source namespace differs from its lineage")
            dimensions["source_namespace"] = namespace
        if independent_unit is not None:
            prior = dimensions.get("independent_unit")
            if prior is not None and prior != independent_unit:
                raise ValueError(f"case {case.id}: independent unit differs from its lineage")
            dimensions["independent_unit"] = independent_unit
        result.append(case.model_copy(update={"dimensions": dimensions}))
    return tuple(result)


def _address(namespace: str, *parts: str) -> str:
    return content_key("qualification-lineage", namespace, *parts)


def suite_digest(cases: Sequence[EvalCase]) -> str:
    """All measured contracts, requests and provenance, beyond executable rows."""
    return content_key("qualification-suite", *(json.dumps(case.model_dump(mode="json"), sort_keys=True)
                                                for case in sorted(cases, key=lambda case: case.id)))


def _claim(path: Path, document: Mapping[str, Any]) -> None:
    """Exclusive allocation: racing experiments never overwrite a seal or probe."""
    path.parent.mkdir(parents=True, exist_ok=True)
    canonical = json.loads(json.dumps(document, sort_keys=True))
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(json.dumps(canonical, indent=2, sort_keys=True) + "\n")
    except FileExistsError:
        if json.loads(path.read_text(encoding="utf-8")) != canonical:
            raise ValueError("sealed qualification allocation already belongs to a different experiment") from None


def lineage_tokens(case: EvalCase, *, unit_dimension: str | None = None) -> tuple[str, ...]:
    """Protected evidence and declared lineage, independent of the case's name."""
    if not case.dimensions.get("source_digest"):
        raise ValueError(f"case {case.id}: qualification needs source_digest; attach served records with "
                         "with_record_provenance()")
    source = case.dimensions.get("source_namespace") or "unscoped"
    tokens: set[str] = set()
    for dimension in ("independent_unit", "evidence_family", "episode_id", "family_id"):
        value = case.dimensions.get(dimension)
        if value:
            tokens.add(_address(source, dimension, value))
    if unit_dimension is not None:
        value = case.dimensions.get(unit_dimension)
        if not value:
            raise ValueError(f"case {case.id}: missing independent-unit dimension {unit_dimension!r}")
        tokens.add(_address(source, "declared-unit", unit_dimension, value))
    for key, kind in (("expected_fact_ids", "fact"), ("expected_evidence_ids", "observation")):
        for value in case.row.get(key, ()):
            tokens.add(_address(source, kind, str(value)))
    expected = case.row.get("expected_dag") or {}
    nodes = expected.get("nodes", ()) if isinstance(expected, Mapping) else expected
    connector_by_node = {str(node.get("id", "")): str(node.get("server") or node.get("connector") or "")
                         for node in nodes}
    for node in nodes:
        if str(node.get("node_kind") or node.get("op")) not in {"read", "search", "get", "list", "download"}:
            continue
        connector = connector_by_node[str(node.get("id", ""))]
        for value in (*node.get("expected_reads", ()), *node.get("fixtures", ())):
            tokens.add(_address(source, "record", connector, str(value)))
        if node.get("fixture"):
            tokens.add(_address(source, "record", connector, str(node["fixture"])))
    for assertion in case.row.get("assertions", ()):
        if assertion.get("type") == "reads_contain":
            connector = connector_by_node.get(str(assertion.get("node", "")), "")
            tokens.update(_address(source, "record", connector, str(value))
                          for value in assertion.get("records", ()))
    if not tokens:
        raise ValueError(f"case {case.id}: no evidence or independent-unit lineage; qualification cannot "
                         "infer independence from case IDs")
    return tuple(sorted(tokens))


def evidence_components(cases: Sequence[EvalCase], *,
                        unit_dimension: str | None = None) -> dict[str, str]:
    """Case IDs to whole transitive evidence components, in stable order."""
    ids = [case.id for case in cases]
    if len(set(ids)) != len(ids):
        raise ValueError("qualification cases must have unique IDs")
    parents = list(range(len(cases)))

    def root(index: int) -> int:
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    owners: dict[str, int] = {}
    tokens = [lineage_tokens(case, unit_dimension=unit_dimension) for case in cases]
    for index, keys in enumerate(tokens):
        for key in keys:
            if key in owners:
                left, right = root(index), root(owners[key])
                parents[max(left, right)] = min(left, right)
            else:
                owners[key] = index
    grouped: dict[int, set[str]] = {}
    for index, keys in enumerate(tokens):
        grouped.setdefault(root(index), set()).update(keys)
    names = {key: content_key("qualification-unit", *sorted(value)) for key, value in sorted(grouped.items())}
    return {case.id: names[root(index)] for index, case in sorted(enumerate(cases), key=lambda item: item[1].id)}


class SplitAudit(Model):
    """A diagnostic audit; an overlap is never an accepted training design."""

    isolated: bool
    training_cases: int
    heldout_cases: int
    training_units: int
    heldout_units: int
    overlapping_units: int
    overlaps: tuple[dict[str, Any], ...]


def audit_splits(train: Sequence[EvalCase], held: Sequence[EvalCase], *,
                 unit_dimension: str | None = None) -> SplitAudit:
    """Audit evidence closure across supplied splits, including renamed variants."""
    together = tuple(case.model_copy(update={"id": f"{side}:{index}"})
                     for side, group in (("train", train), ("held", held))
                     for index, case in enumerate(group))
    combined = evidence_components(together, unit_dimension=unit_dimension)
    train_units: dict[str, list[str]] = {}
    held_units: dict[str, list[str]] = {}
    for side, cases, into in (("train", train, train_units), ("held", held, held_units)):
        for index, case in enumerate(cases):
            into.setdefault(combined[f"{side}:{index}"], []).append(case.id)
    overlap = sorted(set(train_units).intersection(held_units))
    return SplitAudit(isolated=not overlap, training_cases=len(train), heldout_cases=len(held),
                      training_units=len(train_units), heldout_units=len(held_units),
                      overlapping_units=len(overlap),
                      overlaps=tuple({"unit": unit, "training": sorted(train_units[unit]),
                                      "heldout": sorted(held_units[unit])} for unit in overlap))


def isolated_splits(cases: Sequence[EvalCase], *, holdout_share: float,
                    unit_dimension: str | None = None) -> tuple[tuple[EvalCase, ...], tuple[EvalCase, ...]]:
    """Hash whole evidence components; declared split conflicts are refused."""
    if not 0 < holdout_share < 1:
        raise ValueError("holdout_share must lie strictly between 0 and 1")
    units = evidence_components(cases, unit_dimension=unit_dimension)
    fixed: dict[str, bool] = {}
    for case in cases:
        split = declared_split(case)
        if split is None:
            continue
        held = is_held_out(split)
        unit = units[case.id]
        if unit in fixed and fixed[unit] != held:
            raise ValueError("declared training and held-out splits share an evidence component")
        fixed[unit] = held
    train: list[EvalCase] = []
    heldout: list[EvalCase] = []
    for case in cases:
        unit = units[case.id]
        held = fixed.get(unit, int(unit[:16], 16) / (1 << 64) < holdout_share)
        (heldout if held else train).append(case)
    return tuple(train), tuple(heldout)


class QualificationExhausted(ValueError):
    """Every predeclared fresh tranche has been consumed."""


def qualification_tranches(cases: Sequence[EvalCase], *, policy: QualificationPolicy) -> tuple[tuple[str, ...], ...]:
    """The actual deterministic fresh cohorts, available to domain preflights.

    A domain may demand evidence in every cohort before running any target.
    Sharing this allocator prevents a coverage preview from certifying different
    cases than the sealed experiment will actually measure.
    """
    units = evidence_components(cases, unit_dimension=policy.unit_dimension)
    families: dict[str, list[str]] = {}
    for case in cases:
        families.setdefault(units[case.id], []).append(case.id)
    required = policy.trials * policy.min_units
    if len(families) < required:
        raise ValueError(f"qualification needs {required} independent held-out units "
                         f"({policy.trials} trials x {policy.min_units}); found {len(families)}")
    parts: list[list[str]] = [[] for _ in range(policy.trials)]
    counts = [0] * policy.trials
    for _family, ids in sorted(families.items(), key=lambda item: (-len(item[1]), item[0])):
        index = min(range(policy.trials), key=lambda i: (counts[i], len(parts[i]), i))
        parts[index].extend(sorted(ids))
        counts[index] += 1
    return tuple(tuple(sorted(part)) for part in parts)


@dataclass(frozen=True)
class QualificationTrial:
    number: int
    cases: tuple[EvalCase, ...]
    units: dict[str, str]
    label: str
    reservation: dict[str, Any]


@dataclass
class QualificationVault:
    """A sealed pool and its append-only reservations, local to one improve loop."""

    root: Path
    policy: QualificationPolicy
    cases: tuple[EvalCase, ...]
    units: dict[str, str]
    tranches: tuple[tuple[str, ...], ...]
    grader: dict[str, Any]

    @classmethod
    def open(cls, root: Path, train: Sequence[EvalCase], held: Sequence[EvalCase], *,
             policy: QualificationPolicy, grader: Mapping[str, Any]) -> QualificationVault:
        audit = audit_splits(train, held, unit_dimension=policy.unit_dimension)
        if not audit.isolated:
            raise ValueError("training and held-out cases share protected evidence or an independent unit")
        units = evidence_components(held, unit_dimension=policy.unit_dimension)
        tranches = qualification_tranches(held, policy=policy)
        manifest = {"schema": QUALIFICATION_SCHEMA, "policy": policy.model_dump(mode="json"),
                    "train": suite_digest(train), "held": suite_digest(held), "grader": dict(grader),
                    "sources": {side: sorted({case.dimensions["source_digest"] for case in cases})
                                for side, cases in (("train", train), ("held", held))},
                    "units": units, "tranches": tranches, "split_audit": audit.model_dump(mode="json")}
        canonical = json.loads(json.dumps(manifest, sort_keys=True))
        path = root / "seal.json"
        if path.exists():
            stored = json.loads(path.read_text(encoding="utf-8"))
            if stored != canonical:
                raise ValueError("sealed qualification policy, cases, record provenance or grader changed; "
                                 "use a new output directory")
        else:
            _claim(path, canonical)
        return cls(root=root, policy=policy, cases=tuple(held), units=units, tranches=tranches, grader=canonical["grader"])

    def reserve(self, round: int, *, champion: Mapping[str, Any], candidate: Mapping[str, Any],
                grader: Mapping[str, Any]) -> QualificationTrial:
        """Reserve before execution; exact resume is the only legal reuse."""
        grader_document = json.loads(json.dumps(dict(grader), sort_keys=True))
        if grader_document != self.grader:
            raise ValueError("qualification grader differs from its sealed identity")
        request = json.loads(json.dumps({"round": round, "champion": dict(champion), "candidate": dict(candidate),
                                       "grader": grader_document}, sort_keys=True))
        requests = sorted((self.root / "trials").glob("*.json"))
        existing: dict[str, Any] | None = None
        for expected, path in enumerate(requests, start=1):
            saved = json.loads(path.read_text(encoding="utf-8"))
            if saved.get("trial") != expected or path.name != f"{expected:03d}.json":
                raise ValueError("qualification reservations are not an intact append-only sequence")
            if saved["round"] == round:
                if any(saved[key] != value for key, value in request.items()):
                    raise ValueError("qualification reservation cannot be reused by a different "
                                     "candidate, champion, harness or grader")
                existing = saved
        number = int(existing["trial"]) if existing is not None else len(requests) + 1
        if number > self.policy.trials:
            raise QualificationExhausted("sealed qualification pool exhausted; provide a fresh pool "
                                         "in a new campaign stage")
        chosen = set(self.tranches[number - 1])
        cases = tuple(case for case in self.cases if case.id in chosen)
        reservation = {**request, "trial": number, "case_set": case_set_digest(cases),
                       "suite": suite_digest(cases),
                       "units": len({self.units[case.id] for case in cases}),
                       "confidence": self.policy.probe_confidence}
        if existing is not None and existing != reservation:
            raise ValueError("qualification reservation or its sealed case tranche changed")
        if existing is None:
            path = self.root / "trials" / f"{number:03d}.json"
            _claim(path, reservation)
        return QualificationTrial(number=number, cases=cases,
                                  units={case.id: self.units[case.id] for case in cases},
                                  label=f"holdout/trial-{number}", reservation=reservation)

    def summary(self) -> dict[str, Any]:
        spent = len(tuple((self.root / "trials").glob("*.json")))
        return {"schema": QUALIFICATION_SCHEMA, "policy": self.policy.model_dump(mode="json"),
                "independent_units": len(set(self.units.values())), "trials_spent": spent,
                "trials_remaining": self.policy.trials - spent,
                "probe_confidence": self.policy.probe_confidence}


__all__ = ["QUALIFICATION_SCHEMA", "QualificationPolicy", "QualificationExhausted", "QualificationTrial",
           "QualificationVault", "SplitAudit", "audit_splits", "evidence_components", "isolated_splits", "lineage_tokens",
           "qualification_tranches", "suite_digest", "with_record_provenance"]
