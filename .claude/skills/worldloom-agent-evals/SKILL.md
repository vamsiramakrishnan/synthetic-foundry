---
name: worldloom-agent-evals
description: Author, plan, generate, validate, and score realistic multi-connector enterprise MCP workflow evaluation corpora with WorldLoom.
---

# WorldLoom enterprise agent evaluations

Use this skill when a task concerns realistic enterprise prompts, connector fixtures, multi-tool DAGs, coverage plans, or agent-trajectory scoring.

## Workflow

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
