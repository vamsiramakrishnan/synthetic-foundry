"""The benchmark, derived — the gap docs/episode-grammar.md measured twice.

An authored process produced **zero** evaluation cases against the engine
episode's eleven per period, in both proofs. These tests pin what closes it:
the seven families are read out of the fact graph rather than templated per
vertical, so a process that authors *nothing* about evaluation still ships a
benchmark; the declared `EvalSpec` re-voices and prioritises without being able
to invent a case the corpus cannot answer; and every derived case survives the
same gates the four hand-written taxonomies do.

The two ported specs are the two measurements. `ProcureToPay` declares an
`EvalSpec`; `QuarterlyCapitalReturn` declares none, which is the more important
of the two — it is the "for free" claim, unassisted.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

import pytest

from worldloom import BankingWorld, ProcureToPayWorld, benchmark, episodes
from worldloom.models import AUTHORITY_RANK, EvaluationType

EXAMPLES = Path(__file__).parent.parent / "examples" / "episodes"
P2P_PATH = EXAMPLES / "procure-to-pay.json"
CAPITAL_PATH = EXAMPLES / "quarterly-capital-return.json"

PERIODS = ("2026-03", "2026-04", "2026-05")


@pytest.fixture(scope="module")
def p2p_spec() -> episodes.EpisodeSpec:
    specs = episodes.load(P2P_PATH)
    episodes.install(specs)
    return specs[0]


@pytest.fixture(scope="module")
def p2p_world(p2p_spec: episodes.EpisodeSpec):
    built = ProcureToPayWorld(seed=8128).build()
    for period in PERIODS:
        built = built.run(episodes.AuthoredEpisode(episode=p2p_spec.name, period=period))
    return built


@pytest.fixture(scope="module")
def capital_spec() -> episodes.EpisodeSpec:
    specs = episodes.load(CAPITAL_PATH)
    episodes.install(specs)
    return specs[0]


@pytest.fixture(scope="module")
def capital_world(capital_spec: episodes.EpisodeSpec):
    return BankingWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode=capital_spec.name, period="2026-03")
    )


# ---------------------------------------------------------------------------
# The measurement the gap was stated in
# ---------------------------------------------------------------------------


def test_the_port_that_produced_no_cases_now_produces_a_benchmark(p2p_world) -> None:
    """The headline, pinned as a number rather than as a claim.

    The engine's own taxonomy produces 11 cases per period over nine types
    (`generators/procurement_evaluation.py`, measured in the grammar doc); the
    port produced 0. These are the counts the derivation plus the port's
    authored `EvalSpec` actually reach — held to a floor rather than to an
    exact figure, because the derivation reads a graph and a graph that grows
    should be allowed to ask more.
    """
    cases = list(p2p_world.evaluations)
    assert len(cases) >= 11 * len(PERIODS)

    mix = Counter(case.evaluation_type for case in cases)
    # Seven derived families plus the authored abstention. The abstention is
    # the one that cannot be derived at all — see `benchmark.AbstentionSpec` —
    # so its presence here is evidence the authored half is wired, not that
    # the derivation got cleverer.
    assert set(mix) == set(benchmark.DERIVED_FAMILIES) | {
        EvaluationType.EXPECTED_ABSTENTION
    }
    for family in benchmark.DERIVED_FAMILIES:
        assert mix[family] >= len(PERIODS), (family, mix)


def test_a_process_that_authors_nothing_about_evaluation_still_gets_one(
    capital_spec: episodes.EpisodeSpec, capital_world
) -> None:
    """The "for free" claim, unassisted.

    `QuarterlyCapitalReturn` declares no `EvalSpec` at all — its JSON has no
    `evaluation` key — and one quarter of it still carries a multi-family
    benchmark, because every family is a shape in the graph rather than a
    template in a vertical's Python module. This is the property that makes
    authoring an industry produce a benchmark rather than a document pile.
    """
    assert capital_spec.evaluation == benchmark.EvalSpec()
    cases = list(capital_world.evaluations)
    assert len(cases) >= 10
    assert len(Counter(case.evaluation_type for case in cases)) >= 5
    # Nothing authored, so nothing abstains: an absence has no witness in a
    # fact graph and the derivation refuses to invent one.
    assert not any(case.expects_abstention for case in cases)


# ---------------------------------------------------------------------------
# What each family claims about the graph, checked against the graph
# ---------------------------------------------------------------------------


def test_every_authority_case_really_has_a_rival_document(p2p_world) -> None:
    """The family's definition, recomputed from the world.

    An authority-resolution case asserts that some *other* artifact carries a
    different-authority fact about the same subject. If that is not true of the
    world, the case is a lookup wearing a hard family's name and the scorecard
    reports the corpus as harder than it is.
    """
    carriers: dict[str, set[str]] = {}
    for intent in p2p_world.artifact_intents:
        for fact_id in intent.required_fact_ids:
            carriers.setdefault(fact_id, set()).add(intent.id)
    facts = {fact.id: fact for fact in p2p_world.facts}

    checked = 0
    for case in p2p_world.evaluations:
        if case.evaluation_type is not EvaluationType.AUTHORITY_RESOLUTION:
            continue
        answer = facts[case.expected_fact_ids[0]]
        rivals = [
            other for other in p2p_world.facts
            if other.subject == answer.subject
            and other.id != answer.id
            and other.authority is not answer.authority
            and carriers.get(other.id, set()) - carriers.get(answer.id, set())
        ]
        assert rivals, case.question
        assert case.distractor_artifact_ids, case.question
        checked += 1
    assert checked >= len(PERIODS)


def test_every_temporal_cutoff_sits_inside_the_window_it_asks_about(p2p_world) -> None:
    """`validate`'s `answer_unavailable_at_cutoff`, applied before minting.

    A cut-off outside the expected fact's window makes the question
    unanswerable at the moment it is asked. The derivation takes the midpoint
    of a closed window precisely so this holds, and the validator recomputes
    it — but a test that only ran the validator would pass on a corpus that
    happened to have no closed facts.
    """
    facts = {fact.id: fact for fact in p2p_world.facts}
    closed = 0
    for case in p2p_world.evaluations:
        if case.temporal_cutoff is None:
            continue
        for fact_id in case.expected_fact_ids:
            assert facts[fact_id].holds_at(case.temporal_cutoff), case.question
            closed += facts[fact_id].valid_to is not None
    assert closed >= len(PERIODS), "no case asked about a window that actually closed"


def test_every_causal_case_walks_a_real_chain_of_causes(p2p_world) -> None:
    """A path in the event graph, not a phrase containing the word "chain".

    The answer names the events in order; this rebuilds the `caused_by` edges
    from the world and requires the named sequence to be one of them.
    """
    events = {event.id: event for event in p2p_world.events}
    cause_of = {
        event.id: (event.caused_by[0] if event.caused_by else None)
        for event in p2p_world.events
    }
    kinds = {event.kind.replace("_", " ").replace(".", " ") for event in p2p_world.events}

    checked = 0
    for case in p2p_world.evaluations:
        if case.evaluation_type is not EvaluationType.CAUSAL_MULTI_HOP:
            continue
        steps = (case.expected_answer or "").split(" — ")[0].split(" → ")
        assert len(steps) >= 3, case.expected_answer
        assert set(steps) <= kinds, steps
        # And the world really does chain them: walking backwards from the
        # terminal event of the same kind reproduces the sequence.
        terminal = next(
            e for e in reversed(list(p2p_world.events))
            if e.kind.replace("_", " ").replace(".", " ") == steps[-1]
        )
        walked = []
        cursor = terminal.id
        while cursor is not None and cursor in events:
            walked.append(events[cursor].kind.replace("_", " ").replace(".", " "))
            cursor = cause_of.get(cursor)
        walked.reverse()
        assert walked[-len(steps):] == steps, (walked, steps)
        checked += 1
    assert checked >= len(PERIODS)


def test_every_identity_case_actually_holds_to_the_cent(p2p_world) -> None:
    """The arithmetic families assert an identity; the identity is recomputed.

    Every derived numerical and cross-artifact case comes from a declared
    `FactKindSpec.derive`, which the runner evaluates and the derived check
    group recomputes. A case that stated an identity the ledger does not hold
    would be a benchmark with a wrong answer key — the one defect no retriever
    score would ever reveal.
    """
    facts = {fact.id: fact for fact in p2p_world.facts}
    checked = 0
    for case in p2p_world.evaluations:
        if case.evaluation_type not in (
            EvaluationType.NUMERICAL_COMPARISON, EvaluationType.CROSS_ARTIFACT
        ):
            continue
        cited = [facts[i] for i in case.expected_fact_ids]
        if len(cited) != 3 or any(f.value is None for f in cited):
            continue
        total, left, right = (f.value.amount for f in cited)
        assert any(
            abs(total - candidate) < 0.02
            for candidate in (
                left + right, left - right, left * right / 1000,
                left * right / 100, right and left / right * 100,
            )
        ), (case.question, total, left, right)
        checked += 1
    assert checked >= len(PERIODS)


def test_a_direct_lookup_never_reuses_a_harder_familys_evidence(p2p_world) -> None:
    """The floor stays a floor.

    A fact that is the answer to a contested question must not also be the
    answer to a lookup: the same evidence behind an easy question makes the
    hard family read as easier than the corpus makes it. The derivation runs
    hardest-first and claims the kinds it asked about; this is that ordering,
    checked rather than trusted.
    """
    claimed = {
        fact_id
        for case in p2p_world.evaluations
        if case.evaluation_type in (
            EvaluationType.AUTHORITY_RESOLUTION, EvaluationType.TEMPORAL_STATE,
            EvaluationType.CROSS_ARTIFACT, EvaluationType.NUMERICAL_COMPARISON,
        )
        for fact_id in case.expected_fact_ids
    }
    for case in p2p_world.evaluations:
        if case.evaluation_type is EvaluationType.DIRECT_LOOKUP:
            assert not set(case.expected_fact_ids) & claimed, case.question


def test_no_question_is_asked_twice_in_the_corpus(p2p_world) -> None:
    """A benchmark that grows by a period gains questions, not photocopies.

    Found by the property above rather than reasoned about in advance: the
    across-period temporal family restated an earlier period's direct lookup
    word for word — same string, same evidence, two families, two
    difficulties — because the across-period vantage and the lookup vantage
    happen to phrase the same fact identically once the period is in the
    sentence. A scorecard counting that twice reports a benchmark larger than
    the corpus supports.

    Deliberately *not* also a claim that no two cases share evidence: banking's
    contested pair rests two questions on one ratio on purpose, and that is the
    hardest shape this repository knows how to build.
    """
    questions = [case.question for case in p2p_world.evaluations]
    assert len(questions) == len(set(questions))


# ---------------------------------------------------------------------------
# The authored half, and the boundary it may not cross
# ---------------------------------------------------------------------------


def test_the_authored_spec_revoices_without_moving_the_answer(
    p2p_spec: episodes.EpisodeSpec, p2p_world
) -> None:
    """A declared family changes the English and nothing else.

    The port's `EvalSpec` names `p2p.contract_rate` as the authority question
    this vertical exists for; the question that comes out is the sentence a
    purchasing department would say, and the fact it expects is still the one
    the graph chose.
    """
    assert p2p_spec.evaluation.families, "the port declares its phrasing"
    contested = [
        case for case in p2p_world.evaluations
        if "contractually obliged to pay" in case.question
    ]
    assert len(contested) == len(PERIODS)
    facts = {fact.id: fact for fact in p2p_world.facts}
    for case in contested:
        assert case.evaluation_type is EvaluationType.AUTHORITY_RESOLUTION
        assert [facts[i].kind for i in case.expected_fact_ids] == ["p2p.contract_rate"]
        # And it is the rank inversion, not merely a contest: the tempting
        # wrong document outranks the right one.
        answer = facts[case.expected_fact_ids[0]]
        rivals = [
            f for f in p2p_world.facts
            if f.subject == answer.subject
            and AUTHORITY_RANK[f.authority] > AUTHORITY_RANK[answer.authority]
        ]
        assert rivals, case.question


def test_naming_a_kind_the_graph_has_no_contest_about_mints_nothing(
    p2p_spec: episodes.EpisodeSpec,
) -> None:
    """`about` is a priority, never a source.

    An author may bring a kind forward past a family's cap. What they may not
    do is conjure a case: a family naming a kind about which the graph holds no
    contest derives nothing, because a question the corpus cannot answer is the
    one thing this module refuses to produce.
    """
    wishful = p2p_spec.model_copy(update={
        "evaluation": benchmark.EvalSpec(
            families=[benchmark.QuestionFamily(
                family="authority_resolution",
                about=["close.delay"],
                question="Whose fault was the delay?",
            )],
        ),
    })
    episodes.install([wishful.model_copy(update={"name": "WishfulProcureToPay"})])
    world = ProcureToPayWorld(seed=8128).build().run(
        episodes.AuthoredEpisode(episode="WishfulProcureToPay", period="2026-03")
    )
    assert not any(
        case.question == "Whose fault was the delay?" for case in world.evaluations
    )
    assert world.validate().ok


def test_a_family_naming_an_unregistered_kind_is_lint_refused(
    p2p_spec: episodes.EpisodeSpec,
) -> None:
    """The `factkinds` defence, extended to the benchmark.

    The lint that let a spec cite two invented kinds is why the registry
    exists. A question family is exactly the same hazard one layer over: a
    plausible-looking kind name in an `about` list would silently phrase
    nothing forever.
    """
    broken = p2p_spec.model_copy(update={
        "evaluation": benchmark.EvalSpec(
            families=[benchmark.QuestionFamily(
                family="direct_lookup", about=["p2p.imagined_kind"], question="?",
            )],
            skip_kinds=["p2p.also_imagined"],
        ),
    })
    findings = episodes.lint([broken], base="procurement")
    assert any("p2p.imagined_kind" in f and "registry" in f for f in findings), findings
    assert any("p2p.also_imagined" in f for f in findings), findings


def test_a_template_naming_a_slot_the_derivation_never_fills_is_refused() -> None:
    """A `str.format` template is executable data, and a bad one raises inside
    a build hours after it was written. The lint reads the slots statically and
    names both the offender and what was available instead."""
    findings = benchmark.lint(benchmark.EvalSpec(
        families=[benchmark.QuestionFamily(
            family="temporal_state",
            question="What did {subject} say about {rival} at {at}?",
        )],
    ))
    assert any("'rival'" in f or "['rival']" in f for f in findings), findings
    assert all("at" in f for f in findings)


def test_an_abstention_may_not_be_interpolated() -> None:
    """An abstention is authored whole because there is no case to fill it
    from — a slot here would interpolate a question that, by construction, the
    derivation never built."""
    findings = benchmark.lint(benchmark.EvalSpec(
        abstentions=[benchmark.AbstentionSpec(
            question="What did {subject} pay?", reasoning="Never recorded.",
        )],
    ))
    assert any("authored whole" in f for f in findings), findings


# ---------------------------------------------------------------------------
# The gates every taxonomy in this repository ends at
# ---------------------------------------------------------------------------


def test_the_derived_benchmark_validates_and_replays(p2p_world) -> None:
    """Evaluation cases are corpus bytes, so they are held to the corpus's
    rules: every expected fact reachable, no document both source and
    distractor, every cut-off inside its window — and the whole set
    regenerates byte-for-byte from the recipe with no benchmark file on hand."""
    from worldloom import recipe

    assert p2p_world.validate().ok
    again = recipe.rebuild(recipe=p2p_world.recipe)
    assert tuple(again._evaluations) == tuple(p2p_world._evaluations)


def test_the_three_reachability_gates_agree(p2p_world) -> None:
    """`benchmark`, `generators/cases` and `validate` each compute "which facts
    can a question expect". Three copies is two too many in principle; what
    keeps them honest is that they are the same four lines over one field, and
    this is the test that says so."""
    from worldloom.generators import cases as generator_cases

    intents = tuple(p2p_world.artifact_intents)
    assert benchmark.reachable_fact_ids(intents) == generator_cases.reachable_fact_ids(intents)

    validator_view: set[str] = set()
    for intent in intents:
        validator_view.update(intent.required_fact_ids)
    assert benchmark.reachable_fact_ids(intents) == frozenset(validator_view)

    for case in p2p_world.evaluations:
        assert set(case.expected_fact_ids) <= validator_view


def test_the_spec_round_trips_through_json_with_its_benchmark(
    p2p_spec: episodes.EpisodeSpec,
) -> None:
    """The declaration is pack-carried data, like `detail_tables` — so it has
    to survive the trip a pack takes."""
    reloaded = episodes.load(json.loads(json.dumps(
        {"episodes": [p2p_spec.model_dump(mode="json")]}
    )))
    assert reloaded[0].evaluation == p2p_spec.evaluation
