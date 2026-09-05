"""Source parity, honest evidence, stable compilation and authoring integration."""
from __future__ import annotations

import gzip
import hashlib
import json
import os
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from worldloom.process_planning import (
    Catalogue,
    CompanyProcessSpec,
    authoring_context,
    compile_company,
    default_company,
    export_compilations,
    load_catalogue,
    replay_plan,
    to_lexicon,
)
from worldloom.process_planning.models import Activity

DATA = files("worldloom").joinpath("_data", "processes")
AUDIT = json.loads(DATA.joinpath("intake.json").read_text(encoding="utf-8"))
INDUSTRIES = tuple(sorted(load_catalogue().industry_overlays))
PROJECTION = (
    "activity_id", "stream", "stream_name", "activity", "apqc", "function", "owner_kind", "owner_bu",
    "bu_archetype", "country", "sor_class", "sor_product", "type", "control", "exception", "variant", "eval_templates",
)


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_original_archive_structure_is_preserved(industry: str) -> None:
    plan = compile_company(default_company(industry))
    reference = AUDIT["reference_outputs"][f"default-{industry}.jsonl"]
    rows = []
    for row in plan.activities:
        data = row.model_dump(mode="json")
        data["apqc"] = data["apqc_hint"]
        rows.append({k: data[k] for k in PROJECTION})
    rows.sort(key=lambda r: (r["stream"], r["activity_id"], r["owner_bu"], r["country"]))
    fingerprint = hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()
    assert fingerprint == reference["structural_sha256"]
    assert len(rows) == reference["rows"]
    assert len({a.id for a in plan.activities}) == len(rows)
    assert plan.summary["calibrated_streams"] == plan.summary["executable_evals"] == 0
    assert all(not r.apqc_verified and not r.control_evaluable for r in plan.activities)
    assert plan.summary["distinct_activities"] == reference["distinct_activities"]


def test_source_bytes_and_coverage_are_attested() -> None:
    assert hashlib.sha256(gzip.decompress(DATA.joinpath("catalogue.json.gz").read_bytes())).hexdigest() == AUDIT["inputs"]["catalogue.json"]["sha256"]
    assert AUDIT["source_activity_instances"] == 6975
    assert AUDIT["source_industry_stream_cells"] == 215
    assert AUDIT["source_legacy_calibrated_claims"] == 63
    assert len(AUDIT["inputs"]) == 5
    for industry in INDUSTRIES:
        plan = compile_company(default_company(industry))
        by_stream = {r.stream: r for r in plan.coverage if r.status != "missing"}
        for legacy in AUDIT["legacy_coverage"]:
            if legacy["industry"] == industry:
                cell = by_stream[legacy["stream"]]
                assert cell.activities == int(legacy["activities"])
                assert bool(cell.calibration_requested) == (legacy["status"] == "corpus_calibrated")
                assert not cell.calibration_applied


def test_missing_utility_stream_is_not_borrowed_from_telecom() -> None:
    plan = compile_company(default_company("utilities"))
    assert plan.summary["missing_streams"] == ["usage_to_bill"]
    assert not any(r.stream == "usage_to_bill" for r in plan.activities)
    with pytest.raises(ValueError, match="missing_core_stream"):
        compile_company(default_company("utilities"), strict=True)
    with pytest.raises(ValueError, match="unknown explicit stream"):
        compile_company(default_company("utilities").model_copy(update={"streams": ("usage_to_bill",)}))


@pytest.mark.parametrize("column,value,message", [
    ("industry", "not_an_industry", "unknown industry"),
    ("operating_model", "typo", "unknown operating model"),
    ("countries", ("ZZ",), "unknown country"),
])
def test_unknown_dimensions_are_refused(column: str, value: object, message: str) -> None:
    spec = default_company("retail").model_dump(mode="json")
    spec[column] = value
    with pytest.raises(ValueError, match=message):
        compile_company(spec)


@pytest.mark.parametrize("bad", [[], ["x"] * 8, ["x"] * 10])
def test_activity_shape_is_not_silently_truncated(bad: list[str]) -> None:
    with pytest.raises(ValueError, match="exactly nine"):
        Activity.model_validate(bad)


@pytest.mark.parametrize("value", [-0.1, 1.1, float("nan"), float("inf")])
def test_invalid_channel_probability_is_refused(value: float) -> None:
    cat = load_catalogue().model_dump(mode="json")
    cat["channel_priors"]["capture"]["email"] = value
    with pytest.raises(ValueError):
        Catalogue.model_validate(cat)


def test_duplicate_and_unknown_function_references_are_refused() -> None:
    raw = load_catalogue().model_dump(mode="json")
    raw["operating_models"]["centralised"]["BU"].append("treasury")
    with pytest.raises(ValueError, match="exactly one owner"):
        Catalogue.model_validate(raw)
    raw = load_catalogue().model_dump(mode="json")
    raw["value_streams"]["lead_to_order"]["activities"][0]["function"] = "invented"
    with pytest.raises(ValueError, match="unknown function"):
        Catalogue.model_validate(raw)


def test_country_scopes_owner_overrides_and_fallback_diagnostics() -> None:
    spec = default_company("retail").model_dump(mode="json")
    spec["streams"] = ["record_to_report"]
    spec["bus"][3]["countries"] = ["AU"]
    plan = compile_company(spec)
    assert not any(r.owner_bu == "Group Finance" and r.country == "NZ" for r in plan.activities)
    assert any(d.code == "owner_fallback" and d.location.endswith("/NZ") for d in plan.diagnostics)
    spec["owner_overrides"] = {"treasury": ["Group Finance"]}
    plan = compile_company(spec)
    assert any(d.code == "unbound_owner" and d.location.endswith("/NZ") for d in plan.diagnostics)
    assert all(r.owner_binding == "override" for r in plan.activities if r.function == "treasury")
    with pytest.raises(ValueError, match="unknown unit"):
        CompanyProcessSpec.model_validate({**spec, "owner_overrides": {"treasury": ["imaginary"]}})


def test_system_objects_and_workflow_objects_are_separate() -> None:
    plan = compile_company(default_company("retail"))
    lead = next(r for r in plan.activities if r.activity_id == "l2o.01")
    assert "Lead" in lead.process_objects
    assert "Case" not in lead.process_objects and "Case" in lead.sor_objects
    minutes = next(r for r in plan.activities if r.sor_class == "Minutes")
    assert minutes.sor_schema_class == "Wiki" and minutes.sor_binding == "aliased"
    portal = compile_company(default_company("public_sector"))
    assert any(r.sor_class == "portal" and r.sor_binding == "unresolved_schema" for r in portal.activities)
    bad = default_company("retail").model_copy(update={"landscape": {"CRM": "Not Salesforce"}})
    with pytest.raises(ValueError, match="unregistered_product"):
        compile_company(bad, strict=True)


def test_channels_are_independent_probabilities_and_stable_by_identity() -> None:
    spec = default_company("retail")
    first = compile_company(spec)
    assert first == compile_company(spec)
    subset = compile_company(spec.model_copy(update={"streams": ("lead_to_order",)}))
    expected = {r.id: r.channels for r in first.activities if r.stream == "lead_to_order"}
    assert {r.id: r.channels for r in subset.activities} == expected
    alternative = compile_company(spec.model_copy(update={"seed": 73}))
    assert [r.id for r in alternative.activities] == [r.id for r in first.activities]
    assert [r.channels for r in alternative.activities] != [r.channels for r in first.activities]
    assert any(sum(r.channel_probabilities.values()) > 1 for r in first.activities)
    for row in first.activities:
        assert all(c in row.channels for c, p in row.channel_probabilities.items() if p == 1)
    # Inserting an unrelated channel leaves the existing channel decisions alone.
    cat = load_catalogue().model_dump(mode="json")
    cat["channel_priors"]["capture"]["minutes"] = 0.3
    extended = compile_company(spec, Catalogue.model_validate(cat))
    assert {r.id: tuple(c for c in r.channels if c != "minutes") for r in extended.activities if r.type == "capture"} == {
        r.id: r.channels for r in first.activities if r.type == "capture"
    }


def test_lexicon_does_not_collapse_unverified_apqc_hints() -> None:
    plan = compile_company(default_company("banking"))
    records = to_lexicon(plan)
    assert len(records) == plan.summary["distinct_activities"]
    assert len({r.concept for r in records}) == len(records)
    assert all(r.evidence.value == "authored_prior" for r in records)
    assert all(not r.concept.startswith("apqc:") for r in records)


def test_budget_is_enforced_and_core_selection_is_opt_in() -> None:
    with pytest.raises(ValueError, match="budget exceeded"):
        compile_company(default_company("retail"), max_instances=10)
    full = compile_company(default_company("retail"))
    core = compile_company(default_company("retail"), core_only=True)
    assert len(core.activities) < len(full.activities)
    assert all(r.core for r in core.activities)
    with pytest.raises(ValueError, match="context budget"):
        authoring_context(full, "lead_to_order", max_instances=1)


@pytest.mark.parametrize("core_only", [False, True])
def test_export_replay_uses_pinned_inputs_and_matches_bytes(tmp_path: Path, core_only: bool) -> None:
    first = compile_company(default_company("retail"), core_only=core_only)
    export_compilations([first], tmp_path / "first")
    replayed = replay_plan(tmp_path / "first/default-retail.plan.json")
    assert replayed == first
    export_compilations([replayed], tmp_path / "replay")
    one = {p.name: p.read_bytes() for p in (tmp_path / "first").iterdir()}
    two = {p.name: p.read_bytes() for p in (tmp_path / "replay").iterdir()}
    assert one == two
    manifest = json.loads(one["manifest.json"])
    assert manifest["files"] == {n: hashlib.sha256(b).hexdigest() for n, b in one.items() if n != "manifest.json"}
    assert "licenses.json" in manifest["files"]
    with pytest.raises(ValueError, match="empty directory"):
        export_compilations([first], tmp_path / "first")
    pinned = tmp_path / f"first/catalogue-{first.catalogue_sha256}.json"
    raw = json.loads(pinned.read_text())
    raw["meta"]["note"] = "tampered"
    pinned.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="digest mismatch"):
        replay_plan(tmp_path / "first/default-retail.plan.json")


def test_replay_refuses_path_traversal(tmp_path: Path) -> None:
    plan = compile_company(default_company("retail"))
    export_compilations([plan], tmp_path / "export")
    path = tmp_path / "export/default-retail.plan.json"
    raw = json.loads(path.read_text())
    raw["catalogue_file"] = "../../catalogue.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="filename must match"):
        replay_plan(path)


def test_no_silent_filename_collisions(tmp_path: Path) -> None:
    spec = default_company("retail")
    one = compile_company(spec.model_copy(update={"name": "A/B"}))
    two = compile_company(spec.model_copy(update={"name": "A B"}))
    with pytest.raises(ValueError, match="collide"):
        export_compilations([one, two], tmp_path / "collision")
    assert not (tmp_path / "collision").exists()


def test_fresh_processes_replay_without_cwd_or_python_hash_seed_dependency(tmp_path: Path) -> None:
    source = str(Path(__file__).resolve().parents[1] / "src")
    for seed in ("1", "987654"):
        env = {**os.environ, "PYTHONPATH": source, "PYTHONHASHSEED": seed}
        completed = subprocess.run(
            [sys.executable, "-m", "worldloom.process_planning", "--industry", "retail", "--out", str(tmp_path / seed)],
            cwd=tmp_path, env=env, text=True, capture_output=True, check=False,
        )
        assert completed.returncode == 0, completed.stderr
    assert {p.name: p.read_bytes() for p in (tmp_path / "1").iterdir()} == {
        p.name: p.read_bytes() for p in (tmp_path / "987654").iterdir()
    }


def test_catalogue_context_survives_existing_authoring_gates() -> None:
    from worldloom import process
    from worldloom.episodes import EventSpec, FactKindSpec, Invariant

    plan = compile_company(default_company("retail"))
    session = process.open_from_catalogue(plan, "hire_to_retire", engine="retail", lob="hr")
    first = process.next_stage(session)
    source = first.context["process_catalogue"]
    assert source["activities"][0]["name"] == "Raise job requisition"
    source["activities"].clear()
    assert process.next_stage(session).context["process_catalogue"]["activities"]
    with pytest.raises(ValueError):
        process.accept(session, process.Answer(stage="steps", steps=[EventSpec(
            kind="hr.fake", when="start", summary="Bad kind.", fact_keys=["made.up"],
        )]))
    assert process.next_stage(session).stage == "steps"
    accepted = process.accept(session, process.Answer(stage="steps", steps=[EventSpec(
        kind="hr.joiner_recorded", when="start", summary="The joiner is recorded.", fact_keys=["org.joined"],
    )], kinds=[FactKindSpec(kind="org.joined", value_type="text", text="Recorded start for {period}.",
                          invariants=[Invariant(kind="holds-at")])]))
    assert process.next_stage(accepted).context["process_catalogue"] == process.next_stage(session).context["process_catalogue"]
    ready = process.accept(accepted, process.Answer(stage="slots"))
    resolved = process.resolve(ready)
    assert resolved.name == "HireToRetire"
    assert process.next_stage(ready).context["process_catalogue"]["activities"]
    ordinary = process.open(process.ProcessSeed(name="Example", purpose="Test", engine="retail", lob="hr"))
    assert "process_catalogue" not in process.next_stage(ordinary).context
    with pytest.raises(ValueError, match="not a registered domain"):
        process.open_from_catalogue(plan, "hire_to_retire", engine="nonexistent", lob="hr")
