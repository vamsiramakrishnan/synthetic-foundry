"""Constructive eval tactics over ordinary Worldloom worlds.

This module is deliberately small. A tactic changes canonical generation state;
it never fabricates rendered files or connector payloads. Independent candidate
validation still decides whether the result satisfies the originating EvalSpec.
"""

from __future__ import annotations

from dataclasses import replace

from .eval_tactics import TacticKind, TacticProposal
from .ids import content_key
from .models import ArtifactIntent
from .world import World


def _longest_revision_chain(intents: tuple[ArtifactIntent, ...]) -> tuple[ArtifactIntent, ...]:
    by_id = {intent.id: intent for intent in intents}
    longest: tuple[ArtifactIntent, ...] = ()
    for intent in sorted(intents, key=lambda item: item.id):
        chain = [intent]
        seen = {intent.id}
        cursor = intent
        while cursor.revises and cursor.revises in by_id and cursor.revises not in seen:
            cursor = by_id[cursor.revises]
            seen.add(cursor.id)
            chain.append(cursor)
        candidate = tuple(reversed(chain))
        if len(candidate) > len(longest):
            longest = candidate
    return longest


def apply_revision_family(world: World, proposal: TacticProposal) -> World:
    """Extend one existing artifact into a deterministic revision family.

    The existing intent supplies author, audience, evidence and artifact grammar.
    New versions change identity and ``revises`` only; they do not invent new
    business facts. Clearing compiled/rendered artifacts is intentional: the
    normal artifact compiler must resolve the new intents on the next compile.
    """

    if proposal.kind != TacticKind.REVISION_FAMILY:
        raise ValueError(f"expected revision_family tactic, got {proposal.kind.value}")
    artifact_type = proposal.parameters.get("artifact_type")
    minimum = proposal.parameters.get("minimum", 1)
    if not isinstance(artifact_type, str) or not artifact_type:
        raise ValueError("revision_family requires artifact_type")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or minimum < 1:
        raise ValueError("revision_family minimum must be a positive integer")

    matching = tuple(
        intent for intent in world.artifact_intents if intent.artifact_type == artifact_type
    )
    if not matching:
        raise ValueError(f"world has no {artifact_type!r} artifact to revise")

    chain = _longest_revision_chain(matching)
    if len(chain) >= minimum:
        return world

    intents = list(world.artifact_intents)
    previous = chain[-1]
    for ordinal in range(len(chain), minimum):
        identifier = "ART-" + content_key(
            "eval-revision", world.seed or 0, proposal.id, previous.id, ordinal
        )[:16].upper()
        revision = previous.model_copy(
            update={
                "id": identifier,
                "revises": previous.id,
                "supersedes": None,
                "restates": None,
                "rationale": (
                    f"Revision {ordinal + 1} generated to satisfy an eval-first "
                    "revision-family requirement from the same resolved evidence."
                ),
            }
        )
        intents.append(revision)
        previous = revision

    recipe = dict(world.recipe)
    applied = list(recipe.get("eval_tactics", []))
    if proposal.id not in applied:
        applied.append(proposal.id)
    recipe["eval_tactics"] = sorted(applied)
    return replace(
        world,
        _artifact_intents=tuple(intents),
        _artifact_irs=(),
        _artifacts=(),
        _rendered=(),
        _recipe=recipe,
    )


__all__ = ["apply_revision_family"]
