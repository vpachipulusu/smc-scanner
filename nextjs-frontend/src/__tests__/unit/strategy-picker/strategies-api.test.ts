// @vitest-environment node
/** The strategies read wrapper checks the list shape and only ever returns fixed messages. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchStrategies } from '@/lib/api/strategies';
import {
  STRATEGIES_RATE_LIMITED_FALLBACK_MESSAGE,
  STRATEGIES_REQUEST_FAILED_MESSAGE,
  STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
  STRATEGIES_UNAUTHORIZED_MESSAGE,
  STRATEGIES_UNAVAILABLE_MESSAGE,
  strategiesErrorMessage,
  strategiesRateLimitedMessage,
} from '@/lib/api/strategies-messages';
import { makeStrategy } from '../../helpers/strategy-fixtures';

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

describe('fetchStrategies', () => {
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

  it('returns the list in the API order', async () => {
    const items = [makeStrategy(), makeStrategy({ slug: 'my-one', name: 'Mine', builtin: false })];
    fetchMock.mockResolvedValue(jsonResponse({ items }));

    const result = await fetchStrategies();

    expect(result).toEqual({ success: true, data: items });
    const request = fetchMock.mock.calls[0][0];
    expect(new URL(request.url).pathname).toBe('/strategies');
    expect(request.method).toBe('GET');
  });

  it('fails on contract drift instead of hiding a strategy', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeStrategy(), { slug: 'x' }] }));
    expect(await fetchStrategies()).toEqual({
      success: false,
      error: STRATEGIES_REQUEST_FAILED_MESSAGE,
      status: 502,
    });

    fetchMock.mockResolvedValue(jsonResponse({ items: [makeStrategy({ slug: 'Bad Slug' })] }));
    expect((await fetchStrategies()).success).toBe(false);

    fetchMock.mockResolvedValue(jsonResponse({ nope: true }));
    expect((await fetchStrategies()).success).toBe(false);
  });

  it('maps a 429 with Retry-After to the cooldown message', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'slow down' }, 429, { 'Retry-After': '7' })
    );

    expect(await fetchStrategies()).toEqual({
      success: false,
      error: 'Too many strategy requests. Try again in 7 seconds.',
      status: 429,
    });
  });

  it('never passes the backend text on', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Strategy database unavailable' }, 503)
    );

    expect(await fetchStrategies()).toEqual({
      success: false,
      error: STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
      status: 503,
    });
  });

  it('reports an unconfigured API as unreachable', async () => {
    vi.stubEnv('BACKEND_API_URL', '');
    expect(await fetchStrategies()).toEqual({
      success: false,
      error: STRATEGIES_UNAVAILABLE_MESSAGE,
      status: undefined,
    });
  });
});

describe('strategiesErrorMessage', () => {
  it('maps each status to a fixed message', () => {
    expect(strategiesErrorMessage({})).toBe(STRATEGIES_UNAVAILABLE_MESSAGE);
    expect(strategiesErrorMessage({ status: 401 })).toBe(STRATEGIES_UNAUTHORIZED_MESSAGE);
    expect(strategiesErrorMessage({ status: 503 })).toBe(STRATEGIES_STORE_UNAVAILABLE_MESSAGE);
    expect(strategiesErrorMessage({ status: 500 })).toBe(STRATEGIES_REQUEST_FAILED_MESSAGE);
    expect(strategiesErrorMessage({ status: 429 })).toBe(STRATEGIES_RATE_LIMITED_FALLBACK_MESSAGE);
  });

  it('only trusts a sane Retry-After', () => {
    expect(strategiesRateLimitedMessage(1)).toBe(
      'Too many strategy requests. Try again in 1 second.'
    );
    for (const bad of [0, 1.5, 86_401, undefined]) {
      expect(strategiesRateLimitedMessage(bad)).toBe(STRATEGIES_RATE_LIMITED_FALLBACK_MESSAGE);
    }
  });
});
