import 'server-only';

import { callBackend } from './server';
import { CALENDAR_REQUEST_FAILED_MESSAGE, calendarErrorMessage } from './calendar-messages';
import { getCalendar, type CalendarEventOut, type CalendarResponse } from './generated';

/**
 * Server-only call to the economic calendar. Callers import this instead of the generated SDK.
 * Every failure becomes one of the fixed messages in `calendar-messages.ts`. Event `title` is
 * third-party text: render it as escaped plain text only.
 */

export type { CalendarEventOut, CalendarResponse };

export type CalendarResult =
  { success: true; data: CalendarResponse } | { success: false; error: string; status?: number };

const STATUSES: readonly unknown[] = ['fresh', 'stale', 'unavailable'];
const RISKS: readonly unknown[] = ['none', 'elevated', 'high'];
const IMPACTS: readonly unknown[] = ['high', 'medium', 'low', 'holiday'];

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null && !Array.isArray(body);
}

const isOptionalNumber = (value: unknown): boolean =>
  value === undefined || value === null || Number.isFinite(value);

const isTimestamp = (value: unknown): value is string =>
  typeof value === 'string' && !Number.isNaN(Date.parse(value));

function isEvent(body: unknown): body is CalendarEventOut {
  return (
    isRecord(body) &&
    typeof body.currency === 'string' &&
    IMPACTS.includes(body.impact) &&
    isTimestamp(body.time) &&
    typeof body.title === 'string' &&
    isOptionalNumber(body.actual) &&
    isOptionalNumber(body.forecast) &&
    isOptionalNumber(body.previous)
  );
}

function isCalendar(body: unknown): body is CalendarResponse {
  return (
    isRecord(body) &&
    typeof body.symbol === 'string' &&
    Array.isArray(body.currencies) &&
    body.currencies.every((currency) => typeof currency === 'string') &&
    STATUSES.includes(body.calendar_status) &&
    RISKS.includes(body.immediate_risk) &&
    isTimestamp(body.as_of) &&
    (body.fetched_at === null || isTimestamp(body.fetched_at)) &&
    Number.isFinite(body.window_hours) &&
    Array.isArray(body.events) &&
    body.events.every(isEvent)
  );
}

/** Upcoming events and the immediate-risk rating for a symbol. Any invalid row fails the call. */
export async function fetchCalendar(symbol: string, hours?: number): Promise<CalendarResult> {
  const result = await callBackend((client) => getCalendar({ client, query: { symbol, hours } }));
  if (!result.success) {
    return { success: false, error: calendarErrorMessage(result), status: result.status };
  }
  if (!isCalendar(result.data)) {
    return { success: false, error: CALENDAR_REQUEST_FAILED_MESSAGE, status: 502 };
  }
  return { success: true, data: result.data };
}
