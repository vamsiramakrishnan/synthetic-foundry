---
name: worldloom-process-bindings
description: Compile the supplied industry catalogue into company activity bindings, inspect coverage and drive process authoring without treating authored hints as measurements.
---

# Process catalogue

Use this before authoring a company's processes or constructing process-specific
eval demands. Read `docs/process-bindings.md` for SDK and evidence contracts.

Compile through `python -m worldloom.process_bindings --industry retail --out ./processes`
or `compile_company(default_company("retail"))`. Use `--core-only` to restrict the
universal backbone to declared core processes. Read findings before proposing
new content. Preserve unknown systems, fallback owners and missing streams as
gaps until an explicit company specification or source definition resolves them.

Call `authoring_brief(compiled, stream="forecast_to_replenish")` for a bounded
`steps` brief. Use the existing process acceptance and resolution gates to admit
executable steps. Catalogue control prose is not executable policy. Never make
a failed binding pass by inventing an object schema or reusing another industry's
similarly named process without a reviewed mapping.

The read-only `tool_surface(compiled)` exposes `process_catalogue/activity_binding`
through the shared predicate evaluator. `demands(compiled)` emits authoring slots;
only `bound_structural` ownership demands have an oracle. Other tasks need runtime
facts, policy predicates or workflow transitions. Do not count template slots as
executed evals, fitted priors, or generated business records.

The source is `authored_prior`. APQC codes are `unverified_hint`. Calibration
names are targets, not measurements. The input license is `NOASSERTION` and needs
review before redistribution. Keep the original source and provenance ledger.

Run `pytest -q tests/test_process_bindings.py` and verify exports with
`python -m worldloom.process_bindings --verify ./processes/company-000`.
