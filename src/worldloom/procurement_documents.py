"""Procurement's documents: what one purchase cycle warrants, and how it reads.

The procure-to-pay counterpart of ``banking_documents.py`` and
``insurance_documents.py`` — kept here, in the domain module, and registered
through ``documents.register_artifact_types`` so the core compiler's own
tables stay retail vocabulary (build-order §7a).

Seven artifacts, and the relationships between them are the syllabus. The first
six are one purchase cycle's paperwork; the seventh is the company that cycle
happened inside:

* the **purchase order**, the **goods receipt note** and the **supplier
  invoice** are the three-way match, drawn as three documents. Each states
  one quantity and no other document's, which is the property everything else
  here rests on: the order says how many crew-days were committed, the receipt
  says how many arrived, the invoice says how many were billed, and **no
  single document holds two of the three**. A reader who wants to know whether
  they agree has to open all three and then decide which one answers the
  question they were actually asked.

* the **match exception report** states the variances and the tolerance they
  broke, and deliberately does *not* restate the three quantities. It is a
  report of what the match engine concluded, not a re-derivation of it — so it
  cannot be used to shortcut the join above, and the citation question it
  poses ("which facts must this document carry for the escalation to be
  auditable") has a real answer.

* the **payment approval memo** is where the decision and the ledger meet: the
  credit note, what was actually approved for payment, and the month-end
  accrual — which is built from the *receipt*, so this memo and the goods
  receipt note are the two ends of a chain that runs straight past the invoice.

* the **vendor master change** exists once in a corpus, not once a month, and
  is the only document here written under a policy that excludes a function
  the others admit. Operations signs for deliveries and may not see a
  supplier's remittance details; that is the segregation the dual-approval
  norm is about, and an ``AccessPolicy`` that admitted everybody would make
  the access checks decoration.

* the **spend and commitment workbook** is the seventh, and it is the one that
  reports the *company* rather than one order. The six above are the paperwork
  of a single purchase cycle, and a corpus of only those had three business
  units, eighty-one depots and project offices and two cost centres that no
  document mentioned — an estate that was scenery. This is where the divisions,
  the spend categories, the delivery points, the project offices, the materials
  yards and both cost centres carry a figure somebody could argue with, and it
  is a workbook rather than a memo for the reason the retail month-end model is:
  a hundred and forty rows of allocation is a sheet, and prose about it would be
  a paraphrase of a table. Its movement sheet is what stitches a history
  together: this month's opening commitment is last month's closing one, so two
  workbooks from consecutive closes are two pages of one account rather than
  two photographs.
"""

from __future__ import annotations

from datetime import timedelta

from . import documents
from .documents import SectionPlan
from .generators.procurement_cycle import ProcurementEpisode
from .generators.procurement_estate import (
    COMMITMENT,
    MATERIALS,
    OPENING,
    PLACED,
    SPEND,
    EstatePosition,
)
from .ids import Minter
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    Cell,
    Column,
    ErrorType,
    FormulaKind,
    IntentionalError,
    Lifecycle,
    Row,
    Table,
)

MONEY_FORMAT = "#,##0.00;(#,##0.00)"

#: Who signs each document of the purchase cycle, by role key
#: (`documents.approver_of`).
#:
#: Procurement is where a signature is not decoration: a three-way match
#: exception that nobody approved is a payment nobody authorised, and this
#: vertical exists to pose exactly that question. The **exception report** and
#: the **payment approval memo** therefore carry the chief procurement officer's
#: signature and the payables lead's respectively, one level above whoever
#: raised them.
#:
#: The **supplier invoice** has no row and never will: it is the supplier's own
#: claim, posted rather than agreed, and a signature on it would assert the
#: group accepted a document it is in the middle of disputing. "Posted, not
#: agreed — the difference between those two words is the whole of this
#: vertical", as the intent that plans it already says.
_APPROVED_BY: dict[str, str] = {
    "purchase_order": "chief_procurement",
    "goods_receipt_note": "category_manager",
    "match_exception_report": "chief_procurement",
    "payment_approval_memo": "chief_procurement",
    "vendor_master_change": "financial_controller",
    # The one signature in this vertical that leaves Procurement. The workbook
    # states the group's committed position and the accrual behind it, which is
    # a working-capital number: the CPO prepares it and the CFO answers for it.
    # `procurement_org` put those two under different executives on purpose, so
    # this is the same two-reporting-lines argument the three-way match rests
    # on, applied to the position rather than to one order.
    "spend_and_commitment_workbook": "cfo",
}
COUNT_FORMAT = "#,##0"
RATE_FORMAT = "#,##0"


def artifact_intents(
    minter: Minter,
    *,
    episode: ProcurementEpisode,
    estate: EstatePosition,
    roles: dict[str, str],
    mint_vendor_change: bool,
) -> tuple[tuple[ArtifactIntent, ...], tuple[IntentionalError, ...]]:
    """Plan the documents of one purchase cycle, and label its lies.

    Order is identity: these mint ``ART`` ids, so a new artifact may only ever
    be appended after the last — inserting one would renumber everything a
    checked-in narration cites. That is why ``vendor_master_change``, the one
    conditional document, is planned last rather than in the position its
    events happen in: a month that has one and a month that does not must
    agree about the id of every document they share.
    """
    k = episode.keys
    lines = [line.category_id for line in episode.position.lines]
    intents: list[ArtifactIntent] = []

    def intent(artifact_type: str, domain: str, audience: str, author: str,
               facts: list[str], events: list[str], size: str, rationale: str,
               *, derived_from: list[str] | None = None) -> ArtifactIntent:
        made = ArtifactIntent(
            id=minter.next("ART"),
            artifact_type=artifact_type,
            domain=domain,
            audience=audience,
            author_id=author,
            approver_id=documents.approver_of(
                roles, artifact_type, author, _APPROVED_BY
            ),
            triggered_by=events,
            required_fact_ids=facts,
            size_profile=size,  # type: ignore[arg-type]
            rationale=rationale,
            derived_from=derived_from or [],
        )
        intents.append(made)
        return made

    # 1 — the purchase order: what was committed, and at what rate.
    order_facts: list[str] = []
    for cat in lines:
        order_facts += [
            k[f"fact_counterparty_{cat}"], k[f"fact_contract_rate_{cat}"],
            k[f"fact_ordered_quantity_{cat}"], k[f"fact_ordered_value_{cat}"],
        ]
    order_facts += [k["fact_ordered_value_total"], k["fact_approval_tolerance"],
                    k["fact_tolerance_pct"]]
    order = intent(
        "purchase_order", "procurement", "procurement_and_finance",
        roles["category_manager"], order_facts, [k["event_order_raised"]], "medium",
        "The commitment: two lines, the quantity committed on each and the rate the "
        "standing agreement sets. This is the only document in the corpus that states "
        "what the group agreed to pay per unit.",
    )

    # 2 — the goods receipt note: what actually arrived.
    receipt_facts: list[str] = []
    for cat in lines:
        receipt_facts += [
            k[f"fact_received_quantity_{cat}"], k[f"fact_received_value_{cat}"],
            k[f"fact_contract_rate_{cat}"],
        ]
    receipt_facts += [
        k["fact_received_value_total"],
        k["fact_shortfall_released_quantity"], k["fact_shortfall_released_value"],
    ]
    receipt = intent(
        "goods_receipt_note", "operations", "procurement_and_finance",
        roles["site_receiving_lead"], receipt_facts, [k["event_goods_received"]], "medium",
        "What site signed for, at the contracted rate — including the balance of last "
        "month's short delivery, which arrives as an ordinary receipt and not as a "
        "correction of anything. The month-end accrual is built from this document.",
    )

    # 3 — the supplier invoice: what was billed. Immutable from this moment.
    invoice_facts: list[str] = []
    for cat in lines:
        invoice_facts += [
            k[f"fact_invoiced_quantity_{cat}"], k[f"fact_invoiced_unit_price_{cat}"],
            k[f"fact_invoiced_value_{cat}"], k[f"fact_counterparty_{cat}"],
        ]
    invoice_facts.append(k["fact_invoiced_value_total"])
    invoice = intent(
        "supplier_invoice", "finance", "procurement_and_finance",
        roles["accounts_payable_lead"], invoice_facts, [k["event_invoice_received"]], "medium",
        "The supplier's claim, as posted to the payables subledger: quantity billed and "
        "the rate billed at. Posted, not agreed — the difference between those two words "
        "is the whole of this vertical.",
    )

    # 4 — the match exception report: the variances, and nothing to re-derive
    # them from. Cites the escalated status rather than the resolved one: it is
    # written while the exception is still open, and citing the resolution
    # would date it after a decision it exists to ask for.
    exception_facts: list[str] = []
    for cat in lines:
        exception_facts += [
            k[f"fact_quantity_variance_{cat}"], k[f"fact_price_variance_{cat}"],
            k[f"fact_total_variance_{cat}"],
        ]
    exception_facts += [
        k["fact_quantity_variance_total"], k["fact_price_variance_total"],
        k["fact_total_variance_total"], k["fact_approval_tolerance"],
        k["fact_tolerance_pct"], k["fact_exception_raised"], k["fact_exception_escalated"],
    ]
    exception = intent(
        "match_exception_report", "finance", "commercial_review",
        roles["accounts_payable_lead"], exception_facts,
        [k["event_match_run"], k["event_exception_escalated"]], "medium",
        "The match failed and by how much, split into the half that is a quantity billed "
        "and not received and the half that is a rate billed and not agreed — with the "
        "tolerance it broke, which is why this is Finance's decision and not the buyer's.",
        derived_from=[order.id, receipt.id, invoice.id],
    )

    # 5 — the payment approval memo: the decision, and the ledger entry it
    # produces. The one document that carries both the settlement and the
    # accrual, which is what makes the cross-domain question answerable at all.
    memo_facts = [
        k["fact_credit_note_value"], k["fact_approved_payment_value"],
        k["fact_invoiced_value_total"], k["fact_received_value_total"],
        k["fact_total_variance_total"], k["fact_approval_tolerance"],
        k["fact_exception_approved_by"], k["fact_exception_resolved"],
        k["fact_accrual"], k["fact_shortfall_released_value"],
        k["fact_open_shortfall_quantity"], k["fact_open_shortfall_value"],
        k["fact_close_status"],
    ]
    memo = intent(
        "payment_approval_memo", "finance", "commercial_review",
        roles["financial_controller"], memo_facts,
        [k["event_settlement_approved"], k["event_close_finalised"]], "medium",
        "The settlement on the record: what was billed, what was conceded by credit note, "
        "what is actually being paid, and the accrual the close carries — which is built "
        "from the receipt, not from the invoice.",
        derived_from=[exception.id],
    )

    # 6 — the vendor master change, once per corpus. Planned last so a month
    # with one and a month without agree about every other document's id.
    if mint_vendor_change:
        intent(
            "vendor_master_change", "procurement", "vendor_master",
            roles["chief_procurement"],
            [k["fact_vendor_change_status"], *(k[f"fact_counterparty_{cat}"] for cat in lines)],
            [k["event_vendor_change_requested"]], "small",
            "A remittance-detail change requested by the supplier and held for a second "
            "Finance approver. Read under the one policy in this corpus that excludes "
            "Operations, which is the point of the norm it is held under.",
        )

    # 7 — the spend and commitment workbook. Planned after the conditional
    # document rather than before it, which is the rule this function's
    # docstring states read the only way it can be: a new artifact is appended
    # after the last, never inserted, because inserting would renumber the
    # `ART` id of a document somebody has already narrated against.
    #
    # Every estate fact is required and every one of them lands in a cell —
    # `validate.carried_evidence` compares this list against the compiled IR
    # per intent, so a workbook that quietly stopped reporting the yards would
    # be a violation rather than a smaller sheet nobody noticed.
    intent(
        "spend_and_commitment_workbook", "procurement", "procurement_and_finance",
        roles["chief_procurement"], [fact.id for fact in estate.facts],
        [k["event_close_finalised"]], "medium",
        "The group's third-party position at close: what each division bought in, "
        "what it has committed and not yet received, and what is sitting in the "
        "yards — cut by spend category, by delivery point and by the cost centre "
        "the commitment is coded to. The order documents report one cycle; this "
        "reports the company the cycle happened inside.",
    )

    # The canonical figure a labelled imperfection cites has to be the fact's
    # own value in the form `validate.intentional`'s `_quantity_matches`
    # recognises — a descriptive string trips `canonical_mismatch`, and the
    # insurance module's comment records the same lesson from the other side.
    price_variance = next(f for f in episode.facts if f.id == k["fact_price_variance_total"])

    errors = (
        IntentionalError(
            id=minter.next("ERR"),
            artifact_id=memo.id,
            error_type=ErrorType.POLITICAL_UNDERSTATEMENT,
            observed_value=(
                "The memo settles the exception as a credit note against a rate query and "
                "does not state that the rate the supplier billed at was never agreed, nor "
                "that the price half is the larger of the two variances"
            ),
            canonical_value=f"{price_variance.value.amount:g}",
            canonical_fact_id=k["fact_price_variance_total"],
            note=(
                "Deliberate: the memo is Finance's paper and it settles rather than "
                "escalates. The match exception report states the same split plainly, so "
                "the understatement is detectable by reading the document the memo is "
                "derived from. Reuses banking's POLITICAL_UNDERSTATEMENT vocabulary — no "
                "new error kind."
            ),
        ),
    )

    return tuple(intents), errors


# ---------------------------------------------------------------------------
# The three source documents
# ---------------------------------------------------------------------------
#
# Three compilers rather than one parameterised compiler, and that is a
# decision rather than duplication. The three documents differ in exactly the
# way that matters — which quantity each one states — and a single function
# taking a column list would put that difference in a table somewhere else,
# where the next person to read it would have to reconstruct which document
# says what. What they genuinely share (frame the IR, resolve the author,
# stamp the metadata) is `_framed` below, called by all three.


def _by_kind(facts, kind: str):  # type: ignore[no-untyped-def]
    """Facts of *kind*, keyed by subject. One per subject by construction: the
    episode mints exactly one of each per line per period, and the standing
    facts it re-appends carry no period at all."""
    return {f.subject: f for f in facts if f.kind == kind}


def _cell(fact, *, number: bool = True) -> Cell:  # type: ignore[no-untyped-def]
    if fact is None:
        return Cell(value=None)
    if number and fact.value is not None:
        return Cell(value=fact.value.amount, fact_id=fact.id)
    return Cell(value=fact.text_value if fact.value is None else fact.value.amount,
                fact_id=fact.id)


def _line_rows(world, facts, columns: dict[str, str]):  # type: ignore[no-untyped-def]
    """One row per spend category among *facts*, in category-id order.

    Ordered by id rather than by which line is the contested one, for the
    reason ``procurement_match.generate`` orders its lines that way: a document
    whose row order announced which line is interesting would hand a reader
    the answer to the question the corpus is asking.
    """
    category_names = {c.id: c.name for c in world.categories}
    resolved = {kind: _by_kind(facts, kind) for kind in columns.values()}
    subjects = sorted({
        f.subject for f in facts
        if f.subject in category_names and f.kind in set(columns.values())
    })
    return [
        Row(key=subject, label=category_names[subject], cells={
            key: _cell(resolved[kind].get(subject)) for key, kind in columns.items()
        })
        for subject in subjects
    ]


def _counterparty_table(world, facts):  # type: ignore[no-untyped-def]
    """Who each line is with, cited rather than only printed.

    `_supplier_of` reads the counterparty out of the same fact and puts it in
    the document's subtitle, which reads correctly and cites nothing: a subtitle
    is not a section, so `ArtifactIR.fact_ids()` never sees it. The order and
    the invoice both *required* `p2p.contract_counterparty` and both carried it
    nowhere — two facts a document was handed and did not hold, in a corpus
    reporting clean, which is the finance-workbook shape once more. Surfaced by
    `validate.carried_evidence` asking the question per intent rather than over
    the union of every document, where the vendor-master change already held it.

    A table rather than a column on the money tables: the counterparty is one
    repeated string per line and putting it beside the rates would crowd out the
    comparison those tables exist for.
    """
    names = {c.id: c.name for c in world.categories}
    resolved = _by_kind(facts, "p2p.contract_counterparty")
    rows = [
        Row(key=subject, label=names[subject],
            cells={"counterparty": _cell(resolved[subject], number=False)})
        for subject in sorted(resolved)
        if subject in names
    ]
    if not rows:
        return None
    return Table(
        key="counterparty", title="Contracted with",
        columns=[Column(key="counterparty", label="Counterparty and contractual basis")],
        rows=rows,
        note="One line, one contract. Read the rates on this document against this basis.",
    )


def _contract_section(world, facts):  # type: ignore[no-untyped-def]
    """The counterparty table wrapped as a section, or nothing at all.

    Spread into the section list so a document whose facts name no counterparty
    gets no empty heading — an absent section is honest, an empty one is not.
    """
    table = _counterparty_table(world, facts)
    return [ArtifactSection(heading="Contracted with", table=table)] if table else []


def _framed(world, intent: ArtifactIntent, facts, title: str, subtitle: str,  # type: ignore[no-untyped-def]
            sections: list[ArtifactSection]) -> ArtifactIR:
    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=title,
        subtitle=subtitle,
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": world.period or "",
            "worldloom_created": documents.written_at(
                intent, {f.id: f for f in facts}
            ).isoformat(),
            "company": world.company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "note": "Synthetic corpus generated by Worldloom. Not a real company or supplier.",
        },
    )


def purchase_order_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The order: committed quantity and contracted rate, line by line."""
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company

    order = Table(
        key="order_lines", title="Order lines",
        columns=[
            Column(key="rate", label=f"Contracted rate ({company.currency}/unit)",
                   number_format=RATE_FORMAT),
            Column(key="quantity", label="Quantity ordered", number_format=COUNT_FORMAT),
            Column(key="value", label=f"Committed value ({company.currency} "
                                      f"{company.currency_unit})",
                   number_format=MONEY_FORMAT),
        ],
        rows=_line_rows(world, facts, {
            "rate": "p2p.contract_rate",
            "quantity": "p2p.ordered_quantity",
            "value": "p2p.ordered_value",
        }),
        note=(
            "Rates are the standing agreement's, not this order's: they are agreed once "
            "and hold across orders, which is why they carry no period. This document is "
            "the only place in the corpus that states what the group agreed to pay."
        ),
    )

    totals = _by_kind(facts, "p2p.ordered_value")
    tolerance = _by_kind(facts, "p2p.approval_tolerance").get(company.id)
    tolerance_pct = _by_kind(facts, "p2p.approval_tolerance_pct").get(company.id)
    commitment = Table(
        key="commitment", title="Commitment and delegated authority",
        columns=[Column(key="amount", label="Amount", number_format=MONEY_FORMAT)],
        rows=[
            Row(key="committed", label="Total committed value",
                cells={"amount": _cell(totals.get(company.id))}, emphasis=True),
            Row(key="tolerance", label="Match variance a buyer may clear",
                cells={"amount": _cell(tolerance)}),
            Row(key="tolerance_pct", label="Delegated authority (per cent of committed value)",
                cells={"amount": _cell(tolerance_pct)}),
        ],
        note=(
            "Above the stated tolerance the exception leaves the buyer and goes to "
            "Finance, and the person who raised this order may not clear it."
        ),
    )

    return _framed(
        world, intent, facts,
        f"{company.name} — Purchase Order",
        f"{_supplier_of(facts)} · {company.currency} {company.currency_unit}",
        [
            ArtifactSection(heading="Order lines", table=order),
            *_contract_section(world, facts),
            ArtifactSection(heading="Commitment and delegated authority", table=commitment),
        ],
    )


def goods_receipt_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The receipt: what arrived, valued at the contracted rate and nothing else.

    The ordered quantity is deliberately absent. Site receipting since the
    handheld rollout records what was physically signed for; a receipt that
    also restated the order would let a reader answer "did we get what we
    ordered" from one document, which is exactly the join this corpus exists
    to make somebody perform.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company

    received = Table(
        key="received", title="Received at site",
        columns=[
            Column(key="quantity", label="Quantity received", number_format=COUNT_FORMAT),
            Column(key="rate", label=f"Contracted rate ({company.currency}/unit)",
                   number_format=RATE_FORMAT),
            Column(key="value", label=f"Value at contracted rate ({company.currency} "
                                      f"{company.currency_unit})",
                   number_format=MONEY_FORMAT),
        ],
        rows=_line_rows(world, facts, {
            "quantity": "p2p.received_quantity",
            "rate": "p2p.contract_rate",
            "value": "p2p.received_value",
        }),
        note=(
            "Quantities are what was signed for at the gate. Values are those quantities "
            "at the contracted rate — the receipting system has never seen an invoice and "
            "cannot price anything any other way."
        ),
    )

    totals = _by_kind(facts, "p2p.received_value").get(company.id)
    released_qty = _by_kind(facts, "p2p.shortfall_released_quantity").get(company.id)
    released_value = _by_kind(facts, "p2p.shortfall_released_value").get(company.id)
    carried = Table(
        key="carried", title="Against earlier orders",
        columns=[Column(key="amount", label="Amount", number_format=MONEY_FORMAT)],
        rows=[
            Row(key="released_quantity", label="Quantity received against a prior short delivery",
                cells={"amount": _cell(released_qty)}),
            Row(key="released_value", label="Value of that receipt at the contracted rate",
                cells={"amount": _cell(released_value)}),
            Row(key="total", label="Total received this period, at contracted rates",
                cells={"amount": _cell(totals)}, emphasis=True),
        ],
        note=(
            "A balance delivered late arrives as an ordinary receipt, not as a correction: "
            "nothing about the earlier receipt was wrong, and the goods simply were not "
            "there yet. Zero here means nothing was outstanding, which is a statement "
            "rather than an absence."
        ),
    )

    return _framed(
        world, intent, facts,
        f"{company.name} — Goods Receipt Note",
        f"Site receipting · {company.currency} {company.currency_unit}",
        [
            ArtifactSection(heading="Received at site", table=received),
            ArtifactSection(heading="Against earlier orders", table=carried),
        ],
    )


def supplier_invoice_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The invoice, as posted: quantity billed and the rate billed at.

    Nothing here is marked as disputed, and that is the document behaving
    correctly rather than the corpus being coy. An invoice is a third party's
    claim; the match runs afterwards, in a different system, and this document
    never learns its outcome.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company

    billed = Table(
        key="billed", title="Invoice lines",
        columns=[
            Column(key="quantity", label="Quantity invoiced", number_format=COUNT_FORMAT),
            Column(key="price", label=f"Unit price invoiced ({company.currency}/unit)",
                   number_format=RATE_FORMAT),
            Column(key="value", label=f"Invoiced value ({company.currency} "
                                      f"{company.currency_unit})",
                   number_format=MONEY_FORMAT),
        ],
        rows=_line_rows(world, facts, {
            "quantity": "p2p.invoiced_quantity",
            "price": "p2p.invoiced_unit_price",
            "value": "p2p.invoiced_value",
        }),
        note=(
            "As posted to the payables subledger. The unit price here is the supplier's, "
            "and it is not the rate the purchase order states — reading this column as "
            "what the group owes per unit is the single most available mistake in this "
            "corpus."
        ),
    )

    total = Table(
        key="invoice_total", title="Invoice total",
        columns=[Column(key="amount", label="Amount", number_format=MONEY_FORMAT)],
        rows=[Row(key="total", label="Total invoiced",
                  cells={"amount": _cell(_by_kind(facts, "p2p.invoiced_value").get(company.id))},
                  emphasis=True)],
        note="What the supplier has claimed. What is paid is decided elsewhere.",
    )

    return _framed(
        world, intent, facts,
        f"{company.name} — Supplier Invoice",
        f"{_supplier_of(facts)} · as posted · {company.currency} {company.currency_unit}",
        [
            ArtifactSection(heading="Invoice lines", table=billed),
            *_contract_section(world, facts),
            ArtifactSection(heading="Invoice total", table=total),
        ],
    )


def _supplier_of(facts) -> str:  # type: ignore[no-untyped-def]
    """The counterparty, from the standing fact rather than from a parameter.

    The supplier is not an entity in this model — see ``worldloom.procurement``
    on why, and what it would take for it to become one — so its name lives in
    a fact's ``text_value`` and every document that wants to print it reads it
    back from there. One source, so two documents cannot disagree about who
    the order is with.
    """
    named = [f for f in facts if f.kind == "p2p.contract_counterparty" and f.text_value]
    return named[0].text_value if named else ""


# ---------------------------------------------------------------------------
# The workbook: the company the cycle happened inside
# ---------------------------------------------------------------------------


def _figure(resolved, subject: str, children: list[str] | None = None) -> Cell:  # type: ignore[no-untyped-def]
    """One money cell, stated where the ledger states it and summed where it totals.

    A subject the ledger has no figure for gets an empty cell carrying **no**
    ``fact_id``: a project office takes no delivery and a materials yard buys
    nothing in, so those cells are blank by construction rather than by
    omission. The distinction is checked — ``validate.carried_evidence`` fails a
    cell that names a fact and states nothing, which is the signature of the
    workbook defect this repository has already paid for twice.
    """
    fact = resolved.get(subject)
    if fact is None or fact.value is None:
        return Cell(value=None)
    if children:
        return Cell(value=fact.value.amount, fact_id=fact.id,
                    formula=FormulaKind.SUM, operands=children)
    return Cell(value=fact.value.amount, fact_id=fact.id)


def _present(resolved, keys: list[str]) -> list[str]:  # type: ignore[no-untyped-def]
    """Of *keys*, the ones the ledger actually states — a subtotal's operands.

    Per column rather than per row, because the estate's three measures have
    three different populations: a unit's spend total sums its delivery points,
    its commitment sums those *and* its project offices, and its materials sum
    its yards. One operand list for the whole row would have made every subtotal
    sum the whole estate and counted every blank cell as a zero somebody agreed
    to.
    """
    return [key for key in keys if key in resolved]


def spend_and_commitment_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The group's third-party position: divisions, categories, estate, cost centres.

    Five tables, and each one is a decomposition of a figure stated above it
    rather than an independent count. That is what makes the workbook checkable
    against itself: delete a depot's row and the divisional total moves, because
    the total is a formula over the rows and not a number pasted beside them.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company
    money = f"{company.currency} {company.currency_unit}"
    spend = _by_kind(facts, SPEND)
    commitment = _by_kind(facts, COMMITMENT)
    materials = _by_kind(facts, MATERIALS)

    def column(key: str, label: str) -> Column:
        return Column(key=key, label=f"{label} ({money})", number_format=MONEY_FORMAT)

    spend_column = column("spend", "Third-party spend")
    commitment_column = column("commitment", "Open commitment")
    materials_column = column("materials", "Materials on hand")

    units = [unit for unit in world.business_units if unit.id in spend or unit.id in commitment]
    unit_keys = [unit.id for unit in units]

    # A company with no materials yard anywhere states no holding at all, so
    # the column and its row come off the sheet rather than printing blank.
    # `_contract_section` above makes the same call for the same reason: an
    # absent section is honest and an empty one is not.
    money_columns = [spend_column, commitment_column]
    if materials:
        money_columns.append(materials_column)

    # -- the position ------------------------------------------------------
    def headline(key: str, label: str, resolved) -> Row:  # type: ignore[no-untyped-def]
        cell = _figure(resolved, company.id)
        return Row(key=key, label=label, cells={"amount": Cell(
            value=cell.value, fact_id=cell.fact_id,
            formula=FormulaKind.REFERENCE, operands=[f"division:{company.id}:{key}"],
        )})

    position_rows = [
        headline("spend", "Third-party spend received in the period", spend),
        headline("commitment", "Purchase-order commitment open at close", commitment),
    ]
    if materials:
        position_rows.append(
            headline("materials", "Materials held in the yards", materials)
        )
    position = Table(
        key="position", title="Procurement position",
        columns=[Column(key="amount", label="Amount", number_format=MONEY_FORMAT)],
        rows=position_rows,
        note=(
            f"{company.name} · {world.period or ''} · {money}. Spend is a flow and the "
            "other two are balances: the first is what arrived this month, the second is "
            "what has been ordered and not yet arrived, and the third is what arrived "
            "earlier and has not yet been used."
        ),
    )

    # -- the commitment movement -------------------------------------------
    # The reading a contractor's cost report opens with, and the sheet that
    # makes a history causally continuous on the page: this month's opening
    # line is last month's closing line, and a reader with two workbooks open
    # can see the balance carry. No formula cell — the identity mixes signs
    # across *rows*, which neither SUM (rows, one sign) nor DIFFERENCE
    # (columns) declares — so the closing is a plain cited figure and the
    # arithmetic is held by the procurement check group's stockflow clause
    # rather than asserted twice in two grammars.
    opening_by = _by_kind(facts, OPENING)
    placed_by = _by_kind(facts, PLACED)
    movement = Table(
        key="movement", title="Commitment movement",
        columns=[Column(key="amount", label=f"Amount ({money})",
                        number_format=MONEY_FORMAT)],
        rows=[
            Row(key="opening", label="Open commitment brought forward",
                cells={"amount": _figure(opening_by, company.id)}),
            Row(key="placed", label="Orders placed in the period",
                cells={"amount": _figure(placed_by, company.id)}),
            Row(key="received", label="Receipts against orders in the period",
                cells={"amount": _figure(spend, company.id)}),
            Row(key="closing", label="Open commitment carried forward", emphasis=True,
                cells={"amount": _figure(commitment, company.id)}),
        ],
        note=(
            "Closing is opening plus placed less received, to the unit. Receipts "
            "against orders are the period's third-party spend — the same figure the "
            "position above reports, because a receipt is the event that turns "
            "commitment into spend — and the opening balance is the closing balance "
            "of the previous close's workbook."
        ),
    )

    # -- by division -------------------------------------------------------
    division_rows = [
        Row(key=unit.id, label=unit.name, cells={
            "spend": _figure(spend, unit.id),
            "commitment": _figure(commitment, unit.id),
            "materials": _figure(materials, unit.id),
        })
        for unit in units
    ]
    division_rows.append(Row(key=company.id, label="Group", emphasis=True, cells={
        "spend": _figure(spend, company.id, _present(spend, unit_keys)),
        "commitment": _figure(commitment, company.id, _present(commitment, unit_keys)),
        "materials": _figure(materials, company.id, _present(materials, unit_keys)),
    }))
    division = Table(
        key="division", title="By division",
        columns=money_columns,
        rows=division_rows,
        note=(
            "Group is the sum of the divisions above, in every column. A division with "
            "no materials row has no yard to hold anything in — which is a different "
            "statement from holding nothing, and is why the cell is blank rather than "
            "zero."
        ),
    )

    # -- by spend category -------------------------------------------------
    category_rows: list[Row] = []
    category_subtotals: list[str] = []
    for unit in units:
        members = [
            category for category in world.categories
            if category.business_unit_id == unit.id and category.id in spend
        ]
        if not members:
            continue
        for category in members:
            category_rows.append(Row(
                key=category.id, label=f"{unit.name} · {category.name}",
                cells={"spend": _figure(spend, category.id)},
            ))
        category_rows.append(Row(
            key=unit.id, label=f"{unit.name} total", emphasis=True,
            cells={"spend": _figure(spend, unit.id, [c.id for c in members])},
        ))
        category_subtotals.append(unit.id)
    category_rows.append(Row(
        key=company.id, label="Group", emphasis=True,
        cells={"spend": _figure(spend, company.id, category_subtotals)},
    ))
    category = Table(
        key="category", title="By spend category",
        columns=[spend_column],
        rows=category_rows,
        note=(
            "The same divisional figures the estate sheet decomposes, cut the other "
            "way. Two decompositions that both reconcile to the division are a "
            "cross-check; two that were drawn independently would be two "
            "contradictions."
        ),
    )

    # -- the estate --------------------------------------------------------
    estate_rows: list[Row] = []
    estate_subtotals: list[str] = []
    for unit in units:
        places = [site for site in world.sites if site.business_unit_id == unit.id]
        if not places:
            continue
        for site in places:
            estate_rows.append(Row(key=site.id, label=site.name, cells={
                "region": Cell(value=site.region),
                "format": Cell(value=site.format),
                "spend": _figure(spend, site.id),
                "commitment": _figure(commitment, site.id),
                "materials": _figure(materials, site.id),
            }))
        keys = [site.id for site in places]
        estate_rows.append(Row(
            key=unit.id, label=f"{unit.name} total", emphasis=True, cells={
                "region": Cell(value=""), "format": Cell(value=""),
                "spend": _figure(spend, unit.id, _present(spend, keys)),
                "commitment": _figure(commitment, unit.id, _present(commitment, keys)),
                "materials": _figure(materials, unit.id, _present(materials, keys)),
            },
        ))
        estate_subtotals.append(unit.id)
    estate_rows.append(Row(key=company.id, label="Group", emphasis=True, cells={
        "region": Cell(value=""), "format": Cell(value=""),
        "spend": _figure(spend, company.id, _present(spend, estate_subtotals)),
        "commitment": _figure(commitment, company.id, _present(commitment, estate_subtotals)),
        "materials": _figure(materials, company.id, _present(materials, estate_subtotals)),
    }))
    estate = Table(
        # Thirty-one characters is a worksheet name's limit and the renderer
        # truncates rather than refusing, so a longer title would have shipped a
        # tab reading "By depot, project office and ya". The section heading
        # below says it in full.
        key="estate", title="By depot, office and yard",
        columns=[
            Column(key="region", label="Region"),
            Column(key="format", label="Format"),
            *money_columns,
        ],
        rows=estate_rows,
        note=(
            "Three kinds of place and three different measures. A depot takes delivery, "
            "so it carries spend and the order book behind it. A project office raises "
            "commitment and has no gate, so its spend cell is empty. A materials yard "
            "buys nothing in and holds what was bought — which is why the archetype "
            "gives it no revenue weight at all."
        ),
    )

    # -- by cost centre ----------------------------------------------------
    centres = [centre for centre in world.cost_centres if centre.id in commitment]
    centre_rows = [
        Row(key=centre.id, label=centre.name,
            cells={"commitment": _figure(commitment, centre.id)})
        for centre in centres
    ]
    centre_rows.append(Row(key=company.id, label="Group", emphasis=True, cells={
        "commitment": _figure(commitment, company.id, [centre.id for centre in centres]),
    }))
    cost_centre = Table(
        key="cost_centre", title="Commitment by cost centre",
        columns=[commitment_column],
        rows=centre_rows,
        note=(
            "Where the commitment is coded, which is not where it is managed: the "
            "estate sheet says which depot ordered it and this says which centre wears "
            "it. A delegation of authority that cannot separate direct project spend "
            "from corporate services is one nobody can review."
        ),
    )

    # A cut with nothing under it gets no heading at all. A pack that declares
    # no estate, or no spend categories, would otherwise file a workbook whose
    # sheets are one "Group" row apiece — a document that says nothing while
    # looking like it says something, which is the shape every check in this
    # repository's `carried_evidence` family exists to refuse.
    sections = [
        ArtifactSection(heading="Procurement position", table=position),
        ArtifactSection(heading="Commitment movement", table=movement),
        ArtifactSection(heading="By division", table=division),
    ]
    if category_subtotals:
        sections.append(ArtifactSection(heading="By spend category", table=category))
    if estate_subtotals:
        sections.append(
            ArtifactSection(heading="By depot, project office and yard", table=estate)
        )
    if centres:
        sections.append(ArtifactSection(heading="Commitment by cost centre", table=cost_centre))

    return _framed(
        world, intent, facts,
        f"{company.name} — Spend and Commitment Workbook",
        f"Third-party position at close · {money}",
        sections,
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from .render import docx as _docx, markdown as _markdown, xlsx as _xlsx  # noqa: E402

_xlsx.register("purchase_order", "goods_receipt_note", "supplier_invoice",
               "spend_and_commitment_workbook")
_markdown.own_elsewhere("purchase_order", "goods_receipt_note", "supplier_invoice",
                        "spend_and_commitment_workbook")
_docx.register(
    "match_exception_report",
    "payment_approval_memo",
    "vendor_master_change",
)

documents.register_artifact_types(
    standing={
        # The three source documents, and the three different claims their
        # authorities make. The order is an APPROVED_REPORT because it is an
        # agreement somebody signed, not a measurement of anything; the receipt
        # and the invoice are each SYSTEM_OF_RECORD *for their own system* —
        # what arrived, and what was billed — which is exactly why rank cannot
        # arbitrate between them.
        "purchase_order": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        "goods_receipt_note": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "supplier_invoice": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "match_exception_report": (Authority.APPROVED_REPORT, Lifecycle.REVIEWED),
        "payment_approval_memo": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        # The one document below approved standing, matching the one fact below
        # it: a change nobody has countersigned is a draft, whatever the vendor
        # master screen shows.
        "vendor_master_change": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT),
        # A workbook off the order book, the receipting system and the ledger,
        # published at close — the same standing the retail month-end model has,
        # and for the same reason: it restates no third party's claim, it
        # reports what three systems of record hold.
        "spend_and_commitment_workbook": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
    },
    lags={
        "purchase_order": timedelta(hours=1),
        "goods_receipt_note": timedelta(hours=1),
        "supplier_invoice": timedelta(hours=2),
        "match_exception_report": timedelta(hours=4),
        "payment_approval_memo": timedelta(days=1),
        "vendor_master_change": timedelta(hours=3),
        # Longer than any of the six above: the position is assembled after the
        # ledger locks, not while the cycle is running.
        "spend_and_commitment_workbook": timedelta(days=1, hours=6),
    },
    outlines={
        "match_exception_report": (
            SectionPlan(
                "The exception", ("p2p.match_total_variance", "p2p.approval_tolerance"), "group",
                "State the total variance and the tolerance it broke, in that order. This "
                "is the paragraph that decides whether anyone senior reads the rest; it "
                "must say plainly that the buyer can no longer clear this.",
            ),
            SectionPlan(
                "Where the variance sits",
                ("p2p.match_quantity_variance", "p2p.match_price_variance"), "any",
                "Split the variance two ways — billed for what did not arrive, and billed "
                "at a rate that was not agreed — and say which line each sits on. Do not "
                "give the clean line a paragraph; a line that matched warrants a clause.",
            ),
            SectionPlan(
                "Status and what is needed", ("p2p.exception_status",), "group",
                "Where the exception stands and what has to happen for it to move. Written "
                "while it is still open, so it asks for a decision rather than reporting "
                "one.",
            ),
        ),
        "payment_approval_memo": (
            SectionPlan(
                "The settlement",
                ("p2p.approved_payment_value", "p2p.credit_note_value", "p2p.invoiced_value"),
                "group",
                "What was billed, what the supplier conceded, and what is actually being "
                "paid. Lead with the figure being approved, not with the one on the "
                "invoice.",
            ),
            SectionPlan(
                "Authority for the decision",
                ("p2p.exception_approved_by", "p2p.approval_tolerance",
                 "p2p.match_total_variance"), "any",
                "Who approved this and under what delegation. State that the variance "
                "exceeded the tolerance and that this is therefore Finance's decision — "
                "the memo is the record that the approval chain was followed, and a memo "
                "that leaves the approver implicit is not that record.",
            ),
            SectionPlan(
                "What the close carries",
                ("financial.accrual.grni", "p2p.received_value", "close."), "group",
                "The accrual posted at close, and — plainly, rather than left to a "
                "reader's inference — that it is built from what was received at the "
                "contracted rate, not from what was invoiced. This is the sentence that "
                "connects a site receipting note to the general ledger.",
            ),
            SectionPlan(
                "Still outstanding",
                ("p2p.open_shortfall_quantity", "p2p.open_shortfall_value"), "group",
                "The undelivered balance carried into next month, and that it is a "
                "commitment rather than an accrual — nothing has been received, so nothing "
                "is owed for it yet. One short paragraph.",
                # A "still outstanding" where nothing is. A settlement that
                # closed the order out has no balance to carry, and the memo
                # ends on the approval — which is where a memo about an
                # approval should end. The three sections that make it the
                # record of a decision (settlement, authority, what the close
                # carries) stay required.
                required=False,
            ),
        ),
        "vendor_master_change": (
            SectionPlan(
                "The requested change", ("p2p.vendor_change_status",), "group",
                "What the supplier asked for and why it is being held. State the second "
                "approver is outstanding without naming a date it will be resolved by — "
                "there is not one.",
            ),
            SectionPlan(
                "Counterparty", ("p2p.contract_counterparty",), "any",
                "Which agreement this supplier is engaged under. One or two sentences; "
                "this section exists so the change can be tied to a contract, not to "
                "restate the contract.",
            ),
        ),
    },
    compilers={
        "purchase_order": purchase_order_ir,
        "goods_receipt_note": goods_receipt_ir,
        "supplier_invoice": supplier_invoice_ir,
        "spend_and_commitment_workbook": spend_and_commitment_ir,
    },
)
