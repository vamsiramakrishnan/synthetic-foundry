"""Outline derivation: a document's shape as a function of a genome.

The measured problem. The shipped fleet renders 988 documents from 42 artifact
types carrying 108 authored sections between them — and when this module was
written those 108 sections resolved to **33 distinct heading sequences**,
because `documents._OUTLINES` is a constant per type. Every close pack in a
corpus is the same skeleton with different numbers. (The 33 is now 42:
`policies.py` gave each policy area its own vocabulary rather than ten types
sharing one pair. That closed the *authoring* gap and leaves this module's
argument exactly where it was — 42 authored shapes is still a constant per
type, and still one skeleton per close pack.) `documents._OUTLINE_VARIANTS` was the first answer to this and
it is the right shape, but it is hand-authored: three of forty-two types have
alternatives, because writing a fourth outline for a type is a person's afternoon
and there are 42 types times however many tenants.

So the outline stops being retrieved and starts being *derived*. Three
mechanisms, all deterministic:

**Variant choice** — unchanged from `_variant_for`, moved here so that the
mechanisms compose in one place, plus a genome-level bias so that two tenants
built from the same engine do not land on the same variant for the same document.

**Omission.** A document emits a *subset* of its type's optional sections rather
than all of them. This is swarm testing (Groce, Zhang, Eide, Chen & Regehr,
ISSTA 2012) applied to documents instead of test programs: their finding was that
a swarm of configurations each *omitting* some features found 42% more distinct
compiler crashes than one hand-tuned configuration including all of them, because
features compete for room and some actively suppress the behaviours you are
looking for. The same is true of a memo. A document that always contains its
"Standing exposure" section never tests whether a retriever can answer a question
whose evidence is only sometimes present — and a corpus in which every document
of a type has the same five headings teaches a retriever the headings.

The arithmetic is the point: a type with four optional sections has 16 shapes
rather than 1, and 42 types with a handful of optional sections each have more
distinct shapes than a person will ever author by hand.

**Synthesis.** The two above rearrange what an author already wrote for *this*
type. Synthesis draws a shape the fleet vouches for and that no author wrote at
all: `roleseq` learns which section *roles* follow which across every outline
one company issues, and `roleseq.outlines` emits sequences that model admits and
realises them back into real sections from a catalogue. Measured on a
three-period retail close carrying policies, hiring and reviews (25 outlines, 27
symbols, 31 windows) the model admits 321 sequences of at most eight roles,
**299 of which no shipped outline is** — where omission over the same 25
outlines reaches only subsets of what is already there.

Two things make synthesis different in kind from the other two, and both are
constraints rather than features:

* **A draw from `roleseq` is a proposal, not a result.** Omission provably
  cannot break a document — `keep` refuses to drop a required section, and that
  one line is its whole safety argument. A synthesised outline has no such
  argument available, because it is assembled from sections written for *other*
  documents. Three things have to be checked before one may be used, and each
  was found by building a corpus rather than by reasoning about the code: it
  must carry at least what the intent planned into the authored outline; it must
  do so in no more sections, because `compiler.compose` caps a document's
  components by its size class and the shipped variance memo sits exactly on its
  cap; and it must argue the document the way its type argues it, because
  `compiler.grammar` says an executive summary contains a summary. `synthesise`
  refuses on all three and falls back to the authored outline, and **none of the
  three is caught by `worldloom validate`** — the first hides behind the
  supporting-fact appendix, the other two behind the fact that validation does
  not compose.
* **It needs a stream, where the other two need a hash.** `roleseq.outlines`
  backtracks, so unlike `keep` it cannot be a pure function of one section's
  heading. What it can be — and is — is a function of *this document's* derived
  stream, so document N's shape does not depend on how hard document N−1 was to
  find. `roleseq.outlines`' own docstring makes that argument; `attempts` and
  the `rng` parameter of `synthesise` are this module honouring it.

**Why this is not an `Rng` stream.** Each section's fate is decided by a hash of
*that section's own heading* together with the document's id, not by successive
draws from a stream. A stream would work and would be wrong for a reason that has
bitten this repo before (see `rng.py`'s own docstring): drawing n masks in order
means that inserting a section into a type reshuffles the fate of every section
after it, in every already-minted document, at every seed. Hashing each heading
independently means a new section changes only its own presence. It also makes
the mask a pure function of the *set* of sections rather than their order.

**Byte-identity.** `CLASSIC` — omission, variant bias and synthesis all zero —
reproduces today's outline for every type, and every section the engine ships is
`required` until something declares otherwise, so a corpus built without a
structural genome is unchanged down to the byte. That is not a courtesy; CI
regenerates every corpus from its ledger and diffs it, so anything else here
would be a repo-wide failure.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, TypeVar
from zlib import crc32

from . import roleseq

if TYPE_CHECKING:  # pragma: no cover - import cycle only matters to a type checker
    from .adjacency import Adjacency
    from .rng import Rng


class Section(Protocol):
    """What this module needs of a section, which is deliberately almost nothing.

    A `Protocol` rather than an import of `documents.SectionPlan` because
    `documents` is the module that will import *this* one, and because the same
    derivation has to run over `doctypes.SectionSpec` on the authoring side
    before a `SectionPlan` exists. Two heading-bearing types, one derivation.
    """

    @property
    def heading(self) -> str: ...

    @property
    def required(self) -> bool: ...


class Composable(Section, roleseq.Section, Protocol):
    """A section both mechanisms can read: `required` here, `kinds`/`scope` there.

    Spelled as the intersection rather than as a fourth protocol with five
    properties, so that the moment either half moves this one moves with it.
    `documents.SectionPlan` and `doctypes.SectionSpec` both satisfy it — which is
    the same pair `Section` above and `roleseq.Section` are each written for, and
    the reason neither module imports the other's concrete type.
    """


S = TypeVar("S", bound=Section)
C = TypeVar("C", bound=Composable)

#: The resolution of `StructuralGenome.omission`. Per-mille rather than percent
#: because the useful range here is narrow and low — a type with five optional
#: sections at 30% omission emits its full outline only 17% of the time, which
#: is already a different document type rather than a varied one. Per-mille lets
#: a caller ask for "one document in twenty drops a section" without a float,
#: and floats in a determinism-critical path are a category of bug this repo
#: does not need to invite.
SCALE = 1000


@dataclass(frozen=True)
class StructuralGenome:
    """The numbers a document's shape is derived from.

    Small on purpose. Every field here has to be recorded in the recipe, replayed
    exactly, and defended in a diff — so a knob earns its place by changing the
    shape of documents a reader would notice, not by existing.
    """

    omission: int = 0
    """Per-`SCALE` chance that any one *optional* section is left out of any one
    document. ``0`` is the engine's historical behaviour exactly: every section
    of the chosen outline, every time."""

    floor: int = 1
    """The fewest sections a derived outline may carry. Omission restores
    sections in outline order until this is met, so a genome can be aggressive
    without ever producing an empty document."""

    variant_bias: int = 0
    """Rotates variant selection. Two corpora built from the same engine with
    different biases disagree about which variant each document gets, which is
    what stops a mosaic of tenants sharing one shape vocabulary — the measured
    45% cross-tenant overlap between the two retail tenants is mostly this."""

    synthesis: int = 0
    """Per-`SCALE` chance that any one document's outline is *synthesised* rather
    than taken from its type.

    Per-mille and per-document, matching `omission`, so the two read the same way
    on a command line. It is a chance of *attempting* rather than of succeeding:
    a synthesised outline that would carry fewer of the intent's facts than the
    authored one is refused and the authored outline used, so the fraction of
    documents that actually change is always at or below this. `attempts` draws
    it; `synthesise` decides."""

    def __post_init__(self) -> None:
        if not 0 <= self.omission <= SCALE:
            raise ValueError(
                f"omission is per-{SCALE} and must be in [0, {SCALE}], not {self.omission}"
            )
        if self.floor < 1:
            raise ValueError(f"floor must be at least 1, not {self.floor}")
        if self.variant_bias < 0:
            raise ValueError(f"variant_bias must not be negative, not {self.variant_bias}")
        if not 0 <= self.synthesis <= SCALE:
            raise ValueError(
                f"synthesis is per-{SCALE} and must be in [0, {SCALE}], not {self.synthesis}"
            )

    @property
    def varies(self) -> bool:
        """Whether this genome can produce anything the engine would not have.

        The one place a caller should branch on, rather than testing
        ``omission == 0`` at four call sites and getting one of them wrong.
        """
        return self.omission > 0 or self.variant_bias > 0 or self.synthesis > 0


#: The null genome. Named, rather than left as `StructuralGenome()` at call
#: sites, because "the corpus was built classic" is a thing a recipe says and a
#: reader of a diff needs to recognise.
CLASSIC = StructuralGenome()


def _draw(key: str, heading: str) -> int:
    """A stable per-`SCALE` draw for one section of one document.

    ``crc32`` rather than ``hash()``: Python randomises string hashing per
    process, so ``hash()`` here would make a corpus irreproducible between runs
    — the same reason `ids.content_key` exists. ``crc32`` is defined
    byte-for-byte and needs no seeding.

    The NUL separator matters. Without it, a document keyed ``"a"`` with a
    heading ``"bc"`` and one keyed ``"ab"`` with a heading ``"c"`` hash
    identically, and two unrelated sections share a fate for no reason anybody
    stated. NUL cannot occur in either an id or a heading.
    """
    return crc32(f"{key}\x00{heading}".encode()) % SCALE


def keep(key: str, section: Section, genome: StructuralGenome) -> bool:
    """Whether *section* survives into the document identified by *key*.

    Required sections always survive. This is what makes omission safe to turn
    on globally: a type that has not been annotated has no optional sections, so
    a genome cannot silently strip the only section that carried a required
    fact and turn a valid document into one that trips
    ``required_fact_omitted`` at narration time.
    """
    if section.required:
        return True
    return _draw(key, section.heading) >= genome.omission


def derive(
    outline: Sequence[S],
    *,
    key: str,
    genome: StructuralGenome = CLASSIC,
) -> tuple[S, ...]:
    """The sections the document identified by *key* actually gets.

    Order is preserved — omission decides *whether* a section appears, never
    where. Re-ordering headings is variety a reader can see and a retriever
    cannot, and `documents._OUTLINE_VARIANTS` already says why the repo does not
    do it: the variants there differ in what each section is *for*, not in the
    order of the same sections.

    The floor is applied by restoring dropped sections in outline order, so the
    result is a pure function of the set of sections and the key — not of the
    order in which the mask happened to be evaluated.
    """
    if not outline:
        return ()
    if not genome.varies:
        # The byte-identity path, taken by every corpus built without a genome.
        # Written as an early return rather than falling through the mask with
        # `omission == 0`, because `_draw(...) >= 0` is true for every section
        # and the two are equivalent — but only by an argument, and an argument
        # is a worse guarantee than a branch when CI diffs bytes.
        return tuple(outline)

    kept = [section for section in outline if keep(key, section, genome)]
    if len(kept) >= genome.floor:
        return tuple(kept)

    # Under the floor. Restore in outline order until it is met — the dropped
    # sections are put back in the order their author wrote them, so the
    # restored document is one the author would recognise rather than whichever
    # sections happened to hash highest.
    survivors = {id(section) for section in kept}
    restored = list(kept)
    for section in outline:
        if len(restored) >= genome.floor:
            break
        if id(section) not in survivors:
            restored.append(section)
    return tuple(sorted(restored, key=lambda s: _position(outline, s)))


def _position(outline: Sequence[S], section: S) -> int:
    """Where *section* sits in *outline*, by identity.

    By identity rather than by equality: two sections of one outline may
    legitimately share a heading at different scopes (`doctypes.lint` allows it
    and says why), and `index()` would then put the second one back in the
    first's place.
    """
    for position, candidate in enumerate(outline):
        if candidate is section:
            return position
    raise ValueError(f"section {section.heading!r} is not in this outline")


def choose(
    variants: Sequence[Sequence[S]],
    *,
    key: str,
    genome: StructuralGenome = CLASSIC,
) -> Sequence[S]:
    """Which of a type's authored variants the document identified by *key* gets.

    Hashed, not cycled. `documents._variant_for` records the measurement behind
    that at length and it is worth not losing: an ordinal cycle aliases whenever
    the count of documents per period shares a factor with the variant count,
    which at the shipped shape pinned every business unit to one variant in
    every period at every seed — 1 distinct variant per unit across five seeds,
    and one variant rendered 0 times in 15 documents. Ids never repeat, so a
    hash of the id has no period to alias with.
    """
    if not variants:
        raise ValueError("choose() needs at least one variant")
    index = crc32(key.encode()) + genome.variant_bias
    return variants[index % len(variants)]


#: The pseudo-heading `attempts` hashes against, so that whether a document tries
#: synthesis is independent of every real section's fate. NUL cannot occur in a
#: heading (`_draw` relies on the same fact for its separator), so this collides
#: with nothing an author can write, and adding, renaming or removing a section
#: therefore cannot change which documents attempt synthesis. That is the same
#: property the per-heading hash buys for omission, one level up.
_SYNTHESIS = "\x00synthesis"

#: How far a synthesised outline's length may sit from the authored one's, as
#: offsets tried in a per-document shuffled order.
#:
#: Not `(0,)`, and the reason is a measurement rather than a taste. On a
#: six-period, eight-division retail corpus (215 documents attempting synthesis)
#: drawing only at the authored length produced **62 distinct outlines** at an
#: 87.9% success rate; `(0, 1, 2)` produced **87** at 89.3%. A draw of the
#: authored length with the authored roles required has almost nowhere to go —
#: the sequence is nearly pinned to something an author wrote and only the
#: headings move. The spare position is where the recombination lives. It costs
#: nothing at the far end because a section handed no fact is dropped before
#: compilation and the size rule refuses the rest.
#:
#: Shuffled rather than tried in order, and that is the difference between a
#: genome and a preference: `(0, 1, 2)` tried in order would make every document
#: that can hold its authored length keep it, and the extra position would only
#: ever appear on the documents that failed — which is a rule about failure
#: wearing the costume of a rule about shape.
LENGTHS = (0, 1, 2)

#: How many shapes to draw at each length before trying the next one.
#:
#: The one constant here that is a straight cost/quality trade, so it was
#: measured as one. On the corpus above, at 4/8/16/32 draws: **79.5 / 85.1 /
#: 89.3 / 92.6%** of documents synthesised, for a compile of 0.94 / 1.16 / 1.34 /
#: 1.93 seconds against 0.71 classic. The knee is at 16 and that is what this is:
#: past it the curve buys three points for half a second again, and a knob that
#: doubles a build's compile time to move a diversity figure is a knob people
#: turn off. Every one of those seconds is paid only when synthesis is on —
#: `attempts` short-circuits on a classic genome before any of this runs.
DRAWS = 16


def attempts(key: str, genome: StructuralGenome) -> bool:
    """Whether the document identified by *key* tries synthesis at all.

    Separate from `synthesise` rather than folded into it, because the caller
    has to build a role model and a catalogue to call `synthesise` and this
    decides whether that work is worth doing. It is also the honest denominator:
    the fallback rate a caller reports is refusals over *attempts*, and a rate
    computed over every document would be measuring the genome's per-mille
    rather than the mechanism.
    """
    if genome.synthesis <= 0:
        return False
    return _draw(key, _SYNTHESIS) < genome.synthesis


@dataclass(frozen=True)
class Synthesis:
    """What `synthesise` did, and the sections to use either way.

    `outcome` is carried beside the sections rather than logged or counted here,
    because "how often did synthesis refuse" is a measurement about a *corpus*
    and this function only ever sees one document. A mechanism that falls back
    almost always is decorative, and the only way anybody finds that out is if
    the refusal is a value a caller can tally.
    """

    sections: tuple[Composable, ...]
    outcome: str
    """One of:

    ``synthesised``  a drawn shape was admitted, realised, and passed every test
    ``no_shape``     the model admitted nothing realisable at any length tried
    ``uncovered``    shapes existed, and every one carried less than the authored
                     outline does — the refusal this whole function exists for
    ``outsized``     shapes existed and carried enough, in more sections than the
                     document is allowed to have
    ``ungrammatical`` shapes existed and the caller's own structural veto refused
                     every one

    Four fallbacks rather than one, because they are four different facts about a
    corpus. ``no_shape`` says the fleet is too small to splice — a statement
    about the world. ``uncovered`` says the model and the intent disagree.
    ``outsized`` says the splice was a bigger document than this one is.
    ``ungrammatical`` says it was a differently-argued one. Collapsing them would
    leave a reader of the rate unable to tell a mechanism that is not wired from
    a world that has nothing to wire it to.
    """


def synthesise(
    authored: Sequence[C],
    *,
    key: str,
    genome: StructuralGenome,
    model: Adjacency,
    catalogue: roleseq.Catalogue,
    tag: str,
    rng: Rng,
    carried: Callable[[Sequence[C]], frozenset[str]],
    grammatical: Callable[[Sequence[C]], bool] = lambda _outline: True,
) -> Synthesis:
    """A synthesised outline for *key*, or *authored* when none will do.

    *carried* is the whole safety argument, and it is a callback because this
    module knows nothing about facts: given an outline, it returns the ids of the
    intent's required facts that some section of that outline would be assigned.
    Everything below is derived from it and none of it is optional.

    **A candidate must carry at least as much, in no more sections.** Two tests,
    and the corpus needs both:

    *At least as much* — ``carried(candidate) >= carried(authored)``. The
    stronger test, that a candidate carry *every* fact the intent requires, was
    measured and is the wrong one: the authored outlines do not pass it either. A
    document's facts are assigned per section by scope and kind, several shipped
    types are handed facts no section of them claims, and those facts reach the
    page through the supporting-fact appendix instead. Demanding total coverage
    would refuse synthesis for a defect that predates it and belongs to the
    outline the engine shipped, while this test cannot make any document worse
    than the one it would otherwise have compiled — which is exactly the promise
    a knob has to make to be safe to turn on.

    *In no more sections* — a candidate may not have more fact-carrying sections
    than the authored outline does. Sections that carry nothing are dropped
    before compilation, so this is precisely "no more sections in the compiled
    document", and it is not a matter of taste. `compiler.compose` caps a
    document's components by its size class, and the caps are set from the
    outlines `documents.py` ships: a ``medium`` `cfo_variance_memo` compiles to
    exactly its cap of eight, with **zero** headroom. Without this test, three of
    the six variance memos on a six-period build drew a seventh section and
    became artifacts `compose` refuses — invisible to `worldloom validate`, which
    does not compose, and fatal to `worldloom diversity` and to the PPTX and PDF
    renderers, which do. The rule is also the honest modelling claim: synthesis
    recombines a document, it does not inflate one.

    **And it must still be a document of its type.** *grammatical* is the
    caller's own structural veto, a third callback rather than a rule spelled out
    here because what makes a document *of its type* is `compiler.grammar`'s
    business: an executive summary must contain a component playing ``summary``,
    a working note may not contain one playing ``decision``, an RCA states its
    chronology before its explanation. Those are authored claims about documents,
    and a synthesised outline that breaks one surfaces as a `RenderError` out of
    PPTX rather than as anything `worldloom validate` reports — measured before
    this veto existed, a synthesised `executive_summary` lost its summary section
    and took the whole deck render down with it.

    **The authored roles are required of the draw.** Every symbol of an authored
    section that carries something is passed to `roleseq.outlines` as `require`,
    which is a hint rather than a fourth check — the tests above are still what
    decide. Without it the search wanders: measured on the six-period corpus,
    68.8% of documents synthesised against 89.3% with it, and 73 distinct
    outlines against 87. A shape that cannot state the group position is not a
    cheaper variant of this document, it is a different document, and there is no
    reason to spend a draw on it.

    *rng* must already be this document's own stream. `roleseq.outlines`
    backtracks and consumes a variable number of draws, so a stream shared
    between documents makes each one's shape depend on how hard its predecessor
    was to find — see that function's docstring, and `rng.py`'s, which is where
    this repository first paid for it.

    Omission is applied to every candidate before it is tested, so the three
    mechanisms compose rather than layering: what is checked for coverage is the
    outline that will actually be compiled, not a longer one it was drawn from.
    """
    want = carried(authored)
    speaking = sum(1 for section in authored if carried((section,)))
    require = sorted({
        roleseq.symbol(section, tag=tag)
        for section in authored
        if carried((section,))
    })
    base = len(authored)
    # The reported refusal is *how far the best candidate got*, not the reason
    # the last one failed. Last-wins would make the outcome depend on the order
    # the lengths happened to shuffle into, which is a number nobody could read:
    # a corpus reporting `no_shape` for a document whose model offered a shape it
    # merely mis-sized would send a reader to the wrong half of the problem.
    _FURTHEST = ("no_shape", "uncovered", "outsized", "ungrammatical")
    refusal = "no_shape"

    def reached(reason: str) -> None:
        nonlocal refusal
        if _FURTHEST.index(reason) > _FURTHEST.index(refusal):
            refusal = reason

    for offset in rng.derive("length").shuffled(LENGTHS):
        length = base + offset
        if length < 1:
            continue
        for candidate in roleseq.outlines(
            model,
            catalogue,
            rng=rng.derive(f"length/{length}"),
            tag=tag,
            length=length,
            count=DRAWS,
            require=require,
        ):
            shaped = derive(candidate, key=key, genome=genome)
            if carried(shaped) < want:
                reached("uncovered")
                continue
            if sum(1 for section in shaped if carried((section,))) > speaking:
                reached("outsized")
                continue
            if not grammatical(shaped):
                reached("ungrammatical")
                continue
            return Synthesis(sections=shaped, outcome="synthesised")
    return Synthesis(sections=tuple(authored), outcome=refusal)


def space(outline: Sequence[Section], genome: StructuralGenome = CLASSIC) -> int:
    """How many distinct shapes *outline* can take under *genome*.

    The number this module exists to raise, and the one to quote in a diff.
    Counts subsets of the optional sections that clear the floor — an exact
    count rather than ``2 ** optional``, because the floor genuinely removes
    some of them and a headline figure that ignores its own constraint is the
    kind of number that gets quoted back later.

    **Omission only, and deliberately.** Synthesis is not counted here and could
    not honestly be: how many shapes it reaches is a property of the *fleet a
    company issues* — the role model and the catalogue built from every one of
    its outlines — and this function is handed one outline. Folding a
    world-dependent number into a per-outline one would produce exactly the kind
    of headline figure the paragraph above is warning about. `roleseq.admitted`
    is where that count lives, at the scope where it means something.
    """
    if not genome.varies or not outline:
        return 1 if outline else 0
    required = sum(1 for section in outline if section.required)
    optional = len(outline) - required
    if genome.omission == 0:
        return 1
    total = 0
    for dropped in range(optional + 1):
        if len(outline) - dropped < genome.floor:
            continue
        total += _binomial(optional, dropped)
    return total


def _binomial(n: int, k: int) -> int:
    """``n choose k``, by the multiplicative formula.

    Not `math.comb` only because this file is read by people checking the
    headline diversity figure, and a two-line derivation they can verify beats
    a stdlib call they have to trust — the same reason `dispersion.py` spells
    out the radical inverse.
    """
    if k < 0 or k > n:
        return 0
    result = 1
    for step in range(k):
        result = result * (n - step) // (step + 1)
    return result
