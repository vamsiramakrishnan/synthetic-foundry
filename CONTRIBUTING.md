# Contributing to Worldloom

The deep material lives in [AGENTS.md](AGENTS.md): what this tool is, how the
build/narrate/render/validate loop works, and why the harness refuses things.
Read it first; this file is only the mechanics of getting a change merged.

## Setup

```bash
pip install -e ".[dev]"
worldloom --help
```

## The gates a PR must pass

CI runs all of these blocking. Run them locally before pushing:

```bash
ruff check                        # lint; config and rationale in pyproject.toml
mypy                              # types; honest scope declared in pyproject.toml
pytest -q                         # the full fast suite
worldloom validate retail-close   # the reference corpus must stay coherent
worldloom docs --check            # the docs still describe the CLI that exists
```

Byte-identity is the gate behind the gates: CI regenerates corpora from their
ledgers and diffs them byte-for-byte, and the nightly sweep does the same
across the configuration space. A change that moves the bytes of an existing
default build is either deliberate (say so, with the reason) or a bug.

## The determinism rules

- No `random` (use `worldloom.rng.Rng`, derived by *name*), no clock, no UUID,
  no `hash()` as an identifier (use `worldloom.ids.content_key`), no `set`
  iteration order reaching output.
- Prompt text is versioned data. Editing a prompt in place changes what a
  seed means, so bump the version in `src/worldloom/narrative/prompts.py`.
- Eigendecompositions and anything BLAS-shaped are *readings*, never inputs to
  a build decision: they differ in the last bits across machines.

## House style

Comments explain *why*, not what, especially where a simpler-looking
alternative is wrong. When a check catches something during your work, say in
the comment what it caught. If you are tempted to make a validator pass by
editing the fixture or relaxing the check: don't. Fix the thing it caught.

## Reporting problems

A reproducible report names a **seed, a recipe, and a version**. That is the
premise of the tool, and the issue templates ask for those three things.
