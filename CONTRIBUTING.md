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
pytest -q -n auto                 # the full fast suite, one worker per core
worldloom validate retail-close   # the reference corpus must stay coherent
worldloom docs --check            # the docs still describe the CLI that exists
```

`-n auto` is pytest-xdist (in the `dev` extra), and it is how CI runs the
suite: serially it took the better part of an hour per leg. Plain `pytest -q`
runs the same tests in one process and must pass too, so a test may not lean
on another test's side effects, write to a fixed, cwd-relative or home path,
or set an environment variable without `monkeypatch`.

### The test build cache

A few fixtures build something expensive and deterministic (an interviewed
company realised and rendered, a compiled Studio workspace, a company
dataset, a catalogue projection). `tests/build_cache.py` builds each once per
*source tree* and hands every later caller a copy: across xdist workers in one
run, and across runs. The key is a digest of every file under
`src/worldloom`, the interpreter and every installed distribution's version,
the `WORLDLOOM_*` environment and user pack roots, the source of the test
module defining the builder, and the build's recipe, so any change to the
package is a fresh build; a stale artifact can never stand in for code that no
longer exists. Entries are written to a temporary directory and published
with one atomic rename, under a per-entry file lock.

- Location: `.pytest_cache/worldloom-builds/` in the checkout, or
  `$WORLDLOOM_TEST_CACHE`. Entries from other source trees are pruned at the
  start of each session. Deleting the directory is always safe.
- Opt out: `pytest --no-build-cache` or `WORLDLOOM_NO_BUILD_CACHE=1` runs
  every builder directly, exactly as before the cache existed. Run that way
  when measuring coverage of the builders themselves.
- Writing a test: reuse a build only where it is an *input* to what the test
  checks, via `build_cache.cached_tree` (a directory, copied to your path) or
  `build_cache.cached_value` (a pickled object, new on every call); builders
  shared between modules live in `tests/shared_builds.py`. A test whose claim
  is that building is deterministic (the same seed twice, replay, verify,
  resume) must keep building fresh, and a build made under `packkit.use` is
  never cached.

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

## Documentation changes

Write for the reader's next task. A tutorial names prerequisites, runnable
commands, expected output, and the next useful check. A reference defines
inputs, outputs, failure behavior, and version or feature boundaries.

Keep supported behavior separate from proposals and dated measurements.
Performance claims need a workload, revision, method, and result. Test counts,
shared schemas, and successful compilation do not establish deployment quality.
Use plain descriptions of the mechanism instead of claims such as seamless,
production-ready, zero overhead, or guaranteed unless the scope is explicit
and supported by a check.

Shared workflows must work from a terminal-capable coding agent. Put host
installation and permission differences in the host-specific guide. Preserve
real adapter names and historical evidence; do not rename a protocol field or
pretend an integration exists to make the prose vendor-neutral.

Edit canonical sources. Regenerate site or command-reference projections through
the repository's existing build. Check links and examples against the current
checkout. Report local, simulated, and live-provider verification separately.
