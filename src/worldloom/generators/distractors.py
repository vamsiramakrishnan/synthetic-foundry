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
"""

from __future__ import annotations

from datetime import timedelta

from .. import documents
from ..ids import Minter, id_prefix, is_id
from ..models import ArtifactIntent, Authority, CanonicalFact, Lifecycle
from ..rng import Rng
from ..world import World

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
        size_profile="small",
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
    for final in order:
        if remaining <= 0:
            break
        if final.id in used:
            continue
        copy = _derived_copy(final, facts, minter, rng)
        if copy is None:
            continue
        new_intents.append(copy)
        used.add(final.id)
        remaining -= 1

    # (c) routine notices — priority three, pure volume.
    new_intents.extend(_routine_notices(world, remaining, minter, rng))

    return world.extend(
        artifact_intents=(*revised_finals.values(), *new_intents),
        recipe=with_step(world._recipe, "Distractors", count=count),
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

__all__ = ["apply"]
