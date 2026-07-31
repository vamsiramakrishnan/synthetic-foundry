# Worldloom design documents

Worldloom is being implemented as a deterministic, library-first harness. These documents are the architectural contracts for what has landed and what comes next.

| Document | Answers |
| --- | --- |
| [build-order.md](build-order.md) | What gets built, in what order, what has landed, and what gate each step must pass |
| [generation-model.md](generation-model.md) | Which engine owns what, across all twenty generation areas |
| [lore.md](lore.md) | What lore is as a data structure, and how lore generators are authored |
| [artifact-compiler.md](artifact-compiler.md) | How one resolved ArtifactIR becomes diverse PPTX, DOCX, XLSX, and PDF outputs through components, grammars, constraints, validation, and bounded repair |
| [actor-simulation.md](actor-simulation.md) | How role-scoped LLM employees use typed tools to produce events, facts, tasks, and artifact intents without owning canonical truth |

Read the build order first. The generation model is the ownership contract. Lore supplies the priors from which a world is derived. The artifact compiler extends the existing renderer boundary without allowing formats or models to invent truth. The actor roadmap comes after the second vertical and executable world-state work; it adds role-driven behaviour without turning Worldloom into an unconstrained multi-agent framework.

## The five load-bearing decisions

**The generation boundary.** The deterministic engine owns everything that must be *correct* — arithmetic, identity, referential integrity, the graph, the timeline, permissions. The generative engine owns everything that must be *plausible*. Nothing is owned by both. → [generation-model.md](generation-model.md)

**Determinism survives the LLM.** Every generative call is content-addressed into a generation ledger keyed by seed, call site, input facts, model, and prompt version. `from_seed()` replays the ledger instead of re-prompting, so regeneration is offline and byte-identical. → [generation-model.md](generation-model.md#2-every-generative-call-is-recorded-so-worlds-replay)

**One coherent episode before any subsystem.** The first executable is `worldloom demo retail-close`, producing a bounded corpus whose truth, lineage, evaluations, and cross-format projections can be falsified. → [build-order.md](build-order.md)

**One resolved structure, many native artifacts.** PPTX, DOCX, XLSX, and PDF are compiled from the same `ArtifactIR`. Atomic components, format grammars, layout constraints, and diversity search may change presentation; they may never change facts, tables, formulas, or provenance. → [artifact-compiler.md](artifact-compiler.md)

**Actors change the world only through tools.** LLM employees receive role-scoped observations and may propose typed actions. Policy, permissions, preconditions, and deterministic execution decide whether an action commits an event, fact, task, or artifact intent. Prose alone never mutates state. → [actor-simulation.md](actor-simulation.md)
