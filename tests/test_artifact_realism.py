from datetime import UTC, datetime

import pytest

from worldloom.artifact_realism import (
    ArtifactLifecycle,
    EvidenceGraph,
    EvidenceNode,
    artifact_style,
    department_dna,
    lifecycle_for,
    organization_dna,
)
from worldloom.models import Lifecycle


def test_organization_dna_is_stable_and_seed_sensitive() -> None:
    first = organization_dna(8128, "CO-0001")
    again = organization_dna(8128, "CO-0001")
    other = organization_dna(8129, "CO-0001")
    assert first == again
    assert first != other


def test_department_habits_are_correlated_but_not_global_mutation() -> None:
    org = organization_dna(8128, "CO-0001")
    finance = department_dna(8128, org, "Finance")
    finance_again = department_dna(8128, org, "Finance")
    operations = department_dna(8128, org, "Operations")
    assert finance == finance_again
    assert finance.organization_id == operations.organization_id == org.id
    assert finance.revision_formality == "controlled"


def test_artifact_style_is_addressed_by_artifact_key() -> None:
    org = organization_dna(8128, "CO-0001")
    team = department_dna(8128, org, "Finance")
    memo = artifact_style(8128, team, "ART-0001")
    memo_again = artifact_style(8128, team, "ART-0001")
    deck = artifact_style(8128, team, "ART-0002")
    assert memo == memo_again
    assert memo.organization_id == deck.organization_id
    assert memo.department == deck.department
    assert 2 <= memo.information_blocks <= 12


def test_lifecycle_uses_simulated_time_and_is_chronological() -> None:
    created = datetime(2026, 3, 4, 9, tzinfo=UTC)
    lifecycle = lifecycle_for(
        "ART-0001", created, author_id="PERSON-0001", reviewer_id="PERSON-0002"
    )
    assert [step.state for step in lifecycle.steps] == [
        Lifecycle.DRAFT,
        Lifecycle.REVIEWED,
        Lifecycle.APPROVED,
        Lifecycle.PUBLISHED,
    ]
    assert lifecycle.steps[0].at == created
    assert lifecycle.steps[-1].at > created


def test_lifecycle_refuses_time_travel() -> None:
    now = datetime(2026, 3, 4, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="chronological"):
        ArtifactLifecycle(
            artifact_id="ART-0001",
            revision=1,
            steps=(
                {"state": "published", "at": now},
                {"state": "draft", "at": now.replace(hour=8)},
            ),
        )


def test_evidence_graph_refuses_dangling_cross_surface_reference() -> None:
    at = datetime(2026, 3, 4, 9, tzinfo=UTC)
    with pytest.raises(ValueError, match="missing nodes"):
        EvidenceGraph(
            nodes=(
                EvidenceNode(
                    id="EVID-A",
                    episode_id="EV-0001",
                    surface="email",
                    external_id="<a@example>",
                    occurred_at=at,
                    references=("EVID-MISSING",),
                ),
            )
        )


def test_evidence_graph_accepts_cross_surface_episode_chain() -> None:
    at = datetime(2026, 3, 4, 9, tzinfo=UTC)
    snow = EvidenceNode(
        id="EVID-SNOW",
        episode_id="EV-0001",
        surface="servicenow",
        external_id="INC0000001",
        occurred_at=at,
        fact_ids=("FACT-0001",),
    )
    email = EvidenceNode(
        id="EVID-EMAIL",
        episode_id="EV-0001",
        surface="email",
        external_id="<a@example>",
        occurred_at=at.replace(hour=10),
        fact_ids=("FACT-0001",),
        references=(snow.id,),
    )
    graph = EvidenceGraph(nodes=(snow, email))
    assert graph.nodes[1].references == ("EVID-SNOW",)
