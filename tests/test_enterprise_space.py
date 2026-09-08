"""Sizing uses the same narrowed registry and ceiling as the planner."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom.cli import app
from worldloom.enterprise_queries import valid_rows
from worldloom.enterprise_specs import (
    ScenarioProfile,
    apply_scenario_profile,
    builtin_registry,
)

RUNNER = CliRunner()


def _profile(path: Path, **changes: object) -> ScenarioProfile:
    data = {
        "name": "incident-sizing",
        "industry": "retail",
        "company_description": "Retail service operations.",
        "connectors": ["servicenow", "confluence"],
        "workflows": ["incident_review"],
        "coverage": {"name": "bounded", "failures": ["none"], "max_candidates": 100_000},
        **changes,
    }
    profile = ScenarioProfile.model_validate(data)
    path.write_text(profile.model_dump_json(), encoding="utf-8")
    return profile


def test_profile_space_equals_the_planners_actual_candidates(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    profile = _profile(path)
    registry = apply_scenario_profile(builtin_registry(), profile)
    expected = sum(1 for _ in valid_rows(registry, profile.coverage))
    assert expected > 1

    result = RUNNER.invoke(app, ["enterprise-evals", "space", "--profile", str(path)])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "profile": "bounded",
        "scenario_profile": "incident-sizing",
        "valid_candidates": expected,
        "exhaustive": True,
    }


def test_profile_ceiling_is_used_and_cli_override_takes_precedence(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    _profile(path, coverage={"name": "small", "failures": ["none"], "max_candidates": 2})
    base = ["enterprise-evals", "space", "--profile", str(path)]

    result = RUNNER.invoke(app, base)
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "profile": "small", "scenario_profile": "incident-sizing",
        "valid_candidates": 3, "exhaustive": False, "at_least": 3,
    }

    result = RUNNER.invoke(app, [*base, "--max-candidates", "4"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["at_least"] == 5


def test_exact_ceiling_is_exhaustive(tmp_path: Path) -> None:
    path = tmp_path / "profile.json"
    profile = _profile(path)
    count = sum(1 for _ in valid_rows(apply_scenario_profile(builtin_registry(), profile), profile.coverage))
    result = RUNNER.invoke(app, [
        "enterprise-evals", "space", "--profile", str(path), "--max-candidates", str(count),
    ])
    assert result.exit_code == 0, result.output
    report = json.loads(result.output)
    assert report["exhaustive"] is True
    assert report["valid_candidates"] == count
    assert "at_least" not in report


@pytest.mark.parametrize("connectors, message", [
    (["servicenow", "confluenc"], "confluenc"),
    (["servicenow"], "no workflow survives"),
])
def test_bad_selections_refuse_instead_of_claiming_an_exhaustive_empty_space(
    tmp_path: Path, connectors: list[str], message: str,
) -> None:
    path = tmp_path / "profile.json"
    _profile(path, connectors=connectors)
    result = RUNNER.invoke(app, ["enterprise-evals", "space", "--profile", str(path)])
    assert result.exit_code != 0
    assert message in result.output
