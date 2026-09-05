---
name: worldloom-synthesis
description: Generate operational relational data, author causal specifications, run paired interventions, search behavior regimes, or compose coding harnesses for Worldloom synthetic data.
---

# Operational synthesis

Read `AGENTS.md`, then `docs/operational-synthesis.md`. Use this skill when the
requested dataset needs transactions, inventory, balances or exception histories
rather than more document templates.

## Decide what must be true

Name the entities, relationships, units, initial state, transitions and
conservation equations. State whether a distribution is an assumption or fitted
to evidence. A retailer is not a bank with different nouns. Start with the retail
or banking example only when its mechanisms fit the task.

```bash
worldloom synth example retail program.json --entities 8 --ticks 30
worldloom synth check program.json
worldloom synth build program.json records --seed 8128
worldloom synth verify records
```

The harness may author the JSON expression tree. It may not introduce Python
execution into that tree, turn floats into currency, silently repair failed
constraints, or invent references. Operator limits are not proposal fields.

## Test the mechanism

Use a paired intervention, not a fresh random world. Confirm unchanged entity
IDs and noise, changed descendants, and unchanged unrelated trajectories.

```bash
worldloom synth intervene records interventions.json counterfactual
worldloom synth compare records counterfactual
```

Prove shard invariance before increasing the population.

```bash
worldloom synth build program.json shard-0 --shard-index 0 --shard-count 2
worldloom synth build program.json shard-1 --shard-index 1 --shard-count 2
worldloom synth merge merged shard-1 shard-0
```

## Search, then audit

Choose behavioral axes and useful target intervals before search. Do not let a
candidate remove a gate or change the evaluator. Keep training and holdout seeds
disjoint. Report failed holdout champions as failed.

```bash
worldloom synth search program.json search-report.json --proposals 32
worldloom synth team program.json evaluator.json agents.json team-report.json --checkpoint receipts
worldloom synth team program.json evaluator.json agents.json replay-report.json --replay-ledger team-report.json
```

Designers propose bounded parameter values. Critics inspect training measurements
and advise. Validators decide acceptance. Describe a team as executed only when
its configured processes actually ran. A stub adapter is a contract test, not a
model experiment. Do not start paid or privileged executables that the operator
has not selected.

## Deliver evidence

Export the program, recipe, records, manifest, search report and applicable
receipts. Use an industry-specific operational profile for enterprise queries.
Use strict sources and retain the operational ledger. Never relabel a generated
row ID as a World fact ID or claim macro reconciliation without checking it.

Report the rows generated, actual invariants exercised, occupied behavior cells,
holdout outcomes, replay result, process calls made and outstanding limitations.
Do not claim statistical realism from conservation alone.
