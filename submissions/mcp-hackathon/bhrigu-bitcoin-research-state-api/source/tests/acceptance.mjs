import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { buildState } from "../lib/state.mjs";
import { healthPayload, verificationPayload, SLUG } from "../lib/runtime.mjs";

process.env.BHRIGU_COMMIT = "a".repeat(40);

const fakeFetch = async (url) => {
  if (String(url).includes("data-api.binance.vision")) {
    return new Response(JSON.stringify({
      lastPrice: "79000.00",
      priceChangePercent: "1.25",
      highPrice: "80000.00",
      lowPrice: "77000.00",
      volume: "12345.67",
      closeTime: Date.parse("2026-09-08T12:00:00Z")
    }), { status: 200, headers: { "content-type": "application/json" } });
  }
  if (String(url).includes("mempool.space")) return new Response("966100", { status: 200 });
  throw new Error("UNEXPECTED_URL");
};

const health = healthPayload();
assert.equal(health.status, "ok");
assert.match(health.commit, /^[a-f0-9]{40}$/);
assert.deepEqual(verificationPayload(), { schemaVersion: 1, slug: SLUG, commit: "a".repeat(40) });

const pre = await buildState({ fetchImpl: fakeFetch, now: new Date("2026-09-08T12:00:30Z") });
assert.equal(pre.market.symbol, "BTCUSDT");
assert.equal(pre.market.last_price_usdt, 79000);
assert.equal(pre.market.freshness, "FRESH");
assert.equal(pre.protocol_time.halving_epoch, 4);
assert.equal(pre.protocol_time.live_tip_height, 966100);
assert.equal(pre.window.phase, "PRE_BOUNDARY");
assert.equal(pre.window.comparison_status, "NOT_FINAL_BEFORE_BOUNDARY");
assert.equal(pre.memory.append_only, true);
assert.equal(pre.memory.retroactive_rewrite, "forbidden");
assert.deepEqual(pre.authority, {
  trading: false,
  wallet: false,
  payment: false,
  withdrawal: false,
  transfer: false,
  private_account_data: false,
  credentials_read: false
});

const post = await buildState({ fetchImpl: fakeFetch, now: new Date("2026-09-10T01:00:00Z") });
assert.equal(post.window.phase, "POST_BOUNDARY");
assert.equal(post.window.comparison_status, "REALITY_COMPARISON_OPEN");
assert.equal(Number.isFinite(post.window.current_vs_baseline_pct), true);

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const liveSource = fs.readFileSync(path.join(root, "lib/live.mjs"), "utf8");
const urls = [...liveSource.matchAll(/https:\/\/[^"\s]+/g)].map((m) => m[0]);
assert.deepEqual(urls.sort(), [
  "https://data-api.binance.vision/api/v3/ticker/24hr?symbol=BTCUSDT",
  "https://mempool.space/api/blocks/tip/height"
].sort());
const pkg = JSON.parse(fs.readFileSync(path.join(root, "package.json"), "utf8"));
assert.equal(pkg.dependencies, undefined);

await assert.rejects(
  () => buildState({ fetchImpl: async () => { throw new Error("OFFLINE"); } }),
  /OFFLINE/
);

console.log(JSON.stringify({
  schema: "bhrigu_bitcoin_research_state_acceptance_v0_1",
  status: "PASS",
  checks: 18
}, null, 2));
