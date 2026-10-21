// @vitest-environment node
/** The scan wrapper maps the page's query to the API, checks the body shape and curates errors. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  SCAN_NOTHING_LOADED_MESSAGE,
  SCAN_REQUEST_FAILED_MESSAGE,
  SCAN_UNAUTHORIZED_MESSAGE,
  SCAN_UNAVAILABLE_MESSAGE,
  fetchScan,
  fetchScanConfig,
  scanErrorMessage,
  type ScanQuery,
} from '@/lib/api/scan';
import { BACKEND_ERROR_MESSAGE } from '@/lib/api/server';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

export const ROW = {
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
} as const;

const SCAN_BODY = { source: 'demo', tf: '1h', count: 1, rows: [ROW], failures: [] };

const CONFIG_BODY = {
  sources: ['mt5', 'demo'],
  timeframes: ['5m', '15m', '30m', '1h', '4h', '1d'],
  defaults: { source: 'mt5', tf: '1h', bars: 500, swing: 10, near: 0.5 },
  limits: { min_bars: 15, max_bars: 5000, max_swing: 100, max_near: 5, max_symbols: 50 },
  watchlist: { mt5: ['EURUSD'], demo: ['EURUSD', 'XAUUSD'] },
};

const QUERY: ScanQuery = {
  source: 'demo',
  tf: '15m',
  symbols: ['EURUSD', 'XAUUSD'],
  bars: 300,
  swing: 5,
  near: 0.4,
  allTouches: true,
  mtf: true,
  requireHtfAligned: true,
};

describe('fetchScan', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('maps the query to the API parameters and returns the rows', async () => {
    fetchMock.mockResolvedValue(jsonResponse(SCAN_BODY));

    const result = await fetchScan(QUERY);

    expect(result).toEqual({ success: true, data: SCAN_BODY });
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/scan');
    expect(Object.fromEntries(url.searchParams)).toEqual({
      source: 'demo',
      tf: '15m',
      symbols: 'EURUSD,XAUUSD',
      bars: '300',
      swing: '5',
      near: '0.4',
      all_touches: 'true',
      mtf: 'true',
      require_htf_aligned: 'true',
    });
  });

  it('leaves symbols out when the list is empty so the API uses its watchlist', async () => {
    fetchMock.mockResolvedValue(jsonResponse(SCAN_BODY));

    await fetchScan({ ...QUERY, symbols: [] });

    expect(new URL(fetchMock.mock.calls[0][0].url).searchParams.has('symbols')).toBe(false);
  });

  it('refuses a body without rows and failures', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ count: 0 }));

    expect(await fetchScan(QUERY)).toEqual({
      success: false,
      error: SCAN_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });

  it('passes a failed result through', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'No symbol could be loaded; see the scanner log' }, 503)
    );

    expect(await fetchScan(QUERY)).toEqual({
      success: false,
      error: 'No symbol could be loaded; see the scanner log',
      status: 503,
    });
  });
});

describe('fetchScanConfig', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('returns the config', async () => {
    fetchMock.mockResolvedValue(jsonResponse(CONFIG_BODY));

    expect(await fetchScanConfig()).toEqual({ success: true, data: CONFIG_BODY });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/config');
  });

  it('refuses a body without the choice lists', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ defaults: {} }));

    expect(await fetchScanConfig()).toEqual({
      success: false,
      error: SCAN_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });
});

describe('scanErrorMessage', () => {
  it('names the unreachable API', () => {
    expect(scanErrorMessage({ error: 'Backend unavailable' })).toBe(SCAN_UNAVAILABLE_MESSAGE);
  });

  it('explains a rejected internal key', () => {
    expect(scanErrorMessage({ error: 'Unauthorized', status: 401 })).toBe(
      SCAN_UNAUTHORIZED_MESSAGE
    );
  });

  it('shows the curated 422 and 503 texts as they are', () => {
    expect(scanErrorMessage({ error: "Invalid symbol name: '../x'", status: 422 })).toBe(
      "Invalid symbol name: '../x'"
    );
    expect(scanErrorMessage({ error: 'No symbol could be loaded', status: 503 })).toBe(
      'No symbol could be loaded'
    );
  });

  it('falls back to the fixed texts for generic or long errors', () => {
    expect(scanErrorMessage({ error: BACKEND_ERROR_MESSAGE, status: 503 })).toBe(
      SCAN_NOTHING_LOADED_MESSAGE
    );
    expect(scanErrorMessage({ error: 'x'.repeat(201), status: 422 })).toBe(
      SCAN_REQUEST_FAILED_MESSAGE
    );
    expect(scanErrorMessage({ error: 'Internal server error', status: 500 })).toBe(
      SCAN_REQUEST_FAILED_MESSAGE
    );
  });
});
