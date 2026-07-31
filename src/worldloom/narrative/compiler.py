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
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..ids import Minter, content_key
from ..models import ArtifactIR, ArtifactSection, GenerationLedgerEntry
from . import claims as claim_checks
from . import prompts, providers
from .requests import GeneratedClaim, GeneratedNarrative, NarrativeRequest

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
        target_words={"small": 70, "medium": 130, "long": 200}.get(intent.size_profile, 120),
        fact_digest=providers.digest([facts[f] for f in allowed]),
    )


def narrate(
    world: World,
    provider: providers.Provider,
    *,
    ledger: tuple[GenerationLedgerEntry, ...] = (),
    retries: int = DEFAULT_RETRIES,
    prompt_name: str = prompts.SECTION_PROSE.name,
) -> Narration:
    """Fill every section awaiting prose, replaying from *ledger* where possible."""
    if world.seed is None:
        raise NarrationError("narration needs a seeded world")
    if not world._artifact_irs:
        raise NarrationError("nothing to narrate — compile artifacts first")

    prompt = prompts.get(prompt_name)
    facts = {fact.id: fact for fact in world.facts}
    entity_names = frozenset(
        [world.company.name]
        + [unit.name for unit in world.business_units]
        + [person.name for person in world.people]
        + [system.name for system in world.systems]
    )

    by_key = {entry.key: entry for entry in ledger}
    minter = Minter()
    recorded: list[GenerationLedgerEntry] = []
    filled: list[ArtifactIR] = []
    provider_calls = replayed = rejected = 0

    for ir in world._artifact_irs:
        sections: list[ArtifactSection] = []
        for ordinal, section in enumerate(ir.sections):
            if not section.awaiting_prose:
                sections.append(section)
                continue

            request = _request_for(world, ir, section, facts)
            if not request.allowed_fact_ids:
                # Nothing to say and nothing to say it with. Better an empty
                # section than prose invented to fill it.
                sections.append(section)
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
                narrative = GeneratedNarrative.model_validate(existing.output)
                replayed += 1
                recorded.append(existing)
            else:
                narrative, attempts = _generate(
                    provider, request, prompt, facts,
                    entity_names=entity_names, retries=retries,
                )
                provider_calls += 1 + attempts
                rejected += attempts
                recorded.append(
                    GenerationLedgerEntry(
                        id=minter.next("GEN"),
                        key=key,
                        call_site=call_site,
                        ordinal=ordinal,
                        world_seed=world.seed,
                        input_facts_digest=request.fact_digest,
                        model_id=provider.id,
                        prompt_version=prompt.key,
                        output=narrative.model_dump(mode="json"),
                        rejected_attempts=attempts,
                    )
                )

            sections.append(
                section.model_copy(
                    update={
                        "body": narrative.text,
                        "fact_ids": sorted(
                            {f for claim in narrative.claims for f in claim.supporting_fact_ids}
                            | set(section.fact_ids)
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
