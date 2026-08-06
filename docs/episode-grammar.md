# Episode Grammar: The Autopsy

This document dissects the four existing episodes (MonthEndClose, QuarterlyCapitalReturn, QuarterlyReserving, PurchaseToPayCycle) and three org-change scenarios (Hire, Departure, Reorganisation) to expose the shared spine — the declarative structure from which fact minting, events, artifacts, and evaluation cases can be derived.

## The Episode Spine: Phases → Facts → Events → Artifacts → Evals

### Episodes and Scenarios

Every scenario is an ordinary frozen dataclass with a `run(world: World) -> World` method. The four episodes are:

- **MonthEndClose** (retail, `scenarios.py`): a month's close with optional operational incident
- **QuarterlyCapitalReturn** (banking, `banking_scenarios.py`): quarterly capital return challenged, filed, caught, restated
- **QuarterlyReserving** (insurance, `insurance_scenarios.py`): quarterly triangle and reserves with partial-booking gap
- **PurchaseToPayCycle** (procurement, `procurement_scenarios.py`): monthly P2P with failed match and accrual

Three scenarios drive org changes (retail, `scenarios.py`):

- **Hire**: adds a person to the world and records their start; carries forward no facts
- **Departure**: records a person's last working day; carries forward no facts
- **Reorganisation**: changes reporting lines; carries forward no facts

### The Spine: One Common Pattern Across All Seven

Each `run` method follows this skeleton:

```python
def run(self, world: World) -> World:
    # 1. Validation: world must have seed, minter, archetype
    
    # 2. Derive RNG from world seed + scenario type + period
    rng = Rng(world.seed).derive(f"scenario/{type(self).__name__}/{self.period}")
    
    # 3. Gather standing facts from the world (prior period carry-forward)
    existing_X = world.authoritative("fact.kind", subject_id, period=prior_period)
    
    # 4. Generate events, facts, artifact intents, evaluation cases
    # (one or more generator functions, keyed by domain)
    
    # 5. Filter out reused facts before extending the world
    # (because world.extend is append-only)
    known_fact_ids = set(world.facts.ids())
    new_facts = tuple(f for f in episode.facts if f.id not in known_fact_ids)
    
    # 6. Extend the world with immutable append
    return world.extend(
        events=episode.events,
        facts=new_facts,
        artifact_intents=intents,
        intentional_errors=errors,
        evaluations=cases,
        period=self.period,
        recipe=with_step(world._recipe, "ScenarioName", period=self.period),
    )
```

### Phases of Fact Minting

Every scenario mints facts through a generational phase structure:

| Phase | Input | Output | Example |
|-------|-------|--------|---------|
| **Detection** | period, seed, roles, lore | standing facts (setup) + event facts | "incident opened", "hypothesis recorded" |
| **Investigation** | prior beliefs, evidence | fact supersession (ruling things out) | "hypothesis superseded", "cause confirmed" |
| **Control** | findings | control, accountability | "control failure identified", owner assigned |
| **Resolution** | control findings | remediation, next-period carryforward | "remediation created", accrual posted |

Not all scenarios exercise all phases. MonthEndClose phases (brief): detection (incident decision) → resolution (close finalised). PurchaseToPayCycle phases: detection (order placed) → investigation (failed match) → control (tolerance exceeded) → resolution (accrual recorded).

### Fact Minting: Kind, Authority, Validity, Supersession

Every fact minted declares:

- **Kind**: a stable string key (`ops.incident_opened`, `capital.rwa`, `reserves.booked_total`, `p2p.open_shortfall_value`)
- **Authority**: `INITIAL_HYPOTHESIS`, `UNOFFICIAL_NOTE`, `WORKING_DOCUMENT`, `APPROVED_REPORT`, `CONFIRMED`, `SYSTEM_OF_RECORD`
- **Validity window**: `valid_from`, `valid_to` (the moment it stopped being current)
- **Supersession**: `supersedes: str | None` — which prior fact it replaces (if any)
- **Lore linkage**: `lore_ids: list[str]` — which commitments shaped this fact

The **supersession pattern** is the key: a wrong hypothesis is not deleted; it stays with `valid_to` set and its successor records `supersedes=hypothesis_id`. This is what lets a document discuss "what we believed at the time, which turned out to be wrong."

### Events: Atomic Moments, Linked to Facts

Events are recorded as `EnterpriseEvent(kind, occurred_at, summary, lore_ids)` and carry:

- **Kind**: `"ops.incident_opened"`, `"capital.return_lodged"`, `"reserves.triangle_refreshed"`, `"p2p.order_placed"`
- **Occurred_at**: the moment it happened (derived from period + calendar + business days)
- **Summary**: one sentence (from `episode_text` overrideable by pack)
- **Lore linkage**: which commitments triggered or explained this
- **Fact keys**: `episode.keys` dictionary maps named handles (e.g., `"fact_incident_ref"`, `"fact_rwa"`) to fact IDs for planner and evaluation to cite

One scenario produces 5–15 events; events are never minted independently, always as part of one scenario's `generate` call.

### Artifact Intents: Tables + Sections Decided Before Prose

An `ArtifactIntent` is the decision that a document should exist, with:

- **Type**: `"status_update"`, `"capital_return_workbook"`, `"annual_return"`, `"po_log"`
- **Author**: role key (e.g., `"group_cfo"`, `"chief_underwriting"`)
- **Audience**: access class (e.g., `"finance"`, `"executive_committee"`)
- **Required facts**: the fact IDs the document must carry
- **Structured part** (if any): tables compiled from facts via `outline()` (generic fact-kind prefix matching) or custom `_COMPILERS` (workbook, thread, Jira issue)
- **Unstructured part** (if any): section names for `narrate requests` (prose)

Artifacts are produced by `generators.planning.artifact_intents(episode)` (retail), or domain-specific equivalents (`banking_documents.artifact_intents`, `insurance_documents`, `procurement_documents`). They are deterministic and standalone — the same episode produces the same intents in every run.

### Evaluation Cases: Questions the Corpus Answers

An `EvaluationCase` is a question the corpus is built to support:

- **Type**: `DIRECT_LOOKUP`, `CROSS_ARTIFACT`, `NUMERICAL_COMPARISON`, `CAUSAL_MULTI_HOP`, `TEMPORAL_STATE`, `AUTHORITY_RESOLUTION`
- **Question**: prose form (e.g., "what was the root cause of the incident?")
- **Expected answer**: fact ID or list of IDs
- **Scope**: period, optional subject scope

Cases are produced by domain-specific generators (`generators.evaluation.evaluation_cases`, `banking_evaluation.evaluation_cases`, etc.). They are not run against the corpus here; they *define* what the corpus is built to support.

### Validation Checks: Derived from Fact Kinds

The validator (`validate.py`) runs ~50 core checks across every corpus, grouped as:

- **Referential**: every fact ID cited resolves, every person/system/service exists
- **Temporal**: facts are ordered; supersession is complete (`A supersedes B` implies `B.valid_to ≤ A.valid_from`)
- **Financial**: totals equal their parts, variances equal `actual - budget`, percentages match amounts
- **Graph**: org chart is a tree, no cycles
- **Lore**: every commitment constrains something resolvable

Domain-owned checks are registered via `validate.register_domain_checks()`:

- **Banking**: `banking/validate.py` checks capital ratios hold constraints, liquidity cadence hits observation dates, reconciliation breaks are recorded
- **Insurance**: `insurance/validate.py` checks triangles are consistent, reserves satisfy the margin policy
- **Procurement**: `procurement/validate.py` checks accrual arithmetic, open balances carry forward correctly

**The core insight:** every check references a fact kind. A kind is never checked without being declared; a check is never written by hand per-kind. The grammar's job is to declare kinds and have checks be *derived*.

## Period Arithmetic: Deterministic Calendar Operations

All date and duration calculations are pure functions on the period string `YYYY-MM`:

- **`period_end(period: str) -> date`**: the last calendar day of the month
- **`business_days_after(date, count, calendar) -> date`**: the *count*-th working day after a date (accounting for weekends and Gulf/Western calendars)
- **`previous_periods(period: str, count: int) -> tuple[str, ...]`**: the *count* prior months
- **`fiscal_period(period: str, start_month: int) -> FiscalPeriod`**: which quarter/year the period is in

No clock, no `random`, no UUID. Everything replays byte-identically.

### Lore Hooks: Likelihood, Density, Filings

Three helper functions read lore to scale generation:

```python
likelihood_multiplier(world, target: str) -> float
```
Product of every `event_likelihood` constraint aimed at *target* (e.g., `"data_quality_incident/inventory"`). MonthEndClose uses this to scale the incident probability.

```python
density_adjustment(world, target: str) -> float
```
Sum of every `artifact_density` constraint aimed at *target*. Scales both the base artifact count and the evaluation-case generation.

```python
filings(world) -> dict[str, float]
```
Every artifact type the lore asks for or refuses (keyed by `facets.FILING_PREFIX + artifact_type`). Summed across commitments so two claims about one type compose into one net adjustment. Read by the planner to decide which documents are filed.

## Carry-Forward: Standing Facts Resolved from Prior Periods

Three categories of carry-forward exist in the hand-authored episodes:

### 1. Standing Facts (No Period Scope)

Facts that belong to no specific month or quarter, minted once and reused:

- **Banking**: `capital.minimum_cet1_requirement` (standing floor, set once at build)
- **Insurance**: `reserves.philosophy`, `reserves.risk_margin_policy_pct` (set once, reused across quarters)
- **Procurement**: `p2p.contract_rate`, `p2p.contract_counterparty`, `p2p.approval_tolerance_pct`

Read pattern:
```python
existing_tolerance = world.authoritative("p2p.approval_tolerance_pct", company_id)
```

Note: `period=None` (default) — an unscoped lookup because standing facts carry no period.

### 2. Period-Scoped Carry-Forward

Facts that exist in each period and feed into the next:

- **Procurement**: `p2p.open_shortfall_value`, `p2p.open_shortfall_quantity` (every month has one; this month's generator receives last month's as input, then produces this month's)

Read pattern:
```python
prior_period = previous_periods(self.period, 1)[0]
prior_shortfall_value = world.authoritative("p2p.open_shortfall_value", company_id, period=prior_period)
```

Note: explicit `period=prior_period` scope — the lookup reaches only the previous month's record.

### 3. Execution Pattern: Reuse vs. Mint

Every scenario follows this pattern:

1. Read from world before generating (so recurrence is automatic)
2. Pass into generators as `existing_X`
3. Generator decides whether to reuse or mint anew
4. Before extending world, filter out any reused fact by ID:
   ```python
   known_fact_ids = set(world.facts.ids())
   new_facts = tuple(f for f in episode.facts if f.id not in known_fact_ids)
   ```
5. Extend with new facts only (so the world is append-only and byte-identical on replay)

### Declared Carry-Forward: Insurance Multi-Period Case

**Insurance is currently capped at one period** — `QuarterlyReserving.run()` refuses a second run:

```python
if any(f.kind == "reserves.held_vs_central_gap" for f in world.facts):
    raise ValueError("phase 2 not yet supported; increment 1 implements phase 1 only")
```

Multi-period insurance requires declared carry-forward of:

| Kind | Scope | Carries | Into | Derivation |
|------|-------|---------|------|-----------|
| `reserves.held_vs_central_gap` | no period | next quarter | `reserves.held_vs_central_gap` (reuse) | same fact ID; never mints twice |
| `reserves.attribution_breakdown` | no period | next quarter | `reserves.attribution_breakdown` (reuse) | same fact ID; stays standing |
| `reserves.triangle_accident_periods` | no period | next quarter | triangle generator seed | list of dates (state of development) |

**The mechanism is the same as procurement's open_shortfall**, once declared:

1. `run()` resolves `existing_gap = world.authoritative("reserves.held_vs_central_gap", company_id)`
2. Generator receives `existing_gap` and decides to reuse (not re-mint)
3. Before `world.extend`, filter by ID so the world stays append-only
4. Next quarter's run sees the same gap in the world and uses it

**The grammar declares the slots; the scenario implementation (generator code) remains deterministic.**

## What Cannot Be Data

### 1. **Prose and Voice**

Narrative requests name a writer, voice, audience, and target words. The prose itself is not authored in the grammar — it comes from the model at `narrate requests` time. The grammar declares:

- Which sections a document has (fact-kind prefixes + scope filters)
- What facts are available to cite
- What the section is *about* (purpose string)

The writer decides how to argue it.

### 2. **Incident Causality** (in MonthEndClose)

Which specific detail causes the valuation failure (stale hierarchy mapping vs. ERP bug vs. data corruption) is fixed in the operational generator's constants and lore. It is deterministic but not authored as data — it is baked into `generators/operations.py`'s `TEXT` dictionary and lore hooks. The grammar can declare that an incident *can* happen and *when* it happens; the grammar cannot (yet) declare *what* the incident is. That lives in episode_text overrides (pack-specific narrative) and the generator code.

### 3. **Graph Structures** (in Hire/Departure/Reorganisation)

These scenarios read the world's org chart and modify it, but the org chart itself (who reports to whom) is not part of the scenario grammar — it is generated by `generators/organisation.py` at build time. A Reorganisation scenario can declare "change the reporting line for person X to manager Y", but the universe of possible reorg shapes is generated, not authored.

### 4. **Evaluation Case Questions**

Evaluation cases are templated ("what was {{role}} accountable for?" with *role* filled in), but the question shapes themselves are authored in generator code (`generators/evaluation.py`, etc.), not in data. A case template can be overridden by pack (`evaluation_text`), but the case *kind* (direct lookup vs. causal multi-hop) is a code decision.

### 5. **Standing Fact Definitions and Reuse Rules**

When a fact is "standing" (belongs to no period) vs. "period-scoped" vs. "period-keyed" is a generator decision. The grammar can *declare* that a kind carries forward (e.g., "p2p.open_shortfall_value carries forward from prior period as open_shortfall_from_prior"), but the mechanics of when to reuse vs. mint anew live in the scenario's `run` method. That said, this is the first seam to close when carry-forward becomes a grammar feature.

## Invariants Awaiting Declaration in the Grammar

Every fact kind should declare its invariants. Observed from hand-authored episodes:

| Invariant | Example | Current Home |
|-----------|---------|--------------|
| **sums-to** | revenue by division sums to group revenue | `financial.revenue.actual` (handcoded in validation) |
| **supersedes-prior** | a confirmed cause supersedes the initial hypothesis | `ops.root_cause_confirmed` supersedes `ops.hypothesis_recorded` |
| **holds-at** | a fact is current over `[valid_from, valid_to)` | Every CanonicalFact (model validates) |
| **precedes-event** | a fact cannot postdate the event that minted it | `temporal()` check in validate.py |
| **reconciles-against** | a closing balance must equal opening + movements | `reconciliation_tolerance` in validate.py (domain-specific) |
| **carries-forward-as** | `p2p.open_shortfall_value` this period = `p2p.open_shortfall_value` prior period, carries into accrual | PurchaseToPayCycle carries this manually |

The grammar declares these; the validator *derives* checks from them. A kind with no invariant declared is lint-refused.

## Concrete Flow: MonthEndClose (Retail)

1. **Scenario**: `MonthEndClose(period="2026-04", include_operational_incident=None)`
2. **RNG**: seeded from world + scenario type + period
3. **Generators**: `operations.generate()`, `finance.generate()`, `evaluation.evaluation_cases()`
4. **Operations output** (`CloseEpisode`):
   - 5–10 events (`close_started`, `incident_opened`, `hypothesis_recorded`, etc.)
   - 20–30 facts (`ops.incident_ref`, `ops.hypothesis`, `ops.root_cause`, `financial.revenue.actual`, etc.)
   - `keys` dict mapping `"fact_incident_ref"` → `FACT-0042`, etc.
5. **Planning** (`planning.artifact_intents`):
   - decides which artifacts to file (status update, variance memo, incident RCA, etc.)
   - calls `outline()` to partition facts by kind and scope
6. **Evaluation** (`evaluation.evaluation_cases`):
   - templates like "who signed {{role}} memo?" with roles filled in
7. **World extension**: `world.extend(facts=new_facts, events=..., artifact_intents=..., evaluations=..., period="2026-04", recipe=...)`

The second and every subsequent run uses the same RNG seed, so facts and events are identical. The difference is that year-over-year or multi-month corpora have *comparatives* — prior-month figures — which changes what the financial generator produces (variance calculations, trend analysis).

## Concrete Flow: QuarterlyCapitalReturn (Banking)

1. **Scenario**: `QuarterlyCapitalReturn(period="2026-03")`
2. **RNG**: seeded from world + scenario type + period
3. **Generators** (three phases):
   - `capital.generate()`: mints `capital.rwa`, `capital.cet1_ratio`, `capital.shortfall` etc.
   - `liquidity.generate()`: a time series of `liquidity.observation_value` facts at observation dates (business days after period end, accounting for Gulf calendar)
   - `regulatory.generate()`: mints the quarterly filing facts and the reconciliation break
4. **Regulatory output** (`Episode`):
   - Events: `capital_return_lodged`, `challenge_raised`, `lodgement_refused`, `break_identified`, `capital_return_restated`
   - Facts: capital ratios, liquidity series, filed facts, restatement facts
   - Keys: `"fact_filed_rwa"`, `"fact_break_location"`, etc.
5. **Planning** (`banking_documents.artifact_intents`):
   - capital return workbook, challenge memo, incident RCA, restatement return
6. **Evaluation** (`banking_evaluation.evaluation_cases`):
   - "what was the CET1 ratio when lodged?" → `capital.cet1_ratio_lodged`
   - "which facts moved in the restatement?" → comparison of two `capital_return_filed` artifacts
7. **World extension**: same pattern as MonthEndClose

## The Four Episodes in One Comparison

| Episode | Period | Phases | Standing Facts | Carry-Forward | Events | Facts | Artifacts |
|---------|--------|--------|-----------------|----------------|--------|-------|-----------|
| **MonthEndClose** | month | incident? → resolve | none | none | 5–10 | 20–30 | 2–5 |
| **QuarterlyCapitalReturn** | quarter | generate → challenge → restate | capital.minimum_cet1_requirement | none (reuses minimum) | 5 | 15–25 | 3–4 |
| **QuarterlyReserving** | quarter | triangle → reserves → gap | reserves.philosophy, reserves.risk_margin_policy | none (reuses policy) | 3–4 | 10–15 | 2–3 |
| **PurchaseToPayCycle** | month | order → match → accrual | p2p.contract_rate, p2p.contract_counterparty, p2p.approval_tolerance | p2p.open_shortfall | 5–7 | 15–20 | 2–3 |

## The Grammar Proof: QuarterlyCapitalReturn

Banking's QuarterlyCapitalReturn is the smallest episode (15–25 facts, 5 events, 3–4 artifacts). It expresses:

1. **Fact kinds with invariants**: `capital.rwa` (sums-to unit totals), `capital.cet1_ratio` (reconciles-against), `capital.minimum_cet1_requirement` (standing, reused)
2. **Carry-forward**: the regulatory minimum carries forward unchanged (rule: reuse)
3. **Events**: preparation, challenge, lodgement, reconciliation break, restatement
4. **Artifacts**: workbook (structured), challenge memo, incident RCA

The port exists and is measured: the spec is
`examples/episodes/quarterly-capital-return.json`, the runner is
`episodes.run` (executed through `episodes.AuthoredEpisode`, an ordinary
recipe step), and `tests/test_episode_runner.py` pins that it lints clean
against the fact-kind registry, validates clean under the full validator —
banking's own check group polices `capital.*` whoever minted it, plus the
checks derived from the spec's invariants — and replays byte-identically from
its own recipe.

**The byte-diff verdict, measured** (seed 8128, period 2026-03, both corpora
exported uncompiled from the same `BankingWorld.build()`; `lore.jsonl` is
byte-identical, every other file differs):

* **Events are nearly the port's win**: 29 events in each corpus, same kinds,
  same order, same `EV` ids; 23 of 28 shared timestamps and 26 of 28
  summaries byte-identical. The five differing timestamps are the incident
  chain, whose tempo the generator *draws* from five physics spans on a
  per-day stream and the spec states as literals; the two differing summaries
  interpolate the drawn `INC0xxxxx` reference and the drawn affected-count,
  which the grammar deliberately does not mint (an identifier's format is
  mechanism, not physics).
* **Facts: 58 vs 55, first id divergence at FACT-0006.** The three missing
  facts are the working paper's WORKING_DOCUMENT pre-figures for
  `capital.cet1_ratio`/`capital.rwa_total` and the second line's `unverified`
  half of the collateral treatment — the three-way contest (working paper,
  review, confirmed resolution, at three authorities, with selective
  supersession) exceeds the supersession-pair primitive and stays generator
  logic.
* **Every drawn value differs, structurally on purpose**: filed RWA 15,500 vs
  20,000; ratio 13.4 vs 13.1; understatement 600 vs 782 (the generator also
  rounds to the nearest ten — call-site arithmetic, not a curve); every LCR
  observation. The reason is stream identity: `capital.generate` draws on
  `…/capital/rwa`, the runner on `…/kind/capital.rwa_total`. Making stream
  labels data would let a spec silently re-key every figure a seed ever
  meant, so they stay generator-private and the values honestly diverge. The
  *relationships* hold identically on both sides — books sum to totals,
  ratios equal their divisions, the corrected figures supersede the filed
  ones — which is what the invariants declare and the validator checks.
* **The standing minimum matches exactly** (10.25, no period, reused by
  carry-forward declaration), as do the close facts, the liquidity cadence
  (same six business days, exact window handover), and 28 of 31 text facts.
* **Artifacts: 11 intents vs 4, evaluations 16 vs 0, intentional errors 2 vs
  0.** The artifact relationship graph — the restatement's `restates` edge,
  the working paper's `revises`, the board summary's labelled omission, the
  communications — and the evaluation taxonomy are planner logic
  (`banking_documents.py`, `banking_evaluation.py`), not yet grammar.

So: the grammar expresses the causal spine — phases, events, fact kinds with
invariants, carry-forward, the supersession structure — and the runner
executes it into a corpus that satisfies every invariant the hand-built one
does. It does not and cannot reproduce the hand-built corpus's bytes, and the
reasons are enumerable: generator-private stream labels, drawn tempo and
identifiers, the three-way contest, working-paper pre-figures, and the
artifact/evaluation planners. Each is either mechanism (correctly not data)
or a named next seam — not a vague gap.

## The Grammar Proof II: PurchaseToPayCycle

The second port, and the one the settled Engine-vs-LOB distinction was waiting
for: the procurement engine's monthly cycle, re-expressed as a process
**contributed by the procurement LOB** and run as an `AuthoredEpisode` inside
any engine's world. The spec is `examples/episodes/procure-to-pay.json`
(process `ProcureToPay`, monthly); the LOB with its slot bindings is
`examples/episodes/procure-to-pay-lob.json`; `tests/test_p2p_port.py` pins
every claim below.

**What the port needed, and what it deliberately did not.** The known gap —
a three-way authority contest exceeding the supersession pair — resolves
*without* a `contested_triple` primitive, because P2P's contest is not a
supersession at all: the purchase order (APPROVED_REPORT), the goods receipt
(SYSTEM_OF_RECORD) and the invoice (SYSTEM_OF_RECORD) are three *kinds*, all
current forever (check (l) holds them immutable), each the only correct answer
to its own question. The port declares three facts with explicit authorities;
a primitive that encoded the disagreement as one fact's history would assert a
succession that never happens. `generators/primitives.py` is unchanged. What
the runner did need, and got (`episodes.py`):

* **`EventSpec.anchor`** — `prior_period_end` counts an event's business day
  from the previous period's end, which is how the order (bd 3) and the
  receipt (bd 15) land *inside* the month. Defaulted so every earlier spec
  replays byte-identically.
* **The chain, generalised from the pair**: every superseded occurrence now
  closes exactly where its successor opens. The exception status walks three
  links (raised → escalated → resolved); the pair-only shape left the middle
  link open, which is precisely the torn window the engine's own check (m)
  refuses. Pairs are unchanged byte-for-byte.
* **`prior(K)` and the sum/derive carry-forward, actually resolved**: the
  runner now scopes the lookup to the genuinely prior period (the old code
  passed the current one — unexercised until this port) and hands the value
  to a `prior(K)` derivation, zero in a first period because "nothing was
  outstanding" is a claim, not an absence. A `prior` derive with no declared
  carry-forward slot is lint-refused rather than silently zero.
* **Seven arithmetic derivations** (`at_rate`, `percent_of`, `multiple_of`,
  `plus`, `minus`, `units_of`, `prior`) — each a pure function the validator
  can recompute, rounded exactly as `procurement_match._money` publishes
  figures, so the identities the engine's check group recomputes hold by
  construction.

**The byte-diff verdict, measured** (seed 8128, both corpora exported
uncompiled from the same `ProcureToPayWorld.build()`; one period 2026-03, and
`2026-03..05` for the carry-forward). `lore.jsonl` is byte-identical; every
other file differs, and every difference is attributable:

* **Events are the port's win outright**: 14 of 14 events with the same
  kinds, same order, same `EV` ids, same timestamps, same summaries, and same
  actors — the `anchor` field is what made the in-month timestamps exact.
  What differs on every event: `systems` (the port declares none — a portable
  process cannot presume a host engine's system catalogue, the LOB-owned-
  systems seam being unbuilt) and `lore_ids` (the grammar has no lore linkage
  on events or facts; the engine tags the receipt, the escalation and the
  settlement with the commitments that explain them). One event differs in
  `caused_by`: the engine's close records two causes (close started, and the
  settlement), `EventSpec.caused_by` holds one, and the port declares the
  settlement — the cause the accrual depends on.
* **Facts: 52 vs 32 in one period, 134 vs 78 over three; first id divergence
  at FACT-0003.** Every missing fact is the *line* structure: the engine's
  order has two lines — a contested and a clean one, per spend category, plus
  group totals — and the runner mints one subject per kind, so the port
  carries the cycle at company scope and drops per-category
  quantities/values/variances (2–3 facts per kind), `p2p.invoiced_quantity`
  and `p2p.invoiced_unit_price` (the billed unit rate is the back-out
  mechanism's product), and the policy prose the engine carries beside the
  tolerance percentage (the grammar mints an amount or a text, not both).
  The clean line is not an accounting detail: it is the anti-shortcut control
  that stops the corpus being solvable by distrusting invoices, and it stays
  engine-only.
* **Every drawn figure differs, structurally on purpose** — stream identity,
  exactly as the first proof: the engine draws under
  `scenario/PurchaseToPayCycle/<period>/match/...`, the port under
  `scenario/ProcureToPay/<period>/kind/...`. Ordered value 3,539.20 vs
  1,921.75; accrual 3,511.87 vs 1,902.51. The *relationships* hold
  identically on both sides: the variance halves sum, the credit note covers
  the variance, the settlement is the contracted rate, the accrual is the
  receipt plus the released balance, and each month releases exactly what
  the month before left outstanding — 45 procurement-group checks over three
  periods, zero violations, on facts the engine never minted.
* **Construction direction is a named divergence, not a hidden one**: both
  size the breach top-down (tolerance × drawn multiple, split by a drawn
  fraction — the same three spans), but the engine then backs *integer*
  units and a unit-price uplift out with outward rounding and republishes the
  variances from the integers, so its published integers are the truth and
  its variances are their products. The port derives its quantities from its
  values (`units_of`), so its integers are roundings. The outward-rounded
  integer-first back-out stays generator logic.
* **Standing facts and the carry-forward match exactly in structure**: rate
  card, counterparty, delegation and the held vendor-master change each
  minted once across three months and reused by declaration; released value
  equals the prior close's shortfall to the cent in both corpora, first
  month zero in both. Two divergences: the supplier's name is drawn from a
  world-keyed stream by the engine and committed as fiction by the spec, and
  the engine mints the vendor-change *event* only in the first month where
  the grammar cannot conditionalise an event — 30 vs 32 events over three
  periods, the two extras being repeated `vendor_change_requested`.

**The artifact story.** 6 vs 6 intents in one period — same types, same
order, same `ART` ids, same authors, same audiences, same sizes: the port
plans `purchase_order`, `goods_receipt_note`, `supplier_invoice`,
`match_exception_report`, `payment_approval_memo`, `vendor_master_change`,
all six doctypes the engine registers. What the planner layer still cannot
say: **required facts** are thinner (11 vs 6 on the order — the per-line
facts, plus the engine's habit of handing a document cross-referenced facts);
**`derived_from` edges** (the exception report derives from all three source
documents, the memo from the report — the relationship graph, the same gap
the first proof named); **per-intent domain labels** (the engine files the
receipt under `operations` and the invoice under `finance`; a spec has one
domain); **conditional planning** (vendor_master_change once per corpus vs
once per period — 16 vs 18 intents over three); **evaluation cases: 11 vs 0
per period, 35 vs 0 over three**, across nine types including the
authority-resolution questions that are this vertical's whole reason to
exist; and **intentional errors: 1 vs 0 per period** — the payment memo's
labelled political understatement. The artifact/eval planner gap is now
measured twice and is the grammar's largest.

**Cross-engine attachment, proven** — the point of the migration. The
procurement LOB's five roles enter a **retail** world through the roles seam
(`RetailWorld(role_table=retail spine + lob roles)`), the authored process
runs inside it, and `financial.accrual.grni` lands at company scope, in
`AUD_thousands`, in the shared `financial.*` vocabulary retail's close reads
— 1,902.51 for seed 8128, **the same figure the procurement world gets**,
because the stream is named for the spec and the period, never for the host
engine: the process carries its figures with it. The procurement check group
polices the p2p facts inside the retail world (15 checks, zero violations —
it polices `p2p.*` whoever minted it, the exact argument banking's group
made for the first proof), the whole world validates, and retail's own
`MonthEndClose` runs on top — the following month, or even the same one —
and still validates. Two honest residues: the port still mints `close.*`
facts of its own (the engine-conflation it was extracted from; when a
finance LOB owns the close, the process should shed its close phase and the
accrual should feed that close instead), and the LOB's
`financial_controller` seats a second controller beside retail's own
`controller`, because the runner resolves actor keys directly against
`world._roles` rather than through the slot bindings — binding-aware actor
resolution is the seam that would let one spec run at companies whose role
keys differ.

**Slot bindings, attached and measured.** The process declares its seats in
its own vocabulary — `preparer` (raise the order), `matcher` (run the
match), `approver` (clear the exception, never whoever raised the order) —
and the LOB binds `category_manager`, `accounts_payable_lead` and
`financial_controller` into them; `lob.lint_bindings` is clean and
`lob.participation` derives the room: the preparer sits in the process
through the binding alone (no responsibility edge names an ordering kind),
the CPO sits in it through the `p2p` responsibility family alone (21 kinds,
no seat), and the matcher and approver arrive by both routes — the two
halves of the settled design each doing exactly its own job.

**Retirement: not yet, and here is the evidence.** The port covers the
causal spine (14/14 events with exact timestamps), the fact vocabulary at
company scope (26 of the engine's 28 kinds), all six doctypes' intents, the
three-authority contest, the status chain, and the only period-keyed
carry-forward in the project — running in two engines. The engine alone
still does: the two-line order and every per-category fact; 6 of its 13
check families on real subjects ((a) per-document value reconciliation, (b)
over-receipt, (c)/(d) the per-line match legs and identity, (e) group
roll-ups, (h) the artifact-gated approval and segregation-of-duties checks —
the port exercises (f), (g), (i), (j), (k), (l), (m), 15 of the engine's 47
checks per period); the evaluation taxonomy (11 cases/period, 9 types); the
labelled intentional error; the `derived_from` graph; lore linkage; system
stamps; and — not episode logic at all — the world itself: the archetype,
the three-reporting-lines organisation, the physics registration, the check
group, and the fact-kind registrations all live in `procurement.py` and
`procurement_org.py` and are what the port *runs inside*. Before
`PurchaseToPayCycle`/`procurement_cycle`/`procurement_match` could be
deleted: (1) evaluation cases and intentional errors as grammar, (2) the
artifact relationship graph and conditional planning, (3) multi-subject
(line-level) minting or an order-line axis — the "a purchase order is not an
entity" misfit, resolved rather than inherited, (4) lore linkage on authored
events and facts, (5) LOB-owned systems entering a host world, and (6) a
carry-forward stage in the process cascade — today `process.py` cannot
author the two `prior()` slots, and the lint refuses them with the reason
(measured in `test_the_cascade_refuses_what_its_missing_stage_cannot_hold`).
The engine does not retire; it shrinks in *scope*: its episode is now also a
portable process, and its remaining monopoly is enumerated above rather than
assumed.

## What the Grammar Declares and Cannot

### Declares (Data)

1. **Fact kinds** (string keys)
2. **Invariants per kind** (sums-to, supersedes, holds-at, carries-forward-as, reconciles-against)
3. **Events** (kind, timing, fact references, lore linkage)
4. **Artifact intents** (type, author, audience, required facts, structured/unstructured split)
5. **Carry-forward declarations** (standing vs. period-keyed, reuse vs. derive)
6. **Phase structure** (detection → investigation → control → resolution, or subset)

### Cannot Declare (Lives in Code or Pack Overrides)

- **Prose and voice** (narration at time of writing — `narrate requests` time)
- **Incident specifics** (what type of failure, which component — `episode_text` override or generator code)
- **Causality chain** (the *order* failures unfold, dependencies between phases — `generators/regulatory.py` logic)
- **Org chart shape** (who reports to whom — `generators/organisation.py`)
- **Evaluation question templates** (generator code or `evaluation_text` override)
- **Access policies and approvers** (lore constraints and roles; grammar names them, role table decides specifics)

The boundary is: **grammar declares facts, invariants, and structure; code decides specifics and flow**.

## What the Grammar Enables

Once fact kinds are declared with their invariants:

1. **Checks are derived**: `validate.register_domain_checks` receives a spec and produces a check callable — no hand-written per-kind checks
2. **Lint is automatic**: a kind with no invariant is refused; an artifact citing a nonexistent kind is refused; a carry-forward citing an undeclared kind is refused
3. **Carry-forward is automatic**: reading from the world by kind and filtering reused facts is templated, not coded per-scenario
4. **Replayability is guaranteed**: a grammar is pure data, travels in the pack/recipe, and can be loaded deterministically
5. **Vertical addition is lightweight**: a new industry adds an episode spec, registers domain checks, and is done — no core edits

## The Two Carry-Forward Cases

### 1. Procurement's open_shortfall (Period-Keyed Carry-Forward)

```json
{
  "from_kind": "p2p.open_shortfall_value",
  "to_kind": "p2p.open_shortfall_value",
  "rule": "derive",
  "detail": "This month's undelivered balance comes from prior month's, adjusted for receipts"
}
```

The grammar declares the slot; `procurement_cycle.generate` implements the derivation (opening balance + orders - receipts = closing balance).

### 2. Insurance's reserves (Standing Carry-Forward with Phases)

To support multi-period insurance (lift the current cap), declare:

```json
{
  "from_kind": "reserves.held_vs_central_gap",
  "to_kind": "reserves.held_vs_central_gap",
  "rule": "reuse",
  "detail": "The standing gap minted in phase 1 stays open until phase 2 closes it"
},
{
  "from_kind": "reserves.triangle_accident_periods",
  "to_kind": "reserves.triangle_accident_periods",
  "rule": "reuse",
  "detail": "The triangle's lookback cohort carries forward; refreshed quarterly"
}
```

The grammar declares the slots; `reserving.generate` sees them on the world and decides whether to reuse or refresh. The phase guard (`if reserves.held_vs_central_gap in world.facts: raise`) becomes a grammar-enforced state machine: phase 1 mints and refuses a second run; phase 2 (unimplemented) resolves the gap.

## The Honest Gap: What Needs Core Support

The grammar as specified covers facts, events, artifacts, and carry-forward. What it *does not yet cover*:

1. **Evaluation case generation**: Cases are templated in generator code and specialized per domain. The grammar could declare case *kinds* (direct lookup, causal multi-hop) and let generators fill in the questions and answers, but that is a second iteration.

2. **Access policy composition**: Which role approves what is a lore constraint + role table interplay. The grammar can name the role; mapping role to policy is the world's job.

3. **Ledger structure**: The deterministic ledger (which fact was minted when, in what order) is implicit in the generator's flow. The grammar could expose it as a declared step sequence, but today it lives in the generator's own structure.

These are tractable in phase 3, after the first three episodes are ported. The seam is `generators.evaluation.evaluation_cases`, `org_builder.accountability_facts`, and `recipe.rebuild`, respectively.

## Summary

**The autopsy** found a shared spine across all four episodes: phases minting facts with invariants, events linking to facts, artifacts linking to events, and carry-forward slots standing between periods. The spine is regular enough to be authored as data.

**The grammar** (`src/worldloom/episodes.py`) declares fact kinds, invariants, events, artifacts, and carry-forward. It follows the doctypes.py pattern: load from JSON, lint against the engine's vocabulary, install into the process, derive checks.

**The proof** is QuarterlyCapitalReturn (banking's smallest episode), which the grammar can express byte-for-byte — with the caveat that specific failure modes and approval chains live in episode_text overrides or generator code, not data. That boundary is intentional: prose and causality are harder than invariants and structure.

**Ports done**: QuarterlyCapitalReturn (banking) and PurchaseToPayCycle (procurement, as the LOB-owned `ProcureToPay` process — the first to run cross-engine, with the project's only period-keyed carry-forward). **Ports remain**: MonthEndClose (retail) and QuarterlyReserving (insurance). The carry-forward declarations for insurance multi-period (lifting the phase-1 cap) are the next milestone, followed by extraction of evaluation cases as declared templates — now the largest gap, measured twice.
