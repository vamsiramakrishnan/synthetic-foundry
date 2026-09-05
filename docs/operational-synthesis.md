# Operational synthetic data

Documents describe business activity. They should not be the only place that
activity exists. `worldloom.synthesis` generates the records below the documents:
related entities, quantities, state transitions, observations and exception
histories. It is an opt-in SDK and CLI. Existing World recipes are unchanged.

The shipped programs cover store-product inventory and loan servicing. They are
inspectable simulation assumptions, not models fitted to a real customer.

```text
operator-owned program and evaluator
        |
        +-- static dimensions: stores, products, borrowers
        |
        +-- per-entity trajectories: inventory, loan balances
        |       |
        |       +-- keyed exogenous noise
        |       +-- same-tick dependency graph
        |       +-- explicit lagged state
        |       +-- hard constraints
        |
        +-- canonical records + recipe + manifest
                |
                +-- paired interventions and exact deltas
                +-- behavioral archive and held-out seed checks
                +-- exception episodes -> connector records -> query fixtures
```

## Generate records

```bash
worldloom synth example retail retail.json --entities 8 --ticks 30
worldloom synth check retail.json
worldloom synth build retail.json retail-data --seed 8128
worldloom synth verify retail-data
```

For retail, `--entities` sets stores; the example has twelve products per store.
For banking it sets borrowers. An export contains `recipe.json`,
`records.jsonl`, and `manifest.json`. Every record has an entity ID, a row ID, a
tick, typed cells and explicit foreign keys. The manifest commits to the recipe,
record bytes and table counts. Verification re-executes the recipe and compares
every record; recomputing a checksum over fabricated records does not pass.

The SDK exposes the same operations:

```python
from pathlib import Path
from worldloom.synthesis import Simulator, export, retail, verify_export

simulation = Simulator(retail(stores=8, products=12, ticks=30), seed=8128)
manifest = export(simulation, Path("retail-data"))
assert verify_export(Path("retail-data")) == manifest
```

## Declare mechanisms, not executable strings

A `Program` contains frozen `Table`, `Column`, `Relation`, `Parameter` and
`Constraint` models. Columns contain a closed expression tree. There is no
`eval`, Python source, model SDK, SQL execution or dynamic import in that tree.

Operations include integer arithmetic, comparisons, booleans, conditionals,
parameter references, column references, bounded draws and lagged values.
`div` means integer floor division. Money is integer minor currency units.
Intermediate overflow against the operator's bound is a refusal, not a clamp.
Column `unit` is metadata; dimensional analysis is not implemented.

Same-tick references form a directed acyclic graph. `lag("closing", initial)`
reads the preceding tick, with an explicit initial condition. Relations target
static dimensions. Cross-entity, mutable temporal joins are deliberately
unsupported; silently sampling another trajectory would break partitioning.

Retail distinguishes demand from sales. Sales are bounded by available stock.
Closing stock carries into the next tick. Replenishment arrives after two ticks.
New orders account for stock already in the pipeline. Stock and demand each
have a conservation equation. Banking carries balances, capitalized interest,
cash receipts, arrears and consecutive missed periods. Its balance equation is
checked for every borrower and tick.

The integer-uniform sampler maps a fixed 63-bit draw onto a bounded interval.
`cell` scope varies by entity and tick. `entity` produces a stable trait.
`tick` produces a shock shared across entities. `world` produces a run-level
constant. An explicit stream name identifies the exogenous variable. Sharing
a name and scope intentionally shares noise; adding a column does not advance
another column's stream. Quantization can introduce less than one part in
2^63 of probability error per outcome; this is not a fitted continuous sampler.

## Paired interventions

Create `demand-shock.json`:

```json
[{"table":"inventory","column":"demand","value":100,"start":3,"stop":5,"entities":[0]}]
```

```bash
worldloom synth intervene retail-data demand-shock.json retail-shock
worldloom synth compare retail-data retail-shock
```

A do-intervention replaces one declared, intervenable mechanism. It does not
redraw the world. Identity and exogenous noise remain fixed. The selected
trajectory changes, and its lagged consequences can continue after the
intervention ends. Overlapping replacements are refused. Protected columns,
invalid populations and invalid windows are refused before generation.

`compare` returns exact cell deltas. It rejects mismatched seeds, namespaces,
populations, columns or relationships. These are counterfactuals **under the
authored simulation**, not identified causal effects in a real business.

## Partition and resume

```bash
worldloom synth build retail.json part-0 --shard-index 0 --shard-count 2
worldloom synth build retail.json part-1 --shard-index 1 --shard-count 2
worldloom synth build retail.json part-0 --shard-index 0 --shard-count 2 --resume
worldloom synth merge retail-merged part-1 part-0
```

Partitioning selects complete entity trajectories. It never starts a shard in
the middle of an inventory balance. Each worker rebuilds the static dimensions;
only its assigned records are emitted. Memory is bounded by the static dimension
cache and one trajectory's lag ring, not by the number of time-series records.

Completed shards can be resumed after verification. An incomplete trajectory is
recomputed; there is no intra-trajectory checkpoint. Merge requires a complete,
duplicate-free shard set from one recipe. It verifies shards, performs a sorted
merge and rechecks their checksums. Its three output files match a direct,
unsharded export byte-for-byte. Outputs are staged before publication. Existing
destinations are never overwritten. Publication is not a filesystem power-loss
durability guarantee.

`Limits` belongs to the caller. It bounds rows, cached dimension cells,
expression depth and work, lags, interventions, and total planned search work.
Programs and model proposals cannot raise it. The merge API opens at most 128
shards; this is an explicit implementation limit.

## Search for behavior

```bash
worldloom synth search retail.json retail-search.json --proposals 32
```

This is quality-diversity search over bounded parameters. It retains the best
candidate in each observed behavior cell. Retail cells use stockout frequency
and mean closing inventory. Banking cells use arrears frequency and missed
periods. These are measurements of generated rows, not document-shape counts.

The operator owns the metrics, axes, target intervals, hard gates, seeds and
limits. Only parameters marked `mutable` can change. Mutation rotates across
those parameters; every third proposal can also recombine archive parents.
Candidates cannot remove a constraint, rename a measurement or alter the
fitness definition. Duplicate proposals are recorded without reevaluation.

Hard gates are checked on **every** training seed before admission. Quality is
negative weighted distance from target intervals. Ties use the program digest.
Held-out seeds run after the training archive is complete and do not influence
parent selection. Each champion carries its holdout result. A training champion
can fail that audit; the report does not relabel it as qualified.

The built-in targets seek useful test regimes, not empirical realism. Custom
programs require an explicit evaluator JSON. Use `SearchPlan`, `Metric`, `Axis`
and `Target` from the SDK to author one. `mean` is integer floor mean;
`nonzero_ppm` is the fraction of nonzero records in parts per million.

## Compose coding harnesses

```bash
worldloom synth team retail.json evaluator.json agents.json team-report.json --checkpoint receipts
worldloom synth team retail.json evaluator.json agents.json replay-report.json --replay-ledger team-report.json
```

`agents.json` names designer and critic executables:

```json
{"designers":[{"name":"designer","command":"python my_designer.py","version":"v1"}],"critics":[{"name":"reviewer","command":"python my_reviewer.py","version":"v1"}]}
```

The example filenames are adapter entry points to supply, not bundled models.
Each child receives one JSON request on stdin and returns one JSON object on
stdout. The request includes the response schema. A designer proposes parameter
values and a rationale. A critic receives measured training outcomes and returns
concerns and suggestions. Multiple designers rotate through the same bounded
archive and measured feedback. Holdout seeds are not sent to either role.

Critics cannot approve invalid data. Their advice goes to the next designer;
only the mechanical evaluator admits candidates. Each exchange has a
content-addressed receipt. `--checkpoint` publishes receipts as calls complete,
so a later child failure does not discard earlier work. Rerunning with that
checkpoint reuses matching exchanges. Offline replay refuses a missing or
corrupt receipt instead of starting a process.

Commands run without shell expansion through the existing executable seam, but
**they are not sandboxed**. They have the invoking process's privileges and can
incur provider charges. Configure trusted adapters. Changing an adapter's
behavior requires changing its version. The generated JSON program itself
cannot execute commands. No model calls are made by ordinary generation,
verification, counterfactual comparison or parameter search.

## Connect operational records to enterprise evaluations

```python
from worldloom import MonthEndClose, RetailWorld
from worldloom.enterprise_sdk import EnterpriseEvalHarness
from worldloom.synthesis import (
    IncidentRule, Simulator, operational_profile, retail, with_parameters,
)

world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03"))
program = with_parameters(retail(stores=8, products=12, ticks=30),
                          {"initial_stock": 8, "target_stock": 15})
simulation = Simulator(program, seed=world.seed)
harness = (
    EnterpriseEvalHarness.from_world(world)
    .with_scenario(operational_profile("retail"))
    .with_operational_data(
        simulation,
        IncidentRule(table="inventory", signal="lost", title="Stock availability"),
        include_world_records=False,
    )
    .take(32)
)
corpus, coverage = harness.build()
```

Consecutive exceptional observations form a case. A closing observation records
resolution. Jira, ServiceNow and email share the case ID and exact observation
history. Email threads group messages that actually exist. The banking profile
uses loan-servicing cases rather than an IT incident/change workflow. A generic
workflow requiring an IT change request is not silently made valid for retail.

The adapter enables strict source mode. Missing records or insufficient source
cardinality become refusals, not `generated_for_query_requirements` placeholders.
The older fixture mode remains available for compatibility; call
`require_sources()` to make an existing harness strict. Connector materialization
is bounded and in-memory; the raw record generator is the streaming layer.

Provenance contains the simulation recipe digest and source row IDs. These are
not forged `World.fact_ids`. Keep the synthesis export alongside the enterprise
corpus as its evidence ledger. Attaching the simulation to a World supplies
company context; it does **not** reconcile operational totals to that World's
macro financial close. That requires an explicit reconciliation model.

## Boundaries

This layer does not fit distributions to source data, guarantee privacy, prove
causal identification, or implement cross-entity mutable event scheduling.
It does not claim a 100x speed or quality gain. The evidence is executable
mechanisms, invariant checks, paired interventions, byte replay, held-out
behavioral evaluation and grounded connector cases. Statistical calibration and
held-out customer data are separate work, not properties conferred by a seed.
