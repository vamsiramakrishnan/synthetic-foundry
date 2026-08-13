"""Sequence synthesis over section *roles*, because heading text has no seams.

``adjacency.py`` is correct and its own docstring records why it does not help:
applied to the 42 shipped outlines it admitted **34 sequences, of which 1 was
novel**. The cause is vocabulary, not algorithm — 84 distinct headings over 108
occurrences at the time it was written, only 7 of them appearing in more than one
outline, and 10 of those occurrences being the policy family's fixed pair. Two outlines can only be
spliced where they share an element, and these outlines share almost nothing.

So this module stops asking what a section is *called* and asks what it is
*for*. A ``SectionPlan`` already carries ``kinds`` (the fact-kind prefixes it may
draw on) and ``scope`` (``group``/``unit``/``any``), and between them those decide
which facts the section can carry — which is the thing the retrieval half of this
project cares about, and the thing two documents can genuinely have in common
even when no author ever typed the same heading twice.

**The projection is the whole design decision**, so it was measured rather than
argued. Order 2, the 42 shipped outlines, sequences of length 1 to 8, admitted
counts by exhaustive enumeration, and "shuffles" is the fraction of non-identity
permutations of the *training* outlines that the model waves through — a
projection that admits every reordering of a real document has stopped meaning
anything about order, which is the failure mode at the coarse end:

    projection      symbols  windows  admitted  novel   shuffles admitted
    heading             102       72        43      1        0 / 1,736
    kinds                70       62       113     76        0 / 1,723
    scope+kinds          71       63        84     47        0 / 1,726
    kind                 53       58       264    229        0 / 1,723
    scope+kind  ←        55       59       195    159        0 / 1,726
    domain               14       26     1,088  1,060       48 / 913    5.3%
    scope+domain         17       29       835    806       48 / 925    5.2%
    scope                 3        7       275    262       44 / 158   27.9%

The ``heading`` row is the control, and it reads 102/72/43/1 rather than the
84/63/34/1 ``adjacency``'s docstring publishes because this wave gave ten policies
their own headings — eighteen more strings, nine more admitted sequences, and
**still one novel one**, which is the finding restated: heading text does not
recombine however much of it there is. Everything below that row is untouched by
the rename, because a policy's kinds and scope did not move.

``scope+kind`` — scope, then the first kind with its trailing dot stripped, e.g.
``unit:financial.revenue`` — is the pick, and the two boundaries either side of it
are what choose it rather than a preference for the middle:

*The coarse boundary is between ``kind`` and ``domain``, and the shuffle column
finds it.* ``domain`` collapses 102 headings to 14 symbols and admits 5.3% of the
reorderings of documents somebody actually wrote; ``scope`` alone admits 27.9%.
Those models will happily emit a policy whose responsibilities precede its
purpose, which is the exact failure ``adjacency`` was built to avoid. Everything
at ``kind`` granularity or finer admits **zero** shuffles.

*The fine boundary is between ``kind`` and ``scope+kind``, and dropping scope
costs more than the extra 70 sequences are worth.* ``cfo_variance_memo`` opens
``Position`` (group) then ``By business unit`` (unit) over identical kinds. Without
scope those are one symbol, so the model learns a **self-loop** on
``financial.revenue`` and most of the jump from 195 to 264 is that loop firing
repeatedly — sequences that say "state the group position, then state it again".
Scope is one bit and it is the bit that distinguishes the two sections in this
repository's most-read memo.

``kinds`` (the full tuple) is the "too fine" end the exercise predicted: 70
symbols against 102 headings is barely a collapse at all, and it buys 76 novel
sequences against 159.

**Cross-vertical splices are refused by tagging the symbol**, not by partitioning
the examples into four models and not by handing the other verticals' symbols to
``synthesise`` as ``forbid``. All three are equivalent on the adjacency; tagging
wins on two counts. It keeps *one* model, so the policy and workforce families —
which every company has, whatever engine built it — are learned once and appear
under every tag, and a policy section can therefore splice into a retail close
*and* into a bank's committee pack while the close and the pack stay apart. And
it makes the guard structural rather than optional: a caller who forgets to pass
``forbid`` gets a cross-vertical splice, whereas a caller who forgets a tag gets a
``KeyError`` from the catalogue. Measured at ``scope+kind``: **412 sequences are
admitted by the pooled model, 217 of them are refused** because no single company
issues all their sections, leaving the 195 above. Per vertical those 195 shapes
account for 334 (vertical, shape) pairs — retail 146, banking 89, insurance 50,
procurement 49 — of which 267 are novel.

**What the projection still cannot see, stated because it shows in the output.**
Every section of every HR policy carries the prefix ``policy.hr.``, so leave and
remote work are one role at every projection here — the full kind tuple included
— and 36 of the 159 novel shapes therefore splice two policies of one function
into a document a company would issue as two. The fix is a finer kind
(``policy.hr.leave.`` against ``policy.hr.remote_work.``), which lives in
``policies.py`` and ``factkinds.py``; ``tests/test_roleseq.py`` fences the
limitation so that closing it is noticed rather than silently improving a number.
The other 123 novel shapes do not touch a policy section.

**Why lengths are bounded and realisation is not.** The policy family contributes
five genuine self-loops (``any:policy.finance`` follows itself: purpose, then
responsibilities, both over the same kind), so the admitted *symbol* set is
infinite and any count of it is a count at some length. ``admitted`` therefore
takes ``max_length`` and says so. Realisation needs no such bound, because
``realise`` may not use one heading twice: a symbol appearing k times needs k
distinct sections projecting to it, and the catalogue runs out. The bound on real
documents is the vocabulary, which is the honest place for it.

Determinism, since CI regenerates corpora from their ledgers and byte-diffs them:
every draw goes through ``rng.Rng``, every candidate list is sorted before it is
shuffled, and every set is sorted before it is iterated.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal, Protocol

from .adjacency import Adjacency, admits, learn, synthesise
from .rng import Rng

Symbol = str
"""A section's role, canonically spelled. See ``symbol``."""


class Section(Protocol):
    """What this module needs of a section, which is three read-only fields.

    A ``Protocol`` rather than an import of ``documents.SectionPlan``, for the
    reason ``structure.Section`` gives: ``documents`` is 2,600 lines that reach
    the world builder, the renderers and the compiler, and a library that learns
    sequences has no business dragging that in. It also means the same
    projection runs over ``doctypes.SectionSpec`` on the authoring side, where a
    ``SectionPlan`` does not exist yet — a pack author can ask whether the
    outline they are proposing is one the fleet vouches for.
    """

    @property
    def heading(self) -> str: ...

    @property
    def kinds(self) -> tuple[str, ...]: ...

    @property
    def scope(self) -> str: ...


Projection = Literal[
    "heading",
    "kinds",
    "scope+kinds",
    "kind",
    "scope+kind",
    "domain",
    "scope+domain",
    "scope",
]
"""The projections measured in this module's docstring, all eight of them.

``heading`` is in the vocabulary despite being the thing this module exists to
replace, and that is deliberate: it is the control the rest of the table is read
against, and ``tests/test_roleseq.py`` re-derives it rather than quoting it. A
measurement whose control cannot be recomputed is a claim.
"""

DEFAULT: Projection = "scope+kind"
"""The projection the table above picks. Named so call sites do not repeat it."""

_TAG = "|"
"""Separates a vertical tag from the role it qualifies.

A separator rather than a tuple key because ``adjacency`` learns over ``str`` and
widening it to a generic element type would be a change to a module that is
correct and shipped. Refused inside a tag rather than escaped — an escape needs
an unescape, and nothing here ever reads a tag back out.
"""

_SCOPE = ":"
"""Separates scope from kind. Cannot occur in a fact kind (``factkinds`` keys are
dotted lowercase), so a symbol parses unambiguously if anybody ever needs to."""


def _kind(section: Section) -> str:
    """The first fact-kind prefix, without its trailing dot.

    The trailing dot is how ``documents`` writes a *prefix* — ``financial.revenue.``
    matches ``financial.revenue.actual`` and ``.budget`` — and stripping it here is
    presentation only. Kept out of the symbol because a projection is read by
    people comparing it against the fact ledger, and ``unit:financial.revenue.``
    reads as a typo.

    ``routine_notice`` carries ``kinds=("",)``, one section in the whole fleet with
    no kind at all. It projects to the empty string, which is a legitimate symbol:
    "a section about nothing in particular" is exactly what that notice is, and
    silently dropping it would remove a real start and end window.
    """
    return section.kinds[0].rstrip(".") if section.kinds else ""


def symbol(section: Section, *, projection: Projection = DEFAULT, tag: str = "") -> Symbol:
    """*section*'s role under *projection*, qualified by *tag*.

    *tag* names the kind of company that issues the document — the vertical, in
    this repository's vocabulary. Two sections with the same role under different
    tags are different symbols and can never be adjacent, which is the whole of
    the cross-vertical guard.
    """
    if _TAG in tag:
        raise ValueError(f"tag {tag!r} may not contain {_TAG!r}, which separates it from the role")
    prefix = f"{tag}{_TAG}" if tag else ""
    kind = _kind(section)
    if projection == "heading":
        role = section.heading
    elif projection == "kinds":
        role = "+".join(k.rstrip(".") for k in section.kinds)
    elif projection == "scope+kinds":
        role = f"{section.scope}{_SCOPE}" + "+".join(k.rstrip(".") for k in section.kinds)
    elif projection == "kind":
        role = kind
    elif projection == "scope+kind":
        role = f"{section.scope}{_SCOPE}{kind}"
    elif projection == "domain":
        role = kind.split(".")[0]
    elif projection == "scope+domain":
        role = f"{section.scope}{_SCOPE}{kind.split('.')[0]}"
    elif projection == "scope":
        role = section.scope
    else:
        raise ValueError(f"unknown projection {projection!r}")
    return f"{prefix}{role}"


def project(
    outline: Sequence[Section], *, projection: Projection = DEFAULT, tag: str = ""
) -> tuple[Symbol, ...]:
    """*outline* as a symbol sequence — what ``adjacency`` actually learns over."""
    return tuple(symbol(section, projection=projection, tag=tag) for section in outline)


#: Outlines, grouped by the tag of the company that issues them. A family every
#: company has — policies, hiring, performance — belongs under *every* tag, and
#: that repetition is the point rather than a redundancy to factor out: it is how
#: a policy section becomes spliceable into four verticals' documents while those
#: verticals stay apart from each other.
Examples = Mapping[str, Sequence[Sequence[Section]]]


def learn_roles(
    examples: Examples, *, order: int = 2, projection: Projection = DEFAULT
) -> Adjacency:
    """Learn adjacency over the roles of *examples*, tag-qualified.

    Takes a tag→outlines mapping rather than the flat sequence ``adjacency.learn``
    takes, and the difference is not convenience. A flat sequence would make the
    cross-vertical guard something a caller opts into after the fact — and the
    last wave's measurement found a splice joining a retail close commentary to a
    banking committee summary, locally real at every window and issued by no
    company that exists. Requiring the tag up front means the model cannot be
    built without an answer to "whose document is this".

    Iteration is over ``sorted(examples)`` even though ``adjacency.learn`` folds
    everything into sets: the sets it builds are order-insensitive today, and a
    module that relies on that is one refactor away from a corpus that differs
    between runs. This repository has shipped that bug.
    """
    sequences = [
        project(outline, projection=projection, tag=tag)
        for tag in sorted(examples)
        for outline in examples[tag]
    ]
    return learn(sequences, order=order)


@dataclass(frozen=True)
class Catalogue:
    """Symbol → the sections that project to it. What turns a shape into prose.

    Not a plain ``dict`` because the projection has to travel with it: realising a
    ``scope+kind`` sequence against a ``domain`` catalogue looks up symbols that
    happen not to be there and reports "no realisation", which is a wrong answer
    rather than an error. Holding both together makes the mismatch checkable.
    """

    projection: Projection
    sections: Mapping[Symbol, tuple[Section, ...]]
    """Sorted per symbol, and the sort is what makes drawing from it reproducible.

    Two sections may legitimately share a heading at different scopes — the same
    thing ``structure._position`` refuses to resolve by equality — so the key is
    the whole triple rather than the heading alone, and ties fall back to the
    order the caller supplied, which is a ``Mapping``'s insertion order and
    therefore stable.
    """

    def for_symbol(self, sym: Symbol) -> tuple[Section, ...]:
        """Every section that projects to *sym*. Empty for an unknown symbol."""
        return self.sections.get(sym, ())

    @property
    def symbols(self) -> tuple[Symbol, ...]:
        """Every symbol with at least one section, sorted."""
        return tuple(sorted(self.sections))


def _sort_key(section: Section) -> tuple[str, str, tuple[str, ...]]:
    return (section.heading, section.scope, tuple(section.kinds))


def catalogue(examples: Examples, *, projection: Projection = DEFAULT) -> Catalogue:
    """Index *examples* by symbol, so a symbol sequence can be realised.

    Built from the same mapping ``learn_roles`` reads, and that is not an
    accident worth factoring away: a catalogue assembled from a different corpus
    than the model would realise sequences the model never vouched for, in
    headings the model never saw.
    """
    indexed: dict[Symbol, list[Section]] = {}
    for tag in sorted(examples):
        for outline in examples[tag]:
            for section in outline:
                indexed.setdefault(symbol(section, projection=projection, tag=tag), []).append(
                    section
                )
    return Catalogue(
        projection=projection,
        sections=MappingProxyType(
            {sym: tuple(sorted(sections, key=_sort_key)) for sym, sections in sorted(indexed.items())}
        ),
    )


def realise(
    sequence: Sequence[Symbol], cat: Catalogue, *, rng: Rng
) -> tuple[Section, ...] | None:
    """Sections for *sequence*, or ``None`` if no assignment of headings exists.

    *rng* is required rather than defaulted, which the sketch for this function
    did not have. A default would be a hidden global stream, and the one thing
    every module in this repository must not do is decide for its caller which
    stream a draw comes from — see ``outlines`` for what the caller owes here.

    **No heading twice in one outline.** A document with two sections called
    "Responsibilities" is not a document, and the policy family's self-loop makes
    that reachable rather than hypothetical: ``any:policy.finance`` follows itself,
    so a length-3 sequence asks for three finance-policy sections and there are
    only ever two headings to give it.

    **Backtracking, not greedy.** Taking the first free section per symbol is
    wrong for the reason ``adjacency.synthesise`` spells out at more length:
    picking "Responsibilities" for an early symbol that could also have taken
    "Purpose and scope" can leave a later symbol with nothing, and a caller
    counting refusals would read that as the model being tighter than it is. The
    search is over at most eight positions with a handful of candidates each.
    """
    wanted = tuple(sequence)
    if not wanted:
        # Consistent with `adjacency.admits`: a document with no sections is the
        # absence of a shape, not a shape this module can produce.
        return None

    used: set[str] = set()
    chosen: list[Section] = []

    def place(index: int) -> bool:
        if index == len(wanted):
            return True
        candidates = [s for s in cat.for_symbol(wanted[index]) if s.heading not in used]
        for section in rng.shuffled(candidates):
            used.add(section.heading)
            chosen.append(section)
            if place(index + 1):
                return True
            chosen.pop()
            used.discard(section.heading)
        return False

    return tuple(chosen) if place(0) else None


def symbols_for(model: Adjacency, tag: str) -> tuple[Symbol, ...]:
    """Every symbol in *model* carrying *tag*, sorted."""
    prefix = f"{tag}{_TAG}"
    return tuple(sym for sym in model.alphabet if sym.startswith(prefix))


def outlines(
    model: Adjacency,
    cat: Catalogue,
    *,
    rng: Rng,
    tag: str,
    length: int,
    count: int,
    require: Sequence[Symbol] = (),
) -> tuple[tuple[Section, ...], ...]:
    """Up to *count* realised outlines of *length* sections, all issued by *tag*.

    **One derived stream per outline, and this is not tidiness.**
    ``adjacency.synthesise`` backtracks, so it consumes a number of draws that
    depends on which candidates it happened to shuffle to the front — and
    ``realise`` backtracks too. Drawing every outline from one stream therefore
    means outline 7 depends on how hard outline 6 was to find, so adding a single
    window to the examples reshuffles every outline after the first one it
    touches. Deriving by index makes each outline a function of its own index and
    the seed, which is the same argument ``rng.py``'s docstring makes about
    generators sharing a stream, one level down.

    Duplicates are dropped rather than retried, so the result may be shorter than
    *count*: on a model this tight the same shape genuinely comes up twice, and a
    retry loop would either spin on an exhausted model or need a bound nobody can
    justify. A short result is a true statement about the model.
    """
    forbidden = tuple(sym for sym in model.alphabet if sym not in frozenset(symbols_for(model, tag)))
    produced: list[tuple[Section, ...]] = []
    seen: set[tuple[str, ...]] = set()
    for index in range(count):
        stream = rng.derive(f"{tag}/{index}")
        shape = synthesise(model, stream, length=length, require=require, forbid=forbidden)
        if shape is None:
            continue
        realised = realise(shape, cat, rng=stream)
        if realised is None:
            continue
        headings = tuple(section.heading for section in realised)
        if headings in seen:
            continue
        seen.add(headings)
        produced.append(realised)
    return tuple(produced)


def admitted(model: Adjacency, *, max_length: int) -> tuple[tuple[Symbol, ...], ...]:
    """Every sequence of at most *max_length* symbols that *model* admits, sorted.

    Exhaustive, by forward closure over prefixes rather than by generate-and-test
    — the space over 55 symbols at length 8 is 10^13 and the admitted set is 412.

    *max_length* is required, with no default, because on a role model there is no
    honest one: the policy family's self-loop makes the admitted set infinite, and
    a function that silently picked a bound would publish a number whose meaning
    lived in this file rather than at the call site. The docstring's table is at
    8, which is the longest shipped outline plus two — enough for a splice to
    exceed both its parents, which is where ``adjacency``'s own single novel
    sequence lives (it is length 7; a bound of 6 reports 0 novel and would have
    contradicted a published number).
    """
    if max_length < 1:
        return ()

    successors: dict[tuple[Symbol, ...], list[Symbol]] = {}
    for window in model.windows:
        if len(window) == model.order:
            successors.setdefault(window[:-1], []).append(window[-1])
    for tail in successors:
        successors[tail].sort()

    found: set[tuple[Symbol, ...]] = set()
    # Whole examples shorter than one window admit only as themselves — the case
    # `adjacency.admits` handles separately, and six of the 42 shipped outlines
    # are one section long, so dropping it would lose a sixth of the corpus.
    for window in sorted(model.windows):
        if len(window) < model.order and window in model.starts and window in model.ends:
            if len(window) <= max_length:
                found.add(window)

    frontier = sorted(w for w in model.starts if len(w) == model.order and len(w) <= max_length)
    seen = set(frontier)
    for window in frontier:
        if window in model.ends:
            found.add(window)
    while frontier:
        following: list[tuple[Symbol, ...]] = []
        for prefix in frontier:
            if len(prefix) >= max_length:
                continue
            tail = prefix[len(prefix) - (model.order - 1) :]
            for element in successors.get(tail, ()):
                candidate = prefix + (element,)
                if candidate in seen:
                    continue
                seen.add(candidate)
                if candidate[-model.order :] in model.ends:
                    found.add(candidate)
                following.append(candidate)
        frontier = sorted(following)
    return tuple(sorted(found))


def refused(
    model: Adjacency, tags: Iterable[str], sequences: Iterable[Sequence[Symbol]]
) -> tuple[tuple[Symbol, ...], ...]:
    """Which of *sequences*, stripped of their tags, no single tag in *tags* admits.

    The cross-vertical guard, measured rather than asserted. Takes untagged
    sequences — the shapes a *pooled* model would admit — and reports the ones
    that survive only by borrowing sections from two companies at once. 217 of
    412 at the shipped projection.
    """
    ordered = sorted(tags)
    out: list[tuple[Symbol, ...]] = []
    for sequence in sequences:
        shape = tuple(sequence)
        if not any(
            admits(model, tuple(f"{tag}{_TAG}{sym}" for sym in shape)) for tag in ordered
        ):
            out.append(shape)
    return tuple(sorted(out))


def untag(sequence: Sequence[Symbol]) -> tuple[Symbol, ...]:
    """*sequence* with each symbol's tag removed. The inverse ``refused`` consumes."""
    return tuple(sym.split(_TAG, 1)[-1] for sym in sequence)


__all__ = [
    "Catalogue",
    "DEFAULT",
    "Examples",
    "Projection",
    "Section",
    "Symbol",
    "admitted",
    "catalogue",
    "learn_roles",
    "outlines",
    "project",
    "realise",
    "refused",
    "symbol",
    "symbols_for",
    "untag",
]
