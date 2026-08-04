"""The closed loop: measure the corpus, spend effort where it is weakest, prove it moved.

Narration today is **open-loop**. Every section gets one request, one budget and
one attempt, and nothing afterwards looks at what the corpus became. The result
is measurable and this repository already measures it: a three-period grocery
corpus carries **16 groups of near-identical passages**, and twenty-one
artifacts land on **eight distinct shapes**. Build-order §7a records the same
thing at size — 120 artifacts, 11 shapes. Every close pack is one document with
different numbers, and narrating harder does not fix it, because the writer of
section 47 has never been told that sections 12 and 31 already said this.

This module closes the loop. Four steps, and the interesting property is that
the *algorithm* owns three of them:

1. **Measure.** :func:`measure` runs the exact similarity join over the
   corpus's own passages and the fingerprint collision count over its shapes.
   Exact, not sampled — see ``similarity.near_duplicate_pairs``.
2. **Target.** :func:`targets` ranks the repetition and picks what to rewrite,
   keeping one member of each cluster as the exemplar. This is where the
   hundred-fold is: a three-period corpus has ~130 sections and ~16 that
   actually repeat. Re-narrating everything to fix them is the open-loop
   answer; re-narrating sixteen is this one.
3. **Constrain.** The exemplar's *text* becomes the brief — carried on the
   request as ``avoid_texts`` and rendered by the ``section_prose_varied``
   prompt. "Be more varied" is advice. "Here is the passage you are being
   confused with" is a constraint.
4. **Gate.** :func:`judge` re-measures the answer against the exemplar and
   rejects a rewrite that did not actually move, quoting the number. The model
   is not asked to assess its own variety; the same join that found the problem
   decides whether it is fixed.

Then it repeats until the measurement stops improving. :func:`plateaued` is the
stopping rule, and it exists because a budget-driven loop with no plateau
detection spends its whole budget on a corpus that got as good as it was going
to get in round two.

**What this does not touch.** Every existing validator still runs, unchanged: a
rewrite that invents a figure, cites an unavailable fact, or names an entity
that does not exist is rejected exactly as a first draft would be. The loop
widens *how much the model may vary*, and narrows nothing about what it may
assert. That is the whole shape of the bargain — and it is why the similarity
gate is an addition to the claim validators rather than a replacement for any
of them.

**Where the agent fits.** Nothing here calls a model. `worldloom refine` drives
the loop headlessly through a ``Provider`` (the Claude Code harness, by
default), and `worldloom mcp` exposes exactly these functions as tools so an
agent can drive the same loop from inside its own session — measure, ask for
the next target, write, submit, repeat. Both paths run the identical algorithms
in this file, which is what stops the interactive loop and the headless one
from drifting into two different definitions of "better".
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from . import similarity
from .compiler import diversity as diversity_module
from .evaluate.bm25 import tokens
from .evaluate.index import Passage, passages
from .stats import NEAR_DUPLICATE_THRESHOLD, SHINGLE_SIZE

if TYPE_CHECKING:  # pragma: no cover
    from .world import World

#: How similar a rewrite is still allowed to be to the passage it was told to
#: differ from. Lower than ``NEAR_DUPLICATE_THRESHOLD`` (0.8) on purpose: coming
#: to rest just under the line the measurement uses would produce a corpus that
#: passes the audit and still reads as one template. The gap between the two is
#: the margin that makes the improvement real rather than nominal.
REWRITE_CEILING = 0.55

#: Sections to target in one round by default. A bound rather than a target —
#: an unbounded round on a large corpus is an unbounded bill, and the whole
#: argument of this module is that effort should be spent where it counts.
DEFAULT_BUDGET = 16

#: How much the near-duplicate count must fall for a round to count as
#: progress. One pair on a corpus with two hundred is noise, and a loop that
#: treats it as progress never stops.
PROGRESS_FLOOR = 1


def _shingles(text: str) -> frozenset[tuple[str, ...]]:
    """A passage as its token shingle set, exactly as ``stats`` sees it.

    Imported from there rather than re-derived, so "near-duplicate" means one
    thing in the report and in the gate. Two definitions that could drift apart
    is how a loop ends up optimising a number nobody is reading.
    """
    return similarity.shingles(tokens(text), SHINGLE_SIZE)


# ---------------------------------------------------------------------------
# Measure
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Measurement:
    """What the corpus repeats, right now."""

    passages: int
    duplicate_pairs: int
    clusters: tuple[tuple[int, ...], ...]
    """Groups of mutually near-duplicate passages, by index into ``pool``."""
    pool: tuple[Passage, ...]
    artifacts: int
    distinct_shapes: int
    shape_collisions: tuple[tuple[str, tuple[int, ...]], ...]

    @property
    def duplicate_rate(self) -> float:
        """Duplicate pairs as a fraction of all pairs."""
        total = self.passages * (self.passages - 1) // 2
        return self.duplicate_pairs / total if total else 0.0

    @property
    def repeated_passages(self) -> int:
        """How many passages sit in some duplicate cluster — the number the
        loop is actually trying to reduce, and the one a reader cares about.
        A pair count squares with cluster size and so overstates a single
        eleven-way repeat as fifty-five problems."""
        return sum(len(group) for group in self.clusters)

    def as_dict(self) -> dict[str, Any]:
        return {
            "passages": self.passages,
            "duplicate_pairs": self.duplicate_pairs,
            "duplicate_rate": round(self.duplicate_rate, 6),
            "repeated_passages": self.repeated_passages,
            "clusters": [
                {
                    "size": len(group),
                    "artifacts": sorted({self.pool[i].artifact_id for i in group}),
                    "excerpt": self.pool[group[0]].text[:160],
                }
                for group in self.clusters
            ],
            "artifacts": self.artifacts,
            "distinct_shapes": self.distinct_shapes,
            "shape_collisions": [
                {"digest": digest, "count": len(members)}
                for digest, members in self.shape_collisions
            ],
        }

    def __str__(self) -> str:
        return (
            f"Repetition — {self.repeated_passages} of {self.passages} passage(s) "
            f"in {len(self.clusters)} duplicate group(s); "
            f"{self.distinct_shapes} distinct shape(s) across {self.artifacts} artifact(s)"
        )


def measure(world: World) -> Measurement:
    """Everything the loop needs to decide what to do next.

    Prose repetition and structural repetition together, because they are
    different failures with different fixes: twenty distinct shapes can still
    say the same sentences inside all of them, and one shape used twenty times
    can carry twenty genuinely different arguments. A loop that watched only
    one of them would declare victory over the other.
    """
    pool = tuple(passages(world))
    sets = [_shingles(passage.text) for passage in pool]
    pairs = similarity.near_duplicate_pairs(sets, NEAR_DUPLICATE_THRESHOLD)
    clusters = similarity.clusters(pairs, len(pool))

    fingerprints = _fingerprints(world)
    collisions = diversity_module.collisions(fingerprints)
    distinct = len({fp.digest() for fp in fingerprints})

    return Measurement(
        passages=len(pool),
        duplicate_pairs=len(pairs),
        clusters=clusters,
        pool=pool,
        artifacts=len(fingerprints),
        distinct_shapes=distinct,
        shape_collisions=collisions,
    )


def _fingerprints(world: World) -> list[diversity_module.Fingerprint]:
    """Structural fingerprints for every compilable artifact.

    Anything neither the workbook nor the document renderer claims is a record
    projection rather than a component composition and has no shape to
    fingerprint — the same split ``worldloom diversity`` draws, duplicated here
    rather than imported from the CLI because a library must not depend on its
    own front end.
    """
    from .compiler.compose import compose, plan_from_ir
    from .render.docx import HANDLES as DOCX_TYPES
    from .render.xlsx import HANDLES as XLSX_TYPES

    out: list[diversity_module.Fingerprint] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        if intent.artifact_type in XLSX_TYPES:
            fmt = "xlsx"
        elif intent.artifact_type in DOCX_TYPES:
            fmt = "docx"
        else:
            continue
        plan = plan_from_ir(
            ir, artifact_type=intent.artifact_type, size_class=intent.size_profile
        )
        out.append(diversity_module.fingerprint(compose(plan, fmt=fmt)))
    return out


# ---------------------------------------------------------------------------
# Target
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Target:
    """One section worth rewriting, and what it must stop resembling."""

    artifact_id: str
    heading: str
    avoid_texts: tuple[str, ...]
    """The exemplars this section is currently indistinguishable from."""
    exemplar_of: str
    """The artifact whose passage was kept, so a reader can go and compare."""
    similarity: float
    """How similar this passage currently is to its exemplar."""
    ceiling: float
    """What it must get below to be accepted."""

    @property
    def id(self) -> str:
        return f"{self.artifact_id}/{self.heading}"

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "artifact_id": self.artifact_id,
            "heading": self.heading,
            "currently_similar_to": self.exemplar_of,
            "similarity": round(self.similarity, 4),
            "must_get_below": self.ceiling,
            "avoid_texts": list(self.avoid_texts),
        }


def targets(
    measurement: Measurement, *, budget: int = DEFAULT_BUDGET,
    ceiling: float = REWRITE_CEILING,
) -> tuple[Target, ...]:
    """What to rewrite, worst first, within *budget*.

    **One member of each cluster is kept.** A group of three identical passages
    is not three problems; it is one passage that exists three times, and
    rewriting all three would spend three calls to fix two. The kept exemplar
    is the lowest-indexed member, which makes the choice a function of the
    corpus's own traversal order rather than of anything this call decides.

    Ordered by cluster size, so an eleven-way repeat is dealt with before a
    pair. Ties break on the passage's own identity, so two clusters of equal
    size are always handled in the same order.
    """
    ranked = sorted(
        measurement.clusters,
        key=lambda group: (-len(group), measurement.pool[group[0]].artifact_id, group),
    )
    out: list[Target] = []
    for group in ranked:
        exemplar = measurement.pool[group[0]]
        exemplar_shingles = _shingles(exemplar.text)
        for index in group[1:]:
            if len(out) >= budget:
                return tuple(out)
            passage = measurement.pool[index]
            out.append(Target(
                artifact_id=passage.artifact_id,
                heading=passage.heading,
                avoid_texts=(exemplar.text,),
                exemplar_of=exemplar.artifact_id,
                similarity=similarity.jaccard(_shingles(passage.text), exemplar_shingles),
                ceiling=ceiling,
            ))
    return tuple(out)


# ---------------------------------------------------------------------------
# Gate
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Judgement:
    """Whether a rewrite actually moved, and by how much."""

    accepted: bool
    similarity: float
    ceiling: float
    detail: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "similarity": round(self.similarity, 4),
            "ceiling": self.ceiling,
            "detail": self.detail,
        }


def judge(
    text: str,
    target: Target,
    facts: dict[str, Any] | None = None,
    *,
    others: Sequence[str] = (),
) -> Judgement:
    """Did this rewrite get far enough from what it was told to avoid?

    Deliberately *not* a question put to the model. An author asked whether its
    own prose is sufficiently different will say yes, and the failure mode this
    exists to stop — a reword that changes every phrase and no structure — is
    precisely the one that reads as different to its writer and scores as
    identical to a retriever. The same join that found the duplication decides
    whether it is gone.

    The rejection quotes the measured figure and the target, because that is
    something an author can act on. "Be more varied" is not.

    ``facts`` substitutes the rewrite's ``{{fact:ID}}`` references before
    comparing, and passing it is close to mandatory. The avoided text comes
    from ``evaluate.index.passages``, which is *rendered* — a retriever indexes
    "1 business day", not the marker that produced it. Comparing a templated
    draft against rendered prose measures the difference between two notations
    as though it were a difference in what the passages say, and scores a
    verbatim copy at nearly zero. The gate then passes everything, which is the
    most expensive way for a loop to appear to work.
    """
    if not text.strip():
        return Judgement(False, 1.0, target.ceiling, "the rewrite is empty")
    rendered = text
    if facts:
        from .narrative import references

        rendered = references.substitute(text, facts)
    candidate = _shingles(rendered)
    worst = 0.0
    for avoided in target.avoid_texts:
        worst = max(worst, similarity.jaccard(candidate, _shingles(avoided)))
    if worst > target.ceiling:
        return Judgement(
            False, worst, target.ceiling,
            f"still {worst:.2f} similar to the passage in {target.exemplar_of}"
            f" (must be at or below {target.ceiling:.2f}). Rewording phrase by phrase"
            " scores as the same passage — change what the section leads with, what it"
            " subordinates, and what it leaves to the table.",
        )

    # And not a duplicate of anything *else* in the corpus either.
    #
    # Checking only the exemplar is not enough, and the loop demonstrates why
    # within one round: two sections told to stop resembling the same exemplar
    # both moved away from it and landed on each other, so three passages
    # became two and the repeated-passage count did not move at all. A gate
    # that can be satisfied by walking from one duplicate into another is a
    # gate the loop can churn against forever.
    #
    # Held to `NEAR_DUPLICATE_THRESHOLD` rather than the tighter ceiling: the
    # ceiling is a deliberate margin against the *specific* passage this
    # rewrite was confused with, and applying it corpus-wide would refuse
    # perfectly ordinary sections that merely share a register with something
    # at the other end of the estate.
    for other in others:
        against = similarity.jaccard(candidate, _shingles(other))
        if against >= NEAR_DUPLICATE_THRESHOLD:
            return Judgement(
                False, against, target.ceiling,
                f"clear of {target.exemplar_of}, but {against:.2f} similar to another"
                " passage already in the corpus — the rewrite moved out of one"
                " duplicate group and into another. It has to be unlike everything,"
                " not unlike one thing.",
            )

    return Judgement(
        True, worst, target.ceiling,
        f"{worst:.2f} similar to {target.exemplar_of}, at or below the {target.ceiling:.2f} ceiling",
    )


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------


def plateaued(history: list[Measurement], *, floor: int = PROGRESS_FLOOR) -> bool:
    """Whether the last round bought less than *floor* fewer repeated passages.

    A loop with a budget and no stopping rule spends the whole budget, which on
    a corpus that got as good as it was going to get in round two is most of
    the budget wasted. Measured on repeated *passages* rather than pairs: pair
    count grows with the square of cluster size, so breaking one eleven-way
    repeat into two five-way ones looks like enormous progress and is very
    little.
    """
    if len(history) < 2:
        return False
    return history[-2].repeated_passages - history[-1].repeated_passages < floor


__all__ = [
    "DEFAULT_BUDGET",
    "Judgement",
    "Measurement",
    "PROGRESS_FLOOR",
    "REWRITE_CEILING",
    "Target",
    "judge",
    "measure",
    "plateaued",
    "targets",
]
