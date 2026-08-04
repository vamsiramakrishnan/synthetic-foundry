---
name: worldloom-refine
description: Close the loop on a Worldloom corpus — measure what it repeats, rewrite only the sections that repeat, and prove each rewrite moved. Use when a corpus is narrated but monotonous, when `worldloom diversity --near-duplicates` reports groups, or when asked to make a corpus less like one document photocopied.
---

# Refining a corpus

Narration is open-loop. Every section gets one request and one attempt, and
nothing afterwards looks at what the corpus became — so the writer of section 47
never learns that sections 12 and 31 already said this. A three-period grocery
corpus comes out with **44 of its 130 passages in 16 near-duplicate groups**.

You are the loop that fixes that. The tools do the measuring and the judging;
you do the writing.

## The loop

```
measure_corpus   →  next_target  →  write it  →  submit_section  →  repeat
```

1. **`measure_corpus`** once at the start. Note `repeated_passages`; that is the
   number you are driving down.
2. **`next_target`** gives you *one* section: its full brief (the facts it may
   cite, what it may not claim, what its author could know) and the passage it
   is currently indistinguishable from.
3. **Write the section.** Same facts, genuinely different document.
4. **`submit_section`.** Accepted rewrites are committed and the corpus is
   re-measured for you. Rejected ones come back with the reason.
5. Go to 2 until `next_target` returns `{"done": true}`.

Take one target at a time. Writing sixteen sections and then measuring is the
open loop again with extra steps — each target is chosen against a corpus that
includes your previous rewrite.

## Before you start

Write the marker so the Stop hook can hold you to the loop:

```bash
mkdir -p .worldloom && echo "<corpus path>" > .worldloom/refining
```

While that file exists you cannot end the session with duplicates outstanding —
the hook re-runs the measurement and blocks the stop with the number still open.
If you genuinely need to stop early, delete the file. That is the explicit exit,
and it leaves a trace that the loop was abandoned rather than finished.

## Writing a rewrite that passes

Two gates, and they fail for different reasons.

**The fact gate** is the one narration already has, unchanged. Every figure is
`{{fact:ID}}` and never digits. Every assertion needs supporting fact ids.
Nothing outside the brief may be mentioned. Facts marked required must appear.
Widening how much you may *vary* does not widen what you may *assert*.

**The similarity gate** is the new one. Your rewrite is substituted and measured
against the passage you were told to avoid; it must come in at or below the
stated ceiling. A rejection quotes the number.

The failure this exists to catch is the reword: change every phrase, keep the
same structure, and it reads as new to you and scores as identical to a
retriever. What actually moves the number:

- **Lead with something else.** If the avoided passage opens on the close
  status, open on the driver, or the decision, or the thing that did not happen.
- **Change what is subordinate.** A fact that carried a sentence becomes a
  clause; a clause becomes the point.
- **Leave things to the table.** A section whose figures are all in a table
  beside it does not have to narrate every one of them.
- **Change the register.** The brief carries the author's voice and traits — a
  different author under pressure writes a different paragraph about the same
  facts.

Do not chase the ceiling. A rewrite that lands just under it is a passage that
will read as a near-duplicate to anyone who opens both.

## When you are done

```
validate_corpus   the coherence gate must still pass
measure_corpus    repeated_passages should be near zero
```

Then report what moved: passages before and after, groups closed, and how many
sections you actually rewrote. That last number is the point of the loop — a
corpus with 130 sections and 16 duplicates needs 16 rewrites, not 130.

## The other readings

Two tools that are not part of the loop but answer questions that come up while
you are in it:

- **`corpus_topology`** — what depends on what, services by blast radius and by
  gates. A dependency chain of zero hops means the estate is a flat list.
- **`corpus_series`** — trend, season, and the periods neither explains. On a
  corpus with an incident in it, an incident month that does *not* stand out is
  a corpus asserting a disruption its own figures do not show.

## Headless

The same loop without a session, for CI or a batch:

```bash
worldloom refine ./corpus --harness claude-code --rounds 3
```

It runs the identical algorithms — same targeting, same gate, same ceiling — so
the two paths cannot drift into different definitions of "better".
