"""Write ``catalogue.json``: a CUJ catalogue built for W4's round trip.

The miner's sample has one journey that writes, and every question built from
it reads the same pinned page. One page is one evidence group, a group may
not straddle train, validation and test, and Studio caps questions per group,
so that sample can never fill a dataset. This catalogue has four write
journeys, each searching Confluence for a different named page, so the round
trip gets four independent evidence groups:

    journey            reads (pinned)            writes
    notes_to_epics     page "sprint retro"   ──▶ jira issue   create
    summary_page       page "supplier review" ──▶ confluence page create
    ticket_update      page "store rollout"  ──▶ jira issue   update
    page_refresh       page "leave policy"   ──▶ confluence page update

Illustrative values only; nothing here comes from a customer. The ids, totals
and shares are computed, so the file obeys the catalogue's invariants by
construction. Regenerate with::

    python tests/fixtures/telemetry/roundtrip/build_catalogue.py
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

OUT = Path(__file__).with_name("catalogue.json")

#: (name, label, search phrase, template, steps after the search)
JOURNEYS = (
    ("notes_to_epics", "Meeting notes to Jira epics", "sprint retro",
     "Create epics in Jira from the action items in the {topic} notes",
     [("read_page", "confluence", "page", "read", "read", ["page_id"]),
      ("draft", None, None, None, "transform", []),
      ("create_epics", "jira", "issue", "create", "write", ["summary", "description"])]),
    ("summary_page", "Summarise notes into a Confluence page", "supplier review",
     "Summarise the {topic} notes into a new Confluence page",
     [("draft", None, None, None, "transform", []),
      ("create_page", "confluence", "page", "create", "write", ["title", "space_key"])]),
    ("ticket_update", "Update a Jira ticket from a page", "store rollout",
     "Update the Jira ticket with the decisions from the {topic} page",
     [("read_page", "confluence", "page", "read", "read", ["page_id"]),
      ("draft", None, None, None, "transform", []),
      ("update_ticket", "jira", "issue", "update", "write", ["description"])]),
    ("page_refresh", "Refresh a Confluence page", "leave policy",
     "Bring the {topic} page up to date with this week's changes",
     [("draft", None, None, None, "transform", []),
      ("update_page", "confluence", "page", "update", "write", ["page_id", "body"])]),
)

SHARE = 0.2
SESSIONS = 30
QUERIES = 60


def token(step: dict) -> str:
    if "capability" in step:
        return "~" + step["capability"]
    return f"{step['connector']}.{step['entity']}.{step['operation']}"


def cuj_id(steps: list[dict]) -> str:
    signature = "|".join(token(step) for step in steps)
    return "cuj_" + hashlib.sha256(signature.encode("utf-8")).hexdigest()[:12]


def journey(name: str, label: str, phrase: str, template: str, rest: list) -> dict:
    steps = [{"id": "search_page", "connector": "confluence", "entity": "page",
              "operation": "search", "effect": "read", "argument_fields": ["queries"],
              "presence": 1.0}]
    previous = "search_page"
    for step_id, connector, entity, operation, effect, fields in rest:
        if connector is None:
            step = {"id": step_id, "capability": "generate", "effect": effect,
                    "presence": 1.0, "depends_on": [previous]}
        else:
            step = {"id": step_id, "connector": connector, "entity": entity,
                    "operation": operation, "effect": effect, "argument_fields": fields,
                    "presence": 1.0, "depends_on": [previous]}
        steps.append(step)
        previous = step_id
    return {
        "id": cuj_id(steps), "label": label, "label_source": "manual",
        "anchor": "tool_signature", "kind": "single_turn", "steps": steps,
        "support": {"sessions": SESSIONS, "queries": QUERIES, "share": SHARE},
        "outcomes": {"SUCCESS": QUERIES},
        "hardness": {"HEAD_EASY": QUERIES // 2, "MEDIUM": QUERIES // 2},
        "checks": {"trace": QUERIES},
        "volatility": {"stable": QUERIES, "high": 0},
        "domains": {"TOOL_USE": QUERIES},
        "domain_terms": [phrase],
        "failure_modes": [],
        "phrasings": [{"template": template, "support": SESSIONS,
                       "slots": [{"name": "topic", "step_id": "search_page",
                                  "field": "queries"}]}],
    }


def connectors(cujs: list[dict]) -> list[dict]:
    """``connectors[]`` declared from the steps, so ``inv1`` holds."""
    declared: dict[str, dict[str, dict]] = {}
    for cuj in cujs:
        for step in cuj["steps"]:
            if "connector" not in step:
                continue
            entity = declared.setdefault(step["connector"], {}).setdefault(
                step["entity"], {"operations": set(), "argument_fields": set()})
            entity["operations"].add(step["operation"])
            entity["argument_fields"].update(step["argument_fields"])
    out = []
    for key, entities in sorted(declared.items()):
        tools = [{"name": f"{key}_agent__{operation}_{name}", "entity": name,
                  "operation": operation, "calls": SESSIONS, "classified_by": "rule"}
                 for name, spec in sorted(entities.items())
                 for operation in sorted(spec["operations"])]
        out.append({
            "key": key, "display_name": key.title(), "observed_prefixes": [f"{key}_agent"],
            "call_count": sum(tool["calls"] for tool in tools),
            "entities": [{"name": name, "operations": sorted(spec["operations"]),
                          "argument_fields": sorted(spec["argument_fields"]),
                          "calls": SESSIONS * len(spec["operations"])}
                         for name, spec in sorted(entities.items())],
            "tools": tools,
        })
    return out


def catalogue() -> dict:
    cujs = [journey(*spec) for spec in JOURNEYS]
    covered = round(SHARE * len(cujs), 3)
    return {
        "schema_version": "cuj-catalogue/1",
        "catalogue_id": "w4_roundtrip_2026.10",
        "created_at": "2026-10-16T00:00:00Z",
        # The schema admits one producer name; the fixture says what it is in
        # its version and in privacy.notes.
        "producer": {"tool": "customer-telemetry-miner", "version": "0.0.0-w4-fixture",
                     "config_digest": hashlib.sha256(b"w4-roundtrip").hexdigest()},
        "source": {"queryset_id": "w4_roundtrip", "queryset_version": "2026.10",
                   "queryset_checksum": hashlib.sha256(b"w4-roundtrip-queries").hexdigest(),
                   "window": {"start": "2026-08-10T00:00:00Z", "end": "2026-08-25T00:00:00Z"},
                   "counts": {"records_ingested": 400, "records_curated": 240,
                              "sessions": SESSIONS * len(cujs), "tool_calls": 600}},
        "privacy": {"min_support": 3, "text_policy": "templates", "pii_redaction": "regex",
                    "notes": "Illustrative values only; not derived from any customer."},
        "connectors": connectors(cujs),
        "excluded_tools": [],
        "cujs": cujs,
        "coverage": {"cujs_emitted": len(cujs), "covered_share": covered,
                     "suppressed_share": 0.15, "unclassified_share": round(1 - covered - 0.15, 3)},
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(catalogue(), indent=2) + "\n", encoding="utf-8")
    print(f"wrote {OUT}")
