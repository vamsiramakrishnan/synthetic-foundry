---
name: worldloom-process-catalogue
description: Compile authored industry factors into company-bound process plans, then author executable episodes through Worldloom's existing process cascade.
---

# Company process plans

Read `docs/process-catalogue.md`. Use this when an industry needs process, owner,
system, regional and channel context rather than another hand-written name list.

1. Compile `compile_company(default_company(industry))` from
   `worldloom.process_planning`. Inspect `plan.coverage` and `plan.diagnostics`.
   For a real company, supply `CompanyProcessSpec`; narrow `streams`, country
   scopes and owner overrides explicitly. Do not silently borrow another
   industry's missing core stream.
2. Open `worldloom.process.open_from_catalogue(plan, stream, engine=..., lob=...)`.
   Both engine and LOB must exist. Read `process.next_stage(session)`; the
   `process_catalogue` context is the source for activity names, controls,
   exceptions and bindings. Propose steps and kinds, accept through the existing
   lint, then propose slots and resolve. Never bypass a refusal.
3. Only a resolved, validated EpisodeSpec can drive an episode. The plan alone
   is not an execution trace. Apply the existing episode, pack, narrative and
   validation workflow after resolving the process.

For offline bulk compilation:

```bash
python -m worldloom.process_planning --all --out process-plans
```

Preserve the generated licence ledger and pinned catalogue snapshot. Replay via
`--replay` uses the exported spec and checks digests. A replacement catalogue is
an authored input until separately verified. APQC fields are hints; calibration
names are requests; regional wording is unverified; template pairs are not
executable evals. Keep all four distinctions visible in status reports.
