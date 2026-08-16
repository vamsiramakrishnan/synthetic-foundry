---
title: Outline variety and the readings
description: Vary document outlines so a type is not a template, and read topology, series, and diversity.
read-when: Documents of one type all share a skeleton, or before calling a corpus measured.
tags: [outlines, diversity, topology, series, measurement]
---

# One type, several arguments

A six-period corpus produced 32 distinct shapes across 249 artifacts and every
near-duplicate group was exactly ×6 — the same document once per period, the
same headings in the same order. Six close calendars with different dates is
realistic. Six root-cause reviews with an identical five-section skeleton is
not: real reviews differ because the incidents differ, and a reader who sees the
skeleton six times learns the skeleton rather than the content.

Six types now carry alternative outlines (`documents._OUTLINE_VARIANTS`), and
each alternative is a different *argument* rather than a reshuffle — an RCA that
opens with the cause is a different document from one that opens with the
timeline, and a commentary that leads with the exception is what a partner
writes when the month went wrong. The variant is chosen by the document's
ordinal among its own type, so N instances over M variants land evenly by
construction; a seeded draw would only tend to spread. The first variant is the
outline that shipped, so a type's first instance is unchanged.

Measured: 40 shapes, largest group 37 → 18.

## Three more readings

Three more readings answer questions `validate` and `evaluate` cannot, and each
one is a different question — read all four before calling a corpus measured:

```bash
worldloom topology ./corpus              # what depends on what, and what nothing routes around
worldloom series ./corpus                # trend, season, and the periods neither explains
worldloom diversity ./corpus --near-duplicates   # which documents are one template
```

`topology` reads the estate as a graph: services ranked by *blast radius* (how
much falls over transitively when one does) and separately by *gates* (how much
has no second path to what it serves — a well-replicated platform has a large
blast radius and gates nothing). Its ranking is derived from the graph, so it
can disagree with the hand-declared `criticality_tier`, and a zero-hop
dependency chain means an archetype's service catalogue is a flat list rather
than a system.

`series` decomposes a period-keyed fact series into trend, season, and residual,
and names the periods the first two do not explain. Worth building a history for
first: `--comparatives 23 --trend 0.004` gives two years with a direction in
them, where the default flat level makes every seasonally-adjusted month look
like every other.
