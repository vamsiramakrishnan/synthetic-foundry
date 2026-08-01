# Building a world

You are about to run `worldloom build`. This is what each dial does and why it
exists — not the procedure, which is in `SKILL.md`.

## Seeds and determinism

```bash
worldloom build --seed 8128 --out ./corpus
```

`--seed` is the only source of randomness in the whole build. Same seed, same
organisation, same financials, same incident (or lack of one), same evaluation
set, every time — that is what lets CI regenerate a corpus from its ledger and
diff it byte-for-byte against what is checked in. A different seed is a
different company, not a variation on this one: names, headcount, store
count, and every figure are redrawn.

A seed alone does not determine a corpus. Every flag below that changes *shape*
or *schedule* is an input the seed's draws are conditioned on, and several of
them change the world substantially:

| Flag | What it moves |
| --- | --- |
| `--archetype`, `--inspired-by`, `--employees` | The organisation itself |
| `--period`, `--periods` | How much history exists |
| `--comparatives` | Adds prior-month actuals — a large number of extra facts |
| `--incident` / `--no-incident` | Forces the incident, which adds events and several artifacts that otherwise do not exist |

So "same seed, same world" holds only for the same flags. Reproducing a corpus
means recording the whole invocation, not just the number. If you need a second
independent world, change the seed; if you need the same world with more
history, run more periods against it rather than rebuilding.

## Archetypes

```bash
worldloom archetypes
worldloom build --archetype australian_grocery --out ./corpus
```

An archetype is a company *shape*: how many business units, what they sell,
their margin structure, how many sites each runs. `worldloom archetypes`
lists what is registered, with the unit/category/site/employee counts each
one produces. Pick one when the corpus needs to exercise a particular kind of
hierarchy — a single-division retailer poses different roll-up questions than
a four-division grocer with a New Zealand food arm.

The archetype also chooses the *episode*. Retail archetypes run the month-end
close; `midsize_adi` (a fictional Australian bank) runs the quarterly
capital-return episode instead — a second-line challenge filed over by a
lodgement norm, a reconciliation break caught by the daily liquidity cadence,
and a restatement whose original filing stays on the record. The retail-only
flags (`--incident`, `--periods`, `--comparatives`, `--actors`) are refused on
a banking build rather than silently ignored.

`--inspired-by "a large Australian grocer"` resolves a description to the
archetype of that shape — it is a lookup over phrases like "woolies" or
"large australian supermarket", not a data fetch. **No figure, name, or fact
about the real business is looked up or used.** The archetype it resolves to
contributes category structure and rounded scale (a store count, a margin
spread) that are characteristics of an *industry*, not of a company. Every
specific — the company's name, its actual revenue, its stores, its
employees — is generated from the seed exactly as it would be for any other
archetype. If the description matches nothing registered, it falls back to
the mid-size retailer rather than erroring, because a caller who names
something unrecognised is better served by a working world than a stack
trace.

## Scale

```bash
worldloom build --archetype australian_grocery --employees 50000 --out ./corpus
```

`--employees` overrides the archetype's stated headcount; the archetype's own
figure is otherwise used. The built organisation's actual headcount
(`worldloom inspect ./corpus` reports it as "Employees (modelled)") is far
smaller than either — only the roles a scenario actually needs get a person,
because minting fifty thousand `Employee` records nobody ever references
would bloat the corpus for nothing. "Employees (stated)" is what appears in
narrated prose as the company's headcount fact.

Scale is not cosmetic. `australian_grocery` has four business units, 34
categories, and over 1,600 sites against `omnichannel_retailer`'s three units
and 160 sites, and that difference is what lets a world exercise the deeper
roll-ups: categories summing to a business unit, sites summing to a business
unit, units summing to the group. A small archetype can still get every
individual check right while never posing the multi-level version of it,
because it has no fourth level to reach. If a corpus needs to test that a
retrieval system aggregates correctly across a real hierarchy, build a large
archetype; if it only needs one document to reason about, the default is
cheaper to narrate and just as coherent.

## Multiple periods

```bash
worldloom build --seed 8128 --periods 3 --out ./corpus
```

`--period` names where the *first* close lands (`YYYY-MM`); `--periods` runs
that many consecutive closes from there, each one a `MonthEndClose` chained
onto the last. This is the single most important scale knob and the one most
likely to be skipped, because a one-period build already produces a coherent,
validating corpus — it just cannot pose several kinds of question that a
real enterprise's document set answers routinely:

- **Recurrence.** A close calendar, a variance memo, an executive summary —
  these are documents an enterprise produces every month, not once. A
  one-period corpus has exactly one of each, which cannot distinguish "this
  is what a close calendar looks like" from "this is the only close calendar
  that has ever existed."
- **Superseded documents.** A close calendar published in March is
  superseded by April's — same artifact type, same purpose, and only one of
  them current. `worldloom validate` checks that a supersession chain is
  complete and correctly ordered (`supersession`, in the `temporal` group);
  that check has nothing to verify against a single-period build, because
  nothing has been superseded yet.
- **Evaluation question families a single episode cannot pose at all** —
  which version of a document is current, what changed between two periods,
  whether something was true in an earlier period even though it is false
  now. These need two points on the timeline to ask; `worldloom evaluate`
  cannot score a retriever on temporal-state questions a one-period corpus
  never generated.

`--comparatives` is a different axis: it backfills *prior actuals* for a
trend within the first period rather than running additional closes, so a
variance memo can show several months of history without those months
getting their own close calendar, workbook, or RCA. 11 gives a rolling year.
It only applies to the first period in a `--periods` run — a later close
asking for comparatives again would regenerate facts for months the corpus
already has, as a second, conflicting set, so `worldloom build` only ever
passes it to the first.

## History — the org changing over time

`--periods` advances the calendar; it does not change who works here. The
organisation changing — someone joining, someone leaving, a unit getting a
new leader — is a different kind of history, and is currently **library-only**:
reachable from Python (`worldloom.scenarios`), not from a `build` flag.

```python
from worldloom.retail import RetailWorld, MonthEndClose
from worldloom.scenarios import Departure

world = (RetailWorld(seed=8128).build()
         .run(MonthEndClose("2026-03"))
         .run(Departure("2026-03", "controller"))
         .run(MonthEndClose("2026-04")))
```

The three verbs beyond `MonthEndClose`, in `src/worldloom/scenarios.py`
(thin wrappers) and `src/worldloom/generators/personnel.py` (what they
actually mint):

- **`Hire(period, role_key, title, function, unit_key)`** — mints a new
  `PERSON` id and binds it into `world.roles[role_key]`, so a later scenario
  can ask for that role without knowing whether its holder has been there
  since the world was built or started this period.
- **`Departure(period, role_key)`** — the current holder of `role_key`
  leaves. Never a new id: the same `Employee` record comes back with `left`
  set, because the person who leaves is still the one person who was here,
  and every earlier document that names them has to keep meaning the same
  person. A successor is chosen deterministically (a direct report,
  preferred; failing that, a peer in the same function; ties broken on the
  lowest person id) — never invented, and the role table is rebound to them.
- **`Reorganisation(period, unit_key, new_leader_role)`** — a business unit
  gets a new leader without anyone leaving. Deliberately not `Departure` in
  disguise: the outgoing leader stays employed, so no `left` window closes
  and nothing moves except that one unit's leadership.

**Why a departure happens at the period boundary, not mid-period.** Each of
these runs at `_period_boundary(period)` — eight business days after period
end, past every artifact that period's close could still be writing. That
timing is what makes "who signed this" stay coherent without either the
`Hire`/`Departure` call or the `MonthEndClose` that follows it needing to
know a succession happened: the outgoing controller signs their own final
close because it was written before they left, and the incoming controller
signs the next one because by then the role table already points at them.
Placing a departure mid-period would need every artifact already in flight
for that period re-authored by hand the moment it landed after the change.
`worldloom validate` enforces the other half of this: `author_already_departed`
(in the `temporal` group) fails an artifact whose creation time falls on or
after its author's `left`, so a `Departure` placed wrong is caught, not
silently accepted.

`left` is exclusive, matching this check exactly: someone's last day is a day
they worked, so `left` names the first instant they are gone, not their last
instant present. `world.org_at(moment)` returns the roster employed at any
instant — the org chart's `as_of` — and is how you'd check who was actually
here before writing a scenario that depends on it.

## Founding milestones

A world already carries events and facts the moment `RetailWorld(...).build()`
returns, before any `MonthEndClose` has run: every dated commitment in the
company's lore (a replatform, a hierarchy remap, a norm adopted) gets a
matching `EnterpriseEvent` and `CanonicalFact` on the timeline, so the lore's
dated assertions are witnessed rather than merely stated. `worldloom inspect
./corpus --lore` shows the commitments; `--events` shows the milestones they
produced.

These facts use their own `MFACT` id sequence rather than `FACT` — deliberate,
not an oversight. The reference corpus's narration cites scenario-minted
facts starting at `FACT-0001`, by exact id, all the way through its workbook;
if founding milestones took even one number off the `FACT` sequence, every
fact a scenario mints afterwards would shift and that checked-in narration
would stop matching. A milestone fact costing nothing against `FACT` is what
keeps existing fact ids stable as this feature was added.

## Replay

```bash
worldloom build --seed 8128 --replay ./corpus -f markdown --out ./again
```

Regenerates narration from an existing corpus's generation ledger — every
prose request served from what was already recorded, with **no model call at
all**. This is what CI uses to prove a corpus reproduces byte-for-byte; run it
yourself before trusting that a change you made didn't quietly touch
determinism. `diff -r` the two corpora afterward — see `AGENTS.md` for the
exact invocation.

## Inspecting what you got

```bash
worldloom inspect ./corpus            # the summary table
worldloom inspect ./corpus --facts    # every fact, with authority and supersession
worldloom inspect ./corpus --events   # the timeline
worldloom inspect ./corpus --artifacts
worldloom inspect ./corpus --evals
worldloom inspect ./corpus --lore
```

Run with no flags, it prints the same summary table `build` already showed
you. Each flag lists that one collection in full — nothing in a corpus is
hidden from `inspect`. Reach for `--facts` or `--events` before writing a
scenario that depends on what already happened (a `Departure` needs to know
who is eligible to succeed); reach for `--lore` before adding a new
commitment, to see what already constrains the target you're aiming at.
