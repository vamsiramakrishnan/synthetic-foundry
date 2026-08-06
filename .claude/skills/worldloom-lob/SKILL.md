# Authoring Lines of Business

Author a Line of Business (LOB) for a Worldloom vertical. A LOB declares the
roles, responsibilities, and lore of an organizational unit — finance, procurement,
HR, underwriting — and from those declarations, the engine derives authorship
hints, access policies, and accountability facts.

## The cascade

A LOB is built in stages. Each stage is a handshake: the engine proposes a brief,
you answer, and the engine refuses incoherence rather than silently building a
broken world.

### Stage 1: Seed

Start with a minimal premise: the LOB's name, a short title, and its purpose in one sentence.

```python
from worldloom import lob

seed = lob.LobSeed(
    name="finance",
    title="Finance",
    purpose="Financial management, reporting, and close-out.",
    engine="retail",
)
session = lob.open(seed)
```

Check the seed with `lob.lint_seed(seed)` — it should refuse name/engine mismatches.

### Stage 2: Propose roles

Ask the engine what the next stage is:

```python
brief = lob.next_stage(session)
print(f"Stage: {brief.stage}")
print(f"Question: {brief.asks}")
```

The engine asks for roles. Each role has:
- **key**: a lowercase snake_case identifier (used in lookups and ids)
- **title**: what documents print
- **function**: the organisational function (Finance, Technology, etc.)
- **reports_to**: the key this role reports to, or None for the root

Propose roles as a list:

```python
answer = lob.Answer(
    stage="roles",
    roles=[
        lob.RoleSpec(key="cfo", title="Chief Financial Officer", function="Finance"),
        lob.RoleSpec(
            key="controller",
            title="Financial Controller",
            function="Finance",
            reports_to="cfo",
        ),
    ],
)
session = lob.accept(session, answer)
```

The engine refuses duplicate keys, missing roots, reporting cycles, and other
tree inconsistencies — see the findings and fix them before calling `accept()`
again.

### Stage 3: Propose responsibility edges

Ask for the next stage again:

```python
brief = lob.next_stage(session)
```

The engine now asks for responsibilities. Each responsibility ties a role to
the facts it answers for and the documents it authors:

```python
answer = lob.Answer(
    stage="responsibilities",
    responsibilities=[
        lob.Responsibility(
            role_key="cfo",
            fact_kinds=["financial.revenue", "financial.gross_profit"],
            artifact_types=["executive_summary"],
        ),
        lob.Responsibility(
            role_key="controller",
            fact_kinds=["financial.revenue", "financial.gross_profit"],
            artifact_types=["cfo_variance_memo"],
        ),
    ],
)
session = lob.accept(session, answer)
```

The engine refuses responsibilities whose role_key does not exist, and fact
kinds the fact-kind registry (`worldloom.factkinds`) does not hold — a kind
nothing generates is an accountability edge that never fires. A named kind may
be a dot-prefix of a registered family (`financial.revenue` covers
`financial.revenue.actual`); `factkinds.names()` lists what is real.

### Stage 4: Resolve

When all stages are complete:

```python
lob_spec = lob.resolve(
    session,
    artifact_filings=["cfo_variance_memo"],
    episode_contributions=["MonthEndClose"],
)
```

This produces a final `Lob` spec ready to ride the pack/recipe and replay.

## Building with a LOB

Once you have a final `Lob` spec, add it to a blueprint:

```python
from worldloom import sdk

world = (sdk.retail()
         .org(headcount=50, span=6, levels=3)
         .lob(lob_spec)
         .build())
```

The LOB's roles are appended to the organisation. Explicit roles win over LOB
roles with the same key.

## Standard library

The engine ships three LOBs: finance, procurement, and HR. Inspect them with:

```python
library = lob.publish()
for name, spec in library.items():
    print(f"{name}: {spec.title}")
```

Use them as templates for your own, or build worlds with them directly:

```python
world = (sdk.retail()
         .lob(library["finance"])
         .build())
```

## Determinism

The final accepted LOB spec is deterministic and replays from the ledger.
Entries are ordered by key; no draw, no clock, no set iteration. The cascade
conversation is not replayed — only its result, the final spec, rides the recipe.
