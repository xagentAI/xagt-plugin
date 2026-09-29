import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import { SEP_10_POSTBOUNDARY_EVIDENCE } from "../lib/evidence.mjs";
import { SEP_17_2026 } from "../lib/window-sep17.mjs";
import { WINDOW_INTEGRITY, EVIDENCE_INTEGRITY } from "../lib/integrity.mjs";

const sha256 = (path) => crypto.createHash("sha256").update(fs.readFileSync(new URL(path, import.meta.url))).digest("hex");

assert.equal(sha256("../lib/window.mjs"), WINDOW_INTEGRITY.SEP_10_2026.sha256, "SEP_10_2026 precommit changed");
assert.equal(sha256("../evidence/SEP_17_2026_PRECOMMIT.json"), WINDOW_INTEGRITY.SEP_17_2026.sha256, "SEP_17_2026 precommit proof changed");
assert.equal(sha256("../evidence/SEP_10_2026_POSTBOUNDARY.json"), EVIDENCE_INTEGRITY.SEP_10_2026.sha256, "SEP_10_2026 evidence changed");

const sep10Json = JSON.parse(fs.readFileSync(new URL("../evidence/SEP_10_2026_POSTBOUNDARY.json", import.meta.url), "utf8"));
assert.equal(sep10Json.window_id, SEP_10_POSTBOUNDARY_EVIDENCE.window_id);
assert.equal(sep10Json.observed_btcusdt, SEP_10_POSTBOUNDARY_EVIDENCE.observation.btcusdt_last_price);
assert.equal(sep10Json.runtime_commit, SEP_10_POSTBOUNDARY_EVIDENCE.provenance.runtime_commit);

const sep17Json = JSON.parse(fs.readFileSync(new URL("../evidence/SEP_17_2026_PRECOMMIT.json", import.meta.url), "utf8"));
assert.equal(sep17Json.window_id, SEP_17_2026.id);
assert.equal(sep17Json.boundary_utc, SEP_17_2026.boundary_utc);
assert.equal(sep17Json.btcusdt_last_price, SEP_17_2026.baseline.btcusdt_last_price);

const stateSource = fs.readFileSync(new URL("../lib/state.mjs", import.meta.url), "utf8");
const mcpSource = fs.readFileSync(new URL("../lib/mcp.mjs", import.meta.url), "utf8");
const forbidden = [/apiKey/i, /secretKey/i, /withdraw/i, /placeOrder/i, /privateKey/i];
for (const pattern of forbidden) assert.equal(pattern.test(mcpSource), false, `MCP source contains forbidden authority token ${pattern}`);
assert.match(stateSource, /trading: false/);
assert.match(stateSource, /wallet: false/);
assert.match(stateSource, /payment: false/);

console.log(JSON.stringify({
  schema: "bhrigu_integrity_tests_v0_2",
  status: "PASS",
  sep10_window_sha256: WINDOW_INTEGRITY.SEP_10_2026.sha256,
  sep10_evidence_sha256: EVIDENCE_INTEGRITY.SEP_10_2026.sha256,
  sep17_precommit_sha256: WINDOW_INTEGRITY.SEP_17_2026.sha256,
  checks: 15
}));
