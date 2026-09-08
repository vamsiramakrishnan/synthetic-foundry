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
5. `eval_grade(run_id)` to grade actual calls and post-state; or
   `eval_end(run_id)` to grade and release the run.

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
five evaluation tools. Select a smaller workload when its connector estate
exceeds that ceiling.

Defaults permit 32 live runs, four per principal, 512 attempted connector calls
per run, 64 KiB request bodies, 1 MiB connector responses and 100,000 initial
records. Trace pages also obey a byte budget: one bounded result plus its
bounded request and 16 KiB of framing room. `--max-runs` and `--max-calls` configure the common limits;
`ServingLimits` configures all of them. Oversized connector responses roll back
that call, including writes. The trace records the failed attempt. The SDK's
synchronous tools serialize changes under a lock; this is an evaluation
service, not a high-throughput connector proxy.

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
