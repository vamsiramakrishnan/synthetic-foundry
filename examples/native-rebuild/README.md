# Native rebuild evidence pilot

This recorded offline pilot passes the native promotion preflight for all four
operations across DOCX, PPTX, and XLSX. It establishes reference solvability and
independent evidence support. It does not measure a target model or demonstrate
a model improvement.

The source is eighteen deterministic operational cases: six supplier invoice
reconciliations, six customer refund settlements, and six inventory replenishment
exceptions. The recipe checks arithmetic, canonical derivations, temporal
revisions, authored tables, and accountable actors. Only these case artifacts
enter the benchmark; the underlying retail world's background facts are excluded.

## Reproduce

From the repository root, with the project's DOCX, PPTX, and XLSX dependencies
installed:

```bash
python examples/native-rebuild/pilot.py \
  --output /tmp/worldloom-native-rebuild-pilot \
  --report /tmp/worldloom-native-rebuild-report.json
python examples/native-rebuild/pilot.py \
  --output /tmp/worldloom-native-rebuild-pilot \
  --report /tmp/worldloom-native-rebuild-replayed-report.json \
  --resume
```

The first command builds actual files and separated training/held-out packages.
The second verifies the same source recipe and rerenders each native source plan
before accepting the existing packages. Changed source, workload, role, or file
bytes are refused. A failed preflight writes its findings and exits with status 2.
No target harness, language model, candidate proposer, or network service is used.

The input contracts are [demand.json](demand.json),
[workload-plan.json](workload-plan.json), [requirements.json](requirements.json),
and [experiment.json](experiment.json). The workload ceiling was fixed at 768
tasks per split before generation. The twelve operation/format intersections are
explicit requirements. Read/analyze formats refer to consumed inputs;
update/create formats refer to produced outputs.

## Recorded result

[report.json](report.json) contains the complete assessment, source episode
receipts, per-file byte counts and SHA-256 checksums, canonical source digest,
grader source/dependency identity, and actual fresh cohort measurements.
An exact resume reproduced the complete report byte-for-byte and revalidated
the rendered native source bytes.

| Measurement | Training | Held out |
|---|---:|---:|
| Reference-qualified tasks | 575 | 768 |
| Independent canonical families | 3 | 15 |
| Actual native files | 9 | 45 |
| Actual source bytes | 279,122 | 1,395,518 |
| Families per business process | 1 | 5 |

The 54 files use 582 distinct scoped canonical facts. There are zero shared
canonical ancestors between episodes, zero train/held-out evidence overlaps, and
zero background facts in the measured source lineage. Format copies remain in
the same independent family.

Every required cell has three independent training families and fifteen
independent held-out families:

| Required cell | Training tasks | Held-out tasks | Independent families, train/held out |
|---|---:|---:|---:|
| Read DOCX | 137 | 60 | 3 / 15 |
| Read PPTX | 137 | 60 | 3 / 15 |
| Read XLSX | 124 | 121 | 3 / 15 |
| Analyze DOCX | 38 | 90 | 3 / 15 |
| Analyze PPTX | 38 | 90 | 3 / 15 |
| Analyze XLSX | 32 | 61 | 3 / 15 |
| Update DOCX | 3 | 15 | 3 / 15 |
| Update PPTX | 3 | 15 | 3 / 15 |
| Update XLSX | 3 | 15 | 3 / 15 |
| Create DOCX | 9 | 45 | 3 / 15 |
| Create PPTX | 9 | 39 | 3 / 15 |
| Create XLSX | 42 | 157 | 3 / 15 |

The strict experiment declares three fresh trials, at least five independent
units per trial, and at least two paired repeats per side. The actual shared
qualification allocator produces:

| Fresh tranche | Tasks | Independent units in every required cell |
|---|---:|---:|
| 1 | 254 | 5 |
| 2 | 257 | 5 |
| 3 | 257 | 5 |

Arithmetic includes grounded differences, ratios, and authored SUM reconciliation.
The training tasks contain 66 difference, 33 ratio, and 42 sum assertions; held-out
tasks contain 201 difference, 80 ratio, and 81 sum assertions. An assertion count
is descriptive and never adds independent evidence.

## Limits and findings

The held-out selection reaches the predeclared 768-task ceiling and omits
additional candidate questions. All required cells and fresh cohorts still meet
their evidence floors. The training selection contains 575 tasks and is not
truncated. Neither planner reports source or selector findings.

The assessment records two nonblocking findings: operation task counts are
unequal, and multiple tasks share evidence. The latter is expected: 1,343 tasks
provide eighteen independent families, rather than 1,343 independent observations.

All three business processes occur in training and held out. Training contains
two template variants and held out contains three; these dimensions are
descriptive and are not separate predeclared statistical claims. Each actual
fresh tranche contains one or two families per process, not five per process.

This pilot uses artifact-local tasks. It does not establish cross-artifact
workflow performance, full visual layout equivalence, calibrated human realism,
or improvement by a live target model. `promotion_ready` means the declared
experiment has enough validated support to run; no candidate was proposed or
promoted, and no held-out target calls were consumed.

## Separate executable workflow pilot

[workflow_pilot.py](workflow_pilot.py), [workflow_worker.py](workflow_worker.py),
and [workflow-report.json](workflow-report.json) record a separate subprocess
adapter check:

```bash
python examples/native-rebuild/workflow_pilot.py /tmp/worldloom-native-workflow-pilot
python examples/native-rebuild/workflow_pilot.py /tmp/worldloom-native-workflow-pilot --resume
```

All five actual steps passed: read, sum analysis, update, verification of the
changed bytes, and creation. The script stages public inputs only and verifies
the exact resumed report. Its source contains three episodes, six DOCX/XLSX
files, and 192 canonical tasks; the workflow selects one case.

The worker deliberately supports DOCX and sum calculations only. Its creation
step uses canonical source bytes because write contracts against modified inputs
are not supported. This demonstrates executable byte handoffs and grading for a
deterministic adapter; it is not an autonomous model or trajectory score.
