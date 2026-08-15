"""The narrative compiler.

One stage of a pipeline, not the centre of it:

    canonical facts → narrative request → supported claims → prose

For every section awaiting prose, the compiler builds a bounded request, consults
the generation ledger, and only calls a provider when the ledger misses. What comes
back is validated against the facts and either accepted or sent back with the
violation attached. Accepted output is recorded, with the number of rejected
attempts, so the record shows what it took.

**The ledger is what makes determinism survive the model.** A key is
``(seed, call site, ordinal, fact digest, model id, prompt version)``. Regenerating
a world whose ledger is present touches no provider at all: every key hits, the
recorded prose comes back byte for byte, and the run is offline and free. Changing
the model or bumping a prompt version changes every key, so it yields a *different*
world — explicitly, not silently.

**Concurrency must never leak into output.** ``narrate(concurrency=N)`` fans live
generation calls out to a thread pool, but every section's *fate* — replay, empty,
or live — and the traversal order the accepted ledger records them in are decided
by ``_plan`` before a single thread is spun up (see ``_Slot``). A ``GEN-####`` id
is minted in exactly one place, a single-threaded pass over that plan, strictly in
section order — never in whichever order a worker's future happens to resolve.
That is the whole determinism argument for concurrency: it changes *when* a call
happens, never what it produces or where it lands.

**``on_accepted`` rides the same plan.** It fires once per section a worker
actually generates (never for a replay), so a caller that wants to persist
accepted prose as it lands can, rather than only at the end. Its original
caller — a checkpoint sidecar for the deleted ``narrate auto`` command — is
gone, but the seam is generically useful and tested, so it stays. The entry
handed to the callback carries a scratch id, not the sequential one the
finished corpus will use for that section; only the single-threaded assembly
pass decides that, once, in order.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..ids import content_key, format_id, highest_numeric_suffix
from ..models import ArtifactIR, ArtifactSection, GenerationLedgerEntry
from . import claims as claim_checks
from . import prompts, providers
from .requests import GeneratedNarrative, NarrativeRequest

if TYPE_CHECKING:  # pragma: no cover
    from ..models import CanonicalFact
    from ..world import World

#: How many rejections to absorb before giving up on a section.
DEFAULT_RETRIES = 2


class NarrationError(Exception):
    """Raised when a section cannot be produced within the retry budget."""


@dataclass(frozen=True)
class Narration:
    """Everything one narration pass produced."""

    irs: tuple[ArtifactIR, ...]
    ledger: tuple[GenerationLedgerEntry, ...]
    provider_calls: int
    replayed: int
    rejected: int


def ledger_key(
    *,
    seed: int,
    call_site: str,
    ordinal: int,
    fact_digest: str,
    model_id: str,
    prompt_version: str,
) -> str:
    """The content address of one generative call.

    Every component is load-bearing. Drop the fact digest and a corrected figure
    replays stale prose; drop the prompt version and an edited prompt silently
    changes what a seed means; drop the ordinal and two sections of the same
    artifact collide.
    """
    return content_key(seed, call_site, ordinal, fact_digest, model_id, prompt_version)


def _forbidden_for(artifact_type: str) -> list[str]:
    """Claims a given artifact type must not make.

    Modest on purpose. The interesting constraints are the fact bounds; this exists
    so the mechanism is exercised and has somewhere to grow.
    """
    if artifact_type == "confluence_page":
        # A triage page is raised before anyone knows the cause.
        return ["root cause", "confirmed cause"]
    return []


def _comparators(
    allowed: list[str],
    facts: dict[str, CanonicalFact],
    cutoff,  # type: ignore[no-untyped-def]
) -> dict[str, str]:
    """Each measured fact paired with the same measure one period earlier."""
    by_measure: dict[tuple[str, str, str], str] = {}
    for fact in facts.values():
        if fact.period and fact.value is not None and not fact.is_superseded:
            by_measure.setdefault((fact.kind, fact.subject, fact.period), fact.id)

    out: dict[str, str] = {}
    for fact_id in allowed:
        fact = facts[fact_id]
        if not fact.period or fact.value is None:
            continue
        year, _, month = fact.period.partition("-")
        previous = (
            f"{int(year) - 1:04d}-12" if month == "01" else f"{year}-{int(month) - 1:02d}"
        )
        earlier = by_measure.get((fact.kind, fact.subject, previous))
        if earlier is None:
            continue
        # A comparator the author could not yet have seen is not a comparator.
        if cutoff is not None and facts[earlier].valid_from > cutoff:
            continue
        out[fact_id] = earlier
    return out


def _background(world: World, cited: list[CanonicalFact]) -> list[str]:
    """Lore reachable from the facts supplied.

    Only what the figures actually touch. Handing a writer the whole lore graph
    would invite them to explain a margin miss with a decision that has nothing to
    do with it, which is worse than no context at all.
    """
    wanted = {lore_id for fact in cited for lore_id in fact.lore_ids}
    return [c.assertion for c in world.lore if c.id in wanted]


def _hierarchy(world: World, cited: list[CanonicalFact], names: dict[str, str]) -> dict[str, str]:
    """Where each subject sits, so prose can say "the largest division"."""
    units = {unit.id: unit.name for unit in world.business_units}
    out: dict[str, str] = {}
    for fact in cited:
        subject = fact.subject
        if subject in out or subject not in names:
            continue
        if subject == world.company.id:
            out[names[subject]] = "the group"
        elif subject in units:
            out[names[subject]] = f"division of {world.company.name}"
        else:
            parent = getattr(world.categories.get(subject) or world.sites.get(subject), "business_unit_id", None)
            if parent in units:
                kind = "category in" if world.categories.get(subject) else "site in"
                out[names[subject]] = f"{kind} {units[parent]}"
    return out


def _request_for(
    world: World,
    ir: ArtifactIR,
    section: ArtifactSection,
    facts: dict[str, CanonicalFact],
) -> NarrativeRequest:
    """Build the bounded request for one section."""
    intent = world.artifact_intents.by_id(ir.intent_id)
    author = world.people.by_id(intent.author_id)
    persona = world.personas.get(author.persona_id) if author.persona_id else None
    manifest = world.artifacts.get(ir.id)

    allowed = [f for f in section.fact_ids if f in facts]
    names = world.entity_names()
    # An author knows what had happened by the time they wrote. Using the
    # artifact's own timestamp as the cut-off is what stops a page written during
    # triage from citing a cause confirmed hours later — while still letting a
    # later RCA discuss the hypothesis that triage got wrong.
    cutoff = manifest.created_at if manifest else None

    required = [
        fact_id
        for fact_id in intent.required_fact_ids
        if fact_id in allowed
        and (cutoff is None or facts[fact_id].valid_from <= cutoff)
    ][:3]

    # The prior period's value of each measure, added to the allowed set so a
    # trend is written by citing two references rather than by restating a
    # movement the writer worked out in their head. Without this the harness
    # would be right to reject "the third consecutive month" — there would be
    # nothing supporting it.
    comparators = _comparators(allowed, facts, cutoff)
    allowed = allowed + [c for c in comparators.values() if c not in allowed]

    return NarrativeRequest(
        artifact_id=ir.id,
        artifact_type=intent.artifact_type,
        section=section.heading,
        subjects={
            fact_id: names[facts[fact_id].subject]
            for fact_id in allowed
            if facts[fact_id].subject in names
        },
        purpose=section.purpose,
        background=_background(world, [facts[f] for f in allowed]),
        author_traits=dict(author.traits),
        persona_label=persona.label if persona else "",
        hierarchy=_hierarchy(world, [facts[f] for f in allowed], names),
        comparators=comparators,
        persona_id=persona.id if persona else "",
        voice=persona.voice if persona else "plain",
        audience=intent.audience,
        author_title=author.title,
        temporal_cutoff=cutoff,
        allowed_fact_ids=allowed,
        required_fact_ids=required,
        forbidden_claims=_forbidden_for(intent.artifact_type),
        # World-level, not fact-scoped: a vocabulary note holds for every
        # section, and there are never more than a handful. Not part of the
        # fact digest, so adding one cannot orphan a recorded narration.
        terminology={
            constraint.target: constraint.effect
            for commitment in world.lore
            for constraint in commitment.constrains
            if constraint.kind.value == "terminology"
        },
        target_words={"small": 70, "medium": 130, "long": 200}.get(intent.size_profile, 120),
        fact_digest=providers.digest([facts[f] for f in allowed]),
    )


@dataclass
class _Slot:
    """One section's place in a narration pass.

    Resolved immediately (``kind`` is ``"keep"`` — already had prose or a table
    — or ``"empty"`` — awaiting prose but nothing allowed to say it with), or
    deferred (``"replay"``, a ledger hit with nothing to call; ``"live"``,
    a provider call still to make). ``_plan`` builds the whole list up front,
    in section-traversal order, before anything is dispatched — which is what
    lets ``narrate``'s live jobs run on a thread pool while every downstream
    decision (what a `GEN-####` id names, what order the ledger records) stays
    a property of this list's order rather than of thread scheduling.
    """

    section: ArtifactSection
    kind: str
    request: NarrativeRequest | None = None
    call_site: str = ""
    key: str = ""
    ordinal: int = 0
    existing: GenerationLedgerEntry | None = None
    future: Future | None = field(default=None, repr=False)
    result: tuple[GeneratedNarrative, int] | None = None


def _plan(
    world: World,
    facts: dict[str, CanonicalFact],
    ledger: tuple[GenerationLedgerEntry, ...],
    provider: providers.Provider,
    prompt: prompts.Prompt,
) -> tuple[list[list[_Slot]], list[_Slot]]:
    """Decide every section's fate before calling anything.

    Shared by ``narrate`` and ``preflight`` so the two can never disagree about
    what counts as a replay versus a live call — a caller reporting what a pass
    *would* do gets the same computation the run itself does, not a second
    estimate that could drift from it.
    """
    by_key = {entry.key: entry for entry in ledger}
    ir_slots: list[list[_Slot]] = []
    live_jobs: list[_Slot] = []

    for ir in world._artifact_irs:
        slots: list[_Slot] = []
        for ordinal, section in enumerate(ir.sections):
            if not section.awaiting_prose:
                slots.append(_Slot(section=section, kind="keep"))
                continue

            request = _request_for(world, ir, section, facts)
            if not request.allowed_fact_ids:
                # Nothing to say and nothing to say it with. Better an empty
                # section than prose invented to fill it.
                slots.append(_Slot(section=section, kind="empty"))
                continue

            call_site = f"{ir.id}/{section.heading}"
            key = ledger_key(
                seed=world.seed,
                call_site=call_site,
                ordinal=ordinal,
                fact_digest=request.fact_digest,
                model_id=provider.id,
                prompt_version=prompt.key,
            )

            existing = by_key.get(key)
            if existing is not None:
                slots.append(_Slot(section=section, kind="replay", key=key, existing=existing))
                continue

            slot = _Slot(
                section=section, kind="live", request=request,
                call_site=call_site, key=key, ordinal=ordinal,
            )
            slots.append(slot)
            live_jobs.append(slot)
        ir_slots.append(slots)

    return ir_slots, live_jobs


def _ledger_entry(
    *,
    id: str,
    slot: _Slot,
    world_seed: int,
    provider_id: str,
    prompt_key: str,
    narrative: GeneratedNarrative,
    attempts: int,
) -> GenerationLedgerEntry:
    """Build the ledger row for one live job. *id* is the only thing the
    single-threaded assembly pass decides; the copy handed to ``on_accepted``
    mid-run carries a provisional one — see ``narrate``."""
    assert slot.request is not None  # only "live" slots reach here
    return GenerationLedgerEntry(
        id=id,
        key=slot.key,
        call_site=slot.call_site,
        ordinal=slot.ordinal,
        world_seed=world_seed,
        input_facts_digest=slot.request.fact_digest,
        model_id=provider_id,
        prompt_version=prompt_key,
        output=narrative.model_dump(mode="json"),
        rejected_attempts=attempts,
    )


@dataclass(frozen=True)
class Preflight:
    """What a narration pass would do, computed without calling *provider* once.

    ``replay_keys`` is every ledger key `narrate` would serve from *ledger*
    without a call. A caller with its own cache of prior answers can intersect
    this with the keys that cache carries to attribute each hit; `preflight`
    itself doesn't know which source a hit came from, only that it was one.
    """

    total_sections: int
    replay_keys: frozenset[str]
    live_count: int
    live_prompt_chars: int


def preflight(
    world: World,
    provider: providers.Provider,
    *,
    ledger: tuple[GenerationLedgerEntry, ...] = (),
    prompt_name: str = prompts.SECTION_PROSE.name,
) -> Preflight:
    """Count what ``narrate`` would do, without spending a single call.

    Built on the exact same planning pass (`_plan`) `narrate` runs, so the
    number an operator approves before paying for a run is the number the run
    will actually produce.
    """
    if world.seed is None:
        raise NarrationError("narration needs a seeded world")
    if not world._artifact_irs:
        raise NarrationError("nothing to narrate — compile artifacts first")

    prompt = prompts.get(prompt_name)
    facts = {fact.id: fact for fact in world.facts}
    ir_slots, live_jobs = _plan(world, facts, ledger, provider, prompt)

    total = sum(len(slots) for slots in ir_slots)
    replay_keys = frozenset(
        slot.key for slots in ir_slots for slot in slots if slot.kind == "replay"
    )
    # The exact prompt each live call will send, not a guess at its size — the
    # same `Prompt.render()` `_generate` itself calls. `feedback=""` because a
    # preflight cannot know a retry will happen; any section that gets rejected
    # once sends more than this floor.
    live_chars = sum(len(prompt.render(slot.request, facts)) for slot in live_jobs)

    return Preflight(
        total_sections=total,
        replay_keys=replay_keys,
        live_count=len(live_jobs),
        live_prompt_chars=live_chars,
    )


def narrate(
    world: World,
    provider: providers.Provider,
    *,
    ledger: tuple[GenerationLedgerEntry, ...] = (),
    retries: int = DEFAULT_RETRIES,
    prompt_name: str = prompts.SECTION_PROSE.name,
    concurrency: int = 1,
    on_accepted: Callable[[GenerationLedgerEntry], None] | None = None,
) -> Narration:
    """Fill every section awaiting prose, replaying from *ledger* where possible.

    ``concurrency`` fans live generation calls out to a thread pool of that
    size; the default of 1 makes no thread pool at all, so it is today's
    behaviour, byte for byte. Raising it changes *when* calls happen and never
    what they produce: `_plan` decides every section's fate up front, and the
    loop below that turns accepted results into ledger entries is the only
    place a `GEN-####` id is minted, running single-threaded and strictly in
    section order regardless of which worker's future resolves first (see the
    module docstring).

    A provider's ``complete()`` must therefore be safe to call from more than
    one thread at once when ``concurrency > 1`` — every provider shipped here
    is, because each call is self-contained. (The one exception ever shipped,
    an adapter that ran ``asyncio.run()`` per call, was deleted with the
    API-caller path; a future provider with per-call event loops would trip
    the same constraint, which is why it stays written down.)

    ``on_accepted``, if given, is called once per section actually generated
    (never for a replay — nothing new happened), the moment its provider call
    is validated and accepted, from whichever thread produced it — so it must
    be its own thread-safe callable: a crash can land between any two workers
    finishing, so a caller persisting acceptances has to do it here, not after
    this function's own single-threaded reassembly gets around to it.
    """
    if world.seed is None:
        raise NarrationError("narration needs a seeded world")
    if not world._artifact_irs:
        raise NarrationError("nothing to narrate — compile artifacts first")
    if concurrency < 1:
        raise ValueError(f"concurrency must be at least 1, got {concurrency}")

    prompt = prompts.get(prompt_name)
    facts = {fact.id: fact for fact in world.facts}
    entity_names = claim_checks.known_entity_names(world)

    ir_slots, live_jobs = _plan(world, facts, ledger, provider, prompt)

    # Continue the GEN sequence rather than restarting it at 1 — mirrors
    # `compiler/handshake.py`'s plan `accept()`, and for the same reason: this
    # world's ledger can already carry GEN entries (an earlier narration pass,
    # an accepted plan batch, or any prior entries a caller folds into
    # `ledger` — the case that first made this load-bearing was a resumed run
    # replaying its own earlier acceptances). A fresh count starting at 1
    # would mint an id some already-recorded entry owns.
    next_gen = 1 + highest_numeric_suffix("GEN", (entry.id for entry in ledger))

    def _run(slot: _Slot) -> tuple[GeneratedNarrative, int]:
        assert slot.request is not None
        narrative, attempts = _generate(
            provider, slot.request, prompt, facts,
            entity_names=entity_names, retries=retries,
        )
        if on_accepted is not None:
            on_accepted(
                _ledger_entry(
                    # A scratch id, not the sequential one this section will
                    # carry in the finished ledger — that one is only decided
                    # below, once, in section order. See the docstring.
                    id=f"GEN-CKPT-{slot.key[:16].upper()}",
                    slot=slot, world_seed=world.seed, provider_id=provider.id,
                    prompt_key=prompt.key, narrative=narrative, attempts=attempts,
                )
            )
        return narrative, attempts

    if concurrency <= 1 or len(live_jobs) <= 1:
        # No pool at all — not merely one worker — so concurrency=1 touches no
        # threading machinery whatsoever and stays trivially "today's code".
        for slot in live_jobs:
            slot.result = _run(slot)
    else:
        pool = ThreadPoolExecutor(max_workers=concurrency)
        try:
            for slot in live_jobs:
                slot.future = pool.submit(_run, slot)
            for slot in live_jobs:
                assert slot.future is not None
                slot.result = slot.future.result()
        finally:
            # `cancel_futures` drops whatever had not yet started; anything
            # already running is left to finish (and fire `on_accepted`)
            # rather than abandoned, so a `NarrationError` from one exhausted
            # section can never race the acceptance callback of a section
            # that succeeded before it.
            pool.shutdown(wait=True, cancel_futures=True)

    recorded: list[GenerationLedgerEntry] = []
    filled: list[ArtifactIR] = []
    provider_calls = replayed = rejected = 0

    for ir, slots in zip(world._artifact_irs, ir_slots):
        sections: list[ArtifactSection] = []
        for slot in slots:
            if slot.kind in ("keep", "empty"):
                sections.append(slot.section)
                continue

            if slot.kind == "replay":
                assert slot.existing is not None
                narrative = GeneratedNarrative.model_validate(slot.existing.output)
                replayed += 1
                # A checkpoint callback cannot know this section's sequential
                # id until every prior section has assembled, so it persists a
                # content-addressed GEN-CKPT id. On replay we *do* have the
                # canonical section order: replace only that provisional id and
                # advance the same sequence an uninterrupted run uses. This is
                # what makes resume byte-identical, not merely prose-equivalent.
                if slot.existing.id.startswith("GEN-CKPT-"):
                    recorded.append(slot.existing.model_copy(
                        update={"id": format_id("GEN", next_gen)}
                    ))
                    next_gen += 1
                else:
                    recorded.append(slot.existing)
            else:
                assert slot.result is not None
                narrative, attempts = slot.result
                provider_calls += 1 + attempts
                rejected += attempts
                recorded.append(
                    _ledger_entry(
                        id=format_id("GEN", next_gen),
                        slot=slot, world_seed=world.seed, provider_id=provider.id,
                        prompt_key=prompt.key, narrative=narrative, attempts=attempts,
                    )
                )
                next_gen += 1

            sections.append(
                slot.section.model_copy(
                    update={
                        "body": narrative.text,
                        "fact_ids": sorted(
                            {f for claim in narrative.claims for f in claim.supporting_fact_ids}
                            | set(slot.section.fact_ids)
                        ),
                    }
                )
            )

        metadata = dict(ir.metadata)
        if any(not s.awaiting_prose and s.body for s in sections):
            metadata.pop("awaiting_prose", None)
            metadata["narrated_by"] = provider.id
            metadata["prompt_version"] = prompt.key
        filled.append(ir.model_copy(update={"sections": sections, "metadata": metadata}))

    return Narration(
        irs=tuple(filled),
        ledger=tuple(recorded),
        provider_calls=provider_calls,
        replayed=replayed,
        rejected=rejected,
    )


def _generate(
    provider: providers.Provider,
    request: NarrativeRequest,
    prompt: prompts.Prompt,
    facts: dict[str, CanonicalFact],
    *,
    entity_names: frozenset[str],
    retries: int,
) -> tuple[GeneratedNarrative, int]:
    """Call the provider until the result validates, or give up.

    A rejection is handed back verbatim rather than repaired locally. Repairing it
    here would hide from the model that it broke a rule, and hide from the ledger
    that a rejection happened.
    """
    feedback = ""
    attempts = 0

    while True:
        narrative = provider.complete(request, prompt, facts, feedback=feedback)
        verdict = claim_checks.validate(request, narrative, facts, entity_names=entity_names)
        if verdict.accepted:
            return narrative, attempts

        attempts += 1
        if attempts > retries:
            raise NarrationError(
                f"{request.artifact_id}/{request.section} still invalid after {attempts} attempt(s):\n"
                f"{verdict.feedback}"
            )
        feedback = verdict.feedback
