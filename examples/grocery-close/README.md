# grocery-close — a reference narration

`narration.json` is 23 sections of prose written by an agent against the requests
this corpus produces, and accepted by `worldloom narrate accept` on the first
pass. It is not a corpus; it is the *answer* to one, and it reproduces:

```bash
worldloom build --seed 8128 --incident --archetype australian_grocery \
  --comparatives 11 --section-omission 0 --outline-synthesis 0 --variant-bias 0 \
  --out ./corpus
worldloom narrate accept ./corpus --from examples/grocery-close/narration.json \
  --model-id claude-opus-5
worldloom render ./corpus -f docx -f xlsx -f markdown
worldloom validate ./corpus
```

## Why this is in the repository

Two reasons, and the second is the one that matters.

**It is what good output looks like.** The deterministic provider is a contract
fixture that writes plainly and repetitively on purpose. Nothing in the test suite
showed what the harness produces when a capable writer answers it, so nothing
showed whether the *requests* were good enough to be answered well. They were not,
until they carried the section's purpose, the standing context behind the figures,
and the prior period. This file is the evidence that they now are.

**It is a regression test with teeth.** The narration cites fact IDs. Change how
facts are minted, or what a section is given, and `narrate accept` fails loudly
rather than quietly producing weaker prose. That is friction, and it is the right
friction: a corpus whose fact identity moved is a corpus whose evaluation set,
citations, and ledger keys all moved with it.

## What to look at

The variance memo's *Drivers* section is the one worth reading. It notices that a
divisional driver exceeds the whole group movement, says so, calls it structural
rather than one-off, and alludes to the joint-campaign dispute behind it without
asserting it as a finding — because the dispute reached the writer as background,
which may be reasoned from and not cited.

Every figure in it is a `{{fact:ID}}` reference. None was typed.
