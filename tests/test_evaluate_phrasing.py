"""Per-world question phrasing: the refusals, the deal, and what it may not move.

Three properties are worth a test here and the middle one is the reason this
file exists at all.

**The pool is clean.** `phrasing.findings` is run against the shipped
alternatives, so a paraphrase that drops a placeholder or drifts onto a
sibling's subject fails here rather than in a corpus.

**The refusals have teeth.** A checker asserted and never exercised is
decoration. Every rule `findings` states is given a pool that breaks it, and
the finding has to name the key — because the whole safety argument for varying
a question is that changing *what is asked* is refused mechanically.

**Nothing but the question moves.** A case's expected facts, answer, type,
cut-off and difficulty are what grading reads. This builds the same world twice
with phrasing on and off and diffs every one of those fields, which is the
structural claim stated as a measurement.
"""

from __future__ import annotations

import pytest

from worldloom import archetypes, domains, vocabulary
from worldloom.evaluate import phrasing
from worldloom.generators.evaluation import EVAL_TEXT
from worldloom.scenarios import MonthEndClose

def _world(vocab: str = ""):
    domain = domains.by_name("retail")
    shape = archetypes.get(domain.default_archetype)
    if vocab:
        shape = vocabulary.spoken(shape, vocab)
    built = domain.world(seed=8128, archetype=shape).build()
    return built.run(MonthEndClose(period="2026-03", include_operational_incident=True))


# ---------------------------------------------------------------------------
# The pool
# ---------------------------------------------------------------------------


def test_the_shipped_alternatives_are_clean() -> None:
    assert phrasing.findings(EVAL_TEXT, phrasing.ALTERNATIVES) == []


def test_every_alternative_names_a_question_key_that_exists() -> None:
    """Answer keys are deliberately not variable, and a key that names nothing
    is dead data that would silently never be used."""
    assert set(phrasing.ALTERNATIVES) <= set(EVAL_TEXT)
    assert all(key.startswith("q.") for key in phrasing.ALTERNATIVES)


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_dropped_placeholder_is_refused_where_a_pack_override_would_pass() -> None:
    """`episode_text.check_overrides` allows a *subset* of a template's slots,
    which is right for a pack re-voicing a sentence and wrong for a variant of
    one: "What was total revenue?" is a different, ambiguous question the
    moment the corpus has two periods."""
    from worldloom.generators.episode_text import check_overrides

    dropped = {"q.direct.group_revenue": ("What was total revenue?",)}
    assert check_overrides(EVAL_TEXT, {k: v[0] for k, v in dropped.items()}) == []

    found = phrasing.findings(EVAL_TEXT, dropped)
    assert len(found) == 1
    assert "q.direct.group_revenue" in found[0] and "period" in found[0]


def test_an_invented_placeholder_is_refused() -> None:
    found = phrasing.findings(
        EVAL_TEXT, {"q.direct.group_revenue": ("What revenue in {period} for {quarter}?",)}
    )
    assert found and "quarter" in found[0]


def test_a_variant_that_wanders_onto_a_siblings_subject_is_refused() -> None:
    """The check that actually protects correctness. `group_revenue`,
    `group_gross_profit` and `group_gross_margin` all take `{period}` and
    nothing else, so the words are the only thing between them."""
    found = phrasing.findings(
        EVAL_TEXT,
        {"q.direct.group_revenue": ("What gross profit did the group make in {period}?",)},
    )
    # Both rules fire, and they are two different statements about the same
    # sentence: it kept nothing of its own subject, *and* it took a word that
    # belongs to its neighbour's. Either alone is a refusal.
    assert len(found) == 2
    assert all("q.direct.group_revenue" in finding for finding in found)
    assert "q.direct.group_gross_profit" in found[1] and "profit" in found[1]


def test_a_variant_that_keeps_no_word_of_its_own_subject_is_refused() -> None:
    """Generic enough to be any of its siblings is the same defect stated the
    other way round, and it is the one a careless paraphrase actually commits."""
    found = phrasing.findings(
        EVAL_TEXT, {"q.direct.group_revenue": ("What did the group report for {period}?",)}
    )
    assert len(found) == 1
    assert "q.direct.group_revenue" in found[0]


def test_nothing_is_demanded_of_a_variant_whose_default_distinguishes_nothing() -> None:
    """`signed_earlier` and `signed_current` are byte-identical defaults asked
    of two periods. Demanding that a *variant* tell them apart would be asking
    a paraphrase to fix the taxonomy, so the discriminator rule is computed to
    be empty there rather than special-cased."""
    assert phrasing.findings(
        EVAL_TEXT,
        {"q.history.signed_earlier": ("Who put their name to the {doc_type} for {period}?",)},
    ) == []


def test_a_key_with_no_sibling_may_be_reworded_freely() -> None:
    """Nothing takes `{person}` but `succession`, so there is no confusion to
    prevent and the rule must not fire — a check that refuses safe rewordings
    gets switched off, which is worse than not having it."""
    assert phrasing.findings(
        EVAL_TEXT, {"q.history.succession": ("Who came after {person}?",)}
    ) == []


def test_a_repeated_or_unquestioning_variant_is_refused() -> None:
    repeated = phrasing.findings(
        EVAL_TEXT, {"q.abstain.nps": (EVAL_TEXT["q.abstain.nps"],)}
    )
    assert repeated and "repeats" in repeated[0]

    flat = phrasing.findings(
        EVAL_TEXT, {"q.abstain.nps": ("State the group's net promoter score.",)}
    )
    assert flat and "question" in flat[0]


def test_an_answer_key_is_refused_because_grading_reads_it() -> None:
    found = phrasing.findings(EVAL_TEXT, {"a.direct.group_revenue": ("{value}!",)})
    assert found and "a.direct.group_revenue" in found[0]


def test_registers_refuse_a_broken_pool_rather_than_dealing_it() -> None:
    with pytest.raises(ValueError, match="q.direct.group_revenue"):
        phrasing.registers(
            EVAL_TEXT,
            {"q.direct.group_revenue": ("What gross margin did the group run at in {period}?",)},
            2,
        )


# ---------------------------------------------------------------------------
# The deal
# ---------------------------------------------------------------------------


def test_every_retail_vocabulary_is_dealt_one_register() -> None:
    dealt = phrasing.deal("retail")
    assert set(dealt) == set(vocabulary.for_engine("retail"))
    assert all(set(register) == set(phrasing.ALTERNATIVES) for register in dealt.values())


def test_one_register_is_the_taxonomys_own_wording() -> None:
    """The control. A before/after in which every world moved has nothing in it
    to read the movement against, so `farthest_first`'s first pick is the
    all-defaults candidate on purpose."""
    dealt = phrasing.deal("retail")
    assert any(
        all(register[key] == EVAL_TEXT[key] for key in register)
        for register in dealt.values()
    )


def test_no_two_registers_are_the_same_benchmark() -> None:
    dealt = phrasing.deal("retail")
    rendered = {tuple(sorted(register.items())) for register in dealt.values()}
    assert len(rendered) == len(dealt)


def test_the_questions_that_were_identical_everywhere_now_differ() -> None:
    """The three the brief quotes, and the defect they stand for: a question
    quoting no noun the world owns was the same sentence in all five worlds."""
    dealt = phrasing.deal("retail")
    for key in (
        "q.direct.group_revenue",
        "q.abstain.staff_costs",
        "q.abstain.close_calendar_1995",
    ):
        assert len({register[key] for register in dealt.values()}) > 1


def test_dispersion_beats_taking_the_pool_in_order() -> None:
    """The claim `mosaic` makes about company shapes, one level down and
    measured rather than assumed: independent draws clump."""
    keys = sorted(phrasing.ALTERNATIVES)
    variants = phrasing._variants(EVAL_TEXT, phrasing.ALTERNATIVES)
    candidates = phrasing._candidates(variants, phrasing._POOL)
    head = [
        {key: variants[i][candidate[i]] for i, key in enumerate(keys)}
        for candidate in candidates[:5]
    ]
    dealt = list(phrasing.deal("retail").values())
    assert phrasing.separation(dealt)["minimum"] > phrasing.separation(head)["minimum"]


def test_the_deal_is_a_pure_function_of_the_registry() -> None:
    """No seed, no clock, no world. A register is a property of a vocabulary,
    which is what lets a mosaic's third world rebuild alone from its recipe."""
    phrasing.deal.cache_clear()
    first = phrasing.deal("retail")
    phrasing.deal.cache_clear()
    assert phrasing.deal("retail") == first


def test_an_engine_with_no_pool_is_silent_rather_than_wrong() -> None:
    """Banking and insurance keep their own `EVAL_TEXT` in their own modules.
    Inventing paraphrases for questions this module cannot see would be the
    costume problem again, so the answer is nothing."""
    assert phrasing.deal("banking") == {}
    assert phrasing.deal("insurance") == {}


# ---------------------------------------------------------------------------
# What it may not move
# ---------------------------------------------------------------------------


def test_a_world_that_speaks_no_dealt_vocabulary_gets_no_phrasing() -> None:
    """Byte identity, as a property of the data rather than of a flag somebody
    has to remember to leave off."""
    assert phrasing.overrides(_world()) is None


def test_a_world_that_speaks_one_gets_its_register() -> None:
    world = _world("wholesale_club")
    assert phrasing.overrides(world) == phrasing.deal("retail")["wholesale_club"]


def test_phrasing_changes_the_question_and_nothing_else(monkeypatch) -> None:
    """The structural claim, measured. Same world, same seed, same vocabulary —
    only the phrasing seam switched off — so every field grading reads has to
    come back byte-identical while the questions do not."""
    varied = _world("wholesale_club")
    monkeypatch.setattr(phrasing, "overrides", lambda world, **kwargs: None)
    plain = _world("wholesale_club")

    def graded(world):
        return [
            (
                case.id,
                case.evaluation_type,
                case.expected_answer,
                tuple(case.expected_fact_ids),
                tuple(case.required_artifact_ids),
                tuple(case.distractor_artifact_ids),
                case.temporal_cutoff,
                case.difficulty,
                case.expects_abstention,
            )
            for case in world.evaluations
        ]

    assert graded(varied) == graded(plain)
    questions_varied = [case.question for case in varied.evaluations]
    questions_plain = [case.question for case in plain.evaluations]
    assert questions_varied != questions_plain
    # Not merely "some question moved": most of them did, which is what
    # separates a per-world benchmark from a per-world typo.
    moved = sum(1 for a, b in zip(questions_varied, questions_plain) if a != b)
    assert moved > len(questions_plain) // 2


def test_a_pack_that_re_voiced_a_question_still_wins(monkeypatch) -> None:
    """A deal is a default. An author who wrote the sentence said what they
    meant, and the two overrides land in the same map — so the order matters
    and is asserted rather than assumed."""
    domain = domains.by_name("retail")
    shape = vocabulary.spoken(archetypes.get(domain.default_archetype), "wholesale_club")
    built = domain.world(seed=8128, archetype=shape).build()
    authored = "Which merchandise category ran the thinnest gross margin in {period}?"
    built._recipe["pack"] = {
        "evaluation_text": {"q.numerical.thinnest_margin_category": authored}
    }
    world = built.run(MonthEndClose(period="2026-03", include_operational_incident=True))
    questions = {case.question for case in world.evaluations}
    assert authored.replace("{period}", "2026-03") in questions
