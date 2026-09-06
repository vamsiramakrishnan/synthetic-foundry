---
title: Actors
description: Drive the incident's records through employees who see projections, one validated decision at a time.
read-when: Asked who decides what the incident's documents say, or driving an episode with --actors.
tags: [actors, episodes, observations, replay, decisions]
---

# Actors, optionally

`worldloom build --actors` changes who decides what the incident's records say.
It takes `scripted`, the built-in deterministic actor with no network and no
key, or `agent`, which leaves every decision for you.

Without it, the planner writes the incident documents from the whole fact ledger:
it knows the root cause, the control failure, and the remediation, and it hands
each document the facts a document of that type should carry. With it, the
documents are produced by employees calling tools on **what they had actually
observed at the time**, and nothing else:

```bash
# You make every decision, one at a time, through the same kind of handshake
# narration uses. Roughly forty turns for this episode.
worldloom build --seed 8128 --incident --actors agent --out ./corpus
worldloom act requests ./corpus -o decision.json      # what one employee can see
#                                                       you write action.json
worldloom act accept ./corpus --from action.json      # validated before it changes anything
worldloom actors ./corpus --observations              # who could see what, when

# Or let the scripted actor run the whole episode, for CI and for a quick look.
worldloom build --seed 8128 --incident --actors scripted --narrate -f markdown --out ./corpus
```

```
pipeline fails
  → the service desk analyst is paged, opens the incident, puts up a status page
  → the engineer inspects the dependency chain and records a first assessment
  → the divisional finance partner reads the ledger and raises a close dependency
  → the controller is told, and writes a working note
  → the incident commander asks for evidence and names an owner
  → the engineer reads the ERP logs and confirms the cause
  → the controller decides the close moves, with the CFO named as approver
  → the platform lead raises two fixes and says which one fixes the control
  → the CFO writes a short summary, and leaves the control failure out of it
```

Four things are true of every step, and they are what the actor layer is for:

- **An actor sees a projection, never the world.** A provider is handed an
  observation and a tool catalogue. There is no accessor on either that reaches a
  `World`.
- **Only an accepted tool call changes anything.** Refusals are recorded with the
  rule they broke and change nothing; `worldloom actors ./corpus --rejected`
  shows them.
- **Canonical truth is still deterministic.** The pipeline fails because the
  operational generator says so, and the cause is the stale hierarchy mapping
  because 2024 lore made it so. An actor chooses *when the organisation finds
  out, who records it, and what gets written down*, never what happened.
- **It replays.** Every decision is content-addressed into the same generation
  ledger narration uses, so `--replay` regenerates the episode byte-for-byte with
  no provider at all.

The last one is why the CFO's summary omitting the control failure is worth
something: it is a citation that one person did not make, reproducibly, rather
than a rule in a template.

**One decision per exchange, and that is not a limitation to route around.**
Narration hands you every request at once because a memo's third section does not
depend on its second. An episode does: what the controller can see at 09:40
depends on whether the business partner escalated at 09:12, so the later
invocations do not exist until the earlier decisions are made.

Resuming needs no suspend format. Each call rebuilds the world from the corpus's
recipe, replays every decision the ledger already holds (the provider is never
asked for those) and stops at the first one nobody has taken. The ledger was
already shipping; it is now also the save file. Two consequences: `--model-id` is
pinned to the corpus on the first accepted decision, because answering turn nine
under a different id would miss every key before it and silently restart the
episode; and hand-editing a corpus mid-episode makes the rebuild produce a
different world from the one your earlier decisions were taken in.

In-process is the other route: implement `act(view, tools) -> ActorAction` and
the ledger, the policy checks, and the rejection loop all work unchanged around
it.
