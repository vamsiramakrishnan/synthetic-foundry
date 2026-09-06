"""`validate` installs the corpus's own pack before checking it.

The claim this repository makes about a corpus is that it carries its rules with
it: hand somebody a directory of JSONL and they can prove for themselves that
the artifacts agree. A corpus built from a pack was the hole in that. A pack
authors fact kinds, episodes and lines of business, and the invariants those
declare become *derived* check groups — the cohort grid, the per-kind
invariants — which exist only where the spec is installed. On disk nothing
installs anything: `World.load` reads facts and a recipe, and the validator's
domain registry holds whatever package import happened to put there.

Measured before the fix, on the pack below: 891 checks in the process that
built the corpus, 851 from `worldloom validate` on the exported directory. The
40 missing checks were the corpus's own — 34 from the cohort grid, 6 from the
episode's declared invariants — so an authored corpus's authored rules were
verified only by whoever ran the build, which is the opposite of the promise.

Four claims, each pinned where it could rot:

- **A packless corpus is untouched.** Same count, nothing installed, and the
  report identical to the validator run with no install path at all.
- **An authored corpus on disk gains exactly its own derived checks**, matching
  the in-process figure.
- **Validating leaves the process as it found it.** The registries are
  process-global, and `validate` restoring them is the scoping mechanism, not
  housekeeping.
- **Two authored corpora in one process are each checked by their own rules**,
  which is what the restore buys: two packs may declare the same fact kinds
  under different axes, and the first corpus's grid would otherwise be applied
  to the second corpus's facts.

The registry-restoring fixture is `tests/test_reserving_pack.py`'s, for its
reason verbatim: a test may add to a process-global registry but may not leave
anything in one.
"""

from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from worldloom import InsuranceWorld, World, doctypes, episodes, lob, packs
from worldloom import validate as validate_module
from worldloom.cli import app
from worldloom.corpus import CorpusError

PACK = "examples/packs/longtail-insurer.json"
EPISODE = "QuarterlyValuation"
#: The same process under a second pack — see `_second_pack`. A different name
#: because two packs may not declare one process differently, which `install`
#: refuses outright; the leak this file is about is quieter than that.
SECOND_EPISODE = "SemiannualValuation"
QUARTERS = ("2026-03", "2026-06")
SEED = 8128

#: `retail-close`'s check count, from a corpus that carries no pack. Pinned
#: because "a corpus with no pack behaves exactly as it did" is the half of
#: this change that has to be provably *inert*, and a structural assertion
#: alone would still pass if the install path had begun contributing a check
#: to every corpus in the repository. The figure is the one AGENTS.md's
#: pre-commit `worldloom validate retail-close` prints.
PACKLESS_CHECKS = 1283

_REGISTRIES = (
    lambda: doctypes._INSTALLED,
    lambda: episodes._LOADED,
    lambda: episodes._REGISTERED_CHECKS,
    lambda: lob._INSTALLED,
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


def _snapshot() -> list[dict]:
    """Every process-global registry a pack install writes into, copied.

    Keys and values both, so an entry replaced under one name — the failure
    mode `episodes._REGISTERED_CHECKS` has, being keyed by spec name — reads as
    a difference rather than as an equal-length dict.
    """
    return [dict(registry()) for registry in _REGISTRIES]


def _cleared() -> None:
    """Forget every pack anything installed, so a corpus is read cold.

    The point of the exercise: `worldloom validate <dir>` in a fresh process is
    a process that never installed a pack, and a test that validated straight
    after a build would prove nothing about the seam.

    `_DOMAIN_CHECKS` is stripped of its `episode:` entries rather than cleared,
    because it holds two different kinds of thing: the vertical groups
    registered at package import (`banking`, `insurance`, `cohorts`, …), which
    a fresh interpreter *has*, and the derived groups a pack install adds,
    which it does not. Clearing it wholesale would model a process that never
    imported `worldloom`, and shrink every count here for a reason that has
    nothing to do with packs.
    """
    for registry in (
        doctypes._INSTALLED, episodes._LOADED, episodes._REGISTERED_CHECKS, lob._INSTALLED,
    ):
        registry.clear()
    for name in [n for n in validate_module._DOMAIN_CHECKS if n.startswith("episode:")]:
        del validate_module._DOMAIN_CHECKS[name]


def _authored(pack_source, quarters=QUARTERS, episode=EPISODE) -> World:
    """A corpus built from *pack_source*, two valuations deep and compiled."""
    pack = packs.load(pack_source)
    world = InsuranceWorld.from_pack(pack, seed=SEED).build()
    for quarter in quarters:
        world = world.run(episodes.AuthoredEpisode(episode=episode, period=quarter))
    return world.compile()


def _second_pack() -> dict:
    """A second authored insurer whose grid is *three* cohorts, not four.

    The same fact kinds under a different axis, which is the shape that makes
    leakage visible rather than merely possible: run the four-cohort spec over
    this corpus's cells and every column is a cohort short, so a leak reports
    `cohort_grid_hole` instead of quietly agreeing. Two packs sharing a fact
    kind is not a contrived case — a pack reusing another's vocabulary is
    established practice in this repository (banking mints retail's `close.*`
    verbatim).

    Derived from the shipped pack by substitution rather than authored as a
    second file, so it cannot drift from the pack the rest of this file is
    about: if the shipped insurer's episode is renamed, this renames with it.
    """
    document = json.loads(
        json.dumps(packs.to_recipe(packs.load(PACK))).replace(EPISODE, SECOND_EPISODE)
    )
    document["name"] = "shorttail-insurer"
    document["company_name"] = "Second Authored Insurer"
    document["episodes"][0]["cohorts"][0]["count"] = 3
    return document


def _with_an_unreadable_pack(tmp_path) -> object:
    """An exported authored corpus whose embedded pack no longer validates.

    The units are broken rather than a random key deleted, because `Pack`
    refuses them twice over — a share above one, and shares that do not sum to
    the group — so the fixture does not depend on which validator fires first.
    """
    exported = _authored(PACK).export(tmp_path / "authored", overwrite=True)
    header = json.loads((exported / "world.json").read_text(encoding="utf-8"))
    header["recipe"]["pack"]["units"] = [
        {"key": "broken", "name": "", "kind": "", "share": 9.0}
    ]
    (exported / "world.json").write_text(json.dumps(header, indent=2), encoding="utf-8")
    _cleared()
    return exported


# ---------------------------------------------------------------------------
# The packless corpus, which must not move
# ---------------------------------------------------------------------------


def test_a_corpus_with_no_pack_is_checked_by_exactly_the_rules_it_was_before() -> None:
    """Same count, and nothing installed on the way to it.

    The count is asserted twice over: against the pinned figure, and against
    the validator run directly — which is the pre-fix path, `validate` minus
    the install. Both, because they fail differently: the pin catches the
    install contributing a check to every corpus, and the equality catches it
    contributing one *here* if the pin is ever updated for an unrelated reason.

    Read cold, because the pinned figure is what a *fresh process* prints and
    the whole test suite shares one. Some other file's leftover spec in the
    episode registry would otherwise be added to this corpus's count by the
    cohort group, and this test would report it as a regression in the install
    path it is actually about. (That leftover is real: `pytest -q` leaves the
    registry dirty enough to move this figure by one — reported as a defect of
    its own, and not one this file can fix from here.)
    """
    _cleared()
    world = World.load("retail-close")
    assert world.recipe.get("pack") is None

    before = _snapshot()
    report = world.validate()

    assert report.ok, report.violations
    assert report.checks_run == PACKLESS_CHECKS
    assert report.checks_run == validate_module._Validator(world).run().checks_run
    assert _snapshot() == before, "a packless corpus installed something"


# ---------------------------------------------------------------------------
# The authored corpus, which must gain its own
# ---------------------------------------------------------------------------


def test_an_authored_corpus_on_disk_is_checked_by_its_own_packs_rules(tmp_path) -> None:
    """The defect, stated as the two numbers that used to differ.

    Built, exported, and then read back in a process that has forgotten every
    pack — which is what `worldloom validate <dir>` is. The corpus's own
    derived groups have to come back off its recipe, or the directory is
    checked by a smaller rule set than the one it was built under.
    """
    built = _authored(PACK)
    in_process = built.validate()
    assert in_process.ok, in_process.violations

    exported = built.export(tmp_path / "authored", overwrite=True)
    _cleared()

    from_disk = World.load(str(exported))
    # What the corpus would be checked by without its pack: the core groups and
    # the shipped verticals, and none of what it declared for itself. This is
    # the 851 the defect measured, computed rather than pinned so it stays true
    # if a core check is added.
    without_its_rules = validate_module._Validator(from_disk).run()

    report = from_disk.validate()
    assert report.ok, report.violations
    assert report.checks_run == in_process.checks_run
    assert report.checks_run > without_its_rules.checks_run, (
        "the corpus's own pack contributed no checks — the install is inert"
    )


def test_the_checks_an_authored_corpus_gains_come_from_both_authored_layers(
    tmp_path,
) -> None:
    """Two contributors, separated — because a fix could easily miss one.

    Installing the pack's *grammar* is what lets the cohort group see the grid
    (it reads the episode registry, not the check registry); deriving the
    episode's own invariant checks is a second step that only a run performs,
    and a corpus on disk has no run. Measured as three counts on one world so
    that a fix which registered the derived group but never installed the spec
    — or the reverse — fails here rather than passing on a total that happens
    to be larger.
    """
    exported = _authored(PACK).export(tmp_path / "authored", overwrite=True)
    _cleared()
    world = World.load(str(exported))
    pack = packs.load(PACK)

    # `_Validator` directly rather than `world.validate()`: this is the pre-fix
    # path, the run with whatever the process holds and no install of its own.
    cold = validate_module._Validator(world).run().checks_run
    packs.archetype_of(pack)
    with_the_grammar = validate_module._Validator(world).run().checks_run
    for spec in pack.episodes:
        episodes.install_checks(spec)
    with_the_derived_checks = validate_module._Validator(world).run().checks_run

    assert cold < with_the_grammar < with_the_derived_checks
    # And `validate` reaches the third number on its own, from the recipe.
    _cleared()
    assert World.load(str(exported)).validate().checks_run == with_the_derived_checks


def test_validating_an_authored_corpus_leaves_the_process_as_it_found_it(tmp_path) -> None:
    """The restore, asserted directly.

    `validate` installs into five process-global registries and puts all five
    back. Stated on its own because the leakage test below can only show the
    *consequence*, and a fix that scoped the checks some other way while
    leaving the registries dirty would still fail here — which is the honest
    boundary, since three of those registries are read by code (`documents`,
    `process`) that never runs during validation and would be silently altered.
    """
    exported = _authored(PACK).export(tmp_path / "authored", overwrite=True)
    _cleared()

    before = _snapshot()
    World.load(str(exported)).validate()
    assert _snapshot() == before


# ---------------------------------------------------------------------------
# Two corpora, one process
# ---------------------------------------------------------------------------


def test_two_authored_corpora_in_one_process_are_each_checked_by_their_own_rules(
    tmp_path,
) -> None:
    """The leak the restore exists to prevent, shown as a difference that is not.

    The registries are process-global, so without the restore the first
    corpus's four-cohort spec would still be installed when the second corpus
    is read — and because the two packs mint the same fact kinds, it would find
    the second corpus's cells and measure every column against a grid it never
    had. The assertion is that the second corpus's report is *identical*
    whether or not the first was validated first, checks included.
    """
    first = _authored(PACK).export(tmp_path / "first", overwrite=True)
    _cleared()
    second = _authored(_second_pack(), episode=SECOND_EPISODE).export(
        tmp_path / "second", overwrite=True
    )
    _cleared()

    alone = World.load(str(second)).validate()
    assert alone.ok, alone.violations

    _cleared()
    after_the_first = World.load(str(first)).validate()
    assert after_the_first.ok, after_the_first.violations
    together = World.load(str(second)).validate()

    assert together.ok, together.violations
    assert together.checks_run == alone.checks_run, (
        "the second corpus was checked against the first corpus's rules"
    )

    # And the other way round, because a scoping bug is not symmetric: the
    # three-cohort spec left installed would put a hole in nothing and an
    # extra cell in every column of the four-cohort corpus.
    _cleared()
    first_alone = World.load(str(first)).validate()
    _cleared()
    World.load(str(second)).validate()
    first_after = World.load(str(first)).validate()
    assert first_after.ok, first_after.violations
    assert first_after.checks_run == first_alone.checks_run


# ---------------------------------------------------------------------------
# When the corpus's rules cannot be reconstructed
# ---------------------------------------------------------------------------


def test_a_corpus_whose_embedded_pack_does_not_validate_is_refused(tmp_path) -> None:
    """Loud, never degraded.

    Falling back to the core groups would report "coherent — 851 checks" on a
    corpus whose own invariants were never read, which is the defect wearing a
    tick. The error names the pack, so an author knows which half of the corpus
    is unreadable.
    """
    exported = _with_an_unreadable_pack(tmp_path)
    with pytest.raises(CorpusError, match="embedded pack does not validate"):
        World.load(str(exported)).validate()


def test_the_cli_reports_an_unreadable_pack_as_an_error_not_a_traceback(tmp_path) -> None:
    """Exit 2, beside every other "this corpus cannot be read" failure.

    Exit 1 is reserved for a corpus that was checked and found incoherent, and
    this one was never checked at all.
    """
    result = CliRunner().invoke(app, ["validate", str(_with_an_unreadable_pack(tmp_path))])
    assert result.exit_code == 2
    assert "embedded pack does not validate" in result.output


def test_the_cli_checks_an_authored_corpus_by_its_own_rules(tmp_path) -> None:
    """The end of the trail: the command an agent actually runs.

    `--json` because the count is the claim, and parsing it out of prose is the
    thing the flag exists to avoid.
    """
    built = _authored(PACK)
    in_process = built.validate()
    exported = built.export(tmp_path / "authored", overwrite=True)

    _cleared()
    result = CliRunner().invoke(app, ["validate", "--json", str(exported)])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["ok"] is True
    assert payload["checks"] == in_process.checks_run
