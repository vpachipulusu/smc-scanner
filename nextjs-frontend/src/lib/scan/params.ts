import { z } from 'zod';
import type { ScanQuery, ScanSource, ScanTimeframe } from '@/lib/api/scan';

/**
 * The scan page and the CSV route read the same search params. Each field falls back to its
 * default when missing or out of range (like the orders page clamps `page`), so a hand-edited URL
 * never breaks the page; the limits mirror the API's.
 */

export const SOURCES: readonly ScanSource[] = ['mt5', 'demo'];
export const TIMEFRAMES: readonly ScanTimeframe[] = ['5m', '15m', '30m', '1h', '4h', '1d'];

export const LIMITS = {
  minBars: 15,
  maxBars: 5000,
  maxSwing: 100,
  maxNear: 5,
  maxSymbols: 50,
  /** Auto-rescan interval in minutes; 0 is off. */
  maxEvery: 1440,
} as const;

export const DEFAULTS: ScanQuery = {
  source: 'mt5',
  tf: '1h',
  symbols: [],
  bars: 500,
  swing: 10,
  near: 0.5,
  allTouches: false,
  mtf: false,
  requireHtfAligned: false,
};

export const SYMBOL_PATTERN = /^[A-Za-z0-9._#@-]{1,32}$/;

export type Param = string | string[] | undefined;
export type RawScanParams = Record<string, Param>;

export type ScanPageParams = {
  query: ScanQuery;
  /** Minutes between automatic rescans; 0 means off. */
  every: number;
};

const TRUE_VALUES = new Set(['1', 'on', 'true', 'yes']);

function isTruthy(value: string | undefined): boolean {
  return value !== undefined && TRUE_VALUES.has(value.toLowerCase());
}

/** First value of a repeated param; an empty string (a cleared form field) counts as absent. */
function first(value: Param): string | undefined {
  const single = Array.isArray(value) ? value[0] : value;
  return single === '' ? undefined : single;
}

/** Splits on commas and whitespace, drops invalid names, caps the list. */
export function parseSymbols(value: string | undefined): string[] {
  if (!value) return [];
  const names = value
    .split(/[\s,]+/)
    .map((name) => name.trim())
    .filter((name) => SYMBOL_PATTERN.test(name));
  return Array.from(new Set(names)).slice(0, LIMITS.maxSymbols);
}

const schema = z.object({
  source: z.enum(SOURCES as [ScanSource, ...ScanSource[]]).catch(DEFAULTS.source),
  tf: z.enum(TIMEFRAMES as [ScanTimeframe, ...ScanTimeframe[]]).catch(DEFAULTS.tf),
  bars: z.coerce.number().int().min(LIMITS.minBars).max(LIMITS.maxBars).catch(DEFAULTS.bars),
  swing: z.coerce.number().int().min(1).max(LIMITS.maxSwing).catch(DEFAULTS.swing),
  near: z.coerce.number().finite().min(0).max(LIMITS.maxNear).catch(DEFAULTS.near),
  every: z.coerce.number().int().min(0).max(LIMITS.maxEvery).catch(0),
});

export function parseScanParams(raw: RawScanParams): ScanPageParams {
  const parsed = schema.parse({
    source: first(raw.source),
    tf: first(raw.tf),
    bars: first(raw.bars) ?? DEFAULTS.bars,
    swing: first(raw.swing) ?? DEFAULTS.swing,
    near: first(raw.near) ?? DEFAULTS.near,
    every: first(raw.every) ?? 0,
  });
  const all = first(raw.all);
  const mtf = isTruthy(first(raw.mtf));
  return {
    query: {
      source: parsed.source,
      tf: parsed.tf,
      symbols: parseSymbols(first(raw.symbols)),
      bars: parsed.bars,
      swing: parsed.swing,
      near: parsed.near,
      allTouches: isTruthy(all),
      mtf,
      // Alignment needs the higher timeframe, so it only counts with mtf (the API 422s otherwise).
      requireHtfAligned: mtf && isTruthy(first(raw.htf)),
    },
    every: parsed.every,
  };
}

/** Query string for the page and the CSV route; defaults are left out to keep URLs short. */
export function scanSearchParams(params: ScanPageParams): URLSearchParams {
  const { query, every } = params;
  const out = new URLSearchParams();
  if (query.source !== DEFAULTS.source) out.set('source', query.source);
  if (query.tf !== DEFAULTS.tf) out.set('tf', query.tf);
  if (query.symbols.length > 0) out.set('symbols', query.symbols.join(','));
  if (query.bars !== DEFAULTS.bars) out.set('bars', String(query.bars));
  if (query.swing !== DEFAULTS.swing) out.set('swing', String(query.swing));
  if (query.near !== DEFAULTS.near) out.set('near', String(query.near));
  if (query.allTouches) out.set('all', '1');
  if (query.mtf) out.set('mtf', '1');
  if (query.mtf && query.requireHtfAligned) out.set('htf', '1');
  if (every > 0) out.set('every', String(every));
  return out;
}

export function scanHref(params: ScanPageParams, path = '/scan'): string {
  const qs = scanSearchParams(params).toString();
  return qs ? `${path}?${qs}` : path;
}
