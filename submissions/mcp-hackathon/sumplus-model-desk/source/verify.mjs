#!/usr/bin/env node
/**
 * Check an answer from this desk without trusting it, and without a network.
 *
 *   node verify.mjs responses/plan_call.json
 *   node verify.mjs responses/plan_call.json --snapshot snapshots/catalogue.json
 *
 * It reads the saved response and the catalogue snapshot shipped alongside it,
 * then recomputes every number with its own arithmetic. Nothing here imports
 * the service's own pricing code: a checker that calls the thing it is checking
 * proves only that the code agrees with itself.
 *
 * Exit code 0 means every claim in the response held.
 */
import { readFileSync } from "node:fs";
import { createHash } from "node:crypto";

const args = process.argv.slice(2);
const responsePath = args.find((a) => !a.startsWith("--"));
const snapshotFlag = args.indexOf("--snapshot");
const snapshotPath = snapshotFlag === -1 ? "snapshots/catalogue.json" : args[snapshotFlag + 1];

if (!responsePath) {
  console.error("usage: node verify.mjs <response.json> [--snapshot snapshots/catalogue.json]");
  process.exit(2);
}

const response = JSON.parse(readFileSync(responsePath, "utf8"));
const snapshot = JSON.parse(readFileSync(snapshotPath, "utf8"));

let failures = 0;
const check = (ok, name, detail = "") => {
  if (!ok) failures += 1;
  console.log(`${ok ? "  ok  " : "  FAIL"} ${name}${detail ? ` — ${detail}` : ""}`);
};

/**
 * The catalogue's own content address, recomputed here from its offers.
 * One JSON array per offer, sorted, newline separated, sha256 over the whole.
 */
function snapshotId(offers) {
  const canonical = offers
    .map((o) =>
      JSON.stringify([
        o.modelId,
        o.line,
        o.lineCode,
        o.context,
        o.maxOutput,
        o.availability,
        o.inputPerMillionMicro,
        o.outputPerMillionMicro,
        o.cacheHitPerMillionMicro,
      ]),
    )
    .sort()
    .join("\n");
  return createHash("sha256").update(canonical, "utf8").digest("hex");
}

/** Cost in micro-dollars, rounded up, in integers. Written out independently. */
function cost(tokens, perMillionMicro) {
  const product = BigInt(tokens) * BigInt(perMillionMicro);
  const whole = product / 1000000n;
  return Number(product % 1000000n === 0n ? whole : whole + 1n);
}

const offers = new Map(snapshot.offers.map((o) => [`${o.modelId}::${o.line}`, o]));

console.log(`response  ${responsePath}`);
console.log(`snapshot  ${snapshotPath} (${snapshot.offers.length} offers)\n`);

console.log("1. The catalogue is what it says it is");
check(snapshotId(snapshot.offers) === snapshot.snapshotId, "the snapshot's id recomputes from its offers");
if (response.snapshotId) {
  check(
    response.snapshotId === snapshot.snapshotId,
    "the response was priced against this snapshot",
    `${String(response.snapshotId).slice(0, 12)} vs ${snapshot.snapshotId.slice(0, 12)}`,
  );
}
check(typeof response.pricedAt === "string", "the response says when it was priced");
check(typeof response.staleSeconds === "number", "the response says how old its catalogue was");

const request = response.request ?? response.echo ?? null;
const inputTokens = request?.inputTokens ?? Number(process.env.INPUT_TOKENS ?? NaN);
const outputTokens = request?.outputTokens ?? Number(process.env.OUTPUT_TOKENS ?? NaN);

if (!Number.isFinite(inputTokens) || !Number.isFinite(outputTokens)) {
  console.log(
    "\nThe saved response does not carry the job it priced. Re-run with the token counts:\n" +
      "  INPUT_TOKENS=100000 OUTPUT_TOKENS=10000 node verify.mjs " +
      responsePath,
  );
  process.exit(failures > 0 ? 1 : 2);
}

console.log(`\n2. Every offer it accepted can take the job (${inputTokens} in, ${outputTokens} out)`);
let priced = 0;
for (const row of response.eligible ?? []) {
  const offer = offers.get(`${row.modelId}::${row.line}`);
  if (!offer) {
    check(false, `${row.modelId} on ${row.line} exists in the catalogue`);
    continue;
  }
  const fits = offer.context >= inputTokens + outputTokens;
  const outputFits = offer.maxOutput >= outputTokens;
  const expectedInput = cost(inputTokens, offer.inputPerMillionMicro);
  const expectedOutput = cost(outputTokens, offer.outputPerMillionMicro);
  const expectedTotal = expectedInput + expectedOutput;
  const claimed = row.totalCost?.microUsd;

  if (!fits || !outputFits || claimed !== expectedTotal) {
    check(fits, `${row.modelId}@${row.line}: context holds the job`, `${offer.context} vs ${inputTokens + outputTokens}`);
    check(outputFits, `${row.modelId}@${row.line}: output ceiling holds the answer`, `${offer.maxOutput} vs ${outputTokens}`);
    check(claimed === expectedTotal, `${row.modelId}@${row.line}: total matches the catalogue`, `claimed ${claimed}, recomputed ${expectedTotal}`);
  }
  priced += 1;
}
check(priced === (response.eligible ?? []).length, `all ${priced} accepted offers recomputed`);

const costs = (response.eligible ?? []).map((r) => r.totalCost?.microUsd ?? 0);
check(costs.every((c, i) => i === 0 || costs[i - 1] <= c), "accepted offers are ordered cheapest first");

console.log("\n3. Every offer it refused really is out of reach");
let wrongly = 0;
for (const row of response.rejected ?? []) {
  const offer = offers.get(`${row.modelId}::${row.line}`);
  if (!offer) continue;
  const blocked =
    offer.context < inputTokens + outputTokens ||
    offer.maxOutput < outputTokens ||
    offer.context === 0 ||
    offer.maxOutput === 0 ||
    offer.availability !== "live" ||
    row.bindingConstraint === "line" ||
    row.bindingConstraint === "min_context" ||
    row.bindingConstraint === "min_max_output";
  if (!blocked) {
    wrongly += 1;
    check(false, `${row.modelId}@${row.line} was refused but could have taken the job`, `context ${offer.context}, maxOutput ${offer.maxOutput}`);
  }
}
check(wrongly === 0, `none of the ${(response.rejected ?? []).length} refusals is spurious`);
check(
  (response.rejected ?? []).every((r) => r.bindingConstraint && r.requiredValue !== undefined && r.actualValue !== undefined),
  "every refusal names the constraint and both numbers",
);

console.log("\n4. Nothing is recommended that is not sold by the token, or not live");
const notSoldByToken = (response.eligible ?? []).filter((r) => {
  const o = offers.get(`${r.modelId}::${r.line}`);
  return o && (o.context === 0 || o.maxOutput === 0);
});
check(notSoldByToken.length === 0, "no video or image offer was recommended for a token job", `${notSoldByToken.length} such rows`);
const previews = (response.eligible ?? []).filter((r) => {
  const o = offers.get(`${r.modelId}::${r.line}`);
  return o && o.availability !== "live";
});
const previewAsked = response.request?.includePreview === true;
check(previewAsked || previews.length === 0, "no preview offer appears unless it was asked for", `${previews.length} preview rows`);
// The marker belongs to the offer's own rates, not to the total: a job of zero
// tokens costs nothing on every offer in the catalogue, and none of that says
// anything about how the offer is priced.
const listedZero = (response.eligible ?? []).filter((r) => {
  const o = offers.get(`${r.modelId}::${r.line}`);
  return o && o.inputPerMillionMicro === 0 && o.outputPerMillionMicro === 0;
});
const pricedRows = (response.eligible ?? []).filter((r) => {
  const o = offers.get(`${r.modelId}::${r.line}`);
  return o && (o.inputPerMillionMicro > 0 || o.outputPerMillionMicro > 0);
});
check(listedZero.every((r) => r.listedAtZero === true), "every offer the catalogue lists at zero says so", `${listedZero.length} such rows`);
check(pricedRows.every((r) => r.listedAtZero === undefined), "no priced offer is marked as listed at zero", `${pricedRows.length} priced rows`);

console.log("\n5. Several offers of one id keep their own rows");
const byId = new Map();
for (const row of response.eligible ?? []) {
  byId.set(row.modelId, (byId.get(row.modelId) ?? 0) + 1);
}
const repeated = [...byId.entries()].filter(([, n]) => n > 1);
check(
  repeated.length > 0 || (response.eligible ?? []).length < 5,
  "ids sold on several lines appear once per line",
  `${repeated.length} such ids`,
);

console.log(failures === 0 ? "\nEvery claim in this response held." : `\n${failures} claim(s) did not hold.`);
process.exit(failures === 0 ? 0 : 1);
