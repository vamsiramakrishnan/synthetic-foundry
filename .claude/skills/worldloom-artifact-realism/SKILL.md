---
name: worldloom-artifact-realism
description: Improve how a generated world materialises into documents, decks, workbooks, tickets, pages and email through bounded proposals the deterministic host accepts or refuses, covering organisation DNA, surface plans, lifecycle chronology, and product-faithful connector fixtures. Use when rendered artifacts look generic, when a deck or workbook needs to read like its real product, or when asked to make a corpus's documents more realistic without touching a fact.
tags: [worldloom, artifacts, realism, ecology, rendering, connectors]
---

# Worldloom artifact realism

Use this skill when improving how a generated enterprise world materialises into documents, decks, workbooks, tickets, knowledge pages, or email.

## Contract

Worldloom owns truth. The harness owns proposals.

A proposal may choose structure, emphasis, prose, visual density, component order, and one of the bounded artifact families exposed by `worldloom.artifact_ecology`. It may not create a business fact, change a fact value, mint a lifecycle timestamp from wall time, invent an unsupported cross-system reference, or weaken a validator.

The deterministic host decides whether a proposal is accepted. Rejection is a normal search result, not an instruction to relax the gate.

## Workflow

1. Build or load a world and inspect its artifact intents, IR, facts, events, actors, and recipe.
2. Run `worldloom.ecology.prepare(world)` before proposing presentation changes. Read the returned organisation DNA, per-artifact surface plans, lifecycle histories, and realism report.
3. For prose or layout experimentation, construct an `ArtifactProposal` containing only the target artifact id, surface, proposed family, and text/layout fragments.
4. Run `review_proposal(world, proposal)`. Fix every finding. Never remove a finding from the validator to accept a proposal.
5. Render through `worldloom.ecology.render`. Ordinary deterministic generation must still work without a model or harness.
6. For Jira, ServiceNow, Confluence, and email use `worldloom.ecology.connectors`; do not synthesize disconnected connector fixtures by hand.
7. Compare realism metrics and regression tests across at least two seeds. Same seed must replay; different seeds should vary within the organisation's bounded style distribution.

## Hard rules

- Numeric claims must resolve to existing fact ids or cells derived from those facts.
- PPTX charts and XLSX formulas must read existing IR/table cells. A chart is not a new source of numbers.
- ServiceNow and Jira are different products. Preserve their distinct lifecycle and workflow semantics.
- Email is conversational evidence. Preserve thread, reply/forward, participants, timestamps, and attachment/reference topology.
- Confluence pages belong to a space/page tree and carry versions/backlinks; do not emit isolated markdown blobs and call them pages.
- Lifecycle time comes from simulated world time. Never call `now()` for artifact history.
- Keep organisation style correlated across surfaces, but derive artifact-local variation from named deterministic streams so a company does not collapse to one template.
- Do not copy identical prose across surfaces. The same episode should produce different views of the same facts.
- Legacy recipes remain byte-stable unless they explicitly opt into `artifact_realism=ecology/v1`.

## Review questions

Before accepting a change ask:

- Does this improve the artifact as an artifact, or only add decoration?
- Can every number be traced to a fact or formula?
- Does the surface behave like its real product rather than generic JSON?
- Does chronology make sense?
- Are cross-surface IDs stable and non-dangling?
- Does another seed produce meaningful structural variation?
- Does replay of this seed produce the same result?
- Did the change preserve the existing renderer and validation suites?
