const errorResponse = { description: 'Structured error; no submitted cell values or partial output.', content: { 'application/json': { schema: { $ref: '#/components/schemas/Error' } } } };
export const openapi = {
  openapi: '3.1.0',
  info: { title: 'SchemaBridge', version: '0.1.0', description: 'Bounded stateless CSV/JSON field mapping. JSON numbers are parsed as IEEE-754 before validation and may already be rounded; integer mappings accept parsed safe integers or strict decimal integer strings. Use string input when exact digits must be validated. Conversion counts start after parsing. Empty CSV cells are empty strings, never implicit null. No CPU-performance claim.' },
  paths: {
    '/': { get: { operationId: 'serviceHomepage', responses: { '200': { description: 'Human-readable English homepage and live CSV example.', content: { 'text/html': { schema: { type: 'string' } } } } } } },
    '/docs': { get: { operationId: 'apiGuide', responses: { '200': { description: 'English API guide, examples and links to machine-readable contracts.', content: { 'text/html': { schema: { type: 'string' } } } } } } },
    '/status': { get: { operationId: 'statusPage', responses: { '200': { description: 'English status page that checks the live JSON health endpoint.', content: { 'text/html': { schema: { type: 'string' } } } } } } },
    '/v1': { get: { operationId: 'apiIndex', responses: { '200': { description: 'API base description and capability request method/path.' } } } },
    '/v1/transform': { post: {
      operationId: 'transformRecords',
      summary: 'Atomically map up to 100 flat records using up to 20 explicit field mappings.',
      description: '32 KiB UTF-8 JSON envelope. CSV is a string inside data, with unique headers and comma delimiters. LF/CRLF, quoted cells and escaped quotes are supported. No implicit whitespace trimming. Unmapped input fields are ignored after structural validation. Missing optional fields are omitted. Response budget 64 KiB with 256-byte envelope reserve.',
      requestBody: { required: true, content: { 'application/json': { schema: { $ref: '#/components/schemas/TransformInput' } } } },
      responses: {
        '200': { description: 'All rows valid.', content: { 'application/json': { schema: { type: 'object', required: ['ok', 'data', 'summary'], properties: { ok: { const: true }, data: { type: 'array', items: { type: 'object' } }, summary: { type: 'object', properties: { inputRows: { type: 'integer' }, outputRows: { type: 'integer' }, mappedFields: { type: 'integer' }, convertedCells: { type: 'integer' } } } } } } } },
        '400': errorResponse, '413': errorResponse, '415': errorResponse, '422': errorResponse, '500': errorResponse,
      },
    } },
    '/health': { get: { operationId: 'health', responses: {
      '200': { description: 'Configured reviewed commit, supplied by the deployment operator.', content: { 'application/json': { schema: { type: 'object', required: ['status', 'commit'], properties: { status: { const: 'ok' }, commit: { type: 'string', pattern: '^[a-fA-F0-9]{40}$' } } } } } },
      '503': errorResponse,
    } } },
    '/.well-known/xagent-verification.json': { get: { operationId: 'deploymentProof', responses: {
      '200': { description: 'X-Agent slug/commit binding; not independent build provenance.', content: { 'application/json': { schema: { type: 'object', required: ['schemaVersion', 'slug', 'commit'], properties: { schemaVersion: { const: 1 }, slug: { type: 'string' }, commit: { type: 'string', pattern: '^[a-fA-F0-9]{40}$' } } } } } },
      '503': errorResponse,
    } } },
    '/openapi.json': { get: { operationId: 'openapi', responses: { '200': { description: 'This OpenAPI document.' } } } },
  },
  components: { schemas: {
    Field: { type: 'object', description: 'Source and target use literal top-level field names, at most 64 UTF-16 code units. Reserved names __proto__, prototype and constructor are rejected. Targets must be unique.', additionalProperties: false, required: ['source', 'target', 'type'], properties: {
      source: { type: 'string', minLength: 1, maxLength: 64 }, target: { type: 'string', minLength: 1, maxLength: 64 },
      type: { enum: ['string', 'integer', 'number', 'boolean'] }, required: { type: 'boolean', default: true }, nullable: { type: 'boolean', default: false }, trim: { type: 'boolean', default: false },
    } },
    TransformInput: { type: 'object', additionalProperties: false, required: ['format', 'data', 'schema'], properties: {
      format: { enum: ['json', 'csv'] }, data: { oneOf: [{ type: 'string' }, { type: 'array', maxItems: 100, items: { type: 'object', maxProperties: 20, additionalProperties: { type: ['string', 'number', 'boolean', 'null'] } } }] },
      schema: { type: 'array', minItems: 1, maxItems: 20, items: { $ref: '#/components/schemas/Field' } },
    }, allOf: [
      { if: { properties: { format: { const: 'json' } } }, then: { properties: { data: { type: 'array' } } } },
      { if: { properties: { format: { const: 'csv' } } }, then: { properties: { data: { type: 'string', minLength: 1 } } } },
    ] },
    Error: { type: 'object', required: ['ok', 'error'], properties: { ok: { const: false }, error: { type: 'object', required: ['code', 'message'], properties: { code: { type: 'string' }, message: { type: 'string' }, details: { description: 'Optional row/schema locations; bounded field details and total count on validation errors.' } } } } },
  } },
};
