# Narrate programs, not instances

A prose program is authored once for an artifact type, section, voice and audience.
It expands against each section's allowed facts. Expansion makes no model calls.
The existing narrative validator still checks every expanded instance.

```python
from worldloom import RetailWorld, MonthEndClose
from worldloom.narrative import programs

world = RetailWorld(seed=8128).build().run(MonthEndClose(period="2026-03")).compile()
plan = programs.plan(world, budget=programs.Budget(model_calls=40))
author_requests = plan.author_requests()
```

`author_requests` are JSON-compatible contracts for an external coding harness.
The library does not choose or invoke a model. Missing authored families use an
explicit deterministic tail program. They are not reported as model-authored.

## Program contract

```python
program = programs.NarrativeProgram(
    family=plan.families[0].id,
    variant=0,
    clauses=(programs.ProgramClause(
        id="position", kind=plan.families[0].fact_kinds[0],
        minimum=0, maximum=8,
        alternatives=(
            "The recorded position for $subject is $value.",
            "For $subject, the record gives $value.",
        ),
    ),),
)
```

Each clause selects one declared fact kind, with bounded cardinality. Alternatives
may use only `$subject`, `$kind` and `$value`. No expressions, imports, embedded
queries, literal digits or concrete fact references are allowed. `$value` expands
to the existing fact-reference token, not a copied number. Author programs against
all the roles the family needs: an omitted required fact rejects the instance.
The example illustrates syntax, not a complete authored pack.

```python
findings = programs.accept_programs(plan, [program])
# Repair findings and cover every required role before expansion.
sections = programs.expand(world, plan, [program])
report = programs.measure(sections)
```

## Cache and repair

`ExpandedSection` records a program key, input key, output hash, selected
alternatives and clause-to-fact dependencies. The input key includes only bound
facts and their subject labels, plus request identity and cutoff. Changing an
unused fact does not invalidate prose. Changing a bound fact does.

```python
cache = {section.input_key: section for section in sections.sections}
repeated = programs.expand(world, plan, [program], cache=cache)
affected = sections.affected_by(["FACT-ID-FROM-THIS-WORLD"])
```

Re-plan after the world changes. Compatible entries in the old cache remain
usable. Cache corruption and stale plans refuse rather than silently generating
different text. Selection uses stable content hashes, not the global RNG.

## Diversity is a gate

Measurement reuses Worldloom's exact, prefix-filtered Jaccard similarity join.
Fact IDs are normalized so different IDs cannot disguise copied prose. Reports
identify redundant requests and the families to repair. `Budget.near_dup_rate`
bounds the redundant-section fraction at `Budget.similarity_threshold`.
This measures actual output; a guessed number of variants is not a guarantee.

## Blind reader checks

```python
from worldloom.narrative import reader_checks

requests = reader_checks.requests(world, sections, share=0.05)
# An external reader answers these requests with ReaderResponse objects.
# It must not receive answer keys. Its returned objects are `responses` below.
findings = reader_checks.check(world, sections, responses, share=0.05)
```

A reader receives rendered section text and demanded aspects, not expected fact
IDs or expected values. The checker verifies returned values, kinds, subjects
and copied quotations. Missing responses fail. A stale text digest fails.
These are mechanical answer-recovery checks, not a proof of prose quality.
No reader model has been run just because a request file exists.

Set `Budget.reader_check_share` above zero to require those responses at commit.
Zero records no reader validation; it does not report an implicit pass.

```python
narrated = programs.commit(world, sections, reader_responses=responses)
narrated.export("narrated-corpus")
```

Commit rechecks freshness, diversity, hashes, optional reader findings and the
existing claims gate. Programs and dependencies travel in the normal generation
ledger. A recipe step restores that metadata before ordinary narration replay.
The exported corpus replays with an unreachable provider and no model calls.

For a deterministic smoke fixture, use `Budget(model_calls=0, near_dup_rate=1)`.
That explicitly tolerates repetitive tail prose; it is not a production quality
setting. Authoring-call budgets and local tests are not measured provider
billing, latency, or reader-model success rates.
