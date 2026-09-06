from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

import pytest
from pydantic import ValidationError

from worldloom.predicates import Predicate
from worldloom.process_bindings import (
    CompanySpec,
    authoring_brief,
    baseline_parity,
    compile_company,
    default_company,
    demands,
    lexicon_records,
    load_catalogue,
    replay_builtin,
    sample_channels,
    summary,
    tool_surface,
    verify_export,
    verify_ownership,
    write_compilation,
)
from worldloom.process_bindings.__main__ import main
from worldloom.process_bindings.compiler import fingerprint, resource

INDUSTRIES = tuple(sorted(resource("defaults.json")["DEFAULT_ORGS"]))


@pytest.mark.parametrize("industry", INDUSTRIES)
def test_all_uploaded_baselines_reproduce(industry: str) -> None:
    compiled = compile_company(default_company(industry))
    baseline = resource("bindings-provenance.json")["compiled_baselines"][f"default-{industry}.jsonl"]
    assert len(compiled.rows) == baseline["rows"]
    assert baseline_parity(compiled)
    assert replay_builtin(compiled)
    assert all(r.evidence == "authored_prior" and r.pcf_status == "unverified_hint" for r in compiled.rows)
    assert all(c.calibration_status != "calibrated" for c in compiled.coverage)
    assert len({r.id for r in compiled.rows}) == len(compiled.rows)
    assert all(r.id.startswith("PCA-") for r in compiled.rows)


def test_all_uploaded_coverage_cells_reproduced_but_claims_not_promoted() -> None:
    baseline = resource("bindings-provenance.json")["source_coverage"]
    actual = {(c.industry,c.stream):c for i in INDUSTRIES for c in compile_company(default_company(i)).coverage}
    assert len(baseline) == 215
    assert len(actual) == 216
    for row in baseline:
        current = actual[row["industry"],row["stream"]]
        assert current.activities == int(row["activities"])
        if row["status"] == "corpus_calibrated":
            assert current.calibration_status == "unresolved"
            assert current.calibration_targets
    assert actual["utilities","usage_to_bill"].status == "missing_definition"


def test_source_totals() -> None:
    compiled = [compile_company(default_company(i)) for i in INDUSTRIES]
    assert sum(len(c.rows) for c in compiled) == 6975
    assert sum(summary(c)["template_demands"] for c in compiled) == 55800
    assert all(summary(c)["measured_calibrations"] == 0 for c in compiled)


def test_no_cross_industry_borrowing_or_false_strict_success() -> None:
    compiled = compile_company(default_company("utilities"))
    assert not compiled.select(stream="usage_to_bill")
    assert any(f.code == "missing_core_stream" for f in compiled.findings)
    assert not compiled.ready
    with pytest.raises(ValueError, match="missing_core_stream"):
        compiled.require_ready()
    with pytest.raises(ValueError, match="missing_core_stream"):
        compile_company(default_company("utilities"),strict=True)


def test_core_only_excludes_universal_manufacturing_for_bank() -> None:
    compiled = compile_company(default_company("banking"),core_only=True)
    assert not compiled.select(stream="plan_to_produce")
    assert compiled.select(stream="apply_to_disburse")
    assert all(r.core for r in compiled.rows)


def test_unknown_system_objects_and_owner_fallbacks_are_explicit() -> None:
    compiled = compile_company(default_company("consumer_products"))
    assert compiled.select(owner_resolution="fallback")
    assert compiled.select(sor_class="Minutes",binding_status="unknown_class")
    assert compiled.select(sor_class="P2P-suite",binding_status="objects_unspecified")
    spec = default_company("retail").model_dump(mode="json")
    spec["landscape"] = {"CRM":"Invented CRM"}
    custom = compile_company(spec)
    assert custom.select(sor_class="CRM",binding_status="unknown_product")


def test_ownership_rule_ambiguity_is_not_hidden() -> None:
    spec = default_company("retail").model_dump(mode="json")
    spec["bus"].append({"name":"Second SSC","archetype":"shared_service_centre"})
    compiled = compile_company(spec)
    assert compiled.select(owner_resolution="ambiguous")
    assert any(f.code == "owner_ambiguous" and f.severity == "error" for f in compiled.findings)


def test_country_footprints_do_not_cartesian_expand_absent_operations() -> None:
    spec = default_company("retail").model_dump(mode="json")
    spec["bus"][0]["countries"] = ["AU"]
    compiled = compile_company(spec)
    assert compiled.select(owner_bu="Supermarkets",country="AU")
    assert not compiled.select(owner_bu="Supermarkets",country="NZ")


@pytest.mark.parametrize("change,match", [
    ({"countries":["XX"]},"unknown countries"),
    ({"industry":"mars"},"unknown industry"),
    ({"landscape":{"CRN":"typo"}},"unknown landscape"),
    ({"countries":["AU","AU"]},"duplicate country"),
])
def test_invalid_scope_is_refused(change: dict, match: str) -> None:
    spec = {**default_company("retail").model_dump(mode="json"),**change}
    with pytest.raises(ValueError, match=match):
        compile_company(spec)


def test_duplicate_business_units_and_invalid_footprints_rejected() -> None:
    spec = default_company("retail").model_dump(mode="json")
    spec["bus"].append(spec["bus"][0])
    with pytest.raises(ValidationError,match="duplicate business-unit"):
        CompanySpec.model_validate(spec)
    spec["bus"].pop()
    spec["bus"][0]["countries"] = ["JP"]
    with pytest.raises(ValidationError,match="outside company footprint"):
        CompanySpec.model_validate(spec)


@pytest.mark.parametrize("problem", ["arity","duplicate","function","tag","nan","template"])
def test_malformed_catalogue_refused(problem: str) -> None:
    cat = load_catalogue()
    activities = cat["value_streams"]["order_to_cash"]["activities"]
    if problem == "arity":
        activities[0].append("extra")
    elif problem == "duplicate":
        activities[1][0] = activities[0][0]
    elif problem == "function":
        activities[0][3] = "not_a_function"
    elif problem == "tag":
        activities[0][-1] = ["unknown_tag"]
    elif problem == "nan":
        cat["channel_priors"]["capture"]["email"] = float("nan")
    else:
        cat["eval_templates"].append(cat["eval_templates"][0])
    with pytest.raises(ValueError):
        compile_company(default_company("retail"),catalogue=cat)


def test_instance_budget_rejects_before_export(tmp_path: Path) -> None:
    with pytest.raises(ValueError,match="budget"):
        compile_company(default_company("retail"),max_instances=10)
    assert main(["--all","--out",str(tmp_path/"export"),"--max-instances","10"]) == 2
    assert not (tmp_path/"export").exists()


def test_json_mapping_order_does_not_change_output() -> None:
    cat = load_catalogue()
    reordered = {key:cat[key] for key in reversed(cat)}
    assert compile_company(default_company("retail"),catalogue=cat) == compile_company(default_company("retail"),catalogue=reordered)


def test_seeded_channel_presence_and_authored_lexicon() -> None:
    compiled = compile_company(default_company("retail"))
    row = compiled.select(activity_id="o2c.01")[0]
    assert sample_channels(row,seed=10) == sample_channels(row,seed=10)
    assert all("system_record" in sample_channels(row,seed=s) for s in range(20))
    assert len({sample_channels(row,seed=s) for s in range(30)}) > 1
    records = lexicon_records(compiled)
    assert len(records) == 146
    assert sum(r.weight for r in records) == pytest.approx(1)
    assert all(not r.concept.startswith("apqc:") for r in records)
    shared_hint = [r for r in compiled.rows if r.apqc == "9.2.3"]
    assert len({r.activity_id for r in shared_hint}) > 1
    assert all(r.evidence.value == "authored_prior" for r in records)


@pytest.mark.parametrize("industry",INDUSTRIES)
def test_shared_tool_search_and_structural_oracle(industry: str) -> None:
    compiled = compile_company(default_company(industry))
    demand = next(d for d in demands(compiled) if d.status == "bound_structural")
    assert verify_ownership(compiled,demand)
    surface = tool_surface(compiled)
    predicate = Predicate.equalities({"activity_id":compiled.rows[0].activity_id})
    actual = surface.fork().search("process_catalogue","activity_binding",predicate=predicate)
    assert {r.id for r in actual.records} == {r.id for r in compiled.select(activity_id=compiled.rows[0].activity_id)}
    with pytest.raises(ValueError,match="does not support"):
        surface.fork().update("process_catalogue","activity_binding",demand.binding_id,fields={"owner_bu":"fake"})


def test_unknown_selector_fields_do_not_silently_return_empty() -> None:
    with pytest.raises(ValueError,match="unknown activity-binding"):
        compile_company(default_company("retail")).select(ower_bu="typo")


def test_template_intents_do_not_claim_execution() -> None:
    compiled = compile_company(default_company("retail"))
    all_demands = tuple(demands(compiled))
    assert len(all_demands) == len(compiled.rows) * 8
    assert all(d.status == "requires_runtime" and d.expected_json is None for d in all_demands if d.template_id != "ownership")
    unresolved = next(d for d in all_demands if d.status == "binding_unresolved")
    assert not verify_ownership(compiled,unresolved)
    real = next(d for d in all_demands if d.status == "bound_structural")
    assert not verify_ownership(compiled,real.model_copy(update={"expected_json":"{}"}))
    other = compile_company(default_company("retail",name="Other retailer"))
    assert not verify_ownership(other,real)


def test_authoring_brief_is_stream_scoped_and_carries_evidence_boundaries() -> None:
    compiled = compile_company(default_company("banking"))
    brief = authoring_brief(compiled,stream="apply_to_disburse")
    assert brief.stage == "steps"
    assert brief.context["compilation_digest"] == compiled.digest
    assert all(r["stream"] == "apply_to_disburse" for r in brief.context["activities"])
    assert brief.context["evidence"] == "authored_prior"
    with pytest.raises(ValueError,match="no compiled definition"):
        authoring_brief(compiled,stream="imaginary")


def test_export_replays_and_refuses_to_clobber(tmp_path: Path) -> None:
    compiled = compile_company(default_company("retail"))
    first, second = tmp_path/"a",tmp_path/"b"
    write_compilation(compiled,first)
    write_compilation(compiled,second)
    assert verify_export(first) == compiled
    assert {p.name:p.read_bytes() for p in first.iterdir()} == {p.name:p.read_bytes() for p in second.iterdir()}
    with pytest.raises(FileExistsError):
        write_compilation(compiled,first)
    assert main(["--verify",str(first)]) == 0


def test_export_rejects_tampering_even_with_updated_manifest(tmp_path: Path) -> None:
    compiled = compile_company(default_company("retail"))
    out = tmp_path/"export"
    write_compilation(compiled,out)
    ledger = out/"demands.jsonl"
    ledger.write_text("{}\n")
    with pytest.raises(ValueError,match="checksum"):
        verify_export(out)
    manifest = json.loads((out/"manifest.json").read_text())
    manifest["files"][ledger.name] = hashlib.sha256(ledger.read_bytes()).hexdigest()
    (out/"manifest.json").write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match="projection"):
        verify_export(out)


def test_cli_all_and_unsafe_company_name(tmp_path: Path) -> None:
    out = tmp_path/"compiled"
    assert main(["--all","--out",str(out)]) == 0
    report = json.loads((out/"coverage.json").read_text())
    assert len(report["summary"]) == 12
    assert sum(r["activity_instances"] for r in report["summary"]) == 6975
    assert main(["--all","--out",str(out)]) == 2
    spec = default_company("retail",name="../../escape")
    (tmp_path/"spec.json").write_text(spec.model_dump_json())
    assert main(["--spec",str(tmp_path/"spec.json"),"--out",str(tmp_path/"custom")]) == 0
    assert (tmp_path/"custom/company-000/activities.jsonl").is_file()
    assert not (tmp_path/"escape").exists()


def test_cross_process_hashseed_does_not_affect_digest() -> None:
    code = "from worldloom.process_bindings import *; print(compile_company(default_company('retail')).digest)"
    outputs = [subprocess.check_output([sys.executable,"-c",code],env={**os.environ,"PYTHONHASHSEED":seed},text=True) for seed in ("1","123")]
    assert outputs[0] == outputs[1]


def test_input_source_digests_and_readonly_snapshots() -> None:
    cat = load_catalogue()
    compiled = compile_company(default_company("retail"),catalogue=cat)
    digest = compiled.digest
    cat["value_streams"]["order_to_cash"]["name"] = "Changed"
    assert compiled.digest == digest
    assert compile_company(default_company("retail"),catalogue=cat).digest != digest
    manifest = resource("bindings-provenance.json")
    assert set(manifest["inputs"]) == {"catalogue.json","compile_processes.py","coverage.csv","VOCABULARY.md","all-12-industries.zip"}
    assert Counter(r["status"] for r in manifest["source_coverage"])["corpus_calibrated"] == 63
    assert fingerprint([r.legacy_record() for r in compiled.rows]) == manifest["compiled_baselines"]["default-retail.jsonl"]["semantic_sha256"]
