"""The estate families, and the two ways they could be quietly worthless.

A graph question is easy to *generate* and hard to make count. Two failure
modes matter more than whether the wording is nice, and both are silent:

**A case with no expected facts passes for free.** ``cases.answerable`` lets it
through — an empty set is trivially reachable — and ``score._covers`` then
returns ``True`` for any retrieval at all. A family of those would raise every
scorecard while measuring nothing, which is worse than not asking.

**A case whose facts no artifact carries disappears.** Same gate, opposite
direction: the generated estate carries no facts of its own, so a question
grounded on a generated service is dropped between minting and the corpus, and
the only sign is a case count that quietly does not grow.

So the tests below check what the families *ground* on, not how they read, and
they check the no-estate world loses nothing — the condition the whole gate
exists to hold.
"""

from __future__ import annotations

import pytest

from worldloom import MonthEndClose, graphs
from worldloom.retail import RetailWorld

SEED = 8128
PERIOD = "2026-03"


def _built(estate: str | None):
    return RetailWorld(seed=SEED, estate=estate).build().run(
        MonthEndClose(period=PERIOD, include_operational_incident=True)
    )


@pytest.fixture(scope="module")
def plain():
    return _built(None)


@pytest.fixture(scope="module")
def grown():
    return _built("medium")


def _estate_cases(world):
    """The cases only an estate can produce, found by what they cite rather
    than by their id: ids move whenever a family above them mints one more
    case, and a test pinned to `EVAL-0043` would then be testing arithmetic."""
    return [
        case for case in world.evaluations
        if "dependency graph" in case.reasoning
        or "single-point-of-failure" in case.reasoning
        or "Depth, counted in edges" in case.reasoning
    ]


def test_a_world_with_no_estate_asks_nothing_about_one(plain) -> None:
    """The gate, from the side that matters most for byte-identity: the
    episode's own nine-node prop list must produce exactly the case set it
    always has, with no estate question and no estate-scaled rewording."""
    assert _estate_cases(plain) == []
    questions = [case.question for case in plain.evaluations]
    assert "Why was the 2026-03 close delayed?" in questions
    assert "Who owns the product hierarchy mapping table?" in questions
    assert not [q for q in questions if "services and systems" in q]


def test_an_estate_is_asked_what_only_the_graph_knows(grown) -> None:
    cases = _estate_cases(grown)
    assert len(cases) == 3, [case.question for case in cases]

    graph = graphs.dependency_graph(grown)
    # The reading the answers are supposed to agree with, taken independently
    # of the taxonomy: `graphs` is the authority on the estate, and a family
    # that computed its own version of blast radius would be the second
    # implementation this project's determinism rules exist to prevent.
    service = next(s.id for s in grown.services if s.name == "product-hierarchy-sync")
    reach = graphs.blast_radius(graph, service)
    assert len(reach) >= 3, "medium estate should reach past the episode's prop list"

    answers = " ".join(case.expected_answer or "" for case in cases)
    assert str(len(reach)) in answers
    assert str(graph.number_of_nodes()) in " ".join(case.question for case in cases)


def test_every_estate_case_is_grounded_in_a_fact_some_artifact_carries(grown) -> None:
    """Neither free-pass nor dropped — see this module's docstring."""
    from worldloom.generators.cases import reachable_fact_ids

    reachable = reachable_fact_ids(grown.artifact_intents)
    for case in _estate_cases(grown):
        assert case.expected_fact_ids, f"{case.id} would pass for free"
        assert set(case.expected_fact_ids) <= reachable, case.id


def test_the_estate_reworded_the_incident_questions_it_enlarged(grown, plain) -> None:
    """The phrasing lever, and its limit. The questions about *which* service
    or system are asked of a hundred candidates instead of four, so they say
    so; the financial families are untouched, because an estate is no evidence
    about how revenue should be asked after."""
    grown_questions = {case.question for case in grown.evaluations}
    plain_questions = {case.question for case in plain.evaluations}

    assert "Why was the 2026-03 close delayed?" not in grown_questions
    assert [q for q in grown_questions if "services and systems" in q]

    financial = {q for q in plain_questions if "revenue" in q or "gross profit" in q}
    assert financial and financial <= grown_questions
