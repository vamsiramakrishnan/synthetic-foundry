---
title: Working on the harness
description: Change the harness safely — where things are, the docs gate, the determinism sweep, hardness readings.
read-when: Changing harness code, adding a subsystem, or asked whether the corpus is genuinely hard.
tags: [contributing, docs-gate, determinism-sweep, retrievers, layout]
---

# Where things are

| Path | What |
| --- | --- |
| `src/worldloom/models.py` | The thin waist. Every subsystem speaks these types |
| `src/worldloom/generators/` | Deterministic generation. No model, no clock |
| `src/worldloom/narrative/` | The contract with you: requests, claims, ledger |
| `src/worldloom/actors/` | Employees, their observations, tools, and the execution ledger |
| `src/worldloom/recipe.py` | How a world was made, so a corpus can rebuild itself |
| `src/worldloom/render/` | Formats. Read the IR and nothing else |
| `src/worldloom/validate.py` | The guardrails. Start here to understand the rules |
| `examples/retail-close/` | The hand-authored reference corpus. Frozen |
| `examples/grocery-close/` | Real agent-written prose, accepted whole. Replayed by CI |
| `.claude/skills/worldloom/` | The procedure, progressively disclosed by stage |
| `docs/build-order.md` | What gets built next, and the gate it must pass |
| `docs/generation-model.md` | Which engine owns what, and why |
| `docs/lore.md` | Lore as a constraint graph |
| `docs/actor-simulation.md` | LLMs as bounded employees, and the gates for it |

# Working on the harness itself

```bash
pytest -q
worldloom validate retail-close             # the reference corpus must stay coherent
worldloom docs --check                      # the docs still describe the CLI
```

`worldloom docs --check` is not a formality. `AGENTS.md` and the skill under
`.claude/` are what an agent reads *before* it knows anything, so a stale flag
there does not produce an error it can reason about — it produces a thinner
corpus and no sign that anything was missed. `tests/test_harness_docs.py` parses
every command in every agent-facing document and requires it to exist, and
requires every command to be documented somewhere.

`worldloom seams` lists the library seams a harness composes against —
`connectors`, `evals`, `pipeline` — with the canonical import for each;
`--json` emits the full contract. Import through those names rather than the
modules behind them: the seam is what stays put when a subsystem is
reorganised, and it is what the SDK, the CLI, and the skills all share.

Read `docs/build-order.md` before adding a subsystem. It sequences the work and
states an exit gate for each step, and the ordering is deliberate — several steps
exist specifically to stop a later one from being built on guesses.

## Enterprise connector evaluation harness

Use the enterprise harness when the deliverable is a grounded multi-connector
query corpus rather than Worldloom's native retrieval benchmark:

```bash
worldloom enterprise-evals space
worldloom enterprise-evals plan dist/world queries.jsonl --profile examples/enterprise-evals/omnichannel-retailer.json --exhaustive --limit 2000
worldloom enterprise-evals build dist/world dist/enterprise-evals --profile examples/enterprise-evals/omnichannel-retailer.json --exhaustive --limit 2000 --render-limit 30
worldloom enterprise-evals validate dist/enterprise-evals
worldloom enterprise-evals simulate dist/enterprise-evals --limit 500
worldloom enterprise-evals score query.json trace.json
```

Industry workflows belong in a `ScenarioProfile` as `additional_workflows` and
`additional_processes`; do not add industry names to the query planner. Use
covering mode to prove t-way coverage and bounded exhaustive mode to stream a
large, balanced corpus. Both routes must remain deterministic.

## Checking determinism somewhere other than seed 8128

CI proves byte-identity on four builds at one seed, on every push. That is one
point of a ten-dimensional configuration space, sampled repeatedly — and this
repository owns the algorithm for not doing that. `tools/sweep.py` points it at
our own QA: it enumerates engine × archetype × facets × locale × estate ×
trading year × periods × messiness × master-data *from the registries*, covers
the space with `dispersion.halton`, takes the furthest apart with
`dispersion.farthest_first`, and builds each one twice.

```bash
python3 tools/sweep.py --describe                    # the axes, building nothing
python3 tools/sweep.py -n 12                         # twice per config, in separate processes
python3 tools/sweep.py -n 12 --mode resident         # twice per config, in ONE interpreter
python3 tools/sweep.py -n 12 --mode archive          # working tree vs `git archive HEAD`
python3 tools/sweep.py --seed 8128 -n 12 --only <id> # replay one row exactly
```

`process` and `resident` answer different questions and neither subsumes the
other, so the nightly job runs `--mode process,resident`. Two fresh processes
share nothing but the seed, which is what catches a build depending on an
environment variable, a locale, or a hash seed. They cannot catch *leakage*
between builds — both start pristine, so a first build that poisons a
module-level registry has nothing to poison. Only a second build in the same
interpreter can see that, which is `resident`. (This file claimed the opposite
until review of PR #8 pointed out the hole; the fix is pinned by injecting a
module-level counter into `Rng.__init__` and watching `process` report
identical while `resident` reports the first differing line.)

`--mode archive` is the local gate — in a clean CI checkout the working tree
*is* `HEAD`. `.github/workflows/determinism-sweep.yml` runs nightly on a
rotating seed, so the corners covered move over time instead of being the same
eight forever. Every run prints its seed and each selected configuration, so
any failure replays exactly.

It is a tool, not library code: nothing under `src/` imports it and it adds no
dependency.

## Whether the corpus is hard, or only hard for keyword matching

Every difficulty number this project published before now came from BM25 and
TF-IDF — two ranking families and **one idea**, that relevance is word overlap.
A family they both fail is either structurally hard or merely a *lexical* trap
that any deployed retrieval stack walks past, and nothing here could tell those
apart.

```bash
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
python3 tools/measure_retrievers.py ./corpus              # every pin, one table
python3 tools/measure_retrievers.py ./mosaic --mosaic     # or a whole mosaic
```

Both print a second reading beside the agreement table: per family, **genuinely
hard** (lexical and semantic both fail), **lexical trap** (semantic solves it —
so it was never difficulty, and a corpus card counting it is overstating
itself), **semantic blind spot**, or **solved by everything**.

The retriever is an optional extra (`pip install "worldloom[embeddings]"`) and
absent-friendly: without it the dense column is skipped with a message and the
lexical readings still print. Its vectors are pinned to a model *revision* and
cached to a sidecar as quantised integers, so the measurement replays
bit-identically on a machine with no model at all — the generation ledger's
argument, applied to a retriever. `src/worldloom/evaluate/embedding.py` makes
that case in full, and
`.claude/skills/worldloom/references/evaluating.md` has the reading.
