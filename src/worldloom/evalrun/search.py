"""Wide search for the improve loop: many candidates a round, screened cheaply, and an archive to branch from.

A loop that asks for one proposal a round and evaluates it in full spends
the whole round on whatever the proposer happened to try first, and throws
away a candidate that came close. Published recipes that work (GEPA,
AlphaEvolve and FunSearch, the Darwin Goedel Machine) do three things
instead, and this module holds the parts of each that are not the loop
itself:

1. **Screening.** ``screen_order`` fixes, for one round, the order in which
   training cases are spent on screening: stratified by failure cluster, so
   a small prefix already touches every way the parent fails, and seeded by
   the round and the case set, so a rerun spends the same cases. Candidates
   are run on a prefix, the better half advances, the prefix doubles
   (successive halving), and only the finalists pay for the full gates.
2. **An archive.** Every candidate evaluated in full on the training cases
   is kept (``Archive``, one JSON file per pack digest under ``archive/``)
   with its per-case scores and its mean over each failure cluster.
3. **A Pareto frontier and parent selection.** ``pareto_frontier`` keeps
   the archived candidates no other one matches or beats on every cluster;
   ``select_parent`` draws a parent from it, weighted toward a high mean and
   a low visit count, from a seeded SHA-256 draw.

Nothing here judges promotion. The archive only chooses what the proposer
revises; a candidate becomes the champion through the loop's unchanged
gates against the current champion, the sealed holdout included. Screening
and the archive only ever see training cases.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping, Sequence
from pathlib import Path
from typing import Any

from pydantic import Field

from ..models import Model
from ..packkit import diffs
from .runner import RunReport

ARCHIVE_SCHEMA = "worldloom.improve-archive/v1"
CLUSTERS_SCHEMA = "worldloom.improve-archive-clusters/v1"

#: How sharply parent selection prefers a high mean: a member ``d`` below the
#: best mean weighs ``exp(-PARENT_SHARPNESS * d)`` before its visits divide
#: it, so at 10 a member 0.07 behind the best still weighs half as much.
PARENT_SHARPNESS = 10.0
#: The stratum of a training case the champion passes (or whose cluster the
#: autopsy did not list): screened last in each sweep, so a regression on a
#: case that already worked still shows before the finalists are chosen.
PASSING = "(passing)"
#: What each parent-selection mode is called in a receipt.
PARENT_MODES = ("champion", "archive")


# -- records -----------------------------------------------------------------------


class CandidateRecord(Model):
    """One proposal of a wide round, and how far it got."""

    index: int
    """1-based position among the round's proposals."""
    #: ``finalist`` (went to the full training gate), ``screened_out``,
    #: ``refused`` (no proposal linted clean), ``unchanged`` (restated the
    #: draft or the champion) or ``duplicate`` (the same body as an earlier
    #: candidate of this round, named by ``duplicate_of``).
    status: str
    ref: str | None = None
    digest: str | None = None
    summary: str = ""
    diff_stat: str = ""
    duplicate_of: int | None = None
    reasons: tuple[str, ...] = ()
    authoring: tuple[dict[str, Any], ...] = ()
    #: The finalist's training gate against the champion.
    train_mean_delta: float | None = None
    train_passed: bool | None = None


class ScreenScore(Model):
    index: int
    digest: str
    #: Mean over the stage's cases of the candidate's score minus the
    #: champion's mean score over its training repeats: a paired delta.
    mean_delta: float
    cases: int


class ScreenStage(Model):
    """One rung of successive halving."""

    stage: int
    #: Every case the stage's scores are over, in screening order.
    cases: tuple[str, ...]
    #: The cases this stage ran (the rest were run by earlier stages).
    ran: tuple[str, ...]
    scores: tuple[ScreenScore, ...]
    #: Candidate indices that advanced, best first.
    advanced: tuple[int, ...]
    #: Case-runs this stage paid for.
    cost: int


class Screening(Model):
    """A wide round's proposals, their screening, and who reached the full gates."""

    requested: int
    candidates: tuple[CandidateRecord, ...]
    #: The seed the screening order was drawn from, and that order.
    seed: str = ""
    order: tuple[str, ...] = ()
    stages: tuple[ScreenStage, ...] = ()
    finalists: tuple[int, ...] = ()
    #: ``not_needed`` (no more candidates than finalists), ``finalists``,
    #: ``whole_set`` (the subset reached every training case) or ``budget``.
    stopped: str = "not_needed"
    budget: int | None = None
    #: Case-runs the screening stages paid for.
    cost: int = 0


class ArchiveEntry(Model):
    """One candidate evaluated in full on the training cases."""

    schema_version: str = Field(default=ARCHIVE_SCHEMA, alias="schema")
    digest: str
    ref: str
    #: The pack itself (kind, name, title, description, body), so it can be
    #: branched from even after its name was reused for a reduced candidate.
    envelope: dict[str, Any]
    case_set: str
    grader: str
    repeats: int
    round: int
    parent: str | None = None
    #: Failing cases in its first training repeat (what a brief would show).
    failing: int
    #: Mean score per training case over its repeats.
    scores: dict[str, float]
    #: Mean score over each failure cluster's cases.
    clusters: dict[str, float]
    mean: float


# -- scores ------------------------------------------------------------------------


def case_scores(runs: Sequence[RunReport]) -> dict[str, float]:
    """Each case's mean score over *runs*; a case that errored scores 0 in that run."""
    totals: dict[str, list[float]] = {}
    for report in runs:
        for row in report.results:
            value = row.score.score if row.graded and row.score is not None else 0.0
            totals.setdefault(row.case_id, []).append(float(value))
    return {case_id: round(sum(values) / len(values), 6) for case_id, values in sorted(totals.items())}


def paired_delta(candidate: Mapping[str, float], champion: Mapping[str, float], cases: Sequence[str]) -> float:
    """The mean over *cases* of the candidate's score minus the champion's."""
    if not cases:
        return 0.0
    return round(sum(candidate.get(case_id, 0.0) - champion.get(case_id, 0.0) for case_id in cases) / len(cases), 6)


def cluster_means(scores: Mapping[str, float], clusters: Mapping[str, Sequence[str]]) -> dict[str, float]:
    """The mean of *scores* over each cluster's cases (clusters may overlap)."""
    out: dict[str, float] = {}
    for key in sorted(clusters):
        members = [scores[case_id] for case_id in clusters[key] if case_id in scores]
        out[key] = round(sum(members) / len(members), 6) if members else 0.0
    return out


# -- screening order ---------------------------------------------------------------


def screen_seed(case_set: str, round_number: int) -> str:
    return hashlib.sha256(f"improve-screen\0{case_set}\0{round_number}".encode()).hexdigest()[:16]


def screen_order(case_ids: Sequence[str], clusters: Sequence[tuple[str, Sequence[str]]], seed: str) -> tuple[str, ...]:
    """Every training case once, in the order screening spends them.

    Each case's stratum is the smallest failure cluster it belongs to (ties
    by key), so a rare way of failing is not drowned by a common one; a case
    in no cluster is in ``PASSING``. Within a stratum cases are ordered by a
    SHA-256 of *seed* and the case id, and the order deals one case from
    each stratum in turn (strata by size, then key, ``PASSING`` last). Any
    prefix is therefore close to stratified, and a doubled prefix contains
    the smaller one.
    """
    ids = list(dict.fromkeys(case_ids))
    sizes = {key: len(members) for key, members in clusters}
    membership: dict[str, list[str]] = {}
    for key, members in clusters:
        for case_id in members:
            membership.setdefault(case_id, []).append(key)
    strata: dict[str, list[str]] = {}
    for case_id in ids:
        keys = membership.get(case_id)
        stratum = min(keys, key=lambda key: (sizes[key], key)) if keys else PASSING
        strata.setdefault(stratum, []).append(case_id)

    def draw(case_id: str) -> str:
        return hashlib.sha256(f"{seed}\0{case_id}".encode()).hexdigest()

    queues = [sorted(strata[key], key=lambda case_id: (draw(case_id), case_id))
              for key in sorted(strata, key=lambda key: (key == PASSING, sizes.get(key, 0), key))]
    order: list[str] = []
    depth = 0
    while len(order) < len(ids):
        for queue in queues:
            if depth < len(queue):
                order.append(queue[depth])
        depth += 1
    return tuple(order)


def halving_keep(alive: int, finalists: int, whole: bool) -> int:
    """How many candidates advance from a stage: the better half (rounded up), never fewer than *finalists*.

    On the whole training set there is nothing left to double into, so
    exactly *finalists* advance.
    """
    if whole:
        return min(alive, finalists)
    return min(alive, max(finalists, math.ceil(alive / 2)))


# -- the frontier and parent selection ---------------------------------------------


def dominates(left: Mapping[str, float], right: Mapping[str, float]) -> bool:
    """*left* is at least as good as *right* on every cluster and better on one."""
    keys = sorted(set(left) | set(right))
    at_least = all(left.get(key, 0.0) >= right.get(key, 0.0) for key in keys)
    return at_least and any(left.get(key, 0.0) > right.get(key, 0.0) for key in keys)


def pareto_frontier(vectors: Mapping[str, Mapping[str, float]]) -> tuple[str, ...]:
    """The keys of *vectors* no other vector dominates, sorted.

    Two members with the same vector are both on the frontier: neither is
    better anywhere.
    """
    names = sorted(vectors)
    return tuple(name for name in names
                 if not any(dominates(vectors[other], vectors[name]) for other in names if other != name))


def parent_weights(members: Sequence[tuple[str, float, int]]) -> dict[str, float]:
    """Each frontier member's selection weight, from ``(digest, mean, visits)``.

    ``exp(-PARENT_SHARPNESS * (best mean - mean)) / (1 + visits)``: a member
    near the best mean that has rarely been branched from is the likeliest
    parent, and the champion, branched from every round it was not
    displaced, gives way to a stepping stone that has not been tried.
    """
    if not members:
        return {}
    best = max(mean for _, mean, _ in members)
    return {digest: round(math.exp(-PARENT_SHARPNESS * (best - mean)) / (1 + visits), 9)
            for digest, mean, visits in sorted(members)}


def parent_seed(case_set: str, round_number: int, frontier: Iterable[str]) -> str:
    joined = ",".join(sorted(frontier))
    return hashlib.sha256(f"improve-parent\0{case_set}\0{round_number}\0{joined}".encode()).hexdigest()


def select_parent(members: Sequence[tuple[str, float, int]], seed: str) -> tuple[str, float, dict[str, float]]:
    """``(digest, draw, weights)``: the member a uniform draw from *seed* lands on, by weight.

    The draw is the first 48 bits of *seed* (a SHA-256 hex digest) over
    2**48; members are laid out in digest order.
    """
    if not members:
        raise ValueError("no frontier member to branch from")
    weights = parent_weights(members)
    total = sum(weights.values())
    draw = int(seed[:12], 16) / float(16 ** 12)
    point = draw * total
    running = 0.0
    chosen = sorted(weights)[-1]
    for digest in sorted(weights):
        running += weights[digest]
        if point < running:
            chosen = digest
            break
    return chosen, round(draw, 9), weights


# -- the archive -------------------------------------------------------------------


class Archive:
    """``archive/`` under a loop's output directory: one entry per pack digest, and the cluster map.

    The cluster map (``archive/clusters.json``) is fixed the first time the
    archive meets a training case set, from the champion's autopsy then, so
    every entry's cluster means are over the same cases and the frontier
    compares like with like. Entries for another case set or grader are
    kept on disk and ignored.
    """

    def __init__(self, root: Path, *, case_set: str, grader: str) -> None:
        self.root = root
        self.case_set = case_set
        self.grader = grader
        self.clusters: dict[str, tuple[str, ...]] = {}
        self.entries: dict[str, ArchiveEntry] = {}
        self._load()

    def _load(self) -> None:
        stored = _read(self.root / "clusters.json")
        if stored is not None and stored.get("case_set") == self.case_set:
            self.clusters = {str(key): tuple(str(item) for item in members)
                             for key, members in sorted(dict(stored.get("clusters", {})).items())}
        if not self.root.is_dir():
            return
        for path in sorted(self.root.glob("*.json")):
            if path.name == "clusters.json":
                continue
            document = _read(path)
            if document is None:
                continue
            try:
                entry = ArchiveEntry.model_validate(document)
            except ValueError:
                continue
            if entry.case_set == self.case_set and entry.grader == self.grader:
                self.entries[entry.digest] = entry

    def fix_clusters(self, clusters: Sequence[tuple[str, Sequence[str]]], case_ids: Sequence[str]) -> None:
        """Set the cluster map once per case set: the given failure clusters and ``PASSING`` for the rest."""
        if self.clusters:
            return
        mapped: dict[str, tuple[str, ...]] = {key: tuple(sorted(members)) for key, members in clusters}
        covered = {case_id for members in mapped.values() for case_id in members}
        rest = tuple(sorted(case_id for case_id in case_ids if case_id not in covered))
        if rest:
            mapped[PASSING] = rest
        self.clusters = dict(sorted(mapped.items()))
        _write(self.root / "clusters.json", {"schema": CLUSTERS_SCHEMA, "case_set": self.case_set,
                                             "clusters": {key: list(value) for key, value in self.clusters.items()}})

    def add(self, *, digest: str, ref: str, envelope: Mapping[str, Any], runs: Sequence[RunReport], failing: int,
            round_number: int, parent: str | None, repeats: int) -> ArchiveEntry:
        """Record a candidate evaluated in full; an entry already held for this digest is kept as it was."""
        held = self.entries.get(digest)
        if held is not None:
            return held
        scores = case_scores(runs)
        entry = ArchiveEntry(digest=digest, ref=ref, envelope=dict(envelope), case_set=self.case_set,
                             grader=self.grader, repeats=repeats, round=round_number, parent=parent,
                             failing=failing, scores=scores, clusters=cluster_means(scores, self.clusters),
                             mean=round(sum(scores.values()) / len(scores), 6) if scores else 0.0)
        self.entries[digest] = entry
        _write(self.root / f"{digest}.json", entry.model_dump(mode="json", by_alias=True))
        return entry

    def frontier(self) -> tuple[str, ...]:
        return pareto_frontier({digest: entry.clusters for digest, entry in self.entries.items()})


def diff_stat(diff: str) -> str:
    """``2 file(s), 3 hunk(s), +10 -1``: a diff's size, never its content."""
    lines = diff.splitlines()
    files = sum(1 for line in lines if line.startswith("+++ "))
    added = sum(1 for line in lines if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in lines if line.startswith("-") and not line.startswith("---"))
    try:
        hunks = len(diffs.hunks(diff))
    except ValueError:
        hunks = 0
    return f"{files} file(s), {hunks} hunk(s), +{added} -{removed}"


def summary_line(message: str, limit: int = 120) -> str:
    """The first non-empty line of a proposer's reply, clipped."""
    for line in message.splitlines():
        flat = " ".join(line.split())
        if flat:
            return flat if len(flat) <= limit else flat[: limit - 3].rstrip() + "..."
    return "(no summary)"


def _read(path: Path) -> dict[str, Any] | None:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return document if isinstance(document, dict) else None


def _write(path: Path, document: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")


__all__ = ["ARCHIVE_SCHEMA", "PARENT_MODES", "PARENT_SHARPNESS", "PASSING", "Archive", "ArchiveEntry",
           "CandidateRecord", "ScreenScore", "ScreenStage", "Screening", "case_scores", "cluster_means",
           "diff_stat", "dominates", "halving_keep", "paired_delta", "parent_seed", "parent_weights",
           "pareto_frontier", "screen_order", "screen_seed", "select_parent", "summary_line"]
