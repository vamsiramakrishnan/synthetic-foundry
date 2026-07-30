---
name: worldloom
description: Generate a coherent synthetic enterprise corpus with Worldloom — build a world from a seed, write the prose it needs under fact constraints, render it to XLSX/Jira/Confluence/ServiceNow, and validate that every document agrees. Use when asked to create synthetic enterprise data, a RAG or agent evaluation corpus, a fictional company's documents, or to add a scenario, renderer, or industry to this repository.
---

# Worldloom

You are the model. Worldloom is the harness: it builds a coherent enterprise
deterministically, decides which documents that enterprise would have, hands you a
bounded request per document section, and rejects any prose that contradicts the
facts.

Read `AGENTS.md` in the repository root for the full contract. This skill is the
procedure.

## Before starting

```bash
pip install -e ".[xlsx]" && worldloom --help
```

If `worldloom` is not on PATH, use `python3 -m worldloom.cli` in its place
throughout.

## Procedure

### 1. Build the world

```bash
worldloom build --seed <SEED> --period <YYYY-MM> --incident --out ./corpus
```

- `--seed` any integer. The same seed always produces the same world.
- `--incident` / `--no-incident` forces the operational incident on or off. Omit
  both to let the seed and the world's lore decide, which is the more interesting
  behaviour — whether a close goes wrong follows from a decision made two years
  earlier in the world's history.

Report the summary table to the user: company name, headcount, facts, artifacts,
evaluation cases.

### 2. Fetch the prose requests

```bash
worldloom narrate requests ./corpus -o requests.json
```

Read the file. It is self-contained — the rules, the facts you may use, which are
required, what the author knew and when, the voice, the audience, the length.

### 3. Write the prose

Create `responses.json`:

```json
{"responses": [{"id": "<request id>", "text": "...", "claims": [{"text": "...", "supporting_fact_ids": ["FACT-0001"]}]}]}
```

One entry per request, `id` copied exactly. The rules that get violated most often,
in order:

1. **Never type a number.** Every figure, percentage, and date is
   `{{fact:FACT-0028}}`. This is checked lexically — any digit outside a reference
   is rejected. It exists so a deck and its source workbook read the same ledger
   entry and cannot drift apart.
2. **Respect `knows_as_of`.** The document's author cannot know anything recorded
   later. A triage page written mid-incident must not cite the cause confirmed
   hours afterwards.
3. **A `superseded: true` fact is a past belief** — write it as history ("it was
   initially recorded as…"), never as the current position.
4. **Cite only the facts in that request**, and give every claim its supporting
   IDs.
5. **Invent no entity** not present in the facts.

Write documents, not lists. One sentence per fact is correct and dull; lead with
the position, group what belongs together, say what it means. Sections were given
different facts on purpose, so do not restate the group position in a section about
business units.

### 4. Submit

```bash
worldloom narrate accept ./corpus --from responses.json --model-id claude-opus-5
```

**Expect rejection on the first pass.** Every violation is reported at once with
the rule it broke and the offending text. Fix exactly what it names and resubmit.
Nothing is committed until every response passes, so there is no half-narrated
state to clean up.

Never respond to a rejection by editing the corpus, relaxing a check, or dropping
the offending fact. The violation is correct; the prose is wrong.

### 5. Render and validate

```bash
worldloom render ./corpus -f xlsx -f markdown -f jira -f confluence -f servicenow
worldloom validate ./corpus
```

Validation runs over a thousand checks: reconciliation, referential integrity, the
org graph, temporal ordering, lore, access. All must pass.

### 6. Show the user what they have

```bash
worldloom inspect ./corpus --evals
```

Worth surfacing: the evaluation cases (questions with ground-truth answers,
citations, distractors, and temporal cut-offs), and the fact that two documents
disagree *on purpose* where they were written at different times.

## Optional: prove determinism

```bash
worldloom build --seed <SEED> --incident --replay ./corpus -f markdown --out ./again
diff -r ./corpus ./again
```

The replay makes no model call — every request is served from the generation
ledger. Useful to demonstrate that the corpus is citable: a seed plus a ledger
reproduces it exactly.

## Working without writing prose yourself

For a quick corpus where narrative quality does not matter:

```bash
worldloom build --seed 8128 --incident --narrate -f xlsx -f markdown --out ./corpus
```

`--narrate` uses a built-in deterministic provider that emits correct but flat
prose. Use it for smoke tests and demos of the pipeline. Do not use it when the
user wants a corpus that reads like real documents — that is what you are for.

## Extending the repository

Read `docs/build-order.md` first. It sequences the work and gives each step an exit
gate, and the order is deliberate: several steps exist to stop a later one being
built on guesses.

- New format → `src/worldloom/render/`, register it in `render/__init__.py`. A
  renderer reads the artifact IR and nothing else.
- New scenario → `src/worldloom/scenarios.py`. There is deliberately no scenario
  DSL yet; one is due at step 7, after a second industry shows which parts repeat.
- New industry → its own module beside `retail.py`. Industry specifics never go in
  the core world model.
- New coherence rule → `src/worldloom/validate.py`, and add a test that the rule
  can actually fail.

Never introduce a clock, `random`, or a UUID: ledger keys are content addresses and
CI diffs a regenerated corpus byte-for-byte. Use `worldloom.ids.content_key`.
`pytest -q` and `worldloom validate retail-close` must both pass before committing.
