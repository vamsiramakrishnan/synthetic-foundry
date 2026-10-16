# Native evidence and controlled harness queries

This pilot generates two supplier reconciliation episodes with twelve lines,
Zipf budget allocation, three exception lines each, late decision sections and
time-valid working assessments. It renders eight DOCX/XLSX files, verifies the
workbooks' bytes and formula provenance, then compiles their extracted amounts
into six create/update × empty/partial/stale DAG cases.

From an installed checkout with DOCX/XLSX extras:

```bash
python examples/harness-evidence/pilot.py --out /tmp/worldloom-harness-pilot
worldloom enterprise-evals harness-dags /tmp/worldloom-harness-pilot/records.jsonl --config /tmp/worldloom-harness-pilot/harness-dags.json --out /tmp/worldloom-harness-cli-cases
worldloom evalrun prove /tmp/worldloom-harness-cli-cases
worldloom evalrun run /tmp/worldloom-harness-cli-cases --agent reference -o /tmp/worldloom-harness-cli-run
```

The script refuses a nonempty destination. It writes the canonical corpus,
original native files/manifests, private source projection, ordinary evalrun
case set, separate public tasks and a measurement report. Keep the corpus,
projection and case contracts evaluator-side; give a target only public tasks
and its tool surface. Native source hashes and locators remain visible in the
projected connector content.

Two public-only scripted workers must pass all six cases: one starts with a
correct query, and one refines an insufficient query. Two negative controls
must fail: repeating an unchanged insufficient query, even before producing a
correct result; and writing a wrong total while claiming success.

`measurement.json` records the committed reference result. Reproduce it in a
fresh directory to inspect actual bytes and scores. The four format replicas
do not create more independent evidence: two source families form one cohort,
and its six DAG variants share one family.

This qualifies operations over verified extracted content. It does not measure
binary ingestion, OCR, visual comprehension, live-model improvement or fitted
enterprise realism. Nano Banana integration is documented separately in
[`docs/visual-generation.md`](../../docs/visual-generation.md).
