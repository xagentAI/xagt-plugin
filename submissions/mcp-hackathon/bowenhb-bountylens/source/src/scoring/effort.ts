import type { EvidenceSignal } from "../extractors/types.js";
import type { ScopeEvidence } from "../extractors/scope.js";
import type { EffortEstimate } from "./types.js";
import { normalizeConfidence } from "./utils.js";

function roundHalfHour(value: number): number {
  return Math.round(value * 2) / 2;
}

/** Produce a deliberately coarse range from public scope signals, never a commitment. */
export function estimateEffort(scope: EvidenceSignal<ScopeEvidence>): EffortEstimate {
  const value = scope.value;
  const signalCount =
    Number(value.hasAcceptanceSection) +
    Number(value.hasReproductionSection) +
    value.checklistItemCount +
    value.orderedStepCount +
    value.testSignalCount +
    value.fileReferenceCount +
    value.actionItemCount;
  const centralHours =
    2 +
    value.checklistItemCount * 0.75 +
    value.actionItemCount * 0.8 +
    value.testSignalCount * 1.25 +
    value.fileReferenceCount * 0.9 +
    value.orderedStepCount * 0.25;
  const confidence = normalizeConfidence(scope.confidence * (signalCount === 0 ? 0.5 : 1));

  if (signalCount === 0) {
    return {
      minHours: 2,
      maxHours: 16,
      confidence,
      evidence: ["Scope signals are missing, so the estimate uses a wide 2–16 hour range."],
    };
  }

  const uncertainty = 0.3 + (1 - confidence) * 0.55;
  const minHours = Math.max(1, roundHalfHour(centralHours * (1 - uncertainty)));
  const maxHours = Math.min(80, Math.max(minHours + 1, roundHalfHour(centralHours * (1 + uncertainty))));

  return {
    minHours,
    maxHours,
    confidence,
    evidence: [
      `Estimate uses ${value.checklistItemCount} checklist item(s), ${value.testSignalCount} test signal(s), ${value.fileReferenceCount} file reference(s), and ${value.actionItemCount} action item(s).`,
      "This range is derived from public metadata; the target repository code was not executed.",
    ],
  };
}
