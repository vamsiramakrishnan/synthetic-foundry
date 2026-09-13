"""Business functions: what each one does (APQC), who does it (O*NET), and where.

A function is the unit a company organises people by: accounts payable,
treasury, the IT service desk. `_data/functions/functions@<n>.json` is the
crosswalk `tools/build_functions.py` builds between the two published
taxonomies this repository ships: every level-3 process of the cross-industry
PCF belongs to exactly one function, and every function seats O*NET
occupations in three tiers (manager, professional, support) and works in
named system-of-record classes. Names in the file are copied from the data
at build time, so the table cannot drift from its sources.

What the table gives the rest of the system: `for_process(pcf_id)` says
which function owns a process, so anything keyed by PCF id (an activity, a
request, a document) has an owner; `Function.occupations` gives the roles
that function seats, each with the titles real incumbents report; and
`Function.sor_classes` says which systems its records live in.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

SCHEMA = "worldloom.functions/v1"
DATA = "_data/functions"
TIERS: tuple[str, ...] = ("manager", "professional", "support")


@dataclass(frozen=True)
class Seat:
    """One O*NET occupation a function seats, in a tier."""

    tier: str
    code: str
    title: str


@dataclass(frozen=True)
class Process:
    """One PCF process a function owns."""

    pcf_id: str
    hierarchy_id: str
    name: str


@dataclass(frozen=True)
class Function:
    key: str
    title: str
    categories: tuple[str, ...]
    processes: tuple[Process, ...]
    seats: tuple[Seat, ...]
    sor_classes: tuple[str, ...]

    def tier(self, tier: str) -> tuple[Seat, ...]:
        if tier not in TIERS:
            raise KeyError(f"no tier {tier!r}; tiers are {', '.join(TIERS)}")
        return tuple(s for s in self.seats if s.tier == tier)

    @property
    def process_ids(self) -> frozenset[str]:
        return frozenset(p.pcf_id for p in self.processes)


@dataclass(frozen=True)
class Table:
    version: int
    sources: dict[str, str]
    functions: tuple[Function, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_key", {f.key: f for f in self.functions})
        owner: dict[str, Function] = {}
        for function in self.functions:
            for process in function.processes:
                owner[process.pcf_id] = function
        object.__setattr__(self, "_owner", owner)

    def function(self, key: str) -> Function:
        try:
            return self._by_key[key]  # type: ignore[attr-defined, no-any-return]
        except KeyError:
            raise KeyError(f"no function {key!r}; known: {', '.join(sorted(self._by_key))}") from None  # type: ignore[attr-defined]

    def get(self, key: str) -> Function | None:
        return self._by_key.get(key)  # type: ignore[attr-defined, no-any-return]

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(f.key for f in self.functions)

    def for_process(self, pcf_id: str) -> Function | None:
        """The function that owns a level-3 process, or `None` for an id no function owns."""
        return self._owner.get(pcf_id)  # type: ignore[attr-defined, no-any-return]

    def for_occupation(self, code: str) -> tuple[Function, ...]:
        """Every function that seats this O*NET-SOC code."""
        return tuple(f for f in self.functions if any(s.code == code for s in f.seats))

    def in_category(self, number: str) -> tuple[Function, ...]:
        """Every function owning a process in this PCF category (`"9"` for finance)."""
        return tuple(f for f in self.functions if number in f.categories)


def versions() -> tuple[int, ...]:
    root = files("worldloom").joinpath(DATA)
    found = sorted(
        int(entry.name.split("@")[1].split(".")[0])
        for entry in root.iterdir()
        if entry.name.startswith("functions@") and entry.name.endswith(".json")
    )
    return tuple(found)


@cache
def load(version: int | None = None) -> Table:
    """The shipped table, newest version unless one is named."""
    version = version if version is not None else versions()[-1]
    text = files("worldloom").joinpath(DATA, f"functions@{version}.json").read_text(encoding="utf-8")
    document: dict[str, Any] = json.loads(text)
    if document.get("schema") != SCHEMA:
        raise ValueError(f"functions@{version}: expected schema {SCHEMA!r}, found {document.get('schema')!r}")
    functions = tuple(
        Function(
            key=key,
            title=row["title"],
            categories=tuple(c["number"] for c in row["categories"]),
            processes=tuple(Process(**p) for p in row["processes"]),
            seats=tuple(
                Seat(tier=tier, code=seat["code"], title=seat["title"])
                for tier in TIERS for seat in row["occupations"].get(tier, [])
            ),
            sor_classes=tuple(row["sor_classes"]),
        )
        for key, row in document["functions"].items()
    )
    return Table(version=int(document["version"]), sources=dict(document["sources"]), functions=functions)


__all__ = ["DATA", "SCHEMA", "TIERS", "Function", "Process", "Seat", "Table", "load", "versions"]
