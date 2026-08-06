"""The authored process, run — the grammar's proof obligation, measured.

The QuarterlyCapitalReturn spec in `examples/episodes/` is the port of the
hand-built banking episode into the episode grammar. These tests pin what the
port actually achieves: it lints clean against the registry (the previous
attempt cited two invented kinds and was never measured), it runs into a world
that passes the full validator — including banking's own domain checks and the
checks derived from the spec's declared invariants — and it replays
byte-identically from its own recipe. What it does *not* achieve, deliberately
pinned nowhere: byte-identity with the hand-built corpus. The measured diff
and its reasons live in docs/episode-grammar.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from worldloom import BankingWorld, episodes

SPEC_PATH = Path(__file__).parent.parent / "examples" / "episodes" / "quarterly-capital-return.json"


@pytest.fixture(scope="module")
def spec() -> episodes.EpisodeSpec:
    specs = episodes.load(SPEC_PATH)
    episodes.install(specs)
    return specs[0]


@pytest.fixture(scope="module")
def world(spec: episodes.EpisodeSpec):
    return BankingWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode=spec.name, period="2026-03")
    )


def test_the_proof_spec_lints_clean(spec: episodes.EpisodeSpec) -> None:
    """Zero findings, measured — not claimed. The lint compares the spec
    against the fact-kind registry, the banking role table, and itself."""
    assert episodes.lint([spec], base="banking") == []


def test_the_authored_episode_validates(world) -> None:
    """The full validator, including banking's own check group (which polices
    capital.* whoever minted it) and the checks derived from the spec."""
    report = world.validate()
    assert report.ok, report.violations[:5]


def test_the_derived_checks_can_fail(spec: episodes.EpisodeSpec, world) -> None:
    """A validator that cannot fail is decoration. Touch the as-filed record —
    the never-superseded invariant — and the derived group must say so."""
    from worldloom.world import World

    entries = list(world._facts)
    index = next(i for i, f in enumerate(entries) if f.kind == "capital.cet1_ratio_as_filed")
    entries[index] = entries[index].model_copy(update={"valid_to": entries[index].valid_from})
    broken = World(**{**world.__dict__, "_facts": tuple(entries)})

    codes = {v.code for v in broken.validate().violations}
    assert "never_superseded_touched" in codes


def test_the_authored_episode_replays_from_its_recipe(world) -> None:
    """The recipe step is `AuthoredEpisode(episode=..., period=...)`; with the
    spec installed, the rebuild is the same world — facts, events, intents."""
    from worldloom import recipe

    again = recipe.rebuild(recipe=world.recipe)
    assert tuple(again._facts) == tuple(world._facts)
    assert tuple(again._events) == tuple(world._events)
    assert tuple(again._artifact_intents) == tuple(world._artifact_intents)


def test_a_missing_spec_fails_loudly_not_silently(world) -> None:
    """A rebuild in a process that never installed the spec must refuse, not
    build a world with a hole where the episode was."""
    step = episodes.AuthoredEpisode(episode="NeverInstalled", period="2026-03")
    base = BankingWorld(seed=8128).build()
    with pytest.raises(ValueError, match="not installed"):
        base.run(step)
