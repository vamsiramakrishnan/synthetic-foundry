---
title: Interview Layers
description: What each world-interview question asks, the shape of its answer, and the lint that refuses it.
read-when: Before answering the first request of a world interview, or when a refusal names a rule you do not recognise.
tags: [worldloom, interview, layers, refusal-loop]
---

# The questions, in order

Each answer is the JSON under `answer` in your reply. Keys you name (a role, a
process, an event kind, a document type, a system) must be ones `context`
lists or ones this answer declares.

## `company`

`{"spec": <company specification>}`: the `worldloom pack spec` document
(`/worldloom-company`). `identity.company_name` is required, so the pack is
composed and the world is one particular company. Refused on any
`company.resolve` conflict, a missing name, a `pack` field (the interview
composes the pack), or an engine that cannot build from a pack. `unmet`
consequences are carried into `context`, not refused.

## `lobs`

`{"lobs": [{"name", "title", "purpose", "roles": [{"key", "title", "function", "reports_to"}]}]}`.
At least two. Each runs the LOB cascade's seed lint and roles stage: one root,
`ceo` by convention, no dangling or cyclic reporting. A post two LOBs share
must report to the same manager in both. Prefer keys the company's
`role_table` already holds; a new key joins the organisation.

## `employees`

`{"levels": {"<role>": "ic" | "manager" | "director" | "executive"}}` for every
role the LOBs declared. Nobody sits above the person they report to, the root
is an executive, and every level holds at least one role (each level asks the
evals one question).

## `processes:<lob>`

`{"episodes": [EpisodeSpec], "systems": {"Process.event_kind": ["jira", ...]}, "responsibilities": [...], "slot_bindings": [...]}`.
Episodes are the pack's episode specs (`/worldloom-process`, `episodes.lint`).
Every event names the systems it leaves a record in: `confluence`, `email`,
`jira`, `outlook`, `salesforce`, `servicenow`, `sharepoint`, `slack`; at least
two across the answer. Event kinds must be unique across the whole company.
Each document an episode plans is authored by a role this LOB declares, whose
function may own the document's `domain` (the compiler's contract: an
`engineering` document is owned by Technology). Responsibilities and seats use
this LOB's roles; every required slot is bound (`lob.lint_lob`).

## `documents`

`{"doctypes": [DocumentType], "chains": [{"artifact_type", "reviewer", "approver", "published_on": ["sharepoint", ...]}]}`.
Declare every planned type no engine ships (`/worldloom-doctypes`). Every
planned type has a chain: reviewer at or above the author's level, approver
above it (an executive's paper may be approved by a peer executive), never the
author. `published_on` is `sharepoint`, `confluence` or `drive`. Managers,
directors and executives each author at least one type. The assembled pack
must pass `packs.lint`.

## `timeline`

`{"start": "YYYY-MM", "periods": 2..12, "incidents": ["YYYY-MM"], "changes": [{"period", "kind": "departure" | "reorganisation" | "hire", ...}], "policies": [PackCommitment]}`.
Every period named is inside the history; at least one policy takes effect
after the first period. The org changes are reviewed by `timeline.review`
against the built company (a departure needs a successor).

## `evals`

`{"intents": [{"id", "level", "asker", "ask", "reads": [...], "branch", "per_entity", "deliver"}]}`.
See `evals.md` for the level contract and the read shapes.
