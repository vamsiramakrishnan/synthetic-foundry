"""Corpus migration: the guarantee that a schema bump strands no corpus.

``corpus.SCHEMA_VERSION`` is bumped when the on-disk layout changes
incompatibly. Until this module existed, the engine's whole answer to a bump
was ``World.load`` refusing anything *newer* than itself — correct for that
direction, and nothing at all for the other one: every corpus published at
version N would become unreadable the day version N+1 shipped. A corpus is a
directory of plain text precisely because it must outlive the library version
that wrote it (see ``corpus``), and that promise is empty without a path from
old bytes to new.

The shape here is a chain of version→version steps (``_STEPS``), walked from
the corpus's version up to the current one. Today the chain is empty and
``migrate`` is the identity: verify the version, copy the directory
byte-for-byte. That is deliberate — the *structure* is the deliverable, so the
first real bump adds one entry to the chain instead of designing a migration
system under deadline. The policy that forces that entry to be written is
executable: ``tests/test_migrate.py`` freezes a fixture corpus at the current
version, and the test that loads it fails on the PR that bumps
``SCHEMA_VERSION`` until the bumper extends the chain.

Refusals are ``ValueError``s naming both versions — the corpus's and this
library's — because "which two versions disagreed" is the entire content of
the failure. Not ``CorpusError``: that means "cannot be read", and a corpus
this module refuses was read fine; it is the engine that cannot carry it
forward (a future version) or does not yet know how (a gap in the chain). The
CLI wraps the ``ValueError`` in its ``schema_version`` refusal envelope.
"""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

from . import corpus

#: The migration chain: ``_STEPS[n]`` rewrites a version-``n`` corpus
#: directory in place into a version-``n+1`` one, *including* the header's
#: ``schema_version`` field — a step owns its whole delta, so a chain that
#: stops halfway leaves a directory that honestly says which version it
#: reached. Empty until the first bump; ``migrate`` walks it in order.
_STEPS: dict[int, Callable[[Path], None]] = {}


def migrate(
    source: str | Path, destination: str | Path, *, overwrite: bool = False
) -> Path:
    """Copy *source* to *destination*, upgraded to the current schema version.

    At the current version this is the identity migration: a byte-for-byte
    copy. An unknown or future version is refused with both versions named.
    Returns the destination path.
    """
    root = corpus.resolve_corpus(str(source))
    header = corpus.read_json(root / corpus.WORLD_FILE)
    # The same default `World.load` applies: a header without the field is a
    # hand-authored current-version corpus, not an ancient one.
    version = header.get("schema_version", corpus.SCHEMA_VERSION)
    current = corpus.SCHEMA_VERSION

    # `bool` is an `int` to isinstance, and a corpus claiming schema version
    # `true` should be refused as unknown, not silently migrated as 1.
    if isinstance(version, bool) or not isinstance(version, int):
        raise ValueError(
            f"corpus schema version {version!r} is not a version this library"
            f" (schema version {current}) can migrate"
        )
    if version > current:
        # Deliberately echoes `World.load`'s message for the same state: the
        # fix is the same (upgrade worldloom), and two spellings of one
        # failure would make a harness match on both.
        raise ValueError(
            f"corpus schema version {version} is newer than this library"
            f" supports ({current}); upgrade worldloom"
        )
    # One gap check for everything below current — a version 0, a negative
    # version, and a legitimate old version whose step was never written are
    # the same refusal, because to the caller they are the same state: this
    # engine cannot walk that corpus forward.
    missing = [step for step in range(version, current) if step not in _STEPS]
    if missing:
        raise ValueError(
            f"no migration step from schema version {missing[0]}: cannot"
            f" migrate this corpus from schema version {version} to {current}"
        )

    target = Path(destination)
    if target.resolve() == root.resolve():
        # In-place would make `overwrite=True` delete the source before
        # copying it — the exact failure `World.export`'s staging dance exists
        # to survive. Migration has no reason to be in-place (keeping the
        # original readable is the point), so refuse instead of staging.
        raise ValueError(
            f"cannot migrate {root} onto itself; pick a different destination"
        )
    if target.exists():
        # Same posture as `World.export`: a non-empty destination is refused
        # unless asked, and `overwrite=True` replaces the whole directory
        # rather than merging into it — a migrated corpus mixed with a stale
        # one would validate against files neither produced.
        if not overwrite and any(target.iterdir()):
            raise FileExistsError(
                f"{target} is not empty; pass overwrite=True to replace it"
            )
        shutil.rmtree(target)
    shutil.copytree(root, target)
    for step in range(version, current):
        _STEPS[step](target)
    return target
