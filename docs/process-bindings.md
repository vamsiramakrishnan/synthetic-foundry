# Compile a company's process catalogue

Use the supplied industry catalogue to decide which activities exist, who owns
them, which systems record them, and which surfaces may carry their evidence.
The compiler produces structure and authoring inputs. It does not invent loan
histories, claim payments, approval decisions, or statistical calibration.

This is an opt-in SDK. Existing World recipes and the retail/banking operational
simulators are unchanged.

## What ships

The original `catalogue.json` is unchanged. It defines 16 universal value
streams, 12 industry overlays, 30 function families, 3 operating models,
28 system classes, 15 regional variants, and 8 evaluation templates.
The default companies and system landscape are extracted from the supplied
compiler as data, without executing that script.

`_data/process-catalogue/bindings-provenance.json` records SHA-256 hashes and sizes for all
five uploads. It also records the raw and canonical semantic digest for each of
the 12 JSONL files in `all-12-industries.zip`. The expanded archive is a parity
baseline, not a second runtime database. The original coverage CSV and compiler
are retained beside the catalogue; the compiler is stored as inert `.py.txt`.

The supplied [vocabulary proposal](sources/VOCABULARY.md) is retained verbatim as
source material. Its descriptions of harvested datasets, licenses, vendor
objects and regional rules are not a claim that this integration verified them.
The catalogue itself says its APQC numbers are hints and its regional/product
claims need verification. They remain authored priors here. `NOASSERTION` in the
license ledger means no license was established by the upload; it is not an
open-data license or a redistribution clearance.

## Compile and verify

From an installed package, or with `PYTHONPATH=src` from a checkout:

```bash
python -m worldloom.process_bindings --all --out ./compiled-processes
python -m worldloom.process_bindings --verify ./compiled-processes/company-000
python -m worldloom.process_bindings --industry retail --core-only --out ./retail-core
```

The checkout wrapper accepts the same arguments:

```bash
python tools/compile_process_bindings.py --all --out ./compiled-processes
```

`--spec company.json` selects an explicit company instead of a default.
`--catalogue catalogue.json` selects an alternate source. `--max-instances`
bounds each company's Cartesian expansion before any output is written.
`--strict` refuses unresolved core streams, ambiguous central ownership and
unknown system bindings. Descriptive compilation still exports those findings;
it does not turn missing definitions into an invented process.

Output directories are numbered, not constructed from company names. Existing
output directories are never overwritten. Each company directory contains:

```text
compilation.json      frozen source-derived structure and commitments
activities.jsonl      owner/country/system bindings
lexicon.jsonl         one concept per activity, not per Cartesian copy
demands.jsonl         authoring slots and structural ownership expectations
coverage.csv          defined, missing and uncalibrated coverage
findings.jsonl        binding and evidence diagnostics
licenses.json         attribution and unresolved licensing status
summary.json          separate structure, demand and evidence counts
manifest.json         hashes for every projected file
```

Verification checks hashes, recompiles the original specification against the
installed or explicitly supplied catalogue, and byte-compares every projection.
Changing a demand and updating its manifest hash is not sufficient to pass.
Digests commit to the catalogue, specification and `core_only` setting. They
are reproducibility checks, not cryptographic signatures of source truth.

## Python SDK

```python
from worldloom.process_bindings import (
    compile_company, default_company, demands, summary, verify_ownership,
)

compiled = compile_company(default_company("retail"))
replenishment = compiled.select(stream="forecast_to_replenish", country="AU")
print(summary(compiled))

ownership = next(d for d in demands(compiled) if d.status == "bound_structural")
assert verify_ownership(compiled, ownership)
```

`CompanySpec` accepts the source fields `name`, `industry`, `operating_model`,
`countries`, `bus`, and optional `landscape`. Each BU has a name and archetype.
An optional BU `countries` tuple limits its footprint to a subset of the
company's countries. With no BU footprint, the source's full company-country
expansion is preserved. Duplicate names and countries are rejected.

BU declaration order is meaningful only for the source compiler's last-resort
owner fallback. It is preserved. Fallback ownership is marked `fallback`, not
silently upgraded to exact ownership. Multiple central or shared-service owners
are marked ambiguous. All exported rows are sorted independently of map order.

## Use the existing Worldloom contracts

```python
from worldloom.predicates import Predicate
from worldloom.process_bindings import authoring_brief, lexicon_records, tool_surface

surface = tool_surface(compiled).fork()
result = surface.search(
    "process_catalogue", "activity_binding",
    predicate=Predicate.equalities(
        {"stream": "forecast_to_replenish", "country": "AU"},
        entity="activity_binding",
    ),
)
brief = authoring_brief(compiled, stream="forecast_to_replenish")
activities = lexicon_records(compiled)
```

The connector advertises search and read only. It is a structural register,
not a ServiceNow incident table or a Jira issue history. Both SDK selection and
tool searches use Worldloom's shared predicate evaluator.

The `steps` brief feeds the process-authoring seam. Its records include controls,
exceptions, source hints and binding findings. The writer must still author
executable steps, resolve references and pass the existing `process.accept`
and `process.resolve` gates. Free-text controls are not boolean predicates.

Lexicon records use source-and-industry-scoped activity IDs. Two activities
sharing a broad `5.x` APQC hint do not become one canonical concept. Weights
are uniform authored priors over distinct activities, not source-measured
frequencies. `sample_channels(binding, seed=8128)` uses stable per-binding and
per-channel RNG streams. These are independent presence probabilities; they
must not be normalized into a one-channel categorical distribution.

## Measured source parity

The following counts are from recompiling the supplied defaults and comparing
canonical records to every uploaded JSONL member. Sorting object/channel lists
is the only canonicalization within a record. No labels, owners, systems,
controls, variants or activity IDs are replaced.

| Industry | Activities | Bindings | Defined streams |
| --- | ---: | ---: | ---: |
| Banking | 153 | 789 | 19 |
| Consumer products | 133 | 724 | 16 |
| Healthcare | 144 | 180 | 18 |
| Insurance | 151 | 564 | 19 |
| Life sciences | 133 | 543 | 16 |
| Logistics | 144 | 1,472 | 18 |
| Manufacturing | 138 | 747 | 17 |
| Public sector | 148 | 148 | 19 |
| Retail | 146 | 362 | 18 |
| Technology/SaaS | 146 | 1,060 | 18 |
| Telecom | 151 | 209 | 19 |
| Utilities | 145 | 177 | 18 |

Total: **6,975 bindings**. Eight templates yield **55,800 authoring slots**.
That is not 55,800 executed evaluations. Only exact structural ownership
bindings receive a local oracle. Queue, reconciliation, evidence-chase, belief,
action, policy and handoff templates still require runtime facts and further
construction. Even a template with no unresolved text slots can require runtime
state. The demand status makes this distinction explicit.

## Gaps that must stay visible

The uploaded coverage has 215 industry-stream cells. Sixty-three are labelled
`corpus_calibrated` merely because the stream lists a source name. This compiler
preserves the targets but marks them unresolved. None is claimed calibrated.
Loading an unrelated BPI log into the package is not a fit for these processes.

Utilities names `usage_to_bill` as a core stream but defines it only in the
telecom overlay. The audited matrix includes a 216th cell with
`missing_definition` and zero activities. There is no implicit cross-industry
inheritance. Author a utility definition or an explicit, reviewed mapping.

`Minutes` and `portal` are used as system classes but have no class definitions.
Several P2P-suite products contain no object metadata. Product names alone do
not satisfy a system-object binding. The defaults also need explicit ownership
in places where the original compiler fell back to a different BU. The strict
readiness gate is intentionally not green for the complete default catalogues.
These findings do not prevent reading the valid descriptive bindings.

Default compilation includes every universal stream, as the source does.
`core_only=True` narrows the selection to declared core and industry-specific
streams. Choosing which support functions actually operate in a particular
company remains an explicit company-authoring decision.

The uploaded files do not contain authoritative APQC workbooks, ESCO releases,
an anonymised Jira dump, BPI raw logs or EDGAR filings. This integration neither
substitutes for those sources nor claims they were downloaded.
