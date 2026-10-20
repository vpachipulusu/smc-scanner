import type { ScanFailureOut, ScanResponse, ScanRowOut } from '@/lib/api/scan';

/** A TOUCHING bullish FVG hit shaped like the API's rows. */
export const ROW: ScanRowOut = {
  instrument: 'EURUSD',
  status: 'TOUCHING',
  zone: 'bull FVG',
  zone_low: 1.0971,
  zone_high: 1.09898,
  price: 1.09988,
  dist_atr: 0,
  bias: 'bearish',
  in_ote: false,
  trendline_ok: true,
  ob_fvg: false,
  score: 1,
  zone_age: 2,
  prior_touches: 0,
  bar_time: '2026-10-19 23:00:00',
};

export function makeRow(overrides: Partial<ScanRowOut> = {}): ScanRowOut {
  return { ...ROW, ...overrides };
}

export const FAILURE: ScanFailureOut = {
  symbol: 'BTCUSD',
  error: "LoaderError: unknown symbol 'BTCUSD': (-1, 'Terminal: Call failed')",
};

export function makeResponse(
  rows: ScanRowOut[],
  failures: ScanFailureOut[] = [],
  overrides: Partial<ScanResponse> = {}
): ScanResponse {
  return { source: 'demo', tf: '1h', count: rows.length, rows, failures, ...overrides };
}
