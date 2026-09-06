---
title: Probe Endgame
description: Read a probe refusal's chain, check the world-space before resolving, and report unbound leaves.
read-when: On a refusal you do not recognise, or when the graph settles.
tags: [worldloom, probe, refusals, arc-consistency, resolve]
---

# Reading a refusal, checking the world-space before resolving, and what an unbound leaf means.

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
