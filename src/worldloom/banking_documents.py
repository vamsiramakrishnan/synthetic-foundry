"""Banking's documents: what the challenged return warrants, and how it reads.

The banking counterpart of ``generators/planning.py`` plus the banking rows of
``documents.py``'s tables — kept here, in the domain module, and registered
through ``documents.register_artifact_types`` so the core compiler's own tables
stay retail vocabulary (build-order §7a).

Nine artifacts, and the relationships between them are the syllabus:

* the **filed return** and its **restatement** are the same artifact type at
  the same authority, joined by ``restates`` — the AUTHORITY_RANK tie that
  forces resolution through the relationship and the facts' validity, not rank;
* the **working paper** is *revised* to v2 beside them — a working note may be
  revised because it is not a filing, and the two relationships side by side
  are what teach the difference;
* the **challenge memo** is derived from the working paper it disputes — both
  stay standing, which is what a live disagreement looks like on the record;
* the **incident record** and **RCA** reuse retail's types verbatim, so the
  bundle renderer and the shared evaluation machinery apply unchanged;
* the **audit review** and the **board summary** disagree about what to
  mention, and the summary's omission is labelled.
"""

from __future__ import annotations

from datetime import timedelta

from . import documents
from .documents import SectionPlan
from .generators.banking_network import Network
from .generators.regulatory import ReturnEpisode
from .ids import Minter
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Cell,
    Column,
    ErrorType,
    FormulaKind,
    IntentionalError,
    Lifecycle,
    Row,
    Table,
)

MONEY_FORMAT = "#,##0;(#,##0)"
RATIO_FORMAT = "0.00"
COUNT_FORMAT = "#,##0"

#: Who signs each of the nine, by role key (`documents.approver_of`).
#:
#: A prudential return is the most-signed document in this repository's world
#: and was carrying no signature at all, which is the gap the whole approval
#: seam exists to close: "who signed the return the regulator challenged" is
#: the first question anyone asks about this episode.
#:
#: Two absences are load-bearing rather than unfinished. The **working paper**
#: is unsigned because a working paper is unsigned — it is the contested
#: -authority distractor, and giving it a signature would raise its standing
#: against the filed return it is meant to lose to. The **restated return** is
#: covered by the `capital_return` row it shares, which is right: a restatement
#: is signed by whoever signs the thing it restates.
_APPROVED_BY: dict[str, str] = {
    "capital_return": "cfo",
    "second_line_challenge_memo": "cro",
    "incident_rca": "cio",
    # Audit's own review goes to the board committee over the Chief Internal
    # Auditor's signature and nobody else's — which is why the row names the
    # author, and therefore resolves to no countersignature at all
    # (`approver_of` drops a signature that names the author). Written that way
    # rather than omitted, because the omission would read as an oversight and
    # this is an argument: independence is the whole point of the third line,
    # and an audit report countersigned by the management it audits is the one
    # signature that would make this corpus less true rather than more.
    "internal_audit_review": "audit",
    "board_risk_committee_summary": "ceo",
    "meeting_minutes": "cfo",
    # The divisional performance pack is the controller's work and the CFO's
    # number: it is the one document in this episode that reports how the bank
    # traded rather than how it filed, and the CFO answers for that to the
    # executive committee.
    "divisional_performance_pack": "cfo",
}


def artifact_intents(
    minter: Minter,
    *,
    episode: ReturnEpisode,
    roles: dict[str, str],
    network: Network | None = None,
) -> tuple[tuple[ArtifactIntent, ...], tuple[IntentionalError, ...]]:
    """Plan the nine artifacts of one challenged return, and label its lies.

    Order is identity: these mint ``ART`` ids, so a new artifact may only ever
    be appended after the ninth — inserting one would renumber everything a
    checked-in narration cites.

    ``network`` is the quarter's branch-network position
    (``generators/banking_network``), and the twelfth artifact reports it.
    Optional and appended last, for that same ordering rule: a caller that
    passes none plans the eleven records exactly as it did before, which is
    what keeps ``artifact_intents`` usable from a test that has no world.
    """
    k = episode.keys
    book_facts = [
        fact_id for key, fact_id in k.items()
        if key.startswith("fact_book_") and key != "fact_book_corrected"
    ]
    intents: list[ArtifactIntent] = []

    def intent(artifact_type: str, domain: str, audience: str, author: str,
               facts: list[str], events: list[str], size: str, rationale: str,
               *, derived_from: list[str] | None = None, revises: str | None = None,
               restates: str | None = None) -> ArtifactIntent:
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
            revises=revises,
            restates=restates,
        )
        intents.append(made)
        return made

    # 1 — the filed return. Deliberately silent on the open challenge; the
    # omission is registered below, which is what makes it a test case.
    filed_return = intent(
        "capital_return", "finance", "prudential_regulator", roles["reg_reporting_manager"],
        [k["fact_cet1_capital"], k["fact_rwa_filed"], k["fact_ratio_filed"],
         k["fact_ratio_as_filed"], k["fact_filed_at"], k["fact_status_filed"],
         k["fact_return_due"], k["fact_minimum"], *book_facts],
        [k["event_capital_return_filed"]], "long",
        "The quarterly capital return is lodged on the due date. From that instant the "
        "document is immutable: it is the record of what the bank told its regulator.",
    )

    # 2 — the working paper, the contested-authority distractor: it states the
    # fully-secured treatment with a working document's confidence.
    working_paper = intent(
        "rwa_working_paper", "finance", "finance_and_risk", roles["reg_analyst"],
        [k["fact_wp_ratio"], k["fact_wp_rwa"], k["fact_treatment_working"],
         k["fact_close_status"]],
        [k["event_working_paper_issued"]], "medium",
        "The RWA working paper documents the preparer's methodology, including the "
        "collateral treatment the second line will dispute.",
    )

    # 3 — the challenge, on the record. Derived from the paper it disputes:
    # both stay standing, which is precisely what a live contest looks like.
    challenge_memo = intent(
        "second_line_challenge_memo", "risk", "finance_and_risk", roles["prudential_risk_head"],
        [k["fact_challenge"], k["fact_challenge_open"], k["fact_treatment_challenged"],
         k["fact_treatment_working"], k["fact_wp_ratio"]],
        [k["event_challenge_raised"]], "medium",
        "Prudential Risk puts its challenge on the record before lodgement. The memo is "
        "the disagreement register: logged, statused, and — per the filing norm — not "
        "blocking.",
        derived_from=[working_paper.id],
    )

    # 4 — the incident record. Retail's type, verbatim, so the ServiceNow
    # bundle renderer applies unchanged. It carries the wrong FX hypothesis in
    # its densest prose and never mentions the quarterly return.
    incident = intent(
        "servicenow_incident", "operations", "technology_and_risk", roles["svc_incident"],
        [k["fact_break"], k["fact_incident_ref"], k["fact_hypothesis"],
         k["fact_ruled_out"], k["fact_cause"], k["fact_affected"]],
        [k["event_incident_opened"], k["event_root_cause_confirmed"]], "medium",
        "The incident record is the system of record for the operational timeline, "
        "including the hypothesis that was wrong.",
    )

    # 5 — the RCA: the only document that states the shared-upstream structure,
    # which is what makes the cadence join answerable at all.
    rca = intent(
        "incident_rca", "engineering", "technology_and_risk", roles["platform_senior"],
        [k["fact_break"], k["fact_incident_ref"], k["fact_hypothesis"],
         k["fact_ruled_out"], k["fact_cause"], k["fact_affected"],
         k["fact_understatement"], k["fact_delta"], k["fact_materiality"],
         k["fact_ratio_as_filed"]],
        [k["event_root_cause_confirmed"], k["event_capital_impact_assessed"]], "long",
        "A P2 break that invalidated a lodged regulatory return warrants a reviewed RCA, "
        "including why the daily path caught what the quarterly path could not.",
        derived_from=[incident.id],
    )

    # 6 — the restatement. Same artifact type and authority as the filing, so
    # rank ties; `restates` and the facts' validity are the only resolution.
    # Cites BOTH sides of every corrected figure — the banking check group
    # rejects a restatement that does not state the move.
    restatement = intent(
        "capital_return", "finance", "prudential_regulator", roles["reg_reporting_manager"],
        [k["fact_ratio_corrected"], k["fact_rwa_corrected"], k["fact_book_corrected"],
         k["fact_ratio_filed"], k["fact_rwa_filed"], k[f"fact_book_{roles['cat_sme_secured']}"],
         k["fact_ratio_as_filed"], k["fact_cet1_capital"], k["fact_understatement"],
         k["fact_delta"], k["fact_materiality"], k["fact_restatement_reason"],
         k["fact_status_restated"], k["fact_filed_at"], k["fact_minimum"],
         k["fact_notification"], k["fact_cause"],
         *[b for b in book_facts if b != k[f"fact_book_{roles['cat_sme_secured']}"]]],
        [k["event_return_restated"]], "long",
        "The restatement corrects the filed return without touching it: a new lodgement "
        "that states which figures moved, why, and by how much. The original stays on "
        "the record.",
        restates=filed_return.id,
        derived_from=[rca.id],
    )

    # 7 — the working paper, revised. Beside the restatement on purpose: a
    # working note is revised because it is not a filing; a filing is only
    # restated. The two relationships in one episode teach the difference.
    intent(
        "rwa_working_paper", "finance", "finance_and_risk", roles["reg_analyst"],
        [k["fact_cause"], k["fact_understatement"], k["fact_treatment_confirmed"],
         k["fact_materiality"], k["fact_wp_ratio"]],
        [k["event_capital_impact_assessed"]], "medium",
        "Version two of the working paper carries the corrected treatment. The document "
        "keeps its identity; only its content is superseded.",
        revises=working_paper.id,
    )

    # 8 — the third line rules. The only document that names the filing
    # decision plainly: the challenge predated the approval, and was upheld.
    audit_review = intent(
        "internal_audit_review", "risk", "board_risk_committee", roles["audit"],
        [k["fact_challenge"], k["fact_challenge_open"], k["fact_challenge_upheld"],
         k["fact_approval"], k["fact_classification"], k["fact_owner"],
         k["fact_remediation"], k["fact_remediation_scope"], k["fact_cause"],
         k["fact_treatment_confirmed"], k["fact_treatment_challenged"],
         k["fact_filed_at"], k["fact_restatement_reason"]],
        [k["event_control_failure_identified"]], "medium",
        "Internal audit upholds the second-line challenge, classifies the control "
        "failure, and separates the remediation that fixes the control from the one "
        "that only improves detection.",
        derived_from=[rca.id, restatement.id, challenge_memo.id],
    )

    # 9 — the board summary: accurate in every figure, silent on the sequence.
    # The information-asymmetry surface, and the second labelled omission.
    board_summary = intent(
        "board_risk_committee_summary", "strategy", "executive_committee", roles["cro"],
        [k["fact_ratio_corrected"], k["fact_delta"], k["fact_minimum"],
         k["fact_restatement_reason"], k["fact_status_restated"], k["fact_materiality"],
         k["fact_notification"]],
        [k["event_return_restated"]], "small",
        "The board risk committee receives a short summary of the restatement. It omits "
        "the control-failure classification and that the challenge predated the filing.",
        derived_from=[restatement.id, audit_review.id],
    )

    # ------------------------------------------------------------------
    # The fan-out block: appended after the nine artifacts above, never
    # inserted, because tests and any checked-in prose key on their order.
    # ------------------------------------------------------------------

    # 10 — the approval meeting, minuted. The single most eval-dense document
    # the episode can add: the minutes record that the open challenge was
    # tabled and that the decision to file was taken anyway — the exact
    # sequence the filed return omits and the board summary never mentions.
    intent(
        "meeting_minutes", "finance", "finance_and_risk", roles["reg_reporting_manager"],
        [k["fact_challenge"], k["fact_challenge_open"], k["fact_wp_ratio"],
         k["fact_return_due"], k["fact_approval"]],
        [k["event_return_approved"]], "small",
        "The return was approved in a meeting with the challenge on the table; the "
        "minutes are the only document that records both in one place.",
    )

    # 11 — the pre-lodgement thread: working paper issued, challenge raised,
    # approval anyway. Each message knows only what its moment had
    # established, so the thread carries the disagreement as it was lived.
    intent(
        "email_thread", "risk", "finance_and_risk", roles["reg_analyst"],
        [k["fact_wp_ratio"], k["fact_treatment_working"], k["fact_challenge"],
         k["fact_treatment_challenged"], k["fact_challenge_open"], k["fact_approval"]],
        [k["event_working_paper_issued"], k["event_challenge_raised"],
         k["event_return_approved"]], "small",
        "The challenge was argued by email before it was memoed; the thread is the "
        "live disagreement, message by message.",
    )

    # 12 — the divisional performance pack: the only document in this episode
    # that reports the *business* rather than the filing. Before it existed the
    # bank's three divisions, its 133 branches and both its cost centres were
    # named by no fact and carried by no document — a corpus that could be
    # asked what the CET1 ratio was and not which division holds the deposits.
    #
    # A workbook rather than a memo, and for the reason `finance_workbook` is
    # one: the figures reconcile by declared formula, so a reader who
    # recalculates the sheet gets the same answer as the ledger. It plans only
    # when there is an estate to report — see `Network.empty`.
    if network is not None and not network.empty:
        intent(
            "divisional_performance_pack", "finance", "finance_and_risk",
            roles["controller"],
            [fact.id for fact in network.facts],
            [k["event_close_finalised"]], "long",
            "The quarter's divisional and branch-network performance, read from the "
            "locked ledger: deposits, lending, settlements, income and front-line "
            "headcount by division and by branch, and what the shared services cost "
            "the divisions they are recharged to.",
        )

    errors = (
        IntentionalError(
            id=minter.next("ERR"),
            artifact_id=filed_return.id,
            error_type=ErrorType.MATERIAL_OMISSION,
            observed_value=(
                "The return as lodged makes no reference to the open second-line "
                "challenge on the SME Secured collateral treatment"
            ),
            canonical_value="open",
            canonical_fact_id=k["fact_challenge_open"],
            note=(
                "Deliberate: the filing norm files over open challenges, so the wrong "
                "figure is a recorded decision, not an accident. The contested-standing "
                "evaluation family rests on this omission."
            ),
        ),
        IntentionalError(
            id=minter.next("ERR"),
            artifact_id=board_summary.id,
            error_type=ErrorType.MATERIAL_OMISSION,
            observed_value=(
                "The summary reports the restatement without the control-failure "
                "classification and without noting that the challenge predated the filing"
            ),
            canonical_value="control_failure",
            canonical_fact_id=k["fact_classification"],
            note=(
                "Deliberate: establishing what the summary leaves out requires reading "
                "the audit review beside it — absence in one artifact proved against "
                "presence in another."
            ),
        ),
    )

    return tuple(intents), errors


# ---------------------------------------------------------------------------
# The capital return workbook
# ---------------------------------------------------------------------------


def capital_return_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The return as a resolved workbook: components, books, and — when this is
    the restatement — the movement table that states what changed.

    One builder for both lodgements, because they are the same artifact type by
    design; ``intent.restates`` is what distinguishes a correction from an
    original, exactly as it does in the manifest.
    """
    facts: list[CanonicalFact] = [world.facts.by_id(f) for f in intent.required_fact_ids]
    names = world.entity_names()
    company = world.company
    period = next((f.period for f in facts if f.period), world.period or "")

    def cited(kind: str) -> list[CanonicalFact]:
        return sorted((f for f in facts if f.kind == kind), key=lambda f: f.valid_from)

    def latest(kind: str) -> CanonicalFact | None:
        found = cited(kind)
        return found[-1] if found else None

    def earliest(kind: str) -> CanonicalFact | None:
        found = cited(kind)
        return found[0] if found else None

    def amount_cell(fact: CanonicalFact | None) -> Cell:
        if fact is None:
            return Cell(value=None)
        return Cell(value=fact.value.amount if fact.value else fact.text_value,
                    fact_id=fact.id)

    value_column = [Column(key="value", label="Value", number_format=MONEY_FORMAT)]

    capital_fact = latest("capital.cet1_capital")
    rwa_fact = latest("capital.rwa_total")
    ratio_fact = latest("capital.cet1_ratio")
    minimum_fact = latest("capital.minimum_cet1_requirement")
    position = Table(
        key="position",
        title="Capital position",
        columns=value_column,
        rows=[
            Row(key="cet1_capital", label="Common Equity Tier 1 capital",
                cells={"value": amount_cell(capital_fact)}),
            Row(key="rwa_total", label="Total risk-weighted assets",
                cells={"value": amount_cell(rwa_fact)}, emphasis=True),
            Row(key="cet1_ratio", label="CET1 ratio (%)",
                cells={"value": amount_cell(ratio_fact)}, emphasis=True),
            Row(key="minimum", label="PSA 110 minimum CET1 ratio (%)",
                cells={"value": amount_cell(minimum_fact)}),
        ],
        note=(
            f"{company.name} · quarter ended {period} · {company.currency} "
            f"{company.currency_unit}. The ratio states CET1 capital over "
            "risk-weighted assets."
        ),
    )

    # One row per book, the latest cited instance per subject — for the
    # restatement that is the corrected SME figure beside the unchanged books,
    # so the total genuinely sums to the corrected position.
    per_book: dict[str, CanonicalFact] = {}
    for fact in cited("capital.rwa_by_book"):
        per_book[fact.subject] = fact  # later valid_from wins; `cited` sorts
    book_rows = [
        Row(key=subject, label=names.get(subject, subject),
            cells={"value": amount_cell(fact)})
        for subject, fact in sorted(per_book.items())
    ]
    sections = [ArtifactSection(heading="Capital position", table=position)]
    if book_rows:
        total_cell = Cell(
            value=rwa_fact.value.amount if rwa_fact and rwa_fact.value else None,
            fact_id=rwa_fact.id if rwa_fact else None,
            formula=FormulaKind.SUM,
            operands=[row.key for row in book_rows],
        )
        books = Table(
            key="books",
            title="Risk-weighted assets by book",
            columns=value_column,
            rows=[*book_rows,
                  Row(key="total", label="Total", cells={"value": total_cell}, emphasis=True)],
            note="Books sum to the total exactly. The total is the same fact the "
                 "capital position states.",
        )
        sections.append(ArtifactSection(heading="Risk-weighted assets by book", table=books))

    if intent.restates:
        filed_rwa = earliest("capital.rwa_total")
        filed_ratio = earliest("capital.cet1_ratio")
        understatement = latest("capital.rwa_understatement")
        sme_pair = [f for f in cited("capital.rwa_by_book")
                    if len([g for g in cited("capital.rwa_by_book") if g.subject == f.subject]) == 2]
        movement_rows = [
            Row(key="rwa_total", label="Total risk-weighted assets", cells={
                "filed": amount_cell(filed_rwa),
                "restated": amount_cell(rwa_fact),
                "movement": Cell(
                    value=understatement.value.amount if understatement and understatement.value else None,
                    fact_id=understatement.id if understatement else None,
                    formula=FormulaKind.DIFFERENCE, operands=["restated", "filed"],
                ),
            }, emphasis=True),
            Row(key="cet1_ratio", label="CET1 ratio (%)", cells={
                "filed": amount_cell(filed_ratio),
                "restated": amount_cell(ratio_fact),
                "movement": Cell(
                    value=round(
                        (ratio_fact.value.amount - filed_ratio.value.amount), 4
                    ) if ratio_fact and ratio_fact.value and filed_ratio and filed_ratio.value else None,
                    formula=FormulaKind.DIFFERENCE, operands=["restated", "filed"],
                ),
            }, emphasis=True),
        ]
        for subject in sorted({f.subject for f in sme_pair}):
            pair = [f for f in sme_pair if f.subject == subject]
            movement_rows.append(Row(key=subject, label=names.get(subject, subject), cells={
                "filed": amount_cell(pair[0]),
                "restated": amount_cell(pair[-1]),
                "movement": Cell(
                    value=(pair[-1].value.amount - pair[0].value.amount)
                    if pair[0].value and pair[-1].value else None,
                    formula=FormulaKind.DIFFERENCE, operands=["restated", "filed"],
                ),
            }))
        movement = Table(
            key="movement",
            title="Restatement of previously reported figures",
            columns=[
                Column(key="filed", label="As filed", number_format=RATIO_FORMAT),
                Column(key="restated", label="As restated", number_format=RATIO_FORMAT),
                Column(key="movement", label="Movement", number_format=RATIO_FORMAT),
            ],
            rows=movement_rows,
            note=(
                "Only the figures stated here moved. The originally lodged return "
                "remains on the record unchanged; this lodgement corrects it."
            ),
        )
        sections.append(ArtifactSection(heading="Restatement", table=movement))
        sections.append(ArtifactSection(
            heading="Basis of restatement",
            body=None,
            fact_ids=[f.id for f in facts if f.kind in (
                "capital.restatement_reason", "capital.error_materiality",
                "regulatory.notification", "capital.cet1_delta", "ops.cause",
            )],
            purpose=(
                "State why the return is being restated: the confirmed cause, the "
                "materiality conclusion, and that the regulator was notified within "
                "the standard's window. Formal register — this document speaks to "
                "the regulator. Do not editorialise about internal review."
            ),
            semantic_role="decision",
        ))
    else:
        sections.append(ArtifactSection(
            heading="Basis of preparation",
            body=None,
            fact_ids=[f.id for f in facts if f.kind in (
                "capital.return_due_date", "capital.return_filed_at",
                "capital.return_status",
            )],
            purpose=(
                "State the basis: prepared from the locked ledger for the quarter, "
                "lodged via the portal on the due date. Formal register; the return "
                "speaks for the bank and asserts nothing it does not state."
            ),
            semantic_role="evidence",
        ))

    from .narrative import references

    lineage = Table(
        key="supporting_facts",
        title="Supporting facts",
        columns=[
            Column(key="subject", label="Subject"),
            Column(key="statement", label="Statement"),
            Column(key="authority", label="Authority"),
            Column(key="valid_from", label="Valid from"),
        ],
        rows=[
            Row(key=fact.id, label=fact.id, cells={
                "subject": Cell(value=names.get(fact.subject, fact.subject)),
                "statement": Cell(value=references.describe(fact), fact_id=fact.id),
                "authority": Cell(value=fact.authority.value),
                "valid_from": Cell(value=fact.valid_from.isoformat()),
            })
            for fact in facts
        ],
        note="Every value on this return traces to a fact here.",
    )
    sections.append(ArtifactSection(heading="Supporting facts", table=lineage, hidden=True))

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    title = (
        f"{company.name} — Restatement of the Capital Adequacy Return"
        if intent.restates
        else f"{company.name} — Capital Adequacy Return"
    )
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=title,
        subtitle=f"Quarter ended {period} · PSA 110 · {company.currency} {company.currency_unit}",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": period,
            "worldloom_created": documents.written_at(
                intent, {f.id: f for f in facts}
            ).isoformat(),
            "company": company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "note": "Synthetic corpus generated by Worldloom. Not a real company or regulator.",
        },
    )


# ---------------------------------------------------------------------------
# The divisional performance pack
# ---------------------------------------------------------------------------

#: The measures the pack reports, in column order: key, label, the fact kind it
#: reads, and how a spreadsheet spells it. Every one of these **adds up** — a
#: division's deposits are the sum of its branches' — which is what lets a
#: subtotal row declare ``SUM`` over its children rather than paste a figure.
_NETWORK_MEASURES: tuple[tuple[str, str, str, str], ...] = (
    ("deposits", "Deposits", "banking.deposits.balance", MONEY_FORMAT),
    ("lending", "Lending", "banking.lending.balance", MONEY_FORMAT),
    ("settled", "New lending settled", "banking.lending.settled", MONEY_FORMAT),
    ("income", "Net operating income", "banking.net_operating_income", MONEY_FORMAT),
    ("fte", "Front-line FTE", "banking.network.fte", COUNT_FORMAT),
)

#: The rate, held in a separate constant from the measures above rather than
#: carried in the same list behind a boolean. A group loan-to-deposit ratio is
#: group lending over group deposits, never the total of three divisional
#: ratios — the rule ``columns.not_summable`` and ``documents._RATE_KINDS``
#: state for the retail sheet, which this repository has already paid for twice
#: because the two hand-written sets could disagree. Two constants that cannot
#: be confused are cheaper here than one that can.
_NETWORK_RATE: tuple[str, str, str, str] = (
    "loan_to_deposit", "Loan-to-deposit (%)",
    "banking.loan_to_deposit_pct", RATIO_FORMAT,
)


def divisional_performance_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The quarter's business, as a resolved workbook.

    A source artifact rather than a projection of one, exactly as
    ``documents.finance_workbook`` is: every subtotal is declared as a sum of
    the rows above it, so a reader who recalculates the sheet gets the ledger's
    own answer and a renderer with formula support emits the sum rather than
    pasting it.

    The tables follow the organisation rather than a fixed list: a division
    with no branches gets no network table, and the same rule keeps a bank
    whose pack declares no estate from rendering an empty one.
    """
    facts: list[CanonicalFact] = [world.facts.by_id(f) for f in intent.required_fact_ids]
    stated: dict[tuple[str, str], CanonicalFact] = {(f.kind, f.subject): f for f in facts}
    # No `world.entity_names()` here, unlike `capital_return_ir`: every row of
    # this pack is built from the entity itself, so a row is labelled with the
    # branch's own name rather than resolved back out of a fact's subject id.
    company = world.company
    period = next((f.period for f in facts if f.period), world.period or "")

    def cell(kind: str, subject: str, children: list[str] | None = None) -> Cell:
        """One measure for one subject: stated where the ledger states it.

        ``children`` makes the cell a subtotal. The literal value is still the
        ledger's own figure rather than a Python sum of the rows — the two are
        equal by construction (``banking_network`` allocates by largest
        remainder), and stating the fact is what lets the reconciliation check
        compare a declared sum against the fact it claims to be.
        """
        fact = stated.get((kind, subject))
        value = fact.value.amount if fact and fact.value else None
        # No `fact_id` when there is no fact: a cell that names a fact and
        # states nothing is `validate.empty_cell_cites_a_fact`, and a treasury
        # desk genuinely holds no deposits.
        fact_id = fact.id if fact else None
        if children:
            return Cell(value=value, fact_id=fact_id,
                        formula=FormulaKind.SUM, operands=children)
        return Cell(value=value, fact_id=fact_id)

    def measure_row(key: str, label: str, subject: str, *,
                    kinds: tuple[tuple[str, str, str, str], ...],
                    rate: bool = False, children: list[str] | None = None,
                    extra: dict[str, Cell] | None = None,
                    emphasis: bool = False) -> Row:
        cells = {
            column_key: cell(kind, subject, children)
            for column_key, _, kind, _ in kinds
        }
        if rate:
            # Never `children`: see `_NETWORK_RATE`.
            cells[_NETWORK_RATE[0]] = cell(_NETWORK_RATE[2], subject)
        cells.update(extra or {})
        return Row(key=key, label=label, cells=cells, emphasis=emphasis)

    def columns_for(kinds: tuple[tuple[str, str, str, str], ...], *,
                    rate: bool, descriptive: bool = False) -> list[Column]:
        head = (
            [Column(key="region", label="Region"), Column(key="format", label="Format")]
            if descriptive else []
        )
        body = [
            Column(key=key, label=label, number_format=fmt)
            for key, label, _, fmt in kinds
        ]
        tail = (
            [Column(key=_NETWORK_RATE[0], label=_NETWORK_RATE[1],
                    number_format=_NETWORK_RATE[3])]
            if rate else []
        )
        return [*head, *body, *tail]

    measured_kinds = {kind for _, _, kind, _ in _NETWORK_MEASURES}

    def measured(subject: str) -> bool:
        """Whether this subject was booked a quarter at all.

        The rule ``finance_workbook.measured`` states: a unit added after the
        close it is being reported for would otherwise render as a row of empty
        cells inside a subtotal it contributes nothing to.
        """
        return any((kind, subject) in stated for kind in measured_kinds)

    sections: list[ArtifactSection] = []

    # -- divisions, then group ---------------------------------------------
    units = [unit for unit in world.business_units if measured(unit.id)]
    unit_keys = [unit.id for unit in units]
    divisional = Table(
        key="divisions",
        title="Divisional performance",
        columns=columns_for(_NETWORK_MEASURES, rate=True),
        rows=[
            *[measure_row(unit.id, unit.name, unit.id,
                          kinds=_NETWORK_MEASURES, rate=True)
              for unit in units],
            measure_row(company.id, "Group", company.id, kinds=_NETWORK_MEASURES,
                        rate=True, children=unit_keys, emphasis=True),
        ],
        note=(
            f"{company.name} · quarter ended {period} · {company.currency} "
            f"{company.currency_unit}. Divisions sum to group. Loan-to-deposit is a "
            "ratio of the two balances at the level it is stated and does not sum: "
            "a division with no branch network holds no customer balances at all."
        ),
    )
    sections.append(ArtifactSection(heading="Divisional performance", table=divisional))

    # -- one network table per division that has one ------------------------
    for unit in units:
        estate = [
            site for site in world.sites
            if site.business_unit_id == unit.id and measured(site.id)
        ]
        if not estate:
            continue
        site_keys = [site.id for site in estate]
        rows = [
            measure_row(
                site.id, site.name, site.id, kinds=_NETWORK_MEASURES,
                extra={"region": Cell(value=site.region),
                       "format": Cell(value=site.format)},
            )
            for site in estate
        ]
        rows.append(measure_row(
            unit.id, f"{unit.name} total", unit.id, kinds=_NETWORK_MEASURES,
            children=site_keys, emphasis=True,
            extra={"region": Cell(value=None), "format": Cell(value=None)},
        ))
        sections.append(ArtifactSection(
            heading=f"{unit.name} network",
            table=Table(
                key=f"network_{unit.id}",
                title=f"{unit.name} — branch network",
                columns=columns_for(_NETWORK_MEASURES, rate=False, descriptive=True),
                rows=rows,
                note=(
                    "Branches sum to the division exactly. A site that holds work "
                    "rather than customers — an operations centre — carries "
                    "headcount and no balances, which is why its money cells are "
                    "blank rather than zero: a zero would claim it took no deposits, "
                    "and it was never open to any."
                ),
            ),
        ))

    # -- shared services, decomposed twice ----------------------------------
    cost_column = [Column(key="cost", label="Cost", number_format=MONEY_FORMAT)]
    centres = [c for c in world.cost_centres
               if ("banking.shared_services_cost", c.id) in stated]
    if centres:
        centre_keys = [centre.id for centre in centres]
        sections.append(ArtifactSection(
            heading="Shared services by cost centre",
            table=Table(
                key="cost_centres",
                title="Shared services cost base",
                columns=cost_column,
                rows=[
                    *[Row(key=centre.id, label=centre.name,
                          cells={"cost": cell("banking.shared_services_cost", centre.id)})
                      for centre in centres],
                    Row(key=company.id, label="Total shared services", emphasis=True,
                        cells={"cost": cell("banking.shared_services_cost", company.id,
                                            centre_keys)}),
                ],
                note="Where the cost is incurred. The centres sum to the group total.",
            ),
        ))

    recharged = [unit for unit in world.business_units
                 if ("banking.shared_services_recharge", unit.id) in stated]
    if recharged:
        sections.append(ArtifactSection(
            heading="Shared services recharged to divisions",
            table=Table(
                key="recharge",
                title="Shared services recharged",
                columns=[Column(key="recharge", label="Recharge",
                                number_format=MONEY_FORMAT)],
                rows=[
                    *[Row(key=unit.id, label=unit.name,
                          cells={"recharge": cell("banking.shared_services_recharge",
                                                  unit.id)})
                      for unit in recharged],
                    Row(key=company.id, label="Total recharged", emphasis=True,
                        cells={"recharge": cell("banking.shared_services_cost",
                                                company.id,
                                                [u.id for u in recharged])}),
                ],
                note=(
                    "Who carries it, recharged on income share. The same total as the "
                    "cost centres above, decomposed across a different set of "
                    "entities — which is what makes either of them checkable."
                ),
            ),
        ))

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Divisional and Branch Network Performance",
        subtitle=(
            f"Quarter ended {period} · {company.currency} {company.currency_unit}"
        ),
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": period,
            "worldloom_created": documents.written_at(
                intent, {f.id: f for f in facts}
            ).isoformat(),
            "company": company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "note": "Synthetic corpus generated by Worldloom. Not a real company or regulator.",
        },
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# Which format renders what. The return is a workbook — its IR declares the
# formulas — so it belongs to the sheet the way the finance workbook does, and
# markdown must not shadow it with a flat projection. The narrative documents
# are Word (and therefore PDF); markdown keeps rendering those as well, the
# same dual treatment retail's memos get. Import here is safe on a bare
# install: renderer modules import their optional dependency lazily, at render
# time, precisely so registration costs nothing.
from .render import docx as _docx, markdown as _markdown, xlsx as _xlsx

_xlsx.register("capital_return", "divisional_performance_pack")
_markdown.own_elsewhere("capital_return", "divisional_performance_pack")
_docx.register(
    "rwa_working_paper",
    "second_line_challenge_memo",
    "internal_audit_review",
    "board_risk_committee_summary",
)

documents.register_artifact_types(
    standing={
        # Both lodgements of a return sit at SYSTEM_OF_RECORD — the rank tie is
        # the design, so no resolver can shortcut past `restates` and validity.
        "capital_return": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "rwa_working_paper": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT),
        "second_line_challenge_memo": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        "internal_audit_review": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        "board_risk_committee_summary": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        # An approved management report, not a filing: it is read inside the
        # bank, it may be revised, and nothing in `FILING_TYPES` covers it.
        "divisional_performance_pack": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    },
    lags={
        "capital_return": timedelta(minutes=30),
        "rwa_working_paper": timedelta(minutes=90),
        "second_line_challenge_memo": timedelta(hours=3),
        "internal_audit_review": timedelta(hours=4),
        # After the audit review it summarises (and derives from): the summary
        # is written for the committee meeting, not the lodgement day.
        "board_risk_committee_summary": timedelta(days=4),
        # Two days after the ledger locks — a divisional pack is assembled from
        # the close, not on the day of it, and it is out well before the return
        # it sits beside is lodged.
        "divisional_performance_pack": timedelta(days=2),
    },
    outlines={
        "rwa_working_paper": (
            SectionPlan(
                "Methodology and treatment", ("capital.collateral_treatment",), "any",
                "State the treatment applied to each material book, and the basis for "
                "it. Written with a working paper's confidence — this is the document "
                "whose treatment the second line will dispute, and it does not know "
                "that yet.",
            ),
            SectionPlan(
                "Capital position", ("capital.cet1_ratio", "capital.rwa_total"), "any",
                "The computed position as the paper states it. Figures only as "
                "references; the paper argues method, not outcome.",
            ),
            SectionPlan(
                "Correction", ("ops.cause", "capital.rwa_understatement",
                               "capital.error_materiality"), "any",
                "Version two only: what the confirmed cause changed about the "
                "treatment and the position. State it as a correction of this "
                "paper's own earlier method, plainly.",
            ),
            SectionPlan(
                "Basis of preparation", ("close.",), "any",
                "One line: prepared from the locked ledger for the quarter.",
                # Standing boilerplate a reader skips: it restates the basis
                # every working paper in the bank is prepared on. The paper
                # argues method and position, so nothing about its purpose
                # rests on the close facts this section is scoped to — the
                # correction and the position, which do, stay required.
                required=False,
            ),
        ),
        "second_line_challenge_memo": (
            SectionPlan(
                "Finding", ("review.challenge",), "any",
                "The challenge, on the record: what was sampled, what could not be "
                "confirmed, and what the reviewer requires before sign-off. Formal, "
                "insistent, precise — this memo exists to be citable later.",
            ),
            SectionPlan(
                "Treatment under challenge", ("capital.collateral_treatment",), "any",
                "State the preparer's treatment and the reviewer's position beside "
                "each other, without resolving them — the disagreement is the "
                "content.",
            ),
            SectionPlan(
                "Status", ("review.challenge_status",), "any",
                "The challenge's standing under the filing norm: logged, open, not "
                "blocking. State the norm as the memo's author sees it — a "
                "precondition the deadline does not waive.",
            ),
            SectionPlan(
                "Position as drafted", ("capital.cet1_ratio", "capital.rwa_total"), "any",
                "The figures the draft return would file if lodged unaltered.",
                # Context rather than content. The memo exists to put a
                # challenge on the record — Finding, Treatment and Status carry
                # that and stay required — and the drafted position is the
                # working paper's own statement, quoted here for convenience.
                # A challenge memo that cites the paper instead of restating it
                # is the ordinary second-line memo.
                required=False,
            ),
        ),
        "internal_audit_review": (
            SectionPlan(
                "Ruling", ("review.challenge_status", "review.challenge"), "any",
                "The finding first: the second-line challenge is upheld. Audit writes "
                "rulings, not observations.",
            ),
            SectionPlan(
                "The challenge and the filing decision",
                ("capital.return_approval", "capital.return_filed_at"), "any",
                "Establish the sequence on the record: the challenge predated the "
                "approval, and the return was lodged with the challenge open. State "
                "it neutrally; the sequence itself is the finding.",
            ),
            SectionPlan(
                "Root cause and classification",
                ("ops.cause", "ops.root_cause_classification",
                 "ops.collateral_mapping_owner"), "any",
                "The confirmed cause and the control failure beneath it. An "
                "unregistered owner is itself a finding and is stated as one.",
            ),
            SectionPlan(
                "Treatment", ("capital.collateral_treatment",), "any",
                "What the collateral actually was, against what the working paper "
                "assumed.",
                # Evidence for the ruling rather than the ruling. Audit's
                # finding is the sequence and the cause, both required; a
                # review that establishes those and leaves the treatment
                # comparison to the papers it cites is a shorter review, not an
                # incomplete one.
                required=False,
            ),
            SectionPlan(
                "Remediation", ("ops.remediation",), "any",
                "Which action fixes the control and which only improves detection. "
                "A reader must not be able to mistake one for the other.",
            ),
            SectionPlan(
                "Restatement", ("capital.restatement_reason",), "any",
                "The correction as lodged, in one paragraph, for the committee's "
                "record.",
                # What finance then did, not what audit found — the Ruling is
                # the review's result and it is first and required. Audit
                # reviews routinely stop at the remediation and leave the
                # lodgement to the return. Safe under rule 3 as well: the
                # restatement reason is stated in prose by
                # `board_risk_committee_summary` too, so dropping it here
                # cannot take the corpus's only account of the correction.
                required=False,
            ),
        ),
        "board_risk_committee_summary": (
            SectionPlan(
                "Position", ("capital.cet1_ratio", "capital.cet1_delta",
                             "capital.minimum_cet1_requirement"), "group",
                "Three sentences: the restated ratio, the movement, and that the "
                "bank remains above the minimum. Confident register; the committee "
                "wants the outcome.",
            ),
            SectionPlan(
                "Restatement", ("capital.return_status", "capital.restatement_reason",
                                "capital.error_materiality"), "group",
                "What was restated and why, briefly. Write only what the facts "
                "given support — this paper deliberately does not raise the "
                "control-failure classification or the review history.",
            ),
            SectionPlan(
                "Regulator engagement", ("regulatory.notification",), "group",
                "That the regulator was notified within the window. Nothing about "
                "any response — none is recorded.",
            ),
        ),
    },
    compilers={
        "capital_return": capital_return_ir,
        "divisional_performance_pack": divisional_performance_ir,
    },
)
