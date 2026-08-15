"""Deterministic randomness.

Every random choice in a generated world comes from here, and every stream is
derived from the world seed by a stable name rather than by draw order. That
matters more than it sounds: if generators shared one stream, adding a draw to
the organisation generator would reshuffle every financial figure downstream, and
a seed would stop meaning anything across versions.

    rng = Rng(8128)
    org = rng.derive("organisation")     # independent, reproducible
    fin = rng.derive("finance")          # unaffected by anything org draws

Seeded from ``content_key``, which is SHA-256 rather than ``hash()`` — Python
randomises string hashing per process, so ``hash()`` would make a seed
irreproducible between runs.
"""

from __future__ import annotations

import random
from collections.abc import Sequence
from typing import TypeVar

from .ids import content_key

T = TypeVar("T")


class Rng:
    """A named, reproducible random stream."""

    __slots__ = ("_random", "label", "seed")

    def __init__(self, seed: int, label: str = "root") -> None:
        self.seed = seed
        self.label = label
        self._random = random.Random(int(content_key(seed, label), 16))

    def derive(self, label: str) -> Rng:
        """A child stream, independent of what this one draws."""
        return Rng(self.seed, f"{self.label}/{label}")

    # -- draws -------------------------------------------------------------

    def integer(self, low: int, high: int) -> int:
        """An integer in ``[low, high]``."""
        return self._random.randint(low, high)

    def number(self, low: float, high: float, *, places: int | None = None) -> float:
        """A float in ``[low, high]``, optionally rounded."""
        value = self._random.uniform(low, high)
        return value if places is None else round(value, places)

    def choice(self, options: Sequence[T]) -> T:
        """One of *options*."""
        if not options:
            raise ValueError("cannot choose from an empty sequence")
        return options[self._random.randrange(len(options))]

    def sample(self, options: Sequence[T], count: int) -> list[T]:
        """*count* distinct members of *options*, order stable for a given seed."""
        if count > len(options):
            raise ValueError(f"cannot sample {count} from {len(options)}")
        return self._random.sample(list(options), count)

    def shuffled(self, options: Sequence[T]) -> list[T]:
        """A shuffled copy."""
        out = list(options)
        self._random.shuffle(out)
        return out

    def weighted(self, options: Sequence[T], weights: Sequence[float]) -> T:
        """One of *options*, chosen with *weights*."""
        if len(options) != len(weights):
            raise ValueError("options and weights must be the same length")
        return self._random.choices(list(options), weights=list(weights), k=1)[0]

    def chance(self, probability: float) -> bool:
        """``True`` with the given probability.

        Lore adjusts probabilities through ``event_likelihood`` multipliers, so
        this is the hook where a 2024 decision makes a 2026 incident more likely.
        """
        return self._random.random() < probability

    def __repr__(self) -> str:
        return f"Rng(seed={self.seed}, label={self.label!r})"
