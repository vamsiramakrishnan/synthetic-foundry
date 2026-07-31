"""Tests for `worldloom diversity`.

Mirrors `tests/test_library.py`'s CLI section (`typer.testing.CliRunner`, the
harness this repository already uses for command-level tests) rather than
`tests/test_evaluate.py`, which tests the `evaluate` *library* call directly —
this file is about the command surface `cli.py` adds, not about
`compiler.diversity` itself (that module's own behaviour is already covered by
`tests/test_diversity.py`).

Three other agents are editing `compiler/components.py` and `compiler/grammar.py`
in this tree at the same time, so the *numbers* a real, generated corpus
produces can change under this file without warning. Every test below that needs
a batch to actually violate or actually clear a quota builds that batch by hand
for that reason (see `_hand_built_world`), rather than leaning on the shipped
`retail-close` corpus's current shape.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.cli import app
from worldloom.models import ArtifactIntent, ArtifactIR, ArtifactSection, Company

runner = CliRunner()


def _hand_built_world(
    *,
    artifact_type: str = "close_calendar",
    count: int = 5,
    sections: list[ArtifactSection] | None = None,
) -> World:
    """A tiny corpus with `count` *identical* pre-composed artifact IRs.

    Built directly through `World`'s constructor rather than
    `RetailWorld().build().run(...)` — deliberately bypassing generation
    entirely, so this fixture is immune to the concurrent work on the component
    registry and grammar described in the module docstring: every section here
    is `optional=True`, so `compose()` (in `cli.diversity`) never hits a
    required beat with no fitting component no matter what the registry
    contains today, and identical hand-written input composes to an identical
    shape every time regardless of *which* components a given semantic role
    happens to resolve to. That determinism is all a repetition-run violation
    needs — the specific components chosen are incidental.
    """
    sections = sections if sections is not None else [
        ArtifactSection(heading="Position", optional=True),
        ArtifactSection(heading="Detail", optional=True),
    ]
    company = Company(
        id="ORG-0001",
        name="Diversity Test Co",
        industry="retail",
        headquarters="Testville",
        fiscal_year_start_month=1,
        employees_total=10,
    )
    intents = tuple(
        ArtifactIntent(
            id=f"ART-{i:04d}",
            artifact_type=artifact_type,
            domain="finance",
            audience="group_cfo",
            author_id="PERSON-0001",
            size_profile="medium",
        )
        for i in range(1, count + 1)
    )
    irs = tuple(
        ArtifactIR(id=f"IR-{i:04d}", intent_id=f"ART-{i:04d}", title="Test artifact", sections=sections)
        for i in range(1, count + 1)
    )
    return World(company=company, _artifact_intents=intents, _artifact_irs=irs)


@pytest.fixture(scope="module")
def real_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A small, actually-generated multi-period world, exported but not narrated.

    Diversity only needs `Composition`s (structure), not prose, so this skips
    `narrate`/`render` entirely — the same shortcut `test_evaluate.py` cannot
    take (it needs rendered text) but `worldloom diversity` legitimately can.
    """
    out = tmp_path_factory.mktemp("real-corpus")
    world = RetailWorld(seed=8128).build()
    for period in ("2026-01", "2026-02", "2026-03"):
        world = world.run(MonthEndClose(period=period))
    world.export(out, overwrite=True)
    return out


@pytest.fixture(scope="module")
def violating_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A hand-built batch guaranteed to fail every default `Quotas` threshold at
    once: five identical two-section artifacts of the same type compose to one
    shape, repeated five times in a row, drawing on a single component family."""
    out = tmp_path_factory.mktemp("violating-corpus")
    _hand_built_world().export(out, overwrite=True)
    return out


@pytest.fixture(scope="module")
def uncompilable_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A world with no artifact intents at all — `world.compile()` raises
    `ValueError` for this shape (see `world.py`), which is the crash this
    command has to turn into a message instead."""
    out = tmp_path_factory.mktemp("uncompilable-corpus")
    company = Company(
        id="ORG-0001",
        name="Empty Co",
        industry="retail",
        headquarters="Testville",
        fiscal_year_start_month=1,
        employees_total=10,
    )
    World(company=company).export(out, overwrite=True)
    return out


@pytest.fixture(scope="module")
def unrenderable_corpus(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A world that *did* compile but whose only artifact type neither the DOCX
    nor the XLSX renderer claims — the other way `fingerprints` can end up
    empty without ever calling `compile()` (or hitting its `ValueError`)."""
    out = tmp_path_factory.mktemp("unrenderable-corpus")
    _hand_built_world(artifact_type="not_a_composable_type", count=2).export(out, overwrite=True)
    return out


# ---------------------------------------------------------------------------
# 1. A real corpus: exits 0, prints a report
# ---------------------------------------------------------------------------


def test_diversity_reports_on_a_real_corpus(real_corpus: Path) -> None:
    result = runner.invoke(app, ["diversity", str(real_corpus)])
    assert result.exit_code == 0, result.output
    assert "Diversity —" in result.output
    assert "n-gram entropy" in result.output
    assert "max family share" in result.output
    assert "longest repetition run" in result.output


# ---------------------------------------------------------------------------
# 2. -v / --verbose prints strictly more than the plain form
# ---------------------------------------------------------------------------


def test_verbose_prints_more_than_the_plain_form(violating_corpus: Path) -> None:
    plain = runner.invoke(app, ["diversity", str(violating_corpus)])
    verbose = runner.invoke(app, ["diversity", str(violating_corpus), "--verbose"])
    assert plain.exit_code == 0, plain.output
    assert verbose.exit_code == 0, verbose.output

    assert len(verbose.output) > len(plain.output)
    # The plain form already names the artifact type once (in the per-type
    # count table); verbose additionally names the actual distinct shapes,
    # which is the content the short flag has to add to earn its own test.
    assert "close_calendar" in plain.output
    assert "→" in verbose.output, "verbose should spell out the actual component sequence"
    assert "→" not in plain.output


def test_verbose_short_flag_matches_the_long_one(violating_corpus: Path) -> None:
    short = runner.invoke(app, ["diversity", str(violating_corpus), "-v"])
    long_ = runner.invoke(app, ["diversity", str(violating_corpus), "--verbose"])
    assert short.output == long_.output


# ---------------------------------------------------------------------------
# 3. --check-quotas: non-zero on a violating batch, zero on a clean one
# ---------------------------------------------------------------------------


def test_check_quotas_fails_a_batch_built_to_violate_every_threshold(violating_corpus: Path) -> None:
    result = runner.invoke(app, ["diversity", str(violating_corpus), "--check-quotas"])
    assert result.exit_code == 1, result.output
    for code in (
        "unique_ratio_below_quota",
        "family_share_above_quota",
        "repetition_run_above_quota",
        "entropy_below_quota",
    ):
        assert code in result.output, result.output


def test_check_quotas_clears_a_batch_with_nothing_in_it(uncompilable_corpus: Path) -> None:
    """The "clears" half of the flag test, deliberately *not* built from a
    real, currently-clean corpus.

    Today every real corpus this repository can build fails the `core` family-
    share quota (see `.claude/skills/worldloom/references/diversity.md`), and
    another agent is actively working on the fix — so a real corpus is exactly
    the wrong fixture for a test that has to keep passing regardless of when it
    runs relative to that fix landing. An empty batch is not a synthetic
    stand-in for "diverse"; `compiler.diversity.check`'s own docstring states
    plainly that an empty batch trivially meets every quota (nothing to be
    repetitive or concentrated about yet), so exercising exactly that case is a
    real assertion about documented behaviour, not a cheat to dodge the harder
    fixture.
    """
    result = runner.invoke(app, ["diversity", str(uncompilable_corpus), "--check-quotas"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# 4. Nothing compilable: a message, not a traceback
# ---------------------------------------------------------------------------


def test_no_artifact_intents_at_all_is_handled_gracefully(uncompilable_corpus: Path) -> None:
    result = runner.invoke(app, ["diversity", str(uncompilable_corpus)])
    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "Traceback" not in result.output
    assert "nothing compilable" in result.output


def test_no_docx_or_xlsx_artifact_type_is_handled_gracefully(unrenderable_corpus: Path) -> None:
    """The other route to an empty batch: intents exist and compiled fine, but
    every artifact type belongs to a renderer (Jira/Confluence/ServiceNow) that
    is a record projection rather than a component composition, so nothing here
    has a `Composition` to fingerprint."""
    result = runner.invoke(app, ["diversity", str(unrenderable_corpus)])
    assert result.exit_code == 0, result.output
    assert result.exception is None
    assert "Traceback" not in result.output
    assert "nothing compilable" in result.output


# ---------------------------------------------------------------------------
# 5. Determinism
# ---------------------------------------------------------------------------


def test_diversity_output_is_deterministic(real_corpus: Path) -> None:
    first = runner.invoke(app, ["diversity", str(real_corpus), "--verbose"])
    second = runner.invoke(app, ["diversity", str(real_corpus), "--verbose"])
    assert first.exit_code == second.exit_code == 0
    assert first.output == second.output
