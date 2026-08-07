# Architecture and invariants

Worldloom is a deterministic compiler wrapped around bounded generative
handshakes. It is not a document generator with consistency prompts added after
the fact.

## The thin waist

Every subsystem exchanges the same small set of typed values:

```text
Company / Employee / BusinessUnit / Site / System / Service
                              |
                              v
EnterpriseEvent ------> CanonicalFact ------> EvaluationCase
                              |
                              v
                       ArtifactIntent
                              |
                              v
                         ArtifactIR
                              |
                              v
                   ArtifactManifestEntry
```

The core model contains no XLSX cell address, Jira field name, DOCX paragraph,
or LLM client. Industry modules do not write renderer structures. Renderers do
not query the world or invent facts.

That boundary permits two independent extension directions:

- a vertical adds an episode, fact kinds, documents, invariants, and evaluation
  families without adding industry-specific fields to `World`;
- a renderer adds a projection of `ArtifactIR` without changing the episode or
  canonical state.

## Decision ownership

| Owned by deterministic code | Owned by a generative author |
| --- | --- |
| IDs and entity existence | Natural language and judgement |
| Arithmetic and allocation | Explanatory emphasis |
| Event order and validity windows | Voice and register |
| Reporting and dependency graphs | Document organization within a grammar |
| Artifact author, audience, type, and fact scope | Claims supported by offered facts |
| Authority, supersession, revision, restatement | Which defensible implication to foreground |
| Evaluation truth and evidence | Candidate worlds, lore, processes, and document types proposed through lints |
| Replay keys and recipe steps | Responses to bounded handshakes |

The generative side proposes. A deterministic review either returns all findings
or commits the proposal. Nothing crosses the boundary because a prompt asked it
to behave.

## The world lifecycle

```text
            describe                simulate
inputs ----------------> blueprint -----------> world
  |                           |                  |
  |                           | immutable        | append-only events/facts
  |                           v                  v
  |                       describe()         scenario.run()
  |                                              |
  +---------------- recipe ---------------------+
                                                 |
                                                 v
                                         artifact intents
                                                 |
                                         compile / narrate
                                                 |
                                                 v
                                             ArtifactIR
                                                 |
                                             render/export
```

A `Blueprint` is an immutable description. `build()` is the boundary at which
entities and facts are minted. Scenario execution returns a new `World` and
records a replayable recipe step. A loaded corpus is evidence: it is queryable,
renderable, and validatable, but it does not retain the hidden generator state
needed to advance it casually.

## Artifact cohesion

An artifact is cohesive because its scope is a data contract before prose or
layout exists.

```text
ArtifactIntent
+---------------------------+
| artifact_type             |
| domain                    |
| author_id + function      |
| audience + access policy  |
| created_at + knows_as_of  |
| required_fact_ids         |
| triggered_by              |
| authority + lifecycle     |
+-------------+-------------+
              |
              v
       compile and contract
              |
     +--------+---------+----------------+----------------+
     |                  |                |                |
     v                  v                v                v
declared type?   eligible author?   cohesive title?   facts in scope?
     |                  |                |                |
     +------------------+----------------+----------------+
                                |
                                v
                    ArtifactIR + artifact-contract@1
```

Compilation refuses:

- an artifact type without a declared standing and outline;
- an undeclared business domain;
- an author whose function cannot own that domain;
- an empty audience or title;
- a title with no meaningful signal from its artifact family;
- any table cell or narrative reference outside the intent's required facts.

The accepted IR is stamped with artifact type, domain, audience, author ID,
author function, scoped periods, scoped subjects, and
`cohesion_contract=artifact-contract@1`. The subtitle defaults to the real
employee's title and audience. All renderers consume this same IR.

The contract is intentionally renderer-independent. Fixing title cohesion in the
PDF renderer would leave DOCX, PPTX, and Markdown free to drift. Enforcing it at
the IR boundary makes every current and future renderer inherit the same rule.

## Fact references, not copied numbers

Narrative requests do not ask an author to repeat values. A response uses a fact
reference:

```json
{
  "text": "Food finished {{fact:FACT-0028}} against plan.",
  "claims": [
    {
      "text": "Food finished below plan.",
      "supporting_fact_ids": ["FACT-0028"]
    }
  ]
}
```

The renderer substitutes the localized display value from the fact ledger. A
workbook, PDF, and board deck therefore do not hold three copies of the same
amount. A typed digit outside a fact reference is rejected by the narration
contract.

## Time, authority, and lifecycle

Worldloom separates questions that ordinary corpora flatten:

- `valid_from` and `supersedes` decide which fact held at a point in time;
- authority decides which concurrent account is entitled to answer;
- `revises` replaces an artifact version;
- `restates` creates a new filing while leaving the original on the record;
- employee `joined` / `left` and entity lifecycle windows define as-of views;
- `knows_as_of` limits the evidence an artifact author could cite.

Collections expose these semantics directly through `world.as_of(...)`,
`world.org_at(...)`, `world.business_units_at(...)`, `world.sites_at(...)`,
`world.systems_at(...)`, `world.services_at(...)`, `world.visible_to(...)`, and
`world.authoritative(...)`.

Current topology analysis defaults to active systems and services. Historical
validation can explicitly inspect all lifecycle rows, preventing a retired node
from hiding an old cycle while also preventing it from inflating current blast
radius.

## Named roster versus aggregate workforce

`Company.employees_total` is the authoritative workforce scale. The named roster
is a bounded graph of decision-makers, owners, authors, and actors.

The separation is required for enterprise scale, but it creates an invariant:
active named employees may never exceed aggregate headcount. The invariant is
enforced at four boundaries:

1. timeline sampling simulates aggregate and named capacity before proposing a
   hire;
2. timeline review rejects `hire_exceeds_headcount`;
3. direct `Hire.run` refuses the same contradiction;
4. corpus validation checks current and historical roster/headcount states.

This is the general pattern in Worldloom: prevent invalid state near the write,
then independently detect it after load or tampering.

## Replay and determinism

A corpus records two kinds of provenance:

- the **recipe** records deterministic construction and scenario steps;
- the **generation ledger** records accepted generative decisions under
  content-addressed keys.

```text
seed + recipe + worldloom version + generation ledger
                            |
                            v
                       rebuild world
                            |
                            v
                   exact file-set and byte diff
```

Clocks, process-randomized `hash()`, unseeded randomness, and UUIDs are excluded
from generation paths. Prompt text is versioned data because changing it changes
ledger keys.

At batch scale, `mosaic.json` stores a digest of the global plan. Shard ownership
is a pure function of world index. Section checkpoints are newline-framed JSONL,
appended with `O_APPEND` and fsync. A missing final newline proves an interrupted
append and only that tail is truncated; a malformed newline-terminated record is
committed corruption and remains fatal.

## Validation is independent

The validator is not a cleanup step inside generation. It loads the resulting
world and checks invariants without trusting the producer. Check groups include:

- referential integrity and file existence;
- reporting, dependency, provenance, revision, and restatement graphs;
- financial reconciliation, ratios, allocations, formulas, and detail tables;
- temporal validity, employment windows, and knowledge cutoffs;
- authority contests and supersession;
- access policy and author visibility;
- lore reachability and authored-spec lints;
- workforce and lifecycle invariants;
- evaluation evidence, distractor separation, and abstention;
- actor observations, policy, tool authority, and ledger replay.

Validation failures are defects, not warnings. A feature is not complete because
its own generator produced plausible output; it is complete when an independent
gate can refute malformed state.

## Diversity and difficulty are separate gates

Coherence does not imply diversity, and diversity does not imply retrieval
difficulty.

`worldloom diversity` fingerprints artifact structure and can group
near-duplicate passages. `worldloom topology` measures graph depth, blast radius,
and chokepoints. `worldloom series` reads trend, season, and residuals.
`worldloom evaluate` scores BM25 and TF-IDF against fact-derived cases.

These measurements answer different questions. Passing one is not evidence for
another.

## Extension boundaries

| Change | Correct seam |
| --- | --- |
| Different company identity or vocabulary, same episode | Pack |
| Different company claims using implemented consequences | Facets or company specification |
| Different numeric physics | Parameter overrides or probe |
| New document using existing fact kinds | Authored document type |
| New recurring process using declared kinds | Episode/process grammar |
| New causal episode, documents, checks, and benchmark | Vertical |
| New output format | Renderer consuming `ArtifactIR` |
| New coherence rule | Independent validator check group |

Read [generation-model.md](generation-model.md) before moving a decision across
these seams. Most architectural regressions in a synthetic-data system begin as
two layers both believing they own the same fact.
