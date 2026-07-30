# Worldloom design documents

Worldloom is in design. These documents are the specification being built toward; nothing is implemented yet.

| Document | Answers |
| --- | --- |
| [build-order.md](build-order.md) | What gets built, in what order, and what gate each step must pass |
| [generation-model.md](generation-model.md) | Which engine owns what, across all twenty generation areas |
| [lore.md](lore.md) | What lore is as a data structure, and how lore generators are authored |

Read them in that order. The build order is the plan; the generation model is the contract every step must honour; lore is the layer everything else is derived from.

## The three load-bearing decisions

**The generation boundary.** The deterministic engine owns everything that must be *correct* — arithmetic, identity, referential integrity, the graph, the timeline, permissions. The generative engine owns everything that must be *plausible*. Nothing is owned by both. → [generation-model.md](generation-model.md)

**Determinism survives the LLM.** Every generative call is content-addressed into a generation ledger keyed by seed, call site, input facts, model, and prompt version. `from_seed()` replays the ledger instead of re-prompting, so regeneration is offline and byte-identical. → [generation-model.md](generation-model.md#2-every-generative-call-is-recorded-so-worlds-replay)

**One coherent episode before any subsystem.** The first executable is `worldloom demo retail-close`, producing a hand-authored corpus with no LLM involved, so the product contract is fixed before prompt behaviour can shape the architecture. → [build-order.md](build-order.md)
