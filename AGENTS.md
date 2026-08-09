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

# 7b. And whether it is hard for a retriever anyone would deploy, not only for
#     keyword matching. `all` adds a dense retriever beside BM25 and TF-IDF and
#     names, per family, whether it is genuinely hard or merely a lexical trap.
#     Optional extra; without it the dense column is skipped with a message.
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
```

```bash
# 8. Lay it out as a drive somebody could be pointed at, with its permissions.
worldloom workspace ./corpus -o ./drive
```

A corpus exports as one flat `artifacts/` folder of numbered files, which is
right for the harness — it reads the manifest and never looks at a path — and
wrong for what the corpus is *for*. An enterprise assistant indexes the folder a
document sits in, the title somebody typed, who owns it and who it is shared
with, and this corpus knows every one of those and put none of them on the
filesystem: 293 files in one directory with identical permissions.

`workspace` writes the tree that knowledge implies. Documents are shelved by the
function that owns them (`Policies/`, `Finance/Close/2026-03/`,
`People/Performance/`), periodic ones filed under their period and standing ones
at the top of their shelf. Filenames are what a person would have typed and
carry the subject, so four reviews in a month are four names rather than `(2)`
through `(5)`. A policy revised in place sits beside its replacement marked
`(superseded)`; a monthly calendar that supersedes last month's is not marked,
because that is the ordinary life of a periodic document rather than a
retirement. `permissions.jsonl` is one row per file — owner and every address
permitted to open it — which is the half a connector actually needs, since a
tree with no permission table tests retrieval and cannot test access.

Nothing is invented: every folder, title, owner and reader is derived from the
manifest, the roster and the access policies, and the corpus itself is not
touched.

```bash
worldloom workspace ./corpus -o ./drive --noise neglected
```

`--noise` makes the drive untidy the way real drives are: `Copy of X`, a
document dragged into `Shared/` or `_Inbox/`, somebody's `X FINAL` beside the
real one, an `_Archive/` leftover. Every extra file is a **byte-identical copy
of real corpus content**, never invented text — a drive's junk is not fabricated
documents, it is the same documents saved again in the wrong place under the
wrong name, and that is exactly what makes it hard: a retriever cannot tell the
copy from the original by reading it. A copy carries the permissions of what it
copies, so a misfiling is somewhere nobody would look and still readable only by
the people the original was.

Every junk file is **labelled** in `permissions.jsonl` with what kind it is and
what it duplicates. That is the whole difference between this and simply making
a mess: a benchmark scored against a drive it cannot account for cannot tell
"the assistant found the wrong copy" from "the assistant was wrong", and those
are different failures.

This is *filesystem* noise and deliberately not the same thing as
`--messiness`, which is content noise — a page nobody updated, two documents
disagreeing, an author who left. Both are real and they fail differently. A
corpus wanting a realistic archive wants both.

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

## The refine loop that is deliberately not here

Narration is open-loop: every section gets one request and one attempt, and
nothing afterwards looks at what the corpus became. This repository once closed
that loop — a `worldloom refine` command, MCP rewrite tools, a skill, and a
`Stop` hook — rewriting whichever sections a similarity join said were
near-duplicates of each other. It was deleted, and a future reader deserves the
reason rather than just the absence.

The loop was built and gated against `DeterministicProvider`, the template
writer CI uses, whose one-sentence-per-fact prose genuinely does repeat: three
closes from one template put tens of passages into near-duplicate groups. On
real model prose the problem it fought does not exist. A five-world proof run
measured the loop's target — passages sitting in a near-duplicate group — at
**zero in every world** (0/46, 0/50, 0/52, 0/46, 0/43). A writer that varies by
nature never gave the loop anything to do; the repetition was an artifact of
the deterministic fake, and no real writer reproduces it. The loop's headless
driver and API adapters were also the only code violating the first line of
this document, and they went with it.

The *measurement* survives the loop, because "what does this corpus repeat?" is
worth asking of any corpus whoever narrated it — not least as the check that
the finding above stays true:

```bash
worldloom diversity ./corpus --near-duplicates   # the groups, named
worldloom stats ./corpus                         # the same reading among the rest
```

**`worldloom mcp`** serves the read-only tools over stdio — `measure_corpus`,
`corpus_topology`, `corpus_series`, `validate_corpus`, and the probe tools —
and `.mcp.json` wires them into Claude Code, so a session can ask those
questions repeatedly, as data, without leaving the loop it is actually running:
writing prose through `narrate requests` / `narrate accept`. No tool writes a
corpus; every corpus write path stays behind the handshakes.

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

**From a premise, end to end.** `--probe` takes the axes from a settled probe
instead of the engine's defaults:

```bash
worldloom probe open -p "A specialty apparel retailer, 180 stores."
# ... answer its questions ...
worldloom mosaic --probe probe.json -n 5 --out ./apparel
```

The probe decides **what varies and between which bounds**; the algorithm still
decides **which N**. That division is the point — a model is good at arguing
that a business of this kind runs margins in that band and bad at picking five
points that cover a seven-dimensional space; a farthest-point traversal is the
reverse, and neither is asked to do the other's job.

Every parameter the probe bound becomes an axis over the interval it argued for,
and no world's range ever escapes that envelope. Axes the probe said nothing
about keep their defaults, so a probe that reasoned about margin and ignored
reporting depth still gets five different reporting depths. A probe that bound
nothing at all is refused rather than quietly falling back — it would report
success for work that reached no engine.

---

## Saying what kind of company it is, in one document

Nine surfaces answer "what kind of company is this?" — an archetype key,
`--employees`, a `--facet`, `--locale`, `--estate`, a `--physics` file, a
`--pack`, a vocabulary qualifier, and revenue, which can only be said by
writing a pack. Each is documented below and each is right; between them they
require you to know which of nine places each clause of a sentence belongs to,
and two interact in a way nobody predicts.

A **company specification** is that sentence as one document:

```bash
worldloom pack spec                        # the schema, and which registry each field draws on
worldloom pack spec --template             # a starter you can edit
worldloom build --spec company.json --seed 8128 --out ./corpus
```

```json
{
  "industry": "General insurance",
  "geo": "germany",
  "facets": {"listing": "listed", "competition": "fragmented",
             "maturity": "legacy", "trading_pattern": "steady"},
  "organisation": {"headcount": 26, "span": 5, "levels": 3},
  "leadership": [{"key": "chief_underwriting",
                  "title": "Chief Underwriting Officer",
                  "function": "Executive", "reports_to": "ceo"}],
  "identity": {"company_name": "Rheinmark Versicherung",
               "headquarters": "Munich, Germany"}
}
```

It is a **composer, not an engine**. Every field resolves into a seam that is
already load-bearing — `archetypes.get`, `vocabulary.spoken`, `facets.resolve`,
`parameters.with_overrides`, `roles.from_shape`, `locales.named`, `packs.Pack` —
so it adds no capability the flags lack. What it adds is that the pieces are
resolved *together*, and three things follow from that:

* **It refuses a description that contradicts itself, with the arithmetic.**
  "40bn of revenue across twelve employees" is refused naming both numbers and
  the registered shapes that bound them — the envelope is computed from the
  archetype registry (97,500 to 514,286 per head, widened by the factor the
  registry itself spans) rather than typed in, so registering a fifth archetype
  moves it. Premium margins in a fragmented market is refused by
  `facets.resolve`'s own empty-intersection arithmetic; an over-determined
  headcount/span/depth by `roles.from_shape`'s.
* **It reports what it cannot honour, rather than dropping it.** A trading year
  on an engine whose world builder has no `seasonality` field; a margin band on
  a vertical whose generators never draw from `retail.*`; a `geo` with no
  identity to carry its people and regions; a named rival, which nothing here
  mints an entity for. Same `unmet:` channel a facet's `wants` uses, and for
  the same reason.
* **It is never recorded.** A pack is embedded in the recipe verbatim, because
  the pack *is* how the world was made. A specification resolves to
  consequences and the recipe records *those*, exactly as `--facet` records
  consequences rather than facet names — so the corpus replays byte-for-byte
  after the facet registry, the archetype table or the locale presets move
  underneath it.

**A specification is not a pack, and the boundary is `company_name`.** A pack
is *identity*: a company's name, its divisions, their books, its voices, and
`pack_export` marks every one of those `PLACEHOLDER` because nothing derived
can honestly supply them. A specification is a *description* — true of a class
of businesses, naming no company at all. Supplying `identity.company_name` is
what lets a description compose *into* a pack, which is how a description names
the company at all — a `geo` reaches the people, the site regions and the head
office on its own, through `--locale`. Naming a `pack` instead uses it whole, and the
pack then wins over everything derived — the same precedence `Pack.regions`
already has over a locale's pool.

`--spec` refuses the flags it subsumes (`--archetype`, `--inspired-by`,
`--pack`, `--employees`, `--facet`, `--physics`, `--locale`, `--estate`) rather
than merging with them. `--seed`, `--periods`, `--incident`, `--messiness`,
`--timeline` and the formats are untouched: the specification says what the
company *is*, and those say what happens to it.

In Python the same surface is `sdk.described(document)`, which returns an
ordinary `Blueprint` — so a description can be crossed, swept and dispersed
like any other.

### How big the company is, which is not how many people it has

`organisation.divisions` is the field that makes a corpus bigger, and the
measurement says why. Raising `organisation.headcount` from 23 to 429 left
facts at 8,021, artifacts at 204 and evaluation cases at 596 — every one of
them unchanged, because 429 people were still managing the same three
divisions. The close fans out per division and per category, so the document
count follows the *structure*. Widening the same retailer from three divisions
to eight took facts from 604 to 990 and questions from 42 to 52 on the same
seed.

```json
{"archetype": "omnichannel_retailer",
 "organisation": {"headcount": 420, "span": 8, "levels": 6, "divisions": 8}}
```

A division arrives from `worldloom.divisions.POOLS`, keyed by industry, and it
is a real line of business rather than a relabelling — its own categories, its
own site formats, therefore its own row in every unit-level table, its own
close commentary and its own questions. Widening is additive: the archetype's
declared divisions keep their names, their categories and their *relative*
sizes, so 64/21/15 stays in that ratio however many arrive. Only the shares
renormalise, because a share is a fraction of group revenue and a fourth
division has to take something from somebody. Each addition is sized against
the company's *smallest* declared division and declines from there — equal
shares were the first rule and they gave Property a 12.5% share against
General Merchandise's 7.9%, an adjacent business outweighing the core it was
bolted onto.

It refuses rather than improvises in three places: narrowing below what the
archetype declares (that would silently remove every fact, document and
question a division owned), running out of pool (named with how many are
available, because a division called `Division 7` tells a reader the company is
synthetic without telling them anything else), and an industry with no pool at
all. `divisions.register` adds a pool for a fourth vertical.

The width rides the **archetype key** — `omnichannel_retailer+8div`, composing
with the vocabulary qualifier as `omnichannel_retailer+wholesale_club+8div` —
for the reason `vocabulary.spoken` qualified its own key: the key is the only
thing a recipe records about the shape, so a width carried anywhere else would
rebuild a three-division company from an eight-division corpus and report
success.

## Saying what kind of company it is, one attribute at a time

The four flags below are the difference between "a corpus" and "the corpus you
were asked for". Each is a no-op when omitted, so every corpus already built is
byte-identical, and each rides the recipe, so a corpus built with them rebuilds
itself with none of them on the command line.

```bash
worldloom pack facets                      # the dimensions, and what each value commits to
worldloom pack messiness                   # how well the archive is kept
worldloom pack locales                     # jurisdictions, and which half of one a build reaches
worldloom pack landscapes                  # what an estate is called, per vertical

worldloom build --facet listing=listed --facet maturity=legacy --seed 8128 --out ./corpus
worldloom build --locale germany --messiness lived_in --seed 8128 --out ./corpus
worldloom build --periods 12 --timeline turbulent --seed 8128 --out ./corpus
```

**`--facet`** says what the company *is* rather than what it has. A `Pack` is a
closed schema of twenty fields, each threaded by hand into a generator, so
"listed" could only ever have been a boolean nothing read. A facet is instead a
claim that emits **consequences into vocabularies that already exist** —
parameter ranges, lore, roles, a trading year, an estate size — so `listed`
mints an audit committee chair and a head of investor relations, raises
status-report density, and puts the audit committee in the filing approval
chain. Two consequences of that are worth knowing before you use it:

* Naming *any* facet settles *every* facet at its registry default. That is what
  makes claims composable, and it means `--facet listing=listed` alone also
  asserts `trading_pattern=steady` — a flat year, replacing the engine's 21%
  December. Say `--facet trading_pattern=christmas_peak` to keep it.
* Contradictory claims are refused naming both, with the arithmetic where there
  is any: a mutual runs 16-26% margin and a premium brand 48-62%, and no company
  is both. `worldloom pack facets` prints every exclusion before you hit one.

The recipe records the **consequences**, never the facet names, and that is the
stronger of the two: consequences replay this world byte-for-byte after the
registry moves under it, where a stored `listing=listed` would replay whatever
`listed` came to mean later while reporting success. What a facet implies and
nothing implements — an analyst consensus, a regulator with a pricing
determination — is printed as `unmet:` rather than dropped, the same evidence a
probe's unbound leaf is.

Facet **lore** is not in that category. `world.extend_lore` mints it into the
domain's own lore before the organisation is generated, because lore is an
*input*: it dates the business units, attaches persona traits, and decides how
much status reporting a close produces. The recipe records the **claims** it was
minted from — under `lore_claims`, not the finished commitments, whose ids and
dates belong to the world they landed in — so a faceted corpus rebuilds into
itself.

**`--messiness`** grades how well the archive is kept: `pristine`, `well_run`,
`lived_in`, `neglected`. Every corpus so far has been almost perfectly kept, and
only half of that was ever load-bearing — *no document may contradict the
ledger*, which does not change. That every document is also current, correctly
quoted, and owned by somebody still employed was never promised and is not
realistic. What keeps this a corpus rather than noise is that **every
imperfection is recorded**: a reader holding only the corpus can establish
mechanically that the stale page is stale and what the current position is.
Three kinds ship — a document that missed a correction it postdates, two live
documents disagreeing with a ledger that says which is right, and an author who
has left with nobody named in their place. Counts are a budget, not a quota: a
small world has fewer corrections to be stale about and the pass takes what it
can support.

### Line management produces documents

The organisation was modelled in full and used as a source of *bylines*. A
420-person retailer named 24 of 444 people anywhere in its corpus: a manager
three levels down existed, had a name, a function and a manager of their own,
and appeared in nothing.

```bash
worldloom build --seed 8128 --policies core --periods 3 \
  --hiring 3 --reviews 4 --out ./corpus
```

`--hiring` raises, approves, offers and fills vacancies; `--reviews` reviews
people. The hiring manager and the reviewer come from **everybody with a direct
report** — 73 people on a synthesised 420-person company against the dozen the
role table names — which is the whole point. Measured on three periods:
113 artifacts across 28 types with none above 21%, and 41 distinct people named
in 37 distinct titles.

Two things make these more than filler. **A requisition reads the company's own
rules**: its three-year commitment is checked against the delegation of
authority, and the lowest rung that covers it signs — so "was this approved at
the right level" is the first question here whose answer is in neither document
alone. And **the two performance records disagree on purpose**: the signed
review is an approved report countersigned one level up, the running one-to-one
note is an unofficial note carrying the view held before calibration, and the
authority ranking is what resolves them.

Both rounds mint a fifth access class on first use — an offer letter states one
person's salary, and none of the four classes an engine ships describes a
readership of one person and their line.

### The paperwork a company has, rather than the paperwork it produces

Every document in this corpus was **episodic** — a close ran, an incident
happened, a return was filed, and paperwork came out of it. Measured on a
twelve-period, eight-division build: 195 artifacts, of which 96 were the same
type with a different division's name on it, and not one of them was a policy.
An assistant asked "what is our expense approval threshold" or "how long do we
keep contracts" had nothing to find, because the company had no rules.

```bash
worldloom build --seed 8128 --policies core --out ./corpus   # five
worldloom build --seed 8128 --policies full --out ./corpus   # ten
```

A standing document is a different shape, and `worldloom.policies` says so in
three ways. **Nothing triggers it** — it is not caused by an event and does not
report a period; it is in force, from a date, until it is revised. **Its content
is parameters** — "receipts above 90 need a manager's approval" is minted as a
`CanonicalFact` with a number in it, so every question this repository can
already ask of a figure works on a policy unchanged, and forty-eight `policy.*`
kinds sit in `factkinds` beside every other. **A revision is supersession** —
the earlier threshold's window closes, the later fact records what it
superseded, and *the earlier document stays on the shelf*, which is what makes
"what was the limit before the revision" answerable rather than merely askable.

Money provisions are stated as a fraction of the company's own revenue and
rounded to a figure a policy would really name, so a 7.8bn retailer and a 2bn
insurer do not share an expense limit. A delegation-of-authority ladder that
stops climbing is refused rather than clamped, and a policy is dated no earlier
than whoever signed it joined — `form_units`' rule about a unit and its leader,
and `validate.author_not_yet_employed` found the violation the first time it was
not applied.

`--policies` is off by default and a strict no-op, so every corpus built before
it existed is byte-for-byte what it was. `policies.register` adds an area for a
vertical whose paperwork genuinely is its own.

### Who signed it

Every document was authored and none of them approved, which is not how a
company's archive works: "who approved the March pack for Fuel and Convenience"
is the first question a real reader asks. A signed document now carries an
**Approval** block — prepared by, approved by, name, role, date — in Markdown,
DOCX, PDF, PPTX and as a worksheet in XLSX. Ten distinct people were named
across an eight-division corpus before; nineteen after.

Who signs what is a table per vertical (`_APPROVED_BY` in each planner), because
who signs a prudential return is an argument about banking rather than a rule
about documents. The divisional close commentary is the one approval that fans
out with the company: eight divisions means eight different managing directors
signing eight different documents.

**Absence is a claim.** A ServiceNow ticket has an assignee, an email thread a
sender, a calendar is issued rather than approved; banking's RWA working paper
is unsigned *because* it is the contested-authority distractor, and internal
audit's review carries the Chief Internal Auditor's name and no countersignature
at all. A corpus where everything is signed is as unlike a real archive as one
where nothing is.

`validate.approvals` holds a signature to being one somebody could have given —
the approver exists, is not the author, and is permitted by the document's own
access policy. It found two real defects the day it existed and a third the
first time a unit changed hands, which is why `personnel.promote` now carries
the post's access to whoever holds it. Added, never substituted: the archive is
historical and the policy is current state, so striking a name off today would
retroactively invalidate every signature that person ever gave.

**`--locale`** puts the corpus somewhere. It reaches the *figure grammar*,
corpus-wide, so the DOCX, the Markdown, the PPTX and the retrieval index all
spell one number one way — `1.234,50` and `-1.234` in Germany, where before
every corpus printed `1,234.50` and `(1,234)` whatever its pack said. And it
reaches the *build*: the region labels in every site name, the pools the people
are drawn from, the headquarters city, the currency and the fiscal year. Claim
Frankfurt and you get Katharina Kirchgässner in Berlin at `Supermarket BW 001`.
A pack's own `name_pools`, `regions` and `headquarters` still win over the
locale's, the same precedence `Pack.regions` has always had.

The **working week** arrives too. August 2026 ends on a Monday, and four
working days later is Friday the 4th in Sydney and Sunday the 6th in Manama,
because the Gulf week runs Sunday to Thursday and has already spent its
weekend. The retail close, the bank's LCR observations and the insurer's
reserving dates all step on the corpus's own calendar.

**`--timeline`** replaces repetition with a history. `--periods 6` runs six
closes signed by the same twenty-three people, drawn from the same distribution:
one month photocopied. A density — `quiet`, `steady`, `turbulent` — schedules
incidents and org changes across those periods instead, so a controller who
departs in period 2 means periods 3-6 are signed by their successor, an incident
in period 3 and not period 4 makes "which month went wrong" answerable, and a
reorganisation moves who reports to whom *inside one corpus*.

```
worldloom build --periods 12 --timeline turbulent
  → 2026-03 MonthEndClose, Reorganisation · 2026-06 MonthEndClose, Departure
    · 2026-10 MonthEndClose, Departure · 2026-12 MonthEndClose, Reorganisation …
```

It is a flag rather than a command, and the reason is the recipe. Every scenario
a timeline can hold already records itself through its own `with_step`, so a
sampled history rebuilds from the steps it wrote — no new recipe verb, nothing
added. A `worldloom timeline` command applied to a built corpus would be a
second build path whose steps the recipe already describes, which is two
accounts of one history. So: `--periods` says how many, `--timeline` says what
happens between them.

Three refusals, each stated rather than silently absorbed. The schedule states
incidents in *both* directions once it schedules any, so `--incident` and a
non-`quiet` density cannot both decide. `--actors` is refused, because an
episode resumed from the ledger is driven one decision at a time and a history
is decided before the first one is taken. And the single-episode verticals are
refused, because their scenario takes no incident flag at all — a scheduled
incident would be dropped on the floor and the corpus would be `--periods N`
wearing a history's name. Hires are not sampled either: a new post's title is a
business decision, and a sampler inventing one would write the least plausible
sentence in the corpus.

**Keeping a derived world.** `mosaic` and `probe` both answer "what kind of
company is this?" and neither answer survives the command that produced it.
`worldloom pack export` turns one into an artifact that travels:

```bash
worldloom pack export ./kept --world 3 -n 5        # a mosaic world, kept
worldloom pack export ./kept --probe probe.json    # a settled probe's physics, kept
worldloom pack check ./kept/pack.json
worldloom build --pack ./kept/pack.json --physics ./kept/physics.json --out ./corpus
```

What comes out is a **bundle, not a pack**. A pack is texture — a name, units,
books, lore, voices. A variant and a probe are physics and shape. So it writes
`pack.json` plus the sidecars a pack is not allowed to hold (`physics.json` for
`build --physics`, `shape.json` for the org table and estate that have no pack
field at all), rather than widening `Pack` with a physics block and giving a
build two ways to say one thing. Identity fields come out `TODO`-marked and
`pack check` names every one: neither a Halton coordinate nor an interval graph
knows what the company is called, and a name invented there would be signed with
your own.

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

## Conversations, optionally

An event mints facts and makes documents necessary — and it makes **people
talk**. `--conversations` records that third output, which the corpus modelled
and never produced outside the actor runtime:

```bash
worldloom build --seed 8128 --incident --conversations --out ./corpus
worldloom actors ./corpus --observations       # who came to know how much, and how
```

```
What each employee came to know
 role                            first heard         facts  by channel
 Group Financial Controller      2022-01-01 04:00      600  duty 11, message 2, participant 584 …
 Service Desk Analyst            2022-01-01 04:00       18  duty 7, message 5, participant 2 …
```

Two files come out — `actor-observations.jsonl` and `actor-messages.jsonl` — and
between them they answer a question the fact ledger structurally cannot. A fact
carries one `valid_from`; knowledge carries one moment *per person*. Six hundred
figures reach the controller and eighteen reach the analyst, and neither of them
is wrong.

It adds no facts, no events and no documents. What it adds is:

- **A knowledge ledger.** Each fact reaches each employee through exactly one of
  the channels in `actors/observation.py` — witnessed it, was paged about it,
  owns the system that recorded it, was told, read it, or picked it up on the
  ordinary flow of work — and the channel decides both *when* and *how much the
  account is worth*.
- **Messages.** Derived, never invented: somebody is told where the routing
  table wakes them, or where the document plan makes them the author of
  something that event established. The second is the one that mattered — the
  controller's working note cites a root cause their role cannot read, so before
  this the corpus had authors writing about facts no channel could deliver to
  them.
- **Information-asymmetry questions.** *Which employee was first to have a record
  of this? By the time the last of them heard, who had already been able to act?
  Who told them?* Every answer is recomputed from the ledger, so none of them can
  be a sentence somebody wrote.

Four invariants, checked by `worldloom validate` on the shipped files rather than
on the code that wrote them: nobody knows a fact before it was true, nobody
learns anything outside their employment, nobody discloses what they do not yet
hold, and no author cites a fact they never heard.

It is opt-in and refused alongside `--actors`, which derives its own — two
producers appending to one knowledge ledger is two accounts of who knew what.

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

### Checking determinism somewhere other than seed 8128

CI proves byte-identity on four builds at one seed, on every push. That is one
point of a ten-dimensional configuration space, sampled repeatedly — and this
repository owns the algorithm for not doing that. `tools/sweep.py` points it at
our own QA: it enumerates engine × archetype × facets × locale × estate ×
trading year × periods × messiness × master-data *from the registries*, covers
the space with `dispersion.halton`, takes the furthest apart with
`dispersion.farthest_first`, and builds each one twice.

```bash
python3 tools/sweep.py --describe                    # the axes, building nothing
python3 tools/sweep.py -n 12                         # twice per config, in separate processes
python3 tools/sweep.py -n 12 --mode resident         # twice per config, in ONE interpreter
python3 tools/sweep.py -n 12 --mode archive          # working tree vs `git archive HEAD`
python3 tools/sweep.py --seed 8128 -n 12 --only <id> # replay one row exactly
```

`process` and `resident` answer different questions and neither subsumes the
other, so the nightly job runs `--mode process,resident`. Two fresh processes
share nothing but the seed, which is what catches a build depending on an
environment variable, a locale, or a hash seed. They cannot catch *leakage*
between builds — both start pristine, so a first build that poisons a
module-level registry has nothing to poison. Only a second build in the same
interpreter can see that, which is `resident`. (This file claimed the opposite
until review of PR #8 pointed out the hole; the fix is pinned by injecting a
module-level counter into `Rng.__init__` and watching `process` report
identical while `resident` reports the first differing line.)

`--mode archive` is the local gate — in a clean CI checkout the working tree
*is* `HEAD`. `.github/workflows/determinism-sweep.yml` runs nightly on a
rotating seed, so the corners covered move over time instead of being the same
eight forever. Every run prints its seed and each selected configuration, so
any failure replays exactly.

It is a tool, not library code: nothing under `src/` imports it and it adds no
dependency.

### Whether the corpus is hard, or only hard for keyword matching

Every difficulty number this project published before now came from BM25 and
TF-IDF — two ranking families and **one idea**, that relevance is word overlap.
A family they both fail is either structurally hard or merely a *lexical* trap
that any deployed retrieval stack walks past, and nothing here could tell those
apart.

```bash
worldloom evaluate ./corpus --retriever all --vectors ./corpus/vectors.json
python3 tools/measure_retrievers.py ./corpus              # every pin, one table
python3 tools/measure_retrievers.py ./mosaic --mosaic     # or a whole mosaic
```

Both print a second reading beside the agreement table: per family, **genuinely
hard** (lexical and semantic both fail), **lexical trap** (semantic solves it —
so it was never difficulty, and a corpus card counting it is overstating
itself), **semantic blind spot**, or **solved by everything**.

The retriever is an optional extra (`pip install "worldloom[embeddings]"`) and
absent-friendly: without it the dense column is skipped with a message and the
lexical readings still print. Its vectors are pinned to a model *revision* and
cached to a sidecar as quantised integers, so the measurement replays
bit-identically on a machine with no model at all — the generation ledger's
argument, applied to a retriever. `src/worldloom/evaluate/embedding.py` makes
that case in full, and
`.claude/skills/worldloom/references/evaluating.md` has the reading.
