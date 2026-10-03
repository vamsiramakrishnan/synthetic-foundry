# Changelog

Worldloom versions its releases and its worlds together: every generated corpus
stamps the version that made it into `world.json`. Changes that alter what a
seed generates are listed under **Generation**; they are breaking for
reproducibility even when no API moved.

## 0.1.0

### Strict sources, a mutation-tested grader and a failure curriculum

**Generation**

- Enterprise materialization defaults to `strict_sources=True`: a case the
  source corpus cannot ground is refused (`missing_source`), and
  `enterprise-evals build` reports it as the `sources_insufficient` refusal
  rather than a traceback. Corpora that built before build the same bytes.
- Opt-in `--reconcile auto` on `corpus-scale build` (and
  `corpus-scale reconcile`) derives revenue, gross-profit and headcount
  `FactReconciliation`s where unit, period and stock/flow semantics match, and
  reports each pair it did not bind with the reason.
- Opt-in source policies (`source_policy=True`) grade ambiguous joins as a
  clarifying question naming every candidate and stale sources as a citation
  of the authoritative replacement (`outcomes.clarification_missing`,
  `outcomes.stale_source_used`, `outcomes.authoritative_source_missing`).
  Existing case sets keep their bytes.

**Evaluation and harness integration**

- `tests/test_grader_mutations.py` replays 21 mutation classes over gold runs
  and requires the exact finding key for each. It caught a legacy-row
  attribution bug (a readback taken for a skipped read), now fixed;
  `plan.order` on generated rows remains an explicit strict xfail.
- `tools/measure_enterprise_execution.py --paired` measures legacy and grammar
  arms over one identity set with a shared pairing key and retained refusals.
- `improve --curriculum failures` adds training cases drawn from the previous
  champion's failure clusters each round, never overlapping held-out cases by
  id, content, source records or gold DAG. Every finding key is mapped or
  declared unmappable, and a test fails on an unregistered key.
- `worldloom enterprise-evals serve --run-store PATH` journals runs to an
  fsynced append-only JSONL file and replays open runs after a restart.
- `worldloom smoke` runs build, narrate, render, validate, evaluate,
  enterprise case generation and a reference `evalrun` end to end; CI runs it
  first. `tools/scoreboard.py` writes a digest-pinned release scoreboard, which
  the release workflow uploads.
- Cloud sessions install the package at start so the `worldloom` MCP server
  connects; mypy no longer fails on the optional `google-genai` import.

### Controlled harness queries, native realism tactics and visual proposals

**Generation**

- Optional `NativeScenarioDemand.realism` records population and presentation
  tactics in the existing replay recipe. Profiles add 3–64 canonical lines,
  Zipf/lognormal budget allocation, bounded exception prevalence, time-valid
  working assessments and configurable evidence presentation. Existing detail
  allocation and Simulator arithmetic own the results. Omitting the profile
  preserves the earlier recipe and generated facts.
- Native realism measurements distinguish realised simulation/IR quantities
  from physical pagination or perceived realism. Presentation changes preserve
  canonical facts; source variants retain their case ancestry.
- `HarnessDagConfig` compiles supplied, evidence-bearing connector records into
  search/read/reconcile/create-or-update/readback cases. Source cohorts,
  mutation variants and insufficient-result conditions are explicit. Missing
  evidence and impossible budgets refuse or produce named omissions.
- `project_native_sources` connects byte-qualified native files to that DAG
  path through an explicit extracted-content projection. Exact measure/unit
  selection, authority, source hashes and locators are retained; replicas are
  deduplicated and overlapping aggregates refused. This is not a claim that
  the target itself downloaded or parsed the original binary file.
- Optional Nano Banana generation binds infographic requests to canonical fact
  snapshots. A caller-owned Gemini Interactions client proposes PNG bytes;
  bounded decoding and content-addressed receipts permit exact offline replay.
  Images remain unqualified visual evidence. Native attachments preserve
  existing evidence and require task re-planning against their new digest.

**Evaluation and harness integration**

- Controlled retrieval evaluates typed predicates over the real ACL-visible
  corpus, with declared empty/partial/stale responses and transient faults.
  It bypasses upstream ranking. Unsupported native query syntax exposes the
  typed alternative; ordinary connector query execution is unchanged.
- Evaluator-owned receipts bind queries to delivered records, payload digests,
  pagination and semantic progress. Failed/oversized deliveries cannot satisfy
  access; their attempt history survives rollback. Unchanged insufficient
  queries cannot satisfy recovery. Correct first queries need no forced retry.
- The existing three-axis evaluator admits legitimate recovery attempts and
  grades query progress separately from computed values, mutations and readback.
  Bounded exact aggregation consumes actual source results. Public-only
  reference workers exercise direct and refining strategies.
- Grader identity advances to version 4. Create outcomes now check the
  expected persisted fields; explicitly independent mapped reads may arrive
  in either order without relaxing source attribution or result bindings.
- Native command harnesses preserve the selected executable entry path when
  staging inputs. Resolving a virtual environment's Python symlink previously
  launched its base interpreter and silently lost installed dependencies.
- `enterprise-evals harness-dags` writes standard evalrun case sets. `visuals
  plan` and `visuals generate` share the visual SDK and support offline replay.
  Model API tests use injected clients; no live image quality or live-harness
  improvement is claimed by these implementation tests.

### Native scenarios, required coverage and measured training curricula

**Generation**

- Registered `NativeScenarioEpisodes` adds bounded supplier reconciliation,
  customer settlement and inventory replenishment cases to a replayable company.
  Case-specific canonical facts, events, typed tables, formulas and authored
  process variants render as business DOCX, PPTX and XLSX files. The parameters
  are explicit synthetic assumptions, not customer-calibrated distributions.
- Scenario partitioning selects the declared artifact scope and interleaves
  process families before allocating training and held-out evidence. Shared
  facts, formula dependencies and format replicas remain one component.
  Source scope and allocation are pinned in exact resume configuration.
- Native discovery adds numeric reads across formats, source-grounded ratios
  and authored-sum reconciliation. Explicit requirement cells receive bounded
  task-selection priority. This changes generated workload identities and
  ordering; unavailable capabilities remain named findings.
- Benchmark packages use `worldloom.native-benchmark/v2`: canonical World,
  source manifests, source digest and split role participate in identity.
  Root-level native exchanges, `export_legacy`, the CLI layout flag and CLI
  model-import shim are removed. Rebuild old packages; the public task and
  target exchange protocols remain v1.
- Removed `worldloom.query_planning` after proving its realized planning and
  fixture behavior through the canonical enterprise SDK. New-schema corpora
  must be rebuilt. Nominal `checksum`, `map_reduce` and `chart` labels are not
  carried forward as executed capabilities; supported topology runs use the
  existing executable DAG catalogue.

**Evaluation and harness integration**

- `BenchmarkRequirements` declares named operation, format, calculation, scope
  and verified source-dimension cells. Assessment and improvement enforce
  independent support in training, the held-out pool and every fresh tranche.
  Correlated tasks and format copies cannot satisfy another unit; missing
  support refuses improvement before target or proposer calls.
- Authored native workflows qualify and grade bounded ordered steps, propagate
  actual graded update bytes to downstream read/analyze tasks, block descendants
  after a failed parent, and regrade receipts on resume. They observe runner
  calls and staged bytes, not internal target trajectories or autonomous plans.
  Conditional branches, iteration, created-file inputs and derived write
  contracts remain unsupported; connector workflows remain complementary.
- Training-only curriculum diagnosis reloads committed receipts and independently
  regrades their submissions. Versioned proposals carry source, query and
  evaluation demands with bounded diagnostic codes and explicit ablations.
  Evolution rederives the proposal before creating new canonical training
  evidence. New policy claims require a fresh held-out pool and sealed study.
- The public SDK and `native-evals` expose `scenarios`, `workflow-qualify`,
  `workflow-run`, `diagnose` and `evolve`; `inspect` and `improve` accept explicit
  requirements, and `build` can declare a split role. Scripted and reference
  execution tests establish implementation behavior, not live-model gains.

### A shared native benchmark workflow for SDKs and harnesses

**Generation**

- Formula rounding is explicit source semantics. Optional
  `Cell.formula_decimal_places` and authored derivation precision use decimal
  `ROUND_HALF_UP`. Retail margin facts and P&L ratios keep their two-decimal
  business meaning; XLSX and native formulas reproduce it with `ROUND` in
  percentage units. Halfway values can differ from earlier binary rounding.
  Cells without declared precision retain their serialized shape.
- Banking network totals sum only children that carry the requested numeric
  measure. Missing deposits or turnover remain absent rather than becoming
  invented zero-valued formula leaves. Valid financial tables can now enter
  native corpora instead of being excluded for inconsistent computations.
- Native partition plans opt into canonical reporting-period context in section
  headings and table titles. Repeated monthly records become discoverable from
  the actual files. The option defaults off for existing native plans; intake
  accepts contextual labels only when they match the served canonical evidence.

**Evaluation and harness integration**

- `worldloom.benchmarks` is the public seam for building, exporting, loading,
  qualifying, assessing, running and improving native benchmarks. Split packages
  separate public requests/files from private source/oracle material, validate
  exact inventories and reconstruct task contracts from canonical source.
- Native build, partition, inspection, protocol, run and improvement commands
  call that seam. The earlier optional split layout and source-free exchanges
  are superseded by the mandatory source-bound v2 package described above.
- Command and callable harness adapters receive task-scoped public inputs.
  Execution pins implementation, input, contract and grading identities;
  persisted submissions are independently regraded on exact resume. Targets
  receive actual revised policy bodies during improvement. Local subprocesses
  remain trusted processes, not an OS sandbox.
- Assessments distinguish executable tasks, requested coverage and promotion
  support. They count transitive evidence components and audit train/held-out
  overlap, fresh-tranche budgets and repeat requirements using existing gates.
  More paraphrases and format copies do not increase independent support.
- Source-family partitioning constructs disjoint train/held-out packages before
  rendering. Shared facts, derivation/supersession ancestry and table dependencies
  stay together. Final byte-bound workloads must prove the requested family
  support; caps, copies and cross-artifact tasks cannot inflate independence.
  Whole components can be grouped into richer local files; original component
  counts and allocation remain explicit. Prose synthesis can pair the same
  measure and subject across distinct periods without joining unrelated work.
- Bounded discovery samples source evidence and formats fairly before rotating
  task lanes. Small files remain eligible beside large workbooks; format copies
  share a scheduling lane. Canonical lineage still decides independence.
- Native runners require canonical source snapshots to independently verify
  expanded ancestry and pin the source graph. Caller-provided lineage claims
  cannot certify split isolation.
- Planning and native improvement intake share source-evidence guards. Hidden
  source sections, duplicate canonical identities and ungrounded changed prose
  cannot bypass source checks by presenting previously rendered bytes.
- Planning and native case compilation reuse bounded source snapshots within
  each invocation, keyed by actual bytes and format. They retain extracted
  immutable units rather than parser objects; source checks, qualification and
  fresh submitted-output inspection continue to run.

### Physical enterprise corpora and independent promotion evidence

**Generation**

- Eval-first reference proofs no longer manufacture oracle facts in read
  outputs. Bound capability assertions now scope evidence to the source's
  connector and entity; unsupported connectorless execution requires an
  explicit executor. Verification checks observed readback of dependent writes.
  Searches follow every connector page for each selector, so required evidence
  beyond the first page can qualify. Older cases that relied on fabricated
  evidence no longer qualify.
- Opt-in corpus scale plans materialise bounded relational shards, typed XLSX
  and grounded large native files. Declared integer table totals can reconcile
  exactly to canonical company facts. Source replay checks physical projections,
  native bytes and measured counts, including locale and presentation bindings.
- New scale plans opt into business native files with real source tables,
  typed measures, formula dependencies and business labels. Canonical IDs stay
  private. Explicit business native plans refuse hidden source prose and
  tables, including presenter notes, as automatic selection already does.
  Existing native plans retain their legacy serialization and bytes.

**Evaluation**

- Optional qualification policies reserve fresh, disjoint evidence-component
  tranches before target execution. Repeated paired comparisons use independent
  units and a finite confidence budget. Interrupted qualification resumes only
  under the same sealed policy, candidate, source and grader pins.
- `corpus-scale assess|build|verify` and `evalrun audit-split` expose the shared
  SDK checks from the CLI. `evalrun improve --qualification-policy` applies
  them to the existing policy and skill improvement loop.
- `native-evals build|qualify|grade` exposes reference-qualified discovery tasks
  over actual DOCX, PPTX and XLSX bytes. Prompts hide source locators; coverage
  reports ambiguity and missing operations. Cross-file analysis, grounded
  updates and creates reuse the independent native byte grader. Studio accepts
  the same planner through an opt-in discovery request.
- A native evaluation bridge feeds independently graded byte outcomes into
  the existing policy improvement runner, with canonical source lineage,
  native grader/parser pins and fresh repeat execution IDs. Plan and trajectory
  stay unobserved. Optional runner hooks supply experiment context and domain
  grader identity while preserving existing connector runners.
- A reproducible construction pilot records workload, physical row and relation
  counts, file metrics and independent source reconstruction. It does not claim
  a live target harness improved.

The first release. Everything below it is what 0.1.0 ships; the notes run
newest first, and the section headed *The foundation* is the release as it was
first written up, before the waves above it landed.

### Evidence where the vendor keeps it; the contract surface is the default

- **Default change: `connectors.surface` is `contract`.** `evalrun run`,
  `evalrun prove`, `evalrun improve`, `enterprise-evals serve` and every
  service built without a surface now present each connector with a locked
  contract as the operations Anvil's MCP server lists for it; a connector
  without one keeps its own tools, and `--surface native` presents every
  connector's own tools as before. Before the flip the standard build
  (`--seed 8128 --incident`, `enterprise-evals build --exhaustive --limit
  100 --dag-shape '*'`) proved 100 of 100 natively and 32 of 100 on the
  contract surface; after it, 100 of 100 on both, and the reference agent
  scores 1.0 on plan, trajectory, outcomes and every stage on both. The
  same world at `--limit 500` proves 500 of 500 on both surfaces and the
  reference scores 1.0 on both; `--seed 4242 --incident` at `--limit 200`,
  200 of 200 on both. Corner
  cases (four engines, seeds 1 to 3, up to 10 per world, 30 cases): 30 of 30
  on both surfaces, from 12 of 30 on the contract surface. The telecom
  programme's 2,927 record requests: 2,927 on both (they search the system
  of record, which ships no contract).
- **Default change: `connectors.serving.max_tools` is 160 (was 100).** A
  contract lists more operations than a definition has tools, and the limit
  is held per query on the contract surface: a standard case reading three
  contracted connectors is shown about a hundred tools, which the old
  ceiling refused before any call.
- **Evidence has a declared place (Generation).** A record write's evidence
  was two fields no vendor has (`evidence`, `evidence_count`). Each
  connector definition now declares where a write keeps it
  (`catalog.evidence`, or a catalog entity's `evidence`:
  `ConnectorEvidencePlacement`, `worldloom.evidence_placement`): a file's
  `description` on SharePoint, OneDrive and Drive, an issue's `description`
  on Jira, `work_notes` on ServiceNow, a message's `body` on email, Outlook
  and Teams, `text` on Slack, a page's storage `body` on Confluence (read
  first, since a page `PUT` restates the page), `Description` on
  Salesforce. The planner writes an evidence document (the `outline`
  transform: the case's sections, or one `Evidence` section, each record
  cited) in the place's format to that one field, and `write_chain`'s
  marker rewrites it there with a verification line where it set a
  `verified` field. A connector that declares no place keeps the generic
  fields.
- **A place the contract cannot carry is not planned (Generation).**
  `unserved` states why: Confluence's page body is an exclusive union of two
  alternatives that both admit every body, so Anvil's MCP server refuses
  every page write with a body; Salesforce's sObject body declares a fixed
  field list with no `Description` and no `WhatId`. Confluence page and
  Salesforce record writes are no longer generated, so the standard build's
  writes land on SharePoint, Drive and email (its 100 cases were 18
  Confluence and 11 Salesforce writes). `tests/test_evidence_placement.py`
  holds every declaration to the shipped surfaces.
- **Salesforce writes are planned again (Generation).** The authored
  Salesforce contract's sObject body declares `Description`, the textarea
  Account, Contact, Lead, Opportunity and Case each have (the Object
  Reference page for each is cited in the property and the lock's
  `documentation`); the lock, the committed trim and the shipped surface
  are rebuilt from it, and the place is no longer `unserved`. A record
  update's mapping renames `StageName` to the connector's `stage` and
  `Status` to `status`, so an opportunity moved to `Develop` or an
  escalated case is carried as the vendor names the field. The standard
  build's 100 cases write 67 SharePoint files, 14 Drive files, 13 email
  messages and 6 Salesforce accounts (were 60, 21, 19 and none) and prove
  100 of 100 on both surfaces; `--seed 4242` at `--limit 200` writes 12
  Salesforce accounts, 6 opportunities and 6 cases and proves 200 of 200 on
  both; corner cases 30 of 30 on both; the reference agent scores 1.0 on
  every axis and stage on both. Confluence's page body stays `unserved`:
  pinning the write to the storage representation needs a reviewed overlay
  that keeps one alternative of a `oneOf`, and an Anvil manifest's `params`
  retypes an input only to a scalar. An interview's case sets still prove
  on the connector tools (1 of 12 on the contract surface).
- **Confluence page writes are planned again (Generation).** Worldloom's
  Confluence manifest narrows the write body of `createPage`, `updatePage`,
  `createBlogPost`, `updateBlogPost`, `createFooterComment` and
  `updateFooterComment` from `oneOf[<Resource>BodyWrite,
  <Resource>NestedBodyWrite]` to its flat alternative (`PageBodyWrite`,
  `BlogPostBodyWrite`, `CommentBodyWrite`), with `representation` limited
  to `storage` and `representation` and `value` required, citing
  Atlassian's v2 reference for the storage representation. **This needs
  Anvil with manifest union narrowing (`params.<input>.one_of`, Anvil PR
  #63)**; an older Anvil refuses the manifest. The shipped surfaces are
  reprojected under that build (Confluence's six write tools take the
  narrowed body; the other nine change only their AIR digest), the
  placement drops `unserved`, and the planner plans Confluence page
  evidence writes in storage format, reading the page first. The carrier
  sends a nested body's required property its schema fixes
  (`representation: storage`); a field a page `PUT` restates from the page
  it read and sends back unchanged (its title) is not part of the call
  (`connectors.anvil.unchanged_restatements`), on every dispatch path, and
  `write_chain`'s marker on such a place names only the evidence field; a
  pre-existing destination of a connector whose records are numbered is
  named by a number from its record projection, since the contract types
  the page path as an integer. The standard build's 100 cases now write 44
  SharePoint files, 18 Confluence pages, 14 Drive files, 13 email messages
  and 11 Salesforce accounts (were 67, none, 14, 13 and 6), and prove 100
  of 100 on both surfaces; `--seed 4242` at `--limit 200` writes 45
  Confluence pages among its 200 and proves 200 of 200 on both; the
  standard world at `--limit 500` writes 109 and proves 500 of 500 on
  both; corner
  cases 30 of 30 on both; the reference agent scores 1.0 on every axis
  and stage on both surfaces. An interview's case sets prove 2 of 12 on
  the contract surface (from 1) and keep their native pin: the rest need
  KQL's missing `artifact_type`, Slack's named message and search, and
  list reads filtered by the interview's own fields.
- **Searches select by what the vendor filters on (Generation).** A Drive
  search picks its files by name, as Drive's own disjunction
  (`(name = 'A' or name = 'B')`: `compile_native` wrote `name in (...)`,
  which Drive refuses), when the names pick out exactly those files; a
  SharePoint search, whose tool takes KQL, picks them by `filename`
  (`compile_native` writes KQL for a KQL tool; it wrote OData, which the
  search read as free text and matched nothing). A
  Confluence page search names the pages' numeric ids, the listing's `id`
  filter (the mapping now reads it; the CQL transform inverts). A SOQL
  search selects the columns the case reads (`Id`, `Name` and any required
  field; the default list is `select` in `_query.json`) and its gold result
  is snapshotted with the same columns.
- **Creates are named as a client names them (Generation).** A file's name
  carries its format's extension (`report.pptx`), the record's fields
  restate the name in the field the vendor requires for it (a driveItem's
  `name`, an incident's `short_description`, an issue's `summary`), and a
  create carries a parent only where the record lives in one. A
  `restated_figure` corner no longer restates its issue type in its fields.
- **The contract carrier sends what a client sends.** A Graph driveItem
  create carries its `file` facet; a required body property the schema
  fixes (`@odata.type`) is sent as fixed; a numeric path step is an array
  index (Drive's `parents`); a mapping entry may `restate` wire fields from
  the addressed record (a Confluence page `PUT`'s id, status, title and next
  version); a readback after a delete keeps the deleted record's
  coordinates; an id predicate on a numbering vendor is restated on its
  numeric handles.
- **The reference agent's report states no figure.** A case with no
  expected answer is answered `Completed <case>.`; it added the number of
  calls, which the output stage grades as an ungrounded figure once a plan
  makes ten (a mapped read over three sources).
- **`serving_surface(None)` keeps the surface in force** (an enclosing
  block's, else the policy's), so a command given no `--surface` inside a
  block serves the block's surface.
- **Grading (`GRADER_VERSION` 3).** The output stage reads a field bound to
  an evidence document as it read one bound to the evidence set: every
  evidence record must be cited in the written field. A search through a
  vendor query is not held to carry the plan's `fields` beside it. The
  evidence count is stated in the document and no longer graded as a field.
- **Tests changed deliberately.** `test_contract_surface.py`: the default
  is now `contract` (was `native`). `test_enterprise_dag.py`: the map and
  marker tests read the document at `fields.description` where they read
  `evidence_count` and `verified`. `test_evalset_proof.py`: the injected
  break is a diamond joined on titles alone (an evidence count has no field
  to land in now). `test_connector_serving.py`: a mapped create rebinds its
  fields' name with its name. Modules whose agents are scripted in the
  connector definitions' own tool names (`jira.get_issue`) pin the native
  surface with the new `native_surface` fixture, since that is what they
  exercise: `test_connector_serving`, `test_evalrun`, `test_evalrun_lineage`,
  `test_evalrun_mutations`, `test_evalrun_questions`, `test_evalrun_scale`,
  `test_evalrun_stages`, `test_evalset_proof`, `test_agent_packs` (its
  pinned turn documents list connector tools), `test_anvil_provider`,
  `test_autopsy_curriculum`, `test_connector_moves`, `test_corner_cases`,
  `test_interface_lever`, `test_studio_trials`, `test_trace_brief`,
  `test_trace_export`, and `test_housekeeping` (its moves and per-item
  writes are not yet carried on the contract surface); so do the scripted
  reply test in `test_solvable_generation` and the `--dag-shape none`
  fixture in `test_enterprise_evals_pipeline`. `test_connector_packs`
  expects the new `max_tools` default. Tests whose authored
  destination was Confluence or Salesforce now write to SharePoint
  (`test_enterprise_space`, `test_enterprise_queries`,
  `test_enterprise_grounding`, `test_enterprise_fields_state`,
  `test_enterprise_operational_execution`); the two pinned plan digests in
  `test_enterprise_evals_pipeline` moved (same rows, ids and order; each
  write binds its evidence document); `test_solvable_generation` plans its
  sends itself (the first 200 rows no longer reach one) and reads the
  diamond's evidence from the document; `test_evalrun_mutations` breaks the
  evidence by writing a document that cites no record.
- **Lineage (`LINEAGE_VERSION` 2).** A value a write sent is not produced
  again by a call that returns it (the write's own answer, a later
  readback): a second write of the same evidence depends on where the
  evidence came from, not on the first write's echo. The addressed record's
  id and handles stay the write's to produce.
- **Remaining gaps, named.** Interview case sets deliver into systems the
  contract surface cannot yet carry a write to (a Confluence page body, a
  Slack message) and read through list and search operations whose vendor
  filters the mapping cannot yet express (SharePoint list items, Outlook's
  `$filter` on custom fields, Slack search); `interview.realise.prove`
  serves them on the connector tools. Housekeeping's moves and per-item
  writes on Drive, SharePoint, OneDrive, Outlook, Slack and Teams are not
  yet carried either, nor the pre-grammar single-write rows
  (`--dag-shape none`), whose bare updates carry no content. Outlook,
  Teams and Slack declare their evidence places
  but no shipped workflow writes to them, and their contracts take a body as
  Graph's `itemBody` object or Slack's signed form.

### One surface from the contract

Serving and grading; nothing a seed generates changes.

- **`--surface contract`** (policy `connectors.surface`, `native` by
  default) on `evalrun run`, `evalrun prove`, `evalrun improve` and
  `enterprise-evals serve`: a connector with a locked contract presents, in
  process, exactly the tools Anvil's generated MCP server lists for it
  (names, titles, descriptions, input schemas, annotations), and each call
  is split into the provider request Anvil's simulator builds and answered
  through the connector's Anvil mapping, as Anvil's MCP server would answer
  it (the response body, or Anvil's error envelope). The turn document, the
  `sdk-program` client and the MCP server all present it
  (`worldloom.connectors.surface`, `docs/connector-serving.md`, "One
  surface from the contract").
- **`worldloom contracts surface`** projects each contract with Anvil's own
  MCP projection, one tool at a time, beside the wire bindings read with
  Anvil's functions; `--write` refreshes the surfaces the package ships
  (`_data/connectors/anvil/surfaces/`, projected from the committed trims)
  and `--check` exits 1 on drift.
- **One mapping, two transports.** `connectors.anvil.run_request` is the
  single dispatch the stdio provider, the replay of an Anvil trace and the
  in-process contract surface run; the inverse (`placements`) is shared by
  the Anvil proof and the contract surface's gold-plan carrier, each
  placement checked by running the mapping forward.
- **Gold plans on the contract surface.** The reference agent carries each
  gold node by the exposed operation whose mapping gives back exactly its
  call, and `evalrun prove` names a node no operation carries as a
  `contract.gap`, with a per-call tally. The standard build (seed 8128,
  limit 100, every DAG shape) proves 100 of 100 natively and 32 of 100 on
  the contract surface: 62 of the 68 are gold writes of evidence fields
  (`evidence`, `evidence_count`) that Graph's driveItem, Confluence's page
  and Salesforce's sObject operations have no place for, 4 are SOQL reads
  that return only the fields they select, and 4 are searches by the
  corpus's record id that Confluence's v2 listing and Drive's `q` cannot
  express.
- **The interface lever serves in process.** With `--surface contract`,
  each interface candidate's recompiled bundle is projected once (cached by
  its AIR digest) and the loop's runs present that surface, with no Anvil
  server per case.
- **The default stays native.** The surfaces and the calls are proved equal
  to Anvil's (nine connectors listed identically; Anvil's MCP server cannot
  list Drive's file lane, which its converter refuses), but two thirds of
  the standard build's gold plans write what no contract carries, so an
  agent graded on the contract surface would be graded partly on the plans.
  The default flips when the planner writes evidence where the vendor keeps
  it.
- **A search made through a vendor query is graded by what it read.** The
  grammar grader no longer compares a search's structured predicate with a
  call that carries a vendor `query` instead (no vendor API takes a
  predicate); its reads are graded as before, and attribution falls to the
  shape rule, kept only when the call read the node's evidence. A vendor
  query that names no type also finds records stored under an alias the
  tool's types make up (a Jira `issue`), as the vendor's would.

### Real vendor contracts behind every served connector

Serving only; nothing a seed generates changes.

- **A contract lock.** `_data/connectors/_contracts.json`
  (`worldloom.contract-lock/v1`) pins, per connector, the source URL (or the
  package path of an authored contract), its format, the sha256 and size of
  the exact bytes, the version and lock date, the provenance (`vendor` or
  `authored`), the Worldloom exposure profile and manifest Anvil compiles it
  under (`_data/connectors/anvil/profiles/`, `manifests/`), the vendor's and
  the profile's operation counts, and Anvil's snapshot hash. `email`,
  `rovo`, `teamwork_graph` and `sor` say why they have none. (Underscored
  because every other JSON file beside the connector definitions is read as
  one.)
- **`worldloom contracts fetch | build | trim | coverage`.** `fetch`
  downloads and verifies each source and refuses a digest mismatch; `build`
  compiles and approves under the profile with Anvil, checks the snapshot,
  lints the mapping, and caches the bundle by source, profile, manifest,
  mapping and Anvil version, with a `build.json` receipt; `trim` cuts a
  source to the profile's operations and the schemas they reach and proves
  the cut exposes the same surface; `coverage` reports vendor, profiled,
  modelled and unmodelled operations per connector.
- **Authored ServiceNow and Salesforce contracts.** Neither vendor publishes
  a full OpenAPI document, so the Table, Aggregate and Attachment APIs and
  the REST API v61.0 query, search, describe, sObject and limits resources
  are authored from the vendors' references and committed with their
  documentation URLs.
- **Mappings for ten connectors.** Jira, Confluence, Slack, Drive, Outlook,
  OneDrive, SharePoint, Teams, ServiceNow and Salesforce each map every
  operation their profile exposes to a tool or to `unmodelled` with a reason,
  and pass their vendor query language through the shared evaluator. The
  mapping format gained constant, assembled and fallback arguments, value
  maps and key renames, `tool_by` (by a request location or the addressed
  record), result envelopes, query locators (Salesforce's `nextRecordsUrl`),
  and vendor error codes split from the message. Anvil now pages Jira's
  body-token search and some single-record reads itself; the provider
  answers those with the protocol's page, and a size Anvil defaulted is not
  recorded as the agent's argument.
- **Parity per connector.** `tests/test_contract_parity.py` compiles the
  committed trims and runs one call sequence per connector through Anvil
  and in process: records, errors and state diffs agree. The assertions on
  envelope fields still landing in Anvil (Jira's `isLast`, Slack's
  `response_metadata.next_cursor` and `messages.matches`, Drive's `kind`,
  single-record reads served as pages) xfail naming the capability;
  Confluence's `_links.next` and Graph's `@odata.nextLink` are asserted
  outright now that Anvil writes them. Each Graph, Jira, Confluence, Slack
  and Drive lock entry names Anvil's reviewed profile for the same source
  (`anvil_profile`), and a test holds the two pins equal. Page answers carry
  the match count and the query ran as provider `meta` for Anvil's trace.

### Reader-grade documents: four edges a live narration showed

Read off a live-narrated `enterprise/v2` corpus of seed 8128; `legacy` and
`enterprise/v1` corpora (and every `audit` rendering) are byte-identical.

- **The direction once, read from a lexicon.** "missing revenue plan by AUD
  10.2m adverse": a negative figure drops its "adverse" wherever its own
  clause already says which way it went, a phrase ("a shortfall of") or a
  direction word before or just after it ("missing", "fell", "overspent",
  "... below budget"), from prompts pack text
  `render.figures.direction_words.adverse` / `.favourable` and
  `render.figures.direction_window` (`figures.direction`). Decided when the
  page is spelled, so offline and live prose both read once and the ledger
  keeps exactly what the writer wrote; a writer who types "adverse" after such
  a clause, or writes "ahead of plan by" an adverse figure, is refused as
  `number_spelling` (`direction said twice`, `direction contradicts`).
- **Titles bounded, complete, dashless.** A presentation knob, `titles`
  (`free`, the shipped cut; `reader`, 12 words and 80 characters, never
  truncated, a dash between clauses as a colon or comma), from
  `_data/presentation/titles.json` (`worldloom.titles`). The title chooser
  takes a shorter clause that still carries a figure, else the lead fact's
  template; `presenter.lint_titles` names a title over length, carrying a
  forbidden character or ending mid-clause. `reader` and `filing` use it.
- **Every money table states its unit.** Under a reader spelling a schedule
  of ledger cells captions its unit from the facts its cells cite ("Business
  Unit P&L (AUD thousands)"), in DOCX, PDF, Markdown, HTML and the presenter
  deck's appendix; per column header when the columns differ; not at all
  when the table has a unit column (`figures.unit_caption`, the spelling
  rulebook's `tables` entry).
- **The length floor reaches live writers (Generation).** The rhetoric
  catalogue is `moves@3.json`, adding `floors`: each move states the fewest
  `sentences` it says (one per thing it measures, up to three; a derived move
  one) and each reader-grade request a `floor` (sentences, paragraphs, or the
  recorded `exempt` reason when it has fewer facts than moves). Both are in
  the brief (the handshake payload and the `section_moves` prompt), and a
  section below its floor is refused as `section_floor`. The offline narrator
  keeps the paragraphs its floor asks for and says a plain implication
  (`narrative.prose.implication.default`) where no kind gave one; two new
  implication texts (`ops_feed_status`, `ops_incident_opened`). What changes:
  every reader-grade request digest (so ledger keys) and the offline prose
  of the sections those texts reach. Seven sections of the reference
  narration (`examples/grocery-close/narration.json`) were below their new
  floor and are rewritten to it (a paragraph per move, a sentence per thing
  measured), and the reference adapter `tools/exec_agent.py` writes a
  paragraph per move at the length each move states.

### Solvable case sets

- **The shipped generators prove solvable (Generation).** `evalrun prove`
  over `enterprise-evals build --exhaustive --limit 200 --dag-shape '*'` on the
  `--seed 8128 --incident` and `--seed 4242 --incident` worlds, with no profile
  and each shipped profile, now finds 0 of 1,000 cases unsolvable per seed
  (was 116); corner cases 0 of 10 drafted per seed dropped (was 6); the first
  100 record-request cases of the banking, retail and healthcare programmes 0
  of 300 (was 22). Each cause was fixed where the case is made, not by
  loosening a grade:
  - A write the trajectory law `destructive_without_read` holds is planned
    after a read of its target. The planner asks the grader's own
    classification (`OperationSafety.reads_first`: a destructive tool that
    names its record by `id`, so a delete, a reply, a forward), so the two
    cannot drift. The law reads the record a call names as its target as well
    as what it wrote: a reply acts on the message it answers, and before this
    a reply was checked against the reply it created, which no call can read
    first. A send names no record and creates the one it acts on, so it has
    nothing to read and the law no longer holds it (every send, by any agent,
    was a finding). The target read waits on no evidence read, so an agent
    that opens the thread first is not out of order. 44 replies and 21 sends
    per seed.
  - A message's body (a reply, a forward, a comment) is an `outline` of the
    sections its case's document requires over the evidence, a new local
    transform in `enterprise-dag@1`, in place of the raw result set, which
    carried none of them. The 44 replies failed this too, behind the law.
  - The diamond joins its two views on the record (`DIAMOND_JOIN`: its
    `joined` node is a `unique` keyed on `id` over both projections, where it
    was a `collect`; `unique` takes optional key `fields`), so its write
    carries one evidence entry per record read, with the same node count. It concatenated them, and the
    output stage, which counts distinct evidence records, found an evidence
    count of two for one record. 51 per seed (54 with those behind a send).
  - A `restated_figure` corner's answer is the cited issue and what the issue
    says, not the lodged and current figures, which no record an agent can read
    carries.
  - A programme answer (`sor.answer`) for a list or a queue names the records
    that tripped or are open and states only how many were read; `14 open of
    18` stated a count no record carries.
  What changes, for every seed: an enterprise plan's reply, forward, delete
  and move rows (a `target-<write>` read, and for a message the `document`
  node), its diamond rows (nodes and the shape's instruction text), and so
  those rows' compiled cases and case-set digests; `restated_figure` corner
  cases' `expected_answer` (banking and insurance worlds); and every industry
  programme request whose intent answers as a list or a ranked list (its
  `expected_answer`). Other rows are byte-identical: of the pinned narrowed
  hospital plans, 9 of 171 rows and 6 of 40 moved, all diamonds. The
  documented builds no longer carry `--drop-unsolvable`; refusal stays the
  default.

- **Default change: the vendor query engine.** The policy
  `connectors.query.engine` now defaults to `native`: a search tool's `query`
  runs as the vendor's own language through the shared evaluator
  (`worldloom.connectors.query`). A live pilot's call errors were 104 of 122
  "unsupported query clause" refusals from the old parser, many of them valid
  vendor queries (`SELECT Id, Name FROM Account ORDER BY LastModifiedDate DESC
  LIMIT 50`, `priority=1^ORDERBYnumber`, JQL `OR`). `predicate` still selects
  the historical parser. What moves under the default: an emulator answer to a
  `query` string (a query the old parser refused now runs; ServiceNow drops a
  condition it cannot read and SharePoint searches an unknown property as
  text, as the products do; a malformed OData or JQL query gets the vendor's
  error text instead of `unsupported ... query clause`), and so any run ledger
  whose agent searched with query strings. Structured `predicate` searches
  are unchanged. Tests updated for
  the correct vendor behaviour: the default-engine test in
  `test_connector_native_query.py` (now asserts `native`, and `predicate` as
  the selectable legacy parser), the refused-search probes in `test_evalrun.py`
  and `test_evalrun_stages.py` (bare words and `state!!new` are not refusals
  in ServiceNow; the refusal is now a negative offset) and the scripted
  mistakes in `test_trace_brief.py` (`priority=N^ORDERBYnumber` is valid
  ServiceNow; the mistake is now a table the instance does not have, and the
  wrong-dialect email search carries Graph's `Invalid filter clause`).
- **Every search tool states its query language.** The tool catalog
  (`tools[*].query` in the turn document, plans and requests documents) and
  the MCP tool description carry the language a search tool's `query` is read
  in, a grammar summary, two or three examples in that vendor's syntax, the
  field names the connector knows, and the free-text form where the product
  has one (ServiceNow `123TEXTQUERY321=`, Jira and Confluence `text ~`, Drive
  `fullText contains`, KQL bare terms; SOQL has none and says to use `LIKE`).
  A tool the evaluator does not read (GraphQL, Rovo, the system of record) says
  to pass a `predicate`. The words are data
  (`_data/connectors/_query_docs.json`); every example is executed by the
  tests. The catalog gains a key, so a turn document's bytes change.
- **`worldloom evalrun prove <cases>`** (JSON and text; `prove_cases`,
  `EvalSession.prove()`): replays each case's gold DAG through the emulator
  under the vendor engine. Every gold query must parse in its vendor grammar
  (a structured predicate is compiled into the connector's language, an
  identity lookup restated on the vendor's identity), every gold read must
  retrieve its evidence, every gold write must leave the expected state, and
  the reference must score 1.0 on plan, trajectory, outcomes and each stage.
  Each unsolvable case names its first failing node and why; the command
  exits 1 when any is unsolvable. `--connectors anvil --contract ...` also
  serves each gold trajectory through Anvil (each call turned into its
  contract operation's vendor request), skipped with the reason when no
  Anvil CLI is found. `--record` writes `proof.json`.
- **Writers refuse unsolvable sets.** `enterprise-evals build` proves its
  cases before writing and refuses (`cases_unsolvable`) naming each case's
  first failing node; `--drop-unsolvable` writes the solvable ones and lists
  each dropped case with its reason in `proof.json`. `evalrun corners` drops
  by the same proof (every `restated_figure` case is now dropped: its answer
  states figures no readable record carries), and `corners.write_case_set`
  refuses by default. Measured on `--exhaustive --limit 200 --dag-shape '*'`
  over the `--seed 8128 --incident` and `--seed 4242 --incident` worlds, with
  no profile and each shipped profile: 116 of 1,000 unsolvable per seed, 65
  because the gold DAG replies to or sends an email without reading it first
  (`destructive_without_read`) and 51 because a diamond DAG's write carries an
  evidence count of 2 for one evidence record (`stage.output`). The documented
  builds therefore now carry `--drop-unsolvable` until the planner reads a
  send's target first.
- **Eval-set pins.** `proof.json` records the pins its proof rests on: the
  corpus (records and rows), each connector definition, the query engine and
  its vendor data, the grader, and under Anvil the contracts, any exposure
  profiles, the provider mappings and the Anvil version. `evalrun run`
  compares them with the live environment before any agent runs: a moved pin
  re-proves the set and refuses (`proof_stale_unsolvable`) when it no longer
  proves, naming what moved; a set with no proof record is proved at the start
  and runs with a warning. `run.json` records `pins`; `--resume` and `evalrun
  merge` refuse a ledger under other pins, and `compare` reports two runs
  under different pins as incomparable (`pins_mismatch`), as it does two
  graders.
- **Fixed.** A call whose `entity` names an entity the connector does not
  declare (`incidents` for `incident`) crashed the agent's turn with a
  `KeyError` from node attribution; it now gets the emulator's `Unknown
  entity` validation error, as the vendor would answer.
- **Failure ownership reads the proof.** `evalrun.ownership.read_proofs`
  (and `evalrun autopsy --proofs <case set>`) reads the `proof.json` the proof
  writes, dropped cases included, in place of the `proofs.jsonl`,
  `solvability.jsonl` and row fields it guessed at; a `world.proof`
  attribution names the proof's first failing node, check and reason.
- **Fixed: one name for a rendered file.** The served emulator named a
  `ConnectorRecord` by its title while a compiled row's snapshot named it by
  `fields.name`; on a rendered SharePoint or Drive file (whose `name` is its
  file name, `art-0001-close-calendar.docx`) the two differ, so every read or
  search over one graded `result_mismatch` for the reference agent itself.
  The proof found it: on `--seed 8128 --incident` rendered to docx, pdf and
  xlsx, 15 of 200 non-exhaustive cases. The emulator now keeps a record's own
  `fields.name` and falls back to the title only for a record with none, so
  the served answer and the snapshot agree; the interview projection's
  workaround (renaming the file to its title and keeping `file_name`) is
  gone. Emulator answers change only for records whose `fields.name` differs
  from their title.

### Plans as data flow

- **Lineage from the call trace.** `evalrun.lineage.derive_lineage` reads,
  for every call, which earlier calls it consumed: a distinctive value one
  call returned (a record id, key, sys_id, email, cursor, a copied title)
  that reappears in a later call's path, query, body or native query (read
  through the shared evaluator) makes the later call depend on it. Values
  the request states, constants, dates and attributes most items of a
  listing share never link; the most recent producer wins and the others are
  kept as alternatives; a later page depends on the page before it. An
  Anvil-served run links by what the agent actually sent and saw over HTTP.
  With the plan stage on, each ledger span's `consumed_from` is this
  lineage (it was the service's attribution); with it off the spans are
  unchanged.
- **The executed DAG graded edge by edge.** `PlanGrade.nodes.dag` (additive,
  absent on a run with no calls) carries the executed DAG and its grade
  against the gold DAG's data edges (bindings, `for_each`, the same record):
  edge precision and recall, and the findings `plan.edge_missing`,
  `plan.edge_spurious`, `plan.wrong_source`, `plan.wrong_branch` and
  `plan.serialised` (independent reads run serially; efficiency, not an
  error), glossed in the autopsy and the brief. When the agent declares a
  plan, `dag.declared` reports what it declared and never ran, ran and never
  declared, the edges that changed, and an `agreement`; `summarize` reports
  `stages.plan_dag`, `edge_precision`, `edge_recall`, `declared_cases` and
  `declared_agreement`. Every existing score, pass and finding is unchanged.
- **`evalrun run --exec <cmd> --harness-mode sdk-program`.** The agent under
  test writes one Python program per case (`worldloom.evalrun-program/v1`,
  with a generated `worldloom_client` module and the tool endpoint in
  `WORLDLOOM_TOOL_URL`, or the Anvil base URLs under `--connectors anvil`);
  Worldloom runs it under `--program-timeout` against a local HTTP shim over
  the run's own tool surface, or against Anvil, and grades the calls it made
  like any run's. The program, its digest, exit status and the plan read off
  its source (Python `ast`, calls in source order with variable flow) ride
  on the ledger line as `program`. The default harness mode is unchanged.
### A whole world from an interview

- **`worldloom interview`** (and `worldloom.interview`, its SDK) interviews a
  harness or a script one question at a time through seven layers: `company`,
  `lobs`, `employees`, `processes:<lob>`, `documents`, `timeline`, `evals`.
  Each answer is refused with every finding until it lints clean against the
  seam it feeds (`company.resolve`, the LOB cascade's roles stage,
  `episodes.lint`, `lob.lint_lob`, `doctypes.lint` and `packs.lint` on the
  assembled pack, `timeline.review` against the built roster) plus the rules
  only the interview can state: seniority levels on the reporting ladder
  (`ic`, `manager`, `director`, `executive`), the systems every process step
  touches, review chains that go up, and eval intents whose reads name steps
  and systems the processes declared. `run` (with `--script`, `--harness` or
  `--exec`), `next` / `answer` for the file round trip, `status`, `build`,
  `measure`. Requests are `worldloom.world-interview/v1`; prompt keys
  `world.interview.*`, policy `world.interview.max_rounds` and
  `world.interview.max_reads`; the bundled harness adapters recognise the
  schema.
- **Resumable and deterministic.** Every round lands in `transcript.jsonl` as
  it happens; reopening replays the accepted answers through the lints again
  and restores the question in progress, so an interrupted interview finishes
  byte-identical to one never interrupted. Builds inside the interview run
  under `registries.scoped()`.
- **One pack, no parallel format.** The accepted answers assemble into one
  `packs.Pack` (lobs, episodes, artifact types, lore, and a role table when a
  LOB adds a post) plus a resolution for what a pack has no field for.
  `interview build` builds it under the enterprise realism profile, runs the
  reviewed history with every process once per period, narrates under fact
  constraints (the deterministic writer, or `--narrate-exec` /
  `--narrate-harness`), renders, validates, and writes the corpus.
- **Evals from the interviewed world.** Each intent becomes an
  `enterprise-dag@1` query shaped by its asker's level (IC lookup, manager
  fan-in, director conditional with period- and revision-aware document reads,
  executive per-entity maps across LOBs) through the existing materialise,
  validate and compile path, with `interview_provenance` naming the question
  behind every node. One case set per level (`evals/<level>/`) with
  `provenance.jsonl`; the build refuses unless the reference agent passes
  every case. The interview projection adds `interview_*`, `period`,
  `revisions` and review-chain fields to the records it touches and mints a
  record per step on systems the engine projects nothing for; it is opt-in,
  so every other corpus projects as before.
- **`examples/interviews/kestrel-vale.json`**: a scripted interviewee whose
  first answer to every question is refused on purpose. Measured at seed
  8128: 3 LOBs, 12 levelled roles (3 per level), 3 processes over 8 systems,
  75 documents (284 files, 132 revision files), 4 periods with an incident, a
  departure and a mid-history policy, 12 cases (3 per level), reference 12 of
  12. `docs/interview-to-world.md` carries the gap analysis;
  `/worldloom-interview` drives it.
### Two levers: the agent and the interface

- **Failure ownership.** `evalrun.ownership` gives every failing finding one
  owner, `agent`, `interface`, `world` or `grader`, by deterministic rules
  applied in order (a solvability proof record or a reference agent failing
  the same way makes it the world's; an identical trajectory scored
  differently, a replay divergence or an unexplained failure the grader's;
  validation, schema and unsupported-operation errors, refused calls,
  malformed queries on a tool with no documented grammar, undeclared
  pagination, unexposed tools and serving errors the interface's, with the
  findings that follow from never getting evidence charged to the interface
  as consequences). Each attribution names its rule and evidence.
  `autopsy(attribute=True)` adds owner counts per cluster and owner shares;
  `evalrun autopsy` prints them (`--no-owners`, `--reference-run`, `--proofs`,
  `--peer`), `evalrun summarize` prints an owner line and `evalrun compare`
  the change per owner. The pilot's six training runs reclassify as 54%
  interface, 46% agent.
- **The interface lever.** `evalrun improve --levers interface` (or
  `agent,interface`) with `--contract CONNECTOR=<bundle>` lets a round
  reshape the interface the agent is served: an Anvil manifest overlay per
  connector (`evalrun.interface`), proposed from the interface-owned findings,
  the failing arguments and vendor errors and the served tools, through an
  interview (kind `anvil-overlay` on the pack interview's wire format)
  refused with findings until the diff touches only agent-facing keys,
  compiles with `anvil compile`, keeps every approval (re-granted for
  simulation with `anvil approve` when needed) and leaves every operation's
  behaviour in the compiled AIR unchanged. Runs are served through Anvil
  under the champion interface, the agent is handed the served tool catalog
  (`$ANVIL_<CONNECTOR>_SURFACE`), recompiled bundles are cached by digest,
  and candidates face the unchanged training gate, ablation and holdout.
  `--candidates` mixes agent and interface candidates.
- **Transfer gate.** An interface candidate must also not regress a second
  agent (`--transfer-agent`) on the held-out cases; without one the gate is
  skipped and the receipt says why.
- **Promotion output.** A promoted overlay is written under
  `<out>/interface/promoted/NNN/` as a reviewable manifest diff and an
  approvals record in Anvil's `approvals.jsonl` format marked
  simulation-only; nothing outside the loop's directory is touched, and
  production approval stays a human step. Receipts record `lever`, the
  overlay digests and the recompiled contract digests. With `--levers agent`
  (the default) every receipt is byte-identical to before.
### Reader-grade figures, decks and industries

**Generation.** Changes what an `enterprise/v2` build narrates and renders
(its requests, its offline prose, its figures, its deck, its Word section
layout). `legacy` and `enterprise/v1` corpora build, narrate, render and
replay byte for byte as before (checked on retail and banking builds in every
format).

- **The profile owns number spelling.** A new presentation knob, `spelling`
  (`exact`, `reader`; `reader` and `filing` profiles use `reader`), backed by
  a rulebook in `src/worldloom/_data/presentation/spelling.json` and the new
  `figures` module. A reader spelling rounds money per magnitude (`bn` two
  places, `m` one, `k` none, at least two significant figures), spells a
  sentence's figures together (one precision per unit, and a figure at least
  a tenth of the sentence's largest magnitude spelled in it: `AUD 1.0m
  adverse` beside `AUD 617.2m`, not `AUD 958 thousands adverse`), writes `k`
  never "thousands", `nil` for a zero, `%` for a `pct` unit, ISO dates in
  words and recorded enum values in words, and drops "adverse" after a phrase
  that already carries the direction (prompts pack `render.figures.*`). A
  ledger held in millions is no longer relabelled `m` by `magnitudes:
  scaled`. `figures.agrees` accepts a correct rounding of a fact at the
  precision shown and refuses a wrong one; reader checks use it (a reader
  target carries its accepted spellings, off the wire when empty).
- **Narration refusals for what a reader sees.** Under a reader spelling the
  claim validator adds `number_spelling` (the substituted prose read by
  `figures.defects`) and `slug_leak` (a snake_case token, a recorded enum
  value or a slug in the writer's own words, with the words to use). The
  request document states both rules (`narrative.spelling.rule.*`) and shows
  each fact as it will print. The contract fixture (`DeterministicProvider`,
  `writes_for_reader = False`) is not held to them; every other provider is.
  A section's facts that an earlier section of its document carries are
  marked `restated` on the request (still allowed; the offline narrator
  leaves them to the section that said them).
- **Presenter deck.** Content slide titles are built from the lead fact of
  the slide's lead move (`render.deck.takeaway.fact.*`); lead-ins listed in
  `render.deck.generic_titles` are never titles and `presenter.lint_titles`
  refuses a title that carries no fact; one fact titles one slide. The agenda
  lists the argument's sections by lead move (`render.deck.agenda.move.*`).
  Notes draw on larger pack text banks with a no-repeat rule per deck, and the
  line into the next slide comes from the relation between the two slides'
  lead moves (`render.deck.notes.relation.*`). `prose_quality.
  notes_repetition` and `NOTES_THRESHOLD` measure it.
- **Industry prose.** The composing narrator (`composed-prose-2`,
  `ComposedProvider.for_world`) puts the shipped industry pack for the
  world's engine in force while it writes: `banking` and `insurance` gained
  phrase banks for their fact kinds, and a new `infrastructure_services`
  industry pack (no aliases) speaks for the procurement engine's group.
  Industry packs may add `narrative.prose.*` keys the default does not list.
  The rhetoric catalogue moves to `moves@2.json` with move sets for the
  banking, insurance and procurement doctypes. A thin reader-grade section
  may draw on up to three context facts (same subject, kind family and
  period, figures only, current and visible to the author, not carried or
  given elsewhere in the document); a request's `recurrence`
  walks a recurring fact kind through its alternatives. Retail, banking,
  insurance and procurement builds all meet the prose thresholds, enforced
  in `tests/test_industry_prose.py`; `prose_quality` adds
  `number_spelling_defects` (ceiling zero) and counts recorded enum values
  reaching the page as slug leaks.
- **Word structure.** Under `layout: designed` the body is a Word section of
  its own after the front matter, numbered from one, with the running heads
  linked. `tests/test_docx_structure.py` verifies styles, keep-with-next,
  repeating header rows, custom properties, comments, the section break and
  the header and footer fields with python-docx.

### Reader-grade documents (`enterprise/v2`)

**Generation.** New builds default to `artifact_realism: enterprise/v2`. A
corpus that recorded `enterprise/v1` or no profile (`legacy`) rebuilds,
re-renders and replays exactly as before; `--realism enterprise/v1` still
names the first version, and `--realism enterprise` now means `v2`.

- **Section rhetoric as data.** `src/worldloom/_data/rhetoric/moves@1.json`
  declares the moves each section of the shipped doctypes makes (a variance
  memo's Position is headline, comparison, implication; its Recommendation
  decision, action, owner, risk), with a default per semantic role, and the
  fact kinds each move draws on. An authored doctype declares its own with
  `sections[].moves`, linted for unknown moves and out-of-section kinds.
  Under `enterprise/v2` a narration request carries `moves` (and
  `display_names` for subjects recorded as slugs); the brief is the prompts
  pack text `narrative.section_moves.template`, keyed in the ledger as
  `section_moves@1+<template digest>`, and the per-move instructions are
  `narrative.move.<name>`. Requests without moves digest exactly as before.
- **A composing offline narrator.** `narrative.ComposedProvider`
  (`composed-prose-1`) writes a paragraph per move from sentence plans (one
  sentence per measure of a subject, actual against budget with its
  variance), connectives, lead-ins and implications that are prompts pack
  text under `narrative.prose.*`, so an industry pack changes the words
  without code. `build --narrate` and `mosaic` use it under `enterprise/v2`;
  the contract fixture stays the writer for every other profile.
- **Prose quality is measured.** `worldloom.prose_quality` reads
  template-opener rate, repeated-sentence rate, slug leakage, sentences and
  paragraphs per section and paragraph length, with thresholds the tests
  enforce. `diversity --sizes` and `measure_corpus` report it. On seed 8128
  the fixture scores an opener rate of 0.39, a repeated rate of 0.82, eleven
  slug leaks and one paragraph per section; the composing narrator scores
  0, under 0.2, none, and more than two.
- **Provenance placement is profile-driven.** New presentation knobs:
  `citations` (`inline` or `appendix`), `layout` (`plain` or `designed`),
  `deck` (`ledger` or `presenter`), `notes` (`provenance` or `talk`) and
  `slide_budget` (`unbounded`, `board`, `briefing`). `reader` and `filing`
  set the second of each; `audit` keeps the first and its bytes. Under
  `appendix` the "Key figures" and "Figures cited" tables become one
  "Sources of figures" appendix, the workbook schedules move behind the
  paper, and the cited fact ids go into Word and PowerPoint custom properties
  and the PDF information dictionary, which `artifact_text` reports as
  `extra["properties"]`. An `enterprise/v2` corpus that names no profile is
  presented under `reader`.
- **Presenter decks.** Takeaway titles written from the facts on the slide,
  bullets that are the section's argument, a Two Content slide pairing the
  argument with its chart, charts under takeaway titles, tables in the
  appendix, talk-track notes (point, evidence, transition) from the prompts
  pack's `render.deck.notes.*` texts, and a slide budget. Seed 8128's
  executive deck goes from 52 slides (30 Title Only tables) to 21.
- **Designed layout.** A cover with a classification band, title block,
  summary box, contents and distribution; a two-column control grid;
  keep-with-next, whole short tables, unbroken rows and widow and orphan
  control, in Word and PDF.

### Serving connectors through Anvil

- **An Anvil state provider.** `python -m worldloom.anvil_provider --corpus
  <dir> --connector <name>` speaks Anvil's stdio JSON-RPC provider protocol
  (`initialize` at protocol version 1, `invoke`, `shutdown`) behind `anvil
  simulate serve --provider-cmd`. Reads and lists come from the corpus's
  records, searches run their vendor query (Jira's `jql`) through the shared
  query evaluator, writes go through the emulator's state (`--snapshot-out`
  writes the post-state for a diff), and domain errors carry the vendor's
  status, code and error body. Cursors are offsets, so paging is
  deterministic; stdout carries protocol lines only.
- **One mapping file per contract.** `_data/connectors/anvil/<connector>.json`
  (`worldloom.anvil-mapping/v1`) maps each contract operation to a connector
  tool, its arguments to request locations through named transforms, and its
  answer to a result shape, or marks it `unmodelled` with a reason. The lint
  refuses an exposed operation that is neither; it runs at the handshake and
  before an eval run starts. Jira ships, covering all 26 operations of Anvil's
  trimmed Jira Cloud v3 contract (9 modelled, 17 unmodelled).
- **`evalrun run --connectors anvil --contract <bundle>`** (and
  `EvalSession.run(..., anvil=AnvilServing(...))`) serves each case through
  Anvil: the agent gets `ANVIL_BASE_URL`, `ANVIL_<CONNECTOR>_BASE_URL` and
  `ANVIL_TOKEN` (the exec seam passes them in the child's environment, and the
  turn document gains an `anvil` block), calls the vendor API, and the Anvil
  traces are replayed into the case's run so plan, trajectory, outcomes and
  stages grade unchanged. A replay that differs from what the agent was served
  is noted as `anvil_divergence`; `agent_identity.serving` records the
  contracts. The default stays the in-process emulator, byte-identical.
- **Stages read queries through the shared evaluator.** The query stage's
  filter fields, entity and window clauses now come from the vendor
  evaluator's parse, bound to the record keys the search compared (JQL
  `created` is the record's `created_at`, OData `receivedDateTime` its
  `received_at`), and from the historical conjunctive parser only for a query
  the evaluator does not read. A relative bound such as `created >= -7d` is
  now a time relative to the connector clock, so its window is checked; JQL
  `OR`, native date functions and OData expressions are read rather than
  dropped as unknown, so `query.missing_filter` and `query.wrong_window` fire
  on them; a disjunction still names the fields it constrains.
- **Parity.** `tests/test_anvil_provider.py` replays one Jira call sequence
  (JQL search over two pages, get, create, edit, transition, comment, three
  domain errors) through the emulator and through Anvil and the provider, and
  requires identical records, errors and state diff, and one case graded
  identically both ways. Skipped without Node and an Anvil CLI.

### Connector searches in the vendor's own language

- **One query evaluator for every connector language.**
  `worldloom.connectors.query` parses JQL, SOQL, ServiceNow encoded queries,
  OData (`$filter`, `$orderby`, `$top`, `$skip`, `$select`, `$search`), CQL,
  KQL, Drive `q` and Slack search modifiers into one frozen filter tree,
  resolves every relative date against the corpus clock (never the wall
  clock), binds vendor field names to record keys from the connector
  definition's `query_fields` and field manifests plus the per-language
  vendor names in `_data/connectors/_query.json`, and ranks free text with the
  repository's BM25, ties by record id. Anything outside the supported grammar
  gets the vendor's own status, message and response body (Jira's `Field 'x'
  does not exist or you do not have permission to view it.`, Salesforce's
  `INVALID_FIELD` with its row and column, Graph's `Invalid filter clause`,
  Drive's `Invalid Value`); ServiceNow drops an unknown field and SharePoint
  searches an unknown property as text, as those products do. The same
  `parse`, `QueryTarget` and `execute` serve an out-of-process provider.
- **Opt-in in the emulator.** The policy `connectors.query.engine` (default
  `predicate`) or `ConnectorEmulator(query_engine="native")` makes a search
  tool's `query` string run through the evaluator: SharePoint's and
  OneDrive's search tools read KQL, the rest their connector's
  `query_language`; GraphQL, Rovo and the system of record keep the historical
  path. With the default, every emulator answer is byte-identical to before.
  `docs/connector-serving.md` has the grammar and the opt-in.
### Documents the size companies keep them (Generation)

- **New default: `enterprise/v1`.** `worldloom build`, `worldloom mosaic` and
  `sdk.Blueprint.build` now record `artifact_realism: enterprise/v1` on the
  recipe and render long-form documents: Word and PDF controlled reports
  (cover, document control with version, owner, approver, reviewers and
  classification, revision history, approvals, review record, contents,
  numbered sections and subsections, a "figures cited" table per section,
  the pack workbook's schedules and native charts, appendices for supporting
  facts, lineage, measures, chronology and related documents, running heads
  and `Page X of Y`); PDFs add bookmarks, a multi-pass contents page with page
  numbers, tables that repeat their header across pages and a sign-off form.
  Decks are assembled from the pack on the template's real layouts (title,
  agenda, section header, content, two content, comparison, title only with
  native charts and tables), with footer, date and slide number and speaker
  notes on every slide. Markdown is a wiki export (front matter, numbered
  headings, lineage as a YAML block, related pages, attachments, page
  history); HTML is an intranet page (site navigation, breadcrumbs, metadata
  and labels, attachments, related pages, history, comments) with a site
  home page. Measured on `--seed 8128 --incident --narrate`: the board paper
  went from 237 words to about 4,600 and 26 page-equivalents, the variance
  paper PDF from 6 pages to 37, the deck from 7 blank slides to 52 with 52
  sets of notes and 4 native charts.
- **Revisions and packs.** Controlled documents get separate revision files
  under `artifacts/revisions/`: a v0.1 draft dated inside the window its
  citations open (figures not yet true are TBC, superseded ones state the
  predecessor), a v0.2 reviewed version with native Word comments from the
  author's manager or approver, and a v1.x amendment for each later fact that
  superseded a cited one, as tracked changes. Packs (month-end close,
  executive committee, incident) get `artifacts/families/<pack>/index.md`,
  and the executive committee pack an `agenda.docx`.
- **Connector files carry their text.** Under `enterprise/v1` a SharePoint or
  Drive file record carries `content` (so `get_file` returns the document's
  text), `structure` (pages, slides or sections) and the revision files as
  `version_history`; Confluence pages carry their page text.
- **Measured.** `worldloom diversity ./corpus --sizes` (and `measure_corpus`,
  under `documents`) reports words, pages, slides, notes, sections, tables and
  revision files per document type and format, read from the files
  (`worldloom.artifact_text`, standard library only).
- **`legacy` is byte-identical.** `--realism legacy`, `Blueprint.realism("legacy")`
  and `Built.render(realism="legacy")` write no key and reproduce the old files
  byte for byte; a recipe without the key (every existing corpus, the golden
  `retail-close`) is `legacy`, so re-rendering and replay do not move.
  `worldloom render --realism` switches an existing corpus without a rebuild.
  The IR, the facts and the validation report are identical under every
  profile: length comes from structure, and every figure is a fact spelled
  as prose spells it or an IR cell, attributed to its source.
- **Build time.** The same standard build (all six formats) takes about
  6.5s under `enterprise/v1` against about 2.5s before (and under `legacy`).

### Closing the loop: agents that improve against the corpus

- **Query, plan-node and output stages.** `worldloom evalrun` now grades the
  stages inside its three axes (`worldloom.evalrun.stages`): every search or
  list call against the gold evidence of the node it served, by what the
  emulator returned (evidence recall and precision, over-fetch, pages, zero
  results, errors, and structural checks for scope, language and time window
  against the as-of clock), attached as `TrajectoryGrade.queries`; the
  agent's declared or implied DAG against the gold DAG node by node
  (`PlanGrade.nodes`); and the output's field values, format, sections and
  grounded facts (`OutcomeGrade.output`; cases compiled from a corpus now
  carry the planned artifact's `sections`). New finding keys (`query.*`,
  `plan.node_*`, `output.*`) cluster in the autopsy and a query section
  joins the trace brief; `summarize` and `compare` report them as `stages`
  and `stage_deltas`. No existing axis score, pass or verdict moves. Policies
  `evalrun.grade.queries`, `.plan_nodes` and `.output` (on by default) and
  `evalrun.grade.overfetch_ratio`. With a stage on, the grader identity gains
  a `stages` part (stage grader version 1), so a new run's grader digest
  differs from an older run's and a loop pinned before this change refuses to
  continue under it; `compare` judges the axes on the digest without that
  part, so older ledgers stay readable and comparable. With every stage off,
  ledgers, summaries and the digest are byte-identical to before.
- **Trace-level brief.** `worldloom evalrun improve --brief traces` (SDK
  `brief="traces"`, policy `evalrun.improve.brief`; `worldloom evalrun
  campaign --brief`) shows the proposer, below the autopsy summary, an error
  catalogue of each tool, error code and normalised message with a raw
  message, the failing arguments and the accepted shapes of the same tool;
  the declared contracts of those tools; and failing trajectories turn by
  turn (`worldloom.evalrun.evidence`). `--reference-run DIR` (SDK
  `reference_run=`) adds the reference agent's accepted calls and
  trajectories, ids masked and write payloads reduced to field names, and is
  refused when it holds a held-out case. Sections are fitted to the
  interview message, dropping whole items and saying so. The default
  `summary` brief is byte-identical to before.
- **Wide search.** `worldloom evalrun improve --candidates N --screen-cases M
  --finalists F --parents champion|archive --round-budget B` (SDK keywords
  of the same names, policies `evalrun.improve.candidates`, `.screen_cases`,
  `.finalists`, `.parents`, `.round_budget`; `evalrun campaign` takes the
  flags too) asks for N proposals a round, each told it is candidate i of N
  and shown the earlier ones by summary and diff size, dedupes identical
  bodies, and screens the rest on training cases by successive halving:
  a stratified, seeded order of the training cases, one run each on the
  first M, the better half advancing by paired mean delta against the
  champion's existing runs while the prefix doubles, until F finalists go
  through the unchanged training gate, ablation and holdout. Every policy
  evaluated in full is archived under `archive/` with per-case and
  per-failure-cluster scores; `--parents archive` draws each round's parent
  from the archive's Pareto frontier, weighted toward a high mean and few
  visits by a seeded draw, so a near miss becomes a stepping stone.
  Receipts record the parent, every screening stage and the case-runs spent;
  an interrupted round resumes with its proposals and finished screens. At
  the defaults receipts and run directories are byte-identical to before.
- **Noise-aware gates.** `worldloom evalrun improve --repeats K` (SDK
  `repeats=`, policy `evalrun.improve.repeats`, default 1) runs each policy K
  times per case set, each repeat an ordinary pinned run under
  `runs/<pack>@<digest>/<label>/rep-<i>`, cached and resumed on its own. The
  gates then judge a paired comparison over per-case means: a deterministic
  paired bootstrap interval (seeded from the case-set digest and the two
  policies' digests; `evalrun.improve.confidence` 0.95,
  `evalrun.improve.bootstrap_resamples` 2000) with the t interval beside it.
  Training passes when the mean reaches the delta band and the lower bound
  reaches `evalrun.improve.min_train_ci` (0.0); the holdout when the lower
  bound is above `evalrun.improve.min_holdout_delta`; an axis fails only when
  its upper bound is below minus the band; a case is newly errored only when
  it errored in most candidate repeats and no champion repeat. Receipts record
  the interval, the standard error and each side's noise floor, and ablation
  drops a hunk only when its contribution's upper bound is below the
  tolerance. At K = 1 every rule, receipt and run directory is byte-identical
  to before. **`worldloom evalrun noise RUN_DIR...`** (`evalrun.noise.noise`)
  reports one policy's run-to-run spread and the minimum detectable effect
  for N cases at K repeats (power `evalrun.improve.power`, 0.8), so an
  experiment can be sized before it is paid for.
- **`worldloom evalrun improve`** runs a champion `agent` pack over the
  training cases, clusters its failures, and asks a proposing harness for a
  revision through the pack interview. The candidate is kept only if it gains
  at least the delta band on the training cases, loses nothing beyond the band
  on any axis, and then gains on held-out cases the proposer never saw: a
  second corpus from fresh seeds, or a stable share of the first. Every round
  writes a receipt and its diff; runs already paid for are reused. The SDK
  form is `EvalSession.improver(...).run(champion)`, and the
  `worldloom-improve` skill carries the procedure with its detail in
  references read on demand.
- **Agent packs.** The policy of the agent under test is a pack of kind
  `agent`: a standing instruction, overlays on the turn and plan rules, tool
  advice, planning guidance and a skills tree (`skills/<name>/SKILL.md`,
  references, scripts). The rules that define the reply grammar are locked.
  Runs record the pack's reference and digest. A proposer replies with a
  unified diff against the champion's tree, applied strictly; hunks that
  carry less than `evalrun.improve.ablation_tolerance` are taken out before
  the holdout. Generated code lives only in the pack's `skills/` tree.
  `worldloom pack tree`, `pack from-tree` and `pack diff` move a pack between
  JSON and a directory.
- **The improver is improvable.** The proposing harness runs under an
  `agent` pack of its own (`agent:proposer-baseline` ships, restating
  today's proposer): `evalrun improve --proposer-pack` puts its standing
  instruction and skills ahead of the pack interview inside the same
  digest-derived fence the agent under test gets, and each round's authoring
  log records its reference and digest. `worldloom evalrun improve-proposer`
  scores a proposer policy by the held-out gain of the agents it improves
  across a set of tasks, has the proposer revise its own pack by diff, and
  promotes a revision only when it gains on the training tasks and then on
  meta-held-out tasks the brief never describes; receipts land in
  `meta/rounds/`. The SDK form is `evalrun.meta.improve_proposer` and
  `EvalSession.improver(..., proposer_pack=...)`. Without a proposer pack
  every request, prompt and receipt is byte-identical to before.
- **The grader is frozen by digest.** Every run records the rater, the
  `rater.*` prompts, the rubrics and the grading policy as one digest;
  `evalrun compare` calls nothing an improvement across two graders, and the
  loop stops if its grader moves. `worldloom evalrun agreement` measures the
  local answer grade against Eval Studio's on the same answers (MAE, Pearson,
  Spearman, Cohen's kappa, per shape).
- **Failures become targets.** `evalrun autopsy` clusters failing cases by
  finding key with the dimensions they concentrate in; `evalrun curriculum`
  turns the clusters into a dataset plan on a fresh seed with a held-out
  share, and flags slices the agent has saturated with harder shapes to try.
  `evalrun corners` builds cases from the world's own events (a confirmed
  cause that superseded a hypothesis, a restated figure, an escalated invoice
  exception, a handover) that the reference executor must solve, and
  `evalrun frontier` keeps the ones a champion fails.
- **Value at stake.** `evalrun value` weighs each case by the money on the
  records it touches, how often its activity runs and the cost of its
  operation, and reports value-weighted pass rates; the loop's `--value`
  gates on the weighted delta too. A curriculum can keep a share of its rows
  on the company's own operational mix, within a total variation bound.
- **Runs at scale.** `evalrun run --concurrency N` keeps N cases in flight
  on a per-run-locked service with the ledger in case order; `--shard i/n`
  and `evalrun merge` split one run across processes or machines and join it
  byte-for-byte; `--resume` continues a killed run; the ledger is fsynced and
  a torn last line is dropped rather than fatal. On a slowed reference agent,
  twelve cases ran 7.2 times faster at concurrency 12.
- **Training data.** `evalrun export` writes SFT transcripts, preference
  pairs and reward records whose verifiable parts are kept apart from the
  model-rated answer score, and refuses held-out cases unless asked.
- **Recorded, not generated.** A run's `run.json` now names its grader, and
  refused calls in a case's ledger carry the position where they fell. What a
  seed generates is unchanged.
- **Campaigns.** `worldloom evalrun campaign` keeps improving past
  `no_failures`: a sequence of stages, each a fresh training set and a sealed
  held-out set from seeds the campaign never used, each running the improve
  loop until it stops. A saturated or plateaued stage escalates to harder
  slices (`escalate`, or the corner frontier); a failing one gets a curriculum
  aimed at its autopsy. A held-out case never reaches a later training set
  (refused as `held_out_overlap`), and after every stage the original and the
  current champion both run its held-out cases, so `campaign.json` reports the
  gain over the starting policy stage by stage on cases neither trained on.
  Stage builders are injectable (`StageBuilder`; `DatasetStageBuilder`,
  `CornerStageBuilder`), completed stages are read back rather than rerun, and
  the SDK form is `EvalSession.campaign(...)`.

### Scale, live harnesses, and the last literals

- **Dataset compiles run in parallel waves.** `batch_wave` (in a plan or a
  Studio project) commits up to K batches at a time on worker processes
  (`--workers`, `WORLDLOOM_DATASET_WORKERS`, `policy: dataset.workers`). The
  output depends on K, which the plan records, and never on how many workers
  ran it or in what order they finished. A resumed wave gives the same bytes.
  At K=1, the default, the plan and every output are unchanged. On a 62-use-case
  telecom company an 8-batch compile took 141 s instead of 205 s on four
  shared cores; the first batch of each use case, which builds its harness,
  dominates.
- **`industry.evalrun_cases` indexes records** by binding and period instead
  of scanning all of them for every request: banking takes 2.0 s instead of
  523 s, and retail 1.2 s instead of 95 s. The rows are identical.
- **Every live-harness path was run against a signed-in coding-harness CLI and works.** That
  covers pack authoring (including a refusal round), the Studio company
  interview, narration (also under `--pack industry:banking`) and harness
  evalrun in plan and run modes. The runbook is `docs/live-harness.md`. Three
  bugs were fixed:
  - Harness children inherited the caller's session id and persisted a
    transcript under it. They now run with `--no-session-persistence` and
    without the session variables.
  - The pack interview got the evalrun closing sentence.
  - The narration rules showed `{{fact:ID}}` with doubled braces.
- **Connector definitions are the single source.** `CAPABILITIES` and
  `BUILTIN_CONNECTORS` are derived from a `catalog` block in each definition,
  which holds the display name, entity verbs, stable id and formats. An
  uploaded connector declares its own; an inconsistent catalog is refused
  when the definition loads.
- **The rater's text is in the prompts pack**, pinned to Eval Studio's
  wording by a test. An industry pack cannot override `rater.*`.
- **A loaded corpus knows who holds each role.** `World.role_holders()`
  rebuilds the map from the recipe, so ticket assignees survive a reload and
  a pack that renames titles. Nothing is added to the exported files.
- **Structural decisions read stable section keys, not displayed headings**
  (`SectionPlan.key`, `doctypes.RESERVED_KEYS`). The shipped outline headings
  (117 `documents.outline.heading.*` keys) and the per-engine role titles
  (54 `roles.title.*` keys) are prompts that a pack can override. An author's
  own heading is displayed exactly as written.
- **Generation:** none for a default build (verified byte-identical, also
  for the bank, insurer, procurement and grocery archetypes). A compile with
  `batch_wave > 1` records it in its plan.

### Every layer is a pack: found by name, layered, uploaded or authored by a harness

- `worldloom.packkit` is one mechanism for every layer the product used to hold
  as literals. A pack is a JSON envelope of a registered kind: `industry`,
  `prompts`, `policy`, `company`, `connector`, `lob`, `doctype` or
  `presentation`. Packs are searched in this order: `--pack-root`,
  `WORLDLOOM_PACK_PATH`, `~/.worldloom/packs`, then the shipped
  `_data/packs`. A pack layers through `extends` onto its kind's default,
  resolves to a content-addressed body (`kind:name@digest`), and is put in
  force with the global `--pack` flag or `packkit.use`. Code reads packs
  through `packkit.text`, `policy` and `term`.
- `worldloom pack kinds|list|show|lint|install|author` and
  `pack interview request|accept`. Upload and harness authoring run one lint
  and refuse with every finding. The interview reuses the exec seam and the
  cascade protocol: questions go back to the operator, and a refused proposal
  goes back to the harness with its findings.
- Industry packs colloquialise the product. Every template reaches a word
  through `{{term:site}}` (case and plural are derived), so a corpus built
  under `--pack industry:banking` says "Branch Performance" where the default
  says "Store Performance". Twelve industries ship, one per
  process-catalogue overlay, with their aliases, engine, terms and example
  company. `industry_of` recognises a company by the aliases of every visible
  industry pack, so an uploaded industry is recognised by its own phrases.
- About 200 prompts and templated sentences and 49 policy defaults moved from
  code into the default prompts and policy packs. They cover Studio interview
  and harness roles, industry requests and briefs, system-of-record channel
  text, enterprise query instructions, evalrun turn and plan instructions,
  finance workbook headings and ticket texts, serving limits, and programme and
  record policy. The defaults hold the exact literals they replace.
- Connector packs are served: an uploaded connector definition (a `zendesk`)
  reaches the emulator, the served surface and the enterprise specs.
  Per-connector record shapes are a declarative `record_projection` in each
  definition, where they used to be an `if connector ==` chain. Identity keys
  are defined once.
- Studio can upload a pack, generate one with the configured harness (a
  background job whose command the browser cannot supply), and choose a pack
  for a company. `ProjectSpec.packs` pins each reference at revision time, so
  a revision replays exactly or is refused. Presets and operational examples
  are data, and a shipped industry pack does not reshape a shipped preset.
- Support and revenue business-unit archetypes are defined once (there were
  three copies). The SDK reads the function ladder in force.
- **Generation:** none for a default build. A build with a non-default pack in
  force records the pack's reference, digest and merged body under the
  recipe's `packs` key. `build --replay` reinstates the pack from that record
  without the pack file, and refuses a body that no longer matches its digest.
  The only recognition change is that "deposit-taking institution" now
  resolves to banking.

### A catalogue company runs from interview to graded evals at scale

- `worldloom industry project banking` → `studio init` → `studio advance`
  failed at compile on every shipped industry: about a third of the derived
  use cases read ServiceNow, Salesforce, SharePoint lists or Confluence, and
  their system-of-record records were only ever projected onto `sor`, so
  construction refused them (`scoped process evidence needs 1 records;
  observed 0`, repeated 24 times). `sor.product_records` now restates each
  such record on the emulator the line reads, under the same binding scope,
  with that connector's own fields and `sor_record_id`. The `sor` record set,
  and every answer read off it, is unchanged. **Generation:** a catalogue
  company's `servicenow`, `salesforce`, `sharepoint`, `confluence`, `jira`
  and `email` projections gain these records; worlds without a process
  company project exactly as before.
- `industry.project` sizes `max_batches` from its own use cases and counts
  (`industry.batch_budget`). The fixed budget of 12 left 52 of banking's 64
  use cases unattempted, and nothing said so. The workflow report names a
  `batch_budget_short` finding for any project whose budget cannot meet its
  counts.
- A qualification proof keeps the records the run wrote (`post_state`) and
  the ones it deleted (`deleted`), not the whole post-run state of every
  connector it touched. On the banking company a proof was about 40 MB, or
  about 130 GB for the programme; a batch's proofs are now about 200 KB.
- The query emulator filters to its own connector before copying, and copies
  only records an override changes. Before this, each connector's emulator
  deep-copied every connector's records for every query. Requirement checks
  project and flatten a connector once per world. The served surface forks one
  base emulator per connector, and a tool call opens a transaction that
  copies only containers. Every emulator write already replaced its record
  rather than changing it in place. On the banking company a compile batch
  fell from 2.5 to 6 minutes to 20 to 100 seconds, and reference-grading 58
  cases fell from 414 s to 154 s, with identical grades.
- A failed run is the named blocker. The workflow report carries a
  `run_failed` finding, and its `next_action` is that run with its `job_id`.
  Before this, the report pointed at "Connect a writing harness", and
  repeating `studio run` replayed the recorded refusal without retrying.
  `advance` and `run` now resume a failed, interrupted or paused run from its
  checkpoints, and mark a run left `running` by a killed process as
  interrupted.
- `studio advance --max-steps N` walks the stage DAG (build, compile, evalrun,
  and the harness stages when a harness is given) and stops at the first
  proposal, configuration gap or refusal. It lists the runs it executed as
  `steps`.
- A construction refusal names each cause once, with its count and the use
  cases and requirements it holds for. A compile of a constructed company with
  a base-only narration selected says so, where it used to report the
  narration as belonging to another snapshot.

### The planner grounds every row in the world it plans for

- The documented loop starts with `worldloom enterprise-evals build <world>
  <cases> --limit N --dag-shape '*'`. On every shipped world and profile it
  exited 1 at validate with findings like `query <id>: evidence <rid> carries
  no fact (servicenow:incident)`. Two causes shared one missing predicate.
  The corpus builder selected source records by position, so a pool of
  thirty-eight Jira issues with one fact-less record put that record into
  twenty queries. The planner admitted rows over sources the world had no
  records for, the builder minted fact-less filler records to meet the
  count, and the validator refused them.
- `enterprise_evidence.carries_evidence` is the validator's acceptance rule,
  stated once: a record is evidence when it carries a World fact or a valid
  pinned observation. The validator uses it, and the builder now selects by
  it. Selection is a stable sort of the pool in its existing order with
  evidence-bearing records first, so a pool whose leading records all carry
  evidence selects exactly what it selected before. A record without
  evidence is taken only when no evidence-bearing record is left.
- The planner reads the world's groundable inventory before it plans a row.
  `enterprise_grounding.groundable_inventory` counts, for each source a
  registry names, the evidence-bearing records the world offers it, through
  the same `generate_connector_data` call the build makes and the same
  entity aliases the builder resolves. A source with fewer such records
  than its role's minimum is inadmissible for that world. `_groundable` is
  the sibling of `_admissible`, applied where lanes are built, so the
  candidate stream and the derived required set describe one space and the
  report still says `exact: true`. A mapped read or a conditional demands
  two witnesses of a source, so those shapes are not decided for a row
  whose source has one. `CoverageReport.ungroundable_sources` names what the
  world could not ground, as sorted `connector:entity` strings, and the
  `plan` and `build` commands print it. A profile the world grounds nothing
  of is refused with the code `ungroundable_world`, naming the sources,
  rather than exported as an empty corpus. `enterprise-evals space` has no
  world and is unchanged.
- The filler is a tripwire. A query that still reaches materialization over
  a source the world cannot ground raises `ungroundable_source`, naming the
  query and the source, instead of minting a record the validator refuses
  later. Destination fixtures for record-addressed writes are untouched.
- On `examples/hospital` the default profile builds in two seconds and
  names `email:thread`, `salesforce:account`, `salesforce:case`,
  `salesforce:opportunity` and `servicenow:incident` as ungroundable; the
  back-office and omnichannel-retailer profiles build too. `email:thread`
  is ungroundable on every world the builtin projections serve: the email
  projection emits `message` records and the definition does not alias
  `thread` to them, so email as a source grounds only through the
  operational projections, which do emit threads. That gap is recorded
  here, not fixed.
- Byte identity. A plan whose sources all ground is the plan it was:
  measured on a narrowed profile over `jira`, `confluence` and `sharepoint`,
  the full 1,518-row plan, its first 40 rows, a 40-row built corpus, and
  the pipeline test's 12-row corpus on `examples/retail-close` are
  byte-identical before and after this change. A plan over an ungroundable
  source changes, because its rows are gone; no such plan ever built a
  corpus. Two pinned plans moved for that reason and say so where they are
  pinned: the narrowed retail profile over `jira`, `confluence` and `email`
  on `examples/hospital` (312 rows, 167 of them over `email:thread`, 183
  `email:thread` findings at validate) now plans 171 rows, and the unbound
  operational profile's first three rows (two of which failed validation)
  are now three Jira rows. No built corpus changes bytes, so this is not a
  Generation change.
- Qualification and dataset generation plan the world-free space
  (`plan_queries(..., ground=False)`). They execute every query under
  `strict_sources` and record its refusal by name in their own ledgers, so a
  pool's identity and its report do not depend on the inventory.

### The reference passes its own case set

- With every shipped profile building, the reference ran on all five case
  sets from `examples/hospital`. Four scored 40 of 40; the omnichannel profile
  scored 33, every miss a `result_mismatch` on a Confluence search. The
  compiled row's `input_snapshots` and the served emulator shaped the same
  record to two ids: `runtime_records` set no `ident`, so the shaper minted a
  hashed page id, while the emulator's own intake sets `ident` from
  `external_id` and answered `10000001`. `runtime_records` now sets `ident`
  the same way. After: five of five sets at 40 of 40.

- The reference agent is the executable ceiling for a case set, and on a
  project-built world with the back-office profile it scored 35 of 40. Every
  miss was the grader's, not the agent's. Two `delete_chain` rows expected
  `not_found` from the readback after the delete, but a designed failure
  upstream (a denied write, a missing stable id) blocked that readback, so it
  never ran and the grader counted an unhonoured failure. One `delete_chain`
  row updated a record and then deleted it; the update read "is gone". Two
  `write_chain` rows updated a record the same run created, or a record
  another node had already updated; the diff attributed the change to the
  first node and the marker update read "no record of the entity changed".
- `grade_trajectory` no longer expects a failure point on a node an honoured
  failure blocked; a point the agent did reach and meet still counts.
  `grade_outcomes` reads an update node's own successful spans, as the
  service recorded them, before it falls back to the diff, so a second update
  on one record is attributed to the node that made it. An update whose
  record the plan's own delete then removed is met from the span when the
  expectation names no target state to check; with one, it stays "is gone".
- Once a delete could be the primary write, two more graders were wrong about
  it. `compile_failure_contract` asked for a *created record* on a
  `partial_write` at a delete whose id is bound from the read before it, and
  the DAG trace grader reported `state_missing` for the record the delete
  removed. A created record is now asked of writes that create, and a
  delete's absent record is its effect, not a missing state.
- After: back-office 40 of 40, the delete probe 12 of 12, both with every axis
  at 1.0. Four regression tests hold each reading.
- `evalrun run` appends every graded case to `results.jsonl` as it lands. A
  coding-harness run of three cases hit its 40-minute wall clock and left
  nothing, because the ledger was written only at the end. A killed run now
  leaves every case that finished, and a run that completes rewrites the same
  lines, so its bytes do not depend on the checkpoint. `--progress` prints
  one line per case to stderr, with seconds under `--timed`.
- The single-case rerun measured the harness path: eight turns of reads in
  805 seconds, about 100 seconds per turn, each turn a fresh `claude -p`
  process over the whole transcript. The ninth turn returned no text and the
  adapter died with `Expecting value: line 1 column 1 (char 0)`, which named
  nothing. `studio.harness.parse_object` now reads an object a model wrapped
  in a fence or a sentence, and refuses an empty turn by harness name with
  the envelope's own `subtype` and `num_turns`. Size `--timeout` in hundreds
  of seconds per turn and `--limit` in single digits for a first harness run.
- The two-case rerun named the cause of the empty turn. The adapter ran the
  child in plan mode to keep it off the project files, and on the sixteenth
  turn the child answered in prose that plan mode restricted it to read-only
  actions and required a tool it did not have; the other case timed out
  after fourteen turns of reads, about 120 seconds each. The agent under
  test, the planner and the judge answer from the document on stdin and
  touch nothing local, so `command_for` now gives them a child with no tools
  at all and no persisted session; the authoring and narration seams, which
  may read the project, keep plan mode.
- The first case that graded (score 0.48: plan 0.25, trajectory 0.86,
  outcomes 0.33) showed two more things the harness owed the agent. Its two
  `confluence.create_page` calls carried no `space` and were refused as "A
  page with this title already exists in the space", the connector's one
  validation text, so it spent five turns searching for a page that never
  existed. The emulator now names the missing field, and the tool catalogue
  lists `required_on_create` per entity on every create tool, so an agent
  can see what a create must carry. The second case died on a reply cut off
  inside a 7,833-character HTML body; the adapter now re-asks once with the
  refusal in front and a request for a short body, and a second refusal
  stands.
- With both cases grading, the plan axis read 0.0 on each and both branches
  of a conditional were expected, although the agent had created the page
  and read it back. The grammar attribution binds every node's arguments
  from the reference flow and demands equality: the fixture id inside the
  search predicate, the reference's own name and evidence fields on the
  create. An agent that is not the reference never reproduces those bytes,
  so nothing it did attributed. A call now attributes by shape when the
  strict pass finds nothing: the node's tool, its tool ancestors completed,
  its condition holding on what was observed, the entity the node names, and
  a target that resolves to the fixture or to a record a parent made. A read
  attributed by shape stands only if it read the node's record; a refused
  call stands only when the refusal is the node's designed failure. A record
  read through search instead of get is still read, and the receipt of a page
  is read as a page whichever node it landed on. The two recorded runs,
  replayed: 0.43 became 0.81 (plan 0.79, trajectory 0.98, outcomes 0.67)
  and 0.41 became 0.71 (plan 0.79, trajectory 0.69, outcomes 0.67). The
  execution-contract assertions still hold the reference's bytes, so an
  external agent's `passed` stays false on them; the axes are its measure.
- A live three-case run with attribution on graded two cases (0.74 and 0.67)
  and lost the third to a reply that opened "I made several errant tool
  calls that don't belong to this task" and then cut off inside its body.
  The child had no built-in tools but still had the operator's own MCP
  servers, ran in the repository and so loaded its project instructions,
  and answered in free text. The evalrun child now runs with
  `--strict-mcp-config`, from an empty directory, and with a structured
  reply, so it cannot call what the case did not serve, cannot read the
  project, and cannot answer in prose. The schema took two measured turns to
  get right: one that admitted any object had the harness write the call as
  JSON text inside `call`, and one with every reply key optional had it
  write the call inside `answer`; the API refuses a `oneOf` that would
  require one key. Each seam now states its own typed shape on the command
  line, the closing instruction says to fill a field rather than write JSON,
  and the adapter reads a reply stringified one level down as the object it
  meant. Three real turns in a row came back as a well-formed call.
- The sealed run graded three of three cases with no error row: 0.24, 0.67
  and 0.71 against a reference ceiling of 1.0, in 36 minutes for 60 calls.
  The 0.24 is a finding about the query, not the agent: it says "Create a
  new HTML in Confluence", the destination entity is `page`, and the agent
  created a blogpost, which graded as collateral with the page unwritten.
  The prompt renderer names the format and not the entity whenever the
  format is not `record`. Naming both would change every rendered query,
  so it is left as a stated gap rather than changed here.

### The corpus remembers what it was asked for (Generation)

- The section below this one made `build --inspired-by "a mid-size Singaporean
  hospital group"` print `unmet:` before it exported a retailer. The line
  reached the terminal once and nowhere else. The recipe recorded `archetype`,
  the shape that got built, and nothing said what was asked for. A corpus
  handed to someone else could not say it was a stand-in, and a downstream
  eval pipeline had no way to detect the substitution: `enterprise-evals plan`
  grounds queries in the world that exists, and every check it runs is a
  consistency check against that world.
- The recipe now carries two more keys. `inspired_by` is the description the
  build was asked for, from `--inspired-by` or from a specification's
  `industry`. `unmet` is the list of findings the build could not meet, in
  the words `unmet:` printed. Both paths write the same shape, so a
  substitution has one record whichever flag reached for it.
- Both keys are written only when something went unmet. A description the
  registry recognises built exactly what it named, and `archetype` already says
  so. A default build writes neither key and is byte-identical to the one built
  before this change. A corpus that does carry them changes `world.json` by
  design, which is why this section is marked Generation.
- `recipe.rebuild` carries the keys through, so `worldloom verify` still proves
  a substituted corpus is its own record. A world spec that cannot carry them
  gets them back on the recipe after the build, the way a locale does.
- `worldloom inspect` adds one row for such a corpus: `Built as
  omnichannel_retailer; asked for 'a mid-size Singaporean hospital group';
  unmet: 1`. The findings themselves stay on the recipe in `world.json`.
- Nothing about what gets built changed. Only what is recorded.

### A use case's capability and difficulty are read off its rows (Generation)

- Every use case `industry.use_cases` derived carried `evidence_reconciliation`
  at `medium`. The spec was assigned the first and left the second at its
  default, and the one branch that could vary keyed on `line.writes`, which
  is never zero because every activity type suits at least one write verb. A
  healthcare company's fifty-eight use cases had one capability and one
  difficulty while its rows spanned eight activity types and one to three
  evidence channels each.
- `industry.activity_capability` reads the activity type: a report is a
  `search`, a reconcile step is a `reconcile`, and everything else acts on
  evidence, which keeps the name `evidence_reconciliation`.
  `industry.activity_difficulty` reads two things the row declares: an
  exception path, and evidence in more than one channel. Both make the
  activity hard, one makes it medium, neither makes it easy. A line takes the
  most demanding of its activities, and `ProcessLine.capability` and
  `ProcessLine.difficulty` carry the result into the use case's `EvalSpec`.
  Nothing is drawn, hashed or rotated to spread the values.
- A uniform property stays uniform and is said. Every activity the shipped
  catalogue declares carries an exception path, so no shipped use case is
  easy. `IndustryProgramme.uniformity` carries one sentence per value the
  use cases cannot show, naming the row property that keeps it out with its
  count; `capabilities` and `difficulties` carry the counts, and
  `worldloom industry programme <industry> --describe` prints all three.
  Healthcare now spans three capabilities (3 search, 50 evidence, 5
  reconcile) and two difficulties (18 medium, 40 hard).
- The construction's closing step is named for the capability
  (`summarise`, `act`, `reconcile`), so a line whose only activity is a
  report is no longer asked to reconcile, and a search line summarises and
  extracts where every line used to reconcile and generate.
- `request_template` reads as a request the line's owner would make.
  `work admit to discharge for Billing (Corporate Services; SG)` is now
  `Move Bill and claim forward for Corporate Services in SG: find the
  evidence Admit to Discharge leaves in SAP S/4HANA, act on it, and send
  the result back to whoever asked.` Every noun is the rows' own: the
  activity names in catalogue order, the owning units, the countries, the
  stream and the systems of record. A line of more than three activities
  names its first and last and counts the rest.
- `industry.unlocalised` said four locales shipped and ten countries had
  none. Twelve ship, and the two countries without one are TH and VN. The
  docstring now says so, and why.
### A covering plan that stops when it is done

- `worldloom enterprise-evals plan` could not finish on any shipped profile.
  The default candidate space holds over two million rows. The pairwise cover
  walked every one of them, and `--limit` only cut the result afterwards, so
  `--limit 40` ran for fifteen minutes and wrote nothing. The limit now caps
  the walk itself. The rows are the prefix the unlimited walk would choose,
  in the same order, and the command returns in seconds. A run that completed
  before produces the same bytes: a narrowed profile that gave 312 rows still
  gives those 312 rows.
- The planner now knows the exact set of interactions the space requires. It
  derives the set from each lane's domains under the same admissibility
  predicate the candidate stream applies, so it enumerates no rows, and it
  refuses a row that falls outside the set. The walk stops at saturation, and
  `holes` lists the required interactions the selection misses.
- `CoverageReport` says when it is partial. `truncated` means a limit stopped
  the walk with candidates unexamined. `exact` means `required_interactions`
  and `holes` describe the whole space. The streaming report used to set
  `required_interactions` equal to `covered_interactions` whatever happened,
  which read as full coverage of a space it never finished walking.
  `complete` is now false for a selection that has not proved itself.
- `--shard-index` and `--shard-count` split the candidate stream before the
  cover, so shards run in parallel over their own slices. Before, every shard
  first walked the whole space and then kept every nth chosen row. A shard
  covers its slice, the union of the shards' selections covers the whole
  space, and a shard's holes are relative to the whole space. Sharded
  covering output changes as a result; exhaustive sharding is unchanged.
- The `plan` and `build` commands print `hole_count` and `hole_examples` in
  place of the full hole list. A truncated run on a shipped profile leaves
  some sixty thousand real holes, five megabytes on one line. The SDK's
  `CoverageReport.holes` keeps the full list.
- A planned queryset's bytes no longer depend on the operating system. The
  `plan` writer opened its file in text mode, so Windows wrote `\r\n` and the
  same 312 rows hashed to a different digest than on Linux. It now writes
  `\n` like every other byte-stable writer here.

### Every write operation has a prompt, and the back-office workflows post to chat

- `review()` accepts any operation an entity declares, but the prompt renderer
  phrased only the seven the builtin workflows use. A profile whose destination
  said `comment` passed the lint and raised `KeyError` at plan time, and
  `delete` was among the unphrased, which is the operation the DAG shapes exist
  to grade. `ACTION_INSTRUCTIONS` now covers all thirteen write operations and
  a test holds it level with the `Operation` enum.
- Phrasing every operation exposed two that the specs advertised and nothing
  served. `jira.issue` said `attach` and `link`, `confluence.page`, both
  ServiceNow entities and `email.message` said `attach`, and no connector
  definition has a tool for any of them: a profile selecting one passed the
  lint, rendered a prompt and refused at row compilation. The specs now
  advertise only what a definition serves, and a test holds every builtin
  spec to that.
- A `delete`, `move`, `comment` or `forward` addresses a record that has to
  exist, but only `update`, `patch`, `upsert` and `reply` asked the corpus for
  a destination fixture, so a row planning one of the others fell back to a
  source record id, which can belong to another connector. `RECORD_ADDRESSED`
  names the ten operations that need an existing target, and `plan_queries`
  marks each as `preexisting_record`. A delete or move reads its target
  before the write, the way the delete chain already did, because the
  trajectory law `destructive_without_read` holds the reference to the same
  rule it holds the agent to; and neither binds evidence fields, because
  their tools take only the record id. A profile whose destination deletes
  now plans, grounds, compiles and runs: 12 of 12 rows on a project-built
  world, every delete met. `move` is withdrawn from the specs for now: its
  tools need a parent folder the corpus does not materialise, so a planned
  move failed validation at the emulator. It returns with that fixture. No
  shipped workflow selects any of these operations, so every shipped plan is
  byte-identical.
- Wiring Slack and Microsoft Teams into the registry grew the row space by
  nothing, because no builtin workflow named them. Each back-office workflow
  now posts a notification to Slack or Teams beside its record, page, file or
  email, so a run reaches a chat destination as well as a document one.
- The prose gate skipped nothing under `.claude/worktrees/`. Five parallel
  agent worktrees there turned 0 findings into 70 without an edited file, all
  from their copies of pre-existing files. The gate now skips that prefix.

### A back-office scenario, and the shipped scenarios are tested

- The enterprise-evals planner shipped four workflows, and every one was
  shaped like a service desk: incidents, changes, customer accounts, an
  executive digest. The two industry profiles added banking and retail
  workflows over the same channels. Nothing closed a month, matched an
  invoice, onboarded a starter or renewed a contract, which is the work
  that stresses an agent differently from triage.
  `examples/enterprise-evals/back-office.json` adds four such workflows:
  `finance_month_end_close`, `procurement_exception_review`,
  `hr_onboarding_readiness` and `contract_renewal_review`. Each reads the
  `sor` connector beside the channels: journals, accounts, bank statements
  and consolidations for the close; purchase orders, goods receipts,
  invoice receipts and open items for the match; workers, positions and
  requisitions for onboarding; contracts and orders for the renewal. Two of
  them write back to `sor` (a case, a contract) as well as to a page, a
  file or an email.
- The four widen the axes rather than the name list. Together they use
  every topology, add `classify` and `transform` to the content actions the
  builtin workflows emit, add `csv` to the output formats, and set
  audiences a controller or a people partner would recognise. Their
  templates read as a request a manager types. Every `sor` entity they
  name is one a catalogue company binds records for: `employee` and
  `vendor_bill` are connector entities, but no industry's default company
  holds records of them, so a row over them would materialise evidence
  carrying no fact and be refused at validation.
- The profile needs a world built from a catalogue project (`worldloom
  industry project`, then a Studio snapshot), because only such a world
  carries `sor` records. On the golden retail corpus its `sor` rows refuse
  with the same finding that any shipped profile's rows meet on a world
  that lacks their records. The description notes that chat and post
  destinations can be added when those connectors land.
- Nothing loaded the shipped profiles before.
  `tests/test_enterprise_scenarios.py` loads every file in
  `examples/enterprise-evals/`, merges it onto the builtin registry, and
  asserts that `review()` finds nothing, that every named workflow exists
  and survives the connector selection, that every role names a connector
  and entity the merged registry carries, that every template uses only
  the planner's placeholders, and that every destination operation is one
  the planner can phrase. A `comment` destination passes `review()` and
  fails at plan time, so that last check is the one the loader could not
  make. Nothing builtin moved: every plan made without a profile is
  byte-identical.
### The planner knows every connector the emulator serves

- The connector definitions carried fourteen connectors. The enterprise-evals
  planner's registry carried eight, hand-written and never compared against
  them. A scenario profile naming `slack` or `teams` was refused as an unknown
  connector while the emulator stood ready to serve it, and the seventy-six
  tools of `onedrive`, `outlook`, `slack`, `teams`, `rovo` and
  `teamwork_graph` were out of the eval space's reach. `builtin_registry()`
  now carries a `ConnectorSpec` for all fourteen.
- Each new spec mirrors its definition entity for entity. Every operation on
  it is one the definition maps to a tool, so `patch` and `upsert`, which no
  definition carries, stay off the six; a workflow that asks for one is
  reported by `review()` rather than planned. A test holds the two catalogues
  to each other by name, entity and operation, so a definition added without a
  spec fails there and not in a user's profile.
- Maturity is not a gate. The repository has no rule that hides an `eap` or
  `product_surface` connector: the definitions expose `rovo` and
  `teamwork_graph` unconditionally and the binding carries their maturity
  through as data. The specs follow suit, and the four `ga` connectors and the
  two others are wired the same way.
- The request text now takes a connector's name from its spec's
  `display_name`. It used to go through a chain of `str.replace` calls that
  knew seven names, so any connector added later printed in lower case, and
  through `str.title()` for the destination, which printed ServiceNow as
  "Servicenow". The strings those two paths produced for the original eight
  are pinned by name, so every planned row that exists renders byte for byte
  as before, and a test proves it on a narrowed profile. A connector a profile
  authors itself now renders its `display_name` in the request text; its query
  ids do not move, because they are keyed on the row, not on the text.
- The shipped scenario profiles list their connectors explicitly and plan the
  same bytes. The default profile spans fourteen connectors but no built-in
  workflow names the new six, so its candidate space is unchanged: past the
  ten million ceiling before and after.
### A described company that could not be built says so

- `build --inspired-by "a mid-size Singaporean hospital group"` built Greyfell
  Retail Group, an omnichannel retailer in Wellington whose largest unit was
  Food, and reported `coherent: 5064 checks passed`. Nothing said a
  substitution had happened. The same description through `--spec` had always
  reported it as `unmet`; the build path resolved through the same fallback and
  never asked whether anything matched.
- `company.unmet_for_description` is now the one function that words it, and
  both callers use it, so the two cannot tell a reader different stories about
  the same substitution. It names the industry it did recognise, the shape that
  got built instead, and the command that does work: "no registered domain
  builds a 'healthcare' world, so the world is built with the
  'omnichannel_retailer' shape … `worldloom industry programme healthcare`
  derives its lines of business, processes, requests and counts".
- Falling back still beats raising, which is why the build still succeeds. What
  changed is that it is no longer quiet. A description the registry recognises
  reports nothing, because a notice on every build teaches the reader to skip
  the one that matters.
- No bytes moved. The resolved shape is what it always was, so every corpus
  built from a description is byte-identical to the one built before this.
- Still missing, and missing on both paths equally: neither the specification
  nor the description path *persists* the substitution into the corpus. A world
  handed to someone else still cannot say it was built as a stand-in.

### Eight locales, generated from published data (Generation)

- Four locales shipped and the catalogue built companies in fourteen
  countries, so an Indian telecom was given Australian names, Australian
  cities, an Australian calendar and Australian digit grammar while its records
  were denominated in rupees. `tools/ingest_locales.py` generates eight of the
  ten that were missing: China, Hong Kong, India, Indonesia, Japan, Malaysia,
  Singapore and Taiwan.
- Thailand and Vietnam are still gaps, and the tool records why for each. A
  deep name pool needs 500 given and 500 family names. No library publishes a
  romanised Vietnamese surname pool at all, Faker carries ten, and Faker's Thai
  surnames romanise to 314 distinct forms. Ten Vietnamese surnames is not even
  wrong, since they are extraordinarily concentrated, but it cannot meet a
  contract that draws one distinct surname per person. Padding either pool
  would be inventing names, so `locale_finding` keeps saying TH and VN have no
  locale.
- Nothing in them is invented, which is the point: ten hand-written name pools
  would have been ten fabrications. Regions are ISO 3166-2 subdivisions from
  pycountry, cities are ranked by population from geonamescache, names are
  romanised from names-dataset or Faker, the currency and the entire digit
  grammar are CLDR through babel, and holidays are the fixed-date entries the
  holidays package publishes.
- Romanised deliberately. Faker's Japanese, Chinese and Indian providers are in
  native script, and this project renders English-language business documents,
  where a group report listing two scripts is a mixed-script artefact rather
  than a more accurate corpus.
- names-dataset needed cleaning and the tool says so: its per-country first
  names are derived from profile data where field order varies, so Singapore's
  list opens with an abbreviation and four surnames. A candidate that also
  appears in the country's surname list is dropped, as is anything under three
  characters.
- **`Locale.grouping`**, and the reason it had to exist. India writes 12,34,567
  and not 1,234,567, and its filings are denominated in lakh and crore, so
  every rupee figure this tool printed was grouped the Western way. A single
  separator character can say comma or full stop but not group *size*. The
  value is read from the CLDR decimal pattern, `spell` honours it, and it
  defaults to thousands so every locale written before it stays byte-identical.
- Two tables are authored and neither is a name: statutory company forms and
  the month a financial year opens, because no library publishes either per
  jurisdiction. India and Japan open on 1 April; the rest default to the
  calendar year.
- The identifier surface follows. `tools/ingest_surface.py` adds the eight
  countries to `data/surface/rules.json`, with phone formats from
  libphonenumber's published national formats and the statutory registration
  number each country's invoices carry: an Indian company quotes a GSTIN and a
  Singaporean one a UEN, where both used to print `REG-########`. Hong Kong
  takes the PO box convention this repository already uses for the Gulf,
  because it numbers no addresses. No pre-existing country changed.
- Two defects the dispersed-replay gate found, and what each one broke. A
  locale must answer for every engine `domains.names()` registers, and the
  generated table stopped at banking and insurance, so every procurement build
  in the eight new jurisdictions raised at company-naming time. Procurement
  forms are now carried for all ten countries, and a test walks the engine
  registry rather than a written list.
- names-dataset mixes scripts, and three kanji surnames reached Japan's pool
  past a filter that only looked at length. Every generated pool is filtered to
  romanised forms and a test holds it, which is the property the whole tool was
  built on.
- A company form carrying punctuation is no longer read as an invented entity.
  The narration validator peels `.,;:()'"` off every token it extracts, so a
  company chartered `Greyfell Engineering Co., Ltd.` came out of prose as
  `Greyfell Engineering Co Ltd` and matched neither its own name nor any
  fragment of it. Every East Asian company form carries that punctuation, so
  every narration in those jurisdictions was rejected for naming the company it
  was about. The world's own names are stripped the same way before matching.

### Employment is measured, and every shape grounds (Generation)

- `worldloom.staffing` reads occupational employment by industry from the
  Bureau of Labor Statistics. `tools/ingest_bls_oes.py` joins three tables that
  were already here or one download away: OES employment for an SOC occupation
  inside a NAICS industry, the O*NET function crosswalk in `_data/functions`,
  and the process catalogue's NAICS map. All twelve shipped industries are
  carried, from 37,944 occupation-by-industry rows.
- The numbers discriminate where revenue share could not. 58% of a freight
  company's employment is warehousing, 32% of a consumer-products company's is
  production, and 15% of a software company's is engineering. A 20,000-person
  logistics company now puts 18,070 people in warehousing; the revenue-share
  proxy could not tell it from a software company.
- Every derived line carries `workforce_share`, and the programme names the
  release it was measured from. `staffing.allocate` turns a stated total into
  people across the families a company models, by largest remainder so the
  parts sum exactly. An industry the table does not carry gets a zero share and
  a finding that says so, never an even split.
- Longest NAICS prefix wins in the crosswalk. The catalogue carries both
  `NAICS 52` (banking) and `NAICS 5241` (insurance), and first-match order put
  every insurer in the bank.
- `establish` still splits a pack's units by revenue share and now says why:
  a pack's units are trading divisions, and no employment survey counts those.
- **Every DAG shape is planned by default.** `map_read` and `conditional` were
  opt-in because they raise a source's `minimum` to two while the materializer
  topped a source pool up to exactly one record, so rows under them
  materialized and then refused to compile. `materialize_corpus` now tops a
  pool up to the largest minimum any planned row asks of it. The first filler
  record keeps the key it has always had, so a corpus that only ever needed one
  is byte-identical.
- A predicate-filtered source, or a corpus built `strict_sources`, is still
  refused rather than filled: a filler record meets a count and not a claim,
  and the refusal names how many records are present and how many are needed.

### Procurement is a function, and the system says so

- The engine registry listed `procurement` beside `retail`, `banking` and
  `insurance` as though a company could be one. It builds an infrastructure
  services and contracting group, and procure-to-pay is the function its
  episode exercises inside that company. `Domain.industry` declares what an
  engine builds when its own key is not that, `domains.describes` reads it,
  and `worldloom pack targets` prints it. Nothing is renamed: the key is a
  registry key and a corpus identifier, and renaming it would change bytes
  everywhere for a word.
- `industry.function_of` and `industry.stream_of` recognise the words a
  function family and a value stream are asked for in, both built from the
  catalogue rather than authored. `industry.function_finding` turns either
  into one sentence: what was named, that a company has it rather than is it,
  and the `industry.project(...)` call that gets the asker what they wanted.
- A company description that names a function now says so. It read "nothing
  recognised it", which was true and useless: the asker named a real thing in
  the wrong slot, and the twelve shipped industries all carry a procurement
  function already.
- A value stream gets its own sentence, because it is not one function either:
  the catalogue runs `procure_to_pay` across four function families and
  `order_to_cash` across nine, so folding either into one would contradict the
  activity ownership the catalogue ships.

### The stated workforce is allocated, not just stated (Generation)

- A company stated one headcount and nothing spent it. A 400-person and a
  20,000-person retailer carried the same three units and the same two dozen
  named people, so no document could say how big a division was.
  `BusinessUnit.headcount` now carries each unit's part of that total, and
  `generators.org_builder.establish` allocates it: the whole stated number, by
  each unit's declared share of group revenue, by largest remainder so the
  parts sum to it exactly. A 400-person retailer establishes 256/84/60; the
  20,000-person one establishes 12,800/4,200/3,000.
- Revenue share is a proxy for staffing, not a measurement, and it is the only
  per-unit weight a pack declares. It is deliberately not derived from the
  named roster: a pack names the decision-making graph, which is top-heavy by
  construction, so the roster's own proportions would put half a retailer in
  group functions.
- Two validator rules. `establishment_exceeds_headcount` when the units
  establish more people than the company states, and
  `named_roster_exceeds_establishment` when a unit holds more named employees
  than it establishes.
- The world summary names the largest unit and its share of the workforce.
- `headcount` is optional and defaults to `None`, which reads "the world does
  not say". `examples/retail-close` is hand-authored and keeps saying nothing.

### A default build plans a delete (Generation)

- `enterprise-evals plan`, `build` and `qualify` with no `--dag-shape` planned
  the single-write trajectory the grammar produced before shapes existed. Every
  case set they made reported `deletes: 0`, so none of them could grade a
  delete at all. They now plan every shape a row can ground on the sources it
  already declares, `delete_chain` among them. 120 cases from `retail-close`
  grade 11 deletes where they graded none.
- `enterprise_dag.default_shapes()` derives that set from the catalogue rather
  than listing it. `map_read` and `conditional` raise a source's `minimum`
  above what the row asked for, so they stay opt-in: a world holding one record
  where the row wanted one plans a case that materializes and then refuses.
- `enterprise_dag.resolve_shapes()` is the one spelling all three commands use.
  `--dag-shape none` plans the old single-write trajectory, `*` is the whole
  catalogue, and omitting it is the default set.
- A row that outruns the corpus now says so. The refusal read "insufficient
  bound source records"; it names the connector, the entity, how many records
  bound and how many the row needs.

### A container, a checked package, and an honest install line

- A `Dockerfile` builds the wheel and installs it, so the image runs what a
  wheel install gives anyone rather than a source tree. It runs as uid 10001,
  writes only to the `/workspace` volume, and carries the four renderers and
  the MCP server. CI builds it on every push, opens the console on a published
  loopback port, renders DOCX, XLSX, PDF and PPTX inside it, and checks the
  process is not root.
- `worldloom studio serve --host` picks the bind address; it stays 127.0.0.1
  unless you name another. A non-loopback bind prints what it gives away: the
  console has no authentication, so anyone who reaches the port can read the
  company and start jobs.
- The console's origin guard now reads the host *name* and ignores the port.
  Pinning the port rejected every container whose published port differed from
  the port inside it, and bought nothing: a page on another origin picks its
  own port freely, so the loopback name is the whole defence against DNS
  rebinding.
- `twine check --strict` runs on the built sdist and wheel in CI and in the
  release, before anything is uploaded. A README PyPI cannot render is rejected
  at upload, after the version number is spent.
- The release workflow takes a concurrency group that does not cancel: a run
  that has already uploaded cannot be replayed under the same version.
- The README says what actually installs today. Nothing is on PyPI, so the
  three paths are a checkout, a wheel you build, and the container; the PyPI
  line says plainly that no tag has been pushed.

### An installed coding harness is one flag

- `worldloom evalrun run --harness codex|claude`, `evalrun plan --harness` and
  `narrate loop --harness` drive an installed coding harness through the
  adapter this package already shipped for the Studio, using that harness's
  own login. Grading a real agent against the reference ceiling, and getting
  prose accepted, no longer needs an adapter script. `studio.harness.adapter_command`
  is the one spelling all four commands use, quoting for the platform the
  child is split on.
- The adapter now tells the child which seam it is answering
  (`studio.harness.role_for`). It sent authoring prose to every child, so an
  evalrun turn told the agent under test it was completing an authoring
  request; a turn, a plan, a rating and a narration request each get their
  own role, and every one of them still ends in "return exactly one JSON
  object". A native trial that opts in to workspace writes now refuses a seam
  with no write instruction to grant rather than silently dropping the opt-in.
- `narrate loop` takes `--exec` or `--harness` and refuses with both or
  neither, naming the offline round trip in the refusal.

### A country with no locale says so

- `industry.unlocalised` and `industry.locale_finding` name the countries no
  shipped locale answers for and what the company loses to the one it is
  built in: its names, cities, calendar, figure grammar and currency. Ten of
  the twelve countries the shipped industries operate in are among them.
  The programme carries the sentence in `findings`, and the Studio console
  shows it as an acknowledged limit beside the missing engine, which does not
  withhold readiness. The sentence names the currency the catalogue declares
  for those countries, because connector records carry it per country while
  rendered documents carry the locale's.

### Honest counts, and a support unit that earns no revenue (Generation)

- **A programme reports what it grounds, not how it can be phrased.**
  `IndustryProgramme.distinct_answers` and `ProcessLine.distinct_answers`
  count the distinct ground truths a company's requests rest on;
  `industry.lines` fills them when passed the requests. A verb and a channel
  change a request's wording and leave its answer alone, so `situations`
  counts phrasings over these: the twelve shipped industries offer 189,346
  situations resting on 29,505 distinct answers, and a telecom's 5,550 rest
  on 903. `worldloom industry list` prints both.
- **Generation.** A derived Studio use case now asks for the line's distinct
  answers rather than its situations, so a catalogue project stops requesting
  six queries for every answer it can ground. A telecom's billing project
  requests 57 queries where it requested 282.
- **Generation.** `industry.divisions` returns the revenue units alone.
  A shared service centre and a group function sell nothing, so they no
  longer take an equal cut of the company's revenue; they are formed as
  business units by `ownership.materialize_owners`, which allocates none,
  and the Studio snapshot forms them before it declares the structure. A
  telecom's revenue is its two customer segments, not four units at a
  quarter each, and no per-unit commercial or finance post is minted inside
  a unit that sells nothing. `divisions` takes the compiled catalogue to
  weight each division by the bindings it owns.

### The console in the README

- `README.md` gains a Studio console section with four pages of the console
  (overview, company and processes, use cases, evaluations), and
  `docs/studio.md` a gallery of all eight, captured from the connected retail
  pilot and a catalogue-derived telecom company under `docs/images/studio/`.
- The console's overview subtitle and the "Generation boundaries" panel no
  longer print a blank engine for a company no engine builds; the panel
  says the world is derived from the process catalogue.

### The programme's record requests run as evalrun cases

- Every record request of a programme is an `evalrun` case
  (`Programme.evalrun_cases`, `industry.evalrun_cases`, `industry.evalrun_row`):
  its plan searches the `sor` connector per record kind the binding holds
  in the request's period, its outcome is the records the search must
  return (`reads_contain`) and the answer read off them under the request's
  own rubric, and its dimensions carry line, stream, intent, channel and
  activity type. `industry export` writes them as `evalrun-cases.jsonl`
  beside `records.jsonl`; `worldloom evalrun run` and `EvalSession.from_export`
  take such a case set in place of an enterprise corpus
  (`evalrun.contract.read_case_set`, `is_case_set`). The reference agent
  states a row's `expected_answer` when the row carries one, so its run is
  the ceiling on the answer axis too; rows without one are unchanged. A
  telecom's 2,927 record requests are 2,927 cases, and the reference run
  passes every one the grounded rater can grade. The Studio's `evalrun`
  job takes `evalrun_source` (`dataset`, the default; `programme`; `both`):
  a project with a process structure grades the programme's record requests
  for the lines it seats, grouped under the line's use case, over the
  company's own records, with or without the dataset's cases
  (`worldloom studio evalrun --source`).

### The commercial seats take the company's revenue function

- A project of an industry no engine builds rides the retail shape with
  the shape's commercial seats (`merch_lead`, `merch_analyst`, the per-unit
  `_buyer` post) retitled and refunctioned from the company's revenue
  function: the operating function, in APQC's sense, that the industry's
  own value streams bind most in its revenue units
  (`industry.revenue_function`), titled from the function
  table (`industry.role_table`, passed to the world as the pack's roles). A
  telecom seats a Customer Service Director, a logistics company Fulfilment.
  A per-unit post may name the unit kinds it is minted for
  (`roles.UnitRole.kinds`, `PackUnitRole.kinds`; empty mints it everywhere,
  as every engine's own posts do), and the commercial post is minted in the
  revenue units only. `sdk.Blueprint.role_table` takes a pack's authored table over the
  engine's shipped one when lines of business attach, which a pack that
  authored its organisation lost before. Generation: worlds of catalogue
  projects for engine-less industries change titles and functions on those
  seats; retail, banking and insurance worlds are unchanged.

### The interview describes the company, the catalogue derives the rest

- `industry.project` takes a `CompanySpec` in place of an industry name:
  the company as an interview settles it (units, countries, operating
  model, landscape) yields its divisions, LOBs and use cases the way the
  industry's default company did. `industry.rederive` does the same for an
  existing project, keeping its seed, episodes and plans and the families
  it seats where the new company still supports them. An interview reply
  sets `derive` to ask for it, and the Studio derives before recording the
  revision (the reply must carry a structure). `worldloom industry project`
  writes a project from an industry or a company spec for `studio init`.
  The locale follows the company's first country that has one
  (`industry.geo_for`), `australia` otherwise. The catalogue's
  `process.<stream>` fact kinds are registered the first time any process
  consults the fact-kind registry (`factkinds.process_kinds`), so a project
  written by `worldloom industry project` lints the same under `studio
  init` in a process that never imported `worldloom.industry`.

### A catalogue project compiles and grades end to end

- A Studio project derived from the catalogue (`industry.project`) now
  builds a world of its own company and compiles its dataset. The world's
  business units are the company's declared units (`industry.divisions`:
  one pack unit per declared unit, named as declared, its kind the unit's
  archetype), so a process fact can be about the unit that owns the work.
  The process company rides the snapshot world's recipe under
  `process_structure` (`recipe.apply_process_structure`, recorded as the
  recipe step `ApplyProcessStructure` so a rebuild replays it in its
  place). The company's systems of record are the products its bindings
  name (`sor.products_for_world`): one system each, owned by the leader of
  the unit that owns most of its bindings, holding the record kinds the
  catalogue gives it (a telecom gains nineteen, SAP S/4HANA and Amdocs
  among them). The company is declared as one event
  (`organisation.process_structure`, the chief executive its actor, the
  units and the new systems its subjects, dated where the company's facts
  begin) and stated in the ledger: the programme's facts join the world
  subjected to its units, sourced on its systems and caused by that event
  (`sor.facts_for_world`), so a record that cites them cites facts the
  world holds. From the recipe the builtin projections derive the
  company's records on `sor` (`connector_data.generate_sor`) and its channel
  evidence on the emulated channels (`sor.channel_records`: one email
  thread, Jira issue, SharePoint file or Confluence page per bound activity,
  declared channel and period, scoped to the line's LOB, stream and owning
  unit, naming the period's records and the one that tripped the
  exception). A use case declares one hard requirement and one read step
  per source entity, a selector scoped to a value stream covers the use
  case's activities, and support ownership forms nothing for a world built
  from the structure it is given, so construction checks the line's
  evidence against the world and finds it. A world built without a process
  company projects nothing new, so every existing corpus is unchanged.
  Materialising a corpus memoises the connector entity alias check, which
  was parsing a connector definition once per record. Generation: worlds
  and datasets of catalogue projects change (units, the declaration event,
  the process facts, `sor` records and channel evidence).

### Requests read their answers off the records

- A programme now derives the company's system-of-record records
  (`sor.records`, six periods ending at `sor.ANCHOR_PERIOD`, three records
  per binding, kind and period) and every request whose intent rests on a
  record set (`evidence_kinds` names `record_set`: find the exception,
  triage a queue, chase, reconcile, respond to a query and the others) is
  asked about the binding's records in the latest period and answered from
  them (`sor.answer`): the purchase orders among March's that tripped the
  price check, the open items to chase and their owner, the statuses of the
  rest. `Request.expected_record_ids` names the records the answer cites and
  `Request.period` the period; the earlier periods stay in the records as
  the distractors a real system holds. A request whose intent rests on the
  declaration alone still answers with it. One request per situation, as
  before, so the counts are unchanged; a telecom's 5,550 requests now have
  903 distinct answers rather than 203. `IndustryProgramme` reports
  `records`, `record_requests`, `period` and `periods`; `industry export`
  writes `records.jsonl`. Generation: every programme's requests and cases
  change where the intent reads records.

### Every system the catalogue names has records

- `_data/connectors/sor.json`, one system-of-record connector standing in
  for every product the catalogue names and no emulator of its own covers
  (61 of 67 products: SAP S/4HANA, Workday, Temenos T24, Guidewire, Epic,
  Amdocs and the rest). Its 73 entities are the catalogue's record kinds,
  each with a workflow (a purchase order is created, approved, sent,
  received, invoiced, closed), searchable on the fields a binding gives a
  record, created under an idempotency key on the activity, period and
  owner. `tools/build_sor_connector.py` builds it and
  `emulated-systems@2.json` from the catalogue; only the workflow table is
  authored, and the tests check the shipped files against a rebuild.
- `worldloom.sor` derives the records: one per bound activity, record kind
  and period, id in the product's own pattern (SAP's `45{8d}`), status from
  the kind's workflow, an amount in the country's currency where the kind
  carries money, the binding's exception on one record in four, every
  record linked to the programme's facts about its binding. No draw and no
  clock: the record is a function of the binding, the kind and the period.
- The programme reports every line of every industry as supported; what
  stays unemulated is the three channels with no emulator (chat, workflow
  approval, portal filing). A Studio dataset built from a catalogue project
  serves the records through `FrozenCompanyBuilder(projections=...)`, so a
  request about a March invoice in SAP has March invoices in SAP to be asked
  over. Generation: datasets of catalogue projects gain `sor` records; the
  emulator mints ids for any `{Nd}` pattern.

### A project seats every line of business

- `industry.project` seats every family with a supported process line, not
  the four largest: a bank is twenty-five lines and over a hundred people.
  The cap was the composed pack's name pool, cut to the organisation the
  description mints before any line attached; `sdk.Blueprint.lob` now
  re-cuts the pools from the locale to the people the lines add (identical
  draws while the count fits the base pool, the extended pool past it) and
  leaves a pool an author wrote alone for `packs.lint` to report. A
  blueprint with attached lines and no shape takes the engine's own role
  table, so a line attached to a bank joins the bank's organisation instead
  of displacing it with retail's. Generation: every derived Studio project
  and interview request carries every line and its people.

### Job titles from O*NET on every derived line of business

- The function table carries one job title per tier (head, manager,
  professional, support), chosen from the titles O*NET holds for the
  function's seats by a rule the file states: the shortest title carrying
  the tier's word and one of the function's keywords, reported titles before
  alternate ones, a derived title marked `source: derived` where no seat has
  one (17 of 148). `worldloom.functions.Title` reads them.
- `industry.derive_lobs` titles each line of business from the table (a
  Billing Supervisor and a Billing Clerk, not a "Billing Manager" and a
  "Billing Analyst" typed from the family name) and seats a fourth role,
  `<family>_support`, where the function has a support title. Generation:
  every derived programme, Studio project and interview request carries the
  new titles and the support seats; the seat that asks about an activity
  (`SEAT_BY_TYPE`) is unchanged, so request counts are unchanged.

### The catalogue keyed by PCF id, and the parity apparatus retired

- Every activity in the process catalogue now carries the stable APQC
  `pcf_id` of the process it belongs to, in place of a hand-typed hierarchy
  hint (`3.4.1`, `5.x`). Universal streams resolve in the cross-industry
  framework; each industry overlay names its own (`pcf_framework`: banking,
  property and casualty insurance, retail, utilities, healthcare provider,
  city government), and overlays for industries APQC publishes no framework
  for resolve in the cross-industry one. A compiled binding carries the
  resolved `pcf_hierarchy_id`, `pcf_name` and `pcf_framework`; an id its
  framework does not have refuses the compile by activity name.
  `tools/check_catalogue_pcf.py` prints the join, with the function that owns
  each process beside the function the row names.
- The second compiler (`worldloom.process_planning`), the source-reference
  importer (`worldloom.process_catalogue`), the archived upload they replayed
  against (`_data/processes/`, `defaults.zip`, `coverage.csv`, the parity
  fingerprints in `bindings-provenance.json`) and their tools, tests and
  workflow are gone. The catalogue is versioned data checked against the
  shipped frameworks, not a mirror of an upload.
  `process.open_from_catalogue` takes a `CompiledCatalogue` and carries the
  stream's bindings through `authoring_brief`.
- Generation: the activity bindings that feed the industry programme and the
  `process_catalogue` connector records carry the four PCF fields and no
  `apqc` or `pcf_status`; the default corpora do not read them and are
  unchanged.

### Reference data: the PCF, O*NET and the function table

- The APQC Process Classification Framework ships as data: the cross-industry
  framework 7.4 and seventeen industry frameworks under `_data/pcf/`, each
  element with APQC's stable `pcf_id`, its hierarchy index, description and
  benchmarking metrics, and each file carrying the notice APQC's licence
  requires. `worldloom.pcf` reads them; `tools/ingest_apqc.py` writes them
  from the workbooks and refuses one without a notice.
- The O*NET 31.0 database ships as data under `_data/onet/`: 1,016
  occupations with descriptions, job zones, the titles incumbents report,
  task statements mapped to detailed work activities, and the software each
  occupation uses. `worldloom.onet` reads it; `tools/ingest_onet.py` writes
  it with the CC BY 4.0 credit line.
- `worldloom.functions` is the crosswalk between the two: every level-3
  process of the cross-industry PCF assigned to exactly one of 42 business
  functions, each function seated with O*NET occupations in manager,
  professional and support tiers and bound to the catalogue's system-of-record
  classes. `tools/build_functions.py` builds it from three authored tables
  and resolves every id and name against the shipped sources; the tests do
  the same against the shipped file. See `docs/reference-data.md`.

### Industry X, and the whole evaluation programme it implies

- `worldloom industry programme INDUSTRY OUT` (`worldloom.industry`) derives
  everything an interview used to leave to be typed: a line of business per
  function family the operating model owns (a head, a manager and an analyst
  answerable for the family's value streams as `process.<stream>` kinds,
  registered from the catalogue's own stream list), a seated request per
  situation (the seat chosen by activity type, `SEAT_BY_TYPE`, so every asker
  has standing under the same rule `evals.plausibility` applies and
  `standing_findings` proves it), a fact per declared attribute of every bound
  activity (owner, system of record, control, exception) that the request's
  expected answer names and `Request.to_case` cites, and a `ProcessLine` per
  LOB × stream carrying the derived count. `use_cases` turns each supported
  line into a Studio `UseCase` whose `count` is the line's situations rather
  than an authored twelve, with sources from the connectors that emulate the
  line's systems and channels and a construction `EvalSpec` bound to the line.
  Twelve industries, 189,346 requests, each counted where it belongs;
  `worldloom industry list` prints the table.
- `_data/process-catalogue/emulated-systems@1.json` says which systems of
  record and evidence channels a connector emulator stands in for. A product
  it does not list is reported on the line and the programme as unemulated and
  its bindings draw evidence from the declared channels only; a line with no
  emulated source is listed under `unsupported_lines` with its count intact.
  `IndustryProgramme.engine` is empty for the nine industries no engine
  builds, and the programme says so rather than dressing a retail world as a
  telecom.
- `evals.coverage.report` accepts anything carrying the request tuple
  (`coverage.Requested`), so a programme is measured before any case enters a
  world with the code that measures the world afterwards. A full programme
  uses every situation the catalogue offers.
- `industry.project(industry, name)` is a Studio `ProjectSpec` derived from
  the programme, and the Studio preset accepts any industry the catalogue
  knows: the four largest lines of business as LOBs (rooted at the chief
  executive, `industry.ROOT`, so they lint clean and ride the world), every
  supported process line of theirs as a use case with the line's count, the
  company's limitations acknowledged. The interview request carries the
  programme's headline numbers under `programme` and its instructions say a
  count is derived from a process line, never written as a round number.
- `archetypes.matched` reports whether a description named a registered shape
  at all, and `company.resolve` reads it: a retailer is recognised without the
  caveat every retail description used to carry; an industry the catalogue
  knows but no engine builds (`industry.industry_of`: overlay keys, crosswalk
  codes, sector frameworks and a declared word table, longest phrase at word
  boundaries) is reported as exactly that, naming `worldloom industry
  programme <industry>` as what does exist; an unrecognised business is
  reported as a miss.

### Eval execution: a question is a turn

- Every request in the shipped corpora was complete and safe to act on as
  written, and the turn protocol had two replies, a call or an answer. An
  agent that should stop and ask (the request is ambiguous, a parameter is
  missing, a delete needs the user's word) had no way to, and no grade for
  it. `QuestionPoint` is to clarification what `FailurePoint` is to a
  designed error: a row declares the questions its request requires
  (`question_required`: the reason, the tokens the question must mention,
  the user's reply, the nodes that may not run first; `confirm_before` on a
  delete derives one per destructive write), `ToolSurface.ask` records what
  the agent asked and where (the `ask` reply of the `worldloom.evalrun-turn/v2`
  document, the `eval_ask` tool over MCP, an `["ask", {...}]` entry in a
  responses document), the service answers from the row and never says
  whether the question was expected, and the trajectory grade counts the
  points honoured under four laws named once in `QUESTION_LAWS`:
  `acted_without_asking`, `asked_too_late`, `ignored_the_answer`,
  `asked_without_need`. One more score term beside the designed failures,
  absent when a case requires no question and none is asked, so every
  existing ledger scores as it did. The reference agent asks what the row
  requires; the questions ride the ledger (`CaseResult.questions`) and the
  summary; `axis_coverage` reports `questions_expected` and the reasons.

### Hero use cases: organise my drive, my inbox, my chats

- `worldloom enterprise-evals housekeeping WORLD OUT --kind drive|inbox|chats
  --connector ... --records N --mess --stale --duplicates` builds a corpus
  that needs tidying and the cases that grade the tidying
  (`worldloom.housekeeping`). The corpus is in the world's own words: a
  folder tree per business unit and period (Drive, SharePoint, OneDrive), a
  mailbox with subject-tagged categories and mail folders (email, Outlook),
  or a channel list per unit (Slack, Teams), with a stated share of items
  misfiled, mislabelled, stale or duplicated. Nothing on a record says where
  it should be; the rule is in the request and the ground truth in the row.
  Each case is one rule, one group of records that share a destination: a
  search bound to the rule's own predicate, a mapped write per record (a
  move, an update, an archive, a delete) and a mapped readback, in the
  executable DAG grammar and compiled through `compile_dag_row` like every
  other row. The reference agent passes every case on every connector, and
  the count is the point: a corpus of five thousand items is one flag away.
- Scoring a reorganisation. A mapped write over a pinned search now carries
  a `per_record_state` assertion (or a `deleted` one listing its records),
  graded in `grade_trace` by fid, and `evalrun`'s outcome grade holds the
  same list on `StructuredOutcome.records`: the match is the fraction of
  records that landed (`OutcomeMatch.ratio`), so three hundred files with
  one left behind score 0.997 on that expectation rather than 0.
- `SourceRequirement.bind = "predicate"` compiles a search to the
  requirement's own predicate instead of the fixture's `id IN [...]`, so an
  agent that reads the rule can search by it; the reads it must return are
  still exactly the fixture's, and the cap on a bound search rises from
  100 to the grammar's 1000, paged at the tool's page size. Off the wire
  when unset, so every existing row compiles byte for byte.
- The emulator's search under an alias entity (`file` over docx, xlsx, ...)
  matched nothing when it carried a `where` predicate, because the
  predicate kept the alias name and every member record failed the entity
  test. The pool already holds exactly the alias's members, so the
  predicate now drops the alias. The served surface's per-run call limit
  rises to 4096 so a mapped reorganisation of a thousand records fits.

### Connectors: a record can be moved, and mail and chat can be tidied

- Every file connector declared its `move_file`/`move_item` tool as an
  `update` on the folder entity alone, so `tool_for("docx", "move")` had
  nothing to answer and no hero use case (organise my drive, my inbox, my
  chats) could be planned, executed or graded as what it is. `move` is now
  a connector operation of its own (`connector_definition.ConnectorOperation`,
  the DAG grammar's write vocabulary, `enterprise_specs.Operation.MOVE`):
  Drive, SharePoint and OneDrive move files and folders between folders
  with `{id, parent}`, Outlook moves messages between mail folders
  (`move_message`) and creates folders (`create_folder`), the native email
  connector updates a message's labels and read state (`update_message`),
  and Slack creates and archives channels (`create_conversation`,
  `archive_conversation`) through the workflow its definition always
  declared. The emulator's `_op_move` re-parents the record it leaves
  intact and refuses a destination that is not a container (validation)
  or does not exist (not found). `evalrun` grades a move as an update
  outcome on the record's `parent`, and `safety` classifies it as a
  reversible, naturally idempotent mutation, never destructive.

### Packs: the organisation as pack data

- The rung of the de-hardcoding ladder left open the longest. `voices`
  proved that an engine can publish its role keys and lint against them,
  and the role table itself stayed a literal in each engine's organisation
  generator: a pack could re-voice the CFO and could not give the company a
  chief risk officer. `Pack.roles` now carries the whole table (`table`,
  in `lob.RoleSpec`'s `reports_to` spelling, a `voice` attachable on the
  row) and the posts minted per business unit (`unit_roles`), both off the
  wire when unset. The table is reviewed on the way into every builder
  (`packs.role_table_of`: `roles.review` with stand-ins for the per-unit
  posts, refused rather than warned about because a missing spine key is a
  `KeyError` mid-episode) and reaches the build as the builder's
  `role_table`; the posts reach it as a new `unit_roles` field on all four
  builders, which the banking, insurance and procurement generators now
  accept beside retail's, and the recipe records beside the table. `pack
  check` names every review rejection, a post set missing an engine
  suffix, a post the table already declares, a role voiced twice, and a
  LOB role the table does not contain; the voices, name-pool and episode
  author-role lints read the company's own keys. `worldloom pack targets
  --json` prints each engine's organisation as data (`roles.published`):
  the spine a table must keep, the shipped rows and posts to start from.
  `pack export` writes a derived role table and estate into the pack
  instead of a sidecar. Every baseline build is byte-identical.

### Procurement: an estate of its own (Generation)

- `ProcureToPayWorld` refused `--estate` outright, and three modules carried
  the sentence "`landscape.LANDSCAPES` is a closed core table with no
  registration seam" for as long as `landscape.register` has existed. The
  contractor's vocabulary is now `landscape.PROCUREMENT`, the fourth shipped
  landscape (`worldloom pack landscapes`): sourcing, orders, site receipting,
  the three-way match and the accrual it books, gated on the
  site-connectivity gateway and identity. A purchase-to-pay corpus built
  with `--estate` grows a technology graph around the five systems the
  cycle mints, owned by the people who own those systems; built without
  one it is byte-identical. The pack's `estate` and `landscape` reach this
  engine too, and `evolve` no longer refuses an estate on a contractor.
- **Generation**: the procurement mosaic (`worldloom mosaic --engine
  procurement`) regains the estate axis it dropped while the builder
  refused estates, so its variants carry one more coordinate; a
  procurement mosaic dealt before this does not replay. Every other build
  is unchanged.

### Packs: the estate's vocabulary as pack data

- `landscape.named`'s error message promised that "a pack may also supply
  pools of its own" for as long as the module existed, and no pack field
  read it; the SDK's `estate(vocabulary=)` was carried and applied nowhere.
  A pack now states `estate` (the size) and `landscape` (a registered
  vocabulary by name, or pools of its own: services per layer, systems of
  record, purposes and size profiles), both left off the wire when unset so
  every pack corpus already built embeds the exact document it did. The
  retail, banking and insurance builders carry one `landscape` field,
  resolved through `landscape.resolve` with the engine's own vocabulary as
  the default; `Blueprint.estate(vocabulary=)` reaches it; and the recipe
  records the vocabulary beside the size (`landscape`, a name or the pools
  themselves, `landscape.document_of`) so the estate rebuilds in the same
  words from the corpus alone. `pack check` names an unknown vocabulary, a
  size the vocabulary lacks, and an estate asked of an engine that grows
  none. A typed `--estate` wins over the pack's size. Every baseline build
  is byte-identical.

### Fact kinds: the engines' vocabularies as versioned data

- Retail, banking, insurance and procurement each registered their fact
  kinds as a Python literal: 115 declarations across four modules, the
  vocabulary every pack's `fact_kinds`, every LOB responsibility and every
  sheet column has to match. Each vertical's kinds now live in
  `_data/factkinds/<engine>@1.json` (`domain`, `about`, and one row per
  kind), read at import by `factkinds.register_catalogue`; the version is
  in the file name because a registry is a lineage component. A row naming
  a field the kind does not have is refused rather than ignored. The
  arguments that stood as comments beside the literals (why a diagonal is
  `never-superseded`, why `financial.accrual.grni` is procurement's)
  travel as `note` fields and as each file's `about`. The registry's
  content and order are identical to what the literals produced, and every
  baseline build is byte-identical.

### Documents: the engines' catalogues as versioned data

- Banking, insurance and procurement registered their artifact types as
  Python literals (`register_artifact_types` with standing, lag and outline
  tables) while retail's thirty had long been proven expressible as
  `doctypes` JSON. Each catalogue now lives in
  `_data/artifact-types/<engine>@1.json`, read at import by
  `doctypes.register_engine` with the compilers passed in beside it; the
  version is in the file name because a catalogue is a lineage component.
  The argument that stood as comments beside each literal (why a section is
  optional, why a type stands where it does) travels as `note` fields on
  `SectionSpec` and `DocumentType`, left off the wire when empty. Narrated
  banking, insurance and procurement builds are byte-identical.

### Documents: chapter furniture past eight sections

- A document with more than eight visible sections (`render.chaptered`,
  the same threshold that frames its writers) renders with chapters: Word
  and PDF open every section on its own page, Word's running head carries
  the current section as a `STYLEREF` field beside the title, the hidden
  sections gather under one `Appendix` heading on their own page, and the
  Markdown twin opens with a linked contents list and the same `Appendix`
  heading. The threshold sits above every outline the engines ship, so
  every existing document renders byte for byte.

### Documents: sections that repeat over units, and framed long documents

- A section plan may declare `repeat: "unit"` (`doctypes.SectionSpec`,
  `documents.SectionPlan`): one authored step becomes a section per
  business unit with facts for it, each handed only that unit's facts (the
  unit, its categories, its sites), each with `{{var:unit.name}}` resolved
  in its heading and purpose, and each its own narration request under the
  same per-section validator. A long document now grows from facts rather
  than from a longer brief. Unset, the field stays off the wire.
- Once a document has more than eight visible sections, every section's
  narration request carries the outline as standing context: the sections
  in order, and where this one sits between its neighbours, with the
  instruction to refer to another section by heading rather than restate
  it. Built from the compiled outline, not asked of a model, so no ledger
  gains a call site; the threshold sits above every outline the engines
  ship, so every existing request digest and ledger is unchanged.

### Documents: decks for any document type

- The deck renderer handled one artifact type, pinned its size class to
  `small` and its grammar to the executive summary's, so no pack could ship
  a board pack and no deck could exceed four content slides. `render.pptx`
  now composes under the intent's own type, size and budget, and a document
  type declares `deck: true` to be rendered as one (`doctypes.install`
  registers it, `registries.scoped` restores the set, `describe` reads it
  back, and the core port marks the executive summary). A deck opens with an
  agenda once it has more than six visible sections; prose that outgrows one
  slide continues onto the next at paragraph or sentence boundaries, as a
  long table already did. Every deck an old size class could hold renders
  byte for byte: the agenda threshold is strictly above the shipped
  summaries and no section they carry exceeds one slide's estimate.

### Documents: declared size budgets

- The component cap `compiler.compose` enforced per size class and the word
  brief `narrative.compiler` gave each section's writer were two literal
  tables two modules apart, with no flag, no pack field and no fourth entry;
  the longest document a corpus could carry was twelve sections of three
  hundred words. Both now read one table, `sizing.PRESETS`, which holds the
  old numbers verbatim (so every default build composes and narrates exactly
  as before) and adds `xlong` (40 components, a 420-word brief) for a report
  with chapters.
- A document type may declare its budget outright: `filing.budget` on an
  authored type and `budget` on an episode artifact take
  `{"components", "words"}` and win over the size word. The planner copies it
  onto `ArtifactIntent.budget`, so a process that only loads the corpus
  narrates and renders to it without the pack that declared it; the plan
  handshake attaches the intent's budget to every accepted plan. An unset
  budget is left off the wire of the intent, the plan and the doctype, so
  every corpus, ledger and port built before this serialises byte for byte.
- `doctypes.lint` refuses a budget smaller than the outline's required
  sections, naming the `over_budget` refusal the composer would otherwise
  raise on every document of the type.

### Generation: planned deletes in the DAG grammar

- Add the `delete_chain` shape to `enterprise-dag@1`: write, read back,
  delete that exact returned record, read it back expecting `not_found`. The
  compiled row carries a `deleted` assertion naming the write that created
  the record and a `failure_at` expecting the error on the final readback,
  so the record being gone and the readback failing are both graded. Opt-in
  through `--dag-shape`; a build without it is byte-identical.
- Serve `delete_file` on SharePoint and Drive file entities. The specs
  declared `DELETE` on both; the definitions served no tool for it, so no
  destination in the builtin registry could host a delete. `MUTATE` still
  excludes delete, so the legacy planner's output is unchanged and
  `--dag-shape '*'` now includes `delete_chain` wherever a file destination
  admits it.
- Graders learn about records that existed only during a run: the
  execution contract stops reading a deleted record's fields and entity from
  the post-state, aliases an id through the results the trace recorded, and
  skips an expected failure on a node an earlier designed failure blocked;
  the served surface attributes a readback by the id a deleted record
  answered to; the outcome axis meets a create and a delete on the same
  transient record from the spans and grounds the artifact on the write the
  service saw.

### Eval execution: three-axis agent runs

- Review findings closed: the service records every call it refuses
  (unknown tool, undeclared argument, a limit) and the trajectory axis
  counts them as attempts against precision, the budget and its pass, on
  the local and the served path alike; a mapped (`for_each`) write claims
  every record it produced rather than one, so a fan-out of creates is no
  longer collateral; `compare` computes a case's overall delta over the
  axes both runs observed and gives two runs with no axis in common no
  verdict; the summary's trajectory rates are absent rather than zero where
  no trajectory was observed.
- Add Anvil's mutation battery for the graders (`tests/test_evalrun_mutations.py`):
  each case weakens one control on a passing reference trajectory and
  asserts the score drops on the right axis. It found and closed two gaps:
  a successful write the service could not attribute to a node now counts
  as leaking past a designed failure, and an unchanged retry of the refused
  call no longer counts as honouring it (a keyed create makes that retry
  safe under Anvil's law, not honoured).
- Studio grades agents on the company's connector cases: an `evalrun` job
  (`worldloom studio evalrun`, `studio run --operation evalrun`, the
  console's Evaluations page, the workflow's next step once the queryset
  exists) runs the reference agent or the connected coding harness over
  the revision's verified dataset with lineage attached, appends every
  graded case to a durable ledger a retried job resumes from, seals the run
  with a receipt the results route authenticates, and pages per-case grades
  with what each lost on which axis. The run directory is an ordinary
  `evalrun` run, so `summarize` and `compare` read it.
- Add `worldloom evalrun plan`, `EvalSession.plan`, the `evalrun_plan` MCP
  tool and `worldloom.evalrun.plans`: the plan axis graded alone. A planner
  receives the request and the tool catalog and returns a DAG of tool calls;
  nothing executes, and the DAG is graded by tool name and dependency
  reachability with `grade_plan`'s formula. Planners: `reference`,
  `--exec <command>` (a `worldloom.evalrun-plan/v1` document per case) and
  `scripted:<plans.json>` (`worldloom.evalrun-plans/v1`, written against
  `evalrun requests --for plan`). Scores now record which axes they
  observed; a summary reports no mean and `compare` no delta on an axis a
  run did not observe.

- Add `worldloom evalrun` and `worldloom.evalrun`: run any agent against a
  compiled enterprise case set, one isolated connector state per case, and
  grade three axes separately. Plan (the DAG the request should produce),
  trajectory (order, budget, designed failures honoured, retry storms,
  Anvil's `duplicate_write`, `unsafe_retry` and `destructive_without_read`
  laws) and outcomes (records created, updated and deleted as a state diff
  with collateral writes named; artifact grounding on the pinned source
  records; a rated answer). `grade_trace`'s verdict rides beside them.
- Ship a reference agent that walks each expected DAG through the same tool
  surface an external agent gets, a scripted agent, and a callable seam. An
  agent that raises is an error row excluded from every mean. Runs are
  byte-reproducible unless `--timed` records latency.
- Adapt Gemini Enterprise Eval Studio's judge prompt, score parser (clamped,
  with "no number" as an error), latency fields and ±0.10 comparison bands;
  import its results CSV as an answer-axis-only run. Port Anvil's effect,
  risk, idempotency and closed error-code vocabulary as `evalrun.safety`, and
  expose the same MCP annotations from the service's `tool_catalog`.
- Fix `ConnectorEvaluationService` grammar attribution, which demanded an
  `entity` argument on tools that do not declare one and so could not
  attribute any email-source search made through the served surface. Add
  `spans`, `snapshot` and `tool_catalog` to the SDK path.
- The Studio interview now states that evaluation is not retrieval and asks
  which axes and write operations each use case exercises.
- Make the run drivable by any harness: `evalrun run --exec` runs an
  executable as the agent one subprocess per turn over the existing seam
  (`worldloom.evalrun-turn/v1`); `evalrun requests` writes cases and tool
  catalogs as a document a harness answers offline
  (`worldloom.evalrun-requests/v1`, `-responses/v1`); `EvalSession` is the
  SDK entry; `worldloom mcp` gains `evalrun_*` tools; `evalrun` is a declared
  seam in `worldloom seams`; the `worldloom-evalrun` skill and
  `/worldloom-evalrun` command carry the procedure.
- Close the MCP transport: the served surface snapshots state at
  `eval_begin` and gains `eval_score`, which returns the three-axis case
  result for an external agent's run; `evalrun import-served` collects those
  documents into a comparable run. Add `--rater exec:<command>`, a judge
  over the `--exec` seam (`worldloom.evalrun-rating/v1`), so the answer axis
  can be model-rated without this package importing a model SDK.

### Generation: reviewed company-data sizing

- Add opt-in data creation proposals that reuse the canonical retail inventory,
  connected replenishment and banking servicing programs. Preserve authored
  parameter values, validate execution limits and report exact planned table
  rows. Protect custom programs and ambiguous targets from silent replacement.
- Bound monthly-history sizing and require explicit acknowledgement when a
  change invalidates selected narration, native file plans, tasks and calibration.
  Earlier revisions and generated files remain intact. Existing generation
  defaults and golden corpora are unchanged.

### Studio: data, corpus and evaluation workbench

- Add **Create data & evals**, shared sizing proposals in the SDK and HTTP API,
  searchable accepted-source selection, generated file downloads and paginated
  public file-task inspection by operation, format and use case.
- Authenticate native exports before access without exposing private answers;
  distinguish requested connector queries, planned rows, generated files,
  reference qualification and observed target trials.
- Bind creation forms to company revisions and discard out-of-order source and
  query responses. Preserve explicit review before applying generation changes.

### Generation: guided native suites and bounded context selection

- Compile reviewable read, arithmetic, update and creation contracts from
  accepted company sections. Group shared facts before allocating evidence
  cases, reference-qualify actual Office outputs, and report source shortages
  instead of copying content to meet a quota. Preserve other use-case contracts.
- Add opt-in native noise candidates exposing grounded files from the same
  evidence component. Divide the total training budget before sampling, seal
  the training choice before one holdout, and retain authenticated replay.
  This measures additional-file context; it does not implement prose mutation.
- Share readiness, next actions, authenticated narration selection and native
  suite preparation across Studio, SDK and CLI. Add explicit proposal review
  and forms in the UI, plus a bounded workflow entry point in harness skills.
  Native-only tasks no longer require an unrelated connector scenario.
- Add an explicit Codex native-write option scoped to the task output working
  directory for update/create requests. Keep authoring requests read-only and
  preserve normal approval and network controls.

### Generation: native difficulty measurement and retail pilot

- Add opt-in fixed-corpus native calibration using existing empirical
  calibration observations and Wilson intervals. Seal independent evidence
  components before trials, commit the training decision before holdout, and
  require supported intervals within the declared band for every outcome group.
  Native noise evolution is not implied by this measurement.
- Add a reproducible retail pilot using actual company episodes, accepted
  reference narration and native read, calculation, update and creation tasks.
  Keep reference qualification separate from observed target performance.
- Expose native calibration contracts and results in Studio. Fix Windows
  subprocess test quoting and consume bounded rejected HTTP request bodies
  before returning the refusal, preventing connection resets hiding the 403.

### Generation: grounded native corpora and executable file tasks

- Add opt-in native corpus plans that assemble accepted company ArtifactIR
  sections into DOCX, PPTX and XLSX. Enforce content and distinct-fact quotas,
  deterministic bytes and evidence locators verified against actual files.
  Reuse canonical numeric facts in workbook cells for arithmetic evaluations.
- Add byte-bound read, analysis, update and creation contracts. Grade cited
  answers and submitted native files; updates require the original checksum
  and preserve unaffected extracted content. Retain explicit refusals for
  unsupported PDF inspection and rendered pagination.
- Add Studio Documents & files and the native run operation, sharing company
  revisions, narration, coding-harness exchanges and replay checkpoints.
  Report observed native outcomes separately from noise calibration; shared
  source evidence forms one component rather than independent samples.
- Inspect native file shape requirements against parsed Office bytes instead
  of treating requested dimensions as observed evidence.

### Generation: eval-driven company construction and measured selection

- Add opt-in Studio foundry runs that compile explicit use-case construction
  contracts, detect shared-world conflicts and bind source predicates into
  executable queries. Reuse existing recipe tactics and require domain evidence
  for scoped owners and processes. Revalidate all obligations after construction.
- Materialize declared support units without trading revenue allocation. Add a
  connected retail mechanism for lost demand, orders, two-tick receipts and
  invoice price arithmetic. Company events own the evidence projected into
  Jira, ServiceNow and email. Partial delivery, payment and ledger settlement
  remain explicit unresolved obligations. These opt-in steps change recipe,
  event, connector and fixture bytes.
- Compose narration, reference qualification, reader recovery and target-agent
  connector trials through durable checkpoints. Compare noise versions of one
  company using independent evidence components per use case and the existing
  Wilson estimator. Freeze selection before target holdout outcomes; an unmet
  gate publishes no calibrated dataset. Reference and reader quality inspect
  all candidate evidence before that selection.
- Add Studio stage, obligation, noise, coverage and measured-difficulty views,
  plus CLI `--operation foundry`. Reconstruct isolated connector effects from
  recorded proposals on resume. Target grading establishes observed connector
  contracts, not free-form answer correctness. Default generation and existing
  collection replay contracts remain unchanged.

### Generation: one-company datasets and local Studio

- Add `CompanyDatasetPlan`, separate from the existing multi-company
  collection schema. Freeze one canonical world, keep process simulation seeds
  stable, advance real case cohorts across batches, and refuse company drift.
  Task/case splits retain transitive evidence isolation; insufficient diversity
  remains incomplete instead of producing another company.
- Add a local Studio UI and shared SDK/CLI for company profiles, real revenue
  divisions, LOB roles, operating-process definitions, use cases, interviews,
  narration selection, revision history and durable generation jobs. Eval-only
  edits reuse the company; timeline additions replay and extend its history.
- Run bounded interview and narration requests through installed coding
  CLIs, custom JSON adapters or file exchange. Proposals require
  revision-bound application and never approve their own evidence. Existing
  collection plans and default generation paths retain their replay contracts.

### Generation: opt-in dataset compilation and split isolation

- Add a sealed dataset plan with exact stratum quotas, repetition caps, task
  and company minima and a finite generation budget. Deficits drive existing
  company/episode/synthesis builders; equivalent executable plans are removed
  before fixture materialization and qualified rows alone consume quotas.
- Derive task/case/request identities from executable contracts and evidence.
  Reserve admission capacity for diversity; isolate transitive shared evidence
  and task or company groups before assigning splits. Incomplete runs cannot
  emit a publishable queryset.
- Persist exact batch Worlds, fixtures, proofs and content receipts. Resume
  generates only missing batches; complete replay makes no external calls.
  Add `evals dataset compile` and `verify`, SDK composition and a measured
  retail/banking example. Existing generation paths retain their bytes.

### Generation: opt-in evidence admission and empirical noise calibration

- A shared `reader/v2` plan/check/accept boundary covers full eval-critical
  evidence in ordinary narration and program expansions. Rendered prose and
  aspects go to the reader; expected facts remain in the checker. Current
  identity, reader configuration, visibility and artifact witnesses bind the
  acceptance. Missing, ambiguous, stale and unrecoverable targets refuse.
- Accepted and rejected reviews retain responses and findings through the
  generation ledger and `NarrationReaders` recipe step. This changes opted-in
  ledger/recipe bytes; unchanged accepted checks replay without reader calls.
  Legacy reader serialization, default program generation and golden corpora
  are unchanged.
- `evals.calibration.calibrate_noise` reuses Messiness, campaign revalidation,
  reader/fidelity admission, empirical cohort estimates and Archive. Each
  variant starts from isolated baseline generator state. Finite budgets,
  uncertainty, refusals, niche holes and frozen held-out selection are recorded;
  complete records replay without external callbacks. Exports retain the
  exact selected trial worlds and split-labeled receipts.
- Newly added noise prose uses the existing deterministic template provider,
  with its own explicit authorship and ledger namespace. It is not reported as
  model-authored. Offline narration replay can resolve an explicit set of
  recorded model IDs against exact current request keys, refusing ambiguous
  matches and preserving actual authorship. CLI replay uses those recorded IDs.

### Fixed: complete fidelity populations and provenance-bound difficulty

- Fidelity slice columns retain global marginals. The full typed union census
  includes one-sided, missing, null and empty populations even when metrics are
  capped. Nonfinite numeric values cannot satisfy metric gates. CLI strict slice
  support rejects omitted or unsupported groups while retaining diagnostics.
- Difficulty calibration supports versioned eval and request features with
  intervention conditions. Trial replay is idempotent; configuration drift and
  eval/corpus split leakage refuse. Estimates expose Wilson intervals, minimum
  support and provenance. Held-out Brier/ECE retain unsupported denominators;
  legacy counts and reference executions cannot claim fitted agent difficulty.

### Generation: opt-in operational case binding and qualified coverage

- `with_operational_case_binding()` scopes enterprise queries to deterministic
  real case cohorts shared by all source roles. Bound query IDs, user-facing
  source references, source predicates and metadata change. Unbound query
  serialization and generated source records retain their existing bytes.
- `EnterpriseEvalHarness.qualify(pool_size=...)` and `enterprise-evals qualify`
  admit a bounded pool through strict source evidence, independent validation,
  compilation and executable assertions before selecting coverage. Native
  input formats require actual World artifact bytes; metadata alone refuses.
- Semantic interactions and operational cases have separate measured coverage.
  Output caps recompute holes against the requested pool. Refused candidates
  remain inspectable and contribute no witnessed coverage.
- Qualification exports keep the exact shared connector dataset, selected
  fixtures, compiled rows and execution proofs. Source native-byte receipts
  remain bound to admission; the source World retains the native files.
  Default enterprise build behavior is unchanged.

### Generation: narration contracts and calibration provenance

- `section_prose@6` and `artifact_plan@2` bind accepted authorship to the
  complete request and full fact records. Requests exclude future,
  observer-hidden and transaction-unavailable facts before external authors
  receive them. Terminology and record time now reach the JSON handshake.
- A changed cutoff, author, purpose, authority or supersession invalidates
  stale reuse even if numeric values stay equal. Accepted plans must match
  the current contract; conflicting current plans are refused. Cold narration
  replay installs planning evidence before compiling its outline.
- These identities change nonempty authored ledgers. Reaccept authoring under
  the new contract or use the prior engine to replay prior bytes; no unsafe
  fallback treats an old key as a current acceptance. Golden fixtures and the
  hand-authored grocery narration source are unchanged.
- SDK and CLI builds with calibrated priors retain content-addressed estimator
  receipts in the recipe and replay them offline. Final physics overrides
  remain authoritative. Uncalibrated builds omit this metadata.
- SDK company specifications that request policies now generate them through
  the existing domain builder, matching CLI company builds. This changes output
  for SDK specifications whose policy setting was previously silently dropped.

### Generation: candidate shape admission

- Candidate validations now serialize observed shape checks. Designs with
  unsatisfied record, artifact or thread requirements no longer emit accepted
  instances. Layout and execution constraints lacking independent witnesses
  explicitly reject as unsupported. This changes campaign manifests and
  acceptance; it does not synthesize new fixture records to make a check pass.

### Added: reuse company profiles across finalized evaluation campaigns

- `evals.candidate_builder(blueprint, pipeline)` composes the existing immutable
  company blueprint and typed stages using each candidate's planned seed.
  `evals construct --company-spec FILE --periods N` uses that same path and
  retains the company resolution and unmet claims beside the campaign.
  SDK company resolution also carries the existing policy generation setting,
  which was previously dropped between resolution and build.
- `CampaignRun.map_worlds` revalidates and rebinds transformed worlds.
  `select`, `prove`, and `export` preserve the actual candidate and construction
  provenance without invoking its builder again. All attempts remain in the
  manifest, including rejected and deliberately unselected candidates.
- `EvalCampaign.search` delegates to existing adaptive candidate feedback.
  Selection reuses measured outcome diversity. No second campaign framework,
  narrator, episode grammar or evolutionary search engine is introduced.
- Candidate shape constraints now affect acceptance. Observed record, field,
  payload, artifact and thread counts are checked; native layout and execution
  constraints lacking independent witnesses explicitly reject as unsupported.
  Plan validation rejects a plan from a different immutable eval design.
- Company, author, SDK and eval skills route to the same composition path.
  `docs/company-eval-reuse.md` records the audit, narration reading order,
  runnable example, calibration boundary and remaining implementation gaps.

### Generation: executable enterprise DAG grammar

- Opt-in `enterprise-dag@1` plans carry typed arguments, result references,
  result-dependent conditions and bounded iteration. Eight authored shapes
  exercise chains, joins, branches, repeated reads and multiple writes. Shape
  selection participates in coverage and sharding before limiting the output.
- Mapped reads require at least two source records. Conditional campaigns
  deterministically request one- or two-record witnesses. These change planned
  query identities, selected fixture inputs and exported bytes when enabled.
  The default retains the legacy trajectory. No coverage of an unavailable
  external 42-shape catalogue is asserted.

### Added: external connector execution and independent trace grading

- `enterprise-evals serve` exposes MCP StreamableHTTP connector tools with
  isolated runs, per-principal bearer authentication, bounded requests and
  responses, captured native result receipts, trace retrieval and grading.
  The optional `mcp` dependency uses SDK 2.2 APIs; the existing stdio commands
  use the same version. TLS, OAuth deployment and a live Gemini Enterprise
  integration are separate deployment work.
- Both reference and external runs use the same connector emulator and
  assertions. An exact `failure_at` contract checks the declared error, write
  effects and stopped descendants. Partial writes persist their effects before
  returning an error; an unrelated failure cannot satisfy the contract.
- Simulation retains the failure finding and distinguishes completion, a
  designed write failure, an earlier stop and a runtime exception. Grammar
  assertion grades are reported separately from legacy weighted DAG scores.
- Ambiguous joins and stale sources remain data perturbations. Their response
  policies are unimplemented and the grammar refuses those combinations.

### Generation: enterprise state, field and evidence requirements

- Drive now projects rendered PowerPoint artifacts as distinct `pptx`
  connector records. Presentation-rendered corpora gain records and may select
  different source fixtures, changing replay bytes from the prior generation.
  Existing non-PowerPoint record identities and unrendered projections remain
  stable.
- Planned mutations carry an authored target state, derived from a legal
  connector workflow transition or explicitly declared on the destination.
  Required source fields carry their canonical connector definitions through
  query export, deterministic materialization, filtering and grading.
- Fixtures pin expected World facts and, separately, content-addressed
  operational observations. Source evidence never borrows a World fact id to
  disguise missing evidence. Failure overlays name a record belonging to their
  connector and distinguish source failures from destination failures.
- Source fixtures select the declared minimum and both runtimes read that whole
  set. Create and create-path upsert fixtures cannot inherit a preexisting
  destination merely because another query updates the same entity type.
- These additions change `queries.jsonl` and `fixtures.jsonl`; required custom
  fields also change connector records. Existing plans load with empty optional
  contracts. Rematerialize legacy fixtures to obtain verifiable evidence pins.
  Seed replay is stable within this generation; it does not promise byte
  identity with the previous generation.

### Fixed: executable connector vocabulary and checked outcomes

- The bounded, interleaved 400-query reference population now resolves every
  connector operation. Email has an authored connector definition. Patch maps
  to update; upsert chooses create or update from the explicit preexistence
  requirement. File aliases resolve to the selected format before tool lookup.
- Create payloads satisfy the connector's required fields. Verification follows
  the actual created record. Alias destinations retain their artifact assertion.
  Sending email applies the authored sent state rather than creating a draft.
- State grading requires a persisted write to the declared fixture and an
  available post-state. An unchanged initial state, wrong record, or missing
  post-state cannot satisfy a state assertion. A declared, exactly matched
  partial-write failure can establish its recorded persisted effect.
- Evidence validation rejects empty placeholders. Operational evidence has a
  distinct local integrity contract; it does not claim macro reconciliation or
  independent replay of an unavailable synthesis ledger.
- `enterprise-evals space --profile` sizes the selected scenario and reports
  an exact count or a witnessed lower bound. Unused enterprise CLI and field
  manifest implementations were removed after field predicates moved to
  `ConnectorFieldDefinition`. The published `query_planning` API remains
  deprecated with its return schema preserved.

### Added: a corpus and its evaluation set can be run against Gemini Enterprise

`GoogleCloudPlatform/gemini-enterprise-eval-studio` solves the part of an
enterprise-agent evaluation that is genuinely hard and uninteresting to build
twice: reaching a Gemini Enterprise instance. Workforce Identity Federation,
OIDC and SAML, the `streamAssist` stream and its TTFT/TTFA/TTLT telemetry are
all there. What it does not do is populate the index it searches or observe the
run, and both of those are this engine's.

**Generation: none.** Nothing here builds, draws, or changes what a seed
produces. Every command reads a corpus that already exists and writes a new
projection of it.

- **`worldloom gemini-enterprise datastore`** writes a workspace as Discovery
  Engine documents in the `gcsSource` `dataSchema: "document"` format:
  `content.uri` into Cloud Storage, `structData` carrying the authority,
  lifecycle, policy, folder and supersession a two-column CSV cannot, and
  `aclInfo` carrying the drive's own readers -- which is what makes a
  permission failure observable at all. Eval Studio selects data stores and has
  no ingestion path, so without this the assistant is asked questions about a
  company nobody holds the answers for.
  - Document ids are derived from the path, not only the artifact id. A drive's
    noise copies deliberately share the id of what they copy, and importing
    them under it makes `importDocuments` read the second as an update of the
    first: the duplicates collapse, the store holds one document where the
    drive holds four, and the corpus's hardest content disappears between
    export and index with nothing red anywhere.
  - A file whose type Discovery Engine will not accept is skipped and named,
    never relabelled. `.md` to `text/plain` is a wire-type declaration and is
    fine; `.xlsx` to `text/plain` is a corrupt document that indexes as
    mojibake and degrades every query that reaches it.
- **`worldloom gemini-enterprise cases`** writes the evaluation set as one CSV
  per `EvaluationType`, each with the auto-rater instruction its shape claims.
  Eval Studio applies one instruction to a whole run, and its default asks for
  semantic similarity to the golden answer -- which grades an
  `expected_abstention` case exactly backwards, rewarding a confident invented
  answer for its fluency and scoring the refusal the case exists to reward as
  though it were an attempt. `RUBRICS` gives each shape a grader that matches
  what the shape claims.
  - Shards are capped at a hundred rows, because `csv.service.ts` truncates an
    upload with `results.data.slice(0, 100)`. Rows past the cap are not
    rejected, they are never sent, and the run reports a clean pass over a set
    it never saw.
  - A case with no `expected_answer` is left out rather than exported with an
    empty golden: Eval Studio scores a falsy golden as 0 without calling the
    grader, which is indistinguishable in the results from a model that
    answered and was wrong.
- **`worldloom gemini-enterprise score`** reads the results back and slices
  them by the structure the CSV could not carry. `processRow` builds its
  `ResultRow` from scratch, so nothing sent up beyond `query` and `golden`
  comes back down; the join is on the query text and it refuses rather than
  guesses when two cases ask the same question. A row whose auto-rater call
  failed is counted and excluded from every mean rather than averaged in as a
  zero, because Eval Studio returns `score: 0` both for a wrong answer and for
  its own grader failing.
- **What this does not do, said once here so no result implies it**: grade the
  trace. Eval Studio's stream parser keeps
  `answer.replies[].groundedContent.content.text` and discards the rest, so
  tool calls and grounding metadata never leave the browser and
  `connector_trace`'s eighteen assertion kinds have no wire to read. Every
  score this returns is a judgement about a final answer.

### Added: an evaluation case can carry a request, not only a question

An `EvaluationCase` had eleven fields and none of them said who wanted to
know. A question with no asker has no reason to exist beyond "this fact is
checkable", which is what makes a generated set read as a quiz rather than as
work: real requests come from someone, at a moment, through a channel, under
a constraint, and usually name what they want back.

- **`EvaluationCase` gains the request tuple**: `asker`, `asker_person_id`,
  `occasion`, `intent`, `channel`, `constraint`, `deliverable`. All optional,
  and serialized only when set, on the contract `CanonicalFact` already
  established for its bitemporal fields. A case with no request writes exactly
  the bytes it always did, so no corpus is rewritten, no schema version moves
  and no migration step is owed. Verified against a `git archive HEAD` tree:
  a default `build --seed 8128` is byte-identical.
- **`worldloom.evals.intents`**, forty work verbs as authored data
  (`_data/evals/intents.json`, schema `worldloom.eval-intents/v1`): brief,
  triage a queue, chase, escalate, sign off, reject with reason, reconcile,
  attest, close out, abstain and the rest. Each declares its answer shape,
  the evidence it rests on, whether it reads or writes, what a write produces,
  the mistake it is posed to catch, and which activity types it suits.
  `EvaluationType` is untouched and stays the grading shape; intent is the
  work shape, and each verb names the grading shape that checks it, so adding
  a verb never adds a grader.
- **`lob.asks_about`**, the responsibility primitive read backwards. A role
  answers for some fact kinds, so those are the kinds it has standing to ask
  about; `reports_to` extends that down the line for status and up it for the
  authority its own work needs. A join, never a table, on the same argument
  `participation` makes. Industry flavour arrives through the slots: a credit
  officer asks about covenant breaches because an edge says she answers for
  them, and nobody types a per-industry question table.
- **`process_bindings.situations`**, a binding crossed with the verbs its
  activity type admits. The compiled catalogue already declares the activity,
  the owning unit and country, the system of record, the control and the named
  exception; the cross supplies the occasion a request arrives on. The twelve
  shipped industries compile 6,975 bindings and yield 189,346 situations,
  against 103 hand-typed question keys across the four engines today.
- **The `eval_plausibility` check group**, registered from `_install` like
  every vertical's. It refuses what a corpus can be wrong about: an intent
  nothing declares, a grading shape the intent does not name, a write with no
  deliverable. Whether a seat would realistically ask a given thing is a
  judgement about the world rather than a disagreement inside it, so
  `evals.plausibility.findings` reports those as sentences in the shape
  `phrasing.findings` uses, and they never fail a build.
- **Generation**: none. Default builds, `evals construct` and
  `enterprise-evals build` are byte-identical; every field above is opt-in and
  no shipped generator populates one yet.

### Proposal engines behind the compiler boundary

- **`providers.py`**, four extension seams on the pattern `narrative.providers`
  and `actors.providers` already set: `PriorEstimator`, `SurfaceValueProvider`,
  `DetailSynthesizer`, `DomainImporter`. Each is a small `Protocol` with an `id`
  and `version`; each execution leaves a **`Receipt`** whose `key` is a content
  address over backend, operation, configuration, source, candidate and accepted
  digests, digests, never data. `accept` makes a synthesizer's proposal into
  data by refusing rows that violate a constraint and then reconciling every
  declared total by largest remainder at the declared precision. A deterministic
  fake (`EvenSynthesizer`) proves the contract with no backend.
- **`calibrate.py` / `worldloom calibrate` / `build --priors`**, physics
  ranges learned from a sensitive table under differential privacy. The built-in
  Laplace-histogram estimator clips, bounds contributions by truncation, noises
  under sequential composition and reads spans off the noised CDF. The
  `PriorSnapshot` is exactly the `--physics` overrides document plus the receipt
  and a per-column **noise-share** reading; the CLI names parameters whose
  release was more noise than signal. Noise is system entropy by default (a
  calibration is not reproducible, the corpus is) and a `--noise-seed`
  snapshot says in three places that it is not a private release.
- **`surface.py`**, postcodes, phones, registration numbers and bank accounts
  from versioned rules in `data/surface/rules.json`, every value a pure function
  of `seed / rules version / entity type / entity id / field`. Checksums are the
  issuing bodies' own (ABN, USt-IdNr, Austrian UID, UK VAT, NZBN, IBAN) and are
  tested against their published examples. `master_data` takes `"identifiers": 1`
 , the value names the rules version, every version is kept in the data file,
  and a corpus replays under the one it recorded; an un-opted register writes
  the same bytes it always did.
- **`causal.py` / `build --causal` / `worldloom causal check|trace`**, a DAG
  of named quantities with linear effects, dated interventions (`do()`) and
  drives that make a node's value an imperfection kind's budget. Distinct from
  `worldloom.synthesis`, which simulates operational records and intervenes on
  *them*: this drives the *document archive's* decay from a cause and records
  the trace on the corpus as **`causal.jsonl`**; interventions mint
  `causal.intervention` events; the `Causal` recipe verb replays byte for byte;
  the `causal` validator group recomputes every derived value from its recorded
  parents and refuses drift, over-delivery, or a missing event. Linear only , 
  `FactKindSpec.derive`'s closed-vocabulary argument.
- **`fidelity.py` / `worldloom fidelity`**, a synthetic table against a real
  one as a vector: KS and Wasserstein, Jensen–Shannon and total variation,
  cardinality and unseen share, correlation error, contingency distance, a
  nearest-neighbour two-sample statistic beside its baseline, exact-match rate
  and distance-to-closest-record against the real set's own. Per slice on
  request. No aggregate score, by design. Reads CSV, JSONL, JSON, or a corpus's
  detail table.
- **Generation**: no corpus built without `--causal`, `--priors` or
  `identifiers` changes a byte. `CORE_PREFIXES` gains `CAUSE`.
- `docs/extension-seams.md` is the contract; the SDK gains
  `Blueprint.priors()` and `Built.causal()`.

### Fixed: main was red

### Added: the eval drives generation

- `construct_candidate` executes one tactic per demand the eval design
  compiles to, instead of one: connector witnesses with one near miss per
  constrained field (`eval_witnesses`), the write step's precondition record,
  artifact families, access policies, events, and revision chains. Every
  construction is a recipe verb, so a constructed candidate rebuilds from its
  own recipe; the validator that accepts it knows nothing about the
  constructions. A demand no tactic can honour comes back as a finding naming
  the seam that owns it (a fact belongs to an episode).
- Witnesses are world events projected through the same connector registry the
  validator, the emulator and the exporters read, and a connector that has a
  definition but no engine projection (Teams, Slack, OneDrive) is now
  constructible and searchable.
- `EvalCampaign.construct`, `export(construct=True)` with the constructions in
  the manifest, and `worldloom evals construct design.json --out DIR`.
- `emulator_executor`: a reference executor that runs each step through the
  emulated connectors, so a campaign's proof is about the corpus and the
  emulator together.

### Added: a connector is not a file format

- File connectors (SharePoint, Drive) project one record per artifact *and*
  format once the world is rendered, under the definition's entity for that
  format, carrying the rendered file's path, size and hash; `get_file` serves
  the mime type and the hash. Before rendering, the one planned item per
  artifact it always was. `file_formats(connector)` names what a connector
  holds. A demand for a format is constructed by rendering it.

### Changed: the name is worldloom, and the prose reads like a person wrote it

- The package's home is `github.com/vamsiramakrishnan/worldloom`; the README,
  the docs site base path, badges and clone commands point there. The first
  release ships from PyPI as `worldloom`; `RELEASING.md` carries the order of
  operations.
- `tests/test_prose_style.py` gates every user-facing document, the generated
  CLI reference and the docs site against the tells of model-written prose
  (the em dash as a universal joint, a stock adjective of praise, a vendor's
  name), and
  the CLI's own output lines follow the same rule. About 1,400 sentences
  across 110 files were rewritten to pass it; no command, flag, path or claim
  changed.
- `worldloom enterprise-evals space` reports a floor (`at_least`) instead of
  crashing when the space exceeds the ceiling.

### Fixed: main was red

- `EvalRevisionFamily` and `EvalDemands` are registered recipe verbs. Both
  were recorded on every world the eval-first tactics touched and registered
  nowhere, so recording them was itself the failure and no such corpus could
  have replayed; the one-shot workflow meant to patch the verb into
  `recipe.py` never ran. Both register from their own modules through
  `register_step`, import unconditionally from `_install()`, and replay
  (`tests/test_eval_construction.py`, `tests/test_eval_interventions.py`).
- The connector emulator resolves the native ids it emits. A search page's
  `id` handed to the next tool, which is what a real trace does, was refused as
  `not_found` by the emulator that had just returned it.
- `worldloom seams` is documented and the generated reference is current.

### Removed: one-shot branch workflows

- Twenty-two workflows scoped to merged-and-deleted `codex/*` branches (the
  `artifact-realism-*` apply/fix jobs, the eval-contract repair gates, the
  source snapshot and the vocabulary harvests), the never-applied
  `finalize_process_catalogue.py` migration and the b85 catalogue chunks it
  would have switched to. The tools the harvests drove stay in `tools/`.
  `process-catalogue-check` is a read-only check on main; `process-bindings-check`
  no longer names the deleted branch.

### Generation: reusable narration programs

- Add opt-in family-level prose authoring and deterministic clause expansion. Existing per-instance narration remains unchanged.
- Persist program sources and clause dependencies in the normal ledger and restore them during recipe replay. Bound-fact changes invalidate only dependent expansions.
- Enforce measured near-duplicate budgets and optional blind-reader findings through existing claim validation. Expansion and replay make no model calls.

### Generation: canonical bitemporal views

- Add opt-in observer, source and transaction-time fields to canonical facts.
  Unset fields retain legacy serialized bytes. Explicit latent channels do not
  leak into employee views; late corrections cannot enter earlier narration.
- Historical predicates and bounded joins share a frozen query context.
  Missing fields are distinct from null; booleans are not numeric witnesses.
  Unsupported historical construction refuses rather than inventing state.

### Generation: artifact ecology v1

- Opt-in `artifact_realism=ecology/v1` changes native artifact metadata, style
  selection, connector lifecycle history and output bytes for a fixed seed.
  PDF outputs persist machine-readable realism, lifecycle, revision and family
  markers. Recipes record replayable metamorphic noise transforms.

### Added: source-backed process catalogue

- `worldloom.process_bindings` compiles the supplied 12-industry catalogue into
  typed company activity bindings, lexicon records, process-authoring briefs and
  a read-only connector dataset. The installed module CLI and the checkout
  `tools/compile_process_bindings.py` wrapper share the same compiler.
- Preserve all 6,975 supplied bindings and all 215 original coverage cells.
  Surface the missing utilities billing definition as an additional coverage
  cell. Treat the 63 source-labelled calibration cells as unresolved targets,
  not measured priors. Keep APQC IDs as hints and the input license as NOASSERTION.
- Export 55,800 authoring demand slots, with ownership oracles only for exact
  structural bindings. Other templates require runtime state, controls and
  executable eval construction. Source and export commitments support offline
  parity checks and full replay, including projected files.
- Generation compatibility: opt-in namespace `worldloom.process-catalogue/v1`.
  Existing World recipes, operational programs and golden corpora are unchanged.

### Fixed: constructive predicate witnesses

- `satisfy` no longer treats a missing field as a constructed witness for
  `ne` or `eq null`. Explicit existing values still use the shared evaluator;
  absent fields must be materialized by a valid construction or a caller's
  domain alternative. Existing predicate tests now pass without weakening
  matching semantics or manufacturing a status value.

### Fixed: artifact lifecycle source contract

- Artifact ecology resolves timestamps, versions and state from the compiled
  manifest. A missing or mismatched manifest is an explicit refusal, not an
  access to fields that ArtifactIntent does not define. Existing compiled
  artifact lifecycles are unchanged.

### Generation: opt-in authored process planning

- Integrate the supplied 12-industry factors with typed company, owner, country and system bindings, named-stream channel draws, source-attested lexicon records and pinned offline replay. Existing world builds and the source-reference catalogue API do not change.
- Feed activity context into the existing process authoring cascade without bypassing its validation gates. APQC references remain hints; calibration names remain requests; template pairs are not executable evaluations.
- Expose missing streams, fallback owners and unresolved system schemas. Retain source hashes, licence declarations, coverage and replay manifests.


### Added: operational relational synthesis

- Opt-in `worldloom.synthesis` SDK and `worldloom synth` commands. Frozen,
  typed causal programs generate related entities and lagged state with keyed
  noise, integer arithmetic, hard constraints and operator-owned work limits.
- Retail inventory/replenishment and banking loan-servicing programs. Paired
  interventions preserve identity and exogenous noise. Streaming exports carry
  replayable recipes, checksums and counts; verified shard merges reproduce
  unsharded bytes. Completed shards can be resumed without trusting markers.
- Quality-diversity parameter search measures behavior, retains niche champions
  and audits held-out seeds. Candidate code cannot alter the evaluator.
- Designer/critic executable teams share measured feedback and a bounded archive.
  Immutable receipts support checkpointed reuse and offline, no-process replay.
- Grounded operational case projections, industry-specific enterprise query
  profiles, and strict source mode that refuses missing source records.
- Skill, operator documentation, invariant, counterfactual, replay, search,
  executable-contract and enterprise integration regression tests.

### Fixed: reference narration build contract

- CI and the reference README explicitly select the historical outline settings
  expected by the authored grocery narration. The prose and acceptance rules are
  unchanged. A new CLI integration test pins this path, not only the SDK path.

### Generation compatibility

- Existing World recipes, default World generation and golden corpora are not
  changed by operational synthesis. Its recipe namespace is
  `worldloom.synthesis/v1`. Strict enterprise source admission is opt-in.
- The operational simulators are declared assumptions, not statistically fitted
  customer models. They do not imply privacy guarantees or reconciliation to
  an attached World's macro financial totals.

### Added: a real-model writer behind the agent seam

- **`tools/model_narrator.py`** turns a coding harness's headless CLI
  (`--backend claude` or `--backend codex`) into the stdin/stdout child
  contract: request document in, responses document out, rejections fed back
  unchanged on the next round. The backend sees only a self-contained prompt
  built from the harness's own rules and facts, with no Worldloom types and no
  corpus access. Output parsing tolerates fenced or
  chatter-wrapped JSON by scanning for the balanced `responses` object.

### Added: an agent command can write for a whole mosaic

- **`mosaic --narrate-exec COMMAND`** narrates every world through an agent
  command of your choosing instead of the deterministic provider: the command
  runs once per section with a request document on stdin and must print one
  responses document on stdout. That is the same child contract `narrate loop --exec`
  speaks, so one adapter (a wrapper around any writer that reads stdin and
  writes stdout) drives both surfaces unchanged. `tools/exec_agent.py` ships as
  the reference adapter: no model, key or network, and the contract drives end
  to end.
- The exec-backed provider (`narrative.ExecProvider`) rides the existing
  `World.narrate` seam rather than beside it, so everything the mosaic already
  guarantees about narration holds for agent prose too: ledger entries keyed by
  the writer's id (`--narrate-model-id`, so a corpus records who wrote it),
  checkpoint resume via `on_accepted`, `--narration-concurrency` fanning
  sections across concurrent children, and per-section retry with the violation
  text fed back to the child. Rejections come back to the agent as feedback;
  nothing is repaired locally.
- Refused before anything lands on disk: `--narrate-exec` with `--no-narrate`
  is a contradiction (refusal code `narration_conflict`). A child whose stdout
  is not JSON dies in `run_exec`; valid JSON of the wrong shape is refused by
  the provider layer with the child's stderr tail attached.

### Generation: corpora stop being clones of one document and one brand

Five small dials, turned together, aimed at what a six-period corpus reads like
rather than at any one mechanism: **variety** (documents of a type stop sharing
one shape wherever the type gives them room to differ), **diversity** (names no
longer repeat from pools sized for a demo), and **length** (sections asked for
telegrams now ask for prose). Measured on the reference six-period retail build
(seed 8128): 11 → 13 distinct document shapes across 30 compiled artifacts,
unique-shape ratio 37% → 43%, repeated shapes 93% → 87% of artifacts. The
per-period close calendar is still an exact ×6 clone: its sections are all
required and it ships one variant, so every mechanism here declines to touch
it by construction. Types with optional sections, several variants, or room to
recombine are where the difference lives.

- **The structural genome is on by default at the CLI.** `worldloom build` now
  passes `--section-omission 200 --outline-synthesis 300 --variant-bias 1`
  unless told otherwise, so an unflagged build's documents vary in which
  optional sections they carry, in shape drawn from the company's own types,
  and in which authored variant they take, instead of emitting each type's
  outline identically, every period. All three mechanisms are coherence-safe by
  construction (required sections always survive; synthesis must carry at least
  what the authored outline carries; variant bias only rotates variants a type
  ships), and the genome is recorded on the recipe, so replay is byte-exact and
  older recipes without the key stay classic. Pass three zeros for the
  historical corpus.
- **Narration briefs lengthened ~55%, measured at the pin:** `target_words`
  small/medium/long 70/130/200 → 110/190/300 (`narrative/compiler.py`), with
  `NarrativeRequest.target_words`'s standalone default aligned at 190. Longer
  briefs pull more optional facts per section (the deterministic provider's
  evidence budget scales off this number), and that is the whole of the
  retrieval-hardness move recorded in `tests/test_retrievers.py` (numerical
  comparison 5/8 → 4/8): holding briefs at the old numbers while pools widened
  reproduces the old score, so documents demonstrably cite more of the
  corpus, not just more words.
- **Company-name pool tripled** (`generators/names.COMPANY_FIRST`, 15 → 45):
  fifteen first words meant a mosaic of tenants shared one branding vocabulary.
- **Site-name pools doubled per locale** (`locales.py`, four presets, 6 → 12
  cities each): six names could not carry a national estate. Real place names,
  geography rather than branding, keeping each preset's existing cross-border
  entries (Auckland/Wellington, Wien/Zürich).
- **System-name pools widened** (`names.py`: ERP 6→10, MDM/PLATFORM/COMMERCE/
  POS 4–6 → 6–7): a company whose every system was named from a four-deep list
  read as procured from one vendor fair.

**Breaking for reproducibility:** a fresh build from the same seed produces
different documents than before the change: different shapes (genome), names
(pools), and narration briefs. Existing corpora replay byte-for-byte: the
genome travels in the recipe, facts and ledgers travel in the corpus, and
nothing here touches either. The golden `examples/retail-close` corpus is
hand-authored and unaffected.

### Generation: every format reads the style genome, and the genome gains a typeface

- **The style genome now reaches every renderer.** `render/pdf.py` (Helvetica
  end-to-end, hardcoded palette), `render/html.py` (a generic grey stylesheet),
  and `render/xlsx.py` (grey `EEEEEE` headers) were the three formats that
  still decided their own look. They now derive the same world-seeded
  `StyleGenome` `render/docx.py` and `render/pptx.py` already read (fills,
  text colours, type sizes, spacing, density, gridline policy, rule weight,
  title alignment), so one world's memo, deck, PDF, HTML twin, and workbook
  cannot disagree about the company's own identity. PDF additionally gains
  genome-driven table rules per `gridline_policy`/`rule_weight` and
  genome-scaled cell padding; HTML gains the negative-figure colour the other
  formats already carried as colour-is-the-second-signal.
- **A fourth axis: `typeface`.** The genome samples one of four curated
  families, `house_sans` (the shipped look), `editorial_serif`,
  `engineering_mono` and `director_serif` (serif display over sans body), drawn
  from its own named `Rng` stream, so no existing draw reshuffles.
  `render/fonts.py` is the one resolution table: base-14 families for PDF,
  OOXML names or theme-default `None` for Word/PowerPoint/Excel, CSS stacks
  for HTML. `house_sans` is inert in the theme-bearing formats (no font name
  set at all) and resolves to Helvetica only in PDF, where reportlab has no
  theme to inherit.
- **Breaking for reproducibility:** a world whose sampled genome draws a
  non-house family now renders different bytes in every format, and the
  genome-driven colours/sizes change PDF, HTML, and XLSX bytes even for house
  palettes. Existing corpora replay identically under their recorded version;
  re-rendering under the new version re-skins them.

### Generation: AlphaEvolve balances evolutionary search without evolving truth

- Added a checkout-only `evals/alphaevolve` portfolio following a strict
  current-policy → restricted search → holdout/adversarial → reviewed-source
  integration loop. Managed execution uses the official client, is bounded,
  and refuses to start without `--confirm-spend`.
- The first seam is `evolve._propose_children`. Its prior value-only rank could
  mutate a wide axis repeatedly while narrower axes remained untouched. The
  reviewed policy now ranks the least-varied axis first, then the least-seen
  value, then the existing content-addressed tie key.
- Coherence validation, recipe replay, fleet fitness, and fact/generation
  ledgers are protected oracles: candidates cannot see or change them. The
  local gate freezes 64 search, 37 holdout, and four adversarial cases and makes
  no realism, retrieval-quality, managed-winner, or billed-cost claim.

### Generation: a document type may argue its case more than one way

- **`documents._OUTLINE_VARIANTS`.** A six-period corpus produced **32 distinct
  shapes across 249 artifacts (13% unique), largest group 37**, and every
  near-duplicate group was exactly ×6: the same document once per period, the
  same headings in the same order. Six close calendars with different dates is
  realistic; six root-cause reviews with an identical five-section skeleton is
  not, because real reviews differ when the incidents do. Now **40 shapes (16%
  unique), largest group 18**.
- Six types carry alternatives: `unit_close_commentary` (3),
  `incident_rca`, `executive_summary`, `performance_review`, `one_to_one_note`
  and `job_requisition` (2 each). Each alternative is a different **argument**,
  never a reshuffle. An RCA that opens with the cause is a different document
  from one that opens with the timeline, and a test refuses two variants whose
  sections differ only in order.
- **Rotated by ordinal, not drawn.** N instances over M variants land evenly by
  construction; a seeded draw would only *tend* to spread and would happily give
  six documents one shape on an unlucky seed, the exact failure being fixed.
  The first variant is the outline that shipped, so a type's first instance is
  byte-identical and only later ones move.
- `examples/grocery-close/narration.json` (real model prose, checked in) is
  **rewritten** for the three sections the rotation changed rather than the type
  being left alone. A reference narration should stay current, and a document
  type nobody varies is worth less than the work of keeping it.
- Retail's default build and the grocer differ by that rotation, which is the
  intended change; banking, insurance and procurement are byte-identical, having
  no variants on their own types.

### The corpus as a drive, not a folder of numbered files

- **`worldloom workspace`.** A corpus exports to one flat `artifacts/`
  directory of `art-0001-…` files with **identical filesystem permissions on
  all 293**. That is right for the harness, which reads the manifest and never
  looks at a path, and wrong for what the corpus is for: an enterprise
  assistant indexes the folder, the title, the owner and the sharing, and path
  and title carry a large share of retrieval signal. The corpus knew every one
  of those and put none of them on disk.
- Measured on a six-period, eight-division build: **249 files across 52 folders,
  four levels deep, 224 restricted, 44 distinct owners, 6 superseded pairs.**
- Documents are shelved by the function that owns them (`Policies/`,
  `Finance/Close/2026-03/`, `Technology/Incidents/`, `People/Performance/`),
  with periodic types filed under their period and standing types at the top of
  their shelf. Filing a policy under a month would say it expired with the
  month.
- Filenames carry the **subject** where the facts agree on one, so a month's
  reviews read `Performance Review - Sian Vance 2026-07` rather than `(2)`
  through `(5)`, and divisional commentary reads `Unit Close Commentary - Fuel
  and Convenience 2026-03`. They carry the period too, because the commonest
  way a real document loses its context is being lifted out of its folder.
- A policy revised in place sits beside its replacement as
  `Expense Policy (superseded)`, and the **live** one keeps the clean name.
  Marking ran after names were claimed at first, so the retired policy took
  `Expense Policy.md` and the current one landed as `Expense Policy (2).md`:
  backwards, and the mistake a reader would act on. A monthly
  calendar that supersedes last month's is *not* marked, because that is the
  ordinary life of a periodic document; the edge is recorded either way.
- **`permissions.jsonl`** is one row per file: path, title, owner, every
  address permitted, policy label, created date, and the successor where there
  is one. Addresses are derived `first.last@company.example` with collisions
  broken the way a mail administrator breaks them. An unrestricted policy lists
  *nobody* rather than everybody, which is what a real ACL means by "inherit".
  A tree with no permission table tests retrieval and cannot test access.
- Nothing is invented and nothing moves: every folder, title, owner and reader
  is derived from the manifest, the roster and the access policies, the corpus
  itself is untouched, and an unrendered corpus is refused by name rather than
  laid out as empty folders.
- **`--noise none|lived_in|neglected`** makes the drive untidy the way real
  drives are: `Copy of X`, a document dragged into `Shared/` or `_Inbox/`,
  somebody's `X FINAL` beside the real one, an `_Archive/` leftover. Measured:
  249 files become **336, of which 87 are labelled junk**, evenly across the
  four kinds.
- Every extra file is a **byte-identical copy of real corpus content**, never
  invented text. A drive's junk is not fabricated documents, it is the same
  documents saved again in the wrong place under the wrong name, and that is
  what makes it hard: a retriever cannot tell the copy from the original by
  reading it. A copy carries the permissions of what it copies, so a misfiling
  is somewhere nobody would look and still readable only by the people the
  original was.
- Every junk file is **labelled** in `permissions.jsonl` with its kind and what
  it duplicates. That is the difference between this and simply making a mess:
  a benchmark scored against a drive it cannot account for cannot tell "found
  the wrong copy" from "was wrong". Seeded off the world, so a corpus's drive is
  the same drive every time; distractors that moved between runs would not be
  a benchmark.
- Filesystem noise, distinct from `--messiness`, which is content
  noise. A stale page is wrong; a duplicate is not wrong at all, it is merely
  there twice. A realistic archive wants both.

### Generation: the month-end model was empty in every multi-period corpus

- **`documents.finance_workbook` took its reporting month from the world rather
  than from its own facts.** `compile()` compiles every intent against the world
  as it stands *now*, so in a two-period corpus March's workbook was looked up
  at April: every measure lookup missed and the month-end model (the corpus's
  system of record, the document every other one reconciles against) rendered
  with **every cell empty**. Measured: a one-period build's Business Unit P&L
  carries 28 of 28 values, a two-period build's carried **0 of 28**, and the
  Store Performance sheet vanished entirely because it is gated on the period
  having site facts. Single-period builds are byte-identical either way, which
  is why it survived: every fixture, example and default build has one period.
- **`validate.compiled_evidence`**: the check that would have caught it.
  `unreachable_answer` reads `required_fact_ids`, the *plan*, and has to,
  because at step 3 nothing is compiled. The moment a corpus is compiled that
  becomes the weaker claim, and the gap between them is where this hid.
  Measured on an eight-division, six-period build: **6,185 facts planned into
  documents and 1,718 actually carried**, with 55 of 479 evaluation cases
  citing evidence in no document, and `validate` reporting clean. After both
  fixes: 6,071 carried and **0 unanswerable cases**.
- **The reserve triangle showed one valuation.** Found by the new check the day
  it existed: the prior-valuation ultimate was required by the workbook, cited
  by the insurer's own first evaluation case ("as at the 2026-03 valuation"),
  and carried by no compiled document. A triangle whose estimate sheet has one
  column is not a triangle: the subject of that whole episode is that an
  ultimate *moved*. Both valuations now appear per cohort, as the book-position
  sheet already did for the totals.
- The diversity floor drops 8 → 7, and the eighth shape was the bug: two empty
  workbooks composed differently from the populated one and were counted as
  variety. A corpus is not more varied for having two of its thirteen documents
  broken.

### Line management produces documents

- **`worldloom.workforce`**: the organisation was modelled in full and used as
  a source of *bylines*. A 420-person retailer named **24 of 444 people**
  anywhere in its corpus; a manager three levels down existed, had a name, a
  function and a manager of their own, and appeared in nothing. Two rounds fix
  it: `--hiring N` raises, approves, offers and fills N vacancies a period, and
  `--reviews N` reviews N people. Five artifact types, ten fact kinds.
- The hiring manager and the reviewer are drawn from **everybody with a direct
  report**: 73 people on a synthesised 420-person company against the dozen the
  role table names. Measured on a three-period build: artifacts 113 across 28
  types with no type above 21%, and **41 distinct people named in 37 distinct
  titles**, against 24 before.
- **A requisition reads the company's own rules.** Its three-year commitment is
  checked against the delegation of authority (`worldloom.policies`) and the
  lowest rung that covers it signs, so "was this approved at the right level"
  is the first question in this repository whose answer is in *neither document
  alone*. Annual cost was the first rule and made the ladder say nothing: every
  vacancy costs under 110,000 fully loaded and the second rung starts at
  230,000, so every requisition went to the same person. A corpus built without
  `--policies` still hires, and the requisition says "no written delegation" in
  as many words.
- **Two performance records disagree on purpose.** The signed review is an
  approved report countersigned by the manager's own manager (the corpus's only
  three-person document), and the running one-to-one note is an unofficial note
  carrying the view held before calibration. Every authority-resolution case
  here before now was about an incident; a rating is the same shape and reaches
  the whole organisation.
- **A fifth access class**, minted on first use rather than at build so an
  un-opted corpus keeps the four policies it had. An offer letter states one
  person's salary and a review states their rating; "all staff", "finance and
  audit", "executive committee" and "technology" are all wrong for a readership
  of one person and their line, and falling through to the narrowest locked the
  *author* out of what they wrote: `validate.author_cannot_see_own_artifact`,
  the first time this ran. Widened rather than replaced on a second round,
  through the `access_policies` seam `personnel.promote` opened.
- **`policies` is a specification field**, not only a flag. A description of
  what kind of company this is legitimately says whether it writes its rules
  down, and `--spec` refuses the flags it subsumes.
- **`evaluation._Taxonomy.workforce`**: a `cross_artifact` case whose answer
  needs the requisition *and* the delegation, and an `authority_resolution` case
  over the two ratings. They arrive one period behind the rounds, which is the
  same lag every cross-episode family already has: a corpus cannot ask about a
  document it has not planned yet.
- Off by default at zero, byte-identical against HEAD for the default build and
  all five archetypes, and a corpus with two rounds a period over two periods
  replays byte-identical from its recipe.

### The paperwork a company has, rather than the paperwork it produces

- **`worldloom.policies`**: every document in this corpus was *episodic*: a
  close ran, an incident happened, a return was filed. Measured on a
  twelve-period, eight-division build: 195 artifacts, of which 96 were the same
  type with a different division's name on it, and **not one was a policy**. An
  assistant asked "what is our expense approval threshold" or "how long do we
  keep contracts" had nothing to find, because the company had no rules.
  `--policies core|full` gives it ten: a delegation of authority, a code of
  conduct, business continuity, expense, travel, leave, remote work,
  information security, data retention, procurement.
- **A provision is a fact, not a sentence.** "Receipts above 90 need a
  manager's approval" is minted as a `CanonicalFact` with a number in it, so
  every question this repository can already ask of a figure (what is it, when
  did it change, which document says so) works on a policy unchanged. Forty-
  eight `policy.*` kinds are registered in `factkinds` like any other.
- **Scaled off revenue**, and rounded to a figure a policy would really name,
  so a 7.8bn retailer and a 2bn insurer do not share an expense limit. A
  delegation-of-authority ladder that stops climbing (two rungs a decimal place
  apart rounding to the same figure at a small enough company) is refused
  rather than clamped.
- **A revision is supersession.** The expense policy is the one revised entry
  in the shipped library: the earlier threshold's validity window closes, the
  later fact records what it superseded, *and the earlier document stays on the
  shelf* with the current one `supersedes`-ing it. Minting only the closed facts
  was not enough and the corpus said so: `evaluation.answerable` dropped the
  question about the old figure, correctly, and that drop is what found it.
- Dates are **clamped forward of whoever signs**, never back, which is
  `form_units`' rule about a unit and its leader.
  `validate.author_not_yet_employed` found the violation immediately: a
  superseded policy dated five years back signed by a controller who joined
  three years ago.
- **`documents.extends_outline`**: a third kind of compiler. One that builds
  its IR from nothing (a workbook, a thread) must have no outline beside it or
  the outline is dead data; one that *composes* the outline, as
  `policies._provisions` does by inserting a resolved provisions table, has an
  outline that is live. Marked on the function, because the two are the same
  callable shape, and `tests/test_doctypes.py` holds the line per-compiler so a
  from-scratch compiler that grew an outline by accident still fails.
- **`evaluation._Taxonomy.standing_documents`**: the questions an assistant is
  actually asked. Retail's set moves 30 → 44 with `--policies full`: eleven
  direct lookups whose wording is stated on the clause itself
  (`policies.Clause.asks`), one `authority_resolution` about who signed the
  rules, and one hard `temporal_state`: what the threshold was before the
  revision, where the current document is the confident wrong answer and only a
  validity window tells them apart.
- Registered at **package import**, not lazily from inside `build()`. It was
  lazy first, and `tests/test_doctypes.py` passed alone and failed in a full
  suite: `documents.declared_types()` returning two different answers depending
  on what had run before it, which is exactly the import-order determinism bug
  `register_artifact_types` warns about.
- Off by default: `applied(world, None)` returns the same object, every default
  build and all five registered archetypes are byte-identical, and a policy
  corpus replays byte-identical from its own recipe.

### The organisation is shaped like its management

- **`roles.from_shape`** dealt spine keys into levels in sorted-key order and
  gave each whichever parent the rotation reached, throwing away the reporting
  lines the engine's own table already declares. Retail's four Technology keys
  sort early and landed at depth 1 with enormous subtrees; its
  ServiceOperations keys sort late and landed at depth 2 with almost none. A
  420-person retailer came out **159 technologists to 14 service operators**:
  the function mix of the whole company decided by alphabetical order. It now
  reads 140 Finance, 128 Technology, 82 Merchandising, 42 Audit, 27
  ServiceOperations, 1 Executive.
- A spine key is placed at the depth its *own* manager chain implies, under
  that manager. `svc_desk` reports to `svc_lead` reports to `cio` again, and
  where a declared manager is not in the spine at all (`svc_lead` is in
  retail's shipped table and not in `SPINE`) the walk climbs to the nearest
  ancestor that is.
- A per-unit key is in no shipped table, so this function now states their
  structure: the division's MD reports to the chief executive and everyone else
  in the division reports to their MD, which makes **each division a subtree**.
  Deliberately not the dotted line the engines declare (retail's `_bp` reports
  to the group controller) because a synthesised organisation has one line per
  person and the one that makes a division legible is the solid one.
- A full manager pushes a report **down a level rather than refusing**. The
  chief executive takes the CFO, the CIO and one MD per division, so a span of
  three with four divisions cannot seat them all; an organisation whose top is
  wide adds a layer, it does not fail to exist. Widest span still never exceeds
  what the caller claimed.
- Every default build and all five registered archetypes are byte-identical:
  they use their engine's own table and never call this. A mosaic of three
  worlds validates clean, and a widened synthesised corpus replays
  byte-identical from its recipe.

### Somebody signed it

- **`ArtifactIntent.approver_id`**: every document in this corpus was authored
  and none of them was approved, which is not how a company works and, more to
  the point, is not how a company's *archive* works. "Who approved the March
  pack for Fuel and Convenience" is a question every real reader asks and no
  artifact here could answer. A signed document now carries an **Approval**
  block (prepared by, approved by, name, role and date) in Markdown, DOCX,
  PDF, PPTX and as a worksheet in XLSX.
- Measured on an eight-division retailer: **10 distinct people** named across
  the corpus before, **19** after. The divisional close commentary is the one
  approval that fans out with the company: widen a retailer to eight divisions
  and eight *different* managing directors sign eight different documents.
- Who signs what is a per-vertical table (`_APPROVED_BY` in each planner),
  because who signs a prudential return is an argument about banking. All four
  now have one: retail's close, banking's capital return, insurance's contested
  reserve position (the actuary's report over the CFO's signature, the CFO's
  margin memo over the actuary's), procurement's match exception.
- **Absence is a claim.** A ServiceNow ticket has an assignee, an email thread
  has a sender, a calendar is issued rather than approved, banking's RWA working
  paper is unsigned *because* it is the contested-authority distractor, and
  internal audit's review carries the Chief Internal Auditor's name and no
  countersignature at all. A corpus where everything is signed is as unlike a
  real archive as one where nothing is.
- **`validate.approvals`**: a signature has to be one somebody could have
  given: the approver exists, is not the author, and is permitted by the
  document's own access policy. It found two real defects the day it existed.
  Eight divisional MDs were signing finance-audience documents the policy would
  not have let them open, and the CEO was signing a technology-audience
  remediation review for the same reason; both policies now name them, the
  second as a rule (there is no restricted document a chief executive may not
  read) rather than as a patch.
- **Access follows the post.** A reorganisation moved a division's title
  without moving its access, so the corpus recorded a signature from somebody it
  also recorded as unable to open the document. `personnel.promote` now carries
  the post's access to whoever holds it, *added* and never substituted, because
  the archive is historical and the policy is current state, and striking a name
  off today would retroactively invalidate every signature that person ever
  gave. Measured: substituting produced five violations on a six-period history
  where appending produces none.
- A signature block is **furniture, not content**: fully resolved at plan time,
  no prose to write, identical in a document that said the opposite. So it costs
  the narration loop nothing and is exempt from the size-class component budget
  (`compose._FURNITURE`): counting it refused to compose a `meeting_minutes`
  that had not grown by a single sentence.
- Baseline retrieval moved 23 → 22 at @5, `numerical_comparison` 6/8 → 5/8. Two
  names and a date per document is more text to rank against and no more of the
  text a figure question wants, so the corpus got harder for a keyword baseline
  by getting more like a real archive. A signature block that made retrieval
  *easier* would mean the baseline was matching on furniture.
- No default moved that was not meant to: a corpus with no approvals renders
  exactly as it did, `validate.approvals` scores zero out of zero on it, and a
  signed corpus replays byte-identical from its own recipe.
- **And the corpus asks about it**, because a document property nobody asks
  about is decoration. Four cases per episode (`evaluation._Taxonomy.
  approvals`): who approved a group document, who approved *and* who prepared
  one division's commentary out of eight near-identical ones, and (the one
  that makes absence testable) who approved a document nobody signed, which
  must come back as an abstention. Retail's set moves 42 → 46,
  `authority_resolution` 3 → 6, `expected_abstention` 9 → 10. The keyword
  baseline passes none of the four, which is the intended result: a baseline
  that could tell an author from an approver would mean the two were not
  distinguishable in the first place. The byline is the trap: a document names
  its author at the top in larger type and its approver in a table at the foot,
  so a test pins that no expected answer is ever the author's name.

### A synthesised role reports to somebody who does its job

- **`roles.from_shape`** dealt each role's function by position in the tree and
  each role's manager by position in the level, and the two had nothing to do
  with each other. Measured on an eight-division retailer: **319 of 407**
  synthesised people (78%) reported across a function boundary. It produced a
  "Head of Audit" reporting to a Merchandising Systems Analyst and a "Head of
  Executive" reporting to a platform lead. Now 0 of 407.
- A role the synthesiser invented takes its **manager's** function. Inheritance
  rather than "pick a same-function parent", because choosing the parent by
  function unbalances the spans (a function with two managers at a level would
  take a third of the tree), and `measure`/`review` check the widest span
  against what the caller claimed, so a shape accepted yesterday would be
  refused today. The tree's shape is untouched reporting line for reporting
  line; only the labels move.
- Two exceptions keep `functions` a real knob. The root, or every role at depth
  1 inherits Executive and the company is one department. And a manager whose
  function the caller did *not* ask for: the spine's functions are the engine's
  and a caller's list may share nothing with them, in which case there is no
  coherent answer and the honest one is the rotation the caller chose. So
  `functions` stays the closed vocabulary for synthesised roles, exactly as
  documented, and coherence is what you get for asking for departments your
  engine has: which is what `company._functions_of` passes by default.
- Cosmetic until now; everything from here depends on it being right. Everything below the spine is
  about to author documents, and a one-to-one minuted between a finance manager
  and their audit-function manager is noise wearing a document's clothes.
- Left open at the time and closed above: `from_shape` still discarded the
  spine's own declared manager links, so which executives landed at depth 1
  decided the function mix. See *The organisation is shaped like its
  management*.

### The knob a corpus's size actually follows

- **`worldloom.divisions`**: widen a company past the divisions its archetype
  declares. Found by measurement: raising `organisation.headcount` from 23 to
  429 left facts at 8,021, artifacts at 204 and evaluation cases at 596:
  every one unchanged, because 429 people were still managing the same three
  divisions. The close fans out per division and per category, so the corpus
  follows the *structure* and `headcount` was never the knob. Widening the same
  retailer three → eight divisions took facts 604 → 990, artifacts 15 → 20 and
  questions 42 → 52 on one seed.
- Widening is additive. The declared divisions keep their names, categories,
  formats and *relative* sizes (64/21/15 stays in that ratio at any width),
  and only the shares renormalise, because a share is a fraction of group
  revenue and a fourth division has to take something from somebody. Each
  addition is sized against the smallest declared division and declines by 0.8
  from there: equal shares were the first rule and they gave Property a 12.5%
  share against General Merchandise's 7.9%, an adjacent business outweighing
  the core it was bolted onto.
- Pools are per industry and each entry is a real line of business rather than
  a relabelling: its own categories and estate, therefore its own row in every
  unit-level table, its own close commentary and its own questions. Retail
  offers five, banking three, insurance three. `divisions.register` adds a pool
  for a fourth vertical, and is refused on redefinition for `locales.register`'s
  reason. An industry with no pool is refused by name rather than served a
  division called `Division 4`.
- Refused rather than improvised in three places: narrowing below the
  archetype's own count (silently removing every fact, document and question a
  division owned), exhausting the pool (named with how many are available), and
  an unknown industry. Through `--spec` these arrive as an `organisation`
  conflict alongside whatever else the description got wrong.
- The width rides the **archetype key** (`omnichannel_retailer+8div`, composing
  with the vocabulary qualifier as `omnichannel_retailer+wholesale_club+8div`),
  for the reason `vocabulary.spoken` qualified its own key: the key is the only
  thing a recipe records about the shape, so a width carried anywhere else
  would rebuild a three-division company from an eight-division corpus and
  report success. A widened corpus replays byte-identical.
- No default moved: `widened(archetype, None)` returns the archetype itself, and
  every corpus built before this module exists is byte-identical after it.

### A benchmark an authored process gets for free

- **`worldloom.benchmark`**: evaluation cases derived from the fact graph
  rather than templated per vertical. An authored process produced **0**
  evaluation cases against the 11 per period its engine episode produces
  (measured twice, docs/episode-grammar.md), because every question shape lived
  in a per-vertical Python module the grammar cannot reach. A question shape
  turns out to be a shape in the graph: `direct_lookup` is a fact one artifact
  carries and nothing contests, `authority_resolution` is two or more artifacts
  citing different-authority facts about one subject, `temporal_state` is a
  window that closed, `causal_multi_hop` is a path in `caused_by`,
  `cross_artifact`/`numerical_comparison` are a declared `derive` or `sums-to`
  read against where its terms landed, and `citation_required` is a statement
  exactly one document makes.
- **`EpisodeSpec.evaluation`**: an `EvalSpec` for what cannot be derived:
  question phrasing per family and per kind, difficulty targets, which families
  a process wants emphasised, and the abstentions (a fact graph holds no witness
  to a fact's *absence*). Declared beside `detail_tables` and linted the same
  way: a family naming a fact kind the registry lacks is refused, as is a
  `str.format` slot the derivation never fills. `about` is a priority as well as
  a scope, and cannot conjure a case the corpus could not answer.
- **Measured.** `ProcureToPay`: 0 → **17 cases per period, 49 over three**,
  across all eight families, 11 of 17 graded hard. `QuarterlyCapitalReturn`,
  which authors *nothing* about evaluation: 0 → **14 per quarter across six
  families**, which is the "for free" claim unassisted. The four default engine
  builds at seed 8128 are byte-identical against `git archive HEAD`.

### A retriever anyone would deploy, and what it says about the corpus

- **`worldloom.evaluate.embedding`**: dense retrieval as a third ranking
  family, so a hardness claim no longer rests on two heuristics that share one
  idea. `RETRIEVERS` widened from classes to factories (`RetrieverFactory`), and
  that is the whole integration surface: `score()`'s grading still cannot ask
  which retriever produced the passages it is holding, which is what makes the
  comparison evidence rather than two tables printed together.
- **Optional and absent-friendly.** `pip install "worldloom[embeddings]"`.
  Without it, `--retriever all` skips the dense column with a message and still
  reports the lexical pair; `--retriever embedding` says what to install and
  exits nonzero. Never a traceback, never a silent zero.
- **Deterministic, which for an embedding model is not free.** Pins carry a
  model id *and a commit revision*; every vector (passages and questions) is
  cached to a sidecar keyed by `content_key(model, revision, scheme, text)`;
  cached vectors are L2-normalised `int8` and scoring is an integer dot product,
  so the cosine is bit-identical on any machine holding the same cache. A corpus
  that carries its cache is scored **with no model installed at all**, which is
  the generation ledger's argument applied to a retriever.
- **`worldloom evaluate --retriever all`** and `tools/measure_retrievers.py`
  print a new per-family reading: *genuinely hard*, *lexical trap*, *semantic
  blind spot*, *solved by everything*. `--retriever both` is unchanged: still
  exactly BM25 against TF-IDF, same console text, same JSON.
- **Measured, on the reference narration and a five-world mosaic.**
  `expected_abstention` and `temporal_state` are hard for everything (0/96 and
  0/30 lexical; 0/96 and 5/30 semantic, and those five are one question passed
  for the wrong reason). `authority_resolution` moves 0/30 → 8/30, still
  failing, but part of what BM25 was failing on was vocabulary, not authority.
  **No family turned out to be a pure lexical trap**, which is the result the
  corpus wanted and the first time it has been shown rather than assumed.

### Selection on outcomes, and what it actually bought

- **`worldloom.outcomes`**: the loop this repository described and never ran:
  generate candidates, **measure the corpora**, select on the measurements.
  `mosaic` disperses in parameter space, which is a proxy it never checked;
  this points the same `dispersion.farthest_first` at a measurement vector
  built from the instruments that already existed (`Built.measure`,
  `stats.measure`, `stats.compute`, the evaluation family and difficulty mix)
  plus a pairwise question-overlap term. Reachable as
  `sdk.outcome_selected(candidates, n)` and `mosaic.outcome_field(n, pool=30)`.
  `mosaic.field` and `worldloom mosaic -n 5` are byte-for-byte unchanged.
- **The Goodhart line is in the code, not only in the prose.** `select()`
  optimises *spread*, has no model of a good corpus, and provably never touches
  a retriever: `tests/test_outcomes.py` replaces the scorer with something that
  raises and requires the default path not to notice. Selecting against one
  baseline is a separate method (`Pool.hardest`), takes the retriever's name,
  and warns at the call.
- **Measured against parameter dispersion, and the result is mixed.** Same
  candidate pool, same size, both arms narrated and surveyed with
  `evaluate.across` (`tools/outcome_selection.py`). On retail at n=5 and n=8,
  outcome selection reliably wins distinct question strings (124 → 147),
  distinct (question, answer) pairs (145 → 169), cross-world near-duplicate
  *rate* (0.0050 → 0.0042), families showing any spread (3 → 5) and failure
  concentration (0.33 → 0.24); it reliably **loses** raw cross-world duplicate
  pair counts (it prefers denser corpora and that count is quadratic in
  questions per world), and it consistently halves the abstention-floor
  transplants that change a verdict (16 → 9), which is less transfer stress,
  not more. On banking and insurance every row ties: those evaluation
  generators emit the same 16 and 9 question strings in every world, so no
  selector can move anything, which is a finding about the generators rather
  than about the selector. The win is real, partial, and retail-only.
- **The objective's one free parameter changed nothing.** Selection was
  identical at question weights 0, 0.5, 1 and 2 on a thirty-candidate retail
  pool (the metric block decided it), so the win is not an artifact of a term
  that mimics the metric being reported.
- **Cost.** A pool of thirty retail candidates measures in 4–5 s (≈0.15 s each,
  no narration, no render, nothing on disk), against 0.07 s to disperse the
  same candidates on parameters alone. Banking and insurance are ≈0.03 s per
  candidate.

### Fixed

- `sdk.mosaic_of` dropped the vocabulary a mosaic dealt, so its blueprints
  rebuilt worlds the mosaic never planned. `Blueprint.speaking()` and
  `Blueprint.vocabulary_name` carry it; an empty vocabulary is byte-identical
  to before.
- Blueprints from `sdk.mosaic_of(n, engine="banking"|"insurance")` raised
  `TypeError` on `build()`: `Variant` always carries a calendar, including for
  engines that read none, and the bridge passed it to a world spec with no such
  field. Latent because the existing test counted blueprints without building
  one.
- `Built.measure()` and `Built.topology()` were a second copy of
  `outcomes.shape_vector`'s walk; they now delegate to it.

### The foundation

One coherent enterprise, taken all the way through. Two, in fact.

### The tool

- **Deterministic worlds from a seed.** `worldloom build --seed 8128` generates
  an organisation, its people, systems, services, categories and store estate, a
  month-end close with an optional operational incident, the documents that
  episode warrants, and an evaluation set over all of it. The same seed produces
  the same corpus, byte for byte.
- **Two industry verticals.** The retail month-end close is the default;
  `--archetype midsize_adi` builds a fictional bank and runs the quarterly
  capital-return episode instead: challenged by the second line before
  lodgement, filed anyway under a lodgement norm, invalidated by a
  reconciliation break the daily liquidity cadence catches, and corrected by a
  *restatement* that leaves the original filing on the record. Both lodgements
  carry the same authority, so only the restatement relationship and fact
  validity can say which figure is current, and the evaluation set asks
  that, paired with its temporal inverse so no retrieval bias answers
  both. Banking adds zero fields to the core model: its validator checks,
  artifact types, and archetype arrive through registration seams any future
  vertical can use.
- **Seven output formats.** XLSX with live formulas, named ranges, and hidden
  lineage and reconciliation sheets; DOCX, PPTX, and native PDF; Markdown; and
  portable Jira, Confluence, and ServiceNow bundles. All projections of one
  resolved intermediate representation, so no two formats of a document can
  disagree.
- **Three agent handshakes.** `worldloom plan` lets a model propose each
  document's structure under grammar validation; `worldloom narrate` hands out
  bounded prose requests and rejects any response that restates a figure, cites
  an unavailable fact, or invents an entity; `worldloom act` runs the incident
  as employees making one validated tool call at a time, each seeing only what
  that employee could see.
- **Actor simulation (A0–A5).** Role-scoped observations with an epistemic
  ledger of who knew what and when; policies and decision rights enforced by
  typed tools rather than prompts; an event-driven scheduler with bounded
  episodes; an execution ledger recording every call, including the refused
  ones.
- **Evaluation as a product surface.** `worldloom evaluate` scores an in-repo
  baseline retriever per question family (direct, cross-artifact, numerical,
  causal, temporal, authority, abstention) so corpus hardness is measured, not
  asserted. `worldloom diversity` fingerprints document structure so a batch
  cannot quietly become one document photocopied.
- **Complete replay.** Every generative call (prose, plans, actor decisions)
  is content-addressed into a generation ledger that ships with the corpus.
  `--replay` regenerates byte-identically with no provider reachable, and CI
  proves it on every push, from the installed wheel as well as the checkout.

- **The communications fan-out.** Episodes publish their long tail: meeting
  minutes for the decisions that were taken in a room (the escalation that
  moved the retail close; the banking meeting that approved the return with
  the challenge on the table), email threads whose every message knows only
  what its sender knew at that moment, and per-unit close commentary from
  each division's finance partner. Minutes are fully structured (attendees,
  tabled material, decisions) and cost the narration loop nothing; threads
  and commentary are prose under the same fact constraints as everything
  else. New evaluation families ask who was in the room and who was told
  what, when.

- **Industry packs.** A world's shape and lore as a JSON file an agent (or a
  person) authors: units, product categories, site estate, scale, dated lore
  commitments in the engine's closed constraint vocabulary, and the fictional
  company's name: run through either engine, with the episode physics staying
  the engine's. `worldloom pack template` starts one, `pack targets` publishes
  which lore each engine actually consults, `pack check` lints inert
  commitments by name, and `build --pack` builds it. The pack embeds in the
  corpus recipe, so a pack-built corpus rebuilds itself with no pack file.
  Packs also own their texture: ``system_brands`` renames the engine's
  systems for the industry, and ``voices`` re-voices any role's prose:
  applied as per-role persona clones, so a voiced CFO never re-voices
  everyone sharing the CFO's register, and numeric temperament stays the
  engine's. Each engine publishes its slots and role keys through
  ``worldloom pack targets``, and the lint names unknown keys.
  Packs also re-voice the episode itself: every event sentence and prose
  fact an engine states is a keyed template (``worldloom pack texts``), and
  ``episode_text`` overrides them: slot-checked, riding the recipe, over
  causality a pack cannot touch. The insurer's incident is about claims and
  peril codes; the mutual bank's challenge names its own book.
  Shipped references: a general insurer on the close engine and a mutual bank
  on the challenged-return engine, both exercised in tests. Authoring the
  first packs surfaced and fixed three archetype-coupling leaks the telco
  experiment had predicted (`unit_gm`, the merch lead's manager, and the
  banking error's unit), each engine now derives those from the world it was
  given.
  And packs re-voice the benchmark: every evaluation question and authored
  answer is a keyed template too (``EVAL_TEXT``, published beside the episode
  tables by ``pack texts``), overridden through ``evaluation_text`` under the
  same slot contract: the insurer's evaluation set asks about classes of
  business and gross written premium, never a merchandise category. The fact
  each case is graded against stays the engine's.

- **Consecutive banking quarters.** `--periods` now works for single-episode
  domains, stepping by the domain's own cadence (`period_step_months`;
  banking registers 3, so two periods are two quarter-ends). Each quarter
  runs the full challenged-return episode on the world the last one left:
  the standard's minimum-CET1 floor is minted once and reused as the
  standing fact it is, each quarter's liquidity cadence is its own
  supersession chain (gaplessness is enforced inside a chain, never across
  the deliberate gap between windows), and the capital reconciliation checks
  scope to their own period. A two-quarter corpus validates coherent and
  replays byte-for-byte.

- **A third vertical: insurance reserving, increment 1.** "The Living
  Estimate": a mid-size general insurer's quarterly reserving cycle, from
  the decided design record (`docs/design/insurance-reserving.md`): the
  development triangle as append-only observations, estimate chains whose
  superseded links were correct when made, and the estate's first permanent
  two-authority record: the actuarial central estimate and the booked
  reserve legitimately disagree, reconciled only by an explicit margin fact.
  Landing it triggered the rule of three: recipe steps are now a registry
  (`recipe.register_step`) each vertical seeds from its own module, and two
  thin-waist exceptions were paid down rather than a third added.

- **Repetition measured; the rewrite loop deleted before release.** Narration
  is open-loop (every section gets one request and one attempt, and nothing
  afterwards looks at what the corpus became), and a refinement loop
  (`worldloom refine`, MCP rewrite tools, a skill and a Stop hook) was built to
  close it: measure what repeats, rewrite only what repeats, gate each rewrite
  on the measured similarity. It was deleted before release, on evidence. The
  loop was built and gated against `DeterministicProvider` template prose,
  where three closes from one template genuinely repeat; a five-world proof run
  on real model prose measured its target (passages in a near-duplicate group)
  at zero in every world (0/46, 0/50, 0/52, 0/46, 0/43). The repetition it
  fought was an artifact of the deterministic fake, and its API adapters were
  the only code violating "this repository does not call a language model".

  What ships is the measurement, which is worth having about any corpus
  whoever narrated it: `stats.measure` runs the exact similarity join over the
  corpus's own passages beside a structural shape census, `worldloom diversity
  --near-duplicates` names the groups, and `worldloom mcp` serves the
  read-only tools (`measure_corpus`, `corpus_topology`, `corpus_series`,
  `validate_corpus`, and the probe tools) over stdio, with `.mcp.json` wiring
  them into any MCP client. No MCP tool writes a corpus; every corpus write path
  stays behind the CLI handshakes.

  Also fixed: `World.export` copied artifacts twice on an in-place export of a
  corpus that had been rendered, raising `FileExistsError` on a corpus that was
  perfectly intact. It had never fired because the only in-place callers ran on
  corpora with no `artifacts/` directory yet, and fixing it revealed a second,
  older defect it had been masking. CI's agent-handshake step submits
  deliberately invalid prose to prove the guardrail rejects it, and had been
  doing so against an already-narrated corpus: `review()` had nothing to review,
  the responses were never looked at, and the step passed only because that
  `FileExistsError` made the command exit non-zero. The guardrail the step is
  named for had not been exercised since rendering was added to it. `narrate
  accept` now refuses responses submitted into a corpus with no section awaiting
  prose, instead of printing "0 section(s) accepted" and exiting zero, and the
  CI step runs its rejection first, while sections are genuinely pending.

- **The estate becomes a landscape.** `worldloom topology` on the largest world
  this tool builds reported **nine** services and systems and a three-hop
  dependency chain: because nine is exactly what the month-end-close episode
  names. Categories scale with the archetype, sites scale, facts scale; the
  estate did not, which made blast radius meaningless, gave "who gets paged" a
  single answer, and left the incident's stale mapping table reading as bad
  luck rather than as the kind of thing sitting in every estate of that size.
  `build --estate small|medium|large` grows the rest of the landscape around
  the episode's own services: layered (edge → domain → platform → data →
  system of record) so acyclicity is *unconstructible* rather than merely
  checked, with chokepoints **placed**: each backed by a store only it may
  reach, because a shared service whose dependencies everything else can also
  reach directly dominates nothing. 101 nodes, a ten-hop chain, and the close
  orchestrator finally has a blast radius. The episode's four services are
  never edited, so its causality is bit-for-bit unchanged, and omitting the
  flag leaves every existing corpus byte-identical.

- **`worldloom compose`: the third handshake, and the first over entities.**
  `narrate` bounds what a model may *say* and checks it against the fact
  ledger; `plan` bounds how it may *shape* a document and checks it against a
  component grammar. This bounds what the company *runs* (services, systems,
  ownership, dependencies, declared criticality, and the lore explaining why
  the landscape looks that way) and checks it against `worldloom.graphs`. The
  graph library built for other reasons turned out to be exactly the validator
  that judgement needs.

  It exists because the generated estate cannot serve every vertical: its
  name pools are retail's, banking's landscape is not called
  `click-collect-api`, and the insurer ships with no services at all. A pool
  per industry is the wrong answer: it puts an ever-growing list of invented
  names into the engine, the contamination §7 forbids. An industry's
  vocabulary is the thing a model is genuinely better at than a table, so the
  model brings it and the harness refuses anything incoherent: a cycle through
  any number of hops, a dependency resolving to nothing, an owner who does not
  work here, a tier the graph contradicts, lore that constrains nothing, and
  an estate in which nothing is a single point of failure. Every violation is
  reported at once, nothing commits unless everything passes, and the accepted
  composition lands in the generation ledger, so a composed corpus rebuilds
  from its own recipe with no provider reachable, and refuses loudly rather
  than quietly rebuilding into the *un*composed world if its ledger is
  missing.

- **The world as graphs, and the defects only a graph could see.**
  `worldloom.graphs` reads the four graphs the schema always had and nothing
  ever looked at: the service/system dependency graph, the artifact provenance
  DAG across all four relationships at once, the fact supersession forest, and
  the reporting tree. It closed three real invariant gaps corpus-wide, for
  every vertical at the same time: a dependency cycle through more than one
  hop (the old check caught a service that depended on *itself* and nothing
  longer), a **forked supersession chain** (two facts replacing one, which
  leaves "what is current" ambiguous; the fact-layer walk built a dict keyed on
  the superseded id and let the second writer win, so this could never
  surface), and a provenance loop that uses a different relationship on each
  edge. `worldloom topology` is the reading: services ranked by *blast radius*
  and separately by *gates*: how much has no second path to what they serve,
  computed from dominator trees, because "lots of things depend on it" and
  "nothing routes around it" are different properties and a replicated platform
  has the first without the second. Every measure is an exact integer count
  with ties broken on id; there is no centrality score anywhere in it, because
  ranking by a float from an iterative solver is an argmax a different SciPy
  build can flip, and a rank that moves between machines is not a rank.

- **Near-duplicate detection that survives Gate 1.** `stats` has always
  reported an exact near-duplicate rate over passages, computed by comparing
  every pair, defensible at 120 artifacts and uncomputable at the 10,000
  build-order §12 targets, which is to say it would have stopped working on
  exactly the corpora whose repetition most needs auditing. `worldloom.similarity`
  keeps the *answer* and changes the algorithm: a prefix-filtered similarity
  join returns precisely the pairs a full scan would and provably misses none.
  Measured at 158× on corpus-shaped input, and pinned against brute force over
  randomised inputs rather than a fixture, because an off-by-one in a prefix
  bound is the only interesting way it can be wrong. `diversity
  --near-duplicates` turns the rate into a finding: *which* documents are one
  template, named. MinHash and banded LSH ship alongside for the regime past
  the exact one, labelled approximate and able to state the recall their band
  configuration implies.

- **Batch diversity, not just per-artifact.** `compiler.diversity.select` picks
  the *k* most-unlike alternatives for one artifact and is silent about the
  batch: run independently for a hundred artifacts it hands every one of them
  index 0, which is how §7a's measured defect (120 artifacts, 11 distinct
  shapes) is produced in the first place. `assign` spreads shapes *across* a
  batch, carrying what earlier periods already spent so period two does not
  reproduce period one; `collisions` names which artifacts share a shape rather
  than counting how many shapes there were.

- **Time series behind the figures.** `worldloom.series` decomposes a
  period-keyed fact series into trend, season and residual, and names the
  periods the first two do not explain: read it as a corpus check, since an
  incident month that does *not* sit outside the pattern is a corpus asserting
  a disruption its own numbers do not show. Outliers are scored on median
  absolute deviation rather than a z-score, because outliers inflate the
  standard deviation they would be measured against and several of them mask
  each other; the decomposition refits once with the first pass's outliers
  replaced by what it expected, so one spike cannot tilt the trend every other
  month is then judged against. Two defects found by its own tests and fixed
  in the algorithm rather than the assertion: a local (Hampel) filter mistakes
  a genuine seasonal peak for a spike, and a robust scale of zero (routine
  when more than half a sample is identical, which generated figures often are)
  silently disabled the detector on exactly the obvious cases.

- **`build --trend`.** Monthly compound growth behind the comparative history.
  Without it a year of comparatives oscillates around a flat level, so a
  seasonally-adjusted series is flat by construction and no question about
  direction has an answer in the data. 0.0 multiplies by exactly 1.0 (an IEEE
  identity), so every existing corpus is byte-identical, asserted rather than
  reasoned about.

- **Two retrievers, so hardness claims survive a change of heuristic.**
  `evaluate --retriever {bm25,tfidf,both}`: the existing baseline was
  already BM25, so the second family is TF-IDF cosine with shared
  tokenization, and the scorecard reports per-family agreement: a family
  hard under both ranking families is structurally hard. On the shipped
  corpora, every designed-hard family is. `worldloom stats` reports what a
  buyer can recompute: length distributions, vocabulary, exact
  near-duplicate rates, fact-citation density: no invented benchmarks.

- **Name pools and locale as pack data** (ladder rung 4). Person names,
  site regions, and headquarters are engine defaults a pack may replace,
  linted against the archetype's headcount, riding the recipe. Found and
  fixed en route: financial facts stamped AUD units regardless of the
  company's declared currency, in three generators. The insurer example is
  no longer Australian, and proves it byte-reproducibly.

- **Narration at scale, without an API caller.** There is no `narrate auto`
  and no model-SDK extra: an in-process API path (two model providers, and two
  agent-harness adapters) was built and then deleted before release, because
  the product is driven by a coding harness through the `narrate requests` /
  `narrate accept` handshake and the SDK: an API caller was a second writer
  path this repository's first line says it does not have. What ships from
  that work is the scale machinery in `narrative/compiler.py`, which any
  provider benefits from: `narrate(concurrency=N)` fans sections out with
  byte-identical output at any worker count (section fate and ledger order are
  decided before a thread runs), `preflight` counts the work before the first
  call, and the `on_accepted` seam hands each accepted section out as it
  lands so a long-running caller can persist paid work incrementally.

- **A benchmark that scales with the world.** `build --eval-density
  {low,standard,high}` grows the evaluation set and the fan-out layer from
  what the world already has (more categories and sites feed lookups and
  comparisons, more periods feed temporal and recurrence cases), reachability-
  gated like every existing case, with the default byte-identical to before.
  A three-period high-density grocery build carries `168` cases against `44`,
  and its hard families still score near zero, which is the point.

- **The haystack.** `build --distractors <n>` adds provenance-true noise:
  superseded drafts, derived personal copies, and routine notices: real
  authors, real lineage, real dates, citing only subsets of facts real
  documents already carry. No new facts means grading stays safe by
  construction: a distractor can never become the only home of an answer or
  make an abstention question answerable. Off by default; rides the recipe.

- **`/worldloom-design`.** The command for asks that arrive without a seed,
  such as "a hard corpus for insurance RAG": driving elicit → decide engine/pack →
  build → measure (`evaluate --json`, `diversity`) → iterate → deliver, with
  `references/designing.md` carrying the judgment: the elicitation table,
  the archetype / `--inspired-by` / pack cost ladder, symptom-level
  weak-family diagnostics, and the corpus-card delivery format.

### Generation

- The fan-out documents change what every seed generates: a corpus built
  before this release will not regenerate byte-identically under it (new
  artifacts, new evaluation cases, and category/site names admitted to the
  narrative entity check). Corpora built earlier remain loadable and
  validatable; regenerate from the seed to adopt the new layer.

### Packaging

- Installable with `pip install worldloom`; renderers with optional
  dependencies are extras (`worldloom[xlsx]`, `[docx]`, `[pdf]`, `[pptx]`, or
  `[all]`), and a missing extra fails with the exact install command rather
  than a traceback.
- The golden retail-close corpus ships inside the package:
  `worldloom demo retail-close` works with no network and no checkout.
- Generated corpora record the worldloom version that made them, and the CLI
  warns when a corpus is advanced under a different release.
- Typed (`py.typed`), Apache-2.0, Python 3.11–3.13.
