"""The fact-kind registry, its refusals, and the seams it closes.

The registry exists because an episode spec once cited two invented kinds and
its own lint could only compare the spec against itself. These tests pin the
three properties that stop that recurring: registration refuses redefinition,
`lob.lint_responsibilities` refuses a kind nothing generates, and the value
primitives keep the invariants they claim by construction.
"""

from __future__ import annotations

import pytest

import worldloom  # noqa: F401 — importing the package is what populates the registry
from worldloom import factkinds, lob
from worldloom.models import ConstraintKind

# ---------------------------------------------------------------------------
# Registration refusals
# ---------------------------------------------------------------------------


def test_identical_reregistration_is_a_harmless_reload() -> None:
    existing = factkinds.get("capital.rwa_total")
    assert existing is not None
    factkinds.register([existing])  # must not raise
    assert factkinds.get("capital.rwa_total") == existing


def test_a_different_declaration_under_a_known_kind_is_refused() -> None:
    """Two modules disagreeing about one kind would make a lint's verdict
    depend on import order — the exact defect `register_domain` refuses."""
    existing = factkinds.get("capital.rwa_total")
    rogue = factkinds.FactKind(
        kind="capital.rwa_total", domain="retail",
        generated_by="somewhere/else.py", invariants=("holds-at",),
    )
    with pytest.raises(ValueError, match="already registered"):
        factkinds.register([rogue])
    assert factkinds.get("capital.rwa_total") == existing, "a refused write must change nothing"


def test_a_kind_with_no_invariants_is_refused() -> None:
    with pytest.raises(ValueError, match="no invariants"):
        factkinds.register([factkinds.FactKind(
            kind="test.uninvariant", domain="core", generated_by="here", invariants=(),
        )])


def test_an_unknown_invariant_head_is_refused() -> None:
    with pytest.raises(ValueError, match="closed"):
        factkinds.register([factkinds.FactKind(
            kind="test.badhead", domain="core", generated_by="here",
            invariants=("wished-for",),
        )])


def test_resolvable_uses_dot_prefix_semantics() -> None:
    """`financial.revenue` covers the actual/budget/variance family; a
    truncation is a typo, not a family."""
    assert factkinds.resolvable("financial.revenue.actual")
    assert factkinds.resolvable("financial.revenue")
    assert not factkinds.resolvable("financial.rev")
    assert not factkinds.resolvable("financial.cost")


# ---------------------------------------------------------------------------
# The LOB lint arm the registry unblocked
# ---------------------------------------------------------------------------


def test_a_responsibility_naming_an_unregistered_kind_is_refused() -> None:
    findings = lob.lint_responsibilities(
        [lob.Responsibility(role_key="cfo", fact_kinds=["financial.cost"])],
        roles=["cfo"],
    )
    assert any("financial.cost" in f and "registry" in f for f in findings), findings


def test_the_standard_library_lobs_pass_their_own_lint() -> None:
    """The shipped LOBs named `financial.cost`, `procurement.order` and
    `employee.headcount` until the registry existed to check them — kinds
    nothing generates, i.e. accountability edges that never fire."""
    for name, spec in lob.publish().items():
        findings = lob.lint_responsibilities(
            spec.responsibilities, roles=[r.key for r in spec.roles],
        )
        assert findings == [], f"{name}: {findings}"


def test_accountability_constraints_derive_from_responsibility_edges() -> None:
    finance = lob.publish()["finance"]
    constraints = lob.accountability_constraints(finance)
    assert constraints, "a LOB with responsibilities must derive constraints"
    assert all(c.kind is ConstraintKind.ACCOUNTABILITY for c in constraints)
    targets = [c.target for c in constraints]
    assert "cfo/financial.revenue" in targets
    assert targets == sorted(targets, key=targets.index), "declaration order is the order"
    assert all(c.magnitude == 5.0 for c in constraints), "the default tolerance band"


# ---------------------------------------------------------------------------
# One primitive, held to its claim
# ---------------------------------------------------------------------------


def test_rollup_children_sum_to_the_parent_exactly() -> None:
    """Allocated from the total, never drawn and summed — the only shape under
    which sums-to holds by construction."""
    from worldloom.generators.primitives import rollup

    children = rollup(15_500, [0.62, 0.23, 0.11, 0.04])
    assert sum(children) == 15_500


def test_supersession_pair_is_deterministic_and_additive() -> None:
    from worldloom.generators.primitives import supersession_pair
    from worldloom.parameters import DEFAULT
    from worldloom.rng import Rng

    draw = lambda: supersession_pair(  # noqa: E731
        DEFAULT, "capital.rwa.filed_hundreds", "capital.error.understatement_pct",
        Rng(8128).derive("test/pair"), scale=100,
    )
    first, second = draw(), draw()
    assert first == second, "same seed, same stream, same pair"
    initial, corrected = first
    assert corrected > initial, "the correction is adverse by construction"
