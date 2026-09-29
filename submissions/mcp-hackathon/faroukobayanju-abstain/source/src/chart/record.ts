/**
 * Record the point-in-time market data the replay needs.
 *
 *   npm run record    (requires NEXUS_API_KEY)
 *
 * The replay evaluates each trade as of its entry date, so it needs real
 * funding and open interest for every (symbol, entry-date) pair in the trade
 * record. Without them DATA_GAP fails closed on every decision — correct
 * behaviour, useless chart.
 *
 * Writes one cassette per pair, so the chart a reviewer regenerates is built
 * from the same recorded bytes we used.
 */
import { existsSync, readFileSync, writeFileSync } from 'node:fs';
import { NexusClient, cassetteName } from '../nexus/client.js';
import { previousIso } from '../nexus/fetch-all.js';
import { isoDate } from './replay.js';
import type { Trades } from '../types.js';

async function main(): Promise<void> {
  const key = process.env['NEXUS_API_KEY'];
  if (!key) throw new Error('NEXUS_API_KEY is required to record market cassettes');

  const trades = (JSON.parse(readFileSync('fixtures/get_strategy_trades.json', 'utf8')) as { content: Trades }).content;
  const client = new NexusClient({ mode: 'live', apiKey: key });

  const pairs = new Map<string, { symbol: string; asOf: string }>();
  for (const t of trades.trades) {
    const asOf = isoDate(t.entry_ts_ms);
    pairs.set(`${t.symbol}|${asOf}`, { symbol: t.symbol, asOf });
  }
  console.log(`${pairs.size} (symbol, date) pairs from ${trades.trades.length} trades`);

  let ok = 0;
  let missing = 0;
  for (const { symbol, asOf } of pairs.values()) {
    // OI_SHOCK diffs against the previous UTC day, so record that snapshot too
    // or the offline replay cannot reproduce the check.
    const prev = previousIso(asOf);
    for (const [tool, date] of [
      ['get_historical_funding', asOf],
      ['get_open_interest', asOf],
      ['get_open_interest', prev],
    ] as const) {
      const args = { symbol, as_of: date };
      const file = `fixtures/${cassetteName(tool, args)}`;
      if (existsSync(file)) continue; // already recorded by an earlier pair
      const res = await client.call<unknown>(tool, args);
      if (res.ok) {
        writeFileSync(file, JSON.stringify({ ok: true, name: tool, content: res.value }, null, 2));
        ok++;
      } else {
        console.warn(`  ${res.outcome.padEnd(7)} ${tool} ${symbol} ${date}`);
        missing++;
      }
    }
  }
  console.log(`recorded ${ok}, unavailable ${missing}`);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
