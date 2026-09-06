"""The derivation-lineage family: value provenance as a multi-hop question.

``causal_multi_hop`` walks the event graph; nothing walked the *derivation*
graph — ``FactKindSpec.derive``, the declared record of which figures a figure
was computed from — even though the runner mints every link and the chain is
therefore recorded ground truth. These tests pin the traversal that closes
that: the family appears where lineage exists, every minted chain is a real
path in the derivation graph, a chain of fewer than three facts is never
minted (two facts is the identity ``identities`` already asks; one is a
lookup), a chain one document carries whole is refused, and the whole reading
regenerates byte-for-byte.

The P2P port is the measurement world — its spec declares eleven arithmetic
derivations, deep enough for a nine-hop chain — and the synthetic specs below
are the refusal discipline exercised at the exact boundary, which a shipped
spec cannot be trusted to sit on forever.
"""

from __future__ import annotations

from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace

import pytest

from worldloom import ProcureToPayWorld, benchmark, episodes
from worldloom.episodes import FactKindSpec, Invariant
from worldloom.ids import Minter
from worldloom.models import (
    ArtifactIntent,
    Authority,
    CanonicalFact,
    EvaluationType,
    Quantity,
)

EXAMPLES = Path(__file__).parent.parent / "examples" / "episodes"
P2P_PATH = EXAMPLES / "procure-to-pay.json"

PERIODS = ("2026-03", "2026-04")

#: The derived default's reasoning names the walk; an authored re-voice keeps
#: the derived reasoning unless it declares its own, so this is how a test
#: (and a reader of `evals.jsonl`) tells a chain case from the single-step
#: identities that share its wire value.
MARKER = "derivation hops"


@pytest.fixture(scope="module")
def p2p_spec() -> episodes.EpisodeSpec:
    specs = episodes.load(P2P_PATH)
    episodes.install(specs)
    return specs[0]


def _built(spec: episodes.EpisodeSpec):
    built = ProcureToPayWorld(seed=8128).build()
    for period in PERIODS:
        built = built.run(episodes.AuthoredEpisode(episode=spec.name, period=period))
    return built


@pytest.fixture(scope="module")
def p2p_world(p2p_spec: episodes.EpisodeSpec):
    return _built(p2p_spec)


def _lineage_cases(world) -> list:
    return [case for case in world.evaluations if MARKER in (case.reasoning or "")]


def _derive_edges(spec: episodes.EpisodeSpec) -> dict[str, set[str]]:
    """The derivation graph, reparsed from the spec independently of benchmark.py.

    Every ``derive`` head, not just the ones the family walks — the check below
    is that a minted chain's every link is a declared edge, and a link the
    family should not have walked (a ``prior``, a supersession reading) would
    still parse here and then fail the stricter per-head assertions.
    """
    edges: dict[str, set[str]] = {}
    for fk in spec.fact_kinds:
        if not fk.derive:
            continue
        _, _, rest = fk.derive.partition("(")
        edges[fk.kind] = {part.strip() for part in rest.rstrip(")").split(",") if part.strip()}
    return edges


# ---------------------------------------------------------------------------
# The family, on a world whose ledger holds lineage
# ---------------------------------------------------------------------------


def test_the_family_appears_where_lineage_exists(p2p_world) -> None:
    """The headline: a corpus with declared derivations gains chain questions.

    One per period on the P2P port — the spec holds four derivation heads and
    three of them are refused for real reasons (two land in no document, one
    bottoms out after a single hop), so the count is what the graph supports
    rather than the cap.
    """
    chains = _lineage_cases(p2p_world)
    assert len(chains) == len(PERIODS), [case.id for case in chains]
    for case in chains:
        # The wire value is `cross_artifact` — see `benchmark.LINEAGE_FAMILY`
        # for why the family publishes under the family whose definition it
        # generalises rather than widening the thin waist's enum from here.
        assert case.evaluation_type is EvaluationType.CROSS_ARTIFACT
        assert case.difficulty == "hard"
        assert not case.expects_abstention
    # And each period asks its own: the period is in the sentence, so a
    # benchmark that grows by a period gains questions, not photocopies.
    questions = {case.question for case in chains}
    assert len(questions) == len(chains)
    for period in PERIODS:
        assert any(period in case.question for case in chains), period


def test_every_minted_chain_is_a_real_path_in_the_derivation_graph(
    p2p_spec: episodes.EpisodeSpec, p2p_world
) -> None:
    """The expected facts are the chain, and the chain is in the spec.

    Rebuilds the derive edges from the spec JSON and requires every
    consecutive pair of cited facts to be one: fact *i* of the answer is an
    operand of the derivation that produced fact *i+1*. A case this check
    fails on would be a lineage question whose answer key asserts provenance
    the runner never computed — the one defect no retriever score reveals.
    """
    edges = _derive_edges(p2p_spec)
    facts = {fact.id: fact for fact in p2p_world.facts}

    checked = 0
    for case in _lineage_cases(p2p_world):
        chain = [facts[fact_id] for fact_id in case.expected_fact_ids]
        assert len(chain) >= 3, case.question
        for earlier, later in pairwise(chain):
            assert earlier.kind in edges.get(later.kind, set()), (
                later.kind, earlier.kind, case.question,
            )
            # Same period's live figures: the walk may not cite a closed value
            # or reach across periods — those are `temporal_state`'s questions.
            assert later.valid_to is None and earlier.valid_to is None
        # The answer states the intermediate values, not only the endpoints —
        # "through what intermediate figures" is the family's second half.
        assert f"{len(chain) - 1} hops" in (case.expected_answer or "")
        checked += 1
    assert checked >= len(PERIODS)


def test_a_chain_spans_documents_and_none_carries_it_whole(p2p_world) -> None:
    """The refusal that keeps the shared wire value honest.

    Every expected fact is carried by some required artifact, the chain spans
    at least two documents, and no single document carries every link — a
    workbook stating the whole path would make the question a table read, and
    a `cross_artifact` case answerable from one artifact would be the family's
    name telling a lie.
    """
    carriers: dict[str, set[str]] = {}
    for intent in p2p_world.artifact_intents:
        for fact_id in intent.required_fact_ids:
            carriers.setdefault(fact_id, set()).add(intent.id)

    for case in _lineage_cases(p2p_world):
        required = set(case.required_artifact_ids)
        # Intersected with `required` because the corpus-wide map above sees
        # every period: a standing fact (the contract rate) gains carriers in
        # later periods, while the walk snapshots carriers at mint time — and
        # `required` is that snapshot, since an intent's fact list never
        # changes after planning.
        held = [
            carriers.get(fact_id, set()) & required
            for fact_id in case.expected_fact_ids
        ]
        assert all(held), case.question
        assert len(set().union(*held)) >= 2, case.question
        assert not set.intersection(*held), (
            "one document carries the whole chain", case.question,
        )
        assert not required & set(case.distractor_artifact_ids)


def test_the_benchmark_regenerates_byte_for_byte(p2p_spec, p2p_world) -> None:
    """Two builds from one seed are one benchmark.

    The walk iterates declaration order with id tie-breaks throughout; a set
    iteration anywhere in it would show up here as two worlds disagreeing
    about which chain got minted first.
    """
    again = _built(p2p_spec)
    ours = [case.model_dump(mode="json") for case in p2p_world.evaluations]
    theirs = [case.model_dump(mode="json") for case in again.evaluations]
    assert ours == theirs
    assert _lineage_cases(again), "the rebuilt world lost the family"


# ---------------------------------------------------------------------------
# The refusal discipline, at the exact boundary
# ---------------------------------------------------------------------------

_WHEN = datetime(2026, 3, 31, 12, 0, tzinfo=UTC)


def _kind(kind: str, derive: str = "") -> FactKindSpec:
    return FactKindSpec(
        kind=kind, value_type="money", derive=derive,
        invariants=[Invariant(kind="holds-at")],
    )


def _fact(fact_id: str, kind: str, amount: float) -> CanonicalFact:
    return CanonicalFact(
        id=fact_id, kind=kind, subject="COMP-0001", period="2026-03",
        value=Quantity(amount=amount, unit="AUD_thousands"),
        valid_from=_WHEN, authority=Authority.SYSTEM_OF_RECORD,
    )


def _intent(intent_id: str, fact_ids: list[str]) -> ArtifactIntent:
    return ArtifactIntent(
        id=intent_id, artifact_type="working_paper", domain="test",
        audience="finance", author_id="PERSON-0001", required_fact_ids=fact_ids,
    )


def _derived(kinds, facts, intents, evaluation=None):
    spec = SimpleNamespace(
        fact_kinds=list(kinds), evaluation=evaluation or benchmark.EvalSpec()
    )
    return benchmark.derive(
        spec, minter=Minter(), period="2026-03",
        facts=list(facts), events=[], intents=list(intents),
    )


#: One declared step and its two operands — a real derivation, and exactly the
#: shape `identities` already asks about. The values satisfy the arithmetic so
#: the fixture stays an honest ledger even though nothing here recomputes it.
TWO_HOP_KINDS = (
    _kind("t.left"), _kind("t.right"),
    _kind("t.mid", derive="plus(t.left, t.right)"),
)
TWO_HOP_FACTS = (
    _fact("FACT-0001", "t.left", 60.0),
    _fact("FACT-0002", "t.right", 40.0),
    _fact("FACT-0003", "t.mid", 100.0),
)

#: The two-hop ledger extended one declared step: `t.top` rests on `t.mid`
#: rests on `t.left` — the shortest chain the family may mint.
THREE_HOP_KINDS = (
    *TWO_HOP_KINDS,
    _kind("t.side"),
    _kind("t.top", derive="plus(t.mid, t.side)"),
)
THREE_HOP_FACTS = (
    *TWO_HOP_FACTS,
    _fact("FACT-0004", "t.side", 25.0),
    _fact("FACT-0005", "t.top", 125.0),
)


def test_a_two_fact_chain_is_never_minted() -> None:
    """Two facts is one declared step — the identity, already asked — and the
    family refuses it rather than re-asking it under a harder name."""
    cases = _derived(
        TWO_HOP_KINDS, TWO_HOP_FACTS,
        [_intent("ART-0001", ["FACT-0003"]),
         _intent("ART-0002", ["FACT-0001", "FACT-0002"])],
    )
    assert cases, "the identity family should still ask its one step"
    assert not [c for c in cases if MARKER in (c.reasoning or "")]


def test_a_three_fact_chain_is_the_minimum_and_is_minted() -> None:
    """The boundary from the other side, on the same ledger plus one link."""
    cases = _derived(
        THREE_HOP_KINDS, THREE_HOP_FACTS,
        [_intent("ART-0001", ["FACT-0005"]),
         _intent("ART-0002", ["FACT-0001", "FACT-0002", "FACT-0003", "FACT-0004"])],
    )
    chains = [c for c in cases if MARKER in (c.reasoning or "")]
    assert len(chains) == 1
    assert chains[0].expected_fact_ids == ["FACT-0001", "FACT-0003", "FACT-0005"]
    assert chains[0].evaluation_type is EvaluationType.CROSS_ARTIFACT


def test_a_chain_one_document_carries_whole_is_refused() -> None:
    """Same ledger, same chain, one filing cabinet: when a single document
    carries every link the question is a table read, and the family refuses it
    instead of shipping a hard label on an easy case."""
    everything = ["FACT-0001", "FACT-0002", "FACT-0003", "FACT-0004", "FACT-0005"]
    cases = _derived(
        THREE_HOP_KINDS, THREE_HOP_FACTS,
        [_intent("ART-0001", everything),
         _intent("ART-0002", ["FACT-0001"])],
    )
    assert not [c for c in cases if MARKER in (c.reasoning or "")]


def test_an_ambiguous_link_breaks_the_walk_there() -> None:
    """A kind with two live facts this period (a per-unit roll-up) cannot be a
    link: the walk would have to pick one and assert a provenance that holds
    only for the pick. The chain shortens to the ambiguity and, at under three
    facts, is refused."""
    second_mid = CanonicalFact(
        id="FACT-0006", kind="t.mid", subject="UNIT-0002", period="2026-03",
        value=Quantity(amount=50.0, unit="AUD_thousands"),
        valid_from=_WHEN, authority=Authority.SYSTEM_OF_RECORD,
    )
    cases = _derived(
        THREE_HOP_KINDS, (*THREE_HOP_FACTS, second_mid),
        [_intent("ART-0001", ["FACT-0005"]),
         _intent("ART-0002", ["FACT-0001", "FACT-0002", "FACT-0003",
                              "FACT-0004", "FACT-0006"])],
    )
    assert not [c for c in cases if MARKER in (c.reasoning or "")]


def test_the_authored_surface_treats_the_family_as_its_own() -> None:
    """Emphasis and phrasing key on `derivation_lineage`, not on the shared
    wire value — an author caps or re-voices the chains without touching the
    single-step identity questions beside them, and the lint accepts the name."""
    intents = [
        _intent("ART-0001", ["FACT-0005"]),
        _intent("ART-0002", ["FACT-0001", "FACT-0002", "FACT-0003", "FACT-0004"]),
    ]

    capped = _derived(
        THREE_HOP_KINDS, THREE_HOP_FACTS, intents,
        evaluation=benchmark.EvalSpec(emphasis={benchmark.LINEAGE_FAMILY: 0}),
    )
    assert not [c for c in capped if MARKER in (c.reasoning or "")]
    assert any(
        c.evaluation_type in (EvaluationType.CROSS_ARTIFACT,
                              EvaluationType.NUMERICAL_COMPARISON)
        for c in capped
    ), "capping the chains must not cap the identities"

    voiced = _derived(
        THREE_HOP_KINDS, THREE_HOP_FACTS, intents,
        evaluation=benchmark.EvalSpec(families=[benchmark.QuestionFamily(
            family="derivation_lineage",
            question="Trace the {phrase} for {period} back {hops} steps.",
        )]),
    )
    assert any(
        c.question == "Trace the top for 2026-03 back 2 steps." for c in voiced
    ), [c.question for c in voiced]

    assert benchmark.lint(benchmark.EvalSpec(
        emphasis={benchmark.LINEAGE_FAMILY: 1},
    )) == []


def test_the_lineage_slots_are_linted_like_any_familys() -> None:
    """A template naming a slot the walk never fills is refused at lint time,
    with the vocabulary that was available — hours before a build would have
    raised inside `str.format`."""
    findings = benchmark.lint(benchmark.EvalSpec(
        families=[benchmark.QuestionFamily(
            family="derivation_lineage",
            question="What moved the {phrase} via {rival}?",
        )],
    ))
    assert any("'rival'" in f or "['rival']" in f for f in findings), findings
    assert any("origin" in f for f in findings), findings
