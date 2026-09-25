# Worldloom documentation

Choose documentation by the result you need: a corpus, authored documents,
an evaluation workload, or a reproducible fleet. Worldloom generates canonical
state first, then validates artifacts and evaluation evidence against it.

For a first run, use [the repository quickstart](../README.md#quickstart).
For an enterprise dataset, define breadth and admission criteria before scaling.

## Choose a path

| Goal | Start here | Then read |
| --- | --- | --- |
| Explore, interview and generate one persistent company through a UI | [Worldloom Studio](studio.md) | [Company dataset and collection distinction](dataset-compiler.md) |
| Interview a company and reuse it across eval-driven candidates | [Company-driven campaign reuse](company-eval-reuse.md) | [Company specification](agents/company-specification.md) and [Narration rules](agents/writing-responses.md) |
| Measure executable enterprise coverage and real operational cases | [Enterprise qualification](enterprise-qualification.md) | [Measured module reuse and remaining gaps](enterprise-outcome-reuse.md) |
| Admit blind evidence, compare complete populations and calibrate noise | [Quality and calibration](quality-calibration.md) | [Company campaign ownership](company-eval-reuse.md) |
| Design an eval, then generate candidate corpora for it | [Eval-first generation](eval-first.md) | [Eval-first world compilation](eval-first-world-compilation.md) and [Python SDK](sdk.md) |
| Build one corpus | [README quickstart](../README.md#quickstart) | [Architecture and invariants](architecture.md) |
| Generate operational records and counterfactuals | [Operational synthesis](operational-synthesis.md) | [Agent skills](skills.md) |
| Compile a diverse queryset with quotas and isolated splits | [Dataset compiler](dataset-compiler.md) | [Qualification](enterprise-qualification.md) and [Quality gates](quality-calibration.md) |
| Generate a large enterprise dataset | [Enterprise corpus generation](enterprise-corpus.md) | [Generation model](generation-model.md) and [Artifact compiler](artifact-compiler.md) |
| Use Worldloom from Python | [Python SDK](sdk.md) | [Episode grammar](episode-grammar.md) |
| Drive Worldloom with a coding agent | [Agent skills](skills.md) | [AGENTS.md](../AGENTS.md) |
| Speak an industry's language, or change a prompt, default or connector without code | [Packs](packs.md) | [Studio](studio.md) |
| Add a company-specific vocabulary | [Lore](lore.md) | [Generation model](generation-model.md) |
| Add an artifact type | [Artifact compiler](artifact-compiler.md) | [Episode grammar](episode-grammar.md) |
| Add a process or vertical | [Episode grammar](episode-grammar.md) | [Build order](build-order.md) and [Actor simulation](actor-simulation.md) |
| Calibrate physics from real data, drive archive mess from a cause, or measure fidelity | [Extension seams](extension-seams.md) | [Architecture and invariants](architecture.md) |
| Score an agent against multi-connector workflows | [Agent workflow evals](agent-workflow-evals.md) | [Enterprise agent evals](enterprise-agent-evals.md) and [Eval-first generation](eval-first.md) |
| Run a corpus against Gemini Enterprise | [Gemini Enterprise](gemini-enterprise.md) | [Agent workflow evals](agent-workflow-evals.md) |
| Run an agent over a case set and grade plan, trajectory and outcomes | [Eval execution](eval-execution.md) | [Enterprise agent evals](enterprise-agent-evals.md) and [Connector serving](connector-serving.md) |
| Derive every line of business, process, request and count an industry implies | [Industry programme](industry-programme.md) | [Process bindings](process-bindings.md) and [Worldloom Studio](studio.md) |
| Read the process, occupation and function tables the company model is built from | [Reference data](reference-data.md) | [Industry programme](industry-programme.md) and [Process catalogue](process-catalogue.md) |
| Make rendered artifacts read like their real products | [Artifact ecology](artifact-ecology.md) | [Artifact compiler](artifact-compiler.md) |
| Look up an exact CLI flag | [Generated command reference](../.claude/skills/worldloom/references/commands.md) | The relevant workflow guide above |

## System map

```text
                         EVALUATION DESIGN
        +------------------------------------------------+
        | task DAG | capability | world predicates       |
        +------------------------+-----------------------+
                                 |
                         demand compiler
                                 |
                                 v
                         WORLD OBLIGATIONS
        +------------------------------------------------+
        | evidence | search | artifact | ACL | time      |
        +------------------------+-----------------------+
                                 |
                    tactics + candidate plans
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
                                 |       reference execution
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
exists. The demand compiler turns that problem into constructive world
obligations. Candidate generators own attempts. Independent validators decide
whether an attempt really makes the eval statically valid; reference execution
then proves the task is executable against an isolated fork. The accepted world
owns the oracle.

Agent handshakes may improve generation recipes, judgement, or wording under
bounded contracts, but no model gets to rewrite facts, hard predicates, oracle
rules, or acceptance gates.

World-first evaluation generation remains useful when inspecting an existing
corpus for what it happens to test. Eval-first generation is the preferred path
when the goal is to construct the benchmark deliberately.

## Operator guides

- [Eval-first generation](eval-first.md) explains `EvalSpec`, deterministic
  candidate plans, accepted/rejected campaign runs, oracle binding, paired
  eval+corpus export, and validity-first outcome diversity.
- [Eval-first world compilation](eval-first-world-compilation.md) explains the
  demand compiler, constructive witnesses and near-misses, constraint cover,
  frozen time, forked execution, proof gates, and unsat handling.
- [Architecture and invariants](architecture.md) explains the thin waist, fact
  ownership, artifact cohesion, temporal semantics, replay, and independent
  validation.
- [Enterprise corpus generation](enterprise-corpus.md) is the production
  runbook for histories, structured and unstructured projections, mosaics,
  deterministic sharding, checkpoints, resume, and acceptance gates.
- [Python SDK](sdk.md) documents immutable blueprints, combinators, measurements,
  scenarios, queries, rendering, and the CLI/SDK boundary.
- [Agent skills](skills.md) explains the stage commands and specialist skills
  shipped for coding agents, including how any terminal-capable harness uses the
  same protocols.

## Architecture references

These documents preserve design rationale and extension contracts:

| Document | Answers |
| --- | --- |
| [eval-first.md](eval-first.md) | How an eval defines the world conditions its candidate corpora must satisfy |
| [eval-first-world-compilation.md](eval-first-world-compilation.md) | How eval requirements become constructive world obligations and executable proofs |
| [design/eval-demand-compiler.md](design/eval-demand-compiler.md) | The thin-waist contract for demand normalization, tactics, and constraint cover |
| [design/reference-execution.md](design/reference-execution.md) | How isolated world forks prove generated evals are executable |
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

## Authored industry process planning

[Read the process catalogue](process-catalogue.md): value streams and activities keyed by APQC process id, compiled against a company into owners, countries, systems and seeded channels, then carried into the process authoring cascade.


## Audited process bindings

[Inspect activity bindings and evidence](process-bindings.md): shared-predicate search, structural ownership proofs, explicit coverage gaps and full export replay.

## The programme an industry implies

[Derive the whole evaluation programme](industry-programme.md) from a compiled catalogue: a line of business per owning function family, a request per situation with an asker who has standing, a fact per declared attribute, and a Studio use case per LOB × process whose count is derived rather than authored. Every system no connector emulates is named, never replaced.


## Reusable narration

[Narration programs](narration-programs.md) covers family-level authoring, bounded fact substitution, dependency caches, measured diversity, blind reader checks and offline replay.
