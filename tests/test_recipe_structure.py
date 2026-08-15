"""The structural genome survives `recipe.rebuild`, not merely `--replay`.

The measured defect this pins. A corpus built with `--outline-synthesis 1000`
records its genome on the recipe, and `recipe.rebuild` dropped the key: the
rebuilt world carried no `structure`, `structure_of` answered `CLASSIC`, and the
rebuild compiled *different outlines* from the corpus it was rebuilding.

It survived every determinism proof this branch ran, and the reason is worth
keeping in front of whoever reads this next. Those proofs all went through
``worldloom build --replay <dir>``, which re-supplies the same command-line
flags — so `cli._shaped` rebuilt the genome from `--outline-synthesis` rather
than from the record, and the recipe's copy was never consulted. **A replay
proof that passes the original flags is not testing the recording.** The flags
are precisely what the recipe exists to make unnecessary.

So these go through `recipe.rebuild` directly, with nothing but the recipe and
the ledger — the library path `validate`, the actor handshake and every
programmatic rebuilder actually take.
"""

from __future__ import annotations

import pytest

from worldloom import recipe as recipe_module
from worldloom.retail import RetailWorld
from worldloom.scenarios import MonthEndClose
from worldloom.structure import StructuralGenome
from worldloom.world import World


def _built(genome: StructuralGenome) -> World:
    """A small corpus carrying *genome* on its recipe, built the way the CLI does.

    `build_recipe` never writes the structure key — only `with_structure` does,
    from `cli._shaped`, after the world is built — so this mirrors that order
    rather than inventing a shorter one. A fixture that attached the genome
    some other way would be testing a path no build takes.
    """
    world = RetailWorld(seed=8128).build()
    world = world.extend(recipe=recipe_module.with_structure(world.recipe, genome))
    return world.run(MonthEndClose(period="2026-03")).compile()


def _shapes(world: World) -> list[tuple[str, tuple[str, ...]]]:
    return sorted(
        (ir.metadata["artifact_type"], tuple(section.heading for section in ir.sections))
        for ir in world.artifact_irs
    )


@pytest.mark.parametrize(
    "genome",
    [
        StructuralGenome(synthesis=1000),
        StructuralGenome(omission=400),
        StructuralGenome(variant_bias=1),
        StructuralGenome(omission=400, variant_bias=1, synthesis=600),
    ],
    ids=["synthesis", "omission", "variant_bias", "all_three"],
)
def test_a_rebuild_compiles_the_outlines_the_recipe_recorded(
    genome: StructuralGenome,
) -> None:
    """The claim, stated on the documents rather than on the key.

    Asserting the recipe round-trips would pass with the genome attached *after*
    the steps ran, which is the subtly worse bug: a recipe that accurately
    records a genome its own documents were not shaped by. So this compares the
    compiled outlines.
    """
    original = _built(genome)
    rebuilt = recipe_module.rebuild(original.recipe, ledger=original._ledger).compile()

    assert _shapes(rebuilt) == _shapes(original)


def test_the_genome_is_on_the_rebuilt_recipe_verbatim() -> None:
    """And it is copied across, not re-derived.

    Verbatim for `locale`'s reason one field along: a recipe that recorded a
    genome must rebuild into one that still records the same genome, so the
    corpus can be rebuilt again from the rebuild.
    """
    genome = StructuralGenome(omission=400, variant_bias=2, synthesis=600)
    original = _built(genome)
    rebuilt = recipe_module.rebuild(original.recipe, ledger=original._ledger)

    assert rebuilt.recipe[recipe_module.STRUCTURE_KEY] == (
        original.recipe[recipe_module.STRUCTURE_KEY]
    )
    assert recipe_module.structure_of(rebuilt.recipe) == genome


def test_a_classic_corpus_rebuilds_with_no_structure_key() -> None:
    """The other half, and the one that keeps the default build byte-identical.

    `with_structure` declines to write the key for a genome that does not vary,
    so a corpus built without one carries no `structure` at all — and a rebuild
    must not invent one. A key appearing here would put a new line into the
    recipe of every corpus ever rebuilt, which is the unconditional-key pattern
    this module argues against in `build_recipe`.
    """
    original = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    rebuilt = recipe_module.rebuild(original.recipe, ledger=original._ledger)

    assert recipe_module.STRUCTURE_KEY not in original.recipe
    assert recipe_module.STRUCTURE_KEY not in rebuilt.recipe
    assert _shapes(rebuilt.compile()) == _shapes(original)
