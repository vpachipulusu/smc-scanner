// @vitest-environment node
/** The automation server actions validate allow-listed fields, call the wrappers and return fixed state. */
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { makeRun, makeSchedule } from '../../helpers/automation-fixtures';

const mocks = vi.hoisted(() => ({
  addSchedule: vi.fn(),
  editSchedule: vi.fn(),
  removeSchedule: vi.fn(),
  runSchedule: vi.fn(),
  revalidatePath: vi.fn(),
  redirect: vi.fn(),
  /** Real `redirect` throws; a flag on a plain wrapper avoids vitest 5's spy-throw failure. */
  redirectThrows: false,
  /** A plain function (not a spy): vitest 5 fails a test when a spy throws, even if it is caught. */
  thrower: null as (() => Promise<never>) | null,
}));
vi.mock('@/lib/api/schedules', () => ({
  addSchedule: (...a: unknown[]) => mocks.thrower?.() ?? mocks.addSchedule(...a),
  editSchedule: (...a: unknown[]) => mocks.thrower?.() ?? mocks.editSchedule(...a),
  removeSchedule: (...a: unknown[]) => mocks.thrower?.() ?? mocks.removeSchedule(...a),
  runSchedule: (...a: unknown[]) => mocks.thrower?.() ?? mocks.runSchedule(...a),
}));
vi.mock('next/cache', () => ({ revalidatePath: mocks.revalidatePath }));
vi.mock('next/navigation', () => ({
  redirect: (path: string) => {
    mocks.redirect(path);
    if (mocks.redirectThrows) throw new Error('NEXT_REDIRECT');
  },
}));

import {
  deleteScheduleAction,
  runScheduleAction,
  saveScheduleAction,
  toggleScheduleAction,
} from '@/app/automation/actions';
import { SCHEDULES_REQUEST_FAILED_MESSAGE } from '@/lib/api/schedules-messages';
import { IDLE_FORM_STATE, IDLE_ROW_STATE } from '@/lib/automation/state';

function form(entries: Record<string, string>): FormData {
  const data = new FormData();
  for (const [key, value] of Object.entries(entries)) data.append(key, value);
  return data;
}

const VALID = { name: 'Scan', source: 'demo', tf: '1h', symbols: 'EURUSD', frequency: '1h' };

beforeEach(() => {
  for (const mock of Object.values(mocks))
    if (typeof mock === 'function' && 'mockReset' in mock) mock.mockReset();
  mocks.thrower = null;
  mocks.redirectThrows = false;
});

describe('saveScheduleAction', () => {
  it('creates a schedule, revalidates and reports success', async () => {
    mocks.addSchedule.mockResolvedValue({ success: true, data: makeSchedule() });

    const state = await saveScheduleAction(IDLE_FORM_STATE, form(VALID));

    expect(mocks.addSchedule).toHaveBeenCalledWith(
      expect.objectContaining({ name: 'Scan', symbols: ['EURUSD'], telegram_chat_id: null })
    );
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/automation');
    expect(mocks.redirect).not.toHaveBeenCalled();
    expect(state).toEqual({ status: 'success', message: 'Schedule "Scan" created.' });
  });

  it('updates when an id is carried and redirects back to the list', async () => {
    mocks.editSchedule.mockResolvedValue({ success: true, data: makeSchedule() });

    mocks.redirectThrows = true;

    // redirect() throws NEXT_REDIRECT in production; it must propagate, not be swallowed.
    await expect(saveScheduleAction(IDLE_FORM_STATE, form({ ...VALID, id: '4' }))).rejects.toThrow(
      'NEXT_REDIRECT'
    );

    expect(mocks.editSchedule).toHaveBeenCalledWith(4, expect.objectContaining({ name: 'Scan' }));
    expect(mocks.redirect).toHaveBeenCalledWith('/automation');
  });

  it('returns field errors without calling the API', async () => {
    const state = await saveScheduleAction(IDLE_FORM_STATE, form({ ...VALID, symbols: '' }));

    expect(mocks.addSchedule).not.toHaveBeenCalled();
    expect(state).toMatchObject({ status: 'error', errors: { symbols: expect.any(String) } });
  });

  it('rejects a tampered id', async () => {
    const state = await saveScheduleAction(IDLE_FORM_STATE, form({ ...VALID, id: '../x' }));

    expect(mocks.editSchedule).not.toHaveBeenCalled();
    expect(state).toMatchObject({ status: 'error', message: expect.any(String) });
  });

  it('shows the wrapper message when the API refuses, keeping the values', async () => {
    mocks.addSchedule.mockResolvedValue({
      success: false,
      error: 'The API rejected these values.',
    });

    const state = await saveScheduleAction(IDLE_FORM_STATE, form(VALID));

    expect(state).toMatchObject({
      status: 'error',
      message: 'The API rejected these values.',
      values: { name: 'Scan' },
    });
    expect(mocks.revalidatePath).not.toHaveBeenCalled();
  });

  it('turns a thrown error into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom with secrets'));

    const state = await saveScheduleAction(IDLE_FORM_STATE, form(VALID));

    expect(state).toMatchObject({ status: 'error', message: SCHEDULES_REQUEST_FAILED_MESSAGE });
  });
});

describe('toggleScheduleAction', () => {
  it('enables and disables', async () => {
    mocks.editSchedule.mockResolvedValue({ success: true, data: makeSchedule() });

    expect(await toggleScheduleAction(IDLE_ROW_STATE, form({ id: '2', enabled: 'true' }))).toEqual({
      status: 'success',
      message: 'Schedule enabled.',
    });
    expect(mocks.editSchedule).toHaveBeenCalledWith(2, { enabled: true });

    expect(await toggleScheduleAction(IDLE_ROW_STATE, form({ id: '2', enabled: 'false' }))).toEqual(
      {
        status: 'success',
        message: 'Schedule disabled.',
      }
    );
    expect(mocks.editSchedule).toHaveBeenLastCalledWith(2, { enabled: false });
  });

  it('rejects a missing or garbled enabled flag instead of disabling', async () => {
    for (const entries of [{ id: '2' }, { id: '2', enabled: 'yes' }] as Record<string, string>[]) {
      expect(await toggleScheduleAction(IDLE_ROW_STATE, form(entries))).toMatchObject({
        status: 'error',
      });
    }
    expect(mocks.editSchedule).not.toHaveBeenCalled();
  });

  it('rejects a bad id and surfaces failures', async () => {
    expect(await toggleScheduleAction(IDLE_ROW_STATE, form({ id: 'x' }))).toMatchObject({
      status: 'error',
    });
    mocks.editSchedule.mockResolvedValue({ success: false, error: 'gone' });
    expect(await toggleScheduleAction(IDLE_ROW_STATE, form({ id: '2', enabled: 'true' }))).toEqual({
      status: 'error',
      message: 'gone',
    });
  });
});

describe('runScheduleAction', () => {
  it('summarises a finished run', async () => {
    mocks.runSchedule.mockResolvedValue({ success: true, data: makeRun() });

    const state = await runScheduleAction(IDLE_ROW_STATE, form({ id: '1' }));

    expect(state).toEqual({
      status: 'success',
      message: 'Run finished: 3 hits, 2 delivered, 1 skipped.',
    });
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/automation');
  });

  it('reports a failed run without any error text', async () => {
    mocks.runSchedule.mockResolvedValue({ success: true, data: makeRun({ status: 'failed' }) });

    const state = await runScheduleAction(IDLE_ROW_STATE, form({ id: '1' }));

    expect(state).toEqual({
      status: 'error',
      message: 'The run failed. Open the job log for details.',
    });
  });

  it('passes the busy and cooldown messages through', async () => {
    mocks.runSchedule.mockResolvedValue({ success: false, error: 'A run is already in progress.' });
    expect(await runScheduleAction(IDLE_ROW_STATE, form({ id: '1' }))).toEqual({
      status: 'error',
      message: 'A run is already in progress.',
    });
  });

  it('rejects a bad id', async () => {
    expect(await runScheduleAction(IDLE_ROW_STATE, form({ id: '0' }))).toMatchObject({
      status: 'error',
    });
    expect(mocks.runSchedule).not.toHaveBeenCalled();
  });
});

describe('deleteScheduleAction', () => {
  it('deletes and revalidates', async () => {
    mocks.removeSchedule.mockResolvedValue({ success: true, data: null });

    expect(await deleteScheduleAction(IDLE_ROW_STATE, form({ id: '3' }))).toEqual({
      status: 'success',
      message: 'Schedule deleted.',
    });
    expect(mocks.removeSchedule).toHaveBeenCalledWith(3);
    expect(mocks.revalidatePath).toHaveBeenCalledWith('/automation');
  });

  it('rejects a bad id and surfaces failures', async () => {
    expect(await deleteScheduleAction(IDLE_ROW_STATE, form({}))).toMatchObject({ status: 'error' });
    mocks.removeSchedule.mockResolvedValue({ success: false, error: 'nope' });
    expect(await deleteScheduleAction(IDLE_ROW_STATE, form({ id: '3' }))).toEqual({
      status: 'error',
      message: 'nope',
    });
  });
});
