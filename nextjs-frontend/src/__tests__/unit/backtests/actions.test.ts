// @vitest-environment node
/** The backtest server actions read allow-listed fields, call the wrappers and map failures. */
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  startBacktest: vi.fn(),
  fetchBacktest: vi.fn(),
  /** A plain function (not a spy): vitest 5 fails a test when a spy throws, even if it is caught. */
  thrower: null as (() => Promise<never>) | null,
}));
vi.mock('@/lib/api/backtests', () => ({
  startBacktest: (...a: unknown[]) => mocks.thrower?.() ?? mocks.startBacktest(...a),
  fetchBacktest: (...a: unknown[]) => mocks.thrower?.() ?? mocks.fetchBacktest(...a),
}));

import { pollBacktestAction, runBacktestAction } from '@/app/strategies/[slug]/backtest/actions';
import {
  BACKTEST_ALREADY_RUNNING_MESSAGE,
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
  BACKTESTS_REQUEST_FAILED_MESSAGE,
} from '@/lib/api/backtests-messages';
import { BACKTEST_DEFAULTS } from '@/lib/backtests/form';
import { IDLE_RUN_BACKTEST_STATE } from '@/lib/backtests/state';
import { makeBacktest } from '../../helpers/backtest-fixtures';

const formOf = (overrides: Record<string, string> = {}): FormData => {
  const form = new FormData();
  for (const [name, value] of Object.entries({
    strategy: 'my-one',
    ...BACKTEST_DEFAULTS,
    ...overrides,
  })) {
    form.set(name, value);
  }
  return form;
};

const run = (form: FormData) => runBacktestAction(IDLE_RUN_BACKTEST_STATE, form);

beforeEach(() => {
  mocks.startBacktest.mockReset();
  mocks.fetchBacktest.mockReset();
  mocks.thrower = null;
});

describe('runBacktestAction', () => {
  it('starts a run for the strategy and returns its id', async () => {
    mocks.startBacktest.mockResolvedValue({
      success: true,
      data: { id: 11, backtest: makeBacktest({ id: 11, status: 'pending' }) },
    });

    expect(await run(formOf({ symbols: 'EURUSD' }))).toEqual({
      status: 'started',
      id: 11,
      values: { ...BACKTEST_DEFAULTS, symbols: 'EURUSD' },
    });
    expect(mocks.startBacktest).toHaveBeenCalledWith(
      expect.objectContaining({ strategy: 'my-one', source: 'demo', symbols: ['EURUSD'] })
    );
  });

  it('returns field errors without calling the API', async () => {
    const state = await run(formOf({ bars: '1' }));
    expect(state).toMatchObject({ status: 'error', errors: { bars: expect.any(String) } });
    expect(mocks.startBacktest).not.toHaveBeenCalled();
  });

  it('rejects a tampered strategy slug', async () => {
    expect(await run(formOf({ strategy: '../x' }))).toMatchObject({
      status: 'error',
      message: BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
    });
  });

  it('passes the wrapper’s fixed message on (409, 429 and the rest)', async () => {
    mocks.startBacktest.mockResolvedValue({
      success: false,
      error: BACKTEST_ALREADY_RUNNING_MESSAGE,
      status: 409,
    });
    expect(await run(formOf())).toMatchObject({
      status: 'error',
      message: BACKTEST_ALREADY_RUNNING_MESSAGE,
      values: BACKTEST_DEFAULTS,
    });
  });

  it('turns a thrown wrapper error into the generic message', async () => {
    mocks.thrower = () => Promise.reject(new Error('boom'));
    expect(await run(formOf())).toMatchObject({ message: BACKTESTS_REQUEST_FAILED_MESSAGE });
  });
});

describe('pollBacktestAction', () => {
  it('returns the run status', async () => {
    mocks.fetchBacktest.mockResolvedValue({
      success: true,
      data: makeBacktest({ status: 'running' }),
    });
    expect(await pollBacktestAction(7)).toEqual({ ok: true, status: 'running' });
    expect(mocks.fetchBacktest).toHaveBeenCalledWith(7);
  });

  it('marks a missing run as gone and keeps a 429 wait', async () => {
    mocks.fetchBacktest.mockResolvedValue({
      success: false,
      error: BACKTEST_NOT_FOUND_MESSAGE,
      status: 404,
    });
    expect(await pollBacktestAction(7)).toEqual({
      ok: false,
      message: BACKTEST_NOT_FOUND_MESSAGE,
      gone: true,
    });
    mocks.fetchBacktest.mockResolvedValue({
      success: false,
      error: 'wait',
      status: 429,
      retryAfter: 20,
    });
    expect(await pollBacktestAction(7)).toEqual({
      ok: false,
      message: 'wait',
      gone: false,
      retryAfter: 20,
    });
  });

  it('rejects a bad id and survives a thrown error', async () => {
    expect(await pollBacktestAction(-1)).toMatchObject({ ok: false, gone: true });
    expect(mocks.fetchBacktest).not.toHaveBeenCalled();
    mocks.thrower = () => Promise.reject(new Error('boom'));
    expect(await pollBacktestAction(7)).toEqual({
      ok: false,
      message: BACKTESTS_REQUEST_FAILED_MESSAGE,
      gone: false,
    });
  });
});
