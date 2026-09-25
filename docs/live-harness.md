# Running Worldloom against a live coding harness

Every seam that takes a coding harness speaks one contract: a JSON document on
stdin, one JSON object on stdout. Worldloom ships the adapter for an installed
`claude` or `codex` login, so none of the commands below needs an adapter script.
This runbook records the paths that were run for real against a signed-in `claude`
CLI, what each one cost, and what went wrong on the way.

The adapter command, as `--harness-command` takes it:

```bash
ADAPTER="python -m worldloom.studio.harness claude --timeout 590"
```

Where a command offers `--harness claude`, that flag spells the same child.

## What each seam asks of the child

| Seam | Tools | Reply | Working directory |
|---|---|---|---|
| Pack interview (`worldloom.pack-interview/v1`) | none | structured output, envelope schema | empty temp dir |
| Evalrun turn, plan, rating | none | structured output, per-seam schema | empty temp dir |
| Company interview, narration | read-only (plan mode) | one JSON object in the result text | the caller's |

Every `claude` child runs with `--no-session-persistence`, and the adapter strips
the caller's `CLAUDE_CODE_SESSION_ID` and `CLAUDE_CODE_REMOTE_SESSION_ID` from its
environment. Without that, a child launched from inside a `claude` session
answered as that session and, in plan mode, wrote its transcript into the
caller's session file.

## 1. Author a pack through an interview

```bash
worldloom pack author industry --name clinics \
  --message "Outpatient clinics. Sites are clinics, customers are patients." \
  --harness-command "$ADAPTER" \
  --into ./my-packs --rounds 3
worldloom studio pack author industry -w ./ws --name vetcare \
  --message "Veterinary practices. Sites are practices, customers are pet owners." \
  --harness-command "$ADAPTER"
```

Measured: one call and about USD 0.05 for an accepted pack. A request that
provoked a lint refusal (an unregistered `engine`) took two calls: the first
proposal came back with `engine: 'veterinary' is not a registered engine`, and the
second fixed it and was stored. Each round is a separate child with the findings
and the refused draft in the request.

## 2. Interview a Studio company

A Studio `interview` job (the console's Interview tab, or `studio serve
--harness claude`) sends `worldloom.company-interview/v1` to the child. The
file-based route is the same request by hand:

```bash
worldloom studio interview request PROJECT --message "Rename the company." -o request.json -w ./ws
worldloom studio interview accept PROJECT --from reply.json -w ./ws
```

Measured on `examples/studio/retail.json`: one call, eight model turns, about
three minutes and USD 0.67. The reply is the whole proposed project (about 16 KB),
and the only changes were the two name fields. This seam keeps read-only tools,
so the child spends turns reading the repository and writes a sentence before the
object; the adapter reads the object past it.

## 3. Narrate until accepted, then render

```bash
worldloom build --seed 8128 --out ./c1
worldloom narrate loop ./c1 --harness claude --max-rounds 3
worldloom render ./c1 -f markdown
worldloom validate ./c1
```

Measured: ten sections, accepted in one round by one call, about six minutes and
USD 0.70. Render and validate passed. With an industry pack in force:

```bash
worldloom --pack industry:banking build --seed 8128 --out ./c2
worldloom --pack industry:banking narrate loop ./c2 --harness claude --max-rounds 3
```

The pack's terms reach every request's `terminology` (`site: call it "branch"`,
`customer: call it "client"`), and the recipe records the pack, so a later
`narrate requests` without `--pack` still carries them. No section of a
default-shaped close corpus, or of a `customer_owned_bank` build, has a fact about
a site or a customer, so the accepted prose had no occasion to use either word.

## 4. Grade the harness as the agent under test

```bash
worldloom studio init examples/studio/retail.json -w ./ws
worldloom studio run PROJECT --operation build -w ./ws
worldloom studio run PROJECT --operation compile -w ./ws
worldloom studio evalrun PROJECT -w ./ws --agent harness --mode plan --limit 3 \
  --harness-command "$ADAPTER"
worldloom studio evalrun PROJECT -w ./ws --agent harness --limit 3 --max-turns 9 \
  --harness-command "$ADAPTER"
```

Plan mode costs one call per case (three calls, about USD 0.14; all three passed,
plan mean 0.97). Run mode costs one call per turn, so `--max-turns` is the budget:
cap it. A turn is cheap (USD 0.02 to 0.07) but a case takes seven to nine of them:
the three cases above took 24 calls and about USD 0.87, every case was graded on
all three axes with no harness error, and none passed (overall mean 0.72). The
reference agent passes the same three cases, so the gap is the harness's. Calls the
agent makes outside the expected DAG are graded as `unknown_node:None`.

## Pitfalls

- Each call is a fresh child. There is no conversation memory beyond what the
  request carries, which is the point: the request is the whole task.
- A job keyed by the same options is the same job. Rerunning an evalrun that
  completed returns the old result; change an option to run again.
- The narration and company interview seams run in plan mode with read-only
  tools. They are the expensive ones; the no-tool seams are an order of
  magnitude cheaper per call.
