// @vitest-environment node
/** The journal wrapper maps calls to the API, checks every row and never exposes backend text. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  addJournalEntry,
  editJournalEntry,
  fetchJournal,
  fetchJournalEntry,
  removeJournalEntry,
} from '@/lib/api/journal';
import {
  JOURNAL_INVALID_MESSAGE,
  JOURNAL_LIMIT_MESSAGE,
  JOURNAL_NOT_FOUND_MESSAGE,
  JOURNAL_RATE_LIMITED_MESSAGE,
  JOURNAL_REQUEST_FAILED_MESSAGE,
  JOURNAL_STORE_UNAVAILABLE_MESSAGE,
  JOURNAL_UNAUTHORIZED_MESSAGE,
  JOURNAL_UNAVAILABLE_MESSAGE,
  journalErrorMessage,
} from '@/lib/api/journal-messages';
import { makeClosedEntry, makeEntry } from '../../helpers/journal-fixtures';

const jsonResponse = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json' },
  });

const CREATE_BODY = {
  symbol: 'EURUSD',
  timeframe: '1h' as const,
  side: 'long' as const,
  entry: 1.1,
  stop: 1.09,
  opened_at: '2026-10-20T10:00:00Z',
};

describe('journal wrapper', () => {
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

  it('lists a page with the cursor and limit and exposes next_cursor', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ items: [makeEntry(), makeClosedEntry({ id: 2 })], next_cursor: 'abc' })
    );

    const result = await fetchJournal({ limit: 25, cursor: 'zzz' });

    expect(result.success && result.data.items.map((e) => e.id)).toEqual([1, 2]);
    expect(result.success && result.data.next_cursor).toBe('abc');
    const url = new URL(fetchMock.mock.calls[0][0].url);
    expect(url.pathname).toBe('/journal');
    expect(Object.fromEntries(url.searchParams)).toEqual({ limit: '25', cursor: 'zzz' });
  });

  it('returns a null next_cursor on the last page', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [] }));
    const result = await fetchJournal();
    expect(result.success && result.data.next_cursor).toBeNull();
  });

  it('fails when any row is invalid instead of hiding it', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [makeEntry(), { id: 'bad' }] }));
    expect(await fetchJournal()).toEqual({
      success: false,
      error: JOURNAL_REQUEST_FAILED_MESSAGE,
      status: 502,
    });
  });

  it.each([
    ['a stop that is a string', { stop: 'x' }],
    ['an unknown side', { side: 'sideways' }],
    ['an unknown timeframe', { timeframe: '2h' }],
    ['a non-string note', { notes: 5 }],
    ['an exit that is a string', { exit: '1.2' }],
    ['a size that is a string', { size: '1' }],
    ['an analysis id that is a string', { analysis_id: 'a' }],
  ])('rejects a row with %s', async (_label, patch) => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [{ ...makeEntry(), ...patch }] }));
    expect((await fetchJournal()).success).toBe(false);
  });

  it('fails on a malformed next_cursor instead of truncating the journal', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ items: [], next_cursor: 5 }));
    expect((await fetchJournal()).success).toBe(false);
  });

  it('fails on a body that is not a page', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ nope: true }));
    expect((await fetchJournal()).success).toBe(false);
  });

  it('gets one entry and rejects a malformed one', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeEntry({ id: 7 })));
    const result = await fetchJournalEntry(7);
    expect(result.success && result.data.id).toBe(7);
    expect(new URL(fetchMock.mock.calls[0][0].url).pathname).toBe('/journal/7');

    fetchMock.mockResolvedValue(jsonResponse({ id: 7 }));
    expect((await fetchJournalEntry(7)).success).toBe(false);
  });

  it('creates with the body and rejects a malformed result', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeEntry({ id: 5 }), 201));
    const result = await addJournalEntry(CREATE_BODY);
    expect(result.success && result.data.id).toBe(5);
    const create = fetchMock.mock.calls[0][0];
    expect(create.method).toBe('POST');
    expect(await create.json()).toEqual(CREATE_BODY);

    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }, 201));
    const bad = await addJournalEntry(CREATE_BODY);
    expect(!bad.success && bad.error).toBe(JOURNAL_REQUEST_FAILED_MESSAGE);
  });

  it('updates by id with a PATCH and rejects a malformed result', async () => {
    fetchMock.mockResolvedValue(jsonResponse(makeEntry({ id: 5, notes: 'n' })));
    const result = await editJournalEntry(5, { notes: 'n' });
    expect(result.success && result.data.notes).toBe('n');
    const patch = fetchMock.mock.calls[0][0];
    expect(patch.method).toBe('PATCH');
    expect(new URL(patch.url).pathname).toBe('/journal/5');

    fetchMock.mockResolvedValue(jsonResponse({ id: 1 }));
    expect((await editJournalEntry(5, { notes: 'n' })).success).toBe(false);
  });

  it('deletes an entry', async () => {
    fetchMock.mockResolvedValue(jsonResponse({ success: true }));
    expect(await removeJournalEntry(3)).toEqual({ success: true, data: null });
    const request = fetchMock.mock.calls[0][0];
    expect(request.method).toBe('DELETE');
    expect(new URL(request.url).pathname).toBe('/journal/3');
  });

  it('never passes the backend error text on', async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ success: false, error: 'Traceback: secret detail' }, 500)
    );
    expect(await fetchJournal()).toEqual({
      success: false,
      error: JOURNAL_REQUEST_FAILED_MESSAGE,
      status: 500,
    });
  });

  it('reports an unreachable API without a status', async () => {
    fetchMock.mockRejectedValue(new TypeError('fetch failed'));
    expect(await fetchJournal()).toMatchObject({
      success: false,
      error: JOURNAL_UNAVAILABLE_MESSAGE,
    });
  });
});

describe('journalErrorMessage', () => {
  it.each([
    [undefined, JOURNAL_UNAVAILABLE_MESSAGE],
    [401, JOURNAL_UNAUTHORIZED_MESSAGE],
    [404, JOURNAL_NOT_FOUND_MESSAGE],
    [409, JOURNAL_LIMIT_MESSAGE],
    [422, JOURNAL_INVALID_MESSAGE],
    [429, JOURNAL_RATE_LIMITED_MESSAGE],
    [503, JOURNAL_STORE_UNAVAILABLE_MESSAGE],
    [500, JOURNAL_REQUEST_FAILED_MESSAGE],
  ])('maps status %s', (status, message) => {
    expect(journalErrorMessage({ status })).toBe(message);
  });
});
