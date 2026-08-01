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

- **Narration at scale.** `worldloom narrate auto` drives the whole
  requests→generate→validate→accept loop in-process against the Anthropic API
  (`worldloom[llm]` extra), behind the same Provider contract and the same
  validators as hand-written prose. Every response lands in the generation
  ledger, so a narrated corpus still replays byte-for-byte offline — proven by
  a test whose fake provider answers differently on every call.

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
