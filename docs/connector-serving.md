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

## Native vendor queries (opt-in)

By default a search tool's `query` string is read as the historical
conjunctive subset (`field = value AND ...`) and compiled to a Worldloom
predicate. Set the policy `connectors.query.engine` to `native` (or construct
`ConnectorEmulator(..., query_engine="native")`) and the same argument runs as
the vendor's own query language through `worldloom.connectors.query`. The
default is `predicate`, and under it every emulator answer is byte-identical
to what it was before the evaluator existed.

A policy pack that opts a run in:

```json
{"schema": "worldloom.pack/v1", "kind": "policy", "name": "native",
 "body": {"values": {"connectors.query.engine": "native"}}}
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
