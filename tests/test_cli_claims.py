"""The CLI surface for the six capabilities that had none.

`facets`, `locales`, `messiness`, `timeline`, `landscape` and `pack_export` all
shipped as libraries with no command able to reach them. This file covers the
flags and subcommands that reach them, and it is deliberately weighted towards
the two properties the modules themselves cannot check from inside:

* **Every flag rides the recipe.** A corpus built with a locale, a messiness
  profile, a facet set or a sampled history must rebuild *byte-for-byte* from
  its own recipe with none of those flags on the command line. That is the
  product's central promise and the one thing a new build flag can silently
  break, so it is asserted per flag rather than once.
* **Every default is a no-op.** A key that appears unconditionally puts a new
  field in every recipe ever written for a value that changes nothing. Each
  flag is therefore also checked *absent*, against the recipe a plain build
  writes.

The exports go through `World.export` and a file diff rather than comparing
objects, because the recipe is JSON on disk and a float where the first pass
wrote an int is a different corpus by the only measure CI applies.
"""

from __future__ import annotations

import filecmp
import json
from pathlib import Path

from typer.testing import CliRunner

from worldloom import World, recipe
from worldloom.cli import app

runner = CliRunner()


def _build(tmp_path: Path, *args: str, name: str = "corpus") -> World:
    out = tmp_path / name
    result = runner.invoke(app, ["build", "--out", str(out), *args])
    assert result.exit_code == 0, result.output
    return World.load(str(out))


def _replays(built: World, tmp_path: Path, label: str) -> None:
    """The corpus and its own rebuild, exported and diffed file by file."""
    again = recipe.rebuild(built.recipe)
    first, second = tmp_path / f"{label}-a", tmp_path / f"{label}-b"
    built.export(first, overwrite=True)
    again.compile().export(second, overwrite=True)
    files = sorted(p.name for p in first.iterdir())
    assert files == sorted(p.name for p in second.iterdir())
    _match, mismatch, errors = filecmp.cmpfiles(first, second, files, shallow=False)
    assert not mismatch and not errors, f"{label}: {mismatch} differ, {errors} unreadable"


# ---------------------------------------------------------------------------
# --facet
# ---------------------------------------------------------------------------


def test_a_facet_mints_the_roles_the_claim_requires(tmp_path: Path) -> None:
    """An audit committee chair is what "listed" means operationally.

    A build that recorded the claim and did not mint the role would be the
    carried-cited-and-inert failure `packs.lint` exists to catch one layer down,
    which is precisely the failure a facet layer is most likely to reintroduce.
    """
    plain = _build(tmp_path, "--seed", "8128", name="plain")
    listed = _build(tmp_path, "--seed", "8128", "--facet", "listing=listed", name="listed")

    titles = {person.title for person in listed.people}
    assert "Chair, Audit and Risk Committee" in titles
    assert "Head of Investor Relations" in titles
    assert len(listed.people) == len(plain.people) + 2


def test_a_facets_consequences_ride_the_recipe_and_its_name_does_not(tmp_path: Path) -> None:
    """The recipe records what the claim *did*, never the claim.

    Consequences replay this world byte-for-byte after the facet registry moves
    under it; a stored `listing=listed` would replay whatever `listed` came to
    mean later while reporting success — the one failure a recipe exists to make
    impossible.
    """
    built = _build(tmp_path, "--seed", "8128", "--facet", "listing=mutual",
                   "--facet", "maturity=legacy")
    assert "facets" not in built.recipe and "facet" not in built.recipe
    assert built.recipe["estate"] == "large"          # legacy implies one
    assert "retail.margin.budget" in built.recipe["physics"]   # mutual implies one
    assert built.recipe["seasonality"]                # trading_pattern's default
    _replays(built, tmp_path, "facets")


def test_an_implied_role_reaches_the_recipes_role_table(tmp_path: Path) -> None:
    built = _build(tmp_path, "--seed", "8128", "--facet", "listing=listed")
    assert "audit_chair" in {row[0] for row in built.recipe["role_table"]}


def test_an_explicit_estate_beats_a_facets(tmp_path: Path) -> None:
    """You said it; the facet only implied it."""
    built = _build(tmp_path, "--seed", "8128", "--estate", "small",
                   "--facet", "scale=multinational")
    assert built.recipe["estate"] == "small"


def test_contradictory_claims_are_refused_with_the_arithmetic() -> None:
    """A mutual runs 16-26% margin and a premium brand 48-62%, and no company is
    both. "These conflict" is unactionable; the two intervals are not."""
    result = runner.invoke(app, ["build", "--facet", "listing=mutual",
                                 "--facet", "margin_profile=premium"])
    assert result.exit_code == 2
    assert "no_overlap" in result.output
    assert "retail.margin.budget" in result.output


def test_one_dimension_given_twice_is_refused_rather_than_last_wins() -> None:
    result = runner.invoke(app, ["build", "--facet", "listing=listed",
                                 "--facet", "listing=mutual"])
    assert result.exit_code == 2
    assert "twice" in result.output


def test_a_malformed_facet_is_refused_rather_than_ignored() -> None:
    result = runner.invoke(app, ["build", "--facet", "listed"])
    assert result.exit_code == 2
    assert "name=value" in result.output


def test_an_unknown_facet_value_is_refused() -> None:
    result = runner.invoke(app, ["build", "--facet", "listing=floated"])
    assert result.exit_code == 2


def test_a_consequence_a_builder_cannot_carry_is_reported_not_fatal(tmp_path: Path) -> None:
    """`BankingWorld` has no `seasonality` field, and every facet set settles
    `trading_pattern` at its default — so refusing the whole set would make
    `--facet` unusable on two of the three engines over a claim nobody typed."""
    out = tmp_path / "bank"
    result = runner.invoke(app, ["build", "--out", str(out), "--seed", "8128",
                                 "--archetype", "midsize_adi", "--facet", "listing=listed"])
    assert result.exit_code == 0, result.output
    assert "unmet" in result.output
    assert "Chair, Audit and Risk Committee" in {p.title for p in World.load(str(out)).people}


# ---------------------------------------------------------------------------
# --locale
# ---------------------------------------------------------------------------


def test_a_locale_rides_the_recipe_and_replays(tmp_path: Path) -> None:
    built = _build(tmp_path, "--seed", "8128", "--locale", "germany")
    assert built.recipe[recipe.LOCALE_KEY] == "germany"
    assert recipe.locale_of(built.recipe).currency == "EUR"
    _replays(built, tmp_path, "locale")


def test_an_unknown_locale_is_refused_never_defaulted() -> None:
    """A corpus that fell back to the engine's would render a Frankfurt
    company's memo in Australian punctuation and report success."""
    result = runner.invoke(app, ["build", "--locale", "germay"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# --messiness
# ---------------------------------------------------------------------------


def test_messiness_adds_recorded_imperfections_and_replays(tmp_path: Path) -> None:
    """Recorded, not merely present: an imperfection the corpus cannot itself
    explain would be a defect wearing realism's clothes."""
    built = _build(tmp_path, "--seed", "8128", "--incident", "--messiness", "lived_in")
    assert built.intentional_errors
    assert built.recipe["steps"][-1] == {"scenario": "Imperfections", "profile": "lived_in"}
    _replays(built, tmp_path, "messiness")


def test_the_recipe_records_the_profile_by_name(tmp_path: Path) -> None:
    """Not the expanded budget: a profile whose counts are later revised must
    replay as the profile that was asked for."""
    built = _build(tmp_path, "--seed", "8128", "--incident", "--messiness", "neglected")
    assert built.recipe["steps"][-1]["profile"] == "neglected"


def test_pristine_writes_nothing_at_all(tmp_path: Path) -> None:
    plain = _build(tmp_path, "--seed", "8128", "--incident", name="plain")
    pristine = _build(tmp_path, "--seed", "8128", "--incident",
                      "--messiness", "pristine", name="pristine")
    assert pristine.recipe == plain.recipe


def test_an_unknown_messiness_profile_is_refused() -> None:
    result = runner.invoke(app, ["build", "--messiness", "livedin"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# --timeline
# ---------------------------------------------------------------------------


def test_a_sampled_history_runs_org_changes_between_the_closes(tmp_path: Path) -> None:
    built = _build(tmp_path, "--seed", "8128", "--periods", "12", "--timeline", "turbulent")
    scenarios = [step["scenario"] for step in built.recipe["steps"]]
    assert scenarios.count("MonthEndClose") == 12
    assert set(scenarios) - {"MonthEndClose"}, "a turbulent year with no org change"
    assert any(person.left is not None for person in built.people)


def test_a_history_needs_no_recipe_verb_of_its_own(tmp_path: Path) -> None:
    """Every scenario a timeline holds already records itself, so the steps *are*
    the history. A `timeline` key beside them would be a second account of one
    thing."""
    built = _build(tmp_path, "--seed", "8128", "--periods", "6", "--timeline", "steady")
    assert "timeline" not in built.recipe
    assert "density" not in built.recipe
    _replays(built, tmp_path, "timeline")


def test_a_quiet_history_is_the_plain_loop(tmp_path: Path) -> None:
    """`quiet` schedules nothing, so it is `--periods` exactly — which is what
    makes the other two densities a choice rather than an accident."""
    loop = _build(tmp_path, "--seed", "8128", "--periods", "3", name="loop")
    quiet = _build(tmp_path, "--seed", "8128", "--periods", "3",
                   "--timeline", "quiet", name="quiet")
    assert quiet.recipe == loop.recipe


def test_a_schedule_and_a_forced_incident_may_not_both_decide() -> None:
    result = runner.invoke(app, ["build", "--periods", "6", "--timeline", "steady", "--incident"])
    assert result.exit_code == 2
    assert "both decide" in result.output


def test_a_history_is_refused_on_a_single_episode_vertical() -> None:
    """Their scenario takes no incident flag, so a scheduled incident would be
    dropped on the floor and the corpus would be `--periods N` wearing a
    history's name."""
    result = runner.invoke(app, ["build", "--archetype", "midsize_adi",
                                 "--periods", "4", "--timeline", "steady"])
    assert result.exit_code == 2
    assert "--timeline" in result.output


def test_a_history_and_an_actor_episode_are_refused_together() -> None:
    result = runner.invoke(app, ["build", "--periods", "4", "--timeline", "steady",
                                 "--actors", "scripted"])
    assert result.exit_code == 2


def test_an_unknown_density_is_refused() -> None:
    result = runner.invoke(app, ["build", "--timeline", "chaotic"])
    assert result.exit_code == 2


# ---------------------------------------------------------------------------
# Everything at once
# ---------------------------------------------------------------------------


def test_the_flags_compose_and_the_result_still_replays(tmp_path: Path) -> None:
    built = _build(
        tmp_path, "--seed", "8128", "--periods", "6", "--timeline", "steady",
        "--facet", "listing=listed", "--locale", "germany",
        "--messiness", "lived_in", "--distractors", "2",
    )
    assert built.validate().ok
    _replays(built, tmp_path, "everything")


# ---------------------------------------------------------------------------
# The registries, as listings
# ---------------------------------------------------------------------------


def test_pack_facets_prints_the_registry_and_its_json_is_data() -> None:
    result = runner.invoke(app, ["pack", "facets", "--json"])
    assert result.exit_code == 0
    registry = json.loads(result.output)
    assert "listing" in registry
    assert next(o["value"] for o in registry["listing"]["options"]) == "listed"
    assert "listing:mutual" in registry["listing"]["options"][0]["excludes"]


def test_pack_facets_takes_one_facet_and_refuses_an_unknown_one() -> None:
    assert runner.invoke(app, ["pack", "facets", "listing"]).exit_code == 0
    assert runner.invoke(app, ["pack", "facets", "ownership"]).exit_code == 2


def test_pack_locales_and_landscapes_and_messiness_list_their_registries() -> None:
    for command, expected in (
        (["pack", "locales", "--json"], "germany"),
        (["pack", "landscapes", "--json"], "banking"),
        (["pack", "messiness", "--json"], "neglected"),
    ):
        result = runner.invoke(app, command)
        assert result.exit_code == 0, result.output
        assert expected in json.loads(result.output)


def test_an_unknown_locale_or_landscape_is_refused_by_the_listing_too() -> None:
    assert runner.invoke(app, ["pack", "locales", "atlantis"]).exit_code == 2
    assert runner.invoke(app, ["pack", "landscapes", "mining"]).exit_code == 2


# ---------------------------------------------------------------------------
# pack export
# ---------------------------------------------------------------------------


def test_a_mosaic_world_exports_into_a_buildable_bundle(tmp_path: Path) -> None:
    """The round trip is the claim: export, lint, build. A bundle whose pack did
    not build would be a shareable artifact that shares nothing."""
    kept = tmp_path / "kept"
    result = runner.invoke(app, ["pack", "export", str(kept), "--world", "3", "-n", "5"])
    assert result.exit_code == 0, result.output
    assert (kept / "pack.json").exists()
    assert "unfilled" in result.output

    assert runner.invoke(app, ["pack", "check", str(kept / "pack.json")]).exit_code == 0
    args = ["build", "--out", str(tmp_path / "from-kept"), "--pack", str(kept / "pack.json")]
    if (kept / "physics.json").exists():
        args += ["--physics", str(kept / "physics.json")]
    assert runner.invoke(app, args).exit_code == 0


def test_pack_export_needs_exactly_one_source(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pack", "export", str(tmp_path / "x")])
    assert result.exit_code == 2
    assert "exactly one" in result.output


def test_an_index_outside_the_mosaic_is_refused(tmp_path: Path) -> None:
    result = runner.invoke(app, ["pack", "export", str(tmp_path / "x"), "--world", "99", "-n", "3"])
    assert result.exit_code == 2
