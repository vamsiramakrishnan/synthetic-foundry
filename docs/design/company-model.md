# A company is not an engine

Status: design proposal, for decision. Nothing in it is implemented.

## The question this answers

"How is procurement even an industry?" It is not. Procure-to-pay is one of the
sixteen universal value streams every company runs, and the process catalogue
this repository ships already says so: its thirteen activities are owned by the
procurement, warehouse, accounts-payable and treasury function families, and the
retail overlay lists the stream as core. Yet `procurement.py` registers a fourth
engine beside retail, banking and insurance, invents a contractor archetype to
host it, and gives it a role spine of function-family keys. The same confusion
runs through the rest of the model: an archetype bundles economics with
organisation, "line of business" means four different things, two company
specifications never meet, and a company described with twenty thousand
employees builds twenty-three people from a forty-name pool.

Three independent design reviews were run against the code (an operating-model
review, a synthetic-data generation review, an evaluation review). They agree
on the diagnosis and, with two adjudications noted below, on the target. This
document is the synthesis. It proposes the model, the migration, and the
decisions only the owner can make.

## Diagnosis

**An engine bundles nine things that are not one thing.** `domains.Domain`
carries archetype keys, a world builder, one episode and its cadence, role
keys, unit-role suffixes, lore targets, system slots and text templates. Each
engine then ships its own organisation generator, fact kinds, document
catalogue, check group and mosaic axes. Of all that, only three parts are
legitimately per industry: the revenue mechanics (sales times margin, net
interest income times book, premium times class), the industry episode (a
close, a capital return, a reserving cycle) with its regulated filings, and
the product objects (category, facility, policy, claim). Everything else
(the reporting spine, the finance and technology and service-desk roles, the
ERP, the personas, the access policies, the period arithmetic, the build
scaffolding) is the same in every company and is copied four times. The
generation review found `banking.py`'s build to mirror `retail.py`'s down to
the comment that says it is the same one three times.

**An archetype conflates economics with organisation.** `archetypes.Archetype`
is scale, unit shares, category margins, site formats and organisational units
in one record, and `share` and `margin` are on their fourth reading (revenue
share, net-interest share, premium share, spend share). `axes.py` already
notes nineteen declared units of which two have no categories and four no
sites, because the schema has nowhere to say a unit is cut differently.

**"Line of business" means four things.** `lob.Lob` is a function with roles.
`industry.derive_lobs` makes thirty of them per company, one per function
family. `docs/agents/company-specification.md` calls a revenue division a line
of business. `process_bindings.BusinessUnit.archetype` mixes cut dimensions
(product line, geography, segment, channel), organisational kinds (shared
service centre, group function) and legal structure in one enum.

**Two company specifications never meet.** `company.CompanySpec` (industry
prose, archetype, revenue, employees, geography, facets) builds the world;
`process_bindings.CompanySpec` (industry key, operating model, countries,
units, landscape) compiles the process structure. `industry.project` builds
both and reconciles nothing: nine of twelve industries get a retail world with
a limitation acknowledged, and support units are bolted on with the chief
executive as their leader.

**Headcount is a number nobody allocates.** `employees_total` is stated; the
roster is the role table (fourteen fixed rows plus three per unit). The name
pool is sized to that roster before any line of business is attached, so
attaching thirty of them fails at forty names while the locale holds five
hundred and fifty. A four-hundred-person retailer names twenty-four people
anywhere in its corpus; a twenty-thousand-person one names the same
twenty-three, and the documents do not change.

**The count I reported was inflated.** The evaluation review measured it:
telecom's 5,550 requests rest on 203 distinct expected answers, logistics'
39,560 on 1,412. The verb and the channel multiply nothing; every request on a
binding shares one structural sentence as its ground truth, including the
write verbs. The channel most often counted, the system record itself, is the
one no emulator carries. The catalogue's own eight evaluation templates, which
are work shapes with state, were never consulted.

## The target model

Declared (D) is authored data; derived (X) is computed and recorded on the
recipe.

| Concept | Kind | Meaning |
| --- | --- | --- |
| Industry | D | One catalogue overlay key per company, carried on the world beside the prose label. |
| Value stream | D | Universal (sixteen) or industry-specific. An activity belongs to exactly one stream and one function family. |
| Function family | D | The thirty catalogue families. Universal; an industry frame may add its own (claims, underwriting, actuarial) through a registration seam. |
| Line of business | D | A revenue line: what the company sells, with its share, its primary axis, its sites and a leader seat. Industry content. This is the word's only meaning from now on. |
| Function | D | A function family with roles, responsibilities, slot bindings and filings. What `lob.Lob` is today, renamed. |
| Business unit | D | An organisational container: a line of business, a shared service centre or a group function. Legal entity leaves this enum. |
| Operating model | D | Per company: family to owner kind (the catalogue's three), per-family overrides, an optional hybrid flag (centre-led policy, unit-executed). |
| Function instance | X | The join of family, owning unit and country the operating model yields. `ActivityBinding` already rows it out; it becomes an entity with a head seat, a headcount and systems. |
| Legal entity | D, defaulting to one per country | Country, currency, fiscal year, regulators, regional variant. Sites, systems, employment and filings attach here. |
| Site | D counts, X rows | Format, line of business, region, legal entity, headcount allocation. |
| Role and seat | Role D, seat X | A role is a position template; a seat is a position instance in a function instance or a site, with a manager seat. Seats are the org chart. |
| Person and workforce | X | A person fills a seat. The workforce is an allocation table over unit, function instance, legal entity, site and grade, summing to the stated headcount. Named people never exceed the allocation at any boundary. |
| System of record | D class, X entity | Class times landscape gives a product; one system per product and entity scope, owned by the function instance that owns the class. |
| Process instance | X | An episode run over one or more function instances for one period. Slots bound by function instances, never by engine role keys. |

**Adjudication 1: the word.** Line of business means revenue line. The object
in `lob.py` becomes `Function`; the module, the CLI verbs and the skill keep
the old name as an alias for one release. `industry.derive_lobs` becomes
`derive_functions`.

**Adjudication 2: what stays per industry.** An industry frame is authored:
revenue mechanics and the primary axis, the line-of-business pool, the
industry-specific streams and their episodes, regulated filings and
restatement rules, product objects, industry system classes (point of sale,
master data and commerce are missing from the catalogue and the retail frame
must add them), industry roles that join the spine, evaluation families about
those objects, vocabulary and site formats. Everything else is one generic
engine driven by the catalogue.

## One generic engine, driven by the catalogue

The generation review's finding is that the catalogue cannot mint a ledger
today for four structural reasons, none of them effort: activities carry no
quantitative priors; a binding cannot be a fact subject; the roll-up axis the
validator knows (subjects at one period, cohorts over periods) is not the
ownership tree a process ledger needs; and the authoring bridge demands an
installed engine. Each has a small, additive fix.

**Priors as versioned data.** `_data/process-priors/types@1.json` gives each of
the eight activity types spans in the existing parameter shape: volume per
full-time equivalent per month, exception rate, cycle time in business days,
approval rate, rework rate, escalation rate, late rate. Marked as authored
priors, exactly as the catalogue marks its own hints. Optional per-industry
overrides and a function-family headcount weight table sit beside it.

**The period ledger is the episode grammar's job.** A compiler turns a
compiled catalogue plus priors into one authored episode per value stream, run
by the existing `episodes.run`. Per activity type it declares kinds under
`process.<stream>.<activity>.*`: volume and exceptions for a capture;
submitted, approved, rejected, pending and cycle time for an approval;
items, matched, unmatched and break value for a reconciliation; and so on.
Every exception kind carries the catalogue's exception text as its label.
Three grammar extensions, all defaulted so existing specs replay byte for
byte: a `binding` subject type, a volume-from-headcount primitive, and an
ownership-tree roll-up invariant so binding cells sum to activity, activity to
stream per unit, unit to company. The existing derived-checks hook recomputes
all of it; no validator code per industry.

**Records are planned, then materialised lazily.** A record plan per binding
and period says how many records exist in which system (from the volume fact
and the emulator table), plus channel records at the declared channel priors.
A record is a pure function of the plan digest and an ordinal, with native
ids from the product's own pattern and one case id joining the whole chain (a
requisition, its order, its approval, its receipt, its invoice, its payment,
the email thread and the ticket). Nothing is generated eagerly: emulators
materialise on read, exports shard by binding, and the record count is a fact
the plan states rather than a file the corpus carries. This is where the
Snowfakery-style seam belongs: `detail.TableSpec` already has reference
columns and allocation from facts; it gains a table per system-of-record
object, cross-stream references, cardinalities and lifecycle ordering.

**Documents through the existing seam.** Four generic types, outlines only: a
process register per stream, a function period report per family, an
exception log (a table allocated from the exceptions fact with references to
the record plan) and a control attestation. Authored by the derived function
roles, which means the organisation generator takes its role table from the
derived functions rather than a per-engine literal.

**A generic connector per system-of-record class.** Only six products are
emulated; every ERP-bound activity is unreachable, so "all processes" is not
achievable until a connector definition is generated from the catalogue's
system classes and object lists (requisition, order, receipt, invoice,
payment, vendor). The evaluation review names this as the single largest
blocker.

**Determinism.** A recipe step names the industry, the stream, the period, the
priors version and the catalogue digest. Ids come from the world minter in
sorted binding order. Every draw is on a named stream. Default builds never
run the step, so they stay identical.

## Sizing and staffing a large company

Twenty thousand people is a defensible allocation table with named people
only where a seat matters to a document or an evaluation.

1. The stated headcount is the anchor; the productivity envelope already fixes
   revenue per head.
2. Front line versus support by industry prior (retail around 85 percent in
   stores and distribution, banking around 55 percent in branches and
   operations), front line allocated to lines of business by revenue share and
   to sites by format weight, using the existing largest-remainder allocator.
3. Support functions as benchmark shares of headcount (finance one and a half
   to two and a half percent, technology three to five, procurement under
   one), placed by the operating model: group functions at headquarters,
   shared services in the centre, unit-owned split by revenue share.
4. Spans and layers per function instance (front line twelve to twenty,
   knowledge work six to eight), so a twenty-thousand-person company lands at
   seven to nine layers. `roles.from_shape` has the arithmetic and applies it
   at one span for the whole company; it is reused per instance.
5. Three tiers of people. Named: the spine, every function-instance head,
   every unit leader, any site manager a document names, every process slot
   filler, anyone an evaluation demand asks for. That is one hundred and
   fifty to four hundred people at twenty thousand. A roster tier of person
   stubs (id, name, function, site, manager) is a pure function of seed, site
   and ordinal, served but never stored; record assignees come from it.
   Everything else is an allocation row with a stable seat key.
6. Names stop being a pool. Beyond the base count that existing corpora draw,
   names are the given-times-family product of the locale's extended
   vocabularies (about three hundred thousand distinct per locale), indexed
   deterministically. Existing corpora keep their tuples because the base
   pool is a verbatim prefix. The forty-name ceiling and the four-function
   project cap disappear.

## The evaluation model

**The unit is a task, not a situation.** A task is a process instance (an
activity with its control and exception, at an owner seated by a person, in a
system, at a period), a request (persona, channel, wording from the intent
table's verb and failure mode), a starting state (named fixture records with
closed foreign keys plus the near misses the task needs), an expected end
state (the existing outcome contract), an expected trajectory shape (the
existing plan contract, failure points, question points, call budget) and the
three grading axes unchanged.

**Tasks derive from an activity, not from a cross.** The catalogue's eight
evaluation templates are the task kinds: the happy-path action, the exception
path (no write with a stated reason, or a rejection with its reason), the
queue over a threshold, the reconciliation across two systems, the evidence
chase into a channel, the handoff, the policy question that abstains when no
policy fact exists. Each kind is a skeleton (an abstract graph over connector,
entity and operation) bound to instances (concrete records at one owner and
period) and to variants (surface perturbation). Honest variation is data
variation bounded by independent record sets, one instance per named
exception with a near miss, under-specification with a question point,
designed failures at named nodes, and multi-system joins only where the
activity's objects span systems.

**A count is a claim someone can check.** State three numbers: skeletons
(activities times evaluable task kinds), instances (each executed once by the
reference agent, which must pass all of them), and records touched. Variants
are reported beside them, never summed in. An activity whose control is not
machine-evaluable is listed as not evaluable, not counted. Logistics reads
something like "139 activities, around 90 evaluable, six kinds, around 500
skeletons" rather than 39,560, and that is the number to defend. Situations
remain as coverage: what the catalogue offers, not what the corpus holds.

**Coverage per cell, difficulty observed.** Coverage is a matrix per line of
business, stream and activity over closed vocabularies (effect, decision,
path, systems joined, question kind, designed failure, record scale), planned
at strength two and proven by a reference-agent pass. Difficulty is a
pass-rate band per slice with its support, empty until observed; the label
assignment by verb effect is removed.

**Hero use cases at scale.** The housekeeping module has the right grading
primitive (the per-record ratio) and the right search binding. Its corpus is
the gap: a tagged sub-corpus disjoint from the world, one rule per case. The
proper family projects thousands of files, messages and channels from the
world's own artifacts, people, units and periods across several connectors at
once, puts the rules in a policy document the agent must read (retention,
filing convention, legal hold, with a stated precedence that the expected
state is derived by), includes partial states and denied moves, and grades
idempotency (a second run diffs to nothing), collateral as a ratio with a
hard fail only for deletes, budget per record against the reference, and the
records the agent correctly declined to touch.

**What the interview elicits.** Operating model; units by country; system
landscape per class; lines of business in scope; volumes per object per
period; delegation thresholds and retention rules; which task kinds and which
question policy per use case. It proposes a programme matrix whose counts are
skeletons, instances and records with the not-evaluable and unemulated cells
named.

## Migration, keeping every default build byte-identical

The precedent is every opt-in that landed as an absent default. The four
engines remain the default path and are not edited; the generic engine is
reached only by opting in, and the recipe records only steps that ran.

1. Name the concepts: `Function` in `lob.py` with the old name as an alias;
   line of business documented as revenue line; the industry key carried on
   the recipe, not as a new serialised field.
2. One company document: `company.CompanySpec` gains a structure block
   (operating model, countries, units, landscape) that resolves into the
   process specification; `industry.project` stops building two.
3. Consolidate the catalogue: one file, one loader, `process_bindings`
   canonical; `process_planning` becomes an adapter, then goes.
4. One build: the shared scaffolding extracted into a single builder the four
   engines call; proven by the byte-diff sweep.
5. Staffing model: a pure allocation from priors, headcount, shares, operating
   model, countries and sites; a recipe step; workforce facts minted last in
   their own id sequence; a check group for sums and named-within-allocated
   per cell; name generation from the product of the extended pools.
6. Catalogue-derived organisation: the generator takes derived functions as
   its role table when a catalogue is present; support units get real
   leaders. Reached by opting in.
7. Priors, the episode compiler, the three grammar extensions, the four
   generic document types and the process check group. First target: telecom,
   the smallest engine-less industry.
8. Record plans and the generic system-of-record connector, replacing the
   token-classified projections for catalogue worlds only.
9. Procurement becomes a function: the procure-to-pay stream at any industry,
   proven inside a retail world feeding the close's accrual. The old cycle
   stays registered as a recipe verb for replay; the domain and the
   contractor archetype are deprecated (frozen for replay, removed from
   inspiration, listing and interview), removed at a major version.
10. Retail, banking and insurance become industry frames whose organisation
    content the generic engine can replace when opted in; their revenue
    mechanics, regulated episodes and workbook compilers stay authored.

The evaluation programme follows the same order: task kinds and skeletons
over the existing contract and grading first, honest counts replacing the
situation count, then instances as record plans arrive.

## Decisions for the owner

1. **Construction.** The contractor archetype was only ever a home for the
   procure-to-pay demo. Author a construction overlay (the crosswalk currently
   sends NAICS 23 to manufacturing) or let the contractor go.
2. **The rename.** `lob` is in the CLI, the SDK, the Studio and a skill. Alias
   for one release, or a clean break.
3. **Serialisation.** New fields on company, employee or unit move every
   `world.json`. Sidecar files (workforce, allocations) or gated
   exclude-default dumping. The proposal assumes sidecars.
4. **The second ledger tier.** A record plan is evidence the corpus serves,
   not a fact it asserts, so it lives outside the facts file. Confirm.
5. **What large means.** Hundreds of sites with a thin named roster (the
   proposal), or thousands of named people.
6. **Money for the nine industries.** The catalogue has no monetary scale;
   engine-less industries lean on revenue ratios until a frame is authored.
7. **Who authors control predicates.** Most activity controls are free text;
   a versioned file must map each to an evaluable predicate or mark it not
   evaluable. Half the skeleton count depends on this.
8. **The honest count.** Programme counts drop by an order of magnitude when
   stated as skeletons and instances. Confirm that is the claim to make.
9. **Operating-model expressiveness.** Three global models plus per-family
   overrides and a hybrid flag for the first version, or richer.
10. **Legal entities now or later.** Regional variants exist in the catalogue
    and nothing consumes them; deferring keeps the staffing step smaller.

## What is kept

The three grading axes, question and failure points, the safety laws, the
per-record ratio, the executable DAG grammar and its compiler, the
housekeeping planner mechanics, the intent table as request surface and
failure mode, function derivation from operating model and family, the
seating rule, the emulator table, the shared coverage measurement, the
difficulty features, the episode grammar, the detail table seam, the
largest-remainder allocator, the versioned-data discipline and the
byte-identity gate. None of it is thrown away; it is put under a model that
says what a company is.
