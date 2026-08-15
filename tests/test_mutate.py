"""``twins.mutated``: recipe in, mutated recipe out, no build.

The contract under test is the fan-out one: a harness mutates a recipe per
structural candidate, measures cheaply, and buys builds only for winners — so
the mutated recipe must be an ordinary recipe (rebuildable through the same
``recipe.rebuild`` path ``twin`` uses, deterministically), and every refusal
``twin`` makes must survive the missing build. Where ``twin`` measures a
refusal after two builds, ``mutated`` refuses on a static classification, and
these tests hold the boundary between the three outcomes: applied, refused
(``MutationRefused``), and caller error (``TwinError``) — a loop needs all
three distinguishable without parsing prose.

Builds are the expensive step, so the four this module pays for are
module-scoped: one to record a recipe the honest way (through a real build,
not a hand-typed dict), one base rebuild, and two rebuilds of the mutant —
the second existing purely to prove byte-determinism of the mutated recipe.
"""

from __future__ import annotations

import copy
import json

import pytest

from worldloom.recipe import rebuild
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.twins import Intervention, MutationRefused, TwinError, mutated

SEED = 8128

#: Every stream a corpus persists, compared attribute by attribute where a
#: byte-identity claim is made — the same surface ``test_twins`` sweeps, for
#: the same reason: "identical" is only a claim over what was actually compared.
_PERSISTED = ("_facts", "_events", "_artifact_intents", "_artifact_irs",
              "_artifacts", "_evaluations", "_people", "_business_units",
              "_sites", "_systems", "_services", "_lore")


def _row(model) -> str:
    """The corpus's own jsonl spelling — the representation deltas live at."""
    return json.dumps(model.model_dump(mode="json"), sort_keys=True)


@pytest.fixture(scope="module")
def recipe() -> dict:
    """A retail close whose recipe records paths of both classes.

    ``trend_pct`` (a value path — recorded because it is non-default, the
    conditional-write rule) is the gene the mutation cases patch, and
    ``incident``/``comparatives`` (existence paths, recorded unconditionally
    by ``MonthEndClose``) are what the refusal cases name. `--trend`-style on
    purpose, the way ``test_twins`` builds its step-argument fixture: a
    default corpus records neither, and an unrecorded path is a different
    test (the ``TwinError`` one, below).
    """
    world = (
        RetailWorld(seed=SEED)
        .build()
        .run(MonthEndClose(period="2026-03", include_operational_incident=True,
                           comparative_months=6, trend_pct=0.004))
        .compile()
    )
    return world.recipe


@pytest.fixture(scope="module")
def mutant_recipe(recipe: dict) -> dict:
    """The one real mutation: the recorded trend doubled, 0.004 -> 0.008."""
    return mutated(recipe, (Intervention("steps/0/trend_pct", 0.008),))


@pytest.fixture(scope="module")
def base_world(recipe: dict):
    """The base rebuilt from its own record — never the fixture world itself.

    The P1 lesson ``twins`` carries from ``test_recipe_structure``: the
    fixture world was built by a path that re-supplied constructor arguments,
    and a delta measured against it would attribute any recording gap to the
    mutation. Both sides of every comparison below come out of ``rebuild``.
    """
    return rebuild(recipe, ledger=()).compile()


@pytest.fixture(scope="module")
def mutant_world(mutant_recipe: dict):
    return rebuild(mutant_recipe, ledger=()).compile()


def test_zero_interventions_is_identity(recipe: dict) -> None:
    """An empty patch list returns the recipe unchanged — a copy, not a refusal.

    The choice twin's philosophy implies, and why: twin deliberately does not
    special-case the identity intervention (patch a recorded value with
    itself, measure zero) and names the null delta a *finding* — ``is_null``
    exists because "this reached nothing" is an answer. An empty intervention
    list is the same null one step earlier: folding zero patches over a recipe
    is the recipe, and refusing the fold's identity would special-case exactly
    what twin refuses to. The probe-that-bound-nothing refusal does not apply
    here — that refusal exists because a probe *derives* and a no-op
    derivation reports success for work that reached no engine, whereas
    ``mutated`` is a pure patch whose no-op output is exactly correct and
    provably so (the caller can compare the bytes, as this test does).
    """
    result = mutated(recipe, ())
    assert result == recipe
    # A copy, so a caller editing the result can never corrupt the corpus's
    # own record through an alias.
    assert result is not recipe
    result["seed"] = SEED + 1
    assert recipe["seed"] == SEED


def test_interventions_apply_in_order_and_touch_nothing_else(recipe: dict) -> None:
    """N interventions land where addressed; the input recipe is never mutated."""
    pristine = copy.deepcopy(recipe)
    result = mutated(recipe, (
        Intervention("steps/0/trend_pct", 0.008),
        Intervention("steps/0/period", "2026-04"),
    ))
    assert result["steps"][0]["trend_pct"] == 0.008
    assert result["steps"][0]["period"] == "2026-04"
    # Everything not addressed is byte-for-byte the input — the recipe-level
    # statement of the locality twin proves at the corpus level.
    unaddressed = copy.deepcopy(result)
    unaddressed["steps"][0]["trend_pct"] = 0.004
    unaddressed["steps"][0]["period"] = "2026-03"
    assert unaddressed == pristine
    assert recipe == pristine


def test_a_mutated_recipe_rebuilds_deterministically(mutant_recipe: dict, mutant_world) -> None:
    """Two rebuilds of the mutated recipe are the same corpus, to the byte.

    This is the claim that makes ``mutated`` worth anything: its output must
    be an *ordinary* recipe, so a fan-out harness that keeps only the recipe
    (never a world) can still hand a winner to a build farm and get one
    reproducible corpus. Compared at the persisted representation over every
    stream, because "deterministic" is only a claim over what was compared.
    """
    again = rebuild(mutant_recipe, ledger=()).compile()
    for attribute in _PERSISTED:
        first = [_row(m) for m in getattr(mutant_world, attribute)]
        second = [_row(m) for m in getattr(again, attribute)]
        assert first == second, attribute
    # And the rebuilt world's own recipe records the mutated value — the
    # mutation round-trips through a build instead of being shed by it, so a
    # corpus built from a mutated recipe can itself be mutated again.
    assert again.recipe["steps"][0]["trend_pct"] == 0.008


def test_the_mutation_took_and_the_delta_is_confined(base_world, mutant_world) -> None:
    """The doubled trend reaches the comparative history and nothing else.

    ``twin`` measured this intervention's footprint (its step-argument test):
    the trend shapes the months *behind* the reporting month. Here the same
    confinement is recomputed from two rebuilds ``mutated`` mediated — id
    sequences first (the no-reshuffle guarantee the existence gate protects),
    then row diffs. Asserting the changed set non-empty is what separates
    "confined" from "absorbed": a delta of zero would make every confinement
    assertion below pass vacuously while the mutation silently failed to take.
    """
    base_facts = list(base_world._facts)
    mutant_facts = list(mutant_world._facts)
    # Id sequences equal, in order: a value mutation must not change what
    # exists, or every comparison below would align unrelated rows.
    assert [f.id for f in base_facts] == [f.id for f in mutant_facts]

    changed = [b for b, m in zip(base_facts, mutant_facts, strict=True)
               if _row(b) != _row(m)]
    assert changed, "the mutation did not take: no fact row moved"
    # Confinement: every moved fact belongs to a comparative month, strictly
    # before the reporting period the trend has no business touching.
    assert all(f.period is not None and f.period < "2026-03" for f in changed), (
        sorted({f.period for f in changed})
    )
    # And the named negative controls, the half a locality claim needs: the
    # reporting month's revenue and the incident's own facts are byte-identical.
    reporting = [b for b, m in zip(base_facts, mutant_facts, strict=True)
                 if b.period == "2026-03" or b.kind.startswith("ops.")]
    assert reporting, "empty control subset proves nothing"
    for b, m in zip(base_facts, mutant_facts, strict=True):
        if b.period == "2026-03" or b.kind.startswith("ops."):
            assert _row(b) == _row(m), b.id
    # Events and evaluations do not move at all: the eval set asks about the
    # reporting month, and the trend shapes the months behind it.
    for attribute in ("_events", "_evaluations"):
        base_rows = [_row(m) for m in getattr(base_world, attribute)]
        mutant_rows = [_row(m) for m in getattr(mutant_world, attribute)]
        assert base_rows == mutant_rows, attribute


def test_an_unrecorded_path_is_an_error_not_a_refusal(recipe: dict) -> None:
    """The same ``_patched`` grammar ``twin`` resolves through, same class.

    Including an existence-named key the recipe never recorded: ``policies``
    on a corpus built without any is a caller error (nothing recorded to
    intervene on), not a refusal about the policies class — the ordering
    ``twin`` has, kept here so the two commands never disagree about one path.
    """
    with pytest.raises(TwinError, match="not recorded"):
        mutated(recipe, (Intervention("steps/0/trend_pctt", 0.008),))
    with pytest.raises(TwinError, match="not recorded"):
        mutated(recipe, (Intervention("policies", "full"),))


def test_a_cardinality_mutation_is_refused_with_the_cause(recipe: dict) -> None:
    """Existence-deciding paths refuse before any recipe is written.

    Both recorded-and-refused shapes: a step argument (the incident is the
    episode's spine) and a whole step. The message must carry the reasoning —
    "decides what exists" — because a harness reading the refusal is being
    told to route this candidate through ``twin``, which can afford to measure.
    """
    with pytest.raises(MutationRefused, match="decides what exists"):
        mutated(recipe, (Intervention("steps/0/incident", False),))
    with pytest.raises(MutationRefused, match="decides what exists"):
        mutated(recipe, (Intervention("steps/0/comparatives", 12),))
    with pytest.raises(MutationRefused, match="decides what exists"):
        mutated(recipe, (Intervention("steps/0/scenario", "Distractors"),))


def test_duplicate_paths_are_refused_naming_the_path(recipe: dict) -> None:
    """Two values for one gene is a fan-out bug, and it is named, not resolved.

    Last write winning would be silent: the harness would fan out, build the
    winner, and only a wasted build later discover that half its intervention
    never applied. The error names the path so the bug is findable, and it is
    a ``TwinError`` — a caller error, nothing measured — not a refusal.
    """
    with pytest.raises(TwinError, match="steps/0/trend_pct"):
        mutated(recipe, (
            Intervention("steps/0/trend_pct", 0.008),
            Intervention("steps/0/trend_pct", 0.012),
        ))
    # And the identity-pair is still a duplicate: sending the same value twice
    # is the same harness bug with a luckier payload.
    with pytest.raises(TwinError, match="one path, several values"):
        mutated(recipe, (
            Intervention("steps/0/trend_pct", 0.008),
            Intervention("steps/0/trend_pct", 0.008),
        ))
