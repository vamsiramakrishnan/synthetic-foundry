---
name: worldloom-agent-evals
description: Author, plan, generate, validate, and score realistic multi-connector enterprise MCP workflow evaluation corpora with WorldLoom.
metadata: {tags: [worldloom, evals, mcp, connectors, workflows, scoring]}
---

# WorldLoom enterprise agent evaluations

Use this skill when a task concerns realistic enterprise prompts, connector fixtures, multi-tool DAGs, coverage plans, or agent-trajectory scoring.

## Eval-first: the design drives the corpus

When the deliverable is a benchmark, start from the design, not from a corpus:

1. Write an `EvalSpec` (steps with `depends_on`, `connector`, `entity`, `operation`, `effect`; `WorldRequirement`s with a `kind` and a selector of field equalities). Read `docs/eval-first.md` for the contracts.
2. Resolve the company using `/worldloom-company`. Run `worldloom evals construct design.json --company-spec company.json --out ./campaign` (or compose `candidate_builder(blueprint, pipeline)` with `EvalCampaign(spec).construct` in Python). Existing tactics construct supported demands on the company's own episode. Read `docs/company-eval-reuse.md` for the complete path and narration reading order.
3. Read the manifest's `constructions`. A refusal names the seam that owns the missing state (a fact belongs to an episode; a derived artifact field belongs to a revision chain). Change the design or the base, never the validator.
4. Narrate and render via `run.map_worlds(...)`; this revalidates and rebinds the final evidence. Check `attempts[].validation.shape_checks`, including unsupported volume/layout constraints. Use `run.select(count)` for measured diversity while preserving all attempts.
5. Prove the finalized run with `run.prove(emulator_executor())`, then `run.export(...)`. These reuse the same worlds. Reference executability is not semantic answer correctness: see the executor limits in the reuse guide. A failed proof is a defect found before evaluating an agent.

## Workflow: from an existing world

For an executable benchmark, use `worldloom enterprise-evals qualify ./corpus
--pool-size 128 --limit 64 --out ./qualified`. Read
`docs/enterprise-qualification.md`: admission precedes coverage, refusals retain
the requested pool denominator, and exports preserve exact tested records.
With operational projections, enable the SDK's
`with_operational_case_binding()` so coverage exercises actual shared cases.
Inspect `docs/enterprise-outcome-reuse.md` before claiming enterprise breadth,
prose quality or calibrated difficulty from these connector proofs.

## Quality and calibrated noise

Read `docs/quality-calibration.md` when prose must support eval-critical evidence
or a pass-rate band needs measured support. Use `reader_checks.plan` with the
full eval oracle; give an independent reader only `requests_document()`. Persist
failed reviews and repair the named prose through the existing authoring path.
Require complete fidelity slices and explicit distance thresholds. Ingest
observed trials with exact corpus/configuration provenance; a structural
difficulty label or reference-executor pass rate is not fitted agent difficulty.

Use `evals.calibration.calibrate_noise` to compose existing campaign transforms,
Messiness, reader/fidelity gates, cohort estimates and Archive. Declare finite
variants and disjoint held-out candidate ordinals before selection. Do not
forward its oracle-bearing grading input to the agent under evaluation. Preserve
refusals, niche holes, uncertainty and held-out status. Replay accepted records
before spending new calls; keep transport adapters outside the generation core.

The lower-level seams remain useful for inspecting individual stages:

1. Load and validate a `World`; never invent company facts outside it.
2. Start from `builtin_registry()` or author connector, process, and workflow specs. Run `registry.review()` and resolve every finding.
3. Choose a `CoverageProfile`. Use constrained covering for routine evals; exhaustive generation must stream and normally use a limit or shard.
4. Call `plan_queries(...)`. Treat each query's `generation` requirements and `expected_dag` as contracts.
5. Call `materialize_corpus(...)`; validate with `validate_corpus(...)` before execution.
6. Render real office/PDF artifacts with `render_corpus_artifacts(...)` when the query requires them.
7. Execute against an MCP server or `ConnectorSimulator` without leaking connector implementation jargon into the customer request.
8. Record `TraceCall` objects and score them with `score_trace(...)`.

## Execute an agent and grade three axes

Evaluation here is not retrieval. `worldloom evalrun` grades a run on the plan
it formed (which connector DAG), the trajectory it took (order, budget,
designed failures, Anvil's safety laws) and the outcomes it left (records
created, updated and deleted as a state diff; artifact grounding; a rated
answer). Read `docs/eval-execution.md` before interpreting a score.

```bash
worldloom evalrun cases ./cases                    # per-axis coverage; a zero is a named gap
worldloom evalrun run ./cases -o ./runs/reference  # the reference agent is the executable ceiling
worldloom evalrun run ./cases -o ./runs/mine --agent scripted:trajectories.json
worldloom evalrun compare ./runs/reference ./runs/mine
```

An error row (the agent raised) is excluded from every mean; never read it as
a zero. A regression names the axis that moved.

## Non-negotiable rules

- Generate only connector/entity/operation/format combinations admitted by a workflow and connector spec.
- Ground prompts in company, period, source roles, destination, audience, operation, verification, and failure behavior.
- Failure dimensions must alter fixture state; labels alone are invalid.
- Preserve stable identifiers, source links, manually authored content, and write idempotency.
- Every write workflow ends with readback or authoritative cross-system verification.
- Use `content_key`; do not add randomness, clock reads, UUIDs, or `hash()`.

Read [authoring.md](references/authoring.md) to extend connectors or workflows. Read [execution.md](references/execution.md) to build an MCP runner or interpret scores.
