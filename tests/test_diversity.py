"""Tests for `worldloom.compiler.diversity`.

Fingerprints and distances are hand-built here the same way `test_lifetimes.py`
hand-builds validator violations and `test_compiler.py` hand-builds plans: a
check only proves it fires by constructing the exact case it exists for. The
one exception is the regression fixture at the bottom, which deliberately uses
a real generated world — the point of that test is to pin the shape of the
*actual* corpus, not a shape this file invented to be convenient.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

from worldloom import MonthEndClose, RetailWorld
from worldloom.compiler.compose import Composition, compose, plan_from_ir
from worldloom.compiler.diversity import (
    DiversityReport,
    Fingerprint,
    Quotas,
    _density_bucket,  # test-only, same idiom test_compiler.py uses for _OUTLINES/_DEFAULT_OUTLINE
    check,
    distance,
    fingerprint,
    report,
    select,
)
from worldloom.render.docx import HANDLES as DOCX_ARTIFACT_TYPES
from worldloom.render.xlsx import HANDLES as XLSX_ARTIFACT_TYPES


def _composition(
    *,
    artifact_type: str = "cfo_variance_memo",
    fmt: str = "markdown",
    components: tuple[str, ...] = ("core.position", "finance.variance_table"),
    beats: tuple[str, ...] | None = None,
) -> Composition:
    """A `Composition` built directly rather than through `compose()` — this
    file is testing `diversity.py`'s reading of the dataclass, not the
    composer, so there is no reason to route through it (`test_compiler.py`
    already covers `compose()` itself)."""
    beats = beats if beats is not None else components
    return Composition(
        artifact_type=artifact_type,
        fmt=fmt,
        components=components,
        beats=beats,
        dropped=(),
        violations=(),
    )


def _fp(
    components: tuple[str, ...],
    *,
    artifact_type: str = "cfo_variance_memo",
    layouts: tuple[str, ...] = (),
    style_key: str = "",
) -> Fingerprint:
    """A `Fingerprint` with `density_bucket`/`section_count` derived the same
    way `fingerprint()` derives them, so a hand-built fixture never drifts
    from what the real function would have produced for the same components.
    """
    return Fingerprint(
        artifact_type=artifact_type,
        components=tuple(components),
        layouts=tuple(layouts),
        style_key=style_key,
        density_bucket=_density_bucket(len(components)),
        section_count=len(components),
    )


# ---------------------------------------------------------------------------
# 1. Fingerprint digest is stable across processes
# ---------------------------------------------------------------------------


def test_digest_is_stable_across_processes() -> None:
    """The test that protects replay: `Fingerprint.digest()` must agree
    between two cold interpreters, the same proof `test_pdf.py` requires of
    rendering. If this ever depended on `hash()` or dict/set iteration order,
    it would still very likely agree *within* one process and only disagree
    across a fresh one — which is exactly why an in-process comparison alone
    would not catch it.
    """
    script = textwrap.dedent(
        """
        import sys
        from worldloom.compiler import ArtifactPlan, EvidenceRef, NarrativeBeat
        from worldloom.compiler.compose import compose
        from worldloom.compiler.diversity import fingerprint

        plan = ArtifactPlan(
            intent_id="ART-TEST-0001",
            artifact_type="cfo_variance_memo",
            audience="group_cfo",
            intent="explain_performance_and_request_decisions",
            beats=[
                NarrativeBeat(
                    key="position", purpose="p",
                    evidence=[EvidenceRef(fact_id="FACT-0001", role="headline")],
                    semantic_role="position",
                ),
                NarrativeBeat(
                    key="evidence", purpose="e",
                    evidence=[
                        EvidenceRef(fact_id="FACT-0002", role="driver"),
                        EvidenceRef(fact_id="FACT-0003", role="driver"),
                    ],
                    semantic_role="evidence",
                ),
            ],
        )
        composition = compose(plan, fmt="markdown")
        fp = fingerprint(composition, style_key="finance_compact", layouts=("single_column", "table_wide"))
        sys.stdout.write(fp.digest())
        """
    )
    first = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True, text=True)
    second = subprocess.run([sys.executable, "-c", script], capture_output=True, check=True, text=True)
    assert first.stdout, "subprocess produced no digest"
    assert first.stdout == second.stdout


# ---------------------------------------------------------------------------
# 2. Digest reflects composition identity
# ---------------------------------------------------------------------------


def test_identical_compositions_produce_identical_digests() -> None:
    a = fingerprint(_composition(), style_key="editorial_neutral", layouts=("a", "b"))
    b = fingerprint(_composition(), style_key="editorial_neutral", layouts=("a", "b"))
    assert a.digest() == b.digest()


def test_a_changed_component_sequence_changes_the_digest() -> None:
    same_components = fingerprint(_composition(components=("core.position", "finance.variance_table")))
    reordered = fingerprint(_composition(components=("finance.variance_table", "core.position")))
    different = fingerprint(_composition(components=("core.position", "mgmt.decision_panel")))

    assert same_components.digest() != reordered.digest(), "order is part of the shape"
    assert same_components.digest() != different.digest()


def test_layouts_and_style_key_reach_the_digest_even_though_composition_never_carries_them() -> None:
    """`layouts` and `style_key` are supplied by the caller, not read off
    `Composition` (see `fingerprint`'s own docstring for why) — this pins
    that they still affect the digest rather than being silently dropped.
    """
    base = fingerprint(_composition(), style_key="finance_compact", layouts=("a",))
    other_layout = fingerprint(_composition(), style_key="finance_compact", layouts=("b",))
    other_style = fingerprint(_composition(), style_key="executive_sparse", layouts=("a",))

    assert base.digest() != other_layout.digest()
    assert base.digest() != other_style.digest()


# ---------------------------------------------------------------------------
# 3. distance()
# ---------------------------------------------------------------------------


def test_distance_is_zero_for_identical_fingerprints() -> None:
    fp = _fp(("core.position", "finance.variance_table", "mgmt.decision_panel"), layouts=("a", "b", "c"), style_key="finance_compact")
    assert distance(fp, fp) == 0.0


@pytest.mark.parametrize(
    "a,b",
    [
        (_fp(("core.position",)), _fp(("core.position", "finance.variance_table"))),
        (_fp(("core.position", "finance.variance_table")), _fp(("mgmt.decision_panel", "ops.causal_chain"))),
        (_fp((), artifact_type="x"), _fp(("core.position",), artifact_type="x")),
        (_fp(("a", "b", "c"), layouts=("x",)), _fp(("a", "b", "c"), layouts=("y", "z"))),
    ],
)
def test_distance_is_symmetric_and_bounded(a: Fingerprint, b: Fingerprint) -> None:
    forward = distance(a, b)
    backward = distance(b, a)
    assert forward == backward
    assert 0.0 <= forward <= 1.0


def test_distance_weighs_a_differing_component_sequence_above_a_differing_density_bucket() -> None:
    """Justifies the weight ordering documented on `_WEIGHT_COMPONENTS`: two
    fingerprints that disagree only on `components` must end up further
    apart than two that disagree only on `density_bucket`, holding
    everything else equal.
    """
    base = _fp(("core.position", "finance.variance_table"))
    # Same shape, forced into a different density bucket by hand — nothing
    # about the components changed.
    density_only = Fingerprint(
        artifact_type=base.artifact_type,
        components=base.components,
        layouts=base.layouts,
        style_key=base.style_key,
        density_bucket="dense",
        section_count=base.section_count,
    )
    assert base.density_bucket == "sparse"
    component_only = _fp(("mgmt.decision_panel", "ops.causal_chain"))

    assert distance(base, component_only) > distance(base, density_only)


def test_distance_is_maximal_when_every_term_disagrees() -> None:
    """Pushes all five blended terms (`components`, `layouts`, `style_key`,
    `density_bucket`, `section_count`) to their own maximum disagreement at
    once, so the weighted sum reaches exactly 1.0 — proof the blend really
    sums to the full weight budget rather than merely staying under it.

    `artifact_type` is deliberately not one of the blended terms: two
    fingerprints of different artifact types already diverge completely on
    `components` in every real case (the grammars in `grammar.py` guarantee
    unrelated component vocabularies per type), so a further categorical
    term would only ever restate a difference `components` already carries
    at full weight — see `_WEIGHT_COMPONENTS` and friends for the rest of
    the ranking.
    """
    sparse_empty = _fp((), layouts=(), style_key="s1")
    dense_seven = _fp(("c1", "c2", "c3", "c4", "c5", "c6", "c7"), layouts=("l1",), style_key="s2")

    assert sparse_empty.density_bucket == "sparse"
    assert dense_seven.density_bucket == "dense"
    assert distance(sparse_empty, dense_seven) == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# 4. Quotas / check()
# ---------------------------------------------------------------------------


def test_check_on_an_empty_batch_returns_no_violations() -> None:
    """Nothing to be repetitive or concentrated about yet — the same stance
    `grammar.check` takes toward an artifact type with no grammar entry."""
    assert check([]) == []


def test_unique_ratio_quota_fires_and_clears() -> None:
    repetitive = [_fp(("core.position", "finance.variance_table")) for _ in range(5)]
    assert "unique_ratio_below_quota" in {v.code for v in check(repetitive)}

    varied = [
        _fp(("core.position",)),
        _fp(("finance.variance_table",)),
        _fp(("mgmt.decision_panel",)),
        _fp(("ops.causal_chain",)),
        _fp(("core.narrative",)),
    ]
    assert "unique_ratio_below_quota" not in {v.code for v in check(varied)}


def test_family_share_quota_fires_and_clears() -> None:
    # Every fingerprint draws only from the "finance" family: 100% share.
    all_finance = [
        _fp(("finance.variance_table", "finance.metric_strip")),
        _fp(("finance.variance_bridge", "finance.comparative_trend")),
        _fp(("finance.variance_table", "finance.variance_bridge")),
    ]
    assert "family_share_above_quota" in {v.code for v in check(all_finance)}

    # Five families, evenly split — no single family clears the 20% ceiling.
    balanced = [
        _fp(("core.position",)),
        _fp(("finance.variance_table",)),
        _fp(("mgmt.decision_panel",)),
        _fp(("ops.causal_chain",)),
        _fp(("xlsx.reconciliation",)),
    ]
    assert "family_share_above_quota" not in {v.code for v in check(balanced)}


def test_repetition_run_quota_fires_and_clears() -> None:
    identical = _fp(("core.position", "finance.variance_table"))
    other_a = _fp(("mgmt.decision_panel",))
    other_b = _fp(("ops.causal_chain",))

    # Three in a row (identical, identical, identical) exceeds the default
    # ceiling of 2.
    run_of_three = [identical, identical, identical, other_a, other_b]
    assert "repetition_run_above_quota" in {v.code for v in check(run_of_three)}

    # A run of exactly 2 sits at the default ceiling, not above it: the same
    # boundary `Grammar.check`'s tests hold `<=` checks to.
    run_of_two = [identical, identical, other_a, other_a, other_b]
    assert "repetition_run_above_quota" not in {v.code for v in check(run_of_two)}


def test_entropy_quota_fires_and_clears() -> None:
    uniform = [_fp(("core.position", "finance.variance_table")) for _ in range(6)]
    assert "entropy_below_quota" in {v.code for v in check(uniform)}

    varied = [
        _fp(("core.position", "finance.variance_table")),
        _fp(("finance.variance_table", "mgmt.decision_panel")),
        _fp(("mgmt.decision_panel", "ops.causal_chain")),
        _fp(("ops.causal_chain", "core.narrative")),
        _fp(("core.narrative", "xlsx.reconciliation")),
        _fp(("xlsx.reconciliation", "core.position")),
    ]
    assert "entropy_below_quota" not in {v.code for v in check(varied)}


def test_a_lenient_quotas_object_clears_a_repetitive_batch() -> None:
    """Quotas are declarative data, not a fixed policy — a caller who passes
    a looser `Quotas` must get a looser answer over the same batch."""
    repetitive = [_fp(("core.position",)) for _ in range(4)]
    lenient = Quotas(min_unique_ratio=0.0, max_single_family_share=1.0, max_repetition_run=10, min_entropy_bits=0.0)
    assert check(repetitive, lenient) == []


# ---------------------------------------------------------------------------
# 5. select() — greedy max-min
# ---------------------------------------------------------------------------


def test_select_is_deterministic() -> None:
    candidates = [
        _fp(("a", "b", "c")),
        _fp(("a", "b", "d")),
        _fp(("a", "x", "d")),
        _fp(("q", "r", "s")),
    ]
    first = select(candidates, k=3, seed=1)
    second = select(candidates, k=3, seed=1)
    third = select(candidates, k=3, seed=999)  # seed is unused; must not change the answer
    assert first == second == third


def test_select_picks_the_most_distant_candidate_by_hand() -> None:
    """Four fingerprints, same artifact type/layouts/style/section-count, so
    `distance` reduces entirely to the (equal-length) component-sequence
    term, which for equal-length tuples is the Hamming distance divided by
    the length and scaled by `_WEIGHT_COMPONENTS`:

        0: (A, B, C)
        1: (A, B, D)   -- 1 position differs from 0
        2: (A, X, D)   -- 2 positions differ from 0, 1 from candidate 1
        3: (A, B, C)   -- identical to 0

    Worked by hand (weight and denominator cancel in the *comparisons* below
    since every pairwise distance shares the same 0.45/3 scale):

        d(0,1) ~ 1/3   d(0,2) ~ 2/3   d(0,3) = 0
        d(1,2) ~ 1/3   d(1,3) ~ 1/3   d(2,3) ~ 2/3

    k=1: {0} (first pick is always index 0 — see `select`'s docstring).
    k=2: candidate 2 has the largest distance to {0} (2/3 beats 1/3 and 0),
         so the pick is {0, 2}.
    k=3: of the remainder {1, 3}, candidate 1's minimum distance to {0, 2}
         is min(1/3, 1/3) = 1/3, while candidate 3's is min(0, 2/3) = 0 — 1
         wins, giving {0, 2, 1} in that selection order.
    k=4: only candidate 3 is left; it is appended last.
    """
    candidates = [
        _fp(("A", "B", "C")),  # 0
        _fp(("A", "B", "D")),  # 1
        _fp(("A", "X", "D")),  # 2
        _fp(("A", "B", "C")),  # 3, identical to 0
    ]

    assert select(candidates, k=1, seed=0) == (0,)
    assert select(candidates, k=2, seed=0) == (0, 2)
    assert select(candidates, k=3, seed=0) == (0, 2, 1)
    assert select(candidates, k=4, seed=0) == (0, 2, 1, 3)


def test_select_ties_break_toward_the_lowest_index() -> None:
    """Three candidates equidistant from the first pick: the runner-up must
    be whichever comes first in the input, not whichever the max() happened
    to see last."""
    candidates = [
        _fp(("a",)),
        _fp(("b",)),  # distance 1 from "a" (fully disjoint 1-token sequences)
        _fp(("c",)),  # also distance 1 from "a"
    ]
    assert select(candidates, k=2, seed=0) == (0, 1)


def test_select_rejects_k_larger_than_the_candidate_pool() -> None:
    candidates = [_fp(("a",)), _fp(("b",))]
    with pytest.raises(ValueError, match="cannot select"):
        select(candidates, k=3, seed=0)


def test_select_of_zero_returns_nothing() -> None:
    candidates = [_fp(("a",)), _fp(("b",))]
    assert select(candidates, k=0, seed=0) == ()


# ---------------------------------------------------------------------------
# report() / DiversityReport.__str__
# ---------------------------------------------------------------------------


def test_report_counts_and_str_do_not_raise() -> None:
    fingerprints = [
        _fp(("core.position", "finance.variance_table")),
        _fp(("core.position", "finance.variance_table")),
        _fp(("mgmt.decision_panel",), artifact_type="executive_summary"),
    ]
    batch = report(fingerprints)

    assert batch.count == 3
    assert batch.distinct_digests == 2
    assert batch.longest_repetition_run == 2, "the two identical fingerprints are adjacent"
    assert batch.distinct_shapes_by_type == {"cfo_variance_memo": 1, "executive_summary": 1}
    assert isinstance(str(batch), str) and str(batch)  # __str__ is part of the API, per Scorecard/Summary
    assert isinstance(batch, DiversityReport)


def test_longest_repetition_run_is_order_sensitive() -> None:
    """Same multiset of shapes, different order: the report must disagree,
    because a run of repeats back-to-back is a worse reading experience than
    the same shapes spread through the batch — see the field's own
    docstring."""
    a, b = _fp(("core.position",)), _fp(("mgmt.decision_panel",))

    clustered = report([a, a, a, b])
    spread = report([a, b, a, b])

    assert clustered.longest_repetition_run == 3
    assert spread.longest_repetition_run == 1
    assert clustered.distinct_digests == spread.distinct_digests == 2


# ---------------------------------------------------------------------------
# 6. Regression fixture on the real corpus shape
# ---------------------------------------------------------------------------


def _fingerprint_the_corpus() -> list[Fingerprint]:
    """Fingerprint every docx/xlsx narrative artifact in a small multi-period
    retail-close world.

    Jira/Confluence/ServiceNow bundles are skipped — they are record
    projections (see `docs/artifact-compiler.md` §9.5), not component
    compositions, and neither `render.docx.HANDLES` nor `render.xlsx.HANDLES`
    claims them. `finance_workbook` composes with `fmt="xlsx"`; every other
    handled type composes with `fmt="docx"` — the same split
    `render/pdf.py`'s own compiler integration test (`test_pdf.py`) draws
    from `intent.artifact_type`.
    """
    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period))
    world = world.compile()

    fingerprints: list[Fingerprint] = []
    for ir in world.artifact_irs:
        intent = world.artifact_intents.by_id(ir.intent_id)
        if intent.artifact_type in XLSX_ARTIFACT_TYPES:
            fmt = "xlsx"
        elif intent.artifact_type in DOCX_ARTIFACT_TYPES:
            fmt = "docx"
        else:
            continue
        plan = plan_from_ir(ir, artifact_type=intent.artifact_type, size_class=intent.size_profile)
        composition = compose(plan, fmt=fmt)
        fingerprints.append(fingerprint(composition))
    return fingerprints


def test_regression_the_measured_problem_has_a_floor_to_raise() -> None:
    """Pins today's number so a regression is visible in a diff instead of
    silently shipping.

    Three periods of `RetailWorld(seed=8128)` compose to 13 docx/xlsx
    artifacts (cfo_variance_memo, finance_workbook, and close_calendar each
    appear three times — one per period — plus one each of working_note,
    incident_rca, knowledge_article, and executive_summary) and land on 8
    distinct shapes: cfo_variance_memo and close_calendar each compose
    identically in all three periods today, which is exactly the "12 CFO
    memos, identical outlines" symptom this module exists to detect and
    later fix.

    8 is a **floor**, not a target: this is the number *before* any diversity
    mechanism (batch quotas, candidate selection) is wired into generation —
    that wiring is integration work this module deliberately does not do.
    Diversity work landing later should only ever raise this number. A drop
    below 8 means diversity regressed, not that the fixture needs updating.
    """
    fingerprints = _fingerprint_the_corpus()

    assert len(fingerprints) == 13, "the fixture's own shape moved — update the docstring above, not just the floor"
    batch = report(fingerprints)
    assert batch.distinct_digests >= 8, (
        f"only {batch.distinct_digests} distinct shapes across {batch.count} artifacts — "
        "below the recorded floor; diversity regressed"
    )
