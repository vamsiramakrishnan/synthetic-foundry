---
name: worldloom-probe
description: Derive a world's physics by Socratic drill-down instead of typing ranges — descend org → reporting → roles → objectives → measures, state the constraints between layers, and let arc consistency refuse what cannot hold. Use when a corpus needs to be a specific kind of organisation rather than the engine's default one, when a pack cannot express what a business actually is, or when asked what shapes a set of answers has committed to.
---

# Probing a world

The engine draws every figure from a range written into a generator. Those
ranges have names (`worldloom pack params`), so a pack can override them — but
a list of thirty-seven ranges to fill in is the wrong instrument. They are not
independent: setting a margin without moving markdown cadence and inventory
turns builds the same business with one figure edited. So derive them, by
asking. You are the model in that loop; the harness supplies the structure and
refuses what cannot hold.

## The loop

```
probe_open  →  probe_next  →  answer it  →  probe_answer  →  repeat  →  probe_worlds  →  probe_resolve
```

`probe_answer` hands back the next question with the acceptance, so the middle
of that loop is one call per turn, not two.

Headless equivalents, if you would rather drive the CLI:
`worldloom probe open|next|accept|show|worlds|resolve`. `probe next` exits 3
when the graph is settled, so a driving loop can tell "nothing left to ask"
from "something went wrong" without parsing prose.

Layers descend `organisation → reporting → roles → objectives → measures`. A
level is settled before the one under it opens, and `layer_for_sub_questions`
in each brief names the layer to raise into. An answer is one JSON document per
question — `assets/answer.json` is the shape.

Nothing commits on a refused answer; the refusal names the chain that broke.
Fix that specific thing and resubmit. **A rejection is the harness working.**

## Read next

- `references/answering.md` — what each layer asks, the narrowing rule,
  sub-question relations, cross-layer links, and grounding a range in a source.
  Load before answering the first question.
- `references/objectives.md` — the accountability channel: `answers_for`, the
  tolerance band, and its three refusals. Load when the objectives layer opens.
- `references/endgame.md` — the refusal taxonomy, `probe_worlds` before
  resolving, and why an unbound leaf is the finding. Load on a refusal you do
  not recognise, or when the graph settles.
