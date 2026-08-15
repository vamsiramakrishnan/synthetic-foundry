"""A flag either does something or is refused. It may not be accepted and ignored.

Every finding pinned here came from one adversarial pass over the CLI, and they
are one defect wearing five faces: a flag whose effect lives in one build branch
while the command has three. The command has a plain retail loop, a
single-episode loop for the other verticals, and a `--timeline` branch — and
what a reader cannot see from any one of them is which of the other two also
needs the line.

The measured shape of it, before:

    --hiring / --reviews    accepted and discarded on banking, insurance,
                            procurement, and on every --timeline build
    --episode               accepted and discarded on every --timeline build
    --vary-incidents        accepted and discarded on all three single-episode
                            verticals, while its own companion --incident was
                            refused one line away in the same list
    --estate (via a facet)  reached procurement and raised a raw ValueError
                            advising a flag the caller had never typed

None of them errored, none of them warned, and each produced a corpus
byte-identical to one built without it. That is the worst available outcome: a
caller gets exactly what they did not ask for and a green tick, and the only way
to find out is to diff two builds.

The rounds were never *unsupported* — measured on the engines that silently
dropped them, banking goes from 12 artifact intents to 37 and 744 facts to 804,
and all three verticals validate clean. Nothing was missing but the call, which
is why the fix is one `_rounds` helper the three branches share rather than the
same block written a third time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import domains, landscape
from worldloom.cli import app

runner = CliRunner()

SEED = "8128"

#: The verticals whose episode runs once per period through the single-episode
#: branch — read from the registry, so a fifth engine is covered by registering.
SINGLE_EPISODE = tuple(
    sorted(
        name for name in domains.names()
        if (domain := domains.by_name(name)) is not None
        and domain.single_episode is not None
    )
)


def _corpus(tmp_path: Path, name: str, *args: str) -> Path:
    out = tmp_path / name
    result = runner.invoke(app, ["build", "--seed", SEED, *args, "--out", str(out)])
    assert result.exit_code == 0, result.output
    return out


def _flat(text: str) -> str:
    """*text* with every run of whitespace collapsed to one space.

    Rich wraps to the terminal width, so a phrase in a refusal message is split
    across lines at a width nothing in the test controls — asserting on a raw
    substring passes or fails on how wide the runner happens to be.
    """
    return " ".join(text.split())


def _count(corpus: Path, filename: str) -> int:
    path = corpus / filename
    return len(path.read_text(encoding="utf-8").splitlines()) if path.exists() else 0


@pytest.mark.parametrize("engine", SINGLE_EPISODE)
def test_the_workforce_rounds_reach_every_single_episode_vertical(engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """`--hiring` and `--reviews` add documents on the engines that dropped them.

    Asserted as "strictly more, and still coherent" rather than as a count: the
    exact number is the workforce generator's business and pinning it here would
    make this file fail every time that generator got better at its job. What
    must not come back is the *zero*.
    """
    archetype = domains.by_name(engine).default_archetype
    plain = _corpus(tmp_path, f"{engine}-plain", "-a", archetype)
    rounds = _corpus(
        tmp_path, f"{engine}-rounds", "-a", archetype, "--hiring", "5", "--reviews", "5",
    )

    before = _count(plain, "artifact-intents.jsonl")
    after = _count(rounds, "artifact-intents.jsonl")
    assert after > before, (
        f"{engine}: --hiring/--reviews changed nothing. They are accepted here,"
        " so they must do something or be refused."
    )
    assert _count(rounds, "facts.jsonl") > _count(plain, "facts.jsonl")
    assert runner.invoke(app, ["validate", str(rounds)]).exit_code == 0


def test_the_workforce_rounds_reach_a_timeline_build(tmp_path) -> None:
    """The third branch, which had the same hole and one extra reason to.

    `--timeline` already models departures and reorganisations, so a caller
    reaching for `--hiring` alongside it is asking a coherent question — and got
    silence. The rounds run after the whole history rather than inside it,
    because the sampler owns the schedule; what this asserts is only that they
    run at all and that the result still validates.
    """
    plain = _corpus(tmp_path, "tl-plain", "--periods", "6", "--timeline", "turbulent")
    rounds = _corpus(
        tmp_path, "tl-rounds", "--periods", "6", "--timeline", "turbulent",
        "--hiring", "3", "--reviews", "4",
    )

    assert _count(rounds, "artifact-intents.jsonl") > _count(plain, "artifact-intents.jsonl")
    assert runner.invoke(app, ["validate", str(rounds)]).exit_code == 0


def test_an_authored_episode_reaches_a_timeline_build(tmp_path) -> None:
    """`--episode` worked in two branches of three, which is the hardest kind to spot.

    It ran on the plain loop and on the single-episode loop, so anyone testing
    it saw it work; only `--timeline` dropped it.
    """
    pack = "examples/packs/trading-retailer.json"
    plain = _corpus(
        tmp_path, "ep-plain", "--pack", pack, "--periods", "3", "--timeline", "turbulent",
    )
    with_episode = _corpus(
        tmp_path, "ep-run", "--pack", pack, "--periods", "3", "--timeline", "turbulent",
        "--episode", "ProjectSteering",
    )

    assert _count(with_episode, "artifact-intents.jsonl") > _count(plain, "artifact-intents.jsonl")
    assert runner.invoke(app, ["validate", str(with_episode)]).exit_code == 0


@pytest.mark.parametrize("engine", SINGLE_EPISODE)
def test_vary_incidents_is_refused_where_its_companion_is(engine, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """The flag that rotates an incident, on verticals that have no incident.

    Unlike the rounds above, this one genuinely has nothing to do here — a
    single-episode vertical's scenario takes no incident flag at all — so the
    fix is refusal rather than wiring. The defect was the *asymmetry*:
    `--incident` was refused with a stated reason and `--vary-incidents`, which
    exists only to vary what `--incident` schedules, was waved through.
    """
    archetype = domains.by_name(engine).default_archetype
    result = runner.invoke(app, [
        "build", "--seed", SEED, "-a", archetype, "--vary-incidents",
        "--out", str(tmp_path / engine),
    ])
    assert result.exit_code == 2
    assert "--vary-incidents" in _flat(result.output)
    assert not (tmp_path / engine).exists()


#: The verticals with no landscape vocabulary — read from the registry that
#: decides it, not listed, so registering one closes these cases by itself.
NO_LANDSCAPE = tuple(sorted(set(domains.names()) - set(landscape.LANDSCAPES)))


@pytest.mark.skipif(not NO_LANDSCAPE, reason="every vertical names a landscape")
@pytest.mark.parametrize("source", ["flag", "facet"])
def test_an_estate_a_vertical_cannot_build_is_refused_at_plan_time(source, tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Refused before the world is built, and the message names where it came from.

    The facet case is the one that mattered. Three registered facet values imply
    `estate=large`, one of which appears in AGENTS.md's own example command, and
    on procurement that reached the world builder and raised an unhandled
    `ValueError` whose remediation read "build without `--estate`" — a flag the
    caller had not typed. `landscape.LANDSCAPES` is a registry, so this is
    knowable at plan time; the same shape as reading `Domain.max_periods`.
    """
    engine = NO_LANDSCAPE[0]
    archetype = domains.by_name(engine).default_archetype
    asking = ["--estate", "large"] if source == "flag" else ["--facet", "maturity=legacy"]

    result = runner.invoke(app, [
        "build", "--seed", SEED, "-a", archetype, *asking, "--out", str(tmp_path / "x"),
    ])
    assert result.exit_code == 2, result.output
    assert not isinstance(result.exception, ValueError)
    said = _flat(result.output)
    assert "landscape vocabulary" in said
    assert engine in said
    if source == "facet":
        # The half a generic refusal would have lost: the caller never typed a
        # flag, so a message about `--estate` would send them looking for one.
        assert "a facet asks for an estate" in said
        assert "implied by the facets" in said


def test_a_shortfall_in_messiness_is_stated_rather_than_reported_as_success(tmp_path) -> None:
    """`--messiness neglected` on a default retail build delivers nothing.

    "Budget, not quota" is the documented and correct contract — this pass may
    never invent a figure to be wrong about — but the delivery was silent. The
    profile asks for 17 imperfections, a one-period retail world supports none
    of them, and the summary line said "0 recorded imperfection(s)" beside a
    green tick. Somebody asking for an archive that looks lived-in got a
    pristine one and no indication.

    The structural causes are worth keeping in the assertion's reach: staleness
    and disagreement need a superseded fact that a document cites, and orphaning
    needs an author who has left, which only a departure produces — so on a
    single-period build orphaning is 8 of the 17 before anything else is
    considered.
    """
    out = tmp_path / "neglected"
    result = runner.invoke(app, [
        "build", "--seed", SEED, "--messiness", "neglected", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    said = _flat(result.output)
    assert "of 17 imperfection(s) delivered" in said
    assert "unmet:" in said
    assert "orphaning" in said
    # The claim is about *reporting*, so it is checked against what was written.
    assert _count(out, "intentional-errors.jsonl") == 0


def test_a_world_that_can_support_imperfections_reports_no_phantom_shortfall(tmp_path) -> None:
    """The other half: the warning must not fire on a delivery that succeeded.

    A checker that always complains is one people learn to scroll past, so the
    kinds that are fully met say nothing at all.
    """
    out = tmp_path / "lived"
    result = runner.invoke(app, [
        "build", "--seed", SEED, "--periods", "6", "--timeline", "turbulent",
        "--messiness", "neglected", "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert _count(out, "intentional-errors.jsonl") > 0
    unmet = [line for line in result.output.splitlines() if "unmet:" in line]
    assert not any("disagreement" in line for line in unmet), (
        "disagreement was fully delivered on this world and must not be reported"
        f" as short: {unmet}"
    )


def test_measuring_the_ceiling_does_not_move_the_id_sequence(tmp_path) -> None:
    """Found by a replay test, and worth its own name.

    The ceiling is measured by asking which documents *could* be orphaned, and
    the function that answered also minted an `ERR` id per finding — its own
    docstring's "mints nothing" is about canonical facts, not ids. So merely
    measuring advanced the sequence and the corpus stopped replaying from its
    own ledger. Selection is now split from minting, and this pins the property
    directly rather than waiting for a replay diff to notice.
    """
    from worldloom.generators import distractors
    from worldloom.retail import RetailWorld
    from worldloom.scenarios import MonthEndClose

    world = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True)
    )
    before = json.dumps(distractors.messiness_ceilings(world), sort_keys=True)
    minted = distractors.apply_messiness(
        world, messiness=__import__(
            "worldloom.messiness", fromlist=["named"]
        ).named("neglected"),
    )
    # Measuring again, after a real application, still answers about the world
    # it is handed and still mints nothing of its own.
    assert json.dumps(distractors.messiness_ceilings(world), sort_keys=True) == before
    assert distractors.messiness_ceilings(minted) is not None
