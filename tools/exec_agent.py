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
``{{fact:ID}}`` reference — the two rules most likely to reject a first attempt
— so it exists to prove the contract is drivable end to end with no model, no
key and no network, and to be the diff base a real adapter starts from.

Progress goes to stderr. Stdout is the answer, and nothing else.
"""

from __future__ import annotations

import json
import sys


def answer(document: dict) -> dict:
    """Answer every request in *document* under the standing rules."""
    feedback = document.get("feedback")
    responses = []
    for request in document.get("requests", []):
        picked = [f for f in request["facts"] if f["required"]] or request["facts"][:2]
        sentences, claims = [], []
        for fact in picked:
            lead = "It was recorded at the time as" if fact["superseded"] else "The position was"
            sentence = f"{lead} {{{{fact:{fact['id']}}}}}."
            sentences.append(sentence)
            claims.append({"text": sentence, "supporting_fact_ids": [fact["id"]]})
        responses.append({
            "id": request["id"],
            "text": " ".join(sentences),
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
