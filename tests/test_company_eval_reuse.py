from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import locales, sdk
from worldloom.cli import app
from worldloom.corpus import tree_divergence, write_json
from worldloom.evals import (
    EvalCampaign,
    EvalSpec,
    EvalStepSpec,
    RequirementKind,
    WorldRequirement,
    candidate_builder,
    emulator_executor,
)
from worldloom.narrative.providers import DeterministicProvider, UnreachableProvider
from worldloom.pipeline import Pipeline, Stage, standard_pipeline
from worldloom.recipe import locale_of, rebuild
from worldloom.world import World


def design() -> EvalSpec:
    return EvalSpec(
        id="company-campaign-reuse",
        capability="incident_retrieval",
        persona="operations manager",
        request_template="Find the incident requiring a review.",
        steps=(EvalStepSpec(id="find", capability="search", connector="servicenow",
                            entity="incident", operation="search"),),
        requirements=(
            WorldRequirement(id="facts", kind=RequirementKind.FACT),
            WorldRequirement(id="incident", kind=RequirementKind.CONNECTOR,
                             selector={"connector": "servicenow", "entity": "incident",
                                       "priority": "1", "state": "New"}),
        ),
        candidate_count=1,
    )


@pytest.mark.parametrize("engine,geo", [("retail", "germany"), ("banking", "united_kingdom")])
def test_company_campaign_authors_once_then_exports_and_replays(
    engine: str, geo: str, tmp_path: Path,
) -> None:
    campaign = EvalCampaign(design())
    blueprint = sdk.described({"engine": engine, "geo": geo})
    builder = candidate_builder(blueprint, standard_pipeline(
        "2026-03", compile_artifacts=False, validate=False,
    ))
    seeds: list[int] = []

    def once(plan):  # type: ignore[no-untyped-def]
        seeds.append(plan.seed)
        return builder(plan)

    run = campaign.construct(once)
    assert len(run.accepted) == 1
    provider = DeterministicProvider()
    final = run.map_worlds(lambda world: world.narrate(provider).render("markdown"))
    calls = provider.calls
    assert calls > 0
    assert locale_of(final.attempts[0].world.recipe) == locales.named(geo)
    assert final.prove(emulator_executor())[0].status.value == "proven_executable"
    root = final.export(tmp_path / "campaign")
    assert seeds == [campaign.plans()[0].seed]
    assert provider.calls == calls

    manifest = json.loads((root / "manifest.json").read_text())
    corpus = root / manifest["candidates"][0]["path"] / "corpus"
    loaded = World.load(corpus)
    replay = rebuild(loaded.recipe, ledger=loaded.ledger).narrate(
        UnreachableProvider(), ledger=loaded.ledger,
    ).render("markdown")
    assert replay._narration[0] == 0
    assert tree_divergence(corpus, replay.export(tmp_path / "replay")) is None


def test_builder_is_lazy_and_rejects_export_or_changed_seed() -> None:
    blueprint = sdk.retail()
    plan = EvalCampaign(design()).plans()[0]
    exported = candidate_builder(blueprint, Pipeline((Stage(
        name="bad-export", seam="test", runner=lambda _value, _context: Path("exported"),
    ),)))
    with pytest.raises(TypeError, match="Built or World"):
        exported(plan)
    changed = candidate_builder(blueprint, Pipeline((Stage(
        name="bad-seed", seam="test", runner=lambda _value, _context: sdk.retail(seed=7).build().world,
    ),)))
    with pytest.raises(ValueError, match="planned seed"):
        changed(plan)


def test_cli_resolves_company_and_preserves_interview_findings(tmp_path: Path) -> None:
    spec_path = tmp_path / "design.json"
    company_path = tmp_path / "company.json"
    write_json(spec_path, design().model_dump(mode="json"))
    write_json(company_path, {"engine": "banking", "geo": "united_kingdom"})
    destination = tmp_path / "campaign"
    result = CliRunner().invoke(app, ["evals", "construct", str(spec_path),
        "--company-spec", str(company_path), "--periods", "2", "--out", str(destination), "--json"])
    assert result.exit_code == 0, result.output
    manifest = json.loads(result.output)
    resolution = json.loads((destination / manifest["company_resolution"]).read_text())
    assert resolution["engine"] == "banking"
    assert resolution["unmet"]  # Unsupported seasonality is a finding, never dropped.
    corpus = destination / manifest["candidates"][0]["path"] / "corpus"
    loaded = World.load(corpus)
    assert [(step["scenario"], step["period"]) for step in loaded.recipe["steps"]
            if step.get("period")] == [
                ("QuarterlyCapitalReturn", "2026-03"),
                ("QuarterlyCapitalReturn", "2026-06"),
            ]
    conflict = CliRunner().invoke(app, ["evals", "construct", str(spec_path),
        "--company-spec", str(company_path), "--archetype", "omnichannel_retailer",
        "--out", str(tmp_path / "refused"), "--json"])
    assert conflict.exit_code != 0
    assert "both describe the base company" in conflict.output
    assert not (tmp_path / "refused").exists()


def test_cli_refuses_unsupported_history_before_building(tmp_path: Path) -> None:
    spec_path = tmp_path / "design.json"
    company_path = tmp_path / "company.json"
    write_json(spec_path, design().model_dump(mode="json"))
    write_json(company_path, {"engine": "insurance"})
    destination = tmp_path / "refused"
    result = CliRunner().invoke(app, ["evals", "construct", str(spec_path),
        "--company-spec", str(company_path), "--periods", "2", "--out", str(destination)],
        env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert "period_cap" in result.output
    assert not destination.exists()
