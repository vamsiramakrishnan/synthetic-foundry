# Artifact types, authored

An artifact type is `(Authority, Lifecycle)`, a `timedelta`, and a tuple of
`SectionPlan`. Three of those four tables are pure data, and until this
directory existed none of it was authorable: a pack could give a company a name,
divisions, books, voices, a trading year and a backstory, and could not give it
a single document of its own.

Three files, each answering a different question.

| File | What it is for |
| --- | --- |
| `core.json` | The thirty types this repository declares, ported to the schema. The specification's own proof. |
| `franchise-network.json` | A pack that authors a document type, and a company whose lore files it. Builds. |
| `franchise-network-broken.json` | Every lint rule firing at once. Does not build, and is not meant to. |

## Author one

```bash
worldloom pack check examples/artifact-types/franchise-network.json
worldloom build --pack examples/artifact-types/franchise-network.json \
    --seed 8128 --incident -f markdown -f docx -o ./corpus
```

```
✓ franchise-network validates against the retail engine
no lint findings — every commitment is load-bearing
…
✓ coherent — 9672 checks passed
./corpus/artifacts/art-0015-franchisee-trading-statement.docx
./corpus/artifacts/art-0015-franchisee-trading-statement.md
```

The type itself is one object in the pack's `artifact_types`:

```json
{
  "key": "franchisee_trading_statement",
  "authority": "approved_report",
  "lifecycle": "published",
  "lag": {"days": 0, "hours": 20, "minutes": 0},
  "word": true,
  "sections": [
    {"heading": "Network position",
     "kinds": ["financial.revenue.", "financial.gross_profit.",
               "financial.gross_margin_pct."],
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

**Declaring a type does not file it.** What files it is a lore commitment, in
the same `artifact_density` vocabulary a facet uses:

```json
{"kind": "artifact_density", "target": "filing/franchisee_trading_statement",
 "effect": "The network is sent a statement of the month every period",
 "magnitude": 1.0}
```

That split is the whole design. The type is the company's *vocabulary*; the lore
is the company's *claim about who it answers to*. A pack that declares a type
and claims nothing files nothing — and `worldloom pack check` says so, because a
type nothing plans is the carried-and-inert failure this repository keeps
finding.

## Why it rides the pack

A pack embeds in the corpus recipe verbatim, so a corpus carrying an authored
type rebuilds *with* the type, in any process, with no file on hand. A
`--doctypes` flag would be a second thing to remember and a corpus that replays
into a different document set when you forget it — which is
`register_artifact_types`' own stated hazard, "a determinism bug wearing a
plugin's clothes".

## What still needs Python

The schema carries standing, lag, outline, renderer and filing. It does not
carry a **compiler**, and five types have one: `finance_workbook`,
`capital_return` and `reserve_triangle_workbook` declare formulas over a
resolved table, and `meeting_minutes` and `email_thread` build one message per
moment. Those build their IR in code, and an outline beside them would be dead
data — `worldloom.doctypes.describe` returns them with no sections for exactly
that reason.

Everything else is data. Measured, not asserted:
`tests/test_doctypes.py::test_the_data_code_line_falls_at_the_compilers_and_nowhere_else`
re-takes the measurement on every run.

## Regenerating `core.json`

It is `doctypes.describe` over the registry, dumped:

```python
import json, worldloom
from worldloom import documents, doctypes

types = [doctypes.describe(key) for key in sorted(documents.declared_types())]
print(json.dumps(doctypes.to_document(types), indent=2, ensure_ascii=False))
```

The checked-in file covers the thirty types that existed when it was written;
`tests/test_doctypes.py` holds every type the *live* registry declares to the
same round-trip, so a vertical landing afterwards is covered whether or not the
file is regenerated.

## The lint, on the broken example

```bash
worldloom pack check examples/artifact-types/franchise-network-broken.json
```

Nineteen findings covering seventeen rules — the unknown-role rule and the
filing-target rule each fire twice. Read them before authoring anything: each is
a place where what you wrote and what the engine does diverge, and only two
(`is reserved`, `already declared by a module`) are refused at build time. The
rest compile.
