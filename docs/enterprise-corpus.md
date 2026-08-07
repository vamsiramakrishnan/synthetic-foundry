# Generating an enterprise corpus

An enterprise corpus has two independent scale problems:

1. one company's state must be large and evolve over time;
2. a dataset must contain many companies that are structurally different, not
   many renamings of one template.

Worldloom exposes separate controls for those problems. Use `build` for one
deep history. Use `mosaic` for a dispersed multi-company field. Use the SDK when
the selection logic itself is a Python program.

## Decide the corpus contract before its size

Record these choices before running a large build:

| Decision | Examples | Why it changes the corpus |
| --- | --- | --- |
| Evaluation job | retrieval, RAG citation, temporal QA, agent policy, document extraction | Determines which evidence, distractors, and hardness families matter |
| Enterprise breadth | one company, one vertical cohort, mixed vertical field | Determines whether `build`, `mosaic`, or SDK composition is appropriate |
| Time depth | one episode, recurring periods, eventful history | Enables supersession, trend, succession, and as-of questions |
| State scale | workforce, business units, sites, systems, services, master data | Controls the source graph from which artifacts and questions fan out |
| Artifact density | evaluation density, distractors, archive messiness | Controls evidence coverage and false friends, not canonical company size |
| Narrative mode | deterministic test prose or agent-written prose | Changes language quality and orchestration cost, not canonical truth |
| Output projection | JSONL, system bundles, XLSX, DOCX, PPTX, PDF, Markdown | Changes storage and render cost, not the underlying world |
| Reproducibility | seed, version, plan, model ID, prompt version | Makes a benchmark citable and replayable |

The counterfactual is important: increasing `--employees` alone does not create
more named authors, documents, or periods. It changes authoritative workforce
scale and the event-density model. Named employees remain a bounded operating
graph so a million-person company is not represented as a million Python objects.

## One large enterprise over time

The following profile builds a six-period retail history with a growing workforce
and independently changing structural estate:

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
```

The initial counts come from the built world. Each final count is an independent
anchor. Intermediate values are deterministically interpolated and materialized
as explicit scenario steps.

```text
period 1        period 2        period 3        period 4        period 5        period 6
   |               |               |               |               |               |
80,000 --------> 82,400 --------> 84,800 --------> 87,200 --------> 89,600 --------> 92,000
   |               |               |               |               |               |
 estate ---------- grow/retire ---- estate ---------- grow/retire ---- estate ------ target
   |               |               |               |               |               |
 close + facts     close + events  close + facts     close + events  close + facts   close
```

Every workforce movement emits authoritative headcount and signed-delta facts plus
a personnel notice. Every structural movement emits current count, signed-delta
facts, and an estate notice. Recipe steps preserve the exact intermediate path.

### Growth and contraction semantics

Growth appends deterministic entities. Contraction closes a half-open lifecycle
window; it does not delete historical rows. Therefore:

- current topology excludes retired systems and services;
- a historical artifact still resolves the entity that existed when it was
  written;
- as-of accessors reconstruct the active estate at any boundary;
- all-time graph validation can still detect historical dependency defects.

Unsafe targets are refused. A structural contraction cannot remove a business
unit required by people or categories, a system required by a service, or a
service required by the dependency graph. Named employees cannot exceed aggregate
workforce at any sampled or loaded boundary.

### Current vertical scope

Multi-period timelines and workforce/structural endpoints are implemented on the
retail CLI path. Banking, insurance, and procurement currently expose one bounded
episode per CLI build. Their episode cadence and carry-forward rules are not
simulated by pretending retail's history controls apply; unsupported combinations
are refused.

The SDK can run explicit scenario sequences, but doing so transfers responsibility
for the sequence to the caller. Use it when the history is intentional Python,
not as a way to bypass a CLI refusal.

## Increase evidence density deliberately

State scale and artifact scale are not interchangeable.

```bash
worldloom build \
  --seed 8128 \
  --periods 12 \
  --timeline turbulent \
  --comparatives 23 \
  --trend 0.004 \
  --estate large \
  --eval-density high \
  --distractors 40 \
  --messiness lived_in \
  --narrate \
  --out ./retrieval-corpus
```

- `--comparatives` and `--trend` create a direction-bearing financial series;
- `--timeline` schedules incidents and organisation changes between periods;
- `--eval-density` uses the world's size to add supported comparison and
  cross-period cases;
- `--distractors` adds provenance-true noise that answers no evaluation case;
- `--messiness` adds mechanically labelled stale, conflicting, or orphaned
  archive state without relaxing canonical coherence.

The Goodhart boundary is explicit: measure difficulty and select corpora, but do
not gradient-chase the built-in BM25 baseline. A corpus optimized specifically to
defeat one weak retriever can become less representative while its score looks
more impressive.

## Structured and unstructured projections

Build canonical state once, then choose the projections required by downstream
systems.

```bash
worldloom render ./enterprise \
  -f xlsx -f docx -f pptx -f pdf -f markdown \
  -f jira -f confluence -f servicenow
```

### Structured layer

The exported directory contains:

- `world.json`: schema version, generator version, company, entities, access
  policies, and recipe;
- `facts.jsonl`: authoritative, historical, and superseded facts;
- `events.jsonl`: enterprise events and causal links;
- `artifact-intents.jsonl`: artifact type, author, audience, evidence, and
  lineage before prose or rendering;
- `artifact-ir.jsonl`: resolved sections, tables, fact references, and metadata;
- `artifact-manifest.jsonl`: output files, authority, lifecycle, and provenance;
- `evals.jsonl`: questions, truth, evidence, distractors, cutoffs, and abstention;
- optional detail, master-data, generation-ledger, and actor-ledger files.

Portable Jira, Confluence, and ServiceNow bundles remain structured JSONL and can
be transformed into a connector's import shape without scraping rendered prose.

### Unstructured layer

DOCX, PDF, PPTX, and Markdown are projections of the same IR. They inherit the
same title, author, department, audience, scoped subjects, periods, and fact
references. XLSX is analytical rather than purely unstructured: its formulas,
named ranges, lineage, and reconciliation sheets are generated from the same fact
ledger.

For retrieval evaluation, ingest both native artifacts and their manifest. The
manifest is the authoritative source for access, lifecycle, revision,
restatement, and lineage metadata; attempting to infer those fields from body
text throws away ground truth the corpus already contains.

## Many unlike companies

A seed varies deterministic draws within one shape. It does not vary span of
control, reporting depth, estate size, trading calendar, or vertical physics.

`mosaic` generates a low-discrepancy candidate pool, filters infeasible and
domain-refused combinations, and selects the farthest-apart candidates. The
selection is deterministic and prefix-stable.

```bash
worldloom mosaic --describe
worldloom mosaic -n 25 --incident --out ./cohort
worldloom stats ./cohort/world-01 --json
```

Use `--engine banking` or `--engine insurance` for a vertical cohort. A domain
capability marked `single_episode` is never crossed with a multi-period candidate
inside the dispersed replay space.

When a settled probe defines the plausible bounds, it can replace the engine's
default axes:

```bash
worldloom probe open -p "A field-services business, 900 people, four regions."
worldloom probe next probe.json
worldloom probe show probe.json
worldloom mosaic --probe probe.json -n 20 --out ./field-services
```

The probe decides the envelope. Farthest-first selection decides which points
cover it. This division uses a model for semantic priors and an algorithm for
dispersion.

## Deterministic sharding

Every shard receives the complete plan arguments and shares one output root.

```text
                         mosaic.json
                      plan_digest = H(plan)
                              |
          +-------------------+-------------------+
          |                   |                   |
          v                   v                   v
      shard 0/20          shard 1/20          shard 19/20
    worlds 1,21,...     worlds 2,22,...      worlds 20,40,...
          |                   |                   |
          +-------------------+-------------------+
                              |
                              v
                   one deterministic corpus root
```

Ownership is:

```text
(world_index - 1) % shard_count == shard_index
```

Run workers independently:

```bash
worldloom mosaic -n 1000 \
  --shard-count 20 --shard-index 0 \
  --out ./enterprise-corpus

worldloom mosaic -n 1000 \
  --shard-count 20 --shard-index 1 \
  --out ./enterprise-corpus
```

Do not change `-n`, seed, engine, periods, formats, probe, narration mode, or
shard count between workers. The plan digest rejects drift instead of allowing
two different datasets to occupy one directory.

### Resume after interruption

Resume the same shard with the same arguments:

```bash
worldloom mosaic -n 1000 \
  --shard-count 20 --shard-index 0 \
  --out ./enterprise-corpus --resume
```

Resume does not trust file presence:

1. it verifies the global plan digest;
2. it verifies shard identity and state;
3. it loads and validates a completed world before skipping it;
4. it loads accepted section checkpoints for an incomplete world;
5. it truncates only an unterminated final checkpoint record;
6. it rejects malformed committed records;
7. it canonicalizes provisional checkpoint IDs so resumed and uninterrupted
   output remain byte-identical.

The checkpoint is a write-ahead log, not a cache. Treating a malformed committed
record as disposable would turn corruption into silent content loss.

## Narration modes at scale

### Deterministic test narration

`mosaic` narrates by default using the built-in deterministic provider. This is
the correct mode for CI, throughput characterization, byte-identity proofs, and
testing downstream ingestion. It is deliberately not a claim of editorial prose
quality.

Use `--narration-concurrency` to increase independent section generation within a
world. Assembly remains deterministic.

### Agent-written narration

For production-quality language, build plan-only worlds and let an agent harness
drive each world's request/accept loop:

```bash
worldloom mosaic -n 100 --no-narrate --out ./agent-corpus
worldloom status ./agent-corpus/world-01 --json
worldloom narrate requests ./agent-corpus/world-01 -o requests.json
worldloom narrate accept ./agent-corpus/world-01 \
  --from responses.json \
  --model-id enterprise-writer-v1 \
  --json
```

The request is the complete context boundary. A worker does not need access to
the Python object graph or another world's state. Store the accepted generation
ledger with the corpus; it is required for offline replay.

Operationally, partition agent work by world first and by request second. A
single artifact's sections can be independently proposed, but accepted content
must return to the correct corpus and model ID. Actor episodes are different:
decisions are sequential because later observations depend on earlier accepted
actions.

## Quality gates

Run these gates on every completed world or representative cohort:

```bash
worldloom validate ./enterprise --json
worldloom topology ./enterprise --json
worldloom series ./enterprise --json
worldloom diversity ./enterprise --near-duplicates --check-quotas
worldloom evaluate ./enterprise --retriever both --json
worldloom stats ./enterprise --json
```

| Gate | Failure means |
| --- | --- |
| `validate` | The corpus contradicts its own facts, graph, time, access, or lineage |
| `topology` | The estate may be flat, trivial, or dominated by unintended chokepoints |
| `series` | Trend and season may be absent or residual periods may be implausible |
| `diversity` | The batch may be one artifact grammar or repeated prose |
| `evaluate` | Evidence may be missing, the benchmark may be trivial, or a hardness family moved |
| `stats` | The actual corpus shape differs from the intended contract |

For large runs, do not validate only world 1. Select a dispersed regression sample
over vertical, locale, estate, facets, periods, and renderer formats. Rotating the
sample between CI runs improves coverage while each failed sample remains exactly
reproducible.

## Storage and throughput model

The main cost dimensions are:

```text
worlds x periods x artifact intents x narrative sections x output formats
```

They do not scale equally:

- canonical JSONL grows with entities, facts, events, and detail tables;
- narrative cost grows with section count, not with aggregate workforce;
- XLSX cost grows with detailed dimensions and formula-bearing rows;
- native document storage multiplies by selected formats;
- evaluation indexing grows with rendered passages and distractors;
- actor cost grows with sequential decisions and cannot be fully parallelized.

Generate canonical state and one cheap projection first. Measure the resulting
counts with `worldloom stats`. Add expensive native formats only after the shape
passes coherence, diversity, and difficulty gates. Rendering all formats during
initial parameter search wastes work without improving selection.

## Reproducibility manifest

Persist at least:

- Worldloom version and source commit;
- seed or mosaic base seed;
- complete CLI arguments or SDK blueprint descriptions;
- company specs, packs, probes, process/LOB definitions, and their versions;
- `mosaic.json` and plan digest;
- generation and actor ledgers;
- narrator model ID and prompt version;
- validation, diversity, topology, series, evaluation, and stats outputs;
- exact artifact file hashes for the released dataset.

The corpus already records most of this. The release process should retain the
remaining orchestration metadata beside it rather than in a separate wiki.

## Production checklist

- [ ] The evaluation job and hardness families are written down.
- [ ] The selected vertical actually implements the requested episode cadence.
- [ ] Workforce and structural endpoints remain above safe floors.
- [ ] The company field is dispersed, not a prefix of a Cartesian product.
- [ ] Narrative mode and model identity are explicit.
- [ ] All accepted ledgers are retained.
- [ ] Shards share one plan digest and do not overlap.
- [ ] Interrupted shards resume with identical plan arguments.
- [ ] Completed worlds pass validation before ingestion.
- [ ] Structured metadata is ingested with artifact bodies.
- [ ] Diversity, topology, series, and retrieval difficulty are measured
      independently.
- [ ] A replay sample matches the original file set and bytes.
- [ ] The released dataset records Worldloom version, config, hashes, and gates.

Scale is accepted only after semantics remain stable. A faster run that drops a
period, omits evidence, loses a checkpoint, or changes a replay byte is not an
optimization; it is a different corpus.
