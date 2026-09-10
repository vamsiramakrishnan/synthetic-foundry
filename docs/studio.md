# Worldloom Studio

Studio is a local console for one company's synthetic dataset. Describe the
company, interview it through your coding harness, map use cases to owners and
processes, and generate evidence and qualified evaluations from the same world.

```bash
worldloom studio serve --workspace ./worldloom-workspace
```

Open `http://127.0.0.1:8765`. Create a company or choose **Load retail example**.
The example requests 24 inventory evaluations across Jira, ServiceNow and email.
It is an authored example with explicit operational volumes. Its process
catalogue is broader than the business mechanisms that example executes.

The console ships in the Python package. It requires no JavaScript build,
hosted service or separate frontend installation. The local workspace holds
company revisions, interview exchanges, jobs, snapshots and dataset checkpoints.
Back up the whole workspace when retaining generated datasets.

## One company, several contracts

| Object | Meaning | Generation authority |
| --- | --- | --- |
| Company profile | Identity, engine, geography, scale and business characteristics | Existing `company.resolve` and SDK |
| Revenue divisions | Division keys, revenue shares, categories and site formats | Existing `PackUnit` and pack validation; changes affect generated entities |
| Operating structure | Business units, countries, operating model and system landscape | Existing process catalogue; authored ownership definitions |
| LOB | Roles, responsibilities and process seats | Existing LOB lint and `Blueprint.lob`; roles enter the organisation |
| Use case | Business objective, owner, processes, executable workflow and evidence source | Existing `ScenarioProfile`, source contracts and synthesis programs |
| Company dataset | Quotas and diversity within one immutable company snapshot | `CompanyDatasetPlan` and independent qualification |
| Benchmark collection | Separate companies compared across an evaluation population | Historical `DatasetPlan` collection API |

Operating units and revenue divisions are different. Shared finance can own a
process without being a revenue-generating division. The UI shows both. Process
catalogue rows are definitions, not observed transactions. A use case's owner
records responsibility; it does not prove that every source record belongs to
that unit. Operational simulations remain explicit models and do not claim
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
5. **Generate.** Build the company or compile the evalset. Runs execute in a
   separate local process, so the UI remains available. Inspect remaining
   coverage and retry interrupted work from its committed checkpoints.
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
those remain the [reader and calibration gates](quality-calibration.md).

## Generation and changes

Studio fingerprints the company profile, seed, revenue divisions, LOBs and
episode sequence. Eval quotas, source selectors and use-case wording are not
company generation inputs. Changing only those reuses the exact world snapshot.

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
