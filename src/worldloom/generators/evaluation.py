"""The evaluation taxonomy.

An evaluation case is a question whose answer is *read* out of the fact ledger,
never authored. That is the property that makes the set trustworthy, and it is
the reason this module derives everything — including which artifacts are the
right sources and which are the tempting wrong ones.

Two things make a case worth having, and only one of them is correctness:

**It must be answerable.** Every expected fact has to be carried by an artifact
the corpus actually renders, or the question is unanswerable and measures
nothing.

**It must be hard in a stated way.** A question a keyword baseline answers is not
testing retrieval, it is testing that the corpus is coherent — which ``validate``
already covers. So the families below are organised by the capability each one
demands: knowing *when* a document was written, knowing which of two sources is
the record, knowing when the corpus is silent.

``distractor_artifact_ids`` is the field that does most of that work. A stale
status page that confidently states a cause later ruled out is the most
instructive wrong answer in the corpus, and a case that does not name it is not
really testing authority resolution.

``density`` (``_Taxonomy``'s and ``evaluation_cases``'s, not ``planning.py``'s
lore-driven artifact ``density``, a different knob despite the name) is how a
build asks for more than the fixed set every close always produces, once the
world actually has more to ask about. It defaults to ``1.0``, at which every
family below emits exactly what it always has — the byte-identity a stock
build depends on. Above ``1.0`` two things happen, both already latent in data
this module always received but never fully used: ``Subjects.sites_by_unit``
was populated by every caller and read by none, so a large archetype's store
estate could not make the benchmark any harder than a small one's; and
``across_episodes`` only ever looked at the *most recent* prior period, so a
five-period build asked the same "prior period" question a two-period build
did. Density does not touch the hard families — incident, authority, causal —
because padding a fixed-size, already-hard family with easy rephrasings would
lower its average difficulty, not test the corpus at scale.

``estate`` is the other axis, and it was added for a measurement rather than
for a wish. ``evaluate/across.survey`` over a five-world mosaic reported **210
questions, 42 distinct, all 42 byte-identical in all five worlds** — a
five-corpus benchmark that is one benchmark with five answer keys. The mosaic
was doing its job: it handed the taxonomy five structurally unlike companies,
one of them running 101 services with 18 chokepoints and two of them running
the episode's nine-node prop list. This module asked all five the same
questions, because every family here fills its templates from unit and category
names — which a mosaic does not vary — and no family read the estate at all,
even though ``graphs.py`` could have told it everything. ``estate_shape`` is the
three questions only the graph can answer, and four questions in ``incident``
say which estate they are being asked of, because "why was the close delayed"
asked of four candidate services and asked of a hundred are not the same
question. Silent, to the byte, in a world whose estate is the prop list.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact, EvaluationCase, EvaluationType
from . import episode_text
from .cases import CaseBuilder, adverse as _adverse, answerable, fmt as _fmt
from .operations import CloseEpisode
from .org_builder import ACCOUNTABILITY_KIND

#: The retail taxonomy's surface text: every question and expected answer it
#: asks, keyed so a pack can re-voice the benchmark the way `operations.TEXT`
#: lets it re-voice the episode (see `generators/episode_text`) — the fix for
#: a pack-built insurer whose evaluation set still asked about "merchandise
#: category" and "stores" no matter how thoroughly the episode itself had
#: been re-voiced. Defaults are the strings this taxonomy always used,
#: extracted verbatim, so stock evaluation sets are byte-identical whether or
#: not this table exists.
#:
#: Reasoning strings are deliberately not here: they exist for a human
#: reading the corpus afterwards, never for the retriever under test, so
#: re-voicing them would not change what is measured — only entertain the
#: reader. What each key below covers is exactly what the evaluator sees:
#: the question and the answer it is graded against. Where an original answer
#: was a bare fact value with no authored prose around it (`_fmt(fact)`,
#: `hypothesis.text_value`, a computed date) there is deliberately no key —
#: the same "machine values stay out of the template surface" rule
#: `episode_text` states, extended to facts read straight off the ledger.
EVAL_TEXT: dict[str, str] = {
    # -- direct lookup ------------------------------------------------------
    "q.direct.group_revenue": "What was total revenue for {period}?",
    "a.direct.group_revenue": "{value}",
    "q.direct.group_gross_profit": "What was group gross profit for {period}?",
    "a.direct.group_gross_profit": "{value}",
    "q.direct.group_gross_margin": "What was the group gross margin for {period}?",
    "a.direct.group_gross_margin": "{value}",
    "q.direct.unit_revenue": "What revenue did {name} report for {period}?",
    "a.direct.unit_revenue": "{value}",
    "q.direct.category_revenue":
        "What revenue did the {category} category in {unit} report for {period}?",
    "a.direct.category_revenue": "{value}",
    "q.direct.site_revenue": "What revenue did {site} in {unit} report for {period}?",
    "a.direct.site_revenue": "{value}",
    # -- numerical comparison -------------------------------------------------
    "q.numerical.revenue_vs_budget":
        "By how much did revenue miss budget in {period}, in absolute terms and as"
        " a percentage?",
    "a.numerical.revenue_vs_budget": "{adverse}, or {pct:.2f}%.",
    "q.numerical.worst_unit_variance":
        "Which business unit carried the {superlative} adverse {label} variance"
        " in {period}?",
    "a.numerical.worst_unit_variance": "{name}, at {value}.",
    "q.numerical.worst_category":
        "Which merchandise category lost the most gross profit against plan in {period}?",
    "a.numerical.worst_category": "{name}, at {value}.",
    "q.numerical.worst_site_variance":
        "Which site carried the largest adverse revenue variance in {period}?",
    "a.numerical.worst_site_variance": "{name}, at {value}.",
    "q.numerical.best_category":
        "Which merchandise category held up best against plan on gross profit in {period}?",
    "a.numerical.best_category": "{name}, at {value}.",
    "q.numerical.thinnest_margin_category":
        "Which category traded on the thinnest gross margin in {period}?",
    "a.numerical.thinnest_margin_category": "{name}, at {value}.",
    "q.numerical.category_reconciliation":
        "Do the category revenues for {unit} sum to the divisional total in {period}?",
    "a.numerical.category_reconciliation": "Yes — the categories sum exactly to the division.",
    "q.numerical.unit_group_reconciliation":
        "Does gross profit variance reconcile between the units and the group for {period}?",
    "a.numerical.unit_group_reconciliation": "Yes — the unit variances sum to the group variance.",
    # -- incident: causal chains ----------------------------------------------
    "q.incident.why_delayed": "Why was the {period} close delayed?",
    "a.incident.why_delayed":
        "{cause}, which stopped valuation and pushed the close by {days} business day(s).",
    "q.incident.undetected":
        "What allowed the valuation failure to reach production undetected?",
    "a.incident.undetected":
        "The mapping table has no registered owner and no required reviewer, so no"
        " control would have caught it.",
    "q.incident.recurrence":
        "Has this failure happened before, and did the earlier response prevent it?",
    "a.incident.recurrence":
        "Yes — a comparable valuation failure was traced to the same mapping table, and"
        " the response restored service without assigning ownership.",
    # -- incident: temporal state ----------------------------------------------
    "q.incident.hypothesis_at_time":
        "At the time triage first recorded a cause, what was believed to be the cause?",
    "q.incident.expected_on_time":
        "Before the incident was closed, was the close still expected to meet its"
        " committed date?",
    "a.incident.expected_on_time": "No — the close was recorded as delayed at that point.",
    "q.incident.status_at_finalised": "What was the close status once the period was finalised?",
    # -- incident: authority ---------------------------------------------------
    "q.authority.confirmed_cause": "What is the confirmed root cause of the valuation failure?",
    "q.authority.stale_record":
        "Which record still carries the initial hypothesis rather than the confirmed cause?",
    "a.authority.stale_record":
        "The triage status page, which was never updated after the hypothesis was ruled out.",
    "q.authority.close_status_source":
        "Which source was authoritative for the close status at the end of the period?",
    "a.authority.close_status_source":
        "The finance system of record, reporting the close as {status}.",
    # -- incident: citation and cross-artifact ----------------------------------
    "q.citation.mapping_owner": "Who owns the product hierarchy mapping table?",
    "a.citation.mapping_owner": "Nobody — the owner is unassigned.",
    "q.citation.evidence_ruled_out":
        "What evidence ruled out the initial explanation, and where is it recorded?",
    "q.citation.affected_records":
        "How many records were affected, and which document states it?",
    "a.citation.affected_records": "{value}",
    "q.cross.remediation_choice":
        "Which remediation addresses the underlying control failure rather than only"
        " detection?",
    "a.cross.remediation_choice":
        "The ownership assignment. The validation ticket addresses detection only.",
    "q.cross.pl_impact": "What was the P&L impact of the incident on the {period} result?",
    "a.cross.pl_impact":
        "Zero — valuation completed before the ledger closed. The impact was on the"
        " calendar only.",
    # -- across episodes ---------------------------------------------------------
    "q.across.current_calendar":
        "Which close calendar states the committed date currently in force?",
    "a.across.current_calendar": "The calendar published for {period}, committing to {date}.",
    "q.across.recurrence":
        "When did a comparable valuation failure last occur, and did the response"
        " prevent it recurring?",
    "a.across.recurrence":
        "In {prior_period}. It did not — the same mapping table failed again in"
        " {period}, and ownership is still unassigned.",
    "q.across.incident_count":
        "How many valuation incidents has the group opened up to and including {period}?",
    "a.across.incident_count": "{count}.",
    "q.across.prior_period_revenue": "What was total revenue in {period}?",
    "a.across.prior_period_revenue": "{value}",
    # -- abstentions ---------------------------------------------------------
    "q.abstain.previous_close_cause":
        "What was the root cause of the previous period's close delay?",
    "q.abstain.ceo_remuneration":
        "What is the Group Chief Executive Officer's total remuneration?",
    "q.abstain.supplier_shortfall":
        "Which supplier was responsible for the shortfall in fresh produce?",
    "q.abstain.nps": "What was the group's net promoter score this period?",
    "q.abstain.staff_costs": "How much did the group spend on staff costs this period?",
    "q.abstain.market_share": "What is the group's market share against its nearest competitor?",
    "q.abstain.next_audit": "When is the next scheduled audit of the mapping table?",
    # -- history ---------------------------------------------------------------
    "q.history.unit_leader_as_of": "Who led {unit} as of {period}?",
    "q.history.succession": "Who replaced {person} when they left the company?",
    "q.history.milestone_provenance":
        "According to the corpus's own history, when did this happen: {assertion}?",
    "q.history.signed_earlier": "Who signed the {doc_type} for {period}?",
    "q.history.signed_current": "Who signed the {doc_type} for {period}?",
    # -- approvals ---------------------------------------------------------------
    "q.approval.who_approved": "Who approved the {doc_type} for {period}?",
    "q.approval.who_approved_unit":
        "The {unit} close commentary for {period} was prepared by one person and"
        " approved by another. Who approved it?",
    "q.approval.who_prepared_unit":
        "Who prepared the {unit} close commentary for {period}?",
    "q.abstain.unapproved": "Who approved the {doc_type} for {period}?",
    # -- standing documents ------------------------------------------------------
    "q.policy.superseded":
        "What was the {provision} under the expense policy in force before the"
        " current version?",
    "q.policy.owner": "Who approved the {title}?",
    # -- the workforce rounds ----------------------------------------------------
    "q.people.requisition_level":
        "The vacancy {manager} raised committed {amount}. Which level of the"
        " delegation of authority did that require?",
    "q.people.rating": "What rating did {person} receive for {period}?",
    "q.people.held_view":
        "Two records give {person} a different rating for {period}. Which is the"
        " signed one, and what does it say?",
    "q.abstain.cmo":
        "Who is the company's Chief Marketing Officer, and when did they join?",
    "q.abstain.close_calendar_1995": "Who signed the close calendar in 1995?",
    # -- communications ----------------------------------------------------------
    "q.comms.meeting_attendance_cause":
        "Who attended the meeting that moved the close, and what did the minutes"
        " record as the cause?",
    "a.comms.meeting_attendance_cause":
        "The Group Financial Controller and the Group Chief Financial Officer; the"
        " minutes record: {cause}.",
    "q.comms.cfo_notified":
        "When was the Group CFO first told the close was at risk, and through what"
        " channel?",
    "a.comms.cfo_notified":
        "By email, within the hour of the close being recorded as delayed on"
        " {date} — before any formal report existed.",
    # -- accountability ---------------------------------------------------------
    "q.accountability.who_accountable":
        "Who was accountable for {unit}'s {measure} in {period}, given that it moved"
        " beyond the band they are held to?",
    "a.accountability.who_accountable": "{person}.",
    # -- the estate, read as a graph ---------------------------------------------
    #
    # Empty in every world whose estate is the episode's own prop list — see
    # `_Taxonomy._read_estate` for the gate and why it is where it is.
    "q.estate.blast_radius":
        "Of the {scale} this company runs, would a failure in {service} have reached"
        " {name}?",
    "a.estate.blast_radius":
        "Yes — {name} depends on it, directly or through something else, and {count}"
        " things do in total.",
    "q.estate.routed_around":
        "Is {service} the only way anything reaches {system}, or does the estate"
        " route around it?",
    "a.estate.routed_around":
        "It routes around — {count} other service(s) reach {system} without it. What"
        " nothing routes around is {names}.",
    "q.estate.chain_to_record":
        "How deep is the longest chain of services that ends at {system}, and what"
        " sits at the top of it?",
    "a.estate.chain_to_record": "{hops} hops, with {name} at the top.",
    "q.estate.abstain_recovery":
        "Which of the {scale} this company runs has a tested disaster-recovery"
        " failover for {system}?",
    # -- estate-scaled restatements of the incident families ----------------------
    #
    # The same questions the no-estate world asks, re-anchored on what this
    # world actually has. See `_Taxonomy.estate` on why these are gated rather
    # than unconditional.
    "q.incident.why_delayed.estate":
        "Of the {scale} this company runs, which one's failure delayed the {period}"
        " close, and how?",
    "q.incident.undetected.estate":
        "The mapping table sits under {system}, which {reach} service(s) depend on."
        " What allowed the valuation failure to reach production undetected?",
    "q.authority.confirmed_cause.estate":
        "Across the {scale} in this estate, what is the confirmed root cause of the"
        " valuation failure?",
    "q.citation.mapping_owner.estate":
        "Who owns the product hierarchy mapping table held in {system}?",
}


@dataclass(frozen=True)
class Subjects:
    """What the taxonomy needs in order to name and rank what it asks about."""

    company_id: str
    unit_ids: dict[str, str]
    names: dict[str, str]
    categories_by_unit: dict[str, list[str]]
    sites_by_unit: dict[str, list[str]]
    unit_by_person: dict[str, str] = field(default_factory=dict)
    """Which business unit a person belongs to, for the people who belong to one.

    Needed because an accountability fact's subject is a *person* and a
    variance fact's subject is a *business unit*, so a question joining the two
    has to know which unit the accountable person answers for. Without it the
    join is unconstrained and names whoever holds an accountability as
    answerable for every unit's miss — a case that asserts something false, in
    a corpus whose whole premise is that its documents agree.

    Defaulted so that a caller building a `Subjects` for a taxonomy that asks
    no person-scoped question does not have to supply one."""

    def name(self, subject_id: str) -> str:
        return self.names.get(subject_id, subject_id)


#: How many things must transitively depend on the service the incident ran
#: through before the estate families are worth asking.
#:
#: Two, not three, is what the episode's own prop list gives: the valuation job
#: reads the hierarchy sync and the close orchestrator waits on the valuation
#: job, and the RCA says both of those in so many words. A *third* dependent is
#: the first one no document in the corpus mentions — which is the whole reason
#: to consult the graph rather than the prose. So the gate is not "does this
#: world have an estate" (a flag the taxonomy is not handed and would have to
#: be plumbed as one more thing to keep in sync); it is "does the graph know
#: something the documents do not", measured, which is the property the
#: families actually depend on.
ESTATE_REACH_MINIMUM = 3


@dataclass(frozen=True)
class _EstateReading:
    """One world's dependency graph, read once, for the families below.

    Every field is an exact count or an id sequence for the same reason
    ``graphs.py`` states: an evaluation set regenerates byte-for-byte, so a
    ranking that depends on set iteration order or on a float is a ranking that
    can differ between machines. Ties break on the node id at the point of
    sorting, here as there.
    """

    service: str
    """The service the incident ran through — the mapping sync."""
    system: str
    """The system of record under it, whose mapping table has no owner."""
    scale: int
    """Services and systems in the estate, together. Both, because a dependency
    that stopped at the system boundary would miss two services whose only
    relationship is the record they both read (`graphs.dependency_graph`)."""
    reach: tuple[str, ...]
    """What transitively depends on ``service``, largest blast radius first."""
    chokepoints: tuple[tuple[str, int], ...]
    """What nothing routes around, and how much each one gates."""
    detour: int
    """How many things still reach ``system`` with ``service`` removed. Zero
    means the mapping sync is itself the single point of failure."""
    chain: tuple[str, ...]
    """The longest chain of services ending at ``system``."""


class _Taxonomy:
    """Builds the case set for one episode."""

    def __init__(
        self,
        minter: Minter,
        *,
        episode: CloseEpisode,
        facts: tuple[CanonicalFact, ...],
        subjects: Subjects,
        intents: tuple[ArtifactIntent, ...],
        period: str,
        history: tuple[CanonicalFact, ...] = (),
        prior_intents: tuple[ArtifactIntent, ...] = (),
        text: Mapping[str, str] = EVAL_TEXT,
        density: float = 1.0,
        estate: Any = None,
    ) -> None:
        self.minter = minter
        self.episode = episode
        self.subjects = subjects
        self.period = period
        # See the module docstring: 1.0 reproduces every family's historical
        # count exactly; only the families below that check it can differ.
        self.density = density
        # Already merged with any pack override by the caller — see
        # `evaluation_cases`. Stored as `self.text` rather than merged again
        # here, so the lint-time contract (`episode_text.merged` raises once,
        # naming the bad key) is enforced exactly once per build.
        self.text = text
        # The builder owns minting; `self.cases` is the same list, so the
        # family methods and the final gate read one accumulator.
        self._build = CaseBuilder(minter)
        self.cases = self._build.cases

        self.by_kind: dict[tuple[str, str], CanonicalFact] = {}
        for fact in facts:
            if fact.is_superseded or (fact.period not in (None, period)):
                continue
            self.by_kind.setdefault((fact.kind, fact.subject), fact)
        for fact in episode.facts:
            if not fact.is_superseded:
                self.by_kind[(fact.kind, fact.subject)] = fact

        self.artifact = {intent.artifact_type: intent.id for intent in intents}
        self.intents = intents
        self.history = history
        self.prior_intents = prior_intents

        # A single id-keyed index across every fact this episode can see, for
        # the new families below that need to look a fact up by id rather than
        # by (kind, subject) — `org.unit_leader_changed` and `lore.milestone`
        # both key on an id (a unit, the company) that repeats across many
        # facts, which is exactly what `by_kind`'s per-subject dedup discards.
        self._fact_index: dict[str, CanonicalFact] = {
            f.id: f for f in (*history, *facts, *episode.facts)
        }

        # Read once, in the constructor, because two different things consult
        # it: the estate families below, and the incident families, which
        # re-anchor their *questions* on the estate when there is one. Reading
        # it twice would be two chances for the two to disagree about whether
        # this world has an estate at all.
        self._estate_graph = estate
        self.estate = self._read_estate()

    # -- helpers -----------------------------------------------------------

    def case(
        self,
        question: str,
        kind: EvaluationType,
        answer: str,
        facts: list[str],
        *,
        cutoff: datetime | None = None,
        difficulty: str = "medium",
        reasoning: str = "",
        sources: list[str] | None = None,
        distractors: list[str] | None = None,
    ) -> None:
        self._build.case(
            question, kind, answer, facts,
            cutoff=cutoff, difficulty=difficulty, reasoning=reasoning,
            sources=sources, distractors=distractors,
        )

    def abstain(self, question: str, reasoning: str) -> None:
        self._build.abstain(question, reasoning)

    def t(self, key: str, **slots: object) -> str:
        """Render one `EVAL_TEXT` entry — the question or answer surface a
        pack re-voices, filled with whatever this case computed."""
        return self.text[key].format(**slots)

    def get(self, kind: str, subject: str) -> CanonicalFact | None:
        return self.by_kind.get((kind, subject))

    def ranked(self, kind: str, subjects: list[str]) -> list[CanonicalFact]:
        """Facts of one kind over many subjects, worst value first.

        Ranking is how a case becomes interesting without being arbitrary: "the
        category that lost the most margin" is a question with one answer the
        corpus can defend, where "category seventeen" is a question nobody asks.
        """
        found = [f for s in subjects if (f := self.get(kind, s)) is not None and f.value]
        return sorted(found, key=lambda f: f.value.amount)

    def _facts_of(self, kind: str) -> tuple[CanonicalFact, ...]:
        """Every current fact of *kind*, in the order the world minted them.

        For history: a personnel change or a founding milestone is one fact
        per event, not per subject the way `by_kind` assumes — a unit can
        change leader more than once, and every dated lore commitment shares
        the same subject (the company). `by_kind`'s ``setdefault`` would keep
        only the first of each and silently drop the rest, so this reads the
        accumulated history directly instead of going through it.
        """
        return tuple(f for f in self.history if f.kind == kind and not f.is_superseded)

    def _reachable_fact_ids(self) -> frozenset[str]:
        """Every fact id some planned artifact actually requires.

        The shared ``cases.reachable_fact_ids``, over this episode's intents
        and everything planned before it. A fact no ``ArtifactIntent``
        requires can never be rendered into anything a retriever could find,
        so a case built on it is unanswerable rather than merely hard. That
        matters here specifically because a personnel change or a founding
        milestone is witnessed by a ``CanonicalFact`` the moment it happens,
        but nothing today plans a document that requires one:
        ``Hire``/``Departure``/``Reorganisation`` extend the roster and the
        fact ledger without ever minting an ``ArtifactIntent``, and the
        founding facts are never in any intent's ``required_fact_ids`` either.
        The event occurring and the event being citable are two different
        facts, and only the second makes a question answerable — so the
        families below check this before ever asking one, the same guard
        ``incident()`` applies to "did an incident happen" at the top of this
        class.
        """
        from .cases import reachable_fact_ids

        return reachable_fact_ids(self.prior_intents, self.intents)

    def _read_estate(self) -> _EstateReading | None:
        """This world's estate, measured — or ``None`` when there is nothing to ask.

        Three conditions, and each one is a case that would otherwise be minted
        and then be worthless:

        **There has to be an incident.** Not because a graph question needs one
        logically, but because of the trap ``cases.answerable`` exists for: the
        generated estate carries no facts of its own. `estate.generate` mints
        `Service` and `System` entities and nothing else, so *no artifact
        requires a fact whose subject is a generated node*, and a case grounded
        on one would be dropped — or worse, a case grounded on nothing at all
        would survive `answerable` (an empty expected-fact set is trivially
        reachable) and then pass `score._covers` for free, inflating the
        scorecard with questions nobody answered. The incident's facts are the
        only ones in the corpus whose subject is a service at all, so they are
        the only honest anchor a graph question has. Each family below cites
        the ones that are actually about the entity it asks about.

        **The graph has to reach past the episode.** See
        ``ESTATE_REACH_MINIMUM``.

        **The two anchors have to be in the graph.** A composed estate that
        renamed them, or a vertical whose episode names no service, gets no
        estate families rather than a case about a node that is not there.
        """
        graph = self._estate_graph
        if graph is None or not self.episode.had_incident:
            return None

        from .. import graphs

        keys = self.episode.keys
        by_id = {fact.id: fact for fact in self.episode.facts}
        # Derived from the facts rather than from a hardcoded id: the mapping
        # sync is whatever the control failure was classified against, and the
        # system of record is whatever carries the unowned mapping table. A
        # re-voiced or composed episode moves those ids; it does not move what
        # they mean.
        service = by_id[keys["fact_classification"]].subject
        system = by_id[keys["fact_owner"]].subject
        if service not in graph or system not in graph:
            return None

        reach = graphs.blast_radius(graph, service)
        if len(reach) < ESTATE_REACH_MINIMUM:
            return None

        # Largest blast radius first, ties on the id — the same ranking rule
        # `graphs.ServiceRank.key` states, for the same reason.
        ranked = tuple(sorted(
            reach, key=lambda node: (-len(graphs.blast_radius(graph, node)), node)
        ))

        without = graph.copy()
        without.remove_node(service)
        detour = len(graphs.blast_radius(without, system))

        # The chain is taken over the ancestors of the system of record, not
        # over the whole estate. "The longest chain in the estate" is a fact
        # about a landscape; "the longest chain that ends at the unowned
        # mapping table" is a fact about *this incident*, and it is the one the
        # cited facts are actually evidence for.
        upstream = graph.subgraph([system, *sorted(graphs.blast_radius(graph, system))])
        chain = graphs.longest_chain(upstream)

        return _EstateReading(
            service=service,
            system=system,
            scale=graph.number_of_nodes(),
            reach=ranked,
            chokepoints=graphs.chokepoints(graph),
            detour=detour,
            chain=chain,
        )

    @property
    def _scale(self) -> str:
        """The estate's size, as the question's own words for its search space."""
        return f"{self.estate.scale} services and systems" if self.estate else ""

    # -- families ----------------------------------------------------------

    def direct_lookup(self) -> None:
        """One fact, one document. The floor — a baseline should pass these."""
        company = self.subjects.company_id
        for kind, qkey, akey in (
            ("financial.revenue.actual", "q.direct.group_revenue", "a.direct.group_revenue"),
            ("financial.gross_profit.actual",
             "q.direct.group_gross_profit", "a.direct.group_gross_profit"),
            ("financial.gross_margin_pct.actual",
             "q.direct.group_gross_margin", "a.direct.group_gross_margin"),
        ):
            fact = self.get(kind, company)
            if fact:
                self.case(
                    self.t(qkey, period=self.period), EvaluationType.DIRECT_LOOKUP,
                    self.t(akey, value=_fmt(fact)), [fact.id], difficulty="easy",
                    reasoning="Single lookup against the system of record.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        for unit_id in self.subjects.unit_ids.values():
            fact = self.get("financial.revenue.actual", unit_id)
            if fact:
                self.case(
                    self.t("q.direct.unit_revenue", name=self.subjects.name(unit_id),
                           period=self.period),
                    EvaluationType.DIRECT_LOOKUP,
                    self.t("a.direct.unit_revenue", value=_fmt(fact)), [fact.id], difficulty="easy",
                    reasoning="Divisional lookup; the group figure is the tempting wrong answer.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        # Category and store lookups exist because the corpus reports at those
        # levels and nothing was asking about them. Chosen by rank rather than at
        # random: the largest category is a thing someone would ask about.
        #
        # `topn` reads as 1 at the default density (today's behaviour, exactly:
        # only the single biggest category) and grows with the knob — `round`
        # rather than a hardcoded per-tier table so a future numeric density
        # between the CLI's named tiers degrades gracefully instead of falling
        # through to whichever tier's branch happened to be written.
        for unit_id, members in self.subjects.categories_by_unit.items():
            ranked = self.ranked("financial.revenue.actual", members)
            topn = max(1, min(len(ranked), round(self.density)))
            for biggest in reversed(ranked[-topn:]) if len(ranked) >= 2 else ():
                self.case(
                    self.t("q.direct.category_revenue",
                           category=self.subjects.name(biggest.subject),
                           unit=self.subjects.name(unit_id), period=self.period),
                    EvaluationType.DIRECT_LOOKUP,
                    self.t("a.direct.category_revenue", value=_fmt(biggest)), [biggest.id],
                    reasoning="Requires reading below divisional level.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        # Store-level lookups only start existing above the default density.
        # `sites_by_unit` has been on `Subjects` since it was introduced and no
        # family here ever read it — a large archetype's estate (~1,300 stores
        # for the Australian grocer, versus a handful for the mid-size
        # retailer) could not make the benchmark any harder than a small one's,
        # which is exactly the toy-sized-regardless-of-world-size gap this
        # knob exists to close.
        if self.density > 1.0:
            for unit_id, site_ids in self.subjects.sites_by_unit.items():
                ranked_sites = self.ranked("financial.revenue.actual", site_ids)
                if len(ranked_sites) < 2:
                    continue
                biggest_site = ranked_sites[-1]
                self.case(
                    self.t("q.direct.site_revenue",
                           site=self.subjects.name(biggest_site.subject),
                           unit=self.subjects.name(unit_id), period=self.period),
                    EvaluationType.DIRECT_LOOKUP,
                    self.t("a.direct.site_revenue", value=_fmt(biggest_site)), [biggest_site.id],
                    reasoning="Requires reading below category level, to the store estate — "
                              "only the workbook goes this far down.",
                    sources=[self.artifact.get("finance_workbook")],
                )

    def numerical_comparison(self) -> None:
        """Several facts, compared. Answerable, but not by retrieving one page."""
        company = self.subjects.company_id
        units = list(self.subjects.unit_ids.values())

        revenue = self.get("financial.revenue.actual", company)
        budget = self.get("financial.revenue.budget", company)
        variance = self.get("financial.revenue.variance", company)
        if revenue and budget and variance and budget.value.amount:
            pct = abs(variance.value.amount / budget.value.amount * 100)
            self.case(
                self.t("q.numerical.revenue_vs_budget", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.numerical.revenue_vs_budget", adverse=_adverse(variance), pct=pct),
                [revenue.id, budget.id, variance.id], difficulty="easy",
                reasoning="Actual, budget, and the derived percentage must agree.",
                sources=[self.artifact.get("finance_workbook")],
            )

        for kind, label, superlative in (
            ("financial.revenue.variance", "revenue", "largest"),
            ("financial.gross_profit.variance", "gross profit", "largest"),
        ):
            ranked = self.ranked(kind, units)
            if len(ranked) >= 2:
                worst = ranked[0]
                self.case(
                    self.t("q.numerical.worst_unit_variance", superlative=superlative,
                           label=label, period=self.period),
                    EvaluationType.NUMERICAL_COMPARISON,
                    self.t("a.numerical.worst_unit_variance",
                           name=self.subjects.name(worst.subject), value=_adverse(worst)),
                    [f.id for f in ranked],
                    reasoning="Requires comparing every unit rather than reading one.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        # The whole category level, ranked. This is the question a merchandising
        # director actually asks, and it cannot be answered from a summary page.
        every_category = [c for members in self.subjects.categories_by_unit.values() for c in members]
        ranked = self.ranked("financial.gross_profit.variance", every_category)
        if len(ranked) >= 3:
            worst = ranked[0]
            self.case(
                self.t("q.numerical.worst_category", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.numerical.worst_category",
                       name=self.subjects.name(worst.subject), value=_adverse(worst)),
                [f.id for f in ranked[:5]], difficulty="hard",
                reasoning="Thirty-plus categories must be compared; no single page ranks them.",
                sources=[self.artifact.get("finance_workbook")],
            )
            best = ranked[-1]
            self.case(
                self.t("q.numerical.best_category", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.numerical.best_category",
                       name=self.subjects.name(best.subject), value=_adverse(best)),
                [f.id for f in ranked[-5:]], difficulty="hard",
                reasoning="The same comparison in the other direction, which a summary omits.",
                sources=[self.artifact.get("finance_workbook")],
            )

        margins = self.ranked("financial.gross_margin_pct.actual", every_category)
        if len(margins) >= 3:
            thinnest = margins[0]
            self.case(
                self.t("q.numerical.thinnest_margin_category", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.numerical.thinnest_margin_category",
                       name=self.subjects.name(thinnest.subject), value=_fmt(thinnest)),
                [f.id for f in margins[:5]], difficulty="hard",
                reasoning="Margin rate, not margin money — the two rank differently.",
                sources=[self.artifact.get("finance_workbook")],
            )

        # The store-level analogue of `worst_category`, gated the same way as
        # `direct_lookup`'s site cases: it needs an estate large enough to be
        # worth comparing, which only a high-density build asks for.
        if self.density > 1.0:
            every_site = [s for members in self.subjects.sites_by_unit.values() for s in members]
            ranked_sites = self.ranked("financial.revenue.variance", every_site)
            if len(ranked_sites) >= 3:
                worst_site = ranked_sites[0]
                self.case(
                    self.t("q.numerical.worst_site_variance", period=self.period),
                    EvaluationType.NUMERICAL_COMPARISON,
                    self.t("a.numerical.worst_site_variance",
                           name=self.subjects.name(worst_site.subject), value=_adverse(worst_site)),
                    [f.id for f in ranked_sites[:5]], difficulty="hard",
                    reasoning="A thousand-store estate must be compared; no summary page ranks "
                              "individual sites.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        # Reconciliation, asked as a question rather than assumed as a property.
        for unit_id, members in self.subjects.categories_by_unit.items():
            unit_fact = self.get("financial.revenue.actual", unit_id)
            parts = [f for c in members if (f := self.get("financial.revenue.actual", c))]
            if unit_fact and len(parts) >= 2:
                self.case(
                    self.t("q.numerical.category_reconciliation",
                           unit=self.subjects.name(unit_id), period=self.period),
                    EvaluationType.NUMERICAL_COMPARISON,
                    self.t("a.numerical.category_reconciliation"),
                    [unit_fact.id] + [f.id for f in parts], difficulty="hard",
                    reasoning="Tests the roll-up the whole corpus rests on.",
                    sources=[self.artifact.get("finance_workbook")],
                )
                break

        gp = [f for s in (*units, company) if (f := self.get("financial.gross_profit.variance", s))]
        if len(gp) > len(units):
            self.case(
                self.t("q.numerical.unit_group_reconciliation", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.numerical.unit_group_reconciliation"),
                [f.id for f in gp],
                reasoning="Tests the property the whole corpus rests on.",
                sources=[self.artifact.get("finance_workbook")],
            )

    def incident(self) -> None:
        """Everything that only exists when the close went wrong."""
        if not self.episode.had_incident:
            return
        k = self.episode.keys
        by_id = {f.id: f for f in self.episode.facts}
        cause = by_id[k["fact_cause"]]
        hypothesis = by_id[k["fact_hypothesis"]]
        delayed = by_id[k["fact_close_delayed"]]
        delay = by_id[k["fact_close_delay"]]
        final = by_id[k["fact_close_status_final"]]

        rca = self.artifact.get("incident_rca")
        record = self.artifact.get("servicenow_incident")
        stale = self.artifact.get("confluence_page")
        note = self.artifact.get("working_note")
        jira = self.artifact.get("jira_issues")

        # -- causal chains -------------------------------------------------
        #
        # The four questions below that read `self.estate` ask the same thing
        # of a different search space, and that is the honest half of the
        # phrasing lever (see `evaluation_cases`): "why was the close delayed"
        # has one candidate service in a nine-node prop list and a hundred in a
        # real landscape, so a question that does not say which estate it is
        # being asked of is a different question in the two worlds while
        # reading as the same string. Only the question surface moves — the
        # expected answer, the cited facts, the difficulty and the sources are
        # the same in both branches, because the estate changed what has to be
        # ruled out, not what is true.
        self.case(
            self.t("q.incident.why_delayed.estate", scale=self._scale, period=self.period)
            if self.estate else
            self.t("q.incident.why_delayed", period=self.period),
            EvaluationType.CAUSAL_MULTI_HOP,
            self.t("a.incident.why_delayed", cause=cause.text_value,
                   days=int(delay.value.amount)),
            [k["fact_feed_status"], cause.id, delayed.id, delay.id], difficulty="hard",
            reasoning="Failure to cause to workaround to calendar impact.",
            sources=[rca, record], distractors=[stale],
        )
        self.case(
            self.t("q.incident.undetected.estate",
                   system=self.subjects.name(self.estate.system),
                   reach=len(self.estate.reach))
            if self.estate else
            self.t("q.incident.undetected"),
            EvaluationType.CAUSAL_MULTI_HOP,
            self.t("a.incident.undetected"),
            [k["fact_cause"], k["fact_classification"], k["fact_owner"]], difficulty="hard",
            reasoning="The condition behind the cause, which the incident record states "
                      "and the status page does not.",
            sources=[rca], distractors=[stale],
        )
        self.case(
            self.t("q.incident.recurrence"),
            EvaluationType.CAUSAL_MULTI_HOP,
            self.t("a.incident.recurrence"),
            [k["fact_recurrence"], k["fact_owner"], k["fact_classification"]], difficulty="hard",
            reasoning="Recurrence plus an unassigned owner is the finding; either alone is not.",
            sources=[rca],
        )

        # -- temporal state, at three moments -------------------------------
        # Each cut-off is chosen so a *different* answer is correct, which is what
        # makes the family test knowing-when rather than knowing-what.
        if hypothesis.valid_to is not None:
            midpoint = hypothesis.valid_from + (hypothesis.valid_to - hypothesis.valid_from) / 2
            self.case(
                self.t("q.incident.hypothesis_at_time"),
                EvaluationType.TEMPORAL_STATE, hypothesis.text_value or "", [hypothesis.id],
                cutoff=midpoint, difficulty="hard",
                reasoning="At this cut-off the superseded answer is the correct one.",
                sources=[stale], distractors=[rca, record],
            )
        if delayed.valid_to is not None:
            # The cut-off has to sit inside *this* fact's window, not inside the
            # hypothesis's. Reusing the hypothesis midpoint made a case that
            # expected an answer which had not yet been recorded — unanswerable,
            # and caught by `answer_unavailable_at_cutoff` rather than by review.
            during = delayed.valid_from + (delayed.valid_to - delayed.valid_from) / 2
            self.case(
                self.t("q.incident.expected_on_time"),
                EvaluationType.TEMPORAL_STATE,
                self.t("a.incident.expected_on_time"),
                [delayed.id], cutoff=during, difficulty="hard",
                reasoning="The final status supersedes this; asking earlier must not return it.",
                sources=[note], distractors=[rca],
            )
        self.case(
            self.t("q.incident.status_at_finalised"),
            EvaluationType.TEMPORAL_STATE, final.text_value or "", [final.id],
            cutoff=final.valid_from, difficulty="medium",
            reasoning="The same question at a later cut-off, where the answer changed.",
            distractors=[note],
        )

        # -- authority -------------------------------------------------------
        self.case(
            self.t("q.authority.confirmed_cause.estate", scale=self._scale)
            if self.estate else
            self.t("q.authority.confirmed_cause"),
            EvaluationType.AUTHORITY_RESOLUTION, cause.text_value or "",
            [cause.id, hypothesis.id], difficulty="hard",
            reasoning="Two documents state a cause. Only one was updated after it was ruled out.",
            sources=[rca, record], distractors=[stale],
        )
        self.case(
            self.t("q.authority.stale_record"),
            EvaluationType.AUTHORITY_RESOLUTION,
            self.t("a.authority.stale_record"),
            [hypothesis.id, cause.id], difficulty="hard",
            reasoning="Requires recognising a stale source as stale.",
            sources=[stale],
        )
        self.case(
            self.t("q.authority.close_status_source"),
            EvaluationType.AUTHORITY_RESOLUTION,
            self.t("a.authority.close_status_source", status=final.text_value),
            [final.id], cutoff=final.valid_from, difficulty="hard",
            reasoning="Working documents may still show the close as open; they are not the record.",
            distractors=[note],
        )

        # -- citation and cross-artifact -------------------------------------
        self.case(
            self.t("q.citation.mapping_owner.estate",
                   system=self.subjects.name(self.estate.system))
            if self.estate else
            self.t("q.citation.mapping_owner"),
            EvaluationType.CITATION_REQUIRED,
            self.t("a.citation.mapping_owner"), [k["fact_owner"]],
            reasoning="The correct answer is that the field is empty, which is not abstaining.",
            sources=[rca, jira],
        )
        self.case(
            self.t("q.citation.evidence_ruled_out"),
            EvaluationType.CITATION_REQUIRED,
            by_id[k["fact_cause_ruled_out"]].text_value or "",
            [k["fact_cause_ruled_out"], hypothesis.id], difficulty="hard",
            reasoning="An answer without its evidence is indistinguishable from a guess that "
                      "happens to be right.",
            sources=[rca], distractors=[stale],
        )
        self.case(
            self.t("q.citation.affected_records"),
            EvaluationType.CITATION_REQUIRED,
            self.t("a.citation.affected_records", value=_fmt(by_id[k["fact_affected"]])),
            [k["fact_affected"]],
            reasoning="The figure appears in more than one place; the citation is the test.",
            sources=[rca, record],
        )
        self.case(
            self.t("q.cross.remediation_choice"),
            EvaluationType.CROSS_ARTIFACT,
            self.t("a.cross.remediation_choice"),
            [k["fact_classification"], k["fact_remediation"], k["fact_remediation_scope"]],
            difficulty="hard",
            reasoning="Both tickets are plausible; the classification separates them.",
            sources=[rca, jira],
        )
        self.case(
            self.t("q.cross.pl_impact", period=self.period),
            EvaluationType.CROSS_ARTIFACT,
            self.t("a.cross.pl_impact"),
            [k["fact_pl_impact"], delay.id],
            reasoning="A plausible wrong answer attributes the revenue shortfall to the incident.",
            sources=[self.artifact.get("executive_summary")], distractors=[rca],
        )

    def across_episodes(self) -> None:
        """The questions a single close cannot pose.

        Recurrence, whether a remediation held, and which of two documents that
        both look authoritative is the current one. These are the families the
        corpus claims to be about, and until a world ran more than one period they
        were all argued from a single episode's worth of evidence.
        """
        if not self.history:
            return

        earlier_incidents = [
            f for f in self.history
            if f.kind == "ops.incident_opened" and f.period and f.period != self.period
        ]
        calendars = [i.id for i in (*self.prior_intents, *()) if i.artifact_type == "close_calendar"]
        current_calendar = self.artifact.get("close_calendar")

        if calendars and current_calendar:
            due = self.get("close.due_date", self.subjects.company_id)
            if due:
                self.case(
                    self.t("q.across.current_calendar"),
                    EvaluationType.AUTHORITY_RESOLUTION,
                    self.t("a.across.current_calendar", period=self.period, date=due.text_value),
                    [due.id], difficulty="hard",
                    reasoning="Earlier calendars are published, look identical, and are superseded.",
                    sources=[current_calendar], distractors=calendars,
                )

        if earlier_incidents and self.episode.had_incident:
            k = self.episode.keys
            previous = earlier_incidents[-1]
            self.case(
                self.t("q.across.recurrence"),
                EvaluationType.CAUSAL_MULTI_HOP,
                self.t("a.across.recurrence", prior_period=previous.period, period=self.period),
                [previous.id, k["fact_recurrence"], k["fact_owner"]], difficulty="hard",
                reasoning="Spans two episodes. A single close cannot answer it at all.",
                sources=[self.artifact.get("incident_rca")],
            )
            self.case(
                self.t("q.across.incident_count", period=self.period),
                EvaluationType.NUMERICAL_COMPARISON,
                self.t("a.across.incident_count", count=len(earlier_incidents) + 1),
                [f.id for f in earlier_incidents] + [k["fact_incident_ref"]], difficulty="hard",
                reasoning="Requires counting across periods rather than reading one record.",
            )

        # The same measure, asked of a period that is no longer current. A system
        # that returns the latest figure regardless of the period asked for fails
        # here and nowhere else.
        prior_revenue = [
            f for f in self.history
            if f.kind == "financial.revenue.actual"
            and f.subject == self.subjects.company_id
            and f.period
            and f.period != self.period
        ]
        # Only the immediately preceding period at the default density — every
        # corpus this family has ever shipped in. Above it, a build with more
        # than two periods can finally ask about *each* earlier one instead of
        # just the last: a five-period build and a two-period build produced
        # the identical single case here otherwise, which is the fixed-size
        # symptom this whole knob exists to fix — more periods genuinely means
        # more distinct "what did this period say" questions, not a rephrasing
        # of the same one.
        targets = prior_revenue if self.density > 1.0 else prior_revenue[-1:]
        for earlier in targets:
            self.case(
                self.t("q.across.prior_period_revenue", period=earlier.period),
                EvaluationType.TEMPORAL_STATE,
                self.t("a.across.prior_period_revenue", value=_fmt(earlier)), [earlier.id],
                difficulty="hard",
                reasoning="The current period's figure is the confident wrong answer.",
                sources=[self.artifact.get("finance_workbook")],
            )

    def abstentions(self) -> None:
        """Plausible questions this corpus does not answer.

        Each one has to stay unanswerable as the corpus grows, which is harder
        than it sounds — "how many stores does the food division operate" was an
        abstention case until a store estate was generated, and then it quietly
        became a question with an answer sitting in the workbook. These are
        phrased against things the model deliberately does not carry: people
        costs, suppliers, customers, competitors, and any period but this one.
        """
        for key, reasoning in (
            ("q.abstain.previous_close_cause",
             "Presupposes an event this corpus does not contain."),
            ("q.abstain.ceo_remuneration",
             "The person exists; the fact does not."),
            ("q.abstain.supplier_shortfall",
             "Suppliers are not modelled at all, and the question presumes one is."),
            ("q.abstain.nps",
             "A plausible retail metric the corpus does not measure."),
            ("q.abstain.staff_costs",
             "Revenue and gross profit are modelled; operating costs are not."),
            ("q.abstain.market_share",
             "No competitor exists in this world."),
            ("q.abstain.next_audit",
             "Forward-looking; the corpus records what happened, not what is planned."),
        ):
            self.abstain(self.t(key), reasoning)

    # -- history -------------------------------------------------------
    #
    # Four families against the world's own past — a reorganisation, a
    # departure, a founding milestone, a document signed by someone who no
    # longer holds the post — plus the abstentions that go with having a
    # history at all. Every one of the first three is guarded by
    # `_reachable_fact_ids`: the underlying event is always witnessed by a
    # `CanonicalFact` the moment it happens, but nothing downstream of this
    # module currently plans a document that requires that fact (see that
    # method's docstring), so a case built on it would fail `validate()`'s
    # `unreachable_answer` check — correctly, since no artifact carries it
    # yet. That is a gap in what plans artifacts, not in what asks questions
    # about them, so it is reported rather than worked around here.

    def org_state_over_time(self) -> None:
        """Who led a business unit, asked at a moment rather than "currently".

        A `Reorganisation`, or a `Departure` that hands over a unit along with
        the post, changes who is correct to name as the unit's leader from
        that moment on. A system with no notion of a validity window has no
        reason to prefer the leader who was actually in post on the date
        asked about over whoever leads the unit today — which is exactly what
        `org.unit_leader_changed`'s `valid_from` records and what makes this
        a temporal question rather than a plain lookup.
        """
        reachable = self._reachable_fact_ids()
        role_changes = self._facts_of("org.role_changed")
        for change in self._facts_of("org.unit_leader_changed"):
            if change.id not in reachable:
                continue
            successor = next((f for f in role_changes if f.event_id == change.event_id), None)
            if successor is None or successor.id not in reachable:
                continue
            self.case(
                self.t("q.history.unit_leader_as_of",
                       unit=self.subjects.name(change.subject),
                       period=change.period or self.period),
                EvaluationType.TEMPORAL_STATE,
                self.subjects.name(successor.subject),
                [change.id, successor.id],
                cutoff=change.valid_from, difficulty="hard",
                reasoning="Leadership changed within this world's history; a system with no "
                          "validity window has no reason to prefer the post-change leader over "
                          "whoever led the unit before.",
            )

    def succession(self) -> None:
        """Who replaced whom — answerable only by joining two records.

        `org.departed` names who left; a separate `org.role_changed` fact,
        minted by the same event, names who took the post. Neither states the
        other's half, so "who replaced X" is a join across two facts rather
        than a lookup against one — the shape `CAUSAL_MULTI_HOP` exists for.
        """
        reachable = self._reachable_fact_ids()
        role_changes = self._facts_of("org.role_changed")
        for departure in self._facts_of("org.departed"):
            if departure.id not in reachable:
                continue
            successor = next((f for f in role_changes if f.event_id == departure.event_id), None)
            if successor is None or successor.id not in reachable:
                continue
            self.case(
                self.t("q.history.succession", person=self.subjects.name(departure.subject)),
                EvaluationType.CAUSAL_MULTI_HOP,
                self.subjects.name(successor.subject),
                [departure.id, successor.id], difficulty="hard",
                reasoning="The departure record names who left; the succession record names "
                          "who took over. Neither states the other's half.",
            )

    def milestone_provenance(self) -> None:
        """When a founding milestone happened — answerable only from the
        event itself, never from a close document.

        `organisation.generate` mints one `MFACT-` fact per dated lore
        commitment, so a claim lore makes about the corpus's own past — a
        hierarchy remap, a platform replatform — has something on the
        timeline that actually witnesses it. No close artifact restates a
        founding date: a close reports its own period, not the company's
        history, so this is the one family where the finance workbook is not
        even a plausible wrong answer.
        """
        reachable = self._reachable_fact_ids()
        for milestone in self._facts_of("lore.milestone"):
            if milestone.id not in reachable:
                continue
            # The assertion is often compound — the event, then its lasting
            # consequence ("...replatformed. Conversion has been volatile
            # since..."). Only the first clause is the dated event the
            # question asks about; the rest is the scar, not the provenance.
            assertion = (milestone.text_value or "").split(". ")[0].rstrip(".")
            self.case(
                self.t("q.history.milestone_provenance", assertion=assertion),
                EvaluationType.CITATION_REQUIRED,
                milestone.valid_from.strftime("%B %Y"),
                [milestone.id], difficulty="hard",
                reasoning="The date is carried only by the founding milestone fact; nothing in "
                          "a close document restates a founding date.",
            )

    def authorship_over_time(self) -> None:
        """Who signed a role-authored document, before versus after a
        succession moved the post to someone else.

        `_period_boundary` in `scenarios.py` times a departure so the leaver
        signs their own period's close and the successor signs the next
        one — so the same document type, one period apart, is genuinely
        signed by two different people. Mirrors `across_episodes`'s
        prior-period revenue case: the current holder's name is the confident
        wrong answer to a question about the earlier period. Unlike the three
        families above, this one needs no new fact kind and no reachability
        guard — the grounding fact is whichever one the document already
        required, so it is reachable by construction.
        """
        if not self.prior_intents:
            return
        for artifact_type in ("cfo_variance_memo", "finance_workbook", "close_calendar"):
            current = next((i for i in self.intents if i.artifact_type == artifact_type), None)
            earlier = next(
                (i for i in reversed(self.prior_intents) if i.artifact_type == artifact_type),
                None,
            )
            if current is None or earlier is None or earlier.author_id == current.author_id:
                continue
            if not earlier.required_fact_ids or not current.required_fact_ids:
                continue

            label = artifact_type.replace("_", " ")
            earlier_fact = self._fact_index.get(earlier.required_fact_ids[0])
            earlier_period = (
                earlier_fact.period if earlier_fact and earlier_fact.period else "the previous period"
            )
            self.case(
                self.t("q.history.signed_earlier", doc_type=label, period=earlier_period),
                EvaluationType.TEMPORAL_STATE, self.subjects.name(earlier.author_id),
                [earlier.required_fact_ids[0]], difficulty="hard",
                reasoning="The post has changed hands since; the current holder is the "
                          "confident wrong answer to a question about the earlier period.",
            )
            self.case(
                self.t("q.history.signed_current", doc_type=label, period=self.period),
                EvaluationType.TEMPORAL_STATE, self.subjects.name(current.author_id),
                [current.required_fact_ids[0]], difficulty="medium",
                reasoning="The same document type after the post changed hands — included so "
                          "a system that gets the earlier period wrong is shown getting the "
                          "current one right.",
            )
            break  # one document type makes the point; a second would only repeat it.

    def communications(self) -> None:
        """Who was in the room, and who was told when.

        Askable only because the meeting and the thread are documents now. The
        facts these cases expect appear in half the corpus; what makes them
        hard is that the *pairing* — attendance beside decision, moment beside
        channel — exists in exactly one document each, and that document is
        neither the largest nor the most authoritative-looking source.
        """
        if not self.episode.had_incident:
            return
        k = self.episode.keys
        by_id = {f.id: f for f in self.episode.facts}

        minutes = self.artifact.get("meeting_minutes")
        if minutes:
            cause = by_id[k["fact_cause"]]
            self.case(
                self.t("q.comms.meeting_attendance_cause"),
                EvaluationType.CROSS_ARTIFACT,
                self.t("a.comms.meeting_attendance_cause", cause=cause.text_value),
                [k["fact_cause"], k["fact_close_delayed"]], difficulty="hard",
                reasoning="The cause appears in many documents; attendance exists "
                          "only in the minutes, so the pairing has one source.",
                sources=[minutes], distractors=[self.artifact.get("confluence_page")],
            )
        thread = self.artifact.get("email_thread")
        if thread:
            delayed = by_id[k["fact_close_delayed"]]
            self.case(
                self.t("q.comms.cfo_notified"),
                # Cross-artifact, not temporal-state: there is no cutoff to
                # reason at — the question joins a fact many documents carry
                # with a channel and moment only the thread records.
                EvaluationType.CROSS_ARTIFACT,
                self.t("a.comms.cfo_notified", date=delayed.valid_from.date().isoformat()),
                [k["fact_close_delayed"]], difficulty="hard",
                reasoning="The RCA and the memo carry the fact; only the thread "
                          "carries when it reached the CFO, and through what.",
                sources=[thread], distractors=[self.artifact.get("incident_rca")],
            )

    def accountability_measure(self) -> None:
        """Who answers for a measure that moved beyond the band they are held to.

        The question this corpus could not ask. A budget belongs to a business
        unit, a variance is reported against that unit, and until lore could
        name an accountability nothing anywhere connected either to a person —
        so "who was answerable for the miss" had no answer to check against.

        It is a genuine join and that is the point of adding it: the
        accountability fact carries *who and which measure*, the variance fact
        carries *how far it moved*, and the budget fact is what turns an amount
        into a percentage that can be compared against the band. No single
        document holds all three.

        Scoped to the accountable person's own business unit. That constraint
        is the whole correctness of the family: an accountability's subject is a
        person and a variance's subject is a unit, so an unconstrained join
        names the general-merchandise MD as answerable for the digital unit's
        miss. The case would be well-formed, citable, and false.

        Empty unless lore names an accountability, and no shipped lore does.
        """
        accountabilities = [
            fact for fact in self.history
            if fact.kind == ACCOUNTABILITY_KIND and not fact.is_superseded
        ]
        for accountability in accountabilities:
            measure = accountability.text_value
            band = accountability.value.amount if accountability.value else None
            unit_id = self.subjects.unit_by_person.get(accountability.subject)
            if not measure or band is None or unit_id is None:
                # A person with no unit — a group CFO, an auditor — is
                # accountable for something this family cannot scope, so it
                # says nothing rather than guessing at a subject.
                continue

            variance = self.get(measure, unit_id)
            budget = self.get(measure.replace(".variance", ".budget"), unit_id)
            if not (variance and variance.value and budget and budget.value and budget.value.amount):
                continue

            moved_pct = abs(variance.value.amount) / abs(budget.value.amount) * 100.0
            if moved_pct <= band:
                # Inside the band is not a miss, and asking who was accountable
                # for a number that behaved is a question with no answer.
                continue

            self.case(
                self.t("q.accountability.who_accountable",
                       measure=measure, unit=self.subjects.name(unit_id), period=self.period),
                EvaluationType.CROSS_ARTIFACT,
                self.t("a.accountability.who_accountable",
                       person=self.subjects.name(accountability.subject)),
                [accountability.id, variance.id, budget.id],
                difficulty="hard",
                reasoning="The workbook carries the variance and the budget; only the"
                          " accountability says who is held to the measure, and only"
                          " the band it states makes the move a miss rather than a"
                          " number.",
                sources=[self.artifact.get("finance_workbook")],
            )

    def estate_shape(self) -> None:
        """What only the dependency graph can answer.

        Three questions, and none of them has an answer written down anywhere
        in the corpus as a sentence: how far a failure reaches, what nothing
        routes around, and how deep the chain under the system of record runs.
        A keyword retriever cannot shortcut a question nobody wrote a sentence
        about — which is the argument `graphs.py`'s docstring makes for the
        module existing, made good here.

        Where the answer *is* carried is the ServiceNow bundle: the incident
        artifact renders `cmdb_ci` and `cmdb_rel_ci` beside the incident
        itself, so every edge these questions turn on ships in the corpus, in
        the same artifact as the facts each case cites. That is what makes the
        family answerable rather than merely unanswered — and what makes it
        hard, since the retrievable *passages* are prose and the answer is in a
        relationship table the passage index does not index.

        Silent in a world whose estate is the episode's own prop list, and it
        must be: the mapping sync has exactly two dependents there and the RCA
        names both, so all three questions would be restatements of documents
        the corpus already has. See `_read_estate`.
        """
        estate = self.estate
        if estate is None:
            return
        keys = self.episode.keys
        record = self.artifact.get("servicenow_incident")
        rca = self.artifact.get("incident_rca")
        stale = self.artifact.get("confluence_page")

        # Named subject rather than "what would have stopped", because *which*
        # thing gets named is itself a reading of this world's graph — the
        # largest dependent is a generated service nobody wrote a sentence
        # about in one world and the valuation job the RCA is entirely about in
        # another. That is the only lever in this module that makes a family
        # legitimately easier in one world than another: the question is the
        # same shape, and the corpus happens to have narrated its subject.
        largest = self.subjects.name(estate.reach[0])
        self.case(
            self.t("q.estate.blast_radius", scale=self._scale,
                   service=self.subjects.name(estate.service), name=largest),
            EvaluationType.CAUSAL_MULTI_HOP,
            self.t("a.estate.blast_radius", name=largest, count=len(estate.reach)),
            [keys["fact_classification"], keys["fact_feed_status"]], difficulty="hard",
            reasoning="Transitive, not direct: the answer is every ancestor in the"
                      " dependency graph, and no document lists them.",
            sources=[record, rca], distractors=[stale],
        )

        # Only when something *does* route around it. When nothing does, the
        # mapping sync is the single point of failure and `incident.undetected`
        # already tells that story from the control side — asking it again from
        # the graph side would be the restatement this whole family exists to
        # stop producing.
        if estate.detour and estate.chokepoints:
            self.case(
                self.t("q.estate.routed_around",
                       service=self.subjects.name(estate.service),
                       system=self.subjects.name(estate.system)),
                EvaluationType.CAUSAL_MULTI_HOP,
                self.t("a.estate.routed_around", count=estate.detour,
                       system=self.subjects.name(estate.system),
                       names=", ".join(
                           self.subjects.name(node) for node, _ in estate.chokepoints[:3]
                       )),
                [keys["fact_owner"], keys["fact_classification"]], difficulty="hard",
                reasoning="Blast radius and single-point-of-failure are different"
                          " measures, and the intuitive answer confuses them: the"
                          " service the incident ran through is well routed around,"
                          " and the estate's real gates are elsewhere.",
                sources=[record, rca], distractors=[stale],
            )

        if len(estate.chain) >= 2:
            self.case(
                self.t("q.estate.chain_to_record",
                       system=self.subjects.name(estate.system)),
                EvaluationType.CAUSAL_MULTI_HOP,
                self.t("a.estate.chain_to_record", hops=len(estate.chain) - 1,
                       name=self.subjects.name(estate.chain[0])),
                [keys["fact_owner"]], difficulty="hard",
                reasoning="Depth, counted in edges. A document that names the two"
                          " hops the incident took is the confident wrong answer.",
                sources=[record], distractors=[rca],
            )

        # False by construction at every estate size, which is the bar
        # `history_abstentions` sets: nothing in this generator models a
        # recovery posture for anything, so growing the estate adds services
        # without ever adding the fact this asks for.
        self.abstain(
            self.t("q.estate.abstain_recovery", scale=self._scale,
                   system=self.subjects.name(estate.system)),
            "Resilience posture is not modelled at any estate size — the graph"
            " records what depends on what, never what has been tested.",
        )

    def history_abstentions(self) -> None:
        """History questions that stay unanswerable regardless of how large
        the world grows.

        The trap `abstentions` warns about is a question unanswerable by
        accident — a dimension the corpus merely has not generated yet, which
        stops being true the moment it does. Both of these are false *by
        construction* instead: no marketing function is modelled at any world
        size, so a Chief Marketing Officer is not a person this generator can
        ever produce; and `organisation.generate`'s tenure formula has a fixed
        ceiling on how far back anyone's `joined` can fall, so a date well
        before that ceiling is before the roster at every seed, not merely
        this one.
        """
        self.abstain(
            self.t("q.abstain.cmo"),
            "No marketing function is modelled in this organisation; the role, and "
            "therefore the person, does not exist.",
        )
        self.abstain(
            self.t("q.abstain.close_calendar_1995"),
            "Presupposes a roster and a close from before this archetype's organisation "
            "could exist — every join date this generator can produce falls well after it.",
        )


    def approvals(self) -> None:
        """Who signed it, who only wrote it, and which documents nobody signed.

        Documents gained a signature block (`documents._signoff`) and nothing
        asked about it: "who approved the March pack for Fuel and Convenience"
        was answerable from the corpus and asked by nobody.

        Three shapes, and the difficulty runs in one direction.

        **The trap is the byline.** A document names its author at the top, in
        larger type, before any content; it names its approver in a table at
        the bottom. A retrieval system that has learned "the name near the
        title is who this document is from" gets the author every time, which
        is why the author is stated as the wrong answer in the reasoning rather
        than left implicit. `authority_resolution` rather than
        `direct_lookup`: two people are named in one document and the question
        is which of them the corpus says did *what*.

        **The unit commentary is the hard case**, because eight of them exist
        and each has a different pair — so a system that retrieves the right
        *type* of document and the wrong division answers confidently and
        wrongly. Both halves are asked, prepared and approved, so a system
        that gets one by matching on "commentary" is shown getting the other
        wrong.

        **And a document nobody signed must stay unsigned.** Absence is a claim
        here (`planning._APPROVED_BY`): a ServiceNow ticket has an assignee and
        a calendar is issued rather than approved. Asking who approved one is
        an abstention case, and it is the only test this corpus has that a
        system will not invent a signature to fill a blank.

        Grounded on whichever fact the document already required, the trick
        `authorship_over_time` uses: no new fact kind, and reachable by
        construction because the document that carries the signature is the
        document that carries the fact.
        """
        signed = [i for i in self.intents if i.approver_id]
        if not signed:
            return

        def named(person_id: str | None) -> str:
            return self.subjects.name(person_id) if person_id else ""

        # One group-level document, chosen by type rather than by position so
        # the case is the same question whichever engine ran the episode.
        for artifact_type in ("cfo_variance_memo", "finance_workbook"):
            intent = next(
                (i for i in signed
                 if i.artifact_type == artifact_type and i.required_fact_ids),
                None,
            )
            if intent is None:
                continue
            self.case(
                self.t("q.approval.who_approved",
                       doc_type=artifact_type.replace("_", " "), period=self.period),
                EvaluationType.AUTHORITY_RESOLUTION, named(intent.approver_id),
                [intent.required_fact_ids[0]], difficulty="medium",
                reasoning=(
                    f"{named(intent.author_id)} wrote it and is named in the byline;"
                    f" {named(intent.approver_id)} signed it and is named only in the"
                    " approval block at the foot of the document. The byline is the"
                    " confident wrong answer."
                ),
                sources=[intent.id],
            )
            break

        # One division's commentary, both halves. The unit is taken from the
        # first signed commentary rather than a favourite one, so a widened
        # company asks about a division a narrow one does not have.
        commentary = next(
            (i for i in signed
             if i.artifact_type == "unit_close_commentary" and i.required_fact_ids),
            None,
        )
        if commentary is not None:
            subject = self._fact_index.get(commentary.required_fact_ids[0])
            unit = self.subjects.name(subject.subject) if subject else ""
            if unit:
                self.case(
                    self.t("q.approval.who_approved_unit", unit=unit, period=self.period),
                    EvaluationType.AUTHORITY_RESOLUTION, named(commentary.approver_id),
                    [commentary.required_fact_ids[0]], difficulty="hard",
                    reasoning=(
                        "One commentary exists per division and each has a different"
                        " pair, so retrieving the right document type and the wrong"
                        " division answers confidently and wrongly."
                    ),
                    sources=[commentary.id],
                )
                self.case(
                    self.t("q.approval.who_prepared_unit", unit=unit, period=self.period),
                    EvaluationType.AUTHORITY_RESOLUTION, named(commentary.author_id),
                    [commentary.required_fact_ids[0]], difficulty="medium",
                    reasoning=(
                        "The other half of the pair, so a system that answers the"
                        " approval question by matching on 'commentary' is shown"
                        " getting this one wrong."
                    ),
                    sources=[commentary.id],
                )

        # And one that nobody signed.
        unsigned = next(
            (i for i in self.intents
             if not i.approver_id
             and i.artifact_type in ("close_calendar", "servicenow_incident", "email_thread")),
            None,
        )
        if unsigned is not None:
            self.abstain(
                self.t("q.abstain.unapproved",
                       doc_type=unsigned.artifact_type.replace("_", " "),
                       period=self.period),
                "The document exists and carries no approval, because its type does"
                " not get one — a ticket has an assignee and a calendar is issued"
                " rather than approved. The corpus records who wrote it and nobody"
                " else, so inventing a signature is the failure this case tests.",
            )


    def standing_documents(self) -> None:
        """What the rules are, who signed them, and what they used to be.

        The family the corpus most obviously lacked. Everything else here asks
        about a *period* — what revenue was, what the close did, who was in the
        room — and an assistant pointed at a real company's archive is asked
        "what is our expense approval threshold" far more often than any of
        them. It had no answer, because the company had no rules.

        Three shapes over ``worldloom.policies``:

        * **The provision.** A direct lookup, and deliberately so: this is the
          question, and phrasing it as anything cleverer would be dressing up
          the thing being measured. The clause states its own wording
          (``policies.Clause.asks``), because an author adding a provision
          knows what it will be asked and should not have to find a second
          table to say so.
        * **The provision that moved.** The expense policy is the one revised
          version in the shipped library, so the superseded figure is in the
          corpus with a closed validity window and the current one is not the
          answer. `temporal_state`, and the hardest of the three: the current
          document is the confident wrong answer and it is the one that looks
          newest.
        * **Who approved it.** A policy nobody approved is a draft, so every
          standing document carries a signature — which makes the corpus's
          authority chain reach the rules and not only the reports.

        Gated on the facts existing. A build that did not ask for policies
        mints nothing here, which is every corpus built before they did.
        """
        from .. import policies as policies_module

        specs = {spec.artifact_type: spec for area in policies_module.LIBRARY
                 for spec in policies_module.LIBRARY[area]}
        # `prior_intents` as well as this episode's, and for standing documents
        # it is only ever the former: a policy is planned when the world is
        # *built*, before any episode runs, because it is not caused by one.
        # That is the whole distinction this family exists to ask about, and a
        # search of `self.intents` alone found nothing on a corpus that plainly
        # had ten policies in it.
        planned = [i for i in (*self.prior_intents, *self.intents)
                   if i.artifact_type in specs]
        if not planned:
            return

        for intent in planned:
            spec = specs[intent.artifact_type]
            cited = {}
            for fact_id in intent.required_fact_ids:
                fact = self._fact_index.get(fact_id)
                if fact is not None:
                    cited[fact.kind] = fact
            for clause in spec.clauses:
                if not clause.asks:
                    continue
                fact = cited.get(policies_module.kind_of(spec, clause))
                if fact is None or fact.value is None:
                    continue
                self.case(
                    clause.asks, EvaluationType.DIRECT_LOOKUP,
                    f"{fact.value.amount:,.0f} {fact.value.unit}",
                    [fact.id], difficulty="easy",
                    reasoning=f"Stated in the {spec.title}, which is the only"
                              " document in the corpus that says it.",
                    sources=[intent.id],
                )

        # The one provision that moved, and the stale figure that is still in
        # the archive. Found by looking for a closed window rather than by
        # naming the expense policy, so a library that revises something else
        # tomorrow asks about that instead.
        # Over the world's whole ledger rather than this episode's cut: a
        # policy fact predates every episode, so `self.facts` — the period's
        # financial slice — contains none of them.
        ledger = list(self._fact_index.values())
        superseded = [
            fact for fact in ledger
            if fact.kind.startswith("policy.") and fact.valid_to is not None
            and fact.value is not None
        ]
        for fact in superseded[:1]:
            current = next(
                (f for f in ledger
                 if f.kind == fact.kind and f.valid_to is None and f.value is not None),
                None,
            )
            if current is None:
                continue
            spec = next(
                (s for s in specs.values()
                 if any(policies_module.kind_of(s, c) == fact.kind for c in s.clauses)),
                None,
            )
            label = next(
                (c.label.lower() for c in (spec.clauses if spec else ())
                 if policies_module.kind_of(spec, c) == fact.kind), "provision",
            ) if spec else "provision"
            self.case(
                self.t("q.policy.superseded", provision=label),
                EvaluationType.TEMPORAL_STATE,
                f"{fact.value.amount:,.0f} {fact.value.unit}",
                [fact.id], difficulty="hard",
                reasoning=(
                    f"The policy was revised; the figure in force now is"
                    f" {current.value.amount:,.0f} and is the confident wrong"
                    " answer, because it sits in the document that looks"
                    " newest. Only the validity window distinguishes them."
                ),
            )

        for intent in planned[:1]:
            spec = specs[intent.artifact_type]
            if not intent.approver_id or not intent.required_fact_ids:
                continue
            self.case(
                self.t("q.policy.owner", title=spec.title),
                EvaluationType.AUTHORITY_RESOLUTION,
                self.subjects.name(intent.approver_id),
                [intent.required_fact_ids[0]], difficulty="medium",
                reasoning="A policy nobody approved is a draft, so the"
                          " authority chain reaches the rules and not only the"
                          " reports.",
                sources=[intent.id],
            )


    def workforce(self) -> None:
        """A requisition against the rules, and a rating against a note.

        Two shapes, and both are cross-document by construction rather than by
        contrivance.

        **The requisition needs the policy.** Its commitment figure is in one
        document and the ladder that decides who may approve it is in another,
        written by a different function years earlier. This is the first
        question in this corpus whose answer is in neither document alone, and
        it is exactly the shape an enterprise assistant is asked — "was this
        approved at the right level" is a compliance question, not a lookup.

        **The rating needs the authority ranking.** A manager's running
        one-to-one note carries the view they held before calibration and the
        signed review carries the one that counts, and the two disagree on
        purpose. Every authority-resolution case in this repository before now
        was about an incident; a performance rating is the same shape and it
        reaches the whole organisation rather than the dozen people an incident
        touches.

        Gated on the rounds having run. A corpus that hired nobody and reviewed
        nobody mints nothing here.
        """
        by_kind: dict[str, list] = {}
        for fact in self._fact_index.values():
            if fact.kind.startswith("people."):
                by_kind.setdefault(fact.kind, []).append(fact)
        if not by_kind:
            return

        # The requisition whose approval level is highest, so the case is about
        # the rung that had to be climbed rather than the floor everything
        # clears. Ranked on the commitment, which is what the ladder reads.
        commitments = sorted(
            by_kind.get("people.requisition.commitment", []),
            key=lambda f: (-(f.value.amount if f.value else 0), f.id),
        )
        for fact in commitments[:1]:
            level = next(
                (f for f in by_kind.get("people.requisition.approval_level", [])
                 if f.subject == fact.subject), None,
            )
            if level is None or fact.value is None:
                continue
            self.case(
                self.t("q.people.requisition_level",
                       manager=self.subjects.name(fact.subject),
                       amount=f"{fact.value.amount:,.0f} {fact.value.unit}"),
                EvaluationType.CROSS_ARTIFACT, level.text_value or "",
                [fact.id, level.id], difficulty="hard",
                reasoning=(
                    "The figure is in the requisition and the ladder that"
                    " decides who may approve it is in the delegation of"
                    " authority — a different document, written by a different"
                    " function. Neither answers this alone."
                ),
            )

        # One person whose two records disagree.
        for signed in sorted(by_kind.get("people.review.rating", []),
                             key=lambda f: f.id)[:1]:
            held = next(
                (f for f in by_kind.get("people.review.held_rating", [])
                 if f.subject == signed.subject), None,
            )
            self.case(
                self.t("q.people.rating",
                       person=self.subjects.name(signed.subject), period=self.period),
                EvaluationType.DIRECT_LOOKUP, signed.text_value or "",
                [signed.id], difficulty="medium",
                reasoning="Stated in the signed review.",
            )
            if held is None or held.text_value == signed.text_value:
                continue
            self.case(
                self.t("q.people.held_view",
                       person=self.subjects.name(signed.subject), period=self.period),
                EvaluationType.AUTHORITY_RESOLUTION, signed.text_value or "",
                [signed.id], difficulty="hard",
                reasoning=(
                    f"The one-to-one note says {held.text_value!r} and is an"
                    " unofficial note; the review says otherwise and is an"
                    " approved report countersigned one level up. Ranking the"
                    " two is the whole of the question."
                ),
            )


def evaluation_cases(
    minter: Minter,
    *,
    episode: CloseEpisode,
    facts: tuple[CanonicalFact, ...],
    subjects: Subjects,
    intents: tuple[ArtifactIntent, ...],
    period: str,
    history: tuple[CanonicalFact, ...] = (),
    prior_intents: tuple[ArtifactIntent, ...] = (),
    text: Mapping[str, str] | None = None,
    density: float = 1.0,
    estate: Any = None,
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one episode.

    ``history`` and ``prior_intents`` are what the world already contained. A
    second episode asks questions the first could not — which is the only way the
    hard families get past a handful of cases each.

    ``text`` overrides entries of ``EVAL_TEXT`` — a pack re-voicing the
    benchmark itself, not just the episode it is drawn from (see
    `generators/episode_text` and this module's `EVAL_TEXT`).

    ``density`` is the ``--eval-density`` knob's numeric value, riding the
    recipe via ``MonthEndClose.eval_density`` — see the module docstring for
    what it does and does not change.

    ``estate`` is the world's dependency graph (``graphs.dependency_graph``),
    or ``None``. It is a graph rather than a ``World`` on purpose: everything
    the taxonomy wants from the estate is a graph measure, and taking the world
    itself would let a family here reach for anything at all — which is how a
    generator ends up depending on a field nobody knew it read. ``None``
    reproduces every case set built before this argument existed, and so does
    passing a graph the episode's prop list did not outgrow: the estate
    families and the estate-scaled question surfaces both gate on the same
    measured reading (``_Taxonomy._read_estate``), so a world with no estate
    asks none of them and loses nothing.

    That gating is also what keeps the phrasing lever honest. The mosaic varies
    organisation shape, calendar, and estate; it does not vary the business
    vocabulary, so a taxonomy that fills its templates from unit and category
    names renders **identically** in five structurally different companies. The
    estate is the axis the mosaic moves furthest — 9 nodes to 101 across five
    worlds — and it is the only one every fact in this module can be anchored
    to, so it is what the questions are re-anchored on. It deliberately does
    not reach the financial families: an estate is not evidence about how
    revenue should be asked after, and rephrasing those against it would be
    variation bought with a false premise.
    """
    taxonomy = _Taxonomy(
        minter, episode=episode, facts=facts, subjects=subjects, intents=intents,
        period=period, history=history, prior_intents=prior_intents,
        text=episode_text.merged(EVAL_TEXT, text, field="evaluation_text"),
        density=density, estate=estate,
    )
    taxonomy.direct_lookup()
    taxonomy.numerical_comparison()
    taxonomy.incident()
    taxonomy.across_episodes()
    taxonomy.abstentions()
    # Appended after every existing family so an `EVAL-` id already minted by
    # one of them never shifts — see AGENTS.md/CLAUDE.md on id stability.
    taxonomy.org_state_over_time()
    taxonomy.succession()
    taxonomy.milestone_provenance()
    taxonomy.authorship_over_time()
    taxonomy.history_abstentions()
    # Appended after every family above for the same id-stability reason, and
    # gated inside on the fan-out documents actually being planned.
    taxonomy.communications()
    taxonomy.accountability_measure()
    # Last, for the same id-stability reason every family above it was
    # appended rather than inserted: a world with no estate mints nothing here,
    # so no `EVAL-` id in any corpus already built can move.
    taxonomy.estate_shape()
    # Last, and appended for the reason every family above was: a world whose
    # planner names no approver mints nothing here, so no `EVAL-` id in any
    # corpus already built can move.
    taxonomy.approvals()
    # Last, and appended for the reason every family above it was. A world that
    # did not ask for standing documents mints nothing here, so no `EVAL-` id
    # in any corpus already built can move.
    taxonomy.standing_documents()
    # Last again, and for the same reason. A corpus that ran no workforce round
    # mints nothing here.
    taxonomy.workforce()

    # One last pass of the rule every family is supposed to apply for itself.
    #
    # It was incidental until actors landed, because which facts reached a
    # document was a planner's decision and the planner always carried the
    # incident set. It is a *choice* now: an actor cites what it observed, so a
    # close where nobody wrote the RCA leaves the control-failure facts in no
    # document at all, and a family that asked about them anyway would emit a
    # question with no answer in the corpus. The validator catches that as
    # `unreachable_answer`; catching it here means the case is never generated
    # rather than generated and then explained away.
    #
    # Nothing is dropped on the deterministic path — every case there was
    # already reachable, which is what the existing corpora prove.
    return answerable(taxonomy.cases, taxonomy._reachable_fact_ids())
