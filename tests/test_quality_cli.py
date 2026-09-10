"""Public CLI payloads must preserve the core evidence and replay boundaries."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from typer.testing import CliRunner

from worldloom import MonthEndClose, RetailWorld, World
from worldloom.corpus import tree_divergence, write_json
from worldloom.eval_instances import EvalInstance, EvalOracle
from worldloom.eval_metrics import (
    CalibrationObservation,
    DifficultyCalibrator,
    feature_slice,
)
from worldloom.evals.difficulty import RequestFeatures
from worldloom.ids import content_key
from worldloom.narrative import handshake
from worldloom.narrative.providers import ResponseProvider
from worldloom.narrative.requests import GeneratedClaim, GeneratedNarrative
from worldloom.quality_cli import calibration_app, readers_app

runner = CliRunner()


def test_cli_verifies_mixed_author_noise_from_exact_ledger(tmp_path: Path) -> None:
    from dataclasses import replace

    from worldloom.cli import app
    from worldloom.evals.calibration import NoiseVariant, _noise_world
    from worldloom.narrative.providers import DeterministicProvider

    class OriginalAuthor(DeterministicProvider):
        id = "original-test-author/v1"

    baseline = RetailWorld(seed=8128).build().run(
        MonthEndClose(period="2026-03", include_operational_incident=True),
    ).narrate(OriginalAuthor())
    noisy = _noise_world(baseline, NoiseVariant(name="stale", budget={"staleness": 1}, niche="decayed"), ())
    identities = {ir.metadata.get("narrated_by") for ir in noisy.artifact_irs if ir.metadata.get("narrated_by")}
    assert "original-test-author/v1" in identities and len(identities) == 2
    corpus = noisy.export(tmp_path / "mixed-authors")
    result = runner.invoke(app, ["verify", str(corpus), "--json"])
    assert result.exit_code == 0, result.output
    from worldloom.narrative.compiler import ledger_key

    original = next(entry for entry in noisy.ledger if entry.model_id == "original-test-author/v1")
    other_id = next(identity for identity in identities if identity != original.model_id)
    conflicting = original.model_copy(update={
        "id": "GEN-99999", "model_id": other_id,
        "key": ledger_key(seed=noisy.seed, call_site=original.call_site, ordinal=original.ordinal,
                          fact_digest=original.input_facts_digest, model_id=other_id,
                          prompt_version=original.prompt_version),
    })
    replace(noisy, _ledger=(*noisy.ledger, conflicting)).export(corpus, overwrite=True)
    refused = runner.invoke(app, ["verify", str(corpus)], env={"WORLDLOOM_OUTPUT": "json"})
    assert refused.exit_code == 2, refused.output
    assert json.loads(refused.stderr)["refusal"] == "narration_failed"
    assert "ambiguous narration replay" in refused.stderr


@pytest.fixture(scope="module")
def authored() -> World:
    world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
    facts = {fact.id: fact for fact in world.facts}
    responses = {}
    for request in handshake.pending(world):
        sentences = [(fid, "Subject " + request.subjects.get(fid, facts[fid].subject)
                      + "; aspect " + facts[fid].kind + "; value {{fact:" + fid + "}}.")
                     for fid in request.allowed_fact_ids]
        responses[f"{request.artifact_id}/{request.section}"] = GeneratedNarrative(
            text="\n".join(sentence for _, sentence in sentences),
            claims=[GeneratedClaim(text=sentence, supporting_fact_ids=[fid]) for fid, sentence in sentences],
        )
    return world.narrate(ResponseProvider(responses, model_id="cli-test-author"))


def _targets(world: World) -> tuple[str, ...]:
    return tuple(next(section.fact_ids[:5] for ir in world.artifact_irs for section in ir.sections
                      if section.body and len(section.fact_ids) >= 5))


def _args(path: Path, world: World) -> list[str]:
    args = [str(path), "--reader-id", "blind-regex/v1", "--share", "0"]
    for fid in _targets(world):
        args.extend(["--critical-fact", fid])
    return args


def _replies(document: dict) -> list[dict]:
    """The scripted reader sees only request prose, never a World or answer key."""
    replies = []
    for request in document["requests"]:
        claims = []
        for line in request["text"].splitlines():
            found = re.fullmatch(r"Subject (.+); aspect ([^;]+); value (.+)\.", line)
            if found:
                subject, kind, value = found.groups()
                claims.append({"subject": subject, "kind": kind, "value": value, "quote": line})
        replies.append({key: request[key] for key in
                        ("id", "request_id", "text_digest", "reader_id", "contract_version")} | {"claims": claims})
    return replies


def test_reader_public_payload_accept_and_offline_replay(authored: World, tmp_path: Path) -> None:
    corpus = authored.export(tmp_path / "corpus")
    request_path = tmp_path / "public.json"
    result = runner.invoke(readers_app, ["requests", *_args(corpus, authored), "--out", str(request_path)])
    assert result.exit_code == 0, result.output
    wire = request_path.read_text()
    for forbidden in ("expected_value", "targets_digest", "critical_fact_ids", "{{fact:", *_targets(authored)):
        assert forbidden not in wire
    document = json.loads(wire)
    replies = tmp_path / "responses.json"
    write_json(replies, {"responses": _replies(document)})
    result = runner.invoke(readers_app, ["accept", *_args(corpus, authored), "--from", str(replies)])
    assert result.exit_code == 0, result.output
    review = json.loads(result.output)
    assert review["accepted"] and not review["replayed"]
    assert set(review["review"]["recovered_critical_fact_ids"]) == set(_targets(authored))
    accepted = World.load(corpus)
    assert any(entry.call_site == "narration.reader" for entry in accepted.ledger)
    before = accepted.export(tmp_path / "before")
    result = runner.invoke(readers_app, ["accept", *_args(corpus, authored)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["replayed"]
    assert tree_divergence(before, corpus) is None


def test_reader_config_and_eval_oracle_are_checker_inputs(authored: World, tmp_path: Path) -> None:
    corpus = authored.export(tmp_path / "corpus")
    instance = EvalInstance(
        id="reader-eval", spec_id="reader-design", candidate_seed=authored.seed or 0,
        design_digest="test", capability="read", persona="analyst", request="Read evidence",
        difficulty="medium", steps=(), assertions=(),
        oracle=EvalOracle(fact_ids=_targets(authored), evidence_by_requirement={}),
    )
    instance_path = tmp_path / "instance.json"
    config_path = tmp_path / "config.json"
    write_json(instance_path, instance.model_dump(mode="json"))
    write_json(config_path, {"prompt_version": "independent-private-config-v1"})
    args = [str(corpus), "--reader-id", "reader/v1", "--share", "0", "--eval-instance", str(instance_path),
            "--reader-config", str(config_path)]
    result = runner.invoke(readers_app, ["requests", *args])
    assert result.exit_code == 0, result.output
    assert "independent-private-config-v1" not in result.output
    assert "reader-eval" not in result.output
    assert all(fid not in result.output for fid in _targets(authored))
    replies = tmp_path / "responses.json"
    write_json(replies, {"responses": _replies(json.loads(result.output))})
    write_json(config_path, {"prompt_version": "changed-v2"})
    result = runner.invoke(readers_app, ["accept", *args, "--from", str(replies)], env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 3, result.output
    assert not json.loads(result.stdout)["accepted"]
    assert json.loads(result.stderr)["refusal"] == "reader_check_rejected"


@pytest.mark.parametrize("corruption", ["stale", "wrong_reader", "missing"])
def test_failed_reader_check_is_persisted(authored: World, tmp_path: Path, corruption: str) -> None:
    corpus = authored.export(tmp_path / "corpus")
    result = runner.invoke(readers_app, ["requests", *_args(corpus, authored)])
    assert result.exit_code == 0, result.output
    responses = _replies(json.loads(result.output))
    if corruption == "missing":
        responses = []
    elif corruption == "stale":
        responses[0]["text_digest"] = "stale"
    else:
        responses[0]["reader_id"] = "another-reader"
    replies = tmp_path / "responses.json"
    write_json(replies, {"responses": responses})
    result = runner.invoke(readers_app, ["accept", *_args(corpus, authored), "--from", str(replies)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 3, result.output
    report = json.loads(result.stdout)
    assert not report["accepted"]
    assert json.loads(result.stderr)["refusal"] == "reader_check_rejected"
    record = next(entry for entry in World.load(corpus).ledger if entry.call_site == "narration.reader")
    assert record.output["review"] == report["review"]
    assert not record.output["review"]["passed"]


def test_impossible_reader_targets_produce_no_public_request(authored: World, tmp_path: Path) -> None:
    corpus = authored.export(tmp_path / "corpus")
    out = tmp_path / "requests.json"
    result = runner.invoke(readers_app, ["requests", str(corpus), "--reader-id", "reader/v1", "--share", "0",
                                        "--critical-fact", "FACT-NONEXISTENT", "--out", str(out)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "reader_plan_rejected"
    assert not out.exists()


def _row(index: int, *, split: str = "train", density: float = 0.0) -> dict:
    return CalibrationObservation(
        cohort="baseline/v1", trial_id=f"trial-{index}", eval_id=f"eval-{index}",
        corpus_digest=content_key("corpus", index), evaluator_config_digest=content_key("baseline-config"),
        evaluator_kind="agent", passed=index % 2 == 0, split=split,
        features=feature_slice(RequestFeatures(evidence_kinds=1, facts_required=2, artifacts_required=1,
                                               distractor_density=density, unstated_slots=0)),
    ).model_dump(mode="json")


def test_snapshot_ingest_replay_and_holdout_denominators(tmp_path: Path) -> None:
    observations = [_row(i) for i in range(4)] + [_row(4, split="holdout"), _row(5, split="holdout", density=4)]
    source = tmp_path / "observations.jsonl"
    source.write_text("".join(json.dumps(row) + "\n" for row in observations))
    snapshot = tmp_path / "snapshot.json"
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(snapshot)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["added"] == 6
    before = snapshot.read_bytes()
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(snapshot), "--resume", str(snapshot)])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["replayed"] == 6
    assert json.loads(result.output)["added"] == 0
    assert snapshot.read_bytes() == before
    result = runner.invoke(calibration_app, ["report", str(snapshot), "--cohort", "baseline/v1", "--min-trials", "4"])
    assert result.exit_code == 0, result.output
    document = json.loads(result.output)
    assert {row["status"] for row in document["training_estimates"]} == {"fitted", "unfitted"}
    report = document["report"]
    assert (report["observations"], report["scored"], report["unsupported"]) == (2, 1, 1)
    assert report["brier_score"] == .25
    assert len(DifficultyCalibrator.load(snapshot).snapshot().observations) == 6


def test_snapshot_is_immutable_and_conflicting_replay_never_writes(tmp_path: Path) -> None:
    source, snapshot = tmp_path / "observations.json", tmp_path / "snapshot.json"
    write_json(source, {"observations": [_row(0)]})
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(snapshot)])
    assert result.exit_code == 0, result.output
    before = snapshot.read_bytes()
    write_json(source, {"observations": [_row(1)]})
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(snapshot), "--resume", str(snapshot)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "destination_exists"
    assert snapshot.read_bytes() == before
    write_json(source, {"observations": [_row(0) | {"passed": False}]})
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(tmp_path / "new.json"),
                                            "--resume", str(snapshot)], env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "calibration_rejected"
    assert not (tmp_path / "new.json").exists()
    assert snapshot.read_bytes() == before


@pytest.mark.parametrize("payload", ['{"observations": []}', '[NaN]', '[1e999]', '{"x": 1, "x": 2}', '"wrong shape"'])
def test_malformed_calibration_rows_refuse_without_output(tmp_path: Path, payload: str) -> None:
    source = tmp_path / "bad.json"
    source.write_text(payload)
    output = tmp_path / "snapshot.json"
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(output)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "unreadable_document"
    assert not output.exists()


def test_split_overlap_refuses_entire_batch(tmp_path: Path) -> None:
    source = tmp_path / "overlap.json"
    write_json(source, {"observations": [_row(0), _row(0, split="holdout") | {"trial_id": "another-trial"}]})
    output = tmp_path / "snapshot.json"
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(output)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "calibration_rejected"
    assert not output.exists()


def test_report_refuses_unknown_cohort_and_snapshot_overwrite(tmp_path: Path) -> None:
    source, snapshot = tmp_path / "observations.json", tmp_path / "snapshot.json"
    write_json(source, {"observations": [_row(0)]})
    result = runner.invoke(calibration_app, ["ingest", "--from", str(source), "--out", str(snapshot)])
    assert result.exit_code == 0, result.output
    before = snapshot.read_bytes()
    result = runner.invoke(calibration_app, ["report", str(snapshot), "--cohort", "unknown"],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "calibration_rejected"
    result = runner.invoke(calibration_app, ["report", str(snapshot), "--cohort", "baseline/v1", "--out", str(snapshot)],
                           env={"WORLDLOOM_OUTPUT": "json"})
    assert result.exit_code == 2, result.output
    assert json.loads(result.output)["refusal"] == "destination_exists"
    assert snapshot.read_bytes() == before


def test_top_level_routes_quality_commands() -> None:
    from worldloom.cli import app

    for path in (["narrate", "readers"], ["evals", "calibration"]):
        result = runner.invoke(app, [*path, "--help"])
        assert result.exit_code == 0, result.output
