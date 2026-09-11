"""The SDK entry point: one object holding a case set, its service, and its runs.

The functions in this package compose (``cases_from_corpus`` then
``service_for`` then ``run_cases`` then ``write_run``), and a harness that
drives Worldloom from Python should not have to remember the order. An
``EvalSession`` remembers it. Open one from an ``EnterpriseCorpus`` or an
exported directory, ask what the set can grade, run the reference agent for
the ceiling, run yours, compare, write. The session holds nothing a run can
change: every ``run`` begins its cases on fresh forks of the same records.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any

from ..connectors.serving import ConnectorEvaluationService
from .agents import AgentUnderTest, ReferenceAgent
from .contract import AxisCoverage, EvalCase, axis_coverage, cases_from_corpus
from .results import Comparison, RunSummary, compare, summarize, write_run
from .runner import Clock, RunReport, run_cases, service_for


class EvalSession:
    """A case set and the service that executes it, with the runs it has produced."""

    def __init__(self, cases: Iterable[EvalCase], records: Iterable[Mapping[str, Any]], *,
                 definitions: Mapping[str, Any] | None = None, principal: str = "agent") -> None:
        self.cases: tuple[EvalCase, ...] = tuple(cases)
        if not self.cases:
            raise ValueError("an eval session needs at least one case")
        # Kept as given: `ConnectorRecord` models and plain mappings are both
        # what the service accepts, and it copies them itself at construction.
        self._records = tuple(records)
        self._definitions = dict(definitions or {})
        self.principal = principal
        self.runs: dict[str, RunReport] = {}

    @classmethod
    def from_corpus(cls, corpus: Any, *, definitions: Mapping[str, Any] | None = None,
                    principal: str = "agent", limit: int | None = None) -> EvalSession:
        cases = cases_from_corpus(corpus, definitions=definitions, principal=principal)
        return cls(cases[:limit] if limit else cases, corpus.connector_data.records,
                   definitions=definitions, principal=principal)

    @classmethod
    def from_export(cls, directory: str | Path, **options: Any) -> EvalSession:
        from ..enterprise_io import load_exported_corpus

        return cls.from_corpus(load_exported_corpus(Path(directory)), **options)

    def service(self) -> ConnectorEvaluationService:
        """A fresh service over the session's rows and records. Runs do not share state."""

        return service_for(self.cases, self._records, definitions=self._definitions or None)

    def coverage(self) -> AxisCoverage:
        return axis_coverage(self.cases)

    def run(self, agent: AgentUnderTest, *, clock: Clock | None = None,
            rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None = None,
            label: str | None = None) -> RunReport:
        report = run_cases(self.service(), self.cases, agent, principal=self.principal, clock=clock, rater=rater)
        self.runs[label or agent.name] = report
        return report

    def reference(self, **options: Any) -> RunReport:
        """The executable ceiling: the reference agent through the same surface."""

        return self.run(ReferenceAgent(self.cases), label="reference", **options)

    def summary(self, label: str) -> RunSummary:
        return summarize(self._run(label))

    def compare(self, baseline: str, recent: str) -> Comparison:
        return compare(self._run(baseline), self._run(recent))

    def write(self, label: str, directory: str | Path) -> RunSummary:
        return write_run(Path(directory), self._run(label))

    def _run(self, label: str) -> RunReport:
        try:
            return self.runs[label]
        except KeyError as error:
            raise KeyError(f"no run labelled {label!r}; have {sorted(self.runs)}") from error


__all__ = ["EvalSession"]
