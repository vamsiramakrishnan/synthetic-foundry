"""Insurance's documents: what one valuation warrants, and how it reads.

The insurance counterpart of ``banking_documents.py`` — kept here, in the
domain module, and registered through ``documents.register_artifact_types``
so the core compiler's own tables stay retail vocabulary (build-order §7a).

Four artifacts, increment 1's scope, and the relationships between them are
the syllabus:

* the **triangle workbook** is the corpus's one honest picture of the book:
  every cohort at both valuations, paid and incurred, and a future-
  development row that is *structurally* blank — not omitted, not
  estimated, blank — because the tail past this valuation is unobserved by
  construction, the same way IBNR is unobservable in principle.
* the **emergence note** is the low-authority document that happens to be
  right: a WORKING_DOCUMENT stating the actual-versus-expected deviation the
  strengthening below is a direct response to.
* the **valuation report** and the **margin decision memo** quote each
  other's figure verbatim — grafted from the Withheld Rebate design's
  sharpest trap: the report (APPROVED_REPORT, "what the actuary believes")
  states the booked figure as *what finance carries*, and the memo
  (APPROVED_REPORT, "what is carried"), states the central estimate as *what
  the actuary called for*. Similarity between the two documents cannot
  separate "what did the actuary estimate" from "what is booked" — only
  reading which document's own authority answers which question can.

Two more arrived with ``generators/insurance_book.py``, and they are here for a
measured reason rather than for volume. The four above are one argument about
one long-tail book, and between them they named **no business unit, no branch,
no claims centre, no underwriting office, no cost centre and no system** — a
whole insurer's organisation declared in the archetype, minted into the world,
and carried by nothing anybody could open:

* the **underwriting performance pack** is the quarter's book on one grid:
  written premium by unit, by line of business and by office; the policy book
  behind it; claims handled by claims centre; operating expense by cost centre;
  and what each system of record actually holds. It is the artifact that makes
  the estate *reachable* — a fact minted onto a branch that no document carries
  reproduces, one layer along, the exact defect ``validate.carried_evidence``
  exists to refuse.
* the **underwriting result commentary** fans out per business unit, argued and
  signed by that unit's own managing director. Those MD posts were minted by
  ``insurance_org._UNIT_ROLES`` for every unit and authored nothing; this is
  the one document in the vertical that scales with the company rather than
  with this file, which is what retail's divisional close commentary is for.
"""

from __future__ import annotations

from datetime import timedelta

from . import documents
from .documents import SectionPlan
from .generators.insurance_book import UnderwritingBook
from .generators.reserving import ReservingEpisode
from .ids import Minter
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    Cell,
    Chart,
    ChartKind,
    Column,
    ErrorType,
    FormulaKind,
    IntentionalError,
    Lifecycle,
    Row,
    Table,
)

MONEY_FORMAT = "#,##0;(#,##0)"

#: Who signs each of the four, by role key (`documents.approver_of`).
#:
#: The pairing is the point of this episode. The chief actuary's **valuation
#: report** goes to the reserving committee over the CFO's signature; the CFO's
#: own **margin decision memo** — which books less than that report
#: recommended — goes back over the chief actuary's. Each signed the other's
#: document, which is what a contested reserve position actually looks like on
#: paper, and where before there was an author each and no reviewer at all
#: there are now two named people answering for the gap between the numbers.
#:
#: The **emergence note** is unsigned because it is a working paper written
#: before any committee has seen it, which is the same argument banking's RWA
#: working paper makes: a signature would raise its authority against the
#: report it is meant to lose to.
#:
#: The **underwriting performance pack** is signed by the CFO: it is the
#: quarter's book as the ledger states it, and the controller who assembles it
#: is not the person who answers for it. The per-unit **commentary** is the one
#: signature in this vertical that a table keyed by type cannot express — each
#: division's is signed by the CEO its managing director reports to — so it
#: passes ``role_key`` to ``documents.approver_of`` instead, exactly as retail's
#: divisional close commentary does.
_APPROVED_BY: dict[str, str] = {
    "reserve_triangle_workbook": "chief_actuary",
    "actuarial_valuation_report": "cfo",
    "margin_decision_memo": "chief_actuary",
    "underwriting_performance_pack": "cfo",
}


def artifact_intents(
    minter: Minter,
    *,
    episode: ReservingEpisode,
    roles: dict[str, str],
    book: UnderwritingBook,
    units: tuple[tuple[str, str, str], ...],
) -> tuple[tuple[ArtifactIntent, ...], tuple[IntentionalError, ...]]:
    """Plan the artifacts of one phase-1 valuation, and label its lies.

    Order is identity: these mint ``ART`` ids, so a new artifact may only
    ever be appended after the fourth — inserting one would renumber
    everything a checked-in narration cites. The book's own documents are
    therefore planned in a block at the end, below the fan-out comment, the
    same discipline ``generators/planning.py`` states for retail's.

    ``units`` is ``(unit_key, unit_id, unit_name)`` per business unit, in the
    archetype's own order. Passed rather than read off a world because this
    function has no world: the fan-out has to be stable across a replay, and
    the archetype's declared order is the only ordering here that is.
    """
    k = episode.keys
    cohort_periods = sorted(
        {key.split("_", 3)[-1] for key in k if key.startswith("fact_ultimate_current_")}
    )
    intents: list[ArtifactIntent] = []
    # The shared minter, with insurance's own approval table: four planners
    # used to hand-copy this closure and drift on its keywords (see
    # ``documents.intent_minter``); what stays insurance's is _APPROVED_BY.
    intent = documents.intent_minter(
        minter, intents, roles=roles, approved_by=_APPROVED_BY
    )

    triangle_facts: list[str] = []
    for ay in cohort_periods:
        triangle_facts += [
            k[f"fact_paid_prior_{ay}"], k[f"fact_incurred_prior_{ay}"],
            k[f"fact_paid_current_{ay}"], k[f"fact_incurred_current_{ay}"],
            k[f"fact_ultimate_current_{ay}"], k[f"fact_ibnr_current_{ay}"],
        ]
        # The prior estimate is cited too — a workbook that dropped the
        # superseded link the moment it closed would make the mid-chain
        # temporal_state question unanswerable from any artifact, which
        # the evaluation's own reachability gate would then correctly refuse
        # to mint a case against.
        triangle_facts.append(k[f"fact_ultimate_prior_{ay}"])
        triangle_facts.append(k[f"fact_ibnr_prior_{ay}"])
    triangle_facts += [
        k["fact_paid_prior_rollup"], k["fact_incurred_prior_rollup"],
        k["fact_paid_current_rollup"], k["fact_incurred_current_rollup"],
        k["fact_central_prior"], k["fact_central_current"],
        k["fact_margin_prior"], k["fact_margin_current"],
        k["fact_booked_prior"], k["fact_booked_current"],
        k["fact_held_vs_central_gap"], k["fact_close_status"],
    ]

    # 1 — the triangle workbook: the source-of-record grid.
    workbook = intent(
        "reserve_triangle_workbook", "actuarial", "claims_and_actuarial",
        roles["reserving_actuary"], triangle_facts,
        [k["event_current_diagonal_recorded"], k["event_reserves_strengthened"]], "long",
        "The paid and incurred diagonal, both valuations, every cohort of the long-tail "
        "liability book — the grid every other document's figures trace back to.",
    )

    # 2 — the emergence note: low authority, and correct.
    emergence_facts: list[str] = []
    for ay in cohort_periods:
        emergence_facts += [
            k[f"fact_avse_{ay}"], k[f"fact_incurred_prior_{ay}"], k[f"fact_incurred_current_{ay}"],
        ]
    note = intent(
        "claims_emergence_note", "actuarial", "claims_and_actuarial",
        roles["reserving_actuary"], emergence_facts,
        [k["event_emergence_assessed"]], "medium",
        "The actual-versus-expected working paper: the deviation the strengthening "
        "responds to, cohort by cohort, before any committee has seen it.",
        # No `derived_from` on the workbook: the note is written *before* the
        # workbook's own citations (which run through the frozen booked
        # figure) make the workbook the later document — a `derived_from`
        # edge pointing at something not yet written is exactly what
        # `validate.py`'s `derives_from_later_artifact` check catches. The
        # two share cited facts (`claims.incurred_to_date`) without needing
        # a provenance edge between them.
    )

    # 3 — the valuation report: the actuary's formal position. States the
    # full central estimate plainly and quotes the booked figure verbatim —
    # the graft's other half is the memo, below.
    report_facts: list[str] = [
        k["fact_central_prior"], k["fact_central_current"],
        k["fact_attribution_pattern"], k["fact_attribution_deterioration"],
        k["fact_committee_recommendation"], k["fact_booked_current"],
        k["fact_philosophy"], k["fact_margin_policy"],
    ]
    for ay in cohort_periods:
        report_facts += [k[f"fact_ultimate_current_{ay}"], k[f"fact_ibnr_current_{ay}"]]
    report = intent(
        "actuarial_valuation_report", "actuarial", "reserving_committee",
        roles["chief_actuary"], report_facts,
        [k["event_reserves_strengthened"], k["event_committee_recommended"]], "long",
        "The formal valuation: the strengthened central estimate by cohort, the "
        "attribution split, and — stated plainly rather than left to a reader's "
        "inference — the booked figure the report's own recommendation was not fully "
        "carried into.",
        derived_from=[note.id, workbook.id],
    )

    # 4 — the margin decision memo: the contest record. Cites both the
    # central and booked facts, and quotes the central estimate verbatim —
    # the graft's first half.
    memo_facts = [
        k["fact_central_current"], k["fact_booked_current"], k["fact_booked_strengthening"],
        k["fact_margin_released"], k["fact_margin_current"], k["fact_held_vs_central_gap"],
        k["fact_committee_recommendation"], k["fact_philosophy"], k["fact_margin_policy"],
    ]
    memo = intent(
        "margin_decision_memo", "finance", "reserving_committee", roles["cfo"],
        memo_facts, [k["event_reserves_partially_booked"]], "medium",
        "The decision on the record: the central estimate the committee recommended in "
        "full, the amount actually booked, and the margin released to cover the "
        "difference under the standing combined-ratio target.",
        derived_from=[report.id],
    )

    # ------------------------------------------------------------------
    # The book block. Appended strictly after everything above, because ART
    # order is identity: the four intents above are cited by id in checked-in
    # narration and in the evaluation cases, and an intent inserted before
    # them would renumber every one. Anything added here in future goes below
    # this comment, never above it.
    # ------------------------------------------------------------------

    # 5 — the underwriting performance pack. Every subject the book cut, on one
    # grid. This is the artifact that makes the estate reachable rather than
    # merely minted: `validate.carried_evidence`'s dual is a subject that
    # exists and reaches nothing, and a branch fact carried by no document is
    # exactly that.
    pack_facts = book.ids_for(
        "financial.revenue.budget", "financial.revenue.actual",
        "financial.revenue.variance", "portfolio.policies_in_force",
        "claims_ops.notified_count", "claims_ops.settled_count",
        "expense.operating", "data.records_of_record",
    )
    intent(
        "underwriting_performance_pack", "finance", "all_staff",
        roles["financial_controller"], pack_facts,
        [book.keys["event_book_position_recorded"]], "long",
        "The quarter's book as the ledger states it: written premium by unit, by line "
        "of business and by office, the policy book behind it, claims handled by "
        "claims centre, operating expense by cost centre, and what each system of "
        "record holds.",
    )

    # 6..n — one commentary per business unit, argued and signed inside the
    # unit. The fan-out that scales with the company rather than with this
    # file: widen the archetype to six lines of business and six different
    # managing directors write six different documents.
    for unit_key, unit_id, _unit_name in units:
        own = book.ids_for(
            "financial.revenue.budget", "financial.revenue.actual",
            "financial.revenue.variance", "portfolio.policies_in_force",
            "claims_ops.notified_count", "claims_ops.settled_count",
            subjects=(unit_id,),
        )
        if not own:
            # A unit the book measured nothing for gets no page. Retail's
            # fan-out skips on the same predicate and for the same reason: a
            # commentary with no figures in it is a heading.
            continue
        author = roles.get(f"{unit_key}_md")
        if author is None:
            continue
        intent(
            "underwriting_result_commentary", "finance", "all_staff", author,
            own, [book.keys["event_book_position_recorded"]], "small",
            "Each division's quarter is argued by the managing director who answers "
            "for it, not only summed by the centre.",
            # Signed one level up, by the CEO the MD reports to — the one
            # approval in this vertical that fans out with the company, which
            # is why it goes through `role_key` rather than `_APPROVED_BY`.
            approver_role="ceo",
        )

    # The canonical figure a labelled imperfection cites has to be the fact's
    # own value in the form `validate.intentional`'s `_quantity_matches`
    # recognises — a descriptive string trips `canonical_mismatch`, which one
    # early draft of this error did, and the fix is what this comment
    # records.
    deterioration_fact = next(f for f in episode.facts if f.id == k["fact_attribution_deterioration"])
    deterioration_amount = int(deterioration_fact.value.amount)

    errors = (
        IntentionalError(
            id=minter.next("ERR"),
            artifact_id=memo.id,
            error_type=ErrorType.POLITICAL_UNDERSTATEMENT,
            observed_value=(
                "The memo frames the shortfall as a margin release under standing policy "
                "and does not state that the deterioration share of the attribution is the "
                "larger of the two"
            ),
            canonical_value=str(deterioration_amount),
            canonical_fact_id=k["fact_attribution_deterioration"],
            note=(
                "Deliberate: the memo is finance's paper, and it soft-pedals the adverse "
                "half of the attribution the actuarial valuation report states plainly. "
                "Reused from banking's POLITICAL_UNDERSTATEMENT vocabulary — no new error "
                "kind."
            ),
        ),
    )

    return tuple(intents), errors


# ---------------------------------------------------------------------------
# The triangle workbook
# ---------------------------------------------------------------------------


def reserve_triangle_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The triangle as a resolved workbook: cohort grid, book position, and a
    structurally blank future-development row.

    One compiler, new function, existing ``compilers=`` seam — the
    ``capital_return_ir`` precedent.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company

    cohorts = sorted({f.period for f in facts if f.kind == "claims.paid_to_date" and f.period})

    def cell(fact) -> Cell:  # type: ignore[no-untyped-def]
        if fact is None:
            return Cell(value=None)
        return Cell(value=fact.value.amount if fact.value else fact.text_value, fact_id=fact.id)

    # Every triangle kind coexists at two valuations for the same
    # (subject, period) — that is what a diagonal *is* — so "prior" and
    # "current" are resolved by validity ordering (`_earliest`/`_latest`),
    # never by picking "the" fact of a kind the way a non-recurring kind
    # would allow.
    value_columns = [
        Column(key="paid_prior", label="Paid (prior)", number_format=MONEY_FORMAT),
        Column(key="incurred_prior", label="Incurred (prior)", number_format=MONEY_FORMAT),
        Column(key="paid_current", label="Paid (current)", number_format=MONEY_FORMAT),
        Column(key="incurred_current", label="Incurred (current)", number_format=MONEY_FORMAT),
    ]
    diagonal_rows = [
        Row(key=ay, label=f"Accident quarter {ay}", cells={
            "paid_prior": cell(_earliest(facts, "claims.paid_to_date", ay)),
            "incurred_prior": cell(_earliest(facts, "claims.incurred_to_date", ay)),
            "paid_current": cell(_latest(facts, "claims.paid_to_date", ay)),
            "incurred_current": cell(_latest(facts, "claims.incurred_to_date", ay)),
        })
        for ay in cohorts
    ]
    # The book row. `generators/reserving.py` mints a paid and an incurred
    # rollup at each valuation with `period=None` — that is how a total over
    # accident cohorts is denominated — and the cohort comprehension above
    # filters on `f.period`, so all four landed in no compiled cell: a reserve
    # triangle with no total, and four facts a document was asked to carry and
    # did not. The same shape as the finance-workbook defect, one file over: a
    # period predicate that reads as a tidy-up and is really a filter on the
    # thing being looked for.
    #
    # Declared as a SUM of the cohorts rather than pasted, so a reader who
    # deletes an accident quarter sees the book move — and so the render tests'
    # formula evaluator recomputes it against the rollup fact the cell names.
    def rollup(kind: str, chooser) -> Cell:  # type: ignore[no-untyped-def]
        found = chooser(facts, kind, None)
        return Cell(
            value=found.value.amount if found and found.value else None,
            fact_id=found.id if found else None,
            formula=FormulaKind.SUM,
            operands=list(cohorts),
        )

    if cohorts:
        diagonal_rows.append(Row(key="book", label="Whole book", emphasis=True, cells={
            "paid_prior": rollup("claims.paid_to_date", _earliest),
            "incurred_prior": rollup("claims.incurred_to_date", _earliest),
            "paid_current": rollup("claims.paid_to_date", _latest),
            "incurred_current": rollup("claims.incurred_to_date", _latest),
        }))
    diagonals = Table(
        key="diagonals", title="Paid and incurred by accident cohort",
        columns=value_columns, rows=diagonal_rows,
        note=(
            f"{company.name} · long-tail liability book · {company.currency} "
            f"{company.currency_unit}. Both valuations, one row per accident quarter, "
            "and the whole book beneath them."
        ),
    )

    estimate_rows = [
        Row(key=ay, label=f"Accident quarter {ay}", cells={
            # Both valuations, not only the live one. A reserve triangle whose
            # estimate sheet carries one column is not a triangle — the whole
            # subject of this episode is that an ultimate *moved*, and a reader
            # holding only the strengthened figure cannot see that it did.
            #
            # Found by `validate.compiled_evidence` the day it existed: the
            # prior ultimate was required by this workbook, cited by the corpus's
            # own first evaluation case ("as at the 2026-03 valuation"), and
            # carried by no compiled document. The `Book position` sheet below
            # already showed prior against current for the totals; the
            # cohort-level sheet did not.
            "prior_ultimate": cell(_earliest(facts, "reserves.ultimate", ay)),
            "ultimate": cell(_latest(facts, "reserves.ultimate", ay)),
            "prior_ibnr": cell(_earliest(facts, "reserves.ibnr", ay)),
            "ibnr": cell(_latest(facts, "reserves.ibnr", ay)),
            "future_development": Cell(value=None),
        })
        for ay in cohorts
    ]
    estimates = Table(
        key="estimates", title="Actuarial estimate by accident cohort",
        columns=[
            Column(key="prior_ultimate", label="Ultimate, prior valuation",
                   number_format=MONEY_FORMAT),
            Column(key="ultimate", label="Ultimate, current valuation",
                   number_format=MONEY_FORMAT),
            Column(key="prior_ibnr", label="IBNR, prior valuation",
                   number_format=MONEY_FORMAT),
            Column(key="ibnr", label="IBNR, current valuation",
                   number_format=MONEY_FORMAT),
            Column(key="future_development", label="Development beyond this valuation"),
        ],
        rows=estimate_rows,
        note=(
            "The development-beyond-this-valuation column is blank by construction, not "
            "by omission: the tail past a live valuation is unobserved, the same way IBNR "
            "is unobservable in principle. No figure belongs there."
        ),
    )

    position = Table(
        key="position", title="Book position",
        columns=[
            Column(key="prior", label="Prior valuation", number_format=MONEY_FORMAT),
            Column(key="current", label="Current valuation", number_format=MONEY_FORMAT),
        ],
        rows=[
            Row(key="central", label="Actuarial central estimate", cells={
                "prior": cell(_earliest(facts, "reserves.central_estimate_total", None)),
                "current": cell(_latest(facts, "reserves.central_estimate_total", None)),
            }, emphasis=True),
            Row(key="margin", label="Risk margin remaining", cells={
                "prior": cell(_earliest(facts, "reserves.risk_margin_remaining", None)),
                "current": cell(_latest(facts, "reserves.risk_margin_remaining", None)),
            }),
            Row(key="booked", label="Booked reserve", cells={
                "prior": cell(_earliest(facts, "reserves.booked_total", None)),
                "current": cell(_latest(facts, "reserves.booked_total", None)),
            }, emphasis=True),
        ],
        note="Booked = central estimate + risk margin remaining, at every valuation date.",
    )

    # The reporting status of the valuation this grid is cut at. The intent has
    # always required `close.status` — a workbook read at a period still open is
    # a workbook whose figures can still move — and nothing in the compiler drew
    # it, so the one fact that tells a reader how much weight the sheet bears
    # was required by the document and carried by none of it.
    basis = Table(
        key="basis", title="Valuation basis and held position",
        columns=[Column(key="value", label="Value")],
        # By valid_from over the document's own facts, not by `world.period`.
        # The first version of this row looked the status up at the world's
        # current period and a German-locale insurance build — where the world
        # stands at one period and the reserving episode reports another —
        # rendered it blank, which is the finance-workbook defect exactly, in
        # the code added to close the finance-workbook defect. `validate`'s new
        # `carried_evidence` caught it on its first dispersed replay.
        rows=[
            Row(key="close_status", label="Reporting close status",
                cells={"value": cell(_latest_of(facts, "close.status"))}),
            # The margin the book actually holds over the actuary's own number.
            # Required by this workbook since the episode was written, carried
            # by the margin decision memo and by no sheet of the grid the memo
            # argues against — which the union-level `compiled_evidence` could
            # never see, because *some* document held it. The per-intent rule is
            # what surfaced it: this document was handed the figure.
            Row(key="held_gap", label="Held less actuarial central estimate",
                emphasis=True,
                cells={"value": cell(_latest_of(facts, "reserves.held_vs_central_gap"))}),
        ],
        note=(
            "A valuation cut at an open close is provisional; the grid above moves with it. "
            "The held position is stated here so the grid and the booked figure can be read "
            "together rather than from two documents."
        ),
    )

    sections = [
        ArtifactSection(heading="Paid and incurred by accident cohort", table=diagonals),
        ArtifactSection(heading="Actuarial estimate by accident cohort", table=estimates),
        ArtifactSection(heading="Book position", table=position),
        ArtifactSection(heading="Valuation basis", table=basis),
    ]

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Reserve Triangle Workbook",
        subtitle=f"Long-tail liability book · {company.currency} {company.currency_unit}",
        sections=sections,
        metadata={
            "worldloom_synthetic": "true",
            "worldloom_seed": str(world.seed),
            "worldloom_period": world.period or "",
            "worldloom_created": documents.written_at(
                intent, {f.id: f for f in facts}
            ).isoformat(),
            "company": company.name,
            "author": author.name,
            "author_title": author.title,
            "persona": persona.label if persona else "",
            "voice": persona.voice if persona else "",
            "note": "Synthetic corpus generated by Worldloom. Not a real company or insurer.",
        },
    )


# ---------------------------------------------------------------------------
# The underwriting performance pack
# ---------------------------------------------------------------------------


def underwriting_pack_ir(world, intent: ArtifactIntent, minter: Minter) -> ArtifactIR:  # type: ignore[no-untyped-def]
    """The quarter's book, on the six grids the organisation is cut into.

    Every subtotal is declared as a ``FormulaKind.SUM`` of the rows above it and
    every variance as a ``DIFFERENCE`` of two columns, so a reader who
    recalculates the sheet gets the same answer and a renderer that supports
    formulas emits them rather than pasting values — ``documents.
    finance_workbook``'s argument, applied to an insurer's cut.

    **No ratio column anywhere.** A loss ratio and an expense ratio are the two
    numbers an insurance reader would reach for first and both are ratios of
    totals; a subtotal row summing its children's rates would state a group
    expense ratio three times any cost centre's. The rule
    ``columns.not_summable`` and ``documents._RATE_KINDS`` already carry, kept
    here by not minting the column at all rather than by remembering to mark it.
    """
    facts = [world.facts.by_id(f) for f in intent.required_fact_ids]
    company = world.company
    money = f"{company.currency} {company.currency_unit}"

    # The pack's *own* facts decide which quarter it reports, never
    # `world.period`. Reaching for the world's period is the mistake that
    # rendered the finance workbook with every cell empty and validated clean,
    # and `reserve_triangle_ir`'s `_latest_of` carries the same warning one
    # function up: in a locale build the world stands at one period and the
    # episode reports another.
    periods = sorted({f.period for f in facts if f.period})
    period = periods[-1] if periods else (world.period or "")

    held: dict[tuple[str, str], object] = {}
    for f in facts:
        if f.period == period:
            held[(f.kind, f.subject)] = f

    def cell(kind: str, subject: str, **extra) -> Cell:  # type: ignore[no-untyped-def]
        found = held.get((kind, subject))
        if found is None:
            return Cell(value=None)
        return Cell(value=found.value.amount if found.value else found.text_value,
                    fact_id=found.id, **extra)

    def has(kind: str, subject: str) -> bool:
        return (kind, subject) in held

    def money_row(key: str, label: str, subject: str, *, children: list[str] | None = None,
                  emphasis: bool = False) -> Row:
        """One premium row: budget, actual, and the variance between them.

        The variance cell is a ``DIFFERENCE`` of this row's own two money
        columns rather than a second sum of the children, because the facts are
        built that way — the generator allocates actual and budget separately
        and states the variance as their difference, so any other declaration
        here would be a second, disagreeing account of one subtraction.
        """
        summing = {} if children is None else {
            "formula": FormulaKind.SUM, "operands": list(children)
        }
        return Row(key=key, label=label, emphasis=emphasis, cells={
            "budget": cell("financial.revenue.budget", subject, **summing),
            "actual": cell("financial.revenue.actual", subject, **summing),
            "variance": cell("financial.revenue.variance", subject,
                             formula=FormulaKind.DIFFERENCE,
                             operands=["actual", "budget"]),
        })

    money_columns = [
        Column(key="budget", label="Written premium, plan", number_format=MONEY_FORMAT),
        Column(key="actual", label="Written premium, actual", number_format=MONEY_FORMAT),
        Column(key="variance", label="Variance", number_format=MONEY_FORMAT),
    ]

    units = [u for u in world.business_units
             if has("financial.revenue.actual", u.id)]
    sections: list[ArtifactSection] = []

    # -- by business unit ---------------------------------------------------
    if units:
        rows = [money_row(u.id, u.name, u.id) for u in units]
        group = money_row(company.id, "Group", company.id,
                          children=[u.id for u in units], emphasis=True)
        rows.append(group)
        # The policy book beside the premium it was written on. Its own operand
        # list, not the row's: a unit that writes no premium book — an
        # investment function — has no policies either, and a group cell
        # declaring it as a child of the sum would name a blank cell as a part
        # of a total. The `policies` column therefore sums only the units that
        # state one, while the money columns sum all three.
        holders = [u for u in units if has("portfolio.policies_in_force", u.id)]
        for row, unit in zip(rows, units):
            row.cells["policies"] = cell("portfolio.policies_in_force", unit.id)
        group.cells["policies"] = cell(
            "portfolio.policies_in_force", company.id,
            formula=FormulaKind.SUM, operands=[u.id for u in holders],
        )
        sections.append(ArtifactSection(
            heading="Written premium by business unit",
            table=Table(
                key="units", title="Written premium by business unit",
                columns=[*money_columns,
                         Column(key="policies", label="Policies in force",
                                number_format="#,##0")],
                rows=rows,
                note=(
                    f"{company.name} · {period} · {money}. Group is the sum of the "
                    "business units above. The two underwriting units book gross "
                    "written premium and Group Investments books investment income, "
                    "so the group line is total revenue rather than premium — and "
                    "carries no policy book, which is why that column is short of a "
                    "row rather than short of a figure."
                ),
            ),
            charts=[Chart(
                key="unit_premium",
                title="Written premium against plan by business unit",
                kind=ChartKind.COLUMN, table="units",
                series=["budget", "actual"],
                # The unit rows only. Plotting the group beside them draws the
                # same money twice — `validate.charts` refuses it outright, and
                # it would dwarf every other bar even if it did not.
                rows=[u.id for u in units],
                category_axis="Business unit", value_axis=money,
            )],
        ))

    # -- by line of business ------------------------------------------------
    line_rows: list[Row] = []
    subtotals: list[str] = []
    for unit in units:
        members = [c for c in world.categories
                   if c.business_unit_id == unit.id
                   and has("financial.revenue.actual", c.id)]
        if not members:
            continue
        for line in members:
            line_rows.append(money_row(line.id, f"{unit.name} · {line.name}", line.id))
        line_rows.append(money_row(unit.id, f"{unit.name} total", unit.id,
                                   children=[c.id for c in members], emphasis=True))
        subtotals.append(unit.id)
    if line_rows:
        sections.append(ArtifactSection(
            heading="Written premium by line of business",
            table=Table(
                key="lines", title="Written premium by line of business",
                columns=money_columns, rows=line_rows,
                note=(
                    "Lines sum to their business unit. No group row: Group Investments "
                    "writes no premium and is not decomposed by book, so a row headed "
                    "'Group' here would name a total these lines do not reach."
                ),
            ),
        ))

    # -- by underwriting office and branch ----------------------------------
    office_columns = [
        Column(key="region", label="Region"),
        Column(key="format", label="Format"),
        *money_columns,
        Column(key="policies", label="Policies in force", number_format="#,##0"),
    ]
    blank = {"region": Cell(value=""), "format": Cell(value="")}
    office_rows: list[Row] = []
    for unit in units:
        estate = [s for s in world.sites
                  if s.business_unit_id == unit.id
                  and has("financial.revenue.actual", s.id)]
        if not estate:
            continue
        for site in estate:
            row = money_row(site.id, site.name, site.id)
            row.cells["region"] = Cell(value=site.region)
            row.cells["format"] = Cell(value=site.format)
            row.cells["policies"] = cell("portfolio.policies_in_force", site.id)
            office_rows.append(row)
        total = money_row(unit.id, f"{unit.name} total", unit.id,
                          children=[s.id for s in estate], emphasis=True)
        total.cells.update(blank)
        total.cells["policies"] = cell(
            "portfolio.policies_in_force", unit.id,
            formula=FormulaKind.SUM, operands=[s.id for s in estate],
        )
        office_rows.append(total)
    if office_rows:
        sections.append(ArtifactSection(
            heading="Written premium by office",
            table=Table(
                key="offices", title="Written premium by underwriting office",
                columns=office_columns, rows=office_rows,
                note=(
                    "Offices decompose the same unit premium the lines of business do, "
                    "so both sheets reach the same unit total by different routes. "
                    "Claims centres process claims and write no premium, so they are "
                    "not listed here — they have their own sheet below."
                ),
            ),
        ))

    # -- claims handled, by claims centre -----------------------------------
    claims_columns = [
        Column(key="notified", label="Claims notified", number_format="#,##0"),
        Column(key="settled", label="Claims settled", number_format="#,##0"),
    ]

    def claims_row(key: str, label: str, subject: str, *, children: list[str] | None = None,
                   emphasis: bool = False) -> Row:
        summing = {} if children is None else {
            "formula": FormulaKind.SUM, "operands": list(children)
        }
        return Row(key=key, label=label, emphasis=emphasis, cells={
            "notified": cell("claims_ops.notified_count", subject, **summing),
            "settled": cell("claims_ops.settled_count", subject, **summing),
        })

    claims_rows: list[Row] = []
    handling_units = [u for u in world.business_units
                      if has("claims_ops.notified_count", u.id)]
    for unit in handling_units:
        centres = [s for s in world.sites
                   if s.business_unit_id == unit.id
                   and has("claims_ops.notified_count", s.id)]
        for centre in centres:
            claims_rows.append(claims_row(centre.id, centre.name, centre.id))
        claims_rows.append(claims_row(
            unit.id, f"{unit.name} total", unit.id,
            children=[c.id for c in centres] or None, emphasis=True,
        ))
    if claims_rows:
        claims_rows.append(claims_row(
            company.id, "Group", company.id,
            children=[u.id for u in handling_units], emphasis=True,
        ))
        sections.append(ArtifactSection(
            heading="Claims handled by claims centre",
            table=Table(
                key="claims", title="Claims notified and settled",
                columns=claims_columns, rows=claims_rows,
                note=(
                    "Operational counts for the quarter, not reserves: what the claims "
                    "function opened and closed. What those claims will ultimately cost "
                    "is cut by accident cohort in the reserve triangle workbook and is "
                    "deliberately not cut by site — a claim belongs to the quarter it "
                    "happened in, not to the office that logged it. A unit with no "
                    "dedicated claims centre states its total and no breakdown."
                ),
            ),
        ))

    # -- operating expense, by cost centre ----------------------------------
    centres = [c for c in world.cost_centres if has("expense.operating", c.id)]
    if centres:
        expense_rows = [
            Row(key=c.id, label=c.name,
                cells={"amount": cell("expense.operating", c.id)})
            for c in centres
        ]
        expense_rows.append(Row(
            key=company.id, label="Group operating expense", emphasis=True,
            cells={"amount": cell("expense.operating", company.id,
                                  formula=FormulaKind.SUM,
                                  operands=[c.id for c in centres])},
        ))
        sections.append(ArtifactSection(
            heading="Operating expense by cost centre",
            table=Table(
                key="expense", title="Operating expense by cost centre",
                columns=[Column(key="amount", label=f"Amount ({money})",
                                number_format=MONEY_FORMAT)],
                rows=expense_rows,
                note=(
                    "Cost centres sum to the group. The expense ratio this implies is "
                    "left to the reader to divide: a ratio of totals is never the total "
                    "of ratios, so a rate column here would give the group a figure no "
                    "cost centre recognises."
                ),
            ),
        ))

    # -- what each system of record holds -----------------------------------
    of_record = [s for s in world.systems if has("data.records_of_record", s.id)]
    if of_record:
        sections.append(ArtifactSection(
            heading="Systems of record",
            table=Table(
                key="systems", title="Records held by system of record",
                columns=[
                    Column(key="records_for", label="System of record for"),
                    Column(key="records", label="Records held", number_format="#,##0"),
                ],
                rows=[
                    Row(key=s.id, label=s.name, cells={
                        "records_for": Cell(value=", ".join(s.is_system_of_record_for)),
                        "records": cell("data.records_of_record", s.id),
                    })
                    for s in of_record
                ],
                note=(
                    "No total: five systems of record for five different things do not "
                    "add up to a number anybody would report. `System."
                    "is_system_of_record_for` is what each row is counting."
                ),
            ),
        ))

    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    return ArtifactIR(
        id=intent.id,
        intent_id=intent.id,
        title=f"{company.name} — Underwriting Performance Pack",
        subtitle=f"{period} · {money}",
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
            "note": "Synthetic corpus generated by Worldloom. Not a real company or insurer.",
        },
    )


def _earliest(facts, kind: str, period: str | None):  # type: ignore[no-untyped-def]
    found = sorted((f for f in facts if f.kind == kind and f.period == period), key=lambda f: f.valid_from)
    return found[0] if found else None


def _latest(facts, kind: str, period: str | None):  # type: ignore[no-untyped-def]
    found = sorted((f for f in facts if f.kind == kind and f.period == period), key=lambda f: f.valid_from)
    return found[-1] if found else None


def _latest_of(facts, kind: str):  # type: ignore[no-untyped-def]
    """The newest fact of *kind* the document holds, whatever period it names.

    For the singletons — a close status, a valuation basis — where the document
    carries exactly one and the period on it is the episode's, which is not
    necessarily the world's. Reaching for `world.period` here is the mistake
    that emptied the finance workbook, and a `period=` argument invites it.
    """
    found = sorted((f for f in facts if f.kind == kind), key=lambda f: f.valid_from)
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from .render import docx as _docx
from .render import markdown as _markdown
from .render import xlsx as _xlsx

_xlsx.register("reserve_triangle_workbook", "underwriting_performance_pack")
_markdown.own_elsewhere("reserve_triangle_workbook", "underwriting_performance_pack")
_docx.register(
    "claims_emergence_note",
    "actuarial_valuation_report",
    "margin_decision_memo",
    "underwriting_result_commentary",
)

documents.register_artifact_types(
    standing={
        "reserve_triangle_workbook": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "claims_emergence_note": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT),
        "actuarial_valuation_report": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        "margin_decision_memo": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        # The pack is the ledger's own statement of the quarter's book, so it
        # is SYSTEM_OF_RECORD beside the triangle. The commentary is an
        # approved report *about* the pack, one authority below it: when a
        # managing director's page and the pack disagree, the pack wins.
        "underwriting_performance_pack": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "underwriting_result_commentary": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    },
    lags={
        "reserve_triangle_workbook": timedelta(hours=1),
        "claims_emergence_note": timedelta(hours=4),
        "actuarial_valuation_report": timedelta(days=1),
        "margin_decision_memo": timedelta(days=1, hours=6),
        "underwriting_performance_pack": timedelta(hours=2),
        # After the pack it argues from, and by more than the pack's own lag,
        # so a commentary can never be dated before the grid it reads.
        "underwriting_result_commentary": timedelta(days=1, hours=2),
    },
    outlines={
        "claims_emergence_note": (
            SectionPlan(
                "Actual versus expected", ("claims.actual_vs_expected", "claims.incurred_to_date"), "any",
                "State the deviation by cohort: what incurred was expected to be under the "
                "prior pattern, and what it actually was. Working-paper register — this is "
                "the low-authority document that happens to be right.",
            ),
        ),
        "actuarial_valuation_report": (
            SectionPlan(
                "Central estimate", ("reserves.central_estimate_total", "reserves.ultimate",
                                      "reserves.ibnr"), "any",
                "State the strengthened central estimate by cohort and in total, plainly. "
                "This is the actuary's own report; it does not soften the figure for the "
                "committee that will decide how much of it to book.",
            ),
            SectionPlan(
                "Attribution", ("reserves.attribution_pattern_change",
                                 "reserves.attribution_deterioration"), "any",
                "The split between pattern change and genuine deterioration, and that the "
                "two do not resolve into one figure — both are on the record.",
            ),
            SectionPlan(
                "Recommendation and the booked position",
                ("reserves.committee_recommendation", "reserves.booked_total"), "any",
                "State the committee's recommendation, then — quoting the figure exactly as "
                "finance's own decision memo states it — what was actually booked. The gap "
                "between the two is not this report's decision to explain; it is the "
                "memo's.",
            ),
            SectionPlan(
                "Basis of valuation", ("reserves.philosophy", "reserves.risk_margin_policy_pct"), "any",
                "One paragraph: the standing margin policy this valuation was performed "
                "under.",
                # The standing policy, restated. It is the same paragraph in
                # every valuation this actuary signs, and its absence reads as a
                # report that assumed its reader knows the house philosophy —
                # not as a report missing a figure. The central estimate, the
                # attribution and the booked position stay required; they are
                # what the committee is measured against.
                required=False,
            ),
        ),
        "underwriting_result_commentary": (
            SectionPlan(
                "The quarter against plan", ("financial.revenue.",), "unit",
                "State this division's written premium against its own plan and say "
                "plainly whether the quarter was acceptable. Lead with the position, "
                "not with the first figure in the list — the reader runs the division "
                "and already knows its shape.",
            ),
            SectionPlan(
                "The book and the claims behind it",
                ("portfolio.policies_in_force", "claims_ops."), "unit",
                "Connect the policy book to the claims coming off it: whether the "
                "division is writing more business, and whether its claims function is "
                "closing what it opens. Not every division has a claims operation of "
                "its own; do not invent one for a division whose figures are absent.",
                # An investment function has no policy book and notifies no
                # claims, and a division that genuinely has neither should not
                # carry an empty heading. `outline` drops a section with no
                # facts assigned; marking it optional is what says that is
                # intended rather than a section somebody lost.
                required=False,
            ),
        ),
        "margin_decision_memo": (
            SectionPlan(
                "The decision", ("reserves.booked_strengthening", "reserves.margin_released"), "any",
                "State what was booked and what margin was released to cover the "
                "difference, under the standing combined-ratio target.",
            ),
            SectionPlan(
                "The central estimate", ("reserves.central_estimate_total",
                                          "reserves.committee_recommendation"), "any",
                "Quote the actuarial central estimate exactly as the valuation report "
                "states it — this memo's decision is measured against that figure, not "
                "against a paraphrase of it.",
            ),
            SectionPlan(
                "The standing gap", ("reserves.held_vs_central_gap",), "any",
                "State that the booked reserve now sits below the central estimate, by how "
                "much, and that the policy basis for the release is the standing margin "
                "philosophy, not an exception to it.",
            ),
        ),
    },
    compilers={
        "reserve_triangle_workbook": reserve_triangle_ir,
        "underwriting_performance_pack": underwriting_pack_ir,
    },
)
