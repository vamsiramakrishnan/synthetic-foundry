# Worldloom

**Build an enterprise corpus whose documents, records, and evaluation answers share the same facts.**

Worldloom generates a company and its history, then renders that state into
workbooks, documents, slides, PDFs, tickets, and knowledge pages. It also
creates evaluation cases tied to the evidence in the corpus.

Use it to test retrieval, document extraction, temporal questions, and agent
workflows before you have a suitable enterprise dataset. A seed and recipe
control the world; accepted generation ledgers make authored material replayable.

Repository `synthetic-foundry` · Python package and command `worldloom` ·
Python 3.11+ · pre-release, install from source · Apache-2.0

[Quickstart](#quickstart) · [Design a corpus](docs/enterprise-corpus.md) ·
[Python SDK](docs/sdk.md) · [Documentation site](https://vamsiramakrishnan.github.io/synthetic-foundry/)

## Quickstart

Create one local corpus with deterministic sample prose. No model service or
credentials are required:

```bash
git clone https://github.com/vamsiramakrishnan/synthetic-foundry.git
cd synthetic-foundry
python -m venv .venv
source .venv/bin/activate
python -m pip install -e '.[all]'

worldloom build --seed 8128 --incident --narrate --out ./corpus
worldloom render ./corpus -f xlsx -f docx -f pptx -f pdf -f markdown
worldloom validate ./corpus
worldloom evaluate ./corpus --retriever both
worldloom status ./corpus
```

The default example is a retailer's month-end close with an incident. It is a
bounded business episode, not a full retailer's operating history. The prose
is deterministic test material; use the [narration workflow](#add-agent-authored-prose)
when language quality is part of the evaluation.

Inspect the generated files alongside the facts and evaluation records.
`validate` checks their relationships; `evaluate` measures retrieval against
the included cases. A passing validator does not establish realism or strong
retrieval performance. `status` identifies the next incomplete stage.

## Choose the dataset by the test it must support

| Test | Build into the corpus | Start here |
|---|---|---|
| Retrieval and cited answers | Relevant evidence, distractors, and answer/evidence bindings | [Eval-first generation](docs/eval-first.md) |
| Spreadsheet and document extraction | Consistent amounts, identities, tables, and artifact families | [Artifact compiler](docs/artifact-compiler.md) |
| Questions about what was known at a date | Timelines, supersession, and bounded knowledge cutoffs | [Generation model](docs/generation-model.md) |
| Agent work across business systems | Connector records, relationships, permissions, and trace checks | [Connector emulation](docs/agent-workflow-evals.md) |
| Broad enterprise coverage | Several processes, periods, estate entities, and document families | [Enterprise corpus generation](docs/enterprise-corpus.md) |
| Operational trajectories and interventions | Stateful records and explicit transitions | [Operational synthesis](docs/operational-synthesis.md) |

Increasing headcount does not by itself create more documents or business
processes. Named employees form a bounded operating graph; aggregate workforce
scale remains aggregate. Choose business breadth, time depth, and artifact
density independently.

## What makes the files belong to one company

The world owns facts before a renderer or writer sees them. Artifact plans
select the relevant facts, authors, audience, and time. Renderers consume the
resolved artifact representation.

| Relationship | What can be checked |
|---|---|
| A workbook total and a report's financial claim | Both resolve to canonical facts; totals reconcile |
| A ticket and its employee or system | References resolve to entities in the world |
| An author's statement and its date | The claim respects the artifact's knowledge cutoff |
| A question and its expected answer | Supporting evidence exists in the generated corpus |
| A stale or defective document | The intentional defect is recorded and reproducible |

These checks establish declared consistency. They do not establish that the
enterprise resembles a particular real customer. Measure coherence, realism,
diversity, and task difficulty separately.

## Output surfaces

| Surface | Intended use |
|---|---|
| Facts, events, relationships, recipes, and ledgers | Ground truth, inspection, and replay |
| XLSX, DOCX, PDF, PPTX, Markdown | Ingestion, extraction, retrieval, and presentation tests |
| Jira, Confluence, ServiceNow bundles | Business-system-shaped source material |
| Evaluation cases and validation reports | Answer/evidence checks and corpus qualification |
| Permissioned drive layout | File organization and access-aware scenarios |

Add business-system renderings or a drive layout to the same corpus:

```bash
worldloom render ./corpus -f jira -f confluence -f servicenow
worldloom workspace ./corpus -o ./drive
```

These are generated artifacts and local representations. Rendering a Jira or
ServiceNow bundle does not write to a live tenant.

## Add agent-authored prose

Worldloom does not call an LLM. Your coding agent or external writer supplies
prose through a request/accept contract:

```bash
worldloom narrate requests ./corpus -o requests.json
# The writer reads requests.json and produces responses.json.
worldloom narrate accept ./corpus --from responses.json --model-id your-writer
```

Each request carries allowed facts, required facts, author, audience, and a
knowledge cutoff. Use the request's fact references; unsupported figures or
claims can be rejected. Re-render and validate after acceptance.

For a new authored run, build without `--narrate` so requests remain pending.
The quickstart's deterministic prose is already filled.
[Response contract](docs/agents/writing-responses.md) · [Agent workflows](docs/skills.md).

## Grow beyond the first episode

Built-in causal episode families include retail `MonthEndClose`, banking
`QuarterlyCapitalReturn`, insurance `QuarterlyReserving`, and procurement
`PurchaseToPayCycle`. Company packs change enterprise shape; new processes and
artifact families require their own generation and validation contracts.

For one deep history, use `build`. For a population of different companies, use
`mosaic`. For coverage across combinations, use `spaces` before spending on
large fleets:

```bash
worldloom spaces --cover -t 2 > plan.jsonl
worldloom spaces --holes plan.jsonl
worldloom mosaic -n 20 --incident --out ./fleet
worldloom fleet qualify ./fleet --purpose challenge
worldloom fleet curate ./fleet --purpose challenge
```

Start with a small qualified corpus before scaling. Fleet counts measure volume;
qualification and coverage determine whether that volume helps the evaluation.
[Enterprise generation](docs/enterprise-corpus.md) · [Artifact ecology](docs/artifact-ecology.md).

## Reproduce and extend

Replay is scoped to the recorded recipe, accepted ledger, and compatible code
revision. CI runs determinism and dispersed replay checks. Preserve those inputs
with a benchmark result; a seed alone does not describe an externally authored run.

The Python SDK exposes the same world, generation, rendering, and validation
contracts. Extension seams cover company packs, episodes, artifact families,
calibrated priors, and external proposals.

[SDK](docs/sdk.md) · [Extension seams](docs/extension-seams.md) ·
[Architecture](docs/architecture.md) · [Full documentation map](docs/README.md)

## Development

```bash
python -m pip install -e '.[all,dev]'
pytest
worldloom docs --check
```

Follow [CONTRIBUTING.md](CONTRIBUTING.md). Changes to generation must preserve
replay or explicitly declare the compatibility change. See [LICENSE](LICENSE).
