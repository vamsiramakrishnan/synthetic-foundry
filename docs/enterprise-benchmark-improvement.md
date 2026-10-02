# Enterprise corpora and measurable harness improvement

A corpus needs business evidence before it needs more bytes. An evaluation
needs an independent oracle before it needs more cases. An improvement loop
needs fresh qualification evidence before it can call a candidate better.

Worldloom keeps those responsibilities separate. One company owns the source
facts, history, and accepted prose. A versioned process program owns operational
rows. File materialisation owns the delivered bytes. Task contracts own the
requested work. Reference execution checks solvability. A pinned grader judges
the target; the improvement loop changes its policy and skills.

For the complete SDK and command workflow, including a target process, exact
resume and coverage preflight, see [Native benchmarks for coding harnesses](native-benchmark-workflow.md).

## Materialise the declared scale

Install the renderer dependencies before asking for native files:

```bash
pip install -e '.[xlsx,docx,pptx]'
worldloom corpus-scale assess ./company --program process.json --profile enterprise
worldloom corpus-scale build ./company --program process.json --profile enterprise --xlsx --out ./large-corpus
worldloom corpus-scale verify ./company ./large-corpus
```

`assess` reports construction shortfalls and exits unsuccessfully when a target
is unmet. `build` refuses insufficient source evidence. It writes to a staging
directory and commits a complete destination atomically. `--resume` verifies a
completed destination against the same plan; it does not silently replace one.

| Profile | Minimum relational rows | Minimum DOCX content units | Minimum PPTX content units |
|---|---:|---:|---:|
| `development` | 10,000 | 30 | 20 |
| `enterprise` | 1,000,000 | 200 | 100 |
| `stress` | 10,000,000 | 500 | 200 |

These are obligations, not delivered-size claims. A program must declare enough
real rows; a source world must contain enough distinct accepted sections and
facts. Larger programs also need sufficient explicit synthesis limits through
`--limits`. A profile JSON can define other populations and native file floors.

CSV shards rotate at both `--shard-rows` and `--shard-bytes`. `--xlsx` also writes
typed workbooks from the relational shards. The manifest measures delivered
rows, entities, foreign-key links, integer sums and ranges, bounded cardinality
statistics, file sizes, native content units, and distinct canonical facts.
Verification reconstructs projections from the process recipe; rewriting a
CSV and its checksum still fails. It also checks the company, source facts,
accepted prose, locale, and presentation that own the native bytes.

The manifest's `target_files` curates the public data surfaces in `tables/` and `native/`. `source/`, `plan.json`,
and `manifest.json` contain evaluator provenance and belong outside a target
harness's accessible workspace.

## Reconcile transactions with company evidence

An independent operational simulation does not automatically reconcile with a
company's financial close. Declare that relationship when it is part of the
test. A `FactReconciliation` binds a table's integer sum to one numeric canonical
fact at a declared decimal precision. Generation and verification both check it.

The ledger allocation builder provides a bounded construction for this case:

```python
from worldloom.corpus_scale import (
    ledger_allocation_source, plan_corpus_scale, export_corpus_scale,
)

source = ledger_allocation_source(
    world, fact_id=revenue_fact_id, rows=100_000, seed=world.seed,
)
plan = plan_corpus_scale(
    world, source.simulator, profile=profile,
    native_plans=native_plans,
    reconciliations=(source.reconciliation,),
    spreadsheets=True,
)
manifest = export_corpus_scale(world, plan, destination)
```

The equivalent CLI uses `--fact FACT_ID --rows 100000` instead of `--program`.
For an authored process program, repeat `--reconciliation binding.json` for
each declared relationship. The allocation builder's default synthetic skew
puts 80% of the quantity in 10% of transaction rows. It records that assumption,
uses exact integer arithmetic, and closes the total without retaining a vector
of row weights. It does not claim to have fitted a customer's distribution.

## Build discovery queries over business files

New scale plans use the business native surface. It renders accepted prose,
source tables, typed measures and spreadsheet formula dependencies. DOCX tables,
slide tables and speaker notes, and workbook tabs carry business labels. Canonical
fact IDs and source locators stay in the private provenance manifest. Explicit
older native plans retain their legacy surface and deterministic wire format.
Supply checked `--native-plan` files when controlling a source table graph.
An inconsistent formula, missing dependency or table exposing private canonical
identities must be repaired or excluded from that requested graph before it can
become an evaluation surface.

Write a `NativeWorkloadPlan` JSON, for example:

```json
{"use_case_id": "close-review", "objective": "Reconcile the close evidence and prepare the operating review.", "formats": ["docx", "pptx", "xlsx"], "operations": ["read", "analyze", "update", "create"], "max_tasks": 64, "discovery_scope": "mixed"}
```

```bash
worldloom native-evals build ./company ./large-corpus --plan workload.json --out ./native-workload
worldloom native-evals qualify ./native-workload --out qualification-grades.json
worldloom native-evals grade ./native-workload --replies replies.json --out target-grades.json
```

The planner inspects real bytes and binds their evidence back to the company's
authored sections and tables. Prompts describe discoverable business evidence;
they do not supply source paragraph, slide or cell addresses. Compatible measures
can produce cross-file comparisons and variance calculations. Updates must
preserve every unrelated extracted semantic unit. Creates require grounded
output content and, where supported, typed cells and formulas.

Every emitted task passes independent reference construction and byte grading.
Ambiguous selectors, incompatible measures, replicated evidence, unsupported
formula analysis and unavailable operations produce named coverage findings.
`source_fact_counts` and `capability_coverage` expose depth rather than rewarding
task count alone. Small task budgets sample the archive and multiple operations.

Give the target only `public-tasks.json` and `inputs/`. Keep `oracle.json` in the
evaluator's workspace. Replies have the shape
`{"replies": [{"task_id": "...", "submission": {"answers": [], "files": []}}]}`.
Answers cite their actual artifact and locator; output files carry their native
bytes as base64. The grader requires exact task coverage and checks the bytes,
citations, source version and semantic preservation. Visual layout preservation
is a separate measurement.

The SDK exposes `plan_native_workload(world, rendered, plan)` for other exchange
adapters. Studio also accepts `NativeSuiteRequest(query_style="discovery")`;
its default located suite remains compatible.

Native outcomes also connect to the existing policy improvement runner:

```python
from pathlib import Path
from worldloom.evalrun import QualificationPolicy
from worldloom.evalrun.improve import improve
from worldloom.native_eval_bridge import NativeGrader, native_task_cases, native_runner

cases = native_task_cases(workload.tasks, rendered, world=world, namespace="world-8128")
run = native_runner(
    rendered, submit, namespace="world-8128", world=world,
    submit_identity={"harness": "my-native-adapter", "revision": "pinned-revision"},
)
report = improve(
    champion, cases, run=run, agent_for=agent_for,
    exchange=proposer_exchange, out=Path("./native-improvement"),
    rater=NativeGrader(), qualification=QualificationPolicy(), repeats=2,
)
```

The caller's `submit(agent, public_task, input_bytes)` invokes its installed
harness and returns a `NativeSubmission`. It receives public task fields and
the requested input bytes. Use the opaque `execution_id` as its exchange key;
each experimental repeat has a distinct key. The SDK independently grades each
reply, reports native failures to the existing autopsy/proposer, and pins the
native grader, parser dependencies, served files and submission adapter during
execution and resume. It observes **outcomes only**; replies provide no evidence
of a plan or tool trajectory.

Pass `world=world` (or an artifact-ID-to-World mapping for multiple snapshots)
to `native_runner`. It recomputes derivation and supersession ancestry from
canonical sources before qualification and cache reuse. Renamed sources and
distinct derived fact IDs sharing an ancestor remain correlated.

Qualification still requires sufficient independent source graphs. The default
three probes with five units each require at least fifteen held-out families,
plus training evidence. All tasks over one shared native file remain connected;
adding operations or formats cannot supply that support. The construction pilot
below exercises task coverage and is not a promotion cohort.

## Qualify a policy on independent evidence

The existing improvement loop already supports policy and skill revisions,
ablation, repeated paired comparisons, candidate search, and campaigns. An
ordinary repeated holdout remains useful for selection, but adapting promotion
decisions to it consumes information about it.

For stricter qualification, predeclare a `QualificationPolicy` JSON:

```json
{"trials": 3, "min_units": 5, "min_repeats": 2, "confidence": 0.95}
```

```bash
worldloom evalrun audit-split ./training --holdout-corpus ./held-out --source-origin world-8128 --holdout-origin world-4242
worldloom evalrun improve ./training --agent-pack agent:baseline --exec 'python target.py' --proposer-exec 'python proposer.py' --holdout-corpus ./held-out --source-origin world-8128 --holdout-origin world-4242 --qualification-policy qualification.json --repeats 2 --out ./improvement
```

The audit groups tasks through transitive evidence connectivity. Different case
IDs, paraphrases, file formats, or queries do not make shared evidence
independent. The source's immutable snapshot pin and its stable lineage origin
serve different purposes: one detects edits, the other groups related examples.
Keep `--source-origin` and `--holdout-origin` stable across snapshots and
counterfactual variants. Use distinct origins only for independently generated
worlds; origin declarations are caller-owned provenance, not empirical proof.
Without explicit origins, reused local IDs conservatively share one origin.

Each qualifying candidate consumes a fresh tranche of whole evidence components.
Reservation occurs before target execution and survives interruption. Rejected
candidates consume their tranche too. Exhaustion stops qualification rather than
reusing a cohort. Resume requires the same policy, pool, grader, champion, and
candidate identities.

Comparisons average correlated cases within their evidence unit and bootstrap
paired unit deltas. Every graded axis needs its own adequate independent support
and matching observations. The predeclared confidence budget is apportioned over
the allowed probes. These are empirical statistical gates, not exact guarantees
for arbitrary distributions. No policy can manufacture independent support by
adding copies of an existing case.

The default improvement workflow remains compatible. Qualification is explicit
because a small dataset often has too few independent components to support it.
New source evidence is then the required next step.

SDK campaigns accept the same qualification policy. The campaign seals its
original budget and allocates its nominal error probability to stage `n` as
`alpha / (n * (n + 1))`, then divides that stage's budget among its probes.
Extending a campaign cannot reset the budget. Earlier held-out evidence cannot
return as a renamed task in another stage; diagnostic ledgers inspect consumed
tranches only. A separate final blind audit cohort remains caller-owned.

## Keep reference proof independent of its expected answer

The eval-first emulator proof records only the records it actually retrieved and
their provenance. It cannot add oracle facts to a successful search or read.
Source assertions bind to their own connector and entity; global corpus
requirements remain separate static assertions. A missing selector match fails
instead of falling back to an unrelated record. Verification requires observed
evidence and readback of the relevant writes.

Connectorless semantic operations need a caller-supplied `StepExecutor`. The
built-in connector emulator cannot certify an unsupported calculation by copying
expected facts into its output. This changes which older cases qualify: a case
that depended on fabricated execution evidence now fails honestly.

## What a measured result establishes

The checked-in construction measurements use seed 8128 and eighteen monthly
episodes. The native source graph includes 200 distinct prose sections and
three checked operating-table sections from the same company.

| Measurement | Delivered result |
|---|---:|
| Reconciled ledger | 1,000,000 transactions and one ledger row |
| Ledger foreign-key links | 1,000,000 |
| Retail process | 100,070 rows and 200,000 foreign-key links |
| DOCX | 203-page construction floor and 203 tables |
| PPTX | 237 slides, 134 tables and 100 speaker-note sections |
| Native XLSX | 8 tabs and 172 formula cells |
| Distinct native canonical facts | 1,004 |

See [retail measurements](measurements/corpus-scale-retail.json) and
[reconciled ledger measurements](measurements/corpus-scale-million-ledger.json)
for workloads, source recipes, file hashes and measured construction/reconstruction
times. The runs contain **zero live target trials**.
The [native discovery measurement](measurements/native-discovery.json) records
32 independently reference-graded tasks, eight per operation, their capability
coverage and remaining ambiguity findings.

To reproduce the source:

```python
from pathlib import Path
from worldloom.narrative import DeterministicProvider
from worldloom.studio import Studio
from worldloom.studio.native_pilot import pilot_base

world, _ = Studio(Path("./pilot-state")).snapshot(pilot_base(seed=8128, periods=18))
world.narrate(DeterministicProvider()).export("./pilot-company")
```

Then run:

```bash
python tools/measure_corpus_scale.py --corpus ./pilot-company --out ./pilot-retail --report retail-measurement.json --xlsx --table-section ART-0002:3 --table-section ART-0002:4 --table-section ART-0002:5
python tools/measure_corpus_scale.py --corpus ./pilot-company --out ./pilot-ledger --report ledger-measurement.json --ledger-fact FACT-0004 --ledger-rows 1000000 --table-section ART-0002:3 --table-section ART-0002:4 --table-section ART-0002:5
```

`tools/measure_corpus_scale.py` materialises a declared process and native files,
then reconstructs them independently. It reports its workload and runtime beside
the delivered measurements. The source construction and target-agent result are
different measurements. A reference pass proves solvability; it does not measure
model quality or a harness's improvement.

DOCX explicit page boundaries establish a construction floor; physical pagination
still needs a layout engine. Consistency checks do not establish empirical
enterprise realism. Target filesystem isolation must be enforced by the host
before calling private evaluator material inaccessible. The harness remains a
caller-provided execution seam; Worldloom does not call an LLM service itself.
