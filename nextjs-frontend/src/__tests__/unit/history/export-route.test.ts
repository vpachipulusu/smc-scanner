// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeAnalysis } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchAnalyses: vi.fn() }));

vi.mock('@/lib/api/analyses', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/analyses')>('@/lib/api/analyses');
  return { ...actual, fetchAnalyses: mocks.fetchAnalyses };
});

import { GET } from '@/app/analyses/export/route';
import { MAX_EXPORT_PAGES } from '@/components/analyses/history/csv';

const ok = (items: unknown[], next: string | null) => ({
  success: true,
  data: { items, next_cursor: next },
});

describe('GET /analyses/export', () => {
  beforeEach(() => mocks.fetchAnalyses.mockReset());

  it('returns every page of the filtered view as CSV, from the newest', async () => {
    mocks.fetchAnalyses
      .mockResolvedValueOnce(ok([makeAnalysis({ id: 2 })], 'Y3Vy'))
      .mockResolvedValueOnce(ok([makeAnalysis({ id: 1 })], null));

    const response = await GET(
      new Request('http://localhost/analyses/export?symbol=EURUSD&cursor=aWQ6OQ==')
    );

    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/csv; charset=utf-8');
    expect(response.headers.get('Content-Disposition')).toMatch(
      /^attachment; filename="smc-analyses-\d{8}T\d{6}Z\.csv"$/
    );
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    expect(response.headers.get('X-Export-Truncated')).toBeNull();
    expect((await response.text()).trim().split('\r\n')).toHaveLength(3);
    expect(mocks.fetchAnalyses).toHaveBeenNthCalledWith(1, {
      symbol: 'EURUSD',
      action: undefined,
      minConfidence: undefined,
      limit: 200,
      cursor: undefined,
    });
    expect(mocks.fetchAnalyses).toHaveBeenNthCalledWith(
      2,
      expect.objectContaining({ cursor: 'Y3Vy' })
    );
  });

  it('stops at the page cap and says so', async () => {
    mocks.fetchAnalyses.mockResolvedValue(ok([makeAnalysis()], 'Y3Vy'));
    const response = await GET(new Request('http://localhost/analyses/export'));
    expect(mocks.fetchAnalyses).toHaveBeenCalledTimes(MAX_EXPORT_PAGES);
    expect(response.headers.get('X-Export-Truncated')).toBe('true');
  });

  it('is a plain-text error with the fixed message and 503 when the API is unreachable', async () => {
    mocks.fetchAnalyses.mockResolvedValue({ success: false, error: 'fixed message' });
    const response = await GET(new Request('http://localhost/analyses/export'));
    expect(response.status).toBe(503);
    expect(response.headers.get('Content-Type')).toBe('text/plain; charset=utf-8');
    expect(await response.text()).toBe('fixed message');
  });

  it('never returns a non-error status for a failure', async () => {
    mocks.fetchAnalyses.mockResolvedValue({ success: false, error: 'fixed', status: 200 });
    const response = await GET(new Request('http://localhost/analyses/export'));
    expect(response.status).toBe(502);
  });

  it('passes the API status through otherwise', async () => {
    mocks.fetchAnalyses.mockResolvedValue({ success: false, error: 'fixed', status: 502 });
    const response = await GET(new Request('http://localhost/analyses/export'));
    expect(response.status).toBe(502);
  });
});
