import type { BacktestFieldErrors, BacktestFormValues } from './form';

/** State of the "Run backtest" form after a submit (useActionState). */
export type RunBacktestState =
  | { status: 'idle' }
  | {
      status: 'error';
      message?: string;
      errors: BacktestFieldErrors;
      values: BacktestFormValues;
    }
  | { status: 'started'; id: number; values: BacktestFormValues };

export const IDLE_RUN_BACKTEST_STATE: RunBacktestState = { status: 'idle' };

export type BacktestRunStatus = 'pending' | 'running' | 'done' | 'failed';

/** One poll of a run: its status, or why it could not be read (and how long to wait). */
export type BacktestPollResult =
  | { ok: true; status: BacktestRunStatus }
  | { ok: false; message: string; gone: boolean; retryAfter?: number };

export const isFinished = (status: BacktestRunStatus): boolean =>
  status === 'done' || status === 'failed';
