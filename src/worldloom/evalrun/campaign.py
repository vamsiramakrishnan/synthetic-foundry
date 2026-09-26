"""Campaigns: the outer loop that keeps an agent improving after one case set has nothing left to teach.

``improve()`` runs over one fixed case set and stops when the champion passes
all of it (``no_failures``) or its rounds run out. A pass rate of one on a set
says the set is spent, not that the agent is done. A campaign is a sequence of
**stages**. Each stage has a training case set and a sealed held-out case set,
both built from seeds the campaign has never used, and runs ``improve()`` over
them until it stops. Then the campaign reads how the stage ended and decides
what the next stage is made of:

- **escalate** when the champion saturated the stage (``no_failures``) or
  plateaued (policy ``evalrun.campaign.patience`` rounds in a row without a
  promotion): ``curriculum.escalate`` over the champion's training run names
  the slices it has mastered and the harder ones beside them, and
  ``corners.frontier`` finds cases the reference solves and the champion
  fails;
- **target** when the champion still fails the stage's training cases:
  ``design_curriculum`` over the champion's autopsy asks for fresh cases of
  the kinds it fails, weighted by value when values are on, with a
  representative share kept by the mix guard.

What a stage is made of is a builder's business (``StageBuilder``): the
campaign decides the mode and the seeds and hands the builder the previous
stage's outcome; the builder returns the two case sets. Two ship here:
``DatasetStageBuilder`` compiles ``DatasetPlan``s with ``compile_dataset``,
and ``CornerStageBuilder`` draws event-grounded corner cases from seeded
worlds, searching the frontier when escalating. A test or a caller can pass
any other.

The rules the campaign holds whatever the builder does:

- **Held-out cases never train.** A case is identified by its content (id,
  request and row). A stage whose training set contains any earlier stage's
  held-out case, or whose held-out set contains a case some stage trained on,
  is refused before anything runs, and the campaign stops and says so.
  Escalation reads the champion's *training* run only; the held-out cases are
  for judging and nothing else.
- **Seeds are fresh and recorded.** A stage's seeds derive from the campaign
  seed, the stage number, the role and an index by content address, skipping
  any seed already used (including the ones a builder reserves, such as its
  base plan's), and every stage records them.
- **One grader.** The grader is pinned when the campaign starts; a campaign
  resumed under a different grader is refused (``GraderDrift``).

The headline number is the cross-stage held-out ledger: after each stage the
campaign's original champion and its current champion both run the stage's
held-out cases, which neither the proposer nor any training set ever saw, so
the report says stage by stage how far the policy has moved from where it
started. Everything lands under the output directory: ``campaign.json``,
``stages/NNN/stage.json``, the stage's case sets under ``stages/NNN/cases``,
its improve loop under ``stages/NNN/improve`` and the ledger runs under
``stages/NNN/ledger``. A stage with a ``stage.json`` is complete and is read
back, never run again; runs already on disk are reused, so an interrupted
campaign resumes without paying twice.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, NamedTuple, Protocol

from pydantic import Field

from .. import packkit
from ..ids import content_key
from ..models import Model
from .agents import AgentUnderTest, fingerprint
from .contract import EvalCase
from .grader import check_frozen, grader_identity
from .improve import ImproveReport, improve
from .results import compare, read_run, summarize, write_run
from .runner import RunReport, case_set_digest

if TYPE_CHECKING:
    from ..packkit.authoring import Exchange
    from ..packkit.resolve import ResolvedPack
    from .autopsy import Autopsy
    from .curriculum import Escalation
    from .value import ReferenceMix

CAMPAIGN_SCHEMA = "worldloom.campaign/v1"
STAGE_SCHEMA = "worldloom.campaign-stage/v1"

#: How a campaign can stop, each with its reason in ``CampaignReport.reasons``.
STOPS = ("max_stages", "case_budget", "no_new_cases", "nothing_harder", "held_out_overlap", "questions",
         "proposer_error")

#: What ``improve()`` is given by the campaign itself; a caller passing one of
#: these through ``improve_options`` would silently fight the campaign.
_OWNED = frozenset({"run", "agent_for", "exchange", "out", "rater", "holdout", "holdout_share", "pack_roots",
                    "values", "holdout_values"})


# -- records ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RecordGroups:
    """Records per world: each group's cases run over its own records and no other's.

    Two worlds reuse external keys (both have a ``WL-1``), so a case set
    compiled from several worlds (a dataset's batches, several corner seeds)
    cannot be served over one pooled record set. A plain sequence of records
    is one group holding every case.
    """

    groups: tuple[tuple[tuple[str, ...], tuple[Any, ...]], ...]

    @classmethod
    def of(cls, records: Any, cases: Sequence[EvalCase]) -> RecordGroups:
        if isinstance(records, RecordGroups):
            return records
        return cls(groups=((tuple(case.id for case in cases), tuple(records)),))

    def flat(self) -> tuple[Any, ...]:
        return tuple(record for _, records in self.groups for record in records)

    def split(self, cases: Sequence[EvalCase]) -> list[tuple[list[EvalCase], tuple[Any, ...]]]:
        """*cases* partitioned by group, each group's cases in the order given."""
        where = {case_id: index for index, (ids, _) in enumerate(self.groups) for case_id in ids}
        missing = [case.id for case in cases if case.id not in where]
        if missing:
            raise ValueError(f"{len(missing)} case(s) belong to no record group, e.g. {missing[0]}")
        parts: list[list[EvalCase]] = [[] for _ in self.groups]
        for case in cases:
            parts[where[case.id]].append(case)
        return [(part, self.groups[index][1]) for index, part in enumerate(parts) if part]


StageRunner = Callable[[Sequence[EvalCase], RecordGroups, AgentUnderTest], RunReport]


def run_grouped(cases: Sequence[EvalCase], records: RecordGroups | Sequence[Any], agent: AgentUnderTest, *,
                rater: Any = None, concurrency: int = 1, principal: str | None = None,
                definitions: Mapping[str, Any] | None = None) -> RunReport:
    """One agent over *cases*, each record group on its own service, results in case order.

    With one group this is exactly ``run_cases`` over ``service_for``, the
    run the ``improve`` command makes.
    """
    from .runner import run_cases, service_for

    groups = RecordGroups.of(records, cases)
    parts = groups.split(cases)
    reports = [run_cases(service_for(part, held, concurrency=concurrency, definitions=definitions or None), part,
                         agent, principal=principal, rater=rater, concurrency=concurrency)
               for part, held in parts]
    if len(reports) == 1:
        return reports[0]
    by_id = {result.case_id: result for report in reports for result in report.results}
    first = reports[0]
    return first.model_copy(update={"case_set": case_set_digest(cases),
                                    "results": tuple(by_id[case.id] for case in cases)})


# -- seeds -------------------------------------------------------------------------------


class StageSeeds(Model):
    """The seeds one stage's case sets were built from: never used by an earlier stage, nor reserved."""

    train: tuple[int, ...]
    held: tuple[int, ...]

    def all(self) -> tuple[int, ...]:
        return (*self.train, *self.held)


def stage_seed(campaign_seed: int, stage: int, role: str, index: int = 0, attempt: int = 0) -> int:
    """One seed, content-addressed from the campaign seed, the stage, the role and the index."""
    parts = [str(campaign_seed), str(stage), role, str(index)] + ([str(attempt)] if attempt else [])
    return int(content_key("worldloom-campaign-seed", *parts)[:8], 16)


def stage_seeds(campaign_seed: int, stage: int, *, count: int = 1, used: Iterable[int] = ()) -> StageSeeds:
    """*count* training and *count* held-out seeds for *stage*, none of them in *used* or each other.

    A collision (vanishingly rare with 32-bit seeds, but a campaign must not
    rely on luck) moves to the next attempt of the same derivation, so the
    result is still a pure function of its inputs.
    """
    if stage < 1 or count < 1:
        raise ValueError("stages start at 1 and a set needs at least one seed")
    taken = set(used)
    chosen: dict[str, list[int]] = {"train": [], "held": []}
    for role in ("train", "held"):
        for index in range(count):
            attempt = 0
            seed = stage_seed(campaign_seed, stage, role, index)
            while seed in taken:
                attempt += 1
                seed = stage_seed(campaign_seed, stage, role, index, attempt)
            taken.add(seed)
            chosen[role].append(seed)
    return StageSeeds(train=tuple(chosen["train"]), held=tuple(chosen["held"]))


def case_key(case: EvalCase) -> str:
    """A case's content address: id, request and row. The same key ``improve`` refuses overlap by."""
    return hashlib.sha256(json.dumps({"id": case.id, "query": case.query, "row": case.row}, sort_keys=True,
                                     default=str).encode()).hexdigest()


# -- the builder seam -----------------------------------------------------------------------


class StageExhausted(ValueError):
    """The builder cannot produce new cases for this stage; the message says why."""

    code = "no_new_cases"


class NothingHarder(StageExhausted):
    """Escalation proposes nothing harder than what the champion has mastered."""

    code = "nothing_harder"


@dataclass(frozen=True)
class StageOutcome:
    """How a stage (or the baseline, stage 0) left the champion: what the next stage is built from."""

    stage: int
    #: ``baseline``, ``saturated``, ``plateaued``, ``failing`` or ``halted``.
    status: str
    champion: ResolvedPack
    train_cases: tuple[EvalCase, ...]
    train_records: RecordGroups
    #: The champion's run over the training cases, as the stage ended.
    champion_run: RunReport
    report: ImproveReport | None = None
    values: Mapping[str, Any] | None = None


@dataclass(frozen=True)
class StageRequest:
    """What a builder is asked for: one stage's two case sets, from these seeds, in this mode."""

    stage: int
    #: ``initial`` (no stage before it), ``escalate`` or ``target``.
    mode: str
    seeds: StageSeeds
    champion: ResolvedPack
    previous: StageOutcome | None
    #: The champion's failures on the previous stage's training cases.
    autopsy: Autopsy | None
    #: What ``curriculum.escalate`` proposes from the previous stage's training run.
    escalations: tuple[Escalation, ...]
    #: Content keys of every held-out case so far; a builder may skip them, and the campaign refuses them.
    sealed: frozenset[str]
    #: Cases the campaign may still spend (training plus held-out), or ``None`` when unbounded.
    budget: int | None
    #: A directory the builder may write into (compiled datasets, frontier scratch).
    workdir: Path
    agent_for: Callable[[ResolvedPack], AgentUnderTest]
    rater: Any = None

    def proposals(self) -> tuple[dict[str, str], ...]:
        """Every escalation's proposed ``where`` predicates, deduplicated, in the escalations' order."""
        seen: dict[str, dict[str, str]] = {}
        for escalation in self.escalations:
            for proposal in escalation.proposals:
                seen.setdefault(json.dumps(proposal, sort_keys=True), dict(proposal))
        return tuple(seen.values())


class StageCases(NamedTuple):
    train_cases: Sequence[EvalCase]
    held_cases: Sequence[EvalCase]
    records_train: Any
    records_held: Any
    description: str


class StageBuilder(Protocol):
    """Given the previous stage's outcome, the next stage's case sets.

    ``__call__`` returns ``(train_cases, held_cases, records_train,
    records_held, description)``; records are a sequence or a
    ``RecordGroups``. It raises ``StageExhausted`` (or ``NothingHarder``)
    with the reason when it cannot produce new cases. ``id`` names the
    builder and its configuration in every record. A builder may also
    declare ``seeds_per_set`` (default 1) and ``reserved_seeds`` (seeds the
    campaign must never hand it, such as a base plan's own).
    """

    @property
    def id(self) -> str: ...

    def __call__(self, request: StageRequest) -> tuple[Sequence[EvalCase], Sequence[EvalCase], Any, Any, str]: ...


# -- the report ---------------------------------------------------------------------------


class SideScore(Model):
    """One policy over one held-out set."""

    ref: str
    digest: str
    cases: int
    graded: int
    errors: int
    passed: int
    pass_rate: float
    mean: float


class LedgerEntry(Model):
    """The original and the current champion over one stage's held-out cases, which neither ever trained on."""

    stage: int
    held_case_set: str
    held_cases: int
    original: SideScore
    current: SideScore
    #: Current minus original: the mean score and the pass rate.
    mean_delta: float
    pass_rate_delta: float
    improvements: int
    regressions: int
    newly_errored: int


class StageImprove(Model):
    """The stage's ``ImproveReport`` in brief; the whole report is ``stages/NNN/improve/improve.json``."""

    rounds: int
    decisions: tuple[str, ...]
    promotions: int
    champion_before: dict[str, Any]
    champion_after: dict[str, Any]
    grader: str


class StageRecord(Model):
    schema_version: str = Field(default=STAGE_SCHEMA, alias="schema")
    stage: int
    mode: str
    builder: str
    description: str
    seeds: StageSeeds
    train_cases: int
    held_cases: int
    train_case_set: str
    held_case_set: str
    #: What the stage was asked to build from: escalation proposals, or the failure clusters targeted.
    escalations: tuple[dict[str, str], ...] = ()
    targets: tuple[str, ...] = ()
    improve: StageImprove
    #: ``saturated``, ``plateaued``, ``failing`` or ``halted``: what decides the next stage.
    status: str
    status_reason: str
    ledger: LedgerEntry
    #: The champion's final training run, relative to the campaign directory.
    champion_run: str


class CampaignReport(Model):
    schema_version: str = Field(default=CAMPAIGN_SCHEMA, alias="schema")
    seed: int
    builder: str
    grader: dict[str, Any]
    original: dict[str, Any]
    champion: dict[str, Any]
    baseline: dict[str, Any] | None = None
    stages: tuple[StageRecord, ...]
    #: The cross-stage held-out ledger: original against current, stage by stage.
    ledger: tuple[LedgerEntry, ...]
    #: One of ``STOPS``.
    stopped: str
    reasons: tuple[str, ...] = ()
    cases_spent: int = 0


# -- helpers ------------------------------------------------------------------------------


def _identity(pack: ResolvedPack) -> dict[str, Any]:
    return {"ref": pack.ref, "digest": pack.digest, "chain": list(pack.chain)}


def _slug(pack: ResolvedPack) -> str:
    return f"{pack.name}@{pack.digest[:12]}"


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _record_line(record: Any) -> dict[str, Any]:
    from ..connector_data import ConnectorRecord

    if isinstance(record, ConnectorRecord):
        return {"kind": "connector_record", "record": record.model_dump(mode="json")}
    if hasattr(record, "model_dump"):
        return {"kind": "mapping", "record": record.model_dump(mode="json")}
    return {"kind": "mapping", "record": json.loads(json.dumps(dict(record), default=str))}


def _record_from(line: Mapping[str, Any]) -> Any:
    from ..connector_data import ConnectorRecord

    if line.get("kind") == "connector_record":
        return ConnectorRecord.model_validate(line["record"])
    return dict(line["record"])


def write_stage_cases(directory: Path, cases: Sequence[EvalCase], records: RecordGroups) -> None:
    """One case set with its record groups: ``cases.jsonl``, ``records.jsonl`` and ``groups.json``."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / "cases.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for case in cases:
            handle.write(json.dumps(case.model_dump(mode="json"), sort_keys=True, default=str) + "\n")
    spans: list[dict[str, Any]] = []
    start = 0
    with (directory / "records.jsonl").open("w", encoding="utf-8", newline="\n") as handle:
        for ids, held in records.groups:
            for record in held:
                handle.write(json.dumps(_record_line(record), sort_keys=True) + "\n")
            spans.append({"cases": list(ids), "records": [start, start + len(held)]})
            start += len(held)
    _write(directory / "groups.json", {"groups": spans})


def read_stage_cases(directory: Path) -> tuple[tuple[EvalCase, ...], RecordGroups]:
    cases = tuple(EvalCase.model_validate(json.loads(line))
                  for line in (directory / "cases.jsonl").read_text(encoding="utf-8").splitlines() if line.strip())
    lines = [json.loads(line) for line in (directory / "records.jsonl").read_text(encoding="utf-8").splitlines()
             if line.strip()]
    spans = json.loads((directory / "groups.json").read_text(encoding="utf-8"))["groups"]
    groups = tuple((tuple(span["cases"]), tuple(_record_from(line) for line in lines[span["records"][0]:span["records"][1]]))
                   for span in spans)
    return cases, RecordGroups(groups=groups)


def _side(pack: ResolvedPack, report: RunReport) -> SideScore:
    summary = summarize(report)
    return SideScore(ref=pack.ref, digest=pack.digest, cases=summary.cases, graded=summary.graded,
                     errors=summary.errors, passed=summary.passed, pass_rate=summary.pass_rate,
                     mean=summary.means.overall)


def _status(report: ImproveReport, patience: int) -> tuple[str, str]:
    """How a stage ended: what decides whether the next one escalates or targets."""
    decisions = [item.decision for item in report.rounds]
    if not decisions:
        return "failing", "no round ran"
    last = decisions[-1]
    if last in {"questions", "proposer_error"}:
        reasons = report.rounds[-1].reasons
        return "halted", f"the stage stopped with {last}" + (f": {reasons[0]}" if reasons else "")
    if last == "no_failures":
        return "saturated", "the champion passes every training case of the stage"
    trailing = 0
    for decision in reversed(decisions):
        if decision == "promoted":
            break
        trailing += 1
    if trailing >= patience:
        return "plateaued", (f"{trailing} round(s) in a row without a promotion, at least the policy "
                             f"`evalrun.campaign.patience` ({patience})")
    return "failing", f"the champion still fails training cases after {len(decisions)} round(s)"


# -- the campaign ---------------------------------------------------------------------------


@dataclass
class _Campaign:
    builder: StageBuilder
    agent_for: Callable[[ResolvedPack], AgentUnderTest]
    exchange: Exchange
    out: Path
    run: StageRunner
    rater: Any
    grader: dict[str, Any]
    pack_roots: tuple[str | Path, ...]
    value: bool
    improve_options: dict[str, Any]
    _known: dict[str, ResolvedPack] = field(default_factory=dict)

    def stage_dir(self, number: int) -> Path:
        return self.out / "stages" / f"{number:03d}"

    def roots(self, through: int) -> tuple[str | Path, ...]:
        """Every earlier stage's pack root (newest first) and the caller's: where a champion can live."""
        return (*(self.stage_dir(k) / "improve" / "packs" for k in range(through, 0, -1)), *self.pack_roots)

    def resolve(self, identity: Mapping[str, Any], through: int) -> ResolvedPack:
        held = self._known.get(str(identity["digest"]))
        if held is not None:
            return held
        # Pinned: a pack edited on disk since the stage ran is refused, not silently returned.
        pack = packkit.resolve(f"{identity['ref']}@{identity['digest']}", kind_name="agent", roots=self.roots(through))
        self._known[pack.digest] = pack
        return pack

    def cached_run(self, directory: Path, pack: ResolvedPack, cases: Sequence[EvalCase], records: RecordGroups,
                   *, holdout: bool = False) -> RunReport:
        """*pack* over *cases*, read back from *directory* when this exact run is already there."""
        from .harness import skills_cache_in

        with skills_cache_in(self.out / "skills-cache"):
            agent = self.agent_for(pack)
        identity = fingerprint(agent)
        if (directory / "run.json").exists():
            try:
                stored = read_run(directory)
            except ValueError:
                stored = None
            if (stored is not None and stored.case_set == case_set_digest(cases)
                    and (stored.grader or {}).get("digest") == self.grader["digest"]
                    and (stored.agent_pack or {}).get("digest") == pack.digest
                    and stored.agent_identity == identity):
                return stored
        check_frozen(self.grader, self.rater)
        report = self.run(cases, records, agent)
        check_frozen(self.grader, self.rater)
        update: dict[str, Any] = {"grader": self.grader, "agent_pack": report.agent_pack or _identity(pack),
                                  "agent_identity": identity}
        if holdout:
            update["split"] = "holdout"
        report = report.model_copy(update=update)
        write_run(directory, report)
        return report

    def champion_run(self, number: int, pack: ResolvedPack, cases: Sequence[EvalCase],
                     records: RecordGroups) -> tuple[RunReport, str]:
        """The champion's final training run: the one the improve loop already paid for, when it is on disk."""
        stage = self.stage_dir(number)
        paid = stage / "improve" / "runs" / _slug(pack) / "train"
        if (paid / "run.json").exists():
            try:
                stored = read_run(paid)
            except ValueError:
                stored = None
            if (stored is not None and stored.case_set == case_set_digest(cases)
                    and (stored.agent_pack or {}).get("digest") == pack.digest
                    and (stored.grader or {}).get("digest") == self.grader["digest"]):
                return stored, paid.relative_to(self.out).as_posix()
        directory = stage / "champion-train"
        return self.cached_run(directory, pack, cases, records), directory.relative_to(self.out).as_posix()

    def ledger(self, number: int, original: ResolvedPack, current: ResolvedPack, held: Sequence[EvalCase],
               records: RecordGroups) -> LedgerEntry:
        base = self.stage_dir(number) / "ledger"
        before = self.cached_run(base / "original", original, held, records, holdout=True)
        after = before if current.digest == original.digest else self.cached_run(
            base / "current", current, held, records, holdout=True)
        comparison = compare(before, after)
        first, last = _side(original, before), _side(current, after)
        return LedgerEntry(stage=number, held_case_set=case_set_digest(held), held_cases=len(held), original=first,
                           current=last, mean_delta=round(last.mean - first.mean, 6),
                           pass_rate_delta=round(last.pass_rate - first.pass_rate, 6),
                           improvements=len(comparison.improvements), regressions=len(comparison.regressions),
                           newly_errored=len(comparison.newly_errored))

    def values_for(self, cases: Sequence[EvalCase], records: RecordGroups) -> Mapping[str, Any] | None:
        if not self.value:
            return None
        from .value import value_table

        return value_table(cases, records.flat())

    def outcome(self, number: int, status: str, champion: ResolvedPack, train: tuple[EvalCase, ...],
                records: RecordGroups, run: RunReport, report: ImproveReport | None) -> StageOutcome:
        return StageOutcome(stage=number, status=status, champion=champion, train_cases=train, train_records=records,
                            champion_run=run, report=report, values=self.values_for(train, records))


def _decide(previous: StageOutcome | None) -> tuple[str, Autopsy | None, tuple[Escalation, ...]]:
    """The next stage's mode, with the autopsy and the escalations it is built from."""
    from .autopsy import autopsy
    from .curriculum import escalate

    if previous is None:
        return "initial", None, ()
    found = autopsy(previous.champion_run, cases=previous.train_cases, values=previous.values)
    # Escalation reads the training run only: the held-out cases judge, and
    # nothing about them may shape what the next stage trains on.
    escalations = tuple(escalate(previous.champion_run))
    if previous.status in {"saturated", "plateaued"}:
        return "escalate", found, escalations
    if previous.status == "baseline" and found.failing == 0:
        return "escalate", found, escalations
    return "target", found, escalations


def campaign(
    champion: ResolvedPack,
    *,
    builder: StageBuilder,
    agent_for: Callable[[ResolvedPack], AgentUnderTest],
    exchange: Exchange,
    out: str | Path,
    stages: int | None = None,
    seed: int = 0,
    run: StageRunner | None = None,
    rater: Any = None,
    baseline: tuple[Sequence[EvalCase], Any] | None = None,
    max_cases: int | None = None,
    patience: int | None = None,
    pack_roots: Sequence[str | Path] = (),
    concurrency: int = 1,
    principal: str | None = None,
    value: bool = False,
    **improve_options: Any,
) -> CampaignReport:
    """Run stages from *champion* until a stop: the stage budget, the case budget, no new cases, nothing harder.

    Each stage's case sets come from *builder* under fresh seeds derived from
    *seed*; each runs ``improve()`` (given *improve_options* untouched, such
    as ``rounds``) with the stage's held-out set as its holdout. *run* runs
    one agent over cases and their record groups (default ``run_grouped``
    with *rater*, *concurrency* and *principal*). *baseline*, cases and
    their records, is run by the champion first so the first stage can
    already target its failures (or escalate past what it has mastered);
    without it the first stage is built from the builder's base.
    ``stages`` defaults to the policy ``evalrun.campaign.max_stages``,
    ``max_cases`` (training plus held-out cases over the campaign) to
    ``evalrun.campaign.max_cases`` and ``patience`` to
    ``evalrun.campaign.patience``. ``value=True`` gates every stage on the
    value-weighted delta too and weights the targeted curriculum by value.
    """
    owned = sorted(_OWNED.intersection(improve_options))
    if owned:
        raise ValueError(f"the campaign sets {', '.join(owned)} for every stage; do not pass them through")
    limit = int(packkit.policy("evalrun.campaign.max_stages")) if stages is None else int(stages)
    wait = int(packkit.policy("evalrun.campaign.patience")) if patience is None else int(patience)
    budget = int(packkit.policy("evalrun.campaign.max_cases")) if max_cases is None else int(max_cases)
    if limit < 1 or wait < 1 or budget < 1:
        raise ValueError("stages, patience and max_cases must be at least 1")
    root = Path(out)
    root.mkdir(parents=True, exist_ok=True)
    grader = grader_identity(rater)
    builder_id = str(builder.id)
    stored = _read_json(root / "campaign.json")
    if isinstance(stored, dict):
        if stored.get("seed") != seed or (stored.get("original") or {}).get("digest") != champion.digest:
            raise ValueError(f"{root} holds a campaign from another seed or champion; use a new directory")
        if stored.get("builder") != builder_id:
            raise ValueError(f"{root} holds a campaign built by {stored.get('builder')!r}, not {builder_id!r}")
        check_frozen(stored["grader"], rater)

    def default_run(cases: Sequence[EvalCase], records: RecordGroups, agent: AgentUnderTest) -> RunReport:
        return run_grouped(cases, records, agent, rater=rater, concurrency=concurrency, principal=principal)

    state = _Campaign(builder=builder, agent_for=agent_for, exchange=exchange, out=root,
                      run=run if run is not None else default_run, rater=rater, grader=grader,
                      pack_roots=tuple(pack_roots), value=value, improve_options=dict(improve_options))
    original = champion
    state._known[original.digest] = original
    current = original
    used: set[int] = {int(item) for item in getattr(builder, "reserved_seeds", ())}
    per_set = int(getattr(builder, "seeds_per_set", 1))
    sealed: set[str] = set()
    trained: set[str] = set()
    spent = 0
    records: list[StageRecord] = []
    previous: StageOutcome | None = None
    baseline_summary: dict[str, Any] | None = None
    if baseline is not None:
        cases = tuple(baseline[0])
        groups = RecordGroups.of(baseline[1], cases)
        run_report = state.cached_run(root / "baseline", original, cases, groups)
        summary = summarize(run_report)
        baseline_summary = {"case_set": case_set_digest(cases), "cases": len(cases), "passed": summary.passed,
                            "pass_rate": summary.pass_rate, "mean": summary.means.overall}
        previous = state.outcome(0, "baseline", original, cases, groups, run_report, None)
    stopped: str = "max_stages"
    reasons: tuple[str, ...] = (f"ran {limit} stage(s), the stage budget",)
    for number in range(1, limit + 1):
        stage = state.stage_dir(number)
        done = _read_json(stage / "stage.json")
        if isinstance(done, dict):
            record = StageRecord.model_validate(done)
            expected = stage_seeds(seed, number, count=per_set, used=used)
            if (record.builder != builder_id or record.seeds != expected
                    or (number == 1 and record.improve.champion_before.get("digest") != original.digest)):
                raise ValueError(f"{stage} was written by another campaign (seed, builder or champion differ); "
                                 "use a new directory")
            train, train_groups = read_stage_cases(stage / "cases" / "train")
            held, _ = read_stage_cases(stage / "cases" / "held")
            current = state.resolve(record.improve.champion_after, number)
            used.update(record.seeds.all())
            sealed.update(map(case_key, held))
            trained.update(map(case_key, train))
            spent += record.train_cases + record.held_cases
            records.append(record)
            final = read_run(root / record.champion_run)
            previous = state.outcome(number, record.status, current, train, train_groups, final, None)
            if record.status == "halted":
                stopped, reasons = record.improve.decisions[-1], (record.status_reason,)
                break
            continue
        mode, found, escalations = _decide(previous)
        seeds = stage_seeds(seed, number, count=per_set, used=used)
        request = StageRequest(stage=number, mode=mode, seeds=seeds, champion=current, previous=previous,
                               autopsy=found, escalations=escalations, sealed=frozenset(sealed),
                               budget=budget - spent, workdir=stage / "build", agent_for=agent_for, rater=rater)
        built_file = stage / "cases" / "build.json"
        built = _read_json(built_file)
        if isinstance(built, dict) and built.get("seeds") == seeds.model_dump(mode="json"):
            description = str(built.get("description", ""))
        else:
            try:
                made = StageCases(*builder(request))
            except StageExhausted as error:
                stopped, reasons = error.code, (f"stage {number} ({mode}): {error}",)
                break
            train_raw, held_raw = tuple(made.train_cases), tuple(made.held_cases)
            if not train_raw or not held_raw:
                stopped, reasons = "no_new_cases", (f"stage {number} ({mode}): the builder produced "
                                                    f"{len(train_raw)} training and {len(held_raw)} held-out case(s)",)
                break
            write_stage_cases(stage / "cases" / "train", train_raw, RecordGroups.of(made.records_train, train_raw))
            write_stage_cases(stage / "cases" / "held", held_raw, RecordGroups.of(made.records_held, held_raw))
            description = made.description
            _write(built_file, {"builder": builder_id, "mode": mode, "seeds": seeds.model_dump(mode="json"),
                                "description": description})
        # What runs is always what was written, so a first run and a resumed
        # one see the same bytes.
        train, train_groups = read_stage_cases(stage / "cases" / "train")
        held, held_groups = read_stage_cases(stage / "cases" / "held")
        overlap = _overlap(number, train, held, sealed, trained)
        if overlap:
            stopped, reasons = "held_out_overlap", overlap
            _write(stage / "refused.json", {"stopped": stopped, "reasons": list(overlap)})
            break
        if spent + len(train) + len(held) > budget:
            stopped, reasons = "case_budget", (
                f"stage {number} needs {len(train) + len(held)} case(s) and {budget - spent} of the "
                f"campaign's {budget} remain (policy `evalrun.campaign.max_cases`)",)
            break
        by_set = {case_set_digest(train): train_groups, case_set_digest(held): held_groups}

        def run_stage(subset: Sequence[EvalCase], agent: AgentUnderTest,
                      _groups: Mapping[str, RecordGroups] = by_set) -> RunReport:
            groups = _groups.get(case_set_digest(subset))
            if groups is None:
                raise ValueError("the improve loop asked to run cases that are neither the stage's training "
                                 "nor its held-out set")
            return state.run(subset, groups, agent)

        improve_dir = stage / "improve"
        values = state.values_for(train, train_groups)
        holdout_values = state.values_for(held, held_groups)
        report = improve(current, train, run=run_stage, agent_for=agent_for, exchange=exchange, out=improve_dir,
                         rater=rater, holdout=held, pack_roots=state.roots(number - 1), values=values,
                         holdout_values=holdout_values, **improve_options)
        before = current
        after = state.resolve(report.champion, number)
        status, why = _status(report, wait)
        final, final_path = state.champion_run(number, after, train, train_groups)
        entry = state.ledger(number, original, after, held, held_groups)
        record = StageRecord(
            stage=number, mode=mode, builder=builder_id, description=description, seeds=seeds,
            train_cases=len(train), held_cases=len(held), train_case_set=case_set_digest(train),
            held_case_set=case_set_digest(held),
            escalations=request.proposals() if mode == "escalate" else (),
            targets=tuple(cluster.key for cluster in found.clusters) if mode == "target" and found else (),
            improve=StageImprove(rounds=len(report.rounds), decisions=tuple(item.decision for item in report.rounds),
                                 promotions=report.promotions, champion_before=_identity(before),
                                 champion_after=_identity(after), grader=str(report.grader.get("digest", ""))),
            status=status, status_reason=why, ledger=entry, champion_run=final_path)
        _write(stage / "stage.json", record.model_dump(mode="json", by_alias=True))
        records.append(record)
        used.update(seeds.all())
        sealed.update(map(case_key, held))
        trained.update(map(case_key, train))
        spent += len(train) + len(held)
        current = after
        previous = state.outcome(number, status, after, train, train_groups, final, report)
        if status == "halted":
            stopped, reasons = report.rounds[-1].decision, (why,)
            break
    result = CampaignReport(seed=seed, builder=builder_id, grader=grader, original=_identity(original),
                            champion=_identity(current), baseline=baseline_summary, stages=tuple(records),
                            ledger=tuple(record.ledger for record in records), stopped=stopped, reasons=reasons,
                            cases_spent=spent)
    _write(root / "campaign.json", result.model_dump(mode="json", by_alias=True))
    return result


def _overlap(number: int, train: Sequence[EvalCase], held: Sequence[EvalCase], sealed: set[str],
             trained: set[str]) -> tuple[str, ...]:
    """Every way this stage's cases would break the seal, in words; empty when none does."""
    reasons: list[str] = []
    leaked = sorted(case.id for case in train if case_key(case) in sealed)
    if leaked:
        reasons.append(f"stage {number}: {len(leaked)} training case(s) were held out by an earlier stage, "
                       f"e.g. {leaked[0]}")
    held_keys = {case_key(case) for case in held}
    both = sorted(case.id for case in train if case_key(case) in held_keys)
    if both:
        reasons.append(f"stage {number}: {len(both)} case(s) are both training and held out, e.g. {both[0]}")
    seen = sorted(case.id for case in held if case_key(case) in trained)
    if seen:
        reasons.append(f"stage {number}: {len(seen)} held-out case(s) were trained on by an earlier stage, "
                       f"e.g. {seen[0]}")
    return tuple(reasons)


# -- builders -------------------------------------------------------------------------------


def _plan_payload(plan: Any, *, seed: int, strata: Sequence[Mapping[str, Any]], split: str) -> dict[str, Any]:
    """*plan* with *strata* under *seed*, every row in one split, diversity minima clipped to the rows."""
    payload: dict[str, Any] = plan.model_dump(mode="json")
    for per_stratum in ("lineage", "generation_contracts", "split_assignments"):
        payload.pop(per_stratum, None)
    rows = sum(int(stratum["count"]) for stratum in strata)
    payload.update(seed=seed, strata=[dict(stratum) for stratum in strata], split_weights={split: 100},
                   minimum_tasks=min(int(payload.get("minimum_tasks", 1)), rows),
                   minimum_companies=min(int(payload.get("minimum_companies", 1)), rows))
    return payload


def _scaled(strata: Sequence[Mapping[str, Any]], ratio: float) -> list[dict[str, Any]]:
    from .curriculum import round_half_up

    return [{**stratum, "count": max(1, round_half_up(int(stratum["count"]) * ratio))} for stratum in strata]


@dataclass(frozen=True)
class DatasetStageBuilder:
    """Stages compiled from ``DatasetPlan``s by ``compile_dataset``, for enterprise corpora.

    ``initial`` compiles the base plan's strata; ``target`` compiles
    ``design_curriculum`` over the previous stage's autopsy (value-weighted
    when the campaign has values, with a representative share when a
    reference mix is given or can be counted from the previous stage's
    records); ``escalate`` compiles one stratum per escalation proposal, on
    the closest base stratum. The training plan runs under the stage's
    training seed and the held-out plan, the same strata scaled by
    ``held_ratio`` (policy ``evalrun.campaign.held_ratio``), under its
    held-out seed, so the two share no seed and no batch. Each compiled row
    becomes a case named by its dataset row id, over the records of the
    batch it was qualified in.
    """

    base: Any
    total: int | None = None
    held_ratio: float | None = None
    min_per_cluster: int = 4
    max_share: float = 0.5
    reference: ReferenceMix | None = None
    #: Counted from the previous stage's records when no ``reference`` is given; ``None`` keeps no mix.
    mix_dimension: str | None = "activity"
    dataset_builder: Any = None
    workers: int | None = None
    principal: str = "agent"

    @property
    def id(self) -> str:
        from ..providers import digest

        return f"dataset:{digest(self.base.model_dump(mode='json'))[:12]}"

    @property
    def reserved_seeds(self) -> tuple[int, ...]:
        return (int(self.base.seed),)

    seeds_per_set = 1

    def _total(self) -> int:
        return self.total if self.total is not None else sum(stratum.count for stratum in self.base.strata)

    def _ratio(self) -> float:
        ratio = float(packkit.policy("evalrun.campaign.held_ratio")) if self.held_ratio is None else self.held_ratio
        if ratio <= 0:
            raise ValueError("held_ratio must be positive")
        return ratio

    def _reference(self, request: StageRequest) -> tuple[ReferenceMix | None, str]:
        if self.reference is not None:
            return self.reference, f"mix over {self.reference.dimension} as given"
        if self.mix_dimension is None or request.previous is None:
            return None, ""
        from .value import reference_mix

        try:
            mix = reference_mix(request.previous.train_records.flat(), dimension=self.mix_dimension)
        except ValueError as error:
            return None, f"no representative share: {error}"
        return mix, f"mix over {mix.dimension} counted from the previous stage's records"

    def strata(self, request: StageRequest) -> tuple[list[dict[str, Any]], str]:
        """The training strata for *request*, and what they are, in words."""
        from .curriculum import (
            _allocate,
            _choose_stratum,
            _shaped_failures,
            _source_for,
            design_curriculum,
        )

        total = self._total()
        if request.mode == "initial":
            strata = [stratum.model_dump(mode="json") for stratum in self.base.strata]
            return strata, f"initial: the base plan's {len(strata)} stratum(s), {total} row(s)"
        if request.mode == "target":
            if request.autopsy is None:
                raise StageExhausted("a targeted stage needs the previous stage's autopsy")
            reference, note = self._reference(request)
            values = request.previous.values if request.previous is not None else None
            try:
                curriculum = design_curriculum(request.autopsy, self.base, seed=request.seeds.train[0],
                                               round=request.stage, total=total,
                                               min_per_cluster=self.min_per_cluster, max_share=self.max_share,
                                               values=values, reference=reference)
            except ValueError as error:
                if reference is None:
                    raise StageExhausted(str(error)) from error
                # A reference that leaves the targets too few rows falls back
                # to the plain curriculum, and says so.
                try:
                    curriculum = design_curriculum(request.autopsy, self.base, seed=request.seeds.train[0],
                                                   round=request.stage, total=total,
                                                   min_per_cluster=self.min_per_cluster, max_share=self.max_share,
                                                   values=values)
                except ValueError as again:
                    raise StageExhausted(str(again)) from again
                note = f"no representative share: {error}"
            targets = "; ".join(f"{target.stratum} {target.count} row(s) for {', '.join(target.keys)}"
                                for target in curriculum.targets)
            unmapped = f"; {len(curriculum.unmappable)} cluster(s) unmappable" if curriculum.unmappable else ""
            return (list(curriculum.plan["strata"]),
                    f"target: {targets}{unmapped}" + (f"; {note}" if note else "")
                    + ("; value-weighted" if values is not None else ""))
        proposals = [proposal for proposal in request.proposals()
                     if proposal.get("failure", "none") in _shaped_failures()]
        chosen: list[tuple[dict[str, str], Any]] = []
        for where in proposals:
            stratum, _ = _choose_stratum(self.base, where)
            if stratum is not None:
                chosen.append((where, stratum))
        if not chosen:
            saturated = "; ".join(item.reason for item in request.escalations) or "no slice is saturated"
            raise NothingHarder(f"no escalation proposal maps onto a base stratum ({saturated})")
        chosen = chosen[:total]
        counts = _allocate([1.0] * len(chosen), total, 1, total)
        strata = []
        for index, ((where, stratum), count) in enumerate(zip(chosen, counts, strict=True), start=1):
            label = "-".join(f"{key}-{value}" for key, value in sorted(where.items()))
            strata.append({"id": f"s{request.stage}-escalate-{index}-{label}"[:80], "count": count,
                           "source": _source_for(stratum, where)})
        described = ", ".join(json.dumps(where, sort_keys=True) for where, _ in chosen)
        return strata, f"escalate: {len(strata)} harder slice(s) {described}"

    def plans(self, request: StageRequest) -> tuple[Any, Any, str]:
        """The training and held-out ``DatasetPlan``s for *request*, and the stage's description."""
        from ..evals.company_dataset import load_dataset_plan

        strata, description = self.strata(request)
        train = load_dataset_plan(_plan_payload(self.base, seed=request.seeds.train[0], strata=strata, split="train"))
        held = load_dataset_plan(_plan_payload(self.base, seed=request.seeds.held[0],
                                               strata=_scaled(strata, self._ratio()), split="test"))
        return train, held, description

    def compile(self, plan: Any, directory: Path, split: str) -> tuple[list[EvalCase], RecordGroups, str]:
        """*plan* compiled into cases, one record group per qualified batch."""
        from ..enterprise_io import load_exported_corpus
        from ..evals.dataset import compile_dataset
        from .contract import cases_from_corpus

        run = compile_dataset(plan, directory, builder=self.dataset_builder, workers=self.workers)
        source = directory / ("queryset.jsonl" if run.report.complete else "candidates.jsonl")
        rows = ([json.loads(line) for line in source.read_text(encoding="utf-8").splitlines() if line.strip()]
                if source.exists() else [])
        rows = [row for row in rows if row.get("qualification")]
        if not rows:
            raise StageExhausted(f"the {split} plan admitted no row: {'; '.join(run.report.findings) or 'empty'}")
        by_batch: dict[str, list[dict[str, Any]]] = {}
        for row in rows:
            by_batch.setdefault(str(row["qualification"]), []).append(row)
        cases: list[EvalCase] = []
        groups: list[tuple[tuple[str, ...], tuple[Any, ...]]] = []
        for qualification in sorted(by_batch):
            corpus = load_exported_corpus(directory / qualification)
            compiled = {case.id: case for case in cases_from_corpus(corpus, principal=self.principal)}
            ids: list[str] = []
            for row in by_batch[qualification]:
                case = compiled.get(str(row["query_id"]))
                if case is None:
                    raise StageExhausted(f"dataset row {row['id']} names a query its batch does not compile")
                # Named by the dataset row, which is unique across batches,
                # where a query id is only unique within its world.
                named = case.model_copy(update={
                    "id": str(row["id"]), "row": {**case.row, "id": str(row["id"])},
                    "dimensions": {**case.dimensions, "split": "train" if split == "train" else "holdout",
                                   "dataset_row": str(row["id"]), "stratum": str(row.get("stratum", ""))}})
                cases.append(named)
                ids.append(named.id)
            groups.append((tuple(ids), tuple(corpus.connector_data.records)))
        note = "" if run.report.complete else f" (incomplete: {'; '.join(run.report.findings)})"
        return cases, RecordGroups(groups=tuple(groups)), f"{len(cases)} {split} row(s){note}"

    def __call__(self, request: StageRequest) -> StageCases:
        train_plan, held_plan, description = self.plans(request)
        train, train_groups, train_note = self.compile(train_plan, request.workdir / "train", "train")
        held, held_groups, held_note = self.compile(held_plan, request.workdir / "held", "held")
        return StageCases(train, held, train_groups, held_groups, f"{description}; {train_note}; {held_note}")


@dataclass(frozen=True)
class CornerStageBuilder:
    """Stages of event-grounded corner cases from seeded worlds (``corners``).

    Each set draws ``worlds`` seeded worlds of ``engine`` and keeps the
    cases the reference solves. ``target`` narrows the templates to those
    the champion's failing clusters concentrate in; ``escalate`` runs
    ``corners.frontier`` over the training seeds, keeping only the cases
    the reference solves and the champion fails, with the held-out seeds
    refused to the search. Every world is its own record group.
    """

    engine: str = "retail"
    templates: tuple[str, ...] | None = None
    worlds: int = 2
    #: Champion runs the frontier may spend when escalating.
    budget: int = 40

    @property
    def id(self) -> str:
        chosen = ",".join(self.templates) if self.templates else "all"
        return f"corners:{self.engine}:{chosen}:{self.worlds}"

    @property
    def seeds_per_set(self) -> int:
        return self.worlds

    def _templates(self, request: StageRequest) -> tuple[str, ...] | None:
        if request.mode != "target" or request.autopsy is None:
            return self.templates
        failing = sorted({value for cluster in request.autopsy.clusters
                          for value in (cluster.dimensions.get("corner") or {})})
        allowed = [name for name in failing if self.templates is None or name in self.templates]
        return tuple(allowed) or self.templates

    def __call__(self, request: StageRequest) -> StageCases:
        from .corners import corner_cases, corner_generator, frontier, seeded_world

        templates = self._templates(request)
        held_cases: list[EvalCase] = []
        held_groups: list[tuple[tuple[str, ...], tuple[Any, ...]]] = []
        for seed in request.seeds.held:
            batch = corner_cases(seeded_world(self.engine, seed), templates=templates, seed=seed)
            if batch.cases:
                held_cases.extend(batch.cases)
                held_groups.append((tuple(case.id for case in batch.cases), tuple(batch.records)))
        train_cases: list[EvalCase] = []
        train_groups: list[tuple[tuple[str, ...], tuple[Any, ...]]] = []
        if request.mode == "escalate":
            report = frontier(corner_generator(self.engine, templates=templates), request.agent_for(request.champion),
                              budget=self.budget, seeds=request.seeds.train, holdout_seeds=request.seeds.held,
                              rater=request.rater)
            for found in report.batches:
                train_cases.extend(found.cases)
                train_groups.append((tuple(case.id for case in found.cases), tuple(found.records)))
            if not train_cases:
                raise NothingHarder(f"the champion solves every corner case the reference solves on seeds "
                                    f"{list(request.seeds.train)} ({report.spent} champion run(s))")
            how = f"escalate: {len(train_cases)} frontier case(s) from {report.offered} offered"
        else:
            for seed in request.seeds.train:
                batch = corner_cases(seeded_world(self.engine, seed), templates=templates, seed=seed)
                if batch.cases:
                    train_cases.extend(batch.cases)
                    train_groups.append((tuple(case.id for case in batch.cases), tuple(batch.records)))
            how = f"{request.mode}: {len(train_cases)} corner case(s)"
        if not train_cases or not held_cases:
            raise StageExhausted(f"the {self.engine} worlds on seeds {list(request.seeds.all())} hold "
                                 f"{len(train_cases)} training and {len(held_cases)} held-out corner case(s)")
        chosen = ", ".join(templates) if templates else "every template"
        return StageCases(train_cases, held_cases, RecordGroups(groups=tuple(train_groups)),
                          RecordGroups(groups=tuple(held_groups)),
                          f"{how} ({chosen}); {len(held_cases)} held-out case(s)")


# -- the SDK form -------------------------------------------------------------------------------


@dataclass
class CampaignLoop:
    """``campaign()`` with its callables built from a session: ``run`` it from a champion.

    Built by ``EvalSession.campaign``. The session's cases and records are
    the baseline the first stage is decided from. ``out`` receives exactly
    what the CLI writes, so a campaign started here resumes from
    ``worldloom evalrun campaign`` and the other way round.
    """

    builder: StageBuilder
    agent: Callable[[ResolvedPack], AgentUnderTest]
    exchange: Exchange
    out: Path
    baseline: tuple[tuple[EvalCase, ...], tuple[Any, ...]] | None = None
    rater: Any = None
    concurrency: int = 1
    principal: str | None = None
    definitions: Mapping[str, Any] | None = None
    pack_roots: tuple[str | Path, ...] = ()
    seed: int = 0
    max_cases: int | None = None
    patience: int | None = None
    value: bool = False
    improve_options: dict[str, Any] = field(default_factory=dict)

    def run_cases(self, cases: Sequence[EvalCase], records: RecordGroups, agent: AgentUnderTest) -> RunReport:
        return run_grouped(cases, records, agent, rater=self.rater, concurrency=self.concurrency,
                           principal=self.principal, definitions=self.definitions)

    def run(self, champion: ResolvedPack | str, *, stages: int | None = None) -> CampaignReport:
        """Run the campaign from *champion*: a resolved ``agent`` pack or a reference like ``agent:baseline``."""
        from .policy import load, require

        start = load(champion, roots=self.pack_roots) if isinstance(champion, str) else require(champion)
        return campaign(start, builder=self.builder, agent_for=self.agent, exchange=self.exchange, out=self.out,
                        stages=stages, seed=self.seed, run=self.run_cases, rater=self.rater,
                        baseline=self.baseline, max_cases=self.max_cases, patience=self.patience,
                        pack_roots=self.pack_roots, value=self.value, **self.improve_options)

    def champion(self, report: CampaignReport) -> ResolvedPack:
        """The pack *report* ended with, resolved and pinned by digest from where its stage stored it."""
        return campaign_champion(report, self.out, pack_roots=self.pack_roots)


def campaign_champion(report: CampaignReport, out: str | Path, *, pack_roots: Sequence[str | Path] = ()) -> ResolvedPack:
    """The champion a campaign ended with, pinned by digest, from its stages' pack roots."""
    root = Path(out)
    roots = (*(root / "stages" / f"{record.stage:03d}" / "improve" / "packs" for record in reversed(report.stages)),
             *pack_roots)
    identity = report.champion
    return packkit.resolve(f"{identity['ref']}@{identity['digest']}", kind_name="agent", roots=roots)


__all__ = [
    "CAMPAIGN_SCHEMA",
    "STAGE_SCHEMA",
    "STOPS",
    "CampaignLoop",
    "CampaignReport",
    "CornerStageBuilder",
    "DatasetStageBuilder",
    "LedgerEntry",
    "NothingHarder",
    "RecordGroups",
    "SideScore",
    "StageBuilder",
    "StageCases",
    "StageExhausted",
    "StageImprove",
    "StageOutcome",
    "StageRecord",
    "StageRequest",
    "StageRunner",
    "StageSeeds",
    "campaign",
    "campaign_champion",
    "case_key",
    "read_stage_cases",
    "run_grouped",
    "stage_seed",
    "stage_seeds",
    "write_stage_cases",
]
