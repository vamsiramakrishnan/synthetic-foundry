"""Measure whether a Worldloom fleet resembles a usable enterprise corpus.

Coherence is necessary but not sufficient.  A perfectly consistent month-end
close archive can still omit most of the records people expect when they say
"an enterprise corpus".  This audit keeps those two claims separate.  It reads
only shipped corpus files and reports evidence as covered, partial, or missing.

Two admissions are intentional:

``finance-operations-pilot``
    A bounded corpus for finance, service operations, retrieval, and ACL tests.

``enterprise-minimum``
    A cross-functional company corpus with policies, workforce, procurement,
    customer, security, knowledge-flow, history, and connected entities too.

The stricter profile is expected to fail the current retail-close fleet.  That
failure is the product target, not a reason to weaken the gate.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

Status = str


@dataclass(frozen=True)
class Reading:
    status: Status
    evidence: Mapping[str, Any]
    gap: str | None = None


@dataclass(frozen=True)
class Dimension:
    key: str
    label: str
    profiles: tuple[str, ...]
    read: Callable[[Mapping[str, Any]], Reading]


def _json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def _members(root: Path) -> list[Path]:
    if (root / "world.json").exists():
        return [root]
    return sorted(path for path in root.glob("world-*") if (path / "world.json").exists())


def _types(state: Mapping[str, Any], *needles: str) -> list[str]:
    return sorted(kind for kind in state["artifact_types"] if any(n in kind for n in needles))


def _domains(state: Mapping[str, Any], *names: str) -> int:
    return sum(state["domains"].get(name, 0) for name in names)


def _covered(evidence: Mapping[str, Any]) -> Reading:
    return Reading("covered", evidence)


def _partial(evidence: Mapping[str, Any], gap: str) -> Reading:
    return Reading("partial", evidence, gap)


def _missing(evidence: Mapping[str, Any], gap: str) -> Reading:
    return Reading("missing", evidence, gap)


def _has_types(state: Mapping[str, Any], required: Iterable[str]) -> bool:
    return set(required).issubset(state["artifact_types"])


def _identity(state: Mapping[str, Any]) -> Reading:
    counts = state["entity_counts"]
    evidence = {key: counts.get(key, 0) for key in ("people", "business_units", "sites")}
    if evidence["people"] and evidence["business_units"] and evidence["sites"]:
        return _covered(evidence)
    return _partial(evidence, "Add a named organisation, reporting structure, business units, and places.")


def _executive(state: Mapping[str, Any]) -> Reading:
    evidence = {
        "executive_summaries": state["artifact_types"].get("executive_summary", 0),
        "approved_artifacts": state["approved_artifacts"],
    }
    if all(evidence.values()):
        return _covered(evidence)
    return _missing(evidence, "Add executive reporting and real prepared/approved-by records.")


def _finance(state: Mapping[str, Any]) -> Reading:
    evidence = {
        "finance_artifacts": _domains(state, "finance"),
        "workbooks": len(_types(state, "workbook")),
        "financial_fact_kinds": sum(v for k, v in state["fact_kinds"].items() if k.startswith("financial.")),
    }
    if evidence["finance_artifacts"] and evidence["workbooks"] and evidence["financial_fact_kinds"]:
        return _covered(evidence)
    return _missing(evidence, "Add ledger-like facts, reconciliations, plans, actuals, and finance workbooks.")


def _operations(state: Mapping[str, Any]) -> Reading:
    native = _types(state, "servicenow", "jira", "incident", "service_register")
    evidence = {"operations_artifacts": _domains(state, "operations"), "record_types": native}
    if evidence["operations_artifacts"] and native:
        return _covered(evidence)
    return _missing(evidence, "Add operational cases, incidents, changes, services, and system-native records.")


def _technology(state: Mapping[str, Any]) -> Reading:
    counts = state["entity_counts"]
    evidence = {
        "engineering_artifacts": _domains(state, "engineering", "technology"),
        "systems": counts.get("systems", 0),
        "services": counts.get("services", 0),
    }
    if all(evidence.values()):
        return _covered(evidence)
    return _missing(evidence, "Add systems, services, dependencies, ownership, and engineering records.")


def _collaboration(state: Mapping[str, Any]) -> Reading:
    evidence = {kind: state["artifact_types"].get(kind, 0) for kind in ("email_thread", "meeting_minutes")}
    if all(evidence.values()):
        return _covered(evidence)
    if any(evidence.values()):
        return _partial(evidence, "Add both conversational mail and meeting/decision records.")
    return _missing(evidence, "Add mail, meetings, decisions, and task-shaped collaboration records.")


def _access(state: Mapping[str, Any]) -> Reading:
    evidence = {
        "access_policies": state["entity_counts"].get("access_policies", 0),
        "artifacts_with_acl": state["artifacts_with_acl"],
        "artifacts": state["artifacts"],
    }
    if evidence["access_policies"] and evidence["artifacts"] == evidence["artifacts_with_acl"]:
        return _covered(evidence)
    return _partial(evidence, "Attach every record to a readership policy and materialise permission metadata.")


def _time_depth(state: Mapping[str, Any]) -> Reading:
    evidence = {"periods": state["periods"], "dated_events": state["dated_events"]}
    if evidence["periods"] >= 6 and evidence["dated_events"]:
        return _covered(evidence)
    if evidence["periods"] > 1:
        return _partial(evidence, "Use at least six periods with dated events, not a point-in-time snapshot.")
    return _missing(evidence, "Add longitudinal periods and dated events.")


def _lifecycle(state: Mapping[str, Any]) -> Reading:
    evidence = {
        "lifecycle_states": sorted(state["lifecycles"]),
        "revision_links": state["revision_links"],
    }
    if len(evidence["lifecycle_states"]) >= 3 and evidence["revision_links"]:
        return _covered(evidence)
    return _partial(evidence, "Add drafts, approvals, corrections, revisions, supersession, and retained prior versions.")


def _provenance(state: Mapping[str, Any]) -> Reading:
    evidence = {
        "facts": state["facts"],
        "evaluations": state["evaluations"],
        "ledger_entries": state["ledger_entries"],
    }
    if all(evidence.values()):
        return _covered(evidence)
    return _missing(evidence, "Add canonical facts, evaluation cases, and a replayable generation ledger.")


def _format_mixture(state: Mapping[str, Any]) -> Reading:
    office = {kind: state["rendered_formats"].get(kind, 0) for kind in ("docx", "pdf", "pptx", "xlsx")}
    readable = {kind: state["rendered_formats"].get(kind, 0) for kind in ("html", "md")}
    projections = {kind: state["system_projections"].get(kind, 0) for kind in ("jira", "confluence", "servicenow")}
    evidence = {"office": office, "web_and_text": readable, "system_projections": projections}
    if all(office.values()) and all(readable.values()) and all(projections.values()):
        return _covered(evidence)
    if any(office.values()) or any(readable.values()) or any(projections.values()):
        return _partial(evidence, "Render DOCX, PDF, PPTX, XLSX, HTML, Markdown, Jira, Confluence, and ServiceNow projections.")
    return _missing(evidence, "Materialise the corpus into mixed office, web/text, and system-native formats.")


def _workforce(state: Mapping[str, Any]) -> Reading:
    records = _types(state, "job_requisition", "offer_letter", "onboarding", "performance_review", "one_to_one")
    evidence = {"people": state["entity_counts"].get("people", 0), "workforce_record_types": records}
    if len(records) >= 3:
        return _covered(evidence)
    if evidence["people"]:
        return _partial(evidence, "People exist only as actors/bylines; add hiring, onboarding, review, leave, and personnel records.")
    return _missing(evidence, "Add a workforce and its employment records.")


def _policies_risk_legal(state: Mapping[str, Any]) -> Reading:
    policies = _types(state, "policy", "code_of_conduct", "delegation_of_authority")
    risk = _types(state, "risk", "audit", "compliance", "legal")
    evidence = {"policy_types": policies, "risk_or_legal_types": risk}
    if len(policies) >= 5 and risk:
        return _covered(evidence)
    if policies or risk or state["artifact_types"].get("incident_rca", 0):
        return _partial(evidence, "Add standing policies plus legal, compliance, internal-audit, and enterprise-risk records.")
    return _missing(evidence, "Add standing policies and legal/risk/compliance evidence.")


def _procurement(state: Mapping[str, Any]) -> Reading:
    records = _types(state, "purchase_order", "supplier", "vendor", "goods_receipt", "match_exception", "procurement")
    facts = sum(value for key, value in state["fact_kinds"].items() if key.startswith("p2p."))
    evidence = {
        "record_types": records,
        "procure_to_pay_facts": facts,
        "vendor_master_rows": state["master_data"].get("vendors", 0),
        "sku_master_rows": state["master_data"].get("skus", 0),
    }
    if len(records) >= 4 and facts:
        return _covered(evidence)
    if records or facts or evidence["vendor_master_rows"] or evidence["sku_master_rows"]:
        return _partial(evidence, "Complete supplier master, contract, order, receipt, invoice, approval, and payment evidence.")
    return _missing(evidence, "Add vendor, contract, sourcing, purchase-to-pay, and third-party-risk records.")


def _customer(state: Mapping[str, Any]) -> Reading:
    records = _types(state, "customer", "crm", "sales_order", "case", "complaint", "campaign")
    customer_facts = sum(value for key, value in state["fact_kinds"].items() if key.startswith(("customer.", "crm.", "sales.")))
    evidence = {
        "record_types": records,
        "customer_fact_kinds": customer_facts,
        "customer_master_rows": state["master_data"].get("customers", 0),
    }
    if len(records) >= 3 and customer_facts:
        return _covered(evidence)
    if records or customer_facts or evidence["customer_master_rows"]:
        return _partial(evidence, "Complete customer master, commercial activity, service, consent, and complaint history.")
    return _missing(evidence, "Add customer/commercial entities and CRM, sales, service, and complaint records.")


def _security(state: Mapping[str, Any]) -> Reading:
    records = _types(state, "information_security", "security", "access_review", "identity", "vulnerability")
    evidence = {"security_record_types": records, "access_policies": state["entity_counts"].get("access_policies", 0)}
    if len(records) >= 2:
        return _covered(evidence)
    if evidence["access_policies"]:
        return _partial(evidence, "ACLs exist, but add security policy, identity/access reviews, vulnerabilities, and security incidents.")
    return _missing(evidence, "Add security governance and operational security records.")


def _knowledge_flow(state: Mapping[str, Any]) -> Reading:
    evidence = {key: state[key] for key in ("messages", "observations", "tasks")}
    if evidence["messages"] and evidence["observations"]:
        return _covered(evidence)
    if any(evidence.values()):
        return _partial(evidence, "Model who knew what and when across both messages and observations.")
    return _missing(evidence, "Add modeled messages/observations so information asymmetry is testable; add tasks when the workflow supports them.")


def _entity_reach(state: Mapping[str, Any]) -> Reading:
    evidence = {"declared": state["declared_entities"], "reached": state["reached_entities"], "share": state["entity_reach_share"]}
    share = state["entity_reach_share"]
    if share is not None and share >= 0.75:
        return _covered(evidence)
    if share:
        return _partial(evidence, "Make declared people, units, sites, systems, and services subjects of facts carried by readable records (target 75%).")
    return _missing(evidence, "Connect declared enterprise entities to facts and readable records.")


DIMENSIONS = (
    Dimension("identity_and_org", "Company identity and organisation", ("finance-operations-pilot", "enterprise-minimum"), _identity),
    Dimension("executive_governance", "Executive reporting and approvals", ("finance-operations-pilot", "enterprise-minimum"), _executive),
    Dimension("finance", "Finance and performance", ("finance-operations-pilot", "enterprise-minimum"), _finance),
    Dimension("operations", "Operations and service management", ("finance-operations-pilot", "enterprise-minimum"), _operations),
    Dimension("technology", "Technology estate", ("finance-operations-pilot", "enterprise-minimum"), _technology),
    Dimension("collaboration", "Human collaboration artifacts", ("finance-operations-pilot", "enterprise-minimum"), _collaboration),
    Dimension("access_control", "Access control and permissions", ("finance-operations-pilot", "enterprise-minimum"), _access),
    Dimension("time_depth", "Longitudinal time depth", ("finance-operations-pilot", "enterprise-minimum"), _time_depth),
    Dimension("record_lifecycle", "Record lifecycle and supersession", ("finance-operations-pilot", "enterprise-minimum"), _lifecycle),
    Dimension("provenance_and_evals", "Provenance, replay, and evaluations", ("finance-operations-pilot", "enterprise-minimum"), _provenance),
    Dimension("format_mixture", "Mixed native formats and system projections", ("finance-operations-pilot", "enterprise-minimum"), _format_mixture),
    Dimension("workforce", "Workforce and HR", ("enterprise-minimum",), _workforce),
    Dimension("policies_risk_legal", "Policies, legal, risk, and compliance", ("enterprise-minimum",), _policies_risk_legal),
    Dimension("procurement", "Procurement and third parties", ("enterprise-minimum",), _procurement),
    Dimension("customer_commercial", "Customer and commercial", ("enterprise-minimum",), _customer),
    Dimension("security", "Security governance and operations", ("enterprise-minimum",), _security),
    Dimension("knowledge_flow", "Modeled information flow", ("enterprise-minimum",), _knowledge_flow),
    Dimension("entity_reach", "Entity-to-record reach", ("enterprise-minimum",), _entity_reach),
)


def _state(member: Path) -> dict[str, Any]:
    world = _json(member / "world.json")
    artifacts = _jsonl(member / "artifact-manifest.jsonl")
    facts = _jsonl(member / "facts.jsonl")
    events = _jsonl(member / "events.jsonl")
    artifact_types = Counter(row.get("artifact_type") for row in artifacts)
    domains = Counter(row.get("domain") for row in artifacts)
    fact_kinds = Counter(row.get("kind") for row in facts)
    carried = {identifier for row in artifacts for identifier in row.get("supporting_fact_ids", [])}
    reached_subjects = {row.get("subject") for row in facts if row.get("id") in carried}
    collections = {
        "people": world.get("people", []), "business_units": world.get("business_units", []),
        "sites": world.get("sites", []), "systems": world.get("systems", []),
        "services": world.get("services", []), "access_policies": world.get("access_policies", []),
    }
    entity_ids = {
        row["id"] for key, rows in collections.items() if key != "access_policies" for row in rows
    }
    recipe = world.get("recipe", {})
    master = _json(member / "masterdata.json") if (member / "masterdata.json").exists() else {}
    periods = {row.get("period") for row in facts if row.get("period")}
    messages = len(_jsonl(member / "actor-messages.jsonl"))
    observations = len(_jsonl(member / "actor-observations.jsonl"))
    tasks = len(_jsonl(member / "actor-tasks.jsonl"))
    rendered_formats = Counter(
        path.suffix.removeprefix(".").casefold()
        for path in (member / "artifacts").glob("*")
        if path.is_file() and path.suffix
    )
    system_projections = Counter({
        name: sum(1 for path in (member / name).rglob("*") if path.is_file())
        for name in ("jira", "confluence", "servicenow")
    })
    return {
        "artifact_types": artifact_types, "domains": domains, "fact_kinds": fact_kinds,
        "entity_counts": {key: len(rows) for key, rows in collections.items()},
        "approved_artifacts": sum(row.get("approver_id") is not None for row in artifacts),
        "artifacts_with_acl": sum(bool(row.get("access_policy_id")) for row in artifacts),
        "artifacts": len(artifacts), "facts": len(facts),
        "evaluations": len(_jsonl(member / "evals.jsonl")),
        "ledger_entries": len(_jsonl(member / "generation-ledger.jsonl")),
        "periods": len(periods), "dated_events": sum(bool(row.get("occurred_at")) for row in events),
        "lifecycles": Counter(row.get("lifecycle") for row in artifacts),
        "revision_links": sum(bool(row.get(key)) for row in artifacts for key in ("revises", "supersedes", "restates")),
        "messages": messages, "observations": observations, "tasks": tasks,
        "declared_entities": len(entity_ids), "reached_entities": len(entity_ids & reached_subjects),
        "entity_reach_share": round(len(entity_ids & reached_subjects) / len(entity_ids), 4) if entity_ids else None,
        "recipe_scenarios": Counter(step.get("scenario") for step in recipe.get("steps", [])),
        "master_data": {
            key: len(master.get(key, []))
            for key in ("vendors", "customers", "skus", "contacts")
        },
        "rendered_formats": rendered_formats, "system_projections": system_projections,
    }


def audit(root: Path) -> dict[str, Any]:
    members = _members(root)
    if not members:
        raise ValueError(f"{root}: no Worldloom worlds found")
    member_states = {member.name: _state(member) for member in members}
    dimensions: dict[str, Any] = {}
    rank = {"missing": 0, "partial": 1, "covered": 2}
    for dimension in DIMENSIONS:
        readings = {name: dimension.read(state) for name, state in member_states.items()}
        fleet_status = min((reading.status for reading in readings.values()), key=rank.get)
        dimensions[dimension.key] = {
            "label": dimension.label,
            "status": fleet_status,
            "required_by": list(dimension.profiles),
            "members": Counter(reading.status for reading in readings.values()),
            "gap": next((reading.gap for reading in readings.values() if reading.status == fleet_status and reading.gap), None),
            "sample_evidence": next(iter(readings.values())).evidence,
        }
    profiles = {}
    for profile in ("finance-operations-pilot", "enterprise-minimum"):
        required = [dimension.key for dimension in DIMENSIONS if profile in dimension.profiles]
        blockers = [key for key in required if dimensions[key]["status"] != "covered"]
        profiles[profile] = {"admitted": not blockers, "required_dimensions": required, "blockers": blockers}
    return {
        "schema": "worldloom.enterprise-minimum@1",
        "root": str(root),
        "worlds": len(members),
        "profiles": profiles,
        "dimensions": dimensions,
        "interpretation": (
            "Coherence and scale do not imply enterprise breadth. A partial dimension is a real gap, "
            "not half credit toward the stricter admission."
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("root", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--require", choices=("finance-operations-pilot", "enterprise-minimum"))
    args = parser.parse_args()
    report = audit(args.root)
    payload = json.dumps(report, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    if args.require and not report["profiles"][args.require]["admitted"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
