# Service Spec

Status: draft_local_only
Service: Agent Deliverable Auditor

## Proposed endpoint

```text
POST /audit-agent-deliverable
```

## Request schema

```json
{
  "schema_version": "0.1",
  "mode": "quick | full | evaluator",
  "task": {
    "task_id": "string",
    "buyer_goal": "string",
    "surface": "repo | website | research | data | ops | other",
    "allowed_actions": ["string"],
    "forbidden_actions": ["string"],
    "acceptance_criteria": ["string"]
  },
  "delivery": {
    "writeback_text": "string",
    "artifact_paths": ["string"],
    "changed_files": ["string"],
    "validation": ["string"],
    "validation_output": "string",
    "rollback_plan": "string",
    "hard_gates_declared": ["string"],
    "next_gate": "string"
  },
  "context": {
    "repo_state": "clean | dirty | unknown | not_applicable",
    "public_publish_requested": false,
    "payments_or_wallets_in_scope": false,
    "credentials_in_scope": false,
    "notes": "string"
  }
}
```

## Response schema

```json
{
  "schema_version": "0.1",
  "verdict": "pass | needs_review | fail",
  "score": 0,
  "dimension_scores": {
    "delivery_completeness": 0,
    "validation_and_evidence": 0,
    "safety_and_hard_gates": 0,
    "buyer_usability": 0,
    "dispute_readiness": 0
  },
  "missing": ["string"],
  "risks": ["string"],
  "positive_evidence": ["string"],
  "questions_for_seller": ["string"],
  "next_gate": "string",
  "buyer_summary": "string",
  "evaluator_notes": "string",
  "machine_flags": ["string"]
}
```

## Scoring rubric

Total: 100 points.

### Delivery completeness - 30

- 8 artifact or output exists and is named.
- 6 changed files or touched surfaces are declared.
- 6 task goal and scope are understandable.
- 5 rollback or non-impact path is declared.
- 5 next gate is explicit.

### Validation and evidence - 25

- 8 validation commands or checks are listed.
- 6 actual result is included, not just claimed.
- 5 deferred validation is named with reason.
- 3 evidence paths or URLs are concrete.
- 3 source / generated / state files are separated.

### Safety and hard gates - 25

- 7 no unauthorized push / deploy / public publish.
- 5 no unauthorized credentials / API key / OAuth / proxy action.
- 5 no unauthorized wallet / funding / signing / transaction / staking.
- 4 no destructive cleanup or broad repo mutation.
- 4 active writer / ownership / pathspec risk is addressed when relevant.

### Buyer usability - 10

- 4 verdict is clear enough for acceptance decision.
- 3 buyer-facing summary is concise.
- 3 next action is concrete.

### Dispute readiness - 10

- 4 evidence can be independently inspected.
- 3 open questions are listed.
- 3 evaluator notes separate facts from judgment.

## Verdict thresholds

- `pass`: score >= 85 and no critical hard-gate breach.
- `needs_review`: score 65-84, or any unresolved release / buyer-decision / validation gap.
- `fail`: score < 65, missing core artifact, no validation, unclear scope, or hard-gate breach.

Critical hard-gate breach always caps verdict at `fail`.

## Machine flags

Suggested flags:

- `missing_artifact`
- `missing_validation`
- `deferred_build`
- `deferred_visual_smoke`
- `public_release_gate`
- `credentials_gate`
- `wallet_gate`
- `payment_gate`
- `writer_lock_risk`
- `dirty_state`
- `destructive_cleanup_risk`
- `scope_mismatch`
- `dispute_ready`

