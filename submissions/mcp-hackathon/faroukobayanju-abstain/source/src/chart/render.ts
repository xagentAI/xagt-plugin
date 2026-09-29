/**
 * Static SVG of the two equity curves. No runtime, no CDN, no chart library —
 * the artifact is committed to the repo and embedded in SUBMISSION.md, so a
 * broken chart route during the review window is a liability we simply do not
 * take on.
 *
 *   ─── without gate   every trade taken
 *   ━━━ with gate      refused trades contribute nothing
 */
import type { ReplayResult } from './replay.js';

const W = 900;
const H = 380;
const PAD = { top: 44, right: 24, bottom: 46, left: 72 };

const esc = (s: string): string =>
  s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');

export function renderSvg(result: ReplayResult, opts: { title?: string } = {}): string {
  const all = [...result.withoutGate, ...result.withGate];
  const ts = all.map((p) => p.t);
  const eq = all.map((p) => p.equity);
  const tMin = Math.min(...ts);
  const tMax = Math.max(...ts);
  const eMin = Math.min(...eq);
  const eMax = Math.max(...eq);
  const ePad = (eMax - eMin) * 0.12 || 1;
  const lo = eMin - ePad;
  const hi = eMax + ePad;

  const x = (t: number) =>
    PAD.left + (tMax === tMin ? 0 : ((t - tMin) / (tMax - tMin)) * (W - PAD.left - PAD.right));
  const y = (e: number) =>
    H - PAD.bottom - ((e - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);

  const path = (pts: { t: number; equity: number }[]) =>
    pts.map((p, i) => `${i === 0 ? 'M' : 'L'}${x(p.t).toFixed(1)},${y(p.equity).toFixed(1)}`).join(' ');

  const gridlines = Array.from({ length: 5 }, (_, i) => {
    const e = lo + ((hi - lo) * i) / 4;
    const yy = y(e).toFixed(1);
    return `<line x1="${PAD.left}" y1="${yy}" x2="${W - PAD.right}" y2="${yy}" class="grid"/>
    <text x="${PAD.left - 10}" y="${Number(yy) + 4}" class="axis" text-anchor="end">${Math.round(e).toLocaleString('en-US')}</text>`;
  }).join('\n    ');

  // Mark every refusal, so the picture and the receipts agree.
  const marks = result.decisions
    .filter((d) => d.verdict !== 'EXECUTE')
    .map((d) => {
      const px = x(d.entry_ts_ms).toFixed(1);
      return `<line x1="${px}" y1="${PAD.top}" x2="${px}" y2="${H - PAD.bottom}" class="refusal"/>`;
    })
    .join('\n    ');

  const s = result.summary;
  const title = opts.title ?? 'Abstain — same strategy, with and without the gate';

  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${W} ${H}" width="${W}" height="${H}" role="img" aria-label="${esc(title)}">
  <style>
    .bg{fill:#0b0d12}
    .grid{stroke:#1e2430;stroke-width:1}
    .axis{fill:#6b7688;font:11px ui-monospace,SFMono-Regular,Menlo,monospace}
    .title{fill:#e6e9ef;font:600 15px ui-sans-serif,system-ui,sans-serif}
    .sub{fill:#8b95a7;font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
    .without{fill:none;stroke:#e5484d;stroke-width:2}
    .with{fill:none;stroke:#46a758;stroke-width:2.5}
    .refusal{stroke:#7c6aef;stroke-width:1;stroke-dasharray:3 3;opacity:.55}
    .legend{font:12px ui-monospace,SFMono-Regular,Menlo,monospace}
  </style>
  <rect class="bg" width="${W}" height="${H}"/>
  <text x="${PAD.left}" y="24" class="title">${esc(title)}</text>
  <text x="${PAD.left}" y="${H - 14}" class="sub">${s.trades} trades · ${s.refused} refused · max drawdown ${s.maxDrawdownWithoutPct}% → ${s.maxDrawdownWithPct}%</text>
    ${gridlines}
    ${marks}
  <path class="without" d="${path(result.withoutGate)}"/>
  <path class="with" d="${path(result.withGate)}"/>
  <g class="legend" transform="translate(${W - PAD.right - 250},${PAD.top - 16})">
    <line x1="0" y1="-4" x2="22" y2="-4" class="without"/>
    <text x="30" y="0" fill="#e5484d">without gate  ${s.pnlWithoutGate >= 0 ? '+' : ''}${s.pnlWithoutGate}</text>
    <line x1="0" y1="14" x2="22" y2="14" class="with"/>
    <text x="30" y="18" fill="#46a758">with gate     ${s.pnlWithGate >= 0 ? '+' : ''}${s.pnlWithGate}</text>
  </g>
</svg>`;
}

/** Terminal-readable summary. Goes in SUBMISSION.md next to the SVG. */
export function renderTable(result: ReplayResult): string {
  const rows = result.decisions.map(
    (d) =>
      `  ${String(d.seq).padStart(2)}  ${d.symbol.padEnd(10)} ${d.as_of}  ${d.verdict.padEnd(8)} ${
        d.failed.join(',') || '-'
      }`.trimEnd(),
  );
  const s = result.summary;
  return [
    '  #   SYMBOL     AS_OF       VERDICT  FAILED CHECKS',
    '  --  ---------- ----------  -------- -------------',
    ...rows,
    '',
    `  trades ${s.trades} · refused ${s.refused}`,
    `  pnl        without gate ${s.pnlWithoutGate}   with gate ${s.pnlWithGate}`,
    `  max drawdown  without ${s.maxDrawdownWithoutPct}%   with ${s.maxDrawdownWithPct}%`,
  ].join('\n');
}
