# Worldloom documentation

Worldloom is a deterministic, library-first compiler for synthetic enterprise
corpora and the evaluations those corpora are built to support. The documentation
is organized by the job being done, not by the source tree.

## Choose a path

| Goal | Start here | Then read |
| --- | --- | --- |
| Design an eval, then generate candidate corpora for it | [Eval-first generation](eval-first.md) | [Enterprise corpus generation](enterprise-corpus.md) and [Python SDK](sdk.md) |
| Build one corpus | [README quickstart](../README.md#quickstart-one-coherent-enterprise) | [Architecture and invariants](architecture.md) |
| Generate operational records and counterfactuals | [Operational synthesis](operational-synthesis.md) | [Agent skills](skills.md) |
| Generate a large enterprise dataset | [Enterprise corpus generation](enterprise-corpus.md) | [Generation model](generation-model.md) and [Artifact compiler](artifact-compiler.md) |
| Use Worldloom from Python | [Python SDK](sdk.md) | [Episode grammar](episode-grammar.md) |
| Drive Worldloom with a coding agent | [Agent skills](skills.md) | [AGENTS.md](../AGENTS.md) |
| Add a company-specific vocabulary | [Lore](lore.md) | [Generation model](generation-model.md) |
| Add an artifact type | [Artifact compiler](artifact-compiler.md) | [Episode grammar](episode-grammar.md) |
| Add a process or vertical | [Episode grammar](episode-grammar.md) | [Build order](build-order.md) and [Actor simulation](actor-simulation.md) |
| Look up an exact CLI flag | [Generated command reference](../.claude/skills/worldloom/references/commands.md) | The relevant workflow guide above |

## System map

```text
                         EVALUATION DESIGN
        +------------------------------------------------+
        | task DAG | capability | world predicates       |
        +------------------------+-----------------------+
                                 |
                         candidate plans
                                 |
                                 v
                         AUTHORING TIME
        +------------------------------------------------+
        | company spec | pack | facets | lore | process |
        +------------------------+-----------------------+
                                 |
                                 v
                         DETERMINISTIC CORE
        +------------------------------------------------+
        | world | graph | events | facts | access | evals|
        +------------------------+-----------------------+
                                 |
                    independent requirement checks
                                 |
                       +---------+---------+
                       | reject / search  | accept
                       +---------+---------+
                                 |             |
                                 |             v
                                 |       bound eval oracle
                                 |             |
                                 +-------------+
                                               |
                                     intents + bounded requests
                                               |
                                               v
                                      AGENT HANDSHAKES
        +------------------------------------------------+
        | plan | act | narrate | compose | probe         |
        +------------------------+-----------------------+
                                 |
                           accepted ledger
                                 |
                                 v
                         ARTIFACT COMPILER
        +------------------------------------------------+
        | ArtifactIR | cohesion | style | components     |
        +------------------------+-----------------------+
                                 |
                                 v
        +---------+---------+---------+---------+--------+
        | XLSX    | DOCX    | PPTX    | PDF     | JSONL  |
        | Markdown| Jira    | Confluence       | SNOW    |
        +---------+---------+---------+---------+--------+
```

For benchmark construction, evaluation design owns the problem before a corpus
exists. Candidate generators own attempts. Independent validators decide whether
an attempt really makes the eval solvable. The accepted world then owns the
oracle. Agent handshakes may improve judgement or wording under bounded
contracts, but no model gets to rewrite facts, hard predicates, or acceptance
rules.

World-first evaluation generation remains useful when inspecting an existing
corpus for what it happens to test. Eval-first generation is the preferred path
when the goal is to construct the benchmark deliberately.

## Operator guides

- [Eval-first generation](eval-first.md) explains `EvalSpec`, deterministic
  candidate plans, accepted/rejected campaign runs, oracle binding, paired
  eval+corpus export, and validity-first outcome diversity.
- [Architecture and invariants](architecture.md) explains the thin waist, fact
  ownership, artifact cohesion, temporal semantics, replay, and independent
  validation.
- [Enterprise corpus generation](enterprise-corpus.md) is the production
  runbook for histories, structured and unstructured projections, mosaics,
  deterministic sharding, checkpoints, resume, and acceptance gates.
- [Python SDK](sdk.md) documents immutable blueprints, combinators, measurements,
  scenarios, queries, rendering, and the CLI/SDK boundary.
- [Agent skills](skills.md) explains the stage commands and specialist skills
  shipped in `.claude/`, including how another terminal-capable harness uses the
  same protocols.

## Architecture references

These documents preserve design rationale and extension contracts:

| Document | Answers |
| --- | --- |
| [eval-first.md](eval-first.md) | How an eval defines the world conditions its candidate corpora must satisfy |
| [generation-model.md](generation-model.md) | Which engine owns each decision, and why |
| [lore.md](lore.md) | How historical priors constrain generated state |
| [artifact-compiler.md](artifact-compiler.md) | How one resolved IR becomes diverse native artifacts without semantic drift |
| [episode-grammar.md](episode-grammar.md) | How processes declare phases, facts, slots, carry-forward, and lints |
| [actor-simulation.md](actor-simulation.md) | How employees act on scoped observations through typed tools |
| [build-order.md](build-order.md) | Why subsystems landed in this order and which gate each must pass |
| [next-phase-plan.md](next-phase-plan.md) | The process/LOB authoring plan and remaining seams |
| [design/insurance-reserving.md](design/insurance-reserving.md) | The decision record for the insurance vertical |

## Documentation reliability

The exact CLI reference is generated from Typer by `worldloom docs`; it is not
maintained by hand. CI also parses every command and option in the agent-facing
documents and verifies that it exists. The documentation index and every new
operator guide are link-checked locally.

```bash
worldloom docs --check
pytest -q tests/test_harness_docs.py
```

When prose and implementation disagree, implementation is not silently treated
as truth. Either the documentation is stale or the public surface regressed; the
failing check forces that decision into the change that caused it.