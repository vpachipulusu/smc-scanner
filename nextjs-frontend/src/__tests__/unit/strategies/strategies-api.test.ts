// @vitest-environment node
/** The strategy wrappers map calls to the API, check body shapes and never expose backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import {
  addStrategy,
  editStrategy,
  fetchConditionCatalogue,
  fetchStrategies,
  fetchStrategy,
  removeStrategy,
} from '@/lib/api/strategies-write';
import {
  CONDITIONS_UNAVAILABLE_MESSAGE,
  STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE,
  STRATEGIES_REQUEST_FAILED_MESSAGE,
  STRATEGIES_STORE_UNAVAILABLE_MESSAGE,
  STRATEGIES_UNAUTHORIZED_MESSAGE,
  STRATEGIES_UNAVAILABLE_MESSAGE,
  STRATEGY_BUILTIN_MESSAGE,
  STRATEGY_CONFLICT_MESSAGE,
  STRATEGY_INVALID_MESSAGE,
  STRATEGY_LIMIT_MESSAGE,
  STRATEGY_NOT_FOUND_MESSAGE,
  STRATEGY_SLUG_TAKEN_MESSAGE,
  strategyErrorMessage,
  strategyRateLimitMessage,
} from '@/lib/api/strategies-write-messages';
import { BUILTIN, RAW_CONDITIONS, makeStrategy } from '../../helpers/strategy-fixtures';

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const apiError = (status: number, error: string, headers: Record<string, string> = {}) =>
  jsonResponse({ success: false, error }, status, headers);

const { slug: _slug, builtin: _builtin, ...UPDATE } = makeStrategy();

describe('strategies wrapper', () => {
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

  const request = (index = 0) => fetchMock.mock.calls[index][0];

  it('lists strategies', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [BUILTIN, makeStrategy()] }));

    const result = await fetchStrategies();

    expect(result.success && result.data.map((s) => s.slug)).toEqual(['smc-default', 'my-setup']);
    expect(new URL(request().url).pathname).toBe('/strategies');
  });

  it.each([
    ['no items', {}],
    ['a bad item', { items: [makeStrategy(), { slug: 'x' }] }],
    ['a bad slug', { items: [makeStrategy({ slug: 'Bad Slug' })] }],
    ['a bad zone kind', { items: [makeStrategy({ zone_kinds: ['XX' as 'OB'] })] }],
    [
      'a bad param',
      {
        items: [makeStrategy({ require: [{ key: 'a', params: { x: [] as unknown as number } }] })],
      },
    ],
  ])('treats a list with %s as a failure', async (_label, body) => {
    fetchMock.mockResolvedValue(jsonResponse(body));

    expect(await fetchStrategies()).toEqual({
      success: false,
      error: STRATEGIES_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });

  it('reads one strategy by slug', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeStrategy()));

    const result = await fetchStrategy('my-setup');

    expect(result.success && result.data.name).toBe('My setup');
    expect(new URL(request().url).pathname).toBe('/strategies/my-setup');
  });

  it('never calls the API with a slug that cannot exist', async () => {
    for (const call of [
      () => fetchStrategy('../x'),
      () => editStrategy('A', UPDATE),
      () => removeStrategy('a/b'),
    ]) {
      expect(await call()).toEqual({
        success: false,
        error: STRATEGY_NOT_FOUND_MESSAGE,
        status: 404,
      });
    }
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('creates a strategy with a POST', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeStrategy(), 201));

    const result = await addStrategy({ ...UPDATE, slug: 'my-setup' });

    expect(result.success).toBe(true);
    expect(request().method).toBe('POST');
    expect(await request().json()).toMatchObject({ slug: 'my-setup', name: 'My setup' });
  });

  it('updates with a PUT to the slug', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeStrategy()));

    const result = await editStrategy('my-setup', UPDATE);

    expect(result.success).toBe(true);
    expect(request().method).toBe('PUT');
    expect(new URL(request().url).pathname).toBe('/strategies/my-setup');
  });

  it('deletes with a DELETE and an empty 204', async () => {
    fetchMock.mockResolvedValue(new Response(null, { status: 204 }));

    expect(await removeStrategy('my-setup')).toEqual({ success: true, data: null });
    expect(request().method).toBe('DELETE');
  });

  it('rejects a bad single-strategy body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ slug: 'x' }));
    expect((await fetchStrategy('x')).success).toBe(false);
    fetchMock.mockResolvedValue(jsonResponse({ slug: 'x' }, 201));
    expect((await addStrategy({ ...UPDATE, slug: 'x' })).success).toBe(false);
    fetchMock.mockResolvedValue(jsonResponse({ slug: 'x' }));
    expect((await editStrategy('x', UPDATE)).success).toBe(false);
  });

  it.each([
    [409, 'A strategy with this slug already exists', STRATEGY_SLUG_TAKEN_MESSAGE],
    [409, 'Strategy limit reached', STRATEGY_LIMIT_MESSAGE],
    [409, 'Built-in strategies cannot be changed', STRATEGY_BUILTIN_MESSAGE],
    [409, 'something new', STRATEGY_CONFLICT_MESSAGE],
    [422, 'Invalid strategy', STRATEGY_INVALID_MESSAGE],
    [503, 'Strategy database unavailable', STRATEGIES_STORE_UNAVAILABLE_MESSAGE],
    [401, 'Unauthorized', STRATEGIES_UNAUTHORIZED_MESSAGE],
  ])('maps a %i "%s" to a fixed message', async (status, error, message) => {
    fetchMock.mockResolvedValue(apiError(status, error));

    const result = await addStrategy({ ...UPDATE, slug: 'my-setup' });

    expect(result).toEqual({ success: false, error: message, status });
  });

  it('maps a 409 on a built-in edit and delete', async () => {
    fetchMock.mockResolvedValue(apiError(409, 'Built-in strategies cannot be changed'));
    expect(await editStrategy('smc-default', UPDATE)).toMatchObject({
      error: STRATEGY_BUILTIN_MESSAGE,
    });
    fetchMock.mockResolvedValue(apiError(409, 'Built-in strategies cannot be changed'));
    expect(await removeStrategy('smc-default')).toMatchObject({ error: STRATEGY_BUILTIN_MESSAGE });
  });

  it('carries Retry-After into the 429 message', async () => {
    fetchMock.mockResolvedValue(apiError(429, 'Too many requests', { 'Retry-After': '12' }));

    expect(await fetchStrategies()).toMatchObject({
      error: 'Too many strategy requests. Try again in 12 seconds.',
      status: 429,
    });
  });

  it('reports a 404 and an unreachable API', async () => {
    fetchMock.mockResolvedValue(apiError(404, 'Strategy not found'));
    expect(await fetchStrategy('gone')).toMatchObject({
      error: STRATEGY_NOT_FOUND_MESSAGE,
      status: 404,
    });
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchStrategies()).toEqual({
      success: false,
      error: STRATEGIES_UNAVAILABLE_MESSAGE,
    });
  });

  it('reads the condition catalogue from /config', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ sources: [], conditions: RAW_CONDITIONS }));

    const result = await fetchConditionCatalogue();

    expect(new URL(request().url).pathname).toBe('/config');
    expect(result.success && result.data.map((info) => info.key)).toEqual(
      RAW_CONDITIONS.map((raw) => raw.key)
    );
    expect(result.success && result.data[3].params[0]).toMatchObject({
      name: 'bars',
      kind: 'integer',
      max: 5000,
    });
  });

  it.each([
    ['no conditions', {}],
    ['a bad condition', { conditions: [...RAW_CONDITIONS, { key: 'x' }] }],
    ['a duplicate key', { conditions: [RAW_CONDITIONS[0], RAW_CONDITIONS[0]] }],
  ])('fails the catalogue with %s', async (_label, body) => {
    fetchMock.mockResolvedValue(jsonResponse(body));

    expect(await fetchConditionCatalogue()).toMatchObject({
      success: false,
      error: CONDITIONS_UNAVAILABLE_MESSAGE,
    });
  });

  it('fails the catalogue when /config fails', async () => {
    fetchMock.mockResolvedValue(apiError(503, 'down'));

    expect(await fetchConditionCatalogue()).toEqual({
      success: false,
      error: CONDITIONS_UNAVAILABLE_MESSAGE,
      status: 503,
    });
  });
});

describe('strategy messages', () => {
  it('words the rate limit', () => {
    expect(strategyRateLimitMessage(1)).toBe('Too many strategy requests. Try again in 1 second.');
    expect(strategyRateLimitMessage()).toBe(STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(strategyRateLimitMessage(0)).toBe(STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(strategyRateLimitMessage(1.5)).toBe(STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE);
    expect(strategyRateLimitMessage(100_000)).toBe(STRATEGIES_RATE_LIMIT_FALLBACK_MESSAGE);
  });

  it('falls back for unknown statuses and never echoes the reason', () => {
    expect(strategyErrorMessage({ status: 500, reason: 'secret' })).toBe(
      STRATEGIES_REQUEST_FAILED_MESSAGE
    );
    expect(strategyErrorMessage({ status: 409 })).toBe(STRATEGY_CONFLICT_MESSAGE);
    expect(strategyErrorMessage({ status: 409, reason: 'toString' })).toBe(
      STRATEGY_CONFLICT_MESSAGE
    );
  });
});
