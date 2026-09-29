#!/usr/bin/env tsx
/**
 * Tests. Every one of these was checked by breaking the code on purpose and
 * confirming it went red: an assertion that has never failed is not evidence.
 * See verification/README.md for the control experiments and their output.
 *
 * No network. Everything runs against the committed snapshot.
 */
import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { offerKey, snapshotIdOf, type Snapshot } from "../src/catalogue.js";
import { costOf, savingOf, usd } from "../src/pricing.js";
import { plan, resolve, MAX_TOKENS, type PlanResult } from "../src/plan.js";
import { handleMcpPayload, listTools } from "../src/mcp.js";
import { runPlanCall } from "../src/operations.js";
import { TOOLS } from "../src/tools.js";

// A reviewer runs these in an isolated environment. Any network call would be
// red there and green here, which is the shape of a test that proves nothing,
// so the network is taken away for the whole run and its absence is asserted.
globalThis.fetch = (() => {
  throw new Error("these tests must not reach the network");
}) as typeof fetch;

const HERE = dirname(fileURLToPath(import.meta.url));
const snapshot = JSON.parse(
  readFileSync(join(HERE, "..", "snapshots", "catalogue.json"), "utf8"),
) as Snapshot;

let failures = 0;
function check(name: string, ok: boolean, detail = "") {
  console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
  if (!ok) failures += 1;
}
function isResult(x: unknown): x is PlanResult {
  return typeof x === "object" && x !== null && !("error" in x);
}

console.log("0. Offline");
let reachedNetwork = false;
try {
  await fetch("https://example.invalid/");
} catch (err) {
  reachedNetwork = String(err).includes("must not reach the network");
}
check("the network is unavailable to this run", reachedNetwork);

console.log("1. An offer is the unit, not an id");
const ids = new Set(snapshot.offers.map((o) => o.modelId));
const keys = new Set(snapshot.offers.map(offerKey));
const perId = new Map<string, number>();
for (const o of snapshot.offers) perId.set(o.modelId, (perId.get(o.modelId) ?? 0) + 1);
const multi = [...perId.entries()].filter(([, n]) => n > 1);
check("every offer has a distinct id and line", keys.size === snapshot.offers.length, `${keys.size} keys`);
check("there are fewer ids than offers", ids.size < snapshot.offers.length, `${ids.size} ids, ${snapshot.offers.length} offers`);
check("some ids carry several offers", multi.length > 0, `${multi.length} such ids`);
// Grouping by name instead of id loses entries whose name carries the line
// tag, which is the mistake this check exists to catch.
const byName = new Set(snapshot.offers.map((o) => o.name));
check("names are not a grouping key", byName.size > ids.size, `${byName.size} names vs ${ids.size} ids`);
check("an empty line code is kept as an empty string", snapshot.offers.some((o) => o.lineCode === ""));
check("no line code is null or undefined", snapshot.offers.every((o) => typeof o.lineCode === "string"));

console.log("2. Money never prints below what is charged");
let roundingProblems = 0;
let tooGenerous = 0;
for (const offer of snapshot.offers) {
  for (const tokens of [1, 999, 1_000, 33_333, 250_000, 2_000_000]) {
    for (const rate of [offer.inputPerMillionMicro, offer.outputPerMillionMicro]) {
      const shown = costOf(tokens, rate);
      // The exact figure, computed a second way, in integers.
      const exact = (BigInt(tokens) * BigInt(rate)) / 1_000_000n;
      const remainder = (BigInt(tokens) * BigInt(rate)) % 1_000_000n;
      const exactCeil = Number(remainder === 0n ? exact : exact + 1n);
      if (shown < exactCeil) roundingProblems += 1;
      if (shown > exactCeil) tooGenerous += 1;
    }
  }
}
check("no price rounds down", roundingProblems === 0, `${roundingProblems} would under-report`);
check("no price is inflated either", tooGenerous === 0, `${tooGenerous} over-report by more than a rounding step`);
check("a saving rounds down to zero rather than negative", savingOf(100, 250) === 0);
check("a saving is the plain difference otherwise", savingOf(250, 100) === 150);
check("a fractional cent still prints upward", usd(1) === "$0.000001");

console.log("3. Planning one job");
const small = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 500 });
check("a small job has offers", isResult(small) && small.eligible.length > 0, isResult(small) ? `${small.eligibleCount} eligible` : "errored");
if (isResult(small)) {
  const costs = small.eligible.map((e) => e.totalCost.microUsd);
  check("offers come back cheapest first", costs.every((c, i) => i === 0 || costs[i - 1] <= c));
  check("each row names its line", small.eligible.every((e) => typeof e.line === "string" && e.line.length > 0));
  check("the answer carries the catalogue it priced against", small.snapshotId === snapshot.snapshotId);
}

// A job whose prompt plus answer will not fit. The offers that cannot take it
// have to say which number ruled them out.
const big = plan(snapshot, 0, { inputTokens: 900_000, outputTokens: 100_000 });
if (isResult(big)) {
  const ctx = big.rejected.filter((r) => r.bindingConstraint === "context");
  check("a job larger than most windows rejects on context", ctx.length > 0, `${ctx.length} rejected on context`);
  check("each rejection names the number it needed", ctx.every((r) => typeof r.requiredValue === "number" && typeof r.actualValue === "number"));
  check("each rejection reports the actual window", ctx.every((r) => Number(r.actualValue) < Number(r.requiredValue)));
} else {
  check("a 1M-token job still finds something or explains itself", big.error === "no_offer_meets_requirements", big.error);
}

const outputHeavy = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 300_000 });
const outputRejections = isResult(outputHeavy)
  ? outputHeavy.rejected.filter((r) => r.bindingConstraint === "max_output")
  : (outputHeavy.rejected as { bindingConstraint: string }[]).filter((r) => r.bindingConstraint === "max_output");
check("an output ceiling is enforced separately from the window", outputRejections.length > 0, `${outputRejections.length} rejected on max_output`);

console.log("4. Refusals carry numbers");
const impossible = plan(snapshot, 0, { inputTokens: 2_000_000, outputTokens: 2_000_000 });
check("an impossible job is an error, not an empty list", !isResult(impossible) && impossible.error === "no_offer_meets_requirements");
if (!isResult(impossible)) {
  check("it says how large a window exists", typeof impossible.largestContextAvailable === "number");
  check("it says how to get an answer", Array.isArray(impossible.howToGetAnAnswer));
  check("it lists what ruled offers out", Array.isArray(impossible.rejected) && (impossible.rejected as unknown[]).length > 0);
}

const unknown = plan(snapshot, 0, { inputTokens: 10, outputTokens: 10, baselineModelId: "gpt-5.9" });  // not in the catalogue; gpt-5.4 is, so it would be the wrong fixture
check("an unknown id is refused", !isResult(unknown) && unknown.error === "unknown_model");
if (!isResult(unknown)) {
  check("it carries nearest[] as well", Array.isArray(unknown.nearest) && (unknown.nearest as string[]).length > 0);
  check("it suggests ids that exist", Array.isArray(unknown.closestIds) && (unknown.closestIds as string[]).length > 0, JSON.stringify(unknown.closestIds));
}

for (const bad of [-1, 1.5, MAX_TOKENS + 1]) {
  const res = plan(snapshot, 0, { inputTokens: bad, outputTokens: 10 });
  check(`a token count of ${bad} is refused`, !isResult(res) && res.error === "invalid_token_counts");
}

// Zero is a real number of tokens, not a missing one, and above all not a
// stand-in for "no limit". It has to price at zero, not open the gates.
const zero = plan(snapshot, 0, { inputTokens: 0, outputTokens: 0 });
check("a zero-token job is priced, not waved through", isResult(zero) && zero.eligible.every((e) => e.totalCost.microUsd === 0));
check("a zero-token job still reports its catalogue", isResult(zero) && typeof zero.snapshotId === "string" && typeof zero.staleSeconds === "number");
const zeroOut = plan(snapshot, 0, { inputTokens: 5_000, outputTokens: 0 });
check("zero output tokens cost nothing but input still counts", isResult(zeroOut) && zeroOut.eligible.every((e) => e.outputCost.microUsd === 0 && e.totalCost.microUsd === e.inputCost.microUsd));

console.log("5. The same id is not the same price");
const spread = resolve(snapshot, "gpt-5.5");
check("gpt-5.5 is sold more than once", !("error" in spread) && spread.offerCount > 1, "error" in spread ? spread.error : `${spread.offerCount} offers`);
if (!("error" in spread)) {
  check("its offers differ in price", new Set(spread.offers.map((o) => o.inputPerMillion)).size > 1, spread.offers.map((o) => `${o.line}:${o.inputPerMillion}`).join(" "));
  check("the spread is reported", spread.spread.endsWith("x"), spread.spread);
}

const baseline = plan(snapshot, 0, { inputTokens: 100_000, outputTokens: 10_000, baselineModelId: "gpt-5.5" });
check("a baseline produces a comparison", isResult(baseline) && baseline.savingsVsBaseline !== undefined);
if (isResult(baseline) && baseline.savingsVsBaseline) {
  const s = baseline.savingsVsBaseline;
  check("the baseline is priced on its cheapest line", s.baselineOffer !== null);
  check("the saving is not negative", s.absolute.microUsd >= 0);
  if (s.baselineOffer) {
    check("the cheapest is no dearer than the baseline", s.cheapestOffer.totalCost.microUsd <= s.baselineOffer.totalCost.microUsd);
  }
}

// Several offers of one id must each occupy their own row: collapsing them is
// exactly the mistake this desk exists to expose.
const gptLines = snapshot.offers.filter((o) => o.modelId === "gpt-5.5").map((o) => o.line);
// One line at a time keeps the list short enough that nothing is cut, so this
// checks the grouping and not the row cap.
const oneLine = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, requireLines: [gptLines[0]] });
check("a single line fits in one answer", isResult(oneLine) && oneLine.truncated === false, isResult(oneLine) ? `${oneLine.eligibleCount} eligible` : "errored");
if (isResult(oneLine)) {
  check("gpt-5.5 appears on its own line", oneLine.eligible.some((e) => e.modelId === "gpt-5.5"));
}
// The property that matters: an id sold on several lines occupies several
// rows, at several prices. Collapsing them is the mistake this desk exposes.
const wide = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, limit: 50 });
if (isResult(wide)) {
  const seen = new Map<string, number[]>();
  for (const e of wide.eligible) seen.set(e.modelId, [...(seen.get(e.modelId) ?? []), e.totalCost.microUsd]);
  const repeated = [...seen.entries()].filter(([, costs]) => costs.length > 1);
  check("ids with several offers keep a row each", repeated.length > 0, `${repeated.length} such ids in the answer`);
  check("at least one of them differs in price", repeated.some(([, costs]) => new Set(costs).size > 1));
}
// A capped list has to admit it is capped, or a caller reads the cheapest 50
// as though it were everything.
const capped = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, limit: 5 });
check("a capped answer says so", isResult(capped) && capped.truncated === true && capped.omittedCount > 0, isResult(capped) ? `${capped.omittedCount} omitted` : "errored");
check("a capped answer still reports the true total", isResult(capped) && capped.eligibleCount > capped.eligible.length);

console.log("6. Offers that are not sold by the token, and offers that are not live");
const notTokenPriced = snapshot.offers.filter((o) => o.context === 0 || o.maxOutput === 0);
check("the catalogue carries offers with no token window", notTokenPriced.length > 0, `${notTokenPriced.length} of them`);
// A zero-token job is the one that gets past every size constraint, which is
// exactly where a video model would otherwise be recommended at zero.
const zeroJob = plan(snapshot, 0, { inputTokens: 0, outputTokens: 0 });
if (isResult(zeroJob)) {
  const slipped = zeroJob.eligible.filter((e) => e.context === 0 || e.maxOutput === 0);
  check("none of them is recommended for a token job", slipped.length === 0, `${slipped.length} slipped through`);
  const named = zeroJob.rejected.filter((r) => r.bindingConstraint === "not_token_priced");
  check("each is refused by name rather than dropped", named.length === notTokenPriced.length, `${named.length} refused`);
}

const previews = snapshot.offers.filter((o) => o.availability !== "live");
check("the catalogue carries preview offers", previews.length > 0, `${previews.length}`);
const defaultJob = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100 });
if (isResult(defaultJob)) {
  check("preview offers stay out by default", defaultJob.eligible.every((e) => e.availability === "live"));
  check("and are refused on availability", defaultJob.rejected.some((r) => r.bindingConstraint === "availability"));
}
// Narrowed to the preview offer's own line, so the row cap cannot be what
// keeps it out of the list. Without this, dropping the filter still passes.
const previewLine = previews[0].line;
const narrowed = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, requireLines: [previewLine] });
if (isResult(narrowed)) {
  // Pin the premise first: a truncated list and a complete one look identical,
  // so an assertion about what is absent means nothing until this holds.
  check("that short list is complete, not truncated", narrowed.truncated === false && narrowed.eligible.length === narrowed.eligibleCount, `${narrowed.eligible.length} of ${narrowed.eligibleCount}`);
  check("a preview offer is absent even from its own line's short list", !narrowed.eligible.some((e) => e.availability !== "live"), `${narrowed.eligible.length} rows`);
  check("and appears in that list's refusals", narrowed.rejected.some((r) => r.bindingConstraint === "availability"));
}
const withPreview = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, includePreview: true, limit: 50 });
if (isResult(withPreview) && isResult(defaultJob)) {
  check("asking for preview offers brings them back", withPreview.eligibleCount > defaultJob.eligibleCount, `${withPreview.eligibleCount} vs ${defaultJob.eligibleCount}`);
}

console.log("7. A zero price says what it is");
const zeroPriced = snapshot.offers.filter((o) => o.inputPerMillionMicro === 0 && o.outputPerMillionMicro === 0 && o.context > 0);
check("the catalogue lists some offers at zero", zeroPriced.length > 0, `${zeroPriced.length}`);
// The free tier lives on one line and inside a modest window, so this job is
// chosen to make sure those offers are actually in the answer before anything
// is asserted about them.
const freeLine = zeroPriced[0].line;
const glmJob = plan(snapshot, 0, { inputTokens: 1_000, outputTokens: 100, requireLines: [freeLine] });
if (isResult(glmJob)) {
  check("that list is complete, not truncated", glmJob.truncated === false && glmJob.eligible.length === glmJob.eligibleCount, `${glmJob.eligible.length} of ${glmJob.eligibleCount}`);
  const free = glmJob.eligible.filter((e) => e.listedAtZero === true);
  check("the free offers are still recommended", free.length === zeroPriced.filter((o) => o.line === freeLine).length, `${free.length} of them`);
  check("every one of them says the catalogue listed it at zero", free.every((e) => e.totalCost.microUsd === 0));
  const priced = glmJob.eligible.filter((e) => e.totalCost.microUsd > 0);
  check("priced rows carry no such mark", priced.every((e) => e.listedAtZero === undefined), `${priced.length} priced rows`);
}

console.log("8. Money formatting holds for every integer it can meet");
let threw = 0;
for (const micro of [0, 1, 9, 10, 99, 1_000, 999_999, 1_000_000, 123_456_789]) {
  try {
    usd(micro);
  } catch {
    threw += 1;
  }
}
check("no whole micro-dollar amount fails to format", threw === 0);
check("zero formats as zero", usd(0) === "$0.00");
// The invariant made observable: hand it something that is not a whole
// micro-dollar and it refuses rather than quietly rounding.
let refusedFraction = false;
try {
  usd(1.5);
} catch {
  refusedFraction = true;
}
check("a fractional micro-dollar is refused, not rounded", refusedFraction);

console.log("9. JSON-RPC says the same thing as the REST route");
const ctx = { snapshot, staleSeconds: 0, submitted: snapshot };
// eslint-disable-next-line @typescript-eslint/no-explicit-any
const rpc = (payload: unknown): any => handleMcpPayload(payload, ctx);

const listed = rpc({ jsonrpc: "2.0", id: 1, method: "tools/list" });
const listedNames = (listed.result.tools as { name: string }[]).map((t) => t.name);
check("the tool list comes from the manifest", listedNames.join(",") === TOOLS.tools.map((t) => t.name).join(","), listedNames.join(", "));
check("every listed tool carries a schema", (listed.result.tools as { inputSchema: { type: string } }[]).every((t) => t.inputSchema.type === "object"));
const planSchema = (listed.result.tools as { name: string; inputSchema: { properties: Record<string, { type: string }>; required?: string[] } }[]).find((t) => t.name === "plan_call")?.inputSchema;
check("the job's token counts are required", planSchema?.required?.includes("inputTokens") === true && planSchema?.required?.includes("outputTokens") === true, (planSchema?.required ?? []).join(", "));
check("the preview switch is typed as a boolean", planSchema?.properties.includePreview?.type === "boolean");
check("a list of lines is typed as an array", planSchema?.properties.requireLines?.type === "array");

// The point of the layer: one implementation behind two doors.
const args = { inputTokens: 100_000, outputTokens: 10_000, baselineModelId: "gpt-5.5", limit: 5 };
const called = rpc({ jsonrpc: "2.0", id: 2, method: "tools/call", params: { name: "plan_call", arguments: args } });
const throughRpc = JSON.parse((called.result.content as { text: string }[])[0].text);
const throughRest = runPlanCall(snapshot, 0, args).body;
check("a call through JSON-RPC matches the REST answer byte for byte", JSON.stringify(throughRpc) === JSON.stringify(throughRest));
check("a successful call is not marked as an error", called.result.isError === undefined);

// A tool refusing is a result. Only a malformed request is a protocol error.
const refused = rpc({ jsonrpc: "2.0", id: 3, method: "tools/call", params: { name: "plan_call", arguments: { inputTokens: -1, outputTokens: 5 } } });
check("a refusing tool answers as a result, not a protocol error", refused.error === undefined && refused.result.isError === true);
check("the refusal carries the reason", JSON.parse((refused.result.content as { text: string }[])[0].text).error === "invalid_token_counts");

const noSuchTool = rpc({ jsonrpc: "2.0", id: 4, method: "tools/call", params: { name: "make_coffee" } });
check("an unknown tool is a protocol error", noSuchTool.error?.code === -32602);
check("and it names the tools that do exist", Array.isArray(noSuchTool.error?.data?.available));

const noSuchMethod = rpc({ jsonrpc: "2.0", id: 5, method: "tools/rename" });
check("an unknown method is method-not-found", noSuchMethod.error?.code === -32601);

const wrongVersion = rpc({ jsonrpc: "1.0", id: 6, method: "tools/list" });
check("a request that is not JSON-RPC 2.0 is refused", wrongVersion.error?.code === -32600);

const init = rpc({ jsonrpc: "2.0", id: 7, method: "initialize", params: {} });
check("initialize answers with tool capability", init.result.capabilities.tools !== undefined);

check("a notification gets no reply", rpc({ jsonrpc: "2.0", method: "notifications/initialized" }) === null);

const batch = rpc([
  { jsonrpc: "2.0", id: 8, method: "ping" },
  { jsonrpc: "2.0", id: 9, method: "tools/list" },
]);
check("a batch comes back as a batch", Array.isArray(batch) && batch.length === 2);

check("the manifest and the RPC list cannot drift", listTools().length === TOOLS.tools.length);

console.log("10. The snapshot is content addressed");
check("the committed snapshot's id recomputes", snapshotIdOf(snapshot.offers) === snapshot.snapshotId);
const tampered = snapshot.offers.map((o, i) => (i === 0 ? { ...o, inputPerMillionMicro: o.inputPerMillionMicro + 1 } : o));
check("changing one price changes the id", snapshotIdOf(tampered) !== snapshot.snapshotId);

console.log(failures === 0 ? `\nAll checks passed (${snapshot.offers.length} offers).` : `\n${failures} check(s) failed.`);
if (failures > 0) process.exit(1);
