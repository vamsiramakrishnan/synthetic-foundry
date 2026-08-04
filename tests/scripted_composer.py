#!/usr/bin/env python3
"""A scripted stand-in for the composing agent, for CI.

Answers a ``worldloom compose requests`` document with a small but *coherent*
estate — layered, owned, and with one genuine chokepoint — so the handshake's
accept path is exercised with no model in the loop. It is not an attempt at a
convincing landscape; the point of asking a model is the industry vocabulary,
and this deliberately does not have any.

``--cycle`` makes it break the acyclicity rule on purpose, so the pipeline can
prove it refuses rather than committing.

    python3 tests/scripted_composer.py request.json response.json [--cycle]

Reads only the request document, never the corpus — the same discipline
``scripted_actor.py`` follows, and for a related reason: a composer that opened
``services.jsonl`` to decide what to propose would be reading past the boundary
the request draws, and the claim that the request is self-contained would stop
being tested by the thing that is supposed to test it.
"""

from __future__ import annotations

import json
import sys


def compose(document: dict, *, cycle: bool) -> dict:
    people = [person["id"] for person in document["people"]]
    systems = [system["id"] for system in document["existing_systems"]]
    if not people:
        raise SystemExit("the request offers nobody who could own a service")

    def owner(index: int) -> str:
        return people[index % len(people)]

    # One private store behind the gateway, which is what makes the gateway a
    # chokepoint rather than merely a busy node: everything reaches that store
    # through it and there is no second path.
    proposed_systems = [{
        "key": "s_private",
        "name": "Access Store",
        "purpose": "Credential and entitlement store, reachable only through the gateway",
        "owner": owner(0),
        "system_of_record_for": ["credential"],
    }]

    services = [
        {"key": "v_gateway", "name": "access-gateway",
         "purpose": "Authenticates and entitles every internal caller",
         "owner": owner(0), "runs_on": "s_private",
         "depends_on": ["s_private"], "criticality_tier": 1},
        {"key": "v_feed", "name": "record-extract",
         "purpose": "Publishes the system of record's daily extract",
         "owner": owner(1), "runs_on": systems[0] if systems else "s_private",
         "depends_on": ([systems[0]] if systems else []) + ["v_gateway"],
         "criticality_tier": 2},
        {"key": "v_reporting", "name": "reporting-service",
         "purpose": "Assembles the periodic reporting pack from the extract",
         "owner": owner(2), "runs_on": systems[0] if systems else "s_private",
         "depends_on": ["v_feed", "v_gateway"], "criticality_tier": 2},
    ]
    if cycle:
        # The gateway now depends on something that depends back on it. Nothing
        # in the estate can start, and the handshake has to say so.
        services[0]["depends_on"].append("v_reporting")

    return {
        "systems": proposed_systems,
        "services": services,
        "lore": [{
            "kind": "decision",
            "assertion": "Access to every internal service was centralised behind a "
                         "single gateway during a 2021 consolidation; no system kept "
                         "its own access list.",
            "effective_from": "2021-03",
            "visibility": "acknowledged",
            "constrains": [{
                "kind": "approval_chains",
                "target": "internal_access",
                "effect": "Every entitlement change goes through the gateway's own "
                          "change record",
                "magnitude": 1.0,
            }],
        }],
    }


def main() -> None:
    if len(sys.argv) < 3:
        raise SystemExit(__doc__)
    source, destination = sys.argv[1], sys.argv[2]
    cycle = "--cycle" in sys.argv[3:]
    document = json.loads(open(source, encoding="utf-8").read())
    payload = compose(document, cycle=cycle)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
    print(
        f"composed {len(payload['services'])} service(s) and "
        f"{len(payload['systems'])} system(s)"
        + (" with a deliberate cycle" if cycle else "")
    )


if __name__ == "__main__":
    main()
