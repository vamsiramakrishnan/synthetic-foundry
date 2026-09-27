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


def _sentence(fact: dict) -> str:
    lead = "It was recorded at the time as" if fact["superseded"] else "The position was"
    return f"{lead} {{{{fact:{fact['id']}}}}}."


def _by_moves(request: dict, picked: list[dict]) -> tuple[str, list[dict]]:
    """A reader-grade section as its brief asks: one paragraph per move, each at
    least the `sentences` its move states, so the section meets its `floor`.
    The same shape as `tools/exec_agent.py`."""
    by_id = {fact["id"]: fact for fact in request["facts"]}
    cited: set[str] = set()
    claims: list[dict] = []
    paragraphs = []
    for move in request["moves"]:
        lines = []
        for index in range(max(1, move.get("sentences", 1))):
            fid = move["facts"][index] if index < len(move["facts"]) else None
            if move.get("derived") or fid is None or fid in cited:
                lines.append("That is the part of the position the period turns on.")
                continue
            sentence = _sentence(by_id[fid])
            lines.append(sentence)
            cited.add(fid)
            claims.append({"text": sentence, "supporting_fact_ids": [fid]})
        paragraphs.append(" ".join(lines))
    for fact in picked:
        if fact["id"] not in cited:
            sentence = _sentence(fact)
            paragraphs[-1] += " " + sentence
            claims.append({"text": sentence, "supporting_fact_ids": [fact["id"]]})
    return "\n\n".join(paragraphs), claims


def answer(document: dict, *, restate: bool) -> dict:
    responses = []
    for request in document["requests"]:
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        if request.get("moves") and (request.get("floor") or {}).get("sentences"):
            text, claims = _by_moves(request, picked)
        else:
            claims = [{"text": _sentence(fact), "supporting_fact_ids": [fact["id"]]} for fact in picked]
            text = " ".join(claim["text"] for claim in claims)
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
