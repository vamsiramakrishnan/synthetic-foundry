# Changelog

Worldloom versions its releases and its worlds together: every generated corpus
stamps the version that made it into `world.json`. Changes that alter what a
seed generates are listed under **Generation** — they are breaking for
reproducibility even when no API moved.

## 0.1.0 — first release

One coherent enterprise, taken all the way through. Two, in fact.

### The tool

- **Deterministic worlds from a seed.** `worldloom build --seed 8128` generates
  an organisation, its people, systems, services, categories and store estate, a
  month-end close with an optional operational incident, the documents that
  episode warrants, and an evaluation set over all of it. The same seed produces
  the same corpus, byte for byte.
- **Two industry verticals.** The retail month-end close is the default;
  `--archetype midsize_adi` builds a fictional bank and runs the quarterly
  capital-return episode instead — challenged by the second line before
  lodgement, filed anyway under a lodgement norm, invalidated by a
  reconciliation break the daily liquidity cadence catches, and corrected by a
  *restatement* that leaves the original filing on the record. Both lodgements
  carry the same authority, so only the restatement relationship and fact
  validity can say which figure is current — and the evaluation set asks
  exactly that, paired with its temporal inverse so no retrieval bias answers
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
  baseline retriever per question family — direct, cross-artifact, numerical,
  causal, temporal, authority, abstention — so corpus hardness is measured, not
  asserted. `worldloom diversity` fingerprints document structure so a batch
  cannot quietly become one document photocopied.
- **Complete replay.** Every generative call — prose, plans, actor decisions —
  is content-addressed into a generation ledger that ships with the corpus.
  `--replay` regenerates byte-identically with no provider reachable, and CI
  proves it on every push, from the installed wheel as well as the checkout.

- **The communications fan-out.** Episodes publish their long tail: meeting
  minutes for the decisions that were taken in a room (the escalation that
  moved the retail close; the banking meeting that approved the return with
  the challenge on the table), email threads whose every message knows only
  what its sender knew at that moment, and per-unit close commentary from
  each division's finance partner. Minutes are fully structured — attendees,
  tabled material, decisions — and cost the narration loop nothing; threads
  and commentary are prose under the same fact constraints as everything
  else. New evaluation families ask who was in the room and who was told
  what, when.

- **Industry packs.** A world's shape and lore as a JSON file an agent (or a
  person) authors: units, product categories, site estate, scale, dated lore
  commitments in the engine's closed constraint vocabulary, and the fictional
  company's name — run through either engine, with the episode physics staying
  the engine's. `worldloom pack template` starts one, `pack targets` publishes
  which lore each engine actually consults, `pack check` lints inert
  commitments by name, and `build --pack` builds it. The pack embeds in the
  corpus recipe, so a pack-built corpus rebuilds itself with no pack file.
  Packs also own their texture: ``system_brands`` renames the engine's
  systems for the industry, and ``voices`` re-voices any role's prose —
  applied as per-role persona clones, so a voiced CFO never re-voices
  everyone sharing the CFO's register, and numeric temperament stays the
  engine's. Each engine publishes its slots and role keys through
  ``worldloom pack targets``, and the lint names unknown keys.
  Packs also re-voice the episode itself: every event sentence and prose
  fact an engine states is a keyed template (``worldloom pack texts``), and
  ``episode_text`` overrides them — slot-checked, riding the recipe, over
  causality a pack cannot touch. The insurer's incident is about claims and
  peril codes; the mutual bank's challenge names its own book.
  Shipped references: a general insurer on the close engine and a mutual bank
  on the challenged-return engine, both exercised in tests. Authoring the
  first packs surfaced and fixed three archetype-coupling leaks the telco
  experiment had predicted (`unit_gm`, the merch lead's manager, and the
  banking error's unit) — each engine now derives those from the world it was
  given.
  And packs re-voice the benchmark: every evaluation question and authored
  answer is a keyed template too (``EVAL_TEXT``, published beside the episode
  tables by ``pack texts``), overridden through ``evaluation_text`` under the
  same slot contract — the insurer's evaluation set asks about classes of
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
  Estimate" — a mid-size general insurer's quarterly reserving cycle, from
  the decided design record (`docs/design/insurance-reserving.md`): the
  development triangle as append-only observations, estimate chains whose
  superseded links were correct when made, and the estate's first permanent
  two-authority record — the actuarial central estimate and the booked
  reserve legitimately disagree, reconciled only by an explicit margin fact.
  Landing it triggered the rule of three: recipe steps are now a registry
  (`recipe.register_step`) each vertical seeds from its own module, and two
  thin-waist exceptions were paid down rather than a third added.

- **The world as graphs, and the defects only a graph could see.**
  `worldloom.graphs` reads the four graphs the schema always had and nothing
  ever looked at: the service/system dependency graph, the artifact provenance
  DAG across all four relationships at once, the fact supersession forest, and
  the reporting tree. It closed three real invariant gaps corpus-wide, for
  every vertical at the same time — a dependency cycle through more than one
  hop (the old check caught a service that depended on *itself* and nothing
  longer), a **forked supersession chain** (two facts replacing one, which
  leaves "what is current" ambiguous; the fact-layer walk built a dict keyed on
  the superseded id and let the second writer win, so this could never
  surface), and a provenance loop that uses a different relationship on each
  edge. `worldloom topology` is the reading: services ranked by *blast radius*
  and separately by *gates* — how much has no second path to what they serve,
  computed from dominator trees, because "lots of things depend on it" and
  "nothing routes around it" are different properties and a replicated platform
  has the first without the second. Every measure is an exact integer count
  with ties broken on id; there is no centrality score anywhere in it, because
  ranking by a float from an iterative solver is an argmax a different SciPy
  build can flip, and a rank that moves between machines is not a rank.

- **Near-duplicate detection that survives Gate 1.** `stats` has always
  reported an exact near-duplicate rate over passages, computed by comparing
  every pair — defensible at 120 artifacts and uncomputable at the 10,000
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
  batch — run independently for a hundred artifacts it hands every one of them
  index 0, which is how §7a's measured defect (120 artifacts, 11 distinct
  shapes) is produced in the first place. `assign` spreads shapes *across* a
  batch, carrying what earlier periods already spent so period two does not
  reproduce period one; `collisions` names which artifacts share a shape rather
  than counting how many shapes there were.

- **Time series behind the figures.** `worldloom.series` decomposes a
  period-keyed fact series into trend, season and residual, and names the
  periods the first two do not explain — read it as a corpus check, since an
  incident month that does *not* sit outside the pattern is a corpus asserting
  a disruption its own numbers do not show. Outliers are scored on median
  absolute deviation rather than a z-score, because outliers inflate the
  standard deviation they would be measured against and several of them mask
  each other; the decomposition refits once with the first pass's outliers
  replaced by what it expected, so one spike cannot tilt the trend every other
  month is then judged against. Two defects found by its own tests and fixed
  in the algorithm rather than the assertion: a local (Hampel) filter mistakes
  a genuine seasonal peak for a spike, and a robust scale of zero — routine
  when more than half a sample is identical, which generated figures often are
  — silently disabled the detector on exactly the obvious cases.

- **`build --trend`.** Monthly compound growth behind the comparative history.
  Without it a year of comparatives oscillates around a flat level, so a
  seasonally-adjusted series is flat by construction and no question about
  direction has an answer in the data. 0.0 multiplies by exactly 1.0 — an IEEE
  identity — so every existing corpus is byte-identical, asserted rather than
  reasoned about.

- **Two retrievers, so hardness claims survive a change of heuristic.**
  `evaluate --retriever {bm25,tfidf,both}` — the existing baseline was
  already BM25, so the second family is TF-IDF cosine with shared
  tokenization, and the scorecard reports per-family agreement: a family
  hard under both ranking families is structurally hard. On the shipped
  corpora, every designed-hard family is. `worldloom stats` reports what a
  buyer can recompute: length distributions, vocabulary, exact
  near-duplicate rates, fact-citation density — no invented benchmarks.

- **Name pools and locale as pack data** (ladder rung 4). Person names,
  site regions, and headquarters are engine defaults a pack may replace,
  linted against the archetype's headcount, riding the recipe. Found and
  fixed en route: financial facts stamped AUD units regardless of the
  company's declared currency, in three generators. The insurer example is
  no longer Australian, and proves it byte-reproducibly.

- **Narration at scale.** `worldloom narrate auto` drives the whole
  requests→generate→validate→accept loop in-process against the Anthropic API
  (`worldloom[llm]` extra), behind the same Provider contract and the same
  validators as hand-written prose. Every response lands in the generation
  ledger, so a narrated corpus still replays byte-for-byte offline — proven by
  a test whose fake provider answers differently on every call. The same
  command routes `--model gemini-*` to Gemini (`worldloom[gemini]`), and
  `--harness claude-code` / `--harness antigravity` put a whole agent harness
  behind each request — one fresh session per section, because the request is
  the whole of what an author knows. At size: `--concurrency N` fans sections
  out with byte-identical output at any worker count, accepted sections
  checkpoint incrementally so a crash never loses paid model output, and a
  preflight counts the work before the first call.

- **A benchmark that scales with the world.** `build --eval-density
  {low,standard,high}` grows the evaluation set and the fan-out layer from
  what the world already has — more categories and sites feed lookups and
  comparisons, more periods feed temporal and recurrence cases — reachability-
  gated like every existing case, with the default byte-identical to before.
  A three-period high-density grocery build carries `168` cases against `44`,
  and its hard families still score near zero, which is the point.

- **The haystack.** `build --distractors <n>` adds provenance-true noise:
  superseded drafts, derived personal copies, and routine notices — real
  authors, real lineage, real dates, citing only subsets of facts real
  documents already carry. No new facts means grading stays safe by
  construction: a distractor can never become the only home of an answer or
  make an abstention question answerable. Off by default; rides the recipe.

- **`/worldloom-design`.** The command for asks that arrive without a seed —
  "a hard corpus for insurance RAG" — driving elicit → decide engine/pack →
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
