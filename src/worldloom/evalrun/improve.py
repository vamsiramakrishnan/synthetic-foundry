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

Rounds are numbered across every loop run into one output directory: a loop
continues from the last receipt in ``rounds/``, so a second loop never
overwrites an earlier one's receipts, and a candidate is named after its
round (``baseline-r3``). A name already held by a pack a receipt or the
current champion refers to, or by a pack outside the loop's own root, is
never overwritten: the round takes a suffixed name instead
(``baseline-r3-1f2e3d4c``).

Which cases are held out is ``evalrun.splits``'s answer, the same one trace
export and the curriculum use. A training case that declares a held-out
split never trains: without a separate holdout it joins the held-out cases,
and with one it is dropped and counted (``held_out_dropped``). Every run on
the held-out cases is written with ``split="holdout"``, so an export can
refuse it after it leaves the loop.

The proposer works on the champion as a tree of files (the ``agent`` kind's
tree codec: ``policy.json`` plus real skills under ``skills/``) and is asked
for a unified diff against it, so a revision is code generation over the
agent's own skills and every change is reviewable line by line. Each round's
receipt keeps the candidate's diff against the champion (``rounds/NNN.diff``).

A diff is also measurable hunk by hunk. When a candidate passes the training
gate, each hunk is taken out in turn (**ablation**): the candidate without it
is rebuilt, linted and run on the training cases, and a hunk whose removal
costs less than ``evalrun.improve.ablation_tolerance`` of mean score is
dropped. What goes to the held-out cases is the reduced candidate, after it
passes the training gate again; a change that carried no weight on training
never reaches the holdout, where it could only add noise.

An agent under test is stochastic, so one run a side can promote by luck.
With ``repeats`` above 1 (``evalrun.improve.repeats``) each policy runs that
many times over each case set, each repeat an ordinary pinned run in
``runs/<pack>@<digest>/<label>/rep-<i>``, and every comparison, ablation's
included, becomes a paired test over per-case means (``noise.paired``) whose
bootstrap interval the gates judge (``judge_paired``). At 1 the single-run
rules, receipts and run directories are exactly what they always were.

The grader is pinned by digest before the first round and checked around
every run: a loop that could move its own measuring stick would be measuring
nothing. Nothing here edits source code; what changes is a pack, which is
content-addressed, linted and replayable. Generated code lives only in the
agent pack's ``skills/`` tree (``policy.from_tree`` refuses any other path),
and the loop writes only under its output directory and the pack root it
installs candidates into: the materialised skill trees go to
``<out>/skills-cache``.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import Field, SerializerFunctionWrapHandler, model_serializer

from .. import packkit
from ..execseam import ExecError
from ..models import Model
from ..packkit import diffs
from ..packkit.authoring import Exchange, author, check, install
from ..packkit.envelope import PackEnvelope
from ..packkit.resolve import ResolvedPack
from .agents import AgentUnderTest, fingerprint
from .autopsy import autopsy, render_brief
from .contract import EvalCase
from .grader import check_frozen, grader_identity
from .harness import skills_cache_in
from .noise import Interval, PairedComparison, confidence_level, paired, resample_count
from .results import Comparison, compare, delta_band, read_run, write_run
from .runner import RunReport, case_set_digest
from .splits import HELD_OUT_SPLITS, declared_split, is_held_out
from .value import value_weighted_delta

IMPROVE_SCHEMA = "worldloom.improve/v1"
ROUND_SCHEMA = "worldloom.improve-round/v1"

#: A round's suffix on a candidate's name: ``-r3``, or ``-r3-1f2e3d4c`` when
#: the plain name was taken.
_ROUND_SUFFIX = re.compile(r"-r\d+(-[0-9a-f]+)?$")
#: What a failing proposer raises: the exec seam's errors, a harness adapter's
#: refusals and unreadable replies (``ValueError``, JSON errors included), and
#: the operating system's. Anything else is a bug and propagates.
_PROPOSER_ERRORS: tuple[type[Exception], ...] = (ExecError, ValueError, OSError, TimeoutError)

Runner = Callable[[Sequence[EvalCase], AgentUnderTest], RunReport]
AgentFor = Callable[[ResolvedPack], AgentUnderTest]


# -- splits -------------------------------------------------------------------


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
        declared = declared_split(case)
        if declared is not None:
            (held if is_held_out(declared) else train).append(case)
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
    #: The mean delta weighted by each case's value at stake, when the loop
    #: was given values: then it must clear the same bar as the plain mean,
    #: so a candidate cannot win on cheap cases while losing the costly ones.
    value_delta: float | None = None
    #: Runs a side the gate compared. At 1 the fields below are absent from
    #: the receipt, which keeps exactly the bytes a single-run loop wrote.
    repeats: int = 1
    #: The paired bootstrap's interval for ``mean_delta`` over per-case means,
    #: at ``confidence``, with its standard error and the t interval beside it.
    ci_low: float | None = None
    ci_high: float | None = None
    stderr: float | None = None
    t_low: float | None = None
    t_high: float | None = None
    confidence: float | None = None
    #: The pooled run-to-run standard deviation within each side's repeats.
    noise_floor_champion: float | None = None
    noise_floor_candidate: float | None = None
    method: str | None = None
    #: Each axis's paired interval, and the value-weighted one when values were given.
    axis_intervals: dict[str, Interval | None] = Field(default_factory=dict)
    value_interval: Interval | None = None

    @model_serializer(mode="wrap")
    def _single_run_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.repeats == 1:
            for name in _REPEAT_FIELDS:
                data.pop(name, None)
        return data


#: Gate fields that only a comparison over repeats fills, and so only such a
#: receipt carries.
_REPEAT_FIELDS: tuple[str, ...] = ("repeats", "ci_low", "ci_high", "stderr", "t_low", "t_high", "confidence",
                                   "noise_floor_champion", "noise_floor_candidate", "method", "axis_intervals",
                                   "value_interval")


def judge(comparison: Comparison, *, name: str, min_delta: float, strict: bool, max_axis_regression: float,
          values: Mapping[str, Any] | None = None) -> Gate:
    """Whether *comparison* (champion to candidate) is a win by the loop's rules."""
    reasons: list[str] = []
    value_delta: float | None = None
    if values is not None and not comparison.grader_mismatch:
        value_delta = value_weighted_delta(comparison, values)
        if (value_delta <= min_delta) if strict else (value_delta < min_delta):
            reasons.append(f"value-weighted delta {value_delta} is not {'above' if strict else 'at least'} {min_delta}")
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
                regressions=len(comparison.regressions), newly_errored=comparison.newly_errored,
                value_delta=value_delta)


def _clears(estimate: Interval, *, strict: bool, min_delta: float, min_ci: float) -> list[str]:
    """Why *estimate* is not a win: the rules for a comparison over repeats.

    Held out (*strict*), the interval's lower bound must lie above
    *min_delta*. On training, the point estimate must reach *min_delta* and
    the lower bound *min_ci*: the gain is at least the band and
    distinguishable from zero.
    """
    low = estimate.ci_low
    if low is None:
        return [f"only {estimate.cases} case(s) compared; an interval needs two"]
    if strict:
        return [] if low > min_delta else [f"the interval's lower bound {low} is not above {min_delta}"]
    reasons = []
    if estimate.mean < min_delta:
        reasons.append(f"mean delta {estimate.mean} is not at least {min_delta}")
    if low < min_ci:
        reasons.append(f"the interval's lower bound {low} is below {min_ci}: the gain is not distinguishable "
                       "from run-to-run noise")
    return reasons


def judge_paired(comparison: PairedComparison, *, name: str, min_delta: float, strict: bool,
                 max_axis_regression: float, min_ci: float = 0.0) -> Gate:
    """Whether *comparison* (champion repeats to candidate repeats) is a win by the noise-aware rules.

    - Training (not *strict*): the mean of per-case differences is at least
      *min_delta* and the lower bound of its interval at least *min_ci*.
    - Held out (*strict*): the lower bound lies strictly above *min_delta*.
    - The value-weighted difference, when there is one, meets the same rule.
    - An axis fails only when the upper bound of its interval lies below
      ``-max_axis_regression``: a fall the noise cannot explain.
    - A case is newly errored when it errored in a majority of the
      candidate's repeats and in none of the champion's.
    """
    reasons: list[str] = []
    if comparison.grader_mismatch:
        reasons.append("the two runs were graded differently")
    if not comparison.same_case_set:
        reasons.append("the two runs are over different case sets")
    if comparison.compared == 0 or comparison.overall is None:
        reasons.append("no case was graded by both runs")
    if comparison.newly_errored:
        reasons.append(f"the candidate errored on {len(comparison.newly_errored)} case(s) in most of its repeats "
                       "and the champion in none")
    overall = comparison.overall
    if overall is not None:
        reasons.extend(_clears(overall, strict=strict, min_delta=min_delta, min_ci=min_ci))
    if comparison.value is not None:
        reasons.extend(f"value-weighted: {reason}" for reason in _clears(comparison.value, strict=strict,
                                                                         min_delta=min_delta, min_ci=min_ci))
    for axis, estimate in comparison.axes.items():
        if estimate is None:
            continue
        high = estimate.mean if estimate.ci_high is None else estimate.ci_high
        if high < -max_axis_regression:
            reasons.append(f"the {axis} axis fell: its interval's upper bound {high} is below {-max_axis_regression}")
    return Gate(name=name, passed=not reasons, reasons=tuple(reasons), compared=comparison.compared,
                mean_delta=overall.mean if overall is not None else 0.0,
                axis_deltas={axis: None if estimate is None else estimate.mean
                             for axis, estimate in comparison.axes.items()},
                improvements=len(comparison.improvements), regressions=len(comparison.regressions),
                newly_errored=comparison.newly_errored,
                value_delta=None if comparison.value is None else comparison.value.mean,
                repeats=max(comparison.baseline_repeats, comparison.recent_repeats),
                ci_low=None if overall is None else overall.ci_low,
                ci_high=None if overall is None else overall.ci_high,
                stderr=None if overall is None else overall.stderr,
                t_low=None if overall is None else overall.t_low,
                t_high=None if overall is None else overall.t_high,
                confidence=comparison.confidence, noise_floor_champion=comparison.noise_floor_baseline,
                noise_floor_candidate=comparison.noise_floor_recent, method=comparison.method,
                axis_intervals=dict(comparison.axes), value_interval=comparison.value)


# -- receipts -----------------------------------------------------------------


class HunkContribution(Model):
    """One hunk of a candidate's diff, and what taking it out cost on the training cases."""

    index: int
    """1-based position in the proposed diff."""
    file: str
    header: str
    #: ``kept``, ``dropped``, or ``untested`` (past ``evalrun.improve.ablation_max_hunks``).
    decision: str
    #: Mean training score lost without this hunk (the candidate as it stood
    #: then, minus the candidate without it); ``None`` when it was not measured.
    contribution: float | None = None
    reason: str = ""
    #: The interval around ``contribution`` when the loop ran repeats; absent otherwise.
    ci_low: float | None = None
    ci_high: float | None = None

    @model_serializer(mode="wrap")
    def _single_run_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.ci_low is None and self.ci_high is None:
            data.pop("ci_low", None)
            data.pop("ci_high", None)
        return data


class Ablation(Model):
    """The candidate's diff taken apart: which hunks carried the gain."""

    proposed: dict[str, Any]
    """The candidate as the proposer wrote it, before any hunk was dropped."""
    proposed_diff: str
    tolerance: float
    hunks: tuple[HunkContribution, ...] = ()
    #: True when the reduced candidate replaced the proposed one.
    reduced: bool = False
    #: The training gate judged again on the reduced candidate, when one was built.
    reduced_train: Gate | None = None
    reason: str = ""


class RoundReceipt(Model):
    schema_version: str = Field(default=ROUND_SCHEMA, alias="schema")
    round: int
    grader: str
    champion: dict[str, Any]
    candidate: dict[str, Any] | None = None
    #: ``promoted``, ``rejected`` (a gate failed), or why the round stopped
    #: before a candidate could be judged: ``no_failures``, ``questions``,
    #: ``refused``, ``unchanged``, or ``proposer_error`` (the proposing
    #: harness failed or timed out; ``reasons`` holds its error).
    decision: str
    reasons: tuple[str, ...] = ()
    brief_digest: str | None = None
    failing: int = 0
    clusters: tuple[str, ...] = ()
    authoring: tuple[dict[str, Any], ...] = ()
    questions: tuple[str, ...] = ()
    train: Gate | None = None
    holdout: Gate | None = None
    #: The candidate's unified diff against the champion's tree, and its hunk
    #: count; also written beside the receipt as ``rounds/NNN.diff``.
    diff: str | None = None
    diff_hunks: int = 0
    ablation: Ablation | None = None


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
    #: Training cases that declared a held-out split and were dropped because
    #: a separate holdout was given (without one they join the held-out cases).
    held_out_dropped: int = 0
    #: Runs a side for every comparison; absent from ``improve.json`` at 1.
    repeats: int = 1

    @model_serializer(mode="wrap")
    def _single_run_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.repeats == 1:
            data.pop("repeats", None)
        return data


def _identity(pack: ResolvedPack) -> dict[str, Any]:
    return {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain)}


def _slug(pack: ResolvedPack) -> str:
    return f"{pack.name}@{pack.digest[:12]}"


def round_stem(name: str) -> str:
    """*name* without the round suffix a loop gave it: ``ops-runner-r2`` is ``ops-runner``."""
    return (_ROUND_SUFFIX.sub("", name) or name)[:48]


class _ProposerFailed(Exception):
    """The proposing harness failed; carries its error to the round."""

    def __init__(self, error: Exception) -> None:
        super().__init__(str(error))
        self.error = error


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
    ablate: bool = True
    ablation_max_hunks: int = 8
    #: Mean score a hunk must be worth to stay; ``None`` is half the delta band.
    ablation_tolerance: float | None = None
    #: Case id to value at stake (``value.value_table``); when given, every
    #: gate also requires the value-weighted delta to clear its bar.
    values: Mapping[str, Any] | None = None
    #: Values for the held-out cases when they come from another corpus, whose
    #: case ids may repeat the training corpus's for different requests;
    #: ``None`` uses ``values`` for both.
    holdout_values: Mapping[str, Any] | None = None
    #: Runs of each policy over each case set (``evalrun.improve.repeats``).
    #: Above 1 every comparison is a paired test over per-case means
    #: (``noise.paired``) and the gates judge its interval (``judge_paired``);
    #: at 1 the single-run rules and bytes are unchanged.
    repeats: int = 1
    #: The interval's confidence, the bootstrap's resamples, and the least
    #: lower bound a training gain must have; ``None`` reads the policies
    #: ``evalrun.improve.confidence``, ``.bootstrap_resamples`` and ``.min_train_ci``.
    confidence: float | None = None
    resamples: int | None = None
    min_train_ci: float | None = None
    _runs: dict[tuple[str, str, str], RunReport] = field(default_factory=dict)
    _candidates: dict[str, ResolvedPack] = field(default_factory=dict)

    def _pinned_runs(self, pack: ResolvedPack, cases: Sequence[EvalCase], label: str,
                     grader: dict[str, Any]) -> tuple[RunReport, ...]:
        """*pack* over *cases*, ``repeats`` times: each an ordinary pinned run in ``<label>/rep-<i>``.

        At one repeat it is the single run in ``<label>`` itself, where a
        loop without repeats has always written it.
        """
        if self.repeats < 1:
            raise ValueError(f"repeats must be at least 1, not {self.repeats}")
        if self.repeats == 1:
            return (self._pinned_run(pack, cases, label, grader),)
        return tuple(self._pinned_run(pack, cases, label, grader, repeat=index)
                     for index in range(1, self.repeats + 1))

    def _gate(self, champion: Sequence[RunReport], candidate: Sequence[RunReport], *, name: str, min_delta: float,
              strict: bool, max_fall: float, values: Mapping[str, Any] | None) -> Gate:
        """The gate over one comparison: the single-run rules at one repeat, the paired test above it."""
        if self.repeats == 1:
            return judge(compare(champion[0], candidate[0]), name=name, min_delta=min_delta, strict=strict,
                         max_axis_regression=max_fall, values=values)
        return judge_paired(self._paired(champion, candidate, values=values), name=name, min_delta=min_delta,
                            strict=strict, max_axis_regression=max_fall, min_ci=self._min_train_ci())

    def _paired(self, baseline: Sequence[RunReport], recent: Sequence[RunReport], *,
                values: Mapping[str, Any] | None = None) -> PairedComparison:
        return paired(baseline, recent, values=values, confidence=confidence_level(self.confidence),
                      resamples=resample_count(self.resamples))

    def _min_train_ci(self) -> float:
        return float(packkit.policy("evalrun.improve.min_train_ci")) if self.min_train_ci is None else self.min_train_ci

    def _pinned_run(self, pack: ResolvedPack, cases: Sequence[EvalCase], label: str, grader: dict[str, Any],
                    repeat: int | None = None) -> RunReport:
        # The agent is built first, so a run is reused only when this agent
        # made it: one pack run by two different agents (another command,
        # another harness) is two runs. It is built here so a skill tree it
        # materialises lands in this loop's output directory, not the user's
        # cache.
        with skills_cache_in(self.out / "skills-cache"):
            agent = self.agent_for(pack)
        identity = fingerprint(agent)
        # A repeat is its own run: its own cache entry and its own directory
        # under the label's, so a resumed loop reuses every repeat it finished.
        place = label if repeat is None else f"{label}/rep-{repeat}"
        key = (pack.digest, place, json.dumps(identity, sort_keys=True, default=str))
        held = self._runs.get(key)
        if held is not None:
            return held
        directory = self.out / "runs" / _slug(pack) / label
        if repeat is not None:
            directory = directory / f"rep-{repeat}"
        # A run already on disk for this exact policy, agent, case set and
        # grader is reused, so an interrupted loop resumes without paying for
        # it twice.
        if (directory / "run.json").exists():
            try:
                stored = read_run(directory)
            except ValueError:
                stored = None
            if (stored is not None and stored.case_set == case_set_digest(cases)
                    and (stored.grader or {}).get("digest") == grader["digest"]
                    and (stored.agent_pack or {}).get("digest") == pack.digest
                    and stored.agent_identity == identity):
                self._runs[key] = stored
                return stored
        check_frozen(grader, self.rater)
        report = self.run(cases, agent)
        check_frozen(grader, self.rater)
        update: dict[str, Any] = {"grader": grader, "agent_pack": report.agent_pack or _identity(pack),
                                  "agent_identity": identity}
        if label == "holdout":
            # Marked on the run itself, so an export refuses it wherever it goes.
            update["split"] = "holdout"
        report = report.model_copy(update=update)
        write_run(directory, report)
        self._runs[key] = report
        return report

    def _earlier(self) -> tuple[int, frozenset[str]]:
        """The last round number receipted in this output directory, and every pack ref a receipt names.

        A second loop into the same directory continues the numbering, so
        its receipts and candidates never land on an earlier loop's.
        """
        last = 0
        refs: set[str] = set()
        documents: list[Path] = []
        rounds_dir = self.out / "rounds"
        if rounds_dir.is_dir():
            for path in sorted(rounds_dir.glob("*.json")):
                if path.stem.isdigit():
                    last = max(last, int(path.stem))
                documents.append(path)
        documents.append(self.out / "improve.json")
        for path in documents:
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(document, dict):
                continue
            ablation = document.get("ablation")
            for identity in (document.get("champion"), document.get("candidate"), document.get("initial"),
                             ablation.get("proposed") if isinstance(ablation, dict) else None):
                if isinstance(identity, dict) and isinstance(identity.get("ref"), str):
                    refs.add(identity["ref"])
        return last, frozenset(refs)

    def _candidate_name(self, champion: ResolvedPack, stem: str, number: int, protected: frozenset[str]) -> str:
        """A name for round *number*'s candidate that overwrites nothing anyone refers to.

        The plain ``<stem>-r<number>`` is taken when no pack holds it, or when
        the pack holding it is in the loop's own root and neither a receipt
        nor the champion names it (a round interrupted before its receipt,
        which the same name resumes). Otherwise the name carries a short
        digest of the champion and the round, stable across reruns.
        """
        from ..packkit.sources import find

        own = (self.out / "packs").resolve()
        attempt = 0
        name = f"{stem}-r{number}"
        while True:
            located = find(champion.kind, name, roots=self._search())
            if located is None:
                return name
            inside = Path(located.location).resolve().is_relative_to(own)
            if inside and name != champion.name and f"{champion.kind}:{name}" not in protected:
                return name
            attempt += 1
            suffix = hashlib.sha256(f"{champion.digest}\0{number}\0{attempt}".encode()).hexdigest()[:8]
            name = f"{stem}-r{number}-{suffix}"

    def _message(self, champion: ResolvedPack, brief: str, round_number: int) -> str:
        return (packkit.text("evalrun.improve.message", brief=brief, champion=champion.pinned, round=round_number)
                + "\n\n" + packkit.text("evalrun.improve.rule.diff"))

    def _fitted_brief(self, found: Any, champion: ResolvedPack, round_number: int) -> str:
        """The failure brief, as many clusters as the interview's message limit holds, most frequent first.

        A large case set fails in many ways; the brief drops its rarest
        findings (it says how many) before it clips any text, so the proposer
        always gets whole findings, most frequent first.
        """
        from ..packkit.authoring import MAX_MESSAGE, clip_message

        room = MAX_MESSAGE - len(self._message(champion, "", round_number))
        for shown in range(len(found.clusters), 0, -1):
            brief = render_brief(found, clusters=shown)
            if len(brief) <= room:
                return str(brief)
        return clip_message(render_brief(found, clusters=1), room)

    def _propose(self, champion: ResolvedPack, brief: str, round_number: int, stem: str,
                 protected: frozenset[str] = frozenset()) -> Any:
        message = self._message(champion, brief, round_number)
        name = self._candidate_name(champion, stem, round_number, protected)
        draft = {"schema": "worldloom.pack/v1", "kind": "agent", "name": name,
                 "title": f"{stem}, round {round_number}", "body": champion.data}

        def exchange(payload: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.exchange(payload)
            except _PROPOSER_ERRORS as error:
                raise _ProposerFailed(error) from error

        # `replace` only ever overwrites a pack `_candidate_name` found no
        # receipt or champion naming.
        return author("agent", message, exchange, name=name, max_rounds=self.authoring_rounds,
                      root=self.out / "packs", roots=tuple(self.pack_roots), replace=True, draft=draft)

    def improve(self, champion: ResolvedPack, train: Sequence[EvalCase], holdout: Sequence[EvalCase], *,
                rounds: int, min_train_delta: float | None = None, min_holdout_delta: float | None = None,
                max_axis_regression: float | None = None, held_out_dropped: int = 0) -> ImproveReport:
        if not train:
            raise ValueError("no training cases: the loop has nothing to learn from")
        if not holdout:
            raise ValueError("no held-out cases: a candidate could only be judged where it was tuned")
        if self.repeats < 1:
            raise ValueError(f"repeats must be at least 1, not {self.repeats}")
        # A case is the same case when its id, request and row all match: case
        # ids are derived from a request's shape, so a corpus built from a
        # fresh seed reuses ids for different requests over a different world,
        # and those are exactly the held-out cases a fresh seed is for.
        train_keys = {_case_key(case): case.id for case in train}
        overlap = sorted({train_keys[key] for key in map(_case_key, holdout) if key in train_keys})
        if overlap:
            raise ValueError(f"{len(overlap)} case(s) are both training and held out, e.g. {overlap[0]}")
        sealed = sorted(case.id for case in train if is_held_out(declared_split(case)))
        if sealed:
            raise ValueError(f"{len(sealed)} training case(s) declare a held-out split, e.g. {sealed[0]}; "
                             "a case judged on is never trained on")
        band = delta_band()
        min_train = band if min_train_delta is None else min_train_delta
        min_held = float(packkit.policy("evalrun.improve.min_holdout_delta")) if min_holdout_delta is None else min_holdout_delta
        max_fall = band if max_axis_regression is None else max_axis_regression
        grader = grader_identity(self.rater)
        stem = round_stem(champion.name)
        initial = champion
        receipts: list[RoundReceipt] = []
        self.out.mkdir(parents=True, exist_ok=True)
        last, protected = self._earlier()
        for number in range(last + 1, last + rounds + 1):
            protected |= {f"{champion.kind}:{champion.name}"}
            receipt = self._round(number, champion, train, holdout, grader, stem, protected,
                                  min_train=min_train, min_held=min_held, max_fall=max_fall)
            if receipt.candidate is not None:
                protected |= {str(receipt.candidate["ref"])}
            receipts.append(receipt)
            _write(self.out / "rounds" / f"{number:03d}.json", receipt.model_dump(mode="json", by_alias=True))
            if receipt.diff:
                (self.out / "rounds" / f"{number:03d}.diff").write_text(receipt.diff, encoding="utf-8", newline="")
            if receipt.decision == "promoted":
                assert receipt.candidate is not None
                champion = self._candidates[receipt.candidate["digest"]]
            elif receipt.decision in {"no_failures", "questions", "proposer_error"}:
                # Nothing left to learn from this set, the operator has to
                # answer before a harness can go on, or the harness is not
                # answering at all: another round would repeat this one.
                break
        report = ImproveReport(grader=grader, train_cases=len(train), holdout_cases=len(holdout),
                               train_case_set=case_set_digest(train), holdout_case_set=case_set_digest(holdout),
                               initial=_identity(initial), champion=_identity(champion), rounds=tuple(receipts),
                               promotions=sum(item.decision == "promoted" for item in receipts),
                               held_out_dropped=held_out_dropped, repeats=self.repeats)
        _write(self.out / "improve.json", report.model_dump(mode="json", by_alias=True))
        return report

    def _round(self, number: int, champion: ResolvedPack, train: Sequence[EvalCase], holdout: Sequence[EvalCase],
               grader: dict[str, Any], stem: str, protected: frozenset[str] = frozenset(), *,
               min_train: float, min_held: float, max_fall: float) -> RoundReceipt:
        base = {"round": number, "grader": grader["digest"], "champion": _identity(champion)}
        champion_train = self._pinned_runs(champion, train, "train", grader)
        # The brief is the first repeat's failures: the proposer is shown one
        # run, as it always was, and the repeats only sharpen the judging.
        found = autopsy(champion_train[0], cases=train)
        if found.failing == 0:
            return RoundReceipt(**base, decision="no_failures",
                                reasons=("the champion passes every training case; escalate the curriculum",))
        brief = self._fitted_brief(found, champion, number)
        clusters = tuple(cluster.key for cluster in found.clusters)
        brief_digest = hashlib.sha256(brief.encode()).hexdigest()[:16]
        common = {**base, "brief_digest": brief_digest, "failing": found.failing, "clusters": clusters}
        try:
            authored = self._propose(champion, brief, number, stem, protected)
        except _ProposerFailed as failure:
            return RoundReceipt(**common, decision="proposer_error",
                                reasons=(f"the proposer failed: {type(failure.error).__name__}: {failure.error}",))
        rounds = tuple(authored.rounds)
        verdict = authored.verdict
        if verdict.status == "questions":
            return RoundReceipt(**common, decision="questions", authoring=rounds, questions=verdict.questions,
                                reasons=("the proposer asked questions only the operator can answer",))
        if verdict.status != "accepted" or verdict.resolved is None:
            return RoundReceipt(**common, decision="refused", authoring=rounds, reasons=tuple(verdict.findings[:12]))
        candidate: ResolvedPack = verdict.resolved
        proposed_diff = _diff(champion, candidate)
        if candidate.data == champion.data or not proposed_diff:
            return RoundReceipt(**common, decision="unchanged", authoring=rounds, candidate=_identity(candidate),
                                reasons=("the proposal restates the champion's policy",))
        changed: dict[str, Any] = {"diff": proposed_diff, "diff_hunks": len(diffs.hunks(proposed_diff))}
        self._candidates[candidate.digest] = candidate
        candidate_train = self._pinned_runs(candidate, train, "train", grader)
        train_gate = self._gate(champion_train, candidate_train, name="train", min_delta=min_train, strict=False,
                                max_fall=max_fall, values=self.values)
        if not train_gate.passed:
            return RoundReceipt(**common, **changed, decision="rejected", authoring=rounds,
                                candidate=_identity(candidate), train=train_gate, reasons=train_gate.reasons)
        ablation = None
        if self.ablate:
            candidate, candidate_train, ablation = self._ablate(
                champion, candidate, champion_train, candidate_train, train, grader,
                min_train=min_train, max_fall=max_fall)
            if ablation.reduced:
                assert ablation.reduced_train is not None
                train_gate = ablation.reduced_train
                reduced_diff = _diff(champion, candidate)
                changed = {"diff": reduced_diff, "diff_hunks": len(diffs.hunks(reduced_diff))}
        champion_held = self._pinned_runs(champion, holdout, "holdout", grader)
        candidate_held = self._pinned_runs(candidate, holdout, "holdout", grader)
        held_gate = self._gate(champion_held, candidate_held, name="holdout", min_delta=min_held, strict=True,
                               max_fall=max_fall,
                               values=self.holdout_values if self.holdout_values is not None else self.values)
        return RoundReceipt(**common, **changed, decision="promoted" if held_gate.passed else "rejected",
                            authoring=rounds, candidate=_identity(candidate), train=train_gate, holdout=held_gate,
                            reasons=held_gate.reasons, ablation=ablation)

    def _cost(self, without: Sequence[RunReport],
              with_: Sequence[RunReport]) -> tuple[float, tuple[float | None, float | None] | None]:
        """What *with_* scores above *without*: the mean delta, and its interval over repeats (``None`` at one)."""
        if self.repeats == 1:
            return compare(without[0], with_[0]).mean_delta, None
        estimate = self._paired(without, with_).overall
        if estimate is None:
            return 0.0, (None, None)
        return estimate.mean, (estimate.ci_low, estimate.ci_high)

    def _search(self) -> tuple[Path, ...]:
        return (self.out / "packs", *(Path(root) for root in self.pack_roots))

    def _rebuild(self, like: ResolvedPack, body: dict[str, Any]) -> tuple[ResolvedPack | None, list[str]]:
        """*body* as a pack named like *like*: resolved and linted, never stored."""
        envelope = PackEnvelope(kind=like.kind, name=like.name, title=like.title, description=like.description,
                                body=body)
        resolved, findings = check(envelope, roots=self._search(), into=self.out / "packs")
        return resolved, list(findings)

    def _ablate(self, champion: ResolvedPack, candidate: ResolvedPack, champion_train: Sequence[RunReport],
                candidate_train: Sequence[RunReport], train: Sequence[EvalCase], grader: dict[str, Any], *,
                min_train: float, max_fall: float) -> tuple[ResolvedPack, tuple[RunReport, ...], Ablation]:
        """The candidate with every hunk that carried less than the tolerance taken out, one at a time.

        Hunks are tried in the diff's order against the candidate as it
        stands after the earlier drops, so two hunks that only work together
        are not both dropped for each looking useless alone. The last hunk
        left is never dropped: without it the candidate is the champion. The
        reduced candidate is judged by the training gate again and replaces
        the proposed one only if it still passes.

        Over repeats, a hunk's contribution is the paired mean of the
        candidate as it stands minus the candidate without the hunk, and the
        hunk is dropped only when the upper bound of that interval lies below
        the tolerance: it is kept unless the runs show it carries less.
        """
        codec = packkit.kind(candidate.kind)
        assert codec.to_tree is not None and codec.from_tree is not None
        tolerance = delta_band() / 2 if self.ablation_tolerance is None else self.ablation_tolerance
        base = codec.to_tree(champion.data)
        proposed_diff = diffs.render(base, codec.to_tree(candidate.data))
        every = diffs.hunks(proposed_diff)
        keep = list(range(len(every)))
        current, current_run = candidate, tuple(candidate_train)
        records: list[HunkContribution] = []
        for position, hunk in enumerate(every):
            if position >= self.ablation_max_hunks:
                records.append(_contribution(hunk, position, decision="untested",
                                                reason="past the policy `evalrun.improve.ablation_max_hunks`"))
                continue
            remaining = [index for index in keep if index != position]
            if not remaining:
                cost = self._cost(champion_train, current_run)[0]
                records.append(_contribution(hunk, position, decision="kept", contribution=cost,
                                                reason="the last hunk left; without it the candidate is the champion"))
                continue
            try:
                body = codec.from_tree(diffs.apply(base, diffs.join(every[index] for index in remaining)))
            except ValueError as error:
                records.append(_contribution(hunk, position, decision="kept",
                                                reason=f"the rest does not apply without it: {error}"))
                continue
            trial, findings = self._rebuild(candidate, body)
            if trial is None or findings:
                records.append(_contribution(hunk, position, decision="kept",
                                                reason=f"the rest does not lint without it: {'; '.join(findings[:2])}"))
                continue
            trial_run = self._pinned_runs(trial, train, "train", grader)
            cost, bounds = self._cost(trial_run, current_run)
            # One run a side: the measured cost against the tolerance. Over
            # repeats: the upper bound of its interval, so a hunk goes only
            # when the runs show it carries less than the tolerance.
            low, high = (None, None) if bounds is None else bounds
            ceiling = cost if high is None else high
            if ceiling < tolerance:
                keep = remaining
                current, current_run = trial, trial_run
                why = (f"removing it cost {cost}, under the tolerance {tolerance}" if bounds is None
                       else f"removing it cost at most {ceiling} (mean {cost}), under the tolerance {tolerance}")
                records.append(_contribution(hunk, position, decision="dropped", contribution=cost, reason=why,
                                             ci_low=low, ci_high=high))
            else:
                records.append(_contribution(hunk, position, decision="kept", contribution=cost,
                                             ci_low=low, ci_high=high))
        ablation = Ablation(proposed=_identity(candidate), proposed_diff=proposed_diff, tolerance=tolerance,
                            hunks=tuple(records))
        if current is candidate:
            return candidate, tuple(candidate_train), ablation
        gate = self._gate(champion_train, current_run, name="train", min_delta=min_train, strict=False,
                          max_fall=max_fall, values=self.values)
        if not gate.passed:
            return candidate, tuple(candidate_train), ablation.model_copy(update={
                "reduced_train": gate,
                "reason": "the reduced candidate fails the training gate; the proposed one goes to the holdout"})
        # The reduced candidate is what the loop stands behind, so it is what
        # the pack root holds under the round's name.
        envelope = PackEnvelope(kind=current.kind, name=current.name, title=current.title,
                                description=current.description, body=current.data)
        install(envelope, root=self.out / "packs", roots=tuple(self.pack_roots), replace=True)
        self._candidates[current.digest] = current
        return current, current_run, ablation.model_copy(update={"reduced": True, "reduced_train": gate})


def _contribution(hunk: diffs.Hunk, position: int, decision: str, contribution: float | None = None,
                  reason: str = "", ci_low: float | None = None, ci_high: float | None = None) -> HunkContribution:
    return HunkContribution(index=position + 1, file=hunk.path, header=hunk.header, decision=decision,
                            contribution=contribution, reason=reason, ci_low=ci_low, ci_high=ci_high)


def _diff(champion: ResolvedPack, candidate: ResolvedPack) -> str:
    """The candidate's unified diff against the champion, over the kind's tree codec."""
    codec = packkit.kind(champion.kind)
    if codec.to_tree is None:
        return "" if candidate.data == champion.data else "(no tree codec)"
    return diffs.render(codec.to_tree(champion.data), codec.to_tree(candidate.data))


def _case_key(case: EvalCase) -> str:
    return hashlib.sha256(json.dumps({"id": case.id, "query": case.query, "row": case.row}, sort_keys=True,
                                     default=str).encode()).hexdigest()


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def improve(champion: ResolvedPack, cases: Sequence[EvalCase], *, run: Runner, agent_for: AgentFor,
            exchange: Exchange, out: Path, rater: Any = None, holdout: Sequence[EvalCase] | None = None,
            holdout_share: float | None = None, rounds: int | None = None,
            pack_roots: Sequence[str | Path] = (), authoring_rounds: int | None = None,
            min_train_delta: float | None = None, min_holdout_delta: float | None = None,
            max_axis_regression: float | None = None, ablate: bool | None = None,
            ablation_max_hunks: int | None = None, ablation_tolerance: float | None = None,
            values: Mapping[str, Any] | None = None,
            holdout_values: Mapping[str, Any] | None = None, repeats: int | None = None,
            confidence: float | None = None, resamples: int | None = None,
            min_train_ci: float | None = None) -> ImproveReport:
    """Run the loop from *champion* over *cases*; the held-out cases are *holdout* or a stable share of *cases*.

    A separate *holdout* (cases compiled from fresh seeds) is the stronger
    test: a policy that learned this company rather than the task fails
    there. Without one, a share of *cases* is held back by case id.

    *repeats* (default: the policy ``evalrun.improve.repeats``, 1) runs each
    policy that many times over each case set and judges every comparison as
    a paired test over per-case means (``judge_paired``); *confidence*,
    *resamples* and *min_train_ci* tune that test and default to their
    ``evalrun.improve.*`` policies.
    """
    dropped = 0
    if holdout is None:
        share = float(packkit.policy("evalrun.improve.holdout_share")) if holdout_share is None else holdout_share
        train, held = split_cases(cases, holdout_share=share)
    else:
        # A case the training corpus itself declares held out stays sealed
        # even when the holdout comes from elsewhere: it is dropped, counted.
        train = tuple(case for case in cases if not is_held_out(declared_split(case)))
        dropped = len(cases) - len(train)
        held = tuple(holdout)
    improver = Improver(run=run, agent_for=agent_for, exchange=exchange, out=out, rater=rater,
                        pack_roots=pack_roots,
                        authoring_rounds=int(packkit.policy("evalrun.improve.authoring_rounds"))
                        if authoring_rounds is None else authoring_rounds,
                        ablate=bool(packkit.policy("evalrun.improve.ablate")) if ablate is None else ablate,
                        ablation_max_hunks=int(packkit.policy("evalrun.improve.ablation_max_hunks"))
                        if ablation_max_hunks is None else ablation_max_hunks,
                        ablation_tolerance=float(packkit.policy("evalrun.improve.ablation_tolerance"))
                        if ablation_tolerance is None else ablation_tolerance,
                        values=values, holdout_values=holdout_values,
                        repeats=int(packkit.policy("evalrun.improve.repeats")) if repeats is None else int(repeats),
                        confidence=confidence, resamples=resamples, min_train_ci=min_train_ci)
    return improver.improve(champion, train, held,
                            rounds=int(packkit.policy("evalrun.improve.rounds")) if rounds is None else rounds,
                            min_train_delta=min_train_delta, min_holdout_delta=min_holdout_delta,
                            max_axis_regression=max_axis_regression, held_out_dropped=dropped)


__all__ = ["HELD_OUT_SPLITS", "IMPROVE_SCHEMA", "ROUND_SCHEMA", "Ablation", "Gate", "HunkContribution", "ImproveReport",
           "Improver", "RoundReceipt", "improve", "judge", "judge_paired", "round_stem", "split_cases"]
