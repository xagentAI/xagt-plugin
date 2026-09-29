/**
 * The methodology, in one place.
 *
 * Served as an MCP resource, rendered on the docs page, and quoted in the README, so
 * there is exactly one description of what the numbers mean and it cannot drift
 * between surfaces.
 */
export const METHODOLOGY_MARKDOWN = `# How Regimen decides

Regimen answers one question about a track record: **is the measured performance
distinguishable from luck, and under which market conditions does it hold?**

Everything below is computed from the equity curve. Nothing is taken on trust from the
source's own dashboard — where the source publishes its own figures, Regimen recomputes
them and reports the difference.

## 1. The Sharpe ratio is an estimate, not a fact

A Sharpe ratio measured over a short window carries an error bar wide enough to swallow
the claim it is making. Regimen therefore never reports a Sharpe ratio alone.

**Probabilistic Sharpe Ratio (PSR)** — the probability that the *true* Sharpe exceeds a
benchmark, given how long the sample is and how skewed and fat-tailed it is:

\`\`\`
PSR(SR*) = Φ( (SR − SR*) · √(n − 1) / √(1 − γ₃·SR + ((γ₄ − 1)/4)·SR²) )
\`\`\`

where SR is the per-period Sharpe, SR* the benchmark, n the number of returns, γ₃ the
sample skewness and γ₄ the sample (non-excess) kurtosis. Negative skew and fat tails
*reduce* the confidence, which is the correct direction and the opposite of what a bare
Sharpe ratio implies.

**Minimum Track Record Length (MinTRL)** — how many periods the record would need before
the claim could be made at the requested confidence:

\`\`\`
MinTRL = 1 + [1 − γ₃·SR + ((γ₄ − 1)/4)·SR²] · ( Φ⁻¹(confidence) / (SR − SR*) )²
\`\`\`

When the observed Sharpe does not exceed the benchmark, MinTRL does not exist: no amount
of additional history makes that claim significant, and Regimen says so rather than
returning a large number.

**Deflated Sharpe Ratio (DSR)** — the same statement, corrected for selection. If twenty
configurations were tried and the best one is being shown, the benchmark is not zero but
the expected maximum Sharpe of twenty draws:

\`\`\`
SR*₀ = √Var(trial Sharpes) · [ (1 − γ)·Φ⁻¹(1 − 1/N) + γ·Φ⁻¹(1 − 1/(N·e)) ]
\`\`\`

with γ the Euler–Mascheroni constant. DSR is only reported when trial Sharpes are
supplied; it is never silently assumed to equal PSR.

**Bootstrap interval** — a stationary bootstrap (Politis & Romano, 1994) with geometric
block lengths, which preserves serial dependence that an i.i.d. resample would destroy.
Seeded, so a published interval reproduces exactly.

## 2. Evidence tiers

The tier is a published function of the statistics, not a judgement call:

| Tier | Condition |
|---|---|
| \`insufficient_evidence\` | fewer than 20 usable returns, or no dispersion at all |
| \`indistinguishable_from_luck\` | governing confidence below 90% |
| \`weak\` | 90–95%, or an interval that still contains zero |
| \`supported\` | ≥95% and the bootstrap lower bound clears zero |
| \`strong\` | ≥99%, interval clears zero, and the record is at least MinTRL long |

The governing confidence is the Deflated Sharpe Ratio when trial Sharpes were supplied,
and the Probabilistic Sharpe Ratio otherwise.

## 3. Regime attribution

Each period's return is joined to the market conditions that held on the UTC date it
closed on. Every factor is read with an explicit \`as_of\` date, so a bucket can only ever
contain information that was knowable at the time.

Factors with a conventional scale (VIX, funding, positioning, sentiment, trend state) use
**fixed edges chosen in advance**. Factors without one are split into terciles of their
own observed range, and that is disclosed per factor, because tercile edges do depend on
the sample.

**The permutation test is the point.** Slice a return series eight ways and the
best-looking bucket will look good by chance alone. Regimen therefore compares the
observed best-to-worst Sharpe spread against the spread produced by randomly reshuffling
the regime labels thousands of times, and reports the resulting p-value. Without it a
regime map is just a machine for finding flattering subsets.

## 4. Regimen attacking itself

Two controls with known answers run against every analysis:

- **Mean-centred control** — the strategy's own returns with their mean subtracted. Same
  volatility, same shape, true Sharpe exactly zero. A correct engine must grade it near
  50%. If it does not, the engine is broken and the report says so instead of hiding it.
- **Null-strategy distribution** — many simulated strategies with the same length and
  volatility but no edge, each graded, so the real strategy's confidence can be placed as
  a percentile against pure luck.

## 5. What Regimen does not do

It does not trade, hold funds, custody keys, or sign anything. It does not audit smart
contracts, score wallets or transactions, or perform security or compliance analysis. It
reads a track record and reports what the evidence supports.
`;
