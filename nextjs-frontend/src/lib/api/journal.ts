import 'server-only';

import { callBackend } from './server';
import { JOURNAL_REQUEST_FAILED_MESSAGE, journalErrorMessage } from './journal-messages';
import {
  createJournalEntry,
  deleteJournalEntry,
  getJournalEntry,
  listJournal,
  updateJournalEntry,
  type JournalEntryIn,
  type JournalEntryOut,
  type JournalEntryUpdate,
  type JournalPage,
} from './generated';

/**
 * Server-only calls to the journal endpoints. Callers import these instead of the generated SDK.
 * Every failure becomes one of the fixed messages in `journal-messages.ts`; the API's own error
 * text is never passed on. Entry `notes` are user text: render them as escaped text only.
 */

export type { JournalEntryIn, JournalEntryOut, JournalEntryUpdate, JournalPage };

export type JournalResult<T> =
  { success: true; data: T } | { success: false; error: string; status?: number };

export type JournalQuery = { limit?: number; cursor?: string };

const TIMEFRAMES: readonly unknown[] = ['5m', '15m', '30m', '1h', '4h', '1d'];
const SIDES: readonly unknown[] = ['long', 'short'];

function isRecord(body: unknown): body is Record<string, unknown> {
  return typeof body === 'object' && body !== null;
}

const isNumber = (value: unknown): value is number => typeof value === 'number';
const isOptionalNumber = (value: unknown): boolean =>
  value === undefined || value === null || isNumber(value);
const isOptionalString = (value: unknown): boolean =>
  value === undefined || value === null || typeof value === 'string';

function isEntry(body: unknown): body is JournalEntryOut {
  return (
    isRecord(body) &&
    isNumber(body.id) &&
    typeof body.symbol === 'string' &&
    TIMEFRAMES.includes(body.timeframe) &&
    SIDES.includes(body.side) &&
    isNumber(body.entry) &&
    isNumber(body.stop) &&
    isOptionalNumber(body.exit) &&
    isOptionalNumber(body.size) &&
    isOptionalNumber(body.pnl_currency) &&
    isOptionalNumber(body.analysis_id) &&
    typeof body.opened_at === 'string' &&
    isOptionalString(body.closed_at) &&
    (body.notes === undefined || typeof body.notes === 'string') &&
    typeof body.created_at === 'string' &&
    typeof body.updated_at === 'string'
  );
}

type Failure = { success: false; error: string; status?: number };

function badBody(): Failure {
  return { success: false, error: JOURNAL_REQUEST_FAILED_MESSAGE, status: 502 };
}

function failure(result: { status?: number }): Failure {
  return { success: false, error: journalErrorMessage(result), status: result.status };
}

/** One page of entries, newest opened first. Any invalid row fails the page, never hides it. */
export async function fetchJournal(query: JournalQuery = {}): Promise<JournalResult<JournalPage>> {
  const result = await callBackend((client) =>
    listJournal({ client, query: { limit: query.limit, cursor: query.cursor } })
  );
  if (!result.success) return failure(result);
  const body: unknown = result.data;
  if (!isRecord(body) || !Array.isArray(body.items)) return badBody();
  const items = body.items.filter(isEntry);
  if (items.length !== body.items.length) return badBody();
  if (!isOptionalString(body.next_cursor)) return badBody();
  const next = typeof body.next_cursor === 'string' ? body.next_cursor : null;
  return { success: true, data: { items, next_cursor: next } };
}

export async function fetchJournalEntry(id: number): Promise<JournalResult<JournalEntryOut>> {
  const result = await callBackend((client) => getJournalEntry({ client, path: { entry_id: id } }));
  if (!result.success) return failure(result);
  return isEntry(result.data) ? { success: true, data: result.data } : badBody();
}

export async function addJournalEntry(
  body: JournalEntryIn
): Promise<JournalResult<JournalEntryOut>> {
  const result = await callBackend((client) => createJournalEntry({ client, body }));
  if (!result.success) return failure(result);
  return isEntry(result.data) ? { success: true, data: result.data } : badBody();
}

export async function editJournalEntry(
  id: number,
  body: JournalEntryUpdate
): Promise<JournalResult<JournalEntryOut>> {
  const result = await callBackend((client) =>
    updateJournalEntry({ client, path: { entry_id: id }, body })
  );
  if (!result.success) return failure(result);
  return isEntry(result.data) ? { success: true, data: result.data } : badBody();
}

export async function removeJournalEntry(id: number): Promise<JournalResult<null>> {
  const result = await callBackend((client) =>
    deleteJournalEntry({ client, path: { entry_id: id } })
  );
  if (!result.success) return failure(result);
  return { success: true, data: null };
}
