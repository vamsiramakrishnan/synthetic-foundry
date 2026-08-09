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
    incident_rca, knowledge_article, and executive_summary) and land on 7
    distinct shapes: cfo_variance_memo, close_calendar and finance_workbook
    each compose identically in all three periods, which is exactly the "12
    CFO memos, identical outlines" symptom this module exists to detect and
    later fix.

    **It read 8, and the eighth shape was a bug.** `documents.finance_workbook`
    took its reporting month from the world's *current* period rather than from
    its own facts, so in a multi-period corpus every workbook but the last
    looked its figures up at the wrong month and came out with every cell empty
    — a different composition from the populated one, and counted here as
    diversity. Fixing it dropped this number by one. A corpus is not more varied
    for having two of its thirteen documents broken, and a floor that rewarded
    the breakage was measuring the wrong thing.

    7 is a **floor**, not a target: this is the number *before* any diversity
    mechanism (batch quotas, candidate selection) is wired into generation —
    that wiring is integration work this module deliberately does not do.
    Diversity work landing later should only ever raise this number. A drop
    below 7 means diversity regressed, not that the fixture needs updating.
    """
    fingerprints = _fingerprint_the_corpus()

    assert len(fingerprints) == 13, "the fixture's own shape moved — update the docstring above, not just the floor"
    batch = report(fingerprints)
    assert batch.distinct_digests >= 7, (
        f"only {batch.distinct_digests} distinct shapes across {batch.count} artifacts — "
        "below the recorded floor; diversity regressed"
    )


# ---------------------------------------------------------------------------
# Batch assignment: the half `select` leaves open
# ---------------------------------------------------------------------------


def test_collisions_name_the_artifacts_that_share_a_shape() -> None:
    """`report` counts distinct shapes; this says which documents are the
    repeats. The count is a metric, the list is somewhere to go and look."""
    from worldloom.compiler.diversity import collisions

    fingerprints = _fingerprint_the_corpus()
    repeated = collisions(fingerprints)
    assert repeated, "the recorded fixture repeats shapes across its three periods"
    for digest, members in repeated:
        assert len(members) > 1
        assert len({fingerprints[i].digest() for i in members}) == 1
        assert digest == fingerprints[members[0]].digest()
    # Largest group first, which is the order an author wants to work in.
    sizes = [len(members) for _, members in repeated]
    assert sizes == sorted(sizes, reverse=True)


def test_assign_spreads_shapes_across_a_batch_where_select_cannot() -> None:
    """`select` picks the *k* most-unlike alternatives for one artifact and has
    nothing to say about the batch — run independently per artifact it hands
    every one of them index 0, which is precisely how a corpus ends up with 120
    artifacts and 11 shapes. This spreads them."""
    from worldloom.compiler.diversity import assign, select

    # Distinct shapes only. The corpus repeats itself — which is the defect
    # this whole module is about — so a menu taken straight off the front of
    # the list would contain two entries with the same digest, and "use every
    # option" would then be asking for something that is not there.
    seen: dict[str, object] = {}
    for fp in _fingerprint_the_corpus():
        seen.setdefault(fp.digest(), fp)
    menu = list(seen.values())[:4]
    assert len(menu) == 4

    # Every artifact offered the same menu of alternatives: the pathological
    # case, where per-artifact selection is guaranteed to collide.
    batch = [menu] * 4

    per_artifact = [select(menu, k=1, seed=0)[0] for _ in range(4)]
    assert set(per_artifact) == {0}, "per-artifact selection collides, by design"

    chosen = assign(batch)
    assert len(set(chosen)) == len(menu), "the batch should use every distinct shape it has"


def test_assign_respects_what_an_earlier_batch_already_spent() -> None:
    """A corpus built one period at a time must not restart the dispersion at
    every period, or period two reproduces period one exactly."""
    from worldloom.compiler.diversity import assign

    fingerprints = _fingerprint_the_corpus()
    menu = list(fingerprints[:3])
    assert assign([menu], committed=[menu[0]])[0] != 0


def test_assign_refuses_an_artifact_with_no_shapes_to_choose_from() -> None:
    """An empty candidate set means the shape vocabulary is broken, and a quiet
    fallback would hide it behind exactly the monotony this exists to break."""
    from worldloom.compiler.diversity import assign

    fingerprints = _fingerprint_the_corpus()
    with pytest.raises(ValueError, match="no candidate shapes"):
        assign([[fingerprints[0]], []])


# ---------------------------------------------------------------------------
# Outline variants: several arguments per type, rotated over its instances
# ---------------------------------------------------------------------------


def test_a_type_with_variants_does_not_produce_one_shape_six_times() -> None:
    """The measurement this mechanism exists for.

    A six-period corpus produced 12 distinct shapes across 56 artifacts, and
    every near-duplicate group was exactly ×6 — the same document once per
    period, the same headings in the same order. Six close calendars with
    different dates is realistic; six root-cause reviews with an identical
    five-section skeleton is not, because real reviews differ when the incidents
    do and a reader who sees the skeleton six times learns the skeleton.
    """
    from worldloom import MonthEndClose, RetailWorld

    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03", "2026-04"):
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))
    world = world.compile()

    by_type: dict[str, set[tuple[str, ...]]] = {}
    types = {i.id: i.artifact_type for i in world.artifact_intents}
    for ir in world.artifact_irs:
        headings = tuple(s.heading for s in ir.sections if not s.hidden)
        by_type.setdefault(types[ir.intent_id], set()).add(headings)

    assert len(by_type.get("incident_rca", set())) > 1, \
        "four RCAs and one skeleton — the rotation did not reach them"
    assert len(by_type.get("unit_close_commentary", set())) > 1


def test_the_first_instance_keeps_the_outline_that_shipped() -> None:
    """So a type's first document is byte-identical to what it was, and only
    later instances move — which is the intended generation change and the
    smallest one that fixes the measurement."""
    from worldloom import documents

    for artifact_type, variants in documents._OUTLINE_VARIANTS.items():
        assert variants[0] == documents._OUTLINES[artifact_type], artifact_type


def test_the_variant_is_rotated_and_never_drawn() -> None:
    """N instances over M variants land evenly by construction. A seeded draw
    would only *tend* to spread and would happily give six documents the same
    shape on an unlucky seed — the exact failure being fixed."""
    from worldloom import MonthEndClose, RetailWorld, documents

    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period, include_operational_incident=True))

    rcas = [i for i in world.artifact_intents if i.artifact_type == "incident_rca"]
    assert len(rcas) >= 2
    variants = documents._OUTLINE_VARIANTS["incident_rca"]
    for ordinal, intent in enumerate(rcas):
        assert documents._variant_for(world, intent) == variants[ordinal % len(variants)]


def test_a_variant_is_a_different_argument_not_a_reshuffle() -> None:
    """Re-ordering headings without changing what each section is *for* would be
    variety a reader can see and a retriever cannot."""
    from worldloom import documents

    for artifact_type, variants in documents._OUTLINE_VARIANTS.items():
        headings = [frozenset(p.heading for p in variant) for variant in variants]
        assert len(set(headings)) == len(headings), \
            f"{artifact_type} has two variants with the same sections in a different order"
