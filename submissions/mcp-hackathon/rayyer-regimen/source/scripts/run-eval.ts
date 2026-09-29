/**
 * Run the pre-registered evaluation suite and write the scorecard.
 *
 *     pnpm eval
 *
 * Produces two artifacts at the repository root:
 *
 *  - `EVAL.md` — the human-readable scorecard.
 *  - `eval-results.json` — the same data, machine-readable.
 *
 * Neither artifact carries a timestamp, and nothing in the pipeline reads a
 * clock or an unseeded random source. Re-running on a clean checkout therefore
 * produces byte-identical files, which means a diff on `EVAL.md` is always a
 * change in the engine's behaviour and never noise. That is the property that
 * makes it worth committing.
 *
 * Exits non-zero when the run fails its pre-registered targets, so CI can gate
 * on it.
 */

import { writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  runEvaluation,
  type CalibrationBucket,
  type CaseOutcome,
  type EvaluationReport,
  type ScoredRate,
} from '../src/lib/eval/harness';

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const REPRODUCE_COMMAND = 'pnpm eval';

/** A rate as a percentage with its counts, or a dash when the group was empty. */
function formatRate(value: ScoredRate): string {
  if (value.value === null) return 'n/a (0 cases)';
  return `${(value.value * 100).toFixed(1)}% (${value.numerator}/${value.denominator})`;
}

function formatNumber(value: number | null, digits: number): string {
  return value === null ? '—' : value.toFixed(digits);
}

function verdict(observed: ScoredRate, target: number, direction: 'at_most' | 'at_least'): string {
  if (observed.value === null) return 'not evaluated';
  const ok = direction === 'at_most' ? observed.value <= target : observed.value >= target;
  return ok ? 'met' : 'MISSED';
}

function targetsTable(report: EvaluationReport): string {
  const t = report.targets;
  const m = report.metrics;
  const rows: string[] = [
    '| Measure | What it counts | Pre-registered target | Measured | Verdict |',
    '| --- | --- | --- | --- | --- |',
    `| False positive rate | No-edge records graded supported/strong | <= ${t.maxFalsePositiveRate.toFixed(2)} | ${formatRate(m.falsePositiveRate)} | ${verdict(m.falsePositiveRate, t.maxFalsePositiveRate, 'at_most')} |`,
    `| Power | Provable real edges graded supported/strong | >= ${t.minPower.toFixed(2)} | ${formatRate(m.power)} | ${verdict(m.power, t.minPower, 'at_least')} |`,
    `| Correct refusals | Degenerate inputs returning insufficient_evidence | ${t.minCorrectRefusals.toFixed(2)} | ${formatRate(m.correctRefusals)} | ${verdict(m.correctRefusals, t.minCorrectRefusals, 'at_least')} |`,
    `| Restraint | Unprovable real edges the engine declined to claim | >= ${t.minRestraint.toFixed(2)} | ${formatRate(m.restraint)} | ${verdict(m.restraint, t.minRestraint, 'at_least')} |`,
    `| Regime detection | Planted regime effects found at p <= ${m.regime.alpha} | >= ${t.minRegimeDetectionRate.toFixed(2)} | ${formatRate(m.regime.detectionRate)} | ${verdict(m.regime.detectionRate, t.minRegimeDetectionRate, 'at_least')} |`,
    `| Regime false positives | Unplanted factors claimed at p <= ${m.regime.alpha} | <= ${t.maxRegimeFalsePositiveRate.toFixed(2)} | ${formatRate(m.regime.falsePositiveRate)} | ${verdict(m.regime.falsePositiveRate, t.maxRegimeFalsePositiveRate, 'at_most')} |`,
  ];
  return rows.join('\n');
}

function calibrationTable(buckets: readonly CalibrationBucket[]): string {
  const rows: string[] = [
    '| Reported confidence (PSR) | Cases | Truly had an edge | Observed frequency |',
    '| --- | --- | --- | --- |',
  ];
  for (const bucket of buckets) {
    const observed = bucket.observedFraction === null ? '—' : `${(bucket.observedFraction * 100).toFixed(1)}%`;
    rows.push(`| ${bucket.label} | ${bucket.count} | ${bucket.withEdge} | ${observed} |`);
  }
  return rows.join('\n');
}

function caseTable(cases: readonly CaseOutcome[]): string {
  const rows: string[] = [
    '| Case | Group | Expectation | Periods | True SR | Provable | Observed tier | PSR | Result |',
    '| --- | --- | --- | --- | --- | --- | --- | --- | --- |',
  ];
  for (const outcome of cases) {
    rows.push(
      [
        outcome.id,
        outcome.group,
        outcome.expectation,
        String(outcome.periods),
        outcome.trueSharpePerPeriod.toFixed(3),
        outcome.provableAtThisLength ? 'yes' : 'no',
        outcome.observedTier,
        formatNumber(outcome.probabilisticSharpe, 4),
        outcome.pass ? 'pass' : 'FAIL',
      ]
        .map((cell) => `| ${cell} `)
        .join('') + '|',
    );
  }
  return rows.join('\n');
}

function renderMarkdown(report: EvaluationReport): string {
  const { settings, metrics } = report;
  const failedCases = report.cases.filter((outcome) => !outcome.pass);
  const composition = settings.composition;

  const lines: string[] = [];

  lines.push('# Regimen evaluation scorecard');
  lines.push('');
  lines.push(
    'Regimen claims to tell you whether a track record is distinguishable from luck. This file is the check on that claim.',
  );
  lines.push('');
  lines.push(
    `The engine was run against ${settings.suiteSize} synthetic strategies whose truth is known in advance: some have a real edge, most have none, a few are not strategies at all. The suite and the targets below were fixed before the engine was ever run against them, and are not adjusted afterwards. A missed target is a finding, not a prompt to move the target.`,
  );
  lines.push('');
  lines.push(`Reproduce this file exactly: \`${REPRODUCE_COMMAND}\``);
  lines.push('');
  lines.push(`**Result: ${report.passed ? 'PASSED' : 'FAILED'}**`);
  lines.push('');

  if (!report.passed) {
    lines.push('Targets missed:');
    lines.push('');
    for (const failure of report.failures) lines.push(`- ${failure}`);
    lines.push('');
  }

  lines.push('## Targets and measured results');
  lines.push('');
  lines.push(targetsTable(report));
  lines.push('');
  lines.push(
    `"Claimed" means the engine returned ${settings.confidentTiers.join(' or ')}. \`weak\` is not counted as a claim: the engine describes it as "positive but not convincing", and hedging is the behaviour we want from it.`,
  );
  lines.push('');
  lines.push(
    `Restraint is the measure that is easy to skip and hardest to fake. Those ${metrics.restraint.denominator} cases carry a genuine edge on a sample shorter than the analytic minimum track record length for that edge at ${(settings.provabilityConfidence * 100).toFixed(0)}% confidence. The evidence is real and unprovable at the same time, and declining to claim it is the right answer.`,
  );
  lines.push('');

  lines.push('## Calibration');
  lines.push('');
  lines.push(
    'When the engine reports a Probabilistic Sharpe Ratio of 0.95, roughly 95% of the records it says that about should really have an edge. This table checks that across the suite.',
  );
  lines.push('');
  lines.push(calibrationTable(report.calibration));
  lines.push('');
  lines.push(
    'Read this against the suite composition rather than as an absolute: the suite is deliberately loaded with edgeless records, so the base rate in the low bands is low by construction. What matters is that the observed frequency climbs with the reported confidence and gets close to it at the top.',
  );
  lines.push('');

  lines.push('## Regime detection');
  lines.push('');
  lines.push(
    `Each planted case hides its entire edge inside high-VIX periods. Each null case is built identically — same factor series, same bucket split — with no difference between the buckets. The permutation test should find the first group and stay quiet on the second.`,
  );
  lines.push('');
  lines.push(
    `- Planted effects found: ${formatRate(metrics.regime.detectionRate)} at p <= ${metrics.regime.alpha}`,
  );
  lines.push(
    `- Effects claimed where nothing was planted: ${formatRate(metrics.regime.falsePositiveRate)} at p <= ${metrics.regime.alpha}`,
  );
  lines.push('');

  if (report.integrityWarnings.length > 0) {
    lines.push('## Suite integrity warnings');
    lines.push('');
    lines.push(
      'A case whose declared group disagrees with the generator ground truth measures nothing. These invalidate their group:',
    );
    lines.push('');
    for (const warning of report.integrityWarnings) lines.push(`- ${warning}`);
    lines.push('');
  }

  if (failedCases.length > 0) {
    lines.push('## Failing cases');
    lines.push('');
    lines.push(
      'Each line carries the sample skewness the engine measured next to the true skewness of the distribution the record was drawn from. On short windows those two numbers can be very far apart, and the Probabilistic Sharpe Ratio corrects for non-normality using the sample one.',
    );
    lines.push('');
    for (const outcome of failedCases) {
      lines.push(
        `- \`${outcome.id}\` — ${outcome.note} True Sharpe ${outcome.trueSharpePerPeriod.toFixed(3)}, observed ${formatNumber(outcome.observedSharpePerPeriod, 3)} over ${outcome.periods} periods; sample skewness ${formatNumber(outcome.observedSkewness, 2)} against a true ${outcome.populationSkewness.toFixed(2)}.`,
      );
    }
    lines.push('');
  }

  lines.push('## Suite composition');
  lines.push('');
  lines.push('| Group | Cases | Pass rule |');
  lines.push('| --- | --- | --- |');
  lines.push(`| no_edge | ${composition.no_edge} | must not be graded supported/strong |`);
  lines.push(`| edge_provable | ${composition.edge_provable} | should be graded supported/strong |`);
  lines.push(`| edge_not_provable | ${composition.edge_not_provable} | must not be graded supported/strong |`);
  lines.push(`| regime_planted | ${composition.regime_planted} | planted factor permutation p <= ${settings.regimeAlpha} |`);
  lines.push(`| regime_null | ${composition.regime_null} | planted factor permutation p > ${settings.regimeAlpha} |`);
  lines.push(`| degenerate | ${composition.degenerate} | must return insufficient_evidence |`);
  lines.push('');

  lines.push('## Settings');
  lines.push('');
  lines.push(`- Benchmark Sharpe: ${settings.benchmarkSharpe} (per period) — "is there any edge at all?"`);
  lines.push(`- Bootstrap resamples: ${settings.bootstrapResamples}, seed ${settings.significanceSeed}`);
  lines.push(`- Regime permutations: ${settings.permutationResamples}, seed ${settings.regimeSeed}`);
  lines.push(
    `- Moment matching: ${settings.momentMatching} — shapes are standardised by their population moments, so a no-edge sample can still look good by luck. That is what makes the false positive rate a measurement rather than an identity.`,
  );
  lines.push('');

  lines.push('## Every case');
  lines.push('');
  lines.push(caseTable(report.cases));
  lines.push('');

  return lines.join('\n');
}

function printSummary(report: EvaluationReport): void {
  const m = report.metrics;
  const summary = [
    `Regimen evaluation — ${report.settings.suiteSize} cases — ${report.passed ? 'PASSED' : 'FAILED'}`,
    `  False positive rate : ${formatRate(m.falsePositiveRate)}  (target <= ${report.targets.maxFalsePositiveRate})`,
    `  Power               : ${formatRate(m.power)}  (target >= ${report.targets.minPower})`,
    `  Correct refusals    : ${formatRate(m.correctRefusals)}  (target ${report.targets.minCorrectRefusals})`,
    `  Restraint           : ${formatRate(m.restraint)}  (target >= ${report.targets.minRestraint})`,
    `  Regime detection    : ${formatRate(m.regime.detectionRate)}  (target >= ${report.targets.minRegimeDetectionRate})`,
    `  Regime false pos.   : ${formatRate(m.regime.falsePositiveRate)}  (target <= ${report.targets.maxRegimeFalsePositiveRate})`,
  ];
  for (const failure of report.failures) summary.push(`  ! ${failure}`);
  // eslint-disable-next-line no-console
  console.log(summary.join('\n'));
}

const report = runEvaluation();

const markdownPath = join(REPO_ROOT, 'EVAL.md');
const jsonPath = join(REPO_ROOT, 'eval-results.json');

writeFileSync(markdownPath, `${renderMarkdown(report)}`, 'utf8');
writeFileSync(jsonPath, `${JSON.stringify(report, null, 2)}\n`, 'utf8');

printSummary(report);
// eslint-disable-next-line no-console
console.log(`\nWrote ${markdownPath}\nWrote ${jsonPath}`);

if (!report.passed) process.exit(1);
