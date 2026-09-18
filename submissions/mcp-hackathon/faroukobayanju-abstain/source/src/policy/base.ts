/**
 * The default policy, as a module rather than a file read.
 *
 * `readFileSync('policy.base.json')` crashed every Vercel invocation: a
 * serverless function's cwd is not the repo root, and a dynamic read is not
 * traced by the bundler so the file would not have shipped either. A module
 * import is bundled, has no cwd dependency, and cannot fail at runtime.
 *
 * `policy.base.json` remains committed as the human-readable artifact a
 * reviewer inspects. `test/checks.test.ts` asserts the two are identical, so
 * they cannot drift apart silently.
 */
import type { Policy } from '../types.js';

export const BASE_POLICY: Policy = {
  /** 15m live tick cadence, so one missed tick is tolerated. */
  max_signal_age_s: 1800,
  /** The one key that differs between the strict and permissive policies. */
  require_qualified: true,
  max_funding_rate: 0.0005,
  /** Starting value, NOT calibrated against observed OI. Declared as such. */
  max_oi_delta_pct: 15,
  /** Observed max drawdown was 7.62%; 5 fires in the June window and passes later. */
  max_drawdown_pct: 5,
  /** Measured: the only threshold that improves both pnl and drawdown on the 19-trade record. */
  max_cluster_size: 2,
  max_symbol_pct: 20,
  /** Observed maximum consecutive losses was exactly 3. */
  max_loss_streak: 3,
  min_notional: 10,
  max_notional: 50000,
};
