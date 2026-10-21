// @vitest-environment node
/** The journal server actions validate allow-listed fields, call the wrappers and return fixed state. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeEntry } from '../../helpers/journal-fixtures';

const mocks = vi.hoisted(() => ({
  addJournalEntry: vi.fn(),
  editJournalEntry: vi.fn(),
  removeJournalEntry: vi.fn(),
  revalidatePath: vi.fn(),
  redirect: vi.fn(),
  /** Real `redirect` throws; a flag on a plain wrapper avoids vitest 5's spy-throw failure. */
  redirectThrows: false,
  /** A plain function (not a spy): vitest 5 fails a test when a spy throws, even if it is caught. */
  thrower: null as (() => Promise<never>) | null,
}));
vi.mock('@/lib/api/journal', () => ({
  addJournalEntry: (...a: unknown[]) => mocks.thrower?.() ?? mocks.addJournalEntry(...a),
  editJournalEntry: (...a: unknown[]) => mocks.thrower?.() ?? mocks.editJournalEntry(...a),
  removeJournalEntry: (...a: unknown[]) => mocks.thrower?.() ?? mocks.removeJournalEntry(...a),
}));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('next/navigation', () => ({
  redirect: (path: string) => {
    mocks.redirect(path);
    if (mocks.redirectThrows) throw new Error('NEXT_REDIRECT');
  },
}));

import { deleteJournalAction, saveJournalAction } from '@/app/journal/actions';
import { JOURNAL_REQUEST_FAILED_MESSAGE } from '@/lib/api/journal-messages';
import { IDLE_JOURNAL_FORM_STATE, IDLE_JOURNAL_ROW_STATE } from '@/lib/journal/state';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const VALID = {
  symbol: 'EURUSD',
  timeframe: '1h',
  side: 'long',
  entry: '1.1',
  stop: '1.09',
  opened_at: '2026-10-20T10:00',
};

beforeEach(() => {
  for (const mock of Object.values(mocks))
    if (typeof mock === 'function' && 'mockReset' in mock) mock.mockReset();
  mocks.thrower = null;
  mocks.redirectThrows = false;
});

describe('saveJournalAction', () => {
  it('creates an entry, revalidates and redirects to the list', async () => {
    mocks.addJournalEntry.mockResolvedValue({ success: true, data: makeEntry() });
    mocks.redirectThrows = true;

    // redirect() throws NEXT_REDIRECT in production; it must propagate, not be swallowed.
    await expect(saveJournalAction(IDLE_JOURNAL_FORM_STATE, form(VALID))).rejects.toThrow(
      'NEXT_REDIRECT'
    );

    expect(mocks.addJournalEntry).toHaveBeenCalledWith(
      expect.objectContaining({ symbol: 'EURUSD', entry: 1.1, exit: null })
    );
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/journal');
    expect(mocks.redirect).toHaveBeenCalledWith('/journal');
  });

  it('updates when an id is carried, sending explicit nulls to clear fields', async () => {
    mocks.editJournalEntry.mockResolvedValue({ success: true, data: makeEntry() });

    await saveJournalAction(IDLE_JOURNAL_FORM_STATE, form({ ...VALID, id: '4' }));

    expect(mocks.editJournalEntry).toHaveBeenCalledWith(
      4,
      expect.objectContaining({ exit: null, closed_at: null, size: null })
    );
    expect(mocks.addJournalEntry).not.toHaveBeenCalled();
    expect(mocks.redirect).toHaveBeenCalledWith('/journal');
  });

  it('returns field errors without calling the API', async () => {
    const state = await saveJournalAction(IDLE_JOURNAL_FORM_STATE, form({ ...VALID, stop: '1.2' }));

    expect(mocks.addJournalEntry).not.toHaveBeenCalled();
    expect(mocks.redirect).not.toHaveBeenCalled();
    expect(state).toMatchObject({
      status: 'error',
      errors: { stop: expect.any(String) },
      values: { stop: '1.2' },
    });
  });

  it('rejects a tampered id', async () => {
    const state = await saveJournalAction(IDLE_JOURNAL_FORM_STATE, form({ ...VALID, id: '../x' }));

    expect(mocks.editJournalEntry).not.toHaveBeenCalled();
    expect(state).toMatchObject({ status: 'error', message: expect.any(String) });
  });

  it('shows the wrapper message when the API refuses, keeping the values', async () => {
    mocks.addJournalEntry.mockResolvedValue({
      success: false,
      error: 'The API rejected these values.',
    });

    const state = await saveJournalAction(IDLE_JOURNAL_FORM_STATE, form(VALID));

    expect(state).toMatchObject({
      status: 'error',
      message: 'The API rejected these values.',
      values: { symbol: 'EURUSD' },
    });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
    expect(mocks.redirect).not.toHaveBeenCalled();
  });

  it('turns a thrown error into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom with secrets'));

    const state = await saveJournalAction(IDLE_JOURNAL_FORM_STATE, form(VALID));

    expect(state).toMatchObject({ status: 'error', message: JOURNAL_REQUEST_FAILED_MESSAGE });
    expect(JSON.stringify(state)).not.toContain('secrets');
  });
});

describe('deleteJournalAction', () => {
  it('deletes and revalidates', async () => {
    mocks.removeJournalEntry.mockResolvedValue({ success: true, data: null });

    expect(await deleteJournalAction(IDLE_JOURNAL_ROW_STATE, form({ id: '3' }))).toEqual({
      status: 'success',
      message: 'Entry deleted.',
    });
    expect(mocks.removeJournalEntry).toHaveBeenCalledWith(3);
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/journal');
  });

  it('rejects a bad id and surfaces failures', async () => {
    expect(await deleteJournalAction(IDLE_JOURNAL_ROW_STATE, form({}))).toMatchObject({
      status: 'error',
    });
    expect(mocks.removeJournalEntry).not.toHaveBeenCalled();
    mocks.removeJournalEntry.mockResolvedValue({ success: false, error: 'nope' });
    expect(await deleteJournalAction(IDLE_JOURNAL_ROW_STATE, form({ id: '3' }))).toEqual({
      status: 'error',
      message: 'nope',
    });
  });

  it('turns a thrown error into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom'));
    expect(await deleteJournalAction(IDLE_JOURNAL_ROW_STATE, form({ id: '3' }))).toEqual({
      status: 'error',
      message: JOURNAL_REQUEST_FAILED_MESSAGE,
    });
  });
});
