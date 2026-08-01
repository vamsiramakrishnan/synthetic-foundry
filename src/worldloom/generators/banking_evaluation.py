"""The banking evaluation families.

Eight families over one challenged return, and the design constraint that
matters most is stated by the pair in the middle: the contested-figure case
(answer: the restated ratio) is *always* generated together with the
between-filings cutoff case (answer: the filed, later-proven-wrong ratio). A
retriever biased toward the restatement fixes the first and fails the second;
biased toward the filing, vice versa. No lexical heuristic satisfies both,
which is the property the A10 gate demanded and the retail episode could not
produce — its contested pairs always differed in authority rank, so rank alone
resolved them. Here both lodgements are SYSTEM_OF_RECORD, and only the
``restates`` edge and the facts' validity windows can.

Every non-abstention case passes the same reachable-facts gate the retail
taxonomy applies: a question whose answer no planned artifact carries is not
hard, it is unanswerable, and it is dropped before it is ever minted into the
corpus rather than explained afterwards.
"""

from __future__ import annotations

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact, EvaluationCase, EvaluationType
from .regulatory import ReturnEpisode


def _fmt(fact: CanonicalFact) -> str:
    if fact.value is not None:
        amount = fact.value.amount
        rendered = f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
        return f"{rendered} {fact.value.unit}"
    return fact.text_value or ""


def evaluation_cases(
    minter: Minter,
    *,
    episode: ReturnEpisode,
    intents: tuple[ArtifactIntent, ...],
    period: str,
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one challenged-return episode."""
    k = episode.keys
    by_id = {f.id: f for f in episode.facts}

    returns = [i for i in intents if i.artifact_type == "capital_return"]
    filed = next((i.id for i in returns if not i.restates), None)
    restatement = next((i.id for i in returns if i.restates), None)
    memo = next((i.id for i in intents if i.artifact_type == "second_line_challenge_memo"), None)
    rca = next((i.id for i in intents if i.artifact_type == "incident_rca"), None)
    incident = next((i.id for i in intents if i.artifact_type == "servicenow_incident"), None)
    audit = next((i.id for i in intents if i.artifact_type == "internal_audit_review"), None)
    summary = next(
        (i.id for i in intents if i.artifact_type == "board_risk_committee_summary"), None
    )

    cases: list[EvaluationCase] = []

    def case(question: str, kind: EvaluationType, answer: str, facts: list[str], *,
             cutoff=None, difficulty: str = "hard", reasoning: str = "",  # type: ignore[no-untyped-def]
             sources: list[str | None] | None = None,
             distractors: list[str | None] | None = None) -> None:
        cases.append(EvaluationCase(
            id=minter.next("EVAL"),
            question=question,
            evaluation_type=kind,
            expected_answer=answer,
            expected_fact_ids=facts,
            required_artifact_ids=[a for a in (sources or []) if a],
            distractor_artifact_ids=[a for a in (distractors or []) if a],
            temporal_cutoff=cutoff,
            difficulty=difficulty,  # type: ignore[arg-type]
            reasoning=reasoning,
        ))

    ratio_filed = by_id[k["fact_ratio_filed"]]
    ratio_corrected = by_id[k["fact_ratio_corrected"]]
    minimum = by_id[k["fact_minimum"]]
    delta = by_id[k["fact_delta"]]
    cause = by_id[k["fact_cause"]]

    # -- direct lookups. The floor the exit test measures the hard families
    # against: if a keyword baseline cannot pass these, a low score on the
    # authority families would prove nothing about hardness.
    case(
        f"What was the bank's Common Equity Tier 1 capital for the quarter ended {period}?",
        EvaluationType.DIRECT_LOOKUP, _fmt(by_id[k["fact_cet1_capital"]]),
        [k["fact_cet1_capital"]], difficulty="easy",
        reasoning="Single lookup; the figure is unchanged by the restatement, so every "
                  "source agrees.",
        sources=[filed],
    )
    case(
        "What minimum CET1 ratio does PSA 110 require?",
        EvaluationType.DIRECT_LOOKUP, _fmt(minimum), [k["fact_minimum"]],
        difficulty="easy",
        reasoning="Standing figure, stated wherever the position is.",
        sources=[filed],
    )
    case(
        "How many loan facilities were carried at stale collateral values?",
        EvaluationType.DIRECT_LOOKUP, _fmt(by_id[k["fact_affected"]]),
        [k["fact_affected"]], difficulty="easy",
        reasoning="Stated in the incident record and the RCA.",
        sources=[rca, incident],
    )

    # -- the contested figure: rank ties, only the relationship resolves ------
    case(
        f"What was the bank's CET1 ratio for the quarter ended {period}?",
        EvaluationType.AUTHORITY_RESOLUTION,
        f"{_fmt(ratio_corrected)} — the restated figure. The originally filed "
        f"{_fmt(ratio_filed)} was corrected by the restatement.",
        # The corrected fact only. Listing the filed figure beside it — the
        # retail pattern for contested pairs — would let a retriever that
        # surfaced the wrong lodgement claim it carried "an" expected fact;
        # here the two lodgements tie on authority, so carrying the answer is
        # the only thing left to grade.
        [k["fact_ratio_corrected"]],
        reasoning="Both lodgements are SYSTEM_OF_RECORD, so authority rank ties; the "
                  "filed return is the larger, keyword-densest document and states the "
                  "wrong figure. Only the restates edge or fact supersession resolves it.",
        sources=[restatement], distractors=[filed],
    )
    case(
        "Which lodgement is the current statement of the bank's capital position for "
        f"the quarter ended {period}, and how can that be established?",
        EvaluationType.AUTHORITY_RESOLUTION,
        "The restatement — it restates the original return, which remains on the "
        "record but no longer states the current figures.",
        [k["fact_status_restated"], k["fact_ratio_corrected"]],
        reasoning="Nothing distinguishes the two lodgements by authority or type; the "
                  "restates relationship is the only discriminator.",
        sources=[restatement], distractors=[filed],
    )

    # -- contested standing: the official document omits the answer -----------
    case(
        "Did the second line confirm the SME Secured collateral treatment before the "
        "return was filed?",
        EvaluationType.AUTHORITY_RESOLUTION,
        "No. Prudential Risk challenged the treatment on the record before lodgement "
        "and the challenge was still open when the CFO approved the filing. The "
        "return itself is silent on the challenge.",
        [k["fact_challenge"], k["fact_challenge_open"], k["fact_approval"]],
        reasoning="Keyword retrieval surfaces the filing — the highest-authority, "
                  "densest document — which omits the answer by labelled omission. "
                  "Resolution requires ranking the lower-formality challenge memo over "
                  "the official record, which authority rank alone argues against.",
        sources=[memo, audit], distractors=[filed],
    )

    # -- the temporal inverse, generated with the contested figure always -----
    between = episode.filed_at + (episode.restated_at - episode.filed_at) / 2
    case(
        f"As of {between.date().isoformat()}, what CET1 ratio had the bank reported "
        f"for the quarter ended {period}?",
        EvaluationType.TEMPORAL_STATE,
        f"{_fmt(by_id[k['fact_ratio_as_filed']])} — the figure as filed, which the "
        "later restatement proved wrong but which was the reported position on that "
        "date.",
        [k["fact_ratio_as_filed"]], cutoff=between,
        reasoning="The deliberate pair to the contested-figure case: a retriever "
                  "biased toward the restatement answers that one and fails this; "
                  "biased toward the filing, the reverse. No lexical bias satisfies "
                  "both.",
        sources=[filed], distractors=[restatement],
    )

    # -- ordering across documents that never mention each other --------------
    challenge = by_id[k["fact_challenge"]]
    approval = by_id[k["fact_approval"]]
    case(
        "Was the second-line challenge raised before or after the CFO approved the "
        "return for lodgement?",
        EvaluationType.TEMPORAL_STATE,
        f"Before — the challenge was logged on {challenge.valid_from.date().isoformat()} "
        f"and the CFO approved the return on {approval.valid_from.date().isoformat()}.",
        [k["fact_challenge"], k["fact_approval"]],
        reasoning="The dates live in different documents; neither mentions the other's "
                  "event, so the order is recoverable only by joining timestamps.",
        sources=[audit],
    )
    breach = by_id[k["fact_break"]]
    case(
        "Was the return filed before or after the reconciliation break was detected?",
        EvaluationType.TEMPORAL_STATE,
        f"Before — the return was lodged on {episode.filed_at.date().isoformat()}, and "
        f"the break was detected on {breach.valid_from.date().isoformat()}.",
        [k["fact_filed_at"], k["fact_break"]],
        reasoning="The filing metadata and the incident record never reference each "
                  "other; the order is a cross-document join on timestamps.",
        sources=[filed, rca],
    )

    # -- the cadence join: no document contains both ends ----------------------
    case(
        "Which routine process first surfaced the error in the quarterly capital "
        "return?",
        EvaluationType.CROSS_ARTIFACT,
        "The daily liquidity coverage calculation — its reconciliation of collateral "
        "positions against the register flagged the break that led to the confirmed "
        "cause.",
        [k["fact_break"], k["fact_cause"]],
        reasoning="The incident record never says 'quarterly return' and the "
                  "restatement never says 'liquidity'; the bridge is the shared "
                  "collateral-sync dependency, stated only in the RCA and the service "
                  "graph.",
        sources=[rca], distractors=[summary],
    )

    # -- the causal chain, with the wrong hypothesis as the dense answer ------
    case(
        f"Why was the capital return for the quarter ended {period} restated?",
        EvaluationType.CAUSAL_MULTI_HOP,
        f"{cause.text_value}. Risk-weighted assets were understated by "
        f"{_fmt(by_id[k['fact_understatement']])}, the corrected ratio fell by "
        f"{_fmt(delta)}, and the error was material under PSA 110.",
        [k["fact_break"], k["fact_cause"], k["fact_understatement"],
         k["fact_materiality"], k["fact_restatement_reason"]],
        reasoning="The chain runs break → incident → ruled-out FX hypothesis → stale "
                  "mapping → understatement → materiality → restatement. The incident "
                  "record carries the superseded hypothesis in its densest "
                  "cause-flavoured prose.",
        sources=[rca, restatement], distractors=[incident],
    )

    # -- information asymmetry: absence proved against presence ---------------
    case(
        "Did the board risk committee summary disclose that the second-line challenge "
        "predated the filing?",
        EvaluationType.CROSS_ARTIFACT,
        "No. The summary reports the restatement and the corrected position but "
        "neither the challenge nor its sequence; the audit review records both.",
        [k["fact_challenge"], k["fact_approval"]],
        reasoning="Requires establishing absence in one artifact against presence in "
                  "another — the labelled omission made falsifiable.",
        sources=[summary, audit],
    )
    case(
        "By how many basis points did the restatement reduce the reported CET1 ratio, "
        "and did the ratio remain above the PSA 110 minimum?",
        EvaluationType.NUMERICAL_COMPARISON,
        f"{_fmt(delta)}; yes — {_fmt(ratio_corrected)} against a {_fmt(minimum)} "
        "minimum.",
        [k["fact_delta"], k["fact_ratio_corrected"], k["fact_minimum"]],
        difficulty="medium",
        reasoning="Both figures are stated as quantities, so the comparison is read, "
                  "never computed by the reader.",
        sources=[summary],
    )

    # -- what the corpus deliberately cannot answer ---------------------------
    cases.append(EvaluationCase(
        id=minter.next("EVAL"),
        question="What action did the Prudential Standards Authority take in response "
                 "to the restatement?",
        evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
        expected_answer="Not present in the corpus.",
        expects_abstention=True,
        difficulty="hard",
        reasoning="The corpus records the bank's notification and deliberately nothing "
                  "after it — the regulator's side is out of world, so this stays "
                  "unanswerable at every corpus size.",
    ))

    # The same gate the retail taxonomy ends with: a case is generated only if
    # every fact it expects is carried by some planned artifact.
    reachable: set[str] = set()
    for intent in intents:
        reachable.update(intent.required_fact_ids)
    return tuple(
        case for case in cases
        if case.expects_abstention or set(case.expected_fact_ids) <= reachable
    )
