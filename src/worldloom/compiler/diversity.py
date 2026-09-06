"""Diversity as a batch property.

A single ``Composition`` cannot be diverse or repetitive — those words only mean
anything once there is a *batch* to compare it against. A 12-period industry
corpus produced 120 artifacts with 11 distinct section shapes: twelve CFO memos,
identical outlines, DOCX sizes spanning only 38,658-40,618 bytes. Nothing in
``compose.py`` was wrong; the composer picks the first fitting component for
each beat in registry order, deterministically, every time, and a plan authored
the same way twelve times in a row produces the same shape twelve times in a
row. That is correct behaviour for one artifact and a defect in the batch.

This module gives the batch a vocabulary:

``Fingerprint``
    A content-addressed summary of one artifact's *structure* — never its
    prose or its facts. Two artifacts with the same fingerprint look
    identical to a reader scanning past the numbers, regardless of which
    numbers they actually carry.
``distance`` / ``report``
    How far apart two fingerprints are, and what a whole batch of them looks
    like: how much of it repeats, how concentrated it is on one component
    family, how long the worst run of an identical shape is.
``Quotas`` / ``check``
    The declarative form of "the batch counts as diverse" from
    ``docs/artifact-compiler.md`` §7, checked the same way ``grammar.check``
    checks a component sequence — every violation returned, none raised.
``select``
    Greedy max-min candidate selection over structural candidates for one
    artifact (§12), so a caller choosing among a handful of valid
    compositions can prefer the one that looks least like its neighbours.

Nothing here decides which facts are true, which components exist, or how a
composition is built — that is `compose.py` and the modules it draws on. This
module only ever *reads* a `Composition` and reports on the shape it already
has.

Determinism, because CI regenerates a 76 MB corpus and diffs it byte-for-byte:
every digest goes through ``ids.content_key`` (SHA-256, not the per-process
salted builtin ``hash()``), and every report or selection is built by walking
its input in the order the *caller* supplied it — never a ``set`` — so the same
batch, iterated the same way, always answers the same way.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ..ids import content_key
from .compose import Composition

# ---------------------------------------------------------------------------
# 1. Fingerprints
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Fingerprint:
    """A content-addressed summary of one artifact's structure.

    Deliberately shape-only: no title, no prose, no fact id. Two artifacts
    about entirely different business units collapse to the same fingerprint
    when they read the same way, which is exactly the property a batch-level
    diversity check needs — it is asking "does this look like something we
    already produced", not "is this the same document".
    """

    artifact_type: str
    components: tuple[str, ...]
    """Component ids in final order, straight from ``Composition.components``."""
    layouts: tuple[str, ...]
    """Per-component layout choice, parallel to ``components`` when supplied.

    Not read off ``Composition`` — the composer does not decide layout, a
    format planner downstream does (see ``ComponentSpec.layouts``, added
    alongside a style system this module does not own). Empty is a legitimate
    fingerprint: a plan composed before layout is decided still has a shape.
    """
    style_key: str
    """Which style genome rendered this artifact, or ``""`` if none was chosen
    yet. Supplied by the caller for the same reason as ``layouts``: style is a
    renderer-local decision this module has no view of composition-side."""
    density_bucket: str
    section_count: int
    """How many components survived compose — the shape a reader actually
    sees, after optional beats were dropped. Not the beat count the plan
    started with: a dropped beat left no trace on the page, so it should not
    make two artifacts that render identically fingerprint differently."""

    def digest(self) -> str:
        """A stable, content-addressed key for this exact shape.

        Every group below is length-prefixed before its members are joined in
        — ``"components", len(...), *components`` rather than a bare
        ``*components`` — so that two fingerprints whose fields differ only in
        *where* a boundary falls (e.g. one more component and one fewer
        layout) can never collide by having their flattened parts read back
        the same way. ``content_key`` itself already guards the *encoding*
        (SHA-256 over parts joined with a separator no field value contains);
        this guards the *shape* of what gets encoded.
        """
        return content_key(
            "artifact_type", self.artifact_type,
            "components", len(self.components), *self.components,
            "layouts", len(self.layouts), *self.layouts,
            "style_key", self.style_key,
            "density_bucket", self.density_bucket,
            "section_count", self.section_count,
        )


#: Component-count thresholds for `_density_bucket`. Bucket *names* are the
#: three `plan.DensityProfile` words on purpose — a diversity report reads
#: naturally next to the rest of the compiler's output only if it uses the
#: same vocabulary for "how much is on the page" that `plan.py` and
#: `compose.py` already established.
#:
#: The numbers themselves are a fresh, independent scale, not borrowed from
#: `compose._COMPONENT_CAP` or `plan.DENSITY_POINTS` — both describe an
#: input to composition (a size-class cap, a density profile picked before
#: compose runs), and this module only ever sees the *output*: how many
#: components a composition actually settled on after budget drops. Reusing
#: an input-side constant here would silently couple two independent
#: decisions that happen to share units today and have no reason to stay in
#: step. Thresholds instead split compose.py's own cap range (4/7/12 for
#: small/medium/long) roughly in half, so a composition that used most but
#: not all of its budget still buckets one step below its own size class
#: rather than always landing in the top bucket.
_SPARSE_MAX_COMPONENTS = 3
_BALANCED_MAX_COMPONENTS = 6


def _density_bucket(component_count: int) -> str:
    """Bucket a composition's final component count into a density word."""
    if component_count <= _SPARSE_MAX_COMPONENTS:
        return "sparse"
    if component_count <= _BALANCED_MAX_COMPONENTS:
        return "balanced"
    return "dense"


def fingerprint(
    composition: Composition, *, style_key: str = "", layouts: Sequence[str] = ()
) -> Fingerprint:
    """The `Fingerprint` for one resolved `Composition`.

    ``style_key`` and ``layouts`` are accepted rather than read off
    *composition* because neither exists there — `Composition` is what
    `compose.py` produces today, before a style genome or a per-component
    layout has been chosen. A caller integrating this module against that
    later stage supplies them; a caller with only a bare composition gets a
    perfectly valid fingerprint that simply carries no opinion on either,
    which is correct rather than a workaround: an artifact with an
    undecided layout has no layout signal to report yet.
    """
    section_count = len(composition.components)
    return Fingerprint(
        artifact_type=composition.artifact_type,
        components=composition.components,
        layouts=tuple(layouts),
        style_key=style_key,
        density_bucket=_density_bucket(section_count),
        section_count=section_count,
    )


# ---------------------------------------------------------------------------
# 2. Distance and diversity metrics
# ---------------------------------------------------------------------------

#: Blend weights for `distance`. Each term below is already normalised to
#: [0, 1], and these sum to 1.0, so the blend itself stays in [0, 1] — see
#: `distance`'s own assertion.
#:
#: Ranked by how much of "does this look like the same document" each field
#: actually carries, using the same reasoning `docs/artifact-compiler.md` §7
#: gives for fingerprints in the first place:
#:
#: - ``components`` (0.45, the majority of the budget): this *is* the shape.
#:   "120 artifacts, 11 distinct section shapes" was a component-sequence
#:   observation, not a style or density one — a reader scanning past the
#:   numbers notices "this is the same document" from the sequence of
#:   sections, before anything else.
#: - ``layouts`` (0.20): the next most visible thing — two artifacts with the
#:   same components but different layouts still read as different pages —
#:   but it is a decision made *about* an already-fixed component sequence,
#:   so it cannot outweigh the sequence itself.
#: - ``style_key`` (0.15): a real visual signal (colour, spacing, type scale)
#:   but a single categorical switch — flip a genome and every artifact in a
#:   batch changes together, so on its own it says little about whether *this
#:   one* artifact stands out from its neighbours.
#: - ``density_bucket`` (0.10): three words wide, derived from a number
#:   (`section_count`) this blend already scores separately — the two are
#:   correlated by construction, so double-weighting the same underlying
#:   signal would be counted twice for one reason.
#: - ``section_count`` (0.10): a single integer. Real signal (a six-section
#:   memo does not read like a two-section one) but the coarsest of the five,
#:   so it gets the smallest share alongside density.
#:
#: ``artifact_type`` is deliberately not a sixth term. It is a real field on
#: `Fingerprint`, kept there so a caller can group or filter by it (see
#: `report`'s `distinct_shapes_by_type`), but it is not blended into
#: *distance* because it would almost always be either redundant or
#: irrelevant to the two ways this module uses distance: candidate selection
#: (`select`) always compares candidates for one artifact, so the field is
#: constant across every pair and would contribute nothing; a cross-type
#: comparison in a batch `report` already reads as maximally different on
#: `components` alone, because `grammar.py` gives every artifact type its own
#: required roles and therefore an essentially disjoint component vocabulary.
#: A term that is either always zero or always saturated earns no weight.
_WEIGHT_COMPONENTS = 0.45
_WEIGHT_LAYOUTS = 0.20
_WEIGHT_STYLE = 0.15
_WEIGHT_DENSITY = 0.10
_WEIGHT_SECTION_COUNT = 0.10

assert math.isclose(
    _WEIGHT_COMPONENTS + _WEIGHT_LAYOUTS + _WEIGHT_STYLE + _WEIGHT_DENSITY + _WEIGHT_SECTION_COUNT,
    1.0,
), "distance weights must sum to 1.0 for the blend to stay in [0, 1]"

#: Ordinal order for `density_bucket`, so "sparse vs dense" scores as more
#: different than "sparse vs balanced" rather than the two counting equally
#: as "just different", the way `style_key`'s bare genome id has to.
_DENSITY_ORDER = ("sparse", "balanced", "dense")


def _levenshtein(a: Sequence[str], b: Sequence[str]) -> int:
    """Edit distance between two token sequences — insert, delete, substitute.

    Order-sensitive on purpose: `distance` uses this for `components`, and a
    grammar violation report already treats "the same components in a
    different order" as a real, different defect (`grammar.py`'s
    `out_of_order`). A set-overlap measure would call a reordered artifact
    identical to the original, which is exactly the distinction this module
    exists to keep.
    """
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, token_a in enumerate(a, start=1):
        current = [i] + [0] * len(b)
        for j, token_b in enumerate(b, start=1):
            cost = 0 if token_a == token_b else 1
            current[j] = min(
                previous[j] + 1,       # delete from a
                current[j - 1] + 1,    # insert into a
                previous[j - 1] + cost,  # substitute (or match)
            )
        previous = current
    return previous[len(b)]


def _sequence_distance(a: tuple[str, ...], b: tuple[str, ...]) -> float:
    """Levenshtein distance normalised to [0, 1] by the longer sequence.

    Edit distance between unit-cost sequences never exceeds ``max(len(a),
    len(b))`` — the longer sequence can always be reached by substituting
    every shared position and inserting the remainder — so dividing by that
    length is always a true normalisation, not a clamp.
    """
    if a == b:
        return 0.0
    denominator = max(len(a), len(b))
    if denominator == 0:
        return 0.0
    return _levenshtein(a, b) / denominator


def _density_distance(a: str, b: str) -> float:
    """Ordinal distance over `_DENSITY_ORDER`; unknown bucket names are just
    "different" (1.0), since only the three named buckets have a defined
    order to be graded against."""
    if a == b:
        return 0.0
    if a in _DENSITY_ORDER and b in _DENSITY_ORDER:
        span = len(_DENSITY_ORDER) - 1
        return abs(_DENSITY_ORDER.index(a) - _DENSITY_ORDER.index(b)) / span
    return 1.0


def _section_count_distance(a: int, b: int) -> float:
    """``|a - b|`` scaled by the larger count, so a 1-vs-2 gap (doubling) and
    a 6-vs-12 gap (also doubling) score the same, rather than a fixed-width
    artifact type structurally always scoring closer than a wide one."""
    if a == b:
        return 0.0
    denominator = max(a, b, 1)
    return min(abs(a - b) / denominator, 1.0)


def distance(a: Fingerprint, b: Fingerprint) -> float:
    """Weighted structural distance between two fingerprints, in [0, 1].

    0.0 only when every field agrees (identical shape); 1.0 only when every
    field disagrees maximally. Symmetric, because every term it is built from
    is symmetric (edit distance, equality, ordinal and scaled absolute
    difference all commute).
    """
    return (
        _WEIGHT_COMPONENTS * _sequence_distance(a.components, b.components)
        + _WEIGHT_LAYOUTS * _sequence_distance(a.layouts, b.layouts)
        + _WEIGHT_STYLE * (0.0 if a.style_key == b.style_key else 1.0)
        + _WEIGHT_DENSITY * _density_distance(a.density_bucket, b.density_bucket)
        + _WEIGHT_SECTION_COUNT * _section_count_distance(a.section_count, b.section_count)
    )


#: n-gram width for the component-sequence entropy measure. 2 (adjacent
#: pairs) rather than 1 (bare component frequency): unigram entropy cannot
#: see the retail-close defect at all — "position, evidence, decision" and
#: "decision, position, evidence" have identical unigram counts and are
#: obviously not the same document. Bigrams are the smallest window that
#: sees adjacency, which is the thing "the same outline every time" actually
#: repeats.
_NGRAM_SIZE = 2


def _ngrams(components: tuple[str, ...], n: int) -> list[tuple[str, ...]]:
    """Sliding windows of *n* over *components*.

    A composition shorter than *n* still contributes something — its own
    (shorter) tuple, once — rather than vanishing from the entropy measure
    entirely, which would make a batch of two-component artifacts read as
    having no structure at all.
    """
    if len(components) >= n:
        return [tuple(components[i : i + n]) for i in range(len(components) - n + 1)]
    return [components] if components else []


def _family(component_id: str) -> str:
    """The component family a component id belongs to — the text before the
    first ``.``, e.g. ``"finance.variance_table"`` -> ``"finance"``. This is
    exactly the grouping `docs/artifact-compiler.md` §7's
    ``maximum_component_family_share`` quota means: not "how often does this
    *exact* component recur" but "how much of the batch leans on one family
    of components", which a single component id cannot answer on its own.
    """
    family, _, _ = component_id.partition(".")
    return family


def _entropy_bits(counts: Mapping[object, int]) -> float:
    """Shannon entropy, in bits, of the frequency distribution in *counts*.

    ``Mapping.values()`` rather than iterating keys — count order never
    affects the sum, so there is nothing here that depends on dict or set
    iteration order the way the ground rules warn about.
    """
    total = sum(counts.values())
    if total == 0:
        return 0.0
    bits = 0.0
    for count in counts.values():
        if count == 0:
            continue
        probability = count / total
        bits -= probability * math.log2(probability)
    return bits


#: The row labels `DiversityReport.__str__` prints, in order. Named rather than
#: inlined so the column width is computed from the labels that actually appear
#: — a hard-coded "longest one" is a thing to forget to update, and forgetting
#: it misaligns the whole block by however many characters the new row is wider.
_ROW_LABELS: tuple[str, ...] = (
    "n-gram entropy",
    "max family share",
    "largest shape group",
    "repeated shapes",
    "longest repetition run",
    "longest same-type run",
)


@dataclass(frozen=True)
class DiversityReport:
    """What a batch of fingerprints looks like, read as a whole.

    ``__str__`` is part of the API, not an afterthought — matches
    ``evaluate.score.Scorecard`` and ``world.Summary``: this is a report a
    person reads on a terminal, not a struct they unpack.
    """

    count: int
    distinct_digests: int
    """How many distinct shapes the batch holds. An **absolute count**, and on
    its own it is the wrong number to quote: it can only go up as a corpus
    grows, so a corpus that grew four times more repetitive reports a
    distinct-shape count at least as good as the small one it grew from. Read
    `unique_shape_ratio` beside it — that is the reading `check`'s own
    `Quotas.min_unique_ratio` is computed on, and until this report printed it,
    the summary omitted the very number its gate was failing the corpus for."""
    ngram_entropy_bits: float
    """Shannon entropy of the pooled component-sequence bigrams (see
    `_NGRAM_SIZE`), in bits. Low entropy means the same adjacent-component
    pairs keep recurring — the retail-close symptom — even when
    `distinct_digests` looks healthy, because entropy is sensitive to
    *proportion*, not merely to the presence of at least one different
    shape.

    Proportion is also precisely what it cannot see past. Entropy is a
    per-observation average, so a batch and the same batch stamped out four
    times have identical distributions and identical entropy — measured, not
    argued: this engine's retail corpus at 12 periods (85 artifacts) and at 48
    periods (340) both read **4.12 bits**, to the digit, while the worst
    repeated shape went from twelve copies to forty-eight. That is not a defect
    in the statistic; it is what an average is. It means this number answers
    "how varied is the shape *vocabulary*" and never "how often is the
    vocabulary reused", and the second question has to be asked of
    `largest_shape_group` and `longest_same_type_run` instead."""
    max_family_share: float
    """The largest fraction of all components (pooled across the batch)
    contributed by any one component family — see `_family`.

    Scale-invariant for the same reason as `ngram_entropy_bits`, and
    deliberately kept that way: this is the statistic that caught 78% of every
    composed component landing in `core`, which is a claim about the vocabulary
    mix and would be *ruined* by making it sensitive to how many times each
    shape is stamped. Same 12-vs-48-period corpora: 33% (`core`) both times."""
    max_family: str
    """Which family holds `max_family_share`. Empty string when the batch has
    no components at all."""
    longest_repetition_run: int
    """The longest run of consecutive *identical* digests, in the order
    fingerprints were supplied. Order-dependent by design: a batch is
    generated in some sequence, and a run of identical shapes back-to-back in
    that sequence is a different (worse) reader experience than the same
    shapes spread through the batch — `distinct_digests` alone cannot tell
    those apart.

    In practice this reads **1 forever** on anything this engine builds, and
    the reason is structural rather than fixable here: artifacts are emitted
    interleaved by type — a calendar, then a workbook, then a memo, then the
    next period's calendar — so two identical shapes are essentially never
    adjacent no matter how many copies of each exist. 85 artifacts: 1. 340
    artifacts, four times as many copies of every template: still 1.
    `longest_same_type_run` is the same measurement over the sequence a reader
    actually experiences, and is what `check` gates on."""
    longest_same_type_run: int
    """The longest run of identical digests among consecutive artifacts *of the
    same artifact_type* — the emission order with the other types filtered out.

    This is `longest_repetition_run`'s question asked of a sequence somebody
    reads. Nobody reads a corpus in emission order; they read all the CFO
    variance memos, or all the close calendars, and *that* is where twelve
    identical outlines in a row is the experience. On the corpora above it
    reads 12 and 48 where the interleaved run reads 1 and 1.

    Always ``>= longest_repetition_run``, provably and not by luck:
    `Fingerprint.digest` includes ``artifact_type``, so identical digests
    already imply identical types, and any run that is consecutive in emission
    order is therefore also consecutive within its own type's subsequence. That
    containment is what lets `check` move its ceiling onto this field without
    weakening the gate — nothing the old measure caught can slip past this
    one."""
    unique_shape_ratio: float
    """`distinct_digests` as a fraction of `count` — how much of the batch is a
    shape nothing else has.

    The scale-aware companion to `distinct_digests`, and the reading to quote
    when a corpus is large. On the two corpora above: 9/85 = **11%** and 9/340
    = **2.6%**. The absolute count says "9 distinct shapes" both times and
    invites the reading that nothing got worse; the ratio says the corpus
    quadrupled without acquiring a single new shape."""
    largest_shape_group: int
    """How many artifacts share the single most-repeated shape.

    The `stats.Stats.largest_near_duplicate_group` of structure, and it moves
    for the same reason that one does: it is an absolute count of *repetition*
    rather than of variety, so it grows precisely when the corpus gets worse.
    12 and 48 on the corpora above — the one headline figure that tracked what
    the detail section underneath the report had been saying all along."""
    repeated_shape_share: float
    """The fraction of artifacts whose shape at least one other artifact also
    has.

    Distinguishes the two ways a batch can hold few shapes: a corpus with one
    repeated template among many singletons, and a corpus that is nothing but
    templates. `unique_shape_ratio` cannot separate those — both can read 11% —
    and an author deciding whether to rewrite a template or the whole corpus
    needs to know which one they have."""
    distinct_shapes_by_type: Mapping[str, int]
    """``{artifact_type: distinct digest count}``, in the order each
    artifact_type first appears in the input — a scan order, not an
    alphabetical resort, so the report reads next to the batch it summarises."""

    def __str__(self) -> str:
        width = max((len(t) for t in self.distinct_shapes_by_type), default=0)
        # Over the row labels themselves rather than one hard-coded longest, so
        # adding a row can never silently break the column the way it did when
        # "longest same-type run" was assumed to be the widest and "longest
        # repetition run" is one character longer.
        width = max(width, *(len(label) for label in _ROW_LABELS))
        bar = "█" * round(10 * self.max_family_share)
        lines = [
            f"Diversity — {self.count} artifact(s), {self.distinct_digests} distinct shape(s)"
            # In the headline, immediately after the count it qualifies. A
            # reader who takes only the first line away has to take the ratio
            # with it, because the count alone is the misleading half.
            f" ({self.unique_shape_ratio:.0%} unique)",
            "─" * (width + 24),
            f"  {_ROW_LABELS[0].ljust(width)}  {self.ngram_entropy_bits:.2f} bits",
            f"  {_ROW_LABELS[1].ljust(width)}  {self.max_family_share:.0%} ({self.max_family or '—'}) {bar}",
            # The three duplication-sensitive rows, kept together and printed
            # even when they read zero: a row that appears only when a corpus is
            # bad teaches a reader to skim past its absence.
            f"  {_ROW_LABELS[2].ljust(width)}  {self.largest_shape_group}",
            f"  {_ROW_LABELS[3].ljust(width)}  {self.repeated_shape_share:.0%} of artifacts",
            # Both runs, on their own lines, always — the shape
            # `stats.Stats.__str__` settled on for the near-duplicate rate and
            # its share. The two disagree on every corpus this engine builds (1
            # against 48 on a 48-period retail history) and a reader has to see
            # both to notice that the first one is measuring emission order
            # rather than anything they would read. Folding them into one line
            # would make the disagreement look like an annotation on a single
            # figure instead of two different measurements.
            f"  {_ROW_LABELS[4].ljust(width)}  {self.longest_repetition_run}",
            f"  {_ROW_LABELS[5].ljust(width)}  {self.longest_same_type_run}",
        ]
        if self.distinct_shapes_by_type:
            lines.append("─" * (width + 24))
            for artifact_type, distinct in self.distinct_shapes_by_type.items():
                lines.append(f"  {artifact_type.ljust(width)}  {distinct} distinct shape(s)")
        return "\n".join(lines)

    def __repr__(self) -> str:
        return str(self)


def report(fingerprints: Sequence[Fingerprint]) -> DiversityReport:
    """Summarise a batch of fingerprints.

    Walks *fingerprints* once, in the order given — never through a ``set`` —
    so `longest_repetition_run` and `distinct_shapes_by_type` (both order-
    sensitive) answer the same way every time for the same input sequence.
    """
    digests = [fp.digest() for fp in fingerprints]
    distinct_digests = len(set(digests))

    gram_counts: Counter[tuple[str, ...]] = Counter()
    family_counts: Counter[str] = Counter()
    for fp in fingerprints:
        gram_counts.update(_ngrams(fp.components, _NGRAM_SIZE))
        for component_id in fp.components:
            family_counts[_family(component_id)] += 1

    total_components = sum(family_counts.values())
    if total_components:
        # `Counter.most_common` breaks ties by insertion order, which for a
        # `Counter` built by iterating a batch is really "which artifact
        # happened to introduce this family first" — not a property this
        # report may depend on. Sort explicitly: highest share first, family
        # name breaks a tie, so the winner is the same regardless of how the
        # batch was ordered going in.
        max_family, max_family_count = sorted(
            family_counts.items(), key=lambda item: (-item[1], item[0])
        )[0]
        max_family_share = max_family_count / total_components
    else:
        max_family, max_family_share = "", 0.0

    longest_run = 0
    current_run = 0
    previous_digest: str | None = None
    for digest in digests:
        current_run = current_run + 1 if digest == previous_digest else 1
        longest_run = max(longest_run, current_run)
        previous_digest = digest

    # The same run, per artifact type — the sequence a reader experiences, since
    # nobody reads a corpus in emission order. One pass, carrying a
    # (last digest, current run) pair per type, rather than partitioning the
    # batch into per-type lists and re-walking each: the partition would be a
    # second full copy of the batch to compute a number the first walk already
    # has all the information for. See `DiversityReport.longest_same_type_run`
    # for why this is the field `check` gates on.
    longest_same_type_run = 0
    run_state: dict[str, tuple[str, int]] = {}
    for fp, digest in zip(fingerprints, digests):
        previous, run = run_state.get(fp.artifact_type, ("", 0))
        run = run + 1 if digest == previous else 1
        run_state[fp.artifact_type] = (digest, run)
        longest_same_type_run = max(longest_same_type_run, run)

    # First-appearance order, not `sorted(set(...))`: a `set` of artifact
    # types would iterate in an order this module has no business relying on,
    # and a report is read next to the batch it came from — the scan order a
    # person would notice types in while reading down the list.
    shapes_by_type: dict[str, set[str]] = {}
    for fp, digest in zip(fingerprints, digests):
        shapes_by_type.setdefault(fp.artifact_type, set()).add(digest)
    distinct_shapes_by_type = {
        artifact_type: len(digest_set) for artifact_type, digest_set in shapes_by_type.items()
    }

    # Counted off `digests` rather than by calling `collisions()`, which walks
    # the batch again and re-derives every digest to answer half of the same
    # question. `Counter` sums are order-independent, so nothing here depends on
    # how the dict iterates.
    digest_counts = Counter(digests)
    largest_shape_group = max(digest_counts.values(), default=0)
    repeated = sum(count for count in digest_counts.values() if count > 1)

    return DiversityReport(
        count=len(fingerprints),
        distinct_digests=distinct_digests,
        ngram_entropy_bits=_entropy_bits(gram_counts),
        max_family_share=max_family_share,
        max_family=max_family,
        longest_repetition_run=longest_run,
        longest_same_type_run=longest_same_type_run,
        unique_shape_ratio=(distinct_digests / len(fingerprints)) if fingerprints else 0.0,
        # Zero rather than one on an empty batch: "the worst shape is repeated
        # once" would be a claim about a shape that is not there. Same stance
        # `check` takes toward an empty batch meeting every quota.
        largest_shape_group=largest_shape_group if fingerprints else 0,
        repeated_shape_share=(repeated / len(fingerprints)) if fingerprints else 0.0,
        distinct_shapes_by_type=distinct_shapes_by_type,
    )


# ---------------------------------------------------------------------------
# 3. Quota checking
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Quotas:
    """Batch-level diversity thresholds, declared rather than hard-coded —
    the same relationship `Grammar` has to `Grammar.check`. Defaults are the
    numbers `docs/artifact-compiler.md` §7 gives for
    ``minimum_unique_layout_ratio``, ``maximum_component_family_share`` and
    ``maximum_repeated_layout_run``, plus an entropy floor of the same kind
    the module's own `_entropy_bits` measure needs to be checkable against
    something.
    """

    min_unique_ratio: float = 0.35
    max_single_family_share: float = 0.20
    max_repetition_run: int = 2
    min_entropy_bits: float = 2.2


@dataclass(frozen=True)
class QuotaViolation:
    """One way a batch fails its `Quotas` — mirrors `grammar.GrammarViolation`
    field for field, including the ``__str__`` shape, since a caller reading
    both kinds of violation in one place should not have to learn two
    formats for "here is what went wrong and by how much"."""

    code: str
    detail: str

    def __str__(self) -> str:
        return f"[{self.code}] {self.detail}"


_DEFAULT_QUOTAS = Quotas()


def check(fingerprints: Sequence[Fingerprint], quotas: Quotas = _DEFAULT_QUOTAS) -> list[QuotaViolation]:
    """Every way *fingerprints* fails *quotas*. Never raises — mirrors
    `grammar.check`: a caller wants every violation at once, not the first
    one a `raise` happened to reach.

    An empty batch trivially meets every quota rather than dividing by zero
    to find out: there is nothing to be repetitive or concentrated yet, the
    same stance `grammar.check` takes toward an artifact type with no
    grammar entry — absence of data is not itself a violation.
    """
    if not fingerprints:
        return []

    batch = report(fingerprints)
    violations: list[QuotaViolation] = []

    unique_ratio = batch.distinct_digests / batch.count
    if unique_ratio < quotas.min_unique_ratio:
        violations.append(QuotaViolation(
            "unique_ratio_below_quota",
            f"{batch.distinct_digests}/{batch.count} distinct shapes = {unique_ratio:.0%},"
            f" below the {quotas.min_unique_ratio:.0%} floor",
        ))

    if batch.max_family_share > quotas.max_single_family_share:
        violations.append(QuotaViolation(
            "family_share_above_quota",
            f"{batch.max_family!r} holds {batch.max_family_share:.0%} of all components,"
            f" above the {quotas.max_single_family_share:.0%} ceiling",
        ))

    # Gated on the same-type run, not the interleaved one. The interleaved
    # measure reads 1 on every corpus this engine can build — artifacts are
    # emitted a calendar, a workbook, a memo, then the next period's calendar,
    # so two identical shapes are never adjacent — which made this quota
    # unfireable on real output and left a ceiling of 2 looking like a live
    # gate. The move cannot weaken the check: `Fingerprint.digest` carries
    # `artifact_type`, so an interleaved run is always also a same-type run and
    # `longest_same_type_run >= longest_repetition_run` for every batch. See
    # `DiversityReport.longest_same_type_run`.
    if batch.longest_same_type_run > quotas.max_repetition_run:
        violations.append(QuotaViolation(
            "repetition_run_above_quota",
            f"{batch.longest_same_type_run} consecutive artifacts of one type share an"
            f" identical shape, above the {quotas.max_repetition_run} ceiling",
        ))

    if batch.ngram_entropy_bits < quotas.min_entropy_bits:
        violations.append(QuotaViolation(
            "entropy_below_quota",
            f"component-sequence entropy is {batch.ngram_entropy_bits:.2f} bits,"
            f" below the {quotas.min_entropy_bits:.2f}-bit floor",
        ))

    return violations


# ---------------------------------------------------------------------------
# 4. Max-min candidate selection
# ---------------------------------------------------------------------------


def select(candidates: Sequence[Fingerprint], *, k: int, seed: int) -> tuple[int, ...]:
    """Greedy max-min: pick *k* of *candidates* that are maximally spread out.

    Per §12, *candidates* are the small set of structural alternatives for
    *one* artifact (component assignment x layout x style genome — the
    example in the spec is 12). This is furthest-point sampling over that
    set: the first pick is index 0 (see below), and each subsequent pick is
    whichever remaining candidate has the greatest *minimum* distance to
    every candidate already chosen — "furthest from what is already in the
    batch" where "the batch" is the selection being built by this very call.
    Greedy, not an exact max-min solver: §14.E is explicit that OR-Tools does
    not belong here until a recorded fixture proves greedy insufficient, and
    for picking a handful of candidates per artifact — not solving a global
    assignment — greedy dispersion is the textbook-correct answer already.

    Ties always break toward the lowest index, checked by iterating
    ``range(n)`` ascending and only replacing the current best on a *strict*
    improvement — so the result depends on nothing but the input order the
    caller already committed to.

    ``seed`` is accepted for interface parity with the rest of the compiler
    (`compose.compose` takes an `Rng` for the identical reason) but unused:
    every choice here is already fully determined by distances and index
    order, so there is no genuine tie left for a seed to break. If a future
    distance change ever produces a real tie between equally-distant
    candidates at the same index gap, derive an `Rng` from *seed* by name
    rather than reaching for `random` — same rule as everywhere else in this
    project.

    Returns indices into *candidates*, in selection order, so the caller
    (who owns the actual candidate objects — plans, renders, whatever a
    `Fingerprint` here stands in for) decides what to do with them.

    The traversal itself lives in ``worldloom.dispersion``. It was lifted out
    unchanged — same first pick, same strict-improvement tie-break — when
    ``probe.worlds`` needed the identical algorithm over a completely different
    thing: whole consistent worlds rather than document shapes. Two copies of
    "as unlike each other as possible" is two things that can disagree about
    it, which on a project whose central claim is *measured* diversity is a
    particularly bad place to keep a fork. What stays here is this module's own
    judgement — the `distance` a document shape is measured by.
    """
    from ..dispersion import farthest_first

    return farthest_first(candidates, distance, k)

def collisions(fingerprints: Sequence[Fingerprint]) -> tuple[tuple[str, tuple[int, ...]], ...]:
    """Shapes used by more than one artifact, and which artifacts used them.

    ``report()`` counts distinct shapes; this names the repeats. The
    difference is what an author can act on: "120 artifacts, 11 shapes" is a
    number, and "these fourteen close packs are one shape" is a document to go
    and look at. Ordered largest group first, then by digest, so ``--json`` is
    diffable.
    """
    grouped: dict[str, list[int]] = {}
    for index, fp in enumerate(fingerprints):
        grouped.setdefault(fp.digest(), []).append(index)
    return tuple(sorted(
        ((digest, tuple(members)) for digest, members in grouped.items() if len(members) > 1),
        key=lambda row: (-len(row[1]), row[0]),
    ))


def assign(
    candidates: Sequence[Sequence[Fingerprint]],
    *,
    committed: Sequence[Fingerprint] = (),
) -> tuple[int, ...]:
    """One shape per artifact, chosen so the *batch* spreads out.

    ``select`` and this are the two halves of the same problem and neither
    substitutes for the other. ``select`` works inside one artifact: given the
    dozen structural alternatives that artifact could take, pick the *k* most
    unlike each other. That is the right tool for offering a model a varied
    menu, and it has nothing to say about the batch — run it independently for
    a hundred artifacts of the same type and it will happily hand every one of
    them the same first pick, because index 0 is index 0 every time.

    Which is precisely the measured defect build-order §7a.1 records: a
    12-period corpus of 120 artifacts carrying **11 distinct section shapes**,
    with DOCX sizes across 72 files spanning 38,658–40,618 bytes. Every close
    pack in the estate is the same document with different numbers, and no
    amount of per-artifact selection fixes it, because per-artifact selection
    is what produced it.

    So this greedily assigns across the batch: artifacts are taken in the
    order given, and each one gets whichever of *its own* candidates is
    furthest from every shape already committed — the shapes chosen by earlier
    artifacts in this call, plus any *committed* shapes an earlier batch
    already spent (a corpus built one period at a time must not restart the
    dispersion at every period, or period two reproduces period one exactly).

    Greedy, and honestly so. The exact problem — maximise the minimum pairwise
    distance over a product of per-artifact candidate sets — is max-min
    dispersion with assignment constraints and is NP-hard; §14.E is explicit
    that a solver does not belong here until a recorded fixture proves greedy
    insufficient. What greedy guarantees is the thing that was actually
    missing: no artifact takes a shape identical to one already in the batch
    while a different one is available to it.

    Ties break toward the lowest candidate index, by strict-improvement
    comparison, exactly as ``select`` does.

    Returns one index per artifact, into that artifact's own candidate list.
    An artifact with no candidates raises rather than silently taking a
    default — an empty candidate set means the caller's shape vocabulary is
    broken, and a quiet fallback would hide it behind exactly the monotony
    this function exists to break.
    """
    for position, options in enumerate(candidates):
        if not options:
            raise ValueError(f"artifact {position} has no candidate shapes to assign")

    spent: list[Fingerprint] = list(committed)
    chosen: list[int] = []
    for options in candidates:
        best_index = 0
        best_score = -1.0
        for index, option in enumerate(options):
            # Distance to the nearest already-spent shape — the same
            # "furthest from what is already in the batch" rule `select`
            # applies within one artifact, with the batch standing in for the
            # selection being built.
            score = min((distance(option, other) for other in spent), default=float("inf"))
            if score > best_score:
                best_score, best_index = score, index
            if best_score == float("inf"):
                # Nothing spent yet: every candidate is equally unconstrained,
                # so the lowest index wins and there is nothing to compare.
                break
        chosen.append(best_index)
        spent.append(options[best_index])
    return tuple(chosen)


# ---------------------------------------------------------------------------
# 4. Across corpora
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CrossReport:
    """How much of a fleet is the same corpus wearing different names.

    The within-corpus report above cannot see this failure: five companies can
    each score a respectable unique-shape ratio while every one of them holds
    the *same* shapes — a mosaic whose whole point was contrast, byte-shuffled
    into five copies of one company. Measured here as it was first noticed:
    thirty-one benchmark questions asked byte-identically across five mosaic
    worlds, which no single corpus's report could have flagged.

    Shape-level only, deliberately. Prose-level overlap is a different failure
    with a different tool (`stats.near_duplicate_clusters` over a pooled
    passage list — the CLI composes the two); conflating them here would
    repeat the exact structural-versus-prose confusion `--near-duplicates`'s
    help text warns about.
    """

    corpora: tuple[str, ...]
    """Names in the order given — pair keys below preserve it."""

    counts: Mapping[str, int]
    """Artifacts fingerprinted per corpus — the denominators."""

    shared_shapes: int
    """Distinct digests that appear in two or more corpora."""

    shared_share: Mapping[str, float]
    """Per corpus: the fraction of its artifacts standing on a shape some
    *other* corpus also has. The number to watch — a corpus at 0.9 here is
    structurally nine-tenths reproducible from its neighbours."""

    pair_overlap: Mapping[tuple[str, str], float]
    """Jaccard similarity of digest *sets* per corpus pair: 1.0 is the same
    shape vocabulary, 0.0 is none in common. Over sets rather than artifact
    counts so a corpus that repeats a shared shape many times internally
    (its own report's business) does not double-count as fleet overlap."""

    def __str__(self) -> str:
        lines = [
            f"Across {len(self.corpora)} corpora — "
            f"{self.shared_shapes} shape(s) shared by two or more",
        ]
        for name in self.corpora:
            lines.append(
                f"  {name:<24} {self.counts[name]:>5} artifact(s), "
                f"{self.shared_share[name]:>4.0%} on shared shapes"
            )
        for (a, b), jaccard in self.pair_overlap.items():
            lines.append(f"  {a} × {b}: {jaccard:.0%} shape vocabulary in common")
        return "\n".join(lines)


def cross_report(batches: Mapping[str, Sequence[Fingerprint]]) -> CrossReport:
    """Summarise shape overlap across several corpora's fingerprint batches.

    Iterates *batches* in the order given and nothing else — the same
    no-``set``-iteration discipline as `report`, because this output lands in
    CI logs where two runs must diff clean.
    """
    names = tuple(batches)
    digest_sets: dict[str, set[str]] = {
        name: {fp.digest() for fp in fingerprints} for name, fingerprints in batches.items()
    }
    appearance: Counter[str] = Counter()
    for name in names:
        appearance.update(digest_sets[name])
    shared = {digest for digest, corpora in appearance.items() if corpora > 1}

    shared_share = {}
    for name in names:
        fingerprints = batches[name]
        on_shared = sum(1 for fp in fingerprints if fp.digest() in shared)
        shared_share[name] = (on_shared / len(fingerprints)) if fingerprints else 0.0

    pair_overlap = {}
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            union = digest_sets[a] | digest_sets[b]
            pair_overlap[(a, b)] = (
                len(digest_sets[a] & digest_sets[b]) / len(union) if union else 0.0
            )

    return CrossReport(
        corpora=names,
        counts={name: len(batches[name]) for name in names},
        shared_shapes=len(shared),
        shared_share=shared_share,
        pair_overlap=pair_overlap,
    )


__all__ = [
    "CrossReport",
    "DiversityReport",
    "Fingerprint",
    "QuotaViolation",
    "Quotas",
    "assign",
    "check",
    "collisions",
    "cross_report",
    "distance",
    "fingerprint",
    "report",
    "select",
]
