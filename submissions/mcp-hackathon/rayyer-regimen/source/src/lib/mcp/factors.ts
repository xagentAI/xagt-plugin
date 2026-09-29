import type { REGIME_FACTOR_KEYS } from '@/lib/sources/nexus/adapter';

/**
 * Plain-language descriptions of each regime factor.
 *
 * These are written for a model that has to explain a bucket to a person, so each one
 * says what the number measures AND why a strategy's returns might depend on it.
 * A description that only restates the field name gives an agent nothing to reason with.
 */
export const FACTOR_CATALOGUE: Record<
  (typeof REGIME_FACTOR_KEYS)[number],
  { label: string; unit: string; description: string; source: string }
> = {
  vix: {
    label: 'VIX',
    unit: 'index',
    description:
      'CBOE volatility index close: how much fear is priced into equity options. Strategies that sell volatility tend to earn steadily while it is low and give it all back when it spikes.',
    source: 'get_macro',
  },
  us10y: {
    label: 'US 10-year yield',
    unit: 'percent',
    description:
      'Ten-year Treasury yield. It sets the discount rate for every risk asset, crypto included, so a strategy can look like alpha while really being a duration bet.',
    source: 'get_macro',
  },
  fedFunds: {
    label: 'Effective fed funds rate',
    unit: 'percent',
    description:
      'The policy rate actually transacted overnight. Separates tightening regimes from easing ones, which is often the real dividing line in a multi-year backtest.',
    source: 'get_macro',
  },
  fundingRate: {
    label: 'Perpetual funding rate',
    unit: 'fraction per interval',
    description:
      'What longs pay shorts to hold the perpetual. Persistently positive funding marks a crowded long book; a strategy that is quietly short the crowd earns it, and is exposed when it flips.',
    source: 'get_historical_funding',
  },
  openInterestUsd: {
    label: 'Open interest',
    unit: 'USD',
    description:
      'Notional open on the perpetual. Rising open interest into a price move means leverage is building, which changes how violently the move unwinds.',
    source: 'get_open_interest',
  },
  longShortRatio: {
    label: 'Long/short ratio',
    unit: 'ratio',
    description:
      'Account positioning skew. Extremes mark a one-sided book, and one-sided books produce the liquidation cascades that dominate a short track record’s tail.',
    source: 'get_open_interest',
  },
  fearGreed: {
    label: 'Fear & Greed index',
    unit: '0-100',
    description:
      'Composite retail sentiment gauge. Included because a surprising number of strategies turn out to be implicit sentiment bets once their returns are sliced this way.',
    source: 'get_fear_greed',
  },
  trendTemplatePassed: {
    label: 'Trend-template gates passed',
    unit: 'count',
    description:
      'How many Minervini trend-template conditions held that day: a compact description of whether price was in an established uptrend. Momentum strategies concentrate their returns here.',
    source: 'get_vcp',
  },
};
