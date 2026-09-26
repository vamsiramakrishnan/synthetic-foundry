"""The improvement loop: an agent's failures become a revised policy, kept only if it wins where it was not tuned.

One round:

1. the champion (an ``agent`` pack) runs the training cases;
2. its failures are clustered (``autopsy``) into a brief;
3. a harness proposes a revised policy through the pack interview, refused
   with findings until it lints clean;
4. the candidate runs the same training cases and is compared with the
   champion; it must gain at least the delta band on the mean without any
   axis falling by more than the band and without erroring where the
   champion was graded;
5. only then do both run the held-out cases, which the proposer never saw a
   line of; the candidate must gain there too;
6. a candidate that clears both gates becomes the champion; every round,
   promoted or not, leaves a receipt.

The grader is pinned by digest before the first round and checked around
every run: a loop that could move its own measuring stick would be measuring
nothing. Nothing here edits source code; what changes is a pack, which is
content-addressed, linted and replayable.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field

from .. import packkit
from ..models import Model
from ..packkit.authoring import Exchange, author
from ..packkit.resolve import ResolvedPack
from .agents import AgentUnderTest
from .autopsy import autopsy, render_brief
from .contract import EvalCase
from .grader import check_frozen, grader_identity
from .results import Comparison, compare, delta_band, read_run, write_run
from .runner import RunReport, case_set_digest

IMPROVE_SCHEMA = "worldloom.improve/v1"
ROUND_SCHEMA = "worldloom.improve-round/v1"

#: Splits a case can declare that keep it out of training: what the dataset
#: compiler and the foundry call the cases a result is judged on.
HELD_OUT_SPLITS = frozenset({"test", "holdout", "validation"})

Runner = Callable[[Sequence[EvalCase], AgentUnderTest], RunReport]
AgentFor = Callable[[ResolvedPack], AgentUnderTest]


# -- splits -------------------------------------------------------------------


def _declared_split(case: EvalCase) -> str | None:
    for source in (case.dimensions, case.row, case.row.get("dimensions") or {}):
        if isinstance(source, Mapping) and isinstance(source.get("split"), str):
            return str(source["split"])
    return None


def split_cases(cases: Iterable[EvalCase], *, holdout_share: float) -> tuple[tuple[EvalCase, ...], tuple[EvalCase, ...]]:
    """(training, held-out) cases.

    A case that names its split keeps it; one that does not is assigned by a
    stable hash of its id, so the same case lands on the same side in every
    round and every run, whatever order the cases arrive in.
    """
    if not 0 < holdout_share < 1:
        raise ValueError(f"holdout_share must lie strictly between 0 and 1, not {holdout_share}")
    train: list[EvalCase] = []
    held: list[EvalCase] = []
    for case in cases:
        declared = _declared_split(case)
        if declared is not None:
            (held if declared in HELD_OUT_SPLITS else train).append(case)
            continue
        bucket = int(hashlib.sha256(f"improve-split\0{case.id}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        (held if bucket < holdout_share else train).append(case)
    return tuple(train), tuple(held)


# -- gates --------------------------------------------------------------------


class Gate(Model):
    """One comparison judged: passed, with every reason it did not."""

    name: str
    passed: bool
    reasons: tuple[str, ...] = ()
    compared: int = 0
    mean_delta: float = 0.0
    axis_deltas: dict[str, float | None] = Field(default_factory=dict)
    improvements: int = 0
    regressions: int = 0
    newly_errored: tuple[str, ...] = ()


def judge(comparison: Comparison, *, name: str, min_delta: float, strict: bool, max_axis_regression: float) -> Gate:
    """Whether *comparison* (champion to candidate) is a win by the loop's rules."""
    reasons: list[str] = []
    if comparison.grader_mismatch:
        reasons.append("the two runs were graded differently")
    if not comparison.same_case_set:
        reasons.append("the two runs are over different case sets")
    if comparison.compared == 0:
        reasons.append("no case was graded by both runs")
    if comparison.newly_errored:
        reasons.append(f"the candidate errored on {len(comparison.newly_errored)} case(s) the champion was graded on")
    delta = comparison.mean_delta
    if (delta <= min_delta) if strict else (delta < min_delta):
        reasons.append(f"mean delta {delta} is not {'above' if strict else 'at least'} {min_delta}")
    axes = {"plan": comparison.axis_deltas.plan, "trajectory": comparison.axis_deltas.trajectory,
            "outcomes": comparison.axis_deltas.outcomes}
    for axis, value in axes.items():
        if value is not None and value < -max_axis_regression:
            reasons.append(f"the {axis} axis fell by {-value}, more than {max_axis_regression}")
    return Gate(name=name, passed=not reasons, reasons=tuple(reasons), compared=comparison.compared,
                mean_delta=delta, axis_deltas=axes, improvements=len(comparison.improvements),
                regressions=len(comparison.regressions), newly_errored=comparison.newly_errored)


# -- receipts -----------------------------------------------------------------


class RoundReceipt(Model):
    schema_version: str = Field(default=ROUND_SCHEMA, alias="schema")
    round: int
    grader: str
    champion: dict[str, Any]
    candidate: dict[str, Any] | None = None
    #: ``promoted``, ``rejected`` (a gate failed), or why the round stopped
    #: before a candidate could be judged: ``no_failures``, ``questions``,
    #: ``refused``, ``unchanged``.
    decision: str
    reasons: tuple[str, ...] = ()
    brief_digest: str | None = None
    failing: int = 0
    clusters: tuple[str, ...] = ()
    authoring: tuple[dict[str, Any], ...] = ()
    questions: tuple[str, ...] = ()
    train: Gate | None = None
    holdout: Gate | None = None


class ImproveReport(Model):
    schema_version: str = Field(default=IMPROVE_SCHEMA, alias="schema")
    grader: dict[str, Any]
    train_cases: int
    holdout_cases: int
    train_case_set: str
    holdout_case_set: str
    initial: dict[str, Any]
    champion: dict[str, Any]
    rounds: tuple[RoundReceipt, ...]
    promotions: int


def _identity(pack: ResolvedPack) -> dict[str, Any]:
    return {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain)}


def _slug(pack: ResolvedPack) -> str:
    return f"{pack.name}@{pack.digest[:12]}"


# -- the loop -----------------------------------------------------------------


@dataclass
class Improver:
    """Everything a round needs, and the runs it has already paid for.

    ``run`` executes one agent over some cases (the caller decides how: one
    process, many threads, a served endpoint); ``agent_for`` makes the agent
    under test for a policy; ``exchange`` is the proposing harness.
    """

    run: Runner
    agent_for: AgentFor
    exchange: Exchange
    out: Path
    rater: Any = None
    pack_roots: Sequence[str | Path] = ()
    authoring_rounds: int = 4
    _runs: dict[tuple[str, str], RunReport] = field(default_factory=dict)
    _candidates: dict[str, ResolvedPack] = field(default_factory=dict)

    def _pinned_run(self, pack: ResolvedPack, cases: Sequence[EvalCase], label: str, grader: dict[str, Any]) -> RunReport:
        key = (pack.digest, label)
        held = self._runs.get(key)
        if held is not None:
            return held
        directory = self.out / "runs" / _slug(pack) / label
        # A run already on disk for this exact policy, case set and grader is
        # reused, so an interrupted loop resumes without paying for it twice.
        if (directory / "run.json").exists():
            try:
                stored = read_run(directory)
            except ValueError:
                stored = None
            if (stored is not None and stored.case_set == case_set_digest(cases)
                    and (stored.grader or {}).get("digest") == grader["digest"]
                    and (stored.agent_pack or {}).get("digest") == pack.digest):
                self._runs[key] = stored
                return stored
        check_frozen(grader, self.rater)
        report = self.run(cases, self.agent_for(pack))
        check_frozen(grader, self.rater)
        report = report.model_copy(update={"grader": grader,
                                           "agent_pack": report.agent_pack or _identity(pack)})
        write_run(directory, report)
        self._runs[key] = report
        return report

    def _propose(self, champion: ResolvedPack, brief: str, round_number: int, stem: str) -> Any:
        message = packkit.text("evalrun.improve.message", brief=brief, champion=champion.pinned,
                               round=round_number)
        draft = {"schema": "worldloom.pack/v1", "kind": "agent", "name": f"{stem}-r{round_number}",
                 "title": f"{stem}, round {round_number}", "body": champion.data}
        return author("agent", message, self.exchange, name=f"{stem}-r{round_number}",
                      max_rounds=self.authoring_rounds, root=self.out / "packs",
                      roots=tuple(self.pack_roots), replace=True, draft=draft)

    def improve(self, champion: ResolvedPack, train: Sequence[EvalCase], holdout: Sequence[EvalCase], *,
                rounds: int, min_train_delta: float | None = None, min_holdout_delta: float | None = None,
                max_axis_regression: float | None = None) -> ImproveReport:
        if not train:
            raise ValueError("no training cases: the loop has nothing to learn from")
        if not holdout:
            raise ValueError("no held-out cases: a candidate could only be judged where it was tuned")
        overlap = {case.id for case in train} & {case.id for case in holdout}
        if overlap:
            raise ValueError(f"{len(overlap)} case(s) are both training and held out, e.g. {sorted(overlap)[0]}")
        band = delta_band()
        min_train = band if min_train_delta is None else min_train_delta
        min_held = float(packkit.policy("evalrun.improve.min_holdout_delta")) if min_holdout_delta is None else min_holdout_delta
        max_fall = band if max_axis_regression is None else max_axis_regression
        grader = grader_identity(self.rater)
        stem = champion.name.split("-r")[0][:48]
        initial = champion
        receipts: list[RoundReceipt] = []
        self.out.mkdir(parents=True, exist_ok=True)
        for number in range(1, rounds + 1):
            receipt = self._round(number, champion, train, holdout, grader, stem,
                                  min_train=min_train, min_held=min_held, max_fall=max_fall)
            receipts.append(receipt)
            _write(self.out / "rounds" / f"{number:03d}.json", receipt.model_dump(mode="json", by_alias=True))
            if receipt.decision == "promoted":
                assert receipt.candidate is not None
                champion = self._candidates[receipt.candidate["digest"]]
            elif receipt.decision in {"no_failures", "questions"}:
                # Nothing left to learn from this set, or the operator has
                # to answer before a harness can go on: another round would
                # repeat this one.
                break
        report = ImproveReport(grader=grader, train_cases=len(train), holdout_cases=len(holdout),
                               train_case_set=case_set_digest(train), holdout_case_set=case_set_digest(holdout),
                               initial=_identity(initial), champion=_identity(champion), rounds=tuple(receipts),
                               promotions=sum(item.decision == "promoted" for item in receipts))
        _write(self.out / "improve.json", report.model_dump(mode="json", by_alias=True))
        return report

    def _round(self, number: int, champion: ResolvedPack, train: Sequence[EvalCase], holdout: Sequence[EvalCase],
               grader: dict[str, Any], stem: str, *, min_train: float, min_held: float, max_fall: float) -> RoundReceipt:
        base = {"round": number, "grader": grader["digest"], "champion": _identity(champion)}
        champion_train = self._pinned_run(champion, train, "train", grader)
        found = autopsy(champion_train, cases=train)
        if found.failing == 0:
            return RoundReceipt(**base, decision="no_failures",
                                reasons=("the champion passes every training case; escalate the curriculum",))
        brief = render_brief(found)
        clusters = tuple(cluster.key for cluster in found.clusters)
        brief_digest = hashlib.sha256(brief.encode()).hexdigest()[:16]
        common = {**base, "brief_digest": brief_digest, "failing": found.failing, "clusters": clusters}
        authored = self._propose(champion, brief, number, stem)
        rounds = tuple(authored.rounds)
        verdict = authored.verdict
        if verdict.status == "questions":
            return RoundReceipt(**common, decision="questions", authoring=rounds, questions=verdict.questions,
                                reasons=("the proposer asked questions only the operator can answer",))
        if verdict.status != "accepted" or verdict.resolved is None:
            return RoundReceipt(**common, decision="refused", authoring=rounds, reasons=tuple(verdict.findings[:12]))
        candidate: ResolvedPack = verdict.resolved
        if candidate.data == champion.data:
            return RoundReceipt(**common, decision="unchanged", authoring=rounds, candidate=_identity(candidate),
                                reasons=("the proposal restates the champion's policy",))
        self._candidates[candidate.digest] = candidate
        candidate_train = self._pinned_run(candidate, train, "train", grader)
        train_gate = judge(compare(champion_train, candidate_train), name="train", min_delta=min_train,
                           strict=False, max_axis_regression=max_fall)
        if not train_gate.passed:
            return RoundReceipt(**common, decision="rejected", authoring=rounds, candidate=_identity(candidate),
                                train=train_gate, reasons=train_gate.reasons)
        champion_held = self._pinned_run(champion, holdout, "holdout", grader)
        candidate_held = self._pinned_run(candidate, holdout, "holdout", grader)
        held_gate = judge(compare(champion_held, candidate_held), name="holdout", min_delta=min_held,
                          strict=True, max_axis_regression=max_fall)
        return RoundReceipt(**common, decision="promoted" if held_gate.passed else "rejected", authoring=rounds,
                            candidate=_identity(candidate), train=train_gate, holdout=held_gate,
                            reasons=held_gate.reasons)


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def improve(champion: ResolvedPack, cases: Sequence[EvalCase], *, run: Runner, agent_for: AgentFor,
            exchange: Exchange, out: Path, rater: Any = None, holdout: Sequence[EvalCase] | None = None,
            holdout_share: float | None = None, rounds: int | None = None,
            pack_roots: Sequence[str | Path] = (), authoring_rounds: int | None = None,
            min_train_delta: float | None = None, min_holdout_delta: float | None = None,
            max_axis_regression: float | None = None) -> ImproveReport:
    """Run the loop from *champion* over *cases*; the held-out cases are *holdout* or a stable share of *cases*.

    A separate *holdout* (cases compiled from fresh seeds) is the stronger
    test: a policy that learned this company rather than the task fails
    there. Without one, a share of *cases* is held back by case id.
    """
    if holdout is None:
        share = float(packkit.policy("evalrun.improve.holdout_share")) if holdout_share is None else holdout_share
        train, held = split_cases(cases, holdout_share=share)
    else:
        train, held = tuple(cases), tuple(holdout)
    improver = Improver(run=run, agent_for=agent_for, exchange=exchange, out=out, rater=rater,
                        pack_roots=pack_roots,
                        authoring_rounds=int(packkit.policy("evalrun.improve.authoring_rounds"))
                        if authoring_rounds is None else authoring_rounds)
    return improver.improve(champion, train, held,
                            rounds=int(packkit.policy("evalrun.improve.rounds")) if rounds is None else rounds,
                            min_train_delta=min_train_delta, min_holdout_delta=min_holdout_delta,
                            max_axis_regression=max_axis_regression)


__all__ = ["HELD_OUT_SPLITS", "IMPROVE_SCHEMA", "ROUND_SCHEMA", "Gate", "ImproveReport", "Improver", "RoundReceipt",
           "improve", "judge", "split_cases"]
