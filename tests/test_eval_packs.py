"""Enterprise, agent-eval and evalrun prompts and policy come from packs, unchanged by default."""

from __future__ import annotations

import json
from importlib.resources import files
from pathlib import Path

import pytest

from worldloom import packkit


@pytest.fixture(autouse=True)
def _isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("WORLDLOOM_HOME", str(tmp_path / "home"))
    monkeypatch.delenv("WORLDLOOM_PACK_PATH", raising=False)
    packkit.refresh()
    yield
    packkit.refresh()


def _fragment(kind: str, name: str) -> dict:
    return json.loads(files("worldloom").joinpath("_data", "packs", kind, "default", f"{name}.json").read_text("utf-8"))


def _industry(root: Path, body: dict) -> None:
    path = root / "industry" / "evalco.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"schema": "worldloom.pack/v1", "kind": "industry", "name": "evalco", "body": body}))


@pytest.mark.parametrize("fragment", ["connectors", "enterprise", "evalrun"])
def test_every_shipped_prompt_key_resolves(fragment: str) -> None:
    for key, text in _fragment("prompts", fragment)["texts"].items():
        assert packkit.template(key) == text, key


@pytest.mark.parametrize("fragment", ["connectors", "evals"])
def test_every_shipped_policy_key_resolves(fragment: str) -> None:
    for key, value in _fragment("policy", fragment)["values"].items():
        assert packkit.policy(key) == value, key


def test_the_defaults_are_the_literals_they_replaced() -> None:
    from worldloom.enterprise_queries import ACTION_INSTRUCTIONS
    from worldloom.enterprise_specs import BUILTIN_WORKFLOWS
    from worldloom.evalrun.harness import (
        ExecAgent,
        response_instructions,
        turn_instructions,
    )
    from worldloom.evalrun.plans import plan_instructions
    from worldloom.evalrun.results import delta_band

    assert ACTION_INSTRUCTIONS["forward"] == "Forward the existing thread as a" and len(ACTION_INSTRUCTIONS) == 13
    assert BUILTIN_WORKFLOWS[0].prompt_template.startswith("Prepare the {period} {purpose} for {company}'s {audience}")
    assert [len(turn_instructions()), len(response_instructions()), len(plan_instructions())] == [7, 5, 5]
    assert turn_instructions()[0] == "You are the agent under test. Read `query`; act through `tools`; finish with an answer."
    assert plan_instructions()[-1].endswith("plan a read of the record before it.")
    assert ExecAgent("true").max_turns == 64 and delta_band() == 0.1


def test_an_industry_pack_rewords_the_request_and_moves_the_defaults(tmp_path: Path) -> None:
    from worldloom.enterprise_queries import ACTION_INSTRUCTIONS
    from worldloom.enterprise_specs import builtin_registry
    from worldloom.evalrun.harness import ExecAgent, turn_instructions
    from worldloom.evalrun.results import delta_band

    _industry(tmp_path, {
        "prompts": {"enterprise.action.create": "Open a fresh",
                    "enterprise.workflow.prompt": "For {company}: {action_instruction} {output_label} in {destination}.",
                    "evalrun.turn.rule.01": "You are the agent being graded."},
        "policy": {"evalrun.max_turns": 12, "evalrun.delta_band": 0.2},
    })
    with packkit.use("industry:evalco", roots=[tmp_path]):
        assert ACTION_INSTRUCTIONS["create"] == "Open a fresh"
        assert builtin_registry().workflows["incident_review"].prompt_template.startswith("For {company}:")
        assert turn_instructions()[0] == "You are the agent being graded."
        assert ExecAgent("true").max_turns == 12 and delta_band() == 0.2
    assert ACTION_INSTRUCTIONS["create"] == "Create a new"
    assert builtin_registry().workflows["incident_review"].prompt_template.startswith("Prepare the {period}")


def test_an_override_that_adds_a_placeholder_is_refused(tmp_path: Path) -> None:
    _industry(tmp_path, {"prompts": {"enterprise.source": "the {region} copy of {display} {format_label}"}})
    findings = packkit.lint(packkit.resolve("industry:evalco", roots=[tmp_path]), roots=[tmp_path])
    assert any("enterprise.source: introduces {region}" in finding for finding in findings)
