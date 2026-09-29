import type { EvidenceSignal } from "../extractors/types.js";
import type { ScopeEvidence } from "../extractors/scope.js";
import type { DimensionScore } from "./types.js";
import { clampScore, normalizeConfidence } from "./utils.js";

/** Convert observable task-definition signals into a 0–100 clarity score. */
export function scoreScopeClarity(scope: EvidenceSignal<ScopeEvidence>): DimensionScore {
  const value = scope.value;
  const contributions = [
    { points: value.hasAcceptanceSection ? 20 : 0, label: "acceptance criteria" },
    { points: value.hasReproductionSection ? 15 : 0, label: "reproduction steps" },
    { points: Math.min(value.checklistItemCount * 6, 24), label: "checklist items" },
    { points: Math.min(value.orderedStepCount * 4, 12), label: "ordered steps" },
    { points: Math.min(value.testSignalCount * 8, 16), label: "test signals" },
    { points: Math.min(value.fileReferenceCount * 5, 10), label: "file references" },
    { points: Math.min(value.actionItemCount * 3, 12), label: "action items" },
  ];
  const score = clampScore(10 + contributions.reduce((total, item) => total + item.points, 0));
  const positiveContributions = contributions.filter((item) => item.points > 0);

  return {
    score,
    confidence: normalizeConfidence(scope.confidence),
    evidence:
      positiveContributions.length === 0
        ? ["No explicit acceptance, reproduction, test, file, or action signals were found."]
        : positiveContributions.map((item) => `Scope ${item.label}: +${item.points} point(s).`),
  };
}
