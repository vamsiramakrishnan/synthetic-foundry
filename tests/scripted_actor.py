#!/usr/bin/env python3
"""A scripted stand-in for the driving agent, for the actor handshake.

The sibling of ``scripted_agent.py``. That one answers prose requests; this one
answers *decisions*: it reads what one employee can see, picks a tool, and writes
the action out.

    python3 tests/scripted_actor.py decision.json action.json [--overreach]

It reads only the decision document, never the corpus — which is the point. An
agent that opened `facts.jsonl` to decide what the service desk analyst should do
would be reading the world rather than that analyst's position in it, and every
information-asymmetry property of the corpus would quietly stop holding.

``--overreach`` makes it call a tool it was not offered, so CI can prove the
handshake rejects rather than assume it.
"""

from __future__ import annotations

import json
import sys
from typing import Any


def _facts(decision: dict[str, Any], *prefixes: str) -> list[str]:
    return [
        fact["id"]
        for fact in decision["facts"]
        if any(fact["kind"].startswith(prefix) for prefix in prefixes)
    ]


def _latest(decision: dict[str, Any], *prefixes: str) -> dict[str, Any] | None:
    found = [
        fact
        for fact in decision["facts"]
        if any(fact["kind"].startswith(prefix) for prefix in prefixes)
    ]
    return found[-1] if found else None


def choose(decision: dict[str, Any]) -> dict[str, Any]:
    """Pick one legal tool call from what this employee can see.

    Deliberately simple and deliberately not the scripted provider: this is the
    *handshake* under test, not the episode. What matters is that a plausible
    call can be composed from the decision document alone — if it cannot, the
    document is not self-describing and no real agent could answer it either.
    """
    offered = {tool["name"] for tool in decision["tools"]}
    symptom = _latest(decision, "ops.feed_status", "ops.incident_opened", "ops.incident_state")

    # A read, when one is offered. Reading first is what every role in this
    # episode actually does, and it is always legal.
    for tool in decision["tools"]:
        if tool["mutates"]:
            continue
        if tool["name"] in {"query_logs"} and "sys_erp" in decision["resources"]:
            return {"tool_name": "query_logs",
                    "arguments": {"system_id": decision["resources"]["sys_erp"]}}
        if tool["name"] in {"read_ledger", "query_budget"} and "company" in decision["resources"]:
            return {"tool_name": tool["name"],
                    "arguments": {"subject_id": decision["resources"]["company"]}}
        if tool["name"] == "inspect_dependencies" and symptom:
            return {"tool_name": "inspect_dependencies",
                    "arguments": {"service_id": symptom["subject"]}}
        if tool["name"] == "search_incidents":
            return {"tool_name": "search_incidents", "arguments": {"query": "valuation"}}

    # Then write something down. The artifact types offered are already narrowed
    # to the ones this role may author, so the first is always legal — which is
    # the whole reason the catalogue narrows them.
    draft = next((tool for tool in decision["tools"] if tool["name"] == "draft_artifact"), None)
    if draft is not None and decision["facts"]:
        choices = next(
            (a.get("choices", []) for a in draft["arguments"] if a["name"] == "artifact_type"),
            [],
        )
        cited = _facts(decision, "ops.", "close.") or [decision["facts"][0]["id"]]
        if choices:
            return {
                "tool_name": "draft_artifact",
                "arguments": {
                    "artifact_type": choices[0],
                    # Bounded, because an actor woken late has observed more than
                    # any one document should carry — the tool refuses past forty.
                    "cite_fact_ids": cited[:40],
                    "rationale": "The record of what this role could see at the time.",
                },
            }

    if "add_work_note" in offered and symptom:
        return {
            "tool_name": "add_work_note",
            "arguments": {
                "service_id": symptom["subject"],
                "note": "Reviewed what is on the record so far; nothing further to add yet.",
                "cite_fact_ids": [symptom["id"]],
            },
        }

    # Nothing legal and useful left. Abstention is a real answer here, and the
    # harness records it as one.
    return {
        "tool_name": None,
        "abstention_reason": "nothing this role can usefully do with what it can see",
    }


def overreach(decision: dict[str, Any]) -> dict[str, Any]:
    """A call this role was never offered. The handshake must refuse it."""
    return {
        "tool_name": "post_journal",
        "arguments": {"request_fact_id": decision["facts"][0]["id"], "amount": 1.0},
    }


def main() -> int:
    source, target = sys.argv[1], sys.argv[2]
    bad = "--overreach" in sys.argv[3:]

    document = json.loads(open(source, encoding="utf-8").read())
    if document.get("complete"):
        print("nothing left to decide", file=sys.stderr)
        return 1

    decision = document["decision"]
    action = overreach(decision) if bad else choose(decision)
    payload = {"actions": [{"id": decision["id"], **action}]}
    with open(target, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, indent=2) + "\n")
    print(f"{decision['id']}: {action['tool_name'] or 'abstain'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
