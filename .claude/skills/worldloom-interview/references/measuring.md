---
title: Measuring an Interviewed World
description: What interview measure reports, and how to check that an interviewed world is deterministic and resumable.
read-when: Reporting a built interviewed world, or checking a change to the interview pipeline.
tags: [worldloom, interview, measurement, determinism]
---

# What the world holds

`worldloom interview measure ./out` prints `measurements.json`, counts only:

- `employees`: people, people by level (the levelled roles), and the engine's
  posts outside the ladder;
- `lobs`, `processes`, `process_steps`, `systems_touched`;
- `records_per_system`, and how many records carry `interview_*` fields;
- `documents`: intents, rendered files, and `by_type_and_level`
  (`<type>@<level of its author>`);
- `revisions`: revision files, records with a revision chain per system;
- `timeline`: periods, events, process-step events, incident periods, org
  changes, policies and their milestone events;
- `cases`: per level, the count, shapes, DAG depth, width, nodes and
  connectors (min and max), conditional and `for_each` nodes, and each case
  set's systems, records and tool count against the admitted catalogue;
- `reference`: the reference agent's passes per level.

A count is not a quality claim: the reference proof says every case is
executable, not that an agent will find it hard.

# Checking determinism and resumability

Build the same interview twice in two processes and compare the trees; they
must be byte-identical:

```bash
worldloom interview run ./a --script examples/interviews/kestrel-vale.json
worldloom interview run ./b --script examples/interviews/kestrel-vale.json --stop-after 3
worldloom interview run ./b --script examples/interviews/kestrel-vale.json
worldloom interview build ./a ./out-a
worldloom interview build ./b ./out-b
```

`./a` and `./b` must match (an interrupted interview resumes to the same
transcript), and so must `./out-a` and `./out-b`.
