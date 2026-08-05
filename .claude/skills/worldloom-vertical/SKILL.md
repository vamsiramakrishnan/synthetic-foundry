---
name: worldloom-vertical
description: Author a whole new industry vertical for Worldloom — its own episode, documents, checks and benchmark — through the registration seams, without editing core. Use when a corpus needs a business this repository does not model (a hospital, a manufacturer, an airline), when an industry pack cannot express what the episode actually is, or when asked what adding a fourth engine to this codebase would cost.
---

# Authoring a vertical

A **pack** re-voices an existing engine: new names, new units, new lore, same
episode. A **vertical** is a new episode — a different thing happening, with
its own fact kinds, its own documents, its own invariants and its own
benchmark. If the answer to "what happens in this corpus?" is not a month-end
close, a capital return, a reserving valuation or a purchase cycle, you are
authoring a vertical.

Do not start here. Read `.claude/skills/worldloom/references/extending.md`
first for the generation boundary, and `docs/build-order.md` §7a for why the
seams exist. This file is the *cost*, measured, and the order of work.

---

## What it actually costs

Three verticals have been added since the first. Measured, excluding tests:

| vertical | files | lines |
|---|---|---|
| insurance (quarterly reserving) | 7 | 2,823 |
| procure-to-pay (purchase cycle) | 7 + 124 lines of archetype | 3,630 |

The shape is stable, and that is the useful part: **seven files, and the same
seven every time.**

| file | what is in it |
|---|---|
| `<vertical>.py` | the world builder, the lore, the check group, the domain registration |
| `<vertical>_scenarios.py` | the episode as a frozen dataclass with `run`, plus `recipe.register_step` |
| `<vertical>_documents.py` | artifact intents, custom compilers, `register_artifact_types` |
| `generators/<vertical>_org.py` | role table, personas, systems, access policies |
| `generators/<vertical>_<figures>.py` | pure numbers, no facts |
| `generators/<vertical>_<episode>.py` | events and facts, no numbers |
| `generators/<vertical>_evaluation.py` | the benchmark families |

Plus one archetype in `src/worldloom/archetypes.py` (data only) and one import
line in `src/worldloom/__init__.py`. Budget a day and expect the episode
design — *what happens, and what disagrees with what* — to be most of it.

---

## The seams that work

Four registries, and a domain module reaches core through these and nothing
else:

```python
domains.register_domain(Domain(...))                 # how a build finds you
recipe.register_step(name, arg_names, build)         # your scenario as a recipe verb
documents.register_artifact_types(standing=, lags=, outlines=, compilers=)
validate.register_domain_checks(name, checks)        # your invariants
```

Registering a `Domain` is worth more than it looks. It is what makes all of
these work with no further edits:

```bash
worldloom build -a <your_archetype> --seed 8128 --periods 6 -o ./corpus
worldloom pack template <your_domain>      # a starter pack for your engine
worldloom pack targets <your_domain>       # your consulted lore targets
worldloom pack texts <your_domain>         # your overridable surface text
worldloom build --pack yours.json          # a pack whose `base` is your domain
worldloom validate ./corpus                # your check group, on every world
worldloom render ./corpus -f xlsx -f docx  # your registered renderers
worldloom evaluate ./corpus                # your benchmark families
```

`--periods N` runs your episode N times, stepping by the `period_step_months`
you registered. Fill in `consulted_targets`, `system_slots`, `role_keys`,
`episode_text` and `evaluation_text` on the `Domain` — they are not decoration,
they are what a pack author sees and what `pack check` lints against.

## The seams that are not there

Four core tables have no registration seam. Each is a closed literal, so a
fourth vertical cannot add to it without editing core — which
`tests/test_thin_waist.py` forbids, correctly. Report the gap rather than
widening the table:

| table | consequence for you |
|---|---|
| `parameters.DEFAULTS` | your physics ranges are invisible to `worldloom pack params` and `Parameters.with_overrides` refuses them by name, so **a pack cannot tune your engine's physics**. Keep your spans in your own module and layer them under whatever a caller supplies. |
| `landscape.LANDSCAPES` | `--estate` cannot grow a landscape in your vocabulary. Refuse the flag with its reason rather than serving a retailer's `click-collect-api`. |
| `mosaic.ENGINES` | `worldloom mosaic -e <yours>` is refused; the per-engine variation axes are a literal map. |
| `locales.industry_suffixes` | your companies are named from the *retail* suffix pool in every shipped jurisdiction, silently — `suffixes_for` falls back rather than raising. |

And one seam that is not a registry at all: **a domain module registers by
being imported**, and the only thing that imports it unconditionally is
`src/worldloom/__init__.py`. That import is a hand edit and there is no way
around it. Lazy registration is not an option — a check group that runs only
in processes that happened to import the right module is a check that passes
on machines where it never ran.

---

## The order of work

1. **Decide what disagrees with what.** A vertical is worth building when two
   sources of truth can both be current and both be right about different
   questions. Retail's is a hypothesis versus a confirmed cause; banking's a
   filing versus its restatement; insurance's an actuarial estimate versus a
   booked reserve; procurement's an order versus a receipt versus an invoice.
   If nothing in your industry disagrees, you have a pack, not a vertical.

2. **Write the archetype.** Shape only — units, categories, sites, revenue,
   headcount. Keep revenue-per-head inside the envelope the registry already
   spans (`company.productivity_envelope`): an archetype outside it widens the
   envelope and quietly stops the scale check refusing what it was written to
   refuse.

3. **Write the org generator.** Copy `generators/insurance_org.py` and change
   the content, never the mechanism — `org_builder` is shared and its draw
   order is API. Forward `name_pools`, `headquarters`, `regions` and `locale`
   from the first commit; the insurance module shipped without them and was
   unconditionally Australian for its whole first life.
   **Make the reporting lines carry the disagreement.** If two documents are
   meant to be able to contradict each other forever, the people who write
   them should not report to the same person below the CEO — otherwise the
   corpus reads as one function contradicting itself.

4. **Write the figure generator, and size the trap by construction.** Draw in
   dependency order so the contest the vertical exists to pose *always* fires,
   and gate the multiple that guarantees it (`triangles._check_deficit_multiples`,
   `procurement_match._check_breach_multiple` are the two worked examples).
   Refuse physics that tunes the trap away rather than clamping it: a clamped
   range builds a valid corpus that no longer poses the question, and nothing
   tells the author.

5. **Write the episode generator.** Events and facts only; every number comes
   in from step 4, every timestamp is arithmetic on the period string, and the
   working calendar arrives as `locale_of(world.recipe)`. Decide each fact's
   authority deliberately — that field is what the benchmark is about.

6. **Write the documents.** Give the contested question **one document per
   answer** and make sure no single document holds two of them, or the
   authority family collapses into a lookup. Include a *clean* case in the same
   documents as the contested one, so the family cannot be passed by a rule
   about which document type to trust.

7. **Write the check group.** Every fact needs a check. Bucket by
   `(kind, period)` once and loop periods — the shape `validate.financial()`
   uses. Do **not** copy `banking._checks`, whose full-fact scans inside
   per-period loops make it 94% of validate's runtime at scale. Return
   `([], 0)` immediately on a world with none of your fact kinds.

8. **Write the benchmark.** End with the reachability gate
   (`cases.answerable`), and generate contrast cases beside inverted ones.

9. **Write the tests, and show every check firing.** A check that has never
   failed proves only that it compiles. `tests/test_procurement.py` is the
   current model: one tamper test per check, plus determinism, replay, and its
   own thin-waist scan over core for its own vocabulary.

---

## Traps, each of which cost somebody a debugging session

- **Multi-period is not free, and it is the difference between a corpus and a
  demonstration.** Insurance refuses a second run and therefore cannot reach
  any scale. Everything a later period inherits — a rate card, a policy, a
  counterparty, a balance carried forward — must be resolved from the *world's
  own record* (`world.authoritative`), never from a counter threaded through
  the recipe. Then filter the reused facts back out before `world.extend`,
  which is append-only.
- **A reused standing fact must be re-appended and re-filtered.** Your episode
  generator needs it in `episode.facts` so its own handle lookups resolve
  identically whichever period it is; `world.extend` must not see it twice.
  `known_fact_ids = set(world.facts.ids())` is the idiom.
- **Draw unconditionally, then override.** Skipping a draw because a value
  arrived from outside reshuffles every stream after it, and the second period
  comes out a different period.
- **A per-period snapshot is not a supersession chain.** You cannot set
  `valid_to` on a fact an earlier run already minted. Either key the fact by
  period and never close it (`reserves.booked_total`'s discipline), or keep the
  whole chain inside one run.
- **Order your artifact intents so a conditional document is last.** Intents
  mint `ART` ids in sequence; a document that exists in some periods and not
  others must not renumber the ones that exist in all of them.
- **An intent's `audience` names an access class**, matched against a policy
  label with underscores turned into spaces (`world._policy_for`). Name your
  policies after your audiences and the mapping needs no table.
- **A labelled imperfection's `canonical_value` must be the fact's own number**
  in a form `validate._quantity_matches` recognises. A descriptive string trips
  `canonical_mismatch`.

---

## Before you call it done

```bash
pytest -q
worldloom validate retail-close
```

Then prove you moved nothing. A new vertical must not shift an existing corpus
by one byte: `git archive HEAD` into a clean tree, build these four in both
trees, and `diff -r`.

```bash
worldloom build -a omnichannel_retailer     --seed 8128 --incident -o OUT
worldloom build -a australian_grocery       --seed 8128 --incident -o OUT
worldloom build -a midsize_adi              --seed 8128 -o OUT
worldloom build -a midsize_general_insurer  --seed 8128 -o OUT
```

And prove yours replays: build it, rebuild it from its own recipe, export both,
`diff -r`. Then read it four ways — `validate`, `evaluate`, `topology`,
`series`, `diversity` — because a corpus that validates is coherent and not yet
known to be hard.
