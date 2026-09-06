# Balance Worldloom evolution across build axes

Evolve `choose_variation(state, options) -> option_id`. Every option is one
single-axis child of a fleet champion. Refused and already-proposed children
are marked inadmissible and must never be selected.

Among admissible children, prefer the axis varied least often, then the value
seen least often, then the supplied deterministic tie key. This prevents a
wide axis from consuming the build budget while narrower axes remain
untouched. Change only the single `EVOLVE-BLOCK`.

The evaluator owns search cases outside this prompt. Coherence, replay,
fitness, ledger truth, and buildability are protected oracles and are not
candidate inputs.
