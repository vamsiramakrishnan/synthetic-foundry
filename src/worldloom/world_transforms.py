"""Cheap metamorphic transforms over accepted Worldloom worlds.

Transforms are deterministic and publish their oracle effect. They are not new
generators: they reuse an accepted world and vary one controlled dimension while
preserving the invariants declared by the transform.
"""

from __future__ import annotations

from dataclasses import replace
from enum import StrEnum
from typing import Protocol

from .ids import content_key
from .models import Authority, CanonicalFact
from .world import World


class OracleEffect(StrEnum):
    PRESERVE = "preserve"
    REMAP = "remap"


class TransformResult:
    def __init__(
        self,
        *,
        world: World,
        transform_id: str,
        oracle_effect: OracleEffect,
        added_ids: tuple[str, ...] = (),
    ) -> None:
        self.world = world
        self.transform_id = transform_id
        self.oracle_effect = oracle_effect
        self.added_ids = added_ids


class WorldTransform(Protocol):
    def apply(self, world: World, *, seed: int) -> TransformResult: ...


class AddIrrelevantFacts:
    """Increase retrieval density without changing any existing answer.

    The added facts use a dedicated kind and company subject, so they cannot
    accidentally satisfy selectors for an existing business fact. This is the
    cheapest metamorphic robustness test: the oracle is exactly preserved while
    the corpus gets noisier.
    """

    def __init__(self, count: int) -> None:
        if count < 0:
            raise ValueError("count must be non-negative")
        self.count = count

    def apply(self, world: World, *, seed: int) -> TransformResult:
        transform_id = content_key("transform", "add-irrelevant-facts", seed, self.count)
        if not self.count:
            return TransformResult(
                world=world,
                transform_id=transform_id,
                oracle_effect=OracleEffect.PRESERVE,
            )
        anchor = min((fact.valid_from for fact in world.facts), default=None)
        if anchor is None:
            raise ValueError("cannot add deterministic noise to a world without a fact clock")
        existing = {fact.id for fact in world.facts}
        additions: list[CanonicalFact] = []
        for index in range(self.count):
            identifier = f"NOISE-{content_key(transform_id, index)[:16].upper()}"
            if identifier in existing:
                raise ValueError(f"noise id collision: {identifier}")
            additions.append(
                CanonicalFact(
                    id=identifier,
                    kind="metamorphic_irrelevant_context",
                    subject=world.company.id,
                    text_value=f"Synthetic irrelevant context {index + 1}",
                    valid_from=anchor,
                    authority=Authority.UNOFFICIAL_NOTE,
                    source_system="worldloom-metamorphic",
                )
            )
        transformed = replace(world, _facts=world._facts + tuple(additions))
        return TransformResult(
            world=transformed,
            transform_id=transform_id,
            oracle_effect=OracleEffect.PRESERVE,
            added_ids=tuple(item.id for item in additions),
        )


__all__ = ["AddIrrelevantFacts", "OracleEffect", "TransformResult", "WorldTransform"]
