export function openApiDocument(origin: string) {
  return {
    openapi: "3.1.0",
    info: {
      title: "BountyProof API",
      version: "0.1.0",
      description:
        "Evidence-first preflight for public GitHub bounty issues. Responses never confirm payout and issue content is always treated as untrusted.",
      license: { name: "MIT", identifier: "MIT" },
    },
    servers: [{ url: origin }],
    paths: {
      "/health": {
        get: {
          summary: "Deployment health and source commit",
          operationId: "getHealth",
          responses: { "200": { description: "Healthy deployment" } },
        },
      },
      "/v1/check": {
        post: {
          summary: "Preflight one public GitHub bounty issue",
          operationId: "checkBounty",
          requestBody: {
            required: true,
            content: {
              "application/json": {
                schema: {
                  type: "object",
                  additionalProperties: false,
                  required: ["issueUrl"],
                  properties: {
                    issueUrl: {
                      type: "string",
                      format: "uri",
                      examples: ["https://github.com/owner/repository/issues/123"],
                    },
                    expectedRewardUsd: { type: ["number", "null"], minimum: 0.01, maximum: 10_000_000 },
                    expectedPlatform: { type: ["string", "null"], maxLength: 80 },
                  },
                },
              },
            },
          },
          responses: {
            "200": { description: "Current evidence and a STOP, HOLD, or confirmation-first verdict" },
            "400": { description: "Invalid request" },
            "404": { description: "GitHub repository or issue not found" },
            "429": { description: "GitHub upstream rate limit reached" },
            "502": { description: "GitHub upstream unavailable" },
          },
        },
      },
    },
  };
}
