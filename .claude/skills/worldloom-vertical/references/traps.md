# Traps, and the done protocol

Each trap below cost somebody a debugging session. Load this before the first
multi-period run, and the protocol at the bottom before calling the vertical
done.

## Traps

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
