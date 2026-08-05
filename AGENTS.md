# Worldloom, for agents

You are the model. Worldloom is the harness.

This repository does not call a language model. It builds a coherent synthetic
enterprise deterministically, works out which documents that enterprise would
have, hands you a bounded request for each one, and then **checks what you wrote
against the facts**. If you restate a number, cite something you were not given,
or mention an entity that does not exist, your prose is rejected with the reason
and you try again.

That division is the whole design. You supply judgement and language. The harness
supplies truth, and refuses anything that contradicts it.

Written to be agent-neutral: everything below is shell commands and JSON files, so
it works from Claude Code, Antigravity, or any harness that can run a terminal.

---

## Setup

```bash
pip install -e ".[dev]"          # from a checkout; released: pip install "worldloom[all]"
worldloom --help
```

If the ask is loose — an industry, a purpose, a hardness bar, but no seed or
shape yet chosen — start one level up from the loop below:
`.claude/skills/worldloom/references/designing.md` is the decision guide for
turning that kind of ask into a build (stock archetype vs. authoring an
industry pack, which hardness families to force, deterministic prose vs.
writing it yourself), and in Claude Code `/worldloom-design` drives the whole
thing end to end — decide, author, build, measure, iterate, deliver. The loop
below assumes those decisions are already made.

## The loop

```bash
# 1. Build a world. Same seed, same world, every time.
worldloom build --seed 8128 --incident --out ./corpus

# 1b. Optional: choose each document's shape before writing any of it. Without
#     this, structure comes from a fixed outline and every memo looks the same.
worldloom plan requests ./corpus -o plans.json
worldloom plan accept ./corpus --from plans.json --model-id <your model>

# 2. Ask what prose is needed.
worldloom narrate requests ./corpus -o requests.json

# 3. Read requests.json. Write responses.json. (This is your job.)

# 4. Submit. Accepted prose is committed and recorded; rejected prose is returned
#    with the violated rule, and nothing is committed.
worldloom narrate accept ./corpus --from responses.json --model-id <your model>

# 5. Materialise it.
worldloom render ./corpus -f xlsx -f docx -f markdown -f jira -f confluence -f servicenow

# 6. Check the whole corpus agrees with itself.
worldloom validate ./corpus

# 7. Find out whether it is actually hard, not merely coherent.
worldloom evaluate ./corpus
```

Three more readings answer questions `validate` and `evaluate` cannot, and each
one is a different question — read all four before calling a corpus measured:

```bash
worldloom topology ./corpus              # what depends on what, and what nothing routes around
worldloom series ./corpus                # trend, season, and the periods neither explains
worldloom diversity ./corpus --near-duplicates   # which documents are one template
```

`topology` reads the estate as a graph: services ranked by *blast radius* (how
much falls over transitively when one does) and separately by *gates* (how much
has no second path to what it serves — a well-replicated platform has a large
blast radius and gates nothing). Its ranking is derived from the graph, so it
can disagree with the hand-declared `criticality_tier`, and a zero-hop
dependency chain means an archetype's service catalogue is a flat list rather
than a system.

`series` decomposes a period-keyed fact series into trend, season, and residual,
and names the periods the first two do not explain. Worth building a history for
first: `--comparatives 23 --trend 0.004` gives two years with a direction in
them, where the default flat level makes every seasonally-adjusted month look
like every other.

---

## Closing the loop

Narration is open-loop: every section gets one request and one attempt, and
nothing afterwards looks at what the corpus became. So the writer of section 47
never learns that sections 12 and 31 already said this, and a three-period
grocery corpus comes out with **44 of its 130 passages in 16 near-duplicate
groups**.

`worldloom refine` closes it. Measure what repeats, rewrite only what repeats,
and prove each rewrite moved:

```bash
worldloom refine ./corpus --harness claude-code   # drive the loop headlessly
worldloom refine ./corpus --check                 # measure only; exits 1 if anything repeats
```

The economics are the point: ~130 sections, ~16 duplicates, 16 rewrites. Each
one is briefed with the passage it must stop resembling and rejected — with the
measured similarity — if it did not get far enough away. The loop stops when the
measurement plateaus rather than when the budget runs out.

**Or hold the loop yourself.** `worldloom mcp` serves the same algorithms as
tools over stdio, and `.mcp.json` wires them into Claude Code:

```
measure_corpus  →  next_target  →  write it  →  submit_section  →  repeat
```

The `worldloom-refine` skill drives that loop, and a `Stop` hook
(`.claude/hooks/refine_guard.py`) refuses to let a session end while duplicates
remain — a skill can be forgotten mid-session, a hook cannot.

What does not change either way: `next_target` is chosen by the measurement, not
by anyone's sense of what looks repetitive, and `submit_section` runs the same
claim, reference and entity validators a first draft goes through *plus* the
similarity gate. Widening how much you may vary does not widen what you may
assert.

---

## Many companies at once

Varying the seed does not give you several enterprises. A seed decides names,
figures, and which month the incident lands in; it does not decide headcount,
span of control, reporting depth, trading calendar, or how fast an organisation
finds the cause of an outage. Five seeds produce **one company with different
names on the same twenty-three people** — a fine corpus and a poor dataset,
because a model evaluated against it has seen one enterprise five times.

```bash
worldloom mosaic --describe                       # what varies, building nothing
worldloom mosaic -n 5                             # the plan, still building nothing
worldloom mosaic -n 5 --incident --out ./mosaic
worldloom mosaic -e banking -n 5 --out ./banks    # or insurance
```

Each engine varies its own physics, because the parameters are its own: a
retailer's margin erosion and incident tempo, a bank's capital headroom and how
badly its filed risk-weighted assets understate the truth, an insurer's tail
length and how bad the news the actuary has to deliver is. Only the retail
engine varies a trading year, because `finance.generate` is the one generator
that reads one. Estate size is an axis for all three, so a mosaic of banks spans
9 to 101 nodes and the corpus can be asked what has a blast radius.

Each world lands in `./mosaic/world-NN/` with its own recipe, so any one of them
rebuilds alone. `mosaic.json` records the plan. Measured on five worlds: five
distinct organisation shapes, five distinct title sets, mean title overlap 0.72
against 1.00 for five plain seeds — and every world validates clean.

Candidates are covered with a low-discrepancy sequence rather than drawn at
random, because random points clump and a clump is a company shape the tool
never produces. They are filtered to what can actually be built — headcount,
span and depth are three numbers with two degrees of freedom, so the
over-determined combinations are discarded rather than rounded into feasibility
— and then the furthest apart are chosen by farthest-point traversal. That last
step is worth its cost: measured at 2.5× the minimum separation of simply taking
the first five candidates.

Deterministic throughout. World *N* uses `seed + N - 1`, so a mosaic's third
world is reproducible without building the first two, and a smaller mosaic is a
prefix of a larger one.

---

## Deriving the physics, optionally

A pack supplies *values* — this unit's share, that category's name. The ranges
every figure is drawn from belong to the engine. Four literals decide how long
an organisation takes to find the cause of an outage, so every Worldloom
incident ever generated has resolved at exactly one tempo, whatever the pack
said the company was.

The same is true of a company's trading year. One twelve-month index — a 21%
December — is applied to every world the retail engine builds, and since `base`
may only be `retail` or `banking`, that is every industry pack that is not
literally a deposit-taking bank. The general insurer shipped in
`examples/packs/` therefore wrote a premium book that peaked at Christmas.
`worldloom pack profiles` lists the trading years a pack may pick by name —
`flat` is the right answer for any business whose revenue is a book rather than
a till — or a pack may supply twelve months of its own, which must average one.

And a corpus had no way to say who answers for a number. Budgets attach to
business units, variances are reported and never judged, and the engine's one
ownership fact resolves to "unassigned" — so *who was accountable for the unit
that missed* had no answer anywhere. Lore can now say so:

```json
{"kind": "accountability", "target": "gm_md/financial.revenue.variance",
 "effect": "The MD answers for revenue against budget", "magnitude": 3.0}
```

`target` is `role_key/fact_kind` and `magnitude` is the tolerance band in per
cent. It mints a fact whose **subject is a person** — the first in the project —
carrying the measure they are judged on and how far it may move before anyone
asks. `worldloom pack targets` lists it alongside every other consulted target.

`worldloom pack params` prints the numeric ranges, now that they have names, and
`worldloom build --physics` overrides them. But a list of thirty-seven ranges to
fill in is the wrong instrument: they are not independent, and "retailer" or
"insurer" is a label, not a structure. So derive them instead, by descending the
organisation:

```
organisation → reporting → roles → objectives → measures
```

A layer is a *kind* of question, and a level is settled before the one under it
opens. How the business divides, then how it hangs together, then which titles
that implies, then what those titles are accountable for — and only at the
bottom do numbers bind to the engine.

```bash
worldloom probe open -p "A field-services business, 900 people, four regions."
worldloom probe next probe.json                     # the question, its layer, its bounds
#                                                     you answer it
worldloom probe accept probe.json --from answer.json
worldloom probe show probe.json                     # the graph as it stands
worldloom probe worlds probe.json -n 5              # what your answers committed to
worldloom probe resolve probe.json -o physics.json  # the ranges it settled on
worldloom build --seed 8128 --physics physics.json --out ./corpus
```

`probe next` exits 3 when nothing is left to ask, so a loop can tell "finished"
from "failed" without parsing prose. The physics ride the corpus recipe, so a
probed corpus replays byte-for-byte with no probe file on hand.

The shape of an answer is the point. You may **narrow** a question and never
widen it — the bounds you are given are what earlier answers established. If the
quantity is not primitive, do not pick a number: say so, and raise what it
follows from as sub-questions, each with a stated relation. Span of control is
not a number you know about a business; it is what the work's standardisation
and the supervision it needs produce.

**Link across layers.** Headcount, span and reporting levels are three numbers
with two degrees of freedom. A `link` states that, and the graph enforces it on
every answer that follows — in *both* directions, so a measure discovered at the
bottom can make a structure asserted at the top untenable.

The refusals are computed, not listed. Every relation is invertible, so the
whole graph is narrowed to arc consistency after each answer; if a range
empties, the answer is refused naming the chain that broke. Nobody wrote down
which combinations are illegal — they fall out of the relations you supplied.

Two things at the end. `probe worlds` first: a settled probe describes a *space*
of worlds, and this returns the ones furthest apart in it, deterministically. If
they all look the same you have over-constrained it; if they look incoherent a
link is missing. And a leaf that binds to no terminal parameter is **reported,
not dropped** — a quantity this world needed and the engine cannot read, which
is the only honest argument for adding one.

`source` records where a range came from. Sector statistics and published
benchmarks are priors and are welcome — with web search, use one rather than
your recollection of one. A named company's own figures are not: this corpus is
fictional and has to stay that way.

In Claude Code the same surface is MCP tools (`probe_open`, `probe_next`,
`probe_answer`, `probe_worlds`, `probe_resolve`), so a session holds the loop
itself rather than being called once per question.

---

## Composing the estate, optionally

A stock world runs four services on five systems, because nine is what the
episode names. `--estate small|medium|large` grows a real landscape around them
on the retail engine — layered, with placed chokepoints, and with the episode's
own services untouched so its causality is unchanged.

For a vertical whose vocabulary the engine does not have — banking's estate is
not called `click-collect-api`, and the insurer ships with no services at all —
you author it, and the graph is the grammar:

```bash
worldloom compose requests ./corpus -o estate.json    # what the company already runs
#                                                       you write the estate and its lore
worldloom compose accept ./corpus --from estate.json --model-id <your model>
worldloom topology ./corpus                           # read what you built
```

The request carries the company, its units, every existing service with what it
depends on, who may own something, the closed constraint vocabulary lore may
use, and the rules — so you can answer without reading the source. Propose
services and systems under keys of your own; the harness mints the ids.

The refusals are the point, and each is stated in the request before you write
anything: a dependency cycle through any number of hops, a dependency that
resolves to nothing, an owner who does not work here, a criticality tier the
graph contradicts, lore that constrains nothing, and an estate in which nothing
is a single point of failure. All violations come back at once, and nothing is
committed unless everything passes. Accepted compositions land in the generation
ledger, so a composed corpus replays with no provider reachable.

At any point, `worldloom status ./corpus` names the stage the corpus is at and
the exact command that comes next — resume from that rather than from memory.
`status`, `validate`, and every `accept` command take `--json` when you would
rather read data than parse a table.

Steps 3 and 4 repeat until every response is accepted. Rejection is normal and is
not a failure of the harness — it is the harness working.

For an industry that is neither retail nor banking as shipped, author an
**industry pack** — a JSON file carrying the company's shape, lore, and name,
run through one of the two engines. `worldloom pack template <engine>` starts
one, `worldloom pack targets <engine>` lists which lore is load-bearing,
`worldloom pack check` lints yours, and `worldloom build --pack pack.json`
builds it. The pack embeds in the corpus recipe, so a pack-built corpus
rebuilds byte-for-byte with no pack file on hand. Reference packs live in
`examples/packs/`.

The default build is the retail month-end close. `--archetype midsize_adi`
builds the banking vertical instead: a quarterly capital return that is
challenged by the second line, filed anyway under a lodgement norm, invalidated
by a reconciliation break the daily liquidity cadence catches, and corrected by
a *restatement* — a new lodgement that leaves the original on the record, which
is the one thing `revises` and `supersedes` both may not do. Same loop from
step 1b on; the retail-only flags (`--incident`, `--comparatives`, `--actors`)
are refused rather than ignored. `--periods` still applies — `N` consecutive
quarters, each one a `QuarterlyCapitalReturn` chained onto the last, stepping
three months at a time rather than retail's one.


---

## Actors, optionally

`worldloom build --actors` changes who decides what the incident's records say.
It takes `scripted` — the built-in deterministic actor, no network and no key —
or `agent`, which leaves every decision for you.

Without it, the planner writes the incident documents from the whole fact ledger:
it knows the root cause, the control failure, and the remediation, and it hands
each document the facts a document of that type should carry. With it, the
documents are produced by employees calling tools on **what they had actually
observed at the time**, and nothing else:

```bash
# You make every decision, one at a time, through the same kind of handshake
# narration uses. Roughly forty turns for this episode.
worldloom build --seed 8128 --incident --actors agent --out ./corpus
worldloom act requests ./corpus -o decision.json      # what one employee can see
#                                                       you write action.json
worldloom act accept ./corpus --from action.json      # validated before it changes anything
worldloom actors ./corpus --observations              # who could see what, when

# Or let the scripted actor run the whole episode, for CI and for a quick look.
worldloom build --seed 8128 --incident --actors scripted --narrate -f markdown --out ./corpus
```

```
pipeline fails
  → the service desk analyst is paged, opens the incident, puts up a status page
  → the engineer inspects the dependency chain and records a first assessment
  → the divisional finance partner reads the ledger and raises a close dependency
  → the controller is told, and writes a working note
  → the incident commander asks for evidence and names an owner
  → the engineer reads the ERP logs and confirms the cause
  → the controller decides the close moves, with the CFO named as approver
  → the platform lead raises two fixes and says which one fixes the control
  → the CFO writes a short summary, and leaves the control failure out of it
```

Four things are true of every step, and they are what the actor layer is for:

- **An actor sees a projection, never the world.** A provider is handed an
  observation and a tool catalogue. There is no accessor on either that reaches a
  `World`.
- **Only an accepted tool call changes anything.** Refusals are recorded with the
  rule they broke and change nothing — `worldloom actors ./corpus --rejected`
  shows them.
- **Canonical truth is still deterministic.** The pipeline fails because the
  operational generator says so, and the cause is the stale hierarchy mapping
  because 2024 lore made it so. An actor chooses *when the organisation finds
  out, who records it, and what gets written down* — never what happened.
- **It replays.** Every decision is content-addressed into the same generation
  ledger narration uses, so `--replay` regenerates the episode byte-for-byte with
  no provider at all.

The last one is why the CFO's summary omitting the control failure is worth
something: it is a citation that one person did not make, reproducibly, rather
than a rule in a template.

**One decision per exchange, and that is not a limitation to route around.**
Narration hands you every request at once because a memo's third section does not
depend on its second. An episode does: what the controller can see at 09:40
depends on whether the business partner escalated at 09:12, so the later
invocations do not exist until the earlier decisions are made.

Resuming needs no suspend format. Each call rebuilds the world from the corpus's
recipe, replays every decision the ledger already holds — the provider is never
asked for those — and stops at the first one nobody has taken. The ledger was
already shipping; it is now also the save file. Two consequences: `--model-id` is
pinned to the corpus on the first accepted decision, because answering turn nine
under a different id would miss every key before it and silently restart the
episode; and hand-editing a corpus mid-episode makes the rebuild produce a
different world from the one your earlier decisions were taken in.

In-process is the other route: implement `act(view, tools) -> ActorAction` and
the ledger, the policy checks, and the rejection loop all work unchanged around
it.

---

## Writing responses

`requests.json` carries everything you need. Do not go looking for other context;
if a fact is not in the request, you may not use it.

Each request looks like this:

```json
{
  "id": "ART-0003/By business unit",
  "artifact_type": "cfo_variance_memo",
  "section": "By business unit",
  "written_by": "Group Financial Controller",
  "voice": "precise, procedural, cautious",
  "audience": "group_cfo",
  "target_words": 130,
  "knows_as_of": "2026-04-08T09:40:00+00:00",
  "must_not_claim": [],
  "facts": [
    {
      "id": "FACT-0020",
      "statement": "financial.revenue.actual = 408,800 AUD_thousands",
      "authority": "system_of_record",
      "valid_from": "2026-04-07T16:40:00+00:00",
      "superseded": false,
      "required": true
    }
  ]
}
```

Answer it like this, one entry per request, `id` matching exactly:

```json
{
  "responses": [
    {
      "id": "ART-0003/By business unit",
      "text": "Food finished {{fact:FACT-0028}} against plan, the largest of the three shortfalls.",
      "claims": [
        {
          "text": "Food finished below plan by the largest margin.",
          "supporting_fact_ids": ["FACT-0028", "FACT-0029", "FACT-0030"]
        }
      ]
    }
  ]
}
```

### The rules, and why each exists

**Never write a number.** Every figure, percentage, and date goes in as
`{{fact:FACT-0028}}`. The renderer substitutes the value from the ledger at render
time, so a board deck and the workbook it derives from read the same entry and
neither holds a copy. A number you type is a copy, and a copy can drift. This is
checked lexically — any digit outside a reference is rejected.

**Every claim cites its facts.** A claim with no support is invalid, not merely
weak: there is nothing to check it against.

**Use only the facts in your request.** The request is the boundary. Citing a fact
outside it means you reached for something the author of this document did not
have.

**Respect `knows_as_of`.** This is when the document was written. You may not
anticipate anything discovered later — a triage page written at 09:26 cannot cite
a root cause confirmed at 13:27, and the corpus depends on it not doing so.

**A `superseded` fact is a past belief.** It was true when recorded and later
proved wrong. Refer to it as history — "it was initially recorded as…" — never as
the current position. This is how an incident RCA discusses the hypothesis that
turned out to be wrong.

**Invent no entities.** No company, person, system, or metric that is not in your
facts.

**Write in the given voice, for the given audience, at roughly the given length.**
This is the part that is actually yours. A CFO's controller writes differently from
a service desk analyst, and an executive summary is not an RCA.

### Aim for a document, not a list

The dullest possible correct answer is one sentence per fact. Prefer prose that
argues: lead with the position, group what belongs together, say what it means.
Sections partition the facts deliberately — a section headed "By business unit"
was given unit figures precisely so it does not restate the group position.

---

## What the harness will not let you do

`worldloom validate` prints the number of checks it ran — tens of thousands on a
large world — and treats any of these as a defect, not a warning:

- A total that does not equal the sum of its parts
- A variance that is not actual less budget
- A percentage that does not match the amounts it describes
- A document citing a fact that did not yet exist when it was written
- A reference to an entity, event, or fact that does not exist
- A reporting line that cycles, or a service that owns itself
- An author who cannot see the document they wrote
- Lore that constrains nothing

If you are tempted to make one of these pass by editing the fixture or relaxing a
check: don't. A validator that can be talked out of failing is decoration. Fix the
thing it caught.

---

## Determinism, and why it constrains you

A world regenerates byte-for-byte from its seed plus its generation ledger:

```bash
worldloom build --seed 8128 --incident --replay ./corpus -f markdown --out ./again
diff -r ./corpus ./again
```

The second command makes **no model call at all** — every request is served from
the ledger. CI enforces this on every push.

Two consequences for you:

- **Never introduce a clock, `random`, or a UUID.** Ledger keys are content
  addresses. `hash()` is randomised per process and is not one either; use
  `worldloom.ids.content_key`.
- **Prompt text is versioned data.** Editing a prompt in place silently changes
  what a seed means. Bump the version in `src/worldloom/narrative/prompts.py`.

---

## Where things are

| Path | What |
| --- | --- |
| `src/worldloom/models.py` | The thin waist. Every subsystem speaks these types |
| `src/worldloom/generators/` | Deterministic generation. No model, no clock |
| `src/worldloom/narrative/` | The contract with you: requests, claims, ledger |
| `src/worldloom/actors/` | Employees, their observations, tools, and the execution ledger |
| `src/worldloom/recipe.py` | How a world was made, so a corpus can rebuild itself |
| `src/worldloom/render/` | Formats. Read the IR and nothing else |
| `src/worldloom/validate.py` | The guardrails. Start here to understand the rules |
| `examples/retail-close/` | The hand-authored reference corpus. Frozen |
| `examples/grocery-close/` | Real agent-written prose, accepted whole. Replayed by CI |
| `.claude/skills/worldloom/` | The procedure, progressively disclosed by stage |
| `docs/build-order.md` | What gets built next, and the gate it must pass |
| `docs/generation-model.md` | Which engine owns what, and why |
| `docs/lore.md` | Lore as a constraint graph |
| `docs/actor-simulation.md` | LLMs as bounded employees, and the gates for it |

## Working on the harness itself

```bash
pytest -q
worldloom validate retail-close             # the reference corpus must stay coherent
worldloom docs --check                      # the docs still describe the CLI
```

`worldloom docs --check` is not a formality. `AGENTS.md` and the skill under
`.claude/` are what an agent reads *before* it knows anything, so a stale flag
there does not produce an error it can reason about — it produces a thinner
corpus and no sign that anything was missed. `tests/test_harness_docs.py` parses
every command in every agent-facing document and requires it to exist, and
requires every command to be documented somewhere.

Read `docs/build-order.md` before adding a subsystem. It sequences the work and
states an exit gate for each step, and the ordering is deliberate — several steps
exist specifically to stop a later one from being built on guesses.
