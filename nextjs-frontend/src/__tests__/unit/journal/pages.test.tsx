// @vitest-environment node
/** The journal pages read live data, validate route input and show only the fixed error messages. */
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';
import { makeClosedEntry, makeEntry } from '../../helpers/journal-fixtures';

const mocks = vi.hoisted(() => ({
  fetchJournal: vi.fn(),
  fetchJournalEntry: vi.fn(),
  notFound: vi.fn(),
}));
vi.mock('@/lib/api/journal', () => ({
  fetchJournal: mocks.fetchJournal,
  fetchJournalEntry: mocks.fetchJournalEntry,
}));
vi.mock('next/navigation', () => ({ notFound: mocks.notFound }));
vi.mock('@/app/journal/actions', () => ({
  saveJournalAction: vi.fn(),
  deleteJournalAction: vi.fn(),
}));

import JournalError from '@/app/journal/error';
import EditJournalPage from '@/app/journal/[id]/edit/page';
import JournalLoading from '@/app/journal/loading';
import JournalPage from '@/app/journal/page';
import NewJournalPage from '@/app/journal/new/page';
import { JOURNAL_UNAVAILABLE_MESSAGE } from '@/lib/api/journal-messages';

class NotFoundSignal extends Error {}

const list = (cursor?: string) =>
  JournalPage({ searchParams: Promise.resolve(cursor === undefined ? {} : { cursor }) });
const create = (params: Record<string, string | string[]> = {}) =>
  NewJournalPage({ searchParams: Promise.resolve(params) });
const edit = (id: string) => EditJournalPage({ params: Promise.resolve({ id }) });

beforeEach(() => {
  vi.useFakeTimers();
  vi.setSystemTime(new Date('2026-10-21T08:30:45Z'));
  mocks.fetchJournal.mockReset();
  mocks.fetchJournalEntry.mockReset();
  mocks.notFound.mockReset();
  mocks.notFound.mockImplementation(() => {
    throw new NotFoundSignal('NEXT_NOT_FOUND');
  });
});

afterEach(() => {
  vi.useRealTimers();
});

describe('JournalPage', () => {
  it('lists entries newest first with a link to add one', async () => {
    mocks.fetchJournal.mockResolvedValue({
      success: true,
      data: { items: [makeClosedEntry({ id: 2 }), makeEntry({ id: 1 })], next_cursor: null },
    });

    const html = renderToStaticMarkup(await list());

    expect(mocks.fetchJournal).toHaveBeenCalledWith({ limit: 25, cursor: undefined });
    expect(html).toContain('+2.00R');
    expect(html).toContain('href="/journal/new"');
    expect(html).not.toContain('Load more');
  });

  it('passes a valid cursor on and links Load more to the next page', async () => {
    mocks.fetchJournal.mockResolvedValue({
      success: true,
      data: { items: [makeEntry()], next_cursor: 'next_1' },
    });

    const html = renderToStaticMarkup(await list('start'));

    expect(mocks.fetchJournal).toHaveBeenCalledWith({ limit: 25, cursor: 'start' });
    expect(html).toContain('/journal?cursor=next_1');
    expect(html).toContain('Newest');
  });

  it('drops a malformed cursor instead of forwarding it', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: true, data: { items: [], next_cursor: null } });

    await list('x'.repeat(97));

    expect(mocks.fetchJournal).toHaveBeenCalledWith({ limit: 25, cursor: undefined });
  });

  it('shows an empty state that points at the form', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: true, data: { items: [], next_cursor: null } });

    const html = renderToStaticMarkup(await list());

    expect(html).toContain('No trades logged yet');
    expect(html).not.toContain('<table');
  });

  it('says so when a later page is empty', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: true, data: { items: [], next_cursor: null } });

    const html = renderToStaticMarkup(await list('abc'));

    expect(html).toContain('No older entries');
  });

  it('shows the fixed error and a retry link when the list cannot load', async () => {
    mocks.fetchJournal.mockResolvedValue({ success: false, error: JOURNAL_UNAVAILABLE_MESSAGE });

    const html = renderToStaticMarkup(await list('abc'));

    expect(html).toContain(JOURNAL_UNAVAILABLE_MESSAGE);
    expect(html).toContain('Retry');
    expect(html).toContain('/journal?cursor=abc');
  });
});

describe('NewJournalPage', () => {
  it('opens an empty form stamped with the current UTC minute', async () => {
    const html = renderToStaticMarkup(await create());

    expect(html).toContain('New journal entry');
    expect(html).toContain('value="2026-10-21T08:30"');
  });

  it('prefills from valid query params and ignores invalid ones', async () => {
    const html = renderToStaticMarkup(
      await create({
        symbol: 'GBPUSD',
        side: 'short',
        entry: '1.25',
        stop: 'bad',
        analysis_id: '7',
      })
    );

    expect(html).toContain('value="GBPUSD"');
    expect(html).toContain('value="1.25"');
    expect(html).toContain('analysis #7');
    expect(html).not.toContain('value="bad"');
  });
});

describe('EditJournalPage', () => {
  it('shows the stored entry in an edit form', async () => {
    mocks.fetchJournalEntry.mockResolvedValue({
      success: true,
      data: makeEntry({ id: 3, symbol: 'USDJPY', notes: 'note' }),
    });

    const html = renderToStaticMarkup(await edit('3'));

    expect(mocks.fetchJournalEntry).toHaveBeenCalledWith(3);
    expect(html).toContain('Edit journal entry');
    expect(html).toContain('value="USDJPY"');
    expect(html).toContain('Save changes');
  });

  it.each(['abc', '0', '-3', '1.5'])('calls notFound without fetching for id %s', async (id) => {
    await expect(edit(id)).rejects.toBeInstanceOf(NotFoundSignal);
    expect(mocks.fetchJournalEntry).not.toHaveBeenCalled();
  });

  it('calls notFound when the API says 404', async () => {
    mocks.fetchJournalEntry.mockResolvedValue({ success: false, error: 'x', status: 404 });
    await expect(edit('9')).rejects.toBeInstanceOf(NotFoundSignal);
  });

  it('shows the fixed message and a retry link for other failures', async () => {
    mocks.fetchJournalEntry.mockResolvedValue({
      success: false,
      error: JOURNAL_UNAVAILABLE_MESSAGE,
    });

    const html = renderToStaticMarkup(await edit('2'));

    expect(html).toContain(JOURNAL_UNAVAILABLE_MESSAGE);
    expect(html).toContain('/journal/2/edit');
  });
});

describe('journal loading and error states', () => {
  it('has a loading state', () => {
    expect(renderToStaticMarkup(<JournalLoading />)).toContain('aria-busy="true"');
  });

  it('shows a fixed message and a retry button without the error text', () => {
    const reset = vi.fn();
    const html = renderToStaticMarkup(
      <JournalError error={new Error('secret stack detail')} reset={reset} />
    );

    expect(html).toContain('role="alert"');
    expect(html).toContain('Try again');
    expect(html).not.toContain('secret');
  });
});
