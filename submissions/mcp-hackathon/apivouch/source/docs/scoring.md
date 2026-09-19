# Deterministic readiness scoring

APIVouch reports six dimensions totaling 100 points:

| Dimension | Weight | Evidence |
|---|---:|---|
| Schema quality | 25 | Parameter, request, and successful response schemas |
| Documentation | 15 | Operation and parameter descriptions |
| Consistency | 15 | High/critical static and observed findings |
| Error handling | 15 | Documented client and server/default errors |
| Reliability | 15 | Bounded live probe coverage and outcomes |
| Agent usability | 15 | Stable operation IDs, clear inputs, deprecation, side-effect boundaries |

Without live observations, reliability receives only 5/15 points. Skipped and blocked operations receive no live-evidence credit. Warnings receive partial credit.

## Before and after

The source score and generated-contract score use the same evaluator. The generated score is not a promise that the upstream implementation changed. It measures the generated contract and MCP adapter, while live findings remain visible in the evidence pack.

The comparison response explicitly reports:

```json
{
  "before_score": 54,
  "after_score": 82,
  "improvement": 28,
  "basis": "re-analysis of the generated contract; no simulated score"
}
```

## Repeatability

Given the same contract and stored observations, the evaluator returns the same score and findings. No LLM is used in analysis, scoring, inference, or contract generation.
