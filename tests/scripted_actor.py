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

    It advances on ``turn`` rather than re-deciding from scratch each time. An
    earlier version picked the first matching tool every turn, which meant
    ``search_incidents`` — offered to every role — matched forever: the episode
    burned each invocation's whole budget repeating one read, and the call count
    looked healthy while nothing progressed.
    """
    offered = {tool["name"] for tool in decision["tools"]}
    turn = decision["turn"]
    symptom = _latest(decision, "ops.feed_status", "ops.incident_opened", "ops.incident_state")

    if turn == 0:
        # Look first. Every role in this episode does, and it is always legal.
        if "query_logs" in offered and "sys_erp" in decision["resources"]:
            return {"tool_name": "query_logs",
                    "arguments": {"system_id": decision["resources"]["sys_erp"]}}
        if "inspect_dependencies" in offered and symptom:
            return {"tool_name": "inspect_dependencies",
                    "arguments": {"service_id": symptom["subject"]}}
        for name in ("read_ledger", "query_budget"):
            if name in offered and "company" in decision["resources"]:
                return {"tool_name": name,
                        "arguments": {"subject_id": decision["resources"]["company"]}}
        if "search_incidents" in offered:
            return {"tool_name": "search_incidents", "arguments": {"query": "valuation"}}

    if turn == 1:
        # Raise the ticket, if that is this role's job. Without it no incident is
        # ever recorded, every gated downstream route stays shut, and the episode
        # ends after two invocations.
        # The failing feed specifically, not `symptom` — that helper takes the
        # newest of several kinds, and once the incident-opened fact is in view
        # it wins, which left the guard below never matching.
        failure = _latest(decision, "ops.feed_status")
        if "create_incident" in offered and failure is not None:
            return {
                "tool_name": "create_incident",
                "arguments": {
                    "service_id": failure["subject"],
                    "priority": "P2",
                    "summary": "Feed failure reported against this service.",
                    "evidence_fact_ids": [failure["id"]],
                    "notify_role_keys": [
                        k for k in ("svc_incident", "platform_senior")
                        if k in decision["roles"]
                    ],
                },
            }
        if "add_work_note" in offered and symptom:
            return {
                "tool_name": "add_work_note",
                "arguments": {
                    "service_id": symptom["subject"],
                    "note": "Reviewed what is on the record so far.",
                    "cite_fact_ids": [symptom["id"]],
                },
            }

    if turn == 2:
        # Write something down. The artifact types offered are already narrowed
        # to the ones this role may author, so the first is always legal.
        draft = next(
            (t for t in decision["tools"] if t["name"] == "draft_artifact"), None
        )
        if draft is not None and decision["facts"]:
            choices = next(
                (a.get("choices", []) for a in draft["arguments"]
                 if a["name"] == "artifact_type"),
                [],
            )
            cited = _facts(decision, "ops.", "close.") or [decision["facts"][0]["id"]]
            if choices:
                return {
                    "tool_name": "draft_artifact",
                    "arguments": {
                        "artifact_type": choices[0],
                        # Bounded: an actor woken late has observed more than any
                        # one document should carry, and the tool refuses past 40.
                        "cite_fact_ids": cited[:40],
                        "rationale": "The record of what this role could see at the time.",
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
