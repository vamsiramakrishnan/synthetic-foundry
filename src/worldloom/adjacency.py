"""Sequence synthesis from examples: novel wholes made only of familiar parts.

This repository authors 42 document outlines by hand (``documents._OUTLINES``),
which hold 33 distinct heading sequences between them. Both numbers are ceilings
on structural variety, and neither moves without somebody typing another outline.
The two obvious ways past that ceiling are both wrong. A generator that orders
sections freely produces documents no company would issue — an RCA that opens on
"Appendix", a policy whose responsibilities precede its purpose. A generator
restricted to the 33 produces nothing that was not already authored.

The middle path is Merrell's model synthesis and Gumin's WaveFunctionCollapse:
accept a sequence exactly when **every local window of it already occurred
somewhere in the examples**. Plausibility comes from the examples rather than
from a rule an author had to state, and novelty comes from the seams — two
outlines that share a heading can be spliced there, and the splice is locally
indistinguishable from both parents.

That is the mechanism. What it yields depends entirely on how much local context
the examples share, and this module reports on that rather than assuming it. On
the 42 shipped outlines at order 2, the measurement is:

    84 distinct headings across 108 heading occurrences
    63 distinct bigrams, 33 start windows, 33 end windows
    34 sequences admitted in total (all lengths), of which 1 is novel

One. The heading vocabulary is very nearly disjoint across document types — only
seven headings appear in more than one outline, and ten of those appearances are
the policy family's shared "Purpose and scope"/"Responsibilities" pair, which
sits inside a single fixed shape — so there are almost no seams to splice at.
The mechanism is not at fault and neither is the order: this is a *vocabulary*
result. Loosening to order 1 does not fix it, it only stops the model meaning
anything — 47 billion admitted sequences at length 6, essentially all of them
nonsense. What recombination actually needs is section headings drawn from a
shared vocabulary of section *roles* rather than 84 bespoke strings. Adding the
thirteen ``_OUTLINE_VARIANTS`` is the same argument measured from the other
side: 55 examples, 45 admitted sequences, 5 of them novel.

Two consequences shape the API:

``admits`` is the primitive, not ``synthesise``.
    The check is worth more than the generator here. It is what lets a caller
    take shapes from anywhere — an author, a variant table, a mutation, another
    module in this wave — and ask whether the examples vouch for them.
``synthesise`` returns ``None`` rather than raising.
    A caller sampling a thousand outlines under constraints needs a "no" it can
    count, not an exception it has to catch per draw. On a model this tight the
    "no" is the common answer, and it has to be cheap.

Determinism, because CI regenerates every corpus from its ledger and diffs it
byte-for-byte: every draw goes through ``rng.Rng``, and every candidate set is
**sorted before it is shuffled**. Windows live in a ``frozenset`` for cheap
membership, and every place this module iterates one it sorts first — a
frozenset's iteration order is a function of the hash seed, and this repository
has shipped that bug before.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .rng import Rng

Window = tuple[str, ...]


@dataclass(frozen=True)
class Adjacency:
    """What the examples vouch for: which windows, which openings, which closes.

    Deliberately not a probability model. A Markov chain over the same windows
    would carry transition counts and let a caller sample "typically", which
    sounds strictly better and is not: the shipped outlines contribute 66
    bigram occurrences over 63 distinct bigrams, so every count is 1 or 2 and
    the weights would be noise dressed as frequency. A generator leaning on
    them would reproduce whichever outlines happen to be longest, which is the
    monotony this exists to break. A set says only "an author wrote this
    somewhere", which is the whole of what 66 observations support.
    """

    order: int
    """Window size. 2 = bigrams: each element is constrained by its predecessor."""
    windows: frozenset[Window]
    """Every window of *order* consecutive elements seen in any example.

    Also holds whole examples shorter than *order*, which is why the tuples are
    not all the same length. Dropping a short example instead would have been
    the tidier type and the wrong behaviour: six of the 42 shipped outlines have
    a single heading, and a model that cannot readmit them fails the one
    property this module actually promises. ``compiler.diversity._ngrams``
    already settled this question the same way for the same reason."""
    starts: frozenset[Window]
    """Windows that opened an example. A sequence must begin with one."""
    ends: frozenset[Window]
    """Windows that closed an example. A sequence must end with one.

    Start and end are separate constraints rather than a consequence of the
    windows, because without them the model is a walk on a graph and walks do
    not know where documents begin. Learned from these very outlines, an
    unbounded walk happily emits an outline that opens on "Regulator
    engagement" and stops after "Timeline"."""
    alphabet: tuple[str, ...]
    """Every element seen, sorted — the sort is what makes this safe to iterate."""


def learn(examples: Sequence[Sequence[str]], *, order: int = 2) -> Adjacency:
    """Read the local structure out of *examples*.

    Empty examples are skipped rather than refused: a caller passing a batch of
    document outlines through will meet a type whose outline is not authored
    yet, and an empty sequence teaches nothing either way. It is not, however,
    harmless to record — an empty tuple in ``starts`` and ``ends`` would make
    ``admits`` vouch for a document with no sections at all.
    """
    if order < 1:
        raise ValueError(f"order must be at least 1, got {order}")

    windows: set[Window] = set()
    starts: set[Window] = set()
    ends: set[Window] = set()
    alphabet: set[str] = set()

    for example in examples:
        sequence = tuple(example)
        if not sequence:
            continue
        alphabet.update(sequence)
        if len(sequence) < order:
            # Shorter than one window: the example is its own window, and it
            # both opens and closes itself. See `Adjacency.windows`.
            windows.add(sequence)
            starts.add(sequence)
            ends.add(sequence)
            continue
        example_windows = [
            sequence[i : i + order] for i in range(len(sequence) - order + 1)
        ]
        windows.update(example_windows)
        starts.add(example_windows[0])
        ends.add(example_windows[-1])

    return Adjacency(
        order=order,
        windows=frozenset(windows),
        starts=frozenset(starts),
        ends=frozenset(ends),
        alphabet=tuple(sorted(alphabet)),
    )


def admits(model: Adjacency, sequence: Sequence[str]) -> bool:
    """Do the examples vouch for *sequence*?

    Three conditions, all of them local: it opens with a window that opened an
    example, closes with one that closed an example, and every window in
    between occurred somewhere. Nothing here looks at the sequence as a whole,
    which is the property that makes novel sequences possible at all.

    An empty sequence is never admitted. A document with no sections is not a
    shape this model has an opinion about; it is the absence of one.
    """
    candidate = tuple(sequence)
    if not candidate:
        return False
    if len(candidate) < model.order:
        # Too short to have a window of its own, so it can only be admitted as
        # a whole — and it must have been seen opening *and* closing, since it
        # does both here.
        return (
            candidate in model.windows
            and candidate in model.starts
            and candidate in model.ends
        )
    windows = [
        candidate[i : i + model.order]
        for i in range(len(candidate) - model.order + 1)
    ]
    if windows[0] not in model.starts or windows[-1] not in model.ends:
        return False
    return all(window in model.windows for window in windows)


def synthesise(
    model: Adjacency,
    rng: Rng,
    *,
    length: int,
    require: Sequence[str] = (),
    forbid: Sequence[str] = (),
) -> tuple[str, ...] | None:
    """A sequence of *length* elements that *model* admits, or ``None``.

    ``require`` names elements that must appear somewhere in the result;
    ``forbid`` names elements that must not appear at all. ``None`` means no
    such sequence exists — it is a complete answer, not a give-up, because the
    search below is exhaustive.

    **Backtracking, not WFC's propagation.** WaveFunctionCollapse collapses one
    cell at a time and propagates constraints without ever undoing a choice,
    and Karth & Smith are explicit that its characteristic failure — painting
    itself into a corner and emitting a contradiction — is a consequence of
    that greed rather than of the model. That trade is right at image scale,
    where the search tree is astronomically large and a restart is cheap. Here
    a sequence is one to seven elements over 63 windows, so the exponential
    nobody can afford on a texture costs microseconds, and inheriting the greedy
    version's failure mode would mean answering "no" to satisfiable asks — which
    a caller counting refusals would read as the model being tighter than it is.

    The result is *an* admitted sequence, not a uniform draw from the admitted
    set: candidates are shuffled per node, so shapes reachable through more
    partial prefixes come up more often. Sampling admitted sequences uniformly
    means counting completions per state, which is a different function; this
    one is honest about being a randomised search rather than a sampler.
    """
    if length < 1:
        # Not an error. Callers draw a length from a distribution or from a
        # density profile, and a zero-length outline is a request nothing can
        # satisfy — the same kind of "no" as an impossible `require`.
        return None

    forbidden = frozenset(forbid)
    required = frozenset(require)
    if required & forbidden:
        return None
    if not required <= frozenset(model.alphabet):
        # An element nothing ever wrote cannot be worked in.
        return None
    if len(required) > length:
        return None

    def permitted(window: Window) -> bool:
        return not any(element in forbidden for element in window)

    if length < model.order:
        # Below one window's width, only a whole short window can serve, and it
        # has to have been seen both opening and closing (see `admits`).
        candidates = sorted(
            window
            for window in model.windows
            if len(window) == length
            and window in model.starts
            and window in model.ends
            and permitted(window)
            and required <= frozenset(window)
        )
        return rng.choice(candidates) if candidates else None

    # Successors of each (order-1)-element tail. Built once; every list is
    # sorted, because it is iterated and drawn from, and it was assembled by
    # walking a frozenset.
    successors: dict[Window, list[str]] = {}
    for window in model.windows:
        if len(window) != model.order:
            continue  # a short whole example cannot be extended from
        successors.setdefault(window[:-1], []).append(window[-1])
    for tail in successors:
        successors[tail].sort()

    # States proven unsatisfiable, so a wide search does not re-walk them. The
    # future of a search depends on exactly three things — the tail that
    # constrains the next element, how many slots are left, and which required
    # elements are still missing — so a state that failed once fails always.
    # This is what makes the "cheap no" true rather than aspirational: without
    # it, a caller sampling a thousand outlines under an unsatisfiable `require`
    # pays a full exponential walk per refusal.
    #
    # The tail is enough context even for the closing check, which looks at the
    # last *order* elements rather than the last order-1. When a state has
    # `remaining` slots left, the closing window overlaps the prefix by
    # `order - remaining` elements, which is at most order-1 while any slot is
    # left to fill — so it lies inside the tail. Keying on the tail alone would
    # be wrong if `remaining` were ever 0 here, and it never is: the terminal
    # case returns above without consulting the memo.
    failed: set[tuple[Window, int, frozenset[str]]] = set()

    def tail_of(prefix: list[str]) -> Window:
        # `prefix[-(order - 1):]` is wrong at order 1 — a slice of `[-0:]` is
        # the whole list, not the empty one — and order 1 is a legitimate model
        # (elements constrained only by the alphabet and the ends).
        return tuple(prefix[len(prefix) - (model.order - 1) :])

    def extend(prefix: list[str], missing: frozenset[str]) -> tuple[str, ...] | None:
        if len(prefix) == length:
            if tuple(prefix[-model.order :]) in model.ends and not missing:
                return tuple(prefix)
            return None
        remaining = length - len(prefix)
        if len(missing) > remaining:
            return None  # cannot fit what is still required
        tail = tail_of(prefix)
        state = (tail, remaining, missing)
        if state in failed:
            return None
        for element in rng.shuffled(successors.get(tail, ())):
            if element in forbidden:
                continue
            prefix.append(element)
            found = extend(prefix, missing - {element})
            prefix.pop()
            if found is not None:
                return found
        failed.add(state)
        return None

    for start in rng.shuffled(sorted(
        window
        for window in model.starts
        if len(window) == model.order and permitted(window)
    )):
        found = extend(list(start), required - frozenset(start))
        if found is not None:
            return found
    return None


__all__ = ["Adjacency", "admits", "learn", "synthesise"]
