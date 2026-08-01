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
"""

from __future__ import annotations

from datetime import timedelta

from . import documents
from .documents import SectionPlan
from .generators.reserving import ReservingEpisode
from .ids import Minter
from .models import (
    ArtifactIntent,
    ArtifactIR,
    ArtifactSection,
    Authority,
    Cell,
    Column,
    ErrorType,
    IntentionalError,
    Lifecycle,
    Row,
    Table,
)

MONEY_FORMAT = "#,##0;(#,##0)"


def artifact_intents(
    minter: Minter,
    *,
    episode: ReservingEpisode,
    roles: dict[str, str],
) -> tuple[tuple[ArtifactIntent, ...], tuple[IntentionalError, ...]]:
    """Plan the four artifacts of one phase-1 valuation, and label its lies.

    Order is identity: these mint ``ART`` ids, so a new artifact may only
    ever be appended after the fourth — inserting one would renumber
    everything a checked-in narration cites.
    """
    k = episode.keys
    cohort_periods = sorted(
        {key.split("_", 3)[-1] for key in k if key.startswith("fact_ultimate_current_")}
    )
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
            triggered_by=events,
            required_fact_ids=facts,
            size_profile=size,  # type: ignore[arg-type]
            rationale=rationale,
            derived_from=derived_from or [],
        )
        intents.append(made)
        return made

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
    diagonals = Table(
        key="diagonals", title="Paid and incurred by accident cohort",
        columns=value_columns, rows=diagonal_rows,
        note=(
            f"{company.name} · long-tail liability book · {company.currency} "
            f"{company.currency_unit}. Both valuations, one row per accident quarter."
        ),
    )

    estimate_rows = [
        Row(key=ay, label=f"Accident quarter {ay}", cells={
            "ultimate": cell(_latest(facts, "reserves.ultimate", ay)),
            "ibnr": cell(_latest(facts, "reserves.ibnr", ay)),
            "future_development": Cell(value=None),
        })
        for ay in cohorts
    ]
    estimates = Table(
        key="estimates", title="Actuarial estimate by accident cohort (current valuation)",
        columns=[
            Column(key="ultimate", label="Ultimate", number_format=MONEY_FORMAT),
            Column(key="ibnr", label="IBNR", number_format=MONEY_FORMAT),
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

    sections = [
        ArtifactSection(heading="Paid and incurred by accident cohort", table=diagonals),
        ArtifactSection(heading="Actuarial estimate by accident cohort", table=estimates),
        ArtifactSection(heading="Book position", table=position),
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


def _earliest(facts, kind: str, period: str | None):  # type: ignore[no-untyped-def]
    found = sorted((f for f in facts if f.kind == kind and f.period == period), key=lambda f: f.valid_from)
    return found[0] if found else None


def _latest(facts, kind: str, period: str | None):  # type: ignore[no-untyped-def]
    found = sorted((f for f in facts if f.kind == kind and f.period == period), key=lambda f: f.valid_from)
    return found[-1] if found else None


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

from .render import docx as _docx, markdown as _markdown, xlsx as _xlsx  # noqa: E402

_xlsx.register("reserve_triangle_workbook")
_markdown.own_elsewhere("reserve_triangle_workbook")
_docx.register(
    "claims_emergence_note",
    "actuarial_valuation_report",
    "margin_decision_memo",
)

documents.register_artifact_types(
    standing={
        "reserve_triangle_workbook": (Authority.SYSTEM_OF_RECORD, Lifecycle.PUBLISHED),
        "claims_emergence_note": (Authority.WORKING_DOCUMENT, Lifecycle.DRAFT),
        "actuarial_valuation_report": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
        "margin_decision_memo": (Authority.APPROVED_REPORT, Lifecycle.PUBLISHED),
    },
    lags={
        "reserve_triangle_workbook": timedelta(hours=1),
        "claims_emergence_note": timedelta(hours=4),
        "actuarial_valuation_report": timedelta(days=1),
        "margin_decision_memo": timedelta(days=1, hours=6),
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
    compilers={"reserve_triangle_workbook": reserve_triangle_ir},
)
