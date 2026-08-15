# Worldloom

**A deterministic compiler for coherent synthetic enterprise corpora.**

Worldloom generates the enterprise before it generates the files: companies,
people, reporting lines, systems, services, financial facts, events, permissions,
document intents, and evaluation cases. It then projects that state into native
XLSX, DOCX, PPTX, PDF, Markdown, Jira, Confluence, and ServiceNow artifacts.

The result is a corpus in which a memo, workbook, incident, ticket, board summary,
and retrieval answer can be checked against the same fact ledger.

No service to operate. No API key in the library. No hidden model call.

> Your agent supplies judgement and language. Worldloom supplies truth,
> structure, lineage, and refusal.

```bash
pip install "worldloom[all]"

worldloom build --seed 8128 --incident --narrate --out ./corpus
worldloom render ./corpus -f xlsx -f docx -f pptx -f pdf -f markdown
worldloom validate ./corpus
worldloom evaluate ./corpus --retriever both
```

The built-in deterministic narrator is useful for tests, replay, and inspecting a
complete corpus without a model. For production prose, let a coding agent drive the
validated `narrate requests` / `narrate accept` handshake described below.

## The design in one diagram

```text
Authoring inputs                         Deterministic world
+----------------------+                 +---------------------------+
| spec / pack / facets |----+            | company + people + estate |
| seed / locale / lore |    |            | events + facts + access   |
| physics / org shape  |    +----------->| recipe + eval ground truth|
+----------------------+                 +-------------+-------------+
                                                        |
                                                        v
                                              +---------------------+
                                              | artifact intents    |
                                              | author / audience   |
                                              | type / facts / time |
                                              +----------+----------+
                                                         |
                              propose -> validate -> accept
                                                         |
                                                         v
                                              +---------------------+
                                              | ArtifactIR          |
                                              | tables + sections   |
                                              | claims + lineage    |
                                              +----------+----------+
                                                         |
                         +---------------+---------------+---------------+
                         |               |               |               |
                         v               v               v               v
                       XLSX          DOCX/PDF         PPTX/MD       Jira/Confluence/
                                                                      ServiceNow
```

The renderers never decide what is true. They receive one resolved `ArtifactIR`
and project it into different file grammars. That is why the PDF and DOCX can
share the same title, author, period, evidence, and numbers without coordinating
with each other.

## Why this exists

Most synthetic-data systems generate files independently. That produces documents
that look plausible in isolation and fail as a corpus:

- a PDF reports a total the workbook cannot reconcile;
- an RCA names a cause that the incident record never established;
- a ticket is assigned to an employee who does not exist;
- a board paper cites information discovered after it was signed;
- five seeded companies are the same organisation with different names;
- a retriever is evaluated against questions whose evidence is absent.

Worldloom reverses the order:

```text
world state --> events --> canonical facts --> artifact plan --> prose --> files
```

Facts precede prose. Simulation precedes rendering. Evaluation ground truth is
derived from the same state as the evidence. Every generated claim remains
traceable to the facts and events that support it.

## What ships today

### Four verticals

| Vertical | Episode | What makes it useful |
| --- | --- | --- |
| Retail | `MonthEndClose` | Financial reconciliation, operational incidents, multi-period histories, workforce and estate trajectories |
| Banking | `QuarterlyCapitalReturn` | Second-line challenge, equal-authority conflict, filing and restatement |
| Insurance | `QuarterlyReserving` | Triangle development, emergence, held versus central estimates, authority-sensitive answers |
| Procurement | `PurchaseToPayCycle` | Purchase-to-pay controls, three-way matching, exceptions, and carried shortfalls |

The vertical owns the causal episode, its fact kinds, documents, invariants, and
benchmark. A pack changes the company using an existing episode. A new vertical
changes what happens.

#### The organisation is load-bearing, and that is where volume comes from

A company declares business units, sites, cost centres and categories. Whether
anything *reports* on them is a separate question, and for three of the four
verticals the answer used to be no: a bank with three divisions and 133 branches
mentioned none of them in any fact or any document, and its corpus was 58 facts
about capital ratios. Every one of those corpora passed `worldloom validate`,
because coherence and thinness are different properties.

`validate.reachability` asks the question directly — an entity is *reached* when
a fact names it and a compiled document carries that fact on its readable
surface, appendices excluded. Closing it is what produced the volume:

| Vertical | Facts, one period | Documents | `validate` checks |
| --- | --- | --- | --- |
| Retail | 588 | 7 | 7,787 |
| Banking | 58 → **744** | 11 → **12** | 1,661 → **9,249** |
| Insurance | 62 → **219** | 4 → **8** | 1,155 → **3,088** |
| Procurement | 52 → **217** | 6 → **7** | 1,090 → **3,332** |

Each vertical measures what its own vocabulary owns: deposits, lending and
front-line FTE by branch; written premium by underwriting office and claims by
claims centre; spend, commitment and materials by depot, project office and
yard. Every split goes through a largest-remainder allocator, so roll-ups
reconcile exactly rather than nearly, and a rate is never summed. Volume scales
with the estate rather than with a multiplier — banking at `--periods 3` mints
2,220 facts.

The check ships as a ratchet rather than as part of `worldloom validate`: what
it reports is true and is not a statement about coherence, which is the question
`validate` answers. What it still refuses is a different class and is named as
such — a system of record is the *provenance* of every figure in these corpora,
not the subject of one.

### Structured and unstructured outputs

| Layer | Outputs |
| --- | --- |
| Canonical structured state | `world.json`; facts, events, lore, artifact intents, IR, manifests, evaluation cases, detail tables, actor ledgers, and generation ledgers as JSON/JSONL |
| Business-system records | Portable Jira issues/changelog/links, Confluence pages/comments, ServiceNow incidents and CMDB relationships |
| Analytical artifacts | Formula-bearing XLSX workbooks with lineage and reconciliation sheets |
| Narrative artifacts | DOCX, PDF, PPTX, and Markdown generated from the same resolved IR |
| Evaluation assets | Questions, expected fact IDs, required evidence, distractors, temporal cutoffs, and abstention labels |

The corpus directory is plain files. Worldloom is needed to build and validate it,
not to read it.

### Structure is derived, not looked up

A document's outline used to be a constant per artifact type, so a corpus of a
thousand documents rendered a few dozen shapes and twelve monthly close packs
were twelve renderings of one skeleton. A retriever can learn that shape instead
of the content.

The outline is now a function of a **structural genome** — a handful of integers
recorded on the recipe, so a corpus resolves the same shapes when it is loaded
back and a rebuild reproduces them.

```bash
worldloom build --section-omission 400 --variant-bias 1 --outline-synthesis 600 --out ./corpus
worldloom diversity ./corpus --effective
```

`--section-omission` is swarm testing applied to documents: a document emits a
*subset* of its type's optional sections rather than all of them every time.
Sections are required unless a type says otherwise, so the default build is
byte-identical to what it always was.

`--outline-synthesis` goes further and *draws* a shape rather than subsetting
one — from what this company's own document types have in common, projected onto
the roles their sections play rather than the words in their headings. It is
recombination and never inflation: a synthesised outline has to carry at least
what the authored one carried, in no more sections, arguing the document the way
its type argues it, and falls back to the authored outline when no draw does.
Measured on a six-period retail corpus, 40 distinct rendered shapes become 62
with no document losing a line of prose.

Why roles rather than headings is a measured answer, not a preference. Splicing
on heading text admits exactly **one** novel outline across the whole fleet,
because only a handful of headings appear in more than one document type — and
that stayed true after ten policy types were given entirely new headings, which
is how we know the vocabulary was never the fixable part.

`--effective` is the reading that made the case for the work. A count of
distinct shapes prices a shape used ten times exactly as it prices one used
once; the Vendi score reports the **effective** number, and the gap between the
two is where the monotony hides.

### Planning a fleet, not sampling one

```bash
worldloom spaces                              # 12 axes, 3,732,480 configurations
worldloom spaces --cover -t 2 > plan.jsonl    # 39 rows cover every pair
worldloom spaces --holes plan.jsonl           # what a fleet you built missed
```

A covering array grows with the two widest axes rather than with the space, so
every pairwise interaction is reachable in a fleet a person would actually
build. The complement matters more: pointed at the shipped determinism gate,
`--holes` reported that it covered 24% of pairs and had **never once built a
bank running more than one period** — a gap the gate could not see, because a
sampler knows where its points landed and not which combinations nobody reached.

### These are one loop, not five features

Each command above answers a different question, and they close on each other:

```bash
worldloom spaces --cover -t 2 > plan.jsonl    # what should exist
worldloom build --outline-synthesis 600 ...   # make one of them
worldloom diversity ./corpus --effective      # is it actually varied
worldloom spaces --holes fleet.jsonl          # what still does not exist
```

Plan the space, build into it, measure what came out, and ask what is still
missing — then plan again against the answer. The measurement is what makes it a
loop rather than a pipeline: `--effective` and `--holes` both report a
*denominator*, so "we built two hundred corpora" becomes "we covered 41% of the
pairs and never varied five of the twelve axes at all".

One step is deliberately library-only. `worldloom.archive` keeps one champion per
structural niche rather than the best *n* overall — on a measured population it
spanned 33 of 36 niches where best-*n* spanned 20 — and it composes with
`spaces.archive_of` today, but selecting a shipped fleet with it is a decision
about what to keep, not a reading. It gets a command when there is a fleet big
enough for the choice to matter.

## Quickstart: one coherent enterprise

```bash
# Build deterministic state and a complete test narration.
worldloom build \
  --seed 8128 \
  --incident \
  --comparatives 11 \
  --estate large \
  --eval-density high \
  --narrate \
  --out ./corpus

# Materialise every supported artifact family.
worldloom render ./corpus \
  -f xlsx -f docx -f pptx -f pdf -f markdown \
  -f jira -f confluence -f servicenow

# Run independent readings of the corpus.
worldloom validate ./corpus
worldloom topology ./corpus
worldloom series ./corpus
worldloom diversity ./corpus --near-duplicates
worldloom evaluate ./corpus --retriever both
```

Use `worldloom status ./corpus` at any point. It reports the current stage and
the exact next command instead of requiring an orchestrator to infer state from
the directory.

## Production prose: a checked agent handshake

Worldloom deliberately does not import an LLM SDK. Any agent that can execute a
terminal and exchange JSON can narrate a corpus.

```bash
worldloom narrate requests ./corpus -o requests.json
# The agent writes responses.json.
worldloom narrate accept ./corpus \
  --from responses.json \
  --model-id enterprise-writer-v1
```

Each request carries the artifact type, section, author, author voice, audience,
knowledge cutoff, target length, allowed facts, required facts, and claims that
must not be made. Each response carries prose plus explicit supporting fact IDs.

Acceptance is transactional: all applicable rules are checked, violations are
returned as data, and invalid prose is not committed. The loop repeats until the
section is accepted.

```text
request
  |
  +--> author worked here at this time?
  +--> author allowed to own this department's artifact?
  +--> audience permits the author and intended readers?
  +--> title cohesive with the artifact type?
  +--> every cited fact inside the declared scope?
  +--> fact existed before the document's knowledge cutoff?
  +--> every numeric claim expressed as a fact reference?
  |
  +--> accept and ledger it, or refuse with every finding
```

See [Architecture and invariants](docs/architecture.md) for the complete boundary.

## Enterprise-scale history

Workforce size is authoritative aggregate scale; named employees are the bounded
decision-making graph. This permits a large-company corpus without minting one
Python object per payroll record.

The same principle applies to the structural estate. Business units, sites,
systems, and services have half-open lifecycles and can grow or contract across
a timeline while historical artifacts retain their original referents.

```bash
worldloom build \
  --seed 8128 \
  --employees 80000 \
  --headcount-end 92000 \
  --periods 6 \
  --timeline steady \
  --estate large \
  --business-units-end 8 \
  --sites-end 240 \
  --systems-end 24 \
  --services-end 60 \
  --eval-density high \
  --narrate \
  --out ./enterprise

worldloom render ./enterprise -f xlsx -f docx -f pptx -f pdf -f markdown
worldloom validate ./enterprise
```

Every intermediate target is deterministic. Each movement emits count and delta
facts, an enterprise notice, and a replayable recipe step. Contraction closes a
lifecycle window instead of deleting the entity. Targets below dependency-safe,
role-safe, or category-safe floors are refused.

Current CLI scope is explicit: time-varying workforce and structural trajectories
are multi-period retail capabilities. Banking and procurement run consecutive
periods — `--periods 3` validates at 27,001 and 9,398 checks respectively —
without the workforce and estate trajectories retail carries. Insurance declares
`max_periods=1`, because a second consecutive valuation quarter is phase 2 of
that engine and phase 1 is what ships; `--periods 2` is refused at plan time
naming the cap, rather than building a world and then failing inside the
episode. No flag is silently ignored to simulate a history a vertical does not
implement.

For the operational runbook, see [Generating an enterprise corpus](docs/enterprise-corpus.md).

## Many companies: dispersed, sharded, resumable

Changing a seed changes names and figures; it does not guarantee a different
company shape. `mosaic` starts from a low-discrepancy candidate field and uses
farthest-first selection so the chosen worlds cover configuration space instead
of clumping in it.

```bash
worldloom mosaic --describe
worldloom mosaic -n 20 --incident --out ./mosaic
```

For large runs, every worker receives the same global plan and owns a deterministic
subset of world indices:

```bash
worldloom mosaic -n 1000 \
  --shard-count 20 --shard-index 0 \
  --out ./enterprise-corpus

worldloom mosaic -n 1000 \
  --shard-count 20 --shard-index 0 \
  --out ./enterprise-corpus --resume
```

`mosaic.json` stores a digest of the complete plan. Argument drift on resume is
refused. Completed worlds are revalidated before being skipped. Each accepted
narrative section is fsync'd to a newline-framed checkpoint, and a torn final
append is recoverable without accepting malformed committed records.

## Artifact cohesion is a compiler contract

Every `ArtifactIntent` states:

- artifact type and business domain;
- real employee author and author function;
- audience and access policy;
- creation time and knowledge boundary;
- required facts and triggering events;
- lifecycle, authority, revision, derivation, and restatement relationships.

Compilation refuses an undeclared artifact type, an impossible departmental
author, an empty audience or title, a title unrelated to its artifact family, or
content escaping the declared fact scope. It stamps the accepted IR with a
machine-readable `artifact-contract@1` cohesion scope. Every renderer consumes
that same IR.

This is stronger than prompting a model to "keep documents consistent". A prompt
is advisory. The contract is executable and renderer-independent.

## Python SDK

The CLI is a collection of fixed pipelines. Use the SDK when the required shape
is a Python loop: cross calendars and organisation shapes, sweep a parameter,
select the least-alike candidates, or keep only worlds whose measured topology is
interesting.

```python
from worldloom import sdk

base = (
    sdk.company("retail", seed=8128)
    .staff(80_000)
    .located("australia")
    .estate("large")
)

candidates = sdk.cross(
    base,
    calendar=["flat", "harvest", "retail_christmas"],
    org=[
        {"headcount": 24, "span": 4, "levels": 3},
        {"headcount": 45, "span": 6, "levels": 4},
    ],
)

field = sdk.dispersed(candidates, 4)
worlds = [blueprint.build().episodes("2026-01", periods=3) for blueprint in field]

selected = [world for world in worlds if world.ok and world.measure()["chokepoints"] > 0]
for index, world in enumerate(selected, start=1):
    world.render("xlsx", "docx", "pdf", out=f"./sdk-corpus/world-{index:02d}")
```

Blueprints are immutable values. `build()` is the only operation that mints a
world. `cross`, `sweep`, `companies`, and `dispersed` arrange blueprints without
relaxing any invariant.

See the [Python SDK guide](docs/sdk.md) for the complete public surface.

## Agent skills

The repository ships a progressively disclosed agent interface under `.claude/`:

| Entry point | Use it for |
| --- | --- |
| `/worldloom-design` | Take an open-ended corpus ask from design through measurement and delivery |
| `/worldloom-build` | Build a decided world and report what landed |
| `/worldloom-narrate` | Write fact-scoped prose until every section is accepted |
| `/worldloom-render` | Render native files and validate the result |
| `/worldloom-evaluate` | Measure retrieval hardness, diversity, topology, and corpus statistics |
| `/worldloom-act` | Drive an actor episode one employee decision at a time |

Specialist skills cover company specifications, probes, the SDK, whole-world
authoring, document types, lines of business, processes, and new verticals. They
all use the same cascade: propose, receive all findings, revise, accept, resolve,
install, replay.

Claude Code discovers these files directly when opened at the repository root.
Other coding harnesses start with [AGENTS.md](AGENTS.md); every workflow is shell
plus JSON and does not depend on a Claude-specific runtime.

See [Using Worldloom with coding agents](docs/skills.md).

## Corpus anatomy

```text
corpus/
|-- world.json                    company, entities, recipe, schema version
|-- lore.jsonl                    historical priors and constraints
|-- events.jsonl                  append-only enterprise events
|-- facts.jsonl                   canonical and superseded facts
|-- detail.jsonl                  transaction-level tables, when requested
|-- masterdata.json               vendors, customers, SKUs, when requested
|-- artifact-intents.jsonl        type, author, audience, facts, lineage
|-- artifact-ir.jsonl             resolved tables and narrative sections
|-- artifact-manifest.jsonl       rendered files and provenance
|-- evals.jsonl                   questions, evidence, distractors, cutoffs
|-- intentional-errors.jsonl      labelled, mechanically explainable mess
|-- generation-ledger.jsonl       content-addressed generative decisions
|-- actor-*.jsonl                 observations, messages, tasks, tool calls
`-- artifacts/                    XLSX, DOCX, PDF, PPTX, Markdown, bundles
```

All ledgers are ordinary JSONL. Native artifacts are optional projections. The
canonical state remains inspectable even when no renderer dependency is installed.

## Determinism and replay

```bash
worldloom build --seed 8128 --incident --narrate -f xlsx -f markdown --out ./one
worldloom build --seed 8128 --incident --replay ./one -f xlsx -f markdown --out ./two
diff -r ./one ./two
```

The second build uses the first corpus's content-addressed generation ledger and
makes no generative call. A world is reproduced from its seed, recipe, generation
ledger, and Worldloom version. CI exercises exact file-set and byte identity over
a rotating dispersed sample of configurations.

Determinism is not implemented by freezing outputs. The system re-executes the
recipe and proves that the same inputs produce the same world.

## Evaluation is generated with the evidence

Each world creates its own evaluation set from canonical facts. An evaluation case
can carry expected fact IDs, required artifacts, explicit distractors, a temporal
cutoff, and an abstention expectation. Ground truth is therefore not another
model's judgement.

```bash
worldloom evals export ./corpus --out ./evals.jsonl
worldloom evaluate ./corpus --retriever both --json
worldloom stats ./corpus --json
```

BM25 and TF-IDF are deliberately modest baselines. The useful signal is the score
shape: direct lookup should be easier than temporal state, contested authority,
causal chains, and abstention. If a baseline rises without improving, the corpus
may have become easier.

## Documentation

Start at the [documentation home](docs/README.md).

| Guide | Purpose |
| --- | --- |
| [Architecture and invariants](docs/architecture.md) | Thin waist, generation boundary, cohesion, lineage, replay, and validation |
| [Enterprise corpus generation](docs/enterprise-corpus.md) | Scale model, histories, sharding, resume, narration, quality gates, and operations |
| [Python SDK](docs/sdk.md) | Blueprints, combinators, scenarios, queries, measurements, rendering, and extensions |
| [Agent skills](docs/skills.md) | Stage commands, specialist skills, progressive disclosure, and harness-neutral operation |
| [Generated command reference](.claude/skills/worldloom/references/commands.md) | Every installed CLI command and option, derived from Typer and checked in CI |
| [Generation model](docs/generation-model.md) | Which decisions are deterministic and which belong to a generative author |
| [Artifact compiler](docs/artifact-compiler.md) | Components, grammars, style genomes, diversity, and renderer constraints |
| [Episode grammar](docs/episode-grammar.md) | Facts, phases, slots, carry-forward, lints, and authored processes |
| [Build order](docs/build-order.md) | Historical architecture decisions, sequencing, and release gates |

## Developing Worldloom

```bash
git clone https://github.com/vamsiramakrishnan/synthetic-foundry.git
cd synthetic-foundry
pip install -e ".[dev]"

pytest -q
worldloom validate retail-close
worldloom docs --check
```

The top-level model stays small and typed. Generators own deterministic state.
Scenarios append events and facts. Artifact compilers consume intents. Renderers
consume IR. Validators remain independent of the code that produced the data.

Read [AGENTS.md](AGENTS.md) before changing the harness. It states the invariants,
the agent protocol, and the exit gates that are easy to violate with a locally
reasonable abstraction.

## Principles

1. Reality is generated once; artifacts are rendered many times.
2. The model never owns arithmetic, identity, chronology, or graph mutation.
3. Every claim has evidence and every artifact has provenance.
4. Refusal is a product feature, not an exceptional path.
5. Diversity is measured across a batch, not inferred from prompt variation.
6. Replay is offline and byte-identical.
7. Scale may change throughput; it may not change semantics.

## License

Apache License 2.0. See [LICENSE](LICENSE).
