// @vitest-environment node
/** The detail page shows the fixed error message with a heading and way back, and sets its title. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeAnalysis } from '../../helpers/fixtures';

const mocks = vi.hoisted(() => ({ fetchAnalysis: vi.fn() }));

vi.mock('@/lib/api/analyses', () => ({ fetchAnalysis: mocks.fetchAnalysis }));
vi.mock('next/navigation', () => ({
  notFound: () => {
    throw new Error('NEXT_NOT_FOUND');
  },
}));

import AnalysisPage, { generateMetadata } from '@/app/analyses/[id]/page';
import {
  ANALYSES_REQUEST_FAILED_MESSAGE,
  ANALYSES_UNAUTHORIZED_MESSAGE,
  ANALYSES_UNAVAILABLE_MESSAGE,
} from '@/lib/api/analyses-messages';

const props = (id: string) => ({ params: Promise.resolve({ id }) });
const html = async (id = '3') => renderToStaticMarkup(await AnalysisPage(props(id)));

describe('AnalysisPage errors', () => {
  beforeEach(() => mocks.fetchAnalysis.mockReset());

  it.each([
    [500, ANALYSES_REQUEST_FAILED_MESSAGE],
    [401, ANALYSES_UNAUTHORIZED_MESSAGE],
    [undefined, ANALYSES_UNAVAILABLE_MESSAGE],
  ])('status %s shows the message under a heading with a way back', async (status, message) => {
    mocks.fetchAnalysis.mockResolvedValue({ success: false, error: message, status });

    const out = await html();

    expect(out).toContain(message);
    expect(out).toContain('<h1');
    expect(out).toContain('Analysis #3');
    expect(out).toContain('href="/"');
    expect(out).toContain('Back to dashboard');
  });

  it('does not fetch ids above the int32 range', async () => {
    await expect(html('2147483648')).rejects.toThrow('NEXT_NOT_FOUND');
    expect(mocks.fetchAnalysis).not.toHaveBeenCalled();
  });
});

describe('generateMetadata', () => {
  beforeEach(() => mocks.fetchAnalysis.mockReset());

  it('titles the page with the symbol and timeframe', async () => {
    mocks.fetchAnalysis.mockResolvedValue({ success: true, data: makeAnalysis() });

    expect(await generateMetadata(props('1'))).toEqual({ title: 'EURUSD 1h analysis' });
  });

  it('uses the static title for a bad id or a failed read', async () => {
    expect(await generateMetadata(props('abc'))).toEqual({ title: 'Analysis' });
    expect(mocks.fetchAnalysis).not.toHaveBeenCalled();

    mocks.fetchAnalysis.mockResolvedValue({ success: false, error: 'x', status: 404 });
    expect(await generateMetadata(props('9'))).toEqual({ title: 'Analysis' });
  });
});
