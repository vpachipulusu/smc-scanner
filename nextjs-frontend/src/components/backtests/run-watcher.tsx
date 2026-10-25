'use client';

import { useEffect, useRef, useState } from 'react';

import { pollBacktestAction } from '@/app/strategies/[slug]/backtest/actions';
import { BACKTESTS_REQUEST_FAILED_MESSAGE, retryDelayMs } from '@/lib/api/backtests-messages';
import { isFinished, type BacktestRunStatus } from '@/lib/backtests/state';

/**
 * Polls one run until it is done or failed, or turns out to be gone. The three backtest reads
 * share a 60 per minute bucket, so it asks every 5 seconds (later when the API says when to retry)
 * (at most five minutes) and not at all while the tab is hidden. A run that is gone is reported
 * to the parent, which shows it, since this unmounts once the run ends. Mount it with `key={id}` inside a live region so a new
 * run starts with a fresh, announced status line.
 */

export const POLL_INTERVAL_MS = 5000;
/** Consecutive failed polls (about a minute) before it stops asking and says so. */
export const MAX_FAILED_POLLS = 12;
export const POLL_STOPPED_MESSAGE =
  'Stopped checking after repeated errors. Reload the page to see how the run went.';

/** How a watched run ended: its final status, or `gone` when it no longer exists. */
export type RunOutcome = Extract<BacktestRunStatus, 'done' | 'failed'> | 'gone';

type RunWatcherProps = {
  id: number;
  /** The status the run is known to have (a just-started run is pending). */
  initialStatus?: BacktestRunStatus;
  onFinish: (id: number, outcome: RunOutcome) => void;
};

const isHidden = (): boolean =>
  typeof document !== 'undefined' && document.visibilityState === 'hidden';

export function RunWatcher({ id, initialStatus = 'pending', onFinish }: RunWatcherProps) {
  const [status, setStatus] = useState<BacktestRunStatus>(initialStatus);
  const [problem, setProblem] = useState<string | null>(null);
  const finish = useRef(onFinish);

  useEffect(() => {
    finish.current = onFinish;
  }, [onFinish]);

  useEffect(() => {
    let cancelled = false;
    let failures = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const schedule = (delay: number) => {
      timer = setTimeout(() => void tick(), delay);
    };
    const tick = async () => {
      if (isHidden()) {
        schedule(POLL_INTERVAL_MS);
        return;
      }
      let result;
      try {
        result = await pollBacktestAction(id);
      } catch {
        result = { ok: false as const, message: BACKTESTS_REQUEST_FAILED_MESSAGE, gone: false };
      }
      if (cancelled) return;
      if (result.ok) {
        failures = 0;
        setProblem(null);
        setStatus(result.status);
        if (result.status === 'done' || result.status === 'failed') {
          finish.current(id, result.status);
        } else {
          schedule(POLL_INTERVAL_MS);
        }
        return;
      }
      failures += 1;
      if (result.gone) {
        finish.current(id, 'gone');
        return;
      }
      if (failures >= MAX_FAILED_POLLS) {
        setProblem(POLL_STOPPED_MESSAGE);
        return;
      }
      setProblem(result.message);
      schedule(Math.max(POLL_INTERVAL_MS, retryDelayMs(result.retryAfter, POLL_INTERVAL_MS)));
    };
    schedule(POLL_INTERVAL_MS);
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [id]);

  const text = isFinished(status)
    ? `Backtest ${status === 'done' ? 'finished' : 'failed'}. Loading the results…`
    : `Backtest ${status === 'pending' ? 'queued' : 'running'}. Checking every ${POLL_INTERVAL_MS / 1000} seconds; this page updates when it ends.`;

  return (
    <div className="space-y-1 text-sm" data-testid="run-watcher">
      <p>{text}</p>
      {problem && <p className="text-xs text-warn-foreground">{problem}</p>}
    </div>
  );
}
