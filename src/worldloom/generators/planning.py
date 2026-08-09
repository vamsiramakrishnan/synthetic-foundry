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

from collections.abc import Mapping
from dataclasses import dataclass

from .. import documents
from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact
from ..roles import unit_role_key
from .operations import CloseEpisode


@dataclass(frozen=True)
class EstateReading:
    """What the technology landscape says about an incident's paperwork.

    Three integers, taken off the dependency graph by ``scenarios.
    _estate_reading``. Everything the filing gates below need and nothing else:
    a planner holding the graph itself would be a planner that could start
    deciding on any property of it, and the gates would stop being auditable.
    """

    scale: int
    """Services and systems in the estate."""

    incident_reach: int
    """How much falls over transitively with the feed that failed."""

    unowned_reach: int
    """How much rests transitively on the system holding the unowned mapping
    table — the component the remediation has to change."""


#: How many things must fall over with the failed feed before the incident
#: record stops being able to carry the answer.
#:
#: The engine's own landscapes read 1 (no estate), 6 (small), 14 (medium) and
#: 17 (large), so five is the line between an estate whose downstream is a
#: clause in the ServiceNow record's summary and one where "what else is on
#: this" is a piece of work somebody has to do and write up. Above the stock
#: nine-node estate by construction, which is what keeps a default build
#: planning exactly what it planned before this block existed.
IMPACT_ASSESSMENT_REACH = 5

#: How many things must read the unowned mapping table before the remediation's
#: scope stops being a sentence in the RCA.
#:
#: Same landscapes: 3, 14, 34, 71. Twenty sits between an estate where the RCA's
#: contributing-factors section can name every reader and one where it cannot,
#: and it is the *unowned* component's reach deliberately rather than the failed
#: feed's — ``ops.mapping_table_owner`` resolves to "unassigned", and the sharp
#: question this corpus poses is what a change to something nobody owns is
#: allowed to touch.
REMEDIATION_REVIEW_REACH = 20

#: How far above an average month a period must sit before the year is planned
#: around it.
#:
#: A tenth. Below that a month is a good month; above it the month is a fixture,
#: and "against plan" is the wrong frame on its own because the plan already
#: contains the season. Measured against the trading years the registry ships:
#: `flat` never reaches it, so a bank or an insurer never files one — the right
#: answer for a business whose revenue is a book rather than a till; the
#: engine's own retail year reaches it in December alone; `fiscal_year_end`
#: reaches it at all four quarter ends, which is what that profile *means*.
PEAK_TRADING_INDEX = 1.10

#: The services every retail world ships as episode props, estate or no estate.
#: The register documents an estate somebody *asked* to grow; a build with only
#: the four core services already names all of them in its incident documents,
#: and gating on this count is what keeps such a build planning exactly what it
#: planned before the register existed.
CORE_SERVICES = 4

#: The fact bundles a *declaratively authored* filing may ask for, and what each
#: one is (``documents.FilingPlan.facts``, ``worldloom.doctypes``).
#:
#: A closed vocabulary, and the closure is the point. The engine's own filings
#: name fact ids because they are written in this function and can see the ones
#: it computed; an authored type is JSON and cannot, so the choice on offer is
#: either fact *kinds* — which would let a document reach past the planner into
#: the ledger for figures no episode gave it — or the cuts this function has
#: already made. These are those cuts. A bundle that came out empty this episode
#: contributes nothing rather than naming a fact that does not exist, which is
#: the same discipline ``filings`` itself follows: lore states what the company
#: files, the episode states what there was to file it about.
#:
#: Values are the description ``worldloom pack targets``-style tooling prints;
#: the keys are the contract.
FILING_BUNDLES: dict[str, str] = {
    "headline": "the period's figures at group and unit level — what the"
                " variance memo argues over",
    "group": "the same figures, company subjects only — for a reader who is an"
             " owner rather than a manager",
    "close_status": "whether the books closed when they were promised, and by"
                    " how much they did not",
    "control_failure": "the classification of what went wrong and who owns the"
                       " component behind it; empty on a clean close, and"
                       " withheld under `--actors` for the reason the four"
                       " owner reports below withhold it",
}


#: Which role signs off each artifact type, by role key.
#:
#: The corpus's documents were all authored and none of them approved, which is
#: not how a company works and, more to the point, is not how a company's
#: *archive* works: "who approved the March pack for Fuel and Convenience" is a
#: question every real reader asks and no artifact here could answer.
#:
#: A closed table rather than "the author's manager", and the reason is that
#: approval is not a reporting line. A variance memo is signed by the CFO
#: because the CFO owns the number, not because the controller reports to them;
#: a remediation whose finding is an ownership gap is signed by the chief
#: executive rather than by the CIO whose team the gap is in, which is the same
#: argument `remediation_scope_review` already makes about who *writes* it.
#: Reading the two tables side by side is how a reader checks that argument.
#:
#: **Absence is a claim too.** A ServiceNow ticket has an assignee, an email
#: thread has a sender, a republished calendar is issued rather than approved,
#: a working note is nobody's but its writer's, and an executive summary *is*
#: the executive's own. Those types are missing from this table deliberately:
#: a corpus where everything carries a signature is as unlike a real archive as
#: one where nothing does.
#:
#: `member_report` is the interesting omission. A mutual's report to its
#: members is approved by the board, and this world has no board — inventing a
#: signature for it would put a name on a document nobody in the roster could
#: have signed.
_APPROVED_BY: dict[str, str] = {
    "finance_workbook": "controller",
    "cfo_variance_memo": "cfo",
    "meeting_minutes": "cfo",
    "incident_rca": "cio",
    "service_impact_assessment": "cio",
    "remediation_scope_review": "ceo",
    "peak_trading_review": "ceo",
    "audit_committee_pack": "ceo",
    "sponsor_pack": "ceo",
    "ministerial_brief": "ceo",
}


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
    accountability_facts: tuple[CanonicalFact, ...] = (),
    filings: Mapping[str, float] | None = None,
    estate: EstateReading | None = None,
    seasonal_index: float = 1.0,
    milestones: tuple[CanonicalFact, ...] = (),
    estate_services: int = 0,
    masterdata_rows: int = 0,
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

    ``filings``, ``estate`` and ``seasonal_index`` are what make the plan a
    function of *what kind of company this is* rather than of the episode
    alone. Until they existed, five deliberately-unlike companies filed the
    same thirteen artifact types in the same counts: the structure had
    diversified and the document set had not moved at all, which for a project
    whose product is the document set is the whole gap.

    Three different kinds of demand, and they are separate arguments rather
    than one knob:

    * **``filings``** is what the company *claims about who it answers to*,
      arriving as lore (``facets.FILING_PREFIX``) and therefore replaying off
      the recipe for free. A listed company's audit committee reads a pack; a
      fund-owned one's sponsor reads one every month; a mutual reports to its
      members; a state-owned one briefs a minister; a founder-led one minutes
      nothing, and that last is why the vocabulary is a signed magnitude rather
      than a set of names.
    * **``estate``** is what the company *runs*. A nine-node landscape's
      incident is understood by the people in the room. A hundred-node one's is
      not, and the difference shows up as documents — an impact assessment
      somebody has to write because nobody can hold the answer, and a scope
      review because a change to an unowned component that seventy things rest
      on is not a ticket.
    * **``seasonal_index``** is what the company *sells*, at this period. A
      month the year is planned around is reviewed on its own terms; the
      variance memo cannot do it, because "against plan" is the wrong frame
      when the plan already contains the season.

    Nothing here draws from an ``Rng``. Every gate is an integer or a float
    already fixed by the world, so this block adds no stream and reshuffles
    nothing downstream of one — and a default build passes ``filings=None``, no
    estate reading past the thresholds, and a March index of 0.97, so it plans
    exactly what it planned before. Verified by diff rather than asserted.
    """
    asked = dict(filings or {})

    def files(artifact_type: str, *, by_default: bool = False) -> bool:
        """Whether this company files documents of *artifact_type*.

        ``by_default`` is the planner's own half of the decision and does not
        belong in the lore: a summed adjustment of zero means the lore said
        nothing, which for the minutes of an escalation meeting means "still
        filed" and for a sponsor pack means "not filed". Which documents an
        episode produces unprompted is a statement about the episode; lore only
        ever moves it.
        """
        return (1.0 if by_default else 0.0) + asked.get(artifact_type, 0.0) > 0.0

    money = [f.id for f in financial_facts]
    detail = [f.id for f in (workbook_facts or financial_facts)]
    # Accountability facts establish who is responsible for which measures,
    # which the finance workbook needs to support evaluation questions about
    # who was accountable when a variance moved outside tolerance.
    acct = [f.id for f in accountability_facts]
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
               revises: str | None = None, approved_by: str | None = None) -> None:
        intents.append(
            ArtifactIntent(
                id=minter.next("ART"),
                artifact_type=artifact_type,
                domain=domain,
                audience=audience,
                author_id=author,
                approver_id=documents.approver_of(
                    roles, artifact_type, author, _APPROVED_BY, role_key=approved_by,
                ),
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
    # The calendar's second section — "Escalation: what happens when the date
    # moves, and where the period ended up" — asks for `close.revised_date`,
    # `close.status` and `close.delay`, and this intent carried the due date
    # alone. Measured across thirty-one calendars in thirteen builds: the
    # section fired zero times, so half of every close calendar's declared
    # outline had never been written. A standing document that states a
    # commitment and never states whether it was met is the document a reader
    # goes to first and learns nothing from.
    # The revision, and only the revision. The first attempt gave the calendar
    # the final status and the delay as well, and that is what a close calendar
    # is *not*: adding facts that are only true once the period has landed moved
    # the document's own date from the first morning of the close to the day
    # after it finished, and the corpus's earliest document — the one every
    # supersession chain hangs off — became a retrospective. The status and the
    # delay are reporting, and the CFO memo carries both. What belongs on a
    # timetable is the date, and the date it moved to.
    calendar_facts = [episode.keys["fact_due_date"]]
    if episode.had_incident:
        calendar_facts.append(episode.keys["fact_revised_date"])
    intent("close_calendar", "finance", "all_staff", roles["reporting_manager"],
           calendar_facts, [episode.keys["event_close_started"]], "small",
           "The close calendar states the committed date every period, and any revision to it.",
           supersedes=latest("close_calendar"))

    intent("finance_workbook", "finance", "finance", roles["reporting_manager"],
           detail + acct + [episode.keys["fact_close_delay"]], [episode.close_event_id], "long",
           "The month-end model is the source artifact for the period and must reconcile.")

    # Same defect, same shape: the memo's closing "Recommendation" section wants
    # the remediation, its classification and the owner of the control behind
    # it, and no `ops.*` fact was ever in the memo's required set — 0 of 31.
    # The section only makes sense in a period something went wrong in, so the
    # facts are added on the same gate the incident filings use rather than
    # unconditionally; in a clean month the plan finds nothing and the section
    # is correctly absent rather than permanently unreachable.
    memo_facts = money + [episode.keys["fact_close_status_final"], episode.keys["fact_close_delay"]]
    if episode.had_incident:
        memo_facts += [episode.keys["fact_remediation"], episode.keys["fact_classification"],
                       episode.keys["fact_owner"]]
    intent("cfo_variance_memo", "finance", "group_cfo", roles["controller"],
           memo_facts, [episode.close_event_id], "medium",
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
            intent("unit_close_commentary", "finance", "finance",
                   roles[unit_role_key(unit_key, "_bp")],
                   unit_facts, [episode.close_event_id], "small",
                   "Each division's close is argued by the person who partners it, "
                   "not only summed by the centre.",
                   # Signed by *this* division's managing director, which is the
                   # one approval in the corpus that fans out with the company:
                   # widen a retailer to eight divisions and eight different
                   # people sign eight different documents. `_APPROVED_BY` is a
                   # table keyed by type and has no way to say which one.
                   approved_by=unit_role_key(unit_key, "_md"))

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
                intent("unit_close_commentary", "finance", "finance",
                       roles[unit_role_key(unit_key, "_bp")],
                       category_facts, [episode.close_event_id], "small",
                       "At high density the same business partner also argues the "
                       "categories that moved the unit, not only its total.",
                       approved_by=unit_role_key(unit_key, "_md"))

    if episode.had_incident and not actor_authored:
        k = episode.keys
        # The escalation meeting, minuted. Fully structured — attendees,
        # tabled material, decisions — so it costs the narration loop nothing
        # and still gives who-was-in-the-room questions a source document.
        #
        # `by_default=True`, and it is the only filing in this planner that is:
        # a meeting that moves a group commitment gets minutes unless something
        # about this company says otherwise, which is a claim about the episode
        # rather than about the lore. What can say otherwise is
        # `governance:founder_led` — the decision is taken in the room and
        # nobody writes it down. The absence is evidence rather than a hole:
        # the close still moved and there is no document naming who was there,
        # which is a harder corpus than one where the meeting never happened.
        if files("meeting_minutes", by_default=True):
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
                k["fact_cause_ruled_out"], k["fact_cause"], k["fact_close_delayed"],
                # Appended, never inserted: the first three of this list that
                # land in a message's allowed set become its required facts
                # (`_request_for` caps required at three, in this order), and
                # the reference narration in examples/grocery-close cites
                # exactly those. What the two additions fund: the root-cause
                # message's own purpose quotes its event summary, which names
                # the unmapped-SKU count, and the escalation message announces
                # the close moving — both figures were quoted at the writer
                # while the facts carrying them sat only in other documents'
                # scopes, so the request demanded what it had withheld. The
                # realised delay in days is deliberately NOT added: it is only
                # measured when the close lands, days after this thread's
                # cut-off, and an allowed fact the author cannot cite without
                # tripping `not_yet_known` is a trap, not a widening.
                k["fact_affected"], k["fact_revised_date"]],
               [k["event_incident_opened"], k["event_hypothesis"],
                k["event_root_cause"], k["event_close_delayed"]], "small",
               "The incident was escalated by email before any formal record existed; "
               "the thread is what people actually knew, when.")

    # ------------------------------------------------------------------
    # The filing block: documents this *particular* company produces.
    #
    # Everything above is what a close produces. Everything below is what a
    # close produces *here* — because of who this company answers to, what it
    # runs, and where this month sits in its year. Appended last for the reason
    # stated further up: ART order is identity, and the reference narration in
    # examples/ cites the ids the blocks above mint.
    #
    # Every gate is false on a stock build, and that is checked by diff rather
    # than by assertion (`tests/test_filings.py`). It is also why the estate
    # thresholds are stated against the landscapes `--estate` actually
    # produces: a threshold picked to look round could sit under the stock
    # nine-node estate and renumber every corpus this project has shipped.
    # ------------------------------------------------------------------

    # -- what the company runs -----------------------------------------
    #
    # Withheld under `actor_authored` alongside the rest of the incident block
    # and for the same reason: these are documents employees would produce from
    # what they had observed, and the planner writing them from the whole
    # ledger is precisely what the actor layer exists to stop.
    if estate is not None and not actor_authored:
        k = episode.keys
        if estate.incident_reach >= IMPACT_ASSESSMENT_REACH:
            # The document that exists because nobody can hold the answer. In a
            # nine-node estate "what else is affected" is a sentence in the
            # ServiceNow record; past five downstream services it is a piece of
            # work, and it is the input to the decision about whether to wait
            # for the fix or run the workaround — so it is written while the
            # incident is open, by the person who owns the platform, and it is
            # a working document rather than a report.
            intent("service_impact_assessment", "operations", "technology",
                   roles["platform_lead"],
                   [k["fact_feed_status"], k["fact_affected"], k["fact_valuation_status"],
                    k["fact_workaround"], k["fact_cause"]],
                   [k["event_pipeline_failed"], k["event_root_cause"]], "medium",
                   "The estate is large enough that what the failure reaches is a "
                   "question somebody has to answer in writing rather than from memory.")

        if estate.unowned_reach >= REMEDIATION_REVIEW_REACH:
            # The remediation's blast radius, reviewed before it is approved.
            # `ops.mapping_table_owner` resolves to "unassigned", and where
            # twenty-odd things rest on the component nobody owns, "what is the
            # fix allowed to touch" stops being a line in the RCA. Authored by
            # the CIO rather than the platform lead who raised the tickets: the
            # finding is an ownership gap, and a review of it signed by the
            # person whose team would have to own it answers the wrong
            # question.
            intent("remediation_scope_review", "engineering", "technology",
                   roles["cio"],
                   [k["fact_cause"], k["fact_owner"], k["fact_remediation"],
                    k["fact_remediation_scope"], k["fact_recurrence"], k["fact_affected"]],
                   [k["event_control_failure"], k["event_remediation"]], "medium",
                   "A change to an unowned component that much of the estate rests on "
                   "is scoped and reviewed before it is approved.")

    # -- what the company sells, at this period -------------------------
    if seasonal_index >= PEAK_TRADING_INDEX and money:
        # Not a second variance memo. The memo reports the month against plan,
        # and against plan is the wrong frame on its own here because the plan
        # already contains the season — a division that beat budget in a month
        # the whole year is bought for may still have traded badly. Written by
        # the merchandising lead rather than by finance for the same reason:
        # the question is commercial, and it is the one document in the corpus
        # whose author buys things.
        intent("peak_trading_review", "strategy", "all_staff",
               roles["merch_lead"], money, [episode.close_event_id], "medium",
               "This month is one the year is planned around, so it is reviewed on "
               "the year's terms rather than only against its own budget.")

    # -- who the company answers to -------------------------------------
    #
    # Four documents, one per reporting line a facet can claim, in a fixed
    # order. They are four types rather than one addressed four ways because
    # `documents.standing` differs between them — an audit committee pack that
    # the committee has not read is not one — and because the outlines
    # partition the same month differently for each reader.
    #
    # **A note on `audience`, which is doing two jobs.** It names the reader for
    # the narrative request, and it selects an access policy through
    # `world._policy_for`. These used to carry the *access class*
    # (`executive_committee`) rather than the reader, because an unrecognised
    # audience fell through to whatever policy happened to be last in the tuple
    # — "Technology and service operations" in retail — and `audit_committee`
    # therefore locked the CFO out of the pack they wrote.
    #
    # `_policy_for` now has a row for each of these, so they name the reader and
    # still resolve to the access class that governs the document *inside* the
    # company. That distinction is the point and is worth stating: a policy
    # decides who here may open it, and these four readers are all *outside* the
    # org chart — an audit committee, a fund, a members' body, a minister — so
    # no `allow_functions` describes them and minting a policy each would put
    # four rows in `world.json` for every corpus ever built. Who receives it is
    # the filing's own business; who may open it is the policy's.
    #
    # `close_status` is the pair every one of them carries: whether the books
    # closed when they were promised, and by how much they did not. That is the
    # fact an owner reads for, whoever the owner is.
    close_status = [episode.keys["fact_close_status_final"], episode.keys["fact_close_delay"]]
    # The two facts an owner is owed and management would rather not send. Held
    # back under `actor_authored` as well as on a clean close, and the second
    # condition is the interesting one: whether the control failure reaches the
    # committee is a decision an employee takes, and the corpus's sharpest
    # existing finding is that the actor CFO's own summary leaves it out. A
    # planner that reinstated it here from the whole ledger would answer the
    # question the actor layer exists to ask.
    control_failure = (
        [episode.keys["fact_classification"], episode.keys["fact_owner"]]
        if episode.had_incident and not actor_authored else []
    )

    if files("audit_committee_pack"):
        # The committee's business is the integrity of the reporting process,
        # not the performance it reports — so the pack carries the close
        # timetable and the control failure, and the result only as the figure
        # the rest is held against. Signed by the CFO: the committee receives
        # management's account and then decides whether to believe it.
        intent("audit_committee_pack", "finance", "audit_committee", roles["cfo"],
               money + close_status + control_failure, [episode.close_event_id], "medium",
               "A listed company's audit committee reviews the numbers, and the "
               "control environment behind them, before the market sees either.")

    if files("sponsor_pack"):
        intent("sponsor_pack", "finance", "sponsor", roles["cfo"],
               money + close_status, [episode.close_event_id], "medium",
               "A fund with a hold period reads a pack every month and asks about "
               "every line.")

    if files("member_report"):
        # Group only. A mutual's members own the company and are not analysts:
        # the divisional attribution a sponsor demands is management detail
        # here, and including it would make this the sponsor pack with a
        # different cover — which is the failure four near-identical filings
        # would actually be.
        group = [f.id for f in financial_facts if f.subject.startswith("CO")]
        intent("member_report", "strategy", "members", roles["ceo"],
               group + close_status, [episode.close_event_id], "small",
               "A mutual reports to the people who own it, and stewardship rather "
               "than return is what the report is about.")

    if files("ministerial_brief"):
        # Everything, including what went wrong: this company minutes
        # everything because everything is discoverable, and a brief that
        # omitted the control failure would be the omission somebody later
        # finds. Signed by the accountability lead the facet mints, falling
        # back to the chief executive — `roles.get` rather than a literal
        # lookup because that role exists only when this facet was claimed, and
        # a build whose role table could not carry it (`cli`'s `unmet:`
        # channel) must still produce the brief rather than raise.
        author = roles.get("public_accountability") or roles["ceo"]
        group = [f.id for f in financial_facts if f.subject.startswith("CO")]
        intent("ministerial_brief", "strategy", "minister", author,
               group + close_status + control_failure, [episode.close_event_id], "small",
               "A government-owned company briefs its minister on the period, and the "
               "brief is itself discoverable.")

    # -- what an authored type says it is for ---------------------------
    #
    # Everything above names its artifact type in Python, which is right: those
    # choices — who signs a sponsor pack, which facts an audit committee is
    # owed — are arguments about the episode, and an argument belongs in code.
    # What that shape cannot do is let a *model* add a document type, because
    # every one of the thirty this engine declares needs a call written here
    # before any company can file it.
    #
    # So the loop below plans the types whose four choices are data
    # (`documents.FilingPlan`, authored through `worldloom.doctypes` and
    # carried in a pack). The gate is unchanged — `files()` reads the same
    # summed lore adjustment, and a type nothing asked for is not planned — and
    # `filing_plan` returns None for every type declared by a module, so each of
    # the filings above is skipped here rather than planned twice.
    #
    # A no-op on every build that loads no authored type, which is every build
    # this repository ships: `asked` is empty without lore at
    # `facets.FILING_PREFIX`, and each of the five keys the shipped facets do
    # put there plans itself above. Verified by diff, not by assertion.
    from .. import documents as documents_module

    bundles = {
        "headline": money,
        "group": [f.id for f in financial_facts if f.subject.startswith("CO")],
        "close_status": close_status,
        "control_failure": control_failure,
    }
    # Sorted, because `asked` is built by summing over lore and two commitments
    # naming two types must not put them in the plan in whichever order the
    # world's lore happened to be minted. ART ids are identity.
    for artifact_type in sorted(asked):
        plan = documents_module.filing_plan(artifact_type)
        if plan is None or not files(artifact_type):
            continue
        # `or` down the chain rather than `roles[...]`, the same shape the
        # ministerial brief uses: an author role that exists only when some
        # facet was claimed must not raise in a build where it was not.
        author = (
            roles.get(plan.author_role)
            or roles.get(plan.fallback_role)
            or roles.get("ceo")
        )
        if author is None:
            continue
        cited: list[str] = []
        for bundle in plan.facts:
            for fact_id in bundles.get(bundle, ()):
                if fact_id not in cited:
                    cited.append(fact_id)
        # `written_at` derives a document's date from the newest fact it cites,
        # so an intent citing nothing has no date and raises there. A bundle
        # this episode left empty — the control failure on a clean close — is a
        # legitimate reason for that, and the honest answer is that the company
        # had nothing to file rather than a document about nothing.
        if not cited:
            continue
        intent(artifact_type, plan.domain, plan.audience, author,
               cited, [episode.close_event_id], plan.size, plan.rationale)

    # The company timeline — planned by the first episode that runs, and never
    # again. The `MFACT-` milestone facts have existed since the org builder
    # did, and until this intent nothing carried them: five facts per world,
    # in no document, with the `milestone_provenance` evaluation family
    # correctly refusing to ask about any of them. Planned last so its `ART`
    # id lands after every id an existing narration ledger already cites, and
    # with no trigger event: the page predates every close (its date derives
    # from the newest milestone it cites) and pinning it to this episode's
    # start event would claim the close caused the company's history.
    if latest("company_timeline") is None:
        dated = sorted(f.id for f in milestones if f.kind == "lore.milestone")
        if dated:
            intent("company_timeline", "governance", "all_staff",
                   roles["reporting_manager"], dated, [], "small",
                   "Every intranet has the page the onboarding pack links to: "
                   "what happened, dated, before anyone currently arguing about "
                   "it was in the room.")

    # The two standing extracts, on the same once-only rule as the timeline
    # and appended after it for the same id-stability reason. Each is gated on
    # the thing it projects actually existing: the register on an estate the
    # `--estate` generator grew (the four core props are already named by every
    # incident document, and a four-row register would add a page without
    # adding reach), the reference extract on `--master-data` having minted
    # anything. Both cite the close's committed date — an extract is cut *for*
    # a close, and an intent citing nothing has no date.
    if latest("service_register") is None and estate_services > CORE_SERVICES:
        # The CIO's document where the world has a CIO; the reporting manager's
        # where it does not — same `or`-chain shape as the filings above, so a
        # shape without the role gets the register rather than a KeyError.
        intent("service_register", "operations", "all_staff",
               roles.get("cio") or roles["reporting_manager"],
               [episode.keys["fact_due_date"]], [], "medium",
               "The CMDB, as a page: what runs, on what, owned by whom — the "
               "inventory every impact question starts from.")
    if latest("reference_data_extract") is None and masterdata_rows:
        intent("reference_data_extract", "finance", "finance",
               roles["reporting_manager"], [episode.keys["fact_due_date"]], [], "long",
               "The ERP's vendor, customer and item masters, extracted — the "
               "join surface transactional documents point into.")

    return tuple(intents)
