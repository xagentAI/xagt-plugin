import { evaluateAgreement } from "../evaluate.js";
import { AIProviderError } from "./providers.js";
import { evidenceContentSchema, reviewFindingSchema } from "./schemas.js";

const DEFAULT_MIN_CONFIDENCE = 0.65;
const DEFAULT_CRITICAL_MIN_CONFIDENCE = 0.8;
const MAX_EVIDENCE_CONTENT_ITEMS = 200;
const MAX_REVIEW_CONTENT_BYTES = 256 * 1024;
const MIN_REVIEW_TIMEOUT_MS = 250;
const MAX_REVIEW_TIMEOUT_MS = 30_000;

export class ReviewValidationError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "ReviewValidationError";
    this.code = code;
    this.details = details;
  }
}

function contentForEvidence(evidence, evidenceContent) {
  const contentById = new Map(evidenceContent.map((item) => [item.id, item.content]));
  return evidence.map((item) => ({
    ...item,
    content: contentById.get(item.id) ?? null,
  }));
}

function validateReviewInputs({ agreement, evidenceContent, timeoutMs }) {
  evaluateAgreement({ ...agreement, findings: [] });
  if (!Array.isArray(evidenceContent) || evidenceContent.length > MAX_EVIDENCE_CONTENT_ITEMS) {
    throw new ReviewValidationError(
      "INVALID_EVIDENCE_CONTENT",
      `evidenceContent must contain no more than ${MAX_EVIDENCE_CONTENT_ITEMS} items.`,
    );
  }
  const ids = new Set();
  for (const item of evidenceContent) {
    const checked = evidenceContentSchema.safeParse(item);
    if (!checked.success) {
      throw new ReviewValidationError("INVALID_EVIDENCE_CONTENT", "Each evidence content item needs a bounded id and content.");
    }
    if (ids.has(item.id)) {
      throw new ReviewValidationError("INVALID_EVIDENCE_CONTENT", `Evidence content contains duplicate id ${item.id}.`);
    }
    ids.add(item.id);
  }
  if (!Number.isFinite(timeoutMs) || timeoutMs < MIN_REVIEW_TIMEOUT_MS || timeoutMs > MAX_REVIEW_TIMEOUT_MS) {
    throw new ReviewValidationError(
      "INVALID_REVIEW_TIMEOUT",
      `Review timeout must be between ${MIN_REVIEW_TIMEOUT_MS} and ${MAX_REVIEW_TIMEOUT_MS} milliseconds.`,
    );
  }
  const reviewPolicy = agreement.reviewPolicy ?? {};
  for (const [field, fallback] of [["minimumConfidence", DEFAULT_MIN_CONFIDENCE], ["criticalMinimumConfidence", DEFAULT_CRITICAL_MIN_CONFIDENCE]]) {
    const value = reviewPolicy[field] ?? fallback;
    if (!Number.isFinite(value) || value < 0 || value > 1) {
      throw new ReviewValidationError("INVALID_REVIEW_POLICY", `${field} must be between 0 and 1.`);
    }
  }
}

function validateFinding({ finding, criterion, evidence }) {
  const checked = reviewFindingSchema.safeParse(finding);
  if (!checked.success) {
    throw new ReviewValidationError("AI_SCHEMA_INVALID", "The review finding failed local schema validation.");
  }
  const data = checked.data;
  if (data.criterionId !== criterion.id) {
    throw new ReviewValidationError("AI_CRITERION_MISMATCH", "The finding references a different criterion.");
  }
  const allowedEvidence = new Map(evidence.map((item) => [item.id, item]));
  for (const citation of data.evidenceCitations) {
    const cited = allowedEvidence.get(citation.evidenceId);
    if (!cited || cited.criterionId !== criterion.id) {
      throw new ReviewValidationError(
        "AI_EVIDENCE_MISMATCH",
        `The finding cited evidence outside criterion ${criterion.id}.`,
        { evidenceId: citation.evidenceId, criterionId: criterion.id },
      );
    }
  }
  const uncertain =
    data.score === null ||
    data.evidenceCitations.length === 0 ||
    data.verdict === "insufficient_evidence" ||
    data.verdict === "conflicting_evidence" ||
    data.verdict === "cannot_assess";
  return { ...data, uncertain };
}

function findingForKernel({ finding, criterion, providerName }) {
  if (finding.uncertain || finding.score === null) return null;
  return {
    id: `ai-${criterion.id}`,
    criterionId: criterion.id,
    evaluator: `${providerName}:reviewer`,
    score: finding.score,
    confidence: finding.confidence,
    evidenceIds: finding.evidenceCitations.map((item) => item.evidenceId),
    rationale: finding.rationale,
  };
}

function abortAfter(ms, parentSignal) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), ms);
  const cleanup = () => clearTimeout(timer);
  if (parentSignal) {
    if (parentSignal.aborted) controller.abort();
    parentSignal.addEventListener("abort", () => controller.abort(), { once: true });
  }
  return { signal: controller.signal, cleanup };
}

export async function reviewAgreement({
  agreement,
  evidenceContent = [],
  provider,
  signal,
  timeoutMs = 12_000,
}) {
  validateReviewInputs({ agreement, evidenceContent, timeoutMs });
  const content = contentForEvidence(agreement.evidence, evidenceContent);
  if (Buffer.byteLength(JSON.stringify(content), "utf8") > MAX_REVIEW_CONTENT_BYTES) {
    throw new ReviewValidationError(
      "EVIDENCE_CONTENT_TOO_LARGE",
      `Evidence supplied to the reviewer must be no larger than ${MAX_REVIEW_CONTENT_BYTES} bytes.`,
    );
  }
  const reviewPolicy = agreement.reviewPolicy ?? {};
  const minConfidence = reviewPolicy.minimumConfidence ?? DEFAULT_MIN_CONFIDENCE;
  const criticalMinConfidence =
    reviewPolicy.criticalMinimumConfidence ?? DEFAULT_CRITICAL_MIN_CONFIDENCE;
  const findings = [];
  const reviews = [];
  const failures = [];
  const startedAt = Date.now();

  for (const criterion of agreement.criteria) {
    const evidence = content.filter((item) => item.criterionId === criterion.id);
    const deadline = abortAfter(timeoutMs, signal);
    try {
      const raw = await provider.reviewCriterion({ criterion, evidence }, deadline.signal);
      const finding = validateFinding({ finding: raw, criterion, evidence });
      const threshold = criterion.critical ? criticalMinConfidence : minConfidence;
      const belowThreshold = finding.confidence < threshold;
      const accepted = !finding.uncertain && !belowThreshold;
      const kernelFinding = accepted
        ? findingForKernel({ finding, criterion, providerName: provider.name })
        : null;
      if (kernelFinding) findings.push(kernelFinding);
      reviews.push({
        criterionId: criterion.id,
        verdict: finding.verdict,
        score: finding.score,
        confidence: finding.confidence,
        evidenceCitations: finding.evidenceCitations,
        missingEvidence: finding.missingEvidence,
        contradictions: finding.contradictions,
        rationale: finding.rationale,
        accepted,
        belowThreshold,
      });
    } catch (error) {
      const code = error instanceof AIProviderError || error instanceof ReviewValidationError
        ? error.code
        : error?.name === "AbortError"
          ? "AI_TIMEOUT"
          : "AI_REVIEW_FAILED";
      failures.push({ criterionId: criterion.id, code });
      reviews.push({
        criterionId: criterion.id,
        verdict: "cannot_assess",
        score: null,
        confidence: 0,
        evidenceCitations: [],
        missingEvidence: [],
        contradictions: [],
        rationale: "This criterion could not be reviewed safely.",
        accepted: false,
        belowThreshold: true,
        errorCode: code,
      });
    } finally {
      deadline.cleanup();
    }
  }

  const requiresHumanReview = reviews.some(
    (item) => !item.accepted || item.contradictions.length > 0,
  );
  const evaluationInput = { ...agreement, findings };
  const evaluation = evaluateAgreement(evaluationInput);

  return {
    schemaVersion: 1,
    reviewRun: {
      provider: provider.name,
      model: provider.model,
      promptVersion: provider.promptVersion,
      startedAt,
      completedAt: Date.now(),
      durationMs: Date.now() - startedAt,
    },
    readyToResolve: !requiresHumanReview && failures.length === 0,
    requiresHumanReview,
    failures,
    reviews,
    findings,
    evaluation,
  };
}
