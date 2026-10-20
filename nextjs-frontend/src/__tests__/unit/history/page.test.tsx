// @vitest-environment node
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeAnalysis } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchAnalyses: vi.fn() }));

vi.mock('@/lib/api/analyses', async () => {
  const actual = await vi.importActual<typeof import('@/lib/api/analyses')>('@/lib/api/analyses');
  return { ...actual, fetchAnalyses: mocks.fetchAnalyses };
});

import AnalysesPage from '@/app/analyses/page';
import HistoryLoading from '@/app/analyses/loading';
import { ANALYSES_UNAVAILABLE_MESSAGE } from '@/lib/api/analyses-messages';

const page = (raw: Record<string, string | string[]> = {}) =>
  AnalysesPage({ searchParams: Promise.resolve(raw) }).then(renderToStaticMarkup);

describe('AnalysesPage', () => {
  beforeEach(() => mocks.fetchAnalyses.mockReset());

  it('queries with the validated filters and renders rows with a CSV link', async () => {
    mocks.fetchAnalyses.mockResolvedValue({
      success: true,
      data: { items: [makeAnalysis({ id: 9 })], next_cursor: 'bmV4dA==' },
    });

    const html = await page({ symbol: 'EURUSD', action: 'buy', min_conf: '50', evil: 'x' });

    expect(mocks.fetchAnalyses).toHaveBeenCalledWith({
      symbol: 'EURUSD',
      action: 'BUY',
      minConfidence: 50,
      cursor: undefined,
      limit: 25,
    });
    expect(html).toContain('href="/analyses/9"');
    expect(html).toContain('href="/analyses/export?symbol=EURUSD&amp;action=BUY&amp;min_conf=50"');
    expect(html).toContain('cursor=bmV4dA%3D%3D');
  });

  it('passes the cursor on and offers the way back', async () => {
    mocks.fetchAnalyses.mockResolvedValue({
      success: true,
      data: { items: [makeAnalysis()], next_cursor: null },
    });
    const html = await page({ cursor: 'aWQ6NDI=' });
    expect(mocks.fetchAnalyses).toHaveBeenCalledWith(
      expect.objectContaining({ cursor: 'aWQ6NDI=' })
    );
    expect(html).toContain('Newest');
    expect(html).not.toContain('Older');
  });

  it('shows the empty state without a CSV link', async () => {
    mocks.fetchAnalyses.mockResolvedValue({
      success: true,
      data: { items: [], next_cursor: null },
    });
    const html = await page({ symbol: 'ZZZ' });
    expect(html).toContain('No analyses match');
    expect(html).not.toContain('/analyses/export');
  });

  it('shows the fixed message with a retry link', async () => {
    mocks.fetchAnalyses.mockResolvedValue({
      success: false,
      error: ANALYSES_UNAVAILABLE_MESSAGE,
    });
    const html = await page({ symbol: 'EURUSD' });
    expect(html).toContain('role="alert"');
    expect(html).toContain(ANALYSES_UNAVAILABLE_MESSAGE);
    expect(html).toContain('href="/analyses?symbol=EURUSD"');
  });
});

describe('HistoryLoading', () => {
  it('is a labelled status region', () => {
    expect(renderToStaticMarkup(HistoryLoading())).toContain('role="status"');
  });
});
