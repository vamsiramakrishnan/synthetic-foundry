"""The meta loop: the improver improved by the machinery it drives.

``improve`` revises the policy of an agent under test. The harness writing
those revisions (the *proposer*) runs under a policy too: an ``agent`` pack
whose standing instruction, planning note and skills reach it ahead of the
pack interview (``packkit.authoring.with_proposer``). This module revises
that pack with the same discipline ``improve`` applies to agents.

**Score.** A proposer policy is worth the held-out gain it produces. For each
improvement task (an agent champion, training and held-out cases, and how to
run the agent under a policy) ``improve`` runs with the proposer under that
policy; the task's score is the mean held-out delta of the agent champion
the loop ended with over the one it started from, measured by running both
on the task's held-out cases (0 when nothing was promoted). The proposer's
score is the mean over tasks. Its promotion rate and the proposals the lint
refused are kept beside it as secondary signals; they never decide.

**Meta round.**

1. The proposer champion is scored on the training tasks.
2. Its outcomes are read into a brief: each task's rounds, which were
   rejected and why, the findings that refused its proposals, the questions
   it asked, and what earlier meta rounds tried.
3. A meta-proposer revises the proposer pack through the pack interview, by
   diff against its tree. By default it is the same harness running under
   the current proposer champion: the improver revises itself.
4. The candidate is scored on the same training tasks and must gain there
   (paired over tasks: ``compare_scores``). Only then are both scored on
   the meta-held-out tasks, which no brief ever describes; the candidate
   must gain there too.
5. A candidate that clears both gates becomes the proposer champion. Every
   meta round leaves ``meta/rounds/NNN.json`` (and the proposer diff as
   ``NNN.diff``).

**Guards.** The meta loop changes one thing, the proposer pack. Every task's
grader is pinned by digest before the first score and checked around every
one; its case sets are copied and digested once and re-checked; the agent
packs and their held-out cases are read, never written: every inner loop
writes under ``<out>/meta/tasks``. A proposer candidate is linted like any
agent pack (credentials, fence markers, size) and, since only ``system``,
``planning``, ``skills`` and ``files`` reach a proposer, a candidate that
sets anything else is refused with findings through the same interview
(``proposer_findings``): a change nothing reads would be scored as noise.
No meta-held-out task name, case or result reaches the meta-proposer.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field

from .. import packkit
from ..execseam import ExecError
from ..models import Model
from ..packkit import diffs
from ..packkit.authoring import Exchange, author, with_proposer
from ..packkit.resolve import ResolvedPack
from .contract import EvalCase
from .grader import check_frozen, grader_identity
from .harness import skills_cache_in
from .improve import AgentFor, ImproveReport, Runner, improve
from .results import compare, delta_band
from .runner import RunReport, case_set_digest

META_SCHEMA = "worldloom.meta/v1"
META_ROUND_SCHEMA = "worldloom.meta-round/v1"

#: A task's name is a directory under ``meta/tasks``.
_TASK_NAME = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
#: A meta round's suffix on a proposer candidate's name: ``-m2``.
_META_SUFFIX = re.compile(r"-m\d+(-[0-9a-f]+)?$")
#: ``improve`` arguments the meta loop sets itself for every task.
_RESERVED = frozenset({"champion", "cases", "run", "agent_for", "exchange", "out", "rater", "holdout",
                       "holdout_share", "pack_roots"})
#: What a failing meta-proposer raises (the same set ``improve`` treats as a proposer failure).
_PROPOSER_ERRORS: tuple[type[Exception], ...] = (ExecError, ValueError, OSError, TimeoutError)


# -- tasks --------------------------------------------------------------------


class TaskOverlap(ValueError):
    """A meta-held-out task shares a case set with a training task, so it is not held out."""


@dataclass(frozen=True)
class ImprovementTask:
    """One improvement problem a proposer is scored on.

    ``run`` and ``agent_for`` are what ``improve`` takes; ``rater`` is the
    task's grader, pinned for the whole meta loop.
    """

    name: str
    champion: ResolvedPack
    train: tuple[EvalCase, ...]
    holdout: tuple[EvalCase, ...]
    run: Runner
    agent_for: AgentFor
    rater: Any = None
    pack_roots: tuple[str | Path, ...] = ()

    def __post_init__(self) -> None:
        if not _TASK_NAME.match(self.name):
            raise ValueError(f"task name {self.name!r}: lower-case letters, digits, '.', '_' or '-', at most 64")
        object.__setattr__(self, "train", tuple(self.train))
        object.__setattr__(self, "holdout", tuple(self.holdout))
        object.__setattr__(self, "pack_roots", tuple(self.pack_roots))
        if not self.train:
            raise ValueError(f"task {self.name}: no training cases")
        if not self.holdout:
            raise ValueError(f"task {self.name}: no held-out cases")


# -- receipts -----------------------------------------------------------------


class RoundSummary(Model):
    """One inner ``improve`` round, as the meta brief reads it."""

    round: int
    decision: str
    reasons: tuple[str, ...] = ()
    #: Findings of every refused authoring round in it.
    refused: tuple[str, ...] = ()
    questions: tuple[str, ...] = ()
    train_delta: float | None = None
    holdout_delta: float | None = None


class TaskScore(Model):
    """What one proposer policy produced on one task."""

    task: str
    proposer: dict[str, Any]
    initial: dict[str, Any]
    final: dict[str, Any]
    #: Mean held-out delta of ``final`` over ``initial``; 0 when nothing was promoted.
    gain: float
    rounds: int
    promotions: int
    promotion_rate: float
    #: Authoring rounds the lint (or the proposer review) refused.
    refusals: int
    summaries: tuple[RoundSummary, ...] = ()
    grader: str
    train_case_set: str
    holdout_case_set: str
    options: str


class ProposerScore(Model):
    """One proposer policy scored over a set of tasks."""

    proposer: dict[str, Any]
    split: str
    tasks: tuple[TaskScore, ...]
    mean_gain: float
    promotion_rate: float
    refusals: int


class MetaGate(Model):
    """A paired comparison over tasks, judged: passed, with every reason it did not."""

    name: str
    passed: bool
    reasons: tuple[str, ...] = ()
    compared: int = 0
    mean_delta: float = 0.0
    task_deltas: dict[str, float] = Field(default_factory=dict)
    improvements: int = 0
    regressions: int = 0


class MetaRoundReceipt(Model):
    schema_version: str = Field(default=META_ROUND_SCHEMA, alias="schema")
    round: int
    champion: dict[str, Any]
    candidate: dict[str, Any] | None = None
    #: ``promoted``, ``rejected`` (a gate failed), or why no candidate was
    #: judged: ``no_failures``, ``questions``, ``refused``, ``unchanged`` or
    #: ``proposer_error`` (the meta-proposer failed; ``reasons`` holds why).
    decision: str
    reasons: tuple[str, ...] = ()
    brief_digest: str | None = None
    meta_proposer: dict[str, Any] | None = None
    authoring: tuple[dict[str, Any], ...] = ()
    questions: tuple[str, ...] = ()
    champion_train: ProposerScore
    candidate_train: ProposerScore | None = None
    champion_holdout: ProposerScore | None = None
    candidate_holdout: ProposerScore | None = None
    train: MetaGate | None = None
    holdout: MetaGate | None = None
    diff: str | None = None
    diff_hunks: int = 0
    graders: dict[str, str] = Field(default_factory=dict)


class MetaReport(Model):
    schema_version: str = Field(default=META_SCHEMA, alias="schema")
    initial: dict[str, Any]
    champion: dict[str, Any]
    tasks: tuple[str, ...]
    holdout_tasks: tuple[str, ...]
    graders: dict[str, str]
    case_sets: dict[str, dict[str, str]]
    rounds: tuple[MetaRoundReceipt, ...]
    promotions: int


# -- the comparison -----------------------------------------------------------


def compare_scores(champion: ProposerScore, candidate: ProposerScore, *, name: str, min_delta: float, strict: bool,
                   max_task_regression: float) -> MetaGate:
    """Whether *candidate* beats *champion* task by task, by ``improve.judge``'s rules.

    The pairs are the tasks both were scored on. The mean of the per-task
    gain deltas must clear *min_delta* (strictly when *strict*), no task may
    fall by more than *max_task_regression*, and both must have been scored
    on the same tasks. This is the one place a noise-aware comparison would
    replace.
    """
    mine = {item.task: item.gain for item in champion.tasks}
    theirs = {item.task: item.gain for item in candidate.tasks}
    reasons: list[str] = []
    if set(mine) != set(theirs):
        reasons.append("the two proposers were scored on different tasks")
    shared = sorted(set(mine) & set(theirs))
    deltas = {task: theirs[task] - mine[task] for task in shared}
    if not shared:
        reasons.append("no task was scored for both proposers")
    delta = sum(deltas.values()) / len(deltas) if deltas else 0.0
    if (delta <= min_delta) if strict else (delta < min_delta):
        reasons.append(f"mean gain delta {delta} is not {'above' if strict else 'at least'} {min_delta}")
    for task, value in sorted(deltas.items()):
        if value < -max_task_regression:
            reasons.append(f"task {task} fell by {-value}, more than {max_task_regression}")
    band = delta_band()
    return MetaGate(name=name, passed=not reasons, reasons=tuple(reasons), compared=len(shared), mean_delta=delta,
                    task_deltas=deltas, improvements=sum(value > band for value in deltas.values()),
                    regressions=sum(value < -band for value in deltas.values()))


# -- the proposer's own lint --------------------------------------------------


def proposer_findings(pack: ResolvedPack) -> list[str]:
    """What an ``agent`` pack sets that a proposer never reads.

    A proposer answers the pack interview: its ``system``, ``planning``,
    ``skills`` and skill tree reach it, while turn and plan rule overlays,
    tool advice and a turn budget belong to an evalrun agent and would
    change nothing. A candidate differing only there would be scored as
    noise, so it is refused with findings instead.
    """
    body = pack.body
    findings: list[str] = []
    for key in ("turn_rules", "plan_rules", "tools"):
        if getattr(body, key):
            findings.append(f"{key}: a proposer answers the pack interview, not an evalrun turn, so this field "
                            "changes nothing; revise `system`, `planning`, `skills` or `skills/` instead")
    if body.max_turns is not None:
        findings.append("max_turns: a proposer has no turn budget; remove it")
    return findings


def lint_proposer(pack: ResolvedPack, *, roots: Sequence[str | Path] = ()) -> list[str]:
    """Every finding for a proposer policy: the ``agent`` lint, then ``proposer_findings``."""
    from .policy import require

    require(pack)
    return [*packkit.lint(pack, roots=tuple(roots)), *proposer_findings(pack)]


# -- the loop -----------------------------------------------------------------


def _identity(pack: ResolvedPack) -> dict[str, Any]:
    return {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain)}


def _slug(pack: ResolvedPack) -> str:
    return f"{pack.name}@{pack.digest[:12]}"


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str).encode()).hexdigest()[:16]


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _mean(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


@dataclass
class MetaImprover:
    """Everything a meta round needs, and the scores it has already paid for."""

    proposer: Exchange
    tasks: tuple[ImprovementTask, ...]
    holdout_tasks: tuple[ImprovementTask, ...]
    out: Path
    meta_proposer: Exchange | None = None
    pack_roots: tuple[str | Path, ...] = ()
    authoring_rounds: int = 4
    improve_options: dict[str, Any] = field(default_factory=dict)
    _graders: dict[str, dict[str, Any]] = field(default_factory=dict)
    _case_sets: dict[str, dict[str, str]] = field(default_factory=dict)
    _scores: dict[tuple[str, str], TaskScore] = field(default_factory=dict)
    _held_runs: dict[tuple[str, str], RunReport] = field(default_factory=dict)
    _candidates: dict[str, ResolvedPack] = field(default_factory=dict)

    @property
    def _root(self) -> Path:
        return self.out / "meta"

    def _search(self) -> tuple[Path, ...]:
        return (self._root / "packs", *(Path(root) for root in self.pack_roots))

    def pin(self) -> None:
        """Pin every task's grader and case sets before the first score."""
        for task in (*self.tasks, *self.holdout_tasks):
            self._graders[task.name] = grader_identity(task.rater)
            self._case_sets[task.name] = {"train": case_set_digest(task.train),
                                          "holdout": case_set_digest(task.holdout)}

    def _guard(self, task: ImprovementTask) -> None:
        check_frozen(self._graders[task.name], task.rater)
        held = {"train": case_set_digest(task.train), "holdout": case_set_digest(task.holdout)}
        if held != self._case_sets[task.name]:
            raise ValueError(f"task {task.name}: its case sets changed during the meta loop; nothing after that "
                             "is comparable")

    # -- scoring ---------------------------------------------------------------

    def score(self, proposer: ResolvedPack, tasks: Sequence[ImprovementTask], split: str) -> ProposerScore:
        items = tuple(self._task_score(task, proposer) for task in tasks)
        return ProposerScore(proposer=_identity(proposer), split=split, tasks=items,
                             mean_gain=_mean([item.gain for item in items]),
                             promotion_rate=_mean([item.promotion_rate for item in items]),
                             refusals=sum(item.refusals for item in items))

    def _task_score(self, task: ImprovementTask, proposer: ResolvedPack) -> TaskScore:
        key = (task.name, proposer.digest)
        held = self._scores.get(key)
        if held is not None:
            return held
        grader = self._graders[task.name]
        options = _digest(self.improve_options)
        directory = self._root / "tasks" / task.name / _slug(proposer)
        stored = self._stored_score(directory / "score.json", task, proposer, grader["digest"], options)
        if stored is not None:
            self._scores[key] = stored
            return stored
        self._fresh(directory / "improve")
        self._guard(task)
        exchange = with_proposer(self.proposer, proposer, skills_cache=self._root / "skills-cache")
        report = improve(task.champion, task.train, run=task.run, agent_for=task.agent_for, exchange=exchange,
                         out=directory / "improve", rater=task.rater, holdout=task.holdout,
                         pack_roots=task.pack_roots, **self.improve_options)
        self._guard(task)
        gain = self._gain(task, report, directory / "improve")
        self._guard(task)
        summaries = tuple(_summary(receipt) for receipt in report.rounds)
        rounds = len(report.rounds)
        score = TaskScore(task=task.name, proposer=_identity(proposer), initial=dict(report.initial),
                          final=dict(report.champion), gain=gain, rounds=rounds, promotions=report.promotions,
                          promotion_rate=report.promotions / rounds if rounds else 0.0,
                          refusals=sum(entry.get("status") == "refused" for receipt in report.rounds
                                       for entry in receipt.authoring),
                          summaries=summaries, grader=grader["digest"],
                          train_case_set=self._case_sets[task.name]["train"],
                          holdout_case_set=self._case_sets[task.name]["holdout"], options=options)
        _write(directory / "score.json", score.model_dump(mode="json", by_alias=True))
        self._scores[key] = score
        return score

    def _stored_score(self, path: Path, task: ImprovementTask, proposer: ResolvedPack, grader: str,
                      options: str) -> TaskScore | None:
        """A score already on disk for this proposer, task, grader, case sets and options, or ``None``."""
        if not path.is_file():
            return None
        try:
            stored = TaskScore.model_validate(json.loads(path.read_text(encoding="utf-8")))
        except ValueError:
            return None
        if (stored.proposer.get("digest") == proposer.digest and stored.initial.get("digest") == task.champion.digest
                and stored.grader == grader and stored.options == options
                and stored.train_case_set == self._case_sets[task.name]["train"]
                and stored.holdout_case_set == self._case_sets[task.name]["holdout"]):
            return stored
        return None

    @staticmethod
    def _fresh(directory: Path) -> None:
        """An inner loop's directory with no receipts left from an interrupted score.

        ``improve`` continues its round numbering from the receipts it finds,
        so a score interrupted mid-loop would otherwise run more rounds than
        asked. Its runs stay: they are reused by digest and not paid for twice.
        """
        for name in ("rounds", "packs"):
            shutil.rmtree(directory / name, ignore_errors=True)
        (directory / "improve.json").unlink(missing_ok=True)

    def _gain(self, task: ImprovementTask, report: ImproveReport, directory: Path) -> float:
        """The final champion's mean held-out delta over the initial one, run for the purpose; 0 without a promotion."""
        if report.promotions == 0 or report.champion.get("digest") == report.initial.get("digest"):
            return 0.0
        final = packkit.resolve(f"{report.champion['ref']}@{report.champion['digest']}", kind_name="agent",
                                roots=(directory / "packs", *task.pack_roots))
        return compare(self._held_run(task, task.champion), self._held_run(task, final)).mean_delta

    def _held_run(self, task: ImprovementTask, pack: ResolvedPack) -> RunReport:
        key = (task.name, pack.digest)
        held = self._held_runs.get(key)
        if held is None:
            with skills_cache_in(self._root / "skills-cache"):
                agent = task.agent_for(pack)
            held = task.run(task.holdout, agent)
            self._held_runs[key] = held
        return held

    # -- rounds ----------------------------------------------------------------

    def _earlier(self) -> int:
        rounds_dir = self._root / "rounds"
        numbers = [int(path.stem) for path in rounds_dir.glob("*.json") if path.stem.isdigit()] if rounds_dir.is_dir() else []
        return max(numbers, default=0)

    def _candidate_name(self, champion: ResolvedPack, number: int) -> str:
        """``<stem>-m<number>``, or with a short digest when a pack outside this loop's root holds that name."""
        from ..packkit.sources import find

        stem = (_META_SUFFIX.sub("", champion.name) or champion.name)[:48]
        own = (self._root / "packs").resolve()
        name = f"{stem}-m{number}"
        attempt = 0
        while True:
            located = find("agent", name, roots=self._search())
            if located is None or (Path(located.location).resolve().is_relative_to(own) and name != champion.name):
                return name
            attempt += 1
            suffix = hashlib.sha256(f"{champion.digest}\0{number}\0{attempt}".encode()).hexdigest()[:8]
            name = f"{stem}-m{number}-{suffix}"

    def run(self, champion: ResolvedPack, *, rounds: int, min_train_delta: float | None = None,
            min_holdout_delta: float | None = None, max_task_regression: float | None = None) -> MetaReport:
        findings = lint_proposer(champion, roots=self._search())
        if findings:
            from ..cascade import refuse

            refuse(f"proposer {champion.ref}", findings)
        self.pin()
        band = delta_band()
        min_train = band if min_train_delta is None else min_train_delta
        min_held = float(packkit.policy("evalrun.improve.min_holdout_delta")) if min_holdout_delta is None else min_holdout_delta
        max_fall = band if max_task_regression is None else max_task_regression
        initial = champion
        receipts: list[MetaRoundReceipt] = []
        last = self._earlier()
        for number in range(last + 1, last + rounds + 1):
            receipt = self._round(number, champion, receipts, min_train=min_train, min_held=min_held,
                                  max_fall=max_fall)
            receipts.append(receipt)
            _write(self._root / "rounds" / f"{number:03d}.json", receipt.model_dump(mode="json", by_alias=True))
            if receipt.diff:
                (self._root / "rounds" / f"{number:03d}.diff").write_text(receipt.diff, encoding="utf-8", newline="")
            if receipt.decision == "promoted":
                assert receipt.candidate is not None
                champion = self._candidates[receipt.candidate["digest"]]
            elif receipt.decision in {"no_failures", "questions", "proposer_error"}:
                break
        report = MetaReport(initial=_identity(initial), champion=_identity(champion),
                            tasks=tuple(task.name for task in self.tasks),
                            holdout_tasks=tuple(task.name for task in self.holdout_tasks),
                            graders={name: identity["digest"] for name, identity in sorted(self._graders.items())},
                            case_sets=dict(sorted(self._case_sets.items())), rounds=tuple(receipts),
                            promotions=sum(item.decision == "promoted" for item in receipts))
        _write(self._root / "meta.json", report.model_dump(mode="json", by_alias=True))
        return report

    def _round(self, number: int, champion: ResolvedPack, earlier: Sequence[MetaRoundReceipt], *,
               min_train: float, min_held: float, max_fall: float) -> MetaRoundReceipt:
        champion_train = self.score(champion, self.tasks, "train")
        base: dict[str, Any] = {"round": number, "champion": _identity(champion), "champion_train": champion_train,
                                "graders": {name: identity["digest"] for name, identity in sorted(self._graders.items())}}
        if all(summary.decision == "no_failures" for item in champion_train.tasks for summary in item.summaries):
            return MetaRoundReceipt(**base, decision="no_failures",
                                    reasons=("every task's agent passes its training cases; the proposer has "
                                             "nothing to be judged on",))
        brief = render_meta_brief(champion_train, earlier)
        common = {**base, "brief_digest": hashlib.sha256(brief.encode()).hexdigest()[:16]}
        # The recursion: unless told otherwise, the harness that proposes
        # agent revisions proposes this revision too, under the policy it is
        # revising.
        exchange = (self.meta_proposer if self.meta_proposer is not None
                    else with_proposer(self.proposer, champion, skills_cache=self._root / "skills-cache"))
        meta_identity = getattr(exchange, "policy", None)
        if meta_identity is not None:
            common["meta_proposer"] = _identity(meta_identity)
        name = self._candidate_name(champion, number)
        message = packkit.text("evalrun.meta.message", brief=brief, champion=champion.pinned, round=number) \
            + "\n\n" + packkit.text("evalrun.improve.rule.diff")
        draft = {"schema": "worldloom.pack/v1", "kind": "agent", "name": name,
                 "title": f"{champion.title or champion.name}, meta round {number}", "body": champion.data}
        failure: list[Exception] = []

        def guarded(payload: dict[str, Any]) -> dict[str, Any]:
            try:
                return exchange(payload)
            except _PROPOSER_ERRORS as error:
                failure.append(error)
                raise _MetaProposerFailed from error

        try:
            authored = author("agent", message, guarded, name=name, max_rounds=self.authoring_rounds,
                              root=self._root / "packs", roots=self.pack_roots, replace=True, draft=draft,
                              review=proposer_findings)
        except _MetaProposerFailed:
            error = failure[-1]
            return MetaRoundReceipt(**common, decision="proposer_error",
                                    reasons=(f"the meta-proposer failed: {type(error).__name__}: {error}",))
        rounds = tuple(authored.rounds)
        verdict = authored.verdict
        if verdict.status == "questions":
            return MetaRoundReceipt(**common, decision="questions", authoring=rounds, questions=verdict.questions,
                                    reasons=("the meta-proposer asked questions only the operator can answer",))
        if verdict.status != "accepted" or verdict.resolved is None:
            return MetaRoundReceipt(**common, decision="refused", authoring=rounds,
                                    reasons=tuple(verdict.findings[:12]))
        candidate = verdict.resolved
        proposed = _diff(champion, candidate)
        if candidate.data == champion.data or not proposed:
            return MetaRoundReceipt(**common, decision="unchanged", authoring=rounds, candidate=_identity(candidate),
                                    reasons=("the proposal restates the proposer champion's policy",))
        changed: dict[str, Any] = {"diff": proposed, "diff_hunks": len(diffs.hunks(proposed))}
        self._candidates[candidate.digest] = candidate
        candidate_train = self.score(candidate, self.tasks, "train")
        train_gate = compare_scores(champion_train, candidate_train, name="train", min_delta=min_train, strict=False,
                                    max_task_regression=max_fall)
        if not train_gate.passed:
            return MetaRoundReceipt(**common, **changed, decision="rejected", authoring=rounds,
                                    candidate=_identity(candidate), candidate_train=candidate_train,
                                    train=train_gate, reasons=train_gate.reasons)
        champion_held = self.score(champion, self.holdout_tasks, "holdout")
        candidate_held = self.score(candidate, self.holdout_tasks, "holdout")
        held_gate = compare_scores(champion_held, candidate_held, name="holdout", min_delta=min_held, strict=True,
                                   max_task_regression=max_fall)
        return MetaRoundReceipt(**common, **changed, decision="promoted" if held_gate.passed else "rejected",
                                authoring=rounds, candidate=_identity(candidate), candidate_train=candidate_train,
                                champion_holdout=champion_held, candidate_holdout=candidate_held, train=train_gate,
                                holdout=held_gate, reasons=held_gate.reasons)


class _MetaProposerFailed(Exception):
    """The meta-proposer failed; the error is kept by the round that called it."""


def _diff(champion: ResolvedPack, candidate: ResolvedPack) -> str:
    codec = packkit.kind("agent")
    assert codec.to_tree is not None
    return diffs.render(codec.to_tree(champion.data), codec.to_tree(candidate.data))


def _summary(receipt: Any) -> RoundSummary:
    refused = [finding for entry in receipt.authoring if entry.get("status") == "refused"
               for finding in entry.get("findings", ())]
    train = getattr(receipt, "train", None)
    held = getattr(receipt, "holdout", None)
    return RoundSummary(round=receipt.round, decision=receipt.decision, reasons=tuple(receipt.reasons[:3]),
                        refused=tuple(refused[:6]), questions=tuple(receipt.questions),
                        train_delta=getattr(train, "mean_delta", None), holdout_delta=getattr(held, "mean_delta", None))


def render_meta_brief(score: ProposerScore, earlier: Sequence[MetaRoundReceipt] = ()) -> str:
    """What the meta-proposer is shown: the champion's training-task outcomes, and earlier meta rounds.

    Built from training tasks only; a meta-held-out task never appears. An
    inner round's held-out delta does appear, as a number: that gain is the
    training signal of the meta loop, and no held-out case id comes with it.
    """
    lines = [f"Proposer {score.proposer['ref']}@{str(score.proposer['digest'])[:12]}: mean held-out gain "
             f"{score.mean_gain} over {len(score.tasks)} task(s); promotion rate {score.promotion_rate}; "
             f"{score.refusals} refused proposal(s)."]
    for item in score.tasks:
        lines.append(f"\nTask {item.task}: gain {item.gain}; {item.promotions} of {item.rounds} round(s) promoted.")
        for summary in item.summaries:
            deltas = ", ".join(f"{label} delta {value}" for label, value in
                               (("train", summary.train_delta), ("held-out", summary.holdout_delta)) if value is not None)
            lines.append(f"- round {summary.round}: {summary.decision}" + (f" ({deltas})" if deltas else ""))
            lines += [f"  - why: {reason}" for reason in summary.reasons if summary.decision != "promoted"]
            lines += [f"  - refused: {finding}" for finding in summary.refused]
            lines += [f"  - asked: {question}" for question in summary.questions]
    if earlier:
        lines.append("\nEarlier meta rounds:")
        for receipt in earlier:
            candidate = f" {receipt.candidate['ref']}" if receipt.candidate else ""
            why = f": {'; '.join(receipt.reasons[:2])}" if receipt.reasons else ""
            lines.append(f"- meta round {receipt.round}{candidate}: {receipt.decision}{why}")
    return "\n".join(lines) + "\n"


def improve_proposer(proposer_champion: ResolvedPack, *, tasks: Sequence[ImprovementTask],
                     holdout_tasks: Sequence[ImprovementTask], proposer: Exchange, out: str | Path,
                     meta_rounds: int = 1, meta_proposer: Exchange | None = None,
                     pack_roots: Sequence[str | Path] = (), authoring_rounds: int | None = None,
                     min_train_delta: float | None = None, min_holdout_delta: float | None = None,
                     max_task_regression: float | None = None, **improve_options: Any) -> MetaReport:
    """Improve the proposer policy *proposer_champion* by the held-out gain it produces on *tasks*.

    *proposer* is the proposing harness with no policy of its own (any
    exchange); each proposer policy scored runs it under that policy. A
    candidate must gain on *tasks* and then on *holdout_tasks*, which the
    meta-proposer never hears about. *meta_proposer* revises the proposer
    pack; by default it is *proposer* under the current proposer champion.
    ``improve_options`` go to every inner ``improve`` call unchanged
    (``rounds``, ``ablate``, ...).
    """
    if meta_rounds < 1:
        raise ValueError("meta_rounds must be at least 1")
    reserved = sorted(_RESERVED & set(improve_options))
    if reserved:
        raise ValueError(f"improve options {', '.join(reserved)} are set by the meta loop for each task")
    train, held = tuple(tasks), tuple(holdout_tasks)
    if not train:
        raise ValueError("no improvement tasks: a proposer is scored by the agents it improves")
    if not held:
        raise ValueError("no meta-held-out tasks: a proposer could only be judged where it was tuned")
    names = [task.name for task in (*train, *held)]
    if len(set(names)) != len(names):
        raise ValueError("task names must be unique across the training and meta-held-out tasks")
    trained = {digest: task.name for task in train
               for digest in (case_set_digest(task.train), case_set_digest(task.holdout))}
    for task in held:
        for digest in (case_set_digest(task.train), case_set_digest(task.holdout)):
            if digest in trained:
                raise TaskOverlap(f"meta-held-out task {task.name} shares a case set with training task "
                                 f"{trained[digest]}; a held-out task must be one the proposer never saw")
    loop = MetaImprover(proposer=proposer, tasks=train, holdout_tasks=held, out=Path(out),
                        meta_proposer=meta_proposer, pack_roots=tuple(pack_roots),
                        authoring_rounds=int(packkit.policy("evalrun.improve.authoring_rounds"))
                        if authoring_rounds is None else authoring_rounds,
                        improve_options=dict(improve_options))
    return loop.run(proposer_champion, rounds=meta_rounds, min_train_delta=min_train_delta,
                    min_holdout_delta=min_holdout_delta, max_task_regression=max_task_regression)


__all__ = ["META_ROUND_SCHEMA", "META_SCHEMA", "ImprovementTask", "MetaGate", "MetaImprover", "MetaReport",
           "MetaRoundReceipt", "ProposerScore", "RoundSummary", "TaskOverlap", "TaskScore", "compare_scores", "improve_proposer",
           "lint_proposer", "proposer_findings", "render_meta_brief"]
