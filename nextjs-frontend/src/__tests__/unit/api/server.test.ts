// @vitest-environment node
/** callBackend: base URL and internal key from the environment, every outcome in the envelope. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { health } from '@/lib/api/generated';
import {
  BACKEND_ERROR_MESSAGE,
  BACKEND_UNAVAILABLE_MESSAGE,
  INTERNAL_KEY_HEADER,
  callBackend,
} from '@/lib/api/server';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('callBackend', () => {
  const fetchMock = vi.fn<(request: Request) => Promise<Response>>();

  beforeEach(() => {
    vi.stubEnv('BACKEND_API_URL', 'http://backend.test/');
    vi.stubEnv('BACKEND_INTERNAL_KEY', '');
    vi.stubGlobal('fetch', fetchMock);
  });

  afterEach(() => {
    vi.unstubAllEnvs();
    vi.unstubAllGlobals();
    fetchMock.mockReset();
  });

  it('calls the API under BACKEND_API_URL and returns the body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok', version: '0.1.0' }));

    const result = await callBackend((client) => health({ client }));

    expect(result).toEqual({ success: true, data: { status: 'ok', version: '0.1.0' } });
    const request = fetchMock.mock.calls[0][0];
    expect(request.url).toBe('http://backend.test/health');
    expect(request.headers.get(INTERNAL_KEY_HEADER)).toBeNull();
  });

  it('sends the internal key when BACKEND_INTERNAL_KEY is set', async () => {
    vi.stubEnv('BACKEND_INTERNAL_KEY', 'server-key');
    fetchMock.mockResolvedValue(jsonResponse({ status: 'ok', version: '0.1.0' }));

    await callBackend((client) => health({ client }));

    expect(fetchMock.mock.calls[0][0].headers.get(INTERNAL_KEY_HEADER)).toBe('server-key');
  });

  it('is unavailable without BACKEND_API_URL and never calls fetch', async () => {
    vi.stubEnv('BACKEND_API_URL', '');

    expect(await callBackend((client) => health({ client }))).toEqual({
      success: false,
      error: BACKEND_UNAVAILABLE_MESSAGE,
    });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('is unavailable when the fetch itself fails', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));

    expect(await callBackend((client) => health({ client }))).toEqual({
      success: false,
      error: BACKEND_UNAVAILABLE_MESSAGE,
    });
  });

  it('passes the envelope error and status through', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'Unauthorized' }, 401));

    expect(await callBackend((client) => health({ client }))).toEqual({
      success: false,
      error: 'Unauthorized',
      status: 401,
    });
  });

  it('uses a fixed message for an error body that is not the envelope', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ detail: 'boom' }, 500));

    expect(await callBackend((client) => health({ client }))).toEqual({
      success: false,
      error: BACKEND_ERROR_MESSAGE,
      status: 500,
    });
  });
});
