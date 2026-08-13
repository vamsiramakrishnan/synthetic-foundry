"""One champion per named niche, so a batch spans a space instead of converging in it.

The measured problem is recorded in ``compiler.diversity``'s own field notes: a
12-period retail corpus is 85 artifacts standing on **9 distinct shapes**, and
the same corpus at 48 periods is 340 artifacts standing on the *same* 9 — unique
shape ratio 11% then 2.6%, worst repeated shape 12 copies then 48. Every
mechanism this repository had to fight that works on a *pool that already
exists*: ``compiler.diversity.select`` picks the k most unlike each other from
one artifact's candidates, ``assign`` spreads a batch across the shapes it was
offered. Neither can report the shape nobody proposed. Overgenerate and keep the
best n and you get n variants of whichever shape scores well — a population that
has converged, which is exactly what 340 artifacts on 9 shapes is.

A MAP-Elites archive (Mouret & Clune) inverts that. Name the niches of a
behaviour space *first*, keep the single best candidate found for each, and what
you ship is one champion per niche — the empty ones stay empty and are
*reported* (`Archive.holes`) rather than being invisible for want of anybody
having asked. The behaviour characterization is already here:
`compiler.diversity.Fingerprint` summarises an artifact's shape and
`compiler.diversity.distance` measures between two of them. What was missing is
the archive and the accept/reject rule, which is this module and nothing else —
a hundred lines, not a framework, and no `pyribs` dependency.

**How this differs from `dispersion.farthest_first`, honestly.** They are not
two spellings of one idea and neither subsumes the other:

* `farthest_first` needs the whole pool in hand and returns a *relative*
  guarantee — each pick is as far as possible from the picks before it. Change
  the pool and every pick can change; a pool containing no sparse unit-scoped
  shape yields a spread selection that quietly contains no sparse unit-scoped
  shape, and nothing in the answer says so.
* An archive needs no pool. It takes candidates one at a time, in any order and
  in any number, and returns an *absolute* guarantee against a vocabulary the
  caller declared: this niche holds the best thing anyone has yet offered for
  it, and these niches hold nothing.
* The price is symmetric. `farthest_first` has a distance and no vocabulary, so
  it cannot tell you which region of the space it missed. The archive has a
  vocabulary and no distance, so it cannot tell you that two of its occupied
  niches hold shapes a reader would not tell apart — bucket boundaries are the
  caller's assertion about what counts as different, and a coarse axis hides a
  clump the same way a coarse histogram does.

They compose in the obvious direction: fill an archive from a generate-and-test
loop, then run `farthest_first` over `elites()` when you want fewer than all of
them.

**Order independence is the whole reason this module is not trivial.** See
`_beats`.

A pure library: standard library only, no world objects, no `Rng`. Nothing here
draws — every decision is settled by the candidates themselves.
"""

from __future__ import annotations

import math
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from itertools import product

# ---------------------------------------------------------------------------
# 1. The behaviour space
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Axis:
    """One named dimension of the behaviour space, cut into ordered buckets.

    Buckets are *ordered*, not merely distinct, and the order is the caller's
    claim about the axis — `("sparse", "balanced", "dense")` is a scale and
    reads as one in `elites()` and `holes()`, which sort by bucket position
    rather than alphabetically. Alphabetical order would print that scale as
    balanced, dense, sparse and make a report of an ordinal axis unreadable.
    """

    name: str
    buckets: tuple[str, ...]

    def __post_init__(self) -> None:
        # Validated here rather than in `Archive.__init__` so the invariant
        # holds wherever an `Axis` is built — a one-bucket axis is not a
        # dimension of anything, and a repeated bucket makes `capacity()` (a
        # product of bucket counts) disagree with the number of coordinates the
        # grid can actually take, which would silently overstate every hole.
        if len(self.buckets) < 2:
            raise ValueError(
                f"axis {self.name!r} needs at least 2 buckets to be a dimension,"
                f" got {len(self.buckets)}"
            )
        # `set` for a count only — never iterated, so no ordering reaches output.
        if len(set(self.buckets)) != len(self.buckets):
            raise ValueError(f"axis {self.name!r} has duplicate buckets: {self.buckets}")


#: One bucket per axis, in axis order. A plain tuple rather than a mapping
#: because it is a dictionary key on the hot path of `consider`, and because a
#: mapping would let a caller supply the axes in an order they never declared.
Coordinates = tuple[str, ...]


@dataclass(frozen=True)
class Elite:
    """The champion of one niche: the caller's identity for it, where it sits,
    and what it scored. Deliberately holds no reference to the candidate object
    — the caller owns that, and keeping the archive to keys is what lets it be
    tested, printed and diffed without dragging a `Composition` along."""

    key: str
    """The caller's stable identity for the item. Stable is load-bearing: it is
    the tie-break, so a key derived from `id()` or a counter would reintroduce
    the order dependence the tie-break exists to remove."""
    coordinates: Coordinates
    fitness: float


def _beats(challenger: Elite, incumbent: Elite) -> bool:
    """Whether *challenger* displaces *incumbent* from their shared niche.

    **The archive must be a pure function of the set of candidates considered,
    never of the order they arrived in.** A naive ``fitness > incumbent.fitness``
    is not: the moment two candidates tie, the first one through the door wins,
    and fitness here is routinely a small integer or a bounded score, so ties
    are the common case rather than the corner. Two runs considering the same
    population in different orders would then build different archives, ship
    different corpora, and fail CI's byte-diff — with a diff pointing at a
    document rather than at this line.

    So a tie is broken by the **lexicographically smaller key**, which is a
    property of the candidates and of nothing else. With that, the winner of a
    niche is ``min`` over its candidates by ``(-fitness, key)``: a total order
    over the set, computable in any order, including all at once.

    Written as an explicit comparison rather than as ``(-a.fitness, a.key) <
    (-b.fitness, b.key)`` because negating a fitness is a second thing that can
    be wrong (``-0.0``, and ``-inf`` for a candidate legitimately scored at
    infinity), and this reads as the rule it is.

    NaN cannot reach here — `Archive.consider` refuses it — which is what keeps
    this a total order. See there for why.
    """
    if challenger.fitness != incumbent.fitness:
        return challenger.fitness > incumbent.fitness
    return challenger.key < incumbent.key


# ---------------------------------------------------------------------------
# 2. The archive
# ---------------------------------------------------------------------------


class Archive:
    """A MAP-Elites archive: at most one `Elite` per cell of the axes' grid.

    A dictionary keyed by coordinates plus the tie rule in `_beats`, and it is
    meant to stay that size. Every accessor sorts before it returns, so the
    insertion order of the underlying dict — which *is* consider order — never
    reaches a caller and cannot reach a corpus.
    """

    __slots__ = ("_axes", "_bucket_positions", "_elites")

    def __init__(self, axes: Sequence[Axis]) -> None:
        if not axes:
            # An archive over no axes would be a single anonymous cell holding
            # the single best candidate — "overgenerate and keep the best one",
            # which is the behaviour this module exists to replace. Refused
            # rather than silently provided, because a caller who passed an
            # empty axis list built it by accident and would get a plausible,
            # wrong, fully converged answer with no sign anything was missed.
            raise ValueError("an archive needs at least one axis to be an archive")
        names = [axis.name for axis in axes]
        if len(set(names)) != len(names):
            raise ValueError(f"axes must have distinct names, got {tuple(names)}")
        self._axes: tuple[Axis, ...] = tuple(axes)
        # Bucket -> position, per axis. Built once: `consider` validates every
        # coordinate and `elites()` ranks by position, and both would otherwise
        # be a linear scan of the axis on every call.
        self._bucket_positions: tuple[dict[str, int], ...] = tuple(
            {bucket: position for position, bucket in enumerate(axis.buckets)} for axis in axes
        )
        self._elites: dict[Coordinates, Elite] = {}

    # -- filling -----------------------------------------------------------

    def consider(self, key: str, coordinates: Coordinates, fitness: float) -> bool:
        """Offer a candidate to its niche. ``True`` if the archive changed.

        ``False`` covers both ways nothing happened — the niche is held by a
        better candidate, or by an equal one with a smaller key — because from
        the caller's side they are one outcome: this candidate is not in the
        archive right now.

        **This return value is order-dependent, and the archive is not.** A
        candidate that takes a niche and is displaced later answered ``True``,
        so the same population considered in two orders accepts a different
        number of times: measured on the population in `tests/test_archive.py`,
        120 candidates over 36 niches reject 71 times in population order and
        between 49 and 68 across two hundred shuffles, while every one of those
        runs produces a byte-identical `elites()`. That is not a hole in the
        order-independence claim — the claim is about the archive's *state* —
        but it means a rejection count is a diagnostic and never a figure to
        put in a corpus. The invariant that does hold in any order is
        ``accepted >= occupied``.

        Reconsidering a candidate already installed returns ``False``: it does
        not beat itself on either term of `_beats`, and the archive is
        unchanged, which is what the return value reports.
        """
        cell = self._validated(coordinates)
        if math.isnan(fitness):
            # NaN compares false against everything, itself included, so a NaN
            # fitness would make `_beats` false in both directions: the
            # incumbent would keep the niche purely because it arrived first,
            # and the archive would depend on consider order again — the one
            # thing this module promises it does not. Refused at the door, where
            # the caller can still see which candidate produced it.
            raise ValueError(f"candidate {key!r} has a NaN fitness, which has no place in an order")

        challenger = Elite(key=key, coordinates=cell, fitness=fitness)
        incumbent = self._elites.get(cell)
        if incumbent is not None and not _beats(challenger, incumbent):
            return False
        self._elites[cell] = challenger
        return True

    def _validated(self, coordinates: Coordinates) -> Coordinates:
        """*coordinates* as a tuple, or `ValueError` naming the offending axis.

        A mis-binned elite is undiagnosable later — it is a document sitting in
        the wrong cell of a report nobody re-derives — so this refuses rather
        than coercing, and every message names the axis that could not be
        matched instead of only the coordinate that failed.
        """
        cell = tuple(coordinates)
        if len(cell) != len(self._axes):
            if len(cell) < len(self._axes):
                detail = f"nothing for axis {self._axes[len(cell)].name!r}"
            else:
                detail = f"{cell[len(self._axes):]!r} beyond the last axis {self._axes[-1].name!r}"
            raise ValueError(
                f"coordinates {cell!r} do not match the {len(self._axes)} axes"
                f" ({', '.join(axis.name for axis in self._axes)}): {detail}"
            )
        for axis, positions, bucket in zip(self._axes, self._bucket_positions, cell, strict=True):
            if bucket not in positions:
                raise ValueError(
                    f"{bucket!r} is not a bucket of axis {axis.name!r};"
                    f" expected one of {axis.buckets}"
                )
        return cell

    # -- reading -----------------------------------------------------------

    def elites(self) -> tuple[Elite, ...]:
        """Every champion, sorted by coordinates in *axis bucket order*.

        Sorted by each bucket's position on its axis rather than by the bucket
        string, because `Axis.buckets` is ordered and the caller said so: a
        sparse/balanced/dense axis sorted alphabetically reads balanced, dense,
        sparse, which is not a scale. The sort key is total (coordinates are
        unique keys of a dict), so the returned order depends on nothing but
        the set of elites — never on which of them was considered first.
        """
        return tuple(sorted(self._elites.values(), key=lambda elite: self._rank(elite.coordinates)))

    def holes(self) -> tuple[Coordinates, ...]:
        """Every unoccupied niche, in the same order `elites()` uses.

        The half of a quality-diversity result that a "keep the best n" ranking
        structurally cannot produce: not "here is what we made" but "here is
        what nobody proposed". A hole is a stopping condition and a work item,
        which a count of documents is neither.
        """
        return tuple(cell for cell in self._grid() if cell not in self._elites)

    def capacity(self) -> int:
        """How many niches the axes describe — the product of their bucket
        counts. Grows multiplicatively, which is the number to look at before
        adding a fourth axis: it is a target for generation, and an archive
        with more niches than the loop will ever produce candidates for reports
        a low `fill` forever and says nothing about the corpus."""
        return math.prod(len(axis.buckets) for axis in self._axes)

    @property
    def occupied(self) -> int:
        """How many niches hold a champion."""
        return len(self._elites)

    def fill(self) -> float:
        """`occupied` over `capacity` — how much of the space has been reached.

        The headline reading of a quality-diversity run, and the one that
        answers "are we done" without appealing to a document count.
        """
        capacity = self.capacity()
        if capacity == 0:
            # Unreachable as the constructor stands: an axis carries at least 2
            # buckets and an archive at least one axis, so the product is at
            # least 2. Kept because it is the only line between this reading and
            # a ZeroDivisionError, and the two invariants that make it dead live
            # in `Axis.__post_init__` and `__init__` rather than here — a later
            # axis kind that admits an empty bucket tuple would make it live
            # again, and would not think to come and look.
            return 0.0
        return self.occupied / capacity

    # -- internals ---------------------------------------------------------

    def _grid(self) -> Iterator[Coordinates]:
        """Every coordinate the axes describe, in declared bucket order.

        `itertools.product` varies the last axis fastest and preserves each
        axis's own bucket order, which is exactly `_rank`'s ordering — so
        `holes()` needs no sort, and cannot drift out of step with `elites()`.
        """
        return product(*(axis.buckets for axis in self._axes))

    def _rank(self, coordinates: Coordinates) -> tuple[int, ...]:
        """*coordinates* as bucket positions — the sort key for `elites()`."""
        return tuple(
            positions[bucket]
            for positions, bucket in zip(self._bucket_positions, coordinates, strict=True)
        )

    def __repr__(self) -> str:
        # Defined rather than inherited: the default carries a memory address,
        # and this repository diffs its own output — an address that reaches a
        # log or a report is a line that differs between two runs of one seed.
        axes = " x ".join(f"{axis.name}({len(axis.buckets)})" for axis in self._axes)
        return f"Archive({axes}: {self.occupied}/{self.capacity()} niches, {self.fill():.0%} full)"


__all__ = ["Archive", "Axis", "Coordinates", "Elite"]
