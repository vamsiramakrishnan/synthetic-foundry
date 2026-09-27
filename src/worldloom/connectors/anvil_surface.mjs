// Anvil's MCP projection of one compiled bundle, one tool at a time, with the wire bindings.
//
//   node anvil_surface.mjs <bundle-dir> <anvil-cli-entry>
//
// Worldloom runs this (`worldloom contracts surface`) with the Anvil install
// that compiled the bundle. It builds the bundle's MCP server with Anvil's own
// `buildMcpServer` (flat disclosure: every approved operation, no lane cards)
// and converts each registered tool's input schema with the MCP SDK's own
// converter, exactly as the server's `tools/list` handler does. The conversion
// runs per tool rather than once for the whole list, so a tool whose schema the
// converter refuses is reported by name (in `failed`) and given the schema
// Anvil assembles before conversion, instead of failing every tool with it.
//
// Beside each tool it writes how Anvil carries a call to the wire, read with
// Anvil's own functions: each argument's wire name and location, the body's
// projection, whether the simulator pages the operation and at what size, the
// page envelope, the declared success statuses and errors, and the safety keys.
// Prints one JSON document on stdout.
import { existsSync, readFileSync, realpathSync } from "node:fs";
import { dirname, join } from "node:path";
import { pathToFileURL } from "node:url";

const [bundle, cliEntry] = process.argv.slice(2);
if (!bundle || !cliEntry) {
  process.stderr.write("usage: node anvil_surface.mjs <bundle-dir> <anvil-cli-entry>\n");
  process.exit(2);
}

// Anvil's packages are resolved from the CLI that compiled the bundle, so the
// projection is that install's and no other. They are ESM-only, so each is
// found by walking up to its node_modules and reading its exports.
function packageEntry(name, from) {
  let directory = dirname(realpathSync(from));
  for (;;) {
    const root = join(directory, "node_modules", name);
    if (existsSync(join(root, "package.json"))) {
      const manifest = JSON.parse(readFileSync(join(root, "package.json"), "utf8"));
      let main = manifest.exports?.["."] ?? manifest.main ?? "index.js";
      while (typeof main === "object" && main !== null) main = main.import ?? main.default;
      return { root: realpathSync(root), entry: join(realpathSync(root), main) };
    }
    const parent = dirname(directory);
    if (parent === directory) throw new Error(`cannot find ${name} from ${from}`);
    directory = parent;
  }
}
const importFile = (path) => import(pathToFileURL(path).href);
const runtime = packageEntry("@anvil/mcp-runtime", cliEntry);
const mcp = await importFile(runtime.entry);
const airLib = await importFile(packageEntry("@anvil/air", runtime.entry).entry);
const simulator = await importFile(packageEntry("@anvil/simulator", cliEntry).entry);
const sdk = packageEntry("@modelcontextprotocol/sdk", runtime.entry);
const compat = await importFile(join(sdk.root, "dist", "esm", "server", "zod-json-schema-compat.js"));
const zodCompat = await importFile(join(sdk.root, "dist", "esm", "server", "zod-compat.js"));
const { z } = await importFile(packageEntry("zod", runtime.entry).entry);

const air = airLib.loadAirDocument(JSON.parse(readFileSync(join(bundle, "air.json"), "utf8")));
const server = mcp.buildMcpServer(air, { resources: [], disclosure: "flat", contextFor: () => ({}) });
const convert = (shape, strategy) =>
  compat.toJsonSchemaCompat(zodCompat.normalizeObjectSchema(shape), {
    strictUnions: true,
    pipeStrategy: strategy,
  });

function firstArrayField(schema) {
  for (const [name, prop] of Object.entries(propertiesOf(schema))) {
    if (prop && (prop.type === "array" || typeof prop.items === "object")) return name;
  }
  return undefined;
}

// The declared response, cut to what the simulator's envelope writer reads:
// types, fixed values (a `const`, a one-member `enum`, a scalar `default`) and
// `required`, three levels deep, with `allOf` members' properties merged in.
function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function propertiesOf(schema) {
  const props = {};
  if (!isRecord(schema)) return props;
  for (const part of [schema, ...(Array.isArray(schema.allOf) ? schema.allOf : [])]) {
    if (isRecord(part) && isRecord(part.properties)) Object.assign(props, part.properties);
  }
  return props;
}
function shape(schema, depth) {
  if (!isRecord(schema)) return undefined;
  const out = {};
  if (schema.type !== undefined) out.type = schema.type;
  if (schema.const !== undefined) out.const = schema.const;
  if (Array.isArray(schema.enum) && schema.enum.length === 1) out.enum = schema.enum;
  const dflt = schema.default;
  if (typeof dflt === "string" || typeof dflt === "number" || typeof dflt === "boolean") out.default = dflt;
  if (Array.isArray(schema.required)) out.required = schema.required;
  if (isRecord(schema.items)) out.items = {};
  const props = propertiesOf(schema);
  if (depth > 0 && Object.keys(props).length > 0) {
    out.properties = {};
    for (const [name, prop] of Object.entries(props)) out.properties[name] = shape(prop, depth - 1) ?? {};
  }
  return out;
}

function binding(op) {
  const declared = simulator.declaredResponse(air, op);
  const page = airLib.safePageSize(op, airLib.DEFAULT_RESPONSE_BUDGET_TOKENS);
  const body = op.input.body;
  return {
    operation: op.id,
    canonical: op.canonicalName,
    method: op.sourceRef.method?.toUpperCase() ?? null,
    path: op.sourceRef.path ?? null,
    kind: simulator.operationKind(op),
    effect: op.effect,
    params: op.input.params.map((p) => ({
      key: airLib.agentPropKey(p),
      name: p.name,
      in: p.in,
      required: Boolean(p.required),
    })),
    body: body
      ? {
          projection: body.projection,
          required: Boolean(body.required),
          fields:
            body.projection === "fields"
              ? body.fields.map((f) => ({
                  key: airLib.agentPropKey(f),
                  name: f.name,
                  required: Boolean(f.required),
                }))
              : [],
        }
      : null,
    paged: simulator.servesItems(op),
    pagination: op.pagination ?? null,
    odata: airLib.isODataPaging(op.pagination),
    pageSize: { size: page.size ?? null, basis: page.basis },
    envelope: {
      bare: declared?.type === "array",
      itemsField: op.pagination?.itemsField ?? firstArrayField(declared) ?? "items",
    },
    response: shape(declared, 3) ?? null,
    successStatuses:
      airLib.wireProtocolFor(op.sourceRef) === "http_json" ? (op.output.successStatuses ?? []) : [],
    errors: op.errors,
    confirmation: op.confirmation,
    idempotency: op.idempotency,
    retries: { mode: op.retries.mode },
    safetyKeys: airLib.operationSafetyInputKeys(op),
  };
}

const operations = new Map(air.operations.map((op) => [op.mcp.toolName, op]));
const tools = [];
const bindings = {};
const failed = {};
for (const [name, tool] of Object.entries(server._registeredTools)) {
  if (!tool.enabled) continue;
  const definition = {
    name,
    title: tool.title,
    description: tool.description,
    annotations: tool.annotations,
    execution: tool.execution,
    _meta: tool._meta,
  };
  const op = operations.get(name);
  try {
    definition.inputSchema = convert(tool.inputSchema, "input");
    if (tool.outputSchema) definition.outputSchema = convert(tool.outputSchema, "output");
  } catch (error) {
    failed[name] = error instanceof Error ? error.message : String(error);
    if (!op) continue;
    // The schema Anvil assembles before conversion, with the reserved
    // controls converted as they are for every other tool.
    const assembled = airLib.operationInputSchema(op);
    const reserved = convert(
      z.object({ ...mcp.reservedSafetyShape(op), ...mcp.projectionShape() }),
      "input",
    );
    definition.inputSchema = {
      $schema: reserved.$schema,
      type: "object",
      properties: { ...assembled.properties, ...reserved.properties },
      required: assembled.required,
      additionalProperties: false,
    };
    delete definition.outputSchema;
  }
  tools.push(JSON.parse(JSON.stringify(definition)));
  if (op) bindings[name] = JSON.parse(JSON.stringify(binding(op)));
}
process.stdout.write(
  `${JSON.stringify({
    service: air.service.id,
    serverUrl: air.service.servers?.[0]?.url ?? null,
    tools,
    bindings,
    failed,
  })}\n`,
);
