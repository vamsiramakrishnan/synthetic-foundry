"""The APQC Process Classification Framework, as shipped data.

APQC's PCF is the standard taxonomy of what an organisation does: thirteen
categories, each broken into process groups, processes, activities and
tasks, every element with a stable id that survives releases. APQC publishes
a cross-industry framework and industry frameworks (banking, retail,
utilities, healthcare and others) that share the same identifiers where the
process is the same and add their own where it is not.

This repository used to type its own process catalogue and mark the APQC
codes as hints. It now ships the frameworks themselves, ingested by
`tools/ingest_apqc.py` into `_data/pcf/<framework>@<version>.json.gz`, each
file carrying its copyright notice verbatim (APQC's licence permits copying
and derivative works on that condition). This module reads them.

Two ids per element, and the difference matters. The `pcf_id` is APQC's
stable identifier for the concept: "Invoice customer" is 10743 in every
release and every industry framework that has it. The `hierarchy_id` is the
human index (`9.2.2`) and changes between releases. Anything this repository
records against a process records the `pcf_id`.
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

SCHEMA = "worldloom.pcf/v1"
DATA = "_data/pcf"

LEVELS: dict[int, str] = {1: "category", 2: "process_group", 3: "process", 4: "activity", 5: "task"}


@dataclass(frozen=True)
class Element:
    """One process element of one framework."""

    pcf_id: str
    hierarchy_id: str
    level: int
    name: str
    description: str
    parent_pcf_id: str | None
    metrics_available: bool

    @property
    def kind(self) -> str:
        return LEVELS[self.level]

    @property
    def category(self) -> str:
        """The top-level category number, as a string (`"9"` for finance)."""
        return self.hierarchy_id.split(".")[0]


@dataclass(frozen=True)
class Metric:
    """One benchmarking measure APQC defines against a process element."""

    element_pcf_id: str
    metric_id: str
    name: str
    formula: str
    units: str
    category: str


@dataclass(frozen=True)
class Framework:
    """One framework: its elements in hierarchy order, indexed by both ids."""

    name: str
    version: str
    notice: str
    source: dict[str, Any]
    elements: tuple[Element, ...]
    metrics: tuple[Metric, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_id", {e.pcf_id: e for e in self.elements})
        object.__setattr__(self, "_by_hierarchy", {e.hierarchy_id: e for e in self.elements})
        children: dict[str | None, list[Element]] = {}
        for element in self.elements:
            children.setdefault(element.parent_pcf_id, []).append(element)
        object.__setattr__(self, "_children", {k: tuple(v) for k, v in children.items()})
        by_element: dict[str, list[Metric]] = {}
        for metric in self.metrics:
            by_element.setdefault(metric.element_pcf_id, []).append(metric)
        object.__setattr__(self, "_metrics", {k: tuple(v) for k, v in by_element.items()})

    @property
    def key(self) -> str:
        return f"{self.name}@{self.version}"

    def element(self, pcf_id: str) -> Element:
        """The element with this stable id, or a `KeyError` naming it."""
        try:
            return self._by_id[pcf_id]  # type: ignore[attr-defined, no-any-return]
        except KeyError:
            raise KeyError(f"{self.key} has no element with PCF id {pcf_id!r}") from None

    def at(self, hierarchy_id: str) -> Element:
        """The element at this hierarchy index (`"9.2.2"`) in this release."""
        try:
            return self._by_hierarchy[hierarchy_id]  # type: ignore[attr-defined, no-any-return]
        except KeyError:
            raise KeyError(f"{self.key} has no element at {hierarchy_id!r}") from None

    def get(self, pcf_id: str) -> Element | None:
        return self._by_id.get(pcf_id)  # type: ignore[attr-defined, no-any-return]

    def children(self, pcf_id: str | None) -> tuple[Element, ...]:
        """The immediate children of an element; `None` gives the categories."""
        return self._children.get(pcf_id, ())  # type: ignore[attr-defined, no-any-return]

    def ancestors(self, pcf_id: str) -> tuple[Element, ...]:
        """The chain from the category down to the element's parent."""
        chain: list[Element] = []
        current = self.element(pcf_id).parent_pcf_id
        while current is not None:
            parent = self.element(current)
            chain.append(parent)
            current = parent.parent_pcf_id
        return tuple(reversed(chain))

    def descendants(self, pcf_id: str) -> tuple[Element, ...]:
        """Every element under this one, in hierarchy order."""
        out: list[Element] = []
        stack = list(reversed(self.children(pcf_id)))
        while stack:
            element = stack.pop()
            out.append(element)
            stack.extend(reversed(self.children(element.pcf_id)))
        return tuple(out)

    def at_level(self, level: int) -> tuple[Element, ...]:
        return tuple(e for e in self.elements if e.level == level)

    def metrics_for(self, pcf_id: str) -> tuple[Metric, ...]:
        return self._metrics.get(pcf_id, ())  # type: ignore[attr-defined, no-any-return]


def _read(name: str) -> dict[str, Any]:
    resource = files("worldloom").joinpath(DATA, name)
    with resource.open("rb") as handle, gzip.GzipFile(fileobj=handle) as unzipped:
        document: dict[str, Any] = json.loads(unzipped.read().decode("utf-8"))
    if document.get("schema") != SCHEMA:
        raise ValueError(f"{name}: expected schema {SCHEMA!r}, found {document.get('schema')!r}")
    if not document.get("notice"):
        raise ValueError(f"{name}: a framework file must carry APQC's notice")
    return document


def provenance() -> dict[str, Any]:
    """The ingest ledger: which workbook each file came from, and what was skipped."""
    text = files("worldloom").joinpath(DATA, "provenance.json").read_text(encoding="utf-8")
    return dict(json.loads(text))


def frameworks() -> tuple[str, ...]:
    """Every shipped framework key (`cross_industry@7.4`, `retail@7.2.1`, ...), sorted."""
    return tuple(sorted(f"{row['framework']}@{row['version']}" for row in provenance()["frameworks"]))


@cache
def load(key: str) -> Framework:
    """One framework by key, or by bare name (the newest shipped version)."""
    if "@" not in key:
        matches = [k for k in frameworks() if k.split("@")[0] == key]
        if not matches:
            raise KeyError(f"no shipped framework named {key!r}; shipped: {', '.join(frameworks())}")
        key = sorted(matches, key=lambda k: tuple(int(p) for p in k.split("@")[1].split(".")))[-1]
    document = _read(f"{key}.json.gz")
    elements = tuple(
        Element(
            pcf_id=e["pcf_id"], hierarchy_id=e["hierarchy_id"], level=e["level"], name=e["name"],
            description=e["description"], parent_pcf_id=e["parent_pcf_id"],
            metrics_available=bool(e["metrics_available"]),
        )
        for e in document["elements"]
    )
    metrics = tuple(
        Metric(
            element_pcf_id=m["element_pcf_id"], metric_id=m["metric_id"], name=m["name"],
            formula=m["formula"], units=m["units"], category=m["category"],
        )
        for m in document["metrics"]
    )
    return Framework(
        name=document["framework"], version=document["version"], notice=document["notice"],
        source=dict(document["source"]), elements=elements, metrics=metrics,
    )


def cross_industry() -> Framework:
    return load("cross_industry")


def industries() -> tuple[str, ...]:
    """The industry frameworks shipped, by bare name."""
    return tuple(sorted({k.split("@")[0] for k in frameworks()} - {"cross_industry"}))


def shared(a: Framework, b: Framework) -> tuple[str, ...]:
    """PCF ids both frameworks carry: the processes the two have in common."""
    return tuple(e.pcf_id for e in a.elements if b.get(e.pcf_id) is not None)


__all__ = [
    "DATA", "LEVELS", "SCHEMA", "Element", "Framework", "Metric",
    "cross_industry", "frameworks", "industries", "load", "provenance", "shared",
]
