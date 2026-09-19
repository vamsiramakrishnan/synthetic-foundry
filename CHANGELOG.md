# Changelog

Worldloom versions its releases and its worlds together: every generated corpus
stamps the version that made it into `world.json`. Changes that alter what a
seed generates are listed under **Generation**; they are breaking for
reproducibility even when no API moved.

## 0.1.0

The first release. Everything below it is what 0.1.0 ships; the notes run
newest first, and the section headed *The foundation* is the release as it was
first written up, before the waves above it landed.

### A back-office scenario, and the shipped scenarios are tested

- The enterprise-evals planner shipped four workflows, and every one was
  shaped like a service desk: incidents, changes, customer accounts, an
  executive digest. The two industry profiles added banking and retail
  workflows over the same channels. Nothing closed a month, matched an
  invoice, onboarded a starter or renewed a contract, which is the work
  that stresses an agent differently from triage.
  `examples/enterprise-evals/back-office.json` adds four such workflows:
  `finance_month_end_close`, `procurement_exception_review`,
  `hr_onboarding_readiness` and `contract_renewal_review`. Each reads the
  `sor` connector beside the channels: journals, accounts, bank statements
  and consolidations for the close; purchase orders, goods receipts,
  invoice receipts and open items for the match; workers, positions and
  requisitions for onboarding; contracts and orders for the renewal. Two of
  them write back to `sor` (a case, a contract) as well as to a page, a
  file or an email.
- The four widen the axes rather than the name list. Together they use
  every topology, add `classify` and `transform` to the content actions the
  builtin workflows emit, add `csv` to the output formats, and set
  audiences a controller or a people partner would recognise. Their
  templates read as a request a manager types. Every `sor` entity they
  name is one a catalogue company binds records for: `employee` and
  `vendor_bill` are connector entities, but no industry's default company
  holds records of them, so a row over them would materialise evidence
  carrying no fact and be refused at validation.
- The profile needs a world built from a catalogue project (`worldloom
  industry project`, then a Studio snapshot), because only such a world
  carries `sor` records. On the golden retail corpus its `sor` rows refuse
  with the same finding that any shipped profile's rows meet on a world
  that lacks their records. The description notes that chat and post
  destinations can be added when those connectors land.
- Nothing loaded the shipped profiles before.
  `tests/test_enterprise_scenarios.py` loads every file in
  `examples/enterprise-evals/`, merges it onto the builtin registry, and
  asserts that `review()` finds nothing, that every named workflow exists
  and survives the connector selection, that every role names a connector
  and entity the merged registry carries, that every template uses only
  the planner's placeholders, and that every destination operation is one
  the planner can phrase. A `comment` destination passes `review()` and
  fails at plan time, so that last check is the one the loader could not
  make. Nothing builtin moved: every plan made without a profile is
  byte-identical.
### The planner knows every connector the emulator serves

- The connector definitions carried fourteen connectors. The enterprise-evals
  planner's registry carried eight, hand-written and never compared against
  them. A scenario profile naming `slack` or `teams` was refused as an unknown
  connector while the emulator stood ready to serve it, and the seventy-six
  tools of `onedrive`, `outlook`, `slack`, `teams`, `rovo` and
  `teamwork_graph` were out of the eval space's reach. `builtin_registry()`
  now carries a `ConnectorSpec` for all fourteen.
- Each new spec mirrors its definition entity for entity. Every operation on
  it is one the definition maps to a tool, so `patch` and `upsert`, which no
  definition carries, stay off the six; a workflow that asks for one is
  reported by `review()` rather than planned. A test holds the two catalogues
  to each other by name, entity and operation, so a definition added without a
  spec fails there and not in a user's profile.
- Maturity is not a gate. The repository has no rule that hides an `eap` or
  `product_surface` connector: the definitions expose `rovo` and
  `teamwork_graph` unconditionally and the binding carries their maturity
  through as data. The specs follow suit, and the four `ga` connectors and the
  two others are wired the same way.
- The request text now takes a connector's name from its spec's
  `display_name`. It used to go through a chain of `str.replace` calls that
  knew seven names, so any connector added later printed in lower case, and
  through `str.title()` for the destination, which printed ServiceNow as
  "Servicenow". The strings those two paths produced for the original eight
  are pinned by name, so every planned row that exists renders byte for byte
  as before, and a test proves it on a narrowed profile. A connector a profile
  authors itself now renders its `display_name` in the request text; its query
  ids do not move, because they are keyed on the row, not on the text.
- The shipped scenario profiles list their connectors explicitly and plan the
  same bytes. The default profile spans fourteen connectors but no built-in
  workflow names the new six, so its candidate space is unchanged: past the
  ten million ceiling before and after.
### A described company that could not be built says so

- `build --inspired-by "a mid-size Singaporean hospital group"` built Greyfell
  Retail Group, an omnichannel retailer in Wellington whose largest unit was
  Food, and reported `coherent: 5064 checks passed`. Nothing said a
  substitution had happened. The same description through `--spec` had always
  reported it as `unmet`; the build path resolved through the same fallback and
  never asked whether anything matched.
- `company.unmet_for_description` is now the one function that words it, and
  both callers use it, so the two cannot tell a reader different stories about
  the same substitution. It names the industry it did recognise, the shape that
  got built instead, and the command that does work: "no registered domain
  builds a 'healthcare' world, so the world is built with the
  'omnichannel_retailer' shape … `worldloom industry programme healthcare`
  derives its lines of business, processes, requests and counts".
- Falling back still beats raising, which is why the build still succeeds. What
  changed is that it is no longer quiet. A description the registry recognises
  reports nothing, because a notice on every build teaches the reader to skip
  the one that matters.
- No bytes moved. The resolved shape is what it always was, so every corpus
  built from a description is byte-identical to the one built before this.
- Still missing, and missing on both paths equally: neither the specification
  nor the description path *persists* the substitution into the corpus. A world
  handed to someone else still cannot say it was built as a stand-in.

### Eight locales, generated from published data (Generation)

- Four locales shipped and the catalogue built companies in fourteen
  countries, so an Indian telecom was given Australian names, Australian
  cities, an Australian calendar and Australian digit grammar while its records
  were denominated in rupees. `tools/ingest_locales.py` generates eight of the
  ten that were missing: China, Hong Kong, India, Indonesia, Japan, Malaysia,
  Singapore and Taiwan.
- Thailand and Vietnam are still gaps, and the tool records why for each. A
  deep name pool needs 500 given and 500 family names. No library publishes a
  romanised Vietnamese surname pool at all, Faker carries ten, and Faker's Thai
  surnames romanise to 314 distinct forms. Ten Vietnamese surnames is not even
  wrong, since they are extraordinarily concentrated, but it cannot meet a
  contract that draws one distinct surname per person. Padding either pool
  would be inventing names, so `locale_finding` keeps saying TH and VN have no
  locale.
- Nothing in them is invented, which is the point: ten hand-written name pools
  would have been ten fabrications. Regions are ISO 3166-2 subdivisions from
  pycountry, cities are ranked by population from geonamescache, names are
  romanised from names-dataset or Faker, the currency and the entire digit
  grammar are CLDR through babel, and holidays are the fixed-date entries the
  holidays package publishes.
- Romanised deliberately. Faker's Japanese, Chinese and Indian providers are in
  native script, and this project renders English-language business documents,
  where a group report listing two scripts is a mixed-script artefact rather
  than a more accurate corpus.
- names-dataset needed cleaning and the tool says so: its per-country first
  names are derived from profile data where field order varies, so Singapore's
  list opens with an abbreviation and four surnames. A candidate that also
  appears in the country's surname list is dropped, as is anything under three
  characters.
- **`Locale.grouping`**, and the reason it had to exist. India writes 12,34,567
  and not 1,234,567, and its filings are denominated in lakh and crore, so
  every rupee figure this tool printed was grouped the Western way. A single
  separator character can say comma or full stop but not group *size*. The
  value is read from the CLDR decimal pattern, `spell` honours it, and it
  defaults to thousands so every locale written before it stays byte-identical.
- Two tables are authored and neither is a name: statutory company forms and
  the month a financial year opens, because no library publishes either per
  jurisdiction. India and Japan open on 1 April; the rest default to the
  calendar year.
- The identifier surface follows. `tools/ingest_surface.py` adds the eight
  countries to `data/surface/rules.json`, with phone formats from
  libphonenumber's published national formats and the statutory registration
  number each country's invoices carry: an Indian company quotes a GSTIN and a
  Singaporean one a UEN, where both used to print `REG-########`. Hong Kong
  takes the PO box convention this repository already uses for the Gulf,
  because it numbers no addresses. No pre-existing country changed.
- Two defects the dispersed-replay gate found, and what each one broke. A
  locale must answer for every engine `domains.names()` registers, and the
  generated table stopped at banking and insurance, so every procurement build
  in the eight new jurisdictions raised at company-naming time. Procurement
  forms are now carried for all ten countries, and a test walks the engine
  registry rather than a written list.
- names-dataset mixes scripts, and three kanji surnames reached Japan's pool
  past a filter that only looked at length. Every generated pool is filtered to
  romanised forms and a test holds it, which is the property the whole tool was
  built on.
- A company form carrying punctuation is no longer read as an invented entity.
  The narration validator peels `.,;:()'"` off every token it extracts, so a
  company chartered `Greyfell Engineering Co., Ltd.` came out of prose as
  `Greyfell Engineering Co Ltd` and matched neither its own name nor any
  fragment of it. Every East Asian company form carries that punctuation, so
  every narration in those jurisdictions was rejected for naming the company it
  was about. The world's own names are stripped the same way before matching.

### Employment is measured, and every shape grounds (Generation)

- `worldloom.staffing` reads occupational employment by industry from the
  Bureau of Labor Statistics. `tools/ingest_bls_oes.py` joins three tables that
  were already here or one download away: OES employment for an SOC occupation
  inside a NAICS industry, the O*NET function crosswalk in `_data/functions`,
  and the process catalogue's NAICS map. All twelve shipped industries are
  carried, from 37,944 occupation-by-industry rows.
- The numbers discriminate where revenue share could not. 58% of a freight
  company's employment is warehousing, 32% of a consumer-products company's is
  production, and 15% of a software company's is engineering. A 20,000-person
  logistics company now puts 18,070 people in warehousing; the revenue-share
  proxy could not tell it from a software company.
- Every derived line carries `workforce_share`, and the programme names the
  release it was measured from. `staffing.allocate` turns a stated total into
  people across the families a company models, by largest remainder so the
  parts sum exactly. An industry the table does not carry gets a zero share and
  a finding that says so, never an even split.
- Longest NAICS prefix wins in the crosswalk. The catalogue carries both
  `NAICS 52` (banking) and `NAICS 5241` (insurance), and first-match order put
  every insurer in the bank.
- `establish` still splits a pack's units by revenue share and now says why:
  a pack's units are trading divisions, and no employment survey counts those.
- **Every DAG shape is planned by default.** `map_read` and `conditional` were
  opt-in because they raise a source's `minimum` to two while the materializer
  topped a source pool up to exactly one record, so rows under them
  materialized and then refused to compile. `materialize_corpus` now tops a
  pool up to the largest minimum any planned row asks of it. The first filler
  record keeps the key it has always had, so a corpus that only ever needed one
  is byte-identical.
- A predicate-filtered source, or a corpus built `strict_sources`, is still
  refused rather than filled: a filler record meets a count and not a claim,
  and the refusal names how many records are present and how many are needed.

### Procurement is a function, and the system says so

- The engine registry listed `procurement` beside `retail`, `banking` and
  `insurance` as though a company could be one. It builds an infrastructure
  services and contracting group, and procure-to-pay is the function its
  episode exercises inside that company. `Domain.industry` declares what an
  engine builds when its own key is not that, `domains.describes` reads it,
  and `worldloom pack targets` prints it. Nothing is renamed: the key is a
  registry key and a corpus identifier, and renaming it would change bytes
  everywhere for a word.
- `industry.function_of` and `industry.stream_of` recognise the words a
  function family and a value stream are asked for in, both built from the
  catalogue rather than authored. `industry.function_finding` turns either
  into one sentence: what was named, that a company has it rather than is it,
  and the `industry.project(...)` call that gets the asker what they wanted.
- A company description that names a function now says so. It read "nothing
  recognised it", which was true and useless: the asker named a real thing in
  the wrong slot, and the twelve shipped industries all carry a procurement
  function already.
- A value stream gets its own sentence, because it is not one function either:
  the catalogue runs `procure_to_pay` across four function families and
  `order_to_cash` across nine, so folding either into one would contradict the
  activity ownership the catalogue ships.

### The stated workforce is allocated, not just stated (Generation)

- A company stated one headcount and nothing spent it. A 400-person and a
  20,000-person retailer carried the same three units and the same two dozen
  named people, so no document could say how big a division was.
  `BusinessUnit.headcount` now carries each unit's part of that total, and
  `generators.org_builder.establish` allocates it: the whole stated number, by
  each unit's declared share of group revenue, by largest remainder so the
  parts sum to it exactly. A 400-person retailer establishes 256/84/60; the
  20,000-person one establishes 12,800/4,200/3,000.
- Revenue share is a proxy for staffing, not a measurement, and it is the only
  per-unit weight a pack declares. It is deliberately not derived from the
  named roster: a pack names the decision-making graph, which is top-heavy by
  construction, so the roster's own proportions would put half a retailer in
  group functions.
- Two validator rules. `establishment_exceeds_headcount` when the units
  establish more people than the company states, and
  `named_roster_exceeds_establishment` when a unit holds more named employees
  than it establishes.
- The world summary names the largest unit and its share of the workforce.
- `headcount` is optional and defaults to `None`, which reads "the world does
  not say". `examples/retail-close` is hand-authored and keeps saying nothing.

### A default build plans a delete (Generation)

- `enterprise-evals plan`, `build` and `qualify` with no `--dag-shape` planned
  the single-write trajectory the grammar produced before shapes existed. Every
  case set they made reported `deletes: 0`, so none of them could grade a
  delete at all. They now plan every shape a row can ground on the sources it
  already declares, `delete_chain` among them. 120 cases from `retail-close`
  grade 11 deletes where they graded none.
- `enterprise_dag.default_shapes()` derives that set from the catalogue rather
  than listing it. `map_read` and `conditional` raise a source's `minimum`
  above what the row asked for, so they stay opt-in: a world holding one record
  where the row wanted one plans a case that materializes and then refuses.
- `enterprise_dag.resolve_shapes()` is the one spelling all three commands use.
  `--dag-shape none` plans the old single-write trajectory, `*` is the whole
  catalogue, and omitting it is the default set.
- A row that outruns the corpus now says so. The refusal read "insufficient
  bound source records"; it names the connector, the entity, how many records
  bound and how many the row needs.

### A container, a checked package, and an honest install line

- A `Dockerfile` builds the wheel and installs it, so the image runs what a
  wheel install gives anyone rather than a source tree. It runs as uid 10001,
  writes only to the `/workspace` volume, and carries the four renderers and
  the MCP server. CI builds it on every push, opens the console on a published
  loopback port, renders DOCX, XLSX, PDF and PPTX inside it, and checks the
  process is not root.
- `worldloom studio serve --host` picks the bind address; it stays 127.0.0.1
  unless you name another. A non-loopback bind prints what it gives away: the
  console has no authentication, so anyone who reaches the port can read the
  company and start jobs.
- The console's origin guard now reads the host *name* and ignores the port.
  Pinning the port rejected every container whose published port differed from
  the port inside it, and bought nothing: a page on another origin picks its
  own port freely, so the loopback name is the whole defence against DNS
  rebinding.
- `twine check --strict` runs on the built sdist and wheel in CI and in the
  release, before anything is uploaded. A README PyPI cannot render is rejected
  at upload, after the version number is spent.
- The release workflow takes a concurrency group that does not cancel: a run
  that has already uploaded cannot be replayed under the same version.
- The README says what actually installs today. Nothing is on PyPI, so the
  three paths are a checkout, a wheel you build, and the container; the PyPI
  line says plainly that no tag has been pushed.

### An installed coding harness is one flag

- `worldloom evalrun run --harness codex|claude`, `evalrun plan --harness` and
  `narrate loop --harness` drive an installed coding harness through the
  adapter this package already shipped for the Studio, using that harness's
  own login. Grading a real agent against the reference ceiling, and getting
  prose accepted, no longer needs an adapter script. `studio.harness.adapter_command`
  is the one spelling all four commands use, quoting for the platform the
  child is split on.
- The adapter now tells the child which seam it is answering
  (`studio.harness.role_for`). It sent authoring prose to every child, so an
  evalrun turn told the agent under test it was completing an authoring
  request; a turn, a plan, a rating and a narration request each get their
  own role, and every one of them still ends in "return exactly one JSON
  object". A native trial that opts in to workspace writes now refuses a seam
  with no write instruction to grant rather than silently dropping the opt-in.
- `narrate loop` takes `--exec` or `--harness` and refuses with both or
  neither, naming the offline round trip in the refusal.

### A country with no locale says so

- `industry.unlocalised` and `industry.locale_finding` name the countries no
  shipped locale answers for and what the company loses to the one it is
  built in: its names, cities, calendar, figure grammar and currency. Ten of
  the twelve countries the shipped industries operate in are among them.
  The programme carries the sentence in `findings`, and the Studio console
  shows it as an acknowledged limit beside the missing engine, which does not
  withhold readiness. The sentence names the currency the catalogue declares
  for those countries, because connector records carry it per country while
  rendered documents carry the locale's.

### Honest counts, and a support unit that earns no revenue (Generation)

- **A programme reports what it grounds, not how it can be phrased.**
  `IndustryProgramme.distinct_answers` and `ProcessLine.distinct_answers`
  count the distinct ground truths a company's requests rest on;
  `industry.lines` fills them when passed the requests. A verb and a channel
  change a request's wording and leave its answer alone, so `situations`
  counts phrasings over these: the twelve shipped industries offer 189,346
  situations resting on 29,505 distinct answers, and a telecom's 5,550 rest
  on 903. `worldloom industry list` prints both.
- **Generation.** A derived Studio use case now asks for the line's distinct
  answers rather than its situations, so a catalogue project stops requesting
  six queries for every answer it can ground. A telecom's billing project
  requests 57 queries where it requested 282.
- **Generation.** `industry.divisions` returns the revenue units alone.
  A shared service centre and a group function sell nothing, so they no
  longer take an equal cut of the company's revenue; they are formed as
  business units by `ownership.materialize_owners`, which allocates none,
  and the Studio snapshot forms them before it declares the structure. A
  telecom's revenue is its two customer segments, not four units at a
  quarter each, and no per-unit commercial or finance post is minted inside
  a unit that sells nothing. `divisions` takes the compiled catalogue to
  weight each division by the bindings it owns.

### The console in the README

- `README.md` gains a Studio console section with four pages of the console
  (overview, company and processes, use cases, evaluations), and
  `docs/studio.md` a gallery of all eight, captured from the connected retail
  pilot and a catalogue-derived telecom company under `docs/images/studio/`.
- The console's overview subtitle and the "Generation boundaries" panel no
  longer print a blank engine for a company no engine builds; the panel
  says the world is derived from the process catalogue.

### The programme's record requests run as evalrun cases

- Every record request of a programme is an `evalrun` case
  (`Programme.evalrun_cases`, `industry.evalrun_cases`, `industry.evalrun_row`):
  its plan searches the `sor` connector per record kind the binding holds
  in the request's period, its outcome is the records the search must
  return (`reads_contain`) and the answer read off them under the request's
  own rubric, and its dimensions carry line, stream, intent, channel and
  activity type. `industry export` writes them as `evalrun-cases.jsonl`
  beside `records.jsonl`; `worldloom evalrun run` and `EvalSession.from_export`
  take such a case set in place of an enterprise corpus
  (`evalrun.contract.read_case_set`, `is_case_set`). The reference agent
  states a row's `expected_answer` when the row carries one, so its run is
  the ceiling on the answer axis too; rows without one are unchanged. A
  telecom's 2,927 record requests are 2,927 cases, and the reference run
  passes every one the grounded rater can grade. The Studio's `evalrun`
  job takes `evalrun_source` (`dataset`, the default; `programme`; `both`):
  a project with a process structure grades the programme's record requests
  for the lines it seats, grouped under the line's use case, over the
  company's own records, with or without the dataset's cases
  (`worldloom studio evalrun --source`).

### The commercial seats take the company's revenue function

- A project of an industry no engine builds rides the retail shape with
  the shape's commercial seats (`merch_lead`, `merch_analyst`, the per-unit
  `_buyer` post) retitled and refunctioned from the company's revenue
  function: the operating function, in APQC's sense, that the industry's
  own value streams bind most in its revenue units
  (`industry.revenue_function`), titled from the function
  table (`industry.role_table`, passed to the world as the pack's roles). A
  telecom seats a Customer Service Director, a logistics company Fulfilment.
  A per-unit post may name the unit kinds it is minted for
  (`roles.UnitRole.kinds`, `PackUnitRole.kinds`; empty mints it everywhere,
  as every engine's own posts do), and the commercial post is minted in the
  revenue units only. `sdk.Blueprint.role_table` takes a pack's authored table over the
  engine's shipped one when lines of business attach, which a pack that
  authored its organisation lost before. Generation: worlds of catalogue
  projects for engine-less industries change titles and functions on those
  seats; retail, banking and insurance worlds are unchanged.

### The interview describes the company, the catalogue derives the rest

- `industry.project` takes a `CompanySpec` in place of an industry name:
  the company as an interview settles it (units, countries, operating
  model, landscape) yields its divisions, LOBs and use cases the way the
  industry's default company did. `industry.rederive` does the same for an
  existing project, keeping its seed, episodes and plans and the families
  it seats where the new company still supports them. An interview reply
  sets `derive` to ask for it, and the Studio derives before recording the
  revision (the reply must carry a structure). `worldloom industry project`
  writes a project from an industry or a company spec for `studio init`.
  The locale follows the company's first country that has one
  (`industry.geo_for`), `australia` otherwise. The catalogue's
  `process.<stream>` fact kinds are registered the first time any process
  consults the fact-kind registry (`factkinds.process_kinds`), so a project
  written by `worldloom industry project` lints the same under `studio
  init` in a process that never imported `worldloom.industry`.

### A catalogue project compiles and grades end to end

- A Studio project derived from the catalogue (`industry.project`) now
  builds a world of its own company and compiles its dataset. The world's
  business units are the company's declared units (`industry.divisions`:
  one pack unit per declared unit, named as declared, its kind the unit's
  archetype), so a process fact can be about the unit that owns the work.
  The process company rides the snapshot world's recipe under
  `process_structure` (`recipe.apply_process_structure`, recorded as the
  recipe step `ApplyProcessStructure` so a rebuild replays it in its
  place). The company's systems of record are the products its bindings
  name (`sor.products_for_world`): one system each, owned by the leader of
  the unit that owns most of its bindings, holding the record kinds the
  catalogue gives it (a telecom gains nineteen, SAP S/4HANA and Amdocs
  among them). The company is declared as one event
  (`organisation.process_structure`, the chief executive its actor, the
  units and the new systems its subjects, dated where the company's facts
  begin) and stated in the ledger: the programme's facts join the world
  subjected to its units, sourced on its systems and caused by that event
  (`sor.facts_for_world`), so a record that cites them cites facts the
  world holds. From the recipe the builtin projections derive the
  company's records on `sor` (`connector_data.generate_sor`) and its channel
  evidence on the emulated channels (`sor.channel_records`: one email
  thread, Jira issue, SharePoint file or Confluence page per bound activity,
  declared channel and period, scoped to the line's LOB, stream and owning
  unit, naming the period's records and the one that tripped the
  exception). A use case declares one hard requirement and one read step
  per source entity, a selector scoped to a value stream covers the use
  case's activities, and support ownership forms nothing for a world built
  from the structure it is given, so construction checks the line's
  evidence against the world and finds it. A world built without a process
  company projects nothing new, so every existing corpus is unchanged.
  Materialising a corpus memoises the connector entity alias check, which
  was parsing a connector definition once per record. Generation: worlds
  and datasets of catalogue projects change (units, the declaration event,
  the process facts, `sor` records and channel evidence).

### Requests read their answers off the records

- A programme now derives the company's system-of-record records
  (`sor.records`, six periods ending at `sor.ANCHOR_PERIOD`, three records
  per binding, kind and period) and every request whose intent rests on a
  record set (`evidence_kinds` names `record_set`: find the exception,
  triage a queue, chase, reconcile, respond to a query and the others) is
  asked about the binding's records in the latest period and answered from
  them (`sor.answer`): the purchase orders among March's that tripped the
  price check, the open items to chase and their owner, the statuses of the
  rest. `Request.expected_record_ids` names the records the answer cites and
  `Request.period` the period; the earlier periods stay in the records as
  the distractors a real system holds. A request whose intent rests on the
  declaration alone still answers with it. One request per situation, as
  before, so the counts are unchanged; a telecom's 5,550 requests now have
  903 distinct answers rather than 203. `IndustryProgramme` reports
  `records`, `record_requests`, `period` and `periods`; `industry export`
  writes `records.jsonl`. Generation: every programme's requests and cases
  change where the intent reads records.

### Every system the catalogue names has records

- `_data/connectors/sor.json`, one system-of-record connector standing in
  for every product the catalogue names and no emulator of its own covers
  (61 of 67 products: SAP S/4HANA, Workday, Temenos T24, Guidewire, Epic,
  Amdocs and the rest). Its 73 entities are the catalogue's record kinds,
  each with a workflow (a purchase order is created, approved, sent,
  received, invoiced, closed), searchable on the fields a binding gives a
  record, created under an idempotency key on the activity, period and
  owner. `tools/build_sor_connector.py` builds it and
  `emulated-systems@2.json` from the catalogue; only the workflow table is
  authored, and the tests check the shipped files against a rebuild.
- `worldloom.sor` derives the records: one per bound activity, record kind
  and period, id in the product's own pattern (SAP's `45{8d}`), status from
  the kind's workflow, an amount in the country's currency where the kind
  carries money, the binding's exception on one record in four, every
  record linked to the programme's facts about its binding. No draw and no
  clock: the record is a function of the binding, the kind and the period.
- The programme reports every line of every industry as supported; what
  stays unemulated is the three channels with no emulator (chat, workflow
  approval, portal filing). A Studio dataset built from a catalogue project
  serves the records through `FrozenCompanyBuilder(projections=...)`, so a
  request about a March invoice in SAP has March invoices in SAP to be asked
  over. Generation: datasets of catalogue projects gain `sor` records; the
  emulator mints ids for any `{Nd}` pattern.

### A project seats every line of business

- `industry.project` seats every family with a supported process line, not
  the four largest: a bank is twenty-five lines and over a hundred people.
  The cap was the composed pack's name pool, cut to the organisation the
  description mints before any line attached; `sdk.Blueprint.lob` now
  re-cuts the pools from the locale to the people the lines add (identical
  draws while the count fits the base pool, the extended pool past it) and
  leaves a pool an author wrote alone for `packs.lint` to report. A
  blueprint with attached lines and no shape takes the engine's own role
  table, so a line attached to a bank joins the bank's organisation instead
  of displacing it with retail's. Generation: every derived Studio project
  and interview request carries every line and its people.

### Job titles from O*NET on every derived line of business

- The function table carries one job title per tier (head, manager,
  professional, support), chosen from the titles O*NET holds for the
  function's seats by a rule the file states: the shortest title carrying
  the tier's word and one of the function's keywords, reported titles before
  alternate ones, a derived title marked `source: derived` where no seat has
  one (17 of 148). `worldloom.functions.Title` reads them.
- `industry.derive_lobs` titles each line of business from the table (a
  Billing Supervisor and a Billing Clerk, not a "Billing Manager" and a
  "Billing Analyst" typed from the family name) and seats a fourth role,
  `<family>_support`, where the function has a support title. Generation:
  every derived programme, Studio project and interview request carries the
  new titles and the support seats; the seat that asks about an activity
  (`SEAT_BY_TYPE`) is unchanged, so request counts are unchanged.

### The catalogue keyed by PCF id, and the parity apparatus retired

- Every activity in the process catalogue now carries the stable APQC
  `pcf_id` of the process it belongs to, in place of a hand-typed hierarchy
  hint (`3.4.1`, `5.x`). Universal streams resolve in the cross-industry
  framework; each industry overlay names its own (`pcf_framework`: banking,
  property and casualty insurance, retail, utilities, healthcare provider,
  city government), and overlays for industries APQC publishes no framework
  for resolve in the cross-industry one. A compiled binding carries the
  resolved `pcf_hierarchy_id`, `pcf_name` and `pcf_framework`; an id its
  framework does not have refuses the compile by activity name.
  `tools/check_catalogue_pcf.py` prints the join, with the function that owns
  each process beside the function the row names.
- The second compiler (`worldloom.process_planning`), the source-reference
  importer (`worldloom.process_catalogue`), the archived upload they replayed
  against (`_data/processes/`, `defaults.zip`, `coverage.csv`, the parity
  fingerprints in `bindings-provenance.json`) and their tools, tests and
  workflow are gone. The catalogue is versioned data checked against the
  shipped frameworks, not a mirror of an upload.
  `process.open_from_catalogue` takes a `CompiledCatalogue` and carries the
  stream's bindings through `authoring_brief`.
- Generation: the activity bindings that feed the industry programme and the
  `process_catalogue` connector records carry the four PCF fields and no
  `apqc` or `pcf_status`; the default corpora do not read them and are
  unchanged.

### Reference data: the PCF, O*NET and the function table

- The APQC Process Classification Framework ships as data: the cross-industry
  framework 7.4 and seventeen industry frameworks under `_data/pcf/`, each
  element with APQC's stable `pcf_id`, its hierarchy index, description and
  benchmarking metrics, and each file carrying the notice APQC's licence
  requires. `worldloom.pcf` reads them; `tools/ingest_apqc.py` writes them
  from the workbooks and refuses one without a notice.
- The O*NET 31.0 database ships as data under `_data/onet/`: 1,016
  occupations with descriptions, job zones, the titles incumbents report,
  task statements mapped to detailed work activities, and the software each
  occupation uses. `worldloom.onet` reads it; `tools/ingest_onet.py` writes
  it with the CC BY 4.0 credit line.
- `worldloom.functions` is the crosswalk between the two: every level-3
  process of the cross-industry PCF assigned to exactly one of 42 business
  functions, each function seated with O*NET occupations in manager,
  professional and support tiers and bound to the catalogue's system-of-record
  classes. `tools/build_functions.py` builds it from three authored tables
  and resolves every id and name against the shipped sources; the tests do
  the same against the shipped file. See `docs/reference-data.md`.

### Industry X, and the whole evaluation programme it implies

- `worldloom industry programme INDUSTRY OUT` (`worldloom.industry`) derives
  everything an interview used to leave to be typed: a line of business per
  function family the operating model owns (a head, a manager and an analyst
  answerable for the family's value streams as `process.<stream>` kinds,
  registered from the catalogue's own stream list), a seated request per
  situation (the seat chosen by activity type, `SEAT_BY_TYPE`, so every asker
  has standing under the same rule `evals.plausibility` applies and
  `standing_findings` proves it), a fact per declared attribute of every bound
  activity (owner, system of record, control, exception) that the request's
  expected answer names and `Request.to_case` cites, and a `ProcessLine` per
  LOB × stream carrying the derived count. `use_cases` turns each supported
  line into a Studio `UseCase` whose `count` is the line's situations rather
  than an authored twelve, with sources from the connectors that emulate the
  line's systems and channels and a construction `EvalSpec` bound to the line.
  Twelve industries, 189,346 requests, each counted where it belongs;
  `worldloom industry list` prints the table.
- `_data/process-catalogue/emulated-systems@1.json` says which systems of
  record and evidence channels a connector emulator stands in for. A product
  it does not list is reported on the line and the programme as unemulated and
  its bindings draw evidence from the declared channels only; a line with no
  emulated source is listed under `unsupported_lines` with its count intact.
  `IndustryProgramme.engine` is empty for the nine industries no engine
  builds, and the programme says so rather than dressing a retail world as a
  telecom.
- `evals.coverage.report` accepts anything carrying the request tuple
  (`coverage.Requested`), so a programme is measured before any case enters a
  world with the code that measures the world afterwards. A full programme
  uses every situation the catalogue offers.
- `industry.project(industry, name)` is a Studio `ProjectSpec` derived from
  the programme, and the Studio preset accepts any industry the catalogue
  knows: the four largest lines of business as LOBs (rooted at the chief
  executive, `industry.ROOT`, so they lint clean and ride the world), every
  supported process line of theirs as a use case with the line's count, the
  company's limitations acknowledged. The interview request carries the
  programme's headline numbers under `programme` and its instructions say a
  count is derived from a process line, never written as a round number.
- `archetypes.matched` reports whether a description named a registered shape
  at all, and `company.resolve` reads it: a retailer is recognised without the
  caveat every retail description used to carry; an industry the catalogue
  knows but no engine builds (`industry.industry_of`: overlay keys, crosswalk
  codes, sector frameworks and a declared word table, longest phrase at word
  boundaries) is reported as exactly that, naming `worldloom industry
  programme <industry>` as what does exist; an unrecognised business is
  reported as a miss.

### Eval execution: a question is a turn

- Every request in the shipped corpora was complete and safe to act on as
  written, and the turn protocol had two replies, a call or an answer. An
  agent that should stop and ask (the request is ambiguous, a parameter is
  missing, a delete needs the user's word) had no way to, and no grade for
  it. `QuestionPoint` is to clarification what `FailurePoint` is to a
  designed error: a row declares the questions its request requires
  (`question_required`: the reason, the tokens the question must mention,
  the user's reply, the nodes that may not run first; `confirm_before` on a
  delete derives one per destructive write), `ToolSurface.ask` records what
  the agent asked and where (the `ask` reply of the `worldloom.evalrun-turn/v2`
  document, the `eval_ask` tool over MCP, an `["ask", {...}]` entry in a
  responses document), the service answers from the row and never says
  whether the question was expected, and the trajectory grade counts the
  points honoured under four laws named once in `QUESTION_LAWS`:
  `acted_without_asking`, `asked_too_late`, `ignored_the_answer`,
  `asked_without_need`. One more score term beside the designed failures,
  absent when a case requires no question and none is asked, so every
  existing ledger scores as it did. The reference agent asks what the row
  requires; the questions ride the ledger (`CaseResult.questions`) and the
  summary; `axis_coverage` reports `questions_expected` and the reasons.

### Hero use cases: organise my drive, my inbox, my chats

- `worldloom enterprise-evals housekeeping WORLD OUT --kind drive|inbox|chats
  --connector ... --records N --mess --stale --duplicates` builds a corpus
  that needs tidying and the cases that grade the tidying
  (`worldloom.housekeeping`). The corpus is in the world's own words: a
  folder tree per business unit and period (Drive, SharePoint, OneDrive), a
  mailbox with subject-tagged categories and mail folders (email, Outlook),
  or a channel list per unit (Slack, Teams), with a stated share of items
  misfiled, mislabelled, stale or duplicated. Nothing on a record says where
  it should be; the rule is in the request and the ground truth in the row.
  Each case is one rule, one group of records that share a destination: a
  search bound to the rule's own predicate, a mapped write per record (a
  move, an update, an archive, a delete) and a mapped readback, in the
  executable DAG grammar and compiled through `compile_dag_row` like every
  other row. The reference agent passes every case on every connector, and
  the count is the point: a corpus of five thousand items is one flag away.
- Scoring a reorganisation. A mapped write over a pinned search now carries
  a `per_record_state` assertion (or a `deleted` one listing its records),
  graded in `grade_trace` by fid, and `evalrun`'s outcome grade holds the
  same list on `StructuredOutcome.records`: the match is the fraction of
  records that landed (`OutcomeMatch.ratio`), so three hundred files with
  one left behind score 0.997 on that expectation rather than 0.
- `SourceRequirement.bind = "predicate"` compiles a search to the
  requirement's own predicate instead of the fixture's `id IN [...]`, so an
  agent that reads the rule can search by it; the reads it must return are
  still exactly the fixture's, and the cap on a bound search rises from
  100 to the grammar's 1000, paged at the tool's page size. Off the wire
  when unset, so every existing row compiles byte for byte.
- The emulator's search under an alias entity (`file` over docx, xlsx, ...)
  matched nothing when it carried a `where` predicate, because the
  predicate kept the alias name and every member record failed the entity
  test. The pool already holds exactly the alias's members, so the
  predicate now drops the alias. The served surface's per-run call limit
  rises to 4096 so a mapped reorganisation of a thousand records fits.

### Connectors: a record can be moved, and mail and chat can be tidied

- Every file connector declared its `move_file`/`move_item` tool as an
  `update` on the folder entity alone, so `tool_for("docx", "move")` had
  nothing to answer and no hero use case (organise my drive, my inbox, my
  chats) could be planned, executed or graded as what it is. `move` is now
  a connector operation of its own (`connector_definition.ConnectorOperation`,
  the DAG grammar's write vocabulary, `enterprise_specs.Operation.MOVE`):
  Drive, SharePoint and OneDrive move files and folders between folders
  with `{id, parent}`, Outlook moves messages between mail folders
  (`move_message`) and creates folders (`create_folder`), the native email
  connector updates a message's labels and read state (`update_message`),
  and Slack creates and archives channels (`create_conversation`,
  `archive_conversation`) through the workflow its definition always
  declared. The emulator's `_op_move` re-parents the record it leaves
  intact and refuses a destination that is not a container (validation)
  or does not exist (not found). `evalrun` grades a move as an update
  outcome on the record's `parent`, and `safety` classifies it as a
  reversible, naturally idempotent mutation, never destructive.

### Packs: the organisation as pack data

- The rung of the de-hardcoding ladder left open the longest. `voices`
  proved that an engine can publish its role keys and lint against them,
  and the role table itself stayed a literal in each engine's organisation
  generator: a pack could re-voice the CFO and could not give the company a
  chief risk officer. `Pack.roles` now carries the whole table (`table`,
  in `lob.RoleSpec`'s `reports_to` spelling, a `voice` attachable on the
  row) and the posts minted per business unit (`unit_roles`), both off the
  wire when unset. The table is reviewed on the way into every builder
  (`packs.role_table_of`: `roles.review` with stand-ins for the per-unit
  posts, refused rather than warned about because a missing spine key is a
  `KeyError` mid-episode) and reaches the build as the builder's
  `role_table`; the posts reach it as a new `unit_roles` field on all four
  builders, which the banking, insurance and procurement generators now
  accept beside retail's, and the recipe records beside the table. `pack
  check` names every review rejection, a post set missing an engine
  suffix, a post the table already declares, a role voiced twice, and a
  LOB role the table does not contain; the voices, name-pool and episode
  author-role lints read the company's own keys. `worldloom pack targets
  --json` prints each engine's organisation as data (`roles.published`):
  the spine a table must keep, the shipped rows and posts to start from.
  `pack export` writes a derived role table and estate into the pack
  instead of a sidecar. Every baseline build is byte-identical.

### Procurement: an estate of its own (Generation)

- `ProcureToPayWorld` refused `--estate` outright, and three modules carried
  the sentence "`landscape.LANDSCAPES` is a closed core table with no
  registration seam" for as long as `landscape.register` has existed. The
  contractor's vocabulary is now `landscape.PROCUREMENT`, the fourth shipped
  landscape (`worldloom pack landscapes`): sourcing, orders, site receipting,
  the three-way match and the accrual it books, gated on the
  site-connectivity gateway and identity. A purchase-to-pay corpus built
  with `--estate` grows a technology graph around the five systems the
  cycle mints, owned by the people who own those systems; built without
  one it is byte-identical. The pack's `estate` and `landscape` reach this
  engine too, and `evolve` no longer refuses an estate on a contractor.
- **Generation**: the procurement mosaic (`worldloom mosaic --engine
  procurement`) regains the estate axis it dropped while the builder
  refused estates, so its variants carry one more coordinate; a
  procurement mosaic dealt before this does not replay. Every other build
  is unchanged.

### Packs: the estate's vocabulary as pack data

- `landscape.named`'s error message promised that "a pack may also supply
  pools of its own" for as long as the module existed, and no pack field
  read it; the SDK's `estate(vocabulary=)` was carried and applied nowhere.
  A pack now states `estate` (the size) and `landscape` (a registered
  vocabulary by name, or pools of its own: services per layer, systems of
  record, purposes and size profiles), both left off the wire when unset so
  every pack corpus already built embeds the exact document it did. The
  retail, banking and insurance builders carry one `landscape` field,
  resolved through `landscape.resolve` with the engine's own vocabulary as
  the default; `Blueprint.estate(vocabulary=)` reaches it; and the recipe
  records the vocabulary beside the size (`landscape`, a name or the pools
  themselves, `landscape.document_of`) so the estate rebuilds in the same
  words from the corpus alone. `pack check` names an unknown vocabulary, a
  size the vocabulary lacks, and an estate asked of an engine that grows
  none. A typed `--estate` wins over the pack's size. Every baseline build
  is byte-identical.

### Fact kinds: the engines' vocabularies as versioned data

- Retail, banking, insurance and procurement each registered their fact
  kinds as a Python literal: 115 declarations across four modules, the
  vocabulary every pack's `fact_kinds`, every LOB responsibility and every
  sheet column has to match. Each vertical's kinds now live in
  `_data/factkinds/<engine>@1.json` (`domain`, `about`, and one row per
  kind), read at import by `factkinds.register_catalogue`; the version is
  in the file name because a registry is a lineage component. A row naming
  a field the kind does not have is refused rather than ignored. The
  arguments that stood as comments beside the literals (why a diagonal is
  `never-superseded`, why `financial.accrual.grni` is procurement's)
  travel as `note` fields and as each file's `about`. The registry's
  content and order are identical to what the literals produced, and every
  baseline build is byte-identical.

### Documents: the engines' catalogues as versioned data

- Banking, insurance and procurement registered their artifact types as
  Python literals (`register_artifact_types` with standing, lag and outline
  tables) while retail's thirty had long been proven expressible as
  `doctypes` JSON. Each catalogue now lives in
  `_data/artifact-types/<engine>@1.json`, read at import by
  `doctypes.register_engine` with the compilers passed in beside it; the
  version is in the file name because a catalogue is a lineage component.
  The argument that stood as comments beside each literal (why a section is
  optional, why a type stands where it does) travels as `note` fields on
  `SectionSpec` and `DocumentType`, left off the wire when empty. Narrated
  banking, insurance and procurement builds are byte-identical.

### Documents: chapter furniture past eight sections

- A document with more than eight visible sections (`render.chaptered`,
  the same threshold that frames its writers) renders with chapters: Word
  and PDF open every section on its own page, Word's running head carries
  the current section as a `STYLEREF` field beside the title, the hidden
  sections gather under one `Appendix` heading on their own page, and the
  Markdown twin opens with a linked contents list and the same `Appendix`
  heading. The threshold sits above every outline the engines ship, so
  every existing document renders byte for byte.

### Documents: sections that repeat over units, and framed long documents

- A section plan may declare `repeat: "unit"` (`doctypes.SectionSpec`,
  `documents.SectionPlan`): one authored step becomes a section per
  business unit with facts for it, each handed only that unit's facts (the
  unit, its categories, its sites), each with `{{var:unit.name}}` resolved
  in its heading and purpose, and each its own narration request under the
  same per-section validator. A long document now grows from facts rather
  than from a longer brief. Unset, the field stays off the wire.
- Once a document has more than eight visible sections, every section's
  narration request carries the outline as standing context: the sections
  in order, and where this one sits between its neighbours, with the
  instruction to refer to another section by heading rather than restate
  it. Built from the compiled outline, not asked of a model, so no ledger
  gains a call site; the threshold sits above every outline the engines
  ship, so every existing request digest and ledger is unchanged.

### Documents: decks for any document type

- The deck renderer handled one artifact type, pinned its size class to
  `small` and its grammar to the executive summary's, so no pack could ship
  a board pack and no deck could exceed four content slides. `render.pptx`
  now composes under the intent's own type, size and budget, and a document
  type declares `deck: true` to be rendered as one (`doctypes.install`
  registers it, `registries.scoped` restores the set, `describe` reads it
  back, and the core port marks the executive summary). A deck opens with an
  agenda once it has more than six visible sections; prose that outgrows one
  slide continues onto the next at paragraph or sentence boundaries, as a
  long table already did. Every deck an old size class could hold renders
  byte for byte: the agenda threshold is strictly above the shipped
  summaries and no section they carry exceeds one slide's estimate.

### Documents: declared size budgets

- The component cap `compiler.compose` enforced per size class and the word
  brief `narrative.compiler` gave each section's writer were two literal
  tables two modules apart, with no flag, no pack field and no fourth entry;
  the longest document a corpus could carry was twelve sections of three
  hundred words. Both now read one table, `sizing.PRESETS`, which holds the
  old numbers verbatim (so every default build composes and narrates exactly
  as before) and adds `xlong` (40 components, a 420-word brief) for a report
  with chapters.
- A document type may declare its budget outright: `filing.budget` on an
  authored type and `budget` on an episode artifact take
  `{"components", "words"}` and win over the size word. The planner copies it
  onto `ArtifactIntent.budget`, so a process that only loads the corpus
  narrates and renders to it without the pack that declared it; the plan
  handshake attaches the intent's budget to every accepted plan. An unset
  budget is left off the wire of the intent, the plan and the doctype, so
  every corpus, ledger and port built before this serialises byte for byte.
- `doctypes.lint` refuses a budget smaller than the outline's required
  sections, naming the `over_budget` refusal the composer would otherwise
  raise on every document of the type.

### Generation: planned deletes in the DAG grammar

- Add the `delete_chain` shape to `enterprise-dag@1`: write, read back,
  delete that exact returned record, read it back expecting `not_found`. The
  compiled row carries a `deleted` assertion naming the write that created
  the record and a `failure_at` expecting the error on the final readback,
  so the record being gone and the readback failing are both graded. Opt-in
  through `--dag-shape`; a build without it is byte-identical.
- Serve `delete_file` on SharePoint and Drive file entities. The specs
  declared `DELETE` on both; the definitions served no tool for it, so no
  destination in the builtin registry could host a delete. `MUTATE` still
  excludes delete, so the legacy planner's output is unchanged and
  `--dag-shape '*'` now includes `delete_chain` wherever a file destination
  admits it.
- Graders learn about records that existed only during a run: the
  execution contract stops reading a deleted record's fields and entity from
  the post-state, aliases an id through the results the trace recorded, and
  skips an expected failure on a node an earlier designed failure blocked;
  the served surface attributes a readback by the id a deleted record
  answered to; the outcome axis meets a create and a delete on the same
  transient record from the spans and grounds the artifact on the write the
  service saw.

### Eval execution: three-axis agent runs

- Review findings closed: the service records every call it refuses
  (unknown tool, undeclared argument, a limit) and the trajectory axis
  counts them as attempts against precision, the budget and its pass, on
  the local and the served path alike; a mapped (`for_each`) write claims
  every record it produced rather than one, so a fan-out of creates is no
  longer collateral; `compare` computes a case's overall delta over the
  axes both runs observed and gives two runs with no axis in common no
  verdict; the summary's trajectory rates are absent rather than zero where
  no trajectory was observed.
- Add Anvil's mutation battery for the graders (`tests/test_evalrun_mutations.py`):
  each case weakens one control on a passing reference trajectory and
  asserts the score drops on the right axis. It found and closed two gaps:
  a successful write the service could not attribute to a node now counts
  as leaking past a designed failure, and an unchanged retry of the refused
  call no longer counts as honouring it (a keyed create makes that retry
  safe under Anvil's law, not honoured).
- Studio grades agents on the company's connector cases: an `evalrun` job
  (`worldloom studio evalrun`, `studio run --operation evalrun`, the
  console's Evaluations page, the workflow's next step once the queryset
  exists) runs the reference agent or the connected coding harness over
  the revision's verified dataset with lineage attached, appends every
  graded case to a durable ledger a retried job resumes from, seals the run
  with a receipt the results route authenticates, and pages per-case grades
  with what each lost on which axis. The run directory is an ordinary
  `evalrun` run, so `summarize` and `compare` read it.
- Add `worldloom evalrun plan`, `EvalSession.plan`, the `evalrun_plan` MCP
  tool and `worldloom.evalrun.plans`: the plan axis graded alone. A planner
  receives the request and the tool catalog and returns a DAG of tool calls;
  nothing executes, and the DAG is graded by tool name and dependency
  reachability with `grade_plan`'s formula. Planners: `reference`,
  `--exec <command>` (a `worldloom.evalrun-plan/v1` document per case) and
  `scripted:<plans.json>` (`worldloom.evalrun-plans/v1`, written against
  `evalrun requests --for plan`). Scores now record which axes they
  observed; a summary reports no mean and `compare` no delta on an axis a
  run did not observe.

- Add `worldloom evalrun` and `worldloom.evalrun`: run any agent against a
  compiled enterprise case set, one isolated connector state per case, and
  grade three axes separately. Plan (the DAG the request should produce),
  trajectory (order, budget, designed failures honoured, retry storms,
  Anvil's `duplicate_write`, `unsafe_retry` and `destructive_without_read`
  laws) and outcomes (records created, updated and deleted as a state diff
  with collateral writes named; artifact grounding on the pinned source
  records; a rated answer). `grade_trace`'s verdict rides beside them.
- Ship a reference agent that walks each expected DAG through the same tool
  surface an external agent gets, a scripted agent, and a callable seam. An
  agent that raises is an error row excluded from every mean. Runs are
  byte-reproducible unless `--timed` records latency.
- Adapt Gemini Enterprise Eval Studio's judge prompt, score parser (clamped,
  with "no number" as an error), latency fields and ±0.10 comparison bands;
  import its results CSV as an answer-axis-only run. Port Anvil's effect,
  risk, idempotency and closed error-code vocabulary as `evalrun.safety`, and
  expose the same MCP annotations from the service's `tool_catalog`.
- Fix `ConnectorEvaluationService` grammar attribution, which demanded an
  `entity` argument on tools that do not declare one and so could not
  attribute any email-source search made through the served surface. Add
  `spans`, `snapshot` and `tool_catalog` to the SDK path.
- The Studio interview now states that evaluation is not retrieval and asks
  which axes and write operations each use case exercises.
- Make the run drivable by any harness: `evalrun run --exec` runs an
  executable as the agent one subprocess per turn over the existing seam
  (`worldloom.evalrun-turn/v1`); `evalrun requests` writes cases and tool
  catalogs as a document a harness answers offline
  (`worldloom.evalrun-requests/v1`, `-responses/v1`); `EvalSession` is the
  SDK entry; `worldloom mcp` gains `evalrun_*` tools; `evalrun` is a declared
  seam in `worldloom seams`; the `worldloom-evalrun` skill and
  `/worldloom-evalrun` command carry the procedure.
- Close the MCP transport: the served surface snapshots state at
  `eval_begin` and gains `eval_score`, which returns the three-axis case
  result for an external agent's run; `evalrun import-served` collects those
  documents into a comparable run. Add `--rater exec:<command>`, a judge
  over the `--exec` seam (`worldloom.evalrun-rating/v1`), so the answer axis
  can be model-rated without this package importing a model SDK.

### Generation: reviewed company-data sizing

- Add opt-in data creation proposals that reuse the canonical retail inventory,
  connected replenishment and banking servicing programs. Preserve authored
  parameter values, validate execution limits and report exact planned table
  rows. Protect custom programs and ambiguous targets from silent replacement.
- Bound monthly-history sizing and require explicit acknowledgement when a
  change invalidates selected narration, native file plans, tasks and calibration.
  Earlier revisions and generated files remain intact. Existing generation
  defaults and golden corpora are unchanged.

### Studio: data, corpus and evaluation workbench

- Add **Create data & evals**, shared sizing proposals in the SDK and HTTP API,
  searchable accepted-source selection, generated file downloads and paginated
  public file-task inspection by operation, format and use case.
- Authenticate native exports before access without exposing private answers;
  distinguish requested connector queries, planned rows, generated files,
  reference qualification and observed target trials.
- Bind creation forms to company revisions and discard out-of-order source and
  query responses. Preserve explicit review before applying generation changes.

### Generation: guided native suites and bounded context selection

- Compile reviewable read, arithmetic, update and creation contracts from
  accepted company sections. Group shared facts before allocating evidence
  cases, reference-qualify actual Office outputs, and report source shortages
  instead of copying content to meet a quota. Preserve other use-case contracts.
- Add opt-in native noise candidates exposing grounded files from the same
  evidence component. Divide the total training budget before sampling, seal
  the training choice before one holdout, and retain authenticated replay.
  This measures additional-file context; it does not implement prose mutation.
- Share readiness, next actions, authenticated narration selection and native
  suite preparation across Studio, SDK and CLI. Add explicit proposal review
  and forms in the UI, plus a bounded workflow entry point in harness skills.
  Native-only tasks no longer require an unrelated connector scenario.
- Add an explicit Codex native-write option scoped to the task output working
  directory for update/create requests. Keep authoring requests read-only and
  preserve normal approval and network controls.

### Generation: native difficulty measurement and retail pilot

- Add opt-in fixed-corpus native calibration using existing empirical
  calibration observations and Wilson intervals. Seal independent evidence
  components before trials, commit the training decision before holdout, and
  require supported intervals within the declared band for every outcome group.
  Native noise evolution is not implied by this measurement.
- Add a reproducible retail pilot using actual company episodes, accepted
  reference narration and native read, calculation, update and creation tasks.
  Keep reference qualification separate from observed target performance.
- Expose native calibration contracts and results in Studio. Fix Windows
  subprocess test quoting and consume bounded rejected HTTP request bodies
  before returning the refusal, preventing connection resets hiding the 403.

### Generation: grounded native corpora and executable file tasks

- Add opt-in native corpus plans that assemble accepted company ArtifactIR
  sections into DOCX, PPTX and XLSX. Enforce content and distinct-fact quotas,
  deterministic bytes and evidence locators verified against actual files.
  Reuse canonical numeric facts in workbook cells for arithmetic evaluations.
- Add byte-bound read, analysis, update and creation contracts. Grade cited
  answers and submitted native files; updates require the original checksum
  and preserve unaffected extracted content. Retain explicit refusals for
  unsupported PDF inspection and rendered pagination.
- Add Studio Documents & files and the native run operation, sharing company
  revisions, narration, coding-harness exchanges and replay checkpoints.
  Report observed native outcomes separately from noise calibration; shared
  source evidence forms one component rather than independent samples.
- Inspect native file shape requirements against parsed Office bytes instead
  of treating requested dimensions as observed evidence.

### Generation: eval-driven company construction and measured selection

- Add opt-in Studio foundry runs that compile explicit use-case construction
  contracts, detect shared-world conflicts and bind source predicates into
  executable queries. Reuse existing recipe tactics and require domain evidence
  for scoped owners and processes. Revalidate all obligations after construction.
- Materialize declared support units without trading revenue allocation. Add a
  connected retail mechanism for lost demand, orders, two-tick receipts and
  invoice price arithmetic. Company events own the evidence projected into
  Jira, ServiceNow and email. Partial delivery, payment and ledger settlement
  remain explicit unresolved obligations. These opt-in steps change recipe,
  event, connector and fixture bytes.
- Compose narration, reference qualification, reader recovery and target-agent
  connector trials through durable checkpoints. Compare noise versions of one
  company using independent evidence components per use case and the existing
  Wilson estimator. Freeze selection before target holdout outcomes; an unmet
  gate publishes no calibrated dataset. Reference and reader quality inspect
  all candidate evidence before that selection.
- Add Studio stage, obligation, noise, coverage and measured-difficulty views,
  plus CLI `--operation foundry`. Reconstruct isolated connector effects from
  recorded proposals on resume. Target grading establishes observed connector
  contracts, not free-form answer correctness. Default generation and existing
  collection replay contracts remain unchanged.

### Generation: one-company datasets and local Studio

- Add `CompanyDatasetPlan`, separate from the existing multi-company
  collection schema. Freeze one canonical world, keep process simulation seeds
  stable, advance real case cohorts across batches, and refuse company drift.
  Task/case splits retain transitive evidence isolation; insufficient diversity
  remains incomplete instead of producing another company.
- Add a local Studio UI and shared SDK/CLI for company profiles, real revenue
  divisions, LOB roles, operating-process definitions, use cases, interviews,
  narration selection, revision history and durable generation jobs. Eval-only
  edits reuse the company; timeline additions replay and extend its history.
- Run bounded interview and narration requests through installed coding
  CLIs, custom JSON adapters or file exchange. Proposals require
  revision-bound application and never approve their own evidence. Existing
  collection plans and default generation paths retain their replay contracts.

### Generation: opt-in dataset compilation and split isolation

- Add a sealed dataset plan with exact stratum quotas, repetition caps, task
  and company minima and a finite generation budget. Deficits drive existing
  company/episode/synthesis builders; equivalent executable plans are removed
  before fixture materialization and qualified rows alone consume quotas.
- Derive task/case/request identities from executable contracts and evidence.
  Reserve admission capacity for diversity; isolate transitive shared evidence
  and task or company groups before assigning splits. Incomplete runs cannot
  emit a publishable queryset.
- Persist exact batch Worlds, fixtures, proofs and content receipts. Resume
  generates only missing batches; complete replay makes no external calls.
  Add `evals dataset compile` and `verify`, SDK composition and a measured
  retail/banking example. Existing generation paths retain their bytes.

### Generation: opt-in evidence admission and empirical noise calibration

- A shared `reader/v2` plan/check/accept boundary covers full eval-critical
  evidence in ordinary narration and program expansions. Rendered prose and
  aspects go to the reader; expected facts remain in the checker. Current
  identity, reader configuration, visibility and artifact witnesses bind the
  acceptance. Missing, ambiguous, stale and unrecoverable targets refuse.
- Accepted and rejected reviews retain responses and findings through the
  generation ledger and `NarrationReaders` recipe step. This changes opted-in
  ledger/recipe bytes; unchanged accepted checks replay without reader calls.
  Legacy reader serialization, default program generation and golden corpora
  are unchanged.
- `evals.calibration.calibrate_noise` reuses Messiness, campaign revalidation,
  reader/fidelity admission, empirical cohort estimates and Archive. Each
  variant starts from isolated baseline generator state. Finite budgets,
  uncertainty, refusals, niche holes and frozen held-out selection are recorded;
  complete records replay without external callbacks. Exports retain the
  exact selected trial worlds and split-labeled receipts.
- Newly added noise prose uses the existing deterministic template provider,
  with its own explicit authorship and ledger namespace. It is not reported as
  model-authored. Offline narration replay can resolve an explicit set of
  recorded model IDs against exact current request keys, refusing ambiguous
  matches and preserving actual authorship. CLI replay uses those recorded IDs.

### Fixed: complete fidelity populations and provenance-bound difficulty

- Fidelity slice columns retain global marginals. The full typed union census
  includes one-sided, missing, null and empty populations even when metrics are
  capped. Nonfinite numeric values cannot satisfy metric gates. CLI strict slice
  support rejects omitted or unsupported groups while retaining diagnostics.
- Difficulty calibration supports versioned eval and request features with
  intervention conditions. Trial replay is idempotent; configuration drift and
  eval/corpus split leakage refuse. Estimates expose Wilson intervals, minimum
  support and provenance. Held-out Brier/ECE retain unsupported denominators;
  legacy counts and reference executions cannot claim fitted agent difficulty.

### Generation: opt-in operational case binding and qualified coverage

- `with_operational_case_binding()` scopes enterprise queries to deterministic
  real case cohorts shared by all source roles. Bound query IDs, user-facing
  source references, source predicates and metadata change. Unbound query
  serialization and generated source records retain their existing bytes.
- `EnterpriseEvalHarness.qualify(pool_size=...)` and `enterprise-evals qualify`
  admit a bounded pool through strict source evidence, independent validation,
  compilation and executable assertions before selecting coverage. Native
  input formats require actual World artifact bytes; metadata alone refuses.
- Semantic interactions and operational cases have separate measured coverage.
  Output caps recompute holes against the requested pool. Refused candidates
  remain inspectable and contribute no witnessed coverage.
- Qualification exports keep the exact shared connector dataset, selected
  fixtures, compiled rows and execution proofs. Source native-byte receipts
  remain bound to admission; the source World retains the native files.
  Default enterprise build behavior is unchanged.

### Generation: narration contracts and calibration provenance

- `section_prose@6` and `artifact_plan@2` bind accepted authorship to the
  complete request and full fact records. Requests exclude future,
  observer-hidden and transaction-unavailable facts before external authors
  receive them. Terminology and record time now reach the JSON handshake.
- A changed cutoff, author, purpose, authority or supersession invalidates
  stale reuse even if numeric values stay equal. Accepted plans must match
  the current contract; conflicting current plans are refused. Cold narration
  replay installs planning evidence before compiling its outline.
- These identities change nonempty authored ledgers. Reaccept authoring under
  the new contract or use the prior engine to replay prior bytes; no unsafe
  fallback treats an old key as a current acceptance. Golden fixtures and the
  hand-authored grocery narration source are unchanged.
- SDK and CLI builds with calibrated priors retain content-addressed estimator
  receipts in the recipe and replay them offline. Final physics overrides
  remain authoritative. Uncalibrated builds omit this metadata.
- SDK company specifications that request policies now generate them through
  the existing domain builder, matching CLI company builds. This changes output
  for SDK specifications whose policy setting was previously silently dropped.

### Generation: candidate shape admission

- Candidate validations now serialize observed shape checks. Designs with
  unsatisfied record, artifact or thread requirements no longer emit accepted
  instances. Layout and execution constraints lacking independent witnesses
  explicitly reject as unsupported. This changes campaign manifests and
  acceptance; it does not synthesize new fixture records to make a check pass.

### Added: reuse company profiles across finalized evaluation campaigns

- `evals.candidate_builder(blueprint, pipeline)` composes the existing immutable
  company blueprint and typed stages using each candidate's planned seed.
  `evals construct --company-spec FILE --periods N` uses that same path and
  retains the company resolution and unmet claims beside the campaign.
  SDK company resolution also carries the existing policy generation setting,
  which was previously dropped between resolution and build.
- `CampaignRun.map_worlds` revalidates and rebinds transformed worlds.
  `select`, `prove`, and `export` preserve the actual candidate and construction
  provenance without invoking its builder again. All attempts remain in the
  manifest, including rejected and deliberately unselected candidates.
- `EvalCampaign.search` delegates to existing adaptive candidate feedback.
  Selection reuses measured outcome diversity. No second campaign framework,
  narrator, episode grammar or evolutionary search engine is introduced.
- Candidate shape constraints now affect acceptance. Observed record, field,
  payload, artifact and thread counts are checked; native layout and execution
  constraints lacking independent witnesses explicitly reject as unsupported.
  Plan validation rejects a plan from a different immutable eval design.
- Company, author, SDK and eval skills route to the same composition path.
  `docs/company-eval-reuse.md` records the audit, narration reading order,
  runnable example, calibration boundary and remaining implementation gaps.

### Generation: executable enterprise DAG grammar

- Opt-in `enterprise-dag@1` plans carry typed arguments, result references,
  result-dependent conditions and bounded iteration. Eight authored shapes
  exercise chains, joins, branches, repeated reads and multiple writes. Shape
  selection participates in coverage and sharding before limiting the output.
- Mapped reads require at least two source records. Conditional campaigns
  deterministically request one- or two-record witnesses. These change planned
  query identities, selected fixture inputs and exported bytes when enabled.
  The default retains the legacy trajectory. No coverage of an unavailable
  external 42-shape catalogue is asserted.

### Added: external connector execution and independent trace grading

- `enterprise-evals serve` exposes MCP StreamableHTTP connector tools with
  isolated runs, per-principal bearer authentication, bounded requests and
  responses, captured native result receipts, trace retrieval and grading.
  The optional `mcp` dependency uses SDK 2.2 APIs; the existing stdio commands
  use the same version. TLS, OAuth deployment and a live Gemini Enterprise
  integration are separate deployment work.
- Both reference and external runs use the same connector emulator and
  assertions. An exact `failure_at` contract checks the declared error, write
  effects and stopped descendants. Partial writes persist their effects before
  returning an error; an unrelated failure cannot satisfy the contract.
- Simulation retains the failure finding and distinguishes completion, a
  designed write failure, an earlier stop and a runtime exception. Grammar
  assertion grades are reported separately from legacy weighted DAG scores.
- Ambiguous joins and stale sources remain data perturbations. Their response
  policies are unimplemented and the grammar refuses those combinations.

### Generation: enterprise state, field and evidence requirements

- Drive now projects rendered PowerPoint artifacts as distinct `pptx`
  connector records. Presentation-rendered corpora gain records and may select
  different source fixtures, changing replay bytes from the prior generation.
  Existing non-PowerPoint record identities and unrendered projections remain
  stable.
- Planned mutations carry an authored target state, derived from a legal
  connector workflow transition or explicitly declared on the destination.
  Required source fields carry their canonical connector definitions through
  query export, deterministic materialization, filtering and grading.
- Fixtures pin expected World facts and, separately, content-addressed
  operational observations. Source evidence never borrows a World fact id to
  disguise missing evidence. Failure overlays name a record belonging to their
  connector and distinguish source failures from destination failures.
- Source fixtures select the declared minimum and both runtimes read that whole
  set. Create and create-path upsert fixtures cannot inherit a preexisting
  destination merely because another query updates the same entity type.
- These additions change `queries.jsonl` and `fixtures.jsonl`; required custom
  fields also change connector records. Existing plans load with empty optional
  contracts. Rematerialize legacy fixtures to obtain verifiable evidence pins.
  Seed replay is stable within this generation; it does not promise byte
  identity with the previous generation.

### Fixed: executable connector vocabulary and checked outcomes

- The bounded, interleaved 400-query reference population now resolves every
  connector operation. Email has an authored connector definition. Patch maps
  to update; upsert chooses create or update from the explicit preexistence
  requirement. File aliases resolve to the selected format before tool lookup.
- Create payloads satisfy the connector's required fields. Verification follows
  the actual created record. Alias destinations retain their artifact assertion.
  Sending email applies the authored sent state rather than creating a draft.
- State grading requires a persisted write to the declared fixture and an
  available post-state. An unchanged initial state, wrong record, or missing
  post-state cannot satisfy a state assertion. A declared, exactly matched
  partial-write failure can establish its recorded persisted effect.
- Evidence validation rejects empty placeholders. Operational evidence has a
  distinct local integrity contract; it does not claim macro reconciliation or
  independent replay of an unavailable synthesis ledger.
- `enterprise-evals space --profile` sizes the selected scenario and reports
  an exact count or a witnessed lower bound. Unused enterprise CLI and field
  manifest implementations were removed after field predicates moved to
  `ConnectorFieldDefinition`. The published `query_planning` API remains
  deprecated with its return schema preserved.

### Added: a corpus and its evaluation set can be run against Gemini Enterprise

`GoogleCloudPlatform/gemini-enterprise-eval-studio` solves the part of an
enterprise-agent evaluation that is genuinely hard and uninteresting to build
twice: reaching a Gemini Enterprise instance. Workforce Identity Federation,
OIDC and SAML, the `streamAssist` stream and its TTFT/TTFA/TTLT telemetry are
all there. What it does not do is populate the index it searches or observe the
run, and both of those are this engine's.

**Generation: none.** Nothing here builds, draws, or changes what a seed
produces. Every command reads a corpus that already exists and writes a new
projection of it.

- **`worldloom gemini-enterprise datastore`** writes a workspace as Discovery
  Engine documents in the `gcsSource` `dataSchema: "document"` format:
  `content.uri` into Cloud Storage, `structData` carrying the authority,
  lifecycle, policy, folder and supersession a two-column CSV cannot, and
  `aclInfo` carrying the drive's own readers -- which is what makes a
  permission failure observable at all. Eval Studio selects data stores and has
  no ingestion path, so without this the assistant is asked questions about a
  company nobody holds the answers for.
  - Document ids are derived from the path, not only the artifact id. A drive's
    noise copies deliberately share the id of what they copy, and importing
    them under it makes `importDocuments` read the second as an update of the
    first: the duplicates collapse, the store holds one document where the
    drive holds four, and the corpus's hardest content disappears between
    export and index with nothing red anywhere.
  - A file whose type Discovery Engine will not accept is skipped and named,
    never relabelled. `.md` to `text/plain` is a wire-type declaration and is
    fine; `.xlsx` to `text/plain` is a corrupt document that indexes as
    mojibake and degrades every query that reaches it.
- **`worldloom gemini-enterprise cases`** writes the evaluation set as one CSV
  per `EvaluationType`, each with the auto-rater instruction its shape claims.
  Eval Studio applies one instruction to a whole run, and its default asks for
  semantic similarity to the golden answer -- which grades an
  `expected_abstention` case exactly backwards, rewarding a confident invented
  answer for its fluency and scoring the refusal the case exists to reward as
  though it were an attempt. `RUBRICS` gives each shape a grader that matches
  what the shape claims.
  - Shards are capped at a hundred rows, because `csv.service.ts` truncates an
    upload with `results.data.slice(0, 100)`. Rows past the cap are not
    rejected, they are never sent, and the run reports a clean pass over a set
    it never saw.
  - A case with no `expected_answer` is left out rather than exported with an
    empty golden: Eval Studio scores a falsy golden as 0 without calling the
    grader, which is indistinguishable in the results from a model that
    answered and was wrong.
- **`worldloom gemini-enterprise score`** reads the results back and slices
  them by the structure the CSV could not carry. `processRow` builds its
  `ResultRow` from scratch, so nothing sent up beyond `query` and `golden`
  comes back down; the join is on the query text and it refuses rather than
  guesses when two cases ask the same question. A row whose auto-rater call
  failed is counted and excluded from every mean rather than averaged in as a
  zero, because Eval Studio returns `score: 0` both for a wrong answer and for
  its own grader failing.
- **What this does not do, said once here so no result implies it**: grade the
  trace. Eval Studio's stream parser keeps
  `answer.replies[].groundedContent.content.text` and discards the rest, so
  tool calls and grounding metadata never leave the browser and
  `connector_trace`'s eighteen assertion kinds have no wire to read. Every
  score this returns is a judgement about a final answer.

### Added: an evaluation case can carry a request, not only a question

An `EvaluationCase` had eleven fields and none of them said who wanted to
know. A question with no asker has no reason to exist beyond "this fact is
checkable", which is what makes a generated set read as a quiz rather than as
work: real requests come from someone, at a moment, through a channel, under
a constraint, and usually name what they want back.

- **`EvaluationCase` gains the request tuple**: `asker`, `asker_person_id`,
  `occasion`, `intent`, `channel`, `constraint`, `deliverable`. All optional,
  and serialized only when set, on the contract `CanonicalFact` already
  established for its bitemporal fields. A case with no request writes exactly
  the bytes it always did, so no corpus is rewritten, no schema version moves
  and no migration step is owed. Verified against a `git archive HEAD` tree:
  a default `build --seed 8128` is byte-identical.
- **`worldloom.evals.intents`**, forty work verbs as authored data
  (`_data/evals/intents.json`, schema `worldloom.eval-intents/v1`): brief,
  triage a queue, chase, escalate, sign off, reject with reason, reconcile,
  attest, close out, abstain and the rest. Each declares its answer shape,
  the evidence it rests on, whether it reads or writes, what a write produces,
  the mistake it is posed to catch, and which activity types it suits.
  `EvaluationType` is untouched and stays the grading shape; intent is the
  work shape, and each verb names the grading shape that checks it, so adding
  a verb never adds a grader.
- **`lob.asks_about`**, the responsibility primitive read backwards. A role
  answers for some fact kinds, so those are the kinds it has standing to ask
  about; `reports_to` extends that down the line for status and up it for the
  authority its own work needs. A join, never a table, on the same argument
  `participation` makes. Industry flavour arrives through the slots: a credit
  officer asks about covenant breaches because an edge says she answers for
  them, and nobody types a per-industry question table.
- **`process_bindings.situations`**, a binding crossed with the verbs its
  activity type admits. The compiled catalogue already declares the activity,
  the owning unit and country, the system of record, the control and the named
  exception; the cross supplies the occasion a request arrives on. The twelve
  shipped industries compile 6,975 bindings and yield 189,346 situations,
  against 103 hand-typed question keys across the four engines today.
- **The `eval_plausibility` check group**, registered from `_install` like
  every vertical's. It refuses what a corpus can be wrong about: an intent
  nothing declares, a grading shape the intent does not name, a write with no
  deliverable. Whether a seat would realistically ask a given thing is a
  judgement about the world rather than a disagreement inside it, so
  `evals.plausibility.findings` reports those as sentences in the shape
  `phrasing.findings` uses, and they never fail a build.
- **Generation**: none. Default builds, `evals construct` and
  `enterprise-evals build` are byte-identical; every field above is opt-in and
  no shipped generator populates one yet.

### Proposal engines behind the compiler boundary

- **`providers.py`**, four extension seams on the pattern `narrative.providers`
  and `actors.providers` already set: `PriorEstimator`, `SurfaceValueProvider`,
  `DetailSynthesizer`, `DomainImporter`. Each is a small `Protocol` with an `id`
  and `version`; each execution leaves a **`Receipt`** whose `key` is a content
  address over backend, operation, configuration, source, candidate and accepted
  digests, digests, never data. `accept` makes a synthesizer's proposal into
  data by refusing rows that violate a constraint and then reconciling every
  declared total by largest remainder at the declared precision. A deterministic
  fake (`EvenSynthesizer`) proves the contract with no backend.
- **`calibrate.py` / `worldloom calibrate` / `build --priors`**, physics
  ranges learned from a sensitive table under differential privacy. The built-in
  Laplace-histogram estimator clips, bounds contributions by truncation, noises
  under sequential composition and reads spans off the noised CDF. The
  `PriorSnapshot` is exactly the `--physics` overrides document plus the receipt
  and a per-column **noise-share** reading; the CLI names parameters whose
  release was more noise than signal. Noise is system entropy by default (a
  calibration is not reproducible, the corpus is) and a `--noise-seed`
  snapshot says in three places that it is not a private release.
- **`surface.py`**, postcodes, phones, registration numbers and bank accounts
  from versioned rules in `data/surface/rules.json`, every value a pure function
  of `seed / rules version / entity type / entity id / field`. Checksums are the
  issuing bodies' own (ABN, USt-IdNr, Austrian UID, UK VAT, NZBN, IBAN) and are
  tested against their published examples. `master_data` takes `"identifiers": 1`
 , the value names the rules version, every version is kept in the data file,
  and a corpus replays under the one it recorded; an un-opted register writes
  the same bytes it always did.
- **`causal.py` / `build --causal` / `worldloom causal check|trace`**, a DAG
  of named quantities with linear effects, dated interventions (`do()`) and
  drives that make a node's value an imperfection kind's budget. Distinct from
  `worldloom.synthesis`, which simulates operational records and intervenes on
  *them*: this drives the *document archive's* decay from a cause and records
  the trace on the corpus as **`causal.jsonl`**; interventions mint
  `causal.intervention` events; the `Causal` recipe verb replays byte for byte;
  the `causal` validator group recomputes every derived value from its recorded
  parents and refuses drift, over-delivery, or a missing event. Linear only , 
  `FactKindSpec.derive`'s closed-vocabulary argument.
- **`fidelity.py` / `worldloom fidelity`**, a synthetic table against a real
  one as a vector: KS and Wasserstein, Jensen–Shannon and total variation,
  cardinality and unseen share, correlation error, contingency distance, a
  nearest-neighbour two-sample statistic beside its baseline, exact-match rate
  and distance-to-closest-record against the real set's own. Per slice on
  request. No aggregate score, by design. Reads CSV, JSONL, JSON, or a corpus's
  detail table.
- **Generation**: no corpus built without `--causal`, `--priors` or
  `identifiers` changes a byte. `CORE_PREFIXES` gains `CAUSE`.
- `docs/extension-seams.md` is the contract; the SDK gains
  `Blueprint.priors()` and `Built.causal()`.

### Fixed: main was red

### Added: the eval drives generation

- `construct_candidate` executes one tactic per demand the eval design
  compiles to, instead of one: connector witnesses with one near miss per
  constrained field (`eval_witnesses`), the write step's precondition record,
  artifact families, access policies, events, and revision chains. Every
  construction is a recipe verb, so a constructed candidate rebuilds from its
  own recipe; the validator that accepts it knows nothing about the
  constructions. A demand no tactic can honour comes back as a finding naming
  the seam that owns it (a fact belongs to an episode).
- Witnesses are world events projected through the same connector registry the
  validator, the emulator and the exporters read, and a connector that has a
  definition but no engine projection (Teams, Slack, OneDrive) is now
  constructible and searchable.
- `EvalCampaign.construct`, `export(construct=True)` with the constructions in
  the manifest, and `worldloom evals construct design.json --out DIR`.
- `emulator_executor`: a reference executor that runs each step through the
  emulated connectors, so a campaign's proof is about the corpus and the
  emulator together.

### Added: a connector is not a file format

- File connectors (SharePoint, Drive) project one record per artifact *and*
  format once the world is rendered, under the definition's entity for that
  format, carrying the rendered file's path, size and hash; `get_file` serves
  the mime type and the hash. Before rendering, the one planned item per
  artifact it always was. `file_formats(connector)` names what a connector
  holds. A demand for a format is constructed by rendering it.

### Changed: the name is worldloom, and the prose reads like a person wrote it

- The package's home is `github.com/vamsiramakrishnan/worldloom`; the README,
  the docs site base path, badges and clone commands point there. The first
  release ships from PyPI as `worldloom`; `RELEASING.md` carries the order of
  operations.
- `tests/test_prose_style.py` gates every user-facing document, the generated
  CLI reference and the docs site against the tells of model-written prose
  (the em dash as a universal joint, a stock adjective of praise, a vendor's
  name), and
  the CLI's own output lines follow the same rule. About 1,400 sentences
  across 110 files were rewritten to pass it; no command, flag, path or claim
  changed.
- `worldloom enterprise-evals space` reports a floor (`at_least`) instead of
  crashing when the space exceeds the ceiling.

### Fixed: main was red

- `EvalRevisionFamily` and `EvalDemands` are registered recipe verbs. Both
  were recorded on every world the eval-first tactics touched and registered
  nowhere, so recording them was itself the failure and no such corpus could
  have replayed; the one-shot workflow meant to patch the verb into
  `recipe.py` never ran. Both register from their own modules through
  `register_step`, import unconditionally from `_install()`, and replay
  (`tests/test_eval_construction.py`, `tests/test_eval_interventions.py`).
- The connector emulator resolves the native ids it emits. A search page's
  `id` handed to the next tool, which is what a real trace does, was refused as
  `not_found` by the emulator that had just returned it.
- `worldloom seams` is documented and the generated reference is current.

### Removed: one-shot branch workflows

- Twenty-two workflows scoped to merged-and-deleted `codex/*` branches (the
  `artifact-realism-*` apply/fix jobs, the eval-contract repair gates, the
  source snapshot and the vocabulary harvests), the never-applied
  `finalize_process_catalogue.py` migration and the b85 catalogue chunks it
  would have switched to. The tools the harvests drove stay in `tools/`.
  `process-catalogue-check` is a read-only check on main; `process-bindings-check`
  no longer names the deleted branch.

### Generation: reusable narration programs

- Add opt-in family-level prose authoring and deterministic clause expansion. Existing per-instance narration remains unchanged.
- Persist program sources and clause dependencies in the normal ledger and restore them during recipe replay. Bound-fact changes invalidate only dependent expansions.
- Enforce measured near-duplicate budgets and optional blind-reader findings through existing claim validation. Expansion and replay make no model calls.

### Generation: canonical bitemporal views

- Add opt-in observer, source and transaction-time fields to canonical facts.
  Unset fields retain legacy serialized bytes. Explicit latent channels do not
  leak into employee views; late corrections cannot enter earlier narration.
- Historical predicates and bounded joins share a frozen query context.
  Missing fields are distinct from null; booleans are not numeric witnesses.
  Unsupported historical construction refuses rather than inventing state.

### Generation: artifact ecology v1

- Opt-in `artifact_realism=ecology/v1` changes native artifact metadata, style
  selection, connector lifecycle history and output bytes for a fixed seed.
  PDF outputs persist machine-readable realism, lifecycle, revision and family
  markers. Recipes record replayable metamorphic noise transforms.

### Added: source-backed process catalogue

- `worldloom.process_bindings` compiles the supplied 12-industry catalogue into
  typed company activity bindings, lexicon records, process-authoring briefs and
  a read-only connector dataset. The installed module CLI and the checkout
  `tools/compile_process_bindings.py` wrapper share the same compiler.
- Preserve all 6,975 supplied bindings and all 215 original coverage cells.
  Surface the missing utilities billing definition as an additional coverage
  cell. Treat the 63 source-labelled calibration cells as unresolved targets,
  not measured priors. Keep APQC IDs as hints and the input license as NOASSERTION.
- Export 55,800 authoring demand slots, with ownership oracles only for exact
  structural bindings. Other templates require runtime state, controls and
  executable eval construction. Source and export commitments support offline
  parity checks and full replay, including projected files.
- Generation compatibility: opt-in namespace `worldloom.process-catalogue/v1`.
  Existing World recipes, operational programs and golden corpora are unchanged.

### Fixed: constructive predicate witnesses

- `satisfy` no longer treats a missing field as a constructed witness for
  `ne` or `eq null`. Explicit existing values still use the shared evaluator;
  absent fields must be materialized by a valid construction or a caller's
  domain alternative. Existing predicate tests now pass without weakening
  matching semantics or manufacturing a status value.

### Fixed: artifact lifecycle source contract

- Artifact ecology resolves timestamps, versions and state from the compiled
  manifest. A missing or mismatched manifest is an explicit refusal, not an
  access to fields that ArtifactIntent does not define. Existing compiled
  artifact lifecycles are unchanged.

### Generation: opt-in authored process planning

- Integrate the supplied 12-industry factors with typed company, owner, country and system bindings, named-stream channel draws, source-attested lexicon records and pinned offline replay. Existing world builds and the source-reference catalogue API do not change.
- Feed activity context into the existing process authoring cascade without bypassing its validation gates. APQC references remain hints; calibration names remain requests; template pairs are not executable evaluations.
- Expose missing streams, fallback owners and unresolved system schemas. Retain source hashes, licence declarations, coverage and replay manifests.


### Added: operational relational synthesis

- Opt-in `worldloom.synthesis` SDK and `worldloom synth` commands. Frozen,
  typed causal programs generate related entities and lagged state with keyed
  noise, integer arithmetic, hard constraints and operator-owned work limits.
- Retail inventory/replenishment and banking loan-servicing programs. Paired
  interventions preserve identity and exogenous noise. Streaming exports carry
  replayable recipes, checksums and counts; verified shard merges reproduce
  unsharded bytes. Completed shards can be resumed without trusting markers.
- Quality-diversity parameter search measures behavior, retains niche champions
  and audits held-out seeds. Candidate code cannot alter the evaluator.
- Designer/critic executable teams share measured feedback and a bounded archive.
  Immutable receipts support checkpointed reuse and offline, no-process replay.
- Grounded operational case projections, industry-specific enterprise query
  profiles, and strict source mode that refuses missing source records.
- Skill, operator documentation, invariant, counterfactual, replay, search,
  executable-contract and enterprise integration regression tests.

### Fixed: reference narration build contract

- CI and the reference README explicitly select the historical outline settings
  expected by the authored grocery narration. The prose and acceptance rules are
  unchanged. A new CLI integration test pins this path, not only the SDK path.

### Generation compatibility

- Existing World recipes, default World generation and golden corpora are not
  changed by operational synthesis. Its recipe namespace is
  `worldloom.synthesis/v1`. Strict enterprise source admission is opt-in.
- The operational simulators are declared assumptions, not statistically fitted
  customer models. They do not imply privacy guarantees or reconciliation to
  an attached World's macro financial totals.

### Added: a real-model writer behind the agent seam

- **`tools/model_narrator.py`** turns a coding harness's headless CLI
  (`--backend claude` or `--backend codex`) into the stdin/stdout child
  contract: request document in, responses document out, rejections fed back
  unchanged on the next round. The backend sees only a self-contained prompt
  built from the harness's own rules and facts, with no Worldloom types and no
  corpus access. Output parsing tolerates fenced or
  chatter-wrapped JSON by scanning for the balanced `responses` object.

### Added: an agent command can write for a whole mosaic

- **`mosaic --narrate-exec COMMAND`** narrates every world through an agent
  command of your choosing instead of the deterministic provider: the command
  runs once per section with a request document on stdin and must print one
  responses document on stdout. That is the same child contract `narrate loop --exec`
  speaks, so one adapter (a wrapper around any writer that reads stdin and
  writes stdout) drives both surfaces unchanged. `tools/exec_agent.py` ships as
  the reference adapter: no model, key or network, and the contract drives end
  to end.
- The exec-backed provider (`narrative.ExecProvider`) rides the existing
  `World.narrate` seam rather than beside it, so everything the mosaic already
  guarantees about narration holds for agent prose too: ledger entries keyed by
  the writer's id (`--narrate-model-id`, so a corpus records who wrote it),
  checkpoint resume via `on_accepted`, `--narration-concurrency` fanning
  sections across concurrent children, and per-section retry with the violation
  text fed back to the child. Rejections come back to the agent as feedback;
  nothing is repaired locally.
- Refused before anything lands on disk: `--narrate-exec` with `--no-narrate`
  is a contradiction (refusal code `narration_conflict`). A child whose stdout
  is not JSON dies in `run_exec`; valid JSON of the wrong shape is refused by
  the provider layer with the child's stderr tail attached.

### Generation: corpora stop being clones of one document and one brand

Five small dials, turned together, aimed at what a six-period corpus reads like
rather than at any one mechanism: **variety** (documents of a type stop sharing
one shape wherever the type gives them room to differ), **diversity** (names no
longer repeat from pools sized for a demo), and **length** (sections asked for
telegrams now ask for prose). Measured on the reference six-period retail build
(seed 8128): 11 → 13 distinct document shapes across 30 compiled artifacts,
unique-shape ratio 37% → 43%, repeated shapes 93% → 87% of artifacts. The
per-period close calendar is still an exact ×6 clone: its sections are all
required and it ships one variant, so every mechanism here declines to touch
it by construction. Types with optional sections, several variants, or room to
recombine are where the difference lives.

- **The structural genome is on by default at the CLI.** `worldloom build` now
  passes `--section-omission 200 --outline-synthesis 300 --variant-bias 1`
  unless told otherwise, so an unflagged build's documents vary in which
  optional sections they carry, in shape drawn from the company's own types,
  and in which authored variant they take, instead of emitting each type's
  outline identically, every period. All three mechanisms are coherence-safe by
  construction (required sections always survive; synthesis must carry at least
  what the authored outline carries; variant bias only rotates variants a type
  ships), and the genome is recorded on the recipe, so replay is byte-exact and
  older recipes without the key stay classic. Pass three zeros for the
  historical corpus.
- **Narration briefs lengthened ~55%, measured at the pin:** `target_words`
  small/medium/long 70/130/200 → 110/190/300 (`narrative/compiler.py`), with
  `NarrativeRequest.target_words`'s standalone default aligned at 190. Longer
  briefs pull more optional facts per section (the deterministic provider's
  evidence budget scales off this number), and that is the whole of the
  retrieval-hardness move recorded in `tests/test_retrievers.py` (numerical
  comparison 5/8 → 4/8): holding briefs at the old numbers while pools widened
  reproduces the old score, so documents demonstrably cite more of the
  corpus, not just more words.
- **Company-name pool tripled** (`generators/names.COMPANY_FIRST`, 15 → 45):
  fifteen first words meant a mosaic of tenants shared one branding vocabulary.
- **Site-name pools doubled per locale** (`locales.py`, four presets, 6 → 12
  cities each): six names could not carry a national estate. Real place names,
  geography rather than branding, keeping each preset's existing cross-border
  entries (Auckland/Wellington, Wien/Zürich).
- **System-name pools widened** (`names.py`: ERP 6→10, MDM/PLATFORM/COMMERCE/
  POS 4–6 → 6–7): a company whose every system was named from a four-deep list
  read as procured from one vendor fair.

**Breaking for reproducibility:** a fresh build from the same seed produces
different documents than before the change: different shapes (genome), names
(pools), and narration briefs. Existing corpora replay byte-for-byte: the
genome travels in the recipe, facts and ledgers travel in the corpus, and
nothing here touches either. The golden `examples/retail-close` corpus is
hand-authored and unaffected.

### Generation: every format reads the style genome, and the genome gains a typeface

- **The style genome now reaches every renderer.** `render/pdf.py` (Helvetica
  end-to-end, hardcoded palette), `render/html.py` (a generic grey stylesheet),
  and `render/xlsx.py` (grey `EEEEEE` headers) were the three formats that
  still decided their own look. They now derive the same world-seeded
  `StyleGenome` `render/docx.py` and `render/pptx.py` already read (fills,
  text colours, type sizes, spacing, density, gridline policy, rule weight,
  title alignment), so one world's memo, deck, PDF, HTML twin, and workbook
  cannot disagree about the company's own identity. PDF additionally gains
  genome-driven table rules per `gridline_policy`/`rule_weight` and
  genome-scaled cell padding; HTML gains the negative-figure colour the other
  formats already carried as colour-is-the-second-signal.
- **A fourth axis: `typeface`.** The genome samples one of four curated
  families, `house_sans` (the shipped look), `editorial_serif`,
  `engineering_mono` and `director_serif` (serif display over sans body), drawn
  from its own named `Rng` stream, so no existing draw reshuffles.
  `render/fonts.py` is the one resolution table: base-14 families for PDF,
  OOXML names or theme-default `None` for Word/PowerPoint/Excel, CSS stacks
  for HTML. `house_sans` is inert in the theme-bearing formats (no font name
  set at all) and resolves to Helvetica only in PDF, where reportlab has no
  theme to inherit.
- **Breaking for reproducibility:** a world whose sampled genome draws a
  non-house family now renders different bytes in every format, and the
  genome-driven colours/sizes change PDF, HTML, and XLSX bytes even for house
  palettes. Existing corpora replay identically under their recorded version;
  re-rendering under the new version re-skins them.

### Generation: AlphaEvolve balances evolutionary search without evolving truth

- Added a checkout-only `evals/alphaevolve` portfolio following a strict
  current-policy → restricted search → holdout/adversarial → reviewed-source
  integration loop. Managed execution uses the official client, is bounded,
  and refuses to start without `--confirm-spend`.
- The first seam is `evolve._propose_children`. Its prior value-only rank could
  mutate a wide axis repeatedly while narrower axes remained untouched. The
  reviewed policy now ranks the least-varied axis first, then the least-seen
  value, then the existing content-addressed tie key.
- Coherence validation, recipe replay, fleet fitness, and fact/generation
  ledgers are protected oracles: candidates cannot see or change them. The
  local gate freezes 64 search, 37 holdout, and four adversarial cases and makes
  no realism, retrieval-quality, managed-winner, or billed-cost claim.

### Generation: a document type may argue its case more than one way

- **`documents._OUTLINE_VARIANTS`.** A six-period corpus produced **32 distinct
  shapes across 249 artifacts (13% unique), largest group 37**, and every
  near-duplicate group was exactly ×6: the same document once per period, the
  same headings in the same order. Six close calendars with different dates is
  realistic; six root-cause reviews with an identical five-section skeleton is
  not, because real reviews differ when the incidents do. Now **40 shapes (16%
  unique), largest group 18**.
- Six types carry alternatives: `unit_close_commentary` (3),
  `incident_rca`, `executive_summary`, `performance_review`, `one_to_one_note`
  and `job_requisition` (2 each). Each alternative is a different **argument**,
  never a reshuffle. An RCA that opens with the cause is a different document
  from one that opens with the timeline, and a test refuses two variants whose
  sections differ only in order.
- **Rotated by ordinal, not drawn.** N instances over M variants land evenly by
  construction; a seeded draw would only *tend* to spread and would happily give
  six documents one shape on an unlucky seed, the exact failure being fixed.
  The first variant is the outline that shipped, so a type's first instance is
  byte-identical and only later ones move.
- `examples/grocery-close/narration.json` (real model prose, checked in) is
  **rewritten** for the three sections the rotation changed rather than the type
  being left alone. A reference narration should stay current, and a document
  type nobody varies is worth less than the work of keeping it.
- Retail's default build and the grocer differ by that rotation, which is the
  intended change; banking, insurance and procurement are byte-identical, having
  no variants on their own types.

### The corpus as a drive, not a folder of numbered files

- **`worldloom workspace`.** A corpus exports to one flat `artifacts/`
  directory of `art-0001-…` files with **identical filesystem permissions on
  all 293**. That is right for the harness, which reads the manifest and never
  looks at a path, and wrong for what the corpus is for: an enterprise
  assistant indexes the folder, the title, the owner and the sharing, and path
  and title carry a large share of retrieval signal. The corpus knew every one
  of those and put none of them on disk.
- Measured on a six-period, eight-division build: **249 files across 52 folders,
  four levels deep, 224 restricted, 44 distinct owners, 6 superseded pairs.**
- Documents are shelved by the function that owns them (`Policies/`,
  `Finance/Close/2026-03/`, `Technology/Incidents/`, `People/Performance/`),
  with periodic types filed under their period and standing types at the top of
  their shelf. Filing a policy under a month would say it expired with the
  month.
- Filenames carry the **subject** where the facts agree on one, so a month's
  reviews read `Performance Review - Sian Vance 2026-07` rather than `(2)`
  through `(5)`, and divisional commentary reads `Unit Close Commentary - Fuel
  and Convenience 2026-03`. They carry the period too, because the commonest
  way a real document loses its context is being lifted out of its folder.
- A policy revised in place sits beside its replacement as
  `Expense Policy (superseded)`, and the **live** one keeps the clean name.
  Marking ran after names were claimed at first, so the retired policy took
  `Expense Policy.md` and the current one landed as `Expense Policy (2).md`:
  backwards, and the mistake a reader would act on. A monthly
  calendar that supersedes last month's is *not* marked, because that is the
  ordinary life of a periodic document; the edge is recorded either way.
- **`permissions.jsonl`** is one row per file: path, title, owner, every
  address permitted, policy label, created date, and the successor where there
  is one. Addresses are derived `first.last@company.example` with collisions
  broken the way a mail administrator breaks them. An unrestricted policy lists
  *nobody* rather than everybody, which is what a real ACL means by "inherit".
  A tree with no permission table tests retrieval and cannot test access.
- Nothing is invented and nothing moves: every folder, title, owner and reader
  is derived from the manifest, the roster and the access policies, the corpus
  itself is untouched, and an unrendered corpus is refused by name rather than
  laid out as empty folders.
- **`--noise none|lived_in|neglected`** makes the drive untidy the way real
  drives are: `Copy of X`, a document dragged into `Shared/` or `_Inbox/`,
  somebody's `X FINAL` beside the real one, an `_Archive/` leftover. Measured:
  249 files become **336, of which 87 are labelled junk**, evenly across the
  four kinds.
- Every extra file is a **byte-identical copy of real corpus content**, never
  invented text. A drive's junk is not fabricated documents, it is the same
  documents saved again in the wrong place under the wrong name, and that is
  what makes it hard: a retriever cannot tell the copy from the original by
  reading it. A copy carries the permissions of what it copies, so a misfiling
  is somewhere nobody would look and still readable only by the people the
  original was.
- Every junk file is **labelled** in `permissions.jsonl` with its kind and what
  it duplicates. That is the difference between this and simply making a mess:
  a benchmark scored against a drive it cannot account for cannot tell "found
  the wrong copy" from "was wrong". Seeded off the world, so a corpus's drive is
  the same drive every time; distractors that moved between runs would not be
  a benchmark.
- Filesystem noise, distinct from `--messiness`, which is content
  noise. A stale page is wrong; a duplicate is not wrong at all, it is merely
  there twice. A realistic archive wants both.

### Generation: the month-end model was empty in every multi-period corpus

- **`documents.finance_workbook` took its reporting month from the world rather
  than from its own facts.** `compile()` compiles every intent against the world
  as it stands *now*, so in a two-period corpus March's workbook was looked up
  at April: every measure lookup missed and the month-end model (the corpus's
  system of record, the document every other one reconciles against) rendered
  with **every cell empty**. Measured: a one-period build's Business Unit P&L
  carries 28 of 28 values, a two-period build's carried **0 of 28**, and the
  Store Performance sheet vanished entirely because it is gated on the period
  having site facts. Single-period builds are byte-identical either way, which
  is why it survived: every fixture, example and default build has one period.
- **`validate.compiled_evidence`**: the check that would have caught it.
  `unreachable_answer` reads `required_fact_ids`, the *plan*, and has to,
  because at step 3 nothing is compiled. The moment a corpus is compiled that
  becomes the weaker claim, and the gap between them is where this hid.
  Measured on an eight-division, six-period build: **6,185 facts planned into
  documents and 1,718 actually carried**, with 55 of 479 evaluation cases
  citing evidence in no document, and `validate` reporting clean. After both
  fixes: 6,071 carried and **0 unanswerable cases**.
- **The reserve triangle showed one valuation.** Found by the new check the day
  it existed: the prior-valuation ultimate was required by the workbook, cited
  by the insurer's own first evaluation case ("as at the 2026-03 valuation"),
  and carried by no compiled document. A triangle whose estimate sheet has one
  column is not a triangle: the subject of that whole episode is that an
  ultimate *moved*. Both valuations now appear per cohort, as the book-position
  sheet already did for the totals.
- The diversity floor drops 8 → 7, and the eighth shape was the bug: two empty
  workbooks composed differently from the populated one and were counted as
  variety. A corpus is not more varied for having two of its thirteen documents
  broken.

### Line management produces documents

- **`worldloom.workforce`**: the organisation was modelled in full and used as
  a source of *bylines*. A 420-person retailer named **24 of 444 people**
  anywhere in its corpus; a manager three levels down existed, had a name, a
  function and a manager of their own, and appeared in nothing. Two rounds fix
  it: `--hiring N` raises, approves, offers and fills N vacancies a period, and
  `--reviews N` reviews N people. Five artifact types, ten fact kinds.
- The hiring manager and the reviewer are drawn from **everybody with a direct
  report**: 73 people on a synthesised 420-person company against the dozen the
  role table names. Measured on a three-period build: artifacts 113 across 28
  types with no type above 21%, and **41 distinct people named in 37 distinct
  titles**, against 24 before.
- **A requisition reads the company's own rules.** Its three-year commitment is
  checked against the delegation of authority (`worldloom.policies`) and the
  lowest rung that covers it signs, so "was this approved at the right level"
  is the first question in this repository whose answer is in *neither document
  alone*. Annual cost was the first rule and made the ladder say nothing: every
  vacancy costs under 110,000 fully loaded and the second rung starts at
  230,000, so every requisition went to the same person. A corpus built without
  `--policies` still hires, and the requisition says "no written delegation" in
  as many words.
- **Two performance records disagree on purpose.** The signed review is an
  approved report countersigned by the manager's own manager (the corpus's only
  three-person document), and the running one-to-one note is an unofficial note
  carrying the view held before calibration. Every authority-resolution case
  here before now was about an incident; a rating is the same shape and reaches
  the whole organisation.
- **A fifth access class**, minted on first use rather than at build so an
  un-opted corpus keeps the four policies it had. An offer letter states one
  person's salary and a review states their rating; "all staff", "finance and
  audit", "executive committee" and "technology" are all wrong for a readership
  of one person and their line, and falling through to the narrowest locked the
  *author* out of what they wrote: `validate.author_cannot_see_own_artifact`,
  the first time this ran. Widened rather than replaced on a second round,
  through the `access_policies` seam `personnel.promote` opened.
- **`policies` is a specification field**, not only a flag. A description of
  what kind of company this is legitimately says whether it writes its rules
  down, and `--spec` refuses the flags it subsumes.
- **`evaluation._Taxonomy.workforce`**: a `cross_artifact` case whose answer
  needs the requisition *and* the delegation, and an `authority_resolution` case
  over the two ratings. They arrive one period behind the rounds, which is the
  same lag every cross-episode family already has: a corpus cannot ask about a
  document it has not planned yet.
- Off by default at zero, byte-identical against HEAD for the default build and
  all five archetypes, and a corpus with two rounds a period over two periods
  replays byte-identical from its recipe.

### The paperwork a company has, rather than the paperwork it produces

- **`worldloom.policies`**: every document in this corpus was *episodic*: a
  close ran, an incident happened, a return was filed. Measured on a
  twelve-period, eight-division build: 195 artifacts, of which 96 were the same
  type with a different division's name on it, and **not one was a policy**. An
  assistant asked "what is our expense approval threshold" or "how long do we
  keep contracts" had nothing to find, because the company had no rules.
  `--policies core|full` gives it ten: a delegation of authority, a code of
  conduct, business continuity, expense, travel, leave, remote work,
  information security, data retention, procurement.
- **A provision is a fact, not a sentence.** "Receipts above 90 need a
  manager's approval" is minted as a `CanonicalFact` with a number in it, so
  every question this repository can already ask of a figure (what is it, when
  did it change, which document says so) works on a policy unchanged. Forty-
  eight `policy.*` kinds are registered in `factkinds` like any other.
- **Scaled off revenue**, and rounded to a figure a policy would really name,
  so a 7.8bn retailer and a 2bn insurer do not share an expense limit. A
  delegation-of-authority ladder that stops climbing (two rungs a decimal place
  apart rounding to the same figure at a small enough company) is refused
  rather than clamped.
- **A revision is supersession.** The expense policy is the one revised entry
  in the shipped library: the earlier threshold's validity window closes, the
  later fact records what it superseded, *and the earlier document stays on the
  shelf* with the current one `supersedes`-ing it. Minting only the closed facts
  was not enough and the corpus said so: `evaluation.answerable` dropped the
  question about the old figure, correctly, and that drop is what found it.
- Dates are **clamped forward of whoever signs**, never back, which is
  `form_units`' rule about a unit and its leader.
  `validate.author_not_yet_employed` found the violation immediately: a
  superseded policy dated five years back signed by a controller who joined
  three years ago.
- **`documents.extends_outline`**: a third kind of compiler. One that builds
  its IR from nothing (a workbook, a thread) must have no outline beside it or
  the outline is dead data; one that *composes* the outline, as
  `policies._provisions` does by inserting a resolved provisions table, has an
  outline that is live. Marked on the function, because the two are the same
  callable shape, and `tests/test_doctypes.py` holds the line per-compiler so a
  from-scratch compiler that grew an outline by accident still fails.
- **`evaluation._Taxonomy.standing_documents`**: the questions an assistant is
  actually asked. Retail's set moves 30 → 44 with `--policies full`: eleven
  direct lookups whose wording is stated on the clause itself
  (`policies.Clause.asks`), one `authority_resolution` about who signed the
  rules, and one hard `temporal_state`: what the threshold was before the
  revision, where the current document is the confident wrong answer and only a
  validity window tells them apart.
- Registered at **package import**, not lazily from inside `build()`. It was
  lazy first, and `tests/test_doctypes.py` passed alone and failed in a full
  suite: `documents.declared_types()` returning two different answers depending
  on what had run before it, which is exactly the import-order determinism bug
  `register_artifact_types` warns about.
- Off by default: `applied(world, None)` returns the same object, every default
  build and all five registered archetypes are byte-identical, and a policy
  corpus replays byte-identical from its own recipe.

### The organisation is shaped like its management

- **`roles.from_shape`** dealt spine keys into levels in sorted-key order and
  gave each whichever parent the rotation reached, throwing away the reporting
  lines the engine's own table already declares. Retail's four Technology keys
  sort early and landed at depth 1 with enormous subtrees; its
  ServiceOperations keys sort late and landed at depth 2 with almost none. A
  420-person retailer came out **159 technologists to 14 service operators**:
  the function mix of the whole company decided by alphabetical order. It now
  reads 140 Finance, 128 Technology, 82 Merchandising, 42 Audit, 27
  ServiceOperations, 1 Executive.
- A spine key is placed at the depth its *own* manager chain implies, under
  that manager. `svc_desk` reports to `svc_lead` reports to `cio` again, and
  where a declared manager is not in the spine at all (`svc_lead` is in
  retail's shipped table and not in `SPINE`) the walk climbs to the nearest
  ancestor that is.
- A per-unit key is in no shipped table, so this function now states their
  structure: the division's MD reports to the chief executive and everyone else
  in the division reports to their MD, which makes **each division a subtree**.
  Deliberately not the dotted line the engines declare (retail's `_bp` reports
  to the group controller) because a synthesised organisation has one line per
  person and the one that makes a division legible is the solid one.
- A full manager pushes a report **down a level rather than refusing**. The
  chief executive takes the CFO, the CIO and one MD per division, so a span of
  three with four divisions cannot seat them all; an organisation whose top is
  wide adds a layer, it does not fail to exist. Widest span still never exceeds
  what the caller claimed.
- Every default build and all five registered archetypes are byte-identical:
  they use their engine's own table and never call this. A mosaic of three
  worlds validates clean, and a widened synthesised corpus replays
  byte-identical from its recipe.

### Somebody signed it

- **`ArtifactIntent.approver_id`**: every document in this corpus was authored
  and none of them was approved, which is not how a company works and, more to
  the point, is not how a company's *archive* works. "Who approved the March
  pack for Fuel and Convenience" is a question every real reader asks and no
  artifact here could answer. A signed document now carries an **Approval**
  block (prepared by, approved by, name, role and date) in Markdown, DOCX,
  PDF, PPTX and as a worksheet in XLSX.
- Measured on an eight-division retailer: **10 distinct people** named across
  the corpus before, **19** after. The divisional close commentary is the one
  approval that fans out with the company: widen a retailer to eight divisions
  and eight *different* managing directors sign eight different documents.
- Who signs what is a per-vertical table (`_APPROVED_BY` in each planner),
  because who signs a prudential return is an argument about banking. All four
  now have one: retail's close, banking's capital return, insurance's contested
  reserve position (the actuary's report over the CFO's signature, the CFO's
  margin memo over the actuary's), procurement's match exception.
- **Absence is a claim.** A ServiceNow ticket has an assignee, an email thread
  has a sender, a calendar is issued rather than approved, banking's RWA working
  paper is unsigned *because* it is the contested-authority distractor, and
  internal audit's review carries the Chief Internal Auditor's name and no
  countersignature at all. A corpus where everything is signed is as unlike a
  real archive as one where nothing is.
- **`validate.approvals`**: a signature has to be one somebody could have
  given: the approver exists, is not the author, and is permitted by the
  document's own access policy. It found two real defects the day it existed.
  Eight divisional MDs were signing finance-audience documents the policy would
  not have let them open, and the CEO was signing a technology-audience
  remediation review for the same reason; both policies now name them, the
  second as a rule (there is no restricted document a chief executive may not
  read) rather than as a patch.
- **Access follows the post.** A reorganisation moved a division's title
  without moving its access, so the corpus recorded a signature from somebody it
  also recorded as unable to open the document. `personnel.promote` now carries
  the post's access to whoever holds it, *added* and never substituted, because
  the archive is historical and the policy is current state, and striking a name
  off today would retroactively invalidate every signature that person ever
  gave. Measured: substituting produced five violations on a six-period history
  where appending produces none.
- A signature block is **furniture, not content**: fully resolved at plan time,
  no prose to write, identical in a document that said the opposite. So it costs
  the narration loop nothing and is exempt from the size-class component budget
  (`compose._FURNITURE`): counting it refused to compose a `meeting_minutes`
  that had not grown by a single sentence.
- Baseline retrieval moved 23 → 22 at @5, `numerical_comparison` 6/8 → 5/8. Two
  names and a date per document is more text to rank against and no more of the
  text a figure question wants, so the corpus got harder for a keyword baseline
  by getting more like a real archive. A signature block that made retrieval
  *easier* would mean the baseline was matching on furniture.
- No default moved that was not meant to: a corpus with no approvals renders
  exactly as it did, `validate.approvals` scores zero out of zero on it, and a
  signed corpus replays byte-identical from its own recipe.
- **And the corpus asks about it**, because a document property nobody asks
  about is decoration. Four cases per episode (`evaluation._Taxonomy.
  approvals`): who approved a group document, who approved *and* who prepared
  one division's commentary out of eight near-identical ones, and (the one
  that makes absence testable) who approved a document nobody signed, which
  must come back as an abstention. Retail's set moves 42 → 46,
  `authority_resolution` 3 → 6, `expected_abstention` 9 → 10. The keyword
  baseline passes none of the four, which is the intended result: a baseline
  that could tell an author from an approver would mean the two were not
  distinguishable in the first place. The byline is the trap: a document names
  its author at the top in larger type and its approver in a table at the foot,
  so a test pins that no expected answer is ever the author's name.

### A synthesised role reports to somebody who does its job

- **`roles.from_shape`** dealt each role's function by position in the tree and
  each role's manager by position in the level, and the two had nothing to do
  with each other. Measured on an eight-division retailer: **319 of 407**
  synthesised people (78%) reported across a function boundary. It produced a
  "Head of Audit" reporting to a Merchandising Systems Analyst and a "Head of
  Executive" reporting to a platform lead. Now 0 of 407.
- A role the synthesiser invented takes its **manager's** function. Inheritance
  rather than "pick a same-function parent", because choosing the parent by
  function unbalances the spans (a function with two managers at a level would
  take a third of the tree), and `measure`/`review` check the widest span
  against what the caller claimed, so a shape accepted yesterday would be
  refused today. The tree's shape is untouched reporting line for reporting
  line; only the labels move.
- Two exceptions keep `functions` a real knob. The root, or every role at depth
  1 inherits Executive and the company is one department. And a manager whose
  function the caller did *not* ask for: the spine's functions are the engine's
  and a caller's list may share nothing with them, in which case there is no
  coherent answer and the honest one is the rotation the caller chose. So
  `functions` stays the closed vocabulary for synthesised roles, exactly as
  documented, and coherence is what you get for asking for departments your
  engine has: which is what `company._functions_of` passes by default.
- Cosmetic until now; everything from here depends on it being right. Everything below the spine is
  about to author documents, and a one-to-one minuted between a finance manager
  and their audit-function manager is noise wearing a document's clothes.
- Left open at the time and closed above: `from_shape` still discarded the
  spine's own declared manager links, so which executives landed at depth 1
  decided the function mix. See *The organisation is shaped like its
  management*.

### The knob a corpus's size actually follows

- **`worldloom.divisions`**: widen a company past the divisions its archetype
  declares. Found by measurement: raising `organisation.headcount` from 23 to
  429 left facts at 8,021, artifacts at 204 and evaluation cases at 596:
  every one unchanged, because 429 people were still managing the same three
  divisions. The close fans out per division and per category, so the corpus
  follows the *structure* and `headcount` was never the knob. Widening the same
  retailer three → eight divisions took facts 604 → 990, artifacts 15 → 20 and
  questions 42 → 52 on one seed.
- Widening is additive. The declared divisions keep their names, categories,
  formats and *relative* sizes (64/21/15 stays in that ratio at any width),
  and only the shares renormalise, because a share is a fraction of group
  revenue and a fourth division has to take something from somebody. Each
  addition is sized against the smallest declared division and declines by 0.8
  from there: equal shares were the first rule and they gave Property a 12.5%
  share against General Merchandise's 7.9%, an adjacent business outweighing
  the core it was bolted onto.
- Pools are per industry and each entry is a real line of business rather than
  a relabelling: its own categories and estate, therefore its own row in every
  unit-level table, its own close commentary and its own questions. Retail
  offers five, banking three, insurance three. `divisions.register` adds a pool
  for a fourth vertical, and is refused on redefinition for `locales.register`'s
  reason. An industry with no pool is refused by name rather than served a
  division called `Division 4`.
- Refused rather than improvised in three places: narrowing below the
  archetype's own count (silently removing every fact, document and question a
  division owned), exhausting the pool (named with how many are available), and
  an unknown industry. Through `--spec` these arrive as an `organisation`
  conflict alongside whatever else the description got wrong.
- The width rides the **archetype key** (`omnichannel_retailer+8div`, composing
  with the vocabulary qualifier as `omnichannel_retailer+wholesale_club+8div`),
  for the reason `vocabulary.spoken` qualified its own key: the key is the only
  thing a recipe records about the shape, so a width carried anywhere else
  would rebuild a three-division company from an eight-division corpus and
  report success. A widened corpus replays byte-identical.
- No default moved: `widened(archetype, None)` returns the archetype itself, and
  every corpus built before this module exists is byte-identical after it.

### A benchmark an authored process gets for free

- **`worldloom.benchmark`**: evaluation cases derived from the fact graph
  rather than templated per vertical. An authored process produced **0**
  evaluation cases against the 11 per period its engine episode produces
  (measured twice, docs/episode-grammar.md), because every question shape lived
  in a per-vertical Python module the grammar cannot reach. A question shape
  turns out to be a shape in the graph: `direct_lookup` is a fact one artifact
  carries and nothing contests, `authority_resolution` is two or more artifacts
  citing different-authority facts about one subject, `temporal_state` is a
  window that closed, `causal_multi_hop` is a path in `caused_by`,
  `cross_artifact`/`numerical_comparison` are a declared `derive` or `sums-to`
  read against where its terms landed, and `citation_required` is a statement
  exactly one document makes.
- **`EpisodeSpec.evaluation`**: an `EvalSpec` for what cannot be derived:
  question phrasing per family and per kind, difficulty targets, which families
  a process wants emphasised, and the abstentions (a fact graph holds no witness
  to a fact's *absence*). Declared beside `detail_tables` and linted the same
  way: a family naming a fact kind the registry lacks is refused, as is a
  `str.format` slot the derivation never fills. `about` is a priority as well as
  a scope, and cannot conjure a case the corpus could not answer.
- **Measured.** `ProcureToPay`: 0 → **17 cases per period, 49 over three**,
  across all eight families, 11 of 17 graded hard. `QuarterlyCapitalReturn`,
  which authors *nothing* about evaluation: 0 → **14 per quarter across six
  families**, which is the "for free" claim unassisted. The four default engine
  builds at seed 8128 are byte-identical against `git archive HEAD`.

### A retriever anyone would deploy, and what it says about the corpus

- **`worldloom.evaluate.embedding`**: dense retrieval as a third ranking
  family, so a hardness claim no longer rests on two heuristics that share one
  idea. `RETRIEVERS` widened from classes to factories (`RetrieverFactory`), and
  that is the whole integration surface: `score()`'s grading still cannot ask
  which retriever produced the passages it is holding, which is what makes the
  comparison evidence rather than two tables printed together.
- **Optional and absent-friendly.** `pip install "worldloom[embeddings]"`.
  Without it, `--retriever all` skips the dense column with a message and still
  reports the lexical pair; `--retriever embedding` says what to install and
  exits nonzero. Never a traceback, never a silent zero.
- **Deterministic, which for an embedding model is not free.** Pins carry a
  model id *and a commit revision*; every vector (passages and questions) is
  cached to a sidecar keyed by `content_key(model, revision, scheme, text)`;
  cached vectors are L2-normalised `int8` and scoring is an integer dot product,
  so the cosine is bit-identical on any machine holding the same cache. A corpus
  that carries its cache is scored **with no model installed at all**, which is
  the generation ledger's argument applied to a retriever.
- **`worldloom evaluate --retriever all`** and `tools/measure_retrievers.py`
  print a new per-family reading: *genuinely hard*, *lexical trap*, *semantic
  blind spot*, *solved by everything*. `--retriever both` is unchanged: still
  exactly BM25 against TF-IDF, same console text, same JSON.
- **Measured, on the reference narration and a five-world mosaic.**
  `expected_abstention` and `temporal_state` are hard for everything (0/96 and
  0/30 lexical; 0/96 and 5/30 semantic, and those five are one question passed
  for the wrong reason). `authority_resolution` moves 0/30 → 8/30, still
  failing, but part of what BM25 was failing on was vocabulary, not authority.
  **No family turned out to be a pure lexical trap**, which is the result the
  corpus wanted and the first time it has been shown rather than assumed.

### Selection on outcomes, and what it actually bought

- **`worldloom.outcomes`**: the loop this repository described and never ran:
  generate candidates, **measure the corpora**, select on the measurements.
  `mosaic` disperses in parameter space, which is a proxy it never checked;
  this points the same `dispersion.farthest_first` at a measurement vector
  built from the instruments that already existed (`Built.measure`,
  `stats.measure`, `stats.compute`, the evaluation family and difficulty mix)
  plus a pairwise question-overlap term. Reachable as
  `sdk.outcome_selected(candidates, n)` and `mosaic.outcome_field(n, pool=30)`.
  `mosaic.field` and `worldloom mosaic -n 5` are byte-for-byte unchanged.
- **The Goodhart line is in the code, not only in the prose.** `select()`
  optimises *spread*, has no model of a good corpus, and provably never touches
  a retriever: `tests/test_outcomes.py` replaces the scorer with something that
  raises and requires the default path not to notice. Selecting against one
  baseline is a separate method (`Pool.hardest`), takes the retriever's name,
  and warns at the call.
- **Measured against parameter dispersion, and the result is mixed.** Same
  candidate pool, same size, both arms narrated and surveyed with
  `evaluate.across` (`tools/outcome_selection.py`). On retail at n=5 and n=8,
  outcome selection reliably wins distinct question strings (124 → 147),
  distinct (question, answer) pairs (145 → 169), cross-world near-duplicate
  *rate* (0.0050 → 0.0042), families showing any spread (3 → 5) and failure
  concentration (0.33 → 0.24); it reliably **loses** raw cross-world duplicate
  pair counts (it prefers denser corpora and that count is quadratic in
  questions per world), and it consistently halves the abstention-floor
  transplants that change a verdict (16 → 9), which is less transfer stress,
  not more. On banking and insurance every row ties: those evaluation
  generators emit the same 16 and 9 question strings in every world, so no
  selector can move anything, which is a finding about the generators rather
  than about the selector. The win is real, partial, and retail-only.
- **The objective's one free parameter changed nothing.** Selection was
  identical at question weights 0, 0.5, 1 and 2 on a thirty-candidate retail
  pool (the metric block decided it), so the win is not an artifact of a term
  that mimics the metric being reported.
- **Cost.** A pool of thirty retail candidates measures in 4–5 s (≈0.15 s each,
  no narration, no render, nothing on disk), against 0.07 s to disperse the
  same candidates on parameters alone. Banking and insurance are ≈0.03 s per
  candidate.

### Fixed

- `sdk.mosaic_of` dropped the vocabulary a mosaic dealt, so its blueprints
  rebuilt worlds the mosaic never planned. `Blueprint.speaking()` and
  `Blueprint.vocabulary_name` carry it; an empty vocabulary is byte-identical
  to before.
- Blueprints from `sdk.mosaic_of(n, engine="banking"|"insurance")` raised
  `TypeError` on `build()`: `Variant` always carries a calendar, including for
  engines that read none, and the bridge passed it to a world spec with no such
  field. Latent because the existing test counted blueprints without building
  one.
- `Built.measure()` and `Built.topology()` were a second copy of
  `outcomes.shape_vector`'s walk; they now delegate to it.

### The foundation

One coherent enterprise, taken all the way through. Two, in fact.

### The tool

- **Deterministic worlds from a seed.** `worldloom build --seed 8128` generates
  an organisation, its people, systems, services, categories and store estate, a
  month-end close with an optional operational incident, the documents that
  episode warrants, and an evaluation set over all of it. The same seed produces
  the same corpus, byte for byte.
- **Two industry verticals.** The retail month-end close is the default;
  `--archetype midsize_adi` builds a fictional bank and runs the quarterly
  capital-return episode instead: challenged by the second line before
  lodgement, filed anyway under a lodgement norm, invalidated by a
  reconciliation break the daily liquidity cadence catches, and corrected by a
  *restatement* that leaves the original filing on the record. Both lodgements
  carry the same authority, so only the restatement relationship and fact
  validity can say which figure is current, and the evaluation set asks
  that, paired with its temporal inverse so no retrieval bias answers
  both. Banking adds zero fields to the core model: its validator checks,
  artifact types, and archetype arrive through registration seams any future
  vertical can use.
- **Seven output formats.** XLSX with live formulas, named ranges, and hidden
  lineage and reconciliation sheets; DOCX, PPTX, and native PDF; Markdown; and
  portable Jira, Confluence, and ServiceNow bundles. All projections of one
  resolved intermediate representation, so no two formats of a document can
  disagree.
- **Three agent handshakes.** `worldloom plan` lets a model propose each
  document's structure under grammar validation; `worldloom narrate` hands out
  bounded prose requests and rejects any response that restates a figure, cites
  an unavailable fact, or invents an entity; `worldloom act` runs the incident
  as employees making one validated tool call at a time, each seeing only what
  that employee could see.
- **Actor simulation (A0–A5).** Role-scoped observations with an epistemic
  ledger of who knew what and when; policies and decision rights enforced by
  typed tools rather than prompts; an event-driven scheduler with bounded
  episodes; an execution ledger recording every call, including the refused
  ones.
- **Evaluation as a product surface.** `worldloom evaluate` scores an in-repo
  baseline retriever per question family (direct, cross-artifact, numerical,
  causal, temporal, authority, abstention) so corpus hardness is measured, not
  asserted. `worldloom diversity` fingerprints document structure so a batch
  cannot quietly become one document photocopied.
- **Complete replay.** Every generative call (prose, plans, actor decisions)
  is content-addressed into a generation ledger that ships with the corpus.
  `--replay` regenerates byte-identically with no provider reachable, and CI
  proves it on every push, from the installed wheel as well as the checkout.

- **The communications fan-out.** Episodes publish their long tail: meeting
  minutes for the decisions that were taken in a room (the escalation that
  moved the retail close; the banking meeting that approved the return with
  the challenge on the table), email threads whose every message knows only
  what its sender knew at that moment, and per-unit close commentary from
  each division's finance partner. Minutes are fully structured (attendees,
  tabled material, decisions) and cost the narration loop nothing; threads
  and commentary are prose under the same fact constraints as everything
  else. New evaluation families ask who was in the room and who was told
  what, when.

- **Industry packs.** A world's shape and lore as a JSON file an agent (or a
  person) authors: units, product categories, site estate, scale, dated lore
  commitments in the engine's closed constraint vocabulary, and the fictional
  company's name: run through either engine, with the episode physics staying
  the engine's. `worldloom pack template` starts one, `pack targets` publishes
  which lore each engine actually consults, `pack check` lints inert
  commitments by name, and `build --pack` builds it. The pack embeds in the
  corpus recipe, so a pack-built corpus rebuilds itself with no pack file.
  Packs also own their texture: ``system_brands`` renames the engine's
  systems for the industry, and ``voices`` re-voices any role's prose:
  applied as per-role persona clones, so a voiced CFO never re-voices
  everyone sharing the CFO's register, and numeric temperament stays the
  engine's. Each engine publishes its slots and role keys through
  ``worldloom pack targets``, and the lint names unknown keys.
  Packs also re-voice the episode itself: every event sentence and prose
  fact an engine states is a keyed template (``worldloom pack texts``), and
  ``episode_text`` overrides them: slot-checked, riding the recipe, over
  causality a pack cannot touch. The insurer's incident is about claims and
  peril codes; the mutual bank's challenge names its own book.
  Shipped references: a general insurer on the close engine and a mutual bank
  on the challenged-return engine, both exercised in tests. Authoring the
  first packs surfaced and fixed three archetype-coupling leaks the telco
  experiment had predicted (`unit_gm`, the merch lead's manager, and the
  banking error's unit), each engine now derives those from the world it was
  given.
  And packs re-voice the benchmark: every evaluation question and authored
  answer is a keyed template too (``EVAL_TEXT``, published beside the episode
  tables by ``pack texts``), overridden through ``evaluation_text`` under the
  same slot contract: the insurer's evaluation set asks about classes of
  business and gross written premium, never a merchandise category. The fact
  each case is graded against stays the engine's.

- **Consecutive banking quarters.** `--periods` now works for single-episode
  domains, stepping by the domain's own cadence (`period_step_months`;
  banking registers 3, so two periods are two quarter-ends). Each quarter
  runs the full challenged-return episode on the world the last one left:
  the standard's minimum-CET1 floor is minted once and reused as the
  standing fact it is, each quarter's liquidity cadence is its own
  supersession chain (gaplessness is enforced inside a chain, never across
  the deliberate gap between windows), and the capital reconciliation checks
  scope to their own period. A two-quarter corpus validates coherent and
  replays byte-for-byte.

- **A third vertical: insurance reserving, increment 1.** "The Living
  Estimate": a mid-size general insurer's quarterly reserving cycle, from
  the decided design record (`docs/design/insurance-reserving.md`): the
  development triangle as append-only observations, estimate chains whose
  superseded links were correct when made, and the estate's first permanent
  two-authority record: the actuarial central estimate and the booked
  reserve legitimately disagree, reconciled only by an explicit margin fact.
  Landing it triggered the rule of three: recipe steps are now a registry
  (`recipe.register_step`) each vertical seeds from its own module, and two
  thin-waist exceptions were paid down rather than a third added.

- **Repetition measured; the rewrite loop deleted before release.** Narration
  is open-loop (every section gets one request and one attempt, and nothing
  afterwards looks at what the corpus became), and a refinement loop
  (`worldloom refine`, MCP rewrite tools, a skill and a Stop hook) was built to
  close it: measure what repeats, rewrite only what repeats, gate each rewrite
  on the measured similarity. It was deleted before release, on evidence. The
  loop was built and gated against `DeterministicProvider` template prose,
  where three closes from one template genuinely repeat; a five-world proof run
  on real model prose measured its target (passages in a near-duplicate group)
  at zero in every world (0/46, 0/50, 0/52, 0/46, 0/43). The repetition it
  fought was an artifact of the deterministic fake, and its API adapters were
  the only code violating "this repository does not call a language model".

  What ships is the measurement, which is worth having about any corpus
  whoever narrated it: `stats.measure` runs the exact similarity join over the
  corpus's own passages beside a structural shape census, `worldloom diversity
  --near-duplicates` names the groups, and `worldloom mcp` serves the
  read-only tools (`measure_corpus`, `corpus_topology`, `corpus_series`,
  `validate_corpus`, and the probe tools) over stdio, with `.mcp.json` wiring
  them into any MCP client. No MCP tool writes a corpus; every corpus write path
  stays behind the CLI handshakes.

  Also fixed: `World.export` copied artifacts twice on an in-place export of a
  corpus that had been rendered, raising `FileExistsError` on a corpus that was
  perfectly intact. It had never fired because the only in-place callers ran on
  corpora with no `artifacts/` directory yet, and fixing it revealed a second,
  older defect it had been masking. CI's agent-handshake step submits
  deliberately invalid prose to prove the guardrail rejects it, and had been
  doing so against an already-narrated corpus: `review()` had nothing to review,
  the responses were never looked at, and the step passed only because that
  `FileExistsError` made the command exit non-zero. The guardrail the step is
  named for had not been exercised since rendering was added to it. `narrate
  accept` now refuses responses submitted into a corpus with no section awaiting
  prose, instead of printing "0 section(s) accepted" and exiting zero, and the
  CI step runs its rejection first, while sections are genuinely pending.

- **The estate becomes a landscape.** `worldloom topology` on the largest world
  this tool builds reported **nine** services and systems and a three-hop
  dependency chain: because nine is exactly what the month-end-close episode
  names. Categories scale with the archetype, sites scale, facts scale; the
  estate did not, which made blast radius meaningless, gave "who gets paged" a
  single answer, and left the incident's stale mapping table reading as bad
  luck rather than as the kind of thing sitting in every estate of that size.
  `build --estate small|medium|large` grows the rest of the landscape around
  the episode's own services: layered (edge → domain → platform → data →
  system of record) so acyclicity is *unconstructible* rather than merely
  checked, with chokepoints **placed**: each backed by a store only it may
  reach, because a shared service whose dependencies everything else can also
  reach directly dominates nothing. 101 nodes, a ten-hop chain, and the close
  orchestrator finally has a blast radius. The episode's four services are
  never edited, so its causality is bit-for-bit unchanged, and omitting the
  flag leaves every existing corpus byte-identical.

- **`worldloom compose`: the third handshake, and the first over entities.**
  `narrate` bounds what a model may *say* and checks it against the fact
  ledger; `plan` bounds how it may *shape* a document and checks it against a
  component grammar. This bounds what the company *runs* (services, systems,
  ownership, dependencies, declared criticality, and the lore explaining why
  the landscape looks that way) and checks it against `worldloom.graphs`. The
  graph library built for other reasons turned out to be exactly the validator
  that judgement needs.

  It exists because the generated estate cannot serve every vertical: its
  name pools are retail's, banking's landscape is not called
  `click-collect-api`, and the insurer ships with no services at all. A pool
  per industry is the wrong answer: it puts an ever-growing list of invented
  names into the engine, the contamination §7 forbids. An industry's
  vocabulary is the thing a model is genuinely better at than a table, so the
  model brings it and the harness refuses anything incoherent: a cycle through
  any number of hops, a dependency resolving to nothing, an owner who does not
  work here, a tier the graph contradicts, lore that constrains nothing, and
  an estate in which nothing is a single point of failure. Every violation is
  reported at once, nothing commits unless everything passes, and the accepted
  composition lands in the generation ledger, so a composed corpus rebuilds
  from its own recipe with no provider reachable, and refuses loudly rather
  than quietly rebuilding into the *un*composed world if its ledger is
  missing.

- **The world as graphs, and the defects only a graph could see.**
  `worldloom.graphs` reads the four graphs the schema always had and nothing
  ever looked at: the service/system dependency graph, the artifact provenance
  DAG across all four relationships at once, the fact supersession forest, and
  the reporting tree. It closed three real invariant gaps corpus-wide, for
  every vertical at the same time: a dependency cycle through more than one
  hop (the old check caught a service that depended on *itself* and nothing
  longer), a **forked supersession chain** (two facts replacing one, which
  leaves "what is current" ambiguous; the fact-layer walk built a dict keyed on
  the superseded id and let the second writer win, so this could never
  surface), and a provenance loop that uses a different relationship on each
  edge. `worldloom topology` is the reading: services ranked by *blast radius*
  and separately by *gates*: how much has no second path to what they serve,
  computed from dominator trees, because "lots of things depend on it" and
  "nothing routes around it" are different properties and a replicated platform
  has the first without the second. Every measure is an exact integer count
  with ties broken on id; there is no centrality score anywhere in it, because
  ranking by a float from an iterative solver is an argmax a different SciPy
  build can flip, and a rank that moves between machines is not a rank.

- **Near-duplicate detection that survives Gate 1.** `stats` has always
  reported an exact near-duplicate rate over passages, computed by comparing
  every pair, defensible at 120 artifacts and uncomputable at the 10,000
  build-order §12 targets, which is to say it would have stopped working on
  exactly the corpora whose repetition most needs auditing. `worldloom.similarity`
  keeps the *answer* and changes the algorithm: a prefix-filtered similarity
  join returns precisely the pairs a full scan would and provably misses none.
  Measured at 158× on corpus-shaped input, and pinned against brute force over
  randomised inputs rather than a fixture, because an off-by-one in a prefix
  bound is the only interesting way it can be wrong. `diversity
  --near-duplicates` turns the rate into a finding: *which* documents are one
  template, named. MinHash and banded LSH ship alongside for the regime past
  the exact one, labelled approximate and able to state the recall their band
  configuration implies.

- **Batch diversity, not just per-artifact.** `compiler.diversity.select` picks
  the *k* most-unlike alternatives for one artifact and is silent about the
  batch: run independently for a hundred artifacts it hands every one of them
  index 0, which is how §7a's measured defect (120 artifacts, 11 distinct
  shapes) is produced in the first place. `assign` spreads shapes *across* a
  batch, carrying what earlier periods already spent so period two does not
  reproduce period one; `collisions` names which artifacts share a shape rather
  than counting how many shapes there were.

- **Time series behind the figures.** `worldloom.series` decomposes a
  period-keyed fact series into trend, season and residual, and names the
  periods the first two do not explain: read it as a corpus check, since an
  incident month that does *not* sit outside the pattern is a corpus asserting
  a disruption its own numbers do not show. Outliers are scored on median
  absolute deviation rather than a z-score, because outliers inflate the
  standard deviation they would be measured against and several of them mask
  each other; the decomposition refits once with the first pass's outliers
  replaced by what it expected, so one spike cannot tilt the trend every other
  month is then judged against. Two defects found by its own tests and fixed
  in the algorithm rather than the assertion: a local (Hampel) filter mistakes
  a genuine seasonal peak for a spike, and a robust scale of zero (routine
  when more than half a sample is identical, which generated figures often are)
  silently disabled the detector on exactly the obvious cases.

- **`build --trend`.** Monthly compound growth behind the comparative history.
  Without it a year of comparatives oscillates around a flat level, so a
  seasonally-adjusted series is flat by construction and no question about
  direction has an answer in the data. 0.0 multiplies by exactly 1.0 (an IEEE
  identity), so every existing corpus is byte-identical, asserted rather than
  reasoned about.

- **Two retrievers, so hardness claims survive a change of heuristic.**
  `evaluate --retriever {bm25,tfidf,both}`: the existing baseline was
  already BM25, so the second family is TF-IDF cosine with shared
  tokenization, and the scorecard reports per-family agreement: a family
  hard under both ranking families is structurally hard. On the shipped
  corpora, every designed-hard family is. `worldloom stats` reports what a
  buyer can recompute: length distributions, vocabulary, exact
  near-duplicate rates, fact-citation density: no invented benchmarks.

- **Name pools and locale as pack data** (ladder rung 4). Person names,
  site regions, and headquarters are engine defaults a pack may replace,
  linted against the archetype's headcount, riding the recipe. Found and
  fixed en route: financial facts stamped AUD units regardless of the
  company's declared currency, in three generators. The insurer example is
  no longer Australian, and proves it byte-reproducibly.

- **Narration at scale, without an API caller.** There is no `narrate auto`
  and no model-SDK extra: an in-process API path (two model providers, and two
  agent-harness adapters) was built and then deleted before release, because
  the product is driven by a coding harness through the `narrate requests` /
  `narrate accept` handshake and the SDK: an API caller was a second writer
  path this repository's first line says it does not have. What ships from
  that work is the scale machinery in `narrative/compiler.py`, which any
  provider benefits from: `narrate(concurrency=N)` fans sections out with
  byte-identical output at any worker count (section fate and ledger order are
  decided before a thread runs), `preflight` counts the work before the first
  call, and the `on_accepted` seam hands each accepted section out as it
  lands so a long-running caller can persist paid work incrementally.

- **A benchmark that scales with the world.** `build --eval-density
  {low,standard,high}` grows the evaluation set and the fan-out layer from
  what the world already has (more categories and sites feed lookups and
  comparisons, more periods feed temporal and recurrence cases), reachability-
  gated like every existing case, with the default byte-identical to before.
  A three-period high-density grocery build carries `168` cases against `44`,
  and its hard families still score near zero, which is the point.

- **The haystack.** `build --distractors <n>` adds provenance-true noise:
  superseded drafts, derived personal copies, and routine notices: real
  authors, real lineage, real dates, citing only subsets of facts real
  documents already carry. No new facts means grading stays safe by
  construction: a distractor can never become the only home of an answer or
  make an abstention question answerable. Off by default; rides the recipe.

- **`/worldloom-design`.** The command for asks that arrive without a seed,
  such as "a hard corpus for insurance RAG": driving elicit → decide engine/pack →
  build → measure (`evaluate --json`, `diversity`) → iterate → deliver, with
  `references/designing.md` carrying the judgment: the elicitation table,
  the archetype / `--inspired-by` / pack cost ladder, symptom-level
  weak-family diagnostics, and the corpus-card delivery format.

### Generation

- The fan-out documents change what every seed generates: a corpus built
  before this release will not regenerate byte-identically under it (new
  artifacts, new evaluation cases, and category/site names admitted to the
  narrative entity check). Corpora built earlier remain loadable and
  validatable; regenerate from the seed to adopt the new layer.

### Packaging

- Installable with `pip install worldloom`; renderers with optional
  dependencies are extras (`worldloom[xlsx]`, `[docx]`, `[pdf]`, `[pptx]`, or
  `[all]`), and a missing extra fails with the exact install command rather
  than a traceback.
- The golden retail-close corpus ships inside the package:
  `worldloom demo retail-close` works with no network and no checkout.
- Generated corpora record the worldloom version that made them, and the CLI
  warns when a corpus is advanced under a different release.
- Typed (`py.typed`), Apache-2.0, Python 3.11–3.13.
