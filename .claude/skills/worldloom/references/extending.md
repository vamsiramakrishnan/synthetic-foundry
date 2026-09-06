---
title: Extending Worldloom
description: Add a format, scenario, industry, or coherence rule without crossing the generation boundary
read-when: Changing this repository rather than using it: a new renderer, scenario, vertical, or validator
tags: [extending, determinism, renderers, scenarios, validators]
---

# Extending Worldloom

You are changing the repository, not using it. Read `docs/build-order.md` and
`docs/generation-model.md` before this if you have not. This file assumes both,
and only restates what an extension actually needs.

## The generation boundary: read this before writing any code

Worldloom has two engines, and the single most important decision in this
codebase is which one owns a given thing:

> The deterministic engine owns what must be *correct*: arithmetic, identity,
> graph integrity, time. The generative engine owns what must be *plausible*:
> language, judgement, narrative.

**Nothing is owned by both.** A number is either computed by the deterministic
layer and referenced by prose, or it does not appear in prose at all. An entity
either exists in the graph and is citable, or it does not exist and cannot be
mentioned. There is no middle case where the model "mostly" gets a number right.

Every extension decision reduces to one question: *which side is this on?* If
you cannot answer that cleanly for a new feature, the feature is not designed
yet. Go back to `docs/generation-model.md` and find the row it belongs to
before writing code. The most common way this goes wrong is a new artifact
field that quietly lets generated prose carry a figure or an entity name that
the deterministic layer never validated. That field is a `bare_number` or
`unknown_entity` violation waiting to happen, and it will not surface until an
agent runs `narrate accept` and gets rejected for something extending.md should
have stopped them from writing.

---

## Where each kind of change goes

### New render format

Goes in `src/worldloom/render/`, registered in `render/__init__.py` via
`register(name, render_all_fn)`. A renderer's contract is narrow: it reads an
`ArtifactIR` and nothing else (no facts, no world, no model). That
is what lets two formats of the same artifact agree without a synchronisation
step: they are independent projections of one resolved structure, not two
things that were separately told the same facts and might drift.

**Any Office format must call `render/ooxml.py::normalise()` on its finished
bytes.** XLSX, DOCX, and PPTX are all zip archives of XML parts, and all three
of openpyxl, python-docx, and (eventually) python-pptx stamp a wall-clock
modification time into the zip's per-entry metadata and into `docProps/core.xml`,
so a save today and a save tomorrow of an *identical* document differ in bytes.
That breaks the project's central claim: a world regenerates byte-for-byte from
its seed and ledger, and CI diffs the corpus to prove it. `normalise()` rewrites
the zip timestamps to a fixed epoch and, if you pass `created=`, overwrites the
core-property dates with a stamp derived from the world (never `datetime.now()`).
This was found by CI, not locally: two local runs shared a second by luck for
weeks before a CI run landed either side of a boundary and the diff failed.
Do not assume your renderer is exempt because it "only writes text"; if it goes
through any of the three Office libraries, it goes through `normalise()`.

Formulas are a similar trap in reverse: *which* cells are computed, and from
what, is a semantic fact the compiler in `documents.py` already decided and
put in the IR as a `sum` / `difference` / `ratio_pct` / `reference` declaration.
A renderer's job is only to spell the declaration in its format's syntax:
`=SUM(C4:C6)` for XLSX, the literal value for Markdown. A renderer that invents
its own formula logic instead of reading the declaration is the two-formats-
disagree bug in a new shape.

### New scenario

Goes in `src/worldloom/scenarios.py`. Read `MonthEndClose`, `Hire`, `Departure`,
and `Reorganisation` there for the shape every scenario follows: a frozen
dataclass holding whatever parameters it needs (typically at least `period`),
a `run(self, world: World) -> World` method, and a body that derives a scoped
`Rng` (`rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{...}")`),
calls into `generators/`, and ends with `return world.extend(...)`. The world
passed in is never mutated: `World` is frozen, and `extend` returns a new one.

**There is deliberately no scenario DSL.** Designing one now would encode
guesses about what varies between scenarios rather than facts about it. That
generalisation is scheduled for build-order step 7, gated on a second industry
existing to show which parts of `MonthEndClose` versus `Hire` versus
`Departure` actually repeat and which only look similar because there is only
one example of each. Add a fifth scenario the same way the first four were
added: as its own dataclass, duplicating structure with the others where it
must, rather than reaching for an abstraction with a sample size of one.

### New industry

Goes in its own module beside `retail.py`; the plan names `it_services.py`
as the next one. Industry specifics never go in the core world model.
`retail.py` is the model to follow: it holds the archetype's lore, the
incident-likelihood constant, and anything else that is true of retail
specifically, and it imports `World`, `Minter`, and the lore/RNG primitives
from core rather than the reverse. Nothing in `models.py`, `world.py`, or
`validate.py` should ever import from an industry module or branch on
industry. If you find yourself adding `if company.industry == "retail":`
inside core, the thing you are adding belongs in the industry module instead,
even if that means duplicating a little structure until a second vertical
proves what is actually shared.

### New coherence rule

Goes in `src/worldloom/validate.py`, in whichever of the five groups it
belongs to: referential, graph, financial, temporal, or lore (the module
docstring explains each). **You must also add a test that the rule can
actually fail.** A validator nobody has seen fail is a validator that might
not work: it is trivial to write a check with an inverted condition, an
off-by-one on a boundary, or a type comparison that silently never matches,
and a passing test suite will not catch any of those unless something in it
constructs the violating case on purpose.

`tests/test_lifetimes.py` is the worked example, and its own docstring states
the principle directly: it hand-builds a departure, a unit that closes, and a
revision chain rather than relying on a generator to happen to produce one,
because "a violation has to be constructed to prove a check fires at all, and
a coherent world by definition contains none." Follow its pattern: helpers
like `_employee_with` and `_unit_with` copy the fixture world with one field
replaced (everything is frozen, so this is `model_copy(update=...)` plus
`dataclasses.replace`, never mutation), and assert your new violation code
appears in `world.validate().violations` for the doctored world and does not
appear for the clean fixture.

State in the validator's docstring or a comment *why* the rule exists.
Several of the sharper checks in this file exist because a real defect
surfaced first and the check was added afterward to make sure it could not
come back silently. That context is what stops a future edit from "simplifying
away" a check that looks redundant but is guarding a specific incident.

---

## The determinism rules, and what each protects

A world must satisfy `World.from_seed(8128) == World.from_seed(8128)` forever,
across machines and across time, because a seed in a paper or an eval harness
is a promise to reproduce exactly what was measured. Four rules follow from
that promise, and each protects a specific failure:

- **No clock.** `datetime.now()` anywhere in generation makes every run
  different by construction. Dates come from the world (a period string, a
  fact's `valid_from`, an event's timestamp), never from wall-clock time. This
  bit the DOCX renderer indirectly: python-docx doesn't call `now()`, but it
  ships its template's own 2013 timestamps unless told otherwise, which is a
  smaller lie than the clock and still a wrong one; the fix was making the IR
  carry `worldloom_created` derived from the newest fact an artifact cites.
- **No `random`.** Use `Rng` (`src/worldloom/rng.py`), seeded from
  `content_key(seed, label)`, never the stdlib module directly.
- **No UUID.** IDs come from `Minter` (`src/worldloom/ids.py`), which mints
  sequentially per prefix: the *n*-th fact of a run is always `FACT-000n`,
  deterministically, because the traversal order that calls `minter.next(...)`
  is itself deterministic.
- **No builtin `hash()`.** Python randomises string hashing per process
  specifically to resist hash-flooding attacks, which means `hash("finance")`
  differs between two runs of the same script. Ledger keys and RNG seeds need
  a hash that is stable across processes, so both go through
  `worldloom.ids.content_key`, which is SHA-256 truncated to 32 hex characters.

**RNG streams derive by name, not by position.** `Rng(seed).derive("finance")`
is independent of whatever `Rng(seed).derive("organisation")` drew, and in what
order. `rng.py`'s own docstring states the reason directly: if every generator
shared one stream, adding a single draw anywhere upstream would reshuffle every
downstream draw, and a seed would stop meaning anything the moment a later
version of the code inserted one more random choice. When you add a new draw
inside an existing generator, derive a new named child stream for it
(`rng.derive("something-specific")`) rather than pulling another value off the
stream you were handed. Pulling from the shared stream is the
position-dependent coupling this design exists to avoid.

**Prompt text is versioned data**, in `src/worldloom/narrative/prompts.py`.
Editing a prompt template's text in place is not a wording tweak. The
template's `version` is part of the generation ledger key
(`content_key(seed, call_site, ordinal, fact_digest, model_id, prompt_version)`
in `narrative/compiler.py`), so editing the template without bumping `version`
means the *same key* now points at prose generated against a different prompt
than the one the ledger recorded. Anyone replaying the seed gets prose that
looks cached-and-correct but was never actually produced by the process the
ledger claims. Bump the version whenever the template text changes, even for
what looks like a typo fix.

---

## ID stability: a real trap, not a theoretical one

IDs are minted sequentially by `Minter`, in the order generators call
`minter.next(prefix)`. That means **inserting a new ID-minting call anywhere
before an existing one runs shifts every ID after it**: `FACT-0042` silently
becomes `FACT-0043` the moment something upstream mints one more fact.

This matters because `examples/grocery-close/narration.json` is real,
hand-written agent prose, not a fixture generated by the pipeline, checked
into the repository and replayed by CI against a freshly rebuilt corpus. It
cites facts by their exact ID (`{{fact:FACT-0091}}` and similar). If a code
change shifts IDs, that narration now cites the wrong fact, or a fact that no
longer exists, and CI fails, correctly, because the prose the file claims was
accepted no longer matches what the corpus would generate today.

This is *why* founding milestones (the company's founding, past leadership
changes, and similar history baked in before any scenario runs) draw from
their own `MFACT` sequence instead of `FACT`. Milestones are minted once, at
build time, before any scenario runs; if they shared the `FACT` sequence,
adding one more milestone would renumber every scenario-minted fact after it,
and the grocery-close narration would break on a change that has nothing to
do with the March close it cites. Both prefixes are canonical facts and both
are citable (see `FACT_REFS` in `validate.py`); only the sequence differs, and
only because of this problem.

**If you add anything that mints new IDs, put it where it cannot shift
existing ones**: append a new sequence, or make sure the new minting happens
strictly after everything the frozen narration depends on. Then check your
work with the same commands `AGENTS.md` gives for the loop generally:

```bash
worldloom build --seed 8128 --incident --archetype australian_grocery --comparatives 11 --out ./ref
worldloom narrate accept ./ref --from examples/grocery-close/narration.json --model-id claude-opus-5
```

If the second command reports rejections or an unknown-fact error where it
previously reported a clean accept, something upstream renumbered IDs and you
have found the shift before CI did.

---

## Before committing

```bash
pytest -q
worldloom validate retail-close
```

Both must pass locally. CI additionally regenerates a corpus from its
generation ledger and diffs it byte-for-byte against the checked-in one,
including the XLSX and DOCX bytes, so anything non-deterministic (a clock, a
stray `random` call, a UUID, a prompt edited without a version bump, an
Office renderer that skipped `normalise()`) fails there even when every local
test passes, because none of the local tests re-run generation from a
ledger the way CI's replay check does.

---

## Documentation is checked, not optional

If you add a CLI command, you must document it or the build fails.
`tests/test_harness_docs.py` runs three checks that matter here:

- every `worldloom ...` invocation inside a fenced code block in an
  agent-facing document must be a command (and every flag on it) that the CLI
  actually has, so this file, and the others, cannot drift from reality
  without a test noticing;
- every real CLI command must be *mentioned* in at least one hand-written
  agent-facing document (not just the generated reference, which by
  construction lists everything and therefore can't prove anyone would find
  it), so a new command that never gets written into the procedure fails the
  build until it does;
- `.claude/skills/worldloom/references/commands.md` must exactly match what
  `worldloom docs` would regenerate; run `worldloom docs` after adding or
  changing a CLI option and commit the result.

**Do not put hardcoded counts in prose**: "183 tests", "over a thousand
checks", a specific fact count for a specific seed. Numbers like that drift
the moment anyone adds a test or a generator changes, and nothing checks prose
counts against reality the way `test_harness_docs.py` checks commands against
the CLI. Say "a large world runs tens of thousands of checks" rather than a
number you read once and will not maintain.

---

## Known rough edges

Things to know before you extend near them, stated plainly rather than
glossed over:

- **`documents.py`** is over a thousand lines carrying the workbook compiler,
  the outline compiler, and every artifact type's section plan together. It
  works, but a change to one artifact type's plan is easy to make in a way
  that accidentally touches another's, because they are not separated into
  their own modules yet.
- **`Category` and `Site`** (in `models.py`) are retail nouns sitting in the
  thin waist rather than in `retail.py`. They were promoted early because the
  reporting hierarchy (category → unit → group, and separately site → unit)
  needed first-class entities before there was a second industry to prove the
  abstraction against. A second vertical will either need its own equivalent
  concepts promoted alongside them, or will need `Category`/`Site` genuinely
  generalised; expect to touch this when `it_services.py` lands.
- **`models.py`, `validate.py`, and `narrative/providers.py`** are the other
  files most likely to break on a second vertical, for the same reason: they
  were written against one industry's shape, and some of what looks like a
  core concept in them is really a retail concept that has not been forced to
  generalise yet.

These are not bugs to fix pre-emptively. Build-order step 7 is explicit that
the second implementation determines the architecture, and guessing at the
generalisation now would encode retail's shape as if it were universal. They
are named here so an extender recognises the friction as expected when it
shows up, rather than assuming they broke something.
