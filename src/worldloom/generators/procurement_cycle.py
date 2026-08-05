"""The procure-to-pay episode generator: one monthly purchase cycle.

Produces "The Contested Invoice" — the procurement vertical's episode — in
``operations.py``'s idiom: a frozen result carrying events, facts, and a keys
dict of named handles, with every timestamp pure arithmetic on the period
string and every drawn number taken from a stream named for what it is.

The episode's shape, and why each part is there:

* **Three documents, three authorities, one order.** The purchase order
  (APPROVED_REPORT, out of the sourcing and ordering systems) says what was
  committed and at what rate. The goods receipt (SYSTEM_OF_RECORD, out of site
  receipting) says what arrived. The supplier invoice (SYSTEM_OF_RECORD, out
  of the accounts-payable subledger) says what was billed. All three are
  current, none supersedes another, and each is the *only* correct answer to
  its own question. Nothing in ``AUTHORITY_RANK`` resolves that, because it is
  not a contest about one fact — it is three facts a careless reader collapses
  into one.

* **The order composes with the close, and the composition runs the way a
  reader would not guess.** The month-end accrual for goods received and not
  invoiced (``financial.accrual.grni``, in the shared financial vocabulary the
  retail close already speaks) is built from the *receipt* quantity at the
  *contract* rate. The invoice — higher-ranked, more recent, and the document
  with the biggest number on it — contributes nothing to it. That is the
  cross-domain question this vertical exists to make askable: a general-ledger
  figure whose authority is a site receipting note.

* **The invoice is immutable, like a filing.** A wrong invoice is not edited
  and not superseded; it stands, and a credit note is posted beside it. Same
  discipline as banking's ``_as_filed`` facts and insurance's triangle
  diagonals, arrived at independently by the same reasoning: a document a
  third party sent you is evidence, and evidence that can be edited is not.

* **What does move is the exception's status**, which walks a real
  supersession chain inside one period — raised, escalated, resolved — with
  each superseded link closed exactly where its successor opens. None of them
  carries a marker that it was wrong, because none of them was: they are three
  correct statements about three different moments.

* **The undelivered balance carries into the next period.** A shortfall
  recorded at one close is released at the next one, when the goods actually
  arrive — which is what makes this a history rather than one month
  photocopied, and what makes "what was still outstanding at the March close"
  a question whose answer is a fact that is not marked as stale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from collections.abc import Mapping

from ..ids import Minter
from ..models import Authority, CanonicalFact, EnterpriseEvent, Quantity
from ..parameters import DEFAULT, Parameters
from ..rng import Rng
from . import episode_text
from .finance import previous_periods
from .operations import CALENDAR, Calendar, _at, business_days_after, period_end
from .procurement_match import MatchPosition

PCT = "pct"
UNITS = "units"

#: Suppliers this engine draws its counterparty name from. Invented trading
#: names, and deliberately generic ones: a synthetic corpus that named a real
#: subcontractor would be making a claim about a real company's commercial
#: conduct, which is the one thing every generator in this project is written
#: not to do.
_SUPPLIERS = (
    "Kerrigan Civil Services",
    "Ashgrove Plant and Labour",
    "Northline Subcontracting",
    "Tarrant Site Services",
)

#: The procurement engine's surface text — see ``generators/episode_text`` and
#: the identical tables in ``operations.py``, ``regulatory.py`` and
#: ``reserving.py``. A pack overrides by key through ``episode_text``.
TEXT: dict[str, str] = {
    'event.order_raised':
        'A purchase order was raised against the standing rate card and approved under '
        'delegated authority: two lines, committed quantity and contracted rate on each.',
    'event.vendor_change_requested':
        'The supplier requested a change to its remittance details. The change was logged '
        'against the vendor master and held: the standing norm requires two Finance '
        'approvers, and only one has signed.',
    'event.goods_received':
        'Site receipted the delivery. One line arrived in full; the other was signed for '
        'short, and the receipt records the quantity that actually arrived rather than the '
        'quantity ordered.',
    'event.close_started':
        '{period} month-end close commenced; the overnight ledger sequence began.',
    'event.invoice_received':
        "The supplier's invoice was received and posted to the accounts payable subledger. "
        'It bills the full ordered quantity, at a rate above the one on the order.',
    'event.match_run':
        'The three-way match was run: order against receipt against invoice. It failed on '
        'both counts — a quantity billed that was not received, and a rate billed that was '
        'not agreed.',
    'event.exception_escalated':
        'The match variance exceeded the approval tolerance, so the exception left the '
        "buyer's hands and went to Finance. Under the standing delegation the person who "
        'raised the order may not clear it.',
    'event.settlement_approved':
        'Finance approved settlement at the contracted rate for the quantity actually '
        'received. The supplier issued a credit note for the difference and will re-invoice '
        'the undelivered balance when it ships.',
    'event.close_finalised':
        '{period} close finalised and the ledger locked on the committed date. The accrual '
        'for goods received and not invoiced was posted from the receipt, not the invoice.',
    'fact.counterparty':
        '{supplier}, under the standing subcontract and plant rate card',
    'fact.exception_raised':
        'Three-way match failed: the invoice does not agree with the order or the receipt',
    'fact.exception_escalated':
        'Escalated to Finance: the total match variance exceeds the standing approval '
        'tolerance for this order',
    'fact.exception_resolved':
        'Resolved by credit note: settled at the contracted rate for the quantity received, '
        'with the undelivered balance to be re-invoiced on delivery',
    'fact.exception_approved_by':
        'Approved settlement of the {period} three-way match exception at the contracted '
        'rate, under the standing delegation of authority',
    'fact.vendor_change_status':
        'Remittance detail change requested by the supplier and held pending a second '
        'Finance approver; the payment run continues to use the details on file',
    'fact.tolerance_policy':
        'A match variance within the stated percentage of the committed order value may be '
        'cleared by the buyer; above it, Finance approves and the buyer may not',
}


@dataclass(frozen=True)
class ProcurementEpisode:
    """The events and facts of one monthly procure-to-pay cycle."""

    events: tuple[EnterpriseEvent, ...]
    facts: tuple[CanonicalFact, ...]
    period: str
    prior_period: str
    position: MatchPosition
    supplier: str
    released_value: float
    """What last period's shortfall released into this one. ``0.0`` in a
    world's first procurement period, and stated rather than omitted: "nothing
    was outstanding" is a claim the accrual reconciliation needs."""
    released_quantity: int
    accrual_value: float
    ordered_at: datetime
    received_at: datetime
    closed_at: datetime
    keys: dict[str, str] = field(default_factory=dict)
    """Named handles for the facts and events documents and evaluations cite."""


def generate(
    rng: Rng,
    minter: Minter,
    *,
    period: str,
    company_id: str,
    roles: dict[str, str],
    position: MatchPosition,
    category_names: Mapping[str, str],
    lore_by_target: dict[str, list[str]],
    money_unit: str,
    rate_unit: str,
    supplier: str,
    text: Mapping[str, str] | None = None,
    existing_tolerance_pct: CanonicalFact | None = None,
    existing_counterparty: Mapping[str, CanonicalFact] | None = None,
    existing_rates: Mapping[str, CanonicalFact] | None = None,
    existing_vendor_change: CanonicalFact | None = None,
    prior_shortfall_value: CanonicalFact | None = None,
    prior_shortfall_quantity: CanonicalFact | None = None,
    tolerance_pct: float,
    calendar: Calendar = CALENDAR,
    physics: Parameters = DEFAULT,
) -> ProcurementEpisode:
    """Generate the procure-to-pay cycle for the month ending *period*.

    ``position`` is the pre-drawn figure set (``generators.procurement_match``)
    — passed in rather than drawn here, the same separation ``regulatory.py``
    keeps from ``capital.py`` and ``reserving.py`` from ``triangles.py``: this
    function decides *when* a number enters the world and at what authority,
    never what the number is. ``rng`` is accepted and not spent for the same
    reason ``reserving.generate``'s is, and stays on the signature so every
    episode generator is called identically.

    The ``existing_*`` arguments are the standing facts already on the world's
    record, if an earlier month minted them — see the ``existing_minimum``
    comment in ``regulatory.py``, which this mirrors. They are returned in
    ``facts`` whether they were minted here or reused, so this function's own
    handle lookups resolve identically whichever month it is; the caller
    filters the reused ones back out before ``world.extend``, which is
    append-only.

    The two dates the cycle happens on are anchored differently and that is
    deliberate. The *ordering and receiving* happen inside the period, so they
    are counted forward from the end of the month **before** it; the invoice,
    the match and the close happen after it, so they are counted forward from
    the period's own end. Counting the first pair backwards from period end
    would need business-day arithmetic that runs the wrong way and would land
    an order on a Sunday in exactly the jurisdictions ``Calendar`` exists for.
    """
    t = episode_text.merged(TEXT, text)
    events: list[EnterpriseEvent] = []
    facts: list[CanonicalFact] = []
    keys: dict[str, str] = {}

    ends = period_end(period)
    prior_period = previous_periods(period, 1)[0]
    prior_ends = period_end(prior_period)
    bd = lambda n: business_days_after(ends, n, calendar)  # noqa: E731 — read as arithmetic
    within = lambda n: business_days_after(prior_ends, n, calendar)  # noqa: E731

    sourcing, procure = roles["sys_sourcing"], roles["sys_procure"]
    receipting, ap_ledger = roles["sys_receipting"], roles["sys_ap_ledger"]
    gl = roles["sys_general_ledger"]

    rollout_lore = lore_by_target.get("receipting_visibility/subcontract", [])
    doa_lore = lore_by_target.get("exception_approval", [])
    contract_lore = lore_by_target.get("finance/pay_to_contract", [])
    vendor_lore = lore_by_target.get("vendor_master_dual_approval", [])

    def event(kind: str, at: datetime, summary: str, *, actors: list[str] = [],
              systems: list[str] = [], caused_by: list[str] = [],
              lore: list[str] = []) -> EnterpriseEvent:
        made = EnterpriseEvent(id=minter.next("EV"), kind=kind, occurred_at=at,
                               summary=summary, actors=actors, systems=systems,
                               caused_by=caused_by, lore_ids=lore)
        events.append(made)
        keys[f"event_{kind}"] = made.id
        return made

    def fact(kind: str, subject: str, fact_period: str | None, *, at: datetime,
             authority: Authority, event_id: str | None, source: str,
             amount: float | None = None, unit: str = "", text_value: str | None = None,
             until: datetime | None = None, supersedes: str | None = None,
             lore: list[str] | None = None) -> CanonicalFact:
        made = CanonicalFact(
            id=minter.next("FACT"), kind=kind, subject=subject, period=fact_period,
            value=Quantity(amount=amount, unit=unit or money_unit) if amount is not None else None,
            text_value=text_value, valid_from=at, valid_to=until,
            authority=authority, source_system=source, event_id=event_id,
            supersedes=supersedes, lore_ids=lore or [],
        )
        facts.append(made)
        return made

    # -- the order: an approved commitment, not a measurement -----------------
    ordered_at = _at(within(3), 9, 0)
    raised = event(
        "order_raised", ordered_at, t["event.order_raised"],
        actors=[roles["category_manager"]], systems=[procure, sourcing],
    )

    # Standing facts: resolved from the world if an earlier month already
    # minted them, minted here otherwise. `period=None` throughout — a rate
    # card and a counterparty do not belong to a month, and a lookup scoped to
    # one would never find them.
    existing_counterparty = existing_counterparty or {}
    existing_rates = existing_rates or {}
    for line in position.lines:
        name = category_names.get(line.category_id, line.category_id)
        counterparty = existing_counterparty.get(line.category_id)
        if counterparty is None:
            counterparty = CanonicalFact(
                id=minter.next("FACT"), kind="p2p.contract_counterparty",
                subject=line.category_id,
                text_value=t["fact.counterparty"].format(supplier=supplier, category=name),
                valid_from=ordered_at, authority=Authority.APPROVED_REPORT,
                source_system=sourcing, event_id=raised.id,
            )
        facts.append(counterparty)
        keys[f"fact_counterparty_{line.category_id}"] = counterparty.id

        rate = existing_rates.get(line.category_id)
        if rate is None:
            rate = CanonicalFact(
                id=minter.next("FACT"), kind="p2p.contract_rate", subject=line.category_id,
                value=Quantity(amount=line.contract_rate, unit=rate_unit),
                valid_from=ordered_at, authority=Authority.APPROVED_REPORT,
                source_system=sourcing, event_id=raised.id,
            )
        facts.append(rate)
        keys[f"fact_contract_rate_{line.category_id}"] = rate.id

    if existing_tolerance_pct is not None:
        tolerance_policy = existing_tolerance_pct
    else:
        tolerance_policy = CanonicalFact(
            id=minter.next("FACT"), kind="p2p.approval_tolerance_pct", subject=company_id,
            value=Quantity(amount=tolerance_pct, unit=PCT),
            text_value=t["fact.tolerance_policy"],
            valid_from=ordered_at, authority=Authority.SYSTEM_OF_RECORD,
            source_system=gl, event_id=raised.id, lore_ids=doa_lore,
        )
    facts.append(tolerance_policy)
    keys["fact_tolerance_pct"] = tolerance_policy.id

    for line in position.lines:
        keys[f"fact_ordered_quantity_{line.category_id}"] = fact(
            "p2p.ordered_quantity", line.category_id, period, at=ordered_at,
            authority=Authority.APPROVED_REPORT, event_id=raised.id, source=procure,
            amount=line.ordered_quantity, unit=UNITS,
        ).id
        keys[f"fact_ordered_value_{line.category_id}"] = fact(
            "p2p.ordered_value", line.category_id, period, at=ordered_at,
            authority=Authority.APPROVED_REPORT, event_id=raised.id, source=procure,
            amount=line.ordered_value,
        ).id
    keys["fact_ordered_value_total"] = fact(
        "p2p.ordered_value", company_id, period, at=ordered_at,
        authority=Authority.APPROVED_REPORT, event_id=raised.id, source=procure,
        amount=position.ordered_value_total,
    ).id
    # The tolerance *amount* for this order, as against the standing policy
    # percentage above. Two facts because they are two claims — one about how
    # this group delegates, one about what that comes to on this order — and
    # collapsing them would leave the memo quoting a number with no policy
    # behind it or a policy with no number.
    keys["fact_approval_tolerance"] = fact(
        "p2p.approval_tolerance", company_id, period, at=ordered_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=raised.id, source=gl,
        amount=position.approval_tolerance, lore=doa_lore,
    ).id

    # -- the vendor master change: raised once, and still held ----------------
    # Minted only on the world's first procurement period, resolved from the
    # world's own record afterwards — the `existing_*` pattern again. A
    # supplier does not change its remittance details every month, and minting
    # one per period would turn a control finding into wallpaper.
    if existing_vendor_change is not None:
        vendor_change = existing_vendor_change
        facts.append(vendor_change)
    else:
        vendor_requested = event(
            "vendor_change_requested", _at(within(8), 10, 0),
            t["event.vendor_change_requested"],
            actors=[roles["chief_procurement"]], systems=[sourcing], lore=vendor_lore,
        )
        vendor_change = fact(
            "p2p.vendor_change_status", company_id, None,
            at=vendor_requested.occurred_at,
            # The only fact in this corpus below APPROVED_REPORT, and that is the
            # claim: a change nobody has countersigned is not yet a record of
            # anything, whatever the vendor master displays.
            authority=Authority.WORKING_DOCUMENT, event_id=vendor_requested.id,
            source=sourcing, text_value=t["fact.vendor_change_status"], lore=vendor_lore,
        )
    keys["fact_vendor_change_status"] = vendor_change.id

    # -- the receipt: what actually arrived -----------------------------------
    received_at = _at(within(15), 15, 0)
    received = event(
        "goods_received", received_at, t["event.goods_received"],
        actors=[roles["site_receiving_lead"]], systems=[receipting],
        caused_by=[raised.id], lore=rollout_lore,
    )
    for line in position.lines:
        keys[f"fact_received_quantity_{line.category_id}"] = fact(
            "p2p.received_quantity", line.category_id, period, at=received_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=received.id, source=receipting,
            amount=line.received_quantity, unit=UNITS, lore=rollout_lore,
        ).id
        keys[f"fact_received_value_{line.category_id}"] = fact(
            "p2p.received_value", line.category_id, period, at=received_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=received.id, source=receipting,
            amount=line.received_value,
        ).id
    keys["fact_received_value_total"] = fact(
        "p2p.received_value", company_id, period, at=received_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=received.id, source=receipting,
        amount=position.received_value_total,
    ).id

    # Last period's shortfall, arriving. Attached to this period's receipt
    # event because that is what it is — goods turning up — rather than given a
    # ceremony of its own. Minted at zero when there is nothing outstanding,
    # because the accrual reconciliation below adds this term unconditionally
    # and a missing fact would make "nothing was outstanding" indistinguishable
    # from "nobody checked".
    released_value = (
        prior_shortfall_value.value.amount if prior_shortfall_value is not None else 0.0
    )
    released_quantity = int(
        prior_shortfall_quantity.value.amount if prior_shortfall_quantity is not None else 0
    )
    if prior_shortfall_value is not None:
        # Named so the evaluation taxonomy can ask about it. The fact belongs to
        # an earlier month and is *not* re-minted here — the handle points at
        # the earlier month's own id, which is what makes the cross-month
        # temporal question about the same fact a reader would find rather than
        # about a copy of it.
        keys["fact_prior_open_shortfall"] = prior_shortfall_value.id
    keys["fact_shortfall_released_quantity"] = fact(
        "p2p.shortfall_released_quantity", company_id, period, at=received_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=received.id, source=receipting,
        amount=released_quantity, unit=UNITS,
    ).id
    keys["fact_shortfall_released_value"] = fact(
        "p2p.shortfall_released_value", company_id, period, at=received_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=received.id, source=receipting,
        amount=released_value,
    ).id

    # -- the close begins -----------------------------------------------------
    close_start = event(
        "close_started", _at(bd(1), 6, 0),
        t["event.close_started"].format(period=period),
        actors=[roles["financial_controller"]], systems=[gl],
    )
    keys["fact_close_due"] = fact(
        "close.due_date", company_id, period, at=close_start.occurred_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=close_start.id, source=gl,
        text_value=bd(4).isoformat(),
    ).id

    # -- the invoice: immutable from the moment it is posted ------------------
    invoice_at = _at(bd(1), 9, 0)
    invoiced = event(
        "invoice_received", invoice_at, t["event.invoice_received"],
        actors=[roles["accounts_payable_lead"]], systems=[ap_ledger],
        caused_by=[received.id],
    )
    for line in position.lines:
        keys[f"fact_invoiced_quantity_{line.category_id}"] = fact(
            "p2p.invoiced_quantity", line.category_id, period, at=invoice_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=invoiced.id, source=ap_ledger,
            amount=line.invoiced_quantity, unit=UNITS,
        ).id
        keys[f"fact_invoiced_unit_price_{line.category_id}"] = fact(
            "p2p.invoiced_unit_price", line.category_id, period, at=invoice_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=invoiced.id, source=ap_ledger,
            amount=line.invoiced_unit_price, unit=rate_unit,
        ).id
        keys[f"fact_invoiced_value_{line.category_id}"] = fact(
            "p2p.invoiced_value", line.category_id, period, at=invoice_at,
            authority=Authority.SYSTEM_OF_RECORD, event_id=invoiced.id, source=ap_ledger,
            amount=line.invoiced_value,
        ).id
    keys["fact_invoiced_value_total"] = fact(
        "p2p.invoiced_value", company_id, period, at=invoice_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=invoiced.id, source=ap_ledger,
        amount=position.invoiced_value_total,
    ).id

    # -- the match: CONFIRMED, and computed rather than asserted --------------
    match_at = _at(bd(2), 10, 30)
    matched = event(
        "match_run", match_at, t["event.match_run"],
        actors=[roles["accounts_payable_lead"]], systems=[ap_ledger, procure, receipting],
        caused_by=[invoiced.id],
    )
    for line in position.lines:
        keys[f"fact_quantity_variance_{line.category_id}"] = fact(
            "p2p.match_quantity_variance", line.category_id, period, at=match_at,
            authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
            amount=line.quantity_variance,
        ).id
        keys[f"fact_price_variance_{line.category_id}"] = fact(
            "p2p.match_price_variance", line.category_id, period, at=match_at,
            authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
            amount=line.price_variance, lore=contract_lore,
        ).id
        keys[f"fact_total_variance_{line.category_id}"] = fact(
            "p2p.match_total_variance", line.category_id, period, at=match_at,
            authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
            amount=line.total_variance,
        ).id
    keys["fact_quantity_variance_total"] = fact(
        "p2p.match_quantity_variance", company_id, period, at=match_at,
        authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
        amount=position.quantity_variance_total,
    ).id
    keys["fact_price_variance_total"] = fact(
        "p2p.match_price_variance", company_id, period, at=match_at,
        authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
        amount=position.price_variance_total, lore=contract_lore,
    ).id
    keys["fact_total_variance_total"] = fact(
        "p2p.match_total_variance", company_id, period, at=match_at,
        authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
        amount=position.total_variance,
    ).id

    # -- the exception, walking its chain -------------------------------------
    escalated_at = _at(bd(3), 14, 0)
    approved_at = _at(bd(4), 11, 0)
    raised_status = fact(
        "p2p.exception_status", company_id, period, at=match_at,
        authority=Authority.CONFIRMED, event_id=matched.id, source=ap_ledger,
        text_value=t["fact.exception_raised"], until=escalated_at,
    )
    keys["fact_exception_raised"] = raised_status.id

    escalation = event(
        "exception_escalated", escalated_at, t["event.exception_escalated"],
        actors=[roles["accounts_payable_lead"], roles["category_manager"],
                roles["chief_procurement"]],
        systems=[ap_ledger], caused_by=[matched.id], lore=doa_lore,
    )
    escalated_status = fact(
        "p2p.exception_status", company_id, period, at=escalated_at,
        authority=Authority.CONFIRMED, event_id=escalation.id, source=ap_ledger,
        text_value=t["fact.exception_escalated"], until=approved_at,
        supersedes=raised_status.id, lore=doa_lore,
    )
    keys["fact_exception_escalated"] = escalated_status.id

    settled = event(
        "settlement_approved", approved_at, t["event.settlement_approved"],
        actors=[roles["financial_controller"], roles["chief_procurement"]],
        systems=[ap_ledger], caused_by=[escalation.id], lore=contract_lore,
    )
    keys["fact_exception_resolved"] = fact(
        "p2p.exception_status", company_id, period, at=approved_at,
        authority=Authority.CONFIRMED, event_id=settled.id, source=ap_ledger,
        text_value=t["fact.exception_resolved"], supersedes=escalated_status.id,
        lore=contract_lore,
    ).id
    # A fact whose subject is a *person* — the second kind in the project after
    # `org.accountability`, and here for the same reason: without it, "who
    # authorised paying this" is answerable only from an artifact's author
    # field, which is a property of who typed the memo rather than of who
    # carried the delegation. The segregation-of-duties check reads exactly
    # this fact against the order's own author.
    keys["fact_exception_approved_by"] = fact(
        "p2p.exception_approved_by", roles["financial_controller"], period, at=approved_at,
        authority=Authority.APPROVED_REPORT, event_id=settled.id, source=ap_ledger,
        text_value=t["fact.exception_approved_by"].format(period=period), lore=doa_lore,
    ).id
    keys["fact_credit_note_value"] = fact(
        "p2p.credit_note_value", company_id, period, at=approved_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=settled.id, source=ap_ledger,
        amount=position.credit_note_value, lore=contract_lore,
    ).id
    keys["fact_approved_payment_value"] = fact(
        "p2p.approved_payment_value", company_id, period, at=approved_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=settled.id, source=ap_ledger,
        amount=position.approved_payment_value, lore=contract_lore,
    ).id

    # -- the close: where the receipt becomes a ledger figure ------------------
    closed_at = _at(bd(4), 16, 40)
    closed = event(
        "close_finalised", closed_at,
        t["event.close_finalised"].format(period=period),
        actors=[roles["financial_controller"]], systems=[gl],
        caused_by=[close_start.id, settled.id],
    )
    keys["fact_close_status"] = fact(
        "close.status", company_id, period, at=closed_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=closed.id, source=gl,
        text_value="final",
    ).id
    keys["fact_close_delay"] = fact(
        "close.delay", company_id, period, at=closed_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=closed.id, source=gl,
        amount=0, unit="days",
    ).id
    # The composition, in one fact. `financial.` is shared vocabulary — the
    # thin-waist ratchet promoted it when banking reused retail's close — so
    # this sits in the same namespace a month-end variance memo already reads,
    # and a corpus that ran both engines would find it without being told
    # procurement exists.
    accrual_value = round(position.received_value_total + released_value, 2)
    keys["fact_accrual"] = fact(
        "financial.accrual.grni", company_id, period, at=closed_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=closed.id, source=gl,
        amount=accrual_value,
    ).id
    # The undelivered balance at this close: a commitment, not an accrual.
    # Nothing has been received, so nothing is owed for it — which is exactly
    # why it is a separate fact from the accrual above rather than a line
    # inside it, and why the two reconcile to different things.
    keys["fact_open_shortfall_quantity"] = fact(
        "p2p.open_shortfall_quantity", company_id, period, at=closed_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=closed.id, source=procure,
        amount=position.open_shortfall_quantity, unit=UNITS,
    ).id
    keys["fact_open_shortfall_value"] = fact(
        "p2p.open_shortfall_value", company_id, period, at=closed_at,
        authority=Authority.SYSTEM_OF_RECORD, event_id=closed.id, source=procure,
        amount=position.open_shortfall_value,
    ).id

    return ProcurementEpisode(
        events=tuple(events), facts=tuple(facts), period=period,
        prior_period=prior_period, position=position, supplier=supplier,
        released_value=released_value, released_quantity=released_quantity,
        accrual_value=accrual_value,
        ordered_at=ordered_at, received_at=received_at, closed_at=closed_at,
        keys=keys,
    )


__all__ = ["ProcurementEpisode", "TEXT", "_SUPPLIERS", "generate"]
