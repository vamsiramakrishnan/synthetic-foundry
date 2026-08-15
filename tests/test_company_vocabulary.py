"""A world's words, made separable from its shape — `worldloom/vocabulary.py`.

Named ``test_company_vocabulary`` and not ``test_vocabulary`` because that name
is taken by a different thing: ``tests/test_vocabulary.py`` covers the compiler's
*component* vocabulary (``compiler/components.py``), which is about how a
document is built out of atoms. This one is about what a company calls its
divisions.

`evaluate/across.py` measured a five-world mosaic and found 222 questions
reducing to 66 distinct strings, 38 byte-identical in every world. The cause was
not the taxonomy: five worlds built from one archetype share every noun, because
unit names, category names and site formats live on the archetype and an
archetype is one object. `worldloom.vocabulary` supplies alternatives.

Four things this file is for, in the order they matter:

* **A vocabulary renames and cannot re-shape.** The whole safety argument.
  Shares, margins, site counts and revenue weights must survive a renaming
  untouched, or a workbook stops reconciling because somebody added a word list.
* **A unit and its categories stay one business.** The failure that makes a
  corpus incoherent rather than merely repetitive, and the reason a `Trade` is
  indivisible.
* **The precedence rules hold.** A pack wins; an un-asked build is untouched;
  an unknown name is refused rather than defaulted.
* **A mosaic's five worlds are five companies.** The deliverable, asserted as
  distinctness rather than as a golden — the words a given seed deals are an
  implementation detail, that no two of five collide is not.
"""

from __future__ import annotations

import pytest

from worldloom import archetypes, domains, mosaic, packs, vocabulary
from worldloom.vocabulary import QUALIFIER, Trade, Vocabulary

RETAIL_SHAPES = ("omnichannel_retailer", "australian_grocery")
SHAPES = (*RETAIL_SHAPES, "midsize_adi", "midsize_general_insurer")


def _shape(unit) -> tuple:  # type: ignore[no-untyped-def]
    """Everything about a unit that is arithmetic rather than words."""
    return (
        unit.key,
        unit.kind,
        unit.share,
        tuple((c.share, c.margin) for c in unit.categories),
        tuple((f.count, f.revenue_weight) for f in unit.site_formats),
    )


@pytest.mark.parametrize("key", SHAPES)
@pytest.mark.parametrize("name", sorted(vocabulary.VOCABULARIES))
def test_a_vocabulary_renames_and_cannot_reshape(key: str, name: str) -> None:
    """Every word may move; no number may.

    Parametrised over both retail archetypes and every registered vocabulary,
    including the banking and insurance ones — which is why the refusal branch
    is asserted rather than skipped. A vocabulary that cannot name a kind must
    say so, because half-renamed is the one outcome worse than not renamed.
    """
    base = archetypes.get(key)
    if name not in vocabulary.for_units(base.units):
        with pytest.raises(ValueError):
            vocabulary.spoken(base, name)
        return

    spoken = vocabulary.spoken(base, name)
    assert [_shape(u) for u in spoken.units] == [_shape(u) for u in base.units]
    assert spoken.annual_revenue == base.annual_revenue
    assert spoken.site_count == base.site_count
    assert spoken.category_count == base.category_count

    # And the words really did move — otherwise the assertion above is satisfied
    # by a function that returns its argument.
    assert [u.name for u in spoken.units] != [u.name for u in base.units]
    for before, after in zip(base.units, spoken.units):
        # Guarded, not skipped: a unit with nothing to rename is a real shape —
        # a treasury desk's income is not decomposed by product book and its
        # `categories` is an empty tuple on purpose, as is the small retailer's
        # digital arm's `site_formats`. "Renamed nothing" is correct there.
        if before.categories:
            assert [c.name for c in after.categories] != [c.name for c in before.categories]
        if before.site_formats:
            assert [f.name for f in after.site_formats] != [f.name for f in before.site_formats]


@pytest.mark.parametrize("name", sorted(vocabulary.VOCABULARIES))
def test_a_unit_and_its_categories_stay_one_business(name: str) -> None:
    """The coherence claim, asserted structurally rather than by reading names.

    A unit's categories are exactly the head of the same `Trade` its name came
    from — never assembled from a pool shared with another kind. That is what
    makes "a Reinsurance unit selling Home and Living" unrepresentable rather
    than merely unlikely, so it is what the test checks.
    """
    vocab = vocabulary.named(name)
    by_unit_name = {trade.unit: trade for trades in vocab.trades.values() for trade in trades}

    for key in (*RETAIL_SHAPES, "midsize_adi", "midsize_general_insurer"):
        base = archetypes.get(key)
        if name not in vocabulary.for_units(base.units):
            continue
        for unit in vocabulary.spoken(base, name).units:
            trade = by_unit_name[unit.name]
            assert [c.name for c in unit.categories] == list(trade.categories[:len(unit.categories)])
            for fmt in unit.site_formats:
                pool = trade.support if fmt.revenue_weight == 0.0 else trade.trading
                assert fmt.name in pool


def test_a_warehouse_stays_a_warehouse() -> None:
    """A zero-weight format is renamed from the support pool, never the trading one.

    Split out from the parametrised case above because it is the sharp end of
    it: `generators/hierarchy.py` spells out that a distribution centre holds
    stock and books no turnover, and a renaming that drew "Discount Store" for
    it would leave a site table reading as forty shops that sold nothing.
    """
    spoken = vocabulary.spoken(archetypes.get("australian_grocery"), "discount_grocer")
    food = next(u for u in spoken.units if u.key == "food")
    warehouses = [f.name for f in food.site_formats if f.revenue_weight == 0.0]
    assert warehouses == ["Regional Depot"]
    assert set(warehouses).isdisjoint(vocabulary.DISCOUNT_GROCER.trades["supermarkets"][0].trading)


def test_a_pack_wins() -> None:
    """`Pack.units` authors the words, and nothing generated may replace them."""
    pack = packs.load("examples/packs/regional-insurer.json")
    shape = packs.archetype_of(pack)
    assert shape.authored
    for name in sorted(vocabulary.VOCABULARIES):
        assert vocabulary.spoken(shape, name) is shape


def test_no_vocabulary_is_the_default_and_is_untouched() -> None:
    """The byte-identity guarantee, in one line.

    An un-asked build is not "a vocabulary that happens to match the
    archetype's own words" — it is no substitution at all, which is the only
    version of that promise nothing can drift away from.
    """
    base = archetypes.get("omnichannel_retailer")
    assert vocabulary.spoken(base, "") is base
    assert base.vocabulary == ""
    assert [u.name for u in base.units] == ["Food", "General Merchandise", "Digital"]


def test_a_vocabulary_does_not_stack() -> None:
    spoken = vocabulary.spoken(archetypes.get("omnichannel_retailer"), "wholesale_club")
    with pytest.raises(ValueError, match="already speaks"):
        vocabulary.spoken(spoken, "discount_grocer")


def test_an_unknown_vocabulary_is_refused() -> None:
    with pytest.raises(KeyError, match="unknown vocabulary"):
        vocabulary.named("wholsale_club")
    with pytest.raises(KeyError, match="unknown vocabulary"):
        archetypes.get("omnichannel_retailer+wholsale_club")


def test_a_qualified_key_carries_the_words_and_not_the_vertical() -> None:
    """The recipe's carrier, and the one thing it must not confuse.

    `recipe.build_recipe` stores `archetype.key` and nothing else about the
    shape, so the vocabulary rides in the key or a mosaic world rebuilds with
    its figures intact and every division renamed back. `domains.for_archetype`
    must still route it to the engine that builds the *shape*.
    """
    key = f"midsize_adi{QUALIFIER}mutual_bank"
    shape = archetypes.get(key)
    assert shape.key == key
    assert shape.vocabulary == "mutual_bank"
    assert next(u.name for u in shape.units) == "Member Banking"

    domain = domains.for_archetype(key)
    assert domain is not None and domain.name == "banking"
    assert domains.for_archetype("midsize_adi") is domain


def test_a_mosaic_deals_five_companies_not_one_five_times() -> None:
    """The deliverable. Distinctness, and stability under `-n` and under seed."""
    field = mosaic.field(5)
    dealt = [v.vocabulary for v in field]
    assert len(set(dealt)) == 5, dealt

    # Same seed, same words — and a smaller mosaic agrees on the worlds it
    # shares, so re-running with a larger `-n` cannot rename a world the user
    # already has.
    assert [v.vocabulary for v in mosaic.field(5)] == dealt
    assert [v.vocabulary for v in mosaic.field(3)] == dealt[:3]

    # A different seed is a different set of companies, not the same five with
    # different figures inside them.
    assert [v.vocabulary for v in mosaic.field(5, seed=99)] != dealt


def test_speaks_is_a_no_op_for_an_engine_nothing_names() -> None:
    """`cli.py` applies `Variant.speaks` unconditionally, so it has to be safe.

    Constructed rather than taken from `mosaic.field`, because every shipped
    engine *is* covered — and the branch that must not change a corpus is the
    uncovered one.
    """
    variant = mosaic.field(2)[0]
    bare = type(variant)(**{**variant.__dict__, "vocabulary": ""})
    shape = archetypes.get("omnichannel_retailer")
    assert bare.speaks(shape) is shape


def test_every_shipped_vocabulary_dresses_its_engines_default() -> None:
    """A registry entry no engine can use is a name in a table, not a choice."""
    for engine in ("retail", "banking", "insurance"):
        assert vocabulary.for_engine(engine), engine
    covered = {name for engine in ("retail", "banking", "insurance")
               for name in vocabulary.for_engine(engine)}
    assert covered == set(vocabulary.VOCABULARIES)


def test_a_vocabulary_refuses_names_that_would_collide() -> None:
    """Every validation rule shown firing — `tests/test_landscape.py`'s standard."""
    trade = Trade(unit="A", categories=("x",), trading=("S",), support=("D",))

    with pytest.raises(ValueError, match="category twice"):
        Trade(unit="A", categories=("x", "x"))
    with pytest.raises(ValueError, match="blank name"):
        Trade(unit="A", categories=(" ",))
    with pytest.raises(ValueError, match="names no trades"):
        Vocabulary(trades={"supermarkets": ()})
    with pytest.raises(ValueError, match="more than one trade"):
        Vocabulary(trades={"supermarkets": (trade,), "online": (trade,)})
    # Two units sharing a site format mint two different sites with one name.
    twin = Trade(unit="B", categories=("y",), trading=("S",), support=("E",))
    with pytest.raises(ValueError, match="site format"):
        Vocabulary(trades={"supermarkets": (trade,), "online": (twin,)})


def test_a_vocabulary_too_small_for_a_shape_is_refused_not_recycled() -> None:
    """Truncating or reusing would give a company two divisions with one name."""
    thin = Vocabulary(trades={
        "supermarkets": (Trade(unit="Only Food", categories=("a", "b", "c"),
                               trading=("Shop",), support=("Depot",)),),
        "general_merchandise": (Trade(unit="Only GM", categories=("d", "e", "f"),
                                      trading=("Store",), support=("Store Depot",)),),
        "online": (Trade(unit="Only Digital", categories=("g", "h")),),
    })
    vocabulary.VOCABULARIES["_thin"] = thin
    try:
        # The small retailer fits exactly; the grocer needs thirteen food
        # categories and a second supermarkets trade, and gets neither.
        assert thin.dresses(archetypes.get("omnichannel_retailer").units)
        assert not thin.dresses(archetypes.get("australian_grocery").units)
        with pytest.raises(ValueError, match="categories and trade"):
            vocabulary.spoken(archetypes.get("australian_grocery"), "_thin")
    finally:
        del vocabulary.VOCABULARIES["_thin"]
