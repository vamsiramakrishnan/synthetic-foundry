# MCP execution and scoring

Translate each expected DAG node to the connector's MCP tool at runtime. Keep that translation in the runner adapter: the corpus stores semantic connector, operation, and entity names so it remains server-neutral.

Record a `TraceCall` after each call with connector, operation, entity, dependencies, stable record ID, supporting fact IDs, and success. `score_trace` checks required calls, dependency order, post-write verification, provenance, and duplicate side effects.

Expected failures are fixture preconditions. Permission denial must deny the requesting principal; version conflict must expose a newer ETag/version; partial write must identify which branch succeeded; stale source must coexist with an authoritative current copy.
