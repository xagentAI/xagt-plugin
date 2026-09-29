import * as z from 'zod';
import { ERROR_CODES } from '@/lib/errors';
import { inlineRegimeSchema, inlineTrackRecordSchema } from '@/lib/sources/inline/adapter';

/**
 * The OpenAPI 3.1 description of the REST surface.
 *
 * Request schemas are generated from the same Zod definitions the routes validate
 * against, so the published contract cannot drift from the enforced one. Response
 * shapes and prose are written here, because a generated description of a response is
 * accurate and useless — a caller needs to know what a field MEANS.
 */

const jsonSchemaOf = (schema: z.ZodType) => z.toJSONSchema(schema, { io: 'input', target: 'draft-2020-12' });

const errorResponse = {
  type: 'object',
  required: ['error'],
  properties: {
    error: {
      type: 'object',
      required: ['code', 'message', 'retryable'],
      properties: {
        code: { type: 'string', enum: [...ERROR_CODES], description: 'Stable, machine-readable failure code.' },
        message: { type: 'string' },
        retryable: { type: 'boolean', description: 'Whether repeating the identical request can succeed.' },
        remedy: { type: 'string', description: 'What to do instead. Written to be actionable by an agent.' },
        details: { type: 'object', additionalProperties: true },
      },
    },
  },
} as const;

const selectorSchema = {
  oneOf: [
    {
      type: 'object',
      required: ['source'],
      properties: {
        source: { const: 'olaxbt-nexus' },
        symbol: { type: 'string', default: 'BTC/USDT', description: 'Market the strategy trades.' },
      },
      description: 'Analyse the OlaXBT Nexus strategy bound to the supplied API key.',
    },
    {
      type: 'object',
      required: ['source', 'trackRecord'],
      properties: {
        source: { const: 'inline' },
        trackRecord: jsonSchemaOf(inlineTrackRecordSchema),
        regimes: jsonSchemaOf(inlineRegimeSchema),
      },
      description: 'Analyse an equity curve supplied directly, from any venue or backtest.',
    },
  ],
} as const;

function analysisPath(summary: string, description: string, optionProperties: Record<string, unknown>) {
  return {
    post: {
      summary,
      description,
      security: [{ nexusKey: [] }, {}],
      requestBody: {
        required: true,
        content: {
          'application/json': {
            schema: {
              type: 'object',
              required: ['selector'],
              properties: {
                selector: selectorSchema,
                options: { type: 'object', properties: optionProperties, additionalProperties: false },
              },
            },
          },
        },
      },
      responses: {
        '200': {
          description: 'The analysis. Wrapped as `{ data, meta }`; `meta` carries the request id and build commit.',
          content: { 'application/json': { schema: { type: 'object' } } },
        },
        '401': { description: 'No credentials supplied and no demo key configured.', content: { 'application/json': { schema: errorResponse } } },
        '403': { description: 'Rejected `Origin`.', content: { 'application/json': { schema: errorResponse } } },
        '409': { description: 'The upstream strategy has published nothing yet.', content: { 'application/json': { schema: errorResponse } } },
        '422': { description: 'Well-formed request, but the data cannot support an answer.', content: { 'application/json': { schema: errorResponse } } },
        '429': { description: 'Demo rate limit reached.', content: { 'application/json': { schema: errorResponse } } },
        '503': { description: 'The upstream data service is unavailable.', content: { 'application/json': { schema: errorResponse } } },
      },
    },
  };
}

export function buildOpenApiDocument(origin: string) {
  return {
    openapi: '3.1.0',
    info: {
      title: 'Regimen',
      version: '1.0.0',
      summary: 'Is this trading track record distinguishable from luck, and where does the edge live?',
      description:
        'Regimen takes an equity curve — from an OlaXBT Nexus strategy or supplied directly — and reports what the evidence actually supports: the Probabilistic Sharpe Ratio, the Deflated Sharpe Ratio, the Minimum Track Record Length, a bootstrap interval, and a regime-conditional breakdown with a permutation test on the spread. It frequently answers that the evidence is too thin. That is the intended output, not a failure.\n\nIt does not trade, hold funds, custody keys or sign anything, and it performs no security, audit or compliance analysis.',
      license: { name: 'MIT', identifier: 'MIT' },
    },
    servers: [{ url: origin }],
    components: {
      securitySchemes: {
        nexusKey: {
          type: 'apiKey',
          in: 'header',
          name: 'x-nexus-key',
          description:
            'An OlaXBT Nexus API key, issued in Nexus Studio under Profile → API keys. Required only for `source: olaxbt-nexus`. When omitted, a deployment-configured demo key is used if present, under a shared rate limit. Never stored, never logged.',
        },
      },
      schemas: { Error: errorResponse },
    },
    paths: {
      '/api/health': {
        get: {
          summary: 'Liveness and build binding',
          description:
            'Reports `status` and the exact 40-character commit this deployment was built from. Deliberately free of dependencies: a third-party outage must never make a healthy service look dead.',
          responses: { '200': { description: 'Alive.' } },
        },
      },
      '/.well-known/xagent-verification.json': {
        get: {
          summary: 'Deployment proof',
          description: 'Binds this origin to one submission slug and one commit.',
          responses: { '200': { description: 'The proof document.' } },
        },
      },
      '/api/v1/status': {
        get: {
          summary: 'Dependency health',
          description:
            'Upstream reachability, whether a demo key is configured, and point-in-time cache occupancy. Kept separate from liveness on purpose.',
          responses: { '200': { description: 'Status report.' } },
        },
      },
      '/api/v1/evaluate': analysisPath(
        'Evaluate a track record',
        'The core question. Returns the Probabilistic Sharpe Ratio — the probability the true Sharpe beats a benchmark, corrected for sample length, skew and fat tails — a stationary-bootstrap confidence interval, and the Minimum Track Record Length: how long the record would have to run before the claim could be made at all.',
        {
          benchmarkSharpe: { type: 'number', default: 0, description: 'Per-period Sharpe the record must beat.' },
          confidence: { type: 'number', default: 0.95, exclusiveMinimum: 0.5, exclusiveMaximum: 1 },
          bootstrapResamples: { type: 'integer', default: 2000, minimum: 200, maximum: 20000 },
          seed: { type: 'integer', description: 'Fixed by default, so an interval reproduces exactly.' },
          trialSharpes: {
            type: 'array',
            items: { type: 'number' },
            description:
              'Per-period Sharpe ratios of other configurations tried for this strategy. Supplying them enables the Deflated Sharpe Ratio, which discounts the headline for how many variants were tested before this one was reported.',
          },
        },
      ),
      '/api/v1/regime-map': analysisPath(
        'Map performance to market regimes',
        'Performance sliced by the conditions that held on each date — volatility, funding, open interest, positioning, sentiment, trend state. Every factor is read point-in-time, and each carries a permutation test: the observed best-to-worst spread is compared against spreads from randomly reshuffled labels, so a flattering subset cannot pass itself off as a regime effect.',
        {
          minSample: { type: 'integer', default: 15, minimum: 5, maximum: 500 },
          permutationResamples: { type: 'integer', default: 2000, minimum: 200, maximum: 20000 },
          maxDates: { type: 'integer', default: 45, minimum: 5, maximum: 45, description: 'Most recent dates to read conditions for, bounded by the upstream rate limit.' },
          factorKeys: { type: 'array', items: { type: 'string' } },
          seed: { type: 'integer' },
        },
      ),
      '/api/v1/self-attack': analysisPath(
        'Attack the verdict',
        'Runs the analysis against controls whose answer is known in advance: the strategy’s own returns with the edge removed, and a simulated population of strategies with no edge at all. Published rather than hidden, because an evaluation tool that never fails a control is indistinguishable from one that always agrees with you.',
        {
          simulations: { type: 'integer', default: 1000, minimum: 100, maximum: 20000 },
          benchmarkSharpe: { type: 'number', default: 0 },
          seed: { type: 'integer' },
        },
      ),
    },
  };
}
