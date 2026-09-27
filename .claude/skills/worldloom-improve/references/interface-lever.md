---
title: The Interface Lever
description: Who owns a failure (agent, interface, world, grader), and how a round reshapes a served connector through an Anvil manifest overlay that is linted, gated, transfer-checked and written out for human approval.
read-when: An autopsy shows validation errors, refused calls or unexposed operations; before running --levers interface; reading a receipt with lever interface.
tags: [worldloom, evalrun, improve, anvil, interface, ownership]
---

# The interface lever

Read this when the autopsy's owner line gives the interface a large share,
before running `--levers interface`, or when a receipt says `lever:
interface`. `docs/self-improvement.md` ("Two levers") is the design.

## 1. Read the owners first

```bash
worldloom evalrun autopsy ./improve/runs/baseline@<digest>/train --reference-run ./runs/reference
```

The brief opens with `owners: agent N%, interface N%, ...` and every cluster
names its owners. An interface share means the served tools misled the agent
or could not express its need; changing the agent's policy there teaches it
to work around a surface that should be fixed. A world share means the cases
or the corpus are at fault (fix those, not the agent); a grader share means
the measurement is (report it).

## 2. Run with the interface lever

The bundles must be compiled with a manifest (`anvil compile ... --manifest
m.yaml`), so `.anvil/manifest.yaml` and the locked source snapshot exist.

```bash
worldloom evalrun improve ./cases --agent-pack agent:baseline --exec ./agent \
  --proposer-exec ./proposer --holdout-corpus ./fresh-cases \
  --levers agent,interface --contract jira=./generated/jira \
  --anvil-cmd "node /path/to/anvil/packages/cli/dist/bin-anvil.js" \
  --transfer-agent ./second-agent -o ./improve
```

`--source-root jira=<workspace>` names the workspace holding
`.anvil/sources/<snapshot>` when `anvil status` cannot find it.

## 3. What the proposer sees and may change

The request (kind `anvil-overlay`) carries the interface-owned findings, the
failing calls with the vendor's own errors and the arguments sent, the
tools as the agent saw them (`surface`) and the manifests (`draft_tree`). A
reply is a unified diff over `<connector>/manifest.yaml`, refused with
findings until:

- it applies, and touches only the served manifests;
- it changes only agent-facing keys: under an operation `description`,
  `display_name`, `intent_examples`, `name`, `pagination`, `retries`; the
  `workflows` and `query_templates` sections;
- `anvil compile` accepts it, every approval the base had is kept, and every
  workflow it adds compiles approved;
- the compiled AIR leaves every operation's behaviour (effect, inputs,
  outputs, errors, idempotency, confirmation, auth, state) unchanged.

## 4. Reading the receipt

- `lever`: `interface`; `candidate.ref`: `interface:<connectors>`.
- `interface.overlays`: overlay digest per connector; `interface.contracts`
  and `interface.base_contracts`: the recompiled and the served contract
  digests; `interface.transfer`: `{"passed": ...}` or `{"skipped": reason}`.
- `train`, `ablation` (hunks of the manifest diff), `holdout`: exactly as for
  an agent candidate; `transfer`: the second agent's gate on the held-out
  cases.
- `interface.promotion`: where the reviewable diff, the patched manifest and
  the approvals record were written.

## 5. After a promotion

`improve/interface/promoted/NNN/` holds `<connector>.manifest.diff`,
`<connector>.manifest.yaml` and `<connector>.approvals.jsonl` (Anvil's
record, reviewer `unrecorded`, note `simulation-only`). The loop never
touches the served bundle. A person reviews the diff, recompiles the
production bundle with the patched manifest, and approves it with `anvil
approve --reviewer <id>`; that approval is the only one that counts.

## Rules

- Never hand-edit the served bundle or its manifest to make a candidate pass.
- Never widen the allowed keys, or treat a simulation approval as a production one.
- A transfer failure is the gate working: the change helped one agent and hurt another.
