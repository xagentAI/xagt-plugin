export function openApiDocument(baseUrl: string): Record<string, unknown> {
  const bearer = [{ bearerAuth: [] }];
  return {
    openapi: "3.1.0",
    info: {
      title: "Finfold Growth Mission API",
      version: "1.0.0",
      description: "Turn one public business URL into one evidence-bound, trackable growth mission and close the loop with real outcomes.",
      contact: { email: "support@finfold.app" },
    },
    servers: [{ url: baseUrl }],
    paths: {
      "/health": { get: { summary: "Deployment health and source commit", responses: { "200": { description: "Healthy" } } } },
      "/v1/missions": {
        post: {
          summary: "Create one growth mission",
          security: bearer,
          parameters: [{ in: "header", name: "Idempotency-Key", required: true, schema: { type: "string" } }],
          requestBody: { required: true, content: { "application/json": { schema: { $ref: "#/components/schemas/CreateMission" } } } },
          responses: { "201": { description: "Mission created" }, "409": { description: "Idempotency conflict" }, "422": { description: "Source or evidence rejected" } },
        },
      },
      "/v1/missions/{id}": {
        get: {
          summary: "Get mission, attribution, verdict, and next action",
          security: bearer,
          parameters: [{ in: "path", name: "id", required: true, schema: { type: "string" } }],
          responses: { "200": { description: "Mission state" }, "404": { description: "Not found" } },
        },
      },
      "/v1/missions/{id}/outcomes": {
        post: {
          summary: "Record one attributable outcome",
          security: bearer,
          parameters: [
            { in: "path", name: "id", required: true, schema: { type: "string" } },
            { in: "header", name: "Idempotency-Key", required: true, schema: { type: "string" } },
          ],
          requestBody: { required: true, content: { "application/json": { schema: { $ref: "#/components/schemas/Outcome" } } } },
          responses: { "200": { description: "Outcome accepted and verdict recomputed" } },
        },
      },
      "/mcp": { post: { summary: "Stateless Streamable HTTP MCP endpoint", responses: { "200": { description: "JSON-RPC response" } } } },
    },
    components: {
      securitySchemes: { bearerAuth: { type: "http", scheme: "bearer" } },
      schemas: {
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
            landingPage: { type: "string", format: "uri" },
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
      },
    },
  };
}
