"""Which process-global tables belong to one corpus, and the leaks that proved it.

`src/worldloom/registries.py` states the measured problem; these are the claims
it makes, each pinned where it could rot.

Three leaks were reproduced before the module was written and each is a test
below. They are worth reading in order, because they are three different
statements about *why* a snapshot list kept in the caller is the wrong shape:

1. **An authored type silences another pack's lint.** `packs.lint` on a pack
   whose LOB names document types nothing declares reports five findings in a
   cold process and none once any pack has installed a type. Nothing about the
   linted pack changed. This is the plain leak — a table written per corpus and
   never unwritten.

2. **`validate` does not put back everything it installed.** Its
   `_pack_registries` docstring asks for exactly the property this module
   provides — "so the snapshot below can never drift from what
   `packs.archetype_of` actually installs" — and the list has already drifted
   past `columns._INSTALLED`. A list written in the consumer cannot have that
   property. Held as a *ratchet* below, because the one-line fix is in a file
   this change does not own.

3. **A restored registry can still be wrong.** `doctypes.install` writes five
   tables it does not own and records what it did in `_INSTALLED`. Restoring
   `_INSTALLED` alone undoes the record and leaves the effect, so
   `doctypes.installed()` reports nothing installed while
   `documents.declared_types()` still holds the types — and re-installing the
   same pack, revised, is refused as "already declared by a module" when no
   module declared it. This is the one that decides the design: a registry is
   not the same object as its effect, so the declaration has to be made by the
   code that writes, not by the code that wants to restore.

The fourth test group is the anti-drift gate, and it needs no list of its own:
it installs a pack inside a scope and requires **every** module-level container
in `documents` and in the Word renderer to come back unchanged. A sixth table
joining `doctypes.install` without joining the declaration fails there, which is
the whole reason the declaration is worth having.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from worldloom import (
    RetailWorld, World, columns, doctypes, documents, packs, registries,
)
from worldloom.render import docx as docx_render
from worldloom.scenarios import MonthEndClose

REPO = pathlib.Path(__file__).resolve().parents[1]
PACKS = REPO / "examples" / "packs"
TRADING = PACKS / "trading-retailer.json"
INSURER = PACKS / "regional-insurer.json"
PERIOD = "2026-03"
SEED = 8128


@pytest.fixture(autouse=True)
def _restore_the_registries():
    """The mechanism, used on itself. A test here installs by design."""
    with registries.scoped():
        yield


# ---------------------------------------------------------------------------
# Fixtures: packs that install something
# ---------------------------------------------------------------------------


#: What this file's copy of `trading-retailer` calls its document types.
#:
#: Renamed rather than reused, and the reason is this file's own subject. The
#: shipped names are installed by other test files that do not clean up, so a
#: fixture using them asserts a different thing depending on what ran first —
#: `test_a_scope_undoes_the_effect_and_not_only_the_record` failed in a full
#: suite and passed alone, which is exactly how the leak announces itself
#: (`worldloom/__init__.py` records the same symptom for `policies`). A test
#: about registry contamination that is order-dependent proves nothing, so the
#: keys here are unique to this file and cannot already be declared.
SUFFIX = "_registry_probe"


def _own_keys(document: dict) -> dict:
    """Every artifact type name in *document*, suffixed so nothing else owns it.

    Rewritten over the serialised text rather than field by field, because the
    names appear in `artifact_types`, in each LOB's responsibilities and in the
    lore's filing asks, and a fixture that renamed two of the three would be
    testing a pack that is internally inconsistent.
    """
    text = json.dumps(document)
    for spec in json.loads(TRADING.read_text(encoding="utf-8"))["artifact_types"]:
        text = text.replace(f'"{spec["key"]}"', f'"{spec["key"]}{SUFFIX}"')
    return json.loads(text)


def _trading() -> dict:
    """`trading-retailer`, under keys only this file uses."""
    return _own_keys(json.loads(TRADING.read_text(encoding="utf-8")))


def _borrower() -> dict:
    """That pack with its own `artifact_types` removed.

    Its LOB still names all five types, so it is exactly the defect `lob.lint`
    exists for — "an edge to a document that will never be planned" — and
    exactly the pack whose findings a leak silences.
    """
    document = _trading()
    document["name"] = "borrower"
    document.pop("artifact_types", None)
    # Dropped so loading this pack installs nothing itself: the test is about
    # what *another* pack's install does to it.
    document.pop("episodes", None)
    return document


def _dangling_edges() -> int:
    return len([
        finding for finding in packs.lint(packs.load(_borrower()))
        if "will never be planned" in finding
    ])


def _typed(authority: str) -> dict:
    """Five authored types, at a chosen authority.

    Two calls with different authorities are the same company revising its own
    pack — the case a leftover table turns into "already declared by a module".

    The episodes and LOBs are dropped because `episodes._LOADED` and
    `lob._INSTALLED` are not declared scoped yet (they are two of the three
    registries this change names as remaining work), so installing them here
    would leave exactly the mess this file is about.
    """
    document = _trading()
    document.pop("episodes", None)
    document.pop("lobs", None)
    for spec in document["artifact_types"]:
        spec["authority"] = authority
    return document


def _sheeted(label: str) -> dict:
    """The shipped insurer, carrying a relabelled P&L under one fixed pack name.

    One pack *name* across both labels on purpose: `columns._INSTALLED` is keyed
    by owner, so only the same owner under different columns can collide, and
    that collision is the whole observable consequence of the sheet outliving
    its world.
    """
    document = json.loads(INSURER.read_text(encoding="utf-8"))
    document["name"] = "acme"
    document["sheets"] = [{
        "name": columns.AUTHORABLE,
        "columns": [
            {
                "key": column.key,
                "label": f"{label} {column.key}",
                "kind": column.kind,
                "unit": getattr(column.unit, "value", column.unit),
                "summable": column.summable,
                **({"derive": {
                    "formula": column.derive.kind.value,
                    "operands": list(column.derive.operands),
                }} if column.derive is not None else {}),
            }
            for column in columns.PNL.columns
        ],
    }]
    return document


# ---------------------------------------------------------------------------
# Leak 1: an authored type silences another pack's lint
# ---------------------------------------------------------------------------


def test_a_packs_lint_does_not_depend_on_what_else_this_process_installed() -> None:
    """Measured before the scope existed: 5 findings, then 0.

    `lob.lint` answers "will anything ever plan this document?" by asking
    `documents.declared_types()`, which is process-global. Build somebody else's
    company and the answer changes for a pack nobody touched — so `worldloom
    pack check` reports a clean bill for an estate whose edges point nowhere.
    """
    cold = _dangling_edges()
    assert cold, "the borrower pack must have dangling artifact-type edges to be a fixture"

    with registries.scoped():
        # The same five type keys, installed by the company that authors them.
        doctypes.install(packs.load(_typed("approved_report")).artifact_types)
        assert _dangling_edges() == 0, (
            "the leak itself: inside the install the findings are gone. If this"
            " ever fails, the fixture has stopped exercising the hazard."
        )

    assert _dangling_edges() == cold


# ---------------------------------------------------------------------------
# Leak 3: the record restored, the effect left behind
# ---------------------------------------------------------------------------


def test_restoring_the_installers_own_registry_is_not_enough() -> None:
    """Why the declaration is made by the writer and not by the restorer.

    This is `validate._under_the_corpus_rules`' restore, reproduced by hand: it
    puts back `doctypes._INSTALLED` and the four `documents` tables that
    `doctypes.install` actually writes are untouched. The two then disagree, and
    the disagreement is not cosmetic — it is a refusal naming a module that
    never declared the type.
    """
    saved = dict(doctypes._INSTALLED)
    doctypes.install(packs.load(_typed("approved_report")).artifact_types)
    doctypes._INSTALLED.clear()
    doctypes._INSTALLED.update(saved)

    # Against the snapshot rather than against empty: other test files install
    # types and leave them, which is the leak this file is about seen from the
    # outside, and a test asserting `not installed()` would be asserting that
    # they had all been fixed.
    assert doctypes.installed() == saved
    leaked = sorted(set(documents.declared_types()) & set(documents._OUTLINES)
                    & {spec["key"] for spec in _typed("approved_report")["artifact_types"]})
    assert leaked, (
        "the record is back and the effect is not — if this ever passes empty,"
        " something has started undoing the tables and this test should become"
        " the assertion that it always does"
    )

    with pytest.raises(ValueError, match="already declared by a module"):
        doctypes.install(packs.load(_typed("unofficial_note")).artifact_types)


def test_a_scope_undoes_the_effect_and_not_only_the_record() -> None:
    """The same sequence under `scoped()`. The revised pack simply installs."""
    before = set(documents.declared_types())
    held = doctypes.installed()

    with registries.scoped():
        doctypes.install(packs.load(_typed("approved_report")).artifact_types)
        assert set(documents.declared_types()) > before

    assert set(documents.declared_types()) == before
    # As it was found, not empty — see `test_restoring_the_installers_own_registry_is_not_enough`.
    assert doctypes.installed() == held

    # The company revises its own pack. Nothing in the process now disagrees.
    with registries.scoped():
        doctypes.install(packs.load(_typed("unofficial_note")).artifact_types)


# ---------------------------------------------------------------------------
# The anti-drift gate: completeness, derived rather than listed
# ---------------------------------------------------------------------------


def _module_containers(module) -> dict[str, object]:
    """Every module-level dict or set on *module*, copied.

    Derived rather than named, which is the point: a sixth table joining
    `doctypes.install` is covered here on the day it is written, and the test
    that catches an undeclared write is not itself a list somebody has to
    remember to update. Private names included — `_OUTLINES` and `_STANDING`
    are exactly the ones at issue.
    """
    return {
        f"{module.__name__}.{name}": (dict(value) if isinstance(value, dict) else set(value))
        for name, value in vars(module).items()
        if type(value) in (dict, set)
    }


def test_a_scope_puts_back_every_table_an_install_touches() -> None:
    """Not "every table we listed" — every table there is, in both modules.

    `doctypes.install` writes five containers across `documents` and the Word
    renderer, and the reason this repository has hit the leak four times is that
    each of those is easy to write and easy to forget to restore. So the gate
    does not consult the declaration at all: it snapshots both modules whole and
    requires the scope to have been complete.
    """
    before = {**_module_containers(documents), **_module_containers(docx_render)}

    with registries.scoped():
        packs.archetype_of(packs.load(_typed("approved_report")))
        during = {**_module_containers(documents), **_module_containers(docx_render)}

    after = {**_module_containers(documents), **_module_containers(docx_render)}

    touched = sorted(name for name in before if before[name] != during[name])
    assert touched, "the fixture must install something for this gate to mean anything"
    assert after == before, (
        "a container this install writes is not declared scoped. It is one"
        f" `registries.declare` beside the write. Left dirty: "
        f"{sorted(name for name in before if before[name] != after[name])}"
    )


# ---------------------------------------------------------------------------
# Leak 2: columns, and the list in `validate` that has already drifted
# ---------------------------------------------------------------------------


def _authored_corpus(tmp_path) -> pathlib.Path:
    """A corpus built from a pack that installs both a doctype and a sheet."""
    with registries.scoped():
        pack = packs.load(_sheeted("v1"))
        world = RetailWorld.from_pack(pack, seed=SEED).build().run(
            MonthEndClose(period=PERIOD)
        ).compile()
        return world.export(tmp_path / "authored", overwrite=True)


def test_a_sheet_does_not_outlive_the_world_that_declared_it(tmp_path) -> None:
    """The refusal is right; its scope was not.

    A second declaration under one owner is refused because `columns.for_world`
    resolves at *compile* time, so replacing the row would compile an
    already-built world with the other one's columns — silently, since a
    relabelled column reconciles against the same facts. What the owner key
    cannot do is stop the row outliving the process's interest in it, and that
    turns a legitimate second build into a crash.
    """
    with registries.scoped():
        packs.archetype_of(packs.load(_sheeted("v1")))
        assert columns.for_archetype("pack:acme").columns[0].label.startswith("v1")
        with pytest.raises(ValueError, match="already installed for"):
            packs.archetype_of(packs.load(_sheeted("v2")))

    assert not columns.installed()
    with registries.scoped():
        packs.archetype_of(packs.load(_sheeted("v2")))
        assert columns.for_archetype("pack:acme").columns[0].label.startswith("v2")


def test_validate_leaves_at_most_the_one_container_it_is_known_to_forget(tmp_path) -> None:
    """A ratchet on `validate`'s own restore, stated behaviourally.

    `validate._under_the_corpus_rules` installs the corpus's own pack and puts
    back "every process-global registry a pack install writes into" — from a
    tuple written in `validate.py`, which its own docstring says must "never
    drift from what `packs.archetype_of` actually installs". It has:
    `columns._INSTALLED` is not in it, so validating a corpus whose pack authors
    a workbook leaves the sheet installed, and the next build of that pack
    revised is refused because something was *validated* earlier.

    A ceiling rather than an equality, `tests/test_reachability.py`'s idiom: the
    known gap is named and nothing new may join it. The fix is one line in a
    file this change does not own —

        return tuple(registries.containers())

    in place of the hand-written tuple — and this test goes to zero on its own
    when that lands, rather than failing the lane that fixes it.

    Asserted over the *containers* rather than over `_pack_registries` itself so
    a rename or a rewrite of that function cannot make the gate vacuous.
    """
    exported = _authored_corpus(tmp_path)

    before = {entry.name: registries._copy(entry.reach()) for entry in registries.declared()}
    report = World.load(exported).validate()
    assert report.ok, report.violations
    after = {entry.name: registries._copy(entry.reach()) for entry in registries.declared()}

    left_dirty = {name for name in before if before[name] != after[name]}
    assert left_dirty <= {"columns._INSTALLED"}, (
        f"`validate` now leaves {sorted(left_dirty)} installed. Every name here"
        " beyond the known one is a new drift between validate.py's tuple and"
        " what packs.archetype_of installs."
    )


# ---------------------------------------------------------------------------
# The declaration seam itself
# ---------------------------------------------------------------------------


def test_every_declaration_names_a_container_and_says_what_a_leak_costs() -> None:
    """`report()` is the reading a person gets instead of grepping for `dict[`."""
    entries = registries.declared()
    assert entries
    for entry in entries:
        assert entry.owner and entry.name and entry.why
        assert isinstance(entry.reach(), (dict, set))
    assert len({entry.name for entry in entries}) == len(entries)
    assert [line.split(" ")[0] for line in registries.report()] == [e.name for e in entries]


def test_redeclaring_the_same_container_is_a_no_op_and_a_different_one_is_refused() -> None:
    """`register_domain_checks`' rule, for its reason.

    A module imported twice must not double its entry, and two modules
    disagreeing about what `documents._OUTLINES` means would make a restore
    depend on import order — which is the determinism bug the whole registration
    contract in this package exists to avoid.
    """
    count = len(registries.declared())
    registries.declare(
        lambda: documents._OUTLINES,
        owner="doctypes", name="documents._OUTLINES", why="unchanged",
    )
    assert len(registries.declared()) == count

    with pytest.raises(ValueError, match="already declared scoped"):
        registries.declare(
            lambda: {}, owner="somebody_else", name="documents._OUTLINES", why="a different table",
        )


def test_a_scope_restores_rather_than_clears() -> None:
    """What the in-process caller is holding on purpose stays held.

    `_under_the_corpus_rules` states the rule: a caller that built a pack world
    before entering the block installed that pack itself, and emptying the
    tables under it would drop a spec it is relying on and silently stop
    checking facts.
    """
    doctypes.install(packs.load(_typed("approved_report")).artifact_types)
    held = doctypes.installed()
    assert held

    with registries.scoped():
        doctypes._INSTALLED.clear()

    assert doctypes.installed() == held


def test_the_declarations_are_the_same_in_every_process() -> None:
    """No import-order dependency, which is what would make this a determinism bug.

    `doctypes` is not imported by `worldloom/__init__`, so a declaration made at
    its import is made only once something has reached it — the exact hazard
    `register_artifact_types` warns about and the reason `policies` and
    `workforce` were pulled into `__init__`. `registries` imports its writers on
    first read instead, so the answer does not depend on what has run.
    """
    import subprocess
    import sys

    program = (
        "import worldloom.registries as r;"
        " print('|'.join(e.name for e in r.declared()))"
    )
    fresh = subprocess.run(
        [sys.executable, "-c", program], check=True, capture_output=True, text=True, cwd=REPO,
    ).stdout.strip()
    assert fresh.split("|") == [entry.name for entry in registries.declared()]
