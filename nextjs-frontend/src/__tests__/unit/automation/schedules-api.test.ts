// @vitest-environment node
/** The schedules wrapper maps calls to the API, checks body shapes and never exposes backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  addSchedule,
  editSchedule,
  fetchScheduleLogs,
  fetchSchedules,
  removeSchedule,
  runSchedule,
} from '@/lib/api/schedules';
import {
  SCHEDULE_BUSY_MESSAGE,
  SCHEDULE_COOLDOWN_FALLBACK_MESSAGE,
  SCHEDULE_INVALID_MESSAGE,
  SCHEDULE_NOT_FOUND_MESSAGE,
  SCHEDULES_REQUEST_FAILED_MESSAGE,
  SCHEDULES_STORE_UNAVAILABLE_MESSAGE,
  SCHEDULES_UNAUTHORIZED_MESSAGE,
  SCHEDULES_UNAVAILABLE_MESSAGE,
  scheduleCooldownMessage,
  scheduleErrorMessage,
} from '@/lib/api/schedules-messages';
import { makeLog, makeRun, makeSchedule } from '../../helpers/automation-fixtures';

const jsonResponse = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', ...headers },
  });

const CREATE_BODY = {
  name: 'n',
  source: 'demo' as const,
  tf: '1h' as const,
  symbols: ['EURUSD'],
  frequency: '1h' as const,
};

describe('schedules wrapper', () => {
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

  it('lists schedules', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeSchedule(), makeSchedule({ id: 2 })] }));

    const result = await fetchSchedules();

    expect(result.success && result.data.map((s) => s.id)).toEqual([1, 2]);
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/schedules');
  });

  it('fails when any schedule or log row is invalid instead of hiding it', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeSchedule(), { id: 'bad' }] }));
    expect((await fetchSchedules()).success).toBe(false);
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeLog(), { id: 1 }] }));
    expect((await fetchScheduleLogs(1)).success).toBe(false);
  });

  it('fails on a body that is not a list', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ nope: true }));
    expect(await fetchSchedules()).toEqual({
      success: false,
      error: SCHEDULES_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });

  it('creates and updates with the body and path', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeSchedule({ id: 5 }), 200));
    expect(await addSchedule(CREATE_BODY)).toEqual({
      success: true,
      data: makeSchedule({ id: 5 }),
    });
    const create = fetchMock.mock.calls[0][0];
    expect(create.method).toBe('POST');
    expect(await create.json()).toEqual(CREATE_BODY);

    fetchMock.mockResolvedValue(jsonResponse(makeSchedule({ id: 5, enabled: false })));
    const updated = await editSchedule(5, { enabled: false });
    expect(updated.success && updated.data.enabled).toBe(false);
    const patch = fetchMock.mock.calls[1][0];
    expect(patch.method).toBe('PATCH');
    expect(new URL(patch.url).pathname).toBe('/schedules/5');
  });

  it('rejects a created schedule with a malformed body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    const result = await addSchedule(CREATE_BODY);
    expect(!result.success && result.error).toBe(SCHEDULES_REQUEST_FAILED_MESSAGE);
    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    const edited = await editSchedule(1, { name: 'x' });
    expect(!edited.success && edited.error).toBe(SCHEDULES_REQUEST_FAILED_MESSAGE);
  });

  it('deletes a schedule', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ ok: true }));
    expect(await removeSchedule(3)).toEqual({ success: true, data: null });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('DELETE');
    expect(new URL(request.url).pathname).toBe('/schedules/3');
  });

  it('runs a schedule and returns the run summary', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeRun()));
    expect(await runSchedule(1)).toEqual({ success: true, data: makeRun() });
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/schedules/1/run');
  });

  it('rejects a run with a malformed body', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ status: 'weird' }));
    const result = await runSchedule(1);
    expect(!result.success && result.status).toBe(502);
  });

  it('maps 409 to the busy message', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'raw backend text' }, 409));
    expect(await runSchedule(1)).toEqual({
      success: false,
      error: SCHEDULE_BUSY_MESSAGE,
      status: 409,
    });
  });

  it('maps 429 to the cooldown message using Retry-After', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'raw' }, 429, { 'Retry-After': '42' })
    );
    const result = await runSchedule(1);
    expect(!result.success && result.error).toBe(scheduleCooldownMessage(42));
    expect(!result.success && result.error).toContain('42 seconds');
  });

  it('falls back when Retry-After is missing or not whole seconds', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'raw' }, 429));
    expect((await runSchedule(1)).success).toBe(false);
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'raw' }, 429, { 'Retry-After': 'Wed, 21 Oct 2026' })
    );
    const result = await runSchedule(1);
    expect(!result.success && result.error).toBe(SCHEDULE_COOLDOWN_FALLBACK_MESSAGE);
  });

  it('lists logs with the cursor and exposes next_cursor', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeLog()], next_cursor: 'abc' }));

    const result = await fetchScheduleLogs(1, { limit: 50, cursor: 'zzz' });

    expect(result).toEqual({ success: true, data: { items: [makeLog()], next_cursor: 'abc' } });
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/schedules/1/logs');
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '50', cursor: 'zzz' });
  });

  it('returns a null next_cursor for the last page and fails on a bad page', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    const result = await fetchScheduleLogs(1);
    expect(result.success && result.data.next_cursor).toBeNull();
    fetchMock.mockResolvedValue(jsonResponse([]));
    expect((await fetchScheduleLogs(1)).success).toBe(false);
  });

  it('never passes the backend error text on', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Traceback: secret detail' }, 500)
    );
    const result = await fetchSchedules();
    expect(result).toEqual({
      success: false,
      error: SCHEDULES_REQUEST_FAILED_MESSAGE,
      status: 500,
    });
  });

  it('reports an unreachable API without a status', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchSchedules()).toMatchObject({
      success: false,
      error: SCHEDULES_UNAVAILABLE_MESSAGE,
    });
  });
});

describe('scheduleErrorMessage', () => {
  it.each([
    [undefined, SCHEDULES_UNAVAILABLE_MESSAGE],
    [401, SCHEDULES_UNAUTHORIZED_MESSAGE],
    [404, SCHEDULE_NOT_FOUND_MESSAGE],
    [409, SCHEDULE_BUSY_MESSAGE],
    [422, SCHEDULE_INVALID_MESSAGE],
    [503, SCHEDULES_STORE_UNAVAILABLE_MESSAGE],
    [500, SCHEDULES_REQUEST_FAILED_MESSAGE],
  ])('maps status %s', (status, message) => {
    expect(scheduleErrorMessage({ status })).toBe(message);
  });

  it('formats singular and out-of-range cooldowns', () => {
    expect(scheduleCooldownMessage(1)).toContain('1 second.');
    expect(scheduleCooldownMessage(0)).toBe(SCHEDULE_COOLDOWN_FALLBACK_MESSAGE);
    expect(scheduleCooldownMessage(10 ** 7)).toBe(SCHEDULE_COOLDOWN_FALLBACK_MESSAGE);
    expect(scheduleErrorMessage({ status: 429, retryAfter: 5 })).toContain('5 seconds');
  });
});
