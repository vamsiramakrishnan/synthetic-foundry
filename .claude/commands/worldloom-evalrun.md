---
description: Run an agent against a compiled case set and grade plan, trajectory and outcomes separately
tags: [worldloom, evalrun, agents, trajectory, outcomes]
---

Evaluate an agent on the case set at $ARGUMENTS (default `./cases`, a directory
written by `worldloom enterprise-evals build`). This is not retrieval scoring;
for that use `/worldloom-evaluate`.

```bash
worldloom evalrun cases <CASES>                       # what the set can grade; a zero is a named gap
worldloom evalrun run <CASES> -o ./runs/reference     # the reference agent: the executable ceiling
worldloom evalrun run <CASES> -o ./runs/mine --exec "python3 my_agent.py"
worldloom evalrun compare ./runs/reference ./runs/mine
worldloom evalrun plan <CASES> -o ./runs/planner --exec "python3 my_planner.py"   # querying alone
```

Read the coverage first and report every zero. Run the reference before any
agent; a reference case that fails is a finding about the case. Then run the
agent under test through one of three transports: `--exec` (an executable,
one subprocess per turn, the transcript as its only memory; the contract is
in the `worldloom-evalrun` skill's `references/protocol.md`), `--agent
scripted:responses.json` (replay of a document written against `worldloom
evalrun requests <CASES> -o requests.json`), or MCP via `worldloom
enterprise-evals serve`. `--timed` records latency; it is off by default so
runs are byte-reproducible.

Report per axis, not one number: plan (node and edge recall, extra writes),
trajectory (order, budget, designed failures honoured, safety findings),
outcomes (structured expectations met, collateral writes, grounding, answer).
An error row means the agent broke; it is excluded from every mean and is
never a zero. `compare` names which axis moved and which cases changed
reliability rather than score. `import-studio <CASES> results.csv -o
./runs/studio` brings Gemini Enterprise Eval Studio's CSV in as an
answer-axis-only run for the same comparison. `plan` grades a planner on the
plan axis alone (a plan document on stdin, a DAG on stdout, nothing run); its
other axes are unobserved, never zero. Deletes are graded only on a build
made with `--dag-shape delete_chain` against a destination whose connector
serves a delete.
