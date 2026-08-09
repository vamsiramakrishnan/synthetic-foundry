"""The corpus as a drive somebody could actually be pointed at.

A corpus exports to one flat `artifacts/` folder of numbered files with
identical permissions — 293 of them on the largest build measured. That is right
for the harness, which reads the manifest and never looks at a path, and wrong
for what the corpus is for: an enterprise assistant indexes the folder, the
title, the owner and the sharing, and permission behaviour is where those
products most often fail interestingly.

Five properties. That the tree is **derived**, never invented. That a filename
**identifies** its document out of context. That the **live** version of a
revised document keeps the obvious name. That the permission table is **usable**
— addresses, not internal ids. And that laying a corpus out **moves nothing** in
it.
"""

from __future__ import annotations

import json

import pytest

from worldloom import RetailWorld, workspace
from worldloom.narrative import DeterministicProvider
from worldloom.scenarios import MonthEndClose

PERIOD = "2026-03"


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):  # type: ignore[no-untyped-def]
    """Two periods and a policy set, exported and rendered.

    Two rather than one because the properties worth checking are all about
    *telling documents apart* — two Marches of the same pack, a live policy
    beside its superseded version — and a one-period corpus has no pairs in it.
    """
    root = tmp_path_factory.mktemp("corpus")
    world = RetailWorld(seed=8128, policies="core").build()
    for stamp in (PERIOD, "2026-04"):
        world = world.run(MonthEndClose(period=stamp, include_operational_incident=True))
    world = world.compile().narrate(DeterministicProvider()).render("markdown")
    world.export(root / "corpus")
    from worldloom import World

    return World.load(root / "corpus")


# ---------------------------------------------------------------------------
# 1. Derived, never invented
# ---------------------------------------------------------------------------


def test_every_file_lands_on_a_shelf_somebody_would_look_on(rendered) -> None:  # type: ignore[no-untyped-def]
    """Grouped by the function that owns the paperwork, not by the engine that
    generated it. A reader looking for the expense policy looks in Policies."""
    placed = {p.artifact_id: p for p in workspace.layout(rendered)}
    by_type = {a.id: a.artifact_type for a in rendered.artifacts}
    for artifact_id, entry in placed.items():
        shelf = entry.path.rpartition("/")[0]
        assert shelf, f"{by_type[artifact_id]} landed at the root"
    folders = {p.path.rpartition("/")[0] for p in placed.values()}
    assert any(f.startswith("Policies") for f in folders)
    assert any(f.startswith("Finance/Close") for f in folders)
    assert any(f.startswith("Technology") for f in folders)


def test_a_periodic_document_is_filed_under_its_period_and_a_policy_is_not(rendered) -> None:  # type: ignore[no-untyped-def]
    """A close pack lives in a month's folder because there is one per month.
    A policy lives at the top of its shelf because there is one of it and it is
    current until it is not — filing it under a month would say it expired with
    the month."""
    placed = {p.artifact_id: p for p in workspace.layout(rendered)}
    by_type = {a.id: a.artifact_type for a in rendered.artifacts}

    memos = [p for i, p in placed.items() if by_type[i] == "cfo_variance_memo"]
    assert len(memos) == 2, "two periods, two memos"
    assert {p.path.rpartition("/")[0] for p in memos} == {
        f"Finance/Close/{PERIOD}", "Finance/Close/2026-04",
    }

    policies = [p for i, p in placed.items() if by_type[i].endswith("_policy")]
    assert policies
    for entry in policies:
        assert entry.path.rpartition("/")[0] == "Policies", entry.path


def test_the_tree_is_not_flat(rendered) -> None:
    reading = workspace.summarise(rendered)
    assert reading["folders"] > 5
    assert reading["deepest"] >= 3


# ---------------------------------------------------------------------------
# 2. A filename identifies its document out of context
# ---------------------------------------------------------------------------


def test_two_periods_of_one_pack_are_told_apart_by_name(rendered) -> None:  # type: ignore[no-untyped-def]
    """A file lifted out of its folder — attached to an email, dropped in a
    chat — has to stay identifiable. That is the commonest way a real document
    loses its context."""
    placed = {p.artifact_id: p for p in workspace.layout(rendered)}
    by_type = {a.id: a.artifact_type for a in rendered.artifacts}
    names = sorted(
        p.path.rpartition("/")[2] for i, p in placed.items()
        if by_type[i] == "cfo_variance_memo"
    )
    assert len(set(names)) == 2, names
    assert all(PERIOD in n or "2026-04" in n for n in names)


def test_documents_about_a_person_or_a_division_are_named_for_them(rendered) -> None:  # type: ignore[no-untyped-def]
    """A drive full of `(2)` through `(5)` is a drive nobody can search, and the
    corpus knows the answer: those documents are about named subjects."""
    placed = {p.artifact_id: p for p in workspace.layout(rendered)}
    by_type = {a.id: a.artifact_type for a in rendered.artifacts}
    units = {u.name for u in rendered.business_units}
    commentary = [p for i, p in placed.items() if by_type[i] == "unit_close_commentary"]
    assert commentary
    for entry in commentary:
        assert any(unit in entry.title for unit in units), entry.title


def test_no_filename_is_a_sentence(rendered) -> None:
    """An artifact's title is whatever the compiler put there, and for a
    communications bundle that is the whole event summary. No person names a
    file that."""
    for entry in workspace.layout(rendered):
        name = entry.path.rpartition("/")[2]
        assert len(name) <= 110, name
        assert "\n" not in name and "/" not in name.replace("/", "", 0)


# ---------------------------------------------------------------------------
# 3. The live version keeps the obvious name
# ---------------------------------------------------------------------------


def test_a_superseded_document_is_marked_and_does_not_take_the_clean_name(rendered) -> None:  # type: ignore[no-untyped-def]
    """It was applied after names were claimed and the marker arrived too late:
    the superseded expense policy took `Expense Policy.md` and the current one
    landed as `Expense Policy (2).md`. Exactly backwards, and exactly the
    mistake a reader would act on."""
    entries = workspace.layout(rendered)
    marked = [e for e in entries if "(superseded)" in e.path]
    assert marked, "the fixture asked for policies and none of them was revised"
    for entry in marked:
        successor = next(e for e in entries if e.path == entry.superseded_by)
        assert "(superseded)" not in successor.path
        assert "(2)" not in successor.path
        assert successor.path.rpartition("/")[0] == entry.path.rpartition("/")[0], \
            "both versions belong on one shelf or the pair is not legible"


def test_a_republished_periodic_document_is_not_marked_retired(rendered) -> None:  # type: ignore[no-untyped-def]
    """A monthly close calendar supersedes last month's, which is the ordinary
    life of a periodic document rather than a retirement. Marking it would put
    "(superseded)" on five calendars in six and teach a reader to ignore the
    word — so the marker is for a revision *in place*, and the edge is recorded
    either way."""
    entries = {e.artifact_id: e for e in workspace.layout(rendered)}
    by_type = {a.id: a.artifact_type for a in rendered.artifacts}
    calendars = [e for i, e in entries.items() if by_type[i] == "close_calendar"]
    assert len(calendars) == 2
    assert not any("(superseded)" in e.path for e in calendars)
    assert any(e.superseded_by for e in calendars), "the edge is still recorded"


# ---------------------------------------------------------------------------
# 4. The permission table is usable
# ---------------------------------------------------------------------------


def test_readers_are_addresses_and_the_owner_is_among_them(rendered) -> None:  # type: ignore[no-untyped-def]
    """An access list is expressed in addresses everywhere this corpus would be
    loaded, and a document whose own owner is not on its list is one nobody
    could have written."""
    for entry in workspace.layout(rendered):
        assert "@" in entry.owner, entry.path
        if entry.readers:
            assert entry.owner in entry.readers, entry.path


def test_an_unrestricted_policy_lists_nobody_rather_than_everybody(rendered) -> None:  # type: ignore[no-untyped-def]
    """Writing four hundred addresses to say "everyone" is a worse answer than
    the empty list a real ACL uses for "inherit from the drive"."""
    entries = workspace.layout(rendered)
    open_ones = [e for e in entries if e.policy == "All staff"]
    assert open_ones
    assert all(not e.readers for e in open_ones)
    assert any(e.readers for e in entries), "nothing is restricted; the ACL says nothing"


def test_the_permission_table_lands_beside_the_tree(rendered, tmp_path) -> None:  # type: ignore[no-untyped-def]
    root = workspace.write(rendered, tmp_path / "drive")
    rows = [json.loads(line) for line in (root / "permissions.jsonl").read_text().splitlines()]
    assert rows
    for row in rows:
        assert (root / row["path"]).is_file(), row["path"]
        assert row["owner"] and "@" in row["owner"]
    # A row for a file that is not there is a lie a connector would trip on.
    on_disk = {
        str(p.relative_to(root)) for p in root.rglob("*")
        if p.is_file() and p.name != "permissions.jsonl"
    }
    assert {row["path"] for row in rows} == on_disk


def test_two_people_of_one_name_get_two_addresses() -> None:
    """`jordan.lee` then `jordan.lee2`, which is what a mail administrator does
    — and stable, because the roster order is."""
    from types import SimpleNamespace

    roster = [SimpleNamespace(id=f"PERSON-{i}", name="Jordan Lee") for i in range(3)]
    got = workspace._addresses(roster, "example.test")
    assert len(set(got.values())) == 3
    assert got["PERSON-0"] == "jordan.lee@example.test"


# ---------------------------------------------------------------------------
# 5. Laying a corpus out moves nothing in it
# ---------------------------------------------------------------------------


def test_the_corpus_is_untouched(rendered, tmp_path) -> None:  # type: ignore[no-untyped-def]
    before = sorted(
        (str(p.relative_to(rendered.root)), p.stat().st_size)
        for p in rendered.root.rglob("*") if p.is_file()
    )
    workspace.write(rendered, tmp_path / "drive2")
    after = sorted(
        (str(p.relative_to(rendered.root)), p.stat().st_size)
        for p in rendered.root.rglob("*") if p.is_file()
    )
    assert before == after


def test_an_unrendered_corpus_is_refused_by_name(tmp_path) -> None:
    """A workspace of empty folders would look like a corpus that had been
    indexed, which is worse than an error."""
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period=PERIOD)).compile()
    world.export(tmp_path / "plan")
    from worldloom import World

    with pytest.raises(ValueError, match="render"):
        workspace.write(World.load(tmp_path / "plan"), tmp_path / "drive3")


def test_the_layout_is_the_same_every_time(rendered) -> None:
    assert workspace.layout(rendered) == workspace.layout(rendered)
