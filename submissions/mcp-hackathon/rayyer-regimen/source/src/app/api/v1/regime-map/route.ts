import * as z from 'zod';
import { RegimenError } from '@/lib/errors';
import { buildRegimeMap } from '@/lib/engine/regime';
import { datesOf, resolveSource, sourceSelectorSchema } from '@/lib/engine/resolve';
import { enforceDemoRateLimit, handler, parseJsonBody, resolveNexusCredentials } from '@/lib/http';

export const dynamic = 'force-dynamic';
export const maxDuration = 300;

/**
 * Point-in-time reads are paced against the upstream's per-minute ceiling, and each
 * date costs five of them. This cap keeps a single request inside its time budget;
 * longer histories are served from the prefetched dataset or by asking again, since
 * past dates are immutable and cached once fetched.
 */
const MAX_DATES_PER_REQUEST = 45;

const bodySchema = z.object({
  selector: sourceSelectorSchema,
  options: z
    .object({
      minSample: z.number().int().min(5).max(500).default(15),
      permutationResamples: z.number().int().min(200).max(20_000).default(2_000),
      seed: z.number().int().optional(),
      factorKeys: z.array(z.string().min(1).max(40)).max(20).optional(),
      maxDates: z.number().int().min(5).max(MAX_DATES_PER_REQUEST).default(MAX_DATES_PER_REQUEST),
    })
    .prefault({}),
});

/**
 * POST /api/v1/regime-map
 *
 * Where the strategy actually makes money: performance sliced by the market
 * conditions that held on each date, with a permutation test on the spread so a
 * flattering subset cannot masquerade as a regime effect.
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

  const resolvedSource = await resolveSource(body.selector, credentials);
  const { record } = resolvedSource;

  let regimes = resolvedSource.regimes;
  let truncatedFrom: number | null = null;

  if (!regimes) {
    if (!resolvedSource.fetchRegimesFor) {
      throw new RegimenError('invalid_input', 'This source cannot look up market conditions on its own.', {
        remedy:
          'Supply them yourself under `selector.regimes`, one observation per UTC date, or use `"source": "olaxbt-nexus"`.',
      });
    }
    const allDates = datesOf(record);
    // Keep the most recent window: recent conditions are what a caller is deciding on.
    const dates = allDates.slice(-body.options.maxDates);
    if (dates.length < allDates.length) truncatedFrom = allDates.length;
    regimes = await resolvedSource.fetchRegimesFor(dates);
  }

  const report = buildRegimeMap(record, regimes, body.options);

  return {
    report,
    ...(truncatedFrom !== null
      ? {
          truncation: {
            datesAvailable: truncatedFrom,
            datesUsed: body.options.maxDates,
            note: 'Only the most recent dates were read, to stay inside the upstream rate limit for a single request. Past dates are immutable and cached, so repeating the call widens coverage.',
          },
        }
      : {}),
  };
});
