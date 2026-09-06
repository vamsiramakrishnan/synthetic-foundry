"""The procure-to-pay evaluation families.

Nine families over one purchase cycle, and the property that matters most is
the one the vertical was chosen for: **three documents, three questions, and
each document is the only correct answer to exactly one of them.**

    what did we agree to pay per unit?   →  the purchase order      (APPROVED_REPORT)
    what did we actually receive?        →  the goods receipt note  (SYSTEM_OF_RECORD)
    what did the supplier bill?          →  the supplier invoice    (SYSTEM_OF_RECORD)

``AUTHORITY_RANK`` cannot separate the second from the third — they tie — and
it actively **inverts** the first, because the invoice is SYSTEM_OF_RECORD in
the payables subledger and the contracted rate is only an APPROVED_REPORT.
That is a different failure from the two the corpus already had. Banking's
filed-versus-restated pair ties; insurance's central-estimate question
inverts. This is both at once, over three documents rather than two, and the
three cases are generated together for the reason banking generates its
contested pair together: a retriever that always prefers rank passes one and
fails another, and a retriever that has learned to distrust invoices fails the
third.

The clean line is the control and it is inside the *same three documents*. A
question about it is answered correctly by any of them, which is what stops
the family being solvable by a heuristic about which document type to trust.

Every non-abstention case passes the same reachable-facts gate the retail,
banking and insurance taxonomies apply — here against the *world's* planned
artifacts rather than only this episode's, because the multi-period case
deliberately asks about a fact an earlier month's memo carries.
"""

from __future__ import annotations

from collections.abc import Mapping

from ..ids import Minter
from ..models import ArtifactIntent, EvaluationCase, EvaluationType
from . import episode_text
from .cases import CaseBuilder, answerable, reachable_fact_ids
from .cases import fmt as _fmt
from .procurement_cycle import ProcurementEpisode

#: This taxonomy's surface text, keyed exactly as the other three engines'
#: tables are — one pack-overridable entry per question and per authored
#: answer. See ``evaluation.EVAL_TEXT`` for why reasoning strings and bare
#: fact values are deliberately absent.
EVAL_TEXT: dict[str, str] = {
    "q.authority.contract_rate":
        "What unit rate is the group contractually obliged to pay for {category} on the"
        " {period} order?",
    "a.authority.contract_rate":
        "{rate} — the contracted rate, stated on the purchase order. The {invoiced} the"
        " supplier billed at is what was claimed, not what was agreed.",
    "q.authority.received_quantity":
        "How much {category} did the group actually receive against the {period} order?",
    "a.authority.received_quantity":
        "{received} — what site signed for. The order committed {ordered} and the invoice"
        " bills for {invoiced}; neither is a record of what arrived.",
    "q.authority.invoiced_total":
        "What did the supplier bill in total on the {period} invoice?",
    "a.authority.invoiced_total":
        "{value} — the invoice as posted to the payables subledger, which is the record of"
        " what was claimed whether or not any of it was agreed.",
    "q.direct.clean_line":
        "How much {category} was received against the {period} order?",
    "a.direct.clean_line":
        "{received} — ordered, received and invoiced in full, so all three documents agree.",
    "q.cross.accrual_provenance":
        "What was accrued at the {period} close for goods received and not invoiced, and"
        " which document is that figure built from?",
    "a.cross.accrual_provenance":
        "{accrual} — built from the goods receipt note, valued at the contracted rate,"
        " plus {released} received against an earlier short delivery. The supplier invoice"
        " contributes nothing to it.",
    "q.numerical.variance_splits":
        "Do the quantity and price halves of the {period} match variance sum to the total"
        " variance the exception report states?",
    "a.numerical.variance_splits":
        "Yes — {quantity} billed and not received plus {price} billed above the contracted"
        " rate equals the {total} total variance.",
    "q.numerical.settlement":
        "Does the invoiced total less the credit note equal the amount approved for"
        " payment for {period}?",
    "a.numerical.settlement":
        "Yes — {invoiced} invoiced less {credit} credited equals the {approved} approved"
        " for payment, which is the received quantity at the contracted rate.",
    "q.causal.why_not_paid_in_full":
        "Why was the {period} supplier invoice not paid in full?",
    "a.causal.why_not_paid_in_full":
        "The three-way match failed twice over: {quantity} was billed for goods that were"
        " never received, and {price} was billed above the contracted rate. The combined"
        " {total} exceeded the {tolerance} approval tolerance, so the exception went to"
        " Finance and was settled by credit note at the contracted rate.",
    "q.temporal.exception_at_escalation":
        "What was the status of the {period} match exception at the moment it was"
        " escalated to Finance?",
    "a.temporal.exception_at_escalation": "{value}",
    "q.temporal.prior_shortfall":
        "How much of the {prior_period} order was still undelivered at that month's close?",
    "a.temporal.prior_shortfall":
        "{value} — the balance outstanding at the {prior_period} close, which is not the"
        " balance outstanding now.",
    "q.citation.approval_pair":
        "Which two facts must the payment approval memo carry for the {period} settlement"
        " to be auditable?",
    "a.citation.approval_pair":
        "The total match variance and who approved it. Without the variance the memo does"
        " not say why Finance was involved; without the approver it does not say the"
        " delegation was followed, and the buyer who raised the order is not permitted to"
        " clear it.",
    "q.abstain.remittance_details":
        "What are the supplier's new bank account details after the requested vendor"
        " master change?",
}


def evaluation_cases(
    minter: Minter,
    *,
    episode: ProcurementEpisode,
    intents: tuple[ArtifactIntent, ...],
    period: str,
    category_names: Mapping[str, str],
    reachable: frozenset[str] | None = None,
    text: Mapping[str, str] | None = None,
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one purchase cycle.

    ``reachable`` is the fact ids some planned artifact in the *world* carries,
    which is wider than this episode's own intents and is deliberately so: the
    multi-period question asks about a balance an earlier month's payment memo
    states, and gating it on this month's plan alone would drop exactly the
    case a history exists to make askable. Defaults to this episode's intents,
    so a caller that has no world (a unit test, an in-process build of one
    period) gets the same gate the other three taxonomies apply.

    ``text`` overrides entries of ``EVAL_TEXT`` — a pack re-voicing the
    benchmark itself, the seam ``generators/episode_text`` provides.
    """
    t = episode_text.merged(EVAL_TEXT, text, field="evaluation_text")
    k = episode.keys
    by_id = {f.id: f for f in episode.facts}
    if reachable is None:
        reachable = reachable_fact_ids(intents)

    def artifact(kind: str) -> str | None:
        return next((i.id for i in intents if i.artifact_type == kind), None)

    order_doc = artifact("purchase_order")
    receipt_doc = artifact("goods_receipt_note")
    invoice_doc = artifact("supplier_invoice")
    exception_doc = artifact("match_exception_report")
    memo_doc = artifact("payment_approval_memo")

    contested = next(line for line in episode.position.lines if not line.is_clean)
    clean = next(line for line in episode.position.lines if line.is_clean)
    contested_name = category_names.get(contested.category_id, contested.category_id)
    clean_name = category_names.get(clean.category_id, clean.category_id)

    # This vertical's families are hard by design, so the builder's default
    # flips to "hard" rather than repeating it at every call, the same choice
    # `banking_evaluation` makes.
    builder = CaseBuilder(minter, default_difficulty="hard")
    case = builder.case

    rate = by_id[k[f"fact_contract_rate_{contested.category_id}"]]
    invoiced_price = by_id[k[f"fact_invoiced_unit_price_{contested.category_id}"]]
    ordered_qty = by_id[k[f"fact_ordered_quantity_{contested.category_id}"]]
    received_qty = by_id[k[f"fact_received_quantity_{contested.category_id}"]]
    invoiced_qty = by_id[k[f"fact_invoiced_quantity_{contested.category_id}"]]
    invoiced_total = by_id[k["fact_invoiced_value_total"]]
    quantity_variance = by_id[k["fact_quantity_variance_total"]]
    price_variance = by_id[k["fact_price_variance_total"]]
    total_variance = by_id[k["fact_total_variance_total"]]
    tolerance = by_id[k["fact_approval_tolerance"]]
    credit_note = by_id[k["fact_credit_note_value"]]
    approved_payment = by_id[k["fact_approved_payment_value"]]
    accrual = by_id[k["fact_accrual"]]
    released = by_id[k["fact_shortfall_released_value"]]

    # -- authority_resolution ×3: three documents, three right answers -------
    # The order matters here in the same way banking's contested pair does:
    # these are generated together so that no single preference — for rank, for
    # recency, for the ledger, for the contract — passes all three.
    case(
        t["q.authority.contract_rate"].format(category=contested_name, period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.contract_rate"].format(rate=_fmt(rate), invoiced=_fmt(invoiced_price)),
        [k[f"fact_contract_rate_{contested.category_id}"]],
        reasoning="SYSTEM_OF_RECORD outranks APPROVED_REPORT in AUTHORITY_RANK, so rank "
                  "alone picks the invoiced unit price — the wrong source for what was "
                  "agreed. The payables subledger is the record of what was billed and "
                  "has no view at all on what was contracted.",
        sources=[order_doc], distractors=[invoice_doc],
    )
    case(
        t["q.authority.received_quantity"].format(category=contested_name, period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.received_quantity"].format(
            received=_fmt(received_qty), ordered=_fmt(ordered_qty),
            invoiced=_fmt(invoiced_qty),
        ),
        [k[f"fact_received_quantity_{contested.category_id}"]],
        reasoning="Two documents state a quantity at SYSTEM_OF_RECORD and a third states "
                  "one at APPROVED_REPORT, and rank cannot separate the first two. Only "
                  "reading which system is the record *of what* — receipting records "
                  "arrival, payables records billing — resolves it.",
        sources=[receipt_doc], distractors=[order_doc, invoice_doc],
    )
    case(
        t["q.authority.invoiced_total"].format(period=period),
        EvaluationType.AUTHORITY_RESOLUTION,
        t["a.authority.invoiced_total"].format(value=_fmt(invoiced_total)),
        [k["fact_invoiced_value_total"]],
        reasoning="The contrast case: here the invoice is exactly right, and a retriever "
                  "that has learned from the two above to distrust invoices fails it. "
                  "What was billed is a fact about the invoice, and the invoice is its "
                  "record.",
        sources=[invoice_doc], distractors=[order_doc, memo_doc],
    )

    # -- direct_lookup: the clean line, in the same three documents ----------
    case(
        t["q.direct.clean_line"].format(category=clean_name, period=period),
        EvaluationType.DIRECT_LOOKUP,
        t["a.direct.clean_line"].format(received=_fmt(by_id[
            k[f"fact_received_quantity_{clean.category_id}"]])),
        [k[f"fact_received_quantity_{clean.category_id}"]],
        difficulty="easy",
        reasoning="The control. This line sits in the same purchase order, the same goods "
                  "receipt and the same invoice as the contested one, and on it all three "
                  "agree — so the family above cannot be passed by a rule about which "
                  "document type to believe.",
        sources=[receipt_doc],
    )

    # -- cross_artifact: the composition with the close ----------------------
    # The question this vertical exists to make askable. No prior corpus could
    # pose it: the finance close and the thing that produced its figures were
    # the same engine, so "which document is this ledger number built from"
    # had one possible answer.
    case(
        t["q.cross.accrual_provenance"].format(period=period),
        EvaluationType.CROSS_ARTIFACT,
        t["a.cross.accrual_provenance"].format(
            accrual=_fmt(accrual), released=_fmt(released),
        ),
        [k["fact_accrual"], k["fact_received_value_total"],
         k["fact_shortfall_released_value"]],
        reasoning="The general ledger figure is the receipt quantity at the contracted "
                  "rate — one number from the receipting system and one from the sourcing "
                  "system, and neither from the invoice, which is both larger and higher "
                  "ranked. The join spans the goods receipt note and the payment approval "
                  "memo and exists in neither alone.",
        sources=[receipt_doc, memo_doc], distractors=[invoice_doc],
    )

    # -- numerical_comparison: identities whose terms sit at three authorities
    case(
        t["q.numerical.variance_splits"].format(period=period),
        EvaluationType.NUMERICAL_COMPARISON,
        t["a.numerical.variance_splits"].format(
            quantity=_fmt(quantity_variance), price=_fmt(price_variance),
            total=_fmt(total_variance),
        ),
        [k["fact_quantity_variance_total"], k["fact_price_variance_total"],
         k["fact_total_variance_total"]],
        difficulty="medium",
        reasoning="A checkable identity by construction (procurement check f): the two "
                  "halves are computed from the three documents and sum exactly to the "
                  "total the exception report escalated on.",
        sources=[exception_doc],
    )
    case(
        t["q.numerical.settlement"].format(period=period),
        EvaluationType.NUMERICAL_COMPARISON,
        t["a.numerical.settlement"].format(
            invoiced=_fmt(invoiced_total), credit=_fmt(credit_note),
            approved=_fmt(approved_payment),
        ),
        [k["fact_invoiced_value_total"], k["fact_credit_note_value"],
         k["fact_approved_payment_value"]],
        difficulty="medium",
        reasoning="Three figures at three authorities in two documents, and the identity "
                  "is read rather than computed by the reader — but it only closes "
                  "because the approved payment is the received quantity at the "
                  "contracted rate, which is the point the memo has to make and the "
                  "invoice cannot.",
        sources=[invoice_doc, memo_doc],
    )

    # -- causal_multi_hop: receipt -> match -> tolerance -> delegation --------
    case(
        t["q.causal.why_not_paid_in_full"].format(period=period),
        EvaluationType.CAUSAL_MULTI_HOP,
        t["a.causal.why_not_paid_in_full"].format(
            quantity=_fmt(quantity_variance), price=_fmt(price_variance),
            total=_fmt(total_variance), tolerance=_fmt(tolerance),
        ),
        [k["fact_quantity_variance_total"], k["fact_price_variance_total"],
         k["fact_approval_tolerance"]],
        reasoning="Four hops, and the last one is a norm rather than a number: the short "
                  "delivery and the rate uplift produce a variance, the variance exceeds "
                  "a tolerance derived from the order's own value, and the delegation "
                  "lore is what turns that into somebody else's decision.",
        sources=[exception_doc, memo_doc],
    )

    # -- temporal_state: a mid-chain link with no wrongness marker -----------
    escalated = by_id[k["fact_exception_escalated"]]
    case(
        t["q.temporal.exception_at_escalation"].format(period=period),
        EvaluationType.TEMPORAL_STATE,
        t["a.temporal.exception_at_escalation"].format(value=_fmt(escalated)),
        [k["fact_exception_escalated"]], cutoff=escalated.valid_from,
        reasoning="The status chain runs raised → escalated → resolved inside one month, "
                  "and the middle link reads exactly as confident as the one that "
                  "replaced it. Nothing marks it as stale; only its validity window does.",
        sources=[exception_doc], distractors=[memo_doc],
    )

    # -- temporal_state, across months: the same fact kind, a different period
    # Generated only when there *was* a prior month, and gated on the world's
    # own reachable set rather than this episode's — the earlier month's
    # payment memo is what carries the answer, and this month's plan has never
    # heard of it.
    prior_shortfall = k.get("fact_prior_open_shortfall")
    if prior_shortfall is not None:
        case(
            t["q.temporal.prior_shortfall"].format(prior_period=episode.prior_period),
            EvaluationType.TEMPORAL_STATE,
            t["a.temporal.prior_shortfall"].format(
                value=f"{episode.released_value:,.2f} {accrual.value.unit}",
                prior_period=episode.prior_period,
            ),
            [prior_shortfall],
            reasoning="Two facts of one kind and one subject, unsuperseded, both "
                      "SYSTEM_OF_RECORD, differing only in which month they are about — "
                      "and this month's memo states the other one prominently. Nothing "
                      "lexical separates them; the period does.",
            sources=[], distractors=[memo_doc],
        )

    # -- citation_required: what makes the approval auditable ----------------
    case(
        t["q.citation.approval_pair"].format(period=period),
        EvaluationType.CITATION_REQUIRED,
        t["a.citation.approval_pair"],
        [k["fact_total_variance_total"], k["fact_exception_approved_by"]],
        reasoning="Checked by the validator (procurement check h) and asked by the "
                  "benchmark: an above-tolerance settlement with no approver on the "
                  "record, or one approved by the person who raised the order, is a "
                  "control failure rather than a document that is merely thin.",
        sources=[memo_doc],
    )

    # -- what the corpus deliberately cannot answer --------------------------
    builder.abstain(
        t["q.abstain.remittance_details"],
        "Bank account details are never recorded anywhere in this corpus, at any size, "
        "in any period. The vendor master change document says that a change was "
        "requested and is being held; it does not say what to, and no other document "
        "does either — the absence is structural, not a gap this month happens to have.",
    )

    return answerable(builder.cases, reachable)


__all__ = ["EVAL_TEXT", "evaluation_cases"]
