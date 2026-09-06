---
title: Finance LOB Cascade
description: Walk the LOB cascade end to end on a finance LOB, seed, roles, responsibilities, resolve, build.
read-when: Answering your first LOB brief, or when an accept is refused and you want the shape of a passing answer.
tags: [worldloom, lob, cascade, worked-example, refusal-loop]
---

# A finance LOB, seed to built world

The complete exchange behind the loop in the skill entry point. Every `accept`
below passes; the two refusals a first attempt usually hits are called out
after the code, at the answers where they bite.

```python
from worldloom import lob

seed = lob.LobSeed(name="finance", title="Finance",
                   purpose="Financial management, reporting, and close-out.",
                   engine="retail")
lob.lint_seed(seed)               # [] or findings, e.g. an unregistered engine
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

The two refusals to expect first: the role tree needs exactly one root and by
convention it must be `ceo` (a cfo-rooted proposal is refused), and a fact
kind the registry cannot resolve (`worldloom.factkinds.names()`) is an
accountability edge that never fires.

Build with the result:

```python
from worldloom import sdk
world = sdk.retail().org(headcount=50, span=6, levels=3).lob(lob_spec).build()
```
