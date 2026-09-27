---
title: Interview Evals
description: The level contract, how an eval intent becomes an enterprise DAG, per-node provenance, and the per-level case sets.
read-when: Before answering the evals question, or when reading or grading a case an interview generated.
tags: [worldloom, interview, evals, dag, provenance, levels]
---

# Intents, levels, DAGs

An intent is what one employee would ask an agent to do. Its `asker` holds its
`level`.

A read is either a **step read** `{"system", "process", "step", "period"}`
(the records a process step left on a system it declared) or a **document
read** `{"document", "period", "system", "revised"}` (a document type on a
system it is published on). `period` is `latest`, `first`, `previous`, `all`
or a `YYYY-MM` inside the history. `revised: true` reads only versions that
carry a revision chain. `deliver` is `{"system", "entity", "operation", "format"}`;
an alias entity (Jira `issue`, SharePoint `file`) needs its concrete member as
`format` (`task`, `docx`).

| Level | Contract | Shape |
|---|---|---|
| `ic` | exactly one step read; no branch, no map | `interview_ic_lookup` |
| `manager` | reads on two or more systems; no branch | `interview_manager_fan_in` |
| `director` | a document read, two or more reads, a `branch: {"read", "at_least"}` | `interview_director_conditional` |
| `executive` | three or more reads spanning two or more LOBs, `per_entity: true` | `interview_executive_map` |

Also refused: two reads of one system entity in one intent (a case binds one
fixture per entity; read the other on another system), a read of a step or
system no process declared, and a level whose systems together exceed the tool
catalogue one served case set admits.

## From intent to case

Each intent compiles to a `PlannedEnterpriseQuery` in `enterprise-dag@1`:
predicate-bound searches (`bind="predicate"`, the rule stated in the request),
`for_each` fetches for `per_entity`, `collect` / `project` / `unique`
transforms, and a write with its readback (two conditional writes for a
director). It then takes the same path as every enterprise case:
`materialize_corpus(strict_sources=True)`, `validate_corpus`, `compile_rows`,
`evalrun.cases_from_corpus`. A read that matches no record is refused
(`CaseRefusal`) naming the intent.

## Provenance

`dimensions.interview_provenance` maps every node id to the question behind
it: a step read to `processes:<lob>` with the step and system, a document read
to `documents` with the document and its authoring process, transforms and
writes to `evals` with the intent. `evals/<level>/provenance.jsonl` repeats it
per case with the intent, level and shape.

## Running and proving

`interview build` writes `evals/<level>/` (an enterprise case set per level)
and refuses unless the reference agent passes every case. Grade an agent:

```bash
worldloom evalrun run ./out/evals/manager -o ./runs/manager --agent scripted:trajectories.json
worldloom evalrun compare ./runs/reference ./runs/manager
```
