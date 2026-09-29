import * as z from 'zod';
import { analyseSignificance } from '@/lib/engine/significance';
import { resolveSource, sourceSelectorSchema } from '@/lib/engine/resolve';
import { enforceDemoRateLimit, handler, parseJsonBody, resolveNexusCredentials } from '@/lib/http';

export const dynamic = 'force-dynamic';
export const maxDuration = 120;

const optionsSchema = z
  .object({
    benchmarkSharpe: z
      .number()
      .finite()
      .default(0)
      .describe('Per-period Sharpe the record must beat. 0 asks only whether there is any edge at all.'),
    confidence: z.number().gt(0.5).lt(1).default(0.95),
    bootstrapResamples: z.number().int().min(200).max(20_000).default(2_000),
    seed: z.number().int().optional(),
    trialSharpes: z
      .array(z.number().finite())
      .max(1_000)
      .optional()
      .describe('Per-period Sharpe ratios from other evaluation windows, enabling the Deflated Sharpe Ratio.'),
  })
  .prefault({});

const bodySchema = z.object({
  selector: sourceSelectorSchema,
  options: optionsSchema,
});

/**
 * POST /api/v1/evaluate
 *
 * The core question: is this track record distinguishable from luck? Accepts either
 * an OlaXBT Nexus strategy (via `x-nexus-key`, or the deployment's demo key) or an
 * equity curve supplied inline.
 */
export const POST = handler(async (request, { setMode }) => {
  const body = await parseJsonBody(request, bodySchema);

  let credentials = {};
  if (body.selector.source === 'olaxbt-nexus') {
    const resolved = resolveNexusCredentials(request);
    credentials = { apiKey: resolved.apiKey };
    setMode(resolved.mode);
    enforceDemoRateLimit(request, resolved.mode);
  } else {
    setMode('inline');
    enforceDemoRateLimit(request, 'inline');
  }

  const { record } = await resolveSource(body.selector, credentials);
  const report = analyseSignificance(record, body.options);

  return { report, provenance: record.provenance };
});
