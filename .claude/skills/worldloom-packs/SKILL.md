---
name: worldloom-packs
description: Supply any layer of Worldloom as data rather than code, including an industry's colloquial language, prompts, numeric policy, a company, a connector, a line of business, a document type or a presentation profile, and upload one or author one through a harness interview that is refused with findings until it lints clean. Use when a corpus or console should speak an industry's words ("branches", "patients", "policyholders"), when asked to add or change an industry, prompt, default or connector without editing code, when a user uploads a pack, or when a coding harness should generate one.
metadata: {tags: [worldloom, packs, industry, colloquial, prompts, policy, refusal-loop, upload]}
---

# Every layer is a pack

A pack is one JSON envelope of a registered kind. `worldloom pack kinds` lists
the kinds and what each one controls. Code never holds an industry's words, a
prompt or a default: it asks `packkit.text`, `packkit.policy` and
`packkit.term`, which read whatever packs are in force. When no pack is in
force, the shipped defaults apply, and they hold the literals the code used to
hold.

## Find and read

```bash
worldloom pack kinds
worldloom pack list industry
worldloom pack show industry:banking   # merged body, digest, the chain it layers on, findings
```

A pack lives in `<root>/<kind>/<name>.json`. The roots are searched in this
order: `--pack-root`, then `WORLDLOOM_PACK_PATH`, then `~/.worldloom/packs`
(or `$WORLDLOOM_HOME/packs`), then the shipped packs. A pack in a higher root
shadows the same name lower down. If it `extends` its own name, it extends the
pack it shadows.

## Write one: state only what differs

```json
{"schema": "worldloom.pack/v1", "kind": "industry", "name": "hospital",
 "extends": ["industry:healthcare"],
 "body": {"terms": {"site": "hospital", "customer": "patient"}}}
```

- **Terms** are lower-case and singular. Templates reach them with
  `{{term:site}}`, `{{term:Site}}`, `{{term:sites}}` and `{{term:SITES}}`: the
  case and plural are derived from the one term.
- **Prompt overrides** (`body.prompts`) must use keys that
  `prompts:default` has. They keep the `{placeholders}` the caller fills, and
  may add `{{term:x}}`.
- **Policy overrides** (`body.policy`) keep the type of the value they
  override.

```bash
worldloom pack lint hospital.json            # every finding; exit 2 when there are any
worldloom pack install hospital.json         # refused with findings, or stored by name
worldloom --pack industry:hospital build --seed 8128 --out ./corpus
```

## Have a harness author one

```bash
worldloom pack author industry --name hospital \
  --message "An acute hospital network in the UK" --harness-command 'python adapter.py'
```

The loop:

1. Each round, the adapter receives a request on stdin. The request carries
   the kind's JSON Schema, the shipped default as an example, the visible
   packs, the draft so far and the last round's findings.
2. The adapter replies on stdout with either `questions` or a `proposal`.
3. A proposal that fails the lint comes back with every finding, and the loop
   repeats.
4. Questions end the loop and go to the operator.

To run the same exchange through files, with you as the harness:

```bash
worldloom pack interview request industry --name hospital --message "..." -o request.json
# write reply.json: {"request_id": ..., "proposal": {"name": "hospital", "body": {...}}}
worldloom pack interview accept --request request.json --reply reply.json --install
```

A refusal is normal. Read the findings, fix every one of them (not only the
first), and resubmit. Never work around a refusal by editing a shipped
default.

## Replay

When a non-default pack is in force, its merged body and digest are recorded
in the recipe. `build --replay` then rebuilds without the pack file, and
refuses if the stored body no longer matches its digest.

Guide: `docs/packs.md`.
