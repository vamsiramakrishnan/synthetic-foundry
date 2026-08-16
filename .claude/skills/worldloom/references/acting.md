---
title: Acting the Employees
description: Drive an actor episode — one employee decision per turn, from only what that employee observed
read-when: A corpus built with --actors agent has an episode waiting for decisions, or an action was refused
tags: [acting, actor-episode, authority, observations, rejections]
---

# Acting

You are here because a corpus was built with `worldloom build --actors agent` and
there is an episode waiting for decisions. This is the job: be each employee in
turn, choose one tool call from what that employee can actually see, and submit
it. Everything below explains the contract precisely enough that a rejection is
fixable on the first read.

The difference from narration is worth stating plainly. Narrating, you are the
author of a document and the harness checks your prose against the facts. Acting,
you are an *employee inside the world* and the harness checks whether you were
entitled to do what you did, on what you knew at the time. Prose is judged for
truth; an action is judged for authority and knowledge.

## The loop

```bash
worldloom build --seed 8128 --incident --actors agent --out ./corpus   # once
worldloom act requests ./corpus -o decision.json                       # repeat
#                                                                        you write action.json
worldloom act accept ./corpus --from action.json --model-id <your model>
```

Until `act requests` prints that the episode is complete. Roughly forty decisions
for the retail-close episode. Then continue the ordinary loop — `narrate`,
`render`, `validate` — because the episode produced artifact *intents* and their
prose still has to be written.

One decision at a time is not a limitation to work around. What the controller
can see at 09:40 depends on whether the business partner escalated at 09:12, so
the later decisions do not exist until the earlier ones are made.

## The decision document

| Field | What it is |
| --- | --- |
| `id` | `<invocation>#<turn>`. Copy it exactly into your action — it is the join key. |
| `title`, `voice` | Who you are. A service desk analyst and a CFO do not make the same move from the same facts. |
| `trigger` | The event that woke you: kind, summary, and when it happened. |
| `facts` | **Everything you know.** Each carries `statement`, `authority`, `valid_from`, and — this is the part that has no equivalent in narration — `learned_at`, `learned_via`, and `confidence`. |
| `messages` | What people have told you. |
| `tasks` | What is on the hook, with `mine` marking the ones you own. |
| `artifacts` | Documents you may see, with `mine` marking your own drafts. |
| `entities`, `roles`, `resources` | The org chart and the systems list — what an employee knows by working here. `resources` maps role keys to ids, and is where `service_id` and `system_id` arguments come from. |
| `tools` | Every tool your role may call, with its arguments and their types. There are no others. |
| `max_tool_calls`, `deadline` | Your budget for this invocation. |

If a fact is not in `facts`, you do not have it. Not from the corpus files, not
from a previous turn as a different employee, not from having read this
repository. That boundary is the entire point: an evaluation asking "who knew the
root cause before the close decision" only has an answer because it was kept.

### `learned_via` is worth reading

Five channels, and they are not equal:

| `learned_via` | You know this because |
| --- | --- |
| `participant` | You were named on the event. First-hand. |
| `trigger` | You were paged about it. This is how a symptom reaches the service desk. |
| `system_of_record` | You own the system that recorded it. |
| `message` | Somebody told you. Second-hand, and `confidence` says so. |
| `artifact` | You can read a document that cites it. Weakest. |
| `duty` | Your role covers the domain, so it reached you through the ordinary flow of work — after a delay. |

Prefer what you observed to what you were told, and say which when it matters. An
engineer who read the ERP logs and an engineer who was told the ERP was fine are
in different positions, and one of them may confirm a root cause.

## The tool families

**Service management** — `search_incidents`, `create_incident`, `update_incident`,
`assign_incident`, `add_work_note`, `request_evidence`, `escalate_major_incident`.

**Engineering** — `query_logs`, `inspect_dependencies`, `record_hypothesis`,
`propose_change`, `approve_change`, `create_remediation_issue`, `publish_runbook`.

**Finance** — `read_ledger`, `query_budget`, `query_forecast`,
`create_variance_analysis`, `request_journal`, `post_journal`,
`escalate_close_issue`, `decide_close_schedule`.

**Documents** — `draft_artifact`, `submit_for_review`, `approve_artifact`,
`request_revision`, `assign_task`.

The reads change nothing and are how you legitimately come to know something you
did not witness: each discloses a bounded slice — the records one system
produced, one service and its immediate dependencies, one subject's ledger lines
— filtered by what your role may read. **Read before you assert.** Every role in
this episode does.

## Why an action gets rejected

| Code | What it means |
| --- | --- |
| `unobserved_fact` | You cited a fact that was not in your `facts`. |
| `not_authorised` | The tool is not one your role holds. It should not have been in `tools`; if it was, you invented the name. |
| `no_decision_right` | You hold the tool but not the standing. Moving a close, approving a change, and posting a journal each have an accountable role. |
| `insufficient_evidence` | You confirmed something without having gone and looked. Call `query_logs` or `inspect_dependencies` first. |
| `domain_not_writable` | You tried to write in a system your role has no standing in — a controller annotating an incident ticket, say. |
| `too_many_facts` | A document may cite at most forty. Choose what matters. |
| `unknown_argument`, `missing_argument`, `bad_argument` | Schema. The tool's `arguments` list is exact. |
| `already_approved`, `no_open_incident`, `self_approval` | A precondition. The world is not in the state this call assumes. |

Nothing is committed on a rejection. Fix the named thing and resubmit — do not
work around it by choosing a different fact, unless the different fact is one you
genuinely observed.

## Play the role

The corpus is worth something because the analyst, the engineer, the business
partner and the CFO see different incidents and act differently on them. What
makes that real:

- **Do the job in front of you.** The analyst raises the ticket and does not
  diagnose. The engineer investigates and does not move the close. The controller
  decides the calendar and does not touch the incident record.
- **Abstain when you should.** `tool_name: null` with an `abstention_reason` is a
  real answer, recorded as one. An actor that keeps acting to fill its budget
  produces noise with timestamps.
- **What you leave out is a decision.** `draft_artifact` chooses which of the
  facts *you* observed belong in a document. The executive summary that omits the
  control failure is not a template rule — it is a CFO citing ten facts and not
  an eleventh, and the corpus can be asked about it afterwards.
- **You do not decide what happened.** The pipeline failed, and the cause is what
  it is, because the deterministic engine says so. You decide when the
  organisation finds out, who records it, and what is done about it.

## How resuming works, and why it matters to you

There is no suspend file. Each call rebuilds the world from the corpus's recipe,
replays every decision the ledger already holds, and stops at the first one nobody
has taken. The ledger is the save file.

Two consequences:

- **`--model-id` is pinned to the corpus on your first accepted decision.**
  Answering turn nine under a different id would miss every key from turns one to
  eight and silently restart the episode. The CLI refuses rather than letting
  that happen.
- **Never hand-edit the corpus mid-episode.** The rebuild would produce a
  different world from the one your earlier decisions were taken in, and the
  ledger keys would stop matching.

## Reading the result

```bash
worldloom actors ./corpus                 # every tool call, accepted and refused
worldloom actors ./corpus --observations  # what each actor could see when it acted
worldloom actors ./corpus --rejected      # only the refusals, and the rule each broke
```

The second is the one worth showing a user. Two people woken by the same failure
with different numbers of visible facts is the corpus's central claim, made
concrete.
