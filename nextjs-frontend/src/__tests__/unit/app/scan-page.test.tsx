// @vitest-environment node
/** The scan page composes the form, results, failures and errors from the server wrappers. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FAILURE, makeResponse, makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchScan: vi.fn(), fetchScanConfig: vi.fn() }));

vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan, fetchScanConfig: mocks.fetchScanConfig };
});

import ScanPage from '@/app/scan/page';
import { SCAN_UNAVAILABLE_MESSAGE } from '@/lib/api/scan';

const CONFIG = {
  sources: ['mt5', 'demo'],
  timeframes: ['5m', '15m', '30m', '1h', '4h', '1d'],
  defaults: { source: 'mt5', tf: '1h', bars: 500, swing: 10, near: 0.5 },
  limits: { min_bars: 15, max_bars: 5000, max_swing: 100, max_near: 5, max_symbols: 50 },
  watchlist: { mt5: ['EURUSD'], demo: ['EURUSD'] },
};

const page = (raw: Record<string, string> = {}) =>
  ScanPage({ searchParams: Promise.resolve(raw) }).then(renderToStaticMarkup);

describe('ScanPage', () => {
  beforeEach(() => {
    mocks.fetchScan.mockReset();
    mocks.fetchScanConfig.mockReset();
    mocks.fetchScanConfig.mockResolvedValue({ success: true, data: CONFIG });
  });

  it('runs the scan from the URL and renders the rows with a CSV link', async () => {
    mocks.fetchScan.mockResolvedValue({
      success: true,
      data: makeResponse([makeRow(), makeRow({ instrument: 'XAUUSD', status: 'NEAR' })]),
    });

    const html = await page({ source: 'demo', tf: '15m', symbols: 'EURUSD,XAUUSD' });

    expect(mocks.fetchScan).toHaveBeenCalledWith({
      source: 'demo',
      tf: '15m',
      symbols: ['EURUSD', 'XAUUSD'],
      bars: 500,
      swing: 10,
      near: 0.5,
      allTouches: false,
    });
    expect(html).toContain('2 hits on 15m (demo).');
    expect(html.match(/data-testid="scan-row"/g)).toHaveLength(2);
    expect(html).toContain(
      'href="/scan/export?source=demo&amp;tf=15m&amp;symbols=EURUSD%2CXAUUSD"'
    );
    expect(html).toContain('Last scan at');
  });

  it('says so when nothing is near a zone and hides the download', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await page();

    expect(html).toContain('No instrument is touching or near a fresh zone on 1h.');
    expect(html).not.toContain('/scan/export');
    expect(html).not.toContain('data-testid="scan-row"');
  });

  it('lists the symbols the API skipped next to the rows', async () => {
    mocks.fetchScan.mockResolvedValue({
      success: true,
      data: makeResponse([makeRow()], [FAILURE]),
    });

    const html = await page();

    expect(html).toContain('1 symbol skipped');
    expect(html).toContain('BTCUSD');
  });

  it('shows the curated error with a retry link when the scan fails', async () => {
    mocks.fetchScan.mockResolvedValue({ success: false, error: 'Backend unavailable' });
    mocks.fetchScanConfig.mockResolvedValue({ success: false, error: 'Backend unavailable' });

    const html = await page({ tf: '4h' });

    expect(html).toContain('role="alert"');
    expect(html).toContain(SCAN_UNAVAILABLE_MESSAGE);
    expect(html).toContain('href="/scan?tf=4h"');
    // The form still renders from the built-in choices.
    expect(html).toContain('<option value="4h" selected="">4h</option>');
  });

  it('wires the rescan interval into the auto-refresh line', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await page({ every: '5', tf: '5m' });

    expect(html).toContain('Rescanning every 5 min');
    expect(html).toContain('href="/scan?tf=5m"');
  });
});
