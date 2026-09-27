# Serve a connector evaluation to an external agent

`worldloom enterprise-evals serve` exposes the tools in the selected
`ConnectorDefinition`s over MCP StreamableHTTP at `/mcp`. Reads, searches,
updates and workflow transitions use the same emulator as local evaluation.
Each run starts with its own copy of the corpus. Calls change only that run.
The exported corpus remains unchanged.

Install the optional transport and validate the configuration:

```console
pip install 'worldloom[mcp]'
worldloom enterprise-evals serve dist/enterprise-evals --check
worldloom enterprise-evals serve dist/enterprise-evals --port 8000
```

Point an MCP client at `http://127.0.0.1:8000/mcp`. The client calls:

1. `eval_list` to find the query ID and request. Results are paginated.
2. `eval_begin(query_id)` to receive a `run_id`.
3. Connector tools, such as `servicenow.get_record`, with that `run_id` and the
   tool's declared arguments. `tools/list` describes required arguments,
   projections, paging and read/write annotations.
4. `eval_trace(run_id)` to retrieve captured `worldloom.connector-trace/v1`
   spans. Follow `next_offset` until it is null.
5. `eval_grade(run_id)` to grade actual calls and post-state, or
   `eval_score(run_id, answer?, artifacts?, planned_dag?)` for the three-axis
   `worldloom.eval-run` case result (plan, trajectory, outcomes) graded from
   the state snapshot taken at `eval_begin` and the live state now. Keep each
   document; `worldloom evalrun import-served` collects them into a run.
6. `eval_end(run_id)` to grade and release the run.

Retrieve the trace before ending. Runs live in memory and are lost when the
process stops. A request that starts a run is not idempotent: save the returned
handle. There is no automatic expiry, replay cache or shared storage. End runs
explicitly. Run one worker; multiple workers need a routing layer that keeps a
run on its owning process.

## Bound the surface

Use `--query-id` repeatedly to select a workload and `--tool` repeatedly to
allow exact `connector.tool` names. Startup refuses an allowlist that removes a
tool required by the selected queries. It also refuses an unknown definition
or unexecutable compiled row. The default ceiling is 100 tools including the
six evaluation tools. Select a smaller workload when its connector estate
exceeds that ceiling.

Defaults permit 32 live runs, four per principal, 4,096 attempted connector calls
per run, 64 KiB request bodies, 1 MiB connector responses and 100,000 initial
records; each is the policy `connectors.serving.<limit>`. Trace pages also obey a byte budget: one bounded result plus its
bounded request and 16 KiB of framing room. `--max-runs` and `--max-calls` override the common limits;
`ServingLimits` configures all of them. Oversized connector responses roll back
that call, including writes. The trace records the failed attempt. The SDK's
synchronous tools serialize the calls of one run under that run's lock, and
calls on different runs proceed in parallel; this is an evaluation service,
not a high-throughput connector proxy.

Runs live in the memory of the process that began them, so one server is one
worker. To serve more, start several processes, give each its own
`--worker-id` (worker `w3` mints run ids `w3-run-1`, `w3-run-2`, ...), and put
them behind a proxy with sticky routing by run id. A call that reaches a
process that did not begin its run is refused as an unknown run; run state is
never shared between processes.

## Authentication and TLS

Anonymous operation binds to loopback by default. For a non-loopback bind,
`--tokens-env` names an environment variable containing a JSON object mapping
principal names to bearer secrets. Supply secrets through your secret manager;
use at least 24 characters and a distinct secret for each principal. The
variable's value is never printed. A `--allowed-host` must name the external
Host header accepted from the TLS proxy.

```console
worldloom enterprise-evals serve dist/enterprise-evals --host 0.0.0.0 --tokens-env WORLDLOOM_MCP_TOKENS --allowed-host evaluations.example.com
```

Clients send `Authorization: Bearer <their-secret>` on every HTTP request.
The server binds run access to that authenticated principal. Another principal
cannot read, grade, mutate or end a run even if it knows the run ID. Separate
runs under the same principal also have separate record state. Loopback mode
is one trusted local principal; use distinct bearer credentials to separate
users. CORS is not enabled; browser front ends should use a trusted backend.

For Gemini Enterprise, configure a custom MCP data store against the HTTPS
endpoint. Its documented transport is StreamableHTTP, its TLS certificate must
come from a publicly trusted CA, and Google recommends at most 100 enabled
actions. OAuth 2.0 and private Cloud Run invocation are supported by the
product. See Google's [custom MCP setup instructions](https://docs.cloud.google.com/gemini/enterprise/docs/connectors/custom-mcp-server/set-up-custom-mcp-server).

This server validates configured bearer credentials; it does not provide an
OAuth authorization server. For Gemini Enterprise OAuth, an identity-aware
proxy must validate the user's OAuth token and supply a distinct configured
bearer credential for that evaluation principal. Preserve principal isolation
at that boundary. TLS termination, OAuth configuration and Cloud Run IAM are
deployment work. They are not performed by `serve`.

The implementation uses [the official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/)
2.2.x-compatible APIs. The `mcp` extra is bounded to `>=2.2,<3`; the existing
`worldloom mcp` stdio tool surface uses the same SDK version.

## SDK and grading

```python
from worldloom.connectors import ConnectorEvaluationService, create_connector_app
from worldloom.enterprise_io import load_exported_corpus

corpus = load_exported_corpus("dist/enterprise-evals")
service = ConnectorEvaluationService.from_corpus(corpus)
application = create_connector_app(service)  # ASGI app for a local host
```

`from_corpus` validates evidence and fixture references before exposing any
query. Ungrounded placeholders are refused. Compiled rows retain authored
custom connector definitions; conflicting definitions require one explicit
host override.

The service also accepts compiled eval rows, canonical records and custom
connector definitions directly. No MCP dependency is needed for that
synchronous SDK path. A trusted embedding supplies the principal to `begin`,
`call`, `trace`, `grade` and `end`.

Node attribution comes from the server's observed tool and target identity.
For `enterprise-dag@1`, it also checks argument bindings against captured native
results, evaluates branch conditions and tracks each bounded loop item. Pure
transforms derive their values from those results without adding model tools.
An agent cannot submit its own trace, node labels, post-state or assertions.
The grader reports the established `status`, `fails`, executed spans and DAG
format. Missing calls, incorrect order and wrong target state remain visible.
The surface grades the compiled assertions; it does not evaluate the quality
of a prose answer or treat an agent's claim of refusal as observed behavior.

## Native vendor queries (the default)

A search tool's `query` string runs as the vendor's own query language through
`worldloom.connectors.query`: the policy `connectors.query.engine` is `native`
by default. The historical conjunctive subset (`field = value AND ...`,
compiled to a Worldloom predicate) is still there as `predicate`, for a run
that must reproduce a ledger written before the default changed: set the
policy to `predicate`, or construct `ConnectorEmulator(..., query_engine="predicate")`.
The default moved because a pilot's call errors were mostly valid vendor
queries the historical parser refused (SOQL `ORDER BY ... LIMIT`, ServiceNow
`ORDERBY`, JQL `OR`).

Every search tool's catalog entry (`tools[*].query`) and its MCP description
say which language its `query` is read in, with a grammar summary, examples in
that vendor's syntax and the free-text form; see `docs/eval-execution.md`,
*Solvability and pins*.

A policy pack that selects the historical parser:

```json
{"schema": "worldloom.pack/v1", "kind": "policy", "name": "legacy-queries",
 "body": {"values": {"connectors.query.engine": "predicate"}}}
```

Which language a tool reads is its connector's `query_language`, except that
SharePoint's `search_files` and `search_pages` and OneDrive's `search_items`
read KQL (their list endpoints stay OData). Connectors whose language the
evaluator does not parse (Teamwork Graph's GraphQL, Rovo search, the system
of record) keep the historical path under either setting.

| Language | Connectors | Supported subset |
|---|---|---|
| JQL | Jira | `= != > >= < <= ~ !~ IN NOT IN`, `IS [NOT] EMPTY`, `AND OR NOT`, parentheses, `ORDER BY`, `currentUser()`, `now()`, `startOf`/`endOf` `Day Week Month Year(inc)`, relative dates like `-7d` |
| SOQL | Salesforce | `SELECT .. FROM obj WHERE .. ORDER BY .. [NULLS FIRST/LAST] LIMIT OFFSET`, `= != < > <= >= LIKE IN NOT IN INCLUDES EXCLUDES`, date literals (`TODAY`, `LAST_N_DAYS:n`, `THIS_QUARTER`, ...), relationship paths (`Account.Name`) |
| Encoded query | ServiceNow | `^`, `^OR`, `^NQ`, `= != LIKE STARTSWITH ENDSWITH IN NOT IN ISEMPTY ISNOTEMPTY > < >= <= BETWEEN ON`, `ORDERBY`/`ORDERBYDESC`, `javascript:gs.daysAgoStart(n)` and the other `gs` date helpers |
| OData | Outlook, email, Teams, OneDrive and SharePoint lists | `$filter` with `eq ne gt ge lt le in and or not`, `startswith`, `endswith`, `contains`, `any()`/`all()` on simple collections; `$orderby`, `$top`, `$skip`, `$select`, `$search` |
| CQL | Confluence | `space type title text ~ label creator created lastmodified ...`, `AND OR NOT`, `ORDER BY`, `now("-4w")` |
| KQL | SharePoint and OneDrive search | free text, `"phrases"`, `prefix*`, `prop:value`, `prop>date`, `AND OR NOT`, `-term` |
| Drive `q` | Google Drive | `name contains`, `fullText contains`, `mimeType =`, `modifiedTime >`, `'id' in parents`, `trashed = false`, `and or not` |
| Slack search | Slack | `in:#channel`, `from:@user`, `before:` `after:` `on:` `during:`, `-term`, free text |

Every relative date resolves against the connector definition's `clock`, the
corpus's as-of time. Field names bind to record keys through the definition's
`query_fields` and field manifests, then the vendor names listed per language
in `worldloom/_data/connectors/_query.json`, then any key the records carry.
Free text ranks by BM25 over the record's text fields with ties broken by
record id; an explicit order also breaks ties by id.

A query outside the subset is refused the way the vendor refuses it, with the
vendor's HTTP status and message on the `ConnectorError` (the full vendor
response body is on the underlying `QueryError`). Jira answers an unknown
field with `Field 'foo' does not exist or you do not have permission to view
it.`, Salesforce with `INVALID_FIELD` and a row and column, Graph with
`Invalid filter clause: Could not find a property named 'foo' on type
'microsoft.graph.message'.`, Confluence with `Could not parse cql`, Drive with
`Invalid Value`. ServiceNow drops a condition on an unknown field and
SharePoint searches an unknown property as text, because those products do.
The templates live in `_query.json`, not in code.

An out-of-process provider uses the same three calls the emulator does:

```python
from datetime import datetime

from worldloom.connector_definition import load_connector_definition
from worldloom.connectors.query import bind, execute, parse, target_for

definition = load_connector_definition("jira")
records = [{"fid": "r1", "ident": "PHX-1", "project": "PHX", "summary": "Checkout outage"}]
query = parse("jql", 'project = PHX AND text ~ "outage"', clock=datetime.fromisoformat(definition.clock))
target = target_for(definition, records=records)
result = execute(bind(query, target), records, target)
[records[index]["ident"] for index in result.matches]  # ["PHX-1"]
```

## Serving through Anvil

Anvil compiles a vendor's published API spec into a contract and serves it
with `anvil simulate serve`:
the vendor's own paths and methods, auth scopes, idempotency replay, injected
faults (`X-Anvil-Fault`), page envelopes and the contract's error statuses.
With `--provider-cmd`, the records and what a query means come from a state
provider speaking newline-delimited JSON-RPC 2.0 on stdio. Worldloom ships
one:

```sh
anvil simulate serve --contract ./jira \
  --provider-cmd "python -m worldloom.anvil_provider --corpus ./cases --connector jira" \
  --port 0 --trace ./calls.jsonl
```

The provider answers `initialize` (it refuses any `protocolVersion` but 1,
and any contract its mapping does not cover), `invoke` (one normalized
request per call that passed Anvil's surface gates) and `shutdown`. Stdout
carries protocol lines only; diagnostics go to stderr, which Anvil forwards.

| Option | Meaning |
|---|---|
| `--corpus DIR` | A case set (`records.jsonl` beside `evalrun-cases.jsonl`), an enterprise export (`connector-data.json`), or a bare `records.jsonl` |
| `--connector NAME` | The connector whose records and mapping serve the contract |
| `--as-of TIME` | The ISO time relative query dates resolve against (default: the definition's `clock`) |
| `--actor NAME` | Who a write is recorded as (default `agent`) |
| `--snapshot-out FILE` | At shutdown, every record by fid: the post-state of a state diff |
| `--mapping FILE` | A mapping other than the shipped one |
| `--lint CONTRACT` | Check the mapping against a bundle, its `air.json`, or a saved `initialize` operation table, and exit non-zero on an unmapped operation |

Reads and lists come from the connector's records; a search passes its query
parameter (Jira's `jql`) through the shared vendor query evaluator
(`connector_search`, the `native` engine above), so a malformed or unknown
field is refused with the vendor's own status and body. Writes go through the
emulator's state, so the diff between the corpus and `--snapshot-out` is the
state diff. A domain error is a provider error: Anvil's code (`not_found`,
`validation_error`, ...), the connector's error kind as `upstreamCode`, the
vendor's status, and the vendor's error body. Cursors are the decimal offset
of the next item, so paging is deterministic.

### The mapping

Each contract's operations map onto the connector definition's tools in
`worldloom/_data/connectors/anvil/<connector>.json`
(`worldloom.anvil-mapping/v1`). Jira ships, for the Jira Cloud platform v3
spec trimmed to the 26 operations of Anvil's Jira backtest and compiled with
`--service jira`:

```json
{
  "schema": "worldloom.anvil-mapping/v1",
  "connector": "jira",
  "service": "jira",
  "error_body": {"errorMessages": ["{message}"], "errors": {}},
  "transitions": [{"id": "31", "name": "In Review", "to": "review"}],
  "operations": {
    "jira.jql.search": {
      "route": "POST /rest/api/2/search/jql",
      "vendor": "searchAndReconsileIssuesUsingJqlPost",
      "tool": "search_issues",
      "args": {"query": {"from": "body.jql", "required": true},
               "max_results": {"from": "body.maxResults", "transform": "int"}},
      "cursor": "body.nextPageToken",
      "result": {"shape": "token_page", "items": "issues", "next": "nextPageToken", "last": "isLast"}
    },
    "jira.transitions.create": {
      "route": "POST /rest/api/2/issue/{issueIdOrKey}/transitions",
      "tool": "transition_issue",
      "args": {"id": {"from": "path.issueIdOrKey", "required": true},
               "state": {"from": "body.transition", "transform": "transition", "required": true}},
      "result": "empty"
    },
    "jira.issue.delete": {"route": "DELETE /rest/api/2/issue/{issueIdOrKey}",
                          "unmodelled": "the jira definition declares no delete tool; issues are closed by transition"}
  }
}
```

- An entry is keyed by Anvil's `operationId`; `route` matches it when the
  contract was compiled under another service id, and `vendor` (the spec's own
  operationId) matches it in a lint over the contract's AIR.
- `args` read from `body.*`, `path.*`, `query.*`, `header.*` or `page.*`,
  through a named `transform`: `int`, `csv` (a field list; `*all` means all),
  `text` (Atlassian Document Format to text), `entity` (a vendor type name to
  the definition's entity), `jira_fields` (a REST `fields` object to record
  fields: option objects to their scalar, `customfield_*` to the definition's
  custom field name, a status name to its workflow state), `assignee`, and
  `transition` (a transition id or name to the state it leads to).
- `result` shapes the answer: `record`, `pick` (named keys, as a create's
  `{id, key, self}`), `empty` (Jira's 204 edits and transitions), `page` (Anvil
  paging), `token_page` (a vendor continuation token in the body), and the
  derived `comments` and `transitions` lists read from the record.
- An argument may instead be a constant (`{"value": "page"}`), an `object`
  assembled from several locations (`{"object": {"title": "body.title"}}`),
  or a list of locations tried in order (Graph's contract spells an action
  body `DestinationId` where its documentation writes `destinationId`); a
  value may pass through a `map` (a ServiceNow table to its entity) and an
  object through a `rename` (`toRecipients` to `recipients`). More
  transforms: `fields` (a body as record fields, vendor-wrapped values
  unwrapped), `odata` (Graph options as one option string), `cql` (Confluence
  v2 filters as CQL), `slack_in`, `slack_ts`, `flatten`, `drive_item_entity`
  and `locator_query`.
- `tool_by` chooses the tool by a request location or by the addressed
  record (`record.entity`): ServiceNow's one Table API route serves every
  table, and Drive's one PATCH updates a Google Doc and an upload with
  different tools. `*` matches any value present (a PATCH with a new
  `parentReference` is a move).
- `result` may carry an `envelope`, the vendor's body as a template:
  `{"result": "$items"}` for ServiceNow, `{"totalSize": "$total", "done":
  "$is_last", "nextRecordsUrl": "$next_link", "records": "$items"}` for
  Salesforce. A key whose continuation does not exist (the last page) is
  left out. When Anvil pages the operation itself, the provider answers the
  protocol's `items` and `nextCursor` instead and Anvil writes the envelope.
- An operation the connector has no state for is marked `unmodelled` with a
  reason and answered `unsupported_operation`.

The lint refuses a mapping that leaves an exposed operation neither mapped nor
marked unmodelled, or names a tool or argument the definition does not
declare. It runs at the handshake, so Anvil refuses to serve an uncovered
contract rather than answer some operations from nowhere, and it runs before
any case in the runner mode below.

### An eval run through Anvil

`worldloom evalrun run --connectors anvil --contract <bundle>` (repeat
`--contract CONNECTOR=PATH` for more connectors; `--anvil-cmd`, else
`$WORLDLOOM_ANVIL`, else `anvil` on `PATH`) starts one `anvil simulate serve`
per connector per case, with the provider holding that case's compiled row and
records in an evaluation service run, so node attribution and the case's
designed failures apply as they do in process. The agent under test finds
`ANVIL_BASE_URL`, `ANVIL_<CONNECTOR>_BASE_URL` and `ANVIL_TOKEN` in its
environment (the exec seam, `.claude/skills/worldloom-evalrun/references/protocol.md`)
and calls the vendor API. When it answers, the servers stop and each trace is
replayed, in the order the providers answered, through the same mapping into
the case's in-process run: the spans, refusals and state diff the grader and
the stages read are exactly what the in-process run would have recorded for
those calls. A call Anvil answered itself is a refusal. A replay that answers
differently from what the agent was served is noted on the result as
`anvil_divergence`. The run's `agent_identity.serving` names the contracts by
digest, so an Anvil run is never merged or compared with an in-process one
unawares. The default stays the in-process emulator.

From Python, `EvalSession.run(agent, anvil=AnvilServing({"jira": "./jira"}))`
does the same; the agent's surface carries `base_urls`, `token` and
`environment`.

`tests/test_anvil_provider.py` compiles the trimmed Jira contract, replays
one sequence (JQL search over two pages, get, projected get, create, update,
transition by the vendor's transition id, comment, and three domain errors)
through the emulator under the `native` engine and through Anvil and the
provider, and asserts identical returned records, identical errors and an
identical state diff; it also grades one case both ways and requires the same
spans and the same score. It is skipped when neither `node` with an Anvil
checkout nor `$WORLDLOOM_ANVIL` is available.

Limits: a status name in JQL (`status = "In Progress"`) is compared with the
stored workflow state (`open`), not its display name; an Anvil server serves
one contract, so a case across several connectors runs several servers, and a
node-scoped designed failure that depends on another connector's calls may be
attributed differently by the provider than by the replay (noted as
`anvil_divergence`, graded from the replay).

## Real vendor contracts

A connector served through Anvil is only as realistic as the contract Anvil
compiles. Worldloom locks one per connector in
`worldloom/_data/connectors/_contracts.json` (`worldloom.contract-lock/v1`):
the URL the vendor publishes it at (or, for an authored contract, its path in
the package), its format (`openapi3`, `swagger2`, `discovery`), the sha256
and size of the exact bytes, the version and the date it was locked, its
provenance, the Worldloom exposure profile Anvil compiles it under
(`_data/connectors/anvil/profiles/<connector>.yaml`: the operations the
connector's tools model plus the neighbours an agent is likely to reach for
by mistake), the manifest when the contract needs one (Jira and Confluence
declare two auth alternatives, which blocks every operation until one is
chosen), the vendor's operation count and the profile's, and Anvil's
snapshot hash for the locked bytes.

```sh
worldloom contracts fetch                 # download every locked source, verify its sha256
worldloom contracts build jira            # compile + approve under the profile; prints the bundle
worldloom evalrun run ./cases -o ./runs/anvil --exec "<command>" \
  --connectors anvil --contract jira=<bundle>
worldloom contracts coverage              # what each connector exposes and models
```

`fetch` writes into a cache (`--cache`, else `$WORLDLOOM_CONTRACTS_CACHE`,
else `~/.cache/worldloom/contracts`) and refuses bytes that hash to anything
but the lock, naming both digests: a vendor that republished its spec is a
review, never a silent upgrade. Google's Discovery service serves the Drive
document with its keys in a different order on every request, so the Drive
lock says `"canonical": "json"`: its digest is of the key-sorted, compact
JSON, and the cache keeps that form, so Anvil's snapshot of it is stable too. `build` compiles with `anvil compile
--profile --manifest --service`, approves with `anvil approve --profile
--reviewer worldloom-contracts`, checks Anvil read the locked bytes as the
locked snapshot, lints the connector's mapping against what the bundle
exposes, and writes a `build.json` receipt beside the bundle. The build is
cached under a key of the source digest, the profile, the manifest, the
mapping and the Anvil version. `--spec` compiles another source under the
same profile (the receipt says it is not the locked bytes).

Full specs are never committed; the Microsoft Graph one is 44MB. The tests
compile small gzipped trims in `tests/fixtures/anvil/contracts/`, cut with
`worldloom contracts trim CONNECTOR -o OUT`: the operations the built bundle
exposes and every schema they reach, compiled again under the same profile
and refused unless it exposes exactly the same operations. A YAML source is
read with PyYAML (a minute for Graph); converting it to JSON first is faster.

| Connector | Provenance | Source | Vendor operations | Profiled | Modelled | Unmodelled |
|---|---|---|---:|---:|---:|---:|
| jira | vendor | Jira Cloud platform REST API v3 (OpenAPI 3) | 619 | 26 | 9 | 17 |
| confluence | vendor | Confluence Cloud REST API v2 (OpenAPI 3) | 218 | 28 | 13 | 15 |
| slack | vendor | Slack Web API (Swagger 2.0) | 174 | 30 | 14 | 16 |
| drive | vendor | Google Drive API v3 (Discovery) | 64 | 18 | 5 | 13 |
| outlook | vendor | Microsoft Graph v1.0 (OpenAPI 3) | 17,870 | 26 | 17 | 9 |
| onedrive | vendor | Microsoft Graph v1.0 | 17,870 | 20 | 8 | 12 |
| sharepoint | vendor | Microsoft Graph v1.0 | 17,870 | 36 | 12 | 24 |
| teams | vendor | Microsoft Graph v1.0 | 17,870 | 41 | 26 | 15 |
| servicenow | authored | Table, Aggregate and Attachment APIs | 10 | 10 | 5 | 5 |
| salesforce | authored | REST API v61.0: query, search, describe, sObjects, limits | 11 | 11 | 5 | 6 |

ServiceNow and Salesforce publish no full OpenAPI document for these APIs, so
their contracts are authored from the vendors' REST references and committed
in the pack (`_data/connectors/anvil/contracts/`) with provenance `authored`
and the documentation URLs they were written from: ServiceNow's Table API
(`GET`, `POST`, `PATCH`, `PUT`, `DELETE /api/now/table/{tableName}[/{sys_id}]`
with `sysparm_query`, `sysparm_limit`, `sysparm_offset`, `sysparm_fields`,
`sysparm_display_value`, the `{"result": ...}` envelope and ServiceNow's
error body), and Salesforce's SOQL query with `nextRecordsUrl` continuation,
queryAll, SOSL search, the describes, sObject rows and limits. `email`,
`rovo`, `teamwork_graph` and `sor` have no vendor contract to lock (a
provider-neutral mailbox, no published Rovo REST contract, an early-access
GraphQL API, the generic system of record); the lock says so and coverage
reports them as `none`.

Anvil ships its own reviewed profiles for Jira, Confluence v2, Slack, Drive
and Graph (`examples/profiles/<vendor>/` in the Anvil repository), pinned to
the same bytes; each lock entry names its counterpart (`anvil_profile`) and
`tests/test_contracts.py` holds the two pins equal. Anvil's profiles are the
wider surface an agent needs around those APIs; Worldloom's are what its
connectors model plus the neighbours worth refusing, so every exposed
operation has a mapping entry. Confluence v2 has no CQL search (that is the
v1 `/wiki/rest/api/search`), so a v2 listing's filters are answered as the
CQL they mean; a create whose contract declares 200 (Confluence, Drive, some
Graph actions) answers 200.

Unmodelled operations are exposed on purpose: an agent that deletes a Jira
issue instead of transitioning it, or soft-deletes a Teams message, meets the
vendor's route and a refusal (`unsupported_operation`) rather than a 404 for
a path that does not exist. Each carries its reason in the mapping.

`tests/test_contract_parity.py` compiles each committed trim through
`contracts.build`, serves it with the provider, and runs one call sequence
per connector over HTTP and against an in-process emulator over the same
records: searches with the vendor's own query language, pages, reads,
projections, writes, domain errors in the vendor's body, and the state diff
must agree. Where a paging behaviour is still landing in Anvil, only that
assertion is recorded, and the test xfails naming the capability after
every other assertion held. `tests/test_contracts.py` holds the lock, the
trims and the mappings to each other without Node.
