# Repository Guidelines

Working guide for AI assistants in this repository (Worldloom, published from
`synthetic-foundry`). Read before editing anything.

## Project Overview

Python library + CLI (`worldloom`, entry point `src/worldloom/cli.py:app`) that
deterministically generates coherent synthetic enterprise corpora — facts,
timelines, org graphs, business processes — and materialises them as realistic
documents (xlsx/docx/pdf/pptx/markdown/html), evaluation sets, and permissioned
drive layouts.

The harness never calls a language model; **the agent is the writer**. The loop:

1. `worldloom narrate requests ./corpus -o requests.json` hands you bounded prose
   requests (allowed facts, temporal cutoff).
2. You write `responses.json` — every figure referenced as `{{fact:ID}}`, never
   typed out (the most common rejection is `bare_number`; percentages and dates
   count as figures). Contract details: `docs/agents/writing-responses.md`.
3. `worldloom narrate accept ./corpus --from responses.json --model-id <model>`
   checks every claim against the corpus and commits or rejects with the violated
   rule.

Rejection is normal — read the violation, fix that specific thing, resubmit.
Never make a validator pass by editing a fixture, relaxing a check, or working
around a refusal. Deep material is routed one-topic-per-file in `docs/agents/`
(16 files, each says when to read it); the index is `docs/README.md`.

Everything replays byte-for-byte from `seed + recipe + generation ledger`; CI
rebuilds corpora and byte-compares them on every push.

## Architecture & Data Flow

Layered pipeline around an immutable `World` (frozen dataclass,
`src/worldloom/world.py`) — the single entry point for load/build/validate.
No layer re-decides a fact an earlier layer owns. The thin waist is
`src/worldloom/models.py`: every subsystem speaks only in frozen pydantic models
(`ConfigDict(frozen=True, extra="forbid")`, `StrEnum` vocabularies); nothing
format- or provider-aware crosses it.

1. `generators/` (~34 modules, uniform `generate(rng, minter, *, …)` shape) mint
   entities/facts/events from `recipe.py` scenario steps, drawing from
   `rng.derive("<stable-name>")` streams and `ids.Minter` sequential ids.
2. `documents.py` compiles `ArtifactIntent` → `ArtifactIR` (structure and
   tables, no prose); `compiler/` (plan/components/grammar) is the deterministic
   artifact compiler where a model may only choose a content-addressed *plan*.
3. `narrative/` — `requests.py` (contract) → `prompts.py` (versioned registry) →
   providers → `claims.py` validation → `compiler.py` (ledger, retries, the only
   ThreadPoolExecutor; all ids minted single-threaded *before* threads spin up).
4. `render/` turns IR → bytes; `workspace.py` exports the corpus as a
   permissioned shared-drive tree.
5. `validate.py` is the coherence gate (referential, graph, financial, temporal,
   lore, actors); `evaluate/` scores retrieval hardness (BM25/TF-IDF/embedding
   floors, pinned and cached).

Determinism spine:

- **Generation ledger** (`generation-ledger.jsonl`): key = `(seed, call_site,
  ordinal, fact_digest, model_id, prompt_version)` → SHA-256 `ids.content_key`.
  A corpus carrying a ledger rebuilds with zero provider calls, offline.
- **Recipe** (`recipe.py`) records every build-affecting input (archetype,
  `register_step` steps, locale, presentation) so `build --replay` is
  byte-identical; `corpus.tree_divergence` is the arbiter of "identical".
- `cli.py` (~310KB, 30+ commands, 10 sub-apps) is a thin wrapper: lazy imports
  inside command bodies, and `@app.callback()` runs `worldloom._install()`
  before every command so domain registration is all-or-nothing.

## Key Directories

| Path | Purpose |
|---|---|
| `src/worldloom/` | The package; `cli.py`, `world.py`, `models.py`, `validate.py`, `documents.py`, `episodes.py` are load-bearing |
| `src/worldloom/generators/` | Vertical generators (retail, banking, insurance, procurement, org, estate, …) |
| `src/worldloom/{narrative,render,evaluate,compiler,actors}/` | Pipeline stages above |
| `src/worldloom/{connectors,evals,pipeline}/` | The three library seams `worldloom seams` names: product-shaped connector emulation and trace grading; eval-first design → demands → candidates → proof; typed orchestration shared by SDK, CLI and skills |
| `src/worldloom/{synthesis,process_bindings,process_planning}/` | Operational relational synthesis (causal microdata, paired interventions); the supplied 12-industry process catalogue compiled into company bindings and process plans |
| `tests/` | ~225 pytest files; scripted agent stand-ins (`scripted_composer.py`, `scripted_actor.py`, `scripted_agent.py`) |
| `tools/` | Dev-only scripts (`sweep.py` determinism sweep, `measure_retrievers.py`, `outcome_selection.py`); stdlib-only, never imported from `src/` |
| `docs/`, `docs/agents/` | Operator guides; 16 agent topic files |
| `examples/` | `retail-close/` golden corpus (CI-validated, hand-authored — never regenerate or "fix" it), `grocery-close/` reference narration, `packs/`, `episodes/`, `artifact-types/` |
| `evals/` | Checkout-only eval harnesses (enterprise_minimum, executive_narration, alphaevolve) |
| `.claude/skills/`, `.claude/commands/` | 16 skills + 6 slash commands driving the loop; every skill is indexed in `docs/skills.md` |
| `site/` | Astro/Starlight docs site (npm, GitHub Pages) |
| `.github/` | CI workflows; `scripts/dispersed_replay.py` is the byte-identity gate |

## Development Commands

```bash
pip install -e ".[dev]"            # add renderers as needed: ,xlsx,docx,pdf,pptx,polars
pre-commit install                 # ruff-check + worldloom docs --check
worldloom doctor                   # verifies the install; names exact fixes; --json for data

pytest -q                          # house gate (slow tests deselected via addopts)
pytest tests/test_render.py -q     # one file; -k "name" for one test
pytest -m slow -q                  # opt in to heavy builds (weekly in CI)
ruff check .                       # lint gate (CI-blocking)
mypy                               # type gate (CI-blocking; new modules checked by default)

worldloom validate retail-close    # golden corpus must stay coherent (CI gate)
worldloom docs --check             # generated CLI reference must be current
```

Corpus loop:

```bash
worldloom build --seed 8128 --incident --out ./corpus
worldloom narrate requests ./corpus -o requests.json
worldloom narrate accept ./corpus --from responses.json --model-id <your-model>
worldloom render ./corpus -f xlsx -f docx -f markdown
worldloom validate ./corpus
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
worldloom workspace ./corpus -o ./drive
worldloom status ./corpus --json   # names the stage and the exact next command
```

Docs site: `cd site && npm ci && npm run build` (deployed by
`.github/workflows/docs.yml`).

## Code Conventions & Common Patterns

**Determinism** (umbrella rule; `tests/test_determinism_hygiene.py` AST-enforces
it over `src/`):

- No `random`, `uuid`, wall clock (`datetime.now()` and friends), or builtin
  `hash()` for identity. Draws via `rng.derive("<stable-name>")`; ids via
  `ids.Minter`/`format_id`; content addresses via `ids.content_key` (SHA-256).
- No dict/set iteration order reaching output — sort before emitting; JSON/JSONL
  writes go through `corpus.write_jsonl`/`write_json` (sort_keys, pinned
  newlines).
- Prompts are versioned data (`narrative/prompts.py`, key `name@version`):
  never edit a template in place — bump the version; it is a ledger-key
  component.
- Anything that changes what a seed generates is a **Generation** change:
  CHANGELOG entry under its own heading, treated as breaking for
  reproducibility.

**Registration seams** (idempotent, refuse conflicting duplicates):
`register_domain` (`domains.py`), `register_step` (`recipe.py`),
`register_domain_checks` (`validate.py`), `register_artifact_types`
(`documents.py`), `registries.declare` (per-corpus tables beside the code that
writes them), `narrative/prompts.register`. A new vertical registers from its
own module AND must be imported unconditionally from `__init__._install()` —
lazy registration makes coherence depend on import order.

**Error handling**: named exceptions (`CorpusError`, `CoherenceError`,
`RecipeError`, `NarrationError`, `RenderError`) plus the `ValidationReport`
envelope (`raise_if_failed()`; violations vs advisories). CLI refusals go
through the `_REFUSALS` code registry in `cli.py` — codes are a stable wire
format.

**Style**:

- Comments argue *why*, not *what* — including the defect that motivated a
  check. Match that; don't strip it when editing.
- No formatter by design. E501 is ignored (prose comments run long); E402 is
  ignored (late imports are the registration seam, not accidents); `zip()`
  without `strict=` is a ratchet — new code should say `strict=`.
- `from __future__ import annotations` everywhere; frozen dataclasses for value
  objects, pydantic `Model` for serialized entities; `__all__` grouped
  semantically; `TYPE_CHECKING` blocks for import-only types.
- No async anywhere in `src/`; the only concurrency is `narrative/compiler.py`'s
  thread pool.

## Important Files

| File | Role |
|---|---|
| `pyproject.toml` | All gates: extras, ruff, mypy (incl. the `ignore_errors` debt ledger — fix a module, delete its line; never add one), pytest config |
| `src/worldloom/__init__.py` | Version (hatch reads it — bump here only) + `_install()` registration |
| `src/worldloom/ids.py`, `rng.py`, `corpus.py` | Deterministic ids, RNG streams, byte-identical IO |
| `src/worldloom/validate.py` | Coherence gate; `register_domain_checks` |
| `src/worldloom/narrative/prompts.py` | Versioned prompt registry |
| `.claude/skills/worldloom/references/commands.md` | GENERATED CLI reference — regenerate with `worldloom docs`, never hand-edit |
| `examples/retail-close/` | Golden corpus; its empty generation ledger is asserted by a test |
| `tests/test_determinism_hygiene.py`, `tests/test_properties.py` | Determinism AST gate; hypothesis properties |
| `CONTRIBUTING.md`, `RELEASING.md`, `CHANGELOG.md` | PR gates; tag-driven release steps; changelog format |

## Runtime/Tooling Preferences

- Python ≥ 3.11 (floor); CI matrix 3.11/3.12/3.13. `uv run <cmd>` works for
  one-off commands in a checkout.
- pip + hatchling; version single-sourced from `src/worldloom/__init__.py`.
- Optional extras unlock features, and `worldloom doctor` names the missing pip
  extra per format: `xlsx`, `docx`, `pdf`, `pptx`, `polars`, `mcp`,
  `embeddings` (downloads weights — deliberately never core), `all`, `dev`.
- `tools/` scripts run as `python3 tools/<name>.py` (they sys.path-insert
  `src/`); stdlib-only, dev-only.
- Site tooling is npm/Node (Astro 5 + Starlight), isolated to `site/`.
- `.gitattributes` pins LF everywhere — byte-identity fixtures depend on it.

## Testing & QA

- pytest only (no xdist). `pytest -q` is the house gate; `addopts` deselects
  `@pytest.mark.slow` (three heavy density builds) so the default run stays
  fast.
- Hypothesis properties in `tests/test_properties.py`: derandomized, deadline
  on, database disabled. Never weaken a property to pass it; nothing under
  `src/` may gain randomness.
- Determinism is enforced in layers: `tests/test_determinism_hygiene.py` (AST
  scan of `src/`), `tests/test_verify_cli.py` (byte-tamper detection),
  `tests/test_dispersed_replay.py` (guards the CI gate script), nightly
  `tools/sweep.py` across Linux/macOS configs.
- Fixtures: `tests/conftest.py` session fixtures only for genuinely repeated
  identical builds (lazy, no FS mutation). Agent handshakes are tested with the
  scripted stand-ins, which read only the request document, never the corpus.
- CLI test style: module-level `runner = CliRunner()`, assert
  `result.exit_code` with `result.output` in the assert message; negative
  validator tests corrupt one fact and expect the named violation.
- Before committing: `pytest -q`, `ruff check .`, `mypy`,
  `worldloom validate retail-close`, `worldloom docs --check`. CI additionally
  byte-replays corpora — anything nondeterministic fails there even when local
  tests pass.
- Changed the CLI surface (command or flag)? Run `worldloom docs` from the root
  and commit the regenerated reference. `tests/test_harness_docs.py` requires
  every real command to be mentioned in an agent-facing document and rejects
  fenced examples naming commands or flags that don't exist — **this file is on
  that checked list.**
