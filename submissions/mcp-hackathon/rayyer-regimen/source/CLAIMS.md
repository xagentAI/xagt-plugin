# Claims ledger

Every public statement Regimen makes about itself, tagged by what backs it. A product
that grades other people's evidence has no business being vague about its own.

**Evidence tiers**

| Tier | Meaning |
|---|---|
| `REPRODUCIBLE` | You can re-derive it from this repository with one command. |
| `VERIFIED-LIVE` | Observable right now against the deployed service. |
| `MODELED` | Computed from simulation or synthetic data, not from live market results. |
| `NOT-CLAIMED` | Something a reader might reasonably assume, that we are explicitly not asserting. |

---

## Statistics

| Claim | Tier | How to check |
|---|---|---|
| The Probabilistic Sharpe Ratio implements Bailey & López de Prado (2012). | `REPRODUCIBLE` | `src/lib/stats/sharpe.ts` carries the formula and its derivation; `tests/stats/sharpe.test.ts` asserts known-answer cases computed independently of this code. |
| Minimum Track Record Length is the algebraic inverse of PSR. | `REPRODUCIBLE` | A test evaluates PSR at exactly `minTRL` periods and asserts it equals the requested confidence to 1e-12. |
| The Deflated Sharpe Ratio implements Bailey & López de Prado (2014). | `REPRODUCIBLE` | `deflatedSharpeRatio` in `src/lib/stats/sharpe.ts`, tested against both variance conventions. |
| Bootstrap intervals are reproducible. | `REPRODUCIBLE` | Same seed yields a bit-identical interval; asserted in `tests/stats/bootstrap.test.ts`. |
| `normalCdf` is accurate to ~1e-14 relative out to Φ(−37). | `REPRODUCIBLE` | Reference values in `tests/stats/numeric.test.ts` were generated from SciPy's Cephes `ndtr`, not from this implementation. |
| The engine's false-positive rate is near the nominal 5%. | `MODELED` | Measured on seeded synthetic series, not on live strategies. See `EVAL.md`. |
| No public statistics function returns `NaN` or `Infinity`. | `REPRODUCIBLE` | A package-wide sweep walks every success payload from hostile inputs and asserts no non-finite value appears. |

## The service

| Claim | Tier | How to check |
|---|---|---|
| The live service reports the exact commit it was built from. | `VERIFIED-LIVE` | `GET /api/health` and `GET /.well-known/xagent-verification.json`. The value is read from build metadata, not hard-coded, so it cannot drift from the source. |
| The MCP endpoint speaks revision 2026-07-28. | `VERIFIED-LIVE` | `POST /mcp` with `MCP-Protocol-Version: 2026-07-28`; `GET /mcp` returns 405 as the revision requires. |
| Every MCP tool advertises an output schema. | `VERIFIED-LIVE` | `tools/list` — each entry carries `outputSchema`, and calls return `structuredContent`. |
| Requests from an unrecognised `Origin` are refused. | `VERIFIED-LIVE` | `curl -H 'Origin: https://evil.example' .../api/v1/status` returns 403. |
| A reviewer can exercise the inline analyses with no credentials. | `VERIFIED-LIVE` | The `curl` commands in `verification/README.md` use no key. |
| The server is listed in the official MCP Registry. | `VERIFIED-LIVE` | `curl https://registry.modelcontextprotocol.io/v0/servers?search=regimen` returns `io.github.RaYYeR220/regimen` at version 1.0.0, pointing at this deployment. |
| Point-in-time market data carries no lookahead. | `REPRODUCIBLE` | Every upstream read passes an explicit `as_of` date; see `fetchRegimes` in `src/lib/sources/nexus/adapter.ts`. |

## Explicitly NOT claimed

- **Not claimed:** that a `supported` or `strong` verdict means a strategy will make money.
  The verdict is a statement about evidence, not a forecast.
- **Not claimed:** that Regimen detects every real edge. A genuine edge on a short record is
  correctly reported as unproven; that is the intended behaviour, and the evaluation scores
  it as a pass rather than a miss.
- **Not claimed:** conformance with the whole MCP specification. The official conformance
  suite's transport, `ping` and `tools/list` scenarios pass; the remainder exercise
  reference-server fixtures (named test tools, sampling, logging, image and audio content)
  that Regimen does not implement. The measured result is printed in the README rather than
  summarised as a pass.
- **Not claimed:** that the regime factors are exhaustive or the bucket edges optimal. They
  are conventional boundaries fixed in advance, which is a deliberate trade against fitting
  the edges to the data.
- **Not claimed:** any security, audit, risk-scoring or compliance capability. Regimen does
  not inspect contracts, wallets or transactions, and nothing in it is designed to.
- **Not claimed:** that the service holds, moves, or is capable of moving funds. It is
  read-only and holds no keys of its own.
