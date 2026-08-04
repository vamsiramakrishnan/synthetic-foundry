"""Physics a model derives by asking, instead of physics an engineer typed.

``parameters.py`` is a registry of thirty-seven ranges. That is honest about
what the engine can *read* — a generator contains ``physics.number("retail.
margin.budget", rng)``, and a call site is a closed vocabulary by construction.
But it is not honest as a theory of a world. It says a company is thirty-seven
independent numbers, when the thing that makes a company coherent is that its
numbers are not independent: a business with a fifty-eight per cent gross margin
is one that marks down at a certain cadence and turns inventory at a certain
rate, and if you set the margin without moving those you have not built a
specialty retailer, you have built a grocer with one figure edited.

So this module is the layer above. The registry is not the ceiling — it is the
**socket**. Here the vocabulary is open, and the shape is a graph.

**A node is a question, not a value.** ``org.margin`` is not "0.52". It is
*what gross margin does this business run, and why*, carrying an interval that
represents what is still believed possible. A node with the interval
``[0.20, 0.60]`` has not been answered. One with ``[0.52, 0.58]`` has.

**Answering is Socratic: an answer raises questions.** A model that is told
"specialty apparel" and asked for a margin should not produce a number. It
should say that margin here is not primitive — it falls out of full-price
sell-through, markdown depth, and how many times a year the range turns — and
raise those three as children. The parent narrows only as far as its children
allow. That is the recursion, and ``max_depth`` is how many levels of it a
build wants: two is a sketch, five is a business plan.

**The control is propagation, not a schema.** Every edge carries an invertible
relation, so narrowing runs *both* directions: a child constrained from below
pushes its parent up, and a parent narrowed by a sibling's evidence squeezes
the child. ``propagate`` is arc consistency (AC-3) over interval domains, run
to a fixpoint. A world whose answers cannot all be true is one where some
node's interval empties, and that emptying names the chain that caused it. This
is what "which combinations are logical and which aren't" looks like when it is
computed rather than listed: nobody enumerates the illegal pairs, they fall out
of the relations.

**Only leaves bind.** A leaf may name a terminal in ``parameters.DEFAULTS``,
and ``resolve`` turns the graph into overrides for it. A leaf that binds to
nothing is reported, loudly, as an *unbound* finding — it is a parameter the
model found the world needs and the engine cannot yet read. That is the only
honest way the registry grows: pressure from a world that wanted something,
not an engineer guessing in advance. Silently dropping those would make this
module a decoration on the existing thirty-seven.

**Grounding.** Every answer carries a ``source``. A model with web search can
put a sector statistic behind an interval instead of its priors, and the
corpus can then say what it was calibrated against. The boundary the project
has always kept holds here and is worth restating at the point of temptation:
sector aggregates are priors; a named company's figures are not ours to put in
a fictional corpus. ``review`` cannot tell the difference and does not pretend
to — the field records provenance, it does not launder it.

**Determinism.** Nothing here draws. The graph is a pure function of the
answers accepted into it, the propagation worklist is ordered by key, and
acceptance appends to a ledger that rebuilds the graph exactly — the same
handshake ``compose`` uses, for the same reason: a model is in the loop and a
corpus still has to replay byte-for-byte from what it recorded.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any

from pydantic import Field

from .models import Model
from .parameters import DEFAULTS, Parameters, Span

#: How many levels of sub-question a graph will accept before it refuses to go
#: deeper. Not a performance guard — a depth limit is what stops a model from
#: answering "why?" forever, which it will, because there is always another
#: why. Four is enough for margin to decompose into sell-through, markdown and
#: turns, and for one of those to decompose again.
DEFAULT_MAX_DEPTH = 4

#: A narrowing counts as progress only if it shrinks an interval by more than
#: this, relative to the interval's own scale.
#:
#: Without it, propagation does not terminate. Interval narrowing over floats
#: converges *asymptotically* — a scaling relation can shave a millionth off a
#: bound on every pass, forever, and each pass is a legitimate change that
#: re-enqueues its arcs. This is the standard fix and it is load-bearing, not a
#: tolerance for sloppiness.
_MEANINGFUL = 1e-9


# ---------------------------------------------------------------------------
# Interval algebra
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Interval:
    """A closed range of what is still believed possible.

    Unbounded ends are ``±inf`` rather than ``None``: a relation that produces
    "no information about the upper bound" has to compose with one that does,
    and arithmetic on infinities does that correctly while arithmetic on
    ``None`` needs a special case at every operator.
    """

    low: float
    high: float

    @property
    def empty(self) -> bool:
        return self.low > self.high

    @property
    def width(self) -> float:
        return self.high - self.low if not self.empty else 0.0

    def meet(self, other: Interval) -> Interval:
        """The intersection. May be empty — that is the contradiction signal."""
        return Interval(max(self.low, other.low), min(self.high, other.high))

    def contains(self, other: Interval) -> bool:
        return self.low <= other.low and other.high <= self.high

    def admits(self, other: Interval) -> tuple[bool, str]:
        """Whether *other* lies inside this, allowing for float arithmetic.

        Exact containment is the wrong test and fails immediately in practice:
        a `complements` edge turns a stated 0.65 into a bound of
        0.35000000000000003, and an answer of 0.35 is then refused for
        "widening" the question by one part in 10^16. That rejection is not
        only wrong, it is unactionable — both intervals print as [0.35, 0.45].

        So the tolerance is the same relative one narrowing uses, and the
        message names the end that broke and by how much, because a model
        cannot fix a violation it cannot see.
        """
        slack = _MEANINGFUL * max(1.0, abs(self.low), abs(self.high))
        if other.low < self.low - slack:
            return False, f"its low end is {self.low - other.low:.6g} below the {self.low:.17g} allowed"
        if other.high > self.high + slack:
            return False, f"its high end is {other.high - self.high:.6g} above the {self.high:.17g} allowed"
        return True, ""

    def __mul__(self, other: Interval) -> Interval:
        # All four corner products, because either operand may straddle zero
        # and the extremes are then not at matching corners. Taking low*low and
        # high*high is the classic wrong answer here.
        corners = (
            self.low * other.low, self.low * other.high,
            self.high * other.low, self.high * other.high,
        )
        if any(math.isnan(corner) for corner in corners):
            # ``0 * inf`` is nan, and it arises for real: a `scales` relation
            # whose factor can be zero, applied to a parent nobody has bounded
            # yet. The sound answer is the whole line — the product genuinely
            # could be anything — and a nan would instead poison every
            # comparison downstream while looking like a number.
            return WHOLE
        return Interval(min(corners), max(corners))

    def __truediv__(self, other: Interval) -> Interval:
        if other.low <= 0.0 <= other.high:
            # Dividing by an interval containing zero yields a set with a hole
            # in it, which is not an interval. Returning the whole line is the
            # sound over-approximation: it says nothing, rather than something
            # false.
            return WHOLE
        return self * Interval(1.0 / other.high, 1.0 / other.low)

    def narrowed_by(self, other: Interval) -> bool:
        """Whether meeting with *other* would shrink this meaningfully."""
        after = self.meet(other)
        if after.empty:
            return True
        scale = max(1.0, abs(self.low), abs(self.high))
        if math.isinf(self.width):
            return not math.isinf(after.width) or after.low > self.low or after.high < self.high
        return self.width - after.width > _MEANINGFUL * scale

    def __str__(self) -> str:
        def end(value: float) -> str:
            return "∞" if value == math.inf else "-∞" if value == -math.inf else f"{value:g}"

        return f"[{end(self.low)}, {end(self.high)}]"


WHOLE = Interval(-math.inf, math.inf)


# ---------------------------------------------------------------------------
# Relations
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Relation:
    """How a child's quantity is tied to its parent's.

    Deliberately a tiny closed set. A general expression language here would be
    more expressive and would destroy the only property that matters: every
    relation must be **invertible**, so that evidence discovered at a leaf
    travels back up. A relation that only pushed downward would make this a
    template-expansion tree with extra steps.
    """

    kind: str
    factor: Interval = WHOLE

    def forward(self, parent: Interval) -> Interval:
        """What the parent's belief implies about the child."""
        if self.kind == "free":
            return WHOLE
        if self.kind == "scales":
            return parent * self.factor
        if self.kind == "complements":
            return Interval(1.0 - parent.high, 1.0 - parent.low)
        if self.kind == "at_most":
            return Interval(-math.inf, parent.high)
        raise ValueError(f"unknown relation {self.kind!r}")

    def backward(self, child: Interval) -> Interval:
        """What the child's belief implies about the parent. The whole point."""
        if self.kind == "free":
            return WHOLE
        if self.kind == "scales":
            return child / self.factor
        if self.kind == "complements":
            return Interval(1.0 - child.high, 1.0 - child.low)
        if self.kind == "at_most":
            return Interval(child.low, math.inf)
        raise ValueError(f"unknown relation {self.kind!r}")

    def __str__(self) -> str:
        if self.kind == "scales":
            return f"scales by {self.factor}"
        return {"free": "independent of", "complements": "complements",
                "at_most": "at most"}[self.kind]


KINDS = ("free", "scales", "complements", "at_most")


def relation(kind: str, *, factor_low: float = 1.0, factor_high: float = 1.0) -> Relation:
    if kind not in KINDS:
        raise ValueError(f"unknown relation {kind!r}; expected one of {KINDS}")
    if kind != "scales":
        return Relation(kind)
    if factor_low > factor_high:
        raise ValueError(f"inverted scaling factor [{factor_low}, {factor_high}]")
    return Relation(kind, Interval(factor_low, factor_high))


# ---------------------------------------------------------------------------
# The graph
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Question:
    """One node: what is being asked, what is still possible, and why it is asked."""

    key: str
    asks: str
    """The question, as a question. Not a label — a model given ``org.margin``
    and a range will pick a number in it; a model given *what gross margin does
    this business run, and what would have to be true for it* will reason."""
    unit: str
    domain: Interval
    """What is still believed possible. Narrows as answers arrive; never widens
    — see ``review``'s ``widens_the_question``."""
    depth: int
    parent: str | None = None
    via: Relation = Relation("free")
    because: str = ""
    """Why this question follows from its parent, in a sentence. The record of
    the model's actual reasoning, and the only part of a probe a human reads to
    judge whether the derivation was sound rather than merely consistent."""
    layer: str = ""
    """Which of the graph's named layers this question belongs to. Empty on an
    unlayered probe, and on the root, which precedes every layer."""
    answered: bool = False
    claim: str = ""
    source: str = ""
    binds: str | None = None
    """A terminal in ``parameters.DEFAULTS``, on leaves only. ``None`` on an
    answered leaf is not an oversight — see ``resolve``."""


@dataclass(frozen=True)
class Link:
    """A constraint between two questions that are not parent and child.

    The tree says *why a question was asked*; a link says *what else its answer
    has to agree with*. Those are different claims and keeping them in one
    structure would lose the first: an objective is asked because a title
    exists, and it is separately constrained by the span of the team under that
    title. Collapsing both into "parent" would make ``ancestry`` — the
    reasoning a human reads to judge whether a derivation was sound — into an
    arbitrary path through a constraint web.

    Propagation does not care about the distinction and treats both uniformly,
    which is the point: cross-layer constraints are where a probe stops being a
    decomposition and starts being a model of a world.
    """

    subject: str
    object: str
    via: Relation
    because: str = ""


@dataclass(frozen=True)
class Graph:
    """A premise and everything asked in service of it."""

    premise: str
    questions: Mapping[str, Question]
    max_depth: int = DEFAULT_MAX_DEPTH
    layers: tuple[str, ...] = ()
    """The named levels this probe descends through, outermost first — e.g.
    ``("organisation", "reporting", "titles", "objectives")``.

    Named rather than numbered because a level is a *kind* of question, not a
    distance from the root, and because the names are what let a model know
    what it is being asked for. Empty means unlayered: depth alone orders the
    frontier, which is the right default for a probe that is decomposing one
    quantity rather than descending a structure."""

    links: tuple[Link, ...] = ()

    def __iter__(self) -> Iterable[Question]:
        return iter(self.ordered)

    @property
    def ordered(self) -> tuple[Question, ...]:
        """Every question, by depth then key. The only order anything iterates.

        Insertion order would work today and would make the graph depend on the
        sequence a model happened to answer in, which is exactly the class of
        thing this project's replay guarantee rests on not doing.
        """
        return tuple(sorted(self.questions.values(), key=lambda q: (q.depth, q.key)))

    def children_of(self, key: str) -> tuple[Question, ...]:
        return tuple(q for q in self.ordered if q.parent == key)

    def leaves(self) -> tuple[Question, ...]:
        parents = {q.parent for q in self.questions.values()}
        return tuple(q for q in self.ordered if q.key not in parents)

    def ancestry(self, key: str) -> tuple[Question, ...]:
        """Root-first chain down to *key*, inclusive. The context a model gets."""
        chain: list[Question] = []
        cursor: str | None = key
        while cursor is not None:
            node = self.questions[cursor]
            chain.append(node)
            cursor = node.parent
        return tuple(reversed(chain))


def open_graph(premise: str, roots: Sequence[Question] = (), *, max_depth: int = DEFAULT_MAX_DEPTH) -> Graph:
    return Graph(premise, {q.key: q for q in roots}, max_depth)


# ---------------------------------------------------------------------------
# Propagation
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Contradiction:
    """A node whose interval emptied, and the chain that emptied it."""

    key: str
    chain: tuple[str, ...]
    detail: str

    def __str__(self) -> str:
        return f"{self.key}: {self.detail} (via {' → '.join(self.chain)})"


@dataclass(frozen=True)
class Propagation:
    domains: Mapping[str, Interval]
    contradictions: tuple[Contradiction, ...]

    @property
    def consistent(self) -> bool:
        return not self.contradictions


def propagate(graph: Graph) -> Propagation:
    """Narrow every domain to arc consistency, or report what cannot hold.

    AC-3 over interval domains. The worklist is a list processed in sorted
    order rather than a set or a ``deque`` of arbitrary insertion order,
    because two runs over the same graph must narrow in the same sequence:
    interval arithmetic is not associative in floating point, so an
    order-dependent worklist would give order-dependent bounds, and a graph
    that resolved to different spans on replay would take the whole determinism
    guarantee with it.

    Both directions of every edge are queued. That is the difference between
    this and inheritance: a leaf grounded in a published statistic can make its
    parent's range untenable, and the parent is what the corpus was going to
    print.
    """
    domains: dict[str, Interval] = {q.key: q.domain for q in graph.ordered}

    # Tree edges and cross-layer links become the same thing here. The
    # distinction they carry — derivation versus constraint — matters to a
    # reader and to `ancestry`; it does not matter to arc consistency, and
    # giving links a second, weaker propagation path would make a cross-layer
    # constraint quietly less binding than a parent one.
    relations: dict[tuple[str, str], Relation] = {}
    for node in graph.ordered:
        if node.parent is not None:
            relations[(node.parent, node.key)] = node.via
    for link in graph.links:
        relations[(link.subject, link.object)] = link.via

    arcs: list[tuple[str, str, bool]] = []
    for (parent_key, child_key) in relations:
        arcs.append((parent_key, child_key, True))   # subject constrains object
        arcs.append((child_key, parent_key, False))  # object constrains subject
    queue = sorted(arcs)
    found: list[Contradiction] = []
    seen: set[str] = set()

    while queue:
        arc = queue.pop(0)
        source_key, target_key, downward = arc
        if domains[source_key].empty:
            # Never derive from a domain that has already emptied. Both
            # directions of an edge are queued, so without this a single
            # inconsistency empties the child on the way down *and* the parent
            # on the way back up, and gets reported twice — one mistake wearing
            # two names, with no way for a model to tell it is one.
            continue
        via = relations[(source_key, target_key) if downward else (target_key, source_key)]
        implied = (
            via.forward(domains[source_key]) if downward else via.backward(domains[source_key])
        )
        current = domains[target_key]
        if not current.narrowed_by(implied):
            continue
        after = current.meet(implied)
        domains[target_key] = after
        if after.empty:
            if target_key not in seen:
                seen.add(target_key)
                found.append(Contradiction(
                    target_key,
                    tuple(q.key for q in graph.ancestry(target_key)),
                    f"{source_key} {'implies' if downward else 'requires'} {implied}"
                    f", which cannot hold with {current}",
                ))
            # Do not propagate out of an empty domain. Everything downstream
            # of it would empty too and the report would name a dozen nodes for
            # one mistake, burying the one the model has to fix.
            continue
        # Re-enqueue every arc that could now narrow further, sorted so the
        # traversal stays reproducible.
        queue = sorted(set(queue) | {a for a in arcs if a[0] == target_key})

    return Propagation(domains, tuple(found))


# ---------------------------------------------------------------------------
# What a model is asked, and what it may answer
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Brief:
    """The next question, with everything needed to answer it and nothing else.

    The bounds handed over are the *propagated* ones, not the question's own
    declared domain. That distinction is the whole mechanism by which context
    shapes what the model may say: by the time margin is asked, sell-through
    and markdown have already squeezed it, and the model is answering inside a
    box that earlier answers built.
    """

    key: str
    asks: str
    unit: str
    bounds: Interval
    depth: int
    remaining_depth: int
    ancestry: tuple[tuple[str, str, str], ...]
    """``(key, claim-or-question, bounds)`` root-first. Why this is being asked."""
    terminals: tuple[str, ...]
    """Terminal parameters still unclaimed, for a leaf to bind to."""
    layer: str = ""
    layers: tuple[str, ...] = ()
    next_layer: str = ""
    """The layer a sub-question raised from here should belong to. Handed over
    rather than left to the model to infer, because the layer chain is the
    structure the probe is descending and guessing at it is how a probe ends up
    with two names for one level."""


def frontier(graph: Graph, *, terminals: Mapping[str, Span] = DEFAULTS) -> Brief | None:
    """The next question to put to a model, or ``None`` when the graph is done.

    Breadth-first by ``ordered``, so a level is finished before the next is
    opened. Depth-first would let one branch reach ``max_depth`` while its
    siblings were still unasked, and the sibling's evidence is exactly what
    would have narrowed the deep branch before it was answered.

    On a layered probe the layer order wins over depth: every question about
    reporting structure is settled before the first one about titles, whatever
    depth each sits at. That is the point of naming layers — a title asked
    before the span it hangs off is a title answered without the constraint
    that decides it, and no amount of later propagation puts the reasoning
    back.
    """
    state = propagate(graph)
    claimed = {q.binds for q in graph.questions.values() if q.binds}
    order = {name: index for index, name in enumerate(graph.layers)}
    for node in sorted(
        graph.ordered,
        key=lambda q: (order.get(q.layer, -1 if not q.layer else len(order)), q.depth, q.key),
    ):
        if node.answered:
            continue
        return Brief(
            key=node.key,
            asks=node.asks,
            unit=node.unit,
            bounds=state.domains.get(node.key, node.domain),
            depth=node.depth,
            remaining_depth=graph.max_depth - node.depth,
            ancestry=tuple(
                (a.key, a.claim or a.asks, str(state.domains.get(a.key, a.domain)))
                for a in graph.ancestry(node.key)[:-1]
            ),
            terminals=tuple(sorted(set(terminals) - claimed)),
            layer=node.layer,
            layers=graph.layers,
            next_layer=_layer_after(graph, node),
        )
    return None


def _layer_after(graph: Graph, node: Question) -> str:
    """The layer below *node*'s, or its own at the bottom of the chain."""
    if not graph.layers:
        return ""
    if node.layer not in graph.layers:
        return graph.layers[0]
    index = graph.layers.index(node.layer)
    return graph.layers[min(index + 1, len(graph.layers) - 1)]


def bounded(low: float | None, high: float | None) -> Interval:
    """An interval from two optional ends. ``None`` is "unbounded that side".

    Optional rather than defaulting to ``±inf`` because these fields are
    serialised: ``Infinity`` is not valid JSON, and a ledger that only Python's
    own parser can read is not the portable record this project's replay
    guarantee is written against. It is also the more honest encoding — the
    root of a probe is a question about the *world*, not about a quantity, and
    "no numeric claim" is what it actually means.
    """
    return Interval(-math.inf if low is None else low, math.inf if high is None else high)


class SubQuestion(Model):
    """A question raised by answering another. The Socratic step."""

    key: str
    asks: str
    because: str
    unit: str = ""
    relation: str = "free"
    factor_low: float = 1.0
    factor_high: float = 1.0
    domain_low: float | None = None
    domain_high: float | None = None
    binds: str | None = None
    layer: str = ""

    @property
    def domain(self) -> Interval:
        return bounded(self.domain_low, self.domain_high)


class ProposedLink(Model):
    """A constraint the model asserts between two questions already in the graph."""

    subject: str
    object: str
    relation: str = "at_most"
    factor_low: float = 1.0
    factor_high: float = 1.0
    because: str = ""


class Answer(Model):
    """One model's answer to one question."""

    question: str
    claim: str
    low: float | None = None
    high: float | None = None
    source: str = ""
    binds: str | None = None
    raises: list[SubQuestion] = Field(default_factory=list)
    links: list[ProposedLink] = Field(default_factory=list)
    """Cross-layer constraints. Where ``raises`` says "answering this needs
    that", ``links`` says "that and this cannot be set independently" — the
    difference between decomposing a quantity and modelling a world."""

    @property
    def interval(self) -> Interval:
        return bounded(self.low, self.high)


@dataclass(frozen=True)
class Rejection:
    subject: str
    rule: str
    detail: str

    def __str__(self) -> str:
        return f"{self.subject}: {self.rule} — {self.detail}"


#: The grammar, in sentences, because a model that is told the rules can obey
#: them and a model that is told "invalid" can only guess. Printed by
#: ``worldloom probe requests``.
RULES: tuple[str, ...] = (
    "Answer the question you were asked, by name. One question per answer.",
    "Your interval must lie inside the bounds you were given. You may narrow a"
    " question; you may never widen one. The bounds are what earlier answers"
    " have already established, and widening them would silently discard the"
    " reasoning that produced them.",
    "If the quantity you were asked for is not primitive — if it is a"
    " consequence of things you have not been asked about yet — say so in your"
    " claim and raise those things as sub-questions, rather than picking a"
    " number that has nothing under it.",
    "Every sub-question needs a relation to its parent: how would knowing the"
    " child change what the parent can be? 'free' is allowed and means you"
    " believe there is no arithmetic tie, which is a claim, not a default.",
    "Work down the layers, and stay in the one you are given. A layer is a kind"
    " of question — how the organisation divides, how it reports, what roles"
    " that implies, what those roles are accountable for, what those are"
    " measured by — and a level is settled before the one under it opens. A"
    " measure proposed before the accountability it measures is a number with"
    " nothing behind it.",
    "When two questions in *different* layers cannot be set independently, say"
    " so with a link rather than by picking values that happen to agree. A span"
    " of control and a number of reporting levels are not free of each other"
    " once headcount is fixed; a link is how you state that, and the graph then"
    " enforces it on every answer that follows, including ones you have not"
    " seen yet.",
    "A leaf may bind to a terminal parameter, which is how it reaches the"
    " engine. If nothing in the list fits, leave it unbound and say what it"
    " should have been called — an unbound leaf is reported, not discarded.",
    "Cite where a range came from when you have a source. Sector statistics and"
    " published benchmarks are priors and are welcome. A named company's own"
    " figures are not: this corpus is fictional and must stay that way.",
)


def review(graph: Graph, answer: Answer, *, terminals: Mapping[str, Span] = DEFAULTS) -> list[Rejection]:
    """Every reason this answer cannot be committed. All of them, not the first."""
    found: list[Rejection] = []

    def refuse(subject: str, rule: str, detail: str) -> None:
        found.append(Rejection(subject, rule, detail))

    node = graph.questions.get(answer.question)
    if node is None:
        refuse(answer.question, "unknown_question",
               f"no such question. Open ones: {[q.key for q in graph.ordered if not q.answered]}")
        return found
    if node.answered:
        refuse(answer.question, "already_answered",
               f"answered already, with {node.claim!r}")

    state = propagate(graph)
    bounds = state.domains.get(node.key, node.domain)
    proposed = answer.interval

    if proposed.empty:
        refuse(node.key, "inverted_interval", f"{proposed} has its ends the wrong way round")
    else:
        # The central control. Narrowing is reasoning; widening is discarding
        # somebody else's reasoning without saying so.
        admitted, why = bounds.admits(proposed)
        if not admitted:
            refuse(node.key, "widens_the_question",
                   f"{proposed} falls outside {bounds}, which earlier answers"
                   f" established — {why}")

    if node.depth >= graph.max_depth and answer.raises:
        refuse(node.key, "too_deep",
               f"this question is at depth {node.depth} and the graph stops at"
               f" {graph.max_depth}; answer it rather than deferring it further")

    existing_binds = {q.binds: q.key for q in graph.questions.values() if q.binds}
    children = graph.children_of(node.key)

    def check_bind(subject: str, name: str | None, is_leaf: bool) -> None:
        if name is None:
            return
        if name not in terminals:
            refuse(subject, "unknown_terminal",
                   f"{name!r} is not a terminal parameter; run `worldloom pack params`")
            return
        if not is_leaf:
            refuse(subject, "bound_branch",
                   f"{name!r} is bound to a question that has sub-questions."
                   " Only leaves bind — a branch's range is whatever its"
                   " children leave it, not something to set directly.")
        owner = existing_binds.get(name)
        if owner is not None and owner != subject:
            refuse(subject, "terminal_taken", f"{name!r} is already bound by {owner}")

    check_bind(node.key, answer.binds, not children and not answer.raises)
    if answer.binds is not None and answer.binds in terminals:
        span = terminals[answer.binds]
        if span.kind == "chance" and proposed.low != proposed.high:
            refuse(node.key, "chance_needs_a_point",
                   f"{answer.binds!r} is a probability, so it takes one value,"
                   f" not the range {proposed}")

    seen: set[str] = set()
    for sub in answer.raises:
        if sub.key in graph.questions:
            refuse(sub.key, "duplicate_key", "a question with this key already exists")
        if sub.key in seen:
            refuse(sub.key, "duplicate_key", "raised twice in one answer")
        seen.add(sub.key)
        if sub.relation not in KINDS:
            refuse(sub.key, "unknown_relation", f"{sub.relation!r}; expected one of {KINDS}")
        elif sub.relation == "scales" and sub.factor_low > sub.factor_high:
            refuse(sub.key, "inverted_factor",
                   f"scaling factor [{sub.factor_low}, {sub.factor_high}] is the wrong way round")
        if sub.domain.empty:
            refuse(sub.key, "inverted_interval", "domain ends are the wrong way round")
        if not sub.because.strip():
            refuse(sub.key, "unexplained",
                   "say why answering the parent requires this. A sub-question"
                   " with no reasoning is a guess with extra structure.")
        check_bind(sub.key, sub.binds, True)
        if graph.layers and sub.layer and sub.layer not in graph.layers:
            refuse(sub.key, "unknown_layer",
                   f"{sub.layer!r} is not one of this probe's layers {list(graph.layers)}")

    known = set(graph.questions) | seen
    for link in answer.links:
        for role, key in (("subject", link.subject), ("object", link.object)):
            if key not in known:
                refuse(key, "unknown_question",
                       f"a link's {role} must be a question that exists or that this"
                       " answer raises")
        if link.subject == link.object:
            refuse(link.subject, "self_link", "a question cannot constrain itself")
        if link.relation not in KINDS:
            refuse(link.subject, "unknown_relation",
                   f"{link.relation!r}; expected one of {KINDS}")
        elif link.relation == "scales" and link.factor_low > link.factor_high:
            refuse(link.subject, "inverted_factor",
                   f"scaling factor [{link.factor_low}, {link.factor_high}] is the wrong way round")
        if not link.because.strip():
            refuse(link.subject, "unexplained",
                   "say why these two cannot be set independently. An unexplained"
                   " link is an assertion the graph will enforce forever and"
                   " nobody can audit.")

    if found:
        return found

    # Only now, with the answer well-formed, ask whether it can actually be
    # true alongside everything already accepted. Running this earlier would
    # report a contradiction caused by a typo'd relation.
    after = propagate(_applied(graph, answer))
    for contradiction in after.contradictions:
        refuse(contradiction.key, "contradicts", str(contradiction))

    return found


def _applied(graph: Graph, answer: Answer) -> Graph:
    """*graph* with *answer* committed. Pure; no validation."""
    node = graph.questions[answer.question]
    questions = dict(graph.questions)
    questions[node.key] = replace(
        node,
        domain=node.domain.meet(answer.interval),
        answered=True,
        claim=answer.claim,
        source=answer.source or node.source,
        binds=answer.binds if answer.binds is not None else node.binds,
    )
    for sub in answer.raises:
        questions[sub.key] = Question(
            key=sub.key,
            asks=sub.asks,
            unit=sub.unit,
            domain=sub.domain,
            depth=node.depth + 1,
            parent=node.key,
            via=relation(sub.relation, factor_low=sub.factor_low, factor_high=sub.factor_high),
            because=sub.because,
            layer=sub.layer or _layer_after(graph, node),
            binds=sub.binds,
        )
    links = (*graph.links, *(
        Link(link.subject, link.object,
             relation(link.relation, factor_low=link.factor_low, factor_high=link.factor_high),
             link.because)
        for link in answer.links
    ))
    return replace(graph, questions=questions, links=links)


@dataclass(frozen=True)
class AcceptResult:
    graph: Graph | None
    rejections: tuple[Rejection, ...]
    raised: int

    @property
    def accepted(self) -> bool:
        return self.graph is not None


def accept(graph: Graph, answer: Answer, *, terminals: Mapping[str, Span] = DEFAULTS) -> AcceptResult:
    """Commit an answer, or refuse all of it.

    All-or-nothing, like every other handshake here: committing the narrowed
    interval but dropping a malformed sub-question would leave a graph whose
    parent claims to be settled by children that do not exist.
    """
    rejections = review(graph, answer, terminals=terminals)
    if rejections:
        return AcceptResult(None, tuple(rejections), 0)
    return AcceptResult(_applied(graph, answer), (), len(answer.raises))


# ---------------------------------------------------------------------------
# Resolution — where the graph meets the engine
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Unbound:
    """A leaf the world needed and the engine cannot read.

    Reported rather than dropped. This is the module's whole claim to being
    more than decoration: a model that keeps finding the same missing terminal
    across worlds is evidence for adding it to ``parameters.DEFAULTS``, and
    that evidence only exists if the finding survives.
    """

    key: str
    asks: str
    claim: str
    bounds: Interval
    unit: str

    def __str__(self) -> str:
        return f"{self.key} {self.bounds} {self.unit} — {self.claim or self.asks}"


@dataclass(frozen=True)
class Resolution:
    overrides: Mapping[str, Span]
    unbound: tuple[Unbound, ...]
    unanswered: tuple[str, ...]
    contradictions: tuple[Contradiction, ...]

    @property
    def usable(self) -> bool:
        return not self.contradictions and not self.unanswered

    def parameters(self, base: Parameters | None = None) -> Parameters:
        """The engine's physics with this graph's findings applied."""
        from .parameters import DEFAULT

        if not self.usable:
            raise ValueError(
                "this graph cannot produce physics: "
                + "; ".join([*self.unanswered, *(str(c) for c in self.contradictions)])
            )
        return (base or DEFAULT).with_overrides(self.overrides)


def resolve(graph: Graph, *, terminals: Mapping[str, Span] = DEFAULTS) -> Resolution:
    """Turn a settled graph into overrides for the terminal registry.

    Bounds come from ``propagate``, not from the answer as given: a leaf
    answered at ``[0.50, 0.60]`` whose siblings later forced it to
    ``[0.52, 0.55]`` must resolve to the narrower one. Using the stated answer
    would hand the engine a range the graph itself no longer believes.
    """
    state = propagate(graph)
    overrides: dict[str, Span] = {}
    unbound: list[Unbound] = []

    for leaf in graph.leaves():
        if not leaf.answered:
            continue
        bounds = state.domains.get(leaf.key, leaf.domain)
        if leaf.binds is None:
            unbound.append(Unbound(leaf.key, leaf.asks, leaf.claim, bounds, leaf.unit))
            continue
        terminal = terminals[leaf.binds]
        # `kind` and `places` stay the engine's, exactly as `with_overrides`
        # would enforce anyway. Set here too so the Span this returns is the
        # one that will actually be used — a caller inspecting `overrides`
        # should not see a shape that is about to be quietly corrected.
        overrides[leaf.binds] = Span(
            bounds.low, bounds.high, terminal.kind, terminal.places,
            about=terminal.about,
            source=leaf.source or f"probe: {leaf.key}",
        )

    return Resolution(
        overrides=overrides,
        unbound=tuple(unbound),
        unanswered=tuple(q.key for q in graph.ordered if not q.answered),
        contradictions=state.contradictions,
    )


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The space a settled graph describes
# ---------------------------------------------------------------------------

#: How many candidates are drawn before dispersion picks from them. Large
#: enough that the filter below can throw most of them away and still leave a
#: field to choose from; small enough to stay instant. Fixed rather than
#: configurable because it is a property of the sampler, not a knob a world
#: should differ by.
_POOL = 2048

#: How far outside a relation a candidate may sit and still count as satisfying
#: it. Arc consistency narrows domains but does not make every point in the
#: product of those domains jointly consistent, so candidates are filtered —
#: and the filter compares floats that came from interval arithmetic, so it
#: needs the same relative slack every other comparison here uses.
_SATISFIED = 1e-9


@dataclass(frozen=True)
class WorldPoint:
    """One consistent assignment: a value for every question that has a range."""

    values: Mapping[str, float]

    def as_dict(self) -> dict[str, float]:
        return dict(sorted(self.values.items()))


def _bounded_nodes(graph: Graph, state: Propagation) -> tuple[Question, ...]:
    return tuple(
        node for node in graph.ordered
        if not math.isinf(state.domains.get(node.key, node.domain).width)
        and state.domains.get(node.key, node.domain).width > 0.0
    )


def _satisfies(graph: Graph, values: Mapping[str, float]) -> bool:
    """Whether an assignment respects every relation, not just every domain.

    Needed because arc consistency is a property of *domains*, not of points.
    A graph can be perfectly arc-consistent and still contain corners of the
    product space where a child sits at its maximum while its parent sits at
    its minimum — a world that satisfies every range and none of the reasoning.
    """
    pairs: list[tuple[str, str, Relation]] = [
        (node.parent, node.key, node.via)
        for node in graph.ordered if node.parent is not None
    ]
    pairs += [(link.subject, link.object, link.via) for link in graph.links]

    for subject, obj, via in pairs:
        if subject not in values or obj not in values or via.kind == "free":
            continue
        allowed = via.forward(Interval(values[subject], values[subject]))
        slack = _SATISFIED * max(1.0, abs(allowed.low), abs(allowed.high))
        if not (allowed.low - slack <= values[obj] <= allowed.high + slack):
            return False
    return True


def worlds(graph: Graph, *, count: int = 5, pool: int = _POOL) -> tuple[WorldPoint, ...]:
    """*count* consistent worlds this graph allows, as unlike each other as possible.

    A settled probe does not describe one world. It describes a *space* — every
    assignment inside the narrowed domains that also respects the relations —
    and picking the midpoint of each interval, which is what a naive resolver
    does, throws that away and produces the single most average member of it.

    So: cover the space with a low-discrepancy sequence rather than random
    draws (``dispersion.halton``, because random points clump and a clump is a
    region of world-shapes never visited), keep the assignments that satisfy
    every relation, then take the ``count`` furthest apart by farthest-point
    traversal over coordinates normalised to each question's own range.

    Normalising before measuring distance is load-bearing. Reporting depth runs
    1 to 8 and a margin runs 0.2 to 0.6; unnormalised, depth would decide
    entirely what "unlike" means, and the corpus would vary in one dimension
    while looking identical in every other.

    Deterministic end to end — no ``Rng``, no clock, ties to the lowest index —
    so the same graph yields the same mosaic on every machine and every replay.
    """
    if count < 0:
        raise ValueError(f"count must be non-negative, got {count}")
    state = propagate(graph)
    if not state.consistent:
        raise ValueError(
            "this graph is not consistent, so it describes no worlds at all: "
            + "; ".join(str(c) for c in state.contradictions)
        )

    free = _bounded_nodes(graph, state)
    fixed = {
        node.key: state.domains.get(node.key, node.domain).low
        for node in graph.ordered
        if node not in free and not math.isinf(state.domains.get(node.key, node.domain).low)
    }
    if not free:
        # Every question is pinned to a point. There is exactly one world, and
        # saying so is more useful than returning `count` copies of it.
        return (WorldPoint(fixed),) if count else ()

    from .dispersion import farthest_first, halton, manhattan

    spans = [state.domains[node.key] for node in free]
    candidates: list[tuple[float, ...]] = []
    points: list[WorldPoint] = []
    for unit in halton(len(free), pool):
        values = dict(fixed)
        for node, span, coordinate in zip(free, spans, unit, strict=True):
            values[node.key] = span.low + coordinate * span.width
        if not _satisfies(graph, values):
            continue
        candidates.append(unit)  # already normalised: the unit cube is the scale
        points.append(WorldPoint(values))

    if not points:
        raise ValueError(
            f"no assignment among {pool} candidates satisfies every relation."
            " The graph is arc-consistent but its relations may only hold at"
            " corners of the space — check for a `scales` factor narrow enough"
            " to be effectively an equation."
        )

    chosen = farthest_first(candidates, manhattan, min(count, len(points)))
    return tuple(points[index] for index in chosen)


#: The one question every probe starts from. Not a quantity — it has no unit
#: and its interval is the whole line — which is why ``Answer`` lets the numeric
#: claim be omitted. Answering it is where a model turns a premise into the
#: handful of quantities that premise commits it to.
ROOT = "premise"

ROOT_ASKS = (
    "What shape is this organisation, and which of its quantities are not free"
    " to choose once you have said so? Raise those as sub-questions. Do not"
    " give numbers here — name the things that will have to have numbers, and"
    " say how each one is tied to the others. Work down the layers: how the"
    " organisation divides, then how it reports, then what roles that implies,"
    " then what those roles are accountable for, and only then the figures"
    " those accountabilities are measured by."
)


#: A structural layer chain, and the default one. Not an industry — an
#: organisation of any kind has a shape, that shape decides what roles exist,
#: roles decide what people are accountable for, and only then does any of it
#: produce a figure. Descending *that* is what makes a probe about a company
#: rather than about a category called "retailer".
#:
#: Overridable, because the chain is a modelling choice: a probe about a
#: supply chain descends different levels. What is not overridable is that
#: there *is* a chain, and that a level is settled before the one under it.
STRUCTURE: tuple[str, ...] = ("organisation", "reporting", "roles", "objectives", "measures")


def opening(premise: str, *, max_depth: int = DEFAULT_MAX_DEPTH,
            layers: Sequence[str] = STRUCTURE) -> Graph:
    """A graph containing only the question the premise poses."""
    return Graph(
        premise,
        {ROOT: Question(key=ROOT, asks=ROOT_ASKS, unit="", domain=WHOLE, depth=0)},
        max_depth=max_depth,
        layers=tuple(layers),
    )


@dataclass(frozen=True)
class Session:
    """A probe as it is stored between calls: a premise and its answers.

    The graph is *derived*, never stored. Storing the graph as well would give
    a file two sources of truth for the same state and no mechanism to notice
    when they disagreed — and the derived one is the one a later version of the
    grammar would rebuild differently, which is precisely the divergence worth
    finding out about at load time rather than at resolve time.
    """

    premise: str
    max_depth: int = DEFAULT_MAX_DEPTH
    entries: tuple[Mapping[str, Any], ...] = ()
    layers: tuple[str, ...] = STRUCTURE

    @property
    def graph(self) -> Graph:
        graph = opening(self.premise, max_depth=self.max_depth, layers=self.layers)
        for entry in self.entries:
            result = accept(graph, Answer.model_validate(entry))
            if not result.accepted:
                raise ValueError(
                    f"ledger entry for {entry.get('question')!r} no longer accepts: "
                    + "; ".join(str(r) for r in result.rejections)
                )
            graph = result.graph  # type: ignore[assignment]
        return graph

    def committed(self, answer: Answer) -> Session:
        """This session with *answer* appended. Raises if it does not accept."""
        result = accept(self.graph, answer)
        if not result.accepted:
            raise ValueError("; ".join(str(r) for r in result.rejections))
        return replace(self, entries=(*self.entries, ledger_entry(answer)))

    def document(self) -> dict[str, Any]:
        return {
            "premise": self.premise,
            "max_depth": self.max_depth,
            "layers": list(self.layers),
            "answers": [dict(entry) for entry in self.entries],
        }

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> Session:
        return cls(
            premise=document["premise"],
            max_depth=int(document.get("max_depth", DEFAULT_MAX_DEPTH)),
            entries=tuple(document.get("answers", ())),
            # A probe written before layers existed carries none, and its
            # questions all have an empty layer, so the default chain would
            # order its frontier by a level none of them belong to. An absent
            # key means unlayered, not "use the default".
            layers=tuple(document.get("layers", ())),
        )


def brief_document(brief: Brief | None, *, premise: str) -> dict[str, Any]:
    """What a model is handed. ``None`` means the graph is settled."""
    if brief is None:
        return {"premise": premise, "question": None, "rules": list(RULES)}
    return {
        "premise": premise,
        "question": {
            "key": brief.key,
            "asks": brief.asks,
            "unit": brief.unit,
            "bounds": {"low": _finite(brief.bounds.low), "high": _finite(brief.bounds.high)},
            "depth": brief.depth,
            "remaining_depth": brief.remaining_depth,
            "layer": brief.layer,
        },
        "layers": list(brief.layers),
        "layer_for_sub_questions": brief.next_layer,
        "because": [
            {"key": key, "established": claim, "bounds": bounds}
            for key, claim, bounds in brief.ancestry
        ],
        "unclaimed_terminals": list(brief.terminals),
        "rules": list(RULES),
    }


def _finite(value: float) -> float | None:
    """``None`` for an unbounded end — ``Infinity`` is not valid JSON."""
    return None if math.isinf(value) else value


def ledger_entry(answer: Answer) -> dict[str, Any]:
    return answer.model_dump(mode="json")


def replay(premise: str, roots: Sequence[Question], entries: Sequence[Mapping[str, Any]],
           *, max_depth: int = DEFAULT_MAX_DEPTH) -> Graph:
    """Rebuild a graph from its recorded answers.

    Replays through ``accept``, not through ``_applied``: a ledger that
    rebuilds only when validation is skipped is a ledger that has stopped
    describing how the graph was actually built, and the divergence would not
    surface until some later change made a recorded answer illegal.
    """
    graph = open_graph(premise, roots, max_depth=max_depth)
    for entry in entries:
        result = accept(graph, Answer.model_validate(entry))
        if not result.accepted:
            raise ValueError(
                f"ledger entry for {entry.get('question')!r} no longer accepts: "
                + "; ".join(str(r) for r in result.rejections)
            )
        graph = result.graph  # type: ignore[assignment]
    return graph


__all__ = [
    "Answer", "Brief", "Contradiction", "DEFAULT_MAX_DEPTH", "Graph", "Interval",
    "Link", "ProposedLink", "Question", "ROOT", "ROOT_ASKS", "Rejection",
    "Relation", "Resolution", "RULES", "Session", "SubQuestion", "Unbound",
    "WHOLE", "WorldPoint", "accept", "bounded", "brief_document", "frontier",
    "ledger_entry", "open_graph", "opening", "propagate", "relation", "replay",
    "resolve", "review", "worlds",
]
