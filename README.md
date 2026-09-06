# Worldloom

Worldloom generates synthetic enterprise corpora from a deterministic world model.

It creates the company state, events, facts, relationships, and timelines first. Documents, tickets, workbooks, slides, connector records, and evaluation cases are then rendered from that state.

That ordering lets the validator check cross-artifact claims instead of asking a model to keep independently generated files consistent.

[![ci](https://github.com/vamsiramakrishnan/synthetic-foundry/actions/workflows/ci.yml/badge.svg)](https://github.com/vamsiramakrishnan/synthetic-foundry/actions/workflows/ci.yml)
[![determinism sweep](https://github.com/vamsiramakrishnan/synthetic-foundry/actions/workflows/determinism-sweep.yml/badge.svg)](https://github.com/vamsiramakrishnan/synthetic-foundry/actions/workflows/determinism-sweep.yml)
[![docs](https://img.shields.io/badge/docs-site-blue)](https://vamsiramakrishnan.github.io/synthetic-foundry/)
[![license: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)

Status: pre-release. Install from a clone. The library does not call an LLM service by itself.

## What it produces

A build can contain:

- canonical facts and event history;
- DOCX, PDF, PPTX, XLSX, Markdown, Jira, Confluence, and ServiceNow artifacts;
- people, business units, sites, systems, services, and lifecycle changes;
- intentional document defects recorded in a ledger;
- retrieval and evaluation cases tied to the facts that support them;
- provenance linking rendered claims back to world state;
- validation results for arithmetic, identity, chronology, reachability, and artifact contracts.

The current default retail seed used by the repository examples produces 615 facts, 16 rendered artifacts, 51 evaluation cases, and 8,861 validation checks. Treat those numbers as fixture output, not as a fixed product limit.

## Quickstart

```bash
git clone https://github.com/vamsiramakrishnan/synthetic-foundry.git
cd synthetic-foundry
pip install -e ".[all]"

worldloom doctor
worldloom build --seed 8128 --incident --narrate --out ./corpus
worldloom validate ./corpus
```

Render additional surfaces:

```bash
worldloom render ./corpus \
  -f xlsx \
  -f docx \
  -f pptx \
  -f pdf \
  -f markdown \
  -f jira \
  -f confluence \
  -f servicenow
```

Inspect and evaluate the result:

```bash
worldloom evaluate ./corpus --retriever both
worldloom status ./corpus
worldloom topology ./corpus
worldloom series ./corpus
worldloom diversity ./corpus --near-duplicates
```

`worldloom status` reports the first action still required when a build is incomplete or invalid.

## Generation model

```text
recipe
  │
  ▼
world state
  │
  ├── organisation
  ├── people
  ├── estate
  ├── timelines
  └── events
  │
  ▼
canonical facts
  │
  ▼
artifact plan
  │
  ▼
ArtifactIR
  │
  ├── XLSX
  ├── DOCX
  ├── PDF
  ├── PPTX
  ├── Markdown
  ├── Jira
  ├── Confluence
  └── ServiceNow
```

Renderers consume resolved artifact state. They do not decide company facts, arithmetic, authorship, or chronology.

## Determinism

A recipe records the inputs needed to rebuild a world. The determinism tests compare regenerated output against the same recipe and seed.

The library avoids clock-derived IDs and uncontrolled randomness in the generation path. The repository also runs dispersed replay checks in CI.

A deterministic build only proves replay for the tested inputs and code revision. It does not prove that every corpus is realistic or useful for every evaluation task. Realism, diversity, and coherence are measured separately.

## Coherence

Worldloom validates claims against canonical state rather than treating agreement between two generated documents as sufficient evidence.

Examples of checks include:

- totals reconcile with their components;
- rates are not summed as amounts;
- an artifact author exists at the relevant time;
- a document does not cite facts created after its knowledge cutoff;
- titles and sections match the artifact family contract;
- a ticket cannot reference a missing employee or system;
- evaluation answers point to generated evidence;
- intentionally broken artifacts are recorded and reproducible.

Validation failures return the violated rule rather than silently changing the world to fit the artifact.

## Vertical packs

The repository currently includes four causal episode families:

| Vertical | Episode |
| --- | --- |
| Retail | `MonthEndClose` |
| Banking | `QuarterlyCapitalReturn` |
| Insurance | `QuarterlyReserving` |
| Procurement | `PurchaseToPayCycle` |

A vertical defines the episode, fact kinds, document families, invariants, and benchmark behavior. Company packs change the enterprise shape while reusing an episode.

See the docs site for the vertical registration interfaces and authoring workflow.

## Organisation and history

Worldloom can vary workforce scale, business units, sites, systems, services, and reporting periods.

Named employees are a bounded decision-making graph. Aggregate headcount remains aggregate rather than creating one Python object per employee.

Estate entities use time-bounded lifecycles so historical artifacts can keep references to organisations and systems that later changed or disappeared.

## Operational synthesis

The optional operational layer generates stateful records such as inventory and loan-servicing trajectories with explicit relationships and transition checks.

It can produce exception histories and connector-style source data for downstream evaluation without changing existing world recipes.

See [`docs/operational-synthesis.md`](docs/operational-synthesis.md).

## Calibration, causal mess and fidelity

Three proposal seams sit outside the deterministic boundary, each leaving a content-addressed receipt: `worldloom calibrate` learns physics ranges from a sensitive table under differential privacy (only ranges cross, never rows) for `build --priors`; `build --causal` drives the archive's stale and disagreeing documents from a declared cause — a DAG whose every derived value the validator recomputes — and records the trace as `causal.jsonl`; `worldloom fidelity` compares a synthetic table with a real one as a vector, never a score. Vendor registers gain checksum-valid, locale-correct identifiers with `"master_data": {"identifiers": 1}`.

See [`docs/extension-seams.md`](docs/extension-seams.md).

## Agent-authored prose

Worldloom does not import an LLM SDK. A coding agent or other external writer can request narration work over JSON and submit the result for validation.

```bash
worldloom narrate requests ./corpus -o requests.json
# external writer produces responses.json
worldloom narrate accept ./corpus \
  --from responses.json \
  --model-id enterprise-writer-v1
```

Each request includes the artifact family, section, author, audience, knowledge cutoff, allowed facts, required facts, and prohibited claims.

Acceptance checks the response before committing it to the corpus. A response can be rejected for an invalid author, out-of-scope fact, future knowledge, or unsupported numeric claim.

The built-in deterministic narrator exists for tests, replay, and inspection. It is not intended to substitute for production prose quality.

## Fleet generation

Large evaluation programs often need coverage across many world configurations rather than many copies of one configuration.

Worldloom includes commands for planning, sharding, qualification, curation, mutation, counterfactual twins, and deterministic evolutionary search:

```bash
worldloom spaces --cover -t 2 > plan.jsonl
worldloom mosaic -n 20 --incident --out ./fleet
worldloom spaces --holes plan.jsonl
worldloom fleet qualify ./fleet --purpose challenge
worldloom fleet curate ./fleet --purpose challenge
worldloom evolve --generations 3 --population 6 --purpose challenge --out ./evolved
```

`spaces --cover` uses covering-array planning to reduce the number of builds needed to exercise combinations of configuration axes. `spaces --holes` reports combinations the current plan did not cover.

The evolutionary path mutates recipes and uses deterministic qualification/curation rules. Optional AlphaEvolve integration is restricted to the policy surface documented in [`docs/ALPHAEVOLVE-OPTIMIZATION.md`](docs/ALPHAEVOLVE-OPTIMIZATION.md).

## Search and retrieval evaluation

```bash
worldloom search ./corpus "operational incident" -k 3
worldloom search ./corpus "operational incident" -k 3 --as-of 2026-06-30
worldloom evaluate ./corpus --retriever both
```

Search uses the same corpus evidence that evaluation cases reference. `--as-of` limits retrieval to material available before the supplied cutoff.

## Repository map

```text
worldloom/        library and CLI
worldloom/...     world, episode, artifact, validation and evaluation modules
tests/            deterministic and behavioral checks
docs/             guides and architecture notes
evals/            mechanism and benchmark receipts
```

For the full API and command reference, use the [documentation site](https://vamsiramakrishnan.github.io/synthetic-foundry/).

## Development

```bash
git clone https://github.com/vamsiramakrishnan/synthetic-foundry.git
cd synthetic-foundry
pip install -e ".[all,dev]"
pytest
```

Before changing a generation invariant, add or update the test that establishes the intended behavior.

## License

Apache-2.0. See [LICENSE](LICENSE).
