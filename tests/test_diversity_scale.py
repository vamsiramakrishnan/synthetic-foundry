"""`worldloom diversity`'s headline numbers, and which of them can see a corpus grow.

Every figure the report led with was **scale-invariant**, which on a diversity
report is not a neutral property — it is the report failing at the size where
diversity is most at risk. Measured on this engine's own retail corpus, growing
the history from 12 periods to 48 (85 artifacts to 340, four times as many copies
of every template):

    artifacts   distinct shapes   n-gram entropy   max family share   run
           85                 9        4.12 bits          33% core     1
          340                 9        4.12 bits          33% core     1

Not one digit moved. Meanwhile the most-repeated shape went from twelve copies
to forty-eight, which the detail section under the report had been printing all
along.

Each figure is blind for its own reason and this file pins each one separately,
because "the numbers did not move" is a symptom with four causes:

* `distinct_digests` is an **absolute count**, never divided by `count`, so it
  can only ever go up.
* `ngram_entropy_bits` and `max_family_share` are **per-observation averages
  over a pooled distribution** — a batch and the same batch stamped out four
  times have identical distributions. That is what an average is, and it is why
  the fix is a companion reading rather than a repair.
* `longest_repetition_run` counts *consecutive* identical digests and artifacts
  are emitted interleaved by type, so it reads 1 forever.

`stats.py` was given duplication-sensitive statistics for exactly this reason
one commit earlier, and the same shape is used here: the blind statistics stay
(they answer a real question about the shape *vocabulary*), and companions that
move are added off the same walk.
"""

from __future__ import annotations

import pytest

from worldloom.compiler.diversity import (
    Fingerprint,
    Quotas,
    check,
    report,
)


def _fp(artifact_type: str, components: tuple[str, ...]) -> Fingerprint:
    return Fingerprint(
        artifact_type=artifact_type,
        components=components,
        layouts=(),
        style_key="",
        density_bucket="balanced",
        section_count=len(components),
    )


def _batch(*, templates: int, copies: int, interleave: bool) -> list[Fingerprint]:
    """*templates* distinct shapes, each stamped *copies* times.

    ``interleave`` chooses the emission order: interleaved is what this engine
    actually produces (a calendar, a workbook, a memo, then the next period's
    calendar), grouped is what a reader experiences when they open all the
    documents of one type. Every headline figure but the run measures is
    identical between the two orders, which is the point of having the flag.
    """
    shapes = [
        _fp(f"type{t}", tuple(f"core.c{t}_{i}" for i in range(3)))
        for t in range(templates)
    ]
    if interleave:
        return [shapes[t] for _ in range(copies) for t in range(templates)]
    return [shapes[t] for t in range(templates) for _ in range(copies)]


# ---------------------------------------------------------------------------
# 1. What each blind statistic is blind to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("copies", [1, 2, 4, 8, 48])
def test_entropy_and_family_share_cannot_see_how_often_a_shape_is_stamped(
    copies: int,
) -> None:
    """Stated as an exact equality across a 48× range, not as an inequality.

    These are averages over a pooled distribution, so duplicating the whole
    batch leaves the distribution — and therefore the number — *identical*.
    Asserting `>=` or a tolerance would let a partial fix look like a fix; the
    equality is what makes the companion readings necessary rather than
    optional.
    """
    one = report(_batch(templates=4, copies=1, interleave=True))
    many = report(_batch(templates=4, copies=copies, interleave=True))
    assert many.ngram_entropy_bits == one.ngram_entropy_bits
    assert many.max_family_share == one.max_family_share
    assert many.max_family == one.max_family
    # And the absolute shape count, which is the headline the report leads with.
    assert many.distinct_digests == one.distinct_digests


def test_the_interleaved_run_reads_one_however_repetitive_the_batch_is() -> None:
    """The measure that is dead by construction on this engine's output. Forty
    eight copies of four templates, emitted the way the engine emits them: no
    two identical shapes are ever adjacent, so the run is 1 and the ceiling of 2
    it is checked against can never fire."""
    batch = report(_batch(templates=4, copies=48, interleave=True))
    assert batch.longest_repetition_run == 1
    assert batch.count == 192


# ---------------------------------------------------------------------------
# 2. What the companions do instead
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("copies", [1, 2, 4, 8, 48])
def test_the_companion_readings_move_when_the_pooled_ones_do_not(copies: int) -> None:
    templates = 4
    batch = report(_batch(templates=templates, copies=copies, interleave=True))
    assert batch.largest_shape_group == copies
    assert batch.unique_shape_ratio == pytest.approx(templates / (templates * copies))
    assert batch.longest_same_type_run == copies
    assert batch.repeated_shape_share == (0.0 if copies == 1 else 1.0)


def test_the_unique_ratio_falls_as_a_corpus_grows_without_new_shapes() -> None:
    """The single reading that most directly contradicts the old headline.
    Four times the artifacts, the same nine shapes: the count says "9 distinct
    shapes" both times, the ratio says the corpus quadrupled without acquiring
    one."""
    small = report(_batch(templates=9, copies=4, interleave=True))
    large = report(_batch(templates=9, copies=16, interleave=True))
    assert small.distinct_digests == large.distinct_digests == 9
    assert large.unique_shape_ratio < small.unique_shape_ratio


def test_the_same_type_run_sees_what_the_interleaved_run_cannot() -> None:
    batch = report(_batch(templates=4, copies=48, interleave=True))
    assert batch.longest_repetition_run == 1
    assert batch.longest_same_type_run == 48


@pytest.mark.parametrize("interleave", [True, False])
def test_the_same_type_run_dominates_the_interleaved_one(interleave: bool) -> None:
    """The containment argument `check` relies on, asserted rather than trusted.

    `Fingerprint.digest` carries `artifact_type`, so identical digests already
    imply identical types and any run consecutive in emission order is also
    consecutive within its own type's subsequence. That is what lets the quota
    move onto the same-type run without weakening it — nothing the old measure
    caught can slip past the new one.
    """
    batch = report(_batch(templates=3, copies=7, interleave=interleave))
    assert batch.longest_same_type_run >= batch.longest_repetition_run


def test_repeated_share_separates_one_bad_template_from_an_all_template_corpus() -> None:
    """`unique_shape_ratio` cannot tell these apart and an author acting on the
    report needs to: one says rewrite a template, the other says rewrite the
    corpus."""
    singletons = [_fp("memo", (f"core.c{i}",)) for i in range(8)]
    one_repeat = report(singletons + [singletons[0], singletons[0]])
    all_repeats = report([fp for fp in singletons[:2] for _ in range(5)])

    assert one_repeat.repeated_shape_share == pytest.approx(3 / 10)
    assert all_repeats.repeated_shape_share == 1.0


# ---------------------------------------------------------------------------
# 3. Edges, and the gate
# ---------------------------------------------------------------------------


def test_an_empty_batch_reports_zeroes_rather_than_dividing_by_zero() -> None:
    """"The worst shape is repeated once" would be a claim about a shape that is
    not there — the same stance `check` takes toward an empty batch trivially
    meeting every quota."""
    batch = report([])
    assert batch.count == 0
    assert batch.unique_shape_ratio == 0.0
    assert batch.largest_shape_group == 0
    assert batch.repeated_shape_share == 0.0
    assert batch.longest_same_type_run == 0


def test_a_batch_of_one_is_wholly_unique_and_repeats_nothing() -> None:
    batch = report([_fp("memo", ("core.position",))])
    assert batch.unique_shape_ratio == 1.0
    assert batch.largest_shape_group == 1
    assert batch.repeated_shape_share == 0.0


def test_the_repetition_quota_now_fires_on_an_interleaved_batch() -> None:
    """The behaviour change in `check`, and the reason for it. A ceiling of 2
    against a measure that reads 1 on all real output was a gate that could not
    fail — worse than no gate, because it read as one."""
    batch = _batch(templates=4, copies=48, interleave=True)
    codes = {v.code for v in check(batch, Quotas())}
    assert "repetition_run_above_quota" in codes


def test_a_batch_below_the_ceiling_still_clears_it() -> None:
    """The other half: a quota that fires on everything is as uninformative as
    one that fires on nothing."""
    batch = _batch(templates=8, copies=2, interleave=True)
    codes = {v.code for v in check(batch, Quotas(min_unique_ratio=0.0, max_single_family_share=1.0, min_entropy_bits=0.0))}
    assert "repetition_run_above_quota" not in codes


def test_the_headline_line_carries_the_ratio_beside_the_count() -> None:
    """A reader who takes only the first line away has to take the qualifier
    with them, because the count alone is the misleading half."""
    text = str(report(_batch(templates=9, copies=16, interleave=True)))
    first = text.splitlines()[0]
    assert "144 artifact(s)" in first
    assert "9 distinct shape(s)" in first
    assert "6% unique" in first


def test_the_printed_report_carries_both_runs_on_their_own_lines() -> None:
    """The shape `stats.Stats.__str__` settled on for the same problem: the two
    disagree on every corpus this engine builds, and a reader has to see both to
    notice that the first is measuring emission order rather than anything they
    would read.

    Also asserts the absence of square brackets. `cli.py` prints this through
    Rich, which reads ``[...]`` as a style tag — an earlier draft folded the
    second run into the first line as ``[1 interleaved]`` and the annotation
    vanished from the terminal while passing every string test that checked the
    object. A report whose text disappears depending on who prints it is worse
    than one that never had the text.
    """
    text = str(report(_batch(templates=4, copies=48, interleave=True)))
    rows = {line.split("  ")[1].strip(): line.rsplit("  ", 1)[1].strip()
            for line in text.splitlines() if line.startswith("  ") and "  " in line.strip()}
    assert rows["longest repetition run"] == "1"
    assert rows["longest same-type run"] == "48"
    assert "[" not in text
