// @vitest-environment node
/** The analyse wrapper maps the scan query to POST /analyse, validates the body, hides backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAnalyse } from '@/lib/api/analyse';
import { ANALYSE_FAILED_MESSAGE } from '@/lib/api/analyse-messages';
import { DEFAULTS } from '@/lib/scan/params';
import { makeAnalysedRow } from '../../helpers/fixtures';

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const BODY = { source: 'demo', tf: '1h', count: 1, rows: [makeAnalysedRow()], failures: [] };

describe('runAnalyse', () => {
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

  it('posts the scan query as the JSON body and returns the rows', async () => {
    fetchMock.mockResolvedValue(jsonResponse(BODY));

    const result = await runAnalyse({ ...DEFAULTS, symbols: ['EURUSD'], allTouches: true });

    expect(result).toEqual({ success: true, data: BODY });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(new URL(request.url).pathname).toBe('/analyse');
    expect(await request.json()).toEqual({
      source: 'mt5',
      tf: '1h',
      symbols: ['EURUSD'],
      bars: 500,
      swing: 10,
      near: 0.5,
      all_touches: true,
    });
  });

  it('sends no symbols for the watchlist', async () => {
    fetchMock.mockResolvedValue(jsonResponse(BODY));

    await runAnalyse(DEFAULTS);

    expect(await fetchMock.mock.calls[0][0].json()).toMatchObject({ symbols: null });
  });

  it('keeps a valid verdict and nulls an invalid one', async () => {
    const bad = makeAnalysedRow({
      ai: { status: 'analysed', note: '', verdict: { action: 'MOON', confidence: 1 } as never },
    });
    fetchMock.mockResolvedValue(
      jsonResponse({ ...BODY, count: 2, rows: [makeAnalysedRow(), bad] })
    );

    const result = await runAnalyse(DEFAULTS);

    expect(result.success && result.data.rows.map((row) => row.ai.verdict?.action ?? null)).toEqual(
      ['BUY', null]
    );
  });

  it('keeps only well-typed verdict fields', async () => {
    const row = makeAnalysedRow({
      ai: {
        status: 'analysed',
        note: '',
        verdict: {
          action: 'SELL',
          confidence: 60,
          quality: 'Z',
          entry: 'x',
          stop: Number.NaN,
          targets: [1.1, 'a', null],
          risk_reward: 2,
        } as never,
      },
    });
    const text = makeAnalysedRow({
      ai: {
        status: 'analysed',
        note: '',
        verdict: { action: 'BUY', confidence: 1, targets: 'x' } as never,
      },
    });
    const nan = makeAnalysedRow({
      ai: { status: 'analysed', note: '', verdict: { action: 'BUY', confidence: 'hi' } as never },
    });
    fetchMock.mockResolvedValue(jsonResponse({ ...BODY, rows: [row, text, nan] }));

    const result = await runAnalyse(DEFAULTS);

    expect(result.success && result.data.rows.map((r) => r.ai.verdict)).toEqual([
      {
        action: 'SELL',
        confidence: 60,
        quality: null,
        entry: null,
        stop: null,
        targets: [1.1],
        risk_reward: 2,
      },
      {
        action: 'BUY',
        confidence: 1,
        quality: null,
        entry: null,
        stop: null,
        targets: [],
        risk_reward: null,
      },
      null,
    ]);
  });

  it('strips unknown fields and drops rows with a bad field', async () => {
    const extra = { ...makeAnalysedRow(), rationale: 'secret trace' };
    const noScore = { ...makeAnalysedRow(), score: 'high' };
    const noZone = { ...makeAnalysedRow(), zone: { a: 1 } };
    fetchMock.mockResolvedValue(
      jsonResponse({ ...BODY, secret: 'x', rows: [extra, noScore, noZone] })
    );

    const result = await runAnalyse(DEFAULTS);

    expect(result).toEqual({ success: true, data: { ...BODY, count: 1 } });
    expect(JSON.stringify(result)).not.toMatch(/secret/);
  });

  it('validates failures and caps their text', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({
        ...BODY,
        failures: [
          { symbol: 'A', error: 'x'.repeat(500), extra: 1 },
          { symbol: 'B', error: { deep: 1 } },
          null,
        ],
      })
    );

    const result = await runAnalyse(DEFAULTS);

    expect(result.success && result.data.failures).toEqual([
      { symbol: 'A', error: 'x'.repeat(200) },
    ]);
  });

  it('refuses a body with an unknown source or timeframe', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ...BODY, source: 'evil' }));

    expect(await runAnalyse(DEFAULTS)).toMatchObject({ success: false, status: 502 });
  });

  it('drops the free-text note', async () => {
    const row = makeAnalysedRow({
      ai: { status: 'failed', note: 'anthropic 401 sk-ant-key', verdict: null },
    });
    fetchMock.mockResolvedValue(jsonResponse({ ...BODY, rows: [row] }));

    const result = await runAnalyse(DEFAULTS);

    expect(JSON.stringify(result)).not.toContain('sk-ant');
  });

  it('drops rows without a usable ai result', async () => {
    const oddStatus = { ...makeAnalysedRow(), ai: { status: 'weird', note: '', verdict: null } };
    fetchMock.mockResolvedValue(
      jsonResponse({
        ...BODY,
        rows: [
          null,
          { instrument: 'X' },
          { ...makeAnalysedRow(), ai: null },
          oddStatus,
          makeAnalysedRow(),
        ],
      })
    );

    const result = await runAnalyse(DEFAULTS);

    expect(result.success && result.data.rows).toHaveLength(1);
  });

  it('refuses a body that is not an analyse response', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ nope: true }));

    expect(await runAnalyse(DEFAULTS)).toEqual({
      success: false,
      error: ANALYSE_FAILED_MESSAGE,
      status: 502,
    });
  });

  it('reads Retry-After from a 429 and hides the backend text', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'sk-ant-secret budget' }, 429, {
        'Retry-After': '120',
      })
    );

    const result = await runAnalyse(DEFAULTS);

    expect(result).toMatchObject({ success: false, status: 429, retryAfterSeconds: 120 });
    expect(JSON.stringify(result)).not.toContain('sk-ant');
  });

  it('answers 429 without a usable Retry-After', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'x' }, 429));

    const result = await runAnalyse(DEFAULTS);

    expect(result).toMatchObject({ success: false, status: 429 });
    expect(result).not.toHaveProperty('retryAfterSeconds');
  });

  it('replaces provider error text for 502 and 503', async () => {
    fetchMock.mockResolvedValueOnce(
      jsonResponse({ success: false, error: 'anthropic: key abc' }, 502)
    );
    fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'db path C:/x' }, 503));

    const first = await runAnalyse(DEFAULTS);
    const second = await runAnalyse(DEFAULTS);

    expect(JSON.stringify([first, second])).not.toMatch(/anthropic|key abc|C:/);
    expect(first).toMatchObject({ status: 502 });
    expect(second).toMatchObject({ status: 503 });
  });

  it('reports an unreachable API without a status', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));

    const result = await runAnalyse(DEFAULTS);

    expect(result.success).toBe(false);
    expect(result).not.toHaveProperty('status');
  });
});
