---
name: worldloom-agent-evals
description: Author, plan, generate, validate, and score realistic multi-connector enterprise MCP workflow evaluation corpora with WorldLoom.
tags: [worldloom, evals, mcp, connectors, workflows, scoring]
---

# WorldLoom enterprise agent evaluations

Use this skill when a task concerns realistic enterprise prompts, connector fixtures, multi-tool DAGs, coverage plans, or agent-trajectory scoring.

## Eval-first: the design drives the corpus

When the deliverable is a benchmark, start from the design, not from a corpus:

1. Write an `EvalSpec` (steps with `depends_on`, `connector`, `entity`, `operation`, `effect`; `WorldRequirement`s with a `kind` and a selector of field equalities). Read `docs/eval-first.md` for the contracts.
2. Run `worldloom evals construct design.json --out ./campaign` (or `EvalCampaign(spec).construct(base_builder)` from Python). Every demand the design compiles to is constructed on a base world: witnesses the connector search finds plus one near miss per constrained field, the write step's precondition record, artifact families, access policies, events, revision chains. A demand for a file format is met by rendering it.
3. Read the manifest's `constructions`. A refusal names the seam that owns the missing state (a fact belongs to an episode; a derived artifact field belongs to a revision chain). Change the design or the base, never the validator.
4. Prove each instance through the emulated connectors with `emulator_executor()` and `execute_reference`; a proof that fails is a defect found before any model runs.

## Workflow: from an existing world

1. Load and validate a `World`; never invent company facts outside it.
2. Start from `builtin_registry()` or author connector, process, and workflow specs. Run `registry.review()` and resolve every finding.
3. Choose a `CoverageProfile`. Use constrained covering for routine evals; exhaustive generation must stream and normally use a limit or shard.
4. Call `plan_queries(...)`. Treat each query's `generation` requirements and `expected_dag` as contracts.
5. Call `materialize_corpus(...)`; validate with `validate_corpus(...)` before execution.
6. Render real office/PDF artifacts with `render_corpus_artifacts(...)` when the query requires them.
7. Execute against an MCP server or `ConnectorSimulator` without leaking connector implementation jargon into the customer request.
8. Record `TraceCall` objects and score them with `score_trace(...)`.

## Non-negotiable rules

- Generate only connector/entity/operation/format combinations admitted by a workflow and connector spec.
- Ground prompts in company, period, source roles, destination, audience, operation, verification, and failure behavior.
- Failure dimensions must alter fixture state; labels alone are invalid.
- Preserve stable identifiers, source links, manually authored content, and write idempotency.
- Every write workflow ends with readback or authoritative cross-system verification.
- Use `content_key`; do not add randomness, clock reads, UUIDs, or `hash()`.

Read [authoring.md](references/authoring.md) to extend connectors or workflows. Read [execution.md](references/execution.md) to build an MCP runner or interpret scores.
