// @vitest-environment node
/** The scan and automation pages read the pickers' verdicts server-side and pass them down. */
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { makeStrategy } from '../../helpers/strategy-fixtures';

const mocks = vi.hoisted(() => ({
  fetchScan: vi.fn(),
  fetchScanConfig: vi.fn(),
  fetchStrategies: vi.fn(),
  fetchSchedules: vi.fn(),
  fetchBacktestVerdicts: vi.fn(),
}));
vi.mock('@/lib/api/scan', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/scan')>('@/lib/api/scan');
  return { ...actual, fetchScan: mocks.fetchScan, fetchScanConfig: mocks.fetchScanConfig };
});
vi.mock('@/lib/api/strategies', () => ({ fetchStrategies: mocks.fetchStrategies }));
vi.mock('@/lib/api/schedules', () => ({ fetchSchedules: mocks.fetchSchedules }));
vi.mock('@/lib/api/backtests', () => ({ fetchBacktestVerdicts: mocks.fetchBacktestVerdicts }));
vi.mock('@/app/scan/actions', () => ({ analyseScanAction: vi.fn() }));
vi.mock('@/app/automation/actions', () => ({
  saveScheduleAction: vi.fn(),
  toggleScheduleAction: vi.fn(),
  runScheduleAction: vi.fn(),
  deleteScheduleAction: vi.fn(),
}));

import AutomationPage from '@/app/automation/page';
import ScanPage from '@/app/scan/page';

const STRATEGIES = [makeStrategy(), makeStrategy({ slug: 'my-one', name: 'Mine', builtin: false })];

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.fetchScanConfig.mockResolvedValue({ success: false, error: 'down' });
  mocks.fetchStrategies.mockResolvedValue({ success: true, data: STRATEGIES });
  mocks.fetchScan.mockResolvedValue({ success: false, error: 'down' });
  mocks.fetchSchedules.mockResolvedValue({ success: true, data: [] });
  mocks.fetchBacktestVerdicts.mockResolvedValue({ 'my-one': 'survived' });
});

describe('strategy picker verdicts', () => {
  it('reach the scan form', async () => {
    const html = renderToStaticMarkup(await ScanPage({ searchParams: Promise.resolve({}) }));

    expect(mocks.fetchBacktestVerdicts).toHaveBeenCalledWith(STRATEGIES.map((s) => s.slug));
    expect(html).toContain('Mine · Survived');
  });

  it('reach the schedule form', async () => {
    const html = renderToStaticMarkup(await AutomationPage({ searchParams: Promise.resolve({}) }));

    expect(mocks.fetchBacktestVerdicts).toHaveBeenCalledWith(STRATEGIES.map((s) => s.slug));
    expect(html).toContain('Mine · Survived');
  });
});
