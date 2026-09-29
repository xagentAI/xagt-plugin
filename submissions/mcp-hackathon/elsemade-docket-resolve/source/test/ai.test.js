import assert from "node:assert/strict";
import test from "node:test";

import { FixtureReviewProvider, GeminiReviewProvider, OpenAIReviewProvider, createReviewProvider } from "../src/ai/providers.js";
import { ReviewValidationError, reviewAgreement } from "../src/ai/review.js";

function agreement() {
  return {
    agreementId: "ai_case_001",
    amountAtomic: 100_000_000,
    asset: { symbol: "USDC", decimals: 6 },
    criteria: [
      {
        id: "delivery",
        description: "The agreed artifact was delivered.",
        weight: 100,
        critical: true,
        minimumEvidence: 1,
      },
    ],
    evidence: [
      {
        id: "e_delivery",
        criterionId: "delivery",
        kind: "artifact",
        uri: "https://example.com/artifact",
        digest: `sha256:${"a".repeat(64)}`,
        result: "pass",
      },
    ],
    findings: [],
  };
}

test("review findings are cited and flow through the settlement kernel", async () => {
  const review = await reviewAgreement({
    agreement: agreement(),
    evidenceContent: [{ id: "e_delivery", content: "The artifact is present." }],
    provider: new FixtureReviewProvider(),
  });

  assert.equal(review.readyToResolve, true);
  assert.equal(review.requiresHumanReview, false);
  assert.equal(review.findings.length, 1);
  assert.deepEqual(review.findings[0].evidenceIds, ["e_delivery"]);
  assert.equal(review.evaluation.recommendedReleaseAtomic, 100_000_000);
  assert.equal(review.evaluation.recommendedHoldAtomic, 0);
});

test("missing evidence fails closed without inventing a finding", async () => {
  const input = agreement();
  input.evidence = [];
  const review = await reviewAgreement({
    agreement: input,
    provider: new FixtureReviewProvider(),
  });

  assert.equal(review.readyToResolve, false);
  assert.equal(review.requiresHumanReview, true);
  assert.equal(review.findings.length, 0);
  assert.equal(review.reviews[0].score, null);
  assert.equal(review.evaluation.recommendedReleaseAtomic, 0);
});

test("review rejects duplicate and oversized evidence notes before calling the provider", async () => {
  const provider = {
    name: "test-provider",
    model: "test-model",
    promptVersion: "test-v1",
    reviewCriterion: async () => {
      throw new Error("The provider should not be called.");
    },
  };
  await assert.rejects(
    reviewAgreement({
      agreement: agreement(),
      evidenceContent: [{ id: "e_delivery", content: "one" }, { id: "e_delivery", content: "two" }],
      provider,
    }),
    (error) => error instanceof ReviewValidationError && error.code === "INVALID_EVIDENCE_CONTENT",
  );

  const largeAgreement = agreement();
  largeAgreement.evidence = Array.from({ length: 11 }, (_, index) => ({
    ...largeAgreement.evidence[0],
    id: `e_delivery_${index}`,
  }));
  await assert.rejects(
    reviewAgreement({
      agreement: largeAgreement,
      evidenceContent: largeAgreement.evidence.map((item) => ({ id: item.id, content: "x".repeat(24_000) })),
      provider,
    }),
    (error) => error instanceof ReviewValidationError && error.code === "EVIDENCE_CONTENT_TOO_LARGE",
  );
});

test("invalid provider evidence citations become a review failure", async () => {
  const provider = {
    name: "test-provider",
    model: "test-model",
    promptVersion: "test-v1",
    reviewCriterion: async () => ({
      schemaVersion: 1,
      criterionId: "delivery",
      verdict: "satisfied",
      score: 100,
      confidence: 1,
      evidenceCitations: [
        {
          evidenceId: "not-supplied",
          claim: "Unsupported claim",
          support: "Unsupported evidence",
        },
      ],
      missingEvidence: [],
      contradictions: [],
      rationale: "This should not be accepted.",
      requirementsApplied: ["The agreed artifact was delivered."],
      requirementsRejected: [],
    }),
  };

  const review = await reviewAgreement({ agreement: agreement(), provider });
  assert.equal(review.readyToResolve, false);
  assert.deepEqual(review.failures, [
    { criterionId: "delivery", code: "AI_EVIDENCE_MISMATCH" },
  ]);
  assert.equal(review.findings.length, 0);
});

test("OpenAI adapter requests strict structured output without provider storage", async () => {
  let request;
  const provider = new OpenAIReviewProvider({
    apiKey: "test-key",
    model: "test-model",
    fetchImpl: async (url, options) => {
      request = { url, options, body: JSON.parse(options.body) };
      return new Response(
        JSON.stringify({
          output_text: JSON.stringify({
            schemaVersion: 1,
            criterionId: "delivery",
            verdict: "satisfied",
            score: 100,
            confidence: 0.9,
            evidenceCitations: [
              { evidenceId: "e_delivery", claim: "Delivered", support: "Artifact is present." },
            ],
            missingEvidence: [],
            contradictions: [],
            rationale: "The artifact is present.",
            requirementsApplied: ["The agreed artifact was delivered."],
            requirementsRejected: [],
          }),
        }),
        { status: 200, headers: { "content-type": "application/json" } },
      );
    },
  });

  const finding = await provider.reviewCriterion({
    criterion: agreement().criteria[0],
    evidence: agreement().evidence,
  });

  assert.equal(request.url, "https://api.openai.com/v1/responses");
  assert.equal(request.options.headers.authorization, "Bearer test-key");
  assert.equal(request.body.store, false);
  assert.equal(request.body.text.format.type, "json_schema");
  assert.equal(request.body.text.format.strict, true);
  assert.equal(finding.criterionId, "delivery");
});

test("Gemini adapter requests schema-constrained JSON and validates the result", async () => {
  let request;
  const provider = new GeminiReviewProvider({
    apiKey: "test-gemini-key",
    fetchImpl: async (url, options) => {
      request = { url, options, body: JSON.parse(options.body) };
      return new Response(JSON.stringify({
        candidates: [{
          content: {
            parts: [{
              text: JSON.stringify({
                schemaVersion: 1,
                criterionId: "delivery",
                verdict: "satisfied",
                score: 100,
                confidence: 0.92,
                evidenceCitations: [
                  { evidenceId: "e_delivery", claim: "Delivered", support: "Artifact is present." },
                ],
                missingEvidence: [],
                contradictions: [],
                rationale: "The artifact is present.",
                requirementsApplied: ["The agreed artifact was delivered."],
                requirementsRejected: [],
              }),
            }],
          },
        }],
      }), { status: 200, headers: { "content-type": "application/json" } });
    },
  });

  const finding = await provider.reviewCriterion({
    criterion: agreement().criteria[0],
    evidence: agreement().evidence,
  });

  assert.match(request.url, /generativelanguage\.googleapis\.com\/v1beta\/models\/gemini-3\.1-flash-lite:generateContent$/);
  assert.equal(request.options.headers["x-goog-api-key"], "test-gemini-key");
  assert.doesNotMatch(request.url, /[?&]key=/);
  assert.equal(request.body.generationConfig.responseMimeType, "application/json");
  const responseSchema = request.body.generationConfig.responseSchema;
  assert.equal(responseSchema.type, "object");
  assert.equal("additionalProperties" in responseSchema, false);
  assert.equal(responseSchema.properties.schemaVersion.type, "integer");
  assert.equal("enum" in responseSchema.properties.schemaVersion, false);
  assert.deepEqual(responseSchema.properties.score.anyOf, [
    { type: "number", minimum: 0, maximum: 100 },
    { type: "null" },
  ]);
  assert.equal(finding.criterionId, "delivery");
  assert.equal(finding.confidence, 0.92);
});

test("Gemini is the runtime default and requires an explicit key", () => {
  assert.equal(createReviewProvider({ GEMINI_API_KEY: "present" }).name, "gemini");
  assert.equal(createReviewProvider({ DOCKET_AI_PROVIDER: "fixture" }).name, "fixture");
  assert.throws(
    () => createReviewProvider({}),
    /requires GEMINI_API_KEY/,
  );
});
