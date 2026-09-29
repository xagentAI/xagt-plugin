#!/usr/bin/env node
/**
 * Independent verifier. Talks to a running service over HTTP and does not
 * import anything from src/, so it cannot pass by sharing a bug with the code
 * it is checking.
 *
 *   node verify.mjs https://agent3-handshake-production.up.railway.app <40-char commit>
 *
 * Exit codes: 0 all assertions held, 1 an assertion failed,
 * 2 the premise did not hold (the registry was unreachable, so this run
 * cannot judge the service — which is not the same as the service failing).
 */

const base = (process.argv[2] ?? "http://127.0.0.1:8080").replace(/\/+$/, "");
const expectedCommit = process.argv[3] ?? null;

let passed = 0;
const failures = [];
function check(label, condition, detail = "") {
  if (condition) passed += 1;
  else failures.push(`${label}${detail ? ` — ${detail}` : ""}`);
}
function equal(label, actual, expected) {
  check(label, Object.is(actual, expected), `expected ${JSON.stringify(expected)}, got ${JSON.stringify(actual)}`);
}

/**
 * Written out here rather than imported, so this file stays independent of the
 * code it is checking. If the service and this list ever disagree, that is a
 * finding, not something to paper over by sharing one definition.
 */
const LAPSED_DOMAINS = ["agent3.space", "agent3.me"];
function onLapsedDomain(url) {
  let host;
  try {
    host = new URL(url).hostname.toLowerCase();
  } catch {
    return false;
  }
  return LAPSED_DOMAINS.some((domain) => host === domain || host.endsWith(`.${domain}`));
}

async function getJson(path) {
  const response = await fetch(`${base}${path}`, {
    headers: { accept: "application/json" },
    signal: AbortSignal.timeout(30_000),
  });
  return { status: response.status, body: await response.json() };
}

async function rpc(method, params) {
  const response = await fetch(`${base}/mcp`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
    signal: AbortSignal.timeout(30_000),
  });
  return response.json();
}

// ── 1. The three gates, on one origin ───────────────────────────────────────
const health = await getJson("/health");
equal("health returns 200", health.status, 200);
equal("health reports ok", health.body.status, "ok");
check("health commit is a 40-character sha", /^[a-f0-9]{40}$/i.test(health.body.commit ?? ""), health.body.commit);
if (expectedCommit) equal("health reports the expected commit", health.body.commit, expectedCommit);

const proof = await getJson("/.well-known/xagent-verification.json");
equal("deployment proof returns 200", proof.status, 200);
equal("proof declares schemaVersion 1", proof.body.schemaVersion, 1);
equal("proof slug matches the service", proof.body.slug, "agent3-handshake");
equal("proof commit matches health", proof.body.commit, health.body.commit);
check("proof api base shares the origin", String(proof.body.apiBaseUrl ?? "").startsWith(base));

// ── 2. The premise: is upstream readable at all? ─────────────────────────────
// Without this, every assertion below would be judging an empty corpus and
// would pass for the wrong reason.
const snapshot = await getJson("/v1/snapshot");
if (snapshot.status !== 200 || typeof snapshot.body.entryCount !== "number") {
  process.stdout.write("PREMISE NOT MET: the registry could not be read, so this run cannot judge the service\n");
  process.stdout.write(`${JSON.stringify(snapshot.body).slice(0, 300)}\n`);
  process.exit(2);
}
const entryCount = snapshot.body.entryCount;
check("the registry holds at least one entry", entryCount > 0, `entryCount=${entryCount}`);
check("the snapshot digest is a sha256", /^[a-f0-9]{64}$/.test(snapshot.body.digest ?? ""));
equal("entry ids are listed for every entry", snapshot.body.entryIds?.length, entryCount);

// ── 3. The audit covers the whole registry ──────────────────────────────────
const audit = await getJson("/v1/audit");
equal("audit returns 200", audit.status, 200);
equal("audit covers every entry", audit.body.entries?.length, entryCount);
equal("audit totals add up", audit.body.totals.callable + audit.body.totals.blocked, entryCount);
check("the audit exercises the blocked path on real data", audit.body.totals.blocked > 0);
check("the audit exercises the callable path on real data", audit.body.totals.callable > 0);
for (const row of audit.body.entries ?? []) {
  check(`${row.name}: callable agrees with its blocker list`, row.callable === (row.blockers.length === 0));
  for (const defect of row.blockers) {
    check(`${row.name}: blocker "${defect.code}" names a field`, typeof defect.field === "string" && defect.field.length > 0);
    check(`${row.name}: blocker "${defect.code}" explains itself`, typeof defect.detail === "string" && defect.detail.length > 10);
  }
}

// ── 4. Payment: each single-key reader misses part of the registry ──────────
const payments = await getJson("/v1/payments");
equal("payments covers every entry", payments.body.entries?.length, entryCount);
const summary = payments.body.summary;
equal(
  "every entry is accounted for under one of the three states",
  summary.statedUnderMode + summary.statedUnderModel + summary.statedNowhere,
  entryCount,
);
check("some entries use each spelling, so the split is real", summary.statedUnderMode > 0 && summary.statedUnderModel > 0);
equal("a mode-only reader misses exactly the model-stated entries", summary.missedByAModeOnlyReader, summary.statedUnderModel);
equal("a model-only reader misses exactly the mode-stated entries", summary.missedByAModelOnlyReader, summary.statedUnderMode);

// ── 5. call_plan: a built spec is actually built, a refusal actually refuses ──
let builtAny = false;
let refusedAny = false;
for (const row of audit.body.entries ?? []) {
  const described = await getJson(`/v1/entry?entry=${encodeURIComponent(row.resourceId)}`);
  equal(`${row.name}: describe returns 200`, described.status, 200);
  const operations = described.body.operations ?? [];
  if (operations.length === 0) continue;
  const first = operations[0].operationId;
  const planned = await getJson(
    `/v1/plan?entry=${encodeURIComponent(row.resourceId)}&operation=${encodeURIComponent(first)}`,
  );
  if (planned.status === 200) {
    builtAny = true;
    const spec = planned.body;
    check(`${row.name}: planned url is absolute`, /^https:\/\//.test(spec.url ?? ""), spec.url);
    check(`${row.name}: planned url carries no placeholder`, !/<|\{\{|undefined|null/.test(spec.url ?? ""));
    check(`${row.name}: planned method is a real verb`, ["GET", "POST", "PUT", "PATCH", "DELETE"].includes(spec.method));
    check(`${row.name}: a built spec has no blockers attached`, spec.blockers === undefined);

    // A returned spec is a claim that this request can be sent and, if it
    // costs money, paid for. These two assertions check that claim against the
    // spec itself rather than trusting the service's own defect list — without
    // them, downgrading a blocker to a warning would hand back an unsendable
    // request and every other assertion here would still pass.
    check(
      `${row.name}: planned url does not target a lapsed domain`,
      !onLapsedDomain(spec.url ?? ""),
      spec.url,
    );
    if (spec.payment?.kind === "priced") {
      check(
        `${row.name}: a priced spec names a settlement gateway`,
        typeof spec.payment.gateway === "string" && spec.payment.gateway.length > 0,
      );
      check(
        `${row.name}: a priced spec does not settle through a lapsed domain`,
        !onLapsedDomain(spec.payment.gateway ?? ""),
        spec.payment.gateway,
      );
    }
  } else {
    refusedAny = true;
    equal(`${row.name}: a refusal is a 404`, planned.status, 404);
    check(`${row.name}: the refusal names at least one blocker`, (planned.body.detail?.blockers ?? []).length > 0);
  }
}
check("at least one entry produced a spec", builtAny);
check("at least one entry produced a refusal", refusedAny);

// A refusal must never hand back a sendable request.
const unknown = await getJson("/v1/plan?entry=__no_such_entry__&operation=__none__");
equal("an unknown entry is a 404", unknown.status, 404);
equal("an unknown entry is reported as not found", unknown.body.code, "entry_not_found");
check("the not-found response lists what does exist", (unknown.body.detail?.available ?? []).length === entryCount);

// ── 6. The MCP door answers the same as the REST door ───────────────────────
const listed = await rpc("tools/list", {});
const toolNames = (listed.result?.tools ?? []).map((tool) => tool.name);
equal("mcp lists five tools", toolNames.length, 5);
const indexed = await getJson("/v1");
equal("the mcp tool set matches the advertised set", toolNames.join(","), (indexed.body.tools ?? []).map((t) => t.name).join(","));

const viaMcp = await rpc("tools/call", { name: "payment_readings", arguments: {} });
equal("a successful tool call is not an error", viaMcp.result?.isError, false);
const mcpBody = JSON.parse(viaMcp.result.content[0].text);
equal("mcp and rest agree on the payment summary", JSON.stringify(mcpBody.summary), JSON.stringify(summary));

const unknownTool = await rpc("tools/call", { name: "__nope__", arguments: {} });
equal("an unknown tool is a protocol error", unknownTool.error?.code, -32602);
const unknownMethod = await rpc("__nope__", {});
equal("an unknown method is a protocol error", unknownMethod.error?.code, -32601);
check("protocol errors carry no result", unknownMethod.result === undefined);

const declined = await rpc("tools/call", { name: "call_plan", arguments: { entry: "__no_such_entry__", operation: "x" } });
equal("a tool that ran and declined reports through isError", declined.result?.isError, true);
check("a declined tool call is not a protocol error", declined.error === undefined);

// ── report ───────────────────────────────────────────────────────────────────
process.stdout.write(`\n${base}\n${passed} passed, ${failures.length} failed\n`);
for (const failure of failures) process.stdout.write(`  FAIL  ${failure}\n`);
process.exit(failures.length === 0 ? 0 : 1);
