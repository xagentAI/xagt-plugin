# AlphaLitmus Baseline and Gap Register

This preserves the **provided pre-change baseline**, not a final verification run: Python **3.12.10**, application import succeeded, **14 tests passed in 3.23 seconds**, and no baseline lint configuration was present. These facts were supplied for the baseline; they are not newly measured results or external evidence. Final test counts and timings are intentionally reserved for the owner.

The following eleven areas distinguish the initial gaps from current implementation/documentation and outstanding evidence. Local code inspection is not production assurance.

| Area | Baseline gap / risk | Current treatment and remaining evidence |
| --- | --- | --- |
| 1. Identity and contracts | Legacy naming and loosely described interfaces | AlphaLitmus naming, `alpha-litmus` health/proof, sole `ALPHALITMUS_COMMIT`, strict nested challenge contracts |
| 2. Reproducibility | Setup existed but no complete quality configuration | Python 3.12, pytest/Ruff/strict mypy configuration; isolated final run and transitive lock still needed |
| 3. Replay methodology | Reference replay could be mistaken for Nexus validation | Exact next-open, split, cost and mark formulas documented; no bound-strategy replay |
| 4. Failure experiments | Simple cost stress did not establish a failure frontier | Bounded cost/delay/EMA domains and per-dimension minima; no global robustness claim |
| 5. Statistical uncertainty | Small samples and selection bias | IID trade bootstrap/order permutation limitations; no PSR or selection-adjusted estimate |
| 6. Reconciliation | Summary metrics could be overinterpreted | Numeric comparisons always insufficient; explicit run/symbol contradictions mismatch; binding/completeness remain unresolved |
| 7. Certificates | Legacy hashes could be mistaken for attestation | Canonical checksums plus replay verification; no signature, authenticity or trusted timestamp |
| 8. Agent interfaces | Legacy three-tool interface | Four typed tools; REST/MCP demos return full reports; replay input is `report.request` |
| 9. Security and privacy | Strategy-bound secret and unauthenticated service risks | External secrets, opt-in Nexus, authenticated proxy deployment requirement; no live security assessment |
| 10. Packaging and operations | Basic non-root Docker, no healthcheck/labels | Python 3.12 non-root Dockerfile, OCI labels, healthcheck, exclusions; CLI installed but daemon unavailable, build not passed |
| 11. Submission and provenance | No public commit/deployment/rights proof | Official requirements reviewed 2026-09-19; real evidence, owner authorization and submission remain external |

## Legacy Artifacts

`reports/btc-history-input.json`, `reports/btc-history-report.json` and `reports/history-receipt.json` remain unchanged legacy negative artifacts, not new AlphaLitmus certificates. The receipt records a caller-local fetch claim dated 2026-09-15 from `https://data-api.binance.vision/api/v3/klines`, 1461 bars, and dataset digest `db3b8c75e8feffd03e68855cb4dc71b916204477e0f3c29a8e45cd58fe7cf7c8`. This task did not refetch or authenticate those data.

The receipt records `WAIT`, test baseline and guarded return **-3.0863%**, drawdown **26.0245%**, and **3 closed trades** each. It records insufficient trades, no guard improvement, nonprofitable cost stress, and drawdown above the legacy research limit. Those are negative historical local observations, not live Nexus validation or profitability evidence. Keep original names, timestamps, schema and hashes; do not relabel or regenerate them to imply current provenance. `reports/` stays excluded from Git and Docker by default.
