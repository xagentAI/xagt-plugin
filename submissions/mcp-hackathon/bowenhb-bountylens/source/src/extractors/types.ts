/** A raw, explainable signal that can be scored independently later. */
export type EvidenceSignal<Value> = {
  value: Value;
  confidence: number;
  evidence: string[];
};

/** Keep every extractor confidence value inside the documented 0–1 range. */
export function clampConfidence(value: number): number {
  return Math.min(1, Math.max(0, value));
}
