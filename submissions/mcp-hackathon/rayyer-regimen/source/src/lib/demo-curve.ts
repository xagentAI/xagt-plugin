/**
 * The demo equity curve: sixty daily marks of a track record that looks excellent and is not.
 *
 * Its annualised Sharpe is 3.72 — the kind of figure a dashboard leads with — and Regimen
 * still grades it `weak`, because sixty observations cannot separate that from luck.
 * These are the exact values the published verification evidence runs against
 * (`verification/README.md`, "The capability"), so the numbers on the landing page, the
 * numbers in the interactive panel and the numbers in the evidence pack are the same
 * numbers, produced by the same code path.
 */
export interface DemoEquityPoint {
  /** UTC calendar date of the mark, `YYYY-MM-DD`. */
  readonly t: string;
  /** Account equity at that instant, in a single consistent unit. */
  readonly equity: number;
}

export const DEMO_EQUITY_CURVE: ReadonlyArray<DemoEquityPoint> = [
  { t: '2026-06-01', equity: 9988.82 }, { t: '2026-06-02', equity: 10130.95 }, { t: '2026-06-03', equity: 10125.66 },
  { t: '2026-06-04', equity: 10102.36 }, { t: '2026-06-05', equity: 9954.86 }, { t: '2026-06-06', equity: 9952.21 },
  { t: '2026-06-07', equity: 10213.34 }, { t: '2026-06-08', equity: 10340.84 }, { t: '2026-06-09', equity: 10596.64 },
  { t: '2026-06-10', equity: 10691.78 }, { t: '2026-06-11', equity: 10818.96 }, { t: '2026-06-12', equity: 10902.34 },
  { t: '2026-06-13', equity: 10582.67 }, { t: '2026-06-14', equity: 10806.02 }, { t: '2026-06-15', equity: 10958.68 },
  { t: '2026-06-16', equity: 11111.84 }, { t: '2026-06-17', equity: 10780.41 }, { t: '2026-06-18', equity: 10447.53 },
  { t: '2026-06-19', equity: 10303.44 }, { t: '2026-06-20', equity: 10248.17 }, { t: '2026-06-21', equity: 10351.77 },
  { t: '2026-06-22', equity: 10383.67 }, { t: '2026-06-23', equity: 10533.4 }, { t: '2026-06-24', equity: 10440.23 },
  { t: '2026-06-25', equity: 10546.45 }, { t: '2026-06-26', equity: 10671.78 }, { t: '2026-06-27', equity: 10573.36 },
  { t: '2026-06-28', equity: 10978.85 }, { t: '2026-06-29', equity: 11144.98 }, { t: '2026-06-30', equity: 11456.38 },
  { t: '2026-07-01', equity: 11360.07 }, { t: '2026-07-02', equity: 11237.49 }, { t: '2026-07-03', equity: 11205.11 },
  { t: '2026-07-04', equity: 11226.08 }, { t: '2026-07-05', equity: 11412.9 }, { t: '2026-07-06', equity: 11515.26 },
  { t: '2026-07-07', equity: 11458.29 }, { t: '2026-07-08', equity: 11284.84 }, { t: '2026-07-09', equity: 11212.48 },
  { t: '2026-07-10', equity: 11531.12 }, { t: '2026-07-11', equity: 11390.91 }, { t: '2026-07-12', equity: 11492.24 },
  { t: '2026-07-13', equity: 11636.24 }, { t: '2026-07-14', equity: 11336.09 }, { t: '2026-07-15', equity: 11392.42 },
  { t: '2026-07-16', equity: 11735.62 }, { t: '2026-07-17', equity: 11309.76 }, { t: '2026-07-18', equity: 11282.26 },
  { t: '2026-07-19', equity: 11303.44 }, { t: '2026-07-20', equity: 11163.89 }, { t: '2026-07-21', equity: 11319.61 },
  { t: '2026-07-22', equity: 11350.78 }, { t: '2026-07-23', equity: 11063.69 }, { t: '2026-07-24', equity: 11291.12 },
  { t: '2026-07-25', equity: 11487.44 }, { t: '2026-07-26', equity: 11750.69 }, { t: '2026-07-27', equity: 12136.26 },
  { t: '2026-07-28', equity: 12272.73 }, { t: '2026-07-29', equity: 12351.09 }, { t: '2026-07-30', equity: 12079.58 },
];

/**
 * A curve deliberately too short to grade. Regimen declines below twenty usable returns,
 * and the panel keeps that refusal one click away — the refusal is the product working,
 * not the product failing.
 */
export const TOO_SHORT_EQUITY_CURVE: ReadonlyArray<DemoEquityPoint> = DEMO_EQUITY_CURVE.slice(0, 9);
