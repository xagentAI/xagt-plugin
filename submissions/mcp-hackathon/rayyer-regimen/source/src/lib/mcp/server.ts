import { McpServer, ResourceTemplate } from '@modelcontextprotocol/server';
import * as z from 'zod';
import { RegimenError, toRegimenError } from '@/lib/errors';
import { FACTOR_BUCKETING, buildRegimeMap } from '@/lib/engine/regime';
import { datesOf, resolveSource, type SourceSelector } from '@/lib/engine/resolve';
import { runSelfAttack } from '@/lib/engine/self-attack';
import { EVIDENCE_THRESHOLDS, analyseSignificance } from '@/lib/engine/significance';
import { REGIME_FACTOR_KEYS } from '@/lib/sources/nexus/adapter';
import { inlineTrackRecordSchema } from '@/lib/sources/inline/adapter';
import { METHODOLOGY_MARKDOWN } from '@/lib/methodology';
import { FACTOR_CATALOGUE } from './factors';

/**
 * Regimen's MCP surface.
 *
 * Written against MCP revision 2026-07-28, which is stateless: no `initialize`
 * handshake, no session id. Anything that needs to persist between calls travels as
 * an explicit server-minted handle passed back as an ordinary argument, which is the
 * pattern the current spec prescribes in place of sessions.
 *
 * Conventions applied to every tool, because they are what make a tool usable by a
 * model rather than merely callable:
 *  - an `outputSchema`, so results arrive as validated `structuredContent` rather
 *    than a wall of text the client has to re-parse;
 *  - annotations declaring each tool read-only — nothing here writes, trades, signs,
 *    or holds funds, and a client should be able to see that without reading docs;
 *  - descriptions that say what the tool is FOR and when to reach for a different one;
 *  - a `detail` switch, because an agent usually wants the verdict and its reasons,
 *    not sixty buckets it will never quote;
 *  - failures returned as tool-execution errors carrying a machine-readable code, so
 *    the model can correct itself instead of guessing.
 */

const READ_ONLY = {
  readOnlyHint: true,
  destructiveHint: false,
  idempotentHint: true,
  openWorldHint: false,
} as const;

/** Tools that reach the third-party data service: same safety, but results move. */
const READ_ONLY_LIVE = { ...READ_ONLY, idempotentHint: false, openWorldHint: true } as const;

/** Inventories are fixed per deployment; an hour is a safe public lifetime. */
const LIST_CACHE_HINT = { ttlMs: 3_600_000, cacheScope: 'public' } as const;

export interface ServerDeps {
  /** Nexus credentials for this request, if any were supplied or configured. */
  readonly nexusApiKey: string | null;
  readonly credentialSource: 'caller' | 'demo' | 'none';
}

const detailSchema = z
  .enum(['concise', 'full'])
  .default('concise')
  .describe(
    'concise returns the verdict, the headline statistics and the reasoning — enough to answer a user. full adds every bucket, every dropped point and the complete provenance list, and is much larger.',
  );

const selectorSchema = z
  .object({
    source: z
      .enum(['olaxbt-nexus', 'inline'])
      .describe(
        'olaxbt-nexus analyses the strategy bound to this connection’s API key. inline analyses an equity curve you supply directly, from any venue or backtest.',
      ),
    symbol: z
      .string()
      .min(3)
      .max(32)
      .optional()
      .describe('For olaxbt-nexus: the market the strategy trades, used for point-in-time reads. Default BTC/USDT.'),
    trackRecord: inlineTrackRecordSchema.optional().describe('Required when source is inline.'),
  })
  .describe('Which track record to analyse.');

function toSelector(input: z.infer<typeof selectorSchema>): SourceSelector {
  if (input.source === 'inline') {
    if (!input.trackRecord) {
      throw new RegimenError('invalid_input', '`selector.trackRecord` is required when source is "inline".', {
        remedy: 'Supply an equity curve, or set source to "olaxbt-nexus" to analyse the connected strategy.',
      });
    }
    return { source: 'inline', trackRecord: input.trackRecord };
  }
  return { source: 'olaxbt-nexus', symbol: input.symbol ?? 'BTC/USDT' };
}

const evidenceOutputSchema = z.object({
  label: z.string(),
  sourceId: z.string(),
  verdict: z.string().describe('One of insufficient_evidence, indistinguishable_from_luck, weak, supported, strong.'),
  headline: z.string(),
  usableReturns: z.number(),
  sharpePerPeriod: z.number().nullable(),
  sharpeAnnualised: z.number().nullable(),
  probabilisticSharpe: z.number().nullable(),
  minimumTrackRecordLength: z.number().nullable(),
  periodsShortOfSignificance: z.number().nullable(),
  sharpeConfidenceInterval: z.object({ lower: z.number(), upper: z.number(), level: z.number() }).nullable(),
  deflatedSharpe: z.number().nullable(),
  reasoning: z.array(z.string()),
  divergencesFromReported: z.array(
    z.object({ field: z.string(), reported: z.number(), recomputed: z.number(), material: z.boolean() }),
  ),
  notes: z.array(z.string()),
  full: z.unknown().nullable().describe('The complete report when detail is "full", otherwise null.'),
});

const regimeOutputSchema = z.object({
  label: z.string(),
  datesCovered: z.number(),
  minSample: z.number(),
  factors: z.array(
    z.object({
      key: z.string(),
      bucketingMethod: z.string(),
      sufficientBuckets: z.number(),
      best: z.object({ label: z.string(), sharpe: z.number() }).nullable(),
      worst: z.object({ label: z.string(), sharpe: z.number() }).nullable(),
      spread: z.number().nullable(),
      permutationPValue: z.number().nullable(),
      interpretation: z.string().nullable(),
      warnings: z.array(z.string()),
    }),
  ),
  warnings: z.array(z.string()),
  full: z.unknown().nullable(),
});

const selfAttackOutputSchema = z.object({
  label: z.string(),
  verdict: z.string(),
  controls: z.array(
    z.object({
      name: z.string(),
      expected: z.string(),
      observed: z.number().nullable(),
      passed: z.boolean(),
      detail: z.string(),
    }),
  ),
  nullDistribution: z
    .object({
      simulations: z.number(),
      observedPsr: z.number().nullable(),
      nullMedianPsr: z.number().nullable(),
      nullP95Psr: z.number().nullable(),
      empiricalPValue: z.number().nullable(),
      interpretation: z.string(),
    })
    .nullable(),
  notes: z.array(z.string()),
});

const factorDescriptionSchema = z.object({
  factors: z.array(
    z.object({
      key: z.string(),
      label: z.string(),
      unit: z.string(),
      description: z.string(),
      source: z.string(),
      pointInTime: z.boolean(),
    }),
  ),
  note: z.string(),
});

function ok<T>(output: T) {
  return {
    content: [{ type: 'text' as const, text: JSON.stringify(output, null, 2) }],
    structuredContent: output as Record<string, unknown>,
  };
}

/** Failures become tool-execution errors so the model can read them and retry correctly. */
function fail(error: unknown) {
  const normalised = toRegimenError(error);
  return {
    isError: true as const,
    content: [{ type: 'text' as const, text: JSON.stringify(normalised.toJSON(), null, 2) }],
  };
}

export function buildServer(deps: ServerDeps): McpServer {
  const server = new McpServer(
    { name: 'regimen', version: '1.0.0' },
    {
      // The tool, prompt and resource inventories are fixed at build time and are
      // identical for every caller, so they are publicly cacheable. Under the
      // 2026-07-28 revision these hints are the only thing that stops a client
      // refetching the whole catalogue on every turn; the conservative default of
      // `ttlMs: 0, cacheScope: 'private'` would be a lie about data that never moves.
      cacheHints: {
        'tools/list': LIST_CACHE_HINT,
        'prompts/list': LIST_CACHE_HINT,
        'resources/list': LIST_CACHE_HINT,
        'resources/templates/list': LIST_CACHE_HINT,
        'server/discover': LIST_CACHE_HINT,
      },
      instructions:
        'Regimen decides whether a trading track record is distinguishable from luck, and which market regimes its edge lives in. Start with regimen_evaluate_track_record; read regimen://methodology before explaining any number to a user. A verdict of insufficient_evidence or indistinguishable_from_luck is a real answer, not an error — report it as such rather than retrying with different parameters. This service is read-only: it does not trade, hold funds, sign, or perform any security or compliance analysis.',
    },
  );
  const credentials = deps.nexusApiKey ? { apiKey: deps.nexusApiKey } : {};

  server.registerTool(
    'regimen_describe_factors',
    {
      title: 'Describe regime factors',
      description:
        'List the market-condition factors Regimen slices performance by, with units, the upstream operation each is read from, and how it is bucketed. Call this when you need to know which factor keys exist or how to explain a bucket to a user. Takes no arguments, reaches no network, never changes.',
      inputSchema: z.object({}),
      outputSchema: factorDescriptionSchema,
      annotations: { ...READ_ONLY, title: 'Describe regime factors' },
    },
    () =>
      ok({
        factors: REGIME_FACTOR_KEYS.map((key) => ({
          key,
          label: FACTOR_CATALOGUE[key].label,
          unit: FACTOR_CATALOGUE[key].unit,
          description: FACTOR_CATALOGUE[key].description,
          source: FACTOR_CATALOGUE[key].source,
          pointInTime: true,
        })),
        note: 'Every factor is read with an explicit as_of date, so a regime map contains only what was knowable on the day.',
      }),
  );

  server.registerTool(
    'regimen_evaluate_track_record',
    {
      title: 'Evaluate a track record',
      description:
        'Answer whether a trading strategy’s measured performance is distinguishable from luck. Returns the Probabilistic Sharpe Ratio (the probability the true Sharpe beats a benchmark, corrected for sample length, skew and fat tails), a bootstrap confidence interval, and the Minimum Track Record Length — how long the record would have to run before the claim could be made at all. Use this whenever someone quotes a Sharpe ratio, a win rate or a return and you need to know whether the number means anything. It will frequently say the evidence is too thin; that is the intended answer, not a failure.',
      inputSchema: z.object({
        selector: selectorSchema,
        benchmarkSharpe: z
          .number()
          .finite()
          .default(0)
          .describe('Per-period Sharpe the record must beat. 0 asks only whether there is any edge at all.'),
        confidence: z.number().gt(0.5).lt(1).default(0.95),
        trialSharpes: z
          .array(z.number().finite())
          .max(500)
          .optional()
          .describe(
            'Per-period Sharpe ratios of other configurations tried for this strategy. Supplying them enables the Deflated Sharpe Ratio, which discounts the headline for how many variants were tested before this one was reported.',
          ),
        detail: detailSchema,
      }),
      outputSchema: evidenceOutputSchema,
      annotations: { ...READ_ONLY_LIVE, title: 'Evaluate a track record' },
    },
    async ({ selector, benchmarkSharpe, confidence, trialSharpes, detail }) => {
      try {
        const resolved = await resolveSource(toSelector(selector), credentials);
        const report = analyseSignificance(resolved.record, {
          benchmarkSharpe,
          confidence,
          ...(trialSharpes ? { trialSharpes } : {}),
        });
        return ok({
          label: report.label,
          sourceId: report.sourceId,
          verdict: report.evidence.tier,
          headline: report.evidence.headline,
          usableReturns: report.sample.usableReturns,
          sharpePerPeriod: report.performance.sharpePerPeriod,
          sharpeAnnualised: report.performance.sharpeAnnualised,
          probabilisticSharpe: report.evidence.probabilisticSharpe,
          minimumTrackRecordLength: report.evidence.minimumTrackRecordLength,
          periodsShortOfSignificance: report.evidence.periodsShortOfSignificance,
          sharpeConfidenceInterval: report.evidence.sharpeConfidenceInterval,
          deflatedSharpe: report.evidence.deflatedSharpe,
          reasoning: [...report.evidence.rationale],
          divergencesFromReported: report.divergences.map((row) => ({
            field: row.field,
            reported: row.reported,
            recomputed: row.recomputed,
            material: row.material,
          })),
          notes: [...report.notes],
          full: detail === 'full' ? report : null,
        });
      } catch (error) {
        return fail(error);
      }
    },
  );

  server.registerTool(
    'regimen_regime_map',
    {
      title: 'Map performance to market regimes',
      description:
        'Break a strategy’s returns down by the market conditions that held on each date — volatility, funding, open interest, positioning, sentiment, trend state — and report performance per bucket. Each factor also gets a permutation test: the observed best-to-worst spread is compared against spreads produced by randomly reshuffling the regime labels, so a flattering subset cannot pass itself off as a regime effect. Use this after regimen_evaluate_track_record when you need to know WHERE an edge comes from, or whether it is a bet on conditions that could end.',
      inputSchema: z.object({
        selector: selectorSchema,
        minSample: z
          .number()
          .int()
          .min(5)
          .max(500)
          .default(15)
          .describe('Buckets below this many observations are returned but flagged unusable.'),
        maxDates: z
          .number()
          .int()
          .min(5)
          .max(45)
          .default(45)
          .describe('How many of the most recent dates to read conditions for, bounded by the upstream rate limit.'),
        detail: detailSchema,
      }),
      outputSchema: regimeOutputSchema,
      annotations: { ...READ_ONLY_LIVE, title: 'Map performance to market regimes' },
    },
    async ({ selector, minSample, maxDates, detail }) => {
      try {
        const resolvedSelector = toSelector(selector);
        const resolved = await resolveSource(resolvedSelector, credentials);
        let regimes = resolved.regimes;
        if (!regimes) {
          if (!resolved.fetchRegimesFor) {
            return fail(
              new Error(
                'This source cannot look up market conditions. Supply them with the track record, or use source "olaxbt-nexus".',
              ),
            );
          }
          regimes = await resolved.fetchRegimesFor(datesOf(resolved.record).slice(-maxDates));
        }
        const report = buildRegimeMap(resolved.record, regimes, { minSample });
        return ok({
          label: report.label,
          datesCovered: report.alignment.datesCovered,
          minSample: report.minSample,
          factors: report.factors.map((factor) => ({
            key: factor.key,
            bucketingMethod: factor.bucketingMethod,
            sufficientBuckets: factor.sufficientBuckets,
            best: factor.best,
            worst: factor.worst,
            spread: factor.spread,
            permutationPValue: factor.permutation?.pValue ?? null,
            interpretation: factor.permutation?.interpretation ?? null,
            warnings: [...factor.warnings],
          })),
          warnings: [...report.warnings],
          full: detail === 'full' ? report : null,
        });
      } catch (error) {
        return fail(error);
      }
    },
  );

  server.registerTool(
    'regimen_self_attack',
    {
      title: 'Attack the verdict',
      description:
        'Run Regimen’s own analysis against controls whose answer is known in advance: the strategy’s returns with the edge mathematically removed, and a simulated population of strategies with no edge at all. Returns whether the engine correctly found nothing in them, and where the real strategy’s confidence sits among pure-luck strategies of the same length and volatility. Use this when a user is entitled to ask why they should believe the verdict, or before quoting a result as evidence.',
      inputSchema: z.object({
        selector: selectorSchema,
        simulations: z.number().int().min(100).max(10_000).default(1_000),
      }),
      outputSchema: selfAttackOutputSchema,
      annotations: { ...READ_ONLY_LIVE, title: 'Attack the verdict' },
    },
    async ({ selector, simulations }) => {
      try {
        const resolved = await resolveSource(toSelector(selector), credentials);
        const report = runSelfAttack(resolved.record, { simulations });
        return ok({
          label: report.label,
          verdict: report.verdict,
          controls: report.controls.map((control) => ({
            name: control.name,
            expected: control.expected,
            observed: control.observed,
            passed: control.passed,
            detail: control.detail,
          })),
          nullDistribution: report.nullDistribution
            ? {
                simulations: report.nullDistribution.simulations,
                observedPsr: report.nullDistribution.observedPsr,
                nullMedianPsr: report.nullDistribution.nullMedianPsr,
                nullP95Psr: report.nullDistribution.nullP95Psr,
                empiricalPValue: report.nullDistribution.empiricalPValue,
                interpretation: report.nullDistribution.interpretation,
              }
            : null,
          notes: [...report.notes],
        });
      } catch (error) {
        return fail(error);
      }
    },
  );

  registerResources(server);
  registerPrompts(server);

  return server;
}

/**
 * Resources carry the things an agent should read rather than infer: the methodology
 * behind the numbers, the exact grading thresholds, and the factor catalogue. All are
 * static and identical for every caller, so they are marked publicly cacheable with a
 * long TTL — under the 2026-07-28 revision that hint is what lets a client stop
 * refetching them on every turn.
 */
function registerResources(server: McpServer): void {
  const publicCache = { ttlMs: 86_400_000, cacheScope: 'public' as const };

  server.registerResource(
    'methodology',
    'regimen://methodology',
    {
      title: 'How Regimen decides',
      description:
        'The statistics behind every verdict: the Probabilistic and Deflated Sharpe Ratios, Minimum Track Record Length, the bootstrap, the regime permutation test, the published evidence tiers, and the explicit limits of what this service does. Read this before explaining a result to a user.',
      mimeType: 'text/markdown',
      cacheHint: publicCache,
    },
    (uri) => ({
      contents: [{ uri: uri.href, mimeType: 'text/markdown', text: METHODOLOGY_MARKDOWN }],
    }),
  );

  server.registerResource(
    'evidence-tiers',
    'regimen://evidence-tiers',
    {
      title: 'Evidence tier thresholds',
      description:
        'The exact numeric thresholds that map a confidence level to a verdict. Published so a caller can see the grading is a fixed function of the statistics rather than a judgement call.',
      mimeType: 'application/json',
      cacheHint: publicCache,
    },
    (uri) => ({
      contents: [
        {
          uri: uri.href,
          mimeType: 'application/json',
          text: JSON.stringify(
            {
              thresholds: EVIDENCE_THRESHOLDS,
              tiers: [
                { tier: 'insufficient_evidence', condition: 'fewer than 20 usable returns, or no dispersion' },
                { tier: 'indistinguishable_from_luck', condition: 'governing confidence below 90%' },
                { tier: 'weak', condition: '90-95%, or a bootstrap interval that still contains zero' },
                { tier: 'supported', condition: 'at least 95% and the bootstrap lower bound clears zero' },
                { tier: 'strong', condition: 'at least 99%, interval clears zero, record at least MinTRL long' },
              ],
              governing:
                'The Deflated Sharpe Ratio when trial Sharpes were supplied, otherwise the Probabilistic Sharpe Ratio.',
            },
            null,
            2,
          ),
        },
      ],
    }),
  );

  server.registerResource(
    'factor',
    new ResourceTemplate('regimen://factor/{key}', {
      list: () => ({
        resources: REGIME_FACTOR_KEYS.map((key) => ({
          uri: `regimen://factor/${key}`,
          name: FACTOR_CATALOGUE[key].label,
          mimeType: 'application/json',
        })),
      }),
      // Argument completion for the factor key. Rarely implemented, and it is what
      // lets a client offer the valid values instead of making the model guess them.
      complete: {
        key: (value: string) => REGIME_FACTOR_KEYS.filter((key) => key.startsWith(value)),
      },
    }),
    {
      title: 'Regime factor detail',
      description:
        'One market-condition factor: what it measures, its unit, how it is bucketed, and which upstream operation supplies it.',
      mimeType: 'application/json',
      cacheHint: publicCache,
    },
    (uri, variables) => {
      const key = String(variables['key']);
      const entry = (FACTOR_CATALOGUE as Record<string, (typeof FACTOR_CATALOGUE)[keyof typeof FACTOR_CATALOGUE]>)[key];
      if (!entry) {
        throw new RegimenError('not_found', `There is no regime factor called "${key}".`, {
          details: { known: [...REGIME_FACTOR_KEYS] },
        });
      }
      const bucketing = FACTOR_BUCKETING[key] ?? null;
      return {
        contents: [
          {
            uri: uri.href,
            mimeType: 'application/json',
            text: JSON.stringify({ key, ...entry, bucketing }, null, 2),
          },
        ],
      };
    },
  );
}

function registerPrompts(server: McpServer): void {
  server.registerPrompt(
    'validate_strategy',
    {
      title: 'Validate a strategy end to end',
      description:
        'The full review a strategy deserves before anyone sizes on it: establish whether the edge is distinguishable from luck, check the engine against its own controls, then find out which market conditions the edge actually lives in.',
      argsSchema: z.object({
        source: z
          .enum(['olaxbt-nexus', 'inline'])
          .describe('Which track record to review: the connected Nexus strategy, or a curve you will paste.'),
        symbol: z.string().optional().describe('For olaxbt-nexus, the market traded. Default BTC/USDT.'),
      }),
    },
    ({ source, symbol }) => ({
      messages: [
        {
          role: 'user' as const,
          content: {
            type: 'text' as const,
            text: [
              `Review the ${source === 'inline' ? 'equity curve I am about to give you' : `OlaXBT Nexus strategy${symbol ? ` trading ${symbol}` : ''}`} using Regimen, in this order:`,
              '',
              '1. Call regimen_evaluate_track_record. Lead with the verdict and the Probabilistic Sharpe Ratio, and state plainly how many more periods would be needed if the record is short of significance. Do not quote the annualised Sharpe on its own — it is the number that misleads.',
              '2. Call regimen_self_attack. Report whether the mean-centred control passed. If it did not, stop and say the verdict cannot be trusted.',
              '3. Call regimen_regime_map. For each factor, only treat a spread as real when its permutation p-value is at or below 0.05, and say so explicitly when it is not.',
              '',
              'Finish with one paragraph a trader can act on. If the evidence is thin, say that first rather than burying it.',
            ].join('\n'),
          },
        },
      ],
    }),
  );
}
