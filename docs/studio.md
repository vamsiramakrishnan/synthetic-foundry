# Worldloom Studio

Studio is a local console for one company's synthetic dataset. Describe the
company, interview it through your coding harness, map use cases to owners and
processes, and generate evidence and qualified evaluations from the same world.

```bash
worldloom studio serve --workspace ./worldloom-workspace
```

Open `http://127.0.0.1:8765`. Create a company or choose **Load connected retail
pilot**. This example connects inventory exceptions, supplier replenishment and
invoice reconciliation across Jira, ServiceNow and email. **Load smaller retail
example** retains the earlier 24-query inventory example. Both are authored
contracts with explicit operational volumes; their process catalogue is broader
than the business mechanisms they execute.

The console ships in the Python package. It requires no JavaScript build,
hosted service or separate frontend installation. The local workspace holds
company revisions, interview exchanges, jobs, snapshots and dataset checkpoints.
Back up the whole workspace when retaining generated datasets.

## One company, several contracts

| Object | Meaning | Generation authority |
| --- | --- | --- |
| Company profile | Identity, engine, geography, scale and business characteristics | Existing `company.resolve` and SDK |
| Revenue divisions | Division keys, revenue shares, categories and site formats | Existing `PackUnit` and pack validation; changes affect generated entities |
| Operating structure | Business units, countries, operating model and system landscape | Process catalogue and opt-in support-unit materialization |
| LOB | Roles, responsibilities and process seats | Existing LOB lint and `Blueprint.lob`; roles enter the organisation |
| Use case | Business objective, owner, processes, executable workflow and evidence source | `ScenarioProfile` plus an explicit `EvalSpec` construction contract for foundry runs |
| Company dataset | Quotas and diversity within one immutable company snapshot | `CompanyDatasetPlan` and independent qualification |
| Benchmark collection | Separate companies compared across an evaluation population | Historical `DatasetPlan` collection API |

Operating units and revenue divisions are different. Shared finance can own a
process without being a revenue-generating division. The UI shows both. Process
catalogue rows are definitions, not observed transactions. Foundry materializes
declared support groups as company entities without allocating trading revenue.
Its default accountability policy binds an existing CEO role and records that
choice; it does not invent a dedicated department head. Scoped construction
requires actual records matching the declared unit, LOB and activity. A generic
search witness cannot establish process ownership. Ordinary compile-only runs
retain authored ownership as lineage. Operational simulations do not claim
reconciliation with the company's financial aggregates.

## The working loop

1. **Interview.** Describe the company and the work to evaluate. Include systems,
   record volumes, ownership, expected outcomes and changes over time. Export a
   request to a coding harness, or send it through a configured adapter.
2. **Review.** A harness response may contain questions and a complete proposed
   project. Inspect its changes before applying it. Applying a response targets
   the revision that issued the request; a stale proposal cannot overwrite
   later changes. Imported JSON goes through the same validation as the UI.
3. **Model.** Edit the profile, revenue divisions, operating structure and LOBs.
   Add chronological episode periods. The registered domain owns cadence and
   business behavior; entering an industry name cannot create a missing engine.
4. **Specify use cases.** Choose a supported workflow or leave it open for the
   interview. Define source systems, evidence generation, expected mutations,
   failure cases, task shapes and row quotas in its typed contract. Unsupported
   or absent evidence remains a generation refusal.
5. **Construct and measure.** Open **Foundry run**, configure the target cohort,
   noise candidates, pass-rate band and finite trial budgets, then start the
   run. Runs execute in a separate local process, so the UI remains available.
   Inspect unmet obligations, quality findings and observed difficulty. Build
   and compile remain available for intermediate work.
6. **Explore.** Each selected evaluation carries the project, company revision,
   use case, owning unit, LOB and selected process IDs, plus task/case identities
   and its exact qualification directory. Open **Inspect source evidence** to
   read the original connector records and reference qualification proof. The
   service verifies the committed dataset before exposing that evidence.
   Earlier runs retain earlier intent.

## Coding harnesses

Use an installed, signed-in coding CLI:

```bash
worldloom studio serve --workspace ./worldloom-workspace --harness codex
worldloom studio serve --workspace ./worldloom-workspace --harness claude
```

The first adapter uses documented [non-interactive execution and final-output
files](https://developers.openai.com/codex/noninteractive/). The second uses
[print mode and JSON result output](https://code.claude.com/docs/en/headless).
Both preserve the harness's existing authentication and model configuration.
Their execution modes are a read-only sandbox and plan permission mode,
respectively. Neither enables permission bypass. Local configuration and installed
skills remain the harness's responsibility.

A custom SDK, ACP or other harness adapter can use the existing execution seam:

```bash
worldloom studio serve --workspace ./worldloom-workspace --harness-command 'python /path/to/adapter.py'
```

The adapter reads one JSON request from stdin and writes one JSON object to
stdout. The request contains a revision-bound ID, company contract, bounded
recent conversation, instructions and response schema. It does not grant
authority to modify the company. The response is validated and stored; a
separate reviewed action applies the proposal. Commands are configured at
server startup and cannot be supplied by a browser request or model response.

Without a local adapter, use the same handshake through files:

```bash
worldloom studio init examples/studio/retail.json --workspace ./worldloom-workspace
worldloom studio show PROJECT_ID --workspace ./worldloom-workspace
worldloom studio interview request PROJECT_ID --message 'Which teams and systems own replenishment?' --out request.json --workspace ./worldloom-workspace
worldloom studio interview accept PROJECT_ID --from response.json --workspace ./worldloom-workspace
worldloom studio interview accept PROJECT_ID --from response.json --apply --workspace ./worldloom-workspace
worldloom studio run PROJECT_ID --operation compile --batch-limit 2 --workspace ./worldloom-workspace
```

`PROJECT_ID` is printed by `init`. Accepting a response is idempotent; replacing
an already recorded response with different content refuses. Imported proposals
retain unanswered questions and company limitations rather than silently
changing validators. Request/response files work with the coding harness you
already use in an editor or terminal.

Narration reuses `execseam.narrate_loop`: bounded facts, claim checks, retry
budget and generation ledger. Add document-producing episodes before running
**Narrate evidence**. Select **Use this narration** on a completed run to make
that exact authored snapshot the source of a later evalset. Narration from a
different company or generation snapshot refuses. Receipt-backed narration
replays without another authoring call. Reference qualification does not establish
prose entailment, native document layout quality or calibrated agent difficulty;
the foundry run composes reader recovery and observed target trials below.

## Construct, measure and freeze

`foundry` is a durable run over one project revision. It reuses the existing
construction tactics, narration acceptance, connector qualification, Messiness
transforms, reader checker, serving runtime and difficulty estimator. The
enterprise workflow and eval-first design grammars remain explicit: an objective
string is not sufficient authority to invent facts or desired state.

```bash
worldloom studio run PROJECT_ID --operation foundry --harness-command 'python /path/to/adapter.py' --workspace ./worldloom-workspace
```

Each use case needs `construction`, an `EvalSpec`, alongside its executable
`scenario`. Hard connector requirements name a connector, entity and exact
source selectors. Scoped use cases also bind `business_unit`, `activity_id` and,
where declared, `lob`. Every workflow source needs a construction contract.
The compiler namespaces requirement IDs and checks contradictions across use
cases before generating a world. Static conflict detection covers incompatible
selectors and unambiguous same-object state conflicts without temporal
qualifiers; it is not a general temporal constraint solver. Unsupported obligations
and missing domain evidence produce findings, not fabricated source records.

| Stage | Persisted result and admission rule |
| --- | --- |
| Requirements | Explicit designs, compiled demands and conflicts |
| Construction | One company, materialized owners and supported domain/process evidence; every design revalidated against the completed world |
| Narration | Accepted prose and rendered Markdown, with claim checks and recorded harness exchanges |
| Qualification | Complete reference-qualified baseline, fixed query identities, evidence components and case splits |
| Quality | Each noise version independently revalidated, qualified and checked for reader recovery; changed case evidence or unmet coverage rejects that version |
| Trials and selection | Target-agent connector calls, native observations and grades; training selects one version before target holdout trials |
| Freeze | Selected dataset copied and verified only after every use case meets training and holdout support and interval requirements |

Noise candidates start independently from the same authored company. All
batches of the selected dataset export the same world. Candidate versions are
not additional companies or independent statistical samples. Within each use
case, sampling admits one query per transitively connected evidence component.
Components stay on one side of the split; correlated cross-process cases may
contribute to their separate use-case estimates. Rewording a task does not add
support to the same estimate.

`calibration` declares named `variants` with noise budgets, a target `cohort`,
`target_low`, `target_high`, `min_support`, training and holdout attempt budgets,
`reader_share` and a per-trial turn limit. Training compares measured outcomes;
noise is not assumed to increase difficulty monotonically. Each use case must
have enough observations and its Wilson interval must fit entirely inside the
declared band. Among eligible versions, selection minimizes total distance to
the band midpoint, breaking ties by name. The selection receipt is committed
before target-agent holdout outcomes. Holdout failure prevents freezing and
does not trigger selection of another version.

This holdout isolates **target-agent outcome selection**. Reference
qualification and reader quality checks inspect the candidate data, including
held-out evidence, before selection. They are not separately held-out quality
estimates. Reader requests contain text and requested aspects; expected facts
remain in the checker. The same configured harness may serve author and reader
roles through separate exchanges, so separate requests do not establish
independent model errors. Foundry does not currently add a native-layout or
population-fidelity gate.

Target requests expose the question, participating connector tool contracts and
the observations returned so far. The target proposes one native tool call or
a final response. Fixtures, reference traces and grading assertions remain in
the evaluator. The existing connector runtime executes proposals in isolated
trial state, and its grader checks observed connector contracts and effects;
additional unmatched writes fail. Passing this grade does not prove the semantic
correctness of an invoice explanation or other free-form answer.

Native document, slide and spreadsheet outcomes need a further contract.
An input-byte receipt proves the file exists, not that ingestion recovered its
evidence. A successful file write proves neither correct analysis nor a valid
output. Target trials therefore refuse native-file tasks with
`native_ingestion_and_analysis_unmeasured` or
`native_output_content_and_preservation_unmeasured`; those tasks cannot train
the calibration model or freeze as measured outcomes.

The required artifact checks are locator-backed evidence recovery for inputs,
fact-grounded derived answers, parsed native outputs, and preservation of
unaffected sections, slides, cells and formulas during updates. Output rendering
and reference qualification remain useful construction tools, but do not stand
in for those checks. The structured retail pilot reports its prose reader as
not applicable when it contains no authored document sections.

The custom adapter must dispatch the interview/narration, `worldloom.blind-reader/v1`
and `worldloom.target-trial/v1` envelopes to their supplied response schemas.
The subprocess is trusted local code. Keeping oracles out of JSON is not an OS
confidentiality jail: an untrusted executable needs host-enforced filesystem
isolation. The adapter must also avoid carrying author context into reader or
target sessions.

The **Foundry run** view exposes obligations, stage records, requested and
achieved noise, coverage, reader results, per-use-case confidence intervals and
the frozen dataset. A completed worker job can still have a blocked foundry
result. The CLI returns exit code 3 for unmet gates. A batch-limited foundry run
pauses after the declared number of additional batches; repeating the command
or choosing Resume advances its existing checkpoints. Failed or interrupted work
can resume from authenticated checkpoints: accepted exchanges and target
proposals are replayed, tool observations are reconstructed and compared, and
only missing exchanges call the harness. Changing the contract requires a new
revision. Completed replay needs the same adapter identity but makes no new
external calls.

## Connected retailer

`worldloom.studio.retail_pilot.pilot_project()` supplies the same connected
example as the UI. Configure its calibration contract before starting a foundry
run. Its operational program owns stock, lost demand, replenishment orders,
two-tick receipts, supplier contract prices and invoice amounts. Three process
events share one case identity and explicit predecessor references. Connector
records are projections of those events and retain their physical source rows,
owner, activity and observation cutoff.

Invoice validation checks received quantity against the originating order and
reconciles contracted receipt value, billed value and price variance in minor
currency units. Both clean invoices and price exceptions remain visible. This
mechanism supports full deliveries at the declared two-tick lag. Partial
deliveries, credit-note settlement, payment approval and general-ledger
reconciliation remain unresolved obligations. The construction report shows
eligible cases, exclusions from the case budget and orders whose receipts lie
beyond the simulated horizon.

This example is an inspectable mechanism, not a 100,000-query diversity result
or evidence of live-agent performance. Its outcomes depend on measured case
support and the configured target harness. The earlier recorded pilot below
measures a different, compile-only workflow.

## Generation and changes

Studio fingerprints the company profile, seed, revenue divisions, LOBs and
episode sequence. Eval quotas, source selectors and use-case wording are not
base-company generation inputs. Changing only those reuses the base snapshot.
Foundry construction and process configuration add recipe steps after that
baseline; their contracts bind candidate identities and stage checkpoints.

Extending a timeline authenticates the previous snapshot and rehydrates its
generator state through the existing recipe replay before adding the next
episode. Existing entity identities and earlier facts remain in the history.
Editing the company profile, revenue structure or roles creates an explicit
alternate snapshot from the seed. It is a configuration revision, not a claim
that an acquisition or restructuring event was simulated. Such events require
authored business mechanisms.

`CompanyDatasetPlan` freezes one canonical world before the first batch. Every
batch must export that same world byte-for-byte. Operational processes use
fixed seeds across batches and fault variants. Batch ordinals select different
existing case cohorts and executable contracts instead of minting companies.
When the evidence or task space runs out, the dataset stays incomplete.

Case splits co-locate transitively shared evidence and related variants. Task
splits additionally hold out entire executable families. A company-disjoint
multi-split policy cannot work inside one company and is refused. Split weights
remain approximate; large evidence components are never cut to meet a ratio.

```python
from worldloom.studio import Studio, ProjectSpec, RunOptions
from worldloom.studio.worker import run_job

studio = Studio("./worldloom-workspace")
spec = ProjectSpec.model_validate_json(open("examples/studio/retail.json").read())
project = studio.store.create(spec)
job = studio.store.enqueue(project["id"], project["revision"], RunOptions(operation="compile"))
run_job(studio, job["id"])
result = studio.store.job(job["id"])
```

## Local operation

SQLite transactions protect revision compare-and-swap and idempotent jobs.
An OS file lock gives one worker ownership of generation; it is released when
the worker exits. Restart recovery marks abandoned jobs interrupted only after
acquiring that lock. A live worker cannot be taken over. Dataset checkpoints
remain the source of resume truth, and failed jobs retain their errors.

The server binds to loopback and requires matching Host/Origin and a JSON
mutation header. It serves no arbitrary filesystem paths and uses no CORS
allowlist for external websites. This is a local operator console, not a
multi-user hosted service. Harness calls use the configured timeout and no
shell. The worker continues independently if the browser disconnects; queued
jobs are dispatched while the server remains running.

The legacy `worldloom.dataset/v1` collection schema remains unchanged for replay.
New company plans use `worldloom.company-dataset/v1`; `load_dataset_plan` and the
dataset CLI dispatch by schema. Existing collection measurements must not be
presented as evidence for the new one-company mode.

## Recorded pilot

The [reproducible pilot](measurements/company-studio.json) admits 96 queries
across inventory review and Jira state updates: one company, six batches,
93 evidence cases and 68 executable task fingerprints. It exercises all eight
supported DAG shapes. Every batch exports the exact canonical company, and
offline replay is byte-identical. Changing only the eval budget reuses the
company snapshot.

```bash
python tools/measure_company_studio.py --out ./studio-pilot --report ./studio-pilot.json
```

This is reference qualification of two business workflows, not a 100,000-query
capacity claim or a measurement of real-agent difficulty. Coding harness
adapter tests use process stand-ins; live signed-in harness sessions require
separate verification in the operator's environment.


## Native documents and file tasks

Use **Documents & files** to define `native_corpus` and `native_tasks` on the
same project revision. Each task names an existing `use_case_id`, retaining
its company, business unit, LOB and process context. The interview receives
these typed contracts in its response schema and a bounded catalogue of accepted source identifiers. Browse accepted sources in the file view to inspect further pages; neither the operator nor interview needs to invent artifact IDs. Generate through the native
operation; without a configured harness the run prepares files and a queryset,
with zero claimed target observations.

```bash
worldloom studio run PROJECT_ID --workspace ./worldloom-workspace --operation native
```

Native corpus plans select authored ArtifactIR sections by artifact ID and
section index. Generate business evidence through the existing company and
episode mechanisms, narrate it through the normal acceptance loop, and select
that narration in Studio before assembling long files. The renderer refuses
missing prose, unknown facts, repeated content and unmet distinct-fact quotas.
A request for two hundred units needs two hundred distinct authored sections.
A DOCX unit starts on an explicit new page; that establishes a page floor,
not an exact count from a pagination engine. PPTX units become slides or
speaker notes. XLSX contains authored evidence and canonical fact cells.
Every provenance locator is checked against extracted native bytes.

| Task | Measured outcome |
| --- | --- |
| Read | Exact evidence value and citations identifying its file and locator |
| Analyze | Decimal sum, difference or ratio over specified numeric evidence cells |
| Update | Correct native output, original input checksum, required edits and unchanged remaining extracted content |
| Create | Parseable native output satisfying specified content locations |

These are explicit mechanical contracts. They do not grade arbitrary prose
quality, visual layout, chart aesthetics or spreadsheet recalculation. Formula
source, comments, notes and hidden-state evidence are inspectable; PDF grading
and exact rendered DOCX pagination remain unsupported. Existing connector
write success alone still cannot certify a native file task.

Reference qualification creates or edits actual Office bytes and applies the same grader before any target call. Unsupported edits or impossible evidence locators stop compilation.

Native inputs bind exact generated SHA-256 versions. Public requests contain
the task question, submission contract and input files; expected assertions
remain in the private oracle export. Large output files may be written into the supplied per-task output directory and returned by relative file descriptor; small outputs may use base64. A filesystem-capable adapter must support those writes. The built-in authoring adapters retain their existing permission settings. The configured executable is trusted
and must be isolated by the host when evaluating an untrusted agent. This
JSON separation is not an operating-system sandbox.

Runs retain generated bytes, public queryset, provenance, private oracles and
actual trial outcomes. Replaying recorded exchanges makes no further target
calls. Tasks sharing files, original sections or canonical facts share an
evidence component. Without a native calibration contract, runs report unassigned splits and
`calibrated: false`. With `native_calibration`, the fixed native corpus gets
sealed evidence-disjoint training and holdout components before target calls.
Connector noise calibration does not certify native reading difficulty. The native queryset is a separate export from the
connector dataset. Large-file coverage is tested at two hundred units per
format, without claiming measured industry realism or live-agent performance.


### Native difficulty measurement and retail pilot

Configure difficulty in **Documents & files** or declare `native_calibration`
with a named `cohort`, `target_low`, `target_high`, `min_support`,
`max_training_attempts`, `max_holdout_attempts` and `holdout_percent`.
This measures a fixed corpus. It does not apply or select noise variants.

The sampler takes at most one task per independent evidence component and
use-case/operation/format group, distributes finite budgets across groups,
and seals train/holdout assignments before an external call. Shared original
files, authored sections or canonical facts keep tasks together. Creation tasks
without input provenance cannot establish independence merely by changing
question IDs. Different input and assertion counts remain in observation
records while estimates describe the declared group's task population.

Before spending target calls, the run checks that both sealed sample budgets can meet minimum support for every group. Insufficient population or budget produces a blocked report with available, planned and required counts.

The existing calibration ledger computes 95% Wilson intervals. Every group's
training interval must fit the requested band with the declared support before
holdout calls begin. The training decision is recorded before holdout, and
holdout must independently meet the same gate. Missing support or an out-of-band
result leaves the run blocked; it cannot publish a calibrated result.
`noise_calibrated` remains false even when fixed-corpus difficulty is verified.

The retail pilot generates actual monthly company episodes, accepts reference
authorship through the existing narration handshake, and constructs native read,
analysis, update and creation tasks from those artifacts. Its templated author
is disclosed; reference qualification does not establish editorial realism.

```bash
python tools/measure_native_pilot.py --out ./native-pilot --report ./native-pilot.json
```

Use `--harness-command` with the operator's configured coding adapter to collect
actual target outcomes. Without it the report records zero observed target
trials. The pilot's shared document evidence exercises the workflow, not enough
independent support to certify a difficulty band. Large-corpus requests use
`--periods` and `--units`; unmet distinct-content requirements are refused.


The [recorded long retail pilot](measurements/native-retail-pilot.json) contains
18 monthly episodes and 10,788 canonical company facts. Each native file has
200 distinct authored units and references 533 distinct facts. Six tasks
reference-qualify and the run replays byte-for-byte. All tasks share one evidence
component, so these six tasks do not establish calibrated difficulty.
