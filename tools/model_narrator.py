#!/usr/bin/env python3
"""A real-model adapter for Worldloom's agent seam, backed by a coding CLI.

Speaks the child contract exactly: the request document arrives as JSON on
stdin, one responses document leaves on stdout. The writing itself is done by
`claude -p` or `codex exec`, so

    worldloom narrate loop ./corpus --exec "python3 tools/model_narrator.py --backend claude"
    worldloom mosaic -n 4 --narrate-exec "python3 tools/model_narrator.py --backend codex" ...

both work unchanged. The backend only ever sees a self-contained prompt: the
harness's own rules, the facts, and the demand for the exact response shape.
Nothing about Worldloom leaks into the model invocation, and nothing about the
model invocation leaks back except prose that has to survive claim validation.

Stdout carries the responses document and nothing else; every diagnostic goes
to stderr.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys

SCHEMA = """\
{"responses": [{"id": "<the request id>", "text": "<the section prose>",
                "claims": [{"text": "<one sentence of that prose>",
                            "supporting_fact_ids": ["FACT-0001"]}]}]}
"""

INSTRUCTIONS = """\
You are the author writing sections of an enterprise close pack. Below is a
Worldloom request document: rules, then requests[] with each section's facts,
purpose, voice and audience.

Write EVERY request in requests[]. Non-negotiable mechanical rules (a
validator rejects violations):
- Every figure, date, percentage or status appears ONLY as a {{fact:FACT-ID}}
  reference. Zero digits anywhere else in your prose — spell counts/ordinals
  ("two tickets", "first").
- References look EXACTLY like {{{{fact:FACT-0031}}}}: double curly braces,
  lowercase "fact:", no spaces, full id. Never write a bare fact id like
  FACT-0031 into prose, and never space inside the braces.
- Every fact flagged "required": true must appear as a reference.
- Facts flagged "superseded": true are past beliefs: "recorded at the time as
  {{fact:X}}, later superseded".
- Long phrase-valued facts (causes, remediations, classifications,
  workarounds) substitute verbatim: introduce them with a colon
  (`Established cause: {{fact:X}}.`), never weave mid-clause.
- Variance/bps values already contain "adverse" — never add it yourself.
- One claim per sentence that asserts something: split your text into
  sentences; each sentence's claim lists exactly the FACT ids referenced in
  that sentence. Pure transitions need no claim.
- Never use phrases listed in a request's must_not_claim.
- Respect each section's purpose, audience and written_by voice; argue rather
  than list; hit target_words within roughly 40%.
{feedback}
Output ONLY the JSON document, no markdown fences, no commentary:
{schema}
"""


REF = re.compile(r"\{\{\s*fact:\s*(FACT-\d+)\s*\}\}")
SENT = re.compile(r"(?<=[.!?:])\s+")


def sanitize(doc: dict, requests: list[dict]) -> dict:
    """Force the output into what the validators can actually judge.

    The model writes prose; this module owns the plumbing around it. Two
    failure modes seen in the first live hour: claims with empty
    `supporting_fact_ids` (a schema violation that kills parsing downstream),
    and reference spellings like `{{ fact:FACT-0031 }}` (which turn into bare
    digits at validation). Both are mechanical, so both are fixed here:
    references normalised to the canonical spelling, and claims rebuilt from
    scratch — one per sentence, carrying exactly that sentence's references —
    so claim wiring is correct by construction and never trusted to the
    model. The harness's own validator remains the judge of the prose.
    """
    known = {r["id"]: r for r in requests}
    out = []
    for resp in doc.get("responses", []):
        req = known.get(resp.get("id"))
        if req is None or not isinstance(resp.get("text"), str):
            continue
        text = REF.sub(lambda m: "{{fact:" + m.group(1) + "}}", resp["text"])
        valid_ids = {f["id"] for f in req.get("facts", [])}
        claims = []
        for sentence in SENT.split(text):
            ids = sorted({m for m in REF.findall(sentence) if m in valid_ids})
            if ids:
                claims.append({"text": sentence.strip(), "supporting_fact_ids": ids})
        out.append({"id": resp["id"], "text": text.strip(), "claims": claims})
    return {"responses": out}


def extract_responses(raw: str) -> dict:
    """Pull the responses object out of whatever the backend printed."""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.lower().startswith("json"):
            text = text[4:]
    try:
        doc = json.loads(text)
        if isinstance(doc, dict) and "responses" in doc:
            return doc
    except json.JSONDecodeError:
        pass
    # Backend chatter around the answer: find a balanced object naming
    # "responses". Scan candidate braces rather than regex-guessing the span.
    key = text.find('"responses"')
    while key != -1:
        start = text.rfind("{", 0, key)
        depth = 0
        for idx in range(start, len(text)):
            if text[idx] == "{":
                depth += 1
            elif text[idx] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        doc = json.loads(text[start:idx + 1])
                        if isinstance(doc, dict) and "responses" in doc:
                            return doc
                    except json.JSONDecodeError:
                        break
                    break
        key = text.find('"responses"', key + 1)
    raise ValueError(f"no responses document in model output ({len(raw)} bytes)")


BATCH = 5
"""Requests per backend call. One section is what the mosaic seam sends and
it always worked; a whole close (thirty-one) made the backend think for so
long that callers read it as dead. Five keeps each call in the minutes regime
that provably completes while still amortising the instructions across
requests."""


def call_backend(cmd: list[str], prompt: str, *, stdin_prompt: bool,
                 attempts: int = 4) -> str:
    """One backend round trip, retried on quiet transient failures."""
    import time

    last_code = None
    tail = ""
    for attempt in range(1, attempts + 1):
        try:
            done = subprocess.run(
                cmd, capture_output=True, text=True, timeout=1500,
                input=prompt if stdin_prompt else None,
            )
        except FileNotFoundError as exc:
            print(f"backend {cmd[0]!r} not on PATH", file=sys.stderr)
            raise SystemExit(3) from exc
        if done.returncode == 0:
            return done.stdout
        last_code, tail = done.returncode, done.stderr.strip()[-400:]
        # Backends die quietly under load — six sibling writers were enough
        # to starve one here. Backoff before the next attempt; a failure that
        # reaches the harness costs a full extra round of everything.
        time.sleep(5 * attempt)
    print(f"{cmd[0]} exited {last_code}: {tail}", file=sys.stderr)
    raise SystemExit(4)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--backend", choices=("claude", "codex"), default="claude")
    ap.add_argument("--model", default=None, help="model name passed through")
    args = ap.parse_args()

    document = json.load(sys.stdin)
    requests = document.get("requests", [])
    feedback = ""
    if document.get("feedback"):
        feedback = (
            f"\nYour previous attempt was rejected by the validator:\n"
            f"{document['feedback']}\nFix exactly that and resubmit every "
            f"request below.\n"
        )

    collected: list[dict] = []
    for start in range(0, len(requests), BATCH):
        chunk = requests[start:start + BATCH]
        payload = {k: v for k, v in document.items() if k != "brief"}
        payload["requests"] = chunk
        prompt = INSTRUCTIONS.format(feedback=feedback, schema=SCHEMA) + "\n" + \
            json.dumps(payload, ensure_ascii=False)

        cmd = [args.backend]
        stdin_prompt = False
        if args.backend == "claude":
            # Prompt via stdin, never argv: a request document crosses Linux's
            # 128KB single-argument cap long before any model limit, and the
            # failure surfaces as a bare exit 1. `-p` without an argument
            # reads the prompt from standard input.
            if args.model:
                cmd += ["--model", args.model]
            cmd += ["-p", "--output-format", "text"]
            stdin_prompt = True
        else:
            cmd += ["exec", prompt]

        raw = call_backend(cmd, prompt, stdin_prompt=stdin_prompt)
        try:
            out = extract_responses(raw)
        except ValueError as exc:
            print(f"{exc}; tail: {raw.strip()[-300:]}", file=sys.stderr)
            return 5
        out = sanitize(out, chunk)
        print(f"answered {len(out['responses'])}/{len(chunk)}",
              file=sys.stderr)
        collected.extend(out["responses"])

    known = {r["id"] for r in requests}
    collected = [r for r in collected if r["id"] in known]
    if not collected:
        print("model answered zero known request ids", file=sys.stderr)
        return 6
    json.dump({"responses": collected}, sys.stdout, ensure_ascii=False)
    sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
