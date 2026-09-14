---
name: worldloom-process-catalogue
description: Read and extend the process catalogue: value streams and activities keyed by APQC process id, compiled into company activity bindings and carried into the process authoring cascade.
tags: [worldloom, process, catalogue, apqc, episodes]
---

# The process catalogue

Read `docs/process-catalogue.md` and `docs/reference-data.md`. Use this when an
industry needs process, owner, system, regional and channel context rather than
a hand-written name list.

1. Compile `compile_company(default_company(industry))` from
   `worldloom.process_bindings`. Every row carries `pcf_id`, `pcf_hierarchy_id`,
   `pcf_name` and `pcf_framework`: the APQC process the activity belongs to,
   resolved in the framework the industry names. Inspect `compiled.coverage`
   and `compiled.findings`. For a real company, supply `CompanySpec`; narrow
   streams, country scopes and owner overrides explicitly.
2. Open `worldloom.process.open_from_catalogue(compiled, stream, engine=..., lob=...)`.
   Both engine and LOB must exist. Read `process.next_stage(session)`; the
   `process_catalogue` context is the source for activity names, processes,
   controls, exceptions and bindings. Propose steps and kinds, accept through
   the existing lint, then propose slots and resolve. Never bypass a refusal.
3. Only a resolved, validated EpisodeSpec can drive an episode. The bindings
   alone are not an execution trace.

To add or change an activity, edit `src/worldloom/_data/process-catalogue/catalogue.json`
and give the row the `pcf_id` of its process, looked up with `worldloom.pcf`
(`cross.at("9.2.2").pcf_id`), never the hierarchy index. Then run:

```bash
python tools/check_catalogue_pcf.py --strict
pytest -q tests/test_process_bindings.py
```

The join tool prints the process each row resolves to and the function that
owns it beside the function the row names. Controls stay prose, not executable
predicates; calibration names are requests, not measurements; regional wording
is unverified. Keep those distinctions visible in status reports.
