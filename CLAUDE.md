# Worldloom

**Read [AGENTS.md](AGENTS.md) first.** It is the harness guide: you are the model,
Worldloom builds the world and checks your prose against it. Everything below is
Claude Code specifics on top of that.

## Skill and commands

A skill drives the whole loop, including the rejection cycle:

```
/worldloom
```

Individual steps, if you want to drive it yourself:

```
/worldloom-build      build a world from a seed
/worldloom-narrate    fetch requests, write prose, submit until accepted
/worldloom-render     materialise and validate
```

## Shape of the work

The loop is `build → narrate requests → write → narrate accept → render → validate`.
Expect `narrate accept` to reject on the first pass. Read the violation, fix that
specific thing, resubmit. Do not work around a rejection by editing the corpus or
loosening a check.

The most common rejection by far is `bare_number`: a figure typed out instead of
referenced as `{{fact:ID}}`. Percentages and dates count as figures.

## Before you commit

```bash
pytest -q
worldloom validate retail-close
```

Both must pass. CI additionally regenerates a corpus from its ledger and diffs it
byte-for-byte, so anything non-deterministic — a clock, `random`, a UUID, an edited
prompt without a version bump — will fail there even when tests pass locally.

## House style

Match the surrounding code. It is dense with *why*, not *what*: comments explain
the reason a rule exists, particularly where a simpler-looking alternative is
wrong. When you fix something the validator caught, say in the comment what it
caught — several of the sharper invariants in this repo exist because a test or CI
found a real defect, and that context is worth keeping.
