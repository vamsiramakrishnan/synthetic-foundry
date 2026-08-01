"""Artifact planning and evaluation generation.

Two outputs, both derived from facts that already exist.

``ArtifactIntent`` is the decision that a document *should* exist — its type,
audience, author, and the facts it must be able to cite. No content. Bodies arrive
with the renderers at step 5 and prose with the constrained compiler at step 6, so
a step-3 world carries intents and no manifest entries.

The evaluation taxonomy moved to ``generators/evaluation.py`` when it outgrew a
function: cases are now organised by the capability each family demands, and they
need the category hierarchy this module also now takes, for the same reason
(``eval_density``'s category-level fan-out, below) rather than a coincidence of
two modules wanting the same shape.
"""

from __future__ import annotations

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact
from .operations import CloseEpisode


def artifact_intents(
    minter: Minter,
    *,
    episode: CloseEpisode,
    roles: dict[str, str],
    financial_facts: tuple[CanonicalFact, ...],
    period: str,
    density: float,
    workbook_facts: tuple[CanonicalFact, ...] = (),
    prior_intents: tuple[ArtifactIntent, ...] = (),
    actor_authored: bool = False,
    categories_by_unit: dict[str, list[str]] | None = None,
    eval_density: float = 1.0,
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

    ``actor_authored`` withholds the incident block. When an actor episode runs,
    those seven documents are produced by employees calling ``draft_artifact``,
    each citing the facts *that employee had observed* — which is the whole point
    of the exercise, and is undermined entirely if the planner has already
    written the same documents from an omniscient view of the fact ledger. The
    close's standing outputs stay here: the calendar, the workbook, and the
    variance memo exist every period whether or not anything went wrong, so
    nobody decides to write them.

    ``eval_density`` is the ``--eval-density`` knob's numeric value. At its
    default (``1.0``) it changes nothing here — every intent below it is
    gated strictly above 1.0. Above it, the same finance business partner who
    already argues a unit's month (below) also argues that unit's biggest
    categories, reusing ``unit_close_commentary`` rather than a new artifact
    type: the type's outline (``documents.py``) scopes its sections by the
    intent's own ``required_fact_ids``, never by ``artifact_type``, so the
    identical shape already argues a category's month exactly as it argues a
    unit's. A second type here would duplicate machinery to mark a
    distinction the rendered document does not need to make.
    """
    money = [f.id for f in financial_facts]
    detail = [f.id for f in (workbook_facts or financial_facts)]
    intents: list[ArtifactIntent] = []
    unit_keys = [key.removeprefix("unit_") for key in roles if key.startswith("unit_")]

    def latest(artifact_type: str) -> str | None:
        """The most recent prior artifact of a type, if this world has run before.

        Intents accumulate in order, so the last one of a type is the previous
        period's. That is what makes a second episode continuous with the first
        rather than a fresh world that happens to share a company name.
        """
        found = [i.id for i in prior_intents if i.artifact_type == artifact_type]
        return found[-1] if found else None

    def latest_intent(artifact_type: str) -> ArtifactIntent | None:
        """Like ``latest``, but the intent itself rather than only its id.

        A revision needs more than its predecessor's id: it needs what the
        predecessor actually said, so it can carry that forward rather than
        starting from nothing at version two.
        """
        found = [i for i in prior_intents if i.artifact_type == artifact_type]
        return found[-1] if found else None

    def intent(artifact_type: str, domain: str, audience: str, author: str,
               facts: list[str], events: list[str], size: str, rationale: str,
               *, supersedes: str | None = None, derived_from: list[str] | None = None,
               revises: str | None = None) -> None:
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
                supersedes=supersedes,
                derived_from=[a for a in (derived_from or []) if a],
                revises=revises,
            )
        )

    # Republished every period, replacing the last one. This is the corpus's
    # cleanest supersession chain: two documents that both look authoritative,
    # where only the newest is current and the older ones are still on the shelf.
    intent("close_calendar", "finance", "all_staff", roles["reporting_manager"],
           [episode.keys["fact_due_date"]], [episode.keys["event_close_started"]], "small",
           "The close calendar states the committed date every period.",
           supersedes=latest("close_calendar"))

    intent("finance_workbook", "finance", "finance", roles["reporting_manager"],
           detail + [episode.keys["fact_close_delay"]], [episode.close_event_id], "long",
           "The month-end model is the source artifact for the period and must reconcile.")

    intent("cfo_variance_memo", "finance", "group_cfo", roles["controller"],
           money + [episode.keys["fact_close_status_final"], episode.keys["fact_close_delay"]],
           [episode.close_event_id], "medium",
           "Variance commentary is produced for every close.")

    if episode.had_incident and not actor_authored:
        k = episode.keys
        intent("working_note", "finance", "finance", roles["controller"],
               [k["fact_feed_status"], k["fact_hypothesis"], k["fact_cause"], k["fact_close_delayed"]],
               [k["event_pipeline_failed"], k["event_close_delayed"]], "small",
               "The controller keeps a running note through a disrupted close.")

        # A status page is one persistent operational record — "known issue:
        # inventory valuation pipeline" — edited in place across occurrences,
        # unlike its ServiceNow neighbour below whose ticket number is minted
        # fresh every incident and can never be the same document twice. That
        # is what makes this the `revises` case rather than a new page each
        # period: the identity survives, only the content grows.
        #
        # It still never gains the confirmed cause. That omission is the
        # deliberate imperfection `generators/evaluation.py` builds a whole
        # family of authority-resolution cases against ("which record still
        # carries the initial hypothesis"), so a revision that fixed it would
        # retire the very thing it exists to test. What a later revision does
        # gain honestly is the running log: a "known issue" page does not
        # discard its own history, so each occurrence's entry is appended to
        # what the page already said, plus the recurrence link a first
        # occurrence has no way to know. That is what keeps the growth real
        # rather than a one-off bonus fact that stops a third revision from
        # citing more than the second did.
        #
        # Gated on an earlier page existing at all, not merely on there being
        # an incident this period: a world that has never run before has no
        # earlier page to revise, and minting one anyway would insert an extra
        # intent ahead of jira_issues, knowledge_article and executive_summary
        # and shift every id minted after it — exactly what would break
        # examples/grocery-close/narration.json, which is real prose keyed to
        # the ids a single-period build mints today. The author is the same
        # service-desk role every time; nothing here changes hands.
        stale_page = latest_intent("confluence_page")
        intent("confluence_page", "operations", "all_staff", roles["svc_desk"],
               list(stale_page.required_fact_ids if stale_page else [])
               + [k["fact_feed_status"], k["fact_incident_ref"], k["fact_hypothesis"]]
               + ([k["fact_recurrence"]] if stale_page else []),
               list(stale_page.triggered_by if stale_page else [])
               + [k["event_incident_opened"], k["event_hypothesis"]]
               + ([k["event_root_cause"]] if stale_page else []),
               "small",
               "A status page is raised at triage, before the cause is known. It goes stale.",
               revises=stale_page.id if stale_page else None)

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
               "A P2 incident that delayed the close warrants a reviewed RCA.",
               # Derived from, never superseding: an earlier review of an earlier
               # incident remains true about that incident. A recurrence builds on
               # it, and both stay current — which is exactly what makes "did the
               # remediation work" answerable.
               derived_from=[latest("incident_rca")])

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

    # ------------------------------------------------------------------
    # The fan-out block. Appended strictly after everything above, because
    # ART order is identity: the reference narration in examples/ cites the
    # ids the blocks above mint, and an intent inserted before them would
    # renumber every one. Anything added to this planner in future goes
    # below this comment, never above it.
    # ------------------------------------------------------------------

    # Per-unit close commentary: the finance business partner's page for each
    # division, citing only that unit's own headline facts. This is where the
    # corpus stops reporting the month exclusively from the centre — and it is
    # the fan-out that scales with the archetype rather than with this file.
    if density > 0.0:
        for unit_key in unit_keys:
            unit_id = roles[f"unit_{unit_key}"]
            unit_facts = [f.id for f in financial_facts if f.subject == unit_id]
            if not unit_facts:
                continue
            intent("unit_close_commentary", "finance", "finance", roles[f"{unit_key}_bp"],
                   unit_facts, [episode.close_event_id], "small",
                   "Each division's close is argued by the person who partners it, "
                   "not only summed by the centre.")

    # High-density fan-out: one layer below the unit, only once a build has
    # asked for it. A quarter of each unit's categories, ranked by revenue and
    # never fewer than one — enough to be a genuine second layer of reporting
    # on a large archetype (the Australian grocer's Food division alone has
    # thirteen categories; a thirty-category unit does not need thirty extra
    # documents for one knob step to make the point). The workbook already
    # carries every category fact regardless of this block running, so
    # skipping it changes what gets *argued*, never what is answerable.
    if eval_density > 1.0 and categories_by_unit:
        all_facts = workbook_facts or financial_facts
        revenue_of_category = {
            f.subject: f.value.amount
            for f in all_facts
            if f.kind == "financial.revenue.actual" and f.value is not None
        }
        for unit_key in unit_keys:
            unit_id = roles[f"unit_{unit_key}"]
            members = categories_by_unit.get(unit_id, [])
            if len(members) < 2:
                continue
            ranked = sorted(members, key=lambda cid: revenue_of_category.get(cid, 0), reverse=True)
            topn = max(1, len(ranked) // 4)
            for category_id in ranked[:topn]:
                category_facts = [
                    f.id for f in all_facts
                    if f.subject == category_id
                    and f.kind.startswith((
                        "financial.revenue.", "financial.gross_profit.",
                        "financial.gross_margin_pct.",
                    ))
                ]
                if not category_facts:
                    continue
                intent("unit_close_commentary", "finance", "finance", roles[f"{unit_key}_bp"],
                       category_facts, [episode.close_event_id], "small",
                       "At high density the same business partner also argues the "
                       "categories that moved the unit, not only its total.")

    if episode.had_incident and not actor_authored:
        k = episode.keys
        # The escalation meeting, minuted. Fully structured — attendees,
        # tabled material, decisions — so it costs the narration loop nothing
        # and still gives who-was-in-the-room questions a source document.
        intent("meeting_minutes", "finance", "finance", roles["controller"],
               [k["fact_cause"], k["fact_close_delayed"], k["fact_revised_date"],
                k["fact_workaround"], k["fact_close_delay"]],
               [k["event_close_delayed"]], "small",
               "The decision to move the close was taken in a meeting, and a meeting "
               "that moves a group commitment gets minutes.")

        # The escalation thread: one message per moment, each bounded to what
        # its sender knew then. The first report cannot name the cause,
        # because the cause was not a fact yet — the thread is the corpus's
        # cleanest record of knowledge arriving in order.
        intent("email_thread", "operations", "technology", roles["svc_desk"],
               [k["fact_feed_status"], k["fact_incident_ref"], k["fact_hypothesis"],
                k["fact_cause_ruled_out"], k["fact_cause"], k["fact_close_delayed"]],
               [k["event_incident_opened"], k["event_hypothesis"],
                k["event_root_cause"], k["event_close_delayed"]], "small",
               "The incident was escalated by email before any formal record existed; "
               "the thread is what people actually knew, when.")

    return tuple(intents)
