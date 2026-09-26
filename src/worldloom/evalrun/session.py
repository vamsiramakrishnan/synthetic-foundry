"""The SDK entry point: one object holding a case set, its service, and its runs.

The functions in this package compose (``cases_from_corpus`` then
``service_for`` then ``run_cases`` then ``write_run``), and a harness that
drives Worldloom from Python should not have to remember the order. An
``EvalSession`` remembers it. Open one from an ``EnterpriseCorpus`` or an
exported directory, ask what the set can grade, run the reference agent for
the ceiling, run yours, compare, write. ``plan`` grades a planner on the
plan axis alone. The session holds nothing a run can change: every ``run``
begins its cases on fresh forks of the same records.

The improvement loop is the same composition one level up. ``improve()``
takes raw callables (how to run cases, how to make an agent for a policy,
how to talk to the proposer), which is the right shape for a function the
CLI and the Studio both call and the wrong one for a person at a prompt.
``EvalSession.improver`` builds those callables from the session: the runner
over the session's records (and the held-out session's), the agents from an
installed harness or any callable, the proposer from a harness or any
callable, the rater from its name. What it returns runs ``improve()``
unchanged, so every rule the loop enforces (the frozen grader, the two
gates, the held-out cases the proposer never sees) holds here because it is
the same code, not a second copy of it. The failure-side tools the loop is
made of (autopsy, curriculum, escalation, trace export, grader agreement)
are one call each on the session, over its own cases, and return exactly
what the low-level functions return.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal

from ..connectors.serving import ConnectorEvaluationService
from .agents import AgentUnderTest, ReferenceAgent
from .contract import AxisCoverage, EvalCase, axis_coverage, cases_from_corpus
from .plans import Planner, plan_cases
from .results import Comparison, RunSummary, compare, summarize, write_run
from .runner import Clock, RunReport, run_cases, service_for

if TYPE_CHECKING:
    from ..packkit.authoring import Exchange
    from ..packkit.resolve import ResolvedPack
    from .agreement import AgreementReport
    from .autopsy import Autopsy
    from .curriculum import Curriculum, Escalation
    from .improve import ImproveReport
    from .rater import Rater

#: A run named by its label in the session, by the directory ``write_run``
#: wrote it to, or as the report itself.
RunRef = str | Path | RunReport
ExportFormat = Literal["sft", "pairs", "rewards"]


# -- agents, proposers and raters from names ------------------------------------------


@dataclass(frozen=True)
class ExecHarness:
    """The agent under test for a policy: an ``ExecAgent`` over one command, made fresh per policy.

    The loop asks for a new agent every time the champion or a candidate
    runs, because the policy is what differs between them. Calling this with
    a resolved ``agent`` pack returns the ``ExecAgent`` the CLI's ``--exec``
    and ``--harness`` build, so a loop driven from Python and one driven
    from the shell run the same child the same way.
    """

    command: str
    timeout: float = 600.0
    shell: bool = False
    max_turns: int | None = None

    def __call__(self, pack: ResolvedPack) -> AgentUnderTest:
        from .harness import ExecAgent

        return ExecAgent(self.command, timeout=self.timeout, shell=self.shell, max_turns=self.max_turns,
                         policy=pack)


def _child_command(name: str | None, command: str | None, *, timeout: float, what: str) -> str:
    """The command a harness name or an explicit command stands for; exactly one of them."""
    if (name is None) == (command is None):
        raise ValueError(f"name the {what} by harness (codex, claude) or by command, not both and not neither")
    if command is not None:
        return command
    assert name is not None
    from ..studio.harness import adapter_command

    # The child is given less than the parent allows, so the parent's timeout
    # reports the overrun rather than a race between the two (as the CLI does).
    return adapter_command(name, timeout=max(1.0, timeout - 5))


def harness_for(name: str | None = None, *, command: str | None = None, timeout: float = 600.0,
            shell: bool = False, max_turns: int | None = None) -> ExecHarness:
    """The agent under test as an installed coding harness (``"codex"``, ``"claude"``) or an ``--exec`` command."""

    return ExecHarness(_child_command(name, command, timeout=timeout, what="agent under test"),
                       timeout=timeout, shell=shell, max_turns=max_turns)


def proposer_for(name: str | None = None, *, command: str | None = None, timeout: float = 600.0) -> Exchange:
    """The proposing harness over the pack interview seam, as ``pack author`` and ``evalrun improve`` run it."""
    from ..packkit.authoring import run_exec_exchange

    return run_exec_exchange(_child_command(name, command, timeout=timeout, what="proposer"), timeout=timeout)


def rater_for(spec: str | Rater | None, *, timeout: float = 600.0, shell: bool = False) -> Rater | None:
    """The rater ``spec`` names: ``"grounded"``, ``"exec:<command>"``, an object already, or None."""
    if spec is None or not isinstance(spec, str):
        return spec
    if spec == "grounded":
        from .rater import GroundedRater

        return GroundedRater()
    if spec.startswith("exec:") and spec.removeprefix("exec:").strip():
        from .rater import exec_rater

        return exec_rater(spec.removeprefix("exec:"), timeout=timeout, shell=shell)
    raise ValueError(f"unknown rater {spec!r}; use grounded or exec:<command>")


def _agent_factory(agent: Callable[[ResolvedPack], AgentUnderTest] | str) -> Callable[[ResolvedPack], AgentUnderTest]:
    if not isinstance(agent, str):
        return agent
    if agent.startswith("exec:"):
        return harness_for(command=agent.removeprefix("exec:"))
    return harness_for(agent)


def _exchange(value: Exchange | str) -> Exchange:
    if not isinstance(value, str):
        return value
    if value.startswith("exec:"):
        return proposer_for(command=value.removeprefix("exec:"))
    return proposer_for(value)


# -- the improvement loop, bound to a session -----------------------------------------


@dataclass
class ImproveLoop:
    """``improve()`` with its callables built from a session. ``run`` it from a champion.

    Build one with ``EvalSession.improver``. ``out`` receives ``rounds/``,
    ``runs/``, ``packs/`` and ``improve.json`` exactly as the CLI writes
    them, so a loop started here resumes from ``worldloom evalrun improve``
    and the other way round.
    """

    session: EvalSession
    agent: Callable[[ResolvedPack], AgentUnderTest]
    exchange: Exchange
    out: Path
    holdout: tuple[EvalCase, ...] | None = None
    holdout_share: float | None = None
    rater: Rater | None = None
    concurrency: int = 1
    pack_roots: tuple[str | Path, ...] = ()
    authoring_rounds: int | None = None
    min_train_delta: float | None = None
    min_holdout_delta: float | None = None
    max_axis_regression: float | None = None
    #: Gate on the value-weighted delta too (``value.value_table`` over the
    #: training and held-out cases and their records).
    value: bool = False
    ablate: bool | None = None
    #: Runs of each policy per case set; ``None`` is the policy ``evalrun.improve.repeats``.
    repeats: int | None = None
    _records: tuple[Any, ...] = ()
    #: The held-out session's records, when the holdout is another corpus: each
    #: corpus is served over its own, since two worlds reuse external keys.
    _holdout_records: tuple[Any, ...] | None = None
    _services: dict[str, ConnectorEvaluationService] = field(default_factory=dict, repr=False)

    def run_cases(self, cases: Sequence[EvalCase], agent: AgentUnderTest) -> RunReport:
        """One agent over *cases*: the ``run`` callable ``improve()`` is given.

        A service is built once per case set and reused, as the CLI does:
        every case still begins on its own fork, so reuse changes nothing a
        grade can see. Concurrency reaches both the service's limits and
        ``run_cases``.
        """
        from .runner import case_set_digest

        key = case_set_digest(cases)
        service = self._services.get(key)
        if service is None:
            held = (self._holdout_records is not None and self.holdout is not None
                    and key == case_set_digest(self.holdout))
            records = self._holdout_records if held and self._holdout_records is not None else self._records
            service = service_for(cases, records, concurrency=self.concurrency,
                                  definitions=self.session._definitions or None)
            self._services[key] = service
        return run_cases(service, cases, agent, principal=self.session.principal, rater=self.rater,
                         concurrency=self.concurrency)

    def run(self, champion: ResolvedPack | str, *, rounds: int | None = None) -> ImproveReport:
        """Run the loop from *champion*: a resolved ``agent`` pack, or a reference like ``agent:baseline``.

        A reference also finds the candidates an earlier loop into the same
        ``out`` accepted (``agent:baseline-r2``), so a later loop can start
        from an earlier one's champion by name.
        """
        from .improve import improve

        roots = (self.out / "packs", *self.pack_roots)
        start = self.session.agent_pack(champion, roots=roots) if isinstance(champion, str) else champion
        values = holdout_values = None
        if self.value:
            from .value import value_table

            if self._holdout_records is not None and self.holdout is not None:
                values = value_table(self.session.cases, self._records)
                holdout_values = value_table(self.holdout, self._holdout_records)
            else:
                values = value_table((*self.session.cases, *(self.holdout or ())), self._records)
        return improve(start, self.session.cases, run=self.run_cases, agent_for=self.agent, exchange=self.exchange,
                       out=self.out, rater=self.rater, holdout=self.holdout, holdout_share=self.holdout_share,
                       rounds=rounds, pack_roots=self.pack_roots, authoring_rounds=self.authoring_rounds,
                       min_train_delta=self.min_train_delta, min_holdout_delta=self.min_holdout_delta,
                       max_axis_regression=self.max_axis_regression, ablate=self.ablate, values=values,
                       holdout_values=holdout_values, repeats=self.repeats)

    def champion(self, report: ImproveReport) -> ResolvedPack:
        """The pack *report* ended with, resolved and pinned by digest from where the loop stored it."""
        from .. import packkit

        identity = report.champion
        roots = (self.out / "packs", *self.pack_roots)
        # Pinned: a pack edited on disk since the loop ran is refused, not silently returned.
        return packkit.resolve(f"{identity['ref']}@{identity['digest']}", kind_name="agent", roots=roots)


# -- the session ------------------------------------------------------------------------


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
        """A session over an exported enterprise corpus, or over a case set (`industry export` writes one)."""
        from ..enterprise_io import load_exported_corpus
        from .contract import is_case_set, read_case_set

        if is_case_set(directory):
            cases, records = read_case_set(directory)
            limit = options.pop("limit", None)
            options.pop("definitions", None)
            return cls(cases[:limit] if limit else cases, records, **options)
        return cls.from_corpus(load_exported_corpus(Path(directory)), **options)

    @classmethod
    def open(cls, source: str | Path | Any, **options: Any) -> EvalSession:
        """A session over *source*: a directory (exported corpus or case set) or a built ``EnterpriseCorpus``."""

        if isinstance(source, str | Path):
            return cls.from_export(source, **options)
        return cls.from_corpus(source, **options)

    def service(self, *, concurrency: int = 1) -> ConnectorEvaluationService:
        """A fresh service over the session's rows and records. Runs do not share state."""

        return service_for(self.cases, self._records, concurrency=concurrency,
                           definitions=self._definitions or None)

    def coverage(self) -> AxisCoverage:
        return axis_coverage(self.cases)

    def run(self, agent: AgentUnderTest, *, clock: Clock | None = None,
            rater: Callable[[EvalCase, str], tuple[float | None, str | None]] | None = None,
            label: str | None = None, concurrency: int = 1) -> RunReport:
        report = run_cases(self.service(concurrency=concurrency), self.cases, agent, principal=self.principal,
                           clock=clock, rater=rater, concurrency=concurrency)
        self.runs[label or agent.name] = report
        return report

    def plan(self, planner: Planner, *, label: str | None = None) -> RunReport:
        """Grade the plan axis alone: the planner states each case's DAG, nothing runs."""

        report = plan_cases(self.service(), self.cases, planner, principal=self.principal)
        self.runs[label or planner.name] = report
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

    def report(self, run: RunRef) -> RunReport:
        """*run* as a report: a label in this session, a run directory on disk, or a report already."""
        if isinstance(run, RunReport):
            return run
        if isinstance(run, str) and run in self.runs:
            return self.runs[run]
        path = Path(run)
        if (path / "run.json").exists():
            from .results import read_run

            return read_run(path)
        return self._run(str(run))

    # -- the improvement loop ---------------------------------------------------------

    @staticmethod
    def agent_pack(ref: str | ResolvedPack, *, roots: Sequence[str | Path] = ()) -> ResolvedPack:
        """A linted ``agent`` pack: ``agent:<name>[@<digest>]`` or a pack file. Refused when its lint finds anything."""
        from .policy import load, require

        if not isinstance(ref, str):
            return require(ref)
        return load(ref, roots=tuple(roots))

    harness = staticmethod(harness_for)
    proposer = staticmethod(proposer_for)

    def improver(
        self,
        *,
        agent: Callable[[ResolvedPack], AgentUnderTest] | str,
        proposer: Exchange | str,
        out: str | Path,
        holdout: EvalSession | Sequence[EvalCase] | None = None,
        holdout_share: float | None = None,
        rater: str | Rater | None = None,
        concurrency: int | None = None,
        pack_roots: Sequence[str | Path] = (),
        authoring_rounds: int | None = None,
        min_train_delta: float | None = None,
        min_holdout_delta: float | None = None,
        max_axis_regression: float | None = None,
        value: bool = False,
        ablate: bool | None = None,
        repeats: int | None = None,
    ) -> ImproveLoop:
        """The improvement loop over this session's cases; ``.run(champion)`` starts it.

        ``agent`` makes the agent under test for a policy: ``session.harness("codex")``,
        ``"exec:<command>"``, a harness name, or any callable from a resolved
        pack to an agent. ``proposer`` is the harness that revises the policy:
        ``session.proposer("codex")``, a name, ``"exec:<command>"``, or any
        callable from an interview request to a reply. ``holdout`` is a
        second session (a fresh-seed corpus: the stronger test) or held-out
        cases over this session's records; without it a stable share of the
        cases is held back. ``rater`` is pinned for the whole loop.
        ``concurrency`` defaults to the policy ``evalrun.concurrency``.
        ``value=True`` also gates on the delta weighted by each case's value at
        stake; ``ablate`` overrides the policy ``evalrun.improve.ablate``.
        ``repeats`` runs each policy that many times per case set and gates on
        a paired interval (default: the policy ``evalrun.improve.repeats``, 1).
        """
        from .runner import default_concurrency

        records: tuple[Any, ...] = self._records
        held: tuple[EvalCase, ...] | None = None
        held_records: tuple[Any, ...] | None = None
        if isinstance(holdout, EvalSession):
            held = holdout.cases
            held_records = holdout._records
        elif holdout is not None:
            held = tuple(holdout)
        workers = default_concurrency() if concurrency is None else concurrency
        if workers < 1:
            raise ValueError("concurrency must be at least 1")
        return ImproveLoop(session=self, agent=_agent_factory(agent), exchange=_exchange(proposer), out=Path(out),
                           holdout=held, holdout_share=holdout_share, rater=rater_for(rater),
                           concurrency=workers, pack_roots=tuple(pack_roots), authoring_rounds=authoring_rounds,
                           min_train_delta=min_train_delta, min_holdout_delta=min_holdout_delta,
                           max_axis_regression=max_axis_regression, value=value, ablate=ablate,
                           repeats=repeats, _records=records, _holdout_records=held_records)

    # -- the loop's parts, one call each ------------------------------------------------

    def autopsy(self, run: RunRef, *, top: int = 12) -> Autopsy:
        """The run's failing cases clustered by finding key, with the session's cases as the contracts."""
        from .autopsy import autopsy

        return autopsy(self.report(run), cases=self.cases, top=top)

    def brief(self, run: RunRef, *, top: int = 12) -> str:
        """The plain-text brief an improving harness is handed for *run*."""
        from .autopsy import render_brief

        return render_brief(self.autopsy(run, top=top))

    def curriculum(self, run: RunRef, base_plan: Any, *, round: int = 1, total: int | None = None,
                   min_per_cluster: int = 4, max_share: float = 0.5, holdout_share: float = 0.2,
                   top: int = 12) -> Curriculum:
        """Fresh cases aimed at *run*'s failures: a dataset plan under a new seed, with a held-out split.

        *base_plan* is a ``DatasetPlan``, its JSON document, or a path to one.
        """
        from .curriculum import design_curriculum

        return design_curriculum(self.autopsy(run, top=top), _dataset_plan(base_plan), round=round, total=total,
                                 min_per_cluster=min_per_cluster, max_share=max_share, holdout_share=holdout_share)

    def escalate(self, *runs: RunRef, target_band: tuple[float, float] = (0.3, 0.8)) -> list[Escalation]:
        """Harder slices for every slice the pooled *runs* saturate."""
        from .curriculum import escalate

        return escalate([self.report(run) for run in runs], target_band=target_band)

    def export(self, run: RunRef, fmt: ExportFormat, *, against: RunRef | None = None, out: str | Path | None = None,
               min_score: float = 0.0, include_failed: bool = False, margin: float | None = None,
               splits: Sequence[str] | None = None, include_holdout: bool = False, max_chars: int | None = None,
               tools: bool = True) -> list[dict[str, Any]]:
        """*run* as training data: ``sft`` transcripts, ``pairs`` against a second run, or ``rewards``.

        Held-out splits are refused unless *include_holdout*, as on the CLI.
        ``tools`` attaches each case's tool catalog to an SFT record, as
        ``evalrun export`` does. With *out* the records are also written as
        JSONL.
        """
        from .export import (
            FORMATS,
            preference_pairs,
            reward_records,
            sft_records,
            write_records,
        )

        if fmt not in FORMATS:
            raise ValueError(f"format must be one of {', '.join(FORMATS)}, not {fmt!r}")
        if (fmt == "pairs") != (against is not None):
            raise ValueError("pairs need `against`, a second run over the same cases; sft and rewards read one run")
        report = self.report(run)
        records: list[dict[str, Any]]
        if fmt == "sft":
            catalogs = self._catalogs(report) if tools else None
            records = sft_records(report, self.cases, min_score=min_score, require_passed=not include_failed,
                                  splits=splits, include_holdout=include_holdout, tools=catalogs,
                                  max_chars=max_chars)
        elif fmt == "pairs":
            assert against is not None
            records = preference_pairs(report, self.report(against), self.cases, margin=margin, splits=splits,
                                       include_holdout=include_holdout, max_chars=max_chars)
        else:
            records = reward_records(report, self.cases, splits=splits, include_holdout=include_holdout)
        if out is not None:
            write_records(Path(out), records)
        return records

    def _catalogs(self, report: RunReport) -> dict[str, Any]:
        from .harness import requests_document

        ran = {result.case_id for result in report.results}
        document = requests_document(self.service(), [case for case in self.cases if case.id in ran],
                                     principal=report.principal)
        return {entry["case_id"]: entry["tools"] for entry in document["cases"]}

    def import_studio(self, results: str | Path, *, label: str = "studio") -> RunReport:
        """An Eval Studio results CSV as an answer-axis run over this session's cases, kept under *label*."""
        from .results import import_studio_results

        report = import_studio_results(Path(results), self.cases)
        self.runs[label] = report
        return report

    def agreement(self, studio: RunRef, *, rater: str | Rater = "grounded", threshold: float | None = None,
                  band: float | None = None, instruction: str | None = None) -> AgreementReport:
        """How well the local grader agrees with Eval Studio's, answer by answer.

        *studio* is an Eval Studio results CSV, or a run already imported
        (a label or a report).
        """
        from .agreement import agreement

        if isinstance(studio, str | Path) and Path(studio).suffix.lower() == ".csv":
            from .results import import_studio_results

            imported = import_studio_results(Path(studio), self.cases)
        else:
            imported = self.report(studio)
        local = rater_for(rater)
        assert local is not None
        return agreement(imported, self.cases, local, threshold=threshold, band=band, instruction=instruction)


def _dataset_plan(value: Any) -> Any:
    from ..evals.dataset_contract import DatasetPlan

    if isinstance(value, DatasetPlan):
        return value
    from ..evals.company_dataset import load_dataset_plan

    if isinstance(value, str | Path):
        import json

        value = json.loads(Path(value).read_text(encoding="utf-8"))
    return load_dataset_plan(dict(value) if isinstance(value, Mapping) else value)


__all__ = ["EvalSession", "ExecHarness", "ImproveLoop", "harness_for", "proposer_for", "rater_for"]
