---
title: Agent Packs
description: What an agent policy holds, which rules are locked, the skills tree, and how a proposal revises it.
read-when: Writing or reviewing a proposal, or deciding what a revision is allowed to change.
tags: [worldloom, packs, agent, policy, skills, proposals]
---

# Agent packs: what the loop is allowed to change

Read this before writing or reviewing a proposal, or when a proposal is
refused with findings.

## What a policy holds

An `agent` pack is content-addressed JSON: every variant has its own digest,
and every run records the pack's `ref`, `digest` and `chain` in `run.json`.

| Field | Meaning |
| --- | --- |
| `system` | The standing instruction, sent ahead of everything else |
| `turn_rules`, `plan_rules` | Overlays on the shipped `evalrun.turn.rule.*` and `evalrun.plan.rule.*`, keyed by suffix: `01` replaces rule 01, a new key adds a rule, `""` removes a shipped one |
| `tools` | Advice per catalog tool (`servicenow.get_record`): a `description` and `hints` |
| `planning` | How to form a plan before acting |
| `skills` | Named procedures as plain text (kept for compatibility) |
| `files` | The skills tree: `skills/<name>/SKILL.md` (frontmatter `name`, `description`), `references/*.md`, `scripts/*.py` or `*.sh`, in the harness's native layout |
| `max_turns` | The turn budget, when it differs from `evalrun.max_turns` |

`agent:baseline` ships as the starting champion: the shipped rules, no advice,
no skills, a neutral instruction.

## Locked rules

Rule `02` of each list states the reply grammar (`call`, `ask`, `answer` for a
turn; `plan` for a planner) that the harness parses. A policy that restated it
would be a protocol variant whose failures read as the agent's, so the lint
refuses any override or removal of a locked rule, any text that writes a reply
shape out as JSON, any `{placeholder}` or `{{term:...}}` token (policy text is
sent verbatim), and text past `evalrun.agent_pack.max_chars`. The overlay
enforces the lock again at run time.

## The skills tree and proposals as diffs

The skills tree is the one place generated procedure text or code may live.
A revision may add, change or remove skills, tool advice, rules outside the
locked ones, the planning note and the standing instruction; it may not touch
anything outside the pack.

The proposer receives the interview request: the brief, the champion as the
draft, and the response schema. The proposer replies with a unified diff
against the champion's tree, or with the whole revised body, and the host
applies it, lints the result and returns findings until it is clean. Each
accepted proposal is installed under `packs/agent/<stem>-rN.json` in the loop's
output directory and can be named later:

```bash
worldloom evalrun run ./cases -o ./runs/r1 --harness codex --agent-pack ./improve/packs/agent/baseline-r1.json
worldloom pack author agent --name careful --message "Read before every write" --harness-command 'python adapter.py'
```

## Writing a good proposal

- Address the brief's largest clusters by their meaning (a missing verify
  step, a write past a designed failure), not the example case ids. The brief
  ends by saying so, and the held-out gate punishes it anyway.
- Keep what already works. A regression on any axis beyond the band fails the
  training gate even when the mean improves.
- One idea per round is easier to judge than five; a round is cheap to rerun
  because paid-for runs are reused.
