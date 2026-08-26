from __future__ import annotations

import itertools

from worldloom.enterprise_queries import constrained_cover, valid_rows
from worldloom.enterprise_specs import (
    CoverageProfile,
    builtin_registry,
    canonical_action,
)


def test_modify_is_explicitly_canonicalized() -> None:
    assert canonical_action("modify") == "update"
    assert canonical_action("modify", content=True) == "transform"


def test_valid_rows_respect_workflow_connector_contracts() -> None:
    rows = list(itertools.islice(valid_rows(builtin_registry(), CoverageProfile()), 1_000))
    assert rows
    for row in rows:
        workflow = builtin_registry().workflows[row["workflow"]]
        assert row["destination"] in {destination.connector for destination in workflow.destinations}
        assert set(row["source_set"].split("+")) <= {source.connector for source in workflow.sources}


def test_constrained_cover_proves_coverage_over_valid_rows() -> None:
    rows = (
        {"a": "1", "b": "1", "c": "1"},
        {"a": "1", "b": "2", "c": "2"},
        {"a": "2", "b": "1", "c": "2"},
        {"a": "2", "b": "2", "c": "1"},
    )
    selected, report = constrained_cover(rows, 2)
    assert selected
    assert report.complete
    assert report.covered_interactions == report.required_interactions
