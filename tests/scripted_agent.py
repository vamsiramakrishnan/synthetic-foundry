#!/usr/bin/env python3
"""A scripted stand-in for the driving agent, for CI.

Answers every request in a Worldloom request document. Not an attempt at good
prose — it exists so the handshake contract is exercised in CI without a model in
the loop. ``--restate`` makes it break the arithmetic rule on purpose, so the
pipeline can prove it rejects.

    python3 tests/scripted_agent.py requests.json responses.json [--restate]
"""

from __future__ import annotations

import json
import sys


def answer(document: dict, *, restate: bool) -> dict:
    responses = []
    for request in document["requests"]:
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        sentences, claims = [], []
        for fact in picked:
            lead = "It was recorded at the time as" if fact["superseded"] else "The position was"
            sentence = f"{lead} {{{{fact:{fact['id']}}}}}."
            sentences.append(sentence)
            claims.append({"text": sentence, "supporting_fact_ids": [fact["id"]]})
        text = " ".join(sentences)
        if restate:
            text += " Revenue finished 2.48% below plan."
        responses.append({"id": request["id"], "text": text, "claims": claims})
    return {"responses": responses}


def main() -> int:
    if len(sys.argv) < 3:
        print(__doc__)
        return 2
    source, destination = sys.argv[1], sys.argv[2]
    restate = "--restate" in sys.argv[3:]

    with open(source, encoding="utf-8") as handle:
        document = json.load(handle)
    with open(destination, "w", encoding="utf-8") as handle:
        json.dump(answer(document, restate=restate), handle, indent=2)

    print(f"answered {len(document['requests'])} request(s) -> {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
