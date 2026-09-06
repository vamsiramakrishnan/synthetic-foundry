# The builder revamp: an execution plan

Eight work items that close the gap between "excellent engine" and "product
that installs in ten seconds and measures its own users." Written to be
executed by a model session (Sonnet or Haiku) one item per session, one item
per pull request. Read this whole file before starting any item, then read
[AGENTS.md](../../AGENTS.md): it is the harness contract and nothing here
overrides it.

Two further items are **operator actions** for a human and are listed at the
end. Do not attempt them.

---

## How to work

- **One item, one PR.** Start each item from fresh `origin/main`
  (`git fetch origin main && git checkout -B <branch> origin/main`). Open the
  PR as a draft. Do not combine items.
- **Sizing.** Each item is one focused session. If an item is not converging
  inside one session, stop, commit what passes gates, and record what remains
  in the PR body: do not thrash.
- **The gates run before every commit**, not once at the end:

  ```bash
  pytest -q                        # all of it; no test may be skipped to pass
  worldloom validate retail-close  # pinned: 1,283 checks
  worldloom docs --check           # regenerate with `worldloom docs` if stale
  ruff check src/ tests/
  python -m mypy src/worldloom/<files you touched>
  ```

- **Byte-identity gate** for any item touching the build path (W1, W4, W5,
  W6): build `worldloom build --seed 8128 --out A` from your tree and from a
  pristine `git archive HEAD` tree, `diff -r` them. New capabilities must be
  opt-in; the default build's bytes never move.
- **New CLI commands** must be mentioned in AGENTS.md (one honest paragraph,
  in its voice) or `tests/test_harness_docs.py::test_every_command_is_documented`
  fails, and `worldloom docs` must be re-run to refresh the generated
  reference.
- **The lint CI job runs on Python 3.11** (the package floor) so failures
  reproduce locally. If mypy passes for you but fails in CI, check your
  Python version first.

## What is never acceptable

These are the standing repo rules; every one of them exists because a test or
CI caught the violation once:

1. Never respond to a validator rejection by editing the corpus, relaxing a
   check, or dropping the offending fact. The violation is correct.
2. Never introduce a clock, `random`, a UUID, or `hash()` into any path that
   feeds corpus bytes. Ledger keys are content addresses
   (`worldloom.ids.content_key`).
3. Never let a flag be silently ignored. A flag either acts or refuses with
   the reason (`tests/test_flag_reach.py` is the pattern to copy).
4. Never assert on Rich console output with raw substring matches: Rich
   wraps lines. Collapse whitespace first (see `_flat()` in
   `tests/test_flag_reach.py`).
5. Never mark an item done with a test skipped, a check loosened, or a
   number in a doc you did not reproduce.
6. Comments explain *why* a rule exists, especially where a simpler
   alternative is wrong. When a validator or gate catches your defect, say in
   the comment what it caught.

---

## W1: Refusals as data

**Goal.** Every CLI refusal can be consumed as one-line JSON instead of
prose, behind an opt-in that leaves default output byte-identical.

**Why it compounds.** `src/worldloom/cli.py` has ~148 `err.print` sites; the
narration handshake already returns violations as data, but a harness hitting
a plan-time refusal today regexes stderr. The refusal taxonomy is this repo's
best feature and has no wire format.

**Design.**

- A helper in `cli.py` beside `err`:

  ```python
  def _refuse(code: str, message: str, *, fix: str | None = None,
              exit_code: int = 2, **data: Any) -> NoReturn
  ```

  Default mode: print the *exact existing* rich message to stderr (pass the
  current string through unchanged, since many tests assert on these strings).
  When `WORLDLOOM_OUTPUT=json` is set in the environment: print one line of
  JSON to stderr instead: `{"refusal": code, "message": ..., "fix": ...,
  "data": {...}}`, same exit code. An env var, not a global flag, because
  per-command `--json` flags already exist with a different meaning (success
  payloads) and must not be disturbed.
- Codes are snake_case, stable, and registered in one module-level dict
  (`_REFUSALS: dict[str, str]` mapping code → one-line meaning) so they are
  enumerable and a typo is caught by the registry lookup. Reuse names the
  taxonomy already has (`implausible_productivity`, `unknown_facet`,
  `no_overlap`…) where the refusal is the same one.
- **Migrate incrementally.** Convert the *refusal* sites (those that raise
  `typer.Exit(code=2)` or `code=3`), not every `err.print`. Convert in
  batches of ~20, running the full suite between batches. Informational
  stderr stays as-is.

**Tests** (`tests/test_refusal_envelope.py`): pick five representative
refusals (unknown `--access` level, `--periods` over a declared cap, `twin`
unrecorded path exit 2, `mutate` existence path exit 3, `--spec` with an
unknown facet). For each: under `WORLDLOOM_OUTPUT=json` assert stderr parses
as JSON with the expected `refusal` code and the same exit code; without the
env var assert the previous message text still appears (whitespace-collapsed)
and byte-for-byte where a test already pinned it.

**Done when** all five tests pass, the full suite is green untouched, and
AGENTS.md has one short paragraph documenting `WORLDLOOM_OUTPUT=json`.

**Refuse and ask if** you find a refusal whose message is built from a Rich
table (not a string): do not flatten it lossily; leave it unconverted and
list it in the PR body.

---

## W2: `worldloom verify`, the trust demo as one verb

**Goal.** `worldloom verify ./corpus` = rebuild from the corpus's own recipe
and ledger, byte-compare every file, then validate: one command, exit 0.

**Design.**

- New command beside `validate` in `cli.py`. Load the corpus (`_load`);
  refuse (`no_recipe`) when `world.recipe` is empty. Rebuild into a temp
  directory through the same path `build --replay` uses (read that
  implementation first; do not invent a second replay). Byte-compare with the
  file-set-then-bytes logic of
  `.github/scripts/dispersed_replay.py::_assert_byte_identical`; factor that
  helper into `src/worldloom/corpus.py` (or reuse if an equivalent exists)
  rather than copying it a third time; update the script to import it.
- Output: `✓ verified: N files byte-identical, M checks passed`, or exit 1
  naming the first diverging path and whether it is missing, extra, or
  different. Support `--json`.
- Note in the command's docstring: rendered artifact files are compared only
  if present in the corpus: verify never renders.

**Tests** (`tests/test_verify_cli.py`): green path on a fresh
`--seed`-built-and-narrated corpus; red path: copy the corpus, flip one byte
in `facts.jsonl`, assert exit 1 and the filename in stderr; a plan-only
corpus with no recipe refuses with `no_recipe`.

**Done when** tests pass, README's "Determinism and replay" section shows the
one-liner (keep the existing three-command block too; it explains the
mechanism), AGENTS.md mentions the command, docs regenerated.

---

## W3: `worldloom doctor`, install-level health

**Goal.** One command that says whether this installation can do what the
docs promise, and names the exact fix for everything it cannot.

**Design.**

- Checks, each reported as ✓/✗ with a fix string:
  1. Python version ≥ the package floor (read it from package metadata, do
     not hardcode).
  2. Each render format → its importable dependency. **Read the renderer
     registry in `src/worldloom/render/` to enumerate formats and their
     imports**: do not hardcode a table that drifts. The fix string names
     the pip extra (`pip install -e ".[render]"` or whichever extra
     `pyproject.toml` declares for that import).
  3. The pinned example corpus validates (`retail-close`, 1,283 checks).
  4. The generated command reference is current (same check `docs --check`
     runs; import and call it, don't shell out).
- Exit 0 all-green, exit 1 otherwise. `--json` emits the check list. No
  network access, ever.

**Tests** (`tests/test_doctor_cli.py`): green in the dev environment; a
missing renderer dep simulated by monkeypatching the import to raise
`ImportError` → ✗ with the extra named; exit codes both ways.

**Done when** tests pass, README's Quickstart gains one line
(`worldloom doctor` after install), AGENTS.md mentions it, docs regenerated.

---

## W4: Narration verdicts, persist, then read

**Goal.** `worldloom narrate stats` answers "what is model X's first-pass
acceptance rate and what does it fail on" from recorded verdicts.

**The trap this design exists to avoid** (read carefully): CI regenerates a
corpus from its own ledger and byte-diffs the whole directory. Rejected
submissions are not in the generation ledger, so a verdicts file *inside* the
corpus can never be reproduced by replay and would fail byte-identity.
Therefore verdicts live **outside the corpus**, opt-in.

**Design.**

- `narrate accept` gains `--verdicts PATH` (default: off, nothing written).
  When set, append one JSON line per submitted section per attempt:
  `{"model_id": ..., "section": ..., "attempt": N, "accepted": bool,
  "violations": ["bare_number", ...], "response_key": content_key(text)}`.
  No timestamps: the attempt ordinal is the order. Find the accept
  implementation in `src/worldloom/narrative/handshake.py` (the
  `Verdict`/`Violation` models around line 140) and the CLI's accept command;
  write at the CLI layer, not inside the handshake, so the library stays
  pure.
- `worldloom narrate stats VERDICTS_FILE...` (accepts several files):
  first-pass acceptance rate, violations by rule (descending), both split by
  `model_id`, and the sections that took the most attempts. `--json`.

**Tests** (`tests/test_narrate_verdicts.py`): drive requests/accept with the
deterministic provider's responses plus one deliberately bad response (a
typed-out figure) submitted first: assert the verdicts file records the
rejection with `bare_number`-family violation and then the acceptance;
assert stats aggregates it correctly; assert **no** verdicts file appears
without the flag; assert a corpus built with the flag is byte-identical to
one built without it (the file is outside the corpus directory in the test).

**Done when** tests pass, byte-identity holds, AGENTS.md's narration section
gains a short paragraph, docs regenerated.

---

## W5: The `--exec` seam, `narrate loop` and `benchmark run`

**Goal.** Treat the model as an executable. One subprocess contract makes
"real prose in one command" and "score an actual agent against its own
benchmark" both real, without importing any SDK.

**Contract (both commands).** The child process receives one JSON document on
stdin and must emit one JSON document on stdout. Non-zero child exit, or
unparseable stdout → refusal that includes the last ~20 lines of the child's
stderr. `--timeout SECONDS` (default 600) kills and refuses. The command is
run without a shell (list argv via `shlex.split`); `--shell` opts into
`shell=True` for pipelines.

**`worldloom narrate loop CORPUS --exec CMD [--max-rounds 8] [--verdicts PATH]`**

- Round: generate requests for all unaccepted sections (the same document
  `narrate requests` writes; reuse that code path, do not re-derive);
  feed to CMD; parse the responses document (same schema `narrate accept
  --from` reads); run acceptance in-process; repeat with only the still-
  unaccepted sections. Stop when all accepted (exit 0, print rounds taken and
  totals) or max-rounds (exit 1, print every outstanding violation).
- Composes with W4's `--verdicts`.
- Document (in the command help) the adapter expectation with one concrete
  example: a shell script wrapping a coding harness's non-interactive CLI
  that reads stdin and prints the responses JSON. Do not special-case any
  vendor in code.

**`worldloom benchmark run CORPUS --exec CMD [-k 5] [--limit N]`**

- Per evaluation case: payload `{"question": ..., "passages": [top-k from
  the same BM25 index `worldloom search` uses, with passage_id and text]}`.
  The child returns `{"answer_passage_ids": [...], "abstain": bool}`.
- Scoring is **id-based only, never text similarity**: deterministic
  scoring is the house rule, and grading free text would smuggle a judge into
  a system whose whole point is mechanical ground truth. A case scores
  correct when the returned passages carry the expected fact IDs (reuse the
  coverage logic in `src/worldloom/evaluate/score.py`, read it first) and
  the abstention flag matches the case's expectation.
- Output: the same scorecard shape `evaluate` prints, labelled with the exec
  command, plus `--json`.

**Tests** (`tests/test_exec_seam.py`): the fake model is a tiny Python
script the test writes to tmp, deterministic, no network. For the loop: a
responder that answers correctly except one section where its first attempt
types a figure out and its second attempt cites it: assert two rounds, then
acceptance, and that the corpus validates. For benchmark: a responder that
returns the passage containing the expected fact for even-numbered cases and
abstains on the rest: assert the scorecard splits exactly as constructed.
Also: child that exits non-zero → refusal carrying its stderr; child that
prints garbage → refusal; timeout path with a sleeping child and
`--timeout 1`.

**Done when** tests pass, a narrated-by-loop corpus replays byte-for-byte
from its own ledger (accepted prose is ledgered; prove it in a test),
AGENTS.md documents both commands, docs regenerated.

**Refuse and ask if** you find yourself wanting to grade answer *text*: that
is a design boundary, not an implementation gap.

---

## W6: The startup budget

**Goal.** `worldloom --help` cold start drops from the measured 0.64–0.86s
to ≤0.25s, and CI holds the line thereafter.

**Do this item last** among W1–W5: it refactors imports across `cli.py` and
would make every other item's diff conflict.

**Design.**

- Measure first: `python -X importtime -c "import worldloom.cli" 2>&1 | sort
  -t'|' -k2 -rn | head -30`. Record the top offenders in the PR body.
- Defer heavy imports (the world/model stack, numpy-touching modules,
  renderers, evaluate) from module level into the command bodies that use
  them: the pattern most commands already follow; the offenders are the
  stragglers. Check `src/worldloom/__init__.py` for eager re-exports and make
  them lazy via module `__getattr__` (PEP 562) if they pull the heavy stack.
- Guard: `tests/test_startup_budget.py` spawns `python -c "import
  worldloom.cli"` three times and asserts the **minimum** wall time is under
  a ceiling generous enough for CI noise (0.5s): the test exists to catch
  eager-import regressions, not to benchmark. Comment that intent.

**Gates beyond the standard ones:** byte-identity (imports moving can change
nothing about bytes, prove it), and `python -m mypy src/worldloom/` clean:
lazy imports are where type checking usually breaks first.

**Done when** the measured min-of-3 for `worldloom --help` is ≤0.25s in your
environment, the budget test passes, and the PR body shows before/after
importtime tables.

---

## W7: A Windows CI leg

**Goal.** The test suite runs on `windows-latest`, and the bugs it finds are
fixed rather than skipped.

**Plan of attack (likely two PRs; that is fine).**

1. First PR: add a `windows-latest` job to `.github/workflows/ci.yml`
   (one Python version, 3.12), `continue-on-error: true`, so it inventories
   failures without blocking. Read the macOS leg in
   `determinism-sweep.yml` for the shape.
2. Second PR: fix what it found and flip `continue-on-error` off. Expect the
   failures to be: **newline discipline** (any JSONL/text write without
   `newline="\n"` produces CRLF on Windows and breaks byte-identity: grep
   `open(` and `write_text` in `src/worldloom/corpus.py` and everywhere
   corpus files are written; pin `newline="\n"` with a why-comment),
   hardcoded `/tmp` (must use `tempfile`), and path-separator assumptions in
   tests.

**Never** skip a test to make the leg green; a test that cannot pass on
Windows for a stated architectural reason gets a `skipif` with that reason
written out, and there should be almost none.

**Done when** the leg is green and required, and byte-identity is proven
cross-OS: a corpus built on the Windows runner diffs clean against one built
on Linux (add this as a CI artifact comparison step; the macOS sweep may
already have the pattern).

---

## W8: The migration guarantee

**Goal.** No published corpus is ever stranded by a schema bump.

**Design.**

- Find the schema version field (`world.json`, see `World.load` in
  `src/worldloom/world.py` and `src/worldloom/corpus.py`). Establish the
  policy as executable tests:
  1. A frozen fixture corpus at the **current** schema version lives in
     `tests/fixtures/` (small: plan-only retail, one period). A test loads
     it and validates. When a future PR bumps the schema, this test fails,
     which is the point: the bumping PR must then (a) move the old fixture
     to a versioned name, (b) freeze a new fixture, (c) extend `migrate`.
     Write that instruction into the test's docstring.
  2. `worldloom migrate CORPUS --out DIR`: today it verifies the version and
     copies (identity migration), refusing an unknown or future version with
     the versions named. Its structure (a chain of version→version steps)
     is the deliverable; the first real step arrives with the first bump.
- Note: `examples/retail-close` is current-version and CI-validated, but it
  is hand-authored and other tests depend on it: freeze a *separate*
  minimal fixture rather than repointing it.

**Tests**: fixture loads and validates; `migrate` on the fixture is
byte-identical identity; `migrate` on a doctored future version refuses
naming both versions.

**Done when** tests pass, AGENTS.md gains two sentences on the bump policy,
docs regenerated.

---

## Sequencing

```
W1 (refusal envelope)        : first, W2/W3/W5 want it
  ├─ W2 (verify)             : independent after W1, small
  ├─ W3 (doctor)             : independent after W1, small
  ├─ W4 (verdicts + stats)   : independent of W2/W3
  └─ W5 (exec seam)          : after W1; composes with W4's --verdicts
W6 (startup budget)          : LAST of the cli.py items (import refactor)
W7 (Windows leg)             : any time, independent
W8 (migration)               : any time, independent
```

Safe to run in parallel sessions: {W2, W3}, {W4}, {W7}, {W8}. Never run two
sessions that both edit `cli.py` at the same time.

---

## Operator actions (human only, do not attempt)

- **O1: Publish to PyPI.** Claim the `worldloom` name, wire the repo's
  trusted publishing (`.github/workflows/release.yml` is ready), push a
  `v0.1.0` tag. Afterward: a model session should update the README
  quickstart to `uvx worldloom` / `pip install worldloom`, remove the
  no-PyPI badge comment, and add version + python badges.
- **O2: One name.** Decide whether the repository is renamed to `worldloom`
  (GitHub redirects old URLs). Afterward: a model session sweeps the docs
  site config (`site/astro.config.mjs` base path), badges, and clone URLs.
