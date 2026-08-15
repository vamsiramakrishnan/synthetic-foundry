---
name: worldloom-lob
description: Author a Worldloom line of business through a refusable cascade — declare its roles, responsibilities, lore, and process-slot bindings so participation, access, and accountability can be derived rather than maintained separately. Use when a company needs an organizational capability such as finance, procurement, HR, or underwriting that must participate in authored processes.
---

# Authoring Lines of Business

A Line of Business (LOB) declares the roles, responsibilities, and lore of an
organizational unit — finance, procurement, HR, underwriting. From those
declarations the engine derives authorship hints, access policies, and
accountability facts. It is authored through a refusable cascade: the engine
briefs you, you answer, and an incoherent answer is refused with findings
rather than silently building a broken world.

## The loop

```python
from worldloom import lob

seed = lob.LobSeed(name="finance", title="Finance",
                   purpose="Financial management, reporting, and close-out.",
                   engine="retail")
lob.lint_seed(seed)               # [] or findings — e.g. an unregistered engine
session = lob.open(seed)

brief = lob.next_stage(session)   # brief.stage, brief.asks, brief.context
session = lob.accept(session, lob.Answer(stage="roles", roles=[
    lob.RoleSpec(key="ceo", title="Chief Executive Officer", function="Executive"),
    lob.RoleSpec(key="cfo", title="Chief Financial Officer",
                 function="Finance", reports_to="ceo"),
]))
session = lob.accept(session, lob.Answer(stage="responsibilities", responsibilities=[
    lob.Responsibility(role_key="cfo",
                       fact_kinds=["financial.revenue"],
                       artifact_types=["cfo_variance_memo"]),
]))
lob_spec = lob.resolve(session,
                       artifact_filings=["cfo_variance_memo"],
                       episode_contributions=["MonthEndClose"])
```

A refused `accept` raises `ValueError` carrying the findings. Fix the specific
finding and answer again; do not loosen the answer around it. The two refusals
to expect first: the role tree needs exactly one root and by convention it must
be `ceo` — a cfo-rooted proposal is refused — and a fact kind the registry
cannot resolve (`worldloom.factkinds.names()`) is an accountability edge that
never fires.

Build with the result:

```python
from worldloom import sdk
world = sdk.retail().org(headcount=50, span=6, levels=3).lob(lob_spec).build()
```

`assets/lob-seed.json` is a seed to copy; `lob.load_seed` reads a path, JSON
text, or dict.

## Read next

- `references/cascade.md` — every stage's fields and the refusal taxonomy.
  Load before answering a brief.
- `references/integration.md` — the shipped finance/procurement/HR library,
  blueprints and slot bindings, install/describe, determinism. Load when
  building with a finished LOB.
