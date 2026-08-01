"""Tests for the grown component vocabulary — `compiler/components.py` and
`compiler/grammar.py` together, against both the shipped data and a real
built world.

Same idiom as `test_lifetimes.py`: most checks here are static properties of
the shipped `REGISTRY`/`GRAMMARS` (every entry has a purpose, every role has
somewhere rowless to land), proven directly against the data rather than by
constructing a case. The regression fixture at the end is the one exception —
it exists to pin the measured problem this vocabulary was grown to fix
(`core.narrative` absorbing 78% of every composed component in a 12-period
corpus) against a real, smaller corpus, the same way
`test_diversity.py::test_regression_the_measured_problem_has_a_floor_to_raise`
pins the shape-count floor.
"""

from __future__ import annotations

from worldloom import MonthEndClose, RetailWorld
from worldloom.compiler.compose import compose, plan_from_ir
from worldloom.compiler.components import REGISTRY
from worldloom.compiler.diversity import fingerprint, report
from worldloom.compiler.grammar import GRAMMARS
from worldloom.render.docx import HANDLES as DOCX_ARTIFACT_TYPES
from worldloom.render.xlsx import HANDLES as XLSX_ARTIFACT_TYPES

# ---------------------------------------------------------------------------
# 1. Every registry entry is a real, usable atom
# ---------------------------------------------------------------------------


def test_every_component_has_a_purpose_a_role_and_a_format() -> None:
    """A component with an empty `purpose` is a label, not vocabulary — it
    would reach the narrative request (`compiler.handshake._vocabulary`) as
    an empty string, which is a request an author cannot act on. A component
    with no `semantic_roles` or no `supported_formats` is `no_format`- or
    `unsatisfiable`-shaped dead weight `audit.py` would catch structurally;
    this pins the same property directly against the shipped data, in the
    one place an author-facing test belongs.
    """
    for spec in REGISTRY:
        assert spec.purpose.strip(), f"{spec.component_id} has no purpose"
        assert spec.semantic_roles, f"{spec.component_id} fills no role"
        assert spec.supported_formats, f"{spec.component_id} supports no format"


# ---------------------------------------------------------------------------
# 2. markdown is the universal fallback for narrative components
# ---------------------------------------------------------------------------


def test_every_narrative_component_supports_markdown() -> None:
    """`markdown` is what the narrative pipeline reads back and what a reader
    gets with no Office library installed (`components.py`'s own module
    docstring) — every component whose job is to carry prose or a narrative
    table must be spellable there.

    Two families are the deliberate exception. `xlsx.*` atoms are workbook
    structure (a report sheet, a reconciliation, a lineage trace) rather than
    narrative — a sheet has no honest one-column-of-text markdown rendering,
    the same reason `xlsx.reconciliation`/`xlsx.lineage` have never supported
    it. `structure`-role dividers (`core.section_divider`,
    `framing.appendix_divider`) carry no content of their own — they are a
    page or slide boundary, a concept flat markdown does not have — which is
    why `core.section_divider` has never supported markdown either; this is
    an existing, pre-dating rule this test confirms rather than one it
    invents.
    """
    for spec in REGISTRY:
        if spec.component_id.startswith("xlsx.") or "structure" in spec.semantic_roles:
            continue
        assert "markdown" in spec.supported_formats, (
            f"{spec.component_id} is a narrative component but does not support markdown"
        )


# ---------------------------------------------------------------------------
# 3. Every role has somewhere rowless to land
# ---------------------------------------------------------------------------


def test_no_role_is_provided_only_by_components_with_a_row_floor() -> None:
    """This bug already happened once: `explain_change` had no prose fallback,
    and composing an outline with a one-fact "why this moved" beat had
    nothing to select. A rowless beat — the common case for a short prose
    section — must always have at least one component with `min_rows == 0`
    willing to take it, for every role the registry declares at all.
    """
    roles: dict[str, list[str]] = {}
    for spec in REGISTRY:
        for role in spec.semantic_roles:
            roles.setdefault(role, []).append(spec.component_id)

    assert roles, "the registry declares no roles at all"
    for role, component_ids in roles.items():
        rowless = [
            cid for cid in component_ids
            if next(s for s in REGISTRY if s.component_id == cid).min_rows == 0
        ]
        assert rowless, (
            f"role {role!r} is provided only by {component_ids}, all of which have a row "
            "floor — a rowless beat naming this role would have nowhere to land"
        )


# ---------------------------------------------------------------------------
# 4. Every grammar's requires_roles is satisfiable by the registry
# ---------------------------------------------------------------------------


def test_every_grammars_requires_roles_is_satisfiable() -> None:
    """The static half of `audit._check_grammar_requires_unknown_role`, run
    directly here rather than only through `audit()` — a `requires_roles`
    entry naming a role no component provides fails every possible
    composition of that artifact type, unconditionally, which is exactly the
    defect this vocabulary's growth must never reintroduce.
    """
    provided: set[str] = set()
    for spec in REGISTRY:
        provided |= spec.semantic_roles

    for artifact_type, grammar in GRAMMARS.items():
        missing = grammar.requires_roles - provided
        assert not missing, (
            f"{artifact_type}'s grammar requires {sorted(missing)}, which no component provides"
        )


# ---------------------------------------------------------------------------
# 5. core's family share on the real 3-period corpus stays below 50%
# ---------------------------------------------------------------------------


def _fingerprint_the_corpus() -> list:
    """Fingerprint every docx/xlsx narrative artifact in a small multi-period
    retail-close world — the same construction
    `test_diversity.py::_fingerprint_the_corpus` uses, rebuilt here rather
    than imported so this file does not couple to a test module outside its
    ownership.
    """
    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period))
    world = world.compile()

    fingerprints = []
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


def test_core_family_share_is_below_the_measured_ceiling() -> None:
    """78% was the measured problem (`components.py`'s own module docstring).
    50% is not a target to approach — it is a ceiling this vocabulary must
    keep beating by a real margin as more atoms and grammars are added, the
    same way `test_diversity.py` pins its shape-count number as a floor
    rather than a target. On today's registry this lands near 30%, with
    `core` no longer even the largest family — `xlsx.report_sheet` now
    carries the finance-workbook share `core.narrative` used to.
    """
    batch = report(_fingerprint_the_corpus())
    assert batch.count > 0, "fixture produced no artifacts to measure"
    if batch.max_family == "core":
        assert batch.max_family_share < 0.5, (
            f"core holds {batch.max_family_share:.0%} of all composed components — "
            "regressed toward the measured 78% problem"
        )
    # If some other family is now the largest, core's own share could still be
    # under the ceiling but not reported as `max_family` — recompute it
    # directly so this test does not go blind the moment core stops being #1.
    from collections import Counter

    from worldloom.compiler.diversity import _family

    counts: Counter[str] = Counter()
    for fp in _fingerprint_the_corpus():
        for component_id in fp.components:
            counts[_family(component_id)] += 1
    total = sum(counts.values())
    assert total > 0
    core_share = counts.get("core", 0) / total
    assert core_share < 0.5, f"core holds {core_share:.0%} of all composed components"


# ---------------------------------------------------------------------------
# 6. All ten artifact types still compose grammatically
# ---------------------------------------------------------------------------


def test_all_ten_artifact_types_compose_grammatically() -> None:
    """The hard constraint the whole task sits under: growing the vocabulary
    and adding grammars must never make an artifact type that composed
    cleanly before start failing. Mirrors the exact check the task's own
    report is built from.
    """
    world = (
        RetailWorld(seed=8128)
        .build()
        .run(MonthEndClose("2026-03", include_operational_incident=True))
        .compile()
    )
    meta = {intent.id: (intent.artifact_type, intent.size_profile) for intent in world.artifact_intents}

    seen_types: set[str] = set()
    for ir in world.artifact_irs:
        artifact_type, size_profile = meta[ir.intent_id]
        plan = plan_from_ir(ir, artifact_type=artifact_type, size_class=size_profile)
        if not plan.beats:
            continue
        fmt = "xlsx" if artifact_type == "finance_workbook" else "docx"
        composition = compose(plan, fmt=fmt)
        assert composition.ok, (artifact_type, [str(v) for v in composition.violations])
        seen_types.add(artifact_type)

    # Thirteen since the fan-out layer: the ten close artifacts plus minutes,
    # the escalation thread, and per-unit commentary.
    assert len(seen_types) == 13, f"expected all 13 artifact types, saw {sorted(seen_types)}"
