// @vitest-environment node
/** The calendar wrapper maps the call to the API, checks every row and never exposes backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { fetchCalendar } from '@/lib/api/calendar';
import {
  CALENDAR_INVALID_MESSAGE,
  CALENDAR_RATE_LIMITED_MESSAGE,
  CALENDAR_REQUEST_FAILED_MESSAGE,
  CALENDAR_UNAUTHORIZED_MESSAGE,
  CALENDAR_UNAVAILABLE_MESSAGE,
  calendarErrorMessage,
} from '@/lib/api/calendar-messages';
import { makeCalendar, makeEvent } from '../../helpers/calendar-fixtures';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

describe('calendar wrapper', () => {
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

  it('returns the calendar and maps symbol and hours to the query', async () => {
    const calendar = makeCalendar();
    fetchMock.mockResolvedValue(jsonResponse(calendar));

    const result = await fetchCalendar('EURUSD', 48);

    expect(result).toEqual({ success: true, data: calendar });
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/calendar');
    expect(Object.fromEntries(url.searchParams)).toEqual({ symbol: 'EURUSD', hours: '48' });
  });

  it('omits hours when not given and accepts null figures', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse(makeCalendar({ events: [makeEvent({ actual: undefined, forecast: null })] }))
    );

    const result = await fetchCalendar('XAUUSD');

    expect(result.success).toBe(true);
    expect(new URL(fetchMock.mock.calls[0][0].url).searchParams.has('hours')).toBe(false);
  });

  it.each([
    [401, CALENDAR_UNAUTHORIZED_MESSAGE],
    [422, CALENDAR_INVALID_MESSAGE],
    [429, CALENDAR_RATE_LIMITED_MESSAGE],
    [500, CALENDAR_REQUEST_FAILED_MESSAGE],
  ])('maps status %s to a fixed message, never the backend text', async (status, message) => {
    fetchMock.mockResolvedValue(jsonResponse({ success: false, error: 'secret detail' }, status));

    const result = await fetchCalendar('EURUSD');

    expect(result).toEqual({ success: false, error: message, status });
  });

  it('reports an unreachable API without a status', async () => {
    fetchMock.mockRejectedValue(new Error('boom'));

    const result = await fetchCalendar('EURUSD');

    expect(result.success).toBe(false);
    expect(result).toMatchObject({ error: CALENDAR_UNAVAILABLE_MESSAGE });
    expect(calendarErrorMessage({})).toBe(CALENDAR_UNAVAILABLE_MESSAGE);
  });

  it.each([
    ['not an object', 'nope'],
    ['bad status', { ...makeCalendar(), calendar_status: 'old' }],
    ['bad risk', { ...makeCalendar(), immediate_risk: 'severe' }],
    ['missing events', { ...makeCalendar(), events: undefined }],
    ['bad currencies', { ...makeCalendar(), currencies: [1] }],
    ['bad fetched_at', { ...makeCalendar(), fetched_at: 5 }],
    ['unparseable fetched_at', { ...makeCalendar(), fetched_at: 'soon' }],
    ['unparseable as_of', { ...makeCalendar(), as_of: 'x'.repeat(500) }],
    ['array body', []],
    ['unparseable row time', makeCalendar({ events: [makeEvent({ time: 'later' })] })],
    ['bad row impact', makeCalendar({ events: [{ ...makeEvent(), impact: 'extreme' as never }] })],
    ['bad row title', makeCalendar({ events: [{ ...makeEvent(), title: 5 as never }] })],
    ['bad row figure', makeCalendar({ events: [{ ...makeEvent(), actual: '1' as never }] })],
  ])('fails the whole call on a bad body (%s)', async (_name, body) => {
    fetchMock.mockResolvedValue(jsonResponse(body));

    expect(await fetchCalendar('EURUSD')).toEqual({
      success: false,
      error: CALENDAR_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });
});
