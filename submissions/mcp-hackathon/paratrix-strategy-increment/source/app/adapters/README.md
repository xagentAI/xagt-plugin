# Input adapters

`demos.list_cases()` returns summaries of five public examples. `demos.get_case(id)` returns independent objects and raises `KeyError` for an unknown ID. IDs are `aimm-weight`, `duplicate`, `cash`, `missing-day`, and `tradeoff`. The last four include teaching curves explicitly labeled `synthetic`. Every example interval has already been observed and cannot be treated as an unseen holdout.

Each read of the recorded local AIMM fixtures checks the manifest's SHA-256 and point counts. In pinned upstream revision `dd711507690450e9c4c9b170829b01f1e7d7f1b6`, `src/backtest/engines/perp.py:363-382,731-742` marks equity at bar close but writes the opening label as `ts`. Adaptation preserves equity values, uses the harness's explicit initial capital of 10,000 USDT, sets the initial boundary to the first raw `ts`, and maps daily observations to `ts + 86400000`. Original files and the manifest remain unchanged. The resulting valuation interval runs from 2026-06-02 00:00 UTC to 2026-08-01 00:00 UTC, with 60 daily returns. Worker builds embed the original fixture bytes and apply the same checks.

## Supported sources and Nexus status

The Worker supports built-in examples and complete simulated equity JSON imports. External Nexus imports are disabled in both Wrangler development and Cloudflare deployment. Source status is unconfigured/unverified with no public references, and `/v1/nexus/import` returns `source_unavailable` without contacting Nexus.

Every imported curve must include initial valuation, valuation clock, complete daily observations, costs and cash-flow declarations. The service does not infer these fields from sampled chart points. The caller's source label and provenance are preserved as declarations; successful validation does not authenticate upstream data.

See [METHOD](../../docs/METHOD.md) and the [implementation contract](../../docs/IMPLEMENTATION-CONTRACT.md) for method and state definitions.
