"""What the importer says when something is wrong, or was built differently.

A finding is the unit of honesty: nothing the importer cannot build is ever
dropped silently, so every refusal and every judgement call leaves one of these
behind. ``hard`` means something was lost that should not have been; ``info``
means nothing is wrong and a reader should still be told.

Two code vocabularies meet here, and they are deliberately not merged:

``Finding.code``
    The *shared* vocabulary the miner also speaks — ``schema`` and ``inv1`` …
    ``inv10`` for contract failures, and the importer's own names
    (``connector_not_emulated``, ``step_folded``, …) for everything later. Both
    checkers must agree on these, file for file.

``CatalogueRefused.code``
    Worldloom's registered refusal code, the thing the CLI turns into an exit
    status. One refusal can carry many findings.

A version mismatch is the case where the two differ: the shared code is
``schema``, because that is the verdict the conformance suite expects, while the
refusal is ``catalogue_version_unknown``, because that is what Worldloom's own
error registry calls it. Neither contract has to bend.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import Field

from ..models import Model

#: Findings are ordered ``schema`` first, then invariants in numeric order, so
#: ``ImportReport.violation`` picks the same one every run. ``inv2`` must sort
#: before ``inv10``, which rules out comparing the strings.
_SCHEMA_CODE = "schema"


class Severity(StrEnum):
    """Whether anything was lost.

    Not whether something was built. Those two came apart in W3: a journey
    that calls no business tool needs no world to run against, so it is not
    built and nothing at all is missing. Severity answers the question
    ``accepted`` and ``--strict`` actually ask — should this stop a run?
    """

    HARD = "hard"
    """Something real was lost. The catalogue, the journey or the failure mode
    was refused, and a strict run should fail rather than ship a corpus
    quietly missing it."""

    INFO = "info"
    """Nothing is wrong, and a reader should still be told — an alias picked,
    a step folded, a default used, or a journey that needed no world."""


class Finding(Model):
    """One structured note about one thing."""

    code: str = Field(min_length=1)
    """Shared vocabulary where one exists: ``schema``, ``inv1`` … ``inv10``."""

    severity: Severity
    message: str = Field(min_length=1)
    """Plain English, aimed at whoever has to fix the catalogue."""

    cuj_id: str = ""
    """The journey this is about, when it is about one."""

    detail: dict[str, str] = Field(default_factory=dict)
    """Structured context, so a reader does not have to parse ``message``."""


def hard(code: str, message: str, *, cuj_id: str = "",
         detail: dict[str, str] | None = None) -> Finding:
    """A finding that stops something being built."""
    return Finding(code=code, severity=Severity.HARD, message=message,
                   cuj_id=cuj_id, detail=detail or {})


def info(code: str, message: str, *, cuj_id: str = "",
         detail: dict[str, str] | None = None) -> Finding:
    """A finding that records a choice, without stopping anything."""
    return Finding(code=code, severity=Severity.INFO, message=message,
                   cuj_id=cuj_id, detail=detail or {})


def _rank(code: str) -> tuple[int, int]:
    """Sort key putting ``schema`` first, then ``inv1`` … ``inv10`` numerically."""
    if code == _SCHEMA_CODE:
        return (0, 0)
    if code.startswith("inv") and code[3:].isdigit():
        return (1, int(code[3:]))
    return (2, 0)


class ImportReport(Model):
    """Every finding from one import, in the order they were produced."""

    findings: tuple[Finding, ...] = ()

    @property
    def accepted(self) -> bool:
        """True when nothing hard was found. Info findings do not block."""
        return not self.hard_findings

    @property
    def hard_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.HARD)

    @property
    def info_findings(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings if f.severity is Severity.INFO)

    @property
    def violation(self) -> str | None:
        """The one shared code to report, or ``None`` if nothing is wrong.

        The conformance suite names a single verdict per file, and every file it
        ships breaks exactly one rule — but a real catalogue can break several,
        and ``load_catalogue`` reports all of them. This picks the one to quote:
        ``schema`` if the shape failed, otherwise the lowest-numbered invariant.
        """
        hard_codes = [f.code for f in self.hard_findings]
        return min(hard_codes, key=_rank) if hard_codes else None

    def with_findings(self, *added: Finding) -> ImportReport:
        """A new report with more findings. The model is frozen, so this is how
        findings accumulate."""
        return ImportReport(findings=self.findings + added)


class CatalogueRefused(Exception):
    """The catalogue was refused. Carries every reason, not just the first.

    ``code`` is Worldloom's refusal code, which ``telemetry_cli`` (W3) maps onto
    an exit status. ``report`` holds the findings in the shared vocabulary.
    """

    def __init__(self, code: str, report: ImportReport) -> None:
        self.code = code
        self.report = report
        reasons = "; ".join(f.message for f in report.hard_findings)
        super().__init__(f"{code}: {reasons}")
