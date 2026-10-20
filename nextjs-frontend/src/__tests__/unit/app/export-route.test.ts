// @vitest-environment node
/** GET /scan/export runs the same scan and returns CSV, or the curated error as JSON. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeResponse, makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchScan: vi.fn() }));

vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan };
});

import { GET, exportErrorStatus } from '@/app/scan/export/route';
import { SCAN_UNAVAILABLE_MESSAGE } from '@/lib/api/scan';

describe('GET /scan/export', () => {
  beforeEach(() => {
    mocks.fetchScan.mockReset();
  });

  it('returns the rows as a CSV attachment', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([makeRow()]) });

    const response = await GET(new Request('http://localhost/scan/export?source=demo&tf=15m'));

    expect(response.status).toBe(200);
    expect(response.headers.get('Content-Type')).toBe('text/csv; charset=utf-8');
    expect(response.headers.get('Content-Disposition')).toMatch(
      /^attachment; filename="smc-scan-demo-15m-\d{8}T\d{6}Z\.csv"$/
    );
    expect(response.headers.get('Cache-Control')).toBe('no-store');
    const body = await response.text();
    expect(body.startsWith('instrument,status,zone,')).toBe(true);
    expect(body).toContain('EURUSD,TOUCHING,bull FVG,');
    expect(mocks.fetchScan).toHaveBeenCalledWith(
      expect.objectContaining({ source: 'demo', tf: '15m', symbols: [] })
    );
  });

  it('is a 503 JSON error when the API is unreachable', async () => {
    mocks.fetchScan.mockResolvedValue({ success: false, error: 'Backend unavailable' });

    const response = await GET(new Request('http://localhost/scan/export'));

    expect(response.status).toBe(503);
    expect(await response.json()).toEqual({ success: false, error: SCAN_UNAVAILABLE_MESSAGE });
  });

  it('passes the API status through otherwise', async () => {
    mocks.fetchScan.mockResolvedValue({ success: false, error: 'Unauthorized', status: 401 });

    const response = await GET(new Request('http://localhost/scan/export'));

    expect(response.status).toBe(401);
    expect(exportErrorStatus(undefined)).toBe(503);
    expect(exportErrorStatus(422)).toBe(422);
  });
});
