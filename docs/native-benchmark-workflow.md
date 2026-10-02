# Native benchmarks for coding harnesses

Use `worldloom.benchmarks` to build, inspect, execute and improve a harness on
DOCX, PPTX and XLSX tasks. The CLI calls that same SDK. Task construction,
byte grading and promotion reuse the existing native and evaluation engines.

## Build and inspect a benchmark

Start with one company corpus and its verified scale export. Describe the
business objective in a `NativeWorkloadPlan`, such as
[`native-discovery-workload.json`](examples/native-discovery-workload.json).

```bash
worldloom native-evals build ./company ./large-corpus --plan workload.json --layout split --out ./benchmark
worldloom native-evals inspect ./benchmark --source-origin northstar
worldloom native-evals qualify ./benchmark --out ./qualification.json
worldloom native-evals protocol --out ./target-protocol.json
```

The split package contains:

| Path | Purpose | Target access |
|---|---|---|
| `public/public-tasks.json` | Business requests and response contracts | Yes |
| `public/inputs/` | Native source files bound by checksum | Yes, scoped to each task during execution |
| `private/oracle.json` | Expected answers, citations and preservation constraints | Evaluator only |
| `private/source/` | Canonical company used to verify evidence | Evaluator only |
| `private/native-manifests.json` | Native locators and source lineage | Evaluator only |
| `benchmark.json` | Package identity and exact file inventory | Evaluator |

`build --resume` accepts an identical complete package. A changed plan, source,
file, public request or oracle is a refusal. A package load verifies the stored
bytes and source lineage; recalculating a checksum does not establish a new
oracle's correctness. The planner is replayed against the canonical source.

Existing `native-evals build` callers retain the root-level exchange layout
unless they request `--layout split`. Legacy exchanges still qualify, grade and
run. They lack the source provenance needed to certify independent evidence for
promotion; rebuild from the source corpus to obtain that provenance.

The inspection report separates three questions:

- `execution_ready`: can the delivered tasks be independently qualified?
- `coverage_complete`: did the delivered tasks cover the requested operations
  and formats? A task limit is a ceiling, not an invented minimum.
- `promotion_ready`: can the declared experiment meet its independent evidence,
  split and repeat requirements? This is a preflight result, not a promotion.

With a separate held-out package, `heldout_coverage_complete` checks its own
declared operations and formats. Missing requested work in either package
blocks promotion readiness.

Each operation, format and capability has a task count and an independent-unit
count. Shared files, canonical facts, their derivation/supersession ancestors,
and source sections join tasks into one component. Formatting the same evidence as a deck and a document does not add
support. Findings identify the missing condition and the next action.

## Construct independent source families

Partition source sections before rendering when the aggregate files contain
too much shared evidence to fund a training/held-out split:

```bash
worldloom native-evals partition ./company --plan partition-workload.json --train-families 3 --holdout-families 15 --out ./partitioned
worldloom native-evals inspect ./partitioned/training --holdout ./partitioned/heldout --source-origin northstar --repeats 2
```

Use [`native-partition-workload.json`](examples/native-partition-workload.json)
as an example. Artifact-scoped discovery preserves the available source
families; cross-artifact tasks may join them again. The family quotas are
requirements, not promises to invent enough evidence. The default promotion
policy reserves three held-out tranches of five independent units each.

The planner keeps complete table dependencies, shared canonical facts and
their ancestors together. Copies in multiple formats stay in the same family.
It renders only whole families, validates the resulting byte-bound lineage,
and independently audits the final workloads. If the source lacks enough
families, the task budget omits a family, or a task reconnects the splits, the
build refuses without publishing a partial package. Exclusions and whole-family
omissions remain in the partition report.

The atomic builder can combine complete source components into richer files
for local synthesis and preservation tasks. It groups related prose where
possible, then balances section counts. This reduces the available independence;
it never splits a connected component. Reports retain every original component's
section/fact counts and its allocation to the served families. Separate monthly
cost or deadline records are not equivalent to independent financial episodes.

Bounded candidate sampling and task selection rotate across source evidence and
formats within operation/capability lanes. A large workbook cannot consume the
candidate budget merely by having more cells. This improves coverage allocation;
only the final canonical evidence audit establishes independent support.

Partition exports include reporting-period context in headings and table titles
when their served canonical evidence belongs to one period. This makes repeated
monthly records distinguishable in the public files. Mixed-period content keeps
its original heading; the query planner still refuses ambiguous evidence.
Other business native plans can opt in with `contextual_headings=True`; existing
plans retain their original labels by default.

The destination contains source-bound `training/` and `heldout/` benchmark
packages plus `partition.json`. `partition --resume` verifies the exact source,
workload, allocation and packages. SDK callers use `plan_native_partitions`
to inspect capacity and `partition_benchmarks` to perform the atomic build.

## Run a target

Implement the JSON stdin/stdout contract printed by `native-evals protocol`.
The target receives one public task, an opaque execution ID and `input_root`.
Resolve each `task.inputs[].path` beneath that directory. Return the task ID,
execution ID and a `NativeSubmission`; output files carry actual base64 bytes.
No expected answer or private provenance appears in the request.

```bash
worldloom native-evals run ./benchmark --command 'python ./adapter.py' --out ./runs/baseline --repeats 2
worldloom native-evals run ./benchmark --command 'python ./adapter.py' --out ./runs/baseline --repeats 2 --resume
```

Every invocation gets only its task's declared inputs. The runner independently
inspects returned answers, citations, formulas, output types and preservation
constraints. A malformed reply, failed process or timeout becomes a failed task;
other tasks can still run. Run reports and per-task receipts remain machine
readable. A failing run exits unsuccessfully while retaining its report.

Resume checks the package, task contracts, input bytes, command identity and
settings. It regrades saved submissions before reusing them. Completed tasks
are not invoked again. An interrupted task without a committed receipt can be
reissued; the execution ID lets a remote adapter deduplicate its own requests.

The adapter pins the executable and file arguments. Use repeated
`--identity-file` flags for imported modules, lockfiles or configuration. SDK
callers can also declare `identity_extra` for a remote model/deployment revision.
Changing any pinned input requires a new run directory. Runtime settings or
remote services the caller does not pin cannot be verified by Worldloom.

Local commands are trusted subprocesses. Directory separation and task staging
are not an operating-system sandbox: a local command retains the caller's
filesystem permissions and inherited environment. Use a container or remote
adapter to enforce a separate filesystem boundary for an untrusted target.

## Use the SDK

```python
from pathlib import Path
from worldloom import World
from worldloom.benchmarks import NativeBenchmark, CommandHarness, run_benchmark
from worldloom.native_query_planning import NativeWorkloadPlan

world = World.load("./company")
plan = NativeWorkloadPlan.model_validate_json(Path("workload.json").read_text())
benchmark = NativeBenchmark.build(world, Path("./large-corpus"), plan)
benchmark = benchmark.export(Path("./benchmark"), resume=True)
assessment = benchmark.assess(namespace="northstar")
report = run_benchmark(
    benchmark,
    CommandHarness(("python", "./adapter.py")),
    directory=Path("./runs/baseline"),
    repeats=2,
    resume=True,
)
```

`NativeBenchmark.from_rendered(world, rendered, plan)` supports callers that
already have native source bytes. `load`, `qualify`, `grade` and `assess` use the
same contract as their CLI counterparts. `CallableHarness` adapts an in-process
target with an explicit implementation identity. `worldloom seams --json`
describes the canonical `worldloom.benchmarks` import and its operations.

Planning and native case compilation reuse parsed source snapshots within each
invocation. The cache is bounded by 64 entries, 200,000 extracted units and
32 MiB of UTF-8 text plus locators, and keys entries by format and actual byte
SHA-256. It retains no parser objects or grades. Source checks and qualification
still execute; submitted outputs are parsed afresh. Oversized sources remain
usable without being retained.

## Improve a policy on fresh evidence

Create separate training and held-out packages from independently grounded
source families. Keep the company origin stable across snapshots. A new seed,
format or filename alone does not establish independence. The held-out pool
must contain at least `trials * min_units` independent components, plus the
separate training evidence; each comparison also needs the policy's repeat
support.

```bash
worldloom native-evals inspect ./training --holdout ./heldout --source-origin northstar --qualification-policy qualification-policy.json --repeats 2
worldloom native-evals improve ./training ./heldout --source-origin northstar --agent-pack agent:baseline --command 'python ./adapter.py' --proposer-command 'python ./proposer.py' --qualification-policy qualification-policy.json --repeats 2 --out ./study
```

The target uses the native task protocol. The proposer uses the existing
pack-author exchange and receives training failure evidence. The target sees
the revised `AgentPolicy` body, so changing a policy changes the target's
instructions. The proposer does not receive held-out cases.

`improve_benchmark` composes `native_task_cases`, `native_runner`, `NativeGrader`
and the existing sealed improvement loop. It validates lineage, company origin,
artifact identity, declared coverage, split isolation and experiment support before making target
or proposer calls. Every reaching candidate consumes a fresh qualification
tranche. The pinned grader, paired comparisons, ablation and promotion receipts
remain owned by the existing loop. Repeating the same command resumes the
sealed study under its existing identity rules.

## What this fixes and what still needs evidence

| Bottleneck | Change | Remaining limit |
|---|---|---|
| Harnesses assemble several internal modules | One SDK and CLI workflow for packaging, running and improvement | Connector and native tasks still have different task contracts |
| Task counts obscure shared evidence | Requested coverage and independent support reported separately | A larger aggregate file still has only its actual evidence independence |
| Large files collapse independent experiments | Partition authored sections into complete source families before rendering | The source must actually contain enough disjoint evidence |
| Targets need bespoke execution glue | Versioned command protocol, scoped inputs, receipts and resume | A model or harness needs an adapter to this protocol |
| Qualification repeatedly reparses shared source files | Bounded source extraction reuse within an invocation | Output inspection and evidence checks still cost work per task |
| Source formulas disagree with rounded business facts | Explicit rounding belongs to the IR and is evaluated consistently | Supported formula vocabulary remains bounded |
| Source privacy checks differ by entry point | Shared source checks on planning and improvement intake | Trusted local processes need external sandboxing when untrusted |
| Large synthetic files look like enterprise realism | Scale, coverage, qualification and observed trials remain distinct | Customer-calibrated distributions and editorial realism need external measurements |

The source inventory in the measured retail pilot has 44 components: 42 small
monthly cost/deadline components and two large connected components. This is
evidence of available source support, not 44 diverse enterprise scenarios.

The [completed construction measurement](measurements/native-benchmark-partitions.json)
groups these into three training and fifteen held-out families, with zero
canonical evidence overlap. It publishes 54 native files: 18 each of DOCX, PPTX
and XLSX. The constructor completed in 451.424 seconds on the measured runtime,
including its source replay and native-byte reference checks.

| Split | Qualified tasks | Read families | Analyze families | Update families | Create families |
|---|---:|---:|---:|---:|---:|
| Training | 68 | 3 | 1 | 2 | 3 |
| Held-out | 256 | 15 | 1 | 12 | 12 |

The held-out workload has 64 tasks per operation, but its analysis tasks all
share one source family. Training lacks PPTX/XLSX analysis tasks; held-out lacks
PPTX analysis tasks. Aggregate support does not establish independent support
for every operation or coverage of every operation/format combination. No live
target trial, accepted promotion, standalone SDK assessment or additional large
resume run was performed in this measurement.

The [original 32-task baseline](measurements/native-benchmark-workflow.json)
had one evidence component. Intermediate measurements retain the
[pre-grouping result](measurements/native-benchmark-partitions-before-grouping.json),
[ambiguous-context refusal](measurements/native-benchmark-partitions-before-context.json),
[task-budget refusal](measurements/native-benchmark-partitions-budget-refusal.json)
and an [unexplained process termination](measurements/native-benchmark-partitions-crashed-attempt.json).
The [source-parsing comparison](measurements/native-source-inspection.json)
records a separate 24-task fixture: source inspections fell from 70 to 6 with
identical workload JSON. Its local timings are not an enterprise speedup claim.

The shipped construction pilot establishes physical scale and solvability.
It does not establish target improvement. Report live target trials separately
from reference trials, and report accepted promotions only from completed
qualification receipts.
