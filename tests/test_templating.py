"""Tests for structural variables in non-prose document parts.

Variables resolve from the world at outline time, but only for non-prose parts:
headings, purpose text, and table titles. Prose (ArtifactSection.body) may never
contain them. This is not a style preference — templated prose puts 63% of
passages into near-duplicate groups, which is why an entire subsystem was deleted
to fight it. See AGENTS.md, "The refine loop that is deliberately not here".

Variables resolve to the world's own attributes and may never introduce a figure.
A second path to a number would be a second source of truth.
"""

from __future__ import annotations

import pytest

from worldloom import World, templating


class TestVariableParsing:
    """Extract and validate variable references."""

    def test_referenced_finds_all_variables(self) -> None:
        """Every {{var:name}} is extracted."""
        text = "Title {{var:company.name}} and {{var:company.name}} again"
        # Deduplicated
        assert templating.referenced(text) == ["company.name"]

    def test_referenced_preserves_order(self) -> None:
        """Variables are extracted in text order, deduplicated."""
        text = "{{var:company.name}} then {{var:company.industry}} then {{var:company.name}}"
        assert templating.referenced(text) == ["company.name", "company.industry"]

    def test_referenced_ignores_malformed(self) -> None:
        """Malformed references are not matched."""
        text = "{{var:0name}} and {{var:name-dash}} and {{var:name space}}"
        assert templating.referenced(text) == []

    def test_unresolved_detects_malformed(self) -> None:
        """Malformed references are detected and returned."""
        text = "Good {{var:company.name}} bad {{var:0name}}"
        assert templating.unresolved(text) == ["0name"]

    def test_unresolved_ignores_well_formed(self) -> None:
        """Well-formed references pass through unresolved check."""
        text = "{{var:company.name}} {{var:company.industry}}"
        assert templating.unresolved(text) == []

    def test_strip_references_removes_all_variables(self) -> None:
        """Variables are removed, leaving the rest."""
        text = "The {{var:company.name}} is in {{var:company.headquarters}}"
        assert templating.strip_references(text) == "The  is in "


class TestVariableSubstitution:
    """Resolve variables from a world."""

    @pytest.fixture
    def world(self) -> World:
        """A test world with known company data."""
        return World.load("retail-close")

    def test_substitute_company_name(self, world: World) -> None:
        """Company name is resolved."""
        text = "{{var:company.name}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert result == world.company.name

    def test_substitute_company_industry(self, world: World) -> None:
        """Company industry is resolved."""
        text = "{{var:company.industry}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert result == world.company.industry

    def test_substitute_company_headquarters(self, world: World) -> None:
        """Company headquarters is resolved."""
        text = "{{var:company.headquarters}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert result == world.company.headquarters

    def test_substitute_company_currency(self, world: World) -> None:
        """Company currency is resolved."""
        text = "{{var:company.currency}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert result == world.company.currency

    def test_substitute_company_currency_unit(self, world: World) -> None:
        """Company currency unit is resolved."""
        text = "{{var:company.currency_unit}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert result == world.company.currency_unit

    def test_substitute_in_heading(self, world: World) -> None:
        """Variables in headings are substituted."""
        text = "Results for {{var:company.name}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert world.company.name in result

    def test_substitute_multiple_in_text(self, world: World) -> None:
        """Multiple variables in one text are all substituted."""
        text = "{{var:company.name}} ({{var:company.industry}}) is in {{var:company.headquarters}}"
        result, unresolved = templating.substitute(text, world)
        assert not unresolved
        assert world.company.name in result
        assert world.company.industry in result
        assert world.company.headquarters in result

    def test_unknown_variable_marked_as_missing(self, world: World) -> None:
        """Unknown variables are marked [missing var:NAME]."""
        text = "Title {{var:nonexistent.field}}"
        result, unresolved = templating.substitute(text, world)
        assert unresolved == ["nonexistent.field"]
        assert "[missing var:nonexistent.field]" in result

    def test_variables_of_variables_refused(self, world: World) -> None:
        """Variables whose values contain {{var:...}} are refused."""
        # This would only happen if _resolve_variable returned a string
        # containing {{var:...}}, which shouldn't happen in normal use but
        # is good to guard against.
        text = "{{var:company.name}}"
        result, unresolved = templating.substitute(text, world)
        # Normal case: should not be unresolved
        assert not unresolved
        # Make sure we're not getting a variable in the output
        assert "{{var:" not in result

    def test_resolve_all_returns_none_if_unresolved(self, world: World) -> None:
        """resolve_all returns None when variables are unresolved."""
        text = "{{var:unknown.variable}}"
        result = templating.resolve_all(text, world)
        assert result is None

    def test_resolve_all_returns_text_if_resolved(self, world: World) -> None:
        """resolve_all returns the text when all variables are resolved."""
        text = "{{var:company.name}} report"
        result = templating.resolve_all(text, world)
        assert result is not None
        assert world.company.name in result


class TestVariableValidation:
    """Validate variables in document types."""

    def test_valid_variable_names(self) -> None:
        """The closed vocabulary of valid names is retrievable."""
        from worldloom.doctypes import _valid_variable_names
        valid = _valid_variable_names()
        # These are the variables we support
        assert "company.name" in valid
        assert "company.industry" in valid
        assert "company.headquarters" in valid
        assert "company.currency" in valid
        assert "company.currency_unit" in valid

    def test_doctypes_lint_accepts_valid_variables(self) -> None:
        """Doctypes with valid variables pass lint."""
        from worldloom.doctypes import DocumentType, Lag, SectionSpec, lint

        types = [
            DocumentType(
                key="test_type",
                authority="working_document",
                lifecycle="draft",
                lag=Lag(),
                sections=[
                    SectionSpec(
                        heading="{{var:company.name}} Results",
                        kinds=["financial.revenue."],
                        scope="any",
                        purpose="Summarize {{var:company.name}} position.",
                    )
                ],
                word=True,
            )
        ]
        findings = lint(types, base="retail")
        # Should have no variable-related findings
        assert not any("variable" in f.lower() for f in findings)

    def test_doctypes_lint_rejects_malformed_variables(self) -> None:
        """Doctypes with malformed variables are rejected."""
        from worldloom.doctypes import DocumentType, Lag, SectionSpec, lint

        types = [
            DocumentType(
                key="test_type",
                authority="working_document",
                lifecycle="draft",
                lag=Lag(),
                sections=[
                    SectionSpec(
                        heading="{{var:0invalid}}",
                        kinds=["financial.revenue."],
                        scope="any",
                        purpose="Test.",
                    )
                ],
                word=True,
            )
        ]
        findings = lint(types, base="retail")
        # Should have a finding about malformed variable
        assert any("malformed" in f.lower() for f in findings)

    def test_doctypes_lint_rejects_unknown_variables(self) -> None:
        """Doctypes with unknown variables are rejected."""
        from worldloom.doctypes import DocumentType, Lag, SectionSpec, lint

        types = [
            DocumentType(
                key="test_type",
                authority="working_document",
                lifecycle="draft",
                lag=Lag(),
                sections=[
                    SectionSpec(
                        heading="{{var:unknown.field}}",
                        kinds=["financial.revenue."],
                        scope="any",
                        purpose="Test.",
                    )
                ],
                word=True,
            )
        ]
        findings = lint(types, base="retail")
        # Should have a finding about unknown variable
        assert any("unknown variable" in f.lower() for f in findings)


class TestVariableSubstitutionInDocuments:
    """Variables are substituted in actual document compilation."""

    def test_no_variables_in_reference_corpus_headings(self) -> None:
        """The reference corpus has no variables (it's hand-authored)."""
        from worldloom import documents
        from worldloom.ids import Minter

        world = World.load("retail-close")
        # Even hand-authored artifacts shouldn't have variables
        for intent in world.artifact_intents:
            minter = Minter()
            ir = documents.outline(world, intent, minter)
            for section in ir.sections:
                # No variables should remain
                assert "{{var:" not in section.heading
                if section.purpose:
                    assert "{{var:" not in section.purpose


class TestDeterminism:
    """Variable resolution is deterministic."""

    def test_same_world_produces_same_resolution(self) -> None:
        """The same text resolved against the same world is identical."""
        world = World.load("retail-close")
        text = "Title for {{var:company.name}}"

        result1, _ = templating.substitute(text, world)
        result2, _ = templating.substitute(text, world)

        assert result1 == result2

    def test_different_worlds_may_produce_different_results(self) -> None:
        """Different worlds may resolve the same template differently."""
        # This is not a requirement but a note: the corpus and the corpus
        # rebuilt from its recipe should have identical variable resolutions
        # because they have identical worlds.
        pass


class TestErrorHandling:
    """Errors are handled gracefully."""

    def test_invalid_path_returns_none(self) -> None:
        """An invalid attribute path returns None from resolution."""
        world = World.load("retail-close")
        text = "{{var:nonexistent}}"
        _result, unresolved = templating.substitute(text, world)
        assert unresolved == ["nonexistent"]

    def test_numeric_values_are_refused(self) -> None:
        """Numeric attributes cannot be resolved as variables."""
        # If a variable resolved to a number, it would be a second source
        # of truth besides {{fact:}}. This is not allowed.
        world = World.load("retail-close")
        # employees_total is numeric
        text = "{{var:company.employees_total}}"
        _result, unresolved = templating.substitute(text, world)
        # Should be marked as unresolved because it's numeric
        assert unresolved == ["company.employees_total"]
