"""An industry pack colloquialises the corpus, and a corpus built under one replays without it.

A bank's month-end model has a Branch Performance tab where a retailer's has
Store Performance; a build that names no pack is byte-identical to one made
before packs existed; and the words are recorded on the recipe by value, so the
corpus rebuilds after the pack file is gone.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import corpus, packkit
from worldloom import recipe as recipe_module
from worldloom.cli import app
from worldloom.packkit.active import forget_defaults
from worldloom.retail import MonthEndClose, RetailWorld

runner = CliRunner()


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


def _bank(root: Path, **body: object) -> Path:
    """An industry pack that says branch for site and product line for category."""
    path = root / "industry" / "bank.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "worldloom.pack/v1", "kind": "industry", "name": "bank",
        "body": {"terms": {"site": "branch", "category": "product line"}, **body},
    }))
    return path


def _closed() -> object:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


def _workbook(world) -> object:  # type: ignore[no-untyped-def]
    compiled = world.compile()
    intent = next(i for i in compiled.artifact_intents if i.artifact_type == "finance_workbook")
    return next(ir for ir in compiled.artifact_irs if ir.intent_id == intent.id)


def _labels(ir) -> tuple[set[str], set[str]]:  # type: ignore[no-untyped-def]
    headings = {section.heading for section in ir.sections}
    rows = {row.label for section in ir.sections if section.table for row in section.table.rows}
    return headings, rows


def test_the_default_words_are_the_literals_the_code_held() -> None:
    """Every shipped text equals the string it replaced, so default output cannot move."""
    assert packkit.text("documents.workbook.stores.title") == "Store Performance"
    assert packkit.text("documents.workbook.category.title") == "Category P&L"
    assert packkit.text("documents.workbook.stores.partial_total") == "Total, trading stores"
    assert packkit.text("documents.workbook.group") == "Group"
    assert packkit.text("documents.workbook.title", company="Acme") == "Acme — Month-End Model"
    assert packkit.text("documents.outline.heading.by_business_unit") == "By business unit"
    assert packkit.text("render.servicenow.incident.summary", service="X") == "X failed - month-end close at risk"
    assert packkit.texts("render.jira.control.criterion.")[0] == (
        "A named owner is registered for the mapping in the service catalogue")
    world = _closed()
    headings, rows = _labels(_workbook(world))
    assert {"Business Unit P&L", "Category P&L", "Store Performance"} <= headings
    assert "Group" in rows
    assert recipe_module.PACKS_KEY not in world.recipe


def test_an_industry_pack_speaks_the_workbook_in_its_own_words(tmp_path: Path) -> None:
    _bank(tmp_path)
    with packkit.use("industry:bank", roots=[tmp_path]):
        world = _closed()
        ir = _workbook(world)
    headings, _ = _labels(ir)
    assert "Branch Performance" in headings and "Store Performance" not in headings
    assert "Product line P&L" in headings and "Category P&L" not in headings
    stores = next(s for s in ir.sections if s.table is not None and s.table.key == "stores")
    assert stores.table.note.startswith("Branches decompose the same unit revenue the product lines do")
    # Recorded by value, so the words replay without the file.
    record = world.recipe[recipe_module.PACKS_KEY]
    assert record["industry"]["ref"] == "industry:bank"
    assert record["industry"]["body"]["terms"]["site"] == "branch"


def test_a_loaded_world_keeps_its_words_without_the_pack(tmp_path: Path) -> None:
    """``World.compile`` re-enters the recorded packs: no `use` needed afterwards."""
    _bank(tmp_path)
    with packkit.use("industry:bank", roots=[tmp_path]):
        world = _closed()
    (tmp_path / "industry" / "bank.json").unlink()
    packkit.refresh()
    headings, _ = _labels(_workbook(world))
    assert "Branch Performance" in headings


def test_a_rebuild_needs_no_pack_file(tmp_path: Path) -> None:
    _bank(tmp_path)
    with packkit.use("industry:bank", roots=[tmp_path]):
        world = _closed()
    (tmp_path / "industry" / "bank.json").unlink()
    packkit.refresh()
    rebuilt = recipe_module.rebuild(world.recipe)
    assert rebuilt.recipe == world.recipe
    assert "Branch Performance" in _labels(_workbook(rebuilt))[0]


def test_an_edited_record_is_refused_rather_than_replayed_as_something_else(tmp_path: Path) -> None:
    _bank(tmp_path)
    with packkit.use("industry:bank", roots=[tmp_path]):
        world = _closed()
    edited = json.loads(json.dumps(world.recipe))
    edited[recipe_module.PACKS_KEY]["industry"]["body"]["terms"]["site"] = "office"
    with pytest.raises(recipe_module.RecipeError, match="recorded packs do not load"):
        recipe_module.rebuild(edited)


def test_build_replay_without_the_pack_file_is_byte_identical(tmp_path: Path) -> None:
    roots, first, second = tmp_path / "packs", tmp_path / "first", tmp_path / "second"
    _bank(roots)
    built = runner.invoke(app, [
        "--pack", "industry:bank", "--pack-root", str(roots),
        "build", "--seed", "8128", "--incident", "--narrate", "-f", "markdown", "-f", "jira",
        "--out", str(first),
    ])
    assert built.exit_code == 0, built.output
    assert "Branch Performance" in next(first.rglob("*month-end-model*.md")).read_text()
    (roots / "industry" / "bank.json").unlink()
    packkit.refresh()
    replayed = runner.invoke(app, [
        "build", "--seed", "8128", "--incident", "--replay", str(first), "-f", "markdown", "-f", "jira",
        "--out", str(second),
    ])
    assert replayed.exit_code == 0, replayed.output
    assert corpus.tree_divergence(first, second) is None


def test_a_colloquialised_heading_keeps_its_semantic_role(tmp_path: Path) -> None:
    """The role is decided on the authored heading, never on the words shown.

    The override is chosen to contain a role hint ("decision") the authored
    heading does not: were the role inferred from the displayed text, the memo's
    second section would become a decision section.
    """
    def memo(world):  # type: ignore[no-untyped-def]
        compiled = world.compile()
        intent = next(i for i in compiled.artifact_intents if i.artifact_type == "cfo_variance_memo")
        return next(ir for ir in compiled.artifact_irs if ir.intent_id == intent.id)

    default = memo(_closed())
    _bank(tmp_path, prompts={"documents.outline.heading.by_business_unit": "Decision units, by {{term:site}}"})
    with packkit.use("industry:bank", roots=[tmp_path]):
        spoken = memo(_closed())
    assert [s.semantic_role for s in spoken.sections] == [s.semantic_role for s in default.sections]
    headings = [s.heading for s in spoken.sections]
    assert "Decision units, by branch" in headings and "By business unit" not in headings


def test_the_writer_is_told_the_industry_words_only_under_a_pack(tmp_path: Path) -> None:
    from worldloom.narrative import handshake

    default = handshake.pending(_closed().compile())
    assert all("site" not in request.terminology for request in default)
    _bank(tmp_path)
    with packkit.use("industry:bank", roots=[tmp_path]):
        world = _closed().compile()
    # Outside the `use`: the world's recipe carries the words to the writer.
    requests = handshake.pending(world)
    assert requests and requests[0].terminology["site"] == 'call it "branch"'
    assert requests[0].terminology["category"] == 'call it "product line"'
    assert "group" not in requests[0].terminology


def test_a_ticket_finds_its_assignee_by_role_not_by_title() -> None:
    from worldloom.render.bundles import _seated

    world = _closed()
    held = world._roles["merch_lead"]
    assert _seated(world, "merch_lead", lambda title: False, "nobody") == held
    # A world that carries no role map (a corpus loaded from disk) still finds
    # the title's first holder, which is the same person on a shipped world.
    from dataclasses import replace

    loaded = replace(world, _roles={})
    assert _seated(loaded, "merch_lead", lambda title: title.startswith("Head of Merchandising"), "x") == held
