# The evalrun harness protocol

Three documents. Each is JSON, each carries a `schema` string, and each is
what the agent may know and nothing more: no expected DAG, no fixture ids, no
assertions ever appear in them. `worldloom seams --json` lists the versions.

## The turn document (`worldloom.evalrun-turn/v2`)

`worldloom evalrun run ./cases --exec "<command>"` runs the command once per
turn with this on stdin:

```json
{
  "schema": "worldloom.evalrun-turn/v2",
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
     "risk": "none", "idempotency": "natural",
     "query": {"language": "jql", "argument": "query", "name": "JQL (Jira Query Language)",
               "grammar": "clauses `field OP value` joined by AND, OR, NOT …", "free_text": "text ~ \"words\" …",
               "examples": ["project = OPS AND status = open ORDER BY created DESC", "…"],
               "fields": ["assignee", "cf[10231]", "created", "…"]}}
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

or, to ask the user a question:

```json
{"ask": {"question": "Two printer incidents are open; which one do you mean, level 3 or level 4?", "about": ["INC0000001", "INC0000002"]}}
```

The reply arrives in the transcript on the next turn as
`{"ask": "...", "about": [...], "reply": "The one on level 3."}`. A question
is a turn: it is recorded where it was asked, beside the calls, and graded
on the trajectory axis (see below). It costs a turn from `turns_left` and no
call from the case's call budget.

or, to finish:

```json
{"answer": "Drafted the review citing PROJ-12.",
 "artifacts": [{"name": "review", "text": "…", "cites": ["PROJ-12"]}],
 "planned_dag": {"nodes": [{"id": "search", "tool": "jira.search_issues"}]}}
```

- The command is stateless between turns; `transcript` is its memory.
- A tool error is returned in `error`, never raised. Retrying the same
  failed non-idempotent write is graded `unsafe_retry`.
- A call the run does not admit (a tool not in `tools`, a parameter the tool
  does not declare, the call limit) comes back as `error` with kind
  `serving`. It reached no connector, so it is not a span, but it is a
  refused attempt: it costs trajectory precision and its pass, and it is on
  the ledger as `refusals`.
- `query` on a search tool says what its `query` argument is written in: the
  vendor language (JQL, SOQL, a ServiceNow encoded query, OData, CQL, KQL,
  Drive `q`, Slack search) with a grammar summary, examples in that syntax,
  the field names the connector knows and the free-text form (ServiceNow
  `123TEXTQUERY321=`, Jira and Confluence `text ~`, Drive `fullText contains`,
  KQL bare terms; SOQL has none, so `LIKE '%word%'`). The query runs through
  the vendor evaluator, and a query the vendor would refuse comes back with
  the vendor's own error. `"argument": "predicate"` means the tool reads no
  vendor language: pass `predicate` as `{"where": [{"field", "op", "value"}]}`.
- `annotations.destructiveHint` marks a call that cannot be undone; a
  destructive call on a record it names by `id` (a delete, a reply, a
  forward) that no earlier call read is `destructive_without_read`.
- Ask when the request is ambiguous, a required parameter is missing, or a
  call would be destructive and the request did not authorise it. The row
  declares which questions it requires (`question_required` assertions,
  `confirm_before` for a delete); the service answers from the row and
  never says whether the question was expected. Four laws, named in
  `worldloom seams --json` as `question_laws`: `acted_without_asking` (a
  required question was never asked), `asked_too_late` (a call the question
  blocks ran first), `ignored_the_answer` (the reply declined and the call
  ran anyway), `asked_without_need` (a question no point of the row wanted).
  Each required point honoured counts toward the trajectory score exactly
  as a designed failure does; a case that wants no questions and gets none
  scores as it always did.
- Exiting non-zero, printing something that is not one of the two documents,
  or overrunning `--timeout` ends the case as an **error row** with the
  stderr tail. `--max-turns` (default 64) ends it with an empty answer.
- `planned_dag`, `ttft` and `ttfa` are optional and only ever graded
  against what was observed.

### The contract surface, in process (the default; `--surface native` for connector tools)

`worldloom evalrun run ./cases --exec "<command>"` keeps the run in process
and shows the agent each contracted connector's real operations, exactly as
Anvil's MCP server lists them for its contract (policy `connectors.surface`,
`contract` by default; `--surface native` shows every connector definition's
own `connector.tool` entries instead): each
entry in `tools` is Anvil's tool (`name` such as `jira_get_issue`, `title`,
`description`, `inputSchema`, `annotations`) plus `connector`, `operation`,
`method`, `path`, `params` (the argument names), `examples` and, for a tool
whose mapped call reads a vendor query, `query` with its `argument` (e.g.
`body.jql`). A `call` names that tool with those arguments (a write that
needs confirmation takes `"confirm": true`), and the result is the vendor's
response body; a refused call's `error` also carries `envelope`, Anvil's
`{"error": {code, message, ...}}`. A connector with no locked contract keeps
its own `connector.tool` entries. A write keeps its evidence where the
vendor does (a file's `description`, a record's `work_notes`), which is the
place a gold plan writes it and the output grade reads it from. The same
surface proves a case set (`worldloom evalrun prove ./cases`, naming each
gold call no operation carries as a `contract.gap`), and
`worldloom contracts surface` refreshes or checks the surfaces the package
ships (`docs/connector-serving.md`, "One surface from the contract").

### Served through Anvil (`--connectors anvil`)

`worldloom evalrun run ./cases --exec "<command>" --connectors anvil --contract <bundle>`
serves each case's connectors through `anvil simulate serve` instead of the
in-process emulator: the agent calls the vendor's real REST paths (Jira's
`POST /rest/api/2/search/jql`, `GET /rest/api/2/issue/{key}`, ...) over HTTP.
The bundle is the vendor's real contract under Worldloom's profile:
`worldloom contracts fetch` downloads the locked spec and refuses one whose
sha256 moved, `worldloom contracts build jira` compiles and approves it with
Anvil and prints the bundle path to pass as `--contract jira=<bundle>`, and
`worldloom contracts coverage` says which operations each connector models
(`docs/connector-serving.md`, "Real vendor contracts"). A maintainer's
`worldloom contracts trim` cuts a small test fixture from a locked spec.
The command's environment carries, on every turn:

| Variable | Value |
|---|---|
| `ANVIL_BASE_URL` | The server of the case's first connector (alphabetically); for a one-connector case, the only one |
| `ANVIL_<CONNECTOR>_BASE_URL` | Each connector's server, e.g. `ANVIL_JIRA_BASE_URL` |
| `ANVIL_CONNECTORS` | The case's connectors, comma-separated |
| `ANVIL_TOKEN` | The bearer token to send (`Authorization: Bearer $ANVIL_TOKEN`); `admin`, Anvil's principal holding every scope |

The turn document gains `"anvil": {"base_urls": {"jira": "http://127.0.0.1:…"},
"base_url_env": "ANVIL_BASE_URL", "token_env": "ANVIL_TOKEN"}`. `tools` still
describes the connectors, but a `call` document is refused with kind
`serving` (`anvil_mode: …`) and recorded as a refusal: the calls graded are
the ones Anvil served. An agent typically makes its HTTP calls inside one turn
and answers; `ask` works as it does in process.

When the case ends, the servers stop and their JSONL traces are replayed into
the case's run, so plan, trajectory, outcomes and every stage are graded by
the same code as an in-process run. A call Anvil answered itself (auth, an
`X-Anvil-Fault`, an idempotent replay) is a refusal; an operation the mapping
marks unmodelled answers `unsupported_operation` and is a refusal too.
Each case's state, traces and server logs stay under `--out`/anvil. The Anvil
CLI is `--anvil-cmd`, else `$WORLDLOOM_ANVIL`, else `anvil` on `PATH`.
`docs/connector-serving.md` ("Serving through Anvil") has the mapping and the
provider.

## The program document (`worldloom.evalrun-program/v1`)

`worldloom evalrun run ./cases --exec "<command>" --harness-mode sdk-program`
runs the child **once per case** and asks it for a Python program instead of
one call per turn. On stdin:

| Field | Meaning |
|---|---|
| `schema` | `worldloom.evalrun-program/v1` |
| `case_id`, `query`, `persona`, `principal` | The request, as in a turn document |
| `tools` | The case's tool catalog, as in a turn document |
| `client` | `{module: "worldloom_client", source, endpoint_env: "WORLDLOOM_TOOL_URL"}`: a generated module with one method per tool (`worldloom_client.<connector>.<tool>(**arguments)`, or `worldloom_client.call("<connector.tool>", **arguments)`; a tool error raises `worldloom_client.ToolError`) |
| `anvil` | Under `--connectors anvil`: the base URLs, as in a turn document; the program calls the vendor API instead |
| `instructions` | The `evalrun.program.rule.*` texts |
| `program_timeout` | Seconds the program may run (`--program-timeout`, 300) |

The child prints `{"program": "<python source>"}`, optionally with
`"planned_dag": {"nodes": [...]}` (the plan-document shape). Worldloom writes
the program beside `worldloom_client.py`, runs it with `WORLDLOOM_TOOL_URL` (a
local HTTP shim over the run's own tool surface) and any Anvil variables in
its environment, and grades the calls it made. The program prints its answer
last: a JSON line `{"answer": ..., "artifacts": [...]}`, else its stdout is
the answer. A program that exits non-zero or times out is an error row. The
ledger line carries `program` (source, digest, exit code, output tails, the
declared DAG and whether it came from the reply or was read off the source).
Calls the program issues concurrently (threads) are recorded as one step.
Grading, including data-flow lineage and the declared-against-executed
divergence, is in `docs/eval-execution.md` ("Plans as data flow").

## The requests document (`worldloom.evalrun-requests/v1`)

`worldloom evalrun requests ./cases -o requests.json`. In a responses
document a question is written in `calls` as `["ask", {"question": "...",
"about": [...]}]`; replay cannot read the reply, but the question is recorded
where it was asked.

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

## The plan document (`worldloom.evalrun-plan/v1`)

`worldloom evalrun plan ./cases --exec "<command>"` runs the command once per
case with this on stdin (the same `tools` as a turn document, no transcript):

```json
{
  "schema": "worldloom.evalrun-plan/v1",
  "case_id": "fd3a96d6…",
  "query": "Prepare the stock availability review … Draft a HTML in Email, then read it back.",
  "persona": "",
  "principal": "agent",
  "tools": ["… as in the turn document …"],
  "instructions": ["…"]
}
```

The command prints exactly one JSON object: the DAG it would run. Nothing is
executed.

```json
{"plan": {"nodes": [
  {"id": "search", "tool": "jira.search_issues", "entity": "issue"},
  {"id": "draft", "tool": "email.create_draft", "depends_on": ["search"], "entity": "message"},
  {"id": "readback", "tool": "email.get_message", "depends_on": ["draft"]}
]}}
```

- Node ids are the planner's own; grading matches by tool name, in the
  expected order, and grades an expected edge as reachability through
  `depends_on`. Ids must be unique, dependencies must name a node, and a
  cycle is a contract breach.
- A non-zero exit, a reply that is not a plan, or a timeout is an error row.
- `worldloom evalrun requests ./cases --for plan -o requests.json` writes the
  same requests for offline answering; the reply file
  (`worldloom.evalrun-plans/v1`) is `{"schema": "worldloom.evalrun-plans/v1",
  "cases": {"<case_id>": {"nodes": [...]}}}`, replayed by
  `worldloom evalrun plan ./cases --agent scripted:plans.json`. A case left
  out is `not_attempted`.

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
three grades, assertion status, answer, spans with their data-flow
`consumed_from`, latency when timed, the program of an `sdk-program` run), and
`summary.json` (`worldloom.eval-run-summary/v1`). `compare` reads two of
them and refuses nothing, but says when the `case_set` digests differ.
