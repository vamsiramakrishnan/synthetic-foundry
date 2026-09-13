# Industry X, and the whole evaluation programme it implies

An interview ends with a sentence: "a federated telecom in India, four business
units". Until now everything after that sentence was typed by hand. Somebody
listed the lines of business, decided which processes each one runs, chose who
would ask for what, and wrote `count: 12` on every use case because twelve is a
number. `worldloom industry` derives all of it from the process catalogue the
repository already ships, and every number it prints is a function of that
catalogue and two versioned data files, so the same industry yields the same
programme every time.

```bash
worldloom industry list
worldloom industry programme telecom --describe
worldloom industry programme telecom ./programme
```

The first command names the twelve industries the catalogue knows and each
default company's headline count. The second prints one industry's numbers
without writing anything. The third writes the programme: `programme.json`
(the summary), `lobs.json`, `facts.jsonl`, `requests.jsonl`, `cases.jsonl`,
`use-cases.json` and `coverage.json`. An explicit company (its own units,
countries and operating model) is a `CompanySpec` JSON passed in place of the
industry name.

## What is derived, and from what

**A line of business is a function family the operating model owns.** The
catalogue declares thirty function families (accounts payable, billing, IT
operations, ...) and three operating models saying which family a business
unit, a shared service or a group function owns. `industry.derive_lobs` makes
one `lob.Lob` per family that owns at least one bound activity in the compiled
company: a head, a manager, an analyst and, where the function seats one, a
support role (`billing_head`, `billing_manager`, `billing_analyst`,
`billing_support`), with the head and the manager answerable for the value
streams the family's activities sit in. The titles come from the function
table (see [Reference data](reference-data.md)): a billing line is a Head of
Billing, a Billing Supervisor, a Billing Administrator and a Billing Clerk,
the last three titles O*NET incumbents and employers report, the first
derived and marked as such. Standing is expressed as fact-kind
families, `process.<stream>`, registered from the catalogue's own stream list
so `lob.asks_about`, the plausibility check and the derived facts read one
account. Each LOB is rooted at the chief executive (`industry.ROOT`), which is the
convention `lob.lint_roles` asks for and the shape a Studio project accepts;
`derive_lobs(..., root=None)` gives the headless shape the shipped library
uses. The LOBs lint clean under `lob.lint_lob`.

**A request is a situation with someone in the seat.** `process_bindings.situations`
crosses every bound activity with the verbs that suit its type and the channels
its evidence lands in. `industry.requests` seats each one from the LOB whose
family owns the binding, by activity type (`SEAT_BY_TYPE`): the head is asked
about approvals and decisions, the manager about reconciliations and reports,
the analyst about captures, executions, notifications and escalations. The
asker always has standing, by construction, and `industry.standing_findings`
proves it with the same rule `evals.plausibility` applies to a corpus. The
ground truth is what the catalogue declares and nothing more: `industry.facts`
mints one fact per attribute per binding (owner, system of record, control,
exception) as `process.<stream>.<attribute>`, and a request's expected answer
names them. `Request.to_case` turns a request into an `EvaluationCase` citing
those facts; the `abstain` verb becomes an abstention case, as it does
everywhere else.

**The count is derived, per LOB and per process.** A `ProcessLine` is one LOB
crossed with one value stream: its activities, bindings, situations, reads,
writes, systems, channels and emulated sources. `industry.use_cases` turns
each supported line into a Studio `UseCase` whose `count` is the line's
situations rather than an authored twelve, whose scenario's sources are the
connectors that emulate the line's systems of record and evidence channels,
and whose construction `EvalSpec` requires each source constrained to the
line's LOB, stream and owner so a Foundry run cannot satisfy it with another
line's records. Every scenario is one `apply_scenario_profile` accepts against
the builtin registry as it stands.

## What is emulated, and what is said out loud

`_data/process-catalogue/emulated-systems@2.json` says which connector stands
in for each system of record and which evidence channels have an emulator
(email, ticket, document, report, minutes). Six products have an emulator of
their own (ServiceNow, Jira Service Management, Salesforce, SharePoint,
Confluence, Exchange Online). Every other product the catalogue names, an SAP
ledger, a Workday position, a core banking loan, is stood in for by the `sor`
connector: one system-of-record connector whose entities are the catalogue's
record kinds and whose records are derived from the company's bindings
(`worldloom.sor`, one record per binding, record kind and period, ids in the
product's own pattern, a status from the kind's workflow, the binding's
exception on the records that tripped it). The table and the connector are
built from the catalogue by `tools/build_sor_connector.py`. A channel with
no emulator (chat, a workflow approval, a portal filing) is still reported as
unemulated, and the file is versioned in its name because changing which
connector stands in for a system changes every programme derived from it.

`IndustryProgramme.engine` names the registered domain that builds the
company's world (`retail`, `banking`, `insurance`) and is empty for the nine
industries no engine builds. For those the programme stands on the catalogue
alone: structure, requests, facts and connector use cases, but no fact ledger
or documents of the engine's own. That is the seam the next step fills, not
a limitation hidden behind a retail world dressed as a telecom.

## In the Studio

`worldloom.industry.project(industry, name)` is a `ProjectSpec` for one
company of that industry, and the Studio preset accepts any industry the
catalogue knows (`GET /api/preset?engine=telecom`, or `preset("telecom",
"Ardent Telecom")`): the company document names the industry, the process
structure is the catalogue's default company renamed, the LOBs are the derived
ones for the selected families, and the use cases are every supported line of
those families with the line's own count. `company.resolve` picks the engine:
its own for a retailer, a bank or an insurer, and the retail shape for an
industry no engine builds, with that limitation stated in the project's
`acknowledged_unmet` and the programme it does have named in the sentence.

A project seats every line of business with a supported process line by
default, or the families named in `lobs`. A composed company's name pool is
cut to the people its description mints, and each line adds three or four;
`sdk.Blueprint.lob` re-cuts the pools from the locale to the new count when a
line attaches, so a project of thirty lines builds where four was the
ceiling. The interview request carries the
programme's headline numbers under `programme`, and its instructions tell the
interviewer to derive a use case's count from its process line rather than
write a round number.

The company resolver reads industries the same way. `archetypes.matched`
says whether a description named a registered shape at all, so a retailer is
recognised without a caveat, a description the catalogue knows but no engine
builds ("a federated telecom in India") is reported as exactly that, with
`worldloom industry programme telecom` named as what does exist, and an
unrecognised business is reported as a miss. `industry.industry_of` is the
lookup: the overlay keys, the crosswalk codes (`NAICS 517`), each overlay's
sector framework (`TM Forum eTOM`) and a declared word table
(`INDUSTRY_WORDS`), matched at word boundaries with the longest phrase
winning.

## The shipped industries

Counts for each catalogue's default company, as `worldloom industry list`
prints them. Each is thirty LOBs; the lines are LOB × stream cells with at
least one bound activity; situations are the requests derived.

| Industry | Engine | Lines | Situations | Writes |
| --- | --- | --- | --- | --- |
| banking | banking | 64 | 21,321 | 10,242 |
| consumer_products | | 52 | 19,768 | 9,516 | 9 |
| healthcare | | 58 | 4,931 | 2,362 | 12 |
| insurance | insurance | 63 | 15,294 | 7,356 |
| life_sciences | | 52 | 14,826 | 7,137 | 9 |
| logistics | | 58 | 39,560 | 19,100 | 12 |
| manufacturing | | 55 | 20,388 | 9,801 | 11 |
| public_sector | | 60 | 4,074 | 1,934 | 10 |
| retail | retail | 61 | 9,896 | 4,762 |
| technology_saas | | 58 | 28,944 | 13,804 | 10 |
| telecom | | 62 | 5,550 | 2,677 | 10 |
| utilities | | 58 | 4,794 | 2,325 | 9 |

189,346 requests in all, each seated, each grounded in a declared fact, each
counted where it belongs. `evals.coverage.report` reads a programme's requests
exactly as it reads a corpus's cases (`coverage.Requested` is the shared
shape), and a full programme uses every situation the catalogue offers.

## Python

```python
from worldloom import industry

derived = industry.programme("telecom")
summary = derived.summary            # IndustryProgramme: lobs, lines, counts, unemulated, findings
summary.by_lob()                     # situations per line of business
derived.lobs                         # tuple[lob.Lob, ...], one per owning function family
derived.requests[0].to_case()        # an EvaluationCase citing the derived facts
derived.coverage()                   # CoverageReport against every situation offered
derived.use_cases()                  # tuple[studio.UseCase, ...] with derived counts
derived.export("./programme")

industry.project("telecom", "Ardent Telecom")   # a Studio ProjectSpec, LOBs and use cases derived
industry.industry_of("a federated telecom")     # "telecom"
```

`programme` also accepts a `process_bindings.CompanySpec`, an `engine` for the
LOBs to ride, and an `as_of` for the facts' validity. `derive_lobs`,
`requests`, `facts`, `lines` and `use_cases` are each callable on their own
against a compiled catalogue.
