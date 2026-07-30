"""Artifact planning and evaluation generation.

Two outputs, both derived from facts that already exist.

``ArtifactIntent`` is the decision that a document *should* exist — its type,
audience, author, and the facts it must be able to cite. No content. Bodies arrive
with the renderers at step 5 and prose with the constrained compiler at step 6, so
a step-3 world carries intents and no manifest entries.

``EvaluationCase`` is a question whose answer is read out of the fact ledger rather
than invented. That is the property that makes the eval set trustworthy: nothing
here writes an answer, it only records which facts constitute one.
"""

from __future__ import annotations

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact, EvaluationCase, EvaluationType
from .operations import CloseEpisode


def _fmt(fact: CanonicalFact) -> str:
    """A fact's value as text, for an expected answer."""
    if fact.value is not None:
        amount = fact.value.amount
        rendered = f"{int(amount):,}" if float(amount).is_integer() else f"{amount:,.2f}"
        return f"{rendered} {fact.value.unit}"
    return fact.text_value or ""


def _adverse(fact: CanonicalFact) -> str:
    """A variance as a reader would state it: magnitude plus direction, not a sign.

    An expected answer is graded against a system's prose, so "7,200 below budget"
    is a fairer target than "-7200".
    """
    if fact.value is None:
        return fact.text_value or ""
    amount = fact.value.amount
    magnitude = f"{abs(int(amount)):,}" if float(amount).is_integer() else f"{abs(amount):,.2f}"
    direction = "below" if amount < 0 else "above"
    return f"{magnitude} {fact.value.unit} {direction} budget"


def artifact_intents(
    minter: Minter,
    *,
    episode: CloseEpisode,
    roles: dict[str, str],
    financial_facts: tuple[CanonicalFact, ...],
    period: str,
    density: float,
    workbook_facts: tuple[CanonicalFact, ...] = (),
) -> tuple[ArtifactIntent, ...]:
    """Plan the artifacts this episode warrants.

    Bounded fan-out proper is step 10. What is here is the floor: the workbook and
    the CFO report always exist because a close always produces them, and the
    incident artifacts exist only when there was an incident. A close without an
    incident does not get an RCA — the plan follows the episode, not a template.

    ``financial_facts`` is the headline cut — group and unit, this period. It is
    what the narrative artifacts cite. ``workbook_facts`` is the whole hierarchy
    down to category and store, and only the workbook gets it: a variance memo
    handed four thousand facts would produce four thousand narrative requests to
    write five paragraphs.
    """
    money = [f.id for f in financial_facts]
    detail = [f.id for f in (workbook_facts or financial_facts)]
    intents: list[ArtifactIntent] = []

    def intent(artifact_type: str, domain: str, audience: str, author: str,
               facts: list[str], events: list[str], size: str, rationale: str) -> None:
        intents.append(
            ArtifactIntent(
                id=minter.next("ART"),
                artifact_type=artifact_type,
                domain=domain,
                audience=audience,
                author_id=author,
                triggered_by=events,
                required_fact_ids=facts,
                size_profile=size,  # type: ignore[arg-type]
                rationale=rationale,
            )
        )

    intent("close_calendar", "finance", "all_staff", roles["reporting_manager"],
           [episode.keys["fact_due_date"]], [episode.keys["event_close_started"]], "small",
           "The close calendar states the committed date every period.")

    intent("finance_workbook", "finance", "finance", roles["reporting_manager"],
           detail + [episode.keys["fact_close_delay"]], [episode.close_event_id], "long",
           "The month-end model is the source artifact for the period and must reconcile.")

    intent("cfo_variance_memo", "finance", "group_cfo", roles["controller"],
           money + [episode.keys["fact_close_status_final"], episode.keys["fact_close_delay"]],
           [episode.close_event_id], "medium",
           "Variance commentary is produced for every close.")

    if episode.had_incident:
        k = episode.keys
        intent("working_note", "finance", "finance", roles["controller"],
               [k["fact_feed_status"], k["fact_hypothesis"], k["fact_cause"], k["fact_close_delayed"]],
               [k["event_pipeline_failed"], k["event_close_delayed"]], "small",
               "The controller keeps a running note through a disrupted close.")

        intent("confluence_page", "operations", "all_staff", roles["svc_desk"],
               [k["fact_feed_status"], k["fact_incident_ref"], k["fact_hypothesis"]],
               [k["event_incident_opened"], k["event_hypothesis"]], "small",
               "A status page is raised at triage, before the cause is known. It goes stale.")

        intent("servicenow_incident", "operations", "technology", roles["svc_desk"],
               [k["fact_feed_status"], k["fact_incident_ref"], k["fact_hypothesis"], k["fact_cause"],
                k["fact_affected"], k["fact_workaround"], k["fact_valuation_status"], k["fact_classification"]],
               [k["event_incident_opened"], k["event_root_cause"], k["event_control_failure"]], "medium",
               "The incident record is the system of record for the operational timeline.")

        intent("incident_rca", "engineering", "technology", roles["platform_senior"],
               [k["fact_feed_status"], k["fact_incident_ref"], k["fact_hypothesis"],
                k["fact_cause_ruled_out"], k["fact_cause"], k["fact_affected"],
                k["fact_valuation_status"], k["fact_recurrence"], k["fact_workaround"],
                k["fact_classification"], k["fact_owner"], k["fact_remediation"],
                k["fact_remediation_scope"], k["fact_close_delayed"]],
               [k["event_root_cause"], k["event_control_failure"]], "long",
               "A P2 incident that delayed the close warrants a reviewed RCA.")

        intent("jira_issues", "engineering", "technology", roles["platform_lead"],
               [k["fact_classification"], k["fact_owner"], k["fact_remediation"], k["fact_remediation_scope"]],
               [k["event_remediation"]], "small",
               "Remediation is tracked as work, separating the control fix from the detection fix.")

        if density > 0.0:
            intent("knowledge_article", "operations", "technology", roles["platform_engineer"],
                   [k["fact_cause"], k["fact_affected"], k["fact_workaround"], k["fact_owner"]],
                   [k["event_root_cause"]], "medium",
                   "The workaround is repeatable and undocumented, so it is written up.")

        intent("executive_summary", "strategy", "executive_committee", roles["cfo"],
               [f.id for f in financial_facts if f.subject.startswith("CO")]
               + [k["fact_close_status_final"], k["fact_close_delay"], k["fact_pl_impact"]],
               [k["event_close_delayed"]], "small",
               "The executive committee receives a short summary. It omits the control failure.")

    return tuple(intents)


def evaluation_cases(
    minter: Minter,
    *,
    episode: CloseEpisode,
    financial_facts: tuple[CanonicalFact, ...],
    company_id: str,
    unit_ids: dict[str, str],
    unit_names: dict[str, str],
    period: str,
) -> tuple[EvaluationCase, ...]:
    """Derive evaluation cases from the generated facts.

    The seven step-1 exit-gate questions, plus the abstention cases that stop the
    set from being answerable by construction. The full taxonomy is step 4; what
    matters here is that answers are *read* from facts, never authored.
    """
    by_kind: dict[tuple[str, str], CanonicalFact] = {}
    for fact in (*financial_facts, *episode.facts):
        if not fact.is_superseded:
            by_kind[(fact.kind, fact.subject)] = fact

    cases: list[EvaluationCase] = []

    def case(question: str, kind: EvaluationType, answer: str, facts: list[str],
             *, cutoff=None, difficulty: str = "medium", reasoning: str = "") -> None:
        cases.append(
            EvaluationCase(
                id=minter.next("EVAL"), question=question, evaluation_type=kind,
                expected_answer=answer, expected_fact_ids=facts, temporal_cutoff=cutoff,
                difficulty=difficulty, reasoning=reasoning,  # type: ignore[arg-type]
            )
        )

    revenue = by_kind[("financial.revenue.actual", company_id)]
    budget = by_kind[("financial.revenue.budget", company_id)]
    variance = by_kind[("financial.revenue.variance", company_id)]

    case(f"What was total revenue for {period}?", EvaluationType.DIRECT_LOOKUP,
         _fmt(revenue), [revenue.id], difficulty="easy",
         reasoning="Single lookup against the system of record.")

    pct = abs(variance.value.amount / budget.value.amount * 100) if budget.value.amount else 0.0
    case(f"By how much did revenue miss budget in {period}, in absolute terms and as a percentage?",
         EvaluationType.NUMERICAL_COMPARISON,
         f"{_adverse(variance)}, or {pct:.2f}%.",
         [revenue.id, budget.id, variance.id], difficulty="easy",
         reasoning="Actual, budget, and the derived percentage must agree.")

    unit_variances = [by_kind[("financial.revenue.variance", unit_id)] for unit_id in unit_ids.values()]
    worst = min(unit_variances, key=lambda f: f.value.amount)
    case(f"Which business unit caused the largest revenue variance in {period}?",
         EvaluationType.NUMERICAL_COMPARISON,
         f"{unit_names.get(worst.subject, worst.subject)}, at {_adverse(worst)}.",
         [f.id for f in unit_variances],
         reasoning="Requires comparing every unit rather than reading one.")

    gp_variances = [
        by_kind[("financial.gross_profit.variance", subject)]
        for subject in (*unit_ids.values(), company_id)
    ]
    case(f"Does gross profit variance reconcile between the units and the group for {period}?",
         EvaluationType.NUMERICAL_COMPARISON, "Yes — the unit variances sum to the group variance.",
         [f.id for f in gp_variances],
         reasoning="Tests the property the whole corpus rests on.")

    if episode.had_incident:
        k = episode.keys
        cause = next(f for f in episode.facts if f.id == k["fact_cause"])
        hypothesis = next(f for f in episode.facts if f.id == k["fact_hypothesis"])
        delayed = next(f for f in episode.facts if f.id == k["fact_close_delayed"])
        delay = next(f for f in episode.facts if f.id == k["fact_close_delay"])

        case(f"Why was the {period} close delayed?", EvaluationType.CAUSAL_MULTI_HOP,
             f"{cause.text_value}, which stopped valuation and pushed the close by "
             f"{int(delay.value.amount)} business day(s).",
             [k["fact_feed_status"], cause.id, delayed.id, delay.id], difficulty="hard",
             reasoning="Failure to cause to workaround to calendar impact.")

        case("What was the confirmed root cause of the valuation failure?",
             EvaluationType.DIRECT_LOOKUP, cause.text_value or "", [cause.id],
             reasoning="'Confirmed' distinguishes this from the superseded hypothesis.")

        # The wrong answer is correct at this moment. A system that always returns
        # the confirmed cause fails here, which is the point.
        midpoint = hypothesis.valid_from + (hypothesis.valid_to - hypothesis.valid_from) / 2
        case("At the time triage first recorded a cause, what was believed to be the cause?",
             EvaluationType.TEMPORAL_STATE, hypothesis.text_value or "", [hypothesis.id],
             cutoff=midpoint, difficulty="hard",
             reasoning="At this cut-off the superseded answer is the correct one.")

        case("Which record still carries the initial hypothesis rather than the confirmed cause?",
             EvaluationType.AUTHORITY_RESOLUTION,
             "The triage status page, which was never updated after the hypothesis was ruled out.",
             [hypothesis.id, cause.id], difficulty="hard",
             reasoning="Requires recognising a stale source as stale.")

        case("Which remediation addresses the underlying control failure rather than only detection?",
             EvaluationType.CROSS_ARTIFACT,
             "The ownership assignment. The validation ticket addresses detection only.",
             [k["fact_classification"], k["fact_remediation"], k["fact_remediation_scope"]],
             difficulty="hard", reasoning="Both tickets are plausible; the classification separates them.")

        case(f"What was the P&L impact of the incident on the {period} result?",
             EvaluationType.NUMERICAL_COMPARISON,
             "Zero — valuation completed before the ledger closed. The impact was on the calendar only.",
             [k["fact_pl_impact"]],
             reasoning="A plausible wrong answer attributes the revenue shortfall to the incident.")

        case("Who owns the product hierarchy mapping table?", EvaluationType.CITATION_REQUIRED,
             "Nobody — the owner is unassigned.", [k["fact_owner"]],
             reasoning="The correct answer is that the field is empty, which is not the same as abstaining.")

    final = next(f for f in episode.facts if f.id == episode.keys["fact_close_status_final"])
    case("Which source was authoritative for the close status at the end of the period?",
         EvaluationType.AUTHORITY_RESOLUTION,
         f"The finance system of record, reporting the close as {final.text_value}.",
         [final.id], cutoff=final.valid_from, difficulty="hard",
         reasoning="Working documents may still show the close as open; they are not the record.")

    for question, reasoning in (
        ("What was the root cause of the previous period's close delay?",
         "Presupposes an event this corpus does not contain."),
        ("What is the Group Chief Executive Officer's total remuneration?",
         "The person exists; the fact does not."),
        ("How many stores does the Food business unit operate?",
         "A plausible retail question this corpus does not answer."),
    ):
        cases.append(
            EvaluationCase(
                id=minter.next("EVAL"), question=question,
                evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
                expected_answer="Not present in the corpus.", expects_abstention=True,
                difficulty="hard", reasoning=reasoning,
            )
        )

    return tuple(cases)
