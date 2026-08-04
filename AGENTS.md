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
