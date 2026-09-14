#!/usr/bin/env python3
"""Build the `sor` connector definition and the emulator table from the catalogue.

The process catalogue names the systems of record a company's work lives in
(`sor_classes`: ERP-FI, HRIS, CoreBanking, ...), the products that implement
each class (SAP S/4HANA, Workday, Temenos T24, ...) and the record kinds each
product holds (JournalEntry, Worker, Loan, ...). Six of those products have a
connector emulator of their own (ServiceNow, Jira, Salesforce, SharePoint,
Confluence, Exchange). The rest had none, so every activity bound to them was
reported as unemulated and the lines that need them could not be built.

This tool writes two files from the catalogue:

- `_data/connectors/sor.json`: one generic system-of-record connector whose
  entities are every record kind the catalogue names, each with a workflow
  from the table below (or the two-state default), searchable on the fields
  a binding gives a record, created with an idempotency key on the activity,
  period and owner;
- `_data/process-catalogue/emulated-systems@2.json`: the emulator table with
  every product that has no emulator of its own mapped to `sor`, its objects
  mapped to the connector's entities. Channels and destinations are copied
  from the previous version unchanged.

Only the workflow table below is authored. Everything else is read from the
catalogue, so a product or record kind added there reaches the connector by
rerunning this tool. `tests/test_sor.py` checks the shipped files against a
rebuild.

Usage::

    python tools/build_sor_connector.py
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from worldloom.process_bindings import load_catalogue

CONNECTORS = ROOT / "src" / "worldloom" / "_data" / "connectors"
CATALOGUE_DATA = ROOT / "src" / "worldloom" / "_data" / "process-catalogue"
PREVIOUS = "emulated-systems@1.json"
CURRENT = "emulated-systems@2.json"

# Record kind -> the states its record moves through, first to last. A kind
# absent here is open then closed. States are lower-case words a request can
# name; the last state is terminal.
WORKFLOWS: dict[str, tuple[str, ...]] = {
    "SalesOrder": ("created", "confirmed", "delivered", "billed", "closed"),
    "Order": ("created", "confirmed", "fulfilled", "closed"),
    "Delivery": ("planned", "picked", "shipped", "delivered"),
    "Shipment": ("booked", "in_transit", "delivered", "closed"),
    "FreightOrder": ("planned", "tendered", "in_transit", "delivered", "settled"),
    "BillingDoc": ("created", "released", "posted", "cleared"),
    "Invoice": ("draft", "issued", "sent", "paid", "cancelled"),
    "ARInvoice": ("draft", "issued", "sent", "paid", "cancelled"),
    "Bill": ("rated", "generated", "validated", "dispatched", "paid"),
    "CreditBlock": ("blocked", "released"),
    "PurchaseRequisition": ("draft", "submitted", "approved", "converted"),
    "Requisition": ("draft", "submitted", "approved", "converted"),
    "PurchaseOrder": ("created", "approved", "sent", "received", "invoiced", "closed"),
    "GoodsReceipt": ("posted", "reversed"),
    "Receipt": ("posted", "reversed"),
    "InvoiceReceipt": ("captured", "matched", "blocked", "approved", "paid"),
    "VendorBill": ("captured", "matched", "blocked", "approved", "paid"),
    "JournalEntry": ("parked", "posted", "reversed"),
    "AROpenItem": ("open", "dunned", "cleared"),
    "APOpenItem": ("open", "blocked", "cleared"),
    "IncomingPayment": ("received", "applied", "cleared"),
    "CustomerPayment": ("received", "applied", "cleared"),
    "PaymentRun": ("proposal", "scheduled", "executed"),
    "Dunning": ("level_1", "level_2", "level_3", "closed"),
    "BankStatement": ("imported", "reconciled"),
    "CashPosition": ("forecast", "actual"),
    "Consolidation": ("open", "eliminated", "consolidated", "reported"),
    "Cube": ("open", "locked"),
    "Model": ("draft", "submitted", "approved"),
    "Plan": ("draft", "submitted", "approved"),
    "Worker": ("hired", "active", "on_leave", "terminated"),
    "Employee": ("hired", "active", "on_leave", "terminated"),
    "Position": ("open", "filled", "closed"),
    "JobRequisition": ("open", "approved", "posted", "filled"),
    "PayRun": ("scheduled", "calculated", "approved", "paid"),
    "Incident": ("new", "open", "resolved", "closed"),
    "Change": ("new", "assessed", "approved", "scheduled", "implemented", "closed"),
    "Problem": ("open", "known_error", "closed"),
    "Request": ("submitted", "approved", "fulfilled", "closed"),
    "KB": ("draft", "published", "retired"),
    "CI": ("planned", "operational", "retired"),
    "Ticket": ("new", "open", "resolved", "closed"),
    "Case": ("new", "working", "escalated", "closed"),
    "Lead": ("new", "qualified", "converted", "disqualified"),
    "Opportunity": ("qualify", "propose", "negotiate", "closed_won", "closed_lost"),
    "Deal": ("qualify", "propose", "negotiate", "closed_won", "closed_lost"),
    "Quote": ("draft", "approved", "presented", "accepted", "expired"),
    "Contract": ("draft", "negotiated", "signed", "active", "expired"),
    "Account": ("open", "active", "dormant", "closed"),
    "Loan": ("applied", "approved", "disbursed", "closed"),
    "Policy": ("quoted", "bound", "issued", "renewed", "cancelled"),
    "Submission": ("received", "underwriting", "quoted", "declined"),
    "Claim": ("reported", "open", "reserved", "settled", "closed"),
    "Exposure": ("open", "reserved", "closed"),
    "Encounter": ("registered", "admitted", "discharged", "billed"),
    "Outage": ("detected", "assessed", "dispatched", "restored", "reported"),
    "WorkOrder": ("planned", "released", "in_progress", "completed"),
    "Batch": ("planned", "released", "in_progress", "completed"),
    "Wave": ("planned", "released", "picking", "complete"),
    "Pick": ("assigned", "in_progress", "complete"),
    "Task": ("assigned", "in_progress", "complete"),
    "WarehouseOrder": ("created", "in_process", "confirmed"),
    "Part": ("in_work", "released", "obsolete"),
    "Item": ("in_work", "released", "obsolete"),
    "ChangeNotice": ("open", "in_review", "approved", "implemented"),
    "Document": ("draft", "in_review", "published", "archived"),
    "File": ("draft", "published", "archived"),
    "List": ("active", "archived"),
    "Page": ("draft", "published", "archived"),
    "Message": ("sent",),
    "Report": ("draft", "published"),
    "Look": ("draft", "published"),
    "Workbook": ("draft", "published"),
}
DEFAULT_WORKFLOW: tuple[str, ...] = ("open", "closed")

#: What a request can search a record by: the binding fields every record carries.
QUERY_FIELDS: dict[str, str] = {
    "activity": "activity", "activity_id": "activity_id", "stream": "stream", "function": "function",
    "owner_bu": "owner_bu", "country": "country", "product": "product", "sor_class": "sor_class",
    "status": "status", "period": "period", "pcf_id": "pcf_id", "exception": "exception", "amount": "amount",
    "object": "object", "binding_id": "binding_id",
}


def entity_name(kind: str) -> str:
    """`PurchaseOrder` -> `purchase_order`; `APOpenItem` -> `ap_open_item`; `KB` -> `kb`."""
    words = re.findall(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z]+|[A-Z]+", kind)
    return "_".join(w.lower() for w in words)


def object_kinds(catalogue: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Every record kind the catalogue names, with the products that hold it."""
    kinds: dict[str, dict[str, Any]] = {}
    for sor_class, spec in catalogue["sor_classes"].items():
        for product, objects in spec.get("products", {}).items():
            for kind in objects:
                kinds.setdefault(kind, {"products": []})["products"].append(f"{sor_class}/{product}")
    return dict(sorted(kinds.items()))


def definition(catalogue: dict[str, Any]) -> dict[str, Any]:
    entities: dict[str, Any] = {}
    state_codes: dict[str, dict[str, int]] = {}
    for kind in object_kinds(catalogue):
        states = WORKFLOWS.get(kind, DEFAULT_WORKFLOW)
        transitions = {state: [states[i + 1]] if i + 1 < len(states) else [] for i, state in enumerate(states)}
        name = entity_name(kind)
        entities[name] = {
            "kind": "record",
            "ops": {"search": "search_records", "read": "get_record", "extract": "search_records",
                    "create": "create_record", "update": "update_record", "transition": "update_record",
                    "comment": "add_note"},
            "workflow": {"field": "status", "states": list(states), "transitions": transitions, "aliases": {}},
            "required_on_create": ["activity_id", "owner_bu", "period"],
            "searchable": "*",
            "query_name": kind,
        }
        state_codes[name] = {state: index + 1 for index, state in enumerate(states)}
    names = list(entities)
    tools = {
        "search_records": {"op": "search", "entities": names,
                           "params": {"query": "string?", "predicate": "object?", "fields": "array?",
                                      "max_results": "int?", "start_at": "int?", "entity": "string?"},
                           "page_size": 100, "max_results": 10000, "projection": True, "idempotency": None},
        "get_record": {"op": "get", "entities": names, "params": {"id": "string", "fields": "array?"},
                       "page_size": 100, "max_results": 10000, "projection": True, "idempotency": None},
        "create_record": {"op": "create", "entities": names,
                          "params": {"entity": "string", "name": "string", "fields": "object?"},
                          "page_size": 100, "max_results": 10000, "projection": False,
                          "idempotency": {"key": ["activity_id", "period", "owner_bu", "object"], "window_s": 300}},
        "update_record": {"op": "update", "entities": names, "params": {"id": "string", "fields": "object"},
                          "page_size": 100, "max_results": 10000, "projection": False, "idempotency": None},
        "add_note": {"op": "comment", "entities": names, "params": {"id": "string", "body": "string"},
                     "page_size": 100, "max_results": 10000, "projection": False, "idempotency": None},
    }
    return {
        "schema": "worldloom.connector-definition/v1",
        "connector": "sor",
        "version": "1",
        "vendor_product": "System of record (the process catalogue's object models)",
        "maturity": "ga",
        "capability_notes": [
            "One connector stands in for every product the catalogue names and no other emulator does; a record says which product and class it belongs to.",
            "Records are derived from a company's compiled activity bindings by worldloom.sor: one per binding, record kind and period.",
        ],
        "clock": "2026-09-05T09:00:00+08:00",
        "id": {"field": "ident", "pattern": "SOR{10d}"},
        "payload_shape": "sor_record",
        "query_language": "predicate",
        "acl": {"model": "role_table"},
        "errors": {
            "not_found": [404, "No record found"],
            "denied": [403, "Role has no access to this record"],
            "validation": [400, "Required field '{field}' is missing"],
            "bad_transition": [400, "Status transition not allowed"],
        },
        "faults": ["timeout", "rate_limit_429", "partial_page"],
        "options": {},
        "custom_fields": {},
        "state_codes": state_codes,
        "validation_rules": {},
        "entities": entities,
        "entity_aliases": {},
        "tools": tools,
        "aliases": {},
        "query_fields": QUERY_FIELDS,
    }


def emulated_systems(catalogue: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
    products = dict(previous["products"])
    for spec in catalogue["sor_classes"].values():
        for product, objects in spec.get("products", {}).items():
            if product in previous["products"]:
                continue  # an emulator of its own
            entry = products.setdefault(product, {"connector": "sor", "objects": {}})
            # One product serves several classes (SAP S/4HANA is ERP-SD, ERP-MM
            # and ERP-FI); its objects are the union across them.
            entry["objects"].update({kind: entity_name(kind) for kind in objects})
            entry["objects"] = dict(sorted(entry["objects"].items()))
    return {
        "schema": "worldloom.emulated-systems/v1",
        "about": previous["about"] + " Version 2: every product with no emulator of its own is stood in for by the "
                 "`sor` connector (tools/build_sor_connector.py), its objects mapped to that connector's entities.",
        "products": dict(sorted(products.items())),
        "channels": previous["channels"],
        "destinations": previous["destinations"],
    }


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    catalogue = load_catalogue()
    previous = json.loads((CATALOGUE_DATA / PREVIOUS).read_text(encoding="utf-8"))
    return definition(catalogue), emulated_systems(catalogue, previous)


def main() -> int:
    connector, table = build()
    (CONNECTORS / "sor.json").write_text(json.dumps(connector, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    (CATALOGUE_DATA / CURRENT).write_text(json.dumps(table, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"sor.json: {len(connector['entities'])} entities; {CURRENT}: {len(table['products'])} products "
          f"({sum(1 for p in table['products'].values() if p['connector'] == 'sor')} on sor)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
