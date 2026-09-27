---
description: Write the prose a Worldloom corpus needs, under fact constraints, until accepted
tags: [worldloom, narration, prose]
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
the rule and the offending text. Fix what is named and resubmit. Nothing is
committed until all responses pass.

The rule broken most often is `bare_number`: a figure, percentage, or date typed
out instead of referenced as `{{fact:ID}}`. Never respond to a rejection by editing
the corpus or relaxing a check.

Write documents rather than lists: lead with the position, group what belongs
together, say what it means. Sections were given different facts for a reason.

A request from a reader-grade corpus (`enterprise/v2`, the default) carries
`moves`: write one paragraph per move, in order, each drawing on the facts its
move lists (a `derived` move reasons from facts already cited), and use
`display_names` for subjects recorded as slugs. Each fact's `statement` shows
the figure as the page will print it ("AUD 10.2m adverse", "AUD 958k", "nil"):
write the sentence around the reference and add no unit, currency or
direction word (refused as `number_spelling`; a clause that already says the
direction, "missing plan by", "fell", "below budget", makes the page drop the
"adverse"), and never type a recorded identifier such as `control_failure`
(refused as `slug_leak`, with the words to use). Each move states the fewest
`sentences` its paragraph says and the request's `floor` the least the
section says in total; a section below it is refused as `section_floor`
(a `floor` with `exempt` has fewer facts than moves and no floor).

For the full rule set, the rejection reasons in detail, and what good prose looks
like for this harness, read `references/writing-prose.md`.
