'use client';

import { useId, useState } from 'react';
import { DEMO_EQUITY_CURVE, TOO_SHORT_EQUITY_CURVE } from '@/lib/demo-curve';
import type { DemoEquityPoint } from '@/lib/demo-curve';
import type { EvidenceTier, SignificanceReport } from '@/lib/engine/significance';
import { evaluateRequest, postJson } from './api';
import type { ApiErrorBody, EvaluatePayload } from './api';
import { count, formatPeriods, percent, signed } from './format';
import styles from './RunPanel.module.css';

/**
 * Run it yourself.
 *
 * The same endpoint the hero uses, called from the browser against a curve the visitor
 * can edit. The refusal path is one click away on purpose: `insufficient_evidence` is
 * the product working, and it is presented as a decision Regimen made rather than as a
 * failure the page suffered. Genuine failures are rendered from the API's own envelope —
 * its code, its message, its remedy — because those three fields are more useful than
 * anything this component could invent.
 */

const TIER_WORD: Record<EvidenceTier, string> = {
  insufficient_evidence: 'Insufficient evidence',
  indistinguishable_from_luck: 'Indistinguishable from luck',
  weak: 'Weak',
  supported: 'Supported',
  strong: 'Strong',
};

function toneClass(tier: EvidenceTier): string {
  switch (tier) {
    case 'strong':
      return styles.toneStrong ?? '';
    case 'supported':
      return styles.toneSupported ?? '';
    case 'weak':
      return styles.toneWeak ?? '';
    case 'indistinguishable_from_luck':
      return styles.toneLuck ?? '';
    case 'insufficient_evidence':
      return styles.toneRefusal ?? '';
  }
}

function formatCurve(points: ReadonlyArray<DemoEquityPoint>): string {
  return `[\n${points.map((point) => `  {"t": "${point.t}", "equity": ${point.equity}}`).join(',\n')}\n]`;
}

interface ParsedCurve {
  readonly points: DemoEquityPoint[];
}

/** Accepts a bare array of points, or an object carrying one under `equity`. */
function parseCurve(raw: string): ParsedCurve | string {
  let value: unknown;
  try {
    value = JSON.parse(raw);
  } catch {
    return 'That is not valid JSON. Expected an array of {"t": "YYYY-MM-DD", "equity": number}.';
  }

  const candidate = Array.isArray(value) ? value : (value as { equity?: unknown })?.equity;
  if (!Array.isArray(candidate)) {
    return 'Expected a JSON array of equity points, or an object with an `equity` array.';
  }

  const points: DemoEquityPoint[] = [];
  for (const entry of candidate) {
    if (typeof entry !== 'object' || entry === null) {
      return 'Every entry must be an object with `t` and `equity`.';
    }
    const { t, equity } = entry as { t?: unknown; equity?: unknown };
    if ((typeof t !== 'string' && typeof t !== 'number') || typeof equity !== 'number') {
      return 'Every entry needs a timestamp `t` and a numeric `equity`.';
    }
    points.push({ t: String(t), equity });
  }
  return { points };
}

type PanelState =
  | { readonly kind: 'idle' }
  | { readonly kind: 'running' }
  | { readonly kind: 'report'; readonly report: SignificanceReport }
  | { readonly kind: 'error'; readonly error: ApiErrorBody };

export function RunPanel() {
  const textareaId = useId();
  const [source, setSource] = useState(() => formatCurve(DEMO_EQUITY_CURVE));
  const [parseError, setParseError] = useState<string | null>(null);
  const [state, setState] = useState<PanelState>({ kind: 'idle' });

  const load = (points: ReadonlyArray<DemoEquityPoint>) => {
    setSource(formatCurve(points));
    setParseError(null);
    setState({ kind: 'idle' });
  };

  const run = async () => {
    const parsed = parseCurve(source);
    if (typeof parsed === 'string') {
      setParseError(parsed);
      setState({ kind: 'idle' });
      return;
    }
    setParseError(null);
    setState({ kind: 'running' });

    const result = await postJson<EvaluatePayload>(
      '/api/v1/evaluate',
      evaluateRequest(parsed.points, 'pasted-track-record'),
    );

    setState(result.ok ? { kind: 'report', report: result.data.report } : { kind: 'error', error: result.error });
  };

  return (
    <div className={styles.panel}>
      <div className={styles.side}>
        <p className={styles.legend}>Input · equity curve</p>
        <p className={styles.hint}>
          One point per period, in any single consistent unit. Nothing is stored; the payload is analysed and
          discarded inside the request.
        </p>
        <label className={styles.legend} htmlFor={textareaId}>
          JSON equity points
        </label>
        <textarea
          id={textareaId}
          className={styles.textarea}
          spellCheck={false}
          value={source}
          onChange={(event) => setSource(event.target.value)}
        />
        {parseError ? (
          <p className={styles.parseError} role="alert">
            {parseError}
          </p>
        ) : null}
        <div className={styles.controls}>
          <button type="button" className="btn" onClick={run} disabled={state.kind === 'running'}>
            {state.kind === 'running' ? 'Running…' : 'Run'}
          </button>
          <button type="button" className="btnGhost" onClick={() => load(TOO_SHORT_EQUITY_CURVE)}>
            Load a too-short curve
          </button>
          <button type="button" className="btnGhost" onClick={() => load(DEMO_EQUITY_CURVE)}>
            Reset
          </button>
        </div>
      </div>

      <div className={styles.side} aria-live="polite" aria-busy={state.kind === 'running'}>
        <p className={styles.legend}>Verdict</p>
        <Results state={state} />
      </div>
    </div>
  );
}

function Results({ state }: { readonly state: PanelState }) {
  if (state.kind === 'idle') {
    return (
      <p className={styles.idle}>
        Awaiting a run.
        <br />
        The demo curve has an annualised Sharpe of 3.72. Press Run and watch it fail to clear the bar.
      </p>
    );
  }

  if (state.kind === 'running') {
    return (
      <p className={styles.idle}>
        Resampling · 2,000 stationary-bootstrap draws
        <br />
        This is computed, not looked up.
      </p>
    );
  }

  if (state.kind === 'error') {
    return <ErrorReport error={state.error} />;
  }

  return <EvidenceReport report={state.report} />;
}

function ErrorReport({ error }: { readonly error: ApiErrorBody }) {
  return (
    <div className={styles.errorBlock}>
      <p className={styles.errorCode}>{error.code}</p>
      <p className={styles.errorMessage}>{error.message}</p>
      {error.remedy ? (
        <p className={styles.errorRemedy}>
          <b>What to do — </b>
          {error.remedy}
        </p>
      ) : null}
    </div>
  );
}

function EvidenceReport({ report }: { readonly report: SignificanceReport }) {
  const { evidence, sample, performance } = report;
  const refused = evidence.tier === 'insufficient_evidence';
  const interval = evidence.sharpeConfidenceInterval;
  const zeroInside = interval !== null && interval.lower <= 0 && interval.upper >= 0;
  const minTrl = evidence.minimumTrackRecordLength;

  return (
    <div>
      <div className={styles.verdictBlock}>
        {refused ? <p className={styles.refusalTag}>Refused on purpose · not an error</p> : null}
        <p className={`${styles.verdictWord} ${toneClass(evidence.tier)}`}>{TIER_WORD[evidence.tier]}</p>
        <p className={styles.headline}>{evidence.headline}</p>
      </div>

      <ul className={styles.figures}>
        <li>
          <span className={styles.figureTerm}>Confidence (PSR)</span>
          <span className={styles.figureValue}>
            {evidence.probabilisticSharpe === null ? 'not computed' : percent(evidence.probabilisticSharpe)}
          </span>
        </li>
        <li>
          <span className={styles.figureTerm}>{interval ? `${(interval.level * 100).toFixed(0)}% interval` : 'Interval'}</span>
          <span className={styles.figureValue}>
            {interval ? `[${signed(interval.lower)}, ${signed(interval.upper)}]` : 'not computed'}
          </span>
          {zeroInside ? (
            <span className={styles.figureNote}>
              Zero is inside this interval — a Sharpe of zero stays consistent with this sample.
            </span>
          ) : null}
        </li>
        <li>
          <span className={styles.figureTerm}>MinTRL</span>
          <span className={styles.figureValue}>
            {minTrl === null ? 'not defined' : `${formatPeriods(minTrl)} periods`}
          </span>
          {evidence.periodsShortOfSignificance !== null && evidence.periodsShortOfSignificance > 0 ? (
            <span className={styles.figureNote}>
              {evidence.periodsShortOfSignificance} periods short of the length this claim needs.
            </span>
          ) : null}
        </li>
        <li>
          <span className={styles.figureTerm}>Usable returns</span>
          <span className={styles.figureValue}>
            {sample.usableReturns} of {sample.equityPointsSupplied} marks
          </span>
        </li>
        <li>
          <span className={styles.figureTerm}>Sharpe (annualised)</span>
          <span className={styles.figureValue}>
            {performance.sharpeAnnualised === null ? 'not annualisable' : performance.sharpeAnnualised.toFixed(2)}
          </span>
        </li>
      </ul>

      <p className={styles.rationaleLabel}>Why</p>
      <ul className={styles.rationale}>
        {evidence.rationale.map((sentence) => (
          <li key={sentence}>{sentence}</li>
        ))}
        {report.notes.map((note) => (
          <li key={note}>{note}</li>
        ))}
      </ul>

      {evidence.bootstrap ? (
        <p className={styles.meta}>
          {count(evidence.bootstrap.resamples)} stationary-bootstrap resamples · mean block{' '}
          {evidence.bootstrap.blockMeanLength} · seed {evidence.bootstrap.seed}
        </p>
      ) : null}
    </div>
  );
}
