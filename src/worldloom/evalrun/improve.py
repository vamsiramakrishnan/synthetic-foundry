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

**Wide search** (``evalrun.search``) widens a round without touching a gate:
``candidates`` proposals, each told it is the i-th of N; the distinct ones
screened on training cases by successive halving against the champion's
existing runs, down to ``finalists`` that take the full training gate; an
archive of every policy evaluated in full, whose Pareto frontier over failure
clusters ``parents="archive"`` draws the round's parent from; and a
``round_budget`` screening respects. Promotion is still only through the
training gate, ablation and the holdout against the current champion. At
the defaults a round is the narrow one above, receipts to the byte.

**Two levers** (``levers``, ``evalrun.interface``): besides the agent's
policy, a round may change the *interface* the agent is served, an Anvil
manifest overlay per connector, when the loop is given an ``InterfaceLever``
over the served contract bundles. Every run is then served through Anvil
under the champion interface; the autopsy attributes each finding to an
owner (``evalrun.ownership``), and an interface candidate is proposed from
the interface-owned findings, the failing arguments and vendor errors, and
the tools as the agent saw them, through an interview refused with findings
until ``anvil compile`` and the surface check pass. It is judged by exactly
the gates an agent candidate is (training gate, ablation over its hunks,
holdout) and then by a **transfer** gate: a second agent, run on the
held-out cases under both interfaces, must not regress. A promoted overlay
is written as a reviewable manifest diff and a simulation-only approvals
record (``interface.write_promotion``); it is never applied outside the
loop's directory. With ``levers=("agent",)`` and no lever object, nothing
below reads any of it and every receipt keeps its bytes.

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
import math
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
from .autopsy import autopsy
from .contract import EvalCase
from .failure_curriculum import (
    CURRICULUM_MODES,
    DEFAULT_CURRICULUM_CASES,
    FailureCurriculum,
    check_unseen,
    draw_failure_cases,
)
from .grader import GraderDrift, check_frozen, grader_identity
from .harness import skills_cache_in
from .noise import Interval, PairedComparison, confidence_level, paired, resample_count
from .qualification import (
    QualificationExhausted,
    QualificationPolicy,
    QualificationTrial,
    QualificationVault,
    isolated_splits,
)
from .results import Comparison, compare, delta_band, read_run, write_run
from .runner import RunReport, case_set_digest
from .search import (
    PARENT_MODES,
    Archive,
    CandidateRecord,
    Screening,
    ScreenScore,
    ScreenStage,
    case_scores,
    diff_stat,
    halving_keep,
    paired_delta,
    parent_seed,
    pareto_frontier,
    screen_order,
    screen_seed,
    select_parent,
    summary_line,
)
from .splits import HELD_OUT_SPLITS, declared_split, is_held_out
from .value import value_weighted_delta

IMPROVE_SCHEMA = "worldloom.improve/v1"
ROUND_SCHEMA = "worldloom.improve-round/v1"

#: A round's suffix on a candidate's name: ``-r3``, ``-r3-c2`` for the second
#: of several candidates, or either with ``-1f2e3d4c`` when the name was taken.
_ROUND_SUFFIX = re.compile(r"-r\d+(-c\d+)?(-[0-9a-f]+)?$")
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
    #: Independent evidence units, when a sealed qualification experiment was used.
    independent_units: int | None = None

    @model_serializer(mode="wrap")
    def _single_run_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.repeats == 1:
            for name in _REPEAT_FIELDS:
                data.pop(name, None)
        if self.independent_units is None:
            data.pop("independent_units", None)
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
    #: Wide search only (absent otherwise, so a narrow loop's receipt keeps
    #: its bytes): the policy the proposer revised and how it was chosen
    #: (``mode`` ``champion`` or ``archive``, the frontier, weights and draw).
    parent: dict[str, Any] | None = None
    #: Every proposal of the round and its screening stages, when more than one was asked for.
    screening: Screening | None = None
    #: Case-runs this round executed (runs read back from disk cost nothing).
    spent: int | None = None
    #: The lever the round's candidate pulled, when the loop has an interface
    #: lever (``agent`` or ``interface``); absent otherwise.
    lever: str | None = None
    #: An interface candidate's record: its overlay digests per connector, the
    #: recompiled contract digests, the base's, the transfer gate's status and,
    #: when promoted, where its reviewable diff and approvals record were written.
    interface: dict[str, Any] | None = None
    #: The transfer gate: a second agent on the held-out cases under both interfaces.
    transfer: Gate | None = None
    #: The one-use held-out experiment reserved before either side ran.
    qualification: dict[str, Any] | None = None
    #: With a ``failures`` curriculum, the training cases this round added
    #: and the clusters of the previous round's champion that drove each
    #: (``failure_curriculum.FailureDraw.record``); absent otherwise.
    curriculum: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def _narrow_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        for name in _WIDE_FIELDS:
            if data.get(name, False) is None:
                data.pop(name)
        return data


#: Receipt fields only wide search, or the interface lever, fills, and so only their receipts carry.
_WIDE_FIELDS: tuple[str, ...] = ("parent", "screening", "spent", "lever", "interface", "transfer", "qualification",
                                 "curriculum")


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
    #: Wide search only: its settings (``candidates``, ``screen_cases``,
    #: ``finalists``, ``parents``, ``round_budget``) and the case-runs every
    #: round of this loop executed, in total.
    search: dict[str, Any] | None = None
    spent: int | None = None
    #: With an interface lever: the levers the loop pulled, and the interface
    #: it started from and ended with (digests); absent otherwise.
    levers: tuple[str, ...] | None = None
    interface: dict[str, Any] | None = None
    qualification: dict[str, Any] | None = None
    #: With a ``failures`` curriculum: its settings, the cases it added over
    #: every round, and the training set the loop ended with; absent otherwise.
    curriculum: dict[str, Any] | None = None

    @model_serializer(mode="wrap")
    def _single_run_wire(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        data: dict[str, Any] = handler(self)
        if self.repeats == 1:
            data.pop("repeats", None)
        for name in ("search", "spent", "levers", "interface", "qualification", "curriculum"):
            if data.get(name, False) is None:
                data.pop(name)
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


@dataclass
class _Proposal:
    """One proposal of a round, judged before anything runs it."""

    index: int
    #: ``valid``, ``refused``, ``unchanged`` or ``duplicate``.
    status: str
    authoring: tuple[dict[str, Any], ...]
    candidate: ResolvedPack | None = None
    reasons: tuple[str, ...] = ()
    summary: str = ""
    #: Its unified diff against the champion (what the gates judge).
    diff: str = ""
    duplicate_of: int | None = None
    #: ``agent`` (a revised pack in ``candidate``) or ``interface`` (a revised
    #: interface in ``variant``; ``candidate`` is then the champion pack it runs).
    lever: str = "agent"
    variant: Any = None

    @property
    def digest(self) -> str:
        """What names this proposal's candidate: the pack's digest, or the interface variant's."""
        if self.lever == "interface" and self.variant is not None:
            return str(self.variant.digest)
        return self.candidate.digest if self.candidate is not None else ""

    def brief_line(self) -> str:
        """What a later candidate of the round is told about this one: a summary and a size, never content."""
        if self.status == "valid":
            return f"- candidate {self.index}: {self.summary} ({diff_stat(self.diff)})"
        if self.status == "duplicate":
            return f"- candidate {self.index}: the same change as candidate {self.duplicate_of}"
        if self.status == "unchanged":
            return f"- candidate {self.index}: restated the draft, changed nothing"
        return f"- candidate {self.index}: refused by the lint"

    def record(self, **update: Any) -> CandidateRecord:
        if self.lever == "interface":
            return CandidateRecord(index=self.index, status=update.pop("status", self.status),
                                   ref=None if self.variant is None else _interface_ref(self.variant),
                                   digest=None if self.variant is None else self.variant.digest,
                                   summary=self.summary, diff_stat=diff_stat(self.diff) if self.diff else "",
                                   duplicate_of=self.duplicate_of, reasons=self.reasons, authoring=self.authoring,
                                   **update)
        return CandidateRecord(index=self.index, status=update.pop("status", self.status),
                               ref=None if self.candidate is None else self.candidate.ref,
                               digest=None if self.candidate is None else self.candidate.digest,
                               summary=self.summary, diff_stat=diff_stat(self.diff) if self.diff else "",
                               duplicate_of=self.duplicate_of, reasons=self.reasons, authoring=self.authoring,
                               **update)


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
    #: What the proposer is shown: ``summary`` (the autopsy brief) or
    #: ``traces`` (the autopsy, then ``evidence``'s error catalogue, tool
    #: contracts and trajectories); ``None`` reads ``evalrun.improve.brief``.
    brief_mode: str | None = None
    #: A reference-agent run over the training cases, for the accepted calls
    #: and reference trajectories of a ``traces`` brief; never a held-out run
    #: (``evidence.admit_reference`` refuses one).
    reference_run: RunReport | None = None
    #: Wide search (``evalrun.improve.candidates``, ``.screen_cases``,
    #: ``.finalists``, ``.parents``, ``.round_budget``): proposals asked for a
    #: round, training cases the first screening stage spends, candidates that
    #: reach the full training gate, where a round's parent comes from, and
    #: the case-runs screening plus the finalists' training runs may cost a
    #: round. At the defaults (1, -, 1, ``champion``, ``None``) a round is
    #: exactly the narrow loop, receipts to the byte.
    candidates: int = 1
    screen_cases: int = 6
    finalists: int = 1
    parents: str = "champion"
    round_budget: int | None = None
    #: The levers a round may pull (``agent``, ``interface``). ``interface``
    #: needs ``interface``, an ``evalrun.interface.InterfaceLever`` over the
    #: served bundles; with one, every run is served through Anvil under the
    #: champion interface. At ``("agent",)`` without a lever the loop is the
    #: one above, receipts to the byte.
    levers: tuple[str, ...] = ("agent",)
    interface: Any = None
    #: The second agent the transfer gate runs on the held-out cases under
    #: both interfaces; without one the gate is skipped with a recorded reason.
    transfer: AgentUnderTest | None = None
    #: Fresh evidence-disjoint promotion tranches, independent-unit inference,
    #: and a sealed probe budget. Disabled preserves the legacy wire format.
    qualification: QualificationPolicy | None = None
    #: A ``failure_curriculum.FailureCurriculum``: between rounds, new
    #: training cases drawn from its pool and aimed at the clusters the
    #: round's champion failed. ``None`` keeps the training set fixed, and
    #: every receipt, run directory and byte exactly as without it.
    curriculum: FailureCurriculum | None = None
    _qualification: QualificationVault | None = field(default=None, repr=False)
    #: The label training runs are filed under: ``train`` for the set the
    #: loop started with, ``train-<digest>`` once a curriculum has grown it,
    #: so a run over one set is never read back as a run over another.
    _train_label: str = "train"
    #: The champion's first training run of the latest round, which the curriculum reads.
    _last_train_run: RunReport | None = field(default=None, repr=False)
    _variant: Any = None
    _variants: dict[str, Any] = field(default_factory=dict)
    _runs: dict[tuple[str, str, str], RunReport] = field(default_factory=dict)
    _candidates: dict[str, ResolvedPack] = field(default_factory=dict)
    #: Case-runs this loop has executed (a run read back from disk is free).
    _spent: int = 0

    @property
    def wide(self) -> bool:
        """Whether any wide-search setting is off its default: then receipts carry parent, screening and spend."""
        return self.candidates > 1 or self.parents != "champion" or self.round_budget is not None

    def _grading_identity(self) -> dict[str, Any]:
        """The core grader, plus a runner's independently measured domain."""
        base = grader_identity(self.rater)
        identify = getattr(self.run, "grading_identity", None)
        if not callable(identify):
            return base
        identity = dict(identify(self.rater))
        if any(identity.get(key) != value for key, value in base.items() if key != "digest"):
            raise ValueError("runner grading_identity must preserve the core grader identity")
        if not isinstance(identity.get("digest"), str) or not identity["digest"]:
            raise ValueError("runner grading_identity must include its combined digest")
        return dict(json.loads(json.dumps(identity, sort_keys=True)))

    def _validate_cases(self, cases: Sequence[EvalCase]) -> None:
        """A domain's provenance preflight runs before sealing or cache reuse."""
        validate = getattr(self.run, "validate_cases", None)
        if callable(validate):
            validate(cases)

    def _check_grader(self, pinned: Mapping[str, Any]) -> None:
        if not callable(getattr(self.run, "grading_identity", None)):
            check_frozen(pinned, self.rater)
            return
        current = self._grading_identity()
        expected = str(pinned.get("digest", ""))
        if current != dict(pinned):
            changed = tuple(sorted(key for key in set(current) | set(pinned)
                                   if key != "digest" and current.get(key) != pinned.get(key)))
            raise GraderDrift("the runner's grader differs from the sealed experiment",
                              pinned=expected, current=current["digest"], changed=changed)

    def _pinned_runs(self, pack: ResolvedPack, cases: Sequence[EvalCase], label: str,
                     grader: dict[str, Any], *, variant: Any = None,
                     expected: Mapping[str, Any] | None = None) -> tuple[RunReport, ...]:
        """*pack* over *cases*, ``repeats`` times: each an ordinary pinned run in ``<label>/rep-<i>``.

        At one repeat it is the single run in ``<label>`` itself, where a
        loop without repeats has always written it. *variant* is the
        interface it is served under, the champion interface when ``None``.
        """
        if self.repeats < 1:
            raise ValueError(f"repeats must be at least 1, not {self.repeats}")
        if self.repeats == 1:
            return (self._pinned_run(pack, cases, label, grader, variant=variant, expected=expected),)
        return tuple(self._pinned_run(pack, cases, label, grader, repeat=index, variant=variant, expected=expected)
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
                    repeat: int | None = None, *, variant: Any = None, agent: AgentUnderTest | None = None,
                    slug: str | None = None, expected: Mapping[str, Any] | None = None) -> RunReport:
        self._validate_cases(cases)
        # The agent is built first, so a run is reused only when this agent
        # made it: one pack run by two different agents (another command,
        # another harness) is two runs. It is built here so a skill tree it
        # materialises lands in this loop's output directory, not the user's
        # cache.
        if agent is None:
            with skills_cache_in(self.out / "skills-cache"):
                agent = self.agent_for(pack)
        identity = fingerprint(agent)
        self._check_grader(grader)
        if expected is not None and (json.loads(json.dumps(identity, sort_keys=True)) != expected.get("harness")
                                     or pack.digest != expected.get("digest")):
            raise ValueError("target harness or policy changed after the qualification reservation")
        served = None
        if self.interface is not None:
            # Served through Anvil under an interface: the interface is part
            # of what ran, so it is part of the run's identity and directory.
            served = variant if variant is not None else self._variant
            if expected is not None and self.interface.identity(served) != expected.get("serving"):
                raise ValueError("served interface changed after the qualification reservation")
            identity = {**identity, "serving": self.interface.identity(served)}
            if slug is None and served.digest != self.interface.base.digest:
                slug = f"{_slug(pack)}+if-{served.digest[:12]}"
        # A repeat is its own run: its own cache entry and its own directory
        # under the label's, so a resumed loop reuses every repeat it finished.
        place = label if repeat is None else f"{label}/rep-{repeat}"
        key = (pack.digest if slug is None else f"{pack.digest}\0{slug}", place,
               json.dumps(identity, sort_keys=True, default=str))
        held = self._runs.get(key)
        if held is not None:
            return held
        directory = self.out / "runs" / (slug or _slug(pack)) / label
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
        execute = getattr(self.run, "run_experiment", None)
        if served is not None:
            report = self.interface.run(cases, agent, served)
        elif callable(execute):
            # A native or remote runner needs the repeat's identity to
            # checkpoint that execution without replaying a prior repeat.
            report = execute(cases, agent, directory=directory, label=label, repeat=repeat, grader=grader)
        else:
            report = self.run(cases, agent)
        self._spent += len(cases)
        self._check_grader(grader)
        update: dict[str, Any] = {"grader": grader, "agent_pack": report.agent_pack or _identity(pack),
                                  "agent_identity": identity}
        if label == "holdout" or label.startswith("holdout/"):
            # Marked on the run itself, so an export refuses it wherever it goes.
            update["split"] = "holdout"
        report = report.model_copy(update=update)
        write_run(directory, report)
        self._runs[key] = report
        return report

    def _qualification_identity(self, pack: ResolvedPack, *, variant: Any = None) -> dict[str, Any]:
        with skills_cache_in(self.out / "skills-cache"):
            agent = self.agent_for(pack)
        identity = {**_identity(pack), "harness": fingerprint(agent)}
        if self.interface is not None:
            identity["serving"] = self.interface.identity(variant if variant is not None else self._variant)
            if self.transfer is not None:
                identity["transfer_harness"] = fingerprint(self.transfer)
        return identity

    def _qualified_gate(self, champion: Sequence[RunReport], candidate: Sequence[RunReport], *,
                        trial: QualificationTrial, name: str, min_delta: float, max_fall: float,
                        values: Mapping[str, Any] | None = None) -> Gate:
        assert self.qualification is not None
        reasons: list[str] = []
        expected = {case.id for case in trial.cases}
        reference_axes: dict[str, set[str]] = {}
        reference_queries = {case.id: case.query for case in trial.cases}
        for side, runs in (("champion", champion), ("candidate", candidate)):
            for index, report in enumerate(runs, start=1):
                result_ids = [row.case_id for row in report.results]
                if (len(result_ids) != len(expected) or set(result_ids) != expected
                        or report.case_set != case_set_digest(trial.cases)):
                    reasons.append(f"{side} repeat {index} did not run the complete reserved cohort")
                if any(not row.graded for row in report.results):
                    reasons.append(f"{side} repeat {index} has ungraded cases in the reserved cohort")
                for row in report.results:
                    if row.query != reference_queries.get(row.case_id):
                        reasons.append(f"{side} repeat {index} changed the request for {row.case_id}")
                    if row.graded and row.score is not None:
                        observed = set(row.score.observed)
                        if row.case_id not in reference_axes:
                            reference_axes[row.case_id] = observed
                        elif observed != reference_axes[row.case_id]:
                            reasons.append(f"{side} repeat {index} changed observed axes for {row.case_id}")
                        measured = [row.score.score, *(float(getattr(row.score, axis).score) for axis in observed)]
                        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in measured):
                            reasons.append(f"{side} repeat {index} has an invalid score for {row.case_id}")
        if reasons:
            return Gate(name=name, passed=False, reasons=tuple(reasons), repeats=self.repeats,
                        method="cluster_bootstrap", confidence=self.qualification.probe_confidence,
                        independent_units=0)
        comparison = paired(champion, candidate, values=values, units=trial.units,
                            confidence=self.qualification.probe_confidence,
                            resamples=resample_count(self.resamples))
        gate = judge_paired(comparison, name=name, min_delta=min_delta, strict=name == "holdout",
                            max_axis_regression=max_fall, min_ci=min_delta)
        reasons = list(gate.reasons)
        units = comparison.independent_units or 0
        if units < self.qualification.min_units:
            reasons.append(f"only {units} independently graded units; need {self.qualification.min_units}")
        # Establish non-inferiority, rather than merely failing to detect a
        # statistically significant regression. Wide uncertainty is not a pass.
        for axis, estimate in comparison.axes.items():
            if estimate is None:
                if any(axis in axes for axes in reference_axes.values()):
                    reasons.append(f"the {axis} axis has no paired evidence")
                continue
            if estimate.cases < self.qualification.min_units:
                reasons.append(f"the {axis} axis has {estimate.cases} independent units; "
                               f"need {self.qualification.min_units}")
            if estimate.ci_low is None or estimate.ci_low < -max_fall:
                reasons.append(f"the {axis} axis does not establish non-inferiority at {-max_fall}")
        return gate.model_copy(update={"passed": not reasons, "reasons": tuple(reasons),
                                       "independent_units": units})

    def _holdout_experiment(self, number: int, champion: ResolvedPack, candidate: ResolvedPack,
                            holdout: Sequence[EvalCase], grader: dict[str, Any], *, min_held: float,
                            max_fall: float, variant: Any = None) -> tuple[Gate, QualificationTrial | None]:
        trial = None
        label = "holdout"
        if self._qualification is not None:
            trial = self._qualification.reserve(number, champion=self._qualification_identity(champion),
                                                candidate=self._qualification_identity(candidate, variant=variant),
                                                grader=grader)
            holdout, label = trial.cases, trial.label
        before = self._pinned_runs(champion, holdout, label, grader,
                                   expected=None if trial is None else trial.reservation["champion"])
        after = self._pinned_runs(candidate, holdout, label, grader, variant=variant,
                                  expected=None if trial is None else trial.reservation["candidate"])
        values = self.holdout_values if self.holdout_values is not None else self.values
        if trial is None:
            return self._gate(before, after, name="holdout", min_delta=min_held, strict=True,
                              max_fall=max_fall, values=values), None
        return self._qualified_gate(before, after, trial=trial, name="holdout", min_delta=min_held,
                                    max_fall=max_fall, values=values), trial

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
            screening = document.get("screening")
            for identity in (document.get("champion"), document.get("candidate"), document.get("initial"),
                             ablation.get("proposed") if isinstance(ablation, dict) else None,
                             document.get("parent"),
                             *(screening.get("candidates") or () if isinstance(screening, dict) else ())):
                if isinstance(identity, dict) and isinstance(identity.get("ref"), str):
                    refs.add(identity["ref"])
        return last, frozenset(refs)

    def _candidate_name(self, champion: ResolvedPack, stem: str, number: int, protected: frozenset[str],
                        index: int | None = None) -> str:
        """A name for round *number*'s candidate that overwrites nothing anyone refers to.

        The plain ``<stem>-r<number>`` is taken when no pack holds it, or when
        the pack holding it is in the loop's own root and neither a receipt
        nor the champion names it (a round interrupted before its receipt,
        which the same name resumes). Otherwise the name carries a short
        digest of the champion and the round, stable across reruns. The
        *index*-th of several candidates in a round is ``<stem>-r<number>-c<index>``.
        """
        from ..packkit.sources import find

        own = (self.out / "packs").resolve()
        attempt = 0
        plain = f"{stem}-r{number}" + ("" if index is None else f"-c{index}")
        name = plain
        while True:
            located = find(champion.kind, name, roots=self._search())
            if located is None:
                return name
            inside = Path(located.location).resolve().is_relative_to(own)
            if inside and name != champion.name and f"{champion.kind}:{name}" not in protected:
                return name
            attempt += 1
            salt = f"{champion.digest}\0{number}\0{attempt}" + ("" if index is None else f"\0{index}")
            suffix = hashlib.sha256(salt.encode()).hexdigest()[:8]
            name = f"{plain}-{suffix}"

    def _message(self, champion: ResolvedPack, brief: str, round_number: int) -> str:
        return (packkit.text("evalrun.improve.message", brief=brief, champion=champion.pinned, round=round_number)
                + "\n\n" + packkit.text("evalrun.improve.rule.diff"))

    def _fitted_brief(self, found: Any, champion: ResolvedPack, round_number: int, *, run: RunReport | None = None,
                      train: Sequence[EvalCase] = (), holdout: Sequence[EvalCase] = ()) -> str:
        """The brief, fitted to the interview's message limit: ``evidence.fit_summary``, or ``trace_brief``."""
        from ..packkit.authoring import MAX_MESSAGE
        from .evidence import brief_mode, fit_summary, trace_brief

        room = MAX_MESSAGE - len(self._message(champion, "", round_number))
        if run is None or brief_mode(self.brief_mode) == "summary":
            return fit_summary(found, room)
        return trace_brief(found, run, room=room, train=train, holdout=holdout, reference=self.reference_run,
                           values=self.values)

    def _propose(self, champion: ResolvedPack, brief: str, round_number: int, stem: str,
                 protected: frozenset[str] = frozenset(), *, index: int | None = None, total: int = 1,
                 earlier: Sequence[str] = (), judged_against: ResolvedPack | None = None) -> Any:
        """One interview for a revision of *champion* (the draft: the round's parent).

        With *total* above 1 the message says which candidate of the round
        this is and lists the earlier ones by summary and size, asking for a
        different approach. When the draft is not the policy the revision is
        judged against (*judged_against*, the current champion), it says so.
        """
        message = self._message(champion, brief, round_number)
        notes: list[str] = []
        if total > 1:
            notes.append(packkit.text("evalrun.improve.rule.candidates", index=index, total=total,
                                      earlier="\n".join(earlier) if earlier else "(none yet)"))
        if judged_against is not None and judged_against.digest != champion.digest:
            notes.append(packkit.text("evalrun.improve.rule.parent", parent=champion.pinned,
                                      champion=judged_against.pinned))
        if notes:
            from ..packkit.authoring import MAX_MESSAGE, clip_message

            extra = "\n\n" + "\n\n".join(notes)
            room = MAX_MESSAGE - len(self._message(champion, "", round_number)) - len(extra)
            message = self._message(champion, clip_message(brief, max(room, 0)), round_number) + extra
        name = self._candidate_name(judged_against or champion, stem, round_number, protected, index=index)
        title = f"{stem}, round {round_number}" + ("" if index is None else f", candidate {index}")
        draft = {"schema": "worldloom.pack/v1", "kind": "agent", "name": name, "title": title,
                 "body": champion.data}

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
        self._validate_cases(train)
        self._validate_cases(holdout)
        if self.repeats < 1:
            raise ValueError(f"repeats must be at least 1, not {self.repeats}")
        self._check_search()
        self._check_levers()
        self._check_curriculum()
        # The budget caps what a round spends, screening or not: the finalists'
        # full training runs are its floor, so a budget below them could never
        # be kept and is refused rather than silently overrun.
        floor = min(self.finalists, self.candidates) * self.repeats * len(train)
        if self.round_budget is not None and self.round_budget < floor:
            raise ValueError(f"round_budget {self.round_budget} is under the {floor} case-run(s) the finalists' "
                             f"training runs cost ({min(self.finalists, self.candidates)} finalist(s) x "
                             f"{self.repeats} repeat(s) x {len(train)} training case(s)); raise it or drop it")
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
        grader = self._grading_identity()
        if self.qualification is not None:
            if (any(not math.isfinite(value) for value in (min_train, min_held, max_fall))
                    or max_fall < 0):
                raise ValueError("qualification requires finite deltas and a nonnegative axis regression limit")
            if self.repeats < self.qualification.min_repeats:
                raise ValueError(f"qualification needs at least {self.qualification.min_repeats} repeats per side")
            if any((self.out / "rounds").glob("*.json")) and not (self.out / "qualification" / "seal.json").exists():
                raise ValueError("earlier rounds already probed an unqualified holdout; use a new output directory")
            self._qualification = QualificationVault.open(self.out / "qualification", train, holdout,
                                                          policy=self.qualification, grader=grader)
        elif (self.out / "qualification" / "seal.json").exists():
            raise ValueError("this output directory holds a sealed qualification experiment; keep its policy")
        stem = round_stem(champion.name)
        initial = champion
        if self.interface is not None and self._variant is None:
            self._variant = self.interface.base
            self._variants[self._variant.digest] = self._variant
        initial_variant = self._variant
        receipts: list[RoundReceipt] = []
        self.out.mkdir(parents=True, exist_ok=True)
        last, protected = self._earlier()
        initial_train = tuple(train)
        grown: dict[str, Any] | None = None
        for number in range(last + 1, last + rounds + 1):
            protected |= {f"{champion.kind}:{champion.name}"}
            before = self._spent
            try:
                receipt = self._round(number, champion, train, holdout, grader, stem, protected,
                                      min_train=min_train, min_held=min_held, max_fall=max_fall)
            except QualificationExhausted as error:
                receipt = RoundReceipt(round=number, grader=grader["digest"], champion=_identity(champion),
                                       decision="qualification_exhausted", reasons=(str(error),))
            if grown is not None:
                receipt = receipt.model_copy(update={"curriculum": grown})
            if self.wide:
                receipt = receipt.model_copy(update={"spent": self._spent - before})
            if receipt.candidate is not None:
                protected |= {str(receipt.candidate["ref"])}
            receipts.append(receipt)
            _write(self.out / "rounds" / f"{number:03d}.json", receipt.model_dump(mode="json", by_alias=True))
            if receipt.diff:
                (self.out / "rounds" / f"{number:03d}.diff").write_text(receipt.diff, encoding="utf-8", newline="")
            # The round is receipted, so its proposals no longer need keeping for a resume.
            self._journal_path(number).unlink(missing_ok=True)
            if receipt.decision == "promoted" and receipt.lever == "interface":
                assert receipt.candidate is not None
                self._variant = self._variants[receipt.candidate["digest"]]
            elif receipt.decision == "promoted":
                assert receipt.candidate is not None
                champion = self._candidates[receipt.candidate["digest"]]
            elif receipt.decision in {"no_failures", "questions", "proposer_error", "qualification_exhausted"}:
                # Nothing left to learn from this set, the operator has to
                # answer before a harness can go on, or the harness is not
                # answering at all: another round would repeat this one.
                break
            if self.curriculum is not None and number < last + rounds:
                train, grown = self._grow(number, train, holdout)
        report = ImproveReport(grader=grader, train_cases=len(initial_train), holdout_cases=len(holdout),
                               train_case_set=case_set_digest(initial_train),
                               holdout_case_set=case_set_digest(holdout),
                               initial=_identity(initial), champion=_identity(champion), rounds=tuple(receipts),
                               promotions=sum(item.decision == "promoted" for item in receipts),
                               held_out_dropped=held_out_dropped, repeats=self.repeats,
                               search=self._search_settings() if self.wide else None,
                               spent=sum(item.spent or 0 for item in receipts) if self.wide else None,
                               levers=self.levers if self.interface is not None else None,
                               interface=self._interface_summary(initial_variant) if self.interface is not None
                               else None,
                               qualification=self._qualification.summary() if self._qualification is not None else None,
                               curriculum=None if self.curriculum is None else {
                                   **self.curriculum.settings(),
                                   "added": len(train) - len(initial_train),
                                   "final_train_cases": len(train),
                                   "final_train_case_set": case_set_digest(train)})
        _write(self.out / "improve.json", report.model_dump(mode="json", by_alias=True))
        return report

    # -- failure curriculum -----------------------------------------------------

    def _check_curriculum(self) -> None:
        if self.curriculum is None:
            return
        if self.curriculum.mode not in CURRICULUM_MODES:
            raise ValueError(f"unknown curriculum {self.curriculum.mode!r}; use one of {list(CURRICULUM_MODES)}")
        if self.curriculum.cases < 1:
            raise ValueError(f"a curriculum round adds at least one case, not {self.curriculum.cases}")
        # Each of these is fixed over the training set it was built for: a
        # sealed qualification experiment, a value table keyed by the
        # corpus's case ids, and an archive whose cluster means are over one
        # case set. A growing training set would quietly break each.
        if self.qualification is not None:
            raise ValueError("a failures curriculum cannot grow a sealed qualification experiment's training set")
        if self.values is not None:
            raise ValueError("a failures curriculum adds cases no value table covers; drop --value or the curriculum")
        if self.parents == "archive":
            raise ValueError("a failures curriculum changes the training set the archive's cluster means are over; "
                             "use --parents champion with it")

    def _grow(self, number: int, train: Sequence[EvalCase],
              holdout: Sequence[EvalCase]) -> tuple[Sequence[EvalCase], dict[str, Any] | None]:
        """The next round's training cases: *train* plus the curriculum's draw from round *number*'s failures.

        The draw reads the champion's first training run of the round just
        receipted, never a held-out run, and every case it adds is checked
        against the held-out cases by id, content key, source-record digest
        and gold-DAG digest before it can train.
        """
        assert self.curriculum is not None
        run = self._last_train_run
        if run is None:
            return train, None
        # Every cluster, not the brief's top twelve: a small cluster still
        # earns its share of the new cases.
        found = autopsy(run, cases=train, top=max(1, len(run.results)) * 64)
        if found.failing == 0:
            return train, None
        draw = draw_failure_cases(found, self.curriculum.pool, count=self.curriculum.cases, round=number + 1,
                                  train=train, held=holdout, exclude=self.curriculum.exclude)
        check_unseen(draw.cases, holdout)
        grown = (*train, *draw.cases)
        if draw.cases:
            self._validate_cases(grown)
            self._train_label = f"train-{case_set_digest(grown)[:12]}"
        record = draw.record(source_round=number, train_cases=len(grown), train_case_set=case_set_digest(grown))
        return grown, record

    def _round(self, number: int, champion: ResolvedPack, train: Sequence[EvalCase], holdout: Sequence[EvalCase],
               grader: dict[str, Any], stem: str, protected: frozenset[str] = frozenset(), *,
               min_train: float, min_held: float, max_fall: float) -> RoundReceipt:
        base = {"round": number, "grader": grader["digest"], "champion": _identity(champion)}
        champion_train = self._pinned_runs(champion, train, self._train_label, grader)
        self._last_train_run = champion_train[0]
        parent, parent_train = champion, tuple(champion_train)
        archive: Archive | None = None
        wide: dict[str, Any] = {}
        if self.wide:
            archive, parent, parent_train, wide["parent"] = self._branch(number, champion, champion_train, train,
                                                                         grader)
        # The brief is the first repeat's failures of the policy the proposer
        # revises (the champion, or the parent wide search drew): the proposer
        # is shown one run, as it always was, and the repeats only sharpen the
        # judging.
        if self.interface is None:
            found = autopsy(parent_train[0], cases=train, attribute=self.qualification is not None,
                            peers=parent_train[1:] if self.qualification is not None else (),
                            reference=self.reference_run if self.qualification is not None else None)
        else:
            # Served under an interface, every finding gets an owner: the
            # served surface's facts, the other repeats and the reference
            # run are what the ownership rules read.
            found = autopsy(parent_train[0], cases=train, attribute=True, surface=self.interface.facts(self._variant),
                            peers=parent_train[1:], reference=self.reference_run)
        if found.failing == 0:
            return RoundReceipt(**base, **wide, decision="no_failures",
                                reasons=("the champion passes every training case; escalate the curriculum",))
        pulls = self._pullable(found)
        if not pulls:
            return RoundReceipt(**base, **wide, decision="no_failures", failing=found.failing,
                                clusters=tuple(cluster.key for cluster in found.clusters),
                                reasons=("no failing finding is owned by a lever this loop may pull "
                                         f"({', '.join(self.levers)}); see the autopsy's owners",))
        brief = self._fitted_brief(found, parent, number, run=parent_train[0], train=train, holdout=holdout)
        clusters = tuple(cluster.key for cluster in found.clusters)
        brief_digest = hashlib.sha256(brief.encode()).hexdigest()[:16]
        common = {**base, **wide, "brief_digest": brief_digest, "failing": found.failing, "clusters": clusters}
        total = self.candidates
        # A round interrupted after its proposals resumes with them rather
        # than asking again, so its finished screens are read back, not re-run.
        proposals = self._restore(number, parent, brief_digest, champion) if self.wide else []
        for index in range(len(proposals) + 1, total + 1):
            lever = pulls[(index - 1) % len(pulls)]
            try:
                if lever == "interface":
                    proposals.append(self._propose_interface(index, total, number, found, parent_train[0], champion,
                                                             proposals))
                    if proposals[-1].status == "questions":
                        item = proposals.pop()
                        return RoundReceipt(**common, **self._screening(total, proposals), decision="questions",
                                            authoring=item.authoring, questions=item.reasons, lever="interface",
                                            reasons=("the proposer asked questions only the operator can answer",))
                    if self.wide:
                        self._journal(number, parent, brief_digest, proposals)
                    continue
                authored = self._propose(parent, brief, number, stem, protected,
                                         index=None if total == 1 else index, total=total,
                                         earlier=[item.brief_line() for item in proposals], judged_against=champion)
            except _ProposerFailed as failure:
                return RoundReceipt(**common, **self._screening(total, proposals), decision="proposer_error",
                                    reasons=(f"the proposer failed: {type(failure.error).__name__}: {failure.error}",))
            verdict = authored.verdict
            if verdict.status == "questions":
                return RoundReceipt(**common, **self._screening(total, proposals), decision="questions",
                                    authoring=tuple(authored.rounds), questions=verdict.questions,
                                    reasons=("the proposer asked questions only the operator can answer",))
            proposals.append(self._judge_proposal(index, authored, parent, champion, proposals))
            if self.wide:
                self._journal(number, parent, brief_digest, proposals)
        valid = [item for item in proposals if item.status == "valid"]
        if not valid:
            pick = next((item for item in proposals if item.status != "refused"), proposals[0])
            tag: dict[str, Any] = {"lever": pick.lever} if self.interface is not None else {}
            if pick.status == "refused" or pick.candidate is None:
                return RoundReceipt(**common, **self._screening(total, proposals), **tag, decision="refused",
                                    authoring=pick.authoring, reasons=pick.reasons)
            named = _identity(pick.candidate) if pick.lever == "agent" else self._interface_identity(pick.variant)
            return RoundReceipt(**common, **self._screening(total, proposals), **tag, decision="unchanged",
                                authoring=pick.authoring, candidate=named, reasons=pick.reasons)
        finalists, screen = list(valid), None
        if total > 1:
            finalists, screen = self._screen(valid, champion_train, train, number, grader)
        # Each finalist is judged by the unchanged training gate against the
        # current champion; the best that passes (by mean delta, then by its
        # screening rank) is the round's candidate.
        judged: list[tuple[_Proposal, tuple[RunReport, ...], Gate]] = []
        for item in finalists:
            assert item.candidate is not None
            self._candidates[item.candidate.digest] = item.candidate
            runs = self._pinned_runs(item.candidate, train, self._train_label, grader, variant=item.variant)
            gate = self._gate(champion_train, runs, name="train", min_delta=min_train, strict=False,
                              max_fall=max_fall, values=self.values)
            # The archive holds agent policies; an interface candidate is not one.
            if archive is not None and item.lever == "agent":
                self._archive_add(archive, item.candidate, runs, train, number, parent)
            judged.append((item, runs, gate))
        passing = [position for position, entry in enumerate(judged) if entry[2].passed]
        best = min(passing if passing else list(range(len(judged))),
                   key=lambda position: (-judged[position][2].mean_delta, position))
        chosen, candidate_train, train_gate = judged[best]
        extra = self._screening(total, proposals, judged=judged, screen=screen)
        if chosen.lever == "interface":
            return self._finish_interface(number, {**common, **extra}, champion, chosen, champion_train,
                                          candidate_train, train_gate, train, holdout, grader,
                                          min_train=min_train, min_held=min_held, max_fall=max_fall)
        if self.interface is not None:
            extra = {**extra, "lever": "agent"}
        assert chosen.candidate is not None
        candidate: ResolvedPack = chosen.candidate
        rounds = chosen.authoring
        changed: dict[str, Any] = {"diff": chosen.diff, "diff_hunks": len(diffs.hunks(chosen.diff))}
        if not train_gate.passed:
            return RoundReceipt(**common, **extra, **changed, decision="rejected", authoring=rounds,
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
                if archive is not None:
                    self._archive_add(archive, candidate, candidate_train, train, number, parent)
        # Only now, with a candidate through the training gate, are the
        # held-out cases run: screening and the archive never touch them.
        held_gate, trial = self._holdout_experiment(number, champion, candidate, holdout, grader,
                                                    min_held=min_held, max_fall=max_fall)
        return RoundReceipt(**common, **extra, **changed, decision="promoted" if held_gate.passed else "rejected",
                            authoring=rounds, candidate=_identity(candidate), train=train_gate, holdout=held_gate,
                            reasons=held_gate.reasons, ablation=ablation,
                            qualification=trial.reservation if trial is not None else None)

    # -- wide search ------------------------------------------------------------

    def _check_search(self) -> None:
        if self.candidates < 1:
            raise ValueError(f"candidates must be at least 1, not {self.candidates}")
        if self.finalists < 1:
            raise ValueError(f"finalists must be at least 1, not {self.finalists}")
        if self.screen_cases < 1:
            raise ValueError(f"screen_cases must be at least 1, not {self.screen_cases}")
        if self.parents not in PARENT_MODES:
            raise ValueError(f"parents is one of {', '.join(PARENT_MODES)}, not {self.parents!r}")
        if self.round_budget is not None and self.round_budget < 1:
            raise ValueError(f"round_budget must be at least 1 case-run, not {self.round_budget}")

    def _search_settings(self) -> dict[str, Any]:
        return {"candidates": self.candidates, "screen_cases": self.screen_cases, "finalists": self.finalists,
                "parents": self.parents, "round_budget": self.round_budget}

    def _judge_proposal(self, index: int, authored: Any, parent: ResolvedPack, champion: ResolvedPack,
                        earlier: Sequence[_Proposal]) -> _Proposal:
        """What one interview produced, before anything runs it: valid, refused, unchanged or a duplicate."""
        rounds = tuple(authored.rounds)
        verdict = authored.verdict
        summary = summary_line(verdict.message)
        if verdict.status != "accepted" or verdict.resolved is None:
            return _Proposal(index, "refused", rounds, reasons=tuple(verdict.findings[:12]), summary=summary)
        candidate: ResolvedPack = verdict.resolved
        proposed_diff = _diff(champion, candidate)
        if candidate.data == champion.data or not proposed_diff:
            return _Proposal(index, "unchanged", rounds, candidate, ("the proposal restates the champion's policy",),
                             summary)
        if candidate.data == parent.data:
            return _Proposal(index, "unchanged", rounds, candidate, ("the proposal restates its draft's policy",),
                             summary)
        for item in earlier:
            if item.status == "valid" and item.candidate is not None and item.candidate.data == candidate.data:
                return _Proposal(index, "duplicate", rounds, candidate, (f"the same change as candidate {item.index}",),
                                 summary, proposed_diff, duplicate_of=item.index)
        return _Proposal(index, "valid", rounds, candidate, (), summary, proposed_diff)

    def _screening(self, total: int, proposals: Sequence[_Proposal], *,
                   judged: Sequence[tuple[_Proposal, tuple[RunReport, ...], Gate]] = (),
                   screen: Mapping[str, Any] | None = None) -> dict[str, Any]:
        """The receipt's ``screening`` field, for a round that asked for more than one candidate."""
        if total == 1:
            return {}
        gates = {item.index: gate for item, _, gate in judged}
        records: list[CandidateRecord] = []
        for item in proposals:
            gate = gates.get(item.index)
            if gate is not None:
                records.append(item.record(status="finalist", train_mean_delta=gate.mean_delta,
                                           train_passed=gate.passed))
            elif item.status == "valid" and judged:
                records.append(item.record(status="screened_out"))
            else:
                records.append(item.record())
        return {"screening": Screening(requested=total, candidates=tuple(records), **dict(screen or {}))}

    def _screen(self, valid: Sequence[_Proposal], champion_train: Sequence[RunReport], train: Sequence[EvalCase],
                number: int, grader: dict[str, Any]) -> tuple[list[_Proposal], dict[str, Any]]:
        """Successive halving over training cases: the finalists, and what the receipt records of it.

        Stage one runs every candidate once on the first ``screen_cases``
        cases of ``screen_order``; each stage keeps the better half (rounded
        up, never fewer than ``finalists``) by paired mean delta against the
        champion's training runs on the same cases, which cost nothing more,
        then doubles the prefix and runs the survivors on the new cases only.
        It stops when ``finalists`` remain, or on the whole training set,
        where the best ``finalists`` go on. A stage that would take the
        round's screening plus its finalists' full training runs past
        ``round_budget`` is not started; the ranking so far decides.
        """
        budget = self.round_budget
        if len(valid) <= self.finalists:
            return list(valid), {"finalists": tuple(item.index for item in valid), "stopped": "not_needed",
                                 "budget": budget}
        case_set = case_set_digest(train)
        seed = screen_seed(case_set, number)
        strata = autopsy(champion_train[0], cases=train)
        order = screen_order([case.id for case in train], [(cluster.key, cluster.case_ids) for cluster in strata.clusters],
                             seed)
        baseline = case_scores(champion_train)
        reserved = self.finalists * self.repeats * len(train)
        size = min(self.screen_cases, len(order))
        alive = list(valid)
        scores: dict[int, dict[str, float]] = {item.index: {} for item in valid}
        stages: list[ScreenStage] = []
        covered = 0
        spent = 0
        stopped = "finalists"
        while True:
            fresh = order[covered:size]
            cost = len(alive) * len(fresh)
            if budget is not None and spent + cost + reserved > budget:
                stopped = "budget"
                break
            wanted = frozenset(fresh)
            ran = [case for case in train if case.id in wanted]
            label = f"screen/{case_set_digest(ran)[:12]}"
            for item in alive:
                assert item.candidate is not None
                scores[item.index].update(case_scores((self._pinned_run(item.candidate, ran, label, grader,
                                                                        variant=item.variant),)))
            spent += cost
            subset = order[:size]
            deltas = {item.index: paired_delta(scores[item.index], baseline, subset) for item in alive}
            ranked = sorted(alive, key=lambda item: (-deltas[item.index], item.index))
            whole = size >= len(order)
            keep = halving_keep(len(ranked), self.finalists, whole)
            stages.append(ScreenStage(
                stage=len(stages) + 1, cases=tuple(subset), ran=tuple(fresh),
                scores=tuple(ScreenScore(index=item.index, digest=item.digest,
                                         mean_delta=deltas[item.index], cases=len(subset)) for item in ranked),
                advanced=tuple(item.index for item in ranked[:keep]), cost=cost))
            alive = ranked[:keep]
            covered = size
            if whole or len(alive) <= self.finalists:
                stopped = "whole_set" if whole and len(ranked) > self.finalists else "finalists"
                break
            size = min(size * 2, len(order))
        chosen = alive[: self.finalists]
        return chosen, {"seed": seed, "order": order, "stages": tuple(stages),
                        "finalists": tuple(item.index for item in chosen), "stopped": stopped, "budget": budget,
                        "cost": spent}

    def _branch(self, number: int, champion: ResolvedPack, champion_train: Sequence[RunReport],
                train: Sequence[EvalCase], grader: dict[str, Any],
                ) -> tuple[Archive | None, ResolvedPack, tuple[RunReport, ...], dict[str, Any]]:
        """The archive, and the parent this round's proposals revise, with its training runs and the receipt's record.

        The champion is archived first. With ``parents="archive"`` the
        parent is drawn (``select_parent``) from the Pareto frontier of what
        earlier rounds archived plus the champion, over members that still
        fail a training case, weighted toward a high mean and few visits.
        """
        chosen: dict[str, Any] = {"mode": "champion", **_identity(champion)}
        found = autopsy(champion_train[0], cases=train)
        if found.failing == 0:
            return None, champion, tuple(champion_train), chosen
        case_set = case_set_digest(train)
        archive = Archive(self.out / "archive", case_set=case_set, grader=grader["digest"])
        archive.fix_clusters([(cluster.key, cluster.case_ids) for cluster in found.clusters],
                             [case.id for case in train])
        self._archive_add(archive, champion, champion_train, train, number, None, failing=found.failing)
        if self.parents == "champion":
            return archive, champion, tuple(champion_train), chosen
        # Only what earlier rounds archived, and the champion: a round
        # interrupted after archiving its own finalists draws the same parent
        # when it resumes.
        pool = {digest: entry for digest, entry in sorted(archive.entries.items())
                if entry.round < number or digest == champion.digest}
        frontier = pareto_frontier({digest: entry.clusters for digest, entry in pool.items()})
        visits = self._visits()
        members = [(digest, pool[digest].mean, visits.get(digest, 0)) for digest in frontier
                   if pool[digest].failing > 0]
        if not members:
            return archive, champion, tuple(champion_train), {
                **chosen, "reason": "no frontier member fails a training case; the champion is the parent"}
        digest, draw, weights = select_parent(members, parent_seed(case_set, number, frontier))
        entry = pool[digest]
        parent = champion if digest == champion.digest else self._materialise(entry.ref, entry.digest, entry.envelope)
        record = {"mode": "archive", "draw": draw,
                  "frontier": [{"digest": item, "ref": pool[item].ref, "mean": pool[item].mean,
                                "visits": visits.get(item, 0), "weight": weights.get(item)} for item in frontier]}
        if parent is None:
            return archive, champion, tuple(champion_train), {
                **record, **_identity(champion), "reason": f"{entry.ref}@{entry.digest} no longer resolves"}
        runs = tuple(champion_train) if parent is champion else self._pinned_runs(parent, train, self._train_label, grader)
        return archive, parent, runs, {**record, **_identity(parent)}

    def _archive_add(self, archive: Archive, pack: ResolvedPack, runs: Sequence[RunReport], train: Sequence[EvalCase],
                     number: int, parent: ResolvedPack | None, *, failing: int | None = None) -> None:
        if failing is None:
            failing = autopsy(runs[0], cases=train).failing
        archive.add(digest=pack.digest, ref=pack.ref, envelope=_envelope(pack), runs=runs, failing=failing,
                    round_number=number, parent=None if parent is None or parent.digest == pack.digest else parent.digest,
                    repeats=self.repeats)

    def _visits(self) -> dict[str, int]:
        """How many receipted rounds proposed from each policy: the parent a receipt names, else its champion."""
        counts: dict[str, int] = {}
        rounds_dir = self.out / "rounds"
        if not rounds_dir.is_dir():
            return counts
        for path in sorted(rounds_dir.glob("*.json")):
            if not path.stem.isdigit():
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(document, dict) or document.get("decision") == "no_failures":
                continue
            identity = document.get("parent") if isinstance(document.get("parent"), dict) else document.get("champion")
            if isinstance(identity, dict) and isinstance(identity.get("digest"), str):
                counts[identity["digest"]] = counts.get(identity["digest"], 0) + 1
        return counts

    def _materialise(self, ref: str, digest: str, envelope: Mapping[str, Any] | None) -> ResolvedPack | None:
        """A pack by reference and digest: resolved from the pack roots, or rebuilt from its stored envelope.

        Ablation installs a reduced candidate under the proposed one's name,
        so an archived proposal may no longer resolve by name; its envelope
        still rebuilds it, and the digest must match.
        """
        held = self._candidates.get(digest)
        if held is not None:
            return held
        resolved: ResolvedPack | None
        try:
            resolved = packkit.resolve(f"{ref}@{digest}", kind_name="agent", roots=self._search())
        except (ValueError, LookupError, OSError):
            resolved = None
        if resolved is None and envelope:
            try:
                resolved, _ = check(PackEnvelope(**dict(envelope)), roots=self._search(), into=self.out / "packs")
            except ValueError:
                resolved = None
        if resolved is None or resolved.digest != digest:
            return None
        self._candidates[digest] = resolved
        return resolved

    def _journal_path(self, number: int) -> Path:
        return self.out / "proposals" / f"{number:03d}.json"

    def _journal(self, number: int, parent: ResolvedPack, brief_digest: str, proposals: Sequence[_Proposal]) -> None:
        """The round's proposals so far, for a resume: removed once the round's receipt is written."""
        _write(self._journal_path(number), {
            "schema": "worldloom.improve-proposals/v1", "round": number, "parent": parent.digest,
            "brief_digest": brief_digest, "total": self.candidates,
            "proposals": [{"index": item.index, "status": item.status, "authoring": list(item.authoring),
                           "reasons": list(item.reasons), "summary": item.summary, "duplicate_of": item.duplicate_of,
                           "ref": None if item.candidate is None else item.candidate.ref,
                           "digest": None if item.candidate is None else item.candidate.digest,
                           "envelope": None if item.candidate is None else _envelope(item.candidate),
                           # An interface proposal keeps its manifests, from which it is rebuilt.
                           **({"lever": "interface", "tree": item.variant.tree if item.variant is not None else None}
                              if item.lever == "interface" else {})}
                          for item in proposals]})

    def _restore(self, number: int, parent: ResolvedPack, brief_digest: str,
                 champion: ResolvedPack) -> list[_Proposal]:
        """The proposals an interrupted run of this round already had, when they were made for this parent and brief."""
        try:
            document = json.loads(self._journal_path(number).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []
        if (not isinstance(document, dict) or document.get("round") != number
                or document.get("parent") != parent.digest or document.get("brief_digest") != brief_digest
                or document.get("total") != self.candidates):
            return []
        restored: list[_Proposal] = []
        for entry in document.get("proposals") or ():
            if not isinstance(entry, dict) or entry.get("index") != len(restored) + 1:
                break
            if entry.get("lever") == "interface":
                restored_item = self._restore_interface(entry, len(restored) + 1, champion)
                if restored_item is None:
                    break
                restored.append(restored_item)
                continue
            candidate = None
            if isinstance(entry.get("digest"), str):
                candidate = self._materialise(str(entry.get("ref")), entry["digest"], entry.get("envelope"))
                if candidate is None:
                    break
            status = str(entry.get("status"))
            restored.append(_Proposal(
                index=len(restored) + 1, status=status, authoring=tuple(entry.get("authoring") or ()),
                candidate=candidate, reasons=tuple(entry.get("reasons") or ()), summary=str(entry.get("summary", "")),
                diff=_diff(champion, candidate) if candidate is not None and status in {"valid", "duplicate"} else "",
                duplicate_of=entry.get("duplicate_of")))
        return restored

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
            trial_run = self._pinned_runs(trial, train, self._train_label, grader)
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

    # -- the interface lever ------------------------------------------------------

    def _check_levers(self) -> None:
        from .interface import LEVERS

        if not self.levers or any(lever not in LEVERS for lever in self.levers):
            raise ValueError(f"levers are {', '.join(LEVERS)}; got {', '.join(self.levers) or 'none'}")
        if "interface" in self.levers and self.interface is None:
            raise ValueError("the interface lever needs the served contract bundles (an InterfaceLever: "
                             "--connectors anvil --contract CONNECTOR=<bundle>)")

    def _pullable(self, found: Any) -> tuple[str, ...]:
        """The levers this round may pull, in the order its candidates take them.

        An unqualified agent-only loop keeps its original attribution rules.
        Qualification and interface loops pull only levers that own a failing
        finding. With both,
        the first candidate goes to the lever that owns more of them (the
        agent on a tie) and the rest alternate, so wide search tries both;
        when neither owns one (every finding is the world's or the grader's)
        nothing is pulled.
        """
        if found.ownership is None:
            return tuple(self.levers)
        owned = {share.owner: share.findings for share in found.ownership.owners}
        if not any(owned.get(lever, 0) for lever in self.levers):
            return ()
        if len(self.levers) == 1:
            return tuple(self.levers)
        return ("interface", "agent") if owned["interface"] > owned["agent"] else ("agent", "interface")

    def _interface_identity(self, variant: Any) -> dict[str, Any]:
        return {"ref": _interface_ref(variant), "digest": variant.digest}

    def _interface_record(self, variant: Any) -> dict[str, Any]:
        """What a receipt records of an interface candidate: overlays, recompiled contracts, the base's."""
        from .interface import overlay_digests

        lever = self.interface
        compiled = lever.compile(variant)
        record: dict[str, Any] = {
            "variant": variant.digest, "champion": self._variant.digest,
            "overlays": overlay_digests(lever.base, variant),
            "contracts": dict(sorted(compiled.digests.items())),
            "base_contracts": {name: source.contract_digest for name, source in sorted(lever.sources.items())}}
        if compiled.approved_for_simulation:
            record["approved_for_simulation"] = {name: list(ids) for name, ids
                                                 in sorted(compiled.approved_for_simulation.items())}
        return record

    def _interface_summary(self, initial: Any) -> dict[str, Any]:
        from .interface import overlay_digests

        compiled = self.interface.compile(self._variant)
        return {"initial": initial.digest, "champion": self._variant.digest,
                "overlays": overlay_digests(self.interface.base, self._variant),
                "contracts": dict(sorted(compiled.digests.items()))}

    def _propose_interface(self, index: int, total: int, number: int, found: Any, run: RunReport,
                           champion: ResolvedPack, earlier: Sequence[_Proposal]) -> _Proposal:
        """One interface interview: the interface-owned findings and their traces, answered with an overlay diff."""
        from ..packkit.authoring import MAX_MESSAGE
        from .interface import author_overlay, interface_brief

        parent = self._variant
        label = f"interface@{parent.digest[:12]}"
        notes = ""
        if total > 1:
            notes = "\n\n" + packkit.text("evalrun.improve.rule.candidates", index=index, total=total,
                                          earlier="\n".join(item.brief_line() for item in earlier) or "(none yet)")
        skeleton = packkit.text("evalrun.improve.interface.message", round=number, champion=label, brief="")
        brief, touched = interface_brief(found, run, room=max(MAX_MESSAGE - len(skeleton) - len(notes), 400))
        message = packkit.text("evalrun.improve.interface.message", round=number, champion=label, brief=brief) + notes

        def exchange(payload: dict[str, Any]) -> dict[str, Any]:
            try:
                return self.exchange(payload)
            except _PROPOSER_ERRORS as error:
                raise _ProposerFailed(error) from error

        name = f"interface-r{number}" + ("" if total == 1 else f"-c{index}")
        authored = author_overlay(message, exchange, self.interface, parent, name=name,
                                  max_rounds=self.authoring_rounds, touched=touched)
        verdict = authored.verdict
        rounds = tuple(authored.rounds)
        summary = summary_line(verdict.message)
        if verdict.status == "questions":
            return _Proposal(index, "questions", rounds, reasons=verdict.questions, summary=summary, lever="interface")
        if verdict.status != "accepted" or verdict.variant is None:
            return _Proposal(index, "refused", rounds, reasons=tuple(verdict.findings[:12]), summary=summary,
                             lever="interface")
        variant = verdict.variant
        self._variants[variant.digest] = variant
        diff = diffs.render(parent.tree, variant.tree)
        if variant.digest == parent.digest or not diff:
            return _Proposal(index, "unchanged", rounds, champion, ("the proposal restates the champion interface",),
                             summary, lever="interface", variant=variant)
        for item in earlier:
            if item.lever == "interface" and item.status == "valid" and item.variant is not None \
                    and item.variant.digest == variant.digest:
                return _Proposal(index, "duplicate", rounds, champion, (f"the same change as candidate {item.index}",),
                                 summary, diff, duplicate_of=item.index, lever="interface", variant=variant)
        return _Proposal(index, "valid", rounds, champion, (), summary, diff, lever="interface", variant=variant)

    def _restore_interface(self, entry: Mapping[str, Any], index: int, champion: ResolvedPack) -> _Proposal | None:
        """A journaled interface proposal, rebuilt from its manifests; ``None`` when it no longer can be."""
        from .interface import InterfaceVariant

        tree = entry.get("tree")
        status = str(entry.get("status"))
        if self.interface is None:
            return None
        variant = None
        if isinstance(tree, dict):
            variant = InterfaceVariant.from_tree(tree)
            self._variants[variant.digest] = variant
        elif status in {"valid", "duplicate", "unchanged"}:
            return None
        return _Proposal(index=index, status=status, authoring=tuple(entry.get("authoring") or ()),
                         candidate=champion if variant is not None else None,
                         reasons=tuple(entry.get("reasons") or ()), summary=str(entry.get("summary", "")),
                         diff=diffs.render(self._variant.tree, variant.tree) if variant is not None else "",
                         duplicate_of=entry.get("duplicate_of"), lever="interface", variant=variant)

    def _finish_interface(self, number: int, common: Mapping[str, Any], champion: ResolvedPack, chosen: _Proposal,
                          champion_train: Sequence[RunReport], candidate_train: Sequence[RunReport], train_gate: Gate,
                          train: Sequence[EvalCase], holdout: Sequence[EvalCase], grader: dict[str, Any], *,
                          min_train: float, min_held: float, max_fall: float) -> RoundReceipt:
        """The gates after training for an interface candidate: ablation, holdout, transfer, then promotion."""
        from .interface import write_promotion

        variant = chosen.variant
        rounds = chosen.authoring
        changed: dict[str, Any] = {"diff": chosen.diff, "diff_hunks": len(diffs.hunks(chosen.diff))}
        if not train_gate.passed:
            return RoundReceipt(**common, **changed, lever="interface", decision="rejected", authoring=rounds,
                                candidate=self._interface_identity(variant), interface=self._interface_record(variant),
                                train=train_gate, reasons=train_gate.reasons)
        ablation = None
        if self.ablate:
            variant, candidate_train, ablation = self._ablate_interface(
                champion, variant, champion_train, candidate_train, train, grader, min_train=min_train,
                max_fall=max_fall)
            if ablation.reduced:
                assert ablation.reduced_train is not None
                train_gate = ablation.reduced_train
                reduced = diffs.render(self._variant.tree, variant.tree)
                changed = {"diff": reduced, "diff_hunks": len(diffs.hunks(reduced))}
        # Only now are the held-out cases run, as for an agent candidate.
        held_gate, trial = self._holdout_experiment(number, champion, champion, holdout, grader,
                                                    min_held=min_held, max_fall=max_fall, variant=variant)
        if trial is not None:
            holdout = trial.cases
        record = self._interface_record(variant)
        reasons = list(held_gate.reasons)
        transfer: Gate | None = None
        if not held_gate.passed:
            record["transfer"] = {"skipped": "the holdout gate failed, so the transfer agent was never run"}
        else:
            transfer, skipped = self._transfer_gate(champion, variant, holdout, grader, max_fall=max_fall,
                                                     trial=trial)
            if transfer is None:
                record["transfer"] = {"skipped": skipped}
            else:
                record["transfer"] = {"passed": transfer.passed}
                reasons.extend(f"transfer: {reason}" for reason in transfer.reasons)
        promoted = held_gate.passed and (transfer is None or transfer.passed)
        if promoted:
            record["promotion"] = write_promotion(self.interface, self._variant, variant, round_number=number)
        return RoundReceipt(**common, **changed, lever="interface", decision="promoted" if promoted else "rejected",
                            authoring=rounds, candidate=self._interface_identity(variant), train=train_gate,
                            holdout=held_gate, transfer=transfer, interface=record, reasons=tuple(reasons),
                            ablation=ablation, qualification=trial.reservation if trial is not None else None)

    def _transfer_gate(self, champion: ResolvedPack, variant: Any, holdout: Sequence[EvalCase],
                       grader: dict[str, Any], *, max_fall: float,
                       trial: QualificationTrial | None = None) -> tuple[Gate | None, str]:
        """The second agent on the held-out cases under the champion interface and under *variant*.

        An interface change is for every agent a company serves, not the one
        it was tuned on: the second agent must not lose more than the delta
        band on the mean or any axis, nor error where it was graded.
        """
        if self.transfer is None:
            return None, "no transfer agent was given (--transfer-agent); the gate was skipped"
        if trial is not None and fingerprint(self.transfer) != trial.reservation["champion"].get("transfer_harness"):
            raise ValueError("transfer harness changed after the qualification reservation")
        ident = hashlib.sha256(json.dumps(fingerprint(self.transfer), sort_keys=True,
                                          default=str).encode()).hexdigest()[:12]

        def runs(served: Any) -> tuple[RunReport, ...]:
            slug = f"transfer@{ident}" + ("" if served.digest == self.interface.base.digest
                                          else f"+if-{served.digest[:12]}")
            repeats: list[int | None] = [None] if self.repeats == 1 else list(range(1, self.repeats + 1))
            label = "holdout" if trial is None else trial.label
            return tuple(self._pinned_run(champion, holdout, label, grader, repeat=repeat, variant=served,
                                          agent=self.transfer, slug=slug) for repeat in repeats)

        before, after = runs(self._variant), runs(variant)
        if trial is not None:
            return self._qualified_gate(before, after, trial=trial, name="transfer", min_delta=-max_fall,
                                        max_fall=max_fall), ""
        if self.repeats == 1:
            return judge(compare(before[0], after[0]), name="transfer", min_delta=-max_fall, strict=False,
                         max_axis_regression=max_fall), ""
        return judge_paired(self._paired(before, after), name="transfer", min_delta=-max_fall, strict=False,
                            max_axis_regression=max_fall, min_ci=-max_fall), ""

    def _ablate_interface(self, champion: ResolvedPack, variant: Any, champion_train: Sequence[RunReport],
                          candidate_train: Sequence[RunReport], train: Sequence[EvalCase], grader: dict[str, Any], *,
                          min_train: float, max_fall: float) -> tuple[Any, tuple[RunReport, ...], Ablation]:
        """``_ablate`` for an overlay: each hunk of the manifest diff taken out in turn, relinted and recompiled."""
        tolerance = delta_band() / 2 if self.ablation_tolerance is None else self.ablation_tolerance
        parent = self._variant
        proposed_diff = diffs.render(parent.tree, variant.tree)
        every = diffs.hunks(proposed_diff)
        keep = list(range(len(every)))
        current, current_run = variant, tuple(candidate_train)
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
            trial, findings = self.interface.lint(parent, diffs.join(every[index] for index in remaining))
            if trial is None:
                records.append(_contribution(hunk, position, decision="kept",
                                             reason=f"the rest does not lint without it: {'; '.join(findings[:2])}"))
                continue
            self._variants[trial.digest] = trial
            trial_run = self._pinned_runs(champion, train, self._train_label, grader, variant=trial)
            cost, bounds = self._cost(trial_run, current_run)
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
        ablation = Ablation(proposed=self._interface_identity(variant), proposed_diff=proposed_diff,
                            tolerance=tolerance, hunks=tuple(records))
        if current is variant:
            return variant, tuple(candidate_train), ablation
        gate = self._gate(champion_train, current_run, name="train", min_delta=min_train, strict=False,
                          max_fall=max_fall, values=self.values)
        if not gate.passed:
            return variant, tuple(candidate_train), ablation.model_copy(update={
                "reduced_train": gate,
                "reason": "the reduced candidate fails the training gate; the proposed one goes to the holdout"})
        return current, current_run, ablation.model_copy(update={"reduced": True, "reduced_train": gate})


def _interface_ref(variant: Any) -> str:
    """An interface candidate's reference: ``interface:`` and the connectors it covers."""
    return "interface:" + "+".join(connector for connector, _ in variant.manifests)


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


def _optional_int(value: Any) -> int | None:
    """A policy count where 0 (or nothing) means no limit: a pack cannot hold a null, which removes a key."""
    return int(value) if value else None


def _envelope(pack: ResolvedPack) -> dict[str, Any]:
    """*pack* as the envelope that rebuilds it: kind, name, title, description and its merged body."""
    return {"kind": pack.kind, "name": pack.name, "title": pack.title, "description": pack.description,
            "body": pack.data}


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
            min_train_ci: float | None = None, brief: str | None = None,
            reference_run: RunReport | None = None, candidates: int | None = None, screen_cases: int | None = None,
            finalists: int | None = None, parents: str | None = None,
            round_budget: int | None = None, levers: Sequence[str] | str | None = None, interface: Any = None,
            transfer: AgentUnderTest | None = None,
            qualification: QualificationPolicy | None = None, curriculum: str | None = None,
            curriculum_pool: Sequence[EvalCase] | None = None,
            curriculum_cases: int | None = None) -> ImproveReport:
    """Run the loop from *champion* over *cases*; the held-out cases are *holdout* or a stable share of *cases*.

    A separate *holdout* (cases compiled from fresh seeds) is the stronger
    test: a policy that learned this company rather than the task fails
    there. Without one, a share of *cases* is held back by case id.

    *repeats* (default: the policy ``evalrun.improve.repeats``, 1) runs each
    policy that many times over each case set and judges every comparison as
    a paired test over per-case means (``judge_paired``); *confidence*,
    *resamples* and *min_train_ci* tune that test and default to their
    ``evalrun.improve.*`` policies.

    *brief* (default: the policy ``evalrun.improve.brief``, ``summary``) is
    what the proposer is shown; ``traces`` adds the connectors' own error
    messages, the arguments behind them, the tools' contracts and failing
    trajectories (``evidence``), with accepted calls from *reference_run*,
    a reference-agent run over the training cases, when one is given.
    Wide search: *candidates* proposals a round (``evalrun.improve.candidates``,
    1), screened by successive halving from *screen_cases* training cases
    (``.screen_cases``, 6) down to *finalists* (``.finalists``, 1) that go
    through the full gates; *parents* (``.parents``, ``champion``) set to
    ``archive`` draws each round's parent from the Pareto frontier of the
    archive; *round_budget* (``.round_budget``, none) caps the case-runs a
    round's screening and finalists may cost. At the defaults a round is the
    narrow loop, receipts to the byte.

    *levers* (``agent``, ``interface`` or both; default ``agent``) says what a
    round may change. ``interface`` needs *interface*, an
    ``evalrun.interface.InterfaceLever`` over the served contract bundles;
    *transfer* is the second agent an interface candidate must not regress
    on the held-out cases (the gate is skipped, and says so, without one).

    *qualification* seals a bounded pool of fresh promotion tranches before
    proposing. Evidence components remain intact; each reaching candidate
    reserves one tranche before execution. Confidence is nominally allocated
    over the probe budget and intervals resample components and whole repeat
    batches. Cases need served-snapshot provenance from
    ``with_record_provenance`` and sufficient independently grounded units.

    A domain runner may implement ``run_experiment(cases, agent, *, directory,
    label, repeat, grader)`` to distinguish checkpointed repeats, and
    ``grading_identity(rater)`` to extend the core grader's identity with
    its own measured domain. The full identity is frozen around execution
    and when resuming; ordinary two-argument runners keep their contract.
    Optional ``validate_cases(cases)`` verifies domain provenance before
    sealing and before any execution or cached-run reuse.

    *curriculum* ``failures`` grows the training set between rounds: after
    each round, *curriculum_cases* (default 8) cases of *curriculum_pool* are
    drawn for the clusters that round's champion failed, by the declared
    mapping ``failure_curriculum.FINDING_TARGETS`` and weighted by cluster
    size, and join the next round's training cases. A pool case that shares
    an id, a content key, a source-record digest or a gold-DAG digest with a
    held-out case, declares a held-out split, or would have been held out by
    the share split, is never drawn. The next round's receipt records which
    clusters drove which cases. Without it (the default) the training set is
    fixed and nothing about the loop changes.
    """
    from .evidence import admit_reference, brief_mode
    from .interface import parse_levers

    dropped = 0
    exclude: Callable[[EvalCase], bool] | None = None
    if holdout is None:
        share = float(packkit.policy("evalrun.improve.holdout_share")) if holdout_share is None else holdout_share
        train, held = (split_cases(cases, holdout_share=share) if qualification is None else
                       isolated_splits(cases, holdout_share=share, unit_dimension=qualification.unit_dimension))

        def held_by_share(case: EvalCase) -> bool:
            # A pool case the share split would have held out stays out of
            # training, so the same corpus compiled larger never trains on
            # what a smaller compile of it held back.
            return bool(split_cases((case,), holdout_share=share)[1])

        exclude = held_by_share
    else:
        # A case the training corpus itself declares held out stays sealed
        # even when the holdout comes from elsewhere: it is dropped, counted.
        train = tuple(case for case in cases if not is_held_out(declared_split(case)))
        dropped = len(cases) - len(train)
        held = tuple(holdout)
    mode = brief_mode(brief)
    plan: FailureCurriculum | None = None
    if curriculum is not None:
        if curriculum not in CURRICULUM_MODES:
            raise ValueError(f"unknown curriculum {curriculum!r}; use one of {list(CURRICULUM_MODES)}")
        plan = FailureCurriculum(pool=tuple(curriculum_pool or ()), mode=curriculum, exclude=exclude,
                                 cases=DEFAULT_CURRICULUM_CASES if curriculum_cases is None else int(curriculum_cases))
    elif curriculum_pool is not None or curriculum_cases is not None:
        raise ValueError("curriculum_pool and curriculum_cases need curriculum='failures'")
    if reference_run is not None:
        # Refused here, before any run is paid for, as well as at every brief.
        reference_run = admit_reference(reference_run, train=train, holdout=held)
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
                        confidence=confidence, resamples=resamples, min_train_ci=min_train_ci,
                        brief_mode=mode, reference_run=reference_run,
                        candidates=int(packkit.policy("evalrun.improve.candidates")) if candidates is None
                        else int(candidates),
                        screen_cases=int(packkit.policy("evalrun.improve.screen_cases")) if screen_cases is None
                        else int(screen_cases),
                        finalists=int(packkit.policy("evalrun.improve.finalists")) if finalists is None
                        else int(finalists),
                        parents=str(packkit.policy("evalrun.improve.parents")) if parents is None else parents,
                        round_budget=_optional_int(packkit.policy("evalrun.improve.round_budget"))
                        if round_budget is None else int(round_budget),
                        levers=parse_levers(levers), interface=interface, transfer=transfer,
                        qualification=qualification, curriculum=plan)
    return improver.improve(champion, train, held,
                            rounds=int(packkit.policy("evalrun.improve.rounds")) if rounds is None else rounds,
                            min_train_delta=min_train_delta, min_holdout_delta=min_holdout_delta,
                            max_axis_regression=max_axis_regression, held_out_dropped=dropped)


__all__ = ["HELD_OUT_SPLITS", "IMPROVE_SCHEMA", "ROUND_SCHEMA", "Ablation", "Gate", "HunkContribution", "ImproveReport",
           "Improver", "RoundReceipt", "improve", "judge", "judge_paired", "round_stem", "split_cases"]
