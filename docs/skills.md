# Using Worldloom with coding agents

Worldloom is agent-neutral at runtime. Its contracts are commands, JSON requests,
JSON responses, and deterministic accept/refuse results. The repository also
ships Claude Code commands and skills that encode the operating procedure with
progressive disclosure.

```text
coding agent
    |
    | shell + JSON
    v
Worldloom CLI -----> deterministic request
    ^                        |
    |                        v
    +---- accept/refuse <---- agent proposal
              |
              v
       generation ledger
```

The agent is not given unrestricted access to mutate a `World`. It receives the
bounded projection required for one decision and proposes a typed response.

## Discovery

When Claude Code opens the repository root, it can discover:

- `.claude/commands/`: stage-oriented slash commands;
- `.claude/skills/`: specialist procedures with trigger descriptions;
- `.claude/skills/worldloom/references/`: progressively disclosed operational
  detail and the generated CLI reference;
- `AGENTS.md`: the harness-wide truth, narration, determinism, and extension
  contract.

No files need to be copied into generated corpora. They are the procedure for the
agent operating the repository.

For another coding harness, point it to [AGENTS.md](../AGENTS.md) and let it drive
the same commands. No Claude-specific API participates in corpus generation.

## Stage commands

Use a stage command when the company and task are already decided.

| Command | Responsibility | Reads next |
| --- | --- | --- |
| `/worldloom-build` | Build a deterministic world and report its actual shape | `references/building.md` |
| `/worldloom-act` | Become each employee in a bounded actor episode | `references/acting.md` |
| `/worldloom-narrate` | Write fact-scoped sections until accepted | `references/writing-prose.md` |
| `/worldloom-render` | Materialize native artifacts and validate | `references/rendering.md` |
| `/worldloom-evaluate` | Measure difficulty, shape, diversity, and retrieval behavior | `references/evaluating.md` and `references/diversity.md` |

The agent should surface the result of every gate rather than silently running the
whole pipeline. Build counts, actor observations, narration refusals, validation
check counts, diversity readings, and per-family evaluation scores are part of
the deliverable.

## Open-ended design

Use `/worldloom-design` when the request names a purpose or industry but not a
fully decided seed, shape, hardness profile, narrative mode, and output set.

```text
decide --> author if necessary --> build --> measure --> select
   ^                                                  |
   |                                                  v
   +---------------- revise <--------------------- narrate/render
```

The design command first extracts decisions already present in the request. It
asks only for material missing choices. It then chooses between:

- a shipped vertical and ordinary build flags;
- a company specification;
- a pack or facet composition;
- a probe-derived physics space;
- an authored document type, LOB, or process;
- a new vertical when the requested causal episode is genuinely different;
- the SDK when the arrangement is a loop rather than a command.

Measurement closes the loop. `validate`, `topology`, `series`, `diversity`,
`evaluate`, and `stats` answer independent questions and should not be collapsed
into one quality score.

## Specialist skills

### `worldloom`

The primary end-to-end operator skill. Use it for a decided corpus generation
journey: build, optional act/plan, narrate, render, validate, and evaluate.

Source: [`.claude/skills/worldloom/SKILL.md`](../.claude/skills/worldloom/SKILL.md)

### `worldloom-company`

Use one company specification instead of assembling archetype, workforce,
facets, locale, estate, physics, pack, vocabulary, and revenue across separate
surfaces. The resolver reports contradictions and unmet consequences before
build.

Source: [`.claude/skills/worldloom-company/SKILL.md`](../.claude/skills/worldloom-company/SKILL.md)

### `worldloom-probe`

Derive world physics by descending organisation, reporting, roles, objectives,
and measures. Answers narrow intervals and declare links; arc consistency refuses
an empty solution space. Use this when the business shape cannot be responsibly
expressed as a list of remembered parameter values.

Source: [`.claude/skills/worldloom-probe/SKILL.md`](../.claude/skills/worldloom-probe/SKILL.md)

### `worldloom-sdk`

Write Python against immutable blueprints. Use it for crosses, sweeps, dispersed
selection, measured filters, explicit scenario sequences, or any request whose
natural answer contains a loop.

Source: [`.claude/skills/worldloom-sdk/SKILL.md`](../.claude/skills/worldloom-sdk/SKILL.md)

### `worldloom-author`

Author a complete company top-down: identity, lines of business, processes, and
paperwork. It coordinates the same refusable cascade at every layer rather than
treating each JSON file as independent configuration.

Source: [`.claude/skills/worldloom-author/SKILL.md`](../.claude/skills/worldloom-author/SKILL.md)

### `worldloom-doctypes`

Give a company a document family the engine does not ship. The type declares
standing, lifecycle, lag, sections, fact-kind selectors, authorship domain, and
filing triggers. Lint rejects inert or undeclared kinds before a corpus is built.

Source: [`.claude/skills/worldloom-doctypes/SKILL.md`](../.claude/skills/worldloom-doctypes/SKILL.md)

### `worldloom-lob`

Author roles, responsibility edges, lore, and process-slot bindings for a line of
business. Participation and access consequences are derived from those edges;
they are not maintained as a parallel manual roster.

Source: [`.claude/skills/worldloom-lob/SKILL.md`](../.claude/skills/worldloom-lob/SKILL.md)

### `worldloom-process`

Author a recurring business process through seed, step, fact-kind, and role-slot
stages. The resolved `EpisodeSpec` installs, runs, and replays; the authoring
conversation is not part of the runtime recipe.

Source: [`.claude/skills/worldloom-process/SKILL.md`](../.claude/skills/worldloom-process/SKILL.md)

### `worldloom-vertical`

Add a causal episode with its own documents, fact kinds, invariants, and
benchmark. This is the most expensive extension and should be selected only when
a pack or process cannot express what happens.

Source: [`.claude/skills/worldloom-vertical/SKILL.md`](../.claude/skills/worldloom-vertical/SKILL.md)

## One cascade, reused everywhere

The authorable layers share one mechanism from `worldloom.cascade`:

```text
seed
  |
  v
Session --> Brief(context + constraints)
  |                    |
  |                    v
  +---------------> proposal
                        |
                        v
                      lint
                    /      \
             findings      accepted
                |              |
                v              v
              revise        resolve
                               |
                               v
                         install + replay
```

A lint returns every actionable finding in one pass. It does not mutate the
proposal or silently remove unsupported clauses. This keeps authoring loops
mechanically consistent across company, document, LOB, process, and vertical
layers.

## Core request/accept protocols

### Artifact planning

```bash
worldloom plan requests ./corpus -o plans.json
worldloom plan accept ./corpus \
  --from plans.json \
  --model-id enterprise-planner-v1 \
  --json
```

The planner proposes sections and purposes under the artifact grammar. It cannot
change the artifact's type, author, audience, or evidence scope.

### Narration

```bash
worldloom narrate requests ./corpus -o requests.json
worldloom narrate accept ./corpus \
  --from responses.json \
  --model-id enterprise-writer-v1 \
  --json
```

Narration requests are independent by section. Workers may propose them in
parallel; acceptance binds each response to the exact request and corpus ledger.

### Actor decisions

```bash
worldloom act requests ./corpus -o decision.json
worldloom act accept ./corpus \
  --from action.json \
  --model-id enterprise-actor-v1 \
  --json
```

Actor decisions are sequential. The next observation does not exist until the
previous action is accepted and executed. Parallelizing one episode's decisions
would change causality, not merely throughput.

### Estate composition

```bash
worldloom compose requests ./corpus -o estate.json
worldloom compose accept ./corpus \
  --from estate.json \
  --model-id enterprise-architect-v1 \
  --json
```

The response can propose systems, services, dependencies, owners, and lore. The
graph gate refuses cycles, missing dependencies, impossible owners, unsupported
criticality, inert lore, and an estate with no meaningful failure structure.

### Probe

```bash
worldloom probe open -p "A field-services business, 900 people, four regions."
worldloom probe next probe.json
worldloom probe accept probe.json --from answer.json
worldloom probe resolve probe.json -o physics.json
```

Each answer may narrow the offered interval or raise linked subquestions. It may
not widen constraints established by earlier layers.

## Progressive disclosure

The main skill intentionally does not load every reference at startup. Each stage
opens only the procedure it needs:

| Reference | Load when |
| --- | --- |
| `designing.md` | Turning an open-ended ask into a defensible corpus contract |
| `building.md` | Choosing seeds, verticals, scale, timelines, and company shape |
| `acting.md` | Making one employee decision from scoped observations |
| `planning-structure.md` | Proposing document sections under a grammar |
| `writing-prose.md` | Producing claims and fact references after a refusal |
| `rendering.md` | Selecting native output formats |
| `evaluating.md` | Reading retriever-family scores and citations |
| `diversity.md` | Measuring structural and prose repetition |
| `extending.md` | Changing the harness or adding a seam |
| `commands.md` | Looking up exact command and option spelling |

The generated command reference is exhaustive but not an operating procedure.
Loading it for every task spends context on flags irrelevant to the current
stage. Conversely, relying only on a procedural skill makes exact flag spelling
easy to stale. Progressive disclosure keeps the two roles separate.

## Rules for agent implementations

1. Treat each emitted request as the complete authority boundary. Do not search
   the corpus for facts the request withheld.
2. Never respond to a refusal by editing canonical facts, dropping required
   evidence, or weakening validation.
3. Preserve request IDs exactly. They bind proposals to ledger keys.
4. Pin `--model-id` for a resumed protocol. Changing it can change ledger
   identity and replay behavior.
5. Reference figures using fact placeholders. Do not copy digits into prose.
6. Persist accepted ledgers with the corpus.
7. Use `worldloom status` to resume; do not infer stage from filenames.
8. Report refusals and measurement results to the user. They are evidence that
   the guardrail ran.
9. Use the SDK for loops, not shell-generated pseudo-APIs or new one-off flags.
10. Keep deterministic state changes behind scenarios and typed tools.

## Harness-neutral orchestration

An external agent runner needs only four operations:

```text
run(command) -> stdout/stderr/exit code
read(JSON request)
write(JSON proposal)
repeat until accept or terminal completion
```

Exit codes and `--json` responses distinguish completion, refusal, and execution
failure. A large deployment can assign one worker per world because world
directories and ledgers are independent. Within one world, narration sections
may be proposed concurrently; actor decisions may not.

`worldloom mcp` exposes read-only measurements and gates over stdio for harnesses
that prefer tools:

```bash
worldloom mcp --tools
```

Corpus writes remain behind request/accept handshakes. The MCP server does not
create an unvalidated mutation path.

## Verification before changing a skill

Agent-facing documents are executable interface surface. Before publishing a
change:

```bash
worldloom docs --check
pytest -q tests/test_harness_docs.py
worldloom validate retail-close
```

The harness-doc test parses documented invocations and rejects unknown commands
or flags. New operator pages are included in that gate, and their local links are
verified. A skill that advertises an obsolete option is a product bug because it
causes an agent to build the wrong corpus while believing the request succeeded.

## Operational data and behavioral search

The `worldloom-synthesis` skill covers causal record programs, conservation
checks, paired interventions, deterministic sharding, behavioral archives and
designer/critic executable teams. See [operational synthesis](operational-synthesis.md).
Ordinary generation and replay do not call a model. External commands execute
only when explicitly configured; critics cannot override mechanical acceptance.
