# The evalrun harness protocol

Three documents. Each is JSON, each carries a `schema` string, and each is
what the agent may know and nothing more: no expected DAG, no fixture ids, no
assertions ever appear in them. `worldloom seams --json` lists the versions.

## The turn document (`worldloom.evalrun-turn/v1`)

`worldloom evalrun run ./cases --exec "<command>"` runs the command once per
turn with this on stdin:

```json
{
  "schema": "worldloom.evalrun-turn/v1",
  "case_id": "fd3a96d6…",
  "query": "Prepare the stock availability review … Draft a HTML in Email, then read it back.",
  "persona": "",
  "principal": "agent",
  "turn": 3,
  "turns_left": 61,
  "tools": [
    {"name": "jira.search_issues", "op": "search", "entities": ["epic", "story", "bug", "task", "subtask"],
     "params": {"query": "string?", "predicate": "object?", "fields": "array?", "max_results": "int?", "start_at": "int?", "entity": "string?"},
     "annotations": {"readOnlyHint": true, "destructiveHint": false, "idempotentHint": true, "openWorldHint": false},
     "risk": "none", "idempotency": "natural"}
  ],
  "transcript": [
    {"tool": "jira.search_issues", "arguments": {"max_results": 5}, "result": {"items": [{"id": "PROJ-12", "…": "…"}], "is_last": true}},
    {"tool": "jira.get_issue", "arguments": {"id": "PROJ-99"}, "error": {"code": 404, "kind": "not_found", "message": "Issue does not exist…"}}
  ],
  "instructions": ["…"]
}
```

The command prints exactly one JSON object on stdout:

```json
{"call": {"tool": "email.create_draft", "arguments": {"name": "Stock review", "fields": {"subject": "Stock review", "evidence": ["PROJ-12"]}}}}
```

or, to finish:

```json
{"answer": "Drafted the review citing PROJ-12.",
 "artifacts": [{"name": "review", "text": "…", "cites": ["PROJ-12"]}],
 "planned_dag": {"nodes": [{"id": "search", "tool": "jira.search_issues"}]}}
```

- The command is stateless between turns; `transcript` is its memory.
- A tool error is returned in `error`, never raised. Retrying the same
  failed non-idempotent write is graded `unsafe_retry`.
- `annotations.destructiveHint` marks a call that cannot be undone; a
  destructive call on a record no earlier call read is `destructive_without_read`.
- Exiting non-zero, printing something that is not one of the two documents,
  or overrunning `--timeout` ends the case as an **error row** with the
  stderr tail. `--max-turns` (default 64) ends it with an empty answer.
- `planned_dag`, `ttft` and `ttfa` are optional and only ever graded
  against what was observed.

## The requests document (`worldloom.evalrun-requests/v1`)

`worldloom evalrun requests ./cases -o requests.json`:

```json
{
  "schema": "worldloom.evalrun-requests/v1",
  "instructions": ["…"],
  "cases": [
    {"case_id": "fd3a96d6…", "query": "…", "persona": "", "principal": "agent", "max_calls": 1000, "tools": ["… as in the turn document …"]}
  ],
  "response_schema": {"schema": "worldloom.evalrun-responses/v1", "cases": {"<case_id>": {"calls": [["<connector.tool>", {"<param>": "<value>"}]], "answer": "…", "artifacts": [{"name": "…", "text": "…", "cites": ["<record id>"]}]}}}
}
```

## The responses document (`worldloom.evalrun-responses/v1`)

Written by the harness, replayed by `worldloom evalrun run ./cases --agent scripted:responses.json`:

```json
{
  "schema": "worldloom.evalrun-responses/v1",
  "cases": {
    "fd3a96d6…": {
      "calls": [["jira.search_issues", {"max_results": 5}], ["email.create_draft", {"name": "Stock review", "fields": {"subject": "Stock review"}}]],
      "answer": "Drafted the review.",
      "artifacts": [{"name": "review", "text": "…", "cites": ["PROJ-12"]}]
    }
  }
}
```

Replay issues the calls in order and cannot see their results, so an
argument that depends on a returned id cannot be written here. A case left
out is an error row (`not_attempted`), never a pass. The bare
`{case_id: {...}}` form without the envelope is also accepted.

## The rating document (`worldloom.evalrun-rating/v1`)

`--rater exec:"<command>"` runs the command once per answer with this on stdin:

```json
{
  "schema": "worldloom.evalrun-rating/v1",
  "case_id": "fd3a96d6…",
  "query": "…",
  "rubric": "direct_lookup",
  "instruction": "You are grading a factual lookup against a system of record. …",
  "fetched": "<the agent's answer>",
  "golden": "<the golden answer>",
  "prompt": "<instruction>\n\n    Query: …\n    Fetched Response: …\n    Golden Response: …\n\n    Provide only the score as a float between 0.0 and 1.0.",
  "instructions": ["…"]
}
```

The command prints `{"score": 0.85}` or `{"text": "Score: 0.85"}`; text is
salvaged the way Eval Studio salvages it and clamped to `[0, 1]`. A non-zero
exit, a malformed reply or a timeout is a rating error on the case: the
answer axis is unrated there and excluded from its mean.

## Served scoring (`eval_score`)

An agent reaching the corpus over `worldloom enterprise-evals serve` calls
`eval_score(run_id, answer?, artifacts?, planned_dag?)` before `eval_end`.
The reply is a complete `CaseResult` graded by the serving service from the
state snapshot taken at `eval_begin`, the live state, and the observed spans.
Write one per line to a JSONL file; `worldloom evalrun import-served ./cases
scores.jsonl -o ./runs/served` collects them, refuses a case id outside the
set, and reports a missing case as `not_attempted`.

## The run directory

`run.json` (schema `worldloom.eval-run/v1`, agent, principal, `case_set`
digest), `results.jsonl` (one `CaseResult` per line: status, error, the
three grades, assertion status, answer, spans, latency when timed), and
`summary.json` (`worldloom.eval-run-summary/v1`). `compare` reads two of
them and refuses nothing, but says when the `case_set` digests differ.
