# Reference data

Worldloom ships three tables that say what a company does, who does it and
where the records live. Two are published taxonomies ingested as they are.
The third is a crosswalk between them, built by a tool that resolves every
id against the first two and copies every name from them.

| Table | Source | Licence | Data | Reader |
| --- | --- | --- | --- | --- |
| Processes | APQC Process Classification Framework, cross-industry 7.4 and seventeen industry frameworks | APQC notice, embedded in every file | `src/worldloom/_data/pcf/<framework>@<version>.json.gz` | `worldloom.pcf` |
| Occupations | O*NET 31.0 database (USDOL/ETA) | CC BY 4.0, credit line embedded | `src/worldloom/_data/onet/occupations@31.0.json.gz` | `worldloom.onet` |
| Functions | Built from the two above and the catalogue's system classes | Derived | `src/worldloom/_data/functions/functions@1.json` | `worldloom.functions` |

## Processes: the APQC PCF

The PCF is a hierarchy of what an organisation does. Level 1 is a category
(`9.0 Manage Financial Resources`), level 2 a process group (`9.2 Perform
revenue accounting`), level 3 a process (`9.2.2 Invoice customer`), levels 4
and 5 activities and tasks. Every element has two ids. The `pcf_id` is
APQC's stable identifier and survives releases and industry variants:
`Invoice customer` is 10743 in the cross-industry framework and in retail's.
The `hierarchy_id` is the human index and moves between releases. Anything
this repository records against a process records the `pcf_id`.

```python
from worldloom import pcf

cross = pcf.cross_industry()
invoice = cross.at("9.2.2")            # by index, in this release
assert invoice.pcf_id == "10743"
cross.element("10743").description     # APQC's definition
cross.metrics_for("10743")             # APQC's benchmarking measures
retail = pcf.load("retail")            # newest shipped retail framework
pcf.shared(cross, retail)              # ids both frameworks carry
```

`tools/ingest_apqc.py` reads the workbooks APQC publishes and writes one
file per framework. It refuses a workbook whose copyright notice it cannot
find, because APQC's licence permits copies on the condition that the notice
travels with them. `provenance.json` names each source file, its checksum,
and the files that were skipped.

## Occupations: O*NET

O*NET is the U.S. Department of Labor's occupation database. For each of
its 1,016 occupations the shipped file carries the description, the job
zone, the titles incumbents report and the alternate titles employers use,
the task statements with the detailed work activities they map to, and the
software used with its category.

```python
from worldloom import onet

db = onet.load()
clerk = db.occupation("43-3031.00")    # Bookkeeping, Accounting, and Auditing Clerks
clerk.titles[:5]                       # real titles: Account Clerk, Accounting Assistant, ...
clerk.core_tasks[0].text               # a task statement
clerk.software_in("Accounting software")
db.search("accounts payable")          # occupations known by that title
```

Codes are O*NET-SOC codes. The first two digits are the SOC major group,
`.00` is the SOC occupation and another suffix is an O*NET specialty under
it. `tools/ingest_onet.py` reads the CSV archive O*NET publishes and writes
the file with the credit line the licence asks for.

## Functions: the crosswalk

A function is what a company organises people by. The table assigns every
level-3 process of the cross-industry PCF to exactly one of 42 functions,
seats each function with O*NET occupations in three tiers, and names the
system-of-record classes it works in.

| Tier | Meaning | Example, accounts payable |
| --- | --- | --- |
| manager | runs the function | First-Line Supervisors of Office and Administrative Support Workers |
| professional | judgement work: analysis, decisions, approvals | Accountants and Auditors |
| support | transactional work: capture, posting, filing | Bookkeeping clerks; Billing and Posting Clerks |

```python
from worldloom import functions

table = functions.load()
table.for_process("10756").key         # "ap": Process accounts payable (AP)
table.function("ap").tier("support")   # the seats, with O*NET titles
table.function("ap").sor_classes       # ("ERP-FI", "P2P-suite", "e-invoicing")
table.for_occupation("13-2011.00")     # every function that seats accountants
```

`tools/build_functions.py` holds the three authored tables: process group
to function (with per-process overrides), function to occupation codes, and
function to system classes. Everything else in the output is resolved from
the data. The build stops on an unknown id, an unassigned process group, a
process assigned twice, or a function with no manager, no process or no
system. `tests/test_functions.py` checks the shipped file against the
shipped sources the same way.

## Refresh

```bash
python tools/ingest_apqc.py --input ./apqc_pcf --out src/worldloom/_data/pcf
python tools/ingest_onet.py --input ./db_31_0_csv.zip --out src/worldloom/_data/onet
python tools/build_functions.py --out src/worldloom/_data/functions
pytest -q tests/test_pcf.py tests/test_onet.py tests/test_functions.py
```

The raw workbooks and archives are inputs, not repository assets. Each
ingest is byte-deterministic: the same input yields the same file.
