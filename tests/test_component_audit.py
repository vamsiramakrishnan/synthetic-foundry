"""Tests for the component-and-grammar self-audit.

Each test for a specific check follows the same shape as `test_lifetimes.py`'s
validator tests: build the smallest registry/grammar that is broken exactly
one way, assert the code fires, then fix that one thing and assert it clears.
A hand-built fixture proves a check can fire at all; a shipped registry that
is (by construction) already coherent cannot prove that on its own.

`audit()` takes its registry and grammars as optional arguments precisely so
these tests can hand it fixtures without disturbing `compiler.components` or
`compiler.grammar`, which this task does not own.
"""

from __future__ import annotations

from worldloom.compiler.audit import ERROR, WARNING, AuditFinding, audit
from worldloom.compiler.components import REGISTRY, ComponentSpec
from worldloom.compiler.grammar import GRAMMARS, Grammar


def _codes(findings: list[AuditFinding], *, severity: str | None = None) -> set[str]:
    return {f.code for f in findings if severity is None or f.severity == severity}


def _spec(
    component_id: str,
    *,
    roles: frozenset[str] = frozenset({"evidence"}),
    formats: frozenset[str] = frozenset({"markdown"}),
    **overrides,
) -> ComponentSpec:
    """A component with sane defaults, so each test overrides only what it's about."""
    fields = dict(
        component_id=component_id,
        semantic_roles=roles,
        supported_formats=formats,
    )
    fields.update(overrides)
    return ComponentSpec(**fields)


# ---------------------------------------------------------------------------
# 1. The regression guard
# ---------------------------------------------------------------------------


def test_shipped_registry_and_grammars_have_no_errors() -> None:
    """This is what fails the day somebody adds a broken component or grammar.

    Warnings are allowed — `core.section_divider`'s `structure` role is
    genuinely requested by no shipped grammar, which is a legitimate
    `unreachable_component` warning, not a defect — only errors gate this.
    """
    findings = audit()
    errors = [f for f in findings if f.severity == ERROR]
    assert errors == [], f"shipped registry/grammars have audit errors: {errors}"


def test_audit_defaults_match_explicit_shipped_arguments() -> None:
    """`audit()` with no arguments must be the same call as passing the shipped
    registry and grammars explicitly — the defaulting is not a special path."""
    assert audit() == audit(REGISTRY, GRAMMARS)


# ---------------------------------------------------------------------------
# 2. Determinism
# ---------------------------------------------------------------------------


def test_audit_is_deterministic_on_the_shipped_data() -> None:
    assert audit() == audit()


def test_audit_is_deterministic_on_a_broken_registry() -> None:
    """Determinism must hold even when several findings fire at once and have
    to be sorted against each other, not just when the result is empty."""
    broken = (
        _spec("dup.a", requires_predecessor_role="nowhere"),
        _spec("dup.a", supported_formats=frozenset()),
        _spec("dup.b", min_rows=5, max_rows=1),
    )
    first = audit(broken, {})
    second = audit(broken, {})
    assert first == second
    assert [f.code for f in first] == sorted(f.code for f in first), "not just equal — sorted"


# ---------------------------------------------------------------------------
# 3. unsatisfiable_precondition
# ---------------------------------------------------------------------------


def test_unsatisfiable_precondition_fires_and_clears() -> None:
    broken = (
        _spec("core.a", roles=frozenset({"position"})),
        _spec("mgmt.decision", roles=frozenset({"decision"}), requires_predecessor_role="nonexistent"),
    )
    assert "unsatisfiable_precondition" in _codes(audit(broken, {}))

    fixed = (
        _spec("core.a", roles=frozenset({"position"})),
        _spec("mgmt.decision", roles=frozenset({"decision"}), requires_predecessor_role="position"),
    )
    assert "unsatisfiable_precondition" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 4. unreachable_component
# ---------------------------------------------------------------------------


def test_unreachable_component_fires_and_clears() -> None:
    registry = (_spec("core.orphan", roles=frozenset({"orphan_role"})),)

    unrequested = {}
    findings = audit(registry, unrequested)
    assert "unreachable_component" in _codes(findings, severity=WARNING)

    requesting = {
        "some_type": Grammar(artifact_type="some_type", requires_roles=frozenset({"orphan_role"})),
    }
    assert "unreachable_component" not in _codes(audit(registry, requesting))


def test_unreachable_component_is_a_warning_not_an_error() -> None:
    """The unsound version of this check would report an error; the sound,
    weaker version this module implements never does — see the module
    docstring for why "no grammar requests it" cannot mean "unreachable"."""
    registry = (_spec("core.orphan", roles=frozenset({"orphan_role"})),)
    findings = [f for f in audit(registry, {}) if f.code == "unreachable_component"]
    assert findings and all(f.severity == WARNING for f in findings)


# ---------------------------------------------------------------------------
# 5. impossible_density
# ---------------------------------------------------------------------------


def test_impossible_density_fires_and_clears() -> None:
    # (0.3, 0.4) straddles none of this module's density-profile points
    # (1/6, 1/2, 5/6) — the band is too narrow and in the wrong place for any
    # of them to land inside it.
    broken = (_spec("core.narrow", density=(0.3, 0.4)),)
    assert "impossible_density" in _codes(audit(broken, {}), severity=WARNING)

    fixed = (_spec("core.narrow", density=(0.3, 0.5)),)
    assert "impossible_density" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 6. contradictory_rows
# ---------------------------------------------------------------------------


def test_contradictory_rows_fires_and_clears() -> None:
    broken = (_spec("core.rows", min_rows=5, max_rows=3),)
    assert "contradictory_rows" in _codes(audit(broken, {}), severity=ERROR)

    fixed = (_spec("core.rows", min_rows=3, max_rows=5),)
    assert "contradictory_rows" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 7. asymmetric_incompatibility
# ---------------------------------------------------------------------------


def test_asymmetric_incompatibility_fires_and_clears() -> None:
    broken = (
        _spec("core.a", incompatible_with=frozenset({"core.b"})),
        _spec("core.b"),
    )
    assert "asymmetric_incompatibility" in _codes(audit(broken, {}), severity=WARNING)

    fixed = (
        _spec("core.a", incompatible_with=frozenset({"core.b"})),
        _spec("core.b", incompatible_with=frozenset({"core.a"})),
    )
    assert "asymmetric_incompatibility" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 8. duplicate_component_id
# ---------------------------------------------------------------------------


def test_duplicate_component_id_fires_and_clears() -> None:
    broken = (_spec("core.dup"), _spec("core.dup", roles=frozenset({"summary"})))
    assert "duplicate_component_id" in _codes(audit(broken, {}), severity=ERROR)

    fixed = (_spec("core.dup"), _spec("core.other", roles=frozenset({"summary"})))
    assert "duplicate_component_id" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 9. no_format
# ---------------------------------------------------------------------------


def test_no_format_fires_and_clears() -> None:
    broken = (_spec("core.formatless", formats=frozenset()),)
    assert "no_format" in _codes(audit(broken, {}), severity=ERROR)

    fixed = (_spec("core.formatless", formats=frozenset({"markdown"})),)
    assert "no_format" not in _codes(audit(fixed, {}))


# ---------------------------------------------------------------------------
# 10. grammar_requires_unknown_role
# ---------------------------------------------------------------------------


def test_grammar_requires_unknown_role_fires_and_clears() -> None:
    registry = (_spec("core.a", roles=frozenset({"position"})),)

    broken = {"memo": Grammar(artifact_type="memo", requires_roles=frozenset({"nowhere"}))}
    assert "grammar_requires_unknown_role" in _codes(audit(registry, broken), severity=ERROR)

    fixed = {"memo": Grammar(artifact_type="memo", requires_roles=frozenset({"position"}))}
    assert "grammar_requires_unknown_role" not in _codes(audit(registry, fixed))


# ---------------------------------------------------------------------------
# 11. grammar_self_contradictory
# ---------------------------------------------------------------------------


def test_grammar_self_contradictory_fires_and_clears() -> None:
    registry = (_spec("core.a", roles=frozenset({"position"})),)

    broken = {
        "memo": Grammar(
            artifact_type="memo",
            requires_roles=frozenset({"position"}),
            forbids_roles=frozenset({"position"}),
        )
    }
    assert "grammar_self_contradictory" in _codes(audit(registry, broken), severity=ERROR)

    fixed = {
        "memo": Grammar(
            artifact_type="memo",
            requires_roles=frozenset({"position"}),
            forbids_roles=frozenset(),
        )
    }
    assert "grammar_self_contradictory" not in _codes(audit(registry, fixed))


# ---------------------------------------------------------------------------
# 12. grammar_unsatisfiable_ordering
# ---------------------------------------------------------------------------


def test_grammar_unsatisfiable_ordering_fires_and_clears() -> None:
    registry = (
        _spec("core.a", roles=frozenset({"a_role"})),
        _spec("core.b", roles=frozenset({"b_role"})),
    )

    broken = {
        "memo": Grammar(
            artifact_type="memo",
            ordered_roles=(("a_role", "b_role"), ("b_role", "a_role")),
        )
    }
    assert "grammar_unsatisfiable_ordering" in _codes(audit(registry, broken), severity=ERROR)

    fixed = {
        "memo": Grammar(artifact_type="memo", ordered_roles=(("a_role", "b_role"),)),
    }
    assert "grammar_unsatisfiable_ordering" not in _codes(audit(registry, fixed))


def test_grammar_unsatisfiable_ordering_catches_a_longer_cycle() -> None:
    """The cycle need not be a direct pair — A before B, B before C, C before A
    is just as unsatisfiable and has to be caught by the same traversal."""
    registry = (
        _spec("core.a", roles=frozenset({"a_role"})),
        _spec("core.b", roles=frozenset({"b_role"})),
        _spec("core.c", roles=frozenset({"c_role"})),
    )
    broken = {
        "memo": Grammar(
            artifact_type="memo",
            ordered_roles=(("a_role", "b_role"), ("b_role", "c_role"), ("c_role", "a_role")),
        )
    }
    assert "grammar_unsatisfiable_ordering" in _codes(audit(registry, broken), severity=ERROR)


# ---------------------------------------------------------------------------
# 13. grammar_cap_below_requirement
# ---------------------------------------------------------------------------


def test_grammar_cap_below_requirement_fires_and_clears() -> None:
    registry = (
        _spec("core.a", roles=frozenset({"a_role"})),
        _spec("core.b", roles=frozenset({"b_role"})),
    )

    broken = {
        "memo": Grammar(
            artifact_type="memo",
            requires_roles=frozenset({"a_role", "b_role"}),
            max_components=1,
        )
    }
    assert "grammar_cap_below_requirement" in _codes(audit(registry, broken), severity=WARNING)

    fixed = {
        "memo": Grammar(
            artifact_type="memo",
            requires_roles=frozenset({"a_role", "b_role"}),
            max_components=2,
        )
    }
    assert "grammar_cap_below_requirement" not in _codes(audit(registry, fixed))


# ---------------------------------------------------------------------------
# 14. grammar_opening_impossible
# ---------------------------------------------------------------------------


def test_grammar_opening_impossible_fires_for_an_unknown_role_and_clears() -> None:
    registry = (_spec("core.a", roles=frozenset({"position"})),)

    broken = {"memo": Grammar(artifact_type="memo", opens_with=frozenset({"nowhere"}))}
    assert "grammar_opening_impossible" in _codes(audit(registry, broken), severity=ERROR)

    fixed = {"memo": Grammar(artifact_type="memo", opens_with=frozenset({"position"}))}
    assert "grammar_opening_impossible" not in _codes(audit(registry, fixed))


def test_grammar_opening_impossible_fires_when_the_only_opener_has_no_format() -> None:
    """A role that exists in the registry is not enough to open with — the
    component filling it also has to be renderable in *some* format."""
    registry = (_spec("core.a", roles=frozenset({"position"}), formats=frozenset()),)

    grammar = {"memo": Grammar(artifact_type="memo", opens_with=frozenset({"position"}))}
    assert "grammar_opening_impossible" in _codes(audit(registry, grammar), severity=ERROR)


def test_grammar_opening_impossible_is_unconstrained_when_opens_with_is_empty() -> None:
    """Per `Grammar`'s own docstring, an empty `opens_with` means unconstrained,
    not "nothing may open it" — this check must not invent a constraint that
    was never declared."""
    registry: tuple[ComponentSpec, ...] = ()
    grammar = {"memo": Grammar(artifact_type="memo", opens_with=frozenset())}
    assert "grammar_opening_impossible" not in _codes(audit(registry, grammar))
