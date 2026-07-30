# Worldloom

**Worldloom is to enterprise corpora what SQLite is to databases.**

A small, deterministic Python library that generates coherent synthetic enterprise worlds — organisations, people, projects, finances, systems, incidents, years of history — and materialises them into realistic documents, business system records, and knowledge artifacts for AI evaluation, retrieval, and agent testing.

No service to run. No configuration to write. No orchestration framework to adopt. A library, and a CLI that is a thin wrapper over it.

```python
from worldloom import World

world = (
    World()
    .inspired_by("woolworths")
    .fictionalise()
    .employees(80_000)
    .history(years=12)
    .simulate(months=24)
    .generate()
)

world.export("./demo", formats=["pptx", "xlsx", "docx", "jira", "confluence"])
```

> **Status: Gate A complete; renderers and the narrative compiler landing.** The builder chain above and DOCX/PPTX/PDF are still ahead. What runs today:
>
> ```bash
> pip install -e ".[xlsx]"
> worldloom demo retail-close                    # the hand-authored corpus, 1250 checks
> worldloom build --seed 8128 --incident --narrate \
>     -f xlsx -f markdown -f jira -f confluence -f servicenow \
>     --out ./dist/demo                          # generate, narrate, render, validate
> worldloom build --seed 8128 --incident --replay ./dist/demo \
>     -f xlsx -f markdown -f jira -f confluence -f servicenow \
>     --out ./dist/again                          # regenerate offline from the ledger
> ```
>
> Those last two commands produce **byte-identical corpora**, and the second makes no provider call at all. That is the determinism claim below, demonstrated rather than asserted — and CI diffs the two directories on every push.
>
> No provider ships. `--narrate` uses a deterministic fake, so the whole pipeline is exercised with no key, no network, and no spend; a real adapter is a thin wrapper over the same interface.
>
> Treat the rest of this README as the target API. The [roadmap](#roadmap) marks what is built; [`docs/build-order.md`](docs/build-order.md) is the sequence and the exit gate for each step.

---

## Why Worldloom?

Most synthetic data generators produce isolated documents.

- A Jira ticket is created independently from a Confluence page.
- A PowerPoint references projects that don't exist.
- A PDF reports financial numbers that cannot be reconciled.
- An incident has three different root causes depending on which document you read.

Real enterprises don't work this way. Every document, spreadsheet, presentation, ticket, approval, financial report, architecture decision, and postmortem is a consequence of people making decisions over time.

Worldloom generates the enterprise first. Documents are projections of that evolving world.

---

## Generate reality first. Render artifacts second.

Instead of prompting an LLM to write documents, Worldloom builds a coherent enterprise simulation and then renders it.

```
                  Enterprise World
                          │
                          ▼
                   Canonical Facts
                          │
                          ▼
                 Historical Events
                          │
                          ▼
                 Artifact Planning
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
  Documents         Business Systems       Reports
      │                   │                   │
      ▼                   ▼                   ▼
DOCX PPTX PDF      Jira ServiceNow     XLSX Confluence
```

Three rules follow from this, and they are not negotiable:

**Facts before prose.** LLMs write language. They do not invent truth. Every number, date, entity, and claim in a document is resolved from the fact ledger before a word is written.

This is a rule about *prose*, not about *priors*. What the company is — its industry, history, culture, the scar tissue that still shapes its decisions — is generated first, because no org graph, service catalogue, or financial model is decidable without it. Those priors are then frozen, and every later phase reads them and none may contradict them. Coherence comes from that single frozen source, not from constraining prose at the end. See [lore](docs/lore.md) and the [pipeline order](docs/generation-model.md#when-generation-happens).

**Simulation before rendering.** Events create facts. Facts create artifacts. Artifacts create files. Never the other way around.

**Lineage everywhere.** Every artifact knows its source world, scenario, events, supporting facts, author, audience, permissions, recipe, and version. Nothing is anonymous.

---

## The generation boundary

Worldloom has two engines, and the split between them is the most important design decision in the project.

The **deterministic engine** owns everything that must be *correct*. The **generative engine** owns everything that must be *plausible*. Nothing is owned by both.

| Deterministic | Generative |
| --- | --- |
| Entity identity and IDs | Names, brands, terminology |
| Referential integrity | Culture, politics, tone |
| The org graph and reporting lines | Team purpose and collaboration patterns |
| Arithmetic, aggregation, reconciliation | Financial commentary and explanation |
| The timeline and event ordering | Causes, consequences, lessons learned |
| Permissions and visibility | Audience and register |
| Which facts exist | What those facts mean |
| Which artifacts exist, and their provenance | Which artifacts would plausibly exist |
| Seeded randomness | Judgment |

Three rules enforce it:

**The LLM never does arithmetic.** It may reference a number; it may never restate one. Generated prose carries fact references, and the renderer substitutes values from the ledger at render time. This is the single rule that stops a board deck from disagreeing with the workbook it came from — both read the same entry, and neither holds a copy.

**Every generative call is recorded, so worlds replay.** Model calls aren't reproducible, so Worldloom doesn't depend on them being reproducible. Each call is content-addressed into the world's generation ledger, keyed by seed, call site, input facts, model, and prompt version. `from_seed()` replays the ledger instead of re-prompting — regeneration touches no model at all.

**The LLM never writes to the graph.** It proposes; the deterministic layer validates and commits, or rejects and retries with the violation fed back.

The full division — twenty areas of generation, what the model owns in each, and what stays behind the wall — is in **[docs/generation-model.md](docs/generation-model.md)**.

---

## The API

The design goal is a single sentence:

> A senior engineer should be able to discover and use Worldloom from autocomplete alone, without reading the documentation.

Everything below exists to serve that.

### One entry point

```python
from worldloom import World, Company, Scenario
```

Three names cover the public surface. No `worldloom.generators.world.builder.enterprise.company`.

Two ways to start, and only two:

```python
World()                  # build up from nothing
World.from_seed(8128)    # reconstruct an existing world exactly
```

### Immutable

Every builder and simulation method returns a new `World`. Nothing mutates in place.

```python
base = World().employees(50_000).history(years=12)

short = base.simulate(months=6)
long = base.simulate(months=36)

# base is untouched, and short is not derived from long
```

This is what makes worlds safe to fork, cache, compare, and pass around — the same property that makes Polars pleasant.

### Lazy

Building is free. Nothing expensive happens until you ask for something real.

```python
world = World().employees(50_000).history(years=12)   # instant, does no work
world = world.generate()                              # this is the expensive call
```

`.generate()` is the only method that costs real time. Everything before it is description.

### Build, then query

Construction is a builder chain. Interrogation is a fluent query, in the Polars idiom.

```python
(
    world
    .events()
    .where(kind="incident", severity="sev1")
    .render("rca")
)
```

`.where()` is the primitive — one filter mechanism, composable, keyword-based. The named collections below are shorthand for the common whole-set cases, not a second query language.

### Everything is inspectable

```python
world.people()
world.projects()
world.services()
world.products()
world.timeline()
world.events()
world.incidents()
world.artifacts()
```

Internal state is never hidden. If Worldloom knows it, you can read it.

Domain areas are attribute namespaces, so autocomplete reveals the model:

```python
world.finance.ledger()
world.finance.month_end()
world.engineering.projects()
world.operations.incidents()
world.people.org_chart()
```

### Every noun is a first-class object

Not `dict`. Not `Any`. Real typed models:

`Company` · `Employee` · `Project` · `Service` · `Product` · `Timeline` · `Scenario` · `Event` · `Incident` · `Artifact` · `Document` · `Workbook` · `Presentation` · `Budget` · `Report` · `BoardPack`

Every public method returns one of them, or a typed collection of them:

```python
world.people()             # -> EmployeeCollection
world.timeline()           # -> Timeline
world.finance.month_end()  # -> MonthEndReport
```

Never an anonymous dictionary.

### Dataframe interop

Collections convert without ceremony, so analysis happens in the tool you already use:

```python
world.people().to_polars()
world.finance.ledger().to_pandas()
world.events().to_arrow()
```

### Readable in a notebook

`repr()` is part of the API, not an afterthought.

```python
>>> world
World ─────────────────────────────────────
  Name          Southern Cross Retail
  Industry      Retail
  Employees     81,422
  History       2012–2026
  Artifacts     214,833
  Status        ✓ Generated
```

```python
>>> world.summary()
Southern Cross Retail
  Employees        81,422
  Projects            381
  Products            842
  Services            128
  Incidents           491
  Documents       214,833
  Presentations     4,212
  Workbooks         9,182
  Timeline        14 years
```

### First-class provenance

Lineage is queryable from any artifact, in both directions:

```python
artifact.sources()    # the facts that justify it
artifact.events()     # what happened to cause it
artifact.parents()    # what it was derived from
artifact.children()   # what was derived from it
```

### One obvious way

Five verbs, each meaning exactly one thing:

| Verb | Does | Returns |
| --- | --- | --- |
| `.simulate(...)` | Advances the world clock, producing events and facts | `World` |
| `.generate()` | Materialises the world and plans its artifacts | `World` |
| `.validate()` | Checks the world for coherence violations | `ValidationReport` |
| `.render(*formats)` | Turns planned artifacts into files and records | `Corpus` |
| `.export(path)` | Writes a corpus to disk | `Path` |

`world.export(path, formats=[...])` covers the 90% case by rendering and writing in one step. When you need precision, the long form composes from the same verbs:

```python
(
    world
    .artifacts()
    .where(domain="finance", year=2025)
    .render("xlsx", "pptx")
    .export("./demo")
)
```

There is no third way to do either.

### The CLI is a wrapper

The CLI adds no capability the library lacks, and no capability the library lacks is reachable from the CLI. It calls the same five verbs.

```bash
worldloom build --seed 8128 --out ./demo
```

---

## Recipes and scenarios

Artifacts are declared, not scripted — the dbt model of the problem. A recipe names its inputs and its outputs; the planner works out when it should fire and what it may see.

```python
from worldloom import artifact
from worldloom.finance import Ledger, Budget, Forecast
from worldloom.artifacts import Workbook, Report, BoardPack

@artifact.recipe
class MonthEndReport:
    sources = [Ledger, Budget, Forecast]
    outputs = [Workbook, Report, BoardPack]
```

Scenarios declare what an event does to a world — what it produces, across which systems.

```python
from worldloom import scenario
from worldloom.events import ServiceFailure
from worldloom.artifacts import Incident, Problem, RCA, ExecutiveUpdate, RemediationPlan

@scenario
class MajorIncident:
    trigger = ServiceFailure()
    produces = [Incident, Problem, RCA, ExecutiveUpdate, RemediationPlan]
```

These two decorators are the only ones in the library. Worldloom is not a decorator framework; `generate`, `render`, and `export` cover the ordinary path.

From that single scenario, one production incident fans out into a mutually consistent record:

```
Major Incident
        │
        ▼
ServiceNow Incident
        │
        ├───────────────┐
        ▼               ▼
   Jira Bug     Incident Timeline
        │               │
        ▼               ▼
Engineering RCA   Executive Update
        │               │
        ├───────────────┐
        ▼               ▼
 Knowledge Base    Audit Evidence
```

Every artifact agrees on timestamps, systems, services, financial impact, root cause, and ownership — unless the disagreement is intentional.

---

## What Worldloom generates

| Domain | Artifacts |
| --- | --- |
| **Strategy** | Executive memos · board papers · steering committee decks · quarterly business reviews · investment proposals |
| **Finance** | Month-end workbooks · management reports · budget packs · forecasts · variance analysis · cash-flow reports |
| **Engineering** | PRDs · BRDs · technical designs · ADRs · runbooks · test plans · incident RCAs |
| **Delivery** | Programme plans · RAID logs · meeting minutes · change requests · dependency maps |
| **Operations** | ServiceNow records · knowledge articles · SOPs · change approvals |
| **Customer** | Account plans · proposals · statements of work · QBRs |
| **People** | Workforce plans · hiring plans · policies · training material |

Rendered natively to **XLSX**, **PPTX**, **DOCX**, **PDF**, **Confluence**, **Jira**, and **ServiceNow**. Renderers are plugins; adding one never touches the world model.

---

## Worlds inspired by real enterprises

Generate an organisation with the shape of a real one, without reproducing anything proprietary.

```python
World().inspired_by("woolworths").fictionalise()
# -> Southern Cross Retail Group

World().inspired_by("a global IT services company").fictionalise()
# -> Meridian Global Services
```

Preserved: industry characteristics, operating complexity, scale, economic model.
Invented: employees, customers, financials, programmes, projects, incidents, internal systems.

### Or interview your way there

For worlds without a real-world referent, Worldloom can ask instead of guess — a structured interview that builds up company identity, operating model, org topology, technology landscape, financial structure, strategic priorities, historical backstory, political tensions, and information ecosystem.

```python
World.interview()   # -> World, plus the WorldSeed it was built from
```

The interview is a constructor, not a mode. It produces an ordinary `World`; everything downstream is identical.

Two things are easily confused, and they are not the same object:

| Term | Is |
| --- | --- |
| **seed** | An integer — `8128`. Drives seeded randomness |
| **WorldSeed** | The frozen priors document — identity, lore, strategy, org intent — produced by an interview or an archetype |

Reproducing a world takes both, plus the generation ledger and the generator version.

---

## Deterministic

The same seed produces the same enterprise. Byte for byte, run to run, machine to machine.

```python
World.from_seed(8128) == World.from_seed(8128)
```

Identical organisations, projects, events, financials, artifacts, and evaluation datasets. A world is reproducible from a single integer, which means a corpus is citable — you can put a seed in a paper and have someone else regenerate exactly what you measured.

This holds despite the generative layer, because a world carries its generation ledger and `from_seed()` replays it rather than re-prompting. Regeneration is offline, free, and byte-identical. Changing the model or a prompt template changes the ledger keys and therefore produces a *different* world — explicitly, and with a different seed. Worldloom will not quietly re-prompt and hand back something that no longer matches the seed you asked for.

---

## Built for evaluation

Every world can emit its own test set:

```python
evals = world.evaluations()

evals.questions()      # what to ask
evals.answers()        # what is true
evals.citations()      # which artifacts support it
evals.distractors()    # plausible artifacts that do not
```

With the knobs that make an eval hard on purpose: temporal cut-offs, permission-aware variants, and multi-hop reasoning chains.

Built for teams working on RAG, enterprise search, AI agents, coding agents, document intelligence, knowledge graphs, enterprise copilots, and retrieval benchmarks.

### Controlled imperfection

Real enterprises are messy, and a corpus that isn't will flatter your system. Worldloom introduces mess deliberately — stale documents, outdated assumptions, duplicate issues, superseded reports, incomplete summaries, conflicting terminology.

Every inconsistency is labelled and traceable, so it is a test case rather than a bug:

```python
world.artifacts().where(stale=True)
world.inconsistencies()
```

---

## Architecture

```
                 Socratic Interview
                          │
                          ▼
                     World Seed
                          │
                          ▼
                  Enterprise Builder
                          │
                          ▼
                Canonical World Model
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
  Historical         Event Engine         Fact Ledger
   Timeline
      │                   │                   │
      └───────────────────┼───────────────────┘
                          ▼
                   Artifact Planner
                          │
                          ▼
                     Artifact IR
                          │
      ┌───────────────────┼───────────────────┐
      │                   │                   │
      ▼                   ▼                   ▼
  Narrative            Renderers         Evaluations
  Generator
```

The core knows about worlds, events, facts, and an artifact IR. It knows nothing about XLSX, Jira, or SAP.

### Everything else is a plugin

```
worldloom/
├── finance/
├── retail/
├── jira/
├── pptx/
└── servicenow/
```

Industries, domains, and renderers all load through the same entry-point mechanism. Adding SAP support should not require touching the core:

```bash
pip install worldloom-sap
```

---

## Prior art

Worldloom steals from libraries, not from AI frameworks:

| Library | What we take |
| --- | --- |
| **SQLite** | Single-file mental model, ruthless reliability |
| **DuckDB** | Elegant local analytics, zero configuration |
| **Polars** | Fluent, immutable, lazy API |
| **Pydantic** | Clean typed models at every boundary |
| **Typer** | A CLI that mirrors the library exactly |
| **Ruff** | Opinionated defaults, uncompromising speed |
| **uv** | Simple commands, minimal ceremony |
| **dbt** | Declarative recipes and lineage |
| **PyTorch** | A genuinely Pythonic object model |
| **Rich** | Terminal and notebook output worth looking at |
| **pytest** | Extensibility through plugins |

The litmus test for every public API we add:

> Could a senior engineer discover and use this from autocomplete alone, without reading the documentation?

If no, the API is wrong. Not the documentation.

---

## Roadmap

Worldloom is built as one coherent enterprise episode taken all the way through, then generalised — not subsystem by subsystem. The full sequence, with exit gates for each step, is in **[docs/build-order.md](docs/build-order.md)**.

The first executable is `worldloom demo retail-close`, not `worldloom interview`.

**Gate A — Coherence.** One episode agrees with itself across facts, events, systems, and artifacts.

- [x] Thin waist: `World`, `Event`, `Fact`, `Persona`, `ArtifactIntent`, `ArtifactIR`, `EvaluationCase`, `GenerationLedger`
- [x] Hand-authored golden episode: retail month-end close, no LLM
- [x] Library kernel: load, inspect, validate, export — `worldloom demo retail-close`
- [x] Temporal append-only fact ledger with supersession and authority
- [x] Coherence validator: referential, graph, financial reconciliation, temporal, lore, access
- [x] Minimal lore: 5 commitments, each constraining a downstream decision
- [x] Deterministic organisation, financial, and operational generators
- [x] Lore drives generation: incident likelihood, artifact density, persona traits
- [x] Same seed reproduces the world; every seed produces a coherent one

**Gate B — Utility.** An external retrieval or agent system can ingest the corpus and be scored against it.

- [ ] Evaluation cases derived from canonical facts
- [ ] Direct, cross-artifact, numerical, multi-hop, temporal, and authority question types
- [ ] Expected abstention and required citation checking
- [ ] In-repo baseline retriever, so the gate is self-testable
- [x] Artifact IR with declared formulas, and a renderer registry
- [x] XLSX source model: real formulas, named ranges, hidden lineage and reconciliation sheets
- [x] Portable Jira, Confluence, and ServiceNow bundles
- [x] Markdown fallback, so every artifact stays readable and diffable
- [ ] DOCX, then PPTX, then PDF derived from both
- [x] LLM as constrained narrative compiler: claim extraction, fact-reference substitution, validation loop
- [x] Deterministic fake provider and generation-ledger replay

**Gate C — Generality.** A second industry works without industry-specific fields reaching the core.

- [ ] IT-services vertical: fixed-price programme, utilisation, margin erosion
- [ ] Domain modules: `core`, `finance`, `retail`, `it_services`
- [ ] Archetype packs and full lore packs
- [ ] Socratic world composer, with replay and an assumption ledger
- [ ] Scenario DSL and artifact recipes, extracted from two verticals rather than guessed
- [ ] Bounded fan-out, size profiles, lifecycle versions
- [ ] Enterprise mess as a separate mode: temporal versions, authority, permissions, labelled noise

**Gate D — Scale.** Large corpora without changing semantics or losing reproducibility.

- [ ] 10K artifacts, single process, resumable
- [ ] 100K artifacts, partitioned storage and workers
- [ ] 1M artifacts, distributed execution
- [ ] External publishers for Jira, Confluence, ServiceNow
- [ ] Further industry packs: healthcare, banking, manufacturing
- [ ] Multi-company ecosystems and cross-enterprise supply chains

Deliberately postponed: a web UI, multi-agent world-building, a graph database, direct SaaS publishing, and meta-generation of generators. These add surface area without proving the product.

---

## Guiding principle

> **Reality is generated once. Documents are rendered many times.**

That distinction is what makes Worldloom useful for building AI systems that must reason across complex enterprise information instead of memorising disconnected files.

---

## Licence

[Apache 2.0](LICENSE)
