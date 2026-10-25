import type { BacktestCreate } from '@/lib/api/backtests';
import { SOURCES, SYMBOL_PATTERN, TIMEFRAMES } from '@/lib/scan/params';

/**
 * The "Run backtest" form: allow-listed FormData fields, read and checked against the API's
 * `BacktestCreate` limits (TRAD-46; keep these in step with that schema in openapi.json), so a
 * bad value gets its own message before any request. Values stay strings so a failed submit can
 * refill the form as typed. Without symbols the API uses the source's watchlist, so the cost cap
 * and the symbol-split rule are then left to the API (its 422 messages are mapped).
 */

export const BACKTEST_LIMITS = {
  minBars: 15,
  maxBars: 5000,
  maxSymbols: 50,
  maxRr: 100,
  maxStopBufferAtr: 50,
  minTimeStopBars: 1,
  maxTimeStopBars: 5000,
  maxSpread: 1e9,
  maxMinRiskAtr: 50,
  minTrainFraction: 0.3,
  maxTrainFraction: 0.9,
  maxSeed: 2 ** 32 - 1,
  minStride: 1,
  maxStride: 100,
  /** symbols x bars x bars / stride; a run at the cap takes about 15 minutes. */
  maxCost: 1.2e8,
} as const;

export const SPLITS = ['time', 'symbols'] as const;

export type BacktestSource = BacktestCreate['source'];
export type BacktestTimeframe = NonNullable<BacktestCreate['tf']>;
export type BacktestSplit = (typeof SPLITS)[number];

export const BACKTEST_SOURCES: readonly BacktestSource[] = SOURCES;
export const BACKTEST_TIMEFRAMES: readonly BacktestTimeframe[] = TIMEFRAMES;

export type BacktestFormValues = {
  source: string;
  tf: string;
  bars: string;
  symbols: string;
  rr: string;
  stop_buffer_atr: string;
  time_stop_bars: string;
  spread: string;
  min_risk_atr: string;
  split: string;
  train_fraction: string;
  seed: string;
  stride: string;
};

export type BacktestFieldName = keyof BacktestFormValues;
export type BacktestFieldErrors = Partial<Record<BacktestFieldName, string>>;

/** The API's defaults; the seed stays fixed so a re-run is comparable. */
export const BACKTEST_DEFAULTS: BacktestFormValues = {
  source: 'demo',
  tf: '1h',
  bars: '500',
  symbols: '',
  rr: '2',
  stop_buffer_atr: '0',
  time_stop_bars: '50',
  spread: '0',
  min_risk_atr: '0.1',
  split: 'time',
  train_fraction: '0.6',
  seed: '0',
  stride: '1',
};

const FIELDS = Object.keys(BACKTEST_DEFAULTS) as BacktestFieldName[];
const MAX_FIELD_LENGTH = 2000;

export type ParsedBacktestForm =
  | { ok: true; body: Omit<BacktestCreate, 'strategy'>; values: BacktestFormValues }
  | { ok: false; errors: BacktestFieldErrors; values: BacktestFormValues };

/** Only the known fields, as typed (trimmed; cut to the length limit for refilling the form). */
export function readBacktestValues(formData: FormData): BacktestFormValues {
  const entries = FIELDS.map((name) => {
    const raw = formData.get(name);
    return [name, typeof raw === 'string' ? raw.trim().slice(0, MAX_FIELD_LENGTH) : ''] as const;
  });
  return Object.fromEntries(entries) as BacktestFormValues;
}

/** Splits on commas and whitespace; duplicates are dropped (as the API does). */
export function splitSymbols(text: string): string[] {
  return [...new Set(text.split(/[\s,]+/).filter((name) => name !== ''))];
}

/** symbols x bars x bars / stride, the API's cost measure. */
export function backtestCost(symbolCount: number, bars: number, stride: number): number {
  return (symbolCount * bars * bars) / stride;
}

type NumberRule = { min: number; max: number; integer?: boolean; aboveMin?: boolean };

/** Plain decimals only: no exponents, hex or binary literals that `Number()` would accept. */
const DECIMAL_PATTERN = /^-?\d+(\.\d+)?$/;

/** A number within the rule, or the message for the field. */
function readNumber(text: string, rule: NumberRule): number | string {
  if (!DECIMAL_PATTERN.test(text)) return 'Enter a number.';
  const value = Number(text);
  if (!Number.isFinite(value)) return 'Enter a number.';
  if (rule.integer && !Number.isInteger(value)) return 'Enter a whole number.';
  const tooLow = rule.aboveMin ? value <= rule.min : value < rule.min;
  if (tooLow || value > rule.max) {
    return rule.aboveMin
      ? `Enter a number above ${rule.min} and at most ${rule.max}.`
      : `Enter a number from ${rule.min} to ${rule.max}.`;
  }
  return value;
}

const L = BACKTEST_LIMITS;

type NumericField =
  | 'bars'
  | 'rr'
  | 'stop_buffer_atr'
  | 'time_stop_bars'
  | 'spread'
  | 'min_risk_atr'
  | 'train_fraction'
  | 'seed'
  | 'stride';

const NUMBER_RULES: Readonly<Record<NumericField, NumberRule>> = {
  bars: { min: L.minBars, max: L.maxBars, integer: true },
  rr: { min: 0, max: L.maxRr, aboveMin: true },
  stop_buffer_atr: { min: 0, max: L.maxStopBufferAtr },
  time_stop_bars: { min: L.minTimeStopBars, max: L.maxTimeStopBars, integer: true },
  spread: { min: 0, max: L.maxSpread },
  min_risk_atr: { min: 0, max: L.maxMinRiskAtr },
  train_fraction: { min: L.minTrainFraction, max: L.maxTrainFraction },
  seed: { min: 0, max: L.maxSeed, integer: true },
  stride: { min: L.minStride, max: L.maxStride, integer: true },
};

function symbolsError(symbols: readonly string[]): string | undefined {
  if (symbols.length > L.maxSymbols) return `List at most ${L.maxSymbols} symbols.`;
  const bad = symbols.find((name) => !SYMBOL_PATTERN.test(name));
  if (bad !== undefined) return 'Use letters, digits and . _ # @ - only (32 characters at most).';
  return undefined;
}

/** Fields typed longer than the limit: rejected, never silently cut. */
function tooLongErrors(formData: FormData): BacktestFieldErrors {
  const long = FIELDS.filter((name) => {
    const raw = formData.get(name);
    return typeof raw === 'string' && raw.trim().length > MAX_FIELD_LENGTH;
  });
  return Object.fromEntries(
    long.map((name) => [name, `Use at most ${MAX_FIELD_LENGTH} characters.`])
  );
}

/** Reads and checks the form; the strategy slug is added by the caller. */
export function parseBacktestForm(formData: FormData): ParsedBacktestForm {
  const values = readBacktestValues(formData);
  const tooLong = tooLongErrors(formData);
  const errors: BacktestFieldErrors = {};
  const read: Partial<Record<NumericField, number>> = {};
  for (const name of Object.keys(NUMBER_RULES) as NumericField[]) {
    const result = readNumber(values[name], NUMBER_RULES[name]);
    if (typeof result === 'string') errors[name] = result;
    else read[name] = result;
  }
  // Every field is set unless it has an error, and any error returns before `numbers` is used.
  const numbers = read as Record<NumericField, number>;
  const source = BACKTEST_SOURCES.find((item) => item === values.source);
  if (!source) errors.source = 'Pick demo or MT5.';
  const tf = BACKTEST_TIMEFRAMES.find((item) => item === values.tf);
  if (!tf) errors.tf = 'Pick a timeframe.';
  const split = SPLITS.find((item) => item === values.split);
  if (!split) errors.split = 'Pick a split.';

  const symbols = splitSymbols(values.symbols);
  const symbolError = symbolsError(symbols);
  if (symbolError) errors.symbols = symbolError;
  else if (split === 'symbols' && symbols.length === 1) {
    errors.split = 'A symbol split needs at least 2 symbols.';
  }
  if (
    !errors.symbols &&
    !errors.bars &&
    !errors.stride &&
    symbols.length > 0 &&
    backtestCost(symbols.length, numbers.bars, numbers.stride) > L.maxCost
  ) {
    errors.bars = 'Too large: use fewer symbols or bars, or a larger stride.';
  }

  if (Object.keys(tooLong).length > 0) {
    return { ok: false, errors: { ...errors, ...tooLong }, values };
  }
  if (Object.keys(errors).length > 0 || !source || !tf || !split) {
    return { ok: false, errors, values };
  }
  return {
    ok: true,
    values,
    body: {
      source,
      tf,
      bars: numbers.bars,
      ...(symbols.length > 0 ? { symbols } : {}),
      rules: {
        rr: numbers.rr,
        stop_buffer_atr: numbers.stop_buffer_atr,
        time_stop_bars: numbers.time_stop_bars,
        spread: numbers.spread,
        min_risk_atr: numbers.min_risk_atr,
      },
      split,
      train_fraction: numbers.train_fraction,
      seed: numbers.seed,
      stride: numbers.stride,
    },
  };
}
