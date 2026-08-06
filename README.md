# Worldloom

**Worldloom is to enterprise corpora what SQLite is to databases.**

A small, deterministic harness that generates coherent synthetic enterprise worlds
— organisations, people, projects, finances, systems, incidents, years of history —
and materialises them into realistic documents, business system records, and
knowledge artifacts for AI evaluation, retrieval, and agent testing.

No service to run. No API key. No model behind an SDK.

**Your coding agent is the model. Worldloom is the harness.**

```bash
pip install "worldloom[all]"     # or, from a checkout: pip install -e ".[dev]"

worldloom build --seed 8128 --incident --out ./corpus   # deterministic: the world
worldloom narrate requests ./corpus -o requests.json    # what prose is needed
#   the agent writes responses.json
worldloom narrate accept ./corpus --from responses.json # checked against the facts
worldloom render ./corpus -f xlsx -f docx -f jira -f confluence
worldloom validate ./corpus                             # 1,100+ coherence checks
```

Worldloom builds the enterprise, works out which documents it would have, resolves
every table and figure, and then hands the agent a bounded request per section. What
comes back is **checked against the fact ledger**. Restate a number, cite something
you were not given, or mention an entity that does not exist, and the prose is
rejected with the reason.

There is no API-caller path, deliberately: this package never calls a language
model. The writer is the coding harness driving it — Claude Code through the
`/worldloom` skills, Antigravity, or any agent that can run a terminal — and
the loop above is the whole contract: the harness reads `requests.json`,
writes `responses.json`, and submits until accepted. Everything in this
repository, including every test, runs with no key at all.

That division is the design. The agent supplies judgement and language. The harness
supplies truth, and refuses anything that contradicts it.

Agents start at **[AGENTS.md](AGENTS.md)**. Claude Code has a skill: `/worldloom`.

> **Status: Gates A and B complete.** Deterministic generation, all seven
> renderers, the evaluation set with its in-repo baseline retriever, three agent
> handshakes (`plan`, `narrate`, `act`), and the first actor episode — employees
> producing the incident's records from role-scoped observations. Still ahead:
> the second industry, the interview, mess as a mode, and scale. The
> [roadmap](#roadmap) marks each box; [`docs/build-order.md`](docs/build-order.md)
> is the sequence and the exit gate for each step.
>
> ```bash
> worldloom build --seed 8128 --incident --replay ./corpus -f xlsx --out ./again
> diff -r ./corpus ./again        # identical, and no model was called
> ```
>
> A world regenerates byte-for-byte from its seed, its recipe, and its generation
> ledger, under the worldloom version stamped into its `world.json`. CI enforces
> that diff on every push.

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

## The Python engine

The harness is the product; this is the engine underneath it, and every CLI command
is a thin wrapper over it. Reach for it when you are extending Worldloom rather than
using it — a new renderer, scenario, or industry is written here.

The design goal is a single sentence:

> A senior engineer should be able to discover and use Worldloom from autocomplete alone, without reading the documentation.

Everything below exists to serve that.

### One entry point

```python
from worldloom import World, RetailWorld, MonthEndClose
```

Two ways to get a world, and only two:

```python
World.load("retail-close")          # a corpus that already exists, by name or path
RetailWorld(seed=8128).build()      # a new one, deterministically, from a seed
```

A loaded corpus is a result: readable, queryable, renderable, but not advanceable.
A built world can additionally `run` scenarios, because it carries its generator
state. The distinction is deliberate — a corpus you were handed is evidence, and
evidence does not get quietly extended.

### Immutable

Every operation returns a new `World`. Nothing mutates in place.

```python
base = RetailWorld(seed=8128).build()

march = base.run(MonthEndClose(period="2026-03"))
april = march.run(MonthEndClose(period="2026-04"))

# base is untouched, and march does not contain april
```

This is what makes worlds safe to fork, cache, compare, and pass around — the same
property that makes Polars pleasant.

### Lazy

Constructing a builder is free. Nothing expensive happens until you ask for the world.

```python
world = RetailWorld(seed=8128, employees=80_000)   # instant, does no work
world = world.build()                              # this is the expensive call
```

### Build, then query

Interrogation is a fluent query over typed collections, in the Polars idiom.

```python
world.facts.where(kind="ops.cause")
world.events.where(kind="incident_opened")
world.people.where(function="Finance")
```

`.where()` is the primitive. The temporal and authority questions the corpus is
built to pose are first-class operations, not joins you write yourself:

```python
world.as_of("2026-04-01T10:00:00")     # the facts that held at that moment
world.org_at("2026-04-01T10:00:00")    # who worked here then
world.visible_to("PERSON-0007")        # what the controller may read
world.authoritative("ops.cause", "SVC-0001")   # which account of the cause wins
world.provenance("ART-0003")           # where a document came from, both directions
```

### Everything is inspectable

```python
world.people
world.facts
world.events
world.artifacts
world.evaluations
world.timeline()
world.incidents()
world.observations      # who knew what, when, and through which channel
world.actor_ledger      # every actor tool call, accepted and refused
```

Internal state is never hidden. If Worldloom knows it, you can read it.

### Every noun is a first-class object

Not `dict`. Not `Any`. Real typed models:

`Company` · `Employee` · `Persona` · `System` · `Service` · `Category` · `Site` ·
`EnterpriseEvent` · `CanonicalFact` · `LoreCommitment` · `ArtifactIntent` ·
`ArtifactIR` · `EvaluationCase` · `GenerationLedgerEntry`

Every accessor returns one of them, or a typed collection of them. Never an
anonymous dictionary.

### Dataframe interop

Collections convert without ceremony, so analysis happens in the tool you already use:

```python
world.people.to_polars()
world.facts.to_pandas()
world.events.to_arrow()
```

### Readable in a notebook

`repr()` is part of the API, not an afterthought. `world.summary()` prints the
counted overview — entities, facts, artifacts, evaluation cases, ledger entries,
the reporting period, the seed, and the worldloom version that generated it.

### One obvious way

Each verb means exactly one thing, and each returns a new `World` except the last two:

| Verb | Does |
| --- | --- |
| `.run(scenario)` | Advances the world: events, facts, artifact plan, evaluations |
| `.compile()` | Resolves artifact intents into IR — structure and tables before prose |
| `.narrate(provider)` | Fills sections with prose, replaying the ledger where possible |
| `.render(*formats)` | Turns compiled artifacts into files, held until export |
| `.validate()` | Checks coherence → `ValidationReport` |
| `.export(path)` | Writes the corpus to disk → `Path` |

### The CLI is the surface

The CLI adds no capability the engine lacks, and nothing the engine can do is
unreachable from the CLI. It is what an agent drives, so it is the surface that
matters most:

```bash
worldloom build       # generate a world from a seed
worldloom act         # requests / accept — be the employees, one decision at a time
worldloom plan        # requests / accept — propose each document's shape
worldloom narrate     # requests / accept — write the prose, under fact constraints
worldloom render      # materialise into files
worldloom validate    # check that every document agrees
worldloom evaluate    # score the baseline retriever against the corpus
worldloom diversity   # check the batch is not one document photocopied
worldloom inspect     # show what a corpus contains
worldloom actors      # the actor execution ledger: who did what, on what they saw
worldloom archetypes  # list the company shapes a build can take
worldloom evals       # export the evaluation set
```

### Shape and scale

An **archetype** is the shape of a company without the company: how many divisions,
what they sell, how thin the margins are, how many stores. Everything else — names,
figures, people, incidents — is generated from the seed.

```bash
worldloom archetypes
worldloom build --archetype australian_grocery --comparatives 11 -f xlsx --out ./corpus

# Or describe a real business and get a world of that shape:
worldloom build --inspired-by "a large Australian grocer" --comparatives 11 -f xlsx
```

`--inspired-by` resolves a description to an archetype and stops there. It looks up
no data about the named company; what it borrows is unit mix, margin structure,
category depth, and store count — the things that make a corpus *hard* in the way a
real one is hard. The generated company has an invented name, invented divisions,
invented stores, and invented numbers.

Shape is what makes the workbook worth opening. A retailer's month does not stop at
three divisions — it decomposes by merchandise category and, independently, by store:

```
Summary                    5 rows      Business Unit P&L        5 rows
Category P&L              39 rows      Store Performance    1,568 rows
Revenue Trend             39 × 12      Variance Drivers         4 rows
Lineage (hidden)       6,294 rows      Reconciliation (hidden) 10 rows
```

Both decompositions are *allocated* from the unit total rather than drawn and summed,
so they cannot drift; the hidden Reconciliation sheet then sums each of them back —
across sheets, in live formulas — against what the fact ledger states. Ten checks,
every one netting to zero when the file opens.

None of this reaches the narrative side. The workbook cites 6,294 facts; the CFO memo
cites the group and unit figures only, and a build of that size still produces 23
narrative requests with at most 32 facts each.

---

## Scenarios

A scenario is a frozen dataclass with a `run` method — deliberately not a DSL,
because a DSL designed before the second industry exists would encode guesses
rather than recurring structure. Four ship today:

```python
from worldloom import MonthEndClose
from worldloom.scenarios import Departure, Hire, Reorganisation, WorkforceChange

world = world.run(MonthEndClose(period="2026-03", include_operational_incident=True))
world = world.run(Departure(period="2026-04", role_key="controller"))
world = world.run(WorkforceChange(period="2026-04", headcount=84_500))
```

Total workforce and named employees are separate by design. `--employees`
sets authoritative company headcount; Worldloom still materialises the bounded
decision-making graph rather than one `Employee` row per payroll record. Over a
history, `--headcount-end` creates exact aggregate workforce episodes between
the two anchors, and explicit workforce scale raises sampled incident,
succession, and reorganisation density logarithmically rather than linearly:

```bash
worldloom build --employees 80000 --headcount-end 92000 --periods 6 \
  --timeline steady --out ./growing-enterprise
```

The recipe records every intermediate target, each movement emits numeric
headcount and delta facts plus a personnel notice, and replay reconstructs the
same final organisation. A million-person company therefore creates more
organisational activity without creating a million in-memory identities or a
million copies of month-end close.

The artifact plan follows the episode, not a template: a close without an incident
gets no RCA, and a departure produces the personnel notice that makes the
succession answerable. From one incident, the record fans out mutually consistent:

```
Pipeline failure
        │
        ▼
ServiceNow Incident ── Status Page (stale on purpose)
        │
        ├────────────────┐
        ▼                ▼
   Jira Issues     Working Note
        │                │
        ▼                ▼
Engineering RCA   CFO Variance Memo
        │                │
        ▼                ▼
Knowledge Article  Executive Summary
```

Every artifact agrees on timestamps, systems, services, financial impact, root
cause, and ownership — unless the disagreement is intentional, like the triage
status page that never learns the confirmed cause.

---

## Actors, optionally

`worldloom build --actors` changes who decides what the incident's records say.
Without it, a deterministic planner writes them from the whole fact ledger. With
it, they are produced by employees calling typed tools on what each had actually
observed at the time — and the harness enforces authority and knowledge the way
it enforces arithmetic:

```bash
worldloom build --seed 8128 --incident --actors agent --out ./corpus
worldloom act requests ./corpus -o decision.json   # what one employee can see
#   you choose one tool call, and write action.json
worldloom act accept ./corpus --from action.json   # validated before it changes anything
worldloom actors ./corpus --observations           # who could see what, when
```

An actor that cites a fact it never observed, calls a tool beyond its role, or
confirms a cause the world did not establish is refused with the rule it broke.
The service desk analyst, the engineer, and the CFO genuinely see different
incidents, which is what makes "who knew the root cause before the close moved"
a question with a checkable answer. The full contract is in
[AGENTS.md](AGENTS.md) and [docs/actor-simulation.md](docs/actor-simulation.md).

---

## What Worldloom generates

From the retail close episode (the default build):

| Domain | Artifacts |
| --- | --- |
| **Finance** | Month-end workbook with live formulas · CFO variance memo · per-division close commentary · working notes · close calendar |
| **Operations** | ServiceNow incident records · Confluence status pages · knowledge articles |
| **Engineering** | Incident RCAs · Jira remediation issues |
| **Communications** | Meeting minutes with attendance and decisions · email threads whose early messages honestly don't know the ending |
| **Strategy** | Executive committee summaries |
| **People** | Personnel notices, when someone joins, leaves, or a unit changes hands |
| **Evaluation** | Question sets over all of it: direct, cross-artifact, numerical, causal, temporal, authority, abstention — including who was in the room, and who was told what, when |

And from the banking episode (`--archetype midsize_adi`): a quarterly capital
return challenged by the second line before lodgement, filed anyway under a
lodgement norm, invalidated by a reconciliation break the *daily* liquidity
cadence catches, and corrected by a **restatement** that leaves the original
filing on the record — capital return and its restatement, RWA working papers
(v1 revised to v2), the second-line challenge memo, incident record and RCA,
the internal audit ruling, and a board summary with a labelled omission. Both
lodgements sit at the same authority, so nothing but the restatement
relationship and fact validity can say which figure is current — which is
exactly the question the evaluation set asks.

Rendered natively to **XLSX**, **DOCX**, **PPTX**, **PDF**, **Markdown**, and
portable **Jira**, **Confluence**, and **ServiceNow** bundles. Renderers are
plugins; adding one never touches the world model. The wider artifact families —
board packs, PRDs, account plans, workforce plans — arrive with bounded
fan-out, per the [roadmap](#roadmap).

---

## Industry packs

The shape, lore, and name of the company are data you can author — a JSON
file run through one of the shipped engines, with the episode physics staying
the engine's:

```bash
worldloom pack template retail > insurer.json   # start from a valid skeleton
worldloom pack targets retail                   # which lore is load-bearing
worldloom pack check insurer.json               # schema + inert-lore lint
worldloom build --pack insurer.json --incident --narrate -f markdown --out ./corpus
```

Lore is the lever: a dated commitment aimed at a consulted target changes
what the engine generates — how likely the incident is, how much gets
written, how a person writes — and the corpus's own timeline witnesses it.
The pack embeds into the corpus recipe, so a pack-built corpus rebuilds
byte-for-byte with no pack file on hand. Reference packs in
[`examples/packs/`](examples/packs/): a general insurer on the close engine,
a mutual bank on the challenged-return engine.

## Worlds inspired by real enterprises

Generate an organisation with the shape of a real one, without reproducing anything proprietary.

```python
from worldloom import RetailWorld

RetailWorld.inspired_by("a large Australian grocer", seed=8128).build()
```

```bash
worldloom build --inspired-by "a large Australian grocer" --seed 8128 --out ./corpus
```

Preserved: unit mix, margin structure, category depth, store count — the industry
characteristics that make a corpus hard the way a real one is hard. Invented:
every name, employee, figure, system, and incident. No data about the described
company is looked up or used.

### Or interview your way there — planned

For worlds without a real-world referent, the roadmap's step 9 is a structured
interview that builds up company identity, operating model, history, and tensions,
then freezes them into a **WorldSeed** the deterministic engine builds from. It is
not built yet, and deliberately so — it comes after the target schema is proven by
two industries, so prompt behaviour cannot anchor the architecture.

Two things are easily confused, and they are not the same object:

| Term | Is |
| --- | --- |
| **seed** | An integer — `8128`. Drives seeded randomness |
| **WorldSeed** | The frozen priors document — identity, lore, strategy, org intent — produced by an interview or an archetype |

Reproducing a world takes both, plus the generation ledger and the generator version.

---

## Deterministic

The same seed produces the same enterprise. Byte for byte, run to run, machine to machine.

```bash
worldloom build --seed 8128 --incident --narrate -f xlsx -f markdown --out ./one
worldloom build --seed 8128 --incident --replay ./one -f xlsx -f markdown --out ./two
diff -r ./one ./two    # identical, and the second run made no generative call
```

A world is reproducible from its seed, its recipe, and its generation ledger,
which means a corpus is citable — you can put a seed in a paper and have someone
else regenerate exactly what you measured.

This holds despite the generative layer, because every generative call — prose,
document plans, actor decisions — is content-addressed into the ledger, and
`--replay` serves it back rather than re-prompting. Changing the model or a
prompt version changes the ledger keys and therefore produces a *different*
world — explicitly, never silently. Each corpus stamps the worldloom version
that generated it into `world.json`, because reproducibility is a claim about a
specific generator.

---

## Built for evaluation

Every world emits its own test set, derived from canonical facts rather than
invented by a model:

```python
for case in world.evaluations:
    case.question                  # what to ask
    case.expected_fact_ids        # what is true
    case.required_artifact_ids    # which documents support it
    case.distractor_artifact_ids  # plausible documents that do not
    case.temporal_cutoff          # what could have been known, and when
    case.expects_abstention       # whether refusing is the right answer
```

And ships the baseline that makes the hard questions measurable:

```bash
worldloom evaluate ./corpus
```

A deliberately mediocre keyword retriever is scored per question family. The
useful signal is the *shape*: a corpus on which the baseline aces direct lookup
but fails temporal, authority, and abstention questions is a corpus that is
actually testing something. If that score rises without anyone improving the
retriever, the corpus got easier — CI watches for exactly that.

Built for teams working on RAG, enterprise search, AI agents, document
intelligence, knowledge graphs, and retrieval benchmarks.

### Controlled imperfection

Real enterprises are messy, and a corpus that isn't will flatter your system.
The golden episode carries deliberate mess — an initial diagnosis that was wrong,
a status page that never learns the confirmed cause, a summary that omits the
control failure — and every imperfection is a labelled `IntentionalError`, so it
is a test case rather than a bug:

```python
world.inconsistencies()
```

Generated worlds are clean by design for now: mess as a configurable mode is
step 11 of the build order, after coherence, so a coherence bug can never hide
behind a feature.

---

## Architecture

```
            Socratic Interview (planned)
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
                   Actor Runtime
              (employees, tools, policy)
                          │
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

### Renderers are plugins

A renderer reads the `ArtifactIR` and nothing else — no facts, no world, no
model — and registers itself through `worldloom.render.register`. That is what
lets a format be added without touching the world model, and what guarantees two
formats of one artifact agree: they are projections of one resolved structure.
Industry modules follow the same rule from the other side: retail specifics live
in `worldloom.retail`, never in the core `World`. An external plugin mechanism
for third-party packages is deliberately last on the [roadmap](#roadmap) —
plugin APIs get extracted from real extension pressure, not designed
speculatively.

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

- [x] Evaluation cases derived from canonical facts
- [x] Direct, cross-artifact, numerical, multi-hop, temporal, and authority question types
- [x] Expected abstention and required citation checking
- [x] In-repo baseline retriever, so the gate is self-testable — `worldloom evaluate`
- [x] Artifact IR with declared formulas, and a renderer registry
- [x] XLSX source model: real formulas, named ranges, hidden lineage and reconciliation sheets
- [x] Portable Jira, Confluence, and ServiceNow bundles
- [x] Markdown fallback, so every artifact stays readable and diffable
- [x] DOCX for the narrative artifacts, with document dates derived from the world
- [x] PPTX and native PDF, both byte-stable
- [x] LLM as constrained narrative compiler: claim extraction, fact-reference substitution, validation loop
- [x] Deterministic fake provider and generation-ledger replay
- [x] Structural diversity: style genomes, plan handshake, fingerprints — `worldloom diversity`
- [x] Multi-period worlds: recurrence, superseded calendars, org change over time

**Actor simulation** (roadmap A0–A5 of [docs/actor-simulation.md](docs/actor-simulation.md)) — employees as bounded actors inside the deterministic world.

- [x] Actor boundary: observations, invocations, actions, tool results, execution ledger
- [x] Epistemic observations: who knew what, when, through which channel
- [x] Role policies and decision rights, enforced by tools rather than prompts
- [x] 27 typed tools across service management, engineering, finance, and documents
- [x] Event-driven scheduler with bounded episodes
- [x] The retail-close incident as an actor episode, replayable byte-for-byte
- [x] The `worldloom act` handshake: one decision at a time, resumable by rebuild
- [ ] Actor memory, meetings, incentives, cross-period actors (A6–A9)
- [x] The measured hardness gate (A10) on the banking corpus: contested authority at a deliberate rank tie, and its temporal inverse, both scoring below direct lookup — pinned as an inequality in tests

**Gate C — Generality.** A second industry works without industry-specific fields reaching the core.

- [x] The second vertical: banking (`BankingWorld` + `QuarterlyCapitalReturn` — the challenged, restated capital return), with zero core model changes; decision recorded in [docs/build-order.md](docs/build-order.md) §7
- [ ] Domain modules and the industry-pack interface, extracted from two verticals rather than guessed
- [x] Industry packs: archetype and lore as agent-authorable JSON (`worldloom pack`), embedded in the recipe, linted against each engine's consulted targets
- [x] Pack texture: system brands and per-role prose voices, with each engine publishing its slots and roles
- [ ] Name pools and terminology in packs (today they stay engine-owned)
- [ ] Socratic world composer, with replay and an assumption ledger
- [ ] Scenario DSL and artifact recipes
- [x] Bounded fan-out, first slice: minutes, email threads, and per-unit commentary projected from each episode's own facts, in both verticals
- [ ] Bounded fan-out at scale: wider document families, size profiles, lifecycle versions, actor-message threads
- [ ] Enterprise mess as a separate mode: temporal versions, authority, permissions, labelled noise

**Gate D — Scale.** Large corpora without changing semantics or losing reproducibility.

- [ ] 10K artifacts, single process, resumable
- [ ] 100K artifacts, partitioned storage and workers
- [ ] 1M artifacts, distributed execution
- [ ] External publishers for Jira, Confluence, ServiceNow
- [ ] Further industry packs: healthcare, IT services, manufacturing
- [ ] Multi-company ecosystems and cross-enterprise supply chains

Deliberately postponed: a web UI, multi-agent world-building, a graph database, direct SaaS publishing, and meta-generation of generators. These add surface area without proving the product.

---

## Guiding principle

> **Reality is generated once. Documents are rendered many times.**

That distinction is what makes Worldloom useful for building AI systems that must reason across complex enterprise information instead of memorising disconnected files.

---

## Licence

[Apache 2.0](LICENSE)
