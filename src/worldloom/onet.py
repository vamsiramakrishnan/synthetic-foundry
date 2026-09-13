"""The O*NET occupation database, as shipped data.

O*NET is the U.S. Department of Labor's occupational taxonomy: about a
thousand occupations, each with a description, the titles people in it
report, the tasks they perform, the software they use, and the work
activities the tasks map to. It is the source this repository reads for who
does a process: the roles a function seats, the titles those roles carry,
and the systems they touch.

`tools/ingest_onet.py` writes `_data/onet/occupations@<release>.json.gz`
from the CSV archive O*NET publishes. The database is CC BY 4.0; the file
carries the credit line the licence asks for and this module exposes it as
`Database.notice`.

Codes are O*NET-SOC codes (`13-2011.00`). The first two digits are the SOC
major group (`13` business and financial operations, `43` office and
administrative support); a `.00` suffix is the SOC occupation itself and
another suffix is an O*NET specialty under it (`11-3031.01` treasurers and
controllers under `11-3031.00` financial managers).
"""

from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from typing import Any

SCHEMA = "worldloom.onet/v1"
DATA = "_data/onet"

JOB_ZONES: dict[int, str] = {
    1: "little or no preparation",
    2: "some preparation",
    3: "medium preparation",
    4: "considerable preparation",
    5: "extensive preparation",
}


@dataclass(frozen=True)
class Task:
    """One task statement of an occupation, with the detailed work activities it maps to."""

    id: int
    text: str
    type: str
    dwas: tuple[str, ...]


@dataclass(frozen=True)
class Software:
    """One software product an occupation uses, in O*NET's category."""

    category: str
    name: str
    hot: bool


@dataclass(frozen=True)
class Occupation:
    code: str
    title: str
    description: str
    job_zone: int | None
    reported_titles: tuple[str, ...]
    job_titles: tuple[str, ...]
    tasks: tuple[Task, ...]
    software: tuple[Software, ...]

    @property
    def major_group(self) -> str:
        """The two-digit SOC major group (`"13"`)."""
        return self.code[:2]

    @property
    def soc(self) -> str:
        """The six-digit SOC occupation the code sits under (`"11-3031"`)."""
        return self.code.split(".")[0]

    @property
    def core_tasks(self) -> tuple[Task, ...]:
        return tuple(t for t in self.tasks if t.type == "core")

    @property
    def titles(self) -> tuple[str, ...]:
        """Every title the occupation is known by: the reported ones first, then the alternates."""
        seen: dict[str, None] = {}
        for title in (*self.reported_titles, *self.job_titles):
            seen.setdefault(title, None)
        return tuple(seen)

    def software_in(self, category: str) -> tuple[Software, ...]:
        return tuple(s for s in self.software if s.category == category)


@dataclass(frozen=True)
class WorkActivity:
    """One detailed work activity and the two levels above it."""

    gwa_id: str
    gwa: str
    iwa_id: str
    iwa: str
    dwa_id: str
    dwa: str


@dataclass(frozen=True)
class Database:
    release: str
    notice: str
    licence: str
    source: dict[str, Any]
    occupations: tuple[Occupation, ...]
    work_activities: tuple[WorkActivity, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "_by_code", {o.code: o for o in self.occupations})
        object.__setattr__(self, "_dwa", {a.dwa_id: a for a in self.work_activities})

    def occupation(self, code: str) -> Occupation:
        """The occupation with this O*NET-SOC code, or a `KeyError` naming it."""
        try:
            return self._by_code[code]  # type: ignore[attr-defined, no-any-return]
        except KeyError:
            raise KeyError(f"O*NET {self.release} has no occupation with code {code!r}") from None

    def get(self, code: str) -> Occupation | None:
        return self._by_code.get(code)  # type: ignore[attr-defined, no-any-return]

    def major_group(self, prefix: str) -> tuple[Occupation, ...]:
        """Every occupation whose code starts with *prefix* (`"13"`, `"13-2"`, `"11-3031"`)."""
        return tuple(o for o in self.occupations if o.code.startswith(prefix))

    def search(self, phrase: str) -> tuple[Occupation, ...]:
        """Occupations whose title or any known title contains *phrase*, case-insensitively."""
        needle = phrase.lower()
        return tuple(
            o for o in self.occupations
            if needle in o.title.lower() or any(needle in t.lower() for t in o.titles)
        )

    def dwa(self, dwa_id: str) -> WorkActivity:
        try:
            return self._dwa[dwa_id]  # type: ignore[attr-defined, no-any-return]
        except KeyError:
            raise KeyError(f"O*NET {self.release} has no detailed work activity {dwa_id!r}") from None

    def software_categories(self) -> tuple[str, ...]:
        return tuple(sorted({s.category for o in self.occupations for s in o.software}))


def provenance() -> dict[str, Any]:
    text = files("worldloom").joinpath(DATA, "provenance.json").read_text(encoding="utf-8")
    return dict(json.loads(text))


def releases() -> tuple[str, ...]:
    """Every shipped release, oldest first."""
    versions = [row["release"] for row in provenance()["files"]]
    return tuple(sorted(versions, key=lambda v: tuple(int(p) for p in v.split("."))))


@cache
def load(release: str | None = None) -> Database:
    """The shipped database, newest release unless one is named."""
    release = release or releases()[-1]
    resource = files("worldloom").joinpath(DATA, f"occupations@{release}.json.gz")
    with resource.open("rb") as handle, gzip.GzipFile(fileobj=handle) as unzipped:
        document: dict[str, Any] = json.loads(unzipped.read().decode("utf-8"))
    if document.get("schema") != SCHEMA:
        raise ValueError(f"occupations@{release}: expected schema {SCHEMA!r}, found {document.get('schema')!r}")
    if not document.get("notice"):
        raise ValueError(f"occupations@{release}: the file must carry the O*NET credit line")
    occupations = tuple(
        Occupation(
            code=o["code"], title=o["title"], description=o["description"], job_zone=o["job_zone"],
            reported_titles=tuple(o["reported_titles"]), job_titles=tuple(o["job_titles"]),
            tasks=tuple(Task(id=t["id"], text=t["text"], type=t["type"], dwas=tuple(t["dwas"])) for t in o["tasks"]),
            software=tuple(Software(category=s["category"], name=s["name"], hot=bool(s["hot"])) for s in o["software"]),
        )
        for o in document["occupations"]
    )
    activities = tuple(WorkActivity(**a) for a in document["work_activities"])
    return Database(
        release=document["release"], notice=document["notice"], licence=document["licence"],
        source=dict(document["source"]), occupations=occupations, work_activities=activities,
    )


__all__ = [
    "DATA", "JOB_ZONES", "SCHEMA", "Database", "Occupation", "Software", "Task", "WorkActivity",
    "load", "provenance", "releases",
]
