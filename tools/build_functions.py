#!/usr/bin/env python3
"""Build the function table: every PCF process assigned to one business function,
every function seated with O*NET occupations and the systems of record it works in.

This is a crosswalk between two published taxonomies, not a catalogue typed
from memory. The only authored content is the three tables below:

- ``GROUPS`` assigns each APQC process group (level 2 of the cross-industry
  PCF) to a function, and ``PROCESSES`` overrides single processes (level 3)
  whose function differs from their group's;
- ``OCCUPATIONS`` seats each function with O*NET-SOC codes in three tiers:
  ``manager`` (who runs it), ``professional`` (who does the judgement work),
  ``support`` (who does the transactional work);
- ``SOR`` names the system-of-record classes each function works in, from
  the process catalogue's ``sor_classes``.

Every id is resolved against the shipped data when this runs. A PCF id or an
O*NET code that does not exist stops the build; a process group left out of
``GROUPS`` stops the build; a level-3 process assigned twice stops the build.
Names are copied from the data, never typed here, so the output cannot
disagree with its sources. The output is
``src/worldloom/_data/functions/functions@<n>.json``.

Usage::

    python tools/build_functions.py --out src/worldloom/_data/functions
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from worldloom import onet, pcf
from worldloom.process_catalogue import catalogue as load_catalogue

SCHEMA = "worldloom.functions/v1"
VERSION = 1

TITLES: dict[str, str] = {
    "strategy": "Strategy & Corporate Development",
    "product": "Product Management",
    "engineering": "Engineering",
    "marketing": "Marketing",
    "sales": "Sales",
    "sales_ops": "Sales Operations",
    "planning": "Supply & Demand Planning",
    "procurement": "Procurement",
    "production": "Production",
    "quality": "Quality",
    "fulfilment": "Fulfilment & Logistics",
    "warehouse": "Warehouse",
    "service_delivery": "Service Delivery",
    "customer_service": "Customer Service",
    "field_service": "After-sales Service",
    "hr": "Human Resources",
    "payroll": "Payroll",
    "it_governance": "IT Strategy & Governance",
    "it_security": "IT Security & Resilience",
    "data": "Data & Analytics",
    "change_mgmt": "Change & Release",
    "it_ops": "IT Operations / SRE",
    "it_service_desk": "IT Service Desk",
    "fpa": "FP&A",
    "credit": "Credit & Collections",
    "billing": "Billing",
    "controllership": "Controllership",
    "ap": "Accounts Payable",
    "treasury": "Treasury",
    "tax": "Tax",
    "trade_compliance": "Global Trade",
    "facilities": "Facilities & Assets",
    "capital_projects": "Capital Projects",
    "risk": "Risk",
    "compliance": "Compliance",
    "investor_relations": "Investor Relations",
    "corporate_affairs": "Corporate Affairs",
    "legal": "Legal",
    "audit": "Internal Audit",
    "process_excellence": "Process Excellence",
    "pmo": "Portfolio & Programme Office",
    "ehs": "EHS & Sustainability",
}

# APQC process group (hierarchy id in cross_industry@7.4) -> function.
GROUPS: dict[str, str] = {
    "1.1": "strategy", "1.2": "strategy", "1.3": "strategy", "1.4": "strategy",
    "2.1": "product", "2.2": "product", "2.3": "engineering",
    "3.1": "marketing", "3.2": "marketing", "3.3": "marketing", "3.4": "sales_ops", "3.5": "sales",
    "4.1": "planning", "4.2": "procurement", "4.3": "production", "4.4": "fulfilment",
    "5.1": "service_delivery", "5.2": "service_delivery", "5.3": "service_delivery",
    "6.1": "customer_service", "6.2": "customer_service", "6.3": "field_service", "6.4": "quality",
    "6.5": "customer_service",
    "7.1": "hr", "7.2": "hr", "7.3": "hr", "7.4": "hr", "7.5": "hr", "7.6": "hr", "7.7": "hr", "7.8": "hr",
    "8.1": "it_governance", "8.2": "it_governance", "8.3": "it_security", "8.4": "data",
    "8.5": "engineering", "8.6": "change_mgmt", "8.7": "it_ops",
    "9.1": "fpa", "9.2": "billing", "9.3": "controllership", "9.4": "controllership", "9.5": "payroll",
    "9.6": "ap", "9.7": "treasury", "9.8": "controllership", "9.9": "tax", "9.10": "treasury",
    "9.11": "trade_compliance",
    "10.1": "facilities", "10.2": "capital_projects", "10.3": "facilities", "10.4": "facilities",
    "11.1": "risk", "11.2": "compliance", "11.3": "compliance", "11.4": "risk",
    "12.1": "investor_relations", "12.2": "corporate_affairs", "12.3": "controllership",
    "12.4": "legal", "12.5": "corporate_affairs",
    "13.1": "process_excellence", "13.2": "pmo", "13.3": "quality", "13.4": "process_excellence",
    "13.5": "data", "13.6": "process_excellence", "13.7": "data", "13.8": "ehs", "13.9": "ehs",
}

# Level-3 process (hierarchy id) -> function, where it differs from the group.
PROCESSES: dict[str, str] = {
    "3.4.2": "sales",            # Develop sales partner/alliance relationships
    "3.5.4": "sales_ops",        # Manage sales orders
    "4.1.8": "quality",          # Develop quality standards and procedures
    "4.3.3": "quality",          # Perform quality testing
    "4.4.3": "warehouse",        # Operate warehousing
    "7.5.4": "payroll",          # Administer payroll
    "8.7.8": "it_service_desk",  # Operate IT user support
    "9.2.1": "credit",           # Process customer credit
    "9.2.4": "credit",           # Manage and process collections
    "12.3.2": "audit",           # Report audit findings
}

# Function -> O*NET-SOC codes per tier.
OCCUPATIONS: dict[str, dict[str, list[str]]] = {
    "strategy": {"manager": ["11-1011.00", "11-1021.00"], "professional": ["13-1111.00"], "support": ["43-6011.00"]},
    "product": {"manager": ["11-2021.00"], "professional": ["13-1161.00", "13-1111.00"], "support": []},
    "engineering": {"manager": ["11-9041.00", "11-3021.00"],
                    "professional": ["15-1252.00", "15-1253.00", "15-1254.00", "17-2112.00", "17-2141.00", "17-2071.00"],
                    "support": ["15-1251.00"]},
    "marketing": {"manager": ["11-2021.00", "11-2011.00"], "professional": ["13-1161.00", "13-1161.01", "27-3031.00"], "support": []},
    "sales": {"manager": ["11-2022.00", "41-1012.00"],
              "professional": ["41-4012.00", "41-4011.00", "41-3091.00", "41-9031.00"], "support": []},
    "sales_ops": {"manager": ["11-2022.00"], "professional": ["15-2031.00", "13-1199.00"], "support": ["43-4151.00"]},
    "planning": {"manager": ["11-3071.04"], "professional": ["13-1081.00", "15-2031.00"], "support": ["43-5061.00"]},
    "procurement": {"manager": ["11-3061.00"], "professional": ["13-1023.00", "13-1022.00"], "support": ["43-3061.00"]},
    "production": {"manager": ["11-3051.00", "51-1011.00"], "professional": ["17-2112.03", "17-2112.00"],
                   "support": ["51-9198.00", "51-9111.00", "51-9161.00", "51-9199.00"]},
    "quality": {"manager": ["11-3051.01"], "professional": ["19-4099.01", "17-2112.02"], "support": ["51-9061.00"]},
    "fulfilment": {"manager": ["11-3071.00"], "professional": ["13-1081.00", "13-1081.02"],
                   "support": ["43-5011.00", "43-5032.00", "43-5071.00"]},
    "warehouse": {"manager": ["11-3071.00", "53-1042.00", "53-1043.00"], "professional": ["13-1081.00"],
                  "support": ["53-7065.00", "53-7051.00", "53-7062.00", "53-7064.00"]},
    "service_delivery": {"manager": ["11-1021.00"], "professional": ["13-1082.00"], "support": ["43-4051.00"]},
    "customer_service": {"manager": ["43-1011.00"], "professional": ["13-1199.00"], "support": ["43-4051.00", "43-4021.00"]},
    "field_service": {"manager": ["49-1011.00"], "professional": ["13-1199.00"], "support": ["49-9071.00"]},
    "hr": {"manager": ["11-3121.00", "11-3111.00", "11-3131.00"],
           "professional": ["13-1071.00", "13-1141.00", "13-1151.00", "13-1075.00"], "support": ["43-4161.00"]},
    "payroll": {"manager": ["43-1011.00"], "professional": ["13-2011.00"], "support": ["43-3051.00"]},
    "it_governance": {"manager": ["11-3021.00"], "professional": ["15-1211.00", "15-1299.08", "13-1111.00"], "support": []},
    "it_security": {"manager": ["11-3021.00", "11-3013.01"], "professional": ["15-1212.00", "15-1299.05", "15-1299.04"], "support": []},
    "data": {"manager": ["11-3021.00"],
             "professional": ["15-2051.00", "15-2051.01", "15-1243.00", "15-1243.01", "15-2041.00"],
             "support": ["43-9111.00", "43-9021.00"]},
    "change_mgmt": {"manager": ["15-1299.09", "11-3021.00"], "professional": ["15-1211.00", "13-1082.00"], "support": []},
    "it_ops": {"manager": ["11-3021.00"],
               "professional": ["15-1244.00", "15-1242.00", "15-1241.00", "15-1299.08"], "support": []},
    "it_service_desk": {"manager": ["11-3021.00"], "professional": ["15-1231.00"], "support": ["15-1232.00"]},
    "fpa": {"manager": ["11-3031.00"], "professional": ["13-2031.00", "13-2051.00"], "support": ["43-9111.00"]},
    "credit": {"manager": ["11-3031.00"], "professional": ["13-2041.00"], "support": ["43-4041.00", "43-3011.00"]},
    "billing": {"manager": ["43-1011.00"], "professional": ["13-2011.00"], "support": ["43-3021.00", "43-3031.00"]},
    "controllership": {"manager": ["11-3031.01"], "professional": ["13-2011.00"], "support": ["43-3031.00"]},
    "ap": {"manager": ["43-1011.00"], "professional": ["13-2011.00"], "support": ["43-3031.00", "43-3021.00"]},
    "treasury": {"manager": ["11-3031.01"], "professional": ["13-2051.00", "13-2054.00"], "support": ["43-3031.00"]},
    "tax": {"manager": ["11-3031.00"], "professional": ["13-2011.00", "13-2082.00"], "support": ["43-3031.00"]},
    "trade_compliance": {"manager": ["11-3071.00"], "professional": ["13-1041.08", "13-1081.00"], "support": ["43-5011.01"]},
    "facilities": {"manager": ["11-3013.00", "11-3012.00"], "professional": ["13-1199.00"],
                   "support": ["49-9071.00", "43-9061.00", "43-4171.00"]},
    "capital_projects": {"manager": ["11-9021.00"], "professional": ["17-2051.00", "13-1051.00", "13-1082.00"], "support": []},
    "risk": {"manager": ["11-9199.02"], "professional": ["13-2054.00", "13-1199.04"], "support": []},
    "compliance": {"manager": ["11-9199.02", "11-9199.01"], "professional": ["13-1041.00", "13-1041.07"], "support": []},
    "investor_relations": {"manager": ["11-3031.00"], "professional": ["13-2051.00", "27-3031.00"], "support": []},
    "corporate_affairs": {"manager": ["11-2032.00"], "professional": ["27-3031.00", "27-3043.00"], "support": []},
    "legal": {"manager": ["23-1011.00"], "professional": ["23-1011.00"], "support": ["23-2011.00", "43-6012.00"]},
    "audit": {"manager": ["11-3031.00"], "professional": ["13-2011.00"], "support": []},
    "process_excellence": {"manager": ["11-1021.00"], "professional": ["13-1111.00", "17-2112.00"], "support": []},
    "pmo": {"manager": ["15-1299.09", "11-9199.00"], "professional": ["13-1082.00"], "support": []},
    "ehs": {"manager": ["11-1011.03"], "professional": ["17-2111.00", "13-1199.05", "13-1041.01"], "support": []},
}

# Function -> system-of-record classes (keys of the catalogue's sor_classes).
SOR: dict[str, list[str]] = {
    "strategy": ["EPM", "DMS"], "product": ["PLM", "Wiki"], "engineering": ["PLM", "Wiki"],
    "marketing": ["CRM", "BI", "DMS"], "sales": ["CRM", "CPQ", "Email"], "sales_ops": ["CRM", "CPQ", "ERP-SD"],
    "planning": ["ERP-MM", "EPM"], "procurement": ["P2P-suite", "ERP-MM", "DMS"], "production": ["MES", "ERP-MM"],
    "quality": ["MES", "DMS"], "fulfilment": ["ERP-SD", "TMS", "WMS"], "warehouse": ["WMS", "ERP-MM"],
    "service_delivery": ["ERP-SD", "ITSM"], "customer_service": ["CRM", "ITSM", "Chat"],
    "field_service": ["ITSM", "CRM"], "hr": ["HRIS", "DMS"], "payroll": ["Payroll", "HRIS"],
    "it_governance": ["ITSM", "Wiki"], "it_security": ["ITSM", "Wiki"], "data": ["BI", "DMS"],
    "change_mgmt": ["ITSM", "Wiki"], "it_ops": ["ITSM", "Wiki"], "it_service_desk": ["ITSM", "Chat"],
    "fpa": ["EPM", "BI", "ERP-FI"], "credit": ["ERP-FI", "CRM"], "billing": ["ERP-SD", "ERP-FI", "e-invoicing"],
    "controllership": ["ERP-FI", "Consolidation", "DMS"], "ap": ["ERP-FI", "P2P-suite", "e-invoicing"],
    "treasury": ["Treasury", "ERP-FI"], "tax": ["ERP-FI", "DMS"], "trade_compliance": ["ERP-MM", "TMS", "DMS"],
    "facilities": ["ERP-MM", "ITSM"], "capital_projects": ["ERP-FI", "DMS"], "risk": ["BI", "DMS"],
    "compliance": ["DMS", "ITSM"], "investor_relations": ["DMS", "Email"], "corporate_affairs": ["DMS", "Email"],
    "legal": ["DMS", "Email"], "audit": ["DMS", "BI"], "process_excellence": ["Wiki", "BI"],
    "pmo": ["Wiki", "DMS"], "ehs": ["DMS", "ITSM"],
}


def build() -> dict[str, Any]:
    cross = pcf.cross_industry()
    db = onet.load()
    catalogue = load_catalogue()
    sor_classes = set(catalogue["sor_classes"])
    problems: list[str] = []

    for table, name in ((GROUPS, "GROUPS"), (PROCESSES, "PROCESSES")):
        for hierarchy, function in table.items():
            if function not in TITLES:
                problems.append(f"{name}: {hierarchy} names unknown function {function!r}")
            try:
                cross.at(hierarchy)
            except KeyError as error:
                problems.append(f"{name}: {error}")
    for group in cross.at_level(2):
        if group.hierarchy_id not in GROUPS:
            problems.append(f"GROUPS: process group {group.hierarchy_id} {group.name!r} is not assigned")
    for hierarchy, function in PROCESSES.items():
        element = cross.get(cross.at(hierarchy).pcf_id) if hierarchy in {e.hierarchy_id for e in cross.elements} else None
        if element is not None and element.level != 3:
            problems.append(f"PROCESSES: {hierarchy} is a level-{element.level} element, not a process")
        parent = cross.at(hierarchy.rsplit(".", 1)[0]) if element is not None else None
        if parent is not None and GROUPS.get(parent.hierarchy_id) == function:
            problems.append(f"PROCESSES: {hierarchy} repeats its group's function {function!r}")
    for function in TITLES:
        seats = OCCUPATIONS.get(function)
        if seats is None:
            problems.append(f"OCCUPATIONS: {function} has no seats")
            continue
        if not seats.get("manager"):
            problems.append(f"OCCUPATIONS: {function} has no manager")
        for tier, codes in seats.items():
            for code in codes:
                if db.get(code) is None:
                    problems.append(f"OCCUPATIONS: {function}.{tier} names unknown O*NET code {code!r}")
        for klass in SOR.get(function, []):
            if klass not in sor_classes:
                problems.append(f"SOR: {function} names unknown sor class {klass!r}")
        if not SOR.get(function):
            problems.append(f"SOR: {function} names no system of record")
    if problems:
        raise SystemExit("\n".join(problems))

    assigned: dict[str, str] = {}
    for process in cross.at_level(3):
        group = cross.element(process.parent_pcf_id or "")
        assigned[process.pcf_id] = PROCESSES.get(process.hierarchy_id, GROUPS[group.hierarchy_id])
    functions: dict[str, Any] = {}
    for key, title in TITLES.items():
        processes = [
            {"pcf_id": p.pcf_id, "hierarchy_id": p.hierarchy_id, "name": p.name}
            for p in cross.at_level(3) if assigned[p.pcf_id] == key
        ]
        if not processes:
            raise SystemExit(f"{key}: owns no PCF process")
        categories = sorted({p["hierarchy_id"].split(".")[0] for p in processes}, key=int)
        seated = {
            tier: [{"code": code, "title": db.occupation(code).title} for code in codes]
            for tier, codes in OCCUPATIONS[key].items()
        }
        functions[key] = {
            "title": title,
            "categories": [{"number": c, "pcf_id": cross.at(f"{c}.0").pcf_id, "name": cross.at(f"{c}.0").name} for c in categories],
            "processes": processes,
            "occupations": seated,
            "sor_classes": SOR[key],
        }
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "sources": {"pcf": cross.key, "onet": db.release, "sor_classes": "process-catalogue/catalogue.json"},
        "tiers": {
            "manager": "runs the function; the head of the function is the senior title in this tier's pool",
            "professional": "does the judgement work: analysis, decisions, approvals",
            "support": "does the transactional work: capture, posting, filing, dispatch",
        },
        "functions": functions,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", required=True, type=Path)
    args = parser.parse_args(argv)
    document = build()
    args.out.mkdir(parents=True, exist_ok=True)
    target = args.out / f"functions@{VERSION}.json"
    target.write_text(json.dumps(document, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
    counts = {k: len(v["processes"]) for k, v in document["functions"].items()}
    print(f"{target.name}: {len(counts)} functions, {sum(counts.values())} processes, "
          f"{sum(len(c) for f in document['functions'].values() for c in f['occupations'].values())} seats")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
