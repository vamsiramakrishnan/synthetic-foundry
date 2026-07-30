# Build order

Worldloom is not built subsystem by subsystem. It is built as one complete, falsifiable enterprise episode, made useful for evaluation, and then handcrafted parts are replaced with reusable generators.

```
Truth model
→ Golden enterprise episode
→ Evaluation corpus
→ Deterministic generation
→ Artifact projections
→ Constrained LLM narrative
→ Second industry
→ World generation
→ Socratic composition
→ Bounded fan-out
→ Enterprise mess
→ Scale
→ External publishers
```

The first executable is not:

```bash
worldloom interview
```

It is:

```bash
worldloom demo retail-close
```

That command produces one small but completely coherent corpus that proves the product thesis. The interview is the most demonstrable feature and the least load-bearing; building it first lets prompt behaviour anchor the architecture.

---

## 0. Define the thin waist

Before generators, prompts, renderers, or plugins, define the objects every subsystem must use.

```
World
Event
Fact
Persona
ArtifactIntent
ArtifactIR
EvaluationCase
GenerationLedger
```

The critical data flow:

```
World
  ↓
Events
  ↓
Canonical facts
  ↓
Artifact intents
  ↓
Artifact IR
  ├── XLSX
  ├── DOCX
  ├── PPTX
  ├── PDF
  ├── Jira
  ├── Confluence
  └── ServiceNow
```

The LLM does not sit at the centre. It is one compiler stage:

```
Canonical facts
      ↓
Narrative request
      ↓
Supported claims
      ↓
Prose
```

Foundational models:

```
WorldSnapshot
EnterpriseEvent
CanonicalFact
LoreCommitment
Persona
ArtifactIntent
ArtifactIR
ArtifactManifest
EvaluationCase
AccessPolicy
IntentionalError
GenerationLedgerEntry
```

**Persona is in the thin waist** because "who wrote this, and could they have known it" is load-bearing for the temporal and authority questions at step 11 — and because `NarrativeRequest` at step 6 takes a persona, so the concept is required either way.

**The generation ledger is in the thin waist**, not an implementation detail of the LLM client. Reproducibility is the product's central promise, and a world must *ship* with its ledger for a corpus to be citable. As a cache it belongs to a provider; as a thin-waist object it belongs to the artifact you hand someone. See [the ledger contract](generation-model.md#2-every-generative-call-is-recorded-so-worlds-replay).

Do not begin with a generic plugin system, scenario DSL, graph database, multi-agent framework, or orchestration engine.

---

## 1. Hand-author one golden enterprise episode

One fictional retailer, one bounded operating episode.

### The episode

A fictional omnichannel retailer is completing its March month-end close. During the close:

- Revenue is below budget.
- Online conversion is below forecast.
- Gross margin is affected by promotional activity.
- An inventory valuation pipeline fails.
- Finance delays final close by one business day.
- Service operations opens an incident.
- Engineering identifies stale product hierarchy data.
- Remediation tickets are created.
- The CFO receives a variance report.
- The executive committee receives a short summary.

### Initial corpus

Hand-author:

| Quantity | Item |
| --- | --- |
| 1 | company |
| 3 | business units |
| 20 | employees |
| 5 | systems |
| 4 | services |
| 2 | cost centres |
| 1 | reporting period |
| 3–5 | lore commitments |
| 50–60 | canonical facts |
| 10–15 | events |
| 8–12 | artifacts |
| 20–30 | evaluation questions |

Initial artifacts:

```
month-end-model.xlsx
finance-close-notes.md
service-now-incident.json
jira-remediation.json
cfo-summary.md
artifact-manifest.jsonl
lore.jsonl
facts.jsonl
events.jsonl
evals.jsonl
```

**At this point, do not use an LLM.** The static fixture establishes the product contract without allowing prompt behaviour to determine the architecture.

### Two fixture requirements

**Write some evaluation questions before the corpus.** Authoring questions after the corpus guarantees they are answerable by it — the interesting failure modes get selected out. Write a subset first, especially the expected-abstention cases, so the corpus is built against questions rather than the reverse.

**Include a supersession chain in the facts.** Not a flat list: an initial hypothesis, its supersession, and a confirmed cause, with distinct validity and authority states. Supersession is the hardest part of the schema and the most likely to be wrong, so it must be exercised by the fixture rather than deferred to step 3.

The fact count is driven by what the episode has to prove, not by a target. Reconciling revenue, gross profit, and margin at both unit and group level, while also carrying a supersession chain, lands around 55.

### Lore, minimally

The episode says engineering identifies stale product hierarchy data. On its own that is an unexplained coincidence. Three or four lore commitments make it a consequence — a 2024 category restructure left a manual mapping table, ownership of it is ambiguous, and finance tolerates workarounds under close pressure. The [worked example](lore.md#worked-example-the-smallest-useful-lore) is exactly this episode.

The point at this step is the *mechanism*, not the volume. Lore feeds the org generator, the persona model, and the artifact planner; adding it once all three exist means touching all three. The full lore pack waits for step 8.

### Exit gate

The corpus must answer:

- Why was the month-end close delayed?
- Which business unit caused the largest revenue variance?
- What was the confirmed root cause of the inventory issue?
- Which document contains the initial hypothesis?
- Which remediation ticket addresses the underlying control failure?
- What did the executive summary omit?
- Which source was authoritative at the end of the reporting period?

Every answer must map to fact IDs, artifact IDs, event IDs, a temporal cut-off, and an authority state.

This release is already useful as a small enterprise-search and RAG benchmark.

---

## 2. Build the library kernel around the golden episode

The first library API loads, inspects, validates, and exports the handcrafted corpus.

```python
from worldloom import World

world = World.load("examples/retail-close")

world.validate()
world.summary()
world.facts()
world.events()
world.artifacts()
world.evaluations()

world.export("./dist/retail-close")
```

The CLI stays a thin wrapper:

```bash
worldloom demo retail-close
worldloom inspect dist/retail-close
worldloom validate dist/retail-close
worldloom evals export dist/retail-close
```

**Build now:** typed domain models · deterministic identifiers · JSONL and Parquet serialisation · artifact manifests · fact lineage · event lineage · basic access policies · corpus inspector · corpus validator · evaluation export · stable schema versions.

**Do not build now:** LLM provider integrations · Socratic questioning · dynamic scenario registration · direct Jira, Confluence, or ServiceNow APIs · multiple rendering themes · distributed generation.

### Exit gate

The corpus loads, queries, validates, round-trips, and exports without information loss.

---

## 3. Replace the handcrafted episode with deterministic generation

Once the static corpus contract is stable, replace its facts and events with generators — only the generators the retail-close episode requires.

**Organisation generator** — company · business units · finance team · engineering team · service operations team · reporting lines · cost-centre ownership.

**Financial generator** — budget · forecast · actuals · business-unit P&L · revenue variance · margin variance · operating expenditure variance.

**Operational generator** — data pipeline · inventory service · scheduled close job · incident detection · triage · recovery · root cause · remediation.

**Lore application** — the step-1 commitments now *drive* generation rather than sitting beside it: event likelihood, approval depth, persona traits, artifact density. This is the smallest test that the constraint vocabulary works.

### Event ledger

```
close started
→ inventory pipeline failed
→ data unavailable
→ incident opened
→ close delayed
→ workaround applied
→ financial report finalised
→ remediation work created
```

### Fact ledger

Facts are temporal and append-only.

```
08:15     inventory feed status = failed
09:10     initial cause = source-system outage
11:45     initial cause superseded
13:20     confirmed cause = stale hierarchy mapping
17:30     inventory valuation available
next day  close status = final
```

Do not mutate the initial hypothesis into the final answer. Preserve both, with different validity and authority states.

### API

```python
from worldloom import RetailWorld
from worldloom.scenarios import MonthEndClose

world = RetailWorld(seed=8128).build()

episode = world.run(
    MonthEndClose(
        period="2026-03",
        include_operational_incident=True,
    )
)
```

### Exit gate

The same seed produces the same IDs, entities, facts, events, financial values, artifact plan, and evaluation answers. Changing the seed alters the world while preserving every invariant.

**Structural equivalence, not byte equality.** The generator is not asked to reproduce the hand-authored fixture. Doing so would mean encoding arbitrary authored choices — that a particular person has a particular name — to satisfy a test, which corrupts the generator to flatter the fixture. The fixture stays frozen as the regression corpus and the stable benchmark. A generated world's equivalence is that it passes the same validator and answers the same exit-gate questions.

**A step-3 world carries intents, not manifest entries.** Bodies arrive with the renderers at step 5 and prose at step 6, so `ArtifactIntent` is the output here: the decision that a document should exist, its author, audience, and the facts it must be able to cite. Nothing has been rendered, so there is nothing for a manifest to describe.

**Generated worlds are clean corpora.** Deliberate imperfection is step 11, and introducing it here would make every coherence bug indistinguishable from a feature. The hand-authored episode demonstrates the realistic mode; the generator produces the clean one.

---

## 4. Make evaluation the first product surface

Evaluation is what makes a synthetic corpus measurable rather than merely impressive. Each scenario emits an evaluation specification alongside its facts.

```python
EvaluationCase(
    question="Why was the March close delayed?",
    expected_fact_ids=["FACT-0042", "FACT-0051"],
    required_artifact_ids=["ART-SNOW-001", "ART-RCA-001"],
    distractor_artifact_ids=["ART-STATUS-DRAFT-001"],
    temporal_cutoff="2026-04-02T18:00:00Z",
    evaluation_type="causal_multi_hop",
)
```

**Implement first:** direct lookup · cross-artifact lookup · numerical comparison · multi-hop causality · temporal state · authority resolution · expected abstention · required citation checking.

**Add later:** ACL-aware retrieval · chart interpretation · attachment traversal · contradiction resolution · partial visibility.

### Why this is early

A team can immediately generate a corpus, index it with their retrieval system, run questions, score answers and citations, and compare architectures. That is a complete product loop before polished PPTX or PDF generation exists.

### Ship a baseline retriever

[Gate B](#gate-b--utility) as stated depends on an external system, which makes the gate that proves utility impossible to verify on demand. Build a deliberately mediocre in-repo baseline — naive chunking, embedding search, no reranking — so Gate B is a test that can be run, and so regressions in corpus quality surface as score movement.

### Exit gate

Every evaluation case derives from canonical facts. No answer is independently invented by an LLM.

---

## 5. Build artifact projections in semantic order

Renderer order follows information authority, not visual appeal.

### 5.1 XLSX first

The financial workbook is a *source* artifact, and it introduces hard reconciliation constraints.

Sheets: Summary · Business Unit P&L · Budget vs Actual · Forecast vs Actual · Variance Drivers · Incident Impact · Actions · hidden Lineage · hidden Reconciliation.

Requirements: formulas remain formulas · totals reconcile · number formats are correct · named ranges are used · source fact IDs are recorded · workbook metadata identifies the synthetic world.

XLSX is more valuable here than PPTX because it makes numerical coherence testable.

### 5.2 Portable Jira, Confluence, and ServiceNow bundles

Not live APIs. Portable representations:

```
jira/
  projects.json
  issues.jsonl
  changelog.jsonl
  links.jsonl
confluence/
  spaces.json
  pages.jsonl
  comments.jsonl
  attachments.jsonl
servicenow/
  incident.parquet
  problem.parquet
  change_request.parquet
  cmdb_ci.parquet
  cmdb_rel_ci.parquet
```

These add workflows, ownership, status history, comments, page hierarchy, operational records, and cross-system links. Bundles are easier to test, diff, reproduce, and load into arbitrary systems.

### 5.3 DOCX next

The first rich narrative artifact: CFO variance memo · incident RCA · programme status report. One sober template. No general Office theme engine yet.

### 5.4 PPTX after DOCX

One concise executive deck — executive summary · financial performance · variance drivers · operational issue · remediation · decisions required — projected from the same facts as the workbook and memo.

### 5.5 PDF last

Derived from DOCX and PPTX. Do not create a parallel PDF narrative path; that is a second source of inconsistency with a schedule attached.

### Exit gate

A single run produces the XLSX source model, Jira bundle, Confluence bundle, ServiceNow bundle, DOCX memo, PPTX summary, PDF snapshot, and evaluation JSONL — all agreeing, because all compiled from the same fact ledger.

**Formulas are declared in the IR, not invented by a renderer.** *Which* cells are computed, and from what, is a semantic fact the compiler knows. So the IR carries `sum`, `difference`, `ratio_pct`, and `reference` declarations, and each renderer decides only how to spell them: XLSX emits `=SUM(C4:C6)`, Markdown emits the literal. Both agree because both read one declaration.

**The reconciliation sheet must compare against the ledger, not against itself.** Subtracting the P&L's group cell from a sum of the units is tautological when the group cell is itself `=SUM(units)` — it can never disagree, so it proves nothing. The check has to compare the computed sum against the value the fact ledger *states*. That is what makes it a check on the corpus rather than on the spreadsheet's own arithmetic.

**Test the formulas, not the file.** A spreadsheet library stores formulas without evaluating them, so a renderer can emit syntactically valid nonsense and every naive test still passes. The suite carries a small evaluator for the formula shapes the renderer is allowed to produce, and asserts each one resolves to the fact it came from. An unrecognised shape fails the evaluator rather than being skipped.

**Narrative artifacts render as outlines until step 6.** Sections and tables are resolved; `body` is `None`. That is the honest output before a narrative compiler exists, and it is [document outlining](generation-model.md#12-document-outlines) arriving early: prose is later written into a shape that is already correct, rather than inventing structure and data together.

---

## 6. Introduce the LLM as a constrained narrative compiler

Only after the deterministic path works. The first uses are narrow: CFO variance commentary · incident RCA narrative · executive summary · Jira issue description · Confluence meeting notes.

The LLM receives facts, not an open-ended request to invent a document.

```python
NarrativeRequest(
    artifact_type="cfo_variance_memo",
    persona="finance_business_partner",
    audience="group_cfo",
    temporal_cutoff="2026-04-02T18:00:00Z",
    allowed_fact_ids=[...],
    required_fact_ids=[...],
    forbidden_claims=[...],
    target_words=450,
)
```

Structured output is required:

```python
GeneratedNarrative(
    text="...",
    claims=[
        GeneratedClaim(
            text="Revenue finished 2.8% below budget.",
            supporting_fact_ids=["FACT-0091", "FACT-0092"],
        )
    ],
)
```

### Two complementary guards

**Reference substitution** stops literals from drifting: prose carries `{{fact:...}}` markers and the renderer substitutes from the ledger, so a deck and its source workbook read the same entry and neither holds a copy.

**Claim validation** catches unsupported *assertions*, which substitution cannot. "Revenue finished below budget" needs fact support even with no number in it.

Both are required. Neither subsumes the other.

### Validation loop

```
LLM prose
→ extract claims
→ validate numbers
→ validate dates
→ validate entity names
→ validate temporal availability
→ validate supporting facts
→ accept or retry
```

**Engineering requirements:** provider-neutral client · structured output · prompt versioning · response caching into the generation ledger · idempotency keys · deterministic fake provider · retry policy · cost accounting · claim validation · full provenance.

The deterministic fake provider is what makes the whole pipeline testable in CI without spend or flakiness. Build it first, not last.

### Exit gate

No generated numerical, temporal, or entity claim is accepted without fact support. The LLM may choose emphasis and wording. It may not choose reality.

---

## 7. Build a second vertical before generalising

The second implementation determines the architecture. The first only gives you an opinion.

Build a fictional IT-services company with a different economic engine.

### Scenario

A fixed-price client transformation programme experiences utilisation below plan · senior staffing shortage · subcontractor overspend · milestone delay · margin erosion · customer escalation · revised forecast · steering committee intervention.

### Artifacts

Deal economics XLSX · monthly margin report · account-plan Confluence pages · Jira delivery programme · ServiceNow production incident · customer escalation memo · steering committee PPTX · forecast revision · evaluation dataset.

### What this forces

| Retail | IT services |
| --- | --- |
| stores | delivery centres |
| inventory | billable capacity |
| sales and margin | utilisation and margin |
| suppliers | subcontractors |
| product categories | client accounts |
| fulfilment incidents | delivery milestones |

### The rule

Do not add industry-specific fields to the core `World` model. Use domain modules:

```
worldloom.core
worldloom.finance
worldloom.retail
worldloom.it_services
```

Extract a generic abstraction only after both implementations require it. Do not design a universal scenario DSL before this stage — before two verticals it encodes guesses rather than recurring structure.

### Exit gate

Both verticals share the fact ledger, event model, artifact IR, manifest, evaluation schema, renderer interfaces, and provenance system. Domain-specific economics stay outside the core.

---

## 8. Build config-driven world generation

Replace hand-authored company structures with archetype packs. Start with two:

```
large_omnichannel_retailer
global_it_services_provider
```

Each pack defines its economic model · organisational topology · entity distributions · technology landscape · service catalogue patterns · project types · operating calendar · financial metrics · event families · artifact preferences · persona families · terminology — and pairs with a [lore pack](lore.md#lore-packs) supplying the interrogation script, constraint vocabulary, and critics.

```python
world = (
    World.from_archetype("large_omnichannel_retailer")
    .with_seed(8128)
    .with_scale("large")
    .with_history(years=10)
    .build()
)
```

**Generate now:** fictional company name · business units · leadership roles · employees · teams · customers · vendors · products · services · systems · projects · cost centres · historical event skeleton · full lore graph · initial strategic tensions · stable personas.

**Do not generate yet:** arbitrary industry packs · self-authored scenario code · fully autonomous history · unlimited free-form organisational structures.

### Exit gate

A configuration file produces different coherent retailers and IT-services companies without changing application code.

---

## 9. Add the Socratic world composer

The interview comes after the target schema is proven. Its job is not to make the system generative — the system is already generative. Its job is to make world construction accessible, intentional, and differentiated.

```
User intent
→ structured interview
→ explicit assumptions
→ WorldSeed
→ validation
→ immutable seed
→ deterministic world generation
```

### What the interview determines

Company inspiration · fictionalisation policy · geography · scale · economic engine · operating model · historical scar tissue · current strategic tensions · technology maturity · information culture · governance model · evaluation objectives · corpus scale · artifact mix · noise profile.

### Division of labour

| LLM | Deterministic |
| --- | --- |
| Ask the next useful question | Validate the seed |
| Fill non-critical defaults | Assign identifiers |
| Generate plausible company names | Resolve dates |
| Propose backstory | Generate financial values |
| Generate strategic tensions | Construct organisational graphs |
| Resolve narrative gaps | Build the event timeline |
| Explain assumptions | Enforce scale and permissions |

**Required features:** interview replay · user overrides · answer provenance · confidence · assumption ledger · seed diff · seed freeze · structured outputs only.

### A naming note

Two different objects are easily confused, and they should not share a word:

| Term | Is |
| --- | --- |
| **seed** | An integer. `8128`. Drives seeded randomness |
| **WorldSeed** | The frozen priors document — identity, lore, strategy, org intent — produced by the interview or an archetype |

A world is reproduced from *both*, plus the generation ledger and generator version.

### Exit gate

The same interview transcript, model output cache, seed, and generator version reproduce the same world.

---

## 10. Add bounded fan-out and artifact recipes

Only now should the system support broad artifact generation.

```python
MonthEndReportRecipe(
    source_domains=[Ledger, Budget, Forecast, IncidentLedger],
    outputs=[Workbook, FinanceMemo, ExecutiveDeck, BoardPdf],
)
```

### Bounded fan-out

```
Event significance
+ regulatory impact
+ financial impact
+ audience
+ severity
+ organisational reach
→ artifact plan
```

A SEV-3 incident should not produce a board paper. A material financial restatement should.

### Size profiles

Semantic profiles, not token multipliers.

| Profile | A financial report contains |
| --- | --- |
| **small** | headline metrics · major variances · actions |
| **medium** | consolidated results · business-unit analysis · cash flow · forecast · risks |
| **long** | complete statements · detailed cost-centre appendices · control commentary · reconciliations |

### Lifecycle versions

```
draft → reviewed → approved → published → superseded → archived
```

### Derivation relationships

```
XLSX source model
→ DOCX commentary
→ PPTX executive summary
→ PDF board snapshot
```

### Exit gate

The system creates 1,000–10,000 artifacts without producing combinatorial nonsense.

---

## 11. Add enterprise mess only after clean coherence works

Two distinct modes:

```
clean corpus
realistic corpus
```

**Never debug deterministic defects and intentional inconsistencies simultaneously.** Without mode separation, every coherence bug is indistinguishable from a feature, and the validator cannot tell you which.

### 11.1 Temporal versions

Drafts · amendments · superseded pages · late updates · historical states.

### 11.2 Authority hierarchy

System of record · approved report · working document · unofficial note · initial hypothesis.

### 11.3 Permissions

Start with user ACL · group ACL · department ACL · project ACL · attachment inheritance · deny precedence.

Then add geography · legal entity · customer segregation · leadership-only material · audit restrictions.

### 11.4 Controlled noise

Stale status · missing field · duplicate issue · conflicting acronym · incomplete summary · political understatement · initial incorrect diagnosis · outdated owner · timezone discrepancy.

Every inconsistency carries a record:

```python
IntentionalError(
    artifact_id="ART-0042",
    error_type="incorrect_initial_hypothesis",
    observed_value="source ERP outage",
    canonical_value="stale hierarchy mapping",
    detectable=True,
)
```

### Exit gate

The system answers not only *what happened?* but *what was believed at the time, which source superseded it, who could see it, and what was eventually confirmed?*

That is where the corpus becomes genuinely useful for enterprise retrieval and agent evaluation.

---

## 12. Scale only after semantic stability

Do not optimise for a million artifacts while the meaning of an artifact is still changing.

**Gate 1 — 10,000 artifacts.** A single process supports deterministic generation · bounded memory · local filesystem · JSONL · Parquet · cached LLM responses · resumable stages.

**Gate 2 — 100,000 artifacts.** Add partitioned storage · streaming manifests · process pools · renderer workers · batch LLM calls · content-addressed artifacts · incremental validation · failure isolation.

**Gate 3 — 1,000,000 artifacts.** Only then consider distributed workers · queue-backed execution · remote object storage · metadata database · run coordination · workload partitioning · tenant isolation.

The default architecture stays local and library-first.

```python
run = (
    worldloom.run(config)
    .resume()
    .workers(8)
    .execute()
)
```

Do not begin with Kubernetes, Kafka, Temporal, Ray, or a microservice topology. A process-local pipeline with Parquet, DuckDB, object storage, and deterministic task keys travels much further than most teams expect.

---

## 13. Add plugins and external publishers last

Plugin APIs are extracted from real extension pressure, not designed speculatively.

```
Portable Jira bundle       → Jira Cloud publisher
Portable Confluence tree   → Confluence Cloud publisher
Portable ServiceNow tables → ServiceNow publisher
```

Then storage plugins · renderer plugins · archetype packs · scenario packs · artifact recipe packs · evaluation packs.

Public-company-grounded generation also belongs here, because it introduces source ingestion, licensing, citations, factual provenance, temporal freshness, and a public-fact versus synthetic-inference boundary. None of that should complicate the first coherent fictional world.

---

## Team topology

A five-to-seven-person team organises around the same vertical slice, not around isolated formats.

| Workstream | Owns |
| --- | --- |
| **Core and simulation** | World model · event ledger · fact ledger · lore · determinism |
| **Finance and scenarios** | Ledger · reporting · variances · scenario logic |
| **Artifact pipeline** | Artifact IR · XLSX · DOCX · PPTX · portable system bundles |
| **LLM and provenance** | Narrative compiler · claim validation · generation ledger · prompt registry |
| **Evaluation and quality** | Evaluation cases · validators · golden corpus · baseline retriever · corpus inspection |
| **Runtime and developer experience** | Storage · CLI · Python API · resume · parallelism |

Do not create independent "PPTX", "Jira", and "ServiceNow" teams. That recreates the exact silo problem Worldloom exists to solve — the org chart reproducing the product's own failure mode.

Every workstream continuously integrates against the same golden episode.

---

## The four release gates

### Gate A — Coherence

One enterprise episode is consistent across facts, events, systems, and artifacts. No accidental contradictions · no broken references · all financials reconcile · the same seed reproduces the corpus.

### Gate B — Utility

An external RAG or agent system ingests the corpus and runs grounded evaluations: questions · answers · required sources · distractors · citations · temporal cut-offs. The in-repo baseline retriever from step 4 makes this gate self-testable rather than dependent on a third party.

### Gate C — Generality

A second industry works without contaminating the core with industry-specific fields. Retail and IT services, same kernel, different domain packs.

### Gate D — Scale

The pipeline produces large corpora without changing semantics or losing reproducibility. 10K → 100K → 1M artifacts.

---

## What is deliberately postponed

A web UI · multi-agent world-building · autonomous scenario code generation · generic workflow orchestration · a graph database · direct SaaS publishing · twenty industry packs · multiple PPTX themes · OCR-heavy PDFs · distributed generation · a public marketplace · "generate any enterprise" prompts · meta-generation of generators.

These create surface area. They do not prove the product.

The core product is proven when one event travels through finance, operations, engineering, executive reporting, and evaluation without losing its identity or changing its truth.

---

Reduced to one line:

> Handcraft one coherent episode, encode its truth, make it evaluable, make it deterministic, render it broadly, add constrained language, prove a second domain, then add world-building, mess, and scale.
