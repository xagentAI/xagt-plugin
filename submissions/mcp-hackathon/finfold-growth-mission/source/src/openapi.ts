export function openApiDocument(baseUrl: string): Record<string, unknown> {
  const bearer = [{ bearerAuth: [] }];
  const json = (schema: Record<string, unknown>) => ({
    "application/json": { schema },
  });
  const errorResponses = {
    "400": { description: "Invalid request", content: json({ $ref: "#/components/schemas/Error" }) },
    "401": { description: "Missing or invalid review key", content: json({ $ref: "#/components/schemas/Error" }) },
    "403": { description: "Scope denied or key expired", content: json({ $ref: "#/components/schemas/Error" }) },
    "429": { description: "Daily key allowance exhausted", content: json({ $ref: "#/components/schemas/Error" }) },
  };
  return {
    openapi: "3.1.0",
    info: {
      title: "Finfold Growth Mission API",
      version: "1.1.0",
      description: "Turn one public business URL into one evidence-bound, trackable growth mission and close the loop with real outcomes.",
      contact: { email: "support@finfold.app" },
    },
    servers: [{ url: baseUrl }],
    paths: {
      "/health": {
        get: {
          summary: "Deployment health and source commit",
          security: [],
          responses: { "200": { description: "Healthy", content: json({ $ref: "#/components/schemas/Health" }) } },
        },
      },
      "/.well-known/xagent-verification.json": {
        get: {
          summary: "Bind the deployed service to the public review commit",
          security: [],
          responses: { "200": { description: "Deployment proof", content: json({ $ref: "#/components/schemas/Proof" }) } },
        },
      },
      "/v1/capability": {
        get: { summary: "Describe product, pricing, retention, and side-effect boundaries", security: [], responses: { "200": { description: "Capability boundary" } } },
      },
      "/v1/usage": {
        get: {
          summary: "Read the review key's UTC-day usage and expiry",
          description: "Required scope: mission:read.",
          security: bearer,
          responses: { "200": { description: "Key usage" }, ...errorResponses },
        },
      },
      "/v1/missions": {
        post: {
          summary: "Create one growth mission",
          description: "Required scope: mission:create. Persists a mission but never publishes content or mutates an external account.",
          security: bearer,
          parameters: [{ $ref: "#/components/parameters/IdempotencyKey" }],
          requestBody: { required: true, content: { "application/json": { schema: { $ref: "#/components/schemas/CreateMission" } } } },
          responses: {
            "201": { description: "Mission created", content: json({ $ref: "#/components/schemas/MissionState" }) },
            "409": { description: "Idempotency conflict or request in progress", content: json({ $ref: "#/components/schemas/Error" }) },
            "422": { description: "Source, landing page, evidence, or quality rejected", content: json({ $ref: "#/components/schemas/Error" }) },
            ...errorResponses,
          },
        },
      },
      "/v1/missions/{id}": {
        get: {
          summary: "Get mission, attribution, verdict, and next action",
          description: "Required scope: mission:read. Read-only.",
          security: bearer,
          parameters: [{ $ref: "#/components/parameters/MissionId" }],
          responses: {
            "200": { description: "Mission state", content: json({ $ref: "#/components/schemas/MissionState" }) },
            "404": { description: "Not found", content: json({ $ref: "#/components/schemas/Error" }) },
            ...errorResponses,
          },
        },
      },
      "/v1/missions/{id}/outcomes": {
        post: {
          summary: "Record one attributable outcome",
          description: "Required scope: outcome:write. Writes one deduplicated event inside the mission measurement window; no external side effect.",
          security: bearer,
          parameters: [
            { $ref: "#/components/parameters/MissionId" },
            { $ref: "#/components/parameters/IdempotencyKey" },
          ],
          requestBody: { required: true, content: { "application/json": { schema: { $ref: "#/components/schemas/Outcome" } } } },
          responses: {
            "200": { description: "Outcome accepted and verdict recomputed" },
            "404": { description: "Mission not found", content: json({ $ref: "#/components/schemas/Error" }) },
            "409": { description: "Idempotency conflict", content: json({ $ref: "#/components/schemas/Error" }) },
            "422": { description: "Outcome outside window or revenue currency mismatch", content: json({ $ref: "#/components/schemas/Error" }) },
            ...errorResponses,
          },
        },
      },
      "/r/{trackingCode}": {
        get: {
          summary: "Count one anonymous raw click and redirect to the validated destination",
          security: [],
          parameters: [{ in: "path", name: "trackingCode", required: true, schema: { type: "string", pattern: "^[a-z0-9]{36}$" } }],
          responses: { "302": { description: "Redirect with Finfold UTM parameters" }, "404": { description: "Tracking link not found" } },
        },
      },
      "/mcp": {
        post: {
          summary: "Stateless Streamable HTTP MCP endpoint",
          description: "Bearer authentication is required for tools/list and tools/call. initialize, ping, and notifications are public protocol operations.",
          security: bearer,
          responses: { "200": { description: "JSON-RPC or MCP tool response" }, "202": { description: "Notification accepted" }, ...errorResponses },
        },
      },
    },
    components: {
      securitySchemes: { bearerAuth: { type: "http", scheme: "bearer" } },
      parameters: {
        IdempotencyKey: { in: "header", name: "Idempotency-Key", required: true, schema: { type: "string", minLength: 8, maxLength: 128, pattern: "^[A-Za-z0-9._:-]+$" } },
        MissionId: { in: "path", name: "id", required: true, schema: { type: "string", pattern: "^gm_[a-z0-9]{24}$" } },
      },
      schemas: {
        Health: {
          type: "object",
          additionalProperties: false,
          required: ["status", "commit"],
          properties: { status: { const: "ok" }, commit: { type: "string", pattern: "^[0-9a-f]{40}$" } },
        },
        Proof: {
          type: "object",
          additionalProperties: false,
          required: ["schemaVersion", "slug", "commit"],
          properties: {
            schemaVersion: { const: 1 },
            slug: { const: "finfold-growth-mission" },
            commit: { type: "string", pattern: "^[0-9a-f]{40}$" },
          },
        },
        Error: {
          type: "object",
          required: ["error"],
          properties: {
            error: {
              type: "object",
              required: ["code", "message", "retryable", "requestId"],
              properties: {
                code: { type: "string" },
                message: { type: "string" },
                retryable: { type: "boolean" },
                requestId: { type: "string", format: "uuid" },
              },
            },
          },
        },
        CreateMission: {
          type: "object",
          additionalProperties: false,
          required: ["sourceUrl", "objective"],
          properties: {
            sourceUrl: { type: "string", format: "uri" },
            objective: { type: "string", enum: ["leads", "signups", "purchases", "revenue"] },
            platform: { type: "string", enum: ["auto", "linkedin", "x", "reddit", "xiaohongshu", "wechat"], default: "auto" },
            locale: { type: "string", default: "en" },
            targetValue: { type: "number", exclusiveMinimum: 0, default: 1 },
            targetCurrency: { type: "string", minLength: 3, maxLength: 3, default: "USD", description: "Revenue missions only." },
            landingPage: { type: "string", format: "uri", pattern: "^https://", description: "Source host, subdomain, or canonical www/apex equivalent only." },
          },
        },
        Outcome: {
          type: "object",
          additionalProperties: false,
          required: ["eventId", "type"],
          properties: {
            eventId: { type: "string" },
            type: { type: "string", enum: ["lead", "signup", "purchase", "revenue"] },
            quantity: { type: "number", exclusiveMinimum: 0, default: 1 },
            value: { type: "number", minimum: 0 },
            currency: { type: "string", minLength: 3, maxLength: 3 },
            occurredAt: { type: "string", format: "date-time" },
          },
        },
        MissionState: {
          type: "object",
          required: ["mission", "asset", "evidence", "claimMap", "validation", "tracking", "provenance", "sideEffects"],
          properties: {
            mission: { type: "object", description: "Exactly one mission, objective, target, window, audience, and hypothesis." },
            asset: { type: "object", description: "Exactly one publishable platform-native asset with tracked CTA." },
            evidence: { type: "array", items: { type: "object" }, description: "Canonical source excerpts with stable evidence and section IDs." },
            claimMap: { type: "array", items: { type: "object" }, description: "Exact claim-to-evidence links." },
            validation: { type: "object" },
            tracking: { type: "object" },
            attribution: { type: "object" },
            outcome: { type: "object" },
            provenance: { type: "object" },
            sideEffects: { type: "object" },
          },
        },
      },
    },
  };
}
