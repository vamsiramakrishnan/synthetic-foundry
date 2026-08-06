#!/usr/bin/env python3
"""Replay a rotating, dispersed sample of supported build configurations.

The ordinary CI replay checks are deliberately fixed golden paths.  This sweep
does the complementary job: cover the public configuration space with Halton
points, discard combinations the registries say cannot be built, and use the
same farthest-first traversal as mosaics to choose a small, unlike sample.

``GITHUB_RUN_NUMBER`` rotates the candidate order.  Since farthest-first starts
at candidate zero and resolves ties by input order, that changes the sample on
each run without introducing randomness or making a failed selection
irreproducible.
"""

from __future__ import annotations

import argparse
import os
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from typing import Sequence, TypeVar

from worldloom import domains, facets, landscape, locales
from worldloom.dispersion import farthest_first, halton, manhattan


PERIODS = (1, 2, 3)
POOL_SIZE = 1_024
T = TypeVar("T")


@dataclass(frozen=True)
class FacetProfile:
    """One safe facet claim, or the no-facet baseline."""

    label: str
    claims: tuple[str, ...] = ()


@dataclass(frozen=True)
class Configuration:
    facet: FacetProfile
    locale: str
    estate: str | None
    periods: int
    engine: str

    @property
    def label(self) -> str:
        estate = self.estate or "none"
        return (
            f"{self.engine}__{self.locale}__{self.facet.label}__"
            f"estate-{estate}__periods-{self.periods}"
        )


def _facet_profiles() -> tuple[FacetProfile, ...]:
    """Facet claims that compose with every registered engine.

    Engine-specific physics is deliberately excluded.  Passing a retail
    margin range to procurement, for example, is not an adversarial build; it
    is an invalid command.  Estate-implying claims are excluded for the same
    reason because an engine without a registered landscape cannot honour
    them.  Roles, lore, calendars and filing obligations remain in the field.
    """
    profiles = [FacetProfile("none")]
    for name in sorted(facets.FACETS):
        for value in facets.choices(name):
            implication = facets.FACETS[name].choice(value).implies
            if implication.physics or implication.estate is not None:
                continue
            resolution = facets.resolve(**{name: value})
            if resolution.conflicts:
                continue
            profiles.append(FacetProfile(f"{name}-{value}", (f"{name}={value}",)))
    return tuple(profiles)


def _registries() -> tuple[
    tuple[FacetProfile, ...], tuple[str, ...], tuple[str | None, ...], tuple[str, ...]
]:
    facet_profiles = _facet_profiles()
    locale_names = tuple(sorted(locales.LOCALES))
    estate_names: tuple[str | None, ...] = (
        None,
        *sorted({
            profile
            for vocabulary in landscape.LANDSCAPES.values()
            for profile in vocabulary.profiles
        }),
    )
    engine_names = tuple(
        name
        for name in domains.names()
        if (registered := domains.by_name(name)) is not None
        and registered.default_archetype
    )
    if not all((facet_profiles, locale_names, estate_names, engine_names)):
        raise RuntimeError("the dispersed replay space has an empty registry axis")
    return facet_profiles, locale_names, estate_names, engine_names


def _pick(coordinate: float, values: Sequence[T]) -> T:
    return values[min(int(coordinate * len(values)), len(values) - 1)]


def _candidates() -> tuple[Configuration, ...]:
    facet_profiles, locale_names, estate_names, engine_names = _registries()
    candidates: list[Configuration] = []
    seen: set[Configuration] = set()
    for point in halton(5, POOL_SIZE):
        candidate = Configuration(
            facet=_pick(point[0], facet_profiles),
            locale=_pick(point[1], locale_names),
            estate=_pick(point[2], estate_names),
            periods=_pick(point[3], PERIODS),
            engine=_pick(point[4], engine_names),
        )
        # A non-null estate is valid only where the engine registered the words
        # needed to generate it.  Keep the engine in the candidate field with
        # ``estate=None`` rather than silently serving another vertical's names.
        if candidate.estate is not None and candidate.engine not in landscape.LANDSCAPES:
            continue
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
    return tuple(candidates)


def _one_hot(value: object, values: Sequence[object]) -> tuple[float, ...]:
    return tuple(1.0 if candidate == value else 0.0 for candidate in values)


def _coordinates(configuration: Configuration) -> tuple[float, ...]:
    facet_profiles, locale_names, estate_names, engine_names = _registries()
    period = (configuration.periods - min(PERIODS)) / (max(PERIODS) - min(PERIODS))
    # Categorical axes are nominal, not ordinal: Germany is not "further" from
    # Australia than the UK is.  One-hot coordinates make every mismatch cost
    # the same L1 distance while periods remains a genuinely ordered axis.
    return (
        *_one_hot(configuration.facet, facet_profiles),
        *_one_hot(configuration.locale, locale_names),
        *_one_hot(configuration.estate, estate_names),
        period,
        *_one_hot(configuration.engine, engine_names),
    )


def select(run_number: int, sample_size: int) -> tuple[Configuration, ...]:
    candidates = _candidates()
    if sample_size < 1:
        raise ValueError("sample size must be positive")
    if sample_size > len(candidates):
        raise ValueError(
            f"cannot select {sample_size} configurations from {len(candidates)} candidates"
        )
    offset = run_number % len(candidates)
    rotated = candidates[offset:] + candidates[:offset]
    chosen = farthest_first(
        tuple(_coordinates(candidate) for candidate in rotated), manhattan, sample_size
    )
    return tuple(rotated[index] for index in chosen)


def _build_command(configuration: Configuration, seed: int, out: Path) -> list[str]:
    registered = domains.by_name(configuration.engine)
    if registered is None or not registered.default_archetype:
        raise RuntimeError(f"engine {configuration.engine!r} has no default archetype")
    command = [
        "worldloom",
        "build",
        "--seed",
        str(seed),
        "--archetype",
        registered.default_archetype,
        "--locale",
        configuration.locale,
        "--periods",
        str(configuration.periods),
    ]
    for claim in configuration.facet.claims:
        command.extend(("--facet", claim))
    if configuration.estate is not None:
        command.extend(("--estate", configuration.estate))
    command.extend(("--out", str(out)))
    return command


def _run(command: Sequence[str]) -> None:
    print("+", " ".join(command), flush=True)
    subprocess.run(command, check=True)


def _assert_byte_identical(expected: Path, actual: Path) -> None:
    expected_files = {
        path.relative_to(expected) for path in expected.rglob("*") if path.is_file()
    }
    actual_files = {path.relative_to(actual) for path in actual.rglob("*") if path.is_file()}
    if expected_files != actual_files:
        missing = sorted(str(path) for path in expected_files - actual_files)
        extra = sorted(str(path) for path in actual_files - expected_files)
        raise AssertionError(f"replay file set differs; missing={missing}, extra={extra}")
    for relative in sorted(expected_files):
        if (expected / relative).read_bytes() != (actual / relative).read_bytes():
            raise AssertionError(f"replay differs byte-for-byte at {relative}")


def replay(configuration: Configuration, seed: int, root: Path) -> None:
    original = root / f"{configuration.label}__original"
    replayed = root / f"{configuration.label}__replay"
    original_command = _build_command(configuration, seed, original)
    # Narration gives replay an actual ledger to consume.  No rendered format
    # is requested: exact corpus bytes exercise the recipe, IR and prose while
    # keeping this rotating sweep materially cheaper than the fixed render jobs.
    _run([*original_command[:-2], "--narrate", *original_command[-2:]])
    replay_command = _build_command(configuration, seed, replayed)
    _run([*replay_command[:-2], "--replay", str(original), *replay_command[-2:]])
    _assert_byte_identical(original, replayed)
    print(f"byte-identical: {configuration.label}", flush=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-number",
        type=int,
        default=int(os.environ.get("GITHUB_RUN_NUMBER", "0")),
        help="deterministic rotation key (default: GITHUB_RUN_NUMBER or 0)",
    )
    parser.add_argument("--sample-size", type=int, default=3)
    parser.add_argument(
        "--root",
        type=Path,
        help="keep build outputs here; omitted uses a temporary directory",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the sample only")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    configurations = select(args.run_number, args.sample_size)
    print(
        f"dispersed replay run={args.run_number} sample={len(configurations)} "
        f"pool={len(_candidates())}"
    )
    for index, configuration in enumerate(configurations, start=1):
        print(f"  {index}. {configuration.label}")
    if args.dry_run:
        return 0
    if shutil.which("worldloom") is None:
        raise RuntimeError("worldloom executable not found; install the package first")

    if args.root is not None:
        args.root.mkdir(parents=True, exist_ok=False)
        root_context = None
        root = args.root
    else:
        root_context = tempfile.TemporaryDirectory(prefix="worldloom-dispersed-replay-")
        root = Path(root_context.name)

    try:
        for index, configuration in enumerate(configurations):
            replay(configuration, seed=81_280 + index, root=root)
    finally:
        if root_context is not None:
            root_context.cleanup()
    return 0


if __name__ == "__main__":
    sys.exit(main())
