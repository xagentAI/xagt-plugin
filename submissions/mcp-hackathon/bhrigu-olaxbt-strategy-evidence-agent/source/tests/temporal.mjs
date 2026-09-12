import assert from "node:assert/strict";
import { getWindow, listWindows, temporalSummary } from "../lib/windows.mjs";
import { SEP_10_POSTBOUNDARY_EVIDENCE } from "../lib/evidence.mjs";

const before = new Date("2026-09-16T23:59:59Z");
const after = new Date("2026-09-17T00:00:01Z");

const windowsBefore = listWindows(before);
assert.equal(windowsBefore.length, 2);
assert.equal(windowsBefore[0].id, "SEP_10_2026");
assert.equal(windowsBefore[0].phase, "POST_BOUNDARY");
assert.equal(windowsBefore[0].durable_evidence_count, 1);
assert.equal(windowsBefore[1].id, "SEP_17_2026");
assert.equal(windowsBefore[1].phase, "PRE_BOUNDARY");

const sep10 = getWindow("SEP_10_2026", before);
assert.equal(sep10.window.baseline.btcusdt_last_price, 78474);
assert.equal(sep10.evidence.length, 1);
assert.equal(sep10.evidence[0].id, SEP_10_POSTBOUNDARY_EVIDENCE.id);
assert.equal(sep10.evidence[0].observation.btcusdt_last_price, 78348.09);
assert.equal(sep10.evidence[0].invariants.append_only, true);

const sep17 = getWindow("SEP_17_2026", before);
assert.equal(sep17.window.baseline.captured_at_utc, "2026-09-10T04:49:49.136Z");
assert.equal(sep17.window.baseline.btcusdt_last_price, 78348.09);
assert.equal(sep17.evidence.length, 0);
assert.equal(getWindow("SEP_17_2026", after).phase, "POST_BOUNDARY");

const summary = temporalSummary(before);
assert.equal(summary.window_count, 2);
assert.equal(summary.durable_evidence_count, 1);
assert.equal(summary.next_window_id, "SEP_17_2026");
assert.equal(summary.append_only, true);

console.log(JSON.stringify({ schema: "bhrigu_temporal_tests_v0_1", status: "PASS", checks: 17 }));
