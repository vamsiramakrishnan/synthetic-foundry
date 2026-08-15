# The LOB cascade, stage by stage

Purpose: field-level reference for each stage of `worldloom.lob`, and what each
refusal means.

## Seed

`LobSeed` — four fields, nothing structural. Everything structural is proposed
in stages where the lint can refuse it, not asserted in the seed where nothing
checks it.

- `name`: the LOB's key, `^[a-z][a-z0-9_]*$`.
- `title`: a short title (`Finance`).
- `purpose`: one sentence — why this LOB exists.
- `engine`: a registered domain — `banking`, `insurance`, `procurement`, `retail`.

`lob.lint_seed(seed)` is advisory: it returns findings (an unregistered engine
names the known ones) rather than raising. `lob.open(seed)` takes the seed or a
dict of its shape and returns a `Session`; `lob.load_seed` reads a path, JSON
text, or dict — `assets/lob-seed.json` is a starting point.

## Stage: roles

`next_stage` asks for the roles, each a `RoleSpec`:

- `key`: lowercase snake_case; appears in ids and lookups.
- `title`: what documents print.
- `function`: the organisational function (Finance, Technology, …).
- `reports_to`: the key this role reports to, or `None` for the root.

`accept` runs `lint_roles` and refuses (a `ValueError` listing every finding)
on any of:

- no roles at all, a duplicated key, an empty title or function;
- not exactly one root (one role, and only one, reports to nobody);
- a root that is not `ceo` — the convention `lint_roles` enforces, so a
  finance LOB proposes `ceo` at the root with `cfo` reporting to it;
- `reports_to` naming a key not in the proposal;
- a reporting cycle.

## Stage: responsibilities

Each `Responsibility` ties a role to what it answers for:

- `role_key`: must be one of the accepted roles.
- `fact_kinds`: the facts this role answers for.
- `artifact_types`: the documents it authors or approves.

At least one of `fact_kinds`/`artifact_types` per edge. Two lookups back the
refusals, and both exist because an edge to nothing reports as if it were
load-bearing:

- A fact kind must resolve in the process-global registry
  (`worldloom.factkinds`) — a kind nothing generates makes someone answerable
  for facts that never exist. Prefix semantics are the registry's:
  `financial.revenue` covers `financial.revenue.actual` at a dot boundary.
  `factkinds.names()` lists what is real.
- An artifact type must be declared by some engine
  (`documents.declared_types()`) or passed as pack-authored via
  `known_artifact_types` — the shipped `hr` LOB once named two types nothing
  planned, and nothing said so until this half of the lint existed.

Duplicate edges (same role, same kind set) are refused too.

## Resolve

```python
lob_spec = lob.resolve(session,
                       artifact_filings=["cfo_variance_memo"],
                       episode_contributions=["MonthEndClose"])
```

Refuses if any stage is unaccepted. The result is a final `Lob` — the only
thing that rides the pack/recipe and replays; the session, its briefs, and
every refused answer are working state.
