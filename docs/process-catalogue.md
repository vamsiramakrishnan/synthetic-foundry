# Compile company processes from industry factors

This guide uses `worldloom.process_planning`. The existing `worldloom.process_catalogue` API remains a source-reference importer: it reproduces uploaded rows and their original status labels. Those labels do not prove that calibration was applied. Use the planning API below for authoring, diagnostics and operational coverage.

The supplied catalogue now runs as a Worldloom library component. It contains
16 universal value streams and 22 industry-specific streams: 269 authored
activity definitions across 12 industry overlays. Fifteen regional dictionaries
provide source wording. None is presented as a verified regulatory rule.

The inputs are `catalogue.json`, `compile_processes.py`, `all-12-industries.zip`,
`coverage.csv` and `VOCABULARY.md`. Their SHA-256 digests and the archive's
per-company structural digests are in
`src/worldloom/_data/processes/intake.json`. The original catalogue bytes are
preserved, compressed, in `catalogue.json.gz`. The compiler's default landscapes
and organisations were read as Python literals; the import tool never executes
uploaded Python. The supplied design is retained in
[the input document](design/vocabulary-input.md), with its claims marked as
unverified rather than adopted as implementation status.

## Compile and replay

From an installed package, including outside a repository checkout:

```bash
python -m worldloom.process_planning --all --out compiled-all
python -m worldloom.process_planning --industry retail --seed 8128 --out retail-plan
python -m worldloom.process_planning --spec company.json --out company-plan
python -m worldloom.process_planning --industry retail --core-only --out retail-core
python -m worldloom.process_planning --replay retail-plan/default-retail.plan.json --out retail-replayed
```

`tools/compile_process_plans.py` is the compatibility entry point for the supplied
script's `--spec`, `--all`, `--catalogue` and `--out` workflow. The catalogue no
longer has to be in the working directory. `--spec`, `--industry`, `--all` and
`--replay` are mutually exclusive. A replay uses its pinned seed, catalogue and
stream selection. Use `--spec` for an intentional change.

Exports contain activity JSONL, authored lexicon JSONL, the company spec with its
resolved landscape, a pinned catalogue snapshot, coverage JSON/CSV, diagnostics,
a licence/provenance ledger and a SHA-256 manifest. The manifest is written last.
Nonempty destinations are refused; a smaller rerun cannot leave stale companies
masquerading as current output. Replay checks the plan digest and the catalogue's
semantic digest before compiling.

The library API returns values. It does not write until export is requested:

```python
from worldloom.process_planning import (
    compile_company, default_company, export_compilations, to_lexicon,
)

plan = compile_company(default_company("banking", seed=8128))
activities = plan.activities
vocabulary = to_lexicon(plan)
export_compilations([plan], "bank-process-plan")
```

`CompanyProcessSpec` accepts `name`, `industry`, `operating_model`, `countries`,
`bus`, `landscape`, `seed`, optional `streams` and optional `owner_overrides`.
Each business unit has `name`, `archetype` and an optional country scope. A scope
must be a nonempty subset of the company's countries. Owner overrides map a
function to named units. Unknown industries, countries, functions, duplicate
units and malformed nine-column activity rows are refused.

Default selection retains the supplied `all_universal` policy. It does not
silently remove manufacturing activities from a banking plan or invent a
replacement support taxonomy. Use `streams` or `--core-only` to narrow it.

## What reaches the authoring harness

```text
supplied factors + company spec
               |
               v
       compile_company()
               |
   bound activities, diagnostics, source fingerprint
               |
               v
  process.open_from_catalogue()
               |
        next_stage() brief
               |
    propose -> lint -> accept -> resolve
               |
        existing EpisodeSpec
```

This is connected to the existing process authoring cascade, not a second
simulator:

```python
from worldloom import process
from worldloom.process_planning import compile_company, default_company

plan = compile_company(default_company("retail"))
session = process.open_from_catalogue(
    plan, "hire_to_retire", engine="retail", lob="hr",
)
brief = process.next_stage(session)
context = brief.context["process_catalogue"]
```

The brief carries activity IDs and wording, owner/country bindings, system
products and object metadata, controls, exceptions, channel probabilities,
regional source wording and the original evaluation templates. Context survives
accepted steps and slots. Mutating a returned brief does not mutate its session.
Ordinary sessions receive no extra context and retain their existing behaviour.

The caller must name an installed engine and LOB. Twelve planning overlays do
not mean twelve implemented simulation engines. A harness still proposes event
semantics, fact kinds, invariants, role slots and executable controls. Existing
lint and resolution gates still accept or refuse those proposals. Activity
ordering is not treated as an observed transition graph. No source prose is
turned into an executable approval condition by assertion.

`authoring_context(plan, stream)` provides the same bounded input directly. It
refuses more than 1,000 bound instances by default instead of silently truncating
context. Narrow the spec before opening a very large process session.

## Evidence boundaries

**APQC references stay hints.** Every instance has `apqc_hint` and
`apqc_verified: false`. Authored concepts are industry-scoped; multiple activities
carrying `5.x` do not collapse into one canonical APQC concept. A numeric hint is
not assumed verified either.

**Calibration requests stay requests.** The supplied compiler marked 63
industry-stream cells `corpus_calibrated` whenever their `calibrate` list was
nonempty. The new output separates `calibration_requested` and
`calibration_applied`. Applied calibration is empty for these inputs. Existing
BPI travel-permit priors elsewhere in Worldloom are not applied indiscriminately
to unrelated procurement, lending or incident processes.

**Templates are not executed evaluations.** The 6,975 bound instances have
55,800 activity-template pairs. Those are candidate authoring demands, not
55,800 executable evaluations, answer keys or reference-execution proofs.
`executable_evals` is explicitly zero in this planning export.

**Regional text stays authored and unverified.** Tax rates, mandate dates,
privacy labels, payment rails and product-specific details are retained as
supplied. They were not revalidated during this integration. The source note,
provenance ledger and each instance's evidence flags make this boundary visible.

**Attribution is not a licence grant.** The export records the user-supplied
source, fingerprints and the absence of a separate licence declaration. It does
not relabel these files as official APQC/IBM, ESCO, Jira, BPI or EDGAR downloads.
Review applicable third-party terms before distributing a pack as a licensed
reference dataset.

## Binding and sampling behaviour

Ownership follows the selected centralised, federated or decentralised rules.
The original fallback order is retained for compatibility, but every fallback
is now recorded on its activity and in diagnostics. Explicit country scopes
prevent a unit being instantiated outside its footprint. An override with no
eligible owner produces an `unbound_owner` error, not an implicit substitute.

System availability and object knowledge are separate. A known product with no
object metadata receives a diagnostic. Unknown products and missing schemas are
errors. `Minutes` uses an explicitly reported `Wiki` schema alias. `portal` is
not silently treated as a verified PEPPOL business application. Process objects
and a product's possible object types are carried separately.

Channel probabilities are independent Bernoulli probabilities, not a categorical
distribution. They need not sum to one. Each draw derives from the seed, stable
instance identity and channel name. Adding an unrelated activity, changing
stream iteration order or adding another channel does not reshuffle existing
channel draws. Probability-one channels always appear. An activity can have no
selected channel when the authored priors permit that.

Compilation defaults to a 100,000-instance budget. Unknown explicit streams are
refused. `strict=True` or `--strict` rejects error diagnostics. Warnings remain
visible; they are not converted into fabricated schema or owner evidence.

## Reproduced source coverage

The uploaded archive contains exactly 12 JSONL files. Every supplied activity,
control, exception, owner, country, system product, regional variant and template
reference is protected by an independent structural digest. Channel selections
and schema enrichment intentionally differ from the supplied compiler.

| Industry | Distinct activities | Bound instances | Defined streams |
|---|---:|---:|---:|
| Banking | 153 | 789 | 19 |
| Insurance | 151 | 564 | 19 |
| Retail | 146 | 362 | 18 |
| Consumer products | 133 | 724 | 16 |
| Telecom | 151 | 209 | 19 |
| Utilities | 145 | 177 | 18 |
| Life sciences | 133 | 543 | 16 |
| Logistics | 144 | 1,472 | 18 |
| Healthcare | 144 | 180 | 18 |
| Manufacturing | 138 | 747 | 17 |
| Public sector | 148 | 148 | 19 |
| Technology SaaS | 146 | 1,060 | 18 |
| **Total** | n/a | **6,975** | **215** |

Utilities declares `usage_to_bill` as a core stream but provides no definition.
The supplied compiler omitted it. Coverage now adds a 216th cell with status
`missing` and zero instances. It does not import the telecom implementation.
Consumer products and life sciences have no industry-specific activity overrides
in these inputs; their coverage remains authored universal structure.

## Refresh and test

```bash
python tools/import_process_plans.py --inputs supplied-files --out src/worldloom/_data/processes
pytest -q tests/test_process_planning.py tests/test_process.py tests/test_lexicon.py tests/test_determinism_hygiene.py
```

The intake tool validates archive filenames, duplicate entries, size limits and
coverage consistency. It reads compiler constants with `ast.literal_eval` and
never imports or executes the supplied compiler. It records both raw source
checksums and structural checksums for the archived outputs.

This integration does not finish the earlier external-data acquisition task.
Official PCF workbooks, full multilingual ESCO records, anonymised Jira
measurements and filing-derived segment labels remain separate evidence inputs.
