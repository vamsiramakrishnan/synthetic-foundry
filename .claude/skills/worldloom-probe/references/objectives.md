---
title: Objectives Layer
description: Bind an accountability with answers_for and a tolerance band, and avoid its three refusals.
read-when: When the probe's objectives layer opens.
tags: [worldloom, probe, objectives, accountability, refusals]
---

# The objectives layer: binding an accountability instead of a measure, and its three refusals.

The bottom two layers reach the engine by different routes, and this is the one
that used to go nowhere. A **measures** leaf binds a terminal with `binds`, and
its interval is the range the engine draws that figure from. An **objectives**
leaf binds an accountability with `answers_for`: `role_key/fact_kind`, the role
that answers, and the figure it answers for, chosen from the
`accountable_measures` list in your brief. Its interval is then not a range at
all but the **tolerance band**, in per cent: how far that measure may move
before anyone has to explain it. That is what an objective is: a
person, a number, and a band. So the node's interval is already the right
shape, and it propagates like every other: a link from the measure below can
tighten the band you stated.

`assets/objectives-answer.json` is a complete example:

```json
{"answers_for": "gm_md/financial.revenue.variance", "low": 2.0, "high": 3.0}
```

`probe_resolve` returns those as `accountabilities`, each with the
`ConstraintKind.ACCOUNTABILITY` lore constraint already assembled: paste it
into a pack's `lore` and the build mints a fact whose *subject is a person*,
carrying the measure they are judged on and the tolerance. It is the only edge
in the corpus from a human being to a number.

Three things it refuses, and each is the same refusal a measures leaf gets for
the same mistake. `unknown_measure`: a figure no engine mints, so nothing in
the corpus could ever show whether this person met it: the accountability
would be an assertion about a person that no document can check.
`tolerance_out_of_band`: outside 0.1–25 per cent. Tighter than a tenth is
breached by the rounding the corpus prints at, so it fires every period and
names nobody; looser than a quarter is not a tolerance, it is a line nobody is
accountable for. `two_channels`: one leaf setting both `binds` and
`answers_for`, whose interval would have to be a parameter range and a
tolerance simultaneously. Pick the channel you meant.

Choose the band with care: resolution commits to its **tight end**, and the
loose end would assert a laxer regime than your reasoning supports and leave
an accountability edge that never fires.
