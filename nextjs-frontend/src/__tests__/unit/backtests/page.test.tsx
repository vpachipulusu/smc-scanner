// @vitest-environment node
/** The backtest page validates the slug, picks the run to show and covers each empty state. */
import { renderToStaticMarkup } from 'react-dom/server';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { makeStrategy } from '../../helpers/strategies-page-fixtures';
import { makeBacktest, makeListItem, makeSummary } from '../../helpers/backtest-fixtures';

const mocks = vi.hoisted(() => ({
  fetchStrategy: vi.fn(),
  fetchStrategies: vi.fn(),
  fetchConditionCatalogue: vi.fn(),
  fetchBacktests: vi.fn(),
  fetchBacktest: vi.fn(),
  fetchBacktestVerdicts: vi.fn(),
  fetchLatestBacktest: vi.fn(),
  notFound: vi.fn(),
}));
vi.mock('@/lib/api/strategies-write', () => ({
  fetchStrategy: mocks.fetchStrategy,
  fetchStrategies: mocks.fetchStrategies,
  fetchConditionCatalogue: mocks.fetchConditionCatalogue,
}));
vi.mock('@/lib/api/backtests', () => ({
  fetchBacktests: mocks.fetchBacktests,
  fetchBacktest: mocks.fetchBacktest,
  fetchBacktestVerdicts: mocks.fetchBacktestVerdicts,
  fetchLatestBacktest: mocks.fetchLatestBacktest,
}));
vi.mock('next/navigation', () => ({
  notFound: mocks.notFound,
  useRouter: () => ({ replace: vi.fn(), refresh: vi.fn() }),
}));
vi.mock('@/app/strategies/[slug]/backtest/actions', () => ({
  runBacktestAction: vi.fn(),
  pollBacktestAction: vi.fn(),
}));
vi.mock('@/app/strategies/actions', () => ({
  saveStrategyAction: vi.fn(),
  deleteStrategyAction: vi.fn(),
}));

import BacktestPage from '@/app/strategies/[slug]/backtest/page';
import StrategiesPage from '@/app/strategies/page';
import {
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTESTS_STORE_UNAVAILABLE_MESSAGE,
} from '@/lib/api/backtests-messages';
import { STRATEGIES_STORE_UNAVAILABLE_MESSAGE } from '@/lib/api/strategies-write-messages';

class NotFoundSignal extends Error {}

const ok = <T,>(data: T) => ({ success: true, data });
const fail = (error: string, status?: number) => ({ success: false, error, status });

const page = async (slug = 'my-one', run?: string) =>
  renderToStaticMarkup(
    await BacktestPage({
      params: Promise.resolve({ slug }),
      searchParams: Promise.resolve(run === undefined ? {} : { run }),
    })
  );

beforeEach(() => {
  for (const mock of Object.values(mocks)) mock.mockReset();
  mocks.notFound.mockImplementation(() => {
    throw new NotFoundSignal('NEXT_NOT_FOUND');
  });
  mocks.fetchStrategy.mockResolvedValue(ok(makeStrategy({ slug: 'my-one', name: 'Mine' })));
  mocks.fetchBacktests.mockResolvedValue(ok([makeListItem()]));
  mocks.fetchBacktest.mockResolvedValue(ok(makeBacktest()));
  mocks.fetchBacktestVerdicts.mockResolvedValue({});
  mocks.fetchLatestBacktest.mockResolvedValue(ok(null));
});

describe('BacktestPage', () => {
  it('shows the latest finished run with the run form and history', async () => {
    mocks.fetchBacktests.mockResolvedValue(
      ok([makeListItem({ id: 9, status: 'failed', verdict: null }), makeListItem({ id: 7 })])
    );
    const html = await page();

    expect(mocks.fetchBacktest).toHaveBeenCalledWith(7);
    expect(html).toContain('Backtest: Mine');
    expect(html).toContain('Backtest verdict: </span>Survived');
    expect(html).toContain('Against the baselines');
    expect(html).toContain('Run backtest');
    expect(html).toContain('History');
  });

  it('shows the run asked for and disables Run while one is in flight', async () => {
    mocks.fetchBacktests.mockResolvedValue(
      ok([makeListItem({ id: 9, status: 'running', verdict: null }), makeListItem({ id: 7 })])
    );
    mocks.fetchBacktest.mockResolvedValue(
      ok(makeBacktest({ id: 9, status: 'running', results: null }))
    );
    const html = await page('my-one', '9');

    expect(mocks.fetchBacktest).toHaveBeenCalledTimes(1);
    expect(mocks.fetchBacktest).toHaveBeenCalledWith(9);
    expect(html).toContain('This run is running.');
    expect(html).toMatch(/<button[^>]*aria-disabled="true"[^>]*>Run backtest/);
  });

  it('takes the header badge from the fresh list, not the badge cache', async () => {
    const html = await page();

    expect(mocks.fetchBacktests).toHaveBeenCalledWith('my-one', 50);
    expect(mocks.fetchBacktestVerdicts).not.toHaveBeenCalled();
    expect(mocks.fetchLatestBacktest).not.toHaveBeenCalled();
    expect(html).toContain('Backtest verdict: </span>Survived');
  });

  it('asks the API for the badge when a full list has no finished run', async () => {
    const failed = Array.from({ length: 50 }, (_, i) =>
      makeListItem({ id: 100 - i, status: 'failed', verdict: null })
    );
    mocks.fetchBacktests.mockResolvedValue(ok(failed));
    mocks.fetchBacktest.mockResolvedValue(
      ok(makeBacktest({ id: 100, status: 'failed', verdict: null, results: null }))
    );
    mocks.fetchLatestBacktest.mockResolvedValue(
      ok(makeSummary({ verdict: 'insufficient', low_sample: true }))
    );
    const html = await page();

    expect(mocks.fetchLatestBacktest).toHaveBeenCalledWith('my-one');
    expect(html).toContain('Backtest verdict: </span>Insufficient');
  });

  it('says Not run without a read when a short list has no finished run', async () => {
    mocks.fetchBacktests.mockResolvedValue(
      ok([makeListItem({ id: 9, status: 'failed', verdict: null })])
    );
    mocks.fetchBacktest.mockResolvedValue(
      ok(makeBacktest({ id: 9, status: 'failed', verdict: null, results: null }))
    );
    const html = await page();

    expect(mocks.fetchLatestBacktest).not.toHaveBeenCalled();
    expect(html).toContain('Backtest verdict: </span>Not run');
  });

  it('says Not run when the strategy has no runs', async () => {
    mocks.fetchBacktests.mockResolvedValue(ok([]));
    const html = await page();

    expect(mocks.fetchBacktest).not.toHaveBeenCalled();
    expect(html).toContain('data-testid="not-run"');
    expect(html).toContain('Backtest verdict: </span>Not run');
    expect(html).toContain('No runs yet.');
  });

  it('treats a run of another strategy as not found', async () => {
    mocks.fetchBacktest.mockResolvedValue(ok(makeBacktest({ id: 3, strategy: 'other' })));
    const html = await page('my-one', '3');
    expect(html).toContain(BACKTEST_NOT_FOUND_MESSAGE);
  });

  it('shows a failed list with a retry link and still offers Run', async () => {
    mocks.fetchBacktests.mockResolvedValue(fail(BACKTESTS_STORE_UNAVAILABLE_MESSAGE, 503));
    mocks.fetchStrategy.mockResolvedValue(fail(STRATEGIES_STORE_UNAVAILABLE_MESSAGE, 503));
    const html = await page();

    expect(html).toContain(BACKTESTS_STORE_UNAVAILABLE_MESSAGE);
    expect(html).toContain(STRATEGIES_STORE_UNAVAILABLE_MESSAGE);
    expect(html).toContain('Backtest: my-one');
    expect(html).toContain('href="/strategies/my-one/backtest"');
    expect(html).toContain('Run backtest');
    // The strategy could not be confirmed, so no badge is read for it.
    expect(mocks.fetchLatestBacktest).not.toHaveBeenCalled();
  });

  it('is not found for a bad slug or a deleted strategy', async () => {
    await expect(page('Bad Slug')).rejects.toThrow(NotFoundSignal);
    mocks.fetchStrategy.mockResolvedValue(fail('gone', 404));
    mocks.fetchBacktests.mockResolvedValue(fail('down', 503));
    await expect(page('gone-one')).rejects.toThrow(NotFoundSignal);
    expect(mocks.fetchLatestBacktest).not.toHaveBeenCalled();
    expect(mocks.fetchBacktestVerdicts).not.toHaveBeenCalled();
  });
});

describe('StrategiesPage verdict badges', () => {
  it('reads the verdicts of the listed slugs server-side', async () => {
    mocks.fetchStrategies.mockResolvedValue(ok([makeStrategy({ slug: 'my-one', name: 'Mine' })]));
    mocks.fetchConditionCatalogue.mockResolvedValue(ok([]));
    mocks.fetchBacktestVerdicts.mockResolvedValue({ 'my-one': 'failed' });

    const html = renderToStaticMarkup(await StrategiesPage({ searchParams: Promise.resolve({}) }));

    expect(mocks.fetchBacktestVerdicts).toHaveBeenCalledWith(['my-one']);
    expect(html).toContain('Backtest verdict: </span>Failed');
  });
});
