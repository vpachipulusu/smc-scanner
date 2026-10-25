'use client';

import { useRouter } from 'next/navigation';
import { useActionState, useCallback, useEffect, useRef, useState, type FormEvent } from 'react';

import { runBacktestAction } from '@/app/strategies/[slug]/backtest/actions';
import { BacktestRunFields } from '@/components/backtests/backtest-run-fields';
import { RunWatcher, type RunOutcome } from '@/components/backtests/run-watcher';
import { Button } from '@/components/ui/button';
import {
  BACKTEST_ALREADY_RUNNING_MESSAGE,
  BACKTEST_NOT_FOUND_MESSAGE,
} from '@/lib/api/backtests-messages';
import { BACKTEST_DEFAULTS } from '@/lib/backtests/form';
import { backtestHref } from '@/lib/backtests/routes';
import { IDLE_RUN_BACKTEST_STATE, type BacktestRunStatus } from '@/lib/backtests/state';

/**
 * "Run backtest" for one strategy, through a server action (POST /backtests, 202). While a run is
 * pending or running (just started here, or already listed) Run is unavailable and the run is
 * polled; when it ends the page moves to that run's results. Run stays focusable
 * (`aria-disabled`) so focus is not lost when it turns off. Failures (409 already running, 422,
 * 429 with its wait, 503) are announced in an alert region; progress in a status region. A 409
 * also re-reads the page, so the run started elsewhere shows up and keeps Run off.
 */

export const RUN_BUSY_HINT = 'One backtest runs at a time. Run is available again when it ends.';

type BacktestRunFormProps = {
  slug: string;
  /** A listed run that is pending or running, or null. */
  inFlightId: number | null;
  /** That run's listed status. */
  inFlightStatus?: BacktestRunStatus;
};

export function BacktestRunForm({ slug, inFlightId, inFlightStatus }: BacktestRunFormProps) {
  const router = useRouter();
  const [state, formAction, pending] = useActionState(runBacktestAction, IDLE_RUN_BACKTEST_STATE);
  const [finishedIds, setFinishedIds] = useState<ReadonlySet<number>>(() => new Set());
  // Shown once the watcher has gone: a watched run that no longer exists.
  const [goneNotice, setGoneNotice] = useState<string | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const startedId = state.status === 'started' ? state.id : null;
  // The run started here first, else any listed run in flight, unless it is known to have ended.
  const watchId = [startedId, inFlightId].find((id) => id !== null && !finishedIds.has(id)) ?? null;
  const busy = pending || watchId !== null;
  const values = state.status === 'idle' ? BACKTEST_DEFAULTS : state.values;
  const errors = state.status === 'error' ? state.errors : {};
  const message = state.status === 'error' ? state.message : undefined;
  // A 409: a run started elsewhere (another tab, a schedule) that the page does not list yet.
  const alreadyRunning = state.status === 'error' && message === BACKTEST_ALREADY_RUNNING_MESSAGE;

  // A started run, or the one behind a 409, shows up in the history once the page is read again;
  // the page then passes it in as `inFlightId` and Run turns off.
  useEffect(() => {
    if (startedId !== null || alreadyRunning) router.refresh();
  }, [startedId, alreadyRunning, state, router]);

  // After a failed submit, land on the first invalid field.
  useEffect(() => {
    if (state.status === 'error') {
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"]')?.focus();
    }
  }, [state]);

  const onFinish = useCallback(
    (id: number, outcome: RunOutcome) => {
      setFinishedIds((ids) => new Set([...ids, id]));
      setGoneNotice(outcome === 'gone' ? BACKTEST_NOT_FOUND_MESSAGE : null);
      const href = backtestHref(slug, id);
      // The page is dynamic: a navigation reads it afresh; the same URL needs a refresh instead.
      const here = `${window.location.pathname}${window.location.search}`;
      if (outcome === 'gone' || here === href) router.refresh();
      else router.replace(href, { scroll: false });
    },
    [router, slug]
  );

  const onSubmit = (event: FormEvent<HTMLFormElement>) => {
    if (busy) event.preventDefault();
  };

  return (
    <form
      ref={formRef}
      action={formAction}
      onSubmit={onSubmit}
      className="space-y-6"
      aria-label="Run backtest"
    >
      <input type="hidden" name="strategy" value={slug} />
      <BacktestRunFields
        key={state.status === 'idle' ? 'idle' : JSON.stringify(state.values)}
        values={values}
        errors={errors}
      />
      <div role="alert" className="text-sm text-crit-foreground">
        {message}
      </div>
      <div className="flex flex-wrap items-center gap-3">
        <Button
          type="submit"
          aria-disabled={busy}
          aria-describedby="backtest-run-hint"
          className="aria-disabled:pointer-events-none aria-disabled:opacity-50"
        >
          {pending ? 'Starting…' : 'Run backtest'}
        </Button>
        <p id="backtest-run-hint" className="text-xs text-muted-foreground">
          {watchId !== null ? RUN_BUSY_HINT : 'Runs in the background; you can leave this page.'}
        </p>
      </div>
      <div role="status">
        {watchId !== null ? (
          <RunWatcher
            key={watchId}
            id={watchId}
            initialStatus={watchId === inFlightId ? inFlightStatus : 'pending'}
            onFinish={onFinish}
          />
        ) : (
          goneNotice && <p className="text-sm text-warn-foreground">{goneNotice}</p>
        )}
      </div>
    </form>
  );
}
