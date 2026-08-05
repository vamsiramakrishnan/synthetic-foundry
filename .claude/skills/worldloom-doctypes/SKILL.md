---
name: worldloom-doctypes
description: Give a company a document type the engine does not have — authored as JSON in its pack, planned by its own lore, rendered to Word, and linted against what the compiler actually assumes. Use when a corpus needs paperwork no archetype ships (a franchisee statement, a levy return, a covenant certificate), when asked whether Worldloom can produce some particular document, or when a pack's lore asks for a filing nothing plans.
---

# A document type, authored rather than written in Python

Thirty artifact types are declared in this repository, and nearly all of what
defines each one is **data**:

| Table | Shape | Authorable |
| --- | --- | --- |
| `_STANDING` | `(Authority, Lifecycle)` | yes |
| `_LAG` | a `timedelta`, always whole minutes | yes |
| `_OUTLINES` | a tuple of `SectionPlan` — four strings each | yes |
| `_COMPILERS` | a function | **no** |

So a pack could give a company a name, divisions, books, voices, a trading year
and a backstory, and could not give it a single document of its own. It can now.

```bash
worldloom pack check ./pack.json                      # lint it before you build it
worldloom build --pack ./pack.json --seed 8128 -f docx -o ./corpus
```

Reference: `examples/artifact-types/` — the thirty shipped types ported to the
schema (`core.json`), a pack that authors one and builds
(`franchise-network.json`), and one that fires every lint rule
(`franchise-network-broken.json`).

## Write the type

It goes in the pack, under `artifact_types`:

```json
{
  "key": "franchisee_trading_statement",
  "authority": "approved_report",
  "lifecycle": "published",
  "lag": {"days": 0, "hours": 20, "minutes": 0},
  "word": true,
  "sections": [
    {"heading": "Network position",
     "kinds": ["financial.revenue.", "financial.gross_profit."],
     "scope": "group",
     "purpose": "State the network's month against plan, for a reader who is a
                 small-business owner rather than a manager…"}
  ],
  "filing": {
    "author_role": "controller", "fallback_role": "cfo",
    "domain": "finance", "audience": "all_staff", "size": "medium",
    "facts": ["headline", "close_status"],
    "rationale": "A franchisor computes every franchisee's fee off the group's
                  own reported month…"
  }
}
```

Five fields decide whether the document is any good.

* **`sections[].kinds`** are fact-kind *prefixes*, and they are what the section
  is handed. A prefix nothing produces resolves to no facts, the section is
  dropped, and the document compiles into a hidden appendix and nothing else —
  it does not fail. Start from `doctypes.describe("cfo_variance_memo")` rather
  than guessing.
* **`sections[].scope`** filters on a fact's *subject*: `group` for company
  subjects, `unit` for business units, `any` otherwise. Only the financial
  generators state one figure per company and another per unit, so `close.` or
  `ops.` facts scoped to `unit` resolve to nothing.
* **`sections[].purpose`** is the field that decides whether the prose argues or
  lists. "Write the drivers section, here are four metrics" gets four correct
  sentences. Say what the section has to *establish*, and for whom.
* **`filing.audience`** decides who may **open** the document, not who receives
  it. It resolves through `world._policy_for`, and an audience nothing maps
  falls to the world's narrowest policy — if that excludes the author, the
  corpus fails `author_cannot_see_own_artifact`. Name the receiver in the
  purposes.
* **`lag`** is how long after its newest cited fact the document is written. Keep
  it at or under a day and fifteen hours: `scenarios._period_boundary` places a
  departure eight business days after period end and chose eight against the
  slowest artifact any episode plans.

## Then make the company file it

Declaring a type does not produce one. What produces one is lore, in the same
`artifact_density` vocabulary a facet uses:

```json
{"kind": "norm",
 "assertion": "Every franchisee receives a monthly trading statement, because the
               franchise agreement computes their fee off the group's figures.",
 "effective_from": "2019-04",
 "constrains": [
   {"kind": "artifact_density", "target": "filing/franchisee_trading_statement",
    "effect": "The network is sent a statement of the month every period",
    "magnitude": 1.0}]}
```

The type is the company's *vocabulary*; the lore is its *claim about who it
answers to*. Magnitudes sum across commitments, so a negative one suppresses —
which is how a founder-led company loses its minutes.

## Read the lint

`worldloom pack check` runs it. Two findings are refused at build time
(`is reserved`, `already declared by a module`); the other fifteen **compile**,
which is why they are worth reading:

```
artifact_types[3].sections[0] ('Outlook'): fact kind(s) 'esg.scope_three.' — no
document this engine declares is written about anything with that prefix. A
section whose prefixes match no fact is dropped rather than left empty, so this
does not fail: it compiles into a document that is carried, cited, and says
nothing.

artifact_types[3].sections[1] ('Outlook'): repeats the heading of section 0 — a
narrative request is keyed "<artifact id>/<heading>", so the two sections share
one request id and the second response overwrites the first.

artifact_types[2]: declares no `filing`, so nothing will ever plan one … the
type is declared, renderable, and inert.
```

`lore[N]: filing target 'X' names no artifact type` is the one to expect first:
lore asking for a document nobody declared resolves, plans nothing, and reports
success.

## What still needs Python

A **compiler**. Five types have one — `finance_workbook`, `capital_return` and
`reserve_triangle_workbook` declare formulas over a resolved table;
`meeting_minutes` and `email_thread` build one message per moment — and no
outline stands in for that. If the document you want is a workbook whose totals
have to recompute, it is a domain module, not a pack.

Also Python-side, and worth knowing before you promise any of it: a new **fact
kind** (a section can only cite what a generator produced), a new **role**
(`filing.author_role` is looked up in the engine's role table), and a new
**access policy** (an audience nothing maps falls to the narrowest one).

## Determinism

Authored types travel **in the pack**, and the pack is embedded verbatim in the
corpus recipe — so a corpus carrying an authored type rebuilds with the type, in
any process, with no file on hand. There is no search path and no plugin
directory, deliberately: `register_artifact_types` calls that "a determinism bug
wearing a plugin's clothes".

Two names are refused rather than merely linted, because their consequence lands
on *somebody else's* corpus: a key some module already declares, and a key
`documents.reserved_types()` holds — a name a scenario mints without declaring,
where there is no registered value for the seam to disagree with.
