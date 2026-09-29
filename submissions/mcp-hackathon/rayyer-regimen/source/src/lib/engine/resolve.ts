import * as z from 'zod';
import { RegimenError } from '@/lib/errors';
import { buildInlineRegimeSeries, buildInlineTrackRecord, inlineRegimeSchema, inlineTrackRecordSchema } from '@/lib/sources/inline/adapter';
import { NexusAdapter } from '@/lib/sources/nexus/adapter';
import type { RegimeSeries, SourceCredentials, TrackRecord } from '@/lib/sources/types';

/**
 * Turning a request into a track record, whichever source it names.
 *
 * Every analysis endpoint accepts the same `source` discriminator, so the difference
 * between "analyse my OlaXBT strategy" and "analyse this curve I pasted" is one field,
 * not a different API. Keeping that resolution in one place is also what stops a
 * credential from leaking into a code path that does not need one.
 */

export const sourceSelectorSchema = z.discriminatedUnion('source', [
  z.object({
    source: z.literal('olaxbt-nexus'),
    symbol: z
      .string()
      .min(3)
      .max(32)
      .default('BTC/USDT')
      .describe('Market the strategy trades, used for the point-in-time reads. Example: BTC/USDT.'),
  }),
  z.object({
    source: z.literal('inline'),
    trackRecord: inlineTrackRecordSchema,
    regimes: inlineRegimeSchema.optional(),
  }),
]);

export type SourceSelector = z.infer<typeof sourceSelectorSchema>;

export interface ResolvedSource {
  readonly record: TrackRecord;
  readonly regimes: RegimeSeries | null;
  readonly canFetchRegimes: boolean;
  readonly fetchRegimesFor: ((dates: readonly string[]) => Promise<RegimeSeries>) | null;
}

export async function resolveSource(
  selector: SourceSelector,
  credentials: SourceCredentials,
): Promise<ResolvedSource> {
  if (selector.source === 'inline') {
    return {
      record: buildInlineTrackRecord(selector.trackRecord),
      regimes: selector.regimes ? buildInlineRegimeSeries(selector.regimes) : null,
      canFetchRegimes: false,
      fetchRegimesFor: null,
    };
  }

  if (!credentials.apiKey) {
    throw new RegimenError('missing_credentials', 'Analysing a Nexus strategy needs a Nexus API key.', {
      remedy: 'Send it in the `x-nexus-key` header, or use `"source": "inline"` with your own equity curve.',
    });
  }

  const adapter = new NexusAdapter({ symbol: selector.symbol });
  const record = await adapter.fetchTrackRecord(credentials);

  return {
    record,
    regimes: null,
    canFetchRegimes: true,
    fetchRegimesFor: (dates) => adapter.fetchRegimes(dates, credentials),
  };
}

/** The distinct UTC dates an equity curve touches, in order — the keys a regime map needs. */
export function datesOf(record: TrackRecord): string[] {
  const seen = new Set<string>();
  const dates: string[] = [];
  for (const point of record.equity) {
    const date = new Date(point.t).toISOString().slice(0, 10);
    if (seen.has(date)) continue;
    seen.add(date);
    dates.push(date);
  }
  return dates;
}
