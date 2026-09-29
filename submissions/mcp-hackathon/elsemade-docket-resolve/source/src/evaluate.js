import { createHash } from "node:crypto";

const ALLOWED_EVIDENCE_KINDS = new Set([
  "artifact",
  "attestation",
  "automated_test",
  "receipt",
]);
const ALLOWED_EVIDENCE_RESULTS = new Set(["pass", "fail", "inconclusive"]);
const MAX_ATOMIC_AMOUNT = Math.floor(Number.MAX_SAFE_INTEGER / 100);
const MAX_ID_LENGTH = 128;
const MAX_AGREEMENT_ID_LENGTH = 128;
const MAX_CRITERIA = 100;
const MAX_EVIDENCE = 200;
const MAX_FINDINGS = 200;
const MAX_DESCRIPTION_LENGTH = 2_000;
const MAX_RATIONALE_LENGTH = 4_000;
const MAX_URI_LENGTH = 2_048;

export class EvaluationError extends Error {
  constructor(code, message, details = undefined) {
    super(message);
    this.name = "EvaluationError";
    this.code = code;
    this.details = details;
  }
}

function assert(condition, code, message, details) {
  if (!condition) {
    throw new EvaluationError(code, message, details);
  }
}

function isPlainObject(value) {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}

function assertNonEmptyString(value, field, maxLength = MAX_ID_LENGTH) {
  assert(
    typeof value === "string" && value.trim().length > 0,
    "INVALID_FIELD",
    `${field} must be a non-empty string.`,
    { field },
  );
  assert(
    value.length <= maxLength,
    "INVALID_FIELD",
    `${field} must be no longer than ${maxLength} characters.`,
    { field, maxLength },
  );
}

function assertUniqueIds(items, collectionName) {
  const seen = new Set();
  for (const item of items) {
    assertNonEmptyString(item?.id, `${collectionName}.id`);
    assert(
      !seen.has(item.id),
      "DUPLICATE_ID",
      `${collectionName} contains duplicate id ${item.id}.`,
      { collection: collectionName, id: item.id },
    );
    seen.add(item.id);
  }
}

function canonicalize(value) {
  if (Array.isArray(value)) {
    return value.map(canonicalize);
  }
  if (isPlainObject(value)) {
    return Object.fromEntries(
      Object.keys(value)
        .sort()
        .map((key) => [key, canonicalize(value[key])]),
    );
  }
  return value;
}

function evaluationIdFor(agreement) {
  const payload = JSON.stringify(canonicalize(agreement));
  const digest = createHash("sha256").update(payload).digest("hex");
  return `eval_${digest.slice(0, 32)}`;
}

function validateAgreement(agreement) {
  assert(isPlainObject(agreement), "INVALID_BODY", "Request body must be an object.");
  assertNonEmptyString(agreement.agreementId, "agreementId", MAX_AGREEMENT_ID_LENGTH);
  assert(isPlainObject(agreement.asset), "INVALID_FIELD", "asset must be an object.", { field: "asset" });
  assertNonEmptyString(agreement.asset.symbol, "asset.symbol");
  assert(
    /^[A-Za-z0-9._-]{1,16}$/.test(agreement.asset.symbol),
    "INVALID_FIELD",
    "asset.symbol contains unsupported characters.",
    { field: "asset.symbol" },
  );
  assert(
    Number.isInteger(agreement.asset.decimals) &&
      agreement.asset.decimals >= 0 &&
      agreement.asset.decimals <= 18,
    "INVALID_FIELD",
    "asset.decimals must be an integer from 0 to 18.",
    { field: "asset.decimals" },
  );
  assert(
    Number.isSafeInteger(agreement.amountAtomic) &&
      agreement.amountAtomic > 0 &&
      agreement.amountAtomic <= MAX_ATOMIC_AMOUNT,
    "INVALID_FIELD",
    `amountAtomic must be a positive integer no greater than ${MAX_ATOMIC_AMOUNT}.`,
    { field: "amountAtomic" },
  );
  assert(Array.isArray(agreement.criteria) && agreement.criteria.length > 0,
    "INVALID_FIELD", "criteria must contain at least one item.", { field: "criteria" });
  assert(Array.isArray(agreement.evidence), "INVALID_FIELD", "evidence must be an array.", { field: "evidence" });
  assert(Array.isArray(agreement.findings), "INVALID_FIELD", "findings must be an array.", { field: "findings" });
  assert(agreement.criteria.length <= MAX_CRITERIA, "INVALID_FIELD", `criteria may contain no more than ${MAX_CRITERIA} items.`, { field: "criteria", maxItems: MAX_CRITERIA });
  assert(agreement.evidence.length <= MAX_EVIDENCE, "INVALID_FIELD", `evidence may contain no more than ${MAX_EVIDENCE} items.`, { field: "evidence", maxItems: MAX_EVIDENCE });
  assert(agreement.findings.length <= MAX_FINDINGS, "INVALID_FIELD", `findings may contain no more than ${MAX_FINDINGS} items.`, { field: "findings", maxItems: MAX_FINDINGS });

  assertUniqueIds(agreement.criteria, "criteria");
  assertUniqueIds(agreement.evidence, "evidence");
  assertUniqueIds(agreement.findings, "findings");

  const criterionIds = new Set(agreement.criteria.map(({ id }) => id));
  const evidenceById = new Map(agreement.evidence.map((item) => [item.id, item]));
  let weightTotal = 0;

  for (const criterion of agreement.criteria) {
    assertNonEmptyString(criterion.description, `criteria.${criterion.id}.description`, MAX_DESCRIPTION_LENGTH);
    assert(
      Number.isInteger(criterion.weight) && criterion.weight > 0 && criterion.weight <= 100,
      "INVALID_FIELD",
      `Criterion ${criterion.id} weight must be an integer from 1 to 100.`,
      { field: "criteria.weight", id: criterion.id },
    );
    assert(
      typeof criterion.critical === "boolean",
      "INVALID_FIELD",
      `Criterion ${criterion.id} critical must be a boolean.`,
      { field: "criteria.critical", id: criterion.id },
    );
    assert(
      Number.isInteger(criterion.minimumEvidence) && criterion.minimumEvidence >= 0,
      "INVALID_FIELD",
      `Criterion ${criterion.id} minimumEvidence must be a non-negative integer.`,
      { field: "criteria.minimumEvidence", id: criterion.id },
    );
    assert(
      criterion.minimumEvidence <= MAX_EVIDENCE,
      "INVALID_FIELD",
      `Criterion ${criterion.id} minimumEvidence must be no greater than ${MAX_EVIDENCE}.`,
      { field: "criteria.minimumEvidence", id: criterion.id, max: MAX_EVIDENCE },
    );
    weightTotal += criterion.weight;
  }

  assert(
    weightTotal === 100,
    "INVALID_CRITERIA_WEIGHT_TOTAL",
    `Criterion weights must total 100; received ${weightTotal}.`,
    { weightTotal },
  );

  for (const item of agreement.evidence) {
    assert(
      criterionIds.has(item.criterionId),
      "UNKNOWN_CRITERION",
      `Evidence ${item.id} references unknown criterion ${item.criterionId}.`,
      { evidenceId: item.id, criterionId: item.criterionId },
    );
    assert(
      ALLOWED_EVIDENCE_KINDS.has(item.kind),
      "INVALID_FIELD",
      `Evidence ${item.id} has unsupported kind ${item.kind}.`,
      { field: "evidence.kind", id: item.id },
    );
    assert(
      typeof item.uri === "string" && item.uri.length <= MAX_URI_LENGTH && /^https:\/\//i.test(item.uri),
      "INVALID_FIELD",
      `Evidence ${item.id} uri must use HTTPS and be no longer than ${MAX_URI_LENGTH} characters.`,
      { field: "evidence.uri", id: item.id, maxLength: MAX_URI_LENGTH },
    );
    assert(
      typeof item.digest === "string" && /^sha256:[a-f0-9]{64}$/i.test(item.digest),
      "INVALID_FIELD",
      `Evidence ${item.id} digest must be a sha256 digest.`,
      { field: "evidence.digest", id: item.id },
    );
    assert(
      ALLOWED_EVIDENCE_RESULTS.has(item.result),
      "INVALID_FIELD",
      `Evidence ${item.id} has unsupported result ${item.result}.`,
      { field: "evidence.result", id: item.id },
    );
  }

  const evaluatorCriterionPairs = new Set();
  for (const finding of agreement.findings) {
    assert(
      criterionIds.has(finding.criterionId),
      "UNKNOWN_CRITERION",
      `Finding ${finding.id} references unknown criterion ${finding.criterionId}.`,
      { findingId: finding.id, criterionId: finding.criterionId },
    );
    assertNonEmptyString(finding.evaluator, `findings.${finding.id}.evaluator`);
    const evaluatorCriterionKey = `${finding.criterionId}\u0000${finding.evaluator.trim().toLowerCase()}`;
    assert(
      !evaluatorCriterionPairs.has(evaluatorCriterionKey),
      "DUPLICATE_EVALUATOR_FINDING",
      `Evaluator ${finding.evaluator} submitted more than one finding for criterion ${finding.criterionId}.`,
      { evaluator: finding.evaluator, criterionId: finding.criterionId },
    );
    evaluatorCriterionPairs.add(evaluatorCriterionKey);
    assertNonEmptyString(finding.rationale, `findings.${finding.id}.rationale`, MAX_RATIONALE_LENGTH);
    assert(
      Number.isFinite(finding.score) && finding.score >= 0 && finding.score <= 100,
      "INVALID_FIELD",
      `Finding ${finding.id} score must be from 0 to 100.`,
      { field: "findings.score", id: finding.id },
    );
    assert(
      Number.isFinite(finding.confidence) && finding.confidence > 0 && finding.confidence <= 1,
      "INVALID_FIELD",
      `Finding ${finding.id} confidence must be greater than 0 and at most 1.`,
      { field: "findings.confidence", id: finding.id },
    );
    assert(
      Array.isArray(finding.evidenceIds) && finding.evidenceIds.length > 0,
      "INVALID_FIELD",
      `Finding ${finding.id} must cite at least one evidence item.`,
      { field: "findings.evidenceIds", id: finding.id },
    );
    assert(
      finding.evidenceIds.length <= MAX_EVIDENCE,
      "INVALID_FIELD",
      `Finding ${finding.id} may cite no more than ${MAX_EVIDENCE} evidence items.`,
      { field: "findings.evidenceIds", id: finding.id, maxItems: MAX_EVIDENCE },
    );
    for (const evidenceId of finding.evidenceIds) {
      assertNonEmptyString(evidenceId, `findings.${finding.id}.evidenceIds`);
      const evidence = evidenceById.get(evidenceId);
      assert(
        evidence,
        "UNKNOWN_EVIDENCE",
        `Finding ${finding.id} references unknown evidence ${evidenceId}.`,
        { findingId: finding.id, evidenceId },
      );
      assert(
        evidence.criterionId === finding.criterionId,
        "CROSS_CRITERION_EVIDENCE",
        `Finding ${finding.id} cites evidence from another criterion.`,
        { findingId: finding.id, evidenceId },
      );
    }
  }

  const policy = agreement.policy ?? {};
  const conflictSpread = policy.conflictSpread ?? 35;
  const criticalFailureCapPercent = policy.criticalFailureCapPercent ?? 0;
  assert(
    Number.isFinite(conflictSpread) && conflictSpread >= 0 && conflictSpread <= 100,
    "INVALID_FIELD",
    "policy.conflictSpread must be from 0 to 100.",
    { field: "policy.conflictSpread" },
  );
  assert(
    Number.isFinite(criticalFailureCapPercent) &&
      criticalFailureCapPercent >= 0 &&
      criticalFailureCapPercent <= 100,
    "INVALID_FIELD",
    "policy.criticalFailureCapPercent must be from 0 to 100.",
    { field: "policy.criticalFailureCapPercent" },
  );

  return { conflictSpread, criticalFailureCapPercent };
}

function weightedScore(findings) {
  const totalConfidence = findings.reduce((sum, item) => sum + item.confidence, 0);
  return Math.round(
    findings.reduce((sum, item) => sum + item.score * item.confidence, 0) /
      totalConfidence,
  );
}

export function evaluateAgreement(agreement) {
  const policy = validateAgreement(agreement);
  const reasons = new Set();
  let requiresManualReview = false;
  let criticalFailure = false;

  const criteria = agreement.criteria.map((criterion) => {
    const evidence = agreement.evidence.filter(
      (item) => item.criterionId === criterion.id,
    );
    const findings = agreement.findings.filter(
      (item) => item.criterionId === criterion.id,
    );
    const failedEvidence = evidence.some((item) => item.result === "fail");
    const hasSupportingEvidence = evidence.some((item) => item.result === "pass");
    const enoughEvidence = evidence.length >= criterion.minimumEvidence;
    const scores = findings.map(({ score }) => score);
    const conflict =
      scores.length > 1 && Math.max(...scores) - Math.min(...scores) >= policy.conflictSpread;

    let score = findings.length > 0 ? weightedScore(findings) : 0;
    const criterionReasons = [];

    if (!enoughEvidence) {
      score = 0;
      criterionReasons.push("INSUFFICIENT_EVIDENCE");
      reasons.add("INSUFFICIENT_EVIDENCE");
    }
    if (findings.length === 0) {
      score = 0;
      criterionReasons.push("MISSING_FINDING");
      reasons.add("MISSING_FINDING");
    }
    if (!hasSupportingEvidence) {
      score = 0;
      criterionReasons.push("NO_SUPPORTING_EVIDENCE");
      reasons.add("NO_SUPPORTING_EVIDENCE");
    }
    if (failedEvidence) {
      score = Math.min(score, 49);
      criterionReasons.push("CONTRADICTING_EVIDENCE");
      reasons.add("CONTRADICTING_EVIDENCE");
      if (criterion.critical) {
        criticalFailure = true;
      }
    }
    if (conflict) {
      requiresManualReview = true;
      criterionReasons.push("EVALUATOR_CONFLICT");
      reasons.add("EVALUATOR_CONFLICT");
    }
    if (criterion.critical && score < 50) {
      criticalFailure = true;
    }

    const allocatedAtomic = Math.floor(
      (agreement.amountAtomic * criterion.weight) / 100,
    );
    const earnedAtomic = Math.floor((allocatedAtomic * score) / 100);

    return {
      id: criterion.id,
      description: criterion.description,
      critical: criterion.critical,
      weight: criterion.weight,
      score,
      allocatedAtomic,
      earnedAtomic,
      evidenceCount: evidence.length,
      findingCount: findings.length,
      status: conflict
        ? "disputed"
        : score >= 100
          ? "satisfied"
          : score > 0
            ? "partial"
            : "unsatisfied",
      reasonCodes: criterionReasons,
    };
  });

  if (criticalFailure) {
    reasons.add("CRITICAL_CRITERION_FAILED");
  }

  let recommendedReleaseAtomic = criteria.reduce(
    (sum, criterion) => sum + criterion.earnedAtomic,
    0,
  );
  if (criticalFailure) {
    const capAtomic = Math.floor(
      (agreement.amountAtomic * policy.criticalFailureCapPercent) / 100,
    );
    recommendedReleaseAtomic = Math.min(recommendedReleaseAtomic, capAtomic);
  }

  if (requiresManualReview) {
    return {
      schemaVersion: 1,
      evaluationId: evaluationIdFor(agreement),
      agreementId: agreement.agreementId,
      decision: "manual_review",
      asset: agreement.asset,
      amountAtomic: agreement.amountAtomic,
      recommendedReleaseAtomic: null,
      recommendedHoldAtomic: null,
      settlementRatioBps: null,
      criteria,
      reasonCodes: [...reasons].sort(),
    };
  }

  const recommendedHoldAtomic = agreement.amountAtomic - recommendedReleaseAtomic;
  const settlementRatioBps = Math.floor(
    (recommendedReleaseAtomic * 10_000) / agreement.amountAtomic,
  );
  const decision =
    recommendedReleaseAtomic === agreement.amountAtomic
      ? "release_full"
      : recommendedReleaseAtomic > 0
        ? "release_partial"
        : "hold";

  return {
    schemaVersion: 1,
    evaluationId: evaluationIdFor(agreement),
    agreementId: agreement.agreementId,
    decision,
    asset: agreement.asset,
    amountAtomic: agreement.amountAtomic,
    recommendedReleaseAtomic,
    recommendedHoldAtomic,
    settlementRatioBps,
    criteria,
    reasonCodes: [...reasons].sort(),
  };
}
