# Executable enterprise qualification

Use `EnterpriseEvalHarness.qualify` to measure which planned enterprise tasks
the current World can support. It composes the existing query planner,
materializer, source predicates, validators, row compiler, connector executor
and constrained covering algorithm. It creates no new company facts or episode
mechanisms. For deliberate eval-first generation, start with
[company-driven campaigns](company-eval-reuse.md); qualify the enterprise
workloads against their finalized worlds.

## Run a bounded qualification

```bash
worldloom enterprise-evals qualify ./corpus --pool-size 128 --limit 64 --out ./qualified --json
worldloom enterprise-evals qualify ./corpus --profile scenario.json --dag-shape map_read --pool-size 128 --out ./qualified-map
```

The profile is an existing enterprise `ScenarioProfile`, describing workflows,
connector roles and coverage dimensions. Render the source World before
qualification when those roles require native files. A connector's `file` label
or a claimed PDF format does not establish that a PDF exists.

```python
from worldloom import World
from worldloom.enterprise_sdk import EnterpriseEvalHarness

harness = EnterpriseEvalHarness.from_world(World.load("./corpus"))
qualified = harness.take(64).qualify(pool_size=128)
print(qualified.report.model_dump_json(indent=2))
qualified.export("./qualified")
```

`pool_size` bounds candidates inspected in the planner's exhaustive, interleaved
order. One lookahead determines `pool_exhausted`. `take` supplies the output cap;
`max_selected` overrides that cap. The pool is independent of the ordinary
planning strategy. No coverage is claimed for combinations outside this pool.

## Admission and selection

1. Validate the source World. Bind optional operational case predicates.
2. Preflight each query with strict sources. Preserve a refusal when required
   records are unavailable; never synthesize placeholders for admission.
   Mechanically derivable coverage dimensions must agree with generation
   requirements. A PDF label paired with a record-only contract is refused.
3. Materialize the surviving pool together. Independently validate its shared
   dataset and each query's selected evidence. World fact IDs must exist;
   operational `SYNOBS` observations must pass their own provenance checks.
4. Verify selected input formats. Concrete file requirements need actual bytes
   linked to a World artifact. Structured records and threads use their native
   record form. Unsupported formats remain findings.
5. Compile the existing executable row and run its assertions. A designed tool
   error may qualify when the asserted refusal or recovery behavior succeeds.
6. Apply existing constrained cover to eligible semantic dimensions and a
   one-way cover to observed operational case IDs. Preserve pool order and apply
   the output cap, then recompute both coverage reports.

The covering algorithm retains candidates that introduce new interactions. It
does not promise a minimum set or an optimal capped set. Case provenance fields
are excluded from semantic interactions and measured separately, so opaque case
identities cannot inflate apparent workflow diversity.

`eligible_coverage` and `selected_coverage` share the requested pool denominator.
Their holes distinguish what qualification refused from what selection omitted.
Use *observed achievable coverage* for the interactions witnessed by eligible
candidates. An unsampled or refused combination has not been proven impossible.
Case coverage similarly reports the cases requested or observed in the bounded
pool; it does not certify every case in the company.

## Exercise real operational cases

An existing operational projection supplies causal records and observation
provenance. Enable case binding on the same harness:

```python
from worldloom import RetailWorld
from worldloom.synthesis import IncidentRule, Simulator, retail, with_parameters
from worldloom.synthesis.connectors import operational_profile

program = with_parameters(retail(stores=2, products=3, ticks=12),
                          {"initial_stock": 8, "target_stock": 15})
scenario = operational_profile("retail")
scenario = scenario.model_copy(update={"coverage": scenario.coverage.model_copy(
    update={"failures": ("none",)})})
harness = (EnterpriseEvalHarness.from_world(RetailWorld(seed=8128).build())
           .with_scenario(scenario)
           .with_operational_data(Simulator(program, seed=8128),
                                  IncidentRule(table="inventory", signal="lost",
                                               title="Stock availability"),
                                  include_world_records=False)
           .with_operational_case_binding(max_cases=128))
qualified = harness.qualify(pool_size=24, max_selected=24)
qualified.export("./qualified-operational")
```

Binding chooses deterministic case cohorts present in every source role. Mapped
reads bind multiple cases when source minima require them. Query prose names
actual source titles and external references; typed predicates carry machine
case identities. Both materialization and independent validation enforce the
cohort. Missing counterparts, relabelled observations and substituted evidence
are refused. `with_operational_data` currently installs one projection set;
repeated calls do not merge multiple independent simulations.

## Inspect the export

The directory contains the ordinary enterprise corpus and these additions:

| File | Meaning |
| --- | --- |
| `pool-queries.jsonl` | Inspected candidates, including refused and unselected ones |
| `qualification.json` | Eligibility, selection, bounded coverage holes and named refusals |
| `qualified-rows.jsonl` | Exact executable rows used for the selected candidates |
| `proofs.jsonl` | Bound query, fixture, shared data and row identities; native source-byte receipts; execution grade, spans and post-state |
| `manifest.json` | Export schema and content digests |

Native receipts include artifact ID, format, relative path, byte size and SHA256.
Construction-time digests reject later changes to the pool, coverage report,
selected evidence, rows or proofs before export can present them as tested.

Selection retains the original shared batch records and fixtures. Export never
rematerializes a smaller selection: destinations and enriched fields can depend
on the full batch. Source World native files remain in the original World;
the enterprise export contains their admission receipts, not copies of them.
Keep the source World when those files are needed for inspection or execution.

An empty selection still writes its report. The CLI then exits with code 3 and
`no_qualified_evals`. Set `WORLDLOOM_OUTPUT=json` for structured CLI refusals;
`--json` controls successful report output. `--overwrite` only replaces an
existing qualification directory.

## What a proof establishes

Qualification proves the supported connector assertions against the exported
fixture records. It does not establish an agent's ability, semantic correctness
of generated analysis, requested pages/charts, prose entailment, distributional
representativeness or reconciliation between operational microdata and company
aggregates. Legacy query plans do not execute arbitrary model transforms.
Native-file admission checks existence and provenance; it does not inspect
whether the file answers the business question or certify container validity
with a format parser. Receipts identify the nonempty bytes under the linked
artifact's matching format.

See the [measured reuse audit](enterprise-outcome-reuse.md) for remaining reader,
fidelity and difficulty-calibration work. These checks belong before archive
admission or evolutionary optimization and must run again after changes to
worlds, source bindings or executable contracts.
