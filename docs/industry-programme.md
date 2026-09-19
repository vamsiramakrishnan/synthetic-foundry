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

**The capability and the difficulty are read off the rows too.** A use case's
`EvalSpec` used to carry `evidence_reconciliation` at `medium` whatever the
line's activities were. `industry.activity_capability` reads the activity type
(a report is a `search`, a reconcile step is a `reconcile`, the rest act on
evidence) and `industry.activity_difficulty` reads the declared exception path
and the channels the evidence lands in: both make an activity hard, one makes
it medium, neither makes it easy. A line takes the most demanding of its
activities. Where a property is uniform across an industry the output stays
uniform, and `IndustryProgramme.uniformity` says which property and why: every
shipped activity declares an exception path, so no shipped use case is easy.
The request template is written from the same rows, naming the activities,
the owning units, the countries, the stream and the systems of record.

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

## Requests read their answers off the records

A programme derives the company's records in every system its bindings name
(`worldloom.sor`: six periods ending at `sor.ANCHOR_PERIOD`, three records
per binding, record kind and period, ids in the product's own pattern, a
status from the kind's workflow, the exception on one record in four). A
request whose intent rests on a record set, which `evals/intents.json`
declares with `record_set` among its `evidence_kinds` (find the exception,
triage a queue, chase, reconcile, respond to a query), is asked about the
binding's records in the latest period and its expected answer is read off
them by `sor.answer`: the records that tripped the exception for a list, the
open ones in workflow order for a ranked list, the item to chase and its
owner for a message, the count and statuses otherwise. `Request.period`
names the period and `Request.expected_record_ids` the records the answer
cites; `industry export` writes them as `records.jsonl` beside the requests.
A request whose intent rests on the declaration alone (sign off, decide,
review against policy) still answers with the catalogue's declaration. One
request per situation either way, so the counts below are unchanged; what
changes is how many of them have an answer of their own.

## The requests run as evalrun cases

A record request is also an `evalrun` case (`Programme.evalrun_cases`,
`industry.evalrun_cases`): its plan is one search on the `sor` connector per
record kind the binding holds in the request's period, with the binding and
the period as the predicate; its outcome is the records that search must
return (a `reads_contain` assertion names every one) and the answer read off
them, graded by the rater under the request's own rubric; its dimensions
carry the line, the stream, the intent, the channel and the activity type,
so a run's summary slices by them. `industry export` writes the cases as
`evalrun-cases.jsonl` beside `records.jsonl`, and `worldloom evalrun run
PROGRAMME_DIR --rater grounded --out RUN` runs an agent over them with the
company's records as the connector state; `EvalSession.from_export` reads
the same directory. The reference agent states the request's expected
answer after its searches, so its run is the ceiling on all three axes;
shapes the grounded rater cannot grade without a model (causal chains,
citations, authority) stay ungraded rather than green. A request that rests
on the declaration alone is not an `evalrun` case; it stays a corpus case in
`cases.jsonl`. A telecom's 2,927 record requests are 2,927 cases. In the
Studio, `worldloom studio evalrun PROJECT_ID --source programme` grades an
agent on them for the lines the project seats, grouped under the line's use
case, and `--source both` runs them beside the dataset's cases.

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
those families with the line's own count. `project` also takes a
`CompanySpec` in place of the industry, the company as an interview settles
it (its units, countries, operating model and landscape), and derives the
same things from that company; `worldloom industry project company.json
project.json` writes the result for `worldloom studio init`. An interview
reply that changes the company edits `structure` and sets `derive`, and the
Studio derives the divisions, LOBs, use cases and acknowledged limitations
again (`industry.rederive`) before recording the revision, keeping the
families the project seats where the new company still supports them. The
seed, the episodes and every plan the catalogue does not derive stay as
they are. `company.resolve` picks the engine:
its own for a retailer, a bank or an insurer, and the retail shape for an
industry no engine builds, with that limitation stated in the project's
`acknowledged_unmet` and the programme it does have named in the sentence.

A project compiles like any other. Its world's business units are the
company's declared units (`industry.divisions`) and its systems of record
are the products the bindings name (`sor.products_for_world`: SAP S/4HANA
holding the journal entries and open items, Amdocs the bills, ServiceNow
the incidents), each owned by the leader of the unit that owns most of its
bindings. The process company is recorded on the snapshot world's recipe
(`process_structure`) and declared as one event dated where the company's
facts begin, and the programme's facts join the world's ledger about those
units, sourced on those systems. From the recipe the
builtin projections derive the company's records on `sor` and its channel
evidence on the emulated channels from the world alone: one email thread,
Jira issue, SharePoint file or Confluence page per bound activity, declared
channel and period, scoped to the line's LOB, stream and owning unit, and
naming the period's records and the one that tripped the exception. Each
use case requires one source entity per hard requirement under that scope,
so construction checks the line's evidence against the world and finds it,
and the evalrun that follows grades an agent on cases whose sources are
those records.

An industry no engine builds rides the retail shape, and the shape's
commercial seats take the company's own revenue function
(`industry.role_table`): the operating function, in APQC's sense, that the
industry's own value streams bind most in the company's revenue units
(`industry.revenue_function`), titled from the function table. A telecom seats a Customer Service Director and a
Customer Service Manager per unit where a retailer seats a Head of
Merchandising Systems and a Head of Buying; a logistics company seats
Fulfilment. The finance, technology and service operations spine is the
same for every company; the commercial post per unit is minted in the
revenue units only (`UnitRole.kinds`), so a shared service centre has a
managing director and a finance business partner but no one selling. A
retailer, a bank and an insurer keep their engine's organisation.

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

## The locale a company is built in

The catalogue's companies operate in twelve countries: AU, CN, HK, ID, IN,
JP, MY, NZ, SG, TH, TW and VN. Ten of them have a locale. Four were authored
(`australia`, `united_kingdom`, `germany`, `gulf`) and eight were generated by
`tools/ingest_locales.py`, so a company is spelled where it operates rather
than falling back to Australian names, cities, calendar and digit grammar
while its records were denominated in the local currency.

Thailand and Vietnam remain gaps and the generator records why. A deep name
pool needs 500 given and 500 family names; no library publishes a romanised
Vietnamese surname pool at all, and Faker's Thai surnames romanise to 314
distinct forms. Padding either would be inventing names, so those two keep
raising the finding.

Nothing in the generated ten is invented. Regions are ISO 3166-2 subdivisions
from pycountry, cities are ranked by population from geonamescache, names are
romanised from names-dataset or Faker, the currency and the whole digit
grammar are CLDR through babel, and the holidays are the fixed-date entries
the holidays package publishes. Two small tables are authored and neither is a
name: statutory company forms and the month a financial year opens, because no
library publishes either per jurisdiction.

The identifier surface follows the locale. `tools/ingest_surface.py` gives
the eight countries their real phone formats from libphonenumber and the
statutory registration number their invoices carry, so an Indian company
quotes a GSTIN and a Singaporean one a UEN where both used to print
`REG-########`.

India is the case the gap was named for. It takes INR, a financial year
opening on 1 April, Mumbai and Delhi, Republic Day and Independence Day, and
**lakh digit grouping**: 12,34,567 rather than 1,234,567. That last one is why
`Locale.grouping` exists. A single separator character could express a comma
or a full stop but not a group *size*, so every rupee figure this tool printed
was grouped the Western way until the CLDR pattern was read.

`industry.unlocalised` and `industry.locale_finding` are kept for the country
a future catalogue adds. They name the countries with no locale and write the
sentence the programme carries in `findings`; no shipped industry raises one
now.

## The shipped industries

Counts for each catalogue's default company, as `worldloom industry list`
prints them. Each is thirty LOBs; the lines are LOB × stream cells with at
least one bound activity; situations are the ways to phrase a request
and distinct answers are the ground truths under them.

| Industry | Engine | Lines | Situations | Distinct answers | Writes |
| --- | --- | --- | --- | --- | --- |
| banking | banking | 64 | 21,321 | 3,357 | 10,242 |
| consumer_products |  | 52 | 19,768 | 3,067 | 9,516 |
| healthcare |  | 58 | 4,931 | 778 | 2,362 |
| insurance | insurance | 63 | 15,294 | 2,395 | 7,356 |
| life_sciences |  | 52 | 14,826 | 2,310 | 7,137 |
| logistics |  | 58 | 39,560 | 6,177 | 19,100 |
| manufacturing |  | 55 | 20,388 | 3,155 | 9,801 |
| public_sector |  | 60 | 4,074 | 626 | 1,934 |
| retail | retail | 61 | 9,896 | 1,564 | 4,762 |
| technology_saas |  | 58 | 28,944 | 4,404 | 13,804 |
| telecom |  | 62 | 5,550 | 903 | 2,677 |
| utilities |  | 58 | 4,794 | 769 | 2,325 |

189,346 situations in all, resting on **29,505 distinct answers**. The two
numbers measure different things and only the second is an evalset size. A
situation is a binding crossed with a verb and a channel, so asking the same
billing exception by email and in a ticket, as a list and as a message, is
four situations over one ground truth. `worldloom industry list` prints both,
`ProcessLine.distinct_answers` carries the per-line figure, and a derived
Studio use case asks for the distinct count, never the crossing.

`evals.coverage.report` reads a programme's requests exactly as it reads a
corpus's cases (`coverage.Requested` is the shared shape), and a full
programme uses every situation the catalogue offers.


## Python

```python
from worldloom import industry

derived = industry.programme("telecom")
summary = derived.summary            # IndustryProgramme: lobs, lines, counts, unemulated, findings
summary.by_lob()                     # situations per line of business
summary.distinct_answers             # the ground truths under them: the evalset size
summary.capabilities                 # use cases per capability; `difficulties` likewise, `uniformity` says why a zero
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
