"""Asking the same question in a different company's words.

``across.survey`` over a five-world mosaic reported **222 questions, 94
distinct, 31 of them byte-identical in all five worlds**. Two levers had
already been pulled on that number and both worked on the *nouns*: a richer
taxonomy took distinct question strings from 42 to 66, and per-world
vocabularies (``worldloom.vocabulary``) took 66 to 94 by giving each world its
own divisions, categories and site formats to be asked about.

The 31 are what neither lever can reach, and the reason is visible in them:

    What was total revenue for 2026-03?
    How much did the group spend on staff costs this period?
    Who signed the close calendar in 1995?

Not one quotes a noun the world owns. They are the evaluation taxonomy's own
phrasing, typed once in ``generators/evaluation.EVAL_TEXT`` and emitted
identically into every world, so a model evaluated across five worlds sees the
same sentence five times and the retrieval spread for those families is exactly
zero. The *answer* is already a per-world draw. This makes the *question* one
as well.

**What it does not touch, and why that is the whole safety argument.** A
rephrasing that changes what is being asked is a broken evaluation case, not a
varied one, and "somebody reviewed it" is not a guarantee. So the mechanism is
confined to the one field that grading never reads. ``EVAL_TEXT``'s ``q.*``
entries are the *question surface*: the expected answer, the expected fact ids,
the required and distractor artifacts, the temporal cut-off and the difficulty
label are all minted by the same taxonomy code from the same ledger whatever
this module returns. ``cases.answerable`` gates on ``expected_fact_ids``, which
is unreachable from here — so a case cannot become unanswerable by being
reworded. That is structural, not reviewed.

What *is* reviewed-by-machine is the remaining risk: that a paraphrase asks a
different question. Three computed refusals close it, and none of them is a
list somebody maintains — see ``findings``:

* **Slots must match exactly.** ``episode_text.check_overrides`` already
  refuses an override that invents a placeholder; this refuses one that
  *drops* one too. "What was total revenue?" with the ``{period}`` taken out is
  a different, ambiguous question the moment a corpus has two periods.
* **A variant must keep a word that distinguishes its own question.** The
  distinguishing words are computed, per key, as the content words of that
  key's default that no *sibling* default has — where a sibling is a question
  in the same family taking the same placeholders, which is exactly the set
  that nothing but the wording tells apart. ``q.direct.group_revenue``'s are
  ``{total, revenue}``, because ``group_gross_profit`` and
  ``group_gross_margin`` share everything else with it.
* **A variant may not use a sibling's distinguishing word.** A rewording of
  "total revenue" that says "gross profit" is refused naming both keys. This
  is the check that has teeth: it is a mutual exclusion nobody wrote down,
  falling out of the defaults the same way ``probe``'s refusals fall out of its
  relations.

A consequence worth stating rather than discovering: the second rule forbids
synonym substitution on the subject of the question — no "turnover" for
"revenue". That is deliberate. A synonym the lexical index cannot connect to
the document's own word makes the question harder *for a reason that has
nothing to do with the corpus*, which is difficulty bought with a trick. The
variation here is in how a question is built, not in whether its subject is
still in the index.

**Why dispersion, and not five independent draws.**

A template pool per family drawn from a named ``Rng`` is the obvious move and it
is not the right one on its own, for the reason ``mosaic`` already argues about
company shapes: independent draws clump, and a clump is a question the tool
never asks. Worse here than there, because the failure is invisible — five
worlds drawing independently from a pool of three will, more often than not,
give two of them the same wording for most keys, and the survey would report a
distinct-question count that moved while the pairs it was supposed to break
stayed paired.

So: cover, then choose, the same two steps and in the same order. A candidate is
a *complete* phrasing of the benchmark — one variant chosen per key — and the
candidates are drawn from a named ``Rng`` stream of this module's own.
``dispersion.farthest_first`` then takes the *N* furthest apart, which is
Gonzalez's traversal and a 2-approximation to max-min dispersion.

``dispersion.halton`` is deliberately *not* the covering step here, and the
reason is in its own docstring: it is defined for at most thirty dimensions
because beyond that the high bases correlate and it stops covering better than
a grid. A phrasing assignment has one dimension per question key — fifty-seven
for the retail taxonomy — and they are discrete rather than continuous, so a
low-discrepancy sequence over the unit hypercube is answering a question this
space does not ask. A named stream plus dispersion keeps the half of the
argument that applies.

**The distance is the retriever's view, not the survey's.** Two phrasings are
far apart here when their *token sets* are far apart — Jaccard distance over
``bm25.tokens``, summed across keys. It is emphatically not the shingled join
``across.overlap`` reports, and that is the point: optimising the metric you
report is how a number moves without a dataset moving. A retriever confuses two
questions when their bags of terms overlap; the shingle join at ≥80% is a
coarser instrument over the same phenomenon (``overlap``'s own docstring says
it under-reports). Maximising separation in the first makes the second fall as
a *consequence*, which is a finding. Maximising the second directly would have
been a result.

Jaccard distance is a metric and a sum of metrics is a metric, so
``farthest_first``'s approximation guarantee actually means something on it.

**Which world gets which phrasing, and why it is dealt rather than drawn.**

A register is dealt to a *vocabulary*, not to a world index or a seed. Three
things fall out of that and each one was otherwise a problem:

* **Byte identity, for free.** A world that speaks no dealt vocabulary —
  which is every ``worldloom build`` that does not ask for one, and every
  pack-built world, since ``vocabulary.spoken`` returns an authored archetype
  untouched — gets no phrasing at all and is byte-identical to what it was.
  The switch is not a flag anyone can forget to thread; it is the presence of
  the thing whose absence made the questions identical in the first place.
* **A world still rebuilds alone.** ``vocabulary.spoken`` qualifies the
  archetype key (``omnichannel_retailer+wholesale_club``) and
  ``recipe.build_recipe`` stores that key, so the register is recoverable from
  the recipe with no mosaic, no ``-n``, and no seed on hand. A register indexed
  by world position would not be: world 3 of a five-world mosaic would need to
  know it was one of five.
* **The dispersion guarantee survives subsetting.** Every vocabulary the engine
  has is dealt a register in one traversal, so a mosaic taking any subset of
  them takes a subset of a jointly-dispersed set, and the minimum separation
  across that mosaic is at least the minimum across the whole deal. Retail has
  five vocabularies and a five-world mosaic deals all five, so for that case the
  subset is the set.

Register 0 is the taxonomy's own wording, unchanged, and ``farthest_first``
always takes its first candidate first — so one world of every mosaic asks the
benchmark exactly as ``EVAL_TEXT`` wrote it. That is a control kept on purpose:
a before/after where every world moved has nothing in it to read the movement
against.

**Where the pool belongs, eventually.** The alternatives below are retail's,
and retail's question set is declared in ``generators/evaluation.EVAL_TEXT``.
The right long-term home for the data is beside that table, one pool per engine,
the same way ``episode_text`` keeps each engine's narration with the engine. The
*mechanism* stays here regardless — it knows nothing about retail, takes the
defaults as an argument, and would deal banking's or insurance's registers the
day those pools are written. They are not, and ``deal`` returns nothing for
those engines rather than guessing, so a banking or insurance mosaic still asks
its questions one way in every world.

**Measured**, on ``worldloom mosaic -n 5 --incident``, two trees differing only
by this module and the one line in ``scenarios`` that calls it:

===============================================  ======  =====
                                                 before  after
===============================================  ======  =====
questions                                           222    222
distinct question strings                            94    151
distinct (question, answer) pairs                   134    174
byte-identical in every world                        31      0
cross-world near-duplicate pairs (of 19,704)        314     88
questions inside a cross-world duplicate group      163    125
===============================================  ======  =====

The residue is the pigeonhole and nothing else: three variants dealt to five
worlds means a question quoting no world-owned noun is worded the same by at
least two of them, and the worst case measured is three. Deepening the pool to
five would take that to one, and it is the *lesser* of the two remaining
levers — the better one is the taxonomy's, which is to give those questions a
noun the world owns, as ``EVAL_TEXT``'s ``.estate`` keys already do for four of
them.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from functools import lru_cache
from typing import TYPE_CHECKING

from ..dispersion import farthest_first
from ..generators.episode_text import fields_of
from ..similarity import jaccard
from .bm25 import tokens

if TYPE_CHECKING:  # pragma: no cover
    from ..world import World


# ---------------------------------------------------------------------------
# The data: retail's alternative phrasings
# ---------------------------------------------------------------------------

#: Alternative wordings for ``generators/evaluation.EVAL_TEXT``'s ``q.*`` keys.
#: The default is *not* repeated here — ``_variants`` puts it at position 0 —
#: so there is exactly one copy of every shipped question in the project and
#: this table cannot drift from it.
#:
#: Two alternatives per key rather than four, and the arithmetic is the reason:
#: with three options across fifty-seven keys the assignment space is 3**57,
#: which is many orders of magnitude more than the five registers a retail
#: mosaic can use, so the binding constraint on how far apart the registers get
#: is dispersion over the candidate pool and not the size of the pool per key.
#: A fourth alternative per key would be a hundred and fourteen more sentences
#: bought for no measurable separation.
#:
#: ``q.history.signed_earlier`` and ``q.history.signed_current`` share a tuple
#: because they are the same question asked of two periods — the defaults are
#: byte-identical, which is why ``_discriminators`` finds nothing to distinguish
#: them with and correctly demands nothing.
_SIGNATORY = (
    "Whose signature is on the {doc_type} for {period}?",
    "Who put their name to the {doc_type} for {period}?",
)

ALTERNATIVES: dict[str, tuple[str, ...]] = {
    # -- direct lookup ------------------------------------------------------
    "q.direct.group_revenue": (
        "How much revenue did the group record in total for {period}?",
        "For {period}, what revenue does the consolidated position show in total?",
    ),
    "q.direct.group_gross_profit": (
        "How much gross profit did the group make in {period}?",
        "For {period}, what gross profit is booked at group level?",
    ),
    "q.direct.group_gross_margin": (
        "What gross margin did the group run at in {period}?",
        "For {period}, where did the group's gross margin land?",
    ),
    "q.direct.unit_revenue": (
        "How much revenue did {name} book in {period}?",
        "For {period}, what revenue is recorded against {name}?",
    ),
    "q.direct.category_revenue": (
        "How much revenue did {category} take in {unit} during {period}?",
        "For {period}, what revenue does {unit} show for its {category} category?",
    ),
    "q.direct.site_revenue": (
        "How much revenue did {site}, part of {unit}, take in {period}?",
        "For {period}, what revenue is recorded for the {site} site within {unit}?",
    ),
    # -- numerical comparison -----------------------------------------------
    "q.numerical.revenue_vs_budget": (
        "In {period}, how far below budget did revenue land, in absolute terms and"
        " as a percentage?",
        "By what amount, and what percentage, did revenue fall short of budget in"
        " {period}?",
    ),
    "q.numerical.worst_unit_variance": (
        "In {period}, which business unit posted the {superlative} adverse {label}"
        " variance?",
        "Which division ended {period} carrying the {superlative} adverse {label}"
        " variance?",
    ),
    "q.numerical.worst_category": (
        "Against plan, which merchandise category shed the most gross profit in"
        " {period}?",
        "Which merchandise category lost the greatest share of its gross profit plan"
        " in {period}?",
    ),
    "q.numerical.worst_site_variance": (
        "Which site carried the biggest adverse revenue variance in {period}?",
        "In {period}, at which site was the adverse revenue variance largest?",
    ),
    "q.numerical.best_category": (
        "Which merchandise category best defended its gross profit plan in {period}?",
        "In {period}, which merchandise category held up strongest on gross profit"
        " against plan?",
    ),
    "q.numerical.thinnest_margin_category": (
        "Which category ran the thinnest gross margin in {period}?",
        "In {period}, whose gross margin was the narrowest of the categories?",
    ),
    "q.numerical.category_reconciliation": (
        "In {period}, do {unit}'s category revenues add up to its divisional total?",
        "Does the sum of the category revenues for {unit} equal the divisional total"
        " in {period}?",
    ),
    "q.numerical.unit_group_reconciliation": (
        "For {period}, do the divisional gross profit variances add back to the group"
        " figure?",
        "Does the sum of the business unit gross profit variances reconcile to the"
        " group's in {period}?",
    ),
    # -- incident: causal chains --------------------------------------------
    "q.incident.why_delayed": (
        "What held up the {period} close?",
        "For {period}, what caused the close to run late?",
    ),
    "q.incident.undetected": (
        "Why did nothing stop the valuation failure before it hit production?",
        "What control should have caught the valuation failure short of production,"
        " and did not?",
    ),
    "q.incident.recurrence": (
        "Has this happened before, and did the earlier response stop it coming back?",
        "Was there a prior occurrence, and did the response then prevent this one?",
    ),
    # -- incident: temporal state -------------------------------------------
    "q.incident.hypothesis_at_time": (
        "What cause did triage put on the record when it first wrote one down?",
        "When a cause was first recorded in triage, what did it say?",
    ),
    "q.incident.expected_on_time": (
        "While the incident was still open, was the close expected to hit its"
        " committed date?",
        "Was the close still on for its committed date before the incident was"
        " closed?",
    ),
    "q.incident.status_at_finalised": (
        "Once the period was finalised, what status did the close carry?",
        "At the point the period was finalised, what was the close's status?",
    ),
    # -- incident: authority ------------------------------------------------
    "q.authority.confirmed_cause": (
        "What has been confirmed as the root cause of the valuation failure?",
        "Which explanation of the valuation failure is the confirmed one?",
    ),
    "q.authority.stale_record": (
        "Which record still shows the initial hypothesis instead of the confirmed"
        " cause?",
        "Where does the initial hypothesis still stand as this incident's stated"
        " cause?",
    ),
    "q.authority.close_status_source": (
        "At the end of the period, which source was authoritative for the close"
        " status?",
        "Which document is the authoritative source for the close status at period"
        " end?",
    ),
    # -- incident: citation and cross-artifact ------------------------------
    "q.citation.mapping_owner": (
        "Which person owns the product hierarchy mapping table?",
        "The product hierarchy mapping table — who owns it?",
    ),
    "q.citation.evidence_ruled_out": (
        "What evidence ruled the initial explanation out, and where is that noted?",
        "Which page holds the evidence that ruled out the initial explanation?",
    ),
    "q.citation.affected_records": (
        "How many records were affected in the {period} incident, and where is"
        " that number stated?",
        "Which document gives the count of records affected in the {period}"
        " incident, and what is it?",
    ),
    "q.cross.remediation_choice": (
        "Of the remediations, which one fixes the control failure rather than only"
        " detecting it?",
        "Which remediation closes the underlying control gap, not merely the"
        " detection gap?",
    ),
    "q.cross.pl_impact": (
        "What did the incident cost the {period} result in P&L terms?",
        "In {period}, what P&L effect did the incident have on the result?",
    ),
    # -- across episodes ----------------------------------------------------
    "q.across.current_calendar": (
        "Which close calendar carries the committed date in force for the {period}"
        " close?",
        "Where is the committed date that applies to the {period} close set out?",
    ),
    "q.across.recurrence": (
        "When, before the {period} incident, did a comparable valuation failure"
        " last happen — and did the response prevent a repeat?",
        "Had a comparable valuation failure occurred before the {period} incident,"
        " and did the response stop it recurring?",
    ),
    "q.across.incident_count": (
        "How many valuation incidents had the group opened by the end of {period}?",
        "Up to and including {period}, what is the tally of valuation incidents the"
        " group opened?",
    ),
    "q.across.prior_period_revenue": (
        "How much total revenue was recorded in {period}?",
        "For {period}, what was the revenue figure in total?",
    ),
    # -- abstentions --------------------------------------------------------
    "q.abstain.previous_close_cause": (
        "What was the root cause of the close delay in the previous period?",
        "The previous close ran late — what was the root cause?",
    ),
    "q.abstain.ceo_remuneration": (
        "What is the total remuneration paid to the Group Chief Executive Officer?",
        "What does the Group Chief Executive Officer's total remuneration come to?",
    ),
    "q.abstain.supplier_shortfall": (
        "Which supplier caused the fresh produce shortfall?",
        "Which supplier is named as responsible for the shortfall in fresh produce?",
    ),
    "q.abstain.nps": (
        "What net promoter score did the group post this period?",
        "This period, where did the group's net promoter score land?",
    ),
    "q.abstain.staff_costs": (
        "What did the group spend on staff costs this period?",
        "Across the group this period, what went on staff costs?",
    ),
    "q.abstain.market_share": (
        "What share of the market does the group hold against its nearest competitor?",
        "Against its nearest competitor, where does the group's market share sit?",
    ),
    "q.abstain.next_audit": (
        "When is the mapping table next scheduled for audit?",
        "What is the date of the next scheduled audit of the mapping table?",
    ),
    "q.abstain.cmo": (
        "Who holds the Chief Marketing Officer role at this company, and when did"
        " they join?",
        "When did the company's Chief Marketing Officer join?",
    ),
    "q.abstain.close_calendar_1995": (
        "Who signed the close calendar back in 1995?",
        "Whose name is on the 1995 close calendar?",
    ),
    # -- history ------------------------------------------------------------
    "q.history.unit_leader_as_of": (
        "As of {period}, who was leading {unit}?",
        "Who was in charge of {unit} at {period}?",
    ),
    "q.history.succession": (
        "Who took over from {person} after they left?",
        "When {person} left the company, who stepped into the role?",
    ),
    "q.history.milestone_provenance": (
        "By the corpus's own record, when did this take place: {assertion}?",
        "On the corpus's own account of its history, when did this occur:"
        " {assertion}?",
    ),
    "q.history.signed_earlier": _SIGNATORY,
    "q.history.signed_current": _SIGNATORY,
    # -- communications -----------------------------------------------------
    "q.comms.meeting_attendance_cause": (
        "Who was in the meeting that moved the close, and what cause do the minutes"
        " give?",
        "The meeting that moved the close — who attended, and what did its minutes"
        " record as the cause?",
    ),
    "q.comms.cfo_notified": (
        "When was the Group CFO first informed the {period} close was at risk, and"
        " by what channel?",
        "Through which channel, and at what point, was the Group CFO first told of"
        " the risk to the {period} close?",
    ),
    # -- accountability -----------------------------------------------------
    "q.accountability.who_accountable": (
        "{measure} for {unit} moved outside the band it is held to in {period} — who"
        " answers for it?",
        "Given that {unit}'s {measure} in {period} moved beyond its tolerance band,"
        " who was accountable?",
    ),
    # -- the estate, read as a graph ----------------------------------------
    "q.estate.blast_radius": (
        "Across the {scale} this company runs, would {name} have gone down if"
        " {service} failed?",
        "If {service} failed, does that reach {name}, among the {scale} here?",
    ),
    "q.estate.routed_around": (
        "Does anything reach {system} without going through {service}, or is"
        " {service} the only path?",
        "Is {system} reachable only via {service}, or does the estate have another"
        " route to it?",
    ),
    "q.estate.chain_to_record": (
        "What is the longest chain of services ending at {system}, and what sits at"
        " its head?",
        "How many hops is the deepest service chain into {system}, and which service"
        " starts it?",
    ),
    "q.estate.abstain_recovery": (
        "Among the {scale} this company runs, which has a tested failover for"
        " disaster recovery of {system}?",
        "Which of the {scale} here has had its disaster-recovery failover for"
        " {system} tested?",
    ),
    # -- estate-scaled restatements of the incident families ----------------
    "q.incident.why_delayed.estate": (
        "Among the {scale} this company runs, whose failure pushed the {period}"
        " close, and how?",
        "Which of the {scale} here failed and delayed the {period} close, and by"
        " what mechanism?",
    ),
    "q.incident.undetected.estate": (
        "{reach} service(s) depend on {system}, which holds the mapping table. Why"
        " did nothing catch the valuation failure short of production?",
        "The mapping table lives under {system}, depended on by {reach} service(s)."
        " What let the valuation failure through to production?",
    ),
    "q.authority.confirmed_cause.estate": (
        "Of the {scale} in this estate, what has been confirmed as the root cause of"
        " the valuation failure?",
        "Within an estate of {scale}, which confirmed root cause explains the"
        " valuation failure?",
    ),
    "q.citation.mapping_owner.estate": (
        "Who is recorded as owning the product hierarchy mapping table held in"
        " {system}?",
        "The product hierarchy mapping table sits in {system} — who owns it?",
    ),
}


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------

#: Function words, excluded when working out what a question is *about*.
#:
#: Used only by the discriminator check below, never by the distance — the
#: distance has to be the retriever's view of a query and ``bm25.tokens``'
#: docstring is explicit that there is no stop list, so removing words there
#: would measure separation a retriever does not see.
_FUNCTION_WORDS = frozenset(
    """a about across an and any are as at back be been by did do does for from
    had has have how in into is it its of on or other over rather than that the
    their them then there these they this to was were what when where which who
    whom whose why will with within without you your""".split()
)

#: Placeholders, removed before a template is tokenised. Both checks and the
#: distance work on the words an author *chose*; ``{period}`` is present in
#: every variant of any key that takes it, so counting it would report
#: similarity that carries no information.
_SLOT = re.compile(r"\{[^{}]*\}")


def _words(template: str) -> frozenset[str]:
    """The template's tokens, as the retriever would see the filled question."""
    return frozenset(tokens(_SLOT.sub(" ", template)))


def _content(template: str) -> frozenset[str]:
    """The template's tokens minus function words — what it is *about*."""
    return _words(template) - _FUNCTION_WORDS


def _family(key: str) -> str:
    """``q.numerical.worst_category`` → ``numerical``.

    The second segment, so an estate-scaled restatement
    (``q.incident.why_delayed.estate``) sits in the same family as the question
    it restates — which is right, because it is the same question and the two
    are told apart by their placeholders rather than by their family.
    """
    parts = key.split(".")
    return parts[1] if len(parts) > 2 else key


def _siblings(defaults: Mapping[str, str]) -> dict[str, tuple[str, ...]]:
    """For each key, the other keys nothing but the wording tells apart.

    Same family *and* the same placeholder set. The second half is what keeps
    this honest: ``q.direct.group_revenue`` and ``q.direct.unit_revenue`` are
    not confusable, because one of them names a business unit and the other
    does not, and demanding that their wordings differ would refuse paraphrases
    for no reason. ``group_revenue``, ``group_gross_profit`` and
    ``group_gross_margin`` all take ``{period}`` and nothing else, so the words
    are the only thing standing between them.
    """
    grouped: dict[tuple[str, frozenset[str]], list[str]] = {}
    for key in sorted(defaults):
        if not key.startswith("q."):
            continue
        grouped.setdefault((_family(key), fields_of(defaults[key])), []).append(key)
    return {
        key: tuple(other for other in members if other != key)
        for members in grouped.values()
        for key in members
    }


def _discriminators(defaults: Mapping[str, str]) -> dict[str, frozenset[str]]:
    """Per key, the content words no sibling's default uses.

    Computed, never listed. ``q.abstain.staff_costs`` gets ``{much, spend,
    staff, costs}`` because "group" and "period" are shared with the abstention
    questions either side of it, and a rewording that keeps only the shared
    words has stopped asking about staff costs.

    Empty for a key whose default is indistinguishable from a sibling's —
    ``signed_earlier`` and ``signed_current`` are byte-identical — and the
    checks below demand nothing of a variant in that case. Demanding that a
    variant distinguish what the default does not would be asking a paraphrase
    to fix the taxonomy.
    """
    siblings = _siblings(defaults)
    out: dict[str, frozenset[str]] = {}
    for key, others in siblings.items():
        shared: set[str] = set()
        for other in others:
            shared |= _content(defaults[other])
        out[key] = _content(defaults[key]) - shared
    return out


def findings(
    defaults: Mapping[str, str], alternatives: Mapping[str, Sequence[str]]
) -> list[str]:
    """Everything wrong with *alternatives*, as sentences naming the key.

    The same shape as ``episode_text.check_overrides`` and for the same reason:
    a defect here would otherwise surface as a corpus whose evaluation set asks
    a question its answer does not fit, which no downstream check can catch —
    ``validate`` verifies that an expected fact is reachable, not that the
    sentence in front of it is the question that fact answers.
    """
    out: list[str] = []
    discriminators = _discriminators(defaults)
    siblings = _siblings(defaults)

    for key in sorted(alternatives):
        if key not in defaults:
            out.append(f"{key!r} names no template of this engine")
            continue
        if not key.startswith("q."):
            out.append(
                f"{key!r} is not a question — only the question surface varies,"
                " because it is the only part of a case that grading never reads"
            )
            continue
        wanted = fields_of(defaults[key])
        seen = {defaults[key]}
        for variant in alternatives[key]:
            if not variant.strip():
                out.append(f"{key!r} has an empty variant")
                continue
            if not variant.endswith("?"):
                out.append(f"{key!r}: {variant!r} does not end as a question")
            if variant in seen:
                out.append(f"{key!r} repeats {variant!r}")
                continue
            seen.add(variant)
            try:
                got = fields_of(variant)
            except ValueError as exc:
                out.append(f"{key!r}: {variant!r} is not a valid template: {exc}")
                continue
            if got != wanted:
                out.append(
                    f"{key!r}: {variant!r} takes {sorted(got)} where its default"
                    f" takes {sorted(wanted)} — a variant asks the same question,"
                    " so it is filled from the same values"
                )
                continue
            # Only where there is something to be confused with. A key with no
            # sibling has every content word of its default to itself, and
            # demanding a variant keep one of *those* would forbid rewording
            # the only question in the corpus that takes its placeholders —
            # a rule with no confusion to prevent.
            own = discriminators.get(key, frozenset()) if siblings.get(key) else frozenset()
            if own and not (_content(variant) & own):
                out.append(
                    f"{key!r}: {variant!r} keeps none of {sorted(own)}, the words"
                    f" that distinguish it from {list(siblings.get(key, ()))}"
                )
            for other in siblings.get(key, ()):
                trespass = _content(variant) & discriminators.get(other, frozenset())
                if trespass:
                    out.append(
                        f"{key!r}: {variant!r} uses {sorted(trespass)}, which"
                        f" distinguish {other!r} — it is asking that question"
                    )
    return out


# ---------------------------------------------------------------------------
# Cover, then choose
# ---------------------------------------------------------------------------

#: How many complete phrasings are covered before dispersion chooses from them.
#: Not a sample of the space — 3**57 assignments exist and no pool is a sample
#: of that — but a field for the traversal to choose from, so it is sized off
#: the measured curve rather than off the space. Minimum separation of the five
#: registers retail deals, against pool size: 0.360 at 32, 0.347 at 64, 0.364 at
#: 128, 0.373 at 256, 0.376 at 512. It is flat, and the flatness is the finding:
#: the binding constraint on how far apart five registers get is the *depth* of
#: the pool per key, not the number of complete assignments considered. 128 is
#: where that curve first settles, and going past it is not free of *effects*
#: even though it is nearly free of cost: at 512 the extra 3% of separation came
#: with a question worded identically by four of the five registers where 128's
#: worst case was three, which is the pigeonhole below showing through — more
#: candidates cannot manufacture a fourth way of asking a question that has
#: three.
_POOL = 128

#: The stream candidates are drawn from. A fixed seed, not the world's, and
#: that is the whole reason the deal is reproducible from a recipe: a register
#: is a property of a vocabulary, so a world that speaks ``wholesale_club``
#: asks the same questions whether it was built as world 2 of a mosaic seeded
#: 8128 or rebuilt alone from its own recipe with no mosaic in sight.
_STREAM_SEED = 0
_STREAM = "evaluate/phrasing"


def _variants(
    defaults: Mapping[str, str], alternatives: Mapping[str, Sequence[str]]
) -> tuple[tuple[str, ...], ...]:
    """Per key, in sorted key order, the default followed by its alternatives."""
    return tuple(
        (defaults[key], *alternatives[key]) for key in sorted(alternatives)
    )


def _distances(variants: Sequence[Sequence[str]]) -> tuple[tuple[tuple[float, ...], ...], ...]:
    """Per key, the Jaccard distance between every pair of its variants.

    Precomputed because the traversal asks for the same key-pair distance
    thousands of times, and because it makes the metric inspectable: a pool
    entry that is a cosmetic paraphrase shows up here as a near-zero row, and
    dispersion will decline to spend a register on it.
    """
    out = []
    for options in variants:
        words = [_words(option) for option in options]
        out.append(tuple(
            tuple(1.0 - jaccard(left, right) for right in words) for left in words
        ))
    return tuple(out)


def _candidates(variants: Sequence[Sequence[str]], pool: int) -> tuple[tuple[int, ...], ...]:
    """Complete phrasings of the benchmark, covering the assignment space.

    Candidate 0 is the all-defaults assignment, deliberately: ``farthest_first``
    takes its first candidate first with no distance-based reason to prefer any
    other, so register 0 is the taxonomy's own wording and every mosaic keeps
    one world speaking it.
    """
    from ..rng import Rng

    rng = Rng(_STREAM_SEED).derive(_STREAM)
    out = [tuple(0 for _ in variants)]
    while len(out) < pool:
        out.append(tuple(rng.integer(0, len(options) - 1) for options in variants))
    return tuple(out)


def registers(
    defaults: Mapping[str, str],
    alternatives: Mapping[str, Sequence[str]],
    count: int,
) -> tuple[dict[str, str], ...]:
    """*count* complete phrasings of the benchmark, as far apart as it can get.

    Each one is an override map in ``EVAL_TEXT``'s own shape, so the caller
    hands it to the taxonomy through the seam a pack already uses and no
    generator learns that this module exists.
    """
    defects = findings(defaults, alternatives)
    if defects:
        # Raised rather than warned, and at the point the registers are built
        # rather than at import: by the time a build asks for a phrasing, a
        # pool that changes what a question asks is a corpus defect, and the
        # cheapest place to find out is before the case is minted. Same posture
        # as `episode_text.merged`, which raises on what its lint warns about.
        raise ValueError("; ".join(defects))

    keys = sorted(alternatives)
    variants = _variants(defaults, alternatives)
    table = _distances(variants)
    candidates = _candidates(variants, _POOL)

    def distance(left: tuple[int, ...], right: tuple[int, ...]) -> float:
        return sum(
            table[index][a][b]
            for index, (a, b) in enumerate(zip(left, right, strict=True))
        )

    chosen = farthest_first(candidates, distance, count)
    return tuple(
        {key: variants[index][candidates[at][index]] for index, key in enumerate(keys)}
        for at in chosen
    )


def separation(registers_: Sequence[Mapping[str, str]]) -> dict[str, float]:
    """Minimum and mean pairwise distance across a dealt set of registers.

    The number the dispersion step exists to raise, exposed so a test can pin it
    and a report can quote it instead of asserting that farthest-first worked.
    Normalised per key, so it reads as "on an average question, how much of the
    token set differs" and does not grow when a pool covers more keys.
    """
    if len(registers_) < 2:
        return {"minimum": 0.0, "mean": 0.0, "keys": float(len(registers_[0]) if registers_ else 0)}
    keys = sorted(registers_[0])
    gaps = []
    for i in range(len(registers_)):
        for j in range(i + 1, len(registers_)):
            total = sum(
                1.0 - jaccard(_words(registers_[i][key]), _words(registers_[j][key]))
                for key in keys
            )
            gaps.append(total / len(keys))
    return {
        "minimum": round(min(gaps), 4),
        "mean": round(sum(gaps) / len(gaps), 4),
        "keys": float(len(keys)),
    }


# ---------------------------------------------------------------------------
# The deal, and the one line a scenario calls
# ---------------------------------------------------------------------------


@lru_cache(maxsize=4)
def deal(engine: str = "retail") -> dict[str, dict[str, str]]:
    """``{vocabulary name: override map}`` for every vocabulary *engine* has.

    Dealt in one traversal over all of them rather than per mosaic, which is
    what makes any subset of worlds a subset of a jointly-dispersed set — and
    what lets a world rebuild alone, since nothing here depends on how many
    worlds were built or in what order.

    Empty for an engine with no alternatives written for it. That is the
    current state of banking and insurance, and it is a silence rather than a
    failure on purpose: their taxonomies live in their own modules with their
    own ``EVAL_TEXT`` tables, and inventing paraphrases for questions this
    module cannot see would be the costume problem again.
    """
    from .. import vocabulary

    if engine != "retail":
        return {}

    from ..generators.evaluation import EVAL_TEXT

    names = sorted(vocabulary.for_engine(engine))
    if not names:
        return {}
    dealt = registers(EVAL_TEXT, ALTERNATIVES, len(names))
    return dict(zip(names, dealt, strict=True))


def overrides(world: World, *, engine: str = "retail") -> dict[str, str] | None:
    """The register this world's words entitle it to, or ``None``.

    ``None`` for a world that speaks no dealt vocabulary — which is every stock
    ``worldloom build``, and every pack-built world, because
    ``vocabulary.spoken`` leaves an authored archetype alone. That is the
    byte-identity guarantee, and it is a property of the data rather than of a
    flag somebody has to remember to leave off.

    ``None`` too for a vocabulary this deal does not know, which can only
    happen if the registry moved under a corpus being replayed. Rewording a
    benchmark on a guess about what a name used to mean would be worse than not
    rewording it, and the questions a stock build asks are never wrong — only
    identical.
    """
    spoken = getattr(getattr(world, "_archetype", None), "vocabulary", "") or ""
    if not spoken:
        return None
    return deal(engine).get(spoken)


__all__ = [
    "ALTERNATIVES",
    "deal",
    "findings",
    "overrides",
    "registers",
    "separation",
]
