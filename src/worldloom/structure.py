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

So the outline stops being retrieved and starts being *derived*. Two mechanisms,
both cheap, both deterministic:

**Variant choice** — unchanged from `_variant_for`, moved here so that the two
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

**Why this is not an `Rng` stream.** Each section's fate is decided by a hash of
*that section's own heading* together with the document's id, not by successive
draws from a stream. A stream would work and would be wrong for a reason that has
bitten this repo before (see `rng.py`'s own docstring): drawing n masks in order
means that inserting a section into a type reshuffles the fate of every section
after it, in every already-minted document, at every seed. Hashing each heading
independently means a new section changes only its own presence. It also makes
the mask a pure function of the *set* of sections rather than their order.

**Byte-identity.** `CLASSIC` — omission zero — reproduces today's outline for
every type, and every section the engine ships is `required` until something
declares otherwise, so a corpus built without a structural genome is unchanged
down to the byte. That is not a courtesy; CI regenerates every corpus from its
ledger and diffs it, so anything else here would be a repo-wide failure.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Protocol, TypeVar
from zlib import crc32


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


S = TypeVar("S", bound=Section)

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

    def __post_init__(self) -> None:
        if not 0 <= self.omission <= SCALE:
            raise ValueError(
                f"omission is per-{SCALE} and must be in [0, {SCALE}], not {self.omission}"
            )
        if self.floor < 1:
            raise ValueError(f"floor must be at least 1, not {self.floor}")
        if self.variant_bias < 0:
            raise ValueError(f"variant_bias must not be negative, not {self.variant_bias}")

    @property
    def varies(self) -> bool:
        """Whether this genome can produce anything the engine would not have.

        The one place a caller should branch on, rather than testing
        ``omission == 0`` at four call sites and getting one of them wrong.
        """
        return self.omission > 0 or self.variant_bias > 0


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


def space(outline: Sequence[Section], genome: StructuralGenome = CLASSIC) -> int:
    """How many distinct shapes *outline* can take under *genome*.

    The number this module exists to raise, and the one to quote in a diff.
    Counts subsets of the optional sections that clear the floor — an exact
    count rather than ``2 ** optional``, because the floor genuinely removes
    some of them and a headline figure that ignores its own constraint is the
    kind of number that gets quoted back later.
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
