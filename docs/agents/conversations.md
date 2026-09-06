---
title: Conversations
description: Record who came to know each fact, when, and through which channel, without adding facts.
read-when: The corpus should answer information-asymmetry questions, or authors must only cite what they heard.
tags: [conversations, knowledge-ledger, observations, messages]
---

# Conversations, optionally

An event mints facts and makes documents necessary, and it makes **people
talk**. `--conversations` records that third output, which the corpus modelled
and never produced outside the actor runtime:

```bash
worldloom build --seed 8128 --incident --conversations --out ./corpus
worldloom actors ./corpus --observations       # who came to know how much, and how
```

```
What each employee came to know
 role                            first heard         facts  by channel
 Group Financial Controller      2022-01-01 04:00      600  duty 11, message 2, participant 584 …
 Service Desk Analyst            2022-01-01 04:00       18  duty 7, message 5, participant 2 …
```

Two files come out, `actor-observations.jsonl` and `actor-messages.jsonl`, and
between them they answer a question the fact ledger structurally cannot. A fact
carries one `valid_from`; knowledge carries one moment *per person*. Six hundred
figures reach the controller and eighteen reach the analyst, and neither of them
is wrong.

It adds no facts, no events and no documents. What it adds is:

- **A knowledge ledger.** Each fact reaches each employee through one of the
  channels in `actors/observation.py` (witnessed it, was paged about it, owns
  the system that recorded it, was told, read it, or picked it up on the
  ordinary flow of work), and the channel decides both *when* and *how much the
  account is worth*.
- **Messages.** Derived, never invented: somebody is told where the routing
  table wakes them, or where the document plan makes them the author of
  something that event established. The second is the one that mattered: the
  controller's working note cites a root cause their role cannot read, so before
  this the corpus had authors writing about facts no channel could deliver to
  them.
- **Information-asymmetry questions.** *Which employee was first to have a record
  of this? By the time the last of them heard, who had already been able to act?
  Who told them?* Every answer is recomputed from the ledger, so none of them can
  be a sentence somebody wrote.

Four invariants, checked by `worldloom validate` on the shipped files rather than
on the code that wrote them: nobody knows a fact before it was true, nobody
learns anything outside their employment, nobody discloses what they do not yet
hold, and no author cites a fact they never heard.

It is opt-in and refused alongside `--actors`, which derives its own: two
producers appending to one knowledge ledger is two accounts of who knew what.
