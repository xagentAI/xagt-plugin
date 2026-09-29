import * as z from 'zod';
import { RegimenError } from '@/lib/errors';
import type {
  EquityPoint,
  Provenance,
  RegimeSeries,
  SourceAdapter,
  SourceCredentials,
  Trade,
  TrackRecord,
} from '@/lib/sources/types';

/**
 * The bring-your-own-track-record source.
 *
 * Regimen's analysis does not care where an equity curve came from, so the same
 * engine that judges an OlaXBT Nexus strategy will judge a curve pasted in from a
 * spreadsheet, another venue, or a research notebook. That is the difference between
 * a wrapper around one vendor and a capability: an agent holding numbers from
 * anywhere can get the same verdict, with the same statistics and the same refusals.
 *
 * Nothing here is persisted. The payload is analysed and discarded within the request.
 */

export const INLINE_SOURCE_ID = 'inline';

/** Upper bounds exist so a single request cannot be used to exhaust the service. */
const MAX_EQUITY_POINTS = 10_000;
const MAX_TRADES = 20_000;

export const inlineEquityPointSchema = z.object({
  t: z
    .union([z.number(), z.string()])
    .describe('Epoch milliseconds, epoch seconds, or an ISO 8601 timestamp. UTC is assumed.'),
  equity: z.number().finite().positive().describe('Account equity at that instant, in any single consistent unit.'),
});

export const inlineTradeSchema = z.object({
  symbol: z.string().min(1).max(64).optional(),
  pnl: z.number().finite().describe('Realised profit or loss for the closed trade, in the equity unit.'),
  exitedAt: z.union([z.number(), z.string()]).optional(),
  entryPrice: z.number().finite().optional(),
  exitPrice: z.number().finite().optional(),
  holdingBars: z.number().int().nonnegative().optional(),
  exitReason: z.string().max(120).optional(),
});

export const inlineTrackRecordSchema = z.object({
  label: z
    .string()
    .min(1)
    .max(80)
    .default('inline-track-record')
    .describe('A name for this track record, echoed back in results. Do not put anything sensitive here.'),
  equity: z
    .array(inlineEquityPointSchema)
    .min(2)
    .max(MAX_EQUITY_POINTS)
    .describe('The equity curve, one point per period. Order does not matter; it is sorted by timestamp.'),
  trades: z.array(inlineTradeSchema).max(MAX_TRADES).optional(),
  reportedSharpe: z
    .number()
    .finite()
    .optional()
    .describe('Optional. The Sharpe ratio you believe this track record has, so Regimen can contrast it with its own.'),
});

export type InlineTrackRecordInput = z.infer<typeof inlineTrackRecordSchema>;

/**
 * Parse a timestamp given as epoch ms, epoch seconds, or ISO 8601.
 * Returns null rather than guessing when the value cannot be read as a time.
 */
export function parseTimestamp(value: number | string): number | null {
  if (typeof value === 'number') {
    if (!Number.isFinite(value) || value <= 0) return null;
    return value < 1e11 ? Math.round(value * 1000) : Math.round(value);
  }
  const trimmed = value.trim();
  if (trimmed === '') return null;
  if (/^\d+$/.test(trimmed)) return parseTimestamp(Number(trimmed));
  const parsed = Date.parse(trimmed);
  return Number.isFinite(parsed) ? parsed : null;
}

export function buildInlineTrackRecord(input: InlineTrackRecordInput): TrackRecord {
  const provenance: Provenance[] = [
    {
      source: INLINE_SOURCE_ID,
      operation: 'caller_supplied',
      fetchedAt: new Date().toISOString(),
      cached: false,
    },
  ];

  const equity: EquityPoint[] = [];
  const badTimestamps: number[] = [];
  input.equity.forEach((point, index) => {
    const t = parseTimestamp(point.t);
    if (t === null) {
      badTimestamps.push(index);
      return;
    }
    equity.push({ t, equity: point.equity });
  });

  if (badTimestamps.length > 0) {
    throw new RegimenError('invalid_input', 'Some equity timestamps could not be read as a point in time.', {
      details: { indices: badTimestamps.slice(0, 20), count: badTimestamps.length },
      remedy: 'Use epoch milliseconds, epoch seconds, or an ISO 8601 string such as 2026-01-15T00:00:00Z.',
    });
  }

  if (equity.length < 2) {
    throw new RegimenError('insufficient_sample', 'At least two equity points are required to derive a return.', {
      details: { received: equity.length },
    });
  }

  const trades: Trade[] = (input.trades ?? []).map((trade) => {
    const exitedAt = trade.exitedAt === undefined ? null : parseTimestamp(trade.exitedAt);
    return {
      symbol: trade.symbol ?? 'UNKNOWN',
      pnl: trade.pnl,
      ...(exitedAt !== null ? { exitedAt } : {}),
      ...(trade.entryPrice !== undefined ? { entryPrice: trade.entryPrice } : {}),
      ...(trade.exitPrice !== undefined ? { exitPrice: trade.exitPrice } : {}),
      ...(trade.holdingBars !== undefined ? { holdingBars: trade.holdingBars } : {}),
      ...(trade.exitReason ? { exitReason: trade.exitReason } : {}),
    };
  });

  return {
    sourceId: INLINE_SOURCE_ID,
    label: input.label,
    equity,
    trades,
    ...(input.reportedSharpe !== undefined ? { reported: { sharpeRatio: input.reportedSharpe } } : {}),
    provenance,
  };
}

/**
 * Caller-supplied regime labels, for attributing an inline track record to conditions
 * Regimen cannot look up itself. One observation per UTC date.
 */
export const inlineRegimeSchema = z.object({
  observations: z
    .array(
      z.object({
        date: z.string().regex(/^\d{4}-\d{2}-\d{2}$/, 'Use a UTC calendar date, YYYY-MM-DD.'),
        factors: z.record(z.string().min(1).max(40), z.union([z.number(), z.string(), z.null()])),
      }),
    )
    .min(1)
    .max(MAX_EQUITY_POINTS),
});

export function buildInlineRegimeSeries(input: z.infer<typeof inlineRegimeSchema>): RegimeSeries {
  const fetchedAt = new Date().toISOString();
  const keys = new Set<string>();
  for (const observation of input.observations) {
    for (const key of Object.keys(observation.factors)) keys.add(key);
  }

  return {
    sourceId: INLINE_SOURCE_ID,
    factorKeys: [...keys].sort(),
    observations: input.observations.map((observation) => ({
      date: observation.date,
      factors: observation.factors,
      provenance: [
        { source: INLINE_SOURCE_ID, operation: 'caller_supplied', asOf: observation.date, fetchedAt, cached: false },
      ],
    })),
  };
}

export class InlineAdapter implements SourceAdapter {
  readonly id = INLINE_SOURCE_ID;
  readonly displayName = 'Caller-supplied track record';
  readonly capabilities = {
    trackRecord: true,
    regimes: false,
    liveSignal: false,
    reevaluate: false,
  } as const;

  private readonly input: InlineTrackRecordInput;

  constructor(input: InlineTrackRecordInput) {
    this.input = input;
  }

  fetchTrackRecord(_credentials: SourceCredentials): Promise<TrackRecord> {
    return Promise.resolve(buildInlineTrackRecord(this.input));
  }
}
