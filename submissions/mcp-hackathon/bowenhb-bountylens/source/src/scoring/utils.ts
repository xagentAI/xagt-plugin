import { clampConfidence } from "../extractors/types.js";

export function clampScore(value: number): number {
  if (!Number.isFinite(value)) return 0;
  return Math.min(100, Math.max(0, Math.round(value)));
}

export function normalizeConfidence(value: number): number {
  return Number(clampConfidence(value).toFixed(2));
}

export function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((total, value) => total + value, 0) / values.length;
}
