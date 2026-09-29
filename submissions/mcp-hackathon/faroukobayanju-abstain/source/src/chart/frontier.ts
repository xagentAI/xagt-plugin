/**
 * Threshold frontier.
 *
 *   npm run frontier ──▶ docs/evidence/frontier.svg
 *                        docs/evidence/frontier.txt
 *
 * One tuned chart invites the only question it cannot answer: "did you pick
 * these thresholds because they flattered the result?" So publish what EVERY
 * setting does — including the ones that look bad. A frontier cannot be
 * curve-fitted, because the curve IS the output.
 *
 * Each row replays all 19 recorded trades through the same runGate() the live
 * API calls, varying exactly one threshold from the committed policy.base.json.
 */
import { mkdirSync, writeFileSync } from 'node:fs';
import { NexusClient } from '../nexus/client.js';
import { previousIso } from '../nexus/fetch-all.js';
import { loadBasePolicy } from '../deps.js';
import { mergePolicy } from '../policy/index.js';
import { replay, isoDate, type ReplayInputs } from './replay.js';
import { absent, present, type Coverage, type Equity, type Funding, type Metrics, type OpenInterest, type Policy, type Trades } from '../types.js';

export interface FrontierRow {
  label: string;
  knob: string;
  value: number | string;
  taken: number;
  refused: number;
  pnl: number;
  maxDrawdownPct: number;
}

/** A threshold high enough that its check can never fire. */
const OFF = 1e9;

export function variants(base: Policy): { label: string; knob: string; value: number | string; policy: Policy }[] {
  const all: { label: string; knob: string; value: number | string; policy: Policy }[] = [
    {
      label: 'no gate (every check off)',
      knob: '—',
      value: 'baseline',
      policy: {
        ...base,
        max_cluster_size: OFF,
        max_drawdown_pct: OFF,
        max_loss_streak: OFF,
        max_funding_rate: OFF,
        max_oi_delta_pct: OFF,
        max_signal_age_s: OFF,
        max_symbol_pct: OFF,
        require_qualified: false,
        require_signal_support: false,
        require_data_complete: false,
      },
    },
  ];

  const loose = { ...all[0]!.policy };
  const sweep = (knob: keyof Policy, values: number[]) => {
    for (const v of values) {
      all.push({
        label: `${knob} = ${v}`,
        knob: String(knob),
        value: v,
        policy: { ...loose, [knob]: v },
      });
    }
  };

  // One knob at a time against the fully-open baseline, so each row isolates
  // what that single check costs and saves.
  sweep('max_cluster_size', [2, 3, 4, 5]);
  sweep('max_drawdown_pct', [3, 5, 10]);
  sweep('max_loss_streak', [2, 3, 4]);

  all.push({ label: 'shipped policy (all checks)', knob: 'all', value: 'policy.base.json', policy: base });
  return all;
}

export async function buildFrontier(fixtureDir = 'fixtures'): Promise<FrontierRow[]> {
  const client = new NexusClient({ mode: 'replay', fixtureDir });
  const trades = await client.call<Trades>('get_strategy_trades');
  const equity = await client.call<Equity>('get_strategy_equity');
  const metrics = await client.call<Metrics>('get_strategy_metrics');
  const coverage = await client.call<Coverage>('get_historical_coverage');
  if (!trades.ok || !equity.ok) throw new Error('trades or equity cassette unavailable');

  const market: ReplayInputs['market'] = new Map();
  for (const t of trades.value.trades) {
    const asOf = isoDate(t.entry_ts_ms);
    const key = `${t.symbol}|${asOf}`;
    if (market.has(key)) continue;
    const prev = previousIso(asOf);
    const [funding, oi, oiPrev] = await Promise.all([
      client.call<Funding>('get_historical_funding', { symbol: t.symbol, as_of: asOf }),
      client.call<OpenInterest>('get_open_interest', { symbol: t.symbol, as_of: asOf }),
      client.call<OpenInterest>('get_open_interest', { symbol: t.symbol, as_of: prev }),
    ]);
    market.set(key, { funding, openInterest: oi, openInterestPrev: oiPrev });
  }

  const base = mergePolicy(loadBasePolicy(), 'permissive');
  const startingEquity = equity.value.points[0]?.equity ?? 100_000;

  return variants(base).map((v) => {
    const r = replay({
      trades: trades.value,
      equity: equity.value,
      policy: v.policy,
      startingEquity,
      market,
      staticData: {
        metrics: metrics.ok ? present(metrics.value) : absent<Metrics>(),
        coverage: coverage.ok ? present(coverage.value) : absent<Coverage>(),
      },
    });
    return {
      label: v.label,
      knob: v.knob,
      value: v.value,
      taken: r.summary.trades - r.summary.refused,
      refused: r.summary.refused,
      pnl: r.summary.pnlWithGate,
      maxDrawdownPct: r.summary.maxDrawdownWithPct,
    };
  });
}

export function renderFrontierTable(rows: FrontierRow[]): string {
  const head = '  SETTING                        TAKEN  REFUSED       PNL   MAX DD';
  const rule = '  -----------------------------  -----  -------  --------  -------';
  const body = rows.map(
    (r) =>
      `  ${r.label.padEnd(29)}  ${String(r.taken).padStart(5)}  ${String(r.refused).padStart(7)}  ${r.pnl
        .toFixed(2)
        .padStart(8)}  ${(r.maxDrawdownPct.toFixed(2) + '%').padStart(7)}`,
  );
  return [head, rule, ...body].join('\n');
}

/** Scatter: max drawdown (x) against pnl (y). Up and left is better. */
export function renderFrontierSvg(rows: FrontierRow[]): string {
  const W = 900;
  const H = 440;
  const P = { top: 46, right: 30, bottom: 56, left: 86 };
  const dd = rows.map((r) => r.maxDrawdownPct);
  const pnl = rows.map((r) => r.pnl);
  const xLo = 0;
  const xHi = Math.max(...dd) * 1.15 || 1;
  const yLo = Math.min(...pnl, 0) * 1.2;
  const yHi = Math.max(...pnl, 0) * 1.2 || 1;
  const x = (v: number) => P.left + ((v - xLo) / (xHi - xLo)) * (W - P.left - P.right);
  const y = (v: number) => H - P.bottom - ((v - yLo) / (yHi - yLo)) * (H - P.top - P.bottom);

  const grid = Array.from({ length: 5 }, (_, i) => {
    const v = yLo + ((yHi - yLo) * i) / 4;
    const yy = y(v).toFixed(1);
    return `<line x1="${P.left}" y1="${yy}" x2="${W - P.right}" y2="${yy}" class="grid"/><text x="${P.left - 10}" y="${Number(yy) + 4}" class="axis" text-anchor="end">${Math.round(v)}</text>`;
  }).join('\n  ');

  const pts = rows
    .map((r) => {
      const cls = r.knob === '—' ? 'base' : r.knob === 'all' ? 'ship' : 'pt';
      return `<circle cx="${x(r.maxDrawdownPct).toFixed(1)}" cy="${y(r.pnl).toFixed(1)}" r="${cls === 'pt' ? 5 : 7}" class="${cls}"/>
  <text x="${(x(r.maxDrawdownPct) + 10).toFixed(1)}" y="${(y(r.pnl) + 4).toFixed(1)}" class="lbl">${r.label} · ${r.taken}/19</text>`;
    })
    .join('\n  ');

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="Gate threshold frontier">
  <style>
    .bg{fill:#0b0d12}.grid{stroke:#1e2430}
    .axis{fill:#6b7688;font:11px ui-monospace,Menlo,monospace}
    .lbl{fill:#8b95a7;font:10px ui-monospace,Menlo,monospace}
    .title{fill:#e6e9ef;font:600 15px ui-sans-serif,system-ui,sans-serif}
    .sub{fill:#8b95a7;font:12px ui-monospace,Menlo,monospace}
    .pt{fill:#7c6aef}.base{fill:#e5484d}.ship{fill:#46a758}
    .zero{stroke:#3a4152;stroke-dasharray:4 4}
  </style>
  <rect class="bg" width="${W}" height="${H}"/>
  <text x="${P.left}" y="26" class="title">Every threshold, including the unflattering ones</text>
  <text x="${P.left}" y="${H - 18}" class="sub">max drawdown % (lower is better) →   ·   red = no gate, green = shipped policy   ·   n=19 trades</text>
  ${grid}
  <line x1="${P.left}" y1="${y(0).toFixed(1)}" x2="${W - P.right}" y2="${y(0).toFixed(1)}" class="zero"/>
  ${pts}
</svg>`;
}

const invokedDirectly = process.argv[1]?.endsWith('frontier.js');
if (invokedDirectly) {
  buildFrontier()
    .then((rows) => {
      mkdirSync('docs/evidence', { recursive: true });
      const table = renderFrontierTable(rows);
      writeFileSync('docs/evidence/frontier.svg', renderFrontierSvg(rows));
      writeFileSync(
        'docs/evidence/frontier.txt',
        [
          'Abstain — gate threshold frontier',
          'Every row replays all 19 recorded trades through the same runGate() the',
          'live API calls, varying exactly one threshold. Published in full so the',
          'shipped setting cannot be mistaken for a tuned one.',
          '',
          table,
        ].join('\n'),
      );
      console.log('wrote docs/evidence/frontier.svg and frontier.txt\n');
      console.log(table);
    })
    .catch((err) => {
      console.error(err);
      process.exit(1);
    });
}
