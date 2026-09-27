---
name: worldloom-interview
description: Build a whole Worldloom world from one interview, covering the company, its lines of business, employees and their levels, each LOB's processes and the systems every step touches, the documents each stage files, how the company changes over time, and what each level of employee would ask an agent to do; then build, narrate, render, and generate eval cases whose gold DAGs come from the interviewed processes, with per-node provenance. Use when asked for a complete interviewed world, for evals derived from a company rather than templates, or to be the interviewee yourself.
metadata: {tags: [worldloom, interview, authoring, evals, levels, provenance, refusal-loop]}
---

# One interview, the whole world

`worldloom interview` asks one question at a time, in order: `company`,
`lobs`, `employees`, `processes:<lob>` for each LOB, `documents`, `timeline`,
`evals`. Each answer is refused with every finding until it lints clean
against the seam it feeds, then the next question exists. The accepted answers
assemble into one company pack plus a resolution, and `interview build` turns
them into a narrated, rendered, validated corpus and one eval case set per
level.

```bash
worldloom interview run ./interview --script examples/interviews/kestrel-vale.json
worldloom interview status ./interview
worldloom interview build ./interview ./out
worldloom interview measure ./out
```

A live interviewee is a harness: `worldloom interview run ./interview --harness <name>`
or `--exec ./adapter`. An interrupted interview resumes: run the same command on
the same directory.

## Be the interviewee yourself

```bash
worldloom interview next ./interview -o request.json
# write reply.json: {"request_id": ..., "answer": {...}}
worldloom interview answer ./interview --reply reply.json
```

Answer only from the request's `context`. A refusal lists every finding; fix
all of them and resubmit the next request (it carries your draft and the
findings). Never answer around a refusal by weakening what the company is.

## Read next

- `references/layers.md`: what each question asks, the answer's shape, and
  what refuses it. Load before answering the first request.
- `references/evals.md`: the level contract, how an intent becomes a DAG,
  provenance, the per-level case sets and the reference proof. Load before the
  `evals` question or before reading a generated case.
- `references/measuring.md`: what `interview measure` reports and how to
  check determinism and resumability. Load when reporting a built world.
- `docs/interview-to-world.md`: the gap analysis and the pipeline in full.
