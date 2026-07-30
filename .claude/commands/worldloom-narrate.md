---
description: Write the prose a Worldloom corpus needs, under fact constraints, until accepted
---

Write the narrative for a corpus at $ARGUMENTS (default `./corpus`).

```bash
worldloom narrate requests <CORPUS> -o requests.json
```

Read `requests.json`. It is self-contained: the rules, the facts you may use, which
are required, what the author knew and when, the voice, the audience, the length.

Write `responses.json` with one entry per request, `id` copied exactly:

```json
{"responses": [{"id": "...", "text": "...", "claims": [{"text": "...", "supporting_fact_ids": ["FACT-0001"]}]}]}
```

Then submit:

```bash
worldloom narrate accept <CORPUS> --from responses.json --model-id claude-opus-5
```

**Expect rejection on the first pass, and iterate.** Every violation comes back with
the rule and the offending text. Fix exactly what is named and resubmit. Nothing is
committed until all responses pass.

The rule broken most often is `bare_number` — a figure, percentage, or date typed
out instead of referenced as `{{fact:ID}}`. Never respond to a rejection by editing
the corpus or relaxing a check.

Write documents rather than lists: lead with the position, group what belongs
together, say what it means. Sections were given different facts deliberately.
