import { WINDOW as SEP_10_2026 } from "./window.mjs";
import { SEP_17_2026 } from "./window-sep17.mjs";
import { EVIDENCE_LEDGER } from "./evidence.mjs";
import { WINDOW_INTEGRITY, EVIDENCE_INTEGRITY } from "./integrity.mjs";

export const WINDOWS = Object.freeze([SEP_10_2026, SEP_17_2026]);

export function phaseForWindow(window, now = new Date()) {
  return now < new Date(window.boundary_utc) ? "PRE_BOUNDARY" : "POST_BOUNDARY";
}

export function evidenceForWindow(windowId) {
  return EVIDENCE_LEDGER.filter((item) => item.window_id === windowId);
}

export function listWindows(now = new Date()) {
  return WINDOWS.map((window) => ({
    id: window.id,
    boundary_utc: window.boundary_utc,
    baseline_captured_at_utc: window.baseline.captured_at_utc,
    phase: phaseForWindow(window, now),
    durable_evidence_count: evidenceForWindow(window.id).length,
    precommit_sha256: WINDOW_INTEGRITY[window.id]?.sha256 ?? null,
    retroactive_rewrite: window.invariants.retroactive_rewrite,
    trading_signal: window.invariants.trading_signal
  }));
}

export function getWindow(windowId, now = new Date()) {
  const window = WINDOWS.find((item) => item.id === windowId);
  if (!window) return null;
  return {
    window,
    phase: phaseForWindow(window, now),
    integrity: {
      precommit: WINDOW_INTEGRITY[windowId] ?? null,
      evidence: EVIDENCE_INTEGRITY[windowId] ?? null
    },
    evidence: evidenceForWindow(windowId)
  };
}

export function temporalSummary(now = new Date()) {
  const windows = listWindows(now);
  const next = windows.find((item) => item.phase === "PRE_BOUNDARY") || null;
  return {
    schema: "bhrigu_temporal_evidence_index_v0_1",
    law: "FIELD → WINDOW → REALITY → MEMORY → NEXT WINDOW",
    append_only: true,
    hash_bound_artifacts: true,
    durable_evidence_count: EVIDENCE_LEDGER.length,
    window_count: windows.length,
    next_window_id: next?.id ?? null,
    next_boundary_utc: next?.boundary_utc ?? null
  };
}
