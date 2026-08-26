# AlphaEvolve optimization charter

## Outcome order

AlphaEvolve may improve Worldloom only in this order:

1. every generated world remains coherent and factually grounded;
2. the recipe and generation ledger still replay deterministically;
3. the fleet remains qualified for its declared purpose;
4. the policy improves an independently measured, bounded decision seam;
5. only then may it reduce builds, repetitions, runtime, or other cost.

A cheaper corpus that loses facts, questions, replay, or admission is not an
improvement. A corpus that merely performs worse against Worldloom's bundled
BM25 baseline is not an improvement either: that crosses the Goodhart boundary
drawn in `worldloom.outcomes`.

## Role in the product

AlphaEvolve is a policy-search and counterexample tool, not an autonomous
source-code author:

1. the existing production policy is frozen as the control;
2. one pure decision function is searched against a frozen evaluator;
3. generated programs run in a restricted, timeout-bounded process;
4. holdout and adversarial cases are not included in managed search;
5. a maintainer translates a winning rule into ordinary source and tests;
6. Worldloom's full validation, replay, determinism, and docs gates decide
   whether that reviewed translation survives.

Generated code never edits `src/worldloom`. Coherence validation, recipe
replay, fleet fitness, and fact/generation ledgers are registered as protected
oracles in `evals/alphaevolve/registry.py`.

## First integration: balanced child variation

`worldloom evolve` varies one axis of a fleet champion for each child. Its
original ranking minimized the number of times the target value had appeared,
then used a content-addressed tie key. That spreads values, but a wide axis has
more unseen values and can consume several child slots before a narrow axis is
varied once.

The `variation-policy` experiment exposes only:

- whether a candidate child is admissible;
- how often its axis has been varied;
- how often its target value has appeared;
- the existing deterministic tie key.

The completion gate rejects missing, unknown, refused, and already-proposed
choices. The quality oracle ranks axis count, then value count, then tie key.
The current value-only policy remains the managed seed. The reviewed local
integration adds axis count as the first production rank term and leaves
buildability, single-axis mutation, parent selection, corpus measurement, and
fleet fitness unchanged.

The frozen evaluator contains 64 search cases, 37 separately salted holdouts,
and four adversarial cases covering an inadmissible cheap child, axis/value
conflict, within-axis value selection, and deterministic final ties. The dated
receipt in `evals/alphaevolve/2026-08-19-variation-policy.md` records the exact
result and its limitations.

## Promotion contract

A managed winner is only a hypothesis. Production integration requires:

1. every search completion gate passes;
2. exact policy agreement on the independently generated holdout matrix;
3. every adversarial case passes;
4. deterministic behavior across repeated evaluation;
5. a reviewed source translation rather than copied generated code;
6. focused policy tests and the complete repository gates;
7. a receipt that records plateaus and reversals as well as gains.

Managed execution may incur cost and therefore requires `--confirm-spend`.
Local scoring is offline and model-free. Neither path is allowed to claim that
the resulting corpus is more realistic without an external reference
population, or more useful without an independent downstream evaluation.
