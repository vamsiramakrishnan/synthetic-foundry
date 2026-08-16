---
description: Drive a Worldloom actor episode — be each employee, one decision at a time, through validated tools
tags: [worldloom, acting, actor-episode]
---

Drive the actor episode in the corpus at $ARGUMENTS (default `./corpus`).

You are not writing about this company. You *are*, one decision at a time, an
employee inside it — with only what that employee could see at that moment, and
only the tools their role permits.

```bash
worldloom act requests <CORPUS> -o decision.json
```

Read `decision.json`. It is the whole of your world for this turn: `title` and
`voice` say who you are, `trigger` says what woke you, `facts` is everything you
have observed (with `learned_via` and `confidence` saying *how* you know each
one), plus your `messages`, `tasks`, and the `tools` your role may call.

Write `action.json` — one tool call, `id` copied exactly:

```json
{"actions": [{"id": "INV-0001#0", "tool_name": "create_incident", "arguments": {"...": "..."}}]}
```

Then submit:

```bash
worldloom act accept <CORPUS> --from action.json --model-id claude-opus-5
```

Repeat until `act requests` says the episode is complete. Then narrate, render,
and validate as usual — the episode produced the artifact *intents*; their prose
still comes from `worldloom narrate`.

## The four things that get an action rejected

- **Citing a fact you were not shown.** `facts` is the boundary. Not the corpus
  files, not another turn's document, not what you know from having read this
  repository.
- **Calling a tool you were not offered.** Every tool in `tools` is one your role
  holds. There are no others, and asking for one names the rule that stopped you.
- **Deciding something you have no standing for.** Moving a close, approving a
  change, posting a journal — each has an accountable role, and holding the tool
  is not the same as holding the right.
- **Acting without evidence.** Confirming a root cause requires having gone and
  looked, through `query_logs` or `inspect_dependencies`, in this episode.

Nothing is committed unless the action is legal. **Rejection is the harness
working** — read the rule, fix that, resubmit.

## Play the role, not the omniscient narrator

The corpus is worth something because the analyst, the engineer, and the CFO see
different incidents. A service desk analyst raises the ticket and does not
diagnose. A controller decides the calendar and does not touch the incident
record. When nothing legal and useful is left, abstain and say why — that is a
real answer and it is recorded as one.

`draft_artifact` decides a document should exist and which of the facts *you*
observed belong in it. It does not write the document. What you leave out is a
decision the corpus can later be asked about.

For the tool families, the observation channels, and how the episode resumes,
read `references/acting.md`.
