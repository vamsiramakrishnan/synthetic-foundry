"""Noise: provenance-true documents that answer nothing.

Every corpus so far has been built to be *hard* — stale hypotheses, contested
authority, restatements — but a real enterprise estate is not mostly hard
questions wearing a trap. It is mostly a haystack: drafts nobody threw away,
somebody's personal copy of the memo, and a folder of routine notices that say
"no change" in slightly different words every month. Retrieval that only ever
sees the interesting documents is not being tested against anything like a real
archive.

This module adds that haystack, opt-in and after the fact, the same way
``generators/communications.py`` fans meeting minutes and email threads out of
an episode that already ran: no new fact, no new entity, no new event. Every
distractor cites a *subset* of facts a real document already cites, which is
what makes two properties true simultaneously and for the same reason:

* **provenance-true** — a distractor has a real author (borrowed from the
  document it drafts, copies, or accompanies), a real ``created_at`` (derived
  from its own cited facts by the same ``written_at`` rule as everything else),
  and real lineage (``revises``/``derived_from`` pointing at a document that
  really exists);
* **grading-safe** — because the fact was already reachable through the real
  document *before* the distractor existed, and the distractor never removes
  it from there, a distractor can never become the only passage carrying an
  evaluation case's answer. ``tests/test_distractors.py`` states this as a
  structural property of the generator, not a hope about its output.

Three families, tried in priority order per the task's own ordering: a
superseded draft is the most instructive kind of noise (recency confusion), a
derived personal copy is the next most instructive (near-duplicate confusion),
and a routine notice is pure volume. When the eligible pool for a family runs
dry, the remaining budget rolls to the next family rather than erroring — a
small world simply gets less noise than it asked for.

**The second half of this module is decay rather than volume** (``apply_messiness``,
graded by ``worldloom.messiness``). A real archive is not only full of documents
that answer nothing; it is also full of documents that answer *wrongly* — a page
nobody updated after the figure moved, an email quoting a workbook that has since
been restated, a runbook whose author left. Those live here rather than in a
module of their own because every sentence of the contract above applies to them
unchanged: no new fact, no new entity, no new event; every cited fact is one a
real document already cites, so grading safety is preserved for exactly the same
structural reason; and the same eligibility and dating helpers do the work.

What is different, and is the whole reason the family is safe to build, is that
each one is **recorded**. A distractor needs no explanation because it asserts
nothing new. An imperfection asserts something the ledger contradicts, so it is
labelled as an ``IntentionalError`` naming the canonical fact, and
``validate.intentional`` refuses a label the corpus cannot substantiate. The
corpus's promise was never that a synthetic enterprise is tidier than a real one
— it was that no document contradicts the ledger *without the ledger saying so*.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from .. import documents
from ..ids import Minter, id_prefix, is_id
from ..models import (
    ArtifactIntent,
    Authority,
    CanonicalFact,
    ErrorType,
    IntentionalError,
    Lifecycle,
)
from ..rng import Rng
from ..world import World

if TYPE_CHECKING:  # pragma: no cover
    from ..messiness import Messiness

#: Artifact types a "draft" or "personal copy" reading does not fit.
#:
#: ``finance_workbook`` and ``capital_return`` are resolved tables with no
#: narrative register to draft in; ``close_calendar`` already carries its own
#: cross-period ``supersedes`` chain and gaining a second relationship would
#: conflate the two; ``meeting_minutes`` and ``email_thread`` are projections
#: of a real meeting or a real event chain — there is nothing to redraft,
#: because neither document is an argument somebody wrote, it is a transcript
#: of something that happened once; ``jira_issues`` and ``servicenow_incident``
#: are live system-of-record tickets, not memos with a review lifecycle;
#: ``personnel_notice`` carries a single fact set with no meaningful subset.
_NOT_DRAFTABLE = frozenset({
    "finance_workbook", "capital_return", "close_calendar",
    "meeting_minutes", "email_thread", "jira_issues", "servicenow_incident",
    "personnel_notice",
})

#: Which register a document's own reader would copy it into. The default sink
#: is ``working_note`` — an unofficial personal digest — because it exists in
#: every vertical today (core-registered) and its lag (18h) is long enough to
#: sit after almost anything else in the table; the one type that reads oddly
#: copied into itself falls one register further, to ``confluence_page``.
#: A type absent from this table (a vertical's own bespoke artifact) falls
#: through to ``_DEFAULT_COPY_CANDIDATES`` — the mapping is a set of good
#: guesses, not a closed vocabulary, because ``_derived_copy`` verifies the
#: dating constraint itself rather than trusting the guess.
_COPY_CANDIDATES: dict[str, tuple[str, ...]] = {
    "working_note": ("confluence_page", "knowledge_article"),
}
_DEFAULT_COPY_CANDIDATES: tuple[str, ...] = ("working_note", "knowledge_article", "confluence_page")

#: Cap on how many personal copies is not enforced by number here — the
#: dating check in ``_derived_copy`` is what actually limits how often the
#: guess succeeds, and that is the honest limiter: a working note copied into
#: another working note usually fails it (no register left to fall into) and
#: is silently skipped rather than forced.


def _facts_by_id(world: World) -> dict[str, CanonicalFact]:
    return {fact.id: fact for fact in world._facts}


def _eligible_finals(world: World) -> list[ArtifactIntent]:
    """Real, already-planned documents a distractor may attach to.

    Three filters, each guarding a different invariant: the type must have a
    narrative register to draft or copy into; the intent must not already
    carry a relationship of its own (attaching a second one would conflate two
    different provenance claims on one document, which is exactly what
    ``validate.supersession`` exists to catch); and it must cite at least two
    facts, because a "subset" of one fact is not a subset, it is the same
    document.
    """
    return [
        intent
        for intent in world._artifact_intents
        if intent.artifact_type not in _NOT_DRAFTABLE
        and intent.revises is None
        and intent.supersedes is None
        and intent.restates is None
        and len(intent.required_fact_ids) >= 2
    ]


def _superseded_draft(
    final: ArtifactIntent,
    facts: dict[str, CanonicalFact],
    minter: Minter,
    rng: Rng,
) -> tuple[ArtifactIntent, ArtifactIntent] | None:
    """An earlier draft of *final*, and *final* updated to revise it.

    The subset is every fact strictly older than the newest one *final* cites,
    trimmed further by the seed — never the newest fact itself, because
    ``documents.written_at`` is "newest cited fact plus a type lag", and a
    draft that kept the newest fact would date to the same instant as the
    final it is supposed to precede. Dropping strictly-older facts is what
    lets the draft's own ``written_at`` fall out already earlier, with no
    date chosen by hand and nothing for ``temporal.cites_future_fact`` to
    catch later.

    Returns ``None`` when *final*'s facts cannot support the ordering — every
    cited fact shares the single newest timestamp, which happens on a tiny
    world and simply means this candidate yields no draft.
    """
    cited = [(fact_id, facts[fact_id].valid_from) for fact_id in final.required_fact_ids if fact_id in facts]
    if len(cited) < 2:
        return None
    newest = max(when for _, when in cited)
    earlier = [fact_id for fact_id, when in cited if when < newest]
    if not earlier:
        return None

    keep = rng.integer(1, len(earlier))
    subset = set(rng.sample(earlier, keep))
    # Preserve `final`'s own ordering rather than the sample's, so the draft's
    # table reads the same way round the final's does.
    ordered_subset = [fact_id for fact_id in final.required_fact_ids if fact_id in subset]

    draft = ArtifactIntent(
        id=minter.next("ART"),
        artifact_type=final.artifact_type,
        domain=final.domain,
        audience=final.audience,
        author_id=final.author_id,
        required_fact_ids=ordered_subset,
        # A draft has fewer facts, not a different document grammar. Keeping
        # the final's size class is load-bearing for long forms such as an RCA:
        # its five required components do not fit the small-class cap of four,
        # however early the draft is. The compiler must never drop a required
        # section merely because this generator relabelled the same type.
        size_profile=final.size_profile,
        rationale=(
            f"An earlier draft of {final.id}, circulated before the period's "
            "closing figures were final. Same author, same document type, a "
            "strict subset of the facts the final version goes on to cite — "
            "the stale-copy trap a recency question is supposed to catch."
        ),
    )
    # `revises` lives on the newer document (see `ArtifactIntent.revises`), so
    # the edge that marks the draft superseded has to be recorded on `final`,
    # not on the draft — this is the one relationship this generator writes
    # onto a document it did not itself mint. `World.extend` merges
    # `artifact_intents` by id for exactly this call: the id is unchanged, so
    # the merge replaces `final` in place rather than appending a duplicate.
    revised_final = final.model_copy(update={"revises": draft.id})
    return draft, revised_final


def _derived_copy(
    final: ArtifactIntent,
    facts: dict[str, CanonicalFact],
    minter: Minter,
    rng: Rng,
) -> ArtifactIntent | None:
    """A partial, different-register copy of *final*, made after it existed.

    Unlike a draft, a derived copy must not predate what it copies —
    ``validate.supersession``'s ``derives_from_later_artifact`` requires the
    parent to have been written first. The subset here always keeps *final*'s
    own newest fact (so the copy's `written_at` differs from the final's by
    the two types' lag alone, not by which facts happened to be sampled) and
    tries each candidate register in order until one lands at or after
    *final*'s own timestamp; a type with a shorter lag than *final*'s own is
    silently skipped rather than forced into an impossible date. The rest of
    the subset is a strict, seed-chosen fraction of what remains — a partial
    extract, never the whole document under a different name.
    """
    cited = [fact_id for fact_id in final.required_fact_ids if fact_id in facts]
    if len(cited) < 2:
        return None
    newest = max(cited, key=lambda fact_id: facts[fact_id].valid_from)
    rest = [fact_id for fact_id in cited if fact_id != newest]
    # Capped at roughly a third of what remains, so a memo with thirty facts
    # yields a handful kept for reference rather than twenty-nine — a personal
    # extract that quoted nearly the whole source would just be the source.
    cap = max(1, (len(rest) - 1) // 3) if len(rest) > 1 else 0
    extra_count = rng.integer(0, cap)
    extra = set(rng.sample(rest, extra_count)) if extra_count else set()
    kept = {newest, *extra}

    final_at = documents.written_at(final, facts)
    for copy_type in _COPY_CANDIDATES.get(final.artifact_type, _DEFAULT_COPY_CANDIDATES):
        if copy_type == final.artifact_type:
            continue
        probe = ArtifactIntent(
            id="ART-0000",
            artifact_type=copy_type,
            domain=final.domain,
            audience=final.audience,
            author_id=final.author_id,
            required_fact_ids=sorted(kept),
            size_profile="small",
        )
        if documents.written_at(probe, facts) < final_at:
            continue
        return ArtifactIntent(
            id=minter.next("ART"),
            artifact_type=copy_type,
            domain=final.domain,
            audience=final.audience,
            author_id=final.author_id,
            required_fact_ids=[fact_id for fact_id in final.required_fact_ids if fact_id in kept],
            size_profile="small",
            rationale=(
                f"A working extract of {final.id}, kept by the same author in a "
                "different register after the fact — a partial personal copy, "
                "not a second edition. The near-duplicate problem: retrieval "
                "has two documents to choose between and only one is the record."
            ),
            derived_from=[final.id],
        )
    return None


#: Audiences a routine internal notice would not plausibly be addressed to —
#: an external regulator or the top committee is who a *filing* or a *board
#: paper* goes to, not a "category traded to plan" note. Skipped when
#: choosing a voice to borrow, purely for realism: nothing downstream checks
#: this, so getting it wrong would not fail a gate, only read oddly.
_EXTERNAL_AUDIENCES = frozenset({"prudential_regulator", "board_risk_committee", "executive_committee"})


def _finance_voice(world: World) -> tuple[str, str, str]:
    """``(author_id, audience, domain)`` borrowed from an existing document.

    A routine notice needs a plausible author, but this module has no role
    table of its own — retail's keys ("reporting_manager") and banking's
    ("reg_reporting_manager") name the same *function* differently, and a
    generator meant to run against either vertical cannot hardcode one. The
    corpus's own planner already solved "who writes a finance-domain document,
    for whom" once per vertical; reusing that triple verbatim is also what
    keeps ``validate.access`` trivially satisfied, since it is a triple that
    already passed the access-policy check for the document it came from.
    """
    finance = [intent for intent in world.artifact_intents if intent.domain == "finance"]
    internal = [intent for intent in finance if intent.audience not in _EXTERNAL_AUDIENCES]
    chosen = (internal or finance or list(world.artifact_intents))[0]
    return chosen.author_id, chosen.audience, chosen.domain


#: Subjects whose *name* a routine notice may safely mention in prose. Every
#: other subject in this corpus is either fine (a company or business unit is
#: always named in letters) or actively unsafe: a site's name is a real-world
#: retail convention — "Supermarket VIC 002" — and citing it in prose sails a
#: bare digit straight past ``narrative.compiler``'s ``bare_number`` check,
#: the same rule that keeps a memo's dollar figures behind ``{{fact:...}}``
#: references. Tables sidestep this because a cell's text and its number are
#: separate fields; prose has no such separation, which is exactly why the
#: rule exists.
_SAFE_TO_NAME = frozenset({"CO", "BU", "CAT"})


#: Measures a routine notice may quote. Deliberately not every
#: ``.actual``/``.budget`` pair the ledger has: ``financial.gross_margin_pct``
#: is a ratio, and a ratio narrates as a bare, quotable sentence — "gross
#: margin came in at 23%" — that is lexically almost identical to a headline
#: question asked about the same measure at group level ("what was the group
#: gross margin"), whatever level the notice's own subject is. Measured
#: directly: an early build of this generator picked category-level margin
#: facts and a `direct_lookup` case about the *group's* margin lost its
#: top-five slot to four near-identical "gross margin came in at" notices —
#: that is a family the task requires stay at ceiling, and the fix is not to
#: quote the colliding phrase at all rather than to tune the retriever around
#: it. Plain revenue and profit figures do not have this problem: a category's
#: dollar amount and the group's are different numbers in the same sentence
#: shape, so they do not compete for the same top-k slot the way two "X%"
#: sentences about the same ratio do.
_BORING_KINDS = ("financial.revenue.actual", "financial.gross_profit.actual")


def _boring_facts(world: World) -> list[str]:
    """Facts an "on-plan, nothing to report" notice would cite.

    Preferred: a measure whose ``.actual`` sits within 3% of its ``.budget`` —
    a category or unit that traded to plan, which is the least interesting
    thing a finance function can say about a period and exactly what a
    routine notice exists to report. Falls back to whatever a finance-domain
    document already cites when no such pair exists (a small world, or a
    vertical whose facts are not expressed as actual/budget pairs at all,
    such as banking's regulatory ratios) — still real, still already
    reachable, just not provably "on plan".
    """
    current: dict[tuple[str, str, str | None], CanonicalFact] = {}
    for fact in world._facts:
        if fact.is_superseded:
            continue
        current[(fact.kind, fact.subject, fact.period)] = fact

    on_plan: list[str] = []
    for (kind, subject, period), fact in sorted(
        current.items(), key=lambda item: (item[0][0], item[0][1], item[0][2] or "")
    ):
        if kind not in _BORING_KINDS or fact.value is None:
            continue
        if not is_id(subject) or id_prefix(subject) not in _SAFE_TO_NAME:
            continue
        budget = current.get((kind[: -len(".actual")] + ".budget", subject, period))
        if budget is None or budget.value is None or not budget.value.amount:
            continue
        relative = abs(fact.value.amount - budget.value.amount) / abs(budget.value.amount)
        if relative <= 0.03:
            on_plan.append(fact.id)
    if on_plan:
        return on_plan

    return sorted({
        fact_id
        for intent in world.artifact_intents
        if intent.domain == "finance"
        for fact_id in intent.required_fact_ids
    })


def _routine_notices(
    world: World, remaining: int, minter: Minter, rng: Rng,
) -> list[ArtifactIntent]:
    """Pure volume: unremarkable notices that answer nothing interesting.

    Cycles deterministically through the boring-fact pool rather than
    resampling it per notice — a real reporting cadence repeats the same
    figures across several routine memos, so citing the same fact twice is
    the realistic outcome, not a bug to dedupe away.
    """
    if remaining <= 0:
        return []
    pool = _boring_facts(world)
    if not pool:
        return []

    author_id, audience, domain = _finance_voice(world)
    notices: list[ArtifactIntent] = []
    cursor = 0
    for _ in range(remaining):
        take = 1 if len(pool) < 2 else rng.integer(1, min(2, len(pool)))
        subset = [pool[(cursor + offset) % len(pool)] for offset in range(take)]
        cursor += take
        notices.append(
            ArtifactIntent(
                id=minter.next("ART"),
                artifact_type="routine_notice",
                domain=domain,
                audience=audience,
                author_id=author_id,
                required_fact_ids=subset,
                size_profile="small",
                rationale=(
                    "A routine periodic notice, citing figures that are already "
                    "on the record and already carried by the document that "
                    "established them. Volume, not evidence — the corpus's "
                    "haystack rather than one more needle."
                ),
            )
        )
    return notices


def apply(world: World, *, count: int) -> World:
    """Add up to *count* noise artifacts, and record the step on the recipe.

    A no-op below one, and deliberately so: the default build must stay
    byte-identical to a world that never heard of this module, and the
    cheapest way to guarantee that is for the zero case to touch nothing —
    not the artifact intents, not the recipe — rather than to special-case it
    downstream.

    Deterministic in the same sense as every other generator: one ``Rng``
    stream derived from the world's own seed, drawn in a fixed order (drafts,
    then copies, then notices; candidates visited in a seed-shuffled but
    otherwise fixed order within each). Two builds of the same seed with the
    same count produce the same distractors, byte for byte.
    """
    if count <= 0:
        return world
    if world._minter is None:
        raise ValueError("distractors need a generator-backed world; build one from a seed")

    from ..recipe import with_step

    facts = _facts_by_id(world)
    minter = world._minter
    rng = Rng(world.seed).derive("distractors")

    order = rng.shuffled(sorted(_eligible_finals(world), key=lambda intent: intent.id))

    remaining = count
    used: set[str] = set()
    new_intents: list[ArtifactIntent] = []
    revised_finals: dict[str, ArtifactIntent] = {}

    # (a) superseded drafts — priority one, the stale-copy trap.
    for final in order:
        if remaining <= 0:
            break
        made = _superseded_draft(final, facts, minter, rng)
        if made is None:
            continue
        draft, revised_final = made
        new_intents.append(draft)
        revised_finals[final.id] = revised_final
        used.add(final.id)
        remaining -= 1

    # (b) derived personal copies — priority two, the near-duplicate problem.
    #
    # Two passes, and the second one is the point. Skipping a final that
    # already carries a draft spreads the noise across documents, which is a
    # *preference*; `_derived_copy`'s dating rule — the copy's register must
    # have a longer lag than its parent's, or the extract would predate what
    # it extracts — is a *constraint*, and it is far tighter than it looks. In
    # the stock retail close exactly one of nine eligible finals satisfies it:
    # the CFO memo, whose only longer-lagged candidate is `working_note`. So
    # when (a) happened to draft that one memo, the corpus contained no derived
    # copy at any count, and the whole near-duplicate category vanished with
    # nothing failing but one assertion. The preference yields rather than
    # costing the corpus a kind of distractor outright.
    copied: set[str] = set()
    for spread in (True, False):
        for final in order:
            if remaining <= 0:
                break
            if final.id in copied or (spread and final.id in used):
                continue
            copy = _derived_copy(final, facts, minter, rng)
            if copy is None:
                continue
            new_intents.append(copy)
            copied.add(final.id)
            used.add(final.id)
            remaining -= 1
        if copied:
            break

    # (c) routine notices — priority three, pure volume.
    new_intents.extend(_routine_notices(world, remaining, minter, rng))

    return world.extend(
        artifact_intents=(*revised_finals.values(), *new_intents),
        recipe=with_step(world._recipe, "Distractors", count=count),
    )


# ---------------------------------------------------------------------------
# Decay — recorded imperfection, graded by `worldloom.messiness`
# ---------------------------------------------------------------------------

#: Registers a stale document may be re-circulated in, longest lag first.
#: A stale document has to date *after* the correction it missed, and the only
#: dial available is the type's own lag (``documents.written_at`` is "newest
#: cited fact plus a type lag" and nothing here may choose a date by hand — a
#: chosen date is exactly the copy-of-a-fact this project forbids everywhere
#: else). Trying the long lags first is therefore trying the constructions most
#: likely to clear the correction at all; a world whose corrections resolve
#: faster than eighteen hours falls through to the shorter ones.
_STALE_REGISTERS: tuple[str, ...] = ("working_note", "knowledge_article", "confluence_page")

#: The same table read the other way, for a document that must date *before* the
#: correction — it was right when written. Shortest lag first, for the mirrored
#: reason: the tighter the window between a figure being recorded and being
#: corrected, the shorter the lag that still fits inside it.
_QUOTING_REGISTERS: tuple[str, ...] = tuple(reversed(_STALE_REGISTERS))


def _corrections(world: World) -> list[tuple[CanonicalFact, CanonicalFact]]:
    """``(superseded, successor)`` pairs the ledger already records.

    The substrate for both staleness and disagreement, and deliberately *found*
    rather than manufactured: this module mints no fact, so the only figures it
    can be wrong about are ones the world corrected on its own. That is what
    makes every imperfection here explicable from the corpus — the explanation
    was already there before the imperfection was.

    Both halves are required. A fact with ``valid_to`` set but no successor is a
    figure that stopped applying rather than one that was corrected, and a
    document carrying it is out of scope rather than out of date.
    """
    by_id = _facts_by_id(world)
    pairs: list[tuple[CanonicalFact, CanonicalFact]] = []
    for successor in world._facts:
        if not successor.supersedes:
            continue
        old = by_id.get(successor.supersedes)
        if old is None or old.valid_to is None:
            continue
        pairs.append((old, successor))
    return sorted(pairs, key=lambda pair: pair[0].id)


def _citations(world: World) -> dict[str, list[ArtifactIntent]]:
    """Fact id → the planned documents that cite it, in id order.

    Id order rather than date order because it is the one total order that does
    not move when a lag table changes, and every choice made from this table has
    to be reproducible from the seed alone.
    """
    index: dict[str, list[ArtifactIntent]] = {}
    for intent in sorted(world._artifact_intents, key=lambda i: i.id):
        for fact_id in intent.required_fact_ids:
            index.setdefault(fact_id, []).append(intent)
    return index


def _reading(fact: CanonicalFact) -> str:
    """A fact's value in the form ``validate.intentional`` compares against.

    A measured fact is compared numerically by ``_quantity_matches``, so the
    string has to parse back to exactly the same float — ``repr`` rather than a
    formatted figure, because ``f"{x:g}"`` rounds to six significant digits and
    a seven-digit revenue would then be reported as a canonical mismatch. A
    textual fact is compared by containment, so its own text is what to state.
    An early draft of insurance's labelled imperfection tripped this exact check
    by writing a descriptive sentence instead of the value.
    """
    if fact.value is not None:
        amount = float(fact.value.amount)
        return str(int(amount)) if amount.is_integer() else repr(amount)
    return (fact.text_value or "").strip()


def _employed_at(world: World, author_id: str, when: datetime) -> bool:
    """Whether *author_id* was on the roster at *when*.

    Both minting builders borrow their author from the document they attach to,
    and both then move the *date* — forward past a correction, or back before
    one. A borrowed voice is therefore not automatically a valid one: a stale
    page dated a week after its source was written can land after its author
    left, and ``temporal.author_already_departed`` fails it. That check runs
    against the rendered manifest rather than the plan, so an in-memory
    ``world.validate()`` passes and `worldloom render` is where it surfaces —
    which is exactly how this was found, and why the constraint is enforced at
    the point the date is chosen rather than hoped for afterwards.

    Boundaries match ``temporal``'s own, strictly: an artifact dated at the
    instant someone left is refused there, so it is refused here.
    """
    person = world.people.get(author_id)
    if person is None:
        return False
    if person.joined is not None and person.joined > when:
        return False
    return person.left is None or person.left > when


def _probe(source: ArtifactIntent, register: str, cited: list[str]) -> ArtifactIntent:
    """A throwaway intent, only to ask ``documents.written_at`` what it would date to."""
    return ArtifactIntent(
        id="ART-0000",
        artifact_type=register,
        domain=source.domain,
        audience=source.audience,
        author_id=source.author_id,
        required_fact_ids=cited,
        size_profile="small",
    )


def _subset_of(
    source: ArtifactIntent, old: CanonicalFact, new: CanonicalFact,
    facts: dict[str, CanonicalFact], rng: Rng,
) -> list[str]:
    """*old* plus a seed-chosen handful of what *source* cites alongside it.

    Two filters, and each is load-bearing.

    *No newer than old*, which pins the document's date to ``old.valid_from +
    lag`` and leaves the register — the only thing actually being chosen — in
    sole control of where it lands. It also makes it impossible to cite the
    correction by accident: *new* is newer than *old* by construction, so the
    filter excludes it with no special case, and a document carrying both a
    figure and its replacement would be a history rather than an imperfection.

    *No other superseded fact*, so the document is out of date about exactly one
    thing. Without this a page could carry two corrections and the label would
    name one of them, leaving a reader unable to tell which claim the corpus was
    making — and it is not hypothetical: ``validate.imperfection`` caught the
    weaker version of this rule on the fourth stale page of a three-period retail
    world, where a second figure recorded and corrected in the same hour passed
    the date filter alongside its own replacement.
    """
    pool = [
        fact_id
        for fact_id in source.required_fact_ids
        if fact_id != old.id
        and fact_id in facts
        and facts[fact_id].valid_from <= old.valid_from
        and not facts[fact_id].is_superseded
    ]
    keep = rng.integer(0, min(2, len(pool))) if pool else 0
    extra = set(rng.sample(pool, keep)) if keep else set()
    return [fact_id for fact_id in source.required_fact_ids if fact_id == old.id or fact_id in extra]


def _anchor(
    old: CanonicalFact, new: CanonicalFact, cited: list[str], source: ArtifactIntent,
    world: World, facts: dict[str, CanonicalFact], citations: dict[str, list[ArtifactIntent]],
    rng: Rng,
) -> str | None:
    """A later fact that dates a stale document past the correction it missed.

    Lag alone does not get there. ``documents.written_at`` is the newest cited
    fact plus a type lag, so a document citing only facts at or before *old*
    can be at most eighteen hours after it — and an organisation that confirms a
    cause the same afternoon corrects itself faster than that. The honest way to
    move the date is to cite something the document really would have carried:
    one *later* figure, which is what makes it a page that was touched after the
    correction and still left the old number in place. That is the realistic
    shape anyway — nobody rewrites a page from scratch, they edit the top of it.

    Three constraints, each guarding something:

    * the anchor must already be cited by a real document, so this pass never
      becomes the only route to a fact and the grading-safety property the
      module's docstring claims stays true for the decay family too;
    * it must not be *new* itself, nor the successor of anything already cited,
      or the document would carry both a figure and its correction and stop
      being stale at all (``validate.imperfection`` fails exactly that);
    * it must not itself be superseded, because a page anchored on a second
      out-of-date figure muddles which correction the label is about.

    Preference is for facts the source document already cites, then anything in
    the same domain — a stale finance page anchored on an unrelated technology
    figure would be strange in a way nothing downstream would catch.
    """
    carried = {facts[fact_id].id for fact_id in cited if fact_id in facts}
    forbidden = {new.id} | {
        fact.id for fact in world._facts if fact.supersedes in carried
    }

    def usable(fact_id: str) -> bool:
        fact = facts.get(fact_id)
        return (
            fact is not None
            and fact_id not in forbidden
            and fact_id not in carried
            and not fact.is_superseded
            and fact.valid_from > new.valid_from
            and bool(citations.get(fact_id))
        )

    near = sorted(fact_id for fact_id in source.required_fact_ids if usable(fact_id))
    if near:
        return near[rng.integer(0, len(near) - 1)]
    wider = sorted(
        fact_id for fact_id, intents in citations.items()
        if usable(fact_id) and any(intent.domain == source.domain for intent in intents)
    )
    if not wider:
        return None
    return wider[rng.integer(0, len(wider) - 1)]


def _stale_republication(
    old: CanonicalFact, new: CanonicalFact, sources: list[ArtifactIntent],
    world: World, facts: dict[str, CanonicalFact],
    citations: dict[str, list[ArtifactIntent]], minter: Minter, rng: Rng,
) -> tuple[ArtifactIntent, IntentionalError] | None:
    """A page written after the figure moved that still carries the old one.

    The one thing that makes this staleness rather than history is the date, and
    the date is derived: the document has to land *after* ``new.valid_from`` — the
    instant the corrected figure went on the record — while citing only facts at
    or before ``old.valid_from``. Nothing is stamped by hand, so
    ``temporal.cites_future_fact`` has nothing to catch and the reader can
    recompute the whole argument from the two timestamps.

    Returns ``None`` when no source and register combination can carry it — a
    corpus whose every later figure is itself superseded, one with no later
    figure at all, or one where every candidate voice had left by the date the
    document would have to bear. Each of those simply has no stale page to write,
    and forcing one would mean choosing a date or inventing an author.
    """
    for source in sources:
        cited = _subset_of(source, old, new, facts, rng)
        anchor = _anchor(old, new, cited, source, world, facts, citations, rng)
        if anchor is None:
            continue
        cited = [*cited, anchor]

        for register in _STALE_REGISTERS:
            if register == source.artifact_type:
                continue
            at = documents.written_at(_probe(source, register, cited), facts)
            if at <= new.valid_from or not _employed_at(world, source.author_id, at):
                continue
            stale = ArtifactIntent(
                id=minter.next("ART"),
                artifact_type=register,
                domain=source.domain,
                audience=source.audience,
                author_id=source.author_id,
                required_fact_ids=cited,
                size_profile="small",
                rationale=(
                    f"Still in circulation and out of date: written after {new.id} "
                    f"corrected {old.id}, and carrying the superseded figure anyway. "
                    "Nothing revises it and nothing supersedes it, which is what makes "
                    "it a live document rather than an archived draft — the reader has "
                    "to establish its staleness from its own date, not from a label on "
                    "its face."
                ),
            )
            return stale, IntentionalError(
                id=minter.next("ERR"),
                artifact_id=stale.id,
                error_type=ErrorType.STALE_STATUS,
                observed_value=(
                    f"{old.kind} for {old.subject} is given as {_reading(old)}, which "
                    f"stopped being the position at {old.valid_to.isoformat()}"
                ),
                canonical_value=_reading(new),
                canonical_fact_id=new.id,
                note=(
                    "Deliberate staleness. Establishable without this label: the "
                    f"document cites {old.id}, which carries a valid_to; {new.id} "
                    "records what replaced it; and the document's own created_at "
                    "falls after that. The label says it was meant, not that it "
                    "happened."
                ),
            )
    return None


def _quoting_secondary(
    old: CanonicalFact, new: CanonicalFact, sources: list[ArtifactIntent],
    world: World, facts: dict[str, CanonicalFact], minter: Minter, rng: Rng,
) -> tuple[ArtifactIntent, IntentionalError] | None:
    """A secondary document quoting a figure that was right when it quoted it.

    The mirror of ``_stale_republication`` and a different defect, which is why
    both exist: nobody was careless here. The document dates *before* the
    correction, so its author could not have known, and it is wrong now only
    because a third document — the one carrying ``new`` — moved on without it.
    That is the "right in the workbook, wrong in the email quoting it" case, and
    the corpus states the whole of it structurally:

    * it cites ``old``, which the ledger marks superseded;
    * it ``derived_from`` the document it quoted, which is what makes it
      *secondary* rather than a second independent record;
    * some other document cites ``new``, so there is a live disagreement rather
      than an orphaned old figure;
    * its ``created_at`` precedes ``new.valid_from``, which is the exoneration.

    Refused, rather than approximated, when any of those cannot be built. In
    particular the parent has to have been written first or
    ``supersession.derives_from_later_artifact`` would fire — correctly, since a
    document cannot quote one that did not exist.
    """
    for source in sources:
        cited = _subset_of(source, old, new, facts, rng)
        for register in _QUOTING_REGISTERS:
            if register == source.artifact_type:
                continue
            at = documents.written_at(_probe(source, register, cited), facts)
            if at >= new.valid_from or not _employed_at(world, source.author_id, at):
                continue
            parent = next(
                (
                    candidate for candidate in sources
                    if documents.written_at(candidate, facts) <= at
                ),
                None,
            )
            if parent is None:
                continue
            secondary = ArtifactIntent(
                id=minter.next("ART"),
                artifact_type=register,
                domain=source.domain,
                audience=source.audience,
                author_id=source.author_id,
                required_fact_ids=cited,
                size_profile="small",
                derived_from=[parent.id],
                rationale=(
                    f"A secondary document quoting {parent.id}. The figure it "
                    f"carries was the position when it was written and stopped "
                    f"being so at {new.valid_from.isoformat()}; nobody went back "
                    "to it. Two documents in circulation that disagree, and the "
                    "ledger says which is current and why the other is not "
                    "anybody's fault."
                ),
            )
            return secondary, IntentionalError(
                id=minter.next("ERR"),
                artifact_id=secondary.id,
                error_type=ErrorType.STALE_STATUS,
                observed_value=(
                    f"quotes {parent.id} for {old.kind} on {old.subject} as "
                    f"{_reading(old)}, correct when written at {at.isoformat()}"
                ),
                canonical_value=_reading(new),
                canonical_fact_id=new.id,
                note=(
                    "Deliberate disagreement, not deliberate carelessness: this "
                    f"document predates {new.id}. Establishable from the corpus "
                    f"alone — it derives from {parent.id}, cites the superseded "
                    f"{old.id}, and another document carries {new.id}."
                ),
            )
    return None


def _orphaned(
    world: World, facts: dict[str, CanonicalFact], minter: Minter,
) -> list[IntentionalError]:
    """Documents whose author has left, with the departure that orphaned them.

    Mints nothing. It does not have to: a world that has run a ``Departure``
    already contains documents nobody answers for, and the only thing missing
    was any record that the corpus knew. Manufacturing a departure to create one
    would be a canonical change — who works here is a scenario's decision, not a
    post-processing pass's — so this kind is honestly empty on a world where
    nobody has left, the same graceful degradation ``apply`` uses throughout.

    The departure fact is *found* by subject: a canonical fact about the author
    that dates from their leaving. That is what a reader follows to establish the
    orphaning, and it carries the succession, so the label is a pointer to the
    corpus's own answer rather than a second copy of it.
    """
    departures: dict[str, CanonicalFact] = {}
    for person in sorted(world._people, key=lambda p: p.id):
        if person.left is None:
            continue
        candidates = [
            fact for fact in world._facts
            if fact.subject == person.id and fact.valid_from >= person.left
        ]
        if candidates:
            departures[person.id] = min(candidates, key=lambda f: (f.valid_from, f.id))

    already = {
        error.artifact_id for error in world._intentional_errors
        if error.error_type is ErrorType.OUTDATED_OWNER
    }
    found: list[IntentionalError] = []
    for intent in sorted(world._artifact_intents, key=lambda i: i.id):
        departure = departures.get(intent.author_id)
        if departure is None or intent.id in already:
            continue
        # A document written after its author left is a different defect
        # entirely — `temporal.author_not_employed` catches it — and calling it
        # an orphan would launder a real incoherence as a deliberate one.
        if documents.written_at(intent, facts) >= departure.valid_from:
            continue
        author = world.people.get(intent.author_id)
        found.append(
            IntentionalError(
                id=minter.next("ERR"),
                artifact_id=intent.id,
                error_type=ErrorType.OUTDATED_OWNER,
                observed_value=(
                    f"authored by {author.name if author else intent.author_id}"
                    f" ({author.title if author else 'unknown role'}), who has since"
                    " left; the document names no successor and was never reissued"
                ),
                canonical_value=_reading(departure),
                canonical_fact_id=departure.id,
                note=(
                    "Deliberate orphaning, and nothing was invented to produce it: "
                    "the author's own record carries a leaving date, and "
                    f"{departure.id} says who took the work on. The document was "
                    "left where it was."
                ),
            )
        )
    return found


def apply_messiness(
    world: World, *, messiness: Messiness, recorded_as: str | Mapping[str, Any] | None = None,
) -> World:
    """Add the imperfections *messiness* asks for, and record the step.

    Called through ``worldloom.messiness.apply``/``Imperfections``, which owns
    the named profiles and the recipe verb; this is the half that knows what a
    document is. Split that way for the same reason ``parameters`` and the
    generators that read it are split: the registry is what an author edits, and
    the generator is what has to stay byte-identical when they do not.

    A no-op at zero, and deliberately so — the default build must stay
    byte-identical to a world that never heard of this pass, and the cheapest
    guarantee is that the zero case touches neither the intents, nor the errors,
    nor the recipe.

    **Budget, not quota.** Each kind takes what the world can support and stops.
    A world with two corrections cannot have five stale pages without inventing
    a figure to be stale about, and inventing one is the single thing this pass
    may never do.
    """
    if messiness.degree <= 0:
        return world
    if world._minter is None:
        raise ValueError("imperfections need a generator-backed world; build one from a seed")

    from ..recipe import with_step

    facts = _facts_by_id(world)
    minter = world._minter
    rng = Rng(world.seed).derive("messiness")

    new_intents: list[ArtifactIntent] = []
    errors: list[IntentionalError] = []

    corrections = _corrections(world)
    citations = _citations(world)

    # (a) staleness — a document that missed a correction it postdates.
    remaining = messiness["staleness"]
    spent: set[str] = set()
    for old, new in corrections:
        if remaining <= 0:
            break
        sources = citations.get(old.id) or []
        if not sources:
            continue
        made = _stale_republication(old, new, sources, world, facts, citations, minter, rng)
        if made is None:
            continue
        intent, error = made
        new_intents.append(intent)
        errors.append(error)
        spent.add(old.id)
        remaining -= 1

    # (b) disagreement — a document that predates one. Corrections already spent
    # on a stale page are skipped rather than reused: two documents built from
    # one correction would put the same figure in circulation twice under two
    # different explanations, and a reader could not tell which label described
    # which document without reading both.
    remaining = messiness["disagreement"]
    for old, new in corrections:
        if remaining <= 0:
            break
        if old.id in spent:
            continue
        sources = citations.get(old.id) or []
        # No live disagreement unless something actually carries the corrected
        # figure. Without this the "wrong" document would be the only account of
        # the measure in the corpus, which is a hole, not a contradiction.
        if not sources or not citations.get(new.id):
            continue
        made = _quoting_secondary(old, new, sources, world, facts, minter, rng)
        if made is None:
            continue
        intent, error = made
        new_intents.append(intent)
        errors.append(error)
        remaining -= 1

    # (c) orphaning — documents the roster already stranded, now recorded.
    errors.extend(_orphaned(world, facts, minter)[: messiness["orphaning"]])

    return world.extend(
        artifact_intents=tuple(new_intents),
        intentional_errors=tuple(errors),
        recipe=with_step(
            world._recipe, "Imperfections",
            profile=recorded_as if recorded_as is not None else messiness.as_dict(),
        ),
    )


# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

# `routine_notice` is registered unconditionally at import time, the same
# contract every domain module's own types follow (`documents.py`'s own
# docstring: registration must not depend on whether a particular flag was
# used, or a corpus carrying the type would compile differently in a fresh
# process than in the one that built it). It needs no per-vertical wiring —
# `outline()`'s generic compiler and `_DEFAULT_OUTLINE`'s fallback would work
# for it even unregistered — but standing and lag are given explicitly rather
# than left to fall through, because a routine notice's authority and cadence
# are a real modelling decision (a low-stakes, published, same-day note), not
# an accident of what the fallback table happens to default to.
documents.register_artifact_types(
    standing={"routine_notice": (Authority.WORKING_DOCUMENT, Lifecycle.PUBLISHED)},
    lags={"routine_notice": timedelta(hours=4)},
    outlines={
        "routine_notice": (
            documents.SectionPlan(
                "Status", ("",), "any",
                "A routine periodic notice. State the figures given plainly, in "
                "one or two sentences, and stop — the whole point of this "
                "document is that there is nothing to report.",
            ),
        ),
    },
)

__all__ = ["apply", "apply_messiness"]
