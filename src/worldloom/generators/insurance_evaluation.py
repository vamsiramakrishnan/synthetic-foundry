"""The insurance evaluation families.

Seven families over one phase-1 valuation, and the property that matters most
is the one the design record states directly: ``AUTHORITY_RANK`` does not
merely fail to resolve the central-estimate-versus-booked-reserve contest, as
banking's filed/restated tie does — it actively **inverts** the answer for
half the family, because ``SYSTEM_OF_RECORD`` outranks ``CONFIRMED``
(``models.AUTHORITY_RANK``) and the booked reserve is deliberately the wrong
source for "what did the actuary estimate". The contrast case
(``q.authority.booked_reserve``) is generated beside it for the same reason
banking's contested-figure pair is generated together: a retriever that
always prefers rank passes one and fails the other, and a retriever that
always prefers the actuarial voice does the reverse.

Every non-abstention case passes the same reachable-facts gate the retail and
banking taxonomies apply: a question whose answer no planned artifact carries
is dropped before it is ever minted, in exact agreement with
``validate.py``'s ``unreachable_answer`` check.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..ids import Minter
from ..models import ArtifactIntent, EvaluationCase, EvaluationType
from . import episode_text
from .cases import CaseBuilder, answerable, reachable_fact_ids
from .cases import fmt as _fmt
from .reserving import ReservingEpisode

#: This taxonomy's surface text, keyed exactly as `evaluation.EVAL_TEXT` and
#: `banking_evaluation.EVAL_TEXT` are — one pack-overridable entry per
#: question and per authored answer. See those modules' table comments for
#: why reasoning strings and bare fact values are deliberately absent.
EVAL_TEXT: dict[str, str] = {
    "q.temporal.prior_ultimate":
        "What was {company}'s actuarial ultimate for the accident quarter"
        " {accident_period} cohort of the long-tail liability book as at the"
        " {prior_period} valuation?",
    "a.temporal.prior_ultimate": "{value}",
    "q.authority.central_estimate":
        "What is {company}'s actuarial central estimate of ultimate claims for the"
        " long-tail liability book, for the quarter ended {period}?",
    "a.authority.central_estimate":
        "{central} — the actuarial central estimate. The {booked} carried on the balance"
        " sheet is a finance decision, not the actuary's estimate.",
    "q.authority.booked_reserve":
        "What reserve does {company} hold on its balance sheet for the long-tail"
        " liability book, for the quarter ended {period}?",
    "a.authority.booked_reserve": "{value} — the booked reserve, the current figure of record.",
    "q.causal.why_strengthened":
        "Why did the long-tail liability book's actuarial central estimate strengthen this"
        " quarter?",
    "a.causal.why_strengthened":
        "Adverse actual-versus-expected emergence across the book's accident cohorts,"
        " attributed as {pattern} of pattern change from the 2024 claims-transformation"
        " programme and {deterioration} of genuine deterioration.",
    "q.numerical.booked_identity":
        "Does the booked reserve equal the actuarial central estimate plus the risk margin"
        " remaining, for the long-tail liability book this quarter?",
    "a.numerical.booked_identity":
        "Yes — {booked} booked equals {central} central estimate plus {margin} margin"
        " remaining.",
    "q.numerical.attribution_sums":
        "Do the pattern-change and deterioration attribution amounts sum to this quarter's"
        " total central-estimate movement?",
    "a.numerical.attribution_sums":
        "Yes — {pattern} pattern change plus {deterioration} deterioration equals the"
        " {movement} total movement.",
    "q.cross.movement_matches_emergence":
        "For accident quarter {accident_period}, does the movement in the actuarial ultimate"
        " this quarter match the actual-versus-expected deviation the emergence note"
        " recorded for that cohort?",
    "a.cross.movement_matches_emergence":
        "Yes — the ultimate moved by {value}, exactly the emergence note's recorded"
        " deviation for that cohort.",
    "q.abstain.true_ultimate":
        "What is the true ultimate cost of the accident quarter {accident_period} cohort of"
        " the long-tail liability book?",
    "q.citation.margin_memo_pair":
        "Which two facts must the margin decision memo cite to justify a booked reserve"
        " below the actuarial central estimate?",
    "a.citation.margin_memo_pair":
        "The actuarial central estimate and the booked reserve — the memo must state both"
        " figures, each quoting the other document's own number, or the shortfall it"
        " records is an unexplained override.",
}


def evaluation_cases(
    minter: Minter,
    *,
    episode: ReservingEpisode,
    intents: tuple[ArtifactIntent, ...],
    period: str,
    company: str = "",
    text: Mapping[str, str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one phase-1 reserving episode.

    ``text`` overrides entries of ``EVAL_TEXT`` — a pack re-voicing the
    benchmark itself, the seam ``generators/episode_text`` provides.
    """
    t = episode_text.merged(EVAL_TEXT, text, field="evaluation_text")
    # Named before any `.format` call, exactly as `banking_evaluation` does
    # and for the measurement recorded there: this taxonomy produced 9 of 9
    # identical question strings across four seeds, and "the long-tail
    # liability book" is the same book in every insurer this engine builds.
    # Falls back to the generic wording this taxonomy always used, so a
    # caller that does not name the company gets a sentence rather than
    # "What was 's CET1 ratio" — and so the templates stay readable in
    # isolation, which is how every test in `tests/test_eval_text.py`
    # reads them.
    t = {key: value.replace("{company}", company or "the insurer")
         for key, value in t.items()}
    k = episode.keys
    by_id = {f.id: f for f in episode.facts}

    workbook = next((i.id for i in intents if i.artifact_type == "reserve_triangle_workbook"), None)
    note = next((i.id for i in intents if i.artifact_type == "claims_emergence_note"), None)
    report = next((i.id for i in intents if i.artifact_type == "actuarial_valuation_report"), None)
    memo = next((i.id for i in intents if i.artifact_type == "margin_decision_memo"), None)

    cohorts = sorted({key.removeprefix("fact_ultimate_current_")
                       for key in k if key.startswith("fact_ultimate_current_")})
    first_cohort = cohorts[0]

    # This vertical's families are hard by design, so the builder's default
    # flips to "hard" rather than repeating it at every call, the same choice
    # `banking_evaluation` makes.
    builder = CaseBuilder(minter, default_difficulty="hard")
    case = builder.case

    central_current = by_id[k["fact_central_current"]]
    booked_current = by_id[k["fact_booked_current"]]
    margin_current = by_id[k["fact_margin_current"]]
    pattern = by_id[k["fact_attribution_pattern"]]
    deterioration = by_id[k["fact_attribution_deterioration"]]
    movement = pattern.value.amount + deterioration.value.amount

    # -- temporal_state: a mid-chain link with no wrongness marker -----------
    # The correct answer to "as at the prior valuation" is the superseded
    # estimate, which reads exactly as confident as the one that replaced
    # it — unlike retail's ruled-out hypothesis or banking's restated
    # filing, nothing here is lexically marked as having been wrong.
    prior_ultimate = by_id[k[f"fact_ultimate_prior_{first_cohort}"]]
    case(
        t["q.temporal.prior_ultimate"].format(
            accident_period=first_cohort, prior_period=episode.prior_period,
        ),
        EvaluationType.TEMPORAL_STATE,
        t["a.temporal.prior_ultimate"].format(value=_fmt(prior_ultimate)),
        [k[f"fact_ultimate_prior_{first_cohort}"]], cutoff=episode.prior_valuation_at,
        reasoning="The workbook carries both valuations for this cohort; the strengthened "
                  "current figure supersedes this one with no lexical marker distinguishing "
                  "a corrected belief from a current one.",
        sources=[workbook], distractors=[report],
    )

    # -- authority_resolution: rank inverts correctness for this half --------
    case(
        t["q.authority.central_estimate"].format(period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.central_estimate"].format(
            central=_fmt(central_current), booked=_fmt(booked_current),
        ),
        [k["fact_central_current"]],
        reasoning="SYSTEM_OF_RECORD outranks CONFIRMED in AUTHORITY_RANK, so rank alone "
                  "picks the booked reserve — the wrong source for what the actuary "
                  "estimated. Only reading which document's authority answers which "
                  "question resolves it.",
        sources=[report], distractors=[memo],
    )
    # -- the contrast case, generated beside it: here rank resolves correctly.
    case(
        t["q.authority.booked_reserve"].format(period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.booked_reserve"].format(value=_fmt(booked_current)),
        [k["fact_booked_current"]],
        reasoning="The booked reserve is exactly what SYSTEM_OF_RECORD answers correctly — "
                  "the contrast that keeps the family from being solvable by always "
                  "preferring the actuarial voice.",
        sources=[memo], distractors=[report],
    )

    # -- causal_multi_hop: diagonal -> emergence -> attribution -> lore ------
    case(
        t["q.causal.why_strengthened"],
        EvaluationType.CAUSAL_MULTI_HOP,
        t["a.causal.why_strengthened"].format(
            pattern=_fmt(pattern), deterioration=_fmt(deterioration),
        ),
        [k[f"fact_avse_{first_cohort}"], k["fact_attribution_pattern"],
         k["fact_attribution_deterioration"]],
        reasoning="The chain runs diagonal -> actual-versus-expected -> attribution split "
                  "-> the 2024 transformation lore, spanning the emergence note and the "
                  "valuation report.",
        sources=[note, report],
    )

    # -- numerical_comparison: identities whose terms sit at three authorities
    case(
        t["q.numerical.booked_identity"],
        EvaluationType.NUMERICAL_COMPARISON,
        t["a.numerical.booked_identity"].format(
            booked=_fmt(booked_current), central=_fmt(central_current), margin=_fmt(margin_current),
        ),
        [k["fact_booked_current"], k["fact_central_current"], k["fact_margin_current"]],
        difficulty="medium",
        reasoning="Booked, central, and margin are each stated as quantities in different "
                  "documents at different authorities; the identity is read, never "
                  "computed by the reader.",
        sources=[workbook, memo],
    )
    case(
        t["q.numerical.attribution_sums"],
        EvaluationType.NUMERICAL_COMPARISON,
        t["a.numerical.attribution_sums"].format(
            pattern=_fmt(pattern), deterioration=_fmt(deterioration),
            movement=f"{int(movement):,} {pattern.value.unit}",
        ),
        [k["fact_attribution_pattern"], k["fact_attribution_deterioration"]],
        difficulty="medium",
        reasoning="A checkable identity by construction (insurance check e): the two parts "
                  "sum exactly to the movement the committee recommendation states.",
        sources=[report],
    )

    # -- cross_artifact: no single document holds both sides of the join ----
    ultimate_current = by_id[k[f"fact_ultimate_current_{first_cohort}"]]
    ultimate_prior = by_id[k[f"fact_ultimate_prior_{first_cohort}"]]
    avse = by_id[k[f"fact_avse_{first_cohort}"]]
    case(
        t["q.cross.movement_matches_emergence"].format(accident_period=first_cohort),
        EvaluationType.CROSS_ARTIFACT,
        t["a.cross.movement_matches_emergence"].format(value=_fmt(avse)),
        [k[f"fact_ultimate_current_{first_cohort}"], k[f"fact_ultimate_prior_{first_cohort}"],
         k[f"fact_avse_{first_cohort}"]],
        reasoning="The workbook carries both valuations of the ultimate; the emergence "
                  "note carries the deviation. Neither document alone confirms the two "
                  "agree — the join is only correct because "
                  f"{int(ultimate_current.value.amount - ultimate_prior.value.amount)} "
                  "equals the recorded deviation by construction.",
        sources=[workbook, note],
    )

    # -- what the corpus deliberately cannot answer --------------------------
    builder.abstain(
        t["q.abstain.true_ultimate"].format(accident_period=first_cohort),
        "IBNR is by definition unobserved and the tail never resolves inside the "
        "corpus — the estimate is the best the record can state, and the true cost "
        "is structurally absent at every corpus size, not merely missing this "
        "quarter.",
    )

    # -- citation_required: the memo's mandatory dual citation ---------------
    case(
        t["q.citation.margin_memo_pair"],
        EvaluationType.CITATION_REQUIRED,
        t["a.citation.margin_memo_pair"],
        [k["fact_central_current"], k["fact_booked_current"]],
        reasoning="Checked by the validator (insurance check g) and asked by the "
                  "benchmark: an unexplained booked-below-central gap is a defect, and "
                  "the memo's citation of both facts is what makes it explained.",
        sources=[memo],
    )

    # The same gate the retail and banking taxonomies end with: a case is
    # generated only if every fact it expects is carried by some planned
    # artifact.
    return answerable(builder.cases, reachable_fact_ids(intents))
