import { NexusParseError } from './errors.js';

type Obj = Record<string, unknown>;

function object(value: unknown, tool: string, field = 'content'): Obj {
  if (value === null || typeof value !== 'object' || Array.isArray(value)) {
    throw new NexusParseError(`${tool} ${field} must be an object`, tool);
  }
  return value as Obj;
}

function string(obj: Obj, key: string, tool: string): string {
  const value = obj[key];
  if (typeof value !== 'string') throw new NexusParseError(`${tool}.${key} must be a string`, tool);
  return value;
}

function finite(obj: Obj, key: string, tool: string): number {
  const value = obj[key];
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new NexusParseError(`${tool}.${key} must be a finite number`, tool);
  }
  return value;
}

function positive(obj: Obj, key: string, tool: string): number {
  const value = finite(obj, key, tool);
  if (value <= 0) throw new NexusParseError(`${tool}.${key} must be positive`, tool);
  return value;
}

function optionalFinite(obj: Obj, key: string, tool: string): void {
  if (obj[key] !== undefined) finite(obj, key, tool);
}

function matchesArgument(obj: Obj, field: string, argument: string, args: Record<string, unknown>, tool: string): void {
  const expected = args[argument];
  if (typeof expected === 'string' && obj[field] !== expected) {
    throw new NexusParseError(`${tool}.${field} does not match requested ${argument}`, tool);
  }
}

function array(obj: Obj, key: string, tool: string): unknown[] {
  const value = obj[key];
  if (!Array.isArray(value)) throw new NexusParseError(`${tool}.${key} must be an array`, tool);
  return value;
}

/** Validate only tools whose payloads cross the gate's trust boundary. */
export function validateToolPayload<T>(
  tool: string,
  payload: unknown,
  args: Record<string, unknown> = {},
): T {
  const obj = object(payload, tool);

  switch (tool) {
    case 'get_strategy_signal': {
      string(obj, 'symbol', tool);
      matchesArgument(obj, 'symbol', 'symbol', args, tool);
      string(obj, 'reasoning_log', tool);
      positive(obj, 'timestamp', tool);
      optionalFinite(obj, 'confidence', tool);
      const intent = string(obj, 'trade_intent', tool);
      if (!['BUY', 'SELL', 'HOLD'].includes(intent)) {
        throw new NexusParseError(`${tool}.trade_intent is invalid`, tool);
      }
      break;
    }
    case 'get_strategy_metrics': {
      for (const key of [
        'sharpe_ratio',
        'trading_period_days',
        'estimated_aum_usdt',
        'profit_factor',
        'total_return_pct',
        'win_rate_pct',
        'trade_count',
      ]) finite(obj, key, tool);
      const drawdown = obj['max_drawdown'];
      if (typeof drawdown !== 'string' && (typeof drawdown !== 'number' || !Number.isFinite(drawdown))) {
        throw new NexusParseError(`${tool}.max_drawdown must be a percent string or finite number`, tool);
      }
      const status = string(obj, 'status', tool);
      if (!['QUALIFIED_FOR_OKX_LISTING', 'NOT_QUALIFIED'].includes(status)) {
        throw new NexusParseError(`${tool}.status is invalid`, tool);
      }
      break;
    }
    case 'get_strategy_equity':
      string(obj, 'run_id', tool);
      const points = array(obj, 'points', tool);
      if (points.length === 0) throw new NexusParseError(`${tool}.points must not be empty`, tool);
      let previousTimestamp = -Infinity;
      for (const [index, point] of points.entries()) {
        const p = object(point, tool, `points[${index}]`);
        const timestamp = positive(p, 't', tool);
        if (timestamp <= previousTimestamp) {
          throw new NexusParseError(`${tool}.points timestamps must be strictly increasing`, tool);
        }
        previousTimestamp = timestamp;
        positive(p, 'equity', tool);
      }
      break;
    case 'get_strategy_trades':
      string(obj, 'run_id', tool);
      for (const [index, trade] of array(obj, 'trades', tool).entries()) {
        const t = object(trade, tool, `trades[${index}]`);
        string(t, 'symbol', tool);
        string(t, 'exit_reason', tool);
        for (const key of [
          'direction', 'entry_price', 'exit_price', 'size', 'leverage', 'pnl', 'pnl_pct',
          'holding_bars', 'commission', 'entry_bar_index', 'exit_bar_index', 'entry_ts_ms', 'exit_ts_ms',
        ]) finite(t, key, tool);
        if (t['direction'] !== 1 && t['direction'] !== -1) {
          throw new NexusParseError(`${tool}.direction must be 1 or -1`, tool);
        }
      }
      break;
    case 'get_historical_funding':
      string(obj, 'symbol', tool);
      string(obj, 'as_of_date', tool);
      matchesArgument(obj, 'symbol', 'symbol', args, tool);
      matchesArgument(obj, 'as_of_date', 'as_of', args, tool);
      finite(obj, 'last_funding_rate', tool);
      break;
    case 'get_open_interest':
      string(obj, 'symbol', tool);
      string(obj, 'as_of_date', tool);
      matchesArgument(obj, 'symbol', 'symbol', args, tool);
      matchesArgument(obj, 'as_of_date', 'as_of', args, tool);
      finite(obj, 'open_interest', tool);
      // Live responses omit open_interest_prev entirely (2 of 21 recorded
      // fixtures carried it). Requiring it rejected every real payload as
      // NexusParseError, which failed DATA_GAP and abstained on everything.
      // The baseline now comes from an explicit as_of-1 fetch; when the
      // gateway does supply one it must still be positive to be usable.
      if (obj['open_interest_prev'] !== undefined && finite(obj, 'open_interest_prev', tool) <= 0) {
        throw new NexusParseError(`${tool}.open_interest_prev must be positive when present`, tool);
      }
      optionalFinite(obj, 'long_short_ratio', tool);
      break;
    case 'get_historical_coverage':
      for (const key of ['start', 'end', 'end_date', 'latest', 'to', 'max_date', 'last']) {
        if (obj[key] !== undefined && typeof obj[key] !== 'string') {
          throw new NexusParseError(`${tool}.${key} must be a string`, tool);
        }
      }
      break;
    default:
      break;
  }

  return obj as T;
}
