"""A deterministic generational loop over build *configurations*, never prose.

Everything a generational loop needs already exists here except the loop.
``spaces`` declares what a build can vary, ``dispersion`` spreads a first
population through that space, ``fleet`` measures a directory of builds and
keeps one champion per structural niche (``fleet.curate``'s MAP-Elites grid).
What was missing is the generational closure: propose → build → measure →
select → vary-the-champions, with every step recorded. This module is that
closure and only that closure — it adds **no measurement and no fitness of its
own**. Fitness is ``fleet``'s integer metric, selection is ``fleet.curate``'s
archive, and both honesty rules travel with them unchanged: selection reads
deterministic integers only (vendi is carried in the manifest because
``qualify`` reports it, and gates nothing — an eigendecomposition's last bits
vary by BLAS build), and a purpose ``fleet`` cannot measure is refused with
the reference data it would need, never approximated.

**The genome is a build configuration.** A member of a generation is a row of
a ``spaces.BuildSpace`` — archetype, locale, estate, policies, messiness,
history, periods, storyline, genome, eval_density, knowledge — and a child is
its parent's row with exactly one axis moved. Nothing here evolves a corpus's
*content*: the same argument ``fleet``'s module docstring makes ("a curator is
downstream of generation") one level up. What a curation hands the next
generation is which configurations survived; the world builder itself never
consumes a fitness.

**Variation is ranked, not drawn.** Each child slot takes the least-explored
admissible single-axis variation of its parent: candidates are every
``(axis, value)`` the parent does not already hold, ranked first by how many
times that value has appeared anywhere in the run's proposed configurations
(ascending — the loop prefers what it has never built), with ties broken by
``ids.content_key`` over the run seed, generation, slot, axis and value. That
tie-break is the run's entire use of the seed beyond generation zero: a
seeded *ordering*, not a draw, so the choice replays from the manifest and no
``random`` is anywhere in the loop. Candidates the registries refuse are
skipped and **recorded with the refusal** — copied from
``.github/scripts/dispersed_replay.py``'s gates, whose docstring records why:
sampling a command the CLI promises to reject tests argument validation, not
the corpus, and can fail before there is anything to measure.

**Builds go through the ``worldloom`` executable, not the Python API.** The
same choice ``dispersed_replay.py`` made, for a sharper reason here: the axes
of ``spaces.build_space`` *are* CLI flags, and the orchestration those flags
imply — timeline sampling, the storyline rotation, eval-density mapping,
actor wiring, the order the messiness pass runs in — lives in ``cli.py`` and
nowhere else. Driving the API directly would re-implement that orchestration
in a second place that drifts, which is exactly the two-accounts failure the
recipe module exists to prevent. A subprocess per member also means each
world builds in a fresh interpreter, the same isolation argument
``tools/sweep.py``'s ``process`` mode makes.

**Resumable by rerun.** A member whose corpus already exists on disk is not
rebuilt: the run is deterministic, so the bytes there are the bytes this run
would write, and ``fleet``'s replay verification re-checks them anyway — a
corrupted or foreign corpus fails the survey by name rather than being
silently trusted. Manifests are rewritten on every pass in ``fleet``'s
canonical form (sorted keys, two-space indent, one trailing newline) and
carry no absolute path, no clock and no float this module computed, so two
same-seed runs into different directories produce byte-identical manifests.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import dispersion, fleet, spaces
from .ids import content_key

#: What each generation directory records about itself. One name per
#: generation, beside the `fleet-manifest.json` that `fleet.curate` writes
#: there, so a generation carries its proposals and its verdict side by side.
GENERATION_MANIFEST_NAME = "generation-manifest.json"

#: The run-level summary at the out directory's root.
RUN_MANIFEST_NAME = "evolution-manifest.json"

#: Axes this loop refuses to vary, with the reason carried as data so the run
#: manifest can state the omission the way `fleet._UNDERIVABLE` states its
#: coverage omission. `surface` is the load-bearing one: a specification is
#: resolved to consequences and never recorded (`--spec`'s own design), so a
#: spec build and a flags build of one configuration write *identical* recipes
#: — the same seed on both sides of the variation would be the same corpus,
#: `fleet`'s `no_repeated_world` floor would fail the generation, and
#: selection could never see the axis move. Refused at the door rather than
#: silently projected, because an axis the measurement cannot witness is not
#: an axis a selection loop can honestly claim to have explored.
UNEVOLVABLE: Mapping[str, str] = {
    "surface": (
        "a specification is resolved to consequences and never recorded, so a"
        " spec build and a flags build write identical recipes; a same-seed"
        " single-axis variation on this axis is the same corpus twice, which"
        " fleet's no_repeated_world floor rightly fails, and selection could"
        " never observe the variation. Select the axis out of the space before"
        " evolving."
    ),
}

#: The value each axis takes when the caller's space does not carry it — the
#: CLI's own defaults, so a subspace run builds exactly what `worldloom build`
#: builds when the corresponding flag is omitted. `archetype` included: the
#: CLI defaults to the retailer, and a space that varies only, say, locale and
#: history should evolve retailers rather than refuse.
_DEFAULTS: Mapping[str, str] = {
    "archetype": "omnichannel_retailer",
    "locale": "none",
    "estate": "none",
    "policies": "none",
    "messiness": "pristine",
    "history": "unforced",
    "periods": "1",
    "storyline": "fixed",
    "genome": "authored",
    "eval_density": "standard",
    "knowledge": "none",
}

#: The `history` values that name a timeline density rather than an incident
#: flag — the merge `build_space` documents.
_TIMELINE_DENSITIES = frozenset({"quiet", "steady", "turbulent"})

#: The structural-genome doses, fixed rather than evolved: the axis is the
#: *mechanism* (`spaces.build_space`'s own encoding — four states, not two
#: integers), and these are the doses `AGENTS.md` documents for each. Evolving
#: the dose would widen a categorical axis into a numeric one the space does
#: not declare.
_GENOME_FLAGS: Mapping[str, tuple[str, ...]] = {
    "authored": (),
    "omission": ("--section-omission", "400"),
    "variant_bias": ("--variant-bias", "1"),
    "both": ("--section-omission", "400", "--variant-bias", "1"),
}

#: How many Halton points seed generation zero's candidate pool. A constant,
#: not a knob: the pool only has to be comfortably wider than any population
#: so the farthest-first traversal has room to spread, and a caller-facing
#: knob would be one more value two runs could silently disagree on.
_POOL = 512


class EvolveError(Exception):
    """Raised when a run cannot be proposed, built, or continued."""


def excluded(space: spaces.BuildSpace) -> dict[str, str]:
    """Axis → reason, for every axis of *space* this loop cannot drive.

    Two kinds of exclusion, each with its reason as data so a caller can print
    it rather than paraphrase it: the axes in `UNEVOLVABLE` (refused on
    principle — see there), and axes with no build-flag mapping here, which a
    caller from a newer `spaces.build_space` may legitimately hold before this
    module learns their flag. `evolve` *refuses* a space containing any of
    these rather than selecting them out itself, because silently narrowing
    the space would report an exploration of axes the run never touched — this
    helper is for the caller to do the narrowing as a visible act.
    """
    reasons: dict[str, str] = {}
    for name in space.names:
        if name in UNEVOLVABLE:
            reasons[name] = UNEVOLVABLE[name]
        elif name not in _DEFAULTS:
            reasons[name] = (
                "no build-flag mapping in evolve yet; the axis arrived in"
                " spaces.build_space() and this loop has not learned its flag"
            )
    return reasons


# ---------------------------------------------------------------------------
# What the registries refuse — the buildability gate
# ---------------------------------------------------------------------------


def refusal(row: Mapping[str, str]) -> str | None:
    """Why *row* cannot be built, or ``None`` when the registries admit it.

    Every check mirrors a refusal the CLI actually makes (`cli.py`'s
    single-episode block and the `--timeline`/`--actors` exclusion) or a gate
    `dispersed_replay.py` carries (the estate-vocabulary and `max_periods`
    gates, read from the same declarations the CLI refuses on so the two
    cannot drift). Checked *here*, before a subprocess is spent, because a
    proposed configuration that the CLI rejects tests argument validation
    rather than the corpus — `dispersed_replay.py`'s docstring records that
    lesson and this function is its port.

    Values are checked against the registries too: an axis value no registry
    knows is a configuration nothing can build, and admitting it would turn a
    typo into a subprocess failure three steps later.
    """
    from . import archetypes, domains, landscape, locales, messiness, policies

    for name in row:
        if name not in _DEFAULTS:
            # An axis with no flag mapping is a knob this loop cannot turn: a
            # row carrying one would build *something*, silently unvaried on
            # that axis, and report the variation explored. Refused here as
            # well as at `evolve`'s door so the gate holds for rows arriving
            # from anywhere, not only from this module's own proposers.
            return (
                f"axis {name!r} has no build-flag mapping here; evolve can only"
                " vary what `worldloom build` can be told"
            )

    full = {**_DEFAULTS, **row}

    archetype = full["archetype"]
    if archetype not in archetypes.available():
        return f"archetype {archetype!r} names no registered shape"
    domain = domains.for_archetype(archetype)
    if domain is None:
        return f"archetype {archetype!r} belongs to no registered engine"

    if full["locale"] not in ("none", *locales.LOCALES):
        return f"locale {full['locale']!r} is not registered"
    if full["messiness"] not in messiness.PROFILES:
        return f"messiness {full['messiness']!r} is not a registered profile"
    if full["policies"] not in policies.LEVELS:
        return f"policies {full['policies']!r} is not a registered level"
    if full["estate"] not in ("none", "small", "medium", "large"):
        return f"estate {full['estate']!r} is not an estate profile"
    if full["history"] not in ("unforced", "incident", "no_incident", *_TIMELINE_DENSITIES):
        return f"history {full['history']!r} is not a value the merged axis carries"
    if full["storyline"] not in ("fixed", "varied"):
        return f"storyline {full['storyline']!r} is not fixed or varied"
    if full["genome"] not in _GENOME_FLAGS:
        return f"genome {full['genome']!r} is not a structural-genome state"
    if full["eval_density"] not in ("low", "standard", "high"):
        return f"eval_density {full['eval_density']!r} is not a density level"
    if full["knowledge"] not in ("none", "conversations", "actors"):
        return f"knowledge {full['knowledge']!r} is not a knowledge layer"
    try:
        periods = int(full["periods"])
    except ValueError:
        return f"periods {full['periods']!r} is not a number"
    if periods < 1:
        return f"periods {periods} is not at least 1"

    # A non-none estate is valid only where the engine registered the words to
    # generate it — procurement has no landscape vocabulary, and serving it
    # another vertical's names is worse than serving none.
    if full["estate"] != "none" and domain.name not in landscape.LANDSCAPES:
        return (
            f"estate {full['estate']!r} on {domain.name}, which registers no"
            " landscape vocabulary"
        )
    # The same declaration the CLI refuses on (`Domain.max_periods`), read
    # rather than restated so the cap cannot drift: today only insurance
    # declares one, because `QuarterlyReserving` refuses its own second run.
    if domain.max_periods is not None and periods > domain.max_periods:
        return (
            f"{domain.name} builds at most {domain.max_periods} period(s)"
            f" per corpus, and {periods} were asked for"
        )
    if domain.single_episode is not None:
        # cli.py's single-episode refusal block, projected onto the axes: the
        # close-loop flags belong to the retail incident/actor machinery and
        # are refused rather than ignored on every other vertical.
        for axis, legal in (
            ("history", "unforced"),
            ("storyline", "fixed"),
            ("eval_density", "standard"),
            ("knowledge", "none"),
        ):
            if full[axis] != legal:
                return (
                    f"{axis}={full[axis]!r} belongs to the retail close; the"
                    f" {domain.name} vertical runs one episode per period and"
                    f" accepts only {legal!r}"
                )
    # Retail-side exclusion the merged axes cannot express: a sampled history
    # is decided before the first decision is taken, and an actor episode is
    # resumed one decision at a time — cli.py refuses the pair outright.
    if full["knowledge"] == "actors" and full["history"] in _TIMELINE_DENSITIES:
        return (
            "knowledge=actors cannot ride a timeline density; a sampled history"
            " is decided before an actor episode's first decision is taken"
        )
    return None


# ---------------------------------------------------------------------------
# One proposed member, and how it is built
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Proposal:
    """One configuration a generation intends to build, with its provenance."""

    label: str
    generation: int
    seed: int
    configuration: Mapping[str, str]
    parent: str
    """``genN/label`` of the champion this child varies, empty for generation
    zero's dispersed sample."""
    axis: str
    from_value: str
    to_value: str
    refused: tuple[tuple[str, str, str], ...]
    """``(axis, value, reason)`` for every candidate variation the ranking
    examined and stepped over — the registries' refusals and the already-
    proposed duplicates — kept so the manifest shows not only what was chosen
    but what the choice had to step past. Deterministic: the walk order is the
    space's declared axis and value order."""

    def as_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "seed": self.seed,
            "configuration": {k: self.configuration[k] for k in sorted(self.configuration)},
            "parent": self.parent,
            "variation": (
                {"axis": self.axis, "from": self.from_value, "to": self.to_value}
                if self.axis else None
            ),
            "refused_candidates": [
                {"axis": axis, "value": value, "reason": reason}
                for axis, value, reason in self.refused
            ],
            # The command with a *relative* out path: the manifest must be
            # byte-identical across two same-seed runs into different
            # directories, and an absolute path is the one thing on a build
            # command that legitimately differs between them.
            "command": list(self.command(Path(self.address))),
        }

    @property
    def address(self) -> str:
        """Where the member lives, relative to the run root — the same
        ``genN/<label>`` spelling the `parent` field uses."""
        return f"gen{self.generation}/{self.label}"

    def command(self, member_dir: Path) -> tuple[str, ...]:
        """The exact ``worldloom build`` invocation for this configuration.

        Only non-default axis values become flags, so a defaulted axis builds
        the same bytes as the flag never being typed — which is what lets a
        subspace run's members replay under plain ``worldloom build`` with no
        knowledge of this module.
        """
        full = {**_DEFAULTS, **self.configuration}
        command: list[str] = [
            "worldloom", "build",
            "--seed", str(self.seed),
            "--archetype", full["archetype"],
            "--periods", full["periods"],
        ]
        if full["locale"] != "none":
            command += ["--locale", full["locale"]]
        if full["estate"] != "none":
            command += ["--estate", full["estate"]]
        if full["policies"] != "none":
            command += ["--policies", full["policies"]]
        if full["messiness"] != "pristine":
            command += ["--messiness", full["messiness"]]
        if full["history"] == "incident":
            command += ["--incident"]
        elif full["history"] == "no_incident":
            command += ["--no-incident"]
        elif full["history"] in _TIMELINE_DENSITIES:
            command += ["--timeline", full["history"]]
        if full["storyline"] == "varied":
            command += ["--vary-incidents"]
        command += _GENOME_FLAGS[full["genome"]]
        if full["eval_density"] != "standard":
            command += ["--eval-density", full["eval_density"]]
        if full["knowledge"] == "conversations":
            command += ["--conversations"]
        elif full["knowledge"] == "actors":
            # `scripted` is the deterministic built-in; `agent` is an
            # interactive protocol, not a build configuration — the same line
            # `build_space`'s knowledge axis draws.
            command += ["--actors", "scripted"]
        # Narrated with the deterministic provider, `mosaic`'s writer: an
        # un-narrated corpus has no readable surface, so the reachability
        # reading in fleet's survey would run zero checks and the spine share
        # would be vacuous — tests/test_fleet.py's fixture states the same
        # reason for the same choice.
        command += ["--narrate", "--out", str(member_dir)]
        return tuple(command)


def _build(proposal: Proposal, member_dir: Path) -> None:
    """Build one member, or return without touching a corpus that exists.

    Skipping an existing corpus is the resume mechanism: the run is
    deterministic, so a member already on disk carries the bytes this run
    would write — and it is not taken on faith, because fleet's survey
    re-validates and replay-verifies every member and fails the generation by
    name if the directory holds anything else.
    """
    from . import corpus

    if (member_dir / corpus.WORLD_FILE).exists():
        return
    if shutil.which("worldloom") is None:
        raise EvolveError("worldloom executable not found; install the package first")
    member_dir.parent.mkdir(parents=True, exist_ok=True)
    command = proposal.command(member_dir)
    # `--overwrite` for the half-built case only: a directory without a world
    # header is an interrupted export, and rebuilding over it is the same
    # bytes. A *completed* corpus never reaches here.
    completed = subprocess.run(
        [*command, "--overwrite"], capture_output=True, text=True,
    )
    if completed.returncode != 0:
        # Loud on purpose: `refusal` admitted this configuration, so a CLI
        # rejection here is a gate defect, and the one thing worse than the
        # failure is a manifest recording a member that does not exist.
        tail = (completed.stderr or completed.stdout).strip().splitlines()[-8:]
        raise EvolveError(
            f"{proposal.label} did not build (exit {completed.returncode});"
            f" configuration {dict(proposal.configuration)!r} passed the"
            " buildability gate, so the gate and the CLI disagree.\n"
            + "\n".join(tail)
        )


# ---------------------------------------------------------------------------
# Proposing a generation
# ---------------------------------------------------------------------------


def _member_seed(run_seed: int, generation: int, index: int, population: int) -> int:
    """One seed per member, collision-free across the run.

    ``run_seed + generation * population + index`` — the arithmetic `mosaic`
    uses (`seed + N - 1`), extended by a generation stride. Distinct seeds per
    slot, so two different configurations never share a world by accident and
    a member is reproducible from the manifest without building the others.
    """
    return run_seed + generation * population + index


def _one_hot(value: str, values: Sequence[str]) -> tuple[float, ...]:
    return tuple(1.0 if candidate == value else 0.0 for candidate in values)


def _coordinates(space: spaces.BuildSpace, row: Mapping[str, str]) -> tuple[float, ...]:
    """*row* as a point for the farthest-first traversal.

    Every axis is one-hot, `dispersed_replay.py`'s encoding for its
    categorical axes: a `BuildSpace` axis is a declared vocabulary with no
    metric on it, and inventing ordinality for particular axis names here
    would have the sampler knowing semantics the space does not declare.
    """
    coordinates: list[float] = []
    for axis in space.axes:
        coordinates.extend(_one_hot(row[axis.name], axis.values))
    return tuple(coordinates)


def _pick(coordinate: float, values: Sequence[str]) -> str:
    return values[min(int(coordinate * len(values)), len(values) - 1)]


def propose_generation_zero(
    space: spaces.BuildSpace, *, seed: int, population: int
) -> tuple[dict[str, str], ...]:
    """A dispersed, buildable sample of *population* rows from *space*.

    `dispersed_replay.py`'s pipeline, re-pointed at a declared `BuildSpace`:
    Halton points cover the space, the registries' refusals discard what
    cannot build, and a farthest-first traversal under Manhattan distance
    takes the *population* least alike. The seed rotates the candidate order —
    that script's `GITHUB_RUN_NUMBER` trick — because farthest-first starts at
    candidate zero and breaks ties by input order, so rotation varies the
    sample per seed without introducing randomness or losing replayability.
    """
    candidates: list[dict[str, str]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for point in dispersion.halton(len(space.axes), _POOL):
        row = {
            axis.name: _pick(coordinate, axis.values)
            for coordinate, axis in zip(point, space.axes, strict=True)
        }
        key = tuple(sorted(row.items()))
        if key in seen or refusal(row) is not None:
            continue
        seen.add(key)
        candidates.append(row)
    if len(candidates) < population:
        raise EvolveError(
            f"the space yields {len(candidates)} buildable configuration(s) from"
            f" a pool of {_POOL} and the population asks for {population};"
            " widen the space or shrink the population"
        )
    offset = seed % len(candidates)
    rotated = candidates[offset:] + candidates[:offset]
    chosen = dispersion.farthest_first(
        tuple(_coordinates(space, row) for row in rotated),
        dispersion.manhattan,
        population,
    )
    return tuple(rotated[index] for index in chosen)


def _propose_children(
    space: spaces.BuildSpace,
    parents: Sequence[tuple[str, Mapping[str, str]]],
    *,
    seed: int,
    generation: int,
    population: int,
    explored: Mapping[tuple[str, str], int],
    proposed: frozenset[tuple[tuple[str, str], ...]],
) -> tuple[Proposal, ...]:
    """*population* single-axis variations of *parents*, round-robin.

    Parents are the previous generation's champions in `fleet.curate`'s own
    elite order (niche coordinates, ascending), so slot *j* varies champion
    ``j % len(parents)`` first — every champion parents children before any
    parents twice, and the assignment is a function of nothing but the
    champion list. When a champion's whole single-axis neighbourhood is
    already proposed or refused, the slot moves to the next champion in the
    same order rather than failing: a small space exhausts a neighbourhood
    honestly (a 2×2×2 space has three neighbours per row), and the child is
    still a champion's single-axis variation, which is the invariant. Only
    when *every* champion is exhausted does the generation refuse.
    """
    exploration = dict(explored)
    seen = set(proposed)
    children: list[Proposal] = []
    for slot in range(population):
        chosen: tuple[str, Mapping[str, str], tuple[tuple[int, str], str, str, dict[str, str]], tuple[tuple[str, str, str], ...]] | None = None
        for attempt in range(len(parents)):
            parent_address, parent_row = parents[(slot + attempt) % len(parents)]
            refused: list[tuple[str, str, str]] = []
            best: tuple[tuple[int, str], str, str, dict[str, str]] | None = None
            # Candidates ranked by (times this value has been proposed anywhere
            # in the run, seeded content key) and walked in the space's
            # declared axis and value order, keeping the minimum. A candidate
            # is only *checked* against the registries when it would improve on
            # the best admissible one found so far, so `refused` holds every
            # candidate the choice had to step past — the list a reader needs
            # to audit why the winner won — without paying a registry check for
            # candidates that never contended.
            for axis in space.axes:
                for value in axis.values:
                    if value == parent_row[axis.name]:
                        continue
                    rank = (
                        exploration.get((axis.name, value), 0),
                        content_key(str(seed), str(generation), str(slot), axis.name, value),
                    )
                    if best is not None and rank >= best[0]:
                        continue
                    child_row = {**parent_row, axis.name: value}
                    key = tuple(sorted(child_row.items()))
                    if key in seen:
                        refused.append((axis.name, value, "already proposed this run"))
                        continue
                    why = refusal(child_row)
                    if why is not None:
                        refused.append((axis.name, value, why))
                        continue
                    best = (rank, axis.name, value, child_row)
            if best is not None:
                chosen = (parent_address, parent_row, best, tuple(refused))
                break
        if chosen is None:
            raise EvolveError(
                f"generation {generation} slot {slot}: every single-axis"
                " variation of every champion is either already proposed or"
                " refused by the registries; the space is exhausted around"
                f" {', '.join(address for address, _ in parents)}"
            )
        parent_address, parent_row, best, refused_tuple = chosen
        _, axis_name, value, child_row = best
        children.append(Proposal(
            label=f"cfg-{slot:02d}",
            generation=generation,
            seed=_member_seed(seed, generation, slot, population),
            configuration=child_row,
            parent=parent_address,
            axis=axis_name,
            from_value=parent_row[axis_name],
            to_value=value,
            refused=refused_tuple,
        ))
        seen.add(tuple(sorted(child_row.items())))
        for pair in child_row.items():
            exploration[pair] = exploration.get(pair, 0) + 1
    return tuple(children)


# ---------------------------------------------------------------------------
# The run
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Generation:
    """One generation: what was proposed, what it measured, who survived."""

    index: int
    members: tuple[Proposal, ...]
    qualification: Mapping[str, Any]
    curation: Mapping[str, Any]
    champions: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "generation": self.index,
            "members": [member.as_dict() for member in self.members],
            "qualification": dict(self.qualification),
            "curation": dict(self.curation),
            "champions": list(self.champions),
        }

    def manifest(self) -> str:
        """Canonical JSON, `fleet`'s form — sorted keys, two-space indent, one
        trailing newline — so a generation's record diffs byte-for-byte."""
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


@dataclass(frozen=True)
class Evolution:
    """A whole run, as its manifests record it."""

    seed: int
    purpose: str
    population: int
    axes: Mapping[str, tuple[str, ...]]
    generations: tuple[Generation, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "seed": self.seed,
            "purpose": self.purpose,
            "population": self.population,
            "axes": {name: list(self.axes[name]) for name in sorted(self.axes)},
            # Stated the way fleet states `underivable`: the omission is part
            # of the record, so a reader of the manifest alone learns which
            # axis was not explored and why, not merely that it is absent.
            "unevolvable": {k: UNEVOLVABLE[k] for k in sorted(UNEVOLVABLE)},
            "generations": [
                {
                    "generation": generation.index,
                    "members": [member.label for member in generation.members],
                    "champions": list(generation.champions),
                }
                for generation in self.generations
            ],
        }

    def manifest(self) -> str:
        return json.dumps(self.as_dict(), indent=2, sort_keys=True) + "\n"


def evolve(
    space: spaces.BuildSpace,
    *,
    seed: int,
    generations: int,
    population: int,
    out_dir: str | Path,
    purpose: fleet.FleetPurpose = "challenge",
) -> Evolution:
    """Run *generations* of propose → build → measure → select → vary.

    Generation zero is a dispersed sample of *population* rows from *space*;
    every later generation is *population* single-axis variations of the
    previous generation's champions. Measurement and selection are
    ``fleet.qualify`` and ``fleet.curate`` over each generation's directory,
    with the given *purpose* — so every honesty rule of that module rides
    along: integer-only gating, vendi reported and never gating, and a
    purpose needing reference data this repository lacks refused naming it.

    Deterministic end to end: the same seed into any directory produces
    byte-identical manifests, and an interrupted run resumes by rerunning the
    same command (built members are recognised and not rebuilt).
    """
    # fleet's own refusal, before anything is proposed or built — a
    # "naturalistic" run must fail at the door with the reference data it
    # would need, not after a generation of subprocesses. Reaching for the
    # underscored name is deliberate and minimal: `fleet._checked_purpose` is
    # the seam this loop needs, and it should eventually be public on fleet
    # (`qualify` and `curate` both call it) rather than re-stated here where
    # the two copies could drift.
    checked = fleet._checked_purpose(purpose)

    if generations < 1:
        raise EvolveError(f"a run needs at least one generation, asked for {generations}")
    if population < 1:
        raise EvolveError(f"a generation needs at least one member, asked for {population}")
    # Refused, never silently selected out: a run that quietly dropped an axis
    # would report an exploration of a space it never explored. `excluded` is
    # the caller's tool for narrowing the space as a visible act.
    undrivable = excluded(space)
    if undrivable:
        name, reason = sorted(undrivable.items())[0]
        raise EvolveError(f"axis {name!r} cannot be evolved: {reason}")

    root = Path(out_dir)
    root.mkdir(parents=True, exist_ok=True)

    records: list[Generation] = []
    parents: tuple[tuple[str, Mapping[str, str]], ...] = ()
    explored: dict[tuple[str, str], int] = {}
    proposed: set[tuple[tuple[str, str], ...]] = set()

    for index in range(generations):
        if index == 0:
            rows = propose_generation_zero(space, seed=seed, population=population)
            members = tuple(
                Proposal(
                    label=f"cfg-{slot:02d}",
                    generation=0,
                    seed=_member_seed(seed, 0, slot, population),
                    configuration=row,
                    parent="", axis="", from_value="", to_value="",
                    refused=(),
                )
                for slot, row in enumerate(rows)
            )
        else:
            members = _propose_children(
                space, parents,
                seed=seed, generation=index, population=population,
                explored=explored, proposed=frozenset(proposed),
            )
        for member in members:
            proposed.add(tuple(sorted(member.configuration.items())))
            for pair in member.configuration.items():
                explored[pair] = explored.get(pair, 0) + 1

        generation_dir = root / f"gen{index}"
        for member in members:
            _build(member, generation_dir / member.label)

        # Measured by the instruments that already exist, never by arithmetic
        # of this module's own. Two surveys are paid here (qualify and curate
        # each run fleet's survey); `fleet._survey` is the seam that would
        # collapse them to one, and it should become public there rather than
        # be copied here.
        qualification = fleet.qualify(generation_dir, checked)  # type: ignore[arg-type]
        curation = fleet.curate(generation_dir, checked)  # type: ignore[arg-type]
        champions = tuple(champion.world for champion in curation.champions)
        if not champions and index + 1 < generations:
            raise EvolveError(
                f"generation {index} produced no champion — every member failed"
                " validation or replay — so there is nothing to vary; the"
                f" rejects are named in gen{index}/{fleet.MANIFEST_NAME}"
            )

        record = Generation(
            index=index,
            members=members,
            qualification=qualification.as_dict(),
            curation=curation.as_dict(),
            champions=champions,
        )
        (generation_dir / GENERATION_MANIFEST_NAME).write_text(
            record.manifest(), encoding="utf-8"
        )
        records.append(record)

        by_label = {member.label: member.configuration for member in members}
        parents = tuple(
            (f"gen{index}/{label}", by_label[label]) for label in champions
        )

    run = Evolution(
        seed=seed,
        purpose=checked,
        population=population,
        axes={axis.name: axis.values for axis in space.axes},
        generations=tuple(records),
    )
    (root / RUN_MANIFEST_NAME).write_text(run.manifest(), encoding="utf-8")
    return run


__all__ = [
    "GENERATION_MANIFEST_NAME",
    "RUN_MANIFEST_NAME",
    "UNEVOLVABLE",
    "Evolution",
    "EvolveError",
    "Generation",
    "Proposal",
    "evolve",
    "excluded",
    "propose_generation_zero",
    "refusal",
]
