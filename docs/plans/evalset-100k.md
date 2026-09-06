# The 100k agent eval set: the next ten features

Ten features, in build order, that take Worldloom from "a connector contract
that admits every tool a 100,002-row agent eval set uses" to "one seed
produces the fixture corpus and the rows that drive it, with proofs".
Written to be executed by a model session, one feature per pull request, on
the same terms as [the builder revamp](builder-revamp.md). Read this whole
file before starting any feature, then read [AGENTS.md](../../AGENTS.md): it
is the harness contract and nothing here overrides it.

The order was derived, not chosen. Every claim about the set was computed
from the file; every claim about the package was read from the code and
carries its `path:line`; each feature states the rows it unlocks so the
ranking can be recomputed when the numbers change. Four readings were scored
independently and merged: how many rows a feature is the unique blocker for
per unit of size, how much of the fixture corpus it forces into existence
through the eval-first seams, how cleanly it rides the registration seams
this repository already has, and how many other features it unblocks.

---

## How to work

- **One feature, one PR.** Start from fresh `origin/main`
  (`git fetch origin main && git checkout -B <branch> origin/main`), open the
  PR as a draft, and do not combine features. A feature that does not
  converge inside one session stops, commits what passes the gates, and
  records what remains in the PR body. The two features marked XL are
  expected to take two PRs; the split is named in their text.
- **The gates run before every commit**, as CONTRIBUTING.md lists them:

  ```bash
  pytest -q
  ruff check .
  mypy
  worldloom validate retail-close
  worldloom docs --check
  ```

- **Byte identity.** Every feature here is opt-in. A default `worldloom
  build`, a default `evals construct` and a default `enterprise-evals build`
  produce the same bytes after the feature as before it. Anything that
  changes what a seed generates is a Generation change with its own
  CHANGELOG heading, and is treated as breaking for reproducibility.
- **Versioned data, not literals.** Shape catalogues, assertion catalogues,
  difficulty weights, skill signatures, locale vocabularies and request
  lexicons are data files under `src/worldloom/_data/` with a version in the
  key, on the pattern `narrative/prompts.py` set. A change is a new version,
  never an edit in place, because the version is a lineage component.
- **State, never labels.** An adversarial row is valid only when the corpus
  carries the state the row describes: the twin exists in both connectors,
  the passage with the embedded instruction is in the rendered bytes, the
  target record is archived, the principal is denied. A flag the runtime
  trusts without state is exactly the defect eval-first generation exists to
  prevent, and today's runtime trusts three of them.
- **The validator is never edited to pass.** A refused construction names the
  seam that owns the missing state. Change the design or the base.

---

## The target

The set is one file of 100,002 rows. Each row is a request in natural
language, the hidden plan an agent is expected to execute as a DAG of
connector tool calls, and the assertions a trace grader checks. No row
carries an answer in prose. The plan spans six connectors (Jira, Confluence,
ServiceNow, SharePoint, Salesforce, Drive), 73 tool names, 34 entity kinds
and 9 operations in 196 distinct combinations, and every node points at a
fixture in a shared fixture world.

| Tier | Category | Rows | What it exercises |
| --- | --- | --- | --- |
| 1 | `atomic` | 18,000 | one tool call, or a resolve step before one read |
| 2 | `single_connector_chain` | 10,000 | two steps in one connector, including map pipes |
| 3 | `cross_connector_pipe` | 20,001 | read in one connector, write in another |
| 4 | `multi_connector_dag` | 30,000 | fan-in, fan-out, diamonds, conditionals, chains six deep, shapes over five connectors |
| 5 | `adversarial_*` | 12,001 | fifteen families the agent must refuse, clarify, confirm or route around |
| 6 | `skill_*` | 10,000 | twenty-four named skills invoked eight ways |

Three layers of lineage sit under the rows. 26,405 skeletons (an abstract DAG
over connector and entity kinds) bind to 58,866 instances (a skeleton with
concrete fixtures, names and a locale), which expand to 100,002 variants (an
instance under a surface perturbation: a politeness prefix, a "keep it short"
suffix, a typo, lower case, an inverted clause order).

The grader vocabulary is 42 assertion types. Six are structural
(`dag_acyclic`, `tool_called`, `order`, `parallel_ok`, `per_item`,
`branch_exclusive`), eight are effects on connector state, and the rest are
behaviours: refuse, clarify before writing, confirm before a bulk write,
continue past a failed branch and report the gap, ignore embedded
instructions, run once and flag the recurrence, offer an alternative.

The fixture world is small and reused hard: 1,111 fixture ids in 41
namespaces of the form `{sp,dr,cf,jr,sf,sn}:{entity}:{NNNN}`, the busiest
referenced by 498 skeletons. Ten APAC locales each bind their own companies,
sites, programmes and native identifiers, and 959 of the 1,111 slots are
referenced from more than one locale, so the pool is shared and
locale-invariant rather than one world per locale. File fixtures must carry
the aspects the requests ask for, so the rendered bytes have to contain them.

Three properties of the set are exact, and a generator is held to them.

- **Difficulty is a closed form.** Rounded to one decimal, it is
  `0.5 x depth + 0.4 x width + 0.6 x connector_count + 1.0 per for_each node
  + 1.0 per conditional node + 1.5 when the row is adversarial`, plus a skill
  weight by invocation mode (alias, explicit and slash 0.2; missing param
  0.5; nonexistent 0.6; implicit 0.8; conflict 1.0; composed 1.2) and a
  surface weight (lower case, typo, dropped article and abbreviation 0.3
  each; inverted ordering 0.5; prefix, suffix and explicit source 0). That
  reproduces the difficulty of all 100,002 rows with no residual. Node count,
  tier, edge count and node flags carry no weight of their own.
- **A skeleton is a tool signature.** The 26,405 skeleton ids partition the
  rows by shape, per-node server, tool, entity, operation, modifiers, flags
  and edges, and no skeleton carries two signatures.
- **`parallelizable` is derived.** It is true on exactly the rows carrying a
  `parallel_ok` assertion, and the pairs named there are always
  edge-independent in the expected DAG.

Two defects in the source set are worth naming because a generator must not
reproduce them: 635 queries and 624 search payloads leak an unrendered
`{company}` placeholder, and 2,987 instance ids bind two different payloads.
A third is a deliberate departure: the `to`, `links` and `lists` payload
references use an identifier space that resolves to nothing in all 9,019
occurrences, so Worldloom mints node or fixture ids there instead and says so.

---

## What already holds, and what does not

The connector contract is complete for this set, and that is the reason the
ten features are what they are. The six definitions under
`src/worldloom/_data/connectors/` admit every one of the 73 tools, the 34
entities and all 196 combinations the rows use; `tool_for`
(`src/worldloom/connector_definition.py:284`) resolves each entity and
operation to exactly one tool, and `tests/test_connector_100k_coverage.py`
pins that vocabulary already. The generic emulator
(`src/worldloom/connector_emulator.py`) carries faults, a per-record access
list, archived-blocks-edit, idempotent replay on a frozen key, workflow
transitions and paging, all read from the definition rather than branched per
product. The reference runtime (`src/worldloom/connector_eval_runtime.py`)
consumes a row in the target's node shape, and the trace grader
(`src/worldloom/connector_trace.py`) decides sixteen of the 42 assertion
types from tool spans. The eval-first pipeline constructs a corpus for a
design and replays it from recipe verbs.

The gaps sit on top of that contract, and every one of them is specific.

- **The row producer does not exist.** Nothing mints the tier taxonomy, the
  42 named shapes, node modifiers, node flags, payload keys, the adversarial
  and skill objects, the surface layer or the lineage triple. `EvalStepSpec`
  carries id, capability, `depends_on`, connector, entity, operation and
  effect and nothing else (`src/worldloom/eval_design.py:147`). The
  enterprise planner's topologies are labels that never change the emitted
  DAG: `_plan` always emits read-N, transform, write, verify
  (`src/worldloom/enterprise_queries.py:332`).
- **The grader passes silently.** The dispatch in `grade_trace` is an
  if/elif chain with no else, so 26 assertion types contribute nothing and a
  row grades ok when only the handled subset passes
  (`src/worldloom/connector_trace.py:210`). `per_item` and `branch_exclusive`
  read a `ground_truth` key that no row carries and that no module writes.
- **Flags are never compiled into state.** The runtime reads `ambiguous`,
  `misattributed_system` and `gated` only
  (`src/worldloom/connector_eval_runtime.py:166,293`); `nonexistent`,
  `injected_content`, `confirm`, `fault_injected` and `denied` are ignored,
  emulators are built with no faults, and nothing in the package sets a
  record archived, plants an instruction passage in a body, or makes two
  connectors hold twins of one document.
- **Payloads are stored, not interpreted.** Of the 249 tool and key pairs the
  rows use, the runtime understands name, parent, dest, note, state and fmt;
  `aspect`, `search`, `to` and `ref_override` are dropped and the rest become
  opaque record fields. 50,028 of the 77,735 create nodes are refused by
  `required_on_create` because a row payload carries only a name, a priority
  and a parent. The 40,667 search nodes return the unfiltered entity pool.
- **The fixture world is one locale and eleven namespaces.** Only
  `australia` is registered of the ten locales
  (`src/worldloom/locales.py:1123`); the engine projections cover about
  eleven of the 41 namespaces; ServiceNow mints an `INC` number for every
  entity; `gdoc`, `gsheet` and `gslides` have no renderer; and a loaded
  corpus loses the size and hash of its rendered files because `World.load`
  never restores them.
- **Nothing ships proofs.** No command reaches `run_eval_row` or
  `grade_trace`, campaign export writes no proofs, and CI never invokes an
  eval export.

---

## The ten features

### 1. The eval DAG grammar

**One line.** Teach `EvalSpec` the shapes, modifiers and flags the set uses,
and derive metrics and difficulty from them.

**What.** `EvalStepSpec` grows `optional`, `for_each`, `conditional` (a
branch-group label carrying a structured predicate) and `flags`, all
default-off and dropped from the canonical payload so existing design digests
do not move. A shape catalogue at `src/worldloom/_data/evals/dag_shapes.json`
names the 42 shapes as node-and-edge templates with a classifier that reads a
DAG back to its name and a `compose` operator that joins two templates with
one bridging edge. `eval_metrics` gains exact `metrics_for` (node count,
depth as longest path, width as the largest level, `for_each` and conditional
counts, connector count), `independent_pairs` (which yields `parallelizable`
and the `parallel_ok` pairs), and `difficulty_for` implementing the closed
form above from a versioned weight table. `compile_demands` learns the rule
none of the analysis proposed and the corpus doctrine requires: a read,
extract, comment or transition step with an entity compiles to an evidence
demand carrying its aspect. Today `_from_steps` emits a mutation demand only
for writes and a search demand only for search-like capabilities, so a single
`get_page` design compiles to zero demands and is refused, which means the
read roots of tiers 1 to 4, most of the 1,111 slots, are forced by nothing.
Zero-step designs become legal for the `no_plan` rows.

**Why now.** It is the root of the dependency graph: 27 of the other 42
candidate features depend on it, and no producer of any tier can be written
without it. The modifiers are the difference between a label and a plan.

**Rows unlocked.** `resolve_then_act` and the other optional shapes, 9,471
rows; the map and bulk shapes, 12,487 rows; conditional and idempotent
create, 3,650 rows; the flags all 12,001 tier 5 rows need; `metrics` and
`difficulty` on all 100,002; `parallelizable` and `parallel_ok` on 25,656;
`no_plan` on 700.

**Corpus driven.** `for_each` forces search witnesses with at least two
matching records; conditional forces both branch targets to pre-exist and a
condition-bearing field on the read fixture; an optional resolve forces a
name that resolves to exactly one identifier, which is precisely the
uniqueness the ambiguity twins later violate on purpose.

**Lives in.** `eval_design.py`, `eval_demands.py`, `eval_metrics.py`, a new
`evals/shapes.py` (under `evals/`, not beside the existing `eval_shape.py`),
`_data/evals/dag_shapes.json`, `_data/evals/difficulty_weights.json`.

**Design.**

- Validator rules mirror the set exactly: `for_each` needs one parent
  (14,745 of 14,745 nodes), `optional` only on parentless steps (9,639 of
  9,639), conditional nodes share a group label.
- The classifier is total over the catalogue: every emitted DAG classifies to
  exactly one name, and an unclassifiable DAG is a refusal, not a default.
- Difficulty weights are data with a version in the key; changing one is a
  Generation change.
- `features_for` today has no caller in `src/`; fold it into `metrics_for`
  rather than leaving two structural-metric implementations.

**Acceptance.**

- Round-trip the shape catalogue: classify all 42 templates back to their own
  names.
- `difficulty_for` reproduces the difficulty of a fixture sample of rows from
  each tier with zero residual, and the test states the formula.
- `parallelizable` equals "has a `parallel_ok` assertion" on the sample.
- A design whose only step is a read compiles to one evidence demand instead
  of being refused.
- Existing design digests are unchanged: a test builds a pre-feature spec and
  asserts the digest.

**Size** L, expected as two PRs (modifiers and demands, then catalogue and
metrics). **Risk:** the classifier is the load the catalogue has to bear; if
two shapes collide the refusal must name both.

### 2. The eval row contract

**One line.** One typed row model with the lineage triple and one streaming
writer, so every producer emits into the same wire format.

**What.** A frozen pydantic `EvalRow` in a new `src/worldloom/evals/rows.py`
mirroring the 21 keys: nodes carrying `n1..nN`, server, tool, entity,
operation, fixture, the three modifiers, flags and payload; edges as
`[from, to]` pairs; connectors and entities sorted; operations in
first-appearance order; fixtures as the sorted unique set of node fixtures.
The validator admits a server, tool, entity and operation only through
`ConnectorDefinition.tool_for` and refuses a cycle. Beside it, an addressing
layer mints `skeleton_id` as a content key over the canonical tool signature,
`instance_id` over the skeleton with locale, vocabulary digest and fixture
ids, `variant` as the surface ordinal, and the row id through
`ids.format_id` with a per-tier minter so ids are contiguous per tier.
`write_rows` streams row by row through the pinned newline and key order that
`corpus.write_jsonl` already sets; `read_rows` streams back.

**Why now.** It is the contract features 5 through 10 emit into. Writing it
second means the producers are written against a checked schema rather than
against each other.

**Rows unlocked.** All 100,002, as the format. The lineage triple on all of
them: 26,405 skeletons, 58,866 instances, 100,002 variants.

**Corpus driven.** Every hash input names the world and vocabulary digest,
which closes the present defect where an enterprise query id is identical
across two different worlds (`enterprise_queries.py:336`).

**Lives in.** `evals/rows.py`, `evals/lineage.py`, `evals/__init__.py`,
`ids.py`, `corpus.py`.

**Design.**

- One assertion union, type-discriminated, built through the catalogue that
  feature 9 declares; until then, through a provisional constructor the
  catalogue replaces.
- A lint asserts the invariants the source set holds (no skeleton with two
  signatures) and refuses the ones it breaks (an instance id binding two
  payloads).
- Ids are minted in the planner's final emission order, so a resumed shard
  produces the same ids as an uninterrupted run.

**Acceptance.**

- Every emitted row round-trips through `run_eval_row` without a schema
  error.
- A row whose node names an inadmissible tool, entity or operation triple is
  refused with the triple named.
- Re-running the writer on the same rows produces identical bytes.
- The lineage lint refuses a fabricated instance carrying two payloads.

**Size** M. **Risk:** low; the shape is fixed by the file.

### 3. Connector definition v2

**One line.** Give tools a typed payload contract, entities a content model
and native identifiers, and make the emulator interpret both.

**What.** The largest single change, and one Generation bump rather than six.
`tool.params` is a dead `dict[str, str]` declared for every tool and read by
nothing; it becomes a typed payload block per key (type, required, option
alias map, shape) authored in the six JSON files and enforced by
`validate_payload` at `ConnectorEmulator.call` entry. A `derive` map per
entity supplies the fields `required_on_create` demands from context (a Jira
project from the parent key prefix, a Confluence space from the programme, a
SharePoint parent from the site folder, a ServiceNow caller and type), which
is what turns 50,028 refused creates into creates. `ConnectorIdDefinition`
lets an entity override the connector pattern with a range start, so
ServiceNow stops minting `INC` numbers for changes and problems. Entities
gain a typed content field (sections with bullets, a table of columns and
cells, slides, links, version, native fields) that the emulator interprets on
create, on each update mode, and on a read with an aspect; an adapter
projects that content into `ArtifactIR` so created and updated files
materialise as real bytes with a changed hash. `_write_fields`, today an
exclusion set that drops `state` and passes the rest as an opaque patch,
becomes a compiler keyed by operation and entity: a state on an update tool
becomes a workflow-field transition, a search phrase and aspect compile to a
predicate, an aspect on a get compiles to a section or field lookup,
`ref_override` resolves before the fixture identifier, and `to` and `links`
resolve node ids to the records those nodes produced. `capability_notes`,
declared and unused, gains a schema naming what a product cannot do.

**Why now.** Without it the payloads are decoration. Half the create nodes
fail, every search returns the whole entity pool, the transition rows can
never satisfy `state_equals`, and no file fixture can hold an aspect.

**Rows unlocked.** The 50,028 refused create nodes and the 80,570
`artifact_created` assertions that depend on them; the 40,667 search nodes;
the 646 transition nodes and their 1,296 `state_equals` assertions; the
96,377 aspect-bearing reads; 46,446 `field_or_section_updated`; 3,260
`links_present`; 3,046 `lists_created_keys`; the 455 transform nodes that
fail today for want of a create tool on the target entity; the 1,820 rows
whose families are declared capability gaps.

**Corpus driven.** It names what the pool must carry: a programme registry of
containers creates land inside, picklists and aliases, the aspect sections on
1,085 read fixtures, an item-by-quarter grid with named columns on 60 sheets,
decks of at least six slides, the native number every query uses, and initial
workflow states that make each transition legal.

**Lives in.** `connector_definition.py`, the six `_data/connectors/*.json`,
`connector_emulator.py`, `connector_payload.py`, `connector_eval_runtime.py`,
`connector_query.py`, `render/`.

**Design.**

- Payload validation ships advisory first, then strict per tool, so a
  half-migrated definition never blocks the emulator.
- The identifier override defaults to today's pattern, so an un-opted world
  writes the bytes it always did.
- Derived create values come from pool fixtures, never invented per call.
- The content model is a projection the render adapters round-trip, not a
  second document format; figures stay references so `validate` can still
  prove coherence.
- One definition schema version bump, one CHANGELOG Generation entry.

**Acceptance.**

- Every one of the 249 tool and key pairs validates against some contract, or
  is named as deliberately unsupported.
- A create node carrying only name, priority and parent succeeds for each of
  the six connectors.
- A transition row changes the workflow field and satisfies `state_equals`.
- A search phrase filters: the result set is smaller than the entity pool and
  contains the intended record.
- A file record updated through the content model has a different sha256 and
  size than before the update.
- Byte identity: a default build and a default `enterprise-evals build` are
  unchanged.

**Size** XL, two PRs (definition schema with contracts, derivation and
identifiers; then the content model, the payload compiler and
materialisation). **Risk:** the highest of the ten. It touches the file every
other connector consumer reads. Land it behind the advisory mode and keep the
default path untouched until the strict switch.

### 4. The APAC locale and fixture vocabulary

**One line.** Nine new locale presets and one authored table binding each
locale to its companies, sites, programmes, spaces, accounts, identifier
ranges and document-name templates.

**What.** `locales.py` registers Singapore, India, Japan, Hong Kong, South
Korea, Thailand, Indonesia, the Philippines and Malaysia beside Australia,
each differing on the axes that registry already keeps honest (calendar,
digits, week, currency, timezone token). Beside it, a new fixture vocabulary
table declares what a locale binds: the operating companies and their
`-Ops` site names, the programmes with their Jira keys and Drive folders, the
Confluence spaces, the customer accounts, the ServiceNow and Salesforce
number ranges, and the templates for document family names. This is the
vocabulary the request grammar and the fixture pool both read, so a name in a
query and a name in the corpus cannot disagree.

**Why now.** It is a root with no dependency and 22 dependents. Everything
downstream that names anything reads it.

**Rows unlocked.** The `locale` field on all 100,002 rows, and the
locale-bound names inside roughly 100,000 queries: about 22,000 site mentions
and 48,000 programme mentions, plus the roughly 11,300 rows whose suffix
carries a timezone token.

**Corpus driven.** Every fixture slot gets a home locale, company and
programme, and the shared-pool rule falls out of the table: names are fixed
per slot and identical across the locales that borrow them, which is what
959 of the 1,111 slots require.

**Lives in.** `locales.py`, `data/vocab/*.json`, a new `fixture_vocab.py`,
`_data/fixture-worlds/`, `company.py`, `packs.py`.

**Design.**

- The table is authored data with a digest, and that digest is an input to
  the instance id, so a vocabulary change is visible in the lineage.
- Locale keys stay the registry's long names; the two-letter codes the rows
  use are an alias table, not a second registry.
- Thin locales are legitimate: the source set gives Indonesia, the
  Philippines and Malaysia under 700 rows each, and the quota planner treats
  that as a weight, not an accident.

**Acceptance.**

- All ten locales build a world and validate.
- The same fixture slot renders the same native name under every locale that
  references it.
- A default build with no locale override is byte-identical.

**Size** L. **Risk:** low technically; the work is authoring breadth.

### 5. The request grammar and the surface layer

**One line.** Render the query text from slot-typed templates that share
their lexicons with the node payloads, then perturb it deterministically.

**What.** A new `eval_language` module with per-operation request templates
whose slots are typed (an aspect, a search phrase, a create name, a section
list, a location phrase, a note) and whose lexicons are versioned data files.
The same lexicon fills the node payload, so the query and the plan cannot
drift: the aspect the sentence asks for is the aspect the read node names.
On top of it, a pure function derives the eight surface flags from named RNG
streams: a prefix from the politeness pool, a suffix from the generic and
timezone-bound pools, an explicit source clause, an inverted clause order, a
lower-cased whole string, one adjacent transposition inside a content word
that is never an identifier, a dropped article, and the four connector
abbreviations. Each variant carries its own difficulty increment. A lint
refuses a rendered row that leaks a slot placeholder, doubles a token, or
whose canonical slot values are no longer recoverable from the perturbed
string.

**Why now.** The `query` field is the product. Both row realisers, tier 5 and
tier 6, render through it, so it precedes them.

**Rows unlocked.** The query on all 100,002 rows and the natural-language
payload values: aspects on about 96,000 read nodes, 40,667 search phrases,
create names and section, column and slide lists on about 82,000 creates,
notes on 13,000 comments. The surface block and variant on all rows, and the
36,732 rows at variant 1 or higher.

**Corpus driven.** Modest by design, and that is the point: the grammar
consumes the vocabulary and the pool's aspect lists rather than inventing
names. The lint is what stops the source set's 635 leaked placeholders from
being reproduced.

**Lives in.** `eval_language.py`, `_data/eval-language/*.json`,
`eval_instances.py`, `evaluate/phrasing.py` (share its discriminator-word
lint), `validate.py`.

**Design.**

- Perturbation never touches an identifier, a file name or a slot value that
  the plan depends on; the lint proves it by recovering each value.
- The typo is one adjacent transposition, matching the set's own mechanic.
- Tier 6 uses a reduced flag set, as the set does.
- The harness never calls a model, so this is templates and perturbation, not
  generation. `phrasing.findings` is the existing lint to copy.

**Acceptance.**

- Zero leaked placeholders and zero doubled tokens over a full generated
  shard.
- Every canonical slot value is recoverable from every perturbed variant.
- The same instance and ordinal produce the same variant text on two runs.
- Variant difficulty increments match the closed form.

**Size** L. **Risk:** the lexicons are wide; keep them data and let the lint
carry the quality argument.

### 6. The fixture corpus

**One line.** Document families whose sections are the aspects, a shared
1,111-slot pool minted as the demand executor, a manifest binding slot to
world entity to rendered bytes, and a validator that opens the bytes.

**What.** Four threads that only work together. Document families are
authored types (the statement of work, the vendor contract as PDF, the rate
and headcount and budget workbooks, the launch deck, the programme charter,
the requirements document, the runbook, the business review) whose section
headings are the aspects the queries ask for, with name templates resolved
from the vocabulary and a generic sheet, outline and N-slide compiler behind
the existing renderer registration seams. Google-native records join them as
a body class beside rendered files, so a requirements document can be a
`gdoc` and export to PDF through the existing renderers. The pool is a recipe
verb that reads the vocabulary and a per-namespace slot template and mints,
per locale and company and programme, the record graph as witnesses and
artifact intents: stable slot identifiers, native identifiers, parents and
links, per-slot aspect lists, the create-time containers, and search-set
membership so a fixture id can also name the result set of a phrase, with one
near miss per clause. Critically, its input is the summed demand set from
feature 1 and the quota plan, not a hand-authored template, or the pool is a
parallel generator that merely happens to agree with the eval. The manifest
is a corpus file written on export and restored on load, one row per slot,
carrying the rendered file path with size and sha256, the aspect locators,
the parents, the search sets and any adversarial state. The check is a
validator family that opens the bytes with the same libraries the renderers
use and proves each aspect locator resolves.

**Why now.** It is the corpus half of the deliverable. Nothing downstream can
be executed or graded against fixtures that do not exist.

**Rows unlocked.** Every row with fixtures, 99,302 of 100,002; the 41,715
rows touching a file fixture, of which 26,510 read one for an aspect; the
15,275 rows touching a Google-native record; every effect assertion needing a
pre-existing target.

**Corpus driven.** This is the feature where the doctrine is either kept or
lost. The manifest's aspect locators are computed by the same extractor the
check uses, or the manifest can claim an aspect the check cannot find.

**Lives in.** `doctypes.py`, `documents.py`, `render/`, `connector_data.py`,
a new `fixture_world.py`, `_data/fixture-worlds/`, `corpus.py`, `world.py`,
`validate.py`, `connector_seed.py`.

**Design.**

- Everything projects through the connector projection registry, so
  validator, emulator and exporters see one record set.
- The manifest closes the present defect that `World.load` never restores
  rendered files, so a loaded corpus projects hash-less file records.
- Native records appear only when a family is planned native, so un-opted
  worlds stay byte-identical.
- Failures are named violations in the existing report envelope
  (`aspect_missing`, `injected_leak`, `decoy_present`), so `worldloom
  validate` gates the fixture corpus the way it gates prose.

**Acceptance.**

- Every manifest row with a rendered file resolves each of its aspects in the
  bytes.
- A pool built twice from one seed is byte-identical, and replays from its
  recipe.
- A fixture referenced by rows from two locales carries one name and one
  identifier.
- A loaded corpus projects the same records, with the same hashes, as the
  in-memory build.

**Size** XL, two PRs (document families and native bodies; then the pool,
manifest and check). **Risk:** scale. Build the pool for one locale first and
prove the manifest and check before widening.

### 7. Adversarial fixture state

**One line.** Mint the state the fifteen families need as demands and
tactics, teach the emulator the three semantics that make it observable, and
compile node flags from state rather than trusting them.

**What.** New requirement, demand and tactic kinds, each with an executor
registered through `register_step` so every adversarial fixture replays from
the recipe: an archived target with a live successor (the first producer of
`Lifecycle.ARCHIVED`, which exists and nothing mints), a denied target
carrying an access entry, a twin set minting two records on two connectors
under one title, and the absence kind that is declared and dead today,
executed as a reserved-name catalogue no witness may take and every
projection is checked against. An injected-content tactic mints a body
carrying an instruction passage beside legitimate content and records the
passage and the write it tries to induce as an intentional error, routed
through the content model so the bytes behind a document fixture really
contain it. Three emulator semantics follow: name resolution keeps every
identifier per name and raises an ambiguous error with candidates when a
title maps to more than one visible record (today the index is overwritten
per name, so twins are structurally impossible); a validation rule may deny
rather than merely refuse, so a locked field raises 403; and the idempotency
window, which has no consumer, is honoured against the definition clock. The
runtime then compiles flags from state: a fault-injected node passes faults
to that server, a denied fixture supplies the access entry, a nonexistent
reference uses `ref_override` instead of the fixture's identifier, a confirm
flag requires a confirm request and response before the write, and ambiguity
derives its candidates from the resolver rather than the flag. A family
planner turns a base skeleton into a row for each of the fifteen families,
drawing details from data catalogues.

**Why now.** Tier 5 is 12,001 rows and the largest block of the grader
vocabulary. It is also the clearest test of "state, never labels".

**Rows unlocked.** All 12,001 tier 5 rows, and the roughly 6,700 that become
executable under the reference runtime with behaviour derived from state.

**Corpus driven.** Twelve cross-connector twin pairs, twelve archived pages
each with a successor, thirty-six denied targets, twelve injected bodies, a
reserved list of 358 names the pool must never mint, and the fault targets,
all recorded as intentional errors and access policies and all replayable.

**Lives in.** `eval_demands.py`, `eval_tactics.py`, `eval_witnesses.py`,
`models.py`, `connector_emulator.py`, `connector_eval_runtime.py`, a new
`evals/adversarial.py`, `_data/evals/adversarial_details.json`.

**Design.**

- The twin set is a labelled exception to the refuse-duplicate posture, and
  says so at the seam.
- Faults are validated against the definition's declared faults, which are
  dead today and accept an undeclared name.
- Ambiguity becomes a cross-check on the flag rather than its source: if the
  resolver finds one candidate, the row is refused.

**Acceptance.**

- Each of the fifteen families has a row that executes and whose behaviour
  comes from fixture state with the flag removed.
- A candidate corpus missing a twin, an archived successor or a denied entry
  is refused, naming the seam.
- The reserved names match no record title or file name anywhere in the pool.
- The injected passage is present in the rendered bytes of its fixtures and
  absent from every other.

**Size** XL, two PRs (tactics, witnesses and emulator semantics; then the
runtime compile and the family planner). **Risk:** the emulator changes touch
name resolution, which everything reads. Gate the multi-candidate path on
records carrying a twin marker.

### 8. The skill library

**One line.** Twenty-four named skills as authored signatures, realised in
eight invocation modes, lowered into demands so the corpus carries what they
read.

**What.** A skill registry loaded like the connector definitions: authored
JSON per skill with aliases, a slash grammar, a typed parameter, implicit
phrasings, and one fixed signature of nodes and edges. The validator resolves
every node through `tool_for` so tool names are derived rather than
re-authored, refuses a second signature per skill, refuses alias collisions
except the authored conflict pairs, and refuses a signature whose create
nodes cannot be completed from its parameter binding. The realiser binds the
parameter to a locale-bound fixture and renders the query through the
grammar's mode templates: the explicit name, an alias, an implicit sentence,
a slash command with flags, two skills composed in order through the shape
catalogue's compose operator, a conflict between two candidates that gates
every write, a missing parameter that asks for it, and a nonexistent name
that produces no plan at all. A lowering function turns a signature into an
`EvalSpec` so each skill's read fixtures are minted as witnesses and each
update target as a precondition record.

**Why now.** Tier 6 is 10,000 rows and five assertion types that exist
nowhere. The signatures are also the sharpest statement of what the corpus
must contain, because each names its connectors and entities exactly.

**Rows unlocked.** All 10,000: composed 2,352, alias 2,163, explicit 1,854,
implicit 1,433, slash 782, nonexistent 700, conflict 400, missing parameter
316.

**Corpus driven.** Per locale, at least one record in each of the 22
namespaces skill nodes touch (604 of the 1,111 slots are referenced by tier
6), the accounts and incidents and sprints the parameters bind to, and the
epic under which each skill's creates land.

**Lives in.** A new `skill_library.py`, `_data/skills/*.json`, a new
`skill_rows.py`, `eval_witnesses.py`, `evals/campaign.py`, the connectors
seam contract, `__init__._install`.

**Design.**

- The registry is exported through the seam contract so the names and
  signatures cannot drift from the grader.
- The shape of each skill comes from the classifier, never re-authored.
- Composition renumbers ids and adds exactly one bridging edge, which is the
  invariant all 2,352 composed rows hold.
- The campaign runs against the shared pool, not one world per spec.

**Acceptance.**

- Each of the 24 signatures resolves to real tools and executes end to end
  against the pool.
- A nonexistent name yields zero nodes, the `no_plan` shape and empty
  connector and fixture lists.
- Conflict and missing-parameter rows perform no write.
- The registry refuses a duplicate signature and an unauthorised alias
  collision.

**Size** L. **Risk:** authoring accuracy. Derive everything derivable.

### 9. Trace grader v2

**One line.** Close the assertion vocabulary, give behaviours a typed
channel, align spans to nodes, and decide the structural and effect families
from evidence.

**What.** The if/elif chain becomes a declared catalogue: one entry per
assertion type carrying its required keys, the evidence it needs, its node
scope and which families may carry it, as versioned data, dispatched by
lookup, with an unknown kind or missing key recorded as a failure rather than
a silent pass. Behaviours stop being caller-supplied strings and become typed
agent turns with a closed vocabulary (clarify, confirm request and response,
decline, report gap, report not found, report missing capability,
alternative, flag recurrence, correct system, invoke skill, ask parameter,
skill not found), each with a turn index so calls in one turn count as
concurrent. An alignment pass assigns unlabelled spans to expected nodes by
tool, entity, resolved reference and consumption of parent outputs, so a
trace from an external harness is gradable at all. On that base the
structural family is decided from the trace (including `per_item` from span
counts, which removes the dependency on a `ground_truth` key nothing writes)
and the effect family from the content model. The reference runtime honours
the modifiers, so `PROVEN_EXECUTABLE` means the loops and branches actually
ran.

**Why now.** It is what makes the set trustworthy rather than merely large,
and it is the prerequisite for the proof gate. Note the ordering hazard: a
catalogue landing without its branches turns tens of thousands of rows from
silent pass to unhandled failure, so the catalogue and the branches ship
together.

**Rows unlocked.** All 100,002 for `dag_acyclic` alone; the 26 types that
pass silently today, among them 46,446 `field_or_section_updated`, 12,989
`comment_posted`, 25,656 `parallel_ok`, 14,645 `per_item` and the five skill
types; roughly 22,000 rows carrying a behaviour assertion.

**Corpus driven.** Each catalogue entry declares the evidence it needs, and
that declaration is the contract the fixture generator satisfies before a row
may carry the assertion.

**Lives in.** `connector_trace.py`, `connector_emulator.py`,
`connector_eval_runtime.py`, `eval_reference.py`, `eval_execution.py`,
`connectors/__init__.py`, `_data/evals/assertions.json`.

**Design.**

- A test pins the 42 types the way `test_connector_100k_coverage.py` pins the
  73 tools.
- Family gating moves from hardcoded sets into catalogue data, so the 1,416
  tier 6 rows asserting no write and the 416 contradiction rows asserting
  clarification become checkable.
- The reference run emits its own turns, so it is self-consistent rather than
  satisfying `clarify_before_write` by construction as it does today.

**Acceptance.**

- An unknown assertion kind fails with `unhandled_assertion` named.
- Every one of the 42 types has a branch and a test with a passing and a
  failing trace.
- A trace with no node labels grades identically to the labelled one.
- Grading a reference run of a generated shard produces no unhandled kinds.

**Size** L. **Risk:** the flip from silent pass to failure is the risk;
measure the grade of a sample before and after and state the delta.

### 10. Assemble and prove

**One line.** A quota planner over the tier and shape space, a sharded
manifested export that replays, and a proof gate that executes every row
before it ships.

**What.** A quota plan declaring per-tier and per-category counts, the shape
mix per tier over the 66 populated cells, locale weights and a variant
policy, expanded by a planner that reuses the existing lane-fair round robin
so any bounded prefix is balanced, that uses the covering-array engine and
its hole detection so the coverage report stops being tautological, and that
refuses by naming an unfillable bucket rather than raising. A new `evalset`
sub-app writes the rows, the shared pool and a manifest carrying a plan
digest over seed, generator version, vocabulary digest, quota plan, connector
definition digests and assertion catalogue digest, with per-shard row ranges,
per-file hashes and resume. Then the gate: per emitted row, hydrate the
emulators from the pool, run it, and write one proof line; a row failing a
structural assertion is refused with the row and assertion named, so the set
never ships a plan nobody can execute. A grade command runs external traces
through the same catalogue.

**Why now.** Last because it consumes all nine. It is also what makes the
deliverable a deliverable rather than a library.

**Rows unlocked.** The tier, category and shape distribution of all 100,002
rows, and their delivery as one reproducible artifact with a proof per row.

**Corpus driven.** The plan is the pool's demand list: summing the read and
write roots over planned skeletons yields the per-namespace demand and the
adversarial slot quotas before a single fixture is minted. The manifest binds
the pool digest to the row set, so a pool change is a plan mismatch rather
than silent drift.

**Lives in.** `evals/quota.py`, `evals/export.py`, `evals/proof.py`,
`cli.py`, `covering.py`, `spaces.py`, `batch.py`, `recipe.py`,
`.github/workflows/`.

**Design.**

- The plan is a checked-in artifact and a recipe verb, so the set replays.
- Ids come from plan position, so resumed bytes equal an uninterrupted run.
- A CI step builds a small plan twice and compares the trees, mirroring the
  dispersed replay job.
- Refusal codes join the `_REFUSALS` registry; the command is documented and
  the generated reference regenerated.

**Acceptance.**

- The emitted distribution matches the plan exactly, per tier and per
  category.
- Two runs of one plan produce identical bytes; a resumed run equals an
  uninterrupted one.
- Every shipped row has a proof line, and a row that cannot execute is
  refused rather than exported.
- The coverage report names real holes on a plan that cannot be fully
  covered.

**Size** L. **Risk:** low, given the nine below it. The cost is measured
rather than assumed: reference execution ran at about 2.7 ms a row on the
current path, so a full pass is minutes, not hours.

---

## The order, and the first end-to-end run

The sequence is a dependency order, not a priority list. Features 1 and 3 are
roots and could be built in parallel by two sessions; 4 is a third root and
the only one that is mostly authoring. After that the graph narrows: 5 needs
4, 6 needs 3 and 4 and the demands from 1, 7 and 8 need 6 and 5, 9 needs 1
and 2 and the content model from 3, and 10 needs all of them.

**The smallest end-to-end run is 1, 2, 3, 4, 5, 6 and 10.** That yields one
seed producing a fixture corpus with rendered files, rows in the exact
21-key schema for tiers 1 through 4, and a proof per row: 78,001
of the 100,002 rows and without the adversarial or skill tiers. Feature 7
adds 12,001 rows, feature 8 adds 10,000, and feature 9 is what turns a
proof from "it ran" into "it was checked". A session that wants a visible
result early should build that subset first and treat 7, 8 and 9 as the
second wave.

Two ordering hazards are worth restating. The assertion catalogue in feature
9 must land with its branches, because a catalogue without them converts a
silent pass into an unhandled failure across tens of thousands of rows. And
the fixture pool in feature 6 must consume the demand set compiled in feature
1, not a hand-authored slot template; if it does not, the corpus is a
parallel generator that happens to agree with the eval, and the agreement
will not survive the first change to either side.

## What is deliberately not here

Every candidate considered is placed above, but four decisions are worth
recording because they were close.

- **Grading external agent traces is in, proving trajectories is not.** The
  grader work in feature 9 goes as far as deciding the 42 assertion types
  from spans and typed turns. Scoring a model's trajectory against a rubric,
  which the legacy enterprise path does with weighted floats, stays legacy
  and is marked as such rather than extended.
- **The narration path is untouched.** No row's text comes from a model. The
  harness never calls one, and the request grammar is templates and
  perturbation precisely so that the set replays with no provider.
- **The enterprise planner is not migrated.** It keeps its own query shape
  and its own command. Two eval schemas will coexist for a release; the new
  one is additive, and the older one is left alone rather than half-ported.
  A separate cleanup can retire the dead second command app
  (`enterprise_cli.py`, imported by nothing) and the disconnected helpers
  (`query_planning.py`, `field_manifests.py`, `eval_search.py`) once the new
  path carries its weight.
- **Reproducing the source set's defects is not a goal.** The leaked
  placeholders, the colliding instance ids and the unresolvable reference
  identifiers are named in "The target" so that a generator is measured
  against a corrected set, and the lineage note says where Worldloom departs.

## Verifying the numbers

Every count in this file came from the set itself or from the code. Two
properties are worth re-deriving before trusting a feature that depends on
them, because they are the ones that would quietly invalidate a design:

- the difficulty closed form, which reproduces all 100,002 values with no
  residual, and
- the rule that `parallelizable` is true on exactly the rows carrying a
  `parallel_ok` assertion.

Both are stated in "The target" in enough detail to recompute in a few lines
against a copy of the set.
