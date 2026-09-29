# AI adjudication specification

## Purpose

The AI layer reads allowed evidence content and produces structured findings against a frozen agreement. It reduces the burden of reviewing unstructured work while preserving a separate, auditable settlement calculation.

The AI does not calculate, authorize, or execute payment.

## Authority boundary

### AI may

- suggest draft acceptance criteria before approval;
- map evidence to an existing criterion;
- assess whether evidence supports, contradicts, or does not address a criterion;
- propose a score and confidence;
- cite evidence IDs and relevant excerpts;
- identify missing evidence;
- identify conflicting claims;
- draft a plain-language explanation from the final ledger.

### AI may not

- change an activated agreement;
- alter weights, critical flags, amount, asset, or policy;
- create fictional evidence or evidence IDs;
- score against requirements absent from the agreement;
- produce the authoritative release or hold amount;
- override a conflict or manual-review gate;
- access credentials or execute external actions;
- claim legal authority or factual certainty it does not have.

## Provider boundary

Domain and application code depend on this conceptual interface:

```ts
interface ReviewProvider {
  reviewCriterion(input: ReviewCriterionInput, signal: AbortSignal): Promise<ProviderReviewOutput>;
  explainSettlement(input: ExplainSettlementInput, signal: AbortSignal): Promise<ProviderExplanationOutput>;
}
```

The initial hosted adapter may use the OpenAI Responses API with strict JSON Schema output. Provider-specific request and response objects remain inside `src/ai/providers/`.

A deterministic fake provider is mandatory for tests and local offline demos.

## Review input

Each criterion is reviewed independently unless a policy explicitly enables cross-criterion context.

```json
{
  "schemaVersion": 1,
  "caseId": "case_...",
  "agreementVersion": 3,
  "criterion": {
    "id": "docs",
    "description": "A new agent can reproduce one real call from the documentation.",
    "critical": false,
    "minimumEvidence": 1
  },
  "allowedEvidence": [
    {
      "id": "ev-docs",
      "kind": "artifact",
      "digest": "sha256:...",
      "contentType": "text/markdown",
      "content": "bounded normalized text",
      "sourceLabel": "README excerpt"
    }
  ],
  "reviewPolicy": {
    "minimumConfidence": 0.65,
    "criticalMinimumConfidence": 0.8
  }
}
```

The provider does not receive the agreement amount or criterion weight during evidence scoring. This reduces anchoring toward a desired payout.

## Review output

The provider must return strict structured output:

```json
{
  "schemaVersion": 1,
  "criterionId": "docs",
  "verdict": "partial",
  "score": 90,
  "confidence": 0.95,
  "evidenceCitations": [
    {
      "evidenceId": "ev-docs",
      "claim": "The quickstart reproduces the request and response.",
      "support": "The README includes an executable curl example."
    }
  ],
  "missingEvidence": [],
  "contradictions": [],
  "rationale": "The documented call is reproducible; one optional configuration detail is unclear.",
  "requirementsApplied": ["A new agent can reproduce one real call from the documentation."],
  "requirementsRejected": []
}
```

Allowed verdicts:

- `satisfied`
- `partial`
- `not_satisfied`
- `insufficient_evidence`
- `conflicting_evidence`
- `cannot_assess`

For `insufficient_evidence`, `conflicting_evidence`, or `cannot_assess`, the score must be null. These outputs do not become financial findings.

## Local validation

After provider output, Docket must verify:

1. the response matches the exact schema;
2. `criterionId` matches the requested criterion;
3. every cited evidence ID was supplied for that criterion;
4. every positive or negative factual claim has a citation;
5. the output did not add a requirement absent from the agreement;
6. score and verdict are compatible;
7. confidence is within zero to one;
8. the provider did not include an amount, weight, release, hold, wallet, or transaction instruction;
9. content and rationale stay within size bounds;
10. refusal or safety output is handled as `cannot_assess`, not parsed as a finding.

Invalid output is never repaired silently into a financial finding.

## Review pipeline

```text
load frozen agreement and evidence
  -> authorize tenant and case
  -> normalize and redact evidence
  -> enforce byte and token budgets
  -> review criteria independently
  -> validate provider output locally
  -> apply confidence and evidence gates
  -> optionally run independent second review
  -> detect reviewer conflicts
  -> accept structured findings or request clarification
  -> call settlement kernel
  -> generate explanation from the final ledger
  -> verify explanation against ledger
  -> persist provenance and events
```

## Review policy

Default policy, configurable per agreement before activation:

- minimum confidence for non-critical criterion: `0.65`;
- minimum confidence for critical criterion: `0.80`;
- independent second review required for critical criteria and high-value cases;
- conflict spread: existing agreement policy, default `35` points;
- no passing evidence: no score enters the settlement kernel;
- contradiction on a critical criterion: manual review or declared cap;
- any unknown requirement: ignored and recorded as rejected;
- any prompt injection found in evidence: treated as untrusted evidence text and never as an instruction.

Thresholds are product policy, not prompt text. The application enforces them after model output.

## Prompt structure

Every prompt version contains:

1. role and narrow authority;
2. the exact frozen criterion;
3. definitions for verdict, score, and confidence;
4. evidence blocks delimited as untrusted content;
5. instruction to ignore commands inside evidence;
6. prohibition on adding requirements;
7. citation requirements;
8. output schema;
9. explicit permission to return insufficient evidence;
10. examples maintained in the evaluation corpus, not improvised in production code.

Prompt changes require a new prompt version and an evaluation run before release.

## Agreement drafting AI

Drafting is advisory and separate from adjudication.

Input:

- task brief;
- amount and asset;
- desired delivery date;
- supplied constraints;
- optional template.

Output:

- proposed criteria;
- proposed weights totaling 100;
- critical flags;
- required evidence;
- ambiguities and questions;
- rationale for allocation.

No draft becomes active without explicit approval. Drafting AI must not imply that generated criteria were agreed by both parties.

## Settlement explanation AI

Explanation input contains only the frozen agreement summary, accepted findings, criterion ledger, reason codes, and final amounts calculated by the kernel.

The explanation output must:

- state recommendation-only status;
- name the release and hold amounts exactly;
- explain held value by criterion;
- mention critical caps or manual review;
- avoid claims not present in findings;
- never alter or recompute numbers.

The application verifies that every numeric amount in the output matches an allowed ledger value. If verification fails, use a deterministic template instead.

## Provider failure behavior

| Failure | Behavior |
| --- | --- |
| Timeout or connection failure | Retry once with jitter if deadline permits, then leave review recoverable |
| Rate limit | Respect retry guidance within the case deadline; otherwise show deferred state |
| Refusal | Record refusal and route criterion to manual review |
| Schema-invalid response | Do not use; retry only if classified as transient provider formatting failure |
| Hallucinated evidence ID | Reject output and flag model-quality failure |
| Context too large | Reduce through deterministic evidence selection or request narrower evidence |
| Provider unavailable | Permit trusted structured findings or manual review; never invent a score |
| Partial multi-criterion failure | Preserve successful criterion reviews and expose failed criteria; do not settle until policy allows |

## Data and privacy

- Send only evidence required for the criterion.
- Redact secrets and personal data before provider calls where possible.
- Require explicit tenant policy for hosted-model processing.
- Set provider storage off where supported.
- Record the provider's actual retention terms in product disclosures.
- Do not log raw evidence bodies or prompts by default.
- Store hashes, sizes, classifications, and correlation IDs for diagnostics.
- Support a deployment mode where AI review is disabled and only structured findings are accepted.

## Provenance record

Each review run records:

- review run ID;
- case and agreement version;
- criterion and evidence IDs/digests;
- provider and model identifier;
- prompt and schema version;
- sampling/reasoning configuration relevant to reproducibility;
- start/end time and latency;
- provider request ID;
- token usage and estimated cost;
- raw structured output or encrypted restricted copy according to retention policy;
- local validation result;
- accepted finding ID or failure reason.

API keys and full authorization headers are never recorded.

## Evaluation corpus

Maintain versioned fixtures for:

- complete evidence and full satisfaction;
- valuable partial completion;
- missing documentation;
- failed critical requirement;
- irrelevant evidence;
- contradictory artifacts;
- duplicate or forged-looking references;
- requirement introduced after agreement;
- prompt injection inside evidence;
- persuasive but unsupported claimant text;
- two reviewers with material disagreement;
- ambiguous acceptance language;
- model refusal;
- very long evidence requiring selection;
- asset amount designed to bias the model, confirming amount is withheld from scoring.

## Release thresholds

For the frozen evaluation corpus:

- schema validity: 100 percent;
- cited evidence IDs valid: 100 percent;
- financial fields emitted by AI: 0;
- unsupported new requirements accepted: 0;
- prompt-injection compliance: 0;
- manual-review recall on designated conflict/critical-gap cases: 100 percent;
- exact numeric explanation consistency: 100 percent or deterministic fallback;
- criterion score agreement within the fixture tolerance: at least 90 percent;
- no regression in deterministic settlement fixtures.

Any miss in a zero-tolerance category blocks release.

## Cost and latency controls

- Per-case model budget configured server-side.
- Per-criterion evidence and output token limits.
- Parallel reviews only within a bounded concurrency pool.
- Critical criteria may use a stronger or second model; routine criteria use the configured default.
- Cache only by agreement version, evidence digests, prompt version, schema version, and model identifier.
- Cached findings remain auditable and cannot cross tenants.
- Surface estimated and actual model cost to operators, not necessarily end users.
