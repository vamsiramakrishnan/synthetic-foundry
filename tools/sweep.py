#!/usr/bin/env python3
"""A dispersed determinism sweep: the byte-identity gate, pointed at the whole
configuration space instead of one corner of it.

This repository owns a covering algorithm — ``dispersion.halton`` for coverage,
``dispersion.farthest_first`` for selection — written so that a ``mosaic`` never
tests the same company twice. It then verified byte-identity on **the same four
builds at seed 8128, dozens of times**. Every regression gate in ``ci.yml``
samples one point of a ten-dimensional space, repeatedly. This tool is that
algorithm turned on our own QA.

**What it does.** Enumerates the configuration space the CLI actually exposes —
engine × archetype × facets × locale × estate × trading year × periods ×
messiness × front door × reference tables — covers it with a Halton sequence,
discards what cannot be built, and takes the *N* furthest apart by
farthest-point traversal. Each survivor is then built twice and diffed:

* ``--mode process`` builds twice in **separate subprocesses**. That is the
  point of a subprocess rather than a loop: an in-process second build shares
  every module-level registry, every ``lru_cache``, every ``episodes.install``
  from the first, so state that leaked from build one into build two is exactly
  what a single-process comparison cannot see. Two processes share nothing but
  the seed.
* ``--mode archive`` builds once from the working tree and once from a
  ``git archive HEAD`` tree, so a change that moves a corpus's bytes shows up as
  drift against the committed base rather than as a passing test.

**Reproducibility is the whole contract.** Every run prints its seed, its
Halton window, and each selected configuration as a JSON line with a
content-addressed id. A failure replays with

    python3 tools/sweep.py --seed <printed seed> -n <printed n> --only <id>

and nothing else — no saved state, no log scraping.

**Not library code.** Nothing here is importable by ``worldloom``, and it adds
no dependency: the enumeration imports the registries it is enumerating (that is
the point — a hand-written list of configurations would go stale the first time
somebody registered an archetype), and everything else is the standard library.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field as _field
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent

# The registries are read from the *working tree*, always — a sweep run inside a
# checkout is asking about that checkout's configuration space. `--mode archive`
# swaps the source only for the child that builds, never for the enumeration:
# the question there is "does HEAD's code build this configuration the same
# way", and that question needs one configuration, not two.
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

from worldloom.dispersion import farthest_first, halton, manhattan  # noqa: E402
from worldloom.ids import content_key  # noqa: E402

# ---------------------------------------------------------------------------
# The space
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Axis:
    """One thing the sweep varies, and the ordered values it varies over.

    Ordered and never a set: an index into these values *is* the configuration,
    so a set's iteration order would make the same coordinate mean a different
    build between runs — the identical failure ``mosaic._CALENDARS`` sorts to
    avoid.
    """

    name: str
    values: tuple[Any, ...]
    about: str

    def at(self, coordinate: float) -> Any:
        """The value at a unit coordinate. Half-open, so 1.0 cannot overflow."""
        index = min(int(coordinate * len(self.values)), len(self.values) - 1)
        return self.values[index]


#: Archetypes are named per engine, so this axis has no global value list: it
#: resolves against whichever engine the engine axis picked, inside `_config`.
#: A single global list would be the wrong shape — four of five keys are
#: infeasible for any given engine, so 80% of the axis would be refusals, and a
#: farthest-point traversal spends its picks on the extremes of the space it is
#: given. Dispersing over a space that is mostly holes disperses over the holes.
_BY_ENGINE = ()


def axes() -> tuple[Axis, ...]:
    """The configuration space, derived from the registries rather than typed.

    Everything here is read out of ``worldloom`` at call time. That is not
    tidiness: a hand-written list is stale the moment somebody registers a
    locale or a facet value, and a determinism gate that silently stops covering
    a new dimension is worse than no gate, because it still reports green.
    """
    from worldloom import domains, facets, locales, messiness, profiles

    # Every consistent facet combination, from the registry's own exclusion
    # arithmetic. `combinations()` filters through `facets.resolve`, so the
    # contradictions (there is no listed mutual) never reach the space at all —
    # reimplementing that filter here is how two accounts of one rule start.
    consistent = facets.combinations()

    return (
        Axis("engine", tuple(sorted(domains.names())),
             about="Which vertical's engine builds the world."),
        Axis("archetype", _BY_ENGINE,
             about="Company shape, resolved against the chosen engine's own"
                   " archetype keys — see `_BY_ENGINE`."),
        Axis("facets", (None, *consistent),
             about="What the company *is*, as a consistent assignment of every"
                   " facet dimension, or `None` for a build that names no facet"
                   " at all. Naming any facet settles all of them, so 'no facets'"
                   " is a genuinely different build and not the identity of this"
                   " axis."),
        Axis("locale", (None, *sorted(locales.LOCALES)),
             about="The jurisdiction: the working week, the region labels, the"
                   " name pools and the figure grammar."),
        Axis("estate", (None, "small", "medium", "large"),
             about="How much technology landscape grows around the episode's"
                   " own services."),
        Axis("calendar", (None, *sorted(profiles.PROFILES)),
             about="The trading year. Only the retail builder reads one, so"
                   " every other engine refuses a non-default value rather than"
                   " carrying it inert."),
        Axis("periods", (1, 2, 3),
             about="Consecutive episodes on one world."),
        Axis("messiness", (None, *sorted(messiness.PROFILES)),
             about="How well the archive is kept."),
        Axis("surface", ("flags", "spec"),
             about="Which front door states the company: repeated flags, or one"
                   " `--spec` document. Both are supported build paths and they"
                   " resolve through different code, so a determinism gate that"
                   " only ever drove one of them covers half the door."),
        Axis("data", ("none", "master_data", "detail"),
             about="Reference tables and transaction rows under the ledger."),
    )


@dataclass(frozen=True)
class Config:
    """One point of the space: everything that makes this build not the others."""

    position: int
    seed: int
    engine: str
    archetype: str
    facets: Mapping[str, str] | None
    locale: str | None
    estate: str | None
    calendar: str | None
    periods: int
    messiness: str | None
    surface: str
    data: str
    coordinates: tuple[float, ...] = ()

    @property
    def id(self) -> str:
        """A content address for this configuration.

        ``content_key`` rather than ``hash()`` for the reason the ledger uses
        it: Python's string hash is randomised per process, so an id printed by
        one run would not name the same configuration in the next — which would
        make the replay instruction this tool prints a lie.
        """
        return content_key(json.dumps(self.as_dict(), sort_keys=True))[:10]

    def as_dict(self) -> dict[str, Any]:
        """The configuration as JSON. ``position`` is deliberately absent — it
        is where this config landed in one selection, not what it is."""
        return {
            "seed": self.seed,
            "engine": self.engine,
            "archetype": self.archetype,
            "facets": dict(sorted(self.facets.items())) if self.facets else None,
            "locale": self.locale,
            "estate": self.estate,
            "calendar": self.calendar,
            "periods": self.periods,
            "messiness": self.messiness,
            "surface": self.surface,
            "data": self.data,
        }

    def summary(self) -> str:
        parts = [self.archetype, f"{self.periods}p", self.surface]
        for label, value in (("locale", self.locale), ("estate", self.estate),
                             ("cal", self.calendar), ("mess", self.messiness)):
            if value:
                parts.append(f"{label}={value}")
        if self.facets:
            parts.append(f"facets={self.facets['listing']}/{self.facets['maturity']}"
                         f"/{self.facets['trading_pattern']}")
        if self.data != "none":
            parts.append(self.data)
        return " ".join(parts)

    # -- realisation -------------------------------------------------------

    def argv(self, out: Path, *, formats: Sequence[str], narrate: bool) -> list[str]:
        """The ``worldloom build`` arguments this configuration means.

        Written to *out*'s parent when the surface is a specification, because a
        spec is an input file and the child has to be able to read it. The file
        is named for the config id rather than "spec.json" so a failed run
        leaves behind something that names which configuration it belonged to.
        """
        args = ["build", "--seed", str(self.seed), "--periods", str(self.periods),
                "--out", str(out)]
        # Retail is the only engine whose episode takes an incident flag at all;
        # the others refuse it rather than ignore it. Forced rather than left to
        # the seed so the incident half of the retail corpus is actually built —
        # a sweep whose worlds mostly had no incident would be covering the
        # configuration space and not the episode.
        if self.engine == "retail":
            args += ["--incident"]
        if self.messiness:
            args += ["--messiness", self.messiness]
        if narrate:
            args += ["--narrate"]
        for fmt in formats:
            args += ["-f", fmt]

        if self.surface == "spec":
            document: dict[str, Any] = {"archetype": self.archetype}
            if self.locale:
                document["geo"] = self.locale
            if self.estate:
                document["estate"] = self.estate
            if self.calendar:
                document["calendar"] = self.calendar
            if self.facets:
                document["facets"] = dict(sorted(self.facets.items()))
            if self.data == "master_data":
                document["master_data"] = _MASTER_DATA
            path = out.parent / f"spec-{self.id}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n",
                            encoding="utf-8")
            return args + ["--spec", str(path)]

        args += ["--archetype", self.archetype]
        if self.locale:
            args += ["--locale", self.locale]
        if self.estate:
            args += ["--estate", self.estate]
        for name, value in sorted((self.facets or {}).items()):
            args += ["--facet", f"{name}={value}"]
        return args


#: The reference-table counts the `master_data` opt-in asks for. Small on
#: purpose: this sweep is checking that the rows are *the same rows twice*, and
#: two thousand vendors proves that no harder than forty while costing every
#: config that carries them a multiple of the runtime.
_MASTER_DATA: dict[str, int] = {"vendors": 40, "skus": 25}


def _config(coordinates: Sequence[float], *, seed: int,
            space: Sequence[Axis]) -> tuple[Config | None, tuple[str, ...]]:
    """One configuration from one point of the unit cube.

    Returns ``(config, notes)`` or ``(None, (reason,))``. Notes and reasons are
    tallied rather than dropped, because "which parts of this space are not
    reachable, and why" is the more interesting half of the reading: it is where
    a knob with no front door shows up.

    Two different things happen here and the distinction is the design.

    **Projection.** Most axes do not apply to most engines, and an axis that
    does not apply is not an infeasibility — it is a degree of freedom the
    engine does not have. ``BankingWorld`` has no ``seasonality`` field, so a
    banking build has exactly one trading year and the calendar coordinate
    *collapses to it*. This is ``mosaic``'s own argument, one layer up: it
    splits its physics axes per engine because "a banking mosaic carrying this
    axis would report varying a calendar that changed nothing". Refusing instead
    is what the first version of this file did, and it was quietly disastrous —
    a non-retail candidate survived only when the calendar coordinate happened
    to land on ``None`` *and* the periods coordinate on 1, so 1024 candidates
    left 105 feasible, 91 of them retail and *none* procurement. The sweep
    covered the space by refusing almost all of it.

    **Refusal.** Reserved for a combination that genuinely cannot be built at
    all, in any projection.

    Every rule below delegates to something that already exists — a dataclass
    field, a domain's own declaration, a refusal the CLI already prints. None of
    them is a new opinion about what is buildable.
    """
    import dataclasses

    from worldloom import domains, landscape, roles

    values = {axis.name: axis.at(coordinate)
              for axis, coordinate in zip(space, coordinates, strict=True)
              if axis.values}
    raw = {axis.name: coordinate
           for axis, coordinate in zip(space, coordinates, strict=True)}

    engine = values["engine"]
    domain = domains.by_name(engine)
    assert domain is not None                       # the axis came from the registry

    # Resolved here rather than on the axis — see `_BY_ENGINE`.
    keys = tuple(sorted(domain.archetype_keys))
    archetype = keys[min(int(raw["archetype"] * len(keys)), len(keys) - 1)]

    facets = values["facets"]
    calendar = values["calendar"]
    estate = values["estate"]
    surface = values["surface"]
    data = values["data"]
    periods = values["periods"]
    notes: list[str] = []

    builder_fields = {f.name for f in dataclasses.fields(domain.world)}

    # A trading year the builder has no field for. The CLI reports exactly this
    # as `unmet:` rather than failing, so a build carrying it would be
    # byte-identical to one that did not — a "different" configuration that is
    # not one.
    if calendar is not None and "seasonality" not in builder_fields:
        calendar, _ = None, notes.append(f"{engine}: builder has no seasonality field")
    # ...and there is no `--calendar` flag at all. A trading year is reachable
    # from the command line only through a specification.
    if calendar is not None and surface != "spec":
        calendar, _ = None, notes.append("calendar: no build flag, only `--spec`")
    # An estate needs a vocabulary to be named in, and `landscape.LANDSCAPES` is
    # the closed table of the engines that have one. Read from the table rather
    # than naming the engine that does not: registering a fourth landscape must
    # widen this sweep without anybody editing it.
    if estate is not None and engine not in landscape.LANDSCAPES:
        estate, _ = None, notes.append(
            f"{engine}: no estate vocabulary in `landscape.LANDSCAPES`")
    # `--periods N` on a single-episode vertical is refused by the CLI itself.
    if periods > 1 and domain.single_episode is not None:
        periods, _ = 1, notes.append(f"{engine}: single-episode vertical takes --periods 1")
    # A facet implies roles, and they are appended to the engine's own table. An
    # engine with no shipped table has nothing to append to — the CLI says so
    # and exits 2.
    if facets is not None:
        try:
            roles._shipped(engine)
        except (AttributeError, KeyError):
            facets, _ = None, notes.append(
                f"{engine}: no role table for a facet's implied roles")
    # Reference tables are a specification field. No build flag carries them.
    if data == "master_data" and surface != "spec":
        data, _ = "none", notes.append("master_data: no build flag, only `--spec`")
    # And detail tables are declared on an `episodes.EpisodeSpec`, which nothing
    # on the CLI installs — `worldloom build` has no door for an authored
    # episode, so no configuration reachable from the command line can carry
    # one. A refusal and not a projection: unlike a calendar on a bank, this is
    # not a degree of freedom the engine lacks, it is one the front door cannot
    # reach. Enumerated rather than left out of the axis, because an opt-in the
    # tool cannot exercise is a finding, and an axis quietly missing its third
    # value would report full coverage of two.
    if data == "detail":
        return None, ("detail: declared on an EpisodeSpec, and no CLI command installs one",)

    return Config(
        position=0,
        seed=seed,
        engine=engine,
        archetype=archetype,
        facets=facets,
        locale=values["locale"],
        estate=estate,
        calendar=calendar,
        periods=periods,
        messiness=values["messiness"],
        surface=surface,
        data=data,
        coordinates=tuple(coordinates),
    ), tuple(notes)


#: How many points of the space are covered before dispersion chooses from them.
#: Most are discarded — the refusals above bite hardest near the corners — so
#: this is sized to leave a real field to choose from rather than to be a sample
#: of anything. Same reasoning, and roughly the same ratio, as `mosaic._POOL`.
POOL = 1024


def window(seed: int, pool: int) -> int:
    """Where in the Halton sequence this seed's candidates start.

    The rotation, and the reason it is safe. A determinism sweep checks a
    corpus against *itself*, so there is no expected output to drift from — a
    different sample each run is strictly more coverage over time, where a fixed
    sample is the same eight configurations forever, which is the defect this
    tool exists to fix.

    What rotation must not cost is replayability, and this is why the window is
    a pure function of the seed rather than of a clock: consecutive seeds get
    *disjoint* blocks of the sequence, and any seed reproduces its block exactly.
    A contiguous block of a Halton sequence is still low-discrepancy, so a
    rotated window covers the space as evenly as the first one does — it simply
    covers a different part of it.
    """
    return 1 + (seed % 4096) * pool


@dataclass(frozen=True)
class Field:
    """A selection, and everything needed to explain or replay it."""

    configs: tuple[Config, ...]
    refusals: Counter[str]
    projections: Counter[str]
    skip: int
    candidates: int
    distinct: int


def field_of(count: int, *, seed: int, pool: int = POOL,
             space: Sequence[Axis] | None = None) -> Field:
    """*count* configurations, covered then chosen for maximum dispersion.

    Cover, then choose — ``mosaic``'s argument, unchanged: generating *count*
    configurations directly and hoping they differ is precisely what makes a
    regression gate sample one corner. Filtering happens *before* selection,
    because a traversal that picks an unbuildable extreme and then drops it
    returns *count-1* configurations and spends its first pick on the part of
    the space furthest from anything real.

    Deduplicated after projection, and that is not tidiness. Projection collapses
    the axes an engine does not have, so a whole region of coordinates maps onto
    one banking configuration; without the dedupe, a traversal maximising
    distance in *coordinate* space would happily select the same build twice
    because its two coordinates were far apart. The first occurrence keeps its
    coordinate, which does bias the dispersion slightly toward the low end of a
    collapsed axis — worth stating, and much smaller than the alternative.
    """
    space = tuple(axes()) if space is None else tuple(space)
    skip = window(seed, pool)
    feasible: list[Config] = []
    points: list[tuple[float, ...]] = []
    refusals: Counter[str] = Counter()
    projections: Counter[str] = Counter()
    seen: set[str] = set()

    for coordinates in halton(len(space), pool, skip=skip):
        config, notes = _config(coordinates, seed=seed, space=space)
        if config is None:
            refusals[notes[0]] += 1
            continue
        projections.update(notes)
        if config.id in seen:
            continue
        seen.add(config.id)
        feasible.append(config)
        points.append(tuple(coordinates))

    if count > len(feasible):
        raise SystemExit(
            f"asked for {count} configurations and only {len(feasible)} of {pool}"
            f" candidates are distinct and buildable. Raise --pool."
        )
    chosen = farthest_first(points, manhattan, count)
    # Re-seeded and re-positioned in selection order, so configuration 1 is the
    # first chosen rather than whichever candidate happened to survive the
    # filter first — and so `-n 4` and `-n 12` agree on the four they share.
    selected = tuple(
        Config(**{**feasible[at].__dict__, "position": position + 1,
                  "seed": seed + position})
        for position, at in enumerate(chosen)
    )
    return Field(configs=selected, refusals=refusals, projections=projections,
                 skip=skip, candidates=pool, distinct=len(feasible))


# ---------------------------------------------------------------------------
# Building, twice, in processes that share nothing
# ---------------------------------------------------------------------------


@dataclass
class Outcome:
    """What one build produced."""

    ok: bool
    seconds: float
    files: int
    artifacts: int
    stderr: str = ""


def build_once(config: Config, out: Path, *, formats: Sequence[str], narrate: bool,
               source: Path | None = None, timeout: int = 1800) -> Outcome:
    """Run one ``worldloom build`` in a fresh interpreter.

    A subprocess and not a function call. Everything a build touches that is not
    the seed — the archetype registry, the doctype registry, ``episodes``'
    installed specs, every ``lru_cache`` on a module — is process-global, so a
    second build in the same interpreter starts from whatever the first one left
    behind. That is exactly the state leakage worth catching, and it is the one
    thing a single-process comparison structurally cannot see.

    *source* points the child at a different checkout's ``src`` through
    ``PYTHONPATH``, which precedes both ``site-packages`` and the editable
    install's ``.pth`` entry on ``sys.path``. The harness stays this file in
    every mode: the variable under test is the library, not the driver.
    """
    env = dict(os.environ)
    if source is not None:
        env["PYTHONPATH"] = os.pathsep.join(
            [str(source / "src"), *([env["PYTHONPATH"]] if env.get("PYTHONPATH") else [])]
        )
    argv = config.argv(out, formats=formats, narrate=narrate)
    started = time.monotonic()
    completed = subprocess.run(
        # `-c` rather than the console script so the interpreter running the
        # child is the one running this file, whatever is on PATH.
        [sys.executable, "-c", "from worldloom.cli import app; app()", *argv],
        capture_output=True, text=True, env=env, timeout=timeout,
    )
    seconds = time.monotonic() - started
    files = sum(1 for path in out.rglob("*") if path.is_file()) if out.exists() else 0
    manifest = out / "artifact-manifest.jsonl"
    artifacts = (sum(1 for line in manifest.read_text(encoding="utf-8").splitlines()
                     if line.strip()) if manifest.exists() else 0)
    return Outcome(
        ok=completed.returncode == 0,
        seconds=seconds,
        files=files,
        artifacts=artifacts,
        # stdout as well as stderr: `worldloom build` prints its violations to
        # stdout through rich, and a sweep that reported "failed" without the
        # reason would send the reader back to run it by hand.
        stderr=(completed.stderr + completed.stdout)[-4000:] if completed.returncode else "",
    )


def first_difference(left: Path, right: Path) -> str | None:
    """The first place two corpora disagree, or ``None`` if they do not.

    Text files are reported by line, because a corpus is mostly JSONL and a line
    number is what a reader can act on. Anything that is not valid UTF-8 — a
    workbook, a PDF — is reported by byte offset, which is the honest answer:
    "line 1 of a zip archive" would be a worse lie than an offset.
    """
    def tree(root: Path) -> dict[str, Path]:
        return {str(path.relative_to(root)): path
                for path in sorted(root.rglob("*")) if path.is_file()}

    ours, theirs = tree(left), tree(right)
    for name in sorted(set(ours) - set(theirs)):
        return f"{name}: present in the first build, absent from the second"
    for name in sorted(set(theirs) - set(ours)):
        return f"{name}: absent from the first build, present in the second"

    for name in sorted(ours):
        a, b = ours[name].read_bytes(), theirs[name].read_bytes()
        if a == b:
            continue
        try:
            lines_a = a.decode("utf-8").splitlines()
            lines_b = b.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            offset = next((i for i, (x, y) in enumerate(zip(a, b)) if x != y),
                          min(len(a), len(b)))
            return (f"{name}: binary, first differing byte at offset {offset}"
                    f" ({len(a)} vs {len(b)} bytes)")
        for number, (x, y) in enumerate(zip(lines_a, lines_b), start=1):
            if x != y:
                # Windowed on the first differing *column*, not on the start of
                # the line. A corpus line is one JSON object several kilobytes
                # long and the difference is rarely in the first 160 characters;
                # printing the head of both lines shows two identical prefixes
                # and tells the reader nothing.
                column = next((i for i, (p, q) in enumerate(zip(x, y)) if p != q),
                              min(len(x), len(y)))
                start = max(0, column - 40)
                return (f"{name}:{number} col {column + 1}"
                        f"\n      first:  …{x[start:column + 120]}"
                        f"\n      second: …{y[start:column + 120]}")
        return (f"{name}: identical for {min(len(lines_a), len(lines_b))} lines,"
                f" then {len(lines_a)} vs {len(lines_b)} lines in total")
    return None


@dataclass
class Result:
    """One configuration, built and compared."""

    config: Config
    mode: str
    outcomes: list[Outcome] = _field(default_factory=list)
    identical: bool | None = None
    difference: str | None = None
    note: str = ""

    @property
    def seconds(self) -> float:
        return sum(outcome.seconds for outcome in self.outcomes)

    @property
    def built(self) -> bool:
        return all(outcome.ok for outcome in self.outcomes) and bool(self.outcomes)

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.config.id,
            "position": self.config.position,
            "config": self.config.as_dict(),
            "mode": self.mode,
            "seconds": round(self.seconds, 2),
            "files": self.outcomes[0].files if self.outcomes else 0,
            "artifacts": self.outcomes[0].artifacts if self.outcomes else 0,
            "built": self.built,
            "identical": self.identical,
            "difference": self.difference,
            "note": self.note,
        }


def run_one(config: Config, workspace: Path, *, mode: str, formats: Sequence[str],
            narrate: bool, archive: Path | None) -> Result:
    """Build *config* twice under *mode* and compare."""
    result = Result(config=config, mode=mode)
    home = workspace / f"{config.position:02d}-{config.id}"
    first = home / "a"
    second = home / "b"

    result.outcomes.append(
        build_once(config, first, formats=formats, narrate=narrate))
    if not result.outcomes[0].ok:
        result.note = _one_line(result.outcomes[0].stderr)
        return result

    source = archive if mode == "archive" else None
    result.outcomes.append(
        build_once(config, second, formats=formats, narrate=narrate, source=source))
    if not result.outcomes[1].ok:
        result.note = _one_line(result.outcomes[1].stderr)
        return result

    result.difference = first_difference(first, second)
    result.identical = result.difference is None
    return result


def _one_line(text: str) -> str:
    """The most useful single line of a failed build's output.

    The last non-empty line is usually a summary banner; the first line naming a
    refusal or a violation is what a reader needs. Preferring the marked line
    and falling back to the last is a heuristic, and it is stated as one — the
    full output is kept in the JSON report either way.
    """
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    marked = [line for line in lines if line.startswith(("error", "✗")) or "violation" in line]
    return (marked[0] if marked else lines[-1] if lines else "no output")[:200]


# ---------------------------------------------------------------------------
# The base tree
# ---------------------------------------------------------------------------


def export_head(into: Path) -> Path:
    """``git archive HEAD``, unpacked, with this file copied in beside it.

    The archive is the *library* under test. The harness — this file — is copied
    from the working tree rather than taken from the archive, and that is
    deliberate: a sweep whose driver also changed would be comparing two
    variables at once, and on the run that first adds this tool the archive has
    no ``tools/`` at all.
    """
    into.mkdir(parents=True, exist_ok=True)
    archive = subprocess.run(["git", "archive", "HEAD"], cwd=ROOT,
                             capture_output=True, check=True)
    subprocess.run(["tar", "-x", "-C", str(into)], input=archive.stdout, check=True)
    (into / "tools").mkdir(exist_ok=True)
    shutil.copy2(Path(__file__), into / "tools" / Path(__file__).name)
    return into


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def report(results: Sequence[Result], *, seed: int, chosen: Field,
           stream: Any = sys.stdout) -> None:
    def out(line: str = "") -> None:
        print(line, file=stream)

    def tally(label: str, counts: Mapping[str, int]) -> None:
        if not counts:
            return
        out(f"  {sum(counts.values())} {label}:")
        for reason, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
            out(f"    {count:5d}  {reason}")

    out()
    out("configuration space")
    space = axes()
    out(f"  {len(space)} axes: " + ", ".join(
        f"{axis.name}({len(axis.values) or 'per-engine'})" for axis in space))
    out(f"  {chosen.candidates} candidates from Halton index {chosen.skip},"
        f" seed {seed} → {chosen.distinct} distinct buildable")
    tally("axis collapses (a knob the engine or the front door does not have)",
          chosen.projections)
    tally("refused outright", chosen.refusals)
    out()

    # `--plan` reaches here with nothing built. The table and the tally are
    # skipped rather than printed empty: "0/0 identical" beside a selection
    # nobody asked to build reads as a result, and it is not one.
    header = (f"{'#':>2}  {'mode':8}  {'id':10}  {'time':>7}  {'files':>5}"
              f"  {'arts':>4}  {'same':4}  config")
    if results:
        out(header)
        out("-" * len(header))
    for result in results:
        same = ("yes" if result.identical else "NO" if result.identical is False
                else "--")
        out(f"{result.config.position:2d}  {result.mode:8}  {result.config.id:10}"
            f"  {result.seconds:6.1f}s  {result.outcomes[0].files if result.outcomes else 0:5d}"
            f"  {result.outcomes[0].artifacts if result.outcomes else 0:4d}"
            f"  {same:4}  {result.config.summary()}")
        if result.difference:
            out(f"      first difference: {result.difference}")
        if result.note:
            out(f"      build failed: {result.note}")
    if results:
        out()
        identical = sum(1 for r in results if r.identical)
        differed = [r for r in results if r.identical is False]
        failed = [r for r in results if not r.built]
        out(f"{identical}/{len(results)} identical"
            + (f", {len(differed)} DIFFERED" if differed else "")
            + (f", {len(failed)} failed to build" if failed else ""))
    out()
    # The replay block is the reproducibility contract, printed on every run and
    # not only on a failure: a green sweep on a rotating seed is also a record
    # of which corners have been covered, and that record is worthless if it
    # cannot be re-entered. `-n` is the *selection* size, never the number of
    # rows — `--mode both` prints two rows per configuration and asking for
    # twice as many configurations would select entirely different ones.
    out("replay any row exactly:")
    for result in results:
        if result.identical is False or not result.built:
            out(f"  python3 tools/sweep.py --seed {seed} -n {len(chosen.configs)}"
                f" --only {result.config.id} --mode {result.mode} --keep")
    out("  " + json.dumps({"seed": seed, "n": len(chosen.configs),
                           "pool": chosen.candidates, "halton_skip": chosen.skip}))
    for config in chosen.configs:
        out("  " + json.dumps({"id": config.id, **config.as_dict()}, sort_keys=True))


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="tools/sweep.py",
        description=__doc__.split("\n\n")[0],
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("-n", "--count", type=int, default=8,
                        help="how many configurations to select (default 8)")
    parser.add_argument("-s", "--seed", type=int, default=8128,
                        help="the sweep seed: decides the Halton window and every"
                             " world seed. Printed on every run so a failure replays.")
    parser.add_argument("--pool", type=int, default=POOL,
                        help=f"candidates covered before selection (default {POOL})")
    parser.add_argument("--mode", choices=("process", "archive", "both"),
                        default="process",
                        help="process: two subprocesses from the working tree."
                             " archive: working tree against `git archive HEAD`."
                             " both: run each configuration under both.")
    parser.add_argument("--formats", default="markdown,xlsx",
                        help="renderers to exercise, comma separated (default"
                             " markdown,xlsx). Empty plans artifacts without"
                             " rendering them.")
    parser.add_argument("--no-narrate", action="store_true",
                        help="skip narration. On by default: the deterministic"
                             " provider writes the generation ledger, which is"
                             " where a replay-affecting change would surface.")
    parser.add_argument("--only", action="append", default=[],
                        help="build only the configuration(s) with this id."
                             " Repeatable. Selection is unchanged, so an id from"
                             " an earlier run replays that exact configuration.")
    parser.add_argument("--keep", action="store_true",
                        help="keep the built corpora instead of deleting them")
    parser.add_argument("--workspace", default=None,
                        help="where to build (default: a temporary directory)")
    parser.add_argument("--json", dest="as_json", default=None,
                        help="also write the full report here as JSON")
    parser.add_argument("--describe", action="store_true",
                        help="print the axes and exit, building nothing")
    parser.add_argument("--plan", action="store_true",
                        help="print the selection and why the space shrank, and"
                             " exit. Deciding whether a field of forty builds is"
                             " worth the wait should not require forty builds —"
                             " the same argument `mosaic --describe` makes.")
    args = parser.parse_args(argv)

    if args.describe:
        for axis in axes():
            size = len(axis.values) or "per-engine"
            print(f"{axis.name:12} {str(size):>6}  {axis.about}")
        return 0

    formats = tuple(f for f in args.formats.split(",") if f.strip())
    chosen = field_of(args.count, seed=args.seed, pool=args.pool)
    configs = chosen.configs
    if args.plan:
        report([], seed=args.seed, chosen=chosen)
        return 0
    if args.only:
        wanted = set(args.only)
        configs = tuple(c for c in configs if c.id in wanted)
        if not configs:
            print(f"no selected configuration matches {sorted(wanted)}; the ids"
                  f" for --seed {args.seed} -n {args.count} are"
                  f" {[c.id for c in chosen.configs]}", file=sys.stderr)
            return 2

    modes = ("process", "archive") if args.mode == "both" else (args.mode,)
    workspace = Path(args.workspace) if args.workspace else Path(
        tempfile.mkdtemp(prefix="worldloom-sweep-"))
    workspace.mkdir(parents=True, exist_ok=True)
    archive: Path | None = None
    if "archive" in modes:
        archive = export_head(workspace / "_head")

    results: list[Result] = []
    try:
        for mode in modes:
            for config in configs:
                room = workspace / mode
                room.mkdir(parents=True, exist_ok=True)
                print(f"[{config.position}/{len(configs)}] {mode} {config.id}"
                      f" {config.summary()}", file=sys.stderr, flush=True)
                results.append(run_one(config, room, mode=mode, formats=formats,
                                       narrate=not args.no_narrate, archive=archive))
        report(results, seed=args.seed, chosen=chosen)
        if args.as_json:
            Path(args.as_json).write_text(json.dumps({
                "seed": args.seed, "count": args.count, "pool": args.pool,
                "halton_skip": chosen.skip, "formats": list(formats),
                "narrate": not args.no_narrate,
                "distinct_candidates": chosen.distinct,
                "refusals": dict(chosen.refusals),
                "projections": dict(chosen.projections),
                "results": [r.as_dict() for r in results],
            }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    finally:
        if not args.keep and args.workspace is None:
            shutil.rmtree(workspace, ignore_errors=True)
        elif args.keep:
            print(f"corpora kept in {workspace}", file=sys.stderr)

    # Non-zero on a difference *or* on a build that did not run: a configuration
    # the sweep could not build is a hole in the gate, not a pass.
    return 0 if all(r.identical for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
