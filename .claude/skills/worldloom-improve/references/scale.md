---
title: Running the Loop at Scale
description: Concurrency, shards, merge and resume for the runs a loop pays for, and why none of them changes a byte of output.
read-when: A round is too slow, runs should spread across processes or machines, or a run was killed.
tags: [worldloom, evalrun, concurrency, shards, resume]
---

# Scale: concurrency, shards, resume

Read this when a round is too slow, when runs should spread across processes
or machines, or when a run was killed part way.

A round runs two agents over the training cases and, when the candidate
passes, two more over the held-out cases. The loop is therefore as fast as a
run. None of the mechanisms below changes what a run writes: a deterministic
agent leaves the same bytes concurrent, resumed or sharded as in one process.

## Concurrency inside the loop

```python
loop = session.improver(agent=session.harness("codex"), proposer=session.proposer("codex"),
                        out="./improve", concurrency=8)
```

`concurrency` reaches both `service_for(..., concurrency=)`, which raises the
serving limits to admit that many runs under one principal, and
`run_cases(..., concurrency=)`, which keeps that many cases in flight on a
thread pool, each on its own fork. Results come back in case order, so
receipts and run directories are identical at 1 and at 8. The default is the
policy `evalrun.concurrency` (1). `session.run(agent, concurrency=8)` does the
same for a single run. An agent must tolerate calls from several threads; the
shipped agents do, and an `--exec` agent is a subprocess per turn.

The CLI `evalrun improve` runs its cases in order; use the SDK when a loop
needs concurrency.

## Runs outside the loop

```bash
worldloom evalrun run ./cases -o ./runs/mine --harness codex --agent-pack agent:baseline --concurrency 8
worldloom evalrun run ./cases -o ./runs/mine --harness codex --agent-pack agent:baseline --concurrency 8 --resume
worldloom evalrun run ./cases -o ./runs/shard-1 --harness codex --agent-pack agent:baseline --shard 1/4
worldloom evalrun merge ./runs/mine ./runs/shard-1 ./runs/shard-2 ./runs/shard-3 ./runs/shard-4
```

- **Resume.** `--resume` keeps a ledger whose `run.json` names the same agent,
  principal, case set, agent pack and grader (and shard), and grades only the
  cases it lacks. A ledger for a different run is refused, each difference
  named.
- **Shards.** `--shard i/n` partitions by a stable hash of the case id, so every
  machine computes the same split. `evalrun merge` joins shards byte for byte
  and refuses mismatched, duplicated, unfinished or missing ones.
- **The loop resumes too.** A run already in `runs/` for the same pack digest,
  case set and grader is read instead of repeated, so rerunning an
  interrupted loop into the same output directory continues it.

Details: `docs/eval-execution.md`, section "Running at scale".
