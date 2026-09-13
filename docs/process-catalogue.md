# The process catalogue

The catalogue is the authored table that turns an industry into bound work:
value streams, their activities, the function that performs each activity,
the system-of-record class it lives in, its control and its exception.
`worldloom.process_bindings` compiles it against a company (its business
units, countries, operating model and system landscape) into activity
bindings, coverage cells and eval demands. `worldloom.industry` derives a
whole evaluation programme from those bindings.

The file is `src/worldloom/_data/process-catalogue/catalogue.json`. It is
versioned data, edited by hand and checked by tests. It is not a mirror of
an upload: the parity ledgers that once pinned it to a supplied archive are
gone, and so is the second compiler that read the same file.

## What a row says

Each activity is a nine-column row:

| Column | Meaning | Checked against |
| --- | --- | --- |
| `id` | stable key (`o2c.07`) | unique across the catalogue |
| `name` | what the step is called in this stream | free text |
| `pcf_id` | the APQC process the step belongs to | the stream's framework (`worldloom.pcf`) |
| `function` | the business function that performs it | `worldloom.functions` |
| `sor_class` | where its record lives | `sor_classes` in the same file |
| `type` | capture, approve, execute, reconcile, notify, escalate, decide, report | `channel_priors` |
| `control` | the control the step is subject to | free text, not an executable predicate |
| `exception` | the exception the step raises | free text |
| `tags` | regional variant tags | `variant_tags` |

`pcf_id` is APQC's stable identifier, never the hierarchy index. Universal
streams resolve in the cross-industry framework. Each industry overlay names
its framework in `pcf_framework` (banking, retail, utilities and so on);
overlays for industries APQC publishes no framework for (telecom, logistics,
manufacturing, technology) resolve in the cross-industry one. A compiled
binding carries the resolved `pcf_hierarchy_id`, `pcf_name` and
`pcf_framework` next to the id, so a row says which process it is in the
words of the framework.

Several activities may share one process. The catalogue is finer than the
PCF where a stream needs it: `Create purchase order`, `Approve purchase
order` and `Send PO to vendor` all sit under 4.2.3.4 `Create/Distribute
purchase orders`. That is a fact about the two granularities, not an error.

Two streams have no process of their own in their framework and say so in
their `note`: the property and casualty framework has no reserving process,
so `reserve_to_report` anchors to financial forecasting and reporting; the
city government framework models grants from the applicant's side, so
`apply_to_grant` anchors to eligibility verification and certificate
issuance.

## Compile

```python
from worldloom.process_bindings import compile_company, default_company

compiled = compile_company(default_company("retail"))
row = compiled.select(activity_id="o2c.07")[0]
row.pcf_id, row.pcf_hierarchy_id, row.pcf_name   # "10795", "9.2.2.2", "Generate customer billing data"
```

```bash
python -m worldloom.process_bindings --all --out compiled-all
python -m worldloom.process_bindings --industry retail --out retail
python -m worldloom.process_bindings --verify retail/company-000
```

An export is replayed against the installed catalogue when verified; a
manifest hash alone does not legitimise it.

## Check

`tests/test_process_bindings.py` resolves every `pcf_id` in its framework
and checks the compiled name against the framework's. `python
tools/check_catalogue_pcf.py` prints the same join as a table, with the
function the process belongs to in `worldloom.functions` beside the function
the row names, so a row whose performer differs from the process owner is
visible.

## Refresh the frameworks

See [Reference data](reference-data.md) for the PCF and O*NET ingests. A new
PCF release keeps the ids, so the catalogue does not change when the
frameworks are refreshed; a row whose id a release retires fails the test
and names itself.
