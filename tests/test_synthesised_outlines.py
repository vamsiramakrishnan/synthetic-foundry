"""Synthesis — the third structural mechanism, and the refusal that makes it safe.

`structure.omission` and `structure.variant_bias` rearrange what an author wrote
for *this* document type, and both are safe by construction: a required section
is never dropped, and every variant of a type was written for that type.
Synthesis is not safe by construction. It assembles a document out of sections
written for *other* documents, so the one thing this file is actually about is
whether the resulting outline still carries what the intent planned into it —
`structure.synthesise`'s no-regression test, from both sides.

There are three refusals, not one, and each was found by building a corpus
rather than by reasoning about the code:

* a candidate that **carries less** than the authored outline — the one the
  design predicted, and the one `worldloom validate` is blind to;
* a candidate that carries enough **in more sections** — `compiler.compose` caps
  components by size class, and a ``medium`` `cfo_variance_memo` compiles to
  exactly its cap of eight with no headroom at all;
* a candidate that **argues the document differently** — `compiler.grammar` says
  an executive summary contains a summary and a working note contains no
  decision, and a synthesised `executive_summary` that lost its summary section
  took the whole PPTX render down.

Three groups of tests, in order of what they would catch:

1. **The mechanism refuses.** The unit tests below drive `synthesise` against
   hand-built catalogues where the right answer is known, one per refusal.
2. **The mechanism is not decorative.** A knob that falls back on almost every
   document is a knob nobody should ship, and only a measurement says which one
   this is. `test_the_shipped_close_actually_synthesises` pins the rate on a
   real world with a floor, so a change that quietly turns synthesis into a
   no-op fails here rather than being reported as a success.
3. **The corpus survives it.** A synthesised world compiles, validates, renders
   every format that composes, and carries at least as much in prose as the
   classic one — measured per document, because a total can rise while a
   document falls.

The negative control for group 3 lives in
`test_an_unchecked_synthesis_would_lose_prose_validate_cannot_see`, which is the
finding worth keeping in front of a reader: `validate` does **not** catch this.
Every `outline`-path document carries a supporting-fact appendix citing every
fact it was handed, so `validate.carried_evidence` is satisfied whatever the
prose sections say — the same "two absent things agree" shape that check's own
docstring was written about, one level up. The refusal in `synthesise` is
therefore the only thing standing between a synthesised corpus and a quieter one.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

import pytest

import worldloom  # noqa: F401  — imports every vertical, which is what installs them
from worldloom import documents, recipe, roleseq, structure
from worldloom.retail import RetailWorld
from worldloom.rng import Rng
from worldloom.scenarios import MonthEndClose
from worldloom.structure import CLASSIC, SCALE, StructuralGenome
from worldloom.workforce import HiringRound, PerformanceCycle

ALWAYS = StructuralGenome(synthesis=SCALE)


@dataclass(frozen=True)
class Plan:
    """A minimal `structure.Composable`: `required` here, `kinds`/`scope` there."""

    heading: str
    kinds: tuple[str, ...]
    scope: str = "any"
    required: bool = True


# --- the byte-identity floor ------------------------------------------------


def test_a_classic_genome_still_synthesises_nothing() -> None:
    """The whole compatibility story for this mechanism, in one assertion.

    Every corpus in the repository is built without a genome and CI byte-diffs
    them, so `synthesis` defaulting to zero and `attempts` short-circuiting on it
    is the only reason adding a third mechanism is safe at all.
    """
    assert CLASSIC.synthesis == 0
    assert not CLASSIC.varies
    for index in range(500):
        assert not structure.attempts(f"doc-{index}", CLASSIC)


def test_synthesis_alone_makes_a_genome_vary() -> None:
    """`varies` is the single branch every caller reads; it has to see all three."""
    assert StructuralGenome(synthesis=1).varies
    assert not StructuralGenome(floor=4).varies


@pytest.mark.parametrize("synthesis", [-1, SCALE + 1])
def test_a_genome_refuses_an_out_of_range_synthesis(synthesis: int) -> None:
    with pytest.raises(ValueError, match="per-1000"):
        StructuralGenome(synthesis=synthesis)


def test_attempts_is_a_per_document_draw_at_the_stated_rate() -> None:
    drawn = sum(structure.attempts(f"artifact-{i:04d}", StructuralGenome(synthesis=300))
                for i in range(2000))
    # A per-mille draw over crc32, so this is a proportion rather than a count:
    # anything far from 30% would mean the hash is correlating with the id
    # format, which is the failure that would make one artifact family never
    # synthesise while another always did.
    assert 0.25 < drawn / 2000 < 0.35


def test_whether_a_document_attempts_does_not_move_when_a_section_is_added() -> None:
    """Why `attempts` hashes a pseudo-heading rather than drawing from a stream.

    A stream would make "does this document try synthesis" depend on how many
    sections were masked before the question was asked, so inserting a section
    into a type would change which *other* documents attempted. The NUL-prefixed
    marker cannot collide with a heading, so nothing an author writes can move
    it — the same argument `keep` makes one mechanism over.
    """
    keys = [f"doc-{i}" for i in range(300)]
    genome = StructuralGenome(synthesis=400, omission=500)
    before = [structure.attempts(k, genome) for k in keys]
    assert before == [structure.attempts(k, genome) for k in keys]
    assert structure._SYNTHESIS.startswith("\x00")


# --- the mechanism refuses --------------------------------------------------


def _model(*outlines: tuple[Plan, ...]) -> tuple[object, roleseq.Catalogue]:
    grouped = {"retail": list(outlines)}
    return roleseq.learn_roles(grouped), roleseq.catalogue(grouped)


MEMO = (
    Plan("Position", ("financial.revenue.",), "group"),
    Plan("By business unit", ("financial.revenue.",), "unit"),
)
REVIEW = (
    Plan("What the numbers say", ("financial.revenue.",), "group"),
    Plan("Where it landed", ("financial.revenue.",), "unit"),
)


def _synthesise(authored, model, cat, *, carried, key="k", genome=ALWAYS, **extra):  # type: ignore[no-untyped-def]
    return structure.synthesise(
        authored, key=key, genome=genome, model=model, catalogue=cat,
        tag="retail", rng=Rng(8128).derive(key), carried=carried, **extra,
    )


def test_a_synthesised_outline_may_borrow_another_type_s_headings() -> None:
    """The mechanism doing the thing it exists for.

    Two types with the same two roles and four different headings: the model
    admits the shape, the catalogue can realise it either way, and the document
    that comes out is one no author wrote.
    """
    model, cat = _model(MEMO, REVIEW)
    seen = set()
    for index in range(40):
        got = _synthesise(
            MEMO, model, cat,
            carried=lambda plan: frozenset(s.scope for s in plan),
            key=f"doc-{index}",
        )
        assert got.outcome == "synthesised"
        seen.add(tuple(s.heading for s in got.sections))
    assert len(seen) > 1, "one shape over forty documents is not synthesis"
    assert any("What the numbers say" in shape for shape in seen)


#: The same two roles as `MEMO`, and one fewer fact kind in the first of them.
#: This is what a real refusal looks like: `roleseq`'s symbol is scope plus the
#: *first* kind, so two sections can be the same role and still not carry the
#: same facts — a section handed `("financial.revenue.", "metric.")` and one
#: handed `("financial.revenue.",)` are one symbol and two documents. Every
#: refusal measured on the shipped close was this shape.
THIN = (
    Plan("Headline", ("financial.revenue.",), "group"),
    Plan("Where it landed", ("financial.revenue.",), "unit"),
)
RICH = (
    Plan("Position", ("financial.revenue.", "metric."), "group"),
    Plan("By business unit", ("financial.revenue.",), "unit"),
)


def test_an_outline_that_would_carry_less_is_refused_and_the_authored_one_used() -> None:
    """The check the whole mechanism rests on.

    The model admits the authored *shape* — the roles are identical, so
    `require` is satisfied and a candidate is found at the authored length —
    and the only sections the catalogue can realise it with are about one fact
    kind where the author's were about two. `require` cannot see that, which is
    precisely why it is a hint and the coverage test is the decision.
    """
    model, cat = _model(THIN)
    got = _synthesise(
        RICH, model, cat,
        carried=lambda plan: frozenset(kind for s in plan for kind in s.kinds),
    )
    assert got.outcome == "uncovered"
    assert got.sections == RICH


def test_a_model_with_nothing_to_say_reports_no_shape_rather_than_refusing() -> None:
    """The two fallbacks are different facts and are reported as different facts.

    `uncovered` means the model offered shapes and the intent rejected them;
    `no_shape` means it offered none. Collapsing them would hide the case where
    a corpus is falling back because its fleet is too small to splice, which is
    a statement about the world rather than about the check.
    """
    lone = (Plan("Solo", ("close.",)),)
    model, cat = _model(lone)
    got = _synthesise(
        MEMO, model, cat, carried=lambda plan: frozenset({"f"}),
    )
    assert got.outcome == "no_shape"
    assert got.sections == MEMO


def test_a_bigger_document_is_refused_even_when_it_carries_more() -> None:
    """The size rule, which `compose` would otherwise discover at render time.

    `compiler.compose` caps components by size class from the outlines
    `documents.py` ships, and a ``medium`` `cfo_variance_memo` compiles to
    exactly its cap of eight. A synthesised outline with one more speaking
    section is an artifact `compose` refuses — which `worldloom validate` does
    not notice, because it does not compose, and which takes `worldloom
    diversity` and the PPTX and PDF renderers down when they do. Measured before
    this rule existed: three of six variance memos on a six-period build.
    """
    long_form = (*MEMO, Plan("Outlook", ("close.",), "any"))
    model, cat = _model(MEMO, long_form)
    got = _synthesise(
        MEMO, model, cat,
        # Everything speaks, so a three-section shape carries strictly more and
        # would pass the coverage test on its own.
        carried=lambda plan: frozenset(s.heading for s in plan),
    )
    assert got.outcome in {"synthesised", "outsized"}
    assert len(got.sections) <= len(MEMO)


def test_a_shape_that_argues_the_document_differently_is_refused() -> None:
    """The caller's structural veto, which is where the type's grammar lives.

    `compiler.grammar` says an executive summary must contain a component
    playing ``summary`` and a working note may not contain one playing
    ``decision``. Those are claims about documents rather than about outlines,
    so `synthesise` takes them as a callback and refuses on them rather than
    modelling them — see `documents.synthesised`, which supplies the real one.
    """
    model, cat = _model(MEMO, REVIEW)
    got = _synthesise(
        MEMO, model, cat,
        carried=lambda plan: frozenset(s.scope for s in plan),
        grammatical=lambda plan: False,
    )
    assert got.outcome == "ungrammatical"
    assert got.sections == MEMO


def test_omission_is_applied_before_the_coverage_test_and_not_after() -> None:
    """The three mechanisms compose, so what is checked is what gets compiled.

    A candidate drawn at length three and then stripped to two by omission must
    be judged as the two-section document it will become. Checking the drawn
    outline instead would vouch for a document nobody compiles.
    """
    optional = Plan("Appendix", ("financial.revenue.",), "any", required=False)
    model, cat = _model(MEMO, REVIEW, (*MEMO, optional))
    genome = StructuralGenome(synthesis=SCALE, omission=SCALE)
    for index in range(30):
        got = _synthesise(
            MEMO, model, cat,
            carried=lambda plan: frozenset(s.scope for s in plan),
            key=f"doc-{index}", genome=genome,
        )
        assert all(s.required for s in got.sections), got.sections


def test_a_document_s_shape_does_not_depend_on_its_neighbours() -> None:
    """The per-outline stream, which `roleseq.outlines` asks its callers for.

    `adjacency.synthesise` and `roleseq.realise` both backtrack, so they consume
    a number of draws that depends on which candidates they happened to shuffle
    to the front. Drawing every document from one stream would make document N's
    shape a function of how hard document N−1 was to find, and inserting one
    outline into the examples would then reshuffle every document after it.
    Deriving per key means the answer is the same whatever order they are asked
    in, and whatever else was asked first.
    """
    model, cat = _model(MEMO, REVIEW)
    carried = lambda plan: frozenset(s.scope for s in plan)  # noqa: E731
    keys = [f"doc-{i}" for i in range(20)]
    forwards = {k: _synthesise(MEMO, model, cat, carried=carried, key=k).sections for k in keys}
    backwards = {
        k: _synthesise(MEMO, model, cat, carried=carried, key=k).sections
        for k in reversed(keys)
    }
    assert forwards == backwards


# --- the recipe -------------------------------------------------------------


def test_a_synthesis_genome_rides_the_recipe() -> None:
    stored = recipe.with_structure({}, StructuralGenome(synthesis=250, omission=100))
    assert stored[recipe.STRUCTURE_KEY]["synthesis"] == 250
    assert recipe.structure_of(stored) == StructuralGenome(synthesis=250, omission=100)


def test_an_omission_only_recipe_gains_no_synthesis_line() -> None:
    """Byte-stability for every corpus built before this existed.

    A key written unconditionally puts a new line into the recipe of every
    already-built omission corpus for a value that changes nothing about it, and
    the recipe is diffed. Absent has to mean off, on the way out as well as in.
    """
    stored = recipe.with_structure({}, StructuralGenome(omission=400))
    assert "synthesis" not in stored[recipe.STRUCTURE_KEY]
    assert recipe.structure_of(stored).synthesis == 0


def test_a_recipe_written_before_synthesis_existed_reads_as_classic() -> None:
    dated = {recipe.STRUCTURE_KEY: {"omission": 400, "floor": 1, "variant_bias": 0}}
    assert recipe.structure_of(dated) == StructuralGenome(omission=400)


# --- against a real world ---------------------------------------------------


@pytest.fixture(scope="module")
def close():  # type: ignore[no-untyped-def]
    """Two closes with the paperwork a company has as well as what it produces.

    Policies, a hiring round and a performance cycle are here because synthesis
    learns from *the outlines this world's own plan issues* — a bare close plans
    seven documents over five outlines, which is a fleet too small to recombine
    and would measure the fixture rather than the mechanism. Two periods rather
    than one because a one-period world barely reaches a refusal at all, and a
    rate with no refusals in it is not a reading.
    """
    world = RetailWorld(seed=8128, policies="core").build()
    for period in ("2026-03", "2026-04"):
        world = (
            world.run(MonthEndClose(
                period=period, include_operational_incident=period == "2026-03",
            ))
            .run(HiringRound(period=period, count=2))
            .run(PerformanceCycle(period=period, pairs=2))
        )
    return world


def _with(world, genome):  # type: ignore[no-untyped-def]
    return world.extend(recipe=recipe.with_structure(world.recipe, genome)).compile()


def _shapes(world) -> set[tuple[str, ...]]:  # type: ignore[no-untyped-def]
    """What the corpus actually renders: the visible headings of each document."""
    return {
        tuple(s.heading for s in ir.sections if not s.hidden and s.table is None)
        for ir in world.artifact_irs
    }


def _prose_coverage(world) -> dict[str, int]:  # type: ignore[no-untyped-def]
    """Per intent, how many of its required facts reach a *prose* section.

    Prose rather than `ir.fact_ids()`, and that is the whole point of the
    measurement: `fact_ids()` counts the supporting-fact appendix, which carries
    everything the intent was handed whatever the sections say, so it cannot
    distinguish a document that argues its figures from one that files them.
    """
    by_intent = {ir.intent_id: ir for ir in world.artifact_irs}
    out = {}
    for intent in world.artifact_intents:
        ir = by_intent.get(intent.id)
        if ir is None:
            continue
        visible = {
            f for s in ir.sections if not s.hidden and s.table is None for f in s.fact_ids
        }
        out[intent.id] = len([f for f in intent.required_fact_ids if f in visible])
    return out


def test_the_shipped_close_actually_synthesises(close) -> None:  # type: ignore[no-untyped-def]
    """The rate, because a mechanism that falls back almost always is decorative.

    Measured on this fixture at the time of writing: 43 outline decisions, 38
    synthesised (88%), with 3 refused as ungrammatical and 2 finding no shape at
    all; 29 distinct rendered shapes becoming 33. On the six-period,
    eight-division corpus the wave was proved against it is 192 of 215 (89.3%) —
    12 no shape, 10 ungrammatical, 1 outsized — and 40 distinct shapes become 62.

    A floor rather than an equality, because the fleet a world issues is what
    decides this and adding a document type legitimately moves it. What must not
    move is the order of magnitude: a rate that collapses means synthesis has
    stopped happening and the mechanism is a no-op wearing a knob.
    """
    outcomes: Counter[str] = Counter()
    real = documents.synthesised

    def spy(*args, **kwargs):  # type: ignore[no-untyped-def]
        result = real(*args, **kwargs)
        outcomes[result.outcome] += 1
        return result

    documents.synthesised = spy
    try:
        _with(close, ALWAYS)
    finally:
        documents.synthesised = real

    attempted = sum(outcomes.values())
    assert attempted > 30, outcomes
    assert outcomes["synthesised"] / attempted >= 0.65, outcomes


def test_a_synthesised_corpus_renders_shapes_the_authored_one_cannot(close) -> None:  # type: ignore[no-untyped-def]
    classic, synthesised = _with(close, CLASSIC), _with(close, ALWAYS)
    assert len(_shapes(synthesised)) > len(_shapes(classic))
    assert _shapes(synthesised) - _shapes(classic)


def test_a_synthesised_corpus_validates_and_loses_no_document_its_prose(close) -> None:  # type: ignore[no-untyped-def]
    """The promise `synthesise` makes, checked per document rather than in total.

    Per document because a total can rise while a document falls, and a memo
    that stopped arguing its own division's figures is not compensated for by a
    policy that gained a clause.
    """
    classic, synthesised = _with(close, CLASSIC), _with(close, ALWAYS)
    assert synthesised.validate().ok, synthesised.validate().violations[:5]

    before, after = _prose_coverage(classic), _prose_coverage(synthesised)
    assert set(before) == set(after)
    worse = {k: (before[k], after[k]) for k in before if after[k] < before[k]}
    assert not worse, worse


def test_a_synthesised_corpus_argues_every_document_the_way_its_type_does(close) -> None:  # type: ignore[no-untyped-def]
    """Why every format still renders, stated as the invariant rather than the symptom.

    `compose` reads a document as an ordered sequence of semantic roles and
    checks it against the type's grammar, its size-class cap and the component
    registry. Holding that sequence identical to the authored one means every
    check it runs sees what it saw before, so a synthesised corpus cannot become
    unrenderable — an argument, rather than a list of the checks that happen to
    exist today.
    """
    classic, synthesised = _with(close, CLASSIC), _with(close, ALWAYS)
    before = {ir.intent_id: [s.semantic_role for s in ir.sections] for ir in classic.artifact_irs}
    after = {ir.intent_id: [s.semantic_role for s in ir.sections] for ir in synthesised.artifact_irs}
    assert before == after


def test_a_synthesised_corpus_renders_the_formats_that_compose(close) -> None:  # type: ignore[no-untyped-def]
    """The end-to-end statement of the test above, and the one that caught it.

    PPTX, PDF and DOCX go through `compiler.compose`; Markdown and the bundle
    formats do not. Before the grammar veto existed a synthesised
    `executive_summary` lost its summary section and `render("pptx")` raised
    `RenderError` on a corpus `worldloom validate` had just called coherent —
    which is the whole reason this test renders rather than validating.
    """
    rendered = _with(close, ALWAYS).render("pptx", "pdf", "docx")
    assert rendered.artifacts


def test_a_synthesised_corpus_replays_from_its_own_recipe(close) -> None:  # type: ignore[no-untyped-def]
    """The genome is on the recipe, so a rebuild reproduces the same documents.

    This is the corpus-level statement of what `test_a_document_s_shape_does_
    not_depend_on_its_neighbours` says per document, and it is the one CI
    enforces by byte-diffing a regenerated corpus.
    """
    first, second = _with(close, ALWAYS), _with(close, ALWAYS)
    assert [ir.model_dump() for ir in first.artifact_irs] == [
        ir.model_dump() for ir in second.artifact_irs
    ]


def test_an_unchecked_synthesis_would_lose_prose_validate_cannot_see(close) -> None:  # type: ignore[no-untyped-def]
    """The negative control, and the honest reason the check is not redundant.

    Replaces the acceptance test with "take the first shape the model offers"
    and asserts two things at once: documents *do* lose prose, and `validate`
    reports the corpus clean anyway. The second half is why this test exists in
    this file rather than as a note somewhere — every `outline`-path document
    carries a supporting-fact appendix citing every fact it was handed, so
    `carried_evidence`, `compiled_evidence` and `unreachable_answer` are all
    satisfied by a document that files its figures instead of arguing them.

    Measured on the three-period corpus this wave was proved against: 11 of 82
    documents carried fewer facts in prose than the classic build, including all
    three CFO variance memos and both incident RCAs, with `validate` reporting
    26,297 checks and no violations either way.
    """
    def reckless(authored, *, key, genome, model, catalogue, tag, rng, carried, grammatical):  # type: ignore[no-untyped-def]
        require = sorted({roleseq.symbol(s, tag=tag) for s in authored if carried((s,))})
        for offset in rng.derive("length").shuffled(structure.LENGTHS):
            length = len(authored) + offset
            if length < 1:
                continue
            for candidate in roleseq.outlines(
                model, catalogue, rng=rng.derive(f"length/{length}"), tag=tag,
                length=length, count=structure.DRAWS, require=require,
            ):
                return structure.Synthesis(
                    sections=structure.derive(candidate, key=key, genome=genome),
                    outcome="synthesised",
                )
        return structure.Synthesis(sections=tuple(authored), outcome="no_shape")

    checked = _with(close, ALWAYS)
    real = structure.synthesise
    structure.synthesise = reckless
    try:
        unchecked = _with(close, ALWAYS)
    finally:
        structure.synthesise = real

    before, after = _prose_coverage(_with(close, CLASSIC)), _prose_coverage(unchecked)
    worse = [k for k in before if after[k] < before[k]]
    assert worse, (
        "the negative control stopped reproducing the failure: either the model"
        " got tighter or the fixture stopped being able to splice, and either"
        " way the coverage test above is no longer being proved by anything"
    )
    # And nothing downstream notices, which is the finding.
    assert unchecked.validate().ok
    assert not [k for k in before if _prose_coverage(checked)[k] < before[k]]
