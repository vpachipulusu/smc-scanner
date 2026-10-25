// @vitest-environment node
/** The backtest wrappers shape-check bodies, map 404 to "not run" and return fixed messages only. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  MAX_BADGE_REQUESTS,
  VERDICT_BACKOFF_MS,
  VERDICT_TTL_MS,
  clearVerdictCache,
  fetchBacktest,
  fetchBacktestVerdicts,
  fetchBacktests,
  fetchLatestBacktest,
  locationId,
  parseRetryAfter,
  startBacktest,
} from '@/lib/api/backtests';
import {
  MAX_BACKOFF_MS,
  retryDelayMs,
  BACKTEST_ALREADY_RUNNING_MESSAGE,
  BACKTEST_INVALID_MESSAGE,
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTEST_STRATEGY_STORE_UNAVAILABLE_MESSAGE,
  BACKTEST_TOO_LARGE_MESSAGE,
  BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
  BACKTESTS_REQUEST_FAILED_MESSAGE,
  BACKTESTS_STORE_UNAVAILABLE_MESSAGE,
  BACKTESTS_UNAVAILABLE_MESSAGE,
} from '@/lib/api/backtests-messages';
import { makeBacktest, makeListItem, makeSummary } from '../../helpers/backtest-fixtures';

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const apiError = (error: string, status: number, headers: Record<string, string> = {}) =>
  jsonResponse({ success: false, error }, status, headers);

const fetchMock = vi.fn<(request: Request) => Promise<Response>>();
const lastUrl = () => new URL(fetchMock.mock.calls[fetchMock.mock.calls.length - 1][0].url);

beforeEach(() => {
  vi.stubEnv('BACKEND_API_URL', 'http://backend.test');
  vi.stubGlobal('fetch', fetchMock);
  clearVerdictCache();
});

afterEach(() => {
  vi.unstubAllEnvs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  fetchMock.mockReset();
});

describe('fetchBacktests', () => {
  it('lists one strategy newest first with a clamped limit', async () => {
    const items = [makeListItem({ id: 9, status: 'running', verdict: null }), makeListItem()];
    fetchMock.mockResolvedValue(jsonResponse({ items }));

    expect(await fetchBacktests('my-one', 999)).toEqual({ success: true, data: items });
    expect(lastUrl().pathname).toBe('/backtests');
    expect(lastUrl().searchParams.get('strategy')).toBe('my-one');
    expect(lastUrl().searchParams.get('limit')).toBe('200');
  });

  it('lists every strategy without a filter', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    await fetchBacktests(undefined, 0);
    expect(lastUrl().searchParams.has('strategy')).toBe(false);
    expect(lastUrl().searchParams.get('limit')).toBe('1');
    await fetchBacktests(undefined, Number.NaN);
    expect(lastUrl().searchParams.get('limit')).toBe('50');
  });

  it('answers an impossible slug with no runs and no request', async () => {
    expect(await fetchBacktests('Bad Slug')).toEqual({ success: true, data: [] });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('fails on contract drift instead of hiding a run', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeListItem(), { id: 1 }] }));
    expect(await fetchBacktests('my-one')).toEqual({
      success: false,
      error: BACKTESTS_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [makeListItem({ status: 'queued' as never })] })
    );
    expect((await fetchBacktests('my-one')).success).toBe(false);
    fetchMock.mockResolvedValue(jsonResponse([]));
    expect((await fetchBacktests('my-one')).success).toBe(false);
  });

  it('maps a 429 with Retry-After and keeps the seconds', async () => {
    fetchMock.mockResolvedValue(
      apiError('Too many requests; try again shortly', 429, { 'Retry-After': '12' })
    );
    expect(await fetchBacktests('my-one')).toEqual({
      success: false,
      error: 'Too many backtest requests. Try again in 12 seconds.',
      status: 429,
      retryAfter: 12,
    });
  });

  it('maps a 503 and an unreachable API to fixed messages', async () => {
    fetchMock.mockResolvedValue(apiError('Backtest database unavailable', 503));
    expect(await fetchBacktests('my-one')).toMatchObject({
      error: BACKTESTS_STORE_UNAVAILABLE_MESSAGE,
      status: 503,
    });
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchBacktests('my-one')).toEqual({
      success: false,
      error: BACKTESTS_UNAVAILABLE_MESSAGE,
    });
  });
});

describe('fetchBacktest', () => {
  it('returns a checked run', async () => {
    const run = makeBacktest();
    fetchMock.mockResolvedValue(jsonResponse(run));
    expect(await fetchBacktest(7)).toEqual({ success: true, data: run });
    expect(lastUrl().pathname).toBe('/backtests/7');
  });

  it('accepts a pending run without results or rules', async () => {
    const run = makeBacktest({ status: 'pending', verdict: null, results: null, rules: null });
    fetchMock.mockResolvedValue(jsonResponse(run));
    expect((await fetchBacktest(7)).success).toBe(true);
  });

  it('rejects a run whose stats do not fit the schema', async () => {
    const run = makeBacktest();
    fetchMock.mockResolvedValue(
      jsonResponse({ ...run, results: { ...run.results, out_of_sample: { n: 'x' } } })
    );
    expect(await fetchBacktest(7)).toMatchObject({ status: 502 });
    fetchMock.mockResolvedValue(jsonResponse({ ...run, results: { baselines: { random: 1 } } }));
    expect(await fetchBacktest(7)).toMatchObject({ status: 502 });
    fetchMock.mockResolvedValue(jsonResponse({ ...run, rules: { rr: 2 } }));
    expect(await fetchBacktest(7)).toMatchObject({ status: 502 });
  });

  it('maps a 404 and never asks for an impossible id', async () => {
    fetchMock.mockResolvedValue(apiError('Backtest not found', 404));
    expect(await fetchBacktest(8)).toMatchObject({
      error: BACKTEST_NOT_FOUND_MESSAGE,
      status: 404,
    });
    fetchMock.mockClear();
    expect(await fetchBacktest(0)).toMatchObject({ status: 404 });
    expect(await fetchBacktest(1.5)).toMatchObject({ status: 404 });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('fetchLatestBacktest', () => {
  it('returns the badge of the latest finished run', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeSummary()));
    expect(await fetchLatestBacktest('my-one')).toEqual({ success: true, data: makeSummary() });
    expect(lastUrl().pathname).toBe('/strategies/my-one/backtest');
  });

  it('maps the 404 to null, not an error', async () => {
    fetchMock.mockResolvedValue(apiError('No finished backtest for this strategy', 404));
    expect(await fetchLatestBacktest('never-run')).toEqual({ success: true, data: null });
  });

  it('maps a 429 with Retry-After and rejects a malformed badge', async () => {
    fetchMock.mockResolvedValue(apiError('slow down', 429, { 'Retry-After': '3' }));
    expect(await fetchLatestBacktest('slow-one')).toMatchObject({
      error: 'Too many backtest requests. Try again in 3 seconds.',
      retryAfter: 3,
    });
    fetchMock.mockResolvedValue(jsonResponse(makeSummary({ verdict: 'maybe' as never })));
    expect(await fetchLatestBacktest('odd-one')).toMatchObject({ status: 502 });
  });

  it('treats an impossible slug as not run without a request', async () => {
    expect(await fetchLatestBacktest('NOPE')).toEqual({ success: true, data: null });
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe('fetchBacktestVerdicts', () => {
  it('maps each slug and leaves out the ones whose read failed', async () => {
    fetchMock.mockImplementation(async (request) => {
      const path = new URL(request.url).pathname;
      if (path.includes('/v-pass/')) return jsonResponse(makeSummary({ strategy: 'v-pass' }));
      if (path.includes('/v-fail/')) {
        return jsonResponse(makeSummary({ strategy: 'v-fail', verdict: 'fail' }));
      }
      if (path.includes('/v-none/')) return apiError('No finished backtest', 404);
      return apiError('Backtest database unavailable', 503);
    });

    expect(await fetchBacktestVerdicts(['v-pass', 'v-fail', 'v-none', 'v-down', 'v-pass'])).toEqual(
      { 'v-pass': 'survived', 'v-fail': 'failed', 'v-none': 'not-run' }
    );
  });

  it('caps the number of reads', async () => {
    fetchMock.mockImplementation(async () => apiError('none', 404));
    const slugs = Array.from({ length: MAX_BADGE_REQUESTS + 5 }, (_, i) => `cap-${i}`);
    const verdicts = await fetchBacktestVerdicts(slugs);
    expect(Object.keys(verdicts)).toHaveLength(MAX_BADGE_REQUESTS);
  });

  it('reuses a verdict for a minute across requests', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(1_000_000);
    fetchMock.mockImplementation(async () => jsonResponse(makeSummary({ strategy: 'ttl-one' })));
    expect(await fetchBacktestVerdicts(['ttl-one'])).toEqual({ 'ttl-one': 'survived' });
    expect(await fetchBacktestVerdicts(['ttl-one'])).toEqual({ 'ttl-one': 'survived' });
    expect(fetchMock).toHaveBeenCalledTimes(1);

    now.mockReturnValue(1_000_000 + VERDICT_TTL_MS + 1);
    await fetchBacktestVerdicts(['ttl-one']);
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('reads a badge afresh once a run of that strategy is done', async () => {
    fetchMock.mockImplementation(async () => jsonResponse(makeSummary({ strategy: 'my-one' })));
    await fetchBacktestVerdicts(['my-one']);
    fetchMock.mockImplementation(async () => jsonResponse(makeBacktest()));
    await fetchBacktest(7);
    fetchMock.mockImplementation(async () =>
      jsonResponse(makeSummary({ strategy: 'my-one', verdict: 'fail' }))
    );
    expect(await fetchBacktestVerdicts(['my-one'])).toEqual({ 'my-one': 'failed' });
  });

  it('backs off after a 429 for its Retry-After, and after a 503 for the default', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(5_000_000);
    fetchMock.mockImplementation(async () => apiError('slow', 429, { 'Retry-After': '90' }));
    expect(await fetchBacktestVerdicts(['bo-one'])).toEqual({});
    fetchMock.mockClear();

    now.mockReturnValue(5_000_000 + 60_000);
    expect(await fetchBacktestVerdicts(['bo-two'])).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();

    now.mockReturnValue(5_000_000 + 91_000);
    fetchMock.mockImplementation(async () => apiError('Backtest database unavailable', 503));
    await fetchBacktestVerdicts(['bo-two']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockClear();
    now.mockReturnValue(5_000_000 + 91_000 + VERDICT_BACKOFF_MS - 1);
    await fetchBacktestVerdicts(['bo-three']);
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('caps a huge Retry-After at five minutes and treats 0 as the default', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(9_000_000);
    fetchMock.mockImplementation(async () => apiError('slow', 429, { 'Retry-After': '999999' }));
    await fetchBacktestVerdicts(['cap-one']);
    fetchMock.mockClear();
    now.mockReturnValue(9_000_000 + MAX_BACKOFF_MS - 1);
    await fetchBacktestVerdicts(['cap-one']);
    expect(fetchMock).not.toHaveBeenCalled();

    now.mockReturnValue(9_000_000 + MAX_BACKOFF_MS);
    fetchMock.mockImplementation(async () => apiError('slow', 429, { 'Retry-After': '0' }));
    await fetchBacktestVerdicts(['cap-one']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    fetchMock.mockClear();
    now.mockReturnValue(9_000_000 + MAX_BACKOFF_MS + VERDICT_BACKOFF_MS - 1);
    await fetchBacktestVerdicts(['cap-one']);
    expect(fetchMock).not.toHaveBeenCalled();
    now.mockReturnValue(9_000_000 + MAX_BACKOFF_MS + VERDICT_BACKOFF_MS);
    await fetchBacktestVerdicts(['cap-one']);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it('backs off after a 401 (the key was refused)', async () => {
    const now = vi.spyOn(Date, 'now').mockReturnValue(2_000_000);
    fetchMock.mockImplementation(async () => apiError('Unauthorized', 401));
    expect(await fetchBacktestVerdicts(['key-one'])).toEqual({});
    fetchMock.mockClear();
    now.mockReturnValue(2_000_000 + VERDICT_BACKOFF_MS - 1);
    expect(await fetchBacktestVerdicts(['key-two'])).toEqual({});
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('never caches "not run", so an unknown slug cannot fill the cache', async () => {
    fetchMock.mockImplementation(async () => apiError('No finished backtest', 404));
    expect(await fetchBacktestVerdicts(['no-runs'])).toEqual({ 'no-runs': 'not-run' });
    expect(await fetchBacktestVerdicts(['no-runs'])).toEqual({ 'no-runs': 'not-run' });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it('does not re-cache a verdict read while a run of that strategy finished', async () => {
    let answer: (response: Response) => void = () => {};
    fetchMock.mockImplementationOnce(() => new Promise((done) => (answer = done)));
    const reading = fetchBacktestVerdicts(['my-one']);
    await vi.waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));

    fetchMock.mockImplementationOnce(async () => jsonResponse(makeBacktest()));
    await fetchBacktest(7);
    answer(jsonResponse(makeSummary({ strategy: 'my-one' })));
    expect(await reading).toEqual({ 'my-one': 'survived' });

    fetchMock.mockImplementation(async () =>
      jsonResponse(makeSummary({ strategy: 'my-one', verdict: 'fail' }))
    );
    expect(await fetchBacktestVerdicts(['my-one'])).toEqual({ 'my-one': 'failed' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
  });

  it('applies the read cap to cache misses only', async () => {
    fetchMock.mockImplementation(async (request) => {
      const slug = new URL(request.url).pathname.split('/')[2];
      return jsonResponse(makeSummary({ strategy: slug }));
    });
    await fetchBacktestVerdicts(['hit-a', 'hit-b']);
    fetchMock.mockClear();
    const misses = Array.from({ length: MAX_BADGE_REQUESTS }, (_, i) => `miss-${i}`);
    const verdicts = await fetchBacktestVerdicts(['hit-a', 'hit-b', ...misses]);
    expect(fetchMock).toHaveBeenCalledTimes(MAX_BADGE_REQUESTS);
    expect(Object.keys(verdicts)).toHaveLength(MAX_BADGE_REQUESTS + 2);
  });
});

describe('Retry-After', () => {
  it.each([
    ['30', 30],
    ['999999', 999999],
    ['0', undefined],
    ['abc', undefined],
    ['1.5', undefined],
    ['-1', undefined],
    ['Wed, 21 Oct 2026 07:28:00 GMT', undefined],
    [null, undefined],
  ])('parses %s as %s', (header, seconds) => {
    expect(parseRetryAfter(header)).toBe(seconds);
  });

  it('turns it into a wait capped at five minutes, with a fallback', () => {
    expect(retryDelayMs(20, 5000)).toBe(20_000);
    expect(retryDelayMs(999999, 5000)).toBe(MAX_BACKOFF_MS);
    expect(retryDelayMs(0, 5000)).toBe(5000);
    expect(retryDelayMs(1.5, 5000)).toBe(5000);
    expect(retryDelayMs(undefined, 30_000)).toBe(30_000);
  });
});

describe('startBacktest', () => {
  const body = { strategy: 'my-one', source: 'demo' as const, bars: 500 };

  it('returns the pending row with the id from Location', async () => {
    const pending = makeBacktest({ id: 3, status: 'pending', verdict: null, results: null });
    fetchMock.mockResolvedValue(jsonResponse(pending, 202, { Location: '/backtests/11' }));

    expect(await startBacktest(body)).toEqual({
      success: true,
      data: { id: 11, backtest: pending },
    });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('POST');
    expect(await request.json()).toEqual(body);
  });

  it('falls back to the body id without a usable Location', async () => {
    const pending = makeBacktest({ id: 3, status: 'pending', verdict: null, results: null });
    fetchMock.mockResolvedValue(jsonResponse(pending, 202, { Location: '/elsewhere' }));
    expect(await startBacktest(body)).toMatchObject({ data: { id: 3 } });
    fetchMock.mockResolvedValue(jsonResponse({ id: 3 }, 202));
    expect(await startBacktest(body)).toMatchObject({ status: 502 });
  });

  it('still reports a queued run when only its Location is readable', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 'x' }, 202, { Location: '/backtests/14' }));
    expect(await startBacktest(body)).toEqual({
      success: true,
      data: { id: 14, backtest: null },
    });
  });

  it.each([
    [409, 'Backtest already running', BACKTEST_ALREADY_RUNNING_MESSAGE],
    [422, 'Unknown strategy', BACKTEST_UNKNOWN_STRATEGY_MESSAGE],
    [
      422,
      'Backtest too large; use fewer symbols or bars, or a larger stride',
      BACKTEST_TOO_LARGE_MESSAGE,
    ],
    [422, 'Invalid request', BACKTEST_INVALID_MESSAGE],
    [503, 'Strategy database unavailable', BACKTEST_STRATEGY_STORE_UNAVAILABLE_MESSAGE],
    [503, 'Backtest database unavailable', BACKTESTS_STORE_UNAVAILABLE_MESSAGE],
  ])('maps %i "%s" to a fixed message', async (status, reason, message) => {
    fetchMock.mockResolvedValue(apiError(reason, status));
    expect(await startBacktest(body)).toEqual({ success: false, error: message, status });
  });

  it('maps a 429 with its Retry-After', async () => {
    fetchMock.mockResolvedValue(apiError('Rate limit exceeded', 429, { 'Retry-After': '7' }));
    expect(await startBacktest(body)).toEqual({
      success: false,
      error: 'Too many backtest requests. Try again in 7 seconds.',
      status: 429,
      retryAfter: 7,
    });
  });
});

describe('locationId', () => {
  it('reads only /backtests/{positive id}', () => {
    expect(locationId('/backtests/42')).toBe(42);
    expect(locationId('http://x/backtests/5')).toBe(5);
    expect(locationId('/backtests/0')).toBeNull();
    expect(locationId('/backtests/abc')).toBeNull();
    expect(locationId(null)).toBeNull();
    expect(locationId('/backtests/5?x=1')).toBeNull();
    expect(locationId('/backtests/5/')).toBeNull();
    expect(locationId(`/backtests/${'1'.repeat(16)}`)).toBeNull();
    expect(locationId('/backtests/007')).toBe(7);
  });
});
