"""A mosaic that produces corpora rather than plans.

`mosaic` stopped at `build`. Fifteen artifacts were compiled per world and
three of them carried a retrievable passage; the rest were sections awaiting
prose, so a third of every world's evaluation cases cited evidence that was in
no passage at all. `evaluate.score` reports that honestly now
(`Outcome.reachable`), which is what turned an invisible defect into a
measurable one — and the tests below are written against the *measurement*
rather than against a passage count, because "the corpus is finished" and "the
corpus is easy" are the two readings that were confusable and only the scorer
can tell them apart.

Two properties carry most of the weight here:

* **Reachability collapses to zero.** Not "more passages" — every case being
  answerable by a perfect retriever is the whole claim, and it is the one a
  count of passages cannot make.
* **Nothing about narrating a mosaic is less deterministic than building one.**
  Two runs are byte-identical, a narrated world replays from its own ledger
  with the provider never asked, and — the property a shared provider makes
  worth stating — world 5 does not depend on world 1 having been built.
"""

from __future__ import annotations

import filecmp
import json
import subprocess
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import World, recipe
from worldloom.cli import app
from worldloom.evaluate.across import load, survey
from worldloom.evaluate.index import passages
from worldloom.narrative import DeterministicProvider, UnreachableProvider

runner = CliRunner()

#: Two worlds, which is the smallest mosaic `across.load` will read. Every test
#: below is about what one world contains or about what two of them share, so a
#: larger field would buy nothing but seconds.
COUNT = "2"


def _mosaic(out: Path, *args: str) -> None:
    result = runner.invoke(app, ["mosaic", "-n", COUNT, "-o", str(out), *args])
    assert result.exit_code == 0, result.output


@pytest.fixture(scope="module")
def finished(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    out = tmp_path_factory.mktemp("finished")
    _mosaic(out, "--incident")
    return out


@pytest.fixture(scope="module")
def plans(tmp_path_factory) -> Path:  # type: ignore[no-untyped-def]
    """The same mosaic with `--no-narrate` — what this command used to write."""
    out = tmp_path_factory.mktemp("plans")
    _mosaic(out, "--incident", "--no-narrate")
    return out


# ---------------------------------------------------------------------------
# The claim
# ---------------------------------------------------------------------------


def test_a_plan_only_mosaic_asks_questions_no_passage_can_answer(plans: Path) -> None:
    """The baseline this exists to fix, asserted rather than remembered.

    Pinned as "some, and they are concentrated in the families that need a
    written document" rather than as an exact count, because the number moves
    whenever the artifact planner does — but a family whose every case is
    unanswerable in every world is the shape of the defect and not a threshold.
    """
    reading = survey(plans)
    cards = reading.transfers["bm25"].cards
    assert sum(card.unreachable for card in cards.values()) > 0
    blocked = {
        family
        for card in cards.values()
        for family in card.unreachable_by_type()
    }
    assert blocked, "a plan-only mosaic should carry unanswerable cases"


def test_narrating_makes_every_case_reachable(finished: Path) -> None:
    """The deliverable. Not "more passages" — *answerable*: a case is reachable
    when some passage in the pool carries the facts it expects, which is the
    only statement that separates a corpus that is finished from one that is
    easy. Both retrievers, because reachability is a property of the corpus and
    a ranker that changed it would mean the property was mis-defined."""
    reading = survey(finished, retrievers=("bm25", "tfidf"))
    for name, moved in reading.transfers.items():
        assert sum(card.unreachable for card in moved.cards.values()) == 0, name


def test_the_prose_is_where_the_passages_come_from(finished: Path, plans: Path) -> None:
    """Sanity beneath the reachability claim: the sections really were written.

    Compared world-for-world rather than in total, so a mosaic that finished one
    world and abandoned the rest could not pass.
    """
    for done, planned in zip(load(finished), load(plans), strict=True):
        assert len(list(passages(done.world))) > len(list(passages(planned.world)))


def test_the_duplicate_detection_loop_finally_has_something_to_read(
    finished: Path, plans: Path
) -> None:
    """The similarity join and every near-duplicate reading work over
    passages, and a plan-only world has almost none — so they reported a clean
    corpus by having nothing to look at, which is the least useful way to pass."""
    from worldloom.stats import near_duplicate_clusters

    pool = [p for entry in load(plans) for p in passages(entry.world)]
    finished_pool = [p for entry in load(finished) for p in passages(entry.world)]
    assert len(finished_pool) > 3 * len(pool)
    # The interesting duplication is *between* worlds and only exists once
    # there is prose: `DeterministicProvider` composes from templates keyed on
    # fact kind, so the same section of the same document reads the same in
    # every world of the mosaic.
    assert len(near_duplicate_clusters(finished_pool)) > len(near_duplicate_clusters(pool))


# ---------------------------------------------------------------------------
# What is on by default, and what is not
# ---------------------------------------------------------------------------


def test_describe_still_builds_nothing(tmp_path: Path) -> None:
    """The one thing narration by default must not touch. `--describe` is the
    call a user makes to decide whether five worlds are worth the wait, and a
    version of it that generated five worlds would answer the question by
    doing the thing the question was about."""
    out = tmp_path / "nothing"
    result = runner.invoke(app, ["mosaic", "-n", COUNT, "--describe", "-o", str(out)])
    assert result.exit_code == 0, result.output
    assert not out.exists()


def test_rendering_is_asked_for_separately(finished: Path, tmp_path: Path) -> None:
    """Prose and files are different requests, and only the first is a
    correctness question.

    `evaluate.index.passages` reads the IR, never the rendered bytes, so the
    default mosaic carries no file an author can open and is still fully
    measurable — which is the whole argument for `-f` being its own flag rather
    than riding on `--narrate`.
    """
    assert not list((finished / "world-01").rglob("*.md"))
    assert sum(card.unreachable for card in survey(finished).transfers["bm25"].cards.values()) == 0

    rendered = tmp_path / "rendered"
    _mosaic(rendered, "--incident", "-f", "markdown")
    assert list((rendered / "world-01").rglob("*.md"))


def test_the_plan_records_whether_it_was_narrated(finished: Path, plans: Path) -> None:
    """So a reader of the directory — `evaluate.across.load` above all — never
    has to infer from a passage count whether a thin corpus is an easy one or
    an unfinished one."""
    assert json.loads((finished / "mosaic.json").read_text())["narrated"] is True
    assert json.loads((plans / "mosaic.json").read_text())["narrated"] is False


def test_a_plan_only_mosaic_says_what_it_is(tmp_path: Path) -> None:
    """`--no-narrate` is a legitimate request and is not refused. What is
    refused is letting the directory be scored by somebody who did not type the
    flag, so the warning names the command that would misread it."""
    out = tmp_path / "quiet"
    result = runner.invoke(app, ["mosaic", "-n", COUNT, "-o", str(out), "--no-narrate"])
    assert result.exit_code == 0, result.output
    assert "awaiting prose" in result.output
    assert "difficulty" in result.output


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_two_runs_of_one_mosaic_are_byte_identical(tmp_path: Path) -> None:
    first, second = tmp_path / "a", tmp_path / "b"
    _mosaic(first, "--incident")
    _mosaic(second, "--incident")
    assert not subprocess.run(
        ["diff", "-r", str(first), str(second)], capture_output=True
    ).returncode


def test_one_provider_across_the_mosaic_writes_what_fresh_ones_would(
    finished: Path, tmp_path: Path
) -> None:
    """The command narrates every world through a single provider instance.

    That is safe because `DeterministicProvider` holds nothing between calls
    but a counter — but "safe because I read it" is not the standard here, and
    the failure it would cause is the one a mosaic must never have: world 5
    depending on worlds 1-4 having been built. So narrate each world on its own
    fresh provider and diff the bytes.
    """
    for index, entry in enumerate(load(finished), start=1):
        alone = recipe.rebuild(entry.world.recipe).narrate(DeterministicProvider(), ledger=())
        target = tmp_path / f"alone-{index:02d}"
        alone.export(target, overwrite=True)
        _same(Path(finished / f"world-{index:02d}"), target)


def test_a_narrated_world_still_rebuilds_from_its_own_recipe(
    finished: Path, tmp_path: Path
) -> None:
    """The recipe records how the world was made and the ledger records what
    was answered, so the pair reproduces a *narrated* corpus exactly.

    `UnreachableProvider` rather than a second `DeterministicProvider`, and the
    distinction is the point: a replay that quietly fell back to generating
    would pass this test while proving nothing about the ledger. The provider
    raises if it is ever asked, so `provider_calls == 0` is a fact rather than
    a hope.
    """
    for index, entry in enumerate(load(finished), start=1):
        narrated_by = {
            ir.metadata["narrated_by"]
            for ir in entry.world.artifact_irs
            if "narrated_by" in ir.metadata
        }
        assert len(narrated_by) == 1, narrated_by
        again = recipe.rebuild(entry.world.recipe, ledger=entry.world._ledger).narrate(
            UnreachableProvider(id=narrated_by.pop()), ledger=entry.world._ledger
        )
        calls, replayed, rejected = again._narration
        assert (calls, rejected) == (0, 0) and replayed > 0
        target = tmp_path / f"replayed-{index:02d}"
        again.export(target, overwrite=True)
        _same(Path(finished / f"world-{index:02d}"), target)


def _same(first: Path, second: Path) -> None:
    """Two exported corpora, file by file.

    Through `filecmp` on the written bytes rather than by comparing `World`
    objects, because the recipe and the ledger are JSON on disk and a float
    where the first pass wrote an int is a different corpus by the only measure
    CI applies.
    """
    files = sorted(p.name for p in first.iterdir() if p.is_file())
    assert files == sorted(p.name for p in second.iterdir() if p.is_file())
    match, mismatch, errors = filecmp.cmpfiles(first, second, files, shallow=False)
    assert not mismatch and not errors, f"{mismatch} differ, {errors} unreadable"


def test_the_worlds_a_narrated_mosaic_writes_are_still_the_planned_ones(
    finished: Path,
) -> None:
    """Narration must not move a headcount, a span or a calendar. The plan is
    written from the variants and the corpora are built from the same ones, so
    a mosaic whose prose changed its shapes would disagree with its own
    `mosaic.json` — which is the file `pack export --world` re-derives from."""
    from worldloom import mosaic as mosaic_module

    plan = json.loads((finished / "mosaic.json").read_text())
    assert plan["worlds"] == [v.as_dict() for v in mosaic_module.field(int(COUNT))]
    for entry, variant in zip(load(finished), mosaic_module.field(int(COUNT)), strict=True):
        assert len(entry.world.people) >= variant.headcount - 1


def test_a_narrated_world_carries_the_ledger_that_wrote_it(finished: Path) -> None:
    """A corpus whose prose arrived without a ledger entry could not be
    replayed and could not be audited — the two things a Worldloom corpus is
    for. Asserted per world rather than in total: a mosaic that recorded the
    first world's calls and dropped the rest would still have a non-empty
    ledger."""
    for entry in load(finished):
        assert entry.world._ledger
        world = World.load(str(finished / entry.name))
        assert world._ledger, entry.name
