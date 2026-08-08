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

from collections.abc import Mapping

from ..ids import Minter
from ..models import ArtifactIntent, EvaluationCase, EvaluationType
from . import episode_text
from .cases import CaseBuilder, answerable, fmt as _fmt, reachable_fact_ids
from .regulatory import ReturnEpisode

#: This taxonomy's surface text, keyed exactly as `evaluation.EVAL_TEXT` is —
#: one pack-overridable entry per question and per authored answer, extracted
#: verbatim from the f-strings this module always built. See that module's
#: table comment for why reasoning strings and bare fact values (a fact's
#: `text_value` read straight off the ledger, with no authored wrapper) are
#: deliberately absent: neither is what a retriever is graded against in a
#: way that re-voicing would change.
EVAL_TEXT: dict[str, str] = {
    "q.direct.cet1_capital":
        "What was {company}'s Common Equity Tier 1 capital for the quarter ended {period}?",
    "a.direct.cet1_capital": "{value}",
    "q.direct.minimum_ratio": "What minimum CET1 ratio does PSA 110 require?",
    "a.direct.minimum_ratio": "{value}",
    "q.direct.affected_facilities":
        "How many of {company}'s loan facilities were carried at stale collateral values?",
    "a.direct.affected_facilities": "{value}",
    "q.authority.cet1_ratio": "What was {company}'s CET1 ratio for the quarter ended {period}?",
    "a.authority.cet1_ratio":
        "{corrected} — the restated figure. The originally filed {filed} was"
        " corrected by the restatement.",
    "q.authority.current_lodgement":
        "Which lodgement is the current statement of {company}'s capital position for"
        " the quarter ended {period}, and how can that be established?",
    "a.authority.current_lodgement":
        "The restatement — it restates the original return, which remains on the"
        " record but no longer states the current figures.",
    "q.authority.second_line_confirmation":
        "Did the second line confirm the SME Secured collateral treatment before the"
        " return was filed?",
    "a.authority.second_line_confirmation":
        "No. Prudential Risk challenged the treatment on the record before lodgement"
        " and the challenge was still open when the CFO approved the filing. The"
        " return itself is silent on the challenge.",
    "q.temporal.reported_ratio_as_of":
        "As of {date}, what CET1 ratio had {company} reported for the quarter ended"
        " {period}?",
    "a.temporal.reported_ratio_as_of":
        "{value} — the figure as filed, which the later restatement proved wrong but"
        " which was the reported position on that date.",
    "q.temporal.challenge_vs_approval":
        "Was the second-line challenge raised before or after the CFO approved the"
        " return for lodgement?",
    "a.temporal.challenge_vs_approval":
        "Before — the challenge was logged on {challenge_date} and the CFO approved"
        " the return on {approval_date}.",
    "q.temporal.filed_vs_break":
        "Was the return filed before or after the reconciliation break was detected?",
    "a.temporal.filed_vs_break":
        "Before — the return was lodged on {filed_date}, and the break was detected"
        " on {break_date}.",
    "q.cross.first_surfaced":
        "Which routine process first surfaced the error in the quarterly capital"
        " return?",
    "a.cross.first_surfaced":
        "The daily liquidity coverage calculation — its reconciliation of collateral"
        " positions against the register flagged the break that led to the confirmed"
        " cause.",
    "q.causal.why_restated": "Why was the capital return for the quarter ended {period} restated?",
    "a.causal.why_restated":
        "{cause}. Risk-weighted assets were understated by {understatement}, the"
        " corrected ratio fell by {delta}, and the error was material under PSA 110.",
    "q.cross.summary_disclosure":
        "Did the board risk committee summary disclose that the second-line challenge"
        " predated the filing?",
    "a.cross.summary_disclosure":
        "No. The summary reports the restatement and the corrected position but"
        " neither the challenge nor its sequence; the audit review records both.",
    "q.numerical.bps_reduction":
        "By how many basis points did the restatement reduce the reported CET1 ratio,"
        " and did the ratio remain above the PSA 110 minimum?",
    "a.numerical.bps_reduction": "{delta}; yes — {corrected} against a {minimum} minimum.",
    "q.cross.meeting_had_challenge":
        "Did the meeting that approved the return for lodgement have the second-line"
        " challenge in front of it?",
    "a.cross.meeting_had_challenge":
        "Yes — the minutes table the challenge and its open status beside the"
        " decision to lodge at the preparer's figure.",
    "q.cross.meeting_attendance":
        "Who attended the meeting at which the return was approved for lodgement?",
    "a.cross.meeting_attendance":
        "The Group Chief Financial Officer and the Regulatory Reporting Manager.",
    "q.abstain.regulator_action":
        "What action did the Prudential Standards Authority take in response to the"
        " restatement?",
}


def evaluation_cases(
    minter: Minter,
    *,
    episode: ReturnEpisode,
    intents: tuple[ArtifactIntent, ...],
    period: str,
    company: str = "",
    text: Mapping[str, str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one challenged-return episode.

    ``text`` overrides entries of ``EVAL_TEXT`` — a pack re-voicing the
    benchmark itself, the same seam ``evaluation.evaluation_cases`` exposes
    for retail (see `generators/episode_text`).
    """
    t = episode_text.merged(EVAL_TEXT, text, field="evaluation_text")
    # The company's name substituted into every template before any `.format`
    # call sees it, so the sixteen call sites below keep passing exactly the
    # slots they always passed.
    #
    # This is the whole of the frozen-benchmark fix, and the reason it is one
    # line rather than a rewrite. Measured across four seeds at one period,
    # this taxonomy produced 16 of 16 *identical* question strings — and it
    # stayed at 16 of 16 when the archetype changed to a structurally different
    # bank, because the questions said "the bank's" and never named it. A
    # benchmark phrased that way cannot vary with the company no matter how
    # much the company varies, and across a mosaic it is also ambiguous: five
    # worlds asking "what was the bank's CET1 ratio" are five questions with
    # five different right answers and no way to tell them apart.
    # Falls back to the generic wording this taxonomy always used, so a
    # caller that does not name the company gets a sentence rather than
    # "What was 's CET1 ratio" — and so the templates stay readable in
    # isolation, which is how every test in `tests/test_eval_text.py`
    # reads them.
    t = {key: value.replace("{company}", company or "the bank")
         for key, value in t.items()}
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

    # The shared builder defaults difficulty to "medium"; this vertical's
    # families are hard by design, so the wrapper flips the default rather
    # than repeating "hard" at every call.
    builder = CaseBuilder(minter)

    def case(question: str, kind: EvaluationType, answer: str, facts: list[str], *,
             cutoff=None, difficulty: str = "hard", reasoning: str = "",  # type: ignore[no-untyped-def]
             sources: list[str | None] | None = None,
             distractors: list[str | None] | None = None) -> None:
        builder.case(question, kind, answer, facts, cutoff=cutoff,
                     difficulty=difficulty, reasoning=reasoning,
                     sources=sources, distractors=distractors)

    ratio_filed = by_id[k["fact_ratio_filed"]]
    ratio_corrected = by_id[k["fact_ratio_corrected"]]
    minimum = by_id[k["fact_minimum"]]
    delta = by_id[k["fact_delta"]]
    cause = by_id[k["fact_cause"]]

    # -- direct lookups. The floor the exit test measures the hard families
    # against: if a keyword baseline cannot pass these, a low score on the
    # authority families would prove nothing about hardness.
    case(
        t["q.direct.cet1_capital"].format(period=period),
        EvaluationType.DIRECT_LOOKUP,
        t["a.direct.cet1_capital"].format(value=_fmt(by_id[k["fact_cet1_capital"]])),
        [k["fact_cet1_capital"]], difficulty="easy",
        reasoning="Single lookup; the figure is unchanged by the restatement, so every "
                  "source agrees.",
        sources=[filed],
    )
    case(
        t["q.direct.minimum_ratio"],
        EvaluationType.DIRECT_LOOKUP, t["a.direct.minimum_ratio"].format(value=_fmt(minimum)),
        [k["fact_minimum"]],
        difficulty="easy",
        reasoning="Standing figure, stated wherever the position is.",
        sources=[filed],
    )
    case(
        t["q.direct.affected_facilities"],
        EvaluationType.DIRECT_LOOKUP,
        t["a.direct.affected_facilities"].format(value=_fmt(by_id[k["fact_affected"]])),
        [k["fact_affected"]], difficulty="easy",
        reasoning="Stated in the incident record and the RCA.",
        sources=[rca, incident],
    )

    # -- the contested figure: rank ties, only the relationship resolves ------
    case(
        t["q.authority.cet1_ratio"].format(period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.cet1_ratio"].format(
            corrected=_fmt(ratio_corrected), filed=_fmt(ratio_filed)
        ),
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
        t["q.authority.current_lodgement"].format(period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.current_lodgement"],
        [k["fact_status_restated"], k["fact_ratio_corrected"]],
        reasoning="Nothing distinguishes the two lodgements by authority or type; the "
                  "restates relationship is the only discriminator.",
        sources=[restatement], distractors=[filed],
    )

    # -- contested standing: the official document omits the answer -----------
    case(
        t["q.authority.second_line_confirmation"],
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.second_line_confirmation"],
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
        t["q.temporal.reported_ratio_as_of"].format(
            date=between.date().isoformat(), period=period
        ),
        EvaluationType.TEMPORAL_STATE,
        t["a.temporal.reported_ratio_as_of"].format(
            value=_fmt(by_id[k["fact_ratio_as_filed"]])
        ),
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
        t["q.temporal.challenge_vs_approval"],
        EvaluationType.TEMPORAL_STATE,
        t["a.temporal.challenge_vs_approval"].format(
            challenge_date=challenge.valid_from.date().isoformat(),
            approval_date=approval.valid_from.date().isoformat(),
        ),
        [k["fact_challenge"], k["fact_approval"]],
        reasoning="The dates live in different documents; neither mentions the other's "
                  "event, so the order is recoverable only by joining timestamps.",
        sources=[audit],
    )
    breach = by_id[k["fact_break"]]
    case(
        t["q.temporal.filed_vs_break"],
        EvaluationType.TEMPORAL_STATE,
        t["a.temporal.filed_vs_break"].format(
            filed_date=episode.filed_at.date().isoformat(),
            break_date=breach.valid_from.date().isoformat(),
        ),
        [k["fact_filed_at"], k["fact_break"]],
        reasoning="The filing metadata and the incident record never reference each "
                  "other; the order is a cross-document join on timestamps.",
        sources=[filed, rca],
    )

    # -- the cadence join: no document contains both ends ----------------------
    case(
        t["q.cross.first_surfaced"],
        EvaluationType.CROSS_ARTIFACT,
        t["a.cross.first_surfaced"],
        [k["fact_break"], k["fact_cause"]],
        reasoning="The incident record never says 'quarterly return' and the "
                  "restatement never says 'liquidity'; the bridge is the shared "
                  "collateral-sync dependency, stated only in the RCA and the service "
                  "graph.",
        sources=[rca], distractors=[summary],
    )

    # -- the causal chain, with the wrong hypothesis as the dense answer ------
    case(
        t["q.causal.why_restated"].format(period=period),
        EvaluationType.CAUSAL_MULTI_HOP,
        t["a.causal.why_restated"].format(
            cause=cause.text_value,
            understatement=_fmt(by_id[k["fact_understatement"]]),
            delta=_fmt(delta),
        ),
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
        t["q.cross.summary_disclosure"],
        EvaluationType.CROSS_ARTIFACT,
        t["a.cross.summary_disclosure"],
        [k["fact_challenge"], k["fact_approval"]],
        reasoning="Requires establishing absence in one artifact against presence in "
                  "another — the labelled omission made falsifiable.",
        sources=[summary, audit],
    )
    case(
        t["q.numerical.bps_reduction"],
        EvaluationType.NUMERICAL_COMPARISON,
        t["a.numerical.bps_reduction"].format(
            delta=_fmt(delta), corrected=_fmt(ratio_corrected), minimum=_fmt(minimum)
        ),
        [k["fact_delta"], k["fact_ratio_corrected"], k["fact_minimum"]],
        difficulty="medium",
        reasoning="Both figures are stated as quantities, so the comparison is read, "
                  "never computed by the reader.",
        sources=[summary],
    )

    # -- the approval meeting, on the record ----------------------------------
    # The minutes are the one document that tables the challenge beside the
    # decision to file — the pairing the return omits and the summary never
    # mentions — so these cases have exactly one honest source. (Inserting
    # before the abstention shifts its EVAL id, which is safe here: unlike the
    # retail reference corpus, nothing checked-in cites banking ids.)
    minutes = next((i.id for i in intents if i.artifact_type == "meeting_minutes"), None)
    if minutes:
        case(
            t["q.cross.meeting_had_challenge"],
            EvaluationType.CROSS_ARTIFACT,
            t["a.cross.meeting_had_challenge"],
            [k["fact_challenge"], k["fact_challenge_open"], k["fact_approval"]],
            reasoning="The filing is silent by labelled omission and the challenge "
                      "memo predates the meeting; only the minutes hold both the "
                      "challenge and the decision in one record.",
            sources=[minutes], distractors=[filed],
        )
        case(
            t["q.cross.meeting_attendance"],
            EvaluationType.CROSS_ARTIFACT,
            t["a.cross.meeting_attendance"],
            [k["fact_approval"]], difficulty="medium",
            reasoning="Attendance is recorded only in the minutes.",
            sources=[minutes],
        )

    # -- what the corpus deliberately cannot answer ---------------------------
    builder.abstain(
        t["q.abstain.regulator_action"],
        "The corpus records the bank's notification and deliberately nothing "
        "after it — the regulator's side is out of world, so this stays "
        "unanswerable at every corpus size.",
    )

    # The same gate the retail taxonomy ends with: a case is generated only if
    # every fact it expects is carried by some planned artifact.
    return answerable(builder.cases, reachable_fact_ids(intents))
