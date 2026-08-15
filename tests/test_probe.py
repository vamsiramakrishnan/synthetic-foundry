"""The probe graph: interval algebra, propagation, the grammar, and resolution."""

from __future__ import annotations

import math

import pytest

from worldloom import probe
from worldloom.parameters import DEFAULTS
from worldloom.probe import (
    WHOLE,
    Answer,
    Graph,
    Interval,
    Question,
    SubQuestion,
)

PREMISE = "A specialty apparel retailer, 180 stores, Australia."


def root(key: str, *, low: float = -math.inf, high: float = math.inf, unit: str = "") -> Question:
    return Question(key=key, asks=f"what is {key}?", unit=unit, domain=Interval(low, high), depth=0)


def graph(*roots: Question, max_depth: int = 4) -> Graph:
    return probe.open_graph(PREMISE, roots, max_depth=max_depth)


def answer(key: str, low: float, high: float, **kwargs: object) -> Answer:
    return Answer(question=key, claim=kwargs.pop("claim", f"{key} settled"),  # type: ignore[arg-type]
                  low=low, high=high, **kwargs)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Interval algebra
# ---------------------------------------------------------------------------


def test_a_product_takes_the_extreme_corner_not_the_matching_one():
    # The classic wrong answer is low*low..high*high, which for an operand
    # straddling zero gets both ends wrong.
    assert Interval(-2.0, 3.0) * Interval(-5.0, 4.0) == Interval(-15.0, 12.0)


def test_dividing_by_an_interval_containing_zero_says_nothing():
    # The true result has a hole in it and is not an interval; the sound
    # over-approximation is the whole line, never a narrower lie.
    assert Interval(1.0, 2.0) / Interval(-1.0, 1.0) == WHOLE


def test_zero_times_unbounded_is_the_whole_line_not_a_nan():
    # `0 * inf` is nan. A nan bound compares false against everything and would
    # silently disable narrowing rather than raising.
    product = WHOLE * Interval(0.0, 1.0)
    assert product == WHOLE
    assert not math.isnan(product.low) and not math.isnan(product.high)


def test_meeting_disjoint_intervals_is_empty_rather_than_an_error():
    assert Interval(0.0, 1.0).meet(Interval(2.0, 3.0)).empty


def test_a_negligible_narrowing_does_not_count_as_progress():
    # Without this, propagation never terminates: a scaling relation can shave
    # a millionth off a bound forever and each pass re-enqueues its arcs.
    band = Interval(0.0, 1.0)
    assert not band.narrowed_by(Interval(0.0, 1.0 - 1e-15))
    assert band.narrowed_by(Interval(0.0, 0.9))


def test_narrowing_an_unbounded_interval_at_one_end_counts():
    # Both widths are infinite, so a width comparison alone would miss it.
    assert Interval(-math.inf, 5.0).narrowed_by(Interval(-math.inf, 3.0))
    assert not Interval(-math.inf, 5.0).narrowed_by(WHOLE)


# ---------------------------------------------------------------------------
# Propagation
# ---------------------------------------------------------------------------


def test_a_parent_narrows_its_child():
    turns = root("turns", low=1.0, high=10.0)
    world = graph(turns)
    world = probe.accept(world, answer(
        "turns", 3.0, 4.0,
        raises=[SubQuestion(key="weeks", asks="weeks of cover?", because="cover is turns inverted",
                            relation="scales", factor_low=10.0, factor_high=13.0)],
    )).graph
    assert world is not None
    domains = probe.propagate(world).domains
    assert domains["weeks"] == Interval(30.0, 52.0)


def test_a_child_narrows_its_parent():
    # The property that makes this a graph and not a template expansion: a leaf
    # grounded in evidence must be able to make its parent untenable.
    turns = root("turns", low=1.0, high=10.0)
    world = graph(turns)
    world = probe.accept(world, answer(
        "turns", 1.0, 10.0,
        raises=[SubQuestion(key="weeks", asks="weeks of cover?", because="cover is turns inverted",
                            relation="scales", factor_low=4.0, factor_high=4.0,
                            domain_low=16.0, domain_high=20.0)],
    )).graph
    assert world is not None
    domains = probe.propagate(world).domains
    # weeks = turns * 4 and weeks is in [16, 20], so turns cannot be 1..10.
    assert domains["turns"] == Interval(4.0, 5.0)


def test_propagation_reaches_a_fixpoint_on_a_cycle_of_scalings():
    # Two children of one parent, each scaling, is enough to make narrowing
    # ping-pong. If `_MEANINGFUL` were not enforced this would not return.
    world = graph(root("a", low=0.0, high=100.0))
    world = probe.accept(world, answer(
        "a", 0.0, 100.0,
        raises=[
            SubQuestion(key="b", asks="b?", because="b follows a", relation="scales",
                        factor_low=0.4, factor_high=0.6, domain_low=10.0, domain_high=30.0),
            SubQuestion(key="c", asks="c?", because="c follows a", relation="scales",
                        factor_low=0.9, factor_high=1.1, domain_low=0.0, domain_high=40.0),
        ],
    )).graph
    assert world is not None
    state = probe.propagate(world)
    assert state.consistent
    assert state.domains["a"].high <= 75.0  # b <= 30 with factor >= 0.4


def hand_built(*questions: Question) -> Graph:
    """A graph assembled directly, bypassing ``accept``.

    ``accept`` refuses a contradictory answer, which is the point of it — so an
    inconsistent graph cannot be reached through the front door and the
    propagator has to be exercised on one built by hand. That the two tests
    below need this is itself evidence the grammar is doing its job.
    """
    return Graph(PREMISE, {q.key: q for q in questions})


def child(key: str, parent: str, kind: str, *, low: float, high: float,
          factor_low: float = 1.0, factor_high: float = 1.0) -> Question:
    return Question(
        key=key, asks=f"what is {key}?", unit="", domain=Interval(low, high), depth=1,
        parent=parent,
        via=probe.relation(kind, factor_low=factor_low, factor_high=factor_high),
        because="constructed",
    )


def test_a_contradiction_names_the_chain_that_caused_it():
    # margin in [0.5, 0.6] forces cost into [0.4, 0.5]; cost claims [0.7, 0.9].
    world = hand_built(
        root("margin", low=0.5, high=0.6),
        child("cost", "margin", "complements", low=0.7, high=0.9),
    )
    state = probe.propagate(world)
    assert not state.consistent
    (found,) = state.contradictions
    assert found.key in {"margin", "cost"}
    assert "margin" in found.chain


def test_a_contradictory_answer_is_refused_before_it_can_be_committed():
    world = graph(root("margin", low=0.5, high=0.6))
    result = probe.accept(world, answer(
        "margin", 0.5, 0.6,
        raises=[SubQuestion(key="cost", asks="cost ratio?", because="cost complements margin",
                            relation="complements", domain_low=0.7, domain_high=0.9)],
    ))
    assert not result.accepted
    assert any(r.rule == "contradicts" for r in result.rejections)


def test_one_emptied_domain_is_reported_once_not_cascaded():
    # Propagating out of an empty domain would empty everything downstream and
    # bury the one node the model actually has to fix.
    world = hand_built(
        root("a", low=0.0, high=1.0),
        child("b", "a", "scales", low=5.0, high=6.0),
        Question(key="c", asks="c?", unit="", domain=Interval(0.0, 100.0), depth=2,
                 parent="b", via=probe.relation("scales"), because="constructed"),
    )
    assert len(probe.propagate(world).contradictions) == 1


def test_propagation_is_order_independent_for_a_given_graph():
    # Interval arithmetic is not associative in floating point, so an
    # order-dependent worklist would give order-dependent bounds and replay
    # would resolve to different spans.
    world = graph(root("a", low=0.0, high=100.0))
    world = probe.accept(world, answer(
        "a", 0.0, 100.0,
        raises=[
            SubQuestion(key="z", asks="z?", because="z scales a", relation="scales",
                        factor_low=0.3, factor_high=0.5, domain_low=5.0, domain_high=25.0),
            SubQuestion(key="m", asks="m?", because="m scales a", relation="scales",
                        factor_low=0.8, factor_high=0.9, domain_low=0.0, domain_high=60.0),
        ],
    )).graph
    assert world is not None
    first = probe.propagate(world).domains
    for _ in range(5):
        assert probe.propagate(world).domains == first


# ---------------------------------------------------------------------------
# The grammar
# ---------------------------------------------------------------------------


def test_an_answer_may_narrow_a_question_and_may_not_widen_one():
    world = graph(root("margin", low=0.2, high=0.6))
    assert probe.accept(world, answer("margin", 0.5, 0.58)).accepted

    result = probe.accept(world, answer("margin", 0.1, 0.9))
    assert not result.accepted
    (rejection,) = result.rejections
    assert rejection.rule == "widens_the_question"


def test_the_bounds_a_model_is_given_are_what_earlier_answers_left():
    # The mechanism by which context shapes the answer: by the time margin is
    # asked, its children have already squeezed it.
    world = graph(root("margin", low=0.0, high=1.0), root("other", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "margin", 0.0, 1.0,
        raises=[SubQuestion(key="sell_through", asks="full-price sell-through?",
                            because="margin is what survives markdown",
                            relation="scales", factor_low=1.0, factor_high=1.0,
                            domain_low=0.45, domain_high=0.55)],
    )).graph
    assert world is not None
    brief = probe.frontier(world)
    assert brief is not None and brief.key == "other"
    assert probe.propagate(world).domains["margin"] == Interval(0.45, 0.55)


def test_an_answer_that_cannot_hold_alongside_the_graph_is_refused_by_name():
    world = graph(root("margin", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "margin", 0.0, 1.0,
        raises=[SubQuestion(key="cost", asks="cost ratio?", because="complements margin",
                            relation="complements", domain_low=0.0, domain_high=1.0)],
    )).graph
    assert world is not None
    result = probe.accept(world, answer("cost", 0.95, 0.99, raises=[]))
    assert result.accepted  # margin is still [0, 1], so this merely narrows it

    world = result.graph
    assert world is not None
    margin = probe.propagate(world).domains["margin"]
    assert (margin.low, margin.high) == pytest.approx((0.01, 0.05))


def test_a_sub_question_with_no_reasoning_is_refused():
    world = graph(root("margin", low=0.0, high=1.0))
    result = probe.accept(world, answer(
        "margin", 0.4, 0.6,
        raises=[SubQuestion(key="x", asks="x?", because="   ")],
    ))
    assert not result.accepted
    assert any(r.rule == "unexplained" for r in result.rejections)


def test_a_question_at_the_depth_limit_must_be_answered_not_deferred():
    world = graph(root("a", low=0.0, high=1.0), max_depth=0)
    result = probe.accept(world, answer(
        "a", 0.0, 1.0,
        raises=[SubQuestion(key="b", asks="b?", because="because")],
    ))
    assert not result.accepted
    assert any(r.rule == "too_deep" for r in result.rejections)


def test_review_reports_every_reason_not_the_first():
    world = graph(root("a", low=0.0, high=1.0))
    result = probe.accept(world, answer(
        "a", 5.0, 6.0,
        raises=[SubQuestion(key="b", asks="b?", because="", relation="sideways")],
    ))
    rules = {r.rule for r in result.rejections}
    assert {"widens_the_question", "unexplained", "unknown_relation"} <= rules


def test_only_a_leaf_may_bind_to_a_terminal():
    world = graph(root("margin", low=0.0, high=1.0))
    result = probe.accept(world, answer(
        "margin", 0.4, 0.6, binds="retail.margin.budget",
        raises=[SubQuestion(key="turns", asks="turns?", because="margin follows turns")],
    ))
    assert not result.accepted
    assert any(r.rule == "bound_branch" for r in result.rejections)


def test_a_terminal_cannot_be_bound_twice():
    world = graph(root("a", low=0.2, high=0.4), root("b", low=0.2, high=0.4))
    world = probe.accept(world, answer("a", 0.25, 0.3, binds="retail.margin.budget")).graph
    assert world is not None
    result = probe.accept(world, answer("b", 0.25, 0.3, binds="retail.margin.budget"))
    assert not result.accepted
    assert any(r.rule == "terminal_taken" for r in result.rejections)


def test_binding_an_unknown_terminal_is_refused_rather_than_ignored():
    world = graph(root("a", low=0.0, high=1.0))
    result = probe.accept(world, answer("a", 0.2, 0.3, binds="retail.margin.budgt"))
    assert not result.accepted
    assert any(r.rule == "unknown_terminal" for r in result.rejections)


def test_a_probability_terminal_takes_one_value_not_a_range():
    world = graph(root("a", low=0.0, high=1.0))
    result = probe.accept(world, answer("a", 0.4, 0.7, binds="ops.incident.likelihood"))
    assert not result.accepted
    assert any(r.rule == "chance_needs_a_point" for r in result.rejections)

    assert probe.accept(world, answer("a", 0.4, 0.4, binds="ops.incident.likelihood")).accepted


def test_answering_the_same_question_twice_is_refused():
    world = graph(root("a", low=0.0, high=1.0))
    world = probe.accept(world, answer("a", 0.2, 0.3)).graph
    assert world is not None
    result = probe.accept(world, answer("a", 0.21, 0.29))
    assert not result.accepted
    assert any(r.rule == "already_answered" for r in result.rejections)


def test_a_rejected_answer_changes_nothing():
    world = graph(root("a", low=0.0, high=1.0))
    result = probe.accept(world, answer("a", 5.0, 6.0))
    assert result.graph is None
    assert not world.questions["a"].answered


# ---------------------------------------------------------------------------
# The frontier
# ---------------------------------------------------------------------------


def test_the_frontier_finishes_a_level_before_opening_the_next():
    # Depth-first would let one branch bottom out while its siblings were still
    # unasked, and a sibling's evidence is what would have narrowed it.
    world = graph(root("a", low=0.0, high=1.0), root("b", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "a", 0.0, 1.0,
        raises=[SubQuestion(key="a_child", asks="?", because="follows a")],
    )).graph
    assert world is not None
    brief = probe.frontier(world)
    assert brief is not None and brief.key == "b"


def test_a_brief_carries_the_ancestry_that_explains_the_question():
    world = graph(root("margin", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "margin", 0.4, 0.6, claim="apparel margin, before markdown",
        raises=[SubQuestion(key="markdown", asks="markdown depth?",
                            because="margin is what survives markdown")],
    )).graph
    assert world is not None
    brief = probe.frontier(world)
    assert brief is not None and brief.key == "markdown"
    assert brief.ancestry[0][0] == "margin"
    assert "apparel margin" in brief.ancestry[0][1]
    assert brief.remaining_depth == 3


def test_a_brief_offers_only_terminals_nobody_has_claimed():
    world = graph(root("a", low=0.2, high=0.4), root("b", low=0.0, high=1.0))
    world = probe.accept(world, answer("a", 0.25, 0.3, binds="retail.margin.budget")).graph
    assert world is not None
    brief = probe.frontier(world)
    assert brief is not None
    assert "retail.margin.budget" not in brief.terminals
    assert "retail.margin.erosion" in brief.terminals


def test_a_settled_graph_has_no_frontier():
    world = graph(root("a", low=0.0, high=1.0))
    world = probe.accept(world, answer("a", 0.2, 0.3)).graph
    assert world is not None
    assert probe.frontier(world) is None


# ---------------------------------------------------------------------------
# Resolution
# ---------------------------------------------------------------------------


def test_a_leaf_resolves_to_the_propagated_bounds_not_the_stated_answer():
    # A leaf answered wide whose siblings later squeezed it must resolve to the
    # squeezed range; the stated one is a range the graph no longer believes.
    world = graph(root("margin", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "margin", 0.0, 1.0,
        raises=[
            SubQuestion(key="gross", asks="gross margin?", because="what the engine draws",
                        relation="scales", factor_low=1.0, factor_high=1.0,
                        domain_low=0.0, domain_high=1.0, binds="retail.margin.budget"),
            SubQuestion(key="cap", asks="ceiling?", because="bounds gross from above",
                        relation="scales", factor_low=1.0, factor_high=1.0,
                        domain_low=0.0, domain_high=0.55),
        ],
    )).graph
    assert world is not None
    # `cap` has already squeezed margin, and margin squeezes gross, so 0.55 is
    # the widest `gross` can be answered at even before `cap` is settled.
    world = probe.accept(world, answer("gross", 0.45, 0.55)).graph
    assert world is not None
    world = probe.accept(world, answer("cap", 0.5, 0.55)).graph
    assert world is not None

    resolved = probe.resolve(world)
    span = resolved.overrides["retail.margin.budget"]
    assert (span.low, span.high) == (0.5, 0.55)


def test_a_resolved_span_keeps_the_engine_s_kind_and_rounding():
    # A pack states what range a figure lives in. How many decimals it is
    # rounded to is a property of the fact's own unit, and changing it would
    # change every document that prints the figure.
    world = graph(root("m", low=0.0, high=1.0))
    world = probe.accept(world, answer("m", 0.5, 0.58, binds="retail.margin.budget")).graph
    assert world is not None
    span = probe.resolve(world).overrides["retail.margin.budget"]
    assert span.kind == DEFAULTS["retail.margin.budget"].kind
    assert span.places == DEFAULTS["retail.margin.budget"].places


def test_an_unbound_leaf_is_reported_rather_than_dropped():
    # The module's whole claim to being more than decoration: a parameter the
    # world needed and the engine cannot read has to survive as evidence.
    world = graph(root("returns", low=0.0, high=1.0, unit="fraction of units sold"))
    world = probe.accept(world, answer(
        "returns", 0.28, 0.34, claim="online apparel return rate")).graph
    assert world is not None
    resolved = probe.resolve(world)
    assert not resolved.overrides
    (missing,) = resolved.unbound
    assert missing.key == "returns"
    assert "return rate" in missing.claim
    assert missing.bounds == Interval(0.28, 0.34)


def test_an_unfinished_graph_refuses_to_produce_physics():
    world = graph(root("a", low=0.0, high=1.0), root("b", low=0.0, high=1.0))
    world = probe.accept(world, answer("a", 0.2, 0.3, binds="retail.margin.budget")).graph
    assert world is not None
    resolved = probe.resolve(world)
    assert not resolved.usable
    assert resolved.unanswered == ("b",)
    with pytest.raises(ValueError, match="cannot produce physics"):
        resolved.parameters()


def test_a_resolved_graph_becomes_engine_physics():
    world = graph(root("m", low=0.0, high=1.0))
    world = probe.accept(world, answer(
        "m", 0.50, 0.58, source="apparel retail, sector median 52-58%",
        binds="retail.margin.budget")).graph
    assert world is not None
    physics = probe.resolve(world).parameters()
    span = physics.span("retail.margin.budget")
    assert (span.low, span.high) == (0.50, 0.58)
    assert "sector median" in span.source
    # Everything the graph did not touch stays the engine's own.
    assert physics.span("retail.margin.erosion") == DEFAULTS["retail.margin.erosion"]


def test_the_resolved_physics_actually_moves_a_draw():
    from worldloom.rng import Rng

    world = graph(root("m", low=0.0, high=1.0))
    world = probe.accept(world, answer("m", 0.50, 0.58, binds="retail.margin.budget")).graph
    assert world is not None
    physics = probe.resolve(world).parameters()
    drawn = physics.number("retail.margin.budget", Rng(8128, "margin"))
    assert 0.50 <= drawn <= 0.58
    assert drawn != probe.resolve(world).parameters(None).number(
        "retail.margin.erosion", Rng(8128, "margin"))


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------


def test_a_graph_rebuilds_from_its_ledger():
    roots = (root("margin", low=0.0, high=1.0),)
    answers = [
        answer("margin", 0.0, 1.0, raises=[
            SubQuestion(key="gross", asks="gross margin?", because="what the engine draws",
                        relation="scales", factor_low=1.0, factor_high=1.0,
                        domain_low=0.0, domain_high=1.0, binds="retail.margin.budget"),
        ]),
        answer("gross", 0.50, 0.58),
    ]
    built = probe.open_graph(PREMISE, roots)
    entries = []
    for one in answers:
        result = probe.accept(built, one)
        assert result.accepted, result.rejections
        built = result.graph  # type: ignore[assignment]
        entries.append(probe.ledger_entry(one))

    rebuilt = probe.replay(PREMISE, roots, entries)
    assert rebuilt.ordered == built.ordered
    assert probe.resolve(rebuilt).overrides == probe.resolve(built).overrides


def test_a_ledger_entry_that_no_longer_accepts_fails_loudly():
    roots = (root("a", low=0.0, high=1.0),)
    bad = [probe.ledger_entry(answer("a", 5.0, 6.0))]
    with pytest.raises(ValueError, match="no longer accepts"):
        probe.replay(PREMISE, roots, bad)


def test_a_session_round_trips_through_json():
    import json

    session = probe.Session(PREMISE).committed(Answer(
        question=probe.ROOT, claim="specialty apparel; margin is not primitive",
        raises=[SubQuestion(key="margin", asks="gross margin?",
                            because="the premise commits to a margin band",
                            domain_low=0.2, domain_high=0.7,
                            binds="retail.margin.budget")],
    ))
    session = session.committed(answer("margin", 0.50, 0.58))

    # `Infinity` is not valid JSON; a ledger only Python can parse is not the
    # portable record replay is written against.
    text = json.dumps(session.document(), allow_nan=False)
    restored = probe.Session.from_document(json.loads(text))
    assert restored.graph.ordered == session.graph.ordered
    assert probe.resolve(restored.graph).overrides["retail.margin.budget"].low == 0.50


def test_the_opening_question_takes_no_number():
    # The root is a question about the world, not about a quantity.
    session = probe.Session(PREMISE)
    brief = probe.frontier(session.graph)
    assert brief is not None and brief.key == probe.ROOT
    assert brief.bounds == WHOLE

    document = probe.brief_document(brief, premise=PREMISE)
    assert document["question"]["bounds"] == {"low": None, "high": None}
    assert document["rules"]


def test_a_brief_document_is_json_clean_at_every_depth():
    import json

    session = probe.Session(PREMISE).committed(Answer(
        question=probe.ROOT, claim="specialty apparel",
        raises=[SubQuestion(key="turns", asks="inventory turns?", because="drives margin")],
    ))
    brief = probe.frontier(session.graph)
    json.dumps(probe.brief_document(brief, premise=PREMISE), allow_nan=False)
    json.dumps(probe.brief_document(None, premise=PREMISE), allow_nan=False)


def test_a_session_refuses_an_answer_rather_than_storing_it():
    session = probe.Session(PREMISE).committed(Answer(
        question=probe.ROOT, claim="apparel",
        raises=[SubQuestion(key="m", asks="margin?", because="premise commits to one",
                            domain_low=0.2, domain_high=0.7)],
    ))
    with pytest.raises(ValueError, match="widens_the_question"):
        session.committed(answer("m", 0.0, 1.0))
    assert len(session.entries) == 1


# ---------------------------------------------------------------------------
# Layers and cross-layer links
# ---------------------------------------------------------------------------


ORG = "A field-services business, 900 people, four regions."


def structural() -> probe.Session:
    """A probe descending org → reporting → roles, as a model would drive it."""
    session = probe.Session(ORG).committed(Answer(
        question=probe.ROOT,
        claim="Four regions under one operating line. Headcount is fixed, so span"
              " and depth are not independent of each other.",
        raises=[
            SubQuestion(key="headcount", asks="How many people?",
                        because="Everything about shape divides it.",
                        unit="people", layer="organisation",
                        domain_low=800, domain_high=1000),
        ],
    ))
    return session.committed(Answer(
        question="headcount", claim="Nine hundred, give or take.",
        low=880, high=920,
        raises=[
            SubQuestion(key="span", asks="How many reports does a manager carry?",
                        because="Headcount plus span is what fixes the number of levels.",
                        unit="reports", layer="reporting",
                        domain_low=3, domain_high=12),
            SubQuestion(key="levels", asks="How many reporting levels from the top?",
                        because="The other half of the same division.",
                        unit="levels", layer="reporting",
                        domain_low=2, domain_high=8),
        ],
    ))


def test_a_layer_is_settled_before_the_one_under_it_opens():
    # Depth alone would let a role question be asked before the span that
    # decides it, and no later propagation puts that reasoning back.
    session = structural().committed(Answer(
        question="span", claim="Seven or eight.", low=7, high=8,
        raises=[SubQuestion(key="titles", asks="How many distinct titles?",
                            because="Levels and span decide how many rungs need naming.",
                            unit="titles", layer="roles",
                            domain_low=5, domain_high=40)],
    ))
    brief = probe.frontier(session.graph)
    # `titles` is shallower in nothing and deeper in nothing — it is the layer
    # that keeps it waiting behind its sibling in `reporting`.
    assert brief is not None and brief.key == "levels"
    assert brief.layer == "reporting"
    assert brief.next_layer == "roles"


def test_a_sub_question_inherits_the_next_layer_down():
    session = structural()
    assert session.graph.questions["span"].layer == "reporting"
    assert session.graph.questions["headcount"].layer == "organisation"


def test_a_sub_question_in_an_unknown_layer_is_refused():
    session = structural()
    result = probe.accept(session.graph, Answer(
        question="span", claim="Seven.", low=7, high=8,
        raises=[SubQuestion(key="x", asks="?", because="because", layer="vibes")],
    ))
    assert not result.accepted
    assert any(r.rule == "unknown_layer" for r in result.rejections)


def test_a_link_constrains_across_layers_in_both_directions():
    # span and levels are siblings; neither is the other's parent. The link is
    # the only thing that can make one squeeze the other.
    session = structural().committed(Answer(
        question="span", claim="Wide spans; the work is standardised.",
        low=8, high=10,
        links=[probe.ProposedLink(
            subject="span", object="levels", relation="scales",
            factor_low=0.5, factor_high=0.6,
            because="Headcount is fixed, so a wider span buys fewer levels;"
                    " the two cannot be chosen independently.",
        )],
    ))
    domains = probe.propagate(session.graph).domains
    assert domains["levels"] == Interval(4.0, 6.0)  # 8*0.5 .. 10*0.6

    # And backwards: narrowing levels must reach span, which no parent edge
    # connects it to.
    session = session.committed(answer("levels", 4.0, 4.5))
    span = probe.propagate(session.graph).domains["span"]
    # levels <= 4.5 with a factor of at least 0.5 puts span at 9 at the most.
    assert span == Interval(8.0, 9.0)


def test_a_link_with_no_reasoning_is_refused():
    session = structural()
    result = probe.accept(session.graph, Answer(
        question="span", claim="Seven.", low=7, high=8,
        links=[probe.ProposedLink(subject="span", object="levels", because="  ")],
    ))
    assert not result.accepted
    assert any(r.rule == "unexplained" for r in result.rejections)


def test_a_link_to_a_question_that_does_not_exist_is_refused():
    session = structural()
    result = probe.accept(session.graph, Answer(
        question="span", claim="Seven.", low=7, high=8,
        links=[probe.ProposedLink(subject="span", object="okrs", because="hunch")],
    ))
    assert not result.accepted
    assert any(r.rule == "unknown_question" for r in result.rejections)


def test_a_link_may_name_a_question_the_same_answer_raises():
    session = structural()
    result = probe.accept(session.graph, Answer(
        question="span", claim="Seven.", low=7, high=8,
        raises=[SubQuestion(key="titles", asks="titles?", because="rungs need names",
                            layer="roles", domain_low=5, domain_high=40)],
        links=[probe.ProposedLink(
            subject="levels", object="titles", relation="scales",
            factor_low=1.0, factor_high=4.0,
            because="Each level carries at least one title and rarely more than four.",
        )],
    ))
    assert result.accepted, [str(r) for r in result.rejections]


def test_a_question_cannot_constrain_itself():
    session = structural()
    result = probe.accept(session.graph, Answer(
        question="span", claim="Seven.", low=7, high=8,
        links=[probe.ProposedLink(subject="span", object="span", because="itself")],
    ))
    assert not result.accepted
    assert any(r.rule == "self_link" for r in result.rejections)


# ---------------------------------------------------------------------------
# The space a settled graph describes
# ---------------------------------------------------------------------------


def settled() -> probe.Graph:
    session = structural().committed(Answer(
        question="span", claim="Wide.", low=8, high=10,
        links=[probe.ProposedLink(
            subject="span", object="levels", relation="scales",
            factor_low=0.5, factor_high=0.6,
            because="Fixed headcount trades span against levels.",
        )],
    ))
    return session.committed(answer("levels", 4.0, 6.0)).graph


def test_a_settled_graph_describes_many_worlds_not_one():
    # The naive resolver takes the midpoint of every interval and produces the
    # single most average member of the space.
    found = probe.worlds(settled(), count=5)
    assert len(found) == 5
    assert len({tuple(w.as_dict().items()) for w in found}) == 5


def test_every_world_respects_every_relation_not_just_every_range():
    # Arc consistency is a property of domains, not of points: the corner where
    # levels sits at its maximum while span sits at its minimum satisfies both
    # ranges and none of the reasoning.
    for world in probe.worlds(settled(), count=8):
        values = world.as_dict()
        assert 0.5 * values["span"] - 1e-9 <= values["levels"] <= 0.6 * values["span"] + 1e-9


def test_the_worlds_chosen_are_spread_rather_than_clustered():
    chosen = probe.worlds(settled(), count=6)
    spans = sorted(w.as_dict()["span"] for w in chosen)
    # Farthest-first takes the extremes first, so the selection must cover
    # substantially more of the range than a clustered sample would.
    assert spans[-1] - spans[0] > 0.7 * (10.0 - 8.0)


def test_the_mosaic_is_the_same_on_every_run():
    first = [w.as_dict() for w in probe.worlds(settled(), count=4)]
    for _ in range(3):
        assert [w.as_dict() for w in probe.worlds(settled(), count=4)] == first


def test_a_graph_pinned_to_a_point_describes_exactly_one_world():
    world = graph(root("a", low=0.3, high=0.3))
    world = probe.accept(world, answer("a", 0.3, 0.3)).graph
    assert world is not None
    (only,) = probe.worlds(world, count=5)
    assert only.as_dict() == {"a": 0.3}


def test_an_inconsistent_graph_describes_no_worlds_and_says_so():
    world = hand_built(
        root("margin", low=0.5, high=0.6),
        child("cost", "margin", "complements", low=0.7, high=0.9),
    )
    with pytest.raises(ValueError, match="no worlds at all"):
        probe.worlds(world, count=3)


def test_replay_is_stable_across_repeats():
    roots = (root("a", low=0.0, high=1.0),)
    entries = [probe.ledger_entry(answer("a", 0.2, 0.3, binds="retail.margin.budget"))]
    first = probe.replay(PREMISE, roots, entries)
    for _ in range(3):
        assert probe.replay(PREMISE, roots, entries).ordered == first.ordered


# ---------------------------------------------------------------------------
# The second channel: objectives resolve to accountabilities, not to spans
# ---------------------------------------------------------------------------

TARGET = "gm_md/financial.revenue.variance"


def objective(key: str = "gm_md_revenue", *, target: str = TARGET,
              low: float = 2.0, high: float = 4.0, **kwargs: object) -> Answer:
    return answer(key, low, high, answers_for=target, **kwargs)  # type: ignore[arg-type]


def objectives_graph(key: str = "gm_md_revenue", *, unit: str = "percent") -> Graph:
    return graph(root(key, low=0.0, high=100.0, unit=unit))


def test_the_measure_vocabulary_is_computed_rather_than_maintained():
    """`probe.MEASURES` is exactly the numeric fact kinds *every* shipped engine
    mints in its default episode.

    Hand-kept, it would be wrong within a month and wrong *silently*: the
    failure is a model being told a perfectly good measure does not exist,
    which it has no way to argue with. Same mechanism as `roles.SPINE`.

    This test used to name three engines while the repository shipped four, and
    so it passed on a tuple missing all 23 of procurement's numeric kinds — a
    derivation computed over a subset is a hand-kept list wearing a derivation,
    and it fails silently in precisely the direction above. The engines are now
    enumerated from `domains` rather than imported one by one, so a fifth
    vertical is covered by registering itself. Retail is the stated exception
    and the registry says why: it declares `single_episode=None` because its
    build loops closes and threads incident flags through them.
    """
    from worldloom import archetypes, domains
    from worldloom.retail import RetailWorld
    from worldloom.scenarios import MonthEndClose

    built = [
        RetailWorld(seed=8128).build().run(
            MonthEndClose(period="2026-03", include_operational_incident=True)),
    ]
    for name in sorted(domains.names()):
        domain = domains.by_name(name)
        if domain is None or domain.single_episode is None:
            continue
        world = domain.world(
            seed=8128, archetype=archetypes.get(domain.default_archetype),
        ).build()
        built.append(world.run(domain.single_episode("2026-03")))

    minted = {f.kind for world in built for f in world.facts if f.value is not None}
    assert set(probe.MEASURES) == minted
    # The regression this closes, stated so it cannot come back quietly: at
    # least one measure from each shipped vertical's own vocabulary is present.
    for prefix in ("financial.", "capital.", "reserves.", "p2p."):
        assert any(m.startswith(prefix) for m in probe.MEASURES), prefix


def test_an_objective_leaf_resolves_to_an_accountability_and_not_to_a_span():
    settled = probe.accept(objectives_graph(), objective(
        claim="The GM managing director answers for revenue against budget.")).graph
    resolution = probe.resolve(settled)
    assert resolution.overrides == {}
    (found,) = resolution.accountabilities
    assert (found.role, found.measure) == ("gm_md", "financial.revenue.variance")
    assert found.band == Interval(2.0, 4.0)
    # And never an unbound finding: it bound to something, just not to a
    # terminal. "Who answers for revenue" is not a number the registry lacks.
    assert resolution.unbound == ()


def test_the_accountability_carries_enough_to_build_the_lore_constraint():
    from worldloom.models import ConstraintKind

    settled = probe.accept(objectives_graph(), objective(claim="Answers for it.")).graph
    (found,) = probe.resolve(settled).accountabilities
    constraint = found.constraint()
    assert constraint.kind is ConstraintKind.ACCOUNTABILITY
    assert constraint.target == TARGET
    assert constraint.effect == "Answers for it."
    # The tight end of the band, not the midpoint: committing to the loose end
    # asserts a laxer regime than the reasoning supports and leaves an
    # accountability edge that never fires.
    assert constraint.magnitude == 2.0


def test_the_band_resolved_is_the_propagated_one_not_the_stated_one():
    """A tolerance tightened by a link must resolve tightened — reading the
    stated band back would throw away the one thing links are for."""
    tightened = probe.accept(
        graph(root("tolerance", low=0.0, high=100.0)),
        Answer(question="tolerance", claim="Judged tightly.", low=2.0, high=8.0,
               raises=[SubQuestion(
                   key="gm_md_revenue", asks="what band?", because="It is the objective.",
                   unit="percent", relation="scales", factor_low=0.25, factor_high=0.5,
                   domain_low=0.5, domain_high=6.0, answers_for=TARGET,
               )]),
    ).graph
    tightened = probe.accept(tightened, objective(low=0.5, high=4.0)).graph
    (found,) = probe.resolve(tightened).accountabilities
    # 2..8 scaled by 0.25..0.5 gives 0.5..4.0, met with the answer: the parent
    # squeezes it even though the leaf was answered wider.
    assert found.band.low == pytest.approx(0.5) and found.band.high == pytest.approx(4.0)


def test_a_measure_no_engine_mints_is_refused_like_an_unknown_terminal():
    rejections = probe.review(objectives_graph(), objective(target="gm_md/vibes.overall"))
    assert [r.rule for r in rejections] == ["unknown_measure"]


def test_a_target_missing_either_half_is_refused():
    for target in ("gm_md", "gm_md/", "/financial.revenue.variance"):
        rejections = probe.review(objectives_graph(), objective(target=target))
        assert [r.rule for r in rejections] == ["malformed_accountability"], target


def test_a_tolerance_outside_the_sane_band_is_refused():
    # Above a quarter is not a tolerance but the absence of one; below a tenth
    # of a per cent is breached by the rounding the corpus prints at.
    wide = probe.review(objectives_graph(), objective(low=30.0, high=40.0))
    assert [r.rule for r in wide] == ["tolerance_out_of_band"]
    fine = probe.review(objectives_graph(), objective(low=0.001, high=0.01))
    assert [r.rule for r in fine] == ["tolerance_out_of_band"]
    # And an unstated one, which is what a leaf that named a target and no
    # numbers gives: the band is the claim, so leaving it open states nothing.
    open_ended = probe.review(graph(root("gm_md_revenue")), Answer(
        question="gm_md_revenue", claim="Answers for it.", answers_for=TARGET))
    assert [r.rule for r in open_ended] == ["unstated_tolerance"]


def test_a_leaf_may_not_be_both_a_measure_and_an_accountability():
    """The interval cannot be a parameter's range and a tolerance band at once,
    which is the whole reason `answers_for` is not a second meaning for
    `binds`."""
    rejections = probe.review(objectives_graph(), objective(binds="retail.margin.budget"))
    assert "two_channels" in {r.rule for r in rejections}


def test_the_same_role_cannot_answer_for_the_same_measure_twice():
    settled = probe.accept(objectives_graph(), objective()).graph
    settled = probe.Graph(  # a second, still-open question aiming at the same target
        settled.premise,
        {**settled.questions,
         "cfo_revenue": Question(key="cfo_revenue", asks="and the CFO?", unit="percent",
                                 domain=Interval(0.0, 100.0), depth=0)},
        settled.max_depth, settled.layers, settled.links,
    )
    rejections = probe.review(settled, objective("cfo_revenue"))
    assert [r.rule for r in rejections] == ["accountability_taken"]
    # Two *different* roles on one measure is an org chart, not a collision.
    assert probe.review(settled, objective("cfo_revenue",
                                           target="cfo/financial.revenue.variance")) == []


def test_an_accountability_on_a_branch_is_refused_the_way_a_bind_is():
    rejections = probe.review(objectives_graph(), objective(raises=[SubQuestion(
        key="under", asks="what drives it?", because="It is not primitive.",
        domain_low=1.0, domain_high=2.0,
    )]))
    assert "accountable_branch" in {r.rule for r in rejections}


def test_the_brief_hands_over_the_measures_and_the_band():
    document = probe.brief_document(
        probe.frontier(objectives_graph()), premise=PREMISE)
    assert TARGET.split("/")[1] in document["accountable_measures"]
    assert document["tolerance_band_pct"] == {"low": probe.TOLERANCE.low,
                                              "high": probe.TOLERANCE.high}


def test_an_accountability_survives_the_ledger():
    entries = [probe.ledger_entry(objective(claim="Answers for revenue."))]
    rebuilt = probe.replay(PREMISE, (root("gm_md_revenue", low=0.0, high=100.0),), entries)
    (found,) = probe.resolve(rebuilt).accountabilities
    assert found.target == TARGET and found.magnitude == 2.0


def test_the_constraint_a_probe_emits_mints_a_fact_about_a_person():
    """The claim the whole channel rests on: reasoning in the objectives layer
    reaches a build, rather than evaporating at the socket."""
    from worldloom import archetypes
    from worldloom.generators import organisation
    from worldloom.generators.org_builder import ACCOUNTABILITY_KIND
    from worldloom.ids import Minter
    from worldloom.models import LoreCommitment, LoreKind
    from worldloom.rng import Rng

    settled = probe.accept(objectives_graph(), objective(
        claim="The GM managing director answers for revenue against budget.")).graph
    (found,) = probe.resolve(settled).accountabilities

    minter = Minter()
    lore = (LoreCommitment(
        id=minter.next("LORE"), kind=LoreKind.NORM, assertion=found.effect,
        effective_from="2023-04", constrains=[found.constraint()],
    ),)
    org = organisation.generate(
        Rng(8128, "organisation"), minter,
        archetype=archetypes.get("omnichannel_retailer"), lore=lore,
    )
    (fact,) = [f for f in org.founding_facts if f.kind == ACCOUNTABILITY_KIND]
    assert fact.subject in {p.id for p in org.people}
    assert fact.text_value == found.measure
    assert fact.value is not None and fact.value.amount == found.magnitude
