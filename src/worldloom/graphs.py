"""The world as graphs, and the questions only a graph can answer.

Worldloom has always *had* graphs — ``Service.depends_on`` is a dependency
edge, ``Employee.manager_id`` is a tree edge, ``derived_from``/``supersedes``/
``revises``/``restates`` are provenance edges, and a fact's ``supersedes`` is
a chain link. What it has not had is anything that *reads* them. The validator
caught a service that depends on itself and a reporting line that cycles back
on one person; it could not see a cycle through three services, and its
fact-level supersession map silently overwrote a fork. Nothing anywhere could
say which service failing would take the most of the estate with it.

This module is that reading, and it exists for three reasons in ascending
order of value:

1. **It closes real invariant gaps.** Cycles through more than one hop, forked
   supersession chains, and provenance loops are all defects the hand-rolled
   walks in ``validate.py`` were structurally unable to see. They are checked
   corpus-wide now, through one library, for every vertical at once.
2. **It gives the corpus a structural axis.** "Which service's failure reaches
   the most of the estate" and "which dependency is the one nothing routes
   around" are multi-hop questions whose answer is not written down in any
   document — it is a property of the graph. A keyword retriever cannot
   shortcut a question whose answer nobody wrote a sentence about.
3. **It makes the estate legible.** ``worldloom topology`` prints the shape a
   generated world actually has, which is the fastest way to see that an
   archetype's service catalogue is a flat list of nine unrelated things
   rather than a system.

**Determinism, which is the whole constraint.** A corpus regenerates
byte-for-byte, so nothing here may depend on set iteration order, dict
insertion order that a caller did not fix, or a float whose last bit differs
between BLAS builds. Three rules hold that:

* Every graph is built by inserting nodes and then edges **in sorted id
  order**, so any networkx algorithm whose result depends on iteration order
  produces the same result on every machine.
* Every measure is exact integer arithmetic — set cardinalities, path lengths,
  in/out degrees. There is no centrality score anywhere in this module, and
  that is deliberate: PageRank and betweenness are floats produced by
  iterative solvers, and ranking by a float means an ``argmax`` that a
  different SciPy build can flip. A rank that moves between machines is not a
  rank, it is a coin toss with a decimal point.
* Every ordering breaks ties on the node id, explicitly, at the point of
  sorting.

``networkx`` does the graph structure — reachability, dominators, topological
order, cycle enumeration — because it is the right tool and hand-rolling
Lengauer-Tarjan would be worse code with the same answer. The one algorithm
written out longhand here is the longest path (``longest_chain``), because
``nx.dag_longest_path`` breaks ties by iteration order rather than by a stated
rule, and "the deepest dependency chain" is a *reported* answer that must not
wobble.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import networkx as nx

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: How many cycles ``cycles()`` will enumerate before giving up. A coherent
#: corpus has none; a broken one can have exponentially many, and a validator
#: that hangs on a defect is worse than one that reports the first few and says
#: there were more.
CYCLE_LIMIT = 16


# ---------------------------------------------------------------------------
# Building the graphs
# ---------------------------------------------------------------------------


def _ordered(nodes: list[tuple[str, dict[str, Any]]],
             edges: list[tuple[str, str]]) -> nx.DiGraph:
    """A DiGraph with nodes and edges inserted in sorted order.

    The insertion order is the determinism guarantee, not a tidiness
    preference: ``nx.simple_cycles`` and ``nx.immediate_dominators`` both walk
    adjacency in insertion order, so a graph built by iterating a ``set`` would
    return the same cycles in a different order on a different machine — and
    ``worldloom topology --json`` is diffed in CI exactly like a rendered
    corpus is.
    """
    graph = nx.DiGraph()
    # Sorted on the id alone. `sorted(nodes)` compares the whole tuple, so two
    # entries sharing an id fall through to comparing their attribute *dicts*
    # and raise — which turned a duplicate id, a defect the validator exists to
    # report, into a TypeError from inside the reporting machinery.
    for node, attributes in sorted(nodes, key=lambda row: row[0]):
        graph.add_node(node, **attributes)
    for source, target in sorted(edges):
        graph.add_edge(source, target)
    return graph


def dependency_graph(world: World) -> nx.DiGraph:
    """Services and the systems they run on, as a dependency graph.

    **Edge direction is ``dependent -> dependency``**, which reads the way the
    field does: ``A.depends_on = [B]`` becomes the edge ``A -> B``. So
    ``nx.descendants(g, A)`` is everything A rests on, and ``nx.ancestors(g,
    B)`` is everything that falls over when B does — which is what
    :func:`blast_radius` returns.

    Systems are nodes too, not just services. ``validate.py`` already accepts
    either as a ``depends_on`` target (``expect={"SVC", "SYS"}``), and a
    dependency chain that stopped at the system boundary would miss the case
    that matters most: two services whose only relationship is that they read
    the same system of record.
    """
    nodes: list[tuple[str, dict[str, Any]]] = []
    edges: list[tuple[str, str]] = []

    for system in world.systems:
        nodes.append((system.id, {"kind": "system", "name": system.name,
                                  "owner_id": system.owner_id}))
    for service in world.services:
        nodes.append((service.id, {"kind": "service", "name": service.name,
                                   "owner_id": service.owner_id,
                                   "tier": service.criticality_tier,
                                   "system_id": service.system_id}))

    known = {node for node, _ in nodes}
    for service in world.services:
        for target in service.depends_on:
            # A dangling edge is `validate.py`'s referential check to report,
            # not this module's to guess at. Dropping it here keeps every graph
            # algorithm below operating on a graph whose nodes are all real —
            # otherwise networkx would silently mint a node with no attributes
            # and the topology report would name an entity that does not exist.
            if target in known and target != service.id:
                edges.append((service.id, target))

    return _ordered(nodes, edges)


def reporting_graph(world: World) -> nx.DiGraph:
    """People, edge ``report -> manager``."""
    nodes = [(p.id, {"name": p.name, "title": p.title}) for p in world.people]
    known = {node for node, _ in nodes}
    edges = [
        (p.id, p.manager_id) for p in world.people
        if p.manager_id and p.manager_id in known and p.manager_id != p.id
    ]
    return _ordered(nodes, edges)


def provenance_graph(world: World) -> nx.DiGraph:
    """Artifacts, edge ``later -> earlier``, over every provenance relationship.

    All four relationships in one graph on purpose. Each is checked separately
    in ``validate.py`` for its own semantics — a restatement may not also
    revise, a supersession may not point forward in time — but *acyclicity* is
    a property of the union: a document that derives from one that supersedes
    one that revises it is a loop no single-relationship check can see.

    Reads the manifest when there is one and the *intents* when there is not.
    A built-but-unrendered world carries no manifest entries at all (bodies
    arrive with the renderers), and its provenance is already fully decided —
    an intent declares ``derived_from`` at planning time. Reading only the
    manifest would report "no provenance" for every corpus that has not been
    rendered yet, which is the state a corpus spends most of its life in.
    """
    records = list(world.artifacts) or list(world.artifact_intents)
    nodes = [(a.id, {"artifact_type": a.artifact_type}) for a in records]
    known = {node for node, _ in nodes}
    edges: list[tuple[str, str]] = []
    for entry in records:
        related = [*entry.derived_from, entry.supersedes, entry.revises, entry.restates]
        for target in related:
            if target and target in known and target != entry.id:
                edges.append((entry.id, target))
    return _ordered(nodes, edges)


def supersession_graph(world: World) -> nx.DiGraph:
    """Facts that supersede something, edge ``superseding -> superseded``.

    Only facts on a chain are nodes. A corpus's facts are overwhelmingly
    un-superseded — a graph carrying all of them would be tens of thousands of
    isolated nodes, and every measure over it would be dominated by the
    isolates rather than by the chains the measure is about.
    """
    linked = {f.id for f in world.facts if f.supersedes} | {
        f.supersedes for f in world.facts if f.supersedes
    }
    known = {f.id for f in world.facts}
    nodes = [(f.id, {"kind": f.kind, "subject": f.subject})
             for f in world.facts if f.id in linked]
    edges = [(f.id, f.supersedes) for f in world.facts
             if f.supersedes and f.supersedes in known and f.supersedes != f.id]
    return _ordered(nodes, edges)


# ---------------------------------------------------------------------------
# Measures — exact integers, ties broken on id
# ---------------------------------------------------------------------------


def blast_radius(graph: nx.DiGraph, node: str) -> frozenset[str]:
    """Everything that transitively depends on *node* — what falls over with it."""
    return frozenset(nx.ancestors(graph, node)) if node in graph else frozenset()


def supply_chain(graph: nx.DiGraph, node: str) -> frozenset[str]:
    """Everything *node* transitively rests on."""
    return frozenset(nx.descendants(graph, node)) if node in graph else frozenset()


def roots(graph: nx.DiGraph) -> tuple[str, ...]:
    """Nodes nothing depends on — the tops of the dependency chains."""
    return tuple(sorted(n for n in graph if graph.in_degree(n) == 0))


def longest_chain(graph: nx.DiGraph) -> tuple[str, ...]:
    """The deepest path through the graph, ties broken on node id.

    Written out rather than delegated to ``nx.dag_longest_path`` because that
    function breaks ties by whichever predecessor the adjacency iteration
    reached first, which is a rule about insertion order rather than about the
    data. This is a number and a path the topology report *prints*, so it has
    to be the same path everywhere, stated as a rule: longest wins, and among
    equals the lexicographically smallest sequence wins.

    Returns ``()`` on a cyclic graph — "the longest path" is not defined there,
    and the cycle itself is the finding worth reporting.
    """
    if not nx.is_directed_acyclic_graph(graph):
        return ()
    best: dict[str, tuple[str, ...]] = {}
    # Reverse topological order: an edge points from dependent to dependency,
    # so a topological sort puts a node *before* everything it rests on.
    # Walking it backwards means every successor's answer is already in `best`
    # when the node that needs it is reached, and the recurrence needs no
    # second pass.
    for node in reversed(list(nx.lexicographical_topological_sort(graph))):
        candidates = [best[s] for s in sorted(graph.successors(node)) if s in best]
        tail: tuple[str, ...] = ()
        if candidates:
            deepest = max(len(chain) for chain in candidates)
            # Longest first, then the smallest sequence among equals — stated
            # as two steps rather than folded into one `max` key, because a key
            # of `(len, chain)` would prefer the lexicographically *largest*
            # tie and this docstring promises the smallest.
            tail = min(chain for chain in candidates if len(chain) == deepest)
        best[node] = (node, *tail)
    if not best:
        return ()
    deepest = max(len(chain) for chain in best.values())
    return min(chain for chain in best.values() if len(chain) == deepest)


def cycles(graph: nx.DiGraph, *, limit: int = CYCLE_LIMIT) -> tuple[tuple[str, ...], ...]:
    """Up to *limit* elementary cycles, each rotated to start at its smallest node.

    The rotation is what makes a cycle comparable: ``nx.simple_cycles`` returns
    the same loop starting wherever it happened to enter, so two runs that
    entered from different nodes would report "different" cycles that are the
    same defect.
    """
    # The overwhelmingly common case, short-circuited: a coherent corpus is
    # acyclic, and this runs on every `validate` of every corpus.
    if nx.is_directed_acyclic_graph(graph):
        return ()
    found: list[tuple[str, ...]] = []
    for cycle in nx.simple_cycles(graph):
        pivot = cycle.index(min(cycle))
        found.append(tuple(cycle[pivot:] + cycle[:pivot]))
        if len(found) >= limit:
            break
    return tuple(sorted(found))


def chokepoints(graph: nx.DiGraph) -> tuple[tuple[str, int], ...]:
    """Nodes nothing routes around, with how many nodes each one gates.

    A *chokepoint* is a node ``D`` such that some node ``n`` cannot be reached
    from **anywhere** in the estate except through ``D``. That is the honest
    formalisation of "single point of failure": not merely "lots of things
    depend on it" (that is blast radius, which a well-replicated shared
    platform also has), but "there is no second path to what it serves".

    Computed as dominators over the graph augmented with a **virtual source**
    joined to every root, which is what makes "from anywhere" the question.

    There is a second, weaker question that is also worth asking and that this
    deliberately does not answer: *is this node the only way some particular
    consumer reaches what it needs?* That is the per-root dominator union, and
    it is not wrong — it is the right question if you are the team that owns
    one service and want to know what can take you out. It is the wrong
    question for a report about an estate, because on a sparse graph almost
    everything answers yes to it: a 101-node landscape reports **47** under the
    per-root union and **14** under this one, and most of the 47 are nodes that
    one customer-facing service happened to reach by a single path while three
    others reached them by several. Ranked by how much each gates, the per-root
    answer is still readable; as a headline count it says only that the estate
    is sparse, which the node and edge counts already said.

    Cyclic graphs return ``()``: dominators are defined on a flow graph reached
    from an entry, and a dependency cycle has no entry to be reached from — the
    cycle is the finding, and :func:`cycles` reports it.
    """
    if not nx.is_directed_acyclic_graph(graph):
        return ()
    entries = roots(graph)
    if not entries:
        return ()
    # The virtual source is named so it cannot collide with a real id: every
    # entity id in this project is a prefixed, uppercase string.
    source = "\x00source"
    augmented = graph.copy()
    augmented.add_node(source)
    for root in entries:
        augmented.add_edge(source, root)

    gated: dict[str, set[str]] = {}
    for node, dominator in sorted(nx.immediate_dominators(augmented, source).items()):
        # A node is its own immediate dominator by convention, and the virtual
        # source dominates everything trivially — neither says anything about
        # redundancy.
        if dominator not in (node, source) and node != source:
            gated.setdefault(dominator, set()).add(node)
    return tuple(sorted(
        ((node, len(nodes)) for node, nodes in gated.items()),
        key=lambda row: (-row[1], row[0]),
    ))


def forks(graph: nx.DiGraph) -> tuple[tuple[str, tuple[str, ...]], ...]:
    """Nodes with more than one in-edge, and who points at them.

    On a supersession graph this is the invariant that matters: two facts that
    both supersede one earlier fact are a forked chain, which makes "what is
    current" ambiguous — the corpus states two answers and offers no rule for
    choosing. ``validate.py``'s fact-level walk built a ``dict`` keyed on the
    superseded id and let the second writer win, so this class of defect had no
    way to surface at all.
    """
    return tuple(
        (node, tuple(sorted(graph.predecessors(node))))
        for node in sorted(graph)
        if graph.in_degree(node) > 1
    )


# ---------------------------------------------------------------------------
# The service ranking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ServiceRank:
    """One service's position in the estate, every field an exact count."""

    id: str
    name: str
    kind: str
    tier: int
    """The declared criticality tier, 1 (highest) to 4."""
    fan_in: int
    """How many things depend on this directly."""
    fan_out: int
    """How many things this depends on directly."""
    blast_radius: int
    """How many things fall over transitively when this does."""
    depth: int
    """How many hops of its own dependency chain sit below it."""
    gates: int
    """How many nodes this one is the only route to (0 = fully routed around)."""

    @property
    def key(self) -> tuple[int, int, int, str]:
        """The ranking key: reach first, then direct dependents, then declared
        tier, then id. Every component an integer, so the order is identical on
        every machine — see this module's docstring on why no float appears."""
        return (-self.blast_radius, -self.fan_in, self.tier, self.id)


def criticality(world: World) -> tuple[ServiceRank, ...]:
    """Every service and system, ranked by how much of the estate it carries.

    The ranking is *derived*, and that is the point of having it: an archetype
    declares ``criticality_tier`` by hand, and the declaration can disagree
    with the graph. A tier-4 service that seventeen things transitively depend
    on is either a mis-declared tier or an architecture nobody has looked at,
    and both are findings.
    """
    graph = dependency_graph(world)
    ranks: list[ServiceRank] = []
    gated = dict(chokepoints(graph))
    for node in sorted(graph):
        attributes = graph.nodes[node]
        ranks.append(ServiceRank(
            id=node,
            name=attributes.get("name", node),
            kind=attributes.get("kind", "service"),
            # A system carries no declared tier. It sorts as if tier 4 so a
            # system never outranks a service on the tie-break alone; its
            # blast radius, which is the primary key, still speaks for it.
            tier=int(attributes.get("tier", 4)),
            fan_in=graph.in_degree(node),
            fan_out=graph.out_degree(node),
            blast_radius=len(blast_radius(graph, node)),
            depth=len(supply_chain(graph, node)),
            gates=gated.get(node, 0),
        ))
    return tuple(sorted(ranks, key=lambda rank: rank.key))


# ---------------------------------------------------------------------------
# The whole reading
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Topology:
    """What every graph in one corpus looks like, measured."""

    services: tuple[ServiceRank, ...]
    chokepoints: tuple[tuple[str, int], ...]
    longest_dependency_chain: tuple[str, ...]
    dependency_cycles: tuple[tuple[str, ...], ...]
    reporting_depth: int
    """Hops, not levels — the number of edges on the longest chain, so an
    estate with no dependencies at all reports 0 rather than 1. Every ``depth``
    on this record is counted the same way; mixing hops and levels across three
    graphs is exactly the sort of thing a reader silently gets wrong."""
    widest_span: tuple[str, int]
    """The manager with the most direct reports, and how many."""
    reporting_cycles: tuple[tuple[str, ...], ...]
    provenance_depth: int
    deepest_provenance_chain: tuple[str, ...]
    provenance_cycles: tuple[tuple[str, ...], ...]
    supersession_chains: int
    longest_supersession_chain: tuple[str, ...]
    forked_supersessions: tuple[tuple[str, tuple[str, ...]], ...]

    def as_dict(self) -> dict[str, Any]:
        """The whole reading as plain data, stably ordered for ``--json``."""
        return {
            "services": [
                {
                    "id": rank.id, "name": rank.name, "kind": rank.kind,
                    "tier": rank.tier, "fan_in": rank.fan_in, "fan_out": rank.fan_out,
                    "blast_radius": rank.blast_radius, "depth": rank.depth,
                    "gates": rank.gates,
                }
                for rank in self.services
            ],
            "chokepoints": [{"id": node, "gates": count} for node, count in self.chokepoints],
            "longest_dependency_chain": list(self.longest_dependency_chain),
            "dependency_cycles": [list(cycle) for cycle in self.dependency_cycles],
            "reporting_depth": self.reporting_depth,
            "widest_span": {"id": self.widest_span[0], "reports": self.widest_span[1]},
            "reporting_cycles": [list(cycle) for cycle in self.reporting_cycles],
            "provenance_depth": self.provenance_depth,
            "deepest_provenance_chain": list(self.deepest_provenance_chain),
            "provenance_cycles": [list(cycle) for cycle in self.provenance_cycles],
            "supersession_chains": self.supersession_chains,
            "longest_supersession_chain": list(self.longest_supersession_chain),
            "forked_supersessions": [
                {"fact": node, "superseded_by": list(by)}
                for node, by in self.forked_supersessions
            ],
        }

    def __str__(self) -> str:
        lines = [
            "Topology",
            f"  services and systems        {len(self.services)}",
            f"  deepest dependency chain    {_hops(self.longest_dependency_chain)} hops"
            f"  {' → '.join(self.longest_dependency_chain) or '(none)'}",
            f"  chokepoints                 {len(self.chokepoints)}",
            f"  reporting depth             {self.reporting_depth} hops",
            f"  widest span of control      {self.widest_span[1]}  ({self.widest_span[0]})",
            f"  provenance depth            {self.provenance_depth} hops",
            f"  supersession chains         {self.supersession_chains}"
            f"  (longest {_hops(self.longest_supersession_chain)} hops)",
        ]
        defects = (
            len(self.dependency_cycles) + len(self.reporting_cycles)
            + len(self.provenance_cycles) + len(self.forked_supersessions)
        )
        if defects:
            lines.append(f"  structural defects          {defects}")
        return "\n".join(lines)


def _hops(chain: tuple[str, ...]) -> int:
    """A chain's length in edges. See ``Topology.reporting_depth``."""
    return max(0, len(chain) - 1)


def analyse(world: World) -> Topology:
    """Read every graph in *world* once."""
    dependencies = dependency_graph(world)
    reporting = reporting_graph(world)
    provenance = provenance_graph(world)
    supersession = supersession_graph(world)

    # Span of control: the manager with the most direct reports. In-degree,
    # because the reporting edge points from report to manager.
    spans = sorted(
        ((node, reporting.in_degree(node)) for node in reporting),
        key=lambda row: (-row[1], row[0]),
    )

    # A supersession "chain" is one weakly-connected component of the chain
    # graph: one fact and everything that replaced it, however long the run.
    chains = nx.number_weakly_connected_components(supersession) if supersession else 0

    provenance_chain = longest_chain(provenance)
    return Topology(
        services=criticality(world),
        chokepoints=chokepoints(dependencies),
        longest_dependency_chain=longest_chain(dependencies),
        dependency_cycles=cycles(dependencies),
        reporting_depth=_hops(longest_chain(reporting)),
        widest_span=spans[0] if spans else ("", 0),
        reporting_cycles=cycles(reporting),
        provenance_depth=_hops(provenance_chain),
        deepest_provenance_chain=provenance_chain,
        provenance_cycles=cycles(provenance),
        supersession_chains=chains,
        longest_supersession_chain=longest_chain(supersession),
        forked_supersessions=forks(supersession),
    )


__all__ = [
    "ServiceRank",
    "Topology",
    "analyse",
    "blast_radius",
    "chokepoints",
    "criticality",
    "cycles",
    "dependency_graph",
    "forks",
    "longest_chain",
    "provenance_graph",
    "reporting_graph",
    "roots",
    "supersession_graph",
    "supply_chain",
]
