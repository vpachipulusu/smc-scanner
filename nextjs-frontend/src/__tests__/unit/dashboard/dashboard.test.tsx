// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FAILURE, makeResponse, makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchScan: vi.fn() }));

vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan };
});

import HomePage from '@/app/page';
import DashboardLoading from '@/app/loading';
import { SCAN_UNAVAILABLE_MESSAGE } from '@/lib/api/scan';

const page = () => HomePage().then(renderToStaticMarkup);

describe('Dashboard page', () => {
  beforeEach(() => {
    mocks.fetchScan.mockReset();
  });

  it('scans with the default params', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    await page();

    expect(mocks.fetchScan).toHaveBeenCalledWith({
      source: 'mt5',
      tf: '1h',
      symbols: [],
      bars: 500,
      swing: 10,
      near: 0.5,
      allTouches: false,
    });
  });

  it('lists only TOUCHING hits and summarises the scan', async () => {
    mocks.fetchScan.mockResolvedValue({
      success: true,
      data: makeResponse(
        [
          makeRow({ instrument: 'EURUSD' }),
          makeRow({ instrument: 'XAUUSD', status: 'NEAR' }),
          makeRow({ instrument: 'GBPUSD' }),
        ],
        [FAILURE]
      ),
    });

    const html = await page();

    expect(html).toContain('<h1');
    expect(html).toContain('TOUCHING now');
    expect(html).toContain('EURUSD');
    expect(html).toContain('GBPUSD');
    expect(html).not.toContain('XAUUSD');
    expect(html).toContain('3 rows');
    expect(html).toContain('1 symbol skipped');
  });

  it('shows an empty state when nothing is touching', async () => {
    mocks.fetchScan.mockResolvedValue({
      success: true,
      data: makeResponse([makeRow({ status: 'NEAR' })]),
    });

    const html = await page();

    expect(html).toContain('No instrument is touching a fresh zone right now.');
  });

  it('shows a short safe message with an alert role when the API is down', async () => {
    mocks.fetchScan.mockResolvedValue({ success: false, error: 'boom: secret trace' });

    const html = await page();

    expect(html).toContain('role="alert"');
    expect(html).toContain(SCAN_UNAVAILABLE_MESSAGE);
    expect(html).not.toContain('secret trace');
  });

  it('tolerates the wrapper throwing', async () => {
    mocks.fetchScan.mockImplementation(() => {
      throw new Error('network down');
    });

    const html = await page();

    expect(html).toContain('role="alert"');
    expect(html).not.toContain('network down');
  });

  it('shows explicit empty states for the cards that wait on the Analyses API', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await page();

    for (const title of ['Latest verdicts', 'Next scheduled run', 'Last run status']) {
      expect(html).toContain(title);
    }
    expect(html.match(/available after the Analyses API \/ scheduler land/g)).toHaveLength(3);
    expect(html).not.toContain('role="progressbar"');
  });

  it('keeps headings in order: one h1, then h2 only', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await page();

    expect(html.match(/<h1/g)).toHaveLength(1);
    expect(html).not.toMatch(/<h3/);
    expect(html.indexOf('<h1')).toBeLessThan(html.indexOf('<h2'));
  });
});

describe('DashboardLoading', () => {
  it('renders a busy status skeleton', () => {
    const html = renderToStaticMarkup(DashboardLoading());

    expect(html).toContain('role="status"');
    expect(html).toContain('aria-busy="true"');
  });
});
