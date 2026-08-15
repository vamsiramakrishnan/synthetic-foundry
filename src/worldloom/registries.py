"""Which process-global tables belong to one corpus, declared where they are written.

The measured problem
--------------------

This package holds 33 mutable module-level registries across 18 modules. Most
are *registration* registries — a vertical registers its fact kinds, its
document types and its check groups at import, once — and those are fine. Eight
of them are not: they are written **after import, per corpus**, by
``packs.archetype_of``, and never unwritten. The process then carries one
world's configuration into the next world built in the same interpreter.

Three leaks were reproduced before this module was written, and each one says
something different about why a snapshot in the caller is the wrong shape.

**1. An authored type silences another pack's lint.**
``lob.lint`` exists to catch "an edge to a document that will never be planned";
it answers by asking ``documents.declared_types()``. Measured on
``examples/packs/trading-retailer.json`` with its own ``artifact_types``
removed — the exact defect the lint is for::

    packs.lint(borrower)                      → 5 findings
    build --pack trading-retailer.json        (somebody else's company)
    packs.lint(borrower)                      → 0 findings

Nothing about ``borrower`` changed. A pack now passes ``worldloom pack check``
because an unrelated company's paperwork is loaded in the same process.

**2. ``validate`` does not put back what it installed.**
``validate._under_the_corpus_rules`` snapshots "every process-global registry a
pack install writes into" — and that list has already drifted from what
``packs.archetype_of`` actually installs: ``columns._INSTALLED`` is missing from
it. So validating a corpus whose pack authors a workbook leaves the sheet
installed, and the *next* build of that pack, revised, is refused::

    validate ./corpus-built-from-acme-v1
    build --pack acme-v2.json   → ValueError: sheet 'pnl' is already installed
                                  for 'pack:acme' with different columns

A hand-maintained list in one consumer is a list that drifts, and the drift is
silent because the thing it forgets to restore is a thing nobody is looking at.

**3. A restored registry can still be wrong, because a registry is not its
effect.** This is the one that decides the design. ``doctypes.install`` writes
five tables it does not own — ``documents._STANDING``, ``_LAG``, ``_OUTLINES``,
``_FILINGS`` and ``render.docx.HANDLES`` — and records what it did in its own
``_INSTALLED``. Copying ``_INSTALLED`` back therefore undoes the *record* and
leaves the *effect*::

    doctypes.installed()            → 0 types
    documents.declared_types()      → still holds all five of the pack's types
    doctypes.install(same pack, revised)
        → ValueError: artifact type 'trade_pipeline_review' is already declared
          by a module

No module declared it. The registry and the tables it stands for disagree, and
the error names a cause that does not exist.

The mechanism
-------------

**The module that writes a table declares that the table is per-corpus.** Not
the module that owns the table, and emphatically not the module that wants to
restore it. ``documents._OUTLINES`` is a constant as far as ``documents`` is
concerned — populated at import by domain modules and never touched again — and
becomes mutable-per-corpus only because ``doctypes.install`` writes it. So
``doctypes`` is what declares it, beside the code that does the writing, where
a sixth table joining that write is one line away from the declaration instead
of in another module's snapshot list.

That is the same argument ``columns.default`` makes for deriving its resolver
from ``sheets()`` rather than from an import-time table, and the one
``doctypes.audit`` makes for reading ``documents.declared_types()`` rather than
a checked-in snapshot: **a list that has to be remembered is a list that will be
wrong, so derive it from the thing it describes.** Leak 2 above is that argument
with a measurement attached.

``scoped()`` is then a single context manager over everything declared, and it
cannot be partial in the way leaks 2 and 3 are, because completeness is no
longer a property of the caller.

What this deliberately does not do
----------------------------------

**It does not scope a build.** ``packs.archetype_of`` installs for the life of
the process on purpose: a world is built and compiled in two steps, and
``columns.for_world`` resolves the sheet at *compile* time, so a scope that
closed when the build returned would compile the world with the engine's
workbook and report success. ``validate._under_the_corpus_rules`` already
states this boundary — "this undoes what *validation* installed; it does not
undo what a *build* installed" — and this module keeps it rather than moving it.

**It does not thread a registry through ``World``.** That is the mechanism with
no reliance on a caller remembering, and it was rejected on cost: the tables
above are read from ``documents``, ``columns``, ``planning`` and three
renderers, none of which are handed a world, so it is a signature change across
most of the package for a hazard that has exactly two boundaries — a validation
run and a test. Both of those are blocks, and a block is what a context manager
is for.

**It does not offer ``uninstall``.** An explicit inverse has to be paired by
every caller, which is the failure that produced the current state; and it
cannot be written correctly anyway, because ``install`` is idempotent and
refcount-free, so the inverse of two installs is not one uninstall.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, MutableMapping, MutableSet
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any


#: A declared table, and why it is in here rather than being a registration
#: registry like the other 25.
@dataclass(frozen=True)
class Scoped:
    """One process-global container that belongs to a corpus rather than a process."""

    owner: str
    """The module that *writes* it — which is not always the module that owns
    it. See this module's docstring: ``doctypes`` declares five of
    ``documents``' tables, because ``doctypes.install`` is what makes them
    mutable."""

    name: str
    """How to say it in a report: ``"documents._OUTLINES"``."""

    reach: Callable[[], MutableMapping[Any, Any] | MutableSet[Any]]
    """The container, resolved on call.

    A thunk rather than the object, for the reason ``validate._pack_registries``
    imports inside its own body: the writers sit *above* what they write —
    ``doctypes`` reaches ``render.docx``, which imports half the package — and a
    module-level reference here would either close an import cycle or pay for
    the renderer on every ``import worldloom``. It is also the idiom the seven
    hand-rolled test fixtures already used (``lambda: episodes._LOADED``), so
    nothing has to change shape to move onto it.
    """

    why: str
    """What goes wrong if it is not scoped. Printed by ``report()``; the point
    is that a future reader can tell a leak from a registration seam without
    reading the installer."""


#: Every declared container, in declaration order.
#:
#: Order matters only for reporting — restore is per-container and independent —
#: but it is a list rather than a set so ``report()`` is deterministic without
#: sorting a set, which is the ``no set iteration reaching output`` rule.
_DECLARED: list[Scoped] = []


def declare(
    reach: Callable[[], MutableMapping[Any, Any] | MutableSet[Any]],
    *,
    owner: str,
    name: str,
    why: str,
) -> None:
    """Declare that *reach* holds one corpus's configuration, not the process's.

    Called at module import, the same contract every registration seam in this
    package follows (``factkinds.register``, ``validate.register_domain_checks``,
    ``documents.register_artifact_types``) and for the same reason: a scope that
    covered a table only when the right module happened to have been imported
    would restore different things in different processes, which is the
    determinism bug those docstrings all warn about, wearing a scope's clothes.

    Re-declaring the same container under the same name is a no-op, so a module
    imported twice — or reloaded by a test — does not double its entry.
    Declaring a *different* container under a name already taken is refused,
    ``register_domain_checks``' rule and for its reason: two modules disagreeing
    about what ``documents._OUTLINES`` means would make a restore depend on
    import order.
    """
    for existing in _DECLARED:
        if existing.name != name:
            continue
        if existing.reach() is reach():
            return
        raise ValueError(
            f"{name!r} is already declared scoped by {existing.owner!r} over a"
            " different container — a scoped table has one writer that speaks"
            " for it, because two disagreeing declarations would make a restore"
            " depend on import order."
        )
    _DECLARED.append(Scoped(owner=owner, name=name, reach=reach, why=why))


#: The modules whose import performs a declaration.
#:
#: Named here and imported on first read, because a declaration made at the
#: writer is only made once the writer has been imported — and ``doctypes`` is
#: not imported by ``worldloom/__init__.py``. Without this, ``declared()``
#: returns a different answer depending on what has run, which is precisely the
#: hazard ``register_artifact_types`` warns about ("types that exist only when
#: the right module happened to be imported would make ``compile()`` differ
#: between processes") and which ``policies`` and ``workforce`` were each pulled
#: into ``__init__`` to fix.
#:
#: It is a list of *modules* rather than of tables, and that is the difference
#: that matters. A table list drifts because tables are added one at a time by
#: whoever adds a write — the drift measured in ``validate._pack_registries``.
#: A writer module is added once per authored layer, and adding one is already a
#: change to this file.
#:
#: The import is inside a function for ``validate._pack_registries``' reason,
#: verbatim: this module sits *under* the ones that write, so a top-level import
#: would close the cycle.
_WRITERS = ("columns", "doctypes", "episodes", "lob", "validate")


def _ensure_declared() -> None:
    from importlib import import_module

    for module in _WRITERS:
        import_module(f".{module}", __package__)


def declared() -> tuple[Scoped, ...]:
    """Every container declared per-corpus, in declaration order."""
    _ensure_declared()
    return tuple(_DECLARED)


def containers() -> tuple[MutableMapping[Any, Any] | MutableSet[Any], ...]:
    """The declared containers themselves.

    The shape ``validate._pack_registries`` returns, so that function can become
    a call to this one: its own docstring asks for exactly this property — "so
    the snapshot below can never drift from what ``packs.archetype_of`` actually
    installs" — and a list written in the consumer cannot have it. It has
    already drifted; ``columns._INSTALLED`` is not in it.
    """
    return tuple(entry.reach() for entry in declared())


@contextmanager
def scoped() -> Iterator[None]:
    """Install whatever the block installs, and leave the process as it was found.

    Snapshot-and-restore rather than record-and-undo. The two are equivalent
    here and the snapshot is smaller: an installer would have to note every
    write it makes for the recording form to be complete, which is one more
    thing to keep in step with the installer — the property this module exists
    to stop needing. Copying eight small dicts is cheap enough that the
    difference is not worth a second mechanism.

    Restoring rather than clearing, for ``_under_the_corpus_rules``' reason: a
    caller that built a pack world before entering the block is holding that
    pack on purpose, and emptying the tables under it would drop a spec it
    installed itself and silently stop checking facts.

    Nothing in a build path calls this. See the module docstring: a build
    installs for the life of the process deliberately, because the world it
    built is compiled later and has to still find its sheet.
    """
    saved = [(container, _copy(container)) for container in containers()]
    try:
        yield
    finally:
        # Reverse order so a container declared by a module that writes another
        # module's table is put back before the table it stands for — which
        # matters for nothing today and costs nothing, and stops a future
        # declaration whose restore has an ordering from being wrong by
        # default.
        for container, original in reversed(saved):
            container.clear()
            container.update(original)  # type: ignore[arg-type]


def _copy(container: MutableMapping[Any, Any] | MutableSet[Any]) -> Any:
    """A shallow copy that works for both shapes a registry takes here.

    ``dict`` for seven of them and ``set`` for ``render.docx.HANDLES``, and both
    answer ``clear()``/``update()`` the same way — so the restore above needs no
    branch and a ninth container of either shape needs no change.
    """
    return dict(container) if isinstance(container, MutableMapping) else set(container)


def report() -> list[str]:
    """One line per declared container: who writes it, and what a leak costs.

    A reading rather than a check. ``tests/test_registries.py`` holds the claims;
    this is for a person asking "what in this process belongs to the corpus and
    not to me", which before this module had no answer short of grepping for
    ``dict[`` at column zero.
    """
    return [f"{entry.name} (written by {entry.owner}) — {entry.why}" for entry in declared()]


__all__ = ["Scoped", "containers", "declare", "declared", "report", "scoped"]
