---
name: worldloom-probe
description: Derive a world's physics by Socratic drill-down instead of typing ranges — descend org → reporting → roles → objectives → measures, state the constraints between layers, and let arc consistency refuse what cannot hold. Use when a corpus needs to be a specific kind of organisation rather than the engine's default one, when a pack cannot express what a business actually is, or when asked what shapes a set of answers has committed to.
---

# Probing a world

The engine draws every figure from a range written into a generator. Those
ranges have names now (`worldloom pack params`), so a pack can override them —
but a list of thirty-seven ranges to fill in is the wrong instrument. They are
not independent. Setting a margin without moving markdown cadence and inventory
turns does not build a different business; it builds the same business with one
figure edited.

So derive them, by asking. You are the model in that loop. The harness supplies
the structure and refuses what cannot hold.

## The loop

```
probe_open  →  probe_next  →  answer it  →  probe_answer  →  repeat  →  probe_worlds  →  probe_resolve
```

`probe_answer` hands back the next question with the acceptance, so the middle
of that loop is one call per turn, not two.

Headless equivalents, if you would rather drive the CLI:
`worldloom probe open|next|accept|show|worlds|resolve`. `probe next` exits 3
when the graph is settled.

## Descend the layers, and stay in the one you are given

`organisation → reporting → roles → objectives → measures`.

A layer is a *kind* of question, not a distance from the root, and a level is
settled before the one under it opens. This is the part that makes a probe about
an organisation rather than about a category called "retailer":

- **organisation** — how it divides. Units, regions, headcount, what the work is.
- **reporting** — how it hangs together. Span of control, levels, where authority
  actually sits versus where the chart says it does.
- **roles** — what the shape implies. Which titles have to exist, how many rungs
  need naming, which functions are represented at each level.
- **objectives** — what those roles are accountable for. What a regional manager
  is actually judged on, and what nobody owns.
- **measures** — the figures those accountabilities are measured by. Only here do
  numbers bind to the engine.

`layer_for_sub_questions` in each brief tells you which layer to raise into. Use
it rather than inventing a name — two names for one level is how a probe stops
being a structure.

## Answer like this

**A question you are asked is not a request for a number.** If the quantity
follows from things nobody has asked about yet, say so in your claim and raise
those as sub-questions. Span of control is not a number you know about a
business; it is what the work's standardisation and the supervision it needs
produce. Raise both, relate them, and let the span narrow to what they allow.

**You may narrow a question. You may never widen one.** The bounds you are given
are what earlier answers established, propagated through every relation in the
graph. They are not a suggestion and the harness will not let you past them.

**Every sub-question needs a relation.** `scales` (child is parent times a
factor range), `complements` (child is one minus parent), `at_most`, or `free`.
`free` is allowed and is a *claim* — you are asserting there is no arithmetic
tie — not a default to reach for when the relation is hard to state.

**Link across layers.** When two questions in different layers cannot be set
independently, say so with a `link` rather than by quietly choosing values that
happen to agree. Headcount, span and levels are three numbers with two degrees
of freedom; a link is how you state that, and the graph then enforces it on
every answer that follows, including ones you have not seen yet. Links propagate
in *both* directions — this is what lets a measure you discover at the bottom
make a reporting structure you asserted at the top untenable.

## Answering an objectives-layer question

The bottom two layers reach the engine by different routes, and this is the one
that used to go nowhere. A **measures** leaf binds a terminal with `binds`, and
its interval is the range the engine draws that figure from. An **objectives**
leaf binds an accountability with `answers_for`: `role_key/fact_kind` — the role
that answers, and the figure it answers for, chosen from the
`accountable_measures` list in your brief. Its interval is then not a range at
all but the **tolerance band**, in per cent: how far that measure may move
before anyone has to explain it. Which is exactly what an objective is — a
person, a number, and a band — so the node's interval is already the right
shape, and it propagates like every other: a link from the measure below can
tighten the band you stated.

```json
{"question": "gm_md_revenue_accountability",
 "claim": "The divisional MD answers for revenue against budget; anything past three per cent goes to the CFO.",
 "answers_for": "gm_md/financial.revenue.variance", "low": 2.0, "high": 3.0}
```

`probe_resolve` returns those as `accountabilities`, each with the
`ConstraintKind.ACCOUNTABILITY` lore constraint already assembled — paste it
into a pack's `lore` and the build mints a fact whose *subject is a person*,
carrying the measure they are judged on and the tolerance. It is the only edge
in the corpus from a human being to a number.

Three things it refuses, and each is the same refusal a measures leaf gets for
the same mistake. `unknown_measure`: a figure no engine mints, so nothing in
the corpus could ever show whether this person met it — the accountability
would be an assertion about a person that no document can check.
`tolerance_out_of_band`: outside 0.1–25 per cent. Tighter than a tenth is
breached by the rounding the corpus prints at, so it fires every period and
names nobody; looser than a quarter is not a tolerance, it is a line nobody is
accountable for. `two_channels`: one leaf setting both `binds` and
`answers_for`, whose interval would have to be a parameter range and a
tolerance simultaneously. Pick the channel you meant.

Choose the band deliberately, because resolution commits to its **tight end** —
the loose end would assert a laxer regime than your reasoning supports and leave
an accountability edge that never fires.

## The refusals are computed, not listed

Nobody wrote down which combinations are illegal. Every relation is invertible,
so after each answer the whole graph is narrowed to arc consistency; if some
question's range empties, your answer is refused naming the chain that broke.
A rejection is the harness working. Read the chain, fix the specific thing.

Common ones: `widens_the_question` (your interval left the bounds — it names the
end and by how much), `contradicts` (well-formed but cannot hold alongside what
you already said), `unexplained` (a sub-question or link with no reasoning under
it), `bound_branch` / `accountable_branch` (only leaves bind, either way).

## Two things at the end

**`probe_worlds` before you resolve.** A settled probe describes a *space* of
worlds, not one. This returns the ones furthest apart in it — deterministically,
by covering the space with a low-discrepancy sequence and taking a farthest-point
traversal. If they all look the same, your graph is over-constrained and you
have written one world with extra steps. If they look incoherent, a link is
missing.

**Unbound leaves are the finding, not the failure.** A leaf that binds to no
terminal parameter is a quantity this world needed and the engine cannot read.
`probe_resolve` reports it rather than dropping it. Say what it should have been
called — that report is the only honest argument for adding a parameter to the
engine, and it only exists because you left it unbound instead of forcing it
into a terminal that nearly fits.

## Grounding

`source` records where a range came from. If you have web search, use it — a
sector statistic beats your recollection of one, and the corpus can then say
what it was calibrated against.

The boundary holds and is worth stating at the point of temptation: **sector
aggregates and published benchmarks are priors and are welcome; a named
company's own figures are not.** This corpus is fictional and has to stay that
way. The harness cannot tell the difference and does not pretend to — the field
records provenance, it does not launder it.
