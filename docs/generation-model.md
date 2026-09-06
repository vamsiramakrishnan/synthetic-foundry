# The generation model

Worldloom has two engines. The boundary between them is the most important design decision in the project, and this document fixes it.

> The LLM owns what benefits from synthesis, judgment, narrative, and plausibility.
> It owns nothing that benefits from arithmetic, identity, or graph integrity.

The **deterministic engine** owns anything that must be *correct*. The **generative engine** owns anything that must be *plausible*. A thing is never owned by both.

---

## Why the boundary is where it is

Language models are excellent at plausibility and unreliable at bookkeeping. Ask one to invent a retail company's culture and it will do better than a human with a spreadsheet. Ask it to make ninety-one line items sum to a total that also appears on slide 4 of a board deck and in a variance report filed six weeks later, and it will fail. Not always, but often enough that no downstream artifact can be trusted.

The failure modes Worldloom exists to eliminate are exactly the ones an unconstrained LLM introduces:

| Failure | Cause when the LLM owns too much |
| --- | --- |
| Numbers that don't reconcile | The model restated a figure instead of referencing it |
| References to things that don't exist | The model invented an entity the graph never had |
| Three root causes for one incident | Each document was generated independently |
| Org charts with orphaned reports | The model wrote to the graph without validation |
| A corpus that can't be regenerated | Generation wasn't recorded, so it can't be replayed |

Each is a bookkeeping failure wearing narrative clothing. So bookkeeping moves behind a wall.

---

## The division

| Deterministic engine | Generative engine |
| --- | --- |
| Entity identity and IDs | Names, brands, terminology |
| Referential integrity | Culture, politics, tone |
| The org graph and reporting lines | Team purpose and collaboration patterns |
| Arithmetic, aggregation, reconciliation | Financial commentary and explanation |
| The timeline and event ordering | Causes, consequences, lessons learned |
| Permissions and visibility | Audience and register |
| Which facts exist | What those facts mean |
| Artifact IDs, versions, provenance | Which artifacts would plausibly exist |
| Fact-to-artifact binding | Document structure and prose |
| Seeded randomness | Judgment |

Read the table as a contract. If a new feature needs something from the left column, it does not get to ask a model for it.

---

## Three hard rules

### 1. The LLM never does arithmetic

The model may *reference* a number. It may never *restate* one.

Generated prose carries fact references, not literals. The renderer substitutes values from the fact ledger at render time.

```
Model output:   "Gross margin declined {{fact:fin.gm.2025Q3.delta}} against plan,
                 driven primarily by {{fact:fin.gm.2025Q3.top_driver}}."

Rendered:       "Gross margin declined 240 bps against plan, driven primarily by
                 promotional depth in Fresh."
```

This is the single rule that stops a generated board deck from disagreeing with the workbook it was derived from. Both read the same ledger entry. Neither can drift, because neither holds a copy.

A model that emits a bare figure where a reference belongs is a validation error, not a style problem.

### 2. Every generative call is recorded, so worlds replay

A world must satisfy `World.from_seed(8128) == World.from_seed(8128)`. Model calls are not reproducible, so Worldloom does not rely on them being reproducible.

Every generative call is content-addressed and written to the world's **generation ledger**, keyed by:

- the world seed
- the call site and its ordinal within the run
- a digest of the input facts supplied to the call
- the model identifier
- the prompt template version

`from_seed()` replays the ledger. A key that hits is never re-prompted, so regeneration touches no model at all and is byte-identical, offline, and free. A world ships with its ledger; that is what makes a corpus citable: a seed in a paper regenerates exactly what was measured.

Changing the model or a prompt template changes the keys, and therefore produces a *different world*. That is correct and it is explicit: pinning both is part of pinning a world. Worldloom will not silently re-prompt and hand back something that no longer matches the seed it was asked for.

### 3. The LLM never writes to the graph

Generation *proposes*. The deterministic layer *validates and commits*, or rejects and retries.

A model may propose that a new business unit exists, that a VP moved, that a service was decommissioned. None of it is true until the deterministic layer has checked it against the graph: does every referenced entity exist, does the reporting structure stay acyclic, does the timeline stay ordered, do the permissions still hold, does the arithmetic still reconcile.

Rejections are cheap and expected. A proposal that fails validation is regenerated with the violation fed back, and the rejection is recorded in the ledger so the retry is also replayable.

---

## When generation happens

Note the ordering carefully, because "facts before prose" is easily misread as "structure before narrative", which is backwards. The **priors**, what the company is, its history and culture, are generated *first*, because no org graph, service catalogue, or financial model is decidable without them. They are then frozen, and every later phase reads them:

```
integer seed + intent (industry, scale, inspiration)
        ↓
[generative]     Priors: identity, lore, strategy, org intent, tech posture
        ↓        frozen into the ledger, immutable thereafter
[deterministic]  Structure: org graph, services, financial model, timeline
        ↓
[interleaved]    Simulation: events fire, model explains, validator commits
        ↓
[deterministic]  Facts
        ↓
[generative]     Prose
```

Coherence comes from every phase reading one frozen priors document that none may contradict. If the priors could drift mid-generation, the result would be exactly the incoherence Worldloom exists to eliminate. Freezing them before structure is built is therefore the mechanism, not a limitation.

Priors→structure is not a clean waterfall, either: priors can propose infeasible things (nine business units for two hundred people, a service graph that cannot support the claimed uptime). So it is [rule 3](#3-the-llm-never-writes-to-the-graph) applied one level up: priors state *targets*, the deterministic layer checks feasibility and pushes back, and the negotiation is recorded.

The twenty generation areas do not all run at the same time, and *when* an area runs determines its caching, its cost, and its blast radius. Grouped by phase:

| Phase | Runs | Areas |
| --- | --- | --- |
| **Authoring** | Offline, output reviewed and committed | Industry packs, meta-generation |
| **Seed** | Once per world | Identity, backstory, strategy, business model, org design, technology, information ecosystem, personas |
| **Simulation** | Per tick | World evolution, scenario instantiation, event narratives |
| **Planning** | Per artifact | Artifact planning, document outlines, visual design intent |
| **Render** | Per artifact | Narrative generation, cross-document style, intentional imperfections |
| **Evaluation** | On demand | Evaluation generation |

---

# Part I: Authoring time

Generated offline, reviewed by a human, and committed to the repository as data. Never generated during `simulate()` or `generate()`, because anything produced at authoring time is a *dependency* of reproducibility rather than a product of it.

## 18. Industry packs

Industry-specific knowledge, authored once per vertical and loaded as a plugin.

**Retail:** store operations · inventory · promotions · loyalty · distribution · merchandising

**IT services:** delivery · bench · utilisation · staffing · SOW · margin

**Healthcare:** clinical workflows · care pathways · compliance · population health

**Banking:** lending · deposits · AML · risk · treasury

**Manufacturing:** plants · BOM · supply chain · maintenance · quality

A pack contributes vocabulary, entity types, scenario templates, artifact recipes, and the metric definitions that make the vertical's arithmetic correct. The arithmetic itself is deterministic; the pack supplies the definitions, not the numbers.

*Deterministic:* metric formulas, entity schemas, unit and currency handling, the validation rules the vertical implies.

## 20. Meta-generation

The LLM extends the platform itself, generating:

- new artifact recipes
- new scenario templates
- new company archetypes
- new industry packs
- new persona families
- new governance models
- new evaluation templates
- new document taxonomies
- new event chains
- new simulation rules

This is the highest-leverage use of a model in the project: it is how Worldloom broadens coverage without hand-coding every domain. It is also the one place where the platform could destroy its own guarantees. A simulation rule invented at runtime is a simulation rule that cannot be reviewed, cannot be diffed, and makes the seed meaningless.

So meta-generation is a **development-time activity with a human in the loop**, and its output is code and data checked into a repository, versioned, and diffable:

1. The model proposes a recipe, template, or rule.
2. It is materialised as a file, not an in-memory object.
3. It is reviewed and committed, with its prompt version recorded.
4. Worlds reference it by version, like any other dependency.

`simulate()` never invents a rule. It only executes rules that were committed before the run started. Self-extension is a property of the project, not of a running simulation.

---

# Part II: Seed time

Generated once, when the world is created. These outputs *are* the `WorldSeed`: a frozen priors document, distinct from the integer seed that drives randomness. Every later phase reads it and none may contradict it. Expensive, cached permanently, and the reason `World()` construction is lazy: none of this runs until `.generate()`.

Areas 1–3 and 5 are the [lore](lore.md) layer, and lore is a constraint graph rather than a story: every commitment must constrain a downstream decision or it fails validation.

## 1. Enterprise identity

The "who are we?" layer.

Company name · brand architecture · mission · vision · corporate values · operating philosophy · industry archetype · market positioning · competitive landscape · company culture · leadership style · organisational maturity · transformation stage · public perception · corporate language and terminology · internal abbreviations · naming conventions

Note the distinction the top-level rule leaves implicit: the model owns *brand* identity, meaning what the company is called and how it talks about itself. The deterministic layer owns *entity* identity: the stable ID behind every employee, service, and project, and the guarantee that a reference to one always resolves. The model names things. It does not assign identity.

Terminology and naming conventions generated here are binding. Once the world decides its warehouses are "DCs" and its quarters run July–June, every artifact in every format obeys, because the renderer reads the same conventions.

*Deterministic:* entity IDs, name uniqueness, abbreviation collision checks, fiscal calendar arithmetic.

## 2. Historical backstory

A believable past, because enterprises are shaped by what already happened to them.

Founding story · major acquisitions · divestitures · failed initiatives · successful programmes · leadership changes · technology evolution · organisational restructures · regulatory events · market shifts · legacy decisions · cultural norms · previous architecture choices · historical incidents · historical technical debt · scar tissue that still affects decisions

Scar tissue is the point. A 2019 ERP migration that went badly is why the 2026 platform decision is conservative, why one VP is risk-averse in writing, and why a particular vendor is never proposed again. Backstory is not colour; it is a constraint on later judgment, and it is fed into every planning and narrative call as context.

*Deterministic:* event dates and ordering, which systems and entities existed when, the age and accumulated debt of every service.

## 3. Strategic context

Executive priorities, and the disagreements about them.

Annual objectives · multi-year strategy · transformation themes · executive concerns · board priorities · competitive threats · innovation areas · cost pressures · growth initiatives · risk appetite · success metrics · political tensions · cross-functional disagreements

Political tension shapes what gets written down. Two executives who disagree about cost versus growth produce genuinely different documents about the same programme, and that is the difference between a corpus that tests retrieval and one that tests reasoning.

*Deterministic:* metric definitions and targets, budget envelopes, which objectives own which programmes.

## 4. Business model

Revenue streams · cost drivers · customer segments · distribution channels · value proposition · product portfolio · service catalogue · partner ecosystem · vendor landscape · internal chargeback models · budget ownership philosophy

The model generates the *shape* of the economics: what drives revenue, how cost is allocated, who owns which budget. It does not generate the economics.

*Deterministic:* the entire financial model. Revenue, cost, allocation, chargeback, margin, cash flow, and every aggregation over them.

## 5. Organisation design

Executive team · business units · departments · team purposes · reporting philosophy · committee structures · governance forums · RACI patterns · decision rights · ownership boundaries · matrix relationships · internal politics · collaboration patterns

The model proposes structure and the human texture of it: what a team is *for*, who really decides, which two departments cooperate badly. The graph itself is built and validated deterministically: every person has exactly one reporting line, the hierarchy is acyclic, spans of control are plausible, and every service and project has an owner who exists.

*Deterministic:* the org graph, headcount roll-ups, span and depth constraints, ownership completeness.

## 6. Technology landscape

Posture, not exact products.

Technology philosophy · modernisation maturity · platform strategy · build versus buy philosophy · cloud adoption journey · architecture principles · engineering culture · release philosophy · security posture · reliability priorities · data strategy · AI adoption maturity

Generating a posture rather than a product list is what keeps worlds free of real vendor specifics while still producing artifacts that argue about the right things. A company with low modernisation maturity and a conservative release philosophy generates different ADRs, different incident patterns, and different executive resistance.

*Deterministic:* the service graph and its dependencies, criticality tiers, which services can fail together.

## 7. Information ecosystem

How information actually moves: the layer that decides what a corpus *looks* like.

Which teams create documentation · documentation quality · wiki culture · ticket hygiene · approval processes · meeting cadence · reporting hierarchy · knowledge sharing habits · preferred communication style · documentation ownership

This is the most underrated area in the model. It sets artifact density and quality per team, and it is why one business unit's corpus is thorough and searchable while another's is three stale pages and a spreadsheet. Retrieval systems that only ever see well-documented worlds are not being tested.

*Deterministic:* artifact volumes, cadence and dates, approval chains, permission propagation.

## 8. Personas

Every author should read differently.

Writing style · vocabulary · sentence complexity · technical depth · biases · optimism versus pessimism · risk tolerance · political awareness · preferred document structure · favourite phrases · review habits · escalation style

A persona is attached to every artifact as its author, and it is the same persona every time that employee writes. Consistency across hundreds of documents is what makes authorship a signal a system can actually learn. It is also what makes an optimistic status report from a known optimist something a reasoning system can discount.

*Deterministic:* author assignment, who could have written what given role and permissions, timestamps.

---

# Part III: Simulation time

Runs per tick as the world advances. The deterministic engine decides *what happened*. The model explains it and lets the organisation drift.

## 19. World evolution

Possibly the highest-value generative use in the project. Every simulated month:

New priorities · new tensions · organisational drift · cultural changes · leadership messaging · strategic pivots · new terminology · emerging risks · technical debt accumulation · policy evolution

A frozen enterprise is the tell of synthetic data. Real organisations drift: language changes, priorities move, reorganisations land, debt accrues, a risk that was theoretical in March is a programme by September. Evolution is what makes a temporal cut-off meaningful: the world of 2023 genuinely differs from the world of 2026, so a question answered correctly at one cut-off is answered differently at another.

Drift is proposed and then validated, because an organisation may drift but not teleport: headcount moves continuously, reorganisations preserve people, terminology changes are recorded with effective dates so older artifacts keep using the older word.

*Deterministic:* the clock, headcount and financial trajectories, debt accumulation arithmetic, effective-dating of every change.

## 10. Scenario design

Templates are authored offline (Part I). Instantiation happens here: the model decides how *this* scenario lands in *this* world.

Product launch · AI rollout · ERP migration · warehouse automation · customer escalation · vendor bankruptcy · security incident · budget freeze · merger · audit · regulatory change · major outage · supply chain disruption

For each: triggers · timeline · stakeholders · consequences · communication patterns · required artifacts

The same template produces a different scenario in a world with poor ticket hygiene and a risk-averse CTO than in one without. Stakeholders are selected from the actual org graph, not invented.

*Deterministic:* trigger conditions, event ordering and dates, stakeholder resolution against the graph, financial impact.

## 9. Event narratives

The deterministic engine creates events. The model explains them.

Causes · consequences · executive summaries · timeline explanations · lessons learned · meeting discussions · decision rationale · trade-offs · assumptions · open questions · risk commentary

Explanation is generated *once per event* and every artifact about that event reads it. This is why an incident has one root cause across eight documents rather than eight root causes: the explanation is a fact in the ledger, not a per-document improvisation.

Where documents *should* disagree, such as an initial diagnosis that was wrong or a status report written before the real cause was known, the disagreement is generated and labelled (§15), with the artifact's knowledge cut off at its own timestamp.

*Deterministic:* what happened, when, to which services, with what measured impact, and who was involved.

---

# Part IV: Planning time

Judgment about what should exist and how it should be shaped, before a word of prose is written.

## 11. Artifact planning

The model answers one question: *if this happened, in this organisation, what documents would naturally exist?*

A SEV1 outage might produce an incident record, an RCA, a chat discussion, an executive memo, a board update, engineering tasks, a knowledge article, and an audit note.

**Not every incident deserves every artifact.** This is why the choice is made by a model rather than a rule. A template that emits eight artifacts per incident produces a corpus with no signal: every incident looks identical and important. Real organisations are selective and inconsistent: most incidents get a ticket and nothing else, some get an RCA nobody finished, a few reach the board. Plausible *selectivity* is a judgment call, and it is the difference between a corpus that tests retrieval and one that just has a lot of files in it.

The information ecosystem (§7) constrains this directly: a team with poor documentation culture generates fewer artifacts, later, and worse.

*Deterministic:* artifact IDs, timestamps, author eligibility, permission assignment, fact binding, provenance edges.

## 12. Document outlines

Structure before prose.

Sections · ordering · audience · required tables · charts · appendices · references · attachments · reviewers

Outlining separately is what lets the deterministic layer resolve every table, chart, and reference *before* generation. Prose is then written against data that already exists, and a promised appendix is always present.

*Deterministic:* table and chart data, reference resolution, attachment existence, reviewer eligibility.

## 17. Visual design intent

Intent, not pixels.

Deck structure · information density · story flow · chart recommendations · table recommendations · executive versus engineering presentation style · slide hierarchy · appendix planning

The model recommends that a trend belongs in a line chart with the appendix carrying the detail table. Renderers decide pixels. This keeps design intent portable: the same intent renders to PPTX or to a Confluence page without regeneration.

*Deterministic:* chart data, axis ranges, layout, pagination, whether the content physically fits.

---

# Part V: Render time

Prose, at last: the part everyone assumes is the whole job. It is five of twenty areas, and it runs last.

## 13. Narrative generation

Memos · meeting minutes · executive summaries · design documents · PRDs · ADRs · status reports · commentary · RCA prose · financial commentary · release notes · customer communications

Generated against a resolved outline, a bound fact set, an assigned persona, and a domain style. The model writes language and nothing else: no figures (rule 1), no entities the graph lacks (rule 3), no facts absent from the ledger.

*Deterministic:* every number, name, date, and reference in the output.

## 14. Cross-document style

Consistency, not coincidence.

Finance writes differently from engineering. Operations writes differently from HR. Board papers differ from incident reports. Every domain gets its own language, and it keeps it across thousands of artifacts.

Domain style composes with persona (§8): a given engineer writing an ADR sounds like themselves *and* like engineering, and sounds different again writing to the board.

*Deterministic:* which style applies, template and format selection, terminology enforcement.

## 15. Intentional imperfections

Realistic noise, on purpose.

Wrong assumptions · initial diagnosis · stale documentation · political wording · overly optimistic status · missing details · contradictory terminology · duplicate tickets · incomplete meeting notes · human mistakes

A corpus without mess flatters whatever you point at it. The mess is therefore never accidental: every instance is **labelled and traceable**, which is what separates a test case from a bug:

```python
world.artifacts().where(stale=True)
world.inconsistencies()
```

Every imperfection records what it contradicts and why, so an evaluation can ask a question the naive answer gets wrong, and grading still knows the truth.

*Deterministic:* which artifacts are imperfect and how, the ground truth they deviate from, the labels.

---

# Part VI: Evaluation time

## 16. Evaluation generation

Questions · distractors · alternative phrasings · follow-up questions · multi-hop questions · ambiguous questions · clarification prompts · incorrect hypotheses · expected reasoning chains

The model writes the questions. The world already knows the answers: they are facts, with citations, because every artifact records the facts that justify it. Ground truth is never generated, which is what makes the eval set trustworthy: a graded answer is checked against the ledger, not against another model's opinion.

Distractors are drawn from real artifacts that are plausibly relevant and actually wrong: superseded reports, stale pages, the incident with a similar signature. That makes a retrieval failure a genuine near-miss rather than a random file.

*Deterministic:* answers, citations, reasoning-chain validity, difficulty, whether a question is answerable at a given cut-off or permission level.

---

## Summary

Twenty areas of generation. In every one, the model supplies judgment and language, and the deterministic engine supplies truth.

The test for any new feature: **name what the model owns, and name what stays behind the wall.** If those cannot be separated cleanly, the feature is not designed yet.
