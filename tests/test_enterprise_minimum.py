from __future__ import annotations

import json
from pathlib import Path

from evals.enterprise_minimum import audit


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _member(tmp_path: Path) -> Path:
    root = tmp_path / "world-01"
    root.mkdir()
    world = {
        "people": [{"id": "PERSON-1"}],
        "business_units": [{"id": "UNIT-1"}],
        "sites": [{"id": "SITE-1"}],
        "systems": [{"id": "SYSTEM-1"}],
        "services": [{"id": "SERVICE-1"}],
        "access_policies": [{"id": "POLICY-1"}],
        "recipe": {"steps": [{"scenario": "MonthEndClose"}]},
    }
    (root / "world.json").write_text(json.dumps(world), encoding="utf-8")
    types = [
        ("executive_summary", "strategy"), ("finance_workbook", "finance"),
        ("servicenow_incident", "operations"), ("incident_rca", "engineering"),
        ("email_thread", "operations"), ("meeting_minutes", "strategy"),
    ]
    artifacts = []
    for number, (kind, domain) in enumerate(types, 1):
        artifacts.append({
            "id": f"ART-{number}", "artifact_type": kind, "domain": domain,
            "approver_id": "PERSON-1", "access_policy_id": "POLICY-1",
            "lifecycle": ("published", "reviewed", "draft")[number % 3],
            "supporting_fact_ids": [f"FACT-{number}"],
            "revises": "ART-0" if number == 1 else None,
            "supersedes": None, "restates": None,
        })
    _write_jsonl(root / "artifact-manifest.jsonl", artifacts)
    facts = [
        {"id": f"FACT-{n}", "kind": "financial.revenue.actual", "subject": subject, "period": f"2026-{n:02d}"}
        for n, subject in enumerate(("PERSON-1", "UNIT-1", "SITE-1", "SYSTEM-1", "SERVICE-1", "UNIT-1"), 1)
    ]
    _write_jsonl(root / "facts.jsonl", facts)
    _write_jsonl(root / "events.jsonl", [{"occurred_at": "2026-01-01T00:00:00Z"}])
    _write_jsonl(root / "evals.jsonl", [{"id": "EVAL-1"}])
    _write_jsonl(root / "generation-ledger.jsonl", [{"call_site": "request-1"}])
    rendered = root / "artifacts"
    rendered.mkdir()
    for suffix in ("docx", "pdf", "pptx", "xlsx", "html", "md"):
        (rendered / f"artifact.{suffix}").touch()
    for projection in ("jira", "confluence", "servicenow"):
        folder = root / projection
        folder.mkdir()
        (folder / "records.jsonl").touch()
    return root


def test_a_cross_functional_label_is_refused_for_a_finance_operations_pilot(tmp_path: Path) -> None:
    _member(tmp_path)
    report = audit(tmp_path)
    assert report["profiles"]["finance-operations-pilot"]["admitted"]
    enterprise = report["profiles"]["enterprise-minimum"]
    assert not enterprise["admitted"]
    assert {"workforce", "procurement", "customer_commercial", "security", "knowledge_flow"} <= set(enterprise["blockers"])


def test_people_without_workforce_records_are_only_partial_hr_coverage(tmp_path: Path) -> None:
    _member(tmp_path)
    report = audit(tmp_path)
    workforce = report["dimensions"]["workforce"]
    assert workforce["status"] == "partial"
    assert "bylines" in workforce["gap"]


def test_entity_reach_requires_declared_entities_to_land_in_readable_records(tmp_path: Path) -> None:
    member = _member(tmp_path)
    facts = [json.loads(line) for line in (member / "facts.jsonl").read_text().splitlines()]
    for row in facts:
        row["subject"] = "COMPANY-1"
    _write_jsonl(member / "facts.jsonl", facts)
    report = audit(tmp_path)
    assert report["dimensions"]["entity_reach"]["status"] == "missing"
    assert report["dimensions"]["entity_reach"]["sample_evidence"]["share"] == 0.0


def test_master_data_is_evidence_but_not_transactional_coverage(tmp_path: Path) -> None:
    member = _member(tmp_path)
    (member / "masterdata.json").write_text(json.dumps({
        "vendors": [{"id": "VND-1"}],
        "customers": [{"id": "CUS-1"}],
        "skus": [{"id": "SKU-1", "vendor_id": "VND-1"}],
    }), encoding="utf-8")

    report = audit(tmp_path)
    procurement = report["dimensions"]["procurement"]
    customer = report["dimensions"]["customer_commercial"]
    assert procurement["status"] == "partial"
    assert procurement["sample_evidence"]["vendor_master_rows"] == 1
    assert customer["status"] == "partial"
    assert customer["sample_evidence"]["customer_master_rows"] == 1
    assert not report["profiles"]["enterprise-minimum"]["admitted"]
