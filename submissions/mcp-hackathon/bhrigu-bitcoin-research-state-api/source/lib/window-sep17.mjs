export const SEP_17_2026 = Object.freeze({
  id: "SEP_17_2026",
  boundary_utc: "2026-09-17T00:00:00Z",
  role: "precommitted_observation_boundary",
  baseline: Object.freeze({
    captured_at_utc: "2026-09-10T04:49:49.136Z",
    btcusdt_last_price: 78348.09,
    btcusdt_24h_change_pct: -0.983,
    btcusdt_24h_high: 79760,
    btcusdt_24h_low: 77770,
    bitcoin_tip_height: 966302
  }),
  provenance: Object.freeze({
    source_runtime_commit: "05a455ba1407f7b07de226f6c78eefda15b24880",
    market_crosscheck_last_price_usdt: 78348.10,
    market_crosscheck_abs_diff_usdt: 0.01,
    note: "Captured after SEP_10 boundary and committed before SEP_17 boundary."
  }),
  invariants: Object.freeze({
    retroactive_rewrite: "forbidden",
    price_target: false,
    trading_signal: false
  })
});
