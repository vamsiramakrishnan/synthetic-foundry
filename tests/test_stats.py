"""`worldloom stats` — what the corpus contains, not how hard it is.

Deliberately built from a small hand-authored `World` for the correctness tests
below (rather than a generated corpus, whose exact word counts and fact IDs are
a moving target under normal development) — the same shortcut
`test_diversity_cli.py` takes for the same reason. `test_the_shipped_examples_
have_stats` is the one test that runs against real corpora, and only checks
that `compute()` does not raise and returns internally consistent numbers, never
exact figures that would make this file as fragile as the thing it is testing.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import World
from worldloom.cli import app
from worldloom.models import (
    ArtifactIR,
    ArtifactManifestEntry,
    ArtifactSection,
    Authority,
    CanonicalFact,
    Company,
    EvaluationCase,
    EvaluationType,
    Lifecycle,
)
from worldloom.stats import Distribution, compute, diff

runner = CliRunner()

WHEN = datetime(2026, 4, 1, tzinfo=UTC)


def _company() -> Company:
    return Company(
        id="ORG-0001",
        name="Stats Test Co",
        industry="retail",
        headquarters="Testville",
        fiscal_year_start_month=1,
        employees_total=10,
    )


def _fact(fact_id: str, value: str) -> CanonicalFact:
    return CanonicalFact(
        id=fact_id,
        kind="test.figure",
        subject="ORG-0001",
        text_value=value,
        valid_from=WHEN,
        authority=Authority.CONFIRMED,
    )


def _manifest(artifact_id: str, artifact_type: str = "working_note") -> ArtifactManifestEntry:
    return ArtifactManifestEntry(
        id=artifact_id,
        title=artifact_id,
        artifact_type=artifact_type,
        domain="finance",
        path="",
        media_type="text/markdown",
        author_id="PERSON-0001",
        audience="finance",
        created_at=WHEN,
        authority=Authority.CONFIRMED,
        lifecycle=Lifecycle.PUBLISHED,
    )


def _small_world() -> World:
    """Two near-duplicate memos (identical body) citing the same two facts, one
    distinct memo citing a third fact nobody else cites, and one fact
    (FACT-0004) that nothing cites at all.
    """
    facts = (
        _fact("FACT-0001", "one hundred"),
        _fact("FACT-0002", "two hundred"),
        _fact("FACT-0003", "three hundred"),
        _fact("FACT-0004", "never cited"),
    )
    body = "Revenue was {{fact:FACT-0001}} and cost was {{fact:FACT-0002}} this period."
    irs = (
        ArtifactIR(
            id="ART-0001",
            intent_id="ART-0001",
            title="Alpha Memo",
            sections=[ArtifactSection(heading="Summary", body=body)],
        ),
        ArtifactIR(
            id="ART-0002",
            intent_id="ART-0002",
            title="Beta Memo",
            sections=[ArtifactSection(heading="Summary", body=body)],
        ),
        ArtifactIR(
            id="ART-0003",
            intent_id="ART-0003",
            title="Gamma Report",
            sections=[
                ArtifactSection(
                    heading="Analysis",
                    body=(
                        "A wholly different discussion of the quarter, touching on "
                        "staffing, weather, and logistics, with {{fact:FACT-0003}} "
                        "cited once near the very end of a much longer paragraph "
                        "than the other two documents carry, so its shingles do "
                        "not overlap with theirs at all."
                    ),
                )
            ],
        ),
    )
    manifest = tuple(_manifest(ir.id) for ir in irs)
    evaluations = (
        EvaluationCase(
            id="EVAL-0001",
            question="What was revenue?",
            evaluation_type=EvaluationType.DIRECT_LOOKUP,
            expected_fact_ids=["FACT-0001"],
        ),
        EvaluationCase(
            id="EVAL-0002",
            question="What was cost?",
            evaluation_type=EvaluationType.DIRECT_LOOKUP,
            expected_fact_ids=["FACT-0002"],
        ),
        EvaluationCase(
            id="EVAL-0003",
            question="What was staffing spend last year?",
            evaluation_type=EvaluationType.EXPECTED_ABSTENTION,
            expects_abstention=True,
        ),
    )
    return World(
        company=_company(),
        _facts=facts,
        _artifact_irs=irs,
        _artifacts=manifest,
        _evaluations=evaluations,
    )


# ---------------------------------------------------------------------------
# Distribution
# ---------------------------------------------------------------------------


def test_distribution_of_empty_is_all_zero() -> None:
    d = Distribution.of([])
    assert (d.minimum, d.median, d.p90, d.maximum, d.n) == (0.0, 0.0, 0.0, 0.0, 0)


def test_distribution_reports_observed_values_only() -> None:
    """Nearest-rank, not interpolated — every reported figure is one that was
    actually in the sample."""
    values = [1.0, 2.0, 3.0, 4.0, 100.0]
    d = Distribution.of(values)
    assert d.minimum == 1.0
    assert d.maximum == 100.0
    assert d.median in values
    assert d.p90 in values
    assert d.n == 5


# ---------------------------------------------------------------------------
# compute(): correctness against a known small world
# ---------------------------------------------------------------------------


def test_document_count_and_types() -> None:
    report = compute(_small_world())
    assert report.document_count == 3
    assert report.documents_by_type == {"working_note": 3}


def test_near_duplicate_pair_is_found() -> None:
    """Alpha and Beta share an identical body — their one shingle set is
    identical, so Jaccard is 1.0 and they must be flagged. Gamma's much longer,
    unrelated paragraph should not pair with either."""
    report = compute(_small_world())
    assert report.near_duplicate_pairs == 1
    assert report.near_duplicate_total_pairs == 3  # C(3, 2) passages, one per document here
    assert report.near_duplicate_rate == pytest.approx(1 / 3)


def test_citation_graph() -> None:
    report = compute(_small_world())
    # FACT-0001 and FACT-0002 are each cited by Alpha and Beta (2 documents);
    # FACT-0003 only by Gamma (1); FACT-0004 by nobody.
    assert report.fact_count == 4
    assert report.uncited_fact_count == 1
    assert report.documents_per_fact.maximum == 2.0
    assert report.documents_per_fact.minimum == 1.0
    assert report.documents_per_fact.n == 3  # three facts are cited at all


def test_facts_per_document_and_density() -> None:
    report = compute(_small_world())
    # Alpha and Beta each cite 2 facts; Gamma cites 1.
    assert sorted([report.facts_per_document.minimum, report.facts_per_document.maximum]) == [1.0, 2.0]
    assert report.fact_density.n == 3


def test_vocabulary_and_ttr_are_positive_and_bounded() -> None:
    report = compute(_small_world())
    assert report.vocabulary_size > 0
    assert report.total_tokens >= report.vocabulary_size
    assert 0.0 < report.type_token_ratio <= 1.0


def test_eval_cases_by_family() -> None:
    report = compute(_small_world())
    assert report.evals_by_type == {"direct_lookup": 2, "expected_abstention": 1}
    assert report.eval_count == 3


def test_compute_is_deterministic() -> None:
    world = _small_world()
    first = compute(world)
    second = compute(world)
    assert first == second
    assert first.as_dict() == second.as_dict()


def test_compute_raises_on_a_world_with_nothing_to_measure() -> None:
    with pytest.raises(ValueError, match="nothing to compute statistics from"):
        compute(World(company=_company()))


# ---------------------------------------------------------------------------
# diff()
# ---------------------------------------------------------------------------


def test_diff_prints_both_labels_and_every_row() -> None:
    a = compute(_small_world())
    text = diff(a, a, a_label="left", b_label="right")
    assert "left" in text
    assert "right" in text
    assert "documents" in text
    assert "vocabulary size" in text
    assert "eval cases" in text


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def test_the_shipped_examples_have_stats() -> None:
    """The one test against a real, shipped corpus: it must not raise and must
    report internally consistent totals, not any specific figure — those
    figures are the delivery report's job, not a fragile regression pin here.
    """
    result = runner.invoke(app, ["stats", "retail-close"])
    assert result.exit_code == 0, result.output
    assert "Corpus statistics" in result.output
    assert "eval cases by family" in result.output


def test_stats_json_has_stable_keys() -> None:
    result = runner.invoke(app, ["stats", "retail-close", "--json"])
    assert result.exit_code == 0, result.output
    import json

    payload = json.loads(result.output)
    assert payload["corpus"] == "retail-close"
    for key in (
        "document_count",
        "documents_by_type",
        "word_length",
        "token_length",
        "vocabulary_size",
        "type_token_ratio",
        "near_duplicate",
        "facts_per_document",
        "fact_density_per_100_tokens",
        "documents_per_fact",
        "evals_by_type",
        "eval_count",
    ):
        assert key in payload, f"missing {key}"


def test_stats_output_is_deterministic() -> None:
    first = runner.invoke(app, ["stats", "retail-close"])
    second = runner.invoke(app, ["stats", "retail-close"])
    assert first.output == second.output


def test_against_diffs_two_corpora(tmp_path: Path) -> None:
    world = _small_world()
    out = tmp_path / "exported"
    world.export(out, overwrite=True)
    result = runner.invoke(app, ["stats", "retail-close", "--against", str(out)])
    assert result.exit_code == 0, result.output
    assert "metric" in result.output
    assert "retail-close" in result.output
    assert str(out) in result.output


def test_a_corpus_with_nothing_to_measure_is_a_clean_error(tmp_path: Path) -> None:
    out = tmp_path / "empty"
    World(company=_company()).export(out, overwrite=True)
    result = runner.invoke(app, ["stats", str(out)])
    assert result.exit_code == 2
    assert "nothing to compute statistics from" in result.output
