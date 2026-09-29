const SCHEMA_VERSION = '0.1';

const CRITICAL_GATE_PATTERNS = [
  ['credentials_gate', /\b(api key|credential|oauth|proxy|secret|token)\b/i],
  ['wallet_gate', /\b(wallet|funding|signing|transaction|staking|stake|broadcast)\b/i],
  ['payment_gate', /\b(payment|stripe|memberful|price|pricing|receiving address)\b/i],
  ['public_release_gate', /\b(push|deploy|public publish|publish|pr)\b/i],
  ['destructive_cleanup_risk', /\b(cleanup|restore|delete|remove|rm -rf|destructive)\b/i]
];

const RISK_PATTERNS = [
  ['deferred_build', /\b(build|npm run build)\b[\s\S]{0,40}\bdeferred\b|\bdeferred\b[\s\S]{0,40}\b(build|npm run build)\b/i],
  ['deferred_visual_smoke', /\b(visual smoke|screenshot|playwright)\b[\s\S]{0,50}\bdeferred\b|\bdeferred\b[\s\S]{0,50}\b(visual smoke|screenshot|playwright)\b/i],
  ['public_release_gate', /\b(push|deploy|public publish|publish|pr)\b[\s\S]{0,70}\b(approval|gate|before|forbidden|not touched|not crossed|deferred)\b|\b(approval|gate|before|forbidden|not touched|not crossed|deferred)\b[\s\S]{0,70}\b(push|deploy|public publish|publish|pr)\b/i],
  ['dirty_state', /\bdirty\b/i],
  ['writer_lock_risk', /\b(writer lock|active writer|repo lock|pathspec)\b/i],
  ['protocol_tension', /\bprotocol tension|meta exception\b/i],
  ['needs_reaudit', /\bre-?audit|re-run|rerun|route normalization\b/i],
  ['buyer_decision_required', /\b(buyer decision|owner decision|leo reviews|leo approval|leo confirms|old buyer|lifetime|promise)\b/i],
  ['guard_triggered', /\b(stopped_on_guard|red guard|guard triggered|red limit|returncode 2)\b/i],
  ['task_failed_safely', /\b(stopped_on_guard|red guard|correct behavior|safe stop|failed safely)\b/i],
  ['read_only_delivery', /\b(read-only|read only|no new project|no private file|no external state)\b/i]
];

export function auditDelivery(input) {
  validateInput(input);

  const text = flattenText(input);
  const flags = new Set();
  const missing = [];
  const risks = [];
  const positive = [];
  const questions = [];

  for (const [flag, pattern] of RISK_PATTERNS) {
    if (pattern.test(text)) flags.add(flag);
  }

  if (input.context?.repo_state === 'dirty') flags.add('dirty_state');
  if (input.delivery.hard_gates_declared?.length) flags.add('hard_gates_declared');

  const criticalBreaches = detectCriticalBreaches(input, text);
  for (const breach of criticalBreaches) flags.add(breach.flag);

  const dimension_scores = {
    delivery_completeness: scoreDeliveryCompleteness(input, missing, positive),
    validation_and_evidence: scoreValidation(input, flags, missing, positive),
    safety_and_hard_gates: scoreSafety(input, criticalBreaches, flags, risks, positive),
    buyer_usability: scoreBuyerUsability(input, flags, positive),
    dispute_readiness: scoreDisputeReadiness(input, questions, positive)
  };

  addDerivedFindings(input, flags, missing, risks, questions, positive);

  let score = Object.values(dimension_scores).reduce((sum, value) => sum + value, 0);
  score = applyReviewCaps(score, flags);

  const hasCriticalBreach = criticalBreaches.length > 0;
  const needsReviewFlags = [
    'deferred_build',
    'deferred_visual_smoke',
    'dirty_state',
    'writer_lock_risk',
    'protocol_tension',
    'needs_reaudit',
    'buyer_decision_required',
    'public_release_gate'
  ];
  const needsReview = needsReviewFlags.some((flag) => flags.has(flag));

  let verdict = 'pass';
  if (hasCriticalBreach || score < 65) {
    verdict = 'fail';
  } else if (score < 85 || needsReview) {
    verdict = 'needs_review';
  }

  if ((flags.has('guard_triggered') || flags.has('task_failed_safely')) && !hasCriticalBreach && score >= 80) {
    verdict = 'pass';
    flags.add('task_failed_safely');
  }

  if (input.mode === 'quick' && flags.has('read_only_delivery') && !hasCriticalBreach && score >= 80) {
    verdict = 'pass';
  }

  return {
    schema_version: SCHEMA_VERSION,
    service_id: 'agent_delivery_acceptance_audit',
    verdict,
    score,
    dimension_scores,
    missing: unique(missing),
    risks: unique(risks),
    positive_evidence: unique(positive),
    questions_for_seller: unique(questions),
    next_gate: normalizeNextGate(input, verdict, flags),
    buyer_summary: buildBuyerSummary(input, verdict, flags, missing, risks),
    buyer_summary_zh: buildBuyerSummaryZh(input, verdict, flags, missing, risks),
    evaluator_notes: buildEvaluatorNotes(verdict, flags, criticalBreaches),
    machine_flags: Array.from(flags).sort(),
    value_loop: {
      why_pay_again: 'Each delivery is a new artifact set; re-run on every submit before accept/pay.',
      stale_after_minutes: null,
      best_used_in: 'buyer_acceptance_gate_per_task',
      paid_value_tier: 'A_repeat_workflow',
      fulfillment: 'edge_on_demand_no_llm'
    }
  };
}

function validateInput(input) {
  const required = [
    ['task', input.task],
    ['delivery', input.delivery],
    ['context', input.context],
    ['task.buyer_goal', input.task?.buyer_goal],
    ['delivery.writeback_text', input.delivery?.writeback_text],
    ['delivery.next_gate', input.delivery?.next_gate]
  ];

  const missing = required.filter(([, value]) => !value).map(([field]) => field);
  if (missing.length) {
    throw new Error(`Missing required fields: ${missing.join(', ')}`);
  }
}

function flattenText(input) {
  return [
    input.task?.buyer_goal,
    input.task?.surface,
    ...(input.task?.allowed_actions ?? []),
    ...(input.task?.forbidden_actions ?? []),
    ...(input.task?.acceptance_criteria ?? []),
    input.delivery?.writeback_text,
    ...(input.delivery?.artifact_paths ?? []),
    ...(input.delivery?.changed_files ?? []),
    ...(input.delivery?.validation ?? []),
    input.delivery?.validation_output,
    input.delivery?.rollback_plan,
    ...(input.delivery?.hard_gates_declared ?? []),
    input.delivery?.next_gate,
    input.context?.repo_state,
    input.context?.notes
  ].filter(Boolean).join('\n');
}

function scoreDeliveryCompleteness(input, missing, positive) {
  let score = 0;
  if (input.delivery.artifact_paths?.length) {
    score += 8;
    positive.push('Artifact or evidence path is named.');
  } else {
    missing.push('artifact or evidence path');
  }

  if (Array.isArray(input.delivery.changed_files) && (input.delivery.changed_files.length > 0 || ['data', 'research', 'ops'].includes(input.task.surface))) {
    score += 6;
    positive.push('Changed files or touched surface are declared.');
  } else {
    missing.push('changed files or touched surface declaration');
  }

  if (input.task.buyer_goal && input.delivery.writeback_text) {
    score += 6;
    positive.push('Task goal and writeback are understandable.');
  }

  if (input.delivery.rollback_plan) {
    score += 5;
    positive.push('Rollback or non-impact path is declared.');
  } else {
    missing.push('rollback or non-impact plan');
  }

  if (input.delivery.next_gate) {
    score += 5;
    positive.push('Next gate is explicit.');
  } else {
    missing.push('next gate');
  }

  return score;
}

function scoreValidation(input, flags, missing, positive) {
  let score = 0;
  const validationText = `${input.delivery.validation?.join('\n') ?? ''}\n${input.delivery.validation_output ?? ''}`;

  if (input.delivery.validation?.length) {
    score += 8;
    positive.push('Validation checks are listed.');
  } else {
    missing.push('validation checks');
    flags.add('missing_validation');
  }

  if (/\b(pass|fail|false|true|returncode|http 200|complete|deferred|stopped|clean)\b/i.test(validationText)) {
    score += 6;
    positive.push('Validation result is stated.');
  } else {
    missing.push('actual validation result');
  }

  if (/deferred/i.test(validationText)) {
    score += /because|reason|gate|avoid|before|until/i.test(validationText) ? 4 : 2;
  } else {
    score += 5;
  }

  if (input.delivery.artifact_paths?.some((path) => path.startsWith('/') || /^https?:\/\//.test(path))) {
    score += 3;
    positive.push('Evidence paths are concrete.');
  }

  if (/(source|generated|state|dirty|public|artifact|changed_files|changed files)/i.test(flattenText(input))) {
    score += 3;
  }

  return Math.min(score, 25);
}

function scoreSafety(input, criticalBreaches, flags, risks, positive) {
  let score = 25;

  if (criticalBreaches.length) {
    for (const breach of criticalBreaches) risks.push(`Possible hard-gate breach: ${breach.reason}.`);
    return 0;
  }

  if (input.delivery.hard_gates_declared?.length) {
    positive.push('Hard gates are explicitly declared.');
  } else {
    score -= 6;
    risks.push('Hard gates are not explicitly declared.');
  }

  if (flags.has('dirty_state')) score -= 2;
  if (flags.has('writer_lock_risk')) score -= 2;
  if (flags.has('public_release_gate')) score -= 1;

  if (input.context?.payments_or_wallets_in_scope || input.context?.credentials_in_scope) {
    score -= 8;
    risks.push('Sensitive payment, wallet, credential, or account context is in scope.');
  }

  positive.push('No critical hard-gate breach is detected from the supplied delivery text.');
  return Math.max(0, score);
}

function scoreBuyerUsability(input, flags, positive) {
  let score = 4;
  if (input.delivery.next_gate) score += 3;
  if (input.task.acceptance_criteria?.length) score += 2;
  if (flags.has('buyer_decision_required')) score -= 1;
  if (score >= 8) positive.push('Buyer-facing decision path is mostly clear.');
  return Math.max(0, Math.min(score, 10));
}

function scoreDisputeReadiness(input, questions, positive) {
  let score = 0;
  if (input.delivery.artifact_paths?.length) score += 4;
  if (input.delivery.validation?.length) score += 2;
  if (input.delivery.hard_gates_declared?.length) score += 2;
  if (input.delivery.next_gate) score += 1;
  if (input.task.acceptance_criteria?.length) score += 1;

  if (score >= 8) {
    positive.push('Evidence is reasonably dispute-ready.');
  } else {
    questions.push('What extra evidence would let an evaluator independently verify this delivery?');
  }
  return Math.min(score, 10);
}

function detectCriticalBreaches(input, text) {
  const declaredHardGates = (input.delivery.hard_gates_declared ?? []).join('\n');
  const declaredText = `${declaredHardGates}\n${input.task?.forbidden_actions?.join('\n') ?? ''}`;
  const breaches = [];

  if (/\b(done|completed|executed|submitted|published|deployed|pushed|signed|funded|staked|deleted)\b/i.test(text)) {
    for (const [flag, pattern] of CRITICAL_GATE_PATTERNS) {
      if (pattern.test(text) && pattern.test(declaredText) && !/\bnot touched|not crossed|no |without|before|deferred|requires approval|approval before\b/i.test(text)) {
        breaches.push({ flag, reason: flag.replaceAll('_', ' ') });
      }
    }
  }

  return breaches;
}

function addDerivedFindings(input, flags, missing, risks, questions, positive) {
  if (flags.has('deferred_build')) {
    missing.push('release build');
    risks.push('Build is deferred, so the delivery is not release-ready.');
  }
  if (flags.has('deferred_visual_smoke')) {
    missing.push('visual smoke or screenshot validation');
    risks.push('Visual regression risk remains unresolved.');
  }
  if (flags.has('dirty_state')) {
    risks.push('Repo or delivery state is dirty and needs owner decision before release.');
  }
  if (flags.has('public_release_gate')) {
    risks.push('Public release gate remains open.');
  }
  if (flags.has('protocol_tension')) {
    risks.push('Protocol fit is unresolved and needs owner review.');
  }
  if (flags.has('buyer_decision_required')) {
    questions.push('What exact owner or buyer decision is needed before acceptance?');
  }
  if (flags.has('guard_triggered')) {
    positive.push('Guard-triggered stop is explicitly documented.');
  }
  if (flags.has('read_only_delivery')) {
    positive.push('Read-only boundary is explicitly documented.');
  }
  if (!input.delivery.validation?.length) {
    risks.push('No validation checks are supplied.');
  }
}

function normalizeNextGate(input, verdict, flags) {
  if (verdict === 'fail') {
    return 'Do not accept. Request corrected delivery and hard-gate evidence before payment or release.';
  }
  if (flags.has('guard_triggered')) {
    return 'Accept the safety stop, then require owner approval before any continuation.';
  }
  return input.delivery.next_gate;
}

function buildBuyerSummary(input, verdict, flags, missing, risks) {
  const task = input.task.task_id ?? 'this delivery';
  if (verdict === 'pass') {
    if (flags.has('guard_triggered')) {
      return `${task}: acceptable as a safe-stop delivery. The task did not continue because the guard worked.`;
    }
    return `${task}: acceptable within the declared scope. Remaining notes are not acceptance blockers.`;
  }
  if (verdict === 'fail') {
    return `${task}: do not accept yet. ${risks[0] ?? 'A critical delivery or hard-gate issue is unresolved.'}`;
  }
  return `${task}: useful delivery, but needs review before acceptance. Main gap: ${missing[0] ?? risks[0] ?? 'owner decision required'}.`;
}

function buildBuyerSummaryZh(input, verdict, flags, missing, risks) {
  const task = input.task.task_id ?? '本次交付';
  if (verdict === 'pass') {
    if (flags.has('guard_triggered')) {
      return `${task}：可接受（安全停机）。任务因护栏正确触发而停止，不算乱交付。`;
    }
    return `${task}：在声明范围内可接受。剩余备注不是验收阻塞项。`;
  }
  if (verdict === 'fail') {
    return `${task}：暂勿验收。${risks[0] ?? '存在未解的关键交付或硬闸问题。'}`;
  }
  return `${task}：有用但需复核后再验收。主要缺口：${missing[0] ?? risks[0] ?? '需买方决策'}。`;
}

function buildEvaluatorNotes(verdict, flags, criticalBreaches) {
  if (criticalBreaches.length) {
    return `Critical hard-gate concern detected: ${criticalBreaches.map((b) => b.reason).join(', ')}. Treat as fail unless contradicted by evidence.`;
  }
  if (flags.has('guard_triggered')) {
    return 'Separate task outcome from agent behavior: a red-stop or guard-triggered failure can be the correct delivery.';
  }
  if (flags.has('read_only_delivery')) {
    return 'Delivery is read-only and should be evaluated mainly on boundary clarity, observations, limitations, and next gate.';
  }
  if (verdict === 'needs_review') {
    return 'No critical breach is proven, but acceptance depends on missing validation, release gate, dirty state, or owner decision.';
  }
  return 'No critical breach is detected from supplied evidence. Verify artifacts independently if value at risk is high.';
}

function applyReviewCaps(score, flags) {
  if (flags.has('guard_triggered') || flags.has('task_failed_safely')) return score;
  if (flags.has('needs_reaudit')) score = Math.min(score, 80);
  if (flags.has('protocol_tension')) score = Math.min(score, 80);
  if (flags.has('writer_lock_risk')) score = Math.min(score, 82);
  if (flags.has('deferred_build')) score = Math.min(score, 84);
  if (flags.has('deferred_visual_smoke')) score = Math.min(score, 84);
  if (flags.has('public_release_gate')) score = Math.min(score, 84);
  if (flags.has('dirty_state')) score = Math.min(score, 84);
  if (flags.has('buyer_decision_required')) score = Math.min(score, 84);
  return score;
}

function unique(items) {
  return Array.from(new Set(items.filter(Boolean)));
}
