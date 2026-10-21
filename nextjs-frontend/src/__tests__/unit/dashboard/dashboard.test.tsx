// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { FAILURE, makeResponse, makeRow } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchScan: vi.fn(), fetchAnalyses: vi.fn() }));

vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan };
});

vi.mock('@/lib/api/analyses', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/analyses')>('@/lib/api/analyses');
  return { ...actual, fetchAnalyses: mocks.fetchAnalyses };
});

import HomePage from '@/app/page';
import DashboardLoading from '@/app/loading';
import { SCAN_UNAVAILABLE_MESSAGE } from '@/lib/api/scan';
import { analysesUnavailableMessage } from '@/lib/api/analyses-messages';
import { makeAnalysis } from '../../helpers/fixtures';

const page = () => HomePage().then(renderToStaticMarkup);

describe('Dashboard page', () => {
  beforeEach(() => {
    mocks.fetchScan.mockReset();
    mocks.fetchAnalyses.mockReset();
    mocks.fetchAnalyses.mockResolvedValue({ success: true, data: { items: [] } });
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
      mtf: false,
      requireHtfAligned: false,
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

  it('requests the latest ten verdicts and renders them', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });
    mocks.fetchAnalyses.mockResolvedValue({
      success: true,
      data: { items: [makeAnalysis({ id: 42, symbol: 'USDJPY' })] },
    });

    const html = await page();

    expect(mocks.fetchAnalyses).toHaveBeenCalledWith({ limit: 10 });
    expect(html).toContain('USDJPY');
    expect(html).toContain('role="progressbar"');
    expect(html).toContain('#42');
    expect(html).toContain('href="/analyses/42"');
  });

  it('shows the empty verdicts state', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    expect(await page()).toContain('No verdicts yet.');
  });

  it('keeps the scan cards when only the analyses fail', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([makeRow()]) });
    mocks.fetchAnalyses.mockResolvedValue({ success: false, error: 'secret', status: 500 });

    const html = await page();

    expect(html).toContain('TOUCHING now');
    expect(html).toContain('role="alert"');
    expect(html).not.toContain('secret');
  });

  it('tolerates the analyses wrapper throwing', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });
    mocks.fetchAnalyses.mockRejectedValue(new Error('network down'));

    const html = await page();

    expect(html).toContain(analysesUnavailableMessage());
    expect(html).not.toContain('network down');
  });

  it('labels the scheduler cards as coming soon', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await page();

    for (const title of ['Next scheduled run', 'Last run status']) {
      expect(html).toContain(title);
    }
    expect(html.match(/Coming soon/g)).toHaveLength(2);
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
