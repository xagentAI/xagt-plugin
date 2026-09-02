import { AppError } from "./errors";
import type { GeneratedMission, SemanticSection } from "./schemas";

const PLATFORM_LIMITS = {
  linkedin: 3_000,
  x: 280,
  reddit: 40_000,
  xiaohongshu: 1_000,
  wechat: 20_000,
} as const;

const GUARANTEE_PATTERNS = [
  /\bguarantee(?:d|s)?\b/i,
  /\bwill (?:definitely|certainly)\b/i,
  /\b100% (?:growth|results?|success|effective)\b/i,
  /保证(?:增长|效果|成功|转化)/,
  /百分之百(?:增长|有效|成功)/,
];

const PLATFORM_BRANDS: Partial<Record<GeneratedMission["mission"]["platform"], string[]>> = {
  linkedin: ["linkedin"],
  reddit: ["reddit"],
  xiaohongshu: ["xiaohongshu", "小红书"],
  wechat: ["wechat", "微信公众号", "微信公众"],
};

const HYPOTHESIS_MARKERS =
  /\b(?:test|testing|hypothesis|may|might|could|explore|consider|try|experiment)\b|(?:测试|假设|可能|或许|尝试|试试|探索)/i;

export type QualityReport = {
  passed: true;
  evidenceExactMatch: true;
  unsupportedNumbers: string[];
  platformChecks: {
    platform: GeneratedMission["mission"]["platform"];
    characterCount: number;
    characterLimit: number;
    hasTrackingCta: true;
  };
  warnings: string[];
};

export function validateGeneratedMission(
  generated: GeneratedMission,
  sections: SemanticSection[],
  requestedObjective: GeneratedMission["mission"]["primaryMetric"],
  requestedPlatform: "auto" | GeneratedMission["mission"]["platform"],
): QualityReport {
  if (generated.mission.primaryMetric !== requestedObjective) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "Generated mission changed the requested objective.", 422);
  }
  if (requestedPlatform !== "auto" && generated.mission.platform !== requestedPlatform) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "Generated mission changed the requested platform.", 422);
  }

  const sectionsById = new Map(sections.map((section) => [section.id, section.text]));
  const evidenceIds = new Set<string>();
  const evidenceById = new Map<string, string>();
  for (const evidence of generated.evidence) {
    if (evidenceIds.has(evidence.id)) {
      throw new AppError("EVIDENCE_VALIDATION_FAILED", `Duplicate evidence ID: ${evidence.id}.`, 422);
    }
    evidenceIds.add(evidence.id);
    evidenceById.set(evidence.id, evidence.quote);
    const section = sectionsById.get(evidence.sectionId);
    if (!section || !section.includes(evidence.quote)) {
      throw new AppError(
        "EVIDENCE_VALIDATION_FAILED",
        `Evidence ${evidence.id} is not an exact substring of ${evidence.sectionId}.`,
        422,
      );
    }
  }
  const deliverableText = [
    generated.mission.title,
    generated.mission.hypothesis,
    generated.asset.title,
    generated.asset.body,
    generated.asset.cta,
  ].join("\n");
  for (const mapping of generated.claimMap) {
    const citedQuotes: string[] = [];
    for (const evidenceId of mapping.evidenceIds) {
      if (!evidenceIds.has(evidenceId)) {
        throw new AppError("EVIDENCE_VALIDATION_FAILED", `Claim references unknown evidence ${evidenceId}.`, 422);
      }
      const quote = evidenceById.get(evidenceId);
      if (quote) citedQuotes.push(quote);
    }
    if (!deliverableText.includes(mapping.claim)) {
      throw new AppError("EVIDENCE_VALIDATION_FAILED", "A mapped claim is not an exact substring of the deliverable.", 422, {
        details: { claim: mapping.claim },
      });
    }
    if (!citedQuotes.some((quote) => quote.includes(mapping.claim))) {
      throw new AppError("EVIDENCE_VALIDATION_FAILED", "A mapped claim is not an exact substring of its cited evidence.", 422, {
        details: { claim: mapping.claim },
      });
    }
  }

  const body = generated.asset.body;
  if (!body.includes("{{TRACKING_URL}}")) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "The content must include exactly one tracking CTA placeholder.", 422);
  }
  if (body.indexOf("{{TRACKING_URL}}") !== body.lastIndexOf("{{TRACKING_URL}}")) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "The content contains more than one tracking CTA.", 422);
  }
  if (generated.asset.cta.includes("{{TRACKING_URL}}")) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "The CTA field must contain action text, not the tracking placeholder.", 422);
  }

  const evidenceText = generated.evidence.map((evidence) => evidence.quote).join("\n");
  for (const brand of PLATFORM_BRANDS[generated.mission.platform] ?? []) {
    if (deliverableText.toLowerCase().includes(brand.toLowerCase()) && !evidenceText.toLowerCase().includes(brand.toLowerCase())) {
      throw new AppError(
        "EVIDENCE_VALIDATION_FAILED",
        `The deliverable names ${brand} without citing source evidence that names it.`,
        422,
      );
    }
  }

  for (const pattern of GUARANTEE_PATTERNS) {
    if (pattern.test(`${body}\n${generated.asset.cta}\n${generated.mission.hypothesis}`)) {
      throw new AppError("QUALITY_VALIDATION_FAILED", "Absolute or guaranteed outcome language is not allowed.", 422);
    }
  }

  const limit = PLATFORM_LIMITS[generated.mission.platform];
  const projectedBody = body.replace("{{TRACKING_URL}}", "https://api.finfold.app/r/000000000000000000000000000000000000");
  if ([...projectedBody].length > limit) {
    throw new AppError("QUALITY_VALIDATION_FAILED", `Content exceeds the ${generated.mission.platform} character limit.`, 422, {
      details: { limit, actual: [...projectedBody].length },
    });
  }

  const supportedText = generated.evidence.map((evidence) => evidence.quote).join(" ");
  const numberTokens = [...body.matchAll(/(?<![\p{L}\p{N}])\d+(?:[.,]\d+)?%?/gu)].map((match) => match[0]);
  const unsupportedNumbers = [...new Set(numberTokens.filter((token) => !supportedText.includes(token)))];
  if (unsupportedNumbers.length) {
    throw new AppError("QUALITY_VALIDATION_FAILED", "Content contains numbers not present in cited evidence.", 422, {
      details: { unsupportedNumbers },
    });
  }

  const exactClaims = generated.claimMap.map((mapping) => mapping.claim);
  const unsupportedStatements = body
    .replace("{{TRACKING_URL}}", ".\n")
    .split(/(?<=[.!?。！？])\s+|\n+/u)
    .map((statement) => statement.trim().replace(/^["“”']+|["“”']+$/g, ""))
    .filter((statement) => statement.length >= 20)
    .filter((statement) => !/^https?:\/\//i.test(statement))
    .filter(
      (statement) =>
        !generated.evidence.some(
          (evidence) => statement.includes(evidence.quote) || evidence.quote.includes(statement),
        ),
    )
    .filter((statement) => !exactClaims.some((claim) => statement.includes(claim) || claim.includes(statement)))
    .filter((statement) => !HYPOTHESIS_MARKERS.test(statement));
  if (unsupportedStatements.length) {
    throw new AppError(
      "EVIDENCE_VALIDATION_FAILED",
      "The asset contains factual statements that are neither exact evidence nor explicitly framed as a test or hypothesis.",
      422,
      { details: { statements: unsupportedStatements.slice(0, 3) } },
    );
  }
  return {
    passed: true,
    evidenceExactMatch: true,
    unsupportedNumbers: [],
    platformChecks: {
      platform: generated.mission.platform,
      characterCount: [...projectedBody].length,
      characterLimit: limit,
      hasTrackingCta: true,
    },
    warnings: [],
  };
}
