# retail-close — the golden episode

A fictional omnichannel retailer completing its March 2026 month-end close, during
which the inventory valuation pipeline fails and the close lands one business day late.

**Hand-authored. No LLM was involved.** That is the point: the corpus contract is fixed
before any generator or prompt exists, so prompt behaviour cannot shape the
architecture. An empty generation ledger is the proof, and a test asserts it.

```bash
worldloom demo retail-close      # validate and export
worldloom inspect retail-close --facts --events --evals
worldloom evals export retail-close --out evals.jsonl
```

## What is in it

| | |
| --- | --- |
| Company | Southern Cross Retail Group, Sydney |
| Business units | Food, General Merchandise, Digital |
| People | 20, one reporting tree |
| Systems / services | 5 / 4 |
| Lore commitments | 5 |
| Events | 14 |
| Facts | 55, including one supersession chain |
| Artifacts | 10, across 5 formats |
| Labelled imperfections | 6 |
| Evaluation cases | 28, covering all 8 question types |

## Why it is a benchmark and not a pile of files

**The numbers reconcile.** Business unit revenue sums to group revenue; every variance
equals actual less budget; gross margin percentages are derived from the gross profit
and revenue on the same sheet. `worldloom validate` checks all of it.

**The wrong answer is available.** At 09:10 on 1 April the cause was recorded as an
overnight ERP outage. At 11:45 that was ruled out; at 13:20 the real cause — a stale
product hierarchy mapping — was confirmed. Both facts survive with different validity
and authority. A draft status page still asserts the first one, because nobody updated
it.

That makes the temporal questions real:

```python
world.as_of("2026-04-01T10:00:00+00:00").where(kind="ops.cause").one()
# -> "Overnight Helios ERP outage"          (correct at that moment)

world.as_of("2026-04-01T14:00:00+00:00").where(kind="ops.cause").one()
# -> "Stale legacy-to-new product hierarchy mapping in Merchandising Hub"
```

**Documents disagree on purpose, and the disagreement is labelled.** The executive
summary presents the incident as a technical pipeline problem, omitting the control
failure and the November 2025 recurrence that are both in the CFO memo it derives from.
That omission is recorded as `ERR-0003` against `FACT-0049`, so a grader knows the
truth even though the document does not tell it.

**The episode explains itself.** The mapping is stale because of a 2024 category
restructure that left a manual mapping table (`LORE-0001`); nobody caught the drift
because the table has no owner (`LORE-0002`); the delay was escalated because the close
calendar commits to four business days (`LORE-0003`); a workaround was accepted because
finance tolerates them under close pressure (`LORE-0003`). Five commitments, and none of
the episode is authorial fiat.

## Layout

```
world.json                 company, units, people, systems, services, personas, policies
lore.jsonl                 5 commitments, each constraining ≥1 downstream decision
facts.jsonl                55 temporal facts, append-only
events.jsonl               14 events, causally linked
artifact-manifest.jsonl    provenance for every artifact
intentional-errors.jsonl   6 labelled imperfections
evals.jsonl                28 evaluation cases
artifacts/                 the artifact bodies
```

## Known deviations from the build order

**Facts.** `docs/build-order.md` specifies 30–50; this has 55. Reconciling at two
levels (unit and group) across revenue, gross profit, and margin, while also carrying a
supersession chain, needs more than 50. The spec has been updated rather than the
fixture trimmed.

**The workbook is Markdown, not XLSX.** `month-end-model.md` carries the tables and
records its fact IDs. Hand-authoring a binary would fix the contract in the wrong place:
artifacts are projections of facts, and the XLSX renderer at step 5.1 will project these
same facts. Formulas, named ranges, and hidden lineage sheets arrive with the renderer.
