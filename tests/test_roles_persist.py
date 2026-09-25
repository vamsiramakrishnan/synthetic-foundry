"""A corpus loaded from disk knows who holds each role, and the words a post is called by are data.

The role map (role key to the person holding it) is not written into the
exported world: that would change the bytes of every corpus. It is derived
from the recipe the corpus already carries, so a ticket renders with the same
assignee after a round trip to disk as it did in the building process, even
when a pack renamed the posts and the old job-title search would have found
nobody. The titles themselves are prompts (``roles.title.<engine>.<key>``),
so a pack renames a post without code and a company pack's authored table
still replaces the lot.
"""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from worldloom import packkit
from worldloom.generators import (
    banking_org,
    insurance_org,
    organisation,
    procurement_org,
)
from worldloom.packkit.active import forget_defaults
from worldloom.render.bundles import render_jira
from worldloom.retail import MonthEndClose, RetailWorld
from worldloom.world import World

#: The retail titles the generator held as literals before they became
#: prompts. Pinned here, not read from the prompts pack, so a default build
#: whose people changed title would fail rather than agree with itself.
_RETAIL_TITLES = {
    "ceo": "Group Chief Executive Officer",
    "controller": "Group Financial Controller",
    "merch_lead": "Head of Merchandising Systems",
    "platform_engineer": "Data Platform Engineer",
}


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    forget_defaults()
    yield
    packkit.refresh()
    forget_defaults()


def _renamed(root: Path) -> Path:
    """An industry pack that calls two ticket assignees' posts something else."""
    path = root / "industry" / "renamed.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "schema": "worldloom.pack/v1", "kind": "industry", "name": "renamed",
        "body": {"prompts": {
            "roles.title.retail.merch_lead": "Head of Product Data",
            "roles.title.retail.platform_engineer": "Pipeline Developer",
            "roles.title.retail.per_unit.bp": "Finance Partner for {unit}",
        }},
    }))
    return path


def _closed() -> World:
    return RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )


def _assignees(world: World) -> dict[str, str]:
    issues = next(r for r in render_jira(world) if r.path == "jira/issues.jsonl")
    return {row["key"]: row["assignee"] for row in map(json.loads, issues.text.splitlines())}


def test_a_loaded_corpus_holds_the_role_map_its_builder_held(tmp_path: Path) -> None:
    world = _closed()
    loaded = World.load(world.export(tmp_path / "corpus"))
    assert loaded._roles == {}, "the map is derived, never written"
    assert "roles" not in json.loads((tmp_path / "corpus" / "world.json").read_text())
    assert loaded.role_holders() == world._roles


def test_a_ticket_keeps_its_assignee_through_disk_under_renamed_titles(tmp_path: Path) -> None:
    _renamed(tmp_path)
    with packkit.use("industry:renamed", roots=[tmp_path]):
        world = _closed()
        in_memory = _assignees(world)
    held = world._roles
    assert world.people.by_id(held["merch_lead"]).title == "Head of Product Data"
    assert world.people.by_id(held["platform_engineer"]).title == "Pipeline Developer"
    assert in_memory == {"PLAT-1": held["platform_engineer"], "PLAT-2": held["merch_lead"]}

    # Outside the `use`: the loaded corpus replays the pack from its recipe.
    loaded = World.load(world.export(tmp_path / "corpus"))
    assert _assignees(loaded) == in_memory
    # What the title search alone would have said: nobody, so the author.
    blind = replace(loaded, _recipe={})
    assert blind.role_holders() == {}
    author = next(i.author_id for i in loaded.artifact_intents if i.artifact_type == "jira_issues")
    assert set(_assignees(blind).values()) == {author}


def test_a_recipe_that_does_not_rebuild_these_people_gives_no_map(tmp_path: Path) -> None:
    """A map from a neighbouring world would assign a ticket to a stranger."""
    world = _closed()
    loaded = World.load(world.export(tmp_path / "corpus"))
    edited = replace(loaded, _people=tuple(
        person.model_copy(update={"title": "Somebody Else"}) if person.id == world._roles["merch_lead"]
        else person
        for person in loaded._people
    ))
    assert edited.role_holders() == {}


def test_a_corpus_with_no_recipe_keeps_the_title_fallback() -> None:
    fixture = World.load("retail-close")
    assert fixture.recipe == {}
    assert fixture.role_holders() == {}


def test_default_titles_are_the_literals_the_generator_held() -> None:
    table = {row[0]: row[1] for row in organisation._ROLES}
    assert {key: table[key] for key in _RETAIL_TITLES} == _RETAIL_TITLES
    assert [spec.title for spec in organisation._UNIT_ROLES] == [
        "Managing Director, {unit}", "Finance Business Partner, {unit}", "Head of Buying, {unit}",
    ]
    for module in (banking_org, insurance_org, procurement_org):
        assert [spec.title for spec in module._UNIT_ROLES] == ["Managing Director, {unit}"]
    assert dict((row[0], row[1]) for row in banking_org._ROLES)["cro"] == "Chief Risk Officer"


def test_every_engine_title_is_a_prompt() -> None:
    for engine, module in (("retail", organisation), ("banking", banking_org),
                           ("insurance", insurance_org), ("procurement", procurement_org)):
        for key, title, _function, _manager in module._ROLES:
            assert packkit.text(f"roles.title.{engine}.{key}") == title
        for spec in module._UNIT_ROLES:
            assert packkit.template(f"roles.title.{engine}.per_unit.{spec.suffix.lstrip('_')}") == spec.title


def test_a_pack_renames_a_post_without_moving_its_cost_centre(tmp_path: Path) -> None:
    default = RetailWorld(seed=8128).build()
    _renamed(tmp_path)
    with packkit.use("industry:renamed", roots=[tmp_path]):
        renamed = RetailWorld(seed=8128).build()
    engineer = default._roles["platform_engineer"]
    assert renamed._roles == default._roles
    assert renamed.people.by_id(engineer).cost_centre_id == default.people.by_id(engineer).cost_centre_id
    bp = [p.title for p in renamed.people if p.title.startswith("Finance Partner for ")]
    assert len(bp) == len(default.business_units)


def test_a_company_packs_table_still_wins_over_the_prompts() -> None:
    """An authored role table replaces the engine's, titles included, as it always did."""
    rows = tuple(
        (key, "Custom " + title if key == "cfo" else title, function, manager)
        for key, title, function, manager in organisation._ROLES
    )
    world = replace(RetailWorld(seed=8128), role_table=rows).build()
    assert world.people.by_id(world._roles["cfo"]).title == "Custom Group Chief Financial Officer"
