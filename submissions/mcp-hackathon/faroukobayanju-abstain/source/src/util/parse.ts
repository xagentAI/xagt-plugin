/**
 * Nexus returns `max_drawdown` as a percent STRING ("7.62%") while
 * `total_return_pct` and `win_rate_pct` on the same object are numbers.
 * One parser, so three checks cannot each invent their own `.replace('%','')`
 * and silently produce NaN that then passes a threshold comparison.
 */
export function parsePercentString(raw: unknown): number {
  if (typeof raw === 'number') {
    if (!Number.isFinite(raw)) throw new PercentParseError(String(raw));
    return raw;
  }
  if (typeof raw !== 'string') throw new PercentParseError(String(raw));

  const trimmed = raw.trim();
  const match = /^(-?\d+(?:\.\d+)?)\s*%?$/.exec(trimmed);
  if (!match || match[1] === undefined) throw new PercentParseError(raw);

  const n = Number(match[1]);
  if (!Number.isFinite(n)) throw new PercentParseError(raw);
  return n;
}

export class PercentParseError extends Error {
  constructor(raw: string) {
    super(`Cannot parse percent value: ${JSON.stringify(raw)}`);
    this.name = 'PercentParseError';
  }
}

/** Unix SECONDS (Nexus signal timestamps) to milliseconds. */
export const secondsToMs = (s: number): number => s * 1000;

/** YYYY-MM-DD lexical compare is safe for ISO dates; avoids timezone drift. */
export function dateWithin(date: string, start: string, end: string): boolean {
  return date >= start && date <= end;
}
