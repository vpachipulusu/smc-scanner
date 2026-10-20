// @vitest-environment node
/** The detail page validates the id, maps 404 to notFound() and shows only the fixed error messages. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeAnalysis } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchAnalysis: vi.fn(), notFound: vi.fn() }));

vi.mock('@/lib/api/analyses', () => ({ fetchAnalysis: mocks.fetchAnalysis }));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));

import AnalysisPage from '@/app/analyses/[id]/page';
import AnalysisLoading from '@/app/analyses/[id]/loading';
import AnalysisNotFound from '@/app/analyses/[id]/not-found';
import { ANALYSES_REQUEST_FAILED_MESSAGE } from '@/lib/api/analyses-messages';

class NotFoundSignal extends Error {}

const page = (id: string) => AnalysisPage({ params: Promise.resolve({ id }) });

describe('AnalysisPage', () => {
  beforeEach(() => {
    mocks.fetchAnalysis.mockReset();
    mocks.notFound.mockReset();
    mocks.notFound.mockImplementation(() => {
      throw new NotFoundSignal('NEXT_NOT_FOUND');
    });
  });

  it('renders the analysis for a valid id', async () => {
    mocks.fetchAnalysis.mockResolvedValue({ success: true, data: makeAnalysis({ id: 7 }) });

    const html = renderToStaticMarkup(await page('7'));

    expect(mocks.fetchAnalysis).toHaveBeenCalledWith(7);
    expect(html).toContain('EURUSD');
    expect(html).toContain('advisory only');
  });

  it.each(['abc', '0', '-3', '1.5', '1e2'])(
    'calls notFound without fetching for id %s',
    async (id) => {
      await expect(page(id)).rejects.toBeInstanceOf(NotFoundSignal);
      expect(mocks.fetchAnalysis).not.toHaveBeenCalled();
    }
  );

  it('calls notFound when the API says 404', async () => {
    mocks.fetchAnalysis.mockResolvedValue({ success: false, error: 'x', status: 404 });

    await expect(page('99')).rejects.toBeInstanceOf(NotFoundSignal);
  });

  it('shows the fixed message for other failures, never the raw error text', async () => {
    mocks.fetchAnalysis.mockResolvedValue({
      success: false,
      error: ANALYSES_REQUEST_FAILED_MESSAGE,
      status: 500,
    });

    const html = renderToStaticMarkup(await page('3'));

    expect(html).toContain('role="alert"');
    expect(html).toContain(ANALYSES_REQUEST_FAILED_MESSAGE);
    expect(html).toContain('href="/analyses/3"');
  });

  it('has a loading state and a 404 page that link back', () => {
    expect(renderToStaticMarkup(<AnalysisLoading />)).toContain('role="status"');
    const html = renderToStaticMarkup(<AnalysisNotFound />);
    expect(html).toContain('No analysis with that id.');
    expect(html).toContain('href="/"');
  });
});
