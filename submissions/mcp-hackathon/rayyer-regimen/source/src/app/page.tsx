import { headers } from 'next/headers';
import Link from 'next/link';
import { PersistenceScope } from '@/components/PersistenceScope';
import { RunPanel } from '@/components/RunPanel';
import { ScopeReadout, ScopeStatus, ScopeUnavailable } from '@/components/ScopeReadout';
import type { ReadoutField } from '@/components/ScopeReadout';
import { evaluateRequest, postJson, selfAttackRequest } from '@/components/api';
import type { EvaluatePayload, SelfAttackPayload } from '@/components/api';
import { count, formatPeriods, percent, signed } from '@/components/format';
import { DEMO_EQUITY_CURVE } from '@/lib/demo-curve';
import type { EvidenceTier } from '@/lib/engine/significance';

/**
 * The landing page runs the product rather than describing it.
 *
 * Every figure on the glass comes from a server-side call to this deployment's own
 * `/api/v1/evaluate` and `/api/v1/self-attack` against the published demo curve — the
 * same curve the verification evidence uses — so the page cannot quietly disagree with
 * the engine. Nothing here is typed in by hand.
 *
 * If those calls fail the page still renders: the hero keeps its claim and the readout
 * says plainly that the live figures are unavailable. A landing page that 500s because a
 * sub-request failed is worse than one that admits it.
 */

export const revalidate = 300;

const SELF_ATTACK_SIMULATIONS = 500;
const REQUEST_TIMEOUT_MS = 30_000;

interface HeroFigures {
  readonly tier: EvidenceTier;
  readonly sharpeAnnualised: number | null;
  readonly probabilisticSharpe: number | null;
  readonly interval: { readonly lower: number; readonly upper: number; readonly level: number } | null;
  readonly usableReturns: number;
  readonly pointsSupplied: number;
  readonly minimumTrackRecordLength: number | null;
  readonly periodsShort: number | null;
  readonly resamples: number | null;
  readonly empiricalPValue: number | null;
  readonly nullSimulations: number | null;
  readonly engineSane: boolean;
}

type HeroState = { readonly ok: true; readonly figures: HeroFigures } | { readonly ok: false; readonly reason: string };

/**
 * The origin to call.
 *
 * The forwarded protocol is trusted where a proxy sets it and defaults to https, which
 * is right for every deployed environment. With no host header at all — a build-time
 * render, a worker with no request in scope — the loopback address and the port the
 * server is actually listening on is the only address that can work.
 */
async function selfOrigin(): Promise<string> {
  const incoming = await headers();
  const host = incoming.get('host');
  if (!host) return `http://127.0.0.1:${process.env.PORT ?? 3000}`;
  const protocol = incoming.get('x-forwarded-proto') ?? 'https';
  return `${protocol}://${host}`;
}

interface CacheEntry {
  readonly at: number;
  readonly state: HeroState;
}

// Cached rather than recomputed per visitor. A failure is held only briefly, so a
// transient outage does not pin the "unavailable" state in place for five minutes.
let cache: CacheEntry | null = null;
const OK_TTL_MS = revalidate * 1000;
const FAIL_TTL_MS = 15_000;

async function loadHero(): Promise<HeroState> {
  const now = Date.now();
  if (cache && now - cache.at < (cache.state.ok ? OK_TTL_MS : FAIL_TTL_MS)) return cache.state;

  const origin = await selfOrigin();
  const timeout = () => AbortSignal.timeout(REQUEST_TIMEOUT_MS);

  const [evaluated, attacked] = await Promise.all([
    postJson<EvaluatePayload>(
      `${origin}/api/v1/evaluate`,
      evaluateRequest(DEMO_EQUITY_CURVE, 'regimen-demo-curve'),
      { signal: timeout() },
    ),
    postJson<SelfAttackPayload>(
      `${origin}/api/v1/self-attack`,
      selfAttackRequest(DEMO_EQUITY_CURVE, 'regimen-demo-curve', SELF_ATTACK_SIMULATIONS),
      { signal: timeout() },
    ),
  ]);

  let state: HeroState;
  if (!evaluated.ok) {
    state = { ok: false, reason: `${evaluated.error.code} — ${evaluated.error.message}` };
  } else {
    const { evidence, performance, sample } = evaluated.data.report;
    const nullDistribution = attacked.ok ? attacked.data.report.nullDistribution : null;
    state = {
      ok: true,
      figures: {
        tier: evidence.tier,
        sharpeAnnualised: performance.sharpeAnnualised,
        probabilisticSharpe: evidence.probabilisticSharpe,
        interval: evidence.sharpeConfidenceInterval,
        usableReturns: sample.usableReturns,
        pointsSupplied: sample.equityPointsSupplied,
        minimumTrackRecordLength: evidence.minimumTrackRecordLength,
        periodsShort: evidence.periodsShortOfSignificance,
        resamples: evidence.bootstrap?.resamples ?? null,
        empiricalPValue: nullDistribution?.empiricalPValue ?? null,
        nullSimulations: nullDistribution?.simulations ?? null,
        engineSane: attacked.ok ? attacked.data.report.verdict === 'engine_sane' : false,
      },
    };
  }

  cache = { at: now, state };
  return state;
}

const TIER_WORD: Record<EvidenceTier, string> = {
  insufficient_evidence: 'INSUFFICIENT',
  indistinguishable_from_luck: 'LUCK',
  weak: 'WEAK',
  supported: 'SUPPORTED',
  strong: 'STRONG',
};

/** The six fields of the scope readout — the only numbers above the fold. */
function readoutFields(figures: HeroFigures): ReadoutField[] {
  const fields: ReadoutField[] = [];

  if (figures.sharpeAnnualised !== null) {
    fields.push({ key: 'SHARPE', value: figures.sharpeAnnualised.toFixed(2), tone: 'lit' });
  }
  if (figures.probabilisticSharpe !== null) {
    fields.push({ key: 'PSR', value: percent(figures.probabilisticSharpe), tone: 'lit' });
  }
  if (figures.interval) {
    fields.push({
      key: `CI${(figures.interval.level * 100).toFixed(0)}`,
      value: `[${signed(figures.interval.lower)}, ${signed(figures.interval.upper)}]`,
      tone: figures.interval.lower <= 0 ? 'warn' : 'lit',
    });
  }
  fields.push({
    key: 'n',
    value:
      figures.minimumTrackRecordLength === null
        ? String(figures.usableReturns)
        : `${figures.usableReturns} / ${formatPeriods(figures.minimumTrackRecordLength)}`,
    tone: (figures.periodsShort ?? 0) > 0 ? 'warn' : 'lit',
  });
  if (figures.empiricalPValue !== null) {
    fields.push({
      key: 'p(luck)',
      value: figures.empiricalPValue.toFixed(3),
      tone: figures.empiricalPValue <= 0.05 ? 'lit' : 'flare',
    });
  }
  fields.push({
    key: 'VERDICT',
    value: TIER_WORD[figures.tier],
    tone: figures.tier === 'strong' || figures.tier === 'supported' ? 'lit' : figures.tier === 'weak' ? 'warn' : 'flare',
  });

  return fields;
}

export default async function Home() {
  const hero = await loadHero();
  const figures = hero.ok ? hero.figures : null;

  const resamples = figures?.resamples ?? 2000;
  const status = hero.ok
    ? `Sweep live · ${count(resamples)} resamples · ${figures?.usableReturns ?? 0} periods`
    : 'Sweep offline · figures not recomputed';

  return (
    <div className="shell">
      <a className="skipLink" href="#claim">
        Skip to the claim
      </a>

      <header className="masthead">
        <span className="mark">Regimen</span>
        <span className="markSub">Statistical validation desk · does not trade · holds no funds</span>
        <nav className="mastheadNav">
          <Link className="navLink" href="/methodology">
            Methodology
          </Link>
        </nav>
      </header>

      <main>
        <PersistenceScope points={DEMO_EQUITY_CURVE}>
          <ScopeStatus live={hero.ok}>{status}</ScopeStatus>
          <h1 className="heroTitle" id="claim">
            A Sharpe ratio is an estimate. Regimen tells you whether it is <em>a fact</em>.
          </h1>
          {hero.ok ? (
            <ScopeReadout fields={readoutFields(hero.figures)} />
          ) : (
            <ScopeUnavailable reason={hero.reason} />
          )}
          <p className="heroSub">
            Probabilistic Sharpe, Deflated Sharpe, Minimum Track Record Length and a regime-conditional breakdown —
            with a permutation test, so a flattering subset cannot pass itself off as an edge.
          </p>
          <div className="heroCta">
            <a className="btn" href="#run">
              Run it on a track record
            </a>
            <Link className="btnQuiet" href="/methodology">
              Read the methodology
            </Link>
          </div>
        </PersistenceScope>

        <section className="band">
          <div className="bandSplit">
            <div className="bandProse">
              <p className="bandLabel">The asset · how the band is made</p>
              <h2 className="bandHeading">
                The band is not drawn. It is what two thousand resamples leave behind.
              </h2>
              <p>
                Every trace on the glass is this track record with its periods drawn again at random. Where the
                paths pile up the glow is bright; where only a few went it is thin — so the confidence interval is
                made of evidence rather than painted on as a translucent ribbon. Hold the scope and the decay stops,
                and you watch it build.
              </p>
              {figures ? (
                <p>
                  <strong>
                    {figures.pointsSupplied} marks were supplied and {figures.usableReturns} usable returns came out
                    of them.
                  </strong>{' '}
                  {figures.minimumTrackRecordLength === null
                    ? 'The observed Sharpe does not clear the benchmark, so no length of history would make the claim significant.'
                    : `${formatPeriods(figures.minimumTrackRecordLength)} are needed before the claim clears ${(
                        (figures.interval?.level ?? 0.95) * 100
                      ).toFixed(0)}% — ${figures.periodsShort ?? 0} more than are here.`}{' '}
                  {figures.interval && figures.interval.lower <= 0 ? (
                    <>
                      Zero is still inside the interval, which is why the verdict on this record is{' '}
                      <span className="warn">{TIER_WORD[figures.tier].toLowerCase()}</span> and not{' '}
                      <span className="lit">supported</span>.
                    </>
                  ) : null}
                </p>
              ) : (
                <p>
                  The live figures for this record could not be recomputed just now, so none are shown. The scope
                  still draws the record itself; it simply is not claiming a verdict it did not compute.
                </p>
              )}
              {figures && figures.empiricalPValue !== null ? (
                <p>
                  Regimen also grades {figures.nullSimulations === null ? 'many' : count(figures.nullSimulations)} simulated
                  strategies with no edge at all, of the same length and volatility.{' '}
                  <span className="flare">{percent(figures.empiricalPValue)}</span> of them score at least
                  as well as this one.
                </p>
              ) : null}
            </div>

            <div>
              <p className="bandLabel">Scope key</p>
              <ul className="readout">
                <li>
                  <span className="swatch" style={{ background: 'var(--p1-green)' }} aria-hidden="true" />
                  <span className="term">Strategy trace</span>
                  <span className="value">n {figures?.usableReturns ?? '—'}</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'rgba(87,242,168,.35)' }} aria-hidden="true" />
                  <span className="term">Resampled paths</span>
                  <span className="value">{count(resamples)}</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'var(--p3-amber)' }} aria-hidden="true" />
                  <span className="term">Volatility regime</span>
                  <span className="value">shaded</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'var(--ion-magenta)' }} aria-hidden="true" />
                  <span className="term">Funding regime</span>
                  <span className="value">shaded</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'var(--sky-cyan)' }} aria-hidden="true" />
                  <span className="term">Open interest</span>
                  <span className="value">shaded</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'var(--sodium)' }} aria-hidden="true" />
                  <span className="term">Fear &amp; greed</span>
                  <span className="value">shaded</span>
                </li>
                <li>
                  <span className="swatch" style={{ background: 'var(--alert-flare)' }} aria-hidden="true" />
                  <span className="term">Break-even</span>
                  <span className="value">0.000</span>
                </li>
              </ul>
            </div>
          </div>
        </section>

        <section className="band" id="run">
          <p className="bandLabel">Run it · your own track record</p>
          <h2 className="bandHeading">Paste a curve. Regimen will tell you if it is nothing.</h2>
          <p className="bandIntro">
            The demo curve is loaded. Edit it, or load one deliberately too short to grade and watch Regimen decline
            rather than guess.
          </p>
          <RunPanel />
        </section>
      </main>

      <div className="foot">
        <span>Regimen</span>
        <span>Validation only · no execution · no custody</span>
        <Link href="/methodology">Methodology</Link>
        <span>{figures?.engineSane ? 'Self-attack controls passing' : 'Self-attack controls not verified'}</span>
      </div>
    </div>
  );
}
