#!/usr/bin/env python3
"""A reference adapter for the agent seam: stdin request, stdout responses.

Speaks the exact child contract `worldloom narrate loop --exec` and
`worldloom mosaic --narrate-exec` drive — a request document as JSON on stdin,
one responses document as JSON on stdout:

    {"responses": [{"id": "ART-0001/Position", "text": "...",
                    "claims": [{"text": "...", "supporting_fact_ids": [...]}]}]}

so the same command drives one corpus through `narrate loop` or a whole mosaic
of them through `mosaic --narrate-exec`:

    worldloom narrate loop ./corpus --exec "python3 tools/exec_agent.py"
    worldloom mosaic -n 5 --out ./field --narrate-exec "python3 tools/exec_agent.py"

Swap the command string for a wrapper around your own writer (anything that can
read stdin and write stdout) and nothing else changes: the requests, the rules,
the rejection feedback and the validator are all the harness's.

Not an attempt at good prose. It cites every required fact in the section as a
``{{fact:ID}}`` reference (the two rules most likely to reject a first
attempt), and where a request carries moves and a length floor it writes a
paragraph per move at the length each move states. It exists to prove the
contract is drivable end to end with no model, no key and no network, and to
be the diff base a real adapter starts from.

Progress goes to stderr. Stdout is the answer, and nothing else.
"""

from __future__ import annotations

import json
import sys


def _sentence(fact: dict) -> str:
    lead = "It was recorded at the time as" if fact["superseded"] else "The position was"
    return f"{lead} {{{{fact:{fact['id']}}}}}."


def _by_moves(request: dict, picked: list[dict]) -> tuple[str, list[dict]]:
    """A reader-grade section as its brief asks: one paragraph per move, each
    at least the `sentences` its move states, so the section meets its
    `floor` (refused as `section_floor` below it)."""
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


def answer(document: dict) -> dict:
    """Answer every request in *document* under the standing rules."""
    feedback = document.get("feedback")
    responses = []
    for request in document.get("requests", []):
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        if request.get("moves") and (request.get("floor") or {}).get("sentences"):
            text, claims = _by_moves(request, picked)
        else:
            claims = [{"text": _sentence(fact), "supporting_fact_ids": [fact["id"]]} for fact in picked]
            text = " ".join(claim["text"] for claim in claims)
        responses.append({
            "id": request["id"],
            "text": text,
            "claims": claims,
        })
    print(
        f"answered {len(responses)} request(s)"
        + (f" after feedback: {feedback[:120]}" if feedback else ""),
        file=sys.stderr,
    )
    return {"responses": responses}


def main() -> int:
    try:
        document = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        print(f"stdin was not JSON: {exc}", file=sys.stderr)
        return 2
    json.dump(answer(document), sys.stdout)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
