"""What each layer of a world interview accepts: the answer shapes, and nothing else.

Every answer is either a document an existing seam already reads or a thin
envelope around several of them. The company layer carries a company
specification (``company.from_document``); a line of business is a
``lob.LobSeed`` plus the ``lob.RoleSpec`` rows its roles stage takes; a
process is an ``episodes.EpisodeSpec`` with the ``lob.Responsibility`` and
``lob.SlotBinding`` rows that seat it; a document is a
``doctypes.DocumentType``; a policy change is a ``packs.PackCommitment``. The
only shapes new here are the ones no seam had a home for: the seniority level
each role sits at, which systems each process step touches, who reviews and
approves each document, the org changes a history schedules, and what an
employee at each level would ask an agent to do. Those are small on purpose,
and each is refused against the seams it points into rather than trusted.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from ..cascade import CascadeModel
from ..doctypes import DocumentType
from ..episodes import EpisodeSpec
from ..lob import Responsibility, RoleSpec, SlotBinding
from ..packs import PackCommitment

#: The seniority ladder, lowest first. An eval's difficulty is tied to the
#: level of the employee who would ask for it, so the order is load-bearing:
#: a report may not sit above the person it reports to.
Level = Literal["ic", "manager", "director", "executive"]
LEVELS: tuple[str, ...] = ("ic", "manager", "director", "executive")


def rank(level: str) -> int:
    """*level*'s place on the ladder, 0 for an individual contributor."""
    return LEVELS.index(level)


class CompanyAnswer(CascadeModel):
    """The industry and the company, as one company specification document."""

    spec: dict[str, Any]


class LobDraft(CascadeModel):
    """One line of business before its processes exist: the seed and its roles stage.

    Responsibilities and slot bindings name the fact kinds and seats a process
    declares, so they are answered with that LOB's processes, not here.
    """

    name: str = Field(pattern=r"^[a-z][a-z0-9_]*$")
    title: str = Field(min_length=1)
    purpose: str = Field(min_length=1)
    roles: list[RoleSpec]


class LobsAnswer(CascadeModel):
    lobs: list[LobDraft]


class EmployeesAnswer(CascadeModel):
    """The seniority level of every role the lines of business declared."""

    levels: dict[str, Level]


class ProcessesAnswer(CascadeModel):
    """One LOB's processes, the systems each step touches, and who is seated in them.

    ``systems`` is keyed ``Process.event_kind``: every event a process declares
    names the systems it leaves a record in.
    """

    episodes: list[EpisodeSpec] = Field(min_length=1)
    systems: dict[str, list[str]]
    responsibilities: list[Responsibility]
    slot_bindings: list[SlotBinding] = Field(default_factory=list)


class DocumentChain(CascadeModel):
    """Who reviews and who approves one document type, and where it is published."""

    artifact_type: str
    reviewer: str | None = None
    approver: str | None = None
    published_on: list[str] = Field(default_factory=lambda: ["sharepoint"])


class DocumentsAnswer(CascadeModel):
    """The document types the processes file, and each one's review chain."""

    doctypes: list[DocumentType] = Field(default_factory=list)
    chains: list[DocumentChain]


class OrgChange(CascadeModel):
    """One scheduled change to the organisation, landing after its period's close."""

    period: str = Field(pattern=r"^\d{4}-\d{2}$")
    kind: Literal["departure", "reorganisation", "hire"]
    role_key: str = ""
    unit_key: str = ""
    new_leader_role: str = ""
    title: str = ""
    function: str = ""


class TimelineAnswer(CascadeModel):
    """The history: periods, incidents, org changes and policies that change later documents."""

    start: str = Field(pattern=r"^\d{4}-\d{2}$")
    periods: int = Field(ge=2, le=12)
    incidents: list[str] = Field(default_factory=list)
    changes: list[OrgChange] = Field(default_factory=list)
    policies: list[PackCommitment] = Field(default_factory=list)


class ReadSpec(CascadeModel):
    """One read an intent needs: a process step's records on a system, or a document.

    A step read names ``process``, ``step`` (an event kind) and ``system``. A
    document read names ``document`` (an artifact type) and the ``period`` it
    must be read at: ``latest``, ``first``, ``previous``, ``all`` or a
    ``YYYY-MM`` (a step read takes the same periods).
    ``revised`` asks for the document only where it carries a revision chain.
    """

    system: str = ""
    process: str = ""
    step: str = ""
    document: str = ""
    period: str = "latest"
    revised: bool = False

    @property
    def is_document(self) -> bool:
        return bool(self.document)


class BranchSpec(CascadeModel):
    """A decision on data: which write runs depends on how many records a read returns."""

    read: int = Field(ge=0)
    at_least: int = Field(default=2, ge=1)


class DeliverSpec(CascadeModel):
    """Where the result is written, and how."""

    system: str
    entity: str
    operation: str = "create"
    format: str = "record"


class Intent(CascadeModel):
    """What one employee would ask an agent to do across the systems."""

    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    level: Level
    asker: str
    ask: str = Field(min_length=1)
    reads: list[ReadSpec] = Field(min_length=1)
    branch: BranchSpec | None = None
    per_entity: bool = False
    deliver: DeliverSpec


class EvalsAnswer(CascadeModel):
    intents: list[Intent] = Field(min_length=1)


#: The answer model each layer accepts, by layer key.
ANSWERS: dict[str, type[CascadeModel]] = {
    "company": CompanyAnswer,
    "lobs": LobsAnswer,
    "employees": EmployeesAnswer,
    "processes": ProcessesAnswer,
    "documents": DocumentsAnswer,
    "timeline": TimelineAnswer,
    "evals": EvalsAnswer,
}


__all__ = [
    "ANSWERS", "LEVELS", "BranchSpec", "CompanyAnswer", "DeliverSpec", "DocumentChain", "DocumentsAnswer",
    "EmployeesAnswer", "EvalsAnswer", "Intent", "Level", "LobDraft", "LobsAnswer", "OrgChange",
    "ProcessesAnswer", "ReadSpec", "TimelineAnswer", "rank",
]
