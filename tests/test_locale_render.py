"""A locale that reaches the rendered document, not just the model.

`worldloom.locales` gave the project four jurisdictions and a figure grammar for
each, and `render/values.format_value` grew a `locale=` parameter to spell them.
Nothing passed one. A corpus built in Frankfurt still printed `243,800` and
`(2,900)` in every DOCX, PPTX, PDF, Markdown file and index entry it produced,
which is the whole defect a locale exists to fix and the only half of it a reader
ever sees.

So these tests are about the wiring, and they check the three properties that
make the wiring correct rather than merely present:

* **It arrives.** A corpus whose recipe names Germany renders German figures —
  in the tables, in the prose, and in the retrieval index.
* **It arrives everywhere at once.** Word and Markdown spell one figure the same
  way under a non-default locale. This is `render/docx._negative_text`'s rule
  restated where it can now actually be broken: before the locale reached a
  renderer, every format was Anglo and agreement was free.
* **It costs an un-localised corpus nothing.** An absent locale is the engine's
  own, byte for byte, because every corpus built before this existed carries no
  locale and was Australian.
"""

from __future__ import annotations

import io
import re
import zipfile

import pytest

from worldloom import MonthEndClose, RetailWorld, World, locales, recipe
from worldloom.evaluate import index
from worldloom.narrative import DeterministicProvider, references
from worldloom.render.values import corpus_locale, format_value

PERIOD = "2026-03"

#: The artifact that carries both a resolved money table and prose that cites
#: the same figures — the one document where the two formatters can be caught
#: disagreeing.
MEMO = "cfo_variance_memo"


@pytest.fixture(scope="module")
def narrated() -> World:
    """One world, narrated once. Both locale renders below project *this*
    corpus, which is the point: nothing about the world changes, only how it is
    spelled."""
    return (
        RetailWorld(seed=8128)
        .build()
        .run(MonthEndClose(period=PERIOD, include_operational_incident=True))
        .narrate(DeterministicProvider())
    )


def _in(world: World, name: str) -> World:
    return world.extend(recipe=recipe.with_locale(world.recipe, name))


#: What `render/markdown.py` prints on a section the IR marks hidden. Everything
#: after it is the lineage appendix, which is machinery rather than the document
#: — `evaluate.passages` excludes it from retrieval for the same reason.
_HIDDEN = "*(not part of the readable surface)*"


def _readable(body: str) -> str:
    """*body* down to the first hidden section.

    The cut is load-bearing, not cosmetic. The supporting-facts appendix holds
    `references.describe(fact)` output that `documents.outline` spells into the
    IR as a **string** at compile time, before any locale is known — so those
    rows still read `EUR 182,019,500` under Germany. That is a real gap and it
    is named in its own test below; every assertion about what a *reader* sees
    is made against this.
    """
    return body.split(_HIDDEN)[0]


def _markdown(world: World, artifact_type: str) -> str:
    rendered = world.render("markdown")
    wanted = {
        ir.id for ir in rendered.artifact_irs
        if rendered.artifact_intents.by_id(ir.intent_id).artifact_type == artifact_type
    }
    item = next(r for r in rendered._rendered if r.artifact_id in wanted)
    return item.text


def _docx_text(world: World, artifact_type: str) -> str:
    rendered = world.render("docx")
    wanted = {
        ir.id for ir in rendered.artifact_irs
        if rendered.artifact_intents.by_id(ir.intent_id).artifact_type == artifact_type
    }
    item = next(r for r in rendered._rendered if r.artifact_id in wanted)
    with zipfile.ZipFile(io.BytesIO(item.payload)) as bundle:
        return bundle.read("word/document.xml").decode("utf-8")


# ---------------------------------------------------------------------------
# The locale arrives
# ---------------------------------------------------------------------------


def test_a_corpus_renders_in_the_locale_its_recipe_names(narrated: World) -> None:
    """The defect, stated as a test: build under Germany, render, read digits.

    Asserted on a figure taken from the corpus itself rather than a literal, so
    this keeps meaning the same thing when the seed's numbers move.
    """
    body = _readable(_markdown(_in(narrated, "germany"), MEMO))

    facts = {fact.id: fact for fact in narrated.facts}
    cited = [
        facts[fact_id]
        for ir in narrated.artifact_irs
        if narrated.artifact_intents.by_id(ir.intent_id).artifact_type == MEMO
        for section in ir.sections
        if section.body and not section.hidden
        for fact_id in references.referenced(section.body)
    ]
    grouped = [
        fact for fact in cited
        if fact.value is not None and abs(fact.value.amount) >= 1000
    ]
    assert grouped, "the memo's prose cites no figure large enough to be grouped"

    for fact in grouped:
        australian = references.render_value(fact, locale=locales.AUSTRALIA)
        german = references.render_value(fact, locale=locales.GERMANY)
        assert australian != german, fact.id
        assert german in body, (fact.id, german)
        assert australian not in body, (fact.id, australian)


def test_the_locale_reaches_the_table_and_the_prose_as_one_grammar(narrated: World) -> None:
    """`narrative/references` and `render/values` were two number formatters with
    two copies of the digit grammar. A memo whose table read `1.234,50` and whose
    paragraph read `1,234.50` two lines below it is a document disagreeing with
    itself, so both now write through `Locale.spell`.

    Checked on one artifact that carries both, in one render.
    """
    body = _readable(_markdown(_in(narrated, "germany"), MEMO))
    _, _, table = body.partition("| --- |")
    assert table, "the memo lost its resolved table; this test needs one"

    # Every grouped figure in the German render groups on the full stop. A
    # comma-grouped run of digits anywhere in the file is one of the two
    # formatters still writing Anglo.
    assert not re.search(r"\d,\d{3}\b", body), re.findall(r"\S*\d,\d{3}\S*", body)[:5]
    assert re.search(r"\d\.\d{3}\b", body), "no German-grouped figure in the document at all"


def test_word_and_markdown_still_spell_one_figure_identically(narrated: World) -> None:
    """`render/docx._negative_text`'s rule, under the conditions that can break it.

    That function refuses to apply a per-renderer negative convention because a
    table once printed `-10,200` in Word and `(10,200)` in Markdown. Agreement
    was free while every renderer was hardcoded Anglo; it stops being free the
    moment a locale is threaded, and a renderer that missed the thread would
    fail exactly here and nowhere else.
    """
    german = _in(narrated, "germany")
    body = _readable(_markdown(german, MEMO))
    document = _docx_text(german, MEMO)

    figures = [line for line in body.splitlines() if line.startswith("|") and "-" in line]
    assert figures, "the memo has no negative figure to disagree about"
    for line in figures:
        for cell in (part.strip() for part in line.split("|")):
            if cell.startswith("-") and cell[1:2].isdigit():
                assert f">{cell}<" in document, (cell, "Word and Markdown disagree")


def test_the_retrieval_index_is_spelled_the_way_the_documents_are(narrated: World) -> None:
    """A BM25 index built in one grammar over a corpus written in another cannot
    match the string a reader would copy out of the document. The index is not a
    view of the corpus; it is what a retriever is asked to match against."""
    # Hidden sections excluded, which is `passages()`'s own default and what a
    # retriever is actually given — see `_readable` for what lives in them.
    texts = index.document_texts(_in(narrated, "germany"))
    joined = "\n".join(texts.values())
    assert re.search(r"\d\.\d{3}\b", joined)
    assert not re.search(r"\d,\d{3}\b", joined)


def test_the_lineage_appendix_does_not_yet_follow_the_locale(narrated: World) -> None:
    """The one place a German corpus still prints Anglo digits, recorded so it is
    a known boundary rather than a surprise.

    `documents.outline` builds the supporting-facts appendix by calling
    `references.describe(fact)` and storing the **result** in a `Cell` — a
    finished string, spelled at compile time, months before a renderer knows
    what jurisdiction the corpus is in. A renderer cannot re-spell it without
    parsing a number back out of prose, which is precisely the second grammar
    `render/values` exists to prevent.

    `describe` now takes a `locale`, so the fix is one argument at the call site
    (`documents.py`, and its banking/insurance twins). It is not made here
    because it would move the spelling decision to compile time for that one
    table while every other figure is spelled at render time, and the two would
    then disagree for any corpus whose locale is set after it is compiled.

    Contained, in the meantime, by what the appendix is: `ArtifactSection.hidden`
    is true for it, so it is outside the readable surface and outside the
    retrieval index.
    """
    body = _markdown(_in(narrated, "germany"), MEMO)
    assert _HIDDEN in body, "the appendix stopped being hidden; this gap is now visible"

    appendix = body.split(_HIDDEN)[1]
    assert re.search(r"\d,\d{3}\b", appendix), "the appendix now localises — delete this test"


# ---------------------------------------------------------------------------
# The locale is one decision, and it survives
# ---------------------------------------------------------------------------


def test_an_un_localised_corpus_is_the_engines_own_locale(narrated: World) -> None:
    """The byte-identity claim, as an assertion rather than a diff: no locale on
    the recipe means Australia, which is what every corpus built before locales
    existed *was*."""
    assert recipe.LOCALE_KEY not in narrated.recipe
    assert corpus_locale(narrated) is locales.DEFAULT


def test_a_named_locale_is_stored_by_name_and_a_bespoke_one_by_value() -> None:
    """A registry name keeps pointing at the registry; conventions with no name
    have to be carried whole. Storing the dict for a named locale would freeze a
    copy of `locales.GERMANY` into every corpus that used it."""
    assert recipe.with_locale({}, "germany")[recipe.LOCALE_KEY] == "germany"

    bespoke = recipe.with_locale({}, locales.GERMANY)[recipe.LOCALE_KEY]
    assert isinstance(bespoke, dict)
    assert recipe.locale_of({recipe.LOCALE_KEY: bespoke}) == locales.GERMANY


def test_a_recipe_naming_an_unknown_locale_is_refused_not_defaulted() -> None:
    """`locales.named`'s posture, carried through to the corpus: a German
    subsidiary that silently rendered Australian is plausible in every figure and
    there is nothing in the output to notice the drop by."""
    with pytest.raises(recipe.RecipeError, match="locale"):
        corpus_locale(_Recipe({recipe.LOCALE_KEY: "germay"}))
    with pytest.raises(KeyError):
        recipe.with_locale({}, "germay")


class _Recipe:
    """A stand-in world: `corpus_locale` reads exactly one thing off one."""

    def __init__(self, payload: dict) -> None:
        self.recipe = payload


def test_a_rebuilt_corpus_keeps_the_locale_it_was_written_in() -> None:
    """A recipe that could not replay the locale would rebuild a world that is
    identical in every fact and renders every figure differently — success
    reported for a corpus nobody could tell had changed."""
    world = _in(RetailWorld(seed=8128).build(), "germany")
    replayed = recipe.rebuild(world.recipe)

    assert replayed.recipe[recipe.LOCALE_KEY] == "germany"
    assert corpus_locale(replayed) is locales.GERMANY


# ---------------------------------------------------------------------------
# The grammar itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "unit, amount, australian, german",
    [
        ("AUD_thousands", 182019.5, "AUD 182,019.50", "AUD 182.019,50"),
        ("AUD_thousands", -4705.0, "AUD 4,705 thousands adverse", "AUD 4.705 thousands adverse"),
        ("percent", 25.66, "25.66%", "25,66 %"),
        ("bps", -130.0, "130 bps adverse", "130 bps adverse"),
        ("SKUs", 16183.0, "16,183 SKUs", "16.183 SKUs"),
    ],
)
def test_prose_spells_a_fact_in_the_corpus_grammar(
    unit: str, amount: float, australian: str, german: str
) -> None:
    """Every branch of `references.render_value`, in both grammars.

    The money branch is *worded* negative (`adverse`) in both, deliberately: the
    accounting parenthesis and the leading minus are table conventions, and a
    sentence ending `AUD (4,705)` would be a table cell that had wandered into
    prose. Only the digits move.
    """
    from worldloom.models import CanonicalFact, Quantity

    fact = CanonicalFact(
        id="FACT-0001", subject="ORG-1", kind="test.measure",
        value=Quantity(amount=amount, unit=unit),
        valid_from="2026-04-01T00:00:00+00:00", authority="system_of_record",
    )
    if unit == "AUD_thousands" and amount > 0:
        australian, german = australian.replace(" thousands", ""), german.replace(" thousands", "")
        australian += " thousands"
        german += " thousands"
    assert references.render_value(fact, locale=locales.AUSTRALIA) == australian
    assert references.render_value(fact, locale=locales.GERMANY) == german


def test_a_cell_and_a_sentence_share_one_digit_grammar() -> None:
    """The unification, at the seam. Two presenters, one grammar: whatever
    `format_value` groups a figure with, `render_value` groups it with too."""
    from worldloom.models import CanonicalFact, Quantity

    for locale in locales.LOCALES.values():
        cell = format_value(1234567.0, "#,##0", locale=locale)
        fact = CanonicalFact(
            id="FACT-0001", subject="ORG-1", kind="test.measure",
            value=Quantity(amount=1234567.0, unit="AUD"),
            valid_from="2026-04-01T00:00:00+00:00", authority="system_of_record",
        )
        assert cell in references.render_value(fact, locale=locale)
