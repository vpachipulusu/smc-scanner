// @vitest-environment node
/** The analyse wrapper sends the mtf flags and keeps only a well-formed htf_bias on each row. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { runAnalyse } from '@/lib/api/analyse';
import { DEFAULTS } from '@/lib/scan/params';
import { makeAnalysedRow } from '../../helpers/fixtures';

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { 'Content-Type': 'application/json' },
  });

const body = (rows: unknown[]) => ({
  source: 'demo',
  tf: '1h',
  count: rows.length,
  rows,
  failures: [],
});

describe('runAnalyse multi-timeframe', () => {
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

  it('posts mtf and require_htf_aligned', async () => {
    fetchMock.mockResolvedValue(jsonResponse(body([])));

    await runAnalyse({ ...DEFAULTS, mtf: true, requireHtfAligned: true });

    expect(await fetchMock.mock.calls[0][0].json()).toMatchObject({
      mtf: true,
      require_htf_aligned: true,
    });
  });

  it('keeps a valid htf_bias and drops a malformed one', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(
        body([
          { ...makeAnalysedRow({ instrument: 'A' }), htf_bias: 'bullish' },
          { ...makeAnalysedRow({ instrument: 'B' }), htf_bias: '<script>' },
          { ...makeAnalysedRow({ instrument: 'C' }), htf_bias: null },
        ])
      )
    );

    const result = await runAnalyse({ ...DEFAULTS, mtf: true });

    expect(result.success && result.data.rows.map((row) => row.htf_bias)).toEqual([
      'bullish',
      undefined,
      undefined,
    ]);
  });
});
