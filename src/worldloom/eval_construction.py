"""Constructive eval tactics over normal canonical artifact intents.

A tactic does not manufacture native files. It records replayable inputs and
lets the existing artifact compiler materialize the resulting intent family.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Any

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
        while cursor.revises and cursor.revises in by_id:
            if cursor.revises in seen:
                raise ValueError("cannot extend a cyclic revision family")
            cursor = by_id[cursor.revises]
            seen.add(cursor.id)
            chain.append(cursor)
        candidate = tuple(reversed(chain))
        if len(candidate) > len(longest):
            longest = candidate
    return longest


def apply_revision_family(
    world: World,
    proposal: TacticProposal,
    *,
    record_recipe: bool = True,
) -> World:
    """Extend one grounded artifact family; store the full operation in recipe.

    These are versions grounded in the same evidence, not claimed business
    restatements. Numerical/content changes require fact interventions first.
    Replay calls this with ``record_recipe=False`` because the operation is
    already present in the recipe being replayed.
    """
    from .recipe import with_step

    if proposal.kind is not TacticKind.REVISION_FAMILY:
        raise ValueError(f"expected revision_family tactic, got {proposal.kind.value}")
    allowed = {"artifact_type", "minimum", "source_event_id"}
    if set(proposal.parameters) - allowed:
        raise ValueError("revision tactic cannot ignore unsupported selector constraints")
    artifact_type = proposal.parameters.get("artifact_type")
    minimum = proposal.parameters.get("minimum", 1)
    if not isinstance(artifact_type, str) or not artifact_type:
        raise ValueError("revision_family requires artifact_type")
    if not isinstance(minimum, int) or isinstance(minimum, bool) or not 1 <= minimum <= 256:
        raise ValueError("revision_family minimum must be an integer in [1,256]")
    source_event = proposal.parameters.get("source_event_id")
    if source_event is not None and (not isinstance(source_event, str) or source_event not in world.events.ids()):
        raise ValueError("revision source_event_id must name an existing world event")
    matching = tuple(intent for intent in world.artifact_intents if intent.artifact_type == artifact_type)
    if not matching:
        raise ValueError(f"world has no {artifact_type!r} artifact to revise")
    chain = _longest_revision_chain(matching)
    if len(chain) >= minimum:
        return world
    intents = list(world.artifact_intents)
    identifiers = {intent.id for intent in intents}
    previous = chain[-1]
    for ordinal in range(len(chain), minimum):
        identifier = "ART-" + content_key("eval-revision", world.seed or 0, proposal.id, previous.id, ordinal)[:16].upper()
        if identifier in identifiers:
            raise ValueError(f"revision identifier collision: {identifier}")
        triggered_by = list(previous.triggered_by)
        if isinstance(source_event, str) and source_event not in triggered_by:
            triggered_by.append(source_event)
        revision = previous.model_copy(update={
            "id": identifier, "revises": previous.id, "supersedes": None, "restates": None,
            "triggered_by": triggered_by,
            "rationale": f"Revision {ordinal + 1} satisfies the eval revision-family requirement using the same resolved evidence.",
        }, deep=True)
        intents.append(revision)
        identifiers.add(identifier)
        previous = revision
    recipe = (
        with_step(
            world.recipe,
            "EvalRevisionFamily",
            proposal=proposal.model_dump(mode="json"),
        )
        if record_recipe
        else dict(world.recipe)
    )
    applied = set(recipe.get("eval_tactics", []))
    applied.add(proposal.id)
    recipe["eval_tactics"] = sorted(applied)
    return replace(world, _artifact_intents=tuple(intents), _artifact_irs=(),
                   _artifacts=(), _rendered=(), _recipe=recipe)


@dataclass(frozen=True)
class EvalRevisionFamily:
    """The recipe verb behind ``apply_revision_family``.

    Registered from this module, never as a literal in ``recipe.py`` — the same
    seam ``messiness.Imperfections`` and ``scenarios.AccessProfile`` use, for
    the reason ``recipe._STEP_REGISTRY`` documents. What this closes: the
    tactic recorded ``EvalRevisionFamily`` on every world it touched, but the
    verb was never registered anywhere, so ``with_step`` refused the record at
    the moment of writing it (``unknown scenario 'EvalRevisionFamily'``, three
    tests in ``tests/test_eval_construction.py``) and a corpus that *had* been
    written could not have replayed. A one-shot repair workflow was meant to add
    the verb to ``recipe.py`` by string patch and never ran.

    Replay re-records: ``run`` calls the same function with the same recording
    default the original call used, so the rebuilt recipe carries the step in
    the same position — ``AccessProfile.run`` re-records itself the same way.
    The idempotence guard inside ``apply_revision_family`` (a chain already at
    the minimum returns the world untouched) is what keeps a replayed step from
    minting a second family on top of the first.
    """

    proposal: dict[str, Any]
    physics: Any = None
    """Never read. Declared because ``recipe._under`` rebinds recorded physics
    onto every registered step's spec and raises on one that cannot carry
    them — ``messiness.Imperfections.physics``' reason verbatim."""

    def run(self, world: World) -> World:
        return apply_revision_family(world, TacticProposal.model_validate(self.proposal))


from . import recipe as _recipe

_recipe.register_step("EvalRevisionFamily", ("proposal",), EvalRevisionFamily)


__all__ = ["EvalRevisionFamily", "apply_revision_family"]
