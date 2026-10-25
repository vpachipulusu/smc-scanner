// @vitest-environment node
/** Pages and wrappers carry the strategy: scan deep links, analyse, CSV, automation and analysis detail. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeAnalysis, makeResponse, makeRow } from '../../helpers/fixtures';
import { makeSchedule } from '../../helpers/automation-fixtures';
import { makeStrategy } from '../../helpers/strategy-fixtures';

const mocks = vi.hoisted(() => ({
  fetchScan: vi.fn(),
  fetchScanConfig: vi.fn(),
  fetchStrategies: vi.fn(),
  fetchSchedules: vi.fn(),
  fetchAnalysis: vi.fn(),
  fetchCalendar: vi.fn(),
}));

vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan, fetchScanConfig: mocks.fetchScanConfig };
});
vi.mock('@/lib/api/strategies', () => ({ fetchStrategies: mocks.fetchStrategies }));
vi.mock('@/lib/api/schedules', () => ({ fetchSchedules: mocks.fetchSchedules }));
vi.mock('@/lib/api/analyses', () => ({ fetchAnalysis: mocks.fetchAnalysis }));
vi.mock('@/lib/api/calendar', () => ({ fetchCalendar: mocks.fetchCalendar }));
vi.mock('next/navigation', () => ({ notFound: vi.fn(), useRouter: () => ({ refresh: vi.fn() }) }));
vi.mock('@/app/automation/actions', () => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));

import AnalysisPage from '@/app/analyses/[id]/page';
import AutomationPage from '@/app/automation/page';
import ScanPage from '@/app/scan/page';
import { GET as exportScan } from '@/app/scan/export/route';

const CONFIG = {
  sources: ['mt5', 'demo'],
  timeframes: ['1h'],
  defaults: { source: 'mt5', tf: '1h', bars: 500, swing: 10, near: 0.5 },
  limits: { min_bars: 15, max_bars: 5000, max_swing: 100, max_near: 5, max_symbols: 50 },
  watchlist: { mt5: [], demo: [] },
  ai_enabled: false,
  telegram_enabled: false,
  strategies: [
    { slug: 'smc-default', name: 'SMC default', builtin: true, swing_length: 10, near_atr: 0.5 },
    {
      slug: 'htf-aligned-touch',
      name: 'HTF aligned touch',
      builtin: true,
      swing_length: 8,
      near_atr: 0.3,
    },
  ],
  conditions: [{ key: 'htf_aligned', label: 'HTF aligned', params_schema: {} }],
};

const STRATEGIES = [
  makeStrategy(),
  makeStrategy({ slug: 'htf-aligned-touch', name: 'HTF aligned touch', mtf: true }),
];

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.fetchScanConfig.mockResolvedValue({ success: true, data: CONFIG });
  mocks.fetchStrategies.mockResolvedValue({ success: true, data: STRATEGIES });
  mocks.fetchCalendar.mockResolvedValue({ success: false, error: 'x' });
});

const scanPage = (raw: Record<string, string>) =>
  ScanPage({ searchParams: Promise.resolve(raw) }).then(renderToStaticMarkup);

describe('ScanPage with a strategy', () => {
  it('fills swing and near of a deep link from the strategy and shows chips and the HTF column', async () => {
    mocks.fetchScan.mockResolvedValue({
      success: true,
      data: makeResponse([makeRow({ conditions: { htf_aligned: true } })], [], {
        strategy: 'htf-aligned-touch',
      }),
    });

    const html = await scanPage({ strategy: 'htf-aligned-touch' });

    expect(mocks.fetchScan).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: 'htf-aligned-touch', swing: 8, near: 0.3, mtf: false })
    );
    expect(html).toContain('1 hit on 1h (mt5) with HTF aligned touch.');
    expect(html).toContain('HTF aligned<span class="sr-only">: met</span>');
    expect(html).toContain('data-testid="mtf-summary"');
    expect(html).toContain('/scan/export?strategy=htf-aligned-touch&amp;swing=8&amp;near=0.3');
    expect(html).toContain('<optgroup label="Built-in">');
  });

  it('does not flag a custom slug when only the built-ins loaded', async () => {
    mocks.fetchStrategies.mockResolvedValue({ success: false, error: 'x', status: 503 });
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await scanPage({ strategy: 'my-setup', swing: '5', near: '1' });

    expect(html).toContain('>my-setup</option>');
    expect(html).not.toContain('(not found)');
  });

  it('survives a malformed /config strategy list', async () => {
    mocks.fetchScanConfig.mockResolvedValue({
      success: true,
      data: { ...CONFIG, strategies: [null, { slug: 'htf-aligned-touch' }], conditions: [null] },
    });
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    await scanPage({ strategy: 'htf-aligned-touch' });

    expect(mocks.fetchScan).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: 'htf-aligned-touch', swing: 10, near: 0.5 })
    );
  });

  it('keeps the URL tuning and still renders when the strategy lists fail', async () => {
    mocks.fetchScanConfig.mockResolvedValue({ success: false, error: 'x' });
    mocks.fetchStrategies.mockResolvedValue({ success: false, error: 'x' });
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([]) });

    const html = await scanPage({ strategy: 'my-setup', swing: '4', near: '1' });

    expect(mocks.fetchScan).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: 'my-setup', swing: 4, near: 1 })
    );
    expect(html).toContain('on 1h with my-setup.');
  });

  it('shows the API 422 for an unknown strategy', async () => {
    mocks.fetchScan.mockResolvedValue({ success: false, error: 'Unknown strategy', status: 422 });

    const html = await scanPage({ strategy: 'gone' });

    expect(html).toContain('Unknown strategy');
    expect(html).toContain('gone (not found)');
  });
});

describe('scan CSV route', () => {
  it('names the strategy in the download', async () => {
    mocks.fetchScan.mockResolvedValue({ success: true, data: makeResponse([makeRow()]) });

    const response = await exportScan(
      new Request('http://x/scan/export?strategy=fresh-ob-trend&swing=7&near=0.3')
    );

    expect(mocks.fetchScan).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: 'fresh-ob-trend', swing: 7, near: 0.3 })
    );
    expect(response.headers.get('Content-Disposition')).toMatch(
      /filename="smc-scan-mt5-1h-fresh-ob-trend-\d{8}T\d{6}Z\.csv"/
    );
  });
});

describe('AutomationPage strategies', () => {
  it('lists strategy slugs, flags deleted ones and offers the picker', async () => {
    mocks.fetchSchedules.mockResolvedValue({
      success: true,
      data: [makeSchedule(), makeSchedule({ id: 2, name: 'Old', strategy: 'gone' })],
    });

    const html = renderToStaticMarkup(await AutomationPage({ searchParams: Promise.resolve({}) }));

    expect(html).toContain('Strategy missing: runs use smc-default');
    expect(html).toContain('id="schedule-strategy"');
    expect(html).toContain('HTF aligned touch');
  });

  it('does not flag schedules when the strategy list failed', async () => {
    mocks.fetchStrategies.mockResolvedValue({ success: false, error: 'x', status: 503 });
    mocks.fetchSchedules.mockResolvedValue({
      success: true,
      data: [makeSchedule({ strategy: 'gone' })],
    });

    const html = renderToStaticMarkup(await AutomationPage({ searchParams: Promise.resolve({}) }));

    expect(html).not.toContain('Strategy missing');
  });
});

describe('AnalysisPage strategy', () => {
  it('names the stored strategy, or falls back to its slug', async () => {
    mocks.fetchAnalysis.mockResolvedValue({
      success: true,
      data: makeAnalysis({ strategy: 'htf-aligned-touch' }),
    });
    const page = () => AnalysisPage({ params: Promise.resolve({ id: '1' }) });

    expect(renderToStaticMarkup(await page())).toContain('HTF aligned touch (htf-aligned-touch)');

    mocks.fetchStrategies.mockResolvedValue({ success: false, error: 'x' });
    expect(renderToStaticMarkup(await page())).toContain('htf-aligned-touch');
  });
});

describe('API wrappers', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
  const json = (body: unknown) =>
    new Response(JSON.stringify(body), { headers: { 'Content-Type': 'application/json' } });

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubGlobal('fetch', fetchMock);
  });
  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('sends a non-default strategy to GET /scan and leaves the default out', async () => {
    const { fetchScan } = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
    const { DEFAULTS } = await import('@/lib/scan/params');
    fetchMock.mockImplementation(async () => json(makeResponse([])));

    await fetchScan({ ...DEFAULTS, strategy: 'fresh-ob-trend' });
    await fetchScan(DEFAULTS);

    expect(new URL(fetchMock.mock.calls[0][0].url).searchParams.get('strategy')).toBe(
      'fresh-ob-trend'
    );
    expect(new URL(fetchMock.mock.calls[1][0].url).searchParams.has('strategy')).toBe(false);
  });

  it('posts the strategy to /analyse and keeps checked strategy and conditions', async () => {
    const { runAnalyse } = await import('@/lib/api/analyse');
    const { DEFAULTS } = await import('@/lib/scan/params');
    fetchMock.mockResolvedValue(
      json({
        source: 'mt5',
        tf: '1h',
        strategy: 'fresh-ob-trend',
        count: 1,
        failures: [],
        rows: [
          {
            ...makeRow(),
            strategy: 'fresh-ob-trend',
            conditions: { fresh: true, '<x>': true, aligned: 'yes' },
            ai: { status: 'analysed', note: 'raw', verdict: { action: 'BUY', confidence: 70 } },
          },
        ],
      })
    );

    const result = await runAnalyse({ ...DEFAULTS, strategy: 'fresh-ob-trend' });

    expect(await fetchMock.mock.calls[0][0].json()).toMatchObject({ strategy: 'fresh-ob-trend' });
    expect(result.success && result.data.strategy).toBe('fresh-ob-trend');
    expect(result.success && result.data.rows[0]).toMatchObject({
      strategy: 'fresh-ob-trend',
      conditions: { fresh: true },
    });
    expect(result.success && result.data.rows[0].conditions).toEqual({ fresh: true });
  });

  it('accepts schedules with and without a strategy, refusing a malformed one', async () => {
    const { fetchSchedules } =
      await vi.importActual<typeof import('@/lib/api/schedules')>('@/lib/api/schedules');
    fetchMock.mockImplementation(async () =>
      json({ items: [makeSchedule(), makeSchedule({ id: 2, strategy: 'my-setup' })] })
    );
    expect((await fetchSchedules()).success).toBe(true);

    fetchMock.mockImplementation(async () => json({ items: [makeSchedule({ strategy: '<b>' })] }));
    expect((await fetchSchedules()).success).toBe(false);
  });
});
