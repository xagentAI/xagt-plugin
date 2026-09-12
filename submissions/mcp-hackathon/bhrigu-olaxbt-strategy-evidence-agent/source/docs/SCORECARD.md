# X-Agent OlaXBT judge-first scorecard

## Primary product truth

**OLAXBT = strategy + signal authority.**
**BHRIGU = evidence interpretation layer.**
**Job = Can an agent trust the evidence context behind this OlaXBT strategy signal right now?**

## Hard-gate evidence

| Gate | Evidence |
| --- | --- |
| Callable | REST `POST /v1/strategy-evidence`; MCP `bhrigu_get_olaxbt_strategy_evidence` |
| Real | Four live OlaXBT Nexus sources: signal, metrics, trades, equity |
| Reproducible | Node 22+, lockfile, deterministic tests, exact commit binding |
| Safe | Read-only; no trading execution, wallet, payment, transfer, withdrawal, or second signal |
| Useful for agents | One machine-readable evidence object with source status, contradictions, limitations, and explicit authority |

## Score-maximizing evidence

### Real agent/user value
An agent does not merely receive a direction. It receives the evidence context needed to decide how much confidence to place in the *context* around an OlaXBT signal, while OlaXBT retains signal authority.

### Demonstrated capability quality
Observed upstream fields are normalized exactly: `trade_intent` supplies direction and `win_rate_pct` supplies OlaXBT source win rate. Direction is never inferred from prose, and recent-trade positive share is not substituted for source win rate. Four upstream source statuses are independently visible.

### Engineering / maintainability
The new MCP tool calls the same `buildStrategyEvidence()` path as REST, preventing two product implementations. No new runtime dependency or trading engine is introduced.

### MCP productization readiness
Exactly one trading-track MCP tool is added: `bhrigu_get_olaxbt_strategy_evidence`. Input is constrained to `BTC/USDT`, output is structured and read-only, and authority flags are explicit.

### Adoption / operating potential
The capability is small enough for another agent to call directly, requires no caller credential, and keeps the upstream Nexus key server-side. Existing Bitcoin Temporal Evidence remains inherited context rather than the first-screen product object.

## Non-claims

No guarantee of profitability, future return, signal correctness, or trading outcome. No autonomous execution. No second BHRIGU signal.
