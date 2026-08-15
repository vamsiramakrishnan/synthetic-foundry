"""The generational loop: propose → build → measure → select → vary, recorded.

Everything `evolve` composes is tested elsewhere — `spaces` for the axes,
`dispersion` for the sample, `fleet` for measurement and selection. What is
under test here is the loop's own contract:

* **The run is a pure function of (space, seed).** Two same-seed runs into
  different directories write byte-identical manifests — no clock, no absolute
  path, no float this module computed reaches one.
* **A child is its parent's row with exactly one axis moved**, and the parents
  of generation N+1 are exactly generation N's champions.
* **Nothing unbuildable is ever proposed.** The gate mirrors the CLI's own
  refusals and the registries' declarations, so a proposal is a build, never
  an argument-validation test.
* **The refusals are features**: the `surface` axis (a spec is never recorded,
  so selection could not see it move) and the "naturalistic" purpose
  (`fleet`'s own refusal, before anything is built).

The fixture runs a real two-generation evolution twice on the cheapest
configurations the retail engine has — one period, no estate, no policies —
because the loop's claims (champions from a real curation, replay-verified
members) are only meaningful against corpora the real generators produced.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from worldloom import covering, evolve, fleet, spaces


#: The cheapest space that still exercises the loop: five axes wide enough
#: that a single champion's single-axis neighbourhood cannot exhaust under a
#: population of three, and every value the cheap end of its axis — one
#: period (the absent `periods` axis defaults to "1"), no estate, no
#: policies. The two archetypes are both retail so every history value is
#: legal on every member.
def _cheap_space() -> spaces.BuildSpace:
    return spaces.BuildSpace((
        covering.Parameter("archetype", ("australian_grocery", "omnichannel_retailer")),
        covering.Parameter("history", ("no_incident", "incident")),
        covering.Parameter("locale", ("none", "australia")),
        covering.Parameter("eval_density", ("standard", "low")),
        covering.Parameter("messiness", ("pristine", "well_run")),
    ))


@pytest.fixture(scope="module")
def twin_runs(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path]:
    """The same two-generation evolution, run twice into different roots.

    Both runs in one fixture because the determinism claim is *about the
    pair*: a single run's manifest proves nothing about what a second run
    would have written.
    """
    root_a = tmp_path_factory.mktemp("evolve") / "run-a"
    root_b = tmp_path_factory.mktemp("evolve") / "run-b"
    for root in (root_a, root_b):
        evolve.evolve(
            _cheap_space(), seed=8128, generations=2, population=3,
            out_dir=root, purpose="challenge",
        )
    return root_a, root_b


def _manifest(root: Path, *parts: str) -> dict:
    return json.loads((root.joinpath(*parts)).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Determinism: the run is a function of (space, seed)
# ---------------------------------------------------------------------------


def test_same_seed_twice_is_byte_identical(twin_runs: tuple[Path, Path]) -> None:
    root_a, root_b = twin_runs
    for relative in (
        evolve.RUN_MANIFEST_NAME,
        f"gen0/{evolve.GENERATION_MANIFEST_NAME}",
        f"gen1/{evolve.GENERATION_MANIFEST_NAME}",
        # The curation manifests fleet wrote inside each generation directory
        # are part of the run's record and must hold to the same standard.
        f"gen0/{fleet.MANIFEST_NAME}",
        f"gen1/{fleet.MANIFEST_NAME}",
    ):
        first = (root_a / relative).read_bytes()
        second = (root_b / relative).read_bytes()
        assert first == second, f"{relative} differs between two same-seed runs"


def test_manifests_carry_no_absolute_path(twin_runs: tuple[Path, Path]) -> None:
    """The one thing that legitimately differs between the two runs is where
    they live, so no manifest may mention it — a build command is recorded
    with its out path relative to the run root."""
    root_a, _ = twin_runs
    for relative in (
        evolve.RUN_MANIFEST_NAME,
        f"gen0/{evolve.GENERATION_MANIFEST_NAME}",
        f"gen1/{evolve.GENERATION_MANIFEST_NAME}",
    ):
        text = (root_a / relative).read_text(encoding="utf-8")
        assert str(root_a) not in text


def test_a_rerun_resumes_instead_of_rebuilding(twin_runs: tuple[Path, Path]) -> None:
    """Resume is rerun: members already on disk are recognised and skipped,
    and the manifests come out byte-identical — which also re-proves that the
    survey, not trust, is what stands behind a skipped build."""
    root_a, _ = twin_runs
    member = root_a / "gen0" / "cfg-00" / "world.json"
    before_bytes = (root_a / evolve.RUN_MANIFEST_NAME).read_bytes()
    before_mtime = member.stat().st_mtime_ns

    evolve.evolve(
        _cheap_space(), seed=8128, generations=2, population=3,
        out_dir=root_a, purpose="challenge",
    )
    assert member.stat().st_mtime_ns == before_mtime, "an existing member was rebuilt"
    assert (root_a / evolve.RUN_MANIFEST_NAME).read_bytes() == before_bytes


# ---------------------------------------------------------------------------
# Variation: one axis at a time, from the champions and nobody else
# ---------------------------------------------------------------------------


def test_children_differ_from_their_parent_in_exactly_one_axis(
    twin_runs: tuple[Path, Path],
) -> None:
    root_a, _ = twin_runs
    gen0 = _manifest(root_a, "gen0", evolve.GENERATION_MANIFEST_NAME)
    gen1 = _manifest(root_a, "gen1", evolve.GENERATION_MANIFEST_NAME)
    parents = {f"gen0/{m['label']}": m["configuration"] for m in gen0["members"]}

    assert gen1["members"], "generation 1 proposed nothing"
    for member in gen1["members"]:
        parent = parents[member["parent"]]
        child = member["configuration"]
        moved = sorted(axis for axis in child if child[axis] != parent[axis])
        assert moved == [member["variation"]["axis"]], (
            f"{member['label']} moved {moved}, claimed {member['variation']['axis']}"
        )
        assert parent[member["variation"]["axis"]] == member["variation"]["from"]
        assert child[member["variation"]["axis"]] == member["variation"]["to"]


def test_parents_are_exactly_the_previous_generations_champions(
    twin_runs: tuple[Path, Path],
) -> None:
    root_a, _ = twin_runs
    gen0 = _manifest(root_a, "gen0", evolve.GENERATION_MANIFEST_NAME)
    gen1 = _manifest(root_a, "gen1", evolve.GENERATION_MANIFEST_NAME)

    champions = {f"gen0/{label}" for label in gen0["champions"]}
    parents = {member["parent"] for member in gen1["members"]}
    assert parents == champions

    # Generation zero has no parents: it is the dispersed sample.
    assert all(member["parent"] == "" for member in gen0["members"])
    assert all(member["variation"] is None for member in gen0["members"])


def test_champions_are_members_and_bounded_by_the_population(
    twin_runs: tuple[Path, Path],
) -> None:
    root_a, _ = twin_runs
    for generation in ("gen0", "gen1"):
        manifest = _manifest(root_a, generation, evolve.GENERATION_MANIFEST_NAME)
        labels = {member["label"] for member in manifest["members"]}
        assert len(manifest["members"]) <= 3
        assert 1 <= len(manifest["champions"]) <= 3
        assert set(manifest["champions"]) <= labels
        # And the champions are fleet's, verbatim: the loop selects nothing
        # of its own.
        curated = {champion["world"] for champion in manifest["curation"]["champions"]}
        assert set(manifest["champions"]) == curated


def test_the_selection_record_is_fleets_own(twin_runs: tuple[Path, Path]) -> None:
    """Fitness is an integer and says so; vendi is carried as a reading and
    labelled non-gating — the honesty rules ride in from fleet unchanged."""
    root_a, _ = twin_runs
    manifest = _manifest(root_a, "gen0", evolve.GENERATION_MANIFEST_NAME)
    assert manifest["curation"]["fitness"]["gating"] is True
    for champion in manifest["curation"]["champions"]:
        assert isinstance(champion["fitness"], int)
    assert manifest["qualification"]["effective_diversity"]["gating"] is False


# ---------------------------------------------------------------------------
# Nothing unbuildable is ever proposed
# ---------------------------------------------------------------------------


def test_every_proposed_configuration_was_buildable(
    twin_runs: tuple[Path, Path],
) -> None:
    root_a, _ = twin_runs
    for generation in ("gen0", "gen1"):
        manifest = _manifest(root_a, generation, evolve.GENERATION_MANIFEST_NAME)
        for member in manifest["members"]:
            assert evolve.refusal(member["configuration"]) is None


def test_generation_zero_never_samples_the_unbuildable() -> None:
    """Over the real space — the one place every registry gate can fire. No
    build happens here: proposing is a pure function. Narrowed through
    `excluded`, the same visible act the CLI performs, so this test keeps
    working when `spaces.build_space` grows an axis before evolve learns its
    flag."""
    space = spaces.build_space()
    space = space.select([n for n in space.names if n not in evolve.excluded(space)])
    rows = evolve.propose_generation_zero(space, seed=8128, population=12)
    assert len(rows) == 12
    for row in rows:
        assert evolve.refusal(row) is None
    # A dispersed dozen must actually disperse: the sample is not twelve
    # copies of one configuration.
    assert len({tuple(sorted(row.items())) for row in rows}) == 12


def test_the_gate_names_what_the_registries_refuse() -> None:
    """Each reason names the declaration it mirrors, so a manifest's refusal
    entry reads as a fact about the engine rather than a generic no."""
    # Insurance declares max_periods=1 because QuarterlyReserving refuses its
    # own second run; the gate reads the same declaration the CLI refuses on.
    assert "at most 1 period" in evolve.refusal(
        {"archetype": "midsize_general_insurer", "periods": "3"}
    )
    # Procurement registers no landscape vocabulary, so an estate on it would
    # serve another vertical's names.
    assert "landscape" in evolve.refusal(
        {"archetype": "midsize_infrastructure_services", "estate": "small"}
    )
    # The single-episode refusal block: close-loop axes belong to retail.
    assert "retail close" in evolve.refusal(
        {"archetype": "midsize_adi", "history": "incident"}
    )
    # The one retail-side pair the merged axes cannot express.
    assert "actor" in evolve.refusal(
        {"archetype": "omnichannel_retailer", "knowledge": "actors", "history": "steady"}
    )
    # A value no registry knows is refused before a subprocess is spent on it.
    assert "not registered" in evolve.refusal(
        {"archetype": "omnichannel_retailer", "locale": "atlantis"}
    )
    # And the buildable default row is admitted.
    assert evolve.refusal({"archetype": "omnichannel_retailer"}) is None


# ---------------------------------------------------------------------------
# The refusals are features
# ---------------------------------------------------------------------------


def test_the_surface_axis_is_refused_with_the_reason(tmp_path: Path) -> None:
    """A spec is resolved and never recorded, so a same-seed variation on
    `surface` is the same corpus twice and selection could never see the axis
    move. Refused at the door, naming that, before anything is built."""
    space = spaces.BuildSpace((
        covering.Parameter("archetype", ("australian_grocery", "omnichannel_retailer")),
        covering.Parameter("surface", ("flags", "spec")),
    ))
    with pytest.raises(evolve.EvolveError, match="never recorded"):
        evolve.evolve(space, seed=8128, generations=1, population=2, out_dir=tmp_path / "run")
    assert not (tmp_path / "run").exists()
    # And `excluded` carries the same reason as data, for the caller that
    # narrows the real space before evolving it.
    assert "never recorded" in evolve.excluded(spaces.build_space())["surface"]


def test_an_axis_with_no_flag_mapping_is_refused(tmp_path: Path) -> None:
    space = spaces.BuildSpace((
        covering.Parameter("archetype", ("australian_grocery", "omnichannel_retailer")),
        covering.Parameter("flux", ("low", "high")),
    ))
    with pytest.raises(evolve.EvolveError, match="no build-flag mapping"):
        evolve.evolve(space, seed=8128, generations=1, population=2, out_dir=tmp_path / "run")


def test_naturalistic_is_refused_before_anything_builds(tmp_path: Path) -> None:
    """fleet's own refusal, arriving through evolve at the door: the missing
    thing is reference data, and no generation is spent finding that out."""
    with pytest.raises(fleet.FleetError, match="reference data"):
        evolve.evolve(
            _cheap_space(), seed=8128, generations=1, population=2,
            out_dir=tmp_path / "run", purpose="naturalistic",  # type: ignore[arg-type]
        )
    assert not (tmp_path / "run").exists()


def test_a_population_wider_than_the_space_is_refused(tmp_path: Path) -> None:
    space = spaces.BuildSpace((
        covering.Parameter("history", ("no_incident", "incident")),
    ))
    with pytest.raises(evolve.EvolveError, match="buildable configuration"):
        evolve.evolve(space, seed=8128, generations=1, population=64, out_dir=tmp_path / "run")
