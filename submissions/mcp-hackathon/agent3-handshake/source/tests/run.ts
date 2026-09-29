/**
 * Assertions run against the pinned snapshot, so they describe a registry state
 * a reviewer can diff rather than whatever upstream says today.
 *
 * Two rules this file follows throughout:
 *   - every assertion over a list first pins the list's size, so a lookup that
 *     silently matches nothing cannot pass as "no problems found";
 *   - the negative cases are constructed, not hoped for, so a check that only
 *     ever sees well-formed input cannot pass by never being exercised.
 */

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { buildCallSpec } from "../src/callspec.js";
import { inspect, normalizePayment, pointsAtRetiredHost } from "../src/normalize.js";
import type { RawResource } from "../src/registry.js";
import { digestOf, unwrapList } from "../src/registry.js";
import { TOOLS, inputSchema, toolByName } from "../src/tools.js";

const here = dirname(fileURLToPath(import.meta.url));
const snapshot = JSON.parse(readFileSync(join(here, "..", "snapshots", "registry.json"), "utf8")) as {
  resources: RawResource[];
  digest: string;
};
const RESOURCES = snapshot.resources;

let passed = 0;
const failures: string[] = [];

function check(label: string, condition: boolean, detail = "") {
  if (condition) {
    passed += 1;
    return;
  }
  failures.push(`${label}${detail ? ` — ${detail}` : ""}`);
}

function equal(label: string, actual: unknown, expected: unknown) {
  check(label, Object.is(actual, expected), `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

// ── 0. The fixture itself ────────────────────────────────────────────────────
// Everything below reads this list. If it were empty, most assertions would be
// vacuously true and the suite would report green on an empty corpus.
check("fixture is not empty", RESOURCES.length > 0, `length=${RESOURCES.length}`);
check("fixture holds more than one entry", RESOURCES.length >= 5, `length=${RESOURCES.length}`);
equal("digest recomputes from the fixture", digestOf(RESOURCES), snapshot.digest);

// ── 1. The payment field's two spellings ────────────────────────────────────
equal("mode spelling is read", normalizePayment({ mode: "free", supportsX402: false }).statedVia, "mode");
equal("model spelling is read", normalizePayment({ model: "free", amount: 0 }).statedVia, "model");
equal("absent spelling is reported, not defaulted", normalizePayment({}).statedVia, "none");
equal("absent spelling does not become free", normalizePayment({}).kind, "not_stated");
equal("a stated price is priced", normalizePayment({ mode: "usage-based", amount: 0.01 }).kind, "priced");
equal("a stated price of zero is free", normalizePayment({ mode: "usage-based", amount: 0 }).kind, "free");
equal(
  "mode wins when both spellings are present",
  normalizePayment({ mode: "usage-based", model: "free" }).statedVia,
  "mode",
);

// The point of the tool: each single-key reader misses part of the registry.
const viaMode = RESOURCES.filter((r) => typeof r.payment?.mode === "string");
const viaModel = RESOURCES.filter((r) => typeof r.payment?.model === "string");
check("some entries state payment under mode", viaMode.length > 0, `count=${viaMode.length}`);
check("some entries state payment under model", viaModel.length > 0, `count=${viaModel.length}`);
check(
  "the two spellings do not overlap, so neither reader alone sees the whole registry",
  viaMode.every((r) => typeof r.payment?.model !== "string"),
);

// ── 2. Retired hosts ─────────────────────────────────────────────────────────
equal("a retired apex is caught", pointsAtRetiredHost("https://agent3.space/x"), "agent3.space");
equal("a retired subdomain is caught", pointsAtRetiredHost("https://hub.agent3.space/api"), "agent3.space");
equal("the other retired domain is caught", pointsAtRetiredHost("https://hub.agent3.me"), "agent3.me");
equal("a live host is not caught", pointsAtRetiredHost("https://agent3-x-api.vercel.app"), null);
equal("a lookalike host is not caught", pointsAtRetiredHost("https://agent3.space.example.com"), null);
equal("a non-url is not caught", pointsAtRetiredHost("/agent-cards/card.json"), null);

// ── 3. Defect detection, on constructed inputs ───────────────────────────────
// Each case is built to trip exactly one rule, so a rule that stopped working
// shows up as its own failure rather than being masked by a neighbour.
const good: RawResource = {
  resource_id: "fixture-good",
  name: "Fixture Good",
  interfaces: [{ url: "https://example.invalid/base", type: "api", protocol: "https" }],
  payment: { mode: "free", supportsX402: false },
  operations: [
    {
      id: "do-thing",
      name: "Do Thing",
      bindings: { http: { path: "/api/v1/thing", method: "POST", contentType: "application/json" } },
      inputSchema: { type: "object", required: ["query"], properties: { query: { type: "string" } } },
    },
  ],
};
equal("a well-formed entry has no blockers", inspect(good).filter((d) => d.severity === "blocker").length, 0);
equal("a well-formed entry has no warnings", inspect(good).filter((d) => d.severity === "warning").length, 0);

function codesFor(mutate: (draft: RawResource) => void): string[] {
  const draft = JSON.parse(JSON.stringify(good)) as RawResource;
  mutate(draft);
  return inspect(draft).map((d) => d.code);
}
check("relative interface url is a defect", codesFor((d) => { d.interfaces = [{ url: "/cards/x.json" }]; }).includes("relative_interface_url"));
check("missing interface is a defect", codesFor((d) => { d.interfaces = []; }).includes("no_interface"));
check("retired interface host is a defect", codesFor((d) => { d.interfaces = [{ url: "https://hub.agent3.space/api" }]; }).includes("interface_on_retired_host"));
check("absent payment kind is a defect", codesFor((d) => { d.payment = {}; }).includes("payment_kind_not_stated"));
check("legacy payment key is flagged", codesFor((d) => { d.payment = { model: "free", amount: 0 }; }).includes("payment_kind_under_legacy_key"));
check("a price with a retired gateway is a defect", codesFor((d) => { d.payment = { mode: "usage-based", amount: 0.01, currency: "USD", gateway: "https://hub.agent3.space/api/proxy/invoke" }; }).includes("gateway_on_retired_host"));
check("a price with no gateway is a defect", codesFor((d) => { d.payment = { mode: "usage-based", amount: 0.01, currency: "USD" }; }).includes("price_without_gateway"));
check("no operations is a defect", codesFor((d) => { d.operations = []; }).includes("no_operations"));
check("an operation with no binding is a defect", codesFor((d) => { d.operations = [{ id: "x" }]; }).includes("operation_without_binding"));
check("an operation with no path is a defect", codesFor((d) => { d.operations = [{ id: "x", bindings: { http: { method: "POST" } } }]; }).includes("binding_without_path"));
check("an operation with no input schema is flagged", codesFor((d) => { delete d.operations![0].inputSchema; }).includes("operation_without_input_schema"));

// ── 4. Call spec construction ────────────────────────────────────────────────
const built = buildCallSpec(good, "do-thing");
check("a well-formed entry yields a spec", built.ok);
if (built.ok) {
  equal("url is base joined to path", built.spec.url, "https://example.invalid/base/api/v1/thing");
  equal("method comes from the binding", built.spec.method, "POST");
  equal("content type is carried", built.spec.headers["content-type"], "application/json");
  equal("required fields come from the schema", built.spec.requiredFields.join(","), "query");
  check("a free entry asks for no payment header", built.spec.headers["x-payment"] === undefined);
}

const missing = buildCallSpec(good, "no-such-operation");
check("an unknown operation refuses", !missing.ok);
if (!missing.ok) {
  check("the refusal names the operation", missing.refusal.blockers.some((d) => d.code === "operation_not_found"));
  check("the refusal lists what does exist", missing.refusal.blockers[0]!.detail.includes("do-thing"));
}

const relative = JSON.parse(JSON.stringify(good)) as RawResource;
relative.interfaces = [{ url: "/cards/x.json" }];
const refused = buildCallSpec(relative, "do-thing");
check("a relative base refuses rather than guessing a host", !refused.ok);
if (!refused.ok) {
  check("refusal is non-empty", refused.refusal.blockers.length > 0);
  check("refusal names the field", refused.refusal.blockers.some((d) => d.field.startsWith("interfaces[")));
}

const priced = JSON.parse(JSON.stringify(good)) as RawResource;
priced.payment = { mode: "usage-based", amount: 0.01, currency: "USD", gateway: "https://gateway.example.invalid/pay" };
const pricedSpec = buildCallSpec(priced, "do-thing");
check("a payable priced entry yields a spec", pricedSpec.ok);
if (pricedSpec.ok) {
  check("a priced entry asks for a payment header", typeof pricedSpec.spec.headers["x-payment"] === "string");
  equal("the price is carried through", pricedSpec.spec.payment.amount, 0.01);
}

// ── 5. The live corpus, as pinned ────────────────────────────────────────────
const audited = RESOURCES.map((resource) => ({
  name: resource.name ?? "(unnamed)",
  blockers: inspect(resource).filter((d) => d.severity === "blocker"),
}));
equal("every fixture entry was audited", audited.length, RESOURCES.length);
check(
  "the audit finds at least one blocked entry, so the blocked path is exercised by real data",
  audited.some((row) => row.blockers.length > 0),
);
check(
  "the audit finds at least one callable entry, so the success path is exercised by real data",
  audited.some((row) => row.blockers.length === 0),
);

// ── 6. Tool declarations are the single source of truth ─────────────────────
equal("five tools are declared", TOOLS.length, 5);
check("tool names are unique", new Set(TOOLS.map((t) => t.name)).size === TOOLS.length);
for (const tool of TOOLS) {
  check(`${tool.name} declares errors`, tool.errors.length > 0);
  check(`${tool.name} has a rest path`, tool.restPath.startsWith("/v1/"));
  check(`${tool.name} is findable by name`, toolByName(tool.name) === tool);
  const schema = inputSchema(tool);
  equal(`${tool.name} schema lists every declared input`, Object.keys(schema.properties).length, Object.keys(tool.input).length);
  const declaredRequired = Object.entries(tool.input).filter(([, spec]) => spec.required).length;
  equal(`${tool.name} schema marks the right fields required`, schema.required.length, declaredRequired);
}
check("rest paths are unique", new Set(TOOLS.map((t) => t.restPath)).size === TOOLS.length);

// ── 7. The list unwrapper accepts both shapes the hub has shipped ───────────
equal("bare array under data", unwrapList({ data: [{ resource_id: "a" }] }).length, 1);
equal("nested array under data", unwrapList({ data: { resources: [{ resource_id: "a" }] } }).length, 1);
equal("a bare array", unwrapList([{ resource_id: "a" }]).length, 1);
let threw = false;
try { unwrapList({ data: { nothing: 1 } }); } catch { threw = true; }
check("an unrecognized shape throws rather than returning empty", threw);

// ── report ───────────────────────────────────────────────────────────────────
process.stdout.write(`\n${passed} passed, ${failures.length} failed\n`);
for (const failure of failures) process.stdout.write(`  FAIL  ${failure}\n`);
process.exit(failures.length === 0 ? 0 : 1);
