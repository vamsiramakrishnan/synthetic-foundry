"""`EpisodeSpec.replaces`: an authored process standing in for a built-in one.

`--episode` is additive by construction — the build path runs the domain's own
`single_episode` for each period and *then* every authored episode named on the
command line — so an authored process that models the same cycle collides with
the built-in it re-expresses. Measured before this field existed, on the shipped
insurer's own pack: four `cohort_cell_duplicated` findings on
`reserves.ultimate` (both processes state a figure for the same four accident
quarters), and no second quarter at all, because `QuarterlyReserving` refuses
its own second run. The authored reserving cycle was therefore reachable from
the SDK and not from the command line, which is the gap this closes.

What the tests pin, in the order the field is used:

- **The declaration is refused when it names nothing.** A `replaces` that
  matches no registered domain's built-in would be silently additive — the
  worst shape, because the build reports success on the collision.
- **A cross-engine `replaces` is refused too.** It can never fire, and an
  episode that believes it is standing in for something is not the same corpus
  as one that knows it is additive.
- **The substitution runs, four quarters deep, and validates.** The build
  command in the issue verbatim.
- **The recipe records it by omission, and replays.** No `replaces` key is
  written anywhere: the steps that ran *are* the record, so a rebuild that
  drops the same built-in is the proof, and it is a byte-for-byte one.

The registry-restoring fixture is `tests/test_cohorts.py`'s, for its reason
verbatim: installing a spec also registers its derived check group, which
`validate` then runs against every world for the rest of the session, and a
test may add to a registry but may not leave anything in one.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from worldloom import episodes, packs
from worldloom import recipe as recipe_module
from worldloom import validate as validate_module
from worldloom.cli import app

PACK = "examples/packs/longtail-insurer.json"
EPISODE = "QuarterlyValuation"
BUILT_IN = "QuarterlyReserving"

runner = CliRunner()

_REGISTRIES = (
    lambda: episodes._LOADED,
    lambda: episodes._REGISTERED_CHECKS,
    lambda: validate_module._DOMAIN_CHECKS,
)


@pytest.fixture(autouse=True)
def _restore_the_registries():
    saved = [(registry(), dict(registry())) for registry in _REGISTRIES]
    try:
        yield
    finally:
        for registry, original in saved:
            registry.clear()
            registry.update(original)


def _spec(**overrides) -> episodes.EpisodeSpec:
    """The smallest spec the grammar accepts, plus whatever is under test."""
    return episodes.EpisodeSpec(
        name="Stand",
        domain="insurance",
        period="quarter",
        fact_kinds=[episodes.FactKindSpec(
            kind="reserves.stand_in",
            value_type="money",
            amount=1.0,
            invariants=[episodes.Invariant(kind="holds-at")],
        )],
        **overrides,
    )


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_the_replaceable_set_is_read_off_the_domain_registry() -> None:
    """Every domain that runs one episode per period, and nothing else.

    Retail is absent on purpose: its close loop is driven with incident,
    comparative, actor and timeline arguments this grammar cannot state, so
    standing in for it would drop flags nobody could see were dropped.
    """
    replaceable = episodes.replaceable_scenarios()
    assert replaceable[BUILT_IN] == "insurance"
    assert "MonthEndClose" not in replaceable


def test_an_episode_replacing_nothing_registered_is_refused() -> None:
    """The misspelling that would otherwise report success.

    A `replaces` the build path cannot match runs the built-in *as well*, which
    is the collision the field exists to end — so it is caught where an author
    reads findings rather than where a validator reads facts.
    """
    findings = episodes.lint([_spec(replaces="QuarterlyValuationCycle")])
    assert any("names no built-in episode" in finding for finding in findings)
    # And the replaceable set is named, so the fix is in the finding.
    assert any(BUILT_IN in finding for finding in findings)


def test_an_episode_replacing_another_engines_built_in_is_refused() -> None:
    """It could never fire: the build path compares against *its own* domain's
    scenario, so a banking pack claiming the insurer's episode stays additive
    while believing otherwise."""
    findings = episodes.lint([_spec(replaces=BUILT_IN)], base="banking")
    assert any("would never fire" in finding for finding in findings)
    # The same declaration under the engine that owns it is clean.
    assert episodes.lint([_spec(replaces=BUILT_IN)], base="insurance") == []


def test_the_shipped_insurer_pack_declares_the_substitution() -> None:
    """Read off the pack rather than restated: the authored valuation *is* the
    reserving cycle, and that claim lives on the spec rather than on whichever
    command line happens to run it."""
    pack = packs.load(PACK)
    assert packs.lint(pack) == []
    packs.archetype_of(pack)  # installs the spec
    assert episodes.loaded()[EPISODE].replaces == BUILT_IN


# ---------------------------------------------------------------------------
# The build
# ---------------------------------------------------------------------------


def test_four_authored_quarters_build_and_validate(tmp_path) -> None:
    """The command that could not be run before, run.

    Four quarters is the point: the built-in refuses its own second run, so
    every count above one is a corpus the command line could not reach.

    It is also the test that says what `domains.Domain.max_periods` means, and
    it caught the first version of that guard getting it wrong. `build` refuses
    `--periods 2` against the insurer because `QuarterlyReserving` implements
    phase 1 only — but the cap belongs to *that episode*, not to the vertical,
    and a cap applied by vertical refused this build too. An authored grammar
    standing in for a built-in is not bound by the built-in's limits; if this
    goes red with "builds at most 1 period(s)", that distinction is what broke.
    """
    out = tmp_path / "corpus"
    result = runner.invoke(app, [
        "build", "--pack", PACK, "--episode", EPISODE, "--periods", "4",
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    assert "coherent" in result.output
    assert BUILT_IN in result.output  # the skip is announced, never silent

    recipe = json.loads((out / "world.json").read_text(encoding="utf-8"))["recipe"]
    steps = [step["scenario"] for step in recipe["steps"]]
    # The record of the substitution is the built-in's absence from the steps
    # that ran — no `replaces` key is written, because a recipe stating it
    # beside the step list would be two accounts of one history.
    assert steps == ["AuthoredEpisode"] * 4
    assert BUILT_IN not in steps
    assert "replaces" not in json.dumps(recipe["steps"])

    # Four valuations of the authored grid, and none of the built-in's own
    # triangle: `claims.paid` is the hand-written generator's and nothing else
    # mints it.
    facts = [
        json.loads(line)
        for line in (out / "facts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    valuations = {
        fact["valid_from"] for fact in facts
        if fact["kind"] == "reserves.central_estimate_total"
    }
    assert len(valuations) == 4


def test_the_substituted_build_rebuilds_from_its_own_recipe(tmp_path) -> None:
    """Byte-for-byte, with the registries cleared first.

    The rebuild has to install the spec itself off the embedded pack *and* drop
    the same built-in — and it drops it for the only honest reason: the recipe
    never asked for it.
    """
    out = tmp_path / "corpus"
    result = runner.invoke(app, [
        "build", "--pack", PACK, "--episode", EPISODE, "--periods", "2",
        "--out", str(out),
    ])
    assert result.exit_code == 0, result.output
    recipe = json.loads((out / "world.json").read_text(encoding="utf-8"))["recipe"]

    for registry in _REGISTRIES:
        registry().clear()
    again = recipe_module.rebuild(recipe).compile()

    original = [
        json.loads(line)
        for line in (out / "facts.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert [fact.model_dump(mode="json") for fact in again.facts] == original


def test_a_substitution_this_build_cannot_honour_is_refused(tmp_path) -> None:
    """Stated, not ignored: the retail close is not replaceable, and a build
    that ran both would produce the collision while reporting success."""
    packs.archetype_of(packs.load(PACK))  # the spec is installed process-wide
    result = runner.invoke(app, [
        "build", "--episode", EPISODE, "--periods", "1",
        "--out", str(tmp_path / "corpus"),
    ])
    assert result.exit_code == 2
    assert "stand in for nothing" in result.output
