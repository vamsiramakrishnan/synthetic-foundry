# Vocabulary layer: real industry structure, real distributions, synthetic content

Vocabulary is where synthetic worlds leak. A Jira project called PHX with a "payments" service reads as a demo; a "Global Transaction Services" division with a "SG-NET-L2" assignment group, an AVP who reports to an ED, and a P3-heavy incident queue reads as a bank. The names are cheap; the structure and the frequencies are what convince a model and, more importantly, what make the eval distribution match production.

Three layers, three sources:

| Layer | Gives | Comes from |
|---|---|---|
| Taxonomies | structure: what processes, roles, units, and states exist | APQC PCF, O*NET, ESCO, ITIL, CSDM, regulators |
| Corpora | distributions: how often, in what mix, with what transitions | public Jira dumps, ServiceNow event logs, BPI process logs, 10-K filings |
| Packs | surface forms: how this company, region, and industry names things | authored seed pack, then twin packs per customer |

The generators sample from packs; packs are built from taxonomies and weighted by corpora. One lexicon schema carries all three.

## 1. Lexicon schema

```
{"id": "onet:11-3031.02:alt:bank-advisor", "type": "title", "label": "Bank Advisor",
 "canonical": "onet:11-3031.02", "alt_labels": [{"lang": "ja", "label": "..."}],
 "lang": "en", "industry": "banking", "region": "SG", "weight": 0.7,
 "source": "onet-29.3", "license": "CC BY 4.0"}
```

Types: `industry, function, process, activity, title, team, system, regulator, kpi, artifact, field, state`. `canonical` links surface forms to one concept, so a title ladder, a Wikidata label in Korean, and an O*NET alternate title resolve to the same role. `weight` is a prior for sampling; corpora overwrite it with measured frequency. `source` and `license` travel with every record, so a pack can be audited and shipped.

## 2. Source catalogue

Harvested and verified in this session (`harvest.py --sources onet,wikidata,uci_servicenow`, one command, about three minutes):

| Source | Take | Yield | License |
|---|---|---|---|
| O*NET 29.3 (US DoL) | occupations, 56k alternate titles with provenance codes, task statements (activities per role) | 76,372 lexicon rows | CC BY 4.0; confirm in release notes |
| Wikidata | occupations and industries with labels in ja/ko/th/zh/id/ms/vi/hi | 10,005 rows, 4,925 with non-English labels | CC0 |
| UCI 498, ServiceNow incident log | 141,712 events over 24,918 incidents: state vocabulary, priority mix, reassignment and reopen histograms, state-transition frequencies | distribution file | CC BY 4.0 |

Parsers written, download manual (registration or size):

| Source | Take | Why | License |
|---|---|---|---|
| APQC PCF 7.2 cross-industry + industry versions (banking, insurance, retail, consumer products, telecom, utilities, life sciences, airline, aerospace, broadcasting) | 13 categories, process groups, processes, activities with hierarchy ids | the process backbone; skills, actor state machines, and artifact intents key to PCF ids | free with attribution; industry versions carry an APQC/IBM license shipped in the file |
| ESCO | occupations and skills in 28 languages, ISCO-08 crosswalk | European and multilingual titles; the crosswalk cleans Wikidata | CC BY 4.0 |
| Public Jira Dataset (Montgomery et al., Zenodo, anonymised version) | 16 Jiras, 1,822 projects, 2.7M issues; custom field names and fill rates, issue-type mixes, link types, comment register | field manifests with real usage statistics | dataset terms on Zenodo; research use |
| BPI Challenge logs (4TU.ResearchData): 2012/2017 loan applications, 2013 Volvo IT incidents, 2014 Rabobank ITIL, 2019 purchase-to-pay, 2020 travel expenses | activity names, case durations, rework loops, resource handovers | process timing and rework priors per process family | CC licenses per log; check each |
| SEC EDGAR 10-K (EFTS full-text search) | reportable segment names, subsidiary lists (Exhibit 21), risk-factor register | business-unit naming patterns and risk vocabulary | public domain |

Reference vocabularies to encode by hand (small, stable, names only): ITIL 4 practices; ServiceNow CSDM CI classes; Salesforce standard objects and fields; TM Forum eTOM level-1 and level-2 process names for telecom; BIAN service domains for banking; ACORD for insurance; GS1 GPC for retail categories; ISO 20022 message families for payments; XBRL US GAAP and IFRS element names for finance; FIBO for finance concepts (MIT license); Lightcast Open Skills (open license) and SFIA (registration) for IT skills.

APAC-specific: ANZSCO (AU/NZ), SSOC (SG), NCO-2015 (IN) occupation classifications; regulator glossaries from MAS, APRA, RBI, FSA, FSS, HKMA, BOT, OJK, BNM, BSP; ASX and SGX annual reports for segment names (names, not text).

Do not use: LinkedIn or Indeed scraping; anything with personal data (the first Public Jira Dataset version was withdrawn for exactly that; use the anonymised release).

## 3. Distributional realism

Lists make worlds plausible. Distributions make evals match production. Three measured priors from the UCI ServiceNow log, now in `lexicon/uci_servicenow_stats.json`:

- Priority mix across 141,712 events: 3-Moderate 93.5%, 4-Low 2.8%, 2-High 2.1%, 1-Critical 1.6%. Evalgen's incident generator currently draws P1–P4 near-uniformly. That inflates P1 searches and makes "open P1 and P2 incidents" easy.
- Reassignment count per incident: 0 for 54%, 1 for 25%, 2 for 9%, then a long tail to 7+. Reassignment is the natural source of belief divergence between groups.
- Transitions: Resolved → Closed on every incident; Active → Resolved 12,048; New → Active 7,936; New → Resolved 6,347 (direct resolution is common); Active → Awaiting User Info 3,629. "Awaiting Vendor" and "Awaiting Problem" exist and are rare, which is what makes them good near-miss states.

The same treatment for Jira from the public dataset: issue-type mix per project, custom-field fill rates, resolution time by type, link-type frequencies, comment length. For process timing: BPI logs give inter-activity durations and rework probability per activity.

Integration: the world generator takes a `priors.json` per (server, entity) and draws from it. Corpusgen's `satisfy_search` still guarantees hits, but the base population follows the measured mix, so search selectivity is realistic and the difficulty features (LEVERAGE element 10) are calibrated against something real.

## 4. Structure from taxonomies

Processes: key every skill, actor state machine, and artifact intent to an APQC PCF id. A new industry then inherits the cross-industry backbone (categories 7–13 are the same everywhere) and overrides categories 2–6 from its industry PCF. Skills in evalgen become instances of PCF process elements; the skill registry gains a `pcf` field, and conflicts (`CONFLICTS`) can be derived from siblings under one parent.

Roles: O*NET occupations and task statements give the activity vocabulary per role; the pack's title ladders map ladder rungs to O*NET codes. Actor policies (LEVERAGE element 8) read `activities` for a role from the lexicon instead of a hand list.

Units: the starter pack carries business-unit vocabularies and naming patterns per industry. EDGAR segment names and ASX/SGX annual reports extend them with real naming conventions (geography × line, product division, group function).

Systems: per-industry system lists (T24, Finacle, Guidewire, SAP IS-U, CargoWise, Epic) name the "system of record" for a process; the world's cross-links then have a named home, and wrong-system references (evalgen's `wrong_system` operator) become realistic.

## 5. Surface forms from packs

`packs/apac-starter.json` (authored, replace with harvested distributions where a source exists) carries:

- ten industries: business units, teams, processes with APQC ids and activities, systems, regulators per region, regulatory vocabulary, KPIs, artifact types;
- cross-industry: functions, naming patterns for business units, teams, ServiceNow assignment groups, Jira project keys, Confluence spaces, SharePoint sites;
- title ladders for AU corporate, SG bank, IN bank, IN IT services, JP corporate, KR corporate, SG public sector, tech engineering, with a title pyramid prior;
- ITIL 4 practices, process approaches, finance close and procure-to-pay activity lists, artifact types, KPI vocabulary;
- fiscal year starts per region.

Per-company lexicon (NARRATION element 4) is drawn from the pack: which synonym a company uses (incident/ticket/case), which ladder, which naming patterns. Two banks generated from the same pack read differently because the draw differs, not because the prose differs.

Multilingual: Wikidata and ESCO labels give ja/ko/th/zh/id/ms/vi/hi surface forms for titles and industries. Use them for mixed-language artifacts (a Japanese subsidiary's org chart, Korean approver titles on a workflow), which are common in APAC tenants and rare in benchmarks.

## 6. Quality filters

- Crosswalk before trusting Wikidata: keep only occupations that map to ISCO-08 through ESCO or to O*NET-SOC; the raw query returns "polymath" and "beggar" alongside "credit analyst".
- Dedupe across sources on normalised label; keep the highest-provenance source as canonical, others as alt labels.
- Weight normalisation per type and industry so a source with 56k rows does not dominate one with 300.
- Region filter: a title exists in a region only if the region's ladder or classification lists it, or the pack allows the global fallback.
- License ledger: every pack build writes `licenses.json` listing sources, versions, and attribution strings; a pack without it does not ship.

## 7. Integration points

| Where | Today | With the vocabulary layer |
|---|---|---|
| `evalgen.universe` | hand lists of companies, programs, people, services | `pack.sample(industry, region)` draws units, teams, systems, ladders, group names |
| `evalgen.content` NEW_NAME, SEARCH_DESC | generic phrasing | industry phrasing per pack; regulator and KPI slots |
| `evalgen.skills` | 24 hand skills | skills keyed to PCF ids; industry packs add process skills automatically |
| `corpusgen.world` | uniform priors | `priors.json` from UCI, Jira, BPI logs |
| LEVERAGE 8 actors | role names | O*NET activities per role; ladder-based reporting lines |
| NARRATION 4 lexicon | small synonym table | per-company draw from the pack, with multilingual labels |
| Worldloom packs | company spec per vertical | industry pack + region pack + twin pack composed at build time |

## 8. Running

```
python harvest.py --out lexicon/ --sources onet,wikidata,uci_servicenow
python harvest.py --out lexicon/ --apqc PCF_Cross_Industry_7.2.xlsx --esco occupations_en.csv
python harvest.py --out lexicon/ --jira jira_issues.jsonl            # anonymised public dataset export
python harvest.py --out lexicon/ --xes BPI_Challenge_2019.xes
```

Outputs are JSONL in the lexicon schema plus `uci_servicenow_stats.json`. Refresh quarterly; O*NET and ESCO version their releases, and the version is part of the record id.

## 9. Order

1. Wire `priors.json` from the UCI log into the incident generator; it is the cheapest realism gain and it changes search selectivity immediately.
2. Replace `universe.py` hand lists with the starter pack; add industry and region as world parameters.
3. Key skills to PCF ids; download the cross-industry and banking, insurance, retail, telecom PCFs.
4. Add the Jira public dataset for field manifests and fill rates (feeds NARRATION element 9).
5. Add BPI timing priors when actors (LEVERAGE element 8) exist.
6. Twin packs per customer, built with the same harvester against their metadata.
