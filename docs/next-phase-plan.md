# Plan: make *what happens* as authorable as *what the company is*

A handoff for a fresh agent session. Read AGENTS.md first (it is the
harness guide), then this. Merged PR #3 is the record of how the current state
was reached and why the refine loop and API providers are deliberately absent.

## Where things stand

The company layer is open: specification document (`company.py`), facets,
packs, authorable document types (`doctypes.py`), vocabularies, locales,
physics registry. The narration contract is proven **source-blind**: three
writers who never opened `src/` narrated 115 sections in 1/2/1 rounds with one
violation total. The episode layer is the last hardcoded thing:
`MonthEndClose`, `QuarterlyCapitalReturn`, `QuarterlyReserving`, the
procurement cycle and `Hire`/`Departure`/`Reorganisation` are bespoke Python.
`scenarios.py`'s own docstring defers a scenario grammar "until a second
vertical shows which parts repeat," and there are now four verticals.

## Phase 0: small debts first (one agent, half a day)

1. Three sentences in the narration rules text, found by the blind cohort:
   state the claim-coverage **converse** (every `{{fact:ID}}` referenced in
   prose must be cited by some claim, the one violation of the whole run);
   say whether job titles and background-only names count as entities in the
   capitalised-run rule; say what a reference renders as (writers guess the
   suffix and write grammar around it). Bump the prompt version.
2. **Completed:** `--employees` reaches every engine's authoritative company
   headcount, and `--headcount-end` produces recipe-backed workforce changes
   over a retail timeline. Named employees remain the bounded role graph;
   aggregate size scales sampled episode density logarithmically.
3. Insurance is capped at one period (`insurance_scenarios.py`); the cap is
   what makes its quadratic checks unmeasurable. Lift it before Phase 2 makes
   episodes cheap, or its grammar port will inherit the cap.

## Phase 1: the autopsy (read-only, one agent)

Dissect all four episodes plus Hire/Departure/Reorganisation for the shared
spine. Expected shape (verify, don't assume): *phases → facts minted (kind,
authority, validity window, supersession) → events linked to facts → artifact
intents linked to events → evaluation cases → checks*, plus period arithmetic
(`operations.business_days_after`, calendars), the lore hooks
(`likelihood_multiplier`, `density_adjustment`, `filings`), and carry-forward
(procurement's `open_shortfall` is the only current instance: this month's
fact derived from last month's, hand-coded). Deliverable: a written grammar
that expresses all four episodes, and a list of what genuinely cannot be data.

## The unit of authorship is the line of business

The grammar's root object is not the episode: it is the **LOB**. A harness
authors a line of business, standard (finance, HR, procurement, the same in
every industry, shipped as a data library) or vertical-specific (underwriting,
merchandising, claims, authored per world), and one LOB spec declares the
whole causal chain:

- **its people**: roles and titles (the role-table seam exists; the per-unit
  role minting in `organisation.py`/`roles.UNIT_ROLES` is still hardcoded and
  must open),
- **their responsibilities**: declared edges from a role to the fact kinds it
  answers for and the artifact types it authors or approves. Responsibility is
  the cohesion primitive: from one declared edge the engine derives authorship
  (planning), access (policies), accountability (`ConstraintKind.
  ACCOUNTABILITY`), the who-signs check, and the "who is accountable for this
  miss" evaluation cases. Never five hand-written tables that can disagree,
- **its episodes**: which it participates in and what it contributes: facts
  minted, events raised, carry-forward held,
- **its artifacts**: the doctypes it files (seam exists),
- **its lore hooks**: what its history makes likelier, denser, or forbidden.

Employees are then *triggered per LOB*: headcount and spans come from the
physics, titles from the LOB's roles, and every person exists because some
declared responsibility needs an owner, not because a generator had a loop.
The chain the corpus must keep whole: LOB → roles → responsibilities →
episodes → events → artifacts → lore, every link declared, every link checked.

## Phase 2: `worldloom.episodes` (the build)

An episode spec the harness authors, pack-carried like doctypes so it rides
the recipe and replays. Core design commitments:

- **Declaring a fact kind means declaring its invariants** (sums-to,
  supersedes, holds-at, precedes, reconciles-against), and the checks are
  *derived* from the declaration, never hand-written per kind. That is the
  seam that holds cohesiveness: an authored episode physically cannot mint a
  fact the validator does not police. A lint refuses a kind no invariant
  covers (same argument as doctypes' lint, which is the pattern to copy).
- **Carry-forward as declared slots**: this kind, next period, derived thus.
- **Structured + unstructured per event**: tables compile from facts,
  sections go to `narrate requests`: the spec declares which of each.
- **The proof obligation**: the four existing episodes re-expressed in the
  grammar, building **byte-identical** corpora. Doctypes earned trust by
  porting all 30 types; episodes earn it the same way. What cannot be
  expressed stays Python and the grammar documents why.

## Phase 3: close the five seams procurement named

`parameters.DEFAULTS` (wants `parameters.register(spans)`; today a pack
cannot tune a new vertical's physics at all), `landscape.LANDSCAPES`,
`mosaic.ENGINES`, `locales.industry_suffixes` (falls back to the retail pool
silently), and the package-import registration. Each is a closed literal with
its consequence already visible in the procurement modules' comments.

## The ontology, settled (owner's terms)

**Process**: the recurring type, declared once: P2P, O2C, month-end close, a
recruitment drive, the annual performance survey. What `episodes.py`'s spec
actually declares; a LOB *has processes*. **Episode**: one bounded run of a
process, start to end, over a period; history "until now" is the ordered
episodes, carry-forward linking them. **Events**: points in time inside an
episode. Events mint **facts** (system-of-record standing is a fact's
authority) and make **artifacts** necessary, including people talking:
threads, minutes, working notes are artifacts, and the dormant actor layer
(observations, messages, who-knew-what-when) is the deeper form waiting for a
consumer. Code naming should converge on this: the spec is a process, a run
is an episode.

## Who authors a process, and how it binds: settled

Processes are **harness-authored per company**, through the same seed cascade
as LOBs, with the company's context (engine, facets, lore) in the brief so
proposals are contextual; every stage is refusable by the grammar's lint. A
standard library (close, P2P, recruitment) ships as data like standard LOBs.
**Participation derives**: a process's steps declare the fact kinds they
mint, a responsibility edge declares the kinds a role answers for, and who
participates in a process is the join, never a second table that can
disagree. **Ordering is declared**, because it cannot be derived: a process
declares role slots (preparer, challenger, approver) and the LOB binds its
roles to the slots: the slots are the process's vocabulary, the binding is
the company's.

## Engine vs LOB: the distinction, settled

An **engine is an industry frame**: what the company sells, its physics
ranges, its regulatory episodes, its evaluation families. A **LOB is a
function** (roles, responsibilities, episodes) attachable to *any* engine.
Finance, HR and procurement are standard LOBs every industry has; claims and
underwriting are vertical LOBs an insurer's engine ships.

Procurement is today both an engine and a standard-library LOB, which is the
conflation made visible. The engine was the right vehicle for proving the
registration seams and the three-way match; the destination is different:
once the EpisodeRunner lands, procurement's cycle (PO → GRN → invoice →
match → accrual) becomes an *episode contributed by the procurement LOB*,
running inside any engine's world, its GRNI accrual feeding that engine's
own close: which is what "composes with finance" always meant. The
procurement engine then either retires or shrinks to a demo. No new
business function should ever be built as an engine again: engines are for
industries, LOBs are for functions, and a LOB's episodes ride the grammar.

## Phase 4: the proof

A harness authors an industry this repo has never modelled (a hospital, an
airline) as an episode spec plus declared kinds, with zero core edits. Multi-
period, carry-forward, structured and unstructured artifacts, narrated
source-blind, validating clean, replaying byte-for-byte. If that works, write
the skill that advertises it. If it does not, the failure is the finding:
report which part of the grammar broke rather than widening core to pass.

## Non-negotiables (unchanged from the whole project)

- Determinism: no clock, no `random`, no UUID, no set-iteration deciding
  anything; named `Rng` streams; new draws get new streams.
- Byte identity: every default build identical, verified against a
  `git archive HEAD` tree, never asserted.
- Agent teams verify on isolated trees (HEAD + only that agent's files),
  stage by explicit path, and report what did *not* move as plainly as what
  did. A capability reported as missing while it works, and a check weakened
  to pass, are both worse than the defect they hide.
- `pytest -q` and `worldloom validate retail-close` before every commit.
