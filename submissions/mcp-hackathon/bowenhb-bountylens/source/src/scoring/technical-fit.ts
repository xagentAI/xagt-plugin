import type { DeveloperProfile, DimensionScore } from "./types.js";
import { clampScore } from "./utils.js";

function normalizeLanguage(language: string): string {
  return language.trim().toLocaleLowerCase("en-US");
}

/** Score byte-weighted repository-language overlap with an optional developer profile. */
export function scoreTechnicalFit(
  repositoryLanguages: Record<string, number>,
  developerProfile?: DeveloperProfile,
): DimensionScore {
  const profileLanguages = developerProfile?.languages
    ?.map(normalizeLanguage)
    .filter((language) => language.length > 0);
  if (profileLanguages === undefined || profileLanguages.length === 0) {
    return {
      score: 50,
      confidence: 0.35,
      evidence: ["Developer languages were not provided; a neutral technical-fit score was used."],
    };
  }

  const validLanguages = Object.entries(repositoryLanguages).filter(
    ([, bytes]) => Number.isFinite(bytes) && bytes > 0,
  );
  const totalBytes = validLanguages.reduce((total, [, bytes]) => total + bytes, 0);
  if (totalBytes === 0) {
    return {
      score: 50,
      confidence: 0.25,
      evidence: ["Repository language data is unavailable; a neutral technical-fit score was used."],
    };
  }

  const profileSet = new Set(profileLanguages);
  const matched = validLanguages.filter(([language]) => profileSet.has(normalizeLanguage(language)));
  const matchedBytes = matched.reduce((total, [, bytes]) => total + bytes, 0);
  const score = clampScore((matchedBytes / totalBytes) * 100);

  return {
    score,
    confidence: 0.9,
    evidence: [
      matched.length === 0
        ? "No repository language overlaps with the supplied developer languages."
        : `Matched repository language(s): ${matched.map(([language]) => language).join(", ")}.`,
      `${score}% of measured repository language bytes match the supplied profile.`,
    ],
  };
}
