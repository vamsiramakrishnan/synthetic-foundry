---
title: Cascade Verbs
description: Drive any layer's cascade from Python with the four shared verbs — open, next_stage, accept, resolve.
read-when: Working a layer's loop directly from Python rather than through its slash command.
tags: [worldloom, cascade, python, sessions, refusal-loop]
---

# Driving a cascade from Python

Every cascade module exposes the same four verbs.

```python
from worldloom import lob, process   # every cascade has the same verbs

session = lob.open(seed)             # or process.open(seed, facets=...)
brief = lob.next_stage(session)      # stage, asks, context — answer from this alone
try:
    session = lob.accept(session, answer)
except ValueError as refusal:        # findings: what, which rule, what to do
    ...                              # revise that specific thing; session unchanged
spec = lob.resolve(session)          # only this rides the pack/recipe
```

What the shape buys you:

- A `Session` is a frozen value of accepted stages. `accept` returns a new
  one; a refusal leaves the old one untouched, so refusals cost nothing and
  you always revise against exactly the state that judged you.
- The seed is validated at `open` — a malformed seed (bad key pattern,
  missing field, extra field) is refused there with every error at once, not
  discovered mid-cascade.
- A session resumes by replaying its accepted answers through
  `open`/`accept`; there is no hidden state to lose.
- The brief is the boundary: answer from `next_stage`'s context and
  constraints alone. If a fact or bound is not in the brief, the answer may
  not use it.
- Only `resolve`'s output rides the pack or recipe. The conversation is
  working state — never recorded, never replayed.
