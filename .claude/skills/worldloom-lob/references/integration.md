---
title: Finished LOB Integration
description: Build with a resolved Lob: blueprints, slot bindings, the standard library, install and describe.
read-when: Building with a finished LOB, or seating its roles into a process.
tags: [worldloom, lob, blueprints, slot-bindings, determinism]
---

# Using a finished LOB

## Building with a LOB

```python
from worldloom import sdk

world = (sdk.retail()
         .org(headcount=50, span=6, levels=3)
         .lob(lob_spec)
         .build())
```

The LOB's roles are appended to the organisation. Explicit roles win over LOB
roles with the same key.

## Seating roles into a process

A process declares *slots* (`preparer`, `approver`, …) in its own vocabulary;
the company's half of the handshake is `lob.SlotBinding(process=..., slot=...,
role_key=...)` rows on `Lob.slot_bindings`. The blueprint adds them without
editing the LOB:

```python
blueprint = sdk.retail().lob(lob_spec, bind={"MonthEndClose": {"preparer": "cfo"}})
```

A binding naming a role the LOB lacks is refused at that call: at the claim,
not later as a seat filled by nobody. The other half of the lint needs the
process spec: `lob.lint_bindings(my_lob, spec)` refuses an unbound **required**
slot. Participation (who is in a process) is derived, never stored:
`lob.participation(my_lob, spec)` joins the responsibility edges against the
kinds the process mints, plus the bindings. `/worldloom-process` owns the other
side of this seam.

## Standard library

The engine ships three LOBs: finance, procurement, and HR.

```python
library = lob.publish()
for name, spec in library.items():
    print(f"{name}: {spec.title}")

world = sdk.retail().lob(library["finance"]).build()
```

Use them as templates for your own, or build with them directly.

## Registry

`lob.install([spec])` registers into the process registry (refusing a same-name
LOB with a different spec); `lob.installed()` returns a copy.
`lob.describe(name)` returns an installed LOB as a document, including
`participation` per installed process, computed at call time, or `None` for a
name never installed.

## Determinism

The final accepted LOB spec is deterministic and replays from the ledger.
Entries are ordered by key; no draw, no clock, no set iteration. The cascade
conversation is not replayed: only its result, the final spec, rides the
recipe.
