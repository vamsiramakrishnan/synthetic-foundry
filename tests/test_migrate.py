"""The migration guarantee: no published corpus is ever stranded by a schema bump.

Two halves, and the first is the one that does the work:

1. A frozen fixture corpus at the **current** schema version lives in
   ``tests/fixtures/schema-current``. Loading and validating it is what makes
   the bump policy executable — the PR that bumps ``corpus.SCHEMA_VERSION``
   cannot merge without extending the migration chain, because this file goes
   red until it does. ``examples/retail-close`` is also current-version and
   CI-validated, but it is hand-authored and load-bearing for other tests, so
   the policy stands on a separate fixture rather than repointing it.

2. ``worldloom.migrate.migrate`` today: identity for the current version,
   refusal (naming both versions) for anything it cannot walk forward.

The fixture is deliberately minimal — plan-only retail (no narration, no
rendered artifacts), one period, ``eval_density=0.0``, and a single-unit
archetype so ``facts.jsonl`` stays small (~70KB on disk against ~310KB for
the default archetype). It was frozen by::

    from worldloom import MonthEndClose, RetailWorld
    from worldloom.archetypes import Archetype, CategorySpec, SiteFormat, UnitSpec

    tiny = Archetype(
        key="migrate_fixture_minimal",
        label="Minimal single-unit retailer (migration fixture)",
        industry="Omnichannel retail",
        annual_revenue=7_800_000,
        employees=80_000,
        units=(
            UnitSpec(
                key="food", name="Food", kind="supermarkets", share=1.0,
                categories=(
                    CategorySpec("Fresh", 0.55, 0.238),
                    CategorySpec("Packaged Grocery", 0.45, 0.261),
                ),
                site_formats=(SiteFormat("Supermarket", 12, 1.00),),
            ),
        ),
    )
    world = RetailWorld(seed=8128, archetype=tiny).build()
    world = world.run(MonthEndClose(period="2026-01", eval_density=0.0))
    world.export("tests/fixtures/schema-current")

The archetype key is unregistered on purpose: the recipe records archetypes
by key, so a registered key would let ``worldloom rebuild`` silently produce
a *different* world under that name, while an unregistered one fails loudly.
The fixture is frozen bytes, not a build product — it must never be
regenerated to make a failing test pass, because the bytes on disk are the
stand-in for every corpus published at their version.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from worldloom import World
from worldloom.corpus import SCHEMA_VERSION, WORLD_FILE, CorpusError
from worldloom.migrate import migrate

FIXTURE = Path(__file__).parent / "fixtures" / "schema-current"


def _corpus_bytes(root: Path) -> dict[str, bytes]:
    """Every file under *root*, keyed by relative path, as bytes."""
    return {
        str(path.relative_to(root)): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _doctored(tmp_path: Path, version: object) -> Path:
    """A copy of the fixture whose header claims schema version *version*."""
    copy = tmp_path / "doctored"
    shutil.copytree(FIXTURE, copy)
    header = json.loads((copy / WORLD_FILE).read_text(encoding="utf-8"))
    header["schema_version"] = version
    (copy / WORLD_FILE).write_text(json.dumps(header), encoding="utf-8")
    return copy


# -- The policy --------------------------------------------------------------


def test_frozen_fixture_is_current_version_and_validates() -> None:
    """The bump policy, as a test.

    If this fails because you are bumping ``corpus.SCHEMA_VERSION``, that is
    the point — the bumping PR must: (a) move the old fixture to a versioned
    name (``tests/fixtures/schema-v{old}``), (b) freeze a new fixture at the
    new version under ``tests/fixtures/schema-current``, and (c) extend
    ``worldloom.migrate._STEPS`` with the step that carries the old fixture
    to the new version — then add a test that migrates ``schema-v{old}`` and
    validates the result. Never regenerate or delete the old fixture: its
    bytes stand in for every corpus already published at that version.
    """
    world = World.load(FIXTURE)
    assert world.schema_version == SCHEMA_VERSION
    report = world.validate()
    assert report.ok, report.violations


# -- Identity migration ------------------------------------------------------


def test_migrate_current_version_is_byte_identical(tmp_path: Path) -> None:
    out = migrate(FIXTURE, tmp_path / "out")
    assert out == tmp_path / "out"
    assert _corpus_bytes(out) == _corpus_bytes(FIXTURE)


def test_migrated_corpus_loads_and_validates(tmp_path: Path) -> None:
    out = migrate(FIXTURE, tmp_path / "out")
    assert World.load(out).validate().ok


# -- Refusals ----------------------------------------------------------------


def test_migrate_refuses_future_version_naming_both(tmp_path: Path) -> None:
    future = SCHEMA_VERSION + 1
    doctored = _doctored(tmp_path, future)
    with pytest.raises(ValueError, match=rf"version {future} .*\({SCHEMA_VERSION}\)"):
        migrate(doctored, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_migrate_refuses_unknown_old_version_naming_both(tmp_path: Path) -> None:
    # Version 0 was never a schema version this engine wrote, so the chain has
    # no step for it — the refusal names where it stands and where it cannot get.
    doctored = _doctored(tmp_path, 0)
    with pytest.raises(ValueError, match=rf"version 0 to {SCHEMA_VERSION}"):
        migrate(doctored, tmp_path / "out")
    assert not (tmp_path / "out").exists()


def test_migrate_refuses_a_version_that_is_not_a_version(tmp_path: Path) -> None:
    # `true` is an `int` to isinstance; the refusal must not treat it as 1.
    doctored = _doctored(tmp_path, True)
    with pytest.raises(ValueError, match="not a version"):
        migrate(doctored, tmp_path / "out")


def test_migrate_refuses_nonempty_destination_unless_overwritten(tmp_path: Path) -> None:
    occupied = tmp_path / "out"
    occupied.mkdir()
    (occupied / "keepsake.txt").write_text("do not clobber", encoding="utf-8")
    with pytest.raises(FileExistsError, match="overwrite"):
        migrate(FIXTURE, occupied)
    out = migrate(FIXTURE, occupied, overwrite=True)
    assert not (out / "keepsake.txt").exists()
    assert _corpus_bytes(out) == _corpus_bytes(FIXTURE)


def test_migrate_refuses_in_place(tmp_path: Path) -> None:
    copy = tmp_path / "copy"
    shutil.copytree(FIXTURE, copy)
    with pytest.raises(ValueError, match="onto itself"):
        migrate(copy, copy, overwrite=True)
    # The refusal must fire before anything destructive: the source survives.
    assert _corpus_bytes(copy) == _corpus_bytes(FIXTURE)


def test_migrate_of_something_that_is_not_a_corpus_is_a_corpus_error() -> None:
    with pytest.raises(CorpusError, match="no corpus at"):
        migrate("no-such-world", "irrelevant")
