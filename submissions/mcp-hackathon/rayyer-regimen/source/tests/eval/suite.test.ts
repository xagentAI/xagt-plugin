/**
 * The suite is a pre-registered claim, so these tests check the claim holds.
 *
 * The important one is the integrity test: every case declares a group, and the
 * generator independently computes ground truth. If a case labelled
 * `edge_provable` turns out to be shorter than the analytic MinTRL, the power
 * measurement built on it means nothing — and it would mean nothing silently.
 * The harness reports the same mismatch as a run failure; this test catches it
 * before anyone runs the harness.
 */

import { describe, expect, it } from 'vitest';

import {
  EVALUATION_SUITE,
  materialiseCase,
  suiteComposition,
  type CaseExpectation,
  type SuiteCase,
} from '../../src/lib/eval/suite';

const MINIMUM_SUITE_SIZE = 60;

/** The engine declines to grade anything below this many usable returns. */
const ENGINE_MINIMUM_USABLE_RETURNS = 20;

describe('suite shape', () => {
  it('is at least the pre-registered size', () => {
    expect(EVALUATION_SUITE.length).toBeGreaterThanOrEqual(MINIMUM_SUITE_SIZE);
  });

  it('has unique ids and unique seeds', () => {
    const ids = EVALUATION_SUITE.map((entry) => entry.id);
    expect(new Set(ids).size).toBe(ids.length);

    const seeds = EVALUATION_SUITE.map((entry) => (entry.kind === 'degenerate' ? entry.seed : entry.spec.seed));
    expect(new Set(seeds).size).toBe(seeds.length);
  });

  it('makes the false-positive traps the largest group', () => {
    const composition = suiteComposition();
    const others = (Object.entries(composition) as [CaseExpectation, number][]).filter(
      ([group]) => group !== 'no_edge',
    );
    for (const [, count] of others) expect(composition.no_edge).toBeGreaterThan(count);
  });

  it('covers every group, every distribution and every degenerate kind', () => {
    const composition = suiteComposition();
    for (const count of Object.values(composition)) expect(count).toBeGreaterThan(0);

    const distributions = new Set(
      EVALUATION_SUITE.flatMap((entry) => (entry.kind === 'synthetic' ? [entry.spec.distribution] : [])),
    );
    expect(distributions).toEqual(new Set(['normal', 'skewed', 'fat_tailed']));

    const kinds = new Set(
      EVALUATION_SUITE.flatMap((entry) => (entry.kind === 'degenerate' ? [entry.degenerate] : [])),
    );
    expect(kinds).toEqual(
      new Set(['constant_equity', 'too_few_points', 'duplicate_timestamps', 'unsorted_timestamps']),
    );
  });

  it('spreads the no-edge traps across all three shapes', () => {
    const noEdge = EVALUATION_SUITE.filter(
      (entry): entry is Extract<SuiteCase, { kind: 'synthetic' }> =>
        entry.kind === 'synthetic' && entry.expectation === 'no_edge',
    );
    for (const distribution of ['normal', 'skewed', 'fat_tailed'] as const) {
      expect(noEdge.filter((entry) => entry.spec.distribution === distribution).length).toBeGreaterThanOrEqual(6);
    }
  });
});

describe('every declared expectation matches the generated ground truth', () => {
  const materialised = EVALUATION_SUITE.map((entry) => ({ entry, generated: materialiseCase(entry) }));

  it('no_edge cases genuinely have no edge', () => {
    for (const { entry, generated } of materialised) {
      if (entry.expectation !== 'no_edge') continue;
      expect(generated.truth.hasEdge, entry.id).toBe(false);
      expect(generated.truth.trueSharpePerPeriod, entry.id).toBe(0);
    }
  });

  it('edge_provable cases have a real edge that clears the analytic MinTRL', () => {
    for (const { entry, generated } of materialised) {
      if (entry.expectation !== 'edge_provable') continue;
      expect(generated.truth.hasEdge, entry.id).toBe(true);
      expect(generated.truth.provableAtThisLength, entry.id).toBe(true);
    }
  });

  it('edge_not_provable cases have a real edge the sample cannot support', () => {
    for (const { entry, generated } of materialised) {
      if (entry.expectation !== 'edge_not_provable') continue;
      expect(generated.truth.hasEdge, entry.id).toBe(true);
      expect(generated.truth.provableAtThisLength, entry.id).toBe(false);
      // Long enough that the engine actually grades them, so declining is a
      // decision rather than a side effect of the 20-return floor.
      expect(generated.truth.periods, entry.id).toBeGreaterThanOrEqual(ENGINE_MINIMUM_USABLE_RETURNS);
    }
  });

  it('regime cases carry a factor series, and only the planted ones differ between buckets', () => {
    for (const { entry, generated } of materialised) {
      if (entry.expectation !== 'regime_planted' && entry.expectation !== 'regime_null') continue;
      expect(generated.regimes, entry.id).toBeDefined();
      expect(generated.truth.regimeFactor, entry.id).toBe('vix');
      expect(generated.regimes?.observations.length, entry.id).toBe(generated.truth.periods);
      expect(generated.truth.plantedRegimeEffect, entry.id).toBe(entry.expectation === 'regime_planted');
    }
  });

  it('degenerate cases are traps and carry no regime series', () => {
    for (const { entry, generated } of materialised) {
      if (entry.expectation !== 'degenerate') continue;
      expect(generated.truth.degenerate, entry.id).not.toBeNull();
      expect(generated.regimes, entry.id).toBeUndefined();
    }
  });

  it('produces a strictly positive equity curve for every case', () => {
    for (const { entry, generated } of materialised) {
      expect(generated.record.equity.length, entry.id).toBeGreaterThan(0);
      expect(generated.record.equity.every((point) => point.equity > 0), entry.id).toBe(true);
    }
  });

  it('materialises identically on a second pass', () => {
    const first = materialiseCase(EVALUATION_SUITE[0] as SuiteCase);
    const second = materialiseCase(EVALUATION_SUITE[0] as SuiteCase);
    expect(second.record.equity).toEqual(first.record.equity);
  });
});
