// @vitest-environment node
/** The analyses wrapper maps queries to the API, checks body shapes and never exposes backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchAnalyses, fetchAnalysis } from '@/lib/api/analyses';
import {
  ANALYSES_REQUEST_FAILED_MESSAGE,
  ANALYSES_UNAUTHORIZED_HINT,
  ANALYSES_UNAUTHORIZED_MESSAGE,
  ANALYSES_UNAVAILABLE_HINT,
  ANALYSES_UNAVAILABLE_MESSAGE,
  ANALYSIS_NOT_FOUND_MESSAGE,
  analysesErrorMessage,
  analysesUnavailableMessage,
} from '@/lib/api/analyses-messages';
import { makeAnalysis } from '../../helpers/fixtures';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('analyses wrapper', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  describe('fetchAnalyses', () => {
    it('returns the page and maps the query', async () => {
      const page = { items: [makeAnalysis()], next_cursor: null };
      fetchMock.mockResolvedValue(jsonResponse(page));

      const result = await fetchAnalyses({
        symbol: 'EURUSD',
        action: 'BUY',
        minConfidence: 60,
        limit: 10,
        cursor: 'abc',
      });

      expect(result).toEqual({ success: true, data: page });
      const url = new URL(fetchMock.mock.calls[0][0].url);
      expect(url.pathname).toBe('/analyses');
      expect(Object.fromEntries(url.searchParams)).toEqual({
        symbol: 'EURUSD',
        action: 'BUY',
        min_confidence: '60',
        limit: '10',
        cursor: 'abc',
      });
    });

    it('sends no parameters by default', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ items: [] }));

      expect(await fetchAnalyses()).toEqual({ success: true, data: { items: [] } });
      expect([...new URL(fetchMock.mock.calls[0][0].url).searchParams]).toEqual([]);
    });

    it('refuses a body without items', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ nope: true }));

      expect(await fetchAnalyses()).toEqual({
        success: false,
        error: ANALYSES_REQUEST_FAILED_MESSAGE,
        status: 502,
      });
    });

    it('replaces backend error text with a fixed message', async () => {
      fetchMock.mockResolvedValue(
        jsonResponse({ success: false, error: 'psycopg2 secret trace' }, 500)
      );

      expect(await fetchAnalyses()).toEqual({
        success: false,
        error: ANALYSES_REQUEST_FAILED_MESSAGE,
        status: 500,
      });
    });

    it('drops invalid rows and keeps the good ones', async () => {
      const good = makeAnalysis({ id: 1 });
      const nonNull = makeAnalysis({ id: 2, status: 'failed', verdict: null });
      fetchMock.mockResolvedValue(
        jsonResponse({
          items: [
            null,
            good,
            { id: 1 },
            { ...makeAnalysis({ id: 3 }), status: 'weird' },
            makeAnalysis({ id: 4, verdict: { action: 'MOON', confidence: 1 } as never }),
            nonNull,
          ],
          next_cursor: 'c',
        })
      );

      expect(await fetchAnalyses()).toEqual({
        success: true,
        data: { items: [good, nonNull], next_cursor: 'c' },
      });
    });

    it('returns an empty page when every row is invalid', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ items: [null, {}] }));

      expect(await fetchAnalyses()).toEqual({ success: true, data: { items: [] } });
    });

    it('reports an unreachable API', async () => {
      fetchMock.mockRejectedValue(new TypeError('fetch failed'));

      expect(await fetchAnalyses()).toEqual({
        success: false,
        error: analysesUnavailableMessage(),
      });
    });

    it('reports a missing BACKEND_API_URL as unavailable', async () => {
      vi.stubEnv('BACKEND_API_URL', '');

      expect(await fetchAnalyses()).toEqual({
        success: false,
        error: analysesUnavailableMessage(),
      });
      expect(fetchMock).not.toHaveBeenCalled();
    });

    it('treats an empty 200 body as a failed request', async () => {
      fetchMock.mockResolvedValue(new Response(null, { status: 200 }));

      expect(await fetchAnalyses()).toMatchObject({
        success: false,
        error: ANALYSES_REQUEST_FAILED_MESSAGE,
      });
    });

    it('reports a rejected key', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'bad key' }, 401));

      expect(await fetchAnalyses()).toEqual({
        success: false,
        error: analysesErrorMessage({ error: '', status: 401 }),
        status: 401,
      });
    });
  });

  describe('fetchAnalysis', () => {
    it('returns one analysis by id', async () => {
      const analysis = makeAnalysis({ id: 7 });
      fetchMock.mockResolvedValue(jsonResponse(analysis));

      expect(await fetchAnalysis(7)).toEqual({ success: true, data: analysis });
      expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/analyses/7');
    });

    it('maps 404 to a fixed message', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'row 7 missing' }, 404));

      expect(await fetchAnalysis(7)).toEqual({
        success: false,
        error: ANALYSIS_NOT_FOUND_MESSAGE,
        status: 404,
      });
    });

    it('refuses a malformed body', async () => {
      fetchMock.mockResolvedValue(jsonResponse({ id: 'x' }));

      expect(await fetchAnalysis(7)).toEqual({
        success: false,
        error: ANALYSES_REQUEST_FAILED_MESSAGE,
        status: 502,
      });
    });

    it('maps 401, 500 and an unreachable API to fixed messages', async () => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'k' }, 401));
      fetchMock.mockResolvedValueOnce(jsonResponse({ success: false, error: 'trace' }, 500));
      fetchMock.mockRejectedValueOnce(new TypeError('fetch failed'));

      expect(await fetchAnalysis(1)).toMatchObject({
        error: ANALYSES_UNAUTHORIZED_MESSAGE + ANALYSES_UNAUTHORIZED_HINT,
      });
      expect(await fetchAnalysis(1)).toMatchObject({ error: ANALYSES_REQUEST_FAILED_MESSAGE });
      expect(await fetchAnalysis(1)).toMatchObject({ error: analysesUnavailableMessage() });
    });
  });

  describe('analysesErrorMessage', () => {
    it('maps statuses to fixed messages with developer hints outside production', () => {
      vi.stubEnv('NODE_ENV', 'development');

      expect(analysesErrorMessage({ error: 'x' })).toBe(
        ANALYSES_UNAVAILABLE_MESSAGE + ANALYSES_UNAVAILABLE_HINT
      );
      expect(analysesErrorMessage({ error: 'x', status: 401 })).toBe(
        ANALYSES_UNAUTHORIZED_MESSAGE + ANALYSES_UNAUTHORIZED_HINT
      );
      expect(analysesErrorMessage({ error: 'x', status: 404 })).toBe(ANALYSIS_NOT_FOUND_MESSAGE);
      expect(analysesErrorMessage({ error: 'x', status: 422 })).toBe(
        ANALYSES_REQUEST_FAILED_MESSAGE
      );
    });

    it('leaves the developer hints out in production', () => {
      vi.stubEnv('NODE_ENV', 'production');

      expect(analysesErrorMessage({ error: 'x' })).toBe(ANALYSES_UNAVAILABLE_MESSAGE);
      expect(analysesErrorMessage({ error: 'x', status: 401 })).toBe(ANALYSES_UNAUTHORIZED_MESSAGE);
      expect(analysesUnavailableMessage()).not.toMatch(/uvicorn|BACKEND_INTERNAL_KEY/);
    });
  });
});
