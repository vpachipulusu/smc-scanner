import 'server-only';

import { callBackend } from './server';
import { SCHEDULES_REQUEST_FAILED_MESSAGE, scheduleErrorMessage } from './schedules-messages';
import {
  createSchedule,
  deleteSchedule,
  listScheduleLogs,
  listSchedules,
  runScheduleNow,
  updateSchedule,
  type JobLogOut,
  type JobLogPage,
  type RunOut,
  type ScheduleCreate,
  type ScheduleOut,
  type ScheduleUpdate,
} from './generated';

/**
 * Server-only calls to the schedule endpoints. Callers import these instead of the generated SDK.
 * Every failure becomes one of the fixed messages in `schedules-messages.ts`; the API's own error
 * text is never passed on. Job-log `error` text is raw backend text: it is returned as data and
 * must only ever be rendered as escaped text.
 */

export type { JobLogOut, JobLogPage, RunOut, ScheduleCreate, ScheduleOut, ScheduleUpdate };

export type ScheduleResult<T> =
  { success: true; data: T } | { success: false; error: string; status?: number };

const SOURCES: readonly unknown[] = ['mt5', 'demo'];
const TIMEFRAMES: readonly unknown[] = ['5m', '15m', '30m', '1h', '4h', '1d'];
const FREQUENCIES: readonly unknown[] = ['15m', '1h', '4h', '1d'];
const LOG_STATUSES: readonly unknown[] = ['success', 'skipped', 'failed'];
const RUN_STATUSES: readonly unknown[] = ['ok', 'failed'];

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null;
}

const isNumber = (value: unknown): value is number => typeof value === 'number';
const isNullableString = (value: unknown): boolean => value === null || typeof value === 'string';

function isSchedule(body: unknown): body is ScheduleOut {
  return (
    isRecord(body) &&
    isNumber(body.id) &&
    typeof body.name === 'string' &&
    SOURCES.includes(body.source) &&
    TIMEFRAMES.includes(body.tf) &&
    FREQUENCIES.includes(body.frequency) &&
    Array.isArray(body.symbols) &&
    body.symbols.every((symbol) => typeof symbol === 'string') &&
    isNumber(body.min_score) &&
    isNumber(body.min_confidence) &&
    typeof body.only_on_change === 'boolean' &&
    typeof body.send_hold === 'boolean' &&
    typeof body.enabled === 'boolean' &&
    isNullableString(body.telegram_chat_id) &&
    isNullableString(body.last_run_at) &&
    isNullableString(body.next_run_at)
  );
}

function isLog(body: unknown): body is JobLogOut {
  return (
    isRecord(body) &&
    isNumber(body.id) &&
    isNumber(body.schedule_id) &&
    typeof body.started_at === 'string' &&
    typeof body.finished_at === 'string' &&
    isNumber(body.duration_ms) &&
    LOG_STATUSES.includes(body.status) &&
    isNumber(body.hits) &&
    isNumber(body.delivered) &&
    isNumber(body.skipped) &&
    isNullableString(body.skip_reason) &&
    isNullableString(body.error)
  );
}

function isRun(body: unknown): body is RunOut {
  return (
    isRecord(body) &&
    RUN_STATUSES.includes(body.status) &&
    isNumber(body.rows) &&
    isNumber(body.delivered) &&
    isNumber(body.skipped) &&
    isNumber(body.error_count)
  );
}

type Failure = { success: false; error: string; status?: number };

function badBody(): Failure {
  return { success: false, error: SCHEDULES_REQUEST_FAILED_MESSAGE, status: 502 };
}

function failure(result: { status?: number }, retryAfter?: number): Failure {
  return {
    success: false,
    error: scheduleErrorMessage({ status: result.status, retryAfter }),
    status: result.status,
  };
}

export async function fetchSchedules(): Promise<ScheduleResult<ScheduleOut[]>> {
  const result = await callBackend((client) => listSchedules({ client }));
  if (!result.success) return failure(result);
  const items: unknown = isRecord(result.data) ? result.data.items : null;
  if (!Array.isArray(items)) return badBody();
  const schedules = items.filter(isSchedule);
  // A partly invalid list must not read as an empty state; treat contract drift as a failure.
  if (schedules.length !== items.length) return badBody();
  return { success: true, data: schedules };
}

export async function addSchedule(body: ScheduleCreate): Promise<ScheduleResult<ScheduleOut>> {
  const result = await callBackend((client) => createSchedule({ client, body }));
  if (!result.success) return failure(result);
  return isSchedule(result.data) ? { success: true, data: result.data } : badBody();
}

export async function editSchedule(
  id: number,
  body: ScheduleUpdate
): Promise<ScheduleResult<ScheduleOut>> {
  const result = await callBackend((client) =>
    updateSchedule({ client, path: { schedule_id: id }, body })
  );
  if (!result.success) return failure(result);
  return isSchedule(result.data) ? { success: true, data: result.data } : badBody();
}

export async function removeSchedule(id: number): Promise<ScheduleResult<null>> {
  const result = await callBackend((client) =>
    deleteSchedule({ client, path: { schedule_id: id } })
  );
  if (!result.success) return failure(result);
  return { success: true, data: null };
}

/** Parses `Retry-After` (whole seconds); anything else is ignored. */
function parseRetryAfter(header: string | null | undefined): number | undefined {
  if (!header || !/^\d{1,6}$/.test(header)) return undefined;
  return Number(header);
}

export async function runSchedule(id: number): Promise<ScheduleResult<RunOut>> {
  let retryAfter: number | undefined;
  const result = await callBackend(async (client) => {
    const response = await runScheduleNow({ client, path: { schedule_id: id } });
    retryAfter = parseRetryAfter(response.response?.headers.get('Retry-After'));
    return response;
  });
  if (!result.success) return failure(result, retryAfter);
  return isRun(result.data) ? { success: true, data: result.data } : badBody();
}

export type LogsQuery = { limit?: number; cursor?: string };

export async function fetchScheduleLogs(
  id: number,
  query: LogsQuery = {}
): Promise<ScheduleResult<JobLogPage>> {
  const result = await callBackend((client) =>
    listScheduleLogs({
      client,
      path: { schedule_id: id },
      query: { limit: query.limit, cursor: query.cursor },
    })
  );
  if (!result.success) return failure(result);
  const body: unknown = result.data;
  if (!isRecord(body) || !Array.isArray(body.items)) return badBody();
  const next = typeof body.next_cursor === 'string' ? body.next_cursor : null;
  const items = body.items.filter(isLog);
  if (items.length !== body.items.length) return badBody();
  return { success: true, data: { items, next_cursor: next } };
}
