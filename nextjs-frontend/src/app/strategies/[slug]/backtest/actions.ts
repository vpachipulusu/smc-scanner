'use server';

import { fetchBacktest, startBacktest } from '@/lib/api/backtests';
import {
  BACKTEST_NOT_FOUND_MESSAGE,
  BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
  BACKTESTS_REQUEST_FAILED_MESSAGE,
} from '@/lib/api/backtests-messages';
import { parseBacktestForm, readBacktestValues } from '@/lib/backtests/form';
import type { BacktestPollResult, RunBacktestState } from '@/lib/backtests/state';
import { isStrategySlug } from '@/lib/scan/params';

/**
 * Server actions behind the backtest page: start a run (POST /backtests, 202) and poll one run's
 * status. The browser never calls the API; only allow-listed form fields are read and checked
 * (see `lib/backtests/form.ts`), and every failure comes back as a fixed message.
 */

export async function runBacktestAction(
  _previous: RunBacktestState,
  formData: FormData
): Promise<RunBacktestState> {
  const slug = formData.get('strategy');
  if (!isStrategySlug(slug)) {
    return {
      status: 'error',
      message: BACKTEST_UNKNOWN_STRATEGY_MESSAGE,
      errors: {},
      values: readBacktestValues(formData),
    };
  }
  const parsed = parseBacktestForm(formData);
  if (!parsed.ok) return { status: 'error', errors: parsed.errors, values: parsed.values };

  let result;
  try {
    result = await startBacktest({ ...parsed.body, strategy: slug });
  } catch {
    return {
      status: 'error',
      message: BACKTESTS_REQUEST_FAILED_MESSAGE,
      errors: {},
      values: parsed.values,
    };
  }
  if (!result.success) {
    return { status: 'error', message: result.error, errors: {}, values: parsed.values };
  }
  return { status: 'started', id: result.data.id, values: parsed.values };
}

/** The status of one run, for the page's poll after a start. */
export async function pollBacktestAction(id: number): Promise<BacktestPollResult> {
  if (!Number.isSafeInteger(id) || id < 1) {
    return { ok: false, message: BACKTEST_NOT_FOUND_MESSAGE, gone: true };
  }
  try {
    const result = await fetchBacktest(id);
    if (result.success) return { ok: true, status: result.data.status };
    return {
      ok: false,
      message: result.error,
      gone: result.status === 404,
      ...(result.retryAfter === undefined ? {} : { retryAfter: result.retryAfter }),
    };
  } catch {
    return { ok: false, message: BACKTESTS_REQUEST_FAILED_MESSAGE, gone: false };
  }
}
