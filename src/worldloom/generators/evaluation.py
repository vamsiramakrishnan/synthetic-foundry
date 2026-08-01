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
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from ..ids import Minter
from ..models import ArtifactIntent, CanonicalFact, EvaluationCase, EvaluationType
from .cases import CaseBuilder, adverse as _adverse, answerable, fmt as _fmt
from .operations import CloseEpisode


@dataclass(frozen=True)
class Subjects:
    """What the taxonomy needs in order to name and rank what it asks about."""

    company_id: str
    unit_ids: dict[str, str]
    names: dict[str, str]
    categories_by_unit: dict[str, list[str]]
    sites_by_unit: dict[str, list[str]]

    def name(self, subject_id: str) -> str:
        return self.names.get(subject_id, subject_id)


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
    ) -> None:
        self.minter = minter
        self.episode = episode
        self.subjects = subjects
        self.period = period
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

    # -- families ----------------------------------------------------------

    def direct_lookup(self) -> None:
        """One fact, one document. The floor — a baseline should pass these."""
        company = self.subjects.company_id
        for kind, phrasing in (
            ("financial.revenue.actual", "What was total revenue for {period}?"),
            ("financial.gross_profit.actual", "What was group gross profit for {period}?"),
            ("financial.gross_margin_pct.actual", "What was the group gross margin for {period}?"),
        ):
            fact = self.get(kind, company)
            if fact:
                self.case(
                    phrasing.format(period=self.period), EvaluationType.DIRECT_LOOKUP,
                    _fmt(fact), [fact.id], difficulty="easy",
                    reasoning="Single lookup against the system of record.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        for unit_id in self.subjects.unit_ids.values():
            fact = self.get("financial.revenue.actual", unit_id)
            if fact:
                self.case(
                    f"What revenue did {self.subjects.name(unit_id)} report for {self.period}?",
                    EvaluationType.DIRECT_LOOKUP, _fmt(fact), [fact.id], difficulty="easy",
                    reasoning="Divisional lookup; the group figure is the tempting wrong answer.",
                    sources=[self.artifact.get("finance_workbook")],
                )

        # Category and store lookups exist because the corpus reports at those
        # levels and nothing was asking about them. Chosen by rank rather than at
        # random: the largest category is a thing someone would ask about.
        for unit_id, members in self.subjects.categories_by_unit.items():
            ranked = self.ranked("financial.revenue.actual", members)
            if len(ranked) >= 2:
                biggest = ranked[-1]
                self.case(
                    f"What revenue did the {self.subjects.name(biggest.subject)} category in "
                    f"{self.subjects.name(unit_id)} report for {self.period}?",
                    EvaluationType.DIRECT_LOOKUP, _fmt(biggest), [biggest.id],
                    reasoning="Requires reading below divisional level.",
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
                f"By how much did revenue miss budget in {self.period}, in absolute terms "
                "and as a percentage?",
                EvaluationType.NUMERICAL_COMPARISON,
                f"{_adverse(variance)}, or {pct:.2f}%.",
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
                    f"Which business unit carried the {superlative} adverse {label} "
                    f"variance in {self.period}?",
                    EvaluationType.NUMERICAL_COMPARISON,
                    f"{self.subjects.name(worst.subject)}, at {_adverse(worst)}.",
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
                f"Which merchandise category lost the most gross profit against plan in {self.period}?",
                EvaluationType.NUMERICAL_COMPARISON,
                f"{self.subjects.name(worst.subject)}, at {_adverse(worst)}.",
                [f.id for f in ranked[:5]], difficulty="hard",
                reasoning="Thirty-plus categories must be compared; no single page ranks them.",
                sources=[self.artifact.get("finance_workbook")],
            )
            best = ranked[-1]
            self.case(
                f"Which merchandise category held up best against plan on gross profit in {self.period}?",
                EvaluationType.NUMERICAL_COMPARISON,
                f"{self.subjects.name(best.subject)}, at {_adverse(best)}.",
                [f.id for f in ranked[-5:]], difficulty="hard",
                reasoning="The same comparison in the other direction, which a summary omits.",
                sources=[self.artifact.get("finance_workbook")],
            )

        margins = self.ranked("financial.gross_margin_pct.actual", every_category)
        if len(margins) >= 3:
            thinnest = margins[0]
            self.case(
                f"Which category traded on the thinnest gross margin in {self.period}?",
                EvaluationType.NUMERICAL_COMPARISON,
                f"{self.subjects.name(thinnest.subject)}, at {_fmt(thinnest)}.",
                [f.id for f in margins[:5]], difficulty="hard",
                reasoning="Margin rate, not margin money — the two rank differently.",
                sources=[self.artifact.get("finance_workbook")],
            )

        # Reconciliation, asked as a question rather than assumed as a property.
        for unit_id, members in self.subjects.categories_by_unit.items():
            unit_fact = self.get("financial.revenue.actual", unit_id)
            parts = [f for c in members if (f := self.get("financial.revenue.actual", c))]
            if unit_fact and len(parts) >= 2:
                self.case(
                    f"Do the category revenues for {self.subjects.name(unit_id)} sum to the "
                    f"divisional total in {self.period}?",
                    EvaluationType.NUMERICAL_COMPARISON,
                    "Yes — the categories sum exactly to the division.",
                    [unit_fact.id] + [f.id for f in parts], difficulty="hard",
                    reasoning="Tests the roll-up the whole corpus rests on.",
                    sources=[self.artifact.get("finance_workbook")],
                )
                break

        gp = [f for s in (*units, company) if (f := self.get("financial.gross_profit.variance", s))]
        if len(gp) > len(units):
            self.case(
                f"Does gross profit variance reconcile between the units and the group for {self.period}?",
                EvaluationType.NUMERICAL_COMPARISON,
                "Yes — the unit variances sum to the group variance.",
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
        self.case(
            f"Why was the {self.period} close delayed?", EvaluationType.CAUSAL_MULTI_HOP,
            f"{cause.text_value}, which stopped valuation and pushed the close by "
            f"{int(delay.value.amount)} business day(s).",
            [k["fact_feed_status"], cause.id, delayed.id, delay.id], difficulty="hard",
            reasoning="Failure to cause to workaround to calendar impact.",
            sources=[rca, record], distractors=[stale],
        )
        self.case(
            "What allowed the valuation failure to reach production undetected?",
            EvaluationType.CAUSAL_MULTI_HOP,
            "The mapping table has no registered owner and no required reviewer, so no "
            "control would have caught it.",
            [k["fact_cause"], k["fact_classification"], k["fact_owner"]], difficulty="hard",
            reasoning="The condition behind the cause, which the incident record states "
                      "and the status page does not.",
            sources=[rca], distractors=[stale],
        )
        self.case(
            "Has this failure happened before, and did the earlier response prevent it?",
            EvaluationType.CAUSAL_MULTI_HOP,
            "Yes — a comparable valuation failure was traced to the same mapping table, and "
            "the response restored service without assigning ownership.",
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
                "At the time triage first recorded a cause, what was believed to be the cause?",
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
                "Before the incident was closed, was the close still expected to meet its committed date?",
                EvaluationType.TEMPORAL_STATE,
                "No — the close was recorded as delayed at that point.",
                [delayed.id], cutoff=during, difficulty="hard",
                reasoning="The final status supersedes this; asking earlier must not return it.",
                sources=[note], distractors=[rca],
            )
        self.case(
            "What was the close status once the period was finalised?",
            EvaluationType.TEMPORAL_STATE, final.text_value or "", [final.id],
            cutoff=final.valid_from, difficulty="medium",
            reasoning="The same question at a later cut-off, where the answer changed.",
            distractors=[note],
        )

        # -- authority -------------------------------------------------------
        self.case(
            "What is the confirmed root cause of the valuation failure?",
            EvaluationType.AUTHORITY_RESOLUTION, cause.text_value or "",
            [cause.id, hypothesis.id], difficulty="hard",
            reasoning="Two documents state a cause. Only one was updated after it was ruled out.",
            sources=[rca, record], distractors=[stale],
        )
        self.case(
            "Which record still carries the initial hypothesis rather than the confirmed cause?",
            EvaluationType.AUTHORITY_RESOLUTION,
            "The triage status page, which was never updated after the hypothesis was ruled out.",
            [hypothesis.id, cause.id], difficulty="hard",
            reasoning="Requires recognising a stale source as stale.",
            sources=[stale],
        )
        self.case(
            "Which source was authoritative for the close status at the end of the period?",
            EvaluationType.AUTHORITY_RESOLUTION,
            f"The finance system of record, reporting the close as {final.text_value}.",
            [final.id], cutoff=final.valid_from, difficulty="hard",
            reasoning="Working documents may still show the close as open; they are not the record.",
            distractors=[note],
        )

        # -- citation and cross-artifact -------------------------------------
        self.case(
            "Who owns the product hierarchy mapping table?", EvaluationType.CITATION_REQUIRED,
            "Nobody — the owner is unassigned.", [k["fact_owner"]],
            reasoning="The correct answer is that the field is empty, which is not abstaining.",
            sources=[rca, jira],
        )
        self.case(
            "What evidence ruled out the initial explanation, and where is it recorded?",
            EvaluationType.CITATION_REQUIRED,
            by_id[k["fact_cause_ruled_out"]].text_value or "",
            [k["fact_cause_ruled_out"], hypothesis.id], difficulty="hard",
            reasoning="An answer without its evidence is indistinguishable from a guess that "
                      "happens to be right.",
            sources=[rca], distractors=[stale],
        )
        self.case(
            "How many records were affected, and which document states it?",
            EvaluationType.CITATION_REQUIRED,
            _fmt(by_id[k["fact_affected"]]),
            [k["fact_affected"]],
            reasoning="The figure appears in more than one place; the citation is the test.",
            sources=[rca, record],
        )
        self.case(
            "Which remediation addresses the underlying control failure rather than only detection?",
            EvaluationType.CROSS_ARTIFACT,
            "The ownership assignment. The validation ticket addresses detection only.",
            [k["fact_classification"], k["fact_remediation"], k["fact_remediation_scope"]],
            difficulty="hard",
            reasoning="Both tickets are plausible; the classification separates them.",
            sources=[rca, jira],
        )
        self.case(
            f"What was the P&L impact of the incident on the {self.period} result?",
            EvaluationType.CROSS_ARTIFACT,
            "Zero — valuation completed before the ledger closed. The impact was on the calendar only.",
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
                    "Which close calendar states the committed date currently in force?",
                    EvaluationType.AUTHORITY_RESOLUTION,
                    f"The calendar published for {self.period}, committing to {due.text_value}.",
                    [due.id], difficulty="hard",
                    reasoning="Earlier calendars are published, look identical, and are superseded.",
                    sources=[current_calendar], distractors=calendars,
                )

        if earlier_incidents and self.episode.had_incident:
            k = self.episode.keys
            previous = earlier_incidents[-1]
            self.case(
                "When did a comparable valuation failure last occur, and did the response "
                "prevent it recurring?",
                EvaluationType.CAUSAL_MULTI_HOP,
                f"In {previous.period}. It did not — the same mapping table failed again in "
                f"{self.period}, and ownership is still unassigned.",
                [previous.id, k["fact_recurrence"], k["fact_owner"]], difficulty="hard",
                reasoning="Spans two episodes. A single close cannot answer it at all.",
                sources=[self.artifact.get("incident_rca")],
            )
            self.case(
                f"How many valuation incidents has the group opened up to and including {self.period}?",
                EvaluationType.NUMERICAL_COMPARISON,
                f"{len(earlier_incidents) + 1}.",
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
        if prior_revenue:
            earlier = prior_revenue[-1]
            self.case(
                f"What was total revenue in {earlier.period}?",
                EvaluationType.TEMPORAL_STATE, _fmt(earlier), [earlier.id],
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
        for question, reasoning in (
            ("What was the root cause of the previous period's close delay?",
             "Presupposes an event this corpus does not contain."),
            ("What is the Group Chief Executive Officer's total remuneration?",
             "The person exists; the fact does not."),
            ("Which supplier was responsible for the shortfall in fresh produce?",
             "Suppliers are not modelled at all, and the question presumes one is."),
            ("What was the group's net promoter score this period?",
             "A plausible retail metric the corpus does not measure."),
            ("How much did the group spend on staff costs this period?",
             "Revenue and gross profit are modelled; operating costs are not."),
            ("What is the group's market share against its nearest competitor?",
             "No competitor exists in this world."),
            ("When is the next scheduled audit of the mapping table?",
             "Forward-looking; the corpus records what happened, not what is planned."),
        ):
            self.abstain(question, reasoning)

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
                f"Who led {self.subjects.name(change.subject)} as of "
                f"{change.period or self.period}?",
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
                f"Who replaced {self.subjects.name(departure.subject)} when they left "
                "the company?",
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
                f"According to the corpus's own history, when did this happen: {assertion}?",
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
                f"Who signed the {label} for {earlier_period}?",
                EvaluationType.TEMPORAL_STATE, self.subjects.name(earlier.author_id),
                [earlier.required_fact_ids[0]], difficulty="hard",
                reasoning="The post has changed hands since; the current holder is the "
                          "confident wrong answer to a question about the earlier period.",
            )
            self.case(
                f"Who signed the {label} for {self.period}?",
                EvaluationType.TEMPORAL_STATE, self.subjects.name(current.author_id),
                [current.required_fact_ids[0]], difficulty="medium",
                reasoning="The same document type after the post changed hands — included so "
                          "a system that gets the earlier period wrong is shown getting the "
                          "current one right.",
            )
            break  # one document type makes the point; a second would only repeat it.

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
            "Who is the company's Chief Marketing Officer, and when did they join?",
            "No marketing function is modelled in this organisation; the role, and "
            "therefore the person, does not exist.",
        )
        self.abstain(
            "Who signed the close calendar in 1995?",
            "Presupposes a roster and a close from before this archetype's organisation "
            "could exist — every join date this generator can produce falls well after it.",
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
) -> tuple[EvaluationCase, ...]:
    """Derive the evaluation set for one episode.

    ``history`` and ``prior_intents`` are what the world already contained. A
    second episode asks questions the first could not — which is the only way the
    hard families get past a handful of cases each.
    """
    taxonomy = _Taxonomy(
        minter, episode=episode, facts=facts, subjects=subjects, intents=intents,
        period=period, history=history, prior_intents=prior_intents,
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
