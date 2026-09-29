/**
 * Display formatting, shared by the server-rendered readout and the browser panel so
 * the same statistic never appears in two different shapes on one page.
 *
 * Every figure is shown as the API reported it. MinTRL in particular is a real number —
 * 78.1 periods, not 78 and not 79 — and rounding it would silently disagree with the
 * shortfall the same response carries.
 */

/** A Sharpe bound, always with its sign, using a true minus rather than a hyphen. */
export function signed(value: number): string {
  return `${value < 0 ? '−' : '+'}${Math.abs(value).toFixed(3)}`;
}

export function percent(value: number): string {
  return `${(value * 100).toFixed(1)}%`;
}

/** Periods to one decimal, with a trailing `.0` dropped. */
export function formatPeriods(value: number): string {
  const fixed = value.toFixed(1);
  return fixed.endsWith('.0') ? fixed.slice(0, -2) : fixed;
}

export function count(value: number): string {
  return value.toLocaleString('en-GB');
}
